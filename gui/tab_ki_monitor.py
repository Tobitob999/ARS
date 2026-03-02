"""
gui/tab_ki_monitor.py — Tab 3: KI-Monitor (Herzstueck)

Totale Transparenz ueber den KI-Kontext, aufgeteilt in drei Phasen:

Phase 1 — Statischer System-Prompt:
  Persona, Setting, Keeper, Character, Regeln, Abenteuer, Extras
  (wird einmal bei Session-Start gebaut und optional gecacht)

Phase 2 — Dynamischer Kontext (pro Turn):
  Archivar-Chronik, World State, Location-Kontext, Zeit, History
  (wird bei jedem chat_stream() in die Contents injiziert)

Phase 3 — Response-Verarbeitung (Live-Stream):
  KI-Antwort Streaming, Tag-Extraktion, Wuerfelergebnisse
  Token-Aufschluesselung pro Anfrage
"""

from __future__ import annotations

import logging
import re
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    CTX_SYSTEM_PROMPT, CTX_ARCHIVAR, CTX_LOCATION, CTX_HISTORY,
    STREAM_PLAYER, STREAM_KEEPER, STREAM_TAG, STREAM_PROBE, STREAM_ARCHIVAR,
    STREAM_WARNING, GREEN, RED, YELLOW, ORANGE, BLUE, LAVENDER,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, FONT_HEADER, PAD, PAD_SMALL, PAD_LARGE,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.ki_monitor")

# Tag-Regex fuer Phase 3 Response-Parsing
_TAG_PATTERN = re.compile(
    r"\[(?:FAKT|INVENTAR|PROBE|HP_VERLUST|STABILITAET_VERLUST|HP_HEILUNG"
    r"|XP_GEWINN|FERTIGKEIT_GENUTZT|STIMME|ZEIT_VERGEHT|TAGESZEIT|WETTER"
    r"|ANGRIFF|RETTUNGSWURF)"
    r":[^\]]*\]",
    re.IGNORECASE,
)

# Phase-1 Sektionsfarben (Hintergrund-Toene fuer visuelle Unterscheidung)
_P1_PERSONA = "#2D2D4F"
_P1_SETTING = "#2D3D2D"
_P1_KEEPER = "#3D2D3D"
_P1_CHARACTER = "#2D3D3D"
_P1_RULES = "#3D3D2D"
_P1_ADVENTURE = "#3D2D2D"
_P1_EXTRAS = "#2D2D3D"

# Phase-2 Rules-Engine Farben
_P2_RULES = "#2A3D2A"        # leichtes Gruen
_P2_RULES_INJECT = "#2A2D3D" # leichtes Blau fuer injizierte Sektionen
_P2_RULES_KW = "#3D3D1D"     # leichtes Gelb fuer Keywords


class KIMonitorTab(ttk.Frame):
    """KI-Monitor — 3-Phasen-Ansicht der Prompt-Generierung."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self._rules_injection_log: list[dict] = []
        self.configure(style="TFrame")
        self._build_ui()

    # ==================================================================
    # UI-Aufbau
    # ==================================================================

    def _build_ui(self) -> None:
        # Haupt-PanedWindow: drei Bereiche vertikal
        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        self._build_phase1(paned)
        self._build_phase2(paned)
        self._build_phase3(paned)

    # ── Phase 1: Statischer System-Prompt ─────────────────────────────

    def _build_phase1(self, paned: ttk.PanedWindow) -> None:
        frame = ttk.LabelFrame(
            paned, text=" Phase 1 — Statischer System-Prompt ", style="TLabelframe",
        )
        paned.add(frame, weight=1)

        # Toolbar
        toolbar = ttk.Frame(frame, style="TFrame")
        toolbar.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        # Sektions-Filter Checkbuttons
        self._p1_sections = {}
        for key, label in [
            ("persona", "Persona"),
            ("setting", "Setting"),
            ("keeper", "Keeper"),
            ("character", "Charakter"),
            ("rules", "Regeln"),
            ("adventure", "Abenteuer"),
            ("extras", "Extras"),
        ]:
            var = tk.BooleanVar(value=True)
            self._p1_sections[key] = var
            ttk.Checkbutton(
                toolbar, text=label, variable=var,
                command=self._refresh_phase1,
            ).pack(side=tk.LEFT, padx=PAD_SMALL)

        ttk.Button(
            toolbar, text="Refresh", command=self._refresh_phase1,
        ).pack(side=tk.RIGHT, padx=PAD_SMALL)

        # Info-Zeile: Prompt-Groesse + Cache-Status
        self._p1_info = tk.Label(
            frame, text="Prompt: — | Cache: —",
            bg=BG_PANEL, fg=FG_SECONDARY, font=FONT_SMALL, anchor=tk.W, padx=PAD,
        )
        self._p1_info.pack(fill=tk.X)

        # Text-Widget
        text_frame = ttk.Frame(frame, style="TFrame")
        text_frame.pack(fill=tk.BOTH, expand=True)

        self._p1_text = tk.Text(
            text_frame, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self._p1_text.yview)
        self._p1_text.configure(yscrollcommand=scroll.set)
        self._p1_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Farbkodierte Tags
        self._p1_text.tag_configure("persona", background=_P1_PERSONA, foreground=FG_PRIMARY)
        self._p1_text.tag_configure("setting", background=_P1_SETTING, foreground=FG_PRIMARY)
        self._p1_text.tag_configure("keeper", background=_P1_KEEPER, foreground=FG_PRIMARY)
        self._p1_text.tag_configure("character", background=_P1_CHARACTER, foreground=FG_PRIMARY)
        self._p1_text.tag_configure("rules", background=_P1_RULES, foreground=FG_PRIMARY)
        self._p1_text.tag_configure("adventure", background=_P1_ADVENTURE, foreground=FG_PRIMARY)
        self._p1_text.tag_configure("extras", background=_P1_EXTRAS, foreground=FG_PRIMARY)
        self._p1_text.tag_configure("header", foreground=FG_ACCENT, font=FONT_BOLD)
        self._p1_text.tag_configure("muted", foreground=FG_MUTED)
        self._p1_text.tag_configure("separator", foreground=FG_MUTED, font=FONT_SMALL)

    # ── Phase 2: Dynamischer Kontext ──────────────────────────────────

    def _build_phase2(self, paned: ttk.PanedWindow) -> None:
        frame = ttk.LabelFrame(
            paned, text=" Phase 2 — Dynamischer Kontext (pro Turn) ", style="TLabelframe",
        )
        paned.add(frame, weight=1)

        # Toolbar
        toolbar = ttk.Frame(frame, style="TFrame")
        toolbar.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        self._p2_sections = {}
        for key, label in [
            ("chronicle", "Chronik"),
            ("world_state", "World State"),
            ("location", "Location"),
            ("time", "Zeit"),
            ("rules", "Regeln"),
            ("history", "History"),
        ]:
            var = tk.BooleanVar(value=True)
            self._p2_sections[key] = var
            ttk.Checkbutton(
                toolbar, text=label, variable=var,
                command=self._refresh_phase2,
            ).pack(side=tk.LEFT, padx=PAD_SMALL)

        ttk.Button(
            toolbar, text="Refresh", command=self._refresh_phase2,
        ).pack(side=tk.RIGHT, padx=PAD_SMALL)

        # Info-Zeile
        self._p2_info = tk.Label(
            frame, text="Chronik: — | Fakten: — | History: — Turns",
            bg=BG_PANEL, fg=FG_SECONDARY, font=FONT_SMALL, anchor=tk.W, padx=PAD,
        )
        self._p2_info.pack(fill=tk.X)

        # Text-Widget
        text_frame = ttk.Frame(frame, style="TFrame")
        text_frame.pack(fill=tk.BOTH, expand=True)

        self._p2_text = tk.Text(
            text_frame, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self._p2_text.yview)
        self._p2_text.configure(yscrollcommand=scroll.set)
        self._p2_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Farbkodierte Tags
        self._p2_text.tag_configure("chronicle", background=CTX_ARCHIVAR, foreground=FG_PRIMARY)
        self._p2_text.tag_configure("world_state", background="#1A2A3A", foreground=FG_PRIMARY)
        self._p2_text.tag_configure("location", background=CTX_LOCATION, foreground=FG_PRIMARY)
        self._p2_text.tag_configure("time", background="#2A2A3D", foreground=FG_PRIMARY)
        self._p2_text.tag_configure("history", background=CTX_HISTORY, foreground=FG_PRIMARY)
        self._p2_text.tag_configure("header", foreground=FG_ACCENT, font=FONT_BOLD)
        self._p2_text.tag_configure("muted", foreground=FG_MUTED)
        self._p2_text.tag_configure("fact_key", foreground=BLUE, font=FONT_BOLD)
        self._p2_text.tag_configure("fact_val", foreground=GREEN)
        self._p2_text.tag_configure("rules_section", background=_P2_RULES, foreground=FG_PRIMARY)
        self._p2_text.tag_configure("rules_category", foreground=ORANGE, font=FONT_BOLD)
        self._p2_text.tag_configure("rules_id", foreground=BLUE)
        self._p2_text.tag_configure("rules_text", foreground=FG_SECONDARY)
        self._p2_text.tag_configure("rules_injected", background=_P2_RULES_INJECT, foreground=FG_PRIMARY)
        self._p2_text.tag_configure("rules_keyword", foreground=YELLOW, font=FONT_BOLD)
        self._p2_text.tag_configure("rules_budget", foreground=GREEN)
        self._p2_text.tag_configure("rules_log", foreground=FG_MUTED, font=FONT_SMALL)

    # ── Phase 3: Response-Verarbeitung / Live-Stream ──────────────────

    def _build_phase3(self, paned: ttk.PanedWindow) -> None:
        frame = ttk.LabelFrame(
            paned, text=" Phase 3 — Response-Verarbeitung (Live-Stream) ", style="TLabelframe",
        )
        paned.add(frame, weight=2)

        # Text-Widget
        text_frame = ttk.Frame(frame, style="TFrame")
        text_frame.pack(fill=tk.BOTH, expand=True)

        self._p3_text = tk.Text(
            text_frame, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_NORMAL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self._p3_text.yview)
        self._p3_text.configure(yscrollcommand=scroll.set)
        self._p3_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Farbkodierte Tags fuer Live-Stream
        self._p3_text.tag_configure("player", foreground=STREAM_PLAYER, font=FONT_BOLD)
        self._p3_text.tag_configure("keeper", foreground=STREAM_KEEPER)
        self._p3_text.tag_configure("tag", foreground=STREAM_TAG, font=FONT_BOLD)
        self._p3_text.tag_configure("probe", foreground=STREAM_PROBE, font=FONT_BOLD)
        self._p3_text.tag_configure("dice", foreground=ORANGE, font=FONT_BOLD)
        self._p3_text.tag_configure("stat", foreground=YELLOW)
        self._p3_text.tag_configure("combat", foreground=RED, font=FONT_BOLD)
        self._p3_text.tag_configure("combat_hit", foreground=ORANGE, font=FONT_BOLD)
        self._p3_text.tag_configure("combat_miss", foreground=FG_MUTED, font=FONT_BOLD)
        self._p3_text.tag_configure("inventory", foreground=GREEN)
        self._p3_text.tag_configure("time_event", foreground=LAVENDER)
        self._p3_text.tag_configure("fact", foreground=BLUE)
        self._p3_text.tag_configure("archivar", foreground=STREAM_ARCHIVAR)
        self._p3_text.tag_configure("warning", foreground=STREAM_WARNING)
        self._p3_text.tag_configure("label", foreground=FG_MUTED, font=FONT_SMALL)
        self._p3_text.tag_configure("timestamp", foreground=FG_MUTED, font=FONT_SMALL)
        self._p3_text.tag_configure("tag_header", foreground=LAVENDER, font=FONT_BOLD)

        # Token-Aufschluesselung (untere Leiste)
        token_bar = tk.Frame(frame, bg=BG_PANEL, height=24)
        token_bar.pack(fill=tk.X, side=tk.BOTTOM)
        token_bar.pack_propagate(False)
        self._token_info = tk.Label(
            token_bar,
            text="Prompt: — | Cached: — | Output: — | Think: — | Kosten: —",
            bg=BG_PANEL, fg=FG_SECONDARY, font=FONT_SMALL, anchor=tk.W, padx=PAD,
        )
        self._token_info.pack(fill=tk.X)

    # ==================================================================
    # Phase 1 — Refresh: System-Prompt sektionsweise darstellen
    # ==================================================================

    def _refresh_phase1(self) -> None:
        """Laedt den System-Prompt und zeigt ihn sektionsweise farbkodiert an."""
        engine = self.gui.engine
        self._p1_text.configure(state=tk.NORMAL)
        self._p1_text.delete("1.0", tk.END)

        if not engine.ai_backend:
            self._p1_text.insert(tk.END, "(Engine nicht initialisiert)\n", "muted")
            self._p1_text.configure(state=tk.DISABLED)
            self._p1_info.configure(text="Prompt: — | Cache: —")
            return

        backend = engine.ai_backend
        prompt = getattr(backend, "_system_prompt", "")
        cache_name = getattr(backend, "_cache_name", None)
        token_est = len(prompt) // 4

        cache_status = "aktiv" if cache_name else "inaktiv"
        self._p1_info.configure(
            text=f"Prompt: {len(prompt):,} Zeichen (~{token_est:,} Tokens) | "
                 f"Cache: {cache_status}",
        )

        if not prompt:
            self._p1_text.insert(tk.END, "(Kein System-Prompt vorhanden)\n", "muted")
            self._p1_text.configure(state=tk.DISABLED)
            return

        # Prompt in Sektionen aufteilen anhand der ═══ Header ═══
        sections = self._parse_prompt_sections(prompt)

        for section_key, section_title, section_text in sections:
            # Pruefen ob Sektion angezeigt werden soll
            if not self._p1_sections.get(section_key, tk.BooleanVar(value=True)).get():
                continue

            char_count = len(section_text)
            tok_est = char_count // 4

            self._p1_text.insert(
                tk.END,
                f"\u2588\u2588 {section_title} ({char_count:,} Z. / ~{tok_est:,} Tok.)\n",
                "header",
            )
            self._p1_text.insert(tk.END, section_text + "\n", section_key)
            self._p1_text.insert(tk.END, "\n", "separator")

        self._p1_text.configure(state=tk.DISABLED)

    def _parse_prompt_sections(self, prompt: str) -> list[tuple[str, str, str]]:
        """
        Zerteilt den System-Prompt in benannte Sektionen.
        Gibt Liste von (key, title, text) zurueck.

        Mapping der ═══-Header auf Phase-1-Kategorien:
        """
        # Sektions-Mapping: Header-Substring -> (key, display_title)
        header_map = [
            ("DEINE PERSONA", "persona", "Persona & Philosophie"),
            ("SETTING & WELT", "setting", "Setting & Welt"),
            ("SPIELERCHARAKTER", "character", "Spielercharakter"),
            ("STIL & TTS-REGELN", "rules", "Stil & TTS-Regeln"),
            ("WUERFELPROBEN-PROTOKOLL", "rules", "Wuerfelproben-Protokoll"),
            ("CHARAKTER-ZUSTAND-PROTOKOLL", "rules", "Charakter-Zustand-Protokoll"),
            ("FAKTEN-PROTOKOLL", "rules", "Fakten-Protokoll"),
            ("INVENTAR-PROTOKOLL", "rules", "Inventar-Protokoll"),
            ("STIMMEN-WECHSEL", "rules", "Stimmen-Wechsel"),
            ("ZEIT-PROTOKOLL", "rules", "Zeit-Protokoll"),
            ("REGELWERK-REFERENZ", "rules", "Regelwerk-Referenz"),
            ("AKTIVES ABENTEUER", "adventure", "Abenteuer (Keeper-Wissen)"),
            ("ZUSAETZLICHE REGELN", "extras", "Extras / Zusatz-Regeln"),
            ("ABSOLUTES VERBOT", "rules", "Absolutes Verbot"),
        ]

        # Alle ═══ Header-Positionen finden
        header_re = re.compile(r"^═══\s*(.+?)\s*═══\s*$", re.MULTILINE)
        matches = list(header_re.finditer(prompt))

        if not matches:
            # Fallback: ganzen Prompt als eine Sektion
            return [("persona", "System-Prompt (ungeparst)", prompt)]

        result: list[tuple[str, str, str]] = []

        # Text vor erstem Header = Persona-Preamble
        preamble = prompt[:matches[0].start()].strip()
        if preamble:
            result.append(("persona", "Persona & Philosophie", preamble))

        for i, match in enumerate(matches):
            header_text = match.group(1).strip()

            # Text dieser Sektion: von Ende des Headers bis zum naechsten Header
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(prompt)
            body = prompt[start:end].strip()

            # Kategorie bestimmen
            key, title = "rules", header_text
            for substring, mapped_key, mapped_title in header_map:
                if substring in header_text.upper():
                    key = mapped_key
                    title = mapped_title
                    break

            # Preamble mit erstem Persona-Header zusammenfuehren
            if key == "persona" and result and result[-1][0] == "persona":
                prev_key, prev_title, prev_text = result.pop()
                body = prev_text + "\n\n═══ " + header_text + " ═══\n" + body
                title = prev_title

            result.append((key, title, body))

        return result

    # ==================================================================
    # Phase 2 — Refresh: Dynamischer Kontext
    # ==================================================================

    def _refresh_phase2(self) -> None:
        """Laedt den aktuellen dynamischen Kontext und zeigt ihn an."""
        engine = self.gui.engine
        self._p2_text.configure(state=tk.NORMAL)
        self._p2_text.delete("1.0", tk.END)

        if not engine.ai_backend:
            self._p2_text.insert(tk.END, "(Engine nicht initialisiert)\n", "muted")
            self._p2_text.configure(state=tk.DISABLED)
            self._p2_info.configure(text="Chronik: — | Fakten: — | History: — Turns")
            return

        backend = engine.ai_backend
        archivist = getattr(backend, "_archivist", None)
        adv_mgr = getattr(backend, "_adv_manager", None)
        time_tracker = getattr(backend, "_time_tracker", None)
        history = getattr(backend, "_history", [])

        # Zaehler fuer Info-Zeile
        chr_len = 0
        fact_count = 0
        hist_turns = len(history) // 2

        # ── Chronik ──
        if self._p2_sections["chronicle"].get() and archivist:
            chronicle = archivist.get_chronicle()
            if chronicle:
                chr_len = len(chronicle)
                self._p2_text.insert(
                    tk.END,
                    f"\u2588\u2588 CHRONIK ({chr_len:,} Zeichen)\n",
                    "header",
                )
                self._p2_text.insert(tk.END, chronicle + "\n\n", "chronicle")
            else:
                self._p2_text.insert(
                    tk.END, "\u2588\u2588 CHRONIK (noch leer)\n\n", "muted",
                )

        # ── World State ──
        if self._p2_sections["world_state"].get() and archivist:
            ws = archivist.get_world_state()
            fact_count = len(ws)
            if ws:
                self._p2_text.insert(
                    tk.END,
                    f"\u2588\u2588 WORLD STATE ({fact_count} Fakten)\n",
                    "header",
                )
                for k, v in sorted(ws.items()):
                    self._p2_text.insert(tk.END, f"  {k}", "fact_key")
                    self._p2_text.insert(tk.END, f" = {v}\n", "fact_val")
                self._p2_text.insert(tk.END, "\n")
            else:
                self._p2_text.insert(
                    tk.END, "\u2588\u2588 WORLD STATE (noch leer)\n\n", "muted",
                )

        # ── Location-Kontext ──
        if self._p2_sections["location"].get() and adv_mgr:
            if adv_mgr.loaded:
                loc_ctx = adv_mgr.get_location_context()
                if loc_ctx:
                    loc = adv_mgr.get_current_location()
                    loc_name = loc.get("name", "?") if loc else "?"
                    self._p2_text.insert(
                        tk.END,
                        f"\u2588\u2588 LOCATION: {loc_name}\n",
                        "header",
                    )
                    self._p2_text.insert(tk.END, loc_ctx + "\n\n", "location")

        # ── Zeit-Kontext ──
        if self._p2_sections["time"].get() and time_tracker:
            time_ctx = time_tracker.get_context_for_prompt()
            if time_ctx:
                self._p2_text.insert(tk.END, "\u2588\u2588 ZEIT & WETTER\n", "header")
                self._p2_text.insert(tk.END, time_ctx + "\n\n", "time")

        # ── Rules Engine Kontext ──
        rules_section_count = 0
        if self._p2_sections["rules"].get():
            rules_engine = getattr(engine, "rules_engine", None)
            if rules_engine:
                sections = rules_engine.get_all_sections()
                rules_section_count = len(sections)
                total_chars = sum(s.char_count for s in sections)
                max_budget = getattr(rules_engine, "_rules_budget",
                                     rules_engine.DEFAULT_RULES_BUDGET)

                # ── Block A: Letzte Injection ──
                if self._rules_injection_log:
                    last = self._rules_injection_log[-1]
                    last_sections = last["sections"]
                    last_kw = last["keywords"]
                    last_chars = last["char_count"]
                    # Use budget from event if available, otherwise engine default
                    event_budget = last.get("budget", max_budget)
                    pct = min(100, int(last_chars / event_budget * 100))
                    bar_filled = pct // 5
                    bar_empty = 20 - bar_filled
                    bar = "\u2593" * bar_filled + "\u2591" * bar_empty

                    self._p2_text.insert(
                        tk.END,
                        f"\u2588\u2588 LETZTE INJECTION ({last['timestamp']})\n",
                        "header",
                    )
                    # Keywords
                    self._p2_text.insert(tk.END, "  Keywords: ", "muted")
                    self._p2_text.insert(
                        tk.END,
                        ", ".join(last_kw) + "\n",
                        "rules_keyword",
                    )
                    # Budget-Balken
                    self._p2_text.insert(tk.END, "  Budget:   ", "muted")
                    self._p2_text.insert(
                        tk.END,
                        f"{bar} {last_chars}/{event_budget} Z. ({pct}%)\n",
                        "rules_budget",
                    )
                    # Injizierte Sektionen mit vollem Text
                    self._p2_text.insert(tk.END, "  Sektionen:\n", "muted")
                    for sid in last_sections:
                        s = rules_engine.get_section(sid)
                        if s:
                            self._p2_text.insert(
                                tk.END, f"    [{s.section_id}] ", "rules_id",
                            )
                            self._p2_text.insert(
                                tk.END, f"{s.text}\n", "rules_injected",
                            )
                    self._p2_text.insert(tk.END, "\n")

                # ── Block B: Verfuegbare Sektionen (nach Kategorie) ──
                self._p2_text.insert(
                    tk.END,
                    f"\u2588\u2588 REGEL-INDEX ({rules_section_count} Sektionen, {total_chars:,} Z.)\n",
                    "header",
                )
                # Gruppieren nach Kategorie
                categories: dict[str, list] = {}
                for s in sections:
                    categories.setdefault(s.category, []).append(s)
                for cat in sorted(categories.keys()):
                    cat_sections = categories[cat]
                    cat_chars = sum(s.char_count for s in cat_sections)
                    self._p2_text.insert(
                        tk.END,
                        f"  {cat.upper()} ({len(cat_sections)} Sekt., {cat_chars} Z.)\n",
                        "rules_category",
                    )
                    for s in cat_sections:
                        self._p2_text.insert(
                            tk.END, f"    [{s.section_id}] ", "rules_id",
                        )
                        self._p2_text.insert(
                            tk.END, f"{s.text}\n", "rules_text",
                        )
                self._p2_text.insert(tk.END, "\n")

                # ── Block C: Injection-Log (letzte 10) ──
                if self._rules_injection_log:
                    self._p2_text.insert(
                        tk.END,
                        f"\u2588\u2588 INJECTION-LOG ({len(self._rules_injection_log)} Eintraege)\n",
                        "header",
                    )
                    for entry in reversed(self._rules_injection_log[-10:]):
                        ts = entry["timestamp"]
                        n = len(entry["sections"])
                        kw = ", ".join(entry["keywords"][:3])
                        chars = entry["char_count"]
                        self._p2_text.insert(
                            tk.END,
                            f"  {ts} | {n} Sekt. | {chars} Z. | [{kw}]\n",
                            "rules_log",
                        )
                    self._p2_text.insert(tk.END, "\n")

        # ── History ──
        if self._p2_sections["history"].get() and history:
            self._p2_text.insert(
                tk.END,
                f"\u2588\u2588 HISTORY ({len(history)} Nachrichten / ~{hist_turns} Turns)\n",
                "header",
            )
            for entry in history[-20:]:
                role = entry.get("role", "?")
                content = entry.get("content", "")
                prefix = "[USR]" if role == "user" else "[KI] "
                if len(content) > 300:
                    content = content[:300] + "..."
                self._p2_text.insert(tk.END, f"{prefix} {content}\n", "history")
            if len(history) > 20:
                self._p2_text.insert(
                    tk.END,
                    f"  ... ({len(history) - 20} aeltere Eintraege ausgeblendet)\n",
                    "muted",
                )
            self._p2_text.insert(tk.END, "\n")

        # Info-Zeile aktualisieren
        inj_count = len(self._rules_injection_log)
        rules_info = (
            f" | Regeln: {rules_section_count} Sekt. ({inj_count} Inj.)"
            if rules_section_count else ""
        )
        self._p2_info.configure(
            text=f"Chronik: {chr_len:,} Z. | "
                 f"Fakten: {fact_count}"
                 f"{rules_info}"
                 f" | History: {hist_turns} Turns",
        )

        self._p2_text.configure(state=tk.DISABLED)

    # ==================================================================
    # Phase 3 — Live-Stream Hilfsmethoden
    # ==================================================================

    def _p3_append(self, text: str, tag: str = "") -> None:
        """Fuegt Text zum Phase-3 Live-Stream hinzu."""
        self._p3_text.configure(state=tk.NORMAL)
        if tag:
            self._p3_text.insert(tk.END, text, tag)
        else:
            self._p3_text.insert(tk.END, text)
        self._p3_text.see(tk.END)
        self._p3_text.configure(state=tk.DISABLED)

    def _p3_timestamp(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._p3_append(f"[{now}] ", "timestamp")

    # ==================================================================
    # EventBus Handler — alle Phasen
    # ==================================================================

    def handle_event(self, data: dict[str, Any]) -> None:
        """Verarbeitet Events vom EventBus und verteilt auf die drei Phasen."""
        event = data.get("_event", "")

        # ── Phase 3: Live-Stream Events ──────────────────────────────

        if event == "keeper.prompt_sent":
            # Spieler-Eingabe -> Phase 3 Stream
            self._p3_timestamp()
            self._p3_append("\u25b6 SPIELER: ", "label")
            msg = data.get("user_message", "")
            self._p3_append(msg + "\n", "player")
            # Phase 2 aktualisieren (Kontext aendert sich pro Turn)
            self._refresh_phase2()

        elif event == "keeper.response_complete":
            # KI-Antwort komplett -> Phase 3 Stream + Tag-Analyse
            self._p3_timestamp()
            self._p3_append("\u25c0 KEEPER: ", "label")
            response = data.get("response", "")

            # Tags extrahieren und separat darstellen
            tags_found = _TAG_PATTERN.findall(response)
            clean_text = _TAG_PATTERN.sub("", response).strip()

            self._p3_append(clean_text + "\n", "keeper")

            if tags_found:
                self._p3_append("  \u2192 TAGS: ", "tag_header")
                for t in tags_found:
                    if t.upper().startswith("[PROBE"):
                        self._p3_append(t + " ", "probe")
                    elif "FAKT" in t.upper():
                        self._p3_append(t + " ", "fact")
                    elif "HP_VERLUST" in t.upper() or "STABILITAET" in t.upper():
                        self._p3_append(t + " ", "stat")
                    elif "HP_HEILUNG" in t.upper() or "XP_GEWINN" in t.upper():
                        self._p3_append(t + " ", "stat")
                    else:
                        self._p3_append(t + " ", "tag")
                self._p3_append("\n")

            self._p3_append("\n")

        elif event == "keeper.usage_update":
            # Token-Aufschluesselung -> Phase 3 Info-Leiste
            prompt = data.get("prompt_tokens", 0)
            cached = data.get("cached_tokens", 0)
            output = data.get("candidates_tokens", 0)
            think = data.get("thoughts_tokens", 0)
            cost = data.get("cost_request", 0.0)
            session = data.get("session", {})
            session_cost = data.get("session_cost", 0.0)
            self._token_info.configure(
                text=f"Prompt: {prompt:,} | Cached: {cached:,} | "
                     f"Output: {output:,} | Think: {think:,} | "
                     f"Req: ${cost:.4f} | Session: ${session_cost:.4f}",
            )

        elif event == "keeper.context_injected":
            # Kontext-Injektion (dynamisch) -> Phase 3 kurze Notiz
            sources = data.get("sources", [])
            if sources:
                self._p3_timestamp()
                self._p3_append("  \u21b3 Kontext: ", "label")
                for src in sources:
                    origin = src.get("origin", "?")
                    length = len(src.get("content", ""))
                    self._p3_append(f"[{origin}: {length} Z.] ", "archivar")
                self._p3_append("\n")
            # Phase 2 aktualisieren
            self._refresh_phase2()

        # ── Phase 2 / Phase 3: Archivar-Events ────────────────────────

        elif event == "archivar.chronicle_updated":
            self._p3_timestamp()
            self._p3_append("\u270d CHRONIK: ", "label")
            preview = data.get("preview", "")
            self._p3_append(f"Zusammenfassung aktualisiert: {preview}\n", "archivar")
            self._refresh_phase2()

        elif event == "archivar.world_state_updated":
            facts = data.get("new_facts", {})
            if facts:
                self._p3_timestamp()
                self._p3_append("\u270d FAKT: ", "label")
                facts_str = ", ".join(f"{k}={v}" for k, v in facts.items())
                self._p3_append(f"{facts_str}\n", "fact")
                self._refresh_phase2()

        # ── Phase 2 / Phase 3: Adventure-Events ──────────────────────

        elif event == "adventure.location_changed":
            loc = data.get("location_name", "?")
            loc_id = data.get("location_id", "?")
            self._p3_timestamp()
            self._p3_append(f"  \u279c Location: {loc} ({loc_id})\n", "tag")
            self._refresh_phase2()

        elif event == "adventure.flag_changed":
            key = data.get("flag", "?")
            val = data.get("value", "?")
            self._p3_timestamp()
            self._p3_append(f"  \u2691 Flag: {key} = {val}\n", "tag")

        # ── Phase 3: Game-Events (Wuerfel, Stats) ────────────────────

        elif event == "game.output":
            tag = data.get("tag", "")
            text = data.get("text", "")
            if tag == "probe":
                self._p3_timestamp()
                self._p3_append(f"  \u2684 {text}\n", "probe")
            elif tag == "dice":
                self._p3_timestamp()
                self._p3_append(f"  \u2684 {text}\n", "dice")
            elif tag == "combat":
                self._p3_timestamp()
                for line in text.split("\n"):
                    if not line.strip():
                        continue
                    if "TREFFER" in line or "GERETTET" in line:
                        self._p3_append(f"  \u2694 {line}\n", "combat_hit")
                    elif "VERFEHLT" in line or "FEHLSCHLAG" in line or "PATZER" in line:
                        self._p3_append(f"  \u2694 {line}\n", "combat_miss")
                    elif "Schaden:" in line or "[TOT]" in line:
                        self._p3_append(f"  \u2694 {line}\n", "combat")
                    elif "->" in line and "(" in line:
                        self._p3_append(f"  \u2694 {line}\n", "tag_header")
                    else:
                        self._p3_append(f"    {line}\n", "dice")
            elif tag == "initiative":
                self._p3_timestamp()
                self._p3_append(f"  \u2694 {text}\n", "tag_header")
            elif tag == "combat_state":
                self._p3_timestamp()
                for line in text.split("\n"):
                    if not line.strip():
                        continue
                    if "[TOT]" in line:
                        self._p3_append(f"  {line}\n", "combat_miss")
                    elif "[SPIELER]" in line:
                        self._p3_append(f"  {line}\n", "probe")
                    elif "===" in line:
                        self._p3_append(f"  {line}\n", "tag_header")
                    else:
                        self._p3_append(f"  {line}\n", "combat")
            elif tag == "stat":
                self._p3_timestamp()
                self._p3_append(f"  {text}\n", "stat")
            elif tag == "inventory":
                self._p3_timestamp()
                self._p3_append(f"  {text}\n", "inventory")
            elif tag == "time":
                self._p3_timestamp()
                self._p3_append(f"  {text}\n", "time_event")
            elif tag == "fact":
                self._p3_timestamp()
                self._p3_append(f"  {text}\n", "fact")
            elif tag == "rules_warning":
                self._p3_timestamp()
                self._p3_append(f"  \u2696 {text}\n", "warning")
            elif tag == "system":
                self._p3_timestamp()
                self._p3_append(f"  {text}\n", "warning")

        # ── Rules Engine Events ──────────────────────────────────────

        elif event == "rules.section_injected":
            sections = data.get("sections", [])
            char_count = data.get("char_count", 0)
            keywords = data.get("keywords_matched", [])
            # Injection-Log speichern (max 20)
            self._rules_injection_log.append({
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "sections": sections,
                "keywords": keywords,
                "char_count": char_count,
                "budget": data.get("budget", 6000),
                "permanent_count": data.get("permanent_count", 0),
            })
            if len(self._rules_injection_log) > 20:
                self._rules_injection_log = self._rules_injection_log[-20:]
            # Phase 3: kurze Notiz
            self._p3_timestamp()
            self._p3_append("  \u2696 Regeln: ", "label")
            self._p3_append(
                f"{len(sections)} Sektionen ({char_count} Z.) "
                f"[{', '.join(keywords[:5])}]\n",
                "tag",
            )
            self._refresh_phase2()

        elif event == "rules.validation_warning":
            tag_type = data.get("tag_type", "?")
            severity = data.get("severity", "warning")
            message = data.get("message", "")
            self._p3_timestamp()
            prefix = "\u26a0" if severity == "warning" else "\u2718"
            self._p3_append(f"  {prefix} REGEL: [{tag_type}] {message}\n", "warning")

    # ==================================================================
    # Oeffentliche API (aufgerufen von TechGUI bei Engine-Ready)
    # ==================================================================

    def on_engine_ready(self) -> None:
        """Wird aufgerufen wenn die Engine initialisiert ist."""
        self._refresh_phase1()
        self._refresh_phase2()
