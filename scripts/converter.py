#!/usr/bin/env python3
"""
converter.py — AD&D 2e PDF → JSON Lore Converter
Extrahiert Kapitel und Kits aus P1-PDFs und schreibt JSON-Chunks nach data/lore/add_2e/

Usage:
    py -3 scripts/converter.py --batch p1
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
PDF_DIR = BASE_DIR  # PDFs liegen im ADD2e/ Wurzelverzeichnis
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
# OCR-Varianten: bevorzuge _text.pdf falls vorhanden
# ---------------------------------------------------------------------------
TEXT_VARIANT_PDFS = {
    "PHBR10", "PHBR12", "DMGR3"
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
    match = re.search(r"(PHBR\d+|DMGR\d+|Player.s Option|Tome of Magic|Legends and Lore|PO_\w+)", pdf_filename)
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


def cmd_single_pdf(args):
    """Verarbeite ein einzelnes PDF."""
    pdf_filename = args.pdf
    pdf_type = args.type or "phbr"

    # Lookup in P1-Liste
    entry = None
    for row in P1_PDFS:
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
    parser.add_argument("--batch", choices=["p1"], help="Batch-Modus: p1 = alle 21 P1-PDFs")
    parser.add_argument("--pdf", type=str, help="Einzelne PDF-Datei verarbeiten")
    parser.add_argument("--type", type=str,
                        choices=["phbr", "phbr_race", "psionics", "equipment",
                                 "rules_option", "spells", "deities"],
                        help="PDF-Typ (nur mit --pdf)")
    parser.add_argument("--stats", action="store_true", help="Statistik anzeigen")

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.batch == "p1":
        cmd_batch_p1(args)
        return

    if args.pdf:
        cmd_single_pdf(args)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
