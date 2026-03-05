#!/usr/bin/env python3
"""
converter.py — AD&D 2e PDF → JSON Lore Converter
Extrahiert Kapitel, Kits und Monster aus PDFs und schreibt JSON-Chunks nach data/lore/add_2e/

Usage:
    py -3 scripts/converter.py --batch p1
    py -3 scripts/converter.py --batch p2
    py -3 scripts/converter.py --pdf "PHBR01.pdf" --type phbr
    py -3 scripts/converter.py --stats
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    print("FEHLER: PyMuPDF nicht installiert. pip install pymupdf")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
PDF_DIR = BASE_DIR / "ADD2e"  # PDFs liegen im ADD2e/ Unterverzeichnis
LORE_BASE = BASE_DIR / "data" / "lore" / "add_2e"

# ---------------------------------------------------------------------------
# P1-Batch-Definition
# ---------------------------------------------------------------------------
P1_PDFS = [
    # (Dateiname, Typ, Zielordner-Kategorie)
    ("TSR Inc - AD&D 2nd Edition - PHBR01 - The Complete Fighter's Handbook.pdf",
     "phbr", "classes", "PHBR01", ["fighter", "warrior", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR02 - The Complete Thief's Handbook.pdf",
     "phbr", "classes", "PHBR02", ["thief", "rogue", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR03 - The Complete Priest's Handbook.pdf",
     "phbr", "classes", "PHBR03", ["priest", "cleric", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR04 - The Complete Wizard's Handbook.pdf",
     "phbr", "classes", "PHBR04", ["wizard", "mage", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR05 - The Complete Psionics Handbook.pdf",
     "psionics", "psionics", "PHBR05", ["psionics", "psionic", "powers"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR06 - The Complete Book of Dwarves.pdf",
     "phbr_race", "races", "PHBR06", ["dwarf", "dwarves", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR07 - The Complete Bard's Handbook.pdf",
     "phbr", "classes", "PHBR07", ["bard", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR08 - The Complete Book of Elves.pdf",
     "phbr_race", "races", "PHBR08", ["elf", "elves", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR09 - The Complete Book of Gnomes and Halflings.pdf",
     "phbr_race", "races", "PHBR09", ["gnome", "halfling", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR10 - The Complete Book of Humanoids.pdf",
     "phbr_race", "races", "PHBR10", ["humanoid", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR11 - The Complete Ranger's Handbook.pdf",
     "phbr", "classes", "PHBR11", ["ranger", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR12 - The Complete Paladin's Handbook.pdf",
     "phbr", "classes", "PHBR12", ["paladin", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR13 - The Complete Druid's Handbook.pdf",
     "phbr", "classes", "PHBR13", ["druid", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR14 - The Complete Barbarian's Handbook.pdf",
     "phbr", "classes", "PHBR14", ["barbarian", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - PHBR15 - The Complete Ninja's Handbook.pdf",
     "phbr", "classes", "PHBR15", ["ninja", "kits"]),
    ("TSR Inc - AD&D 2nd Edition - DMGR3 - Arms and Equipment Guide.pdf",
     "equipment", "equipment", "DMGR3", ["equipment", "weapons", "armor"]),
    ("TSR Inc - AD&D 2nd Edition - Player's Option - Combat & Tactics.pdf",
     "rules_option", "rules_options", "PO_CT", ["combat", "tactics", "rules"]),
    ("TSR Inc - AD&D 2nd Edition - Player's Option - Skills & Powers.pdf",
     "rules_option", "rules_options", "PO_SP", ["skills", "powers", "rules"]),
    ("TSR Inc - AD&D 2nd Edition - Player's Option - Spells & Magic.pdf",
     "rules_option", "rules_options", "PO_SM", ["spells", "magic", "rules"]),
    ("TSR Inc - AD&D 2nd Edition - Tome of Magic.pdf",
     "spells", "spells", "TOM", ["spells", "magic", "wizard", "priest"]),
    ("TSR Inc - AD&D 2nd Edition - Legends and Lore.pdf",
     "deities", "deities", "LAL", ["deities", "gods", "pantheon", "religion"]),
]

# ---------------------------------------------------------------------------
# P2-Batch-Definition (Monster Compendiums)
# ---------------------------------------------------------------------------
P2_PDFS = [
    # (Dateiname, Typ, Zielordner-Kategorie, Code, Basis-Tags)
    ("TSR Inc - AD&D 2nd Edition - Monstrous Compendium Volume 2.pdf",
     "monster", "monsters", "MC_V2", ["monster", "compendium"]),
    ("TSR Inc - AD&D 2nd Edition - Monstrous Compendium - Annual Volume 1.pdf",
     "monster", "monsters", "MC_A1", ["monster", "annual"]),
    ("TSR Inc - AD&D 2nd Edition - Monstrous Compendium - Annual Volume 2.pdf",
     "monster", "monsters", "MC_A2", ["monster", "annual"]),
    ("TSR Inc - AD&D 2nd Edition - Monstrous Compendium - Annual Volume 3.pdf",
     "monster", "monsters", "MC_A3", ["monster", "annual"]),
    ("TSR Inc - AD&D 2nd Edition - Monstrous Compendium - Annual Volume 4.pdf",
     "monster", "monsters", "MC_A4", ["monster", "annual"]),
    ("TSR Inc - AD&D 2nd Edition - Monstrous Compendium - Fiend Folio Appendix.pdf",
     "monster", "monsters", "MC_FF", ["monster", "fiend_folio"]),
    ("TSR Inc - AD&D 2nd Edition - Monstrous Compendium - Mystara Appendix.pdf",
     "monster", "monsters", "MC_MP", ["monster", "mystara"]),
    ("TSR Inc - AD&D 2nd Edition - Monstrous Compendium - Outer Planes Appendix.pdf",
     "monster", "monsters", "MC_OP", ["monster", "outer_planes"]),
    ("TSR Inc - AD&D 2nd Edition - Monstrous Compendium - Savage Coast Appendix.pdf",
     "monster", "monsters", "MC_SC", ["monster", "savage_coast"]),
]

# ---------------------------------------------------------------------------
# P3-Batch: Spell Compendiums + Encyclopedia Magica (Generisch)
# ---------------------------------------------------------------------------
SPELL_PDFS = [
    ("TSR Inc - AD&D 2nd Edition - Wizards Spell Compendium Volume 1.pdf",
     "spell_compendium", "spells", "WSC1", ["spell", "wizard"]),
    ("TSR Inc - AD&D 2nd Edition - Wizards Spell Compendium Volume 2.pdf",
     "spell_compendium", "spells", "WSC2", ["spell", "wizard"]),
    ("TSR Inc - AD&D 2nd Edition - Wizards Spell Compendium Volume 3.pdf",
     "spell_compendium", "spells", "WSC3", ["spell", "wizard"]),
    ("TSR Inc - AD&D 2nd Edition - Wizards Spell Compendium Volume 4.pdf",
     "spell_compendium", "spells", "WSC4", ["spell", "wizard"]),
    ("TSR Inc - AD&D 2nd Edition - Priest Spell Compendium Volume 1.pdf",
     "spell_compendium", "spells", "PSC1", ["spell", "priest"]),
    ("TSR Inc - AD&D 2nd Edition - Priest Spell Compendium Volume 2.pdf",
     "spell_compendium", "spells", "PSC2", ["spell", "priest"]),
    ("TSR Inc - AD&D 2nd Edition - Priest Spell Compendium Volume 3.pdf",
     "spell_compendium", "spells", "PSC3", ["spell", "priest"]),
]

MAGICITEM_PDFS = [
    ("TSR Inc - AD&D 2nd Edition - Encyclopedia Magica Volume 1.pdf",
     "sourcebook", "magic_items", "EM1", ["magic_item", "encyclopedia"]),
    ("TSR Inc - AD&D 2nd Edition - Encyclopedia Magica Volume 2.pdf",
     "sourcebook", "magic_items", "EM2", ["magic_item", "encyclopedia"]),
    ("TSR Inc - AD&D 2nd Edition - Encyclopedia Magica Volume 3.pdf",
     "sourcebook", "magic_items", "EM3", ["magic_item", "encyclopedia"]),
    ("TSR Inc - AD&D 2nd Edition - Encyclopedia Magica Volume 4.pdf",
     "sourcebook", "magic_items", "EM4", ["magic_item", "encyclopedia"]),
    ("TSR Inc - AD&D 2nd Edition - The Magic Encyclopedia Volume 1.pdf",
     "sourcebook", "magic_items", "ME1", ["magic_item", "encyclopedia"]),
    ("TSR Inc - AD&D 2nd Edition - The Magic Encyclopedia Volume 2.pdf",
     "sourcebook", "magic_items", "ME2", ["magic_item", "encyclopedia"]),
]

# ---------------------------------------------------------------------------
# P3-Batch: DMGR Series + DM Core Books (Generisch)
# ---------------------------------------------------------------------------
DMGR_PDFS = [
    ("TSR Inc - AD&D 2nd Edition - DMGR1 - Campaign Sourcebook and Catacomb Guide.pdf",
     "sourcebook", "dm_tools", "DMGR1", ["dm", "campaign"]),
    ("TSR Inc - AD&D 2nd Edition - DMGR2 - Castle Guide.pdf",
     "sourcebook", "dm_tools", "DMGR2", ["dm", "castle"]),
    ("TSR Inc - AD&D 2nd Edition - DMGR4 - Monster Mythology.pdf",
     "sourcebook", "dm_tools", "DMGR4", ["dm", "monster", "mythology", "deities"]),
    ("TSR Inc - AD&D 2nd Edition - DMGR5 - Creative Campaigning.pdf",
     "sourcebook", "dm_tools", "DMGR5", ["dm", "campaign"]),
    ("TSR Inc - AD&D 2nd Edition - DMGR6 - The Complete Book of Villains.pdf",
     "sourcebook", "dm_tools", "DMGR6", ["dm", "villain", "npc"]),
    ("TSR Inc - AD&D 2nd Edition - DMGR7 - The Complete Book of Necromancers.pdf",
     "sourcebook", "dm_tools", "DMGR7", ["dm", "necromancer", "undead"]),
    ("TSR Inc - AD&D 2nd Edition - DMGR8 - Sages and Specialists.pdf",
     "sourcebook", "dm_tools", "DMGR8", ["dm", "sage", "npc"]),
    ("TSR Inc - AD&D 2nd Edition - DMGR9 - Of Ships And Sea.pdf",
     "sourcebook", "dm_tools", "DMGR9", ["dm", "ships", "naval"]),
]

DM_CORE_PDFS = [
    ("TSR Inc - AD&D 2nd Edition - Dungeon Builder's Guidebook.pdf",
     "sourcebook", "dm_tools", "DBG", ["dm", "dungeon"]),
    ("TSR Inc - AD&D 2nd Edition - World Builders Guidebook.pdf",
     "sourcebook", "dm_tools", "WBG", ["dm", "world"]),
    ("TSR Inc - AD&D 2nd Edition - Dungeon Master Option - High-Level Campaigns.pdf",
     "sourcebook", "dm_tools", "DMO_HLC", ["dm", "high_level", "rules"]),
    ("TSR Inc - AD&D 2nd Edition - Book of Artifacts.pdf",
     "sourcebook", "magic_items", "BOA", ["magic_item", "artifact"]),
    ("Player s Handbook (2nd Edition) 2101.pdf",
     "sourcebook", "rules", "PHB", ["rules", "core", "player"]),
]

# ---------------------------------------------------------------------------
# P4-Batch: Dragonlance (Eigene Welt — NICHT mit Generic AD&D mischen!)
# Output: data/lore/add_2e/settings/dragonlance/
# ---------------------------------------------------------------------------
DL_PDFS = [
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Tales of the Lance.pdf",
     "sourcebook", "settings/dragonlance", "DL_TTL", ["dragonlance", "krynn", "sourcebook"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Player's Guide to the Dragonlance Campaign.pdf",
     "sourcebook", "settings/dragonlance", "DL_PG", ["dragonlance", "krynn", "player"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ A Saga Companion.pdf",
     "sourcebook", "settings/dragonlance", "DL_SC", ["dragonlance", "krynn", "saga"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Classics 15th Anniversary Edition.pdf",
     "sourcebook", "settings/dragonlance", "DL_C15", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLA1 - Dragon Dawn.pdf",
     "sourcebook", "settings/dragonlance", "DLA1", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLA2 - Dragon Knight.pdf",
     "sourcebook", "settings/dragonlance", "DLA2", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLA3 - Dragons Rest.pdf",
     "sourcebook", "settings/dragonlance", "DLA3", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLC1 - Classics Volume 1.pdf",
     "sourcebook", "settings/dragonlance", "DLC1", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLC2 - Classics Volume 2.pdf",
     "sourcebook", "settings/dragonlance", "DLC2", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLC3 - Classics Volume 3.pdf",
     "sourcebook", "settings/dragonlance", "DLC3", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLE1 - In Search of Dragons.pdf",
     "sourcebook", "settings/dragonlance", "DLE1", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLE2 - Dragon Magic.pdf",
     "sourcebook", "settings/dragonlance", "DLE2", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLE3 - Dragon Keep.pdf",
     "sourcebook", "settings/dragonlance", "DLE3", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLQ1 - Knight's Sword.pdf",
     "sourcebook", "settings/dragonlance", "DLQ1", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLQ2 - Flints Axe.pdf",
     "sourcebook", "settings/dragonlance", "DLQ2", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLR1 - Otherlands.pdf",
     "sourcebook", "settings/dragonlance", "DLR1", ["dragonlance", "krynn", "region"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLR2 - Taladas, The Minotaurs.pdf",
     "sourcebook", "settings/dragonlance", "DLR2", ["dragonlance", "krynn", "taladas"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLR3 - Unsung Heroes.pdf",
     "sourcebook", "settings/dragonlance", "DLR3", ["dragonlance", "krynn", "npc"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLS1 - New Beginnings.pdf",
     "sourcebook", "settings/dragonlance", "DLS1", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLS2 - Tree Lords.pdf",
     "sourcebook", "settings/dragonlance", "DLS2", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLS3 - Oak Lords.pdf",
     "sourcebook", "settings/dragonlance", "DLS3", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLS4 - Wild Elves.pdf",
     "sourcebook", "settings/dragonlance", "DLS4", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ DLT1 - New Tales.pdf",
     "sourcebook", "settings/dragonlance", "DLT1", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Dwarven Kingdoms of Krynn.pdf",
     "sourcebook", "settings/dragonlance", "DL_DKK", ["dragonlance", "krynn", "dwarf"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Fifth Age.pdf",
     "sourcebook", "settings/dragonlance", "DL_5A", ["dragonlance", "krynn", "fifth_age"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Heroes of Defiance.pdf",
     "sourcebook", "settings/dragonlance", "DL_HOD", ["dragonlance", "krynn", "heroes"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Heroes of Hope.pdf",
     "sourcebook", "settings/dragonlance", "DL_HOH", ["dragonlance", "krynn", "heroes"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Heroes of Sorcery.pdf",
     "sourcebook", "settings/dragonlance", "DL_HOS", ["dragonlance", "krynn", "heroes"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Heroes of Steel.pdf",
     "sourcebook", "settings/dragonlance", "DL_HOST", ["dragonlance", "krynn", "heroes"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ History of Dragonlance.pdf",
     "sourcebook", "settings/dragonlance", "DL_HIST", ["dragonlance", "krynn", "history"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ More Leaves from the Inn of the Last Home.pdf",
     "sourcebook", "settings/dragonlance", "DL_MLFH", ["dragonlance", "krynn", "sourcebook"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Palanthas.pdf",
     "sourcebook", "settings/dragonlance", "DL_PAL", ["dragonlance", "krynn", "city", "palanthas"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Seeds of Chaos.pdf",
     "sourcebook", "settings/dragonlance", "DL_SOC", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Chaos Spawn.pdf",
     "sourcebook", "settings/dragonlance", "DL_CS", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Citadel of Light.pdf",
     "sourcebook", "settings/dragonlance", "DL_COL", ["dragonlance", "krynn", "sourcebook"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Battle Lines Adventure 1 - The Sylvan Veil.pdf",
     "sourcebook", "settings/dragonlance", "DL_BL1", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Battle Lines Adventure 2 - Rise of the Titans.pdf",
     "sourcebook", "settings/dragonlance", "DL_BL2", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Book Of Lairs.pdf",
     "sourcebook", "settings/dragonlance", "DL_BOL", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ The Last Tower - Legacy of Raistlin.pdf",
     "sourcebook", "settings/dragonlance", "DL_LT", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Time of the Dragon Boxset.pdf",
     "sourcebook", "settings/dragonlance", "DL_TOTD", ["dragonlance", "krynn", "taladas"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ Wings of Fury.pdf",
     "sourcebook", "settings/dragonlance", "DL_WOF", ["dragonlance", "krynn", "adventure"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ The Bestiary.pdf",
     "sourcebook", "settings/dragonlance", "DL_BEST", ["dragonlance", "krynn", "monster"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ TM3 - World of Krynn Trail Map.pdf",
     "sourcebook", "settings/dragonlance", "DL_TM3", ["dragonlance", "krynn", "map"]),
    ("TSR Inc - AD&D 2nd Edition - Dragonlance_ The Art of the Dragonlance Saga.pdf",
     "sourcebook", "settings/dragonlance", "DL_ART", ["dragonlance", "krynn", "art"]),
]

# ---------------------------------------------------------------------------
# P4-Batch: Historical Reference (Generisch, echte Geschichte)
# Output: data/lore/add_2e/settings/historical/
# ---------------------------------------------------------------------------
HR_PDFS = [
    ("TSR Inc - AD&D 2nd Edition - HR1 - Vikings Campaign.pdf",
     "sourcebook", "settings/historical", "HR1", ["historical", "vikings", "norse"]),
    ("TSR Inc - AD&D 2nd Edition - HR2 - Charlemagne's Paladins.pdf",
     "sourcebook", "settings/historical", "HR2", ["historical", "medieval", "charlemagne"]),
    ("TSR Inc - AD&D 2nd Edition - HR3 - Celts.pdf",
     "sourcebook", "settings/historical", "HR3", ["historical", "celtic"]),
    ("TSR Inc - AD&D 2nd Edition - HR4 - A Mighty Fortress.pdf",
     "sourcebook", "settings/historical", "HR4", ["historical", "renaissance"]),
    ("TSR Inc - AD&D 2nd Edition - HR5 - Glory of Rome.pdf",
     "sourcebook", "settings/historical", "HR5", ["historical", "roman"]),
    ("TSR Inc - AD&D 2nd Edition - HR6 - Age of Heroes.pdf",
     "sourcebook", "settings/historical", "HR6", ["historical", "greek"]),
    ("TSR Inc - AD&D 2nd Edition - HR7 - Crusades.pdf",
     "sourcebook", "settings/historical", "HR7", ["historical", "crusades"]),
]

# ---------------------------------------------------------------------------
# OCR-Varianten: bevorzuge _text.pdf falls vorhanden
# ---------------------------------------------------------------------------
TEXT_VARIANT_PDFS = {
    "PHBR10", "PHBR12", "DMGR3",
    "MC_V2", "MC_A1", "MC_A4", "MC_FF", "MC_OP",
    "WSC1", "PSC2", "ME2",
    "DMGR4", "DMGR5", "DMGR7", "DMGR9",
    "DL_SC", "DL_5A", "DL_HOS", "DL_HIST", "DL_MLFH", "DL_PAL",
    "DL_SOC", "DL_CS", "DL_COL", "DL_BL1", "DL_BL2", "DL_WOF", "DL_TM3",
    "HR3", "HR4",
}


def resolve_pdf_path(filename: str, code: str) -> Path:
    """Gibt den effektiven PDF-Pfad zurueck, bevorzugt _text.pdf Variante."""
    base = PDF_DIR / filename
    if code in TEXT_VARIANT_PDFS:
        stem = filename.replace(".pdf", "")
        text_variant = PDF_DIR / (stem + "_text.pdf")
        if text_variant.exists():
            return text_variant
    return base


# ---------------------------------------------------------------------------
# Text-Hilfsfunktionen
# ---------------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """NFC-Normalisierung, Steuerzeichen entfernen, Zeilenenden normalisieren."""
    text = unicodedata.normalize("NFC", text)
    # OCR-Artefakte: seltsame Bindestriche, geschuetzte Leerzeichen
    text = text.replace("\u00ad", "-")   # soft hyphen
    text = text.replace("\u2019", "'")   # right single quote
    text = text.replace("\u201c", '"')   # left double quote
    text = text.replace("\u201d", '"')   # right double quote
    text = text.replace("\u2014", "--")  # em dash
    text = text.replace("\u2013", "-")   # en dash
    text = text.replace("\uf0b7", "*")   # bullet symbol
    text = text.replace("\uf0a7", "*")   # section bullet
    # Zusammengefuegte Woerter durch OCR-Zeilenumbruch trennen (Bindestrich am Zeilen-Ende)
    text = re.sub(r"-\n(\w)", r"\1", text)
    # Mehrfach-Leerzeichen reduzieren
    text = re.sub(r" {3,}", "  ", text)
    return text.strip()


def slugify(text: str) -> str:
    """Erzeuge snake_case-Dateiname aus Titel."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text[:80]  # maximale Laenge


def extract_all_pages(pdf_path: Path) -> list[dict]:
    """Extrahiert Text aller Seiten als Liste von {page, text}."""
    doc = fitz.open(str(pdf_path))
    pages = []
    for i in range(len(doc)):
        text = doc[i].get_text()
        text = normalize_text(text)
        pages.append({"page": i + 1, "text": text})
    doc.close()
    return pages


# ---------------------------------------------------------------------------
# Kapitel-Segmentierung
# ---------------------------------------------------------------------------

CHAPTER_PATTERNS = [
    # "Chapter 1:" oder "Chapter One:"
    re.compile(r"^Chapter\s+(\d+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve)\b", re.IGNORECASE),
    # "CHAPTER 1" (Grossbuchstaben)
    re.compile(r"^CHAPTER\s+\d+", re.MULTILINE),
    # Sehr kurze Seiten (<200 chars) gefolgt von langer Seite — Titel-Seite eines Kapitels
    # Wird in split_into_chapters() behandelt
]

KNOWN_CHAPTER_KEYWORDS = [
    "Introduction", "Appendix", "Preface", "Foreword",
    "Part One", "Part Two", "Part Three", "Part Four",
    "Book One", "Book Two",
]


def is_chapter_start(page_data: dict, prev_page_data: Optional[dict]) -> bool:
    """Erkennt ob eine Seite ein neues Kapitel beginnt."""
    text = page_data["text"]
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    if not lines:
        return False

    first_line = lines[0] if lines else ""
    first_lines_joined = " ".join(lines[:3])

    # Pattern-Match auf erste Zeile
    for pat in CHAPTER_PATTERNS:
        if pat.match(first_line):
            return True

    # Bekannte Kapitel-Keywords als erste Zeile
    for kw in KNOWN_CHAPTER_KEYWORDS:
        if first_line.lower().startswith(kw.lower()):
            return True

    # Kurze Seite (<150 chars) mit 2-6 Zeilen = moeglicherweise Titel-Seite
    if len(text) < 150 and 2 <= len(lines) <= 8:
        # Naechste Seite hat viel Text?
        return True

    # Seite beginnt mit "1 " / "2 " etc. am Anfang (Kapitel-Nummer)
    if re.match(r"^\d{1,2}\s+\n", text):
        return True

    return False


def extract_chapter_title(text: str, page_num: int) -> str:
    """Extrahiert den Kapitel-Titel aus dem Seitentext."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return f"Page {page_num}"

    for pat in CHAPTER_PATTERNS:
        m = pat.match(lines[0])
        if m:
            # Naechste Zeile ist oft der Titel
            title = lines[0]
            if len(lines) > 1 and len(lines[1]) < 60:
                title = lines[0] + ": " + lines[1]
            return title

    for kw in KNOWN_CHAPTER_KEYWORDS:
        if lines[0].lower().startswith(kw.lower()):
            return lines[0]

    # Kurze Seite: Inhalt ist der Titel
    if len(text) < 150:
        return " ".join(lines[:2])

    return lines[0] if lines[0] and len(lines[0]) < 80 else f"Section (Page {page_num})"


def split_into_chapters(pages: list[dict]) -> list[dict]:
    """
    Teilt Seiten in Kapitel-Chunks auf.
    Gibt Liste von {title, start_page, end_page, text} zurueck.
    """
    chapters = []
    current_title = "Introduction"
    current_start = 1
    current_pages = []

    for i, page in enumerate(pages):
        prev = pages[i - 1] if i > 0 else None
        if i > 0 and is_chapter_start(page, prev):
            if current_pages:
                combined = "\n\n".join(p["text"] for p in current_pages if p["text"])
                if combined.strip():
                    chapters.append({
                        "title": current_title,
                        "start_page": current_start,
                        "end_page": current_pages[-1]["page"],
                        "text": combined,
                    })
            current_title = extract_chapter_title(page["text"], page["page"])
            current_start = page["page"]
            current_pages = [page]
        else:
            current_pages.append(page)

    # Letztes Kapitel
    if current_pages:
        combined = "\n\n".join(p["text"] for p in current_pages if p["text"])
        if combined.strip():
            chapters.append({
                "title": current_title,
                "start_page": current_start,
                "end_page": current_pages[-1]["page"],
                "text": combined,
            })

    # Falls keine Kapitel erkannt: Gesamtdokument als ein Chunk
    if not chapters:
        all_text = "\n\n".join(p["text"] for p in pages if p["text"])
        chapters.append({
            "title": "Full Document",
            "start_page": 1,
            "end_page": pages[-1]["page"] if pages else 1,
            "text": all_text,
        })

    return chapters


# ---------------------------------------------------------------------------
# Kit-Extraktion
# ---------------------------------------------------------------------------

KIT_MARKERS = [
    "Description:", "Role:", "Requirements:", "Secondary Skills:",
    "Weapon Proficiencies:", "Nonweapon Proficiencies:", "Equipment:",
    "Special Benefits:", "Special Hindrances:", "Wealth Options:",
    "Weapon Profici", "Nonweapon Profici",
]

KIT_SECTION_PATTERN = re.compile(
    r"(?:Description:|Role:)",
    re.IGNORECASE
)

# Muster zum Erkennen von Kit-Ueberschriften (Eigenname vor 'Description:')
KIT_HEADER_PATTERN = re.compile(
    r"^([A-Z][A-Za-z\s'\-]{2,50})\n.*?(?:Description:|Role:)",
    re.MULTILINE | re.DOTALL
)


def find_kit_boundaries(full_text: str) -> list[tuple[int, int, str]]:
    """
    Findet Kit-Grenzen im Text.
    Gibt Liste von (start_char, end_char, kit_name) zurueck.
    """
    kits = []

    # Finde alle "Description:" oder "Role:" als Kit-Starts
    marker_positions = []
    for m in re.finditer(r"(?:^|\n)([A-Z][A-Za-z\s'\-]{2,50})\n(?:[\w\s]{0,200}\n)?(?:Description:|Role:)",
                         full_text, re.MULTILINE):
        name = m.group(1).strip()
        # Filter: Vermeide Chapter-Ueberschriften und generische Woerter
        skip_words = {"Chapter", "Introduction", "Appendix", "Table", "The", "This",
                      "Part", "Book", "Section", "Note", "Important", "Summary",
                      "Kits", "Warriors", "Warrior", "Characters", "Character",
                      "Special", "Secondary", "Weapon", "Nonweapon", "Equipment"}
        first_word = name.split()[0] if name.split() else ""
        if first_word not in skip_words and len(name) > 3:
            marker_positions.append((m.start(), name))

    # Berechne End-Positionen
    for i, (pos, name) in enumerate(marker_positions):
        end = marker_positions[i + 1][0] if i + 1 < len(marker_positions) else len(full_text)
        kits.append((pos, end, name))

    return kits


def extract_kits_from_text(
    full_text: str,
    source: str,
    base_tags: list[str],
    pages: list[dict],
) -> list[dict]:
    """Extrahiert Kits aus dem gesamten Dokumenttext."""
    kits = []

    boundaries = find_kit_boundaries(full_text)
    if not boundaries:
        return kits

    # Erstelle eine schnelle Page-Lookup Tabelle (char_offset → page_num)
    page_starts = []
    offset = 0
    for p in pages:
        page_starts.append((offset, p["page"]))
        offset += len(p["text"]) + 2  # +2 fuer "\n\n" Trennzeichen

    def find_page(char_pos: int) -> int:
        for i in range(len(page_starts) - 1, -1, -1):
            if char_pos >= page_starts[i][0]:
                return page_starts[i][1]
        return 1

    for start, end, name in boundaries:
        snippet = full_text[start:end].strip()
        if len(snippet) < 100:
            continue  # Zu kurz, kein echter Kit

        page_num = find_page(start)

        # Bereinige Kit-Name
        clean_name = re.sub(r"\s+", " ", name).strip()
        # Bestimme Tags aus Kit-Inhalt
        tags = list(base_tags)
        tags.append("kit")
        name_lower = clean_name.lower()
        for word in name_lower.split():
            if len(word) > 3:
                tags.append(word)

        kit_chunk = {
            "name": f"Kit: {clean_name}",
            "source": source,
            "source_page": page_num,
            "category": "kit",
            "priority": "core",
            "system_id": "add_2e",
            "schema_version": "1.0.0",
            "raw_text": snippet[:8000],  # Max 8000 chars
            "tags": list(dict.fromkeys(tags)),  # Deduplizieren
        }
        kits.append(kit_chunk)

    return kits


# ---------------------------------------------------------------------------
# Psionic Power Extraktion
# ---------------------------------------------------------------------------

PSIONIC_DISCIPLINES = [
    "Telepathy", "Psychokinesis", "Psychometabolism",
    "Psychoportation", "Clairsentience", "Metapsionics"
]


def extract_psionics(pages: list[dict], source: str) -> list[dict]:
    """Extrahiert Psionic-Kapitel-Chunks."""
    chunks = []
    full_text = "\n\n".join(p["text"] for p in pages if p["text"])
    chapters = split_into_chapters(pages)

    for ch in chapters:
        title = ch["title"]
        tags = ["psionics", "psionic"]
        for disc in PSIONIC_DISCIPLINES:
            if disc.lower() in title.lower() or disc.lower() in ch["text"].lower()[:500]:
                tags.append(disc.lower())

        chunk = make_chapter_chunk(ch, source, tags, "psionics")
        chunks.append(chunk)

    return chunks


# ---------------------------------------------------------------------------
# Equipment-Extraktion
# ---------------------------------------------------------------------------

def extract_equipment(pages: list[dict], source: str) -> list[dict]:
    """Extrahiert Equipment-Kapitel."""
    chapters = split_into_chapters(pages)
    chunks = []
    for ch in chapters:
        tags = ["equipment"]
        text_lower = ch["text"].lower()
        for kw in ["weapon", "armor", "armour", "shield", "helm", "boot",
                   "cloak", "ring", "pouch", "tool", "vehicle", "horse"]:
            if kw in text_lower:
                tags.append(kw)
        chunk = make_chapter_chunk(ch, source, list(dict.fromkeys(tags)), "equipment")
        chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# Deity-Extraktion
# ---------------------------------------------------------------------------

DEITY_MARKERS = re.compile(
    r"^([A-Z][A-Za-z\s]{2,40})\n(?:Lesser|Greater|Intermediate|Demi|Over)[\s\-]?god",
    re.MULTILINE
)


def extract_deities(pages: list[dict], source: str) -> list[dict]:
    """Extrahiert Kapitel-Chunks aus Legends and Lore."""
    chapters = split_into_chapters(pages)
    chunks = []
    for ch in chapters:
        tags = ["deity", "gods", "religion", "pantheon"]
        title_lower = ch["title"].lower()
        for kw in ["greek", "norse", "egyptian", "celtic", "babylonian",
                   "sumerian", "finnish", "chinese", "japanese", "indian",
                   "aztec", "mayan", "polynesian"]:
            if kw in title_lower or kw in ch["text"].lower()[:300]:
                tags.append(kw)
        chunk = make_chapter_chunk(ch, source, list(dict.fromkeys(tags)), "deities")
        chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# Spell-Compendium-Extraktion (Wizard/Priest Spell Compendium)
# ---------------------------------------------------------------------------

SPELL_STAT_LABELS = [
    ("level", re.compile(r"^Level:", re.IGNORECASE)),
    ("range", re.compile(r"^Range:", re.IGNORECASE)),
    ("components", re.compile(r"^Components:", re.IGNORECASE)),
    ("casting_time", re.compile(r"^Casting Time:", re.IGNORECASE)),
    ("duration", re.compile(r"^Duration:", re.IGNORECASE)),
    ("area_of_effect", re.compile(r"^Area of Effect:", re.IGNORECASE)),
    ("saving_throw", re.compile(r"^Saving Throw:", re.IGNORECASE)),
]

# Erkennung von Spell-School-Zeilen: (School) oder (School, School)
SCHOOL_PATTERN = re.compile(
    r"^\((?:Abjuration|Alteration|Conjuration|Summoning|Divination|Enchantment|Charm|"
    r"Evocation|Illusion|Phantasm|Invocation|Necromancy|Chronomancy|"
    r"Greater Divination|Lesser Divination|Wild Magic|Geometry|"
    r"Song|Elemental|Shadow|Alchemy|Artifice|Mentalism|Water|"
    r"Air|Fire|Earth|Animal|Plant|Sun|Weather|Healing|Creation|"
    r"Guardian|Chaos|Combat|Numbers|Thought|Time|Travelers|Wards|War|Law)",
    re.IGNORECASE
)


def find_spell_boundaries(pages: list[dict]) -> list[dict]:
    """
    Findet Spell-Eintraege in Spell-Compendium-Seiten.
    Erkennt: Name-Zeile gefolgt von School und Level innerhalb von 8 Zeilen.
    Gibt Liste von {name, school, start_page, text} zurueck.
    """
    # Kombiniere alle Seiten zu Zeilen mit Seiten-Tracking
    all_lines = []
    for p in pages:
        for line in p["text"].split("\n"):
            all_lines.append((line.strip(), p["page"]))

    spells = []
    i = 0
    while i < len(all_lines):
        line, page = all_lines[i]

        # Kandidat: Nicht-leere Zeile, 3-60 Zeichen, beginnt mit Grossbuchstabe
        # Gefolgt von School-Pattern oder Level: innerhalb von 8 Zeilen
        if (line and 3 <= len(line) <= 60 and line[0].isupper()
                and not line.startswith(("Level:", "Range:", "Components:", "Casting",
                                         "Duration:", "Area of", "Saving", "Notes:",
                                         "The ", "This ", "A ", "An ", "If ", "When "))):

            # Suche Level: in den naechsten 8 Zeilen
            found_level = False
            school = ""
            for j in range(1, min(9, len(all_lines) - i)):
                check_line = all_lines[i + j][0]
                if SCHOOL_PATTERN.match(check_line):
                    school = check_line
                if check_line.startswith("Level:"):
                    found_level = True
                    break

            if found_level:
                # Sammle Text bis zum naechsten Spell
                spell_text_lines = [line]
                k = i + 1
                while k < len(all_lines):
                    next_line, next_page = all_lines[k]

                    # Naechster Spell? Pruefe ob neuer Name + Level folgt
                    if (next_line and 3 <= len(next_line) <= 60 and next_line[0].isupper()
                            and not next_line.startswith(("Level:", "Range:", "Components:",
                                                           "Casting", "Duration:", "Area of",
                                                           "Saving", "Notes:", "The ", "This ",
                                                           "A ", "An ", "If ", "When "))
                            and k + 8 < len(all_lines)):
                        # Lookahead: hat naechster Block ein Level:?
                        has_next_level = False
                        for m in range(1, min(9, len(all_lines) - k)):
                            if all_lines[k + m][0].startswith("Level:"):
                                has_next_level = True
                                break
                        if has_next_level:
                            break  # Neuer Spell beginnt

                    spell_text_lines.append(next_line)
                    k += 1

                full_text = "\n".join(spell_text_lines)
                spells.append({
                    "name": line,
                    "school": school.strip("()"),
                    "start_page": page,
                    "text": full_text,
                })
                i = k
                continue
        i += 1

    return spells


def parse_spell_stats(text: str) -> dict:
    """Parst Spell-Stat-Felder aus einem Spell-Text-Block."""
    stats = {}
    for line in text.split("\n"):
        line = line.strip()
        for field_name, pattern in SPELL_STAT_LABELS:
            if pattern.match(line):
                value = line.split(":", 1)[1].strip() if ":" in line else ""
                if value:
                    stats[field_name] = value
                break
    return stats


def extract_spells_compendium(pages: list[dict], source: str, code: str,
                              base_tags: list[str]) -> list[dict]:
    """Extrahiert einzelne Spells aus Wizard/Priest Spell Compendium."""
    spell_blocks = find_spell_boundaries(pages)
    spells = []

    for block in spell_blocks:
        name = block["name"]
        # Bereinige Name
        name = re.sub(r"\s+", " ", name).strip()
        # Skip offensichtliche Nicht-Spells
        if len(name) < 3 or any(skip in name.lower() for skip in
            ["about this", "table of", "appendix", "index", "introduction",
             "chapter", "glossary", "credits", "reversed form", "reversible",
             "sphere:", "school:", "note:", "optional"]):
            continue
        # Skip: Name ist nur "Reversible" oder beginnt mit Erklaerungstext
        if name in ("Reversible", "Reversable"):
            continue

        stats = parse_spell_stats(block["text"])
        # Qualitaets-Check: muss mindestens Level haben
        if "level" not in stats:
            continue

        spell_id = slugify(name)
        if not spell_id:
            continue

        spell = {
            "name": name,
            "id": spell_id,
            "source": source,
            "source_page": block["start_page"],
            "school": block.get("school", ""),
            "category": "spell",
            "priority": "core",
            "system_id": "add_2e",
            "schema_version": "1.0.0",
            "tags": list(dict.fromkeys(base_tags + ["spell"])),
        }

        # Stat-Felder uebernehmen
        for field in ["level", "range", "components", "casting_time",
                      "duration", "area_of_effect", "saving_throw"]:
            if field in stats:
                spell[field] = stats[field]

        spell["raw_text"] = block["text"][:6000]
        spells.append(spell)

    return spells


# ---------------------------------------------------------------------------
# Monster-Extraktion (Monstrous Compendium)
# ---------------------------------------------------------------------------

# Regex fuer CLIMATE/TERRAIN Marker (OCR-tolerant: Kyrillische Zeichen, fehlende Zeichen)
CLIMATE_MARKER = re.compile(
    r"CLIMAT|CLIMATE[/\s]*TERRAIN",
    re.IGNORECASE
)

# Stat-Feld-Labels mit OCR-toleranten Patterns
MONSTER_STAT_LABELS = [
    ("climate_terrain",  re.compile(r"CLIMAT.*?TERRAIN|CLIMATETERRAIN", re.IGNORECASE)),
    ("frequency",        re.compile(r"FREQUEN", re.IGNORECASE)),
    ("organization",     re.compile(r"ORGANIZ", re.IGNORECASE)),
    ("activity_cycle",   re.compile(r"ACTIVIT.*?CYCL", re.IGNORECASE)),
    ("diet",             re.compile(r"^DIET", re.IGNORECASE)),
    ("intelligence",     re.compile(r"INTELLIG", re.IGNORECASE)),
    ("treasure_type",    re.compile(r"TREASURE", re.IGNORECASE)),
    ("alignment",        re.compile(r"ALIGNM", re.IGNORECASE)),
    ("number_appearing", re.compile(r"NO\.?\s*APPEAR|APPEARING", re.IGNORECASE)),
    ("ac",               re.compile(r"ARMO.*?CLASS", re.IGNORECASE)),
    ("movement",         re.compile(r"^MOVE", re.IGNORECASE)),
    ("hit_dice",         re.compile(r"HIT\s*DIC", re.IGNORECASE)),
    ("thac0",            re.compile(r"THAC", re.IGNORECASE)),
    ("number_of_attacks",re.compile(r"NO\.?\s*OF\s*ATTACK|ATTACKS", re.IGNORECASE)),
    ("damage",           re.compile(r"DAMAGE", re.IGNORECASE)),
    ("special_attacks",  re.compile(r"SPECIAL\s*ATTACK", re.IGNORECASE)),
    ("special_defenses", re.compile(r"SPECIAL\s*DEFEN", re.IGNORECASE)),
    ("magic_resistance", re.compile(r"MAGI.*?RESIS", re.IGNORECASE)),
    ("size",             re.compile(r"^SIZE", re.IGNORECASE)),
    ("morale",           re.compile(r"^MORAL", re.IGNORECASE)),
    ("xp_value",         re.compile(r"XP\s*VALUE|EXPERIENCE", re.IGNORECASE)),
]


def find_monster_blocks(pages: list[dict]) -> list[dict]:
    """
    Findet Monster-Eintraege ueber CLIMATE/TERRAIN Marker.
    Gibt Liste von {name, start_page, pages_text} zurueck.
    """
    blocks = []

    # Jede Seite einzeln pruefen auf CLIMATE/TERRAIN Marker
    # Ein Monster-Block beginnt wenn CLIMATE/TERRAIN gefunden wird
    monster_pages = []  # (page_num, text, is_start)

    for p in pages:
        text = p["text"]
        if CLIMATE_MARKER.search(text):
            monster_pages.append((p["page"], text, True))
        elif monster_pages and not monster_pages[-1][2]:
            # Continuation page (nach Start, vor naechstem Start)
            monster_pages.append((p["page"], text, False))
        elif monster_pages:
            # Seite zwischen zwei Monstern (Narrative-Fortsetzung)
            monster_pages.append((p["page"], text, False))

    # Gruppiere: jeder CLIMATE/TERRAIN Start beginnt neuen Block
    current_block = None
    for page_num, text, is_start in monster_pages:
        if is_start:
            if current_block:
                blocks.append(current_block)
            # Monster-Name ist Text VOR dem CLIMATE Marker
            match = CLIMATE_MARKER.search(text)
            pre_climate = text[:match.start()] if match else ""
            # Name: letzte nicht-leere Zeilen vor dem Marker
            pre_lines = [l.strip() for l in pre_climate.split("\n") if l.strip()]
            # Filter: Ueberspringe Seiten die nur Tabellen/Index sind
            if not pre_lines:
                monster_name = f"Unknown_Page_{page_num}"
            else:
                # Monster-Name: suche nach echten Monster-Namen
                # Ignoriere kurze OCR-Artefakte, Seitenzahlen, Varianten-Labels
                OCR_GARBAGE = {"JJJ", "M", "I", "II", "III", "IV", "V", "VI",
                               "VII", "VIII", "IX", "X", "i", "ii", "iii",
                               "OO", "OOO", "AAA", "MENU", "—", "--", "`"}
                name_candidates = []
                for line in pre_lines:
                    # Skip: reine Zahlen, Seitenzahlen
                    if re.match(r"^\d+$", line):
                        continue
                    # Skip: sehr kurze Zeilen (< 3 Zeichen) oder bekannte Artefakte
                    if len(line) < 3 or line in OCR_GARBAGE:
                        continue
                    # Skip: Varianten-Header
                    if len(pre_lines) > 2 and line in ("Common", "Giant",
                        "Lesser", "Greater", "Dracolisk", "Major", "Minor"):
                        continue
                    # Skip: Zeilen die wie Narrative aussehen (>50 chars, Kleinbuchstaben-Start)
                    if len(line) > 50 and line[0].islower():
                        continue
                    # Skip: Zeilen mit Satzzeichen-Mustern (Narrative-Fragmente)
                    if len(line) > 40 and (", " in line or ". " in line):
                        continue
                    name_candidates.append(line)
                monster_name = name_candidates[0] if name_candidates else f"Page_{page_num}"

            current_block = {
                "name": monster_name.strip(),
                "start_page": page_num,
                "pages_text": text,
            }
        else:
            if current_block:
                current_block["pages_text"] += "\n\n" + text

    if current_block:
        blocks.append(current_block)

    return blocks


def parse_monster_stats(block_text: str) -> dict:
    """
    Parst Stat-Block-Felder aus einem Monster-Text-Block.
    Gibt Dict mit erkannten Feldern zurueck.
    """
    lines = block_text.split("\n")
    stats = {}
    current_field = None
    narrative_start = -1
    xp_found = False

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue

        # Prüfe ob Zeile ein Stat-Label ist
        matched_field = None
        for field_name, pattern in MONSTER_STAT_LABELS:
            if pattern.search(line):
                matched_field = field_name
                break

        if matched_field:
            current_field = matched_field
            # Wert kann auf gleicher Zeile sein (nach Doppelpunkt)
            colon_pos = line.find(":")
            if colon_pos >= 0:
                value = line[colon_pos + 1:].strip()
                if value:
                    stats[current_field] = value
            if matched_field == "xp_value":
                xp_found = True
            continue

        # Wenn wir in einem Feld sind und der Wert noch fehlt
        if current_field and current_field not in stats:
            stats[current_field] = line
            if current_field == "xp_value":
                xp_found = True
            current_field = None
            continue

        # XP wurde gefunden und keine weiteren Stat-Labels -> Narrative beginnt
        if xp_found and not matched_field:
            # Narrative Text: alles ab hier (XP-Wert-Zeilen ueberspringen)
            if len(line) > 20 and not re.match(r"^\d[\d,\s]*$", line):
                narrative_start = i
                break

    # Narrative zusammenbauen
    narrative = ""
    if narrative_start > 0:
        narrative_lines = [l.strip() for l in lines[narrative_start:] if l.strip()]
        narrative = "\n".join(narrative_lines)

    stats["_narrative"] = narrative
    return stats


def infer_name_from_narrative(text: str) -> Optional[str]:
    """Versucht Monster-Name aus Narrativ-Text zu erraten."""
    narrative_lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 15]
    if not narrative_lines:
        return None

    # Strategie 1: Suche "The X is/are..." Muster in ersten 5 Zeilen
    for line in narrative_lines[:5]:
        m = re.match(
            r"(?:These|The|A|An)\s+(.+?)\s+(?:is|are|was|were|has|have|resemble|look|appear|dwell|live|inhabit|can|exist)",
            line, re.IGNORECASE
        )
        if m:
            name = m.group(1).strip()
            words = name.split()[:4]
            name = " ".join(words)
            name = re.sub(r"[,;:.\(\)].*$", "", name).strip()
            if 2 < len(name) < 50:
                return name.title()

    # Strategie 2: Suche "X are creatures/monsters/beings..." oder "X is a creature..."
    for line in narrative_lines[:5]:
        m = re.match(
            r"([A-Z][a-z]+(?:\s+[a-z]+){0,2})\s+(?:are|is)\s+(?:a\s+)?(?:creature|monster|being|race|species|type|form|kind|beast|animal|undead|fiend|demon|devil|dragon|humanoid|plant|construct|elemental|ooze|aberration|fey|giant|celestial)",
            line
        )
        if m:
            name = m.group(1).strip()
            if 2 < len(name) < 50:
                return name.title()

    # Strategie 3: Erster Satz — suche Eigenname am Anfang (Gross, 1-3 Woerter, vor Verb)
    first = narrative_lines[0]
    m = re.match(r"^([A-Z][a-z]+(?:[,\s]+[A-Z][a-z]+){0,2})\s+(?:are|is|has|have|live|dwell|inhabit|appear|resemble|can)", first)
    if m:
        name = m.group(1).strip().rstrip(",")
        if 2 < len(name) < 50:
            return name.title()

    return None


def extract_monsters(pages: list[dict], source: str, code: str,
                     base_tags: list[str]) -> list[dict]:
    """
    Extrahiert Monster-Eintraege aus Monstrous Compendium PDFs.
    Gibt Liste von Schema-A Monster-Dicts zurueck.
    """
    blocks = find_monster_blocks(pages)
    monsters = []

    # Skip-Filter fuer Nicht-Monster-Seiten
    skip_names = {"alphabetical index", "monster summoning", "temperate encounter",
                  "tropical encounter", "arctic encounter", "dungeon level",
                  "how to use", "calculating experience", "encounter tables",
                  "appendix", "credits", "table of contents", "beyond random",
                  "monster manual", "introduction", "preface", "foreword",
                  "index for monstrous", "about the author", "experience points",
                  "summoning tables"}

    # Stat-Felder die fuer einen echten Monster-Eintrag vorhanden sein muessen
    REQUIRED_STATS = {"ac", "hit_dice"}
    MIN_STAT_COUNT = 5

    for block in blocks:
        name = block["name"]

        # Bereinige Monster-Name
        name = re.sub(r"\s+", " ", name).strip()
        name = re.sub(r"^[\d\s]+", "", name).strip()
        name = re.sub(r"\s*[\|#@\*]+\s*$", "", name).strip()

        stats = parse_monster_stats(block["pages_text"])

        # Qualitaets-Check: genuegend Stat-Felder vorhanden?
        stat_fields = {k for k in stats if not k.startswith("_")}
        if len(stat_fields) < MIN_STAT_COUNT:
            continue
        if not stat_fields & REQUIRED_STATS:
            continue

        # Name-Fallback: aus Narrativ-Text ableiten
        if not name or len(name) < 2 or name.startswith("Unknown_") or name.startswith("Page_"):
            inferred = infer_name_from_narrative(stats.get("_narrative", ""))
            if inferred:
                name = inferred
            else:
                name = f"Unknown_{code}_p{block['start_page']}"

        # Skip: offensichtlich keine Monster-Eintraege
        if any(skip in name.lower() for skip in skip_names):
            continue

        monster_id = slugify(name)
        if not monster_id:
            continue

        monster = {
            "name": name,
            "id": monster_id,
            "source": source,
            "source_page": block["start_page"],
            "category": "monster",
            "priority": "core",
            "system_id": "add_2e",
            "schema_version": "1.0.0",
            "tags": list(dict.fromkeys(base_tags + ["monster", name.lower().split()[0]])),
        }

        # Stat-Felder uebernehmen
        for field in ["climate_terrain", "frequency", "organization", "activity_cycle",
                      "diet", "intelligence", "treasure_type", "alignment",
                      "number_appearing", "ac", "movement", "hit_dice", "thac0",
                      "number_of_attacks", "damage", "special_attacks",
                      "special_defenses", "magic_resistance", "size", "morale",
                      "xp_value"]:
            if field in stats:
                monster[field] = stats[field]

        # Raw Text = ganzer Block (begrenzt auf 10K)
        monster["raw_text"] = block["pages_text"][:10000]

        monsters.append(monster)

    return monsters


def rebuild_monster_index():
    """Rebuild monsters/index.json mit allen vorhandenen Monster-Dateien."""
    monsters_dir = LORE_BASE / "monsters"
    if not monsters_dir.exists():
        return

    entries = []
    for f in sorted(monsters_dir.glob("*.json")):
        if f.name == "index.json":
            continue
        try:
            with open(f, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
            entries.append({
                "id": data.get("id", f.stem),
                "name": data.get("name", f.stem),
                "file": f.name,
                "source": data.get("source", ""),
                "source_page": data.get("source_page", 0),
            })
        except (json.JSONDecodeError, KeyError):
            entries.append({"id": f.stem, "name": f.stem, "file": f.name})

    index = {
        "type": "monster_index",
        "system_id": "add_2e",
        "total": len(entries),
        "entries": entries,
    }
    index_path = monsters_dir / "index.json"
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)
    print(f"  Index aktualisiert: {len(entries)} Monster in {index_path.name}")


# ---------------------------------------------------------------------------
# Generische Chunk-Fabrik
# ---------------------------------------------------------------------------

def make_chapter_chunk(
    chapter: dict,
    source: str,
    tags: list[str],
    category: str,
) -> dict:
    start = chapter["start_page"]
    end = chapter["end_page"]
    pages_str = str(start) if start == end else f"{start}-{end}"
    return {
        "name": chapter["title"],
        "source": source,
        "source_pages": pages_str,
        "category": "chapter",
        "priority": "support",
        "system_id": "add_2e",
        "schema_version": "1.0.0",
        "raw_text": chapter["text"][:12000],  # Max 12K chars
        "tags": list(dict.fromkeys(tags)),
    }


# ---------------------------------------------------------------------------
# JSON-Datei schreiben
# ---------------------------------------------------------------------------

def sanitize_filename(name: str, prefix: str = "") -> str:
    s = slugify(name)
    if prefix:
        s = prefix + "_" + s
    if not s or s == "_":
        s = "unknown"
    return s + ".json"


def write_json(chunk: dict, target_dir: Path, filename: str) -> bool:
    """Schreibt JSON-Chunk; gibt False zurueck wenn Datei schon existiert."""
    target_dir.mkdir(parents=True, exist_ok=True)
    fpath = target_dir / filename
    if fpath.exists():
        return False  # Duplikat
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(chunk, f, ensure_ascii=False, indent=2)
    return True


# ---------------------------------------------------------------------------
# Haupt-Verarbeitungs-Funktion
# ---------------------------------------------------------------------------

def process_pdf(pdf_filename: str, pdf_type: str, target_category: str,
                code: str, base_tags: list[str]) -> dict:
    """
    Verarbeitet eine PDF-Datei und schreibt JSON-Chunks.
    Gibt Statistik-Dict zurueck.
    """
    stats = {
        "pdf": pdf_filename,
        "code": code,
        "chapters_written": 0,
        "kits_written": 0,
        "kits_skipped": 0,
        "chapters_skipped": 0,
        "pages": 0,
        "error": None,
    }

    pdf_path = resolve_pdf_path(pdf_filename, code)
    if not pdf_path.exists():
        stats["error"] = f"PDF nicht gefunden: {pdf_path}"
        print(f"  FEHLER: {pdf_path} nicht gefunden")
        return stats

    # Kurzname des Buches (ohne Verlag-Prefix)
    match = re.search(r"(PHBR\d+|DMGR\d+|MC_\w+|Player.s Option|Tome of Magic|Legends and Lore|PO_\w+|Monstrous Compendium[^.]*)", pdf_filename)
    short_source = match.group(0) if match else code
    # Vollstaendiger Buchtitel
    full_source = pdf_filename.replace(".pdf", "").replace("TSR Inc - AD&D 2nd Edition - ", "")

    print(f"  Lese PDF: {pdf_path.name} ...", end=" ", flush=True)
    try:
        pages = extract_all_pages(pdf_path)
        stats["pages"] = len(pages)
        print(f"{len(pages)} Seiten")
    except Exception as e:
        stats["error"] = str(e)
        print(f"FEHLER: {e}")
        return stats

    full_text = "\n\n".join(p["text"] for p in pages if p["text"])

    # --- Kapitel-Chunks ---
    print(f"  Segmentiere Kapitel ...", end=" ", flush=True)
    chapters = split_into_chapters(pages)
    print(f"{len(chapters)} Kapitel erkannt")

    target_dir = LORE_BASE / target_category
    for ch in chapters:
        title = ch["title"]
        tags = list(base_tags)
        chunk = make_chapter_chunk(ch, full_source, tags, target_category)
        fname = sanitize_filename(code + "_" + title, "chapter")
        written = write_json(chunk, target_dir, fname)
        if written:
            stats["chapters_written"] += 1
        else:
            stats["chapters_skipped"] += 1

    # --- Kit-Extraktion fuer PHBR-Buecher ---
    if pdf_type in ("phbr", "phbr_race"):
        print(f"  Extrahiere Kits ...", end=" ", flush=True)
        kits = extract_kits_from_text(full_text, full_source, base_tags, pages)
        print(f"{len(kits)} Kits gefunden")

        kits_dir = LORE_BASE / "kits"
        for kit in kits:
            kit_name = kit["name"].replace("Kit: ", "")
            fname = sanitize_filename(code + "_" + kit_name, "kit")
            written = write_json(kit, kits_dir, fname)
            if written:
                stats["kits_written"] += 1
            else:
                stats["kits_skipped"] += 1

    # --- Sonder-Handling fuer Spell Compendium ---
    elif pdf_type == "spell_compendium":
        print(f"  Extrahiere Spells ...", end=" ", flush=True)
        spell_list = extract_spells_compendium(pages, full_source, code, base_tags)
        print(f"{len(spell_list)} Spells erkannt")

        spells_dir = LORE_BASE / target_category
        cnt_written = 0
        cnt_skipped = 0
        for sp in spell_list:
            fname = sp["id"] + ".json"
            written = write_json(sp, spells_dir, fname)
            if written:
                cnt_written += 1
            else:
                cnt_skipped += 1
        stats["chapters_written"] = cnt_written
        stats["chapters_skipped"] = cnt_skipped
        print(f"  -> Spells: {cnt_written} neu, {cnt_skipped} uebersprungen")

    # --- Sonder-Handling fuer Sourcebooks (Kapitel-Extraktion) ---
    elif pdf_type == "sourcebook":
        # Keine Kits, nur Kapitel-Chunks
        pass  # Standard-Kapitel oben bereits verarbeitet

    # --- Sonder-Handling fuer Monster ---
    elif pdf_type == "monster":
        print(f"  Extrahiere Monster ...", end=" ", flush=True)
        monsters = extract_monsters(pages, full_source, code, base_tags)
        print(f"{len(monsters)} Monster-Bloecke erkannt")

        monsters_dir = LORE_BASE / "monsters"
        cnt_written = 0
        cnt_skipped = 0
        for m in monsters:
            fname = m["id"] + ".json"
            written = write_json(m, monsters_dir, fname)
            if written:
                cnt_written += 1
            else:
                cnt_skipped += 1
        stats["chapters_written"] = cnt_written
        stats["chapters_skipped"] = cnt_skipped
        print(f"  -> Monster: {cnt_written} neu, {cnt_skipped} uebersprungen")

    # --- Sonder-Handling fuer Psionics ---
    elif pdf_type == "psionics":
        print(f"  Verarbeite Psionics ...", end=" ", flush=True)
        extra = extract_psionics(pages, full_source)
        extra_dir = LORE_BASE / "psionics"
        cnt = 0
        for ch in extra:
            fname = sanitize_filename(code + "_" + ch.get("name", "unknown"), "psionic")
            if write_json(ch, extra_dir, fname):
                cnt += 1
        print(f"{cnt} Psionic-Chunks")

    # --- Sonder-Handling fuer Deities ---
    elif pdf_type == "deities":
        extra = extract_deities(pages, full_source)
        extra_dir = LORE_BASE / "deities"
        for ch in extra:
            fname = sanitize_filename(code + "_" + ch.get("name", "unknown"), "deity")
            write_json(ch, extra_dir, fname)

    return stats


# ---------------------------------------------------------------------------
# Statistik
# ---------------------------------------------------------------------------

def show_stats():
    """Zaehlt JSON-Dateien in allen Zielordnern."""
    print("\n=== STATISTIK data/lore/add_2e/ ===")
    total = 0
    for subdir in sorted(LORE_BASE.iterdir()):
        if subdir.is_dir():
            count = len(list(subdir.glob("*.json")))
            total += count
            print(f"  {subdir.name:25s}: {count:5d} JSON-Dateien")
    print(f"  {'GESAMT':25s}: {total:5d} JSON-Dateien")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_batch_p1(args):
    """Verarbeite alle 21 P1-PDFs."""
    print(f"\n=== P1-BATCH START ({len(P1_PDFS)} PDFs) ===\n")
    all_stats = []
    total_chapters = 0
    total_kits = 0
    errors = []

    for i, (filename, pdf_type, target_cat, code, base_tags) in enumerate(P1_PDFS):
        print(f"[{i+1:02d}/{len(P1_PDFS)}] {code}: {filename[:60]}")
        s = process_pdf(filename, pdf_type, target_cat, code, base_tags)
        all_stats.append(s)
        total_chapters += s["chapters_written"]
        total_kits += s["kits_written"]
        if s["error"]:
            errors.append(f"{code}: {s['error']}")
        print(f"  -> Kapitel: {s['chapters_written']} neu, {s['chapters_skipped']} uebersprungen | "
              f"Kits: {s['kits_written']} neu, {s['kits_skipped']} uebersprungen | "
              f"{s['pages']} Seiten")
        print()

    print("=== P1-BATCH ABGESCHLOSSEN ===")
    print(f"Kapitel-Chunks gesamt: {total_chapters}")
    print(f"Kit-Chunks gesamt:     {total_kits}")
    if errors:
        print(f"\nFEHLER ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")

    show_stats()

    # JSON-Report speichern
    report_path = LORE_BASE / "conversion_p1_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "batch": "p1",
            "total_pdfs": len(P1_PDFS),
            "total_chapters": total_chapters,
            "total_kits": total_kits,
            "errors": errors,
            "per_pdf": all_stats,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nReport gespeichert: {report_path}")


def cmd_batch_p2(args):
    """Verarbeite alle 9 P2-PDFs (Monster Compendiums)."""
    print(f"\n=== P2-BATCH START ({len(P2_PDFS)} Monster Compendiums) ===\n")
    all_stats = []
    total_monsters = 0
    total_skipped = 0
    errors = []

    for i, (filename, pdf_type, target_cat, code, base_tags) in enumerate(P2_PDFS):
        print(f"[{i+1:02d}/{len(P2_PDFS)}] {code}: {filename[:70]}")
        s = process_pdf(filename, pdf_type, target_cat, code, base_tags)
        all_stats.append(s)
        total_monsters += s["chapters_written"]
        total_skipped += s["chapters_skipped"]
        if s["error"]:
            errors.append(f"{code}: {s['error']}")
        print(f"  -> Monster: {s['chapters_written']} neu, {s['chapters_skipped']} dup | "
              f"{s['pages']} Seiten")
        print()

    # Index neu bauen
    print("Aktualisiere Monster-Index ...")
    rebuild_monster_index()

    print("\n=== P2-BATCH ABGESCHLOSSEN ===")
    print(f"Monster gesamt:   {total_monsters} neu")
    print(f"Duplikate:        {total_skipped} uebersprungen")
    if errors:
        print(f"\nFEHLER ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")

    show_stats()

    # JSON-Report speichern
    report_path = LORE_BASE / "conversion_p2_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "batch": "p2",
            "total_pdfs": len(P2_PDFS),
            "total_monsters_new": total_monsters,
            "total_duplicates": total_skipped,
            "errors": errors,
            "per_pdf": all_stats,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nReport gespeichert: {report_path}")


def run_batch(name: str, pdf_list: list, args):
    """Generische Batch-Funktion fuer beliebige PDF-Listen."""
    print(f"\n=== {name} START ({len(pdf_list)} PDFs) ===\n")
    all_stats = []
    total_new = 0
    total_skipped = 0
    errors = []

    for i, (filename, pdf_type, target_cat, code, base_tags) in enumerate(pdf_list):
        print(f"[{i+1:02d}/{len(pdf_list)}] {code}: {filename[:70]}")
        s = process_pdf(filename, pdf_type, target_cat, code, base_tags)
        all_stats.append(s)
        total_new += s["chapters_written"]
        total_skipped += s["chapters_skipped"]
        if s["error"]:
            errors.append(f"{code}: {s['error']}")
        print(f"  -> {s['chapters_written']} neu, {s['chapters_skipped']} dup | "
              f"{s['pages']} Seiten")
        print()

    print(f"=== {name} ABGESCHLOSSEN ===")
    print(f"Chunks gesamt: {total_new} neu, {total_skipped} dup")
    if errors:
        print(f"\nFEHLER ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")

    show_stats()

    # Report speichern
    safe_name = slugify(name)
    report_path = LORE_BASE / f"conversion_{safe_name}_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "batch": name,
            "total_pdfs": len(pdf_list),
            "total_new": total_new,
            "total_skipped": total_skipped,
            "errors": errors,
            "per_pdf": all_stats,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nReport: {report_path}")
    return {"total_new": total_new, "total_skipped": total_skipped, "errors": errors}


def cmd_batch_spells(args):
    """Alle Spell Compendiums (Wizard + Priest)."""
    run_batch("SPELLS", SPELL_PDFS, args)


def cmd_batch_magicitems(args):
    """Encyclopedia Magica + Magic Encyclopedia."""
    run_batch("MAGIC-ITEMS", MAGICITEM_PDFS, args)


def cmd_batch_dmgr(args):
    """DMGR Serie + DM Core Books."""
    run_batch("DMGR", DMGR_PDFS + DM_CORE_PDFS, args)


def cmd_batch_dragonlance(args):
    """Alle Dragonlance PDFs — eigene Welt!"""
    run_batch("DRAGONLANCE", DL_PDFS, args)


def cmd_batch_historical(args):
    """Historical Reference HR1-HR7."""
    run_batch("HISTORICAL", HR_PDFS, args)


def cmd_batch_all(args):
    """Alle verbleibenden Batches in Reihenfolge."""
    batches = [
        ("SPELLS", SPELL_PDFS),
        ("MAGIC-ITEMS", MAGICITEM_PDFS),
        ("DMGR", DMGR_PDFS + DM_CORE_PDFS),
        ("DRAGONLANCE", DL_PDFS),
        ("HISTORICAL", HR_PDFS),
    ]
    grand_total_new = 0
    grand_total_errors = 0
    for name, pdf_list in batches:
        result = run_batch(name, pdf_list, args)
        grand_total_new += result["total_new"]
        grand_total_errors += len(result["errors"])

    # Monster-Index aktualisieren
    rebuild_monster_index()

    print(f"\n{'='*60}")
    print(f"ALLE BATCHES ABGESCHLOSSEN")
    print(f"Neue Chunks gesamt: {grand_total_new}")
    print(f"Fehler gesamt: {grand_total_errors}")
    show_stats()


def cmd_single_pdf(args):
    """Verarbeite ein einzelnes PDF."""
    pdf_filename = args.pdf
    pdf_type = args.type or "phbr"

    # Lookup in allen Listen
    all_lists = P1_PDFS + P2_PDFS + SPELL_PDFS + MAGICITEM_PDFS + DMGR_PDFS + DM_CORE_PDFS + DL_PDFS + HR_PDFS
    entry = None
    for row in all_lists:
        if row[3] in pdf_filename or row[0] in pdf_filename:
            entry = row
            break

    if entry:
        filename, ptype, target_cat, code, base_tags = entry
        if pdf_type:
            ptype = pdf_type
    else:
        # Defaults fuer unbekannte PDFs
        filename = pdf_filename
        ptype = pdf_type
        code = Path(pdf_filename).stem[:10]
        target_cat = "classes"
        base_tags = ["add_2e"]

    s = process_pdf(filename, ptype, target_cat, code, base_tags)
    print(f"\nErgebnis: {s}")
    show_stats()


def main():
    parser = argparse.ArgumentParser(
        description="AD&D 2e PDF → JSON Lore Converter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  py -3 scripts/converter.py --batch p1
  py -3 scripts/converter.py --pdf "PHBR01.pdf" --type phbr
  py -3 scripts/converter.py --stats
        """,
    )
    parser.add_argument("--batch", choices=["p1", "p2", "spells", "magicitems", "dmgr",
                                             "dragonlance", "historical", "all"],
                        help="Batch-Modus")
    parser.add_argument("--pdf", type=str, help="Einzelne PDF-Datei verarbeiten")
    parser.add_argument("--type", type=str,
                        choices=["phbr", "phbr_race", "psionics", "equipment",
                                 "rules_option", "spells", "deities", "monster",
                                 "spell_compendium", "sourcebook"],
                        help="PDF-Typ (nur mit --pdf)")
    parser.add_argument("--stats", action="store_true", help="Statistik anzeigen")

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.batch == "p1":
        cmd_batch_p1(args)
        return

    if args.batch == "p2":
        cmd_batch_p2(args)
        return

    if args.batch == "spells":
        cmd_batch_spells(args)
        return

    if args.batch == "magicitems":
        cmd_batch_magicitems(args)
        return

    if args.batch == "dmgr":
        cmd_batch_dmgr(args)
        return

    if args.batch == "dragonlance":
        cmd_batch_dragonlance(args)
        return

    if args.batch == "historical":
        cmd_batch_historical(args)
        return

    if args.batch == "all":
        cmd_batch_all(args)
        return

    if args.pdf:
        cmd_single_pdf(args)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
