"""
scripts/rules_tester.py — Deterministischer Regelwerk-Tester fuer AD&D 2e

Testet alle Mechaniken der MechanicsEngine, Tag-Parser und RulesEngine
OHNE KI-Aufrufe. Ergebnisse werden in SQLite gespeichert.

Verwendung:
  py -3 scripts/rules_tester.py run [--unit|--scenario|--matrix|--all]
  py -3 scripts/rules_tester.py run --matrix --matrix-iterations 500
  py -3 scripts/rules_tester.py status [--last N]
  py -3 scripts/rules_tester.py report --run-id N [--failures]
  py -3 scripts/rules_tester.py trends [--days N] [--regressions]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Projektpfad eintragen
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Pfade & Konstanten
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent.parent / "data" / "test_results" / "rules_tests.db"
SCENARIOS_DIR = Path(__file__).parent.parent / "data" / "test_scenarios"

# ANSI-Farben
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ---------------------------------------------------------------------------
# Globale Testzaehler (werden pro Lauf zurueckgesetzt)
# ---------------------------------------------------------------------------

_results: list[dict[str, Any]] = []
_run_id: int = 0
_seed: int = 42
_db_conn: sqlite3.Connection | None = None


# ---------------------------------------------------------------------------
# DB-Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS test_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_mode     TEXT    NOT NULL,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    total_tests  INTEGER DEFAULT 0,
    passed       INTEGER DEFAULT 0,
    failed       INTEGER DEFAULT 0,
    errors       INTEGER DEFAULT 0,
    duration_sec REAL,
    git_commit   TEXT,
    hostname     TEXT
);

CREATE TABLE IF NOT EXISTS test_results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES test_runs(id),
    test_group   TEXT    NOT NULL,
    test_name    TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    duration_ms  REAL,
    input_params TEXT,
    expected     TEXT,
    actual       TEXT,
    message      TEXT
);

CREATE TABLE IF NOT EXISTS matrix_cells (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES test_runs(id),
    test_group   TEXT    NOT NULL,
    param_key    TEXT    NOT NULL,
    iterations   INTEGER,
    pass_count   INTEGER,
    fail_count   INTEGER,
    min_value    REAL,
    max_value    REAL,
    avg_value    REAL,
    stddev_value REAL
);

CREATE TABLE IF NOT EXISTS scenario_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES test_runs(id),
    scenario_file TEXT    NOT NULL,
    scenario_name TEXT    NOT NULL,
    total_steps   INTEGER,
    passed_steps  INTEGER,
    failed_steps  INTEGER,
    final_state   TEXT
);

CREATE INDEX IF NOT EXISTS idx_results_group_status ON test_results(test_group, status);
CREATE INDEX IF NOT EXISTS idx_results_run          ON test_results(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_mode_started    ON test_runs(run_mode, started_at);
"""


def _get_db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db_conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
        _db_conn.executescript(_SCHEMA)
        _db_conn.commit()
    return _db_conn


def _get_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _start_run(mode: str) -> int:
    db = _get_db()
    cur = db.execute(
        "INSERT INTO test_runs (run_mode, started_at, git_commit, hostname) VALUES (?, ?, ?, ?)",
        (mode, datetime.now(timezone.utc).isoformat(), _get_git_commit(), socket.gethostname()),
    )
    db.commit()
    return cur.lastrowid


def _finish_run(run_id: int, total: int, passed: int, failed: int, errors: int,
                started: float) -> None:
    db = _get_db()
    db.execute(
        """UPDATE test_runs SET finished_at=?, total_tests=?, passed=?, failed=?,
           errors=?, duration_sec=? WHERE id=?""",
        (datetime.now(timezone.utc).isoformat(), total, passed, failed, errors,
         time.time() - started, run_id),
    )
    db.commit()


def _record(group: str, name: str, passed: bool, input_params: Any = None,
            expected: Any = None, actual: Any = None, message: str = "",
            duration_ms: float = 0.0, status: str | None = None) -> None:
    """Speichert ein Testergebnis in DB und globale Liste."""
    global _run_id
    if status is None:
        status = "pass" if passed else "fail"
    db = _get_db()
    db.execute(
        """INSERT INTO test_results
           (run_id, test_group, test_name, status, duration_ms,
            input_params, expected, actual, message)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_run_id, group, name, status,
         round(duration_ms, 3),
         json.dumps(input_params, default=str) if input_params is not None else None,
         json.dumps(expected, default=str) if expected is not None else None,
         json.dumps(actual, default=str) if actual is not None else None,
         message),
    )
    db.commit()
    _results.append({
        "group": group, "name": name, "status": status,
        "message": message, "passed": passed,
    })

    # Konsolenausgabe
    icon = f"{GREEN}[OK]{RESET}" if passed else f"{RED}[FEHL]{RESET}"
    suffix = f"  {YELLOW}{message}{RESET}" if message and not passed else ""
    print(f"  {icon} {name}{suffix}")


def _record_matrix_cell(group: str, param_key: str, iterations: int,
                         pass_count: int, fail_count: int,
                         values: list[float]) -> None:
    global _run_id
    avg = sum(values) / len(values) if values else 0.0
    variance = sum((v - avg) ** 2 for v in values) / len(values) if values else 0.0
    db = _get_db()
    db.execute(
        """INSERT INTO matrix_cells
           (run_id, test_group, param_key, iterations, pass_count, fail_count,
            min_value, max_value, avg_value, stddev_value)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_run_id, group, param_key, iterations, pass_count, fail_count,
         min(values) if values else 0.0,
         max(values) if values else 0.0,
         avg, math.sqrt(variance)),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Fixture-Laden
# ---------------------------------------------------------------------------

def _load_ruleset():
    from core.engine import ModuleLoader
    loader = ModuleLoader("add_2e")
    ruleset = loader.load()
    return ruleset


def _load_tables() -> dict:
    tables_path = Path(__file__).parent.parent / "modules" / "rulesets" / "add_2e_tables.json"
    if tables_path.exists():
        with tables_path.open(encoding="utf-8-sig") as f:
            return json.load(f)
    return {}


def _make_mechanics(seed: int | None = None):
    from core.engine import ModuleLoader, DiceConfig
    from core.mechanics import MechanicsEngine
    ruleset = _load_ruleset()
    dice_config = ModuleLoader.get_dice_config(ruleset)
    tables = _load_tables()
    mech = MechanicsEngine(dice_config, tables)
    # Deterministischen RNG injizieren
    mech.rng = random.Random(seed if seed is not None else _seed)
    return mech


def _make_rules_engine():
    from core.rules_engine import RulesEngine
    ruleset = _load_ruleset()
    tables = _load_tables()
    engine = RulesEngine(ruleset, tables)
    return engine


# ---------------------------------------------------------------------------
# ============================================================
# UNIT-TESTS
# ============================================================
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Gruppe: mechanics.attack_roll (~30 Tests)
# ---------------------------------------------------------------------------

def test_attack_roll(mech) -> None:
    group = "mechanics.attack_roll"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # Nat20 trifft immer — egal welche AC / THAC0
    mech.rng = random.Random(None)
    # Wir forcieren den RNG-Wert durch Subklasse
    class _ForcedRNG:
        def __init__(self, val): self._val = val
        def randint(self, a, b): return self._val

    mech.rng = _ForcedRNG(20)
    r = mech.attack_roll(thac0=20, target_ac=10)
    _record(group, "nat20_trifft_immer_ac10", r.is_success and r.success_level == "critical",
            {"thac0": 20, "ac": 10, "forced_roll": 20}, True, r.is_success)

    mech.rng = _ForcedRNG(20)
    r = mech.attack_roll(thac0=20, target_ac=-5)
    _record(group, "nat20_trifft_immer_ac_minus5", r.is_success,
            {"thac0": 20, "ac": -5, "forced_roll": 20}, True, r.is_success)

    mech.rng = _ForcedRNG(20)
    r = mech.attack_roll(thac0=1, target_ac=-10)
    _record(group, "nat20_trifft_immer_beste_ruestung", r.is_success,
            {"thac0": 1, "ac": -10, "forced_roll": 20}, True, r.is_success)

    # Nat1 verfehlt immer
    mech.rng = _ForcedRNG(1)
    r = mech.attack_roll(thac0=1, target_ac=10)
    _record(group, "nat1_verfehlt_immer_ac10", not r.is_success and r.success_level == "fumble",
            {"thac0": 1, "ac": 10, "forced_roll": 1}, False, r.is_success)

    mech.rng = _ForcedRNG(1)
    r = mech.attack_roll(thac0=1, target_ac=-10)
    _record(group, "nat1_verfehlt_immer_ac_minus10", not r.is_success,
            {"thac0": 1, "ac": -10, "forced_roll": 1}, False, r.is_success)

    # Normaler Treffer: thac0=15, ac=5, benoetigt=10, wurf=12 -> Treffer
    mech.rng = _ForcedRNG(12)
    r = mech.attack_roll(thac0=15, target_ac=5)
    _record(group, "normaler_treffer_thac0_15_ac_5", r.is_success,
            {"thac0": 15, "ac": 5, "needed": 10, "roll": 12}, True, r.is_success)

    # Normaler Fehlschlag: benoetigt=10, wurf=8 -> Fehlschlag
    mech.rng = _ForcedRNG(8)
    r = mech.attack_roll(thac0=15, target_ac=5)
    _record(group, "normaler_fehlschlag_roll_8", not r.is_success,
            {"thac0": 15, "ac": 5, "needed": 10, "roll": 8}, False, r.is_success)

    # Grenzfall: genau benoetigt (roll == needed) -> Treffer
    mech.rng = _ForcedRNG(10)
    r = mech.attack_roll(thac0=15, target_ac=5)
    _record(group, "treffer_bei_exakt_benoetigt", r.is_success,
            {"thac0": 15, "ac": 5, "needed": 10, "roll": 10}, True, r.is_success)

    # Grenzfall: ein unter benoetigt -> Fehlschlag
    mech.rng = _ForcedRNG(9)
    r = mech.attack_roll(thac0=15, target_ac=5)
    _record(group, "fehlschlag_eins_unter_benoetigt", not r.is_success,
            {"thac0": 15, "ac": 5, "needed": 10, "roll": 9}, False, r.is_success)

    # Modifikator +2: roll=8+2=10 gegen benoetigt=10 -> Treffer
    mech.rng = _ForcedRNG(8)
    r = mech.attack_roll(thac0=15, target_ac=5, modifiers=2)
    _record(group, "modifikator_plus2_trifft", r.is_success,
            {"thac0": 15, "ac": 5, "needed": 10, "roll": 8, "mod": 2}, True, r.is_success)

    # Modifikator -3: roll=12-3=9 gegen benoetigt=10 -> Fehlschlag
    mech.rng = _ForcedRNG(12)
    r = mech.attack_roll(thac0=15, target_ac=5, modifiers=-3)
    _record(group, "modifikator_minus3_verfehlt", not r.is_success,
            {"thac0": 15, "ac": 5, "needed": 10, "roll": 12, "mod": -3}, False, r.is_success)

    # Schwieriger Gegner: THAC0=20, AC=-5, benoetigt=25 -> nur nat20 trifft
    mech.rng = _ForcedRNG(19)
    r = mech.attack_roll(thac0=20, target_ac=-5)
    _record(group, "fast_untreffbares_ziel_roll19", not r.is_success,
            {"thac0": 20, "ac": -5, "needed": 25, "roll": 19}, False, r.is_success)

    mech.rng = _ForcedRNG(20)
    r = mech.attack_roll(thac0=20, target_ac=-5)
    _record(group, "fast_untreffbares_ziel_nat20", r.is_success,
            {"thac0": 20, "ac": -5, "needed": 25, "roll": 20}, True, r.is_success)

    # Verschiedene THAC0-Werte
    for thac0, ac, roll, expected_hit in [
        (18, 8, 10, True),   # benoetigt=10, roll=10 -> Treffer
        (18, 8, 9, False),   # benoetigt=10, roll=9 -> Fehlschlag
        (10, 0, 10, True),   # benoetigt=10, roll=10 -> Treffer
        (10, 0, 9, False),   # benoetigt=10, roll=9 -> Fehlschlag
        (15, -3, 18, True),  # benoetigt=18, roll=18 -> Treffer
        (15, -3, 17, False), # benoetigt=18, roll=17 -> Fehlschlag
    ]:
        mech.rng = _ForcedRNG(roll)
        r = mech.attack_roll(thac0=thac0, target_ac=ac)
        _record(group, f"thac0_{thac0}_ac_{ac}_roll_{roll}",
                r.is_success == expected_hit,
                {"thac0": thac0, "ac": ac, "roll": roll},
                expected_hit, r.is_success)

    # RollResult Felder korrekt
    mech.rng = _ForcedRNG(15)
    r = mech.attack_roll(thac0=18, target_ac=5)
    _record(group, "rollresult_hat_korrekte_felder",
            hasattr(r, "roll") and hasattr(r, "target") and
            hasattr(r, "success_level") and hasattr(r, "is_success") and
            hasattr(r, "raw_rolls"),
            None, True, True)

    _record(group, "rollresult_raw_rolls_nicht_leer",
            len(r.raw_rolls) > 0, None, ">0", len(r.raw_rolls))


# ---------------------------------------------------------------------------
# Gruppe: mechanics.saving_throw (~15 Tests)
# ---------------------------------------------------------------------------

def test_saving_throw(mech) -> None:
    group = "mechanics.saving_throw"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    class _ForcedRNG:
        def __init__(self, val): self._val = val
        def randint(self, a, b): return self._val

    # Nat20 rettet immer
    mech.rng = _ForcedRNG(20)
    r = mech.saving_throw(target=20)
    _record(group, "nat20_rettet_immer", r.is_success and r.success_level == "critical",
            {"target": 20, "roll": 20}, True, r.is_success)

    mech.rng = _ForcedRNG(20)
    r = mech.saving_throw(target=19)
    _record(group, "nat20_rettet_bei_target_19", r.is_success,
            {"target": 19, "roll": 20}, True, r.is_success)

    # Nat1 scheitert immer
    mech.rng = _ForcedRNG(1)
    r = mech.saving_throw(target=2)
    _record(group, "nat1_scheitert_immer", not r.is_success and r.success_level == "fumble",
            {"target": 2, "roll": 1}, False, r.is_success)

    # Roll-High: target=12, roll=14 -> Erfolg
    mech.rng = _ForcedRNG(14)
    r = mech.saving_throw(target=12)
    _record(group, "roll_high_14_gegen_target_12", r.is_success,
            {"target": 12, "roll": 14}, True, r.is_success)

    # target=12, roll=11 -> Fehlschlag
    mech.rng = _ForcedRNG(11)
    r = mech.saving_throw(target=12)
    _record(group, "roll_high_11_gegen_target_12", not r.is_success,
            {"target": 12, "roll": 11}, False, r.is_success)

    # Genau treffen: roll == target -> Erfolg
    mech.rng = _ForcedRNG(12)
    r = mech.saving_throw(target=12)
    _record(group, "exakt_am_ziel_ist_erfolg", r.is_success,
            {"target": 12, "roll": 12}, True, r.is_success)

    # Modifikator +2: roll=10+2=12 gegen target=12 -> Erfolg
    mech.rng = _ForcedRNG(10)
    r = mech.saving_throw(target=12, modifiers=2)
    _record(group, "modifikator_plus2_rettet", r.is_success,
            {"target": 12, "roll": 10, "mod": 2}, True, r.is_success)

    # Modifikator -2: roll=12-2=10 gegen target=12 -> Fehlschlag
    mech.rng = _ForcedRNG(12)
    r = mech.saving_throw(target=12, modifiers=-2)
    _record(group, "modifikator_minus2_scheitert", not r.is_success,
            {"target": 12, "roll": 12, "mod": -2}, False, r.is_success)

    # Verschiedene Targets
    for target, roll, expected in [
        (15, 15, True),   # exakt
        (15, 14, False),  # knapp drunter
        (5, 6, True),
        (5, 4, False),
        (18, 19, True),
        (18, 17, False),
    ]:
        mech.rng = _ForcedRNG(roll)
        r = mech.saving_throw(target=target)
        _record(group, f"target_{target}_roll_{roll}",
                r.is_success == expected,
                {"target": target, "roll": roll}, expected, r.is_success)

    # Felder vorhanden
    mech.rng = _ForcedRNG(12)
    r = mech.saving_throw(target=12)
    _record(group, "rollresult_hat_success_level",
            r.success_level in ("critical", "regular", "failure", "fumble"),
            None, "gueltige Level", r.success_level)


# ---------------------------------------------------------------------------
# Gruppe: mechanics.morale_check (~10 Tests)
# ---------------------------------------------------------------------------

def test_morale_check(mech) -> None:
    group = "mechanics.morale_check"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    class _ForcedDiceRNG:
        """Gibt vorgegebene Wuerfelwerte der Reihe nach zurueck."""
        def __init__(self, values):
            self._vals = list(values)
            self._idx = 0
        def randint(self, a, b):
            v = self._vals[self._idx % len(self._vals)]
            self._idx += 1
            return v

    # 2d6 <= moral -> bleibt; 2d6 > moral -> flieht
    # moral=8: roll=3+3=6 <= 8 -> bleibt
    mech.rng = _ForcedDiceRNG([3, 3])
    r = mech.morale_check(morale_value=8)
    _record(group, "morale8_roll6_bleibt", r.is_success,
            {"morale": 8, "dice": [3, 3], "total": 6}, True, r.is_success)

    # moral=8: roll=5+5=10 > 8 -> flieht
    mech.rng = _ForcedDiceRNG([5, 5])
    r = mech.morale_check(morale_value=8)
    _record(group, "morale8_roll10_flieht", not r.is_success,
            {"morale": 8, "dice": [5, 5], "total": 10}, False, r.is_success)

    # Genau am Moralwert: roll == moral -> bleibt
    mech.rng = _ForcedDiceRNG([4, 4])
    r = mech.morale_check(morale_value=8)
    _record(group, "morale8_roll8_bleibt", r.is_success,
            {"morale": 8, "dice": [4, 4], "total": 8}, True, r.is_success)

    # Klemmen: morale_value=25 wird auf 20 geklemmt
    mech.rng = _ForcedDiceRNG([6, 6])
    r = mech.morale_check(morale_value=25)
    _record(group, "morale_wert_geklemmt_auf_20",
            r.target <= 20,
            {"morale_input": 25}, "<=20", r.target)

    # Klemmen unten: morale_value=-5 wird auf 2 geklemmt
    mech.rng = _ForcedDiceRNG([1, 1])
    r = mech.morale_check(morale_value=-5)
    _record(group, "morale_wert_geklemmt_auf_2",
            r.target >= 2,
            {"morale_input": -5}, ">=2", r.target)

    # Modifikator: morale=7, mod=+2 -> effective=9
    mech.rng = _ForcedDiceRNG([4, 5])
    r = mech.morale_check(morale_value=7, modifiers=2)
    _record(group, "modifikator_plus2_effective_9", r.target == 9,
            {"morale": 7, "mod": 2}, 9, r.target)

    # Modifikator: morale=10, mod=-3 -> effective=7, roll=4+4=8 > 7 -> flieht
    mech.rng = _ForcedDiceRNG([4, 4])
    r = mech.morale_check(morale_value=10, modifiers=-3)
    _record(group, "modifikator_minus3_flieht", not r.is_success,
            {"morale": 10, "mod": -3, "dice": [4, 4]}, False, r.is_success)

    # raw_rolls hat 2 Eintraege (2d6)
    mech.rng = _ForcedDiceRNG([3, 4])
    r = mech.morale_check(morale_value=10)
    _record(group, "raw_rolls_hat_2_eintraege", len(r.raw_rolls) == 2,
            None, 2, len(r.raw_rolls))

    # is_success-Felder korrekt
    _record(group, "rollresult_felder_vorhanden",
            hasattr(r, "roll") and hasattr(r, "target") and hasattr(r, "is_success"),
            None, True, True)


# ---------------------------------------------------------------------------
# Gruppe: mechanics.reaction_roll (~10 Tests)
# ---------------------------------------------------------------------------

def test_reaction_roll(mech) -> None:
    group = "mechanics.reaction_roll"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    class _ForcedDiceRNG:
        def __init__(self, values):
            self._vals = list(values)
            self._idx = 0
        def randint(self, a, b):
            v = self._vals[self._idx % len(self._vals)]
            self._idx += 1
            return v

    # Schluessel im Ergebnis-Dict
    mech.rng = _ForcedDiceRNG([3, 3])
    r = mech.reaction_roll()
    _record(group, "ergebnis_hat_alle_schluessel",
            all(k in r for k in ("roll", "modified_roll", "reaction_level", "description")),
            None, True, list(r.keys()))

    # Reaktionslevel-Mapping: modified_roll <= 2 -> hostile_attack
    mech.rng = _ForcedDiceRNG([1, 1])
    r = mech.reaction_roll(cha_modifier=0)
    _record(group, "roll2_ist_hostile_attack", r["reaction_level"] == "hostile_attack",
            {"dice": [1, 1], "total": 2}, "hostile_attack", r["reaction_level"])

    # modified_roll 3-5 -> hostile
    mech.rng = _ForcedDiceRNG([2, 2])  # =4
    r = mech.reaction_roll(cha_modifier=0)
    _record(group, "roll4_ist_hostile", r["reaction_level"] == "hostile",
            {"dice": [2, 2], "total": 4}, "hostile", r["reaction_level"])

    # modified_roll 6-8 -> neutral
    mech.rng = _ForcedDiceRNG([3, 4])  # =7
    r = mech.reaction_roll(cha_modifier=0)
    _record(group, "roll7_ist_neutral", r["reaction_level"] == "neutral",
            {"dice": [3, 4], "total": 7}, "neutral", r["reaction_level"])

    # modified_roll 9-11 -> friendly
    mech.rng = _ForcedDiceRNG([5, 5])  # =10
    r = mech.reaction_roll(cha_modifier=0)
    _record(group, "roll10_ist_friendly", r["reaction_level"] == "friendly",
            {"dice": [5, 5], "total": 10}, "friendly", r["reaction_level"])

    # modified_roll >= 12 -> enthusiastic
    mech.rng = _ForcedDiceRNG([6, 6])  # =12
    r = mech.reaction_roll(cha_modifier=0)
    _record(group, "roll12_ist_enthusiastic", r["reaction_level"] == "enthusiastic",
            {"dice": [6, 6], "total": 12}, "enthusiastic", r["reaction_level"])

    # CHA-Modifikator verschiebt das Ergebnis
    mech.rng = _ForcedDiceRNG([2, 2])  # raw=4
    r = mech.reaction_roll(cha_modifier=5)  # modified=9 -> friendly
    _record(group, "cha_mod_plus5_verschiebt_auf_friendly", r["reaction_level"] == "friendly",
            {"dice": [2, 2], "raw": 4, "mod": 5, "modified": 9}, "friendly", r["reaction_level"])

    # Negativer Modifikator
    mech.rng = _ForcedDiceRNG([4, 4])  # raw=8
    r = mech.reaction_roll(cha_modifier=-5)  # modified=3 -> hostile
    _record(group, "cha_mod_minus5_verschiebt_auf_hostile", r["reaction_level"] == "hostile",
            {"dice": [4, 4], "raw": 8, "mod": -5, "modified": 3}, "hostile", r["reaction_level"])

    # modified_roll korrekt berechnet
    mech.rng = _ForcedDiceRNG([3, 4])  # raw=7
    r = mech.reaction_roll(cha_modifier=2)
    _record(group, "modified_roll_korrekt_berechnet", r["modified_roll"] == 9,
            {"raw": 7, "mod": 2}, 9, r["modified_roll"])


# ---------------------------------------------------------------------------
# Gruppe: mechanics.turn_undead (~20 Tests)
# ---------------------------------------------------------------------------

def test_turn_undead(mech) -> None:
    group = "mechanics.turn_undead"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    class _ForcedDiceRNG:
        def __init__(self, values):
            self._vals = list(values)
            self._idx = 0
        def randint(self, a, b):
            v = self._vals[self._idx % len(self._vals)]
            self._idx += 1
            return v

    # Unmoeglich: L1 vs Wraith ("-")
    r = mech.turn_undead(cleric_level=1, undead_hd="wraith")
    _record(group, "level1_vs_wraith_unmoeglich",
            not r["success"] and r["result_type"] == "impossible",
            {"level": 1, "undead": "wraith"}, "impossible", r["result_type"])

    # Automatisch vertrieben: L4 vs Skelett ("T")
    r = mech.turn_undead(cleric_level=4, undead_hd="skeleton")
    _record(group, "level4_vs_skeleton_auto_turned",
            r["success"] and r["result_type"] == "turned",
            {"level": 4, "undead": "skeleton"}, "turned", r["result_type"])

    # Automatisch zerstoert: L6 vs Skelett ("D")
    r = mech.turn_undead(cleric_level=6, undead_hd="skeleton")
    _record(group, "level6_vs_skeleton_auto_destroyed",
            r["success"] and r["result_type"] == "destroyed",
            {"level": 6, "undead": "skeleton"}, "destroyed", r["result_type"])

    # Normaler Wurf noetig: L1 vs Skelett (Zielwert 10)
    # roll=10 >= 10 -> vertrieben
    mech.rng = _ForcedDiceRNG([5, 5])
    r = mech.turn_undead(cleric_level=1, undead_hd="skeleton")
    _record(group, "level1_vs_skeleton_roll10_vertrieben",
            r["success"] and r["result_type"] == "turned",
            {"level": 1, "undead": "skeleton", "roll": 10, "target": 10},
            "turned", r["result_type"])

    # roll=9 < 10 -> fehlgeschlagen
    mech.rng = _ForcedDiceRNG([4, 5])
    r = mech.turn_undead(cleric_level=1, undead_hd="skeleton")
    _record(group, "level1_vs_skeleton_roll9_fehlgeschlagen",
            not r["success"] and r["result_type"] == "failed",
            {"level": 1, "undead": "skeleton", "roll": 9, "target": 10},
            "failed", r["result_type"])

    # Numerische HD
    mech.rng = _ForcedDiceRNG([5, 5])
    r = mech.turn_undead(cleric_level=1, undead_hd=1)
    _record(group, "level1_vs_hd1_numerisch_verarbeitet",
            "result_type" in r, None, True, True)

    # Vampire: L5 vs vampire -> "20" noetig (aus Tabelle)
    mech.rng = _ForcedDiceRNG([6, 6])  # =12 < 20 -> fehlgeschlagen
    r = mech.turn_undead(cleric_level=5, undead_hd="vampire")
    _record(group, "level5_vs_vampire_roll12_fehlgeschlagen",
            not r["success"],
            {"level": 5, "undead": "vampire", "roll": 12}, False, r["success"])

    # Level 14+ kapped: gleich wie 14
    r1 = mech.turn_undead(cleric_level=14, undead_hd="vampire")
    r2 = mech.turn_undead(cleric_level=20, undead_hd="vampire")
    _record(group, "level14_und_level20_gleiches_ergebnis",
            r1["result_type"] == r2["result_type"],
            {"level14_type": r1["result_type"], "level20_type": r2["result_type"]},
            r1["result_type"], r2["result_type"])

    # Ergebnis-Dict hat alle Schluessel
    r = mech.turn_undead(cleric_level=5, undead_hd="ghoul")
    _record(group, "ergebnis_hat_alle_schluessel",
            all(k in r for k in ("success", "result_type", "roll", "target", "description")),
            None, True, list(r.keys()))

    # Lich: L7 vs lich -> tabelle = 20
    mech.rng = _ForcedDiceRNG([6, 6])  # =12 < 20
    r = mech.turn_undead(cleric_level=7, undead_hd="lich")
    _record(group, "level7_vs_lich_benoetigt_20",
            r["target"] == 20 if r["target"] is not None else False,
            {"level": 7, "undead": "lich"}, 20, r.get("target"))

    # Beschreibung nicht leer
    r = mech.turn_undead(cleric_level=3, undead_hd="zombie")
    _record(group, "beschreibung_nicht_leer",
            len(r["description"]) > 10,
            None, ">10 Zeichen", len(r["description"]))

    # Verschiedene Untoten-Namen
    for name in ["skeleton", "zombie", "ghoul", "shadow", "wight", "wraith",
                 "mummy", "spectre", "vampire", "ghost", "lich"]:
        r = mech.turn_undead(cleric_level=10, undead_hd=name)
        _record(group, f"untote_name_{name}_verarbeitet",
                "result_type" in r,
                {"undead": name}, True, True)


# ---------------------------------------------------------------------------
# Gruppe: mechanics.roll_treasure (~10 Tests)
# ---------------------------------------------------------------------------

def test_roll_treasure(mech) -> None:
    group = "mechanics.roll_treasure"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # RNG zuruecksetzen — vorherige Tests koennen einen _ForcedDiceRNG ohne choice() hinterlassen
    mech.rng = random.Random(_seed)

    # Alle Typen A-Q muessen valide Ergebnisse liefern
    for t in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q"]:
        r = mech.roll_treasure(t)
        _record(group, f"typ_{t}_liefert_dict", isinstance(r, dict),
                {"type": t}, True, isinstance(r, dict))

    # Pflichtschluessel
    r = mech.roll_treasure("A")
    _record(group, "typ_A_hat_coins_schluessel",
            "coins" in r or any(k in r for k in ("cp", "sp", "ep", "gp", "pp")),
            None, True, list(r.keys())[:5])

    # Alle Werte >= 0
    for t in ["A", "B", "H"]:
        r = mech.roll_treasure(t)
        coins = r.get("coins", {})
        if isinstance(coins, dict):
            all_positive = all(v >= 0 for v in coins.values() if isinstance(v, (int, float)))
        else:
            all_positive = True
        _record(group, f"typ_{t}_keine_negativen_werte", all_positive,
                {"type": t}, True, all_positive)


# ---------------------------------------------------------------------------
# Gruppe: mechanics.roll_expression (~10 Tests)
# ---------------------------------------------------------------------------

def test_roll_expression(mech) -> None:
    group = "mechanics.roll_expression"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # Feste Zahl
    r = mech.roll_expression("3")
    _record(group, "feste_zahl_3", r == 3, {"expr": "3"}, 3, r)

    r = mech.roll_expression("0")
    _record(group, "feste_zahl_0", r == 0, {"expr": "0"}, 0, r)

    # 1d6: Ergebnis zwischen 1-6
    mech.rng = random.Random(42)
    r = mech.roll_expression("1d6")
    _record(group, "1d6_im_bereich", 1 <= r <= 6, {"expr": "1d6"}, "1-6", r)

    # 2d4+2: Bereich 4-10
    mech.rng = random.Random(42)
    r = mech.roll_expression("2d4+2")
    _record(group, "2d4plus2_im_bereich", 4 <= r <= 10, {"expr": "2d4+2"}, "4-10", r)

    # 1d8+1: Bereich 2-9
    mech.rng = random.Random(42)
    r = mech.roll_expression("1d8+1")
    _record(group, "1d8plus1_im_bereich", 2 <= r <= 9, {"expr": "1d8+1"}, "2-9", r)

    # 1d20: Bereich 1-20
    mech.rng = random.Random(42)
    r = mech.roll_expression("1d20")
    _record(group, "1d20_im_bereich", 1 <= r <= 20, {"expr": "1d20"}, "1-20", r)

    # 3d6: Bereich 3-18
    mech.rng = random.Random(42)
    r = mech.roll_expression("3d6")
    _record(group, "3d6_im_bereich", 3 <= r <= 18, {"expr": "3d6"}, "3-18", r)

    # Deterministisch: gleicher Seed -> gleiches Ergebnis
    mech.rng = random.Random(1234)
    r1 = mech.roll_expression("2d6")
    mech.rng = random.Random(1234)
    r2 = mech.roll_expression("2d6")
    _record(group, "gleicher_seed_gleiche_ergebnis", r1 == r2,
            {"seed": 1234, "expr": "2d6"}, r1, r2)

    # Unbekannter Ausdruck gibt 1 zurueck
    r = mech.roll_expression("xyz")
    _record(group, "unbekannter_ausdruck_gibt_1", r == 1, {"expr": "xyz"}, 1, r)


# ---------------------------------------------------------------------------
# Gruppe: mechanics.skill_check (~10 Tests)
# ---------------------------------------------------------------------------

def test_skill_check(mech) -> None:
    group = "mechanics.skill_check"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    class _ForcedRNG:
        def __init__(self, val): self._val = val
        def randint(self, a, b): return self._val

    # d100-Modus (target > dice_faces=20): target=65 (Prozent-Fertigkeit)
    mech.rng = _ForcedRNG(50)
    r = mech.skill_check(target=65)
    _record(group, "d100_modus_roll50_gegen_65_erfolg", r.is_success,
            {"target": 65, "roll": 50}, True, r.is_success)

    mech.rng = _ForcedRNG(70)
    r = mech.skill_check(target=65)
    _record(group, "d100_modus_roll70_gegen_65_fehlschlag", not r.is_success,
            {"target": 65, "roll": 70}, False, r.is_success)

    # d20-Modus (target <= 20): target=15
    mech.rng = _ForcedRNG(14)
    r = mech.skill_check(target=15)
    _record(group, "d20_modus_roll14_gegen_15_erfolg", r.is_success,
            {"target": 15, "roll": 14}, True, r.is_success)

    mech.rng = _ForcedRNG(16)
    r = mech.skill_check(target=15)
    _record(group, "d20_modus_roll16_gegen_15_fehlschlag", not r.is_success,
            {"target": 15, "roll": 16}, False, r.is_success)

    # Kritisch: d100, roll=1
    mech.rng = _ForcedRNG(1)
    r = mech.skill_check(target=65)
    _record(group, "d100_roll1_kritisch", r.success_level == "critical",
            {"target": 65, "roll": 1}, "critical", r.success_level)

    # Patzer: d100, roll >= 96
    mech.rng = _ForcedRNG(98)
    r = mech.skill_check(target=65)
    _record(group, "d100_roll98_patzer", r.success_level == "fumble",
            {"target": 65, "roll": 98}, "fumble", r.success_level)

    # RollResult Felder vorhanden
    _record(group, "rollresult_felder_korrekt",
            all(hasattr(r, f) for f in ("roll", "target", "success_level", "is_success")),
            None, True, True)


# ---------------------------------------------------------------------------
# Gruppe: mechanics.lookup_thac0 (~8 Tests)
# ---------------------------------------------------------------------------

def test_lookup_thac0(mech) -> None:
    group = "mechanics.lookup_thac0"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # Warrior Level 1 = 20
    r = mech.lookup_thac0("warrior", 1)
    _record(group, "warrior_level1_ist_20", r == 20,
            {"class": "warrior", "level": 1}, 20, r)

    # Warrior Level 3 = 18 (laut PHB)
    r = mech.lookup_thac0("warrior", 3)
    _record(group, "warrior_level3_ist_18", r == 18,
            {"class": "warrior", "level": 3}, 18, r)

    # Wizard Level 1 = 20
    r = mech.lookup_thac0("wizard", 1)
    _record(group, "wizard_level1_ist_20", r == 20,
            {"class": "wizard", "level": 1}, 20, r)

    # Unbekannte Klasse -> Fallback 20
    r = mech.lookup_thac0("unknown_class", 5)
    _record(group, "unbekannte_klasse_fallback_20", r == 20,
            {"class": "unknown_class", "level": 5}, 20, r)

    # Hoehere Level -> niedrigerer THAC0
    r_low = mech.lookup_thac0("warrior", 1)
    r_high = mech.lookup_thac0("warrior", 10)
    _record(group, "hoehere_level_niedrigerer_thac0", r_high <= r_low,
            {"level1": r_low, "level10": r_high}, True, r_high <= r_low)

    # Level > Tabelle -> kein Crash
    r = mech.lookup_thac0("warrior", 25)
    _record(group, "level25_kein_crash", isinstance(r, int),
            {"class": "warrior", "level": 25}, True, isinstance(r, int))

    # Priest und Rogue
    r_priest = mech.lookup_thac0("priest", 1)
    _record(group, "priest_level1_integer", isinstance(r_priest, int),
            {"class": "priest", "level": 1}, True, isinstance(r_priest, int))

    r_rogue = mech.lookup_thac0("rogue", 1)
    _record(group, "rogue_level1_integer", isinstance(r_rogue, int),
            {"class": "rogue", "level": 1}, True, isinstance(r_rogue, int))


# ---------------------------------------------------------------------------
# Gruppe: mechanics.lookup_saving_throw (~8 Tests)
# ---------------------------------------------------------------------------

def test_lookup_saving_throw(mech) -> None:
    group = "mechanics.lookup_saving_throw"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # Alle 5 Save-Typen fuer warrior L1 liefern Integer
    for save_type in range(5):
        r = mech.lookup_saving_throw("warrior", 1, save_type)
        _record(group, f"warrior_l1_save_typ{save_type}_integer",
                isinstance(r, int) and 2 <= r <= 20,
                {"class": "warrior", "level": 1, "save_type": save_type}, "2-20", r)

    # Unbekannte Klasse -> Fallback 20
    r = mech.lookup_saving_throw("unknown", 1, 0)
    _record(group, "unbekannte_klasse_fallback_20", r == 20,
            {"class": "unknown", "level": 1, "save_type": 0}, 20, r)

    # Hoehere Level -> niedrigere Save-Targets
    r_l1 = mech.lookup_saving_throw("warrior", 1, 4)
    r_l15 = mech.lookup_saving_throw("warrior", 15, 4)
    _record(group, "hoehere_level_niedrigerer_save", r_l15 <= r_l1,
            {"l1": r_l1, "l15": r_l15}, True, r_l15 <= r_l1)


# ---------------------------------------------------------------------------
# Gruppe: mechanics.initiative_roll (~5 Tests)
# ---------------------------------------------------------------------------

def test_initiative_roll(mech) -> None:
    group = "mechanics.initiative_roll"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # Mehrere Rolls: Ergebnis immer >= 1
    for seed in range(5):
        mech.rng = random.Random(seed * 100)
        r = mech.initiative_roll(0)
        _record(group, f"initiative_seed{seed}_gueltig",
                isinstance(r, int),
                {"seed": seed}, True, r)

    # Modifikator wird addiert
    class _ForcedRNG:
        def __init__(self, val): self._val = val
        def randint(self, a, b): return self._val

    mech.rng = _ForcedRNG(5)
    r = mech.initiative_roll(modifier=3)
    _record(group, "modifikator_3_addiert", r == 8,
            {"roll": 5, "mod": 3}, 8, r)

    mech.rng = _ForcedRNG(5)
    r = mech.initiative_roll(modifier=-2)
    _record(group, "modifikator_minus2_subtrahiert", r == 3,
            {"roll": 5, "mod": -2}, 3, r)


# ---------------------------------------------------------------------------
# Gruppe: mechanics.encumbrance (~5 Tests)
# ---------------------------------------------------------------------------

def test_encumbrance(mech) -> None:
    group = "mechanics.encumbrance"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # Unbelastet: leichte Items bei STR 10
    items = [("Schwert", 5.0), ("Rucksack", 3.0)]  # 8 lbs, max fuer STR10=40
    r = mech.calculate_encumbrance(items, str_score=10)
    _record(group, "str10_8lbs_unbelastet", r["category"] == "unencumbered",
            {"items_weight": 8, "str": 10}, "unencumbered", r["category"])

    # Schwer belastet
    heavy_items = [("Ruestung", 45.0)]  # STR10 max=40 -> severe
    r = mech.calculate_encumbrance(heavy_items, str_score=10)
    _record(group, "str10_45lbs_ueberlastet", r["category"] == "severe",
            {"items_weight": 45, "str": 10}, "severe", r["category"])

    # STR 18 traegt mehr
    r18 = mech.calculate_encumbrance([("Ladung", 80.0)], str_score=18)
    r10 = mech.calculate_encumbrance([("Ladung", 80.0)], str_score=10)
    _record(group, "str18_traegt_mehr_als_str10",
            r18["max_allowance"] > r10["max_allowance"],
            {"str18_max": r18["max_allowance"], "str10_max": r10["max_allowance"]},
            True, True)

    # Alle Pflicht-Schluessel vorhanden
    r = mech.calculate_encumbrance([("Item", 1.0)], str_score=12)
    _record(group, "alle_schluessel_vorhanden",
            all(k in r for k in ("total_weight", "max_allowance", "category",
                                  "movement_factor", "description")),
            None, True, list(r.keys()))

    # Leere Itemliste -> Gewicht 0
    r = mech.calculate_encumbrance([], str_score=10)
    _record(group, "leere_liste_gewicht_null",
            r["total_weight"] == 0.0,
            {"items": []}, 0.0, r["total_weight"])


# ---------------------------------------------------------------------------
# Gruppe: tag_parser.extract_stat_changes (~20 Tests)
# ---------------------------------------------------------------------------

def test_extract_stat_changes() -> None:
    from core.character import extract_stat_changes
    group = "tag_parser.extract_stat_changes"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # HP_VERLUST
    r = extract_stat_changes("[HP_VERLUST: 5]")
    _record(group, "hp_verlust_5_erkannt",
            any(t[0] == "HP_VERLUST" and t[1] == "5" for t in r),
            {"text": "[HP_VERLUST: 5]"}, ("HP_VERLUST", "5"), r)

    # HP_HEILUNG
    r = extract_stat_changes("[HP_HEILUNG: 3]")
    _record(group, "hp_heilung_3_erkannt",
            any(t[0] == "HP_HEILUNG" and t[1] == "3" for t in r),
            {"text": "[HP_HEILUNG: 3]"}, ("HP_HEILUNG", "3"), r)

    # HP_HEILUNG mit Wuerfelausdruck (Muster: \d+d\d+, kein +Modifier)
    r = extract_stat_changes("[HP_HEILUNG: 2d4]")
    _record(group, "hp_heilung_wuerfelausdruck",
            any(t[0] == "HP_HEILUNG" and "2d4" in t[1] for t in r),
            {"text": "[HP_HEILUNG: 2d4]"}, True, r)

    # XP_GEWINN
    r = extract_stat_changes("[XP_GEWINN: 150]")
    _record(group, "xp_gewinn_150_erkannt",
            any(t[0] == "XP_GEWINN" and t[1] == "150" for t in r),
            {"text": "[XP_GEWINN: 150]"}, ("XP_GEWINN", "150"), r)

    # MAGIC_RESISTANCE
    r = extract_stat_changes("[MAGIC_RESISTANCE: Drachenwyrm | 30]")
    _record(group, "magic_resistance_erkannt",
            any(t[0] == "MAGIC_RESISTANCE" for t in r),
            {"text": "[MAGIC_RESISTANCE: Drachenwyrm | 30]"}, True, r)

    # WAFFEN_IMMUNITAET
    r = extract_stat_changes("[WAFFEN_IMMUNITAET: Geist | +1]")
    _record(group, "waffen_immunitaet_erkannt",
            any(t[0] == "WAFFEN_IMMUNITAET" for t in r),
            {"text": "[WAFFEN_IMMUNITAET: Geist | +1]"}, True, r)

    # GIFT
    r = extract_stat_changes("[GIFT: Schlange | Tod | -2]")
    _record(group, "gift_erkannt",
            any(t[0] == "GIFT" for t in r),
            {"text": "[GIFT: Schlange | Tod | -2]"}, True, r)

    # LEVEL_DRAIN
    r = extract_stat_changes("[LEVEL_DRAIN: Valdrak | 2]")
    _record(group, "level_drain_erkannt",
            any(t[0] == "LEVEL_DRAIN" for t in r),
            {"text": "[LEVEL_DRAIN: Valdrak | 2]"}, True, r)

    # MORAL_CHECK
    r = extract_stat_changes("[MORAL_CHECK: Goblin | 8]")
    _record(group, "moral_check_erkannt",
            any(t[0] == "MORAL_CHECK" for t in r),
            {"text": "[MORAL_CHECK: Goblin | 8]"}, True, r)

    # REGENERATION
    r = extract_stat_changes("[REGENERATION: Troll | 3]")
    _record(group, "regeneration_erkannt",
            any(t[0] == "REGENERATION" for t in r),
            {"text": "[REGENERATION: Troll | 3]"}, True, r)

    # FURCHT
    r = extract_stat_changes("[FURCHT: Held | Flucht | 2 Runden]")
    _record(group, "furcht_erkannt",
            any(t[0] == "FURCHT" for t in r),
            {"text": "[FURCHT: Held | Flucht | 2 Runden]"}, True, r)

    # ATEM_WAFFE
    r = extract_stat_changes("[ATEM_WAFFE: Drache | Feuer | 6d8]")
    _record(group, "atem_waffe_erkannt",
            any(t[0] == "ATEM_WAFFE" for t in r),
            {"text": "[ATEM_WAFFE: Drache | Feuer | 6d8]"}, True, r)

    # Mehrere Tags in einem Text
    text = "Der Drache greift an. [HP_VERLUST: 8] Die Magie wirkt. [XP_GEWINN: 200]"
    r = extract_stat_changes(text)
    _record(group, "mehrere_tags_in_text",
            len(r) >= 2,
            {"text": text}, ">=2 Tags", len(r))

    # Case-Insensitiv
    r = extract_stat_changes("[hp_verlust: 3]")
    _record(group, "case_insensitiv",
            len(r) >= 1,
            {"text": "[hp_verlust: 3]"}, ">=1", len(r))

    # Kein Tag -> leere Liste
    r = extract_stat_changes("Normaler Text ohne Tags.")
    _record(group, "kein_tag_leere_liste",
            r == [],
            {"text": "Normaler Text."}, [], r)

    # Fehlerhafter Tag -> nicht extrahiert
    r = extract_stat_changes("[HP_VERLUST:]")
    _record(group, "fehlerhafter_tag_nicht_extrahiert",
            not any(t[0] == "HP_VERLUST" for t in r),
            {"text": "[HP_VERLUST:]"}, [], r)


# ---------------------------------------------------------------------------
# Gruppe: tag_parser.extract_combat_tags (~10 Tests)
# ---------------------------------------------------------------------------

def test_extract_combat_tags() -> None:
    from core.character import extract_combat_tags
    group = "tag_parser.extract_combat_tags"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # ANGRIFF-Tag
    text = "[ANGRIFF: Schwert | 15 | 5 | 0]"
    r = extract_combat_tags(text)
    _record(group, "angriff_tag_erkannt",
            any(t[0] == "ANGRIFF" for t in r),
            {"text": text}, True, [t[0] for t in r])

    # ANGRIFF-Werte korrekt
    r = extract_combat_tags("[ANGRIFF: Schwert | 15 | 5 | 0]")
    if r:
        d = r[0][1]
        _record(group, "angriff_weapon_korrekt", d["weapon"] == "Schwert",
                d, "Schwert", d.get("weapon"))
        _record(group, "angriff_thac0_korrekt", d["thac0"] == 15,
                d, 15, d.get("thac0"))
        _record(group, "angriff_target_ac_korrekt", d["target_ac"] == 5,
                d, 5, d.get("target_ac"))
        _record(group, "angriff_modifiers_korrekt", d["modifiers"] == 0,
                d, 0, d.get("modifiers"))
    else:
        _record(group, "angriff_werte_nicht_parsbar", False, {"text": text}, True, False)

    # RETTUNGSWURF-Tag
    text = "[RETTUNGSWURF: Gift | 14]"
    r = extract_combat_tags(text)
    _record(group, "rettungswurf_tag_erkannt",
            any(t[0] == "RETTUNGSWURF" for t in r),
            {"text": text}, True, [t[0] for t in r])

    # RETTUNGSWURF-Werte
    if r:
        d = r[0][1]
        _record(group, "rettungswurf_kategorie_korrekt", d["category"] == "Gift",
                d, "Gift", d.get("category"))
        _record(group, "rettungswurf_target_korrekt", d["target"] == 14,
                d, 14, d.get("target"))

    # Mehrere Tags
    text = "[ANGRIFF: Axt | 18 | 3 | 2] ... [RETTUNGSWURF: Laehmung | 12]"
    r = extract_combat_tags(text)
    _record(group, "mehrere_kampftags_erkannt",
            len(r) == 2,
            {"text": text}, 2, len(r))

    # Negativer Modifikator
    text = "[ANGRIFF: Dolch | 18 | 7 | -2]"
    r = extract_combat_tags(text)
    if r:
        _record(group, "negativer_modifikator_erkannt", r[0][1]["modifiers"] == -2,
                {"text": text}, -2, r[0][1].get("modifiers"))
    else:
        _record(group, "negativer_modifikator_erkannt", False, {"text": text}, True, False)


# ---------------------------------------------------------------------------
# Gruppe: tag_parser.extract_party (~15 Tests)
# ---------------------------------------------------------------------------

def test_extract_party_tags() -> None:
    from core.character import extract_party_stat_changes
    group = "tag_parser.extract_party"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # Party HP_VERLUST
    r = extract_party_stat_changes("[HP_VERLUST: Valdrak | 5]")
    _record(group, "party_hp_verlust_erkannt",
            any(t[0] == "HP_VERLUST" and t[1] == "Valdrak" and t[2] == "5" for t in r),
            None, True, r)

    # Party HP_HEILUNG
    r = extract_party_stat_changes("[HP_HEILUNG: Elara | 2d4+2]")
    _record(group, "party_hp_heilung_erkannt",
            any(t[0] == "HP_HEILUNG" and t[1] == "Elara" for t in r),
            None, True, r)

    # Party ZAUBER_VERBRAUCHT
    r = extract_party_stat_changes("[ZAUBER_VERBRAUCHT: Elara | Feuerball | 3]")
    _record(group, "party_zauber_verbraucht_erkannt",
            any(t[0] == "ZAUBER_VERBRAUCHT" and t[1] == "Elara" for t in r),
            None, True, r)

    # Party INVENTAR
    r = extract_party_stat_changes("[INVENTAR: Heiltrank | gefunden | Lyra]")
    _record(group, "party_inventar_erkannt",
            any(t[0] == "INVENTAR" and t[3] == "Lyra" for t in r),
            None, True, r)

    # Party FERTIGKEIT_GENUTZT
    r = extract_party_stat_changes("[FERTIGKEIT_GENUTZT: Move Silently | Lyra]")
    _record(group, "party_fertigkeit_erkannt",
            any(t[0] == "FERTIGKEIT_GENUTZT" and t[2] == "Lyra" for t in r),
            None, True, r)

    # Party PROBE
    r = extract_party_stat_changes("[PROBE: Fallen-Suchen | 45 | Lyra]")
    _record(group, "party_probe_erkannt",
            any(t[0] == "PROBE" and t[3] == "Lyra" for t in r),
            None, True, r)

    # Party ANGRIFF (5 Felder)
    r = extract_party_stat_changes("[ANGRIFF: Schwert | 15 | 5 | 0 | Valdrak]")
    _record(group, "party_angriff_erkannt",
            any(t[0] == "ANGRIFF" and len(t) == 6 and t[5] == "Valdrak" for t in r),
            None, True, r)

    # Monster-Tags auch in Party-Modus erkannt
    r = extract_party_stat_changes("[MAGIC_RESISTANCE: Golem | 50]")
    _record(group, "party_magic_resistance_erkannt",
            any(t[0] == "MAGIC_RESISTANCE" for t in r),
            None, True, r)

    r = extract_party_stat_changes("[REGENERATION: Troll | 3]")
    _record(group, "party_regeneration_erkannt",
            any(t[0] == "REGENERATION" for t in r),
            None, True, r)

    # Gemischter Text
    text = "[HP_VERLUST: Bruder | 4] Dann heilt er. [HP_HEILUNG: Bruder | 2]"
    r = extract_party_stat_changes(text)
    _record(group, "gemischte_party_tags_beide_erkannt",
            any(t[0] == "HP_VERLUST" for t in r) and any(t[0] == "HP_HEILUNG" for t in r),
            {"text": text}, True, [t[0] for t in r])

    # Kein Party-Tag -> leere Liste (reine Solo-Tags werden hier nicht erkannt)
    r = extract_party_stat_changes("[HP_VERLUST: 5]")
    _record(group, "solo_hp_verlust_nicht_als_party_erkannt",
            not any(t[0] == "HP_VERLUST" and len(t) >= 3 and t[1].isdigit() for t in r),
            {"text": "[HP_VERLUST: 5]"}, True,
            [t for t in r if t[0] == "HP_VERLUST"])

    # LEVEL_DRAIN in Party-Modus
    r = extract_party_stat_changes("[LEVEL_DRAIN: Valdrak | 1]")
    _record(group, "party_level_drain_erkannt",
            any(t[0] == "LEVEL_DRAIN" for t in r),
            None, True, r)

    # FURCHT in Party-Modus
    r = extract_party_stat_changes("[FURCHT: Lyra | Panik | 3 Runden]")
    _record(group, "party_furcht_erkannt",
            any(t[0] == "FURCHT" for t in r),
            None, True, r)


# ---------------------------------------------------------------------------
# Gruppe: validation.* (~26 Tests)
# ---------------------------------------------------------------------------

def test_validation() -> None:
    engine = _make_rules_engine()
    group = "validation"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    # --- validate_attack ---
    # Gueltiger Angriff
    vr = engine.validate_attack({"weapon": "Schwert", "thac0": 15, "target_ac": 5, "modifiers": 0})
    _record(group, "attack_gueltig_kein_fehler", vr.severity == "ok",
            {"thac0": 15, "ac": 5}, "ok", vr.severity)

    # THAC0 ausserhalb 1-20
    vr = engine.validate_attack({"weapon": "X", "thac0": 25, "target_ac": 5, "modifiers": 0})
    _record(group, "attack_thac0_25_warnung", vr.severity == "warning",
            {"thac0": 25}, "warning", vr.severity)

    # AC ausserhalb -10..10
    vr = engine.validate_attack({"weapon": "X", "thac0": 15, "target_ac": 15, "modifiers": 0})
    _record(group, "attack_ac_15_warnung", vr.severity == "warning",
            {"ac": 15}, "warning", vr.severity)

    # --- validate_saving_throw ---
    vr = engine.validate_saving_throw({"category": "Gift", "target": 14})
    _record(group, "save_gift_gueltig", vr.severity == "ok",
            {"cat": "Gift", "target": 14}, "ok", vr.severity)

    vr = engine.validate_saving_throw({"category": "Unbekannt_XYZ", "target": 14})
    _record(group, "save_unbekannte_kategorie_warnung", vr.severity == "warning",
            {"cat": "Unbekannt_XYZ"}, "warning", vr.severity)

    vr = engine.validate_saving_throw({"category": "Zauber", "target": 25})
    _record(group, "save_target_25_ausserhalb", vr.severity == "warning",
            {"target": 25}, "warning", vr.severity)

    # --- validate_hp_change ---
    vr = engine.validate_hp_change("HP_VERLUST", "8", None)
    _record(group, "hp_verlust_8_gueltig", vr.severity == "ok",
            {"type": "HP_VERLUST", "val": "8"}, "ok", vr.severity)

    vr = engine.validate_hp_change("HP_VERLUST", "-3", None)
    _record(group, "hp_verlust_negativ_warnung", vr.severity == "warning",
            {"type": "HP_VERLUST", "val": "-3"}, "warning", vr.severity)

    vr = engine.validate_hp_change("HP_VERLUST", "200", None)
    _record(group, "hp_verlust_200_warnung", vr.severity == "warning",
            {"type": "HP_VERLUST", "val": "200"}, "warning", vr.severity)

    vr = engine.validate_hp_change("HP_HEILUNG", "1d6", None)
    _record(group, "hp_heilung_wuerfelausdruck_ok", vr.severity == "ok",
            {"type": "HP_HEILUNG", "val": "1d6"}, "ok", vr.severity)

    # --- validate_xp_gain ---
    vr = engine.validate_xp_gain("200")
    _record(group, "xp_200_gueltig", vr.severity == "ok",
            {"val": "200"}, "ok", vr.severity)

    vr = engine.validate_xp_gain("-50")
    _record(group, "xp_negativ_fehler", vr.severity == "error",
            {"val": "-50"}, "error", vr.severity)

    vr = engine.validate_xp_gain("50000")
    _record(group, "xp_50000_warnung", vr.severity == "warning",
            {"val": "50000"}, "warning", vr.severity)

    # --- validate_probe ---
    skills = {"Move Silently": 35, "Healing": 10}
    vr = engine.validate_probe("Move Silently", 35, skills)
    _record(group, "probe_move_silently_gueltig", vr.severity == "ok",
            {"skill": "Move Silently", "target": 35}, "ok", vr.severity)

    vr = engine.validate_probe("Voellig_Unbekannte_Fertigkeit_XYZ", 15, skills)
    _record(group, "probe_unbekannte_fertigkeit_warnung", vr.severity == "warning",
            {"skill": "XYZ"}, "warning", vr.severity)

    # --- validate_morale_check ---
    vr = engine.validate_morale_check("Goblin | 8")
    _record(group, "morale_check_gueltig", vr.severity == "ok",
            {"val": "Goblin | 8"}, "ok", vr.severity)

    # --- Monster-Validatoren ---
    vr = engine.validate_magic_resistance("Drache | 30")
    _record(group, "magic_resistance_30_gueltig", vr.severity == "ok",
            {"val": "Drache | 30"}, "ok", vr.severity)

    vr = engine.validate_magic_resistance("Drache | 150")
    _record(group, "magic_resistance_150_warnung", vr.severity in ("warning", "error"),
            {"val": "Drache | 150"}, "warning/error", vr.severity)

    vr = engine.validate_weapon_immunity("Geist | +2")
    _record(group, "waffen_immunitaet_plus2_gueltig", vr.severity == "ok",
            {"val": "Geist | +2"}, "ok", vr.severity)

    vr = engine.validate_poison("Schlange | Tod | -2")
    _record(group, "gift_tod_gueltig", vr.severity == "ok",
            {"val": "Schlange | Tod | -2"}, "ok", vr.severity)

    vr = engine.validate_level_drain("Held | 2")
    _record(group, "level_drain_2_gueltig", vr.severity == "ok",
            {"val": "Held | 2"}, "ok", vr.severity)

    vr = engine.validate_regeneration("Troll | 3")
    _record(group, "regeneration_3_gueltig", vr.severity == "ok",
            {"val": "Troll | 3"}, "ok", vr.severity)

    # Dauer muss NdN oder "permanent" sein (nicht "2 Runden")
    vr = engine.validate_fear("Held | Flucht | 1d6")
    _record(group, "furcht_gueltig", vr.severity == "ok",
            {"val": "Held | Flucht | 1d6"}, "ok", vr.severity)

    vr = engine.validate_breath_weapon("Drache | Feuer | 6d8")
    _record(group, "atem_waffe_gueltig", vr.severity == "ok",
            {"val": "Drache | Feuer | 6d8"}, "ok", vr.severity)


# ---------------------------------------------------------------------------
# Gruppe: combat_tracker.* (~18 Tests)
# ---------------------------------------------------------------------------

def test_combat_tracker() -> None:
    from core.combat_tracker import CombatTracker, Combatant
    group = "combat_tracker"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")

    def _make_tracker_with_combatants():
        ct = CombatTracker()
        ct._combatants["player"] = Combatant(
            id="player", name="Held", hp=15, hp_max=15, ac=5,
            thac0=18, weapon="Schwert", damage="1d8",
            movement=12, position="Nahkampf", is_player=True,
            attacks_per_round="1/1",
        )
        ct._combatants["goblin1"] = Combatant(
            id="goblin1", name="Goblin", hp=7, hp_max=7, ac=7,
            thac0=20, weapon="Dolch", damage="1d4",
            movement=6, position="Nahkampf",
            attacks_per_round="1/1",
        )
        return ct

    # apply_damage: reduziert HP
    ct = _make_tracker_with_combatants()
    r = ct.apply_damage("goblin1", 3)
    _record(group, "apply_damage_reduziert_hp",
            r["hp_new"] == 4,
            {"damage": 3, "hp_vorher": 7}, 4, r["hp_new"])

    # apply_damage: toetet bei 0
    ct = _make_tracker_with_combatants()
    r = ct.apply_damage("goblin1", 7)
    _record(group, "apply_damage_toetet_bei_null",
            r["killed"] and not ct._combatants["goblin1"].is_alive,
            {"damage": 7, "hp": 7}, True, r["killed"])

    # apply_damage: HP geht nicht unter 0
    ct = _make_tracker_with_combatants()
    r = ct.apply_damage("goblin1", 100)
    _record(group, "apply_damage_hp_nicht_negativ",
            r["hp_new"] == 0,
            {"damage": 100, "hp": 7}, 0, r["hp_new"])

    # apply_damage auf toten Gegner -> kein Fehler
    ct = _make_tracker_with_combatants()
    ct._combatants["goblin1"].is_alive = False
    r = ct.apply_damage("goblin1", 5)
    _record(group, "apply_damage_toter_gegner_kein_crash",
            r["damage"] == 0,
            {"is_alive": False}, 0, r["damage"])

    # heal: erhoeht HP
    ct = _make_tracker_with_combatants()
    ct._combatants["player"].hp = 8
    r = ct.heal("player", 4)
    _record(group, "heal_erhoeht_hp",
            r["hp_new"] == 12,
            {"hp_vorher": 8, "heilung": 4}, 12, r["hp_new"])

    # heal: kapped bei hp_max
    ct = _make_tracker_with_combatants()
    ct._combatants["player"].hp = 14
    r = ct.heal("player", 10)
    _record(group, "heal_kapped_bei_max",
            r["hp_new"] == 15,
            {"hp_vorher": 14, "heilung": 10, "hp_max": 15}, 15, r["hp_new"])

    # get_max_attacks: 1/1 -> immer 1
    ct = _make_tracker_with_combatants()
    ct._round = 1
    _record(group, "get_max_attacks_1_1_ist_1",
            ct.get_max_attacks("player") == 1,
            {"apr": "1/1", "round": 1}, 1, ct.get_max_attacks("player"))

    # get_max_attacks: 2/1 -> immer 2
    ct = _make_tracker_with_combatants()
    ct._combatants["player"].attacks_per_round = "2/1"
    ct._round = 1
    _record(group, "get_max_attacks_2_1_ist_2",
            ct.get_max_attacks("player") == 2,
            {"apr": "2/1", "round": 1}, 2, ct.get_max_attacks("player"))

    # get_max_attacks: 3/2 -> ungerade Runde=1, gerade=2
    ct = _make_tracker_with_combatants()
    ct._combatants["player"].attacks_per_round = "3/2"
    ct._round = 1
    m1 = ct.get_max_attacks("player")
    ct._round = 2
    m2 = ct.get_max_attacks("player")
    _record(group, "get_max_attacks_3_2_ungerade_1",
            m1 == 1, {"apr": "3/2", "round": 1}, 1, m1)
    _record(group, "get_max_attacks_3_2_gerade_2",
            m2 == 2, {"apr": "3/2", "round": 2}, 2, m2)

    # can_attack: frische Runde -> True
    ct = _make_tracker_with_combatants()
    ct._round = 1
    _record(group, "can_attack_frische_runde",
            ct.can_attack("player"),
            None, True, ct.can_attack("player"))

    # can_attack nach register_attack -> False (bei 1/1)
    ct = _make_tracker_with_combatants()
    ct._round = 1
    ct.register_attack("player")
    _record(group, "can_attack_nach_register_false",
            not ct.can_attack("player"),
            {"apr": "1/1"}, False, ct.can_attack("player"))

    # start_new_round: setzt attacks_this_round auf 0
    ct = _make_tracker_with_combatants()
    ct._round = 0
    ct._active = True
    ct._combatants["player"].attacks_this_round = 2
    mech = _make_mechanics(seed=42)
    ct.start_new_round(mech)
    _record(group, "start_new_round_setzt_angriffe_zurueck",
            ct._combatants["player"].attacks_this_round == 0,
            None, 0, ct._combatants["player"].attacks_this_round)

    # start_new_round: erhoet Rundenzaehler
    ct = _make_tracker_with_combatants()
    ct._round = 0
    ct._active = True
    mech = _make_mechanics(seed=99)
    result = ct.start_new_round(mech)
    _record(group, "start_new_round_erhoet_runde",
            result["round"] == 1,
            None, 1, result["round"])

    # register_regeneration + apply_regeneration
    ct = _make_tracker_with_combatants()
    ct._combatants["goblin1"].hp = 3
    ct.register_regeneration("Goblin", 2)
    msgs = ct.apply_regeneration()
    _record(group, "regeneration_heilt_monster",
            ct._combatants["goblin1"].hp == 5,
            {"hp_vorher": 3, "regen": 2}, 5, ct._combatants["goblin1"].hp)

    # Regeneration kapped bei hp_max
    ct = _make_tracker_with_combatants()
    ct._combatants["goblin1"].hp = 6
    ct.register_regeneration("Goblin", 5)
    ct.apply_regeneration()
    _record(group, "regeneration_kapped_bei_max",
            ct._combatants["goblin1"].hp == 7,
            {"hp_vorher": 6, "regen": 5, "hp_max": 7}, 7, ct._combatants["goblin1"].hp)


# ---------------------------------------------------------------------------
# ============================================================
# MATRIX-TESTS
# ============================================================
# ---------------------------------------------------------------------------

def run_matrix_tests(iterations: int = 1000) -> None:
    """Statistische Tests mit vielen Iterationen."""
    global _run_id

    print(f"\n{BOLD}=== MATRIX-TESTS ({iterations} Iterationen pro Zelle) ==={RESET}")

    # --- attack_roll Matrix ---
    _matrix_attack_roll(iterations)

    # --- saving_throw Matrix ---
    _matrix_saving_throw(iterations)

    # --- morale_check Matrix ---
    _matrix_morale_check(iterations)


def _matrix_attack_roll(iterations: int) -> None:
    group = "matrix.attack_roll"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")
    mech = _make_mechanics()

    # Adaptive Toleranz: ~3% bei 1000 Iter, ~10% bei 100 Iter
    tol = max(0.025, 3.0 / math.sqrt(iterations))

    # THAC0 und AC Kombinationen testen
    thac0_vals = [5, 10, 15, 20]

    # Monotonie pruefen: hoehere THAC0 -> niedrigere Trefferrate
    prev_hit_rate = None
    prev_thac0 = None
    for thac0 in thac0_vals:
        hits = 0
        nat20s = 0
        nat1s = 0
        for _ in range(iterations):
            r = mech.attack_roll(thac0=thac0, target_ac=5)
            if r.is_success:
                hits += 1
            if r.roll == 20:
                nat20s += 1
            if r.roll == 1:
                nat1s += 1

        hit_rate = hits / iterations
        nat20_rate = nat20s / iterations
        nat1_rate = nat1s / iterations

        _record_matrix_cell(group, f"thac0_{thac0}_ac5_hits",
                            iterations, hits, iterations - hits, [hit_rate])

        _record(group, f"thac0_{thac0}_ac5_hit_rate_gueltig_bereich",
                0.0 <= hit_rate <= 1.0,
                {"thac0": thac0, "ac": 5, "iterations": iterations},
                "0.0-1.0", round(hit_rate, 3))

        # nat20 ca. 5% (adaptive Toleranz)
        _record(group, f"thac0_{thac0}_nat20_rate_circa_5pct",
                abs(nat20_rate - 0.05) < tol,
                {"expected": "~5%", "actual": f"{nat20_rate:.1%}", "tol": f"{tol:.1%}"},
                "~5%", f"{nat20_rate:.1%}")

        # nat1 ca. 5% (adaptive Toleranz)
        _record(group, f"thac0_{thac0}_nat1_rate_circa_5pct",
                abs(nat1_rate - 0.05) < tol,
                {"expected": "~5%", "actual": f"{nat1_rate:.1%}", "tol": f"{tol:.1%}"},
                "~5%", f"{nat1_rate:.1%}")

        # Monotonie: hoehere THAC0 -> nicht hoehere Trefferrate
        if prev_hit_rate is not None:
            _record(group, f"monotonie_thac0_{prev_thac0}_zu_{thac0}",
                    hit_rate <= prev_hit_rate + 0.03,
                    {"prev_rate": round(prev_hit_rate, 3), "curr_rate": round(hit_rate, 3)},
                    "<=", round(hit_rate, 3))
        prev_hit_rate = hit_rate
        prev_thac0 = thac0


def _matrix_saving_throw(iterations: int) -> None:
    group = "matrix.saving_throw"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")
    mech = _make_mechanics()

    tol = max(0.025, 3.0 / math.sqrt(iterations))
    targets = [5, 10, 15, 18]
    prev_save_rate = None
    prev_target = None

    for target in targets:
        saves = 0
        nat20s = 0
        for _ in range(iterations):
            r = mech.saving_throw(target=target)
            if r.is_success:
                saves += 1
            if r.roll == 20:
                nat20s += 1

        save_rate = saves / iterations
        nat20_rate = nat20s / iterations

        _record_matrix_cell(group, f"target_{target}_saves",
                            iterations, saves, iterations - saves, [save_rate])

        _record(group, f"target_{target}_save_rate_gueltig",
                0.0 <= save_rate <= 1.0,
                {"target": target, "iterations": iterations}, "0.0-1.0", round(save_rate, 3))

        _record(group, f"target_{target}_nat20_circa_5pct",
                abs(nat20_rate - 0.05) < tol,
                {"expected": "~5%", "actual": f"{nat20_rate:.1%}", "tol": f"{tol:.1%}"},
                "~5%", f"{nat20_rate:.1%}")

        # Hoehere Targets -> niedrigere Save-Rate
        if prev_save_rate is not None:
            _record(group, f"monotonie_target_{prev_target}_zu_{target}",
                    save_rate <= prev_save_rate + 0.03,
                    {"prev": round(prev_save_rate, 3), "curr": round(save_rate, 3)},
                    "<=", round(save_rate, 3))
        prev_save_rate = save_rate
        prev_target = target


def _matrix_morale_check(iterations: int) -> None:
    group = "matrix.morale_check"
    print(f"\n{BOLD}{CYAN}[{group}]{RESET}")
    mech = _make_mechanics()

    morale_vals = [4, 8, 12, 16]
    prev_pass_rate = None
    prev_morale = None

    for morale in morale_vals:
        passes = 0
        for _ in range(iterations):
            r = mech.morale_check(morale_value=morale)
            if r.is_success:
                passes += 1

        pass_rate = passes / iterations

        _record_matrix_cell(group, f"morale_{morale}_passes",
                            iterations, passes, iterations - passes, [pass_rate])

        _record(group, f"morale_{morale}_pass_rate_gueltig",
                0.0 <= pass_rate <= 1.0,
                {"morale": morale, "iterations": iterations}, "0.0-1.0", round(pass_rate, 3))

        # Hoehere Moral -> hoehere Pass-Rate
        if prev_pass_rate is not None:
            _record(group, f"monotonie_morale_{prev_morale}_zu_{morale}",
                    pass_rate >= prev_pass_rate - 0.03,
                    {"prev": round(prev_pass_rate, 3), "curr": round(pass_rate, 3)},
                    ">=", round(pass_rate, 3))
        prev_pass_rate = pass_rate
        prev_morale = morale


# ---------------------------------------------------------------------------
# ============================================================
# SCENARIO-TESTS
# ============================================================
# ---------------------------------------------------------------------------

def run_scenario_tests() -> None:
    """Laedt und verarbeitet Szenario-JSON-Dateien aus data/test_scenarios/."""
    global _run_id
    print(f"\n{BOLD}=== SCENARIO-TESTS ==={RESET}")

    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    scenario_files = list(SCENARIOS_DIR.glob("*.json"))

    if not scenario_files:
        print(f"  {YELLOW}Keine Szenario-Dateien in {SCENARIOS_DIR}{RESET}")
        print(f"  {YELLOW}Erstelle Beispiel-Szenario...{RESET}")
        _create_example_scenario()
        scenario_files = list(SCENARIOS_DIR.glob("*.json"))

    for sf in sorted(scenario_files):
        _run_single_scenario(sf)


def _create_example_scenario() -> None:
    """Erstellt ein Beispiel-Szenario fuer Tests."""
    example = {
        "id": "scenario_basic_combat",
        "name": "Grundlegender Kampf-Test",
        "setup": {
            "player": {
                "name": "Testheldin",
                "hp": 15, "ac": 5, "thac0": 18,
                "weapon": "Schwert", "damage": "1d8",
            },
            "seed": 42,
        },
        "steps": [
            {
                "synthetic_response": "Der Goblin greift an! [HP_VERLUST: 3] Du verlierst 3 TP.",
                "assertions": [
                    {"type": "tag_extracted", "tag": "HP_VERLUST", "count": 1},
                    {"type": "stat_changed", "stat": "HP", "expected_value": 12},
                ]
            },
            {
                "synthetic_response": "Du findest einen Heiltrank. [INVENTAR: Heiltrank | gefunden]",
                "assertions": [
                    {"type": "tag_not_present", "tag": "HP_VERLUST"},
                ]
            },
            {
                "synthetic_response": "Guter Angriff! [XP_GEWINN: 50]",
                "assertions": [
                    {"type": "tag_extracted", "tag": "XP_GEWINN", "count": 1},
                ]
            },
        ]
    }
    out_path = SCENARIOS_DIR / "example_basic_combat.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(example, f, ensure_ascii=False, indent=2)
    print(f"  Beispiel-Szenario erstellt: {out_path}")


def _run_single_scenario(scenario_path: Path) -> None:
    from core.character import (
        extract_stat_changes, extract_combat_tags, extract_inventory_changes,
    )
    global _run_id

    with scenario_path.open(encoding="utf-8") as f:
        scenario = json.load(f)

    name = scenario.get("name", scenario_path.stem)
    steps = scenario.get("steps", [])
    setup = scenario.get("setup", {})

    print(f"\n  {BOLD}Szenario: {name}{RESET}")

    # Zustandsverfolgung
    hp_max = setup.get("player", {}).get("hp", 15)
    state = {"HP": hp_max, "XP": 0}

    total_steps = len(steps)
    passed_steps = 0
    failed_steps = 0

    for i, step in enumerate(steps):
        text = step.get("synthetic_response", "")
        assertions = step.get("assertions", [])

        # Tags extrahieren
        stat_changes = extract_stat_changes(text)
        combat_tags = extract_combat_tags(text)
        inventory = extract_inventory_changes(text)

        # Zustand anwenden
        for change in stat_changes:
            tag_type = change[0]
            if tag_type == "HP_VERLUST":
                try:
                    state["HP"] = max(0, state["HP"] - int(change[1]))
                except (ValueError, IndexError):
                    pass
            elif tag_type == "HP_HEILUNG":
                try:
                    val = change[1]
                    if val.isdigit():
                        state["HP"] = min(hp_max, state["HP"] + int(val))
                except (ValueError, IndexError):
                    pass
            elif tag_type == "XP_GEWINN":
                try:
                    state["XP"] += int(change[1])
                except (ValueError, IndexError):
                    pass

        # Assertions pruefen
        for assertion in assertions:
            atype = assertion.get("type")
            step_name = f"{scenario_path.stem}_step{i+1}_{atype}"
            passed = False
            msg = ""

            if atype == "tag_extracted":
                tag = assertion.get("tag", "")
                expected_count = assertion.get("count", 1)
                actual_count = sum(1 for c in stat_changes if c[0] == tag)
                actual_count += sum(1 for c in combat_tags if c[0] == tag)
                passed = actual_count >= expected_count
                msg = f"Tag {tag}: erwartet >={expected_count}, tatsaechlich {actual_count}"

            elif atype == "tag_not_present":
                tag = assertion.get("tag", "")
                found = any(c[0] == tag for c in stat_changes) or \
                        any(c[0] == tag for c in combat_tags)
                passed = not found
                msg = f"Tag {tag} sollte NICHT vorhanden sein: {'gefunden' if found else 'korrekt nicht gefunden'}"

            elif atype == "stat_changed":
                stat = assertion.get("stat", "HP")
                expected = assertion.get("expected_value")
                actual = state.get(stat)
                passed = actual == expected
                msg = f"Stat {stat}: erwartet {expected}, tatsaechlich {actual}"

            elif atype == "validation_passes":
                engine = _make_rules_engine()
                # Monster-Tags haben 3-4 Felder; Validator erwartet
                # (typ, "Feld1 | Feld2 | ...") als Pipe-String
                sc = [(c[0], " | ".join(c[1:])) if len(c) > 2
                      else (c[0], c[1] if len(c) > 1 else "")
                      for c in stat_changes]
                results = engine.validate_tags(
                    stat_changes=sc,
                    combat_tags=combat_tags,
                )
                errors = [r for r in results if r.severity == "error"]
                passed = len(errors) == 0
                msg = f"Validierung: {len(errors)} Fehler"

            elif atype == "validation_warns":
                engine = _make_rules_engine()
                sc = [(c[0], " | ".join(c[1:])) if len(c) > 2
                      else (c[0], c[1] if len(c) > 1 else "")
                      for c in stat_changes]
                results = engine.validate_tags(
                    stat_changes=sc,
                    combat_tags=combat_tags,
                )
                warnings = [r for r in results if r.severity == "warning"]
                passed = len(warnings) > 0
                msg = f"Validierung: {len(warnings)} Warnungen"

            if passed:
                passed_steps += 1
            else:
                failed_steps += 1

            _record(f"scenario.{scenario_path.stem}", step_name, passed,
                    {"step": i+1, "assertion": atype}, None, None, msg)

    # Szenario-Ergebnis in DB speichern
    db = _get_db()
    db.execute(
        """INSERT INTO scenario_results
           (run_id, scenario_file, scenario_name, total_steps, passed_steps,
            failed_steps, final_state)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (_run_id, scenario_path.name, name, total_steps, passed_steps,
         failed_steps, json.dumps(state)),
    )
    db.commit()


# ---------------------------------------------------------------------------
# ============================================================
# HAUPT-RUN-LOGIK
# ============================================================
# ---------------------------------------------------------------------------

def run_unit_tests(group_filter: str | None = None) -> None:
    mech = _make_mechanics(seed=_seed)

    all_groups = [
        ("mechanics.attack_roll",     lambda: test_attack_roll(mech)),
        ("mechanics.saving_throw",    lambda: test_saving_throw(mech)),
        ("mechanics.morale_check",    lambda: test_morale_check(mech)),
        ("mechanics.reaction_roll",   lambda: test_reaction_roll(mech)),
        ("mechanics.turn_undead",     lambda: test_turn_undead(mech)),
        ("mechanics.roll_treasure",   lambda: test_roll_treasure(mech)),
        ("mechanics.roll_expression", lambda: test_roll_expression(mech)),
        ("mechanics.skill_check",     lambda: test_skill_check(mech)),
        ("mechanics.lookup_thac0",    lambda: test_lookup_thac0(mech)),
        ("mechanics.lookup_saving_throw", lambda: test_lookup_saving_throw(mech)),
        ("mechanics.initiative_roll", lambda: test_initiative_roll(mech)),
        ("mechanics.encumbrance",     lambda: test_encumbrance(mech)),
        ("tag_parser.extract_stat_changes", test_extract_stat_changes),
        ("tag_parser.extract_combat_tags",  test_extract_combat_tags),
        ("tag_parser.extract_party",        test_extract_party_tags),
        ("validation",                      test_validation),
        ("combat_tracker",                  test_combat_tracker),
    ]

    print(f"\n{BOLD}=== UNIT-TESTS ==={RESET}")
    for gname, gfunc in all_groups:
        if group_filter and group_filter.lower() not in gname.lower():
            continue
        try:
            gfunc()
        except Exception as exc:
            print(f"  {RED}[FEHLER] Gruppe {gname}: {exc}{RESET}")
            _record(gname, f"__gruppe_crash__", False,
                    None, None, None, str(exc), status="error")


def cmd_run(args) -> None:
    global _run_id, _seed, _results

    _seed = args.seed
    _results = []

    mode_parts = []
    if args.unit:
        mode_parts.append("unit")
    if args.scenario:
        mode_parts.append("scenario")
    if args.matrix:
        mode_parts.append("matrix")
    if args.all or not mode_parts:
        mode_parts = ["all"]

    mode = "+".join(mode_parts)
    _run_id = _start_run(mode)
    started = time.time()

    print(f"\n{BOLD}ARS Regelwerk-Tester{RESET} | Modus: {mode} | Seed: {_seed} | Run-ID: {_run_id}")
    print(f"Git: {_get_git_commit()} | Host: {socket.gethostname()}")

    try:
        if args.all or args.unit or not (args.unit or args.scenario or args.matrix):
            run_unit_tests(group_filter=args.group)

        if args.all or args.scenario or not (args.unit or args.scenario or args.matrix):
            run_scenario_tests()

        if args.all or args.matrix or not (args.unit or args.scenario or args.matrix):
            run_matrix_tests(iterations=getattr(args, "matrix_iterations", 1000))

    except KeyboardInterrupt:
        print(f"\n{YELLOW}Abgebrochen.{RESET}")

    # Zusammenfassung
    total = len(_results)
    passed = sum(1 for r in _results if r["status"] == "pass")
    failed = sum(1 for r in _results if r["status"] == "fail")
    errors = sum(1 for r in _results if r["status"] == "error")

    _finish_run(_run_id, total, passed, failed, errors, started)

    print(f"\n{'='*60}")
    print(f"{BOLD}ERGEBNIS:{RESET}  "
          f"{GREEN}{passed} OK{RESET}  "
          f"{RED}{failed} Fehl{RESET}  "
          f"{YELLOW}{errors} Fehler{RESET}  "
          f"| {total} Tests gesamt")
    print(f"Dauer: {time.time()-started:.1f}s | Run-ID: {_run_id}")

    if failed > 0 or errors > 0:
        sys.exit(1)


# ---------------------------------------------------------------------------
# STATUS / REPORT / TRENDS
# ---------------------------------------------------------------------------

def cmd_status(args) -> None:
    db = _get_db()
    last_n = getattr(args, "last", 10)
    rows = db.execute(
        "SELECT * FROM test_runs ORDER BY started_at DESC LIMIT ?", (last_n,)
    ).fetchall()

    if not rows:
        print("Keine Testlaeufe in der DB.")
        return

    print(f"\n{'Run':>4}  {'Modus':<12}  {'Gestartet':<22}  "
          f"{'OK':>5}  {'Fehl':>5}  {'Err':>4}  {'Dauer':>7}  {'Commit':<8}")
    print("-" * 80)
    for row in rows:
        dur = f"{row['duration_sec']:.1f}s" if row["duration_sec"] else "---"
        ok_col = GREEN + str(row["passed"] or 0) + RESET
        fail_col = RED + str(row["failed"] or 0) + RESET
        err_col = YELLOW + str(row["errors"] or 0) + RESET
        started = (row["started_at"] or "")[:19].replace("T", " ")
        print(f"  {row['id']:>4}  {(row['run_mode'] or ''):<12}  {started:<22}  "
              f"{ok_col:>14}  {fail_col:>13}  {err_col:>12}  {dur:>7}  "
              f"{(row['git_commit'] or 'n/a'):<8}")


def cmd_report(args) -> None:
    db = _get_db()
    run_id = args.run_id
    failures_only = getattr(args, "failures", False)

    run = db.execute("SELECT * FROM test_runs WHERE id=?", (run_id,)).fetchone()
    if not run:
        print(f"Run {run_id} nicht gefunden.")
        return

    started = (run["started_at"] or "")[:19].replace("T", " ")
    print(f"\n{BOLD}Run {run_id}: {run['run_mode']} @ {started}{RESET}")
    print(f"OK: {run['passed']}  Fehl: {run['failed']}  Err: {run['errors']}  "
          f"Gesamt: {run['total_tests']}  Dauer: {run['duration_sec']:.1f}s")

    where = "WHERE run_id=?"
    params: list = [run_id]
    if failures_only:
        where += " AND status IN ('fail','error')"

    rows = db.execute(
        f"SELECT * FROM test_results {where} ORDER BY test_group, test_name",
        params,
    ).fetchall()

    current_group = None
    for row in rows:
        if row["test_group"] != current_group:
            current_group = row["test_group"]
            print(f"\n  {BOLD}{CYAN}[{current_group}]{RESET}")

        status = row["status"]
        if status == "pass":
            icon = f"{GREEN}OK{RESET}"
        elif status == "fail":
            icon = f"{RED}FEHL{RESET}"
        else:
            icon = f"{YELLOW}ERR{RESET}"

        msg = row["message"] or ""
        suffix = f"  -- {msg}" if msg else ""
        print(f"    [{icon}] {row['test_name']}{suffix}")


def cmd_trends(args) -> None:
    db = _get_db()
    days = getattr(args, "days", 7)
    regressions = getattr(args, "regressions", False)

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Pass-Rate pro Gruppe
    rows = db.execute(
        """SELECT r.test_group,
                  COUNT(*) as total,
                  SUM(CASE WHEN r.status='pass' THEN 1 ELSE 0 END) as passed
           FROM test_results r
           JOIN test_runs tr ON r.run_id = tr.id
           WHERE tr.started_at >= ?
           GROUP BY r.test_group
           ORDER BY r.test_group""",
        (since,),
    ).fetchall()

    print(f"\n{BOLD}Pass-Rate pro Gruppe (letzte {days} Tage):{RESET}")
    print(f"{'Gruppe':<40}  {'OK':>6}  {'Gesamt':>7}  {'Rate':>7}")
    print("-" * 60)
    for row in rows:
        rate = row["passed"] / row["total"] * 100 if row["total"] else 0
        color = GREEN if rate >= 90 else (YELLOW if rate >= 70 else RED)
        print(f"  {row['test_group']:<40}  {row['passed']:>6}  {row['total']:>7}  "
              f"{color}{rate:>6.1f}%{RESET}")

    if regressions:
        print(f"\n{BOLD}Regressionen (letzte 2 Laeufe):{RESET}")
        # Letzten 2 Runs holen
        runs = db.execute(
            "SELECT id FROM test_runs ORDER BY started_at DESC LIMIT 2"
        ).fetchall()
        if len(runs) < 2:
            print("  Zu wenige Laeufe fuer Regressionsanalyse.")
            return

        latest_id = runs[0]["id"]
        prev_id = runs[1]["id"]

        # Tests die vorher pass, jetzt fail
        regressions_rows = db.execute(
            """SELECT r1.test_group, r1.test_name,
                      r1.status as now_status, r2.status as prev_status
               FROM test_results r1
               JOIN test_results r2
                 ON r1.test_group = r2.test_group AND r1.test_name = r2.test_name
               WHERE r1.run_id=? AND r2.run_id=?
                 AND r2.status='pass' AND r1.status IN ('fail','error')""",
            (latest_id, prev_id),
        ).fetchall()

        if not regressions_rows:
            print(f"  {GREEN}Keine Regressionen gefunden.{RESET}")
        else:
            for row in regressions_rows:
                print(f"  {RED}REGRESSION{RESET}: {row['test_group']}.{row['test_name']} "
                      f"(vorher: {row['prev_status']}, jetzt: {row['now_status']})")


# ---------------------------------------------------------------------------
# CLI Einstiegspunkt
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARS Regelwerk-Tester (deterministisch, kein KI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  py -3 scripts/rules_tester.py run --unit
  py -3 scripts/rules_tester.py run --all --seed 123
  py -3 scripts/rules_tester.py run --matrix --matrix-iterations 2000
  py -3 scripts/rules_tester.py run --unit --group attack_roll
  py -3 scripts/rules_tester.py status --last 5
  py -3 scripts/rules_tester.py report --run-id 3 --failures
  py -3 scripts/rules_tester.py trends --days 14 --regressions
        """,
    )

    sub = parser.add_subparsers(dest="command")

    # run
    run_p = sub.add_parser("run", help="Tests ausfuehren")
    run_p.add_argument("--unit",     action="store_true", help="Nur Unit-Tests")
    run_p.add_argument("--scenario", action="store_true", help="Nur Szenario-Tests")
    run_p.add_argument("--matrix",   action="store_true", help="Nur Matrix-Tests")
    run_p.add_argument("--all",      action="store_true", help="Alle Tests (Standard)")
    run_p.add_argument("--group",    type=str, default=None,
                       help="Nur Gruppen die diesen String enthalten")
    run_p.add_argument("--seed",     type=int, default=42, help="Zufallsseed (Standard: 42)")
    run_p.add_argument("--matrix-iterations", type=int, default=1000,
                       dest="matrix_iterations",
                       help="Iterationen pro Matrix-Zelle (Standard: 1000)")

    # status
    status_p = sub.add_parser("status", help="Letzten N Testlaeufe anzeigen")
    status_p.add_argument("--last", type=int, default=10, help="Anzahl Laeufe (Standard: 10)")

    # report
    report_p = sub.add_parser("report", help="Details eines Testlaufs anzeigen")
    report_p.add_argument("--run-id",  type=int, required=True, dest="run_id")
    report_p.add_argument("--failures", action="store_true", help="Nur Fehlschlaege")

    # trends
    trends_p = sub.add_parser("trends", help="Trend-Analyse ueber mehrere Laeufe")
    trends_p.add_argument("--days",        type=int, default=7,
                          help="Zeitfenster in Tagen (Standard: 7)")
    trends_p.add_argument("--regressions", action="store_true",
                          help="Regressionen seit letztem Lauf anzeigen")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "trends":
        cmd_trends(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
