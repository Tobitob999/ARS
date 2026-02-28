"""
gui/tab_gamestate.py — Tab 5: Spielstand & Log

Charakter-Status, World State, Location, Save/Load/Export,
Session-Liste und chronologischer Event-Log.
"""

from __future__ import annotations

import json
import logging
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, PAD, PAD_SMALL, PAD_LARGE,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.gamestate")


class GameStateTab(ttk.Frame):
    """Spielstand & Log Tab — State-Inspektion, Save/Load, Event-Log."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        self._event_log: list[dict[str, Any]] = []
        self._log_filters = {"keeper": True, "archivar": True, "adventure": True, "techgui": True}

        self._build_ui()

    def _build_ui(self) -> None:
        # Vertikaler PanedWindow
        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        # ── Oberer Bereich: Spielstand ──
        state_frame = ttk.Frame(paned, style="TFrame")
        paned.add(state_frame, weight=1)

        # Charakter
        char_lf = ttk.LabelFrame(state_frame, text=" Charakter ", style="TLabelframe")
        char_lf.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        self._char_name_label = ttk.Label(char_lf, text="—", style="Header.TLabel")
        self._char_name_label.pack(anchor=tk.W, padx=PAD, pady=(PAD_SMALL, 0))

        # HP/SAN/MP Balken
        self._stat_bars: dict[str, tuple[ttk.Progressbar, ttk.Label]] = {}
        bars_frame = ttk.Frame(char_lf, style="TFrame")
        bars_frame.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        for stat in ("HP", "SAN", "MP"):
            row = ttk.Frame(bars_frame, style="TFrame")
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"{stat}:", width=5).pack(side=tk.LEFT)
            bar = ttk.Progressbar(row, orient=tk.HORIZONTAL, length=200, mode="determinate")
            bar.pack(side=tk.LEFT, padx=PAD_SMALL, fill=tk.X, expand=True)
            lbl = ttk.Label(row, text="—/—", width=10)
            lbl.pack(side=tk.LEFT)
            self._stat_bars[stat] = (bar, lbl)

        # Skills Used / Inventar
        self._skills_used_label = ttk.Label(char_lf, text="Skills Used: —", style="Muted.TLabel")
        self._skills_used_label.pack(anchor=tk.W, padx=PAD, pady=(0, PAD_SMALL))

        # World State
        ws_lf = ttk.LabelFrame(state_frame, text=" World State ", style="TLabelframe")
        ws_lf.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        self._ws_text = tk.Text(
            ws_lf, height=6, bg=BG_PANEL, fg=FG_PRIMARY,
            font=FONT_SMALL, wrap=tk.WORD, state=tk.DISABLED,
            highlightthickness=0, borderwidth=0,
        )
        ws_scroll = ttk.Scrollbar(ws_lf, orient=tk.VERTICAL, command=self._ws_text.yview)
        self._ws_text.configure(yscrollcommand=ws_scroll.set)
        self._ws_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)
        ws_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=PAD)

        # Location
        loc_lf = ttk.LabelFrame(state_frame, text=" Location ", style="TLabelframe")
        loc_lf.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        loc_row = ttk.Frame(loc_lf, style="TFrame")
        loc_row.pack(fill=tk.X, padx=PAD, pady=PAD)
        self._loc_label = ttk.Label(loc_row, text="—")
        self._loc_label.pack(side=tk.LEFT)
        self._turn_label = ttk.Label(loc_row, text="Turn: 0", style="Muted.TLabel")
        self._turn_label.pack(side=tk.RIGHT)
        self._session_label = ttk.Label(loc_row, text="Session: —", style="Muted.TLabel")
        self._session_label.pack(side=tk.RIGHT, padx=PAD_LARGE)

        # Buttons
        btn_row = ttk.Frame(state_frame, style="TFrame")
        btn_row.pack(fill=tk.X, padx=PAD, pady=PAD)

        ttk.Button(btn_row, text="Save", style="Accent.TButton", command=self._save_game).pack(
            side=tk.LEFT, padx=PAD_SMALL,
        )
        ttk.Button(btn_row, text="Refresh", command=self._refresh_state).pack(
            side=tk.LEFT, padx=PAD_SMALL,
        )
        ttk.Button(btn_row, text="Export JSON", command=self._export_json).pack(
            side=tk.LEFT, padx=PAD_SMALL,
        )

        # Session-Saves
        saves_lf = ttk.LabelFrame(state_frame, text=" Sessions ", style="TLabelframe")
        saves_lf.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        save_cols = ("id", "module", "turn", "location", "date")
        self._saves_tree = ttk.Treeview(
            saves_lf, columns=save_cols, show="headings", height=4,
        )
        for col, head, w in [
            ("id", "#", 40), ("module", "Modul", 100), ("turn", "Turn", 60),
            ("location", "Location", 150), ("date", "Datum", 140),
        ]:
            self._saves_tree.heading(col, text=head)
            self._saves_tree.column(col, width=w)
        self._saves_tree.pack(fill=tk.X, padx=PAD, pady=PAD)

        # ── Unterer Bereich: Event-Log ──
        log_frame = ttk.LabelFrame(paned, text=" Event-Log ", style="TLabelframe")
        paned.add(log_frame, weight=1)

        # Filter
        filter_row = ttk.Frame(log_frame, style="TFrame")
        filter_row.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        self._filter_vars: dict[str, tk.BooleanVar] = {}
        for cat in ("keeper", "archivar", "adventure", "techgui"):
            var = tk.BooleanVar(value=True)
            self._filter_vars[cat] = var
            ttk.Checkbutton(
                filter_row, text=cat, variable=var,
                command=self._apply_log_filter,
            ).pack(side=tk.LEFT, padx=PAD_SMALL)

        ttk.Button(filter_row, text="Clear", command=self._clear_log).pack(
            side=tk.RIGHT, padx=PAD_SMALL,
        )
        ttk.Button(filter_row, text="Export", command=self._export_event_log).pack(
            side=tk.RIGHT, padx=PAD_SMALL,
        )

        # Log Text
        self._log_text = tk.Text(
            log_frame, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scroll.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Log-Tags
        self._log_text.tag_configure("timestamp", foreground=FG_MUTED)
        self._log_text.tag_configure("keeper", foreground=ORANGE)
        self._log_text.tag_configure("archivar", foreground=GREEN)
        self._log_text.tag_configure("adventure", foreground=FG_ACCENT)
        self._log_text.tag_configure("techgui", foreground=YELLOW)
        self._log_text.tag_configure("detail", foreground=FG_SECONDARY)

    # ── State Refresh ──

    def _refresh_state(self) -> None:
        """Aktualisiert alle State-Anzeigen aus der Engine."""
        engine = self.gui.engine

        # Charakter
        if engine.character:
            char = engine.character
            self._char_name_label.configure(text=char.name)

            for stat, (bar, lbl) in self._stat_bars.items():
                cur = char._stats.get(stat, 0)
                mx = char._stats_max.get(stat, 1)
                pct = (cur / mx * 100) if mx > 0 else 0
                bar["value"] = pct
                lbl.configure(text=f"{cur}/{mx}")

                # Farbe basierend auf Prozent
                if pct > 50:
                    bar.configure(style="TProgressbar")
                elif pct > 25:
                    bar.configure(style="Yellow.Horizontal.TProgressbar")
                else:
                    bar.configure(style="Red.Horizontal.TProgressbar")

            if char._skills_used:
                self._skills_used_label.configure(
                    text=f"Skills Used: {', '.join(sorted(char._skills_used))}",
                )

            self.gui.status_bar.set_character(char.status_line())

        # World State
        if engine._orchestrator and engine._orchestrator._archivist:
            ws = engine._orchestrator._archivist.get_world_state()
            self._ws_text.configure(state=tk.NORMAL)
            self._ws_text.delete("1.0", tk.END)
            if ws:
                for k, v in sorted(ws.items()):
                    self._ws_text.insert(tk.END, f"  {k}: {v}\n")
            else:
                self._ws_text.insert(tk.END, "  (keine Fakten)")
            self._ws_text.configure(state=tk.DISABLED)

        # Location
        if hasattr(engine, "_adv_manager") and engine._adv_manager:
            adv = engine._adv_manager
            loc = adv.get_current_location()
            if loc:
                self._loc_label.configure(text=f"{loc.get('name', '?')} ({adv.current_location_id})")
            self.gui.status_bar.set_location(
                loc.get("name", "?") if loc else "—",
            )

        # Turn / Session
        if engine._orchestrator:
            turns = len(engine._orchestrator._session_history) // 2
            self._turn_label.configure(text=f"Turn: {turns}")
            self._session_label.configure(text=f"Session: #{engine._orchestrator._session_id}")

        # Sessions aus DB laden
        self._load_sessions()

    def _load_sessions(self) -> None:
        """Laedt vorhandene Sessions aus der DB."""
        engine = self.gui.engine
        if not engine.character or not engine.character._conn:
            return
        try:
            conn = engine.character._conn
            cur = conn.execute(
                """SELECT s.id, s.module, s.last_active, s.world_state,
                          (SELECT COUNT(*) FROM session_turns WHERE session_id = s.id) as turn_count
                   FROM sessions s ORDER BY s.last_active DESC LIMIT 10""",
            )
            # Alte Eintraege entfernen
            for item in self._saves_tree.get_children():
                self._saves_tree.delete(item)

            for row in cur:
                sid = row[0]
                module = row[1]
                date = row[2][:16] if row[2] else "?"
                turn_count = row[4]
                self._saves_tree.insert("", tk.END, values=(
                    f"#{sid}", module, turn_count, "—", date,
                ))
        except Exception as exc:
            logger.warning("Sessions laden fehlgeschlagen: %s", exc)

    # ── Save / Export ──

    def _save_game(self) -> None:
        """Speichert den aktuellen Charakter-Zustand."""
        engine = self.gui.engine
        if engine.character:
            engine.character.save()
            logger.info("Spielstand gespeichert.")
            self._refresh_state()

    def _export_json(self) -> None:
        """Exportiert den kompletten Spielstand als JSON."""
        engine = self.gui.engine
        export = {"timestamp": datetime.now().isoformat()}

        if engine.character:
            export["character"] = {
                "name": engine.character.name,
                "stats": engine.character._stats,
                "stats_max": engine.character._stats_max,
                "skills_used": list(engine.character._skills_used),
            }

        if engine._orchestrator and engine._orchestrator._archivist:
            archivist = engine._orchestrator._archivist
            export["world_state"] = archivist.get_world_state()
            export["chronicle"] = archivist.get_chronicle()

        if hasattr(engine, "_adv_manager") and engine._adv_manager:
            export["flags"] = engine._adv_manager.get_all_flags()
            loc = engine._adv_manager.get_current_location()
            export["location"] = loc.get("name", "?") if loc else None

        path = Path("saves") / f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path.parent.mkdir(exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=2)
        logger.info("Spielstand exportiert: %s", path)

    # ── Event-Log ──

    def _append_log(self, timestamp: str, event: str, detail: str, category: str) -> None:
        """Fuegt einen Eintrag zum Event-Log hinzu."""
        self._event_log.append({
            "timestamp": timestamp,
            "event": event,
            "detail": detail,
            "category": category,
        })

        # Filter pruefen
        if not self._filter_vars.get(category, tk.BooleanVar(value=True)).get():
            return

        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, f"{timestamp}  ", "timestamp")
        self._log_text.insert(tk.END, f"{event:<35}", category)
        if detail:
            short = detail[:60] + "..." if len(detail) > 60 else detail
            self._log_text.insert(tk.END, f"  {short}", "detail")
        self._log_text.insert(tk.END, "\n")
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def _apply_log_filter(self) -> None:
        """Wendet Filter auf den Log an — zeichnet alles neu."""
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        for entry in self._event_log:
            cat = entry["category"]
            if self._filter_vars.get(cat, tk.BooleanVar(value=True)).get():
                self._log_text.insert(tk.END, f"{entry['timestamp']}  ", "timestamp")
                self._log_text.insert(tk.END, f"{entry['event']:<35}", cat)
                if entry["detail"]:
                    short = entry["detail"][:60] + "..." if len(entry["detail"]) > 60 else entry["detail"]
                    self._log_text.insert(tk.END, f"  {short}", "detail")
                self._log_text.insert(tk.END, "\n")
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self._event_log.clear()
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def _export_event_log(self) -> None:
        path = Path("logs") / f"event_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path.parent.mkdir(exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for entry in self._event_log:
                f.write(f"{entry['timestamp']}  {entry['event']:<35}  {entry['detail']}\n")
        logger.info("Event-Log exportiert: %s", path)

    # ── Engine Ready ──

    def on_engine_ready(self) -> None:
        self._refresh_state()

    # ── EventBus Handler ──

    def handle_event(self, data: dict[str, Any]) -> None:
        event = data.get("_event", "")
        if not event:
            return

        now = datetime.now().strftime("%H:%M:%S")
        category = event.split(".")[0] if "." in event else "techgui"

        # Event-spezifische Details
        detail = ""
        if event == "keeper.prompt_sent":
            detail = f"user_input={data.get('user_message', '')[:50]}"
        elif event == "keeper.response_complete":
            detail = f"tokens={data.get('history_len', '?')}"
            # State nach jeder Antwort aktualisieren
            self._refresh_state()
        elif event == "keeper.usage_update":
            cost = data.get("cost_request", 0.0)
            detail = f"cost=${cost:.4f}"
        elif event == "archivar.chronicle_updated":
            detail = f"len={data.get('length', '?')}"
        elif event == "archivar.world_state_updated":
            facts = data.get("new_facts", {})
            detail = ", ".join(f"{k}={v}" for k, v in facts.items())
        elif event == "adventure.location_changed":
            detail = data.get("location_name", "?")
        elif event == "adventure.flag_changed":
            detail = f"{data.get('flag', '?')}={data.get('value', '?')}"

        self._append_log(now, event, detail, category)
