"""
gui/pixel_renderer.py — Gemeinsamer Pixel-Art Renderer

Wiederverwendbare Render-Logik fuer Dungeon-Visualisierung mit 0x72 Tileset:
  - PixelTileset: Laedt und cached alle Tileset-Assets
  - Autotiler: 4-Bit Cardinal Bitmask fuer Floor-zu-Wall-Edge-Auswahl
  - render_terrain_image(): Terrain-2D-Array → PIL Image
  - render_room_to_image(): Kompletter Raum (Terrain + Entities + Trails)

Verwendet von:
  - gui/tab_dungeon_pixel.py (Live-Dungeon)
  - gui/tab_replay_viewer.py (Replay-Modus)
"""

from __future__ import annotations

import logging
import os
import random
from typing import Any

logger = logging.getLogger("ARS.gui.pixel_renderer")

# ── PIL Verfuegbarkeit ───────────────────────────────────────────────────────

try:
    from PIL import Image, ImageDraw, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ── Pfade & Konstanten ───────────────────────────────────────────────────────

ASSET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "tilesets", "0x72_dungeon_v5",
)

TILE = 16
SCALE = 2
FOG_NEAR = 8
FOG_FAR = 12


# ── Asset-Loader ─────────────────────────────────────────────────────────────

def load_asset(
    name: str,
    asset_dir: str = ASSET_DIR,
    fallback_size: tuple[int, int] = (TILE, TILE),
) -> "Image.Image":
    """Laedt ein PNG-Asset. Fallback: Magenta-Quadrat."""
    path = os.path.join(asset_dir, name)
    if os.path.exists(path):
        return Image.open(path).convert("RGBA")
    return Image.new("RGBA", fallback_size, (255, 0, 255, 255))


def tint(img: "Image.Image", color: tuple[int, int, int],
         strength: float = 0.55) -> "Image.Image":
    """Faerbt nicht-transparente Pixel Richtung color ein."""
    result = img.copy().convert("RGBA")
    r, g, b = color
    px = result.load()
    w, h = result.size
    for y in range(h):
        for x in range(w):
            pr, pg, pb, pa = px[x, y]
            if pa > 30:
                px[x, y] = (
                    int(pr * (1 - strength) + r * strength),
                    int(pg * (1 - strength) + g * strength),
                    int(pb * (1 - strength) + b * strength),
                    pa,
                )
    return result


# ── Auto-Tiler ──────────────────────────────────────────────────────────────

class Autotiler:
    """4-Bit Cardinal Bitmask fuer Floor-zu-Wall-Edge-Auswahl."""

    # N=8, S=4, E=2, W=1
    EDGE_MAP: dict[int, str | None] = {
        0: None, 1: "Edge_w", 2: "Edge_e", 3: "Edge_we",
        4: "Edge_s", 5: "Edge_sw", 6: "Edge_se", 7: "Edge_swe",
        8: "Edge_n", 9: "Edge_nw", 10: "Edge_ne", 11: "Edge_nwe",
        12: "Edge_ns", 13: "Edge_nsw", 14: "Edge_nse", 15: "Edge_single",
    }

    def __init__(self, wall_grid: list[list[int]], edge_assets: dict) -> None:
        self.grid = wall_grid
        self.h = len(wall_grid)
        self.w = len(wall_grid[0]) if wall_grid else 0
        self.edges = edge_assets

    def is_wall(self, x: int, y: int) -> bool:
        if x < 0 or x >= self.w or y < 0 or y >= self.h:
            return True
        return self.grid[y][x] == 1

    def get_edge_mask(self, x: int, y: int) -> int:
        mask = 0
        if self.is_wall(x, y - 1): mask |= 8
        if self.is_wall(x, y + 1): mask |= 4
        if self.is_wall(x + 1, y): mask |= 2
        if self.is_wall(x - 1, y): mask |= 1
        return mask

    def get_wall_asset_name(self, x: int, y: int) -> str:
        has_floor_below = not self.is_wall(x, y + 1)
        if has_floor_below:
            has_floor_left = not self.is_wall(x - 1, y)
            has_floor_right = not self.is_wall(x + 1, y)
            if has_floor_left and not has_floor_right:
                return "Wall_front_left"
            if has_floor_right and not has_floor_left:
                return "Wall_front_right"
            return "Wall_front"
        return "black"


# ── Entity-zu-Asset-Mapping ─────────────────────────────────────────────────

CLASS_MAP: dict[str, tuple[str, tuple[int, int, int]]] = {
    "F": ("fighter",  (60,  120, 210)),   # Kaempfer → Blau
    "M": ("mage",     (170,  60, 220)),   # Magier → Lila
    "C": ("cleric",   (220, 220, 220)),   # Kleriker → Weiss
    "T": ("thief",    (210,  60,  60)),   # Dieb → Rot
    "R": ("ranger",   (60,  180,  80)),   # Waldlaeufer → Gruen
    "P": ("paladin",  (210, 175,  50)),   # Paladin → Gold
    "B": ("bard",     (210, 130,  50)),   # Barde → Orange
    "D": ("druid",    (80,  160, 120)),   # Druide → Tuerkis
}

MONSTER_MAP: dict[str, str] = {
    "goblin":    "monster_goblin.png",
    "ork":       "monster_orc.png",
    "orc":       "monster_orc.png",
    "skelett":   "monster_skelet.png",
    "skeleton":  "monster_skelet.png",
    "zombie":    "monster_zombie.png",
    "imp":       "monster_imp.png",
    "fledermaus": "monster_bat.png",
    "bat":       "monster_bat.png",
    "nekromant": "monster_necromancer.png",
    "necro":     "monster_necromancer.png",
    "wogol":     "monster_wogol.png",
    "chort":     "monster_chort.png",
    "daemon":    "monster_demon.png",
    "demon":     "monster_demon.png",
    "oger":      "monster_ogre.png",
    "ogre":      "monster_ogre.png",
    "elementar": "monster_elemental_fire.png",
    "feuer":     "monster_elemental_fire.png",
    "wasser":    "monster_elemental_water.png",
    "erde":      "monster_elemental_earth.png",
    "luft":      "monster_elemental_air.png",
    "ritter":    "monster_dark_knight.png",
    "knight":    "monster_dark_knight.png",
    "tentakel":  "monster_tentackle.png",
    "spinne":    "monster_imp.png",
    "spider":    "monster_imp.png",
    "troll":     "monster_ogre.png",
    "drache":    "monster_chort.png",
    "dragon":    "monster_chort.png",
    "lich":      "monster_necromancer.png",
    "golem":     "monster_ogre.png",
    "wight":     "monster_skelet.png",
    "ghul":      "monster_zombie.png",
    "ghoul":     "monster_zombie.png",
    "harpyie":   "monster_bat.png",
    "harpy":     "monster_bat.png",
    "mimik":     "monster_wogol.png",
    "mimic":     "monster_wogol.png",
}


# ── PixelTileset ─────────────────────────────────────────────────────────────

class PixelTileset:
    """Laedt und cached alle 0x72-Tileset-Assets."""

    def __init__(self, asset_dir: str = ASSET_DIR) -> None:
        self.asset_dir = asset_dir
        self.hero_imgs: dict[str, "Image.Image"] = {}
        self.monster_imgs: dict[str, "Image.Image"] = {}
        self.edge_tiles: dict[str, "Image.Image"] = {}
        self.floor_plain: "Image.Image | None" = None
        self.floor_stains: list["Image.Image"] = []
        self.floor_light: "Image.Image | None" = None
        self.wall_front: "Image.Image | None" = None
        self.wall_front_left: "Image.Image | None" = None
        self.wall_front_right: "Image.Image | None" = None
        self.wall_black: "Image.Image | None" = None
        self.door_img: "Image.Image | None" = None
        self.column_img: "Image.Image | None" = None
        self.chest_img: "Image.Image | None" = None
        self.skull_img: "Image.Image | None" = None
        self.torch_imgs: list["Image.Image"] = []
        self.default_monster: "Image.Image | None" = None
        self.npc_img: "Image.Image | None" = None
        self._loaded = False

    def load(self) -> None:
        """Laedt alle Pixel-Art-Assets einmalig."""
        if self._loaded:
            return
        self._loaded = True

        A = lambda name, fs=(TILE, TILE): load_asset(name, self.asset_dir, fs)

        # Floor
        self.floor_plain = A("floor_plain.png")
        self.floor_stains = [
            A("floor_stain_1.png"), A("floor_stain_2.png"), A("floor_stain_3.png"),
        ]
        self.floor_light = A("floor_light.png")

        # Walls
        self.wall_front = A("Wall_front.png")
        self.wall_front_left = A("Wall_front_left.png")
        self.wall_front_right = A("Wall_front_right.png")
        self.wall_black = A("black.png")

        # Edges
        for name in Autotiler.EDGE_MAP.values():
            if name and name not in self.edge_tiles:
                self.edge_tiles[name] = A(f"{name}.png")

        # Doors, deko
        self.door_img = A("door_open.png")
        self.column_img = A("column.png", (TILE, 32))
        self.chest_img = A("chest_closed.png")
        self.skull_img = A("skull.png")
        self.torch_imgs = [A(f"torch_{i}.png") for i in range(1, 9)]

        # Heroes
        hero_base = A("hero_basic.png")
        for sym, (key, color) in CLASS_MAP.items():
            self.hero_imgs[sym] = tint(hero_base, color)
        self.hero_imgs["?"] = hero_base

        # Monsters
        for key, filename in MONSTER_MAP.items():
            if key not in self.monster_imgs:
                self.monster_imgs[key] = A(filename)
        self.default_monster = A("monster_imp.png")

        # NPC
        self.npc_img = A("npc_merchant.png")

        logger.info("PixelTileset geladen (%d Heroes, %d Monster)",
                     len(self.hero_imgs), len(self.monster_imgs))

    def get_entity_sprite(
        self, entity_type: str, name: str, symbol: str = "?",
    ) -> "Image.Image":
        """Mappt Entity-Typ/Name auf ein Pixel-Art-Sprite."""
        if entity_type == "party_member":
            s = symbol if symbol in self.hero_imgs else "?"
            return self.hero_imgs.get(s, self.hero_imgs["?"])

        if entity_type == "monster":
            name_lower = name.lower()
            for keyword, img in self.monster_imgs.items():
                if keyword in name_lower:
                    return img
            return self.default_monster

        return self.npc_img

    def get_wall_tile(self, wname: str) -> "Image.Image":
        """Gibt das passende Wall-Tile zurueck."""
        if wname == "Wall_front":
            return self.wall_front
        if wname == "Wall_front_left":
            return self.wall_front_left
        if wname == "Wall_front_right":
            return self.wall_front_right
        return self.wall_black


# ── Render-Funktionen ────────────────────────────────────────────────────────

def render_terrain_image(
    terrain_2d: list[list[str]],
    tileset: PixelTileset,
    room_id: str = "",
) -> "Image.Image":
    """Rendert Terrain-2D-Array als PIL Image (statischer Layer, Source-Aufloesung).

    Args:
        terrain_2d: [y][x] = "wall"|"floor"|"door"|"obstacle"|"water"
        tileset: Geladenes PixelTileset
        room_id: Fuer deterministische Floor-Variation

    Returns:
        PIL Image in Source-Aufloesung (TILE pro Zelle)
    """
    if not HAS_PIL:
        return None

    h = len(terrain_2d)
    w = len(terrain_2d[0]) if terrain_2d else 0
    if w == 0 or h == 0:
        return None

    # Wall-Grid fuer Autotiler
    wall_grid: list[list[int]] = []
    for y in range(h):
        row = []
        for x in range(w):
            t = terrain_2d[y][x] if x < len(terrain_2d[y]) else "wall"
            row.append(1 if t == "wall" else 0)
        wall_grid.append(row)

    autotiler = Autotiler(wall_grid, tileset.edge_tiles)

    # Floor-Variety
    rng = random.Random(hash(room_id) if room_id else 42)
    floor_map: dict[tuple[int, int], "Image.Image"] = {}
    for y in range(h):
        for x in range(w):
            if wall_grid[y][x] == 0:
                r = rng.random()
                if r < 0.06:
                    floor_map[(x, y)] = rng.choice(tileset.floor_stains)
                elif r < 0.10:
                    floor_map[(x, y)] = tileset.floor_light
                else:
                    floor_map[(x, y)] = tileset.floor_plain

    # Render
    img = Image.new("RGBA", (w * TILE, h * TILE), (5, 3, 8, 255))

    for y in range(h):
        for x in range(w):
            px, py = x * TILE, y * TILE
            t = terrain_2d[y][x] if x < len(terrain_2d[y]) else "wall"

            if t == "wall":
                wname = autotiler.get_wall_asset_name(x, y)
                wt = tileset.get_wall_tile(wname)
                img.paste(wt, (px, py), wt)
            else:
                tile = floor_map.get((x, y), tileset.floor_plain)
                img.paste(tile, (px, py), tile)

                mask = autotiler.get_edge_mask(x, y)
                ename = Autotiler.EDGE_MAP.get(mask)
                if ename and ename in tileset.edge_tiles:
                    etile = tileset.edge_tiles[ename]
                    img.paste(etile, (px, py), etile)

                if t == "door" and tileset.door_img:
                    img.paste(tileset.door_img, (px, py), tileset.door_img)
                elif t == "obstacle" and tileset.column_img:
                    col_h = tileset.column_img.height
                    img.paste(
                        tileset.column_img,
                        (px, py - (col_h - TILE)),
                        tileset.column_img,
                    )

    # Skulls in Sackgassen
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if wall_grid[y][x] != 0:
                continue
            nbrs = sum(
                1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= x + dx < w and 0 <= y + dy < h
                and wall_grid[y + dy][x + dx] == 0
            )
            if nbrs == 1 and tileset.skull_img:
                img.paste(
                    tileset.skull_img,
                    (x * TILE, y * TILE),
                    tileset.skull_img,
                )

    return img


def render_room_to_image(
    terrain_2d: list[list[str]],
    tileset: PixelTileset,
    room_id: str = "",
    entities: list[dict] | None = None,
    party_color_map: dict[str, int] | None = None,
    move_trails: list[dict] | None = None,
    scale: int = SCALE,
) -> "Image.Image | None":
    """Rendert einen kompletten Raum als PIL Image.

    Args:
        terrain_2d: [y][x] = terrain type string
        tileset: Geladenes PixelTileset
        room_id: Fuer deterministische Floor-Variation
        entities: Liste von dicts mit x, y, type, name, symbol, alive
        party_color_map: entity_id → Farb-Index (fuer Party-Member)
        move_trails: Liste von move_event dicts (entity_id, from, to, type)
        scale: Skalierungsfaktor (default 2)

    Returns:
        PIL Image in Display-Aufloesung (TILE*scale pro Zelle)
    """
    if not HAS_PIL:
        return None

    # Statischer Layer
    static = render_terrain_image(terrain_2d, tileset, room_id)
    if static is None:
        return None

    src = static.copy()

    # Entities zeichnen
    if entities:
        # Nach Y sortieren (Painter's Algorithm)
        sorted_ents = sorted(entities, key=lambda e: e.get("y", 0))
        for ent in sorted_ents:
            alive = ent.get("alive", True)
            if not alive:
                continue
            ex = int(ent.get("x", 0))
            ey = int(ent.get("y", 0))
            h = len(terrain_2d)
            w = len(terrain_2d[0]) if terrain_2d else 0
            if not (0 <= ex < w and 0 <= ey < h):
                continue

            sprite = tileset.get_entity_sprite(
                ent.get("type", ""),
                ent.get("name", ""),
                ent.get("symbol", "?"),
            )
            px, py = ex * TILE, ey * TILE
            src.paste(sprite, (px, py), sprite)

    # Move-Trails zeichnen
    if move_trails:
        d = ImageDraw.Draw(src)
        TRAIL_COLORS = {
            "party_member": (80, 220, 80, 180),    # Gruen
            "monster":      (220, 60, 60, 180),     # Rot
            "combat":       (220, 220, 60, 180),    # Gelb
        }
        for trail in move_trails:
            trail_type = trail.get("move_type", trail.get("type", "party_member"))
            color = TRAIL_COLORS.get(trail_type, TRAIL_COLORS["party_member"])
            path = trail.get("path", [])
            fx = trail.get("from")
            tx = trail.get("to")

            if path and len(path) >= 2:
                points = [(p[0] * TILE + TILE // 2, p[1] * TILE + TILE // 2)
                          for p in path]
                for i in range(len(points) - 1):
                    d.line([points[i], points[i + 1]], fill=color[:3], width=2)
                # Start-/End-Punkte
                d.ellipse(
                    [points[0][0] - 2, points[0][1] - 2,
                     points[0][0] + 2, points[0][1] + 2],
                    fill=color[:3],
                )
                d.ellipse(
                    [points[-1][0] - 3, points[-1][1] - 3,
                     points[-1][0] + 3, points[-1][1] + 3],
                    fill=color[:3],
                )
            elif fx and tx:
                x1 = int(fx[0]) * TILE + TILE // 2
                y1 = int(fx[1]) * TILE + TILE // 2
                x2 = int(tx[0]) * TILE + TILE // 2
                y2 = int(tx[1]) * TILE + TILE // 2
                d.line([(x1, y1), (x2, y2)], fill=color[:3], width=2)
                d.ellipse([x2 - 3, y2 - 3, x2 + 3, y2 + 3], fill=color[:3])

    # Scale Up (NEAREST fuer Pixel-Art)
    if scale > 1:
        dw = src.width * scale
        dh = src.height * scale
        src = src.resize((dw, dh), Image.NEAREST)

    return src
