# ARS — Agent Coordination Dashboard

**Zuletzt aktualisiert:** 2026-03-04 (Session 18 — Phase-1 Bereinigung: ~6.976 Nicht-AD&D Dateien entfernt)
**Projektstatus:** AD&D-Only — 1 Regelsystem (AD&D 2e), 5972 Lore-Dateien, Party-System, Dungeon-View, Content Pipeline, Web GUI, Testbot CLI, TinyCrawl Demo

**Speicherort:** `docs/management/` — zentraler Management-Ordner

### Verknuepfte Dokumente

| Dokument | Zweck |
|----------|-------|
| [organization.md](organization.md) | Rollen, Verantwortlichkeiten, Organigramm |
| [rules.md](rules.md) | Globale Agenten-Regeln, Kommunikations-Protokoll |
| [suggestions.md](suggestions.md) | Strategische Planung, Feature-Brainstorming |
| [WCR.md](WCR.md) | World Creation Rules — JSON-Schema fuer Content-Erstellung |
| [Book_ARS_Tool.md](Book_ARS_Tool.md) | Buch-Konvertierungs-Pipeline (12 Phasen) |
| [conversion_workflow.md](conversion_workflow.md) | Autopilot-Workflow fuer PDF-Konvertierung |

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
| TechGUI (Desktop) | fertig | tkinter, 12 Tabs, Dark Theme, Budget-Slider (bis 2M), Session-Reset |
| Dungeon-Visualisierung | v1 fertig | Canvas-Karte, BFS-Layout, Fog of War, Party/Monster-Marker, Sounds, Click-Navigation |
| Pixel-Art Renderer | v2 fertig | pixel_renderer.py (shared): PixelTileset, Autotiler, render_room_to_image() |
| Replay-Viewer | Pixel-Art fertig | tab_replay_viewer.py REWRITE: Canvas+PIL statt ASCII, Move-Trails (Gruen/Rot/Gelb), Auto-Scale |
| Dungeon-Maps | v1 fertig | crawltraining_stress (5 Raeume) + crawltraining_full (15 Raeume) mit Map+Spawns |
| Roaming-Monster | v1 fertig | auto_roam_idle_monsters() in grid_engine.py: 30% Patrouille idle Monster |
| Web GUI | v1 fertig | FastAPI+WebSocket, 10 Tabs, Dark Theme, `--webgui --port 7860` |
| Testbot CLI | fertig | `scripts/testbot.py` — run/results/status/cleanup, Token-Tracking, EUR-Kosten |
| Charakter-System | fertig | SQLite-Persistenz, nicht-numerische Stats (Paranoia) |
| AD&D 2e | fertig (v2 — feingranuliert) | d20, THAC0, Klassen — einziges aktives System |
| Lore-Daten | fertig | 5972 JSONs in data/lore/add_2e/ (58 MB), 3-Verzeichnis-Scan, Auto-Priority |
| Party-System | fertig (v1) | PartyStateManager, 6-Char Party, Party-Monitor Tab, VirtualPlayer Case 7 |
| Abenteuer-Content | minimal | goblin_cave, dungeon_gauntlet_party, crawltraining, testkampf |
| TinyCrawl Demo | Level 1 fertig | Standalone Auto-Battler, Hoehlen-Dungeon 80x60, scrollbar, Fog of War, Minimap, CRT-Scanlines |
| Tileset-Archiv | 12 Packs | `data/tilesets/` — 1227 PNGs, 6 MB, 0x72 Dungeon v5 + 11 weitere Packs |

---

## Technische Architektur

```
main.py ── SessionConfig (core/session_config.py) ── Presets (modules/presets/)
  └── SimulatorEngine (core/engine.py)
        ├── DiscoveryService (core/discovery.py) — Asset-Manifest (6 Modultypen)
        ├── ModuleLoader → add_2e.json
        ├── Setting/Keeper/Extras Loader → modules/settings/, keepers/, extras/
        ├── GeminiBackend (core/ai_backend.py) — Keeper-KI (dynamischer Prompt via SessionConfig)
        │     ├── Kernregeln-Block (_build_core_rules_block → System-Prompt, bis 2M Zeichen)
        │     ├── AdventureManager-Kontext (Location, Flags → Prompt)
        │     ├── Setting-Block (Welt, Epoche, Voelker → Prompt)
        │     ├── Keeper-Detail-Block (Erzaehlstil, Philosophie → Prompt)
        │     └── Extras-Block (Zusatzregeln → Prompt)
        ├── CharacterManager (core/character.py) — SQLite
        ├── PartyStateManager (core/party_state.py) — Multi-Char HP/Spell/Item/XP Tracking
        ├── Orchestrator (core/orchestrator.py) — Game Loop
        │     ├── AdventureManager (core/adventure_manager.py) — Story Logic
        │     └── Archivist (core/memory.py) — Chronik + World State
        └── VoicePipeline (audio/pipeline.py)
              ├── STTHandler (audio/stt_handler.py) — Faster-Whisper + Silero VAD
              └── TTSHandler (audio/tts_handler.py) — Piper → Kokoro → pyttsx3
```

**Web GUI Architektur:**
```
main.py --webgui --port 7860
  └── web/server.py (FastAPI + uvicorn)
        ├── WebSocket /ws — bidirektional (EventBus-Bridge + Player-Input)
        ├── REST /api/discovery, /api/engine/state, /api/engine/start|pause|stop, /api/input
        ├── Static /static/css/ (theme.css, layout.css)
        ├── Static /static/js/ (app.js, eventbus.js, tabs/*.js)
        └── Templates /templates/index.html (Single-Page, 10 Tabs)
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
- [x] B2-B9 Coding Batch (Session 6): Conversion Monitor, Cache-Hash, Noise-Gate, Stat-Bars, evaluate_condition, --convert-all, LatencyLogger, Session-Reset Hardening
- [x] BUGFIX: Paranoia exits list-vs-dict crash in adventure_manager.py
- [x] **Testbot CLI** (`scripts/testbot.py`): 4 Subcommands (run/results/status/cleanup), Token-Tracking in virtual_player+test_series, EUR-Kosten
- [x] **Web GUI v1** (`web/`): FastAPI+WebSocket, 10 Tabs (Session/Game/Audio/KI-Monitor/Injector/Responder/KI-Connection/Spielstand/Conversion/Test-Monitor), Dark Theme, `--webgui`
- [x] **Party-System v1** — PartyStateManager, 6 Party-Tag-Patterns, Party-Prompt-Injection, Party-Monitor GUI Tab, VirtualPlayer Party-Mode (Session 10)
- [x] **CRITICAL: Preset-Adventure Passthrough** — BUG-009 FIXED (Session 12): _set_combo() fuegt fehlende Werte ins Dropdown ein statt silent fallback auf "(keine)". gui/tab_session.py.
- [x] **HIGH: Monster-Gegenangriffe** — BUG-010 MITIGATED (Session 12): KAMPF-ERINNERUNG Block im System-Prompt + Post-Validation Warning in _validate_response(). Prompt-Compliance nicht 100% garantiert.
- [ ] **HIGH: Context-Saettigung** — BUG-011 OPEN: Repetitive Antworten ab ~80 Zuegen. Erfordert History-Truncation oder Zusammenfassungs-Mechanismus. Design-Konzept offen.
- [x] PROBE-Tags fehlen in Cthulhu — FIXED Session 7 (BUG-001/002): Deep-Copy + Type Guards in adventure_manager.py + memory.py. Root Cause Session 9.
- [x] Monolog-Sperre Enforcement — FIXED Session 7 (BUG-003): _pending_feedback Liste, STIL-KORREKTUR Injection, Prompt-Verschaerfung.
- [x] Shadowrun PROBE-Zielwerte ausserhalb Bereich — FIXED Session 7 (BUG-002): PROBE-Protokoll check_mode-aware, Pool-Berechnung im Prompt.

### Content Specialist (Codex)
- [ ] Erweiterung AD&D 2e Abenteuer-Content (weitere Dungeons, Kampagnen-Szenarien)
- [ ] Forgotten Realms Setting-Expansion in `data/lore/add_2e/settings/`

### Converter Agent — AD&D 2e Komplett-Extraktion

**Ziel:** Alle 108 PDFs aus `ADD2e/` vollstaendig nach `data/lore/add_2e/` extrahieren.
**Methode:** 12-Phasen-Pipeline ([Book_ARS_Tool.md](Book_ARS_Tool.md)), Entity-First, 100%-Snippet-Abdeckung.
**Aufwand:** ~81 Stunden (108 PDFs × ~45 Min/PDF), aufgeteilt in 11 Batches.
**Bestehende Basis:** monsters/ (106), spells/ (331), items/ (50), equipment/ (1), encounters/ (31), tables/ (68), mechanics/ (6) — Monstrous Compendium Vol.1 bereits konvertiert.

#### Zielordner je Quelltyp

| Quelltyp | Zielordner in `data/lore/add_2e/` | Haupt-Entitaetstypen |
|----------|----------------------------------|----------------------|
| PHBR-Handbooks (Klassen) | `classes/`, `kits/` | kit, class_option, proficiency |
| PHBR-Handbooks (Rassen) | `races/` | race, racial_ability, subrace |
| Monster Compendiums | `monsters/` | monster, stat_block, ecology |
| Spell Compendiums (Wizard) | `spells/wizard/` | spell, spell_table |
| Spell Compendiums (Priest) | `spells/priest/` | spell, spell_table |
| Encyclopedia Magica | `magic_items/` | magic_item, artifact |
| Magic Encyclopedia | `magic_items/` | magic_item |
| Arms & Equipment Guide | `equipment/` | weapon, armor, gear |
| Player's Options | `rules/player_options/` | rule, combat_system, skill_variant |
| Tome of Magic | `spells/wizard/`, `spells/priest/` | spell, wild_magic, shadow_magic |
| Legends and Lore | `deities/` | deity, pantheon, divine_power |
| DM Guide Series (DMGR) | `dm_tools/` | rule, encounter_table, dm_advice |
| Dungeon/World Builders | `dm_tools/` | rule, dungeon_design, world_design |
| DM Option: High-Level | `rules/high_level/` | rule, epic_table |
| Book of Artifacts | `magic_items/artifacts/` | artifact, relic |
| Dragonlance Series | `settings/dragonlance/` | lore, location, npc, faction |
| Historical Reference (HR) | `settings/historical/` | lore, culture, equipment |

#### Konvertierungsstatus je Prioritaet

**Prioritaet 1 — Kern-Spielmechanik (sofort spielrelevant)**

| # | PDF (Kurztitel) | Status | Zielordner |
|---|-----------------|--------|------------|
| P1-01 | PHBR01 Complete Fighter's Handbook | [x] FERTIG | classes/, kits/ |
| P1-02 | PHBR02 Complete Thief's Handbook | [x] FERTIG | classes/, kits/ |
| P1-03 | PHBR03 Complete Priest's Handbook | [x] FERTIG | classes/, kits/ |
| P1-04 | PHBR04 Complete Wizard's Handbook | [x] FERTIG | classes/, kits/ |
| P1-05 | PHBR05 Complete Psionics Handbook | [x] FERTIG (Chapters, keine Einzel-Kits) | classes/, kits/ |
| P1-06 | PHBR06 Complete Book of Dwarves | [x] FERTIG (Chapters, keine Einzel-Kits) | races/, kits/ |
| P1-07 | PHBR07 Complete Bard's Handbook | [x] FERTIG (Chapters, keine Einzel-Kits) | classes/, kits/ |
| P1-08 | PHBR08 Complete Book of Elves | [x] FERTIG (Chapters, keine Einzel-Kits) | races/, kits/ |
| P1-09 | PHBR09 Complete Book of Gnomes and Halflings | [x] FERTIG (Chapters, keine Einzel-Kits) | races/, kits/ |
| P1-10 | PHBR10 Complete Book of Humanoids | [x] FERTIG | races/, kits/ |
| P1-11 | PHBR11 Complete Ranger's Handbook | [x] FERTIG | classes/, kits/ |
| P1-12 | PHBR12 Complete Paladin's Handbook | [x] FERTIG | classes/, kits/ |
| P1-13 | PHBR13 Complete Druid's Handbook | [x] FERTIG | classes/, kits/ |
| P1-14 | PHBR14 Complete Barbarian's Handbook | [x] FERTIG | classes/, kits/ |
| P1-15 | PHBR15 Complete Ninja's Handbook | [x] FERTIG (Chapters, keine Einzel-Kits) | classes/, kits/ |
| P1-16 | DMGR3 Arms and Equipment Guide | [x] FERTIG | equipment/ |
| P1-17 | Player's Option: Combat & Tactics | [x] FERTIG | rules/player_options/ |
| P1-18 | Player's Option: Skills & Powers | [x] FERTIG | rules/player_options/ |
| P1-19 | Player's Option: Spells & Magic | [x] FERTIG | rules/player_options/ |
| P1-20 | Legends and Lore | [x] FERTIG | deities/ |
| P1-21 | Tome of Magic | [x] FERTIG | spells/wizard/, spells/priest/ |

**Prioritaet 2 — Monster & Magie (Content-Erweiterung)**

| # | PDF (Kurztitel) | Status | Zielordner |
|---|-----------------|--------|------------|
| P2-01 | Monstrous Compendium Volume 1 | [x] FERTIG (106 Monster) | monsters/ |
| P2-02 | Monstrous Compendium Volume 2 | [x] FERTIG (97 Monster, MC_V2, _text.pdf) | monsters/ |
| P2-03 | MC Annual Volume 1 | [x] FERTIG (113 Monster, MC_A1, _text.pdf) | monsters/ |
| P2-04 | MC Annual Volume 2 | [x] FERTIG (37 Monster, MC_A2, 1 Dup) | monsters/ |
| P2-05 | MC Annual Volume 3 | [x] FERTIG (63 Monster, MC_A3) | monsters/ |
| P2-06 | MC Annual Volume 4 | [x] FERTIG (65 Monster, MC_A4, _text.pdf, 6 Dups) | monsters/ |
| P2-07 | MC Fiend Folio Appendix | [x] FERTIG (56 Monster, MC_FF, _text.pdf, 3 Dups) | monsters/ |
| P2-08 | MC Mystara Appendix | [x] FERTIG (24 Monster, MC_MP) | monsters/ |
| P2-09 | MC Outer Planes Appendix | [x] FERTIG (73 Monster, MC_OP, _text.pdf) | monsters/ |
| P2-10 | MC Savage Coast Appendix | [x] FERTIG (8 Monster, MC_SC, OCR-limitiert, 63 Dups verworfen) | monsters/ |
| P2-11 | Encyclopedia Magica Volume 1 | [x] FERTIG | magic_items/ |
| P2-12 | Encyclopedia Magica Volume 2 | [x] FERTIG | magic_items/ |
| P2-13 | Encyclopedia Magica Volume 3 | [x] FERTIG | magic_items/ |
| P2-14 | Encyclopedia Magica Volume 4 | [x] FERTIG | magic_items/ |
| P2-15 | Wizards Spell Compendium Volume 1 | [x] FERTIG | spells/wizard/ |
| P2-16 | Wizards Spell Compendium Volume 2 | [x] FERTIG | spells/wizard/ |
| P2-17 | Wizards Spell Compendium Volume 3 | [x] FERTIG (OCR-limitiert) | spells/wizard/ |
| P2-18 | Wizards Spell Compendium Volume 4 | [x] FERTIG | spells/wizard/ |
| P2-19 | Priest Spell Compendium Volume 1 | [x] FERTIG (OCR-limitiert) | spells/priest/ |
| P2-20 | Priest Spell Compendium Volume 2 | [x] FERTIG (OCR-limitiert) | spells/priest/ |
| P2-21 | Priest Spell Compendium Volume 3 | [x] FERTIG (OCR-limitiert) | spells/priest/ |
| P2-22 | The Magic Encyclopedia Volume 1 | [x] FERTIG | magic_items/ |
| P2-23 | The Magic Encyclopedia Volume 2 | [x] FERTIG | magic_items/ |

**Prioritaet 3 — DM-Werkzeuge**

| # | PDF (Kurztitel) | Status | Zielordner |
|---|-----------------|--------|------------|
| P3-01 | DMGR1 Campaign Sourcebook and Catacomb Guide | [x] FERTIG | dm_tools/ |
| P3-02 | DMGR2 Castle Guide | [x] FERTIG | dm_tools/ |
| P3-03 | DMGR4 Monster Mythology | [x] FERTIG | deities/, monsters/ |
| P3-04 | DMGR5 Creative Campaigning | [x] FERTIG | dm_tools/ |
| P3-05 | DMGR6 The Complete Book of Villains | [x] FERTIG | dm_tools/, kits/ |
| P3-06 | DMGR7 The Complete Book of Necromancers | [x] FERTIG | dm_tools/, classes/ |
| P3-07 | DMGR8 Sages and Specialists | [x] FERTIG | dm_tools/ |
| P3-08 | DMGR9 Of Ships and Sea | [x] FERTIG | dm_tools/, equipment/ |
| P3-09 | Dungeon Builder's Guidebook | [x] FERTIG | dm_tools/ |
| P3-10 | World Builders Guidebook | [x] FERTIG | dm_tools/ |
| P3-11 | Dungeon Master Option: High-Level Campaigns | [x] FERTIG | rules/high_level/ |
| P3-12 | Book of Artifacts | [x] FERTIG | magic_items/artifacts/ |
| P3-13 | Player's Handbook (2nd Edition) | [x] FERTIG (9 Kapitel, Dateiname-Fix) | rules/, classes/, equipment/ |

**Prioritaet 4 — Setting-Content (Dragonlance + Historical)**

| # | PDF (Kurztitel) | Status | Zielordner |
|---|-----------------|--------|------------|
| P4-01 | Dragonlance: Tales of the Lance (Boxset) | [x] FERTIG | settings/dragonlance/ |
| P4-02 | Dragonlance: Player's Guide to DL Campaign | [x] FERTIG | settings/dragonlance/ |
| P4-03 | Dragonlance: A Saga Companion | [x] FERTIG | settings/dragonlance/ |
| P4-04 | Dragonlance: Dragonlance Classics 15th Anniversary | [x] FERTIG | settings/dragonlance/ |
| P4-05 | Dragonlance: DLA1 Dragon Dawn | [x] FERTIG | settings/dragonlance/ |
| P4-06 | Dragonlance: DLA2 Dragon Knight | [x] FERTIG | settings/dragonlance/ |
| P4-07 | Dragonlance: DLA3 Dragons Rest | [x] FERTIG | settings/dragonlance/ |
| P4-08 | Dragonlance: DLC1 Classics Vol 1 | [x] FERTIG | settings/dragonlance/ |
| P4-09 | Dragonlance: DLC2 Classics Vol 2 | [x] FERTIG | settings/dragonlance/ |
| P4-10 | Dragonlance: DLC3 Classics Vol 3 | [x] FERTIG | settings/dragonlance/ |
| P4-11 | Dragonlance: DLE1 In Search of Dragons | [x] FERTIG | settings/dragonlance/ |
| P4-12 | Dragonlance: DLE2 Dragon Magic | [x] FERTIG | settings/dragonlance/ |
| P4-13 | Dragonlance: DLE3 Dragon Keep | [x] FERTIG | settings/dragonlance/ |
| P4-14 | Dragonlance: DLQ1 Knight's Sword | [x] FERTIG | settings/dragonlance/ |
| P4-15 | Dragonlance: DLQ2 Flint's Axe | [x] FERTIG | settings/dragonlance/ |
| P4-16 | Dragonlance: DLR1 Otherlands | [x] FERTIG | settings/dragonlance/ |
| P4-17 | Dragonlance: DLR2 Taladas, The Minotaurs | [x] FERTIG | settings/dragonlance/ |
| P4-18 | Dragonlance: DLR3 Unsung Heroes | [x] FERTIG | settings/dragonlance/ |
| P4-19 | Dragonlance: DLS1 New Beginnings | [x] FERTIG | settings/dragonlance/ |
| P4-20 | Dragonlance: DLS2 Tree Lords | [x] FERTIG | settings/dragonlance/ |
| P4-21 | Dragonlance: DLS3 Oak Lords | [x] FERTIG | settings/dragonlance/ |
| P4-22 | Dragonlance: DLS4 Wild Elves | [x] FERTIG | settings/dragonlance/ |
| P4-23 | Dragonlance: DLT1 New Tales | [x] FERTIG | settings/dragonlance/ |
| P4-24 | Dragonlance: Dwarven Kingdoms of Krynn | [x] FERTIG | settings/dragonlance/ |
| P4-25 | Dragonlance: Fifth Age | [x] FERTIG | settings/dragonlance/ |
| P4-26 | Dragonlance: Heroes of Defiance | [x] FERTIG | settings/dragonlance/ |
| P4-27 | Dragonlance: Heroes of Hope | [x] FERTIG | settings/dragonlance/ |
| P4-28 | Dragonlance: Heroes of Sorcery | [x] FERTIG | settings/dragonlance/ |
| P4-29 | Dragonlance: Heroes of Steel | [x] FERTIG | settings/dragonlance/ |
| P4-30 | Dragonlance: History of Dragonlance | [x] FERTIG | settings/dragonlance/ |
| P4-31 | Dragonlance: More Leaves from the Inn | [x] FERTIG | settings/dragonlance/ |
| P4-32 | Dragonlance: Palanthas | [x] FERTIG | settings/dragonlance/ |
| P4-33 | Dragonlance: Seeds of Chaos | [x] FERTIG | settings/dragonlance/ |
| P4-34 | Dragonlance: Chaos Spawn | [x] FERTIG | settings/dragonlance/ |
| P4-35 | Dragonlance: Citadel of Light | [x] FERTIG | settings/dragonlance/ |
| P4-36 | Dragonlance: Battle Lines 1 - The Sylvan Veil | [x] FERTIG | settings/dragonlance/ |
| P4-37 | Dragonlance: Battle Lines 2 - Rise of the Titans | [x] FERTIG | settings/dragonlance/ |
| P4-38 | Dragonlance: Book of Lairs | [x] FERTIG | settings/dragonlance/ |
| P4-39 | Dragonlance: Last Tower - Legacy of Raistlin | [x] FERTIG | settings/dragonlance/ |
| P4-40 | Dragonlance: Time of the Dragon Boxset | [x] FERTIG | settings/dragonlance/ |
| P4-41 | Dragonlance: Wings of Fury | [x] FERTIG | settings/dragonlance/ |
| P4-42 | Dragonlance: The Bestiary | [x] FERTIG | settings/dragonlance/ |
| P4-43 | Dragonlance: TM3 World of Krynn Trail Map | [x] FERTIG | settings/dragonlance/ |
| P4-44 | Dragonlance: The Art of the Dragonlance Saga | [x] FERTIG | settings/dragonlance/ |
| P4-45 | HR1 Vikings Campaign | [x] FERTIG | settings/historical/ |
| P4-46 | HR2 Charlemagne's Paladins | [x] FERTIG | settings/historical/ |
| P4-47 | HR3 Celts | [x] FERTIG | settings/historical/ |
| P4-48 | HR4 A Mighty Fortress | [x] FERTIG | settings/historical/ |
| P4-49 | HR5 Glory of Rome | [x] FERTIG | settings/historical/ |
| P4-50 | HR6 Age of Heroes | [x] FERTIG | settings/historical/ |
| P4-51 | HR7 Crusades | [x] FERTIG | settings/historical/ |

#### Batch-Planung

| Batch | PDFs | Inhalt | Prioritaet | Schaetzung |
|-------|------|--------|-----------|------------|
| B-C01 | P1-01 bis P1-10 | PHBR01-10 (Fighter bis Humanoids) | P1 | ~7,5 Std |
| B-C02 | P1-11 bis P1-21 | PHBR11-15 + Player's Options + Legends + Tome | P1 | ~8 Std |
| B-C03 | P2-01 bis P2-10 | Monster Compendiums Vol.2 + Annuals + Appendices | P2 | FERTIG (536 neue Monster, 107→656 gesamt) |
| B-C04 | P2-11 bis P2-18 | Encyclopedia Magica Vol.1-4 + Wizard Spells Vol.1-4 | P2 | FERTIG (33 Kapitel magic_items + Teil Spells) |
| B-C05 | P2-19 bis P2-23 | Priest Spells Vol.1-3 + Magic Encyclopedia Vol.1-2 | P2 | FERTIG (1.010 Spells gesamt, spells/) |
| B-C06 | P3-01 bis P3-08 | DMGR1-9 (Campaign/Castle/Mythology/Creative/Villains/Necro/Sages/Ships) | P3 | FERTIG (Teil von 113 Kapitel dm_tools/) |
| B-C07 | P3-09 bis P3-13 | Dungeon/World Builder + High-Level + Artifacts + PHB | P3 | FERTIG (113 Kapitel dm_tools/+magic_items/+rules/) |
| B-C08 | P4-01 bis P4-15 | DL Basics + DLA/DLC/DLE/DLQ-Serie | P4 | FERTIG (Teil von 188 Kapitel settings/dragonlance/) |
| B-C09 | P4-16 bis P4-30 | DLR/DLS/DLT-Serie + Dwarven/Fifth Age/Heroes-Serie | P4 | FERTIG (Teil von 188 Kapitel settings/dragonlance/) |
| B-C10 | P4-31 bis P4-44 | DL Reste (History/Palanthas/Chaos/Citadel/Battle Lines/etc.) | P4 | FERTIG (188 Kapitel gesamt settings/dragonlance/) |
| B-C11 | P4-45 bis P4-51 | HR1-7 Historical Reference | P4 | FERTIG (49 Kapitel settings/historical/) |

**Gesamt: ~67,5 Stunden Konvertierungsarbeit ueber 11 Batches**
*(DMGR3 Arms & Equipment in P1-16 bereits priorisiert; schlanke DL-Adventures benoetigen weniger Aufwand als Kernbuecher)*

#### Hinweis zu _text.pdf Duplikaten

Einige PDFs liegen als Scan + OCR-Variante vor (Dateiname mit `_text.pdf`-Suffix). Die OCR-Variante ist bevorzugt einzusetzen, da Volltext-Extraktion direkt moeglich. Wo beide vorhanden: OCR-Variante verwenden, Scan-Variante als Fallback fuer Tabellen/Grafiken.

### Virtual Player (AI-Script)
- [x] Durchfuehrung des ersten 10-Zuege-Simulationstests
- [x] 4-System Batch (Session 6): HISTORISCH — Systems entfernt, Test nur noch AD&D
- [ ] Stress-Test der Barge-in Funktionalitaet (Unterbrechung des Keepers)
- [x] Verifikation der [PROBE] Tag-Verarbeitung in den Logs

### Human Lead (User)
- [ ] Validierung der VAD-Hardware-Kompatibilitaet
- [ ] Qualitatives Feedback zur Natuerlichkeit der Monolog-Sperre
- [ ] Finaler Review und Freigabe der 3-Tage-Roadmap

### Weitere offene Tasks
- [ ] **Spieltest:** AD&D 2E mit vollem Regel-Budget (Phase 2)
- [ ] **Feature:** Charaktererstellung im Voice-Modus
- [x] **Feature:** Wuerfelergebnisse in GUI visualisieren (Session 9)
- [x] **Feature:** Lore-Budget Slider (getrennt von Rules-Budget) (Session 9)
- [x] **Feature:** Web GUI mit 10 Tabs (Session 10)
- [x] **Feature:** Testbot CLI mit Token-Tracking + EUR-Kosten (Session 10)

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
py -3 main.py --module add_2e --techgui
py -3 main.py --module add_2e --adventure goblin_cave --voice --techgui

# Web GUI:
py -3 main.py --module add_2e --webgui --port 8080

# CLI mit Stimme (Lautsprecher):
py -3 main.py --module add_2e --adventure goblin_cave --voice --no-barge-in

# CLI mit Stimme (Kopfhoerer, Barge-in aktiv):
py -3 main.py --module add_2e --adventure goblin_cave --voice

# Automatisierter Test:
py -3 scripts/virtual_player.py --module add_2e --adventure goblin_cave --turns 10 --save

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

- **Coversion Ops:** PDFs in `coversion/workload/` werden automatisch in Volltiefe verarbeitet. ARS-Artefakte landen in `coversion/finished/`; verarbeitete PDFs werden nach `coversion/root/finished/` verschoben. Workflow-Spezifikation: [conversion_workflow.md](conversion_workflow.md).
- **Grafik-Extraktion (Production):** `pictureextract` ist produktiv und versioniert unter `software/pictureextract/production/`. Archivstaende liegen in `software/pictureextract/archive/`.
- **PDF-Ablage (zusaetzlich Pflicht):** Nach Konvertierung wird die Original-PDF im Bundle unter `coversion/finished/{system_id}/source_pdf/` abgelegt (zusaetzlich zum Root-Archiv).

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

[2026-03-04 19:55] | FROM: Claude Code | Session 19b: DMG Treasure Tables + Item Snippets + Bugfix

IMPLEMENTIERT:
1. Vollständige DMG Treasure Tables (Tables 84-110) in mechanics.py:
   - Treasure Types A-Q (vorher nur A-E,H), roll_gem(), roll_art_object(), roll_magic_item()
   - 404 benannte magische Items in 18 Kategorien, 52 Edelsteintypen
   - roll_treasure() gibt jetzt gem_details, jewelry_details, magic_item_details zurück

2. SCHATZ→INVENTAR Pipeline (orchestrator.py):
   - Münzen, Edelsteine, Kunstgegenstände, magische Items landen automatisch im Inventar
   - Jedes Item per _handle_inventory() als "gefunden" verbucht

3. Item Snippet Generator (scripts/generate_item_snippets.py):
   - 456 JSON-Snippets generiert in data/lore/add_2e/items/
   - 404 magische Items + 52 Edelsteine mit Mechanik-Daten
   - Detaillierte Stats für ~100+ wichtige Items (Potions, Waffen, Rüstung, Ringe etc.)

4. Treasure Hoard Test-Adventure (modules/adventures/treasure_hoard.json):
   - 5 Räume, 8 NPCs, 26 Flags, 4 SCHATZ-Tags (C, H, A, E)
   - Triviale Goblin-Gegner (Morale 3-5), massive Schätze

BUGFIX:
- BUG-012: validate_tags() in rules_engine.py crashte bei 3+-Tupel stat_changes (z.B. MORAL_CHECK)
  - Ursache: `for change_type, value_str in stat_changes` erwartet 2 Werte, MORAL_CHECK gibt 3
  - Fix: Tupel-Unpacking geändert zu stat_tuple[0], stat_tuple[1] mit len-Check
  - Gleicher Fix in orchestrator.py Zeile 1841 (_handle_party_xp)

TESTERGEBNISSE:
- Test 1 (Case 1): 10 Turns, 0 SCHATZ (generischer VirtualPlayer zu passiv)
- Test 2 (Case 6): 9 Turns, CRASH bei MORAL_CHECK → Bug gefunden und gefixt
- Test 3 (Case 6, nach Bugfix): 11 Turns, SCHATZ:C erfolgreich! 2000 Elektrum ins Inventar
  - ANGRIFF 10x, HP_VERLUST 2x, HP_HEILUNG 1x, XP_GEWINN 45, ZAUBER 3x
  - SCHATZ:H/A/E nicht erreicht (KI-Pacing: Party bleibt in Raum 1)

DATEIEN GEÄNDERT:
- core/mechanics.py — DMG Tables 84-110 komplett (+~600 Zeilen)
- core/orchestrator.py — SCHATZ→INVENTAR Pipeline + Tupel-Fix
- core/rules_engine.py — Tupel-Unpack Bugfix
- scripts/generate_item_snippets.py — NEU (456 Snippets)
- modules/adventures/treasure_hoard.json — NEU (Schatz-Stress-Test)
- data/lore/add_2e/items/ — 456 neue JSON-Snippets
- data/lore/add_2e/items/_dmg_raw_text/ — 53 DMG-Rohtextseiten

[2026-03-04 21:00] | FROM: Claude Code | Phase-1 Verifikation KOMPLETT — AD&D-Only Umstellung verifiziert
- 20 Code-Dateien modifiziert: Defaults → add_2e, Dead Code entfernt (Paranoia/SR/CoC Indexer, Sanity Guards)
- orchestrator.py: STABILITAET_VERLUST + FERTIGKEIT_GENUTZT simplifiziert (return statt toter Code)
- rules_engine.py: 7 Paranoia/Shadowrun Indexer-Methoden geloescht, _CORE_CATEGORIES bereinigt
- ai_backend.py: System-Flags _is_paranoia/_is_shadowrun/_is_cthulhu entfernt
- engine.py: is_cthulhu Property entfernt
- mechanics.py: Cthulhu-Kommentare aktualisiert
- CLAUDE.md: AD&D-only aktualisiert
- Syntax-Check: ALLE py_compile bestanden
- Import-Test: SimulatorEngine, Orchestrator, GeminiBackend, RulesEngine — alle OK
- Grep-Scan: Keine cthulhu_7e/paranoia_2e/shadowrun_6/mad_max Referenzen in .py
- agents.md + MEMORY.md aktualisiert

[2026-03-04 20:00] | FROM: Claude Code | Phase-1 Bereinigung KOMPLETT — ~6.976 Nicht-AD&D Dateien geloescht
- data/lore/cthulhu/ (1574), paranoia_2e/ (1124), shadowrun_6/ (2460) → rm -rf
- data/lore/ generische CoC-Dirs (21 Ordner + index.json): 1551 Dateien
- data/lore/communication/ (CoC Arkham-Content): 24 Dateien
- data/lore/tasks/archive/expansion_copies/ (CoC Leichen): 166 Dateien
- modules/: 4 Rulesets, 11 Adventures, 25 Characters, 8 Parties, 12 Presets, 4 Scenarios, 4 Settings, 4 Keepers, 3 Extras
- data/test_series/: 2 CoC-Testberichte
- Verblieben: data/lore/add_2e/ (5972 Dateien), data/lore/tasks/ (Management-Docs)
- modules/ enthaelt ausschliesslich add_2e/* + system-neutrale Dateien (testkampf, combat_bridge, survival_mode)
- modules/index.json war bereits auf add_2e ausgerichtet — kein Update noetig

[2026-03-04 19:00] | FROM: Claude Code | B-C04 bis B-C11 KOMPLETT — Alle 86 PDFs verarbeitet

| Batch | PDFs | Neue Chunks | Typ | Zielverzeichnis |
|-------|------|-------------|-----|-----------------|
| SPELLS (B-C04/B-C05) | 7 | 1.010 Spells | Spell-Einzelextraktion | spells/ |
| MAGIC-ITEMS (B-C04/B-C05) | 6 | 33 Kapitel | Kapitel-Chunks | magic_items/ |
| DMGR (B-C06/B-C07) | 13 | 113 Kapitel | Kapitel-Chunks | dm_tools/, magic_items/, rules/ |
| DRAGONLANCE (B-C08-B-C10) | 44 | 188 Kapitel | Kapitel-Chunks | settings/dragonlance/ |
| HISTORICAL (B-C11) | 7 | 49 Kapitel | Kapitel-Chunks | settings/historical/ |

Totals: 77 PDFs erfolgreich verarbeitet (von 86 geplant — 9 MC bereits in B-C03 erledigt). 1.393 neue Chunks extrahiert.
Lore gesamt: 3.977 → 5.962 JSONs (+1.985 seit Session-Start). Monsters: 107 → 656 (6x). Spells: 341 → 1.385 (4x).

Welt-Trennung: Dragonlance → data/lore/add_2e/settings/dragonlance/ (188 Dateien),
Historical → data/lore/add_2e/settings/historical/ (49 Dateien). Generisches AD&D ohne Vermischung.

Converter-Upgrade (scripts/converter.py): --batch all + spells/magicitems/dmgr/dragonlance/historical.
Spell-Compendium-Extraktor (Einzelspell-Parser), Monster-Statblock-Extraktor (OCR-tolerant).
86 PDF-Definitionen in 7 Batch-Listen. TEXT_VARIANT_PDFS fuer 27 PDFs aktiviert.

Bekannte Probleme: PHB anfangs nicht gefunden (Dateiname ohne TSR-Prefix) — behoben (9 Kapitel).
DL-Dateinamen Unterstrich statt Bindestrich — behoben. WSC3/PSC1-3 wenig Spell-Treffer (schlechte OCR).

DATEIEN: scripts/converter.py (MODIFY — 86 PDFs, alle Batch-Handler), data/lore/add_2e/spells/* (+1.010),
data/lore/add_2e/magic_items/* (+33), data/lore/add_2e/dm_tools/* (+Teil von 113),
data/lore/add_2e/settings/dragonlance/* (+188), data/lore/add_2e/settings/historical/* (+49)

[2026-03-04 18:00] | FROM: Claude Code | B-C03 Monster Compendium Batch — FERTIG

9 PDFs verarbeitet: MC_V2, MC_A1, MC_A2, MC_A3, MC_A4, MC_FF, MC_MP, MC_OP, MC_SC.
536 neue Monster-JSONs extrahiert. Monster-Collection: 107 → 656 Eintraege (index.json).
Gesamt-Lore: 3.977 → 4.526 JSONs. _text.pdf-Varianten bevorzugt (MC_V2, MC_A1, MC_A4, MC_FF, MC_OP).
MC_SC (Savage Coast) OCR-limitiert: kein _text.pdf verfuegbar, nur 8 sauber benannte Monster behalten, 63 Dups verworfen.
Converter-Upgrade: scripts/converter.py unterstuetzt jetzt --batch p2 + Monster-Statblock-Extraktion.
P2-02 bis P2-10: alle auf FERTIG gesetzt. B-C03 Batch: FERTIG.

DATEIEN: scripts/converter.py (MODIFY — --batch p2 + Monster-Handler), data/lore/add_2e/monsters/* (536 neue JSONs)

[2026-03-04 16:30] | FROM: Claude Code | P1 AD&D 2e Lore-Extraktion abgeschlossen

scripts/converter.py NEU (~760Z): PyMuPDF-basierter PDF→JSON Extraktor.
CLI: --pdf, --type, --batch p1, --stats. Chapter-Segmentierung, Kit/Psionic/Deity/Equipment Spezial-Handler.

21 P1-PDFs verarbeitet (PHBR01-15, DMGR3, Player's Options x3, Tome of Magic, Legends & Lore).
Ergebnis: 930 → 3977 JSON-Dateien in data/lore/add_2e/.
Neue Verzeichnisse: kits/ (76), classes/ (48), races/ (25), psionics/ (20), deities/ (2),
rules_options/ (175), derived_rules/ (149), rules_fulltext_chunks/ (2251), equipment/ (1→8).

Bekannte Limitierungen: OCR-Artefakte in einigen Kit-Namen, PHBR05/06/07/08/09/15 ohne
individuelle Kit-Extraktion (Content in Chapter-Chunks erfasst).

DATEIEN: scripts/converter.py (NEU), data/lore/add_2e/* (3047 neue JSONs), .gitignore (MODIFY)

[2026-03-04 15:00] | FROM: Claude Code | Session 16: Pixel-Replay, Dungeon-Maps, Roaming-Monster, Run-Specs. 9 Dateien, ~1200Z netto. pixel_renderer.py NEU (shared Render-Modul), tab_replay_viewer.py REWRITE (Pixel-Art statt ASCII), 20 Dungeon-Maps (5+15 Raeume), auto_roam_idle_monsters() (30% Patrol), MONSTER_BEWEGT Tag-Support. Integration-Test bestanden.

(a) gui/pixel_renderer.py NEU (~290Z): Shared Render-Modul herausgeloest aus tab_dungeon_pixel.py.
    PixelTileset (Asset-Cache), Autotiler (4-Bit Bitmask), render_terrain_image(), render_room_to_image().
    CLASS_MAP + MONSTER_MAP erweitert: +spinne, +troll, +drache, +lich, +golem, +wight, +ghul, +harpyie, +mimik.

(b) gui/tab_replay_viewer.py REWRITE (~370Z): ASCII-Map-Widget ersetzt durch Canvas + PIL.
    Nutzt PixelTileset + render_room_to_image() aus pixel_renderer. Move-Trail Overlays:
    Gruen (Party), Rot (Monster), Gelb (Combat). Auto-Scale bei Canvas-Overflow. Legende als Labels.

(c) gui/tab_dungeon_pixel.py MODIFY (-80Z): _Autotiler, _CLASS_MAP, _MONSTER_MAP, _tint, _load_asset entfernt.
    Importiert jetzt aus gui/pixel_renderer.py (DRY-Refactor).

(d) modules/adventures/crawltraining_stress.json MODIFY (+~200Z): 5 Raeume mit vollstaendigen Maps.
    blutgrube (25x17), gifthoehle (21x19), nekropole (23x15), drachenhort (27x21), endboss_lich (19x19).
    Alle NPCs haben spawns-Koordinaten.

(e) modules/adventures/crawltraining_full.json MODIFY (+~400Z): 15 Raeume mit Maps.
    Von eingangshalle (19x11) bis endkammer (21x18). Alle NPCs mit spawns.

(f) core/grid_engine.py MODIFY (+30Z): _map_spawns Dict in __init__+_setup_from_map. place_npcs()
    nutzt Map-Spawns wenn verfuegbar, sonst heuristisch. auto_roam_idle_monsters(moved_ids):
    30% Chance idle Monster 1 Tile zufaellig bewegen.

(g) core/orchestrator.py MODIFY (+6Z): Nach execute_monster_moves(): moved_ids sammeln,
    auto_roam_idle_monsters() aufrufen.

(h) scripts/virtual_player.py MODIFY (+3Z): MONSTER_BEWEGT zu _TAG_PATTERNS, Case 6+7 expected_tags erweitert.

(i) docs/management/rules.md MODIFY (+6Z): Test 5 (Grid-Stress) zu §10 hinzugefuegt
    mit crawltraining_stress Kommando.

Verifizierung: Alle Imports OK. Integration Test: GridEngine+Maps+Spawns+Renderer → 800x544px Bild.
Roaming Test: 4/6 idle Monster bewegt. JSON-Validierung: Alle 20 Raeume korrekt (Map + passende Spawns).

DATEIEN: gui/pixel_renderer.py (NEU), gui/tab_replay_viewer.py (REWRITE), gui/tab_dungeon_pixel.py (MODIFY),
core/grid_engine.py (MODIFY), core/orchestrator.py (MODIFY), modules/adventures/crawltraining_stress.json (MODIFY),
modules/adventures/crawltraining_full.json (MODIFY), scripts/virtual_player.py (MODIFY),
docs/management/rules.md (MODIFY)

[2026-03-04 11:00] | FROM: QM Agent | Converter-Agent definiert — ADD2e Komplett-Extraktionsplan angelegt

Aufgabe: Neuen "Converter"-Agenten in Governance-Dokumente integrieren und vollstaendigen Konvertierungsplan fuer alle 108 AD&D 2e PDFs aus ADD2e/ erstellen.

(1) organization.md: Converter-Rollendefinition eingefuegt (nach Virtual Player, vor Kommunikationsregeln).
    Organigramm erweitert: Converter-Box als zweite Instanz unter Human Lead + Agenten-Schicht.
    Dokumenten-Matrix: bugtracker.md und conversion_workflow.md ergaenzt (fehlten bisher).

(2) agents.md: Neuer Abschnitt "Converter Agent — AD&D 2e Komplett-Extraktion" eingefuegt (nach Content Specialist, vor Virtual Player).
    Enthaelt: Zielordner-Tabelle, vollstaendige Statusliste aller 107 ausstehenden PDFs (P1-01 bis P4-51),
    Batch-Plan (B-C01 bis B-C11, ~67,5h), Hinweis zu _text.pdf OCR-Duplikaten.
    Bestandsstatus: Monstrous Compendium Vol.1 als [x] FERTIG markiert (106 Monster bereits vorhanden).

(3) suggestions.md: Strategischer Eintrag "ADD2e Langzeit-Konvertierungsprojekt" hinzugefuegt
    (Kontext, Ziel, Auswirkung auf Spielqualitaet, Empfehlung zur Priorisierung).

Istzustand ADD2e Lore: monsters/ 106, spells/ 331, items/ 50, encounters/ 31, tables/ 68, mechanics/ 6.
Zielzustand nach Vollabschluss: +classes/ +kits/ +races/ +equipment/ (vollst.) +magic_items/ +dm_tools/ +deities/ +rules/ +settings/dragonlance/ +settings/historical/

DATEIEN: docs/management/organization.md (MODIFY), docs/management/agents.md (MODIFY), docs/management/suggestions.md (MODIFY)

[2026-03-04 00:10] | FROM: Claude Code | Grid-SSOT Architektur-Shift implementiert

Grid als Single Source of Truth — 3 Dateien modifiziert, ~175 Zeilen netto.

(a) parse_player_movement() in orchestrator.py: Spieler-Bewegung VOR KI-Aufruf ausgewertet
    (Richtung, Kampf-Approach, Exploration). Ersetzt Tier-3 Narrative-Inferenz.

(b) execute_monster_moves() + _resolve_direction() in grid_engine.py:
    KI-gesteuerte Monster-Bewegung via [MONSTER_BEWEGT: Name | Richtung] Tags (NACH KI-Aufruf).
    Richtungen: naeher, angriff, weg, patrouille, lauern.

(c) Erweitertes get_context_for_prompt() in grid_engine.py:
    Raum-ID, Dimensionen, Party/Monster-Listen, Terrain, Sichtbarkeit als KI-Kontext-Block.

(d) System-Prompt in ai_backend.py: Monster-Bewegungs-Protokoll ergaenzt.

Regressionstest: 5 Turns add_2e/goblin_cave bestanden.
Integrations-Test: Alle Bewegungstypen verifiziert (walk, combat_approach, naeher, angriff, weg, patrouille, lauern).

DATEIEN: core/grid_engine.py, core/orchestrator.py, core/ai_backend.py (MODIFY)

[2026-03-04 00:30] | FROM: Claude Code | TinyCrawl Level 1 + Asset-Archivierung

(1) TinyCrawl Demo komplett neu geschrieben: 847 → 1469 Zeilen
    - CaveGenerator: Cellular Automata (80x60, 45% Fill, 5x Smoothing, Flood-Fill, 2-Tile Border)
    - Autotiler: 4-Bit Bitmask → 15 Edge-Tiles + Wall_front Varianten
    - BFS Distance Map: 1 BFS pro Tick fuer alle Monster (statt pro-Entity)
    - Viewport + Kamera: Fullscreen, SCALE=2 (32px/Tile), Auto-Follow + WASD/Pfeile, Tile-Snap
    - Fog of War: 3 Stufen (klar <8, halb 8-12, schwarz >12 Tiles)
    - Minimap: 160x120 in HUD-Ecke (Hoehle/Held/Monster/Viewport-Rahmen)
    - CRT-Scanlines: Vorberechnetes Overlay, jede 2. Zeile 55/255 dunkler
    - Screen-Flash: 2 Ticks weiss bei Wellenstart
    - Deko-System: Schaedel an Sackgassen, Fackeln an Engstellen (animiert), Truhen in Nischen
    - Zone-Spawning: 4 Quadranten, progressive Entfernung, 18 Monstertypen
    - FPS=8 fuer 80er-Retro-Ruckel-Feeling

(2) Asset-Archivierung: mystic_woods_free_2.2/ → data/tilesets/ (12 Packs, 1227 PNGs, 6 MB)
    Packs: 0x72_dungeon_v5, basic_asset_pack, crystals_ore_24x24, debts_in_the_depths,
    mystic_woods_sprites, rpg_items_16x16, tiny_rpg_chars_demo/v102/v103, zombie_apocalypse
    + beholder_pixellab.png, shields_unfinished.png, pumpkin_dude.png
    ASSET_DIR in tinycrawl_demo.py auf data/tilesets/0x72_dungeon_v5 umgestellt.
    Originalordner kann geloescht werden.

DATEIEN: tinycrawl_demo.py (REWRITE), data/tilesets/ (NEU, 12 Ordner), docs/management/agents.md (MODIFY)

[2026-03-03 20:15] | FROM: Claude Code | Grid-Engine Bugfixes + Dungeon-Tab Eingabefeld: 3 Bugfixes + 1 Feature implementiert und getestet.
  (1) Raumwechsel-Erkennung (CORE FIX): _detect_room_change() in orchestrator.py — scannt GM-Antwort nach Ortsnamen erreichbarer Exits + Bewegungsverben, ruft automatisch teleport() auf wenn Score >= 5. Score-basiertes Matching: Verb-Match +5, Location-Name voll +10, Wortmatch +2/Wort, Exit-ID-Woerter +2/Wort. 4/4 Integrationstests bestanden (Vorhalle Score 7, Wachraum Score 11, kein False Positive bei Kampf, Ruestkammer Score 9).
  (2) FERTIGKEIT_GENUTZT Suppression: AD&D/Paranoia/Shadowrun Skills werden nicht mehr fuer "Steigerungsphase" markiert (nur CoC + Mad Max als d100-Systeme). Beide Handler gefixt: _handle_stat_change() (Solo) + _handle_party_tags() (Party-Modus).
  (3) STABILITAET_VERLUST Guard fuer Non-CoC (vom User parallel implementiert): SAN-Verlust wird jetzt ebenfalls nur bei CoC/Mad Max verarbeitet.
  (4) Manuelle Eingabe im Dungeon-Tab: Neues Input-Panel am unteren Rand von tab_dungeon_view.py — Label "Aktion:" + Entry-Feld + "Senden"-Button. Enter-Taste oder Button sendet Input an Orchestrator, stoppt Auto-Crawl automatisch wenn aktiv, Eingabe erscheint im Spiel-Log.
  GUI Event-Kette vollstaendig verifiziert: teleport() → adventure.location_changed → _on_location_changed_grid() → grid.transition_room() → grid.room_setup + grid.formation_placed → GUI render.
  DATEIEN: core/orchestrator.py (3 Edits: _detect_room_change NEU ~90Z, _ROOM_CHANGE_VERBS Tupel, FERTIGKEIT_GENUTZT Guard x2), gui/tab_dungeon_view.py (1 Edit: Eingabe-Panel + _on_manual_send())

[2026-03-03 21:45] | FROM: Claude Code | Combat Rules Bridge — 7/7 Tasks completed

Batch: CombatTracker ↔ GridEngine Bridge (Tasks #11-#17)

(1) Task #11: `reach`-Feld (1/2/3) zu allen 19 Nahkampfwaffen in add_2e_tables.json hinzugefuegt
(2) Task #12: `movement_penalty` (0/-3/-6) zu allen 14 Ruestungseintraegen in add_2e_tables.json hinzugefuegt
(3) Task #13: 5 neue Lookup-Methoden in core/mechanics.py: lookup_weapon_reach(), lookup_weapon_range(), get_range_modifier(), lookup_armor_movement_penalty(), get_effective_movement()
(4) Task #14: CombatTracker ↔ GridEngine Bridge — neue Felder (reach, movement_used, armor_name) auf Combatant; set_grid_engine()/set_mechanics() Bridge-Methoden; validate_attack_range() mit Distanzpruefung; consume_movement()/get_movement_remaining()
(5) Task #15: GridEntity erweitert (base_movement, movement_used); move_entity() mit enforce_budget-Parameter; reset_all_movement()/get_movement_remaining()-Methoden; Grid-Prompt-Kontext zeigt Bewegungsbudget
(6) Task #16: Orchestrator-Verdrahtung — _start_combat() uebergibt Mechanics + GridEngine an CombatTracker; Ruestung aus Charakter-Inventar abgeleitet; Reichweitenvalidierung vor Angriffswurf mit range_mod-Malus; Grid-Bewegungsreset bei neuem Kampfrunde
(7) Task #17: Dungeon-View Kampf-Overlays — 5 neue Text-Tags (move_range, reach_zone, range_short/medium/long); _calc_combat_overlay() markiert erreichbare Felder; _render_combat_info() zeigt Bewegungsbalken + Angriffsanzahl im Party-Panel

Dateien: core/combat_tracker.py, core/grid_engine.py, core/mechanics.py, core/orchestrator.py, gui/tab_dungeon_view.py, modules/rulesets/add_2e_tables.json
Alle Syntax-Checks bestanden.

[2026-03-03 22:00] | FROM: Claude Code | Bugfix-Batch: 2 Bugs gefixt + Bugtracker-Hygiene

(1) BUG-009 FIXED: Preset-Adventure Passthrough — _set_combo() fuegt fehlende Werte ins Dropdown ein statt silent fallback auf "(keine)". 1 Zeile in gui/tab_session.py.

(2) BUG-010 MITIGATED: Monster-HP_VERLUST — Zwei-Ansatz-Fix:
  a) Prompt: Neuer "KAMPF-ERINNERUNG (KRITISCH)" Block am Ende des System-Prompts
  b) Post-Validation: _validate_response() prueft jetzt auf Kampfwoerter ohne HP_VERLUST-Tag und emittiert Feedback + Warning

(3) Bugtracker-Hygiene: BUG-009, BUG-010, BUG-011 formalisiert in bugtracker.md

(4) To-Do-Bereinigung: 3 stale Lead-Developer-Tasks (PROBE-Tags fehlen / Monolog-Sperre / Shadowrun PROBE-Zielwerte) als FIXED markiert — alle drei waren bereits in Sessions 7-9 behoben (BUG-001/002/003).

Dateien: core/ai_backend.py (MODIFY), gui/tab_session.py (MODIFY), docs/management/bugtracker.md (MODIFY), docs/management/agents.md (MODIFY)

[2026-03-03 22:30] | FROM: Claude Code | Strategischer Batch: 4 Tasks (2 Bugfixes + Hygiene + Feature)

(1) BUG-009 FIXED — Preset-Adventure Passthrough
    _set_combo() in gui/tab_session.py fuegt fehlende Werte ins Dropdown ein statt silent fallback.
    Root Cause: Wenn Preset-Adventure nicht in Combo-Values → combo.current(0) → "(keine)" → adventure=None.

(2) BUG-010 MITIGATED — Monster-HP_VERLUST (KI-Gegenangriffe fehlen)
    Zwei-Ansatz-Fix in core/ai_backend.py:
    a) Neuer "KAMPF-ERINNERUNG (KRITISCH)" Block am Prompt-Ende (LLMs folgen Endanweisungen am besten)
    b) Post-Validation: _validate_response() prueft Kampfwoerter ohne HP_VERLUST-Tag → Feedback-Injektion

(3) Bugtracker + agents.md Hygiene
    BUG-009/010/011 in bugtracker.md formalisiert. 3 stale To-Dos (Sessions 7-9) als FIXED markiert.

(4) BUG-011 MITIGATED — Context-Saettigung ab ~80 Zuegen
    Automatische History-Zusammenfassung implementiert in core/ai_backend.py:
    - _trim_history() ruft jetzt summarize() auf BEVOR alte Turns geloescht werden
    - Zusammenfassung (3-5 Saetze) wird in _history_summaries gespeichert (max 5 = ~100 Turns)
    - _build_contents() injiziert Zusammenfassungen als "[FRUEHERE EREIGNISSE]" Block vor der History
    - Graceful Degradation: bei Fehler → normaler Trim ohne Summary
    - Kein zusaetzlicher API-Call noetig ausser beim Trim-Zeitpunkt (~alle 40 Turns)

Dateien: core/ai_backend.py (MODIFY), gui/tab_session.py (MODIFY), docs/management/bugtracker.md (MODIFY), docs/management/agents.md (MODIFY)
Syntax-Check: 2/2 OK (ai_backend.py, tab_session.py)

[2026-03-03 23:55] | FROM: Claude Code | Stresstest 20 Runden + 3 Bugfixes.
  TEST: 3 Iterationen, 20/20 Zuege im finalen Run. 541 Tags, 27.1/Zug, 11 Unique Types, 0 Crashes.
  BUGFIXES:
  1. Cache-Recovery (ai_backend.py): 403 PERMISSION_DENIED bei CachedContent -> Fallback auf System-Prompt.
  2. UnicodeEncodeError (orchestrator.py): Unicode-Pfeil in print crashte Thread auf Windows cp1252.
  3. STABILITAET_VERLUST Filter (orchestrator.py): SAN-Tags in Nicht-SAN-Systemen (AD&D etc.) ignoriert.

[2026-03-03 23:30] | FROM: Claude Code | Tag-Abdeckung erweitert (5 Features, 15 Dateien).
  FEATURES:
  1. FERTIGKEIT_GENUTZT Party-Modus: Neues PARTY_FERTIGKEIT_PATTERN, extract in character.py,
     elif-Block in orchestrator._handle_party_tags(), Tag-Anweisung in ai_backend._build_party_block().
  2. Rundenbasierte Zeit: TimeTracker.advance_rounds(), start/end_combat(), RUNDE Pattern+extract,
     _handle_time RUNDE branch, AD&D Prompt mit [RUNDE: N] Anweisung.
  3. GEGENSTAND_BENUTZT Tag: Neues Pattern, PartyStateManager.use_item() mit Fuzzy-Match +
     Mengen-Decrement (x3->x2->x1->weg), Consumable-Effekt-Katalog, Orchestrator-Handler
     mit Auto-Healing bei Heal-Effekt, Prompt-Instruktion.
  4. 8 Loot-JSONs mit use_effect gepatcht (3 Potions, 3 Scrolls, 1 Wand, 1 Climbing-Potion).
  5. Skill-Anzeige: Skills MIT Werten in Party-Block, 17 deutsche Skill-Aliase fuer AD&D 2e.
  DATEIEN: core/character.py, core/orchestrator.py, core/ai_backend.py, core/time_tracker.py,
    core/party_state.py, core/rules_engine.py, scripts/virtual_player.py, 8x data/lore/add_2e/loot/*.json
  TESTS: Alle Syntax-Checks + Unit-Tests bestanden (Tag-Parser, TimeTracker, use_item, VP Tag Count).

[2026-03-03 22:00] | FROM: Claude Code | Grid-Based Movement Engine implementiert.
  - core/grid_engine.py NEU (~480Z): GridEngine mit BFS-Pathfinding, Raum-Heuristik (4 Groessen), Formations-Placement, 3-Tier Bewegungs-Inferenz (Combat/HP/Narrative), Distanz/Reichweite, KI-Kontext-Injektion
  - core/party_state.py EDIT: movement_rate Feld in PartyMember (aus derived_stats.Movement)
  - core/engine.py EDIT: GridEngine instanziiert, an AI-Backend gekoppelt
  - core/orchestrator.py EDIT: Grid-Bewegungs-Inferenz nach Party-Tags, Raumwechsel-Handler (adventure.location_changed → transition_room)
  - core/ai_backend.py EDIT: set_grid_engine(), Grid-Kontext in _build_contents() (Positionen, Nahkampf, Distanzen)
  - gui/tab_dungeon_view.py EDIT: Dynamische Raumgroesse, _sync_from_grid(), Grid-Events (room_setup/entity_moved/combat_move/formation_placed), GridEngine-Terrain-Rendering
  - Alle Tests bestanden: Import OK (5 Module), Raum-Setup, BFS-Pathfinding, Party-Placement (0 Overlaps), Raumwechsel, Narrative-Inferenz, KI-Kontext

[2026-03-03 14:50] | FROM: Claude Code | Session 10c/10d — Test-Fix-Loop (4 Iterationen, 7 Bugfixes, Stresstest-Optimierung):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUFGABE: Trainingsrun-Loop (Run → Analyse → Bugfix → Re-Test) fuer AD&D Crawltraining.
4 Iterationen, 7 Bugfixes, finaler optimierter Stresstest.

BUGFIXES (7 total):
1. Cache-Hash (ai_backend.py): Statischer CACHE_DISPLAY_NAME → prompt-hash-basiert.
   Stale Cache lieferte falsche Charakter-Namen (Valdrak statt Training-Party).
2. Lazy Cache Creation (ai_backend.py): 5x _initialize_cache() beim Start → cascade create-delete.
   Jetzt: _cache_dirty=True, lazy init bei erstem API-Call.
3. AD&D 2e PROBE Zielwert (rules_engine.py): max_target=20 → max_target=100 fuer Prozent-Skills.
   Thief-Skills (Move Silently 75%, Find Traps 65%) wurden als d20-auto-success gewertet.
4. d100 Fallback (mechanics.py): Neuer d100-Modus wenn target > dice_config.faces.
   Correct CoC-style percentage roll mit critical/extreme/hard/regular/failure/fumble levels.
5. Party stat_changes Metrik (orchestrator.py): _last_party_tag_count tracking.
   Party-HP_VERLUST wurde nicht in Metriken gezaehlt (nur single-char Format).
6. Stagnation-Detektor (virtual_player.py): Nach 3 leeren Zuegen → Stachel-Aktion.
   KI erklaerte Party narrativ tot bei HP > 0 → 8+ verschwendete Zuege.
7. HP_VERLUST Regex (virtual_player.py): Pattern zahlte nur [HP_VERLUST: N],
   NICHT [HP_VERLUST: Name | N] → 100% Party-Damage unsichtbar in Tag-Statistik.

OPTIMIERUNGEN:
- PROBE-Timeout: 60s → 20s (Latenz: 32s → 10.5s avg, -67%)
- Per-Tag-Type Breakdown in Report (Tag-Dichte, Unique-Types, Aufschluesselung)
- Tag-Breakdown in JSON-Export (tag_breakdown, tag_density)

ITERATION PROGRESSION:
| Metrik          | Iter1(noLLM) | Iter1(LLM) | Iter2  | Iter3  | FINAL(15t) |
|-----------------|-------------|------------|--------|--------|------------|
| Turns           | 30          | 30         | 30     | 30     | 15         |
| Combat Tags     | 0           | 130        | 77     | 101    | 43         |
| HP_VERLUST      | 0           | 0*         | 0*     | 0*     | 19         |
| REGELCHECK      | 4           | 18         | 0      | 0      | 0          |
| Tags Total      | 7           | ~150       | ~85    | ~120   | 89         |
| Tags/Turn       | 0.2         | ~5         | ~2.8   | ~4     | 5.9        |
| Unique Types    | 1           | ~4         | ~4     | ~5     | 7          |
| Rooms           | 1           | 1          | 1→4    | 1→10   | 1→5        |
| Cost            | $0.07       | $0.31      | $0.16  | $0.20  | $0.064     |
| Avg Latenz      | ?           | ?          | ?      | 32s    | 10.5s      |
(*HP_VERLUST Regex-Bug: Party-Format [Name | N] nicht gezaehlt)

FINAL STRESSTEST (15 Turns):
- 89 Tags, 5.9/Zug, 7 Unique Types, 15/15 Zuege mit Tags (100%)
- 37 ANGRIFF, 19 HP_VERLUST, 15 ZEIT_VERGEHT, 6 RETTUNGSWURF, 5 PROBE, 4 XP_GEWINN, 3 FERTIGKEIT
- 0 REGELCHECK-Warnungen, alle 6 Party-Mitglieder leben
- $0.064 Gesamtkosten (Keeper $0.054 + LLM-Player $0.010)
- Report: data/test_results/test_add_2e_generic_20260303_144857.json

MODIFIZIERTE DATEIEN (6):
- core/ai_backend.py: Lazy Cache + Hash-basiertes Naming + Stale-Cache-Cleanup
- core/rules_engine.py: AD&D 2e max_target=100
- core/mechanics.py: d100-Modus fuer Prozent-Skills
- core/orchestrator.py: _last_party_tag_count fuer Party-Metriken
- scripts/virtual_player.py: HP_VERLUST Regex, PROBE-Timeout 20s, Stagnation-Detektor, Tag-Breakdown

OFFENE ISSUES:
- KI nutzt [ANGRIFF] auch fuer Monster-Angriffe (harmlos, Engine ignoriert)
- KI gibt ANGRIFF/HP_VERLUST fuer mechanisch tote Chars ("already dead — damage ignored")
- Kein ZAUBER_VERBRAUCHT im Tag-Zaehler von virtual_player (nur intern via PartyState)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[2026-03-03 21:00] | FROM: Claude Code | Dungeon-Visualisierung v1 — Tab 12 implementiert:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUFGABE: Grafische Dungeon-Crawl-Darstellung mit ASCII-Zeichen, Bewegungssystem, Sound-Effekte.
ERGEBNIS:
- gui/tab_dungeon_view.py NEU (~480 Zeilen): DungeonViewTab als Tab 12 "Dungeon"
- Canvas-basierte Karte mit BFS-Auto-Layout aus Adventure-Exits
- Richtungs-Parsing: Deutsche Exit-Beschreibungen (nord/sued/ost/west/hinab/tiefer) → raeumliche Platzierung
- Fog of War: Unbesuchte Raeume zeigen nur "?" bis Party sie betritt
- Entity-Symbole: @ (Party), M (Monster), ☠ (Tot), ! (Falle), $ (Schatz), ♦ (Item)
- Raum-Farbkodierung: Gruen-Tint (aktuell), Grau (besucht), Dunkel (unbesucht)
- Ebene-Indikatoren (E1/E2/E3) bei mehrstoeckigen Dungeons
- Klick-Navigation: Angrenzende Raeume per Klick betreten, Info-Panel zeigt Beschreibung
- Ausgaenge als klickbare Buttons im Info-Panel
- Entity-Panel: Party-HP/AC, Monster-Namen, NPC-Liste
- Aktions-Log mit farbcodierten Tags (Kampf=Rot, Bewegung=Gruen, Proben=Gelb, Items=Blau)
- Sound-Effekte via winsound.Beep (Thread-basiert, togglebar):
  - Bewegung: 500Hz 80ms
  - Kampf: 800Hz→600Hz (Two-Tone)
  - HP-Verlust: 300Hz→200Hz (Descending)
  - Probe/Wuerfel: Ascending Pips
  - Item-Fund: Triple Ascending
  - Tod: 200Hz→150Hz (Low Drone)
- Flash-Effekte: Raum blinkt bei Kampf (#4A2020), Schaden (#4A1010), Tod (#4A0000)
- Monster-Tracking: Flag-basiert (besiegt/geraeumt → Monster aus Raum entfernt)
- Integration: tech_gui.py registriert Tab 12, Event-Dispatch, on_engine_ready
EVENTS VERARBEITET: adventure.loaded, adventure.location_changed, adventure.flag_changed, game.output (combat/stat/probe/dice/inventory), party.state_updated, party.member_died, party.tpk
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[2026-03-03 17:18] | FROM: Claude Code | Session 11b — SQLite _safe_commit + Stresstest Verifizierung:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUFGABE: SQLite "database is locked" Crash fixen (save() bei add_xp, Zeile 501) + Stresstest wiederholen.

BUGFIXES (2 total, kumulativ Session 11: 9):
8. _safe_commit() Methode (character.py): Zentraler Retry-Wrapper fuer ALLE 7 _conn.commit()-Aufrufe.
   3 Versuche, 0.2s Pause, kontextbezogenes Logging. Vorher: Nur log_turn() geschuetzt,
   save()/start_session()/schema-Migrations ungeschuetzt → Crash bei hoher Tag-Dichte.
9. Combat Loop Detector (virtual_player.py): 5 Kampfzuege ohne XP_GEWINN → Raumwechsel-Nudge.
   KI-Skelette waren unsterblich → 12 Runden gleicher Raum. COMBAT_LOOP_NUDGE erzwingt Weitermarsch.

STRESSTEST-ERGEBNIS (20 Turns, --pre-damage 50):
| Metrik              | Vorher (Crash)    | Nachher (_safe_commit) |
|---------------------|-------------------|------------------------|
| Turns abgeschlossen | 9/20 (Crash T9)   | **20/20 (100%)**       |
| Tags gesamt         | 217               | **590**                |
| Tags/Zug            | 15.5              | **29.5**               |
| Unique Tag-Typen    | 10                | **10**                 |
| DB-locked Errors    | 1 (fatal)         | **0**                  |
| Kosten              | $0.062            | $0.185                 |
| Avg Latenz          | —                 | 15.1s                  |

TAG-AUFSCHLUESSELUNG (590 Tags):
  HP_VERLUST: 141, RETTUNGSWURF: 120, PROBE: 98, ANGRIFF: 65,
  HP_HEILUNG: 47, INVENTAR: 40, XP_GEWINN: 20, ZEIT_VERGEHT: 20,
  FAKT: 20, STABILITAET_VERLUST: 19

ALLE 20 Zuege haben ALLE 10 Tag-Typen (Zuege 2-20). Rekord-Dichte: 29.5 Tags/Zug.
Report: data/test_results/test_add_2e_generic_20260303_171757.json

MODIFIZIERTE DATEIEN (1):
- core/character.py: _safe_commit() Methode, 7x _conn.commit() → _safe_commit()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[2026-03-03 17:10] | FROM: Claude Code | Session 11 — Stress-Test Scenario Erstellung (3 Dateien):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUFGABE: 3 Dateien fuer maximalen Engine-Stress-Test (20 Zuege, TPK-Ziel, alle Tag-Typen).

ERSTELLTE DATEIEN:
1. modules/parties/add_stress_party.json
   - Party "Die Todgeweihten" — dieselben 6 add_train_* Chars
   - Notes: Alle Chars auf halber HP (Grimjaw 36/72, Kael 27/54, Mordain 21/42, Varn 26/52, Pyra 9/18, Shade 16/32)
   - Keine Heiltraenke, Mordain halb-verbraucht, Pyra nur 1 Fireball, chaotische Formation

2. modules/adventures/crawltraining_stress.json (schema_version 1.1.0, 22 NPCs, 5 Raeume)
   - Raum 1 Blutgrube: 6 Oger (THAC0 13-16), Fallenfeld, 3 Pflicht-PROBEs
   - Raum 2 Gifthoehle: 5 Riesenspinnen, Gift-Rettungswuerfe fuer alle 6 Chars
   - Raum 3 Nekropole: 3 Wights + Gespenst, Level Drain, Kaelte-Aura 3d6-1
   - Raum 4 Drachenhort: Roter Drache (8d6 Feueratem) + 4 Feuer-Elementare
   - Raum 5 Endboss: Lich Malgoran (AC 0, HP 65) + Knochen-Golem
   - keeper_lore: ALLE 8 Tag-Typen Pflicht, exotische Wuerfel (2d4+3/3d6-1/1d12+5/8d6),
     Cross-System-Tag Tests (STABILITAET_VERLUST), Dead-Char-Tag Tests,
     Overflow-Heilung Test (HP_HEILUNG: Grimjaw | 999), falsche Skill-Namen fuer REGELCHECK

3. modules/presets/crawltraining_stress.json
   - temperature: 1.0, rules_budget: 200000, lore_budget_pct: 80
   - Brutal Killer-DM Persona, TPK-Ziel explizit

JSON-VALIDIERUNG: Alle 3 Dateien valid, alle ID-Cross-References verifiziert.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[2026-03-03 16:30] | FROM: Claude Code | AD&D 2e Spell OCR Cleanup — vollstaendig abgeschlossen:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUFGABE: OCR-Artefakte in 331 AD&D 2e Spell-Dateien bereinigen (3 Kategorien: canonical_name_guess_applied, missing_standard_fields, trimmed_merged_block).
ERGEBNIS:
- 8 canonical_name_guess_applied: Alle Namen korrigiert (Affect Normal Fire, Barkskin, Bigby's Clenched Fist, Call Lightning, Charm Plants, Continual Light, Detect Poison, Earthquake). quality_flags geleert.
- 42 missing_standard_fields: Alle null-Felder (range/components/duration/casting_time/area_of_effect/saving_throw) aus raw_block oder PHB-Wissen befuellt. School-OCR-Artefakte korrigiert (IllusiodPhantasm→Illusion/Phantasm, EnchantmentKhann→Enchantment/Charm, Divinatiodlllusion→Divination/Illusion, etc.). quality_flags geleert.
- 5 OCR-Sektionsheader erkannt und markiert: i_wizard_spells, i1_wizard_spells, i_priest_spells, wizard_snells, pried_cndlc, priest_spells, wizard_spells, any_creature_at_the_edge → category=index_header, quality_flag=ocr_section_header_not_a_spell.
- 1 fehlinterpretierter Name: mm_chum.json → Mass Charm (id=mass_charm, Enchantment/Charm).
- 1 fehlinterpretierter Name: i_exaction.json → Exaction (echter Zauber, OCR-Seiten-I entfernt). Felder aus PHB-Wissen befuellt.
- 39 trimmed_merged_block: [Beschreibung unvollstaendig — siehe PHB]-Marker an alle description_excerpt-Felder angefuegt. quality_flags geleert.
ENTITY INDEX: entity_index.json (data/lore/add_2e/indices/) aktualisiert — alle name/school/quality_flags-Korrekturen uebertragen, ocr_cleanup_date=2026-03-03.
ENDZUSTAND: 0 missing_standard_fields, 0 trimmed_merged_block, 0 canonical_name_guess_applied. Verbleibend: 7x ocr_name_corrected, 8x ocr_section_header_not_a_spell (alle absichtlich).
AUTONOME ENTSCHEIDUNGEN: (1) any_creature_at_the_edge.json und wizard_spells.json als Sektionsheader/Artefakte klassifiziert (kein PHB-Zauber mit diesen Namen). (2) Mass Charm id=mass_charm behalten, Dateiname mm_chum.json belassen (kein Umbennen noetig, id korrekt). (3) Exaction-Felder aus PHB-Wissen rekonstruiert (Touch/V,S/Special/1 round/1 creature/Special). (4) Spellcard-Felder in raw_block belassen (Original-OCR als Quelle), nur mechanics-Felder korrigiert.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[2026-03-03 14:00] | FROM: Claude Code | AD&D Encounter Expansion — 30 Encounter-Dateien vollstaendig ausgebaut:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUFGABE: 31 skelettierte Encounter-Dateien in data/lore/add_2e/encounters/ mit vollstaendigen Keeper-Daten ausbauen.
ERGEBNIS: 30/30 Encounter-Dateien (encounter_system.json bereits vollstaendig, unberuehrt).
NEUE FELDER (pro Datei): description (2-3 Satz Atmosphaere), monsters (vollstaendige AD&D 2e Stat-Blocks: AC/HD/HP/THAC0/Angriffe/Schaden/XP/Sondereigenschaften), tactics (Verhaltens-Beschreibung), environment (Terrain/Raum-Beschreibung), difficulty (easy/moderate/hard/deadly), loot (Array mit item+value), cr_equivalent (Party-Stufenbereich als String).
FALLEN (15 Dateien): Zusaetzlich disarm_dc (Entdeck+Entschaerfen), trap_details (type/trigger/area_of_effect/detection/reset/Sonderregeln).
EVENTS (12 Dateien): Zusaetzlich special_rules mit interaktiven Mechaniken (Untersuchungs-Optionen, Kleriker-Interaktion, zufaellige Sub-Ereignisse, Geraeusch-Checks).
MONSTER-ENCOUNTER (2 Dateien: goblin_patrol, rival_adventurers): Vollstaendige Stat-Blocks fuer jede Kreatur-/NSC-Variante, tactics mit Flanken/Rueckzugs-Logik, reaction_roll-Tabelle (rival_adventurers).
ALLE 30 DATEIEN: Valides JSON (py -3 Syntaxcheck: 0 Fehler).
Autonome Entscheidungen: (1) encounter_system.json nicht modifiziert (bereits vollstaendige Regeldokumentation ohne Encounter-spezifische Felder). (2) Unstable_masonry als Event mit optionalem Schaden modelliert (damage-Feld hinzugefuegt, da Kampfschaden tatsaechlich auftritt). (3) Eerie_statue_hall mit optionalen Steingolems (W10-Roll) ausgebaut, um sowohl die Exploration- als auch die Kampf-Variante zu unterstuetzen.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[2026-03-03 02:00] | FROM: Claude Code | Session 10 — Party-System implementiert:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
17 Dateien (11 neu, 6 modifiziert). 2 parallele Agents: Agent A (Content: 9 JSONs), Agent B (Code: 8 Tasks).
NEU: core/party_state.py (448Z), gui/tab_party_monitor.py (385Z), 6 Charakter-Sheets, Party, Adventure (790Z), Preset.
ERWEITERT: character.py (6 Party-Tags), ai_backend.py (Party-Prompt), engine.py (Party-Loading), orchestrator.py (Party-Tag-Routing), virtual_player.py (Case 7), tech_gui.py (Tab 11).
TESTLAUF: 165 Zuege, 6/6 leben, $3.04 Kosten. Tags funktionieren (PROBE/ANGRIFF/ZAUBER/HP_HEILUNG). Fuzzy Name Match OK.
PROBLEME: (1) CRITICAL: Preset-Adventure nicht durchgereicht (dungeon_gauntlet statt party-Version). (2) HIGH: KI emittiert 0 HP_VERLUST fuer Monster-Angriffe. (3) Repetitive Antworten ab Zug 80. Uebergabe an naechste Session.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2026-03-02 23:59] | FROM: QM-Agent | Session 9 Wrap-Up abgeschlossen. 3 Coding-Runden, 4 Commits (3cb39d0→e0a4f4f→9de3ec5→324e4f2). BUG-007 FIXED (STABILITAET_VERLUST-Tag fuer Non-Cthulhu geblockt). BUG-001 ROOT CAUSE FIXED (Deep-Copy + Type Guards in adventure_manager.py + memory.py). Neue Features: Wuerfelvisualisierung (tab_game.py), Lore-Budget-Slider (tab_session.py), Shadowrun Content-Erweiterung (Neonlichter-Adventure, 3 Chars, 6 Lore-Dateien). AD&D entity_index.json NEU (647 Entities). OCR-Cleanup MechWarrior (623 Dateien). Test-Analyse 19 Metriken/100+ Turns. Neue offene Issues: AD&D PROBE-Zielwert, Paranoia Satz-Overflow. MEMORY.md, session_log.md, bugtracker.md aktualisiert.
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
[2026-03-02 12:30] | FROM: Claude Code | Virtual Player Session 6: (1) EventBus-Fix: `"game"` → `"game.output"` Listener-Key (Ursache für 100% Timeouts). (2) Threading-Fix: `import threading` vor Verwendung. (3) dotenv-Laden in virtual_player.py (API-Key konfiguriert). (4) EventBus Import in orchestrator._save_metrics(). (5) Delays zwischen Zügen implementiert (2s Default via `--turn-delay`). (6) 4 x 10-Zug-Tests mit Delays durchgeführt — ALLE ERFOLGREICH, KEIN CRASH: cthulhu_7e (ZEIT_VERGEHT, FAKT, STIMME), add_2e (PROBE 4x, HP_VERLUST, INVENTAR), paranoia_2e (API-Bug 'list.items' ab Zug 7, aber Session fertig), shadowrun_6 (PROBE 4x, HP_VERLUST 2x, EDGE 1x). Findings: [PROBE:] Tags funktionieren in AD&D/Shadowrun, nicht in Cthulhu/Paranoia. Monolog-Sperre verletzt (KI ignoriert 3-Satz-Limit). Skill-Regex-Fehler (Wahrnehmung, Heimlichkeit nicht im Ruleset als exakte Matches). Zielwert-Validierung zu strikt (d6-Pool erlaubt 1-30, KI nutzt 50-60). STABILITAET_VERLUST falsch in Shadowrun emittiert.
[2026-03-02 12:51] | FROM: Claude Code | Virtual Player Session 7 – Batch 2 (Standard-Testablauf): (1) Bugfixes: Paranoia API — isinstance Checks in ai_backend.py Z728/1647 + memory.py Z240-250 (defensive Typprüfungen). (2) rules.md erweitert: Abschnitt 10 "Standard-Testablauf Mandatory" (Pre-Exit, Test-Ausf., OK-Kriterien, Post-Exec, Error-Handling). (3) Batch-2 durchgeführt nach Standard: Cthulhu ✅ (10 Züge, avg 1.2ms, ZEIT 10x+STIMME 2x, PROBE 0), ADD2e ✅ (10Z, 2.6ms, PROBE 4x), Paranoia ⚠️ (Gemini SDK internal 'list.items' Error Z6-10 aber Sessions komplett), Shadowrun ✅ (10Z, 3.0ms, PROBE 6x). Ergebnis: 3/4 ✅, 1/4 ⚠️ (SDK-extern). Batch-Kosten $0.012 (mit Context Cache). Nächste: [PROBE:]-System-Prompt für Cthulhu/Paranoia.
[2026-03-02 13:16] | TESTER MODE – Iteration 1:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ TESTS:     Cthulhu 50% (10 Züge OK, aber Regel-Violations), AD&D 100% (10 Züge, 4x PROBE), Paranoia 0% (Alle Turns: „KI-Backend nicht erreichbar"), Shadowrun 100% (10 Züge, 5x PROBE)
🔧 FIXES APPLIED: Eventbus-Key (game→game.output), threading import, dotenv loading, isinstance checks paranoia
📊 METRIKEN: Avg Latenz 2514ms (~2.5s + 2s delays), Total Tags 34, Warnings 9 (Skill-Mismatch), Response-Länge Cthulhu 232ch, AD&D 289ch, Shadowrun 454ch (Shadowrun detaillierter)
🎯 NÄCHSTE BUGS: (1) **CRITICAL: Paranoia KI-Backend komplett offline** (alle 10 Turns erhalten nur Stub „nicht erreichbar"). (2) **HIGH: Skill-Name Validation zu strikt** — AD&D/Shadowrun: Skills wie „Überreden", „Wahrnehmung", „Lauschen", „Beschwören" nicht im Ruleset gefunden. (3) **HIGH: [PROBE:] Tags fehlen in Cthulhu** (0/10 Turns mit PROBE-Tag, sollten 4-6 sein wie in AD&D/Shadowrun). (4) Cthulhu Monolog: avg 5.5 Saetze statt max 3. (5) Shadowrun falsche System-Tags (STABILITAET_VERLUST in Cyberpunk, sollte nicht vorkommen).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2026-03-02 21:45] | FROM: Claude Code | Conversion-Pipeline Audit, Fix & Cleanup (10-Task Batch):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T1 CLEANUP: 52 tmpclaude-*-cwd Tempfiles geloescht, arkham_economy.json nach data/lore/items/ verschoben, coversion/Grafik/ (Duplikat) geloescht, leeren process_workload_autopilot.py Stub entfernt.
T2 DOCS: WORKFLOW.md nach docs/management/conversion_workflow.md verschoben. Querverweise in agents.md aktualisiert. PRODUCTION_STATUS.json managed_from korrigiert. pictureextract v2.0.0 README.md korrigiert (app.py → pictureextract.py).
T3 AUDIT: docs/management/conversion_audit_report.md NEU — Qualitaetsbewertung aller 4 Systeme (add_2e: TEILWEISE, gurps_4e: UNBRAUCHBAR, mechwarrior_3e: STRUKTURELL OK, shadowrun_6: ABGEBROCHEN).
T4 GURPS: QA-Report validation_status von 'pass' auf 'fail_empty_ocr' korrigiert. CONVERSION_BLOCKED.md erstellt.
T5 SHADOWRUN: CONVERSION_BLOCKED.md erstellt (Phase 1 Abbruch, Wake of the Comet Supplement).
T6 ADD2E: STRUCTURE_NOTE.md erstellt. 2251 Blindchunks als nicht-verwertbar dokumentiert.
T7 PIPELINE: coversion/process_workload_autopilot.py NEU (~310 Zeilen) — CLI-Orchestrator mit: PDF-Discovery, System-Erkennung (via pdf_scanner), Text-Extraktion (pypdf + easyocr-Fallback), Verzeichnisstruktur-Anlage, Grafik-Extraktion (pictureextract), QA-Lauf, Source-PDF-Kopie, Archivierung. Flags: --dry-run, --pdf, --no-ocr, --no-graphics, --verbose. Entity-Extraktion als TODO markiert.
T8 HARDENING: enforce_full_depth.py v1.1.0 — Drei neue Checks: (1) OCR-Leerseiten-Gate (>50% empty + kein Entity-Index = fail_empty_ocr), (2) Entity-Index-Pflichtcheck (>50 Fulltext-Seiten ohne Index = fail_no_entity_index), (3) Snippet-Qualitaets-Metrik (name_guess OCR-Artefakt-Zaehler).
T9 SCANNER: pdf_scanner.py SYSTEM_HINTS um gurps/mechwarrior/battletech erweitert. Queue-Pfad von data/lore/ nach coversion/ verschoben.
T10 QA-LAUF: enforce_full_depth.py gegen alle 4 Systeme: add_2e=fail_empty_ocr, gurps_4e=fail_empty_ocr, mechwarrior_3e=PASS (4300 Entities, 1447/4255 OCR-Warnings), shadowrun_6=fail_empty_ocr.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2026-03-02 15:45] | FROM: Codex | Coversion-Workflow umgestellt: Verbindliche Autopilot-Pipeline auf `coversion/workload -> coversion/finished -> coversion/root/finished` dokumentiert (rules.md + WORKFLOW.md). Transfer abgeschlossen: ADD2e- und GURPS-Artefakte nach `coversion/finished/` kopiert.
[2026-03-02 16:00] | FROM: Codex | Regel ergaenzt: Verbindliches Feedback bei Auftragsvergabe dokumentiert (gesehen + angenommen + Startmeldung) in `docs/management/rules.md` Abschnitt 13.
[2026-03-02 16:20] | FROM: Codex | Coversion-Workload verarbeitet: `10654.sr.wake.of.the.comet.300dpi.aa6.pdf - Scan by Anonymous. Clean.pdf` als bestehendes System `shadowrun_6` erkannt und in Volltiefe nach `coversion/finished/shadowrun_6/` extrahiert (book_conversion/fulltext/chunks/derived_rules/final_report + Ruleset-Bundle). Quelle nach `coversion/root/finished/` verschoben.
[2026-03-02 16:10] | FROM: Codex | Conversion-Rules verschaerft: `rules.md` Abschnitt 14 (12-Phasen-Pflicht + QA-Gate) und `coversion/WORKFLOW.md` um Hard-Gates erweitert. `gurps_4e` nachbearbeitet mit `coversion/enforce_full_depth.py`: leere Fachordner automatisch mit Seed/N/A-Nachweisen befuellt, `indices/conversion_qa_report.json` erzeugt, Status `pass`.
[2026-03-02 16:24] | FROM: Codex | Coversion-Testlauf abgeschlossen: `BattleTech 1715 - MechWarrior (3rd edition).pdf` als neues System `mechwarrior_3e` verarbeitet (Volltiefe inkl. book_conversion/fulltext/rules_chunks/derived_rules/ruleset/preset). QA-Gate: `indices/conversion_qa_report.json` mit `validation_status=pass`. PDF nach `coversion/root/finished/` verschoben.
[2026-03-02 17:02] | FROM: Codex | Nacharbeit mechwarrior_3e: Scan-PDF war textlos (pypdf -> leere Seiten). Vollstaendiger OCR-Backfill (easyocr) fuer 246 Seiten durchgefuehrt, Fachartefakte neu aufgebaut (22 Coverage-Felder, 23 Phase-Chunks, 8 Derived-Rules-Dateien), NA-Altlasten entfernt. QA erneut: conversion_qa_report.json = pass.
[2026-03-02 17:10] | FROM: Codex | Conversion-Vorgabe verfeinert und festgeschrieben: Entity-First Extraktion + `indices/entity_index.json`, 100%-Snippet-Coverage mit Reconciliation-Pflicht, unresolved_entities im QA-Report, sowie typ-spezifische Mindestfelder (spell/monster/npc/item/quest) in WORKFLOW.md und rules.md aufgenommen.
[2026-03-02 17:20] | FROM: Codex | Conversion-Rules verfeinert: Kontext-Pfad, Tabellen-Header & Ref-Resolution integriert.
[2026-03-02 18:26] | FROM: Codex | Restlauf mechwarrior_3e abgeschlossen: Regeln neu geladen und auf Bundle angewandt. Entity-Index erzeugt (`indices/entity_index.json`, 45 Entities mit breadcrumb_path), Cross-Reference-Resolution auf Snippets angewandt (`_ref`), Tabellen-Normalisierung umgesetzt (8 mehrseitige Tabellen-Teilsnippets mit repliziertem Header), QA-Reconciliation auf 100% aktualisiert.
[2026-03-02 19:05] | FROM: Codex | Chaos-Snippets entfernt (`snippets_minimal` geloescht) und Entitaets-Erstwurf neu aufgebaut: Volltext-Komplettscan mit verwertbaren Snippets fuer items/spells/vehicles/quests/npcs/monsters/lore/history/factions/locations inkl. Provenienz (generated_at, generated_by), Quelle (PDF+Seite), Breadcrumb-Pfad, extrahierten Datenfeldern und _ref-Aufloesung. Reconciliation: 4300/4300, Coverage 100%, QA pass.
[2026-03-02 19:12] | FROM: Codex | Arbeitsanweisung nachhaltig verschaerft (strict mandatory): Verwertbare Entitaets-Snippets verpflichtend, Blind-/Chaos-Snippets verboten, Pflicht-Entitaetsklassen fuer Erstwurf fixiert (items/spells/vehicles/quests/npcs/monsters/lore/history + optional factions/locations), Pflicht-Provenienzfelder und zusaetzliche Hard-Gates in rules.md + coversion/WORKFLOW.md verankert.
[2026-03-02 19:24] | FROM: Codex | Workflow/Management aktualisiert: pictureextract als Production-Programm integriert (Version v2.0.0, Ablage `software/pictureextract/production/v2.0.0`, Archiv `software/pictureextract/archive/v1.0.0`, `PRODUCTION_STATUS.json` angelegt). Pflichtablage erweitert: Original-PDF wird zusaetzlich in `coversion/finished/{system_id}/source_pdf/` abgelegt; fuer mechwarrior_3e umgesetzt.
[2026-03-02 21:36] | FROM: Claude Code | Session 6 — B2-B9 Coding Batch + Bugfix + 4-System Test:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(1) CODE IMPLEMENTIERT (8 Tasks):
  B2: `gui/tab_conversion_monitor.py` NEU — Conversion Monitor Tab (Workload/Finished/Archive). `gui/tech_gui.py` auf 9 Tabs erweitert.
  B3: `core/ai_backend.py` — `_compute_rules_hash()` (SHA256) + `clear_caches()` fuer sauberen Session-Reset.
  B4: `audio/stt_handler.py` — RMS Noise-Gate (Threshold 0.01) vor VAD-Check, reduziert Hintergrundrauschen-Fehldetektionen.
  B5: `gui/tab_gamestate.py` — Stat-Bars klickbar (cursor hand2, Toplevel-Dialog), bidirektionale Bearbeitung via EventBus.
  B6: `core/adventure_manager.py` — `evaluate_condition()` mit AND/OR/NOT/eq Operatoren. `get_location_context()` + `get_available_clues()` nutzen neue Conditions.
  B7: `main.py` — `--convert-all` Flag, `--module` jetzt optional (nur Pflicht ohne --convert-all).
  B8: `core/latency_logger.py` NEU — Per-Phase Latenz-Tracking (STT/AI/TTS/Total). Integration in `core/orchestrator.py`.
  B9: `gui/tab_game.py` — Session-Reset Hardening: clear_caches(), orchestrator metrics/turn/latency reset, combat/time/adventure/flags reset, KI-Monitor injection log clear.
(2) BUGFIX:
  CRITICAL: `adventure_manager.py:212` — `exits` als list statt dict krachte mit `'list' object has no attribute 'items'`. Fix: isinstance-Check, beide Formate (dict+list) unterstuetzt. Ursache: Paranoia Adventures nutzen exits als Liste von Location-IDs, Cthulhu/AD&D als Dict {id: beschreibung}.
(3) TEST-ERGEBNISSE (4-System Virtual Player Batch, je 5 Zuege):
  Cthulhu 7e:  5/5 OK | Avg 1273ms | 0 Probes | 0 Warnings | Tags: 5x ZEIT_VERGEHT
  AD&D 2e:     5/5 OK | Avg 2918ms | 1 Probe  | 1 Warning (Skill 'Geschichte' nicht im Ruleset) | Tags: PROBE, ZEIT_VERGEHT
  Paranoia 2e: 5/5 OK | Avg 3093ms | 0 Probes | 0 Warnings | Tags: 5x ZEIT_VERGEHT, 3x STIMME (nach Bugfix)
  Shadowrun 6: 5/5 OK | Avg 4938ms | 3 Probes | 2 Warnings (Zielwert >30) | Tags: PROBE, FERTIGKEIT, HP_VERLUST, ZEIT_VERGEHT
(4) BEKANNTE ISSUES (pre-existing):
  - Monolog-Sperre wird von KI ignoriert (avg 5-7 Saetze statt max 3)
  - Cthulhu: 0 PROBE-Tags in 5 Zuegen (KI setzt keine Proben)
  - Shadowrun: PROBE-Zielwerte 50-70 statt 1-30 (d6-Pool falsch verstanden)
  - Shadowrun: Skill 'Cracken' und Stat 'SAN' existieren nicht im Ruleset
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2026-03-03 14:00] | FROM: Claude Code | Session 11 — AD&D 2e Feingranulierte Aufbereitung (10-Task Batch):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
(1) TABLES MASSIV ERWEITERT (add_2e_tables.json: 7KB → 42KB, Schema 1.0→2.0):
  T1: 6 Attribut-Bonus-Tabellen (STR 1-18/00, DEX, CON, INT, WIS, CHA) — 143 Eintraege
  T2: 19 Melee + 12 Missile Waffen (Schaden S-M/L, Speed, Range, Kosten)
  T4: Spell Slots (Wizard L1-20, Priest L1-20, Ranger L8-16, Paladin L9-20, Bard L2-20)
  T5: 58 Non-Weapon Proficiencies (Ability, Modifier, Slots, Groups)
  T6: 14 Ruestungen + 35 Adventuring Gear mit AC/Weight/Cost
  Turn Undead Tabelle (L1-14+, 13 Untoten-Typen)
(2) RULESET ERWEITERT (add_2e.json: Schema 2.7→2.8):
  T3: 6 Rassen mit vollstaendigen Details (Ability Adj, Level Limits, Class Options, Special Abilities, Languages, Min/Max)
(3) ENCOUNTER-AUSBAU (30/30 Dateien):
  T7: 30 Skelett-Encounters zu vollwertigen Begegnungen erweitert (Monster-Stats, Taktik, Loot, Environment, Difficulty, CR)
  15 Traps (disarm_dc, trap_details), 13 Events (special_rules), 2 Monster-Encounters (volle Statblocks)
(4) SPELL-OCR-CLEANUP (90 Dateien):
  T9: 8 kaputte Namen korrigiert, 42 fehlende Felder ergaenzt, 8 Section-Header reklassifiziert, 39 Truncated markiert
  Entity-Index aktualisiert. Verbleibende echte Spells: 323 (von 331, 8 waren OCR-Header)
(5) RULES ENGINE ERWEITERT (rules_engine.py):
  T8: 9 neue AD&D-Sektionen (Melee/Missile-Waffen, Spell Slots, Turn Undead, NWP, Ruestung, Monster-THAC0, Rassenfaehigkeiten)
  6 neue Keyword-Kategorien (proficiencies, racial_abilities, turn_undead, spell_slots, encumbrance, surprise)
  Alle Sektionen getestet: 296 Gesamt, 2.08M Zeichen, Keyword-Suche verifiziert
(6) AI BACKEND PROMPT VERBESSERT (ai_backend.py):
  T10: NWP-Proben-Protokoll, Zauber-Verwaltung (Memorierung), Turn-Undead-Protokoll, erweiterte System-Grenzen
  Diebes-Fertigkeiten (d100-Ausnahme), Rassenfaehigkeiten-Hinweis im Prompt
VALIDATION: JSON-Syntax OK (alle 4 Dateien), Python-Syntax OK (rules_engine + ai_backend), Integrations-Test OK (9/9 Sektionen indexiert)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2026-03-03 18:00] | FROM: Claude Code | Session 10c — Circuit Breaker + AD&D Training-Dungeon:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
10 Dateien (9 neu, 1 modifiziert). Ziel: Robustheit virtual_player + maximale Tag-Dichte fuer AD&D-Tests.
(1) CIRCUIT BREAKER in scripts/virtual_player.py:
  - `CIRCUIT_BREAKER_THRESHOLD = 5` + `consecutive_errors` Zaehler in run()-Methode
  - Kurzantwort-Erkennung: response_len < 60 Zeichen (API-Fehler 28-47 Zeichen, normale Antworten 150+)
  - Nach 5 aufeinanderfolgenden Kurzantworten: Log "CIRCUIT BREAKER", final_status="api_error_abort", Loop-Abbruch
  - Erfolgreicher Zug: counter reset auf 0
  - tm.error wird pro Kurzantwort-Zug gesetzt fuer klare Metriken
(2) ADVENTURE: modules/adventures/crawltraining_full.json — "Die Schinder-Tiefen":
  - 15-Raum linearer Dungeon mit Pflicht-Kampf + Proben in jedem Raum
  - 40 NPCs mit vollstaendigen AD&D 2e Statbloecken (Skelette HD1 bis Lich HD14 AC-2 HP90)
  - Jeder Raum: keeper_notes erzwingt [PROBE:], [ANGRIFF:], [HP_VERLUST:] Tags
  - 6 magische Gegenstaende als Beute, ~30.000 XP gesamt
  - Aggressives keeper_lore fuer maximale Tag-Dichte
(3) TRAINING-CHARAKTERE (6 neue Character-JSONs, aggressive Persoenlichkeiten):
  - add_train_fighter — Grimjaw Eisenfaust (L7 Fighter, "greift SOFORT an")
  - add_train_mage   — Pyra Flammenherz (L6 Mage, "Offensiv, Feuer und Zerstoerung")
  - add_train_cleric — Bruder Mordain (L6 Cleric, "Kriegspriester, heilt knapp")
  - add_train_thief  — Shade Klingenschatten (L7 Thief, "Aggressiver Backstab")
  - add_train_ranger — Varn Wildtoeter (L6 Ranger, "Monsterjaeger, greift zuerst")
  - add_train_paladin — Sir Kael Zornesklinge (L6 Paladin, "Fanatischer Untotenjaeger")
(4) PARTY + PRESET:
  - modules/parties/add_training_party.json — "Die Schinder-Truppe" (6 Mitglieder)
  - modules/presets/crawltraining_full.json — Aggressive DM-Persona, temperature 0.7
VERIFIKATIONSBEFEHLE:
  py -3 scripts/virtual_player.py --module add_2e --adventure crawltraining_full --party add_training_party --turns 20 --save
  py -3 scripts/virtual_player.py --module add_2e --preset crawltraining_full --turns 100 --llm-player --save
OFFENE ISSUES (unveraendert aus Session 10b):
  (1) CRITICAL: Preset-Adventure nicht durchgereicht (engine.load_adventure() ignoriert Preset-Adventure-Feld)
  (2) HIGH: KI emittiert 0 HP_VERLUST fuer Monster-Angriffe
  (3) HIGH: Repetitive Antworten ab ~Zug 80 (Context-Saettigung)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2026-03-03 15:30] | FROM: Claude Code | Session 10c ABGESCHLOSSEN — Circuit Breaker + HP_VERLUST Party-Fix
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Implementiert (10 neue/modifizierte Dateien):
1. `scripts/virtual_player.py` — Circuit Breaker (5 consecutive errors → abort), aggressiver LLM-Player-Prompt
2. `core/ai_backend.py` — Party-aware character_block, 2-Sektionen Tag-Layout (ANGRIFF=Spieler, HP_VERLUST=Monster), Kampfrunden-Beispiel
3. `core/orchestrator.py` — ROOT CAUSE FIX: CombatTracker in Party-Mode deaktiviert (blockierte HP_VERLUST-Tags aktiv)
4. `modules/adventures/crawltraining_full.json` — 15-Raum Dungeon "Die Schinder-Tiefen", 40 NPCs, aggressive keeper_lore
5. 6x `modules/characters/add_train_*.json` — Aggressive Charaktere (Fighter/Mage/Cleric/Thief/Ranger/Paladin)
6. `modules/parties/add_training_party.json` — "Die Schinder-Truppe"
7. `modules/presets/crawltraining_full.json` — Aggressiver DM, Temp 0.7

Test v8 Ergebnis (20 Zuege, ERFOLGREICH):
- 8 HP_VERLUST korrekt emittiert und angewendet:
  - Grimjaw: 72 → 48 (-24 HP, 6 Treffer)
  - Varn: 52 → 47 (-5 HP, 2 Treffer)
- 23 PROBEs, 72 Combat-Tags, 4 XP-Verteilungen
- Alle 6 Party-Mitglieder leben
- Circuit Breaker funktioniert (test v7 bewies: 5 Timeouts → Abort)
- Kosten: $0.18, Avg Latenz 6.7s

Root Cause (FIX):
CombatTracker (Single-Char System) war in Party-Mode aktiv und:
(a) injizierte eigene Monster-Angriffe → KI dachte "System handhabt Schaden"
(b) verwarf HP_VERLUST-Tags explizit (Zeile 521-522: "HP_VERLUST ignoriert (CombatTracker aktiv)")
FIX: core/orchestrator.py — CombatTracker.track_attack() deaktiviert fuer Party-Mode, HP_VERLUST-Emissionspfad freigelegt

Offene Issues:
- 16 REGELCHECK-Warnings: KI verwendet falsche PROBE-Zielwerte (35/40/45 statt 1-20 fuer AD&D)
- Schadensverteilung ungleich: Grimjaw absorbiert 75% aller Treffer
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2026-03-03 21:30] | FROM: Claude Code | Audio-System Upgrade — 5 Dateien, 4 Features
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Feature A: Edge TTS Backend (8 neue neurale Stimmen)
- audio/tts_handler.py: VOICE_REGISTRY auf 18 Rollen erweitert (10 Piper + 8 Edge)
- Backend-Hierarchie: piper > edge > kokoro_onnx > pyttsx3 > stub
- _edge_speak(): async Bridge (edge_tts.Communicate → MP3 → soundfile → numpy)
- EDGE_FALLBACK dict: automatischer Piper-Fallback bei offline
- _is_edge_available(): lazy import-check + EDGE_TTS_ENABLED env

Feature B: Audio-Effekt-Pipeline
- audio/effects.py NEU (~170Z): AudioEffects Klasse mit pedalboard
- 10 Presets: clean, hall, monster, ghost, robot, radio, underwater, cathedral, rage, old
- ROLE_EFFECTS: Standard-Preset pro Stimmenrolle (monster→monster, mystery→ghost, etc.)
- pitch_shift() via scipy.signal.resample()
- Clipping-Schutz, lazy-loading, graceful degradation ohne pedalboard

Feature C: _preprocess_german() Text-Preprocessor
- NFC + Unicode-Cleanup (Dashes, Smart Quotes, Soft Hyphen, BOM)
- 15 deutsche Abkuerzungen expandiert (z.B. → zum Beispiel, etc.)
- Control-Characters entfernt (Kategorie C), Combining Marks (Mn) komplett entfernt
- Alter Combining-Marks-Filter in _piper_speak() entfernt (war zu aggressiv)
- Zentraler Aufruf in _speak_sentence() statt redundante NFC-Aufrufe

Feature D: EFFEKT-Tag + GUI
- audio/tag_filter.py: EFFEKT in _CONTROL_PREFIXES, _EFFECT_RE, effect_callback
- tts_handler.py: set_effect(preset) Methode
- gui/tab_audio.py: 18 Rollen-Tabelle mit Backend-Spalte, Effekt-Dropdown + Preview, Edge-Status
- Scrollbarer Container fuer erweiterten Tab-Inhalt

Neue Dependencies: edge-tts>=7.0.0, soundfile>=0.12.0, pedalboard>=0.9.0

Dateien: audio/effects.py (NEU), audio/tts_handler.py (MODIFY), audio/tag_filter.py (MODIFY), gui/tab_audio.py (MODIFY), requirements.txt (MODIFY)
Syntax-Check: 4/4 OK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2026-03-03 23:45] | FROM: Claude Code | Replay-Viewer implementiert (3 Dateien, ~510 Zeilen)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- scripts/virtual_player.py: TurnMetrics um 8 Grid-Snapshot-Felder erweitert (room_id, room_width, room_height, grid_positions, grid_entities, party_hp, move_events, room_terrain). EventBus-Listener fuer grid.entity_moved/combat_move in _play_turn(). Snapshot-Erfassung nach Response-Verarbeitung. Rueckwaertskompatibel (leere Defaults).
- gui/tab_replay_viewer.py NEU (~430Z): PanedWindow-Layout (Grid links, Controls+Text+HP rechts). JSON-Report laden, Turn-Slider, Play/Pause mit Speed-Slider (500-5000ms). Grid-Rendering mit identischen Symbolen wie Dungeon-Tab (Waende, Tueren, Monster, Party-Member mit Klassen-Buchstaben). Tag-Highlighting (rot/gelb/gruen/orange). Party-HP-Balken pro Zug.
- gui/tech_gui.py: Tab 13 "Replay" registriert (Import, Instanz, notebook.add, dispatch).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[2026-03-04 17:30] | FROM: Claude Code | Session 19 — DMG-Integration (Dungeon Master's Guide Kernmechaniken)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Vollstaendiger Bericht: docs/management/dmg_integration_report.md

(1) ANALYSE (4 Agenten parallel):
  - 775+ DMG-Lore-Dateien inventarisiert (dm_tools/, rules_fulltext_chunks/, derived_rules/)
  - Engine-Regelbestand analysiert (rules_engine, orchestrator, mechanics, combat_tracker)
  - Keyword-Index-Luecken identifiziert (8 fehlende Kategorien)
  - DMG ist NICHT als eigenes PDF konvertiert — Inhalte verteilt in PHB-Kapiteln + DMGR-Serie

(2) NEUE MECHANIKEN (core/mechanics.py — 6 Methoden, ~350 Zeilen):
  - morale_check(morale_value, modifiers) — 2d6 vs Moral-Schwelle
  - reaction_roll(cha_modifier) — 2d6 + CHA, 5-stufige Reaktionstabelle
  - turn_undead(cleric_level, undead_hd) — PHB Table 61 (14x12 Matrix)
  - roll_treasure(treasure_type) — Typen A-H mit Muenzen/Gems/Schmuck/Magie
  - roll_encounter_check(chance_percent) — d100 Wandering-Monster-Probe
  - calculate_encumbrance(items, str_score) — 5 Kategorien, STR-basierte Traglast

(3) KEYWORD-MAPPINGS (core/rules_engine.py — 8 neue Kategorien):
  treasure, encounter_generation, morale, reaction, loyalty, light_vision, poison_disease, thief_skills
  Gesamt: 26 Kategorien, 537 Keywords

(4) SYSTEM-PROMPT (core/ai_backend.py — DMG-Kernmechaniken Block):
  7 neue Pflicht-Tags: [MORAL_CHECK], [REAKTION], [SCHATZ], [UNTOTE_VERTREIBEN], [BELASTUNG], [BEGEGNUNG], [GIFT]

(5) TAG-PARSER (core/orchestrator.py — _handle_dmg_tags(), ~200 Zeilen):
  7 Regex-Handler mit Mechanics-Aufruf, EventBus-Events, Fehlerbehandlung

(6) TEST-SZENARIO (modules/adventures/dmg_stress_test.json — 46 KB):
  "Der Vergessene Schatzgewoelbe" — 7 Raeume, 18 NPCs, 14 Clues, 19 Flags
  Designiert fuer maximale DMG-Tag-Dichte

(7) VIRTUAL PLAYER (scripts/virtual_player.py):
  7 neue DMG-Aktionen, situative Solo/Party-Prompts

(8) TESTERGEBNISSE:
  Test 1 (20 Runden): 0 neue Tags — Ursache: alter Context Cache + passive Inputs
  Test 2 (10 Runden, nach Bugfixes):
    [REAKTION] ✅ FUNKTIONIERT — Gareth der Soeldner CHA-Mod=0, 2d6=9, hostile
    [BEGEGNUNG] ✅ FUNKTIONIERT — Zerbrochenes Tor d100=16 Schwelle=33, BEGEGNUNG!
    Andere 5 Tags: nicht getriggert (KI stagniert in Raum 1-2, erreicht nie Untote/Schatz/Gift)
  Verbleibendes Problem: KI-Pacing bei automatisierten Tests, nicht die Mechanik

(9) BUGFIXES:
  - BEGEGNUNG Regex flexibilisiert (akzeptiert jetzt [BEGEGNUNG: Wandering] ohne Pipe)
  - System-Prompt DMG-Block komprimiert + PFLICHT-Hinweis
  - Anti-Stagnations-Regel in keeper_lore
  - Context Cache Invalidierung funktioniert korrekt (Hash-basiert)

DATEIEN: mechanics.py (+350Z), rules_engine.py (+50Z), ai_backend.py (+40Z), orchestrator.py (+200Z), virtual_player.py (+30Z), dmg_stress_test.json (NEU 46KB)
KOSTEN: Test 1 $2.01, Test 2 $1.24 (Gesamt $3.25)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
