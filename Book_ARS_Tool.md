# Book → ARS Konvertierungs-Pipeline

**Version:** 1.0
**Datum:** 2026-02-28
**Zweck:** Anleitung fuer KI-Agenten zur vollstaendigen Konvertierung eines Pen-&-Paper-Regelbuchs in ARS-kompatible JSON-Module.

**Parallel anwenden mit:** `WCR.md` (Schema-Referenz)

---

## 1. Ueberblick

Diese Anleitung beschreibt den Prozess, ein physisches oder digitales RPG-Regelbuch in das ARS-JSON-Format umzuwandeln. Das Ziel ist die **vollstaendige mechanische Abbildung** des Regelwerks — nicht nur ein Auszug.

**Zwei Produkte entstehen:**
1. **Ruleset-JSON** (`modules/rulesets/{system_id}.json`) — Regelgeruest mit allen mechanischen Sektionen
2. **Lore-Dateien** (`data/lore/{system_id}/`) — Monster, Zauber, Items, Tabellen als Einzeldateien

**Prinzip:** Das universelle Regelgeruest in WCR.md Sektion 3 definiert **alle moeglichen Felder**. Dieses Dokument beschreibt, **wie** ein Buch darauf abgebildet wird.

---

## 2. Vorbereitung

### 2.1 Benoetigte Referenz-Dokumente

Lade vor Beginn:
1. `WCR.md` — Schema-Referenz (insbesondere Sektion 3: Skeleton-Baum)
2. `modules/rulesets/add_2e.json` — Beispiel-Ruleset (Fantasy/d20)
3. `modules/rulesets/cthulhu_7e.json` — Beispiel-Ruleset (Horror/d100)
4. `agents.md` — Codex-Richtlinien und Namenskonventionen

### 2.2 System-ID festlegen

Bestimme die `system_id` fuer das neue Regelsystem:
- Format: `snake_case`
- Muster: `{system}_{edition}` (z.B. `dnd_5e`, `gurps_4e`, `shadowrun_6e`)
- Diese ID wird als Dateiname und Verzeichnisname verwendet

### 2.3 Zielverzeichnisse anlegen

```
modules/rulesets/{system_id}.json
data/lore/{system_id}/
data/lore/{system_id}/monsters/
data/lore/{system_id}/items/
data/lore/{system_id}/spells/
data/lore/{system_id}/loot/
data/lore/{system_id}/encounters/
data/lore/{system_id}/tables/
```

---

## 3. Phasen-Pipeline

Die Konvertierung erfolgt in **12 Phasen**. Jede Phase extrahiert bestimmte Informationen aus dem Buch und ordnet sie dem ARS-Skeleton zu.

### Phase 1: Inhaltsverzeichnis → Skeleton-Mapping

**Eingabe:** Inhaltsverzeichnis des Regelbuchs
**Ausgabe:** Mapping-Tabelle: Buch-Kapitel → ARS-Skeleton-Felder

Erstelle eine Tabelle:

| Buch-Kapitel | Seiten | ARS-Skeleton-Feld | Status |
|-------------|--------|-------------------|--------|
| Kapitel 1: Einleitung | 1-12 | metadata | offen |
| Kapitel 2: Charaktererschaffung | 13-40 | characteristics, races, classes | offen |
| Kapitel 3: Fertigkeiten | 41-60 | skills | offen |
| ... | ... | ... | ... |
| Anhang: Monsterliste | 200-290 | data/lore/monsters/ | offen |

**Sonderfaelle markieren:** Wenn ein Kapitel keine klare Zuordnung hat → Notiz "extensions?" hinzufuegen.

### Phase 2: metadata

**Buch-Quelle:** Titelseite, Impressum, Einleitung
**ARS-Feld:** `metadata`

Extrahiere:
```json
{
  "metadata": {
    "name": "Name des Systems",
    "version": "Edition/Version",
    "system": "{system_id}",
    "schema_version": "1.0.0",
    "publisher": "Verlag",
    "language": "de",
    "game_master_title": "Titel des Spielleiters",
    "player_character_title": "Titel der Spielercharaktere"
  }
}
```

### Phase 3: dice_system

**Buch-Quelle:** Kapitel "Spielmechanik" / "Wuerfelproben"
**ARS-Feld:** `dice_system`

Identifiziere:
- Haupt-Wuerfel (d20, d100, 2d6, d10 Pool, ...)
- Probe-Richtung (roll_under vs. roll_over)
- Erfolgs-Stufen (Kritisch, Extrem, Hart, Patzer)
- Bonus/Malus-Mechanik

### Phase 4: characteristics

**Buch-Quelle:** Kapitel "Attribute" / "Characteristics"
**ARS-Feld:** `characteristics`

Fuer jedes Attribut:
```json
{
  "ATTR_CODE": {
    "label": "Anzeigename",
    "roll": "Wuerfelformel (z.B. 3d6)",
    "multiplier": "Proben-Multiplikator"
  }
}
```

### Phase 5: attribute_bonuses

**Buch-Quelle:** Attribut-Tabellen (z.B. "Staerke-Tabelle")
**ARS-Feld:** `attribute_bonuses`

Viele Systeme haben Tabellen die Attributwerten mechanische Boni zuordnen. Jede solche Tabelle wird als Threshold-Array abgebildet.

### Phase 6: races

**Buch-Quelle:** Kapitel "Voelker" / "Rassen" / "Spezies"
**ARS-Feld:** `races`

Pro spielbarer Rasse: Modifikatoren, Groesse, Bewegung, Spezialfaehigkeiten, Klassenbeschraenkungen, Stufenlimits.

### Phase 7: classes + progression

**Buch-Quelle:** Kapitel "Klassen" / "Berufe"
**ARS-Felder:** `classes`, `saving_throws.tables`

Dies ist meist die **umfangreichste Phase**. Pro Klasse:
- Grunddaten (Hit Die, Attribute, erlaubte Waffen/Ruestung)
- Progressionstabelle (Level → XP, THAC0/Angriff, Rettungswuerfe, Titel)
- Zauber-Slots (falls Zauberer)
- Spezialfaehigkeiten pro Stufe

**Batching-Empfehlung:** 2-3 Klassen pro Batch.

### Phase 8: skills

**Buch-Quelle:** Kapitel "Fertigkeiten" / "Skills"
**ARS-Feld:** `skills`

Pro Fertigkeit: Name, Basiswert, Formel, Klassen-Bindung, Kategorie.

### Phase 9: combat

**Buch-Quelle:** Kapitel "Kampf" / "Combat"
**ARS-Feld:** `combat`

Extrahiere: Initiative-System, Ueberraschung, Aktionen pro Runde, Angriffsregeln, kritische Treffer, Patzer, Flucht, Moral.

### Phase 10: magic

**Buch-Quelle:** Kapitel "Magie" / "Zauber"
**ARS-Felder:** `magic` (im Ruleset), `data/lore/{system_id}/spells/` (einzelne Zauber)

**Zweistufig:**
1. **Magie-System** (ins Ruleset): System-Typ, Schulen, Slot-Tabellen, Lernregeln
2. **Einzelne Zauber** (als Lore): Pro Zauber eine JSON-Datei nach Spell-Schema

**Batching:** Zauber kapitelweise konvertieren (z.B. "Stufe 1 Zauber", "Stufe 2 Zauber", ...).

### Phase 11: Uebrige Sektionen

**Sammelt die verbleibenden Skeleton-Felder:**
- `alignment` ← Gesinnungs-Kapitel
- `movement` ← Bewegungsregeln
- `encumbrance` ← Traglast-Regeln
- `economy` ← Waehrung, Preislisten, Startgold
- `conditions` ← Zustandsregeln (Gift, Laehmung, ...)
- `healing` ← Heilungsregeln, Tod & Sterben
- `experience` ← XP-Vergabe, Stufenaufstieg, Training
- `time` ← Runden, Zuege, Rasten
- `senses` ← Sicht, Licht, Wahrnehmung
- `travel` ← Reisen, Zufallsbegegnungen, Wetter
- `henchmen_hirelings` ← Gefolge, Soeldner
- `downtime` ← Zwischen-Abenteuer-Aktivitaeten

### Phase 12: extensions

**Buch-Quelle:** Alles was in keine vorherige Phase passt
**ARS-Feld:** `extensions`

Sammle System-spezifische Mechaniken:
- Mechaniken die nur dieses System hat
- Optionale Regel-Varianten
- Subsysteme (z.B. Psionics, Schiffskaempfe, Massenschlachten)

---

## 4. Batching-Strategie

### Fuer grosse Buecher (200+ Seiten)

Teile die Arbeit in Batches auf:

| Batch | Phasen | Seiten (ca.) |
|-------|--------|-------------|
| 1 | Phase 1-4 | Kapitel 1-3 (Grundlagen, Attribute) |
| 2 | Phase 5-6 | Kapitel 4-5 (Rassen, Attribut-Tabellen) |
| 3 | Phase 7 (Teil 1) | Kapitel 6 (Klassen A-D) |
| 4 | Phase 7 (Teil 2) | Kapitel 6 (Klassen E-Z) |
| 5 | Phase 8-9 | Kapitel 7-8 (Fertigkeiten, Kampf) |
| 6 | Phase 10 (System) | Kapitel 9 (Magie-Regeln) |
| 7 | Phase 10 (Zauber 1-3) | Kapitel 9 (Zauber Stufe 1-3) |
| 8 | Phase 10 (Zauber 4-9) | Kapitel 9 (Zauber Stufe 4-9) |
| 9 | Phase 11 | Kapitel 10-12 (Reisen, Wirtschaft, ...) |
| 10 | Phase 12 + Monster A-G | Anhang |
| 11 | Monster H-Z | Anhang |
| 12 | Items + Tabellen | Anhang |

### Pro Batch

1. **Lese** den relevanten Buchausschnitt
2. **Extrahiere** Daten in das ARS-Format
3. **Validiere** gegen WCR-Schema
4. **Merge** in das bestehende Ruleset-JSON (Deep-Merge, keine Felder ueberschreiben)
5. **Markiere** Phase als abgeschlossen im Mapping (Phase 1 Tabelle)

### Merge-Strategie

```
Batch N erzeugt: { "combat": { "initiative": {...} } }
Batch N+1 erzeugt: { "combat": { "morale": {...} } }
Merge-Ergebnis: { "combat": { "initiative": {...}, "morale": {...} } }
```

Konflikte (gleicher Schluessel, anderer Wert) → spaeterer Batch gewinnt + Warnung loggen.

---

## 5. Lore-Extraktion

Parallel zum Ruleset werden Lore-Dateien als Einzeldateien extrahiert.

### Zuordnung Buch → Lore-Verzeichnis

| Buchkapitel | Lore-Verzeichnis | Schema |
|------------|-----------------|--------|
| Monsterliste / Bestiarium | `monsters/` | Monster-Schema (WCR 11) |
| Zauberliste | `spells/` | Spell-Schema (WCR 11) |
| Ausruestungslisten | `items/` | Item-Schema (WCR 11) |
| Schatztabellen | `loot/` | Loot-Schema (WCR 11) |
| Begegnungstabellen | `encounters/` | Encounter-Schema (WCR 11) |
| Zufallstabellen | `tables/` | Tables-Schema (WCR 11) |

### Dateibenennug

- Ein Eintrag = eine Datei
- Dateiname = `snake_case` des Eintragsnamens
- Beispiel: "Magic Missile" → `magic_missile.json`

### Massenverarbeitung

Bei grossen Listen (100+ Monster, 200+ Zauber):
1. Pro Batch maximal 20-30 Eintraege
2. Nach jedem Batch: JSON-Validierung aller neuen Dateien
3. `index.json` am Ende aktualisieren

---

## 6. Mapping-Regeln

### 1:1 Mapping

Buch-Konzept hat ein exaktes Skeleton-Feld:
- "Strength" → `characteristics.STR`
- "Armor Class" → `combat.armor_class`
- "Fireball (Spell)" → `data/lore/{system_id}/spells/fireball.json`

### 1:N Mapping

Buch-Konzept verteilt sich auf mehrere ARS-Felder:
- "Elf" (im Buch ein Kapitel) → `races.elf` (Modifikatoren) + `senses.vision_types.infravision` (Verweis) + `classes.*.level_limits.elf` (Stufenlimits)

### N:1 Mapping

Mehrere Buch-Kapitel fuellen ein ARS-Feld:
- "Kampf-Kapitel" + "Optionale Kampfregeln" → beide in `combat`

### Kein Mapping

Buch-Konzept existiert nicht im Skeleton:
- "Psionics" → `extensions.psionics`
- "Ship Combat" → `extensions.ship_combat`
- Immer pruefen ob nicht doch ein Skeleton-Feld passt

### Tracking-Log

Fuehre ein Log welche Buchseiten welchen ARS-Feldern zugeordnet wurden:

```
Seite 15-16: characteristics (STR, DEX, CON, INT, WIS, CHA)
Seite 17-20: attribute_bonuses.STR (Staerke-Tabelle)
Seite 21-24: races (Elf, Zwerg, Halbelf, Halbling, Gnom)
...
Seite 289-290: NICHT ZUGEORDNET — "Optional Mass Combat Rules"
```

Nicht zugeordnete Seiten am Ende pruefen: Gehoeren sie in `extensions`? Oder wurden sie versehentlich uebersprungen?

---

## 7. Qualitaets-Checkliste

Nach Abschluss der Konvertierung:

### Ruleset-JSON

- [ ] Alle 4 Pflichtfelder vorhanden (metadata, dice_system, characteristics, skills)
- [ ] `metadata.schema_version` gesetzt (z.B. "1.0.0")
- [ ] `metadata.system` stimmt mit Dateiname ueberein
- [ ] Zahlen sind Zahlen, nicht Strings (`"ac": 5` nicht `"ac": "5"`)
- [ ] Wuerfelmechaniken in Standard-Notation (`XdY+Z`)
- [ ] Alle Klassen haben `progression`-Tabellen
- [ ] Alle `spellcasting`-Verweise zeigen auf existierende Lore-Dateien
- [ ] `saving_throws.tables` sind vollstaendig (alle Klassen, alle Level-Bereiche)
- [ ] JSON valide: `python -c "import json; json.load(open('...'))" `

### Lore-Dateien

- [ ] Jede Datei hat `id` (snake_case, entspricht Dateiname ohne .json)
- [ ] Monster: mindestens `id`, `ac`, `hit_dice`, `thac0`, `attacks`
- [ ] Spells: mindestens `id`, `name`, `level`, `range`, `duration`, `casting_time`, `components`, `saving_throw`, `description`
- [ ] Items: mindestens `id`, `item_type`
- [ ] Encoding: UTF-8 ohne BOM
- [ ] `index.json` aktualisiert mit korrekten Pfaden und Zaehlerstaenden

### Vollstaendigkeit

- [ ] Mapping-Log hat keine "NICHT ZUGEORDNET"-Eintraege (oder sie sind in `extensions`)
- [ ] Alle Buchkapitel sind abgedeckt
- [ ] Alle Tabellen im Buch sind als JSON abgebildet
- [ ] Stichproben-Test: 3 zufaellige Monster, 3 Zauber, 3 Items gegen Buch pruefen

---

## 8. Versionierung

### Erstkonvertierung

- Ruleset: `schema_version: "1.0.0"`
- Alle Lore-Dateien implizit Version 1.0.0 (kein schema_version-Feld noetig in Lore)

### Nachtraegliche Korrekturen

- Inhaltliche Fehler beheben: **PATCH** bump → `"1.0.1"`
- Neue Kapitel hinzufuegen (z.B. Erweiterungsbuch): **MINOR** bump → `"1.1.0"`
- Schema-Aenderung (z.B. Feld umstrukturiert): **MAJOR** bump → `"2.0.0"`

### Commit-Message-Konvention

```
feat(ruleset): add dnd_5e ruleset v1.0.0 — Kapitel 1-6 (Grundlagen, Klassen)
feat(lore): add dnd_5e monsters A-G (45 Eintraege)
fix(ruleset): correct dnd_5e Fighter progression table — schema 1.0.1
feat(ruleset): add dnd_5e magic section from PHB Ch.10 — schema 1.1.0
```

---

## 9. Haeufige Fallstricke

| Problem | Loesung |
|---------|---------|
| Tabellen mit vielen Spalten | Als Array von Objekten mit benannten Feldern |
| Querverweise im Buch ("siehe Seite X") | Als `_ref`-Feld oder in `notes` |
| Optionale Regeln | In `extensions` oder als separate `extras`-Module |
| Widersprueche zwischen Kapiteln | Spaeteres Kapitel gewinnt + Kommentar in `notes` |
| Illustration-only-Seiten | Ueberspringen, im Mapping-Log als "Illustration" markieren |
| Errata/FAQ | Als PATCH-Update nach Erstkonvertierung |
| Veraltete Begriffe | ARS-kompatible Begriffe verwenden, Original in `notes` |

---

## 10. Beispiel-Workflow: AD&D 2e Konvertierung

```
1. system_id = "add_2e" (bereits festgelegt)
2. Mapping: Player's Handbook → 12 Phasen
3. Phase 1: ToC-Mapping erstellt
4. Phase 2: metadata ✓ (bereits vorhanden)
5. Phase 3: dice_system ✓ (bereits vorhanden)
6. Phase 4: characteristics ✓ (6 Attribute vorhanden)
7. Phase 5: attribute_bonuses → NEU: STR/DEX/CON/INT/WIS/CHA Tabellen
8. Phase 6: races → NEU: Elf, Zwerg, Halbelf, Halbling, Gnom, Halb-Ork
9. Phase 7: classes → ERWEITERN: Progression + hit_die + spellcasting
10. Phase 8: skills → ERWEITERN: Allgemeine Skills (nicht nur Thief)
11. Phase 9: combat → ERWEITERN: Initiative, Surprise, Moral
12. Phase 10: magic → NEU: Komplett + Einzelzauber als Lore
13. Phase 11: movement, encumbrance, economy, etc. → ALLES NEU
14. Phase 12: extensions (exceptional_strength, weapon_speed_factor)
15. Validierung + schema_version bump auf "2.0.0"
```
