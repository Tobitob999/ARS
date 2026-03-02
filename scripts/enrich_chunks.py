#!/usr/bin/env python3
"""
enrich_chunks.py — Auto-tag existing rules_fulltext_chunks with topic/keywords.

Scans data/lore/*/rules_fulltext_chunks/*.json and enriches chunks that lack
the new metadata fields (topic, keywords) required by the budget injection system.

Usage:
    py -3 scripts/enrich_chunks.py --dry-run     # Preview changes
    py -3 scripts/enrich_chunks.py                # Apply changes
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Topic detection — maps chapter title / source keywords to topic categories
# ---------------------------------------------------------------------------

_TOPIC_PATTERNS: list[tuple[str, list[str]]] = [
    ("combat.initiative", ["initiative", "ueberraschung", "surprise", "reihenfolge"]),
    ("combat.attack", ["angriff", "attack", "thac0", "treffer", "to hit"]),
    ("combat.defense", ["ruestung", "armor", "ac ", "ruest", "defense", "verteidigung"]),
    ("combat.damage", ["schaden", "damage", "verwundung", "wound", "injury"]),
    ("combat", ["kampf", "combat", "fighting", "melee", "missile", "waffe", "weapon"]),
    ("magic.spells", ["zauber", "spell", "cantrip", "beschwoe", "incantation"]),
    ("magic.ritual", ["ritual", "zeremonie", "ceremony"]),
    ("magic", ["magie", "magic", "arcane", "wizard", "mage", "sorcerer", "priester"]),
    ("healing", ["heilung", "healing", "regenerat", "first aid", "erste hilfe", "recovery"]),
    ("death", ["tod", "death", "dying", "sterben", "bewusstlos", "unconscious", "0 hp"]),
    ("sanity", ["san", "sanity", "wahnsinn", "insanity", "madness", "stabilitaet"]),
    ("saving_throws", ["rettungswurf", "saving throw", "save vs", "rettung"]),
    ("skills.social", ["social", "sozial", "charisma", "ueberzeug", "persuasion"]),
    ("skills.physical", ["klettern", "climb", "schwimm", "swim", "athletics"]),
    ("skills", ["fertigkeit", "skill", "proficiency", "talent", "ability check"]),
    ("classes", ["klasse", "class", "krieger", "fighter", "magier", "thief", "dieb", "kleriker", "cleric", "ranger", "paladin", "barde", "bard", "druide", "druid"]),
    ("races", ["rasse", "race", "elf", "zwerg", "dwarf", "halbling", "halfling", "gnome", "mensch", "human"]),
    ("advancement", ["erfahrung", "experience", "xp", "stufe", "level", "aufstieg", "advancement"]),
    ("equipment", ["ausruest", "equipment", "gegenstand", "item", "rucksack", "inventory"]),
    ("economy", ["gold", "muenze", "coin", "handel", "trade", "kaufen", "buy", "preis", "price"]),
    ("movement", ["bewegung", "movement", "geschwindigkeit", "speed", "reise", "travel", "marsch"]),
    ("conditions", ["zustand", "condition", "vergiftet", "poison", "gelae", "paralyz", "blind"]),
    # Paranoia-specific
    ("treason", ["verrat", "treason", "treasonous", "traitor"]),
    ("clones", ["klon", "clone", "replacement", "backup"]),
    ("clearance", ["clearance", "sicherheitsstufe", "infrared", "ultraviolet"]),
    ("service_groups", ["service group", "tech services", "intsec", "hpd", "armed forces"]),
    ("secret_societies", ["secret societ", "geheimgesellschaft", "illuminati", "sierra club"]),
    ("mutations", ["mutation", "mutant", "mutanten"]),
    # Shadowrun-specific
    ("matrix", ["matrix", "decker", "hacker", "host", "ic ", "cyberdeck"]),
    ("cyberware", ["cyberware", "bioware", "essenz", "essence", "augment", "implant"]),
    ("edge", ["edge", "glueck", "luck"]),
    ("rigger", ["rigger", "drohne", "drone", "fernsteuer"]),
    ("astral", ["astral", "geist", "spirit", "astralpro", "astraler"]),
]

# Stopwords — filtered out of keyword extraction
_STOPWORDS = {
    "der", "die", "das", "ein", "eine", "und", "oder", "ist", "sind", "wird",
    "werden", "hat", "haben", "kann", "koennen", "muss", "muessen", "nicht",
    "auch", "aber", "wenn", "dass", "fuer", "mit", "von", "auf", "aus", "bei",
    "nach", "ueber", "unter", "vor", "zur", "zum", "des", "dem", "den",
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
    "has", "have", "can", "may", "will", "not", "but", "its", "all", "any",
    "each", "per", "one", "two", "his", "her", "you", "your", "than",
    "page", "chapter", "section", "see", "table", "note", "seite", "kapitel",
    "regel", "rule", "rules", "chunk",
}


def detect_topic(title: str, raw_text: str) -> str:
    """Detect topic from title and first ~500 chars of raw_text."""
    combined = (title + " " + raw_text[:500]).lower()
    for topic, patterns in _TOPIC_PATTERNS:
        for p in patterns:
            if p in combined:
                return topic
    return "general"


def extract_keywords(raw_text: str, max_kw: int = 8) -> list[str]:
    """Extract top keywords from raw_text."""
    words = re.findall(r"[a-zäöüß]{4,}", raw_text.lower())
    # Normalize umlauts for matching
    normalized = []
    for w in words:
        n = w.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        normalized.append(n)

    counts = Counter(w for w in normalized if w not in _STOPWORDS)
    # Take most common, deduplicate short/long forms
    top = []
    seen: set[str] = set()
    for word, _ in counts.most_common(max_kw * 3):
        # Skip if a prefix of an already-seen word
        if any(word.startswith(s) or s.startswith(word) for s in seen):
            continue
        seen.add(word)
        top.append(word)
        if len(top) >= max_kw:
            break
    return top


def enrich_file(fp: Path, dry_run: bool) -> tuple[bool, str]:
    """Enrich a single chunk file. Returns (changed, message)."""
    try:
        with fp.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"SKIP (bad JSON): {exc}"

    mechanics = data.get("mechanics", {})
    raw_text = mechanics.get("raw_text", "")
    if not raw_text:
        return False, "SKIP (no raw_text)"

    changed = False
    summary = data.get("summary", "")

    # Topic
    if "topic" not in mechanics:
        mechanics["topic"] = detect_topic(summary, raw_text)
        changed = True

    # Keywords
    if "keywords" not in mechanics:
        mechanics["keywords"] = extract_keywords(raw_text)
        changed = True

    # injection_priority — keep existing, normalize values
    prio = mechanics.get("injection_priority", "support")
    valid = ("permanent", "core", "support", "flavor")
    if prio not in valid:
        mechanics["injection_priority"] = "support"
        changed = True

    if not changed:
        return False, "OK (already enriched)"

    data["mechanics"] = mechanics

    if dry_run:
        return True, (
            f"WOULD SET topic={mechanics.get('topic')}, "
            f"keywords={mechanics.get('keywords', [])[:3]}..."
        )

    with fp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return True, f"ENRICHED topic={mechanics['topic']}, {len(mechanics.get('keywords', []))} kw"


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich rules_fulltext_chunks with topic/keywords")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--path", type=str, default=None,
                        help="Specific lore dir (default: data/lore/*/rules_fulltext_chunks/)")
    args = parser.parse_args()

    base = Path(__file__).parent.parent / "data" / "lore"
    if args.path:
        dirs = [Path(args.path)]
    else:
        dirs = sorted(base.glob("*/rules_fulltext_chunks"))

    if not dirs:
        print(f"No rules_fulltext_chunks dirs found under {base}")
        sys.exit(1)

    total = 0
    enriched = 0
    for d in dirs:
        print(f"\n{'='*60}")
        print(f"Processing: {d}")
        print(f"{'='*60}")
        for fp in sorted(d.glob("*.json")):
            changed, msg = enrich_file(fp, args.dry_run)
            total += 1
            if changed:
                enriched += 1
                print(f"  {fp.name}: {msg}")

    mode = "DRY RUN" if args.dry_run else "DONE"
    print(f"\n{mode}: {enriched}/{total} files enriched.")


if __name__ == "__main__":
    main()
