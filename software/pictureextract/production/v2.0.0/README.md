# PDF Bild-Extraktor (CLI)

Dieses Tool durchsucht eine PDF-Datei und extrahiert alle eingebetteten Bilder.
Die Bilder werden in einen Unterordner gespeichert, dessen Name dem PDF-Dateinamen entspricht.

## Funktionen
- CLI-basierte Bildextraktion aus PDFs
- Automatische Ordnerstruktur: `<Zielordner>/<PDF-Name>/...`
- Batch-faehig fuer Pipeline-Integration

## Voraussetzungen
- Python 3.10+
- `PyMuPDF` (Modulname: `fitz`)

Falls noetig installieren:

```bash
pip install pymupdf
```

## Starten

```bash
python pictureextract.py <pdf_path> [output_dir]
```

Oder via Wrapper:

```bash
pictureextract.cmd <pdf_path> [output_dir]
```

## Versionshistorie
- v2.0.0: CLI-Version fuer Pipeline-Integration (ohne GUI)
- v1.0.0: GUI-Version mit app.py (archiviert)
