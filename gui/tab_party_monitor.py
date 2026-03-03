"""
gui/tab_party_monitor.py -- Tab: Party-Monitor

Multi-Charakter-Uebersicht mit 3 Zonen:
  Zone 1 (oben, ~200px): Party Grid (Treeview mit HP-Farbkodierung)
  Zone 2 (mitte, expandierend): Game Text Log (farbkodiert)
  Zone 3 (unten, ~100px): Developer Metrics (Tags, Tokens, Kosten)

Lauscht auf EventBus-Events:
  - party.state_updated  -> Party Grid aktualisieren
  - party.member_died    -> Mitglied als tot markieren
  - party.tpk            -> TPK-Anzeige
  - game.output           -> Text-Log fuettern
  - keeper.response_complete -> Keeper-Antwort komplett
  - keeper.usage_update   -> Token/Kosten aktualisieren
"""

from __future__ import annotations

import logging
import tkinter as tk
import tkinter.ttk as ttk
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE, BLUE,
    STREAM_PLAYER, STREAM_KEEPER, STREAM_TAG, STREAM_WARNING,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, FONT_HEADER, PAD, PAD_SMALL, PAD_LARGE,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.party_monitor")


class PartyMonitorTab(ttk.Frame):
    """Party-Monitor Tab — Multi-Charakter-Uebersicht mit Text-Log und Metriken."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        # Zustandsvariablen
        self._turn_count: int = 0
        self._tag_counters: dict[str, int] = {
            "ANGRIFF": 0,
            "HP_VERLUST": 0,
            "PROBE": 0,
            "INVENTAR": 0,
            "XP_GEWINN": 0,
            "ZAUBER_VERBRAUCHT": 0,
        }
        self._total_prompt_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_cached_tokens: int = 0
        self._total_cost: float = 0.0
        self._last_latency_ms: float = 0.0

        self._build_ui()

    def _build_ui(self) -> None:
        """Erstellt die 3-Zonen UI."""
        # ── Zone 1: Party Grid (oben, fest ~200px) ──
        zone1 = ttk.LabelFrame(self, text="Party-Status", style="TLabelframe")
        zone1.pack(fill=tk.X, padx=PAD, pady=(PAD, PAD_SMALL))

        # Treeview mit Spalten
        columns = ("name", "klasse", "lvl", "hp", "ac", "thac0", "zauber", "status")
        self._tree = ttk.Treeview(
            zone1, columns=columns, show="headings",
            height=7,  # 6 Mitglieder + 1 Puffer
            selectmode="browse",
        )

        # Spalten-Header
        self._tree.heading("name", text="Name")
        self._tree.heading("klasse", text="Klasse")
        self._tree.heading("lvl", text="Lvl")
        self._tree.heading("hp", text="HP")
        self._tree.heading("ac", text="AC")
        self._tree.heading("thac0", text="THAC0")
        self._tree.heading("zauber", text="Zauber")
        self._tree.heading("status", text="Status")

        # Spaltenbreiten
        self._tree.column("name", width=160, minwidth=100)
        self._tree.column("klasse", width=80, minwidth=60)
        self._tree.column("lvl", width=40, minwidth=30, anchor=tk.CENTER)
        self._tree.column("hp", width=90, minwidth=60, anchor=tk.CENTER)
        self._tree.column("ac", width=40, minwidth=30, anchor=tk.CENTER)
        self._tree.column("thac0", width=50, minwidth=40, anchor=tk.CENTER)
        self._tree.column("zauber", width=120, minwidth=60)
        self._tree.column("status", width=80, minwidth=60, anchor=tk.CENTER)

        # Tag-Styles fuer HP-Farbkodierung
        self._tree.tag_configure("hp_high", foreground=GREEN)
        self._tree.tag_configure("hp_mid", foreground=YELLOW)
        self._tree.tag_configure("hp_low", foreground=RED)
        self._tree.tag_configure("dead", foreground=FG_MUTED)

        tree_scroll = ttk.Scrollbar(zone1, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=tree_scroll.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=PAD_SMALL)

        # ── Zone 2: Game Text Log (mitte, expandierend) ──
        zone2 = ttk.LabelFrame(self, text="Spielverlauf", style="TLabelframe")
        zone2.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD_SMALL)

        self._log_text = tk.Text(
            zone2, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_NORMAL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        log_scroll = ttk.Scrollbar(zone2, orient=tk.VERTICAL, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scroll.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Text-Tags fuer Farbkodierung
        self._log_text.tag_configure("player", foreground=STREAM_PLAYER, font=FONT_BOLD)
        self._log_text.tag_configure("keeper", foreground=STREAM_KEEPER)
        self._log_text.tag_configure("tag", foreground=STREAM_TAG)
        self._log_text.tag_configure("warning", foreground=STREAM_WARNING)
        self._log_text.tag_configure("system", foreground=FG_MUTED)
        self._log_text.tag_configure("stat", foreground=YELLOW)

        # ── Zone 3: Developer Metrics (unten, fest ~100px) ──
        zone3 = ttk.LabelFrame(self, text="Metriken", style="TLabelframe")
        zone3.pack(fill=tk.X, padx=PAD, pady=(PAD_SMALL, PAD))

        # Metriken-Grid: 2 Zeilen
        metrics_frame = ttk.Frame(zone3, style="TFrame")
        metrics_frame.pack(fill=tk.X, padx=PAD_SMALL, pady=PAD_SMALL)

        # Zeile 1: Turn, Tokens, Latency, Cost
        row1 = ttk.Frame(metrics_frame, style="TFrame")
        row1.pack(fill=tk.X, pady=(0, PAD_SMALL))

        self._lbl_turn = ttk.Label(row1, text="Turn: 0", style="TLabel")
        self._lbl_turn.pack(side=tk.LEFT, padx=(0, PAD_LARGE))

        self._lbl_tokens = ttk.Label(
            row1, text="Tokens: P:0 O:0 C:0", style="Muted.TLabel",
        )
        self._lbl_tokens.pack(side=tk.LEFT, padx=(0, PAD_LARGE))

        self._lbl_latency = ttk.Label(
            row1, text="Latenz: -", style="Muted.TLabel",
        )
        self._lbl_latency.pack(side=tk.LEFT, padx=(0, PAD_LARGE))

        self._lbl_cost = ttk.Label(
            row1, text="Kosten: $0.0000", style="Muted.TLabel",
        )
        self._lbl_cost.pack(side=tk.LEFT, padx=(0, PAD_LARGE))

        # Party-Status Indicator
        self._lbl_party_status = ttk.Label(
            row1, text="Party: -/- alive", style="Green.TLabel",
        )
        self._lbl_party_status.pack(side=tk.RIGHT, padx=(PAD_LARGE, 0))

        # Zeile 2: Tag-Zaehler
        row2 = ttk.Frame(metrics_frame, style="TFrame")
        row2.pack(fill=tk.X)

        self._lbl_tags = ttk.Label(
            row2,
            text="Tags: ANGRIFF:0  HP_VERLUST:0  PROBE:0  INVENTAR:0  XP:0  ZAUBER:0",
            style="Muted.TLabel",
        )
        self._lbl_tags.pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Engine Ready
    # ------------------------------------------------------------------

    def on_engine_ready(self) -> None:
        """Wird aufgerufen wenn die Engine bereit ist."""
        engine = self.gui.engine
        party_state = getattr(engine, "party_state", None)
        if party_state:
            self._refresh_party_grid(party_state)
            self._update_party_status(party_state)

    # ------------------------------------------------------------------
    # Event Handling
    # ------------------------------------------------------------------

    def handle_event(self, data: dict[str, Any]) -> None:
        """Verarbeitet Events vom EventBus."""
        event = data.get("_event", "")

        # Party-State Update
        if event == "party.state_updated":
            self._on_party_updated()

        elif event == "party.member_died":
            self._on_party_updated()
            name = data.get("name", "?")
            self._append_log(f"[TOD] {name} ist gefallen!", "warning")

        elif event == "party.tpk":
            self._on_party_updated()
            self._append_log("[TPK] TOTAL PARTY KILL!", "warning")
            self._lbl_party_status.configure(text="TPK!", style="Red.TLabel")

        # Game Output -> Text-Log
        elif event == "game.output":
            tag = data.get("tag", "")
            text = data.get("text", "")
            if tag == "player":
                self._append_log(f"[SPIELER] {text}", "player")
            elif tag == "stream_end":
                self._append_log(f"[SPIELLEITER] {text}", "keeper")
            elif tag in ("stat", "inventory"):
                self._append_log(text, "tag")
                self._increment_tag_counter(text)
            elif tag == "rules_warning":
                self._append_log(text, "warning")
            elif tag == "system":
                self._append_log(text, "system")
            elif tag in ("probe", "dice"):
                self._append_log(text, "tag")
                if tag == "probe":
                    self._tag_counters["PROBE"] = self._tag_counters.get("PROBE", 0) + 1
                    self._update_tags_display()

        # Keeper Antwort komplett
        elif event == "keeper.response_complete":
            self._turn_count += 1
            self._lbl_turn.configure(text=f"Turn: {self._turn_count}")

        # Token-Usage
        elif event == "keeper.usage_update":
            self._total_prompt_tokens += data.get("prompt_tokens", 0)
            self._total_output_tokens += data.get("candidates_tokens", 0)
            self._total_cached_tokens += data.get("cached_tokens", 0)
            self._total_cost += data.get("cost_request", 0.0)
            self._last_latency_ms = data.get("latency_ms", 0.0)
            self._update_metrics_display()

    # ------------------------------------------------------------------
    # Party Grid
    # ------------------------------------------------------------------

    def _on_party_updated(self) -> None:
        """Party-State hat sich geaendert — Grid aktualisieren."""
        engine = self.gui.engine
        party_state = getattr(engine, "party_state", None)
        if party_state:
            self._refresh_party_grid(party_state)
            self._update_party_status(party_state)

    def _refresh_party_grid(self, party_state: Any) -> None:
        """Aktualisiert den Treeview mit aktuellen Party-Daten."""
        # Alle Eintraege loeschen
        for item in self._tree.get_children():
            self._tree.delete(item)

        for name, member in party_state.members.items():
            # HP-Farbkodierung
            if not member.alive:
                hp_tag = "dead"
            elif member.hp_max > 0:
                hp_pct = member.hp / member.hp_max
                if hp_pct > 0.5:
                    hp_tag = "hp_high"
                elif hp_pct > 0.25:
                    hp_tag = "hp_mid"
                else:
                    hp_tag = "hp_low"
            else:
                hp_tag = "hp_mid"

            # Zauber-Info
            spell_parts = []
            for lvl, cnt in sorted(member.spells_remaining.items()):
                if cnt > 0:
                    spell_parts.append(f"L{lvl}:{cnt}")
            spell_str = ", ".join(spell_parts) if spell_parts else "-"

            # Status
            status = "Tot" if not member.alive else "Aktiv"

            # HP-String
            hp_str = f"{member.hp}/{member.hp_max}"

            self._tree.insert(
                "", tk.END,
                values=(
                    member.name,
                    member.archetype.title(),
                    member.level,
                    hp_str,
                    member.ac,
                    member.thac0,
                    spell_str,
                    status,
                ),
                tags=(hp_tag,),
            )

    def _update_party_status(self, party_state: Any) -> None:
        """Aktualisiert das Party-Status-Label."""
        alive = len(party_state.alive_members())
        total = len(party_state.members)
        total_hp = sum(m.hp for m in party_state.members.values())
        total_hp_max = sum(m.hp_max for m in party_state.members.values())

        if party_state.is_tpk():
            self._lbl_party_status.configure(
                text="TPK!", style="Red.TLabel",
            )
        elif alive < total:
            self._lbl_party_status.configure(
                text=f"Party: {alive}/{total} alive | HP: {total_hp}/{total_hp_max}",
                style="Yellow.TLabel",
            )
        else:
            self._lbl_party_status.configure(
                text=f"Party: {alive}/{total} alive | HP: {total_hp}/{total_hp_max}",
                style="Green.TLabel",
            )

    # ------------------------------------------------------------------
    # Text Log
    # ------------------------------------------------------------------

    def _append_log(self, text: str, tag: str = "") -> None:
        """Haengt Text an das Log an (auto-scroll)."""
        self._log_text.configure(state=tk.NORMAL)
        if self._log_text.index("end-1c") != "1.0":
            self._log_text.insert(tk.END, "\n")
        self._log_text.insert(tk.END, text, tag if tag else ())
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _increment_tag_counter(self, text: str) -> None:
        """Inkrementiert Tag-Zaehler basierend auf dem Text."""
        import re
        for tag_name in self._tag_counters:
            pattern = rf"\[{tag_name}[:\s]"
            if re.search(pattern, text, re.IGNORECASE):
                self._tag_counters[tag_name] += 1
        self._update_tags_display()

    def _update_tags_display(self) -> None:
        """Aktualisiert die Tag-Zaehler-Anzeige."""
        c = self._tag_counters
        self._lbl_tags.configure(
            text=(
                f"Tags: ANGRIFF:{c.get('ANGRIFF', 0)}  "
                f"HP_VERLUST:{c.get('HP_VERLUST', 0)}  "
                f"PROBE:{c.get('PROBE', 0)}  "
                f"INVENTAR:{c.get('INVENTAR', 0)}  "
                f"XP:{c.get('XP_GEWINN', 0)}  "
                f"ZAUBER:{c.get('ZAUBER_VERBRAUCHT', 0)}"
            )
        )

    def _update_metrics_display(self) -> None:
        """Aktualisiert Token/Kosten/Latenz-Anzeige."""
        self._lbl_tokens.configure(
            text=(
                f"Tokens: P:{self._total_prompt_tokens:,} "
                f"O:{self._total_output_tokens:,} "
                f"C:{self._total_cached_tokens:,}"
            )
        )
        self._lbl_cost.configure(
            text=f"Kosten: ${self._total_cost:.4f}"
        )
        if self._last_latency_ms > 0:
            self._lbl_latency.configure(
                text=f"Latenz: {self._last_latency_ms:.0f}ms"
            )
