"""
gui/tab_test_monitor.py — Tab 10: Test-Monitor

Echtzeit-Uebersicht fuer VirtualPlayer-Testlaeufe:
  - Steuerung: Modul/Case/Adventure waehlen, Queue, Batch starten/stoppen
  - Aktive Runs: Live-Fortschritt via JSON-Progress-Files
  - Systemlast: CPU/RAM (+ GPU/VRAM falls pynvml vorhanden)
  - Abgeschlossene Runs: Ergebnis-Tabelle mit Inline-Scoring + Detail-Dialog
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.ttk as ttk
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, FONT_HEADER, PAD, PAD_SMALL, PAD_LARGE,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.test_monitor")

_PROJECT_ROOT = Path(__file__).parent.parent
_PROGRESS_DIR = _PROJECT_ROOT / "data" / "test_progress"
_RESULTS_DIR = _PROJECT_ROOT / "data" / "test_results"

# Verfuegbare Module
_MODULES = ["cthulhu_7e", "add_2e", "paranoia_2e", "shadowrun_6", "mad_max"]

# Test Cases
_CASES = {
    1: "generic",
    2: "investigation",
    3: "combat",
    4: "horror",
    5: "social",
}

# ── Graceful psutil / pynvml import ──────────────────────────────────

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

try:
    import pynvml
    pynvml.nvmlInit()
    _HAS_PYNVML = True
except Exception:
    _HAS_PYNVML = False


# ── Inline Scoring (gleiche Logik wie test_evaluator.py) ─────────────

import re

_HOOK_RE = re.compile(r"(\?\s*(\[[^\]]*\]\s*)*$|\[PROBE:[^\]]+\]\s*$)")
_TAG_PATTERNS = {
    "PROBE": re.compile(r"\[PROBE:\s*[^\]]+\]"),
    "HP_VERLUST": re.compile(r"\[HP_VERLUST:\s*\d+\s*\]"),
    "HP_HEILUNG": re.compile(r"\[HP_HEILUNG:\s*[^\]]+\]"),
    "STABILITAET_VERLUST": re.compile(r"\[STABILITAET_VERLUST:\s*[^\]]+\]"),
    "XP_GEWINN": re.compile(r"\[XP_GEWINN:\s*\d+\s*\]"),
    "FERTIGKEIT_GENUTZT": re.compile(r"\[FERTIGKEIT_GENUTZT:\s*[^\]]+\]"),
    "INVENTAR": re.compile(r"\[INVENTAR:\s*[^\]]+\]"),
    "ANGRIFF": re.compile(r"\[ANGRIFF:\s*[^\]]+\]"),
    "RETTUNGSWURF": re.compile(r"\[RETTUNGSWURF:\s*[^\]]+\]"),
    "FAKT": re.compile(r"\[FAKT:\s*[^\]]+\]"),
    "STIMME": re.compile(r"\[STIMME:\s*[^\]]+\]"),
}


def _inline_score(data: dict[str, Any]) -> int:
    """Berechnet Score analog test_evaluator.py (100 Punkte)."""
    turns = data.get("turns", [])
    expected_tags = data.get("expected_tags", {})
    character_alive = data.get("character_alive", True)
    avg_latency = data.get("avg_latency_ms", 0.0)
    total_warnings = data.get("total_rules_warnings", 0)

    # Tags (40)
    score_tags = 40
    if expected_tags:
        checks_passed = 0
        for tag_name, min_count in expected_tags.items():
            actual = 0
            for turn in turns:
                resp = turn.get("keeper_response", "")
                pat = _TAG_PATTERNS.get(tag_name)
                if pat:
                    actual += len(pat.findall(resp))
            if actual >= min_count:
                checks_passed += 1
        total_checks = len(expected_tags)
        score_tags = round(40 * checks_passed / total_checks) if total_checks else 40

    # Monolog (20)
    total_sentences = 0
    valid_turns = 0
    for turn in turns:
        resp = turn.get("keeper_response", "")
        if not resp:
            continue
        clean = re.sub(r"\[[^\]]+\]", "", resp).strip()
        n_sent = len(re.findall(r"[.!?]+(?:\s|$)", clean)) if clean else 0
        total_sentences += n_sent
        valid_turns += 1
    avg_sent = total_sentences / valid_turns if valid_turns else 0
    if avg_sent <= 4:
        score_monolog = 20
    elif avg_sent <= 6:
        score_monolog = 10
    else:
        score_monolog = 0

    # Cross-System (15)
    if total_warnings == 0:
        score_cross = 15
    elif total_warnings <= 2:
        score_cross = 8
    else:
        score_cross = 0

    # Alive (10)
    score_alive = 10 if character_alive else 0

    # Hook (10)
    hook_ok = 0
    hook_total = 0
    for turn in turns:
        resp = turn.get("keeper_response", "")
        if not resp:
            continue
        hook_total += 1
        stripped = resp.rstrip()
        without_tags = re.sub(r"(\s*\[[^\]]*\])+\s*$", "", stripped)
        if without_tags.rstrip().endswith("?") or re.search(r"\[PROBE:[^\]]+\]\s*$", stripped):
            hook_ok += 1
    score_hook = round(10 * hook_ok / hook_total) if hook_total else 10

    # Latenz (5)
    if avg_latency < 10_000:
        score_latency = 5
    elif avg_latency < 20_000:
        score_latency = 2
    else:
        score_latency = 0

    return score_tags + score_monolog + score_cross + score_alive + score_hook + score_latency


# ── Run-Konfiguration ────────────────────────────────────────────────

@dataclass
class RunConfig:
    """Konfiguration fuer einen einzelnen Testlauf."""
    module: str
    case_id: int
    case_name: str
    adventure: str | None
    turns: int


@dataclass
class ActiveRun:
    """Laufende Subprocess-Instanz (oder extern erkannter Run)."""
    config: RunConfig
    progress_file: Path
    proc: subprocess.Popen | None = None   # None = extern gestartet
    tree_id: str = ""
    external: bool = False                 # True = aus Verzeichnis-Scan erkannt


@dataclass
class CompletedRun:
    """Abgeschlossener Lauf mit Ergebnis."""
    config: RunConfig
    result_file: Path | None = None
    result_data: dict[str, Any] = field(default_factory=dict)
    score: int = 0
    avg_latency: float = 0.0
    total_probes: int = 0
    total_combat: int = 0
    total_warnings: int = 0
    character_alive: bool = True
    tree_id: str = ""


# ── Tab-Klasse ────────────────────────────────────────────────────────

class TestMonitorTab(ttk.Frame):
    """Test-Monitor Tab — Echtzeit-Dashboard fuer VirtualPlayer-Laeufe."""

    def __init__(self, parent: ttk.Notebook, gui: TechGUI) -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        self._queue: list[RunConfig] = []
        self._active_runs: dict[str, ActiveRun] = {}   # progress_file_name -> ActiveRun
        self._completed_runs: list[CompletedRun] = []
        self._max_parallel = 2
        self._run_counter = 0
        self._known_progress_files: set[str] = set()   # Bereits erkannte Dateien
        self._finished_files: set[str] = set()          # Abgeschlossene Dateien

        _PROGRESS_DIR.mkdir(parents=True, exist_ok=True)

        self._build_ui()

        # Auto-Polling immer aktiv — scannt Verzeichnis auf neue Progress-Files
        self.after(1000, self._poll_progress)

    def _build_ui(self) -> None:
        # ── Sektion 1: Steuerung ──
        ctrl_frame = ttk.LabelFrame(self, text=" Steuerung ", style="TLabelframe")
        ctrl_frame.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        # Zeile 1: Modul, Case, Adventure
        row1 = ttk.Frame(ctrl_frame, style="TFrame")
        row1.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        ttk.Label(row1, text="Modul:").pack(side=tk.LEFT, padx=(0, 4))
        self._var_module = tk.StringVar(value=_MODULES[0])
        self._cb_module = ttk.Combobox(
            row1, textvariable=self._var_module, values=_MODULES,
            state="readonly", width=14,
        )
        self._cb_module.pack(side=tk.LEFT, padx=(0, PAD))

        ttk.Label(row1, text="Case:").pack(side=tk.LEFT, padx=(0, 4))
        case_values = [f"{cid}-{cname}" for cid, cname in _CASES.items()]
        self._var_case = tk.StringVar(value=case_values[0])
        self._cb_case = ttk.Combobox(
            row1, textvariable=self._var_case, values=case_values,
            state="readonly", width=16,
        )
        self._cb_case.pack(side=tk.LEFT, padx=(0, PAD))

        ttk.Label(row1, text="Adventure:").pack(side=tk.LEFT, padx=(0, 4))
        self._var_adventure = tk.StringVar(value="")
        self._cb_adventure = ttk.Combobox(
            row1, textvariable=self._var_adventure, values=[""],
            state="readonly", width=16,
        )
        self._cb_adventure.pack(side=tk.LEFT, padx=(0, PAD))
        self._cb_module.bind("<<ComboboxSelected>>", self._on_module_changed)

        # Zeile 2: Zuege, Max Parallel
        row2 = ttk.Frame(ctrl_frame, style="TFrame")
        row2.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        ttk.Label(row2, text="Zuege:").pack(side=tk.LEFT, padx=(0, 4))
        self._var_turns = tk.IntVar(value=10)
        self._spin_turns = ttk.Spinbox(
            row2, from_=1, to=50, textvariable=self._var_turns, width=5,
        )
        self._spin_turns.pack(side=tk.LEFT, padx=(0, PAD))

        ttk.Label(row2, text="Max parallel:").pack(side=tk.LEFT, padx=(0, 4))
        self._var_parallel = tk.IntVar(value=2)
        self._spin_parallel = ttk.Spinbox(
            row2, from_=1, to=4, textvariable=self._var_parallel, width=4,
        )
        self._spin_parallel.pack(side=tk.LEFT, padx=(0, PAD))

        # Zeile 3: Buttons
        row3 = ttk.Frame(ctrl_frame, style="TFrame")
        row3.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        ttk.Button(row3, text="+ Hinzufuegen", command=self._add_to_queue).pack(
            side=tk.LEFT, padx=(0, PAD),
        )
        ttk.Button(
            row3, text=">> Batch starten", style="Accent.TButton",
            command=self._start_batch,
        ).pack(side=tk.LEFT, padx=(0, PAD))
        ttk.Button(
            row3, text="X Alle stoppen", style="Danger.TButton",
            command=self._stop_all,
        ).pack(side=tk.LEFT, padx=(0, PAD))

        self._lbl_counts = ttk.Label(
            row3, text="Warteschlange: 0 | Aktiv: 0/2 | Fertig: 0",
            style="Muted.TLabel",
        )
        self._lbl_counts.pack(side=tk.RIGHT)

        # ── Sektion 2: Aktive Runs ──
        active_frame = ttk.LabelFrame(self, text=" Aktive Runs ", style="TLabelframe")
        active_frame.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD_SMALL)

        active_cols = ("num", "module", "case", "adventure", "progress", "status", "latency", "pid")
        self._active_tree = ttk.Treeview(
            active_frame, columns=active_cols, show="headings", height=5,
        )
        for col, head, w, anc in [
            ("num", "#", 35, tk.CENTER),
            ("module", "Modul", 100, tk.W),
            ("case", "Case", 110, tk.W),
            ("adventure", "Abenteuer", 100, tk.W),
            ("progress", "Fortschritt", 120, tk.W),
            ("status", "Status", 80, tk.CENTER),
            ("latency", "Latenz", 80, tk.E),
            ("pid", "PID", 60, tk.E),
        ]:
            self._active_tree.heading(col, text=head)
            self._active_tree.column(col, width=w, anchor=anc)

        self._active_tree.pack(fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)

        # Rechtsklick-Kontextmenu
        self._active_menu = tk.Menu(self._active_tree, tearoff=0, bg=BG_PANEL, fg=FG_PRIMARY)
        self._active_menu.add_command(label="Run stoppen", command=self._stop_selected_run)
        self._active_tree.bind("<Button-3>", self._on_active_right_click)

        # ── Sektion 3: Systemlast ──
        sys_frame = ttk.LabelFrame(self, text=" Systemlast ", style="TLabelframe")
        sys_frame.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        sys_inner = ttk.Frame(sys_frame, style="TFrame")
        sys_inner.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        # CPU
        ttk.Label(sys_inner, text="CPU:").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        self._pb_cpu = ttk.Progressbar(sys_inner, length=200, mode="determinate")
        self._pb_cpu.grid(row=0, column=1, padx=(0, 4))
        self._lbl_cpu = ttk.Label(sys_inner, text="—", width=6)
        self._lbl_cpu.grid(row=0, column=2, padx=(0, PAD_LARGE))

        # GPU
        ttk.Label(sys_inner, text="GPU:").grid(row=0, column=3, sticky=tk.W, padx=(0, 4))
        self._pb_gpu = ttk.Progressbar(sys_inner, length=200, mode="determinate")
        self._pb_gpu.grid(row=0, column=4, padx=(0, 4))
        self._lbl_gpu = ttk.Label(sys_inner, text="N/V", width=6)
        self._lbl_gpu.grid(row=0, column=5, padx=(0, PAD_LARGE))

        # RAM
        ttk.Label(sys_inner, text="RAM:").grid(row=1, column=0, sticky=tk.W, padx=(0, 4), pady=(PAD_SMALL, 0))
        self._lbl_ram = ttk.Label(sys_inner, text="—")
        self._lbl_ram.grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=(0, PAD_LARGE), pady=(PAD_SMALL, 0))

        # VRAM
        ttk.Label(sys_inner, text="VRAM:").grid(row=1, column=3, sticky=tk.W, padx=(0, 4), pady=(PAD_SMALL, 0))
        self._lbl_vram = ttk.Label(sys_inner, text="N/V")
        self._lbl_vram.grid(row=1, column=4, columnspan=2, sticky=tk.W, padx=(0, PAD_LARGE), pady=(PAD_SMALL, 0))

        # ── Sektion 4: Abgeschlossene Runs ──
        done_frame = ttk.LabelFrame(self, text=" Abgeschlossene Runs ", style="TLabelframe")
        done_frame.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD_SMALL)

        done_cols = ("num", "module", "case", "turns", "avg_lat", "probes", "combat", "warnings", "alive", "score", "file")
        self._done_tree = ttk.Treeview(
            done_frame, columns=done_cols, show="headings", height=6,
        )
        for col, head, w, anc in [
            ("num", "#", 35, tk.CENTER),
            ("module", "Modul", 90, tk.W),
            ("case", "Case", 100, tk.W),
            ("turns", "Zuege", 50, tk.E),
            ("avg_lat", "Avg Lat.", 80, tk.E),
            ("probes", "Proben", 55, tk.E),
            ("combat", "Kampf", 55, tk.E),
            ("warnings", "Warn.", 50, tk.E),
            ("alive", "Lebt", 45, tk.CENTER),
            ("score", "Score", 55, tk.E),
            ("file", "Datei", 200, tk.W),
        ]:
            self._done_tree.heading(col, text=head)
            self._done_tree.column(col, width=w, anchor=anc)

        done_scroll = ttk.Scrollbar(done_frame, orient=tk.VERTICAL, command=self._done_tree.yview)
        self._done_tree.configure(yscrollcommand=done_scroll.set)
        self._done_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)
        done_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=PAD_SMALL)

        # Doppelklick -> Detail
        self._done_tree.bind("<Double-1>", self._on_done_double_click)

        # Buttons unter der Done-Tabelle
        done_btn_frame = ttk.Frame(self, style="TFrame")
        done_btn_frame.pack(fill=tk.X, padx=PAD, pady=(0, PAD_SMALL))
        ttk.Button(done_btn_frame, text="Ergebnis anzeigen", command=self._show_selected_result).pack(
            side=tk.LEFT, padx=(0, PAD),
        )
        ttk.Button(done_btn_frame, text="Alle loeschen", command=self._clear_completed).pack(
            side=tk.LEFT,
        )

        # Adventure-Liste initial laden
        self._on_module_changed()

        # Systemlast-Polling starten
        self._start_sysmon()

    # ── Adventure Discovery ──────────────────────────────────────────

    def _on_module_changed(self, _event: Any = None) -> None:
        """Aktualisiert die Adventure-Combobox nach Modul-Wechsel."""
        adventures = self._discover_adventures()
        self._cb_adventure.configure(values=[""] + adventures)
        self._var_adventure.set("")

    def _discover_adventures(self) -> list[str]:
        """Findet verfuegbare Adventures fuer das aktuelle Modul."""
        adv_dir = _PROJECT_ROOT / "modules" / "adventures"
        if not adv_dir.is_dir():
            return []
        adventures = []
        module = self._var_module.get()
        for f in sorted(adv_dir.iterdir()):
            if f.suffix == ".json":
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    # Nur Adventures die zum Modul passen oder generisch sind
                    ruleset = data.get("ruleset", "")
                    if not ruleset or ruleset == module:
                        adventures.append(f.stem)
                except (json.JSONDecodeError, OSError):
                    adventures.append(f.stem)
        return adventures

    # ── Queue / Batch Management ─────────────────────────────────────

    def _add_to_queue(self) -> None:
        """Fuegt einen Run zur Warteschlange hinzu."""
        module = self._var_module.get()
        case_str = self._var_case.get()
        case_id = int(case_str.split("-")[0])
        case_name = _CASES.get(case_id, "generic")
        adventure = self._var_adventure.get() or None
        turns = self._var_turns.get()

        config = RunConfig(
            module=module,
            case_id=case_id,
            case_name=case_name,
            adventure=adventure,
            turns=turns,
        )
        self._queue.append(config)
        self._update_counts()
        logger.info("Run hinzugefuegt: %s case=%d-%s turns=%d", module, case_id, case_name, turns)

    def _start_batch(self) -> None:
        """Startet die Warteschlange."""
        self._max_parallel = self._var_parallel.get()
        self._launch_queued_runs()

    def _stop_all(self) -> None:
        """Stoppt alle laufenden Runs und leert die Queue."""
        self._queue.clear()
        for key, run in list(self._active_runs.items()):
            if run.proc:
                try:
                    run.proc.terminate()
                except OSError:
                    pass
        self._update_counts()

    def _launch_queued_runs(self) -> None:
        """Startet queued Runs bis max_parallel erreicht."""
        while self._queue and len(self._active_runs) < self._max_parallel:
            config = self._queue.pop(0)
            self._launch_run(config)

    def _launch_run(self, config: RunConfig) -> None:
        """Startet einen einzelnen VirtualPlayer-Subprocess."""
        self._run_counter += 1
        ts = int(time.time() * 1000)
        progress_file = _PROGRESS_DIR / f"progress_{ts}_{self._run_counter}.json"

        cmd = [
            sys.executable, str(_PROJECT_ROOT / "scripts" / "virtual_player.py"),
            "-m", config.module,
            "--case", str(config.case_id),
            "-t", str(config.turns),
            "--save",
            "--progress-file", str(progress_file),
        ]
        if config.adventure:
            cmd.extend(["-a", config.adventure])

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(_PROJECT_ROOT),
            )
        except OSError as exc:
            logger.error("Subprocess-Start fehlgeschlagen: %s", exc)
            return

        run = ActiveRun(config=config, progress_file=progress_file, proc=proc)

        # In Treeview einfuegen
        tree_id = self._active_tree.insert("", tk.END, values=(
            self._run_counter,
            config.module,
            f"{config.case_id}-{config.case_name}",
            config.adventure or "—",
            "0/{}".format(config.turns),
            "start...",
            "—",
            proc.pid,
        ))
        run.tree_id = tree_id
        key = progress_file.name
        self._known_progress_files.add(key)
        self._active_runs[key] = run
        self._update_counts()
        logger.info("Run gestartet: PID=%d %s case=%d", proc.pid, config.module, config.case_id)

    # ── Polling ──────────────────────────────────────────────────────

    def _poll_progress(self) -> None:
        """Pollt Progress-Dir: erkennt neue Runs automatisch + aktualisiert bekannte."""
        # 1. Verzeichnis scannen — neue Progress-Files automatisch aufnehmen
        try:
            for pf in _PROGRESS_DIR.iterdir():
                if pf.suffix == ".json" and pf.name not in self._known_progress_files and pf.name not in self._finished_files:
                    self._adopt_external_run(pf)
        except OSError:
            pass

        # 2. Alle bekannten aktiven Runs aktualisieren
        finished_keys: list[str] = []

        for key, run in list(self._active_runs.items()):
            progress = self._read_progress(run.progress_file)
            proc_done = run.proc.poll() is not None if run.proc else False

            if progress:
                current = progress.get("current_turn", 0)
                total = progress.get("total_turns", run.config.turns)
                status = progress.get("status", "running")
                lat = progress.get("latest_latency_ms", 0)
                lat_str = f"{lat:.0f}ms" if lat > 0 else "—"
                pid = progress.get("pid", "—")

                # Config aus Progress aktualisieren (fuer externe Runs)
                if run.external:
                    run.config.module = progress.get("module", run.config.module)
                    run.config.case_id = progress.get("case_id", run.config.case_id)
                    run.config.case_name = progress.get("case_name", run.config.case_name)
                    run.config.adventure = progress.get("adventure", run.config.adventure)
                    run.config.turns = total

                # Treeview aktualisieren
                try:
                    self._active_tree.item(run.tree_id, values=(
                        self._active_tree.item(run.tree_id, "values")[0],  # #
                        run.config.module,
                        f"{run.config.case_id}-{run.config.case_name}",
                        run.config.adventure or "—",
                        f"{current}/{total}",
                        status,
                        lat_str,
                        pid,
                    ))
                except tk.TclError:
                    pass

                # Farbkodierung
                try:
                    if status == "completed":
                        self._active_tree.tag_configure("done", foreground=GREEN)
                        self._active_tree.item(run.tree_id, tags=("done",))
                    elif status == "error":
                        self._active_tree.tag_configure("err", foreground=RED)
                        self._active_tree.item(run.tree_id, tags=("err",))
                    else:
                        self._active_tree.tag_configure("run", foreground=YELLOW)
                        self._active_tree.item(run.tree_id, tags=("run",))
                except tk.TclError:
                    pass

                if status in ("completed", "error"):
                    finished_keys.append(key)
            elif proc_done:
                # Subprocess beendet, aber kein Progress -> trotzdem finishen
                finished_keys.append(key)

        # 3. Abgeschlossene Runs verarbeiten
        for key in finished_keys:
            self._finish_run(key)

        self._update_counts()

        # Immer weiter pollen
        self.after(1500, self._poll_progress)

    def _adopt_external_run(self, pf: Path) -> None:
        """Erkennt eine extern erstellte Progress-Datei und nimmt sie auf."""
        progress = self._read_progress(pf)
        if not progress:
            return

        key = pf.name
        self._known_progress_files.add(key)
        self._run_counter += 1

        config = RunConfig(
            module=progress.get("module", "?"),
            case_id=progress.get("case_id", 0),
            case_name=progress.get("case_name", "?"),
            adventure=progress.get("adventure"),
            turns=progress.get("total_turns", 0),
        )

        run = ActiveRun(config=config, progress_file=pf, proc=None, external=True)

        current = progress.get("current_turn", 0)
        total = progress.get("total_turns", 0)
        status = progress.get("status", "?")
        lat = progress.get("latest_latency_ms", 0)
        lat_str = f"{lat:.0f}ms" if lat > 0 else "—"
        pid = progress.get("pid", "—")

        tree_id = self._active_tree.insert("", tk.END, values=(
            self._run_counter,
            config.module,
            f"{config.case_id}-{config.case_name}",
            config.adventure or "—",
            f"{current}/{total}",
            status,
            lat_str,
            pid,
        ))
        run.tree_id = tree_id
        self._active_runs[key] = run

        logger.info("Externer Run erkannt: %s (%s case=%d)", pf.name, config.module, config.case_id)

    def _read_progress(self, path: Path) -> dict[str, Any] | None:
        """Liest eine Progress-Datei (None bei Fehler/nicht vorhanden)."""
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _finish_run(self, key: str) -> None:
        """Verschiebt einen Run von active zu completed."""
        run = self._active_runs.pop(key, None)
        if not run:
            return
        self._finished_files.add(key)

        # Auf Prozess-Ende warten (nur bei eigenen Subprocesses)
        if run.proc:
            try:
                run.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                run.proc.kill()

        # Ergebnis-Datei finden (neueste passende JSON)
        result_file = self._find_result_file(run.config)
        result_data: dict[str, Any] = {}
        score = 0

        if result_file:
            try:
                result_data = json.loads(result_file.read_text(encoding="utf-8"))
                score = _inline_score(result_data)
            except (json.JSONDecodeError, OSError):
                pass

        completed = CompletedRun(
            config=run.config,
            result_file=result_file,
            result_data=result_data,
            score=score,
            avg_latency=result_data.get("avg_latency_ms", 0.0),
            total_probes=result_data.get("total_probes", 0),
            total_combat=result_data.get("total_combat_tags", 0),
            total_warnings=result_data.get("total_rules_warnings", 0),
            character_alive=result_data.get("character_alive", True),
        )

        # In Done-Treeview einfuegen
        alive_str = "Ja" if completed.character_alive else "NEIN"
        file_str = result_file.name if result_file else "—"
        tree_id = self._done_tree.insert("", tk.END, values=(
            len(self._completed_runs) + 1,
            run.config.module,
            f"{run.config.case_id}-{run.config.case_name}",
            result_data.get("total_turns", run.config.turns),
            f"{completed.avg_latency:.0f}ms",
            completed.total_probes,
            completed.total_combat,
            completed.total_warnings,
            alive_str,
            f"{score}/100",
            file_str,
        ))
        completed.tree_id = tree_id

        # Score-Farbkodierung
        if score >= 60:
            self._done_tree.tag_configure("pass", foreground=GREEN)
            self._done_tree.item(tree_id, tags=("pass",))
        else:
            self._done_tree.tag_configure("fail", foreground=RED)
            self._done_tree.item(tree_id, tags=("fail",))

        self._completed_runs.append(completed)

        # Aktive-Tree aufräumen
        try:
            self._active_tree.delete(run.tree_id)
        except tk.TclError:
            pass

        # Progress-File aufraeumen
        try:
            run.progress_file.unlink(missing_ok=True)
        except OSError:
            pass

        # Naechsten queued Run starten
        self._launch_queued_runs()

    def _find_result_file(self, config: RunConfig) -> Path | None:
        """Findet die neueste Ergebnis-JSON fuer einen Run."""
        if not _RESULTS_DIR.is_dir():
            return None
        pattern = f"test_{config.module}_{config.case_name}_*.json"
        candidates = sorted(_RESULTS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0] if candidates else None

    # ── Kontextmenu / Aktionen ───────────────────────────────────────

    def _on_active_right_click(self, event: Any) -> None:
        """Rechtsklick auf aktive Runs -> Kontextmenu."""
        item = self._active_tree.identify_row(event.y)
        if item:
            self._active_tree.selection_set(item)
            self._active_menu.post(event.x_root, event.y_root)

    def _stop_selected_run(self) -> None:
        """Stoppt den ausgewaehlten aktiven Run."""
        sel = self._active_tree.selection()
        if not sel:
            return
        values = self._active_tree.item(sel[0], "values")
        if not values:
            return
        # Run ueber tree_id finden
        for key, run in self._active_runs.items():
            if run.tree_id == sel[0] and run.proc:
                try:
                    run.proc.terminate()
                except OSError:
                    pass
                break

    def _on_done_double_click(self, _event: Any = None) -> None:
        """Doppelklick auf abgeschlossenen Run -> Detail-Dialog."""
        self._show_selected_result()

    def _show_selected_result(self) -> None:
        """Zeigt den Detail-Dialog fuer den ausgewaehlten abgeschlossenen Run."""
        sel = self._done_tree.selection()
        if not sel:
            return
        values = self._done_tree.item(sel[0], "values")
        if not values:
            return
        try:
            idx = int(values[0]) - 1
        except (IndexError, ValueError):
            return
        if 0 <= idx < len(self._completed_runs):
            self._show_detail_dialog(self._completed_runs[idx])

    def _clear_completed(self) -> None:
        """Loescht alle abgeschlossenen Runs."""
        for item in self._done_tree.get_children():
            self._done_tree.delete(item)
        self._completed_runs.clear()
        self._update_counts()

    # ── Detail-Dialog ────────────────────────────────────────────────

    def _show_detail_dialog(self, completed: CompletedRun) -> None:
        """Oeffnet ein Toplevel mit Turn-by-Turn Report."""
        data = completed.result_data
        if not data:
            return

        dlg = tk.Toplevel(self)
        dlg.title(f"Test-Ergebnis: {completed.config.module} / {completed.config.case_id}-{completed.config.case_name}")
        dlg.configure(bg=BG_DARK)
        dlg.geometry("900x600")
        dlg.transient(self.winfo_toplevel())

        # Score-Header
        header = tk.Frame(dlg, bg=BG_DARK)
        header.pack(fill=tk.X, padx=PAD, pady=PAD)

        score_color = GREEN if completed.score >= 60 else RED
        verdict = "BESTANDEN" if completed.score >= 60 else "DURCHGEFALLEN"
        tk.Label(
            header, text=f"Score: {completed.score}/100 — {verdict}",
            bg=BG_DARK, fg=score_color, font=FONT_HEADER,
        ).pack(side=tk.LEFT)

        tk.Label(
            header,
            text=f"Modul: {completed.config.module}  |  Case: {completed.config.case_id}-{completed.config.case_name}  |  Avg Latenz: {completed.avg_latency:.0f}ms",
            bg=BG_DARK, fg=FG_SECONDARY, font=FONT_NORMAL,
        ).pack(side=tk.RIGHT)

        # Score-Breakdown
        breakdown_frame = ttk.LabelFrame(dlg, text=" Score-Breakdown ", style="TLabelframe")
        breakdown_frame.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        # Inline-Score-Breakdown berechnen
        turns = data.get("turns", [])
        expected_tags = data.get("expected_tags", {})
        total_warnings = data.get("total_rules_warnings", 0)
        character_alive = data.get("character_alive", True)
        avg_latency = data.get("avg_latency_ms", 0.0)

        breakdown_text = (
            f"Tags: ?/40  |  Monolog: ?/20  |  Cross-System: {'15' if total_warnings == 0 else '0-8'}/15  |  "
            f"Alive: {'10' if character_alive else '0'}/10  |  Latenz: {'5' if avg_latency < 10000 else '0-2'}/5"
        )
        ttk.Label(breakdown_frame, text=breakdown_text).pack(padx=PAD, pady=PAD_SMALL)

        # Turn-Treeview
        turn_frame = ttk.LabelFrame(dlg, text=" Turn-by-Turn ", style="TLabelframe")
        turn_frame.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD_SMALL)

        turn_cols = ("turn", "latency", "chars", "sentences", "tags", "error")
        turn_tree = ttk.Treeview(
            turn_frame, columns=turn_cols, show="headings", height=10,
        )
        for col, head, w in [
            ("turn", "Zug", 50), ("latency", "Latenz", 80),
            ("chars", "Zeichen", 70), ("sentences", "Saetze", 60),
            ("tags", "Tags", 250), ("error", "Fehler", 200),
        ]:
            turn_tree.heading(col, text=head)
            turn_tree.column(col, width=w)

        turn_scroll = ttk.Scrollbar(turn_frame, orient=tk.VERTICAL, command=turn_tree.yview)
        turn_tree.configure(yscrollcommand=turn_scroll.set)
        turn_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)
        turn_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=PAD_SMALL)

        for turn in turns:
            tags_str = ", ".join(turn.get("tags_found", [])) or "—"
            err = turn.get("error", "") or ""
            turn_tree.insert("", tk.END, values=(
                turn.get("turn", "?"),
                f"{turn.get('latency_ms', 0):.0f}ms",
                turn.get("response_chars", 0),
                turn.get("response_sentences", 0),
                tags_str,
                err,
            ))

        # Keeper-Response Text-Widget
        resp_frame = ttk.LabelFrame(dlg, text=" Keeper-Responses ", style="TLabelframe")
        resp_frame.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD_SMALL)

        resp_text = tk.Text(
            resp_frame, bg=BG_PANEL, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.NORMAL, height=8,
        )
        resp_scroll = ttk.Scrollbar(resp_frame, orient=tk.VERTICAL, command=resp_text.yview)
        resp_text.configure(yscrollcommand=resp_scroll.set)
        resp_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)
        resp_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=PAD_SMALL)

        for turn in turns:
            turn_num = turn.get("turn", "?")
            player = turn.get("player_input", "")
            keeper = turn.get("keeper_response", "")
            resp_text.insert(tk.END, f"--- Zug {turn_num} ---\n", "header")
            resp_text.insert(tk.END, f"Spieler: {player}\n", "player")
            resp_text.insert(tk.END, f"Keeper: {keeper}\n\n", "keeper")

        resp_text.tag_configure("header", foreground=FG_ACCENT, font=FONT_BOLD)
        resp_text.tag_configure("player", foreground=YELLOW)
        resp_text.tag_configure("keeper", foreground=FG_PRIMARY)
        resp_text.configure(state=tk.DISABLED)

        # Schliessen-Button
        ttk.Button(dlg, text="Schliessen", command=dlg.destroy).pack(pady=PAD)

        # Detail-Dialog: Turn-Auswahl -> Response anzeigen
        def _on_turn_select(_evt: Any = None) -> None:
            sel = turn_tree.selection()
            if not sel:
                return
            vals = turn_tree.item(sel[0], "values")
            try:
                turn_num = int(vals[0])
            except (IndexError, ValueError):
                return
            # Zum entsprechenden Abschnitt im Text scrollen
            search_str = f"--- Zug {turn_num} ---"
            idx = resp_text.search(search_str, "1.0", tk.END)
            if idx:
                resp_text.see(idx)

        turn_tree.bind("<<TreeviewSelect>>", _on_turn_select)

    # ── Systemlast-Monitoring ────────────────────────────────────────

    def _start_sysmon(self) -> None:
        """Startet den System-Monitor Background-Thread."""
        self._sysmon_active = True
        t = threading.Thread(target=self._sysmon_loop, daemon=True, name="TestMon-SysMon")
        t.start()

    def _sysmon_loop(self) -> None:
        """Pollt CPU/RAM/GPU/VRAM alle 2 Sekunden."""
        while self._sysmon_active:
            stats = self._read_sys_stats()
            try:
                self.after(0, self._update_sysmon_ui, stats)
            except RuntimeError:
                break
            time.sleep(2.0)

    def _read_sys_stats(self) -> dict[str, Any]:
        """Liest Systemauslastung."""
        stats: dict[str, Any] = {
            "cpu_percent": 0.0,
            "ram_used_gb": 0.0,
            "ram_total_gb": 0.0,
            "gpu_percent": None,
            "vram_used_gb": None,
            "vram_total_gb": None,
        }

        if _HAS_PSUTIL:
            stats["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            stats["ram_used_gb"] = mem.used / (1024 ** 3)
            stats["ram_total_gb"] = mem.total / (1024 ** 3)

        if _HAS_PYNVML:
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                stats["gpu_percent"] = util.gpu
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                stats["vram_used_gb"] = mem_info.used / (1024 ** 3)
                stats["vram_total_gb"] = mem_info.total / (1024 ** 3)
            except Exception:
                pass

        return stats

    def _update_sysmon_ui(self, stats: dict[str, Any]) -> None:
        """Aktualisiert die Systemlast-Anzeige (Main-Thread)."""
        # CPU
        cpu = stats["cpu_percent"]
        self._pb_cpu["value"] = cpu
        self._lbl_cpu.configure(text=f"{cpu:.0f}%")

        # RAM
        ram_used = stats["ram_used_gb"]
        ram_total = stats["ram_total_gb"]
        if ram_total > 0:
            self._lbl_ram.configure(text=f"{ram_used:.1f} / {ram_total:.1f} GB")
        else:
            self._lbl_ram.configure(text="—")

        # GPU
        gpu = stats.get("gpu_percent")
        if gpu is not None:
            self._pb_gpu["value"] = gpu
            self._lbl_gpu.configure(text=f"{gpu:.0f}%")
        else:
            self._lbl_gpu.configure(text="N/V")

        # VRAM
        vram_used = stats.get("vram_used_gb")
        vram_total = stats.get("vram_total_gb")
        if vram_used is not None and vram_total is not None:
            self._lbl_vram.configure(text=f"{vram_used:.1f} / {vram_total:.1f} GB")
        else:
            self._lbl_vram.configure(text="N/V")

    # ── Hilfsfunktionen ──────────────────────────────────────────────

    def _update_counts(self) -> None:
        """Aktualisiert die Zaehler-Anzeige."""
        q = len(self._queue)
        a = len(self._active_runs)
        mx = self._max_parallel
        d = len(self._completed_runs)
        self._lbl_counts.configure(text=f"Warteschlange: {q} | Aktiv: {a}/{mx} | Fertig: {d}")

    # ── Event-Interface (Tab-Pattern) ────────────────────────────────

    def on_engine_ready(self) -> None:
        """Wird aufgerufen wenn die Engine initialisiert ist."""
        self._on_module_changed()

    def handle_event(self, data: dict[str, Any]) -> None:
        """EventBus-Events (derzeit keine Verarbeitung noetig)."""
        pass
