# ARS — Agent Coordination Board

**Zuletzt aktualisiert:** 2026-02-28
**Projektstatus:** In Betrieb — erster Spieltest erfolgreich

**Lead Coordinator:** Gemini (Keeper-KI, Regelwerk-Planung)
**Technical Implementation:** Claude Code (Audio, Engine, GUI, Debugging)
**Storage:** Google Drive (`g:\Meine Ablage\ARS`) — primäres Arbeitsverzeichnis

---

## Projektstatus

| Komponente | Status | Anmerkung |
|------------|--------|-----------|
| Core Engine | ✅ fertig | Regelwerk laden, validieren, Würfelsystem |
| KI-Backend (Gemini) | ✅ fertig | Gemini 2.5 Flash, Streaming, History |
| STT (Faster-Whisper) | ✅ fertig | Whisper base CPU, Silero VAD |
| TTS (Piper) | ✅ fertig | de_DE-thorsten-medium, Deutsch |
| Voice Pipeline | ✅ fertig | STT→Gemini→TTS, Barge-in optional |
| GUI Dashboard | ⚠️ gebaut | CustomTkinter, noch nicht vollständig getestet |
| Charakter-System | ✅ fertig | SQLite-Persistenz |
| Regelwerk (CoC 7e) | ✅ fertig | cthulhu_7e.json |
| Abenteuer-Engine | ✅ fertig | AdventureManager, DiscoveryService, Flag-Persistenz, Location-Kontext |
| Abenteuer-Content | 🔄 minimal | spukhaus.json + template.json + goblin_cave.json vorhanden |
| Dice Mechanics | ✅ fertig | d100 (CoC) + d20 (AD&D), Erfolgsgrade, Bonus/Malus-Würfel |
| AD&D 2e Ruleset | ✅ fertig | add_2e.json, Schema-validiert, d20 roll-under |
| AD&D Content | 🔄 minimal | goblin_cave.json, 2 Presets, Lore in data/lore/add_2e/ |

---

## Technische Architektur

```
main.py ── SessionConfig (core/session_config.py) ── Presets (modules/presets/)
  └── SimulatorEngine (core/engine.py)
        ├── DiscoveryService (core/discovery.py) — Asset-Manifest (6 Modultypen)
        ├── ModuleLoader → cthulhu_7e.json / add_2e.json
        ├── Setting/Keeper/Extras Loader → modules/settings/, keepers/, extras/
        ├── GeminiBackend (core/ai_backend.py) — Keeper-KI (dynamischer Prompt via SessionConfig)
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

## Aktive / Offene Aufgaben

- [ ] **Test:** GUI-Modus (`--gui --voice --no-barge-in`) vollständig testen
- [ ] **Test:** Barge-in mit Kopfhörer verifizieren
- [ ] **Test:** Whisper `small` testen (`WHISPER_MODEL=small` in .env — jetzt konfigurierbar)
- [ ] **Test:** Piper `thorsten-high` Stimme testen (`PIPER_VOICE=de_DE-thorsten-high` in .env)
- [ ] **Content:** Weitere Abenteuer-Module erstellen (spukhaus ist minimal)
- [ ] **Feature:** Charaktererstellung im Voice-Modus
- [ ] **Feature:** Würfelergebnisse in GUI visualisieren
- [x] **TASK 56:** Session Configuration & Prompt Injection (SessionConfig, Presets, CLI-Overrides)
- [ ] **Test:** Diagnostic Center testen (`py -3 scripts/tech_gui.py --module cthulhu_7e --adventure spukhaus`)
- [ ] **Content:** spukhaus.json Flags mit Gemini befuellen (sets_flag/requires_flag an Events/Clues)
- [x] **Bugfix:** Protokoll-Tags werden von TTS vorgelesen — gefixt: `HP_HEILUNG` und `XP_GEWINN` zu `tag_filter.py` und `character.py`/`orchestrator.py` hinzugefuegt.

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
# Vollständiger Spielstart (Lautsprecher):
py -3 main.py --module cthulhu_7e --adventure spukhaus --voice --no-barge-in

# Mit Kopfhörer (Barge-in aktiv):
py -3 main.py --module cthulhu_7e --adventure spukhaus --voice

# Mit GUI:
py -3 main.py --module cthulhu_7e --adventure spukhaus --gui --voice --no-barge-in

# Mit Session-Preset:
py -3 main.py --module cthulhu_7e --preset coc_classic --voice --no-barge-in

# AD&D 2e Dungeon Crawl:
py -3 main.py --module add_2e --preset add_demo --voice --no-barge-in

# AD&D Free Roam (kein festes Abenteuer):
py -3 main.py --module add_2e --preset add_fantasy --voice --no-barge-in

# Preset + Override (hardcore, andere Persona):
py -3 main.py --module cthulhu_7e --preset coc_classic --difficulty hardcore --persona "Sadistisch, wortgewandt"

# Keeper-Dialog isoliert testen:
py -3 scripts/test_keeper.py --adventure spukhaus --voice --no-barge-in

# Audio-Diagnose:
py -3 scripts/test_audio.py --list
py -3 scripts/test_audio.py --tts "Testtext"
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

Rulesets nutzen ein **universelles Skeleton** mit ~25 optionalen Sektionen (siehe WCR.md Sektion 3). Nur 4 Sektionen sind Pflicht (metadata, dice_system, characteristics, skills). Alle anderen werden vom KI-Backend im System-Prompt verwendet, wenn vorhanden.

Fuer die **vollstaendige Konvertierung eines Regelbuchs** siehe `Book_ARS_Tool.md` (12-Phasen-Pipeline).

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
