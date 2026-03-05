"""
scripts/testbot.py — ARS Testbot CLI

Zentrale Steuerung fuer automatisierte Testreihen.

Subcommands:
  run       Startet einen Testbatch (wraps test_series.run_series)
  run -t rules  Deterministischer Regelwerk-Test (kein AI, kein Netzwerk)
  results   Uebersichtstabelle aller Serien oder Detail-Ansicht
  status    Zeigt laufende Tests (pollt progress-Files)
  cleanup   Loescht alte Ergebnisse

Verwendung:
  py -3 scripts/testbot.py run -t investigation -n 10
  py -3 scripts/testbot.py run -t 5 -n 5 -m add_2e --turns 8
  py -3 scripts/testbot.py run -t rules
  py -3 scripts/testbot.py run -t rules --rules-mode unit --seed 42
  py -3 scripts/testbot.py run -t rules --rules-mode matrix --matrix-iterations 500
  py -3 scripts/testbot.py results
  py -3 scripts/testbot.py results --job series_add_2e_case2_10runs_20260302.json
  py -3 scripts/testbot.py status
  py -3 scripts/testbot.py cleanup --older-than 7
  py -3 scripts/testbot.py cleanup --older-than 30 --dry-run

Remote-Jobs (Ausfuehrung auf Server via Shared Folder):
  py -3 scripts/testbot.py remote run -t rules --wait
  py -3 scripts/testbot.py remote run -t dungeon_crawl --runs 5 --turns 10
  py -3 scripts/testbot.py remote run -t virtual_player --adventure goblin_cave
  py -3 scripts/testbot.py remote status
  py -3 scripts/testbot.py remote list --hours 48
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_RESULTS_DIR = _ROOT / "data" / "test_results"
_SERIES_DIR = _ROOT / "data" / "test_series"
_PROGRESS_DIR = _ROOT / "data" / "test_progress"

USD_TO_EUR = 0.92

# Test-Case-Lookup (Name -> ID)
CASE_NAMES: dict[str, int] = {
    "generic": 1,
    "investigation": 2,
    "combat": 3,
    "social": 4,
    "dungeon_crawl": 5,
    "party_dungeon_crawl": 6,
    "rules": 7,
}
CASE_IDS: dict[int, str] = {v: k for k, v in CASE_NAMES.items()}

# Sonder-Case: rules_tester (kein AI, deterministisch)
_RULES_CASE_ID = 7


def _resolve_case(value: str) -> int:
    """Akzeptiert Case-Name oder Nummer, gibt Case-ID zurueck."""
    if value.isdigit():
        cid = int(value)
        if cid in CASE_IDS:
            return cid
        raise ValueError(f"Unbekannte Case-ID: {cid}. Gueltig: {list(CASE_IDS.keys())}")
    lower = value.lower().replace("-", "_")
    if lower in CASE_NAMES:
        return CASE_NAMES[lower]
    raise ValueError(f"Unbekannter Case-Name: {value}. Gueltig: {list(CASE_NAMES.keys())}")


def _dir_size(path: Path) -> int:
    """Berechnet Verzeichnisgroesse in Bytes."""
    if not path.is_dir():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _fmt_size(size_bytes: int) -> str:
    """Formatiert Bytes als menschenlesbare Groesse."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


# ── run ─────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> None:
    """Startet einen Testbatch via test_series oder rules_tester."""
    case_id = _resolve_case(args.type)

    # ── Sonderfall: deterministischer Regelwerk-Test ─────────────────
    if case_id == _RULES_CASE_ID:
        _cmd_run_rules(args)
        return

    # ── Standard: AI-basierte Testreihe ─────────────────────────────
    from scripts.test_series import run_series, analyze_series, save_series_report

    case_name = CASE_IDS[case_id]

    print(f"\n  Testbot: Starte Batch")
    print(f"  Case: {case_id}-{case_name} | Modul: {args.module} | Runs: {args.runs} | Turns: {args.turns}")
    print(f"  Parallel: {args.parallel} | Stil: {args.speech_style}\n")

    t0 = time.time()
    results = run_series(
        total_runs=args.runs,
        module=args.module,
        case_id=case_id,
        turns=args.turns,
        max_parallel=args.parallel,
        adventure=args.adventure,
        speech_style=args.speech_style,
    )
    elapsed = time.time() - t0

    report = analyze_series(results, args.module, case_id, args.turns, args.speech_style)
    print(report)
    print(f"  Gesamtdauer: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"  Durchschnitt pro Run: {elapsed/max(len(results),1):.1f}s\n")

    json_path = save_series_report(results, report, args.module, case_id)
    print(f"  Report gespeichert: {json_path}")
    print(f"  Text-Report: {json_path.with_suffix('.txt')}\n")


def _cmd_run_rules(args: argparse.Namespace) -> None:
    """Deterministischer Regelwerk-Test via rules_tester.py (kein AI)."""
    import subprocess

    rules_mode = getattr(args, "rules_mode", "all")
    seed = getattr(args, "seed", 42)
    matrix_iter = getattr(args, "matrix_iterations", 1000)
    group = getattr(args, "group", None)

    print(f"\n  Testbot: Regelwerk-Test (deterministisch, kein AI)")
    print(f"  Modus: {rules_mode} | Seed: {seed} | Matrix-Iter: {matrix_iter}")
    if group:
        print(f"  Gruppe: {group}")
    print()

    cmd = [
        sys.executable,
        str(_ROOT / "scripts" / "rules_tester.py"),
        "run",
        f"--{rules_mode}",
        "--seed", str(seed),
        "--matrix-iterations", str(matrix_iter),
    ]
    if group:
        cmd.extend(["--group", group])

    result = subprocess.run(cmd, cwd=str(_ROOT))

    # Status/Trends nach erfolgreichem Lauf anzeigen
    if result.returncode == 0:
        print(f"\n  {'='*60}")
        print(f"  Regelwerk-Test BESTANDEN")
        print(f"  {'='*60}")
        # Kurzstatus
        subprocess.run(
            [sys.executable, str(_ROOT / "scripts" / "rules_tester.py"),
             "status", "--last", "1"],
            cwd=str(_ROOT),
        )
    else:
        print(f"\n  {'='*60}")
        print(f"  Regelwerk-Test FEHLGESCHLAGEN (Exit-Code: {result.returncode})")
        print(f"  {'='*60}")

    sys.exit(result.returncode)


# ── results ─────────────────────────────────────────────────────────

def cmd_results(args: argparse.Namespace) -> None:
    """Zeigt Uebersicht aller Serien oder Detail einer einzelnen."""
    if args.job:
        _show_job_detail(args.job)
        return

    _show_results_overview()


def _show_results_overview() -> None:
    """Uebersichtstabelle aller Serien-Ergebnisse."""
    if not _SERIES_DIR.is_dir():
        print("  Keine Testreihen gefunden.")
        return

    files = sorted(_SERIES_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print("  Keine Testreihen gefunden.")
        return

    # Header
    print(f"\n  {'Datum':<20} {'Modul':<14} {'Case':<16} {'Runs':>5} {'Pass%':>6} "
          f"{'Score':>6} {'Kosten EUR':>11} {'Groesse':>9}")
    print(f"  {'-'*20} {'-'*14} {'-'*16} {'-'*5} {'-'*6} {'-'*6} {'-'*11} {'-'*9}")

    total_cost_eur = 0.0
    total_size = 0

    for fp in files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        module = data.get("module", "?")
        case_id = data.get("case_id", 0)
        case_name = CASE_IDS.get(case_id, "?")
        total_runs = data.get("total_runs", 0)
        ts = data.get("timestamp", "")

        # Datum formatieren
        try:
            dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            date_str = ts[:16] if ts else "?"

        # Scores
        results = data.get("results", [])
        passed = sum(1 for r in results if r.get("passed", False))
        pass_pct = (passed / total_runs * 100) if total_runs else 0
        scores = [r.get("score", 0) for r in results]
        avg_score = sum(scores) / len(scores) if scores else 0

        # Token-Kosten (rueckwaertskompatibel)
        tok_agg = data.get("tokens_aggregate", {})
        cost_usd = tok_agg.get("total_cost_usd", 0.0)
        if cost_usd == 0:
            # Fallback: aus Einzelergebnissen summieren
            cost_usd = sum(r.get("total_cost_usd", 0.0) for r in results)
        cost_eur = cost_usd * USD_TO_EUR
        total_cost_eur += cost_eur

        # Dateigroesse (JSON + TXT)
        file_size = fp.stat().st_size
        txt_path = fp.with_suffix(".txt")
        if txt_path.is_file():
            file_size += txt_path.stat().st_size
        total_size += file_size

        print(f"  {date_str:<20} {module:<14} {case_id}-{case_name:<13} {total_runs:5d} "
              f"{pass_pct:5.1f}% {avg_score:5.1f} {cost_eur:10.4f}  {_fmt_size(file_size):>9}")

    # Footer
    print(f"\n  Serien: {len(files)}")

    # Speicherplatz-Report
    size_results = _dir_size(_RESULTS_DIR)
    size_series = _dir_size(_SERIES_DIR)
    size_progress = _dir_size(_PROGRESS_DIR)
    size_total = size_results + size_series + size_progress

    print(f"\n  Speicherplatz:")
    print(f"    test_results/  {_fmt_size(size_results):>10}")
    print(f"    test_series/   {_fmt_size(size_series):>10}")
    print(f"    test_progress/ {_fmt_size(size_progress):>10}")
    print(f"    Gesamt:        {_fmt_size(size_total):>10}")
    if total_cost_eur > 0:
        print(f"\n  Gesamt-Kosten aller Serien: {total_cost_eur:.4f} EUR")
    print()


def _show_job_detail(job_ref: str) -> None:
    """Detail-Ansicht einer einzelnen Serie."""
    # Datei finden: exakter Pfad oder Name-Match
    job_path = Path(job_ref)
    if not job_path.is_file():
        job_path = _SERIES_DIR / job_ref
    if not job_path.is_file():
        # Partial match (nur JSON)
        candidates = [p for p in _SERIES_DIR.glob(f"*{job_ref}*.json")]
        if len(candidates) == 1:
            job_path = candidates[0]
        elif len(candidates) > 1:
            print(f"  Mehrdeutig ({len(candidates)} Treffer):")
            for c in candidates:
                print(f"    {c.name}")
            return
        else:
            print(f"  Datei nicht gefunden: {job_ref}")
            return

    try:
        data = json.loads(job_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  Fehler beim Lesen: {exc}")
        return

    module = data.get("module", "?")
    case_id = data.get("case_id", 0)
    case_name = CASE_IDS.get(case_id, "?")
    total_runs = data.get("total_runs", 0)
    ts = data.get("timestamp", "")
    results = data.get("results", [])

    print(f"\n  {'='*70}")
    print(f"  SERIEN-DETAIL: {job_path.name}")
    print(f"  Modul: {module} | Case: {case_id}-{case_name} | Runs: {total_runs} | Datum: {ts}")
    print(f"  {'='*70}")

    # Token-Aggregate
    tok = data.get("tokens_aggregate", {})
    if tok:
        cost_usd = tok.get("total_cost_usd", 0)
        cost_eur = tok.get("total_cost_eur", cost_usd * USD_TO_EUR)
        print(f"\n  TOKEN/KOSTEN (Aggregat)")
        print(f"  {'Prompt-Tokens:':<25} {tok.get('prompt_tokens', 0):,}")
        print(f"  {'Cached-Tokens:':<25} {tok.get('cached_tokens', 0):,}")
        print(f"  {'Output-Tokens:':<25} {tok.get('output_tokens', 0):,}")
        print(f"  {'Think-Tokens:':<25} {tok.get('think_tokens', 0):,}")
        print(f"  {'Kosten (USD):':<25} ${cost_usd:.4f}")
        print(f"  {'Kosten (EUR):':<25} {cost_eur:.4f} EUR")
        avg_cost = tok.get("avg_cost_usd", 0)
        if avg_cost:
            print(f"  {'Avg/Session (USD):':<25} ${avg_cost:.4f}")

    # Einzelergebnisse
    print(f"\n  {'Run':>4} {'Score':>6} {'Pass':>5} {'Lat ms':>8} {'Turns':>6} "
          f"{'Probes':>7} {'Cost $':>8} Fehler")
    print(f"  {'-'*4} {'-'*6} {'-'*5} {'-'*8} {'-'*6} {'-'*7} {'-'*8} {'-'*30}")

    for r in results:
        rid = r.get("run_id", "?")
        score = r.get("score", 0)
        passed = "PASS" if r.get("passed", False) else "FAIL"
        lat = r.get("avg_latency_ms", 0)
        turns = r.get("total_turns", 0)
        probes = r.get("total_probes", 0)
        cost = r.get("total_cost_usd", 0.0)
        errs = ", ".join(r.get("errors", [])) or "-"
        print(f"  {rid:4} {score:6d} {passed:>5} {lat:8.0f} {turns:6d} "
              f"{probes:7d} {cost:8.4f} {errs}")

    # Summary
    scores = [r.get("score", 0) for r in results]
    passed_n = sum(1 for r in results if r.get("passed", False))
    print(f"\n  Passed: {passed_n}/{len(results)}", end="")
    if scores:
        print(f" | Avg Score: {sum(scores)/len(scores):.1f}", end="")
    print(f"\n  Dateigroesse: {_fmt_size(job_path.stat().st_size)}")
    print(f"  {'='*70}\n")


# ── status ──────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
    """Zeigt laufende Tests anhand von Progress-Files."""
    if not _PROGRESS_DIR.is_dir():
        print("  Keine laufenden Tests (kein progress-Verzeichnis).")
        return

    progress_files = list(_PROGRESS_DIR.glob("*.json"))
    if not progress_files:
        print("  Keine laufenden Tests.")
        return

    active = []
    stale = []
    now = time.time()

    for fp in progress_files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        updated = data.get("updated_at", "")
        try:
            updated_dt = datetime.fromisoformat(updated)
            age_s = now - updated_dt.timestamp()
        except (ValueError, TypeError):
            age_s = 9999

        # Stale wenn aelter als 5 Minuten
        if age_s > 300:
            stale.append((fp, data, age_s))
        else:
            active.append((fp, data, age_s))

    if active:
        print(f"\n  LAUFENDE TESTS ({len(active)}):")
        print(f"  {'PID':>6} {'Modul':<14} {'Case':<16} {'Turn':>10} {'Status':<10} "
              f"{'Latenz':>8} {'Cost $':>8} {'Alter':>6}")
        print(f"  {'-'*6} {'-'*14} {'-'*16} {'-'*10} {'-'*10} {'-'*8} {'-'*8} {'-'*6}")

        for fp, data, age in active:
            pid = data.get("pid", "?")
            module = data.get("module", "?")
            case_id = data.get("case_id", 0)
            case_name = data.get("case_name", "?")
            current = data.get("current_turn", 0)
            total = data.get("total_turns", 0)
            status = data.get("status", "?")
            lat = data.get("avg_latency_ms", 0)
            cost = data.get("total_cost_usd", 0.0)
            print(f"  {pid:6} {module:<14} {case_id}-{case_name:<13} "
                  f"{current:4d}/{total:<4d} {status:<10} {lat:7.0f}ms {cost:8.4f} {age:5.0f}s")

    if stale:
        print(f"\n  VERWAISTE PROGRESS-FILES ({len(stale)}):")
        for fp, data, age in stale:
            print(f"    {fp.name} (Alter: {age:.0f}s)")

    if not active and not stale:
        print("  Keine laufenden Tests.")
    print()


# ── cleanup ─────────────────────────────────────────────────────────

def cmd_cleanup(args: argparse.Namespace) -> None:
    """Loescht alte Test-Ergebnisse."""
    cutoff = datetime.now() - timedelta(days=args.older_than)
    dry_run = args.dry_run

    dirs_to_clean = [_RESULTS_DIR]
    if not args.keep_series:
        dirs_to_clean.append(_SERIES_DIR)
    dirs_to_clean.append(_PROGRESS_DIR)

    total_files = 0
    total_bytes = 0

    print(f"\n  Cleanup: Dateien aelter als {args.older_than} Tage (vor {cutoff.strftime('%Y-%m-%d')})")
    if dry_run:
        print(f"  ** DRY RUN — keine Dateien werden geloescht **")
    if args.keep_series:
        print(f"  ** --keep-series: test_series/ wird uebersprungen **")
    print()

    for dir_path in dirs_to_clean:
        if not dir_path.is_dir():
            continue

        dir_files = 0
        dir_bytes = 0

        for fp in dir_path.iterdir():
            if not fp.is_file():
                continue
            try:
                mtime = datetime.fromtimestamp(fp.stat().st_mtime)
            except OSError:
                continue

            if mtime < cutoff:
                size = fp.stat().st_size
                dir_files += 1
                dir_bytes += size
                if not dry_run:
                    try:
                        fp.unlink()
                    except OSError as exc:
                        print(f"    Fehler: {fp.name}: {exc}")
                        continue

        if dir_files > 0:
            action = "Wuerde loeschen" if dry_run else "Geloescht"
            print(f"  {dir_path.name}/: {action} {dir_files} Dateien ({_fmt_size(dir_bytes)})")

        total_files += dir_files
        total_bytes += dir_bytes

    if total_files == 0:
        print(f"  Keine Dateien aelter als {args.older_than} Tage gefunden.")
    else:
        action = "Wuerde loeschen" if dry_run else "Geloescht"
        print(f"\n  Gesamt: {action} {total_files} Dateien ({_fmt_size(total_bytes)})")
    print()


# ── remote ─────────────────────────────────────────────────────────

def cmd_remote(args: argparse.Namespace) -> None:
    """Dispatch fuer remote-Subcommands."""
    sub = getattr(args, "remote_command", None)
    if sub == "run":
        _remote_run(args)
    elif sub == "status":
        _remote_status(args)
    elif sub == "list":
        _remote_list(args)
    else:
        print("  Unbekannter remote-Subcommand. Verwende: run, status, list")


def _remote_run(args: argparse.Namespace) -> None:
    """Reicht einen Job via job_client ein."""
    from scripts.job_client import submit_job, wait_for_job

    case_name = args.type
    # Job-Typ bestimmen
    if case_name == "virtual_player":
        job_type = "virtual_player"
        params = {
            "module": args.module,
            "adventure": args.adventure,
            "turns": args.turns,
            "save": True,
            "turn_delay": 2.0,
        }
    elif case_name == "rules":
        job_type = "testbot"
        params = {
            "type": "rules",
            "rules_mode": getattr(args, "rules_mode", "all"),
            "seed": getattr(args, "seed", 42),
            "matrix_iterations": getattr(args, "matrix_iterations", 1000),
            "group": getattr(args, "group", None),
        }
    else:
        job_type = "testbot"
        params = {
            "type": case_name,
            "module": args.module,
            "runs": args.runs,
            "turns": args.turns,
            "adventure": args.adventure,
        }

    job = submit_job(job_type, params)
    job_id = job["job_id"]
    print(f"\n  Remote-Job eingereicht: {job_id}")
    print(f"  Typ: {job_type} | Params: {json.dumps(params, ensure_ascii=False)}")

    if args.wait:
        print(f"  Warte auf Ergebnis (Timeout: {args.wait_timeout}s)...\n")
        result = wait_for_job(job_id, poll_interval=10, timeout=args.wait_timeout)
        if result:
            status = result.get("status", "?")
            exit_code = result.get("server", {}).get("exit_code", "?")
            print(f"\n  {'='*60}")
            print(f"  Job {job_id}: {status.upper()} (exit_code: {exit_code})")
            if result.get("result", {}).get("report_path"):
                print(f"  Report: {result['result']['report_path']}")
            if result.get("result", {}).get("error"):
                print(f"  Fehler: {result['result']['error']}")
            stdout_tail = result.get("result", {}).get("stdout_tail", "")
            if stdout_tail:
                print(f"\n  --- Letzte Ausgabe ---")
                for line in stdout_tail.splitlines()[-20:]:
                    print(f"  {line}")
            print(f"  {'='*60}")
        else:
            print(f"\n  Timeout — Job {job_id} laeuft moeglicherweise noch.")
            print(f"  Pruefe mit: py -3 scripts/testbot.py remote status")
    else:
        print(f"\n  Job laeuft im Hintergrund.")
        print(f"  Status pruefen: py -3 scripts/testbot.py remote status")
    print()


def _remote_status(args: argparse.Namespace) -> None:
    """Zeigt Status aller Remote-Jobs."""
    from scripts.job_client import list_jobs

    jobs = list_jobs(max_age_hours=getattr(args, "hours", 24))
    if not jobs:
        print("  Keine Remote-Jobs gefunden.")
        return

    print(f"\n  {'ID':<10} {'Typ':<16} {'Status':<18} {'Von':<14} "
          f"{'Erstellt':<20} {'Exit':>5}")
    print(f"  {'-'*10} {'-'*16} {'-'*18} {'-'*14} {'-'*20} {'-'*5}")

    for j in jobs:
        jid = j.get("job_id", "?")
        jtype = j.get("job_type", "?")
        status = j.get("status", j.get("_dir", "?"))
        req = j.get("requester", "?")
        created = j.get("created_at", "?")[:19]
        exit_code = j.get("server", {}).get("exit_code", "")
        exit_str = str(exit_code) if exit_code is not None else ""
        print(f"  {jid:<10} {jtype:<16} {status:<18} {req:<14} {created:<20} {exit_str:>5}")

    print(f"\n  Gesamt: {len(jobs)} Jobs\n")


def _remote_list(args: argparse.Namespace) -> None:
    """Listet Remote-Jobs mit mehr Detail."""
    from scripts.job_client import list_jobs

    hours = getattr(args, "hours", 24)
    jobs = list_jobs(max_age_hours=hours)
    if not jobs:
        print(f"  Keine Remote-Jobs in den letzten {hours}h gefunden.")
        return

    print(f"\n  Remote-Jobs (letzte {hours}h): {len(jobs)}\n")
    for j in jobs:
        jid = j.get("job_id", "?")
        status = j.get("status", j.get("_dir", "?"))
        jtype = j.get("job_type", "?")
        req = j.get("requester", "?")
        created = j.get("created_at", "?")
        server = j.get("server", {})
        result = j.get("result", {})

        print(f"  [{status.upper()}] {jid} — {jtype} (von {req}, {created})")
        if server.get("hostname"):
            print(f"    Server: {server['hostname']} (PID {server.get('pid', '?')})")
        if server.get("exit_code") is not None:
            print(f"    Exit: {server['exit_code']}")
        if result.get("report_path"):
            print(f"    Report: {result['report_path']}")
        if result.get("error"):
            print(f"    Fehler: {result['error']}")
        if result.get("autofix_attempted"):
            print(f"    Auto-Fix: {result.get('autofix_result', '?')}")
        print()


# ── CLI ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARS Testbot — Zentrale Steuerung fuer automatisierte Testreihen",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Testbatch starten")
    p_run.add_argument("--type", "-t", required=True,
                        help="Test Case: Name (investigation, dungeon_crawl, rules, ...) oder Nummer (1-7)")
    p_run.add_argument("--runs", "-n", type=int, default=10, help="Anzahl Runs (Default: 10)")
    p_run.add_argument("--module", "-m", default="add_2e", help="Regelsystem (Default: add_2e)")
    p_run.add_argument("--turns", type=int, default=5, help="Zuege pro Run (Default: 5)")
    p_run.add_argument("--parallel", "-p", type=int, default=2, help="Max parallele Runs (Default: 2)")
    p_run.add_argument("--adventure", "-a", default=None, help="Adventure (optional)")
    p_run.add_argument("--speech-style", "-s", default="normal",
                        choices=["normal", "sanft", "aggressiv"],
                        help="Keeper-Sprechstil (Default: normal)")
    # rules_tester-spezifische Optionen (nur fuer --type rules)
    p_run.add_argument("--rules-mode", default="all",
                        choices=["unit", "scenario", "matrix", "all"],
                        help="Rules-Tester Modus (Default: all)")
    p_run.add_argument("--seed", type=int, default=42, help="RNG-Seed fuer rules_tester (Default: 42)")
    p_run.add_argument("--matrix-iterations", type=int, default=1000,
                        help="Iterationen pro Matrix-Zelle (Default: 1000)")
    p_run.add_argument("--group", default=None,
                        help="Unit-Test Gruppe filtern (z.B. mechanics.attack_roll)")

    # results
    p_results = sub.add_parser("results", help="Ergebnis-Uebersicht")
    p_results.add_argument("--job", default=None,
                           help="Detail-Ansicht einer bestimmten Serie (Dateiname oder Teilmatch)")

    # status
    sub.add_parser("status", help="Laufende Tests anzeigen")

    # cleanup
    p_clean = sub.add_parser("cleanup", help="Alte Ergebnisse loeschen")
    p_clean.add_argument("--older-than", type=int, required=True,
                         help="Dateien aelter als N Tage loeschen")
    p_clean.add_argument("--dry-run", action="store_true",
                         help="Nur anzeigen, nicht loeschen")
    p_clean.add_argument("--keep-series", action="store_true",
                         help="test_series/ nicht anraeumen")

    # remote
    p_remote = sub.add_parser("remote", help="Remote-Jobs (Server-Ausfuehrung)")
    remote_sub = p_remote.add_subparsers(dest="remote_command", required=True)

    # remote run
    p_rr = remote_sub.add_parser("run", help="Remote-Job einreichen")
    p_rr.add_argument("--type", "-t", required=True,
                      help="Job-Typ: rules, investigation, dungeon_crawl, virtual_player, ...")
    p_rr.add_argument("--module", "-m", default="add_2e", help="Regelsystem")
    p_rr.add_argument("--runs", "-n", type=int, default=10, help="Anzahl Runs")
    p_rr.add_argument("--turns", type=int, default=5, help="Zuege pro Run")
    p_rr.add_argument("--adventure", "-a", default=None, help="Adventure")
    p_rr.add_argument("--wait", "-w", action="store_true",
                      help="Blockiert bis Job fertig")
    p_rr.add_argument("--wait-timeout", type=int, default=3600,
                      help="Max Wartezeit in Sekunden (Default: 3600)")
    p_rr.add_argument("--rules-mode", default="all",
                      choices=["unit", "scenario", "matrix", "all"])
    p_rr.add_argument("--seed", type=int, default=42)
    p_rr.add_argument("--matrix-iterations", type=int, default=1000)
    p_rr.add_argument("--group", default=None)

    # remote status
    p_rs = remote_sub.add_parser("status", help="Job-Status anzeigen")
    p_rs.add_argument("--hours", type=int, default=24,
                      help="Jobs der letzten N Stunden (Default: 24)")

    # remote list
    p_rl = remote_sub.add_parser("list", help="Jobs auflisten (Detail)")
    p_rl.add_argument("--hours", type=int, default=24,
                      help="Jobs der letzten N Stunden (Default: 24)")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "results":
        cmd_results(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)
    elif args.command == "remote":
        cmd_remote(args)


if __name__ == "__main__":
    main()
