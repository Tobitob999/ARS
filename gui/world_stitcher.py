"""
gui/world_stitcher.py — World Stitcher fuer organische Gesamtkarte

Nimmt einzelne Raum-Terrains aus einem Adventure-JSON und verbindet sie
zu einem einzigen World-Grid mit organisch geglaetteten Raendern,
windenden Durchgaengen und Dekorationen.

Pipeline:
  1. BFS ab start_location: Raeume in wechselnden Richtungen platzieren
  2. Windende Durchgaenge zwischen Exits graben
  3. Aggressive Cellular Automaton fuer organische Hoehlenwaende
  4. Dekoration streuen (Schutt, Pfuetzen, Kristalle, Moos)
  5. -> WorldLayout als Ergebnis
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("ARS.gui.world_stitcher")

# ── Pfade ────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADVENTURES_DIR = os.path.join(_PROJECT_ROOT, "modules", "adventures")
GENERATED_DIR = os.path.join(_PROJECT_ROOT, "data", "tilesets", "generated")


# ── Datenstruktur ────────────────────────────────────────────────────────────

@dataclass
class WorldLayout:
    """Ergebnis des Stitching-Prozesses."""
    width: int = 0
    height: int = 0
    terrain: list[list[str]] = field(default_factory=list)  # [y][x]
    room_bounds: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)
    room_biome: dict[str, str] = field(default_factory=dict)
    tile_to_room: list[list[str | None]] = field(default_factory=list)
    spawns: dict[str, tuple[int, int]] = field(default_factory=dict)
    decorations: list[dict] = field(default_factory=list)
    start_location: str = ""
    locations: dict[str, dict] = field(default_factory=dict)  # id -> location data


# ── Richtungs-Helfer ─────────────────────────────────────────────────────────

# Reihenfolge in der Richtungen ausprobiert werden, mit Variation
_DIRECTIONS = ["S", "E", "N", "W"]

_DIR_OFFSETS = {
    "N": (0, -1),
    "S": (0, 1),
    "E": (1, 0),
    "W": (-1, 0),
}

_OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


def _exit_direction(pos: list[int], room_h: int, room_w: int) -> str:
    """Bestimmt Richtung eines Exits anhand seiner Position am Rand."""
    x, y = pos[0], pos[1]
    dists = {"N": y, "S": room_h - 1 - y, "W": x, "E": room_w - 1 - x}
    return min(dists, key=dists.get)


def _find_exit_pos(room_map: dict, target_room_id: str) -> list[int] | None:
    """Findet die Exit-Position in einem Raum, die zum Zielraum fuehrt."""
    exits = room_map.get("exits", {})
    if target_room_id in exits:
        pos = exits[target_room_id]
        if isinstance(pos, list) and len(pos) == 2:
            return pos
    return None


# ── Haupt-Stitcher ──────────────────────────────────────────────────────────

def stitch_adventure(adventure: dict) -> WorldLayout | None:
    """Stitcht alle Locations eines Adventures zu einer WorldLayout.

    Platziert Raeume in wechselnden Richtungen mit variablen Abstaenden
    und windenden Durchgaengen fuer ein organisches Hoehlen-Layout.
    """
    locations = adventure.get("locations", [])
    start_id = adventure.get("start_location", "")

    # Locations mit map-Daten sammeln
    loc_map: dict[str, dict] = {}
    for loc in locations:
        if "map" in loc and loc["map"] and "terrain" in loc["map"]:
            loc_map[loc["id"]] = loc

    if not loc_map:
        logger.warning("Keine Locations mit map-Daten gefunden")
        return None

    if start_id not in loc_map:
        start_id = next(iter(loc_map))

    rng = random.Random(hash(start_id) ^ 0xBEEF)

    # Raum-Groessen sammeln
    room_sizes: dict[str, tuple[int, int]] = {}
    for rid, loc in loc_map.items():
        t = loc["map"]["terrain"]
        room_sizes[rid] = (len(t[0]) if t else 0, len(t))

    # BFS mit wechselnden Richtungen
    placed: dict[str, tuple[int, int]] = {start_id: (0, 0)}
    queue = deque([start_id])
    visited = {start_id}

    # Richtungs-Rotation: Nicht immer dieselbe Richtung
    direction_idx = 0

    while queue:
        current_id = queue.popleft()
        current_loc = loc_map[current_id]
        current_map = current_loc["map"]
        cw, ch = room_sizes[current_id]
        cx, cy = placed[current_id]

        for target_id in current_map.get("exits", {}):
            if target_id in visited or target_id not in loc_map:
                continue

            tw, th = room_sizes[target_id]
            target_map = loc_map[target_id]["map"]

            exit_pos = _find_exit_pos(current_map, target_id)
            target_exit = _find_exit_pos(target_map, current_id)

            # Richtung aus Exit-Position bestimmen, aber Variation einfuegen
            if exit_pos:
                preferred_dir = _exit_direction(exit_pos, ch, cw)
            else:
                # Rotierende Richtung fuer Abwechslung
                preferred_dir = _DIRECTIONS[direction_idx % 4]
                direction_idx += 1

            # Abstand: 5-12 Tiles fuer windende Durchgaenge
            gap = rng.randint(5, 12)

            # Zielposition berechnen
            tx, ty = _calc_target_pos(
                cx, cy, cw, ch, tw, th,
                preferred_dir, gap, exit_pos, target_exit, rng,
            )

            # Overlap-Check mit allen platzierten Raeumen
            attempts = 0
            tried_dirs = [preferred_dir]
            while _overlaps(tx, ty, tw, th, placed, room_sizes, target_id, gap=2):
                attempts += 1
                if attempts > 12:
                    break
                # Alternative Richtung probieren
                alt_dir = _DIRECTIONS[(attempts + direction_idx) % 4]
                if alt_dir not in tried_dirs:
                    tried_dirs.append(alt_dir)
                gap_try = gap + attempts * 2
                tx, ty = _calc_target_pos(
                    cx, cy, cw, ch, tw, th,
                    alt_dir, gap_try, exit_pos, target_exit, rng,
                )

            if attempts <= 12:
                placed[target_id] = (tx, ty)
                visited.add(target_id)
                queue.append(target_id)
                direction_idx += 1

    if not placed:
        return None

    # Koordinaten normalisieren + grosszuegiger Rand
    MARGIN = 6
    min_x = min(p[0] for p in placed.values())
    min_y = min(p[1] for p in placed.values())

    for rid in placed:
        ox, oy = placed[rid]
        placed[rid] = (ox - min_x + MARGIN, oy - min_y + MARGIN)

    # World-Grid Groesse berechnen
    max_x = max(placed[rid][0] + room_sizes[rid][0] for rid in placed)
    max_y = max(placed[rid][1] + room_sizes[rid][1] for rid in placed)
    world_w = max_x + MARGIN
    world_h = max_y + MARGIN

    # Terrain-Grid initialisieren (alles void)
    terrain = [["void"] * world_w for _ in range(world_h)]
    tile_to_room = [[None] * world_w for _ in range(world_h)]

    # Room-Terrains einsetzen
    room_bounds: dict[str, tuple[int, int, int, int]] = {}
    room_biome: dict[str, str] = {}
    all_spawns: dict[str, tuple[int, int]] = {}
    all_decos: list[dict] = []

    for rid in placed:
        loc = loc_map[rid]
        rmap = loc["map"]
        rt = rmap["terrain"]
        wx, wy = placed[rid]
        rw, rh = room_sizes[rid]

        room_bounds[rid] = (wx, wy, rw, rh)
        room_biome[rid] = rmap.get("biome", "cave")

        for ry in range(rh):
            for rx in range(rw):
                cell = rt[ry][rx] if rx < len(rt[ry]) else "wall"
                terrain[wy + ry][wx + rx] = cell
                tile_to_room[wy + ry][wx + rx] = rid

        for npc_id, pos in rmap.get("spawns", {}).items():
            if isinstance(pos, list) and len(pos) == 2:
                all_spawns[npc_id] = (wx + pos[0], wy + pos[1])

        for d in rmap.get("decorations", []):
            all_decos.append({
                "x": wx + d.get("x", 0),
                "y": wy + d.get("y", 0),
                "type": d.get("type", "obstacle"),
                "room": rid,
            })

    # Windende Durchgaenge graben
    _carve_winding_passages(terrain, tile_to_room, loc_map, placed, room_sizes,
                            world_w, world_h, rng)

    # Aggressiver organischer Pass
    _organic_smooth(terrain, tile_to_room, all_spawns, loc_map, placed, room_sizes,
                    world_w, world_h, rng)

    # Zweiter Pass: Wand-Raender abrunden
    _round_edges(terrain, world_w, world_h, rng)

    # Dekoration streuen
    extra_decos = _scatter_decorations(terrain, tile_to_room, world_w, world_h, rng)
    all_decos.extend(extra_decos)

    layout = WorldLayout(
        width=world_w,
        height=world_h,
        terrain=terrain,
        room_bounds=room_bounds,
        room_biome=room_biome,
        tile_to_room=tile_to_room,
        spawns=all_spawns,
        decorations=all_decos,
        start_location=start_id,
        locations={rid: loc_map[rid] for rid in placed},
    )

    logger.info("World stitched: %dx%d, %d Raeume", world_w, world_h, len(placed))
    return layout


def _calc_target_pos(
    cx: int, cy: int, cw: int, ch: int,
    tw: int, th: int,
    direction: str, gap: int,
    exit_pos: list[int] | None,
    target_exit: list[int] | None,
    rng: random.Random,
) -> tuple[int, int]:
    """Berechnet Position des Zielraums in gegebener Richtung mit Offset-Jitter."""
    # Lateraler Jitter: -3 bis +3 Tiles seitlich verschoben
    jitter = rng.randint(-3, 3)

    if direction == "S":
        ty = cy + ch + gap
        if exit_pos and target_exit:
            tx = cx + exit_pos[0] - target_exit[0] + jitter
        else:
            tx = cx + (cw - tw) // 2 + jitter
    elif direction == "N":
        ty = cy - th - gap
        if exit_pos and target_exit:
            tx = cx + exit_pos[0] - target_exit[0] + jitter
        else:
            tx = cx + (cw - tw) // 2 + jitter
    elif direction == "E":
        tx = cx + cw + gap
        if exit_pos and target_exit:
            ty = cy + exit_pos[1] - target_exit[1] + jitter
        else:
            ty = cy + (ch - th) // 2 + jitter
    elif direction == "W":
        tx = cx - tw - gap
        if exit_pos and target_exit:
            ty = cy + exit_pos[1] - target_exit[1] + jitter
        else:
            ty = cy + (ch - th) // 2 + jitter
    else:
        tx = cx + cw + gap
        ty = cy + jitter

    return tx, ty


def _overlaps(tx: int, ty: int, tw: int, th: int,
              placed: dict, room_sizes: dict, skip_id: str,
              gap: int = 2) -> bool:
    """Prueft ob ein Raum mit bereits platzierten ueberlappt (mit Puffer)."""
    for rid, (px, py) in placed.items():
        if rid == skip_id:
            continue
        pw, ph = room_sizes[rid]
        if (tx - gap < px + pw and tx + tw + gap > px and
                ty - gap < py + ph and ty + th + gap > py):
            return True
    return False


# ── Windende Durchgaenge ─────────────────────────────────────────────────────

def _carve_winding_passages(
    terrain: list[list[str]],
    tile_to_room: list[list[str | None]],
    loc_map: dict[str, dict],
    placed: dict[str, tuple[int, int]],
    room_sizes: dict[str, tuple[int, int]],
    world_w: int, world_h: int,
    rng: random.Random,
) -> None:
    """Grabt windende Durchgaenge zwischen verbundenen Raeumen."""
    processed_pairs: set[tuple[str, str]] = set()

    for rid, (wx, wy) in placed.items():
        loc = loc_map[rid]
        rmap = loc["map"]
        rw, rh = room_sizes[rid]

        for target_id, exit_pos in rmap.get("exits", {}).items():
            if target_id not in placed:
                continue
            pair = tuple(sorted([rid, target_id]))
            if pair in processed_pairs:
                continue
            processed_pairs.add(pair)

            if not isinstance(exit_pos, list) or len(exit_pos) != 2:
                continue

            # Start: Exit im aktuellen Raum (World-Coords)
            sx = wx + exit_pos[0]
            sy = wy + exit_pos[1]

            # Ziel: Exit im Zielraum (World-Coords)
            target_map = loc_map[target_id]["map"]
            target_exit = _find_exit_pos(target_map, rid)
            twx, twy = placed[target_id]

            if target_exit:
                ex = twx + target_exit[0]
                ey = twy + target_exit[1]
            else:
                ex = twx + room_sizes[target_id][0] // 2
                ey = twy + room_sizes[target_id][1] // 2

            # Exit-Tiles oeffnen
            if 0 <= sy < world_h and 0 <= sx < world_w:
                terrain[sy][sx] = "floor"
            if 0 <= ey < world_h and 0 <= ex < world_w:
                terrain[ey][ex] = "floor"

            # Windenden Durchgang graben
            _carve_winding_path(terrain, tile_to_room,
                                sx, sy, ex, ey,
                                world_w, world_h, rng)

    # Waende um Durchgaenge setzen
    _wall_border_passages(terrain, world_w, world_h)


def _carve_winding_path(
    terrain: list[list[str]],
    tile_to_room: list[list[str | None]],
    x1: int, y1: int, x2: int, y2: int,
    world_w: int, world_h: int,
    rng: random.Random,
) -> None:
    """Grabt einen windenden Durchgang mit variabler Breite.

    Benutzt einen "Drunk Walk" mit Richtungsbias zum Ziel:
    70% Richtung Ziel, 30% seitlich abdriften.
    Durchgang-Breite variiert zwischen 3 und 5 Tiles.
    """
    cx, cy = x1, y1
    max_steps = abs(x2 - x1) + abs(y2 - y1) + 40  # Sicherheits-Limit

    for _ in range(max_steps):
        # Breite an diesem Punkt
        half_w = rng.randint(1, 2)

        # Floor graben
        for dy in range(-half_w, half_w + 1):
            for dx in range(-half_w, half_w + 1):
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < world_w and 0 <= ny < world_h:
                    if terrain[ny][nx] in ("wall", "void", "door"):
                        terrain[ny][nx] = "floor"
                    if tile_to_room[ny][nx] is None:
                        tile_to_room[ny][nx] = "_passage"

        # Am Ziel?
        if abs(cx - x2) <= 1 and abs(cy - y2) <= 1:
            break

        # Naechster Schritt: Bias zum Ziel + Drift
        dx_goal = x2 - cx
        dy_goal = y2 - cy

        if rng.random() < 0.70:
            # Richtung Ziel
            if abs(dx_goal) > abs(dy_goal):
                cx += (1 if dx_goal > 0 else -1)
                # Manchmal auch vertikal bewegen
                if rng.random() < 0.3 and dy_goal != 0:
                    cy += (1 if dy_goal > 0 else -1)
            else:
                cy += (1 if dy_goal > 0 else -1)
                if rng.random() < 0.3 and dx_goal != 0:
                    cx += (1 if dx_goal > 0 else -1)
        else:
            # Seitlich abdriften (Windung erzeugen)
            if abs(dx_goal) > abs(dy_goal):
                # Eigentlich horizontal, aber vertikal abdriften
                cy += rng.choice([-1, 1])
            else:
                cx += rng.choice([-1, 1])

        cx = max(1, min(cx, world_w - 2))
        cy = max(1, min(cy, world_h - 2))


def _wall_border_passages(terrain: list[list[str]], world_w: int, world_h: int) -> None:
    """Setzt Wall-Tiles um Floor-Tiles die an void grenzen."""
    changes: list[tuple[int, int]] = []
    for y in range(world_h):
        for x in range(world_w):
            if terrain[y][x] != "void":
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < world_h and 0 <= nx < world_w:
                        if terrain[ny][nx] in ("floor", "door", "obstacle", "water"):
                            changes.append((x, y))
                            break
                else:
                    continue
                break

    for x, y in changes:
        terrain[y][x] = "wall"


# ── Aggressiver organischer Pass ────────────────────────────────────────────

def _organic_smooth(
    terrain: list[list[str]],
    tile_to_room: list[list[str | None]],
    spawns: dict[str, tuple[int, int]],
    loc_map: dict[str, dict],
    placed: dict[str, tuple[int, int]],
    room_sizes: dict[str, tuple[int, int]],
    world_w: int, world_h: int,
    rng: random.Random,
) -> None:
    """Aggressiver Cellular Automaton fuer organische Hoehlenwaende.

    5 Durchlaeufe mit hoeheren Wahrscheinlichkeiten als zuvor:
      - Wall mit <=3 Wall-Nachbarn + Floor-Nachbar -> 50% floor (Nischen)
      - Floor mit >=6 Wall-Nachbarn -> 35% wall (Vorspruenge)
      - Wall mit genau 4 Wall-Nachbarn + 2+ Floor -> 25% floor (Abrundung)
    """
    # Schutz-Zonen: Exits + Spawns
    protected: set[tuple[int, int]] = set()

    for rid, (wx, wy) in placed.items():
        rmap = loc_map[rid]["map"]
        for _, epos in rmap.get("exits", {}).items():
            if isinstance(epos, list) and len(epos) == 2:
                ex, ey = wx + epos[0], wy + epos[1]
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        protected.add((ex + dx, ey + dy))

    for _, (sx, sy) in spawns.items():
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                protected.add((sx + dx, sy + dy))

    # 5 Durchlaeufe
    for iteration in range(5):
        changes: list[tuple[int, int, str]] = []

        for y in range(1, world_h - 1):
            for x in range(1, world_w - 1):
                if (x, y) in protected:
                    continue

                cell = terrain[y][x]
                if cell == "void":
                    continue

                # Moore-Nachbarn zaehlen
                wall_count = 0
                floor_count = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dy == 0 and dx == 0:
                            continue
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < world_h and 0 <= nx < world_w:
                            n = terrain[ny][nx]
                            if n in ("wall", "void"):
                                wall_count += 1
                            else:
                                floor_count += 1
                        else:
                            wall_count += 1

                if cell == "wall" and floor_count >= 1 and wall_count <= 3:
                    if rng.random() < 0.50:
                        changes.append((x, y, "floor"))
                elif cell == "wall" and floor_count >= 2 and wall_count == 4:
                    if rng.random() < 0.25:
                        changes.append((x, y, "floor"))
                elif cell == "floor" and wall_count >= 6:
                    if rng.random() < 0.35:
                        changes.append((x, y, "wall"))

        for x, y, new_cell in changes:
            terrain[y][x] = new_cell

    # Konnektivitaets-Check
    _ensure_connectivity(terrain, spawns, world_w, world_h)


def _round_edges(
    terrain: list[list[str]], world_w: int, world_h: int, rng: random.Random,
) -> None:
    """Zweiter Pass: Ecken abrunden wo 2 Waende diagonal aneinander stossen.

    Erzeugt das "Hoehlen-Gefuehl" indem scharfe 90-Grad-Ecken aufgebrochen werden.
    """
    for _ in range(2):
        changes: list[tuple[int, int, str]] = []

        for y in range(1, world_h - 1):
            for x in range(1, world_w - 1):
                if terrain[y][x] != "wall":
                    continue

                # Diagonale Nachbarn pruefen
                # Wenn Wall eine "Ecke" ist (2 benachbarte floor + diagonal wall)
                n = terrain[y - 1][x] if y > 0 else "void"
                s = terrain[y + 1][x] if y < world_h - 1 else "void"
                e = terrain[y][x + 1] if x < world_w - 1 else "void"
                w = terrain[y][x - 1] if x > 0 else "void"

                floor_dirs = sum(1 for d in (n, s, e, w)
                                 if d in ("floor", "door", "water", "obstacle"))

                if floor_dirs >= 3 and rng.random() < 0.60:
                    changes.append((x, y, "floor"))
                elif floor_dirs == 2:
                    # L-foermige Ecke aufbrechen
                    is_l = ((n in ("floor",) and e in ("floor",)) or
                            (n in ("floor",) and w in ("floor",)) or
                            (s in ("floor",) and e in ("floor",)) or
                            (s in ("floor",) and w in ("floor",)))
                    if is_l and rng.random() < 0.40:
                        changes.append((x, y, "floor"))

        for x, y, new_cell in changes:
            terrain[y][x] = new_cell


def _ensure_connectivity(
    terrain: list[list[str]],
    spawns: dict[str, tuple[int, int]],
    world_w: int, world_h: int,
) -> None:
    """BFS-Konnektivitaets-Check. Isolierte Floor-Inseln werden zu Wall."""
    walkable = {"floor", "door", "obstacle", "water"}

    start = None
    for y in range(world_h):
        for x in range(world_w):
            if terrain[y][x] in walkable:
                start = (x, y)
                break
        if start:
            break

    if not start:
        return

    visited: set[tuple[int, int]] = set()
    queue = deque([start])
    visited.add(start)

    while queue:
        cx, cy = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < world_w and 0 <= ny < world_h:
                if (nx, ny) not in visited and terrain[ny][nx] in walkable:
                    visited.add((nx, ny))
                    queue.append((nx, ny))

    for y in range(world_h):
        for x in range(world_w):
            if terrain[y][x] in walkable and (x, y) not in visited:
                terrain[y][x] = "wall"


# ── Dekoration ───────────────────────────────────────────────────────────────

def _scatter_decorations(
    terrain: list[list[str]],
    tile_to_room: list[list[str | None]],
    world_w: int, world_h: int,
    rng: random.Random,
) -> list[dict]:
    """Streut reichlich Dekorationen fuer visuellen Reichtum."""
    decos: list[dict] = []

    for y in range(1, world_h - 1):
        for x in range(1, world_w - 1):
            if terrain[y][x] != "floor":
                continue

            walkable_nbrs = sum(
                1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= x + dx < world_w and 0 <= y + dy < world_h
                and terrain[y + dy][x + dx] in ("floor", "door", "obstacle", "water")
            )

            wall_nbrs = sum(
                1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= x + dx < world_w and 0 <= y + dy < world_h
                and terrain[y + dy][x + dx] in ("wall", "void")
            )

            room = tile_to_room[y][x]
            is_passage = room == "_passage"

            # Sackgassen
            if walkable_nbrs == 1:
                decos.append({"x": x, "y": y, "type": "skull", "room": room})
                continue

            # Passage-Tiles: hoehere Deko-Dichte (10%)
            if is_passage:
                r = rng.random()
                if r < 0.04:
                    terrain[y][x] = "obstacle"
                    decos.append({"x": x, "y": y, "type": "obstacle", "room": room})
                elif r < 0.07:
                    terrain[y][x] = "water"
                    decos.append({"x": x, "y": y, "type": "water", "room": room})
                elif r < 0.10:
                    decos.append({"x": x, "y": y, "type": "moss", "room": room})
                continue

            # Neben Wand: Moos, Kristalle, Schutt (8%)
            if wall_nbrs >= 1:
                r = rng.random()
                if r < 0.03:
                    decos.append({"x": x, "y": y, "type": "moss", "room": room})
                elif r < 0.05:
                    decos.append({"x": x, "y": y, "type": "crystal", "room": room})
                elif r < 0.08:
                    terrain[y][x] = "obstacle"
                    decos.append({"x": x, "y": y, "type": "obstacle", "room": room})
                continue

            # Offene Flaechen: Pfuetzen (3%)
            if wall_nbrs == 0 and walkable_nbrs == 4 and rng.random() < 0.03:
                terrain[y][x] = "water"
                decos.append({"x": x, "y": y, "type": "water", "room": room})

    return decos


# ── Adventure laden ──────────────────────────────────────────────────────────

def load_adventure(name_or_path: str) -> dict | None:
    """Laedt ein Adventure-JSON von Pfad oder aus modules/adventures/."""
    if os.path.isfile(name_or_path):
        path = name_or_path
    else:
        path = os.path.join(ADVENTURES_DIR, name_or_path)
        if not path.endswith(".json"):
            path += ".json"

    if not os.path.isfile(path):
        logger.warning("Adventure nicht gefunden: %s", path)
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Adventure-Fehler: %s: %s", path, e)
        return None


def scan_adventures_with_maps() -> list[tuple[str, str, str]]:
    """Scannt adventures/ nach JSONs mit map-Feldern.

    Returns:
        Liste von (filename, title, stem) Tupeln
    """
    results: list[tuple[str, str, str]] = []
    if not os.path.isdir(ADVENTURES_DIR):
        return results

    for fn in sorted(os.listdir(ADVENTURES_DIR)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(ADVENTURES_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                adv = json.load(f)
            has_map = any(
                "map" in loc and loc["map"] and "terrain" in loc.get("map", {})
                for loc in adv.get("locations", [])
            )
            if has_map:
                title = adv.get("title", adv.get("name", fn.replace(".json", "")))
                stem = fn.replace(".json", "")
                results.append((fn, title, stem))
        except (json.JSONDecodeError, OSError):
            pass

    return results
