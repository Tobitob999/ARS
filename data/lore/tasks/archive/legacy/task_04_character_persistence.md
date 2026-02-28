ARS Task 04: Charakter-Persistenz \& Zustands-Logik

Akteur: Claude Code

Kontext: Verwaltung von HP, Stabilität (Sanity) und Skills in ars\_vault.sqlite.



Zielsetzung

Implementiere eine robuste Logik, um den Zustand des Investigators (Spielercharakter) während des Spiels zu verändern und dauerhaft zu speichern.



Anforderungen

Character-Model: Erweitere core/mechanics.py, um einen Charakter aus der DB zu laden. Nutze das cthulhu\_7e.json Ruleset als Mapping-Grundlage .



Dynamic Updates: Implementiere Funktionen für:



update\_stat(stat\_name, change\_value): Für HP-Verlust oder Sanity-Drops .



mark\_skill\_used(skill\_name): (CoC-spezifisch) Markiert einen Skill für die Steigerungsphase am Ende des Abenteuers.



Trigger-Parsing: Der Orchestrator muss neue Tags erkennen:



`` → Zieht 3 Trefferpunkte ab.



`` → Lässt die Mechanik würfeln und zieht das Ergebnis von der Stabilität ab .



Auto-Save: Jeder Turn muss den aktuellen Zustand in data/ars\_vault.sqlite persistieren, damit das Spiel jederzeit fortgesetzt werden kann .



Abnahmekriterien

Ein Befehl wie `` im KI-Stream führt zu einer sofortigen Änderung in der SQLite-DB.



Beim Neustart mit --module cthulhu\_7e wird der letzte Stand des Charakters automatisch geladen.

