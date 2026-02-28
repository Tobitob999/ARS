"""
gui/tab_session.py — Tab 1: Session Setup

Konfiguration aller Grundparameter vor dem Spielstart:
- Regelwerk, Abenteuer, Setting, Keeper, Character, Party, Extras
- Schwierigkeit, Temperatur, Atmosphaere, Persona, Sprache
- Start / Pause / Stop Buttons
"""

from __future__ import annotations

import logging
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT, FG_PRIMARY, FG_SECONDARY, FG_ACCENT, FG_MUTED,
    GREEN, RED, FONT_NORMAL, FONT_BOLD, FONT_HEADER, PAD, PAD_SMALL, PAD_LARGE,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.session")


class SessionTab(ttk.Frame):
    """Session Setup Tab — Konfiguration & Engine-Steuerung."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        self._build_ui()
        self._scan_modules()

    def _build_ui(self) -> None:
        # Scrollbarer Container
        canvas = tk.Canvas(self, bg=BG_DARK, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        self._scroll_frame = ttk.Frame(canvas, style="TFrame")

        self._scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        container = self._scroll_frame

        # ── Module-Auswahl ──
        mod_frame = ttk.LabelFrame(container, text=" Module ", style="TLabelframe")
        mod_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD)

        self._combos: dict[str, ttk.Combobox] = {}
        labels = [
            ("Regelwerk", "ruleset"),
            ("Abenteuer", "adventure"),
            ("Setting", "setting"),
            ("Keeper", "keeper"),
            ("Character", "character"),
            ("Party", "party"),
        ]
        for i, (label, key) in enumerate(labels):
            ttk.Label(mod_frame, text=label).grid(
                row=i, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
            )
            combo = ttk.Combobox(mod_frame, state="readonly", width=35)
            combo.grid(row=i, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.EW)
            self._combos[key] = combo

        # Extras (Checkbuttons)
        ttk.Label(mod_frame, text="Extras").grid(
            row=len(labels), column=0, sticky=tk.NW, padx=PAD, pady=PAD_SMALL,
        )
        self._extras_frame = ttk.Frame(mod_frame, style="TFrame")
        self._extras_frame.grid(
            row=len(labels), column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.W,
        )
        self._extras_vars: dict[str, tk.BooleanVar] = {}

        # Preset
        ttk.Label(mod_frame, text="Preset").grid(
            row=len(labels) + 1, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
        )
        preset_row = ttk.Frame(mod_frame, style="TFrame")
        preset_row.grid(
            row=len(labels) + 1, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.EW,
        )
        self._combos["preset"] = ttk.Combobox(preset_row, state="readonly", width=25)
        self._combos["preset"].pack(side=tk.LEFT)
        ttk.Button(preset_row, text="Load", command=self._load_preset).pack(
            side=tk.LEFT, padx=PAD,
        )

        mod_frame.columnconfigure(1, weight=1)

        # ── Feineinstellungen ──
        fine_frame = ttk.LabelFrame(container, text=" Feineinstellungen ", style="TLabelframe")
        fine_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD)

        # Schwierigkeit
        ttk.Label(fine_frame, text="Schwierigkeit").grid(
            row=0, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
        )
        diff_frame = ttk.Frame(fine_frame, style="TFrame")
        diff_frame.grid(row=0, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.W)
        self._difficulty_var = tk.StringVar(value="normal")
        for d in ("easy", "normal", "heroic", "hardcore"):
            ttk.Radiobutton(
                diff_frame, text=d.capitalize(), variable=self._difficulty_var, value=d,
            ).pack(side=tk.LEFT, padx=PAD_SMALL)

        # Atmosphaere
        ttk.Label(fine_frame, text="Atmosphaere").grid(
            row=1, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
        )
        self._atmosphere_var = tk.StringVar(value="1920s Cosmic Horror")
        tk.Entry(
            fine_frame, textvariable=self._atmosphere_var,
            bg=BG_INPUT, fg=FG_PRIMARY, insertbackground=FG_PRIMARY,
            font=FONT_NORMAL, width=45,
        ).grid(row=1, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.EW)

        # Keeper-Persona
        ttk.Label(fine_frame, text="Keeper-Persona").grid(
            row=2, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
        )
        self._persona_var = tk.StringVar(value="Mysterioes, detailverliebt, zynisch")
        tk.Entry(
            fine_frame, textvariable=self._persona_var,
            bg=BG_INPUT, fg=FG_PRIMARY, insertbackground=FG_PRIMARY,
            font=FONT_NORMAL, width=45,
        ).grid(row=2, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.EW)

        # Sprache
        ttk.Label(fine_frame, text="Sprache").grid(
            row=3, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
        )
        self._language_var = tk.StringVar(value="de-DE")
        lang_combo = ttk.Combobox(
            fine_frame, textvariable=self._language_var,
            values=["de-DE", "en-US", "en-GB", "fr-FR", "es-ES"],
            state="readonly", width=12,
        )
        lang_combo.grid(row=3, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.W)

        # Temperatur
        ttk.Label(fine_frame, text="KI-Temperatur").grid(
            row=4, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
        )
        temp_frame = ttk.Frame(fine_frame, style="TFrame")
        temp_frame.grid(row=4, column=1, padx=PAD, pady=PAD_SMALL, sticky=tk.EW)
        self._temperature_var = tk.DoubleVar(value=0.92)
        self._temp_scale = ttk.Scale(
            temp_frame, from_=0.0, to=2.0, variable=self._temperature_var,
            orient=tk.HORIZONTAL, length=200,
            command=self._on_temp_change,
        )
        self._temp_scale.pack(side=tk.LEFT)
        self._temp_label = ttk.Label(temp_frame, text="0.92")
        self._temp_label.pack(side=tk.LEFT, padx=PAD)
        ttk.Label(
            temp_frame,
            text="(0 = vorhersagbar/strikt, 1 = ausgewogen, 2 = maximal kreativ/zufaellig)",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT, padx=PAD_SMALL)

        fine_frame.columnconfigure(1, weight=1)

        # ── Charakter-Uebersicht ──
        char_frame = ttk.LabelFrame(container, text=" Charakter-Uebersicht ", style="TLabelframe")
        char_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD)

        self._char_info = tk.Text(
            char_frame, height=5, bg=BG_PANEL, fg=FG_PRIMARY,
            font=FONT_NORMAL, wrap=tk.WORD, state=tk.DISABLED,
            highlightthickness=0, borderwidth=0,
        )
        self._char_info.pack(fill=tk.X, padx=PAD, pady=PAD)

        # ── Steuerung ──
        ctrl_frame = ttk.Frame(container, style="TFrame")
        ctrl_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD_LARGE)

        self._btn_start = ttk.Button(
            ctrl_frame, text="  Start Session  ", style="Accent.TButton",
            command=self._on_start,
        )
        self._btn_start.pack(side=tk.LEFT, padx=PAD)

        self._btn_pause = ttk.Button(
            ctrl_frame, text="  Pause  ", command=self._on_pause,
        )
        self._btn_pause.pack(side=tk.LEFT, padx=PAD)
        self._btn_pause.state(["disabled"])

        self._btn_stop = ttk.Button(
            ctrl_frame, text="  Stop  ", style="Danger.TButton",
            command=self._on_stop,
        )
        self._btn_stop.pack(side=tk.LEFT, padx=PAD)
        self._btn_stop.state(["disabled"])

        ttk.Separator(ctrl_frame, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=PAD,
        )

        self._btn_load = ttk.Button(
            ctrl_frame, text="  Load Session  ", command=self._on_load_session,
        )
        self._btn_load.pack(side=tk.LEFT, padx=PAD)

        # ── Saved Sessions Liste ──
        saves_frame = ttk.LabelFrame(container, text=" Gespeicherte Sessions ", style="TLabelframe")
        saves_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD)

        save_cols = ("id", "module", "turns", "date")
        self._saves_tree = ttk.Treeview(
            saves_frame, columns=save_cols, show="headings", height=4,
        )
        for col, head, w in [
            ("id", "#", 50), ("module", "Modul", 120),
            ("turns", "Turns", 60), ("date", "Datum", 160),
        ]:
            self._saves_tree.heading(col, text=head)
            self._saves_tree.column(col, width=w)
        self._saves_tree.pack(fill=tk.X, padx=PAD, pady=PAD)
        self._saves_tree.bind("<Double-1>", lambda e: self._on_load_session())

    def _scan_modules(self) -> None:
        """Scannt verfuegbare Module via DiscoveryService."""
        try:
            from core.discovery import DiscoveryService
            ds = DiscoveryService(Path(__file__).parent.parent)
            ds.scan()

            self._combos["ruleset"]["values"] = ds.list_rulesets()
            self._combos["adventure"]["values"] = ["(keine)"] + ds.list_adventures()
            self._combos["setting"]["values"] = ["(keine)"] + ds.list_settings()
            self._combos["keeper"]["values"] = ["(keine)"] + ds.list_keepers()
            self._combos["character"]["values"] = ["(keine)"] + ds.list_characters()
            self._combos["party"]["values"] = ["(keine)"] + ds.list_parties()
            presets_dir = Path(__file__).parent.parent / "modules" / "presets"
            preset_names = [p.stem for p in presets_dir.glob("*.json")] if presets_dir.is_dir() else []
            self._combos["preset"]["values"] = ["(keine)"] + preset_names

            # Defaults setzen aus Engine-Config
            sc = self.gui.engine.session_config
            if sc:
                self._set_combo("ruleset", getattr(sc, "ruleset", ""))
                self._set_combo("adventure", getattr(sc, "adventure", None))
                self._set_combo("setting", getattr(sc, "setting", None))
                self._set_combo("keeper", getattr(sc, "keeper", None))
                self._set_combo("character", getattr(sc, "character", None))
                self._set_combo("party", getattr(sc, "party", None))
                self._difficulty_var.set(getattr(sc, "difficulty", "normal"))
                self._atmosphere_var.set(getattr(sc, "atmosphere", ""))
                self._persona_var.set(getattr(sc, "keeper_persona", ""))
                self._language_var.set(getattr(sc, "language", "de-DE"))
                self._temperature_var.set(getattr(sc, "temperature", 0.92))
                self._temp_label.configure(text=f"{getattr(sc, 'temperature', 0.92):.2f}")
            else:
                self._combos["ruleset"].current(0)
                self._combos["adventure"].current(0)

            # Extras als Checkbuttons
            try:
                extras_list = ds.list_extras()
            except AttributeError:
                extras_list = []
            active_extras = getattr(sc, "extras", []) or [] if sc else []
            for name in extras_list:
                var = tk.BooleanVar(value=(name in active_extras))
                self._extras_vars[name] = var
                ttk.Checkbutton(
                    self._extras_frame, text=name, variable=var,
                ).pack(side=tk.LEFT, padx=PAD_SMALL)

        except Exception as exc:
            logger.warning("Module-Scan fehlgeschlagen: %s", exc)

    def _set_combo(self, key: str, value: str | None) -> None:
        combo = self._combos[key]
        if value and value in (combo["values"] or []):
            combo.set(value)
        elif combo["values"]:
            combo.current(0)

    def _on_temp_change(self, value: str) -> None:
        self._temp_label.configure(text=f"{float(value):.2f}")

    def _load_preset(self) -> None:
        preset_name = self._combos["preset"].get()
        if not preset_name or preset_name == "(keine)":
            return
        try:
            from core.session_config import SessionConfig
            cfg = SessionConfig.from_preset(preset_name)
            self._set_combo("ruleset", cfg.ruleset)
            self._set_combo("adventure", cfg.adventure)
            self._set_combo("setting", cfg.setting)
            self._set_combo("keeper", cfg.keeper)
            self._set_combo("character", cfg.character)
            self._set_combo("party", cfg.party)
            self._difficulty_var.set(cfg.difficulty)
            self._atmosphere_var.set(cfg.atmosphere)
            self._persona_var.set(cfg.keeper_persona)
            self._language_var.set(cfg.language)
            self._temperature_var.set(cfg.temperature)
            self._temp_label.configure(text=f"{cfg.temperature:.2f}")
            logger.info("Preset geladen: %s", preset_name)
        except Exception as exc:
            logger.warning("Preset-Load fehlgeschlagen: %s", exc)

    def _build_session_config(self) -> Any:
        """Baut eine SessionConfig aus den GUI-Werten."""
        from core.session_config import SessionConfig

        adventure = self._combos["adventure"].get()
        setting = self._combos["setting"].get()
        keeper = self._combos["keeper"].get()
        character = self._combos["character"].get()
        party = self._combos["party"].get()
        extras = [name for name, var in self._extras_vars.items() if var.get()]

        return SessionConfig(
            ruleset=self._combos["ruleset"].get() or "cthulhu_7e",
            adventure=adventure if adventure != "(keine)" else None,
            setting=setting if setting != "(keine)" else None,
            keeper=keeper if keeper != "(keine)" else None,
            character=character if character != "(keine)" else None,
            party=party if party != "(keine)" else None,
            extras=extras,
            difficulty=self._difficulty_var.get(),
            atmosphere=self._atmosphere_var.get(),
            keeper_persona=self._persona_var.get(),
            language=self._language_var.get(),
            temperature=self._temperature_var.get(),
        )

    # ── Button-Aktionen ──

    def _on_start(self) -> None:
        """Start Session: Config bauen, Engine starten."""
        sc = self._build_session_config()
        engine = self.gui.engine
        engine.module_name = sc.ruleset
        engine.session_config = sc
        engine.loader.module_name = sc.ruleset

        self._btn_start.state(["disabled"])
        self._btn_pause.state(["!disabled"])
        self._btn_stop.state(["!disabled"])

        self.gui.start_engine()

    def _on_pause(self) -> None:
        self.gui.pause_engine()
        self._btn_start.state(["!disabled"])
        self._btn_start.configure(text="  Resume  ")
        self._btn_pause.state(["disabled"])

    def _on_stop(self) -> None:
        self.gui.stop_engine()
        self._btn_start.state(["!disabled"])
        self._btn_start.configure(text="  Start Session  ")
        self._btn_pause.state(["disabled"])
        self._btn_stop.state(["disabled"])

    def _on_load_session(self) -> None:
        """Laedt eine gespeicherte Session aus der DB."""
        engine = self.gui.engine
        if not engine.character or not engine.character._conn:
            logger.warning("Kein Charakter geladen — kann keine Sessions anzeigen.")
            return

        # Ausgewaehlte Session aus Treeview
        sel = self._saves_tree.selection()
        if sel:
            item = self._saves_tree.item(sel[0])
            sid_str = item["values"][0]
            sid = int(str(sid_str).replace("#", ""))
            logger.info("Session #%d zum Laden ausgewaehlt.", sid)
            # TODO: Implementiere vollstaendiges Session-Restore
            return

        # Falls nichts ausgewaehlt: Dialog anzeigen
        self._refresh_sessions()

    def _refresh_sessions(self) -> None:
        """Laedt Sessions aus der DB in die Treeview."""
        engine = self.gui.engine
        if not engine.character or not engine.character._conn:
            return
        try:
            conn = engine.character._conn
            cur = conn.execute(
                """SELECT s.id, s.module, s.last_active,
                          (SELECT COUNT(*) FROM session_turns WHERE session_id = s.id) as turn_count
                   FROM sessions s ORDER BY s.last_active DESC LIMIT 15""",
            )
            # Alte Eintraege entfernen
            for item in self._saves_tree.get_children():
                self._saves_tree.delete(item)

            for row in cur:
                sid, module, last_active, turn_count = row
                date = last_active[:16] if last_active else "?"
                self._saves_tree.insert("", tk.END, values=(
                    f"#{sid}", module or "—", turn_count, date,
                ))
        except Exception as exc:
            logger.warning("Sessions laden fehlgeschlagen: %s", exc)

    # ── Events ──

    def on_engine_ready(self) -> None:
        """Wird aufgerufen wenn die Engine fertig initialisiert ist."""
        engine = self.gui.engine
        if engine.character:
            self._char_info.configure(state=tk.NORMAL)
            self._char_info.delete("1.0", tk.END)
            name = engine.character.name
            status = engine.character.status_line()
            self._char_info.insert(tk.END, f"  Name: {name}\n")
            self._char_info.insert(tk.END, f"  Status: {status}\n")
            if hasattr(engine.character, "_archetype") and engine.character._archetype:
                self._char_info.insert(tk.END, f"  Archetyp: {engine.character._archetype}\n")
            if hasattr(engine.character, "_skills"):
                top_skills = sorted(
                    engine.character._skills.items(),
                    key=lambda x: x[1], reverse=True,
                )[:8]
                skills_str = ", ".join(f"{k}({v})" for k, v in top_skills)
                self._char_info.insert(tk.END, f"  Top-Skills: {skills_str}\n")
            self._char_info.configure(state=tk.DISABLED)
            self.gui.status_bar.set_character(status)
