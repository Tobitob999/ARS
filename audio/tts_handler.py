"""
audio/tts_handler.py — Text-to-Speech Handler

Backend-Hierarchie (auto-detected):
  1. "piper"       — Piper TTS (lokal, Deutsch: de_DE-thorsten-medium/high)
  2. "kokoro_onnx" — Kokoro-82M ONNX via kokoro-onnx (Englisch)
  3. "pyttsx3"     — System-TTS (offline-Fallback, Windows SAPI)
  4. "stub"        — stdout-Ausgabe (Dev / kein Audio-Device)

Features:
  - Sentence-Streaming: Sprachausgabe startet sobald der erste Satz fertig ist
  - Barge-in: threading.Event stoppt die Wiedergabe sofort wenn gesetzt
  - speak_streaming(): nimmt LLM-Text-Chunks entgegen, puffert bis Satzgrenze

Konfiguration via .env:
  PIPER_VOICE=de_DE-thorsten-medium  # Piper Stimmen-ID
  PIPER_SPEED=1.0                    # Sprechgeschwindigkeit
  KOKORO_VOICE=af_heart              # Kokoro Stimmen-ID (Englisch-Fallback)
  KOKORO_SPEED=1.0                   # Sprechgeschwindigkeit
  TTS_LANG=en-us                     # Sprach-Code fuer kokoro-onnx
"""

from __future__ import annotations

import logging
import os
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger("ARS.audio.tts")

KOKORO_SAMPLE_RATE = 24_000   # Hz — Kokoro-82M Output
PLAYBACK_CHUNK     = 2048     # Samples pro Playback-Iteration (Barge-in Granularität)

# Piper Model-Cache Verzeichnis
PIPER_MODEL_DIR = Path(__file__).parent.parent / "data" / "models" / "piper"

# Satzgrenzen-Regex: trennt nach . ! ? … gefolgt von Leerzeichen/Zeilenumbruch
SENTENCE_PATTERN = re.compile(r"(?<=[.!?…])\s+")

# Alle verfuegbaren deutschen Piper-Stimmen
VOICE_REGISTRY = {
    # --- Kernrollen ---
    "keeper":       "de_DE-thorsten-high",              # Standard Erzaehler (maennlich, klar)
    "woman":        "de_DE-kerstin-low",                # Weibliche NPCs
    "monster":      "de_DE-pavoque-low",                # Tiefe, raue Stimme (Antagonisten)
    "scholar":      "de_DE-karlsson-low",               # Akademiker / Investigator
    "mystery":      "de_DE-eva_k-x_low",                # Geister / Traumwesen (weiblich)
    # --- Erweiterte Stimmen ---
    "emotional":    "de_DE-thorsten_emotional-medium",   # Emotionaler Erzaehler
    "narrator":     "de_DE-thorsten-medium",             # Neutraler Erzaehler (medium quality)
    "villager":     "de_DE-ramona-low",                  # Dorfbewohnerin / Buerger (weiblich)
    "crowd":        "de_DE-mls-medium",                  # Generische Stimme / Statisten
    "whisper":      "de_DE-thorsten-low",                # Leise/Fluestern (low quality = rauer)
}
DEFAULT_VOICE = "keeper"

# Auswahl an vordefinierten Keeper-Stimmen (Archetypen)
KEEPER_VOICES = {
    "standard":   "de_DE-thorsten-high",              # Der klassische Erzaehler
    "emotional":  "de_DE-thorsten_emotional-medium",   # Emotionaler, dramatischer
    "mysterioes": "de_DE-eva_k-x_low",                # Geheimnisvoll, weiblich
    "sachlich":   "de_DE-karlsson-low",                # Praeziser, sachlicher
}


def split_sentences(text: str) -> list[str]:
    """Zerlegt Text in Sätze für Streaming-TTS."""
    return [s.strip() for s in SENTENCE_PATTERN.split(text) if s.strip()]


class TTSHandler:
    """
    Kokoro-82M TTS mit Sentence-Streaming und Barge-in Support.

    Öffentliche API:
      speak(text, stop_event)          → Blockiert; gibt True zurück wenn vollständig
      speak_streaming(iter, stop_event)→ Nimmt Text-Chunks vom LLM entgegen
      stop()                           → Unterbricht sofort
    """

    def __init__(self) -> None:
        # Keeper-Profil aus .env lesen und die Standard-Stimme setzen
        keeper_profile = os.getenv("KEEPER_VOICE_PROFILE", "standard").lower()
        default_keeper_voice_id = KEEPER_VOICES.get(keeper_profile, KEEPER_VOICES["standard"])
        
        # Aktualisiere die Standard-Keeper-Stimme in der Registry zur Laufzeit
        VOICE_REGISTRY["keeper"] = default_keeper_voice_id
        logger.info("Keeper-Stimmenprofil: '%s' -> %s", keeper_profile, default_keeper_voice_id)

        # Piper config
        self._piper_voice_id: str = VOICE_REGISTRY[DEFAULT_VOICE]
        self._piper_speed: float = float(os.getenv("PIPER_SPEED", "1.0"))
        self._piper_models: dict[str, Any] = {}  # Cache für geladene Modelle
        self._active_piper: Any = None           # Aktuell genutztes Modell
        self._piper_sample_rate: int = 22050
        self._piper_failed_voices: set[str] = set()  # Per-Voice Tracking statt globalem Flag
        # Kokoro config
        self._voice:    str = os.getenv("KOKORO_VOICE", "af_heart")
        self._speed:    float = float(os.getenv("KOKORO_SPEED", "1.0"))
        self._lang:     str = os.getenv("TTS_LANG", "en-us")
        self._kokoro:   Any = None          # kokoro_onnx.Kokoro Instanz
        self._kokoro_load_failed: bool = False
        self._engine:   Any = None          # pyttsx3
        self._stop_event = threading.Event()
        self._backend: str = self._detect_backend()
        logger.info("TTS initialisiert — Backend: %s", self._backend)

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def speak(self, text: str, stop_event: threading.Event | None = None) -> bool:
        """
        Spricht den gesamten Text.

        Intern: zerlegt in Sätze, synthesisiert + spielt jeden sofort.
        Returns True wenn vollständig, False wenn durch stop_event unterbrochen.
        """
        if not text.strip():
            return True

        evt = stop_event or self._stop_event
        evt.clear()

        sentences = split_sentences(text)
        if not sentences:
            sentences = [text.strip()]

        for sentence in sentences:
            if evt.is_set():
                logger.info("TTS unterbrochen vor Satz: '%s…'", sentence[:40])
                return False
            if not self._speak_sentence(sentence, evt):
                return False

        return True

    def set_voice(self, role: str) -> bool:
        """
        Wechselt die aktive Stimme basierend auf einer Rolle (keeper, monster, etc.).
        Lädt das Modell bei Bedarf nach.
        """
        if role not in VOICE_REGISTRY:
            logger.warning("Unbekannte Rolle '%s'. Bleibe bei aktueller Stimme.", role)
            return False
        
        target_id = VOICE_REGISTRY[role]
        self._piper_voice_id = target_id
        return True

    def speak_streaming(
        self,
        text_iter: Iterator[str],
        stop_event: threading.Event | None = None,
    ) -> bool:
        """
        Nimmt LLM-Text-Chunks entgegen und spricht Satz für Satz sobald
        eine Satzgrenze erkannt wird.

        Ermöglicht < 500ms First-Audio-Latenz beim Streaming-LLM.
        """
        evt = stop_event or self._stop_event
        evt.clear()

        buffer = ""
        for chunk in text_iter:
            if evt.is_set():
                return False

            buffer += chunk

            # Prüfe auf vollständige Sätze im Puffer
            parts = SENTENCE_PATTERN.split(buffer)
            if len(parts) > 1:
                # Alle vollständigen Sätze aussprechen (letzter Teil ist Reste-Puffer)
                for sentence in parts[:-1]:
                    sentence = sentence.strip()
                    if sentence:
                        if not self._speak_sentence(sentence, evt):
                            return False
                buffer = parts[-1]  # Rest für nächsten Chunk aufheben

        # Restlichen Puffer sprechen
        remainder = buffer.strip()
        if remainder and not evt.is_set():
            self._speak_sentence(remainder, evt)

        return not evt.is_set()

    def stop(self) -> None:
        """Unterbricht laufende TTS-Ausgabe sofort."""
        self._stop_event.set()
        logger.info("TTS gestoppt.")

    # ------------------------------------------------------------------
    # Satz-Synthese + Wiedergabe
    # ------------------------------------------------------------------

    def _speak_sentence(self, sentence: str, stop_event: threading.Event) -> bool:
        """
        Synthetisiert einen Satz und spielt ihn ab.
        Prüft stop_event zwischen Playback-Chunks (Barge-in Granularität).
        Returns True wenn vollständig abgespielt.
        """
        # NFC-Normalisierung: verhindert dass Umlaute (ü, ö, ä) als
        # zwei separate Vokale gesprochen werden (NFD → NFC)
        sentence = unicodedata.normalize("NFC", sentence)
        logger.debug("TTS: '%s…'", sentence[:50])

        if self._backend == "piper":
            return self._piper_speak(sentence, stop_event)
        elif self._backend == "kokoro_onnx":
            return self._kokoro_speak(sentence, stop_event)
        elif self._backend == "pyttsx3":
            if stop_event.is_set():
                return False
            self._pyttsx3_speak(sentence)
            return True
        else:
            if stop_event.is_set():
                return False
            print(f"[TTS] {sentence}")
            return True

    def _piper_speak(self, sentence: str, stop_event: threading.Event) -> bool:
        """Piper TTS Synthese + non-blocking Wiedergabe mit Barge-in Check."""
        try:
            import sounddevice as sd
            import numpy as np
            import time

            self._ensure_piper_loaded(self._piper_voice_id)
            if self._active_piper is None:
                # Downgrade zu Kokoro
                return self._kokoro_speak(sentence, stop_event)

            chunks = list(self._active_piper.synthesize(sentence))
            if not chunks:
                return True

            samples = np.concatenate([c.audio_float_array for c in chunks])
            sample_rate = chunks[0].sample_rate

            if stop_event.is_set():
                return False

            # Non-blocking play + poll für Barge-in
            sd.play(samples, samplerate=sample_rate, blocking=False)
            while sd.get_stream().active:
                if stop_event.is_set():
                    sd.stop()
                    logger.info("TTS Barge-in: Piper-Wiedergabe gestoppt.")
                    return False
                time.sleep(0.02)  # 20ms Poll-Intervall

            return True

        except Exception as exc:
            logger.error("Piper Wiedergabe-Fehler: %s — Downgrade zu Kokoro", exc)
            return self._kokoro_speak(sentence, stop_event)

    def _kokoro_speak(self, sentence: str, stop_event: threading.Event) -> bool:
        """Kokoro-82M (kokoro-onnx) Synthese + non-blocking Wiedergabe."""
        try:
            import sounddevice as sd
            import numpy as np
            import time

            self._ensure_kokoro_loaded()
            if self._kokoro is None:
                self._pyttsx3_speak(sentence)
                return True

            samples, sample_rate = self._kokoro.create(
                sentence,
                voice=self._voice,
                speed=self._speed,
                lang=self._lang,
            )

            if stop_event.is_set():
                return False

            # Non-blocking play + poll für Barge-in
            sd.play(samples, samplerate=sample_rate, blocking=False)
            while sd.get_stream().active:
                if stop_event.is_set():
                    sd.stop()
                    logger.info("TTS Barge-in: Kokoro-Wiedergabe gestoppt.")
                    return False
                time.sleep(0.02)

            return True

        except Exception as exc:
            logger.error("Kokoro-ONNX Wiedergabe-Fehler: %s", exc)
            self._pyttsx3_speak(sentence)
            return True

    def _pyttsx3_speak(self, text: str) -> None:
        try:
            import pyttsx3  # type: ignore[import]

            if self._engine is None:
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", 160)
                self._engine.setProperty("volume", 0.9)
                for v in self._engine.getProperty("voices"):
                    langs = v.languages if v.languages else []
                    if any("german" in str(l).lower() for l in langs):
                        self._engine.setProperty("voice", v.id)
                        break

            self._engine.say(text)
            self._engine.runAndWait()

        except Exception as exc:
            logger.error("pyttsx3 Fehler: %s", exc)
            print(f"[TTS-Stub] {text}")

    # ------------------------------------------------------------------
    # Model-Lazy-Loading
    # ------------------------------------------------------------------

    def _ensure_piper_loaded(self, voice_id: str) -> None:
        """
        Laedt ein spezifisches Piper TTS Modell (lazy).
        Wechselt self._active_piper auf das angeforderte Modell.
        """
        if voice_id in self._piper_failed_voices:
            return

        # Check Cache
        if voice_id in self._piper_models:
            self._active_piper = self._piper_models[voice_id]
            return

        try:
            import urllib.request
            from piper import PiperVoice  # type: ignore[import]

            PIPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)

            # Pfade konstruieren
            # Stimmen-ID zerlegen: de_DE-thorsten-medium → de/de_DE/thorsten/medium
            # Beachte: Manche IDs haben Unterstriche im Speaker/Quality,
            # z.B. de_DE-eva_k-x_low → de/de_DE/eva_k/x_low
            # Strategie: lang_code ist alles vor dem ersten "-",
            # dann Quality-Suffix von hinten matchen (bekannte Werte).
            first_dash = voice_id.index("-")
            lang_code = voice_id[:first_dash]          # de_DE
            lang_short = lang_code[:2]                  # de
            remainder = voice_id[first_dash + 1:]       # thorsten-medium / eva_k-x_low

            # Quality von hinten matchen: x_low, low, medium, high
            _quality_suffixes = ("-x_low", "-low", "-medium", "-high")
            speaker = remainder
            quality = "medium"
            for suffix in _quality_suffixes:
                if remainder.endswith(suffix):
                    quality = suffix[1:]  # ohne führendes "-"
                    speaker = remainder[: -len(suffix)]
                    break

            model_file = f"{voice_id}.onnx"
            config_file = f"{voice_id}.onnx.json"
            model_path = PIPER_MODEL_DIR / model_file
            config_path = PIPER_MODEL_DIR / config_file

            BASE_URL = (
                f"https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                f"{lang_short}/{lang_code}/{speaker}/{quality}/"
            )

            for fname, fpath in [
                (model_file, model_path),
                (config_file, config_path),
            ]:
                if not fpath.exists():
                    url = BASE_URL + fname
                    logger.info("Lade Piper-Datei '%s' von HuggingFace...", fname)
                    urllib.request.urlretrieve(url, fpath)
                    size_mb = fpath.stat().st_size // 1_000_000
                    logger.info("'%s' heruntergeladen (%d MB).", fname, size_mb)
                else:
                    logger.debug("Piper-Datei '%s' bereits im Cache.", fname)

            # Laden und Cachen
            voice = PiperVoice.load(str(model_path), config_path=str(config_path))
            self._piper_models[voice_id] = voice
            self._active_piper = voice
            logger.info("Piper Stimme geladen: %s", voice_id)

        except Exception as exc:
            logger.warning("Piper Laden für '%s' fehlgeschlagen: %s", voice_id, exc)
            self._piper_failed_voices.add(voice_id)

    def _ensure_kokoro_loaded(self) -> None:
        """
        Laedt Kokoro-82M ONNX Modell v1.0 (lazy).

        Modell-Dateien (kokoro-v1.0.onnx + voices-v1.0.bin) werden einmalig
        von GitHub Releases heruntergeladen und in data/models/ gecacht.
        Bei erneutem Start werden die lokalen Dateien direkt verwendet.
        """
        if self._kokoro is not None or self._kokoro_load_failed:
            return
        try:
            import urllib.request

            # Lokaler Modell-Cache
            model_dir = Path(__file__).parent.parent / "data" / "models"
            model_dir.mkdir(parents=True, exist_ok=True)

            model_path  = model_dir / "kokoro-v1.0.onnx"
            voices_path = model_dir / "voices-v1.0.bin"

            BASE_URL = (
                "https://github.com/thewh1teagle/kokoro-onnx"
                "/releases/download/model-files-v1.0/"
            )

            for fname, fpath in [
                ("kokoro-v1.0.onnx", model_path),
                ("voices-v1.0.bin",  voices_path),
            ]:
                if not fpath.exists():
                    url = BASE_URL + fname
                    logger.info(
                        "Lade Kokoro-Datei '%s' (~%s) von GitHub Releases...",
                        fname,
                        "300 MB" if "onnx" in fname else "10 MB",
                    )
                    urllib.request.urlretrieve(url, fpath)
                    size_mb = fpath.stat().st_size // 1_000_000
                    logger.info("'%s' heruntergeladen (%d MB).", fname, size_mb)
                else:
                    logger.debug("Kokoro-Datei '%s' bereits im Cache.", fname)

            self._kokoro = Kokoro(str(model_path), str(voices_path))
            logger.info("Kokoro-82M v1.0 bereit.")

        except Exception as exc:
            logger.warning(
                "Kokoro-ONNX Laden fehlgeschlagen: %s — Fallback auf pyttsx3.", exc
            )
            self._kokoro = None
            self._kokoro_load_failed = True

    # ------------------------------------------------------------------
    # Backend-Erkennung
    # ------------------------------------------------------------------

    def _detect_backend(self) -> str:
        try:
            import piper  # type: ignore[import]  # noqa: F401
            import sounddevice  # type: ignore[import]  # noqa: F401
            return "piper"
        except ImportError:
            pass
        try:
            import kokoro_onnx  # type: ignore[import]  # noqa: F401
            import sounddevice  # type: ignore[import]  # noqa: F401
            return "kokoro_onnx"
        except ImportError:
            pass
        try:
            import pyttsx3  # type: ignore[import]  # noqa: F401
            return "pyttsx3"
        except ImportError:
            pass
        logger.warning(
            "Kein TTS-Backend installiert — Stub-Modus. "
            "Installation: pip install piper-tts sounddevice"
        )
        return "stub"
