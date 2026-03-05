"""
ARS Session Configuration
Bundles session-level meta-parameters (difficulty, atmosphere, persona, language)
that are injected into the KI system prompt.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger("ARS.session_config")

PRESETS_DIR = Path(__file__).parent.parent / "modules" / "presets"

# Default values
_DEFAULT_DIFFICULTY = "normal"
_DEFAULT_ATMOSPHERE = "Klassische Fantasy, Schwerter und Magie"
_DEFAULT_PERSONA = "Episch, detailverliebt, gerecht"
_DEFAULT_LANGUAGE = "de-DE"
_DEFAULT_TEMPERATURE = 0.92
_DEFAULT_RULES_BUDGET = 6000  # chars (~1500 Tokens)
_DEFAULT_LORE_BUDGET_PCT = 50  # % of MAX_LORE_CHARS (500K chars)

VALID_DIFFICULTIES = ("easy", "normal", "heroic", "hardcore")
VALID_SPEECH_STYLES = ("normal", "sanft", "aggressiv")


@dataclass
class SessionConfig:
    """Session-level configuration injected into the KI system prompt."""

    ruleset: str = "add_2e"
    adventure: str | None = None
    setting: str | None = None
    keeper: str | None = None
    extras: list[str] = field(default_factory=list)
    character: str | None = None
    party: str | None = None
    difficulty: str = _DEFAULT_DIFFICULTY
    atmosphere: str = _DEFAULT_ATMOSPHERE
    keeper_persona: str = _DEFAULT_PERSONA
    language: str = _DEFAULT_LANGUAGE
    temperature: float = _DEFAULT_TEMPERATURE
    rules_budget: int = _DEFAULT_RULES_BUDGET
    lore_budget_pct: int = _DEFAULT_LORE_BUDGET_PCT
    speech_style: str = "normal"

    def __post_init__(self) -> None:
        if self.speech_style not in VALID_SPEECH_STYLES:
            logger.warning(
                "Unknown speech_style '%s', falling back to 'normal'.",
                self.speech_style,
            )
            self.speech_style = "normal"
        if self.difficulty not in VALID_DIFFICULTIES:
            logger.warning(
                "Unknown difficulty '%s', falling back to '%s'.",
                self.difficulty, _DEFAULT_DIFFICULTY,
            )
            self.difficulty = _DEFAULT_DIFFICULTY
        self.temperature = max(0.0, min(2.0, self.temperature))
        self.rules_budget = max(1000, min(2000000, self.rules_budget))
        self.lore_budget_pct = max(0, min(100, self.lore_budget_pct))

    # -- factory methods ------------------------------------------------------

    @classmethod
    def from_preset(cls, name: str) -> SessionConfig:
        """Load a preset JSON from modules/presets/{name}.json."""
        path = PRESETS_DIR / f"{name}.json"
        if not path.exists():
            available = [p.stem for p in PRESETS_DIR.glob("*.json")]
            raise FileNotFoundError(
                f"Preset '{name}' not found at {path}\n"
                f"Available presets: {available}"
            )
        with path.open(encoding="utf-8-sig") as fh:
            data: dict[str, Any] = json.load(fh)
        valid_keys = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        logger.info("Loaded preset '%s' from %s", name, path)
        return cls(**filtered)

    @classmethod
    def from_args(cls, args: Any, base: SessionConfig | None = None) -> SessionConfig:
        """Build config from CLI args, optionally overriding a base preset."""
        cfg = base or cls()

        # ruleset and adventure are handled by engine, but sync them here
        if getattr(args, "module", None):
            cfg.ruleset = args.module
        if getattr(args, "adventure", None):
            cfg.adventure = args.adventure
        if getattr(args, "difficulty", None):
            cfg.difficulty = args.difficulty
        if getattr(args, "atmosphere", None):
            cfg.atmosphere = args.atmosphere
        if getattr(args, "persona", None):
            cfg.keeper_persona = args.persona
        if getattr(args, "language", None):
            cfg.language = args.language
        if getattr(args, "setting", None):
            cfg.setting = args.setting
        if getattr(args, "keeper", None):
            cfg.keeper = args.keeper
        if getattr(args, "extras", None):
            cfg.extras = args.extras
        if getattr(args, "character", None):
            cfg.character = args.character
        if getattr(args, "party", None):
            cfg.party = args.party
        if getattr(args, "temperature", None) is not None:
            cfg.temperature = args.temperature
        if getattr(args, "rules_budget", None) is not None:
            cfg.rules_budget = args.rules_budget
        if getattr(args, "lore_budget_pct", None) is not None:
            cfg.lore_budget_pct = args.lore_budget_pct
        if getattr(args, "speech_style", None) is not None:
            cfg.speech_style = args.speech_style

        cfg.__post_init__()
        return cfg

    # -- prompt helpers -------------------------------------------------------

    @property
    def difficulty_instruction(self) -> str:
        """Return a KI instruction string matching the difficulty level."""
        if self.difficulty == "easy":
            return (
                "Sei gnaedig bei Fehlschlaegen. Gib dezente Hinweise, wenn der "
                "Spieler feststeckt. Reduziere Verluste leicht."
            )
        if self.difficulty == "heroic":
            return (
                "Heroische Fantasy. Kaempfe sind fair aber gefaehrlich. "
                "Belohne clevere Taktik und mutiges Spiel. Schaetze und XP gemaess Herausforderung."
            )
        if self.difficulty == "hardcore":
            return (
                "Kein Erbarmen. Patzer haben verheerende Folgen. Hinweise sind rar. "
                "Verluste sind hoeher. NPCs sind misstrauisch."
            )
        return (
            "Faire Balance zwischen Herausforderung und Fortschritt. "
            "Konsequenzen ja, aber Raum zum Atmen."
        )
