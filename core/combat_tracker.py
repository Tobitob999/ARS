"""
core/combat_tracker.py — Kampfzustandsverwaltung

Verwaltet alle Kampfteilnehmer (Spieler + NPCs) mit mechanischem
HP-Tracking, Positionen und Bewegungsraten. Wird vom Orchestrator
bei Kampfbeginn initialisiert und bei jedem Angriff aktualisiert.

Der CombatTracker stellt sicher, dass NPCs erst sterben wenn ihre
HP tatsaechlich 0 erreichen — nicht wenn die KI es willkuerlich
entscheidet.

Initiative-System (AD&D 2e):
  - Gruppen-Initiative: d10 pro Seite, niedriger handelt zuerst
  - Waffen-Speed-Factor als Tie-Breaker
  - Attacks per Round: Krieger 1-6: 1/1, 7-12: 3/2, 13+: 2/1
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("ARS.combat_tracker")


@dataclass
class Combatant:
    """Ein Kampfteilnehmer (Spieler oder NPC)."""

    id: str
    name: str
    hp: int
    hp_max: int
    ac: int
    thac0: int
    weapon: str
    damage: str          # Schadenswuerfel, z.B. "1d6", "1d10"
    movement: int        # Bewegungsrate (Felder/Runde)
    position: str        # z.B. "Nahkampf", "Plattform (Fernkampf)"
    is_alive: bool = True
    is_player: bool = False
    # Initiative-System
    initiative: int = 0         # Aktueller Initiative-Wurf
    speed_factor: int = 5       # Waffen-Speed (2=Dolch, 7=Streitaxt)
    attacks_per_round: str = "1/1"  # "1/1", "3/2", "2/1"
    attacks_this_round: int = 0     # Zaehler: wie oft angegriffen
    level: int = 1
    class_group: str = "warrior"    # warrior/priest/rogue/wizard
    # Bewegungs- und Reichweiten-Bridge (Task #14)
    reach: int = 1               # Nahkampf-Reichweite in Feldern (1=Standard, 2=Stangenwaffe, 3=Lanze)
    movement_used: int = 0       # Verbrauchte Bewegung in dieser Runde
    armor_name: str = ""         # Ruestungsname fuer Bewegungsmalus-Lookup


class CombatTracker:
    """
    Verwaltet den Kampfzustand fuer alle Teilnehmer.

    API:
      start_combat(location, npcs, player_stats)  -> Kampf initialisieren
      start_new_round(mechanics)                   -> Runde starten + Initiative
      apply_damage(target_id, amount)              -> Schaden anwenden
      find_target(target_ac, attacker)             -> Ziel ermitteln
      can_attack(combatant_id)                     -> Angriffe uebrig?
      register_attack(combatant_id)                -> Angriff zaehlen
      validate_attack_range(attacker_id, target_id) -> Reichweite pruefen
      consume_movement(combatant_id, tiles)        -> Bewegung verbrauchen
      get_movement_remaining(combatant_id)         -> Restbewegung
      get_status_text()                            -> Formatierter Status
      get_context_for_prompt()                     -> Kontext fuer AI
      is_combat_over()                             -> Alle Feinde tot?
    """

    def __init__(self) -> None:
        self._combatants: dict[str, Combatant] = {}
        self._round: int = 0
        self._active: bool = False
        self._log: list[str] = []
        self._player_initiative: int = 0
        self._monster_initiative: int = 0
        self._player_first: bool = True
        self._grid_engine: Any = None   # Optional GridEngine-Referenz
        self._mechanics: Any = None     # Optional Mechanics-Referenz
        # Regenerations-Tracking: {monster_name: hp_per_round}
        self._regenerating: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Bridge: GridEngine + Mechanics
    # ------------------------------------------------------------------

    def set_grid_engine(self, grid_engine: Any) -> None:
        """Setzt die GridEngine-Referenz fuer Distanzpruefungen."""
        self._grid_engine = grid_engine
        logger.debug("GridEngine-Bridge gesetzt.")

    def set_mechanics(self, mechanics: Any) -> None:
        """Setzt die Mechanics-Referenz fuer Waffen-/Ruestungs-Lookups."""
        self._mechanics = mechanics
        logger.debug("Mechanics-Bridge gesetzt.")

    # ------------------------------------------------------------------
    # Regenerations-System (Session 19)
    # ------------------------------------------------------------------

    def register_regeneration(self, name: str, hp_per_round: int) -> None:
        """
        Registriert Regeneration fuer ein Monster.

        Args:
            name: Monster-Name (wird normalisiert auf lowercase)
            hp_per_round: HP pro Runde (positiver Wert)
        """
        self._regenerating[name.strip()] = max(1, hp_per_round)
        logger.debug("Regeneration registriert: %s +%d HP/Runde", name, hp_per_round)

    def apply_regeneration(self) -> list[str]:
        """
        Heilt alle registrierten Monster um ihre HP-pro-Runde.

        Returns: Liste von Meldungsstrings fuer jede Heilung.
        """
        messages: list[str] = []
        for name, hp_per_round in list(self._regenerating.items()):
            # Combatant per Name suchen (case-insensitive)
            target = self._find_combatant_by_name(name)
            if target is None or not target.is_alive:
                # Totes Monster aus Regenerationsliste entfernen
                if target and not target.is_alive:
                    del self._regenerating[name]
                continue
            old_hp = target.hp
            target.hp = min(target.hp_max, target.hp + hp_per_round)
            healed = target.hp - old_hp
            if healed > 0:
                msg = (
                    f"[REGENERATION] {target.name} regeneriert +{healed} HP "
                    f"({old_hp} -> {target.hp}/{target.hp_max})"
                )
                self._log.append(msg)
                logger.info(msg)
                messages.append(msg)
        return messages

    def clear_regeneration(self) -> None:
        """Loescht alle registrierten Regenerationen (bei Kampfende)."""
        self._regenerating.clear()
        logger.debug("Regenerations-Liste geleert.")

    def _find_combatant_by_name(self, name: str) -> "Combatant | None":
        """Sucht Combatant per Name (case-insensitive, Teilstring-Match)."""
        name_lower = name.strip().lower()
        # Exakter Match
        for c in self._combatants.values():
            if c.name.lower() == name_lower:
                return c
        # Teilstring-Match
        for c in self._combatants.values():
            if name_lower in c.name.lower() or c.name.lower() in name_lower:
                return c
        return None

    # ------------------------------------------------------------------
    # Kampf starten
    # ------------------------------------------------------------------

    def start_combat(
        self,
        location: dict[str, Any],
        npcs: list[dict[str, Any]],
        player_stats: dict[str, Any],
    ) -> None:
        """
        Initialisiert den Kampf aus Location-Daten, NPC-Liste und Spieler-Stats.

        player_stats: {name, hp, hp_max, ac, thac0, weapon, damage, movement,
                       level, class_group, speed_factor, attacks_per_round}
        npcs: Liste von Adventure-NPC-Dicts mit 'stats' Sub-Dict
        """
        self._combatants.clear()
        self._round = 0  # wird bei start_new_round auf 1 gesetzt
        self._active = True
        self._log.clear()

        # Spieler hinzufuegen
        p_weapon = player_stats.get("weapon", "Waffe")
        p_armor = player_stats.get("armor", "")
        p_reach = 1
        p_movement = player_stats.get("movement", 12)
        if self._mechanics:
            p_reach = self._mechanics.lookup_weapon_reach(p_weapon)
            p_movement = self._mechanics.get_effective_movement(p_movement, p_armor)

        self._combatants["player"] = Combatant(
            id="player",
            name=player_stats.get("name", "Spieler"),
            hp=player_stats.get("hp", 10),
            hp_max=player_stats.get("hp_max", 10),
            ac=player_stats.get("ac", 10),
            thac0=player_stats.get("thac0", 20),
            weapon=p_weapon,
            damage=player_stats.get("damage", "1d6"),
            movement=p_movement,
            position="Nahkampf",
            is_player=True,
            level=player_stats.get("level", 1),
            class_group=player_stats.get("class_group", "warrior"),
            speed_factor=player_stats.get("speed_factor", 5),
            attacks_per_round=player_stats.get("attacks_per_round", "1/1"),
            reach=p_reach,
            armor_name=p_armor,
        )

        # NPCs hinzufuegen
        for npc in npcs:
            npc_id = npc.get("id", "unknown")
            stats = npc.get("stats", {})
            # Position aus Beschreibung ableiten
            desc = npc.get("description", "").lower()
            behavior = npc.get("behavior", "").lower()
            if any(kw in desc or kw in behavior for kw in
                   ("bogen", "fernkampf", "plattform", "distanz", "schiesst")):
                position = "Fernkampf"
            else:
                position = "Nahkampf"

            # NPC Hit Dice -> Level-Approximation fuer attacks_per_round
            hd = stats.get("hd", 1)
            n_weapon = stats.get("weapon", "Waffe")
            n_reach = 1
            if self._mechanics:
                n_reach = self._mechanics.lookup_weapon_reach(n_weapon)

            self._combatants[npc_id] = Combatant(
                id=npc_id,
                name=npc.get("name", npc_id),
                hp=stats.get("hp", 4),
                hp_max=stats.get("hp", 4),
                ac=stats.get("ac", 10),
                thac0=stats.get("thac0", 20),
                weapon=n_weapon,
                damage=stats.get("damage", "1d6"),
                movement=stats.get("movement", 9),
                position=position,
                speed_factor=stats.get("speed_factor", 5),
                level=hd,
                class_group="warrior",
                attacks_per_round="1/1",  # Monster: default 1
                reach=n_reach,
            )

        loc_name = location.get("name", "Unbekannt")
        participant_names = [c.name for c in self._combatants.values()]
        logger.info(
            "Kampf gestartet in '%s': %s",
            loc_name, ", ".join(participant_names),
        )
        self._log.append(
            f"Kampf begonnen in {loc_name}"
        )

    # ------------------------------------------------------------------
    # Initiative + Runden
    # ------------------------------------------------------------------

    def start_new_round(self, mechanics: Any) -> dict[str, Any]:
        """
        Beginnt eine neue Kampfrunde:
          1. Rundzaehler erhoehen
          2. Gruppen-Initiative wuerfeln (d10 pro Seite)
          3. Attack-Zaehler fuer alle Combatants zuruecksetzen
        Returns: {player_init, monster_init, player_first, round, detail}
        """
        self._round += 1

        # Attack-Zaehler + Bewegung reset
        for c in self._combatants.values():
            c.attacks_this_round = 0
            c.movement_used = 0

        # Gruppen-Initiative: d10, niedriger = zuerst
        self._player_initiative = mechanics.initiative_roll(0)
        self._monster_initiative = mechanics.initiative_roll(0)

        # Tie-Breaker: niedrigerer Speed-Factor gewinnt
        if self._player_initiative == self._monster_initiative:
            player = self._combatants.get("player")
            p_speed = player.speed_factor if player else 5
            # Niedrigster NPC-Speed
            m_speeds = [
                c.speed_factor for c in self._combatants.values()
                if not c.is_player and c.is_alive
            ]
            m_speed = min(m_speeds) if m_speeds else 5
            self._player_first = p_speed <= m_speed
        else:
            self._player_first = self._player_initiative < self._monster_initiative

        who = "Spieler zuerst" if self._player_first else "Monster zuerst"
        detail = (
            f"--- Runde {self._round} --- "
            f"Initiative: Spieler d10={self._player_initiative} vs "
            f"Monster d10={self._monster_initiative} | {who}"
        )
        self._log.append(detail)
        logger.info(detail)

        # Regeneration am Rundenanfang anwenden
        regen_msgs = self.apply_regeneration()
        if regen_msgs:
            for rmsg in regen_msgs:
                logger.info(rmsg)

        return {
            "player_init": self._player_initiative,
            "monster_init": self._monster_initiative,
            "player_first": self._player_first,
            "round": self._round,
            "detail": detail,
            "regen_messages": regen_msgs,
        }

    def get_max_attacks(self, combatant_id: str) -> int:
        """
        Berechnet max Angriffe fuer diese Runde.

        "1/1" -> immer 1
        "3/2" -> abwechselnd 1 und 2 (ungerade Runde=1, gerade=2)
        "2/1" -> immer 2
        """
        c = self._combatants.get(combatant_id)
        if not c:
            return 0

        apr = c.attacks_per_round
        if apr == "2/1":
            return 2
        if apr == "3/2":
            # Ungerade Runde: 1 Angriff, gerade: 2 Angriffe
            return 2 if self._round % 2 == 0 else 1
        return 1  # "1/1" oder unbekannt

    def can_attack(self, combatant_id: str) -> bool:
        """Prueft ob Combatant noch Angriffe uebrig hat."""
        c = self._combatants.get(combatant_id)
        if not c or not c.is_alive:
            return False
        return c.attacks_this_round < self.get_max_attacks(combatant_id)

    def register_attack(self, combatant_id: str) -> None:
        """Zaehlt einen Angriff fuer diesen Combatant."""
        c = self._combatants.get(combatant_id)
        if c:
            c.attacks_this_round += 1

    # ------------------------------------------------------------------
    # Distanz- & Reichweiten-Bridge
    # ------------------------------------------------------------------

    def validate_attack_range(
        self, attacker_id: str, target_id: str,
    ) -> dict[str, Any]:
        """
        Prueft ob ein Angriff von attacker auf target reichweiten-gueltig ist.

        Returns:
            {valid: bool, distance: int, reach: int, range_mod: int, reason: str}
        """
        attacker = self._combatants.get(attacker_id)
        target = self._combatants.get(target_id)
        if not attacker or not target:
            return {"valid": False, "distance": 999, "reach": 0,
                    "range_mod": 0, "reason": "Teilnehmer nicht gefunden"}

        # Ohne GridEngine: immer gueltig (Fallback)
        if not self._grid_engine:
            return {"valid": True, "distance": 0, "reach": attacker.reach,
                    "range_mod": 0, "reason": "Keine Grid-Engine — kein Distanz-Check"}

        distance = self._grid_engine.get_distance(attacker_id, target_id)
        if distance >= 999:
            return {"valid": True, "distance": 0, "reach": attacker.reach,
                    "range_mod": 0, "reason": "Entities nicht auf Grid"}

        # Fernkampfwaffe?
        range_data = None
        if self._mechanics:
            range_data = self._mechanics.lookup_weapon_range(attacker.weapon)

        if range_data:
            # Fernkampf: 1 Tile = 10ft = ~3.3 Yards → Distanz in Yards
            distance_yards = distance * 10  # 1 Tile = 10ft ≈ 10 Yards (AD&D Vereinfachung)
            range_mod = self._mechanics.get_range_modifier(attacker.weapon, distance_yards)
            if range_mod <= -99:
                return {"valid": False, "distance": distance,
                        "reach": 0, "range_mod": range_mod,
                        "reason": f"Ausser Reichweite ({distance} Felder / {distance_yards} Yards)"}
            return {"valid": True, "distance": distance,
                    "reach": 0, "range_mod": range_mod,
                    "reason": f"Fernkampf: {distance} Felder, Mod {range_mod}"}

        # Nahkampf: Distanz muss <= reach sein
        if distance > attacker.reach:
            return {"valid": False, "distance": distance,
                    "reach": attacker.reach, "range_mod": 0,
                    "reason": f"Zu weit fuer Nahkampf ({distance} > {attacker.reach} Reichweite)"}

        return {"valid": True, "distance": distance,
                "reach": attacker.reach, "range_mod": 0,
                "reason": f"Nahkampf OK ({distance} <= {attacker.reach})"}

    def consume_movement(self, combatant_id: str, tiles: int) -> int:
        """
        Verbraucht Bewegung fuer einen Combatant.

        Returns: Tatsaechlich verbrauchte Tiles (kann weniger sein als angefragt).
        """
        c = self._combatants.get(combatant_id)
        if not c or not c.is_alive:
            return 0
        remaining = c.movement - c.movement_used
        actual = min(tiles, remaining)
        c.movement_used += actual
        return actual

    def get_movement_remaining(self, combatant_id: str) -> int:
        """Gibt die verbleibende Bewegungsrate fuer diese Runde zurueck."""
        c = self._combatants.get(combatant_id)
        if not c or not c.is_alive:
            return 0
        return max(0, c.movement - c.movement_used)

    def get_initiative_order(self) -> list[Combatant]:
        """
        Sortierte Reihenfolge: gewinnende Seite zuerst,
        innerhalb einer Seite nach speed_factor aufsteigend.
        """
        players = [c for c in self._combatants.values()
                    if c.is_player and c.is_alive]
        monsters = [c for c in self._combatants.values()
                    if not c.is_player and c.is_alive]

        players.sort(key=lambda c: c.speed_factor)
        monsters.sort(key=lambda c: c.speed_factor)

        if self._player_first:
            return players + monsters
        return monsters + players

    def is_player_side(self, thac0: int, weapon: str = "") -> bool:
        """Prueft ob ein ANGRIFF-Tag vom Spieler stammt (fuer Sortierung)."""
        player = self._combatants.get("player")
        if not player:
            return False
        if player.thac0 == thac0:
            return True
        if weapon and player.weapon.lower() in weapon.lower():
            return True
        return False

    # ------------------------------------------------------------------
    # Schaden / Heilung
    # ------------------------------------------------------------------

    def apply_damage(self, target_id: str, amount: int) -> dict[str, Any]:
        """
        Wendet Schaden auf ein Ziel an.

        Returns:
            {target, damage, hp_old, hp_new, hp_max, killed}
        """
        combatant = self._combatants.get(target_id)
        if not combatant or not combatant.is_alive:
            return {"target": target_id, "damage": 0, "hp_old": 0,
                    "hp_new": 0, "hp_max": 0, "killed": False}

        hp_old = combatant.hp
        combatant.hp = max(0, combatant.hp - amount)
        killed = combatant.hp <= 0
        if killed:
            combatant.is_alive = False

        result = {
            "target": combatant.name,
            "target_id": target_id,
            "damage": amount,
            "hp_old": hp_old,
            "hp_new": combatant.hp,
            "hp_max": combatant.hp_max,
            "killed": killed,
        }

        log_entry = (
            f"  {combatant.name}: -{amount} HP "
            f"({hp_old} -> {combatant.hp}/{combatant.hp_max})"
        )
        if killed:
            log_entry += " [TOT]"
        self._log.append(log_entry)
        logger.info(log_entry.strip())

        return result

    def heal(self, target_id: str, amount: int) -> dict[str, Any]:
        """Heilt ein Ziel (bis hp_max)."""
        combatant = self._combatants.get(target_id)
        if not combatant or not combatant.is_alive:
            return {"target": target_id, "healed": 0}

        hp_old = combatant.hp
        combatant.hp = min(combatant.hp_max, combatant.hp + amount)
        healed = combatant.hp - hp_old

        return {
            "target": combatant.name,
            "healed": healed,
            "hp_old": hp_old,
            "hp_new": combatant.hp,
            "hp_max": combatant.hp_max,
        }

    # ------------------------------------------------------------------
    # Ziel-Ermittlung
    # ------------------------------------------------------------------

    def find_target(
        self, target_ac: int, attacker: Combatant | None,
    ) -> Combatant | None:
        """
        Ermittelt das Ziel eines Angriffs.

        Logik:
        - Angreifer ist Spieler -> Ziel ist NPC (AC-Match, dann Fallback)
        - Angreifer ist NPC     -> Ziel ist Spieler
        - Angreifer unbekannt   -> Spieler als Fallback
        """
        player = self._combatants.get("player")
        if not player:
            return None

        if attacker:
            if attacker.is_player:
                # Spieler greift NPC an — nach AC matchen
                candidates = [
                    c for c in self._combatants.values()
                    if not c.is_player and c.is_alive and c.ac == target_ac
                ]
                if candidates:
                    return candidates[0]
                # Fallback: erster lebender NPC
                for c in self._combatants.values():
                    if not c.is_player and c.is_alive:
                        return c
                return None
            else:
                # NPC greift Spieler an
                return player if player.is_alive else None

        # Kein Angreifer bekannt — Fallback: Spieler als Ziel
        return player if player.is_alive else None

    def get_attacker(
        self, attacker_thac0: int, weapon: str = "",
    ) -> Combatant | None:
        """
        Ermittelt den Angreifer.

        Reihenfolge:
          1. Exakter THAC0-Match (Spieler oder NPC)
          2. Waffen-Name Match (robust gegen AI-THAC0-Abweichung)
          3. Wenn THAC0 != Spieler -> erster lebender NPC (Fallback)
        """
        player = self._combatants.get("player")
        if player and player.thac0 == attacker_thac0:
            return player

        # NPC mit exaktem THAC0
        for c in self._combatants.values():
            if not c.is_player and c.is_alive and c.thac0 == attacker_thac0:
                return c

        # Fallback: Waffen-Name matchen
        if weapon:
            weapon_lower = weapon.lower()
            for c in self._combatants.values():
                if not c.is_player and c.is_alive and c.weapon.lower() in weapon_lower:
                    return c

        # Letzter Fallback: THAC0 != Spieler -> irgendein lebender NPC
        if player and attacker_thac0 != player.thac0:
            for c in self._combatants.values():
                if not c.is_player and c.is_alive:
                    return c
        return None

    # ------------------------------------------------------------------
    # Status-Anzeige
    # ------------------------------------------------------------------

    def get_status_text(self) -> str:
        """Formatierter Kampfstatus fuer KI-Monitor."""
        init_str = ""
        if self._round > 0:
            who = "Spieler" if self._player_first else "Monster"
            init_str = f" | Init: {self._player_initiative} vs {self._monster_initiative} ({who})"
        lines = [f"=== KAMPF (Runde {self._round}{init_str}) ==="]
        for c in self._combatants.values():
            if c.is_player:
                prefix = "[SPIELER]"
            elif c.is_alive:
                prefix = "[FEIND]  "
            else:
                prefix = "[TOT]    "

            if c.is_alive:
                atk_info = f"{c.attacks_this_round}/{self.get_max_attacks(c.id)}"
                mv_info = f"Bew: {c.movement - c.movement_used}/{c.movement}"
                reach_info = f"Rw: {c.reach}" if c.reach > 1 else ""
                extra = f" | {reach_info}" if reach_info else ""
                lines.append(
                    f"{prefix} {c.name} | HP: {c.hp}/{c.hp_max} | "
                    f"AC: {c.ac} | {c.weapon} (Spd {c.speed_factor}) | "
                    f"Angriffe: {atk_info} | {mv_info}{extra} | {c.position}"
                )
            else:
                lines.append(f"{prefix} {c.name}")
        return "\n".join(lines)

    def get_context_for_prompt(self) -> str:
        """
        Kompakter Kampfstatus fuer AI-System-Kontext.
        Die KI muss Initiative-Reihenfolge und Angriffslimits kennen.
        """
        who = "Spieler handelt zuerst" if self._player_first else "Monster handeln zuerst"
        lines = [f"Aktiver Kampf (Runde {self._round}, {who}):"]
        for c in self._combatants.values():
            if c.is_alive:
                max_atk = self.get_max_attacks(c.id)
                mv_remaining = c.movement - c.movement_used
                reach_str = f", Reichweite: {c.reach} Felder" if c.reach > 1 else ""
                lines.append(
                    f"  - {c.name}: HP {c.hp}/{c.hp_max}, AC {c.ac}, "
                    f"THAC0 {c.thac0}, Waffe: {c.weapon} ({c.damage}), "
                    f"Angriffe: {max_atk}/Runde, "
                    f"Bewegung: {mv_remaining}/{c.movement}{reach_str}, "
                    f"Position: {c.position}"
                )
            else:
                lines.append(f"  - {c.name}: TOT")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Kampf-Lifecycle
    # ------------------------------------------------------------------

    def is_combat_over(self) -> bool:
        """Prueft ob alle Feinde tot sind."""
        return all(
            not c.is_alive
            for c in self._combatants.values()
            if not c.is_player
        )

    def next_round(self) -> None:
        """Naechste Kampfrunde (Legacy — nutze start_new_round)."""
        self._round += 1
        self._log.append(f"--- Runde {self._round} ---")
        logger.debug("Kampfrunde %d", self._round)
        # Regeneration am Rundenanfang anwenden
        self.apply_regeneration()

    def end_combat(self) -> None:
        """Beendet den Kampf."""
        self._active = False
        self.clear_regeneration()
        logger.info("Kampf beendet nach %d Runden.", self._round)
        self._log.append(f"Kampf beendet (Runde {self._round})")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active

    @property
    def round(self) -> int:
        return self._round

    @property
    def player_first(self) -> bool:
        return self._player_first

    @property
    def combatants(self) -> dict[str, Combatant]:
        return self._combatants

    @property
    def log(self) -> list[str]:
        return list(self._log)
