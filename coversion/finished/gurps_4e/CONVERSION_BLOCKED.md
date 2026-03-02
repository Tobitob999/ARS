# GURPS 4E — Conversion Blocked

**Status:** BLOCKED (fail_empty_ocr)
**Datum:** 2026-03-02
**Erstellt von:** Claude Code (Pipeline Audit)

## Begruendung

Die Quell-PDF (GURPS Basic Set) ist ein Scan ohne eingebetteten Text.
Die Text-Extraktion via pypdf lieferte fuer den Grossteil der 580 Seiten leere Strings (`"text": ""`).

Ein spaeterer OCR-Backfill (easyocr) hat teilweise Text auf spaeteren Seiten erzeugt,
aber die Coverage ist unzureichend fuer eine verwertbare Konversion.

## QA-Status

Der urspruengliche QA-Report (`indices/conversion_qa_report.json`) zeigte faelschlicherweise
`validation_status: "pass"` — dies wurde durch Autofill-Seeds und NA-Reports erzwungen,
nicht durch tatsaechlich vorhandene Inhalte.

**Korrigiert auf:** `fail_empty_ocr`

## Erforderliche Massnahmen

1. Quell-PDF mit einem echten OCR-Tool (Tesseract, easyocr mit GPU, oder ABBYY) neu scannen
2. Sicherstellen dass >90% der Seiten verwertbaren Text enthalten
3. Danach Pipeline erneut starten

## Vorhandene Artefakte

- 580 Fulltext-Seiten (groesstenteils leer)
- 11 Rules-Fulltext-Chunks (teilweise mit Inhalt)
- 5 Derived-Rules-Dateien
- Seed/NA-Dateien in allen Fachordnern (nicht verwertbar)
