"""
core/adventure_manager.py — Adventure Engine & Story Logic

Verwaltet das geladene Abenteuer-Szenario:
  - Location-Tracking (aktueller Ort)
  - Flag-System (World-State Flags mit Initialwerten aus JSON)
  - Clue-Verwaltung (gefundene/offene Hinweise)
  - Lore-Zugriff fuer die KI (get_location_context)

Kopplung:
  - Orchestrator ruft get_location_context() fuer den KI-Prompt
  - Archivist speichert Flags in world_state (SQLite)
  - Tech-GUI kann Flags/Location manuell setzen

Konfiguration:
  - Adventure-JSON muss locations[], flags{} enthalten
  - Schema: modules/adventures/schema.json
"""

from __future__ import annotations

import logging
from typing import Any

from core.event_bus import EventBus

logger = logging.getLogger("ARS.adventure")


class AdventureManager:
    """
    Zentrale Verwaltung eines geladenen Abenteuers.

    Oeffentliche API:
      load(data)                  — Abenteuer-Daten laden
      get_location(id)            — Location-Dict nach ID
      get_current_location()      — Aktueller Ort
      teleport(location_id)       — Ort wechseln
      get_location_context()      — Lore-String fuer KI-Prompt
      get_flag(key)               — Flag-Wert lesen
      set_flag(key, value)        — Flag setzen
      get_all_flags()             — Alle Flags als Dict
      reset_flags()               — Flags auf Initialwerte zuruecksetzen
      get_npc(id)                 — NPC-Dict nach ID
      get_clue(id)                — Clue-Dict nach ID
      get_available_clues()       — Clues am aktuellen Ort
      list_locations()            — Alle Location-IDs + Namen
      list_npcs()                 — Alle NPC-IDs + Namen
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._locations: dict[str, dict] = {}
        self._npcs: dict[str, dict] = {}
        self._clues: dict[str, dict] = {}
        self._flags: dict[str, Any] = {}
        self._initial_flags: dict[str, Any] = {}
        self._current_location_id: str | None = None
        self._loaded = False
        self._archivist = None  # Referenz fuer SQLite-Persistenz

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def title(self) -> str:
        return self._data.get("title", "(kein Abenteuer)")

    # ------------------------------------------------------------------
    # Laden
    # ------------------------------------------------------------------

    def load(self, data: dict[str, Any]) -> None:
        """Laedt Abenteuer-Daten und indiziert Locations/NPCs/Clues."""
        self._data = data

        # Locations indizieren
        self._locations = {}
        for loc in data.get("locations", []):
            self._locations[loc["id"]] = loc
            # Sub-Locations ebenfalls indizieren
            for sub in loc.get("sub_locations", []):
                self._locations[sub["id"]] = sub
                sub["_parent"] = loc["id"]

        # NPCs indizieren
        self._npcs = {npc["id"]: npc for npc in data.get("npcs", [])}

        # Clues indizieren
        self._clues = {clue["id"]: clue for clue in data.get("clues", [])}

        # Flags initialisieren
        self._initial_flags = dict(data.get("flags", {}))
        self._flags = dict(self._initial_flags)

        # Start-Location setzen
        self._current_location_id = data.get("start_location")
        if not self._current_location_id and self._locations:
            self._current_location_id = next(iter(self._locations))

        self._loaded = True
        EventBus.get().emit("adventure", "loaded", {
            "title": self.title,
            "locations": len(self._locations),
            "npcs": len(self._npcs),
            "clues": len(self._clues),
            "flags": len(self._flags),
        })
        logger.info(
            "Abenteuer geladen: '%s' — %d Locations, %d NPCs, %d Clues, %d Flags",
            self.title, len(self._locations), len(self._npcs),
            len(self._clues), len(self._flags),
        )

    # ------------------------------------------------------------------
    # Location-Tracking
    # ------------------------------------------------------------------

    def get_location(self, location_id: str) -> dict[str, Any] | None:
        """Gibt Location-Dict zurueck oder None."""
        return self._locations.get(location_id)

    def get_current_location(self) -> dict[str, Any] | None:
        """Gibt den aktuellen Ort zurueck."""
        if self._current_location_id:
            return self._locations.get(self._current_location_id)
        return None

    @property
    def current_location_id(self) -> str | None:
        return self._current_location_id

    def teleport(self, location_id: str) -> bool:
        """Wechselt den aktuellen Ort. Gibt True bei Erfolg zurueck."""
        if location_id not in self._locations:
            logger.warning("Teleport fehlgeschlagen: Location '%s' nicht gefunden.", location_id)
            return False
        old = self._current_location_id
        self._current_location_id = location_id
        loc = self._locations[location_id]
        EventBus.get().emit("adventure", "location_changed", {
            "old": old,
            "new": location_id,
            "name": loc.get("name", "?"),
        })
        logger.info("Ortswechsel: %s -> %s (%s)", old, location_id, loc.get("name", "?"))
        return True

    def list_locations(self) -> list[tuple[str, str]]:
        """Gibt Liste von (id, name) Tupeln zurueck."""
        result = []
        for loc_id, loc in self._locations.items():
            # Nur Top-Level und Sub-Locations mit _parent kennzeichnen
            parent = loc.get("_parent", "")
            prefix = f"  > " if parent else ""
            result.append((loc_id, f"{prefix}{loc.get('name', loc_id)}"))
        return result

    # ------------------------------------------------------------------
    # KI-Kontext
    # ------------------------------------------------------------------

    def get_location_context(self) -> str:
        """
        Baut einen Lore-String fuer den KI-Prompt basierend auf dem aktuellen Ort.
        Enthaelt: Ortsbeschreibung, Atmosphaere, anwesende NPCs, verfuegbare Hinweise.
        """
        loc = self.get_current_location()
        if not loc:
            return ""

        parts: list[str] = []
        parts.append(f"=== AKTUELLER ORT: {loc.get('name', '?')} ===")

        if loc.get("description"):
            parts.append(loc["description"])

        if loc.get("atmosphere"):
            parts.append(f"Atmosphaere: {loc['atmosphere']}")

        # Anwesende NPCs
        npc_ids = loc.get("npcs_present", [])
        if npc_ids:
            npc_lines = []
            for nid in npc_ids:
                npc = self._npcs.get(nid)
                if npc:
                    npc_lines.append(f"  - {npc.get('name', nid)}: {npc.get('role', '')}")
            if npc_lines:
                parts.append("Anwesende Personen:\n" + "\n".join(npc_lines))

        # Verfuegbare Hinweise (nur wenn Flag-Bedingung erfuellt)
        clue_ids = loc.get("clues_available", [])
        if clue_ids:
            clue_lines = []
            for cid in clue_ids:
                clue = self._clues.get(cid)
                if clue:
                    req_flag = clue.get("requires_flag")
                    if req_flag and not self._flags.get(req_flag):
                        continue
                    probe = clue.get("probe_required", "frei")
                    clue_lines.append(f"  - {clue.get('name', cid)} (Probe: {probe})")
            if clue_lines:
                parts.append("Moegliche Hinweise:\n" + "\n".join(clue_lines))

        # Exits
        exits = loc.get("exits", {})
        if exits:
            exit_lines = [f"  - {self._locations.get(eid, {}).get('name', eid)}: {desc}"
                          for eid, desc in exits.items()]
            parts.append("Ausgaenge:\n" + "\n".join(exit_lines))

        # Keeper Notes
        if loc.get("keeper_notes"):
            parts.append(f"[Keeper-Notiz: {loc['keeper_notes']}]")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Flag-System
    # ------------------------------------------------------------------

    def get_flag(self, key: str) -> Any:
        """Liest einen Flag-Wert."""
        return self._flags.get(key)

    def set_archivist(self, archivist: Any) -> None:
        """Koppelt den Archivist fuer automatische Flag-Persistenz in SQLite."""
        self._archivist = archivist
        logger.debug("Archivist an AdventureManager gekoppelt.")

    def set_flag(self, key: str, value: Any) -> None:
        """Setzt einen Flag-Wert und persistiert ihn via Archivist in SQLite."""
        old = self._flags.get(key, "(neu)")
        self._flags[key] = value
        EventBus.get().emit("adventure", "flag_changed", {
            "key": key, "value": value, "old": old,
        })
        logger.info("Flag gesetzt: %s = %s (war: %s)", key, value, old)
        # Sofort in SQLite world_state persistieren
        if self._archivist:
            self._archivist.merge_world_state({f"flag:{key}": value})

    def get_all_flags(self) -> dict[str, Any]:
        """Gibt Kopie aller Flags zurueck."""
        return dict(self._flags)

    def reset_flags(self) -> None:
        """Setzt alle Flags auf Initialwerte zurueck."""
        self._flags = dict(self._initial_flags)
        logger.info("Flags zurueckgesetzt auf Initialwerte (%d Flags).", len(self._flags))

    def merge_flags_from_world_state(self, world_state: dict[str, Any]) -> None:
        """Uebernimmt Flags aus dem Archivist-WorldState (Session-Restore)."""
        for key, val in world_state.items():
            if key.startswith("flag:"):
                self._flags[key[5:]] = val
            else:
                self._flags[key] = val

    def flags_as_world_state(self) -> dict[str, Any]:
        """Exportiert Flags als WorldState-Dict (fuer Archivist)."""
        return {f"flag:{k}": v for k, v in self._flags.items()}

    # ------------------------------------------------------------------
    # NPC / Clue Zugriff
    # ------------------------------------------------------------------

    def get_npc(self, npc_id: str) -> dict[str, Any] | None:
        return self._npcs.get(npc_id)

    def get_clue(self, clue_id: str) -> dict[str, Any] | None:
        return self._clues.get(clue_id)

    def list_npcs(self) -> list[tuple[str, str]]:
        """Gibt Liste von (id, name) Tupeln zurueck."""
        return [(nid, npc.get("name", nid)) for nid, npc in self._npcs.items()]

    def get_available_clues(self) -> list[dict[str, Any]]:
        """Clues am aktuellen Ort, die per Flag-Bedingung sichtbar sind."""
        loc = self.get_current_location()
        if not loc:
            return []
        result = []
        for cid in loc.get("clues_available", []):
            clue = self._clues.get(cid)
            if clue:
                req = clue.get("requires_flag")
                if req and not self._flags.get(req):
                    continue
                result.append(clue)
        return result
