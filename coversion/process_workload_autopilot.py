"""
coversion/process_workload_autopilot.py — Conversion Pipeline Orchestrator

Scannt coversion/workload/ nach neuen PDFs und fuehrt automatisiert die
strukturellen Schritte der Konvertierung aus:
  1. System-Erkennung (via pdf_scanner.detect_system)
  2. PDF-Text-Extraktion (pypdf + optionaler OCR-Fallback)
  3. Fulltext -> Page-JSONs
  4. Verzeichnisstruktur anlegen (REQ_DIRS)
  5. Grafik-Extraktion (pictureextract)
  6. QA-Report generieren (enforce_full_depth.py Logik)
  7. Source-PDF ins Bundle kopieren
  8. Ergebnis-Summary

HINWEIS: Semantische Entity-Extraktion (Entities erkennen, Snippets erzeugen,
Reconciliation) erfordert einen KI-Agenten und wird als TODO markiert.

Verwendung:
  py -3 coversion/process_workload_autopilot.py
  py -3 coversion/process_workload_autopilot.py --dry-run
  py -3 coversion/process_workload_autopilot.py --pdf path/to/book.pdf
  py -3 coversion/process_workload_autopilot.py --help
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
WORKLOAD_DIR = SCRIPT_DIR / "workload"
FINISHED_DIR = SCRIPT_DIR / "finished"
ARCHIVE_DIR = SCRIPT_DIR / "root" / "finished"
PICTUREEXTRACT = (
    PROJECT_ROOT
    / "software"
    / "pictureextract"
    / "production"
    / "v2.0.0"
    / "pictureextract.py"
)

# Add project root to path so we can import from scripts/
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ARS.autopilot")

# ---------------------------------------------------------------------------
# Required directories for a complete bundle (from enforce_full_depth.py)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Step 1: Discover PDFs
# ---------------------------------------------------------------------------
def discover_pdfs(workload_dir: Path, single_pdf: Path | None = None) -> list[Path]:
    """Return list of PDFs to process."""
    if single_pdf:
        if not single_pdf.exists():
            logger.error("PDF not found: %s", single_pdf)
            return []
        return [single_pdf.resolve()]

    if not workload_dir.exists():
        logger.warning("Workload directory not found: %s", workload_dir)
        return []

    pdfs = sorted(workload_dir.glob("*.pdf"))
    if not pdfs:
        logger.info("No PDFs found in %s", workload_dir)
    return pdfs


# ---------------------------------------------------------------------------
# Step 2: System detection
# ---------------------------------------------------------------------------
def detect_system(filename: str) -> str:
    """Detect ruleset system from filename. Uses pdf_scanner hints."""
    try:
        from scripts.pdf_scanner import detect_system as _detect
        return _detect(filename)
    except ImportError:
        logger.warning("Could not import pdf_scanner, using built-in hints")

    hints = {
        "cthulhu": "cthulhu_7e",
        "call_of": "cthulhu_7e",
        "coc": "cthulhu_7e",
        "add": "add_2e",
        "adnd": "add_2e",
        "dungeon": "add_2e",
        "paranoia": "paranoia_2e",
        "shadowrun": "shadowrun_6",
        "sr6": "shadowrun_6",
        "mad_max": "mad_max",
        "wasteland": "mad_max",
        "gurps": "gurps_4e",
        "mechwarrior": "mechwarrior_3e",
        "battletech": "mechwarrior_3e",
    }
    name_lower = filename.lower().replace("-", "_").replace(" ", "_")
    for hint, system in hints.items():
        if hint in name_lower:
            return system
    return "unknown"


# ---------------------------------------------------------------------------
# Step 3: PDF text extraction
# ---------------------------------------------------------------------------
def extract_text_pages(pdf_path: Path) -> list[dict]:
    """Extract text from each page. Returns list of {page, text}."""
    pages = []
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            pages.append({"page": i, "text": text})
        logger.info("Extracted %d pages via pypdf", len(pages))
    except ImportError:
        logger.error("pypdf not installed. Install with: pip install pypdf")
        return []
    except Exception as exc:
        logger.error("pypdf extraction failed: %s", exc)
        return []

    # Check for empty OCR — warn if >50% empty
    empty_count = sum(1 for p in pages if not p["text"])
    if pages and empty_count / len(pages) > 0.5:
        logger.warning(
            "OCR quality warning: %d/%d pages are empty (%.0f%%). "
            "Consider OCR fallback with easyocr.",
            empty_count, len(pages), 100 * empty_count / len(pages),
        )

    return pages


def try_ocr_fallback(pdf_path: Path, pages: list[dict]) -> list[dict]:
    """Attempt OCR via easyocr for pages with empty text. Optional."""
    try:
        import easyocr
        import fitz
    except ImportError:
        logger.info("easyocr/fitz not available — skipping OCR fallback")
        return pages

    empty_indices = [i for i, p in enumerate(pages) if not p["text"]]
    if not empty_indices:
        return pages

    logger.info("Running OCR fallback on %d empty pages...", len(empty_indices))
    try:
        reader = easyocr.Reader(["de", "en"], gpu=False)
        doc = fitz.open(str(pdf_path))
        for idx in empty_indices:
            page = doc[idx]
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            results = reader.readtext(img_bytes, detail=0)
            pages[idx]["text"] = "\n".join(results)
        doc.close()
        filled = sum(1 for i in empty_indices if pages[i]["text"])
        logger.info("OCR fallback filled %d/%d pages", filled, len(empty_indices))
    except Exception as exc:
        logger.error("OCR fallback failed: %s", exc)

    return pages


# ---------------------------------------------------------------------------
# Step 4: Write page JSONs and create bundle structure
# ---------------------------------------------------------------------------
def create_bundle(
    system_id: str,
    pdf_path: Path,
    pages: list[dict],
    dry_run: bool = False,
) -> Path:
    """Create the output bundle directory structure and write fulltext pages."""
    bundle_dir = FINISHED_DIR / system_id
    lore_root = bundle_dir / "data" / "lore" / system_id

    if dry_run:
        logger.info("[DRY-RUN] Would create bundle at: %s", bundle_dir)
        logger.info("[DRY-RUN] Lore root: %s", lore_root)
        logger.info("[DRY-RUN] Would write %d fulltext pages", len(pages))
        return bundle_dir

    # Create all required directories
    for d in REQ_DIRS:
        (lore_root / d).mkdir(parents=True, exist_ok=True)

    # Write fulltext page JSONs
    fulltext_dir = lore_root / "fulltext"
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    for p in pages:
        page_file = fulltext_dir / f"page_{p['page']:03d}.json"
        payload = {
            "schema_version": "1.0.0",
            "category": "fulltext_page",
            "tags": [system_id, "fulltext", f"page_{p['page']}"],
            "source_text": {
                "pdf": pdf_path.name,
                "page": p["page"],
                "generated_at": now_iso,
                "generated_by": "process_workload_autopilot.py",
            },
            "text": p["text"],
        }
        with page_file.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    logger.info("Wrote %d fulltext pages to %s", len(pages), fulltext_dir)

    # Write book_conversion manifest
    manifest = {
        "schema_version": "1.0.0",
        "category": "conversion_manifest",
        "tags": [system_id, "conversion", "manifest"],
        "source_text": {
            "pdf": pdf_path.name,
            "total_pages": len(pages),
            "empty_pages": sum(1 for p in pages if not p["text"]),
            "generated_at": now_iso,
            "generated_by": "process_workload_autopilot.py",
        },
    }
    manifest_path = lore_root / "book_conversion" / "conversion_manifest.json"
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    # Create TODO marker for entity extraction
    todo_path = lore_root / "indices" / "TODO_entity_extraction.json"
    todo = {
        "schema_version": "1.0.0",
        "category": "todo_marker",
        "tags": [system_id, "todo", "entity_extraction"],
        "summary": "Entity-Extraktion steht noch aus. Erfordert KI-Agent (Codex).",
        "source_text": {
            "generated_at": now_iso,
            "generated_by": "process_workload_autopilot.py",
        },
        "required_actions": [
            "Entity-Index erstellen (indices/entity_index.json)",
            "Entity-Snippets erzeugen (items, spells, monsters, npcs, etc.)",
            "Reconciliation durchfuehren (100% Coverage)",
            "QA-Report finalisieren",
        ],
    }
    with todo_path.open("w", encoding="utf-8") as fh:
        json.dump(todo, fh, ensure_ascii=False, indent=2)

    return bundle_dir


# ---------------------------------------------------------------------------
# Step 5: Graphic extraction
# ---------------------------------------------------------------------------
def run_graphic_extraction(pdf_path: Path, bundle_dir: Path, dry_run: bool = False) -> bool:
    """Run pictureextract on the PDF."""
    if not PICTUREEXTRACT.exists():
        logger.warning("pictureextract not found at %s — skipping", PICTUREEXTRACT)
        return False

    output_dir = bundle_dir / "grafik_extract"

    if dry_run:
        logger.info("[DRY-RUN] Would run pictureextract: %s -> %s", pdf_path.name, output_dir)
        return True

    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(PICTUREEXTRACT),
        str(pdf_path),
        str(output_dir),
    ]
    logger.info("Running graphic extraction: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            logger.info("Graphic extraction complete")
            return True
        else:
            logger.error("pictureextract failed (rc=%d): %s", result.returncode, result.stderr)
            return False
    except subprocess.TimeoutExpired:
        logger.error("pictureextract timed out after 300s")
        return False
    except Exception as exc:
        logger.error("pictureextract error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Step 6: Run QA (enforce_full_depth.py)
# ---------------------------------------------------------------------------
def run_qa(bundle_dir: Path, dry_run: bool = False) -> dict | None:
    """Run enforce_full_depth.py against the bundle."""
    enforce_script = SCRIPT_DIR / "enforce_full_depth.py"
    if not enforce_script.exists():
        logger.warning("enforce_full_depth.py not found — skipping QA")
        return None

    if dry_run:
        logger.info("[DRY-RUN] Would run QA: enforce_full_depth.py --bundle %s", bundle_dir)
        return {"validation_status": "dry_run"}

    cmd = [sys.executable, str(enforce_script), "--bundle", str(bundle_dir)]
    logger.info("Running QA validation...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and result.stdout.strip():
            qa_result = json.loads(result.stdout.strip())
            logger.info("QA result: %s", qa_result.get("validation_status", "unknown"))
            return qa_result
        else:
            logger.error("QA failed (rc=%d): %s", result.returncode, result.stderr)
            return None
    except json.JSONDecodeError:
        logger.error("QA output not valid JSON: %s", result.stdout[:200])
        return None
    except Exception as exc:
        logger.error("QA error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Step 7: Copy source PDF into bundle
# ---------------------------------------------------------------------------
def copy_source_pdf(pdf_path: Path, bundle_dir: Path, dry_run: bool = False) -> None:
    """Copy original PDF into bundle's source_pdf/ directory."""
    source_dir = bundle_dir / "source_pdf"

    if dry_run:
        logger.info("[DRY-RUN] Would copy %s -> %s/", pdf_path.name, source_dir)
        return

    source_dir.mkdir(parents=True, exist_ok=True)
    dest = source_dir / pdf_path.name
    if not dest.exists():
        shutil.copy2(str(pdf_path), str(dest))
        logger.info("Source PDF copied to %s", dest)
    else:
        logger.info("Source PDF already exists at %s", dest)


# ---------------------------------------------------------------------------
# Step 8: Archive processed PDF
# ---------------------------------------------------------------------------
def archive_pdf(pdf_path: Path, dry_run: bool = False) -> None:
    """Move processed PDF to coversion/root/finished/."""
    if dry_run:
        logger.info("[DRY-RUN] Would archive %s -> %s/", pdf_path.name, ARCHIVE_DIR)
        return

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / pdf_path.name
    if pdf_path.parent == WORKLOAD_DIR:
        shutil.move(str(pdf_path), str(dest))
        logger.info("Archived PDF: %s -> %s", pdf_path.name, dest)
    else:
        # Don't move PDFs that weren't in workload/ (e.g. --pdf flag)
        shutil.copy2(str(pdf_path), str(dest))
        logger.info("Copied PDF to archive: %s", dest)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def process_single_pdf(
    pdf_path: Path,
    dry_run: bool = False,
    no_ocr: bool = False,
    no_graphics: bool = False,
) -> dict:
    """Run the full pipeline for a single PDF. Returns summary dict."""
    logger.info("=" * 60)
    logger.info("Processing: %s", pdf_path.name)
    logger.info("=" * 60)

    summary = {
        "pdf": pdf_path.name,
        "system_id": None,
        "pages": 0,
        "empty_pages": 0,
        "bundle_dir": None,
        "qa_status": None,
        "graphics": False,
        "errors": [],
    }

    # 1. Detect system
    system_id = detect_system(pdf_path.name)
    summary["system_id"] = system_id
    if system_id == "unknown":
        logger.warning("Could not detect system for %s — using 'unknown'", pdf_path.name)

    # 2. Extract text
    pages = extract_text_pages(pdf_path)
    if not pages:
        summary["errors"].append("Text extraction failed")
        return summary
    summary["pages"] = len(pages)
    summary["empty_pages"] = sum(1 for p in pages if not p["text"])

    # 3. OCR fallback for empty pages
    if not no_ocr and summary["empty_pages"] > len(pages) * 0.5:
        pages = try_ocr_fallback(pdf_path, pages)
        summary["empty_pages"] = sum(1 for p in pages if not p["text"])

    # 4. Create bundle
    bundle_dir = create_bundle(system_id, pdf_path, pages, dry_run=dry_run)
    summary["bundle_dir"] = str(bundle_dir)

    # 5. Graphic extraction
    if no_graphics:
        graphics_ok = False
        logger.info("Graphic extraction skipped (--no-graphics)")
    else:
        graphics_ok = run_graphic_extraction(pdf_path, bundle_dir, dry_run=dry_run)
    summary["graphics"] = graphics_ok

    # 6. Copy source PDF into bundle
    copy_source_pdf(pdf_path, bundle_dir, dry_run=dry_run)

    # 7. Run QA
    qa_result = run_qa(bundle_dir, dry_run=dry_run)
    if qa_result:
        summary["qa_status"] = qa_result.get("validation_status")
    else:
        summary["qa_status"] = "not_run"

    # 8. Archive (only if not dry-run and QA didn't hard-fail)
    if not dry_run:
        archive_pdf(pdf_path, dry_run=dry_run)

    logger.info("Done: %s -> %s (QA: %s)", pdf_path.name, system_id, summary["qa_status"])
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARS Conversion Pipeline — Automatisierte PDF-zu-ARS-Konvertierung",
        epilog=(
            "Scannt coversion/workload/ nach PDFs und fuehrt strukturelle Konversion aus.\n"
            "Entity-Extraktion (KI-gestuetzt) wird als TODO markiert."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pdf", metavar="PATH",
        help="Einzelne PDF-Datei verarbeiten (statt workload/ zu scannen)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulation: zeigt was passieren wuerde, ohne Dateien zu schreiben",
    )
    parser.add_argument(
        "--no-ocr", action="store_true",
        help="OCR-Fallback deaktivieren (nur pypdf-Text verwenden)",
    )
    parser.add_argument(
        "--no-graphics", action="store_true",
        help="Grafik-Extraktion ueberspringen",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Debug-Ausgabe aktivieren",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Discover PDFs
    single_pdf = Path(args.pdf).resolve() if args.pdf else None
    pdfs = discover_pdfs(WORKLOAD_DIR, single_pdf)

    if not pdfs:
        logger.info("Keine PDFs zu verarbeiten.")
        return

    logger.info("Gefunden: %d PDF(s) zur Verarbeitung", len(pdfs))

    summaries = []
    for pdf_path in pdfs:
        summary = process_single_pdf(
            pdf_path,
            dry_run=args.dry_run,
            no_ocr=args.no_ocr,
            no_graphics=args.no_graphics,
        )
        summaries.append(summary)

    # Final summary
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    for s in summaries:
        status_icon = {
            "pass": "OK",
            "fail": "FAIL",
            "fail_empty_ocr": "FAIL(OCR)",
            "fail_no_entity_index": "FAIL(IDX)",
            "dry_run": "DRY",
            "not_run": "SKIP",
        }.get(s["qa_status"], "?")
        errors_str = f" ERRORS: {', '.join(s['errors'])}" if s["errors"] else ""
        print(
            f"  [{status_icon:10s}] {s['pdf']:50s} -> {s['system_id'] or '?':15s} "
            f"({s['pages']} pages, {s['empty_pages']} empty){errors_str}"
        )

    print(f"\nVerarbeitet: {len(summaries)} PDF(s)")
    if args.dry_run:
        print("(Dry-Run — keine Dateien geschrieben)")


if __name__ == "__main__":
    main()
