# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ARS (Advanced Roleplay Simulator) is a TTRPG engine with an AI game master (Keeper) powered by Gemini 2.5 Flash. It is focused on AD&D 2nd Edition, with voice I/O (STT/TTS), and three interface modes: CLI, TechGUI (tkinter), and Web GUI (FastAPI + WebSocket).

**Language:** All code, comments, and documentation are in German. The AI Keeper responds in German by default.

**API Key:** Requires `GEMINI_API_KEY` in `.env` file (loaded via python-dotenv).

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt
# For voice: pip install torch --index-url https://download.pytorch.org/whl/cpu

# Run with TechGUI (primary dev mode)
py -3 main.py --module add_2e --techgui
py -3 main.py --module add_2e --adventure goblin_cave --voice --techgui

# Run with Web GUI
py -3 main.py --module add_2e --webgui --port 8080

# Run CLI mode
py -3 main.py --module add_2e --adventure goblin_cave --voice --no-barge-in

# Automated test run (10 turns, saves metrics JSON)
py -3 scripts/virtual_player.py --module add_2e --adventure goblin_cave --turns 10 --save

# Test batch via testbot
py -3 scripts/testbot.py run -t combat -n 3 -m add_2e --turns 10
py -3 scripts/testbot.py results
py -3 scripts/testbot.py status

# AD&D 2e standard test batch (rules.md §10)
py -3 scripts/virtual_player.py --module add_2e --adventure goblin_cave --turns 10 --save --turn-delay 2.0
py -3 scripts/virtual_player.py --module add_2e --adventure dungeon_gauntlet --case 5 --turns 10 --save --turn-delay 2.0
py -3 scripts/virtual_player.py --module add_2e --adventure dungeon_gauntlet --party add_valdrak_party --case 6 --turns 10 --save --turn-delay 2.0
```

There is no formal test suite (pytest/unittest). Testing is done via `virtual_player.py` and `testbot.py` which run live AI sessions and score results.

## Architecture

### Core Data Flow

```
main.py → SimulatorEngine → Orchestrator (game loop)
                          → GeminiBackend (AI API, prompt assembly, response parsing)
                          → RulesEngine (3-layer: index → pre-injection → post-validation)
                          → PartyStateManager (multi-char HP/Spell/XP tracking)
                          → CharacterManager (SQLite persistence in data/ars_vault.sqlite)
```

### EventBus Pattern

`core/event_bus.py` is a thread-safe singleton Observer. All inter-component communication flows through it:
- `EventBus.get()` for singleton access
- `bus.emit("category", "event_name", data_dict)` to fire
- `bus.on("category.event", callback)` to listen
- Key categories: `keeper.*`, `game.*`, `party.*`, `session.*`, `rules.*`
- GUI tabs receive events via a thread-safe queue (`root.after()` polling at 50ms)

### AI Response Tags

The AI Keeper emits structured tags in its prose that the Orchestrator parses:
- `[PROBE: Skill Zielwert]` — skill check (d20 roll-under for AD&D 2e)
- `[HP_VERLUST: N]` or `[HP_VERLUST: Name | N]` (party mode)
- `[ANGRIFF: Waffe Schaden]` — attack roll
- `[RETTUNGSWURF: Typ]` — saving throw
- `[ZAUBER_VERBRAUCHT: Zauber]` — spell slot consumed
- `[XP_GEWINN: N]`, `[FAKT: text]`, `[ZEIT_VERGEHT: duration]`, `[INVENTAR: +/-item]`
- `[MONSTER_BEWEGT: Name | Richtung]` — monster movement for grid engine
- Party variants use `Name | Value` format for per-character targeting

### Module System

All game content lives in `modules/` as JSON files:
- `rulesets/` — rule definitions (dice, stats, skills, combat)
- `adventures/` — locations, NPCs, clues, items, flags
- `characters/` — stat blocks per system
- `parties/` — member lists referencing character IDs
- `presets/` — session config bundles (maps to `SessionConfig` dataclass)
- `scenarios/` — full session bundles
- `settings/`, `keepers/`, `extras/` — world/personality/modifier overlays

### Lore System

`data/lore/{system_id}/` contains thousands of JSON/MD knowledge chunks loaded by `GeminiBackend._load_and_merge_lore()`:
- Budget-controlled: `MAX_LORE_CHARS = 500_000`, adjustable via GUI slider (0-100%)
- Priority-ranked: `permanent` > `core` > `support` > `flavor`
- Per-system `_exclude_dirs` prevent loading combat tables/spell lists into context
- `core/lore_adapter.py` normalizes system-specific fields to canonical engine fields

### GUI Architecture

`gui/tech_gui.py` hosts 11 tabs in a `ttk.Notebook`. Each tab is a separate module (`gui/tab_*.py`) with a `handle_event(data)` method. Events are dispatched from the engine thread to the GUI main thread via a `Queue` polled every 50ms.

The Web GUI (`web/`) mirrors the same architecture: FastAPI REST endpoints + WebSocket bridge that serializes all EventBus events to browser clients. Single-page app with vanilla JS (no framework).

### Test Infrastructure

Three-tier: `testbot.py` (CLI dispatcher) → `test_series.py` (parallel batch runner via ThreadPoolExecutor) → `virtual_player.py` (actual AI game session). Results scored 0-100 on tags, monolog length, cross-system accuracy, survival, hook presence, latency. Pass threshold: >=60.

### Remote Job Dispatch System

File-based job queue for running tests on a remote server (Ubuntu) triggered from any workstation. No ports, no cloud — uses the shared ARS folder as message bus.

**Architecture:** `data/remote_jobs/` with subdirectories `pending/`, `running/`, `done/`, `failed/`, `logs/`. Client drops Job-JSON into `pending/`, server daemon (`job_watcher.py`) polls and executes.

**Key files:**
- `scripts/job_watcher.py` — Server-side polling daemon (~340 lines). Scans `pending/`, executes via subprocess, moves to `done/` or `failed/`. Supports auto-fix via `claude --print` on startup errors (1 retry). Run as systemd service or foreground.
- `scripts/job_client.py` — Client library: `submit_job()`, `wait_for_job()`, `list_jobs()`. Atomic JSON writes via temp-file + replace.
- `scripts/ars-job-watcher.service` — systemd unit file (adjust paths for target server).

**Supported job types:** `testbot`, `rules_tester`, `virtual_player`, `script` (path-validated).

**Job-JSON format:** `{timestamp}_{job_id}_{requester}.json` with fields: `job_id`, `job_type`, `requester`, `status`, `params`, `server` (hostname/pid/timestamps/exit_code), `result` (stdout_tail/report_path/error/autofix).

**Status flow:** `pending → running → done | failed → (autofix_running → done | failed_permanent)`

```bash
# Client: submit a remote job
py -3 scripts/testbot.py remote run -t rules --wait
py -3 scripts/testbot.py remote run -t dungeon_crawl --runs 5 --turns 10
py -3 scripts/testbot.py remote run -t virtual_player --adventure goblin_cave

# Client: check status
py -3 scripts/testbot.py remote status
py -3 scripts/testbot.py remote list --hours 48

# Server: run watcher (foreground for testing)
python scripts/job_watcher.py --interval 30 --timeout 600
python scripts/job_watcher.py --no-autofix -v
```

## Mandatory Process Rules

These rules are defined in `docs/management/rules.md` and `docs/management/organization.md`. They are binding.

### Agent Behavior (rules.md §6, §7, §13)

- **No counter-questions.** Claude Code does NOT ask "Shall I...?", "May I...?", "Do you want me to...?" or similar confirmation prompts. Tasks are executed autonomously and completely. Questions are ONLY allowed when a technical dependency is genuinely unclear and blocks implementation.
- **Secretary protocol.** Claude Code acts as administrative agent: Gemini outputs, decisions, and rules are transferred to `docs/management/` documents independently. New tasks are documented in `agents.md` immediately. Documentation is always part of the task.
- **Acknowledge assignments.** On every new task assignment, confirm receipt and immediate start. No counter-question, just a brief acknowledgement.

### Task Workflow (rules.md §2, §8)

- **agents.md is the central hub** (`docs/management/agents.md`). Read before every action. Report after every completed task.
- **Report format:** `[YYYY-MM-DD HH:MM] | FROM: [Agent] | [Status/Result]` — written to the "Agent Reports" section of `agents.md`.
- **Standard work batch:** 10 related tasks per session, fully completed without partial delivery. Full Agent Report after each batch.
- **Strategic ideas** go to `docs/management/suggestions.md`, reviewed every 3 days.

### File Placement (rules.md §9)

- Every data file MUST be placed under `data/lore/...`. File creation in the project root is FORBIDDEN.
- Before writing, verify the target directory exists; create with `os.makedirs` if necessary.

### Standard Test Protocol (rules.md §10)

Run AD&D 2e test batch before each release. Per run: 10 turns, 2s delay, with `--save`.

**Test order:** (1) `add_2e` / `goblin_cave` (investigation), (2) `add_2e` / `dungeon_gauntlet` case 5 (dungeon crawl), (3) `add_2e` / `dungeon_gauntlet` party mode case 6.

**Pass criteria (all must be met):**
- No crash/exception
- All 10 turns completed (no timeouts)
- Report saved as JSON in `data/metrics/`
- Tags emitted: at least 1 per 3 turns
- Average latency < 5s

**Post-test:** Check JSON reports, summarize metrics (turns, latency, tags, warnings), document new bugs in `agents.md`.

### Tester Mode (rules.md §11)

Activated by user saying "tester mode". Runs a continuous Test-Fix-Report loop:
1. TEST: AD&D 2e standard batch (3 runs)
2. REPORT: update `agents.md`
3. FIX: top-3 bugs by impact
4. COMMIT: `git add . && git commit -m "[TESTER] Iteration N: ..."`
5. REPEAT

**Stop conditions:** User says "STOP", all bugs solved, or 3 consecutive green runs (all 3 tests pass).

### Bug Tracking

Bugs are tracked in `docs/management/bugtracker.md`. Format includes ID, severity, system, status, and description. Reference: BUG-001 through BUG-008 currently tracked.

## Governance Documents

All management documents live in `docs/management/`:

| Document | Purpose | Reference |
|----------|---------|-----------|
| `rules.md` | Binding agent rules (17 sections) — process, communication, testing, conversion | Primary authority |
| `agents.md` | Central task dashboard, project status, To-Dos by role, Agent Reports log | Read before work, write after |
| `organization.md` | Org chart and role definitions (Human Lead, Gemini, Claude Code, Codex, Virtual Player) | Role reference |
| `WCR.md` | World Creation Rules — JSON schema spec for all module types | Schema authority |
| `Book_ARS_Tool.md` | 12-phase PDF-to-JSON conversion pipeline | Conversion reference |
| `conversion_workflow.md` | Autopilot workflow for PDF conversion | Pipeline reference |
| `bugtracker.md` | Bug tracking with IDs, severity, status | Bug reference |
| `suggestions.md` | Strategic roadmap, lore ideas, feature brainstorming | Long-term planning |

### Hierarchy of Authority

1. **Human Lead (User)** — final decisions, approvals
2. **Gemini User Console** — leading instance for session logic; decisions made there are binding (rules.md §1)
3. **rules.md** — process rules, mandatory for all agents
4. **WCR.md** — schema rules for content creation

## Content Creation Rules

### JSON Schema Requirements (from WCR.md)

Every JSON file in `modules/` MUST carry `schema_version` (semver). Version bumps:
- MAJOR: fields renamed/removed, structure broken
- MINOR: new optional fields added
- PATCH: content corrections, typos

**Ruleset mandatory fields:** `metadata` (name, version, system, schema_version), `dice_system` (default_die, success_levels), `characteristics` (min 1), `skills` (min 1).

**Adventure mandatory fields:** `id`, `name`, `locations` (array of objects with `id`), `npcs` (array of objects with `id`). IMPORTANT: `locations` and `npcs` are arrays, NOT dicts.

**Encoding:** UTF-8 (with or without BOM). Engine reads `utf-8-sig`.

### PDF Conversion Pipeline (rules.md §12, §14-§17)

- **Working directory:** `coversion/` (sic — historical typo, kept for consistency)
- **Input:** `coversion/workload/`
- **Output:** `coversion/finished/{system_id}/`
- **Archive:** `coversion/root/finished/`
- All 12 phases from `Book_ARS_Tool.md` must be completed. "Done" requires every phase at `done` or `na_with_reason`.
- **Entity-first extraction** is mandatory (rules.md §15, §16): `indices/entity_index.json` required with `breadcrumb_path`, `entity_id`, `entity_type`, `name`, `source_pages`, `snippet_path`, `status`.
- **100% snippet coverage:** Every index entity points to an existing snippet file. Every snippet file is in the index. Discrepancies listed as `unresolved_entities` in QA report.
- **No blind snippets:** Pure text segmentation without entity context is forbidden. Snippets must have provenance (`generated_at`, `generated_by`, `method`), source (`source_text.pdf`, `source_text.page`), and content fields.
- **QA gate:** `indices/conversion_qa_report.json` with phase status 1-12, folder counts, `validation_status: pass|fail`. No completion until `pass`.
- **Source PDF copy:** After conversion, original PDF also placed in `coversion/finished/{system_id}/source_pdf/`.
- **Graphics extraction:** Via `software/pictureextract/production/{version}/`.

## Supported Rule Systems

| ID | System | Dice | Key Mechanic |
|---|---|---|---|
| `add_2e` | AD&D 2nd Edition | d20 | THAC0, classes, spells, saving throws |

## Key Constants

- `MAX_LORE_CHARS = 500_000` (ai_backend.py)
- `MAX_HISTORY_TURNS = 40` (ai_backend.py)
- Monolog limit: 5 sentences hard cap (20 party mode), hook required within 3 sentences (15 party mode)
- Context cache TTL: 2 hours (Gemini explicit caching)
- GUI event poll interval: 50ms
- Rules budget default: 6000 chars
