"""
core/mechanics.py — Würfelmechanik & Probenlogik

Implementiert die regelkonforme Auswertung von:
  - Standardproben (d100 unter Fertigkeitswert)
  - Erfolgsgrade (Regulär / Hart / Extrem / Kritisch / Patzer)
  - Bonus- und Strafwürfe (Cthulhu 7e)
  - Widerstandstabellen-Proben (optional)
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

    def __init__(self, dice_config: DiceConfig) -> None:
        self.dice_config = dice_config
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
                f"Akteur würfelt {actor.roll} (Ziel {actor.target}) → {actor.success_level}. "
                f"Gegner würfelt {opponent.roll} (Ziel {opponent.target}) → {opponent.success_level}. "
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
          '1d6'  → wuerfelt 1d6
          '2d4'  → wuerfelt 2d4
          '3'    → gibt 3 zurueck
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
                "Unbekannter Wuerfelausdruck '%s' — nehme Wert 1 an.", expr
            )
            return 1

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
