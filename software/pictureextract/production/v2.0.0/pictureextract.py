import argparse
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

PICTUREEXTRACT_VERSION = "2.0.0"


SUPPORTED_IMAGE_EXTENSIONS = {
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "png": ".png",
    "tiff": ".tiff",
    "tif": ".tif",
    "bmp": ".bmp",
    "jp2": ".jp2",
    "jpx": ".jpx",
    "pbm": ".pbm",
    "pgm": ".pgm",
    "ppm": ".ppm",
    "pam": ".pam",
}


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
    return cleaned or "pdf_images"


def unique_dir(base_dir: Path) -> Path:
    if not base_dir.exists():
        return base_dir

    counter = 2
    while True:
        candidate = base_dir.parent / f"{base_dir.name}_{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def collect_pdfs(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return [input_path]
    if input_path.is_dir():
        pattern = "**/*.pdf" if recursive else "*.pdf"
        return sorted([p for p in input_path.glob(pattern) if p.is_file()])
    return []


def is_too_small_image(meta: dict, min_pixels: int) -> bool:
    width = int(meta.get("width", 0) or 0)
    height = int(meta.get("height", 0) or 0)
    if width <= 0 or height <= 0:
        return True
    return (width * height) < min_pixels


def is_likely_page_scan(
    doc: fitz.Document,
    page: fitz.Page,
    images_on_page: list[tuple],
    xref: int,
    area_threshold: float,
) -> bool:
    """Heuristic: skip full-page background scans in image-based PDFs."""
    if len(images_on_page) != 1:
        return False

    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return False

    try:
        image_rects = page.get_image_rects(xref)
    except Exception:
        return False
    if not image_rects:
        return False

    rect = image_rects[0]
    area_ratio = (rect.width * rect.height) / page_area

    try:
        meta = doc.extract_image(xref)
    except Exception:
        return False

    width = int(meta.get("width", 0) or 0)
    height = int(meta.get("height", 0) or 0)
    high_res = width >= 1400 or height >= 1400
    return area_ratio >= area_threshold and high_res


def extract_images_from_pdf(
    pdf_path: Path,
    target_root: Path,
    verbose: bool = False,
    skip_page_scans: bool = True,
    page_scan_area_threshold: float = 0.75,
    min_pixels: int = 20000,
    min_display_area_ratio: float = 0.002,
    render_oriented: bool = True,
) -> dict:
    output_dir = unique_dir(target_root / sanitize_name(pdf_path.stem))
    output_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    skipped = 0
    skipped_page_scans = 0
    skipped_small = 0

    doc = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(doc, start=1):
            images = page.get_images(full=True)
            if verbose:
                print(f"[{pdf_path.name}] Seite {page_index}: {len(images)} Bild(er)")

            for image_position, image_info in enumerate(images, start=1):
                xref = image_info[0]

                if skip_page_scans and is_likely_page_scan(
                    doc=doc,
                    page=page,
                    images_on_page=images,
                    xref=xref,
                    area_threshold=page_scan_area_threshold,
                ):
                    skipped_page_scans += 1
                    if verbose:
                        print(
                            f"[{pdf_path.name}] Seite {page_index}: "
                            "Bild als Seiten-Scan erkannt, uebersprungen"
                        )
                    continue

                try:
                    extracted = doc.extract_image(xref)
                except Exception:
                    skipped += 1
                    continue

                if is_too_small_image(extracted, min_pixels):
                    skipped_small += 1
                    if verbose:
                        print(
                            f"[{pdf_path.name}] Seite {page_index}: "
                            "Bild zu klein (Pixel), uebersprungen"
                        )
                    continue

                image_bytes = extracted.get("image")
                image_ext = extracted.get("ext", "bin").lower()
                if not image_bytes:
                    skipped += 1
                    continue

                # Additional tiny-display filter to ignore tiny logos / ornaments.
                try:
                    page_area = page.rect.width * page.rect.height
                    rects = page.get_image_rects(xref)
                    display_ratio = 0.0
                    if rects and page_area > 0:
                        r0 = rects[0]
                        display_ratio = (r0.width * r0.height) / page_area
                    if display_ratio < min_display_area_ratio:
                        skipped_small += 1
                        if verbose:
                            print(
                                f"[{pdf_path.name}] Seite {page_index}: "
                                "Bild zu klein (Anzeige), uebersprungen"
                            )
                        continue
                except Exception:
                    pass

                file_ext = SUPPORTED_IMAGE_EXTENSIONS.get(image_ext, f".{image_ext}")
                out_name = f"page_{page_index:04d}_img_{image_position:03d}{file_ext}"
                out_path = output_dir / out_name

                counter = 2
                while out_path.exists():
                    out_path = output_dir / f"page_{page_index:04d}_img_{image_position:03d}_{counter}{file_ext}"
                    counter += 1

                if render_oriented:
                    # Render clip from page to preserve on-page orientation.
                    try:
                        rects = page.get_image_rects(xref)
                        if rects:
                            clip = rects[0]
                            pix = page.get_pixmap(clip=clip, alpha=False)
                            out_path = out_path.with_suffix(".png")
                            pix.save(str(out_path))
                            saved += 1
                            continue
                    except Exception:
                        # fallback to raw extraction
                        pass

                out_path.write_bytes(image_bytes)
                saved += 1
    finally:
        doc.close()

    return {
        "pdf": str(pdf_path),
        "output_dir": str(output_dir),
        "saved": saved,
        "skipped": skipped,
        "skipped_page_scans": skipped_page_scans,
        "skipped_small": skipped_small,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pictureextract",
        description="Extrahiert Bilder aus einer PDF oder aus allen PDFs in einem Ordner.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {PICTUREEXTRACT_VERSION}")
    parser.add_argument("input", help="Pfad zu PDF-Datei oder Ordner mit PDFs")
    parser.add_argument("target", help="Zielordner fuer extrahierte Bilder")
    parser.add_argument("-r", "--recursive", action="store_true", help="Ordner rekursiv nach PDFs durchsuchen")
    parser.add_argument("-v", "--verbose", action="store_true", help="Detaillierte Ausgabe")
    parser.add_argument(
        "--include-page-scans",
        action="store_true",
        help="Seiten-Scans NICHT filtern (Default: filtern aktiv)",
    )
    parser.add_argument(
        "--page-scan-area-threshold",
        type=float,
        default=0.75,
        help="Ab welchem Flaechenanteil ein Einzelbild als Seiten-Scan gilt (Default: 0.75)",
    )
    parser.add_argument(
        "--min-pixels",
        type=int,
        default=20000,
        help="Mindestpixelzahl fuer ein Bild (width*height), kleinere Bilder werden gefiltert",
    )
    parser.add_argument(
        "--min-display-area-ratio",
        type=float,
        default=0.002,
        help="Mindest-Flaechenanteil auf der Seite fuer Bildanzeige (Default: 0.002)",
    )
    parser.add_argument(
        "--raw-orientation",
        action="store_true",
        help="Rohbild speichern statt orientierungsrichtiger Seiten-Clip",
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    target_root = Path(args.target).expanduser().resolve()

    if not input_path.exists():
        print(f"Fehler: Eingabepfad nicht gefunden: {input_path}", file=sys.stderr)
        return 2

    target_root.mkdir(parents=True, exist_ok=True)

    pdfs = collect_pdfs(input_path, args.recursive)
    if not pdfs:
        print("Fehler: Keine PDF-Dateien gefunden.", file=sys.stderr)
        return 3

    total_saved = 0
    total_skipped = 0

    print(f"Starte Extraktion fuer {len(pdfs)} PDF(s)...")
    for pdf in pdfs:
        result = extract_images_from_pdf(
            pdf,
            target_root,
            verbose=args.verbose,
            skip_page_scans=not args.include_page_scans,
            page_scan_area_threshold=args.page_scan_area_threshold,
            min_pixels=args.min_pixels,
            min_display_area_ratio=args.min_display_area_ratio,
            render_oriented=not args.raw_orientation,
        )
        total_saved += result["saved"]
        total_skipped += result["skipped"]
        print(
            f"- {Path(result['pdf']).name}: {result['saved']} gespeichert, "
            f"{result['skipped']} uebersprungen, "
            f"{result['skipped_page_scans']} Seiten-Scans gefiltert, "
            f"{result['skipped_small']} Kleinbilder gefiltert -> {result['output_dir']}"
        )

    print(f"Fertig. Gesamt: {total_saved} gespeichert, {total_skipped} uebersprungen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
