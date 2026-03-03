"""
TinyCrawl — AD&D Cave Dungeon Crawler  (Level 1)
Standalone auto-battler using 0x72 Dungeon Tileset v5 pixel art assets.
Cave map generated via cellular automaton (80×60 tiles), scrollable viewport,
fog of war, minimap, scanline CRT effect, animated torches, zone-based spawning.
tkinter + PIL + winsound.  Run: py -3 tinycrawl_demo.py
"""

import tkinter as tk
import random
import math
import os
import struct
import io
import wave
import threading
from dataclasses import dataclass, field
from collections import deque
from typing import Optional, List, Tuple, Dict
from PIL import Image, ImageDraw, ImageTk

try:
    import winsound
    HAS_SOUND = True
except ImportError:
    HAS_SOUND = False

# ── Paths ───────────────────────────────────────────────────────────────────────
ASSET_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "tilesets",
    "0x72_dungeon_v5",
)

# ── Constants ───────────────────────────────────────────────────────────────────
TILE       = 16
SCALE      = 1
WORLD_W    = 80
WORLD_H    = 60
FPS        = 8              # choppy retro feel
MOVE_TICKS = 2
ANIM_TICKS = 4
WAVE_PAUSE = 20
HUD_H      = 56             # pixels at screen resolution
FOG_NEAR   = 8              # tiles — 50 % dark beyond this
FOG_FAR    = 12             # tiles — 90 % dark beyond this
MINIMAP_W  = 80
MINIMAP_H  = 60
SCANLINE_ALPHA = 55         # darkness per scanline row (0-255)
MAX_BFS_RANGE  = 40         # monster pathfinding cap

# ── Sound Engine ────────────────────────────────────────────────────────────────

_SAMPLE_RATE = 22050


def _make_wav(samples: list) -> bytes:
    """Build a WAV file in memory from 16-bit mono samples."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SAMPLE_RATE)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def _tone(freq: float, dur_ms: int, volume: float = 0.3) -> list:
    """Generate sine-wave samples."""
    n = int(_SAMPLE_RATE * dur_ms / 1000)
    return [int(volume * 32767 * math.sin(2 * math.pi * freq * i / _SAMPLE_RATE))
            for i in range(n)]


def _build_sounds() -> dict:
    sounds = {}
    sounds["slash"]      = _make_wav(_tone(380, 35, 0.25) + _tone(280, 25, 0.15))
    s = []
    for i in range(int(_SAMPLE_RATE * 0.08)):
        f = 700 + 600 * (i / (_SAMPLE_RATE * 0.08))
        s.append(int(0.2 * 32767 * math.sin(2 * math.pi * f * i / _SAMPLE_RATE)))
    sounds["projectile"] = _make_wav(s)
    sounds["heal"]       = _make_wav(_tone(520, 60, 0.2) + _tone(780, 80, 0.25))
    sounds["death"]      = _make_wav(_tone(250, 60, 0.25) + _tone(180, 80, 0.2) + _tone(120, 100, 0.15))
    sounds["wave"]       = _make_wav(_tone(400, 80, 0.2) + _tone(530, 80, 0.25) + _tone(660, 120, 0.3))
    sounds["victory"]    = _make_wav(
        _tone(523, 120, 0.3) + _tone(659, 120, 0.3) +
        _tone(784, 120, 0.3) + _tone(1047, 200, 0.35))
    sounds["defeat"]     = _make_wav(
        _tone(400, 150, 0.25) + _tone(300, 150, 0.2) + _tone(200, 250, 0.2))
    return sounds


_SOUNDS: dict = {}


def play_sound(name: str):
    """Play a named sound asynchronously."""
    if not HAS_SOUND:
        return
    global _SOUNDS
    if not _SOUNDS:
        _SOUNDS.update(_build_sounds())
    data = _SOUNDS.get(name)
    if data:
        threading.Thread(
            target=lambda: winsound.PlaySound(data, winsound.SND_MEMORY),
            daemon=True,
        ).start()


# ── Asset Loader ────────────────────────────────────────────────────────────────

def load_asset(name: str, fallback_size: Tuple[int, int] = (TILE, TILE)) -> Image.Image:
    path = os.path.join(ASSET_DIR, name)
    if os.path.exists(path):
        return Image.open(path).convert("RGBA")
    img = Image.new("RGBA", fallback_size, (255, 0, 255, 255))
    return img


def tint(img: Image.Image, color: Tuple[int, int, int], strength: float = 0.55) -> Image.Image:
    """Blend non-transparent pixels toward color."""
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


def make_beholder() -> List[Image.Image]:
    """Procedural 32x32 AD&D Beholder — two animation frames."""
    frames = []
    for fi in range(2):
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((8, 27, 24, 31), fill=(0, 0, 0, 90))
        d.ellipse((3, 4, 29, 28), fill=(110, 68, 30))
        d.ellipse((6, 6, 17, 15), fill=(155, 100, 50))
        d.arc((3, 18, 29, 28), start=0, end=180, fill=(70, 38, 10), width=2)
        stalk_col = (80, 48, 18)
        tips  = [(7, 3), (11, 1), (16, 1), (21, 1), (25, 3), (27, 6)]
        roots = [(10, 7), (13, 5), (16, 5), (19, 5), (22, 7), (24, 9)]
        for (rx, ry), (tx, ty) in zip(roots, tips):
            d.line([(rx, ry), (tx, ty)], fill=stalk_col, width=1)
            d.ellipse((tx - 2, ty - 2, tx + 2, ty + 2), fill=(220, 40, 40))
            d.ellipse((tx - 1, ty - 1, tx + 1, ty + 1), fill=(20, 20, 20))
        ecx = 14 if fi == 0 else 18
        ecy = 16
        d.ellipse((ecx - 5, ecy - 5, ecx + 5, ecy + 5), fill=(240, 240, 240))
        idx = -1 if fi == 0 else 1
        d.ellipse((ecx + idx - 3, ecy - 3, ecx + idx + 3, ecy + 3), fill=(170, 30, 30))
        d.ellipse((ecx + idx - 1, ecy - 1, ecx + idx + 1, ecy + 1), fill=(10, 10, 10))
        d.ellipse((ecx + idx, ecy - 3, ecx + idx + 2, ecy - 1), fill=(255, 255, 255, 220))
        d.arc((7, 20, 25, 28), start=15, end=165, fill=(25, 8, 5), width=2)
        for tx in range(10, 24, 3):
            d.line([(tx, 23), (tx, 26)], fill=(225, 215, 195), width=1)
        frames.append(img)
    return frames


# ── Cave Generator ──────────────────────────────────────────────────────────────

class CaveGenerator:
    """Cellular automaton cave generator with flood-fill cleanup."""

    def __init__(self, w: int, h: int, fill: float = 0.45, seed=None):
        self.w = w
        self.h = h
        self.fill = fill
        self.rng = random.Random(seed)
        self.grid: List[List[int]] = [[0] * w for _ in range(h)]  # 0=floor, 1=wall

    def generate(self) -> List[List[int]]:
        # Phase 1: random fill
        for y in range(self.h):
            for x in range(self.w):
                if x < 2 or x >= self.w - 2 or y < 2 or y >= self.h - 2:
                    self.grid[y][x] = 1
                else:
                    self.grid[y][x] = 1 if self.rng.random() < self.fill else 0

        # Phase 2: 5x cellular automaton smoothing (Moore neighborhood)
        for _ in range(5):
            new = [[0] * self.w for _ in range(self.h)]
            for y in range(self.h):
                for x in range(self.w):
                    if x < 1 or x >= self.w - 1 or y < 1 or y >= self.h - 1:
                        new[y][x] = 1
                        continue
                    walls = sum(
                        1 for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                        if self.grid[y + dy][x + dx] == 1
                    )
                    new[y][x] = 1 if walls >= 5 else 0
            self.grid = new

        # Phase 3: keep only the largest connected floor region
        self._keep_largest_region()

        # Phase 4: enforce 2-tile solid border
        for y in range(self.h):
            for x in range(self.w):
                if x < 2 or x >= self.w - 2 or y < 2 or y >= self.h - 2:
                    self.grid[y][x] = 1

        return self.grid

    def _keep_largest_region(self):
        visited = [[False] * self.w for _ in range(self.h)]
        regions = []
        for y in range(self.h):
            for x in range(self.w):
                if self.grid[y][x] == 0 and not visited[y][x]:
                    region = []
                    stack = [(x, y)]
                    while stack:
                        cx, cy = stack.pop()
                        if visited[cy][cx]:
                            continue
                        if self.grid[cy][cx] == 1:
                            continue
                        visited[cy][cx] = True
                        region.append((cx, cy))
                        for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                            nx, ny = cx + ddx, cy + ddy
                            if 0 <= nx < self.w and 0 <= ny < self.h:
                                stack.append((nx, ny))
                    regions.append(region)
        if not regions:
            return
        largest = max(regions, key=len)
        largest_set = set(largest)
        for y in range(self.h):
            for x in range(self.w):
                if self.grid[y][x] == 0 and (x, y) not in largest_set:
                    self.grid[y][x] = 1

    def get_floor_zones(self, min_size: int = 20) -> List[List[Tuple[int, int]]]:
        """Partition floor tiles into 4 quadrant zones (NW, NE, SW, SE)."""
        floor_cells = [
            (x, y)
            for y in range(self.h)
            for x in range(self.w)
            if self.grid[y][x] == 0
        ]
        cx, cy = self.w // 2, self.h // 2
        zones: List[List[Tuple[int, int]]] = [[], [], [], []]
        for x, y in floor_cells:
            qi = (1 if x >= cx else 0) + (2 if y >= cy else 0)
            zones[qi].append((x, y))
        return [z for z in zones if len(z) >= min_size]


# ── Auto-Tiler ──────────────────────────────────────────────────────────────────

class Autotiler:
    """4-bit cardinal bitmask for floor-to-wall edge selection."""

    # N=8, S=4, E=2, W=1
    EDGE_MAP: Dict[int, Optional[str]] = {
        0:  None,
        1:  "Edge_w",
        2:  "Edge_e",
        3:  "Edge_we",
        4:  "Edge_s",
        5:  "Edge_sw",
        6:  "Edge_se",
        7:  "Edge_swe",
        8:  "Edge_n",
        9:  "Edge_nw",
        10: "Edge_ne",
        11: "Edge_nwe",
        12: "Edge_ns",
        13: "Edge_nsw",
        14: "Edge_nse",
        15: "Edge_single",
    }

    def __init__(self, grid: List[List[int]], assets: dict):
        self.grid   = grid
        self.h      = len(grid)
        self.w      = len(grid[0]) if grid else 0
        self.assets = assets

    def is_wall(self, x: int, y: int) -> bool:
        if x < 0 or x >= self.w or y < 0 or y >= self.h:
            return True
        return self.grid[y][x] == 1

    def get_edge_mask(self, x: int, y: int) -> int:
        """Return 4-bit mask for a FLOOR tile indicating adjacent wall sides."""
        mask = 0
        if self.is_wall(x, y - 1): mask |= 8  # N
        if self.is_wall(x, y + 1): mask |= 4  # S
        if self.is_wall(x + 1, y): mask |= 2  # E
        if self.is_wall(x - 1, y): mask |= 1  # W
        return mask

    def get_wall_asset_name(self, x: int, y: int) -> str:
        """Choose wall front or black fill based on neighbor layout."""
        has_floor_below = not self.is_wall(x, y + 1)
        if has_floor_below:
            has_floor_left  = not self.is_wall(x - 1, y)
            has_floor_right = not self.is_wall(x + 1, y)
            if has_floor_left and not has_floor_right:
                return "Wall_front_left"
            if has_floor_right and not has_floor_left:
                return "Wall_front_right"
            return "Wall_front"
        return "black"


# ── BFS Pathfinding ─────────────────────────────────────────────────────────────

def bfs_next_step(
    start: Tuple[int, int],
    goal:  Tuple[int, int],
    blocked: set,
    w: int,
    h: int,
) -> Optional[Tuple[int, int]]:
    """Return the first step on the shortest path from start to goal."""
    if start == goal:
        return None
    queue: deque = deque([start])
    visited: dict = {start: None}
    while queue:
        pos = queue.popleft()
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            npos = (pos[0] + dx, pos[1] + dy)
            if npos in visited:
                continue
            if not (0 <= npos[0] < w and 0 <= npos[1] < h):
                continue
            if npos in blocked:
                continue
            visited[npos] = pos
            if npos == goal:
                step = npos
                while visited[step] != start:
                    step = visited[step]
                return step
            queue.append(npos)
    return None


def bfs_distance_map(
    origin: Tuple[int, int],
    wall_cells: set,
    w: int,
    h: int,
    max_range: int = MAX_BFS_RANGE,
) -> Dict[Tuple[int, int], int]:
    """Compute distance map from origin; monsters read this to pathfind."""
    dist: Dict[Tuple[int, int], int] = {origin: 0}
    queue: deque = deque([origin])
    while queue:
        pos = queue.popleft()
        d = dist[pos]
        if d >= max_range:
            continue
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            np_ = (pos[0] + dx, pos[1] + dy)
            if np_ in dist:
                continue
            if np_ in wall_cells:
                continue
            if not (0 <= np_[0] < w and 0 <= np_[1] < h):
                continue
            dist[np_] = d + 1
            queue.append(np_)
    return dist


# ── Data Classes ────────────────────────────────────────────────────────────────

@dataclass
class Effect:
    kind:     str
    x:        float
    y:        float
    tx:       float = 0.0
    ty:       float = 0.0
    text:     str   = ""
    ttl:      int   = 12
    max_ttl:  int   = 12
    progress: float = 0.0
    color:    Tuple[int, int, int] = (255, 255, 0)


@dataclass
class Entity:
    name:      str
    gx:        int
    gy:        int
    hp:        int
    max_hp:    int
    atk:       int
    defense:   int
    is_hero:   bool
    img:       Image.Image
    size:      int  = 1
    range_:    int  = 1
    is_healer: bool = False
    speed:     int  = 1
    move_timer:  int = 0
    anim_frame:  int = 0
    anim_timer:  int = 0
    anim_frames: List[Image.Image] = field(default_factory=list)

    @property
    def dead(self) -> bool:
        return self.hp <= 0

    def cells(self) -> List[Tuple[int, int]]:
        return [(self.gx + dx, self.gy + dy)
                for dy in range(self.size)
                for dx in range(self.size)]

    def center_tile(self) -> Tuple[int, int]:
        off = self.size // 2
        return (self.gx + off, self.gy + off)

    def distance_to(self, other: "Entity") -> float:
        scx, scy = self.center_tile()
        ocx, ocy = other.center_tile()
        return math.hypot(scx - ocx, scy - ocy)

    def take_damage(self, dmg: int) -> int:
        dmg = max(1, dmg)
        self.hp = max(0, self.hp - dmg)
        return dmg


# ── TinyCrawl ───────────────────────────────────────────────────────────────────

class TinyCrawl:
    """Cave-based dungeon crawler with scrollable viewport and zone-based waves."""

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("TinyCrawl — Cave Level 1")
        root.configure(bg="#050508")

        # ── Fullscreen setup ───────────────────────────────────────────────────
        root.attributes("-fullscreen", True)
        root.bind("<Escape>", lambda _e: root.destroy())
        root.bind("<Key>", self._on_key)

        self._screen_w = root.winfo_screenwidth()
        self._screen_h = root.winfo_screenheight()
        self._view_w   = self._screen_w
        self._view_h   = self._screen_h - HUD_H  # pixels at screen resolution
        # viewport in tiles
        self._vp_tiles_x = self._view_w // (TILE * SCALE)
        self._vp_tiles_y = self._view_h // (TILE * SCALE)
        # camera position in tile coordinates (top-left of viewport)
        self.cam_x = 0
        self.cam_y = 0
        # manual camera offset (added to auto-follow)
        self._manual_dx = 0
        self._manual_dy = 0
        self._flash_ticks = 0   # screen flash counter

        self.canvas = tk.Canvas(
            root,
            width=self._screen_w,
            height=self._screen_h,
            bg="#050508",
            highlightthickness=0,
        )
        self.canvas.pack()
        self._tk_image: Optional[ImageTk.PhotoImage] = None
        self._canvas_img_id = self.canvas.create_image(0, 0, anchor="nw")

        self._load_assets()
        self._build_cave()
        self._cache_static_layer()
        self._build_scanline_overlay()
        self._setup_game()
        self._tick()

    # ── Input ──────────────────────────────────────────────────────────────────

    def _on_key(self, event):
        k = event.keysym
        if k in ("Left", "a"):
            self._manual_dx -= 2
        elif k in ("Right", "d"):
            self._manual_dx += 2
        elif k in ("Up", "w"):
            self._manual_dy -= 2
        elif k in ("Down", "s"):
            self._manual_dy += 2
        elif k in ("space", "Home"):
            self._manual_dx = 0
            self._manual_dy = 0

    # ── Asset Loading ──────────────────────────────────────────────────────────

    def _load_assets(self):
        A = load_asset

        # Floor
        self.floor_plain  = A("floor_plain.png")
        self.floor_stains = [A("floor_stain_1.png"), A("floor_stain_2.png"),
                             A("floor_stain_3.png")]
        self.floor_light  = A("floor_light.png")
        self.floor_mud_mid = A("floor_mud_mid_1.png")

        # Edge tiles (autotiler)
        self.edge_tiles: Dict[str, Image.Image] = {}
        for name in [
            "Edge_n", "Edge_s", "Edge_e", "Edge_w",
            "Edge_ne", "Edge_nw", "Edge_se", "Edge_sw",
            "Edge_ns", "Edge_we", "Edge_nse", "Edge_nsw",
            "Edge_nwe", "Edge_swe", "Edge_single",
        ]:
            self.edge_tiles[name] = A(f"{name}.png")

        # Wall tiles
        self.wall_front       = A("Wall_front.png")
        self.wall_front_left  = A("Wall_front_left.png")
        self.wall_front_right = A("Wall_front_right.png")
        self.wall_black       = A("black.png")

        # Pit tiles (for narrow tunnels / dead ends feel)
        self.pit_tiles: Dict[str, Image.Image] = {}
        for name in ["Pit_n", "Pit_s", "Pit_e", "Pit_w",
                     "Pit_ne", "Pit_nw", "Pit_se", "Pit_sw"]:
            self.pit_tiles[name] = A(f"{name}.png")

        # Darkness overlay tiles
        self.darkness_tiles = {
            "bottom": A("darkness_bottom.png"),
            "left":   A("darkness_left.png"),
            "right":  A("darkness_right.png"),
            "top":    A("darkness_top.png"),
        }
        self.black_tile = A("black.png")

        # Decorations
        self.column_img      = A("column.png",       (TILE, 32))
        self.chest_img       = A("chest_closed.png")
        self.chest_gold_img  = A("chest_golden_closed.png")
        self.skull_img       = A("skull.png")
        self.ladder_img      = A("Floor_ladder.png")
        self.torch_imgs      = [A(f"torch_{i}.png") for i in range(1, 9)]
        self.torch_no_flame  = A("torch_no_flame.png")
        self.flag_blue_img   = A("wall_flag_blue.png")
        self.flag_red_img    = A("wall_flag_red.png")
        self.flag_green_img  = A("wall_flag_green.png")
        self.flag_yellow_img = A("wall_flag_yellow.png")

        # Heroes (tinted copies of hero_basic)
        hero_base = A("hero_basic.png")
        self.hero_imgs = {
            "fighter": tint(hero_base, (60,  120, 210)),
            "paladin": tint(hero_base, (210, 175,  50)),
            "mage":    tint(hero_base, (170,  60, 220)),
            "cleric":  tint(hero_base, (220, 220, 220)),
            "ranger":  tint(hero_base, (60,  180,  80)),
            "thief":   tint(hero_base, (210,  60,  60)),
        }

        # Monsters (16×16)
        self.mon_imgs: Dict[str, Image.Image] = {
            "goblin":    A("monster_goblin.png"),
            "orc":       A("monster_orc.png"),
            "orc_arm":   A("monster_orc_armored.png"),
            "orc_vet":   A("monster_orc_veteran.png"),
            "orc_sha":   A("monster_orc_shaman.png"),
            "skelet":    A("monster_skelet.png"),
            "imp":       A("monster_imp.png"),
            "zombie":    A("monster_zombie.png"),
            "bat":       A("monster_bat.png"),
            "necro":     A("monster_necromancer.png"),
            "wogol":     A("monster_wogol.png"),
            "chort":     A("monster_chort.png"),
            "el_fire":   A("monster_elemental_fire.png"),
            "el_water":  A("monster_elemental_water.png"),
            "el_earth":  A("monster_elemental_earth.png"),
            "el_air":    A("monster_elemental_air.png"),
            "demon":     A("monster_demon.png",   (32, 32)),
            "ogre":      A("monster_ogre.png",    (32, 32)),
        }
        self.beholder_frames      = make_beholder()
        self.mon_imgs["beholder"] = self.beholder_frames[0]

        self.torch_frame = 0
        self.torch_timer = 0

    # ── Cave Build ─────────────────────────────────────────────────────────────

    def _build_cave(self):
        """Generate cave, run autotiler, place decorations."""
        seed = random.randint(0, 0xFFFFFF)
        gen  = CaveGenerator(WORLD_W, WORLD_H, fill=0.45, seed=seed)
        self.grid = gen.generate()

        # Build wall_cells set
        self.wall_cells: set = set()
        for y in range(WORLD_H):
            for x in range(WORLD_W):
                if self.grid[y][x] == 1:
                    self.wall_cells.add((x, y))

        # Autotiler
        self.autotiler = Autotiler(self.grid, self.edge_tiles)

        # Floor variety map: (x,y) -> tile image
        rng = random.Random(seed ^ 0xABCD)
        self.floor_map: Dict[Tuple[int, int], Image.Image] = {}
        for y in range(WORLD_H):
            for x in range(WORLD_W):
                if self.grid[y][x] == 0:
                    r = rng.random()
                    if   r < 0.05: self.floor_map[(x, y)] = rng.choice(self.floor_stains)
                    elif r < 0.08: self.floor_map[(x, y)] = self.floor_light
                    elif r < 0.10: self.floor_map[(x, y)] = self.floor_mud_mid
                    else:          self.floor_map[(x, y)] = self.floor_plain

        # Get zones for hero/monster placement
        self.zones = gen.get_floor_zones(min_size=20)
        if not self.zones:
            # Fallback: any 4 floor cells spread across quadrants
            all_floor = [(x, y) for y in range(WORLD_H) for x in range(WORLD_W)
                         if self.grid[y][x] == 0]
            rng.shuffle(all_floor)
            chunk = max(1, len(all_floor) // 4)
            self.zones = [all_floor[i*chunk:(i+1)*chunk] for i in range(4)]
            self.zones = [z for z in self.zones if z]

        # Decorations: (x, y, kind)
        self.decorations: List[Tuple[int, int, str]] = []
        deco_set: set = set()  # blocked by deco

        # Find dead ends (floor tiles with exactly 1 floor neighbor) -> skulls
        for y in range(2, WORLD_H - 2):
            for x in range(2, WORLD_W - 2):
                if self.grid[y][x] != 0:
                    continue
                floor_nbrs = sum(
                    1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if self.grid[y + dy][x + dx] == 0
                )
                if floor_nbrs == 1 and (x, y) not in deco_set:
                    self.decorations.append((x, y, "skull"))
                    deco_set.add((x, y))

        # Torch positions: narrow passages (floor tiles touching >=2 walls on N/S or E/W)
        torch_count = 0
        for y in range(2, WORLD_H - 2):
            for x in range(2, WORLD_W - 2):
                if self.grid[y][x] != 0 or (x, y) in deco_set:
                    continue
                wall_n = self.grid[y - 1][x] == 1
                wall_s = self.grid[y + 1][x] == 1
                wall_e = self.grid[y][x + 1] == 1
                wall_w = self.grid[y][x - 1] == 1
                if (wall_n and wall_s) or (wall_e and wall_w):
                    if torch_count < 80 and rng.random() < 0.25:
                        self.decorations.append((x, y, "torch"))
                        torch_count += 1

        # Chest placements: wide open spots (floor tiles surrounded mostly by floor)
        chest_count = 0
        for y in range(3, WORLD_H - 3):
            for x in range(3, WORLD_W - 3):
                if self.grid[y][x] != 0 or (x, y) in deco_set:
                    continue
                floor_nbrs = sum(
                    1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                                     (1, 1), (-1, -1), (1, -1), (-1, 1))
                    if 0 <= y + dy < WORLD_H and self.grid[y + dy][x + dx] == 0
                )
                if floor_nbrs >= 7 and chest_count < 12 and rng.random() < 0.04:
                    kind = "chest_gold" if rng.random() < 0.3 else "chest"
                    self.decorations.append((x, y, kind))
                    deco_set.add((x, y))
                    chest_count += 1

        # Add deco cells as blocked (but only non-torch, non-skull for movement)
        for gx, gy, kind in self.decorations:
            if kind in ("chest", "chest_gold", "column"):
                self.wall_cells.add((gx, gy))

        # Ladder (exit) at opposite end from heroes
        if self.zones:
            far_zone = self.zones[-1] if len(self.zones) >= 2 else self.zones[0]
            mid_idx = len(far_zone) // 2
            lx, ly = far_zone[mid_idx]
            self.ladder_pos = (lx, ly)
            self.decorations.append((lx, ly, "ladder"))
        else:
            self.ladder_pos = (WORLD_W - 5, WORLD_H - 5)

    def _cache_static_layer(self):
        """Render the entire WORLD_W x WORLD_H cave to one RGBA image at source scale."""
        src_w = WORLD_W * TILE
        src_h = WORLD_H * TILE
        self._static = Image.new("RGBA", (src_w, src_h), (5, 3, 8, 255))

        at = self.autotiler

        for y in range(WORLD_H):
            for x in range(WORLD_W):
                px, py = x * TILE, y * TILE
                if self.grid[y][x] == 0:
                    # Floor base
                    tile = self.floor_map.get((x, y), self.floor_plain)
                    self._static.paste(tile, (px, py), tile)
                    # Edge overlay
                    mask = at.get_edge_mask(x, y)
                    ename = Autotiler.EDGE_MAP.get(mask)
                    if ename and ename in self.edge_tiles:
                        etile = self.edge_tiles[ename]
                        self._static.paste(etile, (px, py), etile)
                else:
                    # Wall tile
                    wname = at.get_wall_asset_name(x, y)
                    if wname == "Wall_front":
                        wt = self.wall_front
                    elif wname == "Wall_front_left":
                        wt = self.wall_front_left
                    elif wname == "Wall_front_right":
                        wt = self.wall_front_right
                    else:
                        wt = self.wall_black
                    self._static.paste(wt, (px, py), wt)

        # Paste static decorations (non-animated)
        for gx, gy, kind in self.decorations:
            if kind == "skull":
                img = self.skull_img
                self._static.paste(img, (gx * TILE, gy * TILE), img)
            elif kind == "chest":
                img = self.chest_img
                self._static.paste(img, (gx * TILE, gy * TILE), img)
            elif kind == "chest_gold":
                img = self.chest_gold_img
                self._static.paste(img, (gx * TILE, gy * TILE), img)
            elif kind == "ladder":
                img = self.ladder_img
                self._static.paste(img, (gx * TILE, gy * TILE), img)

    def _build_scanline_overlay(self):
        """Pre-compute CRT scanline overlay at final screen resolution."""
        h = self._view_h + HUD_H
        self._scanline = Image.new("RGBA", (self._screen_w, h), (0, 0, 0, 0))
        for row in range(0, h, 2):
            ImageDraw.Draw(self._scanline).line(
                [(0, row), (self._screen_w - 1, row)],
                fill=(0, 0, 0, SCANLINE_ALPHA),
            )

    # ── Game Setup ─────────────────────────────────────────────────────────────

    def _setup_game(self):
        self.tick_count = 0
        self.wave       = 0
        self.wave_pause = 0
        self.game_over  = False
        self.victory    = False
        self.effects:   List[Effect] = []
        self.log_msgs:  deque        = deque(maxlen=5)
        self._dist_map: Dict[Tuple[int, int], int] = {}
        self.log("TinyCrawl Level 1 — Hoehle!")
        self.heroes   = self._make_heroes()
        self.monsters: List[Entity] = []
        self._spawn_wave()
        self._center_camera()

    def _center_camera(self):
        """Snap camera to hero centroid."""
        alive = [h for h in self.heroes if not h.dead]
        if not alive:
            return
        cx = sum(h.gx for h in alive) // len(alive)
        cy = sum(h.gy for h in alive) // len(alive)
        self.cam_x = max(0, min(WORLD_W - self._vp_tiles_x, cx - self._vp_tiles_x // 2))
        self.cam_y = max(0, min(WORLD_H - self._vp_tiles_y, cy - self._vp_tiles_y // 2))

    def _make_heroes(self) -> List[Entity]:
        """Place heroes in zone 0 (closest to world origin)."""
        zone0 = self.zones[0] if self.zones else [(5, 5)]
        # pick 6 spread positions from zone0
        step = max(1, len(zone0) // 7)
        positions = [zone0[i * step] for i in range(min(6, len(zone0) // step))]
        while len(positions) < 6:
            positions.append(zone0[len(positions) % len(zone0)])

        specs = [
            ("Thorin",      "fighter", 45,  8,  4, 1),
            ("Sir Aldric",  "paladin", 50,  7,  5, 1),
            ("Elara",       "mage",    20, 12,  1, 4),
            ("Br. Aldhelm", "cleric",  35,  5,  3, 1),
            ("Kaelen",      "ranger",  30,  9,  2, 5),
            ("Lyra",        "thief",   25, 10,  2, 1),
        ]
        healers = {3}  # Br. Aldhelm index
        heroes  = []
        for i, (name, cls, hp, atk, defense, rng) in enumerate(specs):
            gx, gy = positions[i]
            heroes.append(Entity(
                name=name, gx=gx, gy=gy, hp=hp, max_hp=hp,
                atk=atk, defense=defense, is_hero=True,
                img=self.hero_imgs[cls],
                range_=rng, is_healer=(i in healers), speed=1,
            ))
        return heroes

    def _spawn_wave(self):
        """Spawn wave monsters in progressively further zones."""
        self.wave += 1
        play_sound("wave")
        self._flash_ticks = 2

        def mk(name, key, gx, gy, hp, atk, df, size=1, rng=1):
            img = self.mon_imgs.get(key, self.mon_imgs["goblin"])
            if key == "beholder":
                return Entity(
                    name=name, gx=gx, gy=gy, hp=hp, max_hp=hp,
                    atk=atk, defense=df, is_hero=False,
                    img=self.beholder_frames[0], size=size, range_=rng,
                    anim_frames=self.beholder_frames,
                )
            return Entity(
                name=name, gx=gx, gy=gy, hp=hp, max_hp=hp,
                atk=atk, defense=df, is_hero=False,
                img=img, size=size, range_=rng,
            )

        # Choose spawn zone (wave 1 → zone 1, wave 2 → zone 2, etc.)
        zones = self.zones
        zone_idx = min(self.wave - 1, len(zones) - 1)
        # Fallback to zone 0 if needed
        if zone_idx < 0 or zone_idx >= len(zones):
            zone_idx = 0
        zone = zones[zone_idx]

        def zone_pos(i: int) -> Tuple[int, int]:
            """Pick a floor position from zone, avoiding wall_cells."""
            rng = random.Random(self.wave * 100 + i)
            candidates = [p for p in zone if p not in self.wall_cells]
            if not candidates:
                candidates = zone
            rng.shuffle(candidates)
            # Try to spread positions out
            return candidates[i % len(candidates)]

        self.monsters = []
        if self.wave == 1:
            names = ["Goblin I", "Goblin II", "Goblin III", "Goblin IV",
                     "Fledermaus I", "Fledermaus II"]
            kinds = ["goblin", "goblin", "goblin", "goblin", "bat", "bat"]
            stats = [(12, 4, 1), (12, 4, 1), (12, 4, 1), (12, 4, 1),
                     (8,  3, 0, 1, 3), (8, 3, 0, 1, 3)]
            for i, (n, k) in enumerate(zip(names, kinds)):
                st = stats[i]
                gx, gy = zone_pos(i)
                self.monsters.append(mk(n, k, gx, gy, *st[:3],
                                        size=st[3] if len(st) > 3 else 1,
                                        rng=st[4]  if len(st) > 4 else 1))

        elif self.wave == 2:
            entries = [
                ("Ork I",    "orc",     (20, 6, 2)),
                ("Ork II",   "orc",     (20, 6, 2)),
                ("Ork Vet",  "orc_vet", (25, 7, 3)),
                ("Skelett I","skelet",  (15, 5, 1)),
                ("Skelett II","skelet", (15, 5, 1)),
                ("Necro",    "necro",   (18, 7, 1, 1, 4)),
                ("Wogol",    "wogol",   (22, 6, 2)),
            ]
            for i, (n, k, st) in enumerate(entries):
                gx, gy = zone_pos(i)
                self.monsters.append(mk(n, k, gx, gy, *st[:3],
                                        size=st[3] if len(st) > 3 else 1,
                                        rng=st[4]  if len(st) > 4 else 1))

        elif self.wave == 3:
            entries = [
                ("Beholder",   "beholder", (80, 10, 3, 2, 5)),
                ("Chort",      "chort",    (30,  8, 3)),
                ("Imp I",      "imp",      (10,  5, 1, 1, 3)),
                ("Imp II",     "imp",      (10,  5, 1, 1, 3)),
                ("El. Feuer",  "el_fire",  (25,  8, 2)),
                ("El. Wasser", "el_water", (22,  6, 2)),
                ("Ork Sha.",   "orc_sha",  (18,  7, 1, 1, 4)),
            ]
            for i, (n, k, st) in enumerate(entries):
                gx, gy = zone_pos(i)
                self.monsters.append(mk(n, k, gx, gy, *st[:3],
                                        size=st[3] if len(st) > 3 else 1,
                                        rng=st[4]  if len(st) > 4 else 1))

        elif self.wave == 4:
            entries = [
                ("Daemon",    "demon",    (100, 12, 4, 2, 1)),
                ("Oger",      "ogre",     (60,   9, 3, 2, 1)),
                ("El. Erde",  "el_earth", (35,   8, 3)),
                ("El. Luft",  "el_air",   (28,   7, 2, 1, 3)),
                ("Zombie I",  "zombie",   (20,   5, 1)),
                ("Zombie II", "zombie",   (20,   5, 1)),
                ("Ork Maske", "orc_arm",  (30,   8, 4)),
            ]
            for i, (n, k, st) in enumerate(entries):
                gx, gy = zone_pos(i)
                self.monsters.append(mk(n, k, gx, gy, *st[:3],
                                        size=st[3] if len(st) > 3 else 1,
                                        rng=st[4]  if len(st) > 4 else 1))

        self.log(f"--- Welle {self.wave}: {len(self.monsters)} Feinde! ---")

    # ── Distance Map ───────────────────────────────────────────────────────────

    def _compute_distance_map(self):
        """Build BFS distance map from hero centroid (used by all monsters)."""
        alive = [h for h in self.heroes if not h.dead]
        if not alive:
            self._dist_map = {}
            return
        cx = sum(h.gx for h in alive) // len(alive)
        cy = sum(h.gy for h in alive) // len(alive)
        origin = (cx, cy)
        # clamp to floor
        if origin in self.wall_cells:
            # find nearest floor tile
            for r in range(1, 6):
                for dx, dy in ((0, -r), (0, r), (-r, 0), (r, 0)):
                    p = (cx + dx, cy + dy)
                    if p not in self.wall_cells and 0 <= p[0] < WORLD_W and 0 <= p[1] < WORLD_H:
                        origin = p
                        break
                else:
                    continue
                break
        self._dist_map = bfs_distance_map(origin, self.wall_cells, WORLD_W, WORLD_H)

    # ── Game Logic ─────────────────────────────────────────────────────────────

    def _blocked_for(self, entity: Entity, all_entities: List[Entity]) -> set:
        own = set(entity.cells())
        bl  = set(self.wall_cells)
        for e in all_entities:
            if e is not entity and not e.dead:
                for c in e.cells():
                    bl.add(c)
        bl -= own
        return bl

    def _find_adjacent_goal(
        self, attacker: Entity, target: Entity, blocked: set
    ) -> Optional[Tuple[int, int]]:
        best     = None
        best_dist = 999
        tcells   = set(target.cells())
        for tc in target.cells():
            for ddx, ddy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                adj = (tc[0] + ddx, tc[1] + ddy)
                if adj in tcells:
                    continue
                if adj in blocked and adj not in set(attacker.cells()):
                    continue
                if not (0 <= adj[0] < WORLD_W and 0 <= adj[1] < WORLD_H):
                    continue
                d = abs(adj[0] - attacker.gx) + abs(adj[1] - attacker.gy)
                if d < best_dist:
                    best_dist = d
                    best = adj
        return best

    def _update(self):
        self.tick_count += 1

        # Flash tick
        if self._flash_ticks > 0:
            self._flash_ticks -= 1

        # Torch animation
        self.torch_timer += 1
        if self.torch_timer >= ANIM_TICKS:
            self.torch_timer = 0
            self.torch_frame = (self.torch_frame + 1) % len(self.torch_imgs)

        # Wave pause countdown
        if self.wave_pause > 0:
            self.wave_pause -= 1
            if self.wave_pause == 0:
                if self.wave < 4:
                    self._spawn_wave()
                else:
                    self.victory  = True
                    self.game_over = True
                    self.log("*** SIEG! Das Dungeon bezwungen! ***")
                    play_sound("victory")
            return

        # Effects tick
        for eff in self.effects[:]:
            eff.ttl -= 1
            if eff.kind == "projectile":
                eff.progress = min(1.0, eff.progress + 0.2)
            if eff.ttl <= 0:
                self.effects.remove(eff)

        # Beholder / animated monster frames
        for m in self.monsters:
            if not m.dead and m.anim_frames:
                m.anim_timer += 1
                if m.anim_timer >= ANIM_TICKS:
                    m.anim_timer = 0
                    m.anim_frame = (m.anim_frame + 1) % len(m.anim_frames)
                    m.img = m.anim_frames[m.anim_frame]

        alive_heroes   = [h for h in self.heroes   if not h.dead]
        alive_monsters = [m for m in self.monsters if not m.dead]

        if not alive_heroes:
            self.game_over = True
            self.log("NIEDERLAGE! Die Gruppe gefallen...")
            play_sound("defeat")
            return

        if not alive_monsters:
            self.log(f"Welle {self.wave} besiegt!")
            if self.wave >= 4:
                self.victory  = True
                self.game_over = True
                self.log("*** SIEG! Das Dungeon bezwungen! ***")
                play_sound("victory")
            else:
                self.wave_pause = WAVE_PAUSE
            return

        all_ents = alive_heroes + alive_monsters

        # Compute distance map once per tick
        self._compute_distance_map()

        # ── Camera auto-follow ─────────────────────────────────────────────────
        if alive_heroes:
            cx = sum(h.gx for h in alive_heroes) // len(alive_heroes)
            cy = sum(h.gy for h in alive_heroes) // len(alive_heroes)
            target_cx = cx - self._vp_tiles_x // 2 + self._manual_dx
            target_cy = cy - self._vp_tiles_y // 2 + self._manual_dy
            self.cam_x = max(0, min(WORLD_W - self._vp_tiles_x, target_cx))
            self.cam_y = max(0, min(WORLD_H - self._vp_tiles_y, target_cy))

        # ── Hero turns ─────────────────────────────────────────────────────────
        for hero in alive_heroes:
            hero.move_timer += 1
            if hero.move_timer < MOVE_TICKS * hero.speed:
                continue
            hero.move_timer = 0

            # Healer
            if hero.is_healer:
                wounded = [h for h in alive_heroes if h.hp < h.max_hp]
                if wounded:
                    t = min(wounded, key=lambda h: h.hp)
                    heal = random.randint(4, 8)
                    t.hp = min(t.max_hp, t.hp + heal)
                    self.effects.append(Effect(
                        "dmg_text",
                        (t.gx + 0.5) * TILE, (t.gy) * TILE,
                        text=f"+{heal}", color=(100, 255, 120), ttl=18, max_ttl=18,
                    ))
                    play_sound("heal")
                continue

            if not alive_monsters:
                continue
            nearest = min(alive_monsters, key=lambda m: hero.distance_to(m))
            dist    = hero.distance_to(nearest)
            if dist <= hero.range_ + 0.5:
                self._attack(hero, nearest, ranged=(hero.range_ > 1))
            else:
                bl   = self._blocked_for(hero, all_ents)
                goal = self._find_adjacent_goal(hero, nearest, bl)
                if goal:
                    step = bfs_next_step((hero.gx, hero.gy), goal, bl, WORLD_W, WORLD_H)
                    if step:
                        hero.gx, hero.gy = step

        # ── Monster turns (use distance map) ───────────────────────────────────
        alive_heroes_now = [h for h in self.heroes if not h.dead]
        for mon in alive_monsters:
            mon.move_timer += 1
            if mon.move_timer < MOVE_TICKS:
                continue
            mon.move_timer = 0

            if not alive_heroes_now:
                break
            nearest = min(alive_heroes_now, key=lambda h: mon.distance_to(h))
            dist    = mon.distance_to(nearest)

            if dist <= mon.range_ + 0.5:
                self._attack(mon, nearest, ranged=(mon.range_ > 1))
                alive_heroes_now = [h for h in alive_heroes_now if not h.dead]
            else:
                # Move toward decreasing distance in dist_map
                mcx, mcy = mon.center_tile()
                best_step = None
                best_d    = self._dist_map.get((mcx, mcy), 9999)
                bl        = self._blocked_for(mon, all_ents)
                for ddx, ddy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                    np_ = (mcx + ddx, mcy + ddy)
                    if np_ in bl:
                        continue
                    nd = self._dist_map.get(np_, 9999)
                    if nd < best_d:
                        best_d    = nd
                        best_step = np_

                if best_step:
                    off  = mon.size // 2
                    ngx  = max(0, min(WORLD_W - mon.size, best_step[0] - off))
                    ngy  = max(0, min(WORLD_H - mon.size, best_step[1] - off))
                    new_cells = {
                        (ngx + dx, ngy + dy)
                        for dy in range(mon.size)
                        for dx in range(mon.size)
                    }
                    if not new_cells.intersection(bl):
                        mon.gx, mon.gy = ngx, ngy

    def _attack(self, attacker: Entity, target: Entity, ranged: bool):
        dmg = max(1, attacker.atk - target.defense + random.randint(-2, 2))
        target.take_damage(dmg)

        # Coordinates in world-pixel space (source scale)
        scx = (attacker.gx + attacker.size * 0.5) * TILE
        scy = (attacker.gy + attacker.size * 0.5) * TILE
        tcx = (target.gx  + target.size  * 0.5) * TILE
        tcy = (target.gy  + target.size  * 0.5) * TILE

        if ranged:
            col = (255, 200, 60) if attacker.is_hero else (180, 60, 255)
            self.effects.append(Effect(
                "projectile", scx, scy, tx=tcx, ty=tcy,
                ttl=8, max_ttl=8, color=col,
            ))
            play_sound("projectile")
        else:
            self.effects.append(Effect(
                "slash", tcx, tcy, ttl=6, max_ttl=6, color=(255, 60, 60),
            ))
            play_sound("slash")

        txt_col = (255, 220, 50) if attacker.is_hero else (255, 80, 80)
        self.effects.append(Effect(
            "dmg_text", tcx, tcy - 3,
            text=str(dmg), color=txt_col, ttl=18, max_ttl=18,
        ))

        if target.dead:
            self.log(f"{attacker.name} besiegt {target.name}!")
            play_sound("death")

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _render(self):
        cam_x, cam_y = self.cam_x, self.cam_y
        vp_tw = self._vp_tiles_x
        vp_th = self._vp_tiles_y

        # Crop viewport from static world image
        crop_x = cam_x * TILE
        crop_y = cam_y * TILE
        crop_w = vp_tw * TILE
        crop_h = vp_th * TILE
        # Clamp crop box to world image bounds
        crop_x = max(0, min(WORLD_W * TILE - crop_w, crop_x))
        crop_y = max(0, min(WORLD_H * TILE - crop_h, crop_y))
        src = self._static.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))

        # Animated torches on top of viewport crop
        torch = self.torch_imgs[self.torch_frame]
        for gx, gy, kind in self.decorations:
            if kind == "torch":
                vx = gx - cam_x
                vy = gy - cam_y
                if 0 <= vx < vp_tw and 0 <= vy < vp_th:
                    src.paste(torch, (vx * TILE, vy * TILE), torch)

        # Draw entities sorted by y
        living = [e for e in self.heroes + self.monsters if not e.dead]
        living.sort(key=lambda e: e.gy)
        for ent in living:
            vx = ent.gx - cam_x
            vy = ent.gy - cam_y
            if not (-ent.size < vx < vp_tw and -ent.size < vy < vp_th):
                continue
            px, py = vx * TILE, vy * TILE
            src.paste(ent.img, (px, py), ent.img)
            # HP bar
            bw    = TILE * ent.size
            by_   = py - 3
            ratio = max(0.0, ent.hp / ent.max_hp)
            d = ImageDraw.Draw(src)
            d.rectangle([px, by_, px + bw - 1, by_ + 1], fill=(40, 40, 40))
            filled = max(1, int(bw * ratio))
            if ratio > 0:
                col = (70, 210, 70) if ent.is_hero else (210, 50, 50)
                d.rectangle([px, by_, px + filled, by_ + 1], fill=col)

        # Slash effects at source scale
        d_src = ImageDraw.Draw(src)
        for eff in self.effects:
            if eff.kind == "slash":
                ex = int(eff.x / TILE - cam_x) * TILE + TILE // 2
                ey = int(eff.y / TILE - cam_y) * TILE + TILE // 2
                col = eff.color
                d_src.line([(ex - 3, ey - 3), (ex + 3, ey + 3)], fill=col, width=1)
                d_src.line([(ex + 3, ey - 3), (ex - 3, ey + 3)], fill=col, width=1)

        # Apply fog of war
        self._render_fog(src, cam_x, cam_y, vp_tw, vp_th)

        # Scale up viewport image with NEAREST (retro pixel art)
        big = src.resize(
            (vp_tw * TILE * SCALE, vp_th * TILE * SCALE),
            Image.NEAREST,
        )

        # Final frame at screen size
        final_w = self._screen_w
        final_h = self._view_h + HUD_H
        final = Image.new("RGBA", (final_w, final_h), (5, 3, 8, 255))
        final.paste(big, (0, 0))

        d = ImageDraw.Draw(final)

        # Projectile + damage text at screen scale
        for eff in self.effects:
            if eff.kind == "projectile":
                def to_screen(wx, wy):
                    sx = (wx / TILE - cam_x) * TILE * SCALE
                    sy = (wy / TILE - cam_y) * TILE * SCALE
                    return sx, sy
                sx_, sy_ = to_screen(eff.x, eff.y)
                ex_, ey_ = to_screen(eff.tx, eff.ty)
                cx_ = sx_ + (ex_ - sx_) * eff.progress
                cy_ = sy_ + (ey_ - sy_) * eff.progress
                d.ellipse((cx_ - 4, cy_ - 4, cx_ + 4, cy_ + 4), fill=eff.color)
                if eff.progress > 0.2:
                    px_ = sx_ + (ex_ - sx_) * max(0, eff.progress - 0.2)
                    py_ = sy_ + (ey_ - sy_) * max(0, eff.progress - 0.2)
                    d.ellipse((px_ - 2, py_ - 2, px_ + 2, py_ + 2),
                              fill=tuple(max(0, c // 2) for c in eff.color))
            elif eff.kind == "dmg_text":
                rise = (1.0 - eff.ttl / eff.max_ttl) * 24
                sx_ = (eff.x / TILE - cam_x) * TILE * SCALE
                sy_ = (eff.y / TILE - cam_y) * TILE * SCALE - rise
                fade = eff.ttl / eff.max_ttl
                col  = tuple(max(0, min(255, int(v * fade))) for v in eff.color)
                d.text((int(sx_), int(sy_)), eff.text, fill=col)

        # Wave flash (white overlay)
        if self._flash_ticks > 0:
            flash = Image.new("RGBA", (final_w, self._view_h), (255, 255, 200, 100))
            final.alpha_composite(flash, (0, 0))

        # Scanline CRT effect
        final.alpha_composite(self._scanline, (0, 0))

        # HUD + minimap
        self._draw_hud(d, self._view_h)
        self._render_minimap(final)

        if self.game_over:
            self._draw_endgame(final)

        self._tk_image = ImageTk.PhotoImage(final)
        self.canvas.itemconfig(self._canvas_img_id, image=self._tk_image)

    def _render_fog(
        self,
        src: Image.Image,
        cam_x: int, cam_y: int,
        vp_tw: int, vp_th: int,
    ):
        """Apply fog of war over the viewport src image (in-place)."""
        alive = [h for h in self.heroes if not h.dead]
        if not alive:
            # Full black fog
            fog = Image.new("RGBA", src.size, (0, 0, 0, 230))
            src.alpha_composite(fog)
            return

        # Build set of lit tiles (within FOG_NEAR of any hero)
        near_set: set = set()
        mid_set:  set = set()
        for h in alive:
            for dy in range(-FOG_FAR - 1, FOG_FAR + 2):
                for dx in range(-FOG_FAR - 1, FOG_FAR + 2):
                    tx = h.gx + dx
                    ty = h.gy + dy
                    dist_sq = dx * dx + dy * dy
                    if dist_sq <= FOG_NEAR * FOG_NEAR:
                        near_set.add((tx, ty))
                    elif dist_sq <= FOG_FAR * FOG_FAR:
                        mid_set.add((tx, ty))

        # Draw fog tile by tile into viewport
        fog_layer = Image.new("RGBA", src.size, (0, 0, 0, 0))
        fd = ImageDraw.Draw(fog_layer)
        for vy in range(vp_th):
            for vx in range(vp_tw):
                wx, wy = vx + cam_x, vy + cam_y
                pos = (wx, wy)
                if pos in near_set:
                    continue  # fully lit
                px, py = vx * TILE, vy * TILE
                if pos in mid_set:
                    fd.rectangle([px, py, px + TILE - 1, py + TILE - 1],
                                  fill=(0, 0, 0, 128))
                else:
                    fd.rectangle([px, py, px + TILE - 1, py + TILE - 1],
                                  fill=(0, 0, 0, 230))
        src.alpha_composite(fog_layer)

    def _render_minimap(self, final: Image.Image):
        """Draw a 160×120 minimap in the bottom-right HUD corner."""
        mm_w, mm_h = MINIMAP_W, MINIMAP_H
        mm = Image.new("RGBA", (mm_w, mm_h), (15, 12, 20, 200))
        d  = ImageDraw.Draw(mm)

        sx = mm_w / WORLD_W
        sy = mm_h / WORLD_H

        # Draw floor/wall
        for y in range(WORLD_H):
            for x in range(WORLD_W):
                px = int(x * sx)
                py = int(y * sy)
                pw = max(1, int(sx))
                ph = max(1, int(sy))
                if self.grid[y][x] == 0:
                    d.rectangle([px, py, px + pw - 1, py + ph - 1], fill=(80, 72, 60))
                else:
                    d.rectangle([px, py, px + pw - 1, py + ph - 1], fill=(20, 18, 25))

        # Viewport rectangle
        vx0 = int(self.cam_x * sx)
        vy0 = int(self.cam_y * sy)
        vx1 = int((self.cam_x + self._vp_tiles_x) * sx)
        vy1 = int((self.cam_y + self._vp_tiles_y) * sy)
        d.rectangle([vx0, vy0, vx1, vy1], outline=(200, 200, 200, 180))

        # Heroes (green dots)
        for h in self.heroes:
            if not h.dead:
                mx = int(h.gx * sx)
                my = int(h.gy * sy)
                d.rectangle([mx - 1, my - 1, mx + 1, my + 1], fill=(80, 220, 80))

        # Monsters (red dots)
        for m in self.monsters:
            if not m.dead:
                mx = int(m.gx * sx)
                my = int(m.gy * sy)
                d.rectangle([mx, my, mx, my], fill=(220, 60, 60))

        # Border
        d.rectangle([0, 0, mm_w - 1, mm_h - 1], outline=(100, 90, 120))

        hud_y     = self._view_h
        paste_x   = self._screen_w - mm_w - 4
        paste_y   = hud_y + (HUD_H - mm_h) // 2
        final.alpha_composite(mm, (paste_x, max(hud_y, paste_y)))

    def _draw_hud(self, d: ImageDraw.ImageDraw, hud_y: int):
        """Draw the HUD panel below the viewport."""
        hud_w = self._screen_w
        d.rectangle([0, hud_y, hud_w - 1, hud_y + HUD_H - 1], fill=(10, 8, 18))
        d.line([(0, hud_y), (hud_w, hud_y)], fill=(80, 60, 110), width=2)

        alive_mon = len([m for m in self.monsters if not m.dead])
        pause_txt = f"  (Naechste in {self.wave_pause})" if self.wave_pause > 0 else ""
        d.text((10, hud_y + 6),
               f"Welle {self.wave}/4    Feinde: {alive_mon}{pause_txt}    "
               f"[WASD/Pfeile=Kamera  Leertaste=Zentrierung  ESC=Beenden]",
               fill=(200, 175, 90))

        bx, by = 10, hud_y + 20
        bw, bh = 50, 5
        for hero in self.heroes:
            ratio = max(0.0, hero.hp / hero.max_hp)
            d.rectangle([bx, by, bx + bw, by + bh], fill=(30, 28, 40))
            if ratio > 0 and not hero.dead:
                col = (70, 200, 70) if ratio > 0.4 else (220, 160, 30) if ratio > 0.2 else (210, 50, 50)
                d.rectangle([bx, by, bx + int(bw * ratio), by + bh], fill=col)
            d.rectangle([bx, by, bx + bw, by + bh], outline=(60, 50, 80))
            short = hero.name.split()[0][:6]
            d.text((bx, by + bh + 2), f"{short} {max(0,hero.hp)}/{hero.max_hp}",
                   fill=(155, 135, 175) if not hero.dead else (70, 55, 65))
            bx += bw + 12

        log_y = hud_y + 40
        for i, msg in enumerate(self.log_msgs):
            if log_y + i * 10 >= hud_y + HUD_H - 2:
                break
            fade = max(0.35, 1.0 - i * 0.18)
            col  = tuple(int(v * fade) for v in (185, 160, 215))
            d.text((10, log_y + i * 10), msg[:120], fill=col)

    def _draw_endgame(self, final: Image.Image):
        overlay = Image.new("RGBA", final.size, (0, 0, 0, 170))
        final.alpha_composite(overlay)
        d  = ImageDraw.Draw(final)
        cx = self._screen_w // 2
        cy = (self._view_h) // 2 - 20
        if self.victory:
            msg, col = "*** SIEG! ***", (255, 215, 50)
            sub = "Das Dungeon ist bezwungen!"
        else:
            msg, col = "*** NIEDERLAGE! ***", (220, 50, 50)
            sub = "Die Gruppe ist gefallen..."
        # Shadow
        d.text((cx - 68, cy + 2), msg, fill=(0, 0, 0))
        d.text((cx - 70, cy),     msg, fill=col)
        d.text((cx - 80, cy + 22), sub,                    fill=(200, 200, 200))
        d.text((cx - 90, cy + 40), "ESC druecken zum Beenden.", fill=(130, 120, 150))

    # ── Main Loop ──────────────────────────────────────────────────────────────

    def _tick(self):
        try:
            if not self.game_over:
                self._update()
            self._render()
        except Exception as e:
            print(f"[TinyCrawl ERROR] {e}")
            import traceback
            traceback.print_exc()
        self.root.after(1000 // FPS, self._tick)

    def log(self, msg: str):
        self.log_msgs.appendleft(msg)


# ── Entry Point ─────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    TinyCrawl(root)
    root.mainloop()


if __name__ == "__main__":
    main()
