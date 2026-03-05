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

# AD&D 2e Erweiterungen: Inventar, Zeit, Wetter
INVENTAR_PATTERN = re.compile(
    r"\[INVENTAR:\s*([^\|]+)\|\s*(gefunden|verloren|gekauft|verkauft)\s*\]",
    re.IGNORECASE,
)
ZEIT_PATTERN = re.compile(r"\[ZEIT_VERGEHT:\s*([\d.]+)h?\s*\]", re.IGNORECASE)
TAGESZEIT_PATTERN = re.compile(r"\[TAGESZEIT:\s*(\d{1,2}):(\d{2})\s*\]", re.IGNORECASE)
WETTER_PATTERN = re.compile(r"\[WETTER:\s*([^\]]+)\s*\]", re.IGNORECASE)
RUNDE_PATTERN = re.compile(r"\[RUNDE:\s*(\d+)\s*\]", re.IGNORECASE)

# AD&D 2e Kampf-Tags
ANGRIFF_PATTERN = re.compile(
    r"\[ANGRIFF:\s*([^\|]+)\|\s*(\d+)\s*\|\s*(-?\d+)\s*\|\s*(-?\d+)\s*\]",
    re.IGNORECASE,
)
RETTUNGSWURF_PATTERN = re.compile(
    r"\[RETTUNGSWURF:\s*([^\|]+)\|\s*(\d+)\s*\]",
    re.IGNORECASE,
)

# ── Party-spezifische Tags (per-Character) ──────────────────────────────────
# [HP_VERLUST: Thorin Eisenschild | 8]
PARTY_HP_LOSS_PATTERN = re.compile(
    r"\[HP_VERLUST:\s*([^\|]+)\|\s*(\d+)\s*\]",
    re.IGNORECASE,
)
# [HP_HEILUNG: Bruder Aldhelm | 2d4+2]
PARTY_HP_HEAL_PATTERN = re.compile(
    r"\[HP_HEILUNG:\s*([^\|]+)\|\s*(\d+d\d+(?:\+\d+)?|\d+)\s*\]",
    re.IGNORECASE,
)
# [ZAUBER_VERBRAUCHT: Elara | Fireball | 3]
PARTY_SPELL_USED_PATTERN = re.compile(
    r"\[ZAUBER_VERBRAUCHT:\s*([^\|]+)\|\s*([^\|]+)\|\s*(\d+)\s*\]",
    re.IGNORECASE,
)
# [INVENTAR: Heiltrank | gefunden | Lyra]
PARTY_INVENTAR_PATTERN = re.compile(
    r"\[INVENTAR:\s*([^\|]+)\|\s*(gefunden|verloren|gekauft|verkauft)\s*\|\s*([^\]]+)\s*\]",
    re.IGNORECASE,
)
# [FERTIGKEIT_GENUTZT: Move Silently | Lyra]
PARTY_FERTIGKEIT_PATTERN = re.compile(
    r"\[FERTIGKEIT_GENUTZT:\s*([^\|]+)\|\s*([^\]]+)\s*\]", re.IGNORECASE,
)
# [GEGENSTAND_BENUTZT: Potion of Healing | Bruder Aldhelm]
PARTY_ITEM_USED_PATTERN = re.compile(
    r"\[GEGENSTAND_BENUTZT:\s*([^\|]+)\|\s*([^\]]+)\s*\]", re.IGNORECASE,
)
# [PROBE: Fallen-Suchen | 45 | Lyra]
PARTY_PROBE_PATTERN = re.compile(
    r"\[PROBE:\s*([^\|]+)\|\s*(\d+)\s*\|\s*([^\]]+)\s*\]",
    re.IGNORECASE,
)
# [ANGRIFF: Waffe | THAC0 | AC | Mod | CharName]
PARTY_ANGRIFF_PATTERN = re.compile(
    r"\[ANGRIFF:\s*([^\|]+)\|\s*(\d+)\s*\|\s*(-?\d+)\s*\|\s*([+-]?\d+)\s*\|\s*([^\]]+)\s*\]",
    re.IGNORECASE,
)

# ── Monster-Mechanik-Tags (Session 19) ──────────────────────────────────────
# [MAGIC_RESISTANCE: MonsterName | Prozent]
MAGIC_RESISTANCE_PATTERN = re.compile(
    r"\[MAGIC_RESISTANCE:\s*([^\|]+)\|\s*(\d+)\s*\]", re.IGNORECASE,
)
# [WAFFEN_IMMUNITAET: MonsterName | Mindest-Bonus]
WAFFEN_IMMUNITAET_PATTERN = re.compile(
    r"\[WAFFEN_IMMUNITAET:\s*([^\|]+)\|\s*([^\]]+)\s*\]", re.IGNORECASE,
)
# [GIFT: MonsterName | Typ | Save-Modifikator]
GIFT_PATTERN = re.compile(
    r"\[GIFT:\s*([^\|]+)\|\s*([^\|]+)\|\s*(-?\d+)\s*\]", re.IGNORECASE,
)
# [LEVEL_DRAIN: CharName | Stufen]
LEVEL_DRAIN_PATTERN = re.compile(
    r"\[LEVEL_DRAIN:\s*([^\|]+)\|\s*(\d+)\s*\]", re.IGNORECASE,
)
# [MORAL_CHECK: MonsterName | Schwelle]
MORAL_CHECK_PATTERN = re.compile(
    r"\[MORAL_CHECK:\s*([^\|]+)\|\s*(\d+)\s*\]", re.IGNORECASE,
)
# [REGENERATION: MonsterName | HP_pro_Runde]
REGENERATION_PATTERN = re.compile(
    r"\[REGENERATION:\s*([^\|]+)\|\s*(\d+)\s*\]", re.IGNORECASE,
)
# [FURCHT: CharName | Effekt | Dauer]
FURCHT_PATTERN = re.compile(
    r"\[FURCHT:\s*([^\|]+)\|\s*([^\|]+)\|\s*([^\]]+)\s*\]", re.IGNORECASE,
)
# [ATEM_WAFFE: MonsterName | Typ | Schaden]
ATEM_WAFFE_PATTERN = re.compile(
    r"\[ATEM_WAFFE:\s*([^\|]+)\|\s*([^\|]+)\|\s*([^\]]+)\s*\]", re.IGNORECASE,
)


def extract_party_stat_changes(text: str) -> list[tuple[str, ...]]:
    """
    Extrahiert alle party-spezifischen Tags aus dem KI-Antworttext.

    Returns list of tuples. Format pro Tag-Typ:
      ("HP_VERLUST", char_name, amount_str)
      ("HP_HEILUNG", char_name, amount_str)
      ("ZAUBER_VERBRAUCHT", char_name, spell_name, level_str)
      ("INVENTAR", item_name, action, char_name)
      ("FERTIGKEIT_GENUTZT", skill_name, char_name)
      ("GEGENSTAND_BENUTZT", item_name, char_name)
      ("PROBE", skill_name, target_str, char_name)
      ("ANGRIFF", weapon, thac0, ac, mod, char_name)
      -- Monster-Mechanik-Tags (gleiches Format wie extract_stat_changes) --
      ("MAGIC_RESISTANCE", monster_name, prozent_str)
      ("WAFFEN_IMMUNITAET", monster_name, bonus_str)
      ("GIFT", monster_name, typ, save_mod_str)
      ("LEVEL_DRAIN", char_name, stufen_str)
      ("MORAL_CHECK", monster_name, schwelle_str)
      ("REGENERATION", monster_name, hp_str)
      ("FURCHT", char_name, effekt, dauer_str)
      ("ATEM_WAFFE", monster_name, typ, schaden_str)

    Kompatibilitaet: Vorhandene Tags OHNE Pipe-getrennten Namen werden NICHT
    erfasst — dafuer ist extract_stat_changes() zustaendig (Single-Char-Modus).
    """
    results: list[tuple[str, ...]] = []

    for m in PARTY_HP_LOSS_PATTERN.finditer(text):
        results.append(("HP_VERLUST", m.group(1).strip(), m.group(2).strip()))

    for m in PARTY_HP_HEAL_PATTERN.finditer(text):
        results.append(("HP_HEILUNG", m.group(1).strip(), m.group(2).strip()))

    for m in PARTY_SPELL_USED_PATTERN.finditer(text):
        results.append((
            "ZAUBER_VERBRAUCHT",
            m.group(1).strip(),
            m.group(2).strip(),
            m.group(3).strip(),
        ))

    for m in PARTY_INVENTAR_PATTERN.finditer(text):
        results.append((
            "INVENTAR",
            m.group(1).strip(),
            m.group(2).strip().lower(),
            m.group(3).strip(),
        ))

    for m in PARTY_FERTIGKEIT_PATTERN.finditer(text):
        results.append((
            "FERTIGKEIT_GENUTZT",
            m.group(1).strip(),
            m.group(2).strip(),
        ))

    for m in PARTY_ITEM_USED_PATTERN.finditer(text):
        results.append((
            "GEGENSTAND_BENUTZT",
            m.group(1).strip(),
            m.group(2).strip(),
        ))

    for m in PARTY_PROBE_PATTERN.finditer(text):
        results.append((
            "PROBE",
            m.group(1).strip(),
            m.group(2).strip(),
            m.group(3).strip(),
        ))

    for m in PARTY_ANGRIFF_PATTERN.finditer(text):
        results.append((
            "ANGRIFF",
            m.group(1).strip(),
            m.group(2).strip(),
            m.group(3).strip(),
            m.group(4).strip(),
            m.group(5).strip(),
        ))

    # Monster-Mechanik-Tags (beide Modi: Party und Solo nutzen dieselben Patterns)
    for m in MAGIC_RESISTANCE_PATTERN.finditer(text):
        results.append(("MAGIC_RESISTANCE", m.group(1).strip(), m.group(2).strip()))
    for m in WAFFEN_IMMUNITAET_PATTERN.finditer(text):
        results.append(("WAFFEN_IMMUNITAET", m.group(1).strip(), m.group(2).strip()))
    for m in GIFT_PATTERN.finditer(text):
        results.append(("GIFT", m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
    for m in LEVEL_DRAIN_PATTERN.finditer(text):
        results.append(("LEVEL_DRAIN", m.group(1).strip(), m.group(2).strip()))
    for m in MORAL_CHECK_PATTERN.finditer(text):
        results.append(("MORAL_CHECK", m.group(1).strip(), m.group(2).strip()))
    for m in REGENERATION_PATTERN.finditer(text):
        results.append(("REGENERATION", m.group(1).strip(), m.group(2).strip()))
    for m in FURCHT_PATTERN.finditer(text):
        results.append(("FURCHT", m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
    for m in ATEM_WAFFE_PATTERN.finditer(text):
        results.append(("ATEM_WAFFE", m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))

    return results


def extract_stat_changes(text: str) -> list[tuple[str, ...]]:
    """
    Parst alle Zustandsaenderungs-Tags aus dem GM-Text.
    Returns list of tuples (tag_type, *values).
      ("HP_VERLUST", amount_str)
      ("HP_HEILUNG", amount_str)
      ("STABILITAET_VERLUST", amount_str)
      ("XP_GEWINN", amount_str)
      ("FERTIGKEIT_GENUTZT", skill_name)
      ("MAGIC_RESISTANCE", monster_name, prozent_str)
      ("WAFFEN_IMMUNITAET", monster_name, bonus_str)
      ("GIFT", monster_name, typ, save_mod_str)
      ("LEVEL_DRAIN", char_name, stufen_str)
      ("MORAL_CHECK", monster_name, schwelle_str)
      ("REGENERATION", monster_name, hp_str)
      ("FURCHT", char_name, effekt, dauer_str)
      ("ATEM_WAFFE", monster_name, typ, schaden_str)
    """
    results: list[tuple[str, ...]] = []
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
    # Monster-Mechanik-Tags
    for m in MAGIC_RESISTANCE_PATTERN.finditer(text):
        results.append(("MAGIC_RESISTANCE", m.group(1).strip(), m.group(2).strip()))
    for m in WAFFEN_IMMUNITAET_PATTERN.finditer(text):
        results.append(("WAFFEN_IMMUNITAET", m.group(1).strip(), m.group(2).strip()))
    for m in GIFT_PATTERN.finditer(text):
        results.append(("GIFT", m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
    for m in LEVEL_DRAIN_PATTERN.finditer(text):
        results.append(("LEVEL_DRAIN", m.group(1).strip(), m.group(2).strip()))
    for m in MORAL_CHECK_PATTERN.finditer(text):
        results.append(("MORAL_CHECK", m.group(1).strip(), m.group(2).strip()))
    for m in REGENERATION_PATTERN.finditer(text):
        results.append(("REGENERATION", m.group(1).strip(), m.group(2).strip()))
    for m in FURCHT_PATTERN.finditer(text):
        results.append(("FURCHT", m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
    for m in ATEM_WAFFE_PATTERN.finditer(text):
        results.append(("ATEM_WAFFE", m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
    return results


def extract_inventory_changes(text: str) -> list[tuple[str, str]]:
    """
    Parst alle INVENTAR-Tags aus dem GM-Text.
    Returns list of (item_name, action) tuples.
      action: "gefunden" | "verloren" | "gekauft" | "verkauft"
    """
    results: list[tuple[str, str]] = []
    for m in INVENTAR_PATTERN.finditer(text):
        results.append((m.group(1).strip(), m.group(2).strip().lower()))
    return results


def extract_combat_tags(text: str) -> list[tuple[str, Any]]:
    """
    Parst alle Kampf-Tags aus dem GM-Text (AD&D 2e).
    Returns list of (tag_type, data) tuples.
      ("ANGRIFF", {"weapon": str, "thac0": int, "target_ac": int, "modifiers": int})
      ("RETTUNGSWURF", {"category": str, "target": int})
    """
    results: list[tuple[str, Any]] = []
    for m in ANGRIFF_PATTERN.finditer(text):
        results.append(("ANGRIFF", {
            "weapon": m.group(1).strip(),
            "thac0": int(m.group(2)),
            "target_ac": int(m.group(3)),
            "modifiers": int(m.group(4)),
        }))
    for m in RETTUNGSWURF_PATTERN.finditer(text):
        results.append(("RETTUNGSWURF", {
            "category": m.group(1).strip(),
            "target": int(m.group(2)),
        }))
    return results


def extract_time_changes(text: str) -> list[tuple[str, str | tuple[int, int]]]:
    """
    Parst alle Zeit/Wetter-Tags aus dem GM-Text.
    Returns list of (tag_type, value) tuples.
      ("ZEIT_VERGEHT", "2.0")
      ("TAGESZEIT", (14, 30))
      ("WETTER", "starker Regen")
    """
    results: list[tuple[str, Any]] = []
    for m in ZEIT_PATTERN.finditer(text):
        results.append(("ZEIT_VERGEHT", m.group(1)))
    for m in TAGESZEIT_PATTERN.finditer(text):
        results.append(("TAGESZEIT", (int(m.group(1)), int(m.group(2)))))
    for m in WETTER_PATTERN.finditer(text):
        results.append(("WETTER", m.group(1).strip()))
    for m in RUNDE_PATTERN.finditer(text):
        results.append(("RUNDE", m.group(1)))
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
        self._inventory: list[str] = []
        self._xp: int = 0
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # DB Safety
    # ------------------------------------------------------------------

    def _safe_commit(self, context: str = "unknown") -> bool:
        """
        Fuehrt _conn.commit() mit Retry-Logik aus (3 Versuche, 0.2s Pause).
        Schuetzt gegen 'database is locked' bei konkurrierenden Schreibzugriffen.
        Returns True bei Erfolg, False bei Fehlschlag.
        """
        import time as _t
        for attempt in range(3):
            try:
                self._conn.commit()
                return True
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc) and attempt < 2:
                    logger.warning(
                        "DB locked bei %s (Versuch %d/3) — warte 0.2s",
                        context, attempt + 1,
                    )
                    _t.sleep(0.2)
                else:
                    logger.error("DB-Fehler bei %s: %s", context, exc)
                    return False
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Oeffnet die DB-Verbindung und stellt sicher dass das Schema existiert."""
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=10.0)
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

        # Inventar und XP laden (neue Spalten, Fallback fuer alte DBs)
        try:
            self._inventory = json.loads(row["inventory"])
        except (KeyError, IndexError):
            self._inventory = []
        try:
            self._xp = row["xp"]
        except (KeyError, IndexError):
            self._xp = 0

        hp_current = self._stats.get("HP", 0)
        hp_max = self._stats_max.get("HP", 0)
        # Defensive: ensure integers (some systems use strings)
        try:
            hp_current = int(hp_current) if hp_current else 0
            hp_max = int(hp_max) if hp_max else 0
        except (ValueError, TypeError):
            hp_current, hp_max = 0, 0

        logger.info(
            "Charakter geladen: %s (ID=%d) | HP: %d/%d | XP: %d",
            self._name,
            self._char_id,
            hp_current,
            hp_max,
            self._xp,
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

    # ------------------------------------------------------------------
    # Inventar
    # ------------------------------------------------------------------

    def add_item(self, item_name: str) -> None:
        """Fuegt einen Gegenstand zum Inventar hinzu und persistiert."""
        self._inventory.append(item_name.strip())
        self.save()
        logger.info("Inventar +: '%s' (gesamt: %d)", item_name, len(self._inventory))

    def remove_item(self, item_name: str) -> bool:
        """
        Entfernt einen Gegenstand aus dem Inventar (case-insensitive Suche).
        Returns True wenn gefunden und entfernt, False wenn nicht vorhanden.
        """
        needle = item_name.strip().lower()
        for i, existing in enumerate(self._inventory):
            if existing.lower() == needle:
                removed = self._inventory.pop(i)
                self.save()
                logger.info("Inventar -: '%s' (gesamt: %d)", removed, len(self._inventory))
                return True
        logger.warning("Gegenstand '%s' nicht im Inventar.", item_name)
        return False

    def get_inventory(self) -> list[str]:
        """Gibt eine Kopie des aktuellen Inventars zurueck."""
        return list(self._inventory)

    # ------------------------------------------------------------------
    # XP
    # ------------------------------------------------------------------

    def add_xp(self, amount: int) -> dict[str, int]:
        """
        Fuegt Erfahrungspunkte hinzu und persistiert sofort.
        Returns dict mit old_xp, new_xp, gained.
        """
        old = self._xp
        self._xp += amount
        self.save()
        logger.info("XP: %d -> %d (+%d)", old, self._xp, amount)
        return {"old_xp": old, "new_xp": self._xp, "gained": amount}

    @property
    def xp(self) -> int:
        return self._xp

    @property
    def inventory(self) -> list[str]:
        return list(self._inventory)

    @property
    def level(self) -> int:
        return self._level

    def save(self) -> None:
        """Persistiert den aktuellen Charakter-Zustand sofort in der DB."""
        if not self._conn:
            return

        now = datetime.now(timezone.utc).isoformat()

        if self._char_id is None:
            cur = self._conn.execute(
                """INSERT INTO characters
                   (name, module, stats_current, stats_max, skills, skills_used,
                    inventory, xp, created_at, last_saved)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._name,
                    self._module,
                    json.dumps(self._stats),
                    json.dumps(self._stats_max),
                    json.dumps(self._skills),
                    json.dumps(list(self._skills_used)),
                    json.dumps(self._inventory),
                    self._xp,
                    now,
                    now,
                ),
            )
            self._char_id = cur.lastrowid
            self._safe_commit("save/insert")
            logger.debug("Charakter neu erstellt (ID=%d).", self._char_id)
        else:
            self._conn.execute(
                """UPDATE characters SET
                   stats_current = ?, stats_max = ?, skills = ?,
                   skills_used = ?, inventory = ?, xp = ?, last_saved = ?
                   WHERE id = ?""",
                (
                    json.dumps(self._stats),
                    json.dumps(self._stats_max),
                    json.dumps(self._skills),
                    json.dumps(list(self._skills_used)),
                    json.dumps(self._inventory),
                    self._xp,
                    now,
                    self._char_id,
                ),
            )
            self._safe_commit("save/update")
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
        self._safe_commit("start_session")
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
        self._safe_commit("log_turn")

    def get_conn(self) -> sqlite3.Connection | None:
        """Gibt die interne DB-Verbindung zurueck (fuer Archivist-Sharing)."""
        return self._conn

    # ------------------------------------------------------------------
    # Status-Anzeige
    # ------------------------------------------------------------------

    def status_line(self) -> str:
        """Kurze Statuszeile: 'HP: 13/13 | SAN: 65/65 | XP: 150 | Inventar: 5'."""
        parts = []
        for key in ("HP", "SAN", "MP"):
            if key in self._stats:
                parts.append(f"{key}: {self._stats[key]}/{self._stats_max.get(key, '?')}")
        if self._xp > 0:
            parts.append(f"XP: {self._xp}")
        if self._inventory:
            parts.append(f"Inventar: {len(self._inventory)}")
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
        hp = self._stats.get("HP", 1)
        return hp <= 0 if isinstance(hp, (int, float)) else False

    @property
    def is_insane(self) -> bool:
        san = self._stats.get("SAN", 1)
        return san <= 0 if isinstance(san, (int, float)) else False

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
        self._safe_commit("ensure_schema")

        # Migrations fuer bestehende DBs aus Task 01 (optionale Spalten hinzufuegen)
        _migrations = [
            ("characters", "stats_current", "TEXT NOT NULL DEFAULT '{}'"),
            ("characters", "stats_max",     "TEXT NOT NULL DEFAULT '{}'"),
            ("characters", "skills",        "TEXT NOT NULL DEFAULT '{}'"),
            ("characters", "skills_used",   "TEXT NOT NULL DEFAULT '[]'"),
            ("characters", "inventory",     "TEXT NOT NULL DEFAULT '[]'"),
            ("characters", "xp",            "INTEGER NOT NULL DEFAULT 0"),
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
                self._safe_commit(f"migration/{table}.{col}")
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
        self._safe_commit("migrate_characters")
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
        if not isinstance(derived, dict):
            derived = {}
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
        if not isinstance(skills_def, dict):
            skills_def = {}
        base_skills: dict[str, int] = {}
        for skill_name, skill_def in skills_def.items():
            base = skill_def.get("base", 0)
            base_skills[skill_name] = int(base) if isinstance(base, (int, float)) else 0
        # Template-Skills ueberschreiben
        template_skills = t.get("skills", {})
        if isinstance(template_skills, dict):
            for skill_name, skill_val in template_skills.items():
                base_skills[skill_name] = skill_val
        self._skills = base_skills
        self._skills_used = set()

        # Equipment aus Template ins Inventar uebernehmen
        self._inventory = list(self._equipment)
        self._xp = t.get("xp", 0)

        logger.info(
            "Charakter aus Template: %s (%s, Stufe %d)",
            self._name, self._archetype, self._level,
        )

    def _create_from_ruleset_defaults(self) -> None:
        """Erstellt einen Standardcharakter mit Durchschnittswerten aus dem Ruleset."""
        ruleset_chars = self.ruleset.get("characteristics", {})
        if not isinstance(ruleset_chars, dict):
            ruleset_chars = {}
        skills_def = self.ruleset.get("skills", {})
        if not isinstance(skills_def, dict):
            skills_def = {}

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

        # Abgeleitete Werte — systemabhaengig
        derived_def = self.ruleset.get("derived_stats", {})

        if "SIZ" in char_values:
            # CoC-Stil: HP = (CON + SIZ) / 10
            con = char_values.get("CON", 65)
            siz = char_values.get("SIZ", 65)
            hp_val = math.floor((con + siz) / 10)
        else:
            # AD&D-Stil: HP = Hit Die Durchschnitt (d10=5 fuer Fighter)
            hp_val = 10

        self._stats     = {"HP": hp_val}
        self._stats_max = {"HP": hp_val}

        # SAN nur fuer Rulesets mit Sanity-System (CoC)
        if "sanity" in self.ruleset:
            pow_ = char_values.get("POW", 65)
            self._stats["SAN"] = pow_
            self._stats_max["SAN"] = min(99, pow_)

        # MP nur fuer Rulesets die das explizit definieren (CoC)
        if "MP" in derived_def:
            pow_ = char_values.get("POW", 65)
            mp_val = math.floor(pow_ / 5)
            self._stats["MP"] = mp_val
            self._stats_max["MP"] = mp_val

        # Fertigkeiten mit Basiswerten aus Ruleset
        base_skills: dict[str, int] = {}
        if isinstance(skills_def, dict):
            for skill_name, skill_def in skills_def.items():
                base = skill_def.get("base", 0)
                base_skills[skill_name] = int(base) if isinstance(base, (int, float)) else 0
        self._skills = base_skills
        self._skills_used = set()
