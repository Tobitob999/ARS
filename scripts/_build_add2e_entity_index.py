"""
Build entity_index.json for AD&D 2E lore directory.
Output: data/lore/add_2e/indices/entity_index.json
"""

import json
import os
from pathlib import Path

BASE = Path("G:/Meine Ablage/ARS/data/lore/add_2e")
OUT_DIR = BASE / "indices"
OUT_FILE = OUT_DIR / "entity_index.json"


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def rel(path):
    """Relative path from data/lore/add_2e root, forward slashes."""
    return str(path.relative_to(BASE)).replace("\\", "/")


# ---------------------------------------------------------------
# SPELLS
# ---------------------------------------------------------------
def build_spells():
    spell_dir = BASE / "spells"
    band_map = {
        "first": 1, "second": 2, "third": 3, "fourth": 4,
        "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
    }

    # Load spell_index for canonical metadata
    si = load_json(BASE / "indices" / "spell_index.json")
    si_records = {}
    if si:
        for rec in si.get("source_text", {}).get("spell_records", []):
            si_records[rec["id"]] = rec

    spells = []
    for f in sorted(spell_dir.glob("*.json")):
        data = load_json(f)
        if data is None:
            continue

        name = data.get("name")
        mech = data.get("mechanics", {})
        card = mech.get("spell_card", {})
        if not name and card.get("name"):
            name = card["name"]
        if not name:
            name = f.stem.replace("_", " ").title()

        school = mech.get("school_or_type") or card.get("school_or_type")
        src = data.get("source_text", {})
        spell_list = src.get("spell_list")
        level_band = src.get("level_band")
        level = band_map.get(str(level_band).lower()) if level_band else None

        pages = src.get("book_pages", [])
        page_ref = f"PHB p.{pages[0]}" if pages else None

        entry = {
            "name": name,
            "spell_list": spell_list,
            "level": level,
            "school": school,
            "source_file": rel(f),
        }
        if page_ref:
            entry["page_ref"] = page_ref

        # Enrich from spell_index
        sid = f.stem
        if sid in si_records:
            rec = si_records[sid]
            if not entry["spell_list"] and rec.get("spell_list"):
                entry["spell_list"] = rec["spell_list"]
            if not entry["level"] and rec.get("level_band"):
                entry["level"] = band_map.get(rec["level_band"])
            if not entry["school"] and rec.get("school_or_type"):
                entry["school"] = rec["school_or_type"]
            qf = rec.get("quality_flags", [])
            if qf:
                entry["quality_flags"] = qf

        spells.append(entry)

    return spells


# ---------------------------------------------------------------
# MONSTERS
# ---------------------------------------------------------------
def build_monsters():
    monster_dir = BASE / "monsters"
    skip = {"index.json", "ARS.code-workspace"}
    monsters = []

    for f in sorted(monster_dir.glob("*.json")):
        if f.name in skip:
            continue
        data = load_json(f)
        if data is None:
            continue

        name = data.get("name", f.stem.replace("_", " ").title())
        # Trim doubled names (OCR artifact): "Beholder Beholder of the" -> use id
        monster_id = data.get("id", f.stem)

        entry = {
            "name": name,
            "id": monster_id,
            "hd": data.get("hit_dice"),
            "ac": data.get("ac"),
            "alignment": data.get("alignment"),
            "frequency": data.get("frequency"),
            "size": data.get("size"),
            "xp_value": data.get("xp_value"),
            "source_file": rel(f),
        }
        page = data.get("source_page")
        if page:
            entry["page_ref"] = f"MC1 p.{page}"
        monsters.append(entry)

    return monsters


# ---------------------------------------------------------------
# ITEMS (mundane weapons/armor)
# ---------------------------------------------------------------
def build_items():
    item_dir = BASE / "items"
    items = []
    for f in sorted(item_dir.glob("*.json")):
        data = load_json(f)
        if data is None:
            continue
        item_id = data.get("id", f.stem)
        name = item_id.replace("_", " ").title()
        entry = {
            "name": name,
            "id": item_id,
            "item_type": data.get("item_type", "weapon"),
            "damage_sm": data.get("damage_small_medium"),
            "damage_lg": data.get("damage_large"),
            "weight_lbs": data.get("weight"),
            "speed_factor": data.get("speed_factor"),
            "source_file": rel(f),
        }
        items.append(entry)
    return items


# ---------------------------------------------------------------
# LOOT / MAGIC ITEMS
# ---------------------------------------------------------------
def build_loot():
    loot_dir = BASE / "loot"
    loot = []
    for f in sorted(loot_dir.glob("*.json")):
        data = load_json(f)
        if data is None:
            continue
        item_id = data.get("id", f.stem)
        name = item_id.replace("_", " ").title()
        effect = data.get("effect_description", "")
        entry = {
            "name": name,
            "id": item_id,
            "magical": data.get("magical", False),
            "value_gp": data.get("value_gp"),
            "description": effect[:120] if effect else None,
            "source_file": rel(f),
        }
        loot.append(entry)
    return loot


# ---------------------------------------------------------------
# CLASSES
# ---------------------------------------------------------------
def build_classes():
    cb = load_json(BASE / "characters" / "class_blueprints.json")
    classes = []
    if not cb:
        return classes
    mech = cb.get("mechanics", {})
    for group_name, group_data in mech.get("class_groups", {}).items():
        hit_die = group_data.get("hit_die")
        for cls_name, cls_data in group_data.get("classes", {}).items():
            entry = {
                "name": cls_name.title(),
                "group": group_name,
                "hit_die": hit_die,
                "requirements": cls_data.get("requirements", {}),
                "prime_requisites": cls_data.get("prime_requisites", []),
                "alignment": cls_data.get("alignment", "any"),
                "special": cls_data.get("special", []),
                "source_file": "characters/class_blueprints.json",
            }
            classes.append(entry)
    return classes


# ---------------------------------------------------------------
# RACES (extracted from PHB chapter 2)
# ---------------------------------------------------------------
def build_races():
    src = "chapters/chapter_02_player_character_races.json"
    races = [
        {
            "name": "Human",
            "ability_adj": {},
            "infravision_ft": 0,
            "available_classes": ["any"],
            "special": ["any class", "unlimited level advancement"],
            "source_file": src,
        },
        {
            "name": "Dwarf",
            "ability_adj": {"CON": 1, "CHA": -1},
            "infravision_ft": 60,
            "available_classes": ["cleric", "fighter", "thief", "fighter/cleric", "fighter/thief"],
            "special": [
                "constitution saving throw bonus vs. magic/poison",
                "detect grade/slope, tunnels, stonework traps underground",
                "+1 to hit orcs/half-orcs/goblins/hobgoblins",
                "-4 to ogre/giant attack rolls against dwarves",
                "20% magic item malfunction chance",
            ],
            "source_file": src,
        },
        {
            "name": "Elf",
            "ability_adj": {"DEX": 1, "CON": -1},
            "infravision_ft": 60,
            "available_classes": ["cleric", "fighter", "mage", "thief", "ranger",
                                  "fighter/mage", "fighter/thief", "fighter/mage/thief", "mage/thief"],
            "special": [
                "90% resistance to sleep and charm spells",
                "+1 attack with bows (non-crossbow) and long/short swords",
                "secret door detection (1-in-6 passive, 1-in-3 active search)",
                "surprise bonus in non-metal armor",
            ],
            "source_file": src,
        },
        {
            "name": "Gnome",
            "ability_adj": {"INT": 1, "WIS": -1},
            "infravision_ft": 60,
            "available_classes": ["fighter", "thief", "cleric", "illusionist",
                                  "fighter/thief", "illusionist/thief"],
            "special": [
                "constitution saving throw bonus vs. magic",
                "detect grade/slope, unsafe walls/ceilings, depth, direction underground",
                "+1 to hit kobolds and goblins",
                "-4 to gnoll/bugbear/ogre/giant attack rolls against gnomes",
                "20% magic item malfunction (excluding illusionist items)",
            ],
            "source_file": src,
        },
        {
            "name": "Half-Elf",
            "ability_adj": {},
            "infravision_ft": 60,
            "available_classes": ["cleric", "druid", "fighter", "ranger", "mage",
                                  "specialist wizard", "thief", "bard"],
            "special": [
                "30% resistance to sleep and charm spells",
                "secret door detection (1-in-6 passive, 1-in-3 active)",
                "broad multi-class options",
            ],
            "source_file": src,
        },
        {
            "name": "Halfling",
            "ability_adj": {"STR": -1, "DEX": 1},
            "infravision_ft": 30,
            "available_classes": ["cleric", "fighter", "thief", "fighter/thief"],
            "special": [
                "constitution saving throw bonus vs. magic and poison",
                "+1 attack with slings and thrown weapons",
                "surprise bonus in non-metal armor",
                "Stout subtype: detect grade and direction underground",
            ],
            "source_file": src,
        },
    ]
    return races


# ---------------------------------------------------------------
# ENCOUNTERS (dungeon set-pieces and traps)
# ---------------------------------------------------------------
def build_encounters():
    encounter_dir = BASE / "encounters"
    skip = {"encounter_system.json"}
    encounters = []
    for f in sorted(encounter_dir.glob("*.json")):
        if f.name in skip:
            continue
        data = load_json(f)
        if data is None:
            continue
        name = (data.get("name") or f.stem.replace("_", " ").title())
        etype = data.get("type") or data.get("category") or "encounter"
        entry = {
            "name": name,
            "id": f.stem,
            "type": etype,
            "source_file": rel(f),
        }
        desc = (data.get("description") or data.get("summary")
                or data.get("situation") or data.get("setup") or "")
        if desc:
            entry["description"] = str(desc)[:120]
        encounters.append(entry)
    return encounters


# ---------------------------------------------------------------
# RULES SUBSYSTEMS
# ---------------------------------------------------------------
def build_subsystems():
    subsystems = []
    sources = list((BASE / "mechanics").glob("*.json")) + [
        BASE / "npcs" / "npc_relations_system.json",
        BASE / "encounters" / "encounter_system.json",
        BASE / "vision" / "vision_light_system.json",
        BASE / "treasure" / "treasure_system.json",
    ]
    for f in sorted(sources):
        data = load_json(f)
        if data is None:
            continue
        name = data.get("name") or f.stem.replace("_", " ").title()
        summary = data.get("summary", "") or ""
        entry = {
            "name": name,
            "id": f.stem,
            "category": data.get("category", "rules_subsystem"),
            "summary": summary[:150],
            "source_file": rel(f),
        }
        subsystems.append(entry)
    return subsystems


# ---------------------------------------------------------------
# TABLES
# ---------------------------------------------------------------
def build_tables():
    table_dir = BASE / "tables"
    # Try to get table names from index
    phb_idx = load_json(table_dir / "phb_table_index.json")
    table_names = {}
    if phb_idx:
        tlist = phb_idx.get("tables", [])
        if isinstance(tlist, list):
            for t in tlist:
                tid = t.get("id") or t.get("table_id", "")
                tname = t.get("name") or t.get("title", "")
                if tid:
                    table_names[tid] = tname
        elif isinstance(tlist, dict):
            for tid, tdata in tlist.items():
                if isinstance(tdata, dict):
                    table_names[tid] = tdata.get("name") or tdata.get("title", "")
                else:
                    table_names[tid] = str(tdata)

    tables = []
    for f in sorted(table_dir.glob("table_*.json")):
        data = load_json(f)
        if data is None:
            continue
        tname = (table_names.get(f.stem)
                 or (data.get("name") if data else None)
                 or f.stem.replace("_", " ").title())
        entry = {
            "name": tname,
            "id": f.stem,
            "source_file": rel(f),
        }
        tables.append(entry)
    return tables


# ---------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------
def main():
    print("Building AD&D 2E entity index...")

    spells = build_spells()
    monsters = build_monsters()
    items = build_items()
    loot = build_loot()
    classes = build_classes()
    races = build_races()
    encounters = build_encounters()
    subsystems = build_subsystems()
    tables = build_tables()

    total = (len(spells) + len(monsters) + len(items) + len(loot)
             + len(classes) + len(races) + len(encounters) + len(subsystems) + len(tables))

    index = {
        "meta": {
            "system": "add_2e",
            "generated": "2026-03-02",
            "schema_version": "1.0.0",
            "description": "Entity index for AD&D 2nd Edition lore. Auto-generated by scripts/_build_add2e_entity_index.py.",
            "total_entities": total,
            "counts_by_category": {
                "spells": len(spells),
                "monsters": len(monsters),
                "items_mundane": len(items),
                "loot_magic_items": len(loot),
                "classes": len(classes),
                "races": len(races),
                "encounters": len(encounters),
                "rules_subsystems": len(subsystems),
                "tables": len(tables),
            },
        },
        "entities": {
            "spells": spells,
            "monsters": monsters,
            "items_mundane": items,
            "loot_magic_items": loot,
            "classes": classes,
            "races": races,
            "encounters": encounters,
            "rules_subsystems": subsystems,
            "tables": tables,
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"Written: {OUT_FILE}")
    print(f"Total entities: {total}")
    for k, v in index["meta"]["counts_by_category"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
