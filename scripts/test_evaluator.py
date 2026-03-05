"""
scripts/test_evaluator.py — Offline-Bewertung von Virtual-Player-Testlaeufen

Liest JSON-Ergebnisse aus data/test_results/, bewertet nach Punktesystem,
gibt Report aus.

Punktesystem (100 Punkte):
  Erwartete Tags:           40  (Jeder expected_tag >= min_count)
  Monolog-Sperre:           20  (Durchschn. Saetze <= 4)
  Keine Cross-System Fehler: 15  (rules_warnings == 0)
  Charakter lebt:           10  (character_alive == True)
  Hook-Zwang:               10  (Antwort endet mit ? oder PROBE)
  Latenz akzeptabel:         5  (avg < 10000ms)

Bestanden: Score >= 60

Verwendung:
  py -3 scripts/test_evaluator.py data/test_results/test_add_2e_investigation_*.json
  py -3 scripts/test_evaluator.py --all
  py -3 scripts/test_evaluator.py --compare file1.json file2.json
  py -3 scripts/test_evaluator.py --all --report data/test_results/report.md
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_TEST_DIR = _ROOT / "data" / "test_results"

# ──────────────────────────────────────────────────────────────
# Tag-Zaehlung (gleiche Patterns wie virtual_player.py)
# ──────────────────────────────────────────────────────────────

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

# Hook-Erkennung: Antwort endet mit Fragezeichen oder PROBE-Tag
_HOOK_RE = re.compile(r"(\?\s*(\[[^\]]*\]\s*)*$|\[PROBE:[^\]]+\]\s*$)")


def _count_tag_in_text(text: str, tag_name: str) -> int:
    """Zaehlt Vorkommen eines Tags in einem Text."""
    pat = _TAG_PATTERNS.get(tag_name)
    if not pat:
        return 0
    return len(pat.findall(text))


def _count_sentences(text: str) -> int:
    """Zaehlt Saetze (Tags entfernt)."""
    clean = re.sub(r"\[[^\]]+\]", "", text).strip()
    if not clean:
        return 0
    return len(re.findall(r"[.!?]+(?:\s|$)", clean))


def _has_hook(text: str) -> bool:
    """Prueft ob eine Antwort mit Hook endet (Frage oder PROBE)."""
    stripped = text.rstrip()
    if not stripped:
        return False
    # Endet mit Fragezeichen (ggf. nach Tags)?
    # Entferne trailing Tags, pruefe auf ?
    without_trailing_tags = re.sub(r"(\s*\[[^\]]*\])+\s*$", "", stripped)
    if without_trailing_tags.rstrip().endswith("?"):
        return True
    # Endet mit PROBE-Tag?
    if re.search(r"\[PROBE:[^\]]+\]\s*$", stripped):
        return True
    return False


# ──────────────────────────────────────────────────────────────
# Bewertung
# ──────────────────────────────────────────────────────────────

class EvalResult:
    """Ergebnis der Bewertung einer Test-Datei."""

    def __init__(self, filepath: str, data: dict[str, Any]) -> None:
        self.filepath = filepath
        self.data = data
        self.module: str = data.get("module", "?")
        self.adventure: str = data.get("adventure") or "?"
        self.case_id: int = data.get("case_id", 1)
        self.case_name: str = data.get("case_name", "generic")
        self.expected_tags: dict[str, int] = data.get("expected_tags", {})
        self.turns: list[dict] = data.get("turns", [])
        self.character_alive: bool = data.get("character_alive", True)
        self.avg_latency_ms: float = data.get("avg_latency_ms", 0.0)
        self.total_rules_warnings: int = data.get("total_rules_warnings", 0)

        # Berechnete Werte
        self.score = 0
        self.score_tags = 0
        self.score_monolog = 0
        self.score_cross_system = 0
        self.score_alive = 0
        self.score_hook = 0
        self.score_latency = 0
        self.tag_checks: list[tuple[str, int, int, bool]] = []  # (name, min, actual, ok)
        self.monolog_avg = 0.0
        self.monolog_violations: list[tuple[int, int]] = []  # (turn, sentences)
        self.hook_ok = 0
        self.hook_total = 0
        self.hook_violations: list[int] = []  # turn numbers
        self.passed = False

    def evaluate(self) -> None:
        """Fuehrt die Bewertung durch."""
        self._eval_tags()
        self._eval_monolog()
        self._eval_cross_system()
        self._eval_alive()
        self._eval_hook()
        self._eval_latency()
        self.score = (
            self.score_tags + self.score_monolog + self.score_cross_system
            + self.score_alive + self.score_hook + self.score_latency
        )
        self.passed = self.score >= 60

    def _eval_tags(self) -> None:
        """Erwartete Tags pruefen (40 Punkte)."""
        if not self.expected_tags:
            # Kein Tag-Check fuer generic case — volle Punkte
            self.score_tags = 40
            return

        checks_passed = 0
        total_checks = len(self.expected_tags)

        for tag_name, min_count in self.expected_tags.items():
            # Zaehle Tag ueber alle Turns
            actual = 0
            # Fuer zusammengesetzte Tags (tag1|tag2)
            sub_tags = tag_name.split("|")
            for turn in self.turns:
                response = turn.get("keeper_response", "")
                for st in sub_tags:
                    actual += _count_tag_in_text(response, st)

            ok = actual >= min_count
            self.tag_checks.append((tag_name, min_count, actual, ok))
            if ok:
                checks_passed += 1

        if total_checks > 0:
            self.score_tags = round(40 * checks_passed / total_checks)
        else:
            self.score_tags = 40

    def _eval_monolog(self) -> None:
        """Monolog-Sperre pruefen (20 Punkte): Durchschn. Saetze <= 4."""
        if not self.turns:
            self.score_monolog = 20
            return

        total_sentences = 0
        valid_turns = 0
        for turn in self.turns:
            response = turn.get("keeper_response", "")
            if not response:
                continue
            n_sentences = _count_sentences(response)
            total_sentences += n_sentences
            valid_turns += 1
            if n_sentences > 4:
                self.monolog_violations.append((turn.get("turn", 0), n_sentences))

        self.monolog_avg = total_sentences / valid_turns if valid_turns > 0 else 0
        if self.monolog_avg <= 4:
            self.score_monolog = 20
        elif self.monolog_avg <= 6:
            self.score_monolog = 10
        else:
            self.score_monolog = 0

    def _eval_cross_system(self) -> None:
        """Cross-System Fehler pruefen (15 Punkte)."""
        if self.total_rules_warnings == 0:
            self.score_cross_system = 15
        elif self.total_rules_warnings <= 2:
            self.score_cross_system = 8
        else:
            self.score_cross_system = 0

    def _eval_alive(self) -> None:
        """Charakter lebt (10 Punkte)."""
        self.score_alive = 10 if self.character_alive else 0

    def _eval_hook(self) -> None:
        """Hook-Zwang pruefen (10 Punkte): Antwort endet mit ? oder PROBE."""
        if not self.turns:
            self.score_hook = 10
            return

        for turn in self.turns:
            response = turn.get("keeper_response", "")
            if not response:
                continue
            self.hook_total += 1
            if _has_hook(response):
                self.hook_ok += 1
            else:
                self.hook_violations.append(turn.get("turn", 0))

        if self.hook_total == 0:
            self.score_hook = 10
        else:
            ratio = self.hook_ok / self.hook_total
            self.score_hook = round(10 * ratio)

    def _eval_latency(self) -> None:
        """Latenz pruefen (5 Punkte): avg < 10000ms."""
        if self.avg_latency_ms < 10_000:
            self.score_latency = 5
        elif self.avg_latency_ms < 20_000:
            self.score_latency = 2
        else:
            self.score_latency = 0


# ──────────────────────────────────────────────────────────────
# Output-Formatierung
# ──────────────────────────────────────────────────────────────

def format_result(r: EvalResult) -> str:
    """Formatiert ein EvalResult als menschenlesbaren Report."""
    lines: list[str] = []
    verdict = "BESTANDEN" if r.passed else "DURCHGEFALLEN"

    lines.append("")
    lines.append("=== TEST-AUSWERTUNG ===")
    lines.append(f"Datei:  {Path(r.filepath).name}")
    lines.append(f"Case:   {r.case_id} -- {r.case_name}")
    lines.append(f"System: {r.module} / {r.adventure}")
    lines.append(f"Score:  {r.score}/100  {verdict}")
    lines.append("")

    # Tag-Checks
    if r.tag_checks:
        lines.append("Tag-Checks:")
        for tag_name, min_count, actual, ok in r.tag_checks:
            status = "OK" if ok else "FAIL"
            lines.append(f"  {tag_name:<20} >= {min_count}   ->  {actual}  {status}")
        lines.append("")

    # Stil
    lines.append("Stil:")
    monolog_note = ""
    if r.monolog_avg > 4:
        monolog_note = "(Verstoss)"
    elif r.monolog_avg > 3:
        monolog_note = "(knapp)"
    lines.append(f"  Monolog Avg {r.monolog_avg:.1f} Saetze    {monolog_note}")
    lines.append(f"  Hook-Zwang {r.hook_ok}/{r.hook_total} OK")
    lines.append(f"  Cross-System {r.total_rules_warnings} Warnings  {'OK' if r.total_rules_warnings == 0 else 'FAIL'}")
    lines.append(f"  Charakter lebt: {'Ja' if r.character_alive else 'NEIN'}")
    lines.append(f"  Latenz Avg {r.avg_latency_ms:.0f}ms  {'OK' if r.score_latency == 5 else 'LANGSAM'}")
    lines.append("")

    # Punkteaufschluesselung
    lines.append("Punkte:")
    lines.append(f"  Tags:         {r.score_tags:3d}/40")
    lines.append(f"  Monolog:      {r.score_monolog:3d}/20")
    lines.append(f"  Cross-System: {r.score_cross_system:3d}/15")
    lines.append(f"  Alive:        {r.score_alive:3d}/10")
    lines.append(f"  Hook:         {r.score_hook:3d}/10")
    lines.append(f"  Latenz:       {r.score_latency:3d}/5")
    lines.append(f"  GESAMT:       {r.score:3d}/100")
    lines.append("")

    # Befunde
    findings: list[str] = []
    for turn_num, n_sent in r.monolog_violations:
        findings.append(f"  - Turn {turn_num}: {n_sent} Saetze (Verstoss)")
    for turn_num in r.hook_violations:
        findings.append(f"  - Turn {turn_num}: Kein Hook am Ende")
    for tag_name, min_count, actual, ok in r.tag_checks:
        if not ok:
            findings.append(f"  - Tag {tag_name}: erwartet >= {min_count}, gefunden {actual}")

    if findings:
        lines.append("Befunde:")
        lines.extend(findings)
        lines.append("")

    return "\n".join(lines)


def format_comparison(r1: EvalResult, r2: EvalResult) -> str:
    """Formatiert einen Vergleich zweier Laeufe."""
    lines: list[str] = []
    lines.append("")
    lines.append("=== VERGLEICH ===")
    lines.append(f"{'':20} {'Lauf A':>12}  {'Lauf B':>12}  {'Delta':>8}")
    lines.append(f"{'-'*56}")

    def _row(label: str, a: Any, b: Any, fmt: str = "") -> str:
        if isinstance(a, float) and isinstance(b, float):
            delta = b - a
            sign = "+" if delta >= 0 else ""
            return f"  {label:<18} {a:>12{fmt}}  {b:>12{fmt}}  {sign}{delta:>7{fmt}}"
        return f"  {label:<18} {str(a):>12}  {str(b):>12}  {'':>8}"

    lines.append(_row("Datei", Path(r1.filepath).name, Path(r2.filepath).name))
    lines.append(_row("Score", r1.score, r2.score, ".0f"))
    lines.append(_row("Bestanden", "JA" if r1.passed else "NEIN", "JA" if r2.passed else "NEIN"))
    lines.append(f"{'-'*56}")
    lines.append(_row("Tags", r1.score_tags, r2.score_tags, ".0f"))
    lines.append(_row("Monolog", r1.score_monolog, r2.score_monolog, ".0f"))
    lines.append(_row("Cross-System", r1.score_cross_system, r2.score_cross_system, ".0f"))
    lines.append(_row("Alive", r1.score_alive, r2.score_alive, ".0f"))
    lines.append(_row("Hook", r1.score_hook, r2.score_hook, ".0f"))
    lines.append(_row("Latenz", r1.score_latency, r2.score_latency, ".0f"))
    lines.append(f"{'-'*56}")
    lines.append(_row("Latenz Avg ms", r1.avg_latency_ms, r2.avg_latency_ms, ".0f"))
    lines.append(_row("Monolog Avg Saetze", r1.monolog_avg, r2.monolog_avg, ".1f"))
    lines.append(_row("Warnings", float(r1.total_rules_warnings), float(r2.total_rules_warnings), ".0f"))
    lines.append("")

    return "\n".join(lines)


def format_markdown_report(results: list[EvalResult]) -> str:
    """Erzeugt einen Markdown-Report fuer alle Ergebnisse."""
    lines: list[str] = []
    lines.append("# ARS Test-Auswertung\n")

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    lines.append(f"**{passed}/{total} bestanden**\n")

    lines.append("| Datei | Case | System | Score | Ergebnis |")
    lines.append("|-------|------|--------|------:|----------|")
    for r in results:
        name = Path(r.filepath).name
        verdict = "PASS" if r.passed else "FAIL"
        lines.append(f"| {name} | {r.case_id}-{r.case_name} | {r.module} | {r.score}/100 | {verdict} |")

    lines.append("")

    # Detail pro Ergebnis
    for r in results:
        lines.append(f"## {Path(r.filepath).name}\n")
        lines.append(f"- **Case:** {r.case_id} -- {r.case_name}")
        lines.append(f"- **System:** {r.module} / {r.adventure}")
        lines.append(f"- **Score:** {r.score}/100 ({'BESTANDEN' if r.passed else 'DURCHGEFALLEN'})\n")

        lines.append("| Kriterium | Punkte | Max |")
        lines.append("|-----------|-------:|----:|")
        lines.append(f"| Tags | {r.score_tags} | 40 |")
        lines.append(f"| Monolog | {r.score_monolog} | 20 |")
        lines.append(f"| Cross-System | {r.score_cross_system} | 15 |")
        lines.append(f"| Alive | {r.score_alive} | 10 |")
        lines.append(f"| Hook | {r.score_hook} | 10 |")
        lines.append(f"| Latenz | {r.score_latency} | 5 |")
        lines.append("")

        if r.tag_checks:
            lines.append("**Tag-Checks:**\n")
            for tag_name, min_count, actual, ok in r.tag_checks:
                status = "OK" if ok else "FAIL"
                lines.append(f"- `{tag_name}` >= {min_count} \u2192 {actual} {status}")
            lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# Lade- und Auswertungslogik
# ──────────────────────────────────────────────────────────────

def load_and_evaluate(filepath: str) -> EvalResult:
    """Laedt eine JSON-Datei und bewertet sie."""
    with open(filepath, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    result = EvalResult(filepath, data)
    result.evaluate()
    return result


def find_test_files() -> list[str]:
    """Findet alle test_*.json Dateien in data/test_results/."""
    pattern = str(_TEST_DIR / "test_*.json")
    files = sorted(glob.glob(pattern))
    return files


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARS Test Evaluator — Offline-Bewertung von Testlaeufen",
    )
    parser.add_argument(
        "files", nargs="*", default=[],
        help="JSON-Dateien zum Auswerten (Glob-Patterns erlaubt)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Alle test_*.json in data/test_results/ auswerten",
    )
    parser.add_argument(
        "--compare", nargs=2, metavar=("FILE1", "FILE2"),
        help="Zwei Laeufe vergleichen",
    )
    parser.add_argument(
        "--report", default=None, metavar="PATH",
        help="Markdown-Report in Datei speichern",
    )

    args = parser.parse_args()

    # Dateien bestimmen
    files: list[str] = []

    if args.compare:
        # Vergleichsmodus
        r1 = load_and_evaluate(args.compare[0])
        r2 = load_and_evaluate(args.compare[1])
        print(format_result(r1))
        print(format_result(r2))
        print(format_comparison(r1, r2))
        return

    if args.all:
        files = find_test_files()
        if not files:
            print(f"Keine test_*.json Dateien in {_TEST_DIR} gefunden.")
            sys.exit(1)
    elif args.files:
        # Glob-Expansion fuer Windows
        for pattern in args.files:
            expanded = glob.glob(pattern)
            if expanded:
                files.extend(expanded)
            else:
                print(f"Warnung: Keine Datei fuer Pattern '{pattern}' gefunden.")
    else:
        parser.print_help()
        sys.exit(1)

    if not files:
        print("Keine Dateien zum Auswerten gefunden.")
        sys.exit(1)

    # Auswerten
    results: list[EvalResult] = []
    for f in files:
        try:
            r = load_and_evaluate(f)
            results.append(r)
            print(format_result(r))
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Fehler beim Laden von {f}: {e}")

    # Zusammenfassung
    if len(results) > 1:
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        avg_score = sum(r.score for r in results) / total
        print("=== ZUSAMMENFASSUNG ===")
        print(f"  {passed}/{total} bestanden, Avg Score: {avg_score:.0f}/100")
        print()

    # Markdown-Report
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        md = format_markdown_report(results)
        report_path.write_text(md, encoding="utf-8")
        print(f"Markdown-Report gespeichert: {report_path}")


if __name__ == "__main__":
    main()
