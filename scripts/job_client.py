"""
scripts/job_client.py — ARS Remote Job Client

Client-Bibliothek zum Einreichen und Ueberwachen von Remote-Jobs.
Jobs werden als JSON-Dateien in data/remote_jobs/pending/ abgelegt
und vom job_watcher.py auf dem Server abgeholt.

Verwendung als Bibliothek:
    from scripts.job_client import submit_job, wait_for_job, list_jobs

    job = submit_job("testbot", {"type": "rules", "rules_mode": "unit"})
    result = wait_for_job(job["job_id"], timeout=600)
"""

from __future__ import annotations

import json
import os
import platform
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DROPZONE = _ROOT / "data" / "remote_jobs"

_SUBDIRS = ("pending", "running", "done", "failed")


def _ensure_dirs(dropzone: Path | None = None) -> Path:
    """Stellt sicher, dass alle Unterverzeichnisse existieren."""
    dz = dropzone or _DROPZONE
    for sub in (*_SUBDIRS, "logs"):
        (dz / sub).mkdir(parents=True, exist_ok=True)
    return dz


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


def _requester_name() -> str:
    """Erzeugt einen Requester-Namen aus Hostname."""
    return platform.node() or "unknown"


def submit_job(
    job_type: str,
    params: dict[str, Any],
    requester: str | None = None,
    dropzone: Path | None = None,
) -> dict:
    """Schreibt einen neuen Job nach pending/.

    Args:
        job_type: Einer von 'testbot', 'rules_tester', 'virtual_player', 'script'
        params: Job-spezifische Parameter
        requester: Absender-Name (Default: Hostname)
        dropzone: Pfad zu remote_jobs/ (Default: data/remote_jobs/)

    Returns:
        Das vollstaendige Job-Dict
    """
    dz = _ensure_dirs(dropzone)
    requester = requester or _requester_name()

    job_id = uuid.uuid4().hex[:8]
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")

    job = {
        "job_id": job_id,
        "job_type": job_type,
        "requester": requester,
        "created_at": now.isoformat(timespec="seconds"),
        "status": "pending",
        "params": params,
        "server": {
            "hostname": None,
            "pid": None,
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
        },
        "result": {
            "stdout_tail": "",
            "report_path": None,
            "error": None,
            "autofix_attempted": False,
            "autofix_result": None,
        },
    }

    filename = f"{ts}_{job_id}_{requester}.json"
    _atomic_write_json(dz / "pending" / filename, job)
    return job


def wait_for_job(
    job_id: str,
    poll_interval: float = 10.0,
    timeout: float = 3600.0,
    dropzone: Path | None = None,
) -> dict | None:
    """Pollt bis ein Job in done/ oder failed/ erscheint.

    Args:
        job_id: Die Job-ID
        poll_interval: Sekunden zwischen Polls
        timeout: Maximale Wartezeit in Sekunden

    Returns:
        Das Job-Dict oder None bei Timeout
    """
    dz = dropzone or _DROPZONE
    deadline = time.time() + timeout

    while time.time() < deadline:
        # In allen Verzeichnissen suchen
        for subdir in ("done", "failed", "running", "pending"):
            folder = dz / subdir
            if not folder.is_dir():
                continue
            for fp in folder.glob(f"*_{job_id}_*.json"):
                try:
                    data = json.loads(fp.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if data.get("job_id") == job_id:
                    if subdir in ("done", "failed"):
                        return data
                    # Noch in Bearbeitung — Status anzeigen und weiter warten
                    status = data.get("status", subdir)
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                          f"Job {job_id}: {status}")
                    break
            else:
                continue
            break

        time.sleep(poll_interval)

    print(f"  Timeout nach {timeout:.0f}s fuer Job {job_id}")
    return None


def list_jobs(
    max_age_hours: float = 24.0,
    dropzone: Path | None = None,
) -> list[dict]:
    """Listet alle Jobs aus allen Unterverzeichnissen.

    Args:
        max_age_hours: Maximales Alter in Stunden
        dropzone: Pfad zu remote_jobs/

    Returns:
        Liste von (status_dir, filename, job_dict) Tupeln
    """
    dz = dropzone or _DROPZONE
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    results: list[dict] = []

    for subdir in _SUBDIRS:
        folder = dz / subdir
        if not folder.is_dir():
            continue
        for fp in sorted(folder.glob("*.json")):
            try:
                mtime = datetime.fromtimestamp(fp.stat().st_mtime)
                if mtime < cutoff:
                    continue
                data = json.loads(fp.read_text(encoding="utf-8"))
                data["_dir"] = subdir
                data["_file"] = fp.name
                results.append(data)
            except (json.JSONDecodeError, OSError):
                continue

    return results
