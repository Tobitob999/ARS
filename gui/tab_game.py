"""
gui/tab_game.py — Tab 2: Game (Spielansicht)

Aktives Gameplay-Interface:
- Start / Pause / Stop / Save / Load Buttons
- Scrollbare Text-Ausgabe mit Live-Streaming (Keeper, System, Proben, ...)
- Text-Eingabe + Senden
- Voice On/Off + Auto-Voice Toggle
- Charakter-Status (HP/SAN/MP Balken, Inventar)
- Wuerfelgeraeusch bei Proben
- Wuerfel-Visualisierung: Dice History Panel mit Farb-Kodierung (B5)
"""

from __future__ import annotations

import logging
import re
import threading
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE,
    STREAM_PLAYER, STREAM_KEEPER, STREAM_TAG, STREAM_PROBE, STREAM_ARCHIVAR,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, FONT_HEADER, PAD, PAD_SMALL, PAD_LARGE,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.game")


class GameTab(ttk.Frame):
    """Game Tab — aktives Spielinterface mit Text-Ein/Ausgabe und Controls."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        self._voice_on = False
        self._auto_voice = False
        self._waiting_for_input = False
        self._streaming = False  # True waehrend Keeper streamt
        self._last_gui_input: str | None = None  # Gegen Doppel-Anzeige

        # Wuerfel-Visualisierung: letzter unverarbeiteter PROBE-Event
        self._pending_probe: dict[str, Any] | None = None
        # Wuerfel-History: max. 5 Eintraege (neueste zuerst)
        self._dice_history: list[dict[str, Any]] = []
        self._max_dice_history = 5

        self._build_ui()

    def _build_ui(self) -> None:
        # Haupt-Layout: Links = Game Output + Input, Rechts = Sidebar (Stats)
        main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        # ── Linke Seite: Game Output + Input ──
        left_frame = ttk.Frame(main_paned, style="TFrame")
        main_paned.add(left_frame, weight=3)

        # Control-Leiste oben
        ctrl_frame = ttk.Frame(left_frame, style="TFrame")
        ctrl_frame.pack(fill=tk.X, pady=(0, PAD_SMALL))

        self._btn_start = ttk.Button(
            ctrl_frame, text="Start", style="Accent.TButton",
            command=self._on_start,
        )
        self._btn_start.pack(side=tk.LEFT, padx=PAD_SMALL)

        self._btn_pause = ttk.Button(
            ctrl_frame, text="Pause", command=self._on_pause,
        )
        self._btn_pause.pack(side=tk.LEFT, padx=PAD_SMALL)
        self._btn_pause.state(["disabled"])

        self._btn_stop = ttk.Button(
            ctrl_frame, text="Stop", style="Danger.TButton",
            command=self._on_stop,
        )
        self._btn_stop.pack(side=tk.LEFT, padx=PAD_SMALL)
        self._btn_stop.state(["disabled"])

        ttk.Separator(ctrl_frame, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=PAD,
        )

        ttk.Button(
            ctrl_frame, text="Save", command=self._on_save,
        ).pack(side=tk.LEFT, padx=PAD_SMALL)

        ttk.Button(
            ctrl_frame, text="Load", command=self._on_load,
        ).pack(side=tk.LEFT, padx=PAD_SMALL)

        ttk.Separator(ctrl_frame, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=PAD,
        )

        ttk.Button(
            ctrl_frame, text="Reset", style="Danger.TButton",
            command=self._on_reset,
        ).pack(side=tk.LEFT, padx=PAD_SMALL)

        # Voice-Controls (rechte Seite der Control-Leiste)
        voice_frame = ttk.Frame(ctrl_frame, style="TFrame")
        voice_frame.pack(side=tk.RIGHT)

        # Keeper-Stimme Auswahl
        self._keeper_voice_var = tk.StringVar(value="keeper")
        ttk.Label(voice_frame, text="Stimme:", style="Muted.TLabel").pack(
            side=tk.RIGHT, padx=(PAD, 0),
        )
        self._keeper_voice_combo = ttk.Combobox(
            voice_frame, textvariable=self._keeper_voice_var,
            values=["keeper", "scholar", "mystery", "woman", "monster",
                    "emotional", "narrator", "villager", "crowd", "whisper"],
            state="readonly", width=12,
        )
        self._keeper_voice_combo.pack(side=tk.RIGHT, padx=PAD_SMALL)
        self._keeper_voice_combo.bind("<<ComboboxSelected>>", self._on_keeper_voice_change)

        ttk.Separator(voice_frame, orient=tk.VERTICAL).pack(
            side=tk.RIGHT, fill=tk.Y, padx=PAD_SMALL,
        )

        self._auto_voice_var = tk.BooleanVar(value=False)
        self._auto_voice_cb = ttk.Checkbutton(
            voice_frame, text="Auto-Voice",
            variable=self._auto_voice_var,
            command=self._toggle_auto_voice,
        )
        self._auto_voice_cb.pack(side=tk.RIGHT, padx=PAD_SMALL)

        self._voice_var = tk.BooleanVar(value=False)
        self._voice_cb = ttk.Checkbutton(
            voice_frame, text="Voice",
            variable=self._voice_var,
            command=self._toggle_voice,
        )
        self._voice_cb.pack(side=tk.RIGHT, padx=PAD_SMALL)

        self._voice_status = ttk.Label(
            voice_frame, text="Mic: Off", style="Muted.TLabel",
        )
        self._voice_status.pack(side=tk.RIGHT, padx=PAD_SMALL)

        # ── Game-Output (scrollbar) ──
        output_frame = ttk.Frame(left_frame, style="TFrame")
        output_frame.pack(fill=tk.BOTH, expand=True)

        self._output_text = tk.Text(
            output_frame, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_NORMAL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        output_scroll = ttk.Scrollbar(
            output_frame, orient=tk.VERTICAL, command=self._output_text.yview,
        )
        self._output_text.configure(yscrollcommand=output_scroll.set)
        self._output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        output_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Text-Tags fuer Farbkodierung
        self._output_text.tag_configure("keeper", foreground=STREAM_KEEPER)
        self._output_text.tag_configure("player", foreground=STREAM_PLAYER, font=FONT_BOLD)
        self._output_text.tag_configure("system", foreground=FG_MUTED)
        self._output_text.tag_configure("probe", foreground=STREAM_PROBE, font=FONT_BOLD)
        self._output_text.tag_configure("dice", foreground=STREAM_PROBE)
        self._output_text.tag_configure("stat", foreground=YELLOW)
        self._output_text.tag_configure("combat", foreground=RED, font=FONT_BOLD)
        self._output_text.tag_configure("combat_hit", foreground=ORANGE, font=FONT_BOLD)
        self._output_text.tag_configure("combat_miss", foreground=FG_MUTED, font=FONT_BOLD)
        self._output_text.tag_configure("combat_state", foreground=FG_SECONDARY)
        self._output_text.tag_configure("fact", foreground=STREAM_TAG)
        self._output_text.tag_configure("rules_warning", foreground=ORANGE)
        self._output_text.tag_configure("archivar", foreground=STREAM_ARCHIVAR)
        self._output_text.tag_configure("timestamp", foreground=FG_MUTED, font=FONT_SMALL)
        self._output_text.tag_configure("label", foreground=FG_MUTED, font=FONT_SMALL)

        # ── Input-Zeile ──
        input_frame = tk.Frame(left_frame, bg=BG_PANEL)
        input_frame.pack(fill=tk.X, pady=(PAD_SMALL, 0))

        self._input_label = tk.Label(
            input_frame, text="[SPIELER] >", bg=BG_PANEL, fg=FG_ACCENT,
            font=FONT_BOLD, padx=PAD,
        )
        self._input_label.pack(side=tk.LEFT)

        self._input_entry = tk.Entry(
            input_frame, bg=BG_INPUT, fg=FG_PRIMARY,
            insertbackground=FG_PRIMARY, font=FONT_NORMAL,
            relief=tk.FLAT, borderwidth=4,
        )
        self._input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)
        self._input_entry.bind("<Return>", self._on_send)
        self._input_entry.configure(state=tk.DISABLED)

        self._btn_send = ttk.Button(
            input_frame, text="Senden", style="Accent.TButton",
            command=lambda: self._on_send(None),
        )
        self._btn_send.pack(side=tk.RIGHT, padx=PAD_SMALL, pady=PAD_SMALL)
        self._btn_send.state(["disabled"])

        # ── Mic-Level + STT-Text Anzeige ──
        mic_frame = tk.Frame(left_frame, bg=BG_PANEL)
        mic_frame.pack(fill=tk.X, pady=(PAD_SMALL, 0))

        tk.Label(
            mic_frame, text="Mic:", bg=BG_PANEL, fg=FG_MUTED,
            font=FONT_SMALL, padx=PAD_SMALL,
        ).pack(side=tk.LEFT)

        self._mic_level_bar = ttk.Progressbar(
            mic_frame, orient=tk.HORIZONTAL, length=120,
            mode="determinate", maximum=100,
        )
        self._mic_level_bar.pack(side=tk.LEFT, padx=PAD_SMALL, pady=2)
        self._mic_level_bar["value"] = 0

        self._mic_vad_label = tk.Label(
            mic_frame, text="", bg=BG_PANEL, fg=FG_MUTED,
            font=FONT_SMALL, width=3,
        )
        self._mic_vad_label.pack(side=tk.LEFT, padx=(0, PAD))

        tk.Label(
            mic_frame, text="STT:", bg=BG_PANEL, fg=FG_MUTED,
            font=FONT_SMALL,
        ).pack(side=tk.LEFT, padx=(PAD_SMALL, 0))

        self._stt_text_label = tk.Label(
            mic_frame, text="—", bg=BG_PANEL, fg=STREAM_PLAYER,
            font=FONT_SMALL, anchor=tk.W,
        )
        self._stt_text_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=PAD_SMALL)

        # ── Rechte Seite: Character Sidebar ──
        right_frame = ttk.Frame(main_paned, style="TFrame")
        main_paned.add(right_frame, weight=1)

        # Charakter-Name
        self._char_name = ttk.Label(right_frame, text="—", style="Header.TLabel")
        self._char_name.pack(anchor=tk.W, padx=PAD, pady=(PAD, PAD_SMALL))

        # HP / SAN / MP Balken
        stats_lf = ttk.LabelFrame(right_frame, text=" Status ", style="TLabelframe")
        stats_lf.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        self._stat_bars: dict[str, tuple[ttk.Progressbar, ttk.Label]] = {}
        for stat in ("HP", "SAN", "MP"):
            row = ttk.Frame(stats_lf, style="TFrame")
            row.pack(fill=tk.X, padx=PAD_SMALL, pady=2)
            ttk.Label(row, text=f"{stat}:", width=5).pack(side=tk.LEFT)
            bar = ttk.Progressbar(row, orient=tk.HORIZONTAL, length=120, mode="determinate")
            bar.pack(side=tk.LEFT, padx=PAD_SMALL, fill=tk.X, expand=True)
            lbl = ttk.Label(row, text="—/—", width=8)
            lbl.pack(side=tk.LEFT)
            self._stat_bars[stat] = (bar, lbl)

        # Inventar
        inv_lf = ttk.LabelFrame(right_frame, text=" Inventar ", style="TLabelframe")
        inv_lf.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD_SMALL)

        self._inv_text = tk.Text(
            inv_lf, bg=BG_PANEL, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, height=8,
        )
        inv_scroll = ttk.Scrollbar(inv_lf, orient=tk.VERTICAL, command=self._inv_text.yview)
        self._inv_text.configure(yscrollcommand=inv_scroll.set)
        self._inv_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)
        inv_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=PAD_SMALL)

        # Skills Used
        skills_lf = ttk.LabelFrame(right_frame, text=" Genutzte Fertigkeiten ", style="TLabelframe")
        skills_lf.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        self._skills_label = ttk.Label(skills_lf, text="—", style="Muted.TLabel", wraplength=200)
        self._skills_label.pack(anchor=tk.W, padx=PAD, pady=PAD_SMALL)

        # ── Wuerfel-History Panel ──
        self._build_dice_panel(right_frame)

        # Location
        loc_lf = ttk.LabelFrame(right_frame, text=" Ort ", style="TLabelframe")
        loc_lf.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        self._loc_label = ttk.Label(loc_lf, text="—", wraplength=200)
        self._loc_label.pack(anchor=tk.W, padx=PAD, pady=PAD_SMALL)

        # Turn-Zaehler
        self._turn_label = ttk.Label(right_frame, text="Turn: 0", style="Muted.TLabel")
        self._turn_label.pack(anchor=tk.W, padx=PAD, pady=PAD_SMALL)

    # ── Wuerfel-Panel ──

    def _build_dice_panel(self, parent: ttk.Frame) -> None:
        """Erstellt das Dice-History-Panel in der rechten Sidebar."""
        dice_lf = ttk.LabelFrame(parent, text=" Wuerfelwuerfe ", style="TLabelframe")
        dice_lf.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        # Leerer Zustand (sichtbar wenn noch keine Wuerfe)
        self._dice_empty_label = ttk.Label(
            dice_lf, text="(noch keine Proben)", style="Muted.TLabel",
        )
        self._dice_empty_label.pack(anchor=tk.W, padx=PAD, pady=PAD_SMALL)

        # Container fuer Wurf-Karten (max. 5 Eintraege)
        self._dice_cards_frame = tk.Frame(dice_lf, bg=BG_DARK)
        self._dice_cards_frame.pack(fill=tk.X, padx=PAD_SMALL, pady=(0, PAD_SMALL))

        # Bis zu 5 Slot-Frames vorab erstellen (werden bei Bedarf befullt)
        self._dice_card_slots: list[tk.Frame] = []
        for _ in range(self._max_dice_history):
            slot = tk.Frame(self._dice_cards_frame, bg=BG_DARK)
            # Slot nicht packen — erst bei Befuellung einblenden
            self._dice_card_slots.append(slot)

    def _render_dice_history(self) -> None:
        """Rendert alle Wuerfel-History-Eintraege neu in die Slot-Frames."""
        # Alle Slots zunaechst leeren und verstecken
        for slot in self._dice_card_slots:
            for widget in slot.winfo_children():
                widget.destroy()
            slot.pack_forget()

        if not self._dice_history:
            self._dice_empty_label.pack(anchor=tk.W, padx=PAD, pady=PAD_SMALL)
            return

        self._dice_empty_label.pack_forget()

        for idx, entry in enumerate(self._dice_history):
            if idx >= self._max_dice_history:
                break
            slot = self._dice_card_slots[idx]
            self._fill_dice_card(slot, entry, is_latest=(idx == 0))
            slot.pack(fill=tk.X, pady=1)

    def _fill_dice_card(self, frame: tk.Frame, entry: dict[str, Any], is_latest: bool) -> None:
        """
        Befuellt einen Slot-Frame mit einer Wurf-Karte.

        entry keys:
          skill        str  — Fertigkeitsname
          target       int  — Zielwert
          roll         int  — Gewuerfelter Wert (0 = unbekannt/d6-Pool)
          is_success   bool
          success_level str  — "critical"|"extreme"|"hard"|"regular"|"failure"|"fumble"
          dice_system  str  — "d100"|"d20"|"d6pool"
          pool_dice    list[int] | None  — Bei d6-Pool: alle Einzelwuerfel
          hits         int | None  — Bei d6-Pool: Anzahl Treffer (5+)
          threshold    int | None  — Bei d6-Pool: benoet. Treffer
          timestamp    str  — HH:MM:SS
        """
        is_success = entry.get("is_success", False)
        success_level = entry.get("success_level", "failure")
        dice_system = entry.get("dice_system", "d100")
        skill = entry.get("skill", "?")
        target = entry.get("target", 0)
        roll = entry.get("roll", 0)
        timestamp = entry.get("timestamp", "")

        # Farbschema je Erfolgsgrad
        _level_colors = {
            "critical":  "#FFD700",   # Gold
            "extreme":   "#A6E3A1",   # Gruen hell
            "hard":      "#A6E3A1",   # Gruen
            "regular":   "#A6E3A1",   # Gruen (etwas dunkler)
            "failure":   "#F38BA8",   # Rot
            "fumble":    "#FF4444",   # Dunkelrot
        }
        result_color = _level_colors.get(success_level, RED if not is_success else GREEN)
        border_color = result_color if is_latest else FG_MUTED

        # Aeuesserer Rahmen mit Farb-Indikator
        card_bg = BG_PANEL if is_latest else BG_DARK
        card = tk.Frame(frame, bg=card_bg, highlightbackground=border_color,
                        highlightthickness=1 if is_latest else 0)
        card.pack(fill=tk.X, pady=1)

        # ── Zeile 1: Skill + Ergebnis-Badge ──
        row1 = tk.Frame(card, bg=card_bg)
        row1.pack(fill=tk.X, padx=PAD_SMALL, pady=(PAD_SMALL, 0))

        tk.Label(
            row1, text=skill, bg=card_bg, fg=FG_PRIMARY,
            font=FONT_SMALL, anchor=tk.W,
        ).pack(side=tk.LEFT)

        # Timestamp (gedimmt, rechts)
        tk.Label(
            row1, text=timestamp, bg=card_bg, fg=FG_MUTED,
            font=FONT_SMALL,
        ).pack(side=tk.RIGHT)

        # ── Zeile 2: Wuerfeldetails ──
        row2 = tk.Frame(card, bg=card_bg)
        row2.pack(fill=tk.X, padx=PAD_SMALL, pady=(0, PAD_SMALL))

        if dice_system == "d6pool":
            # Shadowrun d6-Pool: Einzelwuerfel + Hits-Anzeige
            pool_dice = entry.get("pool_dice") or []
            hits = entry.get("hits", 0)
            threshold = entry.get("threshold", 1)
            self._render_d6_pool(row2, card_bg, pool_dice, hits, threshold, result_color)
        else:
            # d100 / d20: einfache Roll | Ziel Darstellung
            self._render_simple_roll(row2, card_bg, roll, target, dice_system, result_color, success_level)

    def _render_simple_roll(
        self, parent: tk.Frame, bg: str,
        roll: int, target: int, dice_system: str,
        result_color: str, success_level: str,
    ) -> None:
        """Rendert eine einfache d100/d20-Probe als Zahlen-Anzeige."""
        die_label = "d100" if dice_system == "d100" else "d20"

        # Wuerfelwert (gross, gefaerbt)
        tk.Label(
            parent, text=str(roll), bg=bg, fg=result_color,
            font=FONT_BOLD,
        ).pack(side=tk.LEFT)

        tk.Label(
            parent, text=f" / {target}", bg=bg, fg=FG_SECONDARY,
            font=FONT_SMALL,
        ).pack(side=tk.LEFT)

        # Erfolgsgrad-Label
        _level_labels = {
            "critical": "KRITISCH",
            "extreme":  "EXTREM",
            "hard":     "HART",
            "regular":  "OK",
            "failure":  "MISS",
            "fumble":   "PATZER",
        }
        level_text = _level_labels.get(success_level, success_level.upper())
        tk.Label(
            parent, text=f"  {level_text}", bg=bg, fg=result_color,
            font=FONT_BOLD,
        ).pack(side=tk.LEFT)

        # Die-Typ rechts
        tk.Label(
            parent, text=die_label, bg=bg, fg=FG_MUTED,
            font=FONT_SMALL,
        ).pack(side=tk.RIGHT)

    def _render_d6_pool(
        self, parent: tk.Frame, bg: str,
        pool_dice: list[int], hits: int, threshold: int, result_color: str,
    ) -> None:
        """Rendert einen Shadowrun d6-Pool als einzelne Wuerfel-Symbole."""
        # Einzelwuerfel darstellen (max. 12 Wuerfel anzeigen, Rest "...")
        for i, d in enumerate(pool_dice[:12]):
            is_hit = d >= 5
            die_fg = GREEN if is_hit else FG_MUTED
            tk.Label(
                parent, text=str(d), bg=bg, fg=die_fg,
                font=FONT_SMALL,
                relief=tk.SOLID, borderwidth=1, padx=2,
            ).pack(side=tk.LEFT, padx=1)

        if len(pool_dice) > 12:
            tk.Label(
                parent, text=f"+{len(pool_dice)-12}", bg=bg, fg=FG_MUTED,
                font=FONT_SMALL,
            ).pack(side=tk.LEFT, padx=1)

        # Hits/Threshold-Zusammenfassung
        tk.Label(
            parent, text=f"  {hits}/{threshold} Hits", bg=bg, fg=result_color,
            font=FONT_BOLD,
        ).pack(side=tk.LEFT, padx=(PAD_SMALL, 0))

    # ── Probe-Parsing ──

    # Parst "[PROBE] Schleichen (Zielwert: 45)" -> ("Schleichen", 45)
    _RE_PROBE_TEXT = re.compile(
        r"\[PROBE\]\s+(.+?)\s+\(Zielwert:\s*(\d+)\)", re.IGNORECASE,
    )
    # Parst "Wurf: 73 | Ziel: 45 | [!!] Misserfolg" -> (73, 45, False, "failure")
    _RE_DICE_TEXT = re.compile(
        r"Wurf:\s*(\d+)\s*\|\s*Ziel:\s*(\d+)\s*\|\s*(\[OK\]|\[!!\])\s+(.+)", re.IGNORECASE,
    )
    # Shadowrun Pool-Text: z.B. "d6-Pool [5]: Wuerfel: 2 4 5 6 1 -> 2 Hits (Schwelle: 3)"
    _RE_D6_POOL_TEXT = re.compile(
        r"d6-Pool\s*\[(\d+)\].*?Wuerfel:\s*([\d\s]+?)\s*->\s*(\d+)\s*Hits?\s*\(Schwelle:\s*(\d+)\)",
        re.IGNORECASE,
    )

    _LEVEL_MAP = {
        "kritischer erfolg": "critical",
        "kritisch":          "critical",
        "extremer erfolg":   "extreme",
        "extrem":            "extreme",
        "harter erfolg":     "hard",
        "hart":              "hard",
        "regulärer erfolg":  "regular",
        "regulaerer erfolg": "regular",
        "regulaer":          "regular",
        "ok":                "regular",
        "misserfolg":        "failure",
        "miss":              "failure",
        "patzer":            "fumble",
    }

    def _parse_probe_text(self, text: str) -> dict[str, Any] | None:
        """
        Extrahiert Skill und Zielwert aus einem PROBE-Event-Text.

        Erwartet: "[PROBE] Fertigkeitsname (Zielwert: 45)"
        Returns: {"skill": str, "target": int} oder None
        """
        m = self._RE_PROBE_TEXT.search(text)
        if m:
            return {"skill": m.group(1).strip(), "target": int(m.group(2))}
        # Fallback: Zielwert irgendwo im Text
        m2 = re.search(r"Zielwert:\s*(\d+)", text, re.IGNORECASE)
        if m2:
            # Skill-Name: alles zwischen [PROBE] und "(Zielwert"
            skill_m = re.search(r"\[PROBE\]\s+(.+?)\s+\(", text, re.IGNORECASE)
            skill = skill_m.group(1).strip() if skill_m else "Probe"
            return {"skill": skill, "target": int(m2.group(1))}
        return None

    def _parse_dice_text(self, text: str) -> dict[str, Any] | None:
        """
        Extrahiert Wurf, Ziel und Erfolgsgrad aus einem Dice-Event-Text.

        Erwartet: "Wurf: 73 | Ziel: 45 | [!!] Misserfolg"
        Oder Shadowrun Pool-Format.
        Returns: dict mit roll, target, is_success, success_level, dice_system
        """
        # Shadowrun d6-Pool zuerst pruefen
        m_pool = self._RE_D6_POOL_TEXT.search(text)
        if m_pool:
            pool_size = int(m_pool.group(1))
            dice_values = [int(x) for x in m_pool.group(2).split() if x.isdigit()]
            hits = int(m_pool.group(3))
            threshold = int(m_pool.group(4))
            return {
                "roll": 0,
                "target": threshold,
                "is_success": hits >= threshold,
                "success_level": "regular" if hits >= threshold else "failure",
                "dice_system": "d6pool",
                "pool_dice": dice_values,
                "hits": hits,
                "threshold": threshold,
            }

        # Standard Probe (d100 / d20)
        m = self._RE_DICE_TEXT.search(text)
        if m:
            roll = int(m.group(1))
            target = int(m.group(2))
            is_success = m.group(3).upper() == "[OK]"
            level_raw = m.group(4).strip().lower()
            success_level = self._LEVEL_MAP.get(level_raw, "regular" if is_success else "failure")
            # d20 heuristisch: Zielwert <= 20
            dice_system = "d20" if target <= 20 else "d100"
            return {
                "roll": roll,
                "target": target,
                "is_success": is_success,
                "success_level": success_level,
                "dice_system": dice_system,
                "pool_dice": None,
                "hits": None,
                "threshold": None,
            }
        return None

    def _on_dice_event(self, probe_text: str | None, dice_text: str | None) -> None:
        """
        Verarbeitet ein Probe+Dice-Paar und fuegt es der History hinzu.

        Wird aufgerufen wenn beide Events eingegangen sind (oder nur dice_text
        fuer Systeme ohne vorangehenden PROBE-Event).
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Skillname + Zielwert aus probe_text
        skill = "Probe"
        target_override: int | None = None
        if probe_text:
            parsed_probe = self._parse_probe_text(probe_text)
            if parsed_probe:
                skill = parsed_probe["skill"]
                target_override = parsed_probe["target"]

        # Wuerfeldetails aus dice_text
        if dice_text:
            parsed_dice = self._parse_dice_text(dice_text)
        else:
            parsed_dice = None

        if parsed_dice is None:
            # Kein parsbares Wuerfelergebnis — minimal-Eintrag
            if target_override is None:
                return
            parsed_dice = {
                "roll": 0,
                "target": target_override,
                "is_success": False,
                "success_level": "failure",
                "dice_system": "d100",
                "pool_dice": None,
                "hits": None,
                "threshold": None,
            }

        # Zielwert aus PROBE-Text hat Vorrang (praeziser als geclampt in mechanics)
        if target_override is not None:
            parsed_dice["target"] = target_override

        entry = {
            "skill": skill,
            "timestamp": timestamp,
            **parsed_dice,
        }

        # History: neuesten Eintrag vorne einreihen
        self._dice_history.insert(0, entry)
        if len(self._dice_history) > self._max_dice_history:
            self._dice_history = self._dice_history[:self._max_dice_history]

        # Panel neu rendern — via after() in den Main-Thread dispatchen (Thread-Safety)
        self.after(0, self._render_dice_history)

        # Strukturiertes Event auf EventBus fuer andere Listener (z.B. KI-Monitor)
        try:
            from core.event_bus import EventBus
            EventBus.get().emit("keeper", "dice_roll", {
                "skill": entry["skill"],
                "target": entry["target"],
                "roll": entry.get("roll", 0),
                "is_success": entry["is_success"],
                "success_level": entry["success_level"],
                "dice_system": entry["dice_system"],
                "pool_dice": entry.get("pool_dice"),
                "hits": entry.get("hits"),
                "threshold": entry.get("threshold"),
                "system": self.gui.engine.module_name if hasattr(self.gui, "engine") else "",
            })
        except Exception:
            pass  # EventBus-Emission ist optional — nie Game-Loop blockieren

    # ── Output-Methoden ──

    def _append_output(self, text: str, tag: str = "") -> None:
        """Fuegt Text zum Game-Output hinzu."""
        self._output_text.configure(state=tk.NORMAL)
        if tag:
            self._output_text.insert(tk.END, text, tag)
        else:
            self._output_text.insert(tk.END, text)
        self._output_text.see(tk.END)
        self._output_text.configure(state=tk.DISABLED)

    def _append_timestamp(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._append_output(f"[{now}] ", "timestamp")

    # ── Wuerfelgeraeusch ──

    def _play_dice_sound(self) -> None:
        """Spielt ein kurzes Wuerfelgeraeusch ab."""
        try:
            import winsound
            dice_wav = Path(__file__).parent.parent / "data" / "sounds" / "dice.wav"
            if dice_wav.exists():
                winsound.PlaySound(
                    str(dice_wav),
                    winsound.SND_FILENAME | winsound.SND_ASYNC,
                )
            else:
                # Fallback: System-Sound
                winsound.PlaySound(
                    "SystemExclamation",
                    winsound.SND_ALIAS | winsound.SND_ASYNC,
                )
        except Exception:
            pass  # Kein Sound-Support — kein Problem

    # ── Input ──

    def _on_send(self, event: Any) -> None:
        """Sendet Spieler-Input an den Orchestrator."""
        if not self._waiting_for_input:
            return

        text = self._input_entry.get().strip()
        if not text:
            return

        self._input_entry.delete(0, tk.END)
        self._last_gui_input = text  # Merken gegen Doppel-Anzeige

        # Anzeigen im Output
        self._append_timestamp()
        self._append_output("SPIELER: ", "label")
        self._append_output(text + "\n", "player")

        # An Orchestrator senden
        orch = self.gui.engine._orchestrator
        if orch:
            orch.submit_input(text)

        self._set_input_state(False)

    def _set_input_state(self, enabled: bool) -> None:
        """Aktiviert/deaktiviert das Eingabefeld."""
        self._waiting_for_input = enabled
        state = tk.NORMAL if enabled else tk.DISABLED
        self._input_entry.configure(state=state)
        if enabled:
            self._btn_send.state(["!disabled"])
            self._input_entry.focus_set()
            self._input_label.configure(fg=GREEN)
        else:
            self._btn_send.state(["disabled"])
            self._input_label.configure(fg=FG_ACCENT)

    # ── Control-Buttons ──

    def _on_start(self) -> None:
        """Startet oder resumed die Engine."""
        btn_text = self._btn_start.cget("text")
        if btn_text == "Resume":
            # Resume: Orchestrator fortsetzen
            orch = self.gui.engine._orchestrator
            if orch:
                import threading
                threading.Thread(
                    target=orch.resume_session, daemon=True, name="ARS-Resume",
                ).start()
            self._btn_start.configure(text="Start")
        else:
            # Neuer Start via TechGUI
            self.gui.start_engine()

        self._btn_start.state(["disabled"])
        self._btn_pause.state(["!disabled"])
        self._btn_stop.state(["!disabled"])

    def _on_pause(self) -> None:
        self.gui.pause_engine()
        self._btn_start.state(["!disabled"])
        self._btn_start.configure(text="Resume")
        self._btn_pause.state(["disabled"])
        self._set_input_state(False)

    def _on_stop(self) -> None:
        self.gui.stop_engine()
        self._btn_start.state(["!disabled"])
        self._btn_start.configure(text="Start")
        self._btn_pause.state(["disabled"])
        self._btn_stop.state(["disabled"])
        self._set_input_state(False)

    def _on_reset(self) -> None:
        """Reset: stoppt Engine, leert Chat + History, wechselt zum Session-Tab."""
        from tkinter import messagebox
        if not messagebox.askokcancel(
            "Session Reset",
            "Session zuruecksetzen?\n\n"
            "Chat-Verlauf, KI-History, Kampf- und Zeit-Tracker\n"
            "werden geloescht. Ungespeicherter Fortschritt geht verloren.",
            parent=self.gui.root,
        ):
            return

        # 1. Engine stoppen
        self._on_stop()

        # 2. Chat-Output leeren
        self._output_text.configure(state=tk.NORMAL)
        self._output_text.delete("1.0", tk.END)
        self._output_text.configure(state=tk.DISABLED)

        engine = self.gui.engine

        # 3. KI-Backend: History + alle Caches leeren
        if hasattr(engine, "ai_backend") and engine.ai_backend:
            engine.ai_backend.clear_caches()

        # 4. Orchestrator: Session-History, Metrics, Latency leeren
        if hasattr(engine, "_orchestrator") and engine._orchestrator:
            orch = engine._orchestrator
            orch._session_history.clear()
            orch._metrics_log.clear()
            orch._turn_number = 0
            orch._session_start = 0.0
            if hasattr(orch, "_latency_logger") and orch._latency_logger:
                orch._latency_logger.clear()

        # 5. Combat-Tracker zuruecksetzen
        if hasattr(engine, "_orchestrator") and engine._orchestrator:
            ct = engine._orchestrator._combat_tracker
            if ct and hasattr(ct, "end_combat"):
                ct.end_combat()

        # 6. Time-Tracker zuruecksetzen
        if hasattr(engine, "_orchestrator") and engine._orchestrator:
            tt = getattr(engine._orchestrator, "_time_tracker", None)
            if tt:
                tt._hour, tt._minute, tt._day = 8, 0, 1
                tt._weather = "klar"

        # 7. Adventure-Manager Flags zuruecksetzen
        if hasattr(engine, "_adv_manager") and engine._adv_manager:
            engine._adv_manager.reset_flags()

        # 8. KI-Monitor Injection-Log leeren
        if hasattr(self.gui, "tab_ki_monitor"):
            monitor = self.gui.tab_ki_monitor
            if hasattr(monitor, "_rules_injection_log"):
                monitor._rules_injection_log.clear()

        # 9. Status-Meldung
        self._append_timestamp()
        self._append_output("Session zurueckgesetzt. Druecke [Start] fuer neue Session.\n", "system")

        # 10. Zum Session-Tab wechseln
        self.gui.notebook.select(self.gui.tab_session)

    def _on_save(self) -> None:
        engine = self.gui.engine
        if engine.character:
            engine.character.save()
            self._append_timestamp()
            self._append_output("Spielstand gespeichert.\n", "system")

    def _on_load(self) -> None:
        """Zeigt einen Dialog mit verfuegbaren Sessions zum Laden."""
        engine = self.gui.engine
        if not engine.character or not engine.character._conn:
            self._append_output("Kein Charakter geladen.\n", "system")
            return

        # Sessions aus DB holen
        try:
            conn = engine.character._conn
            cur = conn.execute(
                """SELECT s.id, s.module, s.last_active,
                          (SELECT COUNT(*) FROM session_turns WHERE session_id = s.id) as turn_count
                   FROM sessions s ORDER BY s.last_active DESC LIMIT 10""",
            )
            sessions = cur.fetchall()
        except Exception as exc:
            self._append_output(f"Fehler beim Laden: {exc}\n", "system")
            return

        if not sessions:
            self._append_output("Keine Sessions gefunden.\n", "system")
            return

        # Einfacher Selection-Dialog
        dialog = tk.Toplevel(self.gui.root)
        dialog.title("Session laden")
        dialog.geometry("400x300")
        dialog.configure(bg=BG_DARK)
        dialog.transient(self.gui.root)
        dialog.grab_set()

        tk.Label(
            dialog, text="Session waehlen:", bg=BG_DARK, fg=FG_ACCENT,
            font=FONT_BOLD,
        ).pack(padx=PAD, pady=PAD)

        listbox = tk.Listbox(
            dialog, bg=BG_PANEL, fg=FG_PRIMARY, font=FONT_NORMAL,
            selectbackground=FG_ACCENT, selectforeground=BG_DARK,
            height=8,
        )
        listbox.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD_SMALL)

        session_ids = []
        for row in sessions:
            sid, module, last_active, turn_count = row
            date = last_active[:16] if last_active else "?"
            listbox.insert(tk.END, f"#{sid}  |  {module}  |  {turn_count} Turns  |  {date}")
            session_ids.append(sid)

        def _do_load():
            sel = listbox.curselection()
            if not sel:
                return
            chosen_id = session_ids[sel[0]]
            dialog.destroy()
            self._append_timestamp()
            self._append_output(f"Session #{chosen_id} laden...\n", "system")
            # TODO: Implementiere Session-Restore im Orchestrator

        ttk.Button(
            dialog, text="Laden", style="Accent.TButton", command=_do_load,
        ).pack(pady=PAD)

    # ── Voice Toggles ──

    def _toggle_voice(self) -> None:
        self._voice_on = self._voice_var.get()
        engine = self.gui.engine
        if self._voice_on:
            if not hasattr(engine, "_tts") or not engine._tts:
                # Voice-Init im Hintergrund um GUI nicht zu blockieren
                self._voice_status.configure(text="Mic: Loading...", style="Muted.TLabel")
                self._voice_cb.state(["disabled"])
                import threading

                def _init_voice():
                    try:
                        engine.enable_voice(barge_in=False)
                        self.after(0, self._on_voice_ready)
                    except Exception as exc:
                        logger.warning("Voice-Aktivierung fehlgeschlagen: %s", exc)
                        self.after(0, self._on_voice_failed)

                threading.Thread(target=_init_voice, daemon=True).start()
                return
            engine._voice_enabled = True
            self._voice_status.configure(text="Mic: On", style="Green.TLabel")
            self.gui.status_bar.set_mic_state("listening")
        else:
            engine._voice_enabled = False
            self._auto_voice_var.set(False)
            self._auto_voice = False
            self._voice_status.configure(text="Mic: Off", style="Muted.TLabel")
            self.gui.status_bar.set_mic_state("off")

    def _on_voice_ready(self) -> None:
        """Callback wenn Voice-Init im Hintergrund fertig ist."""
        self._voice_cb.state(["!disabled"])
        self.gui.engine._voice_enabled = True
        self._voice_on = True
        self._voice_status.configure(text="Mic: On", style="Green.TLabel")
        self.gui.status_bar.set_mic_state("listening")
        self._append_timestamp()
        self._append_output("Voice aktiviert (TTS + STT bereit)\n", "system")

    def _on_voice_failed(self) -> None:
        """Callback wenn Voice-Init fehlschlaegt."""
        self._voice_cb.state(["!disabled"])
        self._voice_var.set(False)
        self._voice_on = False
        self._voice_status.configure(text="Mic: Off", style="Muted.TLabel")
        self._append_timestamp()
        self._append_output("Voice-Aktivierung fehlgeschlagen!\n", "system")

    def _on_keeper_voice_change(self, event: Any) -> None:
        """Wechselt die Keeper-Stimme live."""
        role = self._keeper_voice_var.get()
        engine = self.gui.engine
        if hasattr(engine, "_tts") and engine._tts:
            if engine._tts.set_voice(role):
                self._append_timestamp()
                self._append_output(f"Keeper-Stimme: {role}\n", "system")
                logger.info("Keeper-Stimme gewechselt: %s", role)
        else:
            self._append_output("TTS nicht geladen — Stimme wird beim naechsten Start gesetzt.\n", "system")

    def _toggle_auto_voice(self) -> None:
        self._auto_voice = self._auto_voice_var.get()
        if self._auto_voice and not self._voice_on:
            self._voice_var.set(True)
            self._toggle_voice()

    # ── State-Updates ──

    def _refresh_stats(self) -> None:
        """Aktualisiert Charakter-Stats in der Sidebar."""
        engine = self.gui.engine
        if not engine.character:
            return

        char = engine.character
        self._char_name.configure(text=char.name)

        for stat, (bar, lbl) in self._stat_bars.items():
            cur = char._stats.get(stat, 0)
            mx = char._stats_max.get(stat, 1)
            # Handle non-numeric stats (e.g. Paranoia "state_track")
            if not isinstance(cur, (int, float)):
                bar["value"] = 100
                lbl.configure(text=str(cur))
                continue
            if not isinstance(mx, (int, float)) or mx <= 0:
                mx = 1
            pct = (cur / mx * 100) if mx > 0 else 0
            bar["value"] = pct
            lbl.configure(text=f"{cur}/{mx}")

            if pct > 50:
                bar.configure(style="TProgressbar")
            elif pct > 25:
                bar.configure(style="Yellow.Horizontal.TProgressbar")
            else:
                bar.configure(style="Red.Horizontal.TProgressbar")

        # Skills Used
        if char._skills_used:
            self._skills_label.configure(
                text=", ".join(sorted(char._skills_used)),
            )

        # Inventar aus World State
        if engine._orchestrator and engine._orchestrator._archivist:
            ws = engine._orchestrator._archivist.get_world_state()
            inv_items = {k: v for k, v in ws.items() if k.startswith("inventar_") or k.startswith("item_")}
            self._inv_text.configure(state=tk.NORMAL)
            self._inv_text.delete("1.0", tk.END)
            if inv_items:
                for k, v in sorted(inv_items.items()):
                    self._inv_text.insert(tk.END, f"  {k}: {v}\n")
            else:
                self._inv_text.insert(tk.END, "  (leer)")
            self._inv_text.configure(state=tk.DISABLED)

    # ── Engine-Ready ──

    def on_engine_ready(self) -> None:
        """Wird aufgerufen wenn die Engine fertig initialisiert ist."""
        self._refresh_stats()
        self._set_input_state(True)

        # Location
        engine = self.gui.engine
        if hasattr(engine, "_adv_manager") and engine._adv_manager:
            loc = engine._adv_manager.get_current_location()
            if loc:
                self._loc_label.configure(text=f"{loc.get('name', '?')}")

    # ── EventBus Handler ──

    def handle_event(self, data: dict[str, Any]) -> None:
        """Verarbeitet Events vom EventBus."""
        event = data.get("_event", "")

        # Game-Output Events (vom Orchestrator)
        if event == "game.output":
            tag = data.get("tag", "")
            text = data.get("text", "")

            # ── Streaming: Keeper-Antwort Chunk fuer Chunk ──
            if tag == "stream_start":
                self._streaming = True
                self._append_timestamp()
                self._append_output("KEEPER: ", "label")

            elif tag == "stream_chunk":
                # Live-Chunk anfuegen (ohne Zeilenumbruch)
                self._append_output(text, "keeper")

            elif tag == "stream_end":
                self._streaming = False
                self._append_output("\n\n")

            # ── Spieler-Text (STT oder GUI) ──
            elif tag == "player":
                # Wurde der Text gerade ueber die GUI gesendet? -> nicht doppelt anzeigen
                if text == self._last_gui_input:
                    self._last_gui_input = None
                else:
                    # STT-Input oder anderer Kanal -> anzeigen
                    self._append_timestamp()
                    self._append_output("SPIELER: ", "label")
                    self._append_output(text + "\n", "player")

            # ── Wuerfelwurf: Geraeusch + Visualisierung ──
            elif tag == "dice":
                self._play_dice_sound()
                self._append_timestamp()
                self._append_output(text + "\n", tag)
                # Dice-Panel updaten: kombiniere mit letztem PROBE-Event
                probe_text = None
                if self._pending_probe:
                    probe_text = self._pending_probe.get("text")
                    self._pending_probe = None
                self._on_dice_event(probe_text, text)

            elif tag == "combat":
                self._play_dice_sound()
                self._append_timestamp()
                for line in text.split("\n"):
                    if not line.strip():
                        continue
                    if "TREFFER" in line or "GERETTET" in line:
                        self._append_output(line + "\n", "combat_hit")
                    elif "VERFEHLT" in line or "FEHLSCHLAG" in line or "PATZER" in line:
                        self._append_output(line + "\n", "combat_miss")
                    elif "Schaden:" in line or "[TOT]" in line:
                        self._append_output(line + "\n", "combat")
                    elif "->" in line and "(" in line:
                        # Header: Angreifer -> Ziel (Waffe)
                        self._append_output(line + "\n", "combat_state")
                    else:
                        self._append_output(line + "\n", "dice")

            elif tag == "initiative":
                self._append_timestamp()
                self._append_output(text + "\n", "combat_state")

            elif tag == "combat_state":
                self._append_output(text + "\n", "combat_state")

            elif tag == "rules_warning":
                self._append_timestamp()
                self._append_output(text + "\n", "rules_warning")

            elif tag == "probe":
                # Probe-Text merken fuer nachfolgendes "dice"-Event
                self._pending_probe = {"text": text}
                self._append_timestamp()
                self._append_output(text + "\n", tag)

            elif tag in ("stat", "fact", "system"):
                self._append_timestamp()
                self._append_output(text + "\n", tag)

            else:
                self._append_output(text + "\n")

        elif event == "game.waiting_for_input":
            self._set_input_state(True)

        elif event == "keeper.response_complete":
            self._refresh_stats()

        elif event == "keeper.usage_update":
            # Turn-Zaehler aktualisieren
            orch = self.gui.engine._orchestrator
            if orch:
                self._turn_label.configure(text=f"Turn: {orch._turn_number}")

        elif event == "adventure.location_changed":
            loc_name = data.get("location_name", "?")
            self._loc_label.configure(text=loc_name)

        elif event == "archivar.world_state_updated":
            # Inventar koennte sich geaendert haben
            self._refresh_stats()

        # ── Audio-Events (Mic-Level + STT-Text) ──
        elif event == "audio.mic_level":
            level = data.get("level", 0)
            vad = data.get("vad", 0)
            speech = data.get("speech", False)
            self._mic_level_bar["value"] = level
            if speech:
                self._mic_vad_label.configure(text="REC", fg=RED)
            elif vad > 0.2:
                self._mic_vad_label.configure(text="...", fg=YELLOW)
            else:
                self._mic_vad_label.configure(text="", fg=FG_MUTED)

        elif event == "audio.stt_text":
            text = data.get("text", "")
            if text:
                display = text if len(text) <= 80 else text[:77] + "..."
                self._stt_text_label.configure(text=display)
                # Reset nach 5 Sekunden
                self.after(5000, lambda: self._stt_text_label.configure(text="—"))
