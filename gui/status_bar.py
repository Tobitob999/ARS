"""
gui/status_bar.py — Persistente Statusleiste am unteren Fensterrand

Zeigt: Engine State | Turn | Character Stats | Location | Mic | Cost | Duration
"""

from __future__ import annotations

import time
import tkinter as tk
import tkinter.ttk as ttk
from typing import Any

from gui.styles import (
    BG_HEADER, FG_PRIMARY, FG_MUTED, GREEN, RED, YELLOW, ORANGE,
    FONT_SMALL, PAD_SMALL,
)


class StatusBar(ttk.Frame):
    """Statusleiste mit Live-Updates via EventBus."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, style="TFrame")
        self.configure(style="TFrame")

        # Container mit dunklem Hintergrund
        self._bar = tk.Frame(self, bg=BG_HEADER, height=28)
        self._bar.pack(fill=tk.X)
        self._bar.pack_propagate(False)

        # ── Segmente ──
        self._engine_state = self._make_label("Stopped", side=tk.LEFT)
        self._sep1 = self._make_sep()
        self._turn_label = self._make_label("Turn 0", side=tk.LEFT)
        self._sep2 = self._make_sep()
        self._char_label = self._make_label("—", side=tk.LEFT)
        self._sep3 = self._make_sep()
        self._location_label = self._make_label("—", side=tk.LEFT)

        # Rechte Seite
        self._duration_label = self._make_label("00:00", side=tk.RIGHT)
        self._sep6 = self._make_sep(side=tk.RIGHT)
        self._cost_label = self._make_label("$0.000", side=tk.RIGHT)
        self._sep5 = self._make_sep(side=tk.RIGHT)
        self._mic_label = self._make_label("Mic: Off", side=tk.RIGHT)

        # Timer
        self._start_time: float | None = None
        self._duration_after_id: str | None = None

    def _make_label(self, text: str, side: str = tk.LEFT) -> tk.Label:
        lbl = tk.Label(
            self._bar, text=text, bg=BG_HEADER, fg=FG_PRIMARY,
            font=FONT_SMALL, padx=PAD_SMALL * 2,
        )
        lbl.pack(side=side)
        return lbl

    def _make_sep(self, side: str = tk.LEFT) -> tk.Label:
        sep = tk.Label(
            self._bar, text="|", bg=BG_HEADER, fg=FG_MUTED,
            font=FONT_SMALL, padx=2,
        )
        sep.pack(side=side)
        return sep

    # ── Update-Methoden (thread-safe via root.after) ──

    def set_engine_state(self, state: str) -> None:
        color = {
            "Running": GREEN,
            "Paused": YELLOW,
            "Stopped": FG_MUTED,
            "Error": RED,
            "Initializing": ORANGE,
        }.get(state, FG_PRIMARY)
        self._engine_state.configure(text=state, fg=color)

    def set_turn(self, turn: int) -> None:
        self._turn_label.configure(text=f"Turn {turn}")

    def set_character(self, status_line: str) -> None:
        self._char_label.configure(text=status_line or "—")

    def set_location(self, location: str) -> None:
        text = location if location else "—"
        if len(text) > 30:
            text = text[:27] + "..."
        self._location_label.configure(text=text)

    def set_mic_state(self, state: str) -> None:
        """state: 'off' | 'listening' | 'speaking'"""
        cfg = {
            "off": ("Mic: Off", FG_MUTED),
            "listening": ("Mic: Listening", GREEN),
            "speaking": ("Mic: TTS", RED),
        }.get(state, ("Mic: ?", FG_MUTED))
        self._mic_label.configure(text=cfg[0], fg=cfg[1])

    def set_cost(self, cost: float) -> None:
        self._cost_label.configure(text=f"${cost:.4f}")

    def start_timer(self) -> None:
        self._start_time = time.time()
        self._tick_timer()

    def stop_timer(self) -> None:
        self._start_time = None
        if self._duration_after_id:
            self.after_cancel(self._duration_after_id)
            self._duration_after_id = None

    def _tick_timer(self) -> None:
        if self._start_time is None:
            return
        elapsed = int(time.time() - self._start_time)
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            self._duration_label.configure(text=f"{hours}:{minutes:02d}:{seconds:02d}")
        else:
            self._duration_label.configure(text=f"{minutes:02d}:{seconds:02d}")
        self._duration_after_id = self.after(1000, self._tick_timer)

    # ── EventBus-Integration ──

    def handle_event(self, data: dict[str, Any]) -> None:
        """Wildcard-Handler fuer EventBus '*' Events."""
        event = data.get("_event", "")

        if event == "keeper.usage_update":
            cost = data.get("session_cost", 0.0)
            self.set_cost(cost)

        elif event == "keeper.response_complete":
            history_len = data.get("history_len", 0)
            self.set_turn(history_len // 2)

        elif event == "adventure.location_changed":
            loc = data.get("location_name", "")
            self.set_location(loc)
