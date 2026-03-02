"""
gui/tab_injector.py — Injector: Prompt-Bau Spielwiese

Technische Werkbank fuer alles, was IN die KI geht:
- System-Prompt Sektionen einzeln inspizieren und editieren
- Dynamischen Kontext (Chronik, World State, Location) manipulieren
- Prompt zusammenbauen, Token-Schaetzung, Cache-Status
- Test-Nachricht mit aktuellem Prompt an Gemini senden
"""

from __future__ import annotations

import logging
import re
import tkinter as tk
import tkinter.ttk as ttk
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE, BLUE, LAVENDER,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, FONT_HEADER, PAD, PAD_SMALL, PAD_LARGE,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.injector")

# Farben fuer Prompt-Sektionen
_SEC_COLORS = {
    "persona":   ("#2D2D4F", FG_PRIMARY),
    "setting":   ("#2D3D2D", FG_PRIMARY),
    "keeper":    ("#3D2D3D", FG_PRIMARY),
    "character": ("#2D3D3D", FG_PRIMARY),
    "rules":     ("#3D3D2D", FG_PRIMARY),
    "adventure": ("#3D2D2D", FG_PRIMARY),
    "extras":    ("#2D2D3D", FG_PRIMARY),
}


class InjectorTab(ttk.Frame):
    """Prompt-Bau Spielwiese — alles was IN die KI geht."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        # Gespeicherte Sektionen (key -> text)
        self._sections: list[tuple[str, str, str]] = []  # (key, title, text)
        self._section_edits: dict[str, tk.Text] = {}
        self._section_enabled: dict[str, tk.BooleanVar] = {}

        self._build_ui()

    # ==================================================================
    # UI
    # ==================================================================

    def _build_ui(self) -> None:
        # Haupt-Paned: Links Sektions-Editor, Rechts Vorschau + Test
        main_paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        # ── Links: Sektions-Editor ──
        left = ttk.Frame(main_paned, style="TFrame")
        main_paned.add(left, weight=3)

        # Toolbar
        toolbar = ttk.Frame(left, style="TFrame")
        toolbar.pack(fill=tk.X, pady=PAD_SMALL)

        ttk.Button(
            toolbar, text="Vom Engine laden", command=self._load_from_engine,
        ).pack(side=tk.LEFT, padx=PAD_SMALL)
        ttk.Button(
            toolbar, text="Alle ein", command=lambda: self._toggle_all(True),
        ).pack(side=tk.LEFT, padx=PAD_SMALL)
        ttk.Button(
            toolbar, text="Alle aus", command=lambda: self._toggle_all(False),
        ).pack(side=tk.LEFT, padx=PAD_SMALL)
        ttk.Button(
            toolbar, text="Zusammenbauen \u2192", command=self._assemble_prompt,
            style="Accent.TButton",
        ).pack(side=tk.RIGHT, padx=PAD_SMALL)

        # Info-Zeile
        self._info_label = tk.Label(
            left, text="Sektionen: — | Gesamt: — Zeichen",
            bg=BG_PANEL, fg=FG_SECONDARY, font=FONT_SMALL, anchor=tk.W, padx=PAD,
        )
        self._info_label.pack(fill=tk.X)

        # Scrollbarer Bereich fuer Sektionen
        canvas_frame = ttk.Frame(left, style="TFrame")
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(canvas_frame, bg=BG_DARK, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._sections_frame = ttk.Frame(self._canvas, style="TFrame")
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._sections_frame, anchor=tk.NW,
        )

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._sections_frame.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # ── Rechts: Vorschau + Test ──
        right = ttk.Frame(main_paned, style="TFrame")
        main_paned.add(right, weight=2)

        right_paned = ttk.PanedWindow(right, orient=tk.VERTICAL)
        right_paned.pack(fill=tk.BOTH, expand=True)

        # Vorschau-Panel
        preview_frame = ttk.LabelFrame(
            right_paned, text=" Zusammengebauter Prompt ", style="TLabelframe",
        )
        right_paned.add(preview_frame, weight=2)

        self._preview_info = tk.Label(
            preview_frame, text="Zeichen: — | ~Tokens: — | Cache: —",
            bg=BG_PANEL, fg=FG_SECONDARY, font=FONT_SMALL, anchor=tk.W, padx=PAD,
        )
        self._preview_info.pack(fill=tk.X)

        pf = ttk.Frame(preview_frame, style="TFrame")
        pf.pack(fill=tk.BOTH, expand=True)

        self._preview_text = tk.Text(
            pf, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD,
        )
        ps = ttk.Scrollbar(pf, orient=tk.VERTICAL, command=self._preview_text.yview)
        self._preview_text.configure(yscrollcommand=ps.set)
        self._preview_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ps.pack(side=tk.RIGHT, fill=tk.Y)

        for key, (bg, fg) in _SEC_COLORS.items():
            self._preview_text.tag_configure(key, background=bg, foreground=fg)
        self._preview_text.tag_configure("header", foreground=FG_ACCENT, font=FONT_BOLD)
        self._preview_text.tag_configure("muted", foreground=FG_MUTED)

        # Test-Panel
        test_frame = ttk.LabelFrame(
            right_paned, text=" Test-Nachricht an KI ", style="TLabelframe",
        )
        right_paned.add(test_frame, weight=1)

        # Eingabezeile
        input_row = ttk.Frame(test_frame, style="TFrame")
        input_row.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        ttk.Label(input_row, text="Nachricht:").pack(side=tk.LEFT)
        self._test_input = tk.Entry(
            input_row, bg=BG_INPUT, fg=FG_PRIMARY, font=FONT_NORMAL,
            insertbackground=FG_PRIMARY,
        )
        self._test_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=PAD_SMALL)
        self._test_input.insert(0, "Ich betrete das Haus.")
        self._test_input.bind("<Return>", lambda e: self._send_test())

        ttk.Button(
            input_row, text="Senden", command=self._send_test, style="Accent.TButton",
        ).pack(side=tk.RIGHT, padx=PAD_SMALL)

        # Test-Antwort
        tf = ttk.Frame(test_frame, style="TFrame")
        tf.pack(fill=tk.BOTH, expand=True)

        self._test_output = tk.Text(
            tf, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
            borderwidth=0, padx=PAD, pady=PAD, height=6,
        )
        ts = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._test_output.yview)
        self._test_output.configure(yscrollcommand=ts.set)
        self._test_output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ts.pack(side=tk.RIGHT, fill=tk.Y)

        self._test_output.tag_configure("response", foreground=LAVENDER)
        self._test_output.tag_configure("error", foreground=RED)
        self._test_output.tag_configure("info", foreground=FG_MUTED)

    # ==================================================================
    # Canvas-Scroll
    # ==================================================================

    def _on_frame_configure(self, event: Any = None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: Any = None) -> None:
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    # ==================================================================
    # Engine-Daten laden
    # ==================================================================

    def _load_from_engine(self) -> None:
        """Laedt den aktuellen System-Prompt und zerlegt ihn in Sektionen."""
        engine = self.gui.engine
        if not engine.ai_backend:
            self._set_info("Engine nicht initialisiert")
            return

        prompt = getattr(engine.ai_backend, "_system_prompt", "")
        if not prompt:
            self._set_info("Kein System-Prompt vorhanden")
            return

        self._sections = self._parse_prompt_sections(prompt)
        self._rebuild_section_editors()

    def _parse_prompt_sections(self, prompt: str) -> list[tuple[str, str, str]]:
        """Zerteilt den System-Prompt in Sektionen (key, title, text)."""
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

        header_re = re.compile(r"^═══\s*(.+?)\s*═══\s*$", re.MULTILINE)
        matches = list(header_re.finditer(prompt))

        if not matches:
            return [("persona", "System-Prompt (ungeparst)", prompt)]

        result: list[tuple[str, str, str]] = []

        # Preamble
        preamble = prompt[:matches[0].start()].strip()
        if preamble:
            result.append(("persona", "Persona (Preamble)", preamble))

        for i, match in enumerate(matches):
            header_text = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(prompt)
            body = prompt[start:end].strip()

            key, title = "rules", header_text
            for substring, mapped_key, mapped_title in header_map:
                if substring in header_text.upper():
                    key = mapped_key
                    title = mapped_title
                    break

            result.append((key, title, body))

        return result

    def _rebuild_section_editors(self) -> None:
        """Baut die Sektions-Editoren im linken Panel neu auf."""
        # Alte Widgets entfernen
        for widget in self._sections_frame.winfo_children():
            widget.destroy()
        self._section_edits.clear()
        self._section_enabled.clear()

        total_chars = 0

        for idx, (key, title, text) in enumerate(self._sections):
            bg, fg = _SEC_COLORS.get(key, (BG_PANEL, FG_PRIMARY))
            char_count = len(text)
            tok_est = char_count // 4
            total_chars += char_count

            # Header-Zeile mit Checkbox
            header_frame = tk.Frame(self._sections_frame, bg=bg)
            header_frame.pack(fill=tk.X, padx=2, pady=(PAD_SMALL if idx > 0 else 0, 0))

            var = tk.BooleanVar(value=True)
            self._section_enabled[f"{idx}_{key}"] = var

            cb = tk.Checkbutton(
                header_frame, variable=var, bg=bg, fg=fg,
                activebackground=bg, selectcolor=BG_INPUT,
            )
            cb.pack(side=tk.LEFT)

            tk.Label(
                header_frame, text=f"\u2588 {title}",
                bg=bg, fg=FG_ACCENT, font=FONT_BOLD,
            ).pack(side=tk.LEFT, padx=PAD_SMALL)

            tk.Label(
                header_frame, text=f"({char_count:,} Z. / ~{tok_est:,} Tok.)",
                bg=bg, fg=FG_MUTED, font=FONT_SMALL,
            ).pack(side=tk.RIGHT, padx=PAD_SMALL)

            # Text-Editor (kollabierbar)
            editor = tk.Text(
                self._sections_frame, bg=bg, fg=fg, font=FONT_SMALL,
                wrap=tk.WORD, highlightthickness=0, borderwidth=1,
                relief=tk.FLAT, padx=PAD, pady=PAD_SMALL,
                insertbackground=FG_PRIMARY,
                height=min(max(text.count("\n") + 1, 3), 12),
            )
            editor.insert("1.0", text)
            editor.pack(fill=tk.X, padx=2)
            self._section_edits[f"{idx}_{key}"] = editor

        total_tok = total_chars // 4
        self._set_info(
            f"Sektionen: {len(self._sections)} | "
            f"Gesamt: {total_chars:,} Zeichen (~{total_tok:,} Tokens)"
        )

        # Canvas-Scrollregion aktualisieren
        self._sections_frame.update_idletasks()
        self._on_frame_configure()

    # ==================================================================
    # Prompt zusammenbauen
    # ==================================================================

    def _assemble_prompt(self) -> None:
        """Baut den Prompt aus den (editierten) Sektionen zusammen und zeigt ihn in der Vorschau."""
        self._preview_text.configure(state=tk.NORMAL)
        self._preview_text.delete("1.0", tk.END)

        if not self._section_edits:
            self._preview_text.insert(tk.END, "(Keine Sektionen geladen — klicke 'Vom Engine laden')\n", "muted")
            self._preview_text.configure(state=tk.DISABLED)
            return

        assembled_parts: list[str] = []
        active_count = 0

        for idx, (key, title, _original) in enumerate(self._sections):
            edit_key = f"{idx}_{key}"
            enabled = self._section_enabled.get(edit_key)
            if enabled and not enabled.get():
                # Sektion deaktiviert - uebersprungen
                self._preview_text.insert(
                    tk.END, f"\u2610 {title} (deaktiviert)\n", "muted",
                )
                continue

            editor = self._section_edits.get(edit_key)
            if not editor:
                continue

            text = editor.get("1.0", tk.END).strip()
            if not text:
                continue

            active_count += 1
            assembled_parts.append(text)

            # In Vorschau einfuegen
            char_count = len(text)
            tok_est = char_count // 4
            self._preview_text.insert(
                tk.END,
                f"\u2611 {title} ({char_count:,} Z. / ~{tok_est:,} Tok.)\n",
                "header",
            )
            # Gekuerzte Vorschau (max 500 Zeichen pro Sektion)
            preview = text[:500]
            if len(text) > 500:
                preview += f"\n... ({len(text) - 500:,} weitere Zeichen)"
            self._preview_text.insert(tk.END, preview + "\n\n", key)

        full_prompt = "\n\n".join(assembled_parts)
        total_chars = len(full_prompt)
        total_tok = total_chars // 4
        cache_eligible = total_chars >= 15000

        self._preview_info.configure(
            text=f"Zeichen: {total_chars:,} | ~Tokens: {total_tok:,} | "
                 f"Cache: {'moeglich' if cache_eligible else 'zu kurz (<15k)'}",
        )

        self._preview_text.configure(state=tk.DISABLED)

    # ==================================================================
    # Test-Nachricht senden
    # ==================================================================

    def _send_test(self) -> None:
        """Sendet eine Test-Nachricht mit dem aktuellen Prompt an die KI."""
        engine = self.gui.engine
        if not engine.ai_backend:
            self._test_append("Engine nicht initialisiert.\n", "error")
            return

        msg = self._test_input.get().strip()
        if not msg:
            return

        self._test_append(f"\u25b6 {msg}\n", "info")

        # Im Hintergrund-Thread senden um GUI nicht zu blockieren
        import threading

        def _run():
            try:
                response = ""
                for chunk in engine.ai_backend.chat_stream(msg):
                    response += chunk
                self._test_output.after(0, self._test_append, f"\u25c0 {response}\n\n", "response")
            except Exception as exc:
                self._test_output.after(0, self._test_append, f"Fehler: {exc}\n\n", "error")

        threading.Thread(target=_run, daemon=True).start()

    def _test_append(self, text: str, tag: str = "") -> None:
        self._test_output.configure(state=tk.NORMAL)
        if tag:
            self._test_output.insert(tk.END, text, tag)
        else:
            self._test_output.insert(tk.END, text)
        self._test_output.see(tk.END)
        self._test_output.configure(state=tk.DISABLED)

    # ==================================================================
    # Hilfsmethoden
    # ==================================================================

    def _set_info(self, text: str) -> None:
        self._info_label.configure(text=text)

    def _toggle_all(self, state: bool) -> None:
        for var in self._section_enabled.values():
            var.set(state)

    def on_engine_ready(self) -> None:
        """Wird aufgerufen wenn die Engine initialisiert ist."""
        self._load_from_engine()
        self._assemble_prompt()

    def handle_event(self, data: dict[str, Any]) -> None:
        """Events vom EventBus (derzeit keine speziellen Injector-Events)."""
        pass
