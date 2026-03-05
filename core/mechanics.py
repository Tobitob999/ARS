"""
core/mechanics.py — Würfelmechanik & Probenlogik

Implementiert die regelkonforme Auswertung von:
  - Standardproben (d100 unter Fertigkeitswert)
  - Erfolgsgrade (Regulaer / Hart / Extrem / Kritisch / Patzer)
  - Bonus- und Strafwuerfe
  - THAC0-basierte Angriffswuerfe (AD&D 2e)
  - Rettungswuerfe (AD&D 2e, d20 roll-high)
  - Initiative (AD&D 2e, d10 niedrig = besser)
  - Tabellen-Lookups (THAC0, Saving Throws nach Klasse/Level)
"""

from __future__ import annotations

import random
import re
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.engine import DiceConfig

logger = logging.getLogger("ARS.mechanics")


# ---------------------------------------------------------------------------
# Ergebnis-Dataclass
# ---------------------------------------------------------------------------

@dataclass
class RollResult:
    """Vollständiges Ergebnis eines Würfelwurfs."""
    roll: int                    # Tatsächlich gewürfelter Wert
    target: int                  # Fertigkeitswert / Zielwert
    success_level: str           # "critical" | "extreme" | "hard" | "regular" | "failure" | "fumble"
    is_success: bool
    description: str
    raw_rolls: list[int] = field(default_factory=list)  # Bei Bonus-/Strafwürfen alle Teilergebnisse


# ---------------------------------------------------------------------------
# MechanicsEngine
# ---------------------------------------------------------------------------

class MechanicsEngine:
    """
    Kapselt alle Würfel- und Probenlogik.

    Liest Erfolgsgrad-Schwellen und Würfeltypen direkt aus dem
    DiceConfig-Objekt, das vom ModuleLoader bereitgestellt wird.
    Das bedeutet: die Logik ist Ruleset-agnostisch — andere Module
    können andere Schwellen definieren.
    """

    def __init__(self, dice_config: DiceConfig, tables_data: dict[str, Any] | None = None) -> None:
        self.dice_config = dice_config
        self.tables = tables_data or {}
        self.rng = random.SystemRandom()  # Kryptographisch sicher, für Fairness

    # ------------------------------------------------------------------
    # Kern-Probe
    # ------------------------------------------------------------------

    def skill_check(self, target: int, modifier: int = 0) -> RollResult:
        """
        Führt eine Standardprobe durch (z.B. d100 unter Fertigkeitswert).

        Args:
            target:   Fertigkeitswert (0-100)
            modifier: Positiver Wert = Bonus-Würfel, Negativer = Straf-Würfel

        Returns:
            RollResult mit Erfolgsgrad und Beschreibung
        """
        # AD&D 2e Prozent-Skills: Target > Wuerfelflächen → d100 Modus
        if target > self.dice_config.faces:
            roll = self.rng.randint(1, 100)
            effective_target = max(1, min(target, 100))
            is_success = roll <= effective_target
            if roll == 1:
                level = "critical"
            elif roll <= effective_target // 5:
                level = "extreme"
            elif roll <= effective_target // 2:
                level = "hard"
            elif is_success:
                level = "regular"
            elif roll >= 96:
                level = "fumble"
            else:
                level = "failure"
            description = (
                f"Wurf: {roll} (d100) | Ziel: {effective_target} | "
                f"{'[OK]' if is_success else '[FEHL]'} "
                f"{level.replace('critical', 'Kritisch').replace('extreme', 'Extremer Erfolg').replace('hard', 'Harter Erfolg').replace('regular', 'Regulaerer Erfolg').replace('failure', 'Fehlschlag').replace('fumble', 'PATZER')}"
            )
            logger.debug("Prozent-Probe: Wurf=%d (d100), Ziel=%d, Ergebnis=%s", roll, effective_target, level)
            return RollResult(
                roll=roll, target=effective_target, success_level=level,
                is_success=is_success, description=description, raw_rolls=[roll],
            )

        effective_target = max(1, min(target, self.dice_config.faces))
        roll, raw_rolls = self._roll_with_modifier(modifier)
        level, is_success = self._evaluate(roll, effective_target)
        description = self._format_result(roll, effective_target, level, is_success)
        logger.debug("Probe: Wurf=%d, Ziel=%d, Ergebnis=%s", roll, effective_target, level)
        return RollResult(
            roll=roll,
            target=effective_target,
            success_level=level,
            is_success=is_success,
            description=description,
            raw_rolls=raw_rolls,
        )

    def opposed_check(self, actor_target: int, opponent_target: int) -> dict[str, Any]:
        """Vergleichsprobe: Höherer Erfolgsgrad gewinnt."""
        actor = self.skill_check(actor_target)
        opponent = self.skill_check(opponent_target)

        level_order = ["fumble", "failure", "regular", "hard", "extreme", "critical"]
        actor_rank = level_order.index(actor.success_level)
        opponent_rank = level_order.index(opponent.success_level)

        if actor_rank > opponent_rank:
            winner = "actor"
        elif opponent_rank > actor_rank:
            winner = "opponent"
        else:
            winner = "tie"

        return {
            "actor": actor,
            "opponent": opponent,
            "winner": winner,
            "description": (
                f"Akteur wuerfelt {actor.roll} (Ziel {actor.target}) -> {actor.success_level}. "
                f"Gegner wuerfelt {opponent.roll} (Ziel {opponent.target}) -> {opponent.success_level}. "
                f"Gewinner: {winner}."
            ),
        }

    # ------------------------------------------------------------------
    # Würfelhelfer
    # ------------------------------------------------------------------

    def roll_die(self, faces: int | None = None) -> int:
        """Wirft einen einzelnen Würfel mit <faces> Seiten."""
        faces = faces or self.dice_config.faces
        return self.rng.randint(1, faces)

    def roll_dice(self, count: int, faces: int | None = None) -> list[int]:
        """Wirft <count> Wuerfel und gibt alle Einzelergebnisse zurueck."""
        return [self.roll_die(faces) for _ in range(count)]

    def roll_expression(self, expr: str) -> int:
        """
        Wirft einen Wuerfelausdruck wie '1d6', '2d4' oder eine feste Zahl.
        Wird fuer STABILITAET_VERLUST-Tags mit variablen Schadenswuerfen benoetigt.

        Beispiele:
          '1d6'  -> wuerfelt 1d6
          '2d4'  -> wuerfelt 2d4
          '3'    -> gibt 3 zurueck
        """
        expr = expr.strip().lower()
        m = re.match(r"^(\d+)d(\d+)([+-]\d+)?$", expr)
        if m:
            count = int(m.group(1))
            faces = int(m.group(2))
            modifier = int(m.group(3)) if m.group(3) else 0
            return sum(self.roll_die(faces) for _ in range(count)) + modifier
        try:
            return int(expr)
        except ValueError:
            logger.warning(
                "Unbekannter Wuerfelausdruck '%s' -- nehme Wert 1 an.", expr
            )
            return 1

    def roll_damage(self, expr: str) -> tuple[int, str]:
        """
        Wirft einen Schadenswurf und gibt (Ergebnis, Detail-String) zurueck.

        Beispiele:
          '1d6'   -> (4, '1d6: [4] = 4')
          '2d4'   -> (6, '2d4: [3, 3] = 6')
          '1d8+2' -> (7, '1d8+2: [5]+2 = 7')
          '5'     -> (5, '5')
        """
        expr = expr.strip().lower()

        # NdN+M oder NdN-M Format
        m = re.match(r"^(\d+)d(\d+)([+-]\d+)?$", expr)
        if m:
            count = int(m.group(1))
            faces = int(m.group(2))
            modifier = int(m.group(3)) if m.group(3) else 0
            rolls = [self.roll_die(faces) for _ in range(count)]
            total = sum(rolls) + modifier
            rolls_str = ", ".join(str(r) for r in rolls)
            if modifier > 0:
                detail = f"{expr}: [{rolls_str}]+{modifier} = {total}"
            elif modifier < 0:
                detail = f"{expr}: [{rolls_str}]{modifier} = {total}"
            else:
                detail = f"{expr}: [{rolls_str}] = {total}"
            return max(0, total), detail

        # Feste Zahl
        try:
            val = int(expr)
            return val, str(val)
        except ValueError:
            logger.warning(
                "Unbekannter Schadenswurf '%s' -- nehme 1 an.", expr
            )
            return 1, "1"

    # ------------------------------------------------------------------
    # AD&D 2e — THAC0-basierter Kampf
    # ------------------------------------------------------------------

    def attack_roll(self, thac0: int, target_ac: int, modifiers: int = 0) -> RollResult:
        """
        AD&D 2e Angriffswurf: d20 + Modifikatoren >= THAC0 - Ziel-AC.

        Args:
            thac0:     THAC0-Wert des Angreifers
            target_ac: Ruestungsklasse des Ziels (10 = ungeruestet, 0 = Vollplatte+Schild)
            modifiers: Summe aller Angriffsmodifikatoren (STR, Magie, Situation)

        Returns:
            RollResult mit Trefferergebnis
        """
        needed = thac0 - target_ac
        roll = self.roll_die(20)
        modified_roll = roll + modifiers

        # Natural 20 = Auto-Hit, Natural 1 = Auto-Miss
        if roll == 20:
            is_hit = True
            level = "critical"
        elif roll == 1:
            is_hit = False
            level = "fumble"
        else:
            is_hit = modified_roll >= needed
            level = "regular" if is_hit else "failure"

        description = (
            f"Angriff: d20={roll}"
            f"{'+' + str(modifiers) if modifiers > 0 else ('-' + str(abs(modifiers)) if modifiers < 0 else '')}"
            f" = {modified_roll} | Benoetigt: {needed} (THAC0 {thac0} vs AC {target_ac})"
            f" | {'TREFFER' if is_hit else 'VERFEHLT'}"
            f"{' (Nat 20!)' if roll == 20 else ''}"
            f"{' (Nat 1!)' if roll == 1 else ''}"
        )
        logger.debug("Attack: roll=%d mod=%d needed=%d hit=%s", roll, modifiers, needed, is_hit)
        return RollResult(
            roll=roll,
            target=needed,
            success_level=level,
            is_success=is_hit,
            description=description,
            raw_rolls=[roll],
        )

    def saving_throw(self, target: int, modifiers: int = 0) -> RollResult:
        """
        AD&D 2e Rettungswurf: d20 + Modifikatoren >= Zielwert (roll-high).

        Args:
            target:    Rettungswurf-Zielwert (aus Tabelle 60)
            modifiers: Bonusse/Mali (pos = Vorteil, neg = Nachteil)

        Returns:
            RollResult mit Ergebnis
        """
        roll = self.roll_die(20)
        modified_roll = roll + modifiers
        is_success = modified_roll >= target

        if roll == 20:
            is_success = True
            level = "critical"
        elif roll == 1:
            is_success = False
            level = "fumble"
        else:
            level = "regular" if is_success else "failure"

        description = (
            f"Rettungswurf: d20={roll}"
            f"{'+' + str(modifiers) if modifiers > 0 else ('-' + str(abs(modifiers)) if modifiers < 0 else '')}"
            f" = {modified_roll} | Benoetigt: {target}"
            f" | {'GERETTET' if is_success else 'FEHLSCHLAG'}"
        )
        logger.debug("Save: roll=%d mod=%d target=%d success=%s", roll, modifiers, target, is_success)
        return RollResult(
            roll=roll,
            target=target,
            success_level=level,
            is_success=is_success,
            description=description,
            raw_rolls=[roll],
        )

    def initiative_roll(self, modifier: int = 0) -> int:
        """
        AD&D 2e Initiative: d10, niedrigerer Wert handelt zuerst.

        Args:
            modifier: Waffengeschwindigkeit, Zauberdauer etc.

        Returns:
            Modifizierter Initiativewert (niedrig = besser)
        """
        roll = self.roll_die(10)
        result = roll + modifier
        logger.debug("Initiative: d10=%d mod=%d total=%d", roll, modifier, result)
        return result

    # ------------------------------------------------------------------
    # Tabellen-Lookups (AD&D 2e)
    # ------------------------------------------------------------------

    def lookup_thac0(self, class_group: str, level: int) -> int:
        """
        Schlaegt THAC0 in der Klassengruppen-Tabelle nach.

        Args:
            class_group: "warrior", "priest", "rogue", "wizard"
            level: Charakterlevel (1-20)

        Returns:
            THAC0-Wert. Fallback: 20.
        """
        thac0_table = self.tables.get("thac0_by_group", {})
        group_data = thac0_table.get(class_group.lower())
        if not group_data:
            logger.warning("Keine THAC0-Tabelle fuer Gruppe '%s'", class_group)
            return 20
        idx = max(0, min(level - 1, len(group_data) - 1))
        return group_data[idx]

    def lookup_saving_throw(self, class_group: str, level: int, save_type: int) -> int:
        """
        Schlaegt Rettungswurf-Zielwert in Tabelle 60 nach.

        Args:
            class_group: "warrior", "priest", "rogue", "wizard"
            level: Charakterlevel
            save_type: 0=Para/Poison, 1=Rod/Staff, 2=Petrif, 3=Breath, 4=Spell

        Returns:
            Rettungswurf-Zielwert. Fallback: 20.
        """
        save_table = self.tables.get("saving_throws", {})
        group_data = save_table.get(class_group.lower())
        if not group_data:
            logger.warning("Keine Save-Tabelle fuer Gruppe '%s'", class_group)
            return 20

        # Level-Range finden (z.B. "1-2", "3-4", "17+")
        for level_range, values in group_data.items():
            if level_range.startswith("_"):
                continue  # Metadaten ueberspringen
            if "+" in level_range:
                min_lvl = int(level_range.replace("+", ""))
                if level >= min_lvl:
                    return values[save_type] if save_type < len(values) else 20
            elif "-" in level_range:
                parts = level_range.split("-")
                min_lvl, max_lvl = int(parts[0]), int(parts[1])
                if min_lvl <= level <= max_lvl:
                    return values[save_type] if save_type < len(values) else 20

        logger.warning("Kein Save-Eintrag fuer %s Level %d", class_group, level)
        return 20

    def lookup_class_group(self, class_name: str) -> str:
        """
        Ordnet einen Klassennamen der Klassengruppe zu.

        Args:
            class_name: z.B. "fighter", "cleric", "thief", "mage"

        Returns:
            Klassengruppe: "warrior", "priest", "rogue", "wizard"
        """
        mapping = self.tables.get("class_to_group", {})
        return mapping.get(class_name.lower(), "warrior")

    def lookup_speed_factor(self, weapon_name: str) -> int:
        """
        Sucht Waffen-Speed-Factor aus den Item-Daten.

        Durchsucht data/lore/add_2e/items/*.json nach passender Waffe.
        Fallback: 5 (mittlerer Speed).
        """
        import json
        from pathlib import Path

        if not weapon_name:
            return 5

        items_dir = Path(__file__).parent.parent / "data" / "lore" / "add_2e" / "items"
        if not items_dir.exists():
            return 5

        weapon_lower = weapon_name.lower().replace("+", "").strip()
        # Versuche exakten Dateinamen (z.B. "longsword" -> "longsword.json")
        for json_file in items_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                file_weapon = json_file.stem.replace("_", " ").lower()
                item_name = data.get("name", file_weapon).lower()
                # Match: Dateiname oder Name im JSON
                if file_weapon in weapon_lower or weapon_lower in item_name:
                    sf = data.get("speed_factor", 5)
                    logger.debug("Speed-Factor fuer '%s': %d", weapon_name, sf)
                    return sf
            except Exception:
                continue

        logger.debug("Kein Speed-Factor fuer '%s' — Fallback 5", weapon_name)
        return 5

    def lookup_attacks_per_round(self, class_group: str, level: int) -> str:
        """
        Schlaegt Angriffe pro Runde nach (Table 15).

        Nur Warrior-Klassen bekommen Extraangriffe.
        Returns: "1/1", "3/2" oder "2/1"
        """
        if class_group != "warrior":
            return "1/1"

        apr_table = self.tables.get("attacks_per_round", {})
        warrior_data = apr_table.get("warrior", [])
        for entry in warrior_data:
            levels_str = entry.get("levels", "")
            attacks = entry.get("attacks", "1/1")
            if "+" in levels_str:
                min_lvl = int(levels_str.replace("+", ""))
                if level >= min_lvl:
                    return attacks
            elif "-" in levels_str:
                parts = levels_str.split("-")
                if int(parts[0]) <= level <= int(parts[1]):
                    return attacks
        return "1/1"

    # ------------------------------------------------------------------
    # Waffen-Reichweite und Ruestungs-Bewegung
    # ------------------------------------------------------------------

    def lookup_weapon_reach(self, weapon_name: str) -> int:
        """
        Sucht die Nahkampf-Reichweite einer Waffe (in Feldern, 1 Feld = 10 ft).

        Stangenwaffen (Halberd, Spear, Trident, Quarter Staff) = 2 Felder.
        Lanzen = 3 Felder. Standard = 1 Feld.
        """
        if not weapon_name:
            return 1
        wn = weapon_name.lower()
        for entry in self.tables.get("melee_weapons", []):
            if entry["name"].lower() in wn or wn in entry["name"].lower():
                return entry.get("reach", 1)
        return 1

    def lookup_weapon_range(self, weapon_name: str) -> dict | None:
        """
        Sucht Fernkampf-Reichweiten einer Waffe (short/medium/long in Yards).

        Returns: {"range_s": int, "range_m": int, "range_l": int, "rof": str}
                 oder None wenn keine Fernkampfwaffe.
        """
        if not weapon_name:
            return None
        wn = weapon_name.lower()
        for entry in self.tables.get("missile_weapons", []):
            if entry["name"].lower() in wn or wn in entry["name"].lower():
                return {
                    "range_s": entry.get("range_s", 0),
                    "range_m": entry.get("range_m", 0),
                    "range_l": entry.get("range_l", 0),
                    "rof": entry.get("rof", "1"),
                }
        return None

    def get_range_modifier(self, weapon_name: str, distance_yards: int) -> int:
        """
        Berechnet den Fernkampf-Modifikator basierend auf Distanz.

        Returns:
            0  = Kurzreichweite (kein Malus)
            -2 = Mittelreichweite
            -5 = Langreichweite
            -99 = Ausserhalb maximaler Reichweite (Angriff unmoeglich)
        """
        rng = self.lookup_weapon_range(weapon_name)
        if rng is None:
            return 0  # Nahkampfwaffe, kein Range-Mod

        if distance_yards <= rng["range_s"]:
            return 0
        elif distance_yards <= rng["range_m"]:
            return self.tables.get("combat_modifiers", {}).get("missile_medium_range", -2)
        elif distance_yards <= rng["range_l"]:
            return self.tables.get("combat_modifiers", {}).get("missile_long_range", -5)
        else:
            return -99  # Ausser Reichweite

    def lookup_armor_movement_penalty(self, armor_name: str) -> int:
        """
        Sucht den Bewegungsmalus einer Ruestung.

        Returns: 0 (Leder), -3 (Kette), -6 (Platte), etc.
        """
        if not armor_name:
            return 0
        an = armor_name.lower()
        for entry in self.tables.get("armor_catalog", []):
            if entry["name"].lower() in an or an in entry["name"].lower():
                return entry.get("movement_penalty", 0)
        return 0

    def get_effective_movement(self, base_movement: int, armor_name: str) -> int:
        """
        Berechnet die effektive Bewegungsrate nach Ruestungsmalus.

        Args:
            base_movement: Basis-Bewegungsrate (z.B. 12 fuer Menschen)
            armor_name: Name der getragenen Ruestung

        Returns:
            Effektive Bewegungsrate (Minimum 1 Feld)
        """
        penalty = self.lookup_armor_movement_penalty(armor_name)
        return max(1, base_movement + penalty)

    # ------------------------------------------------------------------
    # Interne Helfer
    # ------------------------------------------------------------------

    def _roll_with_modifier(self, modifier: int) -> tuple[int, list[int]]:
        """
        modifier > 0: Bonus-Würfe (niedrigstes Ergebnis gilt für d100)
        modifier < 0: Straf-Würfe (höchstes Ergebnis gilt für d100)
        modifier = 0: Einzelwurf
        """
        count = 1 + abs(modifier)
        rolls = self.roll_dice(count, self.dice_config.faces)
        if modifier > 0:
            chosen = min(rolls)
        elif modifier < 0:
            chosen = max(rolls)
        else:
            chosen = rolls[0]
        return chosen, rolls

    def _evaluate(self, roll: int, target: int) -> tuple[str, bool]:
        """Wertet einen Wurf gegen die Erfolgsgrad-Schwellen des Rulesets aus."""
        levels = self.dice_config.success_levels

        # Patzer (Fumble) — schlechteste automatische Fehler
        fumble_threshold = levels.get("fumble", 96)
        if roll >= fumble_threshold:
            return "fumble", False

        # Kritischer Erfolg — bestes automatisches Ergebnis
        critical_threshold = levels.get("critical", 1)
        if roll <= critical_threshold:
            return "critical", True

        if roll > target:
            return "failure", False

        # Erfolgsgrade unterhalb des Fertigkeitswerts
        extreme_threshold = int(target * levels.get("extreme", 0.2))
        hard_threshold = int(target * levels.get("hard", 0.5))

        if roll <= extreme_threshold:
            return "extreme", True
        if roll <= hard_threshold:
            return "hard", True
        return "regular", True

    def _format_result(self, roll: int, target: int, level: str, is_success: bool) -> str:
        labels = {
            "critical": "KRITISCHER ERFOLG",
            "extreme":  "Extremer Erfolg",
            "hard":     "Harter Erfolg",
            "regular":  "Regulärer Erfolg",
            "failure":  "Misserfolg",
            "fumble":   "PATZER",
        }
        outcome = "[OK]" if is_success else "[!!]"
        label = labels.get(level, level)
        return f"Wurf: {roll} | Ziel: {target} | {outcome} {label}"

    # ------------------------------------------------------------------
    # AD&D 2e — Moral-Probe (Morale Check)
    # ------------------------------------------------------------------

    def morale_check(self, morale_value: int, modifiers: int = 0) -> RollResult:
        """
        AD&D 2e Moral-Probe: 2d6 gegen Moral-Wert.

        Ergebnis <= Moral-Wert: Monster bleibt und kaempft.
        Ergebnis >  Moral-Wert: Monster flieht oder ergibt sich.

        Args:
            morale_value: Moral-Wert des Monsters (2-20).
                          Typische Werte: Goblin=7, Hobgoblin=8, Oger=10, Drache=16
            modifiers:    Situationsmodifikatoren.
                          Anführer tot=-2, Übermacht=-1, gute Moral=+2

        Returns:
            RollResult mit is_success=True = Monster bleibt.
        """
        d1 = self.roll_die(6)
        d2 = self.roll_die(6)
        raw_total = d1 + d2
        effective_morale = max(2, min(morale_value + modifiers, 20))
        is_success = raw_total <= effective_morale

        if is_success:
            level = "regular"
            outcome_str = "BLEIBT (kaempft weiter)"
        else:
            level = "failure"
            outcome_str = "FLIEHT (oder ergibt sich)"

        description = (
            f"Moral-Probe: 2d6=[{d1}+{d2}]={raw_total}"
            f" | Moral: {morale_value}"
            f"{('+' + str(modifiers)) if modifiers > 0 else (str(modifiers) if modifiers < 0 else '')}"
            f"={effective_morale}"
            f" | {outcome_str}"
        )
        logger.debug(
            "Moral-Probe: 2d6=%d Moral=%d (mod=%d) -> %s",
            raw_total, morale_value, modifiers, outcome_str,
        )
        return RollResult(
            roll=raw_total,
            target=effective_morale,
            success_level=level,
            is_success=is_success,
            description=description,
            raw_rolls=[d1, d2],
        )

    # ------------------------------------------------------------------
    # AD&D 2e — NPC-Reaktionswurf (Reaction Roll)
    # ------------------------------------------------------------------

    def reaction_roll(self, cha_modifier: int = 0) -> dict[str, Any]:
        """
        AD&D 2e NPC-Reaktionswurf: 2d6 + CHA-Modifikator.

        Bestimmt die erste Reaktion eines unbekannten NSC auf die Gruppe.

        Args:
            cha_modifier: CHA-Reaktionsmodifikator des Sprechers
                          (z.B. CHA 17 = +2, CHA 6 = -1)

        Returns:
            dict mit:
              roll (int): Rohergebnis 2d6
              modified_roll (int): Modifiziertes Ergebnis
              reaction_level (str): "hostile_attack" | "hostile" | "neutral" | "friendly" | "enthusiastic"
              description (str): Deutsche Beschreibung
        """
        d1 = self.roll_die(6)
        d2 = self.roll_die(6)
        raw = d1 + d2
        modified = raw + cha_modifier

        if modified <= 2:
            reaction_level = "hostile_attack"
            description = "Feindlich — greift sofort an"
        elif modified <= 5:
            reaction_level = "hostile"
            description = "Feindlich — moeglicherweise aggressiv"
        elif modified <= 8:
            reaction_level = "neutral"
            description = "Neutral — unsicher, abwartend"
        elif modified <= 11:
            reaction_level = "friendly"
            description = "Freundlich — interessiert, gespraechsbereit"
        else:
            reaction_level = "enthusiastic"
            description = "Begeistert — hilfsbereit, wohlgesonnen"

        logger.debug(
            "Reaktionswurf: 2d6=%d CHA-Mod=%d total=%d -> %s",
            raw, cha_modifier, modified, reaction_level,
        )
        return {
            "roll": raw,
            "modified_roll": modified,
            "reaction_level": reaction_level,
            "description": (
                f"Reaktionswurf: 2d6=[{d1}+{d2}]={raw}"
                f"{('+' + str(cha_modifier)) if cha_modifier > 0 else (str(cha_modifier) if cha_modifier < 0 else '')}"
                f"={modified} | {description}"
            ),
        }

    # ------------------------------------------------------------------
    # AD&D 2e — Untote vertreiben (Turn Undead)
    # ------------------------------------------------------------------

    # Turn-Undead-Tabelle (PHB Table 61).
    # Zeilen = Kleriker-Level 1-14+; Spalten = Untoten-HD-Kategorien.
    # Werte: int = benoetigtes 2d6-Minimum, "T" = automatisch vertrieben,
    #        "D" = automatisch zerstoert, "-" = unmoeglich.
    _TURN_TABLE: list[list[Any]] = [
        # Skel  Zomb  Ghoul  Shadow  Wight  Wraith  Mummy  Spectre  Vampire  Ghost  Lich  Special
        [10,    13,   16,    19,     20,    "-",    "-",   "-",     "-",     "-",   "-",  "-"],   # L1
        [ 7,    10,   13,    16,     19,    20,     "-",   "-",     "-",     "-",   "-",  "-"],   # L2
        [ 4,     7,   10,    13,     16,    19,     20,    "-",     "-",     "-",   "-",  "-"],   # L3
        ["T",    4,    7,    10,     13,    16,     19,    20,      "-",     "-",   "-",  "-"],   # L4
        ["T",   "T",   4,     7,     10,    13,     16,    19,      20,      "-",   "-",  "-"],   # L5
        ["D",   "T",  "T",    4,      7,    10,     13,    16,      19,      20,    "-",  "-"],   # L6
        ["D",   "D",  "T",   "T",     4,     7,     10,    13,      16,      19,    20,   "-"],   # L7
        ["D",   "D",  "D",   "T",    "T",    4,      7,    10,      13,      16,    19,   20],    # L8
        ["D",   "D",  "D",   "D",    "T",   "T",     4,     7,      10,      13,    16,   19],   # L9
        ["D",   "D",  "D",   "D",    "D",   "T",    "T",    4,       7,      10,    13,   16],   # L10
        ["D",   "D",  "D",   "D",    "D",   "D",    "T",   "T",      4,       7,    10,   13],   # L11
        ["D",   "D",  "D",   "D",    "D",   "D",    "D",   "T",     "T",      4,     7,   10],   # L12
        ["D",   "D",  "D",   "D",    "D",   "D",    "D",   "D",     "T",     "T",    4,    7],   # L13
        ["D",   "D",  "D",   "D",    "D",   "D",    "D",   "D",     "D",     "T",   "T",   4],   # L14+
    ]

    # Mapping von Untoten-HD auf Spalten-Index in _TURN_TABLE
    _UNDEAD_COLUMN: dict[str | float, int] = {
        "skeleton": 0, "zombie": 1, "ghoul": 2,
        "shadow": 3, "wight": 4, "ghast": 4,
        "wraith": 5, "mummy": 6, "spectre": 7, "specter": 7,
        "vampire": 8, "ghost": 9, "lich": 10, "special": 11,
        # Numerische HD-Schluessen
        1: 0, 2: 1, 3: 2, 3.5: 3, 4: 4,
        5: 5, 6: 6, 7: 7, 8: 8, 10: 9, 11: 10, 13: 11,
    }

    def turn_undead(self, cleric_level: int, undead_hd: int | float | str) -> dict[str, Any]:
        """
        AD&D 2e Untote vertreiben (PHB Table 61).

        Args:
            cleric_level: Level des Klerikers (1-20+, kap auf 14 fuer die Tabelle)
            undead_hd:    HD des Untoten als Zahl (1, 2, 3.5 ...) oder
                          als Name ("skeleton", "vampire", "lich", "special")

        Returns:
            dict mit:
              success (bool): Ob vertrieben/zerstoert
              result_type (str): "turned" | "destroyed" | "rolled" | "failed" | "impossible"
              roll (int | None): 2d6-Wuerfelergebnis (bei rolled/failed), sonst None
              target (int | None): Benoetigter Mindestwurf, sonst None
              description (str): Ausfuehrliche Beschreibung
        """
        # Tabellen-Zeilenindex (0-13, ab Level 14+ bleibt Zeile 13)
        row_idx = max(0, min(cleric_level - 1, 13))

        # Spalten-Index ermitteln
        if isinstance(undead_hd, str):
            col_idx = self._UNDEAD_COLUMN.get(undead_hd.lower())
        else:
            col_idx = self._UNDEAD_COLUMN.get(undead_hd)

        if col_idx is None:
            # Unbekannter Untoten-Typ: Fallback auf numerischen Naherungs-Index
            if isinstance(undead_hd, (int, float)):
                # HD <= 1 -> Skelett, HD 2 -> Zombie, etc.
                if undead_hd <= 1:
                    col_idx = 0
                elif undead_hd <= 2:
                    col_idx = 1
                elif undead_hd <= 3:
                    col_idx = 2
                elif undead_hd <= 4:
                    col_idx = 4
                elif undead_hd <= 5:
                    col_idx = 5
                elif undead_hd <= 6:
                    col_idx = 6
                elif undead_hd <= 7:
                    col_idx = 7
                elif undead_hd <= 8:
                    col_idx = 8
                elif undead_hd <= 10:
                    col_idx = 9
                else:
                    col_idx = 11
            else:
                col_idx = 11  # Unbekannt -> Special

        table_value = self._TURN_TABLE[row_idx][col_idx]

        # Ergebnis auswerten
        if table_value == "-":
            logger.debug(
                "Untote vertreiben: Kleriker L%d vs col %d -> UNMOEGLICH",
                cleric_level, col_idx,
            )
            return {
                "success": False,
                "result_type": "impossible",
                "roll": None,
                "target": None,
                "description": (
                    f"Untote vertreiben: Kleriker L{cleric_level} kann diesen Untoten "
                    f"(HD={undead_hd}) nicht vertreiben — zu mächtig."
                ),
            }

        if table_value == "T":
            logger.debug("Untote vertreiben: Kleriker L%d -> AUTOMATISCH VERTRIEBEN", cleric_level)
            return {
                "success": True,
                "result_type": "turned",
                "roll": None,
                "target": None,
                "description": (
                    f"Untote vertreiben: Kleriker L{cleric_level} — "
                    f"AUTOMATISCH VERTRIEBEN (HD={undead_hd})."
                ),
            }

        if table_value == "D":
            logger.debug("Untote vertreiben: Kleriker L%d -> AUTOMATISCH ZERSTOERT", cleric_level)
            return {
                "success": True,
                "result_type": "destroyed",
                "roll": None,
                "target": None,
                "description": (
                    f"Untote vertreiben: Kleriker L{cleric_level} — "
                    f"AUTOMATISCH ZERSTOERT (HD={undead_hd})."
                ),
            }

        # Normaler Wurf: 2d6 >= table_value
        d1 = self.roll_die(6)
        d2 = self.roll_die(6)
        roll_total = d1 + d2
        success = roll_total >= table_value

        logger.debug(
            "Untote vertreiben: Kleriker L%d 2d6=%d Benoetigt=%d -> %s",
            cleric_level, roll_total, table_value, "Erfolg" if success else "Fehlschlag",
        )
        return {
            "success": success,
            "result_type": "turned" if success else "failed",
            "roll": roll_total,
            "target": int(table_value),
            "description": (
                f"Untote vertreiben: Kleriker L{cleric_level} wuerfelt 2d6=[{d1}+{d2}]={roll_total}"
                f" | Benoetigt: {table_value}"
                f" | {'VERTRIEBEN' if success else 'FEHLGESCHLAGEN'} (HD={undead_hd})."
            ),
        }

    # ------------------------------------------------------------------
    # AD&D 2e — Schatz wuerfeln (Treasure Roll)
    # ------------------------------------------------------------------

    # Vereinfachte Schatz-Tabelle.
    # Muenzen-Format: (wuerfelanzahl, wuerfelseiten, multiplikator, prozent_chance)
    # Gems/Schmuck-Format: (wuerfelanzahl, wuerfelseiten, prozent_chance)
    # Magie-Format: (anzahl_magische_gegenstaende, prozent_chance)
    _TREASURE_TYPES: dict[str, dict[str, Any]] = {
        "A": {
            "cp":      (1, 6, 1000, 25),
            "sp":      (1, 6, 1000, 30),
            "ep":      (1, 6, 1000, 20),
            "gp":      (1, 10, 1000, 40),
            "pp":      (1, 4, 100, 25),
            "gems":    (4, 10, 60),
            "jewelry": (3, 6, 50),
            "magic":   (3, 30),
        },
        "B": {
            "cp":      (1, 8, 1000, 50),
            "sp":      (1, 6, 1000, 25),
            "ep":      (1, 4, 1000, 25),
            "gp":      (1, 3, 1000, 25),
            "gems":    (1, 6, 25),
            "jewelry": (1, 6, 25),
            "magic":   (1, 10),
        },
        "C": {
            "cp":      (1, 12, 1000, 20),
            "sp":      (1, 4, 1000, 30),
            "ep":      (1, 4, 1000, 10),
            "gems":    (1, 4, 25),
            "jewelry": (1, 4, 25),
            "magic":   (2, 10),
        },
        "D": {
            "cp":      (1, 8, 1000, 10),
            "sp":      (1, 12, 1000, 15),
            "gp":      (1, 6, 1000, 60),
            "gems":    (1, 8, 30),
            "jewelry": (1, 4, 30),
            "magic":   (2, 15),
        },
        "E": {
            "cp":      (1, 10, 1000, 5),
            "sp":      (1, 12, 1000, 30),
            "ep":      (1, 6, 1000, 25),
            "gp":      (1, 8, 1000, 25),
            "gems":    (1, 10, 15),
            "jewelry": (1, 4, 10),
            "magic":   (3, 25),
        },
        "H": {
            "cp":      (3, 8, 1000, 25),
            "sp":      (1, 100, 1000, 40),
            "ep":      (1, 4, 10000, 40),
            "gp":      (1, 6, 10000, 55),
            "pp":      (1, 8, 1000, 25),
            "gems":    (1, 100, 50),
            "jewelry": (3, 10, 50),
            "magic":   (4, 15),
        },
        # ── Typ F (DMG Table 84) ──────────────────────────────────────
        "F": {
            "sp":      (1, 8, 1000, 10),
            "ep":      (1, 10, 1000, 15),
            "gp":      (1, 4, 1000, 40),
            "pp":      (1, 4, 200, 35),
            "gems":    (1, 4, 20),
            "jewelry": (1, 4, 10),
            "magic":   (1, 15),
        },
        # ── Typ G (DMG Table 84) ──────────────────────────────────────
        "G": {
            "gp":      (1, 4, 10000, 50),
            "pp":      (1, 6, 1000, 50),
            "gems":    (3, 6, 25),
            "jewelry": (1, 10, 25),
            "magic":   (4, 30),
        },
        # ── Individuelle Typen I–N (pro Monster, DMG Table 84) ───────
        # Format gleich wie Lair-Typen, nur kleinere Mengen.
        "I": {
            "pp":   (3, 8, 1, 30),
        },
        "J": {
            "cp":   (3, 8, 1, 45),
            "sp":   (3, 8, 1, 45),
        },
        "K": {
            "cp":   (3, 8, 1, 90),
            "sp":   (3, 8, 1, 90),
        },
        "L": {
            "gems": (1, 4, 50),
        },
        "M": {
            "gp":   (2, 4, 1, 40),
            "pp":   (4, 6, 1, 50),
        },
        "N": {
            "magic": (2, 4),
        },
        # ── Typ O (DMG Table 84) ─────────────────────────────────────
        "O": {
            "sp":   (1, 4, 1, 25),
            "gp":   (1, 4, 1, 25),
        },
        # ── Typ P (DMG Table 84) — Potions only ─────────────────────
        "P": {
            "magic": (1, 100),
        },
        # ── Typ Q (DMG Table 84) — Scrolls only ─────────────────────
        "Q": {
            "magic": (1, 100),
        },
    }

    # ── DMG Table 85: Gem Base Value ─────────────────────────────────────
    # Format: (d100_max, base_gp, tier_name, example_stones)
    # Variation (DMG Table 86) wird in roll_gem() angewendet.
    _GEM_VALUE_TABLE: list[tuple[int, int, str, list[str]]] = [
        (25,    10, "Ornamental", [
            "Azurit", "Banded Achat", "Blauer Quarz", "Augen-Achat",
            "Haematit", "Lapislazuli", "Malachit", "Moos-Achat",
            "Obsidian", "Rhodochrosit", "Tigerauge", "Tuerkis",
        ]),
        (50,    50, "Halbedelstein", [
            "Blutstein", "Karneol", "Chalcedon", "Chrysopras",
            "Citrin", "Jaspis", "Mondstein", "Onyx",
            "Bergkristall", "Sardonyx", "Rauchquarz", "Rosenquarz", "Zirkon",
        ]),
        (70,   100, "Schmuckstein", [
            "Bernstein", "Alexandrit", "Amethyst", "Chrysoberyll",
            "Koralle", "Granat", "Jade", "Jet", "Perle",
        ]),
        (90,   500, "Edelstein", [
            "Aquamarin", "Peridot", "Spinell", "Topas", "Turmalin",
        ]),
        (99,  1000, "Kostbarer Edelstein", [
            "Opal", "Orient. Amethyst", "Orient. Topas", "Saphir",
        ]),
        (100, 5000, "Juwel", [
            "Schwarzer Opal", "Schwarzer Saphir", "Diamant",
            "Smaragd", "Jacinth", "Orient. Smaragd", "Rubin",
            "Sternrubin", "Sternsaphir",
        ]),
    ]

    # ── DMG Table 87: Objects of Art ─────────────────────────────────────
    # Format: (d100_max, min_gp_value, max_gp_value)
    _ART_OBJECT_TABLE: list[tuple[int, int, int]] = [
        (10,    10,    40),
        (25,    41,   180),
        (40,   181,   300),
        (50,   200,  1200),
        (60,   300,  1800),
        (70,   400,  2400),
        (80,   500,  3000),
        (85,  1000,  4000),
        (90,  1000,  6000),
        (95,  2000,  8000),
        (99,  2000, 12000),
        (100, 2000, 20000),
    ]

    # ── DMG Table 88: Magic Item Determination (d100) ─────────────────────
    # Format: (d100_max, category_name)
    _MAGIC_ITEM_TABLE: list[tuple[int, str]] = [
        (20,  "Potions and Oils"),
        (35,  "Scrolls"),
        (40,  "Rings"),
        (41,  "Rods"),
        (42,  "Staves"),
        (45,  "Wands"),
        (46,  "Books and Tomes"),
        (48,  "Jewels and Jewelry"),
        (50,  "Cloaks and Robes"),
        (52,  "Boots and Gloves"),
        (53,  "Girdles and Helms"),
        (55,  "Bags and Bottles"),
        (56,  "Dusts and Stones"),
        (57,  "Household Items and Tools"),
        (58,  "Musical Instruments"),
        (60,  "The Weird Stuff"),
        (75,  "Armor and Shields"),
        (100, "Weapons"),
    ]

    # ── DMG Tables 89-110: Sub-tables per magic item category ─────────────
    _MAGIC_ITEM_SUBTABLES: dict[str, list[str]] = {
        "Potions and Oils": [
            "Potion of Animal Control", "Potion of Clairvoyance", "Potion of Climbing",
            "Potion of Delusion", "Potion of Diminution", "Potion of ESP",
            "Potion of Extra-Healing", "Potion of Fire Resistance", "Potion of Flying",
            "Potion of Gaseous Form", "Potion of Giant Strength", "Potion of Growth",
            "Potion of Healing", "Potion of Heroism", "Potion of Invisibility",
            "Potion of Invulnerability", "Potion of Levitation", "Potion of Longevity",
            "Potion of Speed", "Potion of Super-Heroism",
            "Oil of Acid Resistance", "Oil of Disenchantment", "Oil of Etherealness",
            "Oil of Fiery Burning", "Oil of Impact", "Oil of Slipperiness",
            "Oil of Timelessness", "Philter of Glibness", "Philter of Love",
            "Philter of Persuasiveness", "Potion of Plant Control",
            "Potion of Polymorph Self", "Potion of Rainbow Hues",
            "Potion of Treasure Finding", "Potion of Undead Control",
            "Potion of Vitality", "Potion of Water Breathing",
            "Elixir of Health", "Elixir of Madness", "Elixir of Youth",
        ],
        "Scrolls": [
            "Scroll: 1 Zauber (Level 1-4)", "Scroll: 1 Zauber (Level 1-6)",
            "Scroll: 2 Zauber (Level 1-4)", "Scroll: 2 Zauber (Level 2-9)",
            "Scroll: 3 Zauber (Level 1-4)", "Scroll: 3 Zauber (Level 2-9)",
            "Scroll: 4 Zauber (Level 1-6)", "Scroll: 5 Zauber (Level 1-6)",
            "Scroll: 5 Zauber (Level 4-9)", "Scroll: 7 Zauber (Level 1-8)",
            "Scroll of Protection from Demons",
            "Scroll of Protection from Devils",
            "Scroll of Protection from Elementals",
            "Scroll of Protection from Lycanthropes",
            "Scroll of Protection from Magic",
            "Scroll of Protection from Petrification",
            "Scroll of Protection from Plants",
            "Scroll of Protection from Possession",
            "Scroll of Protection from Undead",
            "Verfluchter Scroll",
        ],
        "Rings": [
            "Ring of Animal Friendship", "Ring of Contrariness",
            "Ring of Djinni Summoning", "Ring of Elemental Command",
            "Ring of Feather Falling", "Ring of Fire Resistance",
            "Ring of Free Action", "Ring of Human Influence",
            "Ring of Invisibility", "Ring of Mammal Control",
            "Ring of Multiple Wishes", "Ring of Protection +1",
            "Ring of Protection +2", "Ring of Protection +3",
            "Ring of the Ram", "Ring of Regeneration",
            "Ring of Shooting Stars", "Ring of Spell Storing",
            "Ring of Spell Turning", "Ring of Warmth", "Ring of Wizardry",
        ],
        "Rods": [
            "Rod of Absorption", "Rod of Alertness", "Rod of Beguiling",
            "Rod of Cancellation", "Rod of Flailing", "Rod of Lordly Might",
            "Rod of Passage", "Rod of Resurrection", "Rod of Rulership",
            "Rod of Security", "Rod of Smiting", "Rod of Splendor",
            "Rod of Terror", "Rod of Withering",
        ],
        "Staves": [
            "Staff of Command", "Staff of Curing", "Staff of the Magi",
            "Staff of Power", "Staff of the Serpent", "Staff of Slinging",
            "Staff of Striking", "Staff of Swarming Insects",
            "Staff of Thunder & Lightning", "Staff of Withering",
            "Staff of the Woodlands",
        ],
        "Wands": [
            "Wand of Conjuration", "Wand of Enemy Detection",
            "Wand of Fear", "Wand of Fire", "Wand of Flame Extinguishing",
            "Wand of Frost", "Wand of Illumination", "Wand of Lightning",
            "Wand of Magic Detection", "Wand of Magic Missiles",
            "Wand of Metal & Mineral Detection", "Wand of Negation",
            "Wand of Paralyzation", "Wand of Polymorphing",
            "Wand of Secret Door & Trap Location",
            "Wand of Size Alteration", "Wand of Wonder",
        ],
        "Books and Tomes": [
            "Book of Exalted Deeds", "Book of Infinite Spells",
            "Book of Vile Darkness", "Libram of Gainful Conjuration",
            "Libram of Silver Magic", "Manual of Bodily Health",
            "Manual of Gainful Exercise", "Manual of Golems",
            "Manual of Puissant Skill at Arms",
            "Manual of Quickness of Action",
            "Manual of Stealthy Pilfering", "Tome of Clear Thought",
            "Tome of Leadership and Influence",
            "Tome of Understanding", "Vacuous Grimoire",
        ],
        "Jewels and Jewelry": [
            "Amulet of Life Protection", "Amulet of the Planes",
            "Amulet of Proof Against Detection and Location",
            "Amulet versus Undead", "Brooch of Shielding",
            "Gem of Brightness", "Gem of Seeing", "Medallion of ESP",
            "Necklace of Adaptation", "Necklace of Missiles",
            "Necklace of Prayer Beads", "Necklace of Strangulation",
            "Periapt of Foul Rotting", "Periapt of Health",
            "Periapt of Proof Against Poison", "Periapt of Wound Closure",
            "Phylactery of Faithfulness", "Phylactery of Long Years",
            "Phylactery of Monstrous Attention", "Scarab of Death",
            "Scarab of Enraging Enemies", "Scarab of Insanity",
            "Scarab of Protection", "Scarab Versus Golems",
            "Talisman of Pure Good", "Talisman of Ultimate Evil",
            "Talisman of the Sphere", "Talisman of Zagy",
        ],
        "Cloaks and Robes": [
            "Cloak of Arachnida", "Cloak of Displacement",
            "Cloak of Elvenkind", "Cloak of the Bat",
            "Cloak of the Manta Ray", "Cloak of Poisonousness",
            "Cloak of Protection +1", "Cloak of Protection +2",
            "Cloak of Protection +3", "Robe of the Archmagi",
            "Robe of Blending", "Robe of Eyes",
            "Robe of Powerlessness", "Robe of Scintillating Colors",
            "Robe of Stars", "Robe of Useful Items", "Robe of Vermin",
        ],
        "Boots and Gloves": [
            "Boots of Dancing", "Boots of Elvenkind",
            "Boots of Levitation", "Boots of Speed",
            "Boots of Striding and Springing", "Boots of the North",
            "Boots of Varied Tracks", "Bracers of Archery",
            "Bracers of Brachiation", "Bracers of Defense",
            "Bracers of Defenselessness", "Gauntlets of Dexterity",
            "Gauntlets of Fumbling", "Gauntlets of Ogre Power",
            "Gauntlets of Swimming and Climbing",
            "Gloves of Missile Snaring", "Gloves of Thievery",
        ],
        "Girdles and Helms": [
            "Girdle of Dwarvenkind", "Girdle of Femininity/Masculinity",
            "Girdle of Giant Strength", "Girdle of Many Pouches",
            "Hat of Disguise", "Hat of Stupidity",
            "Helm of Brilliance", "Helm of Comprehending Languages",
            "Helm of Opposite Alignment", "Helm of Telepathy",
            "Helm of Teleportation", "Helm of Underwater Action",
        ],
        "Bags and Bottles": [
            "Alchemy Jug", "Bag of Beans", "Bag of Devouring",
            "Bag of Holding", "Bag of Transmuting", "Bag of Tricks",
            "Beaker of Plentiful Potions", "Bottle of Air",
            "Bucknard's Everfull Purse", "Candle of Invocation",
            "Decanter of Endless Water", "Eversmoking Bottle",
            "Flask of Curses", "Heward's Handy Haversack",
            "Iron Flask", "Portable Hole",
        ],
        "Dusts and Stones": [
            "Dust of Appearance", "Dust of Disappearance",
            "Dust of Dryness", "Dust of Illusion",
            "Dust of Sneezing and Choking", "Dust of Tracelessness",
            "Ioun Stone", "Keoghtom's Ointment",
            "Philosopher's Stone",
            "Stone of Controlling Earth Elementals",
            "Stone of Good Luck", "Stone of Weight",
            "Universal Solvent",
        ],
        "Household Items and Tools": [
            "Broom of Animated Attack", "Broom of Flying",
            "Carpet of Flying", "Crystal Ball",
            "Crystal Hypnosis Ball", "Cube of Force",
            "Cube of Frost Resistance", "Eyes of Charming",
            "Eyes of Minute Seeing", "Eyes of Petrification",
            "Eyes of the Eagle", "Figurine of Wondrous Power",
            "Folding Boat", "Horseshoes of a Zephyr",
            "Horseshoes of Speed", "Lenses of Detection",
            "Mattock of the Titans", "Maul of the Titans",
            "Mirror of Life Trapping", "Mirror of Mental Prowess",
            "Mirror of Opposition", "Murlynd's Spoon",
            "Nolzur's Marvelous Pigments", "Pearl of Power",
            "Pearl of the Sirines", "Quaal's Feather Token",
            "Rope of Climbing", "Rope of Constriction",
            "Rope of Entanglement", "Rug of Smothering",
            "Rug of Welcome", "Saw of Mighty Cutting",
            "Sovereign Glue", "Spade of Colossal Excavation",
        ],
        "Musical Instruments": [
            "Chime of Hunger", "Chime of Opening",
            "Drums of Deafening", "Drums of Panic",
            "Harp of Charming", "Horn of Blasting",
            "Horn of Bubbles", "Horn of Collapsing",
            "Horn of Goodness (Evil)", "Horn of the Tritons",
            "Horn of Valhalla", "Lyre of Building",
            "Pipes of Haunting", "Pipes of Pain",
            "Pipes of the Sewers",
        ],
        "The Weird Stuff": [
            "Apparatus of Kwalish",
            "Bowl of Commanding Water Elementals",
            "Brazier of Commanding Fire Elementals",
            "Censer of Controlling Air Elementals",
            "Cubic Gate", "Daern's Instant Fortress",
            "Deck of Many Things", "Efreeti Bottle",
            "Sphere of Annihilation", "Well of Many Worlds",
            "Wind Fan",
        ],
        "Armor and Shields": [
            "Chain Mail +1", "Chain Mail +2", "Chain Mail +3",
            "Leather Armor +1", "Plate Mail +1", "Plate Mail +2",
            "Plate Mail +3", "Full Plate +1", "Full Plate +2",
            "Ring Mail +1", "Scale Mail +1", "Scale Mail +2",
            "Splint Mail +1", "Studded Leather +1",
            "Shield +1", "Shield +2", "Shield +3", "Shield +4",
            "Shield +5", "Armor of Blending",
            "Armor of Missile Attraction", "Armor of Etherealness",
            "Armor of Command", "Armor of Vulnerability",
            "Elven Chain Mail",
        ],
        "Weapons": [
            "Arrow +1 (2d6)", "Arrow +2 (2d4)", "Arrow +3 (1d6)",
            "Arrow of Slaying", "Axe +1", "Axe +2", "Axe +3",
            "Battle Axe +1", "Bolt +1 (2d6)", "Bolt +2 (2d4)",
            "Bow +1", "Crossbow of Accuracy +3", "Crossbow of Distance",
            "Crossbow of Speed", "Dagger +1", "Dagger +2",
            "Dagger +2, +3 vs. Larger", "Dagger of Venom",
            "Dart +1 (1d6)", "Flail +1", "Hammer +1", "Hammer +2",
            "Hammer +3, Dwarven Thrower", "Hammer of Thunderbolts",
            "Javelin +2", "Javelin of Lightning", "Javelin of Piercing",
            "Long Sword +1", "Long Sword +2", "Long Sword +3",
            "Long Sword +1, +2 vs. Magic-Using",
            "Long Sword +1, +3 vs. Regenerating",
            "Long Sword +1, +3 vs. Lycanthropes/Shape-Changers",
            "Long Sword +1, +4 vs. Reptiles",
            "Long Sword +1, Flame Tongue",
            "Long Sword +2, Giant Slayer",
            "Long Sword +2, Dragon Slayer",
            "Long Sword +3, Frost Brand",
            "Long Sword +4, Defender", "Long Sword +5, Defender",
            "Long Sword +5, Holy Avenger",
            "Long Sword of Wounding", "Long Sword of Life Stealing",
            "Long Sword of Sharpness", "Long Sword, Luck Blade",
            "Long Sword, Nine Lives Stealer", "Long Sword, Vorpal",
            "Cursed Sword, Berserking", "Cursed Sword -2",
            "Mace +1", "Mace +2", "Mace +3", "Mace +4",
            "Mace of Disruption", "Mace of Smiting", "Mace of Terror",
            "Morning Star +1", "Scimitar +1", "Scimitar +2",
            "Short Sword +1", "Short Sword +2",
            "Short Sword of Backstabbing", "Short Sword of Quickness",
            "Short Sword, Luck Blade", "Spear +1", "Spear +2",
            "Spear +3", "Spear, Cursed Backbiter",
            "Trident of Fish Command", "Trident of Submission",
            "Trident of Warning", "Trident of Yearning",
            "Two-Handed Sword +1", "Two-Handed Sword +2",
            "Two-Handed Sword +3", "Two-Handed Sword of Wounding",
            "War Hammer +1", "War Hammer +2",
        ],
    }

    # Fallback-Durchschnittswerte (nur fuer Faelle ohne Detailwurf)
    _GEM_GP_VALUE = 50
    _JEWELRY_GP_VALUE = 200
    _MAGIC_GP_VALUE = 1000

    def roll_gem(self) -> dict[str, Any]:
        """
        Wuerfelt einen einzelnen Edelstein auf DMG Table 85 mit
        optionaler Wertschwankung gemaess DMG Table 86.

        Returns:
            dict mit:
              name (str): Beispiel-Steinname aus der Tier-Liste
              tier (str): Tier-Bezeichnung (z.B. "Ornamental", "Juwel")
              base_value (int): Basiswert in GP
              actual_value (int): Endwert nach Variation in GP
        """
        roll = self.rng.randint(1, 100)
        chosen = self._GEM_VALUE_TABLE[-1]          # Fallback: hoechster Tier
        tier_index = len(self._GEM_VALUE_TABLE) - 1
        for i, entry in enumerate(self._GEM_VALUE_TABLE):
            if roll <= entry[0]:
                chosen = entry
                tier_index = i
                break

        _, base_value, tier_name, examples = chosen
        stone_name = self.rng.choice(examples)

        # DMG Table 86: Wertschwankung — 10% Chance pro Stein
        variation_roll = self.rng.randint(1, 100)
        if variation_roll <= 10:
            d6 = self.roll_die(6)
            if d6 == 1:
                # Aufwertung auf naechsthoehere Tier
                next_idx = min(tier_index + 1, len(self._GEM_VALUE_TABLE) - 1)
                actual_value = self._GEM_VALUE_TABLE[next_idx][1]
            elif d6 == 2:
                actual_value = base_value * 2
            elif d6 == 3:
                # +10 bis +60 Prozent
                pct = self.rng.randint(1, 6) * 10
                actual_value = int(base_value * (1 + pct / 100))
            elif d6 == 4:
                # -10 bis -40 Prozent
                pct = self.rng.randint(1, 4) * 10
                actual_value = int(base_value * (1 - pct / 100))
            elif d6 == 5:
                actual_value = base_value // 2
            else:  # d6 == 6
                # Abwertung auf naechstniedrigere Tier
                prev_idx = max(tier_index - 1, 0)
                actual_value = self._GEM_VALUE_TABLE[prev_idx][1]
        else:
            actual_value = base_value

        actual_value = max(1, actual_value)
        logger.debug(
            "Edelstein: %s (%s) Basiswert=%d GP Endwert=%d GP",
            stone_name, tier_name, base_value, actual_value,
        )
        return {
            "name": stone_name,
            "tier": tier_name,
            "base_value": base_value,
            "actual_value": actual_value,
        }

    def roll_art_object(self) -> dict[str, Any]:
        """
        Wuerfelt einen Kunstgegenstand gemaess DMG Table 87.

        Returns:
            dict mit:
              value (int): GP-Wert des Kunstgegenstands
              description (str): Lesbare Beschreibung mit Wert
        """
        roll = self.rng.randint(1, 100)
        chosen_min, chosen_max = self._ART_OBJECT_TABLE[-1][1], self._ART_OBJECT_TABLE[-1][2]
        for max_roll, min_val, max_val in self._ART_OBJECT_TABLE:
            if roll <= max_roll:
                chosen_min, chosen_max = min_val, max_val
                break

        value = self.rng.randint(chosen_min, chosen_max)
        logger.debug("Kunstgegenstand: %d GP", value)
        return {
            "value": value,
            "description": f"Kunstgegenstand ({value} GP)",
        }

    def roll_magic_item(self) -> dict[str, Any]:
        """
        Wuerfelt einen magischen Gegenstand gemaess DMG Table 88
        (Kategorie-Bestimmung) + Kategorie-Sub-Tabellen.

        Returns:
            dict mit:
              name (str): Name des magischen Gegenstands
              category (str): Kategorie gemaess DMG Table 88
        """
        roll = self.rng.randint(1, 100)
        category = self._MAGIC_ITEM_TABLE[-1][1]  # Fallback
        for max_roll, cat in self._MAGIC_ITEM_TABLE:
            if roll <= max_roll:
                category = cat
                break

        sub_list = self._MAGIC_ITEM_SUBTABLES.get(category, [])
        if sub_list:
            item_name = self.rng.choice(sub_list)
        else:
            item_name = f"Unbekannter magischer Gegenstand ({category})"

        logger.debug("Magischer Gegenstand: %s [%s]", item_name, category)
        return {
            "name": item_name,
            "category": category,
        }

    def roll_treasure(self, treasure_type: str) -> dict[str, Any]:
        """
        Wuerfelt Schatz gemaess AD&D 2e Treasure-Type-Tabelle (DMG Table 84).

        Bestimmt Muenzen, Edelsteine, Kunstgegenstaende und magische Items
        mit vollstaendigen DMG-Sub-Tabellen fuer Edelsteine (Table 85/86),
        Kunstgegenstaende (Table 87) und magische Items (Table 88).

        Args:
            treasure_type: Schatztyp "A" bis "Q" (Grossbuchstabe).
                           Unbekannte Typen liefern leeres Ergebnis.

        Returns:
            dict mit:
              coins (dict): {cp, sp, ep, gp, pp} -> Mengen (int)
              gems (int): Anzahl Edelsteine (rueckwaerts-kompatibel)
              jewelry (int): Anzahl Kunstgegenstaende (rueckwaerts-kompatibel)
              magic_items (int): Anzahl magische Gegenstaende (rueckwaerts-kompatibel)
              gem_details (list[dict]): Einzelne Edelstein-Wuerfe (roll_gem()-Ergebnisse)
              jewelry_details (list[dict]): Einzelne Kunstgegenstand-Wuerfe
              magic_item_details (list[dict]): Einzelne magische Item-Wuerfe
              total_gp_value (int): Berechneter Gesamtwert in GP
              description (str): Lesbare Zusammenfassung mit Einzelnennungen
        """
        tt = treasure_type.upper()
        table = self._TREASURE_TYPES.get(tt)

        coins: dict[str, int] = {"cp": 0, "sp": 0, "ep": 0, "gp": 0, "pp": 0}
        gem_details: list[dict[str, Any]] = []
        jewelry_details: list[dict[str, Any]] = []
        magic_item_details: list[dict[str, Any]] = []

        if table is None:
            logger.warning("Unbekannter Schatztyp '%s' — leerer Schatz", treasure_type)
            return {
                "coins": coins,
                "gems": 0,
                "jewelry": 0,
                "magic_items": 0,
                "gem_details": [],
                "jewelry_details": [],
                "magic_item_details": [],
                "total_gp_value": 0,
                "description": f"Schatztyp '{treasure_type}' unbekannt — kein Schatz.",
            }

        # Muenzen wuerfeln
        for coin_type in ("cp", "sp", "ep", "gp", "pp"):
            entry = table.get(coin_type)
            if entry is None:
                continue
            dice_count, dice_faces, multiplier, chance = entry
            if self.rng.randint(1, 100) <= chance:
                amount = sum(self.roll_die(dice_faces) for _ in range(dice_count)) * multiplier
                coins[coin_type] = amount

        # Edelsteine wuerfeln (mit Sub-Tabellen)
        gem_entry = table.get("gems")
        if gem_entry is not None:
            dice_count, dice_faces, chance = gem_entry
            if self.rng.randint(1, 100) <= chance:
                count = sum(self.roll_die(dice_faces) for _ in range(dice_count))
                gem_details = [self.roll_gem() for _ in range(count)]

        # Schmuck/Kunstgegenstaende wuerfeln (mit Sub-Tabellen)
        jewelry_entry = table.get("jewelry")
        if jewelry_entry is not None:
            dice_count, dice_faces, chance = jewelry_entry
            if self.rng.randint(1, 100) <= chance:
                count = sum(self.roll_die(dice_faces) for _ in range(dice_count))
                jewelry_details = [self.roll_art_object() for _ in range(count)]

        # Magische Gegenstaende wuerfeln (mit Sub-Tabellen)
        magic_entry = table.get("magic")
        if magic_entry is not None:
            if len(magic_entry) == 2:
                count, chance = magic_entry
                if self.rng.randint(1, 100) <= chance:
                    magic_item_details = [self.roll_magic_item() for _ in range(count)]
            else:
                # Manche Typen (P=Potions, Q=Scrolls) haben 100%-Chance
                count = magic_entry[0]
                magic_item_details = [self.roll_magic_item() for _ in range(count)]

        # Rueckwaertskompatible Zaehlwerte
        gems = len(gem_details)
        jewelry = len(jewelry_details)
        magic_items = len(magic_item_details)

        # Gesamtwert berechnen aus echten Wuerfel-Ergebnissen
        gp_value = (
            coins["cp"] * 0.01
            + coins["sp"] * 0.1
            + coins["ep"] * 0.5
            + coins["gp"] * 1.0
            + coins["pp"] * 5.0
            + sum(g["actual_value"] for g in gem_details)
            + sum(j["value"] for j in jewelry_details)
            + magic_items * self._MAGIC_GP_VALUE
        )
        total_gp = int(gp_value)

        # Beschreibung zusammenstellen
        parts = []
        if coins["cp"]:
            parts.append(f"{coins['cp']} Kupfer")
        if coins["sp"]:
            parts.append(f"{coins['sp']} Silber")
        if coins["ep"]:
            parts.append(f"{coins['ep']} Elektrum")
        if coins["gp"]:
            parts.append(f"{coins['gp']} Gold")
        if coins["pp"]:
            parts.append(f"{coins['pp']} Platin")
        for g in gem_details:
            parts.append(f"{g['name']} ({g['actual_value']} GP)")
        for j in jewelry_details:
            parts.append(j["description"])
        for m in magic_item_details:
            parts.append(m["name"])

        if parts:
            desc = f"Schatz Typ {tt}: {', '.join(parts)}. Gesamtwert: {total_gp} GP."
        else:
            desc = f"Schatz Typ {tt}: Kein Schatz (Wuerfelglueck negativ)."

        logger.debug(
            "Schatzwurf Typ %s: GP-Wert=%d gems=%d jewelry=%d magic=%d",
            tt, total_gp, gems, jewelry, magic_items,
        )
        return {
            "coins": coins,
            "gems": gems,
            "jewelry": jewelry,
            "magic_items": magic_items,
            "gem_details": gem_details,
            "jewelry_details": jewelry_details,
            "magic_item_details": magic_item_details,
            "total_gp_value": total_gp,
            "description": desc,
        }

    # ------------------------------------------------------------------
    # AD&D 2e — Wandering-Monster-Probe (Encounter Check)
    # ------------------------------------------------------------------

    def roll_encounter_check(self, chance_percent: int = 15) -> dict[str, Any]:
        """
        Prueft ob ein Wandering Monster erscheint (d100-Probe).

        In AD&D 2e wird standardmaessig 1 auf 1d6 (=~17%) oder eine
        explizite Prozent-Chance verwendet. Diese Methode nutzt d100.

        Args:
            chance_percent: Wahrscheinlichkeit in Prozent (Standard 15).
                            Typische Werte: Dungeon=15, Wildnis=25, Stadt=5

        Returns:
            dict mit:
              occurred (bool): True = Begegnung findet statt
              roll (int): Wuerfelergebnis (1-100)
              threshold (int): Schwellenwert (= chance_percent)
              description (str): Beschreibung
        """
        roll = self.rng.randint(1, 100)
        occurred = roll <= chance_percent
        logger.debug(
            "Begegnungsprobe: d100=%d Schwelle=%d -> %s",
            roll, chance_percent, "BEGEGNUNG" if occurred else "Ruhig",
        )
        return {
            "occurred": occurred,
            "roll": roll,
            "threshold": chance_percent,
            "description": (
                f"Wandering-Monster-Probe: d100={roll} | Schwelle: {chance_percent}%"
                f" | {'BEGEGNUNG!' if occurred else 'Keine Begegnung.'}"
            ),
        }

    # ------------------------------------------------------------------
    # AD&D 2e — Tragekapazitaet (Encumbrance)
    # ------------------------------------------------------------------

    # Max. Tragekapazitaet in Pfund nach STR-Wert (PHB Table 1).
    # Exceptional STR (18/xx) wird hier nicht gesondert beruecksichtigt;
    # STR 18 entspricht dem Standard-Maximalwert fuer nicht-Krieger.
    _STR_MAX_ALLOWANCE: dict[int, int] = {
        3:  5,
        4:  10, 5: 10,
        6:  20, 7: 20,
        8:  35, 9: 35,
        10: 40, 11: 40,
        12: 45, 13: 45,
        14: 55, 15: 55,
        16: 70,
        17: 85,
        18: 110,
    }

    def calculate_encumbrance(
        self,
        items_with_weights: list[tuple[str, float]],
        str_score: int,
    ) -> dict[str, Any]:
        """
        Berechnet die Tragekapazitaet (Encumbrance) nach AD&D 2e.

        Args:
            items_with_weights: Liste von (Gegenstandsname, Gewicht_in_Pfund)-Tupeln
            str_score: STR-Wert des Charakters (3-18)

        Returns:
            dict mit:
              total_weight (float): Gesamtgewicht in Pfund
              max_allowance (int): Maximale Tragekapazitaet in Pfund
              category (str): "unencumbered" | "light" | "moderate" | "heavy" | "severe"
              movement_factor (float): Bewegungsfaktor (1.0 = voll, 0.0 = unbeweglich)
              description (str): Beschreibung
              items (list): Uebergebene Liste (zur Referenz)
        """
        # STR klemmen und Max-Allowance bestimmen
        str_clamped = max(3, min(str_score, 18))
        max_allow = self._STR_MAX_ALLOWANCE.get(str_clamped, 40)

        total_weight = sum(w for _, w in items_with_weights)

        # Schwellenwerte berechnen
        threshold_light    = max_allow / 3.0       # bis hierher: voll beweglich
        threshold_moderate = max_allow / 2.0       # 3/4 Bewegung
        threshold_heavy    = max_allow * 2.0 / 3.0 # 1/2 Bewegung
        # bis max_allow: 1/3 Bewegung
        # darueber: Schwer (1 Feld)

        if total_weight <= threshold_light:
            category = "unencumbered"
            movement_factor = 1.0
            cat_de = "Unbelastet"
            move_str = "volle Bewegung"
        elif total_weight <= threshold_moderate:
            category = "light"
            movement_factor = 0.75
            cat_de = "Leicht belastet"
            move_str = "3/4 Bewegung"
        elif total_weight <= threshold_heavy:
            category = "moderate"
            movement_factor = 0.5
            cat_de = "Maessig belastet"
            move_str = "1/2 Bewegung"
        elif total_weight <= max_allow:
            category = "heavy"
            movement_factor = 0.33
            cat_de = "Schwer belastet"
            move_str = "1/3 Bewegung"
        else:
            category = "severe"
            movement_factor = 0.0
            cat_de = "Ueberlastet"
            move_str = "1 Feld/Runde"

        description = (
            f"Tragekapazitaet: {total_weight:.1f} / {max_allow} Pfund"
            f" (STR {str_clamped}) — {cat_de} ({move_str})"
        )
        logger.debug(
            "Encumbrance: STR=%d max=%d lbs total=%.1f lbs -> %s (factor=%.2f)",
            str_clamped, max_allow, total_weight, category, movement_factor,
        )
        return {
            "total_weight": total_weight,
            "max_allowance": max_allow,
            "category": category,
            "movement_factor": movement_factor,
            "description": description,
            "items": list(items_with_weights),
        }
