"""
gui/tab_conversion_monitor.py — Tab 9: Conversion Monitor

Zeigt den Status der PDF-Konvertierungs-Pipeline:
  - Workload-Queue (coversion/workload/)
  - Fertige Bundles (coversion/finished/)
  - Archiv (coversion/root/finished/)
"""

from __future__ import annotations

import logging
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, PAD, PAD_SMALL,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.conversion")

# Basisverzeichnis relativ zum Projekt-Root
_PROJECT_ROOT = Path(__file__).parent.parent
COVERSION_DIR = _PROJECT_ROOT / "coversion"
WORKLOAD_DIR = COVERSION_DIR / "workload"
FINISHED_DIR = COVERSION_DIR / "finished"
ARCHIVE_DIR = COVERSION_DIR / "root" / "finished"


class ConversionMonitorTab(ttk.Frame):
    """Conversion Pipeline Monitor — Workload, Finished, Archiv."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")
        self._build_ui()

    def _build_ui(self) -> None:
        # Refresh-Button oben
        top = ttk.Frame(self, style="TFrame")
        top.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)
        ttk.Button(top, text="Refresh", command=self._refresh).pack(side=tk.LEFT)
        self._status_label = ttk.Label(top, text="", style="Muted.TLabel")
        self._status_label.pack(side=tk.RIGHT)

        # Drei Bereiche: Workload, Finished, Archive
        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD_SMALL)

        # ── Workload ──
        wl_frame = ttk.LabelFrame(paned, text=" Workload (wartend) ", style="TLabelframe")
        paned.add(wl_frame, weight=1)

        self._wl_tree = ttk.Treeview(
            wl_frame, columns=("file", "size"), show="headings", height=5,
        )
        self._wl_tree.heading("file", text="Datei")
        self._wl_tree.heading("size", text="Groesse")
        self._wl_tree.column("file", width=400)
        self._wl_tree.column("size", width=100)
        self._wl_tree.pack(fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)

        # ── Finished ──
        fin_frame = ttk.LabelFrame(paned, text=" Finished (Bundles) ", style="TLabelframe")
        paned.add(fin_frame, weight=2)

        self._fin_tree = ttk.Treeview(
            fin_frame, columns=("system", "dirs", "files", "qa"), show="headings", height=6,
        )
        self._fin_tree.heading("system", text="System")
        self._fin_tree.heading("dirs", text="Ordner")
        self._fin_tree.heading("files", text="Dateien")
        self._fin_tree.heading("qa", text="QA-Status")
        self._fin_tree.column("system", width=200)
        self._fin_tree.column("dirs", width=80)
        self._fin_tree.column("files", width=80)
        self._fin_tree.column("qa", width=100)
        self._fin_tree.pack(fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)

        # ── Archive ──
        arc_frame = ttk.LabelFrame(paned, text=" Archiv (verarbeitet) ", style="TLabelframe")
        paned.add(arc_frame, weight=1)

        self._arc_tree = ttk.Treeview(
            arc_frame, columns=("file", "size"), show="headings", height=4,
        )
        self._arc_tree.heading("file", text="Datei")
        self._arc_tree.heading("size", text="Groesse")
        self._arc_tree.column("file", width=400)
        self._arc_tree.column("size", width=100)
        self._arc_tree.pack(fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)

    def _refresh(self) -> None:
        """Scannt die Conversion-Verzeichnisse und aktualisiert die Anzeige."""
        # Workload
        self._clear_tree(self._wl_tree)
        wl_count = 0
        if WORKLOAD_DIR.is_dir():
            for f in sorted(WORKLOAD_DIR.iterdir()):
                if f.is_file() and f.suffix.lower() == ".pdf":
                    size = self._fmt_size(f.stat().st_size)
                    self._wl_tree.insert("", tk.END, values=(f.name, size))
                    wl_count += 1

        # Finished bundles
        self._clear_tree(self._fin_tree)
        fin_count = 0
        if FINISHED_DIR.is_dir():
            for d in sorted(FINISHED_DIR.iterdir()):
                if d.is_dir():
                    dirs = sum(1 for x in d.rglob("*") if x.is_dir())
                    files = sum(1 for x in d.rglob("*") if x.is_file())
                    # QA-Report pruefen
                    qa_path = d / "indices" / "conversion_qa_report.json"
                    if qa_path.exists():
                        try:
                            import json
                            qa = json.loads(qa_path.read_text(encoding="utf-8"))
                            qa_status = qa.get("validation_status", "?")
                        except Exception:
                            qa_status = "error"
                    else:
                        qa_status = "missing"
                    self._fin_tree.insert("", tk.END, values=(d.name, dirs, files, qa_status))
                    fin_count += 1

        # Archive
        self._clear_tree(self._arc_tree)
        arc_count = 0
        if ARCHIVE_DIR.is_dir():
            for f in sorted(ARCHIVE_DIR.iterdir()):
                if f.is_file():
                    size = self._fmt_size(f.stat().st_size)
                    self._arc_tree.insert("", tk.END, values=(f.name, size))
                    arc_count += 1

        self._status_label.configure(
            text=f"Workload: {wl_count} | Fertig: {fin_count} | Archiv: {arc_count}",
        )

    def on_engine_ready(self) -> None:
        self._refresh()

    def handle_event(self, data: dict[str, Any]) -> None:
        pass

    @staticmethod
    def _clear_tree(tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    @staticmethod
    def _fmt_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes / (1024 * 1024):.1f} MB"
