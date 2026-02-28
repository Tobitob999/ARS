"""
audio/pipeline.py — VoicePipeline

Koordiniert STTHandler und TTSHandler für den vollständigen Voice-Loop:

  listen() → [Mikrofon] → Silero VAD → Faster-Whisper → Text
  speak()  → Text → Kokoro-82M → [Lautsprecher]
               ↕ (gleichzeitig)
           Barge-in Monitor: VAD überwacht Mikrofon während TTS spielt
           Wenn Spieler spricht → stop_event gesetzt → TTS stoppt sofort

Latenz-Budget (schneller lokaler Rechner):
  VAD-Stille-Erkennung:  ~800ms  (25 Chunks × 32ms)
  Faster-Whisper base:   ~200ms
  Kokoro First-Audio:    ~100ms
  ─────────────────────────────
  Gesamt Speech→Audio:   ~1.1s  (Ziel: < 1s mit small-GPU oder tiny-CPU)
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING, Iterator

from audio.stt_handler import STTHandler
from audio.tts_handler import TTSHandler

if TYPE_CHECKING:
    pass

logger = logging.getLogger("ARS.audio.pipeline")

# VAD-Konfidenz-Schwelle während TTS-Wiedergabe.
# Höher als STT-Threshold um Echo/Bleed-Through von Lautsprechern zu ignorieren.
BARGEIN_VAD_THRESHOLD = 0.90

# Anzahl aufeinander folgender VAD-positiver Chunks bevor Barge-in ausgelöst wird.
BARGEIN_CONSECUTIVE = 2

# Cooldown-Chunks am Anfang des Monitors (~480ms bei 16kHz/512).
# Ignoriert Restsignal vom Mikrofon nach STT-Phase.
COOLDOWN_CHUNKS = 15


class VoicePipeline:
    """
    Zentrale Koordinationsklasse für den Voice-Game-Loop.

    Wird von SimulatorEngine instanziiert (enable_voice()).
    Der Orchestrator ruft listen() und speak() auf.

    Barge-in Mechanismus (optional, barge_in=True):
      speak() startet parallel einen Barge-in-Monitor-Thread.
      Dieser Thread öffnet einen zweiten InputStream auf dem Mikrofon
      und prüft jeden Chunk mit Silero VAD.
      Bei Sprach-Erkennung > BARGEIN_VAD_THRESHOLD (2 consecutive Chunks)
      wird _barge_in_event gesetzt.
      Das TTS-Handler-speak() prüft das Event zwischen Playback-Chunks.
    """

    def __init__(
        self,
        stt: STTHandler | None = None,
        tts: TTSHandler | None = None,
        barge_in: bool = True,
    ) -> None:
        self.stt = stt or STTHandler()
        self.tts = tts or TTSHandler()
        self._barge_in = barge_in
        self._barge_in_event = threading.Event()
        logger.info(
            "VoicePipeline bereit — STT: %s | TTS: %s | Barge-in: %s",
            self.stt._backend,
            self.tts._backend,
            "AN" if barge_in else "AUS",
        )

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def listen(self) -> str | None:
        """
        Lauscht auf Spieler-Sprache und gibt transkribierten Text zurück.
        Blockiert bis Sprechende erkannt.
        """
        self._barge_in_event.clear()
        return self.stt.listen()

    def speak(self, text: str) -> bool:
        """
        Spricht Text mit optionalem Barge-in Support.

        Bei barge_in=True:
          - TTS-Wiedergabe (Hauptthread blockiert)
          - Barge-in-Monitor (Daemon-Thread überwacht Mikrofon)
        Bei barge_in=False:
          - Nur TTS-Wiedergabe, kein Mikrofon-Monitoring

        Returns True wenn vollständig abgespielt, False wenn unterbrochen.
        """
        self._barge_in_event.clear()

        monitor = None
        if self._barge_in:
            monitor = threading.Thread(
                target=self._run_barge_in_monitor,
                daemon=True,
                name="ars-bargein-monitor",
            )
            monitor.start()

        try:
            completed = self.tts.speak(text, stop_event=self._barge_in_event)
        finally:
            if monitor is not None:
                self._barge_in_event.set()
                monitor.join(timeout=1.0)

        return completed

    def speak_streaming(self, text_iter: Iterator[str]) -> bool:
        """
        Wie speak(), aber nimmt LLM-Streaming-Chunks entgegen.
        Startet TTS sobald erster vollständiger Satz vorliegt.
        """
        self._barge_in_event.clear()

        monitor = None
        if self._barge_in:
            monitor = threading.Thread(
                target=self._run_barge_in_monitor,
                daemon=True,
                name="ars-bargein-monitor",
            )
            monitor.start()

        try:
            completed = self.tts.speak_streaming(text_iter, stop_event=self._barge_in_event)
        finally:
            if monitor is not None:
                self._barge_in_event.set()
                monitor.join(timeout=1.0)

        return completed

    # ------------------------------------------------------------------
    # Barge-in Monitor (Daemon-Thread)
    # ------------------------------------------------------------------

    def _run_barge_in_monitor(self) -> None:
        """
        Öffnet einen separaten InputStream und überwacht das Mikrofon mit
        Silero VAD während die TTS-Wiedergabe läuft.

        Beendet sich wenn _barge_in_event gesetzt wird (durch TTS-Ende
        oder eigene Sprach-Erkennung).
        """
        if self.tts._backend == "stub":
            # Im Stub-Modus kein Audio-Device vorhanden
            return

        try:
            import sounddevice as sd
            import torch
        except ImportError:
            logger.debug("Barge-in Monitor: sounddevice/torch nicht verfügbar.")
            return

        # VAD-Modell laden (nutzt torch-Cache, kein erneuter Download)
        try:
            if self.stt._vad_model is not None:
                vad_model = self.stt._vad_model
            else:
                try:
                    from silero_vad import load_silero_vad  # type: ignore[import]
                    vad_model = load_silero_vad()
                except ImportError:
                    vad_model, _ = torch.hub.load(
                        "snakers4/silero-vad",
                        "silero_vad",
                        force_reload=False,
                        trust_repo=True,
                    )
                vad_model.eval()
        except Exception as exc:
            logger.warning("Barge-in Monitor: VAD konnte nicht geladen werden: %s", exc)
            return

        audio_queue: queue.Queue = queue.Queue(maxsize=50)
        SAMPLE_RATE = 16_000
        CHUNK = 512

        def _callback(indata, frames, time, status) -> None:
            if not audio_queue.full():
                audio_queue.put_nowait(indata.copy())

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK,
                callback=_callback,
            ):
                logger.debug("Barge-in Monitor gestartet.")
                chunk_index = 0
                consecutive_speech = 0
                while not self._barge_in_event.is_set():
                    try:
                        chunk = audio_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    chunk_index += 1

                    # Cooldown: Restsignal nach STT-Phase ignorieren
                    if chunk_index <= COOLDOWN_CHUNKS:
                        continue

                    tensor = torch.from_numpy(chunk.flatten()).unsqueeze(0)
                    with torch.no_grad():
                        confidence: float = vad_model(tensor, SAMPLE_RATE).item()

                    if confidence >= BARGEIN_VAD_THRESHOLD:
                        consecutive_speech += 1
                        if consecutive_speech >= BARGEIN_CONSECUTIVE:
                            logger.info(
                                "Barge-in erkannt! VAD-Konfidenz: %.2f (%dx) — TTS gestoppt.",
                                confidence, consecutive_speech,
                            )
                            self._barge_in_event.set()
                            break
                    else:
                        consecutive_speech = 0

        except Exception as exc:
            logger.warning("Barge-in Monitor Fehler: %s", exc)

        logger.debug("Barge-in Monitor beendet.")
