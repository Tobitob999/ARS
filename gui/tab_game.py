"""
gui/tab_game.py — Tab 2: Game (Spielansicht)

Aktives Gameplay-Interface:
- Start / Pause / Stop / Save / Load Buttons
- Scrollbare Text-Ausgabe mit Live-Streaming (Keeper, System, Proben, ...)
- Text-Eingabe + Senden
- Voice On/Off + Auto-Voice Toggle
- Charakter-Status (HP/SAN/MP Balken, Inventar)
- Wuerfelgeraeusch bei Proben
"""

from __future__ import annotations

import logging
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
        self._output_text.tag_configure("fact", foreground=STREAM_TAG)
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

        # Location
        loc_lf = ttk.LabelFrame(right_frame, text=" Ort ", style="TLabelframe")
        loc_lf.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        self._loc_label = ttk.Label(loc_lf, text="—", wraplength=200)
        self._loc_label.pack(anchor=tk.W, padx=PAD, pady=PAD_SMALL)

        # Turn-Zaehler
        self._turn_label = ttk.Label(right_frame, text="Turn: 0", style="Muted.TLabel")
        self._turn_label.pack(anchor=tk.W, padx=PAD, pady=PAD_SMALL)

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
                try:
                    engine.enable_voice(barge_in=False)
                except Exception as exc:
                    logger.warning("Voice-Aktivierung fehlgeschlagen: %s", exc)
                    self._voice_var.set(False)
                    self._voice_on = False
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

            # ── Wuerfelwurf: Geraeusch abspielen ──
            elif tag == "dice":
                self._play_dice_sound()
                self._append_timestamp()
                self._append_output(text + "\n", tag)

            elif tag in ("probe", "stat", "fact", "system"):
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
