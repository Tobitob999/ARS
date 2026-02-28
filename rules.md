# ARS - Global Agent Rules (rules.md)

## 1. Zwei-Ebenen-Planung
- **Strategische Ebene (Roadmap):** Weitblick, Lore-Aufbau, Architektur. Review alle 3 Tage.
- **Kurzfristige Ebene (To-Dos):** Direkte Entwicklungsschritte für den nächsten Testlauf.

## 2. Kommunikations-Hub: agents.md (Stelle A)
`agents.md` ist der zentrale Einsatzbefehl und Rückmeldeort.
- **Lesepflicht:** Vor jeder Aktion `agents.md` prüfen.
- **Berichtspflicht:** Nach Abschluss einer Aufgabe Status in `agents.md` unter "Agent Reports" aktualisieren.
- **Format:** `[YYYY-MM-DD HH:MM] | FROM: [Agent] | [Status/Ergebnis]`

## 3. Strategie & Ideen: suggestions.md
- Agenten sind ausdrücklich ermutigt, Ideen für Lore, Gegenstände, NPCs oder Mechaniken hier zu deponieren.
- Diese werden im 3-Tages-Strategielauf gesichtet und in das Active Backlog übernommen.

## 4. Hintergrund-Tasks (Lore/Data)
- Datensammlungen (Menschen, Gebäude, Länder) werden als "Background-Threads" in `suggestions.md` vorbereitet und nach Freigabe in das `/data/` Verzeichnis überführt.

## 5. Schreib-Etikette
- Knapp, präzise, keine Floskeln.
- Bestehende Einträge nicht ohne Grund löschen.

## 6. Ablage-Erzwingung (Mandatory)
- Jede Dateierstellung MUSS einen Pfad enthalten, der mit `data/lore/...` beginnt.
- Dateierstellungen im Root-Verzeichnis sind UNTERSAGT.
- Agenten müssen vor dem Schreiben prüfen, ob der Zielordner existiert, und ihn ggf. mit `os.makedirs` (oder entsprechendem Tool-Befehl) anlegen.