"""
core/character.py — Charakter-Persistenz & Zustandsverwaltung

Verwaltet:
  - Laden/Speichern des Investigator-Zustands (HP, SAN, MP, Skills) in SQLite
  - update_stat(): sofortige DB-Persistierung bei Zustandsaenderungen
  - mark_skill_used(): Steigerungs-Markierung fuer Fertigkeiten (CoC 7e)
  - Session-Logging: Turns in session_turns-Tabelle speichern

Tag-Protokoll (GM -> Engine):
  [HP_VERLUST: 3]              → 3 Trefferpunkte abziehen
  [STABILITAET_VERLUST: 1d6]  → 1d6 wuerfeln, von SAN abziehen
  [FERTIGKEIT_GENUTZT: Name]  → Fertigkeit fuer Steigerungsphase markieren
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("ARS.character")

DB_PATH = Path(__file__).parent.parent / "data" / "ars_vault.sqlite"

# ── Tag-Parser ────────────────────────────────────────────────────────────────

HP_LOSS_PATTERN = re.compile(r"\[HP_VERLUST:\s*(\d+)\s*\]", re.IGNORECASE)
HP_HEAL_PATTERN = re.compile(r"\[HP_HEILUNG:\s*(\d+d\d+|\d+)\s*\]", re.IGNORECASE)
SAN_LOSS_PATTERN = re.compile(
    r"\[STABILITAET_VERLUST:\s*(\d+d\d+|\d+)\s*\]", re.IGNORECASE
)
XP_GAIN_PATTERN = re.compile(r"\[XP_GEWINN:\s*(\d+)\s*\]", re.IGNORECASE)
SKILL_USED_PATTERN = re.compile(r"\[FERTIGKEIT_GENUTZT:\s*([^\]]+)\s*\]", re.IGNORECASE)


def extract_stat_changes(text: str) -> list[tuple[str, str]]:
    """
    Parst alle Zustandsaenderungs-Tags aus dem GM-Text.
    Returns list of (tag_type, value_str) tuples.
      tag_type: "HP_VERLUST" | "HP_HEILUNG" | "STABILITAET_VERLUST"
              | "XP_GEWINN" | "FERTIGKEIT_GENUTZT"
    """
    results: list[tuple[str, str]] = []
    for m in HP_LOSS_PATTERN.finditer(text):
        results.append(("HP_VERLUST", m.group(1)))
    for m in HP_HEAL_PATTERN.finditer(text):
        results.append(("HP_HEILUNG", m.group(1)))
    for m in SAN_LOSS_PATTERN.finditer(text):
        results.append(("STABILITAET_VERLUST", m.group(1)))
    for m in XP_GAIN_PATTERN.finditer(text):
        results.append(("XP_GEWINN", m.group(1)))
    for m in SKILL_USED_PATTERN.finditer(text):
        results.append(("FERTIGKEIT_GENUTZT", m.group(1).strip()))
    return results


# ── CharacterManager ──────────────────────────────────────────────────────────


class CharacterManager:
    """
    Laedt und persistiert den Spielercharakter (Investigator) in der SQLite-Datenbank.

    Oeffentliche API:
      connect()                        DB-Verbindung oeffnen, Schema sichern
      load_latest() -> bool            Letzten Charakter fuer dieses Modul laden
      update_stat(name, change) -> dict Sofort in DB schreiben, Ergebnis zurueckgeben
      mark_skill_used(name)            Steigerungs-Markierung setzen
      save()                           Persistiert aktuellen Zustand
      start_session() -> int           Neue Session-Zeile anlegen, ID zurueck
      log_turn(sid, turn, input, resp) Turn + Charakter-Snapshot speichern
      status_line() -> str             Kompakte HP/SAN/MP-Anzeige
    """

    def __init__(
        self,
        ruleset: dict[str, Any],
        template: dict[str, Any] | None = None,
    ) -> None:
        self.ruleset = ruleset
        self._template = template
        self._module: str = ruleset["metadata"]["system"]
        self._char_id: int | None = None
        self._name: str = ruleset.get("metadata", {}).get("player_character_title", "Charakter")
        self._archetype: str = ""
        self._level: int = 1
        self._background: str = ""
        self._traits: str = ""
        self._appearance: str = ""
        self._equipment: list[str] = []
        self._characteristics: dict[str, int] = {}
        self._stats: dict[str, int] = {}
        self._stats_max: dict[str, int] = {}
        self._skills: dict[str, int] = {}
        self._skills_used: set[str] = set()
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Oeffnet die DB-Verbindung und stellt sicher dass das Schema existiert."""
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def load_latest(self) -> bool:
        """
        Laedt den zuletzt gespeicherten Charakter fuer dieses Modul.
        Returns True wenn ein Charakter gefunden und geladen wurde,
                False wenn ein neuer Standardcharakter erstellt wurde.
        """
        if not self._conn:
            self.connect()

        cur = self._conn.execute(
            "SELECT * FROM characters WHERE module = ? ORDER BY last_saved DESC LIMIT 1",
            (self._module,),
        )
        row = cur.fetchone()

        if row is None:
            logger.info(
                "Kein Charakter fuer Modul '%s' — erstelle Standardcharakter.",
                self._module,
            )
            self._create_default_character()
            return False

        self._char_id = row["id"]
        self._name = row["name"]
        self._stats = json.loads(row["stats_current"])
        self._stats_max = json.loads(row["stats_max"])
        self._skills = json.loads(row["skills"])
        self._skills_used = set(json.loads(row["skills_used"]))

        logger.info(
            "Charakter geladen: %s (ID=%d) | HP: %d/%d | SAN: %d/%d",
            self._name,
            self._char_id,
            self._stats.get("HP", 0),
            self._stats_max.get("HP", 0),
            self._stats.get("SAN", 0),
            self._stats_max.get("SAN", 0),
        )
        return True

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    def update_stat(self, stat_name: str, change_value: int) -> dict[str, Any]:
        """
        Aendert einen abgeleiteten Wert (HP, SAN, MP) und persistiert sofort in die DB.

        Args:
            stat_name:    Stat-Schluessel, z.B. "HP", "SAN", "MP" (case-insensitive)
            change_value: Negativer Wert = Verlust, Positiver = Gewinn

        Returns:
            Dict mit stat_name, old_value, new_value, change, max_value
        """
        key = stat_name.upper()
        if key not in self._stats:
            logger.warning("Unbekannter Stat '%s' — ignoriert.", stat_name)
            return {"stat_name": key, "error": "unknown_stat"}

        old_val = self._stats[key]
        max_val = self._stats_max.get(key, old_val)
        new_val = max(0, min(old_val + change_value, max_val))
        self._stats[key] = new_val
        self.save()

        logger.info(
            "Stat '%s': %d -> %d (Aenderung: %+d, Max: %d)",
            key, old_val, new_val, change_value, max_val,
        )
        return {
            "stat_name": key,
            "old_value": old_val,
            "new_value": new_val,
            "change": change_value,
            "max_value": max_val,
        }

    def mark_skill_used(self, skill_name: str) -> None:
        """
        Markiert eine Fertigkeit fuer die Steigerungsphase am Ende des Abenteuers.
        (CoC 7e: Bei Nutzung + Erfolg kann nach dem Abenteuer auf Steigerung gewuerfelt werden.)
        Fuehrt einen Fuzzy-Match durch (case-insensitive).
        """
        for existing in self._skills:
            if existing.lower() == skill_name.lower():
                self._skills_used.add(existing)
                self.save()
                logger.info("Fertigkeit '%s' als genutzt markiert.", existing)
                return
        logger.warning(
            "Fertigkeit '%s' nicht im Ruleset gefunden — nicht markiert.", skill_name
        )

    def save(self) -> None:
        """Persistiert den aktuellen Charakter-Zustand sofort in der DB."""
        if not self._conn:
            return

        now = datetime.now(timezone.utc).isoformat()

        if self._char_id is None:
            cur = self._conn.execute(
                """INSERT INTO characters
                   (name, module, stats_current, stats_max, skills, skills_used,
                    created_at, last_saved)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._name,
                    self._module,
                    json.dumps(self._stats),
                    json.dumps(self._stats_max),
                    json.dumps(self._skills),
                    json.dumps(list(self._skills_used)),
                    now,
                    now,
                ),
            )
            self._char_id = cur.lastrowid
            self._conn.commit()
            logger.debug("Charakter neu erstellt (ID=%d).", self._char_id)
        else:
            self._conn.execute(
                """UPDATE characters SET
                   stats_current = ?, stats_max = ?, skills = ?,
                   skills_used = ?, last_saved = ?
                   WHERE id = ?""",
                (
                    json.dumps(self._stats),
                    json.dumps(self._stats_max),
                    json.dumps(self._skills),
                    json.dumps(list(self._skills_used)),
                    now,
                    self._char_id,
                ),
            )
            self._conn.commit()
            logger.debug("Charakter gespeichert (ID=%d).", self._char_id)

    def start_session(self) -> int:
        """
        Legt eine neue Session-Zeile in der DB an.
        Returns die neue Session-ID (0 wenn DB nicht verbunden).
        """
        if not self._conn:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """INSERT INTO sessions (module, character_id, started_at, last_active)
               VALUES (?, ?, ?, ?)""",
            (self._module, self._char_id, now, now),
        )
        self._conn.commit()
        session_id = cur.lastrowid
        logger.info("Session in DB angelegt (ID=%d).", session_id)
        return session_id

    def log_turn(
        self,
        session_id: int,
        turn_number: int,
        user_input: str,
        gm_response: str,
    ) -> None:
        """
        Speichert einen vollstaendigen Turn in session_turns inkl. Charakter-Snapshot.
        Aktualisiert auch last_active der Session.
        """
        if not self._conn or session_id == 0:
            return

        now = datetime.now(timezone.utc).isoformat()
        snapshot = json.dumps({"stats": self._stats, "stats_max": self._stats_max})

        # Kompatibilitaet mit Task-01-Schema (turn_index, role, content NOT NULL)
        self._conn.execute(
            """INSERT INTO session_turns
               (session_id, turn_index, turn_number, role, content,
                user_input, gm_response, char_snapshot, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, turn_number, turn_number, "user",
             user_input, user_input, gm_response, snapshot, now),
        )
        self._conn.execute(
            "UPDATE sessions SET last_active = ? WHERE id = ?",
            (now, session_id),
        )
        self._conn.commit()

    def get_conn(self) -> sqlite3.Connection | None:
        """Gibt die interne DB-Verbindung zurueck (fuer Archivist-Sharing)."""
        return self._conn

    # ------------------------------------------------------------------
    # Status-Anzeige
    # ------------------------------------------------------------------

    def status_line(self) -> str:
        """Kurze Statuszeile: 'HP: 13/13 | SAN: 65/65 | MP: 13/13'."""
        parts = []
        for key in ("HP", "SAN", "MP"):
            if key in self._stats:
                parts.append(f"{key}: {self._stats[key]}/{self._stats_max.get(key, '?')}")
        if self._skills_used:
            parts.append(f"Fertigkeiten markiert: {len(self._skills_used)}")
        return " | ".join(parts) if parts else ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    @property
    def is_dead(self) -> bool:
        return self._stats.get("HP", 1) <= 0

    @property
    def is_insane(self) -> bool:
        return self._stats.get("SAN", 1) <= 0

    # ------------------------------------------------------------------
    # Private Helfer
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Erstellt Tabellen falls noch nicht vorhanden; migriert fehlende Spalten."""
        # Pruefe ob characters-Tabelle mit der alten Task-01-Schema existiert
        # (session_id NOT NULL — inkompatibel mit session-unabhaengigem Design)
        self._migrate_characters_if_needed()

        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS characters (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL DEFAULT 'Investigator',
                module        TEXT    NOT NULL,
                stats_current TEXT    NOT NULL DEFAULT '{}',
                stats_max     TEXT    NOT NULL DEFAULT '{}',
                skills        TEXT    NOT NULL DEFAULT '{}',
                skills_used   TEXT    NOT NULL DEFAULT '[]',
                created_at    TEXT    NOT NULL DEFAULT '',
                last_saved    TEXT    NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                module       TEXT    NOT NULL,
                character_id INTEGER,
                started_at   TEXT    NOT NULL DEFAULT '',
                last_active  TEXT    NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS session_turns (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    INTEGER NOT NULL,
                turn_number   INTEGER NOT NULL DEFAULT 0,
                user_input    TEXT    NOT NULL DEFAULT '',
                gm_response   TEXT    NOT NULL DEFAULT '',
                char_snapshot TEXT    NOT NULL DEFAULT '{}',
                created_at    TEXT    NOT NULL DEFAULT ''
            );
        """)
        self._conn.commit()

        # Migrations fuer bestehende DBs aus Task 01 (optionale Spalten hinzufuegen)
        _migrations = [
            ("characters", "stats_current", "TEXT NOT NULL DEFAULT '{}'"),
            ("characters", "stats_max",     "TEXT NOT NULL DEFAULT '{}'"),
            ("characters", "skills",        "TEXT NOT NULL DEFAULT '{}'"),
            ("characters", "skills_used",   "TEXT NOT NULL DEFAULT '[]'"),
            ("characters", "created_at",    "TEXT NOT NULL DEFAULT ''"),
            ("characters", "last_saved",    "TEXT NOT NULL DEFAULT ''"),
            ("sessions",   "character_id",  "INTEGER"),
            ("sessions",   "last_active",   "TEXT NOT NULL DEFAULT ''"),
            ("session_turns", "turn_number",   "INTEGER NOT NULL DEFAULT 0"),
            ("session_turns", "user_input",    "TEXT NOT NULL DEFAULT ''"),
            ("session_turns", "gm_response",   "TEXT NOT NULL DEFAULT ''"),
            ("session_turns", "char_snapshot", "TEXT NOT NULL DEFAULT '{}'"),
            ("session_turns", "created_at",    "TEXT NOT NULL DEFAULT ''"),
        ]
        for table, col, defn in _migrations:
            try:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
                self._conn.commit()
                logger.debug("Migration: %s.%s hinzugefuegt.", table, col)
            except sqlite3.OperationalError:
                pass  # Spalte existiert bereits

    def _migrate_characters_if_needed(self) -> None:
        """
        Erkennt die alte Task-01-Schema (characters.session_id NOT NULL) und
        migriert auf das neue session-unabhaengige Schema.
        Bestehende Zeilen werden uebernommen; das Backup bleibt als
        _characters_task01_backup erhalten.
        """
        cur = self._conn.execute("PRAGMA table_info(characters)")
        cols = {row[1]: row[3] for row in cur}  # name -> notnull (1=NOT NULL)

        if "session_id" not in cols:
            return  # Tabelle existiert noch nicht oder hat bereits neues Schema
        if cols["session_id"] != 1:
            return  # session_id ist nullable — kein Problem

        logger.info(
            "characters-Tabelle hat Task-01-Schema (session_id NOT NULL) "
            "— migriere auf neues Schema."
        )
        # Backup und Neuerstellung; Daten soweit moeglich uebernehmen
        self._conn.executescript("""
            DROP TABLE IF EXISTS _characters_task01_backup;
            ALTER TABLE characters RENAME TO _characters_task01_backup;
            CREATE TABLE characters (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL DEFAULT 'Investigator',
                module        TEXT    NOT NULL,
                stats_current TEXT    NOT NULL DEFAULT '{}',
                stats_max     TEXT    NOT NULL DEFAULT '{}',
                skills        TEXT    NOT NULL DEFAULT '{}',
                skills_used   TEXT    NOT NULL DEFAULT '[]',
                created_at    TEXT    NOT NULL DEFAULT '',
                last_saved    TEXT    NOT NULL DEFAULT ''
            );
            INSERT INTO characters
                (id, name, module, stats_current, stats_max,
                 skills, skills_used, created_at, last_saved)
            SELECT id, name, module,
                   COALESCE(stats_current, '{}'),
                   COALESCE(stats_max,     '{}'),
                   COALESCE(skills,        '{}'),
                   COALESCE(skills_used,   '[]'),
                   COALESCE(created_at,    ''),
                   COALESCE(last_saved,    '')
            FROM _characters_task01_backup;
        """)
        self._conn.commit()
        logger.info("characters-Migration abgeschlossen.")

    def _create_default_character(self) -> None:
        """
        Erstellt einen Charakter. Wenn ein Template geladen wurde, werden dessen
        Werte verwendet. Ansonsten Durchschnittswerte aus dem Ruleset.
        """
        if self._template:
            self._create_from_template()
        else:
            self._create_from_ruleset_defaults()

        self.save()
        logger.info(
            "Standardcharakter erstellt: %s | %s",
            self._name, self.status_line(),
        )

    def _create_from_template(self) -> None:
        """Erstellt einen Charakter aus einem geladenen Template."""
        t = self._template
        self._name = t.get("name", self._name)
        self._archetype = t.get("archetype", "")
        self._level = t.get("level", 1)
        self._background = t.get("background", "")
        self._traits = t.get("traits", "")
        self._appearance = t.get("appearance", "")
        self._equipment = t.get("equipment", [])
        self._characteristics = t.get("characteristics", {})

        # Derived stats from template
        derived = t.get("derived_stats", {})
        self._stats = {}
        self._stats_max = {}
        for key, val in derived.items():
            self._stats[key] = val
            self._stats_max[key] = val
        # Mindestens HP
        if "HP" not in self._stats:
            self._stats["HP"] = 10
            self._stats_max["HP"] = 10

        # Skills: Basis aus Ruleset, dann Template-Overrides
        skills_def = self.ruleset.get("skills", {})
        base_skills: dict[str, int] = {}
        for skill_name, skill_def in skills_def.items():
            base = skill_def.get("base", 0)
            base_skills[skill_name] = int(base) if isinstance(base, (int, float)) else 0
        # Template-Skills ueberschreiben
        for skill_name, skill_val in t.get("skills", {}).items():
            base_skills[skill_name] = skill_val
        self._skills = base_skills
        self._skills_used = set()

        logger.info(
            "Charakter aus Template: %s (%s, Stufe %d)",
            self._name, self._archetype, self._level,
        )

    def _create_from_ruleset_defaults(self) -> None:
        """Erstellt einen Standardcharakter mit Durchschnittswerten aus dem Ruleset."""
        ruleset_chars = self.ruleset.get("characteristics", {})
        skills_def = self.ruleset.get("skills", {})

        # Charaktereigenschaften berechnen (Durchschnitt)
        char_values: dict[str, int] = {}
        for stat_key, stat_def in ruleset_chars.items():
            roll_str = stat_def.get("roll", "3d6")
            mult = stat_def.get("multiplier", 5)
            parts = roll_str.split("+")
            dice_part = parts[0].strip()
            bonus = int(parts[1].strip()) if len(parts) > 1 else 0
            if "d" in dice_part:
                count_str, faces_str = dice_part.split("d", 1)
                count = int(count_str) if count_str else 1
                faces = int(faces_str)
                avg = count * (faces + 1) // 2 + bonus
            else:
                avg = int(dice_part)
            char_values[stat_key] = avg * mult
        self._characteristics = char_values

        # Abgeleitete Werte
        con  = char_values.get("CON", 65)
        siz  = char_values.get("SIZ", 65)
        pow_ = char_values.get("POW", 65)

        hp_val  = math.floor((con + siz) / 10)
        san_val = pow_
        mp_val  = math.floor(pow_ / 5)

        # Stats dynamisch: nur SAN/MP wenn Ruleset diese definiert
        self._stats     = {"HP": hp_val}
        self._stats_max = {"HP": hp_val}
        if "sanity" in self.ruleset:
            self._stats["SAN"] = san_val
            self._stats_max["SAN"] = min(99, san_val)
        if "MP" in self.ruleset.get("derived_stats", {}):
            self._stats["MP"] = mp_val
            self._stats_max["MP"] = mp_val

        # Fertigkeiten mit Basiswerten aus Ruleset
        base_skills: dict[str, int] = {}
        for skill_name, skill_def in skills_def.items():
            base = skill_def.get("base", 0)
            base_skills[skill_name] = int(base) if isinstance(base, (int, float)) else 0
        self._skills = base_skills
        self._skills_used = set()
