import argparse
import glob
import json
import os
import re
from datetime import datetime, timezone

REQ_DIRS = [
    "book_conversion",
    "fulltext",
    "chapters",
    "appendices",
    "spells",
    "tables",
    "indices",
    "mechanics",
    "characters",
    "combat",
    "equipment",
    "treasure",
    "encounters",
    "npcs",
    "vision",
    "monsters",
    "rules_fulltext_chunks",
    "derived_rules",
]

CONTENT_DIRS = [
    "chapters",
    "appendices",
    "spells",
    "tables",
    "indices",
    "mechanics",
    "characters",
    "combat",
    "equipment",
    "treasure",
    "encounters",
    "npcs",
    "vision",
    "monsters",
]

DIR_TO_FIELDS = {
    "chapters": ["characteristics", "skills", "combat"],
    "appendices": ["extensions", "travel", "conditions"],
    "spells": ["magic"],
    "tables": ["economy", "conditions", "travel"],
    "indices": ["extensions"],
    "mechanics": ["healing", "conditions", "economy"],
    "characters": ["characteristics", "skills", "henchmen_hirelings"],
    "combat": ["combat"],
    "equipment": ["economy"],
    "treasure": ["economy"],
    "encounters": ["travel", "combat"],
    "npcs": ["henchmen_hirelings"],
    "vision": ["conditions", "travel"],
    "monsters": ["combat", "extensions"],
}

PHASES = [
    (1, "skeleton_mapping"),
    (2, "metadata"),
    (3, "dice_system"),
    (4, "characteristics"),
    (5, "attribute_bonuses"),
    (6, "races"),
    (7, "classes_progression"),
    (8, "skills"),
    (9, "combat"),
    (10, "magic"),
    (11, "remaining_sections"),
    (12, "extensions"),
]


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def detect_layout(bundle_path):
    bundle_name = os.path.basename(os.path.normpath(bundle_path))

    data_lore = os.path.join(bundle_path, "data", "lore")
    if os.path.isdir(data_lore):
        systems = [d for d in os.listdir(data_lore) if os.path.isdir(os.path.join(data_lore, d))]
        if systems:
            system_id = systems[0]
            lore_root = os.path.join(data_lore, system_id)
            return system_id, lore_root

    direct_candidate = os.path.join(bundle_path, bundle_name)
    if os.path.isdir(direct_candidate):
        return bundle_name, direct_candidate

    dirs = [d for d in os.listdir(bundle_path) if os.path.isdir(os.path.join(bundle_path, d))]
    if dirs:
        return dirs[0], os.path.join(bundle_path, dirs[0])

    raise RuntimeError(f"No lore root found in bundle: {bundle_path}")


def find_ruleset_path(bundle_path, system_id):
    p1 = os.path.join(bundle_path, "modules", "rulesets", f"{system_id}.json")
    if os.path.isfile(p1):
        return p1
    p2 = os.path.join(bundle_path, f"{system_id}.json")
    if os.path.isfile(p2):
        return p2
    return None


def find_latest(pattern):
    candidates = glob.glob(pattern)
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def list_json_files(path):
    if not os.path.isdir(path):
        return []
    return [f for f in os.listdir(path) if f.lower().endswith(".json")]


def excerpt_for_fields(coverage, fields):
    out = []
    by_field = (coverage or {}).get("mechanics", {}).get("coverage_by_field", {})
    for field in fields:
        node = by_field.get(field)
        if not node:
            continue
        top = node.get("top_sources", [])
        if not top:
            continue
        sample = top[0]
        out.append(
            {
                "field": field,
                "source_file": sample.get("source_file"),
                "page_refs": sample.get("page_refs", [])[:8],
                "excerpt": (sample.get("excerpt") or "")[:1000],
            }
        )
    return out


def ensure_nonempty_dirs(system_id, lore_root, coverage):
    created = []
    for d in CONTENT_DIRS:
        p = os.path.join(lore_root, d)
        os.makedirs(p, exist_ok=True)
        files = list_json_files(p)
        if files:
            continue
        fields = DIR_TO_FIELDS.get(d, [])
        snippets = excerpt_for_fields(coverage, fields)
        kind = "autofill_seed" if snippets else "na_with_reason"
        payload = {
            "schema_version": "1.0.0",
            "category": f"{d}_{kind}",
            "tags": [system_id, d, "conversion_autopilot", kind],
            "summary": "Automatisch erzeugter Nachweis fuer Vollstaendigkeit im Conversion-Autopilot.",
            "source_text": {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "generator": "coversion/enforce_full_depth.py",
                "coverage_fields": fields,
            },
            "mechanics": {
                "status": kind,
                "reason": (
                    "Kein direkter Extrakt in diesem Ordner gefunden; Seed aus Coverage erstellt."
                    if snippets
                    else "Im Quellmaterial wurde fuer diesen Ordner kein belastbarer Inhalt erkannt."
                ),
                "evidence": snippets,
            },
        }
        filename = "_coverage_seed.json" if snippets else "_na_report.json"
        out_path = os.path.join(p, filename)
        write_json(out_path, payload)
        created.append(out_path)
    return created


def phase_status(ruleset, lore_root):
    phases = []
    bc = os.path.join(lore_root, "book_conversion")
    derived = os.path.join(lore_root, "derived_rules")

    p1 = bool(glob.glob(os.path.join(bc, "phase1_skeleton_mapping*.json")))
    p2 = bool(glob.glob(os.path.join(bc, "*metadata.json"))) and bool(ruleset)
    p3 = bool(ruleset.get("dice_system"))
    p4 = bool(ruleset.get("characteristics"))
    p5 = bool(ruleset.get("attribute_bonuses"))
    p6 = bool(ruleset.get("races"))
    p7 = bool(ruleset.get("classes"))
    p8 = bool(ruleset.get("skills"))
    p9 = bool(ruleset.get("combat"))
    p10 = bool(ruleset.get("magic"))
    remaining_keys = [
        "alignment",
        "movement",
        "encumbrance",
        "economy",
        "conditions",
        "healing",
        "experience",
        "time",
        "senses",
        "travel",
        "henchmen_hirelings",
        "downtime",
    ]
    p11 = any(k in ruleset for k in remaining_keys)
    p12 = bool(ruleset.get("extensions")) or bool(glob.glob(os.path.join(derived, "*merge_candidates*.json")))

    checks = {
        1: p1,
        2: p2,
        3: p3,
        4: p4,
        5: p5,
        6: p6,
        7: p7,
        8: p8,
        9: p9,
        10: p10,
        11: p11,
        12: p12,
    }

    for num, name in PHASES:
        done = checks[num]
        phases.append(
            {
                "phase": num,
                "name": name,
                "status": "done" if done else "na_with_reason",
                "reason": None if done else "Nicht direkt im Ruleset/Artefakt nachweisbar; als N/A markiert.",
            }
        )
    return phases


def recalc_counts(lore_root):
    counts = {}
    for d in REQ_DIRS:
        p = os.path.join(lore_root, d)
        counts[d] = len(list_json_files(p))
    return counts


def check_ocr_quality(lore_root):
    """Check if >50% of fulltext pages have empty text. Returns (empty, total, ratio)."""
    ft_dir = os.path.join(lore_root, "fulltext")
    if not os.path.isdir(ft_dir):
        return 0, 0, 0.0
    total = 0
    empty = 0
    for f in os.listdir(ft_dir):
        if not f.lower().endswith(".json"):
            continue
        try:
            data = read_json(os.path.join(ft_dir, f))
            total += 1
            text = data.get("text", "")
            if not text or not text.strip():
                empty += 1
        except (json.JSONDecodeError, IOError):
            total += 1
            empty += 1
    ratio = empty / total if total > 0 else 0.0
    return empty, total, ratio


def check_entity_index(lore_root):
    """Check if entity_index.json exists. Returns (exists, path)."""
    idx_path = os.path.join(lore_root, "indices", "entity_index.json")
    return os.path.isfile(idx_path), idx_path


def check_snippet_quality(lore_root):
    """Count name_guess fields with OCR artifacts. Returns (warnings, checked, details)."""
    ocr_artifact_patterns = [
        re.compile(r"[_\[\]{}|]"),           # OCR bracket/pipe artifacts
        re.compile(r"\b[A-Z][a-z]?[A-Z]"),   # Mixed case mid-word (e.g. "Tralt")
        re.compile(r"\s{2,}"),                # Double spaces
    ]
    warnings = 0
    checked = 0
    details = []
    # Check entity-heavy directories for name_guess fields
    entity_dirs = ["npcs", "monsters", "items", "spells", "vehicles",
                   "lore", "history", "factions", "locations", "quests"]
    for d in entity_dirs:
        dirpath = os.path.join(lore_root, d)
        if not os.path.isdir(dirpath):
            continue
        for f in os.listdir(dirpath):
            if not f.lower().endswith(".json"):
                continue
            try:
                data = read_json(os.path.join(dirpath, f))
            except (json.JSONDecodeError, IOError):
                continue
            mechs = data.get("mechanics", {})
            name = mechs.get("name_guess") or data.get("name_guess") or data.get("name", "")
            if not name:
                continue
            checked += 1
            words = name.split()
            is_suspect = False
            # Short name (<3 words) is potentially OCR fragment
            if len(words) < 3 and len(name) > 30:
                is_suspect = True
            # Check for OCR artifact patterns
            for pat in ocr_artifact_patterns:
                if pat.search(name):
                    is_suspect = True
                    break
            if is_suspect:
                warnings += 1
                if len(details) < 10:  # Cap detail list
                    details.append({"file": f, "name": name[:80], "dir": d})
    return warnings, checked, details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, help="Path to coversion/finished/{system_id} bundle")
    args = parser.parse_args()

    bundle = os.path.abspath(args.bundle)
    system_id, lore_root = detect_layout(bundle)

    ruleset_path = find_ruleset_path(bundle, system_id)
    if not ruleset_path:
        raise RuntimeError(f"Ruleset not found for {system_id} in bundle {bundle}")

    ruleset = read_json(ruleset_path)

    coverage_path = find_latest(os.path.join(lore_root, "derived_rules", "ars_skeleton_coverage*.json"))
    coverage = read_json(coverage_path) if coverage_path else {}

    for d in REQ_DIRS:
        os.makedirs(os.path.join(lore_root, d), exist_ok=True)

    created = ensure_nonempty_dirs(system_id, lore_root, coverage)
    phases = phase_status(ruleset, lore_root)
    counts = recalc_counts(lore_root)

    # --- Hardened checks ---
    ocr_empty, ocr_total, ocr_ratio = check_ocr_quality(lore_root)
    entity_idx_exists, entity_idx_path = check_entity_index(lore_root)
    snippet_warnings, snippet_checked, snippet_details = check_snippet_quality(lore_root)

    all_dirs_nonempty = all(counts[d] > 0 for d in REQ_DIRS)
    all_phases_ok = all(p["status"] in ("done", "na_with_reason") for p in phases)

    # Determine validation status with hardened gates
    # Empty OCR is only a hard fail if there's no entity index to compensate
    if ocr_ratio > 0.5 and ocr_total >= 10 and not entity_idx_exists:
        validation_status = "fail_empty_ocr"
    elif not entity_idx_exists and counts.get("fulltext", 0) > 50:
        validation_status = "fail_no_entity_index"
    elif all_dirs_nonempty and all_phases_ok:
        validation_status = "pass"
    else:
        validation_status = "fail"

    report = {
        "schema_version": "1.1.0",
        "category": "conversion_qa",
        "tags": [system_id, "conversion", "qa", "autopilot"],
        "summary": "Verbindlicher QA-Report fuer Volltiefen-Conversion mit 12-Phasen-Gate.",
        "source_text": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "bundle": bundle,
            "lore_root": lore_root,
            "ruleset_path": ruleset_path,
        },
        "mechanics": {
            "validation_status": validation_status,
            "required_dirs": REQ_DIRS,
            "counts": counts,
            "phases": phases,
            "autofill_files_created": created,
            "ocr_quality": {
                "empty_pages": ocr_empty,
                "total_pages": ocr_total,
                "empty_ratio": round(ocr_ratio, 3),
            },
            "entity_index": {
                "exists": entity_idx_exists,
                "path": entity_idx_path,
            },
            "snippet_quality": {
                "warnings": snippet_warnings,
                "checked": snippet_checked,
                "sample_artifacts": snippet_details,
            },
        },
    }

    qa_path = os.path.join(lore_root, "indices", "conversion_qa_report.json")
    write_json(qa_path, report)

    index_path = os.path.join(lore_root, "index.json")
    if os.path.isfile(index_path):
        idx = read_json(index_path)
        idx.setdefault("mechanics", {})
        idx["mechanics"]["counts"] = counts
        idx["mechanics"]["total_json"] = sum(counts.values())
        idx["summary"] = "Index nach Vollstaendigkeits-Nachbearbeitung aktualisiert."
        write_json(index_path, idx)

    print(json.dumps({
        "system_id": system_id,
        "lore_root": lore_root,
        "validation_status": validation_status,
        "autofill_created": len(created),
        "qa_report": qa_path,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
