"""
ARS Core Engine
Handles ruleset loading, validation, and module lifecycle.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("ARS.engine")

# Minimal JSON-Schema for ruleset validation
RULESET_SCHEMA: dict[str, Any] = {
    "required_keys": ["metadata", "dice_system", "characteristics", "skills"],
    "metadata_keys": ["name", "version", "system"],
    "dice_system_keys": ["default_die", "success_levels"],
}

RULESETS_DIR = Path(__file__).parent.parent / "modules" / "rulesets"
ADVENTURES_DIR = Path(__file__).parent.parent / "modules" / "adventures"
SETTINGS_DIR = Path(__file__).parent.parent / "modules" / "settings"
KEEPERS_DIR = Path(__file__).parent.parent / "modules" / "keepers"
EXTRAS_DIR = Path(__file__).parent.parent / "modules" / "extras"
CHARACTERS_DIR = Path(__file__).parent.parent / "modules" / "characters"
PARTIES_DIR = Path(__file__).parent.parent / "modules" / "parties"


# ---------------------------------------------------------------------------
# ModuleLoader
# ---------------------------------------------------------------------------

class ModuleLoader:
    """Loads a ruleset JSON and exposes its dice logic."""

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        self._raw: dict[str, Any] = {}

    # -- public API ----------------------------------------------------------

    def load(self) -> dict[str, Any]:
        path = RULESETS_DIR / f"{self.module_name}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"Ruleset file not found: {path}\n"
                f"Available rulesets: {self._list_available()}"
            )
        with path.open(encoding="utf-8-sig") as fh:
            self._raw = json.load(fh)
        logger.info("Loaded ruleset '%s' from %s", self.module_name, path)
        return self._raw

    def validate(self, data: dict[str, Any]) -> None:
        """Validates the loaded ruleset against RULESET_SCHEMA."""
        for key in RULESET_SCHEMA["required_keys"]:
            if key not in data:
                raise ValueError(f"Ruleset missing required key: '{key}'")

        for key in RULESET_SCHEMA["metadata_keys"]:
            if key not in data.get("metadata", {}):
                raise ValueError(f"Ruleset metadata missing key: '{key}'")

        dice_sys = data.get("dice_system", {})
        for key in RULESET_SCHEMA["dice_system_keys"]:
            if key not in dice_sys:
                raise ValueError(f"dice_system missing key: '{key}'")

        # Validate die notation (e.g. "d100", "2d6")
        die_notation = dice_sys.get("default_die", "")
        if not re.match(r"^\d*d\d+$", die_notation):
            raise ValueError(
                f"Invalid die notation '{die_notation}'. Expected format: [N]dX"
            )

        logger.info(
            "Ruleset validated — system: %s, default die: %s",
            data["metadata"]["system"],
            dice_sys["default_die"],
        )

    # -- dice helpers --------------------------------------------------------

    @staticmethod
    def get_dice_config(data: dict[str, Any]) -> DiceConfig:
        dice_sys = data["dice_system"]
        return DiceConfig(
            default_die=dice_sys["default_die"],
            success_levels=dice_sys["success_levels"],
            bonus_penalty_die=dice_sys.get("bonus_penalty_die"),
        )

    # -- private -------------------------------------------------------------

    def _list_available(self) -> list[str]:
        return [p.stem for p in RULESETS_DIR.glob("*.json")]


# ---------------------------------------------------------------------------
# DiceConfig — thin data class for dice logic
# ---------------------------------------------------------------------------

class DiceConfig:
    """Parsed dice configuration ready for use by mechanics.py."""

    def __init__(
        self,
        default_die: str,
        success_levels: dict[str, Any],
        bonus_penalty_die: str | None = None,
    ) -> None:
        self.default_die = default_die          # e.g. "d100"
        self.success_levels = success_levels    # e.g. {"extreme": 0.2, ...}
        self.bonus_penalty_die = bonus_penalty_die  # e.g. "d100" for BRP bonus

        # Parse die faces from notation
        parts = default_die.lstrip("0123456789").split("d")
        self.faces: int = int(default_die.split("d")[-1])
        self.count: int = int(default_die.split("d")[0]) if "d" in default_die and default_die[0].isdigit() else 1

    def __repr__(self) -> str:
        return f"DiceConfig(die={self.default_die}, faces={self.faces})"


# ---------------------------------------------------------------------------
# SimulatorEngine
# ---------------------------------------------------------------------------

class SimulatorEngine:
    """Top-level engine: wires together ModuleLoader, Orchestrator, and I/O."""

    def __init__(self, module_name: str, session_config: Any | None = None) -> None:
        self.module_name = module_name
        self.session_config = session_config
        self.loader = ModuleLoader(module_name)
        self.ruleset: dict[str, Any] = {}
        self.dice_config: DiceConfig | None = None
        self.ai_backend = None
        self.character = None
        self.discovery = None         # Task 06: DiscoveryService
        self.setting_data: dict[str, Any] | None = None
        self.keeper_data: dict[str, Any] | None = None
        self.extras_data: list[dict[str, Any]] = []
        self.character_template: dict[str, Any] | None = None
        self.party_data: dict[str, Any] | None = None
        self._voice_enabled = False
        self._orchestrator = None

    # -- ruleset helpers -----------------------------------------------------

    @property
    def pc_title(self) -> str:
        """Player character title from ruleset metadata."""
        meta = self.ruleset.get("metadata", {}) if self.ruleset else {}
        return meta.get("player_character_title", "Charakter")

    @property
    def is_cthulhu(self) -> bool:
        """True if the loaded ruleset is a Cthulhu variant."""
        meta = self.ruleset.get("metadata", {}) if self.ruleset else {}
        return meta.get("system", "").startswith("cthulhu")

    # -- lifecycle -----------------------------------------------------------

    def initialize(self) -> None:
        """Load and validate the ruleset, prepare sub-systems."""
        # Asset-Discovery: verfuegbare Regelsaetze + Abenteuer indizieren
        from core.discovery import DiscoveryService
        self.discovery = DiscoveryService(Path(__file__).parent.parent)
        self.discovery.scan()
        self.discovery.print_manifest()

        self.ruleset = self.loader.load()
        self.loader.validate(self.ruleset)
        self.dice_config = ModuleLoader.get_dice_config(self.ruleset)

        # Optionale Module laden (Setting, Keeper, Extras)
        sc = self.session_config
        if sc and getattr(sc, "setting", None):
            self.load_setting(sc.setting)
        if sc and getattr(sc, "keeper", None):
            self.load_keeper(sc.keeper)
        if sc and getattr(sc, "extras", None):
            self.load_extras(sc.extras)
        if sc and getattr(sc, "character", None):
            self.load_character_template(sc.character)
        if sc and getattr(sc, "party", None):
            self.load_party(sc.party)

        # KI-Backend initialisieren
        from core.ai_backend import GeminiBackend
        self.ai_backend = GeminiBackend(
            ruleset=self.ruleset,
            session_config=self.session_config,
            setting=self.setting_data,
            keeper=self.keeper_data,
            extras=self.extras_data,
            character_template=self.character_template,
        )

        # Charakter-Persistenz initialisieren
        from core.character import CharacterManager
        self.character = CharacterManager(
            ruleset=self.ruleset,
            template=self.character_template,
        )
        self.character.connect()
        loaded = self.character.load_latest()
        logger.info(
            "Charakter%s geladen: %s",
            "" if loaded else " (neu)",
            self.character.name,
        )

        # Lazy import to avoid circular dependency
        from core.orchestrator import Orchestrator
        self._orchestrator = Orchestrator(engine=self)

        logger.info(
            "Engine initialised — %s %s | dice: %s",
            self.ruleset["metadata"]["name"],
            self.ruleset["metadata"]["version"],
            self.dice_config,
        )

    def load_setting(self, setting_name: str) -> None:
        """Load a setting module from modules/settings/."""
        path = SETTINGS_DIR / f"{setting_name}.json"
        if not path.exists():
            logger.warning("Setting file not found: %s", path)
            return
        with path.open(encoding="utf-8-sig") as fh:
            self.setting_data = json.load(fh)
        logger.info("Setting loaded: %s", setting_name)

    def load_keeper(self, keeper_name: str) -> None:
        """Load a keeper personality from modules/keepers/."""
        path = KEEPERS_DIR / f"{keeper_name}.json"
        if not path.exists():
            logger.warning("Keeper file not found: %s", path)
            return
        with path.open(encoding="utf-8-sig") as fh:
            self.keeper_data = json.load(fh)
        logger.info("Keeper loaded: %s", keeper_name)

    def load_extras(self, extra_names: list[str]) -> None:
        """Load extra modules from modules/extras/."""
        self.extras_data = []
        for name in extra_names:
            path = EXTRAS_DIR / f"{name}.json"
            if not path.exists():
                logger.warning("Extra file not found: %s", path)
                continue
            with path.open(encoding="utf-8-sig") as fh:
                self.extras_data.append(json.load(fh))
            logger.info("Extra loaded: %s", name)

    def load_character_template(self, char_name: str) -> None:
        """Load a character template from modules/characters/."""
        path = CHARACTERS_DIR / f"{char_name}.json"
        if not path.exists():
            logger.warning("Character template not found: %s", path)
            return
        with path.open(encoding="utf-8-sig") as fh:
            self.character_template = json.load(fh)
        logger.info("Character template loaded: %s", char_name)

    def load_party(self, party_name: str) -> None:
        """Load a party module from modules/parties/ (placeholder)."""
        path = PARTIES_DIR / f"{party_name}.json"
        if not path.exists():
            logger.warning("Party file not found: %s", path)
            return
        with path.open(encoding="utf-8-sig") as fh:
            self.party_data = json.load(fh)
        logger.info("Party loaded: %s", party_name)

    def load_adventure(self, adventure_name: str) -> None:
        # Discovery-Validierung: existiert das Abenteuer im Manifest?
        if self.discovery and adventure_name not in self.discovery.list_adventures():
            available = ", ".join(self.discovery.list_adventures()) or "(keine)"
            logger.warning(
                "Adventure '%s' nicht im Manifest. Verfuegbar: %s",
                adventure_name, available,
            )
        path = ADVENTURES_DIR / f"{adventure_name}.json"
        if not path.exists():
            logger.warning("Adventure file not found: %s — starting sandbox session.", path)
            return
        with path.open(encoding="utf-8-sig") as fh:
            adventure_data = json.load(fh)
        self._orchestrator.set_adventure(adventure_data)
        logger.info("Adventure loaded: %s", adventure_name)

    def enable_voice(self, barge_in: bool = True) -> None:
        from audio.pipeline import VoicePipeline
        self._voice_pipeline = VoicePipeline(barge_in=barge_in)
        # Kompatibilitaets-Aliase fuer Orchestrator
        self._stt = self._voice_pipeline.stt
        self._tts = self._voice_pipeline.tts
        self._voice_enabled = True
        logger.info(
            "Voice I/O aktiviert — STT: %s | TTS: %s",
            self._voice_pipeline.stt._backend,
            self._voice_pipeline.tts._backend,
        )

    def run(self) -> None:
        if self._orchestrator is None:
            raise RuntimeError("Engine not initialised. Call initialize() first.")
        self._orchestrator.start_session()
