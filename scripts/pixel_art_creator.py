"""
scripts/pixel_art_creator.py — Prozeduraler Pixel-Art-Generator

Erzeugt 16x16 RGBA PNGs fuer das ARS Dungeon-Tileset:
  - Monster (Symmetrie-Generator mit Silhouette-Seeds)
  - Items (Template-basiert mit Farb-Varianten)
  - Terrain/Deko (Noise-Pattern und Moebel-Shapes)
  - Effekte (Animationsframes fuer Spell/Combat)
  - Animationen (Walk, Attack, Idle, Hit, Death — Charakter-Spritesheets)

Verwendung:
  py -3 scripts/pixel_art_creator.py --all --preview
  py -3 scripts/pixel_art_creator.py --category animations --count 6 --seed 42
  py -3 scripts/pixel_art_creator.py --category monsters --count 10 --seed 42
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
from typing import Callable

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("FEHLER: Pillow nicht installiert. pip install Pillow")
    sys.exit(1)

# ── Konstanten ───────────────────────────────────────────────────────────────

TILE = 16
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "tilesets", "generated",
)

# Farbpaletten (RGBA)
PALETTES = {
    "undead":  [(90, 100, 80), (60, 75, 55), (140, 150, 130), (200, 210, 190), (50, 60, 45)],
    "demon":   [(180, 40, 30), (120, 20, 15), (60, 10, 10), (220, 80, 40), (255, 160, 60)],
    "beast":   [(140, 100, 60), (100, 70, 40), (180, 140, 90), (80, 55, 30), (200, 170, 120)],
    "elemental": [(60, 120, 200), (40, 80, 160), (100, 180, 240), (200, 100, 40), (80, 200, 120)],
    "insect":  [(60, 80, 40), (40, 55, 25), (100, 120, 60), (80, 100, 50), (120, 140, 80)],
    "arcane":  [(120, 40, 180), (80, 20, 140), (180, 80, 220), (200, 120, 255), (60, 10, 100)],
}

ITEM_COLORS = {
    "rot":   (200, 50, 40),
    "blau":  (50, 80, 200),
    "gruen": (50, 160, 60),
    "gold":  (210, 180, 50),
    "silber": (180, 190, 200),
    "lila":  (140, 50, 180),
}

# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def clamp(v: int, lo: int = 0, hi: int = 255) -> int:
    return max(lo, min(hi, v))


def color_shift(color: tuple[int, int, int], rng: random.Random,
                amount: int = 15) -> tuple[int, int, int]:
    """Leichte Farbvariation."""
    return tuple(clamp(c + rng.randint(-amount, amount)) for c in color)


def outline_pass(img: Image.Image, color: tuple[int, int, int, int] = (20, 15, 10, 255)):
    """Fuegt schwarze Outline um nicht-transparente Pixel hinzu."""
    px = img.load()
    w, h = img.size
    outline_pixels = []
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > 0:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and px[nx, ny][3] > 30:
                    outline_pixels.append((x, y))
                    break
    for x, y in outline_pixels:
        px[x, y] = color


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SYMMETRIE-GENERATOR (Monster/Kreaturen)
# ═══════════════════════════════════════════════════════════════════════════════

# Silhouette-Seeds: (y_start, y_end, x_min, x_max) pro Koerperteil
# Koordinaten fuer linke Haelfte (0-7), wird gespiegelt
SILHOUETTES = {
    "humanoid": {
        "head":  [(2, 3, 3, 5)],
        "body":  [(4, 5, 3, 6), (5, 6, 4, 6), (6, 8, 3, 6)],
        "legs":  [(9, 11, 3, 5), (9, 11, 5, 7)],
        "arms":  [(5, 8, 2, 3)],
        "eyes":  [(2, 3, 4, 5)],
    },
    "beast": {
        "head":  [(3, 5, 4, 7)],
        "body":  [(5, 7, 2, 7), (7, 9, 3, 7)],
        "legs":  [(9, 12, 2, 4), (9, 12, 5, 7)],
        "arms":  [],
        "eyes":  [(3, 4, 5, 6)],
    },
    "blob": {
        "head":  [],
        "body":  [(3, 6, 3, 7), (6, 9, 2, 7), (9, 11, 3, 7)],
        "legs":  [(11, 13, 4, 6)],
        "arms":  [(5, 7, 1, 3)],
        "eyes":  [(4, 5, 4, 6)],
    },
    "flying": {
        "head":  [(3, 5, 5, 7)],
        "body":  [(5, 8, 4, 7)],
        "legs":  [(8, 10, 5, 7)],
        "arms":  [(3, 7, 1, 4)],  # Fluegel
        "eyes":  [(3, 4, 6, 7)],
    },
    "tall": {
        "head":  [(1, 3, 4, 6)],
        "body":  [(3, 5, 3, 6), (5, 9, 4, 6)],
        "legs":  [(9, 13, 4, 5), (9, 13, 6, 7)],
        "arms":  [(4, 7, 2, 4)],
        "eyes":  [(1, 2, 5, 6)],
    },
}

MONSTER_TYPES = [
    ("undead",    "humanoid"),
    ("undead",    "blob"),
    ("demon",     "humanoid"),
    ("demon",     "tall"),
    ("beast",     "beast"),
    ("beast",     "flying"),
    ("elemental", "blob"),
    ("elemental", "tall"),
    ("insect",    "beast"),
    ("insect",    "flying"),
    ("arcane",    "humanoid"),
    ("arcane",    "blob"),
]

# ── Koerperbau- und Farb-Modifikatoren ────────────────────────────────────────

BODY_MODIFIERS = {
    "normal":  {"width": 0,  "height": 0,  "head_scale": 1.0, "leg_ext": 0,  "fill": 0.85},
    "slim":    {"width": -1, "height": 0,  "head_scale": 1.0, "leg_ext": 0,  "fill": 0.75},
    "stocky":  {"width": 0,  "height": 1,  "head_scale": 0.9, "leg_ext": -1, "fill": 0.92},
    "tall":    {"width": -1, "height": -1, "head_scale": 0.9, "leg_ext": 2,  "fill": 0.80},
    "tiny":    {"width": -1, "height": 1,  "head_scale": 1.1, "leg_ext": -1, "fill": 0.80},
    "bulky":   {"width": 1,  "height": 0,  "head_scale": 0.8, "leg_ext": 0,  "fill": 0.95},
}

COLOR_MODIFIERS = {
    "normal": {"shift": 0,   "saturation": 0},
    "bright": {"shift": 25,  "saturation": 0},
    "dark":   {"shift": -30, "saturation": 0},
    "pale":   {"shift": 15,  "saturation": -20},
    "vivid":  {"shift": 0,   "saturation": 20},
}


def _apply_color_mod(color: tuple[int, int, int], mod: dict) -> tuple[int, int, int]:
    """Wendet Farbmodifikator auf eine RGB-Farbe an."""
    r, g, b = color
    # Helligkeits-Shift
    r = clamp(r + mod["shift"])
    g = clamp(g + mod["shift"])
    b = clamp(b + mod["shift"])
    # Saettigungs-Aenderung (vereinfacht: Abstand zum Durchschnitt skalieren)
    if mod["saturation"] != 0:
        avg = (r + g + b) // 3
        factor = 1.0 + mod["saturation"] / 100.0
        r = clamp(int(avg + (r - avg) * factor))
        g = clamp(int(avg + (g - avg) * factor))
        b = clamp(int(avg + (b - avg) * factor))
    return (r, g, b)


def generate_monster(rng: random.Random, palette_name: str, silhouette_name: str,
                     body_mod: str = "normal", color_mod: str = "normal") -> Image.Image:
    """Generiert ein Monster-Sprite via Symmetrie-Generator."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px = img.load()

    palette = PALETTES[palette_name]
    sil = SILHOUETTES[silhouette_name]
    bmod = BODY_MODIFIERS.get(body_mod, BODY_MODIFIERS["normal"])
    cmod = COLOR_MODIFIERS.get(color_mod, COLOR_MODIFIERS["normal"])
    fill_prob = bmod["fill"]

    # Hauptfarben waehlen
    body_color = rng.choice(palette)
    detail_color = rng.choice([c for c in palette if c != body_color] or palette)
    eye_color = (220, 220, 60) if palette_name != "arcane" else (200, 60, 220)
    # Farbmodifikator anwenden
    body_color = _apply_color_mod(body_color, cmod)
    detail_color = _apply_color_mod(detail_color, cmod)

    half = TILE // 2  # 8

    def mirror_draw(x: int, y: int, color: tuple[int, int, int]):
        """Zeichnet Pixel und sein Spiegelbild."""
        if 0 <= x < half and 0 <= y < TILE:
            c = color_shift(color, rng, 10)
            px[x, y] = (*c, 255)
            mx = TILE - 1 - x
            px[mx, y] = (*c, 255)

    # Koerperteile zeichnen
    for part_name, regions in sil.items():
        color = eye_color if part_name == "eyes" else (
            detail_color if part_name in ("arms", "legs") else body_color
        )
        for (y1, y2, x1, x2) in regions:
            # Leichte Zufalls-Variation der Grenzen
            y1v = y1 + rng.randint(-1, 0) + bmod["height"]
            y2v = y2 + rng.randint(0, 1) + bmod["height"]
            x1v = max(0, x1 + rng.randint(-1, 1) + bmod["width"])
            x2v = min(half, x2 + rng.randint(-1, 1) - bmod["width"])
            # Beinverlaengerung
            if part_name == "legs":
                y2v = min(TILE - 1, y2v + bmod["leg_ext"])
            for y in range(max(0, y1v), min(TILE, y2v)):
                for x in range(x1v, x2v):
                    if rng.random() < fill_prob:
                        mirror_draw(x, y, color)

    # Zufaellige Detail-Pixel (Textur)
    for _ in range(rng.randint(3, 8)):
        x = rng.randint(1, half - 1)
        y = rng.randint(1, TILE - 2)
        if px[x, y][3] > 0:
            mirror_draw(x, y, detail_color)

    outline_pass(img)
    return img


def generate_monster_sized(rng: random.Random, palette_name: str, silhouette_name: str,
                           body_mod: str = "normal", color_mod: str = "normal",
                           size_px: int = 16) -> Image.Image:
    """Monster-Sprite in beliebiger Groesse (16/24/32/48).

    Groessere Sprites haben proportional mehr Detail-Pixel.
    """
    if size_px <= 16:
        return generate_monster(rng, palette_name, silhouette_name, body_mod, color_mod)

    img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    px = img.load()

    palette = PALETTES.get(palette_name, PALETTES["beast"])
    sil = SILHOUETTES.get(silhouette_name, SILHOUETTES["humanoid"])
    bmod = BODY_MODIFIERS.get(body_mod, BODY_MODIFIERS["normal"])
    cmod = COLOR_MODIFIERS.get(color_mod, COLOR_MODIFIERS["normal"])
    fill_prob = bmod["fill"]
    scale = size_px / 16.0

    body_color = rng.choice(palette)
    detail_color = rng.choice([c for c in palette if c != body_color] or palette)
    eye_color = (220, 220, 60) if palette_name != "arcane" else (200, 60, 220)
    body_color = _apply_color_mod(body_color, cmod)
    detail_color = _apply_color_mod(detail_color, cmod)

    half = size_px // 2

    def mirror_draw(x: int, y: int, color: tuple[int, int, int]):
        if 0 <= x < half and 0 <= y < size_px:
            c = color_shift(color, rng, 10)
            px[x, y] = (*c, 255)
            mx = size_px - 1 - x
            px[mx, y] = (*c, 255)

    for part_name, regions in sil.items():
        color = eye_color if part_name == "eyes" else (
            detail_color if part_name in ("arms", "legs") else body_color
        )
        for (y1, y2, x1, x2) in regions:
            sy1 = int(y1 * scale) + rng.randint(-1, 0) + bmod["height"]
            sy2 = int(y2 * scale) + rng.randint(0, 1) + bmod["height"]
            sx1 = max(0, int(x1 * scale) + rng.randint(-1, 1) + bmod["width"])
            sx2 = min(half, int(x2 * scale) + rng.randint(-1, 1) - bmod["width"])
            if part_name == "legs":
                sy2 = min(size_px - 1, sy2 + int(bmod["leg_ext"] * scale))
            for y in range(max(0, sy1), min(size_px, sy2)):
                for x in range(sx1, sx2):
                    if rng.random() < fill_prob:
                        mirror_draw(x, y, color)

    # Detail-Pixel (mehr bei groesseren Sprites)
    detail_count = int(rng.randint(3, 8) * scale * scale)
    for _ in range(detail_count):
        x = rng.randint(1, half - 1)
        y = rng.randint(1, size_px - 2)
        if px[x, y][3] > 0:
            mirror_draw(x, y, detail_color)

    # Extra-Details fuer groessere Sprites: Musterung/Textur
    if size_px >= 24:
        for _ in range(int(4 * scale)):
            x = rng.randint(2, half - 2)
            y = rng.randint(2, size_px - 3)
            if px[x, y][3] > 0:
                highlight = tuple(clamp(c + 30) for c in body_color)
                mirror_draw(x, y, highlight)

    if size_px >= 32:
        # Schuppen/Streifen-Muster
        for y in range(int(3 * scale), int(10 * scale), max(2, int(scale))):
            for x in range(int(3 * scale), half, max(2, int(1.5 * scale))):
                if 0 <= x < half and 0 <= y < size_px and px[x, y][3] > 0:
                    if rng.random() < 0.3:
                        shadow = tuple(clamp(c - 25) for c in body_color)
                        mirror_draw(x, y, shadow)

    outline_pass(img)
    return img


def generate_monsters(rng: random.Random, count: int) -> list[tuple[str, Image.Image]]:
    """Generiert count Monster-Sprites."""
    results = []
    for i in range(count):
        palette_name, sil_name = MONSTER_TYPES[i % len(MONSTER_TYPES)]
        sprite = generate_monster(rng, palette_name, sil_name)
        name = f"monster_gen_{palette_name}_{sil_name}_{i + 1:03d}.png"
        results.append((name, sprite))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 1b. HUMANOIDER-RASSEN-GENERATOR (20 verschiedene Rassen)
# ═══════════════════════════════════════════════════════════════════════════════

# Jede Rasse definiert: skin, hair, eyes, clothing, height, width, features
HUMANOID_RACES = {
    "human": {
        "skin": (210, 170, 130), "hair": (80, 50, 30), "eyes": (60, 100, 180),
        "tunic": (120, 60, 40), "pants": (70, 55, 45), "boots": (50, 35, 25),
        "head_h": 4, "body_h": 4, "leg_h": 4, "width": 6,
        "features": [],  # baseline
    },
    "elf": {
        "skin": (230, 210, 185), "hair": (200, 190, 140), "eyes": (80, 200, 160),
        "tunic": (40, 100, 60), "pants": (50, 80, 50), "boots": (60, 50, 35),
        "head_h": 3, "body_h": 4, "leg_h": 5, "width": 5,
        "features": ["pointed_ears"],
    },
    "dwarf": {
        "skin": (200, 155, 120), "hair": (140, 80, 30), "eyes": (100, 80, 60),
        "tunic": (100, 100, 110), "pants": (80, 70, 60), "boots": (60, 50, 40),
        "head_h": 4, "body_h": 5, "leg_h": 3, "width": 7,
        "features": ["beard", "helmet"],
    },
    "orc": {
        "skin": (80, 130, 60), "hair": (30, 30, 30), "eyes": (200, 50, 30),
        "tunic": (100, 70, 40), "pants": (70, 50, 30), "boots": (50, 40, 30),
        "head_h": 4, "body_h": 5, "leg_h": 3, "width": 8,
        "features": ["tusks", "brow_ridge"],
    },
    "goblin": {
        "skin": (100, 160, 60), "hair": (0, 0, 0), "eyes": (220, 200, 30),
        "tunic": (80, 60, 40), "pants": (60, 50, 35), "boots": (40, 30, 20),
        "head_h": 5, "body_h": 3, "leg_h": 3, "width": 5,
        "features": ["big_ears", "big_nose"],
    },
    "hobgoblin": {
        "skin": (160, 100, 50), "hair": (30, 20, 15), "eyes": (200, 160, 30),
        "tunic": (80, 80, 90), "pants": (60, 60, 65), "boots": (40, 40, 45),
        "head_h": 4, "body_h": 4, "leg_h": 4, "width": 7,
        "features": ["flat_nose", "armor_plates"],
    },
    "gnome": {
        "skin": (220, 190, 160), "hair": (180, 140, 80), "eyes": (60, 140, 200),
        "tunic": (140, 40, 40), "pants": (100, 80, 50), "boots": (80, 60, 30),
        "head_h": 5, "body_h": 3, "leg_h": 2, "width": 5,
        "features": ["big_nose", "pointy_hat"],
    },
    "halfling": {
        "skin": (220, 180, 140), "hair": (150, 100, 50), "eyes": (80, 120, 60),
        "tunic": (80, 120, 60), "pants": (100, 80, 50), "boots": (0, 0, 0),
        "head_h": 4, "body_h": 3, "leg_h": 3, "width": 5,
        "features": ["curly_hair", "bare_feet"],
    },
    "tiefling": {
        "skin": (160, 60, 70), "hair": (20, 10, 30), "eyes": (255, 200, 30),
        "tunic": (40, 20, 50), "pants": (30, 15, 40), "boots": (20, 10, 25),
        "head_h": 4, "body_h": 4, "leg_h": 4, "width": 6,
        "features": ["horns", "tail"],
    },
    "dragonborn": {
        "skin": (60, 100, 140), "hair": (0, 0, 0), "eyes": (255, 180, 30),
        "tunic": (100, 80, 50), "pants": (80, 60, 40), "boots": (60, 50, 35),
        "head_h": 4, "body_h": 5, "leg_h": 3, "width": 7,
        "features": ["snout", "scales", "neck_frill"],
    },
    "kobold": {
        "skin": (140, 100, 50), "hair": (0, 0, 0), "eyes": (255, 220, 30),
        "tunic": (60, 50, 40), "pants": (50, 40, 30), "boots": (0, 0, 0),
        "head_h": 5, "body_h": 3, "leg_h": 2, "width": 4,
        "features": ["snout", "horn_small", "tail_short"],
    },
    "bugbear": {
        "skin": (140, 100, 60), "hair": (100, 70, 40), "eyes": (200, 160, 30),
        "tunic": (80, 60, 40), "pants": (60, 45, 30), "boots": (50, 35, 25),
        "head_h": 4, "body_h": 5, "leg_h": 3, "width": 8,
        "features": ["fur_body", "big_ears"],
    },
    "gnoll": {
        "skin": (160, 130, 80), "hair": (100, 70, 40), "eyes": (200, 60, 30),
        "tunic": (80, 60, 40), "pants": (60, 50, 35), "boots": (0, 0, 0),
        "head_h": 5, "body_h": 4, "leg_h": 3, "width": 6,
        "features": ["snout", "mane", "spots"],
    },
    "lizardfolk": {
        "skin": (60, 120, 60), "hair": (0, 0, 0), "eyes": (220, 200, 30),
        "tunic": (80, 70, 50), "pants": (0, 0, 0), "boots": (0, 0, 0),
        "head_h": 4, "body_h": 4, "leg_h": 4, "width": 6,
        "features": ["snout", "scales", "tail", "crest"],
    },
    "drow": {
        "skin": (60, 50, 70), "hair": (230, 230, 240), "eyes": (200, 30, 50),
        "tunic": (30, 20, 40), "pants": (25, 15, 35), "boots": (20, 10, 25),
        "head_h": 3, "body_h": 4, "leg_h": 5, "width": 5,
        "features": ["pointed_ears", "white_hair"],
    },
    "ogre": {
        "skin": (170, 140, 90), "hair": (60, 40, 25), "eyes": (150, 100, 30),
        "tunic": (80, 60, 40), "pants": (70, 50, 35), "boots": (50, 40, 30),
        "head_h": 4, "body_h": 5, "leg_h": 3, "width": 9,
        "features": ["brow_ridge", "underbite", "belly"],
    },
    "troll_humanoid": {
        "skin": (60, 120, 70), "hair": (30, 50, 30), "eyes": (200, 200, 30),
        "tunic": (50, 80, 50), "pants": (40, 60, 40), "boots": (0, 0, 0),
        "head_h": 3, "body_h": 4, "leg_h": 5, "width": 5,
        "features": ["long_nose", "long_arms", "claws"],
    },
    "minotaur": {
        "skin": (120, 80, 50), "hair": (80, 50, 30), "eyes": (200, 30, 30),
        "tunic": (90, 70, 40), "pants": (70, 55, 35), "boots": (0, 0, 0),
        "head_h": 5, "body_h": 4, "leg_h": 3, "width": 8,
        "features": ["bull_horns", "snout", "hooves"],
    },
    "skeleton_humanoid": {
        "skin": (220, 210, 190), "hair": (0, 0, 0), "eyes": (200, 50, 30),
        "tunic": (0, 0, 0), "pants": (0, 0, 0), "boots": (0, 0, 0),
        "head_h": 4, "body_h": 4, "leg_h": 4, "width": 5,
        "features": ["bones_only", "skull_face"],
    },
    "zombie_humanoid": {
        "skin": (120, 140, 100), "hair": (60, 50, 40), "eyes": (180, 200, 60),
        "tunic": (80, 60, 50), "pants": (60, 50, 40), "boots": (40, 35, 30),
        "head_h": 4, "body_h": 4, "leg_h": 4, "width": 6,
        "features": ["wounds", "shamble", "torn_clothes"],
    },
}


def _hpx(img: Image.Image, x: int, y: int, c: tuple, rng: random.Random = None):
    """Sicherer Pixel-Setter fuer Humanoide mit optionaler Farbvariation."""
    if 0 <= x < img.width and 0 <= y < img.height:
        if rng:
            c = color_shift(c, rng, 8)
        if len(c) == 3:
            c = (*c, 255)
        img.load()[x, y] = c


def _shade3(base: tuple[int, int, int]) -> tuple:
    """3-Tone Palette: (hi, mid, lo) aus Basisfarbe — wie Chibi-System."""
    return (
        tuple(clamp(c + 45) for c in base),
        base,
        tuple(clamp(c - 50) for c in base),
    )


def _lighting_pass(img: Image.Image) -> None:
    """Post-Processing: Top-Light + Ambient-Occlusion + Rim-Light.

    Lichtquelle: oben-links. Jeder sichtbare Pixel bekommt:
    - Top-Highlight: oberste Zeile einer Region heller (+20)
    - Bottom-Shadow: unterste Zeile dunkler (-25)
    - Left-Rim: linker Rand leicht heller (+12, Rim-Light)
    - Right-Shadow: rechter Rand dunkler (-18, Schattenseite)
    - AO: Pixel mit vielen Nachbarn leicht dunkler (eingeklemmt)
    """
    w, h = img.size
    px = img.load()
    # Erst alle Farben lesen, dann modifizieren (vermeidet Leseraenderung)
    orig = {}
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 30:
                orig[(x, y)] = (r, g, b, a)

    for (x, y), (r, g, b, a) in orig.items():
        shift = 0
        # Nachbar-Analyse
        has_above = (x, y - 1) in orig
        has_below = (x, y + 1) in orig
        has_left = (x - 1, y) in orig
        has_right = (x + 1, y) in orig

        # Top-Light: oberster Pixel einer Spalte bekommt Highlight
        if not has_above:
            shift += 22
        # Bottom-Shadow: unterster Pixel bekommt Shadow
        if not has_below:
            shift -= 12
        # Left Rim-Light (Lichtquelle links-oben)
        if not has_left:
            shift += 14
        # Right-Shadow (Schattenseite)
        if not has_right:
            shift -= 20
        # Ambient Occlusion: viele Nachbarn = eingeklemmt = dunkler
        neighbors = sum([has_above, has_below, has_left, has_right])
        if neighbors == 4:
            shift -= 8  # Komplett umgeben → leicht dunkler

        if shift != 0:
            px[x, y] = (clamp(r + shift), clamp(g + shift), clamp(b + shift), a)


def generate_humanoid_race(rng: random.Random, race_name: str,
                           size_px: int = 16) -> Image.Image:
    """Erzeugt einen einzigartigen Humanoiden einer bestimmten Rasse.

    Jede Rasse hat eigene Proportionen, Farben und besondere Merkmale.
    Verwendet 3-Tone-Shading (hi/mid/lo) + post-processing Lighting-Pass.
    """
    race = HUMANOID_RACES.get(race_name, HUMANOID_RACES["human"])
    img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    sc = size_px / 16.0

    features = race["features"]

    # 3-Tone-Paletten fuer alle Farbzonen
    sk_hi, sk_mid, sk_lo = _shade3(race["skin"])
    hr_hi, hr_mid, hr_lo = _shade3(race["hair"])
    tu_hi, tu_mid, tu_lo = _shade3(race["tunic"])
    pa_hi, pa_mid, pa_lo = _shade3(race["pants"])
    bt_hi, bt_mid, bt_lo = _shade3(race["boots"])
    eyes = race["eyes"]

    head_h = race["head_h"]
    body_h = race["body_h"]
    leg_h = race["leg_h"]
    w = race["width"]

    # Proportionen auf Canvas mappen
    total = head_h + body_h + leg_h
    y_head = max(1, int((16 - total) * sc / 2))
    y_body = y_head + int(head_h * sc)
    y_legs = y_body + int(body_h * sc)
    y_bot = min(int(size_px - 1), y_legs + int(leg_h * sc))

    cx = size_px // 2
    hw = max(2, int(w * sc / 2))

    # ── KOPF ──────────────────────────────────────────────────────
    head_w = max(2, int(hw * 0.8))
    head_mid_y = y_head + max(1, (y_body - y_head) // 2)

    if "skull_face" in features:
        bone_hi, bone_mid, bone_lo = _shade3((220, 210, 190))
        for y in range(y_head, y_body):
            for x in range(cx - head_w, cx + head_w):
                c = bone_hi if y == y_head else (bone_lo if y >= y_body - 1 else bone_mid)
                _hpx(img, x, y, c, rng)
        _hpx(img, cx - max(1, head_w // 2), y_head + int(1 * sc), (20, 5, 5), None)
        _hpx(img, cx + max(1, head_w // 2) - 1, y_head + int(1 * sc), (20, 5, 5), None)
        jaw_y = y_body - 1
        for x in range(cx - head_w + 1, cx + head_w - 1):
            if (x + jaw_y) % 2 == 0:
                _hpx(img, x, jaw_y, bone_lo, rng)
    else:
        for y in range(y_head, y_body):
            for x in range(cx - head_w, cx + head_w):
                # 3-Tone: oben=hi, mitte=mid, unten=lo
                if y == y_head:
                    c = sk_hi
                elif y >= y_body - 1:
                    c = sk_lo
                else:
                    c = sk_mid
                # Seitenrand dunkler
                if x == cx - head_w or x == cx + head_w - 1:
                    c = sk_lo
                _hpx(img, x, y, c, rng)

        # Haare mit 3-Tone
        if race["hair"] != (0, 0, 0) or "white_hair" in features:
            if "white_hair" in features:
                hr_hi, hr_mid, hr_lo = _shade3((230, 230, 240))
            for x in range(cx - head_w, cx + head_w):
                # Haar-Highlight in Mitte, dunkel an Seiten
                if abs(x - cx) <= 1:
                    _hpx(img, x, y_head, hr_hi, rng)
                else:
                    _hpx(img, x, y_head, hr_mid, rng)
            if head_h >= 4:
                for x in range(cx - head_w + 1, cx + head_w - 1):
                    _hpx(img, x, max(0, y_head - 1), hr_mid, rng)
            if "curly_hair" in features:
                _hpx(img, cx - head_w - 1, y_head, hr_lo, rng)
                _hpx(img, cx + head_w, y_head, hr_lo, rng)
                _hpx(img, cx - head_w, y_head - 1, hr_mid, rng)
                _hpx(img, cx + head_w - 1, y_head - 1, hr_mid, rng)

        # Augen (leuchten — kein Shading)
        eye_y = y_head + max(1, int(head_h * sc * 0.4))
        # Weisser Augapfel + farbige Pupille
        _hpx(img, cx - max(1, head_w // 2), eye_y, (240, 240, 240), None)
        _hpx(img, cx + max(1, head_w // 2) - 1, eye_y, (240, 240, 240), None)
        # Pupille 1px darunter oder gleich (bei kleinem Kopf)
        if head_h >= 4:
            pupil_y = eye_y
            _hpx(img, cx - max(1, head_w // 2), pupil_y, eyes, None)
            _hpx(img, cx + max(1, head_w // 2) - 1, pupil_y, eyes, None)

    # ── GESICHTS-FEATURES ─────────────────────────────────────────
    eye_y = y_head + max(1, int(head_h * sc * 0.4))

    if "pointed_ears" in features:
        ear_y = y_head + int(1 * sc)
        _hpx(img, cx - head_w - 1, ear_y, sk_mid, rng)
        _hpx(img, cx + head_w, ear_y, sk_lo, rng)
        _hpx(img, cx - head_w - 1, ear_y - 1, sk_hi, rng)
        _hpx(img, cx + head_w, ear_y - 1, sk_mid, rng)

    if "big_ears" in features:
        ear_y = y_head + int(1 * sc)
        for dy in range(int(2 * sc)):
            c = sk_hi if dy == 0 else sk_lo
            _hpx(img, cx - head_w - 1, ear_y + dy, c, rng)
            _hpx(img, cx + head_w, ear_y + dy, sk_lo, rng)
        _hpx(img, cx - head_w - 2, ear_y, sk_mid, rng)
        _hpx(img, cx + head_w + 1, ear_y, sk_lo, rng)

    if "tusks" in features:
        tusk_hi, tusk_mid, tusk_lo = _shade3((240, 230, 200))
        tusk_y = y_body - 1
        _hpx(img, cx - head_w + 1, tusk_y, tusk_hi, None)
        _hpx(img, cx + head_w - 2, tusk_y, tusk_mid, None)
        _hpx(img, cx - head_w + 1, tusk_y + 1, tusk_mid, None)
        _hpx(img, cx + head_w - 2, tusk_y + 1, tusk_lo, None)

    if "big_nose" in features:
        _hpx(img, cx, eye_y + 1, sk_lo, None)
        _hpx(img, cx, eye_y + 2, sk_lo, None)

    if "long_nose" in features:
        for dy in range(int(2 * sc)):
            _hpx(img, cx, eye_y + 1 + dy, sk_lo, None)

    if "flat_nose" in features:
        _hpx(img, cx - 1, eye_y + 1, sk_lo, None)
        _hpx(img, cx, eye_y + 1, sk_lo, None)

    if "brow_ridge" in features:
        for x in range(cx - head_w + 1, cx + head_w - 1):
            _hpx(img, x, eye_y - 1, sk_lo, rng)

    if "snout" in features:
        sy = eye_y + 1
        _hpx(img, cx - 1, sy, sk_mid, rng)
        _hpx(img, cx, sy, sk_hi, rng)
        _hpx(img, cx + 1, sy, sk_lo, rng)
        _hpx(img, cx, sy + 1, sk_lo, rng)
        _hpx(img, cx - 1, sy + 1, (20, 15, 10), None)
        _hpx(img, cx + 1, sy + 1, (20, 15, 10), None)

    if "underbite" in features:
        jaw_y = y_body - 1
        for x in range(cx - head_w, cx + head_w):
            _hpx(img, x, jaw_y, sk_lo, rng)
        _hpx(img, cx - head_w + 1, jaw_y + 1, sk_lo, rng)
        _hpx(img, cx + head_w - 2, jaw_y + 1, sk_lo, rng)

    if "beard" in features:
        beard_c = race["hair"] if race["hair"] != (0, 0, 0) else (140, 80, 30)
        bd_hi, bd_mid, bd_lo = _shade3(beard_c)
        beard_start = y_body - 1
        for dy in range(int(3 * sc)):
            beard_w = max(1, head_w - dy)
            for x in range(cx - beard_w, cx + beard_w):
                if rng.random() < 0.7:
                    c = bd_hi if dy == 0 else (bd_lo if dy >= 2 else bd_mid)
                    _hpx(img, x, beard_start + dy, c, rng)

    if "horns" in features:
        hn_hi, hn_mid, hn_lo = _shade3((60, 30, 20))
        _hpx(img, cx - head_w, y_head - 1, hn_mid, rng)
        _hpx(img, cx + head_w - 1, y_head - 1, hn_lo, rng)
        _hpx(img, cx - head_w - 1, y_head - 2, hn_hi, rng)
        _hpx(img, cx + head_w, y_head - 2, hn_mid, rng)

    if "bull_horns" in features:
        hn_hi, hn_mid, hn_lo = _shade3((80, 60, 40))
        for dx in range(int(3 * sc)):
            c = hn_hi if dx == 0 else (hn_lo if dx >= 2 else hn_mid)
            _hpx(img, cx - head_w - dx, y_head - 1, c, rng)
            _hpx(img, cx + head_w - 1 + dx, y_head - 1, hn_lo, rng)
        _hpx(img, cx - head_w - int(2 * sc), y_head - 2, hn_hi, rng)
        _hpx(img, cx + head_w + int(2 * sc) - 1, y_head - 2, hn_lo, rng)

    if "horn_small" in features:
        _hpx(img, cx, max(0, y_head - 1), (220, 200, 150), rng)

    if "neck_frill" in features:
        frill_hi = tuple(clamp(c + 50) for c in race["skin"])
        frill_lo = tuple(clamp(c + 10) for c in race["skin"])
        fy = y_body - 1
        for dx in range(-1, 2):
            _hpx(img, cx - head_w - 1 + dx, fy, frill_hi, rng)
            _hpx(img, cx + head_w + dx, fy, frill_lo, rng)

    if "crest" in features:
        crest_hi = tuple(clamp(c + 70) for c in race["skin"])
        crest_lo = tuple(clamp(c + 30) for c in race["skin"])
        for dy in range(int(3 * sc)):
            c = crest_hi if dy == 0 else crest_lo
            _hpx(img, cx, max(0, y_head - 1 - dy), c, rng)

    if "mane" in features:
        mn_c = race["hair"] if race["hair"] != (0, 0, 0) else (100, 70, 40)
        mn_hi, mn_mid, mn_lo = _shade3(mn_c)
        for dy in range(int(3 * sc)):
            _hpx(img, cx - head_w - 1, y_head + dy, mn_hi, rng)
            _hpx(img, cx + head_w, y_head + dy, mn_lo, rng)
        for dx in range(head_w * 2):
            _hpx(img, cx - head_w + dx, max(0, y_head - 1), mn_mid, rng)

    if "pointy_hat" in features:
        ht_hi, ht_mid, ht_lo = _shade3(race["tunic"])
        hat_base = y_head
        for x in range(cx - head_w, cx + head_w):
            _hpx(img, x, hat_base, ht_lo, rng)
        for dy in range(1, int(3 * sc)):
            hw_hat = max(1, head_w - dy)
            for x in range(cx - hw_hat, cx + hw_hat):
                c = ht_hi if abs(x - cx) <= 1 else ht_mid
                _hpx(img, x, hat_base - dy, c, rng)

    if "helmet" in features:
        hel_hi, hel_mid, hel_lo = _shade3((150, 150, 160))
        for x in range(cx - head_w, cx + head_w):
            c = hel_hi if abs(x - cx) <= 1 else hel_lo
            _hpx(img, x, y_head, c, rng)
        _hpx(img, cx, max(0, y_head - 1), hel_hi, rng)

    # ── KOERPER ───────────────────────────────────────────────────
    if "bones_only" in features:
        bn_hi, bn_mid, bn_lo = _shade3((220, 210, 190))
        for y in range(y_body, y_legs):
            _hpx(img, cx, y, bn_mid, rng)
        for y in range(y_body, y_legs, max(1, int(2 * sc))):
            for x in range(cx - hw + 1, cx + hw - 1):
                c = bn_hi if x < cx else bn_lo
                _hpx(img, x, y, c, rng)
        _hpx(img, cx - hw, y_body, bn_hi, rng)
        _hpx(img, cx + hw - 1, y_body, bn_lo, rng)
    else:
        body_rows = max(1, y_legs - y_body)
        for y in range(y_body, y_legs):
            frac = (y - y_body) / max(1, body_rows - 1)
            if "belly" in features:
                bw = hw + int(frac * 2 * sc)
            else:
                bw = hw - int((1 - frac) * sc * 0.5)
            bw = max(2, bw)
            for x in range(cx - bw, cx + bw):
                # Vertikaler Gradient: oben hi, unten lo
                if y == y_body:
                    c = tu_hi
                elif y >= y_legs - 1:
                    c = tu_lo
                else:
                    c = tu_mid
                # Horizontaler Gradient: Mitte heller, Raender dunkler
                dx_from_center = abs(x - cx)
                if dx_from_center >= bw - 1:
                    c = tu_lo
                elif dx_from_center == 0 and y <= y_body + 1:
                    c = tu_hi
                _hpx(img, x, y, c, rng)

        if "armor_plates" in features:
            pl_hi = (180, 180, 195)
            pl_lo = (120, 120, 135)
            for y in range(y_body, y_legs, max(1, int(2 * sc))):
                for x in range(cx - hw + 1, cx + hw - 1):
                    if rng.random() < 0.3:
                        c = pl_hi if y == y_body else pl_lo
                        _hpx(img, x, y, c, rng)

        if "fur_body" in features:
            fur_c = race["hair"] if race["hair"] != (0, 0, 0) else (100, 70, 40)
            f_hi, f_mid, f_lo = _shade3(fur_c)
            for y in range(y_body, y_legs):
                for x in range(cx - hw, cx + hw):
                    if rng.random() < 0.35:
                        c = f_hi if y < y_body + 1 else (f_lo if rng.random() < 0.4 else f_mid)
                        _hpx(img, x, y, c, rng)

        if "scales" in features:
            sc_dark = tuple(clamp(c - 25) for c in race["skin"])
            sc_light = tuple(clamp(c + 15) for c in race["skin"])
            for y in range(y_body, y_legs):
                for x in range(cx - hw, cx + hw):
                    if (x + y) % 2 == 0 and rng.random() < 0.4:
                        c = sc_light if (x + y) % 4 == 0 else sc_dark
                        _hpx(img, x, y, c, rng)

        if "spots" in features:
            sp_dark = tuple(clamp(c - 40) for c in race["skin"])
            for _ in range(int(5 * sc)):
                sx = rng.randint(cx - hw + 1, cx + hw - 2)
                sy = rng.randint(y_body, y_legs - 1)
                _hpx(img, sx, sy, sp_dark, rng)

        if "wounds" in features:
            for _ in range(int(3 * sc)):
                wx = rng.randint(cx - hw + 1, cx + hw - 2)
                wy = rng.randint(y_body, y_legs - 1)
                _hpx(img, wx, wy, (140, 30, 20), rng)
                if rng.random() < 0.5:
                    _hpx(img, wx + 1, wy, (100, 20, 15), rng)

        if "torn_clothes" in features:
            for _ in range(int(4 * sc)):
                tx = rng.randint(cx - hw + 1, cx + hw - 2)
                ty = rng.randint(y_body, y_legs - 1)
                _hpx(img, tx, ty, sk_lo, rng)

    # ── ARME ──────────────────────────────────────────────────────
    arm_start = y_body + int(1 * sc)
    arm_end = y_body + int(body_h * sc * 0.8)
    if "long_arms" in features:
        arm_end = y_legs + int(2 * sc)

    if "bones_only" in features:
        bn_hi, bn_mid, bn_lo = _shade3((220, 210, 190))
        for y in range(arm_start, arm_end):
            _hpx(img, cx - hw - 1, y, bn_hi, rng)
            _hpx(img, cx + hw, y, bn_lo, rng)
    else:
        for y in range(arm_start, arm_end):
            frac = (y - arm_start) / max(1, arm_end - arm_start - 1)
            c = sk_hi if frac < 0.3 else (sk_lo if frac > 0.7 else sk_mid)
            _hpx(img, cx - hw - 1, y, c, rng)  # Linker Arm (Lichtseite)
            c_r = sk_mid if frac < 0.3 else sk_lo  # Rechter Arm (Schatten)
            _hpx(img, cx + hw, y, c_r, rng)

    if "claws" in features:
        cl_hi, cl_mid, cl_lo = _shade3((200, 180, 130))
        _hpx(img, cx - hw - 2, arm_end, cl_hi, None)
        _hpx(img, cx + hw + 1, arm_end, cl_lo, None)
        _hpx(img, cx - hw - 1, arm_end + 1, cl_mid, None)
        _hpx(img, cx + hw, arm_end + 1, cl_lo, None)

    # ── BEINE ─────────────────────────────────────────────────────
    if "bones_only" in features:
        bn_hi, bn_mid, bn_lo = _shade3((220, 210, 190))
        for y in range(y_legs, y_bot):
            _hpx(img, cx - max(1, int(hw * 0.4)), y, bn_hi, rng)
            _hpx(img, cx + max(0, int(hw * 0.4)), y, bn_lo, rng)
    else:
        pants_c = race["pants"] if race["pants"] != (0, 0, 0) else race["skin"]
        p_hi, p_mid, p_lo = _shade3(pants_c)
        for y in range(y_legs, y_bot):
            frac = (y - y_legs) / max(1, y_bot - y_legs - 1)
            leg_sep = max(1, int(hw * 0.3))
            # Linkes Bein (Lichtseite)
            for x in range(cx - hw + 1, cx - leg_sep):
                c = p_hi if frac < 0.3 else (p_lo if frac > 0.7 else p_mid)
                _hpx(img, x, y, c, rng)
            # Rechtes Bein (Schattenseite)
            for x in range(cx + leg_sep, cx + hw - 1):
                c = p_mid if frac < 0.3 else p_lo
                _hpx(img, x, y, c, rng)

    # Schuhe/Hufe
    if "hooves" in features:
        hf_hi, hf_mid, hf_lo = _shade3((60, 40, 30))
        for x in range(cx - hw, cx + hw):
            c = hf_hi if x < cx else hf_lo
            _hpx(img, x, y_bot, c, rng)
    elif "bare_feet" in features:
        _hpx(img, cx - hw, y_bot, sk_mid, rng)
        _hpx(img, cx + hw - 1, y_bot, sk_lo, rng)
        _hpx(img, cx - hw - 1, y_bot, sk_hi, rng)
        _hpx(img, cx + hw, y_bot, sk_lo, rng)
    elif race["boots"] != (0, 0, 0):
        for x in range(cx - hw, cx + hw):
            c = bt_hi if x < cx else bt_lo
            _hpx(img, x, y_bot, c, rng)
            if y_bot - 1 >= y_legs:
                _hpx(img, x, y_bot - 1, bt_mid, rng)

    # ── SCHWANZ ───────────────────────────────────────────────────
    if "tail" in features:
        for i in range(int(4 * sc)):
            frac = i / max(1, int(4 * sc) - 1)
            c = sk_mid if frac < 0.5 else sk_lo
            _hpx(img, cx + hw + i, y_legs + i // 2, c, rng)

    if "tail_short" in features:
        _hpx(img, cx + hw, y_legs, sk_mid, rng)
        _hpx(img, cx + hw + 1, y_legs + 1, sk_lo, rng)

    # ── SHAMBLE (Zombie) ──────────────────────────────────────────
    if "shamble" in features:
        for dx in range(int(3 * sc)):
            frac = dx / max(1, int(3 * sc) - 1)
            c = sk_mid if frac < 0.5 else sk_lo
            _hpx(img, cx + hw + dx, arm_start + int(1 * sc), c, rng)

    # ── POST-PROCESSING ──────────────────────────────────────────
    _lighting_pass(img)
    outline_pass(img)
    return img


def _humanoid_apply_walk_frame(base: Image.Image, race: dict,
                               frame_idx: int, size_px: int = 16) -> Image.Image:
    """Erzeugt einen Walk-Cycle-Frame durch Pixel-Region-Verschiebung.

    Walk-Cycle: 6 Frames
      0: Kontakt rechts   1: Tiefpunkt     2: Durchschwung
      3: Kontakt links    4: Tiefpunkt     5: Durchschwung
    """
    scale = size_px / 16.0
    result = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
    src = base.load()
    dst = result.load()

    head_h = race["head_h"]
    body_h = race["body_h"]
    total = head_h + body_h + race["leg_h"]
    y_head_start = max(1, int((16 - total) * scale / 2))
    y_body_start = y_head_start + int(head_h * scale)
    y_leg_start = y_body_start + int(body_h * scale)
    cx = size_px // 2
    hw = max(2, int(race["width"] * scale / 2))

    # Walk-Keyframes: (body_dy, head_bob, leg_l_dx, leg_l_dy, leg_r_dx, leg_r_dy, arm_l_dy, arm_r_dy, lean)
    _WK = [
        (0,  0,   0, 0,   0, 0,   0, 0,  0),    # 0: neutral
        (-1, 0,  -1, -1,  1, 0,  -1, 1,  0),    # 1: schritt L vor, R zurueck
        (0,  0,  -1, 0,   1, -1,  0, 0,  0),    # 2: durchschwung
        (0,  0,   0, 0,   0, 0,   0, 0,  0),    # 3: neutral
        (-1, 0,   1, 0,  -1, -1,  1, -1, 0),    # 4: schritt R vor, L zurueck
        (0,  0,   1, -1, -1, 0,   0, 0,  0),    # 5: durchschwung
    ]
    kf = _WK[frame_idx % len(_WK)]
    body_dy, head_bob, ll_dx, ll_dy, lr_dx, lr_dy, al_dy, ar_dy, lean = kf

    for y in range(size_px):
        for x in range(size_px):
            r, g, b, a = src[x, y]
            if a == 0:
                continue
            dx, dy = 0, 0

            if y < y_body_start:
                # Kopf: body-bob + head-bob + lean
                dy = body_dy + head_bob
                dx = lean
            elif y < y_leg_start:
                # Oberkörper
                if x < cx - hw:
                    # Linker Arm
                    dy = body_dy + al_dy
                    dx = lean
                elif x >= cx + hw:
                    # Rechter Arm
                    dy = body_dy + ar_dy
                    dx = lean
                else:
                    # Torso
                    dy = body_dy
                    dx = lean
            else:
                # Beine
                if x < cx:
                    dx, dy = ll_dx, ll_dy
                else:
                    dx, dy = lr_dx, lr_dy

            nx = max(0, min(size_px - 1, x + dx))
            ny = max(0, min(size_px - 1, y + dy))
            # Nicht ueberschreiben wenn Ziel schon belegt (Prioritaet: weiter unten)
            if dst[nx, ny][3] == 0 or a > dst[nx, ny][3]:
                dst[nx, ny] = (r, g, b, a)

    return result


def generate_humanoid_walk_cycle(rng: random.Random, race_name: str,
                                  size_px: int = 16,
                                  num_frames: int = 6) -> list[Image.Image]:
    """Erzeugt einen kompletten Walk-Cycle fuer eine Humanoide Rasse.

    Returns: Liste von num_frames PIL Images.
    """
    race = HUMANOID_RACES.get(race_name, HUMANOID_RACES["human"])
    base = generate_humanoid_race(rng, race_name, size_px)
    frames = []
    for i in range(num_frames):
        frame = _humanoid_apply_walk_frame(base, race, i, size_px)
        frames.append(frame)
    return frames


def generate_humanoid_races(rng: random.Random,
                            size_px: int = 16) -> list[tuple[str, Image.Image]]:
    """Generiert alle 20 Humanoiden-Rassen (Einzelbilder)."""
    results = []
    for race_name in HUMANOID_RACES:
        sprite = generate_humanoid_race(rng, race_name, size_px)
        fname = f"humanoid_{race_name}.png"
        results.append((fname, sprite))
    return results


def generate_humanoid_races_animated(rng: random.Random,
                                      size_px: int = 16,
                                      num_frames: int = 6
                                      ) -> list[tuple[str, list[Image.Image]]]:
    """Generiert alle 20 Humanoiden-Rassen mit Walk-Cycle-Animation.

    Returns: Liste von (name, [frame1, frame2, ...])
    """
    results = []
    for race_name in HUMANOID_RACES:
        frames = generate_humanoid_walk_cycle(rng, race_name, size_px, num_frames)
        results.append((race_name, frames))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 1d. KAMPF-ANIMATIONEN (attack / hit / death) fuer Monster + Humanoide
# ═══════════════════════════════════════════════════════════════════════════════

# -- Kampf-Keyframes (generisch, arbeiten auf beliebigen Sprite-Groessen) ------
# Jeder Keyframe: dict mit dx/dy-Offsets fuer Regionen
# Regionen werden relativ zum Sprite bestimmt (obere Haelfte = Kopf+Torso,
# untere Haelfte = Beine, linke Seite = Arme links, rechte = Arme rechts)

_COMBAT_ATTACK_KF = [
    # Ausholen → Lunge → Impact → Nachschwung → Rueckkehr
    {"body_dx": 0,  "body_dy": 0,  "upper_dx": -1, "upper_dy": 0, "flash": False, "opacity": 255},
    {"body_dx": -1, "body_dy": -1, "upper_dx": -2, "upper_dy": -1, "flash": False, "opacity": 255},
    {"body_dx": 1,  "body_dy": 0,  "upper_dx": 2,  "upper_dy": 0, "flash": False, "opacity": 255},
    {"body_dx": 2,  "body_dy": 0,  "upper_dx": 3,  "upper_dy": 1, "flash": False, "opacity": 255},
    {"body_dx": 1,  "body_dy": 0,  "upper_dx": 1,  "upper_dy": 0, "flash": False, "opacity": 255},
    {"body_dx": 0,  "body_dy": 0,  "upper_dx": 0,  "upper_dy": 0, "flash": False, "opacity": 255},
]

_COMBAT_HIT_KF = [
    # Treffer-Rueckstoss + Flash
    {"body_dx": 0,  "body_dy": 0,  "upper_dx": 0,  "upper_dy": 0,  "flash": False, "opacity": 255},
    {"body_dx": -1, "body_dy": 0,  "upper_dx": -2, "upper_dy": 0,  "flash": True,  "opacity": 255},
    {"body_dx": -2, "body_dy": 1,  "upper_dx": -2, "upper_dy": 1,  "flash": True,  "opacity": 200},
    {"body_dx": -1, "body_dy": 0,  "upper_dx": -1, "upper_dy": 0,  "flash": False, "opacity": 255},
    {"body_dx": 0,  "body_dy": 0,  "upper_dx": 0,  "upper_dy": 0,  "flash": False, "opacity": 255},
]

_COMBAT_DEATH_KF = [
    # Zusammensacken + Ausblenden
    {"body_dx": 0,  "body_dy": 0,  "upper_dx": 0,  "upper_dy": 0,  "squash": 0, "flash": False, "opacity": 255},
    {"body_dx": -1, "body_dy": 0,  "upper_dx": -1, "upper_dy": 1,  "squash": 0, "flash": True,  "opacity": 255},
    {"body_dx": -1, "body_dy": 1,  "upper_dx": -2, "upper_dy": 1,  "squash": 1, "flash": False, "opacity": 220},
    {"body_dx": -2, "body_dy": 2,  "upper_dx": -2, "upper_dy": 2,  "squash": 2, "flash": False, "opacity": 180},
    {"body_dx": -2, "body_dy": 3,  "upper_dx": -2, "upper_dy": 3,  "squash": 3, "flash": False, "opacity": 130},
    {"body_dx": -2, "body_dy": 3,  "upper_dx": -2, "upper_dy": 3,  "squash": 3, "flash": False, "opacity": 70},
]

COMBAT_ANIMS = {
    "attack": _COMBAT_ATTACK_KF,
    "hit":    _COMBAT_HIT_KF,
    "death":  _COMBAT_DEATH_KF,
}


def _apply_combat_frame(base: Image.Image, keyframe: dict) -> Image.Image:
    """Wendet einen generischen Kampf-Keyframe auf ein beliebig grosses Sprite an.

    Funktioniert mit 16px, 24px, 32px, 48px — Regionen werden proportional bestimmt.
    """
    w, h = base.size
    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    src = base.load()
    dst = result.load()

    body_dx = keyframe.get("body_dx", 0)
    body_dy = keyframe.get("body_dy", 0)
    upper_dx = keyframe.get("upper_dx", 0)
    upper_dy = keyframe.get("upper_dy", 0)
    is_flash = keyframe.get("flash", False)
    opacity = keyframe.get("opacity", 255)
    squash = keyframe.get("squash", 0)

    mid_y = h // 2   # Grenze oben/unten
    cx = w // 2       # Mitte horizontal

    for y in range(h):
        for x in range(w):
            r, g, b, a = src[x, y]
            if a == 0:
                continue

            dx, dy = body_dx, body_dy

            if y < mid_y:
                # Obere Haelfte (Kopf + Torso): extra upper_dx/dy + squash
                dx += upper_dx - body_dx
                dy += upper_dy - body_dy + squash
            # Untere Haelfte (Beine): nur body_dx/dy

            nx = max(0, min(w - 1, x + dx))
            ny = max(0, min(h - 1, y + dy))

            a_out = min(a, opacity)
            if is_flash:
                dst[nx, ny] = (min(255, r + 120), min(255, g + 120), min(255, b + 120), a_out)
            else:
                dst[nx, ny] = (r, g, b, a_out)

    return result


def generate_combat_frames(base: Image.Image, anim_name: str) -> list[Image.Image]:
    """Erzeugt Kampf-Animations-Frames (attack/hit/death) aus einem Base-Sprite."""
    keyframes = COMBAT_ANIMS.get(anim_name, _COMBAT_ATTACK_KF)
    return [_apply_combat_frame(base, kf) for kf in keyframes]


def _make_combat_spritesheet(frames: list[Image.Image], scale: int = 4) -> Image.Image:
    """Horizontales Spritesheet fuer beliebig grosse Frames (nicht nur 16px)."""
    if not frames:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    fw, fh = frames[0].size
    cell_w = fw * scale
    cell_h = fh * scale
    padding = 1
    sheet_w = len(frames) * (cell_w + padding) + padding
    sheet_h = cell_h + 2 * padding
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (30, 25, 35, 255))
    for i, frame in enumerate(frames):
        x = padding + i * (cell_w + padding)
        scaled = frame.resize((cell_w, cell_h), Image.NEAREST)
        sheet.paste(scaled, (x, padding), scaled)
    return sheet


def generate_humanoid_combat_anims(rng: random.Random,
                                    size_px: int = 16
                                    ) -> list[tuple[str, Image.Image]]:
    """Erzeugt attack/hit/death Animationen fuer alle 20 Humanoiden-Rassen.

    Speichert Einzelframes + Spritesheets.
    Returns: Liste von (filename, image)
    """
    results = []
    for race_name in HUMANOID_RACES:
        base = generate_humanoid_race(rng, race_name, size_px)
        for anim_name in ("attack", "hit", "death"):
            frames = generate_combat_frames(base, anim_name)
            # Einzelframes
            for i, frame in enumerate(frames):
                fname = f"humanoid_{race_name}_{anim_name}_{i:02d}.png"
                results.append((fname, frame))
            # Spritesheet
            sheet = _make_combat_spritesheet(frames)
            sheet_name = f"humanoid_{race_name}_{anim_name}_sheet.png"
            results.append((sheet_name, sheet))
    return results


def generate_monster_combat_anims(rng: random.Random,
                                   size_px: int = 16
                                   ) -> list[tuple[str, Image.Image]]:
    """Erzeugt attack/hit/death Animationen fuer alle 12 Symmetrie-Monster-Typen.

    Returns: Liste von (filename, image)
    """
    results = []
    for palette_name, sil_name in MONSTER_TYPES:
        base = generate_monster(rng, palette_name, sil_name)
        tag = f"monster_{palette_name}_{sil_name}"
        for anim_name in ("attack", "hit", "death"):
            frames = generate_combat_frames(base, anim_name)
            for i, frame in enumerate(frames):
                fname = f"{tag}_{anim_name}_{i:02d}.png"
                results.append((fname, frame))
            sheet = _make_combat_spritesheet(frames)
            results.append((f"{tag}_{anim_name}_sheet.png", sheet))
    return results


def generate_sized_monster_combat_anims(rng: random.Random
                                         ) -> list[tuple[str, Image.Image]]:
    """Erzeugt Kampf-Animationen fuer groessere Monster (L/H/G).

    Erzeugt je 1 Monster in 24px, 32px, 48px mit attack/hit/death.
    """
    results = []
    size_configs = [
        (24, "beast", "beast", "L"),
        (32, "demon", "tall", "H"),
        (48, "elemental", "blob", "G"),
    ]
    for size_px, palette, sil, size_label in size_configs:
        base = generate_monster_sized(rng, palette, sil, size_px=size_px)
        tag = f"monster_{palette}_{sil}_{size_label}"
        for anim_name in ("attack", "hit", "death"):
            frames = generate_combat_frames(base, anim_name)
            for i, frame in enumerate(frames):
                fname = f"{tag}_{anim_name}_{i:02d}.png"
                results.append((fname, frame))
            sheet = _make_combat_spritesheet(frames)
            results.append((f"{tag}_{anim_name}_sheet.png", sheet))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 1c. NPC-ROLLEN-GENERATOR (10 Rollen × Rassen)
# ═══════════════════════════════════════════════════════════════════════════════

NPC_ROLES = {
    "merchant": {
        "tunic": (140, 100, 50), "pants": (90, 70, 45), "boots": (60, 40, 25),
        "hat": "hood", "accessory": "pouch", "label": "Haendler",
    },
    "guard": {
        "tunic": (100, 100, 115), "pants": (70, 65, 60), "boots": (50, 40, 35),
        "hat": "helmet", "accessory": "spear", "label": "Wache",
    },
    "priest": {
        "tunic": (210, 210, 220), "pants": (180, 180, 190), "boots": (100, 85, 60),
        "hat": "hood", "accessory": "holy_symbol", "label": "Priester",
    },
    "sage": {
        "tunic": (70, 50, 120), "pants": (55, 40, 90), "boots": (45, 30, 60),
        "hat": "pointy_hat", "accessory": "book", "label": "Gelehrter",
    },
    "innkeeper": {
        "tunic": (160, 120, 70), "pants": (100, 80, 55), "boots": (70, 50, 35),
        "hat": "none", "accessory": "apron", "label": "Wirt",
    },
    "thief": {
        "tunic": (50, 45, 40), "pants": (40, 38, 35), "boots": (30, 25, 20),
        "hat": "hood", "accessory": "dagger", "label": "Dieb",
    },
    "noble": {
        "tunic": (130, 30, 50), "pants": (100, 25, 40), "boots": (60, 20, 30),
        "hat": "crown", "accessory": "cape", "label": "Adliger",
    },
    "farmer": {
        "tunic": (130, 110, 70), "pants": (90, 80, 55), "boots": (60, 50, 35),
        "hat": "straw_hat", "accessory": "pitchfork", "label": "Bauer",
    },
    "blacksmith": {
        "tunic": (80, 70, 60), "pants": (60, 55, 50), "boots": (50, 40, 35),
        "hat": "none", "accessory": "hammer", "label": "Schmied",
    },
    "healer": {
        "tunic": (200, 200, 210), "pants": (170, 170, 180), "boots": (90, 80, 60),
        "hat": "none", "accessory": "cross", "label": "Heiler",
    },
}


def generate_npc(rng: random.Random, race_name: str, role_name: str,
                 size_px: int = 16) -> Image.Image:
    """Erzeugt einen NPC: Humanoid-Rasse + Rollen-Kleidung/Accessoire."""
    role = NPC_ROLES.get(role_name, NPC_ROLES["merchant"])
    # Rasse als Basis, aber Kleidung ueberschreiben
    race = dict(HUMANOID_RACES.get(race_name, HUMANOID_RACES["human"]))
    race["tunic"] = role["tunic"]
    race["pants"] = role["pants"]
    race["boots"] = role["boots"]

    # Features anpassen fuer Rolle
    features = list(race["features"])
    hat = role["hat"]
    if hat == "pointy_hat" and "pointy_hat" not in features:
        features.append("pointy_hat")
    elif hat == "helmet" and "helmet" not in features:
        features.append("helmet")
    race["features"] = features

    # Temporaer HUMANOID_RACES patchen (via dict)
    old = HUMANOID_RACES.get("_npc_tmp")
    HUMANOID_RACES["_npc_tmp"] = race
    img = generate_humanoid_race(rng, "_npc_tmp", size_px)
    if old is None:
        del HUMANOID_RACES["_npc_tmp"]
    else:
        HUMANOID_RACES["_npc_tmp"] = old

    px = img.load()
    sc = size_px / 16.0
    cx = size_px // 2
    total = race["head_h"] + race["body_h"] + race["leg_h"]
    y_head = max(1, int((16 - total) * sc / 2))
    y_body = y_head + int(race["head_h"] * sc)
    hw = max(2, int(race["width"] * sc / 2))

    # Accessoire zeichnen
    acc = role["accessory"]
    if acc == "spear":
        # Speer rechts neben dem Koerper
        spear_c = (160, 140, 100)
        tip_c = (190, 195, 200)
        sx = cx + hw + 1
        for y in range(max(0, y_head - 2), min(size_px, y_body + int(race["body_h"] * sc) + 2)):
            _hpx(img, sx, y, spear_c, rng)
        _hpx(img, sx, max(0, y_head - 2), tip_c, None)
        _hpx(img, sx, max(0, y_head - 1), tip_c, None)
    elif acc == "pouch":
        # Beutel an der Seite
        pouch_c = (120, 90, 40)
        py_ = y_body + int(race["body_h"] * sc * 0.5)
        _hpx(img, cx + hw, py_, pouch_c, rng)
        _hpx(img, cx + hw + 1, py_, pouch_c, rng)
        _hpx(img, cx + hw, py_ + 1, tuple(clamp(c - 30) for c in pouch_c), rng)
    elif acc == "holy_symbol":
        # Goldenes Symbol auf der Brust
        sym_c = (220, 200, 80)
        sy_ = y_body + 1
        _hpx(img, cx, sy_, sym_c, None)
        _hpx(img, cx - 1, sy_ + 1, sym_c, None)
        _hpx(img, cx + 1, sy_ + 1, sym_c, None)
        _hpx(img, cx, sy_ + 1, sym_c, None)
    elif acc == "book":
        # Buch unter dem Arm
        book_c = (120, 30, 30)
        by_ = y_body + int(race["body_h"] * sc * 0.4)
        _hpx(img, cx - hw - 1, by_, book_c, rng)
        _hpx(img, cx - hw - 2, by_, book_c, rng)
        _hpx(img, cx - hw - 1, by_ + 1, tuple(clamp(c - 30) for c in book_c), rng)
    elif acc == "apron":
        # Schuerze ueber Koerper
        apron_c = (220, 210, 190)
        for y in range(y_body + 1, y_body + int(race["body_h"] * sc)):
            _hpx(img, cx - 1, y, apron_c, rng)
            _hpx(img, cx, y, apron_c, rng)
            _hpx(img, cx + 1, y, apron_c, rng)
    elif acc == "dagger":
        # Dolch an der Seite
        blade_c = (190, 195, 200)
        hilt_c = (100, 70, 30)
        dy_ = y_body + int(race["body_h"] * sc * 0.3)
        _hpx(img, cx + hw + 1, dy_, hilt_c, None)
        _hpx(img, cx + hw + 1, dy_ + 1, blade_c, None)
        _hpx(img, cx + hw + 1, dy_ + 2, blade_c, None)
    elif acc == "cape":
        # Umhang hinten (dunkelrot)
        cape_hi = (160, 40, 60)
        cape_lo = (90, 20, 35)
        for y in range(y_body, y_body + int((race["body_h"] + race["leg_h"]) * sc)):
            if y < size_px:
                c = cape_hi if y < y_body + 2 else cape_lo
                _hpx(img, cx - hw - 1, y, c, rng)
                _hpx(img, cx + hw, y, c, rng)
    elif acc == "pitchfork":
        # Heugabel
        stick_c = (130, 100, 50)
        tip_c = (160, 155, 150)
        sx = cx + hw + 1
        for y in range(max(0, y_head - 1), min(size_px, y_body + int(race["body_h"] * sc) + 2)):
            _hpx(img, sx, y, stick_c, rng)
        _hpx(img, sx - 1, max(0, y_head - 1), tip_c, None)
        _hpx(img, sx, max(0, y_head - 1), tip_c, None)
        _hpx(img, sx + 1, max(0, y_head - 1), tip_c, None)
    elif acc == "hammer":
        # Schmiedehammer
        handle_c = (100, 70, 40)
        head_c = (140, 140, 150)
        sx = cx + hw + 1
        for y in range(y_body, y_body + int(race["body_h"] * sc)):
            _hpx(img, sx, y, handle_c, rng)
        hy_ = y_body
        _hpx(img, sx - 1, hy_, head_c, None)
        _hpx(img, sx, hy_, head_c, None)
        _hpx(img, sx + 1, hy_, head_c, None)
    elif acc == "cross":
        # Heiler-Kreuz auf Brust
        cross_c = (220, 50, 50)
        cy_ = y_body + 1
        _hpx(img, cx, cy_, cross_c, None)
        _hpx(img, cx - 1, cy_ + 1, cross_c, None)
        _hpx(img, cx, cy_ + 1, cross_c, None)
        _hpx(img, cx + 1, cy_ + 1, cross_c, None)
        _hpx(img, cx, cy_ + 2, cross_c, None)

    # Hood/Straw-Hat/Crown zeichnen (ueber dem Kopf)
    if hat == "hood":
        hood_c = tuple(clamp(c - 20) for c in role["tunic"])
        head_w = max(2, int(hw * 0.8))
        for x in range(cx - head_w, cx + head_w):
            _hpx(img, x, y_head, hood_c, rng)
        _hpx(img, cx - head_w, y_head + 1, hood_c, rng)
        _hpx(img, cx + head_w - 1, y_head + 1, hood_c, rng)
    elif hat == "straw_hat":
        hat_c = (200, 180, 100)
        hat_lo = (160, 140, 70)
        head_w = max(2, int(hw * 0.8))
        for x in range(cx - head_w - 1, cx + head_w + 1):
            _hpx(img, x, y_head, hat_c, rng)
        for x in range(cx - head_w, cx + head_w):
            _hpx(img, x, max(0, y_head - 1), hat_lo, rng)
    elif hat == "crown":
        crown_c = (220, 200, 60)
        crown_gem = (200, 40, 40)
        head_w = max(2, int(hw * 0.8))
        for x in range(cx - head_w, cx + head_w):
            _hpx(img, x, y_head, crown_c, rng)
        _hpx(img, cx - 1, max(0, y_head - 1), crown_c, None)
        _hpx(img, cx + 1, max(0, y_head - 1), crown_c, None)
        _hpx(img, cx, max(0, y_head - 1), crown_gem, None)

    outline_pass(img)
    return img


def generate_all_npcs(rng: random.Random,
                      races: list[str] | None = None,
                      size_px: int = 16) -> list[tuple[str, Image.Image]]:
    """Erzeugt NPCs: jede Rolle mit mehreren Rassen-Varianten."""
    if races is None:
        races = ["human", "elf", "dwarf", "orc", "halfling",
                 "gnome", "tiefling", "drow", "dragonborn", "goblin"]
    results = []
    for role_name in NPC_ROLES:
        for race_name in races:
            sprite = generate_npc(rng, race_name, role_name, size_px)
            fname = f"npc_{role_name}_{race_name}.png"
            results.append((fname, sprite))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 1d. ERWEITERTE ITEMS (30 Templates)
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_item_sprite(draw: "ImageDraw.Draw", px, item_type: str,
                      color: tuple[int, int, int], rng: random.Random,
                      size: int = 16) -> None:
    """Zeichnet ein einzelnes Item-Sprite mit 3-Tone-Shading."""
    hi = tuple(clamp(c + 45) for c in color)
    mid = color
    lo = tuple(clamp(c - 50) for c in color)
    metal_hi = (210, 215, 220)
    metal_mid = (160, 165, 170)
    metal_lo = (110, 112, 115)
    wood_hi = (160, 120, 70)
    wood_mid = (120, 85, 45)
    wood_lo = (80, 55, 25)
    s = size / 16.0

    def p(x, y, c):
        if 0 <= x < size and 0 <= y < size:
            if len(c) == 3:
                c = (*c, 255)
            px[x, y] = c

    if item_type == "axe":
        # Stiel
        for y in range(int(4*s), int(14*s)):
            p(int(8*s), y, wood_mid)
        # Klinge
        for dy in range(int(4*s)):
            p(int(9*s), int(3*s) + dy, metal_hi)
            p(int(10*s), int(3*s) + dy, metal_mid)
            p(int(11*s), int(4*s) + dy, metal_lo)
        p(int(9*s), int(2*s), metal_hi)
    elif item_type == "bow":
        # Bogen-Kurve
        for dy in range(int(10*s)):
            bx = int(6*s) + (1 if dy < 3 or dy > 7 else (2 if dy < 2 or dy > 8 else 0))
            p(bx, int(3*s) + dy, wood_hi if dy < 5 else wood_lo)
        # Sehne
        for dy in range(int(10*s)):
            p(int(9*s), int(3*s) + dy, (200, 190, 170))
    elif item_type == "spear":
        # Langer Schaft
        for y in range(int(2*s), int(15*s)):
            p(int(8*s), y, wood_mid)
        # Spitze
        p(int(8*s), int(1*s), metal_hi)
        p(int(7*s), int(2*s), metal_mid)
        p(int(9*s), int(2*s), metal_lo)
    elif item_type == "staff":
        # Stab mit Orb
        for y in range(int(4*s), int(15*s)):
            p(int(8*s), y, wood_hi if y < int(8*s) else wood_lo)
        # Orb oben
        p(int(7*s), int(2*s), hi)
        p(int(8*s), int(2*s), hi)
        p(int(9*s), int(2*s), mid)
        p(int(7*s), int(3*s), mid)
        p(int(8*s), int(3*s), hi)
        p(int(9*s), int(3*s), lo)
    elif item_type == "mace":
        # Stiel
        for y in range(int(6*s), int(14*s)):
            p(int(8*s), y, wood_mid)
        # Kopf
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                c = metal_hi if dy < 0 else (metal_lo if dy > 0 else metal_mid)
                p(int(8*s) + dx, int(4*s) + dy, c)
        p(int(8*s), int(3*s), metal_hi)
    elif item_type == "dagger":
        # Klinge
        for y in range(int(3*s), int(9*s)):
            p(int(8*s), y, metal_hi if y < int(6*s) else metal_mid)
        # Griff
        for y in range(int(9*s), int(12*s)):
            p(int(8*s), y, wood_mid)
        p(int(7*s), int(9*s), hi)
        p(int(9*s), int(9*s), lo)
    elif item_type == "flail":
        # Stiel
        for y in range(int(8*s), int(14*s)):
            p(int(7*s), y, wood_mid)
        # Kette
        for y in range(int(5*s), int(8*s)):
            p(int(8*s), y, metal_lo)
        # Kopf
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                p(int(9*s) + dx, int(3*s) + dy, metal_hi if dx + dy < 0 else metal_lo)
    elif item_type == "crossbow":
        # Schaft
        for x in range(int(5*s), int(12*s)):
            p(x, int(8*s), wood_mid)
        # Buegel
        for dy in range(-3, 4):
            bx = int(5*s) - (0 if abs(dy) < 2 else 1)
            p(bx, int(8*s) + dy, wood_hi if dy < 0 else wood_lo)
        # Bolzen
        for x in range(int(6*s), int(12*s)):
            p(x, int(7*s), metal_mid)
        p(int(12*s), int(7*s), metal_hi)
    elif item_type == "warhammer":
        # Stiel
        for y in range(int(5*s), int(14*s)):
            p(int(8*s), y, wood_mid)
        # Hammerkopf (breit)
        for dx in range(-2, 3):
            c = metal_hi if dx < 0 else (metal_lo if dx > 0 else metal_mid)
            p(int(8*s) + dx, int(3*s), c)
            p(int(8*s) + dx, int(4*s), tuple(clamp(v - 15) for v in c))
    elif item_type == "whip":
        # Griff
        for y in range(int(10*s), int(14*s)):
            p(int(6*s), y, wood_mid)
        # Peitschenschnur (kurvig)
        coords = [(7,9),(8,8),(9,7),(10,6),(11,5),(11,4),(10,3)]
        for bx, by in coords:
            p(int(bx*s), int(by*s), (100, 60, 30))
    elif item_type == "chainmail":
        # Kettenhemd-Form
        for y in range(int(4*s), int(12*s)):
            w_ = 3 if y < int(8*s) else 2
            for x in range(int(8*s) - w_, int(8*s) + w_ + 1):
                c = metal_hi if (x + y) % 2 == 0 else metal_lo
                p(x, y, c)
        # Schultern
        p(int(5*s), int(4*s), metal_mid)
        p(int(11*s), int(4*s), metal_mid)
    elif item_type == "platemail":
        # Plattenpanzer
        for y in range(int(3*s), int(12*s)):
            w_ = 3 if int(5*s) <= y <= int(9*s) else 2
            for x in range(int(8*s) - w_, int(8*s) + w_ + 1):
                if y < int(6*s):
                    c = metal_hi
                elif y < int(9*s):
                    c = metal_mid
                else:
                    c = metal_lo
                p(x, y, c)
        # Kreuz-Emblem
        p(int(8*s), int(5*s), hi)
        p(int(7*s), int(6*s), hi)
        p(int(8*s), int(6*s), hi)
        p(int(9*s), int(6*s), hi)
    elif item_type == "leather_armor":
        # Lederruestung
        leather_hi = (160, 110, 60)
        leather_mid = (120, 80, 40)
        leather_lo = (80, 55, 25)
        for y in range(int(4*s), int(11*s)):
            w_ = 3 if int(5*s) <= y <= int(8*s) else 2
            for x in range(int(8*s) - w_, int(8*s) + w_ + 1):
                c = leather_hi if y < int(7*s) else leather_lo
                if x == int(8*s) - w_ or x == int(8*s) + w_:
                    c = leather_lo
                p(x, y, c)
    elif item_type == "robe":
        # Magier-Robe
        for y in range(int(3*s), int(13*s)):
            w_ = 2 + (1 if y > int(8*s) else 0)
            for x in range(int(8*s) - w_, int(8*s) + w_ + 1):
                c = hi if y < int(6*s) else (lo if y > int(10*s) else mid)
                p(x, y, c)
        # Kapuze
        p(int(7*s), int(2*s), mid)
        p(int(8*s), int(2*s), hi)
        p(int(9*s), int(2*s), lo)
    elif item_type == "buckler":
        # Kleiner Rundschild
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx*dx + dy*dy <= 5:
                    c = metal_hi if dx + dy < 0 else metal_lo
                    p(int(8*s) + dx, int(8*s) + dy, c)
        p(int(8*s), int(8*s), hi)  # Boss
    elif item_type == "gold_pile":
        # Goldhaufen
        gold_hi = (255, 230, 80)
        gold_mid = (220, 190, 50)
        gold_lo = (170, 140, 30)
        for dx in range(-3, 4):
            h_ = 3 - abs(dx) // 2
            for dy in range(h_):
                c = gold_hi if dy == 0 else (gold_lo if dy == h_ - 1 else gold_mid)
                p(int(8*s) + dx, int(12*s) - dy, c)
    elif item_type == "crown":
        crown_c = (220, 200, 60)
        gem_c = (200, 40, 40)
        for x in range(int(5*s), int(12*s)):
            p(x, int(9*s), crown_c)
            p(x, int(10*s), tuple(clamp(c - 30) for c in crown_c))
        # Zacken
        for x in [int(5*s), int(7*s), int(8*s), int(9*s), int(11*s)]:
            p(x, int(8*s), crown_c)
        p(int(8*s), int(7*s), gem_c)
    elif item_type == "chalice":
        # Kelch
        gold_hi = (230, 210, 80)
        gold_lo = (160, 140, 40)
        # Fuss
        for x in range(int(6*s), int(11*s)):
            p(x, int(13*s), gold_lo)
        # Stiel
        p(int(8*s), int(11*s), gold_lo)
        p(int(8*s), int(12*s), gold_lo)
        # Schale
        for x in range(int(5*s), int(12*s)):
            p(x, int(8*s), gold_hi)
            p(x, int(9*s), gold_lo)
        p(int(5*s), int(7*s), gold_hi)
        p(int(11*s), int(7*s), gold_lo)
        # Inhalt (rot = Wein)
        for x in range(int(6*s), int(11*s)):
            p(x, int(7*s), (160, 30, 40))
    elif item_type == "necklace":
        gold_c = (220, 200, 60)
        gem_c = hi
        # Kette
        for dx in range(-3, 4):
            dy = abs(dx) - 1
            p(int(8*s) + dx, int(6*s) + max(0, dy), gold_c)
        # Anhaenger
        p(int(8*s), int(9*s), gem_c)
        p(int(7*s), int(8*s), gold_c)
        p(int(9*s), int(8*s), gold_c)
    elif item_type == "antidote":
        # Flasche mit gruener Fluessigkeit
        glass_c = (180, 200, 180)
        liquid_hi = (80, 220, 80)
        liquid_lo = (40, 140, 40)
        # Flasche
        p(int(8*s), int(4*s), glass_c)
        for y in range(int(5*s), int(12*s)):
            w_ = 1 if y < int(7*s) else 2
            for x in range(int(8*s) - w_, int(8*s) + w_ + 1):
                if x == int(8*s) - w_ or x == int(8*s) + w_:
                    p(x, y, glass_c)
                else:
                    c = liquid_hi if y < int(9*s) else liquid_lo
                    p(x, y, c)
    elif item_type == "bomb":
        # Schwarze Kugel mit Lunte
        bomb_hi = (60, 55, 50)
        bomb_lo = (25, 22, 20)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx*dx + dy*dy <= 5:
                    c = bomb_hi if dx + dy < 0 else bomb_lo
                    p(int(8*s) + dx, int(9*s) + dy, c)
        # Lunte
        p(int(9*s), int(6*s), (180, 140, 80))
        p(int(10*s), int(5*s), (180, 140, 80))
        # Funke
        p(int(10*s), int(4*s), (255, 220, 80))
        p(int(11*s), int(4*s), (255, 180, 50))
    elif item_type == "torch_item":
        # Fackel
        for y in range(int(6*s), int(14*s)):
            p(int(8*s), y, wood_mid)
        # Flamme
        p(int(7*s), int(4*s), (255, 200, 50))
        p(int(8*s), int(3*s), (255, 230, 80))
        p(int(9*s), int(4*s), (255, 160, 30))
        p(int(8*s), int(4*s), (255, 240, 100))
        p(int(8*s), int(5*s), (255, 180, 40))
    elif item_type == "rope":
        # Aufgewickeltes Seil
        rope_hi = (180, 150, 90)
        rope_lo = (120, 95, 55)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if 2 <= dx*dx + dy*dy <= 6:
                    c = rope_hi if (dx + dy) % 2 == 0 else rope_lo
                    p(int(8*s) + dx, int(8*s) + dy, c)
    elif item_type == "lockpick":
        metal_c = (170, 170, 175)
        # Stiel
        for y in range(int(6*s), int(13*s)):
            p(int(8*s), y, metal_c)
        # Haken
        p(int(9*s), int(6*s), metal_c)
        p(int(9*s), int(5*s), metal_c)
        p(int(8*s), int(5*s), metal_c)
        # Griff
        p(int(7*s), int(12*s), metal_lo)
        p(int(9*s), int(12*s), metal_lo)
    elif item_type == "sack":
        sack_hi = (180, 160, 110)
        sack_lo = (120, 105, 70)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if abs(dx) + abs(dy) <= 3:
                    c = sack_hi if dy < 0 else sack_lo
                    p(int(8*s) + dx, int(9*s) + dy, c)
        # Knoten
        p(int(8*s), int(6*s), sack_lo)
        p(int(7*s), int(5*s), sack_hi)
        p(int(9*s), int(5*s), sack_hi)
    elif item_type == "chest_closed":
        wood = (140, 95, 45)
        wood_d = (100, 65, 25)
        metal_c = (180, 175, 165)
        for x in range(int(4*s), int(13*s)):
            for y in range(int(7*s), int(12*s)):
                c = wood if y < int(10*s) else wood_d
                if x == int(4*s) or x == int(12*s):
                    c = wood_d
                p(x, y, c)
        # Deckel
        for x in range(int(4*s), int(13*s)):
            p(x, int(7*s), wood_d)
        # Schloss
        p(int(8*s), int(9*s), metal_c)
        p(int(8*s), int(10*s), metal_c)
    elif item_type == "chest_open":
        wood = (140, 95, 45)
        wood_d = (100, 65, 25)
        gold_c = (220, 200, 60)
        for x in range(int(4*s), int(13*s)):
            for y in range(int(8*s), int(12*s)):
                p(x, y, wood if y < int(10*s) else wood_d)
        # Deckel offen (oben)
        for x in range(int(4*s), int(13*s)):
            p(x, int(6*s), wood)
            p(x, int(5*s), wood_d)
        # Gold drin
        for x in range(int(5*s), int(12*s)):
            p(x, int(8*s), gold_c)
            p(x, int(9*s), tuple(clamp(c - 30) for c in gold_c))
    elif item_type == "chest_trapped":
        wood = (140, 95, 45)
        wood_d = (100, 65, 25)
        trap_c = (200, 50, 40)
        for x in range(int(4*s), int(13*s)):
            for y in range(int(7*s), int(12*s)):
                p(x, y, wood if y < int(10*s) else wood_d)
        for x in range(int(4*s), int(13*s)):
            p(x, int(7*s), wood_d)
        # Rotes Warnsymbol
        p(int(7*s), int(9*s), trap_c)
        p(int(8*s), int(8*s), trap_c)
        p(int(8*s), int(9*s), trap_c)
        p(int(8*s), int(10*s), trap_c)
        p(int(9*s), int(9*s), trap_c)

    # Standard-Item-Fallback fuer unbekannte
    # (nutzt die bestehende generate_items Logik)


EXTENDED_ITEM_TYPES = [
    "axe", "bow", "spear", "staff", "mace", "dagger", "flail",
    "crossbow", "warhammer", "whip",
    "chainmail", "platemail", "leather_armor", "robe", "buckler",
    "gold_pile", "crown", "chalice", "necklace",
    "antidote", "bomb", "torch_item", "rope", "lockpick", "sack",
    "chest_closed", "chest_open", "chest_trapped",
]

EXTENDED_ITEM_COLORS = {
    "normal":  (160, 160, 170),
    "fire":    (200, 80, 30),
    "ice":     (80, 160, 220),
    "poison":  (60, 180, 60),
    "holy":    (220, 200, 80),
    "shadow":  (80, 50, 120),
}


def generate_extended_items(rng: random.Random,
                            size_px: int = 16) -> list[tuple[str, Image.Image]]:
    """Generiert alle erweiterten Item-Sprites mit Farbvarianten."""
    results = []
    for item_type in EXTENDED_ITEM_TYPES:
        for color_name, color in EXTENDED_ITEM_COLORS.items():
            img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            px = img.load()
            _draw_item_sprite(draw, px, item_type, color, rng, size_px)
            outline_pass(img)
            fname = f"item_{item_type}_{color_name}.png"
            results.append((fname, img))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 1e. INTERAKTIVE OBJEKTE (Tueren, Fallen, Moebel-Varianten)
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_object_sprite(px, obj_type: str, rng: random.Random,
                        size: int = 16) -> None:
    """Zeichnet ein interaktives Objekt."""
    s = size / 16.0

    def p(x, y, c):
        xi, yi = int(x), int(y)
        if 0 <= xi < size and 0 <= yi < size:
            if len(c) == 3:
                c = (*c, 255)
            px[xi, yi] = c

    wood_hi = (170, 130, 75)
    wood_mid = (130, 95, 50)
    wood_lo = (90, 60, 30)
    stone_hi = (160, 155, 150)
    stone_mid = (120, 118, 115)
    stone_lo = (80, 78, 75)
    metal_hi = (190, 195, 200)
    metal_mid = (140, 142, 145)
    metal_lo = (95, 97, 100)

    if obj_type == "door_wood":
        for x in range(int(5*s), int(12*s)):
            for y in range(int(2*s), int(14*s)):
                c = wood_hi if x < int(8*s) else wood_lo
                if y == int(2*s) or y == int(13*s):
                    c = wood_lo
                p(x, y, c)
        # Klinke
        p(10*s, 8*s, metal_mid)
        # Scharniere
        p(5*s, 4*s, metal_lo)
        p(5*s, 11*s, metal_lo)
    elif obj_type == "door_metal":
        for x in range(int(5*s), int(12*s)):
            for y in range(int(2*s), int(14*s)):
                c = metal_hi if x < int(8*s) else metal_lo
                if (x + y) % 3 == 0:
                    c = metal_mid  # Nieten-Muster
                p(x, y, c)
        p(10*s, 8*s, (220, 200, 60))  # Goldener Griff
    elif obj_type == "door_barred":
        for x in range(int(5*s), int(12*s)):
            for y in range(int(2*s), int(14*s)):
                p(x, y, wood_mid)
        # Gitter
        for x in range(int(5*s), int(12*s), int(2*s)):
            for y in range(int(2*s), int(14*s)):
                p(x, y, metal_lo)
        for y in range(int(2*s), int(14*s), int(3*s)):
            for x in range(int(5*s), int(12*s)):
                p(x, y, metal_lo)
    elif obj_type == "door_secret":
        # Sieht aus wie Wand
        for x in range(int(4*s), int(13*s)):
            for y in range(int(2*s), int(14*s)):
                c = stone_hi if (x + y) % 5 < 2 else stone_lo
                p(x, y, c)
        # Kaum sichtbarer Riss
        for y in range(int(3*s), int(13*s)):
            p(12*s, y, stone_mid)
    elif obj_type == "trap_pit":
        # Dunkles Loch
        for dx in range(-3, 4):
            for dy in range(-2, 3):
                if abs(dx) + abs(dy) <= 4:
                    depth = abs(dx) + abs(dy)
                    v = max(10, 40 - depth * 10)
                    p(8*s + dx, 8*s + dy, (v, v, v + 5))
        # Rand
        for dx in range(-4, 5):
            for dy in [-3, 3]:
                if abs(dx) <= 4 - abs(dy):
                    p(8*s + dx, 8*s + dy, stone_lo)
    elif obj_type == "trap_spikes":
        # Boden mit Spitzen
        for x in range(int(4*s), int(13*s)):
            p(x, int(12*s), stone_lo)
        spike_c = metal_hi
        for sx in range(int(5*s), int(12*s), int(2*s)):
            p(sx, int(8*s), spike_c)
            p(sx, int(9*s), metal_mid)
            p(sx, int(10*s), metal_mid)
            p(sx, int(11*s), metal_lo)
    elif obj_type == "trap_dart":
        # Wand-Schlitz mit Pfeil
        for y in range(int(6*s), int(11*s)):
            p(3*s, y, stone_lo)
            p(4*s, y, stone_mid)
        # Pfeil
        arrow_c = (160, 140, 100)
        for x in range(int(5*s), int(12*s)):
            p(x, 8*s, arrow_c)
        p(12*s, 7*s, metal_hi)
        p(12*s, 9*s, metal_hi)
        p(13*s, 8*s, metal_hi)
    elif obj_type == "lever_up":
        # Basis
        for x in range(int(6*s), int(11*s)):
            p(x, int(12*s), stone_mid)
            p(x, int(13*s), stone_lo)
        # Stange (oben)
        p(8*s, 6*s, metal_hi)
        p(8*s, 7*s, metal_mid)
        p(8*s, 8*s, metal_mid)
        p(8*s, 9*s, metal_lo)
        p(8*s, 10*s, metal_lo)
        # Griff
        p(7*s, 5*s, metal_hi)
        p(8*s, 5*s, metal_hi)
        p(9*s, 5*s, metal_mid)
    elif obj_type == "lever_down":
        for x in range(int(6*s), int(11*s)):
            p(x, int(12*s), stone_mid)
            p(x, int(13*s), stone_lo)
        # Stange (unten/schraeg)
        p(8*s, 10*s, metal_lo)
        p(9*s, 9*s, metal_mid)
        p(10*s, 8*s, metal_mid)
        p(11*s, 8*s, metal_hi)
    elif obj_type == "altar":
        # Steinblock
        for x in range(int(4*s), int(13*s)):
            for y in range(int(8*s), int(13*s)):
                c = stone_hi if y < int(10*s) else stone_lo
                if x == int(4*s) or x == int(12*s):
                    c = stone_lo
                p(x, y, c)
        # Oberfläche
        for x in range(int(3*s), int(14*s)):
            p(x, int(7*s), stone_hi)
        # Opferschale
        p(7*s, 6*s, metal_mid)
        p(8*s, 6*s, metal_hi)
        p(9*s, 6*s, metal_lo)
        # Flamme
        p(8*s, 5*s, (255, 200, 50))
    elif obj_type == "fountain":
        # Becken
        for dx in range(-3, 4):
            p(8*s + dx, 11*s, stone_mid)
            p(8*s + dx, 12*s, stone_lo)
        p(5*s, 10*s, stone_mid)
        p(11*s, 10*s, stone_lo)
        # Saeule
        p(8*s, 7*s, stone_mid)
        p(8*s, 8*s, stone_mid)
        p(8*s, 9*s, stone_lo)
        # Wasser
        p(7*s, 10*s, (80, 140, 220))
        p(8*s, 10*s, (100, 170, 240))
        p(9*s, 10*s, (70, 120, 200))
        # Tropfen
        p(7*s, 6*s, (120, 180, 240))
        p(9*s, 7*s, (100, 160, 230))
    elif obj_type == "statue":
        # Humanoid-Statue aus Stein
        for y in range(int(3*s), int(6*s)):
            p(8*s, y, stone_hi)
        for y in range(int(6*s), int(10*s)):
            for dx in range(-1, 2):
                c = stone_hi if dx < 0 else stone_lo
                p(8*s + dx, y, c)
        for y in range(int(10*s), int(13*s)):
            p(7*s, y, stone_mid)
            p(9*s, y, stone_lo)
        # Sockel
        for x in range(int(6*s), int(11*s)):
            p(x, 13*s, stone_lo)
    elif obj_type == "pillar":
        for y in range(int(2*s), int(14*s)):
            p(7*s, y, stone_hi)
            p(8*s, y, stone_mid)
            p(9*s, y, stone_lo)
        # Kapitell
        for x in range(int(6*s), int(11*s)):
            p(x, int(2*s), stone_hi)
        # Basis
        for x in range(int(6*s), int(11*s)):
            p(x, int(13*s), stone_lo)
    elif obj_type == "barricade":
        for x in range(int(3*s), int(14*s)):
            for y in range(int(7*s), int(12*s)):
                if rng.random() < 0.7:
                    c = wood_hi if (x + y) % 3 == 0 else wood_lo
                    p(x, y, c)
        # Naegel
        for x in range(int(4*s), int(13*s), int(3*s)):
            p(x, int(8*s), metal_lo)
    elif obj_type == "web":
        web_c = (200, 200, 210, 180)
        web_lo = (160, 160, 170, 120)
        # Diagonale Faeden
        for i in range(int(14*s)):
            p(1*s + i, 1*s + i, web_c)
            p(14*s - i, 1*s + i, web_lo)
        # Horizontale
        for x in range(int(3*s), int(14*s)):
            p(x, 8*s, web_c)
        # Vertikale
        for y in range(int(3*s), int(14*s)):
            p(8*s, y, web_lo)
        # Knoten
        p(8*s, 8*s, (220, 220, 230))


INTERACTIVE_OBJECTS = [
    "door_wood", "door_metal", "door_barred", "door_secret",
    "trap_pit", "trap_spikes", "trap_dart",
    "lever_up", "lever_down",
    "altar", "fountain", "statue", "pillar", "barricade", "web",
]


def generate_interactive_objects(rng: random.Random,
                                 size_px: int = 16) -> list[tuple[str, Image.Image]]:
    """Generiert alle interaktiven Objekt-Sprites."""
    results = []
    for obj_type in INTERACTIVE_OBJECTS:
        img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
        _draw_object_sprite(img.load(), obj_type, rng, size_px)
        outline_pass(img)
        results.append((f"obj_{obj_type}.png", img))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 1f. STATUS-ICONS (12 Zustands-Symbole)
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_status_icon(px, icon_type: str, size: int = 16) -> None:
    """Zeichnet ein 16x16 Status-Icon."""
    s = size / 16.0

    def p(x, y, c):
        xi, yi = int(x), int(y)
        if 0 <= xi < size and 0 <= yi < size:
            if len(c) == 3:
                c = (*c, 255)
            px[xi, yi] = c

    if icon_type == "poison":
        # Grüner Totenkopf
        for dx in range(-2, 3):
            for dy in range(-2, 2):
                p(8*s + dx, 7*s + dy, (60, 180, 60))
        p(7*s, 6*s, (20, 40, 20))  # Auge L
        p(9*s, 6*s, (20, 40, 20))  # Auge R
        p(8*s, 8*s, (20, 40, 20))  # Nase
        # Tropfen
        p(8*s, 11*s, (40, 200, 40))
        p(8*s, 12*s, (30, 160, 30))
    elif icon_type == "burn":
        # Flamme
        colors = [(255, 240, 100), (255, 180, 40), (255, 100, 20), (200, 50, 10)]
        flame = [(8,4), (7,5),(8,5),(9,5), (6,6),(7,6),(8,6),(9,6),(10,6),
                 (7,7),(8,7),(9,7), (7,8),(8,8),(9,8), (8,9),(9,9), (8,10)]
        for i, (fx, fy) in enumerate(flame):
            c = colors[min(i // 5, 3)]
            p(fx*s, fy*s, c)
    elif icon_type == "frozen":
        # Eiskristall
        ice = (120, 200, 255)
        ice_lo = (70, 140, 200)
        # Kreuz
        for d in range(-3, 4):
            p(8*s, 8*s + d, ice)
            p(8*s + d, 8*s, ice)
        # Diagonalen
        for d in range(-2, 3):
            p(8*s + d, 8*s + d, ice_lo)
            p(8*s + d, 8*s - d, ice_lo)
        p(8*s, 8*s, (200, 240, 255))  # Mitte hell
    elif icon_type == "stun":
        # Gelbe Sterne
        star_c = (255, 230, 50)
        star_lo = (200, 180, 30)
        for cx_, cy_ in [(6,5), (10,5), (8,9)]:
            p(cx_*s, cy_*s, star_c)
            p((cx_-1)*s, cy_*s, star_lo)
            p((cx_+1)*s, cy_*s, star_lo)
            p(cx_*s, (cy_-1)*s, star_lo)
            p(cx_*s, (cy_+1)*s, star_lo)
    elif icon_type == "sleep":
        # Z Z Z
        z_c = (150, 180, 220)
        # Grosses Z
        for x in range(int(6*s), int(10*s)):
            p(x, 5*s, z_c)
            p(x, 8*s, z_c)
        p(9*s, 6*s, z_c)
        p(7*s, 7*s, z_c)
        # Kleines z
        for x in range(int(10*s), int(12*s)):
            p(x, 9*s, z_c)
            p(x, 11*s, z_c)
        p(11*s, 10*s, z_c)
    elif icon_type == "shield_buff":
        # Blaues Schild
        sh_hi = (80, 140, 220)
        sh_lo = (40, 80, 160)
        for dx in range(-3, 4):
            h_ = 6 - abs(dx)
            for dy in range(h_):
                c = sh_hi if dx < 0 else sh_lo
                p(8*s + dx, 5*s + dy, c)
        p(8*s, 5*s, (120, 180, 255))
    elif icon_type == "strength_buff":
        # Roter Pfeil nach oben
        arr_c = (220, 60, 40)
        arr_hi = (255, 100, 70)
        for y in range(int(6*s), int(12*s)):
            p(8*s, y, arr_c)
        p(7*s, 7*s, arr_hi)
        p(6*s, 8*s, arr_hi)
        p(9*s, 7*s, arr_c)
        p(10*s, 8*s, arr_c)
        p(8*s, 5*s, arr_hi)
    elif icon_type == "haste":
        # Blauer Blitz
        bolt_c = (80, 180, 255)
        bolt_lo = (40, 120, 200)
        coords = [(9,3),(8,4),(8,5),(7,6),(8,6),(9,6),(10,6),(8,7),(8,8),(7,9),(7,10)]
        for i, (bx, by) in enumerate(coords):
            c = bolt_c if i < 6 else bolt_lo
            p(bx*s, by*s, c)
    elif icon_type == "invisible":
        # Transparenter Umriss
        ghost = (150, 150, 170, 120)
        # Kopf-Umriss
        for dx in range(-1, 2):
            p(8*s + dx, 4*s, ghost)
        p(7*s, 5*s, ghost)
        p(9*s, 5*s, ghost)
        # Koerper-Umriss
        p(7*s, 7*s, ghost)
        p(9*s, 7*s, ghost)
        p(7*s, 8*s, ghost)
        p(9*s, 8*s, ghost)
        # Beine
        p(7*s, 10*s, ghost)
        p(9*s, 10*s, ghost)
    elif icon_type == "blessed":
        # Goldener Heiligenschein
        gold = (255, 230, 80)
        gold_lo = (200, 180, 50)
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                dist = dx*dx + dy*dy
                if 5 <= dist <= 10:
                    p(8*s + dx, 7*s + dy, gold if dy < 0 else gold_lo)
        p(8*s, 4*s, (255, 255, 200))
    elif icon_type == "cursed":
        # Rotes Pentagram
        red = (200, 30, 40)
        red_lo = (140, 20, 30)
        # Kreis
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                dist = dx*dx + dy*dy
                if 7 <= dist <= 10:
                    p(8*s + dx, 8*s + dy, red_lo)
        # Stern-Linien
        star_pts = [(8,4),(6,7),(10,7),(5,11),(11,11)]
        for fx, fy in star_pts:
            p(fx*s, fy*s, red)
    elif icon_type == "bleeding":
        # Rote Tropfen
        blood = (180, 20, 20)
        blood_lo = (120, 10, 10)
        for cy_ in [5, 8, 11]:
            cx_ = 7 if cy_ == 8 else (9 if cy_ == 11 else 8)
            p(cx_*s, cy_*s, blood)
            p(cx_*s, (cy_+1)*s, blood_lo)
            p((cx_-1)*s, (cy_+1)*s, blood_lo)


STATUS_ICONS = [
    "poison", "burn", "frozen", "stun", "sleep",
    "shield_buff", "strength_buff", "haste",
    "invisible", "blessed", "cursed", "bleeding",
]


def generate_status_icons(rng: random.Random,
                          size_px: int = 16) -> list[tuple[str, Image.Image]]:
    """Generiert alle Status-Icons."""
    results = []
    for icon_type in STATUS_ICONS:
        img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
        _draw_status_icon(img.load(), icon_type, size_px)
        outline_pass(img)
        results.append((f"icon_{icon_type}.png", img))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH-GENERIERUNG: Alle fehlenden Sprites auf einmal erzeugen
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# 1g. SCHÄTZE & MAGISCHE GEGENSTÄNDE
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_treasure_sprite(px, treasure_type: str, rng: random.Random,
                          size: int = 16) -> None:
    """Zeichnet einen Schatz-Sprite."""
    s = size / 16.0

    def p(x, y, c):
        xi, yi = int(x), int(y)
        if 0 <= xi < size and 0 <= yi < size:
            px[xi, yi] = (*c, 255) if len(c) == 3 else c

    gold_hi = (255, 235, 90)
    gold_mid = (220, 195, 55)
    gold_lo = (170, 145, 30)
    silver_hi = (220, 225, 230)
    silver_mid = (175, 180, 185)
    silver_lo = (130, 133, 138)

    if treasure_type == "coin_pile":
        # Kleiner Muenzhaufen
        for layer in range(3):
            w_ = 4 - layer
            y_ = int((11 - layer) * s)
            for dx in range(-w_, w_ + 1):
                c = gold_hi if layer == 0 else (gold_mid if layer == 1 else gold_lo)
                if rng.random() < 0.8:
                    p(8*s + dx, y_, c)
        # Einzelne Muenze oben
        p(8*s, int(8*s), gold_hi)
        p(9*s, int(9*s), gold_mid)
    elif treasure_type == "coin_stack":
        # Muenzstapel (Turm)
        for y in range(int(6*s), int(13*s)):
            for dx in range(-1, 2):
                c = gold_hi if dx < 0 else (gold_lo if dx > 0 else gold_mid)
                p(8*s + dx, y, c)
        p(7*s, int(6*s), gold_hi)
        p(9*s, int(6*s), gold_lo)
    elif treasure_type == "gold_bar":
        # Goldbarren (Trapez)
        for y in range(int(8*s), int(12*s)):
            w_ = 3 if y < int(10*s) else 4
            for dx in range(-w_, w_ + 1):
                frac = (y - int(8*s)) / max(1, int(3*s))
                c = gold_hi if frac < 0.3 else (gold_lo if frac > 0.7 else gold_mid)
                if abs(dx) >= w_:
                    c = gold_lo
                p(8*s + dx, y, c)
    elif treasure_type == "silver_bar":
        for y in range(int(8*s), int(12*s)):
            w_ = 3 if y < int(10*s) else 4
            for dx in range(-w_, w_ + 1):
                frac = (y - int(8*s)) / max(1, int(3*s))
                c = silver_hi if frac < 0.3 else (silver_lo if frac > 0.7 else silver_mid)
                if abs(dx) >= w_:
                    c = silver_lo
                p(8*s + dx, y, c)
    elif treasure_type == "diamond":
        # Geschliffener Diamant
        dia_hi = (220, 240, 255)
        dia_mid = (170, 200, 240)
        dia_lo = (120, 150, 200)
        # Oberteil (Dreieck)
        for dy in range(int(4*s)):
            w_ = dy + 1
            for dx in range(-w_, w_ + 1):
                c = dia_hi if dx <= 0 else dia_lo
                p(8*s + dx, int(5*s) + dy, c)
        # Unterteil (umgekehrtes Dreieck)
        for dy in range(int(3*s)):
            w_ = int(3*s) - dy
            for dx in range(-w_, w_ + 1):
                c = dia_mid if abs(dx) < w_ else dia_lo
                p(8*s + dx, int(9*s) + dy, c)
        # Glanzpunkt
        p(7*s, int(6*s), (255, 255, 255))
    elif treasure_type == "ruby":
        ruby_hi = (255, 60, 70)
        ruby_mid = (200, 30, 40)
        ruby_lo = (140, 15, 25)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if abs(dx) + abs(dy) <= 3:
                    c = ruby_hi if dx + dy < 0 else (ruby_lo if dx + dy > 1 else ruby_mid)
                    p(8*s + dx, 8*s + dy, c)
        p(7*s, 7*s, (255, 120, 130))  # Glanz
    elif treasure_type == "sapphire":
        sap_hi = (60, 100, 255)
        sap_mid = (30, 60, 200)
        sap_lo = (15, 35, 140)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if abs(dx) + abs(dy) <= 3:
                    c = sap_hi if dx + dy < 0 else (sap_lo if dx + dy > 1 else sap_mid)
                    p(8*s + dx, 8*s + dy, c)
        p(7*s, 7*s, (130, 170, 255))
    elif treasure_type == "emerald":
        em_hi = (50, 220, 80)
        em_mid = (30, 160, 50)
        em_lo = (15, 100, 30)
        # Sechseck-Form
        for dx in range(-2, 3):
            for dy in range(-3, 4):
                if abs(dx) + abs(dy) // 2 <= 2:
                    c = em_hi if dy < 0 else (em_lo if dy > 1 else em_mid)
                    p(8*s + dx, 8*s + dy, c)
        p(7*s, 6*s, (100, 255, 130))
    elif treasure_type == "pearl":
        pearl_hi = (245, 240, 235)
        pearl_mid = (215, 210, 205)
        pearl_lo = (180, 175, 170)
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx*dx + dy*dy <= 5:
                    c = pearl_hi if dx + dy < 0 else (pearl_lo if dx + dy > 1 else pearl_mid)
                    p(8*s + dx, 8*s + dy, c)
        p(7*s, 7*s, (255, 252, 248))  # Glanz
    elif treasure_type == "tiara":
        g_hi = (240, 220, 80)
        g_lo = (180, 160, 40)
        gem = (100, 60, 200)
        # Band
        for x in range(int(4*s), int(13*s)):
            p(x, int(9*s), g_hi if x < int(8*s) else g_lo)
        # Zacken
        for x in [int(5*s), int(8*s), int(11*s)]:
            p(x, int(8*s), g_hi)
        p(int(8*s), int(7*s), gem)
        p(int(5*s), int(8*s), gem)
        p(int(11*s), int(8*s), gem)
    elif treasure_type == "scepter":
        # Koenigszepter
        for y in range(int(5*s), int(14*s)):
            c = gold_hi if y < int(8*s) else gold_lo
            p(8*s, y, c)
        # Orb oben
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                if abs(dx) + abs(dy) <= 1:
                    c = (200, 60, 220) if dx + dy == 0 else (140, 30, 160)
                    p(8*s + dx, int(3*s) + dy, c)
        p(8*s, int(3*s), (230, 100, 255))
    elif treasure_type == "signet_ring":
        g_c = (220, 200, 60)
        g_lo = (160, 140, 30)
        # Ring
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if 3 <= dx*dx + dy*dy <= 5:
                    p(8*s + dx, 9*s + dy, g_c if dy < 0 else g_lo)
        # Siegel
        p(8*s, 7*s, (180, 30, 30))
    elif treasure_type == "reliquary":
        # Reliquienschrein
        wood_hi = (160, 120, 60)
        wood_lo = (100, 70, 30)
        for x in range(int(5*s), int(12*s)):
            for y in range(int(6*s), int(12*s)):
                c = wood_hi if y < int(9*s) else wood_lo
                if x == int(5*s) or x == int(11*s):
                    c = wood_lo
                p(x, y, c)
        # Goldverzierung
        for x in range(int(5*s), int(12*s)):
            p(x, int(6*s), gold_hi)
            p(x, int(11*s), gold_lo)
        # Kreuz
        p(8*s, int(8*s), gold_hi)
        p(7*s, int(9*s), gold_mid)
        p(8*s, int(9*s), gold_hi)
        p(9*s, int(9*s), gold_mid)
    elif treasure_type == "treasure_chest":
        # Große Schatztruhe voller Gold
        wood = (140, 95, 45)
        wood_d = (100, 65, 25)
        for x in range(int(3*s), int(14*s)):
            for y in range(int(6*s), int(13*s)):
                c = wood if y < int(10*s) else wood_d
                p(x, y, c)
        # Goldener Beschlag
        for x in range(int(3*s), int(14*s)):
            p(x, int(6*s), gold_lo)
        p(int(8*s), int(8*s), gold_hi)
        # Gold quillt raus
        for x in range(int(5*s), int(12*s)):
            p(x, int(5*s), gold_hi)
            if rng.random() < 0.5:
                p(x, int(4*s), gold_mid)
        # Edelstein drin
        p(int(7*s), int(5*s), (200, 40, 50))
        p(int(10*s), int(5*s), (50, 100, 220))
    elif treasure_type == "jewel_box":
        # Schmuckkaestchen
        velvet = (80, 20, 40)
        velvet_lo = (50, 10, 25)
        for x in range(int(5*s), int(12*s)):
            for y in range(int(7*s), int(11*s)):
                c = velvet if y < int(9*s) else velvet_lo
                p(x, y, c)
        # Deckel
        for x in range(int(5*s), int(12*s)):
            p(x, int(7*s), gold_lo)
        # Juwelen drin
        p(int(7*s), int(8*s), (255, 60, 70))
        p(int(8*s), int(8*s), (60, 100, 255))
        p(int(9*s), int(8*s), (50, 220, 80))
        p(int(8*s), int(9*s), (245, 240, 235))


TREASURE_TYPES = [
    "coin_pile", "coin_stack", "gold_bar", "silver_bar",
    "diamond", "ruby", "sapphire", "emerald", "pearl",
    "tiara", "scepter", "signet_ring", "reliquary",
    "treasure_chest", "jewel_box",
]


def generate_treasures(rng: random.Random,
                       size_px: int = 16) -> list[tuple[str, Image.Image]]:
    """Generiert alle Schatz-Sprites."""
    results = []
    for t_type in TREASURE_TYPES:
        img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
        _draw_treasure_sprite(img.load(), t_type, rng, size_px)
        outline_pass(img)
        results.append((f"treasure_{t_type}.png", img))
    return results


def _magic_outline_pass(img: Image.Image,
                        color: tuple[int, int, int, int] = (40, 80, 200, 255)):
    """Blaue magische Outline statt schwarzer — kennzeichnet magische Items."""
    px = img.load()
    w, h = img.size
    outline_pixels = []
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > 0:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and px[nx, ny][3] > 30:
                    outline_pixels.append((x, y))
                    break
    for x, y in outline_pixels:
        px[x, y] = color


def _add_magic_shimmer(img: Image.Image, rng: random.Random) -> None:
    """Fuegt subtile leuchtende Partikel um das Item hinzu (magischer Glanz)."""
    px = img.load()
    w, h = img.size
    shimmer_c = (100, 150, 255, 160)
    spark_c = (180, 210, 255, 200)
    # Finde alle Outline-Pixel (Rand des Items)
    outline_pos = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 0:
                # Ist Rand-Pixel?
                has_empty = False
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        if px[nx, ny][3] == 0:
                            has_empty = True
                    else:
                        has_empty = True
                if has_empty:
                    outline_pos.append((x, y))
    # 3-5 Funken um das Item
    if not outline_pos:
        return
    num_sparks = rng.randint(2, min(5, len(outline_pos)))
    if outline_pos:
        for _ in range(num_sparks):
            ox, oy = rng.choice(outline_pos)
            dx = rng.choice([-1, 0, 1])
            dy = rng.choice([-1, 0, 1])
            sx, sy = ox + dx, oy + dy
            if 0 <= sx < w and 0 <= sy < h and px[sx, sy][3] == 0:
                px[sx, sy] = spark_c if rng.random() < 0.4 else shimmer_c


def generate_magic_items(rng: random.Random,
                         size_px: int = 16) -> list[tuple[str, Image.Image]]:
    """Generiert magische Varianten aller Items (blaue Outline + Shimmer).

    Nimmt die normalen Item-Templates und ersetzt schwarze Outline
    durch leuchtend blaue + fuegt magische Funken hinzu.
    """
    # Nur Extended Items (die haben _draw_item_sprite Handler)
    magic_worthy = [i for i in EXTENDED_ITEM_TYPES
                    if not i.startswith("chest_") and i != "sack"]

    results = []
    for item_type in magic_worthy:
        # Base-Item erzeugen (ohne Outline)
        img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        px = img.load()

        if item_type in EXTENDED_ITEM_TYPES:
            _draw_item_sprite(draw, px, item_type, (160, 160, 170), rng, size_px)
        else:
            # Original-Items via existierende Logik (vereinfacht)
            _draw_item_sprite(draw, px, item_type, (160, 160, 170), rng, size_px)

        # Magische blaue Outline
        _magic_outline_pass(img)
        # Magischer Schimmer
        _add_magic_shimmer(img, rng)

        fname = f"magic_{item_type}.png"
        results.append((fname, img))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 1h. ERWEITERTE EFFEKTE (30 neue → gesamt ~46)
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_extended_effect(px, effect_type: str, frame: int,
                          rng: random.Random, size: int = 16) -> None:
    """Zeichnet erweiterte Effekt-Sprites."""
    s = size / 16.0

    def p(x, y, c):
        xi, yi = int(x), int(y)
        if 0 <= xi < size and 0 <= yi < size:
            px[xi, yi] = (*c, 255) if len(c) == 3 else c

    t = frame / 5.0  # Normalized time 0-1

    if effect_type == "lightning_bolt":
        # Blitz-Linie diagonal
        bolt_c = (200, 220, 255)
        bolt_lo = (120, 160, 255)
        for i in range(int(12*s)):
            x = int(3*s) + i
            y = int(2*s) + i + rng.randint(-1, 1)
            p(x, y, bolt_c if rng.random() < 0.6 else bolt_lo)
            if rng.random() < 0.3:
                p(x, y - 1, (255, 255, 255, 180))
    elif effect_type == "fire_wall":
        # Feuerwand (volle Breite)
        for x in range(int(2*s), int(14*s)):
            h_ = rng.randint(int(4*s), int(8*s))
            for dy in range(h_):
                y = int(13*s) - dy
                frac = dy / max(1, h_ - 1)
                if frac < 0.3:
                    c = (255, 100, 20)
                elif frac < 0.6:
                    c = (255, 180, 40)
                else:
                    c = (255, 240, 100)
                if rng.random() < 0.8:
                    p(x, y, c)
    elif effect_type == "ice_wall":
        for x in range(int(3*s), int(13*s)):
            h_ = rng.randint(int(6*s), int(10*s))
            for dy in range(h_):
                y = int(13*s) - dy
                frac = dy / max(1, h_ - 1)
                c = (70 + int(frac * 60), 140 + int(frac * 60), 220 + int(frac * 35))
                c = tuple(clamp(v) for v in c)
                if rng.random() < 0.85:
                    p(x, y, c)
    elif effect_type == "acid_splash":
        green_hi = (140, 255, 60)
        green_lo = (60, 160, 20)
        # Spritzer
        num = int(6 + t * 4)
        for _ in range(num):
            dx = rng.randint(-5, 5)
            dy = rng.randint(-5, 5)
            c = green_hi if rng.random() < 0.4 else green_lo
            p(8*s + dx, 8*s + dy, c)
    elif effect_type == "thunder_wave":
        # Konzentrische Kreise
        radius = int(2 + t * 5)
        for angle_i in range(36):
            a = angle_i * math.pi / 18
            x = int(8*s + math.cos(a) * radius * s)
            y = int(8*s + math.sin(a) * radius * s)
            p(x, y, (200, 210, 255, 200))
    elif effect_type == "dark_pulse":
        # Dunkle Welle
        radius = int(2 + t * 5)
        for angle_i in range(24):
            a = angle_i * math.pi / 12
            x = int(8*s + math.cos(a) * radius * s)
            y = int(8*s + math.sin(a) * radius * s)
            p(x, y, (60, 20, 80, 200))
            p(x + 1, y, (40, 10, 60, 150))
    elif effect_type == "entangle":
        # Grüne Ranken
        vine_c = (40, 140, 30)
        vine_lo = (25, 90, 15)
        for i in range(int(8 + t * 6)):
            x = rng.randint(int(3*s), int(13*s))
            y = rng.randint(int(3*s), int(13*s))
            p(x, y, vine_c if rng.random() < 0.5 else vine_lo)
            p(x + rng.choice([-1, 0, 1]), y + 1, vine_lo)
    elif effect_type == "web_spell":
        web = (210, 210, 220, 180)
        for i in range(int(14*s)):
            p(2*s + i, 2*s + i, web)
            p(14*s - i, 2*s + i, web)
        for x in range(int(4*s), int(13*s)):
            p(x, 8*s, web)
        for y in range(int(4*s), int(13*s)):
            p(8*s, y, web)
    elif effect_type == "sleep_cloud":
        for _ in range(int(10 + t * 8)):
            x = int(8*s + rng.gauss(0, 3*s))
            y = int(8*s + rng.gauss(0, 3*s))
            c = (140, 130, 200, 150) if rng.random() < 0.5 else (180, 170, 230, 120)
            p(x, y, c)
    elif effect_type == "silence":
        # Grauer gedämpfter Kreis
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                if dx*dx + dy*dy <= 18:
                    v = 100 + rng.randint(-10, 10)
                    p(8*s + dx, 8*s + dy, (v, v, v, 100))
    elif effect_type == "mirror_image":
        # Geisterhafte Kopien
        ghost = (150, 180, 220, 100)
        for ox in [-3, 3]:
            for y in range(int(4*s), int(12*s)):
                p(8*s + ox, y, ghost)
                if abs(y - int(5*s)) < 2:
                    p(8*s + ox - 1, y, ghost)
                    p(8*s + ox + 1, y, ghost)
    elif effect_type == "teleport":
        # Aufsteigende Partikel
        for _ in range(int(12 + t * 6)):
            x = int(8*s + rng.gauss(0, 2*s))
            y = int(12*s - t * 10*s + rng.gauss(0, 1.5*s))
            c = (100, 60, 220) if rng.random() < 0.5 else (180, 140, 255)
            p(x, y, c)
    elif effect_type == "smite":
        # Goldener Strahl von oben
        for y in range(int(1*s), int(13*s)):
            w_ = 1 + int((1.0 - abs(y - 7*s) / (6*s)) * 2)
            for dx in range(-w_, w_ + 1):
                v = 180 + int(40 * (1 - y / (13*s)))
                p(8*s + dx, y, (v, v - 20, clamp(v - 80)))
    elif effect_type == "necrotic":
        # Schwarze/lila Partikel, aufsteigend
        for _ in range(int(10 + t * 8)):
            x = int(8*s + rng.gauss(0, 3*s))
            y = int(12*s - rng.random() * 10*s)
            c = (80, 20, 100) if rng.random() < 0.5 else (40, 5, 50)
            p(x, y, c)
    elif effect_type == "radiant":
        # Goldene Strahlen vom Zentrum
        gold = (255, 230, 100)
        for angle_i in range(8):
            a = angle_i * math.pi / 4
            for r in range(int(2*s), int(7*s)):
                x = int(8*s + math.cos(a) * r)
                y = int(8*s + math.sin(a) * r)
                v = 255 - r * 15
                p(x, y, (clamp(v), clamp(v - 25), clamp(v - 100)))
    elif effect_type == "force_field":
        # Halbtransparenter Schild-Kreis
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                dist = dx*dx + dy*dy
                if 16 <= dist <= 28:
                    p(8*s + dx, 8*s + dy, (80, 140, 255, 140))
                elif dist < 16:
                    if rng.random() < 0.15:
                        p(8*s + dx, 8*s + dy, (120, 170, 255, 60))
    elif effect_type == "confusion":
        # Wirbelnde bunte Spirale
        for i in range(int(16 * (0.5 + t))):
            a = i * 0.8 + t * 6
            r = i * 0.4 * s
            x = int(8*s + math.cos(a) * r)
            y = int(8*s + math.sin(a) * r)
            colors = [(255, 100, 100), (100, 255, 100), (100, 100, 255), (255, 255, 100)]
            p(x, y, colors[i % 4])
    elif effect_type == "charm":
        # Rosa Herzen
        heart_c = (255, 100, 130)
        heart_lo = (200, 60, 90)
        for cx_, cy_ in [(6, 5), (10, 7), (8, 10)]:
            p(cx_*s - 1, cy_*s, heart_c)
            p(cx_*s + 1, cy_*s, heart_c)
            p(cx_*s - 1, cy_*s + 1, heart_lo)
            p(cx_*s, cy_*s + 1, heart_lo)
            p(cx_*s + 1, cy_*s + 1, heart_lo)
            p(cx_*s, cy_*s + 2, heart_lo)
    elif effect_type == "petrify":
        # Steinerne Welle
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                if abs(dx) + abs(dy) <= int(4 + t * 3):
                    v = 120 + rng.randint(-15, 15)
                    p(8*s + dx, 8*s + dy, (v, v - 2, v - 5, 180))
    elif effect_type == "polymorph":
        # Glitzernder Strudel
        for i in range(int(20 * (0.5 + t))):
            a = i * 0.5 + t * 8
            r = (5 - abs(i - 10) * 0.4) * s
            x = int(8*s + math.cos(a) * r)
            y = int(8*s + math.sin(a) * r)
            p(x, y, (rng.randint(100, 255), rng.randint(100, 255), rng.randint(100, 255)))
    elif effect_type == "banish":
        # Verschwindender Kreis
        r_max = int((1 - t) * 6 * s)
        for angle_i in range(36):
            a = angle_i * math.pi / 18
            x = int(8*s + math.cos(a) * r_max)
            y = int(8*s + math.sin(a) * r_max)
            p(x, y, (255, 220, 100, int(200 * (1 - t))))
    elif effect_type == "resurrect":
        # Aufsteigendes goldenes Licht + Partikel
        for y in range(int(13*s), int(2*s), -1):
            frac = (int(13*s) - y) / (11*s)
            if frac > t * 1.2:
                break
            w_ = int(1 + frac * 3)
            for dx in range(-w_, w_ + 1):
                v = int(200 + frac * 55)
                p(8*s + dx, y, (clamp(v), clamp(v - 20), clamp(v - 120), 180))
    elif effect_type == "aura_protection":
        # Blaue Aura-Blase
        for dx in range(-5, 6):
            for dy in range(-6, 7):
                dist = dx*dx + dy*dy
                if 20 <= dist <= 35:
                    p(8*s + dx, 7*s + dy, (60, 120, 220, 120))
                elif dist < 20 and rng.random() < 0.08:
                    p(8*s + dx, 7*s + dy, (100, 160, 255, 80))
    elif effect_type == "aura_fire":
        for dx in range(-5, 6):
            for dy in range(-6, 7):
                dist = dx*dx + dy*dy
                if 20 <= dist <= 35:
                    p(8*s + dx, 7*s + dy, (220, 80 + rng.randint(0, 40), 20, 140))
    elif effect_type == "summon_circle":
        # Magischer Kreis am Boden
        for angle_i in range(36):
            a = angle_i * math.pi / 18
            for r in [4, 5]:
                x = int(8*s + math.cos(a) * r * s)
                y = int(10*s + math.sin(a) * r * s * 0.5)
                c = (180, 100, 255) if r == 5 else (120, 50, 200)
                p(x, y, c)
        # Runen
        for a_i in range(6):
            a = a_i * math.pi / 3 + t * 2
            x = int(8*s + math.cos(a) * 3 * s)
            y = int(10*s + math.sin(a) * 1.5 * s)
            p(x, y, (220, 160, 255))


EXTENDED_EFFECTS = [
    "lightning_bolt", "fire_wall", "ice_wall", "acid_splash",
    "thunder_wave", "dark_pulse", "entangle", "web_spell",
    "sleep_cloud", "silence", "mirror_image", "teleport",
    "smite", "necrotic", "radiant", "force_field",
    "confusion", "charm", "petrify", "polymorph",
    "banish", "resurrect", "aura_protection", "aura_fire",
    "summon_circle",
]


def generate_extended_effects(rng: random.Random,
                              num_frames: int = 6,
                              size_px: int = 16) -> list[tuple[str, Image.Image]]:
    """Generiert alle erweiterten Effekt-Sprites (je 6 Frames)."""
    results = []
    for effect_type in EXTENDED_EFFECTS:
        for frame in range(num_frames):
            img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
            _draw_extended_effect(img.load(), effect_type, frame,
                                 random.Random(rng.randint(0, 999999)), size_px)
            fname = f"effect_{effect_type}_{frame + 1:02d}.png"
            results.append((fname, img))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 1i. ERWEITERTE UMGEBUNGS-OBJEKTE (12 neue)
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_extended_object(px, obj_type: str, rng: random.Random,
                          size: int = 16) -> None:
    """Zeichnet erweiterte Umgebungsobjekte."""
    s = size / 16.0

    def p(x, y, c):
        xi, yi = int(x), int(y)
        if 0 <= xi < size and 0 <= yi < size:
            px[xi, yi] = (*c, 255) if len(c) == 3 else c

    stone_hi = (160, 155, 150)
    stone_mid = (120, 118, 115)
    stone_lo = (80, 78, 75)
    wood_hi = (170, 130, 75)
    wood_lo = (90, 60, 30)
    gold_c = (220, 200, 60)

    if obj_type == "tapestry":
        # Wandteppich (rot mit Muster)
        cloth_hi = (160, 40, 40)
        cloth_lo = (100, 25, 25)
        for x in range(int(4*s), int(13*s)):
            for y in range(int(2*s), int(13*s)):
                c = cloth_hi if (x + y) % 4 < 2 else cloth_lo
                p(x, y, c)
        # Stange oben
        for x in range(int(3*s), int(14*s)):
            p(x, int(2*s), gold_c)
    elif obj_type == "painting":
        # Gemälde mit Rahmen
        for x in range(int(4*s), int(13*s)):
            for y in range(int(4*s), int(11*s)):
                if x == int(4*s) or x == int(12*s) or y == int(4*s) or y == int(10*s):
                    p(x, y, gold_c)
                else:
                    # Landschaft
                    if y < int(7*s):
                        p(x, y, (100, 140, 200))
                    else:
                        p(x, y, (60, 120, 40))
    elif obj_type == "candelabra":
        # Kerzenständer
        for y in range(int(8*s), int(14*s)):
            p(8*s, y, gold_c)
        # Arme
        p(6*s, int(7*s), gold_c)
        p(7*s, int(7*s), gold_c)
        p(9*s, int(7*s), gold_c)
        p(10*s, int(7*s), gold_c)
        # Kerzen
        for cx_ in [int(6*s), int(8*s), int(10*s)]:
            p(cx_, int(6*s), (240, 230, 200))
            p(cx_, int(5*s), (255, 200, 50))  # Flamme
    elif obj_type == "sarcophagus":
        for x in range(int(4*s), int(13*s)):
            for y in range(int(6*s), int(13*s)):
                c = stone_hi if y < int(9*s) else stone_lo
                p(x, y, c)
        # Deckel-Kante
        for x in range(int(3*s), int(14*s)):
            p(x, int(6*s), stone_hi)
        # Kreuz
        p(8*s, int(8*s), gold_c)
        p(7*s, int(9*s), gold_c)
        p(8*s, int(9*s), gold_c)
        p(9*s, int(9*s), gold_c)
        p(8*s, int(10*s), gold_c)
    elif obj_type == "throne":
        wood_c = (120, 50, 30)
        cushion = (140, 30, 40)
        # Rücklehne
        for y in range(int(3*s), int(8*s)):
            p(6*s, y, wood_c)
            p(10*s, y, wood_c)
            if y < int(5*s):
                for x in range(int(7*s), int(10*s)):
                    p(x, y, wood_c)
        # Sitz
        for x in range(int(5*s), int(12*s)):
            p(x, int(8*s), wood_c)
            p(x, int(9*s), cushion)
        # Beine
        p(6*s, int(10*s), wood_c)
        p(6*s, int(11*s), wood_c)
        p(10*s, int(10*s), wood_c)
        p(10*s, int(11*s), wood_c)
        # Gold
        p(8*s, int(3*s), gold_c)
    elif obj_type == "anvil":
        iron_hi = (140, 140, 150)
        iron_lo = (80, 80, 90)
        # Oberfläche
        for x in range(int(4*s), int(13*s)):
            p(x, int(7*s), iron_hi)
            p(x, int(8*s), iron_lo)
        # Horn
        p(3*s, int(7*s), iron_hi)
        p(3*s, int(8*s), iron_lo)
        # Fuss
        for x in range(int(6*s), int(11*s)):
            for y in range(int(9*s), int(13*s)):
                c = iron_hi if x < int(8*s) else iron_lo
                p(x, y, c)
    elif obj_type == "cauldron":
        iron_hi = (80, 80, 90)
        iron_lo = (50, 50, 58)
        liquid = (40, 180, 40)
        # Kessel
        for dx in range(-3, 4):
            for dy in range(0, int(5*s)):
                if abs(dx) <= 3 - dy // int(max(1, 2*s)):
                    c = iron_hi if dx < 0 else iron_lo
                    p(8*s + dx, int(7*s) + dy, c)
        # Inhalt (grün)
        for dx in range(-2, 3):
            p(8*s + dx, int(7*s), liquid)
            p(8*s + dx, int(8*s), (30, 140, 30))
        # Beine
        p(6*s, int(12*s), iron_lo)
        p(8*s, int(12*s), iron_lo)
        p(10*s, int(12*s), iron_lo)
        # Dampf
        p(7*s, int(5*s), (140, 200, 140, 120))
        p(9*s, int(6*s), (140, 200, 140, 100))
    elif obj_type == "gravestone":
        for x in range(int(6*s), int(11*s)):
            for y in range(int(5*s), int(13*s)):
                c = stone_hi if x < int(8*s) else stone_lo
                p(x, y, c)
        # Rundung oben
        p(7*s, int(4*s), stone_mid)
        p(8*s, int(4*s), stone_hi)
        p(9*s, int(4*s), stone_lo)
        # RIP
        p(7*s, int(7*s), stone_lo)
        p(8*s, int(7*s), stone_lo)
        p(9*s, int(7*s), stone_lo)
    elif obj_type == "shrine":
        # Kleiner Schrein
        for x in range(int(5*s), int(12*s)):
            for y in range(int(7*s), int(13*s)):
                p(x, y, stone_mid if y < int(10*s) else stone_lo)
        # Dach (Dreieck)
        for dy in range(int(3*s)):
            w_ = int(4*s) - dy
            for dx in range(-w_, w_ + 1):
                p(8*s + dx, int(6*s) - dy, stone_hi if dx < 0 else stone_lo)
        # Statue drin
        p(8*s, int(8*s), gold_c)
        p(8*s, int(9*s), gold_c)
    elif obj_type == "banner":
        # Hängendes Banner
        cloth = (40, 60, 140)
        cloth_lo = (25, 40, 100)
        # Stange
        for x in range(int(5*s), int(12*s)):
            p(x, int(3*s), wood_hi)
        # Stoff
        for x in range(int(6*s), int(11*s)):
            for y in range(int(4*s), int(12*s)):
                wave = 1 if (y + x) % 4 == 0 else 0
                c = cloth if (x + wave) < int(9*s) else cloth_lo
                p(x, y, c)
        # Symbol
        p(8*s, int(7*s), gold_c)
        p(7*s, int(8*s), gold_c)
        p(8*s, int(8*s), gold_c)
        p(9*s, int(8*s), gold_c)
    elif obj_type == "portcullis":
        # Fallgitter
        for y in range(int(2*s), int(14*s)):
            for x in range(int(4*s), int(13*s), int(2*s)):
                p(x, y, (100, 95, 90))
        for y in range(int(4*s), int(14*s), int(3*s)):
            for x in range(int(4*s), int(13*s)):
                p(x, y, (80, 75, 70))
    elif obj_type == "campfire":
        # Lagerfeuer
        for dx in range(-2, 3):
            p(8*s + dx, int(12*s), wood_lo)
            p(8*s + dx, int(11*s), wood_hi)
        # Flamme
        flames = [(8,7),(7,8),(8,8),(9,8),(7,9),(8,9),(9,9),(8,10)]
        colors = [(255,240,100),(255,200,50),(255,140,30),(255,100,20)]
        for i, (fx, fy) in enumerate(flames):
            p(fx*s, fy*s, colors[min(i // 2, 3)])


EXTENDED_OBJECTS = [
    "tapestry", "painting", "candelabra", "sarcophagus",
    "throne", "anvil", "cauldron", "gravestone",
    "shrine", "banner", "portcullis", "campfire",
]


def generate_extended_objects(rng: random.Random,
                              size_px: int = 16) -> list[tuple[str, Image.Image]]:
    """Generiert erweiterte Umgebungsobjekte."""
    results = []
    for obj_type in EXTENDED_OBJECTS:
        img = Image.new("RGBA", (size_px, size_px), (0, 0, 0, 0))
        _draw_extended_object(img.load(), obj_type, rng, size_px)
        outline_pass(img)
        results.append((f"obj_{obj_type}.png", img))
    return results


def generate_all_missing(seed: int = 42, output_dir: str | None = None) -> dict:
    """Generiert ALLE fehlenden Sprite-Kategorien und speichert sie.

    Returns: dict mit Statistik {kategorie: anzahl}
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    rng = random.Random(seed)
    stats = {}

    # 1. NPC-Rollen (10 Rollen × 10 Rassen = 100)
    npcs = generate_all_npcs(rng)
    for fname, img in npcs:
        img.save(os.path.join(output_dir, fname))
    stats["npcs"] = len(npcs)

    # 2. Erweiterte Items (27 Typen × 6 Farben = 162)
    items = generate_extended_items(rng)
    for fname, img in items:
        img.save(os.path.join(output_dir, fname))
    stats["items"] = len(items)

    # 3. Interaktive Objekte (15)
    objects = generate_interactive_objects(rng)
    for fname, img in objects:
        img.save(os.path.join(output_dir, fname))
    stats["objects"] = len(objects)

    # 4. Status-Icons (12)
    icons = generate_status_icons(rng)
    for fname, img in icons:
        img.save(os.path.join(output_dir, fname))
    stats["icons"] = len(icons)

    # 5. Humanoide Rassen (20 Rassen, statisch)
    humanoids = generate_humanoid_races(rng)
    for fname, img in humanoids:
        img.save(os.path.join(output_dir, fname))
    stats["humanoids"] = len(humanoids)

    # 6. Schaetze (15 Typen)
    treasures = generate_treasures(rng)
    for fname, img in treasures:
        img.save(os.path.join(output_dir, fname))
    stats["treasures"] = len(treasures)

    # 7. Magische Items (blaue Outline + Shimmer)
    magic = generate_magic_items(rng)
    for fname, img in magic:
        img.save(os.path.join(output_dir, fname))
    stats["magic_items"] = len(magic)

    # 8. Erweiterte Effekte (25 Typen × 6 Frames = 150)
    ext_effects = generate_extended_effects(rng)
    for fname, img in ext_effects:
        img.save(os.path.join(output_dir, fname))
    stats["extended_effects"] = len(ext_effects)

    # 9. Erweiterte Umgebungsobjekte (12)
    ext_objects = generate_extended_objects(rng)
    for fname, img in ext_objects:
        img.save(os.path.join(output_dir, fname))
    stats["extended_objects"] = len(ext_objects)

    # 10. Humanoid-Kampfanimationen (20 Rassen × 3 Anims × ~6 Frames + Sheets)
    h_combat = generate_humanoid_combat_anims(rng)
    for fname, img in h_combat:
        img.save(os.path.join(output_dir, fname))
    stats["humanoid_combat"] = len(h_combat)

    # 11. Monster-Kampfanimationen (12 Typen × 3 Anims × ~6 Frames + Sheets)
    m_combat = generate_monster_combat_anims(rng)
    for fname, img in m_combat:
        img.save(os.path.join(output_dir, fname))
    stats["monster_combat"] = len(m_combat)

    # 12. Grosse Monster Kampfanimationen (L/H/G × 3 Anims)
    lg_combat = generate_sized_monster_combat_anims(rng)
    for fname, img in lg_combat:
        img.save(os.path.join(output_dir, fname))
    stats["sized_monster_combat"] = len(lg_combat)

    return stats


def generate_single_variant(
    category: str,
    sub_type: str,
    body_mod: str = "normal",
    color_mod: str = "normal",
    seed: int = 42,
    variant_idx: int = 0,
) -> tuple[str, "Image.Image", dict]:
    """Erzeugt eine einzelne Sprite-Variante.

    Args:
        category: "monsters", "characters" oder "environments"
        sub_type: z.B. "undead_humanoid", "fighter", "dungeon"
        body_mod: Key aus BODY_MODIFIERS
        color_mod: Key aus COLOR_MODIFIERS
        seed: RNG-Seed
        variant_idx: Varianten-Index (wird zum Seed addiert)

    Returns:
        (filename, image, params_dict)
    """
    rng = random.Random(seed + variant_idx)
    params = {
        "category": category,
        "sub_type": sub_type,
        "body_mod": body_mod,
        "color_mod": color_mod,
        "seed": seed,
        "variant_idx": variant_idx,
    }

    if category == "monsters":
        # sub_type Format: "palette_silhouette" z.B. "undead_humanoid"
        parts = sub_type.split("_", 1)
        palette_name = parts[0] if len(parts) > 1 else "beast"
        sil_name = parts[1] if len(parts) > 1 else parts[0]
        if palette_name not in PALETTES:
            palette_name = "beast"
        if sil_name not in SILHOUETTES:
            sil_name = "humanoid"
        img = generate_monster(rng, palette_name, sil_name, body_mod, color_mod)
        filename = f"monster_{sub_type}_{body_mod}_{color_mod}_v{variant_idx}.png"

    elif category == "characters":
        char_def = CHAR_DEFS.get(sub_type)
        if not char_def:
            char_def = CHAR_DEFS["fighter"]
        img = _draw_chibi_base(char_def, body_mod, color_mod)
        filename = f"char_{sub_type}_{body_mod}_{color_mod}_v{variant_idx}.png"

    elif category == "environments":
        biome = BIOME_DEFS.get(sub_type)
        if not biome:
            biome = BIOME_DEFS["dungeon"]
            sub_type = "dungeon"
        # Umgebungen: Body-Mod hat keinen Effekt, aber Color-Mod schon
        cmod = COLOR_MODIFIERS.get(color_mod, COLOR_MODIFIERS["normal"])
        floor_color = _apply_color_mod(biome["floor"], cmod)
        img = _env_floor(rng, floor_color, None, biome["variation"], seed + variant_idx)
        filename = f"env_{sub_type}_{color_mod}_v{variant_idx}.png"

    else:
        # Fallback: leeres Tile
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        filename = f"unknown_{variant_idx}.png"

    return filename, img, params


def _apply_variance(transform: dict, amplitude: float, chaos: float,
                     rng: random.Random) -> dict:
    """Skaliert/randomisiert einen Keyframe-Transform-Dict.

    Args:
        transform: Originaler Keyframe (body_dy, lean_dx, flash, etc.)
        amplitude: Multiplikator fuer alle numerischen Werte (0.1-3.0)
        chaos: Addiert rng.uniform(-chaos, chaos) zu jedem Wert (0.0-5.0)
    """
    result = {}
    for key, val in transform.items():
        if isinstance(val, bool):
            result[key] = val
        elif isinstance(val, (int, float)):
            scaled = val * amplitude
            if chaos > 0:
                scaled += rng.uniform(-chaos, chaos)
            result[key] = round(scaled)
        else:
            result[key] = val
    return result


def _apply_sprite_variance(img: Image.Image, rng: random.Random,
                            color_jitter: int = 0,
                            pixel_noise: float = 0.0) -> Image.Image:
    """Fuegt Seed-basierte visuelle Varianz zum fertigen Sprite hinzu.

    Args:
        color_jitter: RGB pro Pixel um +-jitter variieren (0-50)
        pixel_noise: Chance, dass ein Pixel um 1px verschoben wird (0.0-1.0)
    """
    if color_jitter == 0 and pixel_noise <= 0:
        return img

    result = img.copy()
    px = result.load()
    w, h = result.size

    # Color-Jitter: RGB-Werte leicht verschieben
    if color_jitter > 0:
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if a == 0:
                    continue
                r = clamp(r + rng.randint(-color_jitter, color_jitter))
                g = clamp(g + rng.randint(-color_jitter, color_jitter))
                b = clamp(b + rng.randint(-color_jitter, color_jitter))
                px[x, y] = (r, g, b, a)

    # Pixel-Noise: zufaellige 1px-Verschiebung
    if pixel_noise > 0:
        src = result.copy()
        src_px = src.load()
        for y in range(h):
            for x in range(w):
                r, g, b, a = src_px[x, y]
                if a == 0:
                    continue
                if rng.random() < pixel_noise:
                    dx = rng.choice([-1, 0, 1])
                    dy = rng.choice([-1, 0, 1])
                    nx = clamp(x + dx, 0, w - 1)
                    ny = clamp(y + dy, 0, h - 1)
                    px[nx, ny] = (r, g, b, a)

    return result


def generate_animated_variant(
    sub_type: str,
    anim_name: str,
    body_mod: str = "normal",
    color_mod: str = "normal",
    seed: int = 42,
    variant_idx: int = 0,
    amplitude: float = 1.0,
    chaos: float = 0.0,
    color_jitter: int = 0,
    pixel_noise: float = 0.0,
    custom_char_def: dict | None = None,
) -> tuple[str, list["Image.Image"], dict]:
    """Erzeugt animierte Sprite-Frames fuer einen Charakter oder Monster.

    Args:
        amplitude: Multiplikator fuer Keyframe-Werte (0.1-3.0)
        chaos: Zufalls-Offset pro Keyframe-Wert (0.0-5.0)
        color_jitter: RGB-Varianz pro Pixel (0-50)
        pixel_noise: Chance fuer 1px-Verschiebung (0.0-1.0)

    Returns:
        (base_filename, [frame_images], params_dict)
    """
    rng = random.Random(seed + variant_idx)
    keyframes = ANIMATIONS.get(anim_name, ANIMATIONS["idle"])
    params = {
        "category": "animations",
        "sub_type": sub_type,
        "anim_name": anim_name,
        "body_mod": body_mod,
        "color_mod": color_mod,
        "seed": seed,
        "variant_idx": variant_idx,
        "amplitude": amplitude,
        "chaos": chaos,
        "color_jitter": color_jitter,
        "pixel_noise": pixel_noise,
    }

    # Charakter oder Monster?
    if custom_char_def:
        char_def = custom_char_def
    else:
        char_def = CHAR_DEFS.get(sub_type)
    if char_def:
        base_sprite = _draw_chibi_base(char_def, body_mod, color_mod)
    else:
        # Monster — sub_type Format: "palette_silhouette"
        parts = sub_type.split("_", 1)
        palette_name = parts[0] if len(parts) > 1 else "beast"
        sil_name = parts[1] if len(parts) > 1 else parts[0]
        if palette_name not in PALETTES:
            palette_name = "beast"
        if sil_name not in SILHOUETTES:
            sil_name = "humanoid"
        base_sprite = generate_monster(rng, palette_name, sil_name, body_mod, color_mod)

    # Sprite-Varianz anwenden (Farbe + Pixel-Noise)
    base_sprite = _apply_sprite_variance(base_sprite, rng, color_jitter, pixel_noise)

    frames = []
    for f_idx, transform in enumerate(keyframes):
        # Keyframe-Varianz anwenden
        if amplitude != 1.0 or chaos > 0:
            transform = _apply_variance(transform, amplitude, chaos, rng)
        frame = _apply_frame_transform(base_sprite, transform)
        if anim_name == "cast" and char_def:
            frame = _add_cast_glow(frame, char_def, f_idx)
        frames.append(frame)

    base_name = f"anim_{sub_type}_{anim_name}_{body_mod}_{color_mod}_v{variant_idx}"
    return base_name, frames, params


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TEMPLATE-GENERATOR (Items)
# ═══════════════════════════════════════════════════════════════════════════════

# Templates als Liste von (x, y) Offset-Paaren relativ zur Mitte
# Jedes Template definiert die Kern-Pixel

def _template_sword() -> list[tuple[int, int, int]]:
    """Schwert-Template. Returniert (x, y, part) — part: 0=blade, 1=guard, 2=grip."""
    pixels = []
    # Klinge (diagonal)
    for i in range(7):
        pixels.append((8 + i // 2 - 3, 2 + i, 0))
        if i > 0:
            pixels.append((8 + i // 2 - 2, 2 + i, 0))
    # Parierstange
    for x in range(4, 12):
        pixels.append((x, 9, 1))
    # Griff
    for y in range(10, 14):
        pixels.append((7, y, 2))
        pixels.append((8, y, 2))
    # Knauf
    pixels.append((7, 14, 1))
    pixels.append((8, 14, 1))
    return pixels


def _template_shield() -> list[tuple[int, int, int]]:
    pixels = []
    # Schildkoerper (Oval)
    for y in range(3, 14):
        width = 5 - abs(y - 8) // 2
        for x in range(8 - width, 8 + width):
            pixels.append((x, y, 0))
    # Rand
    for y in range(3, 14):
        width = 5 - abs(y - 8) // 2
        pixels.append((8 - width, y, 1))
        pixels.append((8 + width - 1, y, 1))
    # Emblem-Mitte
    pixels.append((7, 7, 2))
    pixels.append((8, 7, 2))
    pixels.append((7, 8, 2))
    pixels.append((8, 8, 2))
    return pixels


def _template_potion() -> list[tuple[int, int, int]]:
    pixels = []
    # Flaschenhals
    for y in range(3, 6):
        pixels.append((7, y, 1))
        pixels.append((8, y, 1))
    # Korken
    pixels.append((7, 2, 2))
    pixels.append((8, 2, 2))
    # Bauch
    for y in range(6, 13):
        width = 3 if 7 <= y <= 11 else 2
        for x in range(8 - width, 8 + width):
            pixels.append((x, y, 0))
    # Boden
    for x in range(5, 11):
        pixels.append((x, 13, 1))
    return pixels


def _template_scroll() -> list[tuple[int, int, int]]:
    pixels = []
    # Rolle oben
    for x in range(4, 12):
        pixels.append((x, 3, 1))
        pixels.append((x, 4, 1))
    # Papier
    for y in range(5, 12):
        for x in range(5, 11):
            pixels.append((x, y, 0))
    # Rolle unten
    for x in range(4, 12):
        pixels.append((x, 12, 1))
        pixels.append((x, 13, 1))
    # Schrift-Linien
    for y in range(6, 11):
        if y % 2 == 0:
            for x in range(6, 10):
                pixels.append((x, y, 2))
    return pixels


def _template_ring() -> list[tuple[int, int, int]]:
    pixels = []
    # Ring (Kreis)
    cx, cy, r = 8, 8, 4
    for y in range(TILE):
        for x in range(TILE):
            d = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            if r - 1.2 < d < r + 0.8:
                pixels.append((x, y, 0))
    # Stein oben
    pixels.append((7, 4, 1))
    pixels.append((8, 4, 1))
    pixels.append((7, 3, 1))
    pixels.append((8, 3, 1))
    return pixels


def _template_amulet() -> list[tuple[int, int, int]]:
    pixels = []
    # Kette
    for y in range(1, 5):
        pixels.append((6 + y // 2, y, 1))
        pixels.append((9 - y // 2, y, 1))
    # Anhaenger (Raute)
    for dy in range(5):
        w = min(dy, 4 - dy) + 1
        for dx in range(-w, w + 1):
            pixels.append((8 + dx, 5 + dy, 0))
    # Stein
    pixels.append((8, 7, 2))
    return pixels


def _template_helm() -> list[tuple[int, int, int]]:
    pixels = []
    # Helmkoerper
    for y in range(3, 10):
        w = 4 if y < 7 else 3
        for x in range(8 - w, 8 + w):
            pixels.append((x, y, 0))
    # Visier
    for x in range(5, 11):
        pixels.append((x, 7, 1))
    # Kamm
    for y in range(2, 6):
        pixels.append((8, y, 2))
    # Nacken
    for x in range(5, 11):
        pixels.append((x, 10, 1))
    return pixels


def _template_book() -> list[tuple[int, int, int]]:
    pixels = []
    # Buchdeckel
    for y in range(3, 13):
        for x in range(4, 12):
            pixels.append((x, y, 0))
    # Buchrücken
    for y in range(3, 13):
        pixels.append((4, y, 1))
    # Seiten (heller Streifen)
    for y in range(4, 12):
        pixels.append((11, y, 2))
    # Emblem
    pixels.append((7, 7, 2))
    pixels.append((8, 7, 2))
    pixels.append((7, 8, 2))
    pixels.append((8, 8, 2))
    return pixels


def _template_key() -> list[tuple[int, int, int]]:
    pixels = []
    # Ring (Griff)
    cx, cy, r = 5, 5, 2.5
    for y in range(TILE):
        for x in range(TILE):
            d = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
            if r - 1.0 < d < r + 0.8:
                pixels.append((x, y, 0))
    # Schaft
    for x in range(7, 13):
        pixels.append((x, 5, 0))
    # Bart
    pixels.append((12, 6, 0))
    pixels.append((12, 7, 0))
    pixels.append((10, 6, 0))
    pixels.append((10, 7, 0))
    return pixels


def _template_gem() -> list[tuple[int, int, int]]:
    pixels = []
    # Obere Facetten
    for y in range(5, 8):
        w = y - 4
        for x in range(8 - w, 8 + w):
            pixels.append((x, y, 0 if y < 7 else 1))
    # Untere Facetten
    for y in range(8, 12):
        w = 12 - y
        for x in range(8 - w, 8 + w):
            pixels.append((x, y, 0))
    # Glanz
    pixels.append((7, 6, 2))
    return pixels


ITEM_TEMPLATES: dict[str, Callable[[], list[tuple[int, int, int]]]] = {
    "sword":  _template_sword,
    "shield": _template_shield,
    "potion": _template_potion,
    "scroll": _template_scroll,
    "ring":   _template_ring,
    "amulet": _template_amulet,
    "helm":   _template_helm,
    "book":   _template_book,
    "key":    _template_key,
    "gem":    _template_gem,
}


def generate_item(rng: random.Random, template_name: str,
                  color_name: str) -> Image.Image:
    """Generiert ein Item-Sprite aus Template + Farbvariante."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px = img.load()

    base_color = ITEM_COLORS[color_name]
    template_fn = ITEM_TEMPLATES[template_name]
    pixels = template_fn()

    # Part-Farben: 0=Hauptfarbe, 1=Dunkel, 2=Highlight
    dark = tuple(clamp(c - 60) for c in base_color)
    highlight = tuple(clamp(c + 80) for c in base_color)

    part_colors = {0: base_color, 1: dark, 2: highlight}

    for (x, y, part) in pixels:
        if 0 <= x < TILE and 0 <= y < TILE:
            c = color_shift(part_colors[part], rng, 8)
            # ±1 Pixel Variation
            dx = rng.randint(-1, 1) if rng.random() < 0.1 else 0
            dy = rng.randint(-1, 1) if rng.random() < 0.1 else 0
            nx, ny = clamp(x + dx, 0, TILE - 1), clamp(y + dy, 0, TILE - 1)
            px[nx, ny] = (*c, 255)

    outline_pass(img)
    return img


def generate_items(rng: random.Random, count: int) -> list[tuple[str, Image.Image]]:
    """Generiert count Item-Sprites."""
    results = []
    templates = list(ITEM_TEMPLATES.keys())
    colors = list(ITEM_COLORS.keys())
    i = 0
    while len(results) < count:
        tmpl = templates[i % len(templates)]
        color = colors[(i // len(templates)) % len(colors)]
        sprite = generate_item(rng, tmpl, color)
        name = f"item_{tmpl}_{color}.png"
        # Duplikate vermeiden
        if any(n == name for n, _ in results):
            name = f"item_{tmpl}_{color}_{i + 1:03d}.png"
        results.append((name, sprite))
        i += 1
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PATTERN-GENERATOR (Terrain/Deko)
# ═══════════════════════════════════════════════════════════════════════════════

def _noise_tile(rng: random.Random, base: tuple[int, int, int],
                variation: int = 20) -> Image.Image:
    """Generiert ein Noise-basiertes Boden-Tile."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px = img.load()
    for y in range(TILE):
        for x in range(TILE):
            c = color_shift(base, rng, variation)
            px[x, y] = (*c, 255)
    return img


TERRAIN_DEFS = {
    "sand":   (190, 170, 120),
    "wood":   (120, 80, 45),
    "moss":   (60, 100, 50),
    "stone":  (100, 100, 105),
    "marble": (180, 175, 170),
    "dirt":   (90, 70, 50),
    "ice":    (170, 200, 220),
    "lava":   (180, 60, 20),
}


def _furniture_shape(rng: random.Random, shape_name: str) -> Image.Image:
    """Generiert ein Moebel/Deko-Sprite."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    wood = (120, 80, 45)
    wood_dark = (80, 50, 25)
    metal = (140, 140, 150)
    stone_c = (130, 130, 135)

    if shape_name == "table":
        # Tischplatte
        draw.rectangle([3, 6, 12, 8], fill=(*wood, 255))
        # Beine
        draw.line([(4, 9), (4, 13)], fill=(*wood_dark, 255))
        draw.line([(11, 9), (11, 13)], fill=(*wood_dark, 255))

    elif shape_name == "chair":
        # Sitz
        draw.rectangle([5, 8, 10, 10], fill=(*wood, 255))
        # Rueckenlehne
        draw.rectangle([5, 3, 6, 8], fill=(*wood_dark, 255))
        # Beine
        draw.line([(6, 11), (6, 14)], fill=(*wood_dark, 255))
        draw.line([(10, 11), (10, 14)], fill=(*wood_dark, 255))

    elif shape_name == "bed":
        # Matratze
        draw.rectangle([2, 5, 13, 12], fill=(180, 160, 140, 255))
        # Kopfteil
        draw.rectangle([2, 3, 13, 5], fill=(*wood_dark, 255))
        # Kissen
        draw.rectangle([4, 4, 7, 6], fill=(200, 200, 210, 255))
        # Rahmen
        draw.rectangle([2, 12, 13, 13], fill=(*wood, 255))

    elif shape_name == "bookshelf":
        # Regal
        draw.rectangle([3, 2, 12, 14], fill=(*wood, 255))
        # Boeden
        for y in (4, 7, 10):
            draw.line([(3, y), (12, y)], fill=(*wood_dark, 255))
        # Buecher
        for y_base in (5, 8, 11):
            for x in range(4, 12, 2):
                c = rng.choice([(180, 40, 30), (40, 60, 150), (40, 120, 50), (150, 120, 40)])
                draw.rectangle([x, y_base, x + 1, y_base + 2], fill=(*c, 255))

    elif shape_name == "barrel":
        # Fass-Koerper
        for y in range(4, 13):
            w = 3 if 6 <= y <= 10 else 2
            draw.line([(8 - w, y), (8 + w, y)], fill=(*wood, 255))
        # Reifen
        draw.line([(5, 6), (11, 6)], fill=(*metal, 255))
        draw.line([(5, 10), (11, 10)], fill=(*metal, 255))

    elif shape_name == "altar":
        # Altarstein
        draw.rectangle([3, 6, 12, 10], fill=(*stone_c, 255))
        # Stufen
        draw.rectangle([2, 10, 13, 12], fill=(110, 110, 115, 255))
        # Kerzen
        draw.rectangle([4, 3, 5, 6], fill=(200, 190, 160, 255))
        draw.point((4, 2), fill=(255, 200, 60, 255))
        draw.rectangle([10, 3, 11, 6], fill=(200, 190, 160, 255))
        draw.point((10, 2), fill=(255, 200, 60, 255))

    elif shape_name == "spike_trap":
        # Boden
        draw.rectangle([1, 12, 14, 14], fill=(80, 80, 85, 255))
        # Spikes
        for x in (3, 6, 9, 12):
            draw.polygon([(x - 1, 12), (x, 4), (x + 1, 12)], fill=(*metal, 255))

    elif shape_name == "fire_trap":
        # Basis
        draw.rectangle([3, 12, 12, 14], fill=(80, 80, 85, 255))
        # Flammen
        flame_colors = [(255, 200, 60), (255, 140, 30), (220, 60, 20)]
        for x in range(4, 12):
            h = rng.randint(4, 9)
            c = rng.choice(flame_colors)
            draw.line([(x, 11), (x, h)], fill=(*c, 255))

    elif shape_name == "pit_trap":
        # Rand
        draw.rectangle([2, 2, 13, 13], fill=(60, 50, 40, 255))
        # Loch (dunkel)
        draw.rectangle([3, 3, 12, 12], fill=(10, 5, 5, 255))
        # Schatten-Gradient
        draw.rectangle([3, 3, 12, 5], fill=(30, 20, 15, 255))

    outline_pass(img)
    return img


FURNITURE_SHAPES = [
    "table", "chair", "bed", "bookshelf", "barrel", "altar",
    "spike_trap", "fire_trap", "pit_trap",
]


def generate_terrain(rng: random.Random, count: int) -> list[tuple[str, Image.Image]]:
    """Generiert Terrain- und Moebel-Sprites."""
    results = []
    # Boden-Tiles
    terrain_names = list(TERRAIN_DEFS.keys())
    for i, name in enumerate(terrain_names):
        if len(results) >= count:
            break
        base = TERRAIN_DEFS[name]
        tile = _noise_tile(rng, base)
        results.append((f"terrain_{name}.png", tile))

    # Moebel/Fallen
    for shape in FURNITURE_SHAPES:
        if len(results) >= count:
            break
        sprite = _furniture_shape(rng, shape)
        results.append((f"deko_{shape}.png", sprite))

    return results[:count]


# ═══════════════════════════════════════════════════════════════════════════════
# 3b. UMGEBUNGS-BIOM-GENERATOR (14 Biome mit je ~15 Tiles)
# ═══════════════════════════════════════════════════════════════════════════════

# Biom-Definitionen: Farben, Variationen und Deko-Objekte
BIOME_DEFS: dict[str, dict] = {
    "dungeon": {
        "floor":         (100, 100, 105),
        "floor_accent":  (90,  85,  80),
        "wall_body":     (70,  70,  75),
        "wall_edge":     (110, 108, 105),
        "variation":     15,
        "dekos":         ["torch", "chain", "crack", "spiderweb"],
        "special_color": (60,  80,  120),   # Pfuetzen-Blau
    },
    "cave": {
        "floor":         (90,  75,  55),
        "floor_accent":  (70,  60,  45),
        "wall_body":     (60,  55,  45),
        "wall_edge":     (100, 90,  70),
        "variation":     22,
        "dekos":         ["stalactite", "mushroom", "moss_patch", "bat"],
        "special_color": (40,  80,  40),    # Moos-Gruen
    },
    "crypt": {
        "floor":         (130, 125, 135),
        "floor_accent":  (100, 95,  110),
        "wall_body":     (90,  85,  100),
        "wall_edge":     (150, 145, 155),
        "variation":     10,
        "dekos":         ["sarcophagus", "urn", "candelabra", "skull"],
        "special_color": (120, 60,  160),   # Violett-Nebel
    },
    "forest": {
        "floor":         (60,  110, 50),
        "floor_accent":  (45,  90,  35),
        "wall_body":     (50,  80,  30),
        "wall_edge":     (80,  120, 55),
        "variation":     25,
        "dekos":         ["tree", "bush", "flower", "fern"],
        "special_color": (100, 200, 80),    # Sonnenlicht-Gruen
    },
    "swamp": {
        "floor":         (55,  75,  40),
        "floor_accent":  (40,  55,  30),
        "wall_body":     (45,  60,  30),
        "wall_edge":     (70,  90,  50),
        "variation":     20,
        "dekos":         ["reed", "dead_tree", "bone", "lily_pad"],
        "special_color": (60,  90,  20),    # Sumpf-Gase
    },
    "river": {
        "floor":         (60,  110, 150),
        "floor_accent":  (50,  90,  130),
        "wall_body":     (40,  70,  100),
        "wall_edge":     (80,  140, 180),
        "variation":     18,
        "dekos":         ["rock", "bridge_plank", "lily", "fish"],
        "special_color": (80,  160, 220),   # Wasser-Wellen
    },
    "beach": {
        "floor":         (195, 180, 130),
        "floor_accent":  (175, 160, 110),
        "wall_body":     (160, 140, 90),
        "wall_edge":     (210, 200, 160),
        "variation":     18,
        "dekos":         ["driftwood", "crab", "shell", "net"],
        "special_color": (120, 190, 220),   # Meeresgischt
    },
    "volcano": {
        "floor":         (40,  30,  30),
        "floor_accent":  (60,  20,  10),
        "wall_body":     (30,  20,  20),
        "wall_edge":     (80,  40,  20),
        "variation":     12,
        "dekos":         ["fire_pillar", "vent", "obsidian_shard", "ash_pile"],
        "special_color": (200, 80,  20),    # Lava-Glut
    },
    "ice": {
        "floor":         (200, 225, 240),
        "floor_accent":  (180, 210, 230),
        "wall_body":     (160, 195, 220),
        "wall_edge":     (220, 240, 250),
        "variation":     12,
        "dekos":         ["ice_crystal", "snowdrift", "icicle", "frozen_skull"],
        "special_color": (210, 240, 255),   # Eis-Funkeln
    },
    "desert": {
        "floor":         (200, 175, 100),
        "floor_accent":  (180, 155, 80),
        "wall_body":     (160, 135, 70),
        "wall_edge":     (215, 195, 130),
        "variation":     20,
        "dekos":         ["cactus", "skull_desert", "oasis_palm", "ruin_pillar"],
        "special_color": (230, 180, 60),    # Sand-Glut
    },
    "temple": {
        "floor":         (190, 170, 120),
        "floor_accent":  (160, 130, 80),
        "wall_body":     (140, 120, 70),
        "wall_edge":     (210, 190, 140),
        "variation":     10,
        "dekos":         ["statue", "banner", "altar_small", "magic_orb"],
        "special_color": (220, 180, 60),    # Goldenes Leuchten
    },
    "sewer": {
        "floor":         (80,  95,  75),
        "floor_accent":  (60,  75,  55),
        "wall_body":     (55,  65,  50),
        "wall_edge":     (100, 115, 90),
        "variation":     15,
        "dekos":         ["pipe", "grate", "rat", "slime"],
        "special_color": (50,  100, 50),    # Schimmerndes Wasser
    },
    "mine": {
        "floor":         (85,  70,  55),
        "floor_accent":  (70,  55,  40),
        "wall_body":     (60,  50,  38),
        "wall_edge":     (100, 85,  65),
        "variation":     18,
        "dekos":         ["rail", "cart", "ore_vein", "support_beam"],
        "special_color": (180, 150, 40),    # Erz-Schimmer
    },
    "underdark": {
        "floor":         (35,  25,  55),
        "floor_accent":  (25,  15,  45),
        "wall_body":     (20,  12,  40),
        "wall_edge":     (55,  40,  80),
        "variation":     12,
        "dekos":         ["glow_mushroom", "crystal_cluster", "web", "eye_stalk"],
        "special_color": (80,  40,  180),   # Biolumineszenz
    },
}


def _env_floor(rng: random.Random,
               base_color: tuple[int, int, int],
               detail_func: Callable | None = None,
               variation: int = 20,
               seed_offset: int = 0) -> Image.Image:
    """Erweitertes Noise-Boden-Tile mit optionaler Detail-Funktion."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px = img.load()
    sub_rng = random.Random(rng.getstate()[1][0] + seed_offset)
    for y in range(TILE):
        for x in range(TILE):
            # Leichtes Diagonalmuster fuer Textur
            diagonal_mod = ((x + y) % 4) * 2
            shifted = (
                clamp(base_color[0] + sub_rng.randint(-variation, variation) - diagonal_mod // 3),
                clamp(base_color[1] + sub_rng.randint(-variation, variation) - diagonal_mod // 4),
                clamp(base_color[2] + sub_rng.randint(-variation, variation)),
            )
            px[x, y] = (*shifted, 255)
    if detail_func is not None:
        detail_func(img, sub_rng)
    return img


def _env_wall(rng: random.Random,
              body_color: tuple[int, int, int],
              edge_color: tuple[int, int, int],
              pattern_func: Callable | None = None) -> Image.Image:
    """Wand-Tile: obere 60% Wand-Koerper, untere 40% Uebergang."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px = img.load()
    body_end = int(TILE * 0.60)   # y=9

    for y in range(TILE):
        for x in range(TILE):
            if y < body_end:
                # Wand-Koerper mit leichter Variation
                var = 12
                c = (
                    clamp(body_color[0] + rng.randint(-var, var)),
                    clamp(body_color[1] + rng.randint(-var, var)),
                    clamp(body_color[2] + rng.randint(-var, var)),
                )
                # Highlight oben, Schatten unten
                if y == 0:
                    c = tuple(clamp(v + 30) for v in c)
                elif y == body_end - 1:
                    c = tuple(clamp(v - 20) for v in c)
                px[x, y] = (*c, 255)
            else:
                # Uebergangs-Kante (heller)
                t = (y - body_end) / (TILE - body_end)
                c = (
                    clamp(int(body_color[0] * (1 - t) + edge_color[0] * t)
                          + rng.randint(-8, 8)),
                    clamp(int(body_color[1] * (1 - t) + edge_color[1] * t)
                          + rng.randint(-8, 8)),
                    clamp(int(body_color[2] * (1 - t) + edge_color[2] * t)
                          + rng.randint(-8, 8)),
                )
                px[x, y] = (*c, 255)

    if pattern_func is not None:
        pattern_func(img, rng, body_end)
    return img


def _wall_pattern_bricks(img: Image.Image, rng: random.Random, body_end: int) -> None:
    """Backstein-Muster auf Wand."""
    draw = ImageDraw.Draw(img)
    mortar = (50, 48, 46, 255)
    for row in range(0, body_end, 4):
        offset = 4 if (row // 4) % 2 else 0
        for x in range(-2 + offset, TILE + 2, 8):
            draw.line([(x, row), (x + 7, row)], fill=mortar)
        draw.line([(0, row + 2), (TILE, row + 2)], fill=mortar)


def _wall_pattern_rocks(img: Image.Image, rng: random.Random, body_end: int) -> None:
    """Unregelmaessige Fels-Steine."""
    draw = ImageDraw.Draw(img)
    shadow = (30, 25, 20, 180)
    for _ in range(4):
        x = rng.randint(1, TILE - 5)
        y = rng.randint(1, body_end - 3)
        w = rng.randint(3, 6)
        h = rng.randint(2, 4)
        draw.rectangle([x, y, x + w, y + h], outline=shadow)


def _wall_pattern_marble(img: Image.Image, rng: random.Random, body_end: int) -> None:
    """Marmor-Maserung."""
    draw = ImageDraw.Draw(img)
    vein = (160, 155, 165, 140)
    for _ in range(3):
        x0 = rng.randint(0, TILE)
        y0 = rng.randint(0, body_end)
        length = rng.randint(6, 12)
        angle = rng.uniform(-0.3, 0.3)
        for i in range(length):
            xi = int(x0 + i * math.cos(angle) + rng.randint(-1, 1))
            yi = int(y0 + i * math.sin(angle) + rng.randint(0, 1))
            if 0 <= xi < TILE and 0 <= yi < body_end:
                draw.point((xi, yi), fill=vein)


def _wall_pattern_wood(img: Image.Image, rng: random.Random, body_end: int) -> None:
    """Holz-Balken Wand."""
    draw = ImageDraw.Draw(img)
    grain = (50, 30, 15, 120)
    for y in range(0, body_end, 5):
        draw.line([(0, y), (TILE, y)], fill=grain)
    for _ in range(3):
        x = rng.randint(2, TILE - 2)
        draw.line([(x, 0), (x + rng.randint(-1, 1), body_end)], fill=grain)


def _wall_pattern_ice(img: Image.Image, rng: random.Random, body_end: int) -> None:
    """Eis-Wand mit Rissen."""
    draw = ImageDraw.Draw(img)
    crack = (180, 210, 235, 200)
    for _ in range(2):
        x = rng.randint(2, TILE - 2)
        y = 0
        for _ in range(8):
            nx = x + rng.randint(-2, 2)
            ny = y + rng.randint(1, 2)
            nx = clamp(nx, 0, TILE - 1)
            ny = min(ny, body_end - 1)
            draw.line([(x, y), (nx, ny)], fill=crack)
            x, y = nx, ny


def _wall_pattern_sand(img: Image.Image, rng: random.Random, body_end: int) -> None:
    """Sandstein-Schichten."""
    draw = ImageDraw.Draw(img)
    layer = (120, 100, 50, 120)
    for y in range(3, body_end, 5):
        draw.line([(0, y), (TILE, y + rng.randint(-1, 1))], fill=layer)


def _wall_pattern_lava(img: Image.Image, rng: random.Random, body_end: int) -> None:
    """Lavagestein mit Glut-Rissen."""
    draw = ImageDraw.Draw(img)
    glow = (200, 80, 20, 160)
    for _ in range(4):
        x = rng.randint(1, TILE - 1)
        y = rng.randint(1, body_end - 1)
        draw.line(
            [(x, y), (x + rng.randint(-3, 3), y + rng.randint(1, 3))],
            fill=glow,
        )


def _wall_pattern_mossy(img: Image.Image, rng: random.Random, body_end: int) -> None:
    """Moos-bedeckte Wand (Kanal/Hoehle)."""
    draw = ImageDraw.Draw(img)
    moss = (50, 90, 40, 160)
    for x in range(0, TILE, 3):
        h = rng.randint(0, 3)
        if h > 0:
            draw.line([(x, 0), (x, h)], fill=moss)
    for _ in range(6):
        px_ = rng.randint(0, TILE - 2)
        py_ = rng.randint(0, body_end - 1)
        draw.point((px_, py_), fill=moss)


def _wall_pattern_alien(img: Image.Image, rng: random.Random, body_end: int) -> None:
    """Underdark: glatte, fremdartige Strukturen."""
    draw = ImageDraw.Draw(img)
    glow = (80, 40, 180, 130)
    for _ in range(3):
        cx = rng.randint(2, TILE - 2)
        cy = rng.randint(1, body_end - 1)
        r = rng.randint(1, 3)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=glow)


# ── Detail-Funktionen fuer Boden-Tiles ──────────────────────────────────────

def _detail_stone_cracks(img: Image.Image, rng: random.Random) -> None:
    """Risse im Steinboden."""
    draw = ImageDraw.Draw(img)
    crack = (55, 55, 58, 200)
    for _ in range(rng.randint(1, 3)):
        x, y = rng.randint(1, TILE - 2), rng.randint(1, TILE - 2)
        for _ in range(rng.randint(3, 6)):
            nx = clamp(x + rng.randint(-2, 2), 0, TILE - 1)
            ny = clamp(y + rng.randint(-2, 2), 0, TILE - 1)
            draw.line([(x, y), (nx, ny)], fill=crack)
            x, y = nx, ny


def _detail_grass_blades(img: Image.Image, rng: random.Random) -> None:
    """Grashalme auf Waldboden."""
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(4, 8)):
        x = rng.randint(1, TILE - 1)
        y = rng.randint(8, TILE - 1)
        tip_x = x + rng.randint(-2, 2)
        tip_y = y - rng.randint(3, 6)
        g = rng.choice([(30, 100, 20), (50, 130, 35), (70, 150, 50)])
        draw.line([(x, y), (tip_x, tip_y)], fill=(*g, 200))


def _detail_water_ripple(img: Image.Image, rng: random.Random) -> None:
    """Wasser-Kraeusel."""
    draw = ImageDraw.Draw(img)
    ripple = (200, 230, 255, 120)
    for _ in range(rng.randint(1, 3)):
        cx = rng.randint(3, TILE - 3)
        cy = rng.randint(3, TILE - 3)
        r = rng.randint(2, 4)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ripple)


def _detail_sand_pattern(img: Image.Image, rng: random.Random) -> None:
    """Wellen-Muster im Sand."""
    draw = ImageDraw.Draw(img)
    wave = (160, 140, 80, 100)
    for y in range(2, TILE, 5):
        offset = rng.randint(-1, 1)
        draw.line([(0, y + offset), (TILE, y + offset + rng.randint(-1, 1))], fill=wave)


def _detail_lava_glow(img: Image.Image, rng: random.Random) -> None:
    """Lava-Glutpunkte auf Obsidian-Boden."""
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(2, 5)):
        x = rng.randint(1, TILE - 2)
        y = rng.randint(1, TILE - 2)
        c = rng.choice([(220, 80, 20), (255, 140, 40), (180, 50, 10)])
        draw.point((x, y), fill=(*c, 220))
        draw.point((x + 1, y), fill=(*c, 100))


def _detail_ice_sparkle(img: Image.Image, rng: random.Random) -> None:
    """Eis-Glitzer."""
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(3, 7)):
        x = rng.randint(0, TILE - 1)
        y = rng.randint(0, TILE - 1)
        draw.point((x, y), fill=(255, 255, 255, 200))


def _detail_mushroom_spores(img: Image.Image, rng: random.Random) -> None:
    """Pilz-Sporen auf Underdark-Boden."""
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(2, 5)):
        x = rng.randint(1, TILE - 1)
        y = rng.randint(1, TILE - 1)
        c = rng.choice([(100, 60, 180), (60, 140, 180), (180, 60, 120)])
        draw.point((x, y), fill=(*c, 180))


def _detail_mud_bubbles(img: Image.Image, rng: random.Random) -> None:
    """Sumpf-Blasen."""
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(1, 3)):
        x = rng.randint(2, TILE - 3)
        y = rng.randint(2, TILE - 3)
        draw.ellipse([x - 1, y - 1, x + 1, y + 1], outline=(30, 45, 20, 160))


def _detail_carpet_pattern(img: Image.Image, rng: random.Random) -> None:
    """Tempel-Teppich-Muster."""
    draw = ImageDraw.Draw(img)
    border = (180, 120, 40, 180)
    center = (160, 40, 40, 120)
    # Rahmen
    for x in range(0, TILE):
        draw.point((x, 1), fill=border)
        draw.point((x, TILE - 2), fill=border)
    for y in range(0, TILE):
        draw.point((1, y), fill=border)
        draw.point((TILE - 2, y), fill=border)
    # Mittel-Ornament
    draw.rectangle([6, 6, 9, 9], outline=center)


def _detail_ore_veins(img: Image.Image, rng: random.Random) -> None:
    """Erz-Adern im Minenboden."""
    draw = ImageDraw.Draw(img)
    ore = rng.choice([(180, 150, 40), (60, 180, 140), (180, 60, 60)])
    for _ in range(rng.randint(1, 3)):
        x = rng.randint(1, TILE - 3)
        y = rng.randint(1, TILE - 3)
        draw.rectangle([x, y, x + 1, y + 1], fill=(*ore, 180))


def _detail_sewer_algae(img: Image.Image, rng: random.Random) -> None:
    """Algen-Flecken auf Kanalboden."""
    draw = ImageDraw.Draw(img)
    algae = (40, 100, 50, 140)
    for _ in range(rng.randint(2, 5)):
        x = rng.randint(0, TILE - 2)
        y = rng.randint(0, TILE - 2)
        draw.point((x, y), fill=algae)
        draw.point((x + 1, y), fill=algae)


# Mapping Biom -> Detail-Funktion
_BIOME_FLOOR_DETAIL: dict[str, Callable | None] = {
    "dungeon":   _detail_stone_cracks,
    "cave":      _detail_stone_cracks,
    "crypt":     None,
    "forest":    _detail_grass_blades,
    "swamp":     _detail_mud_bubbles,
    "river":     _detail_water_ripple,
    "beach":     _detail_sand_pattern,
    "volcano":   _detail_lava_glow,
    "ice":       _detail_ice_sparkle,
    "desert":    _detail_sand_pattern,
    "temple":    _detail_carpet_pattern,
    "sewer":     _detail_sewer_algae,
    "mine":      _detail_ore_veins,
    "underdark": _detail_mushroom_spores,
}

# Mapping Biom -> Wand-Pattern-Funktion
_BIOME_WALL_PATTERN: dict[str, Callable | None] = {
    "dungeon":   _wall_pattern_bricks,
    "cave":      _wall_pattern_rocks,
    "crypt":     _wall_pattern_marble,
    "forest":    None,
    "swamp":     _wall_pattern_mossy,
    "river":     _wall_pattern_rocks,
    "beach":     _wall_pattern_sand,
    "volcano":   _wall_pattern_lava,
    "ice":       _wall_pattern_ice,
    "desert":    _wall_pattern_sand,
    "temple":    _wall_pattern_marble,
    "sewer":     _wall_pattern_bricks,
    "mine":      _wall_pattern_wood,
    "underdark": _wall_pattern_alien,
}


def _env_transition(rng: random.Random,
                    base_color: tuple[int, int, int],
                    variation: int,
                    direction: str = "left_to_right") -> Image.Image:
    """Halbtransparentes Uebergangs-Tile: Biom verblasst links→rechts oder rechts→links."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px = img.load()
    for y in range(TILE):
        for x in range(TILE):
            if direction == "left_to_right":
                t = x / (TILE - 1)
            else:
                t = 1.0 - x / (TILE - 1)
            # Jagged-Kante: zufaellige Welligkeit
            wave = rng.randint(-2, 2)
            effective_t = clamp(int(t * 255 + wave * 20), 0, 255) / 255.0
            alpha = int(255 * effective_t)
            if alpha < 10:
                continue
            c = color_shift(base_color, rng, variation)
            px[x, y] = (*c, alpha)
    return img


def _env_special(rng: random.Random, biome_id: str, frame: int) -> Image.Image:
    """Spezialeffekt-Tile (2 Frames fuer einfache Animation)."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bdef = BIOME_DEFS[biome_id]
    sc = bdef["special_color"]

    # Wasser / Fluss / Kanal / Sumpf: Wellen-Linien
    if biome_id in ("river", "beach", "sewer", "swamp"):
        offset = 0 if frame == 1 else 3
        for y in range(2, TILE, 4):
            for x in range(0, TILE, 2):
                xi = (x + offset) % TILE
                alpha = 180 if (x // 2) % 2 == 0 else 80
                draw.point((xi, y), fill=(*sc, alpha))
                draw.point((xi, y + 1), fill=(*sc, alpha // 2))

    # Lava / Vulkan: Glueh-Puls
    elif biome_id == "volcano":
        pulse = 200 if frame == 1 else 120
        for _ in range(6 + frame * 2):
            x = rng.randint(1, TILE - 2)
            y = rng.randint(1, TILE - 2)
            draw.point((x, y), fill=(*sc, pulse))
            draw.point((x + 1, y), fill=(sc[0] // 2, sc[1] // 2, sc[2] // 2, pulse // 2))

    # Eis: Glitzer-Funkeln
    elif biome_id == "ice":
        sparks = [(rng.randint(0, TILE - 1), rng.randint(0, TILE - 1)) for _ in range(8)]
        for i, (sx, sy) in enumerate(sparks):
            visible = (i + frame) % 2 == 0
            if visible:
                draw.point((sx, sy), fill=(255, 255, 255, 220))
                if sx + 1 < TILE:
                    draw.point((sx + 1, sy), fill=(*sc, 100))

    # Underdark: Biolumineszenz-Pulse
    elif biome_id == "underdark":
        for _ in range(4):
            cx = rng.randint(2, TILE - 3)
            cy = rng.randint(2, TILE - 3)
            r = 1 + frame
            alpha = 180 if frame == 1 else 100
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         fill=(*sc, alpha))

    # Wald: Sonnenlicht-Flecken
    elif biome_id == "forest":
        spots = [(rng.randint(2, TILE - 3), rng.randint(2, TILE - 3)) for _ in range(3)]
        shift = 1 if frame == 2 else 0
        for (sx, sy) in spots:
            alpha = 80 + shift * 40
            draw.ellipse([sx - 2, sy - 2, sx + 2, sy + 2], fill=(*sc, alpha))

    # Tempel: Goldenes Leuchten
    elif biome_id == "temple":
        alpha = 120 if frame == 1 else 60
        draw.ellipse([5, 5, 10, 10], fill=(*sc, alpha))
        draw.ellipse([6, 6, 9, 9], fill=(255, 240, 150, alpha + 40))

    # Alle anderen: subtiles Glow-Overlay
    else:
        alpha = 60 if frame == 1 else 30
        for y in range(TILE):
            for x in range(TILE):
                noise = rng.randint(0, 30)
                if noise > 20:
                    draw.point((x, y), fill=(*sc, alpha))

    return img


def _env_deko(rng: random.Random, biome_id: str, index: int) -> Image.Image:
    """Generiert biom-spezifische Deko-Objekte."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    deko_name = BIOME_DEFS[biome_id]["dekos"][index]

    # ── DUNGEON ──────────────────────────────────────────────────────────────
    if deko_name == "torch":
        # Halterung
        draw.rectangle([7, 9, 8, 13], fill=(90, 70, 50, 255))
        draw.rectangle([6, 7, 9, 9], fill=(80, 60, 40, 255))
        # Flamme (3-schichtig)
        draw.ellipse([6, 4, 9, 8], fill=(255, 200, 60, 255))
        draw.ellipse([6, 3, 9, 6], fill=(255, 140, 30, 220))
        draw.point((7, 2), fill=(255, 240, 180, 180))

    elif deko_name == "chain":
        link = (140, 140, 150, 255)
        for y in range(2, 14, 3):
            ox = 1 if (y // 3) % 2 == 0 else -1
            draw.ellipse([6 + ox, y, 9 + ox, y + 2], outline=link)

    elif deko_name == "crack":
        # Breite Mauer-Riss
        crack = (40, 40, 45, 255)
        pts = [(7, 1), (6, 4), (8, 7), (5, 10), (7, 14)]
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=crack, width=2)
        for pt in pts:
            draw.point(pt, fill=(25, 25, 28, 255))

    elif deko_name == "spiderweb":
        web = (200, 200, 210, 160)
        # Radiale Faeden
        cx, cy = 8, 5
        for angle_deg in range(0, 360, 45):
            a = math.radians(angle_deg)
            ex = int(cx + math.cos(a) * 6)
            ey = int(cy + math.sin(a) * 6)
            draw.line([(cx, cy), (ex, ey)], fill=web)
        # Konzentrische Ringe
        for r in (2, 4, 6):
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=web)

    # ── CAVE ─────────────────────────────────────────────────────────────────
    elif deko_name == "stalactite":
        stone = (80, 70, 55, 255)
        shadow = (55, 48, 38, 255)
        # Hauptzapfen von oben haengend
        draw.polygon([(6, 0), (9, 0), (7, 9)], fill=stone)
        draw.line([(7, 0), (7, 9)], fill=shadow)
        # Kleiner Nebenzapfen
        draw.polygon([(11, 0), (13, 0), (12, 5)], fill=stone)

    elif deko_name == "mushroom":
        stem = (180, 160, 130)
        cap = rng.choice([(200, 60, 40), (180, 80, 160), (60, 160, 80)])
        # Stiel
        draw.rectangle([7, 9, 8, 13], fill=(*stem, 255))
        # Kappe
        draw.ellipse([4, 5, 11, 10], fill=(*cap, 255))
        # Tupfen
        for _ in range(3):
            px_ = rng.randint(5, 10)
            py_ = rng.randint(6, 9)
            draw.point((px_, py_), fill=(255, 255, 220, 200))

    elif deko_name == "moss_patch":
        for _ in range(20):
            x = rng.randint(2, 13)
            y = rng.randint(6, 13)
            g = rng.choice([(40, 90, 30), (60, 110, 45), (50, 100, 35)])
            draw.point((x, y), fill=(*g, 220))
        # Moos-Klumpen
        draw.ellipse([4, 8, 11, 13], fill=(50, 95, 38, 180))

    elif deko_name == "bat":
        body = (60, 50, 70, 255)
        wing = (80, 65, 90, 220)
        # Koerper
        draw.ellipse([6, 6, 9, 10], fill=body)
        # Fluegel (links + rechts)
        draw.polygon([(6, 8), (2, 5), (4, 10)], fill=wing)
        draw.polygon([(9, 8), (13, 5), (11, 10)], fill=wing)
        # Ohren
        draw.polygon([(6, 6), (5, 3), (7, 5)], fill=body)
        draw.polygon([(9, 6), (10, 3), (8, 5)], fill=body)
        # Augen
        draw.point((7, 7), fill=(255, 50, 50, 255))
        draw.point((8, 7), fill=(255, 50, 50, 255))

    # ── CRYPT ────────────────────────────────────────────────────────────────
    elif deko_name == "sarcophagus":
        stone = (130, 125, 135, 255)
        dark = (90, 85, 100, 255)
        draw.rectangle([3, 4, 12, 13], fill=stone)
        draw.rectangle([2, 3, 13, 5], fill=dark)
        # Gesichts-Umriss auf Deckel
        draw.ellipse([5, 5, 10, 9], outline=dark)
        draw.line([(6, 9), (6, 12)], fill=dark)
        draw.line([(9, 9), (9, 12)], fill=dark)

    elif deko_name == "urn":
        stone = (120, 115, 130, 255)
        dark = (80, 75, 90, 255)
        # Bauch
        for y in range(5, 13):
            w = {5: 2, 6: 3, 7: 4, 8: 4, 9: 4, 10: 3, 11: 2, 12: 1}.get(y, 2)
            draw.line([(8 - w, y), (8 + w, y)], fill=stone)
        # Hals + Deckel
        draw.rectangle([6, 3, 9, 5], fill=dark)
        draw.rectangle([5, 2, 10, 3], fill=stone)

    elif deko_name == "candelabra":
        metal = (160, 150, 100, 255)
        wax = (220, 210, 180, 255)
        flame = (255, 200, 60, 255)
        # Staender
        draw.line([(7, 13), (7, 8)], fill=metal, width=2)
        draw.line([(5, 10), (9, 10)], fill=metal)
        # Kerzen
        for cx in (5, 7, 9):
            draw.rectangle([cx, 5, cx + 1, 9], fill=wax)
            draw.point((cx, 4), fill=flame)

    elif deko_name == "skull":
        bone = (210, 200, 185, 255)
        shadow = (140, 130, 115, 255)
        dark = (20, 15, 10, 255)
        # Schaedel
        draw.ellipse([4, 3, 11, 10], fill=bone)
        # Kiefer
        draw.rectangle([5, 9, 10, 12], fill=bone)
        # Augenhoehlen
        draw.ellipse([5, 5, 7, 7], fill=dark)
        draw.ellipse([8, 5, 10, 7], fill=dark)
        # Zaehne
        for tx in range(5, 11, 2):
            draw.rectangle([tx, 10, tx + 1, 12], fill=shadow)

    # ── FOREST ───────────────────────────────────────────────────────────────
    elif deko_name == "tree":
        trunk = (90, 60, 30, 255)
        leaf1 = (40, 120, 35, 255)
        leaf2 = (60, 150, 45, 255)
        # Stamm
        draw.rectangle([6, 9, 9, 14], fill=trunk)
        # Blaetter (3 Schichten)
        draw.ellipse([3, 6, 12, 12], fill=leaf1)
        draw.ellipse([4, 3, 11, 9], fill=leaf2)
        draw.ellipse([5, 1, 10, 6], fill=leaf1)

    elif deko_name == "bush":
        c1 = (50, 130, 40, 255)
        c2 = (70, 160, 55, 255)
        draw.ellipse([2, 7, 13, 14], fill=c1)
        draw.ellipse([4, 5, 11, 11], fill=c2)
        draw.ellipse([6, 8, 12, 13], fill=c1)
        # Beeren
        for _ in range(3):
            bx = rng.randint(3, 12)
            by = rng.randint(7, 13)
            draw.point((bx, by), fill=(180, 40, 40, 240))

    elif deko_name == "flower":
        stem = (50, 130, 40, 255)
        petal = rng.choice([(220, 80, 80), (220, 180, 60), (160, 80, 200), (80, 160, 220)])
        center = (255, 240, 60, 255)
        # Stiel
        draw.line([(7, 14), (7, 9)], fill=stem)
        # Blaetter
        draw.ellipse([4, 10, 7, 13], fill=stem)
        # Bluetenblaetter
        for angle_deg in range(0, 360, 60):
            a = math.radians(angle_deg)
            px_ = int(7 + math.cos(a) * 3)
            py_ = int(7 + math.sin(a) * 3)
            draw.ellipse([px_ - 1, py_ - 1, px_ + 1, py_ + 1], fill=(*petal, 255))
        draw.ellipse([6, 6, 8, 8], fill=center)

    elif deko_name == "fern":
        g = (50, 120, 35, 255)
        for i, (sx, sy, ex, ey) in enumerate([
            (7, 13, 3, 4), (7, 13, 11, 4), (7, 13, 7, 1),
            (7, 13, 4, 8), (7, 13, 10, 8),
        ]):
            draw.line([(sx, sy), (ex, ey)], fill=g)
            mx = (sx + ex) // 2
            my = (sy + ey) // 2
            draw.line([(mx - 2, my), (mx + 2, my)], fill=g)

    # ── SWAMP ────────────────────────────────────────────────────────────────
    elif deko_name == "reed":
        stem = (80, 110, 50, 255)
        head = (100, 70, 40, 255)
        for rx in (5, 8, 11):
            draw.line([(rx, 14), (rx + rng.randint(-1, 1), 2)], fill=stem)
        # Rohrkolben
        for rx in (5, 8):
            draw.rectangle([rx - 1, 4, rx + 1, 8], fill=head)

    elif deko_name == "dead_tree":
        trunk = (70, 55, 40, 255)
        draw.line([(7, 14), (7, 2)], fill=trunk, width=2)
        # Aeste
        draw.line([(7, 5), (3, 3)], fill=trunk)
        draw.line([(7, 5), (11, 2)], fill=trunk)
        draw.line([(7, 8), (4, 6)], fill=trunk)
        draw.line([(7, 8), (12, 7)], fill=trunk)

    elif deko_name == "bone":
        b = (200, 190, 170, 255)
        # Knochen-Form
        draw.line([(4, 12), (11, 4)], fill=b, width=2)
        for cx, cy in ((4, 12), (11, 4)):
            draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=b)

    elif deko_name == "lily_pad":
        pad = (50, 110, 40, 255)
        flower = (240, 200, 220, 255)
        draw.ellipse([3, 6, 12, 13], fill=pad)
        draw.line([(7, 6), (7, 9)], fill=(35, 80, 28, 255))  # Schlitz
        draw.ellipse([6, 5, 9, 8], fill=flower)

    # ── RIVER ────────────────────────────────────────────────────────────────
    elif deko_name == "rock":
        stone = (110, 105, 100, 255)
        dark = (75, 70, 65, 255)
        draw.ellipse([3, 6, 12, 13], fill=stone)
        draw.ellipse([5, 4, 10, 8], fill=stone)
        draw.ellipse([3, 7, 7, 12], fill=dark)

    elif deko_name == "bridge_plank":
        wood = (110, 80, 45, 255)
        dark = (75, 52, 28, 255)
        for y in (5, 7, 9, 11):
            draw.rectangle([1, y, 14, y + 1], fill=wood)
            draw.line([(1, y), (14, y)], fill=dark)
        # Seile
        draw.line([(1, 5), (1, 11)], fill=dark, width=2)
        draw.line([(14, 5), (14, 11)], fill=dark, width=2)

    elif deko_name == "lily":
        pad = (50, 120, 40, 255)
        flower = (240, 200, 60)
        draw.ellipse([3, 8, 13, 14], fill=pad)
        # Bluete
        for angle_deg in range(0, 360, 72):
            a = math.radians(angle_deg)
            px_ = int(8 + math.cos(a) * 2)
            py_ = int(9 + math.sin(a) * 2)
            draw.ellipse([px_, py_, px_ + 2, py_ + 2], fill=(*flower, 255))
        draw.ellipse([7, 8, 9, 10], fill=(255, 240, 100, 255))

    elif deko_name == "fish":
        body = (80, 160, 200, 255)
        belly = (200, 230, 240, 255)
        # Koerper
        draw.ellipse([3, 7, 12, 11], fill=body)
        draw.ellipse([5, 8, 11, 11], fill=belly)
        # Flosse (Schwanz)
        draw.polygon([(3, 9), (1, 7), (1, 11)], fill=body)
        # Auge
        draw.point((10, 8), fill=(20, 20, 20, 255))

    # ── BEACH ────────────────────────────────────────────────────────────────
    elif deko_name == "driftwood":
        wood = (140, 120, 90, 255)
        draw.line([(2, 10), (13, 8)], fill=wood, width=3)
        draw.line([(4, 8), (7, 12)], fill=wood, width=2)
        draw.line([(10, 6), (12, 11)], fill=wood, width=2)

    elif deko_name == "crab":
        body = (200, 100, 60, 255)
        claw = (180, 80, 50, 255)
        # Koerper
        draw.ellipse([5, 7, 10, 11], fill=body)
        # Scheren
        draw.ellipse([2, 6, 5, 9], fill=claw)
        draw.ellipse([10, 6, 13, 9], fill=claw)
        # Beine
        for lx in (4, 6, 9, 11):
            draw.line([(lx, 11), (lx - 1 + (lx > 7) * 2, 14)], fill=body)
        # Augen
        draw.point((6, 7), fill=(20, 20, 20, 255))
        draw.point((9, 7), fill=(20, 20, 20, 255))

    elif deko_name == "shell":
        base = (220, 190, 150, 255)
        stripe = (180, 140, 100, 255)
        draw.ellipse([4, 5, 11, 13], fill=base)
        # Spiralen
        for r in (1, 2, 3):
            draw.arc([8 - r, 9 - r, 8 + r, 9 + r], 0, 270, fill=stripe)

    elif deko_name == "net":
        net = (150, 130, 90, 180)
        # Diagonales Netz
        for i in range(0, TILE + 4, 4):
            draw.line([(i - 4, 0), (i, 4)], fill=net)
            draw.line([(i - 4, 0), (0, i - 4)], fill=net)
        for y in range(0, TILE, 4):
            for x in range(0, TILE, 4):
                draw.point((x, y), fill=(120, 100, 70, 220))

    # ── VOLCANO ──────────────────────────────────────────────────────────────
    elif deko_name == "fire_pillar":
        base = (60, 40, 30, 255)
        draw.rectangle([5, 10, 10, 14], fill=base)
        # Flammen-Zungen
        for fx, fh, fc in [(6, 8, (255, 200, 60)), (8, 6, (255, 140, 30)),
                           (7, 4, (220, 60, 20))]:
            draw.line([(fx, 10), (fx + rng.randint(-1, 1), fh)], fill=(*fc, 255))
        draw.ellipse([5, 6, 10, 10], fill=(255, 160, 40, 180))

    elif deko_name == "vent":
        rock = (40, 30, 25, 255)
        smoke = (80, 70, 65)
        # Vulkan-Schlot
        draw.ellipse([4, 9, 11, 14], fill=rock)
        draw.ellipse([5, 10, 10, 13], fill=(15, 10, 10, 255))
        # Rauch
        for i in range(4):
            sy = 9 - i * 2
            draw.ellipse([6 + i, sy - 1, 9 + i, sy + 1],
                         fill=(*smoke, max(10, 160 - i * 35)))

    elif deko_name == "obsidian_shard":
        obs = (30, 25, 40, 255)
        shine = (80, 60, 100, 255)
        # Kristall-Form
        draw.polygon([(7, 1), (11, 7), (9, 14), (5, 14), (3, 7)], fill=obs)
        draw.line([(7, 1), (9, 7)], fill=shine)
        draw.line([(7, 1), (5, 7)], fill=shine)

    elif deko_name == "ash_pile":
        ash = (90, 85, 80)
        dark = (60, 55, 50, 255)
        draw.ellipse([3, 10, 12, 14], fill=(*ash, 255))
        draw.ellipse([5, 9, 10, 12], fill=dark)
        # Ascheteilchen
        for _ in range(5):
            ax = rng.randint(1, TILE - 2)
            ay = rng.randint(2, 9)
            draw.point((ax, ay), fill=(*ash, 120))

    # ── ICE ──────────────────────────────────────────────────────────────────
    elif deko_name == "ice_crystal":
        ice = (180, 220, 245, 255)
        shine = (240, 250, 255, 255)
        # Hexagonaler Kristall
        pts = []
        for i in range(6):
            a = math.radians(i * 60 - 30)
            pts.append((int(8 + math.cos(a) * 5), int(8 + math.sin(a) * 5)))
        draw.polygon(pts, fill=ice)
        # Kreuz-Glanz
        draw.line([(8, 2), (8, 13)], fill=shine)
        draw.line([(2, 8), (13, 8)], fill=shine)

    elif deko_name == "snowdrift":
        snow = (230, 240, 250, 255)
        shadow = (180, 200, 220, 255)
        draw.ellipse([2, 9, 13, 14], fill=snow)
        draw.ellipse([5, 7, 11, 12], fill=snow)
        draw.ellipse([3, 10, 9, 14], fill=shadow)

    elif deko_name == "icicle":
        ice = (180, 215, 240, 255)
        tip = (210, 235, 250, 255)
        for ix, ih in [(5, 7), (8, 10), (11, 6)]:
            draw.polygon([(ix - 1, 0), (ix + 1, 0), (ix, ih)], fill=ice)
            draw.point((ix, ih), fill=tip)

    elif deko_name == "frozen_skull":
        bone = (190, 210, 225, 255)
        ice_c = (160, 200, 230, 200)
        dark = (10, 15, 20, 255)
        draw.ellipse([4, 3, 11, 10], fill=bone)
        draw.rectangle([5, 9, 10, 12], fill=bone)
        draw.ellipse([5, 5, 7, 7], fill=dark)
        draw.ellipse([8, 5, 10, 7], fill=dark)
        # Eis-Overlay
        draw.ellipse([3, 2, 12, 11], outline=(*ice_c,))

    # ── DESERT ───────────────────────────────────────────────────────────────
    elif deko_name == "cactus":
        green = (50, 130, 40, 255)
        dark_g = (35, 95, 28, 255)
        # Stamm
        draw.rectangle([6, 4, 9, 14], fill=green)
        # Arme
        draw.rectangle([3, 7, 6, 9], fill=green)
        draw.rectangle([2, 5, 4, 7], fill=green)
        draw.rectangle([9, 6, 12, 8], fill=green)
        draw.rectangle([11, 4, 13, 6], fill=green)
        # Dornen
        for dx, dy in [(4, 5), (4, 8), (11, 5), (11, 7)]:
            draw.point((dx, dy), fill=dark_g)

    elif deko_name == "skull_desert":
        # Bleicherer Wuesten-Schaedel (Sonnen-ausgeblichen)
        bone = (220, 210, 185, 255)
        shadow = (160, 148, 120, 255)
        dark = (30, 25, 15, 255)
        draw.ellipse([4, 2, 11, 9], fill=bone)
        draw.rectangle([5, 8, 10, 13], fill=bone)
        draw.ellipse([5, 4, 7, 6], fill=dark)
        draw.ellipse([8, 4, 10, 6], fill=dark)
        for tx in range(5, 11, 2):
            draw.rectangle([tx, 9, tx + 1, 12], fill=shadow)

    elif deko_name == "oasis_palm":
        trunk = (140, 100, 60, 255)
        leaf = (50, 150, 40, 255)
        # Gebogener Stamm
        for i, (tx, ty) in enumerate([(7, 14), (7, 12), (8, 10), (8, 8), (9, 6), (9, 4)]):
            draw.point((tx, ty), fill=trunk)
            if i > 0:
                draw.line([prev, (tx, ty)], fill=trunk, width=2)
            prev = (tx, ty)
        # Wedel
        for angle_deg in range(-60, 60, 20):
            a = math.radians(angle_deg - 90)
            ex = int(9 + math.cos(a) * 7)
            ey = int(4 + math.sin(a) * 7)
            draw.line([(9, 4), (ex, ey)], fill=leaf)

    elif deko_name == "ruin_pillar":
        stone = (170, 155, 120, 255)
        dark = (120, 108, 80, 255)
        # Gebrochene Saule
        draw.rectangle([5, 2, 10, 14], fill=stone)
        draw.rectangle([5, 2, 10, 3], fill=dark)   # Bruchstelle
        draw.rectangle([5, 8, 10, 9], fill=dark)   # Riss
        # Abplatzer
        draw.polygon([(5, 2), (7, 2), (5, 5)], fill=dark)
        draw.rectangle([3, 12, 12, 14], fill=stone)  # Basis

    # ── TEMPLE ───────────────────────────────────────────────────────────────
    elif deko_name == "statue":
        stone = (170, 160, 140, 255)
        dark = (120, 110, 95, 255)
        # Sockel
        draw.rectangle([4, 11, 11, 14], fill=dark)
        draw.rectangle([5, 10, 10, 11], fill=dark)
        # Figur (stilisiert)
        draw.rectangle([6, 5, 9, 10], fill=stone)   # Koerper
        draw.ellipse([5, 2, 10, 6], fill=stone)      # Kopf
        draw.line([(4, 6), (5, 9)], fill=dark, width=2)   # linker Arm
        draw.line([(10, 6), (11, 9)], fill=dark, width=2)  # rechter Arm

    elif deko_name == "banner":
        pole = (120, 100, 60, 255)
        fabric = rng.choice([(180, 40, 40), (40, 60, 180), (40, 140, 60)])
        # Stange
        draw.line([(7, 1), (7, 14)], fill=pole, width=2)
        # Fahne
        draw.polygon([(7, 2), (13, 5), (7, 8)], fill=(*fabric, 255))
        # Muster auf Fahne
        draw.line([(8, 4), (11, 5)], fill=(255, 220, 60, 180))

    elif deko_name == "altar_small":
        stone = (160, 145, 110, 255)
        dark = (110, 98, 70, 255)
        glow = (255, 200, 60, 220)
        # Tischplatte
        draw.rectangle([3, 6, 12, 9], fill=stone)
        draw.rectangle([2, 9, 13, 11], fill=dark)
        # Kerzen
        draw.rectangle([4, 2, 5, 6], fill=(210, 200, 170, 255))
        draw.point((4, 1), fill=glow)
        draw.rectangle([10, 2, 11, 6], fill=(210, 200, 170, 255))
        draw.point((10, 1), fill=glow)
        # Heiliges Symbol
        draw.line([(7, 6), (7, 9)], fill=glow)
        draw.line([(5, 7), (9, 7)], fill=glow)

    elif deko_name == "magic_orb":
        core = (100, 60, 220, 255)
        glow_c = (160, 120, 255, 180)
        outer = (80, 40, 180, 100)
        # Stand
        draw.rectangle([6, 12, 9, 14], fill=(100, 80, 60, 255))
        draw.rectangle([5, 11, 10, 13], fill=(80, 65, 45, 255))
        # Kugel
        draw.ellipse([3, 4, 12, 13], fill=(*outer,))
        draw.ellipse([4, 5, 11, 12], fill=(*glow_c,))
        draw.ellipse([5, 6, 10, 11], fill=core)
        draw.point((7, 8), fill=(220, 200, 255, 255))

    # ── SEWER ────────────────────────────────────────────────────────────────
    elif deko_name == "pipe":
        metal = (100, 110, 100, 255)
        rust = (140, 90, 60, 255)
        dark = (60, 65, 60, 255)
        # Horizontales Rohr
        draw.rectangle([1, 6, 14, 10], fill=metal)
        draw.rectangle([1, 6, 14, 7], fill=(130, 140, 130, 255))  # Highlight
        draw.rectangle([1, 9, 14, 10], fill=dark)
        # Flansche
        draw.rectangle([3, 5, 5, 11], fill=dark)
        draw.rectangle([10, 5, 12, 11], fill=dark)
        # Rost-Flecken
        for _ in range(3):
            rx = rng.randint(2, 12)
            draw.point((rx, 8), fill=rust)

    elif deko_name == "grate":
        metal = (90, 95, 90, 255)
        dark = (50, 55, 50, 255)
        # Gitter-Rahmen
        draw.rectangle([2, 2, 13, 13], outline=metal, width=2)
        # Gitterstabe horizontal
        for y in range(4, 13, 3):
            draw.line([(2, y), (13, y)], fill=metal)
        # Gitterstabe vertikal
        for x in range(4, 13, 3):
            draw.line([(x, 2), (x, 13)], fill=metal)
        # Schatten
        draw.rectangle([3, 3, 12, 12], outline=dark)

    elif deko_name == "rat":
        body = (100, 85, 75, 255)
        belly = (140, 125, 110, 255)
        dark = (60, 50, 42, 255)
        # Koerper
        draw.ellipse([3, 7, 11, 12], fill=body)
        draw.ellipse([5, 8, 10, 12], fill=belly)
        # Kopf
        draw.ellipse([9, 5, 14, 10], fill=body)
        # Nase
        draw.point((13, 7), fill=(180, 100, 100, 255))
        # Augen
        draw.point((11, 6), fill=(20, 20, 20, 255))
        # Schwanz
        draw.line([(3, 10), (0, 12)], fill=dark, width=2)
        # Ohren
        draw.ellipse([10, 4, 12, 6], fill=body)

    elif deko_name == "slime":
        slime_c = (60, 160, 60, 220)
        dark_s = (30, 100, 30, 200)
        # Schleimige Masse
        draw.ellipse([3, 8, 12, 14], fill=slime_c)
        draw.ellipse([5, 6, 10, 11], fill=slime_c)
        draw.ellipse([4, 9, 9, 14], fill=dark_s)
        # Augen (aufgestellt)
        draw.ellipse([5, 5, 7, 8], fill=(200, 220, 200, 255))
        draw.ellipse([9, 6, 11, 9], fill=(200, 220, 200, 255))
        draw.point((6, 6), fill=(20, 20, 20, 255))
        draw.point((10, 7), fill=(20, 20, 20, 255))

    # ── MINE ─────────────────────────────────────────────────────────────────
    elif deko_name == "rail":
        metal = (130, 125, 120, 255)
        wood = (100, 75, 45, 255)
        # Schienen
        draw.line([(0, 9), (15, 9)], fill=metal, width=2)
        draw.line([(0, 12), (15, 12)], fill=metal, width=2)
        # Schwellen
        for x in range(1, TILE - 1, 4):
            draw.rectangle([x, 8, x + 2, 13], fill=wood)

    elif deko_name == "cart":
        wood = (100, 75, 45, 255)
        metal = (120, 118, 115, 255)
        dark = (60, 45, 28, 255)
        # Kasten
        draw.rectangle([2, 5, 13, 11], fill=wood)
        draw.rectangle([2, 5, 13, 6], fill=dark)    # Rahmen oben
        draw.rectangle([2, 10, 13, 11], fill=dark)  # Rahmen unten
        # Raeder
        draw.ellipse([2, 10, 5, 13], fill=dark, outline=metal)
        draw.ellipse([10, 10, 13, 13], fill=dark, outline=metal)
        # Inhalt (Erzbrocken)
        for _ in range(3):
            ex = rng.randint(3, 11)
            ey = rng.randint(6, 9)
            c = rng.choice([(150, 120, 40), (80, 140, 120), (140, 80, 80)])
            draw.rectangle([ex, ey, ex + 1, ey + 1], fill=(*c, 255))

    elif deko_name == "ore_vein":
        rock = (80, 70, 55, 255)
        ore = rng.choice([(180, 150, 40), (60, 180, 140), (180, 80, 60)])
        # Felsen-Hintergrund
        draw.rectangle([2, 3, 13, 13], fill=rock)
        draw.rectangle([2, 3, 13, 4], fill=(100, 90, 72, 255))
        # Erz-Adern
        for _ in range(4):
            x1 = rng.randint(2, 10)
            y1 = rng.randint(4, 11)
            x2 = x1 + rng.randint(2, 4)
            y2 = y1 + rng.randint(-1, 2)
            draw.line([(x1, y1), (x2, y2)], fill=(*ore, 255), width=2)
            draw.point((x1, y1), fill=(255, 255, 200, 180))  # Glanz

    elif deko_name == "support_beam":
        wood = (100, 75, 45, 255)
        dark = (65, 48, 28, 255)
        # Vertikale Balken
        draw.rectangle([2, 0, 4, 15], fill=wood)
        draw.rectangle([11, 0, 13, 15], fill=wood)
        # Querbalken
        draw.rectangle([2, 4, 13, 6], fill=wood)
        draw.rectangle([2, 10, 13, 12], fill=dark)
        # Holz-Maserung
        for y in range(2, 14, 3):
            draw.line([(2, y), (4, y)], fill=dark)

    # ── UNDERDARK ────────────────────────────────────────────────────────────
    elif deko_name == "glow_mushroom":
        stem = (80, 70, 100, 255)
        cap_base = rng.choice([(60, 180, 140), (140, 60, 180), (80, 160, 200)])
        glow_a = (min(cap_base[0] + 80, 255), min(cap_base[1] + 80, 255),
                  min(cap_base[2] + 80, 255))
        # Stiel
        draw.rectangle([7, 10, 8, 14], fill=stem)
        # Leuchtende Kappe
        draw.ellipse([4, 6, 11, 11], fill=(*cap_base, 255))
        draw.ellipse([5, 5, 10, 9], fill=(*glow_a, 200))
        # Leuchtpunkte
        for _ in range(4):
            gx = rng.randint(5, 10)
            gy = rng.randint(6, 10)
            draw.point((gx, gy), fill=(255, 255, 200, 220))

    elif deko_name == "crystal_cluster":
        base_c = rng.choice([(80, 40, 180), (40, 160, 180), (180, 60, 120)])
        shine = (min(base_c[0] + 100, 255), min(base_c[1] + 100, 255),
                 min(base_c[2] + 100, 255))
        for cx, cy, h in [(5, 12, 8), (8, 12, 11), (11, 12, 7), (6, 12, 6), (10, 12, 9)]:
            draw.polygon([(cx - 1, cy), (cx + 1, cy), (cx, cy - h)],
                         fill=(*base_c, 255))
            draw.line([(cx, cy), (cx, cy - h)], fill=(*shine, 180))

    elif deko_name == "web":
        web_c = (200, 195, 210, 150)
        # Radiales Netz (dunkle Hoehle-Version)
        cx, cy = 8, 6
        for angle_deg in range(0, 360, 40):
            a = math.radians(angle_deg)
            ex = int(cx + math.cos(a) * 7)
            ey = int(cy + math.sin(a) * 7)
            draw.line([(cx, cy), (ex, ey)], fill=web_c)
        for r in (2, 4, 6):
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=web_c)
        # Spinne in der Mitte
        draw.ellipse([7, 5, 9, 7], fill=(30, 25, 35, 255))

    elif deko_name == "eye_stalk":
        stalk = (50, 40, 70, 255)
        eyeball = (200, 195, 210, 255)
        pupil = (180, 40, 60, 255)
        iris = (80, 20, 100, 255)
        # Stiel (gewunden)
        pts = [(8, 14), (7, 11), (9, 8), (7, 6)]
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=stalk, width=2)
        # Auge
        draw.ellipse([4, 2, 11, 7], fill=eyeball)
        draw.ellipse([5, 3, 10, 6], fill=iris)
        draw.ellipse([6, 3, 9, 6], fill=pupil)
        draw.point((7, 4), fill=(255, 255, 255, 200))  # Glanzpunkt

    else:
        # Fallback: generisches Objekt
        draw.rectangle([4, 4, 11, 11], fill=(120, 100, 80, 255))
        draw.ellipse([5, 5, 10, 10], fill=(160, 140, 110, 255))

    outline_pass(img)
    return img


def generate_environments(rng: random.Random,
                          count: int,
                          biome_filter: str | None = None) -> list[tuple[str, Image.Image]]:
    """Generiert alle 14 Biome mit je 15 Tiles (oder gefiltert nach biome_filter)."""
    results: list[tuple[str, Image.Image]] = []

    biomes = [biome_filter] if biome_filter else list(BIOME_DEFS.keys())

    for biome_id in biomes:
        if len(results) >= count:
            break
        bdef = BIOME_DEFS[biome_id]
        floor_c    = bdef["floor"]
        accent_c   = bdef["floor_accent"]
        wall_body  = bdef["wall_body"]
        wall_edge  = bdef["wall_edge"]
        variation  = bdef["variation"]
        detail_fn  = _BIOME_FLOOR_DETAIL.get(biome_id)
        wall_pat   = _BIOME_WALL_PATTERN.get(biome_id)

        # Basis-Seed fuer diesen Biom (reproduzierbar)
        biome_seed = abs(hash(biome_id)) % (2 ** 31)
        biome_rng  = random.Random(rng.getstate()[1][0] ^ biome_seed)

        # 1. Boden-Varianten (floor + v1 + v2 + v3)
        for v_idx, suffix in enumerate(["", "_v1", "_v2", "_v3"]):
            if len(results) >= count:
                break
            tile = _env_floor(biome_rng, floor_c, detail_fn, variation, seed_offset=v_idx * 17)
            results.append((f"env_{biome_id}_floor{suffix}.png", tile))

        # 2. Akzent-Boden
        if len(results) < count:
            accent = _env_floor(biome_rng, accent_c, detail_fn, variation // 2, seed_offset=99)
            results.append((f"env_{biome_id}_floor_accent.png", accent))

        # 3. Wand-Vorderseite
        if len(results) < count:
            wall_f = _env_wall(biome_rng, wall_body, wall_edge, wall_pat)
            results.append((f"env_{biome_id}_wall_front.png", wall_f))

        # 4. Wand-Oberkante (heller, schmaeleres Muster)
        if len(results) < count:
            top_body = tuple(clamp(v + 20) for v in wall_body)
            wall_t = _env_wall(biome_rng, top_body, wall_edge, None)
            results.append((f"env_{biome_id}_wall_top.png", wall_t))

        # 5. Deko-Objekte (4 Stueck)
        for d_idx in range(4):
            if len(results) >= count:
                break
            deko = _env_deko(biome_rng, biome_id, d_idx)
            results.append((f"env_{biome_id}_deko_0{d_idx + 1}.png", deko))

        # 6. Uebergangs-Tiles (links→rechts und rechts→links)
        for t_idx, direction in enumerate(["left_to_right", "right_to_left"]):
            if len(results) >= count:
                break
            trans = _env_transition(biome_rng, floor_c, variation, direction)
            results.append((f"env_{biome_id}_transition_0{t_idx + 1}.png", trans))

        # 7. Spezial-Frames (2 Animationsframes)
        for s_idx in range(1, 3):
            if len(results) >= count:
                break
            special = _env_special(biome_rng, biome_id, s_idx)
            results.append((f"env_{biome_id}_special_0{s_idx}.png", special))

    return results[:count]


# ═══════════════════════════════════════════════════════════════════════════════
# 3b. CAVE EXTENDED — 68 Hoehlen-spezifische Tiles fuer organische Weltkarte
# ═══════════════════════════════════════════════════════════════════════════════

# Farb-Definitionen fuer Cave-Tiles
_CAVE_STONE   = (90, 75, 55)
_CAVE_DARK    = (55, 48, 38)
_CAVE_SHADOW  = (35, 30, 25)
_CAVE_WET     = (70, 65, 60)
_CAVE_MOSS    = (45, 85, 35)
_CAVE_CRYSTAL = (120, 180, 220)
_CAVE_GLOW    = (80, 200, 120)
_CAVE_MUD     = (75, 60, 40)
_CAVE_WATER   = (40, 70, 110)


def _cave_stalagmite(rng: random.Random, size: str) -> Image.Image:
    """Stalagmit (Boden-Zapfen): tiny/small/medium/large/cluster/twin/broken/wide."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    stone = color_shift(_CAVE_STONE, rng, 12)
    dark = color_shift(_CAVE_DARK, rng, 8)
    hi = tuple(clamp(c + 30) for c in stone)

    if size == "tiny":
        draw.polygon([(7, 14), (8, 14), (7, 10)], fill=(*stone, 255))
        draw.line([(7, 14), (7, 10)], fill=(*dark, 255))
    elif size == "small":
        draw.polygon([(6, 14), (9, 14), (7, 8)], fill=(*stone, 255))
        draw.line([(7, 8), (7, 14)], fill=(*hi, 180))
        draw.line([(6, 14), (7, 8)], fill=(*dark, 200))
    elif size == "medium":
        draw.polygon([(5, 14), (10, 14), (7, 5)], fill=(*stone, 255))
        draw.line([(7, 5), (8, 14)], fill=(*hi, 180))
        draw.line([(5, 14), (7, 5)], fill=(*dark, 200))
        # Textur-Ringe
        for ry in (8, 11):
            draw.line([(6, ry), (9, ry)], fill=(*dark, 120))
    elif size == "large":
        draw.polygon([(4, 15), (11, 15), (7, 2)], fill=(*stone, 255))
        draw.line([(7, 2), (9, 15)], fill=(*hi, 180))
        draw.line([(4, 15), (7, 2)], fill=(*dark, 200))
        for ry in (5, 8, 11):
            draw.line([(5, ry), (10, ry)], fill=(*dark, 100))
    elif size == "cluster":
        # 3 Stalagmiten zusammen
        draw.polygon([(3, 14), (6, 14), (4, 6)], fill=(*stone, 255))
        draw.polygon([(6, 14), (10, 14), (8, 3)], fill=(*stone, 255))
        draw.polygon([(10, 14), (13, 14), (11, 8)], fill=(*stone, 255))
        draw.line([(4, 6), (5, 14)], fill=(*hi, 160))
        draw.line([(8, 3), (9, 14)], fill=(*hi, 160))
    elif size == "twin":
        draw.polygon([(3, 14), (7, 14), (5, 4)], fill=(*stone, 255))
        draw.polygon([(8, 14), (12, 14), (10, 6)], fill=(*stone, 255))
        draw.line([(5, 4), (6, 14)], fill=(*hi, 160))
        draw.line([(10, 6), (11, 14)], fill=(*hi, 160))
    elif size == "broken":
        # Abgebrochener Stalagmit
        draw.polygon([(4, 14), (11, 14), (5, 8), (10, 8)], fill=(*stone, 255))
        draw.line([(5, 8), (10, 8)], fill=(*hi, 200))  # Bruchkante
        draw.point((7, 9), fill=(*dark, 255))
    elif size == "wide":
        # Breiter, flacher Stalagmit
        draw.polygon([(2, 15), (13, 15), (7, 7)], fill=(*stone, 255))
        draw.line([(7, 7), (10, 15)], fill=(*hi, 150))
        for ry in (9, 12):
            draw.line([(4, ry), (11, ry)], fill=(*dark, 100))

    outline_pass(img)
    return img


def _cave_stalactite_ext(rng: random.Random, variant: str) -> Image.Image:
    """Stalaktit-Varianten (haengend von oben)."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    stone = color_shift(_CAVE_STONE, rng, 12)
    dark = color_shift(_CAVE_DARK, rng, 8)

    if variant == "dripping":
        draw.polygon([(5, 0), (10, 0), (7, 10)], fill=(*stone, 255))
        draw.line([(7, 0), (7, 10)], fill=(*dark, 200))
        # Wassertropfen
        draw.ellipse([6, 11, 8, 13], fill=(*_CAVE_WATER, 200))
    elif variant == "cluster":
        for cx, tip_y in [(4, 7), (7, 11), (11, 6), (13, 4)]:
            w = rng.randint(1, 2)
            draw.polygon([(cx - w, 0), (cx + w, 0), (cx, tip_y)], fill=(*stone, 255))
    elif variant == "thick":
        draw.polygon([(3, 0), (12, 0), (8, 12), (6, 12)], fill=(*stone, 255))
        draw.line([(7, 0), (7, 12)], fill=(*dark, 180))
        draw.line([(5, 0), (6, 12)], fill=(*dark, 120))
    elif variant == "icicle":
        # Duenner, langer Stalaktit
        draw.polygon([(6, 0), (9, 0), (7, 14)], fill=(*stone, 255))
        draw.line([(7, 0), (7, 14)], fill=(*dark, 200))

    outline_pass(img)
    return img


def _cave_rock_formation(rng: random.Random, variant: str) -> Image.Image:
    """Felsformationen verschiedener Art."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    stone = color_shift(_CAVE_STONE, rng, 15)
    dark = color_shift(_CAVE_DARK, rng, 10)
    hi = tuple(clamp(c + 25) for c in stone)

    if variant == "boulder_small":
        draw.ellipse([4, 7, 11, 14], fill=(*stone, 255))
        draw.ellipse([5, 8, 9, 12], fill=(*hi, 200))
        draw.arc([4, 7, 11, 14], 200, 340, fill=(*dark, 200))
    elif variant == "boulder_large":
        draw.ellipse([2, 4, 13, 15], fill=(*stone, 255))
        draw.ellipse([3, 5, 10, 12], fill=(*hi, 180))
        draw.arc([2, 4, 13, 15], 180, 350, fill=(*dark, 200))
    elif variant == "rock_pile":
        for _ in range(4):
            rx = rng.randint(2, 10)
            ry = rng.randint(7, 12)
            rr = rng.randint(2, 4)
            c = color_shift(stone, rng, 10)
            draw.ellipse([rx, ry, rx + rr, ry + rr], fill=(*c, 255))
    elif variant == "ledge":
        # Felsvorsprung
        draw.polygon([(0, 5), (15, 7), (15, 10), (0, 8)], fill=(*stone, 255))
        draw.line([(0, 5), (15, 7)], fill=(*hi, 200))
        draw.line([(0, 8), (15, 10)], fill=(*dark, 200))
    elif variant == "column_natural":
        # Natuerliche Felssaeule (Stalagmit+Stalaktit verbunden)
        draw.polygon([(5, 0), (10, 0), (11, 15), (4, 15)], fill=(*stone, 255))
        draw.line([(7, 0), (7, 15)], fill=(*hi, 140))
        draw.line([(5, 0), (4, 15)], fill=(*dark, 160))
        # Verdickung in der Mitte
        draw.ellipse([3, 6, 12, 10], fill=(*stone, 220))
    elif variant == "slab":
        # Flache Steinplatte
        draw.polygon([(1, 10), (14, 9), (15, 13), (0, 14)], fill=(*stone, 255))
        draw.line([(1, 10), (14, 9)], fill=(*hi, 200))
    elif variant == "arch":
        # Natuerlicher Felsbogen
        draw.arc([2, 2, 13, 14], 180, 360, fill=(*stone, 255), width=3)
        draw.rectangle([2, 8, 4, 15], fill=(*stone, 255))
        draw.rectangle([11, 8, 13, 15], fill=(*stone, 255))
    elif variant == "overhang":
        # Ueberhang von oben
        draw.polygon([(0, 0), (15, 0), (12, 8), (0, 6)], fill=(*stone, 255))
        draw.line([(0, 6), (12, 8)], fill=(*dark, 200))

    outline_pass(img)
    return img


def _cave_puddle(rng: random.Random, variant: str) -> Image.Image:
    """Pfuetzen und kleine Wasserflaechen."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    water = color_shift(_CAVE_WATER, rng, 10)
    hi = tuple(clamp(c + 40) for c in water)
    dark = tuple(clamp(c - 20) for c in water)

    if variant == "small":
        draw.ellipse([5, 8, 10, 13], fill=(*water, 200))
        draw.point((7, 10), fill=(*hi, 220))
    elif variant == "medium":
        draw.ellipse([3, 5, 12, 14], fill=(*water, 200))
        draw.ellipse([4, 6, 10, 12], fill=(*hi, 140))
        draw.point((6, 8), fill=(*hi, 255))
    elif variant == "large":
        draw.ellipse([1, 3, 14, 14], fill=(*water, 200))
        draw.ellipse([3, 5, 11, 11], fill=(*hi, 140))
        # Wellenringe
        draw.arc([4, 6, 9, 10], 0, 360, fill=(*hi, 120))
    elif variant == "edge":
        # Pfuetze am Rand einer Wand
        draw.chord([0, 6, 10, 15], 270, 90, fill=(*water, 200))
        draw.point((3, 10), fill=(*hi, 220))
    elif variant == "drip_pool":
        # Kleine Pfuetze mit Tropf-Ringen
        draw.ellipse([4, 8, 11, 14], fill=(*water, 200))
        draw.arc([5, 9, 10, 13], 0, 360, fill=(*hi, 160))
        draw.arc([6, 10, 9, 12], 0, 360, fill=(*hi, 200))
    elif variant == "stream":
        # Duenner Wasserlauf
        pts = [(2, 0), (4, 4), (3, 8), (5, 12), (4, 15)]
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=(*water, 200), width=3)
        draw.line([pts[0], pts[1]], fill=(*hi, 160), width=1)

    return img


def _cave_moss(rng: random.Random, variant: str) -> Image.Image:
    """Moos, Pilze und biologisches Material."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if variant == "floor_moss":
        # Dichter Moosteppich
        for _ in range(40):
            x = rng.randint(0, 15)
            y = rng.randint(0, 15)
            g = rng.choice([(40, 90, 30), (55, 105, 40), (35, 75, 25), (50, 95, 35)])
            draw.point((x, y), fill=(*g, rng.randint(140, 240)))
    elif variant == "wall_moss":
        # Moos an der oberen Haelfte (haengt von Wand)
        for _ in range(35):
            x = rng.randint(0, 15)
            y = rng.randint(0, 10)
            g = rng.choice([(40, 90, 30), (50, 100, 35)])
            draw.point((x, y), fill=(*g, rng.randint(120, 220)))
        # Haengende Faeden
        for x in range(0, 16, 3):
            length = rng.randint(3, 8)
            for dy in range(length):
                alpha = 200 - dy * 20
                if alpha > 0:
                    draw.point((x + rng.randint(-1, 1), dy), fill=(40, 85, 30, alpha))
    elif variant == "mushroom_cluster":
        for _ in range(4):
            mx = rng.randint(2, 12)
            my = rng.randint(6, 13)
            cap = rng.choice([(180, 60, 40), (160, 80, 150), (60, 150, 70), (200, 180, 50)])
            draw.rectangle([mx, my + 2, mx + 1, my + 4], fill=(170, 150, 120, 255))
            draw.ellipse([mx - 2, my, mx + 3, my + 3], fill=(*cap, 255))
    elif variant == "glowing_fungus":
        glow = color_shift(_CAVE_GLOW, rng, 20)
        for _ in range(5):
            mx = rng.randint(1, 13)
            my = rng.randint(4, 13)
            r = rng.randint(1, 2)
            draw.ellipse([mx - r - 1, my - r - 1, mx + r + 1, my + r + 1],
                         fill=(*glow, 60))
            draw.ellipse([mx - r, my - r, mx + r, my + r], fill=(*glow, 180))
    elif variant == "lichen":
        # Flechten (kreisfoermig)
        for _ in range(6):
            cx = rng.randint(2, 13)
            cy = rng.randint(2, 13)
            r = rng.randint(1, 3)
            c = rng.choice([(120, 130, 80), (100, 110, 60), (90, 120, 70)])
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*c, 200))
    elif variant == "vine":
        # Ranken
        vine_c = (50, 100, 40, 220)
        x = rng.randint(3, 12)
        for y in range(0, 15):
            x += rng.randint(-1, 1)
            x = clamp(x, 1, 14)
            draw.point((x, y), fill=vine_c)
            if rng.random() < 0.3:
                draw.point((x + rng.choice([-1, 1]), y), fill=(60, 110, 45, 180))
    elif variant == "fungal_floor":
        # Pilz-Boden (flach)
        for _ in range(25):
            x = rng.randint(0, 15)
            y = rng.randint(8, 15)
            c = rng.choice([(160, 140, 100), (140, 120, 80), (120, 100, 70)])
            draw.point((x, y), fill=(*c, rng.randint(150, 240)))
        # Einige kleine Pilzkoepfe
        for _ in range(3):
            px_ = rng.randint(2, 13)
            py_ = rng.randint(9, 14)
            cap = rng.choice([(200, 60, 40), (60, 160, 80)])
            draw.ellipse([px_ - 1, py_ - 1, px_ + 1, py_], fill=(*cap, 220))
    elif variant == "spore_cloud":
        # Sporenstaub in der Luft
        for _ in range(30):
            x = rng.randint(0, 15)
            y = rng.randint(0, 15)
            alpha = rng.randint(40, 120)
            c = rng.choice([(180, 200, 100), (160, 180, 80), (200, 220, 120)])
            draw.point((x, y), fill=(*c, alpha))

    return img


def _cave_crystal(rng: random.Random, variant: str) -> Image.Image:
    """Kristallformationen."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    crystal = color_shift(_CAVE_CRYSTAL, rng, 20)
    hi = tuple(clamp(c + 50) for c in crystal)
    dark = tuple(clamp(c - 40) for c in crystal)

    if variant == "small":
        draw.polygon([(6, 14), (9, 14), (8, 7), (7, 6)], fill=(*crystal, 220))
        draw.line([(7, 6), (8, 14)], fill=(*hi, 200))
    elif variant == "large":
        draw.polygon([(4, 15), (7, 15), (6, 3), (5, 2)], fill=(*crystal, 220))
        draw.polygon([(8, 15), (11, 15), (10, 5), (9, 4)], fill=(*crystal, 200))
        draw.line([(5, 2), (6, 15)], fill=(*hi, 220))
        draw.line([(9, 4), (10, 15)], fill=(*hi, 200))
    elif variant == "cluster":
        for _ in range(5):
            cx = rng.randint(2, 12)
            tip = rng.randint(2, 8)
            base_y = rng.randint(11, 14)
            w = rng.randint(1, 2)
            c = color_shift(crystal, rng, 30)
            draw.polygon([(cx - w, base_y), (cx + w, base_y), (cx, tip)],
                         fill=(*c, rng.randint(180, 240)))
    elif variant == "glowing":
        # Leuchtender Kristall mit Glow-Effekt
        glow = color_shift(_CAVE_GLOW, rng, 15)
        # Glow-Halo
        draw.ellipse([2, 2, 13, 13], fill=(*glow, 40))
        draw.ellipse([4, 4, 11, 11], fill=(*glow, 60))
        # Kristall
        draw.polygon([(6, 14), (9, 14), (8, 4), (7, 3)], fill=(*crystal, 240))
        draw.line([(7, 3), (8, 14)], fill=(*hi, 255))
    elif variant == "amethyst":
        purple = color_shift((150, 80, 200), rng, 15)
        hi_p = tuple(clamp(c + 40) for c in purple)
        for _ in range(4):
            cx = rng.randint(3, 11)
            tip = rng.randint(3, 7)
            draw.polygon([(cx - 1, 14), (cx + 1, 14), (cx, tip)],
                         fill=(*purple, 230))
            draw.line([(cx, tip), (cx, 14)], fill=(*hi_p, 200))
    elif variant == "vein":
        # Ader im Stein
        x = rng.randint(2, 5)
        for y in range(0, 16):
            x += rng.randint(-1, 1)
            x = clamp(x, 0, 15)
            for dx in range(-1, 2):
                nx = clamp(x + dx, 0, 15)
                alpha = 220 if dx == 0 else 140
                draw.point((nx, y), fill=(*crystal, alpha))

    outline_pass(img)
    return img


def _cave_debris(rng: random.Random, variant: str) -> Image.Image:
    """Schutt, Truemmer, Gestein."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    stone = color_shift(_CAVE_STONE, rng, 15)
    dark = color_shift(_CAVE_DARK, rng, 10)

    if variant == "gravel":
        for _ in range(20):
            x = rng.randint(1, 14)
            y = rng.randint(8, 14)
            c = color_shift(stone, rng, 18)
            s = rng.randint(1, 2)
            draw.rectangle([x, y, x + s, y + s], fill=(*c, 255))
    elif variant == "rubble_small":
        for _ in range(6):
            x = rng.randint(2, 11)
            y = rng.randint(7, 13)
            w = rng.randint(2, 4)
            h = rng.randint(1, 3)
            c = color_shift(stone, rng, 15)
            draw.rectangle([x, y, x + w, y + h], fill=(*c, 255))
            draw.line([(x, y), (x + w, y)], fill=(*dark, 150))
    elif variant == "rubble_large":
        for _ in range(4):
            x = rng.randint(1, 9)
            y = rng.randint(4, 11)
            w = rng.randint(3, 6)
            h = rng.randint(2, 4)
            c = color_shift(stone, rng, 15)
            draw.rectangle([x, y, x + w, y + h], fill=(*c, 255))
            draw.line([(x, y), (x + w, y)], fill=(*tuple(clamp(v + 20) for v in c), 200))
    elif variant == "collapsed":
        # Eingestuerzte Decke
        for _ in range(8):
            pts = []
            cx = rng.randint(1, 13)
            cy = rng.randint(2, 12)
            for _ in range(rng.randint(3, 5)):
                pts.append((clamp(cx + rng.randint(-3, 3), 0, 15),
                            clamp(cy + rng.randint(-2, 2), 0, 15)))
            if len(pts) >= 3:
                c = color_shift(stone, rng, 18)
                draw.polygon(pts, fill=(*c, 255))
    elif variant == "bone_pile":
        bone = (200, 195, 180, 255)
        bone_d = (160, 155, 140, 255)
        for _ in range(5):
            x = rng.randint(3, 11)
            y = rng.randint(8, 13)
            length = rng.randint(3, 6)
            angle = rng.uniform(0, math.pi)
            x2 = int(x + math.cos(angle) * length)
            y2 = int(y + math.sin(angle) * length)
            draw.line([(x, y), (x2, y2)], fill=bone, width=1)
        # Schaedel
        draw.ellipse([6, 9, 10, 13], fill=bone)
        draw.point((7, 10), fill=bone_d)
        draw.point((9, 10), fill=bone_d)
    elif variant == "dust":
        # Staub/Sand auf Boden
        for _ in range(35):
            x = rng.randint(0, 15)
            y = rng.randint(0, 15)
            c = color_shift(_CAVE_MUD, rng, 12)
            draw.point((x, y), fill=(*c, rng.randint(80, 180)))
    elif variant == "crack_floor":
        # Bodenriss
        dark_c = (40, 35, 30, 255)
        x = rng.randint(3, 12)
        y = 0
        for _ in range(rng.randint(8, 14)):
            nx = clamp(x + rng.randint(-2, 2), 0, 15)
            ny = clamp(y + rng.randint(1, 2), 0, 15)
            draw.line([(x, y), (nx, ny)], fill=dark_c, width=rng.choice([1, 2]))
            x, y = nx, ny
            if y >= 15:
                break
    elif variant == "wet_rocks":
        # Nasse Felsbroecken
        for _ in range(5):
            x = rng.randint(2, 11)
            y = rng.randint(6, 13)
            w = rng.randint(2, 4)
            h = rng.randint(2, 3)
            c = color_shift(_CAVE_WET, rng, 10)
            draw.ellipse([x, y, x + w, y + h], fill=(*c, 255))
            # Naesse-Highlight
            draw.point((x + 1, y), fill=(*tuple(clamp(v + 30) for v in c), 180))

    outline_pass(img)
    return img


def _cave_floor_variant(rng: random.Random, variant: str) -> Image.Image:
    """Boden-Varianten fuer Hoehlen."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px = img.load()
    draw = ImageDraw.Draw(img)

    if variant == "wet":
        base = _CAVE_WET
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(base[0] + rng.randint(-8, 8)),
                     clamp(base[1] + rng.randint(-8, 8)),
                     clamp(base[2] + rng.randint(-8, 8)))
                px[x, y] = (*c, 255)
        # Glanz-Punkte
        for _ in range(5):
            gx = rng.randint(0, 15)
            gy = rng.randint(0, 15)
            draw.point((gx, gy), fill=(180, 190, 200, 120))
    elif variant == "muddy":
        base = _CAVE_MUD
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(base[0] + rng.randint(-12, 12)),
                     clamp(base[1] + rng.randint(-10, 10)),
                     clamp(base[2] + rng.randint(-8, 8)))
                px[x, y] = (*c, 255)
    elif variant == "sandy":
        base = (140, 125, 90)
        for y in range(TILE):
            for x in range(TILE):
                mod = ((x + y) % 3) * 3
                c = (clamp(base[0] + rng.randint(-10, 10) + mod),
                     clamp(base[1] + rng.randint(-10, 10)),
                     clamp(base[2] + rng.randint(-8, 8)))
                px[x, y] = (*c, 255)
    elif variant == "mineral":
        base = _CAVE_STONE
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(base[0] + rng.randint(-15, 15)),
                     clamp(base[1] + rng.randint(-15, 15)),
                     clamp(base[2] + rng.randint(-12, 12)))
                px[x, y] = (*c, 255)
        # Mineral-Adern
        for _ in range(2):
            ax = rng.randint(0, 15)
            for ay in range(rng.randint(0, 8), rng.randint(8, 15)):
                ax += rng.randint(-1, 1)
                ax = clamp(ax, 0, 15)
                draw.point((ax, ay), fill=(*color_shift((140, 160, 180), rng, 20), 200))
    elif variant == "smooth":
        # Glatter polierter Stein
        base = tuple(clamp(c + 15) for c in _CAVE_STONE)
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(base[0] + rng.randint(-5, 5)),
                     clamp(base[1] + rng.randint(-5, 5)),
                     clamp(base[2] + rng.randint(-5, 5)))
                px[x, y] = (*c, 255)
    elif variant == "rough":
        base = _CAVE_STONE
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(base[0] + rng.randint(-25, 25)),
                     clamp(base[1] + rng.randint(-25, 25)),
                     clamp(base[2] + rng.randint(-20, 20)))
                px[x, y] = (*c, 255)

    return img


def _cave_wall_variant(rng: random.Random, variant: str) -> Image.Image:
    """Wand-Overlays fuer organisches Aussehen."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if variant == "jagged_left":
        stone = color_shift(_CAVE_STONE, rng, 12)
        # Zackige linke Kante
        for y in range(TILE):
            indent = rng.randint(0, 4)
            for x in range(indent):
                draw.point((x, y), fill=(*stone, 255))
    elif variant == "jagged_right":
        stone = color_shift(_CAVE_STONE, rng, 12)
        for y in range(TILE):
            indent = rng.randint(0, 4)
            for x in range(TILE - indent, TILE):
                draw.point((x, y), fill=(*stone, 255))
    elif variant == "jagged_top":
        stone = color_shift(_CAVE_STONE, rng, 12)
        for x in range(TILE):
            indent = rng.randint(0, 4)
            for y in range(indent):
                draw.point((x, y), fill=(*stone, 255))
    elif variant == "jagged_bottom":
        stone = color_shift(_CAVE_STONE, rng, 12)
        for x in range(TILE):
            indent = rng.randint(0, 4)
            for y in range(TILE - indent, TILE):
                draw.point((x, y), fill=(*stone, 255))
    elif variant == "dripping":
        # Tropfende Wand
        water = color_shift(_CAVE_WATER, rng, 10)
        for x in range(0, TILE, rng.randint(3, 5)):
            length = rng.randint(4, 12)
            for y in range(length):
                alpha = 200 - y * 15
                if alpha > 0:
                    draw.point((x + rng.randint(-1, 0), y), fill=(*water, alpha))
    elif variant == "mossy":
        moss = color_shift(_CAVE_MOSS, rng, 15)
        for _ in range(30):
            x = rng.randint(0, 15)
            y = rng.randint(0, TILE - 1)
            draw.point((x, y), fill=(*moss, rng.randint(120, 220)))
    elif variant == "crystalline":
        crystal = color_shift(_CAVE_CRYSTAL, rng, 25)
        for _ in range(4):
            cx = rng.randint(1, 14)
            cy = rng.randint(1, 10)
            h = rng.randint(3, 6)
            draw.polygon([(cx - 1, cy + h), (cx + 1, cy + h), (cx, cy)],
                         fill=(*crystal, 200))
    elif variant == "eroded":
        # Verwitterte Wand
        for _ in range(15):
            x = rng.randint(0, 15)
            y = rng.randint(0, 15)
            r = rng.randint(1, 3)
            c = color_shift(_CAVE_DARK, rng, 10)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(*c, rng.randint(80, 160)))

    return img


def _cave_passage_tile(rng: random.Random, variant: str) -> Image.Image:
    """Tiles speziell fuer Durchgaenge zwischen Raeumen."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px_arr = img.load()
    draw = ImageDraw.Draw(img)

    base = color_shift((80, 70, 55), rng, 10)

    if variant == "passage_floor":
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(base[0] + rng.randint(-15, 15)),
                     clamp(base[1] + rng.randint(-15, 15)),
                     clamp(base[2] + rng.randint(-12, 12)))
                px_arr[x, y] = (*c, 255)
        _detail_stone_cracks(img, rng)
    elif variant == "passage_rubble":
        # Boden mit Schutt-Overlay
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(base[0] + rng.randint(-10, 10)),
                     clamp(base[1] + rng.randint(-10, 10)),
                     clamp(base[2] + rng.randint(-8, 8)))
                px_arr[x, y] = (*c, 255)
        for _ in range(6):
            rx = rng.randint(1, 13)
            ry = rng.randint(1, 13)
            rs = rng.randint(1, 3)
            rc = color_shift(_CAVE_DARK, rng, 12)
            draw.rectangle([rx, ry, rx + rs, ry + rs], fill=(*rc, 220))
    elif variant == "passage_wet":
        wet = color_shift(_CAVE_WET, rng, 8)
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(wet[0] + rng.randint(-8, 8)),
                     clamp(wet[1] + rng.randint(-8, 8)),
                     clamp(wet[2] + rng.randint(-6, 6)))
                px_arr[x, y] = (*c, 255)
        for _ in range(3):
            gx = rng.randint(0, 15)
            gy = rng.randint(0, 15)
            draw.point((gx, gy), fill=(170, 180, 195, 100))
    elif variant == "passage_narrow":
        # Enger Durchgang — Waende links/rechts naeher
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(base[0] + rng.randint(-12, 12)),
                     clamp(base[1] + rng.randint(-12, 12)),
                     clamp(base[2] + rng.randint(-10, 10)))
                px_arr[x, y] = (*c, 255)
        # Schatten an den Seiten
        for y in range(TILE):
            for x in range(3):
                px_arr[x, y] = tuple(clamp(c - 30) for c in px_arr[x, y][:3]) + (255,)
            for x in range(TILE - 3, TILE):
                px_arr[x, y] = tuple(clamp(c - 30) for c in px_arr[x, y][:3]) + (255,)
    elif variant == "passage_mossy":
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(base[0] + rng.randint(-10, 10)),
                     clamp(base[1] + rng.randint(-10, 10)),
                     clamp(base[2] + rng.randint(-8, 8)))
                px_arr[x, y] = (*c, 255)
        # Moos drauf
        for _ in range(20):
            mx = rng.randint(0, 15)
            my = rng.randint(0, 15)
            draw.point((mx, my), fill=(*color_shift(_CAVE_MOSS, rng, 15),
                                        rng.randint(100, 200)))
    elif variant == "passage_puddle":
        for y in range(TILE):
            for x in range(TILE):
                c = (clamp(base[0] + rng.randint(-10, 10)),
                     clamp(base[1] + rng.randint(-10, 10)),
                     clamp(base[2] + rng.randint(-8, 8)))
                px_arr[x, y] = (*c, 255)
        water = color_shift(_CAVE_WATER, rng, 12)
        draw.ellipse([3, 4, 12, 11], fill=(*water, 180))
        draw.point((6, 7), fill=(*tuple(clamp(c + 40) for c in water), 200))

    return img


def _cave_ceiling(rng: random.Random, variant: str) -> Image.Image:
    """Decken-Details (als Overlay nutzbar)."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if variant == "drips":
        water = color_shift(_CAVE_WATER, rng, 10)
        for x in range(0, 16, rng.randint(3, 6)):
            y = rng.randint(0, 5)
            draw.line([(x, 0), (x, y)], fill=(*water, 180))
            draw.ellipse([x - 1, y, x + 1, y + 2], fill=(*water, 220))
    elif variant == "roots":
        root_c = (80, 55, 30, 220)
        for _ in range(4):
            x = rng.randint(0, 15)
            pts = [(x, 0)]
            for dy in range(1, rng.randint(6, 14)):
                x += rng.randint(-1, 1)
                x = clamp(x, 0, 15)
                pts.append((x, dy))
            for i in range(len(pts) - 1):
                draw.line([pts[i], pts[i + 1]], fill=root_c)
    elif variant == "cracks":
        crack_c = (30, 25, 20, 200)
        for _ in range(3):
            x = rng.randint(0, 15)
            y = rng.randint(0, 8)
            for _ in range(rng.randint(4, 8)):
                nx = clamp(x + rng.randint(-2, 2), 0, 15)
                ny = clamp(y + rng.randint(-1, 2), 0, 15)
                draw.line([(x, y), (nx, ny)], fill=crack_c)
                x, y = nx, ny
    elif variant == "cobwebs":
        web = (200, 200, 210, 120)
        cx, cy = rng.randint(0, 4), 0
        for angle_deg in range(0, 180, 30):
            a = math.radians(angle_deg)
            ex = int(cx + math.cos(a) * 10)
            ey = int(cy + math.sin(a) * 10)
            draw.line([(cx, cy), (ex, ey)], fill=web)

    return img


def generate_cave_extended(rng: random.Random, count: int) -> list[tuple[str, Image.Image]]:
    """Generiert 68 erweiterte Hoehlen-Tiles fuer organische Weltkarten.

    Kategorien:
      - Stalagmiten (8)
      - Stalaktiten (4)
      - Felsformationen (8)
      - Pfuetzen/Wasser (6)
      - Moos/Pilze (8)
      - Kristalle (6)
      - Schutt/Truemmer (8)
      - Boden-Varianten (6)
      - Wand-Overlays (8)
      - Durchgangs-Tiles (6)
      - Decken-Details (4)
    """
    results: list[tuple[str, Image.Image]] = []
    cave_rng = random.Random(rng.getstate()[1][0] ^ 0xCAFE)

    # Stalagmiten (8)
    for v in ["tiny", "small", "medium", "large", "cluster", "twin", "broken", "wide"]:
        tile = _cave_stalagmite(cave_rng, v)
        results.append((f"cave_stalagmite_{v}.png", tile))

    # Stalaktiten (4)
    for v in ["dripping", "cluster", "thick", "icicle"]:
        tile = _cave_stalactite_ext(cave_rng, v)
        results.append((f"cave_stalactite_{v}.png", tile))

    # Felsformationen (8)
    for v in ["boulder_small", "boulder_large", "rock_pile", "ledge",
              "column_natural", "slab", "arch", "overhang"]:
        tile = _cave_rock_formation(cave_rng, v)
        results.append((f"cave_rock_{v}.png", tile))

    # Pfuetzen (6)
    for v in ["small", "medium", "large", "edge", "drip_pool", "stream"]:
        tile = _cave_puddle(cave_rng, v)
        results.append((f"cave_puddle_{v}.png", tile))

    # Moos/Pilze (8)
    for v in ["floor_moss", "wall_moss", "mushroom_cluster", "glowing_fungus",
              "lichen", "vine", "fungal_floor", "spore_cloud"]:
        tile = _cave_moss(cave_rng, v)
        results.append((f"cave_moss_{v}.png", tile))

    # Kristalle (6)
    for v in ["small", "large", "cluster", "glowing", "amethyst", "vein"]:
        tile = _cave_crystal(cave_rng, v)
        results.append((f"cave_crystal_{v}.png", tile))

    # Schutt (8)
    for v in ["gravel", "rubble_small", "rubble_large", "collapsed",
              "bone_pile", "dust", "crack_floor", "wet_rocks"]:
        tile = _cave_debris(cave_rng, v)
        results.append((f"cave_debris_{v}.png", tile))

    # Boden-Varianten (6)
    for v in ["wet", "muddy", "sandy", "mineral", "smooth", "rough"]:
        tile = _cave_floor_variant(cave_rng, v)
        results.append((f"cave_floor_{v}.png", tile))

    # Wand-Overlays (8)
    for v in ["jagged_left", "jagged_right", "jagged_top", "jagged_bottom",
              "dripping", "mossy", "crystalline", "eroded"]:
        tile = _cave_wall_variant(cave_rng, v)
        results.append((f"cave_wall_{v}.png", tile))

    # Durchgangs-Tiles (6)
    for v in ["passage_floor", "passage_rubble", "passage_wet",
              "passage_narrow", "passage_mossy", "passage_puddle"]:
        tile = _cave_passage_tile(cave_rng, v)
        results.append((f"cave_{v}.png", tile))

    # Decken-Details (4)
    for v in ["drips", "roots", "cracks", "cobwebs"]:
        tile = _cave_ceiling(cave_rng, v)
        results.append((f"cave_ceiling_{v}.png", tile))

    return results[:count]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. EFFEKT-GENERATOR (Spell/Combat Animationsframes)
# ═══════════════════════════════════════════════════════════════════════════════

def _effect_explosion(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Explosion: Kreis der waechst und verblasst."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        radius = int(2 + progress * 6)
        alpha = int(255 * (1 - progress * 0.7))
        # Kern
        r_inner = max(1, radius - 2)
        draw.ellipse(
            [8 - r_inner, 8 - r_inner, 8 + r_inner, 8 + r_inner],
            fill=(255, 255, 200, alpha),
        )
        # Aussen
        draw.ellipse(
            [8 - radius, 8 - radius, 8 + radius, 8 + radius],
            fill=(255, 140, 30, alpha // 2),
        )
        # Partikel
        for _ in range(3 + f * 2):
            angle = rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(1, radius + 2)
            px = int(8 + math.cos(angle) * dist)
            py = int(8 + math.sin(angle) * dist)
            if 0 <= px < TILE and 0 <= py < TILE:
                c = rng.choice([(255, 200, 60), (255, 100, 20), (200, 50, 10)])
                draw.point((px, py), fill=(*c, alpha))
        frames.append(img)
    return frames


def _effect_magic_circle(rng: random.Random, num_frames: int = 8) -> list[Image.Image]:
    """Rotierender Magie-Kreis."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        angle_offset = (f / num_frames) * 2 * math.pi
        # Kreis
        draw.ellipse([3, 3, 12, 12], outline=(100, 60, 200, 200), width=1)
        # Rotierende Punkte
        for i in range(4):
            a = angle_offset + i * math.pi / 2
            px = int(8 + math.cos(a) * 5)
            py = int(8 + math.sin(a) * 5)
            if 0 <= px < TILE and 0 <= py < TILE:
                draw.rectangle([px - 1, py - 1, px + 1, py + 1],
                               fill=(180, 120, 255, 220))
        # Glühen in der Mitte
        alpha = int(150 + 80 * math.sin(f * math.pi / num_frames))
        draw.ellipse([6, 6, 10, 10], fill=(160, 80, 240, alpha))
        frames.append(img)
    return frames


def _effect_heal(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Heilungs-Effekt: aufsteigende gruene Partikel."""
    frames = []
    # Partikel vorberechnen
    particles = [(rng.randint(3, 12), rng.randint(4, 14), rng.uniform(0.8, 2.0))
                 for _ in range(12)]
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        for (px, start_y, speed) in particles:
            py = int(start_y - progress * speed * 8)
            alpha = int(255 * (1 - progress * 0.5))
            if 0 <= py < TILE and 0 <= px < TILE:
                c = rng.choice([(80, 220, 80), (120, 255, 120), (60, 180, 60)])
                draw.point((px, py), fill=(*c, alpha))
                if px + 1 < TILE:
                    draw.point((px + 1, py), fill=(*c, alpha // 2))
        # Kreuz in der Mitte (statisch, verblassend)
        ca = int(200 * (1 - progress * 0.6))
        draw.line([(7, 5), (7, 11)], fill=(100, 255, 100, ca))
        draw.line([(5, 8), (9, 8)], fill=(100, 255, 100, ca))
        frames.append(img)
    return frames


def _effect_lightning(rng: random.Random, num_frames: int = 4) -> list[Image.Image]:
    """Blitz-Effekt: zackige Linie von oben nach unten."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        alpha = 255 if f % 2 == 0 else 120  # Flackern
        # Blitz-Pfad
        x = 8
        points = [(x, 0)]
        for y in range(1, TILE):
            x += rng.randint(-2, 2)
            x = clamp(x, 2, 13)
            points.append((x, y))
        # Hauptlinie
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=(200, 220, 255, alpha), width=1)
        # Glow
        for (px, py) in points[::2]:
            draw.point((px - 1, py), fill=(150, 180, 255, alpha // 3))
            draw.point((px + 1, py), fill=(150, 180, 255, alpha // 3))
        frames.append(img)
    return frames


def _effect_fireball(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Fireball: Wachsende Flamme orange/rot."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        radius = int(1 + progress * 7)
        alpha = int(255 * (1 - progress * 0.4))
        # Kern (gelb-weiss)
        r_inner = max(1, radius // 2)
        draw.ellipse([8 - r_inner, 8 - r_inner, 8 + r_inner, 8 + r_inner],
                     fill=(255, 240, 180, alpha))
        # Mittlere Schicht (orange)
        r_mid = max(1, int(radius * 0.75))
        draw.ellipse([8 - r_mid, 8 - r_mid, 8 + r_mid, 8 + r_mid],
                     fill=(255, 160, 40, int(alpha * 0.7)))
        # Aeussere Schicht (rot)
        draw.ellipse([8 - radius, 8 - radius, 8 + radius, 8 + radius],
                     fill=(220, 60, 20, int(alpha * 0.4)))
        # Funken
        for _ in range(2 + f * 3):
            angle = rng.uniform(0, 2 * math.pi)
            dist = rng.uniform(radius * 0.5, radius + 3)
            px_ = int(8 + math.cos(angle) * dist)
            py_ = int(8 + math.sin(angle) * dist)
            if 0 <= px_ < TILE and 0 <= py_ < TILE:
                c = rng.choice([(255, 200, 60), (255, 140, 30), (255, 80, 20)])
                draw.point((px_, py_), fill=(*c, alpha))
        frames.append(img)
    return frames


def _effect_ice_shard(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Eissplitter: Hellblaue Kristalle die wachsen."""
    frames = []
    shards = [(rng.randint(3, 12), rng.randint(3, 12), rng.uniform(-0.5, 0.5))
              for _ in range(5)]
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        length = int(2 + progress * 6)
        alpha = int(255 * (1 - progress * 0.3))
        for sx, sy, angle in shards:
            ex = int(sx + math.cos(angle) * length)
            ey = int(sy - length)
            draw.line([(sx, sy), (ex, ey)], fill=(180, 220, 255, alpha), width=1)
            draw.point((ex, ey), fill=(220, 240, 255, alpha))
        # Frost-Aura
        draw.ellipse([8 - length, 8 - length, 8 + length, 8 + length],
                     outline=(150, 200, 240, int(alpha * 0.3)))
        frames.append(img)
    return frames


def _effect_holy_light(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Strahl von oben, goldenes Licht."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        alpha = int(200 * (0.4 + 0.6 * math.sin(progress * math.pi)))
        # Strahl von oben
        beam_w = int(2 + progress * 3)
        draw.rectangle([8 - beam_w, 0, 8 + beam_w, int(TILE * progress)],
                       fill=(255, 230, 100, int(alpha * 0.5)))
        # Zentraler heller Kern
        draw.rectangle([7, 0, 8, int(TILE * progress)],
                       fill=(255, 255, 200, alpha))
        # Boden-Glow
        if progress > 0.3:
            r = int(3 + progress * 4)
            draw.ellipse([8 - r, 12 - r // 2, 8 + r, 12 + r // 2],
                         fill=(255, 220, 80, int(alpha * 0.4)))
        frames.append(img)
    return frames


def _effect_divine_blessing(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Aufsteigende goldene/weisse Partikel."""
    frames = []
    particles = [(rng.randint(2, 13), rng.randint(8, 15), rng.uniform(1.0, 2.5))
                 for _ in range(15)]
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        for px_, start_y, speed in particles:
            py_ = int(start_y - progress * speed * 10)
            alpha = int(220 * (1 - progress * 0.4))
            if 0 <= py_ < TILE:
                c = rng.choice([(255, 230, 100), (255, 255, 200), (240, 200, 60)])
                draw.point((px_, py_), fill=(*c, alpha))
                if py_ + 1 < TILE:
                    draw.point((px_, py_ + 1), fill=(*c, alpha // 3))
        frames.append(img)
    return frames


def _effect_magic_missile(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """3 lila Punkte in Pfeilformation, fliegen nach rechts."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        base_x = int(-2 + progress * 18)
        alpha = int(255 * (1 - progress * 0.2))
        positions = [(base_x, 7), (base_x - 3, 5), (base_x - 3, 9)]
        for mx, my in positions:
            if 0 <= mx < TILE and 0 <= my < TILE:
                draw.ellipse([mx - 1, my - 1, mx + 1, my + 1],
                             fill=(180, 100, 255, alpha))
                # Schweif
                for t in range(1, 4):
                    tx = mx - t
                    if 0 <= tx < TILE:
                        draw.point((tx, my), fill=(140, 60, 220, alpha // (t + 1)))
        frames.append(img)
    return frames


def _effect_shield_spell(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Blaues Aura-Schild, pulsierend."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        pulse = math.sin(f * math.pi / max(num_frames - 1, 1))
        alpha = int(80 + 120 * pulse)
        r = int(5 + pulse * 2)
        draw.ellipse([8 - r, 8 - r, 8 + r, 8 + r],
                     outline=(80, 140, 255, alpha), width=2)
        draw.ellipse([8 - r + 1, 8 - r + 1, 8 + r - 1, 8 + r - 1],
                     outline=(120, 180, 255, int(alpha * 0.5)))
        frames.append(img)
    return frames


def _effect_turn_undead(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Weiss/Gold Strahlenkranz."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        alpha = int(255 * (1 - progress * 0.5))
        num_rays = 8
        ray_len = int(2 + progress * 6)
        angle_offset = progress * math.pi / 4
        for i in range(num_rays):
            a = angle_offset + i * 2 * math.pi / num_rays
            ex = int(8 + math.cos(a) * ray_len)
            ey = int(8 + math.sin(a) * ray_len)
            c = (255, 255, 200) if i % 2 == 0 else (255, 220, 80)
            draw.line([(8, 8), (ex, ey)], fill=(*c, alpha))
        draw.ellipse([6, 6, 10, 10], fill=(255, 255, 220, alpha))
        frames.append(img)
    return frames


def _effect_lay_on_hands(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Warmgoldenes sanftes Gluehen, aufsteigend."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        alpha = int(180 * math.sin(progress * math.pi))
        r = int(3 + progress * 3)
        draw.ellipse([8 - r, 10 - r - int(progress * 4),
                      8 + r, 10 + r - int(progress * 4)],
                     fill=(255, 210, 100, alpha))
        draw.ellipse([7, 9 - int(progress * 4), 9, 11 - int(progress * 4)],
                     fill=(255, 240, 180, int(alpha * 1.2)))
        frames.append(img)
    return frames


def _effect_poison_cloud(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Gruener Giftnebel, sich ausbreitend."""
    frames = []
    blobs = [(rng.randint(4, 11), rng.randint(4, 11), rng.randint(2, 4))
             for _ in range(6)]
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        alpha = int(180 * (1 - progress * 0.3))
        for bx, by, br in blobs:
            r = int(br * (0.5 + progress))
            ox = rng.randint(-1, 1)
            oy = rng.randint(-1, 1)
            c = rng.choice([(60, 180, 40), (40, 150, 30), (80, 200, 60)])
            draw.ellipse([bx + ox - r, by + oy - r, bx + ox + r, by + oy + r],
                         fill=(*c, int(alpha * 0.6)))
        frames.append(img)
    return frames


def _effect_fear_aura(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Dunkelrot/schwarze Wellen, pulsierend nach aussen."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        progress = f / max(num_frames - 1, 1)
        for ring in range(3):
            r = int((ring + 1) * 2 + progress * 4)
            alpha = int(150 * (1 - ring * 0.3) * (1 - progress * 0.3))
            c = (80 + ring * 20, 10, 10) if ring < 2 else (30, 10, 30)
            draw.ellipse([8 - r, 8 - r, 8 + r, 8 + r],
                         outline=(*c, alpha), width=1)
        # Kern
        draw.ellipse([6, 6, 10, 10], fill=(60, 5, 5, int(200 * (1 - progress * 0.5))))
        frames.append(img)
    return frames


def _effect_bless(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Sanftes goldenes Leuchten."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        pulse = math.sin(f * math.pi / max(num_frames - 1, 1))
        alpha = int(60 + 140 * pulse)
        r = int(4 + pulse * 2)
        draw.ellipse([8 - r, 8 - r, 8 + r, 8 + r],
                     fill=(255, 230, 120, alpha))
        draw.ellipse([7, 7, 9, 9], fill=(255, 250, 200, int(alpha * 1.3)))
        # Kleine Sterne
        for _ in range(3):
            sx = rng.randint(2, 13)
            sy = rng.randint(2, 13)
            draw.point((sx, sy), fill=(255, 255, 200, int(alpha * 0.6)))
        frames.append(img)
    return frames


def _effect_curse(rng: random.Random, num_frames: int = 6) -> list[Image.Image]:
    """Dunkelrote Rune, pulsierend."""
    frames = []
    for f in range(num_frames):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        pulse = math.sin(f * math.pi / max(num_frames - 1, 1))
        alpha = int(120 + 120 * pulse)
        c = (160, 20, 20, alpha)
        # Rune: Dreieck + Kreis + Linien
        draw.polygon([(8, 2), (3, 13), (13, 13)], outline=c)
        draw.ellipse([5, 5, 11, 11], outline=c)
        draw.line([(4, 4), (12, 12)], fill=c)
        draw.line([(12, 4), (4, 12)], fill=c)
        # Kern-Glow
        draw.ellipse([7, 7, 9, 9], fill=(200, 40, 40, int(alpha * 0.8)))
        frames.append(img)
    return frames


EFFECT_GENERATORS: dict[str, Callable[[random.Random, int], list[Image.Image]]] = {
    "explosion":        _effect_explosion,
    "magic_circle":     _effect_magic_circle,
    "heal":             _effect_heal,
    "lightning":        _effect_lightning,
    "fireball":         _effect_fireball,
    "ice_shard":        _effect_ice_shard,
    "holy_light":       _effect_holy_light,
    "divine_blessing":  _effect_divine_blessing,
    "magic_missile":    _effect_magic_missile,
    "shield_spell":     _effect_shield_spell,
    "turn_undead":      _effect_turn_undead,
    "lay_on_hands":     _effect_lay_on_hands,
    "poison_cloud":     _effect_poison_cloud,
    "fear_aura":        _effect_fear_aura,
    "bless":            _effect_bless,
    "curse":            _effect_curse,
}


def generate_effect_sprite(rng: random.Random, effect_name: str,
                           num_frames: int = 1) -> "Image.Image":
    """Erzeugt ein einzelnes Effekt-Sprite (erster Frame). Fuer SpriteExtractor."""
    gen_fn = EFFECT_GENERATORS.get(effect_name)
    if gen_fn:
        frames = gen_fn(rng, max(num_frames, 2))
        return frames[0]
    # Fallback: generischer Magie-Kreis
    frames = _effect_magic_circle(rng, max(num_frames, 2))
    return frames[0]


def generate_effects(rng: random.Random, count: int) -> list[tuple[str, Image.Image]]:
    """Generiert Effekt-Animationsframes."""
    results = []
    effect_names = list(EFFECT_GENERATORS.keys())
    for i in range(min(count, len(effect_names))):
        name = effect_names[i]
        gen_fn = EFFECT_GENERATORS[name]
        frames = gen_fn(rng, 6)
        for f_idx, frame in enumerate(frames):
            fname = f"effect_{name}_{f_idx + 1:02d}.png"
            results.append((fname, frame))
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ANIMATIONS-GENERATOR (Tiny-RPG-Stil, Chibi-Proportionen)
#    Orientiert an itch.io "Tiny RPG Character Asset Pack"
# ═══════════════════════════════════════════════════════════════════════════════

# Chibi-Layout auf 16x16:
#   Kopf:   y=1-6  (gross, rund, ~7px breit) — 40% der Hoehe
#   Koerper: y=7-10 (klein, 5px breit)
#   Beine:  y=11-14 (kurz, getrennt)
#   Schatten: y=15
#
# 3-Ton-Shading: highlight, base, shadow pro Farbe

def _shade(base: tuple[int, int, int]) -> dict[str, tuple[int, int, int]]:
    """Erzeugt 3-Ton-Palette aus einer Basisfarbe."""
    return {
        "hi":  tuple(clamp(c + 45) for c in base),
        "mid": base,
        "lo":  tuple(clamp(c - 50) for c in base),
    }


# Charakter-Definitionen mit vollen Farb-Paletten und Ausruestungs-Typ
CHAR_DEFS = {
    "fighter": {
        "skin": (220, 180, 140), "hair": (90, 60, 30),
        "armor_a": (90, 95, 115), "armor_b": (70, 75, 95),  # Kettenhemd
        "pants": (70, 65, 55), "boots": (60, 45, 30),
        "weapon_blade": (190, 195, 200), "weapon_hilt": (120, 80, 40),
        "eye": (255, 255, 255), "pupil": (40, 40, 50),
        "equip": "sword_shield",
    },
    "mage": {
        "skin": (210, 175, 145), "hair": (180, 180, 200),
        "armor_a": (70, 40, 130), "armor_b": (90, 60, 160),  # Robe
        "pants": (60, 35, 110), "boots": (50, 30, 80),
        "weapon_blade": (180, 140, 240), "weapon_hilt": (100, 70, 50),
        "eye": (255, 255, 255), "pupil": (60, 30, 90),
        "equip": "staff",
    },
    "rogue": {
        "skin": (200, 165, 125), "hair": (40, 35, 30),
        "armor_a": (65, 60, 55), "armor_b": (85, 75, 65),  # Leder
        "pants": (55, 50, 45), "boots": (45, 35, 25),
        "weapon_blade": (175, 180, 185), "weapon_hilt": (90, 65, 35),
        "eye": (255, 255, 255), "pupil": (40, 40, 40),
        "equip": "dagger",
    },
    "cleric": {
        "skin": (215, 180, 150), "hair": (150, 120, 70),
        "armor_a": (210, 210, 220), "armor_b": (180, 180, 195),  # Weisse Robe
        "pants": (170, 170, 180), "boots": (100, 85, 60),
        "weapon_blade": (220, 200, 100), "weapon_hilt": (130, 90, 50),
        "eye": (255, 255, 255), "pupil": (50, 50, 60),
        "equip": "mace",
    },
    "skeleton": {
        "skin": (210, 205, 190), "hair": (0, 0, 0),  # kein Haar
        "armor_a": (190, 185, 170), "armor_b": (170, 165, 150),
        "pants": (160, 155, 140), "boots": (140, 135, 120),
        "weapon_blade": (160, 165, 170), "weapon_hilt": (100, 90, 70),
        "eye": (255, 50, 30), "pupil": (200, 20, 10),
        "equip": "sword_shield",
    },
    "orc": {
        "skin": (95, 145, 75), "hair": (30, 30, 25),
        "armor_a": (110, 75, 40), "armor_b": (85, 55, 30),  # Fell
        "pants": (75, 65, 45), "boots": (55, 40, 25),
        "weapon_blade": (140, 145, 150), "weapon_hilt": (80, 55, 30),
        "eye": (255, 230, 50), "pupil": (200, 50, 20),
        "equip": "axe",
    },
}


def _draw_px(px, x: int, y: int, color: tuple[int, int, int], alpha: int = 255):
    """Sicheres Pixel setzen."""
    if 0 <= x < TILE and 0 <= y < TILE:
        px[x, y] = (*color, alpha)


def _draw_chibi_base(char_def: dict, body_mod: str = "normal", color_mod: str = "normal") -> Image.Image:
    """Zeichnet den Basis-Frame eines Chibi-Charakters mit vollem Detail."""
    img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    px = img.load()

    sk = _shade(char_def["skin"])
    hr = _shade(char_def["hair"])
    aa = _shade(char_def["armor_a"])
    ab = _shade(char_def["armor_b"])
    pt = _shade(char_def["pants"])
    bt = _shade(char_def["boots"])
    wb = _shade(char_def["weapon_blade"])
    wh = _shade(char_def["weapon_hilt"])
    eye_w = char_def["eye"]
    pupil = char_def["pupil"]
    equip = char_def["equip"]

    # Modifikatoren
    bmod = BODY_MODIFIERS.get(body_mod, BODY_MODIFIERS["normal"])
    cmod = COLOR_MODIFIERS.get(color_mod, COLOR_MODIFIERS["normal"])

    # Farben anpassen
    if color_mod != "normal":
        sk = _shade(_apply_color_mod(char_def["skin"], cmod))
        hr = _shade(_apply_color_mod(char_def["hair"], cmod))
        aa = _shade(_apply_color_mod(char_def["armor_a"], cmod))
        ab = _shade(_apply_color_mod(char_def["armor_b"], cmod))
        pt = _shade(_apply_color_mod(char_def["pants"], cmod))
        bt = _shade(_apply_color_mod(char_def["boots"], cmod))
        wb = _shade(_apply_color_mod(char_def["weapon_blade"], cmod))
        wh = _shade(_apply_color_mod(char_def["weapon_hilt"], cmod))

    # Body-Offsets berechnen
    bw = bmod["width"]     # Breiten-Aenderung (-1=schmaler, +1=breiter)
    bh = bmod["height"]    # Hoehen-Verschiebung
    leg_ext = bmod["leg_ext"]  # Beinverlaengerung

    # ── Schatten (y=15) ──
    for x in range(5, 11):
        _draw_px(px, x, 15, (20, 18, 30), 100)

    # ── Haare / Helm oben (y=1-2) ──
    if char_def["hair"] != (0, 0, 0):  # nicht Skeleton
        for x in range(5, 11):
            _draw_px(px, x, 1, hr["hi"])
        for x in range(4, 12):
            _draw_px(px, x, 2, hr["mid"])
        _draw_px(px, 4, 1, hr["lo"])
        _draw_px(px, 10, 1, hr["lo"])
    else:
        # Skeleton: Schaedel-Oberseite
        for x in range(5, 11):
            _draw_px(px, x, 1, sk["hi"])
        for x in range(5, 11):
            _draw_px(px, x, 2, sk["mid"])

    # ── Kopf (y=3-6) — grosser runder Chibi-Kopf ──
    # Breite: 4=schmal, 5-10=voll, 11=schmal
    for x in range(4, 12):
        _draw_px(px, x, 3, sk["hi"])  # Stirn highlight
    for x in range(4, 12):
        _draw_px(px, x, 4, sk["mid"])
    for x in range(4, 12):
        _draw_px(px, x, 5, sk["mid"])
    for x in range(5, 11):
        _draw_px(px, x, 6, sk["lo"])  # Kinn

    # Augen (y=4) — weiss + Pupille, typischer Tiny-RPG-Look
    _draw_px(px, 5, 4, eye_w)
    _draw_px(px, 6, 4, pupil)
    _draw_px(px, 9, 4, eye_w)
    _draw_px(px, 10, 4, pupil)

    # Mund (y=5, Mitte)
    _draw_px(px, 7, 5, sk["lo"])
    _draw_px(px, 8, 5, sk["lo"])

    # Haare seitlich (y=3-5)
    if char_def["hair"] != (0, 0, 0):
        _draw_px(px, 3, 3, hr["mid"])
        _draw_px(px, 3, 4, hr["lo"])
        _draw_px(px, 12, 3, hr["mid"])
        _draw_px(px, 12, 4, hr["lo"])

    # ── Koerper / Ruestung (y=7-10) ──
    x_left = 4 - bw     # Linke Koerpergrenze (normal=4, bulky=3, slim=5)
    x_right = 11 + bw   # Rechte Koerpergrenze (normal=11, bulky=12, slim=10)
    x_inner_l = 5 - bw
    x_inner_r = 11 + bw
    by = bh              # Vertikal-Offset

    # Schultern
    _draw_px(px, x_left, 7 + by, aa["hi"])
    for x in range(x_inner_l, x_inner_r):
        _draw_px(px, x, 7 + by, aa["hi"])
    _draw_px(px, x_right, 7 + by, aa["lo"])

    # Brust
    for x in range(x_inner_l, x_inner_r):
        _draw_px(px, x, 8 + by, aa["mid"])
    _draw_px(px, x_left, 8 + by, ab["mid"])   # Arm links
    _draw_px(px, x_right, 8 + by, ab["mid"])  # Arm rechts

    # Bauch / Guertel
    for x in range(x_inner_l, x_inner_r):
        _draw_px(px, x, 9 + by, ab["mid"])
    _draw_px(px, 7, 9 + by, ab["lo"])   # Guertelschnalle-Schatten
    _draw_px(px, 8, 9 + by, ab["hi"])   # Guertelschnalle-Highlight
    _draw_px(px, x_left, 9 + by, ab["lo"])   # Arm links unten
    _draw_px(px, x_right, 9 + by, ab["lo"])  # Arm rechts unten

    # Huefte
    for x in range(x_inner_l, x_inner_r):
        _draw_px(px, x, 10 + by, pt["mid"])

    # ── Beine (y=11-14) ──
    leg_y_start = 11 + by
    leg_y_boot = leg_y_start + 2 + max(0, leg_ext)  # Stiefel-Start
    leg_y_end = min(14, leg_y_start + 3 + max(0, leg_ext))  # Stiefel-Ende

    # Linkes Bein
    for ly in range(leg_y_start, min(leg_y_boot, 15)):
        tone = pt["mid"] if (ly - leg_y_start) < 2 else pt["lo"]
        _draw_px(px, 5, ly, tone)
        _draw_px(px, 6, ly, tone)
    for ly in range(max(leg_y_boot, leg_y_start), min(leg_y_end + 1, 15)):
        tone = bt["mid"] if ly == leg_y_boot else bt["lo"]
        _draw_px(px, 5, ly, tone)
        _draw_px(px, 6, ly, tone)

    # Rechtes Bein
    for ly in range(leg_y_start, min(leg_y_boot, 15)):
        tone = pt["mid"] if (ly - leg_y_start) < 2 else pt["lo"]
        _draw_px(px, 9, ly, tone)
        _draw_px(px, 10, ly, tone)
    for ly in range(max(leg_y_boot, leg_y_start), min(leg_y_end + 1, 15)):
        tone = bt["mid"] if ly == leg_y_boot else bt["lo"]
        _draw_px(px, 9, ly, tone)
        _draw_px(px, 10, ly, tone)

    # ── Waffe ──
    if equip == "sword_shield":
        # Schwert rechts (y=6-10 an x=12-13)
        _draw_px(px, 13, 5, wb["hi"])
        _draw_px(px, 13, 6, wb["hi"])
        _draw_px(px, 13, 7, wb["mid"])
        _draw_px(px, 13, 8, wb["mid"])
        _draw_px(px, 12, 9, wh["mid"])  # Parierstange
        _draw_px(px, 13, 9, wh["mid"])
        _draw_px(px, 14, 9, wh["mid"])
        _draw_px(px, 13, 10, wh["lo"])  # Griff
        # Schild links (x=2-3, y=7-10)
        _draw_px(px, 2, 7, ab["hi"])
        _draw_px(px, 3, 7, ab["hi"])
        _draw_px(px, 2, 8, ab["mid"])
        _draw_px(px, 3, 8, aa["hi"])  # Emblem
        _draw_px(px, 2, 9, ab["mid"])
        _draw_px(px, 3, 9, ab["lo"])
        _draw_px(px, 2, 10, ab["lo"])
        _draw_px(px, 3, 10, ab["lo"])
    elif equip == "staff":
        # Stab rechts (y=3-13 an x=13)
        for y in range(3, 13):
            _draw_px(px, 13, y, wh["mid"])
        _draw_px(px, 13, 3, wb["hi"])  # Kristall oben
        _draw_px(px, 12, 3, wb["mid"])
        _draw_px(px, 14, 3, wb["mid"])
        _draw_px(px, 13, 2, wb["hi"])
    elif equip == "dagger":
        # Dolch rechts (kurz, y=7-10 an x=12-13)
        _draw_px(px, 13, 6, wb["hi"])
        _draw_px(px, 13, 7, wb["mid"])
        _draw_px(px, 12, 8, wh["mid"])  # Griff
        _draw_px(px, 13, 8, wh["mid"])
        _draw_px(px, 13, 9, wh["lo"])
    elif equip == "mace":
        # Streitkolben rechts
        _draw_px(px, 12, 5, wb["hi"])
        _draw_px(px, 13, 5, wb["hi"])
        _draw_px(px, 14, 5, wb["mid"])
        _draw_px(px, 13, 6, wb["mid"])
        _draw_px(px, 13, 7, wh["mid"])
        _draw_px(px, 13, 8, wh["mid"])
        _draw_px(px, 13, 9, wh["lo"])
    elif equip == "axe":
        # Axt rechts
        _draw_px(px, 12, 5, wb["mid"])
        _draw_px(px, 13, 5, wb["hi"])
        _draw_px(px, 14, 5, wb["mid"])
        _draw_px(px, 14, 6, wb["mid"])
        _draw_px(px, 13, 6, wb["lo"])
        _draw_px(px, 13, 7, wh["mid"])
        _draw_px(px, 13, 8, wh["mid"])
        _draw_px(px, 13, 9, wh["lo"])
        _draw_px(px, 13, 10, wh["lo"])

    outline_pass(img)
    return img


def _apply_frame_transform(
    base_img: Image.Image,
    transform: dict,
) -> Image.Image:
    """Wendet Animation-Transform auf Basis-Bild an.

    Transforms arbeiten auf Regionen statt Einzelpixeln:
      body_dy: Ganzer Koerper hoch/runter (Atem-Bob)
      head_dy: Nur Kopf (y=1-6)
      leg_l_dx/dy: Linkes Bein (x=5-6, y=11-14)
      leg_r_dx/dy: Rechtes Bein (x=9-10, y=11-14)
      arm_l_dy: Linker Arm (x=2-4, y=7-10)
      arm_r_dy: Rechter Arm + Waffe (x=11-14, y=2-13)
      lean_dx: Koerper neigen (alles ausser Beine)
      flash: Alles weiss
      squash_y: Tod-Animation (y-offset fuer Zusammensacken)
      rotate_weapon: Waffen-Rotation in Grad (vereinfacht)
    """
    img = base_img.copy()
    result = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    src = img.load()
    dst = result.load()

    body_dy = transform.get("body_dy", 0)
    head_dy = transform.get("head_dy", 0)
    leg_l = (transform.get("leg_l_dx", 0), transform.get("leg_l_dy", 0))
    leg_r = (transform.get("leg_r_dx", 0), transform.get("leg_r_dy", 0))
    arm_l_dy = transform.get("arm_l_dy", 0)
    arm_r_dy = transform.get("arm_r_dy", 0)
    arm_r_dx = transform.get("arm_r_dx", 0)
    lean_dx = transform.get("lean_dx", 0)
    is_flash = transform.get("flash", False)
    squash_y = transform.get("squash_y", 0)
    opacity = transform.get("opacity", 255)

    # Regionen definieren und verschieben
    for y in range(TILE):
        for x in range(TILE):
            r, g, b, a = src[x, y]
            if a == 0:
                continue

            dx, dy = 0, 0

            # Schatten-Zeile: unbewegt
            if y == 15:
                pass
            # Kopf (y=1-6)
            elif y <= 6:
                dy = body_dy + head_dy + squash_y
                dx = lean_dx
            # Ruestung/Koerper (y=7-10)
            elif 7 <= y <= 10:
                if x <= 4:  # Linker Arm / Schild
                    dy = body_dy + arm_l_dy
                    dx = lean_dx
                elif x >= 11:  # Rechter Arm / Waffe
                    dy = body_dy + arm_r_dy
                    dx = lean_dx + arm_r_dx
                else:  # Torso
                    dy = body_dy + squash_y
                    dx = lean_dx
            # Waffe ueber Koerper (x>=12, y<7)
            elif y < 7 and x >= 12:
                dy = body_dy + arm_r_dy
                dx = lean_dx + arm_r_dx
            # Beine (y=11-14)
            elif 11 <= y <= 14:
                if x <= 7:  # Linkes Bein
                    dx, dy = leg_l
                else:  # Rechtes Bein
                    dx, dy = leg_r

            nx = clamp(x + dx, 0, TILE - 1)
            ny = clamp(y + dy, 0, TILE - 1)

            if is_flash:
                dst[nx, ny] = (240, 240, 240, min(a, opacity))
            else:
                dst[nx, ny] = (r, g, b, min(a, opacity))

    return result


# Animations-Keyframes als Transform-Dicts
# Jede Animation ist eine Liste von Transforms

_ANIM_IDLE_KF = [
    {},
    {"body_dy": -1},
    {},
    {"body_dy": -1},
    {},
    {"body_dy": 0},
]

_ANIM_WALK_KF = [
    {"body_dy": 0,  "leg_l_dx": 0,  "leg_l_dy": 0,  "leg_r_dx": 0,  "leg_r_dy": 0},
    {"body_dy": -1, "leg_l_dx": -1, "leg_l_dy": -1, "leg_r_dx": 1,  "leg_r_dy": 0, "arm_l_dy": -1, "arm_r_dy": 1},
    {"body_dy": 0,  "leg_l_dx": -1, "leg_l_dy": 0,  "leg_r_dx": 1,  "leg_r_dy": -1, "arm_l_dy": 0, "arm_r_dy": 0},
    {"body_dy": 0,  "leg_l_dx": 0,  "leg_l_dy": 0,  "leg_r_dx": 0,  "leg_r_dy": 0},
    {"body_dy": -1, "leg_l_dx": 1,  "leg_l_dy": 0,  "leg_r_dx": -1, "leg_r_dy": -1, "arm_l_dy": 1, "arm_r_dy": -1},
    {"body_dy": 0,  "leg_l_dx": 1,  "leg_l_dy": -1, "leg_r_dx": -1, "leg_r_dy": 0, "arm_l_dy": 0, "arm_r_dy": 0},
]

_ANIM_ATTACK_KF = [
    {"arm_r_dy": -1, "arm_r_dx": -1, "lean_dx": -1},  # Ausholen
    {"arm_r_dy": -2, "arm_r_dx": -2, "lean_dx": -1, "body_dy": -1},  # Weit zurueck
    {"arm_r_dy": 0,  "arm_r_dx": 1,  "lean_dx": 1},   # Schwung!
    {"arm_r_dy": 1,  "arm_r_dx": 2,  "lean_dx": 1,  "body_dy": 0},  # Impact
    {"arm_r_dy": 0,  "arm_r_dx": 1,  "lean_dx": 0},   # Nachschwung
    {},  # Zurueck
]

_ANIM_HIT_KF = [
    {"lean_dx": -1, "body_dy": 0},
    {"lean_dx": -2, "body_dy": 0, "flash": True},
    {"lean_dx": -2, "body_dy": 1, "head_dy": 1},
    {"lean_dx": -1, "body_dy": 0},
    {},
]

_ANIM_DEATH_KF = [
    {"body_dy": 0,  "lean_dx": 0},
    {"body_dy": 1,  "lean_dx": -1, "head_dy": 1},
    {"body_dy": 2,  "lean_dx": -2, "head_dy": 1, "squash_y": 1},
    {"body_dy": 3,  "lean_dx": -2, "head_dy": 2, "squash_y": 2},
    {"body_dy": 3,  "lean_dx": -2, "head_dy": 2, "squash_y": 2, "opacity": 200},
    {"body_dy": 3,  "lean_dx": -2, "head_dy": 2, "squash_y": 2, "opacity": 140},
]

_ANIM_CAST_KF = [
    {"arm_l_dy": -1, "arm_r_dy": -1},
    {"arm_l_dy": -2, "arm_r_dy": -2, "body_dy": -1, "head_dy": -1},
    {"arm_l_dy": -2, "arm_r_dy": -2, "body_dy": -1, "head_dy": -1},  # Peak + glow
    {"arm_l_dy": -1, "arm_r_dy": -1, "body_dy": 0},
    {"arm_l_dy": 0, "arm_r_dy": 0},
    {},
]

# ── Comichafte Kurzsequenzen ──

_ANIM_STUMBLE_KF = [  # Stolpern — uebertriebenes Taumeln
    {"lean_dx": -1, "body_dy": 0},
    {"lean_dx": -2, "body_dy": -1, "leg_l_dy": -1, "arm_l_dy": -2, "arm_r_dy": -2},
    {"lean_dx": -3, "body_dy": 1, "leg_r_dx": 1, "head_dy": 1},
    {"lean_dx": -2, "body_dy": 2, "squash_y": 1, "arm_l_dy": 1, "arm_r_dy": 1},
    {"lean_dx": -1, "body_dy": 1, "head_dy": 1},
    {"lean_dx": 0, "body_dy": 0},
]

_ANIM_CELEBRATE_KF = [  # Jubeln — Arme hoch, Huepfen
    {"body_dy": 0},
    {"body_dy": -2, "arm_l_dy": -3, "arm_r_dy": -3, "head_dy": -1},
    {"body_dy": -3, "arm_l_dy": -3, "arm_r_dy": -3, "head_dy": -2, "leg_l_dy": -1, "leg_r_dy": -1},
    {"body_dy": -2, "arm_l_dy": -3, "arm_r_dy": -3, "head_dy": -1},
    {"body_dy": -1, "arm_l_dy": -2, "arm_r_dy": -2},
    {"body_dy": 0},
]

_ANIM_SNEAK_KF = [  # Schleichen — geduckter Gang
    {"body_dy": 1, "head_dy": 1, "squash_y": 1, "lean_dx": 0},
    {"body_dy": 1, "head_dy": 1, "squash_y": 1, "lean_dx": 1, "leg_l_dx": 1, "leg_l_dy": -1},
    {"body_dy": 2, "head_dy": 1, "squash_y": 1, "lean_dx": 1, "leg_r_dx": 1},
    {"body_dy": 1, "head_dy": 1, "squash_y": 1, "lean_dx": 0, "leg_r_dx": 1, "leg_r_dy": -1},
    {"body_dy": 1, "head_dy": 1, "squash_y": 1, "lean_dx": -1, "leg_l_dx": -1},
    {"body_dy": 1, "head_dy": 1, "squash_y": 1},
]

_ANIM_TAUNT_KF = [  # Provozieren — Kopf vor, Arme wedeln
    {"head_dy": 0, "lean_dx": 0},
    {"head_dy": -1, "lean_dx": 1, "arm_r_dy": -2, "arm_r_dx": 1},
    {"head_dy": -1, "lean_dx": 2, "arm_r_dy": -1, "arm_l_dy": -2},
    {"head_dy": 0, "lean_dx": 2, "arm_r_dy": -2, "arm_l_dy": -1},
    {"head_dy": -1, "lean_dx": 1, "arm_r_dy": -1, "arm_l_dy": -2},
    {"lean_dx": 0},
]

_ANIM_DODGE_KF = [  # Ausweichen — schneller Seitsprung
    {"lean_dx": 0, "body_dy": 0},
    {"lean_dx": 2, "body_dy": -1, "leg_l_dx": 1, "leg_r_dx": 1},
    {"lean_dx": 3, "body_dy": -2, "leg_l_dx": 2, "leg_r_dx": 2, "arm_l_dy": -1},
    {"lean_dx": 2, "body_dy": -1, "leg_l_dx": 1, "leg_r_dx": 1},
    {"lean_dx": 1, "body_dy": 0},
    {},
]

_ANIM_SHIVER_KF = [  # Zittern/Angst — schnelles Wackeln
    {"lean_dx": -1, "head_dy": 0},
    {"lean_dx": 1, "head_dy": -1, "arm_l_dy": -1, "arm_r_dy": -1},
    {"lean_dx": -1, "head_dy": 0},
    {"lean_dx": 1, "body_dy": -1, "arm_l_dy": -1, "arm_r_dy": -1},
    {"lean_dx": -1},
    {"lean_dx": 1, "head_dy": -1},
]

_ANIM_BOW_KF = [  # Verbeugung — hoeflich/theatralisch
    {},
    {"body_dy": 1, "head_dy": 1, "arm_r_dy": 1},
    {"body_dy": 2, "head_dy": 2, "squash_y": 1, "arm_r_dy": 2, "arm_l_dy": 1},
    {"body_dy": 2, "head_dy": 2, "squash_y": 1, "arm_r_dy": 2, "arm_l_dy": 1},
    {"body_dy": 1, "head_dy": 1, "arm_r_dy": 1},
    {},
]

_ANIM_LAUGH_KF = [  # Lachen — Koerper schuettelt rhythmisch
    {"body_dy": 0},
    {"body_dy": -1, "head_dy": -1, "squash_y": -1},
    {"body_dy": 1, "head_dy": 1},
    {"body_dy": -1, "head_dy": -1, "squash_y": -1},
    {"body_dy": 1, "head_dy": 1},
    {"body_dy": 0},
]

ANIMATIONS = {
    "idle":      _ANIM_IDLE_KF,
    "walk":      _ANIM_WALK_KF,
    "attack":    _ANIM_ATTACK_KF,
    "hit":       _ANIM_HIT_KF,
    "death":     _ANIM_DEATH_KF,
    "cast":      _ANIM_CAST_KF,
    "stumble":   _ANIM_STUMBLE_KF,
    "celebrate": _ANIM_CELEBRATE_KF,
    "sneak":     _ANIM_SNEAK_KF,
    "taunt":     _ANIM_TAUNT_KF,
    "dodge":     _ANIM_DODGE_KF,
    "shiver":    _ANIM_SHIVER_KF,
    "bow":       _ANIM_BOW_KF,
    "laugh":     _ANIM_LAUGH_KF,
}


def _add_cast_glow(img: Image.Image, char_def: dict, frame_idx: int) -> Image.Image:
    """Fuegt Zauber-Glow ueber den Haenden hinzu (Cast Frames 1-3)."""
    result = img.copy()
    draw = ImageDraw.Draw(result)
    wb = _shade(char_def["weapon_blade"])

    # Glow-Partikel links und rechts
    alpha = [0, 150, 220, 220, 120, 0][min(frame_idx, 5)]
    if alpha > 0:
        # Links (um x=3, y=5-6)
        draw.point((3, 5), fill=(*wb["hi"], alpha))
        draw.point((2, 6), fill=(*wb["mid"], alpha // 2))
        draw.point((4, 6), fill=(*wb["mid"], alpha // 2))
        # Rechts (um x=12, y=5-6)
        draw.point((12, 5), fill=(*wb["hi"], alpha))
        draw.point((11, 6), fill=(*wb["mid"], alpha // 2))
        draw.point((13, 6), fill=(*wb["mid"], alpha // 2))
        # Zentraler Glow
        if frame_idx in (2, 3):
            draw.point((7, 3), fill=(*wb["hi"], alpha))
            draw.point((8, 3), fill=(*wb["hi"], alpha))
            draw.point((7, 2), fill=(*wb["mid"], alpha // 2))
            draw.point((8, 2), fill=(*wb["mid"], alpha // 2))

    return result


def _create_spritesheet(frames: list[Image.Image], scale: int = 4) -> Image.Image:
    """Kombiniert Frames zu einem horizontalen Spritesheet."""
    n = len(frames)
    cell = TILE * scale
    padding = 1
    sheet_w = n * (cell + padding) + padding
    sheet_h = cell + 2 * padding

    sheet = Image.new("RGBA", (sheet_w, sheet_h), (30, 25, 35, 255))

    for i, frame in enumerate(frames):
        x = padding + i * (cell + padding)
        scaled = frame.resize((cell, cell), Image.NEAREST)
        sheet.paste(scaled, (x, padding), scaled)

    return sheet


def generate_animations(rng: random.Random, count: int) -> list[tuple[str, Image.Image]]:
    """Generiert Charakter-Animations-Spritesheets + Einzelframes (Tiny-RPG-Stil)."""
    results = []
    char_names = list(CHAR_DEFS.keys())

    for char_idx in range(min(count, len(char_names))):
        char_name = char_names[char_idx]
        char_def = CHAR_DEFS[char_name]

        # Basis-Sprite zeichnen (einmalig)
        base_sprite = _draw_chibi_base(char_def)

        for anim_name, keyframes in ANIMATIONS.items():
            frames = []
            for f_idx, transform in enumerate(keyframes):
                frame = _apply_frame_transform(base_sprite, transform)

                # Cast-Glow Overlay
                if anim_name == "cast":
                    frame = _add_cast_glow(frame, char_def, f_idx)

                frames.append(frame)
                fname = f"anim_{char_name}_{anim_name}_{f_idx + 1:02d}.png"
                results.append((fname, frame))

            # Spritesheet
            sheet = _create_spritesheet(frames)
            sheet_name = f"sheet_{char_name}_{anim_name}.png"
            results.append((sheet_name, sheet))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 6. LORE-MONSTER-GENERATOR (handgezeichnete AD&D-Ikonen, Chibi-Stil)
# ═══════════════════════════════════════════════════════════════════════════════

def _px(img, x, y, c, a=255):
    """Shortcut fuer sicheres Pixel-Setzen auf Image."""
    if 0 <= x < img.width and 0 <= y < img.height:
        img.load()[x, y] = (*c, a)


def _rect(img, x1, y1, x2, y2, c, a=255):
    """Gefuelltes Rechteck."""
    for yy in range(max(0, y1), min(img.height, y2 + 1)):
        for xx in range(max(0, x1), min(img.width, x2 + 1)):
            img.load()[xx, yy] = (*c, a)


def _draw_beholder() -> list[Image.Image]:
    """Beholder: schwebende Kugel, zentrales Auge, Augenstiele."""
    frames = []
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        bob = -1 if f in (1, 2) else 0

        # Schatten
        for x in range(4, 12):
            _px(img, x, 15, (20, 15, 25), 80)

        # Koerper (Kugel y=3-12)
        body_hi = (140, 90, 130)
        body_mid = (110, 60, 100)
        body_lo = (75, 35, 70)
        # Reihen: oben schmal, Mitte breit, unten schmal
        rows = [
            (5, 10),   # y=3
            (4, 11),   # y=4
            (3, 12),   # y=5
            (3, 12),   # y=6
            (3, 13),   # y=7
            (3, 13),   # y=8
            (3, 12),   # y=9
            (3, 12),   # y=10
            (4, 11),   # y=11
            (5, 10),   # y=12
        ]
        for i, (x1, x2) in enumerate(rows):
            y = 3 + i + bob
            c = body_hi if i < 3 else (body_mid if i < 7 else body_lo)
            for x in range(x1, x2 + 1):
                _px(img, x, y, c)

        # Mund (zahnig, y=10-11)
        mouth_y = 10 + bob
        for x in range(5, 11):
            _px(img, x, mouth_y, (50, 20, 30))
        # Zaehne
        for x in (5, 7, 9):
            _px(img, x, mouth_y, (220, 210, 190))

        # Zentrales Auge (y=6-8, x=6-9)
        eye_y = 6 + bob
        _rect(img, 6, eye_y, 9, eye_y + 2, (230, 230, 220))
        # Pupille
        pupil_x = 7 + (f % 2)
        _px(img, pupil_x, eye_y + 1, (180, 30, 30))
        _px(img, pupil_x + 1, eye_y + 1, (120, 10, 10))

        # Augenstiele (5 Stueck, oben)
        stalk_color = (120, 70, 110)
        stalk_tips = [(3, 1), (5, 0), (8, 0), (10, 0), (12, 1)]
        for sx, sy in stalk_tips:
            sy2 = sy + bob
            _px(img, sx, sy2, stalk_color)
            _px(img, sx, sy2 + 1, stalk_color)
            # Mini-Auge oben
            _px(img, sx, sy2, (220, 200, 60))

        outline_pass(img)
        frames.append(img)
    return frames


def _draw_mind_flayer() -> list[Image.Image]:
    """Mind Flayer: tentakelgesichtiger Humanoid in Robe."""
    frames = []
    skin = (160, 130, 170)
    skin_hi = (185, 155, 195)
    skin_lo = (120, 90, 135)
    robe = (50, 30, 70)
    robe_hi = (70, 45, 90)
    robe_lo = (30, 15, 45)
    eye_c = (240, 240, 240)

    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        bob = -1 if f in (1, 2) else 0

        # Schatten
        for x in range(5, 11): _px(img, x, 15, (20, 15, 25), 80)

        # Kopf (y=1-6) — breit, tentakelfoermig
        for x in range(5, 11): _px(img, x, 1 + bob, skin_hi)
        for x in range(4, 12): _px(img, x, 2 + bob, skin_hi)
        for x in range(4, 12): _px(img, x, 3 + bob, skin)
        for x in range(4, 12): _px(img, x, 4 + bob, skin)
        for x in range(5, 11): _px(img, x, 5 + bob, skin_lo)

        # Augen (y=3)
        _px(img, 6, 3 + bob, eye_c); _px(img, 9, 3 + bob, eye_c)

        # Tentakel unterm Kinn (y=6-8)
        tent_offsets = [(-1 if f % 2 == 0 else 0), (0), (1 if f % 2 == 0 else 0)]
        for i, tx in enumerate([5, 7, 10]):
            for ty in range(6, 9):
                _px(img, tx + tent_offsets[i % 3], ty + bob, skin_lo)

        # Robe (y=7-13)
        for y in range(7, 14):
            w = 3 if y < 10 else (4 if y < 12 else 3)
            c = robe_hi if y < 9 else (robe if y < 11 else robe_lo)
            for x in range(8 - w, 8 + w):
                _px(img, x, y, c)

        # Guertel
        for x in range(5, 11): _px(img, x, 9, (100, 80, 50))

        # Fuesse
        _px(img, 5, 14, robe_lo); _px(img, 6, 14, robe_lo)
        _px(img, 9, 14, robe_lo); _px(img, 10, 14, robe_lo)

        outline_pass(img)
        frames.append(img)
    return frames


def _draw_red_dragon() -> list[Image.Image]:
    """Red Dragon: gefluegelt, rote Schuppen, Feueratem."""
    frames = []
    red_hi = (220, 60, 30)
    red_mid = (180, 35, 20)
    red_lo = (120, 20, 10)
    belly = (210, 160, 80)
    wing = (160, 30, 20)
    wing_mem = (200, 80, 50)
    eye_c = (255, 220, 50)

    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        wing_up = -1 if f in (1, 2) else 0

        # Schatten
        for x in range(2, 14): _px(img, x, 15, (20, 15, 25), 80)

        # Fluegel (hinten, y=2-8)
        for dy in range(5):
            wy = 3 + dy + wing_up
            # Links
            _px(img, 1 - dy // 2, wy, wing)
            _px(img, 2 - dy // 2, wy, wing_mem)
            # Rechts
            _px(img, 14 + dy // 2, wy, wing)
            _px(img, 13 + dy // 2, wy, wing_mem)

        # Koerper (y=5-12)
        for y in range(5, 13):
            w = 4 if 7 <= y <= 10 else 3
            for x in range(8 - w, 8 + w):
                c = red_hi if y < 7 else (red_mid if y < 10 else red_lo)
                _px(img, x, y, c)
        # Bauch
        for y in range(8, 11):
            for x in range(6, 10):
                _px(img, x, y, belly)

        # Kopf (y=3-6, rechts versetzt — Seitenansicht)
        for x in range(6, 11): _px(img, x, 3, red_hi)
        for x in range(5, 12): _px(img, x, 4, red_mid)
        for x in range(6, 11): _px(img, x, 5, red_mid)

        # Hoerner
        _px(img, 5, 2, red_lo); _px(img, 10, 2, red_lo)
        _px(img, 5, 1, red_lo); _px(img, 10, 1, red_lo)

        # Auge
        _px(img, 8, 4, eye_c); _px(img, 9, 4, (200, 50, 20))

        # Maul
        _px(img, 11, 5, (240, 140, 40)); _px(img, 12, 5, (240, 140, 40))

        # Beine (y=12-14)
        _px(img, 5, 12, red_lo); _px(img, 5, 13, red_lo); _px(img, 5, 14, red_lo)
        _px(img, 10, 12, red_lo); _px(img, 10, 13, red_lo); _px(img, 10, 14, red_lo)

        # Schwanz (y=11-13, links)
        _px(img, 3, 11, red_mid); _px(img, 2, 12, red_lo); _px(img, 1, 13, red_lo)

        outline_pass(img)
        frames.append(img)
    return frames


def _draw_owlbear() -> list[Image.Image]:
    """Owlbear: Eulengesicht auf Baerenkoerper."""
    frames = []
    fur_hi = (160, 130, 90)
    fur_mid = (130, 100, 65)
    fur_lo = (95, 70, 45)
    beak = (200, 170, 60)
    feather = (180, 170, 150)
    eye_c = (240, 200, 50)

    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        bob = -1 if f in (1, 2) else 0

        for x in range(4, 12): _px(img, x, 15, (20, 15, 25), 80)

        # Kopf (Eulen-artig, y=1-5)
        for x in range(5, 11): _px(img, x, 1 + bob, feather)
        for x in range(4, 12): _px(img, x, 2 + bob, feather)
        for x in range(4, 12): _px(img, x, 3 + bob, feather)
        for x in range(5, 11): _px(img, x, 4 + bob, feather)

        # Ohren/Federbueschel
        _px(img, 4, 0 + bob, fur_mid); _px(img, 11, 0 + bob, fur_mid)

        # Augen (gross, rund)
        _px(img, 5, 2 + bob, eye_c); _px(img, 6, 2 + bob, (40, 40, 30))
        _px(img, 9, 2 + bob, eye_c); _px(img, 10, 2 + bob, (40, 40, 30))

        # Schnabel
        _px(img, 7, 4 + bob, beak); _px(img, 8, 4 + bob, beak)
        _px(img, 7, 5 + bob, beak)

        # Koerper (Baeren-artig, massig, y=5-12)
        for y in range(5, 13):
            w = 5 if 7 <= y <= 10 else 4
            c = fur_hi if y < 7 else (fur_mid if y < 10 else fur_lo)
            for x in range(8 - w, 8 + w):
                _px(img, x, y, c)

        # Arme/Klauen (y=7-9)
        _px(img, 2, 7 + bob, fur_mid); _px(img, 2, 8 + bob, fur_lo)
        _px(img, 2, 9, (200, 180, 150))  # Klaue
        _px(img, 13, 7 + bob, fur_mid); _px(img, 13, 8 + bob, fur_lo)
        _px(img, 13, 9, (200, 180, 150))

        # Beine
        for y in (12, 13, 14):
            _px(img, 5, y, fur_lo); _px(img, 6, y, fur_lo)
            _px(img, 9, y, fur_lo); _px(img, 10, y, fur_lo)

        outline_pass(img)
        frames.append(img)
    return frames


def _draw_gelatinous_cube() -> list[Image.Image]:
    """Gelatinous Cube: halbtransparenter Wuerfel mit Inhalt."""
    frames = []
    gel = (120, 200, 180)
    gel_lo = (80, 160, 140)

    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))

        # Wuerfel-Koerper (y=2-14, fast ganzes Tile, halbtransparent)
        alpha = 120 + (f % 2) * 20
        for y in range(2, 15):
            for x in range(2, 14):
                _px(img, x, y, gel, alpha)

        # Rand heller
        for x in range(2, 14):
            _px(img, x, 2, gel_lo, alpha + 40)
            _px(img, x, 14, gel_lo, alpha + 40)
        for y in range(2, 15):
            _px(img, 2, y, gel_lo, alpha + 40)
            _px(img, 13, y, gel_lo, alpha + 40)

        # Eingeschlossene Objekte (Knochen, Helm)
        _px(img, 5, 8, (200, 195, 180), 200)  # Knochen
        _px(img, 6, 8, (200, 195, 180), 200)
        _px(img, 6, 9, (200, 195, 180), 200)
        _px(img, 9, 6, (140, 140, 155), 180)  # Helm
        _px(img, 10, 6, (140, 140, 155), 180)
        _px(img, 9, 7, (120, 120, 135), 180)
        _px(img, 10, 7, (120, 120, 135), 180)
        _px(img, 7, 11, (180, 160, 80), 160)  # Muenze
        # Blasen
        bubble_pos = [(4, 4 + f % 3), (11, 6 - f % 2), (8, 3 + f % 2)]
        for bx, by in bubble_pos:
            _px(img, bx, by, (200, 240, 230), 180)

        # Kein outline_pass — Cube ist transparent/formlos
        frames.append(img)
    return frames


def _draw_rust_monster() -> list[Image.Image]:
    """Rust Monster: insektoid, Fuehler, Panzerplatten."""
    frames = []
    rust_hi = (190, 130, 60)
    rust_mid = (160, 100, 40)
    rust_lo = (110, 70, 25)
    belly_c = (200, 180, 120)
    antenna = (170, 120, 50)

    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        bob = 0 if f % 2 == 0 else -1

        for x in range(3, 13): _px(img, x, 15, (20, 15, 25), 80)

        # Koerper (laenglich, y=7-12)
        for y in range(7, 13):
            w = 4 if 8 <= y <= 11 else 3
            c = rust_hi if y < 9 else (rust_mid if y < 11 else rust_lo)
            for x in range(8 - w, 8 + w):
                _px(img, x, y + bob, c)

        # Panzerplatten (Segmente)
        for x in range(5, 11):
            _px(img, x, 9 + bob, rust_lo)

        # Bauch
        for y in range(9, 12):
            for x in range(6, 10):
                _px(img, x, y + bob, belly_c)

        # Kopf (y=5-7, vorne)
        for x in range(5, 10): _px(img, x, 5 + bob, rust_hi)
        for x in range(4, 11): _px(img, x, 6 + bob, rust_mid)
        for x in range(5, 10): _px(img, x, 7 + bob, rust_mid)

        # Augen
        _px(img, 5, 5 + bob, (40, 40, 40)); _px(img, 8, 5 + bob, (40, 40, 40))

        # Fuehler (Antennae, y=2-5)
        ant_wave = 1 if f in (1, 3) else 0
        _px(img, 3 - ant_wave, 2 + bob, antenna)
        _px(img, 4 - ant_wave, 3 + bob, antenna)
        _px(img, 4, 4 + bob, antenna)
        _px(img, 10 + ant_wave, 2 + bob, antenna)
        _px(img, 9 + ant_wave, 3 + bob, antenna)
        _px(img, 9, 4 + bob, antenna)

        # Schwanz (Paddelform, y=12-14)
        _px(img, 8, 13 + bob, rust_lo)
        _px(img, 7, 14, rust_mid); _px(img, 8, 14, rust_lo); _px(img, 9, 14, rust_mid)

        # 6 Beine
        leg_y = 12
        for lx in (4, 6, 10, 12):
            _px(img, lx, leg_y + bob, rust_lo)
            _px(img, lx, leg_y + 1, rust_lo)

        outline_pass(img)
        frames.append(img)
    return frames


def _draw_displacer_beast() -> list[Image.Image]:
    """Displacer Beast: schwarzer Panther mit Schultentakeln, gruene Augen."""
    frames = []
    body_hi = (50, 50, 70)
    body_mid = (30, 30, 50)
    body_lo = (15, 15, 30)
    tentacle = (40, 45, 65)
    eye_c = (80, 240, 80)

    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        tent_wave = 1 if f in (1, 3) else -1

        for x in range(3, 13): _px(img, x, 15, (20, 15, 25), 80)

        # Koerper (Katze, lang, y=7-11)
        for y in range(7, 12):
            w = 4 if 8 <= y <= 10 else 3
            c = body_hi if y < 9 else (body_mid if y < 11 else body_lo)
            for x in range(7 - w, 7 + w):
                _px(img, x, y, c)

        # Kopf (y=5-7)
        for x in range(4, 9): _px(img, x, 5, body_hi)
        for x in range(3, 9): _px(img, x, 6, body_mid)
        for x in range(4, 8): _px(img, x, 7, body_mid)

        # Gruene Augen
        _px(img, 4, 5, eye_c); _px(img, 7, 5, eye_c)

        # Ohren
        _px(img, 3, 4, body_mid); _px(img, 8, 4, body_mid)

        # Tentakel (2 Stueck von Schultern, y=4-9)
        for ty in range(3, 9):
            tx = 11 + tent_wave * (ty - 5) // 2
            _px(img, clamp(tx, 0, 15), ty, tentacle)
        for ty in range(4, 10):
            tx = 12 - tent_wave * (ty - 6) // 2
            _px(img, clamp(tx, 0, 15), ty, tentacle)
        # Tentakel-Spitzen (gezackt)
        _px(img, 12 + tent_wave, 3, (80, 80, 100))
        _px(img, 13 - tent_wave, 4, (80, 80, 100))

        # 4 Beine
        for lx in (4, 6, 8, 10):
            _px(img, lx, 12, body_lo)
            _px(img, lx, 13, body_lo)
            _px(img, lx, 14, body_lo)

        # Schwanz
        _px(img, 2, 10, body_mid); _px(img, 1, 9, body_lo)
        _px(img, 0, 8, body_lo)

        outline_pass(img)
        frames.append(img)
    return frames


def _draw_carrion_crawler() -> list[Image.Image]:
    """Carrion Crawler: riesiger Wurm mit 8 Tentakeln am Kopf."""
    frames = []
    body_hi = (100, 140, 70)
    body_mid = (70, 110, 45)
    body_lo = (50, 80, 30)
    belly_c = (160, 155, 110)
    tent_c = (130, 120, 90)

    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        wave = f % 2

        for x in range(2, 14): _px(img, x, 15, (20, 15, 25), 80)

        # Wurm-Koerper (Segmente, y=6-14)
        for y in range(6, 15):
            w = 3 if 8 <= y <= 12 else 2
            seg = body_hi if y % 2 == wave else body_mid
            for x in range(8 - w, 8 + w):
                _px(img, x, y, seg)
            # Bauch-Streifen
            if 8 <= y <= 12:
                _px(img, 7, y, belly_c); _px(img, 8, y, belly_c)

        # Kopf (y=4-6)
        for x in range(5, 11): _px(img, x, 4, body_hi)
        for x in range(5, 11): _px(img, x, 5, body_mid)
        for x in range(6, 10): _px(img, x, 6, body_lo)

        # Augen
        _px(img, 6, 4, (40, 40, 40)); _px(img, 9, 4, (40, 40, 40))

        # 8 Tentakel (y=1-4, faecher)
        tent_positions = [
            (3 - wave, 1), (4, 2), (5 + wave, 1), (6, 2),
            (9, 2), (10 - wave, 1), (11, 2), (12 + wave, 1),
        ]
        for tx, ty in tent_positions:
            _px(img, tx, ty, tent_c)
            _px(img, tx, ty + 1, tent_c)

        # Mini-Fuesse (Segmentbeine)
        for y in range(8, 13, 2):
            _px(img, 4, y, body_lo); _px(img, 11, y, body_lo)

        outline_pass(img)
        frames.append(img)
    return frames


def _draw_fire_giant() -> list[Image.Image]:
    """Fire Giant: 18 Fuss, schwarze Haut, flammendes Haar."""
    frames = []
    skin = (50, 35, 30)
    skin_hi = (70, 50, 40)
    skin_lo = (30, 20, 18)
    hair = (240, 120, 30)
    hair_hi = (255, 180, 60)
    armor = (120, 100, 80)
    armor_hi = (150, 130, 100)
    armor_lo = (80, 65, 50)

    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        bob = -1 if f in (1, 2) else 0
        flame_flicker = f % 2

        for x in range(4, 12): _px(img, x, 15, (20, 15, 25), 80)

        # Haar (flammenartig, y=0-2)
        flame_cols = [hair, hair_hi]
        for x in range(5, 11):
            h = 0 if (x + flame_flicker) % 2 == 0 else 1
            _px(img, x, h + bob, flame_cols[(x + f) % 2])
        for x in range(4, 12):
            _px(img, x, 2 + bob, hair)

        # Kopf (y=3-5)
        for x in range(5, 11): _px(img, x, 3 + bob, skin_hi)
        for x in range(5, 11): _px(img, x, 4 + bob, skin)
        for x in range(5, 11): _px(img, x, 5 + bob, skin)

        # Augen + Zaehne
        _px(img, 6, 4 + bob, (240, 160, 40))
        _px(img, 9, 4 + bob, (240, 160, 40))
        _px(img, 7, 5 + bob, (220, 210, 180))  # Zahn
        _px(img, 8, 5 + bob, (220, 210, 180))

        # Ruestung/Koerper (y=6-10)
        for y in range(6, 11):
            w = 4 if 7 <= y <= 9 else 3
            c = armor_hi if y < 8 else (armor if y < 10 else armor_lo)
            for x in range(8 - w, 8 + w):
                _px(img, x, y, c)

        # Guertel
        for x in range(5, 11): _px(img, x, 9, (100, 70, 30))

        # Arme
        _px(img, 3, 7, skin); _px(img, 3, 8, skin); _px(img, 3, 9, skin_lo)
        _px(img, 12, 7, skin); _px(img, 12, 8, skin); _px(img, 12, 9, skin_lo)

        # Waffe (grosses Schwert, rechts)
        for y in range(3, 10): _px(img, 14, y, (160, 160, 170))
        _px(img, 13, 10, (100, 70, 40)); _px(img, 14, 10, (100, 70, 40))

        # Beine
        for y in (11, 12, 13, 14):
            _px(img, 5, y, armor_lo); _px(img, 6, y, armor_lo)
            _px(img, 9, y, armor_lo); _px(img, 10, y, armor_lo)

        outline_pass(img)
        frames.append(img)
    return frames


def _draw_mimic() -> list[Image.Image]:
    """Mimic: Truhe die sich oeffnet — Zaehne und Zunge."""
    frames = []
    wood = (130, 90, 45)
    wood_hi = (160, 115, 65)
    wood_lo = (90, 60, 30)
    metal = (180, 170, 100)
    tongue = (200, 60, 60)
    teeth = (230, 225, 210)

    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        mouth_open = f  # 0=zu, 1-3=offen

        for x in range(3, 13): _px(img, x, 15, (20, 15, 25), 80)

        # Deckel (y=3-7, kippt auf bei mouth_open)
        lid_y = 3 - min(mouth_open, 2)
        for y in range(lid_y, lid_y + 3):
            for x in range(3, 13):
                c = wood_hi if y == lid_y else wood
                _px(img, x, y, c)
        # Metallbeschlag Deckel
        _px(img, 3, lid_y + 1, metal); _px(img, 12, lid_y + 1, metal)

        # Koerper/Boden (y=8-14)
        for y in range(8, 15):
            for x in range(3, 13):
                c = wood if y < 11 else wood_lo
                _px(img, x, y, c)

        # Metallbeschlaege
        for x in range(3, 13):
            _px(img, x, 8, metal)
        _px(img, 3, 10, metal); _px(img, 12, 10, metal)
        _px(img, 7, 10, metal); _px(img, 8, 10, metal)  # Schloss

        if mouth_open > 0:
            # Inneres (dunkel)
            for y in range(lid_y + 3, 8):
                for x in range(4, 12):
                    _px(img, x, y, (30, 10, 10))

            # Zaehne oben
            for x in range(4, 12, 2):
                _px(img, x, lid_y + 3, teeth)

            # Zaehne unten
            for x in range(5, 12, 2):
                _px(img, x, 7, teeth)

            # Zunge
            if mouth_open >= 2:
                _px(img, 7, 6, tongue); _px(img, 8, 6, tongue)
                _px(img, 8, 5, tongue)
                if mouth_open >= 3:
                    _px(img, 9, 4, tongue)

            # Augen (erscheinen wenn offen)
            _px(img, 5, lid_y + 2, (255, 200, 50))
            _px(img, 10, lid_y + 2, (255, 200, 50))

        outline_pass(img)
        frames.append(img)
    return frames


# ── 10 neue Lore-Monster ──────────────────────────────────────────────────────

def _draw_troll() -> list[Image.Image]:
    """Troll: Gruen, lang, grosse Arme, 4 Idle-Frames."""
    frames = []
    body = (60, 120, 50)
    dark = (40, 80, 30)
    eye = (255, 200, 50)
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        sway = f % 2
        # Kopf (klein)
        for x in range(6, 10):
            for y in range(1 + sway, 4 + sway):
                _px(img, x, y, body)
        _px(img, 7, 2 + sway, eye); _px(img, 8, 2 + sway, eye)
        # Langer Koerper
        for y in range(4 + sway, 11):
            for x in range(5, 11):
                _px(img, x, y, body if (x + y) % 3 != 0 else dark)
        # Grosse Arme
        for y in range(5, 10):
            _px(img, 3 - (f % 2), y, dark)
            _px(img, 4, y, body)
            _px(img, 11, y, body)
            _px(img, 12 + (f % 2), y, dark)
        # Klauen
        _px(img, 2 - (f % 2), 10, eye); _px(img, 13 + (f % 2), 10, eye)
        # Beine
        for y in range(11, 15):
            _px(img, 6, y, dark); _px(img, 7, y, body)
            _px(img, 8, y, body); _px(img, 9, y, dark)
        outline_pass(img)
        frames.append(img)
    return frames


def _draw_basilisk() -> list[Image.Image]:
    """Basilisk: Reptilisch, 8 Beine, 4 Frames."""
    frames = []
    body = (80, 100, 60)
    belly = (120, 140, 90)
    eye = (255, 50, 50)
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        # Kopf
        for x in range(3, 7):
            for y in range(4, 7):
                _px(img, x, y, body)
        _px(img, 4, 5, eye)
        _px(img, 2, 5, (200, 200, 50))  # Steinblick-Strahl
        # Koerper (lang)
        for x in range(5, 14):
            for y in range(6, 10):
                _px(img, x, y, body if y < 8 else belly)
        # 8 Beine (4 pro Seite)
        leg_off = f % 2
        for lx in (5, 7, 9, 11):
            _px(img, lx, 10 + leg_off, body)
            _px(img, lx, 11 + leg_off, body)
            _px(img, lx + 1, 10 + (1 - leg_off), body)
            _px(img, lx + 1, 11 + (1 - leg_off), body)
        # Schwanz
        for x in range(13, 16):
            _px(img, min(x, 15), 7 + (x - 13) // 2, body)
        outline_pass(img)
        frames.append(img)
    return frames


def _draw_wyvern() -> list[Image.Image]:
    """Wyvern: Gefluegelt, Stachelschwanz, 4 Frames."""
    frames = []
    body = (80, 60, 100)
    wing = (100, 80, 130)
    spike = (200, 60, 40)
    eye = (255, 220, 50)
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        wing_up = -1 if f % 2 == 0 else 1
        # Kopf
        for x in range(6, 10):
            for y in range(3, 6):
                _px(img, x, y, body)
        _px(img, 7, 4, eye); _px(img, 8, 4, eye)
        _px(img, 10, 4, spike)  # Hornschnabel
        # Koerper
        for x in range(5, 11):
            for y in range(6, 10):
                _px(img, x, y, body)
        # Fluegel
        for dy in range(5):
            wx = 4 - dy
            wy = 4 + dy + wing_up
            if 0 <= wx < TILE and 0 <= wy < TILE:
                _px(img, wx, wy, wing)
            wx2 = 11 + dy
            if 0 <= wx2 < TILE and 0 <= wy < TILE:
                _px(img, wx2, wy, wing)
        # Stachelschwanz
        for i in range(4):
            tx = 5 - i
            ty = 10 + i // 2
            if 0 <= tx < TILE and 0 <= ty < TILE:
                _px(img, tx, ty, body if i < 3 else spike)
        # Beine
        _px(img, 6, 10, body); _px(img, 6, 11, body)
        _px(img, 9, 10, body); _px(img, 9, 11, body)
        outline_pass(img)
        frames.append(img)
    return frames


def _draw_lich() -> list[Image.Image]:
    """Lich: Skelett-Magier, gluehende Augen, Krone, 4 Frames."""
    frames = []
    bone = (200, 190, 170)
    robe = (40, 20, 80)
    crown = (220, 180, 50)
    eye = (80, 255, 80)
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        glow = 200 + (f % 2) * 55
        # Krone
        for x in range(5, 11):
            _px(img, x, 1, crown)
        for x in (5, 7, 9):
            _px(img, x, 0, crown)
        # Schaedel
        for x in range(5, 11):
            for y in range(2, 6):
                _px(img, x, y, bone)
        _px(img, 6, 3, (min(glow, 255), 255, min(glow, 255)))  # Glueh-Augen
        _px(img, 9, 3, (min(glow, 255), 255, min(glow, 255)))
        _px(img, 7, 5, (40, 30, 20)); _px(img, 8, 5, (40, 30, 20))  # Mund
        # Robe
        for y in range(6, 14):
            w = 3 + min(y - 6, 3)
            for x in range(8 - w, 8 + w):
                if 0 <= x < TILE:
                    _px(img, x, y, robe)
        # Stab (rechte Hand)
        for y in range(3, 14):
            _px(img, 12, y, (100, 80, 50))
        _px(img, 12, 2, (180, 100, 255))  # Orb oben
        _px(img, 12, 1, (200, 120, 255))
        outline_pass(img)
        frames.append(img)
    return frames


def _draw_manticore() -> list[Image.Image]:
    """Manticore: Loewe + Fledermausfluegel + Skorpionschwanz, 4 Frames."""
    frames = []
    body = (180, 140, 60)
    wing = (120, 80, 60)
    tail = (160, 40, 40)
    mane = (140, 100, 30)
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        wing_dy = -1 if f % 2 == 0 else 0
        # Kopf + Maehne
        for x in range(3, 7):
            for y in range(4, 8):
                _px(img, x, y, mane if y < 5 else body)
        _px(img, 4, 5, (255, 220, 50))  # Auge
        _px(img, 3, 7, (200, 60, 60))   # Maul
        # Koerper
        for x in range(5, 13):
            for y in range(6, 10):
                _px(img, x, y, body)
        # Fluegel
        for dy in range(4):
            wy = 4 + dy + wing_dy
            if 0 <= wy < TILE:
                _px(img, 7 + dy, wy, wing)
                _px(img, 8 + dy, wy, wing)
        # Skorpionschwanz (ueber dem Ruecken)
        _px(img, 13, 7, tail); _px(img, 14, 6, tail)
        _px(img, 14, 5, tail); _px(img, 15, 4, tail)
        _px(img, 15, 3, (220, 60, 60))  # Stachel
        # 4 Beine
        for lx in (5, 7, 9, 11):
            _px(img, lx, 10, body)
            _px(img, lx, 11 + f % 2, body)
        outline_pass(img)
        frames.append(img)
    return frames


def _draw_hydra() -> list[Image.Image]:
    """Hydra: Mehrere Koepfe, Schuppen, 4 Frames."""
    frames = []
    body = (40, 100, 60)
    head_c = (50, 120, 70)
    eye = (255, 200, 50)
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        # Koerper (breit)
        for x in range(4, 12):
            for y in range(8, 13):
                _px(img, x, y, body)
        # Beine
        for lx in (5, 7, 9, 11):
            _px(img, lx, 13, body); _px(img, lx, 14, body)
        # 3 Koepfe auf Haelsen
        head_positions = [(4, 3), (8, 2), (12, 3)]
        neck_sway = f % 2
        for hx, hy in head_positions:
            # Hals
            for ny in range(hy + 2, 9):
                nx = hx + (neck_sway if hx == 8 else 0)
                if 0 <= nx < TILE:
                    _px(img, nx, ny, body)
            # Kopf
            for dx in range(-1, 2):
                for dy in range(-1, 1):
                    cx = hx + dx + (neck_sway if hx == 8 else 0)
                    cy = hy + dy
                    if 0 <= cx < TILE and 0 <= cy < TILE:
                        _px(img, cx, cy, head_c)
            # Augen
            ex = hx + (neck_sway if hx == 8 else 0)
            if 0 <= ex < TILE and 0 <= hy < TILE:
                _px(img, ex, hy, eye)
        outline_pass(img)
        frames.append(img)
    return frames


def _draw_vampire() -> list[Image.Image]:
    """Vampire: Bleich, Umhang, rote Augen, 4 Frames."""
    frames = []
    skin = (220, 200, 190)
    hair = (30, 20, 40)
    cape = (60, 10, 20)
    eye = (255, 30, 30)
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        cape_sway = f % 2
        # Haare
        for x in range(5, 11):
            _px(img, x, 1, hair); _px(img, x, 2, hair)
        # Gesicht
        for x in range(6, 10):
            for y in range(2, 6):
                _px(img, x, y, skin)
        _px(img, 7, 3, eye); _px(img, 8, 3, eye)
        _px(img, 7, 5, (180, 20, 20))  # Zaehne/Mund
        _px(img, 8, 5, (180, 20, 20))
        # Koerper (Anzug)
        for y in range(6, 12):
            for x in range(6, 10):
                _px(img, x, y, (30, 25, 40))
        # Umhang
        for y in range(5, 14):
            w = min(y - 4, 4) + cape_sway
            for x in (8 - w - 1, 8 + w):
                if 0 <= x < TILE:
                    _px(img, x, y, cape)
            if y > 8:
                _px(img, 8 - w - 2, y, cape)
                if 8 + w + 1 < TILE:
                    _px(img, 8 + w + 1, y, cape)
        # Beine
        _px(img, 7, 12, (30, 25, 40)); _px(img, 8, 12, (30, 25, 40))
        _px(img, 7, 13, (30, 25, 40)); _px(img, 8, 13, (30, 25, 40))
        outline_pass(img)
        frames.append(img)
    return frames


def _draw_treant() -> list[Image.Image]:
    """Treant: Baum-Kreatur, Aeste als Arme, 4 Frames."""
    frames = []
    bark = (80, 60, 35)
    bark_dark = (55, 40, 20)
    leaf = (50, 130, 40)
    eye = (200, 180, 50)
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        sway = 1 if f % 2 == 0 else -1
        # Blaetterkrone
        for x in range(3, 13):
            for y in range(0, 5):
                if abs(x - 8) + abs(y - 2) < 6:
                    _px(img, x, y, leaf)
        # Stamm-Koerper
        for y in range(4, 13):
            w = 3 if y < 10 else 2
            for x in range(8 - w, 8 + w):
                _px(img, x, y, bark if (x + y) % 3 != 0 else bark_dark)
        # Gesicht
        _px(img, 6, 6, eye); _px(img, 9, 6, eye)
        _px(img, 7, 8, bark_dark); _px(img, 8, 8, bark_dark)  # Mund
        # Ast-Arme
        for i in range(4):
            ax = 4 - i + sway
            ay = 6 + i
            if 0 <= ax < TILE and 0 <= ay < TILE:
                _px(img, ax, ay, bark)
            ax2 = 11 + i - sway
            if 0 <= ax2 < TILE and 0 <= ay < TILE:
                _px(img, ax2, ay, bark)
        # Blaetter an Armen
        _px(img, 3 + sway, 5, leaf); _px(img, 12 - sway, 5, leaf)
        # Wurzel-Fuesse
        for x in range(5, 11):
            _px(img, x, 13, bark_dark)
        _px(img, 4, 14, bark_dark); _px(img, 11, 14, bark_dark)
        outline_pass(img)
        frames.append(img)
    return frames


def _draw_purple_worm() -> list[Image.Image]:
    """Purple Worm: Riesiger Wurm, Segmente, 4 Frames."""
    frames = []
    body = (120, 40, 140)
    belly = (160, 80, 180)
    mouth = (200, 60, 60)
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        wave_off = f * 0.5
        # Wurm-Segmente (S-Kurve)
        for seg in range(12):
            sx = int(8 + 3 * math.sin((seg + wave_off) * 0.8))
            sy = 2 + seg
            if 0 <= sy < TILE:
                for dx in range(-2, 3):
                    px_ = sx + dx
                    if 0 <= px_ < TILE:
                        c = belly if abs(dx) < 2 else body
                        _px(img, px_, sy, c)
                # Segment-Linien
                if seg % 2 == 0:
                    for dx in range(-2, 3):
                        px_ = sx + dx
                        if 0 <= px_ < TILE:
                            _px(img, px_, sy, (100, 30, 120))
        # Kopf (oben)
        hx = int(8 + 3 * math.sin(wave_off * 0.8))
        for dx in range(-2, 3):
            for dy in range(-1, 2):
                px_ = hx + dx
                py_ = 1 + dy
                if 0 <= px_ < TILE and 0 <= py_ < TILE:
                    _px(img, px_, py_, body)
        # Mund
        if 0 <= hx < TILE:
            _px(img, hx, 0, mouth)
            _px(img, hx - 1, 0, mouth)
            _px(img, hx + 1, 0, mouth)
        outline_pass(img)
        frames.append(img)
    return frames


def _draw_iron_golem() -> list[Image.Image]:
    """Iron Golem: Metallisch, massiv, gluehend, 4 Frames."""
    frames = []
    metal = (140, 140, 155)
    dark_metal = (90, 90, 105)
    glow = (220, 120, 40)
    eye = (255, 160, 50)
    for f in range(4):
        img = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
        glow_pulse = 200 + (f % 2) * 55
        # Kopf (eckig)
        for x in range(5, 11):
            for y in range(1, 4):
                _px(img, x, y, metal)
        # Helm-Schlitze
        _px(img, 6, 2, (min(glow_pulse, 255), 160, 50))
        _px(img, 9, 2, (min(glow_pulse, 255), 160, 50))
        # Massiver Koerper
        for y in range(4, 11):
            w = 4 if y < 8 else 3
            for x in range(8 - w, 8 + w):
                if 0 <= x < TILE:
                    _px(img, x, y, metal if (x + y) % 4 != 0 else dark_metal)
        # Glut-Risse
        for gx, gy in [(6, 6), (9, 7), (7, 9)]:
            _px(img, gx, gy, (min(glow_pulse, 255), 100, 30))
        # Arme (massiv)
        for y in range(5, 9):
            _px(img, 3, y, dark_metal); _px(img, 4, y, metal)
            _px(img, 11, y, metal); _px(img, 12, y, dark_metal)
        # Faeuste
        _px(img, 3, 9, metal); _px(img, 12, 9, metal)
        # Beine (breit)
        for y in range(11, 15):
            _px(img, 5, y, dark_metal); _px(img, 6, y, metal)
            _px(img, 7, y, metal)
            _px(img, 8, y, metal); _px(img, 9, y, metal)
            _px(img, 10, y, dark_metal)
        outline_pass(img)
        frames.append(img)
    return frames


# Registry aller Lore-Monster
LORE_MONSTER_DEFS: dict[str, Callable[[], list[Image.Image]]] = {
    "beholder":       _draw_beholder,
    "mind_flayer":    _draw_mind_flayer,
    "red_dragon":     _draw_red_dragon,
    "owlbear":        _draw_owlbear,
    "gelatinous_cube": _draw_gelatinous_cube,
    "rust_monster":   _draw_rust_monster,
    "displacer_beast": _draw_displacer_beast,
    "carrion_crawler": _draw_carrion_crawler,
    "fire_giant":     _draw_fire_giant,
    "mimic":          _draw_mimic,
    "troll":          _draw_troll,
    "basilisk":       _draw_basilisk,
    "wyvern":         _draw_wyvern,
    "lich":           _draw_lich,
    "manticore":      _draw_manticore,
    "hydra":          _draw_hydra,
    "vampire":        _draw_vampire,
    "treant":         _draw_treant,
    "purple_worm":    _draw_purple_worm,
    "iron_golem":     _draw_iron_golem,
}


def generate_lore_monsters(rng: random.Random, count: int) -> list[tuple[str, Image.Image]]:
    """Generiert handgezeichnete AD&D-Monster-Sprites mit Idle-Animationen."""
    results = []
    names = list(LORE_MONSTER_DEFS.keys())

    for i in range(min(count, len(names))):
        name = names[i]
        draw_fn = LORE_MONSTER_DEFS[name]
        frames = draw_fn()

        for f_idx, frame in enumerate(frames):
            fname = f"monster_{name}_{f_idx + 1:02d}.png"
            results.append((fname, frame))

        # Spritesheet
        sheet = _create_spritesheet(frames)
        results.append((f"sheet_monster_{name}.png", sheet))

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Preview-Sheet
# ═══════════════════════════════════════════════════════════════════════════════

def create_preview_sheet(sprites: list[tuple[str, Image.Image]],
                         output_path: str, scale: int = 4) -> None:
    """Erstellt ein Preview-Sheet aller generierten Sprites."""
    if not sprites:
        return

    cols = 16
    rows = math.ceil(len(sprites) / cols)
    cell = TILE * scale
    padding = 2
    sheet_w = cols * (cell + padding) + padding
    sheet_h = rows * (cell + padding) + padding

    sheet = Image.new("RGBA", (sheet_w, sheet_h), (30, 25, 35, 255))
    draw = ImageDraw.Draw(sheet)

    for idx, (name, sprite) in enumerate(sprites):
        col = idx % cols
        row = idx // cols
        x = padding + col * (cell + padding)
        y = padding + row * (cell + padding)

        # Hintergrund-Zelle
        draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(50, 45, 55, 255))

        # Sprite hochskaliert (Nearest Neighbor)
        scaled = sprite.resize((cell, cell), Image.NEAREST)
        sheet.paste(scaled, (x, y), scaled)

    sheet.save(output_path)
    print(f"Preview-Sheet: {output_path} ({len(sprites)} Sprites, {sheet_w}x{sheet_h}px)")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

CATEGORY_DEFAULTS = {
    "monsters":       12,
    "items":          20,
    "terrain":        17,   # 8 Boden + 9 Moebel/Fallen
    "effects":        16,   # 16 Effekte x 6 Frames
    "animations":     6,    # 6 Charakter-Typen x 6 Animationen x 4-6 Frames + Sheets
    "lore_monsters":  20,   # 20 handgezeichnete AD&D-Ikonen x 4 Idle-Frames + Sheets
    "environments":   210,  # 14 Biome x 15 Tiles
    "cave_extended":  68,   # 68 Hoehlen-spezifische Tiles
}

CATEGORY_GENERATORS = {
    "monsters":       generate_monsters,
    "items":          generate_items,
    "terrain":        generate_terrain,
    "effects":        generate_effects,
    "animations":     generate_animations,
    "lore_monsters":  generate_lore_monsters,
    "environments":   generate_environments,
    "cave_extended":  generate_cave_extended,
}


def main():
    parser = argparse.ArgumentParser(
        description="Prozeduraler Pixel-Art-Generator fuer ARS Dungeon-Tileset"
    )
    parser.add_argument("--category", "-c",
                        choices=list(CATEGORY_GENERATORS.keys()),
                        help="Kategorie zum Generieren")
    parser.add_argument("--count", "-n", type=int, default=0,
                        help="Anzahl Sprites (0 = Kategorie-Default)")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Alle Kategorien generieren")
    parser.add_argument("--seed", "-s", type=int, default=None,
                        help="Random-Seed fuer Reproduzierbarkeit")
    parser.add_argument("--preview", "-p", action="store_true",
                        help="Preview-Sheet generieren")
    parser.add_argument("--output", "-o", type=str, default=OUTPUT_DIR,
                        help=f"Output-Verzeichnis (default: {OUTPUT_DIR})")
    parser.add_argument("--biome", "-b", type=str, default=None,
                        choices=list(BIOME_DEFS.keys()),
                        help="Nur diesen Biom generieren (nur fuer --category environments)")

    args = parser.parse_args()

    if not args.all and not args.category:
        parser.print_help()
        print("\nFEHLER: --category oder --all angeben.")
        sys.exit(1)

    if args.biome and args.category not in (None, "environments"):
        print("WARNUNG: --biome wird nur fuer --category environments beachtet.")

    os.makedirs(args.output, exist_ok=True)

    seed = args.seed if args.seed is not None else random.randint(0, 2**31)
    print(f"Seed: {seed}")

    all_sprites: list[tuple[str, Image.Image]] = []

    categories = list(CATEGORY_GENERATORS.keys()) if args.all else [args.category]

    for cat in categories:
        rng = random.Random(seed)
        count = args.count if args.count > 0 else CATEGORY_DEFAULTS[cat]
        gen_fn = CATEGORY_GENERATORS[cat]

        print(f"\n-- {cat.upper()} ({count}) --")

        # Biom-Filter fuer environments
        if cat == "environments" and args.biome:
            count = args.count if args.count > 0 else 15  # 1 Biom = 15 Tiles
            sprites = gen_fn(rng, count, biome_filter=args.biome)
        else:
            sprites = gen_fn(rng, count)

        for name, sprite in sprites:
            path = os.path.join(args.output, name)
            sprite.save(path)
            print(f"  {name}")

        all_sprites.extend(sprites)

    print(f"\n{len(all_sprites)} Sprites generiert in {args.output}")

    if args.preview:
        preview_path = os.path.join(args.output, "_preview.png")
        create_preview_sheet(all_sprites, preview_path)


if __name__ == "__main__":
    main()
