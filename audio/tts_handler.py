"""
audio/tts_handler.py — Text-to-Speech Handler

Backend-Hierarchie (auto-detected):
  1. "piper"       — Piper TTS (lokal, Deutsch: de_DE-thorsten-medium/high)
  2. "edge"        — Microsoft Edge Neural TTS (online, kostenlos, 8+ deutsche Stimmen)
  3. "kokoro_onnx" — Kokoro-82M ONNX via kokoro-onnx (Englisch)
  4. "pyttsx3"     — System-TTS (offline-Fallback, Windows SAPI)
  5. "stub"        — stdout-Ausgabe (Dev / kein Audio-Device)

Features:
  - Sentence-Streaming: Sprachausgabe startet sobald der erste Satz fertig ist
  - Barge-in: threading.Event stoppt die Wiedergabe sofort wenn gesetzt
  - speak_streaming(): nimmt LLM-Text-Chunks entgegen, puffert bis Satzgrenze
  - Audio-Effekte: Reverb, Distortion, Filter etc. via pedalboard (optional)
  - 18 Stimmenrollen: 10 Piper (offline) + 8 Edge (online, neural)

Konfiguration via .env:
  PIPER_VOICE=de_DE-thorsten-medium  # Piper Stimmen-ID
  PIPER_SPEED=1.0                    # Sprechgeschwindigkeit
  KOKORO_VOICE=af_heart              # Kokoro Stimmen-ID (Englisch-Fallback)
  KOKORO_SPEED=1.0                   # Sprechgeschwindigkeit
  TTS_LANG=en-us                     # Sprach-Code fuer kokoro-onnx
  EDGE_TTS_ENABLED=1                 # Edge TTS aktivieren (default: 1)
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
PLAYBACK_CHUNK     = 2048     # Samples pro Playback-Iteration (Barge-in Granularitaet)

# Piper Model-Cache Verzeichnis
PIPER_MODEL_DIR = Path(__file__).parent.parent / "data" / "models" / "piper"

# Satzgrenzen-Regex: trennt nach . ! ? … gefolgt von Leerzeichen/Zeilenumbruch
SENTENCE_PATTERN = re.compile(r"(?<=[.!?…])\s+")

# ── Stimmenregister: Piper (offline) + Edge (online) ──

VOICE_REGISTRY = {
    # --- Piper Stimmen (offline) ---
    "keeper":       "de_DE-thorsten-high",              # Standard Erzaehler (maennlich, klar)
    "woman":        "de_DE-kerstin-low",                # Weibliche NPCs
    "monster":      "de_DE-pavoque-low",                # Tiefe, raue Stimme (Antagonisten)
    "scholar":      "de_DE-karlsson-low",               # Akademiker / Investigator
    "mystery":      "de_DE-eva_k-x_low",                # Geister / Traumwesen (weiblich)
    "emotional":    "de_DE-thorsten_emotional-medium",   # Emotionaler Erzaehler
    "narrator":     "de_DE-thorsten-medium",             # Neutraler Erzaehler (medium quality)
    "villager":     "de_DE-ramona-low",                  # Dorfbewohnerin / Buerger (weiblich)
    "crowd":        "de_DE-mls-medium",                  # Generische Stimme / Statisten
    "whisper":      "de_DE-thorsten-low",                # Leise/Fluestern (low quality = rauer)
    # --- Edge Stimmen (online, neural) ---
    "child":        "edge:de-DE-GiselaNeural",           # Kind / junge Stimme
    "noble":        "edge:de-DE-RalfNeural",             # Adliger / Wuerdentraeger
    "merchant":     "edge:de-CH-LeniNeural",             # Haendlerin (Schweizer Akzent)
    "austrian":     "edge:de-AT-JonasNeural",            # Oesterreichischer Akzent
    "priestess":    "edge:de-AT-IngridNeural",           # Priesterin / Heilige
    "commander":    "edge:de-DE-KillianNeural",          # Kommandant / Militaer
    "servant":      "edge:de-DE-AmalaNeural",            # Diener / unterwuerfig
    "herald":       "edge:de-DE-ConradNeural",           # Herold / Ausrufer
}
DEFAULT_VOICE = "keeper"

# Fallback-Mapping: Edge-Rolle → naechstbeste Piper-Stimme (wenn offline)
EDGE_FALLBACK = {
    "child":     "de_DE-kerstin-low",        # woman
    "noble":     "de_DE-karlsson-low",        # scholar
    "merchant":  "de_DE-ramona-low",          # villager
    "austrian":  "de_DE-thorsten-medium",     # narrator
    "priestess": "de_DE-eva_k-x_low",        # mystery
    "commander": "de_DE-pavoque-low",         # monster
    "servant":   "de_DE-kerstin-low",         # woman
    "herald":    "de_DE-thorsten-high",       # keeper
}

# Auswahl an vordefinierten Keeper-Stimmen (Archetypen)
KEEPER_VOICES = {
    "standard":   "de_DE-thorsten-high",              # Der klassische Erzaehler
    "emotional":  "de_DE-thorsten_emotional-medium",   # Emotionaler, dramatischer
    "mysterioes": "de_DE-eva_k-x_low",                # Geheimnisvoll, weiblich
    "sachlich":   "de_DE-karlsson-low",                # Praeziser, sachlicher
}

# Deutsche Abkuerzungen fuer TTS-Expansion
_ABBREVIATIONS = {
    "z.B.":  "zum Beispiel",
    "z. B.": "zum Beispiel",
    "d.h.":  "das heisst",
    "d. h.": "das heisst",
    "u.a.":  "unter anderem",
    "u. a.": "unter anderem",
    "o.ae.": "oder aehnliches",
    "o. ae.":"oder aehnliches",
    "bzw.":  "beziehungsweise",
    "ca.":   "circa",
    "etc.":  "et cetera",
    "evtl.": "eventuell",
    "ggf.":  "gegebenenfalls",
    "inkl.": "inklusive",
    "Nr.":   "Nummer",
    "usw.":  "und so weiter",
    "vgl.":  "vergleiche",
}


def _preprocess_german(text: str) -> str:
    """
    Bereinigt Text fuer deutsche TTS-Synthese.

    1. NFC-Normalisierung (Umlaute als precomposed)
    2. Unicode-Ersetzungen (Dashes, Smart Quotes, Ellipsis)
    3. Deutsche Abkuerzungen expandieren
    4. Control-Characters entfernen (ausser \\n, \\t)
    5. Verbleibende Combining Marks (Mn) entfernen
    """
    # 1. NFC — Umlaute als einzelne Zeichen
    text = unicodedata.normalize("NFC", text)

    # 2. Unicode-Sonderzeichen → ASCII-Aequivalente
    text = text.replace("\u2013", "-")    # En-Dash
    text = text.replace("\u2014", " - ")  # Em-Dash
    text = text.replace("\u2018", "'")    # Left single quote
    text = text.replace("\u2019", "'")    # Right single quote
    text = text.replace("\u201C", '"')    # Left double quote
    text = text.replace("\u201D", '"')    # Right double quote
    text = text.replace("\u2026", "...")   # Ellipsis
    text = text.replace("\u00AD", "")     # Soft Hyphen
    text = text.replace("\u200B", "")     # Zero-Width Space
    text = text.replace("\uFEFF", "")     # BOM

    # 3. Abkuerzungen expandieren (laengste zuerst)
    for abbr, expansion in _ABBREVIATIONS.items():
        text = text.replace(abbr, expansion)

    # 4. Control-Characters entfernen (Kategorie C), Newline/Tab behalten
    text = "".join(
        c for c in text
        if c in ("\n", "\t") or not unicodedata.category(c).startswith("C")
    )

    # 5. Verbleibende Combining Marks entfernen (nach NFC sind Umlaute safe)
    text = "".join(
        c for c in text
        if unicodedata.category(c) != "Mn"
    )

    return text


def split_sentences(text: str) -> list[str]:
    """Zerlegt Text in Saetze fuer Streaming-TTS."""
    return [s.strip() for s in SENTENCE_PATTERN.split(text) if s.strip()]


class TTSHandler:
    """
    Multi-Backend TTS mit Sentence-Streaming, Barge-in und Audio-Effekten.

    Oeffentliche API:
      speak(text, stop_event)          -> Blockiert; gibt True zurueck wenn vollstaendig
      speak_streaming(iter, stop_event)-> Nimmt Text-Chunks vom LLM entgegen
      set_voice(role)                  -> Wechselt Stimme + Effekt-Preset
      set_effect(preset)               -> Wechselt Effekt-Preset manuell
      stop()                           -> Unterbricht sofort
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
        self._piper_models: dict[str, Any] = {}  # Cache fuer geladene Modelle
        self._active_piper: Any = None            # Aktuell genutztes Modell
        self._piper_sample_rate: int = 22050
        self._piper_failed_voices: set[str] = set()  # Per-Voice Tracking

        # Edge TTS config
        self._edge_available: bool | None = None
        self._current_edge_voice: str = "de-DE-ConradNeural"

        # Kokoro config
        self._voice:    str = os.getenv("KOKORO_VOICE", "af_heart")
        self._speed:    float = float(os.getenv("KOKORO_SPEED", "1.0"))
        self._lang:     str = os.getenv("TTS_LANG", "en-us")
        self._kokoro:   Any = None          # kokoro_onnx.Kokoro Instanz
        self._kokoro_load_failed: bool = False
        self._engine:   Any = None          # pyttsx3
        self._stop_event = threading.Event()

        # Audio-Effekte
        self._current_preset: str = "clean"
        self._effects: Any = None
        self._effects_loaded: bool = False

        # Aktive Rolle (fuer Backend-Routing)
        self._current_role: str = DEFAULT_VOICE

        self._backend: str = self._detect_backend()
        logger.info("TTS initialisiert — Backend: %s", self._backend)

    def _ensure_effects(self) -> Any:
        """Lazy-Load der AudioEffects Instanz."""
        if not self._effects_loaded:
            self._effects_loaded = True
            try:
                from audio.effects import AudioEffects
                self._effects = AudioEffects()
                logger.info("AudioEffects geladen.")
            except Exception as exc:
                logger.warning("AudioEffects nicht verfuegbar: %s", exc)
                self._effects = None
        return self._effects

    def _apply_effects(self, samples, sample_rate: int):
        """Wendet das aktive Effekt-Preset auf Samples an."""
        if self._current_preset == "clean":
            return samples
        fx = self._ensure_effects()
        if fx is None:
            return samples
        return fx.apply(samples, sample_rate, self._current_preset)

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    def speak(self, text: str, stop_event: threading.Event | None = None) -> bool:
        """
        Spricht den gesamten Text.

        Intern: zerlegt in Saetze, synthesisiert + spielt jeden sofort.
        Returns True wenn vollstaendig, False wenn durch stop_event unterbrochen.
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
                logger.info("TTS unterbrochen vor Satz: '%s...'", sentence[:40])
                return False
            if not self._speak_sentence(sentence, evt):
                return False

        return True

    def set_voice(self, role: str) -> bool:
        """
        Wechselt die aktive Stimme basierend auf einer Rolle (keeper, monster, etc.).
        Setzt auch das zugehoerige Effekt-Preset.
        """
        if role not in VOICE_REGISTRY:
            logger.warning("Unbekannte Rolle '%s'. Bleibe bei aktueller Stimme.", role)
            return False

        target_id = VOICE_REGISTRY[role]
        self._current_role = role

        if target_id.startswith("edge:"):
            self._current_edge_voice = target_id[5:]
            # Piper-Fallback setzen falls Edge offline
            if role in EDGE_FALLBACK:
                self._piper_voice_id = EDGE_FALLBACK[role]
        else:
            self._piper_voice_id = target_id

        # Effekt-Preset aus Rollen-Mapping
        try:
            from audio.effects import AudioEffects
            self._current_preset = AudioEffects.get_role_preset(role)
        except ImportError:
            self._current_preset = "clean"

        logger.debug("Stimme: %s -> %s (Effekt: %s)", role, target_id, self._current_preset)
        return True

    def set_effect(self, preset: str) -> bool:
        """Setzt das Effekt-Preset manuell (clean, hall, monster, etc.)."""
        try:
            from audio.effects import AudioEffects
            if preset in AudioEffects.PRESET_NAMES:
                self._current_preset = preset
                logger.info("Effekt-Preset: %s", preset)
                return True
            logger.warning("Unbekanntes Effekt-Preset: '%s'", preset)
            return False
        except ImportError:
            logger.warning("AudioEffects nicht verfuegbar.")
            return False

    def speak_streaming(
        self,
        text_iter: Iterator[str],
        stop_event: threading.Event | None = None,
    ) -> bool:
        """
        Nimmt LLM-Text-Chunks entgegen und spricht Satz fuer Satz sobald
        eine Satzgrenze erkannt wird.

        Ermoeglicht < 500ms First-Audio-Latenz beim Streaming-LLM.
        """
        evt = stop_event or self._stop_event
        evt.clear()

        buffer = ""
        for chunk in text_iter:
            if evt.is_set():
                return False

            buffer += chunk

            # Pruefe auf vollstaendige Saetze im Puffer
            parts = SENTENCE_PATTERN.split(buffer)
            if len(parts) > 1:
                # Alle vollstaendigen Saetze aussprechen (letzter Teil ist Reste-Puffer)
                for sentence in parts[:-1]:
                    sentence = sentence.strip()
                    if sentence:
                        if not self._speak_sentence(sentence, evt):
                            return False
                buffer = parts[-1]  # Rest fuer naechsten Chunk aufheben

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
        Prueft stop_event zwischen Playback-Chunks (Barge-in Granularitaet).
        Returns True wenn vollstaendig abgespielt.
        """
        sentence = _preprocess_german(sentence)
        logger.debug("TTS: '%s...'", sentence[:50])

        # Edge-Routing: wenn aktive Stimme eine Edge-Stimme ist
        voice_id = VOICE_REGISTRY.get(self._current_role, "")
        if voice_id.startswith("edge:") and self._is_edge_available():
            return self._edge_speak(sentence, stop_event)

        if self._backend == "piper":
            return self._piper_speak(sentence, stop_event)
        elif self._backend == "edge":
            return self._edge_speak(sentence, stop_event)
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

    def _playback_with_effects(
        self, samples, sample_rate: int, stop_event: threading.Event
    ) -> bool:
        """Wendet Effekte an und spielt Audio mit Barge-in Check ab."""
        import sounddevice as sd
        import time

        # Effekte anwenden
        samples = self._apply_effects(samples, sample_rate)

        if stop_event.is_set():
            return False

        # Non-blocking play + poll fuer Barge-in
        sd.play(samples, samplerate=sample_rate, blocking=False)
        while sd.get_stream().active:
            if stop_event.is_set():
                sd.stop()
                logger.info("TTS Barge-in: Wiedergabe gestoppt.")
                return False
            time.sleep(0.02)  # 20ms Poll-Intervall

        return True

    def _piper_speak(self, sentence: str, stop_event: threading.Event) -> bool:
        """Piper TTS Synthese + non-blocking Wiedergabe mit Barge-in Check."""
        try:
            import numpy as np

            self._ensure_piper_loaded(self._piper_voice_id)
            if self._active_piper is None:
                # Downgrade zu Kokoro
                return self._kokoro_speak(sentence, stop_event)

            chunks = list(self._active_piper.synthesize(sentence))
            if not chunks:
                return True

            samples = np.concatenate([c.audio_float_array for c in chunks])
            sample_rate = chunks[0].sample_rate

            return self._playback_with_effects(samples, sample_rate, stop_event)

        except Exception as exc:
            logger.error("Piper Wiedergabe-Fehler: %s — Downgrade zu Kokoro", exc)
            return self._kokoro_speak(sentence, stop_event)

    def _edge_speak(self, sentence: str, stop_event: threading.Event) -> bool:
        """Edge TTS Synthese (async) + non-blocking Wiedergabe."""
        try:
            import asyncio
            import io
            import numpy as np
            import soundfile as sf  # type: ignore[import]

            async def _synthesize() -> bytes:
                import edge_tts  # type: ignore[import]
                communicate = edge_tts.Communicate(
                    sentence, self._current_edge_voice
                )
                audio_bytes = b""
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_bytes += chunk["data"]
                return audio_bytes

            # Event-Loop: async Bridge
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Innerhalb eines laufenden Loops: neuen Thread nutzen
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    mp3_bytes = pool.submit(
                        lambda: asyncio.run(_synthesize())
                    ).result(timeout=30)
            else:
                mp3_bytes = asyncio.run(_synthesize())

            if not mp3_bytes or stop_event.is_set():
                return not stop_event.is_set()

            # MP3 → numpy float32
            audio_buf = io.BytesIO(mp3_bytes)
            samples, sample_rate = sf.read(audio_buf, dtype="float32")

            # Stereo → Mono falls noetig
            if samples.ndim > 1:
                samples = samples.mean(axis=1)

            return self._playback_with_effects(samples, sample_rate, stop_event)

        except Exception as exc:
            logger.error("Edge TTS Fehler: %s — Fallback auf Piper", exc)
            # Fallback auf Piper mit Edge-Fallback-Stimme
            if self._current_role in EDGE_FALLBACK:
                old_voice = self._piper_voice_id
                self._piper_voice_id = EDGE_FALLBACK[self._current_role]
                result = self._piper_speak(sentence, stop_event)
                self._piper_voice_id = old_voice
                return result
            return self._piper_speak(sentence, stop_event)

    def _kokoro_speak(self, sentence: str, stop_event: threading.Event) -> bool:
        """Kokoro-82M (kokoro-onnx) Synthese + non-blocking Wiedergabe."""
        try:
            import numpy as np

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

            return self._playback_with_effects(samples, sample_rate, stop_event)

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
    # Edge TTS Verfuegbarkeit
    # ------------------------------------------------------------------

    def _is_edge_available(self) -> bool:
        """Prueft ob Edge TTS verfuegbar ist (import + env)."""
        if self._edge_available is not None:
            return self._edge_available
        if os.getenv("EDGE_TTS_ENABLED", "1") == "0":
            self._edge_available = False
            return False
        try:
            import edge_tts  # type: ignore[import]  # noqa: F401
            import soundfile  # type: ignore[import]  # noqa: F401
            self._edge_available = True
        except ImportError:
            self._edge_available = False
            logger.info("edge-tts/soundfile nicht installiert — Edge Stimmen deaktiviert.")
        return self._edge_available

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
                    quality = suffix[1:]  # ohne fuehrendes "-"
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
            logger.warning("Piper Laden fuer '%s' fehlgeschlagen: %s", voice_id, exc)
            self._piper_failed_voices.add(voice_id)

    def _ensure_kokoro_loaded(self) -> None:
        """
        Laedt Kokoro-82M ONNX Modell v1.0 (lazy).
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

            from kokoro_onnx import Kokoro  # type: ignore[import]
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
        if self._is_edge_available():
            try:
                import sounddevice  # type: ignore[import]  # noqa: F401
                return "edge"
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
