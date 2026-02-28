"""
audio/stt_handler.py — Speech-to-Text Handler

Backend-Hierarchie (auto-detected):
  1. "faster_whisper"  — Faster-Whisper + Silero VAD  (production)
  2. "stub"            — stdin-Eingabe                (kein Mikrofon / Dev)

Silero VAD erkennt automatisch das Ende der Sprache (kein Tastendruck nötig).
Faster-Whisper transkribiert auf CPU mit int8-Quantisierung (~5-10x schneller
als original Whisper).

Konfiguration via .env:
  WHISPER_MODEL=base   # tiny | base | small | medium | large-v3
  STT_LANGUAGE=de      # ISO-639-1 Sprachcode
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from typing import Any

logger = logging.getLogger("ARS.audio.stt")

SAMPLE_RATE = 16_000      # Hz — Silero VAD und Whisper Standard
CHUNK_SIZE  = 512         # Samples pro Chunk ~32ms bei 16kHz (Silero VAD Pflicht)
VAD_THRESHOLD     = 0.5   # Konfidenz ab der Sprache erkannt wird
MAX_SILENCE_CHUNKS = 25   # ~800ms Stille = Äußerung beendet
MAX_SPEECH_SECONDS = 30   # Sicherheits-Timeout gegen endlose Aufnahme


class STTHandler:
    """
    Faster-Whisper STT mit Silero VAD für automatische Sprachgrenzenerkennung.

    Öffentliche API:
      listen()          → Blockiert bis Sprache erkannt + transkribiert (str | None)
      transcribe_file() → Transkribiert Audio-Datei direkt
    """

    def __init__(self) -> None:
        self._model_size: str = os.getenv("WHISPER_MODEL", "base")
        self._language:   str = os.getenv("STT_LANGUAGE", "de")
        self._whisper:    Any = None
        self._vad_model:  Any = None
        self._backend:    str = self._detect_backend()
        logger.info("STT initialisiert — Backend: %s | Modell: %s", self._backend, self._model_size)

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def listen(self) -> str | None:
        """
        Lauscht auf das Mikrofon und gibt den transkribierten Text zurück.

        Im faster_whisper-Modus: Silero VAD erkennt automatisch Sprachstart
        und -ende. Kein Tastendruck nötig.
        Im Stub-Modus: liest Text von stdin.
        """
        if self._backend == "faster_whisper":
            return self._vad_listen()
        return self._stub_listen()

    def transcribe_file(self, path: str) -> str | None:
        """Transkribiert eine Audio-Datei direkt (WAV/FLAC/MP3)."""
        if self._backend != "faster_whisper":
            logger.warning("transcribe_file nur im faster_whisper-Modus verfügbar.")
            return None
        try:
            self._ensure_models_loaded()
            segments, _ = self._whisper.transcribe(path, language=self._language)
            return " ".join(s.text for s in segments).strip() or None
        except Exception as exc:
            logger.error("transcribe_file Fehler: %s", exc)
            return None

    # ------------------------------------------------------------------
    # VAD-basierter Aufnahme-Loop
    # ------------------------------------------------------------------

    def _vad_listen(self) -> str | None:
        """
        Kernlogik:
          1. Öffnet Mikrofon-Stream (non-blocking callback)
          2. Schiebt 512-Sample-Chunks in eine Queue
          3. Silero VAD prüft jeden Chunk auf Sprache
          4. Puffert Sprach-Audio; stoppt nach MAX_SILENCE_CHUNKS stiller Chunks
          5. Faster-Whisper transkribiert den Puffer
        """
        try:
            import sounddevice as sd
            import numpy as np
            import torch
        except ImportError as exc:
            logger.error("Abhängigkeit fehlt: %s — Fallback auf Stub", exc)
            return self._stub_listen()

        self._ensure_models_loaded()

        audio_queue: queue.Queue = queue.Queue()

        def _callback(indata: Any, frames: int, time: Any, status: Any) -> None:
            if status:
                logger.debug("sd.InputStream Status: %s", status)
            audio_queue.put(indata.copy())

        speech_chunks: list[Any] = []
        in_speech = False
        silence_count = 0
        max_chunks = MAX_SPEECH_SECONDS * SAMPLE_RATE // CHUNK_SIZE

        logger.info("Hoere zu...")
        print("[STT] Ich hoere... (sprich jetzt)")

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_SIZE,
                callback=_callback,
            ):
                chunk_count = 0
                while chunk_count < max_chunks:
                    try:
                        chunk = audio_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue

                    chunk_flat = chunk.flatten()
                    chunk_count += 1

                    # Silero VAD Konfidenz
                    tensor = torch.from_numpy(chunk_flat).unsqueeze(0)
                    with torch.no_grad():
                        confidence: float = self._vad_model(tensor, SAMPLE_RATE).item()

                    is_speech = confidence >= VAD_THRESHOLD

                    if is_speech:
                        speech_chunks.append(chunk_flat)
                        in_speech = True
                        silence_count = 0
                    elif in_speech:
                        speech_chunks.append(chunk_flat)
                        silence_count += 1
                        if silence_count >= MAX_SILENCE_CHUNKS:
                            logger.debug("Stille erkannt — Aufnahme beendet.")
                            break

        except Exception as exc:
            logger.error("Mikrofon-Fehler: %s", exc)
            return self._stub_listen()

        if not speech_chunks:
            logger.info("Keine Sprache erkannt.")
            return None

        audio = np.concatenate(speech_chunks)
        return self._transcribe(audio)

    # ------------------------------------------------------------------
    # Transkription
    # ------------------------------------------------------------------

    def _transcribe(self, audio: Any) -> str | None:
        """Ruft Faster-Whisper auf einem numpy-Float32-Array auf."""
        try:
            segments, info = self._whisper.transcribe(
                audio,
                language=self._language,
                beam_size=5,
                vad_filter=False,   # eigenes VAD bereits erfolgt
            )
            text = " ".join(s.text for s in segments).strip()
            logger.info("STT: '%s'", text[:80])
            return text or None
        except Exception as exc:
            logger.error("Faster-Whisper Transkriptionsfehler: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Model-Lazy-Loading
    # ------------------------------------------------------------------

    def _ensure_models_loaded(self) -> None:
        if self._whisper is None:
            from faster_whisper import WhisperModel  # type: ignore[import]
            logger.info("Lade Faster-Whisper '%s' (CPU int8)...", self._model_size)
            self._whisper = WhisperModel(
                self._model_size, device="cpu", compute_type="int8"
            )
            logger.info("Faster-Whisper bereit.")

        if self._vad_model is None:
            import torch  # type: ignore[import]
            logger.info("Lade Silero VAD...")
            try:
                # Primär: silero-vad pip-Paket
                from silero_vad import load_silero_vad  # type: ignore[import]
                self._vad_model = load_silero_vad()
            except ImportError:
                # Fallback: torch.hub
                self._vad_model, _ = torch.hub.load(
                    "snakers4/silero-vad",
                    "silero_vad",
                    force_reload=False,
                    trust_repo=True,
                )
            self._vad_model.eval()
            logger.info("Silero VAD bereit.")

    # ------------------------------------------------------------------
    # Backend-Erkennung & Stub
    # ------------------------------------------------------------------

    def _detect_backend(self) -> str:
        try:
            import faster_whisper  # type: ignore[import]  # noqa: F401
            import torch           # type: ignore[import]  # noqa: F401
            import sounddevice     # type: ignore[import]  # noqa: F401
            return "faster_whisper"
        except ImportError:
            logger.warning(
                "faster-whisper / torch / sounddevice nicht installiert — "
                "STT laeuft im Stub-Modus. "
                "Installation: pip install faster-whisper torch sounddevice"
            )
            return "stub"

    def _stub_listen(self) -> str | None:
        """Stub: liest Text von stdin (Dev/Test ohne Mikrofon)."""
        try:
            text = input("[STT-Stub] Sprache simulieren > ").strip()
            return text or None
        except (EOFError, KeyboardInterrupt):
            return None
