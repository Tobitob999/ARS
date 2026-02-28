# ARS - Projekthistorie (Tasks 01-09)

Dieses Dokument fasst alle abgeschlossenen Entwicklungs-Tasks des ARS-Projekts zusammen.

---

## Task 01: Projekt-Gerüst und Kern-Orchestrator

**Akteur:** Claude Code

**Kontext:** Aufbau eines lokalen Python-Projekts für einen KI-Rollenspiel-Simulator.

### Zielsetzung

Erstelle eine robuste, modulare Projektstruktur, die es ermöglicht, Regelsysteme (z.B. AD&D) und Welten als JSON/YAML-Module zu laden.

### Anforderungen

**Verzeichnisstruktur:** Erstelle folgende Ordner:

*   `/core`: Kernlogik (Orchestrator, Agenten-Definitionen).
*   `/modules/rulesets`: Für Regelsystem-Definitionen (z.B. cthulhu.json).
*   `/modules/worlds`: Für Lore-Datenbanken.
*   `/modules/adventures`: Für Plot-Graphen und Szenarien.
*   `/audio`: Komponenten für STT und TTS.
*   `/data`: Lokale SQLite-Datenbank für Charakter- und Session-Zustand .

**Main Entry Point (main.py):** Implementiere eine Basis-Klasse `SimulatorEngine`, die beim Start ein ausgewähltes Modul-Manifest lädt.

**Modul-Loader:** Schreibe eine Logik, die JSON-Dateien validiert und in ein internes Zustands-Objekt überführt .

**Environment:** Erstelle eine `.env.example` für API-Keys (Gemini, Claude) und lokale Modell-Pfade.

### Abnahmekriterien

*   Das Projekt lässt sich mit `python main.py --module cthulhu_v7` starten (auch wenn die Logik noch ein Platzhalter ist).
*   Alle Pfade sind relativ und für den lokalen Betrieb optimiert.

---

## Task 02: KI-Backend & Narrator-Orchestration

**Akteur:** Gemini 2.0 Flash (via Google AI Studio API)

**Kontext:** Integration des LLM als "Keeper" (Spielleiter) für Call of Cthulhu.

### Zielsetzung

Ersetze die Placeholder-Antworten in `orchestrator.py` durch echte KI-Aufrufe. Die KI muss den Spielzustand (Charakterwerte, Regeln, bisherige Story) kennen und darauf reagieren.

### Anforderungen

**API-Anbindung:** Erstelle `core/ai_client.py`. Nutze das `google-generativeai` SDK. Implementiere eine Methode, die Text-Streaming unterstützt .

**Keeper-Prompting:** Erstelle einen System-Prompt, der Gemini in die Rolle eines CoC-Keepers versetzt.

**Regel-Fokus:** Die KI soll nicht selbst würfeln, sondern die `MechanicsEngine` auffordern, wenn eine Probe nötig ist (Tools/Function Calling oder spezifische Tags).

**Atmosphäre:** Fokus auf Lovecraft’schen Horror, subtile Spannung und detaillierte Beschreibungen .

**Kontext-Management:**

*   Übermittle bei jedem Turn den aktuellen Charakter-Status aus der SQLite-DB.
*   Nutze Gemini's Context Caching, um das geladene `cthulhu_7e.json` und die Lore permanent im Gedächtnis zu behalten, ohne jedes Mal Token zu verschwenden .

**Integration:** Verbinde `orchestrator.py` so mit dem neuen Client, dass die Antwort des Keepers für die Sprachausgabe bereitgestellt wird.

### Abnahmekriterien

*   Ein Testlauf in der Konsole zeigt eine atmosphärische Beschreibung des Keepers.
*   Die KI erkennt, wenn der Spieler eine Aktion versucht (z.B. "Ich untersuche die Bibliothek"), und schlägt eine "Library Use"-Probe vor.

---

## Task 03: Lokale Audio-Pipeline Realisierung

**Akteur:** Claude Code

**Kontext:** Umwandlung der Audio-Stubs in performante, lokale KI-Dienste.

### Zielsetzung

Implementiere die lokale Sprachverarbeitung mit minimaler Latenz (< 500ms), um ein flüssiges Gespräch zu ermöglichen .

### Anforderungen

**STT (Speech-to-Text):**

*   Implementiere in `audio/stt_handler.py` die Faster-Whisper Bibliothek .
*   Integriere Silero VAD, um das Ende der Spielersprache automatisch zu erkennen, damit kein Tastendruck nötig ist .

**TTS (Text-to-Speech):**

*   Implementiere in `audio/tts_handler.py` das Modell Kokoro-82M (via ONNX oder direktem Python-Wrapper) .
*   Wichtig: Aktiviere Audio-Streaming. Die Sprachausgabe muss starten, sobald der erste Satz vom LLM generiert wurde .

**Interruption Logic:** Implementiere ein "Barge-in" Feature. Wenn der Spieler spricht (VAD-Signal), während die KI noch antwortet, muss die TTS-Ausgabe sofort stoppen.

**Dependencies:** Aktualisiere die `requirements.txt` mit allen notwendigen Paketen (faster-whisper, kokoro, sounddevice, pyaudio).

### Abnahmekriterien

*   `python main.py --voice` startet das Spiel im Sprachmodus.
*   Die Latenz zwischen "Spieler hört auf zu sprechen" und "KI fängt an zu sprechen" liegt bei einem schnellen lokalen Rechner unter 1 Sekunde.

---

## Task 04: Charakter-Persistenz & Zustands-Logik

**Akteur:** Claude Code

**Kontext:** Verwaltung von HP, Stabilität (Sanity) und Skills in `ars_vault.sqlite`.

### Zielsetzung

Implementiere eine robuste Logik, um den Zustand des Investigators (Spielercharakter) während des Spiels zu verändern und dauerhaft zu speichern.

### Anforderungen

**Character-Model:** Erweitere `core/mechanics.py`, um einen Charakter aus der DB zu laden. Nutze das `cthulhu_7e.json` Ruleset als Mapping-Grundlage .

**Dynamic Updates:** Implementiere Funktionen für:

*   `update_stat(stat_name, change_value)`: Für HP-Verlust oder Sanity-Drops .
*   `mark_skill_used(skill_name)`: (CoC-spezifisch) Markiert einen Skill für die Steigerungsphase am Ende des Abenteuers.

**Trigger-Parsing:** Der Orchestrator muss neue Tags erkennen:

*   `[HP_VERLUST: 3]` → Zieht 3 Trefferpunkte ab.
*   `[STABILITAET_VERLUST: 1d4]` → Lässt die Mechanik würfeln und zieht das Ergebnis von der Stabilität ab .

**Auto-Save:** Jeder Turn muss den aktuellen Zustand in `data/ars_vault.sqlite` persistieren, damit das Spiel jederzeit fortgesetzt werden kann .

### Abnahmekriterien

*   Ein Befehl wie `[HP_VERLUST: 2]` im KI-Stream führt zu einer sofortigen Änderung in der SQLite-DB.
*   Beim Neustart mit `--module cthulhu_7e` wird der letzte Stand des Charakters automatisch geladen.

---

## Task 05: Archivist & Langzeit-Gedächtnis

### Zielsetzung

Verwandle den Simulator in eine persistente Welt. Der Keeper muss sich an Ereignisse von vor 100 Runden erinnern, ohne das Token-Limit zu sprengen oder die Latenz zu erhöhen.

### Anforderungen

**1. Explizites Context Caching (Performance)**

Implementiere in `core/ai_backend.py` eine Logik für Gemini Explicit Caching:

*   **Static Cache:** Erstelle einen Cache für das `cthulhu_7e.json` Regelwerk. Da sich Regeln selten ändern, spart dies bei jedem Turn Rechenzeit.
*   **Adventure Cache:** Cache die Lore-Beschreibungen des aktuellen Abenteuers (Orte, NPCs).
*   **TTL-Management:** Setze eine Time-to-Live (TTL) von mind. 2 Stunden für aktive Sessions.

**2. Die "Chronik" (Zusammenfassung)**

Erstelle eine Klasse `Archivist` in `core/memory.py`:

*   **Trigger:** Nach jeweils 15 Runden (aus `session_turns`) soll die KI eine kurze, faktische Zusammenfassung der bisherigen Ereignisse erstellen ("Chronik").
*   **Injektion:** Diese Chronik ersetzt die alten Einzel-Turns im Prompt. So bleibt der Kontext schlank, aber der "Rote Faden" erhalten.

**3. World-State-Tracking (Fakten)**

Erweitere die SQLite-Logik, um einen World State (JSON-Blob) zu speichern:

*   Die KI kann über ein neues Tag `[FAKT: {"key": "value"}]` Fakten festschreiben (z.B. `{"miller_tot": true}`).
*   Dieser Zustand wird bei jedem Turn als "Aktuelle Fakten" mitgesendet, um Widersprüche zu vermeiden (z.B. dass ein toter NPC plötzlich wieder spricht).

### Abnahmekriterien

*   Beim Start einer Session wird geprüft, ob ein passender Cache existiert, und dieser wird geladen.
*   Nach 15 Runden Spielzeit erscheint in den Logs ein "Chronicle Update", das die Story zusammenfasst.
*   Der Keeper "weiß" auch nach einem Neustart, welche NPCs bereits getroffen wurden (via World State).

---

## Task 06: Abenteuer-Modul "Das Spukhaus"

**Akteur:** Gemini 2.5 Flash

**Kontext:** Erstellung der Datenbasis für ein Call of Cthulhu Einstiegs-Szenario.

### Zielsetzung

Erstelle eine `adventure_spukhaus.json` und eine dazugehörige Lore-Datei, die alle Informationen für den Keeper enthält.

### Anforderungen

**Szenario-Struktur:** Erstelle ein JSON-Objekt für `/modules/adventures/spukhaus.json`:

*   **hook:** Der Einstieg (Ein Hilferuf eines sterbenden Freundes).
*   **locations:** Mindestens 3 Orte (Das Krankenhaus, die Bibliothek von Arkham, das alte Corbitt-Haus).
*   **npcs:** Profile für wichtige Charaktere (Rupert Merriweather, der Geist von Corbitt).
*   **clues:** Hinweise, die an Orten gefunden werden können.

**Keeper-Lore:** Erstelle einen ausführlichen Text-Block "Hintergrund für den Spielleiter". Dieser enthält das dunkle Geheimnis, das der Spieler erst am Ende erfahren darf.

**Integration:** Das JSON muss so aufgebaut sein, dass der `ModuleLoader` aus Task 01 es einlesen kann.

---

## Task 07: Investigator-Erstellung & DB-Injektion

**Akteur:** Claude Code

**Kontext:** Vorbereitung eines Test-Charakters in `ars_vault.sqlite`.

### Zielsetzung

Erstelle einen vollständigen CoC 7e Investigator und speichere ihn als Start-Zustand in der Datenbank.

### Anforderungen

**Investigator-Profil:** Erstelle einen Charakter (z.B. Dr. Silas Moore, Professor an der Miskatonic University).

**Werte-Generierung:** Berechne die Attribute und Skills gemäß `cthulhu_7e.json` (z.B. Bibliotheksnutzung 70%, Psychologie 50%, HP 12, SAN 60).

**Automatisierung:** Schreibe ein Hilfsskript `scripts/create_test_char.py`, das diesen Charakter per SQL direkt in die Tabelle `characters` deiner `ars_vault.sqlite` schreibt.

**Verknüpfung:** Stelle sicher, dass beim Start von `main.py --module cthulhu_7e` dieser Charakter als Standard geladen wird.

---

## Task 08: Master Keeper Persona & Interaktions-Design

**Akteur:** Gemini 2.5 Flash

**Kontext:** Feinschliff der KI-Persönlichkeit.

### Zielsetzung

Entwickle den ultimativen System-Prompt, der alle technischen Funktionen deines Frameworks nutzt.

### Anforderungen

**Rollen-Definition:** Du bist ein erfahrener Call of Cthulhu Keeper. Dein Stil ist atmosphärisch, düster und reagiert extrem flexibel auf Spielerideen ("Yes, and...").

**Protokoll-Einhaltung:** Integriere strikte Anweisungen für:

*   **Würfeln:** Fordere Proben an mit `[PROBE: <Fertigkeit> | <Zielwert>]`.
*   **Konsequenzen:** Ziehe HP oder SAN ab mit `[HP_VERLUST: <n>]` oder `[STABILITAET_VERLUST: <ndm>]`.
*   **Gedächtnis:** Halte Fakten fest mit `[FAKT: {"key": "value"}]`.

**Sprach-Optimierung:** Kurze Sätze für flüssiges TTS. Warte nach Beschreibungen immer auf die Reaktion des Spielers.

**Keine Metasprache:** Sprich niemals über Regeln oder Technik, außer innerhalb der Tags.

---

## Task 09: GUI-Implementierung "The Investigator's Desk"

**Kontext:**

Das ARS-Backend ist stabil. Wir benötigen nun ein atmosphärisches Frontend, das die Immersion eines Lovecraft-Horrorspiels der 1920er Jahre unterstützt. Die Wahl des Frameworks fällt auf CustomTkinter, um moderne Dark-Mode-Ästhetik mit einfacher Python-Integration zu verbinden.

### 1. Architektur & Datei-Struktur

*   **Neues Modul:** Erstelle `ui/dashboard.py` mit der Klasse `InvestigatorDashboard`.
*   **Asynchronität:** Die GUI muss in einem separaten Thread oder via `asyncio.loop` laufen, um den Orchestrator und die VoicePipeline nicht zu blockieren.
*   **Integration:** Erweitere `main.py`, um die GUI optional via `--gui` Flag zu starten.

### 2. Visuelles Design (Thema & Layout)

*   **Ästhetik:** Dark-Mode (Hintergrund: `#1A1A1A`). Akzentfarben: Pergament (`#F5F5DC`), Blutrot (`#8B0000`) für Warnungen/HP.
*   **Schriftarten:** Serif (z. B. "Times New Roman") für den Keeper-Text; Monospace (z. B. "Courier") für technische Statusmeldungen.
*   **Layout (4-Säulen-Grid):**
    *   **Links (Investigator Stats):** Vertikale Progress-Bars für HP (rot), SAN (blau), MP (violett). Anzeige von Name (Dr. Silas Moore), Beruf (Professor), INT (85) und EDU (90).
    *   **Mitte (Narrative Feed):** Ein großes `CTkTextbox`-Element. Text wird mit einem "Typewriter-Effekt" (verzögerte Zeichenausgabe) angezeigt, um die TTS-Generierung visuell zu kaschieren.
    *   **Rechts (Case Folder):** Ein Bereich für Handouts. Nutze `PIL` (Pillow), um Bilder oder Dokument-Texte aus `spukhaus.json` darzustellen.
    *   **Unten (Console & Status):** Ein pulsierender Indikator für das `silero-vad` Signal (Grün = hört zu, Grau = Stille).

### 3. Funktionale Logik & Data Binding

*   **Live-Update:** Binde die UI an `data/ars_vault.sqlite`. Sobald der Orchestrator ein Zustands-Tag (z. B. `<SUB_HP:2>`) verarbeitet, muss die UI den entsprechenden Balken sofort aktualisieren.
*   **Tag-Filtering:** Der Narrative Feed muss alle technischen Tags (z. B. `<ROLL:LibraryUse>` oder `<FACTS:...>`) aus dem Text entfernen, bevor sie angezeigt werden.
*   **Handout-Trigger:** Implementiere einen Event-Handler. Wenn der Keeper ein Handout erwähnt (z. B. `handout_1`), soll das entsprechende Asset automatisch im rechten Bereich eingeblendet werden.
*   **Barge-in Button:** Ein manueller "Stopp"-Button, der das `interrupt_signal` an die TTS-Engine sendet, falls die automatische VAD-Erkennung versagt.

### 4. Abnahmekriterien

*   Start von `main.py --gui --module cthulhu_7e` öffnet das Dashboard.
*   Die Stats von Dr. Silas Moore werden korrekt aus der DB geladen.
*   Der Keeper-Text erscheint im Narrative Feed, ohne technische Tags anzuzeigen.
*   Der VAD-Status visualisiert Echtzeit-Spracherkennung.

### Nächste Schritte für dich (Claude):

*   Erstelle die Datei `ui/dashboard.py`.
*   Passe `core/orchestrator.py` an, um Signale (Text, Stats, Handouts) an die UI-Instanz zu senden.
*   Teste die Darstellung mit dem "Spukhaus"-Szenario.