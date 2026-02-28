Task 01: Projekt-Gerüst und Kern-Orchestrator

Akteur: Claude Code

Kontext: Aufbau eines lokalen Python-Projekts für einen KI-Rollenspiel-Simulator.



Zielsetzung

Erstelle eine robuste, modulare Projektstruktur, die es ermöglicht, Regelsysteme (z.B. AD\&D) und Welten als JSON/YAML-Module zu laden.



Anforderungen

Verzeichnisstruktur: Erstelle folgende Ordner:



/core: Kernlogik (Orchestrator, Agenten-Definitionen).



/modules/rulesets: Für Regelsystem-Definitionen (z.B. cthulhu.json).



/modules/worlds: Für Lore-Datenbanken.



/modules/adventures: Für Plot-Graphen und Szenarien.



/audio: Komponenten für STT und TTS.



/data: Lokale SQLite-Datenbank für Charakter- und Session-Zustand .



Main Entry Point (main.py): Implementiere eine Basis-Klasse SimulatorEngine, die beim Start ein ausgewähltes Modul-Manifest lädt.



Modul-Loader: Schreibe eine Logik, die JSON-Dateien validiert und in ein internes Zustands-Objekt überführt .



Environment: Erstelle eine .env.example für API-Keys (Gemini, Claude) und lokale Modell-Pfade.



Abnahmekriterien

Das Projekt lässt sich mit python main.py --module cthulhu\_v7 starten (auch wenn die Logik noch ein Platzhalter ist).



Alle Pfade sind relativ und für den lokalen Betrieb optimiert.

