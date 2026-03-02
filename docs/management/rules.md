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