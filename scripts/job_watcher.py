"""
scripts/job_watcher.py — ARS Remote Job Watcher (Server-Daemon)

Polling-Daemon der data/remote_jobs/pending/ ueberwacht, Jobs ausfuehrt
und Ergebnisse in done/ oder failed/ ablegt.

Verwendung:
    python scripts/job_watcher.py                    # Foreground, Ctrl+C stoppt
    python scripts/job_watcher.py --dropzone /pfad   # Anderer Pfad
    python scripts/job_watcher.py --interval 30      # Poll alle 30s
    python scripts/job_watcher.py --timeout 600      # Job-Timeout 10min
    python scripts/job_watcher.py --no-autofix       # Kein Auto-Fix bei Fehlern

Laeuft als systemd-Service via ars-job-watcher.service.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_DEFAULT_DROPZONE = _ROOT / "data" / "remote_jobs"
_DEFAULT_INTERVAL = 60       # Sekunden zwischen Polls
_DEFAULT_TIMEOUT = 1800      # 30 Minuten Job-Timeout
_HUNG_THRESHOLD = 3600       # 1 Stunde — dann gilt ein running-Job als haengend
_AUTOFIX_TIMEOUT = 120       # Sekunden fuer claude --print
_STDOUT_TAIL_LINES = 50      # Letzte N Zeilen im Job-JSON speichern
_STARTUP_ERROR_LINES = 50    # Erste N Zeilen auf Traceback pruefen

_LOG = logging.getLogger("job_watcher")

# ── Hilfsfunktionen ──────────────────────────────────────────────────

def _atomic_write_json(path: Path, data: dict) -> None:
    """Schreibt JSON atomar via temp-Datei + rename."""
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp", prefix="job_", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        Path(tmp_path).replace(path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_job(path: Path) -> dict | None:
    """Liest ein Job-JSON. Gibt None zurueck bei Fehler."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _LOG.warning("Kann Job nicht lesen: %s — %s", path.name, exc)
        return None


def _move_job(src: Path, dest_dir: Path) -> Path:
    """Verschiebt eine Job-Datei atomar (gleicher Mount)."""
    dest = dest_dir / src.name
    try:
        src.replace(dest)
    except OSError:
        # Fallback fuer Cross-Device (NAS-Shares)
        shutil.move(str(src), str(dest))
    return dest


def _tail(text: str, n: int) -> str:
    """Letzte N Zeilen eines Strings."""
    lines = text.splitlines()
    return "\n".join(lines[-n:]) if len(lines) > n else text


def _has_startup_traceback(output: str) -> str | None:
    """Prueft die ersten N Zeilen auf Python-Traceback.

    Gibt den Traceback zurueck oder None.
    """
    lines = output.splitlines()[:_STARTUP_ERROR_LINES]
    tb_start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Traceback (most recent call last)"):
            tb_start = i
            break
    if tb_start is None:
        return None
    # Traceback bis zur Error-Zeile extrahieren
    tb_lines = []
    for line in lines[tb_start:]:
        tb_lines.append(line)
        # Typische Error-Zeilen: ValueError:, ImportError:, etc.
        if line and not line.startswith(" ") and "Error" in line and tb_start != len(tb_lines) - 1 + tb_start:
            break
    return "\n".join(tb_lines) if tb_lines else None


# ── Executor-Dispatch ────────────────────────────────────────────────

def _build_testbot_cmd(params: dict) -> list[str]:
    """Baut den Befehl fuer einen testbot-Job."""
    cmd = [sys.executable, str(_ROOT / "scripts" / "testbot.py"), "run"]
    cmd.extend(["--type", str(params.get("type", "rules"))])
    if params.get("module"):
        cmd.extend(["--module", params["module"]])
    if params.get("runs"):
        cmd.extend(["--runs", str(params["runs"])])
    if params.get("turns"):
        cmd.extend(["--turns", str(params["turns"])])
    if params.get("adventure"):
        cmd.extend(["--adventure", params["adventure"]])
    if params.get("rules_mode"):
        cmd.extend(["--rules-mode", params["rules_mode"]])
    if params.get("seed") is not None:
        cmd.extend(["--seed", str(params["seed"])])
    if params.get("matrix_iterations"):
        cmd.extend(["--matrix-iterations", str(params["matrix_iterations"])])
    if params.get("group"):
        cmd.extend(["--group", params["group"]])
    if params.get("speech_style"):
        cmd.extend(["--speech-style", params["speech_style"]])
    if params.get("parallel"):
        cmd.extend(["--parallel", str(params["parallel"])])
    return cmd


def _build_rules_tester_cmd(params: dict) -> list[str]:
    """Baut den Befehl fuer einen rules_tester-Job."""
    cmd = [sys.executable, str(_ROOT / "scripts" / "rules_tester.py"), "run"]
    mode = params.get("rules_mode", "all")
    cmd.append(f"--{mode}")
    if params.get("seed") is not None:
        cmd.extend(["--seed", str(params["seed"])])
    if params.get("matrix_iterations"):
        cmd.extend(["--matrix-iterations", str(params["matrix_iterations"])])
    if params.get("group"):
        cmd.extend(["--group", params["group"]])
    return cmd


def _build_virtual_player_cmd(params: dict) -> list[str]:
    """Baut den Befehl fuer einen virtual_player-Job."""
    cmd = [sys.executable, str(_ROOT / "scripts" / "virtual_player.py")]
    cmd.extend(["--module", params.get("module", "add_2e")])
    if params.get("adventure"):
        cmd.extend(["--adventure", params["adventure"]])
    if params.get("turns"):
        cmd.extend(["--turns", str(params["turns"])])
    if params.get("case"):
        cmd.extend(["--case", str(params["case"])])
    if params.get("party"):
        cmd.extend(["--party", params["party"]])
    if params.get("save", True):
        cmd.append("--save")
    if params.get("turn_delay"):
        cmd.extend(["--turn-delay", str(params["turn_delay"])])
    return cmd


def _build_generic_cmd(params: dict) -> list[str]:
    """Baut den Befehl fuer ein generisches Script.

    Sicherheit: script_path muss innerhalb des ARS-Root liegen.
    """
    script_path = Path(params.get("script_path", ""))
    # Sicherheitscheck: Pfad muss innerhalb ARS-Root sein
    try:
        resolved = (_ROOT / script_path).resolve()
        resolved.relative_to(_ROOT.resolve())
    except (ValueError, OSError):
        raise ValueError(
            f"script_path '{script_path}' liegt ausserhalb des ARS-Root"
        )
    cmd = [sys.executable, str(resolved)]
    if params.get("args"):
        cmd.extend(params["args"])
    return cmd


EXECUTORS = {
    "testbot": _build_testbot_cmd,
    "rules_tester": _build_rules_tester_cmd,
    "virtual_player": _build_virtual_player_cmd,
    "script": _build_generic_cmd,
}


# ── JobWatcher ───────────────────────────────────────────────────────

class JobWatcher:
    """Polling-Daemon der pending/-Jobs ausfuehrt."""

    def __init__(
        self,
        dropzone: Path = _DEFAULT_DROPZONE,
        interval: int = _DEFAULT_INTERVAL,
        timeout: int = _DEFAULT_TIMEOUT,
        autofix: bool = True,
    ):
        self.dropzone = dropzone
        self.interval = interval
        self.timeout = timeout
        self.autofix = autofix
        self._running = True
        self._hostname = platform.node()

        # Verzeichnisse sicherstellen
        for sub in ("pending", "running", "done", "failed", "logs"):
            (self.dropzone / sub).mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        """Hauptschleife — laeuft bis SIGINT/SIGTERM."""
        _LOG.info(
            "JobWatcher gestartet — Dropzone: %s, Intervall: %ds, Timeout: %ds",
            self.dropzone, self.interval, self.timeout,
        )

        # Signal-Handler
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        while self._running:
            try:
                self._reap_hung_jobs()
                job_path = self._get_next_pending()
                if job_path:
                    self._process_job(job_path)
                else:
                    time.sleep(self.interval)
            except Exception:
                _LOG.exception("Fehler im Poll-Loop")
                time.sleep(self.interval)

        _LOG.info("JobWatcher beendet.")

    def _handle_signal(self, signum: int, frame: Any) -> None:
        _LOG.info("Signal %d empfangen, beende...", signum)
        self._running = False

    def _reap_hung_jobs(self) -> None:
        """Verschiebt Jobs in running/ die aelter als HUNG_THRESHOLD sind nach failed/."""
        running_dir = self.dropzone / "running"
        if not running_dir.is_dir():
            return

        now = time.time()
        for fp in running_dir.glob("*.json"):
            try:
                age = now - fp.stat().st_mtime
            except OSError:
                continue
            if age > _HUNG_THRESHOLD:
                _LOG.warning("Haengender Job erkannt: %s (Alter: %.0fs)", fp.name, age)
                job = _read_job(fp)
                if job:
                    job["status"] = "failed"
                    job["result"]["error"] = f"Job-Timeout nach {age:.0f}s (haengend)"
                    job["server"]["finished_at"] = datetime.now().isoformat(timespec="seconds")
                    _atomic_write_json(fp, job)
                _move_job(fp, self.dropzone / "failed")

    def _get_next_pending(self) -> Path | None:
        """Aelteste .json aus pending/ (FIFO nach Dateiname/Timestamp)."""
        pending_dir = self.dropzone / "pending"
        if not pending_dir.is_dir():
            return None
        jobs = sorted(pending_dir.glob("*.json"))
        return jobs[0] if jobs else None

    def _process_job(self, pending_path: Path) -> None:
        """Nimmt einen Job an und fuehrt ihn aus."""
        job = _read_job(pending_path)
        if not job:
            # Kaputte Datei nach failed/ verschieben
            _move_job(pending_path, self.dropzone / "failed")
            return

        job_id = job.get("job_id", "unknown")
        job_type = job.get("job_type", "unknown")
        _LOG.info("Job aufgenommen: %s (Typ: %s, von: %s)",
                  job_id, job_type, job.get("requester", "?"))

        # Status auf running setzen
        job["status"] = "running"
        job["server"]["hostname"] = self._hostname
        job["server"]["pid"] = os.getpid()
        job["server"]["started_at"] = datetime.now().isoformat(timespec="seconds")
        _atomic_write_json(pending_path, job)

        # Nach running/ verschieben
        running_path = _move_job(pending_path, self.dropzone / "running")

        # Ausfuehren
        success = self._execute(running_path, job)

        if success:
            job["status"] = "done"
            _atomic_write_json(running_path, job)
            _move_job(running_path, self.dropzone / "done")
            _LOG.info("Job %s: DONE (exit_code: %s)", job_id, job["server"]["exit_code"])
        else:
            # Auto-Fix versuchen?
            if (self.autofix
                    and not job["result"].get("autofix_attempted")
                    and self._should_autofix(job)):
                self._try_autofix(running_path, job)
            else:
                job["status"] = "failed"
                _atomic_write_json(running_path, job)
                _move_job(running_path, self.dropzone / "failed")
                _LOG.info("Job %s: FAILED (exit_code: %s)",
                          job_id, job["server"]["exit_code"])

    def _execute(self, job_path: Path, job: dict) -> bool:
        """Fuehrt den Job-Befehl aus. Gibt True bei Erfolg zurueck."""
        job_id = job["job_id"]
        job_type = job["job_type"]
        params = job.get("params", {})

        # Befehl bauen
        builder = EXECUTORS.get(job_type)
        if not builder:
            job["result"]["error"] = f"Unbekannter job_type: {job_type}"
            job["server"]["exit_code"] = -1
            return False

        try:
            cmd = builder(params)
        except (ValueError, KeyError) as exc:
            job["result"]["error"] = f"Fehler beim Befehlsaufbau: {exc}"
            job["server"]["exit_code"] = -1
            return False

        _LOG.info("Job %s: Fuehre aus: %s", job_id, " ".join(str(c) for c in cmd))

        # Log-Datei
        log_path = self.dropzone / "logs" / f"{job_id}.log"

        try:
            result = subprocess.run(
                cmd,
                cwd=str(_ROOT),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            exit_code = result.returncode
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            output = stdout + ("\n--- STDERR ---\n" + stderr if stderr else "")
        except subprocess.TimeoutExpired:
            job["result"]["error"] = f"Timeout nach {self.timeout}s"
            job["server"]["exit_code"] = -2
            job["server"]["finished_at"] = datetime.now().isoformat(timespec="seconds")
            return False
        except Exception as exc:
            job["result"]["error"] = f"Ausfuehrungsfehler: {exc}"
            job["server"]["exit_code"] = -3
            job["server"]["finished_at"] = datetime.now().isoformat(timespec="seconds")
            return False

        # Log schreiben
        try:
            log_path.write_text(output, encoding="utf-8")
        except OSError:
            pass

        # Job-Felder aktualisieren
        job["server"]["exit_code"] = exit_code
        job["server"]["finished_at"] = datetime.now().isoformat(timespec="seconds")
        job["result"]["stdout_tail"] = _tail(output, _STDOUT_TAIL_LINES)

        # Report-Pfad suchen (letztes .json in data/metrics/ oder data/test_series/)
        if exit_code == 0:
            for search_dir in ("data/test_series", "data/metrics"):
                search_path = _ROOT / search_dir
                if search_path.is_dir():
                    reports = sorted(
                        search_path.glob("*.json"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    if reports:
                        newest = reports[0]
                        # Nur wenn in den letzten 60s erstellt
                        if time.time() - newest.stat().st_mtime < 60:
                            job["result"]["report_path"] = str(
                                newest.relative_to(_ROOT)
                            )
                            break

        _atomic_write_json(job_path, job)
        return exit_code == 0

    def _should_autofix(self, job: dict) -> bool:
        """Prueft ob Auto-Fix versucht werden soll (Startup-Fehler)."""
        stdout_tail = job["result"].get("stdout_tail", "")
        return _has_startup_traceback(stdout_tail) is not None

    def _try_autofix(self, job_path: Path, job: dict) -> None:
        """Versucht einen automatischen Fix via claude --print."""
        job_id = job["job_id"]
        _LOG.info("Job %s: Versuche Auto-Fix...", job_id)

        job["result"]["autofix_attempted"] = True
        job["status"] = "autofix_running"
        _atomic_write_json(job_path, job)

        traceback = _has_startup_traceback(job["result"].get("stdout_tail", ""))
        if not traceback:
            job["result"]["autofix_result"] = "Kein Traceback gefunden"
            job["status"] = "failed"
            _atomic_write_json(job_path, job)
            _move_job(job_path, self.dropzone / "failed")
            return

        prompt = (
            f"ARS startup error beim Ausfuehren eines Remote-Jobs.\n"
            f"Job-Typ: {job['job_type']}\n\n"
            f"Traceback:\n{traceback}\n\n"
            f"Fix the error. Nur den Bug fixen, keine anderen Aenderungen."
        )

        try:
            fix_result = subprocess.run(
                ["claude", "--print", prompt],
                cwd=str(_ROOT),
                capture_output=True,
                text=True,
                timeout=_AUTOFIX_TIMEOUT,
            )
            job["result"]["autofix_result"] = _tail(
                fix_result.stdout or fix_result.stderr or "(keine Ausgabe)",
                30,
            )
            _LOG.info("Job %s: Auto-Fix Ergebnis (exit %d)",
                      job_id, fix_result.returncode)
        except subprocess.TimeoutExpired:
            job["result"]["autofix_result"] = f"claude Timeout nach {_AUTOFIX_TIMEOUT}s"
            job["status"] = "failed"
            _atomic_write_json(job_path, job)
            _move_job(job_path, self.dropzone / "failed")
            _LOG.warning("Job %s: Auto-Fix Timeout", job_id)
            return
        except FileNotFoundError:
            job["result"]["autofix_result"] = "claude CLI nicht gefunden"
            job["status"] = "failed"
            _atomic_write_json(job_path, job)
            _move_job(job_path, self.dropzone / "failed")
            _LOG.warning("Job %s: claude CLI nicht installiert", job_id)
            return

        # Retry: Job nochmal ausfuehren
        _LOG.info("Job %s: Retry nach Auto-Fix...", job_id)
        job["status"] = "running"
        job["server"]["started_at"] = datetime.now().isoformat(timespec="seconds")
        _atomic_write_json(job_path, job)

        success = self._execute(job_path, job)

        if success:
            job["status"] = "done"
            _atomic_write_json(job_path, job)
            _move_job(job_path, self.dropzone / "done")
            _LOG.info("Job %s: DONE nach Auto-Fix", job_id)
        else:
            job["status"] = "failed_permanent"
            _atomic_write_json(job_path, job)
            _move_job(job_path, self.dropzone / "failed")
            _LOG.info("Job %s: FAILED_PERMANENT (auch nach Auto-Fix)", job_id)


# ── CLI ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARS Remote Job Watcher — Server-Daemon",
    )
    parser.add_argument(
        "--dropzone", type=Path, default=_DEFAULT_DROPZONE,
        help=f"Pfad zu remote_jobs/ (Default: {_DEFAULT_DROPZONE})",
    )
    parser.add_argument(
        "--interval", type=int, default=_DEFAULT_INTERVAL,
        help=f"Poll-Intervall in Sekunden (Default: {_DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--timeout", type=int, default=_DEFAULT_TIMEOUT,
        help=f"Job-Timeout in Sekunden (Default: {_DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--no-autofix", action="store_true",
        help="Kein automatischer Fix bei Startup-Fehlern",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Debug-Logging",
    )
    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    watcher = JobWatcher(
        dropzone=args.dropzone,
        interval=args.interval,
        timeout=args.timeout,
        autofix=not args.no_autofix,
    )
    watcher.run()


if __name__ == "__main__":
    main()
