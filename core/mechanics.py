"""
core/mechanics.py — Würfelmechanik & Probenlogik

Implementiert die regelkonforme Auswertung von:
  - Standardproben (d100 unter Fertigkeitswert, Cthulhu 7e)
  - Erfolgsgrade (Regulär / Hart / Extrem / Kritisch / Patzer)
  - Bonus- und Strafwürfe (Cthulhu 7e)
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
            target:   Fertigkeitswert (0–100 für Cthulhu 7e)
            modifier: Positiver Wert = Bonus-Würfel, Negativer = Straf-Würfel

        Returns:
            RollResult mit Erfolgsgrad und Beschreibung
        """
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
        m = re.match(r"^(\d+)d(\d+)$", expr)
        if m:
            count = int(m.group(1))
            faces = int(m.group(2))
            return sum(self.roll_die(faces) for _ in range(count))
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
