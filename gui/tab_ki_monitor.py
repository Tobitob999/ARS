"""
gui/tab_ki_monitor.py — Tab 3: KI-Monitor (Herzstueck)

Totale Transparenz ueber den KI-Kontext:
- Context-Zusammenbau (System Prompt, Archivar, Location, History) farbkodiert
- Live-Stream der aktuellen Interaktion
- Tag-Parsing Visualisierung
- Token-Aufschluesselung pro Anfrage
"""

from __future__ import annotations

import logging
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    CTX_SYSTEM_PROMPT, CTX_ARCHIVAR, CTX_LOCATION, CTX_HISTORY,
    STREAM_PLAYER, STREAM_KEEPER, STREAM_TAG, STREAM_PROBE, STREAM_ARCHIVAR,
    STREAM_WARNING, GREEN, RED, YELLOW,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, FONT_HEADER, PAD, PAD_SMALL, PAD_LARGE,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.ki_monitor")


class KIMonitorTab(ttk.Frame):
    """KI-Monitor — farbkodierter Context-Viewer und Live-Stream."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        self._build_ui()

    def _build_ui(self) -> None:
        # Vertikaler PanedWindow: oben Context, unten Live-Stream
        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        # ── Oberer Bereich: Context-Zusammenbau ──
        ctx_frame = ttk.LabelFrame(paned, text=" Context-Zusammenbau ", style="TLabelframe")
        paned.add(ctx_frame, weight=1)

        # Toggle-Buttons fuer Sektionen
        toggle_row = ttk.Frame(ctx_frame, style="TFrame")
        toggle_row.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        self._section_vars = {}
        for section, label in [
            ("system_prompt", "System Prompt"),
            ("archivar", "Archivar-Kontext"),
            ("location", "Location-Kontext"),
            ("history", "History"),
        ]:
            var = tk.BooleanVar(value=True)
            self._section_vars[section] = var
            ttk.Checkbutton(
                toggle_row, text=label, variable=var,
                command=self._refresh_context,
            ).pack(side=tk.LEFT, padx=PAD_SMALL)

        ttk.Button(
            toggle_row, text="Refresh", command=self._refresh_context,
        ).pack(side=tk.RIGHT, padx=PAD_SMALL)

        # Context Text-Widget
        self._ctx_text = tk.Text(
            ctx_frame, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        ctx_scroll = ttk.Scrollbar(ctx_frame, orient=tk.VERTICAL, command=self._ctx_text.yview)
        self._ctx_text.configure(yscrollcommand=ctx_scroll.set)
        self._ctx_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ctx_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Tags fuer Farbkodierung
        self._ctx_text.tag_configure("system_prompt", background=CTX_SYSTEM_PROMPT, foreground=FG_PRIMARY)
        self._ctx_text.tag_configure("archivar", background=CTX_ARCHIVAR, foreground=FG_PRIMARY)
        self._ctx_text.tag_configure("location", background=CTX_LOCATION, foreground=FG_PRIMARY)
        self._ctx_text.tag_configure("history", background=CTX_HISTORY, foreground=FG_PRIMARY)
        self._ctx_text.tag_configure("header", foreground=FG_ACCENT, font=FONT_BOLD)
        self._ctx_text.tag_configure("muted", foreground=FG_MUTED)

        # ── Unterer Bereich: Live-Stream ──
        stream_frame = ttk.LabelFrame(paned, text=" Live-Stream ", style="TLabelframe")
        paned.add(stream_frame, weight=2)

        self._stream_text = tk.Text(
            stream_frame, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_NORMAL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        stream_scroll = ttk.Scrollbar(stream_frame, orient=tk.VERTICAL, command=self._stream_text.yview)
        self._stream_text.configure(yscrollcommand=stream_scroll.set)
        self._stream_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        stream_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Tags fuer Stream-Farbkodierung
        self._stream_text.tag_configure("player", foreground=STREAM_PLAYER, font=FONT_BOLD)
        self._stream_text.tag_configure("keeper", foreground=STREAM_KEEPER)
        self._stream_text.tag_configure("tag", foreground=STREAM_TAG, font=FONT_BOLD)
        self._stream_text.tag_configure("probe", foreground=STREAM_PROBE, font=FONT_BOLD)
        self._stream_text.tag_configure("archivar", foreground=STREAM_ARCHIVAR)
        self._stream_text.tag_configure("warning", foreground=STREAM_WARNING)
        self._stream_text.tag_configure("label", foreground=FG_MUTED, font=FONT_SMALL)
        self._stream_text.tag_configure("timestamp", foreground=FG_MUTED, font=FONT_SMALL)

        # ── Token-Aufschluesselung (untere Leiste) ──
        token_bar = tk.Frame(stream_frame, bg=BG_PANEL, height=24)
        token_bar.pack(fill=tk.X, side=tk.BOTTOM)
        token_bar.pack_propagate(False)
        self._token_info = tk.Label(
            token_bar, text="Prompt: — | Cached: — | Output: — | Think: — | Kosten: —",
            bg=BG_PANEL, fg=FG_SECONDARY, font=FONT_SMALL, anchor=tk.W, padx=PAD,
        )
        self._token_info.pack(fill=tk.X)

    # ── Context-Viewer ──

    def _refresh_context(self) -> None:
        """Laedt den aktuellen Context und zeigt ihn farbkodiert an."""
        engine = self.gui.engine
        self._ctx_text.configure(state=tk.NORMAL)
        self._ctx_text.delete("1.0", tk.END)

        if not engine.ai_backend:
            self._ctx_text.insert(tk.END, "(Engine nicht initialisiert)\n", "muted")
            self._ctx_text.configure(state=tk.DISABLED)
            return

        backend = engine.ai_backend

        # System Prompt
        if self._section_vars["system_prompt"].get():
            prompt = getattr(backend, "_system_prompt", "")
            token_est = len(prompt) // 4  # Grobe Schaetzung
            self._ctx_text.insert(
                tk.END,
                f"\u2588\u2588 SYSTEM PROMPT (~{token_est:,} tokens)\n",
                "header",
            )
            # Gekuerzte Vorschau
            if len(prompt) > 2000:
                self._ctx_text.insert(tk.END, prompt[:2000], "system_prompt")
                self._ctx_text.insert(
                    tk.END, f"\n... ({len(prompt):,} Zeichen gesamt)\n\n", "muted",
                )
            else:
                self._ctx_text.insert(tk.END, prompt + "\n\n", "system_prompt")

        # Archivar-Kontext
        if self._section_vars["archivar"].get():
            archivist = getattr(backend, "_archivist", None)
            if archivist:
                ctx = archivist.get_context_for_prompt()
                if ctx:
                    self._ctx_text.insert(tk.END, "\u2588\u2588 ARCHIVAR-KONTEXT\n", "header")
                    self._ctx_text.insert(tk.END, ctx + "\n\n", "archivar")
                else:
                    self._ctx_text.insert(tk.END, "\u2588\u2588 ARCHIVAR-KONTEXT (leer)\n\n", "muted")

        # Location-Kontext
        if self._section_vars["location"].get():
            adv_mgr = getattr(backend, "_adv_manager", None)
            if adv_mgr and adv_mgr.loaded:
                loc_ctx = adv_mgr.get_location_context()
                if loc_ctx:
                    loc = adv_mgr.get_current_location()
                    loc_name = loc.get("name", "?") if loc else "?"
                    self._ctx_text.insert(
                        tk.END,
                        f"\u2588\u2588 LOCATION-KONTEXT: {loc_name}\n",
                        "header",
                    )
                    self._ctx_text.insert(tk.END, loc_ctx + "\n\n", "location")

        # History
        if self._section_vars["history"].get():
            history = getattr(backend, "_history", [])
            turn_count = len(history)
            hist_text = ""
            for entry in history[-20:]:  # Letzte 20 Eintraege
                role = entry.get("role", "?")
                content = entry.get("content", "")
                prefix = "[USR]" if role == "user" else "[KI] "
                # Kuerzen wenn noetig
                if len(content) > 300:
                    content = content[:300] + "..."
                hist_text += f"{prefix} {content}\n"
            if hist_text:
                token_est = sum(len(e.get("content", "")) for e in history) // 4
                self._ctx_text.insert(
                    tk.END,
                    f"\u2588\u2588 HISTORY ({turn_count} Eintraege, ~{token_est:,} tokens)\n",
                    "header",
                )
                self._ctx_text.insert(tk.END, hist_text + "\n", "history")

        self._ctx_text.configure(state=tk.DISABLED)

    # ── Live-Stream Methoden ──

    def _append_stream(self, text: str, tag: str = "") -> None:
        """Fuegt Text zum Live-Stream hinzu (Main-Thread)."""
        self._stream_text.configure(state=tk.NORMAL)
        if tag:
            self._stream_text.insert(tk.END, text, tag)
        else:
            self._stream_text.insert(tk.END, text)
        self._stream_text.see(tk.END)
        self._stream_text.configure(state=tk.DISABLED)

    def _append_timestamp(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._append_stream(f"[{now}] ", "timestamp")

    # ── EventBus Handler ──

    def handle_event(self, data: dict[str, Any]) -> None:
        """Verarbeitet Events vom EventBus."""
        event = data.get("_event", "")

        if event == "keeper.prompt_sent":
            self._append_timestamp()
            self._append_stream("\u25b6 SPIELER: ", "label")
            msg = data.get("user_message", "")
            self._append_stream(msg + "\n", "player")
            # Context aktualisieren
            self._refresh_context()

        elif event == "keeper.response_complete":
            self._append_timestamp()
            self._append_stream("\u25c0 KEEPER: ", "label")
            response = data.get("response", "")
            # Tags extrahieren und separat faerben
            import re
            # Tags am Ende des Texts
            tag_pattern = re.compile(r"\[(?:FAKT|INVENTAR|PROBE|HP_VERLUST|STABILITAET_VERLUST|HP_HEILUNG|XP_GEWINN|FERTIGKEIT_GENUTZT|STIMME|ZEIT_VERGEHT|TAGESZEIT|WETTER):[^\]]*\]", re.IGNORECASE)
            tags_found = tag_pattern.findall(response)
            clean_text = tag_pattern.sub("", response).strip()

            self._append_stream(clean_text + "\n", "keeper")

            if tags_found:
                self._append_stream("  TAGS: ", "label")
                for t in tags_found:
                    # Proben separat
                    if t.upper().startswith("[PROBE"):
                        self._append_stream(t + " ", "probe")
                    else:
                        self._append_stream(t + " ", "tag")
                self._append_stream("\n")

            self._append_stream("\n")

        elif event == "keeper.usage_update":
            prompt = data.get("prompt_tokens", 0)
            cached = data.get("cached_tokens", 0)
            output = data.get("candidates_tokens", 0)
            think = data.get("thoughts_tokens", 0)
            cost = data.get("cost_request", 0.0)
            self._token_info.configure(
                text=f"Prompt: {prompt:,} | Cached: {cached:,} | "
                     f"Output: {output:,} | Think: {think:,} | "
                     f"Kosten: ${cost:.4f}",
            )

        elif event == "keeper.context_injected":
            # Optionales Detail-Event
            parts = data.get("parts", [])
            if parts:
                self._append_timestamp()
                self._append_stream("  Context: ", "label")
                for part in parts:
                    source = part.get("source", "?")
                    length = part.get("length", 0)
                    self._append_stream(f"[{source}: {length} chars] ", "archivar")
                self._append_stream("\n")

        elif event == "archivar.chronicle_updated":
            self._append_timestamp()
            self._append_stream("\u270d ARCHIVAR: ", "label")
            preview = data.get("preview", "")
            self._append_stream(f"Chronik aktualisiert: {preview}\n", "archivar")
            self._refresh_context()

        elif event == "archivar.world_state_updated":
            facts = data.get("new_facts", {})
            if facts:
                self._append_timestamp()
                self._append_stream("\u270d ARCHIVAR: ", "label")
                facts_str = ", ".join(f"{k}={v}" for k, v in facts.items())
                self._append_stream(f"World State: {facts_str}\n", "archivar")

        elif event == "adventure.location_changed":
            loc = data.get("location_name", "?")
            loc_id = data.get("location_id", "?")
            self._append_timestamp()
            self._append_stream(f"  Location: {loc} ({loc_id})\n", "tag")
            self._refresh_context()

        elif event == "adventure.flag_changed":
            key = data.get("flag", "?")
            val = data.get("value", "?")
            self._append_timestamp()
            self._append_stream(f"  Flag: {key} = {val}\n", "tag")
