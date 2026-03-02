"""
core/latency_logger.py — Strukturiertes Latenz-Tracking

Erfasst Latenzen pro Pipeline-Phase (STT, AI, TTS, Gesamt)
und stellt sie fuer Metriken-Export und GUI bereit.

Verwendung:
    ll = LatencyLogger()
    ll.start("ai")
    ... KI-Aufruf ...
    ll.stop("ai")
    ll.start("tts")
    ... TTS ...
    ll.stop("tts")
    ll.finish_turn()  # Aggregiert + emittiert
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("ARS.latency")


class LatencyLogger:
    """
    Per-Turn Latenz-Tracker fuer die ARS-Pipeline.

    Phasen: stt, ai, tts, rules, total
    """

    def __init__(self) -> None:
        self._running: dict[str, float] = {}
        self._current_turn: dict[str, float] = {}
        self._turn_history: list[dict[str, float]] = []
        self._turn_start: float = 0.0

    def start_turn(self) -> None:
        """Markiert den Beginn eines neuen Turns."""
        self._current_turn.clear()
        self._running.clear()
        self._turn_start = time.perf_counter()

    def start(self, phase: str) -> None:
        """Startet die Zeitmessung fuer eine Phase."""
        self._running[phase] = time.perf_counter()

    def stop(self, phase: str) -> float:
        """Stoppt die Zeitmessung und gibt die Dauer in ms zurueck."""
        t0 = self._running.pop(phase, None)
        if t0 is None:
            return 0.0
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self._current_turn[phase] = self._current_turn.get(phase, 0.0) + elapsed_ms
        return elapsed_ms

    def finish_turn(self, turn_number: int = 0) -> dict[str, Any]:
        """
        Schliesst den Turn ab, berechnet Gesamtlatenz und speichert.
        Gibt das Metriken-Dict zurueck.
        """
        total_ms = (time.perf_counter() - self._turn_start) * 1000.0 if self._turn_start else 0.0
        self._current_turn["total"] = total_ms

        entry = {
            "turn": turn_number,
            **{f"{k}_ms": round(v, 1) for k, v in self._current_turn.items()},
        }
        self._turn_history.append(entry)

        logger.debug(
            "Turn %d Latenz: %s",
            turn_number,
            " | ".join(f"{k}={v:.0f}ms" for k, v in self._current_turn.items()),
        )

        # EventBus-Emit (best-effort)
        try:
            from core.event_bus import EventBus
            EventBus.get().emit("game", "latency", entry)
        except Exception:
            pass

        return entry

    def get_history(self) -> list[dict[str, Any]]:
        """Gibt die gesamte Turn-History zurueck."""
        return list(self._turn_history)

    def get_averages(self) -> dict[str, float]:
        """Berechnet Durchschnittswerte ueber alle Turns."""
        if not self._turn_history:
            return {}
        keys = set()
        for entry in self._turn_history:
            keys.update(k for k in entry if k.endswith("_ms"))
        avgs = {}
        for k in keys:
            vals = [e[k] for e in self._turn_history if k in e]
            avgs[k] = round(sum(vals) / len(vals), 1) if vals else 0.0
        return avgs

    def clear(self) -> None:
        """Leert alle aufgezeichneten Daten."""
        self._running.clear()
        self._current_turn.clear()
        self._turn_history.clear()
        self._turn_start = 0.0
