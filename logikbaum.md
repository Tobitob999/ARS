# ARS Prompt-Generierung — Logikbaum

```
SYSTEM-PROMPT-AUFBAU (_build_system_prompt)
============================================================

Die gesamte Prompt-Generierung findet in core/ai_backend.py
statt (Klasse GeminiBackend). Der System-Prompt wird einmalig
beim Start zusammengebaut und optional als Gemini Context Cache
vorgehalten (TTL 2h). Zusaetzlich wird bei jedem Turn ein
dynamischer Kontext in die Chat-History injiziert.


 +============================+
 |     SZENARIO-AUSWAHL       |   modules/scenarios/*.json
 |  (GUI: tab_session.py)     |   Bsp: guzzoline_run.json
 +============================+
              |
              | laedt Referenzen auf:
              v
 +---+--------+--------+--------+--------+--------+--------+
 | R |   A    |   S    |   K    |   C    |   P    |   E    |
 +---+--------+--------+--------+--------+--------+--------+
   |      |        |        |        |        |        |
   v      v        v        v        v        v        v

 Ruleset  Adventure Setting Keeper  Character Party  Extras
 (.json)  (.json)  (.json) (.json)  (.json)  (.json) (.json)


============================================================
 PHASE 1: STATISCHER SYSTEM-PROMPT  (bei Session-Start)
============================================================

 engine.initialize()
       |
       +---> ModuleLoader.load()         # Ruleset laden + validieren
       +---> load_setting(name)          # Setting laden (optional)
       +---> load_keeper(name)           # Keeper laden (optional)
       +---> load_extras([names])        # Extras laden (optional)
       +---> load_character_template()   # Character laden (optional)
       +---> load_party(name)            # Party laden (optional)
       |
       +---> GeminiBackend.__init__(ruleset, setting, keeper, extras, character)
                    |
                    +---> _build_system_prompt()
                    |           |
                    |           |  ENTSCHEIDUNGSBAUM:
                    |           |
                    |           +-- [1] PERSONA-BLOCK
                    |           |       |
                    |           |       +-- IF ruleset.metadata.system
                    |           |       |       .startswith("cthulhu")
                    |           |       |   THEN:
                    |           |       |     "Du bist der Keeper of Arcane Lore"
                    |           |       |     Philosophie: Kosmischer Horror
                    |           |       |     (Cthulhu-spezifisch)
                    |           |       |
                    |           |       +-- ELSE (Generic/Fantasy):
                    |           |       |     "Du bist der {gm_title}"
                    |           |       |     Philosophie: Lebendige Fantasywelt
                    |           |       |
                    |           |       +-- persona = session_config.keeper_persona
                    |           |       |     OVERRIDE IF keeper.json geladen:
                    |           |       |       persona = keeper["tone"]
                    |           |       |
                    |           |       +-- atmosphere = session_config.atmosphere
                    |           |       |     OVERRIDE IF setting.json geladen:
                    |           |       |       atmosphere = setting["epoch"] + setting["atmosphere"]
                    |           |       |
                    |           |       +-- difficulty = session_config.difficulty_instruction
                    |           |       |
                    |           |       +-- language_block:
                    |           |             IF lang.startswith("en"):
                    |           |               "Antworte auf Englisch"
                    |           |             ELSE: leer
                    |           |
                    |           +-- [1b] KEEPER-DETAIL-BLOCK
                    |           |       (_build_keeper_detail_block)
                    |           |       IF keeper.json geladen:
                    |           |         + narration_style
                    |           |         + combat_style
                    |           |         + npc_voice
                    |           |         + philosophy
                    |           |         + catch_phrases (max 3)
                    |           |       ELSE: leer
                    |           |
                    |           +-- [2] SETTING-BLOCK
                    |           |       (_build_setting_block)
                    |           |       IF setting.json geladen:
                    |           |         + Welt, Epoche, Geographie
                    |           |         + Kultur, Technologie
                    |           |         + Voelker/Spezies, Waehrung
                    |           |         + Sprachstil, special_rules
                    |           |       ELSE: leer
                    |           |
                    |           +-- [3] CHARAKTER-BLOCK
                    |           |       (_build_character_block)
                    |           |       IF character.json geladen:
                    |           |         + Name, Klasse/Beruf, Stufe
                    |           |         + Hintergrund, Traits, Erscheinung
                    |           |         + Charakteristiken (STR, DEX...)
                    |           |         + Ausruestung
                    |           |       ELSE: leer
                    |           |
                    |           +-- [4] STIL & TTS-REGELN
                    |           |       (immer enthalten, statisch)
                    |           |       + Kurze Saetze (max 15 Woerter)
                    |           |       + Keine Klammern/Listen
                    |           |       + Warten auf Spieler-Reaktion
                    |           |       + Keine Metasprache
                    |           |       + Tags ans Ende
                    |           |       + Atmosphaere zuerst
                    |           |
                    |           +-- [5] WUERFELPROBEN-PROTOKOLL
                    |           |       (immer enthalten, statisch)
                    |           |       + [PROBE: Skill | Zielwert]
                    |           |       + [WUERFELERGEBNIS: ...] Reaktion
                    |           |       + [FERTIGKEIT_GENUTZT: Name]
                    |           |
                    |           +-- [6] CHARAKTER-ZUSTAND-PROTOKOLL
                    |           |       |
                    |           |       +-- IF Cthulhu:
                    |           |       |     + [HP_VERLUST: n]
                    |           |       |     + [STABILITAET_VERLUST: ndX]
                    |           |       |     SAN-Regeln, Wahnsinn
                    |           |       |
                    |           |       +-- ELSE (Generic):
                    |           |             + [HP_VERLUST: n]
                    |           |             + [HP_HEILUNG: n/ndX]
                    |           |             + [XP_GEWINN: n]
                    |           |             + Kampfsystem-Info (IF vorhanden)
                    |           |
                    |           +-- [7] FAKTEN-PROTOKOLL
                    |           |       (immer enthalten, statisch)
                    |           |       + [FAKT: {"key": "value"}]
                    |           |
                    |           +-- [8] INVENTAR-PROTOKOLL
                    |           |       (immer enthalten, statisch)
                    |           |       + [INVENTAR: Name | gefunden/verloren/erledigt]
                    |           |
                    |           +-- [9] STIMMEN-WECHSEL
                    |           |       (immer enthalten, statisch)
                    |           |       + [STIMME:keeper/woman/monster/scholar/mystery]
                    |           |
                    |           +-- [10] ZEIT-PROTOKOLL
                    |           |       (immer enthalten, statisch)
                    |           |       + [ZEIT_VERGEHT: Xh]
                    |           |       + [TAGESZEIT: HH:MM]
                    |           |       + [WETTER: Beschreibung]
                    |           |
                    |           +-- [11] REGELWERK-REFERENZ
                    |           |       (immer enthalten)
                    |           |       + System-Name, Version, Default-Die
                    |           |       + Erfolgsgrade (aus dice_system)
                    |           |       + Fertigkeiten-Liste (aus skills{})
                    |           |
                    |           +-- [12] ABENTEUER-BLOCK
                    |           |       (_build_adventure_block)
                    |           |       IF adventure.json geladen:
                    |           |         + Titel, Schauplatz, Aufhaenger
                    |           |         + Keeper-Lore (geheim)
                    |           |         + NPCs (Name, Rolle, Merkmale,
                    |           |           Geheimnisse, Dialog-Hinweise)
                    |           |         + Orte (Name, Atmosphaere,
                    |           |           Hinweise, Keeper-Notizen)
                    |           |         + Gegenstaende & Artefakte
                    |           |         + Dokumente & Handouts
                    |           |         + Organisationen & Kulte
                    |           |         + Okkulte Zauber
                    |           |         + Bestiarium (Keeper-only)
                    |           |         + Library-Daten
                    |           |         + NPC-Generator-Tabellen
                    |           |         + Wetter-Muster
                    |           |         + Pop-Kultur & Alltag
                    |           |         + Architektur & Raumdetails
                    |           |         + Sanitarium
                    |           |         + Justizsystem
                    |           |         + Hinweis-Matrix
                    |           |         + Moegliche Ausgaenge
                    |           |       ZUSAETZLICH: _load_and_merge_lore()
                    |           |         Laedt /data/lore/**/*.json + *.md
                    |           |         und merged sie ins Adventure-Dict
                    |           |       ELSE: leer
                    |           |
                    |           +-- [13] EXTRAS-BLOCK
                    |           |       (_build_extras_block)
                    |           |       IF extras geladen:
                    |           |         Fuer jedes Extra:
                    |           |           + extra["prompt_injection"]
                    |           |       ELSE: leer
                    |           |
                    |           +-- [14] ABSOLUTES VERBOT
                    |                   (immer enthalten, statisch)
                    |                   + Keine Regeln/Tags erwaehnen
                    |                   + Keine Immersionsbrueche
                    |                   + Keine Spieler-Tipps
                    |
                    +---> _initialize_cache()
                              |
                              +-- IF len(system_prompt) >= 15000 Zeichen:
                              |     Gemini Context Cache erstellen
                              |     (TTL 2h, spart Tokens bei jedem Turn)
                              |
                              +-- ELSE: Standard-Modus (Prompt bei jedem
                                    Request als system_instruction senden)


============================================================
 PHASE 2: DYNAMISCHER KONTEXT  (bei jedem Turn)
============================================================

 _build_contents()  (wird bei jedem chat_stream() aufgerufen)
       |
       +-- [A] ARCHIVIST-KONTEXT  (IF Archivist verbunden)
       |       |
       |       +-- Chronik (get_chronicle):
       |       |     "=== CHRONIK DER BISHERIGEN EREIGNISSE ==="
       |       |     Zusammenfassung der bisherigen Session
       |       |     (alle SUMMARY_INTERVAL Runden aktualisiert)
       |       |
       |       +-- World State (get_world_state):
       |             "=== AKTUELLE FAKTEN ==="
       |             Key-Value-Paare aus [FAKT:...] Tags
       |             z.B. "rupert_besucht: true"
       |
       +-- [B] LOCATION-KONTEXT  (IF AdventureManager geladen)
       |       get_location_context():
       |       Aktueller Ort mit Beschreibung, NPCs,
       |       verfuegbare Hinweise, Ausgaenge
       |
       +-- [C] ZEIT-KONTEXT  (IF TimeTracker verbunden)
       |       "=== AKTUELLE ZEIT ==="
       |       Tageszeit, Wetter, vergangene Stunden
       |
       +-- [D] KONVERSATIONSHISTORIE
               Letzte MAX_HISTORY_TURNS=40 Runden
               (user/model Nachrichten abwechselnd)


============================================================
 PHASE 3: RESPONSE-VERARBEITUNG  (nach KI-Antwort)
============================================================

 Orchestrator._game_loop()
       |
       +-- KI-Antwort empfangen (Streaming)
       |
       +-- extract_probes(response)
       |     Regex: [PROBE: Skill | Zielwert]
       |     --> MechanicsEngine.skill_check(target)
       |     --> inject_roll_result() --> erneuter chat_stream()
       |
       +-- extract_stat_changes(response)
       |     Tags: HP_VERLUST, STABILITAET_VERLUST,
       |           HP_HEILUNG, XP_GEWINN, FERTIGKEIT_GENUTZT
       |     --> CharacterManager.update_stat()
       |
       +-- extract_facts(response)
       |     Tag: [FAKT: {"key": "value"}]
       |     --> Archivist.merge_world_state()
       |     --> AdventureManager.merge_flags_from_world_state()
       |
       +-- CharacterManager.log_turn()
       |     Persistiert Turn in SQLite
       |
       +-- IF should_summarize(turn_number):
             Archivist._update_chronicle()
             --> ai_backend.summarize(turns)
             --> Zusammenfassung in DB speichern


============================================================
 GESAMT-DATENFLUSS (Uebersicht)
============================================================

 +------------------+     +------------------+
 | modules/         |     | data/lore/       |
 | rulesets/*.json   |     | **/*.json + *.md |
 | adventures/*.json |     +--------+---------+
 | settings/*.json   |              |
 | keepers/*.json    |              | merge
 | extras/*.json     |              v
 | characters/*.json |     +--------+---------+
 | parties/*.json    +---->| GeminiBackend    |
 | scenarios/*.json  |     |                  |
 +------------------+     | System-Prompt    |
                          | (statisch)       |
 +------------------+     |                  |     +------------------+
 | session_config   +---->| + Persona        |     | Gemini 2.5 Flash |
 | (GUI/CLI Args)   |     | + Setting        |     |                  |
 | - persona        |     | + Keeper         +---->| system_instruction|
 | - atmosphere     |     | + Character      |     | (oder Cache)     |
 | - difficulty     |     | + Regeln         |     |                  |
 | - language       |     | + Abenteuer      |     | contents[]       |
 | - temperature    |     | + Extras         |     | (dynamisch)      |
 +------------------+     |                  |     |                  |
                          +--+----+----+-----+     +--------+---------+
                             |    |    |                     |
 +------------------+        |    |    |                     | Stream
 | Archivist        +--------+    |    |                     v
 | - Chronik        | inject      |    |            +--------+---------+
 | - World State    |             |    |            | Response Chunks  |
 +------------------+             |    |            +--------+---------+
                                  |    |                     |
 +------------------+             |    |                     | parse
 | AdventureManager +---------+--+    |                     v
 | - Location-Ctx   | inject          |            +--------+---------+
 +------------------+                 |            | Tag-Extraktion   |
                                      |            |                  |
 +------------------+                 |            | [PROBE:...]      |
 | TimeTracker      +---------+-------+            | [HP_VERLUST:...] |
 | - Tageszeit      | inject                       | [FAKT:{...}]     |
 | - Wetter         |                              | [INVENTAR:...]   |
 +------------------+                              | [ZEIT_VERGEHT:]  |
                                                   | [STIMME:...]     |
                                                   +--------+---------+
                                                            |
                                              +-------------+------------+
                                              |             |            |
                                              v             v            v
                                     MechanicsEngine  CharacterMgr  Archivist
                                     (Wuerfel)        (HP/SAN/XP)   (Fakten)
```

## Prompt-Groessen (typisch)

| Komponente          | Zeichen (ca.) | Anteil  |
|---------------------|---------------|---------|
| Persona-Block       | 800-1200      | 5-8%    |
| Keeper-Details      | 200-500       | 1-3%    |
| Setting-Block       | 400-800       | 3-5%    |
| Charakter-Block     | 300-600       | 2-4%    |
| Stil & TTS-Regeln   | 700           | 5%      |
| Proben-Protokoll    | 600           | 4%      |
| Zustand-Protokoll   | 500-700       | 4%      |
| Fakten-Protokoll    | 300           | 2%      |
| Inventar-Protokoll  | 300           | 2%      |
| Stimmen-Wechsel     | 400           | 3%      |
| Zeit-Protokoll      | 500           | 3%      |
| Regelwerk-Referenz  | 200-500       | 2-3%    |
| Abenteuer-Block     | 2000-8000+    | 30-55%  |
| Lore-Merge          | 0-50000+      | 0-70%   |
| Extras-Block        | 100-500       | 1-3%    |
| Absolutes Verbot    | 200           | 1%      |
| **Gesamt (ohne Lore)** | **~8000-15000** | **100%** |

## Context-Cache-Schwelle

Der System-Prompt wird gecacht wenn `len(prompt) >= 15.000 Zeichen`.
Das ist typischerweise der Fall wenn ein Abenteuer mit Lore geladen ist.
Ohne Abenteuer (~8000 Zeichen) wird der Prompt bei jedem Turn als
`system_instruction` mitgesendet.

## Dateien im Logikbaum

| Datei | Rolle |
|-------|-------|
| `core/ai_backend.py` | Prompt-Bau, Gemini-API, Streaming, Tag-Regex |
| `core/engine.py` | Modul-Laden, Lifecycle, SimulatorEngine |
| `core/orchestrator.py` | Game Loop, Tag-Verarbeitung, I/O |
| `core/discovery.py` | Asset-Indizierung, Szenario-Aufloesung |
| `core/mechanics.py` | Wuerfellogik, Skill-Checks |
| `core/character.py` | HP/SAN/XP-Verwaltung, SQLite-Persistenz |
| `core/memory.py` | Archivist: Chronik, World State, Fakten |
| `core/adventure_manager.py` | Location-Tracking, Flags, Clues |
| `gui/tab_session.py` | Szenario-Auswahl, Modul-Konfiguration |
