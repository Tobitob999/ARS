"""
scripts/sprite_extractor.py — Automatische Sprite-Erzeugung beim Abenteuer-Laden

Analysiert Adventure-JSON-Daten und erzeugt fehlende Sprites fuer Monster,
NPCs, Items und Zauber-Effekte via pixel_art_creator.

Verwendung:
  from scripts.sprite_extractor import SpriteExtractor
  extractor = SpriteExtractor()
  reqs = extractor.extract_requirements(adventure_data)
  generated = extractor.ensure_sprites(reqs)
"""

from __future__ import annotations

import logging
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("ARS.sprite_extractor")

# ── Pfade ────────────────────────────────────────────────────────────────────

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
GENERATED_DIR = os.path.join(_PROJECT_ROOT, "data", "tilesets", "generated")
LORE_MONSTER_DIR = os.path.join(_PROJECT_ROOT, "data", "lore", "add_2e", "monsters")


# ── Keyword-Maps fuer Palette/Silhouette-Erkennung ──────────────────────────

PALETTE_KEYWORDS: dict[str, list[str]] = {
    "undead": [
        "skelett", "skeleton", "zombie", "ghoul", "ghul", "wight", "lich",
        "wraith", "geist", "mumie", "mummy", "specter", "spectre",
        "untot", "undead", "revenant", "banshee",
    ],
    "demon": [
        "daemon", "demon", "teufel", "devil", "fiend", "succubus",
        "incubus", "balor", "pit_fiend", "imp",
    ],
    "beast": [
        "wolf", "baer", "bear", "spinne", "spider", "ratte", "rat",
        "schlange", "snake", "loewe", "lion", "hund", "dog", "tiger",
        "panther", "boar", "eber", "hirsch", "stag", "adler", "eagle",
        "hawk", "falke", "wyvern", "basilisk", "manticore", "hydra",
        "chimera", "griffon", "greif", "wurm", "worm",
    ],
    "elemental": [
        "elementar", "elemental", "feuer", "fire", "wasser", "water",
        "erde", "earth", "luft", "air", "eis", "ice", "frost",
        "flamme", "flame", "magma", "blitz", "lightning",
    ],
    "insect": [
        "spinne", "spider", "insekt", "insect", "kaefer", "beetle",
        "skorpion", "scorpion", "ameise", "ant", "wespe", "wasp",
        "centipede", "tausendfuessler", "ankeg", "crawler",
    ],
    "arcane": [
        "magier", "mage", "hexe", "witch", "beschwoerer", "summoner",
        "zauberer", "wizard", "sorcerer", "nekromant", "necromancer",
        "warlock", "hexenmeister", "lich",
    ],
}

SILHOUETTE_KEYWORDS: dict[str, list[str]] = {
    "humanoid": [
        "goblin", "ork", "orc", "skelett", "skeleton", "zombie",
        "ritter", "knight", "magier", "mage", "lich", "nekromant",
        "troll", "ogre", "oger", "riese", "giant", "golem",
        "vampire", "vampir", "ghul", "ghoul", "wight",
    ],
    "beast": [
        "wolf", "baer", "bear", "loewe", "lion", "tiger", "hund",
        "dog", "boar", "eber", "ratte", "rat", "basilisk",
        "panther", "scorpion", "skorpion", "spinne", "spider",
    ],
    "blob": [
        "blob", "schleim", "slime", "ooze", "gelatinous", "cube",
        "pudding", "qualle", "jellyfish",
    ],
    "flying": [
        "fledermaus", "bat", "harpyie", "harpy", "drache", "dragon",
        "wyvern", "adler", "eagle", "hawk", "falke", "griffon",
        "manticore", "sphinx",
    ],
    "tall": [
        "treant", "ent", "baum", "tree", "riese", "giant",
        "elementar", "elemental", "daemon", "demon", "teufel",
        "wurm", "worm", "hydra", "naga", "schlange", "snake",
    ],
}

# Effekt-Name → Effekt-Typ Mapping
SPELL_EFFECT_MAP: dict[str, str] = {
    "feuer": "fireball", "fire": "fireball", "flamme": "fireball",
    "feuerpfeil": "fireball", "fireball": "fireball", "feuerball": "fireball",
    "eis": "ice_shard", "ice": "ice_shard", "frost": "ice_shard",
    "eissplitter": "ice_shard", "eissturm": "ice_shard",
    "heilig": "holy_light", "holy": "holy_light", "licht": "holy_light",
    "heiliges licht": "holy_light",
    "segen": "divine_blessing", "bless": "divine_blessing",
    "goettlicher segen": "divine_blessing",
    "magisch": "magic_missile", "magic": "magic_missile",
    "magisches geschoss": "magic_missile", "geschoss": "magic_missile",
    "schild": "shield_spell", "shield": "shield_spell",
    "schutz": "shield_spell",
    "untote": "turn_undead", "turn": "turn_undead",
    "handauflegen": "lay_on_hands", "handauf": "lay_on_hands",
    "gift": "poison_cloud", "poison": "poison_cloud", "giftwolke": "poison_cloud",
    "furcht": "fear_aura", "fear": "fear_aura", "angst": "fear_aura",
    "fluch": "curse", "curse": "curse",
    "blitz": "lightning", "lightning": "lightning",
    "heilen": "heal", "heal": "heal", "heilung": "heal",
    "explosion": "explosion",
}


# ── Datenstruktur ────────────────────────────────────────────────────────────

@dataclass
class SpriteReq:
    """Anforderung fuer ein zu generierendes Sprite."""
    id: str              # "goblin_krieger"
    name: str            # "Goblin-Krieger"
    category: str        # "monster" | "npc" | "item" | "effect" | "party_member"
    size: str            # "S" | "M" | "L" | "H" | "G"
    palette_hint: str    # "undead" | "demon" | "beast" | "elemental" | "insect" | "arcane"
    silhouette_hint: str # "humanoid" | "beast" | "blob" | "flying" | "tall"
    sprite_file: str     # Ziel: "sprite_goblin_krieger.png"


# ── Groessen-Mapping ─────────────────────────────────────────────────────────

SIZE_TO_PX: dict[str, int] = {
    "S": 16,
    "M": 16,
    "L": 24,
    "H": 32,
    "G": 48,
}


def _normalize_id(name: str) -> str:
    """Erzeugt eine saubere ID aus einem Namen."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _detect_palette(name: str) -> str:
    """Erkennt Palette anhand von Keywords im Namen."""
    name_lower = name.lower()
    for palette, keywords in PALETTE_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return palette
    return "beast"  # Default


def _detect_silhouette(name: str) -> str:
    """Erkennt Silhouette anhand von Keywords im Namen."""
    name_lower = name.lower()
    for sil, keywords in SILHOUETTE_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return sil
    return "humanoid"  # Default


def _detect_size_from_hd(hd_value: Any) -> str:
    """Bestimmt Groesse aus Hit Dice Wert."""
    try:
        if isinstance(hd_value, str):
            # "8d8+16" → 8
            m = re.match(r"(\d+)", hd_value)
            hd = int(m.group(1)) if m else 4
        else:
            hd = int(hd_value)
    except (ValueError, TypeError):
        hd = 4

    if hd <= 1:
        return "S"
    if hd <= 4:
        return "M"
    if hd <= 8:
        return "L"
    if hd <= 12:
        return "H"
    return "G"


def _detect_effect_type(spell_name: str) -> str | None:
    """Erkennt Effekt-Typ aus Zauber-/Faehigkeitsname."""
    name_lower = spell_name.lower().strip()
    # Exakter Match zuerst
    if name_lower in SPELL_EFFECT_MAP:
        return SPELL_EFFECT_MAP[name_lower]
    # Teilwort-Match
    for keyword, effect in SPELL_EFFECT_MAP.items():
        if keyword in name_lower:
            return effect
    return None


# ══════════════════════════════════════════════════════════════════════════════
# SpriteExtractor
# ══════════════════════════════════════════════════════════════════════════════

class SpriteExtractor:
    """Extrahiert Sprite-Anforderungen aus Adventure-Daten und erzeugt fehlende."""

    def __init__(self, output_dir: str = GENERATED_DIR) -> None:
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def extract_requirements(self, adventure_data: dict) -> list[SpriteReq]:
        """Analysiert Adventure-JSON und erzeugt Sprite-Anforderungsliste."""
        reqs: dict[str, SpriteReq] = {}  # id → SpriteReq (dedupliziert)

        # NPCs / Monster
        for npc in adventure_data.get("npcs", []):
            npc_name = npc.get("name", "Unknown")
            npc_id = _normalize_id(npc_name)
            npc_type = npc.get("type", "monster")

            if npc_type in ("friendly", "ally", "neutral"):
                category = "npc"
            else:
                category = "monster"

            # Groesse bestimmen
            size = npc.get("size", "")
            if not size or size not in SIZE_TO_PX:
                hd = npc.get("hit_dice", npc.get("hd", npc.get("hp", 4)))
                size = _detect_size_from_hd(hd)

            palette = npc.get("palette", "") or _detect_palette(npc_name)
            silhouette = npc.get("silhouette", "") or _detect_silhouette(npc_name)

            req = SpriteReq(
                id=npc_id,
                name=npc_name,
                category=category,
                size=size,
                palette_hint=palette,
                silhouette_hint=silhouette,
                sprite_file=f"sprite_{npc_id}.png",
            )
            reqs[npc_id] = req

            # Zauber/Faehigkeiten aus NPC-Stats extrahieren
            for spell in npc.get("spells", []):
                spell_name = spell if isinstance(spell, str) else spell.get("name", "")
                effect = _detect_effect_type(spell_name)
                if effect:
                    eff_id = f"effect_{_normalize_id(effect)}"
                    if eff_id not in reqs:
                        reqs[eff_id] = SpriteReq(
                            id=eff_id,
                            name=effect,
                            category="effect",
                            size="M",
                            palette_hint="arcane",
                            silhouette_hint="blob",
                            sprite_file=f"sprite_{eff_id}.png",
                        )

            for ability in npc.get("abilities", []):
                ab_name = ability if isinstance(ability, str) else ability.get("name", "")
                effect = _detect_effect_type(ab_name)
                if effect:
                    eff_id = f"effect_{_normalize_id(effect)}"
                    if eff_id not in reqs:
                        reqs[eff_id] = SpriteReq(
                            id=eff_id,
                            name=effect,
                            category="effect",
                            size="M",
                            palette_hint="arcane",
                            silhouette_hint="blob",
                            sprite_file=f"sprite_{eff_id}.png",
                        )

        # Monster aus locations extrahieren
        for loc in adventure_data.get("locations", []):
            for monster in loc.get("monsters", []):
                m_name = monster.get("name", monster) if isinstance(monster, dict) else str(monster)
                m_id = _normalize_id(m_name)
                if m_id not in reqs:
                    size = "M"
                    if isinstance(monster, dict):
                        size = monster.get("size", "") or _detect_size_from_hd(
                            monster.get("hit_dice", monster.get("hd", 4)))
                    reqs[m_id] = SpriteReq(
                        id=m_id,
                        name=m_name,
                        category="monster",
                        size=size,
                        palette_hint=_detect_palette(m_name),
                        silhouette_hint=_detect_silhouette(m_name),
                        sprite_file=f"sprite_{m_id}.png",
                    )

            # Items aus Locations
            for item in loc.get("items", []):
                i_name = item.get("name", item) if isinstance(item, dict) else str(item)
                i_id = _normalize_id(i_name)
                if i_id not in reqs:
                    reqs[i_id] = SpriteReq(
                        id=i_id,
                        name=i_name,
                        category="item",
                        size="S",
                        palette_hint="beast",
                        silhouette_hint="blob",
                        sprite_file=f"sprite_{i_id}.png",
                    )

            for item in loc.get("treasure", []):
                i_name = item.get("name", item) if isinstance(item, dict) else str(item)
                i_id = _normalize_id(i_name)
                if i_id not in reqs:
                    reqs[i_id] = SpriteReq(
                        id=i_id,
                        name=i_name,
                        category="item",
                        size="S",
                        palette_hint="beast",
                        silhouette_hint="blob",
                        sprite_file=f"sprite_{i_id}.png",
                    )

        return list(reqs.values())

    def ensure_sprites(self, reqs: list[SpriteReq]) -> dict[str, Path]:
        """Erzeugt fehlende Sprites. Gibt dict[id → Path] zurueck."""
        # Lazy-Import um zirkulaere Abhaengigkeiten zu vermeiden
        import sys
        if _SCRIPT_DIR not in sys.path:
            sys.path.insert(0, _SCRIPT_DIR)
        from pixel_art_creator import (
            generate_monster_sized,
            generate_item, generate_effect_sprite,
            PALETTES, SILHOUETTES, ITEM_TEMPLATES, ITEM_COLORS,
            outline_pass,
        )

        generated: dict[str, Path] = {}
        skipped = 0
        created = 0

        for req in reqs:
            target = os.path.join(self.output_dir, req.sprite_file)
            if os.path.exists(target):
                generated[req.id] = Path(target)
                skipped += 1
                continue

            rng = random.Random(hash(req.id) & 0x7FFFFFFF)

            try:
                if req.category in ("monster", "npc"):
                    palette = req.palette_hint if req.palette_hint in PALETTES else "beast"
                    sil = req.silhouette_hint if req.silhouette_hint in SILHOUETTES else "humanoid"
                    size_px = SIZE_TO_PX.get(req.size, 16)
                    img = generate_monster_sized(rng, palette, sil, "normal", "normal", size_px)

                elif req.category == "item":
                    templates = list(ITEM_TEMPLATES.keys())
                    colors = list(ITEM_COLORS.keys())
                    tmpl = rng.choice(templates)
                    color = rng.choice(colors)
                    img = generate_item(rng, tmpl, color)

                elif req.category == "effect":
                    effect_name = req.name
                    img = generate_effect_sprite(rng, effect_name)

                else:
                    # Fallback: einfacher Monster-Sprite
                    img = generate_monster_sized(rng, "beast", "humanoid", "normal", "normal", 16)

                img.save(target)
                generated[req.id] = Path(target)
                created += 1
                logger.debug("SpriteExtractor: %s erzeugt", req.sprite_file)

            except Exception as e:
                logger.warning("SpriteExtractor: Fehler bei %s: %s", req.id, e)

        logger.info("SpriteExtractor: %d erzeugt, %d uebersprungen", created, skipped)
        print(f"SpriteExtractor: {created} erzeugt, {skipped} uebersprungen")
        return generated

    def extract_and_ensure(self, adventure_data: dict) -> dict[str, Path]:
        """Convenience: extract_requirements + ensure_sprites in einem Schritt."""
        reqs = self.extract_requirements(adventure_data)
        if not reqs:
            logger.info("SpriteExtractor: Keine Sprite-Anforderungen gefunden")
            return {}
        return self.ensure_sprites(reqs)
