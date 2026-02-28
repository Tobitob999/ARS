"""
gui/tab_ki_connection.py — Tab 4: KI-Connection

Monitoring der API-Verbindung, Token-Verbrauch, Context Cache und Kosten.
Inkl. Turn-fuer-Turn Verlauf und Token-Trend Canvas-Grafik.
"""

from __future__ import annotations

import logging
import os
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

logger = logging.getLogger("ARS.gui.ki_connection")

# Preise (Gemini 2.5 Flash)
PRICE_INPUT = 0.30 / 1_000_000
PRICE_CACHED = 0.03 / 1_000_000
PRICE_OUTPUT = 2.50 / 1_000_000


class KIConnectionTab(ttk.Frame):
    """KI-Connection Tab — API-Status, Token-Tracking, Cost-Analyse."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        # Turn-Daten fuer Grafik
        self._turn_data: list[dict[str, Any]] = []
        self._session_totals = {
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "candidates_tokens": 0,
            "thoughts_tokens": 0,
            "total_cost": 0.0,
        }

        self._build_ui()

    def _build_ui(self) -> None:
        # Scrollbarer Container
        canvas = tk.Canvas(self, bg=BG_DARK, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas, style="TFrame")
        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        container = scroll_frame

        # ── Verbindungsstatus ──
        conn_frame = ttk.LabelFrame(container, text=" Verbindungsstatus ", style="TLabelframe")
        conn_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD)

        self._conn_labels: dict[str, ttk.Label] = {}
        conn_fields = [
            ("API-Key", "api_key"),
            ("Modell", "model"),
            ("Status", "status"),
            ("Letzte Antwort", "last_response"),
            ("Rate Limits", "rate_limits"),
        ]
        for i, (label, key) in enumerate(conn_fields):
            ttk.Label(conn_frame, text=label).grid(
                row=i, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
            )
            lbl = ttk.Label(conn_frame, text="—", style="Muted.TLabel")
            lbl.grid(row=i, column=1, sticky=tk.W, padx=PAD, pady=PAD_SMALL)
            self._conn_labels[key] = lbl

        ttk.Button(
            conn_frame, text="Test Connection", command=self._test_connection,
        ).grid(row=0, column=2, padx=PAD, pady=PAD_SMALL)

        conn_frame.columnconfigure(1, weight=1)

        # ── Context Cache ──
        cache_frame = ttk.LabelFrame(container, text=" Context Cache ", style="TLabelframe")
        cache_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD)

        self._cache_labels: dict[str, ttk.Label] = {}
        cache_fields = [
            ("Cache Status", "cache_status"),
            ("Cache Name", "cache_name"),
            ("Cache Groesse", "cache_size"),
            ("TTL", "cache_ttl"),
            ("Ersparnis", "cache_savings"),
        ]
        for i, (label, key) in enumerate(cache_fields):
            ttk.Label(cache_frame, text=label).grid(
                row=i, column=0, sticky=tk.W, padx=PAD, pady=PAD_SMALL,
            )
            lbl = ttk.Label(cache_frame, text="—", style="Muted.TLabel")
            lbl.grid(row=i, column=1, sticky=tk.W, padx=PAD, pady=PAD_SMALL)
            self._cache_labels[key] = lbl

        cache_frame.columnconfigure(1, weight=1)

        # ── Session Token-Verbrauch ──
        usage_frame = ttk.LabelFrame(container, text=" Session Token-Verbrauch ", style="TLabelframe")
        usage_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD)

        cols = ("category", "tokens", "cost")
        self._usage_tree = ttk.Treeview(
            usage_frame, columns=cols, show="headings", height=6,
        )
        self._usage_tree.heading("category", text="Kategorie")
        self._usage_tree.heading("tokens", text="Tokens")
        self._usage_tree.heading("cost", text="Kosten")
        self._usage_tree.column("category", width=150)
        self._usage_tree.column("tokens", width=120, anchor=tk.E)
        self._usage_tree.column("cost", width=100, anchor=tk.E)

        # Initiale Zeilen
        self._usage_rows = {}
        for cat in ("Prompt", "Cached", "Output", "Thinking", "GESAMT"):
            iid = self._usage_tree.insert("", tk.END, values=(cat, "0", "$0.0000"))
            self._usage_rows[cat] = iid

        self._usage_tree.pack(fill=tk.X, padx=PAD, pady=PAD)

        # ── Turn-Verlauf ──
        hist_frame = ttk.LabelFrame(container, text=" Verlauf (pro Turn) ", style="TLabelframe")
        hist_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD)

        turn_cols = ("turn", "prompt", "cached", "output", "think", "cost", "latency")
        self._turn_tree = ttk.Treeview(
            hist_frame, columns=turn_cols, show="headings", height=8,
        )
        for col, head, w in [
            ("turn", "Turn", 50), ("prompt", "Prompt", 80), ("cached", "Cached", 80),
            ("output", "Output", 70), ("think", "Think", 60),
            ("cost", "Cost", 70), ("latency", "Lat.", 60),
        ]:
            self._turn_tree.heading(col, text=head)
            self._turn_tree.column(col, width=w, anchor=tk.E if col != "turn" else tk.CENTER)

        turn_scroll = ttk.Scrollbar(hist_frame, orient=tk.VERTICAL, command=self._turn_tree.yview)
        self._turn_tree.configure(yscrollcommand=turn_scroll.set)
        self._turn_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)
        turn_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=PAD)

        # ── Token-Trend Grafik ──
        graph_frame = ttk.LabelFrame(container, text=" Token-Trend ", style="TLabelframe")
        graph_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD)

        self._graph_canvas = tk.Canvas(
            graph_frame, bg=BG_PANEL, height=180, highlightthickness=0,
        )
        self._graph_canvas.pack(fill=tk.X, padx=PAD, pady=PAD)

        # ── History Management ──
        mgmt_frame = ttk.LabelFrame(container, text=" History Management ", style="TLabelframe")
        mgmt_frame.pack(fill=tk.X, padx=PAD_LARGE, pady=PAD)

        mgmt_row = ttk.Frame(mgmt_frame, style="TFrame")
        mgmt_row.pack(fill=tk.X, padx=PAD, pady=PAD)

        self._history_info = ttk.Label(mgmt_row, text="History: 0 / 40 Turns")
        self._history_info.pack(side=tk.LEFT)

        ttk.Button(mgmt_row, text="Clear History", command=self._clear_history).pack(
            side=tk.RIGHT, padx=PAD,
        )
        ttk.Button(mgmt_row, text="Export Log", command=self._export_log).pack(
            side=tk.RIGHT, padx=PAD,
        )

    # ── Updates ──

    def on_engine_ready(self) -> None:
        """Wird aufgerufen wenn die Engine initialisiert ist."""
        engine = self.gui.engine
        backend = engine.ai_backend

        # API-Key Status
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if api_key:
            masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
            self._conn_labels["api_key"].configure(text=f"Geladen (.env): {masked}", style="Green.TLabel")
        else:
            self._conn_labels["api_key"].configure(text="FEHLT", style="Red.TLabel")

        # Modell
        if backend:
            from core.ai_backend import GEMINI_MODEL
            self._conn_labels["model"].configure(text=GEMINI_MODEL)

            # Status
            if backend._client:
                self._conn_labels["status"].configure(text="Connected", style="Green.TLabel")
            else:
                self._conn_labels["status"].configure(text="Stub (kein API-Key)", style="Yellow.TLabel")

            # Cache
            if backend._cache_name:
                self._cache_labels["cache_status"].configure(text="Aktiv", style="Green.TLabel")
                self._cache_labels["cache_name"].configure(text=backend._cache_name[:50] + "...")
                prompt_len = len(getattr(backend, "_system_prompt", ""))
                self._cache_labels["cache_size"].configure(text=f"~{prompt_len // 4:,} tokens")
                self._cache_labels["cache_ttl"].configure(text="7200s")
            else:
                self._cache_labels["cache_status"].configure(text="Inaktiv", style="Muted.TLabel")

    def _update_usage_table(self) -> None:
        """Aktualisiert die Session-Summen Tabelle."""
        t = self._session_totals
        prompt = t["prompt_tokens"]
        cached = t["cached_tokens"]
        output = t["candidates_tokens"]
        think = t["thoughts_tokens"]

        cost_prompt = (prompt - cached) * PRICE_INPUT
        cost_cached = cached * PRICE_CACHED
        cost_output = (output + think) * PRICE_OUTPUT
        total_cost = cost_prompt + cost_cached + cost_output
        t["total_cost"] = total_cost

        self._usage_tree.item(self._usage_rows["Prompt"], values=(
            "Prompt", f"{prompt:,}", f"${cost_prompt:.4f}",
        ))
        self._usage_tree.item(self._usage_rows["Cached"], values=(
            "Cached", f"{cached:,}", f"${cost_cached:.4f}",
        ))
        self._usage_tree.item(self._usage_rows["Output"], values=(
            "Output", f"{output:,}", f"${cost_output:.4f}",
        ))
        self._usage_tree.item(self._usage_rows["Thinking"], values=(
            "Thinking", f"{think:,}", "$0.0000",
        ))
        self._usage_tree.item(self._usage_rows["GESAMT"], values=(
            "GESAMT", f"{prompt + output + think:,}", f"${total_cost:.4f}",
        ))

        # Cache-Ersparnis berechnen
        if cached > 0:
            savings = cached * (PRICE_INPUT - PRICE_CACHED)
            self._cache_labels["cache_savings"].configure(text=f"~${savings:.4f} gespart")

    def _draw_graph(self) -> None:
        """Zeichnet den Token-Trend als Canvas-Linien."""
        c = self._graph_canvas
        c.delete("all")

        if not self._turn_data:
            c.create_text(
                c.winfo_width() // 2, 90,
                text="(Noch keine Daten)", fill=FG_MUTED, font=FONT_SMALL,
            )
            return

        w = c.winfo_width() or 400
        h = 170
        margin_left = 50
        margin_bottom = 20
        plot_w = w - margin_left - 20
        plot_h = h - margin_bottom - 10

        # Daten
        n = len(self._turn_data)
        if n < 2:
            return

        max_prompt = max(d.get("prompt_tokens", 1) for d in self._turn_data)
        max_output = max(d.get("candidates_tokens", 1) for d in self._turn_data)
        max_val = max(max_prompt, max_output, 1)

        # Achse
        c.create_line(margin_left, 10, margin_left, h - margin_bottom, fill=FG_MUTED)
        c.create_line(margin_left, h - margin_bottom, w - 20, h - margin_bottom, fill=FG_MUTED)

        # Y-Achse Labels
        for frac in (0, 0.5, 1.0):
            y = int(10 + plot_h * (1 - frac))
            val = int(max_val * frac)
            c.create_text(margin_left - 5, y, text=f"{val:,}", fill=FG_MUTED, font=FONT_SMALL, anchor=tk.E)
            c.create_line(margin_left, y, w - 20, y, fill=BG_INPUT, dash=(2, 4))

        # X-Achse Labels
        c.create_text(w // 2, h - 5, text="Turns", fill=FG_MUTED, font=FONT_SMALL)

        # Punkte berechnen
        def _points(key: str) -> list[tuple[int, int]]:
            pts = []
            for i, d in enumerate(self._turn_data):
                x = margin_left + int((i / (n - 1)) * plot_w)
                v = d.get(key, 0)
                y = int(10 + plot_h * (1 - v / max_val))
                pts.append((x, y))
            return pts

        # Prompt-Linie
        prompt_pts = _points("prompt_tokens")
        if len(prompt_pts) >= 2:
            flat = [coord for pt in prompt_pts for coord in pt]
            c.create_line(*flat, fill=BLUE, width=2, smooth=True)
            c.create_text(w - 60, prompt_pts[-1][1], text="Prompt", fill=BLUE, font=FONT_SMALL)

        # Output-Linie
        output_pts = _points("candidates_tokens")
        if len(output_pts) >= 2:
            flat = [coord for pt in output_pts for coord in pt]
            c.create_line(*flat, fill=GREEN, width=2, smooth=True)
            c.create_text(w - 60, output_pts[-1][1] + 12, text="Output", fill=GREEN, font=FONT_SMALL)

    def _test_connection(self) -> None:
        """Testet die API-Verbindung."""
        engine = self.gui.engine
        if engine.ai_backend and engine.ai_backend._client:
            self._conn_labels["status"].configure(text="Connected", style="Green.TLabel")
        else:
            self._conn_labels["status"].configure(text="Disconnected", style="Red.TLabel")

    def _clear_history(self) -> None:
        engine = self.gui.engine
        if engine.ai_backend:
            engine.ai_backend.reset_history()
            self._history_info.configure(text="History: 0 / 40 Turns")

    def _export_log(self) -> None:
        """Exportiert den Turn-Verlauf als Textdatei."""
        from pathlib import Path
        from datetime import datetime
        log_path = Path("logs") / f"token_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        log_path.parent.mkdir(exist_ok=True)
        with log_path.open("w", encoding="utf-8") as f:
            f.write("Turn | Prompt | Cached | Output | Think | Cost | Latency\n")
            f.write("-" * 60 + "\n")
            for d in self._turn_data:
                f.write(
                    f"#{d.get('turn', '?'):>4} | "
                    f"{d.get('prompt_tokens', 0):>7,} | "
                    f"{d.get('cached_tokens', 0):>7,} | "
                    f"{d.get('candidates_tokens', 0):>7,} | "
                    f"{d.get('thoughts_tokens', 0):>6,} | "
                    f"${d.get('cost', 0):.4f} | "
                    f"{d.get('latency', 0):.1f}s\n"
                )
            f.write(f"\nGesamt: ${self._session_totals['total_cost']:.4f}\n")
        logger.info("Token-Log exportiert: %s", log_path)

    # ── EventBus Handler ──

    def handle_event(self, data: dict[str, Any]) -> None:
        event = data.get("_event", "")

        if event == "keeper.usage_update":
            prompt = data.get("prompt_tokens", 0)
            cached = data.get("cached_tokens", 0)
            output = data.get("candidates_tokens", 0)
            think = data.get("thoughts_tokens", 0)
            cost = data.get("cost_request", 0.0)
            latency = data.get("latency", 0.0)

            # Session-Summen
            self._session_totals["prompt_tokens"] += prompt
            self._session_totals["cached_tokens"] += cached
            self._session_totals["candidates_tokens"] += output
            self._session_totals["thoughts_tokens"] += think

            # Turn-Daten
            turn_num = len(self._turn_data) + 1
            turn_entry = {
                "turn": turn_num,
                "prompt_tokens": prompt,
                "cached_tokens": cached,
                "candidates_tokens": output,
                "thoughts_tokens": think,
                "cost": cost,
                "latency": latency,
            }
            self._turn_data.append(turn_entry)

            # Turn-Tabelle aktualisieren
            self._turn_tree.insert("", tk.END, values=(
                f"#{turn_num}", f"{prompt:,}", f"{cached:,}",
                f"{output:,}", f"{think:,}", f"${cost:.4f}",
                f"{latency:.1f}s" if latency else "—",
            ))
            self._turn_tree.yview_moveto(1.0)

            # Summen-Tabelle
            self._update_usage_table()

            # Grafik
            self._draw_graph()

            # History-Info
            engine = self.gui.engine
            if engine.ai_backend:
                hist_len = len(engine.ai_backend._history)
                self._history_info.configure(text=f"History: {hist_len} / 40 Turns")

            # Letzte Antwort
            self._conn_labels["last_response"].configure(text="gerade eben")

        elif event == "keeper.prompt_sent":
            self._conn_labels["last_response"].configure(text="...")
