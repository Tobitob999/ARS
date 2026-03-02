# ARS - Global Agent Rules (rules.md)

## 1. Fuehrende Instanz & Planung
- **Fuehrender Chat:** Der Gemini-User-Konsole-Chat ist die fuehrende Instanz. Jede dort getroffene Entscheidung oder Anweisung ist eine bindende Regel fuer die Session-Logik und muss sofort in die Dokumentation uebernommen werden.
- **Strategische Ebene (Roadmap):** Weitblick, Lore-Aufbau, Architektur. Review alle 3 Tage.
- **Kurzfristige Ebene (To-Dos):** Direkte Entwicklungsschritte für den nächsten Testlauf.

## 2. Kommunikations-Hub: agents.md (Stelle A)
[agents.md](agents.md) ist der zentrale Einsatzbefehl und Rückmeldeort.
- **Lesepflicht:** Vor jeder Aktion [agents.md](agents.md) prüfen.
- **Berichtspflicht:** Nach Abschluss einer Aufgabe Status in [agents.md](agents.md) unter "Agent Reports" aktualisieren.
- **Format:** `[YYYY-MM-DD HH:MM] | FROM: [Agent] | [Status/Ergebnis]`

## 3. Strategie & Ideen: [suggestions.md](suggestions.md)
- Agenten sind ausdrücklich ermutigt, Ideen für Lore, Gegenstände, NPCs oder Mechaniken hier zu deponieren.
- Diese werden im 3-Tages-Strategielauf gesichtet und in das Active Backlog übernommen.

## 4. Hintergrund-Tasks (Lore/Data)
- Datensammlungen (Menschen, Gebäude, Länder) werden als "Background-Threads" in [suggestions.md](suggestions.md) vorbereitet und nach Freigabe in das `/data/` Verzeichnis überführt.

## 5. Schreib-Etikette
- Knapp, präzise, keine Floskeln.
- Bestehende Einträge nicht ohne Grund löschen.

## 6. Kommunikations-Verbot: Keine Gegenfragen (Mandatory)
- Claude Code stellt **KEINE** Rückfragen wie "Soll ich als nächstes...?", "Darf ich...?", "Möchtest du, dass ich...?" oder ähnliche Bestätigungsanfragen.
- Erhaltene Aufgaben werden eigenständig und vollständig abgearbeitet.
- Rückfragen sind NUR erlaubt, wenn eine technische Abhängigkeit unklar ist und ohne Antwort keine Implementierung möglich ist.
- Alle Outputs und Entscheidungen von Gemini werden von Claude Code **eigenständig** in die relevanten Dokumente übertragen — ohne Rückfrage.

## 7. Sekretariats-Protokoll: Claude Code als administrativer Agent
- Claude Code übernimmt **alle administrativen Aufgaben** eigenständig:
  - Gemini-Outputs (Regeln, Entscheidungen, Prompts) werden direkt in `docs/management/` übertragen.
  - Neue Tasks werden sofort in [agents.md](agents.md) dokumentiert.
  - Abgeschlossene Tasks werden mit Timestamp in "Agent Reports" eingetragen.
  - Regeländerungen aus der Gemini-Konsole werden sofort in [rules.md](rules.md) und [organization.md](organization.md) übernommen.
- Claude Code wartet nicht auf explizite Anweisung — Dokumentation ist **immer Teil der Aufgabe**.

## 8. Standard-Arbeitspaket: 10 zusammenhaengende Tasks
- Das Standard-Arbeitspaket fuer Claude Code umfasst **10 zusammenhaengende Tasks** pro Batch.
- Tasks werden in einer einzigen Session vollstaendig abgearbeitet (kein Teilabschluss).
- Nach jedem Batch: vollstaendiger Agent Report in [agents.md](agents.md).
- Task-Dateien werden unter `data/lore/tasks/TASK_{NR}_{Name}.md` abgelegt.

## 9. Ablage-Erzwingung (Mandatory)
- Jede Dateierstellung MUSS einen Pfad enthalten, der mit `data/lore/...` beginnt.
- Dateierstellungen im Root-Verzeichnis sind UNTERSAGT.
- Agenten müssen vor dem Schreiben prüfen, ob der Zielordner existiert, und ihn ggf. mit `os.makedirs` (oder entsprechendem Tool-Befehl) anlegen.

## 10. Standard-Testablauf für Virtual Player (Mandatory)

**Ziel:** Konsistente, wiederholbare Testrunden mit stabilen Ergebnissen.

### Pre-Austritt (vor jedem Test-Batch)
1. **Bugfixes sammeln:** Prioritäten nach Impact (Kritisch > Hoch > Mittel)
2. **Systematisch fixen:** Ein Bug nach dem anderen, mit Inline-Tests
3. **Git-Commit:** `git add . && git commit -m "[BUGFIX] ..."`

### Test-Ausführung (Standard 4-System-Batch)
**Pro System:** 10 Züge, 2 Sekunden Delay zwischen Zügen, mit Report-Speicherung
```bash
py -3 scripts/virtual_player.py \
  --module {MODULE} \
  --adventure {ADVENTURE} \
  --turns 10 \
  --save \
  --turn-delay 2.0
```

**Test-Reihenfolge (alphabetisch nach Impact-Kürzung):**
| # | System | Adventure | Priorität |
|---|--------|-----------|-----------|
| 1 | `cthulhu_7e` | `spukhaus` | Basis-Stabilität |
| 2 | `add_2e` | `goblin_cave` | Fantasy-Verhalten |
| 3 | `paranoia_2e` | `alpha_complex_reactor_audit` | KI-API-Stress |
| 4 | `shadowrun_6` | (default) | Moderne-Mechaniken |

### OK-Kriterien (ein Test bestanden ≡ alle erfüllt)
- ✓ **Kein Crash** (Bluescreen/Exception)
- ✓ **Alle 10 Züge durchgeführt** (keine Timeouts)
- ✓ **Report gespeichert** als JSON in `data/metrics/sim_*_*.json`
- ✓ **Tags emittiert:** Mindestens eine pro 3 Züge (ZEIT_VERGEHT, PROBE, INVENTAR, etc.)
- ✓ **Latenz stabil:** Durchschnitt < 5s (mit Delays) oder >2s deutet auf Systemlast hin

### Post-Ausführung (Daten-Sammlung)
1. **JSON-Reports** aus `data/metrics/sim_*_{TIMESTAMP}.json` prüfen
2. **Metriken-Zusammenfassung:**
   - Total Turns, Avg Latency, Response Avg Chars, Avg Sentences
   - Tags-Häufigkeit (Probe, Inventar, HP-Verlust, Fakt, Zeit)
   - Rules Warnings (Skill-Mismatches, Zielwert-Fehler)
3. **Findings dokumentieren:** Neue Bugs in agents.md unter "Report"

### Dokumentation (nach allen 4 Tests)
**Format:**
```
[YYYY-MM-DD HH:MM] | FROM: Claude Code | Virtual Player Batch {N}:
(1) Bugfixes: {Bugname} behoben (Änderungen in Dateien).
(2) Test Results: {System} ✅, {System} ⚠️ (API-Bug ab Z7), {System} ✅, {System} ✅.
(3) Metriken: Avg Latenz {X}ms, Total Tags {Y}, Rules Warnings {Z}.
(4) Neue Bugs: [Listung] → nächster Batch priorisieren.
```

## 11. TESTER MODE (wenn aktiviert: kontinuierliche Loop)

**Aktivierung:** User sagt "leg fest dass du im tester modus ... testen, reporten, fixen, testen"

**Verhalten:**
- Kontinuierliche **Test-Fix-Report-Loop** ohne Rückfragen
- Format pro Iteration: `[Test] → [Fix] → [Report] → [Next Test]`
- Folge dem Standard-Testablauf (rules.md Punkt 10)
- **Stopbedingungen:** User sagt "STOP" ODER alle Task-Bugs gelöst ODER 3x in Folge grün (3/4+ Tests ✅)

**Loop-Ablauf:**
```
1. TEST:   4-System-Batch (Cthulhu, AD&D, Paranoia, Shadowrun)
2. REPORT: agents.md aktualisieren mit Findings
3. FIX:    Top-3 Bugs aus Report bearbeiten (nach Impact)
4. COMMIT: git add . && git commit -m "[TESTER] Iteration N: ..."
5. REPEAT: Gehe zu 1
```

**Report-Format pro Iteration:**
```
[YYYY-MM-DD HH:MM] | TESTER MODE – Iteration N:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ TESTS:     Cthulhu {X}%, AD&D {X}%, Paranoia {X}%, Shadowrun {X}%
🔧 FIXES:     {Bug1}, {Bug2}, {Bug3}
📊 METRIKEN:  Avg Latenz {X}ms | Tags {Y} | Warnings {Z}
🎯 NÄCHSTE:   {Top-3 Bugs für nächste Iteration}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Exit Kriterium:** Wenn User "STOP" schreibt, sofort beenden + Final Summary

## 12. Coversion-Autopilot (Mandatory)
- Arbeitsverzeichnis fuer PDF-Konvertierung: `coversion/`
- Eingang: `coversion/workload/`
- Ausgabe: `coversion/finished/{system_id}/`
- Archiv fuer verarbeitete PDF-Dateien: `coversion/root/finished/`
- Claude Code ermittelt bei jeder neuen PDF-Datei automatisch, ob es ein neues oder bestehendes Regelsystem ist.
- Claude Code fuehrt immer Volltiefen-Verarbeitung aus (Extrakt -> Mapping -> Chunks -> Derived Rules -> Coverage/Digest/Candidates -> Ruleset/Preset -> Finalreport), sofern keine Teiltiefe explizit gefordert ist.
- Nach Abschluss wird das PDF aus dem Eingang nach `coversion/root/finished/` verschoben.
- Integrations-Output fuer Claude befindet sich ausschliesslich in `coversion/finished/`.

## 13. Feedback bei Auftragsvergabe (Mandatory)
- Bei jeder neuen Auftragsvergabe durch den User muss Claude Code den Auftrag explizit bestaetigen (gesehen + angenommen) und den unmittelbaren Start der Bearbeitung rueckmelden.
- Diese Rueckmeldung erfolgt kurz und ohne Rueckfrage, sofern keine technische Blockade vorliegt.

## 14. Conversion Volltiefe + QA-Gate (Mandatory)
- Bei PDF-Konvertierung sind immer alle 12 Phasen aus `Book_ARS_Tool.md` abzuarbeiten.
- "Fertig" ist ein Lauf nur dann, wenn fuer alle 12 Phasen ein Status vorliegt: `done` oder `na_with_reason`.
- Kein Ziel-Unterordner unter `data/lore/{system_id}/` darf unkommentiert leer bleiben.
- Wenn fuer einen Bereich keine belastbaren Inhalte im Quellbuch vorhanden sind, MUSS der Agent eine explizite N/A-Datei (`*_na_report.json`) mit Begruendung erzeugen.
- Vor Verschiebung nach `coversion/root/finished/` ist ein maschinenlesbarer QA-Report zu erzeugen (`indices/conversion_qa_report.json`) mit:
  - Phasenstatus 1-12
  - Ordner-Counts
  - Validation-Status `pass|fail`
- Bei `fail` darf kein Abschluss gemeldet werden; der Agent arbeitet selbststaendig nach, bis `pass` erreicht ist.

## 15. Entity-Index + 100%-Snippet Coverage (Mandatory)
- Bei jeder PDF-Conversion MUSS ein entitaetsbasierter Extraktionslauf erfolgen (nicht nur Fulltext/Phase-Chunks).
- Pflichtdatei: `indices/entity_index.json` im jeweiligen `data/lore/{system_id}/` Baum.
- Jeder Entity-Index-Eintrag MUSS enthalten:
  - `breadcrumb_path` (Format: `Hauptkapitel > Unterkapitel > Sektion`)
  - `entity_id`
  - `entity_type` (`npc` | `item` | `spell` | `monster` | `quest` | `location` | `rule` | `table` | `character_option`)
  - `name`
  - `source_pages`
  - `snippet_path`
  - `status` (`extracted` | `na_with_reason`)
- Reconciliation ist Pflicht:
  - Jede Index-Entity verweist auf eine existierende Snippet-Datei.
  - Jede Snippet-Datei ist im Index referenziert.
  - Abweichungen werden als `unresolved_entities` in `indices/conversion_qa_report.json` gelistet.
- Abschlusskriterium:
  - `coverage_percent = 100` ODER
  - vollstaendige `na_with_reason`-Dokumentation pro nicht extrahierbarer Entitaet.
- Tabellen-Normalisierung ist Pflicht:
  - Tabellen, die sich ueber mehrere Seiten erstrecken, muessen in jedem Teil-Snippet den Tabellen-Header erneut enthalten.
  - Ohne replizierten Header gilt der Tabellen-Snippet als unvollstaendig und darf nicht als `extracted` gezaehlt werden.
- Typ-spezifische Mindestfelder:
  - `spell`: Name, Kosten, Reichweite, Dauer, Effekt, Seitenreferenz
  - `monster`: Name, Stats, Angriffe, Sonderregeln, Seitenreferenz
  - `npc`: Rolle, Werte/Skills, Fraktion, Hook, Seitenreferenz
  - `item`: Name, Kosten, Gewicht/Slot, Regelwirkung, Seitenreferenz
  - `quest`: Einstieg, Ziel, Trigger, Belohnung, Fail-State, Seitenreferenz

## 16. Verwertbare Entitaets-Snippets (Strict Mandatory)
- Unverwertbare "Chaos"- oder Blind-Snippets sind untersagt. Reine Textzerlegung ohne Entitaetsbezug gilt nicht als gueltiger Extrakt.
- Fuer den Erstwurf sind mindestens diese Entitaetsklassen zu extrahieren:
  - `items`, `spells`, `vehicles`, `quests`, `npcs`, `monsters`, `lore`, `history`
  - zusaetzlich sinnvolle Klassen wie `factions`, `locations` wenn im Material vorhanden.
- Jedes Entitaets-Snippet MUSS enthalten:
  - Provenienz: `generated_at`, `generated_by`, `method`
  - Herkunft: `source_text.pdf`, `source_text.page`
  - Kontext: `breadcrumb_path`
  - Identifikation: `entity_id`, `entity_type`, `status`
  - Inhalt: kategorierelevante extrahierte Datenfelder + verwertbarer `excerpt`
  - Verweise: `_ref` (falls Querverweise erkannt werden)
- Abschluss (`pass`) ist nur zulaessig, wenn:
  - Reconciliation 100% erreicht ist,
  - keine verbotenen Blind-Snippets im Bundle verbleiben,
  - alle Pflicht-Entitaetsklassen entweder befuellt oder pro Klasse als `na_with_reason` dokumentiert sind.

## 17. Grafik-Extraktion in Production (Mandatory)
- Das Tool `pictureextract` ist als produktiver Pipeline-Baustein zu behandeln.
- Produktionsablage und Versionierung erfolgen unter `software/pictureextract/`:
  - aktive Version unter `software/pictureextract/production/{version}/`
  - archivierte Staende unter `software/pictureextract/archive/{version}/`
  - Produktionsstatus in `software/pictureextract/PRODUCTION_STATUS.json`
- Nach jeder PDF-Konvertierung MUSS die Original-PDF zusaetzlich im erzeugten Datenbundle abgelegt werden:
  - Ziel: `coversion/finished/{system_id}/source_pdf/{original_filename}.pdf`
  - Das ersetzt nicht das zentrale Archiv `coversion/root/finished/`, sondern ist zusaetzlich verpflichtend.
- Grafik-Extraktion erfolgt auf die Bundle-PDF und nicht auf temporaere Kopien.

