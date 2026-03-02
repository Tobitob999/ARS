# ADD 2E — Conversion Structure Note

**Datum:** 2026-03-02
**Erstellt von:** Claude Code (Pipeline Audit)

## Layout

Legacy Flat-Struktur: `add_2e/add_2e/...` (innerer Ordner = Lore-Root)

## Bundle-Inhalt (coversion/finished/add_2e/)

| Verzeichnis | Dateien | Status |
|-------------|---------|--------|
| rules_fulltext_chunks | 2251 | Nicht integriert — Blindchunks |
| book_conversion | 429 | Nicht integriert — Metadaten |
| spells | 331 | Integriert in data/lore/add_2e/ |
| fulltext | 258 | Integriert |
| derived_rules | 151 | Nicht integriert |
| monsters | 83 | Integriert |
| tables | 68 | Integriert |
| chapters | 15 | Integriert |
| appendices | 9 | Integriert |
| mechanics | 6 | Integriert |
| indices | 4 | Integriert |
| Sonstige (1 Datei je) | 7 | Integriert (Seed/NA-Dateien) |
| **Gesamt** | **3613** | |

## Integration in data/lore/add_2e/

930 Dateien integriert (Spells, Fulltext, Monsters, Tables, Chapters, etc.)

## Nicht integrierte Verzeichnisse

### rules_fulltext_chunks/ (2251 Dateien)

**Bewertung:** Nicht verwertbar fuer Engine-Injection.

Stichprobe zeigt:
- Core-Buecher (PHB, DMG): Strukturierte Metadaten mit Kapitelverzeichnissen und Keyword-Extraktion
- Supplements: Minimaler bis leerer Inhalt (`"text": ""`)
- Die meisten Dateien enthalten Phase-1-Mapping-Metadaten ohne verwertbaren Regeltext
- Fuer die RulesEngine (Schicht 3, keyword-basierter Index) nicht direkt nutzbar

**Entscheidung:** Verbleiben im Coversion-Bundle als Referenz. Nicht in data/lore/ kopieren.

### derived_rules/ (151 Dateien)

**Bewertung:** Potenziell wertvoll, aber nicht Engine-kompatibel.

Enthaelt:
- Rules-Profile-Dateien mit Scoring und PDF-Seitenreferenzen
- Automatisierte Feld-Extraktion mit Konfidenz-Werten
- Koennte fuer zukuenftige RulesEngine-Erweiterung genutzt werden

**Entscheidung:** Verbleiben im Coversion-Bundle. Integration bei Bedarf.

## Fehlend

- **Entity-Index:** `indices/entity_index.json` existiert nicht
- **Entity-Reconciliation:** Nicht durchgefuehrt
- Spells und Monsters sind als Einzel-Dateien vorhanden, aber nicht durch einen Index verknuepft
