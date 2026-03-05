"""
scripts/sprite_from_image.py — Hybrid Image-to-Sprite Analyse-Modul

Analysiert ein Bild via Gemini Flash und mappt erkannte Merkmale
auf prozedurale Sprite-Generator-Parameter (CHAR_DEFS-Format).

Verwendung:
  from scripts.sprite_from_image import analyze_image_for_sprite, generate_sprite_from_analysis
  analysis = analyze_image_for_sprite("portrait.png", api_key)
  name, img, meta = generate_sprite_from_analysis(analysis, seed=42)
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Gueltige Werte fuer Validierung
VALID_CHAR_TYPES = {"fighter", "mage", "rogue", "cleric", "skeleton", "orc"}
VALID_BODY_MODS = {"normal", "slim", "stocky", "tall", "tiny", "bulky"}
VALID_COLOR_MODS = {"normal", "bright", "dark", "pale", "vivid"}
VALID_EQUIPS = {"sword_shield", "staff", "dagger", "mace", "axe"}

_ANALYSIS_PROMPT = """\
Analysiere dieses Bild fuer einen 16x16 Pixel-Art Sprite-Generator.
Antworte NUR mit JSON, kein anderer Text.

{
  "char_type": "fighter"|"mage"|"rogue"|"cleric"|"skeleton"|"orc",
  "body_mod": "normal"|"slim"|"stocky"|"tall"|"tiny"|"bulky",
  "color_mod": "normal"|"bright"|"dark"|"pale"|"vivid",
  "skin": [R, G, B],
  "hair": [R, G, B],
  "armor_a": [R, G, B],
  "armor_b": [R, G, B],
  "pants": [R, G, B],
  "boots": [R, G, B],
  "weapon_blade": [R, G, B],
  "weapon_hilt": [R, G, B],
  "equip": "sword_shield"|"staff"|"dagger"|"mace"|"axe",
  "description": "kurze Beschreibung"
}

Waehle char_type nach der naechsten visuellen Uebereinstimmung.
Extrahiere Farben direkt aus dem Bild.
"""


def _clamp_rgb(val: list | tuple) -> tuple[int, int, int]:
    """Stellt sicher, dass RGB-Werte im Bereich 0-255 liegen."""
    if not isinstance(val, (list, tuple)) or len(val) < 3:
        return (128, 128, 128)
    return tuple(max(0, min(255, int(v))) for v in val[:3])


def _extract_json(text: str) -> dict:
    """Extrahiert JSON aus Gemini-Antwort (mit oder ohne ```json Wrapper)."""
    # Versuche ```json ... ``` Block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Versuche rohes JSON
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"Kein JSON in Antwort gefunden: {text[:200]}")


def analyze_image_for_sprite(image_path: str, api_key: str) -> dict[str, Any]:
    """Analysiert ein Bild via Gemini Flash und gibt Sprite-Parameter zurueck.

    Args:
        image_path: Pfad zum Bild (PNG, JPG, BMP, WebP)
        api_key: Gemini API Key

    Returns:
        Dict mit char_type, body_mod, color_mod, Farben (RGB-Tuples),
        equip, description, token_count
    """
    from PIL import Image

    # Bild laden und auf max 512x512 skalieren
    img = Image.open(image_path)
    img.thumbnail((512, 512), Image.LANCZOS)

    # Als PNG in Bytes konvertieren
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    # Gemini API Call
    from google import genai  # type: ignore[import]
    from google.genai import types  # type: ignore[import]

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[{
            "role": "user",
            "parts": [
                types.Part.from_data(data=png_bytes, mime_type="image/png"),
                {"text": _ANALYSIS_PROMPT},
            ],
        }],
        config=types.GenerateContentConfig(
            temperature=0.3,
        ),
    )

    text = response.text or ""
    raw = _extract_json(text)

    # Token-Count aus Response-Metadata
    token_count = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        token_count = getattr(response.usage_metadata, "total_token_count", 0) or 0

    # Validierung und Fallbacks
    result = {
        "char_type": raw.get("char_type", "fighter"),
        "body_mod": raw.get("body_mod", "normal"),
        "color_mod": raw.get("color_mod", "normal"),
        "skin": _clamp_rgb(raw.get("skin", [220, 180, 140])),
        "hair": _clamp_rgb(raw.get("hair", [90, 60, 30])),
        "armor_a": _clamp_rgb(raw.get("armor_a", [90, 95, 115])),
        "armor_b": _clamp_rgb(raw.get("armor_b", [70, 75, 95])),
        "pants": _clamp_rgb(raw.get("pants", [70, 65, 55])),
        "boots": _clamp_rgb(raw.get("boots", [60, 45, 30])),
        "weapon_blade": _clamp_rgb(raw.get("weapon_blade", [190, 195, 200])),
        "weapon_hilt": _clamp_rgb(raw.get("weapon_hilt", [120, 80, 40])),
        "equip": raw.get("equip", "sword_shield"),
        "description": raw.get("description", ""),
        "token_count": token_count,
    }

    # Unbekannte Werte auf Defaults
    if result["char_type"] not in VALID_CHAR_TYPES:
        result["char_type"] = "fighter"
    if result["body_mod"] not in VALID_BODY_MODS:
        result["body_mod"] = "normal"
    if result["color_mod"] not in VALID_COLOR_MODS:
        result["color_mod"] = "normal"
    if result["equip"] not in VALID_EQUIPS:
        result["equip"] = "sword_shield"

    logger.info("Bild-Analyse: %s (%s, %s) — %d Tokens",
                result["char_type"], result["body_mod"], result["equip"], token_count)
    return result


def _build_char_def(analysis: dict) -> dict:
    """Baut ein CHAR_DEFS-kompatibles Dict aus Analyse-Ergebnis."""
    from scripts.pixel_art_creator import CHAR_DEFS

    # Basis-Template fuer equip und eye/pupil
    template = CHAR_DEFS.get(analysis["char_type"], CHAR_DEFS["fighter"])

    return {
        "skin": analysis["skin"],
        "hair": analysis["hair"],
        "armor_a": analysis["armor_a"],
        "armor_b": analysis["armor_b"],
        "pants": analysis["pants"],
        "boots": analysis["boots"],
        "weapon_blade": analysis["weapon_blade"],
        "weapon_hilt": analysis["weapon_hilt"],
        "eye": template["eye"],
        "pupil": template["pupil"],
        "equip": analysis["equip"],
    }


def generate_sprite_from_analysis(
    analysis: dict,
    seed: int = 42,
    variant_idx: int = 0,
    amplitude: float = 1.0,
    chaos: float = 0.0,
    color_jitter: int = 0,
    pixel_noise: float = 0.0,
) -> tuple[str, "Image.Image", dict]:
    """Erzeugt einen Sprite aus Analyse-Ergebnis.

    Returns:
        (filename, pil_image, meta_dict)
    """
    from scripts.pixel_art_creator import _draw_chibi_base, _apply_sprite_variance
    import random

    char_def = _build_char_def(analysis)
    body_mod = analysis.get("body_mod", "normal")
    color_mod = analysis.get("color_mod", "normal")

    img = _draw_chibi_base(char_def, body_mod, color_mod)

    rng = random.Random(seed + variant_idx)
    if color_jitter > 0 or pixel_noise > 0:
        img = _apply_sprite_variance(img, rng, color_jitter, pixel_noise)

    filename = f"img_sprite_{analysis['char_type']}_{body_mod}_{color_mod}_v{variant_idx}.png"
    meta = {
        "category": "image_sprite",
        "sub_type": analysis["char_type"],
        "body_mod": body_mod,
        "color_mod": color_mod,
        "seed": seed,
        "variant_idx": variant_idx,
        "amplitude": amplitude,
        "chaos": chaos,
        "color_jitter": color_jitter,
        "pixel_noise": pixel_noise,
        "description": analysis.get("description", ""),
        "equip": analysis.get("equip", ""),
        "source": "image_analysis",
    }
    return filename, img, meta
