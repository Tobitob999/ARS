"""
audio/effects.py — Audio-Effekt-Pipeline

Wendet Klang-Presets (Reverb, Distortion, Filter, etc.) auf TTS-Output an.
Basiert auf pedalboard (Spotify) fuer Echtzeit-Audio-DSP.

10 Presets fuer dramatische Variation:
  clean, hall, monster, ghost, robot, radio, underwater, cathedral, rage, old

Fallback: Wenn pedalboard nicht installiert → keine Effekte (passthrough).

Usage:
    fx = AudioEffects()
    processed = fx.apply(samples, sample_rate, "hall")
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("ARS.audio.effects")

# Pedalboard lazy-loading
_pb: Any = None
_pb_available: bool | None = None


def _ensure_pedalboard() -> bool:
    """Laedt pedalboard lazy. Gibt True zurueck wenn verfuegbar."""
    global _pb, _pb_available
    if _pb_available is not None:
        return _pb_available
    try:
        import pedalboard  # type: ignore[import]
        _pb = pedalboard
        _pb_available = True
        logger.info("pedalboard geladen — Audio-Effekte verfuegbar.")
    except ImportError:
        _pb_available = False
        logger.warning(
            "pedalboard nicht installiert — Audio-Effekte deaktiviert. "
            "Installation: pip install pedalboard"
        )
    return _pb_available


def _build_presets() -> dict[str, Any]:
    """Erstellt die Effekt-Preset-Boards. Nur aufrufen wenn pedalboard verfuegbar."""
    pb = _pb
    return {
        "clean": pb.Pedalboard([]),

        "hall": pb.Pedalboard([
            pb.Reverb(room_size=0.7, wet_level=0.4, dry_level=0.7),
        ]),

        "monster": pb.Pedalboard([
            pb.LowpassFilter(cutoff_frequency_hz=2000),
            pb.Distortion(drive_db=15),
        ]),

        "ghost": pb.Pedalboard([
            pb.HighpassFilter(cutoff_frequency_hz=800),
            pb.Reverb(room_size=0.9, wet_level=0.6, dry_level=0.4),
            pb.Gain(gain_db=-6),
        ]),

        "robot": pb.Pedalboard([
            pb.Bitcrush(bit_depth=8),
            pb.Chorus(rate_hz=2.0, depth=0.4, mix=0.5),
        ]),

        "radio": pb.Pedalboard([
            pb.HighpassFilter(cutoff_frequency_hz=300),
            pb.LowpassFilter(cutoff_frequency_hz=3500),
            pb.Compressor(threshold_db=-20, ratio=6),
            pb.Gain(gain_db=3),
        ]),

        "underwater": pb.Pedalboard([
            pb.LowpassFilter(cutoff_frequency_hz=600),
            pb.Chorus(rate_hz=0.3, depth=0.6, mix=0.4),
        ]),

        "cathedral": pb.Pedalboard([
            pb.Delay(delay_seconds=0.12, feedback=0.3, mix=0.3),
            pb.Reverb(room_size=0.85, wet_level=0.5, dry_level=0.5),
        ]),

        "rage": pb.Pedalboard([
            pb.Compressor(threshold_db=-15, ratio=8),
            pb.Distortion(drive_db=8),
            pb.Gain(gain_db=3),
        ]),

        "old": pb.Pedalboard([
            pb.LowpassFilter(cutoff_frequency_hz=3500),
            pb.Gain(gain_db=-2),
        ]),
    }


# Standard-Preset pro Stimmenrolle
ROLE_EFFECTS: dict[str, str] = {
    "keeper":    "clean",
    "woman":     "clean",
    "monster":   "monster",
    "scholar":   "clean",
    "mystery":   "ghost",
    "emotional": "clean",
    "narrator":  "clean",
    "villager":  "clean",
    "crowd":     "clean",
    "whisper":   "clean",
    "child":     "clean",
    "noble":     "hall",
    "merchant":  "clean",
    "austrian":  "clean",
    "priestess": "cathedral",
    "commander": "rage",
    "servant":   "clean",
    "herald":    "hall",
}


class AudioEffects:
    """Audio-Effekt-Prozessor mit vordefinierten Presets."""

    PRESET_NAMES = [
        "clean", "hall", "monster", "ghost", "robot",
        "radio", "underwater", "cathedral", "rage", "old",
    ]

    def __init__(self) -> None:
        self._presets: dict[str, Any] | None = None

    def _ensure_loaded(self) -> bool:
        """Lazy-Load der Presets."""
        if self._presets is not None:
            return True
        if not _ensure_pedalboard():
            return False
        self._presets = _build_presets()
        return True

    def apply(
        self,
        samples: np.ndarray,
        sample_rate: int,
        preset: str = "clean",
    ) -> np.ndarray:
        """
        Wendet ein Effekt-Preset auf Audio-Samples an.

        Args:
            samples: float32 numpy array (mono)
            sample_rate: Sample-Rate in Hz (z.B. 22050, 24000)
            preset: Name des Presets (clean, hall, monster, etc.)

        Returns:
            Verarbeitetes float32 numpy array (gleiche Laenge)
        """
        if preset == "clean":
            return samples

        if not self._ensure_loaded():
            return samples

        board = self._presets.get(preset)
        if board is None:
            logger.warning("Unbekanntes Effekt-Preset '%s' — passthrough.", preset)
            return samples

        # pedalboard erwartet (channels, samples) oder (samples,) fuer mono
        # Sicherstellen: float32, 2D mit shape (1, N)
        if samples.ndim == 1:
            audio_2d = samples.reshape(1, -1).astype(np.float32)
        else:
            audio_2d = samples.astype(np.float32)

        processed = board(audio_2d, sample_rate)

        # Zurueck zu 1D mono
        result = processed.flatten()

        # Clipping-Schutz: Normalisiere wenn noetig
        peak = np.abs(result).max()
        if peak > 1.0:
            result = result / peak
            logger.debug("Effekt '%s': Clipping verhindert (Peak %.2f).", preset, peak)

        return result

    @staticmethod
    def get_role_preset(role: str) -> str:
        """Gibt das Standard-Effekt-Preset fuer eine Stimmenrolle zurueck."""
        return ROLE_EFFECTS.get(role, "clean")


def pitch_shift(samples: np.ndarray, sample_rate: int, semitones: float) -> np.ndarray:
    """
    Pitch-Shift via Resampling (scipy).

    Args:
        samples: float32 mono array
        sample_rate: Sample-Rate in Hz
        semitones: Verschiebung in Halbtoenen (+/- 12 = eine Oktave)

    Returns:
        Pitch-verschobenes float32 array (gleiche Laenge)
    """
    if abs(semitones) < 0.01:
        return samples

    try:
        from scipy.signal import resample

        # Faktor: hoeher = kuerzer resampled = hoehere Tonhoehe
        factor = 2 ** (semitones / 12.0)
        new_length = int(len(samples) / factor)
        shifted = resample(samples, new_length).astype(np.float32)

        # Auf Originallaenge bringen (Tempo beibehalten)
        result = resample(shifted, len(samples)).astype(np.float32)

        return result

    except ImportError:
        logger.warning("scipy nicht installiert — pitch_shift nicht verfuegbar.")
        return samples
