# ARS Conversion Pipeline — Audit Report

**Erstellt:** 2026-03-02
**Erstellt von:** Claude Code (Pipeline Audit Session)
**Scope:** Alle 4 konvertierten Systeme in `coversion/finished/`

---

## Zusammenfassung

| System | JSON-Files | Entity-Index | Snippet-Qualitaet | Bewertung |
|--------|-----------|-------------|-------------------|-----------|
| **add_2e** | 3613 (coversion) / 930 (data/lore) | Kein entity_index.json | Spells/Monster brauchbar, Regeln als Fulltext-Chunks (2251 Blindchunks). Schema 1.2.1 | **TEILWEISE** |
| **gurps_4e** | 618 | Keiner | 580 Fulltext-Seiten, viele mit `"text": ""` (Scan-PDF ohne OCR). 11 Rules-Chunks. Seed-Dateien | **UNBRAUCHBAR** |
| **mechwarrior_3e** | 4563 | 4300 entities, 100% reconciled | OCR-basiert, `name_guess` enthaelt Artefakte. keyword_window_extraction | **STRUKTURELL OK, INHALTLICH MAESSIG** |
| **shadowrun_6** | 104 | Keiner | Nur Fulltext-Pages (90), keine Entities, kein Chunking | **ABGEBROCHEN** |

---

## Detailanalyse pro System

### ADD 2E (Advanced Dungeons & Dragons 2nd Edition)

**Bewertung: TEILWEISE — Entity-Extraktion fehlt, Blindchunks dominieren**

- **Coversion-Bundle:** 3613 Dateien (103 MB) in `coversion/finished/add_2e/`
- **Integriert in data/lore:** 930 Dateien (5.2 MB) — spells, fulltext, monsters, tables
- **Entity-Index:** Nicht vorhanden
- **Verzeichnis-Verteilung:**
  - `rules_fulltext_chunks/`: 2251 Dateien (62% des Bundles)
  - `book_conversion/`: 429 Dateien
  - `spells/`: 331 Dateien (brauchbar)
  - `fulltext/`: 258 Dateien
  - `derived_rules/`: 151 Dateien
  - `monsters/`: 83 Dateien (brauchbar)
  - `tables/`: 68 Dateien
- **Stichprobe rules_fulltext_chunks:**
  - Core-Buecher (PHB, DMG): Strukturierte Metadaten mit Keyword-Extraktion, Kapitelverzeichnisse
  - Supplements (DMGR*, Encyclopedia Magica): Minimaler bis leerer Inhalt
  - Viele Dateien enthalten nur `"text": ""` (leere Extraktion)
- **Fehlende Verzeichnisse in data/lore:** `rules_fulltext_chunks/` (2251 Files), `derived_rules/` (151 Files) — bewusst nicht integriert
- **Aktion:** Blindchunks sind nicht verwertbar fuer Engine-Injection. Spells/Monster-Snippets sind brauchbar.

### GURPS 4E (Generic Universal RolePlaying System)

**Bewertung: UNBRAUCHBAR — Scan-PDF ohne eingebetteten Text**

- **Coversion-Bundle:** 618 Dateien in `coversion/finished/gurps_4e/`
- **Entity-Index:** Nicht vorhanden
- **Fulltext-Seiten:** 580 — grosse Teile mit `"text": ""` (leeres OCR-Ergebnis)
- **QA-Report:** Zeigt `validation_status: "pass"` — **FALSCH**, wurde durch Autofill-Seeds/NA-Reports erzwungen
- **Tatsaechlicher Zustand:** PDF war ein Scan ohne eingebetteten Text. OCR (pypdf) lieferte leere Seiten. Spaetere Seiten haben teilweise Text (easyocr-Backfill?), aber Coverage ist unzureichend.
- **Aktion:** Status auf `fail_empty_ocr` korrigiert. CONVERSION_BLOCKED.md erstellt.

### MechWarrior 3E (BattleTech)

**Bewertung: STRUKTURELL OK, INHALTLICH MAESSIG — OCR-Garbage in ~30% der Entities**

- **Coversion-Bundle:** 4563 Dateien in `coversion/finished/mechwarrior_3e/`
- **Entity-Index:** 4300 Entities, 100% Reconciliation laut QA-Report
- **Verzeichnis-Verteilung:**
  - `npcs/`: 882 Dateien
  - `history/`: 849 Dateien
  - `lore/`: 509 Dateien
  - `items/`: 488 Dateien
  - `factions/`: 488 Dateien
  - `locations/`: 415 Dateien
  - `vehicles/`: 392 Dateien
  - `fulltext/`: 246 Seiten
- **OCR-Qualitaet (Stichprobe):**
  - `name_guess` enthaelt Artefakte: "Negotiation is also useful for interpreting veiled messages_", "Even (Lost Limb Trait] Grazing Wound will heal"
  - Typische OCR-Fehler: Zeichenersetzung ("weck"→"week", "tinger"→"finger"), Klammerfehler, fehlende Leerzeichen
  - Geschaetzt ~30% der name_guess-Felder enthalten OCR-Artefakte
- **Grafik-Extraktion:** Vorhanden (grafik_extract/, grafik_extract_v2/, grafik_extract_filtered/)
- **Source-PDF:** Vorhanden in source_pdf/
- **Aktion:** Fuer Engine-Verwendung muessen name_guess-Felder bereinigt werden. Strukturell vollstaendig.

### Shadowrun 6 (Wake of the Comet)

**Bewertung: ABGEBROCHEN — nur Phase 1 (Fulltext) erreicht**

- **Coversion-Bundle:** 104 Dateien in `coversion/finished/shadowrun_6/`
- **Entity-Index:** Nicht vorhanden (indices/ Verzeichnis ist leer)
- **Fulltext-Seiten:** 90
- **Source-PDF:** Nicht vorhanden (kein source_pdf/ Verzeichnis)
- **Quell-PDF:** Wake of the Comet (Supplement, nicht Core-Regelwerk)
- **Tatsaechlicher Zustand:** Konversion wurde nach Phase 1 (Fulltext-Dump) abgebrochen. Keine Entity-Extraktion, kein Chunking, kein QA-Report.
- **Aktion:** CONVERSION_BLOCKED.md erstellt. Nicht verwertbar fuer Engine.

---

## QA-Ergebnisse (enforce_full_depth.py v1.1.0 — mit gehärteten Checks)

| System | Status | OCR-Empty-Ratio | Entity-Index | Snippet-Warnings |
|--------|--------|-----------------|--------------|------------------|
| add_2e | **fail_empty_ocr** | 258/258 (100%) | nein | 0/0 |
| gurps_4e | **fail_empty_ocr** | 580/580 (100%) | nein | 0/0 |
| mechwarrior_3e | **pass** | 246/246 (100%) | ja (4300) | 1447/4255 (34%) |
| shadowrun_6 | **fail_empty_ocr** | 88/90 (98%) | nein | 0/0 |

**Anmerkung:** mechwarrior_3e hat zwar leere Fulltext-Seiten, aber 4300 Entity-Snippets
mit eigener OCR-Extraktion. Der Entity-Index kompensiert die leeren Fulltext-Pages.

---

## Empfehlungen

1. **add_2e:** Entity-Extraktion nachholen (Spells/Monster sind da, aber kein entity_index.json). Blindchunks (2251) koennen geloescht oder ignoriert werden.
2. **gurps_4e:** Quell-PDF mit echtem OCR-Tool (Tesseract/easyocr) neu scannen. Erst danach Pipeline erneut starten.
3. **mechwarrior_3e:** OCR-Cleanup fuer name_guess-Felder. Entity-Daten sind strukturell vollstaendig.
4. **shadowrun_6:** Core-Regelwerk (nicht Supplement) als Quelle verwenden. Komplette Neukonversion noetig.
