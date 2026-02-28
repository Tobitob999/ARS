"""
core/discovery.py — Asset Discovery Service

Scannt beim Start alle verfuegbaren Regelsaetze, Abenteuer, Settings,
Keeper, Extras, Characters und Parties und stellt ein Manifest bereit.
Die Engine nutzt das Manifest zur Validierung von Argumenten.

Scan-Verzeichnisse:
  modules/rulesets/*.json    — Regelsaetze (cthulhu_7e, etc.)
  modules/adventures/*.json  — Abenteuer-Szenarien
  modules/settings/*.json    — Welt-Settings
  modules/keepers/*.json     — Keeper-Persoenlichkeiten
  modules/extras/*.json      — Optionale Erweiterungen
  modules/characters/*.json  — Charakter-Templates
  modules/parties/*.json     — Party-Zusammenstellungen

API:
  DiscoveryService(root_path)
  .scan()                     — Indiziert alle JSON-Dateien
  .get_manifest()             — Gibt strukturiertes Manifest zurueck
  .list_rulesets()            — Namen aller Regelsaetze
  .list_adventures()          — Namen aller Abenteuer
  .list_settings()            — Namen aller Settings
  .list_keepers()             — Namen aller Keeper
  .list_extras()              — Namen aller Extras
  .list_characters()          — Namen aller Characters
  .list_parties()             — Namen aller Parties
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("ARS.discovery")


class DiscoveryService:
    """Indiziert verfuegbare Module aller Typen."""

    def __init__(self, root_path: Path | str | None = None) -> None:
        self._root = Path(root_path) if root_path else Path(__file__).parent.parent
        self._rulesets_dir = self._root / "modules" / "rulesets"
        self._adventures_dir = self._root / "modules" / "adventures"
        self._settings_dir = self._root / "modules" / "settings"
        self._keepers_dir = self._root / "modules" / "keepers"
        self._extras_dir = self._root / "modules" / "extras"
        self._characters_dir = self._root / "modules" / "characters"
        self._parties_dir = self._root / "modules" / "parties"
        self._rulesets: dict[str, dict[str, Any]] = {}
        self._adventures: dict[str, dict[str, Any]] = {}
        self._settings: dict[str, dict[str, Any]] = {}
        self._keepers: dict[str, dict[str, Any]] = {}
        self._extras: dict[str, dict[str, Any]] = {}
        self._characters: dict[str, dict[str, Any]] = {}
        self._parties: dict[str, dict[str, Any]] = {}
        self._scanned = False

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def scan(self) -> None:
        """Scannt alle Verzeichnisse und baut den Index."""
        self._rulesets = self._scan_dir(self._rulesets_dir, "ruleset")
        self._adventures = self._scan_dir(self._adventures_dir, "adventure")
        self._settings = self._scan_dir(self._settings_dir, "setting")
        self._keepers = self._scan_dir(self._keepers_dir, "keeper")
        self._extras = self._scan_dir(self._extras_dir, "extra")
        self._characters = self._scan_dir(self._characters_dir, "character")
        self._parties = self._scan_dir(self._parties_dir, "party")
        self._scanned = True
        logger.info(
            "Discovery abgeschlossen: %d Regelsaetze, %d Abenteuer, "
            "%d Settings, %d Keeper, %d Extras, %d Characters, %d Parties",
            len(self._rulesets), len(self._adventures),
            len(self._settings), len(self._keepers), len(self._extras),
            len(self._characters), len(self._parties),
        )

    def _scan_dir(self, directory: Path, asset_type: str) -> dict[str, dict[str, Any]]:
        """Scannt ein Verzeichnis und extrahiert Metadata aus JSON-Dateien."""
        result: dict[str, dict[str, Any]] = {}
        if not directory.exists():
            return result

        for path in sorted(directory.glob("*.json")):
            if path.stem == "schema":
                continue
            try:
                with path.open(encoding="utf-8-sig") as fh:
                    data = json.load(fh)
                info = self._extract_info(path, data, asset_type)
                result[path.stem] = info
                logger.debug("Gefunden: %s '%s'", asset_type, path.stem)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Fehler beim Lesen von %s: %s", path, exc)

        return result

    def _extract_info(
        self, path: Path, data: dict[str, Any], asset_type: str,
    ) -> dict[str, Any]:
        """Extrahiert relevante Metadata aus einer JSON-Datei."""
        info: dict[str, Any] = {
            "name": path.stem,
            "path": str(path),
            "type": asset_type,
            "size_kb": path.stat().st_size // 1024,
        }

        if asset_type == "ruleset":
            meta = data.get("metadata", {})
            info["title"] = meta.get("name", path.stem)
            info["version"] = meta.get("version", "?")
            info["system"] = meta.get("system", "?")
            info["dice"] = data.get("dice_system", {}).get("default_die", "?")
            info["skill_count"] = len(data.get("skills", {}))
            info["char_count"] = len(data.get("characteristics", {}))

        elif asset_type == "adventure":
            info["title"] = data.get("title", path.stem)
            info["setting"] = data.get("setting", "?")
            info["difficulty"] = data.get("difficulty", "?")
            info["location_count"] = len(data.get("locations", []))
            info["npc_count"] = len(data.get("npcs", []))
            info["clue_count"] = len(data.get("clues", []))
            info["flag_count"] = len(data.get("flags", {}))
            info["start_location"] = data.get("start_location", "?")

        elif asset_type == "setting":
            info["title"] = data.get("name", path.stem)
            info["epoch"] = data.get("epoch", "?")
            info["compatible"] = data.get("compatible_rulesets", [])

        elif asset_type == "keeper":
            info["title"] = data.get("name", path.stem)
            info["tone"] = data.get("tone", "?")
            info["compatible"] = data.get("compatible_rulesets", [])

        elif asset_type == "extra":
            info["title"] = data.get("name", path.stem)
            info["extra_type"] = data.get("type", "?")
            info["compatible"] = data.get("compatible_rulesets", [])

        elif asset_type == "character":
            info["title"] = data.get("name", path.stem)
            info["archetype"] = data.get("archetype", "?")
            info["level"] = data.get("level", 1)
            info["compatible"] = data.get("compatible_rulesets", [])

        elif asset_type == "party":
            info["title"] = data.get("name", path.stem)
            info["member_count"] = len(data.get("members", []))
            info["compatible"] = data.get("compatible_rulesets", [])

        return info

    # ------------------------------------------------------------------
    # Abfrage-API
    # ------------------------------------------------------------------

    def get_manifest(self) -> dict[str, Any]:
        """Gibt das komplette Manifest zurueck."""
        if not self._scanned:
            self.scan()
        return {
            "rulesets": dict(self._rulesets),
            "adventures": dict(self._adventures),
            "settings": dict(self._settings),
            "keepers": dict(self._keepers),
            "extras": dict(self._extras),
            "characters": dict(self._characters),
            "parties": dict(self._parties),
            "ruleset_count": len(self._rulesets),
            "adventure_count": len(self._adventures),
            "setting_count": len(self._settings),
            "keeper_count": len(self._keepers),
            "extra_count": len(self._extras),
            "character_count": len(self._characters),
            "party_count": len(self._parties),
        }

    def list_rulesets(self) -> list[str]:
        """Namen aller verfuegbaren Regelsaetze."""
        if not self._scanned:
            self.scan()
        return list(self._rulesets.keys())

    def list_adventures(self) -> list[str]:
        """Namen aller verfuegbaren Abenteuer."""
        if not self._scanned:
            self.scan()
        return list(self._adventures.keys())

    def list_settings(self) -> list[str]:
        """Namen aller verfuegbaren Settings."""
        if not self._scanned:
            self.scan()
        return list(self._settings.keys())

    def list_keepers(self) -> list[str]:
        """Namen aller verfuegbaren Keeper."""
        if not self._scanned:
            self.scan()
        return list(self._keepers.keys())

    def list_extras(self) -> list[str]:
        """Namen aller verfuegbaren Extras."""
        if not self._scanned:
            self.scan()
        return list(self._extras.keys())

    def list_characters(self) -> list[str]:
        """Namen aller verfuegbaren Charakter-Templates."""
        if not self._scanned:
            self.scan()
        return list(self._characters.keys())

    def list_parties(self) -> list[str]:
        """Namen aller verfuegbaren Parties."""
        if not self._scanned:
            self.scan()
        return list(self._parties.keys())

    def get_ruleset_info(self, name: str) -> dict[str, Any] | None:
        """Metadata eines Regelsets nach Name."""
        if not self._scanned:
            self.scan()
        return self._rulesets.get(name)

    def get_adventure_info(self, name: str) -> dict[str, Any] | None:
        """Metadata eines Abenteuers nach Name."""
        if not self._scanned:
            self.scan()
        return self._adventures.get(name)

    def print_manifest(self) -> None:
        """Gibt ein formatiertes Manifest auf stdout aus."""
        if not self._scanned:
            self.scan()

        print("\n=== ARS Asset Discovery ===\n")

        print("Regelsaetze:")
        if self._rulesets:
            for name, info in self._rulesets.items():
                print(
                    f"  [{name}] {info['title']} v{info['version']} "
                    f"| {info['dice']} | {info['skill_count']} Skills "
                    f"| {info['size_kb']} KB"
                )
        else:
            print("  (keine gefunden)")

        print("\nAbenteuer:")
        if self._adventures:
            for name, info in self._adventures.items():
                print(
                    f"  [{name}] {info['title']} "
                    f"| {info['setting']} "
                    f"| {info['location_count']} Orte, {info['npc_count']} NPCs, "
                    f"{info['clue_count']} Hinweise, {info['flag_count']} Flags "
                    f"| {info['size_kb']} KB"
                )
        else:
            print("  (keine gefunden)")

        print("\nSettings:")
        if self._settings:
            for name, info in self._settings.items():
                print(f"  [{name}] {info['title']} | {info['epoch']}")
        else:
            print("  (keine gefunden)")

        print("\nKeeper:")
        if self._keepers:
            for name, info in self._keepers.items():
                print(f"  [{name}] {info['title']} | {info['tone']}")
        else:
            print("  (keine gefunden)")

        print("\nExtras:")
        if self._extras:
            for name, info in self._extras.items():
                print(f"  [{name}] {info['title']} | {info['extra_type']}")
        else:
            print("  (keine gefunden)")

        print("\nCharacters:")
        if self._characters:
            for name, info in self._characters.items():
                print(f"  [{name}] {info['title']} | {info['archetype']} Lv.{info['level']}")
        else:
            print("  (keine gefunden)")

        print("\nParties:")
        if self._parties:
            for name, info in self._parties.items():
                print(f"  [{name}] {info['title']} | {info['member_count']} Mitglieder")
        else:
            print("  (keine gefunden)")
        print()
