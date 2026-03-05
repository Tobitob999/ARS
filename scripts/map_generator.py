#!/usr/bin/env python3
"""Map Generator -- Automatische Spielekarten-Erzeugung fuer ARS-Abenteuer.

Pipeline:
  Quelle (Bild / Text / Adventure-JSON)
    -> Gemini Vision/Text -> Abstrakte Raumlayout-Struktur
    -> Algorithmische Grid-Konvertierung -> terrain 2D Array
    -> Fehlende Tiles? -> Sprite-Generator (Hybrid)
    -> Pixel-Renderer -> gerendertes Kartenbild
    -> Gemini evaluiert Qualitaet -> Score + Vorschlaege
    -> Anpassungen anwenden -> zurueck zu Rendering (max 3 Iterationen)
    -> Fertige Karte -> Adventure-JSON injizieren + Preview speichern

Usage:
  py -3 scripts/map_generator.py --adventure goblin_cave [--preview] [--inject]
  py -3 scripts/map_generator.py --adventure goblin_cave --image karte.png
  py -3 scripts/map_generator.py --location boss_lair --text "Grosse Hoehle..."
  py -3 scripts/map_generator.py --adventure goblin_cave --no-ai
"""
from __future__ import annotations

import argparse
import collections
import copy
import io
import json
import logging
import math
import os
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

ADVENTURES_DIR = os.path.join(_PROJECT_ROOT, "modules", "adventures")
GENERATED_MAPS_DIR = os.path.join(_PROJECT_ROOT, "data", "generated_maps")
GENERATED_TILES_DIR = os.path.join(_PROJECT_ROOT, "data", "tilesets", "generated")

logger = logging.getLogger("map_generator")

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RoomLayout:
    room_id: str
    name: str
    width: int             # Grid-Tiles (1 Tile = 10ft)
    height: int
    shape: str             # rectangular/circular/irregular/L-shaped/corridor
    biome: str             # Key aus BIOME_DEFS
    exits: dict[str, dict]  # exit_id -> {direction, type, pos}
    features: list[dict]    # {type, x, y, description}
    spawns: dict[str, list[int]]  # npc_id -> [x, y]
    description: str


@dataclass
class MapResult:
    room_id: str
    terrain_2d: list[list[str]]    # GridEngine-kompatibel
    exits: dict[str, list[int]]    # exit_id -> [x, y]
    decorations: list[dict]        # {x, y, type}
    spawns: dict[str, list[int]]
    biome: str
    rendered_image: Any = None      # PIL Image or None
    quality_score: float = 0.0
    iteration: int = 0


# ---------------------------------------------------------------------------
# Biome Detection (rein algorithmisch)
# ---------------------------------------------------------------------------
_BIOME_KEYWORDS: dict[str, list[str]] = {
    "cave":      ["hoehle", "cave", "grotte", "kaverne", "tropf", "stalaktit",
                  "feucht", "unterirdisch", "tunnel"],
    "crypt":     ["krypta", "gruft", "crypt", "grab", "sarkophag", "katakomben",
                  "untot", "leichen", "begraebnis"],
    "dungeon":   ["kerker", "dungeon", "verlies", "zelle", "gefaengnis", "ketten"],
    "forest":    ["wald", "forest", "lichtung", "clearing", "dickicht", "baeume",
                  "moos", "unterholz"],
    "temple":    ["tempel", "temple", "altar", "schrein", "shrine", "heilig",
                  "kapelle", "kathedrale", "kirche"],
    "sewer":     ["kanal", "sewer", "abwasser", "kloake", "abfluss"],
    "mine":      ["mine", "stollen", "bergwerk", "schacht", "erz", "grube"],
    "swamp":     ["sumpf", "swamp", "moor", "morast", "feuchtgebiet"],
    "volcano":   ["vulkan", "volcano", "lava", "magma", "krater", "feuer"],
    "ice":       ["eis", "ice", "frost", "gletscher", "schnee", "gefroren"],
    "desert":    ["wueste", "desert", "sand", "oase", "duene"],
    "beach":     ["strand", "beach", "kueste", "hafen", "pier", "dock"],
    "river":     ["fluss", "river", "bach", "strom", "wasserfall", "see"],
    "underdark":  ["underdark", "drow", "pilz", "fungi", "tiefe", "abgrund"],
}


def detect_biome(location: dict, adventure: dict | None = None) -> str:
    """Erkennt Biome aus Location-Text via Keyword-Matching."""
    parts = [
        location.get("description", ""),
        location.get("atmosphere", ""),
        location.get("name", ""),
    ]
    if adventure:
        parts.append(adventure.get("setting", ""))
    text = " ".join(parts).lower()

    scores: dict[str, int] = {}
    for biome, keywords in _BIOME_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[biome] = score

    if not scores:
        return "dungeon"
    return max(scores, key=scores.get)


# ---------------------------------------------------------------------------
# JSON Extraction helper (like sprite_from_image.py)
# ---------------------------------------------------------------------------
def _extract_json(text: str) -> dict:
    """Extrahiert JSON aus Gemini-Antwort (mit oder ohne ```json Wrapper)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"Kein JSON in Antwort gefunden: {text[:200]}")


def _extract_json_or_list(text: str) -> dict | list:
    """Extrahiert JSON dict oder list aus Antwort."""
    m = re.search(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"[\[\{].*[\]\}]", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"Kein JSON in Antwort gefunden: {text[:200]}")


# ---------------------------------------------------------------------------
# Gemini API helpers
# ---------------------------------------------------------------------------
def _gemini_call(api_key: str, prompt: str, image_bytes: bytes | None = None,
                 mime_type: str = "image/png") -> str:
    """Einzelner Gemini-Aufruf. Gibt Response-Text zurueck."""
    from google import genai  # type: ignore[import]
    from google.genai import types  # type: ignore[import]

    client = genai.Client(api_key=api_key)

    parts: list = []
    if image_bytes:
        parts.append(types.Part.from_data(data=image_bytes, mime_type=mime_type))
    parts.append({"text": prompt})

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[{"role": "user", "parts": parts}],
        config=types.GenerateContentConfig(temperature=0.3),
    )

    tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        tokens = getattr(response.usage_metadata, "total_token_count", 0) or 0
    logger.info("Gemini: %d Tokens", tokens)

    return response.text or ""


# ---------------------------------------------------------------------------
# Image Analysis (Gemini Vision)
# ---------------------------------------------------------------------------
_IMAGE_ANALYSIS_PROMPT = """\
Analysiere diese Karte/Grundriss und beschreibe das Layout als JSON.
Antworte NUR mit einem JSON-Objekt (keine Erklaerung):
{
  "rooms": [
    {
      "id": "room_1",
      "name": "Name des Raums",
      "width": 15,
      "height": 9,
      "shape": "rectangular",
      "features": [
        {"type": "obstacle", "x": 3, "y": 4, "description": "Saeule"},
        {"type": "water", "x": 7, "y": 2, "description": "Brunnen"}
      ]
    }
  ],
  "connections": [
    {"from": "room_1", "to": "room_2", "type": "door"}
  ],
  "setting": "cave"
}
Regeln:
- 1 Tile = ca. 10 Fuss / 3 Meter
- Breite/Hoehe in ganzen Tiles (min 7, max 25)
- shape: rectangular, circular, irregular, L-shaped, corridor
- features type: obstacle, water, door
- setting: cave, dungeon, crypt, temple, forest, etc.
"""


def analyze_map_image(image_path: str, api_key: str) -> dict:
    """Analysiert ein Kartenbild via Gemini Vision."""
    from PIL import Image

    img = Image.open(image_path)
    img.thumbnail((1024, 1024), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    text = _gemini_call(api_key, _IMAGE_ANALYSIS_PROMPT, image_bytes=png_bytes)
    result = _extract_json(text)
    logger.info("Bild-Analyse: %d Raeume erkannt", len(result.get("rooms", [])))
    return result


# ---------------------------------------------------------------------------
# Text Analysis (Gemini Text)
# ---------------------------------------------------------------------------
_TEXT_ANALYSIS_PROMPT = """\
Erzeuge ein Grid-Layout fuer diesen Raum. Antworte NUR mit JSON:
{{
  "width": 15,
  "height": 9,
  "shape": "rectangular",
  "terrain_features": [
    {{"type": "obstacle", "x": 3, "y": 4, "description": "Saeule"}},
    {{"type": "water", "x": 7, "y": 2, "description": "Brunnen"}}
  ],
  "exit_positions": {{
    "exit_id": {{"direction": "N", "preferred_x": 7}}
  }},
  "npc_positions": {{
    "npc_id": [5, 3]
  }}
}}
Regeln:
- 1 Tile = 10 Fuss
- Waende sind implizit am Rand
- Exits muessen auf Waenden liegen (N=y0, S=ymax, W=x0, E=xmax)
- NPCs auf begehbaren Feldern (nicht auf Waenden)
- shape: rectangular, circular, irregular, L-shaped, corridor

RAUM-BESCHREIBUNG:
{description}

ATMOSPHAERE:
{atmosphere}

EXITS:
{exits}

NPCS:
{npcs}
"""


def analyze_location_text(location: dict, api_key: str) -> dict:
    """Erzeugt Grid-Layout aus Text-Beschreibung via Gemini."""
    exits_text = "\n".join(
        f"- {eid}: {desc}" for eid, desc in location.get("exits", {}).items()
    )
    npcs_text = "\n".join(
        f"- {nid}" for nid in location.get("npcs_present", [])
    )

    prompt = _TEXT_ANALYSIS_PROMPT.format(
        description=location.get("description", "Unbekannter Raum"),
        atmosphere=location.get("atmosphere", ""),
        exits=exits_text or "Keine",
        npcs=npcs_text or "Keine",
    )

    text = _gemini_call(api_key, prompt)
    result = _extract_json(text)
    logger.info("Text-Analyse: %dx%d, shape=%s",
                result.get("width", 0), result.get("height", 0),
                result.get("shape", "?"))
    return result


# ---------------------------------------------------------------------------
# Algorithmic Grid Conversion
# ---------------------------------------------------------------------------
def _carve_shape(terrain: list[list[str]], shape: str, w: int, h: int,
                 rng: random.Random) -> None:
    """Modifiziert das terrain-Grid nach Shape (in-place)."""
    if shape == "circular":
        cx, cy = w / 2, h / 2
        rx, ry = (w - 2) / 2, (h - 2) / 2
        for y in range(h):
            for x in range(w):
                dx = (x - cx + 0.5) / rx
                dy = (y - cy + 0.5) / ry
                if dx * dx + dy * dy > 1.0:
                    terrain[y][x] = "wall"

    elif shape == "L-shaped":
        # Obere rechte Ecke blockieren (ca. 1/3)
        cut_x = max(2, w * 2 // 3)
        cut_y = max(2, h // 3)
        for y in range(1, cut_y):
            for x in range(cut_x, w - 1):
                terrain[y][x] = "wall"

    elif shape == "irregular":
        # Zufaellige Wandtaschen
        for _ in range(max(1, (w * h) // 25)):
            px = rng.randint(1, w - 2)
            py = rng.randint(1, h - 2)
            if terrain[py][px] == "floor":
                # Nur wenn nicht an einem Exit
                terrain[py][px] = "wall"

    elif shape == "corridor":
        # Mitte 3 Tiles breit freihalten, Rest Wall
        mid_x = w // 2
        mid_y = h // 2
        if w > h:
            # Horizontal corridor
            for y in range(h):
                for x in range(w):
                    if abs(y - mid_y) > 1 and terrain[y][x] == "floor":
                        terrain[y][x] = "wall"
        else:
            # Vertical corridor
            for y in range(h):
                for x in range(w):
                    if abs(x - mid_x) > 1 and terrain[y][x] == "floor":
                        terrain[y][x] = "wall"


def _place_exit_on_wall(terrain: list[list[str]], direction: str,
                        preferred_pos: int | None, w: int, h: int) -> tuple[int, int]:
    """Platziert einen Exit (door) auf einer Wand und gibt (x, y) zurueck."""
    if direction == "N":
        x = min(max(1, preferred_pos or w // 2), w - 2)
        terrain[0][x] = "door"
        return (x, 0)
    elif direction == "S":
        x = min(max(1, preferred_pos or w // 2), w - 2)
        terrain[h - 1][x] = "door"
        return (x, h - 1)
    elif direction == "W":
        y = min(max(1, preferred_pos or h // 2), h - 2)
        terrain[y][0] = "door"
        return (0, y)
    elif direction == "E":
        y = min(max(1, preferred_pos or h // 2), h - 2)
        terrain[y][w - 1] = "door"
        return (w - 1, y)
    # Fallback: Sued-Mitte
    terrain[h - 1][w // 2] = "door"
    return (w // 2, h - 1)


def _validate_connectivity(terrain: list[list[str]],
                           exit_positions: list[tuple[int, int]]) -> bool:
    """BFS: Prueft ob alle Exits untereinander erreichbar sind."""
    if len(exit_positions) < 2:
        return True

    h = len(terrain)
    w = len(terrain[0]) if terrain else 0
    walkable = {"floor", "door", "water"}

    start = exit_positions[0]
    visited: set[tuple[int, int]] = set()
    queue = collections.deque([start])
    visited.add(start)

    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                if terrain[ny][nx] in walkable:
                    visited.add((nx, ny))
                    queue.append((nx, ny))

    for ex, ey in exit_positions:
        if (ex, ey) not in visited:
            return False
    return True


def _fix_connectivity(terrain: list[list[str]],
                      exit_positions: list[tuple[int, int]]) -> None:
    """Fraest Korridore zwischen nicht-verbundenen Exits."""
    if len(exit_positions) < 2:
        return

    h = len(terrain)
    w = len(terrain[0]) if terrain else 0

    for i in range(len(exit_positions) - 1):
        x1, y1 = exit_positions[i]
        x2, y2 = exit_positions[i + 1]

        # Horizontaler Korridor
        sx, ex = min(x1, x2), max(x1, x2)
        mid_y = y1
        for x in range(sx, ex + 1):
            if 0 < x < w - 1 and 0 < mid_y < h - 1:
                if terrain[mid_y][x] == "wall":
                    terrain[mid_y][x] = "floor"

        # Vertikaler Korridor
        sy, ey = min(y1, y2), max(y1, y2)
        for y in range(sy, ey + 1):
            if 0 < ex < w - 1 and 0 < y < h - 1:
                if terrain[y][x2] == "wall":
                    terrain[y][x2] = "floor"


def layout_to_terrain(layout: RoomLayout) -> MapResult:
    """Konvertiert ein RoomLayout in ein MapResult mit terrain_2d."""
    w, h = layout.width, layout.height
    rng = random.Random(hash(layout.room_id) & 0x7FFFFFFF)

    # 1. Grid initialisieren: Rand = wall, Innen = floor
    terrain: list[list[str]] = []
    for y in range(h):
        row = []
        for x in range(w):
            if x == 0 or x == w - 1 or y == 0 or y == h - 1:
                row.append("wall")
            else:
                row.append("floor")
        terrain.append(row)

    # 2. Shape anwenden
    _carve_shape(terrain, layout.shape, w, h, rng)

    # 3. Exits platzieren
    directions_used: list[str] = []
    available_dirs = ["N", "S", "E", "W"]
    exit_coords: dict[str, list[int]] = {}
    all_exit_positions: list[tuple[int, int]] = []

    for i, (exit_id, exit_info) in enumerate(layout.exits.items()):
        if isinstance(exit_info, dict):
            direction = exit_info.get("direction", available_dirs[i % 4])
            preferred = exit_info.get("preferred_pos")
        else:
            direction = available_dirs[i % 4]
            preferred = None

        # Vermeiden doppelte Richtungen
        while direction in directions_used and available_dirs:
            alt = [d for d in available_dirs if d not in directions_used]
            if alt:
                direction = alt[0]
            else:
                break
        directions_used.append(direction)

        x, y = _place_exit_on_wall(terrain, direction, preferred, w, h)
        exit_coords[exit_id] = [x, y]
        all_exit_positions.append((x, y))

    # 4. Features platzieren
    decorations: list[dict] = []
    for feat in layout.features:
        fx, fy = feat.get("x", 0), feat.get("y", 0)
        ftype = feat.get("type", "obstacle")
        # Sicherstellen: innerhalb der Grenzen und auf Floor
        fx = min(max(1, fx), w - 2)
        fy = min(max(1, fy), h - 2)
        if terrain[fy][fx] == "floor":
            terrain[fy][fx] = ftype
            decorations.append({"x": fx, "y": fy, "type": ftype})

    # 5. Spawns validieren
    valid_spawns: dict[str, list[int]] = {}
    for npc_id, pos in layout.spawns.items():
        sx, sy = pos[0], pos[1]
        sx = min(max(1, sx), w - 2)
        sy = min(max(1, sy), h - 2)
        # Auf walkable Tile setzen
        if terrain[sy][sx] not in ("floor", "door"):
            # Naechstes Floor-Tile suchen
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    nx, ny = sx + dx, sy + dy
                    if 0 < nx < w - 1 and 0 < ny < h - 1 and terrain[ny][nx] == "floor":
                        sx, sy = nx, ny
                        break
                else:
                    continue
                break
        valid_spawns[npc_id] = [sx, sy]

    # 6. Konnektivitaet pruefen
    if not _validate_connectivity(terrain, all_exit_positions):
        _fix_connectivity(terrain, all_exit_positions)

    return MapResult(
        room_id=layout.room_id,
        terrain_2d=terrain,
        exits=exit_coords,
        decorations=decorations,
        spawns=valid_spawns,
        biome=layout.biome,
    )


# ---------------------------------------------------------------------------
# Heuristic Room Size (mirrors grid_engine._estimate_room_size)
# ---------------------------------------------------------------------------
_SIZE_KEYWORDS: dict[str, tuple[int, int]] = {
    "gang": (7, 15), "korridor": (7, 15), "tunnel": (7, 15),
    "corridor": (7, 15), "passage": (7, 15), "schmal": (7, 15),
    "kammer": (9, 7), "zelle": (9, 7), "nische": (9, 7),
    "klein": (9, 7), "eng": (9, 7), "small": (9, 7),
    "halle": (21, 15), "saal": (21, 15), "gross": (15, 11),
    "riesig": (21, 15), "kathedrale": (21, 15), "large": (21, 15),
    "hall": (21, 15), "cavern": (15, 11),
}


def _estimate_room_size(location: dict, npc_count: int = 0,
                        exit_count: int = 0) -> tuple[int, int]:
    """Heuristik fuer Raumgroesse basierend auf Keywords."""
    text = " ".join([
        location.get("description", ""),
        location.get("atmosphere", ""),
        location.get("name", ""),
    ]).lower()

    for kw, size in _SIZE_KEYWORDS.items():
        if kw in text:
            w, h = size
            if npc_count > 5 or exit_count > 3:
                w = max(w, 15)
                h = max(h, 11)
            return w, h

    w, h = 15, 9
    if npc_count > 5 or exit_count > 3:
        w = max(w, 15)
        h = max(h, 11)
    return w, h


def _detect_shape(location: dict) -> str:
    """Shape-Erkennung aus Text."""
    text = " ".join([
        location.get("description", ""),
        location.get("name", ""),
    ]).lower()

    if any(kw in text for kw in ("gang", "korridor", "tunnel", "corridor", "schmal")):
        return "corridor"
    if any(kw in text for kw in ("rund", "circular", "kreis", "turm")):
        return "circular"
    if any(kw in text for kw in ("unregelmaessig", "verwinkelt", "irregular")):
        return "irregular"
    return "rectangular"


def _detect_features_from_text(location: dict, w: int, h: int,
                               rng: random.Random) -> list[dict]:
    """Extrahiert Features aus Beschreibungstext via Keyword-Matching."""
    text = " ".join([
        location.get("description", ""),
        location.get("atmosphere", ""),
        location.get("keeper_notes", ""),
    ]).lower()

    features: list[dict] = []

    feature_keywords = {
        "obstacle": ["thron", "throne", "saeule", "column", "knochen", "bones",
                      "truhe", "chest", "statue", "altar", "felsen", "boulder",
                      "barrikade", "druckplatte", "lagerfeuer", "campfire",
                      "tisch", "table"],
        "water":    ["brunnen", "fountain", "wasser", "water", "teich", "pool",
                      "bach", "strom"],
    }

    for ftype, keywords in feature_keywords.items():
        for kw in keywords:
            if kw in text:
                # Zufaellige Position auf Floor
                fx = rng.randint(2, max(2, w - 3))
                fy = rng.randint(2, max(2, h - 3))
                features.append({"type": ftype, "x": fx, "y": fy, "description": kw})
                break  # Ein Feature pro Typ reicht

    return features


# ---------------------------------------------------------------------------
# Algorithmic Fallback (no AI)
# ---------------------------------------------------------------------------
def generate_layout_algorithmic(location: dict, adventure: dict | None = None,
                                biome: str | None = None) -> RoomLayout:
    """Erzeugt ein RoomLayout rein algorithmisch (ohne API-Calls)."""
    room_id = location["id"]
    name = location.get("name", room_id)
    exits_raw = location.get("exits", {})
    npcs = location.get("npcs_present", [])
    npc_count = len(npcs)
    exit_count = len(exits_raw)

    w, h = _estimate_room_size(location, npc_count, exit_count)
    shape = _detect_shape(location)
    detected_biome = biome or detect_biome(location, adventure)

    rng = random.Random(hash(room_id) & 0x7FFFFFFF)

    # Exit-Richtungen zuweisen
    directions = ["N", "S", "E", "W"]
    exits: dict[str, dict] = {}
    for i, exit_id in enumerate(exits_raw):
        d = directions[i % len(directions)]
        exits[exit_id] = {"direction": d, "type": "door", "pos": None}

    # Features aus Text
    features = _detect_features_from_text(location, w, h, rng)

    # NPC-Spawns gleichmaessig verteilen
    spawns: dict[str, list[int]] = {}
    if npcs:
        spacing = max(1, (w - 4) // max(1, npc_count))
        for i, npc_id in enumerate(npcs):
            sx = min(2 + i * spacing, w - 3)
            sy = h // 2 + rng.randint(-1, 1)
            sy = min(max(2, sy), h - 3)
            spawns[npc_id] = [sx, sy]

    return RoomLayout(
        room_id=room_id,
        name=name,
        width=w,
        height=h,
        shape=shape,
        biome=detected_biome,
        exits=exits,
        features=features,
        spawns=spawns,
        description=location.get("description", ""),
    )


# ---------------------------------------------------------------------------
# AI-based Layout Generation
# ---------------------------------------------------------------------------
def generate_layout_ai(location: dict, adventure: dict | None,
                       api_key: str, biome: str | None = None) -> RoomLayout:
    """Erzeugt ein RoomLayout via Gemini Text-Analyse."""
    room_id = location["id"]
    name = location.get("name", room_id)
    detected_biome = biome or detect_biome(location, adventure)

    result = analyze_location_text(location, api_key)

    w = min(max(7, result.get("width", 15)), 25)
    h = min(max(7, result.get("height", 9)), 25)
    shape = result.get("shape", "rectangular")
    if shape not in ("rectangular", "circular", "irregular", "L-shaped", "corridor"):
        shape = "rectangular"

    # Exits
    exits_raw = location.get("exits", {})
    exit_positions = result.get("exit_positions", {})
    exits: dict[str, dict] = {}
    directions = ["N", "S", "E", "W"]
    for i, exit_id in enumerate(exits_raw):
        if exit_id in exit_positions:
            ep = exit_positions[exit_id]
            d = ep.get("direction", directions[i % 4])
            pref = ep.get("preferred_x") or ep.get("preferred_y")
            exits[exit_id] = {"direction": d, "type": "door", "pos": pref}
        else:
            exits[exit_id] = {"direction": directions[i % 4], "type": "door", "pos": None}

    # Features
    features = []
    for tf in result.get("terrain_features", []):
        ftype = tf.get("type", "obstacle")
        if ftype not in ("obstacle", "water", "door"):
            ftype = "obstacle"
        features.append({
            "type": ftype,
            "x": tf.get("x", w // 2),
            "y": tf.get("y", h // 2),
            "description": tf.get("description", ""),
        })

    # NPC-Spawns
    npcs = location.get("npcs_present", [])
    npc_positions = result.get("npc_positions", {})
    spawns: dict[str, list[int]] = {}
    rng = random.Random(hash(room_id) & 0x7FFFFFFF)
    for i, npc_id in enumerate(npcs):
        if npc_id in npc_positions:
            pos = npc_positions[npc_id]
            spawns[npc_id] = [pos[0], pos[1]]
        else:
            spawns[npc_id] = [rng.randint(2, max(2, w - 3)),
                              rng.randint(2, max(2, h - 3))]

    return RoomLayout(
        room_id=room_id,
        name=name,
        width=w,
        height=h,
        shape=shape,
        biome=detected_biome,
        exits=exits,
        features=features,
        spawns=spawns,
        description=location.get("description", ""),
    )


# ---------------------------------------------------------------------------
# Image-based Layout Generation
# ---------------------------------------------------------------------------
def generate_layout_from_image(image_path: str, api_key: str,
                               location: dict | None = None,
                               adventure: dict | None = None,
                               biome: str | None = None) -> list[RoomLayout]:
    """Erzeugt RoomLayouts aus einem Kartenbild via Gemini Vision."""
    analysis = analyze_map_image(image_path, api_key)
    rooms = analysis.get("rooms", [])
    setting = analysis.get("setting", "dungeon")
    connections = analysis.get("connections", [])

    layouts: list[RoomLayout] = []
    for room in rooms:
        rid = room.get("id", f"room_{len(layouts)}")
        rng = random.Random(hash(rid) & 0x7FFFFFFF)

        # Exits aus Connections
        exits: dict[str, dict] = {}
        directions = ["N", "S", "E", "W"]
        dir_idx = 0
        for conn in connections:
            if conn.get("from") == rid:
                target = conn["to"]
                exits[target] = {
                    "direction": directions[dir_idx % 4],
                    "type": conn.get("type", "door"),
                    "pos": None,
                }
                dir_idx += 1
            elif conn.get("to") == rid:
                source = conn["from"]
                exits[source] = {
                    "direction": directions[dir_idx % 4],
                    "type": conn.get("type", "door"),
                    "pos": None,
                }
                dir_idx += 1

        features = []
        for f in room.get("features", []):
            features.append({
                "type": f.get("type", "obstacle"),
                "x": f.get("x", 3),
                "y": f.get("y", 3),
                "description": f.get("description", ""),
            })

        detected_biome = biome or setting
        if detected_biome not in _BIOME_KEYWORDS:
            detected_biome = "dungeon"

        w = min(max(7, room.get("width", 15)), 25)
        h = min(max(7, room.get("height", 9)), 25)
        shape = room.get("shape", "rectangular")

        layouts.append(RoomLayout(
            room_id=rid,
            name=room.get("name", rid),
            width=w,
            height=h,
            shape=shape,
            biome=detected_biome,
            exits=exits,
            features=features,
            spawns={},
            description=room.get("description", ""),
        ))

    return layouts


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_map(result: MapResult, scale: int = 2) -> Any:
    """Rendert eine MapResult als PIL Image via pixel_renderer."""
    try:
        from gui.pixel_renderer import render_terrain_image, PixelTileset
    except ImportError:
        logger.warning("pixel_renderer nicht verfuegbar -- Rendering uebersprungen")
        return None

    tileset = PixelTileset()
    tileset.load()

    img = render_terrain_image(result.terrain_2d, tileset, result.room_id)
    if img is None:
        return None

    if scale > 1:
        from PIL import Image
        new_size = (img.width * scale, img.height * scale)
        img = img.resize(new_size, Image.NEAREST)

    result.rendered_image = img
    return img


# ---------------------------------------------------------------------------
# Quality Evaluation (Gemini Vision)
# ---------------------------------------------------------------------------
_EVAL_PROMPT = """\
Bewerte diese generierte Spielekarte (Pixel-Art Dungeon Map).
Die Karte soll folgende Beschreibung darstellen:
{description}

Bewerte nach diesen Kriterien (je 0.0 bis 1.0):
- connectivity: Sind alle Ausgaenge erreichbar? (Gewicht: 0.3)
- proportions: Stimmen die Proportionen? (Gewicht: 0.25)
- features: Sind die beschriebenen Merkmale vorhanden? (Gewicht: 0.25)
- aesthetics: Ist die Karte visuell ansprechend? (Gewicht: 0.2)

Antworte NUR mit JSON:
{{
  "connectivity": 0.9,
  "proportions": 0.8,
  "features": 0.7,
  "aesthetics": 0.8,
  "overall": 0.81,
  "suggestions": ["Vorschlag 1", "Vorschlag 2"]
}}
"""


def evaluate_map_quality(result: MapResult, description: str,
                         api_key: str) -> dict:
    """Bewertet die Qualitaet einer generierten Karte via Gemini Vision."""
    img = result.rendered_image
    if img is None:
        return {"overall": 0.5, "suggestions": ["Kein Bild zum Bewerten"]}

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    prompt = _EVAL_PROMPT.format(description=description)
    text = _gemini_call(api_key, prompt, image_bytes=png_bytes)

    try:
        scores = _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        logger.warning("Qualitaets-Bewertung konnte nicht geparst werden")
        return {"overall": 0.5, "suggestions": []}

    overall = float(scores.get("overall", 0.5))
    suggestions = scores.get("suggestions", [])

    logger.info("Qualitaet: %.2f (conn=%.1f, prop=%.1f, feat=%.1f, aes=%.1f)",
                overall,
                scores.get("connectivity", 0),
                scores.get("proportions", 0),
                scores.get("features", 0),
                scores.get("aesthetics", 0))

    return {
        "connectivity": scores.get("connectivity", 0.5),
        "proportions": scores.get("proportions", 0.5),
        "features": scores.get("features", 0.5),
        "aesthetics": scores.get("aesthetics", 0.5),
        "overall": overall,
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# Suggestion Application
# ---------------------------------------------------------------------------
def apply_suggestions(layout: RoomLayout, result: MapResult,
                      suggestions: list[str]) -> MapResult:
    """Wendet Verbesserungsvorschlaege algorithmisch an."""
    text = " ".join(s.lower() for s in suggestions)
    modified = False

    if any(kw in text for kw in ("zu klein", "too small", "groesser", "larger")):
        layout.width = min(25, layout.width + 4)
        layout.height = min(25, layout.height + 4)
        modified = True

    if any(kw in text for kw in ("blockiert", "blocked", "nicht erreichbar",
                                  "unreachable", "connectivity")):
        _fix_connectivity(result.terrain_2d,
                          [(pos[0], pos[1]) for pos in result.exits.values()])
        modified = True

    if any(kw in text for kw in ("wasser", "water", "fehlt wasser",
                                  "missing water")):
        rng = random.Random(42)
        w = len(result.terrain_2d[0]) if result.terrain_2d else 0
        h = len(result.terrain_2d)
        if w > 4 and h > 4:
            wx = rng.randint(2, w - 3)
            wy = rng.randint(2, h - 3)
            if result.terrain_2d[wy][wx] == "floor":
                result.terrain_2d[wy][wx] = "water"
                result.decorations.append({"x": wx, "y": wy, "type": "water"})
        modified = True

    if any(kw in text for kw in ("zu leer", "too empty", "mehr details",
                                  "more detail", "leer")):
        rng = random.Random(hash(result.room_id) & 0x7FFFFFFF)
        w = len(result.terrain_2d[0]) if result.terrain_2d else 0
        h = len(result.terrain_2d)
        placed = 0
        for _ in range(10):
            ox = rng.randint(2, max(2, w - 3))
            oy = rng.randint(2, max(2, h - 3))
            if h > oy and w > ox and result.terrain_2d[oy][ox] == "floor":
                result.terrain_2d[oy][ox] = "obstacle"
                result.decorations.append({"x": ox, "y": oy, "type": "obstacle"})
                placed += 1
                if placed >= 3:
                    break
        modified = True

    if modified and any(kw in text for kw in ("zu klein", "groesser", "larger")):
        # Muss komplett neu generiert werden
        return layout_to_terrain(layout)

    return result


# ---------------------------------------------------------------------------
# Sprite Helpers
# ---------------------------------------------------------------------------
def ensure_biome_tiles(biome: str) -> bool:
    """Prueft ob Biome-Tiles existieren; generiert sie sonst."""
    floor_file = os.path.join(GENERATED_TILES_DIR, f"env_{biome}_floor.png")
    if os.path.exists(floor_file):
        logger.debug("Biome-Tiles fuer '%s' existieren bereits", biome)
        return True

    try:
        from pixel_art_creator import generate_environments
    except ImportError:
        logger.warning("pixel_art_creator nicht verfuegbar -- Biome-Tiles fehlen")
        return False

    logger.info("Generiere Biome-Tiles fuer '%s'...", biome)
    os.makedirs(GENERATED_TILES_DIR, exist_ok=True)

    rng = random.Random(42)
    results = generate_environments(rng, count=15, biome_filter=biome)

    for filename, img in results:
        path = os.path.join(GENERATED_TILES_DIR, filename)
        img.save(path)
        logger.debug("Gespeichert: %s", filename)

    print(f"  Biome-Tiles: {len(results)} Tiles fuer '{biome}' generiert")
    return True


def ensure_location_sprites(location: dict, adventure: dict) -> dict:
    """Stellt sicher dass NPC-Sprites existieren."""
    try:
        from sprite_extractor import SpriteExtractor
    except ImportError:
        logger.warning("sprite_extractor nicht verfuegbar")
        return {}

    extractor = SpriteExtractor()
    return extractor.extract_and_ensure(adventure)


# ---------------------------------------------------------------------------
# Adventure Injection
# ---------------------------------------------------------------------------
def inject_maps_into_adventure(adventure_path: str, maps: dict[str, MapResult],
                               output_path: str | None = None) -> str:
    """Schreibt map-Felder in Adventure-JSON. Original bleibt unveraendert."""
    with open(adventure_path, "r", encoding="utf-8") as f:
        adventure = json.load(f)

    for loc in adventure.get("locations", []):
        lid = loc["id"]
        if lid in maps:
            mr = maps[lid]
            loc["map"] = {
                "terrain": mr.terrain_2d,
                "exits": mr.exits,
                "decorations": mr.decorations,
                "spawns": mr.spawns,
            }

    if output_path is None:
        stem = Path(adventure_path).stem
        output_path = os.path.join(
            os.path.dirname(adventure_path),
            f"{stem}_mapped.json",
        )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(adventure, f, indent=2, ensure_ascii=False)

    logger.info("Adventure mit Maps gespeichert: %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Main Orchestration
# ---------------------------------------------------------------------------
def generate_map_for_location(
    location: dict,
    adventure: dict | None = None,
    source_image: str | None = None,
    api_key: str | None = None,
    max_iter: int = 3,
    threshold: float = 0.7,
    biome: str | None = None,
    no_ai: bool = False,
) -> MapResult:
    """Erzeugt eine Karte fuer eine einzelne Location."""
    room_id = location["id"]
    name = location.get("name", room_id)
    print(f"\n--- Generiere Karte: {name} ({room_id}) ---")

    # Biome
    detected_biome = biome or detect_biome(location, adventure)
    print(f"  Biome: {detected_biome}")

    # Biome-Tiles sicherstellen
    ensure_biome_tiles(detected_biome)

    # Layout erzeugen
    if source_image and api_key and not no_ai:
        layouts = generate_layout_from_image(source_image, api_key,
                                             location, adventure, detected_biome)
        if layouts:
            layout = layouts[0]
        else:
            layout = generate_layout_algorithmic(location, adventure, detected_biome)
    elif api_key and not no_ai:
        try:
            layout = generate_layout_ai(location, adventure, api_key, detected_biome)
        except Exception as e:
            logger.warning("AI-Layout fehlgeschlagen: %s -- Fallback", e)
            print(f"  [!!] AI-Analyse fehlgeschlagen: {e}")
            layout = generate_layout_algorithmic(location, adventure, detected_biome)
    else:
        layout = generate_layout_algorithmic(location, adventure, detected_biome)

    print(f"  Grid: {layout.width}x{layout.height}, Shape: {layout.shape}")

    # Grid konvertieren
    result = layout_to_terrain(layout)

    # Rendern
    img = render_map(result)
    if img:
        print(f"  Rendering: {img.width}x{img.height} px")
    else:
        print("  Rendering: [!!] Kein Bild erzeugt")

    # Qualitaets-Loop (nur mit AI)
    if api_key and not no_ai and img:
        for iteration in range(max_iter):
            result.iteration = iteration + 1
            eval_result = evaluate_map_quality(
                result, location.get("description", ""), api_key,
            )
            result.quality_score = eval_result.get("overall", 0.5)
            suggestions = eval_result.get("suggestions", [])

            print(f"  Iteration {iteration + 1}: Score={result.quality_score:.2f}")

            if result.quality_score >= threshold:
                print(f"  [OK] Qualitaet ausreichend (>= {threshold})")
                break

            if suggestions:
                print(f"  Vorschlaege: {', '.join(suggestions[:3])}")
                result = apply_suggestions(layout, result, suggestions)
                img = render_map(result)
        else:
            print(f"  Max Iterationen ({max_iter}) erreicht")
    else:
        result.quality_score = 0.5  # Kein Score ohne AI

    return result


def generate_maps_for_adventure(
    adventure_path: str,
    source_images: dict[str, str] | None = None,
    api_key: str | None = None,
    max_iter: int = 3,
    threshold: float = 0.7,
    biome: str | None = None,
    no_ai: bool = False,
) -> dict[str, MapResult]:
    """Erzeugt Karten fuer alle Locations eines Abenteuers."""
    with open(adventure_path, "r", encoding="utf-8") as f:
        adventure = json.load(f)

    print(f"=== Map Generator: {adventure.get('title', '?')} ===")
    print(f"Locations: {len(adventure.get('locations', []))}")

    # NPC-Sprites sicherstellen
    if not no_ai:
        try:
            ensure_location_sprites({}, adventure)
        except Exception as e:
            logger.warning("Sprite-Sicherstellung fehlgeschlagen: %s", e)

    maps: dict[str, MapResult] = {}
    source_images = source_images or {}

    for loc in adventure.get("locations", []):
        lid = loc["id"]
        img_path = source_images.get(lid)
        result = generate_map_for_location(
            loc, adventure, img_path, api_key,
            max_iter, threshold, biome, no_ai,
        )
        maps[lid] = result

    print(f"\n=== Fertig: {len(maps)} Karten generiert ===")
    return maps


# ---------------------------------------------------------------------------
# Preview Saving
# ---------------------------------------------------------------------------
def save_previews(maps: dict[str, MapResult], output_dir: str | None = None) -> list[str]:
    """Speichert Preview-Bilder fuer alle generierten Karten."""
    out = output_dir or GENERATED_MAPS_DIR
    os.makedirs(out, exist_ok=True)

    saved: list[str] = []
    for room_id, result in maps.items():
        if result.rendered_image is None:
            continue

        filename = f"map_{room_id}.png"
        filepath = os.path.join(out, filename)
        result.rendered_image.save(filepath)
        saved.append(filepath)
        print(f"  Preview: {filepath}")

    # Map-JSONs speichern (ohne Bild)
    for room_id, result in maps.items():
        json_path = os.path.join(out, f"map_{room_id}.json")
        data = {
            "room_id": result.room_id,
            "terrain": result.terrain_2d,
            "exits": result.exits,
            "decorations": result.decorations,
            "spawns": result.spawns,
            "biome": result.biome,
            "quality_score": result.quality_score,
            "iteration": result.iteration,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    return saved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _find_adventure(name: str) -> str | None:
    """Sucht Adventure-JSON in modules/adventures/."""
    candidates = [
        os.path.join(ADVENTURES_DIR, f"{name}.json"),
        os.path.join(ADVENTURES_DIR, name),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Map Generator -- Automatische Spielekarten-Erzeugung",
    )
    parser.add_argument("--adventure", type=str,
                        help="Adventure-Name (z.B. goblin_cave)")
    parser.add_argument("--location", type=str,
                        help="Einzelne Location-ID")
    parser.add_argument("--image", type=str,
                        help="Quell-Kartenbild (PNG/JPG)")
    parser.add_argument("--text", type=str,
                        help="Raum-Beschreibung als Text")
    parser.add_argument("--output", type=str,
                        help="Output-Verzeichnis fuer Previews")
    parser.add_argument("--inject", action="store_true",
                        help="Maps in Adventure-JSON injizieren")
    parser.add_argument("--biome", type=str,
                        help="Biome erzwingen (cave, dungeon, crypt, ...)")
    parser.add_argument("--max-iter", type=int, default=3,
                        help="Max Verfeinerungs-Iterationen (Default: 3)")
    parser.add_argument("--quality", type=float, default=0.7,
                        help="Qualitaets-Schwellwert 0.0-1.0 (Default: 0.7)")
    parser.add_argument("--preview", action="store_true",
                        help="Preview-Bilder speichern")
    parser.add_argument("--no-ai", action="store_true",
                        help="Algorithmischer Fallback ohne API")
    parser.add_argument("--debug", action="store_true",
                        help="Debug-Logging aktivieren")
    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # API Key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and not args.no_ai:
        print("[!!] GEMINI_API_KEY nicht gesetzt -- verwende --no-ai Modus")
        args.no_ai = True

    # Adventure-Modus
    if args.adventure:
        adv_path = _find_adventure(args.adventure)
        if not adv_path:
            print(f"[!!] Adventure nicht gefunden: {args.adventure}")
            sys.exit(1)

        print(f"Adventure: {adv_path}")

        source_images: dict[str, str] = {}
        if args.image and args.location:
            source_images[args.location] = args.image

        maps = generate_maps_for_adventure(
            adv_path, source_images, api_key,
            max_iter=args.max_iter,
            threshold=args.quality,
            biome=args.biome,
            no_ai=args.no_ai,
        )

        if args.preview or args.inject:
            saved = save_previews(maps, args.output)
            print(f"\n{len(saved)} Preview-Bilder gespeichert")

        if args.inject:
            out_path = inject_maps_into_adventure(adv_path, maps)
            print(f"Adventure mit Maps: {out_path}")

        # Zusammenfassung
        print("\n--- Zusammenfassung ---")
        for rid, mr in maps.items():
            h = len(mr.terrain_2d)
            w = len(mr.terrain_2d[0]) if mr.terrain_2d else 0
            print(f"  {rid}: {w}x{h} ({mr.biome}) "
                  f"Score={mr.quality_score:.2f} Iter={mr.iteration}")

    # Einzelne Location
    elif args.location:
        if args.text:
            location = {
                "id": args.location,
                "name": args.location.replace("_", " ").title(),
                "description": args.text,
                "atmosphere": "",
                "exits": {},
                "npcs_present": [],
            }
        elif args.adventure:
            adv_path = _find_adventure(args.adventure)
            if not adv_path:
                print(f"[!!] Adventure nicht gefunden: {args.adventure}")
                sys.exit(1)
            with open(adv_path, "r", encoding="utf-8") as f:
                adventure = json.load(f)
            location = None
            for loc in adventure.get("locations", []):
                if loc["id"] == args.location:
                    location = loc
                    break
            if not location:
                print(f"[!!] Location nicht gefunden: {args.location}")
                sys.exit(1)
        else:
            print("[!!] --text oder --adventure benoetigt fuer --location")
            sys.exit(1)

        result = generate_map_for_location(
            location, None, args.image, api_key,
            args.max_iter, args.quality, args.biome, args.no_ai,
        )

        if args.preview:
            save_previews({result.room_id: result}, args.output)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
