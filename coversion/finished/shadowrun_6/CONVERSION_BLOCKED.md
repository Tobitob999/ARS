# Shadowrun 6 — Conversion Blocked

**Status:** INCOMPLETE (abgebrochen nach Phase 1)
**Datum:** 2026-03-02
**Erstellt von:** Claude Code (Pipeline Audit)

## Begruendung

Die Konversion wurde nach Phase 1 (Fulltext-Dump) abgebrochen.
Es gibt keine Entity-Extraktion, keinen Entity-Index, kein Chunking und keinen QA-Report.

## Quell-PDF

- **Titel:** Wake of the Comet (Supplement, nicht Core-Regelwerk)
- **Source-PDF-Verzeichnis:** Nicht vorhanden (kein `source_pdf/` im Bundle)
- **Anmerkung:** Das Core-Regelwerk (Shadowrun 6E Grundregelwerk) ist bereits
  separat in `data/lore/shadowrun_6/` integriert (2036 Lore-Chunks aus Session 3).

## Vorhandene Artefakte

- 90 Fulltext-Seiten (`fulltext/page_*.json`)
- 6 Rules-Fulltext-Chunks
- 4 Book-Conversion-Dateien
- Leeres `indices/` Verzeichnis (kein entity_index.json)

## Fehlend

- Entity-Index (`indices/entity_index.json`)
- Entity-Snippets (items, npcs, spells, etc.)
- QA-Report (`indices/conversion_qa_report.json`)
- Source-PDF-Ablage (`source_pdf/`)

## Erforderliche Massnahmen

1. Entscheiden ob Wake of the Comet (Supplement) ueberhaupt konvertiert werden soll
2. Falls ja: Vollstaendige Entity-Extraktion, Chunking und QA durchfuehren
3. Source-PDF in `source_pdf/` ablegen
