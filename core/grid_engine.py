"""
core/grid_engine.py — Grid-basierte Bewegungs-Engine

Verwaltet ein tilebasiertes Raumgitter fuer raeumliche Mechaniken:
  - Raum-Generierung aus Adventure-Daten (heuristisch)
  - BFS-Pathfinding (8 Richtungen)
  - Formations-Placement aus Party-JSON
  - Bewegungs-Inferenz (Event-Driven, Combat-Tags, Narrative Keywords)
  - Distanzberechnung, Reichweitenpruefung, Nahkampf-Check
  - Kontext-Injektion fuer KI-Prompt

Skala: 1 Tile = 10ft. AD&D Movement 12 = 12 Tiles/Runde.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from core.event_bus import EventBus

logger = logging.getLogger("ARS.grid_engine")

# ══════════════════════════════════════════════════════════════════════════════
# Datenstrukturen
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GridCell:
    """Eine Zelle im Raum-Gitter."""
    walkable: bool = True
    entity_ids: list[str] = field(default_factory=list)
    terrain: str = "floor"  # floor, wall, door, obstacle, water


@dataclass
class GridEntity:
    """Eine Entitaet auf dem Grid (Party-Member, NPC, Monster)."""
    entity_id: str
    name: str
    entity_type: str  # "party_member", "npc", "monster"
    x: int = 0
    y: int = 0
    symbol: str = "?"
    movement_rate: int = 12  # Tiles pro Runde (effektiv, nach Ruestungsmalus)
    base_movement: int = 12  # Basis-Bewegungsrate (vor Ruestungsmalus)
    movement_used: int = 0   # Verbrauchte Bewegung in dieser Runde
    alive: bool = True


class RoomGrid:
    """Ein generiertes Raum-Gitter mit Zellen, Entities und Ausgaengen."""

    def __init__(self, width: int, height: int, room_id: str = "") -> None:
        self.width = width
        self.height = height
        self.room_id = room_id
        self.cells: list[list[GridCell]] = [
            [GridCell() for _ in range(width)] for _ in range(height)
        ]
        self.entities: dict[str, GridEntity] = {}
        self.exits: dict[str, tuple[int, int]] = {}  # exit_id -> (x, y)

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        return self.cells[y][x].walkable

    def place_entity(self, entity: GridEntity) -> None:
        self.entities[entity.entity_id] = entity
        if self.in_bounds(entity.x, entity.y):
            self.cells[entity.y][entity.x].entity_ids.append(entity.entity_id)

    def remove_entity(self, entity_id: str) -> None:
        ent = self.entities.pop(entity_id, None)
        if ent and self.in_bounds(ent.x, ent.y):
            ids = self.cells[ent.y][ent.x].entity_ids
            if entity_id in ids:
                ids.remove(entity_id)

    def move_entity_to(self, entity_id: str, x: int, y: int) -> None:
        ent = self.entities.get(entity_id)
        if not ent:
            return
        # Alte Zelle aufraumen
        if self.in_bounds(ent.x, ent.y):
            ids = self.cells[ent.y][ent.x].entity_ids
            if entity_id in ids:
                ids.remove(entity_id)
        # Neue Position setzen
        ent.x = x
        ent.y = y
        if self.in_bounds(x, y):
            self.cells[y][x].entity_ids.append(entity_id)


# ══════════════════════════════════════════════════════════════════════════════
# Raum-Dimensions-Heuristik
# ══════════════════════════════════════════════════════════════════════════════

# Keywords fuer Raumgroessen-Erkennung
_SMALL_KW = re.compile(r"\bkammer\b|\bzelle\b|\bnische\b|\balkoven\b|\bversteck\b|\benger?\b|\bklein", re.I)
_CORRIDOR_KW = re.compile(r"\bgang\b|\bkorridor\b|\btunnel\b|\bpassage\b|\bschmal\b|\bflur\b|\bstollen\b", re.I)
_LARGE_KW = re.compile(r"\bhalle\b|\bsaal\b|\bgross|\briesig|\bkathedrale\b|\barena\b|\bthronsal|\bhoehle\b|\bkaverne\b", re.I)

# Richtungs-Keywords fuer Narrative-Inferenz
_MOVE_VERBS = re.compile(
    r"(?:geht?|laeuft?|rennt?|schleicht?|bewegt?\s+sich|marschier|eilt?|"
    r"stuerm|rueck|zieht?\s+sich|flieht?|kriecht?|klettert?)",
    re.I,
)
_DIR_MAP: dict[str, tuple[int, int]] = {
    "nord": (0, -1), "norden": (0, -1), "oben": (0, -1),
    "sued": (0, 1), "sueden": (0, 1), "unten": (0, 1),
    "ost": (1, 0), "osten": (1, 0), "rechts": (1, 0),
    "west": (-1, 0), "westen": (-1, 0), "links": (-1, 0),
    "tuer": (0, 0), "ausgang": (0, 0), "treppe": (0, 0),
    "vorn": (0, -1), "vorwaerts": (0, -1), "zurueck": (0, 1),
}

# Klassen-Symbole (Duplikat aus tab_dungeon_view fuer Standalone-Faehigkeit)
_CLS_SYM: dict[str, str] = {
    "fighter": "F", "kaempfer": "F", "mage": "M", "magier": "M", "wizard": "M",
    "cleric": "C", "kleriker": "C", "priester": "C", "thief": "T", "dieb": "T",
    "schurke": "T", "ranger": "R", "waldlaeufer": "R", "paladin": "P",
    "ritter": "P", "bard": "B", "barde": "B", "druid": "D", "druide": "D",
}

# Spieler-Input-Patterns (fuer parse_player_movement, VOR KI-Aufruf)
_PLAYER_MOVE_VERBS = re.compile(
    r"\b(geh|lauf|renn|schleich|beweg|betret|folg|fluecht|wander|"
    r"marschier|kletter|spring|schwimm|kriech)\w*\b", re.I,
)
_PLAYER_COMBAT_VERBS = re.compile(
    r"\b(greif|angriff|attackier|schlag|schiess|wuerf|cast|zaub)\w*\b", re.I,
)
_PLAYER_EXPLORE_VERBS = re.compile(
    r"\b(untersuch|such|pruef|oeffn|schau|betracht|tast|hoer|lausch)\w*\b", re.I,
)

# Ranged-Waffen-Keywords
_RANGED_KW = re.compile(
    r"bogen|bow|armbrust|crossbow|schleuder|sling|wurf|thrown|pfeil|arrow|bolzen|bolt",
    re.I,
)


def _estimate_room_size(
    location: dict, npc_count: int = 0, exit_count: int = 0,
) -> tuple[int, int]:
    """Heuristik: Raumdimensionen aus Beschreibung ableiten."""
    desc = (
        location.get("description", "") + " " +
        location.get("atmosphere", "") + " " +
        location.get("name", "")
    )

    if _CORRIDOR_KW.search(desc):
        w, h = 7, 15
    elif _SMALL_KW.search(desc):
        w, h = 9, 7
    elif _LARGE_KW.search(desc):
        w, h = 21, 15
    else:
        w, h = 15, 9  # Standard

    # Mehr Platz bei vielen NPCs/Exits
    if npc_count > 5 or exit_count > 3:
        w = max(w, 15)
        h = max(h, 11)

    return w, h


# ══════════════════════════════════════════════════════════════════════════════
# BFS Pathfinding
# ══════════════════════════════════════════════════════════════════════════════

_DIRS_8 = [
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (-1, 1), (1, -1), (-1, -1),
]


def bfs_path(
    grid: RoomGrid,
    start: tuple[int, int],
    goal: tuple[int, int],
    max_steps: int = 50,
) -> list[tuple[int, int]]:
    """BFS-Pathfinding auf dem Grid. Gibt Pfad als Liste von (x,y) zurueck."""
    if start == goal:
        return [start]
    sx, sy = start
    gx, gy = goal

    visited: set[tuple[int, int]] = {(sx, sy)}
    queue: deque[tuple[int, int, list[tuple[int, int]]]] = deque()
    queue.append((sx, sy, [(sx, sy)]))

    while queue:
        cx, cy, path = queue.popleft()
        if len(path) > max_steps:
            continue
        for dx, dy in _DIRS_8:
            nx, ny = cx + dx, cy + dy
            if (nx, ny) in visited:
                continue
            if not grid.in_bounds(nx, ny):
                continue
            cell = grid.cells[ny][nx]
            # Ziel darf auch unwalkable sein (z.B. Tuer)
            if not cell.walkable and (nx, ny) != (gx, gy):
                continue
            new_path = path + [(nx, ny)]
            if (nx, ny) == (gx, gy):
                return new_path
            visited.add((nx, ny))
            queue.append((nx, ny, new_path))

    return []  # Kein Pfad gefunden


# ══════════════════════════════════════════════════════════════════════════════
# GridEngine
# ══════════════════════════════════════════════════════════════════════════════

class GridEngine:
    """
    Zentrale Grid-Verwaltung: Raumgitter, Pathfinding, Bewegungs-Inferenz.

    Emittiert Events via EventBus:
      - grid.room_setup    — neuer Raum geladen
      - grid.entity_moved  — Entity hat sich bewegt
      - grid.combat_move   — Kampfbewegung (zu Gegner)
      - grid.formation_placed — Party aufgestellt
    """

    def __init__(self) -> None:
        self._current_room: RoomGrid | None = None
        self._rooms_cache: dict[str, RoomGrid] = {}
        self._party_members: dict[str, GridEntity] = {}  # entity_id -> GridEntity
        self._bus = EventBus.get()
        self._formation_text: str = ""  # Raw-Formation aus Party-JSON
        self._adventure_data: dict = {}
        self._npc_index: dict[str, dict] = {}  # npc_id -> npc_data
        self._map_spawns: dict[str, list[int]] = {}  # npc_id -> [x, y]

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def set_adventure(self, adventure_data: dict) -> None:
        """Adventure-Daten setzen fuer NPC-Lookup."""
        self._adventure_data = adventure_data
        self._npc_index.clear()
        for npc in adventure_data.get("npcs", []):
            if isinstance(npc, dict) and "id" in npc:
                self._npc_index[npc["id"]] = npc

    def set_formation(self, formation_text: str) -> None:
        """Formation aus Party-JSON setzen."""
        self._formation_text = formation_text

    # ------------------------------------------------------------------
    # Raum-Setup
    # ------------------------------------------------------------------

    def setup_room(self, location: dict, room_id: str = "") -> RoomGrid:
        """Generiert ein Grid fuer einen Raum aus Adventure-Location-Daten."""
        rid = room_id or location.get("id", "unknown")

        # Aus Cache?
        if rid in self._rooms_cache:
            room = self._rooms_cache[rid]
            self._current_room = room
            return room

        # Vordefinierte Karte?
        map_data = location.get("map")
        if map_data:
            return self._setup_from_map(map_data, rid, location)

        # NPCs und Exits zaehlen
        npc_ids = location.get("npcs_present", [])
        exits = location.get("exits", {})
        exit_count = len(exits) if isinstance(exits, dict) else len(exits) if isinstance(exits, list) else 0

        w, h = _estimate_room_size(location, len(npc_ids), exit_count)
        room = RoomGrid(w, h, rid)

        # Waende setzen (1 Tile Rahmen)
        for x in range(w):
            room.cells[0][x] = GridCell(walkable=False, terrain="wall")
            room.cells[h - 1][x] = GridCell(walkable=False, terrain="wall")
        for y in range(h):
            room.cells[y][0] = GridCell(walkable=False, terrain="wall")
            room.cells[y][w - 1] = GridCell(walkable=False, terrain="wall")

        # Tueren positionieren
        if isinstance(exits, dict):
            exit_ids = list(exits.keys())
        elif isinstance(exits, list):
            exit_ids = exits
        else:
            exit_ids = []

        door_positions = self._calc_door_positions(w, h, exit_ids, location)
        for eid, (dx, dy) in door_positions.items():
            room.cells[dy][dx] = GridCell(walkable=True, terrain="door")
            room.exits[eid] = (dx, dy)

        # Terrain-Deko aus Beschreibung
        desc = (location.get("description", "") + " " +
                location.get("atmosphere", "")).lower()
        self._apply_terrain_deco(room, desc)

        self._rooms_cache[rid] = room
        self._current_room = room

        self._bus.emit("grid", "room_setup", {
            "room_id": rid,
            "width": w,
            "height": h,
            "exits": dict(room.exits),
        })
        logger.info("Grid-Raum generiert: %s (%dx%d, %d Exits)",
                     rid, w, h, len(room.exits))
        return room

    def _calc_door_positions(
        self, w: int, h: int, exit_ids: list, location: dict,
    ) -> dict[str, tuple[int, int]]:
        """Berechnet Tuer-Positionen am Raumrand."""
        doors: dict[str, tuple[int, int]] = {}
        mx, my = w // 2, h // 2
        # 4 moegliche Positionen: N, S, W, E
        slots = [
            ("n", (mx, 0)),
            ("s", (mx, h - 1)),
            ("w", (0, my)),
            ("e", (w - 1, my)),
        ]
        exits_dict = location.get("exits", {})
        used_dirs: set[str] = set()

        for i, eid in enumerate(exit_ids):
            desc = ""
            if isinstance(exits_dict, dict):
                desc = str(exits_dict.get(eid, "")).lower()

            # Richtungs-Hint aus Exit-Beschreibung
            placed = False
            for hint, (dx, dy) in _DIR_MAP.items():
                if hint in desc:
                    for d, pos in slots:
                        if d not in used_dirs:
                            if (d == "n" and dy < 0) or (d == "s" and dy > 0) or \
                               (d == "w" and dx < 0) or (d == "e" and dx > 0):
                                doors[eid] = pos
                                used_dirs.add(d)
                                placed = True
                                break
                    break

            if not placed:
                # Round-Robin ueber freie Slots
                for d, pos in slots:
                    if d not in used_dirs:
                        doors[eid] = pos
                        used_dirs.add(d)
                        break
                else:
                    # Alle 4 belegt — zusaetzliche Tuer neben bestehende
                    offset = len(doors)
                    doors[eid] = (min(w - 2, mx + offset), 0)

        return doors

    def _apply_terrain_deco(self, room: RoomGrid, desc: str) -> None:
        """Setzt Terrain-Deko basierend auf Raumbeschreibung."""
        w, h = room.width, room.height
        if any(w in desc for w in ("wasser", "fluss", "bach", "see")):
            for x in range(2, w - 2):
                if room.cells[h - 3][x].terrain == "floor":
                    room.cells[h - 3][x].terrain = "water"
        if any(w in desc for w in ("schutt", "truemmer", "eingestuerzt")):
            for ox, oy in [(3, 3), (w - 4, 4)]:
                if 1 <= ox < w - 1 and 1 <= oy < h - 1:
                    room.cells[oy][ox] = GridCell(walkable=False, terrain="obstacle")
        if any(w in desc for w in ("saeule", "pfeiler")):
            for sx, sy in [(4, 3), (w - 5, 3), (4, h - 4), (w - 5, h - 4)]:
                if 1 <= sx < w - 1 and 1 <= sy < h - 1:
                    room.cells[sy][sx] = GridCell(walkable=False, terrain="obstacle")

    def _setup_from_map(self, map_data: dict, rid: str, location: dict) -> RoomGrid:
        """Baut RoomGrid aus vordefiniertem Map-Feld (Hybrid-Map-Support)."""
        terrain_grid = map_data.get("terrain", [])
        h = len(terrain_grid)
        w = len(terrain_grid[0]) if terrain_grid else 15
        room = RoomGrid(w, h, rid)

        for y, row in enumerate(terrain_grid):
            for x, t in enumerate(row):
                walkable = t not in ("wall",)
                room.cells[y][x] = GridCell(walkable=walkable, terrain=t)

        # Exits aus Map-Daten
        for eid, pos in map_data.get("exits", {}).items():
            ex, ey = pos[0], pos[1]
            if room.in_bounds(ex, ey):
                room.cells[ey][ex] = GridCell(walkable=True, terrain="door")
                room.exits[eid] = (ex, ey)

        # Deko-Positionen
        for deco in map_data.get("decorations", []):
            dx, dy = deco["x"], deco["y"]
            if room.in_bounds(dx, dy):
                room.cells[dy][dx].terrain = deco.get("type", "floor")

        # Spawns merken (fuer place_npcs)
        self._map_spawns: dict[str, list[int]] = map_data.get("spawns", {})

        self._rooms_cache[rid] = room
        self._current_room = room

        self._bus.emit("grid", "room_setup", {
            "room_id": rid,
            "width": w,
            "height": h,
            "exits": dict(room.exits),
        })
        logger.info("Grid-Raum aus Map geladen: %s (%dx%d, %d Exits)",
                     rid, w, h, len(room.exits))
        return room

    # ------------------------------------------------------------------
    # Party-Placement
    # ------------------------------------------------------------------

    def place_party(self, party_members: list[dict], entry_exit: str = "") -> None:
        """Platziert die Party auf dem Grid basierend auf Formation."""
        room = self._current_room
        if not room:
            return

        self._party_members.clear()
        # Bestehende Party-Entities entfernen
        for eid in list(room.entities.keys()):
            if room.entities[eid].entity_type == "party_member":
                room.remove_entity(eid)

        if not party_members:
            return

        # Formation parsen
        rows = self._parse_formation(party_members)

        # Eingangsposition bestimmen
        entry_pos, facing = self._get_entry_position(room, entry_exit)
        ex, ey = entry_pos

        for row_idx, row_members in enumerate(rows):
            for col_idx, member_data in enumerate(row_members):
                name = member_data.get("name", f"member_{row_idx}_{col_idx}")
                eid = member_data.get("id", name.lower().replace(" ", "_"))
                archetype = member_data.get("class", member_data.get("archetype", "?")).lower()
                symbol = _CLS_SYM.get(archetype, archetype[0].upper() if archetype else "?")
                derived = member_data.get("derived_stats", {})
                base_movement = derived.get("Movement", 12)
                movement = base_movement  # Effektiv = Basis (Ruestungsmalus via CombatTracker)

                # Position: Reihe * 2 Tiles Abstand, Spalte * 2 Tiles
                # col_offset: -1, +1 fuer 2er; -2, 0, +2 fuer 3er
                n_cols = len(row_members)
                col_offset = (col_idx * 2) - (n_cols - 1)  # z.B. 2er: -1, +1
                if facing == "s":  # Eingang Norden, Party blickt Sueden
                    px = ex + col_offset
                    py = ey + row_idx * 2
                elif facing == "n":
                    px = ex + col_offset
                    py = ey - row_idx * 2
                elif facing == "e":
                    px = ex + row_idx * 2
                    py = ey + col_offset
                else:  # facing == "w"
                    px = ex - row_idx * 2
                    py = ey + col_offset

                # Clamp ins Innere
                px = max(1, min(room.width - 2, px))
                py = max(1, min(room.height - 2, py))

                entity = GridEntity(
                    entity_id=eid,
                    name=name,
                    entity_type="party_member",
                    x=px, y=py,
                    symbol=symbol,
                    movement_rate=movement,
                    base_movement=base_movement,
                    alive=member_data.get("alive", True),
                )
                room.place_entity(entity)
                self._party_members[eid] = entity

        self._bus.emit("grid", "formation_placed", {
            "room_id": room.room_id,
            "positions": {eid: (e.x, e.y) for eid, e in self._party_members.items()},
        })
        logger.info("Party platziert: %d Members in %s (entry=%s)",
                     len(self._party_members), room.room_id, entry_exit)

    def _parse_formation(self, party_members: list[dict]) -> list[list[dict]]:
        """Parst die Formation aus dem Formation-Text. Fallback: 2er-Reihen."""
        text = self._formation_text.upper()
        rows: list[list[dict]] = []
        name_map = {m.get("name", "").upper(): m for m in party_members}

        if "VORDERE REIHE" in text or "VORNE" in text:
            # Strukturierte Formation
            row_labels = ["VORDERE REIHE", "MITTLERE REIHE", "HINTERE REIHE"]
            for label in row_labels:
                row: list[dict] = []
                if label in text:
                    idx = text.index(label)
                    # Bis zum naechsten Label oder Ende
                    end = len(text)
                    for other in row_labels:
                        if other != label:
                            pos = text.find(other, idx + len(label))
                            if pos > 0:
                                end = min(end, pos)
                    segment = text[idx:end]
                    for name, mdata in name_map.items():
                        if name in segment:
                            row.append(mdata)
                if row:
                    rows.append(row)

        # Fallback: nicht zugewiesene Members in 2er-Reihen
        assigned = set()
        for row in rows:
            for m in row:
                assigned.add(m.get("name", "").upper())

        unassigned = [m for m in party_members if m.get("name", "").upper() not in assigned]
        for i in range(0, len(unassigned), 2):
            rows.append(unassigned[i:i + 2])

        if not rows:
            # Letzter Fallback: alle in 2er-Reihen
            for i in range(0, len(party_members), 2):
                rows.append(party_members[i:i + 2])

        return rows

    def _get_entry_position(
        self, room: RoomGrid, exit_id: str,
    ) -> tuple[tuple[int, int], str]:
        """Bestimmt Startposition und Blickrichtung vom Eingang."""
        if exit_id and exit_id in room.exits:
            dx, dy = room.exits[exit_id]
            # 2 Tiles vom Eingang entfernt
            if dy == 0:  # Nordwand
                return (dx, 3), "s"
            elif dy == room.height - 1:  # Suedwand
                return (dx, room.height - 4), "n"
            elif dx == 0:  # Westwand
                return (3, dy), "e"
            else:  # Ostwand
                return (room.width - 4, dy), "w"

        # Default: Westen, blickt Osten
        return (3, room.height // 2), "e"

    # ------------------------------------------------------------------
    # NPC-Placement
    # ------------------------------------------------------------------

    def place_npcs(self, npc_ids: list[str]) -> None:
        """Platziert NPCs/Monster auf dem Grid.

        Wenn Map-Spawns definiert sind (via _setup_from_map), werden NPCs
        an vordefinierten Koordinaten platziert. Sonst heuristisch.
        """
        room = self._current_room
        if not room:
            return

        # Bestehende NPCs entfernen
        for eid in list(room.entities.keys()):
            if room.entities[eid].entity_type in ("npc", "monster"):
                room.remove_entity(eid)

        spawns = getattr(self, "_map_spawns", {})

        for i, npc_id in enumerate(npc_ids):
            npc_data = self._npc_index.get(npc_id, {})
            name = npc_data.get("name", npc_id)
            npc_type = npc_data.get("type", "monster")
            entity_type = "npc" if npc_type == "friendly" else "monster"

            # Spawn-Position: Map-definiert oder heuristisch
            if npc_id in spawns:
                mx, my = spawns[npc_id][0], spawns[npc_id][1]
            else:
                mx = room.width - 4 - (i % 3) * 2
                my = 2 + (i // 3) * 2
            mx = max(1, min(room.width - 2, mx))
            my = max(1, min(room.height - 2, my))

            entity = GridEntity(
                entity_id=npc_id,
                name=name,
                entity_type=entity_type,
                x=mx, y=my,
                symbol="\u2666",  # ♦
                movement_rate=9,  # Default Monster
            )
            room.place_entity(entity)

        logger.info("NPCs platziert: %d in %s (%d Map-Spawns)",
                     len(npc_ids), room.room_id, len(spawns))

    # ------------------------------------------------------------------
    # Bewegung
    # ------------------------------------------------------------------

    def move_entity(
        self, entity_id: str, target_x: int, target_y: int,
        enforce_budget: bool = False,
    ) -> list[tuple[int, int]]:
        """
        Bewegt eine Entity zum Ziel via BFS. Gibt Pfad zurueck.

        enforce_budget=True: Beschraenkt Pfad auf verbleibende Bewegung
        und zaehlt movement_used hoch.
        """
        room = self._current_room
        if not room or entity_id not in room.entities:
            return []

        entity = room.entities[entity_id]

        if enforce_budget:
            remaining = entity.movement_rate - entity.movement_used
            if remaining <= 0:
                return []
            max_steps = remaining
        else:
            max_steps = entity.movement_rate

        path = bfs_path(room, (entity.x, entity.y), (target_x, target_y),
                         max_steps=max_steps)
        if not path:
            return []

        # Pfad beschraenken auf erlaubte Schritte
        path = path[:max_steps + 1]

        # Bewegung verbrauchen (Pfadlaenge - 1, da Startfeld nicht zaehlt)
        tiles_moved = len(path) - 1
        if enforce_budget:
            entity.movement_used += tiles_moved

        # Entity ans Ziel bewegen
        final_x, final_y = path[-1]
        room.move_entity_to(entity_id, final_x, final_y)

        return path

    # ------------------------------------------------------------------
    # Spieler-Bewegung VOR KI-Aufruf (Single Source of Truth)
    # ------------------------------------------------------------------

    def parse_player_movement(self, user_input: str) -> bool:
        """Parst Spieler-Input nach Bewegungs-Absicht. Bewegt Party VOR KI-Aufruf.

        Erkennt:
        - Richtungen: "gehe nach Norden", "ich laufe suedlich"
        - Ziele: "gehe zur Tuer", "betrete den Gang", "zum Ausgang"
        - Kampf-Approach: "greife an", "Angriff auf den Goblin"
        - Exploration: "untersuche die Truhe", "suche nach Fallen"

        Returns True wenn Bewegung stattfand.
        """
        room = self._current_room
        if not room:
            return False

        text_lower = user_input.lower()
        moved = False

        # ── Richtungs-Bewegung ────────────────────────────────────
        if _PLAYER_MOVE_VERBS.search(user_input):
            direction: tuple[int, int] | None = None
            for keyword, dvec in _DIR_MAP.items():
                if keyword in text_lower:
                    if dvec == (0, 0):
                        direction = self._direction_to_nearest_exit()
                    else:
                        direction = dvec
                    break

            if direction:
                dx, dy = direction
                for eid, entity in self._party_members.items():
                    if not entity.alive:
                        continue
                    nx = max(1, min(room.width - 2, entity.x + dx * 3))
                    ny = max(1, min(room.height - 2, entity.y + dy * 3))
                    if room.is_walkable(nx, ny):
                        path = self.move_entity(eid, nx, ny)
                        if path:
                            self._bus.emit("grid", "entity_moved", {
                                "entity_id": eid,
                                "name": entity.name,
                                "path": path,
                                "move_type": "walk",
                            })
                            moved = True
                if moved:
                    return True

        # ── Kampf-Approach ────────────────────────────────────────
        if _PLAYER_COMBAT_VERBS.search(user_input):
            leader = self._get_party_leader()
            if leader:
                target = self._find_nearest_enemy(leader, entity_type="monster")
                if target:
                    adj = self._get_adjacent_to(target.x, target.y)
                    if adj:
                        path = self.move_entity(leader.entity_id, adj[0], adj[1])
                        if path:
                            self._bus.emit("grid", "entity_moved", {
                                "entity_id": leader.entity_id,
                                "name": leader.name,
                                "path": path,
                                "move_type": "combat_approach",
                            })
                            return True

        # ── Explorations-Approach ─────────────────────────────────
        if _PLAYER_EXPLORE_VERBS.search(user_input):
            leader = self._get_party_leader()
            if leader:
                target = self._find_nearest_deco(leader)
                if target:
                    self._move_toward_target(leader, target[0], target[1],
                                             max_tiles=2, action="explore")
                    return True

        return False

    def _get_party_leader(self) -> GridEntity | None:
        """Erster lebender Party-Member."""
        for ent in self._party_members.values():
            if ent.alive:
                return ent
        return None

    # ------------------------------------------------------------------
    # KI-gesteuerte Monster-Bewegung (Post-KI)
    # ------------------------------------------------------------------

    def execute_monster_moves(self, moves: list[tuple[str, str]]) -> None:
        """Fuehrt KI-gesteuerte Monster-Bewegungen aus.

        Args:
            moves: Liste von (monster_name, richtung) Tupeln aus [MONSTER_BEWEGT:] Tags.
        """
        for name, direction in moves:
            entity = self._find_entity_by_name(name)
            if not entity or entity.entity_type == "party_member":
                continue  # Nur Monster bewegen
            if not entity.alive:
                continue

            target = self._resolve_direction(entity, direction)
            if target:
                path = self.move_entity(entity.entity_id, target[0], target[1])
                if path:
                    self._bus.emit("grid", "entity_moved", {
                        "entity_id": entity.entity_id,
                        "name": entity.name,
                        "path": path,
                        "move_type": "monster",
                        "direction": direction,
                    })
                    logger.debug("Monster %s bewegt: %s → (%d,%d)",
                                 entity.name, direction, path[-1][0], path[-1][1])

    def auto_roam_idle_monsters(self, moved_ids: set[str]) -> None:
        """Idle-Monster patrouillieren: 30% Chance, 1 Tile zufaellige Richtung.

        Args:
            moved_ids: Entity-IDs die bereits via MONSTER_BEWEGT bewegt wurden.
        """
        import random

        room = self._current_room
        if not room:
            return

        _CARDINAL = [(1, 0), (-1, 0), (0, 1), (0, -1)]

        for ent in list(room.entities.values()):
            if ent.entity_type != "monster" or not ent.alive:
                continue
            if ent.entity_id in moved_ids:
                continue
            if random.random() > 0.30:
                continue

            # Zufaellige Richtung
            dirs = list(_CARDINAL)
            random.shuffle(dirs)
            for dx, dy in dirs:
                nx, ny = ent.x + dx, ent.y + dy
                if room.is_walkable(nx, ny):
                    path = self.move_entity(ent.entity_id, nx, ny)
                    if path:
                        self._bus.emit("grid", "entity_moved", {
                            "entity_id": ent.entity_id,
                            "name": ent.name,
                            "path": path,
                            "move_type": "monster",
                            "direction": "patrouille",
                        })
                    break

    def _resolve_direction(self, entity: GridEntity, direction: str) -> tuple[int, int] | None:
        """Loest semantische Richtung in Zielkoordinaten auf."""
        import random

        room = self._current_room
        if not room:
            return None

        _DIR_RESOLVE = {
            "norden": (0, -2), "sueden": (0, 2),
            "osten": (2, 0), "westen": (-2, 0),
        }

        direction = direction.strip().lower()

        # Kardinal-Richtung
        if direction in _DIR_RESOLVE:
            dx, dy = _DIR_RESOLVE[direction]
            nx, ny = entity.x + dx, entity.y + dy
            nx = max(1, min(room.width - 2, nx))
            ny = max(1, min(room.height - 2, ny))
            if room.is_walkable(nx, ny):
                return (nx, ny)
            return None

        # Auf Party zu / Angriff
        if direction in ("naeher", "angriff"):
            target = self._find_nearest_enemy(entity, entity_type="party_member")
            if target:
                adj = self._get_adjacent_to(target.x, target.y)
                return adj
            return None

        # Von Party weg
        if direction == "weg":
            alive = [e for e in self._party_members.values() if e.alive]
            if alive:
                avg_x = sum(e.x for e in alive) / len(alive)
                avg_y = sum(e.y for e in alive) / len(alive)
                dx = -1 if entity.x < avg_x else 1
                dy = -1 if entity.y < avg_y else 1
                nx = max(1, min(room.width - 2, entity.x + dx * 2))
                ny = max(1, min(room.height - 2, entity.y + dy * 2))
                if room.is_walkable(nx, ny):
                    return (nx, ny)
            return None

        # Patrouille: zufaelliger Nachbar
        if direction == "patrouille":
            candidates = []
            for ddx, ddy in _DIRS_8:
                nx, ny = entity.x + ddx, entity.y + ddy
                if room.is_walkable(nx, ny):
                    candidates.append((nx, ny))
            return random.choice(candidates) if candidates else None

        # "lauern" oder unbekannt → keine Bewegung
        return None

    # ------------------------------------------------------------------
    # Bewegungs-Inferenz (Post-KI, 2-Tier — Tier 3 entfernt)
    # ------------------------------------------------------------------

    def infer_movement(self, gm_response: str, current_location: dict | None = None) -> None:
        """
        Inferiert Bewegungen aus der KI-Antwort (Post-KI).

        2 Stufen (Tier 3 Narrative entfernt — Party wird jetzt in
        parse_player_movement() VOR dem KI-Aufruf bewegt):
          1. Combat-Tags: [ANGRIFF:] → Melee/Ranged Bewegung
          2. HP_VERLUST: Angreifer zum Ziel bewegen
        """
        room = self._current_room
        if not room:
            return

        # Tier 1: Combat-Tags
        self._infer_combat_movement(gm_response)

        # Tier 2: HP-Tags fuer Positionierung
        self._infer_hp_movement(gm_response)

    def _infer_combat_movement(self, text: str) -> bool:
        """ANGRIFF-Tags: Melee → zum Ziel, Ranged → stehen bleiben."""
        room = self._current_room
        if not room:
            return False

        # [ANGRIFF: Name | Waffe Schaden] oder [ANGRIFF: Waffe Schaden]
        pattern = re.compile(
            r"\[ANGRIFF:\s*(?:([^|\]]+)\s*\|)?\s*([^|\]]+?)(?:\s+\d+[dDwW]\d+[^|\]]*)?]",
            re.I,
        )
        moved = False

        for m in pattern.finditer(text):
            attacker_name = m.group(1).strip() if m.group(1) else None
            weapon = m.group(2).strip() if m.group(2) else ""
            is_ranged = bool(_RANGED_KW.search(weapon))

            # Attacker identifizieren
            attacker = None
            if attacker_name:
                attacker = self._find_entity_by_name(attacker_name)
            if not attacker:
                # Erster lebender Party-Fighter
                for eid, ent in self._party_members.items():
                    if ent.alive and ent.entity_type == "party_member":
                        attacker = ent
                        break

            if not attacker or is_ranged:
                continue

            # Naechstes Monster finden
            target = self._find_nearest_enemy(attacker)
            if not target:
                continue

            # Zum Gegner bewegen (Melee: 1 Tile Abstand)
            adj = self._get_adjacent_to(target.x, target.y)
            if adj:
                path = self.move_entity(attacker.entity_id, adj[0], adj[1])
                if path:
                    self._bus.emit("grid", "combat_move", {
                        "attacker_id": attacker.entity_id,
                        "attacker_name": attacker.name,
                        "target_id": target.entity_id,
                        "target_name": target.name,
                        "path": path,
                        "attack_type": "melee",
                    })
                    moved = True

        return moved

    def _infer_hp_movement(self, text: str) -> bool:
        """HP_VERLUST-Tags: Monster zum Ziel bewegen."""
        room = self._current_room
        if not room:
            return False

        # [HP_VERLUST: Name | N]
        pattern = re.compile(r"\[HP_VERLUST:\s*([^|\]]+?)(?:\s*\|\s*(\d+))?\s*]", re.I)
        moved = False

        for m in pattern.finditer(text):
            target_name = m.group(1).strip()
            target = self._find_entity_by_name(target_name)
            if not target:
                continue

            # Wenn target ein Party-Member ist, naechstes Monster zum Target bewegen
            if target.entity_type == "party_member":
                attacker = self._find_nearest_enemy(target, entity_type="monster")
                if attacker:
                    adj = self._get_adjacent_to(target.x, target.y)
                    if adj:
                        path = self.move_entity(attacker.entity_id, adj[0], adj[1])
                        if path:
                            self._bus.emit("grid", "combat_move", {
                                "attacker_id": attacker.entity_id,
                                "attacker_name": attacker.name,
                                "target_id": target.entity_id,
                                "target_name": target.name,
                                "path": path,
                                "attack_type": "melee",
                            })
                            moved = True

        return moved

    def _infer_narrative_movement(self, text: str) -> None:
        """Richtungsverben + Richtung → Party bewegen."""
        room = self._current_room
        if not room:
            return

        if not _MOVE_VERBS.search(text):
            return

        # Richtung bestimmen
        direction: tuple[int, int] | None = None
        text_lower = text.lower()
        for keyword, dvec in _DIR_MAP.items():
            if keyword in text_lower:
                if dvec == (0, 0):
                    # Tuer/Ausgang: naechsten Exit finden
                    direction = self._direction_to_nearest_exit()
                else:
                    direction = dvec
                break

        if not direction:
            return

        dx, dy = direction
        # Alle Party-Members 2 Tiles in Richtung bewegen
        for eid, entity in self._party_members.items():
            if not entity.alive:
                continue
            nx = entity.x + dx * 2
            ny = entity.y + dy * 2
            nx = max(1, min(room.width - 2, nx))
            ny = max(1, min(room.height - 2, ny))
            if room.is_walkable(nx, ny):
                path = self.move_entity(eid, nx, ny)
                if path:
                    self._bus.emit("grid", "entity_moved", {
                        "entity_id": eid,
                        "name": entity.name,
                        "path": path,
                        "move_type": "walk",
                    })

    # ------------------------------------------------------------------
    # Aktions-Bewegungs-Inferenz (Nicht-Kampf-Tags)
    # ------------------------------------------------------------------

    def infer_action_movement(self, gm_response: str) -> None:
        """Mappt Nicht-Kampf-Tags auf raeumliche Charakter-Bewegung.

        Wird vom Orchestrator NACH infer_movement() aufgerufen.
        Tags: [PROBE:], [INVENTAR: +Item], [ZAUBER_VERBRAUCHT:]
        """
        room = self._current_room
        if not room:
            return

        # [PROBE: Skill Zielwert] oder [PROBE: Name | Skill Zielwert]
        for m in re.finditer(
            r"\[PROBE:\s*(?:([^|\]]+)\s*\|)?\s*([^|\]]+?)(?:\s+\d+)?\s*]",
            gm_response, re.I,
        ):
            actor_name = m.group(1).strip() if m.group(1) else None
            actor = self._find_actor_for_action(actor_name)
            if actor:
                target = self._find_interaction_target(actor)
                if target:
                    self._move_toward_target(actor, target[0], target[1],
                                             max_tiles=2, action="probe")

        # [INVENTAR: +Item] oder [INVENTAR: Name | +Item]
        for m in re.finditer(
            r"\[INVENTAR:\s*(?:([^|\]]+)\s*\|)?\s*\+([^]]+)]",
            gm_response, re.I,
        ):
            actor_name = m.group(1).strip() if m.group(1) else None
            actor = self._find_actor_for_action(actor_name)
            if actor:
                deco_pos = self._find_nearest_deco(actor)
                if deco_pos:
                    self._move_toward_target(actor, deco_pos[0], deco_pos[1],
                                             max_tiles=3, action="loot")

        # [ZAUBER_VERBRAUCHT: Spell] oder [ZAUBER_VERBRAUCHT: Name | Spell]
        for m in re.finditer(
            r"\[ZAUBER_VERBRAUCHT:\s*(?:([^|\]]+)\s*\|)?\s*([^]]+)]",
            gm_response, re.I,
        ):
            actor_name = m.group(1).strip() if m.group(1) else None
            actor = self._find_actor_for_action(actor_name)
            if actor:
                ny = max(1, actor.y - 1)
                if room.is_walkable(actor.x, ny):
                    self._move_toward_target(actor, actor.x, ny,
                                             max_tiles=1, action="cast")

    def _find_actor_for_action(self, name: str | None) -> GridEntity | None:
        """Findet den Actor — per Name oder ersten lebenden Party-Member."""
        if name:
            found = self._find_entity_by_name(name)
            if found:
                return found
        for ent in self._party_members.values():
            if ent.alive:
                return ent
        return None

    def _find_interaction_target(self, actor: GridEntity) -> tuple[int, int] | None:
        """Findet ein interaktives Ziel in der Naehe (Tuer, Obstacle, Exit)."""
        room = self._current_room
        if not room:
            return None
        best: tuple[int, int] | None = None
        best_dist = 999
        for dy in range(-5, 6):
            for dx in range(-5, 6):
                nx, ny = actor.x + dx, actor.y + dy
                if not room.in_bounds(nx, ny):
                    continue
                t = room.cells[ny][nx].terrain
                if t in ("door", "obstacle", "water", "trap"):
                    d = abs(dx) + abs(dy)
                    if d < best_dist:
                        best_dist = d
                        best = (nx, ny)
        return best

    def _find_nearest_deco(self, actor: GridEntity) -> tuple[int, int] | None:
        """Findet das naechste Deko-Feld (nicht-floor, nicht-wall)."""
        room = self._current_room
        if not room:
            return None
        best: tuple[int, int] | None = None
        best_dist = 999
        for dy in range(-5, 6):
            for dx in range(-5, 6):
                nx, ny = actor.x + dx, actor.y + dy
                if not room.in_bounds(nx, ny):
                    continue
                t = room.cells[ny][nx].terrain
                if t in ("obstacle", "door"):
                    d = abs(dx) + abs(dy)
                    if d < best_dist:
                        best_dist = d
                        best = (nx, ny)
        return best

    def _move_toward_target(self, actor: GridEntity, tx: int, ty: int,
                            max_tiles: int = 2, action: str = "") -> None:
        """Bewegt Actor Richtung Ziel, maximal max_tiles Schritte."""
        adj = self._get_adjacent_to(tx, ty)
        if not adj:
            adj = (tx, ty)
        path = self.move_entity(actor.entity_id, adj[0], adj[1])
        if path:
            path = path[:max_tiles + 1]
            self._bus.emit("grid", "entity_moved", {
                "entity_id": actor.entity_id,
                "name": actor.name,
                "path": path,
                "move_type": "action",
                "action": action,
            })

    # ------------------------------------------------------------------
    # Bewegungsbudget-Verwaltung
    # ------------------------------------------------------------------

    def reset_all_movement(self) -> None:
        """Setzt movement_used fuer alle Entities auf 0 (Rundenbeginn)."""
        room = self._current_room
        if not room:
            return
        for ent in room.entities.values():
            ent.movement_used = 0

    def get_movement_remaining(self, entity_id: str) -> int:
        """Verbleibende Bewegung fuer eine Entity."""
        room = self._current_room
        if not room:
            return 0
        ent = room.entities.get(entity_id)
        if not ent:
            return 0
        return max(0, ent.movement_rate - ent.movement_used)

    # ------------------------------------------------------------------
    # Raumwechsel
    # ------------------------------------------------------------------

    def transition_room(self, new_location: dict, exit_used: str = "") -> RoomGrid:
        """Wechselt zu einem neuen Raum. Party wird am Eingang platziert."""
        new_id = new_location.get("id", "unknown")

        # Alten Raum aufraumen: Party-Entities entfernen
        if self._current_room:
            for eid in list(self._party_members.keys()):
                self._current_room.remove_entity(eid)

        # Neuen Raum setup
        room = self.setup_room(new_location, new_id)

        # NPCs platzieren
        npc_ids = new_location.get("npcs_present", [])
        if npc_ids:
            self.place_npcs(npc_ids)

        # Gegenueberliegenden Eingang finden
        entry_exit = ""
        if exit_used and self._current_room:
            # exit_used ist die ID des Raums von dem wir kommen
            for eid, pos in room.exits.items():
                if eid == exit_used:
                    entry_exit = eid
                    break

        return room

    # ------------------------------------------------------------------
    # Distanz & Reichweite
    # ------------------------------------------------------------------

    def get_distance(self, id_a: str, id_b: str) -> int:
        """Chebyshev-Distanz (8-Richtungen) zwischen zwei Entities."""
        room = self._current_room
        if not room:
            return 999
        a = room.entities.get(id_a)
        b = room.entities.get(id_b)
        if not a or not b:
            return 999
        return max(abs(a.x - b.x), abs(a.y - b.y))

    def get_entities_in_range(
        self, origin: tuple[int, int], radius: int,
    ) -> list[GridEntity]:
        """Alle Entities im Umkreis (Chebyshev)."""
        room = self._current_room
        if not room:
            return []
        ox, oy = origin
        result = []
        for ent in room.entities.values():
            if max(abs(ent.x - ox), abs(ent.y - oy)) <= radius:
                result.append(ent)
        return result

    def is_in_melee_range(self, id_a: str, id_b: str) -> bool:
        """True wenn Distanz <= 1 (angrenzend)."""
        return self.get_distance(id_a, id_b) <= 1

    # ------------------------------------------------------------------
    # Kontext fuer KI-Prompt
    # ------------------------------------------------------------------

    def get_context_for_prompt(self) -> str:
        """Generiert erweiterten Grid-Kontext fuer die KI-Injektion.

        Enthaelt: Raum-ID, Dimensionen, Party-Positionen, Monster-Liste,
        Nahkampf-Paare, Distanzen, Terrain-Objekte, Sichtbarkeit.
        """
        room = self._current_room
        if not room or not room.entities:
            return ""

        lines: list[str] = ["=== GRID-POSITIONEN ==="]

        # ── Raum-Info ─────────────────────────────────────────────
        lines.append(f"Raum: {room.room_id} ({room.width}x{room.height})")

        # ── Party-Positionen ──────────────────────────────────────
        party_parts = []
        party_ids = []
        for eid, ent in room.entities.items():
            if ent.entity_type == "party_member" and ent.alive:
                party_ids.append(eid)
                party_parts.append(f"{ent.name}({ent.x},{ent.y})")
        if party_parts:
            lines.append("Party: " + " ".join(party_parts))

        # ── Monster-Liste ─────────────────────────────────────────
        monster_parts = []
        enemy_ids = []
        alive_count = 0
        dead_count = 0
        for eid, ent in room.entities.items():
            if ent.entity_type == "monster":
                if ent.alive:
                    enemy_ids.append(eid)
                    alive_count += 1
                    monster_parts.append(f"{ent.name}({ent.x},{ent.y})")
                else:
                    dead_count += 1
        if monster_parts:
            summary = f" [{alive_count} lebend"
            if dead_count:
                summary += f", {dead_count} tot"
            summary += "]"
            lines.append("Monster: " + " ".join(monster_parts) + summary)

        # ── Nahkampf-Paare ────────────────────────────────────────
        melee_pairs = []
        for pid in party_ids:
            for mid in enemy_ids:
                if self.is_in_melee_range(pid, mid):
                    pn = room.entities[pid].name
                    mn = room.entities[mid].name
                    melee_pairs.append(f"{pn}\u2194{mn}")
        if melee_pairs:
            lines.append("Nahkampf: " + ", ".join(melee_pairs))

        # ── Distanzen (Party → Feinde) ────────────────────────────
        if enemy_ids and party_ids:
            dist_parts = []
            for pid in party_ids:
                pe = room.entities[pid]
                min_dist = 999
                nearest = ""
                for mid in enemy_ids:
                    d = self.get_distance(pid, mid)
                    if d < min_dist:
                        min_dist = d
                        nearest = room.entities[mid].name
                if nearest and min_dist > 1:
                    dist_parts.append(f"{pe.name}\u2192{nearest}:{min_dist}")
            if dist_parts:
                lines.append("Distanz: " + ", ".join(dist_parts))

        # ── Terrain-Objekte im Sichtfeld ──────────────────────────
        terrain_objs = self._get_visible_terrain()
        if terrain_objs:
            t_parts = [f"{t}({x},{y})" for t, x, y in terrain_objs]
            lines.append("Terrain: " + " ".join(t_parts))

        # ── Sichtbarkeits-Zusammenfassung ─────────────────────────
        visible_items: list[str] = []
        if alive_count:
            names = set()
            for mid in enemy_ids:
                base = room.entities[mid].name.split("_")[0]
                names.add(base)
            for name in sorted(names):
                cnt = sum(1 for mid in enemy_ids if room.entities[mid].name.startswith(name))
                visible_items.append(f"{cnt} {name}" if cnt > 1 else name)
        terrain_types = set()
        for t, _, _ in terrain_objs:
            terrain_types.add(t)
        for t in sorted(terrain_types):
            cnt = sum(1 for tt, _, _ in terrain_objs if tt == t)
            visible_items.append(f"{cnt} {t}" if cnt > 1 else t)
        if visible_items:
            lines.append("Sichtbar: Party sieht " + ", ".join(visible_items))

        return "\n".join(lines) if len(lines) > 1 else ""

    def get_all_positions(self) -> dict[str, tuple[int, int]]:
        """Alle Entity-Positionen als Dict zurueckgeben."""
        room = self._current_room
        if not room:
            return {}
        return {eid: (e.x, e.y) for eid, e in room.entities.items()}

    def get_room_dimensions(self) -> tuple[int, int]:
        """Aktuelle Raum-Dimensionen."""
        room = self._current_room
        if not room:
            return 15, 9
        return room.width, room.height

    def get_current_room(self) -> RoomGrid | None:
        """Gibt das aktuelle RoomGrid zurueck."""
        return self._current_room

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------

    def _get_visible_terrain(self, radius: int = 8) -> list[tuple[str, int, int]]:
        """Terrain-Objekte im Sichtradius der Party (nicht-floor, nicht-wall)."""
        room = self._current_room
        if not room:
            return []

        # Party-Zentrum berechnen
        alive = [e for e in self._party_members.values() if e.alive]
        if not alive:
            return []
        cx = int(sum(e.x for e in alive) / len(alive))
        cy = int(sum(e.y for e in alive) / len(alive))

        _TERRAIN_LABELS = {
            "door": "Tuer", "obstacle": "Hindernis", "water": "Wasser",
            "trap": "Falle", "stairs": "Treppe",
        }
        result: list[tuple[str, int, int]] = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                nx, ny = cx + dx, cy + dy
                if not room.in_bounds(nx, ny):
                    continue
                t = room.cells[ny][nx].terrain
                if t not in ("floor", "wall"):
                    label = _TERRAIN_LABELS.get(t, t.capitalize())
                    result.append((label, nx, ny))

        # Exits hinzufuegen
        for eid, (ex, ey) in room.exits.items():
            if abs(ex - cx) <= radius and abs(ey - cy) <= radius:
                result.append((f"Ausgang_{eid}", ex, ey))

        return result

    def _find_entity_by_name(self, name: str) -> GridEntity | None:
        """Findet eine Entity per Name (case-insensitive, Teilstring)."""
        room = self._current_room
        if not room:
            return None
        name_lower = name.lower().strip()
        # Exakt
        for ent in room.entities.values():
            if ent.name.lower() == name_lower:
                return ent
        # Teilstring
        for ent in room.entities.values():
            if name_lower in ent.name.lower() or ent.name.lower() in name_lower:
                return ent
        return None

    def _find_nearest_enemy(
        self, entity: GridEntity, entity_type: str = "monster",
    ) -> GridEntity | None:
        """Findet den naechsten lebenden Feind."""
        room = self._current_room
        if not room:
            return None
        nearest = None
        min_dist = 999
        for ent in room.entities.values():
            if ent.entity_type != entity_type or not ent.alive:
                continue
            d = max(abs(ent.x - entity.x), abs(ent.y - entity.y))
            if d < min_dist:
                min_dist = d
                nearest = ent
        return nearest

    def _get_adjacent_to(self, x: int, y: int) -> tuple[int, int] | None:
        """Findet ein freies walkable Feld neben (x, y)."""
        room = self._current_room
        if not room:
            return None
        for dx, dy in _DIRS_8:
            nx, ny = x + dx, y + dy
            if room.is_walkable(nx, ny):
                return (nx, ny)
        return None

    def _direction_to_nearest_exit(self) -> tuple[int, int] | None:
        """Richtungsvektor zum naechsten Ausgang."""
        room = self._current_room
        if not room or not room.exits or not self._party_members:
            return None

        # Mittelpunkt der Party
        alive = [e for e in self._party_members.values() if e.alive]
        if not alive:
            return None
        avg_x = sum(e.x for e in alive) / len(alive)
        avg_y = sum(e.y for e in alive) / len(alive)

        # Naechster Exit
        min_dist = 999.0
        best_exit = None
        for eid, (ex, ey) in room.exits.items():
            d = ((ex - avg_x) ** 2 + (ey - avg_y) ** 2) ** 0.5
            if d < min_dist:
                min_dist = d
                best_exit = (ex, ey)

        if not best_exit:
            return None

        dx = 1 if best_exit[0] > avg_x else -1 if best_exit[0] < avg_x else 0
        dy = 1 if best_exit[1] > avg_y else -1 if best_exit[1] < avg_y else 0
        return (dx, dy)
