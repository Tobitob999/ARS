"""
scripts/pdf_scanner.py — PDF-Scanner & Verarbeitungs-Queue

Indiziert rekursiv alle .pdf-Dateien im Projektverzeichnis und erstellt
coversion/pdf_queue.json als Verarbeitungs-Queue fuer die Conversion-Pipeline.

Verwendung:
  py -3 scripts/pdf_scanner.py                    # Scan Projektverzeichnis
  py -3 scripts/pdf_scanner.py --dir PATH          # Anderes Verzeichnis
  py -3 scripts/pdf_scanner.py --reset             # Queue zuruecksetzen
  py -3 scripts/pdf_scanner.py --status            # Queue-Status anzeigen
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ARS.pdf_scanner")

# Projekt-Root (zwei Ebenen ueber scripts/)
PROJECT_ROOT = Path(__file__).parent.parent
QUEUE_FILE = PROJECT_ROOT / "coversion" / "pdf_queue.json"

# Heuristische Erkennung des Regelsystems anhand des Dateinamens
SYSTEM_HINTS: dict[str, str] = {
    "add":           "add_2e",
    "adnd":          "add_2e",
    "dungeon":       "add_2e",
    "forgotten":     "add_2e",
    "gurps":         "gurps_4e",
    "mechwarrior":   "mechwarrior_3e",
    "battletech":    "mechwarrior_3e",
    "mech_warrior":  "mechwarrior_3e",
}

# Scan-Verzeichnisse (relativ zu Projekt-Root)
SCAN_DIRS = [
    PROJECT_ROOT,
    Path("G:/Meine Ablage"),
]


def detect_system(filename: str) -> str:
    """Erkennt das Regelsystem heuristisch anhand des Dateinamens."""
    name_lower = filename.lower().replace("-", "_").replace(" ", "_")
    for hint, system in SYSTEM_HINTS.items():
        if hint in name_lower:
            return system
    return "unknown"


def assign_priority(path: Path, system: str) -> int:
    """Berechnet Prioritaet (1=hoch, 5=niedrig). Kernbuecher zuerst."""
    name = path.stem.lower()
    # Core-Buecher haben hoechste Prioritaet
    if any(k in name for k in ("core", "grundregeln", "main", "base", "rulebook")):
        return 1
    # Supplements
    if any(k in name for k in ("supplement", "erweiterung", "companion", "sourcebook")):
        return 3
    # Sonstige
    return 4


def scan_for_pdfs(scan_paths: list[Path]) -> list[dict[str, Any]]:
    """Scannt Verzeichnisse nach PDFs und gibt strukturierte Eintraege zurueck."""
    seen: set[str] = set()
    entries: list[dict[str, Any]] = []
    entry_id = 1

    for scan_path in scan_paths:
        if not scan_path.exists():
            logger.debug("Pfad nicht gefunden, ueberspringe: %s", scan_path)
            continue

        logger.info("Scanne: %s", scan_path)
        for pdf_path in sorted(scan_path.rglob("*.pdf")):
            # Duplikate vermeiden (gleicher absoluter Pfad)
            abs_str = str(pdf_path.resolve())
            if abs_str in seen:
                continue
            seen.add(abs_str)

            try:
                size_bytes = pdf_path.stat().st_size
                size_mb = round(size_bytes / (1024 * 1024), 2)
            except OSError:
                size_mb = 0.0

            system = detect_system(pdf_path.name)
            priority = assign_priority(pdf_path, system)

            entries.append({
                "id": f"pdf_{entry_id:04d}",
                "path": str(pdf_path),
                "filename": pdf_path.name,
                "size_mb": size_mb,
                "status": "pending",
                "priority": priority,
                "detected_system": system,
                "created_at": datetime.now().isoformat(),
                "updated_at": None,
                "error_msg": None,
                "output_ruleset": None,
                "output_lore_dir": None,
                "notes": "",
            })
            entry_id += 1

    # Nach Prioritaet sortieren, dann Dateigroesse (groessere zuerst)
    entries.sort(key=lambda e: (e["priority"], -e["size_mb"]))
    return entries


def load_queue() -> dict[str, Any]:
    """Laedt bestehende Queue oder gibt leere Struktur zurueck."""
    if QUEUE_FILE.exists():
        try:
            with QUEUE_FILE.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, IOError) as exc:
            logger.warning("Queue-Datei fehlerhaft: %s", exc)
    return {"generated_at": None, "total": 0, "entries": []}


def save_queue(queue: dict[str, Any]) -> None:
    """Speichert Queue in data/lore/pdf_queue.json."""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_FILE.open("w", encoding="utf-8") as fh:
        json.dump(queue, fh, ensure_ascii=False, indent=2)
    logger.info("Queue gespeichert: %s (%d Eintraege)", QUEUE_FILE, queue["total"])


def merge_with_existing(existing: dict[str, Any], new_entries: list[dict]) -> dict[str, Any]:
    """
    Fuegt neue PDFs zur bestehenden Queue hinzu, ohne abgeschlossene/laufende
    Eintraege zu ueberschreiben.
    """
    existing_paths = {e["path"]: e for e in existing.get("entries", [])}

    merged: list[dict] = []
    for entry in new_entries:
        if entry["path"] in existing_paths:
            # Bestehenden Eintrag beibehalten (Status/Fortschritt erhalten)
            merged.append(existing_paths[entry["path"]])
        else:
            merged.append(entry)

    return {
        "generated_at": datetime.now().isoformat(),
        "total": len(merged),
        "pending": sum(1 for e in merged if e["status"] == "pending"),
        "in_progress": sum(1 for e in merged if e["status"] == "in_progress"),
        "done": sum(1 for e in merged if e["status"] == "done"),
        "error": sum(1 for e in merged if e["status"] == "error"),
        "entries": merged,
    }


def print_status(queue: dict[str, Any]) -> None:
    """Gibt Queue-Statistik auf stdout aus."""
    entries = queue.get("entries", [])
    total = queue.get("total", len(entries))
    print(f"\n=== PDF-Queue Status ===")
    print(f"Gesamt:       {total}")
    print(f"Pending:      {queue.get('pending', sum(1 for e in entries if e['status'] == 'pending'))}")
    print(f"In Progress:  {queue.get('in_progress', sum(1 for e in entries if e['status'] == 'in_progress'))}")
    print(f"Done:         {queue.get('done', sum(1 for e in entries if e['status'] == 'done'))}")
    print(f"Error:        {queue.get('error', sum(1 for e in entries if e['status'] == 'error'))}")
    print(f"\nQueue-Datei:  {QUEUE_FILE}")

    if entries:
        print(f"\n--- Ausstehende PDFs (Prioritaet 1-5) ---")
        for e in entries:
            if e["status"] == "pending":
                print(f"  [{e['priority']}] {e['filename']:40s} {e['size_mb']:6.1f} MB  [{e['detected_system']}]")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARS PDF-Scanner — erstellt Verarbeitungs-Queue fuer Codex"
    )
    parser.add_argument(
        "--dir", nargs="*", metavar="PATH",
        help="Zusaetzliche Scan-Verzeichnisse",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Queue vollstaendig zuruecksetzen (alle Status auf 'pending')",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Queue-Status anzeigen und beenden",
    )
    args = parser.parse_args()

    # Nur Status anzeigen
    if args.status:
        queue = load_queue()
        print_status(queue)
        return

    # Scan-Pfade bestimmen
    scan_paths = list(SCAN_DIRS)
    if args.dir:
        for d in args.dir:
            p = Path(d)
            if p.exists():
                scan_paths.append(p)
            else:
                logger.warning("Verzeichnis nicht gefunden: %s", d)

    # Reset
    if args.reset:
        existing = load_queue()
        for e in existing.get("entries", []):
            e["status"] = "pending"
            e["updated_at"] = datetime.now().isoformat()
            e["error_msg"] = None
        save_queue(existing)
        print("Queue zurueckgesetzt.")
        print_status(existing)
        return

    # Scan
    logger.info("Starte PDF-Scan...")
    new_entries = scan_for_pdfs(scan_paths)

    if not new_entries:
        logger.warning("Keine PDFs gefunden.")
        return

    existing = load_queue()
    merged_queue = merge_with_existing(existing, new_entries)

    save_queue(merged_queue)
    print_status(merged_queue)
    print(f"\nQueue bereit fuer Codex: {QUEUE_FILE}")


if __name__ == "__main__":
    main()
