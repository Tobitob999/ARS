# ARS — Agent Coordination Dashboard

**Zuletzt aktualisiert:** 2026-03-02 (Session 4)
**Projektstatus:** In Betrieb — 5 Regelsysteme, Budget-Injection bis 500K Tokens, TechGUI 8 Tabs + Reset

**Speicherort:** `docs/management/` — zentraler Management-Ordner

### Verknuepfte Dokumente

| Dokument | Zweck |
|----------|-------|
| [organization.md](organization.md) | Rollen, Verantwortlichkeiten, Organigramm |
| [rules.md](rules.md) | Globale Agenten-Regeln, Kommunikations-Protokoll |
| [suggestions.md](suggestions.md) | Strategische Planung, Feature-Brainstorming |
| [WCR.md](WCR.md) | World Creation Rules — JSON-Schema fuer Content-Erstellung |
| [Book_ARS_Tool.md](Book_ARS_Tool.md) | Buch-Konvertierungs-Pipeline (12 Phasen) |

---

## Projektstatus

| Komponente | Status | Anmerkung |
|------------|--------|-----------|
| Core Engine | fertig | Regelwerk laden, validieren, Wuerfelsystem |
| Rules Engine | fertig | 3-Schicht: Index, Pre-Injection, Post-Validation, Budget bis 2M Zeichen (~500K Tokens), Auto-Priority, Fulltext-Scan |
| KI-Backend (Gemini) | fertig | Gemini 2.5 Flash, Streaming, History, System-Persona, Kernregeln im System-Prompt |
| STT (Faster-Whisper) | fertig | Whisper base CPU, Silero VAD |
| TTS (Piper) | fertig | de_DE-thorsten-medium, 10 Stimmen |
| Voice Pipeline | fertig | STT->Gemini->TTS, Barge-in optional |
| TechGUI | fertig | tkinter, 8 Tabs, Dark Theme, Budget-Slider (bis 2M), Session-Reset |
| Charakter-System | fertig | SQLite-Persistenz, nicht-numerische Stats (Paranoia) |
| Cthulhu 7e | fertig | d100, roll-under, SAN |
| AD&D 2e | fertig | d20, roll-under, THAC0, Klassen |
| Mad Max | fertig | d100, Survival |
| Paranoia 2e | fertig | d20, roll-under, Clones, Treason, 451 Lore-Chunks |
| Shadowrun 6e | fertig | d6 Pool, Edge, Matrix, 2036 Lore-Chunks |
| Lore-Daten | fertig | ~5000+ Dateien, 3-Verzeichnis-Scan (chunks/chapters/fulltext), Auto-Priority-Promotion |
| Abenteuer-Content | minimal | spukhaus, goblin_cave, 4x Paranoia Adventures |

---

## Technische Architektur

```
main.py ── SessionConfig (core/session_config.py) ── Presets (modules/presets/)
  └── SimulatorEngine (core/engine.py)
        ├── DiscoveryService (core/discovery.py) — Asset-Manifest (6 Modultypen)
        ├── ModuleLoader → cthulhu_7e.json / add_2e.json
        ├── Setting/Keeper/Extras Loader → modules/settings/, keepers/, extras/
        ├── GeminiBackend (core/ai_backend.py) — Keeper-KI (dynamischer Prompt via SessionConfig)
        │     ├── Kernregeln-Block (_build_core_rules_block → System-Prompt, bis 2M Zeichen)
        │     ├── AdventureManager-Kontext (Location, Flags → Prompt)
        │     ├── Setting-Block (Welt, Epoche, Voelker → Prompt)
        │     ├── Keeper-Detail-Block (Erzaehlstil, Philosophie → Prompt)
        │     └── Extras-Block (Zusatzregeln → Prompt)
        ├── CharacterManager (core/character.py) — SQLite
        ├── Orchestrator (core/orchestrator.py) — Game Loop
        │     ├── AdventureManager (core/adventure_manager.py) — Story Logic
        │     └── Archivist (core/memory.py) — Chronik + World State
        └── VoicePipeline (audio/pipeline.py)
              ├── STTHandler (audio/stt_handler.py) — Faster-Whisper + Silero VAD
              └── TTSHandler (audio/tts_handler.py) — Piper → Kokoro → pyttsx3
```

**TTS Backend-Hierarchie:**
1. Piper TTS — `de_DE-thorsten-medium` (22050 Hz, ~63 MB Cache)
2. Kokoro-82M — Englisch-Fallback (`af_heart`, en-us, 24000 Hz, ~310 MB Cache)
3. pyttsx3 — Windows SAPI
4. stub — stdout

---

## Aktive To-Dos (nach Rolle)

### Strategic Lead (Gemini)
- [ ] Konsistenz-Scan der `/data/lore/` Struktur auf Duplikate
- [ ] Erstellung eines High-Level Narrative Arc fuer das "Spukhaus" in `strategic_protocol.md`
- [ ] Risiko-Assessment technischer Schulden in `suggestions.md`

### Lead Developer (Claude Code)
- [x] Implementierung des Autotesters in `scripts/virtual_player.py`
- [x] Einbau der Monolog-Sperre (max. 3 Saetze) und Hook-Zwang in `core/ai_backend.py`
- [x] Setup eines automatisierten Metrics-Loggers fuer Simulationslaeufe

### Content Specialist (Codex)
- [ ] Expansion des MU-Personal-Katalogs in `/data/lore/university/`
- [ ] Erstellung der Quartiers-Daten fuer das "North End" in `/data/lore/society/`
- [ ] Aufbau eines 1920er Preisverzeichnisses in `/data/lore/items/arkham_economy.json`

### Virtual Player (AI-Script)
- [ ] Durchfuehrung des ersten 10-Zuege-Simulationstests
- [ ] Stress-Test der Barge-in Funktionalitaet (Unterbrechung des Keepers)
- [ ] Verifikation der [ROLL] Tag-Verarbeitung in den Logs

### Human Lead (User)
- [ ] Validierung der VAD-Hardware-Kompatibilitaet
- [ ] Qualitatives Feedback zur Natuerlichkeit der Monolog-Sperre
- [ ] Finaler Review und Freigabe der 3-Tage-Roadmap

### Weitere offene Tasks
- [ ] **Spieltest:** Paranoia 2E mit vollem Regel-Budget
- [ ] **Spieltest:** Shadowrun 6E mit vollem Regel-Budget
- [ ] **Spieltest:** AD&D 2E mit vollem Regel-Budget
- [ ] **Optimierung:** Shadowrun Lore-Coverage erhoehen (22% → Ziel 60%)
- [ ] **Content:** Mehr Shadowrun-Content (Adventures, Characters)
- [ ] **Feature:** Charaktererstellung im Voice-Modus
- [ ] **Feature:** Wuerfelergebnisse in GUI visualisieren
- [ ] **Feature:** Lore-Budget Slider (getrennt von Rules-Budget)

---

## Abgeschlossene Aufgaben

- [x] XXXXL Welle 12 (Tasks 45-48) abgeschlossen. Mythos-Götter, Buch-Exzerpte und taktische Encounter-Logik sind im System.
- [x] XXXXL Welle 11 (Tasks 41-44) abgeschlossen. Forensik-Regeln, Kommunikations-Netz und Stadtregister sind einsatzbereit.
- [x] XXXXL Welle 10 (Tasks 37-40) abgeschlossen. Wildnis-Atlas, Migrations-Viertel und Prohibitions-Struktur sind jetzt Teil der Welt.
- [x] XXXXL Welle 09 (Tasks 33-36) abgeschlossen. Sanatorium, Familien-Genealogie und Justiz-System sind im System.
- [x] XXXXL Welle 08 (Tasks 29-32) abgeschlossen. Architektur-Datenbank und Raum-Atmosphäre sind für den Orchestrator verfügbar.
- [x] XXXXL Welle 07 (Tasks 25-28) abgeschlossen. Orne Library inkl. Katalog, Personal und Restricted Section ist vollständig dokumentiert.
- [x] XXXXL Welle 06 (Tasks 21-24) abgeschlossen. Wettersimulation, Popkultur und NPC-Generatortabellen sind integriert.
- [x] XXXXL Welle 05 (Tasks 17-20) abgeschlossen. Kriminalitäts-Archiv, Wirtschaftssystem und Verkehrsnetz sind integriert.
- [x] XXXXL Welle 04 (Tasks 13-16) abgeschlossen. Medizinische Archive, Uni-Fakultäten und Regional-Bestiarium sind live.
- [x] XXXXL Welle 03 (Tasks 9-12) abgeschlossen. Magie-System, Regional-Atlas und Ambient-Events sind einsatzbereit.
- [x] Lore-Welle 02 (Tasks 5-8) abgeschlossen. Okkult-Daten und Social-Web integriert.
- [x] Lore-Welle 01 (Laufzettel 01) abgeschlossen. NPCs, Orte, Items für "Spukhaus" erstellt.
- [x] Projektstruktur & Module aufsetzen
- [x] Gemini-Backend mit Streaming
- [x] Faster-Whisper STT + Silero VAD
- [x] Kokoro-82M TTS (ONNX, lokal)
- [x] Piper TTS (Deutsch, de_DE-thorsten-medium)
- [x] VoicePipeline mit Barge-in Monitor
- [x] Barge-in deaktivierbar (`--no-barge-in`) für Lautsprecherbetrieb
- [x] Audio-Diagnose-Script (`scripts/test_audio.py`)
- [x] Keeper-Test-Script (`scripts/test_keeper.py`)
- [x] Kokoro Endless-Retry-Bug behoben
- [x] Kokoro Chunk-Playback-Bug behoben (unhörbar → non-blocking sd.play)
- [x] Barge-in False Positive (Echo) reduziert (Threshold 0.90, 2 consecutive)
- [x] CustomTkinter GUI Dashboard gebaut
- [x] SQLite Charakter-Persistenz
- [x] Piper TTS als primäres Backend in tts_handler.py integriert (de_DE-thorsten, auto-download)
- [x] `--no-barge-in` Flag durch main.py → engine.py → pipeline.py
- [x] Barge-in Bugfixes: Cooldown 15 Chunks, Threshold 0.90, Consecutive=2
- [x] Kokoro Endless-Retry-Bug: `_kokoro_load_failed` Flag
- [x] .env: WHISPER_MODEL, STT_LANGUAGE, PIPER_VOICE, PIPER_SPEED konfigurierbar
- [x] requirements.txt: piper-tts, silero-vad hinzugefügt
- [x] TASK 50/51: Diagnostic Center (`scripts/tech_gui.py`) — Audio-Panel, AI-Backend-Panel, Engine-State mit Würfelproben
- [x] TASK 06: Adventure Engine — Schema, AdventureManager, Flag-System, Location-Tracking, Orchestrator-Integration
- [x] TASK 52/53: Diagnostic Center Erweiterung — Story & State Tab (Szenario-Waehler, Teleport, Flag-Editor), Memory Engine Tab (Turns, Chronik, World State, Context-Preview, Summary-Trigger)
- [x] TASK 06 (erweitert): DiscoveryService, Flag-Persistenz via SQLite, Location-Kontext-Injektion in Gemini-Prompt, Template-Abenteuer

---

## Startbefehle

```powershell
# TechGUI (empfohlen):
py -3 main.py --module cthulhu_7e --techgui
py -3 main.py --module paranoia_2e --techgui
py -3 main.py --module shadowrun_6 --techgui

# CLI mit Stimme (Lautsprecher):
py -3 main.py --module cthulhu_7e --adventure spukhaus --voice --no-barge-in

# CLI mit Stimme (Kopfhoerer, Barge-in aktiv):
py -3 main.py --module cthulhu_7e --adventure spukhaus --voice

# Preset + Override:
py -3 main.py --module cthulhu_7e --preset coc_classic --difficulty hardcore

# Audio-Diagnose:
py -3 scripts/test_audio.py --list
```

---

## Konfiguration (.env)

```
GEMINI_API_KEY=...
PIPER_VOICE=de_DE-thorsten-medium   # oder thorsten-high, kerstin-medium, ...
PIPER_SPEED=1.0
KOKORO_VOICE=af_heart               # Englisch-Fallback
TTS_LANG=en-us
```

---

## Bekannte Einschränkungen

- **Barge-in + Lautsprecher:** Mikrofon nimmt Lautsprecher auf → VAD 0.91–0.96 → False Positive.
  Workaround: `--no-barge-in`. Echter Fix: Kopfhörer verwenden.
- **STT-Qualität:** Whisper `base` CPU macht gelegentlich Transkriptionsfehler bei undeutlicher Aussprache.
- **Piper Stimme:** `thorsten-medium` klingt synthetisch; `thorsten-high` besser (~130 MB).

---

## Codex Content-Richtlinien (Ruleset & Adventure Schema)

### Schema-Versionierung (PFLICHT)

**Jede JSON-Datei in `modules/` MUSS `schema_version` tragen** (Semver: `"MAJOR.MINOR.PATCH"`).
- Bei Rulesets: in `metadata.schema_version`
- Bei allen anderen Modulen: als Top-Level-Feld `"schema_version"`
- **Agents die Module aendern MUESSEN die Version bumpen:**
  - MAJOR: Felder umbenannt/entfernt, Struktur gebrochen
  - MINOR: Neue optionale Felder hinzugefuegt
  - PATCH: Inhaltliche Korrekturen, Tippfehler

### Universelles Regelgeruest (Skeleton)

Rulesets nutzen ein **universelles Skeleton** mit ~25 optionalen Sektionen (siehe [WCR.md](WCR.md) Sektion 3). Nur 4 Sektionen sind Pflicht (metadata, dice_system, characteristics, skills). Alle anderen werden vom KI-Backend im System-Prompt verwendet, wenn vorhanden.

Fuer die **vollstaendige Konvertierung eines Regelbuchs** siehe [Book_ARS_Tool.md](Book_ARS_Tool.md) (12-Phasen-Pipeline).

### Pflichtfelder fuer Rulesets (`modules/rulesets/*.json`)

Jedes Ruleset MUSS diese 4 Top-Level-Keys haben, sonst schlaegt die Engine-Validierung fehl:

| Key | Pflichtfelder | Beschreibung |
|-----|---------------|--------------|
| `metadata` | `name`, `version`, `system`, `schema_version` | Name des Systems, Edition, ID, Schema-Version |
| `dice_system` | `default_die`, `success_levels` | Wuerfeltyp (`"d20"`, `"d100"`) + Schwellen (`critical`, `fumble`, `extreme`, `hard`) |
| `characteristics` | (mind. 1 Eintrag) | Attribute mit `label`, `roll`, `multiplier` |
| `skills` | (mind. 1 Eintrag) | Fertigkeiten mit `base` Wert |

**Optionale metadata-Felder** (fuer Prompt-Generierung):
- `game_master_title`: z.B. `"Dungeon Master"` (Default: `"Spielleiter"`)
- `player_character_title`: z.B. `"Abenteurer"` (Default: `"Investigator"`)

**dice_system.default_die** Format: `[N]dX` — z.B. `"d20"`, `"d100"`, `"2d6"`

**dice_system.success_levels** Schwellen:
```json
{
  "critical": 1,      // Wurf <= critical → Kritischer Erfolg
  "extreme": 0.25,    // Wurf <= target * extreme → Extremer Erfolg
  "hard": 0.5,        // Wurf <= target * hard → Harter Erfolg
  "fumble": 20        // Wurf >= fumble → Patzer
}
```

### Pflichtfelder fuer Adventures (`modules/adventures/*.json`)

- `id`: Eindeutige ID (z.B. `"goblin_cave"`)
- `name`: Anzeigename
- `locations`: **Array** von Location-Objekten (mind. 1). Jedes Objekt MUSS ein `id`-Feld haben.
- `npcs`: **Array** von NPC-Objekten. Jedes Objekt MUSS ein `id`-Feld haben.

**WICHTIG:** `locations` und `npcs` sind Arrays (`[{...}, {...}]`), KEINE Dicts/Maps (`{"key": {...}}`).

Optionale Felder: `items_loot`, `flags`, `clues`, `events`, `handouts`, `resolution`.
Siehe `modules/adventures/template.json` als vollstaendiges Beispiel.

### Settings (`modules/settings/*.json`)

Welt-Beschreibung: Geographie, Kultur, Technologie, Voelker, Waehrung, Epoche.
Pflichtfelder: `id`, `name`, `compatible_rulesets`, `epoch`, `geography`, `atmosphere`.

### Keepers (`modules/keepers/*.json`)

Spielleiter-Persoenlichkeit: Ton, Erzaehlstil, Kampfbeschreibung, NPC-Stimmen.
Pflichtfelder: `id`, `name`, `tone`.

### Extras (`modules/extras/*.json`)

Optionale Erweiterungen (Atmosphaere-Pakete, Spielmodus-Modifier, Regel-Erweiterungen).
Pflichtfelder: `id`, `name`, `type` (`atmosphere` | `game_mode` | `rule_extension`), `prompt_injection`.
`compatible_rulesets`: Array oder `null` (universal).

### Characters (`modules/characters/*.json`)

Charakter-Templates mit Attributen, Fertigkeiten, Ausruestung. An Regelsystem gebunden.
Pflichtfelder: `id`, `name`, `compatible_rulesets`, `archetype`.
`characteristics` nutzt die Attribute des Ziel-Regelsystems.
`derived_stats` muss mindestens `HP` enthalten.
Optional: `level`, `background`, `traits`, `appearance`, `equipment`, `skills`, `notes`.

### Parties (`modules/parties/*.json`)

Platzhalter fuer Multi-Charakter-Unterstuetzung. Fasst mehrere Characters zusammen.
Pflichtfelder: `id`, `name`, `members`.
`members` referenziert `character_id`s aus `modules/characters/`.

### Presets (`modules/presets/*.json`)

Gueltige Felder: `ruleset`, `adventure`, `setting`, `keeper`, `extras`, `character`, `party`, `difficulty`, `atmosphere`, `keeper_persona`, `language`, `temperature`.

- `setting` und `keeper` referenzieren Module aus `modules/settings/` bzw. `modules/keepers/`
- `character` referenziert ein Charakter-Template aus `modules/characters/`
- `party` referenziert ein Party-Modul aus `modules/parties/`
- Wenn `setting` gesetzt → ueberschreibt `atmosphere`
- Wenn `keeper` gesetzt → ueberschreibt `keeper_persona`
- `extras` ist ein Array von Extra-IDs

Gueltige `difficulty` Werte: `"easy"`, `"normal"`, `"heroic"`, `"hardcore"`.

**Encoding:** UTF-8 (mit oder ohne BOM). Engine liest `utf-8-sig`.

### Beispiel-Referenz

- Cthulhu: `modules/rulesets/cthulhu_7e.json` (d100, roll-under, SAN)
- AD&D: `modules/rulesets/add_2e.json` (d20, roll-under, THAC0)
- Adventure: `modules/adventures/template.json` (vollstaendiges Schema)
- Setting: `modules/settings/cthulhu_1920.json`, `modules/settings/forgotten_realms.json`
- Keeper: `modules/keepers/arkane_archivar.json`, `modules/keepers/epischer_barde.json`
- Extras: `modules/extras/noir_atmosphere.json`, `modules/extras/survival_mode.json`
- Character: `modules/characters/coc_investigator.json`, `modules/characters/add_fighter.json`
- Party: `modules/parties/_template.json`
- Preset: `modules/presets/coc_classic.json`

---

## Agent Reports

[2026-02-27 13:31] | FROM: Codex | Alle in `core/` erstellten Lore-JSONs in die regelkonforme Struktur `data/lore/...` verschoben und thematisch einsortiert (u. a. `npcs`, `locations`, `items`, `organizations`, `spells`, `mythos_entities`, `technology`). `core/` enth�lt keine JSON-Dateien mehr.
[2026-02-27 17:47] | FROM: Codex | Nur die Spielinhalt-Markdown-Dateien aus dem Hauptordner (`arkham_rumors`, `global_events_1925`, `famous_cases`, `witch_trials_archive`, alle `*_excerpt`) in JSON konvertiert, in `data/lore/...` einsortiert und die 12 konvertierten `.md` aus dem Root entfernt.
[2026-02-27 17:49] | FROM: Codex | Schema-Standardisierung f�r 12 aus Markdown konvertierte Lore-JSONs umgesetzt: einheitliche Felder (`schema_version`, `category`, `tags`, `summary`, `source_text`, `mechanics`), `content_markdown` entfernt, Excerpt-Effekte nach `mechanics` �berf�hrt.
[2026-02-27 18:12] | FROM: Codex | Korrektur Zeitstempel: Schema-Standardisierung der 12 konvertierten Lore-JSONs best�tigt abgeschlossen.
[2026-02-27 18:14] | FROM: Codex | Alte Task-Dateien aufger�umt: `lore_tasks.md` sowie Legacy-`task*.md` aus `finished/` nach `data/lore/tasks/archive/legacy/` verschoben und Dateiname `task_04_character_persistence.md.md` auf `task_04_character_persistence.md` bereinigt. `finished/` ist nun leer.
[2026-02-27 18:20] | FROM: Codex | Lore-Datenfundus kreativ erweitert: pro bestehender Lore-JSON (ohne Tasks) wurde eine neue eigenst�ndige `*_micro_01.json` mit kurzem Hook + klassenbezogenem Attribut erstellt (171 neue Inhalte). Zuvor erzeugte Copy-Varianten wurden aus den Content-Ordnern entfernt/ausgelagert. Zus�tzlich `data/lore/index.json` als zentrale Auflistung (Kategorien, Counts, Pfade, Generated-Flag) erstellt.
[2026-02-27 18:24] | FROM: Codex | Zus�tzliche Inhaltswelle erstellt: pro Basisdatei eine weitere eigenst�ndige `*_micro_02.json` (171 neue Snippets, kreative Hooks + klassenbezogene Felder). `data/lore/index.json` auf v1.2 aktualisiert; aktiver Lore-Bestand jetzt 513 Dateien, davon 342 generiert.
[2026-02-27 18:29] | FROM: Codex | Rules-konforme Content-Erweiterung fortgesetzt: Welle 3 (`*_micro_03.json`) mit 171 neuen, eigenst�ndigen Snippets erstellt (keine Kopien), inkl. kategoriespezifischer Attribute und Hooks. `data/lore/index.json` auf v1.3 aktualisiert; aktiver Lore-Bestand jetzt 684 Dateien, davon 513 generiert.
[2026-02-27] | FROM: Claude Code | TASK 06 erweitert implementiert: (1) `core/discovery.py` — DiscoveryService scannt `modules/rulesets/` und `modules/adventures/`, baut Manifest mit Metadata (Titel, Version, Location/NPC/Clue/Flag-Counts), Print-Funktion beim Engine-Start. (2) `core/adventure_manager.py` — `set_flag()` persistiert jetzt sofort via Archivist in SQLite `world_state` (flag:-Prefix). `set_archivist()` koppelt den Archivist. (3) `core/ai_backend.py` — `_build_contents()` injiziert jetzt neben Archivist-Kontext auch `AdventureManager.get_location_context()` in jeden Turn. Gemini weiss bei jeder Antwort den aktuellen Ort, Atmosphaere, NPCs, Clues, Exits. (4) `core/engine.py` — DiscoveryService wird bei `initialize()` gestartet, Manifest wird auf stdout gedruckt, `load_adventure()` validiert gegen Manifest. (5) `modules/adventures/template.json` — vollstaendiges Template-Abenteuer (4 Locations, 2 NPCs, 3 Clues, 8 Flags, 2 Handouts, Resolution).
[2026-02-27 18:45] | FROM: Codex | Task 07 abgeschlossen: `modules/adventures/spukhaus.json` als vollwertiges The-Haunting-Szenario nach neuem Template neu erstellt, Skill-Namen gegen `modules/rulesets/cthulhu_7e.json` abgeglichen (OK), `modules/index.json` als Registry erzeugt (Ruleset/Adventure/Template + aktive Defaults). Altlasten-Check auf `modules/adventures/*.json` gegen Schema-Minimum durchgefuehrt; keine weiteren schemawidrigen JSON-Leichen mehr vorhanden.
[2026-02-27 22:49] | FROM: Codex | Lore kreativ erweitert (Welle 4): 166 neue eigenst�ndige `*_micro_04.json` mit `scene_seed`, `sensory_detail`, `twist`, `complication`, `payoff`, `gm_moves` und kategoriespezifischen Attributen erzeugt. `data/lore/index.json` auf v1.4 aktualisiert; aktiver Bestand nun 845 JSON-Dateien (679 generiert).
[2026-02-27 22:52] | FROM: Codex | Naechste kreative Lore-Welle ausgerollt: 166 neue `*_micro_05.json` mit Fokus auf Konflikt/Preis/Countdown/Fallback + kategoriespezifischen Feldern erstellt. `data/lore/index.json` auf v1.5 aktualisiert. Aktiver Lore-Bestand jetzt 1011 JSON-Dateien, davon 845 generiert.
[2026-02-27 23:45] | FROM: Codex | Status-Update: Lore-Ausbau bis Welle 5 dokumentiert und verifiziert. Aktiver Bestand: 1011 JSON-Dateien (data/lore, exkl. Archiv-Kopien), davon 845 generierte Micro-Inhalte. Index-Stand: data/lore/index.json v1.5.
[2026-02-27 23:46] | FROM: Codex | Lore-Welle 6 ausgerollt: 166 neue *_micro_06.json (Knotenpunkt-Format mit Pressure/Turn/Cost/Reward + kategoriespezifischen Feldern). data/lore/index.json auf v1.6 aktualisiert. Aktiver Bestand: 1177 JSON-Dateien, davon 1011 generiert.
[2026-02-28 00:13] | FROM: Codex | Weitere Lore-Ladung (Welle 7) abgeschlossen: 166 neue *_micro_07.json (Signal/Friction/Stake/Payoff-Format + kategoriespezifische Felder). data/lore/index.json auf v1.7 aktualisiert. Aktiver Bestand: 1343 JSON-Dateien, davon 1177 generiert.
[2026-02-28 00:27] | FROM: Codex | Lore-Ausbau Inventarfokus: 33 neue Basis-Itemdateien unter data/lore/items/ erstellt (Waffen, Werkzeuge, Medizin, Schutz, Utility, Consumables, Evidence) � keine Micro-Kopien. data/lore/index.json auf v1.8 aktualisiert. Aktiver Gesamtbestand: 1376 JSON-Dateien (1177 Micro, 199 Basis); items Basisbestand jetzt 36.
[2026-02-28 00:29] | FROM: Codex | Inventar-Ausbau erweitert: weitere 54 neue Basis-Itemdateien (Waffen, Munition, Schutz, Tools, Medizin, Kommunikation, Feldgear, Dokumente, Okkult-Utility) unter data/lore/items/ angelegt. data/lore/index.json auf v1.9 aktualisiert. Gesamtstand: 1430 aktive JSON-Dateien (1177 Micro, 253 Basis); items-Basisbestand jetzt 90.
[2026-02-28 00:33] | FROM: Codex | Next-Ladung umgesetzt + Regel beachtet (gents.md immer aktualisieren): 49 neue Basis-Items unter data/lore/items/ erstellt (zus. Waffen, Munition, Forensik/Tools, Medizin, Kommunikation, Feldlogistik, Utility, Evidence, Okkult-Utility). data/lore/index.json auf v2.0 aktualisiert. Gesamt: 1479 aktive JSON-Dateien (1177 Micro, 302 Basis), items-Basisbestand jetzt 139.
[2026-02-28 00:43] | FROM: Codex | Next-Ladung (Batch 4) umgesetzt: 49 weitere Basis-Items in data/lore/items/ erstellt (Waffen, Munition, Schutz, Forensik/Tools, Medizin, Kommunikation, Feldgear, Utility, Dokumente, Okkult-Utility). data/lore/index.json auf v2.1 aktualisiert. Gesamt: 1528 aktive JSON-Dateien (1177 Micro, 351 Basis), items-Basisbestand jetzt 188.
[2026-02-28 01:05] | FROM: Codex | Next-Ladung (Batch 5) geliefert: 45 neue Basis-Items in data/lore/items/ angelegt (Waffenzubehoer, Forensik-/Investigations-Tools, Medizin, Kommunikation, Feldgear, Utility, Evidence, Okkult-Utility). data/lore/index.json auf v2.2 aktualisiert. Gesamt: 1573 aktive JSON-Dateien (1177 Micro, 396 Basis), items-Basisbestand jetzt 233.
[2026-02-28] | FROM: Claude Code | TASK 56 implementiert: (1) `core/session_config.py` — SessionConfig Dataclass mit difficulty, atmosphere, keeper_persona, language, temperature + `from_preset()`/`from_args()` Factory-Methoden. (2) `modules/presets/coc_classic.json` — Beispiel-Preset. (3) `main.py` — 6 neue CLI-Args (--preset, --difficulty, --atmosphere, --persona, --language, --temperature). (4) `core/engine.py` — SessionConfig durchgereicht an Backend. (5) `core/ai_backend.py` — Persona/Atmosphaere/Schwierigkeit/Sprache dynamisch im System-Prompt, Temperature konfigurierbar. Kein Breaking Change — ohne neue Args identisches Verhalten.
[2026-02-28] | FROM: Claude Code | AD&D-Integration implementiert: (1) `modules/rulesets/add_2e.json` — Schema-kompatibel umstrukturiert (metadata, dice_system d20, characteristics, skills + combat/classes/saving_throws). (2) `core/session_config.py` — Difficulty "heroic" als vierte Stufe hinzugefuegt. (3) `core/ai_backend.py` — System-Prompt ruleset-aware: Cthulhu-Modus (Keeper, SAN, STABILITAET_VERLUST) vs. Fantasy-Modus (Dungeon Master, THAC0, XP_GEWINN, HP_HEILUNG, Initiative). GM-Titel und PC-Titel aus metadata.game_master_title/player_character_title. (4) `scripts/tech_gui.py` — Preset-Dropdown hinzugefuegt, SessionConfig wird bei Engine-Load aus Preset gebaut. (5) `main.py` — "--difficulty heroic" als CLI-Choice. (6) BOM-Fix in session_config.py (utf-8-sig). (7) Codex-Richtlinien in agents.md dokumentiert (Ruleset/Adventure Pflichtfelder).
[2026-03-01] | FROM: Claude Code | Paranoia 2E + Shadowrun 6E vollstaendig integriert: 2 Rulesets, 21 Characters, 4 Adventures, 6 Parties, 11 Presets, 2 Szenarien, 4 Keeper/Settings. Lore: ~3576 Dateien. RulesEngine: 11 Keywords, 7 Index-Methoden. AI Backend: System-spezifische Persona + Kampf-Protokolle.
[2026-03-02] | FROM: Claude Code | Budget-basierte Regel-Injektion implementiert: (1) RulesEngine Budget-System (konfigurierbares Budget 1000-50000 Zeichen, 3-Schicht-Selektion mit Priority-Gewichtung, Lore-Chunk-Loader). (2) SessionConfig: rules_budget Feld. (3) GUI: Budget-Slider in tab_session.py. (4) KI-Monitor: dynamische Budget-Anzeige. (5) WCR.md: Neuer Abschnitt 11a (Chunk-Schema mit topic/keywords/injection_priority). (6) 2487 bestehende Chunks automatisch mit topic + keywords angereichert.
[2026-03-02] | FROM: Claude Code | Management-Reorganisation: Alle Steuerungsdokumente (agents.md, rules.md, suggestions.md, WCR.md, Book_ARS_Tool.md) nach `docs/management/` verschoben. `organization.md` erstellt (Rollen: Human Lead, Strategic Lead/Gemini, Lead Developer/Claude Code, Content Specialist/Codex, Virtual Player/AI-Script). agents.md als zentrales Dashboard mit Dokumenten-Verweisen umgebaut. Interne Querverweise angepasst.
[2026-03-02] | FROM: Claude Code | Core Mandate Session 5: (1) rules.md aktualisiert — Gemini-User-Konsole als fuehrende Instanz definiert. (2) agents.md — rollenbasiertes Backlog mit je 3 Tasks pro Rolle (Strategic Lead, Lead Developer, Content Specialist, Virtual Player, Human Lead). (3) `scripts/virtual_player.py` NEU — Automatisierter Spieltest-Agent: N Zuege gegen KI, Metriken-Erfassung (Latenz, Tags, Saetze, Regelcheck-Warnungen), system-spezifische Default-Aktionen (Cthulhu/AD&D/Paranoia/Shadowrun), Dry-Run-Modus, JSON-Export nach data/metrics/. (4) Monolog-Sperre in ai_backend.py: _validate_response() prueft max. 3 Saetze ohne Hook (Frage/[PROBE:]), emittiert response_warning via EventBus. System-Prompt verschaerft: Regel 2 = "MAXIMAL 3 SAETZE NARRATIV". (5) Metrics-Logger in orchestrator.py: automatische Latenz-Messung pro Zug, _metrics_log aggregiert alle Zuege, _save_metrics() schreibt JSON nach data/metrics/ bei Session-Ende.
[2026-03-02] | FROM: Claude Code | Budget-System Expansion + Bugfixes (Session 4): (1) MAX_RULES_BUDGET von 50K auf 2M Zeichen (~500K Tokens) erweitert — User will testen mit vollem Regelwerk. (2) Lore-Chunk-Loader erweitert: scannt jetzt `rules_fulltext_chunks/`, `chapters/`, `fulltext/` (statt nur chunks). Keyword-Ableitung aus chapter_slug, Fallback `source_text.text` wenn `mechanics.raw_text` fehlt. (3) Layer 3 Fulltext-Scan: durchsucht Sektionstext direkt nach Keywords wenn Index nicht genuegt. (4) Auto-Priority-Promotion: kleine Sektionen (<500 Zeichen) werden automatisch hochgestuft — combat/stats/death → permanent, magic/healing/tables/etc. → core. (5) `_build_core_rules_block()` NEU in ai_backend.py: laedt alle 4 Priority-Tiers (permanent/core/support/flavor) in den statischen System-Prompt. (6) KRITISCHER Timing-Bug behoben: `_system_prompt` wurde in `__init__` gebaut BEVOR `set_rules_engine()` aufgerufen wurde → Kernregeln waren leer. Fix: `set_rules_engine()` baut Prompt und Cache neu auf. Verifiziert: 2109 Tokens ohne → 493604 Tokens mit RulesEngine. (7) Session-Reset-Button in Game-Tab (Confirmation Dialog, loescht Chat/History/Combat/Time/KI-Monitor). (8) Paranoia TypeError behoben: `is_dead`/`is_insane` und GUI-Stat-Bars koennen jetzt mit nicht-numerischen Stats umgehen (Paranoia nutzt Strings fuer HP).
