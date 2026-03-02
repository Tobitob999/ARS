#!/usr/bin/env python3
"""
ocr_cleanup_mechwarrior.py — OCR Artifact Cleanup for MechWarrior 3E Lore Files

Scans all JSON files in the mechwarrior_3e conversion bundle, identifies
name_guess fields with OCR artifacts, applies conservative auto-fixes, and
creates backups before modifying.

Usage:
    py -3 scripts/ocr_cleanup_mechwarrior.py --dry-run
    py -3 scripts/ocr_cleanup_mechwarrior.py --dry-run --report
    py -3 scripts/ocr_cleanup_mechwarrior.py
    py -3 scripts/ocr_cleanup_mechwarrior.py --report
    py -3 scripts/ocr_cleanup_mechwarrior.py --stats-only

OCR Artifact Patterns handled (cataloged from analysis):
  1. t0  -> to       (digit 0 for letter o)
  2. tne -> the      (n for h)
  3. a5  -> as       (digit 5 for letter s)
  4. 0f  -> of       (digit 0 for letter O)
  5. f   -> of       (isolated f as word — "multitude f non")
  6. Jrd -> 3rd      (J for 3)
  7. JrD -> 3rd
  8. iS  -> is       (capital S for lowercase s)
  9. Iet -> let      (capital I for lowercase l)
  10. Skllls / Skllls= -> Skills   (ll OCR for il)
  11. Tlme -> Time   (l for i)
  12. Attrlbute -> Attribute
  13. Mlnlmums -> Minimums
  14. Thls -> This
  15. Uso -> Use
  16. Tralt -> Trait
  17. Descrlption -> Description
  18. Hlgher -> Higher
  19. Slml -> Similar
  20. Whlte -> White
  21. Pllot -> Pilot
  22. Rolllng -> Rolling
  23. Creatlnn / Creatlon -> Creation
  24. Char$ -> Char's (dollar sign for apostrophe+s)
  25. Word- word -> Word-word (broken OCR hyphen rejoined)
  26. Trailing _ -> . or empty (period OCR as underscore)
  27. Jrd Edvt / JrD Edi -> 3rd Edition
  28. CHWARRIOR / MECHWARRIOR header fragments cleaned
  29. 0101 / 010l -> d10/D10
  30. thc -> the (c for e)
  31. ne -> he (missing h at word start)
  32. 0r -> or (digit 0 for letter O)
  33. 0n -> on
  34. lts -> its (lowercase l for I)
  35. Actlon -> Action
  36. Acrobatlcs -> Acrobatics
  37. Attlllatlon -> Affiliation

Conservative approach: only fix patterns with HIGH confidence.
Questionable patterns are logged but not changed.
"""

import argparse
import json
import os
import re
import shutil
import sys
import datetime
import glob
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MECHWARRIOR_LORE_DIR = (
    "G:/Meine Ablage/ARS/coversion/finished/mechwarrior_3e/data/lore/mechwarrior_3e"
)
BACKUP_SUFFIX = ".bak_ocr"
LOG_SEPARATOR = "-" * 72

# ---------------------------------------------------------------------------
# OCR fix rules — ordered from most-specific to most-general
# Each rule: (pattern_regex, replacement, description, confidence)
# confidence: HIGH | MEDIUM (MEDIUM rules are applied but flagged)
# ---------------------------------------------------------------------------

# Word-boundary substitutions (common OCR confusions)
_WORD_RULES: list[tuple[str, str, str, str]] = [
    # Whole-word substitutions (safe because bounded by \b)
    (r"\bt0\b",               "to",        "digit-0 for letter-o in 'to'",      "HIGH"),
    (r"\btne\b",              "the",       "n for h in 'the'",                   "HIGH"),
    (r"\bthc\b",              "the",       "c for e in 'the'",                   "HIGH"),
    (r"\ba5\b",               "as",        "digit-5 for s in 'as'",              "HIGH"),
    (r"\b0f\b",               "of",        "digit-0 for O in 'of'",              "HIGH"),
    (r"\b0r\b",               "or",        "digit-0 for o in 'or'",              "HIGH"),
    (r"\b0n\b",               "on",        "digit-0 for o in 'on'",              "HIGH"),
    (r"\bIet\b",              "let",       "capital-I for l in 'let'",           "HIGH"),
    (r"\biS\b",               "is",        "capital-S in 'is'",                  "HIGH"),
    (r"\blts\b",              "its",       "lowercase-l for I in 'its'",         "HIGH"),
    (r"\bJrd\b",              "3rd",       "J misread as 3",                     "HIGH"),
    (r"\bJrD\b",              "3rd",       "J misread as 3 (alt case)",          "HIGH"),
    # OCR for 'the' with missing h at word start
    (r"\bTne\b",              "The",       "Tne -> The (n for h)",               "HIGH"),
    # OCR broken edition label
    (r"\bEdvt\b",             "Edition",   "Edvt -> Edition",                    "HIGH"),
    (r"\bEditic[,.]?\b",      "Edition",   "Editic -> Edition",                  "HIGH"),
    (r"\bEDItIo[n;]?\b",      "Edition",   "EDItIo -> Edition",                  "HIGH"),
    (r"\bEDItIc[,.]?\b",      "Edition",   "EDItIc -> Edition",                  "HIGH"),
    (r"\bEdi\b",              "Edition",   "Edi -> Edition (header)",            "MEDIUM"),
    # Common OCR word garbling
    (r"\bThls\b",             "This",      "Thls -> This",                       "HIGH"),
    (r"\bThlS\b",             "This",      "ThlS -> This",                       "HIGH"),
    (r"\bUso\b",              "Use",       "Uso -> Use",                         "HIGH"),
    (r"\bTralt\b",            "Trait",     "Tralt -> Trait (l for i)",           "HIGH"),
    (r"\bTralts\b",           "Traits",    "Tralts -> Traits (l for i)",         "HIGH"),
    (r"\bTralning\b",         "Training",  "Tralning -> Training",               "HIGH"),
    (r"\bDescrlption\b",      "Description","Descrlption -> Description",        "HIGH"),
    (r"\bDescrlptions\b",     "Descriptions","Descrlptions -> Descriptions",     "HIGH"),
    (r"\bAttrlbute\b",        "Attribute", "Attrlbute -> Attribute (l for i)",   "HIGH"),
    (r"\bAttrlbutes\b",       "Attributes","Attrlbutes -> Attributes",           "HIGH"),
    (r"\bMlnlmum\b",          "Minimum",   "Mlnlmum -> Minimum",                 "HIGH"),
    (r"\bMlnlmums\b",         "Minimums",  "Mlnlmums -> Minimums",               "HIGH"),
    (r"\bMinlmums\b",         "Minimums",  "Minlmums -> Minimums",               "HIGH"),
    (r"\bMinlmum\b",          "Minimum",   "Minlmum -> Minimum",                 "HIGH"),
    (r"\bHlgher\b",           "Higher",    "Hlgher -> Higher",                   "HIGH"),
    (r"\bWhlte\b",            "White",     "Whlte -> White (l for i)",           "HIGH"),
    (r"\bPllot\b",            "Pilot",     "Pllot -> Pilot",                     "HIGH"),
    (r"\bPllots\b",           "Pilots",    "Pllots -> Pilots",                   "HIGH"),
    (r"\bRolllng\b",          "Rolling",   "Rolllng -> Rolling",                 "HIGH"),
    (r"\bCreatlon\b",         "Creation",  "Creatlon -> Creation",               "HIGH"),
    (r"\bCreatlnn\b",         "Creation",  "Creatlonn -> Creation",              "HIGH"),
    (r"\bActlon\b",           "Action",    "Actlon -> Action",                   "HIGH"),
    (r"\bActlons\b",          "Actions",   "Actlons -> Actions",                 "HIGH"),
    (r"\bActlng\b",           "Acting",    "Actlng -> Acting",                   "HIGH"),
    (r"\bAcrobatlcs\b",       "Acrobatics","Acrobatlcs -> Acrobatics",           "HIGH"),
    (r"\bAfflllatlons?\b",    "Affiliation","Affiliation OCR garble",            "HIGH"),
    (r"\bAtflllatlons?\b",    "Affiliation","Affiliation variant OCR",           "HIGH"),
    (r"\bSkllls\b",           "Skills",    "Skllls -> Skills (ll for il)",       "HIGH"),
    (r"\bSklll\b",            "Skill",     "Sklll -> Skill",                     "HIGH"),
    (r"\bSklIls\b",           "Skills",    "SklIls -> Skills (I for l)",         "HIGH"),
    (r"\bSkllls=\b",          "Skills:",   "Skllls= -> Skills: (= for :)",       "HIGH"),
    (r"\bTlme\b",             "Time",      "Tlme -> Time",                       "HIGH"),
    (r"\bSlml\b",             "Simil",     "Slml -> Simil",                      "HIGH"),
    (r"\bMechwarnor\b",       "MechWarrior","Mechwarnor -> MechWarrior",         "HIGH"),
    (r"\bMechWarnor\b",       "MechWarrior","MechWarnor -> MechWarrior",         "HIGH"),
    (r"\bMechwarrior\b",      "MechWarrior","Mechwarrior -> MechWarrior (caps)", "HIGH"),
    (r"\bLocatlon\b",         "Location",  "Locatlon -> Location",               "HIGH"),
    (r"\bLocatlons\b",        "Locations", "Locatlons -> Locations",             "HIGH"),
    (r"\blnitlatlve\b",       "Initiative","Initiative OCR garble",             "HIGH"),
    (r"\blnltlatlve\b",       "Initiative","Initiative variant OCR",            "HIGH"),
    (r"\bOvervlew\b",         "Overview",  "Overvlew -> Overview",               "HIGH"),
    (r"\bOccupatlonal\b",     "Occupational","Occupational OCR",                 "HIGH"),
    (r"\bResolutlon\b",       "Resolution","Resolutlon -> Resolution",           "HIGH"),
    (r"\bSltuation\b",        "Situation", "Sltuation -> Situation",             "HIGH"),
    (r"\bSituatlon\b",        "Situation", "Situatlon -> Situation",             "HIGH"),
    (r"\bSituatlons\b",       "Situations","Situatlons -> Situations",           "HIGH"),
    (r"\bVehlcle\b",          "Vehicle",   "Vehlcle -> Vehicle",                 "HIGH"),
    (r"\bVehlcles\b",         "Vehicles",  "Vehlcles -> Vehicles",               "HIGH"),
    (r"\bVehlcular\b",        "Vehicular", "Vehlcular -> Vehicular",             "HIGH"),
    (r"\bCombatl\b",          "Combat",    "Combatl -> Combat",                  "MEDIUM"),
    (r"\bFlelds\b",           "Fields",    "Flelds -> Fields",                   "HIGH"),
    (r"\bFleld\b",            "Field",     "Fleld -> Field",                     "HIGH"),
    # Trueborn/Freeborn OCR
    (r"\bFreeborn\b",         "Freeborn",  "already correct",                    "HIGH"),
    (r"\bTrueborn\b",         "Trueborn",  "already correct",                    "HIGH"),
    # OAME for GAME
    (r"\bOAME\b",             "GAME",      "OAME -> GAME (O for G)",             "HIGH"),
    # Evenis for Events
    (r"\bEvenis\b",           "Events",    "Evenis -> Events",                   "HIGH"),
    # Beginnlng / Finishlng
    (r"\bFinlshing\b",        "Finishing", "Finlshing -> Finishing",             "HIGH"),
    (r"\bFinlsh\b",           "Finish",    "Finlsh -> Finish",                   "HIGH"),
    (r"\bFlnlshing\b",        "Finishing", "Flnlshing -> Finishing",             "HIGH"),
    # Weapons/items
    (r"\bWeapans\b",          "Weapons",   "Weapans -> Weapons",                 "HIGH"),
    (r"\bWeapon\b",           "Weapon",    "already correct",                    "HIGH"),
    # Determinc -> Determine
    (r"\bDetermlne\b",        "Determine", "Determlne -> Determine",             "HIGH"),
    (r"\bDetermining\b",      "Determining","already correct",                   "HIGH"),
    # Hlnder/Hinder
    (r"\bHlnder\b",           "Hinder",    "Hlnder -> Hinder",                   "HIGH"),
    # Tact -> Fact (common OCR)
    # Too risky — 'tact' is a real word. Skip.
    # Charcter, Charac ter (split word)
    (r"\bCharac ter\b",       "Character", "space in 'character'",               "HIGH"),
    (r"\bCHARAGTER\b",        "CHARACTER", "CHARAGTER -> CHARACTER (G for C)",   "HIGH"),
    (r"\bCharagter\b",        "Character", "Charagter -> Character",             "HIGH"),
    # Wnee/Wheel
    (r"\bWnee\b",             "Wheel",     "Wnee -> Wheel",                      "MEDIUM"),
    # Flenter -> Fighter
    (r"\bFlenter\b",          "Fighter",   "Flenter -> Fighter",                 "MEDIUM"),
    # Aclons -> Actions
    (r"\bAclons\b",           "Actions",   "Aclons -> Actions",                  "HIGH"),
    # consisi -> consist
    (r"\bconsisi\b",          "consist",   "consisi -> consist",                 "HIGH"),
    # Of WAR -> OF WAR (uppercase consistency, header)
    # Already handled by whole-word replacements
    # Cchwarrior header truncations (safe to note, hard to auto-fix)
]

# Compound fixes applied with re.sub (not word-boundary, more structural)
_STRUCTURAL_RULES: list[tuple[str, str, str, str]] = [
    # Dollar sign replacing apostrophe+s in possessives: "character $ "  -> "character's "
    # Pattern: word <space> $ <space> -> word's <space>
    (r"(\w)\s+\$\s+(\w)",   r"\1's \2",  "dollar-sign apostrophe-s fix",        "HIGH"),
    # Dollar sign at end of word: "character$" -> "character's"
    (r"(\w)\$\s",           r"\1's ",    "dollar-sign possessive (no space)",    "HIGH"),
    # Trailing underscore (OCR period artifact): word_ -> word.
    # Matches trailing underscore (with optional trailing whitespace) at end of string.
    (r"_\s*$",               ".",         "trailing underscore -> period",        "MEDIUM"),
    # Broken hyphenated word: "sev- eral" -> "several"
    # Conservative: only rejoin if both parts are short (< 8 chars)
    # We handle this with a dedicated function
    # Jrd/JrD Edition header cleanup (full header fragment)
    (r"\b(MECHWARRIOR|CHWARRIOR|MECHWARRI0R)\s+(?:Jrd|JrD)\s+\w+\b",
     r"MECHWARRIOR 3rd Edition",
     "MECHWARRIOR 3rd Edition header",
     "HIGH"),
    # 0101 / D10 confusion in dice text
    (r"\b0[Ll]0[Ll]\b",     "D10",       "0101 -> D10 dice notation",           "HIGH"),
    # Skllls= (equals sign for colon)
    (r"\bSkllls=",           "Skills:",   "Skills= -> Skills:",                  "HIGH"),
    # NUMBERB for NUMBERS
    (r"\bNUMBERB\b",         "NUMBERS",   "NUMBERB -> NUMBERS",                  "HIGH"),
    # BUCKESSM -> SUCCESS (common OCR)
    (r"\bBUCCEBSMFAILURE\b", "SUCCESS/FAILURE", "OCR SUCCESS/FAILURE",         "HIGH"),
    # Tne Clans -> The Clans
    (r"\bTne\b",             "The",       "Tne -> The at start of phrase",       "HIGH"),
]


# ---------------------------------------------------------------------------
# Regex compilation
# ---------------------------------------------------------------------------

_COMPILED_WORD_RULES = [
    (re.compile(pat, re.IGNORECASE if conf == "MEDIUM" else 0), repl, desc, conf)
    for pat, repl, desc, conf in _WORD_RULES
]

_COMPILED_STRUCTURAL = [
    (re.compile(pat, re.MULTILINE), repl, desc, conf)
    for pat, repl, desc, conf in _STRUCTURAL_RULES
]

# Broken-word hyphen: "abili- ty" -> "ability"
# Rules:
#   - LEFT fragment must be all-lowercase and preceded by non-letter (not tail of proper noun)
#   - RIGHT fragment (the suffix) must be <= 6 chars — longer right sides are likely
#     standalone words, not line-break suffixes (e.g. "sim- animosi" -> skip)
# "Lyrans- particularly" -> excluded (left 'yrans' preceded by 'L')
# "sev- eral" -> included (left 'sev' starts after space, right 'eral' = 4 chars)
# "sim- animosi" -> excluded (right 'animosi' = 7 chars)
_BROKEN_HYPHEN_RE = re.compile(r"(?<![A-Za-z])([a-z]{2,7})- ([a-z]{2,6})\b")


# ---------------------------------------------------------------------------
# Core fixing logic
# ---------------------------------------------------------------------------

def _rejoin_broken_hyphens(text: str) -> tuple[str, list[str]]:
    """Rejoin OCR-split hyphenated words like 'sev- eral' -> 'several'."""
    changes = []

    def replacer(m: re.Match) -> str:
        left = m.group(1)
        right = m.group(2)
        joined = left + right
        # Only accept if result looks like a real English word (simple heuristic:
        # no consecutive consonants that don't appear in English).
        # Conservative: minimum joined length check, no double-consonant triplets.
        if len(joined) >= 4:
            changes.append(f"broken-hyphen: '{left}- {right}' -> '{joined}'")
            return joined
        return m.group(0)

    result = _BROKEN_HYPHEN_RE.sub(replacer, text)
    return result, changes


def _apply_word_rules(text: str) -> tuple[str, list[str]]:
    """Apply word-boundary substitution rules."""
    changes = []
    for pattern, repl, desc, conf in _COMPILED_WORD_RULES:
        new_text = pattern.sub(repl, text)
        if new_text != text:
            changes.append(f"[{conf}] {desc}: '{text[:60]}' -> '{new_text[:60]}'")
            text = new_text
    return text, changes


def _apply_structural_rules(text: str) -> tuple[str, list[str]]:
    """Apply structural/compound substitution rules."""
    changes = []
    for pattern, repl, desc, conf in _COMPILED_STRUCTURAL:
        new_text = pattern.sub(repl, text)
        if new_text != text:
            changes.append(f"[{conf}] {desc}: '{text[:60]}' -> '{new_text[:60]}'")
            text = new_text
    return text, changes


def fix_name_guess(original: str) -> tuple[str, list[str]]:
    """
    Apply all OCR fixes to a name_guess value.
    Returns (fixed_text, list_of_change_descriptions).
    Conservative: if no rules fire, original is returned unchanged.
    """
    if not original or not isinstance(original, str):
        return original, []

    text = original
    all_changes: list[str] = []

    # 1. Structural rules first (broader patterns)
    text, ch = _apply_structural_rules(text)
    all_changes.extend(ch)

    # 2. Word-boundary rules
    text, ch = _apply_word_rules(text)
    all_changes.extend(ch)

    # 3. Broken hyphen rejoining
    text, ch = _rejoin_broken_hyphens(text)
    all_changes.extend(ch)

    # Strip leading/trailing whitespace introduced by any substitution
    text = text.strip()

    return text, all_changes


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------

def process_file(
    filepath: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Process a single JSON file.
    Returns a result dict with keys:
      file, had_name_guess, original, fixed, changes, error
    """
    result: dict[str, Any] = {
        "file": filepath,
        "had_name_guess": False,
        "original": None,
        "fixed": None,
        "changes": [],
        "changed": False,
        "error": None,
    }

    try:
        with open(filepath, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        result["error"] = f"JSON parse error: {exc}"
        return result

    mechanics = data.get("mechanics", {})
    if not isinstance(mechanics, dict):
        return result

    name_guess = mechanics.get("name_guess")
    if name_guess is None:
        return result

    result["had_name_guess"] = True
    result["original"] = name_guess

    fixed, changes = fix_name_guess(name_guess)
    result["fixed"] = fixed
    result["changes"] = changes
    result["changed"] = fixed != name_guess

    if result["changed"] and not dry_run:
        # Create backup
        backup_path = filepath + BACKUP_SUFFIX
        if not os.path.exists(backup_path):
            shutil.copy2(filepath, backup_path)

        # Update in-place
        data["mechanics"]["name_guess"] = fixed
        # Also update summary if it matches the original name_guess exactly
        if data.get("summary") == name_guess:
            data["summary"] = fixed

        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    return result


def scan_directory(
    base_dir: str,
    dry_run: bool = True,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Scan all JSON files in base_dir recursively."""
    all_files = glob.glob(os.path.join(base_dir, "**", "*.json"), recursive=True)
    all_files = sorted(all_files)

    results = []
    total = len(all_files)

    for idx, filepath in enumerate(all_files, 1):
        if verbose and idx % 500 == 0:
            print(f"  [{idx}/{total}] scanning...", flush=True)

        res = process_file(filepath, dry_run=dry_run)
        results.append(res)

        if res["changed"] and verbose:
            print(f"  CHANGED: {os.path.basename(filepath)}")
            for ch in res["changes"]:
                print(f"    {ch}")

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def build_report(results: list[dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    """Build a structured report from scan results."""
    total_files = len(results)
    with_name_guess = [r for r in results if r["had_name_guess"]]
    errors = [r for r in results if r["error"]]
    changed = [r for r in results if r["changed"]]
    unchanged = [r for r in with_name_guess if not r["changed"] and not r["error"]]

    # Artifact rate before
    before_rate = len(with_name_guess) - 0  # all had potential issues

    # Collect all change types
    change_type_counts: dict[str, int] = {}
    for r in changed:
        for ch in r["changes"]:
            # Extract rule description
            key = ch.split(":")[0].strip() if ":" in ch else ch[:40]
            change_type_counts[key] = change_type_counts.get(key, 0) + 1

    report = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "mode": "DRY_RUN" if dry_run else "APPLIED",
        "base_dir": MECHWARRIOR_LORE_DIR,
        "summary": {
            "total_files_scanned": total_files,
            "files_with_name_guess": len(with_name_guess),
            "files_changed": len(changed),
            "files_unchanged": len(unchanged),
            "files_with_errors": len(errors),
            "artifact_rate_before_pct": round(
                len(with_name_guess) / max(total_files, 1) * 100, 1
            ),
            "fix_rate_pct": round(
                len(changed) / max(len(with_name_guess), 1) * 100, 1
            ),
        },
        "change_type_counts": dict(
            sorted(change_type_counts.items(), key=lambda x: -x[1])
        ),
        "changed_files": [
            {
                "file": os.path.basename(r["file"]),
                "original": r["original"],
                "fixed": r["fixed"],
                "changes": r["changes"],
            }
            for r in changed
        ],
        "errors": [
            {"file": r["file"], "error": r["error"]}
            for r in errors
        ],
        "manual_review_needed": [
            {
                "file": os.path.basename(r["file"]),
                "name_guess": r["original"],
                "reason": "no auto-fix applied",
            }
            for r in unchanged
            if _needs_manual_review(r["original"])
        ],
    }
    return report


def _needs_manual_review(name: str) -> bool:
    """Heuristic: flag names that still look garbled after auto-fix."""
    if not name:
        return False
    # Long phrase (> 7 words) still present
    if len(name.split()) > 7:
        return False  # These are all long — don't spam the manual-review list
    # Contains digit mixed into alphabetic word
    if re.search(r"[a-zA-Z][0-9]|[0-9][a-zA-Z]", name):
        return True
    # Contains semicolons in unusual positions
    if name.count(";") > 2:
        return True
    # Still has uppercase-only long sequences not typical for titles
    return False


def print_summary(report: dict[str, Any]) -> None:
    """Print human-readable summary to stdout."""
    s = report["summary"]
    print()
    print(LOG_SEPARATOR)
    print("OCR CLEANUP REPORT — MechWarrior 3E")
    print(LOG_SEPARATOR)
    print(f"Mode:                  {report['mode']}")
    print(f"Generated:             {report['generated_at']}")
    print(f"Base dir:              {report['base_dir']}")
    print()
    print(f"Total files scanned:   {s['total_files_scanned']}")
    print(f"With name_guess:       {s['files_with_name_guess']}")
    print(f"Files CHANGED:         {s['files_changed']}  ({s['fix_rate_pct']}% fix rate)")
    print(f"Files unchanged:       {s['files_unchanged']}")
    print(f"Parse errors:          {s['files_with_errors']}")
    print()
    print("Top change types applied:")
    for k, v in list(report["change_type_counts"].items())[:20]:
        print(f"  {v:5d}x  {k}")

    manual = report.get("manual_review_needed", [])
    if manual:
        print()
        print(f"Manual review needed: {len(manual)} names")
        for item in manual[:10]:
            print(f"  {item['file']}: {repr(item['name_guess'][:70])}")
        if len(manual) > 10:
            print(f"  ... and {len(manual) - 10} more (see JSON report)")

    errors = report.get("errors", [])
    if errors:
        print()
        print(f"Errors ({len(errors)}):")
        for e in errors[:5]:
            print(f"  {e['file']}: {e['error']}")

    print()
    print(LOG_SEPARATOR)

    # Show a sample of changes
    changed = report.get("changed_files", [])
    if changed:
        print(f"Sample changes (first 10 of {len(changed)}):")
        for item in changed[:10]:
            print(f"  FILE: {item['file']}")
            print(f"    BEFORE: {repr(item['original'][:80])}")
            print(f"    AFTER:  {repr(item['fixed'][:80])}")
        if len(changed) > 10:
            print(f"  ... and {len(changed) - 10} more")

    print(LOG_SEPARATOR)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="OCR Artifact Cleanup for MechWarrior 3E lore JSON files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be changed without modifying files (default: False).",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        default=False,
        help="Write a JSON report file alongside the run.",
    )
    parser.add_argument(
        "--report-path",
        default="G:/Meine Ablage/ARS/docs/management/ocr_cleanup_mechwarrior_report.json",
        help="Path for JSON report output.",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        default=False,
        help="Only print statistics, do not process files.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Print each changed file as it is processed.",
    )
    parser.add_argument(
        "--dir",
        default=MECHWARRIOR_LORE_DIR,
        help="Base directory to scan (default: mechwarrior_3e lore dir).",
    )

    args = parser.parse_args()

    base_dir = args.dir

    if not os.path.isdir(base_dir):
        print(f"ERROR: Directory not found: {base_dir}", file=sys.stderr)
        return 1

    if args.stats_only:
        # Just count files and show basic stats without applying fixes
        all_files = glob.glob(os.path.join(base_dir, "**", "*.json"), recursive=True)
        print(f"Total JSON files in {base_dir}: {len(all_files)}")
        sample_count = 0
        with_ng = 0
        for f in all_files:
            try:
                with open(f, encoding="utf-8") as fh:
                    d = json.load(fh)
                ng = d.get("mechanics", {}).get("name_guess")
                if ng:
                    with_ng += 1
                    _, changes = fix_name_guess(ng)
                    if changes:
                        sample_count += 1
            except Exception:
                pass
        print(f"Files with name_guess: {with_ng}")
        print(f"Files with fixable artifacts: {sample_count} ({sample_count/max(with_ng,1)*100:.1f}%)")
        return 0

    mode_label = "DRY RUN" if args.dry_run else "APPLYING FIXES"
    print(f"[ocr_cleanup_mechwarrior] {mode_label}")
    print(f"  Directory: {base_dir}")
    print(f"  Scanning files...", flush=True)

    results = scan_directory(base_dir, dry_run=args.dry_run, verbose=args.verbose)

    report = build_report(results, dry_run=args.dry_run)
    print_summary(report)

    if args.report:
        report_path = args.report_path
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"JSON report written to: {report_path}")

    changed_count = report["summary"]["files_changed"]
    if args.dry_run and changed_count > 0:
        print()
        print(f"DRY RUN complete. {changed_count} files would be modified.")
        print("Run without --dry-run to apply changes.")
    elif not args.dry_run and changed_count > 0:
        print()
        print(f"Done. {changed_count} files modified. Backups stored as *.bak_ocr")

    return 0


if __name__ == "__main__":
    sys.exit(main())
