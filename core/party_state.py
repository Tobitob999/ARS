"""
core/party_state.py -- Party State Manager

Verwaltet den Zustand aller Gruppenmitglieder (Multi-Charakter-Modus).
Unterstuetzt HP-Tracking, Zaubermanagement, Inventar, XP und Persistenz.

Tags (per-Character):
  [HP_VERLUST: <Name> | <Menge>]
  [HP_HEILUNG: <Name> | <Menge>]
  [ZAUBER_VERBRAUCHT: <Name> | <Zaubername> | <Level>]
  [INVENTAR: <Item> | <Aktion> | <Name>]
  [XP_GEWINN: <Menge>]  (wird auf lebende Mitglieder aufgeteilt)
"""

from __future__ import annotations

import copy
import difflib
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger("ARS.party_state")


@dataclass
class PartyMember:
    """Zustand eines einzelnen Gruppenmitglieds."""
    name: str
    char_id: str
    archetype: str           # Klasse (z.B. Fighter, Mage)
    level: int
    race: str
    hp: int
    hp_max: int
    ac: int
    thac0: int
    characteristics: dict    # STR/DEX/CON/INT/WIS/CHA
    saving_throws: dict      # 5 Kategorien
    equipment: list
    spells_prepared: list    # Flache Liste aller vorbereiteten Sprueche
    spells_remaining: dict   # {level_int: slots_remaining}
    xp: int
    alive: bool = True


class PartyStateManager:
    """Verwaltet den Zustand aller Gruppenmitglieder."""

    def __init__(self) -> None:
        self._members: dict[str, PartyMember] = {}  # keyed by char name
        self._turn_log: list[dict] = []

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_party_json(
        cls, party_data: dict, characters: list[dict]
    ) -> PartyStateManager:
        """Factory: baut PartyStateManager aus Party-Definition + Charakter-Dicts."""
        mgr = cls()

        for char in characters:
            name = char.get("name", "Unbekannt")
            char_id = char.get("id", name.lower().replace(" ", "_"))
            archetype = char.get("class", char.get("archetype", "?"))
            level = char.get("level", 1)
            race = char.get("race", "?")

            # Derived Stats
            derived = char.get("derived_stats", {})
            hp = derived.get("HP", 10)
            hp_max = hp
            ac = derived.get("AC", 10)
            thac0 = derived.get("THAC0", 20)

            # Characteristics
            characteristics = dict(char.get("characteristics", {}))

            # Saving Throws
            saving_throws = dict(char.get("saving_throws", {}))

            # Equipment
            equipment = list(char.get("equipment", []))

            # Spells: aus spells_prepared dict -> flache Liste + Slot-Tracking
            spells_prep_raw = char.get("spells_prepared", {})
            spells_flat: list[str] = []
            spells_remaining: dict[int, int] = {}
            if isinstance(spells_prep_raw, dict):
                for level_str, spell_list in spells_prep_raw.items():
                    try:
                        lvl = int(level_str)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(spell_list, list):
                        spells_flat.extend(spell_list)
                        spells_remaining[lvl] = len(spell_list)

            xp = char.get("xp", 0)

            member = PartyMember(
                name=name,
                char_id=char_id,
                archetype=archetype,
                level=level,
                race=race,
                hp=hp,
                hp_max=hp_max,
                ac=ac,
                thac0=thac0,
                characteristics=characteristics,
                saving_throws=saving_throws,
                equipment=equipment,
                spells_prepared=spells_flat,
                spells_remaining=spells_remaining,
                xp=xp,
                alive=True,
            )
            mgr._members[name] = member
            logger.info(
                "PartyMember geladen: %s (%s %d, %s) HP:%d/%d AC:%d",
                name, archetype, level, race, hp, hp_max, ac,
            )

        logger.info(
            "PartyStateManager: %d Mitglieder geladen aus '%s'.",
            len(mgr._members),
            party_data.get("name", "?"),
        )
        return mgr

    # ------------------------------------------------------------------
    # Fuzzy Match
    # ------------------------------------------------------------------

    def _fuzzy_match(self, name: str) -> str | None:
        """Findet den naechsten Mitgliedsnamen via difflib."""
        if not name or not self._members:
            return None
        # Exakte Treffer (case-insensitive)
        for member_name in self._members:
            if member_name.lower() == name.lower():
                return member_name
        # Teilstring-Match
        for member_name in self._members:
            if name.lower() in member_name.lower() or member_name.lower() in name.lower():
                return member_name
        # Fuzzy-Match
        matches = difflib.get_close_matches(
            name, self._members.keys(), n=1, cutoff=0.5
        )
        return matches[0] if matches else None

    # ------------------------------------------------------------------
    # HP Management
    # ------------------------------------------------------------------

    def apply_damage(self, char_name: str, amount: int) -> str:
        """Wendet Schaden an, markiert tot bei HP<=0. Gibt Status-String zurueck."""
        resolved = self._fuzzy_match(char_name)
        if not resolved:
            msg = f"[PARTY] Charakter '{char_name}' nicht gefunden — Schaden ignoriert."
            logger.warning(msg)
            return msg

        member = self._members[resolved]
        if not member.alive:
            msg = f"[PARTY] {resolved} ist bereits tot — Schaden ignoriert."
            logger.info(msg)
            return msg

        old_hp = member.hp
        member.hp = max(0, member.hp - amount)
        if member.hp <= 0:
            member.alive = False

        status = "TOT" if not member.alive else f"HP: {member.hp}/{member.hp_max}"
        msg = (
            f"[HP-VERLUST] {resolved}: -{amount} | "
            f"HP: {old_hp} -> {member.hp}/{member.hp_max}"
        )
        if not member.alive:
            msg += f" | {resolved} ist gefallen!"

        self._turn_log.append({
            "action": "damage",
            "target": resolved,
            "amount": amount,
            "hp_before": old_hp,
            "hp_after": member.hp,
            "alive": member.alive,
        })
        logger.info(msg)
        return msg

    def apply_healing(self, char_name: str, amount: int) -> str:
        """Heilt bis max HP. Gibt Status-String zurueck."""
        resolved = self._fuzzy_match(char_name)
        if not resolved:
            msg = f"[PARTY] Charakter '{char_name}' nicht gefunden — Heilung ignoriert."
            logger.warning(msg)
            return msg

        member = self._members[resolved]
        if not member.alive:
            msg = f"[PARTY] {resolved} ist tot — Heilung ignoriert."
            logger.info(msg)
            return msg

        old_hp = member.hp
        member.hp = min(member.hp_max, member.hp + amount)
        msg = (
            f"[HP-HEILUNG] {resolved}: +{amount} | "
            f"HP: {old_hp} -> {member.hp}/{member.hp_max}"
        )

        self._turn_log.append({
            "action": "healing",
            "target": resolved,
            "amount": amount,
            "hp_before": old_hp,
            "hp_after": member.hp,
        })
        logger.info(msg)
        return msg

    # ------------------------------------------------------------------
    # Spell Management
    # ------------------------------------------------------------------

    def use_spell(self, char_name: str, spell_name: str, level: int) -> str:
        """Verbraucht einen Zauberplatz. Gibt Status-String zurueck."""
        resolved = self._fuzzy_match(char_name)
        if not resolved:
            msg = f"[PARTY] Charakter '{char_name}' nicht gefunden — Zauber ignoriert."
            logger.warning(msg)
            return msg

        member = self._members[resolved]
        if not member.alive:
            return f"[PARTY] {resolved} ist tot — Zauber nicht moeglich."

        remaining = member.spells_remaining.get(level, 0)
        if remaining <= 0:
            msg = f"[ZAUBER] {resolved}: Keine Sprueche Level {level} mehr verfuegbar!"
            logger.warning(msg)
            return msg

        member.spells_remaining[level] = remaining - 1
        msg = (
            f"[ZAUBER] {resolved} wirkt {spell_name} (Level {level}) | "
            f"Verbleibend Level {level}: {remaining - 1}"
        )

        self._turn_log.append({
            "action": "spell_used",
            "caster": resolved,
            "spell": spell_name,
            "level": level,
            "remaining": remaining - 1,
        })
        logger.info(msg)
        return msg

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def add_item(self, char_name: str, item: str) -> None:
        """Fuegt einem Charakter einen Gegenstand hinzu."""
        resolved = self._fuzzy_match(char_name)
        if not resolved:
            logger.warning("add_item: Charakter '%s' nicht gefunden.", char_name)
            return
        self._members[resolved].equipment.append(item.strip())
        logger.info("Inventar +: %s -> %s", resolved, item)

    def remove_item(self, char_name: str, item: str) -> None:
        """Entfernt einen Gegenstand (case-insensitive)."""
        resolved = self._fuzzy_match(char_name)
        if not resolved:
            logger.warning("remove_item: Charakter '%s' nicht gefunden.", char_name)
            return
        needle = item.strip().lower()
        equip = self._members[resolved].equipment
        for i, existing in enumerate(equip):
            if existing.lower() == needle or needle in existing.lower():
                removed = equip.pop(i)
                logger.info("Inventar -: %s -> %s", resolved, removed)
                return
        logger.warning("Gegenstand '%s' nicht bei %s gefunden.", item, resolved)

    # ------------------------------------------------------------------
    # XP
    # ------------------------------------------------------------------

    def add_xp(self, amount: int) -> None:
        """Teilt XP gleichmaessig auf alle lebenden Mitglieder auf."""
        alive = self.alive_members()
        if not alive:
            logger.warning("add_xp: Keine lebenden Mitglieder — XP verfallen.")
            return
        share = amount // len(alive)
        remainder = amount % len(alive)
        for i, member in enumerate(alive):
            bonus = 1 if i < remainder else 0
            member.xp += share + bonus
        names = ", ".join(m.name for m in alive)
        logger.info(
            "XP verteilt: %d auf %d Mitglieder (%d/Person). [%s]",
            amount, len(alive), share, names,
        )
        self._turn_log.append({
            "action": "xp_gain",
            "amount": amount,
            "per_member": share,
            "alive_count": len(alive),
        })

    # ------------------------------------------------------------------
    # State Queries
    # ------------------------------------------------------------------

    def is_tpk(self) -> bool:
        """True wenn alle Mitglieder tot sind (Total Party Kill)."""
        if not self._members:
            return False
        return all(not m.alive for m in self._members.values())

    def alive_members(self) -> list[PartyMember]:
        """Liste aller lebenden Mitglieder."""
        return [m for m in self._members.values() if m.alive]

    def get_member(self, name: str) -> PartyMember | None:
        """Gibt ein Mitglied zurueck (mit Fuzzy-Match)."""
        resolved = self._fuzzy_match(name)
        if resolved:
            return self._members[resolved]
        return None

    @property
    def members(self) -> dict[str, PartyMember]:
        """Alle Mitglieder (read-only Zugriff)."""
        return dict(self._members)

    # ------------------------------------------------------------------
    # Summary / Detail
    # ------------------------------------------------------------------

    def get_summary(self) -> str:
        """Kompakte Zusammenfassung fuer Prompt-Refresh."""
        lines = ["=== PARTY STATUS ==="]
        for m in self._members.values():
            status = "DEAD" if not m.alive else f"HP:{m.hp}/{m.hp_max}"
            spells = ""
            if m.spells_remaining:
                sp_parts = [
                    f"L{lvl}:{cnt}"
                    for lvl, cnt in sorted(m.spells_remaining.items())
                    if cnt > 0
                ]
                if sp_parts:
                    spells = f" | Spells: {','.join(sp_parts)}"
            lines.append(
                f"  {m.name} ({m.archetype} {m.level}, {m.race}) "
                f"[{status} | AC:{m.ac}]{spells}"
            )
        alive_count = len(self.alive_members())
        total = len(self._members)
        lines.append(f"  --- {alive_count}/{total} alive ---")
        return "\n".join(lines)

    def get_detail(self) -> dict:
        """Vollstaendiges Detail fuer JSON-Export."""
        detail = {
            "members": {},
            "alive_count": len(self.alive_members()),
            "total_count": len(self._members),
            "is_tpk": self.is_tpk(),
            "total_hp": sum(m.hp for m in self._members.values()),
            "total_hp_max": sum(m.hp_max for m in self._members.values()),
        }
        for name, m in self._members.items():
            detail["members"][name] = asdict(m)
        return detail

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_state(self, path: str, turn_number: int) -> None:
        """Atomic JSON write."""
        data = {
            "turn_number": turn_number,
            "party": self.get_detail(),
            "turn_log": self._turn_log[-50:],  # Letzte 50 Eintraege
        }
        save_path = Path(path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = save_path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(save_path))
            logger.info("Party-State gespeichert: %s (Runde %d)", path, turn_number)
        except OSError as exc:
            logger.warning("Party-State Speicherfehler: %s", exc)

    def load_state(self, path: str) -> bool:
        """Restore from saved state. Returns True on success."""
        save_path = Path(path)
        if not save_path.exists():
            logger.info("Kein Party-Save gefunden: %s", path)
            return False
        try:
            with save_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            party_data = data.get("party", {})
            members_data = party_data.get("members", {})
            for name, mdict in members_data.items():
                if name in self._members:
                    m = self._members[name]
                    m.hp = mdict.get("hp", m.hp)
                    m.hp_max = mdict.get("hp_max", m.hp_max)
                    m.alive = mdict.get("alive", True)
                    m.xp = mdict.get("xp", m.xp)
                    m.equipment = mdict.get("equipment", m.equipment)
                    m.spells_remaining = {
                        int(k): v
                        for k, v in mdict.get("spells_remaining", {}).items()
                    }
            self._turn_log = data.get("turn_log", [])
            logger.info(
                "Party-State geladen: %s (%d Mitglieder)",
                path, len(members_data),
            )
            return True
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            logger.warning("Party-State Ladefehler: %s", exc)
            return False
