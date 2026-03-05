"""
scripts/test_series.py — Automatisierte Testreihe

Fuehrt N VirtualPlayer-Laeufe durch (parallel), sammelt alle Ergebnisse,
berechnet statistische Kennzahlen und erzeugt einen Gesamtreport.

Ziel: Fehler provozieren, Haeufigkeitsverteilung ermitteln, Fehlerstrategie entwickeln.

Verwendung:
  py -3 scripts/test_series.py --runs 100 --turns 5 --parallel 3
  py -3 scripts/test_series.py --runs 50 --module add_2e --case 3 --turns 8
  py -3 scripts/test_series.py --runs 20 --all-cases --turns 5
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_RESULTS_DIR = _ROOT / "data" / "test_results"
_SERIES_DIR = _ROOT / "data" / "test_series"
_PROGRESS_DIR = _ROOT / "data" / "test_progress"

logger = logging.getLogger("ARS.test_series")

# ── Scoring (inline, gleiche Logik wie test_evaluator.py) ────────────

import re

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


def _score_result(data: dict[str, Any]) -> dict[str, Any]:
    """Bewertet ein Testergebnis, gibt Score + Teilwerte zurueck."""
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
    monolog_violations = 0
    for turn in turns:
        resp = turn.get("keeper_response", "")
        if not resp:
            continue
        clean = re.sub(r"\[[^\]]+\]", "", resp).strip()
        n_sent = len(re.findall(r"[.!?]+(?:\s|$)", clean)) if clean else 0
        total_sentences += n_sent
        valid_turns += 1
        if n_sent > 4:
            monolog_violations += 1
    avg_sent = total_sentences / valid_turns if valid_turns else 0
    score_monolog = 20 if avg_sent <= 4 else (10 if avg_sent <= 6 else 0)

    # Cross-System (15)
    score_cross = 15 if total_warnings == 0 else (8 if total_warnings <= 2 else 0)

    # Alive (10)
    score_alive = 10 if character_alive else 0

    # Hook (10)
    hook_ok = hook_total = 0
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
    score_latency = 5 if avg_latency < 10_000 else (2 if avg_latency < 20_000 else 0)

    total = score_tags + score_monolog + score_cross + score_alive + score_hook + score_latency

    # Fehlertypen sammeln
    errors: list[str] = []
    if score_tags < 40:
        errors.append("TAGS_MISSING")
    if score_monolog < 20:
        errors.append("MONOLOG_VIOLATION")
    if score_cross < 15:
        errors.append("CROSS_SYSTEM")
    if score_alive < 10:
        errors.append("CHARACTER_DEAD")
    if score_hook < 10:
        errors.append("HOOK_MISSING")
    if score_latency < 5:
        errors.append("LATENCY_HIGH")
    for turn in turns:
        if turn.get("error"):
            errors.append(f"TURN_ERROR:{turn['error'][:50]}")

    return {
        "score": total,
        "passed": total >= 60,
        "score_tags": score_tags,
        "score_monolog": score_monolog,
        "score_cross": score_cross,
        "score_alive": score_alive,
        "score_hook": score_hook,
        "score_latency": score_latency,
        "avg_sentences": round(avg_sent, 1),
        "monolog_violations": monolog_violations,
        "hook_ok": hook_ok,
        "hook_total": hook_total,
        "errors": errors,
    }


# ── Einzelnen Run starten ────────────────────────────────────────────

def run_single_test(
    run_id: int,
    module: str,
    case_id: int,
    turns: int,
    adventure: str | None = None,
    speech_style: str = "normal",
) -> dict[str, Any] | None:
    """Startet einen virtual_player Subprocess und wartet auf Ergebnis."""
    progress_file = _PROGRESS_DIR / f"series_{run_id}_{int(time.time()*1000)}.json"

    cmd = [
        sys.executable, str(_ROOT / "scripts" / "virtual_player.py"),
        "-m", module,
        "--case", str(case_id),
        "-t", str(turns),
        "--save",
        "--progress-file", str(progress_file),
        "--turn-delay", "1.0",
        "--speech-style", speech_style,
    ]
    if adventure:
        cmd.extend(["-a", adventure])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=turns * 60 + 120,
            cwd=str(_ROOT),
        )
    except subprocess.TimeoutExpired:
        logger.error("Run %d: Timeout", run_id)
        return None
    except OSError as exc:
        logger.error("Run %d: Start fehlgeschlagen: %s", run_id, exc)
        return None
    finally:
        # Progress-File aufraeumen
        try:
            progress_file.unlink(missing_ok=True)
        except OSError:
            pass

    if result.returncode != 0:
        logger.warning("Run %d: Exit Code %d", run_id, result.returncode)
        # Trotzdem Result-File suchen (Crash nach save)

    return {"run_id": run_id, "exit_code": result.returncode}


def find_latest_result(module: str, case_name: str, after_ts: float) -> Path | None:
    """Findet die neueste Ergebnis-JSON nach Timestamp."""
    if not _RESULTS_DIR.is_dir():
        return None
    pattern = f"test_{module}_{case_name}_*.json"
    for p in sorted(_RESULTS_DIR.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.stat().st_mtime >= after_ts:
            return p
    return None


# ── Paralleler Batch-Runner ──────────────────────────────────────────

def run_series(
    total_runs: int,
    module: str,
    case_id: int,
    turns: int,
    max_parallel: int = 2,
    adventure: str | None = None,
    speech_style: str = "normal",
) -> list[dict[str, Any]]:
    """Fuehrt eine Testreihe durch und sammelt alle Ergebnisse."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Case-Name ermitteln
    case_names = {1: "generic", 2: "investigation", 3: "combat", 4: "social", 5: "dungeon_crawl", 6: "party_dungeon_crawl"}
    case_name = case_names.get(case_id, "generic")

    _PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    started = 0
    completed = 0

    print(f"\n{'='*70}")
    print(f"  TESTREIHE: {total_runs} Runs")
    print(f"  Modul: {module} | Case: {case_id}-{case_name} | Zuege: {turns}")
    print(f"  Stil: {speech_style} | Parallel: {max_parallel}")
    print(f"{'='*70}\n")

    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {}
        for i in range(1, total_runs + 1):
            ts_before = time.time()
            future = executor.submit(run_single_test, i, module, case_id, turns, adventure, speech_style)
            futures[future] = (i, ts_before, case_name)
            started += 1

        for future in as_completed(futures):
            run_id, ts_before, cn = futures[future]
            completed += 1

            try:
                run_info = future.result()
            except Exception as exc:
                logger.error("Run %d Exception: %s", run_id, exc)
                results.append({"run_id": run_id, "score": 0, "passed": False, "errors": ["EXCEPTION"]})
                print(f"  [{completed:3d}/{total_runs}] Run {run_id:3d}: EXCEPTION")
                continue

            # Ergebnis-JSON laden
            result_file = find_latest_result(module, cn, ts_before)
            if result_file:
                try:
                    data = json.loads(result_file.read_text(encoding="utf-8"))
                    scored = _score_result(data)
                    scored["run_id"] = run_id
                    scored["file"] = result_file.name
                    scored["avg_latency_ms"] = data.get("avg_latency_ms", 0)
                    scored["total_turns"] = data.get("total_turns", 0)
                    scored["total_probes"] = data.get("total_probes", 0)
                    scored["total_combat_tags"] = data.get("total_combat_tags", 0)
                    scored["total_rules_warnings"] = data.get("total_rules_warnings", 0)
                    scored["character_alive"] = data.get("character_alive", True)

                    # Token-Daten aus Einzel-JSON extrahieren (rueckwaertskompatibel)
                    tok = data.get("tokens", {})
                    scored["prompt_tokens"] = tok.get("prompt_tokens", 0)
                    scored["cached_tokens"] = tok.get("cached_tokens", 0)
                    scored["output_tokens"] = tok.get("output_tokens", 0)
                    scored["think_tokens"] = tok.get("think_tokens", 0)
                    scored["total_cost_usd"] = tok.get("total_cost_usd", 0.0)

                    results.append(scored)

                    status = "PASS" if scored["passed"] else "FAIL"
                    print(f"  [{completed:3d}/{total_runs}] Run {run_id:3d}: {scored['score']:3d}/100 {status}  "
                          f"lat={scored['avg_latency_ms']:.0f}ms  err={scored['errors']}")
                except (json.JSONDecodeError, OSError) as exc:
                    logger.error("Run %d: JSON-Fehler: %s", run_id, exc)
                    results.append({"run_id": run_id, "score": 0, "passed": False, "errors": ["JSON_ERROR"]})
                    print(f"  [{completed:3d}/{total_runs}] Run {run_id:3d}: JSON_ERROR")
            else:
                results.append({"run_id": run_id, "score": 0, "passed": False, "errors": ["NO_RESULT_FILE"]})
                print(f"  [{completed:3d}/{total_runs}] Run {run_id:3d}: NO_RESULT_FILE")

    return results


# ── Statistische Analyse ─────────────────────────────────────────────

def analyze_series(results: list[dict[str, Any]], module: str, case_id: int, turns: int, speech_style: str = "normal") -> str:
    """Erzeugt statistischen Report."""
    n = len(results)
    if n == 0:
        return "Keine Ergebnisse."

    scores = [r.get("score", 0) for r in results]
    passed = sum(1 for r in results if r.get("passed", False))
    failed = n - passed

    # Score-Verteilung
    avg_score = sum(scores) / n
    min_score = min(scores)
    max_score = max(scores)
    scores_sorted = sorted(scores)
    median_score = scores_sorted[n // 2] if n > 0 else 0

    # Latenz
    latencies = [r.get("avg_latency_ms", 0) for r in results if r.get("avg_latency_ms", 0) > 0]
    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    max_lat = max(latencies) if latencies else 0
    min_lat = min(latencies) if latencies else 0

    # Fehler-Verteilung
    all_errors: list[str] = []
    for r in results:
        all_errors.extend(r.get("errors", []))
    error_counts = Counter(all_errors)

    # Teilscore-Durchschnitte
    def _avg(key: str) -> float:
        vals = [r.get(key, 0) for r in results if key in r]
        return sum(vals) / len(vals) if vals else 0

    # Monolog-Stats
    monolog_viols = [r.get("monolog_violations", 0) for r in results if "monolog_violations" in r]
    avg_sentences = [r.get("avg_sentences", 0) for r in results if "avg_sentences" in r]

    # Hook-Stats
    hook_rates = []
    for r in results:
        ht = r.get("hook_total", 0)
        if ht > 0:
            hook_rates.append(r.get("hook_ok", 0) / ht * 100)

    lines: list[str] = []
    lines.append(f"\n{'='*70}")
    lines.append(f"  TESTREIHEN-REPORT")
    lines.append(f"  Modul: {module} | Case: {case_id} | Zuege/Run: {turns} | Stil: {speech_style} | Runs: {n}")
    lines.append(f"  Zeitpunkt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"{'='*70}")

    lines.append(f"\n  ERGEBNIS-UEBERSICHT")
    lines.append(f"  {'Bestanden:':<25} {passed}/{n} ({passed/n*100:.1f}%)")
    lines.append(f"  {'Durchgefallen:':<25} {failed}/{n} ({failed/n*100:.1f}%)")

    lines.append(f"\n  SCORE-VERTEILUNG")
    lines.append(f"  {'Durchschnitt:':<25} {avg_score:.1f}/100")
    lines.append(f"  {'Median:':<25} {median_score}/100")
    lines.append(f"  {'Min / Max:':<25} {min_score} / {max_score}")

    # Score-Histogramm (10er-Buckets)
    buckets = [0] * 10
    for s in scores:
        idx = min(s // 10, 9)
        buckets[idx] += 1
    lines.append(f"\n  Score-Histogramm:")
    for i in range(10):
        lo = i * 10
        hi = lo + 9
        bar = "#" * buckets[i]
        lines.append(f"    {lo:3d}-{hi:3d}: {bar} ({buckets[i]})")

    lines.append(f"\n  TEILSCORES (Durchschnitt)")
    lines.append(f"  {'Tags:':<25} {_avg('score_tags'):.1f}/40")
    lines.append(f"  {'Monolog:':<25} {_avg('score_monolog'):.1f}/20")
    lines.append(f"  {'Cross-System:':<25} {_avg('score_cross'):.1f}/15")
    lines.append(f"  {'Alive:':<25} {_avg('score_alive'):.1f}/10")
    lines.append(f"  {'Hook:':<25} {_avg('score_hook'):.1f}/10")
    lines.append(f"  {'Latenz:':<25} {_avg('score_latency'):.1f}/5")

    lines.append(f"\n  LATENZ")
    lines.append(f"  {'Durchschnitt:':<25} {avg_lat:.0f}ms")
    lines.append(f"  {'Min / Max:':<25} {min_lat:.0f}ms / {max_lat:.0f}ms")

    lines.append(f"\n  STIL-METRIKEN")
    if avg_sentences:
        lines.append(f"  {'Avg Saetze/Antwort:':<25} {sum(avg_sentences)/len(avg_sentences):.1f}")
    if monolog_viols:
        lines.append(f"  {'Monolog-Verstoesse/Run:':<25} {sum(monolog_viols)/len(monolog_viols):.1f}")
    if hook_rates:
        lines.append(f"  {'Hook-Rate:':<25} {sum(hook_rates)/len(hook_rates):.1f}%")

    lines.append(f"\n  FEHLER-VERTEILUNG ({len(all_errors)} gesamt)")
    if error_counts:
        for err_type, count in error_counts.most_common():
            pct = count / n * 100
            bar = "#" * min(int(pct / 2), 30)
            lines.append(f"    {err_type:<30} {count:4d} ({pct:5.1f}%) {bar}")
    else:
        lines.append(f"    Keine Fehler!")

    # Token/Kosten
    total_prompt = sum(r.get("prompt_tokens", 0) for r in results)
    total_cached = sum(r.get("cached_tokens", 0) for r in results)
    total_output = sum(r.get("output_tokens", 0) for r in results)
    total_think = sum(r.get("think_tokens", 0) for r in results)
    total_cost_usd = sum(r.get("total_cost_usd", 0.0) for r in results)
    total_cost_eur = total_cost_usd * 0.92

    lines.append(f"\n  TOKEN/KOSTEN")
    lines.append(f"  {'Prompt-Tokens:':<25} {total_prompt:,}")
    lines.append(f"  {'Cached-Tokens:':<25} {total_cached:,}")
    lines.append(f"  {'Output-Tokens:':<25} {total_output:,}")
    lines.append(f"  {'Think-Tokens:':<25} {total_think:,}")
    lines.append(f"  {'Gesamt-Kosten (USD):':<25} ${total_cost_usd:.4f}")
    lines.append(f"  {'Gesamt-Kosten (EUR):':<25} {total_cost_eur:.4f} EUR")
    if n > 0:
        lines.append(f"  {'Avg Kosten/Session:':<25} ${total_cost_usd/n:.4f} ({total_cost_eur/n:.4f} EUR)")

    # Tode
    deaths = sum(1 for r in results if not r.get("character_alive", True))
    lines.append(f"\n  SONSTIGES")
    lines.append(f"  {'Charakter-Tode:':<25} {deaths}/{n} ({deaths/n*100:.1f}%)")

    lines.append(f"\n{'='*70}\n")

    return "\n".join(lines)


def save_series_report(
    results: list[dict[str, Any]],
    report_text: str,
    module: str,
    case_id: int,
) -> Path:
    """Speichert Testreihen-Ergebnis als JSON + Text."""
    _SERIES_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"series_{module}_case{case_id}_{len(results)}runs_{ts}"

    # Token-Aggregate berechnen
    total_prompt = sum(r.get("prompt_tokens", 0) for r in results)
    total_cached = sum(r.get("cached_tokens", 0) for r in results)
    total_output = sum(r.get("output_tokens", 0) for r in results)
    total_think = sum(r.get("think_tokens", 0) for r in results)
    total_cost_usd = sum(r.get("total_cost_usd", 0.0) for r in results)
    n = len(results) or 1

    # JSON mit allen Einzelergebnissen
    json_path = _SERIES_DIR / f"{base}.json"
    json_data = {
        "module": module,
        "case_id": case_id,
        "total_runs": len(results),
        "timestamp": ts,
        "tokens_aggregate": {
            "prompt_tokens": total_prompt,
            "cached_tokens": total_cached,
            "output_tokens": total_output,
            "think_tokens": total_think,
            "total_cost_usd": round(total_cost_usd, 6),
            "total_cost_eur": round(total_cost_usd * 0.92, 6),
            "avg_cost_usd": round(total_cost_usd / n, 6),
        },
        "results": results,
    }
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Text-Report
    txt_path = _SERIES_DIR / f"{base}.txt"
    txt_path.write_text(report_text, encoding="utf-8")

    return json_path


# ── CLI ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARS Test Series — Automatisierte Testreihe mit statistischer Auswertung",
    )
    parser.add_argument("--runs", "-n", type=int, default=10, help="Anzahl Testlaeufe (Default: 10)")
    parser.add_argument("--module", "-m", default="add_2e", help="Regelsystem (Default: add_2e)")
    parser.add_argument("--case", "-c", type=int, default=1, choices=[1, 2, 3, 4, 5, 6], help="Test Case (Default: 1)")
    parser.add_argument("--turns", "-t", type=int, default=5, help="Zuege pro Run (Default: 5)")
    parser.add_argument("--parallel", "-p", type=int, default=2, help="Max parallele Runs (Default: 2)")
    parser.add_argument("--adventure", "-a", default=None, help="Adventure (optional)")
    parser.add_argument("--speech-style", "-s", default="normal",
                        choices=["normal", "sanft", "aggressiv"],
                        help="Keeper-Sprechstil (Default: normal)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    t0 = time.time()
    results = run_series(
        total_runs=args.runs,
        module=args.module,
        case_id=args.case,
        turns=args.turns,
        max_parallel=args.parallel,
        adventure=args.adventure,
        speech_style=args.speech_style,
    )
    elapsed = time.time() - t0

    report = analyze_series(results, args.module, args.case, args.turns, args.speech_style)
    print(report)
    print(f"  Gesamtdauer: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"  Durchschnitt pro Run: {elapsed/max(len(results),1):.1f}s\n")

    json_path = save_series_report(results, report, args.module, args.case)
    print(f"  Report gespeichert: {json_path}")
    print(f"  Text-Report: {json_path.with_suffix('.txt')}\n")


if __name__ == "__main__":
    main()
