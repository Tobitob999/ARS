"""
gui/tab_responder.py — Responder: Response-Parsing Spielwiese

Technische Werkbank fuer alles, was AUS der KI kommt:
- Test-Text eingeben und alle Tag-Extraktoren live durchlaufen lassen
- Ergebnisse farbkodiert anzeigen: Proben, HP/SAN, Fakten, Inventar, Stimmen, Zeit
- Clean-Text (narrativ, Tags entfernt) vs. Raw-Text Vergleich
- Live-Feed aus laufender Session
"""

from __future__ import annotations

import json
import logging
import re
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE, BLUE, LAVENDER,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, FONT_HEADER, PAD, PAD_SMALL, PAD_LARGE,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.responder")

# ── Alle Tag-Regex-Patterns (gespiegelt aus core/) ────────────────────

_PROBE_RE = re.compile(
    r"\[PROBE:\s*([^\|]+)\|\s*(\d+)\s*\]", re.IGNORECASE,
)
_HP_LOSS_RE = re.compile(r"\[HP_VERLUST:\s*(\d+)\s*\]", re.IGNORECASE)
_HP_HEAL_RE = re.compile(r"\[HP_HEILUNG:\s*(\d+d\d+|\d+)\s*\]", re.IGNORECASE)
_SAN_LOSS_RE = re.compile(
    r"\[STABILITAET_VERLUST:\s*(\d+d\d+|\d+)\s*\]", re.IGNORECASE,
)
_XP_GAIN_RE = re.compile(r"\[XP_GEWINN:\s*(\d+)\s*\]", re.IGNORECASE)
_SKILL_USED_RE = re.compile(r"\[FERTIGKEIT_GENUTZT:\s*([^\]]+)\s*\]", re.IGNORECASE)
_FAKT_RE = re.compile(r"\[FAKT:\s*(\{[^}]*\})\s*\]", re.IGNORECASE)
_INVENTAR_RE = re.compile(
    r"\[INVENTAR:\s*([^\|]+)\|\s*(gefunden|verloren|erledigt)\s*\]", re.IGNORECASE,
)
_STIMME_RE = re.compile(r"\[STIMME:(\w+)\]", re.IGNORECASE)
_ZEIT_RE = re.compile(r"\[ZEIT_VERGEHT:\s*([\d.]+)h\s*\]", re.IGNORECASE)
_TAGESZEIT_RE = re.compile(r"\[TAGESZEIT:\s*(\d{1,2}:\d{2})\s*\]", re.IGNORECASE)
_WETTER_RE = re.compile(r"\[WETTER:\s*([^\]]+)\s*\]", re.IGNORECASE)

# Alle Tags zusammen (fuer Strip)
_ALL_TAGS_RE = re.compile(
    r"\[(?:PROBE|HP_VERLUST|HP_HEILUNG|STABILITAET_VERLUST|XP_GEWINN"
    r"|FERTIGKEIT_GENUTZT|FAKT|INVENTAR|STIMME|ZEIT_VERGEHT|TAGESZEIT|WETTER)"
    r":[^\]]*\]",
    re.IGNORECASE,
)

# Beispieltext zum Testen
_EXAMPLE_TEXT = (
    "Die schwere Eichentuer knarrt, als du sie aufstosst. "
    "Der Geruch von Moder und altem Papier schlaegt dir entgegen. "
    "Im Schein deiner Laterne erkennst du ein verstaubtes Arbeitszimmer. "
    "Auf dem Schreibtisch liegt ein ledergebundenes Tagebuch. "
    "Etwas stimmt hier nicht. Die Schatten scheinen sich zu bewegen.\n\n"
    "[STIMME:mystery] \"Wer stoert meine Ruhe...\" [STIMME:keeper] "
    "Die Stimme verhallt. War das Einbildung?\n\n"
    "Was tust du?\n\n"
    "[PROBE: Wahrnehmung | 55]\n"
    "[ZEIT_VERGEHT: 0.5h]\n"
    "[WETTER: dichter Nebel]\n"
    "[INVENTAR: Altes Tagebuch | gefunden]\n"
    "[FAKT: {\"arbeitszimmer_betreten\": true}]\n"
    "[STABILITAET_VERLUST: 1d3]\n"
    "[FERTIGKEIT_GENUTZT: Wahrnehmung]"
)


class ResponderTab(ttk.Frame):
    """Response-Parsing Spielwiese — alles was AUS der KI kommt."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")
        self._build_ui()

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self) -> None:
        # Haupt-Paned: Oben Eingabe+Analyse, Unten Live-Feed
        main_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        # ── Oberer Bereich: Eingabe + Analyse ──
        top_paned = ttk.PanedWindow(main_paned, orient=tk.HORIZONTAL)
        main_paned.add(top_paned, weight=2)

        # Links: Eingabe
        input_frame = ttk.LabelFrame(
            top_paned, text=" KI-Response (Test-Eingabe) ", style="TLabelframe",
        )
        top_paned.add(input_frame, weight=1)

        # Toolbar
        input_toolbar = ttk.Frame(input_frame, style="TFrame")
        input_toolbar.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        ttk.Button(
            input_toolbar, text="Analysieren", command=self._analyze,
            style="Accent.TButton",
        ).pack(side=tk.LEFT, padx=PAD_SMALL)
        ttk.Button(
            input_toolbar, text="Beispiel laden", command=self._load_example,
        ).pack(side=tk.LEFT, padx=PAD_SMALL)
        ttk.Button(
            input_toolbar, text="Leeren", command=self._clear_input,
        ).pack(side=tk.LEFT, padx=PAD_SMALL)

        # Eingabe-Text
        tf = ttk.Frame(input_frame, style="TFrame")
        tf.pack(fill=tk.BOTH, expand=True)

        self._input_text = tk.Text(
            tf, bg=BG_INPUT, fg=FG_PRIMARY, font=FONT_NORMAL,
            wrap=tk.WORD, highlightthickness=0, borderwidth=0,
            padx=PAD, pady=PAD, insertbackground=FG_PRIMARY,
        )
        ts = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._input_text.yview)
        self._input_text.configure(yscrollcommand=ts.set)
        self._input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ts.pack(side=tk.RIGHT, fill=tk.Y)

        # Beispiel vorausfuellen
        self._input_text.insert("1.0", _EXAMPLE_TEXT)

        # Rechts: Analyse-Ergebnisse
        result_frame = ttk.LabelFrame(
            top_paned, text=" Analyse-Ergebnisse ", style="TLabelframe",
        )
        top_paned.add(result_frame, weight=1)

        # Ergebnis-Info
        self._result_info = tk.Label(
            result_frame, text="Tags: — | Clean: — Zeichen",
            bg=BG_PANEL, fg=FG_SECONDARY, font=FONT_SMALL, anchor=tk.W, padx=PAD,
        )
        self._result_info.pack(fill=tk.X)

        rf = ttk.Frame(result_frame, style="TFrame")
        rf.pack(fill=tk.BOTH, expand=True)

        self._result_text = tk.Text(
            rf, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        rs = ttk.Scrollbar(rf, orient=tk.VERTICAL, command=self._result_text.yview)
        self._result_text.configure(yscrollcommand=rs.set)
        self._result_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rs.pack(side=tk.RIGHT, fill=tk.Y)

        # Farbkodierte Tags
        self._result_text.tag_configure("header", foreground=FG_ACCENT, font=FONT_BOLD)
        self._result_text.tag_configure("muted", foreground=FG_MUTED)
        self._result_text.tag_configure("clean", foreground=LAVENDER)
        self._result_text.tag_configure("probe", foreground=RED, font=FONT_BOLD)
        self._result_text.tag_configure("stat", foreground=YELLOW)
        self._result_text.tag_configure("stat_heal", foreground=GREEN)
        self._result_text.tag_configure("fact", foreground=BLUE)
        self._result_text.tag_configure("inventar_add", foreground=GREEN)
        self._result_text.tag_configure("inventar_del", foreground=RED)
        self._result_text.tag_configure("inventar_done", foreground=YELLOW)
        self._result_text.tag_configure("voice", foreground=ORANGE)
        self._result_text.tag_configure("time", foreground=FG_ACCENT)
        self._result_text.tag_configure("ok", foreground=GREEN, font=FONT_BOLD)
        self._result_text.tag_configure("warn", foreground=YELLOW, font=FONT_BOLD)
        self._result_text.tag_configure("error_tag", foreground=RED, font=FONT_BOLD)

        # ── Unterer Bereich: Live-Feed ──
        live_frame = ttk.LabelFrame(
            main_paned, text=" Live-Feed (laufende Session) ", style="TLabelframe",
        )
        main_paned.add(live_frame, weight=1)

        lf = ttk.Frame(live_frame, style="TFrame")
        lf.pack(fill=tk.BOTH, expand=True)

        self._live_text = tk.Text(
            lf, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        ls = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self._live_text.yview)
        self._live_text.configure(yscrollcommand=ls.set)
        self._live_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ls.pack(side=tk.RIGHT, fill=tk.Y)

        self._live_text.tag_configure("timestamp", foreground=FG_MUTED, font=FONT_SMALL)
        self._live_text.tag_configure("label", foreground=FG_MUTED, font=FONT_SMALL)
        self._live_text.tag_configure("raw", foreground=FG_SECONDARY)
        self._live_text.tag_configure("probe", foreground=RED, font=FONT_BOLD)
        self._live_text.tag_configure("stat", foreground=YELLOW)
        self._live_text.tag_configure("fact", foreground=BLUE)
        self._live_text.tag_configure("voice", foreground=ORANGE)
        self._live_text.tag_configure("time", foreground=FG_ACCENT)
        self._live_text.tag_configure("inventar", foreground=GREEN)
        self._live_text.tag_configure("action", foreground=LAVENDER, font=FONT_BOLD)

    # ==================================================================
    # Beispiel laden / leeren
    # ==================================================================

    def _load_example(self) -> None:
        self._input_text.delete("1.0", tk.END)
        self._input_text.insert("1.0", _EXAMPLE_TEXT)

    def _clear_input(self) -> None:
        self._input_text.delete("1.0", tk.END)

    # ==================================================================
    # Analyse-Kernlogik
    # ==================================================================

    def _analyze(self) -> None:
        """Analysiert den eingegebenen Text und zeigt alle extrahierten Tags."""
        text = self._input_text.get("1.0", tk.END).strip()
        if not text:
            return

        self._result_text.configure(state=tk.NORMAL)
        self._result_text.delete("1.0", tk.END)

        total_tags = 0

        # ── 1. Clean-Text (narrativ, alle Tags entfernt) ──
        clean = _ALL_TAGS_RE.sub("", text).strip()
        clean = re.sub(r"\n{3,}", "\n\n", clean)  # Mehrfach-Leerzeilen reduzieren

        self._result_text.insert(tk.END, "\u2588\u2588 NARRATIVER TEXT (Tags entfernt)\n", "header")
        self._result_text.insert(tk.END, clean + "\n\n", "clean")

        # ── 2. Proben ──
        probes = _PROBE_RE.findall(text)
        if probes:
            total_tags += len(probes)
            self._result_text.insert(
                tk.END, f"\u2588\u2588 PROBEN ({len(probes)})\n", "header",
            )
            for skill, target in probes:
                skill = skill.strip()
                self._result_text.insert(
                    tk.END,
                    f"  \u2684 {skill} (Zielwert: {target})\n",
                    "probe",
                )
                self._result_text.insert(
                    tk.END,
                    f"    \u2192 Engine wuerfelt d100, vergleicht mit {target}\n",
                    "muted",
                )
            self._result_text.insert(tk.END, "\n")

        # ── 3. Stat-Aenderungen ──
        stats = []
        for m in _HP_LOSS_RE.finditer(text):
            stats.append(("HP_VERLUST", m.group(1), "stat"))
        for m in _HP_HEAL_RE.finditer(text):
            stats.append(("HP_HEILUNG", m.group(1), "stat_heal"))
        for m in _SAN_LOSS_RE.finditer(text):
            stats.append(("SAN_VERLUST", m.group(1), "stat"))
        for m in _XP_GAIN_RE.finditer(text):
            stats.append(("XP_GEWINN", m.group(1), "stat_heal"))
        for m in _SKILL_USED_RE.finditer(text):
            stats.append(("FERTIGKEIT", m.group(1).strip(), "stat"))

        if stats:
            total_tags += len(stats)
            self._result_text.insert(
                tk.END, f"\u2588\u2588 CHARAKTER-AENDERUNGEN ({len(stats)})\n", "header",
            )
            for change_type, value, tag in stats:
                icon = "\u2764" if "HP" in change_type else "\u2620" if "SAN" in change_type else "\u2b50" if "XP" in change_type else "\u2699"
                action = {
                    "HP_VERLUST": f"CharacterManager.update_stat('HP', -{value})",
                    "HP_HEILUNG": f"CharacterManager.update_stat('HP', +roll('{value}'))",
                    "SAN_VERLUST": f"CharacterManager.update_stat('SAN', -roll('{value}'))",
                    "XP_GEWINN": f"+{value} XP",
                    "FERTIGKEIT": f"CharacterManager.mark_skill_used('{value}')",
                }.get(change_type, "?")

                self._result_text.insert(
                    tk.END,
                    f"  {icon} [{change_type}: {value}]\n",
                    tag,
                )
                self._result_text.insert(
                    tk.END,
                    f"    \u2192 {action}\n",
                    "muted",
                )
            self._result_text.insert(tk.END, "\n")

        # ── 4. Fakten (World State) ──
        fakten = _FAKT_RE.findall(text)
        if fakten:
            total_tags += len(fakten)
            self._result_text.insert(
                tk.END, f"\u2588\u2588 FAKTEN / WORLD STATE ({len(fakten)})\n", "header",
            )
            for fakt_json in fakten:
                try:
                    parsed = json.loads(fakt_json)
                    for k, v in parsed.items():
                        self._result_text.insert(
                            tk.END, f"  {k} = {v}\n", "fact",
                        )
                    self._result_text.insert(
                        tk.END,
                        f"    \u2192 Archivist.merge_world_state({parsed})\n",
                        "muted",
                    )
                except json.JSONDecodeError:
                    self._result_text.insert(
                        tk.END, f"  \u26a0 Ungueltiges JSON: {fakt_json}\n", "error_tag",
                    )
            self._result_text.insert(tk.END, "\n")

        # ── 5. Inventar ──
        inventar = _INVENTAR_RE.findall(text)
        if inventar:
            total_tags += len(inventar)
            self._result_text.insert(
                tk.END, f"\u2588\u2588 INVENTAR ({len(inventar)})\n", "header",
            )
            for item_name, action in inventar:
                item_name = item_name.strip()
                action_lower = action.lower()
                tag = "inventar_add" if action_lower == "gefunden" else \
                      "inventar_del" if action_lower == "verloren" else "inventar_done"
                icon = "\u2795" if action_lower == "gefunden" else \
                       "\u2796" if action_lower == "verloren" else "\u2714"
                self._result_text.insert(
                    tk.END,
                    f"  {icon} {item_name} ({action})\n",
                    tag,
                )
            self._result_text.insert(tk.END, "\n")

        # ── 6. Stimmen-Wechsel ──
        stimmen = _STIMME_RE.findall(text)
        if stimmen:
            total_tags += len(stimmen)
            self._result_text.insert(
                tk.END, f"\u2588\u2588 STIMMEN-WECHSEL ({len(stimmen)})\n", "header",
            )
            for voice_role in stimmen:
                self._result_text.insert(
                    tk.END,
                    f"  \u266b {voice_role}\n",
                    "voice",
                )
                self._result_text.insert(
                    tk.END,
                    f"    \u2192 TTS.set_voice('{voice_role}')\n",
                    "muted",
                )
            self._result_text.insert(tk.END, "\n")

        # ── 7. Zeit & Wetter ──
        zeit_tags = []
        for m in _ZEIT_RE.finditer(text):
            zeit_tags.append(("ZEIT_VERGEHT", f"{m.group(1)}h"))
        for m in _TAGESZEIT_RE.finditer(text):
            zeit_tags.append(("TAGESZEIT", m.group(1)))
        for m in _WETTER_RE.finditer(text):
            zeit_tags.append(("WETTER", m.group(1).strip()))

        if zeit_tags:
            total_tags += len(zeit_tags)
            self._result_text.insert(
                tk.END, f"\u2588\u2588 ZEIT & WETTER ({len(zeit_tags)})\n", "header",
            )
            for zt_type, zt_val in zeit_tags:
                icon = "\u231a" if zt_type != "WETTER" else "\u2601"
                action = {
                    "ZEIT_VERGEHT": f"TimeTracker.advance({zt_val})",
                    "TAGESZEIT": f"TimeTracker.set_time('{zt_val}')",
                    "WETTER": f"TimeTracker.set_weather('{zt_val}')",
                }.get(zt_type, "?")
                self._result_text.insert(
                    tk.END,
                    f"  {icon} [{zt_type}: {zt_val}]\n",
                    "time",
                )
                self._result_text.insert(
                    tk.END,
                    f"    \u2192 {action}\n",
                    "muted",
                )
            self._result_text.insert(tk.END, "\n")

        # ── Zusammenfassung ──
        clean_len = len(clean)
        self._result_text.insert(tk.END, "\u2588\u2588 ZUSAMMENFASSUNG\n", "header")

        if total_tags > 0:
            self._result_text.insert(
                tk.END,
                f"  {total_tags} Tags extrahiert, {clean_len:,} Zeichen narrativer Text\n",
                "ok",
            )
        else:
            self._result_text.insert(
                tk.END,
                f"  Keine Tags gefunden ({clean_len:,} Zeichen reiner Text)\n",
                "warn",
            )

        # Warnungen
        if not probes and any(w in text.lower() for w in ["versuch", "pruef", "klett", "such"]):
            self._result_text.insert(
                tk.END,
                "  \u26a0 Text enthaelt Handlungsverben aber keine [PROBE:] — fehlende Probe?\n",
                "warn",
            )
        if stimmen and stimmen[-1].lower() != "keeper":
            self._result_text.insert(
                tk.END,
                f"  \u26a0 Letzte Stimme ist '{stimmen[-1]}' — [STIMME:keeper] fehlt am Ende!\n",
                "warn",
            )

        self._result_info.configure(
            text=f"Tags: {total_tags} | Clean: {clean_len:,} Zeichen | "
                 f"Raw: {len(text):,} Zeichen",
        )

        self._result_text.configure(state=tk.DISABLED)

    # ==================================================================
    # Live-Feed (EventBus)
    # ==================================================================

    def _live_append(self, text: str, tag: str = "") -> None:
        self._live_text.configure(state=tk.NORMAL)
        if tag:
            self._live_text.insert(tk.END, text, tag)
        else:
            self._live_text.insert(tk.END, text)
        self._live_text.see(tk.END)
        self._live_text.configure(state=tk.DISABLED)

    def _live_timestamp(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._live_append(f"[{now}] ", "timestamp")

    def handle_event(self, data: dict[str, Any]) -> None:
        """Verarbeitet Events vom EventBus — Live-Feed der Response-Verarbeitung."""
        event = data.get("_event", "")

        if event == "keeper.response_complete":
            response = data.get("response", "")
            self._live_timestamp()
            self._live_append("RAW: ", "label")
            # Gekuerzte Anzeige
            preview = response[:200]
            if len(response) > 200:
                preview += "..."
            self._live_append(preview + "\n", "raw")

            # Live-Tag-Analyse
            probes = _PROBE_RE.findall(response)
            stats_hp = _HP_LOSS_RE.findall(response)
            stats_san = _SAN_LOSS_RE.findall(response)
            fakten = _FAKT_RE.findall(response)
            inventar = _INVENTAR_RE.findall(response)
            stimmen = _STIMME_RE.findall(response)
            zeiten = _ZEIT_RE.findall(response)

            if probes:
                for skill, target in probes:
                    self._live_append(f"  \u2684 PROBE: {skill.strip()} ({target})\n", "probe")
            if stats_hp:
                for val in stats_hp:
                    self._live_append(f"  \u2764 HP_VERLUST: {val}\n", "stat")
            if stats_san:
                for val in stats_san:
                    self._live_append(f"  \u2620 SAN_VERLUST: {val}\n", "stat")
            if fakten:
                for f_json in fakten:
                    self._live_append(f"  \u270d FAKT: {f_json}\n", "fact")
            if inventar:
                for item, action in inventar:
                    self._live_append(f"  \u2692 {item.strip()} ({action})\n", "inventar")
            if stimmen:
                self._live_append(f"  \u266b Stimmen: {' \u2192 '.join(stimmen)}\n", "voice")
            if zeiten:
                for z in zeiten:
                    self._live_append(f"  \u231a +{z}h\n", "time")

            tag_count = len(probes) + len(stats_hp) + len(stats_san) + len(fakten) + len(inventar) + len(stimmen) + len(zeiten)
            if tag_count > 0:
                self._live_append(f"  \u2192 {tag_count} Tags verarbeitet\n", "action")
            self._live_append("\n")

        elif event == "game.output":
            tag = data.get("tag", "")
            text = data.get("text", "")
            if tag in ("probe", "dice", "stat", "fact"):
                self._live_timestamp()
                color = {"probe": "probe", "dice": "probe", "stat": "stat", "fact": "fact"}.get(tag, "raw")
                self._live_append(f"  \u21b3 {text}\n", color)

    def on_engine_ready(self) -> None:
        """Wird aufgerufen wenn die Engine initialisiert ist."""
        pass
