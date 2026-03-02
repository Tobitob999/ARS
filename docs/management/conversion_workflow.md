# ARS Coversion Workflow (Autopilot)

## Ziel
PDFs in `coversion/workload/` werden automatisch in voller Tiefe verarbeitet und als ARS-kompatible Artefakte nach `coversion/finished/` ausgegeben.

## Standardpipeline (ohne Rueckfrage)
1. Eingang in `coversion/workload/` erkennen.
2. System-Erkennung: neues oder bestehendes System (`system_id`).
3. Volltiefen-Extrakt ausfuehren:
   - `book_conversion` (pages.jsonl, metadata, chapter_map, manifest)
   - `fulltext/page_###.json`
   - `rules_fulltext_chunks`
   - `derived_rules` (profile, coverage, digest, merge_candidates, finalreport)
   - `modules/rulesets/{system_id}.json` (+ Preset falls sinnvoll)
   - Grafik-Extraktion via Production-Tool `pictureextract` in `grafik_extract/`
4. Validierung:
   - JSON parse checks
   - Referenzpfade pruefen
   - 12-Phasen-Completeness report schreiben
   - Hard-Gate: Lauf gilt nur als "fertig", wenn alle 12 Phasen "done" oder "na_with_reason" sind
   - Hard-Gate: kein Fachordner darf still leer bleiben (entweder Artefaktdatei oder `*_na_report.json`)
   - Hard-Gate: Entity-Reconciliation muss 100% sein (`indices/entity_index.json` gegen Snippet-Dateien)
5. Ausgabe-Bundle in `coversion/finished/{system_id}/` speichern.
6. Original-PDF zusaetzlich in `coversion/finished/{system_id}/source_pdf/` ablegen.
7. Verarbeitetes PDF nach `coversion/root/finished/` verschieben.

## Ausgabeformat in finished
- `data/lore/{system_id}/...`
- `modules/rulesets/{system_id}.json`
- optional `modules/presets/{preset}.json`
- `grafik_extract/...` (durch `pictureextract`)
- `source_pdf/{original_filename}.pdf`

## Betriebsregel
Diese Pipeline ist ab sofort Standard und wird fuer neue PDF-Eingaenge automatisch ausgefuehrt, sofern der User keine Teiltiefe verlangt.

## Production-Software (verbindlich)
- `pictureextract` wird als Production-Programm aus `software/pictureextract/production/{version}/` betrieben.
- Alte Programmstaende sind in `software/pictureextract/archive/{version}/` zu archivieren.

## Vollstaendigkeits-Definition (verbindlich)
- "Volltiefe" bedeutet hier immer: `book_conversion`, `fulltext`, `rules_fulltext_chunks`, `derived_rules`, Ruleset-Datei und 12-Phasen-QA.
- Wenn eine Phase aus Quellmaterial wirklich nicht belegbar ist, MUSS eine N/A-Datei mit Begruendung erzeugt werden (kein stilles Leerfeld).
- Ein PDF darf erst nach `coversion/root/finished/` verschoben werden, wenn der QA-Status `pass` ist.

## Entity-First Extraktion (verbindlich)
- Zielbild ist eine entitaetsbasierte Extraktion statt nur Kapitel/Feld-Chunks.
- Fuer jedes PDF MUSS `indices/entity_index.json` erzeugt werden.
- Der Entity-Index enthaelt pro Eintrag mindestens:
  - `breadcrumb_path` (Format: `Hauptkapitel > Unterkapitel > Sektion`)
  - `entity_id`
  - `entity_type` (`npc` | `item` | `spell` | `monster` | `quest` | `location` | `rule` | `table` | `character_option`)
  - `name`
  - `source_pages`
  - `snippet_path`
  - `status` (`extracted` | `na_with_reason`)

## 100%-Snippet Ziel (verbindlich)
- Alle erkannten Entitaeten muessen in Snippet-Dateien abgebildet werden.
- Reconciliation-Regeln:
  - Jede Entity im Index muss auf eine existierende Snippet-Datei zeigen.
  - Jede Snippet-Datei muss im Index referenziert sein.
  - Fehlende Zuordnungen sind als `unresolved_entities` im QA-Report zu fuehren.
- Tabellen-Normalisierung:
  - Mehrseitige Tabellen muessen pro Teil-Snippet den vollstaendigen Header replizieren.
  - Fehlt der Header im Teil-Snippet, ist der Eintrag QA-seitig ungueltig (`unresolved_entities`).
- QA-Abschluss ist nur erlaubt bei:
  - `coverage_percent = 100` ODER
  - vollstaendiger, expliziter `na_with_reason`-Dokumentation pro nicht extrahierbarer Entitaet.

## Verwertbarkeit (strict)
- Blindes Segmentieren in Mini-Schnipsel ohne Entitaetsbezug ist unzulaessig.
- Vorhandene Chaos-/Blind-Snippets muessen vor einem Restlauf entfernt oder explizit aus dem Index ausgeschlossen werden.
- Erstwurf muss mindestens diese Entitaetsklassen erzeugen, sofern im Text vorhanden:
  - `items`, `spells`, `vehicles`, `quests`, `npcs`, `monsters`, `lore`, `history`
  - optional/ergaenzend: `factions`, `locations`
- Pflichtfelder je erzeugtem Snippet:
  - Provenienz: `generated_at`, `generated_by`, `method`
  - Herkunft: `source_text.pdf`, `source_text.page`
  - Kontext: `breadcrumb_path`
  - Identifikation: `entity_id`, `entity_type`, `status`
  - Inhalt: verwertbarer `excerpt` + kategoriespezifische Datenfelder
  - Verweise: `_ref` (wenn Querverweise erkannt werden)
- Hard-Gate zusaetzlich:
  - Kein `pass`, wenn eine Pflicht-Entitaetsklasse leer ist und keine `na_with_reason`-Dokumentation existiert.

## Typ-spezifische Mindestfelder (verbindlich)
- `spell`: Name, Kosten, Reichweite, Dauer, Effekt, Seitenreferenz
- `monster`: Name, Stats, Angriffe, Sonderregeln, Seitenreferenz
- `npc`: Rolle, Werte/Skills, Fraktion, Hook, Seitenreferenz
- `item`: Name, Kosten, Gewicht/Slot, Regelwirkung, Seitenreferenz
- `quest`: Einstieg, Ziel, Trigger, Belohnung, Fail-State, Seitenreferenz
