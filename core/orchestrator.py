"""
core/orchestrator.py — Session-Orchestrator

Verantwortlich für:
  - Verwaltung des Spielzustands (aktive Szene, Charaktere, Inventar)
  - Koordination zwischen Engine, Mechanics und KI-Backend
  - Haupt-Game-Loop (Eingabe → KI-Antwort → Probe → Würfelergebnis → Loop)
"""

from __future__ import annotations

import json
import logging
import queue
import random
import re
import time as _time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.engine import SimulatorEngine

logger = logging.getLogger("ARS.orchestrator")

# ── Monster-Bewegungs-Tag-Parser ─────────────────────────────────────
_RE_MONSTER_MOVE = re.compile(
    r"\[MONSTER_BEWEGT:\s*([^|]+?)\s*\|\s*([^]]+?)\s*]", re.I,
)


def _extract_monster_moves(text: str) -> list[tuple[str, str]]:
    """Extrahiert [MONSTER_BEWEGT: Name | Richtung] Tags aus KI-Antwort."""
    return [(m.group(1).strip(), m.group(2).strip().lower())
            for m in _RE_MONSTER_MOVE.finditer(text)]


class Orchestrator:
    """
    Verbindet alle Subsysteme und führt den Spiel-Loop aus.

    Wird von SimulatorEngine instanziiert und erhält eine Referenz
    auf die Engine zurück (bidirektionale Kopplung über TYPE_CHECKING).
    """

    def __init__(self, engine: SimulatorEngine) -> None:
        self.engine = engine
        self._adventure: dict[str, Any] | None = None
        self._session_history: list[dict[str, str]] = []
        self._active = False
        self._session_id: int = 0       # DB-Session-ID (0 = nicht in DB)
        self._archivist = None          # Task 05: Chronik + World State
        self._adv_manager = None        # Task 06: Adventure Manager
        self._combat_tracker = None     # CombatTracker (aktiv waehrend Kampf)
        # GUI-Modus: Input kommt aus Queue statt stdin
        self._gui_mode = False
        self._input_queue: queue.Queue[str | None] = queue.Queue()
        self._turn_number: int = 0
        # Metrics-Logger
        self._metrics_log: list[dict[str, Any]] = []
        self._session_start: float = 0.0
        # Strukturierter Latenz-Logger
        self._latency_logger = None  # Lazy-Init in _game_loop

    def set_gui_mode(self, enabled: bool = True) -> None:
        """Aktiviert GUI-Modus: Input via Queue, Output via EventBus."""
        self._gui_mode = enabled

    def submit_input(self, text: str) -> None:
        """Schiebt Spieler-Input in die Queue (aufgerufen vom GUI-Thread)."""
        self._input_queue.put(text)

    def resume_session(self) -> None:
        """Setzt eine pausierte Session fort."""
        if not self._active:
            self._active = True
            self._game_loop()

    # ------------------------------------------------------------------
    # Konfigurations-API (wird von Engine aufgerufen)
    # ------------------------------------------------------------------

    def set_adventure(self, adventure_data: dict[str, Any]) -> None:
        self._adventure = adventure_data
        # AdventureManager laden (Task 06)
        from core.adventure_manager import AdventureManager
        self._adv_manager = AdventureManager()
        self._adv_manager.load(adventure_data)
        # Engine-Referenz fuer GUI-Zugriff
        self.engine._adv_manager = self._adv_manager
        # Abenteuer auch ans AI-Backend weitergeben
        if self.engine.ai_backend:
            self.engine.ai_backend.set_adventure(adventure_data)
            self.engine.ai_backend.set_adventure_manager(self._adv_manager)
        # Grid-Engine: Adventure-Daten + initialen Raum setzen
        grid = getattr(self.engine, "grid_engine", None)
        if grid:
            grid.set_adventure(adventure_data)
            start_loc_id = adventure_data.get("start_location", "")
            if start_loc_id:
                locations = {
                    loc["id"]: loc for loc in adventure_data.get("locations", [])
                    if isinstance(loc, dict) and "id" in loc
                }
                start_loc = locations.get(start_loc_id)
                if start_loc:
                    grid.setup_room(start_loc, start_loc_id)
                    npc_ids = start_loc.get("npcs_present", [])
                    if npc_ids:
                        grid.place_npcs(npc_ids)
                    if self.engine.party_members:
                        grid.place_party(self.engine.party_members)
        logger.info(
            "Adventure gesetzt: %s",
            adventure_data.get("title", "Unbekannt"),
        )

    # ------------------------------------------------------------------
    # Session-Lifecycle
    # ------------------------------------------------------------------

    def start_session(self) -> None:
        """Startet den interaktiven Spiel-Loop."""
        self._active = True
        ruleset = self.engine.ruleset
        system_name = ruleset["metadata"]["name"]
        dice = self.engine.dice_config

        print(f"\n{'='*60}")
        print(f"  Advanced Roleplay Simulator — {system_name}")
        if self._adventure:
            print(f"  Abenteuer: {self._adventure.get('title', 'Sandkasten')}")
        print(f"  Standard-Wuerfel: {dice.default_die}")
        if self.engine.ai_backend and self.engine.ai_backend._client:
            from core.ai_backend import GEMINI_MODEL
            ai_status = GEMINI_MODEL
        else:
            ai_status = "Stub"
        print(f"  KI-Backend: {ai_status}")
        # Charakter-Status anzeigen + Session in DB anlegen
        if self.engine.character:
            char = self.engine.character
            # HP auf Maximum wenn Charakter tot (neue Session = frisch)
            if char.is_dead:
                hp_max = char._stats_max.get("HP", 10)
                char._stats["HP"] = hp_max
                char.save()
                logger.info("Charakter wiederbelebt: HP auf %d gesetzt.", hp_max)
            status = char.status_line()
            if status:
                print(f"  Charakter: {char.name} | {status}")
            self._session_id = char.start_session()

            # Archivist initialisieren (Task 05)
            from core.memory import Archivist
            conn = char.get_conn()
            if conn and self._session_id:
                self._archivist = Archivist(
                    session_id=self._session_id,
                    conn=conn,
                )
                # Archivist ans AI-Backend koppeln
                if self.engine.ai_backend:
                    self.engine.ai_backend.set_archivist(self._archivist)
                # Flags aus World State restaurieren + Archivist koppeln (Task 06)
                if self._adv_manager:
                    self._adv_manager.set_archivist(self._archivist)
                    ws = self._archivist.get_world_state()
                    if ws:
                        self._adv_manager.merge_flags_from_world_state(ws)
                        logger.info("Flags aus World State restauriert: %d", len(ws))

                # Cache-Status anzeigen
                cache_status = (
                    "aktiv" if self.engine.ai_backend and self.engine.ai_backend._cache_name
                    else "inaktiv"
                )
                print(f"  Context Cache: {cache_status}")

        # Keeper-Stimme setzen (falls Voice aktiv und Keeper geladen)
        if self.engine._voice_enabled and hasattr(self.engine, "_tts"):
            keeper = self.engine.keeper_data
            if keeper and keeper.get("voice"):
                voice_role = keeper["voice"]
                if self.engine._tts.set_voice(voice_role):
                    print(f"  Keeper-Stimme: {voice_role}")
                    logger.info("Keeper-Stimme gesetzt: %s", voice_role)

        # Grid-Engine: Location-Changed Listener registrieren
        grid = getattr(self.engine, "grid_engine", None)
        if grid:
            from core.event_bus import EventBus as _EB
            _EB.get().on("adventure.location_changed", self._on_location_changed_grid)

        print(f"{'='*60}\n")

        if self._adventure:
            intro = self._adventure.get("intro", "Das Abenteuer beginnt...")
            self._gm_print(intro)

        self._game_loop()

    def stop_session(self) -> None:
        self._active = False
        logger.info("Session beendet. %d Zuege gespielt.", len(self._session_history))
        self._save_metrics()

    def _save_metrics(self) -> None:
        """Speichert die Zug-Metriken als JSON in data/metrics/."""
        if not self._metrics_log:
            return
        try:
            import time as _t
            metrics_dir = Path(__file__).parent.parent / "data" / "metrics"
            metrics_dir.mkdir(parents=True, exist_ok=True)
            ts = _t.strftime("%Y%m%d_%H%M%S")
            module = self.engine.module_name
            path = metrics_dir / f"session_{module}_{ts}.json"

            total_latency = sum(m["latency_ms"] for m in self._metrics_log)
            n = len(self._metrics_log)
            summary = {
                "module": module,
                "session_id": self._session_id,
                "total_turns": n,
                "total_latency_ms": round(total_latency, 1),
                "avg_latency_ms": round(total_latency / n, 1) if n else 0,
                "avg_response_chars": round(
                    sum(m["response_chars"] for m in self._metrics_log) / n, 1
                ) if n else 0,
                "total_probes": sum(m["probes"] for m in self._metrics_log),
                "total_combat_tags": sum(m["combat_tags"] for m in self._metrics_log),
                "total_rules_warnings": sum(m["rules_warnings"] for m in self._metrics_log),
                "turns": self._metrics_log,
            }

            with path.open("w", encoding="utf-8") as fh:
                json.dump(summary, fh, ensure_ascii=False, indent=2)
            logger.info("Session-Metriken gespeichert: %s", path)

            from core.event_bus import EventBus
            bus = EventBus.get()
            bus.emit("game", "metrics_saved", {"path": str(path), "turns": n})
        except Exception as exc:
            logger.warning("Metriken-Export fehlgeschlagen: %s", exc)

    # ------------------------------------------------------------------
    # Grid-Engine: Raumwechsel-Handler
    # ------------------------------------------------------------------

    def _on_location_changed_grid(self, data: dict[str, Any]) -> None:
        """Reagiert auf adventure.location_changed — Grid-Raum wechseln."""
        grid = getattr(self.engine, "grid_engine", None)
        if not grid:
            return
        new_loc_id = data.get("new", "")
        old_loc_id = data.get("old", "")
        if not new_loc_id or not self._adv_manager:
            return
        try:
            loc_data = self._adv_manager._locations.get(new_loc_id)
            if not loc_data:
                return
            grid.transition_room(loc_data, exit_used=old_loc_id)
            # Party neu platzieren
            if self.engine.party_members:
                grid.place_party(self.engine.party_members, entry_exit=old_loc_id)
        except Exception:
            logger.exception("Grid transition_room Fehler")

    # ------------------------------------------------------------------
    # Raumwechsel-Erkennung aus KI-Antwort
    # ------------------------------------------------------------------

    # Verben die Raumwechsel signalisieren (deutsch)
    _ROOM_CHANGE_VERBS = (
        "betritt", "betreten", "betrete", "betretet",
        "geht in", "gehen in", "geht durch", "gehen durch",
        "tritt ein", "treten ein", "tretet ein",
        "erreicht", "erreichen",
        "oeffnet die tuer", "oeffnen die tuer",
        "steigt hinab", "steigen hinab", "steigt hinauf", "steigen hinauf",
        "klettert", "klettern",
        "folgt dem gang", "folgen dem gang",
        "laeuft", "laufen", "rennt", "rennen",
        "schreitet", "schreiten",
        "dringt vor", "dringen vor",
    )

    def _detect_room_change(self, gm_response: str) -> None:
        """Erkennt Raumwechsel aus der KI-Antwort und teleportiert automatisch.

        Strategie:
          1. Aktuelle Location holen + deren Exits (= erreichbare Raeume)
          2. Fuer jeden Exit: Location-Namen und Exit-ID im GM-Text suchen
          3. Wenn ein Raumwechsel-Verb + Location-Name gefunden → teleport()
          4. Fallback: auch ohne Verb, wenn Ortsname prominent erwaehnt wird
        """
        if not self._adv_manager or not self._adv_manager.loaded:
            return

        current_loc = self._adv_manager.get_current_location()
        if not current_loc:
            return

        exits = current_loc.get("exits", {})
        if not exits or not isinstance(exits, dict):
            return

        text_lower = gm_response.lower()

        # Hat der Text ueberhaupt ein Bewegungs-Verb?
        has_movement_verb = any(v in text_lower for v in self._ROOM_CHANGE_VERBS)

        best_match: str | None = None
        best_score = 0

        for exit_loc_id, exit_desc in exits.items():
            # Location-Daten fuer den Exit holen
            exit_loc = self._adv_manager.get_location(exit_loc_id)
            if not exit_loc:
                continue

            exit_name = exit_loc.get("name", "").lower()
            exit_desc_lower = str(exit_desc).lower()

            score = 0

            # Match auf Location-Name (oder Teile davon)
            if exit_name and len(exit_name) > 3:
                # Volltreffer: ganzer Name
                if exit_name in text_lower:
                    score += 10
                else:
                    # Einzelne signifikante Woerter pruefen (>3 Zeichen)
                    name_words = [w for w in exit_name.split() if len(w) > 3]
                    matched = sum(1 for w in name_words if w in text_lower)
                    if name_words and matched >= max(1, len(name_words) // 2):
                        score += matched * 2

            # Match auf Exit-ID (z.B. "wachraum_untergeschoss" als Wort)
            eid_parts = exit_loc_id.replace("_", " ").lower()
            eid_words = [w for w in eid_parts.split() if len(w) > 3]
            eid_matched = sum(1 for w in eid_words if w in text_lower)
            if eid_words and eid_matched >= max(1, len(eid_words) // 2):
                score += eid_matched * 2

            # Match auf Exit-Beschreibung (einzelne signifikante Woerter)
            if exit_desc_lower:
                desc_words = [w for w in exit_desc_lower.split() if len(w) > 4]
                desc_matched = sum(1 for w in desc_words if w in text_lower)
                if desc_words and desc_matched >= max(1, len(desc_words) // 2):
                    score += 1

            # Bewegungsverb boostet den Score
            if has_movement_verb and score > 0:
                score += 5

            if score > best_score:
                best_score = score
                best_match = exit_loc_id

        # Schwellwert: mindestens Score 5 (Verb+Name oder starker Namensmatch)
        if best_match and best_score >= 5:
            old_id = self._adv_manager.current_location_id
            if best_match != old_id:
                loc_name = self._adv_manager.get_location(best_match)
                loc_display = loc_name.get("name", best_match) if loc_name else best_match
                logger.info(
                    "Raumwechsel erkannt: %s -> %s (Score: %d)",
                    old_id, best_match, best_score,
                )
                self._adv_manager.teleport(best_match)
                msg = f"[ORTSWECHSEL] -> {loc_display}"
                print(f"\n{msg}")
                self._emit_game("system", msg)

    # ------------------------------------------------------------------
    # Interner Game-Loop
    # ------------------------------------------------------------------

    def _game_loop(self) -> None:
        from core.mechanics import MechanicsEngine
        from core.ai_backend import extract_probes
        from core.character import extract_stat_changes, extract_inventory_changes, extract_time_changes, extract_combat_tags, extract_party_stat_changes
        from core.memory import extract_facts
        from core.time_tracker import TimeTracker

        # Tables laden fuer AD&D 2e Lookups (THAC0, Saves, etc.)
        tables_data = self.engine.ruleset.get("tables_data") or {}
        mechanics = MechanicsEngine(
            dice_config=self.engine.dice_config,
            tables_data=tables_data,
        )

        # TimeTracker instanziieren und ans AI-Backend koppeln
        self._time_tracker = TimeTracker()
        if self.engine.ai_backend:
            self.engine.ai_backend.set_time_tracker(self._time_tracker)

        # LatencyLogger instanziieren
        from core.latency_logger import LatencyLogger
        self._latency_logger = LatencyLogger()

        turn_number = 0

        self._session_start = _time.perf_counter()

        while self._active:
            # ── Eingabe ────────────────────────────────────────────────
            user_input = self._get_input()
            if user_input is None:
                # EOF / KeyboardInterrupt
                print("\n[SYSTEM] Session unterbrochen.")
                break

            if not user_input:
                continue

            # ── System-Kommandos ───────────────────────────────────────
            if user_input.lower() in {"quit", "exit", "beenden"}:
                self.stop_session()
                break

            if user_input.lower() == "/status":
                if self.engine.character:
                    print(f"[CHARAKTER] {self.engine.character.status_line()}\n")
                continue

            if user_input.lower().startswith(("/roll ", "/wuerfl ")):
                parts = user_input.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    target = int(parts[1])
                    result = mechanics.skill_check(target)
                    print(f"[WUERFEL] {result.description}\n")
                else:
                    print("[SYSTEM] Syntax: /roll <Fertigkeitswert>\n")
                continue

            if user_input.lower() == "/orte":
                if self._adv_manager and self._adv_manager.loaded:
                    locs = self._adv_manager.list_locations()
                    cur = self._adv_manager.current_location_id
                    print("[ORTE]")
                    for lid, name in locs:
                        marker = " <--" if lid == cur else ""
                        print(f"  {lid}: {name}{marker}")
                    print()
                else:
                    print("[SYSTEM] Kein Abenteuer geladen.\n")
                continue

            if user_input.lower().startswith("/teleport "):
                loc_id = user_input.split(maxsplit=1)[1].strip()
                if self._adv_manager and self._adv_manager.teleport(loc_id):
                    loc = self._adv_manager.get_current_location()
                    print(f"[TELEPORT] {loc.get('name', loc_id)}\n")
                else:
                    print(f"[SYSTEM] Ort '{loc_id}' nicht gefunden.\n")
                continue

            if user_input.lower() == "/inventar":
                if self.engine.character:
                    inv = self.engine.character.get_inventory()
                    if inv:
                        print("[INVENTAR]")
                        for item in inv:
                            print(f"  - {item}")
                        print()
                    else:
                        print("[INVENTAR] Leer.\n")
                else:
                    print("[SYSTEM] Kein Charakter geladen.\n")
                continue

            if user_input.lower() == "/zeit":
                if hasattr(self, "_time_tracker") and self._time_tracker:
                    print(f"[ZEIT] {self._time_tracker.get_context_for_prompt()}\n")
                else:
                    print("[SYSTEM] Kein TimeTracker aktiv.\n")
                continue

            if user_input.lower() == "/flags":
                if self._adv_manager:
                    flags = self._adv_manager.get_all_flags()
                    if flags:
                        print("[FLAGS]")
                        for k, v in sorted(flags.items()):
                            print(f"  {k}: {v}")
                        print()
                    else:
                        print("[FLAGS] Keine Flags definiert.\n")
                else:
                    print("[SYSTEM] Kein Abenteuer geladen.\n")
                continue

            # ── Spieler-Bewegung VOR KI-Aufruf (Grid als SSOT) ─────
            _grid_pre = getattr(self.engine, "grid_engine", None)
            if _grid_pre and _grid_pre._current_room:
                try:
                    _grid_pre.parse_player_movement(user_input)
                except Exception:
                    logger.exception("Pre-AI Grid-Bewegung Fehler")

            # ── Neue Kampfrunde starten (vor AI-Aufruf) ─────────────
            if self._combat_tracker and self._combat_tracker.active:
                round_info = self._combat_tracker.start_new_round(mechanics)
                print(f"\n{round_info['detail']}")
                self._emit_game("initiative", round_info["detail"])
                # Grid-Bewegungsbudget zuruecksetzen
                _grid = getattr(self.engine, "grid_engine", None)
                if _grid:
                    _grid.reset_all_movement()

            # ── KI-Antwort streamen ────────────────────────────────────
            self._session_history.append({"role": "user", "content": user_input})
            self._emit_game("player", user_input)

            print("[SPIELLEITER] ", end="", flush=True)
            self._emit_game("stream_start", "")
            if self._latency_logger:
                self._latency_logger.start_turn()
                self._latency_logger.start("ai")
            _t0 = _time.perf_counter()
            gm_response = self._stream_gm_response(user_input)
            _latency_ms = (_time.perf_counter() - _t0) * 1000.0
            if self._latency_logger:
                self._latency_logger.stop("ai")
            print()  # Zeilenumbruch nach Stream-Ende
            self._emit_game("stream_end", gm_response)

            self._session_history.append({"role": "assistant", "content": gm_response})

            # ── Rules Validation (Schicht 2) ─────────────────────────
            rules_engine = getattr(self.engine, "rules_engine", None)
            _rules_warning_count = 0
            if rules_engine:
                pre_probes = extract_probes(gm_response)
                pre_stats = extract_stat_changes(gm_response)
                pre_combat = extract_combat_tags(gm_response)
                pre_inv = extract_inventory_changes(gm_response)
                char_stats = None
                char_skills = None
                if self.engine.character:
                    char_stats = getattr(self.engine.character, "stats", None)
                    char_skills = getattr(self.engine.character, "_skills", None)
                validations = rules_engine.validate_tags(
                    probes=pre_probes,
                    stat_changes=pre_stats,
                    combat_tags=pre_combat,
                    inventory_changes=pre_inv,
                    character_stats=char_stats,
                    character_skills=char_skills,
                )
                for vr in validations:
                    if vr.severity in ("warning", "error"):
                        msg = f"[REGELCHECK] {vr.tag_type}: {vr.message}"
                        logger.warning(msg)
                        self._emit_game("rules_warning", msg)
                        _rules_warning_count += 1

            # ── Proben-Marker verarbeiten ──────────────────────────────
            probes = extract_probes(gm_response)
            for skill_name, target_value in probes:
                self._handle_probe(skill_name, target_value, mechanics)

            # ── Kampf-Tags verarbeiten (AD&D 2e) ────────────────────
            # Im Party-Modus: CombatTracker deaktiviert — HP wird ueber
            # [HP_VERLUST: Name | N] Tags in _handle_party_tags() verwaltet.
            party_state = getattr(self.engine, "party_state", None)
            combat_tags = extract_combat_tags(gm_response)
            if not party_state:
                # Initiative-Sortierung: gewinnende Seite zuerst
                if self._combat_tracker and self._combat_tracker.active and combat_tags:
                    combat_tags = self._sort_by_initiative(combat_tags)
                for tag_type, data in combat_tags:
                    self._handle_combat(tag_type, data, mechanics)
                    if not self._active:
                        break  # Spieler tot — restliche Tags ueberspringen

            if not self._active:
                break  # Spieler tot — Game Loop beenden

            # ── Zustandsaenderungs-Tags verarbeiten ────────────────────
            stat_changes = extract_stat_changes(gm_response)
            for stat_tuple in stat_changes:
                self._handle_stat_change(stat_tuple[0], stat_tuple[1] if len(stat_tuple) > 1 else "", mechanics, stat_tuple[2:] if len(stat_tuple) > 2 else ())

            # ── INVENTAR-Tags verarbeiten ────────────────────────────
            inventory_changes = extract_inventory_changes(gm_response)
            for item_name, action in inventory_changes:
                self._handle_inventory(item_name, action)

            # ── ZEIT/WETTER-Tags verarbeiten ─────────────────────────
            time_changes = extract_time_changes(gm_response)
            for tag_type, value in time_changes:
                self._handle_time(tag_type, value)

            # ── FAKT-Tags verarbeiten (World State) ───────────────────
            facts_list = extract_facts(gm_response)
            for facts in facts_list:
                self._handle_facts(facts)

            # ── Party-Tags verarbeiten (Multi-Charakter-Modus) ────────
            self._last_party_tag_count = 0
            party_state = getattr(self.engine, "party_state", None)
            if party_state:
                self._handle_party_tags(gm_response, party_state, mechanics)
                # TPK-Check: alle tot -> Session beenden
                if party_state.is_tpk():
                    tpk_msg = "TOTAL PARTY KILL! Alle Gruppenmitglieder sind gefallen!"
                    print(f"\n[SYSTEM] {tpk_msg}")
                    self._emit_game("system", tpk_msg)
                    from core.event_bus import EventBus
                    EventBus.get().emit("party", "tpk", {"message": tpk_msg})
                    self._active = False
                # Party-Save nach jedem Zug
                self._handle_party_save(turn_number + 1)

            # ── DMG-Mechanik-Tags verarbeiten ─────────────────────────
            self._handle_dmg_tags(gm_response, mechanics)

            # ── Raumwechsel-Erkennung + Grid-Bewegung ────────────────
            grid = getattr(self.engine, "grid_engine", None)
            if grid and grid._current_room:
                try:
                    current_loc = None
                    if self._adv_manager and self._adv_manager.loaded:
                        current_loc = self._adv_manager.get_current_location()
                    grid.infer_movement(gm_response, current_loc)
                    grid.infer_action_movement(gm_response)
                except Exception:
                    logger.exception("Grid-Bewegungs-Inferenz Fehler")

                # ── Monster-Bewegung aus KI-Tags ──────────────────
                try:
                    monster_moves = _extract_monster_moves(gm_response)
                    if monster_moves:
                        grid.execute_monster_moves(monster_moves)
                    # Idle-Monster patrouillieren (30% Chance pro Monster)
                    moved_ids: set[str] = set()
                    for name, _ in monster_moves:
                        ent = grid._find_entity_by_name(name)
                        if ent:
                            moved_ids.add(ent.entity_id)
                    grid.auto_roam_idle_monsters(moved_ids)
                except Exception:
                    logger.exception("Monster-Bewegungs-Verarbeitung Fehler")

            # Raumwechsel aus KI-Text erkennen (nach Grid-Bewegung)
            self._detect_room_change(gm_response)

            # ── Auto-Save: Turn in DB persistieren ────────────────────
            turn_number += 1
            self._turn_number = turn_number
            if self.engine.character:
                self.engine.character.log_turn(
                    self._session_id,
                    turn_number,
                    user_input,
                    gm_response,
                )

            # ── Latency-Logger: Turn abschliessen ────────────────────
            if self._latency_logger:
                self._latency_logger.finish_turn(turn_number)

            # ── Metrics-Log: Zug-Metriken erfassen ──────────────────
            self._metrics_log.append({
                "turn": turn_number,
                "latency_ms": round(_latency_ms, 1),
                "response_chars": len(gm_response),
                "probes": len(probes),
                "combat_tags": len(combat_tags),
                "stat_changes": len(stat_changes) + self._last_party_tag_count,
                "inventory_changes": len(inventory_changes),
                "time_changes": len(time_changes),
                "facts": len(facts_list),
                "rules_warnings": _rules_warning_count,
            })

            # ── Kosten-Limit pruefen ──────────────────────────────
            ai = self.engine.ai_backend
            if ai and getattr(ai, "_cost_tracker", None):
                ct = ai._cost_tracker
                exceeded, msg = ct.check_session_limit()
                if not exceeded:
                    lim = ct.check_limits()
                    if lim["blocked"]:
                        exceeded, msg = True, lim["block_reason"]
                if exceeded:
                    warn = f"[KOSTEN] Session beendet: {msg}"
                    logger.warning(warn)
                    self._gm_print(warn)
                    self._emit_game("system", warn)
                    self.stop_session()
                    break

            # ── Chronik-Update alle SUMMARY_INTERVAL Runden ───────────
            if self._archivist and self._archivist.should_summarize(turn_number):
                self._update_chronicle(turn_number)

    # ------------------------------------------------------------------
    # Proben-Verarbeitung
    # ------------------------------------------------------------------

    def _handle_probe(
        self,
        skill_name: str,
        target_value: int,
        mechanics: Any,
    ) -> None:
        """Fuehrt eine angeforderte Probe durch und injiziert das Ergebnis in die KI."""
        # Alias-Resolution: falsche Skill-Namen korrigieren
        if hasattr(self.engine, "rules_engine") and self.engine.rules_engine:
            resolved, was_aliased = self.engine.rules_engine.resolve_skill_alias(skill_name)
            if was_aliased:
                logger.info("Probe Skill-Alias: '%s' -> '%s'", skill_name, resolved)
                skill_name = resolved
        print(f"\n[PROBE angefordert] {skill_name} (Zielwert: {target_value})")
        self._emit_game("probe", f"[PROBE] {skill_name} (Zielwert: {target_value})")
        if not self.engine._voice_enabled and not self._gui_mode:
            # Nur im reinen Text-Modus auf ENTER warten
            try:
                input("  Druecke ENTER um zu wuerfeln...")
            except EOFError:
                pass

        result = mechanics.skill_check(target_value)
        print(f"[WUERFEL] {result.description}\n")
        self._emit_game("dice", result.description)

        # Ergebnis an KI schicken — GM antwortet narrativ (mit TTS)
        self._narrate_roll_result(skill_name, result, mechanics)

    # ------------------------------------------------------------------
    # Zustandsaenderungs-Verarbeitung (Task 04)
    # ------------------------------------------------------------------

    def _handle_stat_change(
        self,
        change_type: str,
        value_str: str,
        mechanics: Any,
        extra: tuple = (),
    ) -> None:
        """
        Verarbeitet HP_VERLUST, STABILITAET_VERLUST, FERTIGKEIT_GENUTZT und
        alle 8 Monster-Mechanik-Tags (Session 19).
        Alle Aenderungen werden sofort in die SQLite-DB geschrieben.

        extra: zusaetzliche Werte fuer Tags mit mehr als 2 Parametern
               z.B. bei GIFT: extra = (typ, save_mod_str)
        """
        character = self.engine.character
        if character is None:
            return

        if change_type == "HP_VERLUST":
            # Im aktiven Kampf verwaltet der CombatTracker die HP mechanisch
            if self._combat_tracker and self._combat_tracker.active:
                logger.debug("HP_VERLUST ignoriert (CombatTracker aktiv)")
                return
            amount = int(value_str)
            result = character.update_stat("HP", -amount)
            if "error" not in result:
                msg = (
                    f"[HP-VERLUST] -{amount} | "
                    f"HP: {result['old_value']} -> {result['new_value']}"
                    f"/{result['max_value']}"
                )
                print(f"\n{msg}")
                self._emit_game("stat", msg)
                if character.is_dead:
                    death_msg = f"Der {self.engine.pc_title} ist bewusstlos oder gefallen!"
                    print(f"[SYSTEM] {death_msg}")
                    self._emit_game("system", death_msg)

        elif change_type == "STABILITAET_VERLUST":
            # SAN nicht unterstuetzt in AD&D 2e — Tag wird ignoriert
            logger.debug("STABILITAET_VERLUST ignoriert (AD&D 2e hat keine SAN).")
            return

        elif change_type == "HP_HEILUNG":
            amount = mechanics.roll_expression(value_str)
            result = character.update_stat("HP", +amount)
            if "error" not in result:
                msg = (
                    f"[HP-HEILUNG] +{amount} "
                    f"(Wurf: {value_str}) | "
                    f"HP: {result['old_value']} -> {result['new_value']}"
                    f"/{result['max_value']}"
                )
                print(f"\n{msg}")
                self._emit_game("stat", msg)

        elif change_type == "XP_GEWINN":
            amount = int(value_str)
            xp_result = character.add_xp(amount)
            msg = (
                f"[XP] +{amount} Erfahrungspunkte | "
                f"Gesamt: {xp_result['new_xp']}"
            )
            print(f"\n{msg}")
            self._emit_game("stat", msg)

        elif change_type == "FERTIGKEIT_GENUTZT":
            # Skill-Steigerung nicht bei AD&D 2e (kein Improvement durch Nutzung).
            logger.debug("FERTIGKEIT_GENUTZT ignoriert (AD&D 2e hat kein Skill-Improvement).")
            return

        # ── Monster-Mechanik-Tags (Session 19) ─────────────────────────────

        elif change_type == "MAGIC_RESISTANCE":
            # value_str = monster_name, extra[0] = prozent_str
            monster_name = value_str
            try:
                prozent = int(extra[0]) if extra else 0
            except (ValueError, IndexError):
                prozent = 0
            wurf = random.randint(1, 100)
            if wurf <= prozent:
                msg = (
                    f"Magieresistenz von {monster_name}: {wurf}% — Zauber scheitert! "
                    f"(Resistenz: {prozent}%)"
                )
            else:
                msg = (
                    f"Magieresistenz von {monster_name}: {wurf}% — Zauber durchdringt! "
                    f"(Resistenz: {prozent}%)"
                )
            print(f"\n[MAGIC_RESISTANCE] {msg}")
            self._emit_game("combat", f"[MAGIC_RESISTANCE] {msg}")

        elif change_type == "WAFFEN_IMMUNITAET":
            # value_str = monster_name, extra[0] = mindest_bonus
            monster_name = value_str
            bonus = extra[0] if extra else "magisch"
            msg = (
                f"[WARNUNG] {monster_name} kann nur von Waffen mit "
                f"+{bonus} oder besser getroffen werden!"
            )
            print(f"\n{msg}")
            self._emit_game("combat", msg)

        elif change_type == "GIFT":
            # value_str = monster_name, extra[0] = typ, extra[1] = save_mod_str
            monster_name = value_str
            gift_typ = extra[0].strip().lower() if extra else "schaden"
            try:
                save_mod = int(extra[1]) if len(extra) > 1 else 0
            except (ValueError, IndexError):
                save_mod = 0
            # Rettungswurf vs. Gift
            try:
                # Standardwert fuer Rettungswurf vs. Gift/Paralyse/Tod (AD&D 2e Tabelle 60)
                # Typischer Zielwert fuer mittlere Charakterstufe: 16
                save_result = mechanics.saving_throw(
                    target=16,
                    modifiers=save_mod,
                )
                save_success = save_result.is_success
            except Exception:
                # Fallback: einfacher d20-Wurf gegen 16 + Modifikator
                roll = random.randint(1, 20)
                save_success = (roll + save_mod) >= 16
            if not save_success:
                if gift_typ in ("tod", "toedlich", "death"):
                    msg = f"[GIFT] Toedliches Gift von {monster_name}! Rettungswurf MISSLUNGEN — lebensgefaehrlich!"
                elif gift_typ in ("paralyse", "paralysis"):
                    msg = f"[GIFT] Gift von {monster_name}! Rettungswurf MISSLUNGEN — Paralyse fuer 1d6 Runden!"
                elif gift_typ in ("krankheit", "disease"):
                    msg = f"[GIFT] Krankheit von {monster_name}! Rettungswurf MISSLUNGEN — Krankheit kontrahiert!"
                else:
                    msg = f"[GIFT] Gift von {monster_name}! Rettungswurf MISSLUNGEN — zusaetzlicher Giftschaden!"
            else:
                msg = f"[GIFT] Gift von {monster_name}! Rettungswurf GELUNGEN — kein Effekt!"
            print(f"\n{msg}")
            self._emit_game("combat", msg)

        elif change_type == "LEVEL_DRAIN":
            # value_str = char_name, extra[0] = stufen_str
            char_name = value_str
            try:
                stufen = int(extra[0]) if extra else 1
            except (ValueError, IndexError):
                stufen = 1
            # Level reduzieren (falls vorhanden)
            char = self.engine.character
            if char:
                current_level = char._stats.get("Level", 1)
                if isinstance(current_level, (int, float)):
                    new_level = max(0, int(current_level) - stufen)
                    update_result = char.update_stat("Level", new_level - int(current_level))
                    level_info = f"Neues Level: {new_level}"
                    if "error" in update_result:
                        level_info = "(Level-Stat nicht gefunden)"
                else:
                    level_info = "(Level-Tracking nicht verfuegbar)"
                # HP-Verlust: 1d8 pro Stufe
                hp_loss = sum(random.randint(1, 8) for _ in range(stufen))
                char.update_stat("HP", -hp_loss)
                msg = (
                    f"[LEVEL_DRAIN] {char_name} verliert {stufen} "
                    f"Erfahrungsstufe(n)! {level_info} "
                    f"| -{hp_loss} HP"
                )
            else:
                msg = (
                    f"[LEVEL_DRAIN] {char_name} verliert {stufen} "
                    f"Erfahrungsstufe(n)! (Kein Charakter geladen)"
                )
            print(f"\n{msg}")
            self._emit_game("stat", msg)

        elif change_type == "MORAL_CHECK":
            # value_str = monster_name, extra[0] = schwelle_str
            monster_name = value_str
            try:
                schwelle = int(extra[0]) if extra else 7
            except (ValueError, IndexError):
                schwelle = 7
            wurf = random.randint(1, 6) + random.randint(1, 6)
            if wurf > schwelle:
                msg = (
                    f"[MORAL] {monster_name}: Moral-Check 2d6={wurf} > {schwelle} "
                    f"— Monster FLIEHT!"
                )
            else:
                msg = (
                    f"[MORAL] {monster_name}: Moral-Check 2d6={wurf} <= {schwelle} "
                    f"— Monster kaempft weiter!"
                )
            print(f"\n{msg}")
            self._emit_game("combat", msg)

        elif change_type == "REGENERATION":
            # value_str = monster_name, extra[0] = hp_pro_runde_str
            monster_name = value_str
            try:
                hp_per_round = int(extra[0]) if extra else 1
            except (ValueError, IndexError):
                hp_per_round = 1
            # Im CombatTracker registrieren (falls aktiv)
            if self._combat_tracker and self._combat_tracker.active:
                self._combat_tracker.register_regeneration(monster_name, hp_per_round)
            msg = f"[REGENERATION] {monster_name} regeneriert {hp_per_round} HP pro Runde."
            print(f"\n{msg}")
            self._emit_game("combat", msg)

        elif change_type == "FURCHT":
            # value_str = char_name, extra[0] = effekt, extra[1] = dauer_str
            char_name = value_str
            effekt = extra[0].strip().lower() if extra else "flucht"
            dauer = extra[1].strip() if len(extra) > 1 else "unbekannt"
            if effekt in ("flucht", "flee", "flieht"):
                msg = f"[FURCHT] {char_name} ergreift die Flucht! Dauer: {dauer} Runden"
            elif effekt in ("paralyse", "gelähmt", "gelaehmt", "paralysis"):
                msg = f"[FURCHT] {char_name} ist vor Furcht gelaehmt! Dauer: {dauer} Runden"
            elif effekt in ("alterung", "aging", "altert"):
                msg = f"[FURCHT] {char_name} altert schlagartig! (Uebernatuerliche Furcht)"
            else:
                msg = f"[FURCHT] {char_name}: {effekt}. Dauer: {dauer} Runden"
            print(f"\n{msg}")
            self._emit_game("combat", msg)

        elif change_type == "ATEM_WAFFE":
            # value_str = monster_name, extra[0] = typ, extra[1] = schaden_str
            monster_name = value_str
            atem_typ = extra[0].strip() if extra else "Feuer"
            schaden_str = extra[1].strip() if len(extra) > 1 else "1d6"
            try:
                total = mechanics.roll_expression(schaden_str)
            except Exception:
                # Fallback: einfach 1d10
                total = random.randint(1, 10)
            msg = (
                f"[ATEM_WAFFE] {monster_name} setzt {atem_typ}-Atem ein! "
                f"Voller Schaden: {total}. Rettungswurf gegen Atemwaffe = "
                f"halber Schaden ({total // 2})."
            )
            print(f"\n{msg}")
            self._emit_game("combat", msg)

    # ------------------------------------------------------------------
    # Task 05 — Archivist-Methoden
    # ------------------------------------------------------------------

    def _handle_facts(self, facts: dict) -> None:
        """Persistiert einen FAKT-Tag-Inhalt im World State des Archivist + AdventureManager."""
        if not self._archivist or not facts:
            return
        self._archivist.merge_world_state(facts)
        # Flags auch im AdventureManager aktualisieren (Task 06)
        if self._adv_manager:
            self._adv_manager.merge_flags_from_world_state(facts)
        facts_str = ", ".join(f"{k}={v}" for k, v in facts.items())
        msg = f"[FAKT] World State aktualisiert: {facts_str}"
        print(f"\n{msg}")
        self._emit_game("fact", msg)

    # ------------------------------------------------------------------
    # Kampf-Verarbeitung (AD&D 2e)
    # ------------------------------------------------------------------

    def _start_combat(self) -> None:
        """Initialisiert den CombatTracker aus der aktuellen Location."""
        from core.combat_tracker import CombatTracker

        if not self._adv_manager:
            return

        loc = self._adv_manager.get_current_location()
        if not loc:
            return

        # NPCs an aktueller Location suchen
        npc_ids = loc.get("npcs_present", [])
        npcs = [
            self._adv_manager.get_npc(nid)
            for nid in npc_ids
            if self._adv_manager.get_npc(nid)
        ]

        # Fallback: Alle NPCs aus allen Locations durchsuchen
        if not npcs:
            for loc_data in self._adv_manager._locations.values():
                for nid in loc_data.get("npcs_present", []):
                    npc = self._adv_manager.get_npc(nid)
                    if npc and npc not in npcs:
                        npcs.append(npc)

        if not npcs:
            logger.warning("_start_combat: Keine NPCs gefunden")
            return

        # MechanicsEngine fuer Lookups
        from core.mechanics import MechanicsEngine
        tables_data = self.engine.ruleset.get("tables_data") or {}
        mech = MechanicsEngine(
            dice_config=self.engine.dice_config,
            tables_data=tables_data,
        )

        # Spieler-Stats zusammenbauen
        char = self.engine.character
        player_stats = {"name": "Spieler", "hp": 10, "hp_max": 10,
                        "ac": 10, "thac0": 20, "weapon": "Waffe",
                        "damage": "1d6", "movement": 12,
                        "level": 1, "class_group": "warrior",
                        "speed_factor": 5, "attacks_per_round": "1/1",
                        "armor": ""}
        if char:
            player_stats["name"] = char.name
            player_stats["hp"] = char._stats.get("HP", 10)
            player_stats["hp_max"] = char._stats_max.get("HP", 10)
            ds = getattr(char, "_derived_stats", {})
            player_stats["ac"] = ds.get("AC", 10)
            player_stats["thac0"] = ds.get("THAC0", 20)
            player_stats["movement"] = ds.get("Movement", 12)
            player_stats["level"] = char._stats.get("Level", 1)
            # Klassengruppe
            char_class = char._stats.get("Class", "fighter")
            cg = mech.lookup_class_group(char_class)
            player_stats["class_group"] = cg
            # Waffe aus Equipment/Skills ableiten
            skills = getattr(char, "_skills", {})
            for skill_name in skills:
                if "Weapon Proficiency" in skill_name:
                    weapon = skill_name.replace("Weapon Proficiency (", "").rstrip(")")
                    player_stats["weapon"] = weapon
                    break
            player_stats["damage"] = "1d8"  # Standard-Schwertschaden
            # Ruestung aus Inventar ableiten
            inventory = getattr(char, "_inventory", [])
            _ARMOR_KW = ("armor", "mail", "plate", "leather", "shield",
                         "ruestung", "rüstung", "panzer", "schild", "kettenhemd")
            for item in inventory:
                item_lower = item.lower() if isinstance(item, str) else ""
                if any(kw in item_lower for kw in _ARMOR_KW):
                    player_stats["armor"] = item
                    break
            # Speed-Factor + Attacks-per-Round
            player_stats["speed_factor"] = mech.lookup_speed_factor(
                player_stats["weapon"],
            )
            player_stats["attacks_per_round"] = mech.lookup_attacks_per_round(
                cg, player_stats["level"],
            )

        self._combat_tracker = CombatTracker()
        # Bridge: Mechanics + GridEngine fuer Distanz-/Reichweitenprüfung
        self._combat_tracker.set_mechanics(mech)
        grid = getattr(self.engine, "grid_engine", None)
        if grid:
            self._combat_tracker.set_grid_engine(grid)
        self._combat_tracker.start_combat(loc, npcs, player_stats)

        # An AI-Backend koppeln
        if self.engine.ai_backend:
            self.engine.ai_backend.set_combat_tracker(self._combat_tracker)

        # Kampfstatus emittieren
        status = self._combat_tracker.get_status_text()
        print(f"\n{status}")
        self._emit_game("combat_state", status)

    # ------------------------------------------------------------------
    # Waffen-Validierung
    # ------------------------------------------------------------------

    _WEAPON_ALIASES: dict[str, list[str]] = {
        "long sword": ["longsword", "langschwert"],
        "short sword": ["shortsword", "kurzschwert"],
        "short bow": ["shortbow", "kurzbogen"],
        "longbow": ["long bow", "langbogen"],
        "chain mail": ["chainmail", "kettenhemd", "kettenpanzer"],
        "leather armor": ["leather armour", "lederruestung"],
        "studded leather armor": ["studded leather", "beschlagene lederruestung"],
        "steel shield": ["schild", "stahlschild"],
        "wooden shield": ["holzschild"],
        "quarterstaff": ["quarter staff", "kampfstab", "stab"],
        "two-handed sword": ["zweihander", "zweihandschwert"],
    }

    def _player_has_weapon(self, weapon_name: str) -> bool:
        """Prueft ob der Spieler die genannte Waffe im Inventar hat.

        Fuzzy-Matching: normalisiert auf lowercase und prueft Teilstrings
        sowie gaengige Aliase (deutsch/englisch, Bindestrich-Varianten).
        """
        if not self.engine.character:
            return True  # Kein Charakter -> kein Check

        inventory = self.engine.character.get_inventory()
        if not inventory:
            return True  # Leeres Inventar -> kein Check (Startphase)

        needle = weapon_name.strip().lower()

        # Direkte Teilstring-Suche
        for item in inventory:
            item_l = item.lower()
            if needle in item_l or item_l in needle:
                return True

        # Alias-Suche: Waffe -> alle bekannten Varianten
        for canonical, aliases in self._WEAPON_ALIASES.items():
            all_names = [canonical] + aliases
            # Ist die gesuchte Waffe eine dieser Varianten?
            needle_match = any(n in needle or needle in n for n in all_names)
            if not needle_match:
                continue
            # Hat der Spieler eine dieser Varianten im Inventar?
            for item in inventory:
                item_l = item.lower()
                if any(n in item_l or item_l in n for n in all_names):
                    return True

        return False

    # Fernkampfwaffen -> benoetigte Munitionsart
    _RANGED_AMMO: dict[str, str] = {
        "shortbow": "arrows",
        "short bow": "arrows",
        "kurzbogen": "arrows",
        "longbow": "arrows",
        "long bow": "arrows",
        "langbogen": "arrows",
        "composite longbow": "arrows",
        "light crossbow": "bolts",
        "heavy crossbow": "bolts",
        "armbrust": "bolts",
        "sling": "bullets",
        "schleuder": "bullets",
    }

    def _consume_ammo(self, weapon_name: str) -> bool:
        """Verbraucht 1 Munition fuer eine Fernkampfwaffe.

        Returns True wenn Munition vorhanden und verbraucht,
        False wenn keine Munition -> Angriff nicht moeglich.
        """
        char = self.engine.character
        if not char:
            return True

        needle = weapon_name.strip().lower()
        ammo_type: str | None = None
        for wpn, ammo in self._RANGED_AMMO.items():
            if wpn in needle or needle in wpn:
                ammo_type = ammo
                break

        if ammo_type is None:
            return True  # Keine Fernkampfwaffe -> kein Munitionsverbrauch

        # Suche Munition im Inventar: "Arrows (17)", "Bolts (10)", etc.
        import re
        inventory = char.get_inventory()
        for i, item in enumerate(inventory):
            item_l = item.lower()
            if ammo_type not in item_l:
                continue
            # Zahl in Klammern extrahieren
            m = re.search(r"\((\d+)\)", item)
            if m:
                count = int(m.group(1))
                if count <= 0:
                    break  # 0 Munition
                new_count = count - 1
                # Inventar-Eintrag aktualisieren
                new_name = item[:m.start()] + f"({new_count})" + item[m.end():]
                char._inventory[i] = new_name
                char.save()
                logger.info("Munition: %s -> %d verbleibend", ammo_type, new_count)
                self._emit_game("system", f"[Munition: {new_name.strip()}]")
                if new_count == 0:
                    self._emit_game("system", f"[Letzte Munition verbraucht!]")
                return True
            else:
                # Kein Zaehler -> als "unendlich" behandeln
                return True

        # Keine Munition gefunden
        logger.info("Angriff ignoriert: keine %s im Inventar", ammo_type)
        self._emit_game("system", f"[Keine {ammo_type.title()} im Inventar — Angriff ignoriert]")
        return False

    def _handle_combat(self, tag_type: str, data: dict, mechanics: Any) -> None:
        """Verarbeitet ANGRIFF und RETTUNGSWURF Tags mit CombatTracker."""
        if tag_type == "ANGRIFF":
            weapon = data["weapon"]
            thac0 = data["thac0"]
            target_ac = data["target_ac"]

            # CombatTracker starten wenn noch nicht aktiv
            if not self._combat_tracker or not self._combat_tracker.active:
                self._start_combat()

            # Ziel und Angreifer ermitteln (Waffe als Fallback)
            attacker = None
            target = None
            if self._combat_tracker and self._combat_tracker.active:
                attacker = self._combat_tracker.get_attacker(thac0, weapon)
                target = self._combat_tracker.find_target(target_ac, attacker)

                # Waffen-Validierung: Spieler darf nur mit Inventar-Waffen angreifen
                if attacker and attacker.is_player and self.engine.character:
                    if not self._player_has_weapon(weapon):
                        logger.info(
                            "Angriff ignoriert: Spieler hat '%s' nicht im Inventar",
                            weapon,
                        )
                        self._emit_game(
                            "system",
                            f"[Waffe '{weapon}' nicht im Inventar — Angriff ignoriert]",
                        )
                        return
                    # Munitionsverbrauch bei Fernkampf
                    if not self._consume_ammo(weapon):
                        return

                # Reichweiten-Validierung (GridEngine-Bridge)
                if attacker and target:
                    range_check = self._combat_tracker.validate_attack_range(
                        attacker.id, target.id,
                    )
                    if not range_check["valid"]:
                        logger.info(
                            "Angriff ignoriert: %s -> %s (%s)",
                            attacker.name, target.name, range_check["reason"],
                        )
                        self._emit_game(
                            "system",
                            f"[Angriff ungueltig: {range_check['reason']}]",
                        )
                        return
                    # Fernkampf-Modifikator auf Modifikatoren addieren
                    if range_check["range_mod"] != 0:
                        data["modifiers"] = data.get("modifiers", 0) + range_check["range_mod"]
                        logger.debug(
                            "Fernkampf-Modifikator %+d fuer %s (%d Felder)",
                            range_check["range_mod"], attacker.name, range_check["distance"],
                        )

                # Angriffslimit pruefen
                if attacker and not self._combat_tracker.can_attack(attacker.id):
                    logger.info(
                        "Angriff ignoriert: %s hat max Angriffe erreicht",
                        attacker.name,
                    )
                    return
                if attacker:
                    self._combat_tracker.register_attack(attacker.id)

                # CombatTracker-Stats verwenden statt AI-Werte
                if attacker:
                    thac0 = attacker.thac0

            # Wuerfeln (erst nach Validierung)
            result = mechanics.attack_roll(
                thac0=thac0,
                target_ac=target.ac if target else target_ac,
                modifiers=data["modifiers"],
            )

            # -- Angreifer/Ziel-Namen fuer Anzeige --
            atk_name = attacker.name if attacker else weapon
            tgt_name = target.name if target else "?"

            # Bei Treffer: Schaden wuerfeln und anwenden
            dmg_result = None
            damage_detail = ""
            if result.is_success and target and attacker and self._combat_tracker:
                damage_dice = attacker.damage
                damage, damage_detail = mechanics.roll_damage(damage_dice)
                dmg_result = self._combat_tracker.apply_damage(target.id, damage)

                # Spieler-HP auch im CharacterManager aktualisieren
                if target.is_player and self.engine.character:
                    stat_result = self.engine.character.update_stat("HP", -damage)
                    if "error" not in stat_result:
                        self._emit_game(
                            "stat",
                            f"[HP-VERLUST] -{damage} | HP: "
                            f"{stat_result['old_value']} -> "
                            f"{stat_result['new_value']}/{stat_result['max_value']}",
                        )
                        # Spieler-Tod: Game Loop stoppen
                        if self.engine.character.is_dead:
                            self._active = False
                            from core.event_bus import EventBus
                            EventBus.get().emit(
                                "game", "player_dead",
                                {"message": f"{self.engine.character.name} ist gefallen!"},
                            )

            # -- Strukturierte Combat-Message --
            # Zeile 1: Wer -> Wen (Waffe)
            header = f"{atk_name} -> {tgt_name} ({weapon})"
            # Zeile 2: Wurf-Details
            roll_line = (
                f"  Wurf: d20={result.roll} | "
                f"Ziel: {result.target} (THAC0 {thac0} vs AC {target_ac})"
            )
            # Zeile 3: Ergebnis
            if result.is_success:
                hit_str = "TREFFER"
                if result.roll == 20:
                    hit_str = "KRITISCHER TREFFER (Nat 20!)"
            else:
                hit_str = "VERFEHLT"
                if result.roll == 1:
                    hit_str = "PATZER (Nat 1!)"
            result_line = f"  Ergebnis: {hit_str}"
            # Zeile 4: Schaden (nur bei Treffer)
            dmg_line = ""
            if dmg_result:
                dmg_line = (
                    f"  Schaden: {damage_detail} | "
                    f"{dmg_result['target']} HP: {dmg_result['hp_old']}"
                    f" -> {dmg_result['hp_new']}/{dmg_result['hp_max']}"
                )
                if dmg_result["killed"]:
                    dmg_line += " [TOT]"

            msg = header + "\n" + roll_line + "\n" + result_line
            if dmg_line:
                msg += "\n" + dmg_line

            print(f"\n{msg}")
            self._emit_game("combat", msg)

            # Kampfstatus aktualisieren
            if self._combat_tracker and self._combat_tracker.active:
                status = self._combat_tracker.get_status_text()
                self._emit_game("combat_state", status)

                # Kampf vorbei?
                if self._combat_tracker.is_combat_over():
                    self._combat_tracker.end_combat()
                    end_msg = "[KAMPF ENDE] Alle Gegner besiegt!"
                    print(f"\n{end_msg}")
                    self._emit_game("combat", end_msg)
                    # Tracker vom AI-Backend entfernen
                    if self.engine.ai_backend:
                        self.engine.ai_backend.set_combat_tracker(None)

            # Ergebnis an KI schicken fuer narrative Reaktion (mit TTS)
            self._narrate_roll_result(
                f"Angriff ({weapon})", result, mechanics,
            )

        elif tag_type == "RETTUNGSWURF":
            category = data["category"]
            result = mechanics.saving_throw(
                target=data["target"],
            )
            msg = f"[RETTUNGSWURF] {category}: {result.description}"
            print(f"\n{msg}")
            self._emit_game("combat", msg)

            # Ergebnis an KI schicken fuer narrative Reaktion (mit TTS)
            self._narrate_roll_result(
                f"Rettungswurf ({category})", result, mechanics,
            )

    def _narrate_roll_result(
        self, skill_name: str, result: Any, mechanics: Any,
    ) -> None:
        """Schickt Wuerfelergebnis an KI und streamt die Narrative mit TTS."""
        if not self.engine.ai_backend:
            return

        print("[SPIELLEITER] ", end="", flush=True)
        self._emit_game("stream_start", "")

        narrative_chunks = self.engine.ai_backend.inject_roll_result(
            skill_name=skill_name,
            roll=result.roll,
            target=result.target,
            success_level=result.success_level,
            description=result.description,
        )

        # Voice: TTS fuer narrativen Text (Tags werden rausgefiltert)
        if self.engine._voice_enabled and hasattr(self.engine, "_voice_pipeline"):
            from audio.tag_filter import TagFilteredStream

            pipeline = self.engine._voice_pipeline

            def _raw():
                for chunk in narrative_chunks:
                    print(chunk, end="", flush=True)
                    if self._gui_mode:
                        self._emit_game("stream_chunk", chunk)
                    yield chunk

            filtered = TagFilteredStream(_raw())
            try:
                pipeline.speak_streaming(filtered)
            except Exception as exc:
                logger.warning("TTS Kampf-Narrative Fehler: %s", exc)

            narrative = filtered.full
        else:
            # Kein Voice — nur Text
            narrative = ""
            for chunk in narrative_chunks:
                print(chunk, end="", flush=True)
                narrative += chunk
                if self._gui_mode:
                    self._emit_game("stream_chunk", chunk)

        print()
        self._emit_game("stream_end", narrative)
        self._session_history.append({"role": "assistant", "content": narrative})

        # Narrative auf Tags scannen (HP_VERLUST etc.)
        self._scan_narrative_tags(narrative, mechanics)

    def _sort_by_initiative(
        self, combat_tags: list[tuple[str, dict]],
    ) -> list[tuple[str, dict]]:
        """
        Sortiert Kampf-Tags nach Initiative-Reihenfolge.

        Gewinnende Seite zuerst, innerhalb einer Seite nach Speed-Factor.
        RETTUNGSWURF-Tags bleiben in Originalreihenfolge am Ende.
        """
        ct = self._combat_tracker
        if not ct or not ct.active:
            return combat_tags

        attacks: list[tuple[str, dict]] = []
        others: list[tuple[str, dict]] = []

        for tag_type, data in combat_tags:
            if tag_type == "ANGRIFF":
                attacks.append((tag_type, data))
            else:
                others.append((tag_type, data))

        if not attacks:
            return combat_tags

        # Angriffe nach Seite + Speed sortieren
        player_attacks: list[tuple[tuple[str, dict], int]] = []
        monster_attacks: list[tuple[tuple[str, dict], int]] = []

        for tag in attacks:
            weapon = tag[1].get("weapon", "")
            thac0 = tag[1].get("thac0", 20)
            attacker = ct.get_attacker(thac0, weapon)
            speed = attacker.speed_factor if attacker else 5
            is_player = attacker.is_player if attacker else ct.is_player_side(thac0, weapon)
            if is_player:
                player_attacks.append((tag, speed))
            else:
                monster_attacks.append((tag, speed))

        player_attacks.sort(key=lambda x: x[1])
        monster_attacks.sort(key=lambda x: x[1])

        if ct.player_first:
            sorted_attacks = [t for t, _ in player_attacks] + [t for t, _ in monster_attacks]
        else:
            sorted_attacks = [t for t, _ in monster_attacks] + [t for t, _ in player_attacks]

        return sorted_attacks + others

    def _scan_narrative_tags(self, narrative: str, mechanics: Any) -> None:
        """Scannt die Narrative-Antwort nach inject_roll_result auf weitere Tags."""
        from core.character import (
            extract_stat_changes, extract_inventory_changes, extract_time_changes,
        )

        # Party-Tags haben Vorrang im Party-Modus
        party_state = getattr(self.engine, "party_state", None)
        if party_state:
            self._handle_party_tags(narrative, party_state, mechanics)
            # Zeit-Tags trotzdem verarbeiten
            time_changes = extract_time_changes(narrative)
            for tag_type, value in time_changes:
                self._handle_time(tag_type, value)
            return

        # Stat-Changes (aber HP_VERLUST im Kampf ueberspringen)
        stat_changes = extract_stat_changes(narrative)
        for stat_tuple in stat_changes:
            change_type = stat_tuple[0]
            if change_type == "HP_VERLUST" and self._combat_tracker and self._combat_tracker.active:
                continue  # Tracker verwaltet HP mechanisch
            self._handle_stat_change(change_type, stat_tuple[1] if len(stat_tuple) > 1 else "", mechanics, stat_tuple[2:] if len(stat_tuple) > 2 else ())

        # Inventar
        inventory_changes = extract_inventory_changes(narrative)
        for item_name, action in inventory_changes:
            self._handle_inventory(item_name, action)

        # Zeit
        time_changes = extract_time_changes(narrative)
        for tag_type, value in time_changes:
            self._handle_time(tag_type, value)

    # ------------------------------------------------------------------
    # Inventar-Verarbeitung
    # ------------------------------------------------------------------

    def _handle_inventory(self, item_name: str, action: str) -> None:
        """Verarbeitet INVENTAR-Tags: gefunden/gekauft → hinzufuegen, verloren/verkauft → entfernen."""
        character = self.engine.character
        if character is None:
            return

        if action in ("gefunden", "gekauft"):
            character.add_item(item_name)
            msg = f"[INVENTAR] +{item_name} ({action})"
        elif action in ("verloren", "verkauft"):
            removed = character.remove_item(item_name)
            if removed:
                msg = f"[INVENTAR] -{item_name} ({action})"
            else:
                msg = f"[INVENTAR] '{item_name}' nicht im Inventar — ignoriert."
        else:
            msg = f"[INVENTAR] Unbekannte Aktion: {action}"

        print(f"\n{msg}")
        self._emit_game("inventory", msg)

    # ------------------------------------------------------------------
    # Zeit/Wetter-Verarbeitung
    # ------------------------------------------------------------------

    def _handle_time(self, tag_type: str, value: Any) -> None:
        """Verarbeitet ZEIT_VERGEHT, TAGESZEIT und WETTER Tags."""
        if not hasattr(self, "_time_tracker") or self._time_tracker is None:
            return

        if tag_type == "ZEIT_VERGEHT":
            hours = float(value)
            self._time_tracker.advance(hours)
            msg = f"[ZEIT] {hours}h vergangen -> {self._time_tracker.get_context_for_prompt()}"
        elif tag_type == "TAGESZEIT":
            h, m = value
            self._time_tracker.set_time(h, m)
            msg = f"[ZEIT] Uhrzeit gesetzt: {h:02d}:{m:02d} ({self._time_tracker.get_time_of_day()})"
        elif tag_type == "WETTER":
            self._time_tracker.set_weather(value)
            msg = f"[WETTER] {value}"
        elif tag_type == "RUNDE":
            rounds = int(value)
            self._time_tracker.advance_rounds(rounds)
            msg = f"[RUNDE] +{rounds} Kampfrunde(n) -> {self._time_tracker.get_context_for_prompt()}"
        else:
            return

        print(f"\n{msg}")
        self._emit_game("time", msg)

    # ------------------------------------------------------------------
    # Party-Tag-Verarbeitung (Multi-Charakter-Modus)
    # ------------------------------------------------------------------

    def _handle_party_tags(
        self,
        gm_response: str,
        party_state: Any,
        mechanics: Any,
    ) -> None:
        """Verarbeitet Party-spezifische Tags aus der KI-Antwort."""
        from core.character import extract_party_stat_changes
        from core.event_bus import EventBus
        bus = EventBus.get()

        party_tags = extract_party_stat_changes(gm_response)
        self._last_party_tag_count = len(party_tags) if party_tags else 0
        if not party_tags:
            return

        for tag in party_tags:
            tag_type = tag[0]

            if tag_type == "HP_VERLUST" and len(tag) >= 3:
                char_name, amount_str = tag[1], tag[2]
                try:
                    amount = int(amount_str)
                except ValueError:
                    continue
                msg = party_state.apply_damage(char_name, amount)
                print(f"\n{msg}")
                self._emit_game("stat", msg)
                bus.emit("party", "state_updated", {
                    "action": "damage",
                    "character": char_name,
                    "amount": amount,
                })
                # Mitglied-Tod pruefen
                member = party_state.get_member(char_name)
                if member and not member.alive:
                    death_msg = f"{member.name} ist gefallen!"
                    print(f"[SYSTEM] {death_msg}")
                    self._emit_game("system", death_msg)
                    bus.emit("party", "member_died", {
                        "name": member.name,
                        "message": death_msg,
                    })

            elif tag_type == "HP_HEILUNG" and len(tag) >= 3:
                char_name, amount_str = tag[1], tag[2]
                try:
                    amount = mechanics.roll_expression(amount_str)
                except (ValueError, AttributeError):
                    try:
                        amount = int(amount_str)
                    except ValueError:
                        continue
                msg = party_state.apply_healing(char_name, amount)
                print(f"\n{msg}")
                self._emit_game("stat", msg)
                bus.emit("party", "state_updated", {
                    "action": "healing",
                    "character": char_name,
                    "amount": amount,
                })

            elif tag_type == "ZAUBER_VERBRAUCHT" and len(tag) >= 4:
                char_name, spell_name, level_str = tag[1], tag[2], tag[3]
                try:
                    level = int(level_str)
                except ValueError:
                    continue
                msg = party_state.use_spell(char_name, spell_name, level)
                print(f"\n{msg}")
                self._emit_game("stat", msg)
                bus.emit("party", "state_updated", {
                    "action": "spell_used",
                    "character": char_name,
                    "spell": spell_name,
                    "level": level,
                })

            elif tag_type == "FERTIGKEIT_GENUTZT" and len(tag) >= 3:
                # Nicht relevant fuer AD&D 2e (kein Skill-Improvement durch Nutzung)
                continue

            elif tag_type == "GEGENSTAND_BENUTZT" and len(tag) >= 3:
                item_name, char_name = tag[1], tag[2]
                result = party_state.use_item(char_name, item_name)
                msg = result["message"]
                print(f"\n{msg}")
                self._emit_game("inventory", msg)
                # Automatische Heilung bei Heal-Effekt
                effect = result.get("effect")
                if effect and effect.get("type") == "heal" and mechanics:
                    heal_amount = mechanics.roll_expression(effect["amount"])
                    heal_msg = party_state.apply_healing(char_name, heal_amount)
                    print(f"\n{heal_msg}")
                    self._emit_game("stat", heal_msg)
                bus.emit("party", "state_updated", {
                    "action": "item_used",
                    "character": char_name,
                    "item": item_name,
                })

            elif tag_type == "INVENTAR" and len(tag) >= 4:
                item_name, action, char_name = tag[1], tag[2], tag[3]
                if action in ("gefunden", "gekauft"):
                    party_state.add_item(char_name, item_name)
                    msg = f"[INVENTAR] +{item_name} ({action}) -> {char_name}"
                elif action in ("verloren", "verkauft"):
                    party_state.remove_item(char_name, item_name)
                    msg = f"[INVENTAR] -{item_name} ({action}) -> {char_name}"
                else:
                    msg = f"[INVENTAR] Unbekannte Aktion: {action}"
                print(f"\n{msg}")
                self._emit_game("inventory", msg)
                bus.emit("party", "state_updated", {
                    "action": "inventory",
                    "character": char_name,
                    "item": item_name,
                })

            # ── Monster-Mechanik-Tags (Session 19) — Party-Modus ──────────

            elif tag_type == "MAGIC_RESISTANCE" and len(tag) >= 3:
                monster_name, prozent_str = tag[1], tag[2]
                try:
                    prozent = int(prozent_str)
                except ValueError:
                    prozent = 0
                wurf = random.randint(1, 100)
                if wurf <= prozent:
                    msg = f"[MAGIC_RESISTANCE] Magieresistenz von {monster_name}: {wurf}% — Zauber scheitert! (Resistenz: {prozent}%)"
                else:
                    msg = f"[MAGIC_RESISTANCE] Magieresistenz von {monster_name}: {wurf}% — Zauber durchdringt! (Resistenz: {prozent}%)"
                print(f"\n{msg}")
                self._emit_game("combat", msg)

            elif tag_type == "WAFFEN_IMMUNITAET" and len(tag) >= 3:
                monster_name, bonus = tag[1], tag[2]
                msg = f"[WARNUNG] {monster_name} kann nur von Waffen mit +{bonus} oder besser getroffen werden!"
                print(f"\n{msg}")
                self._emit_game("combat", msg)

            elif tag_type == "GIFT" and len(tag) >= 4:
                monster_name, gift_typ_raw, save_mod_str = tag[1], tag[2], tag[3]
                gift_typ = gift_typ_raw.strip().lower()
                try:
                    save_mod = int(save_mod_str)
                except ValueError:
                    save_mod = 0
                try:
                    # Standardwert fuer Rettungswurf vs. Gift/Paralyse/Tod (AD&D 2e Tabelle 60)
                    save_result = mechanics.saving_throw(
                        target=16,
                        modifiers=save_mod,
                    )
                    save_success = save_result.is_success
                except Exception:
                    roll = random.randint(1, 20)
                    save_success = (roll + save_mod) >= 16
                if not save_success:
                    if gift_typ in ("tod", "toedlich", "death"):
                        msg = f"[GIFT] Toedliches Gift von {monster_name}! Rettungswurf MISSLUNGEN — lebensgefaehrlich!"
                    elif gift_typ in ("paralyse", "paralysis"):
                        msg = f"[GIFT] Gift von {monster_name}! Rettungswurf MISSLUNGEN — Paralyse fuer 1d6 Runden!"
                    elif gift_typ in ("krankheit", "disease"):
                        msg = f"[GIFT] Krankheit von {monster_name}! Rettungswurf MISSLUNGEN — Krankheit kontrahiert!"
                    else:
                        msg = f"[GIFT] Gift von {monster_name}! Rettungswurf MISSLUNGEN — zusaetzlicher Giftschaden!"
                else:
                    msg = f"[GIFT] Gift von {monster_name}! Rettungswurf GELUNGEN — kein Effekt!"
                print(f"\n{msg}")
                self._emit_game("combat", msg)

            elif tag_type == "LEVEL_DRAIN" and len(tag) >= 3:
                char_name, stufen_str = tag[1], tag[2]
                try:
                    stufen = int(stufen_str)
                except ValueError:
                    stufen = 1
                member = party_state.get_member(char_name)
                if member:
                    hp_loss = sum(random.randint(1, 8) for _ in range(stufen))
                    msg_hp = party_state.apply_damage(char_name, hp_loss)
                    msg = (
                        f"[LEVEL_DRAIN] {char_name} verliert {stufen} Erfahrungsstufe(n)! "
                        f"| {msg_hp}"
                    )
                else:
                    msg = f"[LEVEL_DRAIN] {char_name} verliert {stufen} Erfahrungsstufe(n)! (Charakter nicht in Party)"
                print(f"\n{msg}")
                self._emit_game("stat", msg)
                bus.emit("party", "state_updated", {
                    "action": "level_drain",
                    "character": char_name,
                    "levels": stufen,
                })

            elif tag_type == "MORAL_CHECK" and len(tag) >= 3:
                monster_name, schwelle_str = tag[1], tag[2]
                try:
                    schwelle = int(schwelle_str)
                except ValueError:
                    schwelle = 7
                wurf = random.randint(1, 6) + random.randint(1, 6)
                if wurf > schwelle:
                    msg = f"[MORAL] {monster_name}: Moral-Check 2d6={wurf} > {schwelle} — Monster FLIEHT!"
                else:
                    msg = f"[MORAL] {monster_name}: Moral-Check 2d6={wurf} <= {schwelle} — Monster kaempft weiter!"
                print(f"\n{msg}")
                self._emit_game("combat", msg)

            elif tag_type == "REGENERATION" and len(tag) >= 3:
                monster_name, hp_str = tag[1], tag[2]
                try:
                    hp_per_round = int(hp_str)
                except ValueError:
                    hp_per_round = 1
                if self._combat_tracker and self._combat_tracker.active:
                    self._combat_tracker.register_regeneration(monster_name, hp_per_round)
                msg = f"[REGENERATION] {monster_name} regeneriert {hp_per_round} HP pro Runde."
                print(f"\n{msg}")
                self._emit_game("combat", msg)

            elif tag_type == "FURCHT" and len(tag) >= 4:
                char_name, effekt_raw, dauer = tag[1], tag[2], tag[3]
                effekt = effekt_raw.strip().lower()
                if effekt in ("flucht", "flee", "flieht"):
                    msg = f"[FURCHT] {char_name} ergreift die Flucht! Dauer: {dauer} Runden"
                elif effekt in ("paralyse", "gelähmt", "gelaehmt", "paralysis"):
                    msg = f"[FURCHT] {char_name} ist vor Furcht gelaehmt! Dauer: {dauer} Runden"
                elif effekt in ("alterung", "aging", "altert"):
                    msg = f"[FURCHT] {char_name} altert schlagartig! (Uebernatuerliche Furcht)"
                else:
                    msg = f"[FURCHT] {char_name}: {effekt_raw}. Dauer: {dauer} Runden"
                print(f"\n{msg}")
                self._emit_game("combat", msg)

            elif tag_type == "ATEM_WAFFE" and len(tag) >= 4:
                monster_name, atem_typ, schaden_str = tag[1], tag[2], tag[3]
                try:
                    total = mechanics.roll_expression(schaden_str.strip())
                except Exception:
                    total = random.randint(1, 10)
                msg = (
                    f"[ATEM_WAFFE] {monster_name} setzt {atem_typ}-Atem ein! "
                    f"Voller Schaden: {total}. Rettungswurf gegen Atemwaffe = "
                    f"halber Schaden ({total // 2})."
                )
                print(f"\n{msg}")
                self._emit_game("combat", msg)

        # XP aus Standard-Tags (teilen unter lebenden Mitgliedern)
        from core.character import extract_stat_changes
        for stat_tuple in extract_stat_changes(gm_response):
            change_type = stat_tuple[0]
            value_str = stat_tuple[1] if len(stat_tuple) > 1 else ""
            if change_type == "XP_GEWINN":
                try:
                    amount = int(value_str)
                except ValueError:
                    continue
                party_state.add_xp(amount)
                alive = len(party_state.alive_members())
                share = amount // alive if alive else 0
                msg = (
                    f"[XP] +{amount} Erfahrungspunkte "
                    f"(je ~{share} fuer {alive} Mitglieder)"
                )
                print(f"\n{msg}")
                self._emit_game("stat", msg)
                bus.emit("party", "state_updated", {
                    "action": "xp_gain",
                    "amount": amount,
                })

    # ------------------------------------------------------------------
    # DMG-Mechanik-Tags (Session 20)
    # ------------------------------------------------------------------

    # Regulaere Ausdruecke fuer alle 7 neuen DMG-Tags
    _RE_DMG_MORAL_CHECK    = re.compile(r"\[MORAL_CHECK:\s*([^|]+)\|\s*(\d+)\]")
    _RE_DMG_REAKTION       = re.compile(r"\[REAKTION:\s*([^|]+)\|\s*([+-]?\d+)\]")
    _RE_DMG_SCHATZ         = re.compile(r"\[SCHATZ:\s*([A-Za-z])\]")
    _RE_DMG_UNTOTE         = re.compile(r"\[UNTOTE_VERTREIBEN:\s*(\d+)\s*\|\s*(\d+(?:\.\d+)?)\]")
    _RE_DMG_BELASTUNG      = re.compile(r"\[BELASTUNG:\s*([^|]+)\|\s*(\d+(?:\.\d+)?)\]")
    _RE_DMG_BEGEGNUNG      = re.compile(r"\[BEGEGNUNG:\s*([^|\]]+?)(?:\s*\|\s*(\d+))?\s*\]")
    _RE_DMG_GIFT           = re.compile(r"\[GIFT:\s*([^|]+)\|\s*([^|]+)\|\s*([+-]?\d+)\]")

    def _handle_dmg_tags(self, response_text: str, mechanics: Any) -> None:
        """
        Verarbeitet DMG-Mechanik-Tags aus der KI-Antwort.

        Unterstuetzte Tags:
          [MORAL_CHECK: Name | MoralWert]      — Moral-Probe (2d6 vs Schwelle)
          [REAKTION: NPCName | CHA-Mod]        — NPC-Reaktionswurf (2d6 + CHA-Mod)
          [SCHATZ: Typ]                         — Schatz wuerfeln (Typ A-Z)
          [UNTOTE_VERTREIBEN: Level | HD]       — Kleriker vertreibt Untote
          [BELASTUNG: Name | Gewicht]           — Tragekapazitaet pruefen
          [BEGEGNUNG: LocationTyp | Chance%]    — Wandering-Monster-Probe
          [GIFT: Name | Typ | Save-Mod]         — Rettungswurf gegen Gift
        """
        from core.event_bus import EventBus
        bus = EventBus.get()

        # ── [MORAL_CHECK: Name | MoralWert] ───────────────────────────────
        for m in self._RE_DMG_MORAL_CHECK.finditer(response_text):
            monster_name = m.group(1).strip()
            morale_value_str = m.group(2).strip()
            try:
                morale_value = int(morale_value_str)
                result = mechanics.morale_check(morale_value)
                msg = f"[MORAL_CHECK] {monster_name}: {result.description}"
                print(f"\n{msg}")
                self._emit_game("combat", msg)
                bus.emit("game", "morale_check", {
                    "monster": monster_name,
                    "morale_value": morale_value,
                    "roll": result.roll,
                    "success": result.is_success,
                    "description": result.description,
                })
                logger.info("MORAL_CHECK: %s Moral=%d Wurf=%d -> %s",
                            monster_name, morale_value, result.roll,
                            "bleibt" if result.is_success else "flieht")
            except Exception as exc:
                logger.warning("MORAL_CHECK Fehler fuer '%s': %s", monster_name, exc)

        # ── [REAKTION: NPCName | CHA-Mod] ────────────────────────────────
        for m in self._RE_DMG_REAKTION.finditer(response_text):
            npc_name = m.group(1).strip()
            cha_mod_str = m.group(2).strip()
            try:
                cha_mod = int(cha_mod_str)
                result = mechanics.reaction_roll(cha_mod)
                msg = (
                    f"[REAKTION] {npc_name}: {result['description']}"
                )
                print(f"\n{msg}")
                self._emit_game("combat", msg)
                bus.emit("game", "reaction_roll", {
                    "npc": npc_name,
                    "cha_modifier": cha_mod,
                    "roll": result["roll"],
                    "modified_roll": result["modified_roll"],
                    "reaction_level": result["reaction_level"],
                    "description": result["description"],
                })
                logger.info("REAKTION: %s CHA-Mod=%d Ergebnis=%s",
                            npc_name, cha_mod, result["reaction_level"])
            except Exception as exc:
                logger.warning("REAKTION Fehler fuer '%s': %s", npc_name, exc)

        # ── [SCHATZ: Typ] ─────────────────────────────────────────────────
        for m in self._RE_DMG_SCHATZ.finditer(response_text):
            treasure_type = m.group(1).strip().upper()
            try:
                result = mechanics.roll_treasure(treasure_type)
                msg = f"[SCHATZ] {result['description']}"
                print(f"\n{msg}")
                self._emit_game("inventory", msg)

                # ── Muenzen ins Inventar ──────────────────────────────
                for coin_type, amount in result["coins"].items():
                    if amount > 0:
                        coin_names = {"cp": "Kupfermuenzen", "sp": "Silbermuenzen",
                                      "ep": "Elektrummuenzen", "gp": "Goldmuenzen",
                                      "pp": "Platinmuenzen"}
                        coin_item = f"{amount} {coin_names.get(coin_type, coin_type)}"
                        self._handle_inventory(coin_item, "gefunden")

                # ── Edelsteine ins Inventar ────────────────────────────
                for gem in result.get("gem_details", []):
                    gem_item = f"{gem['name']} ({gem['actual_value']} GP)"
                    self._handle_inventory(gem_item, "gefunden")

                # ── Kunstgegenstaende ins Inventar ─────────────────────
                for art in result.get("jewelry_details", []):
                    self._handle_inventory(art["description"], "gefunden")

                # ── Magische Gegenstaende ins Inventar ─────────────────
                for magic in result.get("magic_item_details", []):
                    self._handle_inventory(magic["name"], "gefunden")

                bus.emit("game", "treasure_found", {
                    "treasure_type": treasure_type,
                    "coins": result["coins"],
                    "gems": result["gems"],
                    "jewelry": result["jewelry"],
                    "magic_items": result["magic_items"],
                    "gem_details": result.get("gem_details", []),
                    "jewelry_details": result.get("jewelry_details", []),
                    "magic_item_details": result.get("magic_item_details", []),
                    "total_gp_value": result["total_gp_value"],
                    "description": result["description"],
                })
                logger.info("SCHATZ Typ %s: ~%d GP Wert", treasure_type, result["total_gp_value"])
            except Exception as exc:
                logger.warning("SCHATZ Fehler fuer Typ '%s': %s", treasure_type, exc)

        # ── [UNTOTE_VERTREIBEN: Level | HD] ──────────────────────────────
        for m in self._RE_DMG_UNTOTE.finditer(response_text):
            level_str = m.group(1).strip()
            hd_str    = m.group(2).strip()
            try:
                cleric_level = int(level_str)
                undead_hd    = float(hd_str)
                result = mechanics.turn_undead(cleric_level, undead_hd)
                msg = f"[UNTOTE_VERTREIBEN] {result['description']}"
                print(f"\n{msg}")
                self._emit_game("combat", msg)
                bus.emit("game", "turn_undead", {
                    "cleric_level": cleric_level,
                    "undead_hd": undead_hd,
                    "success": result["success"],
                    "result_type": result["result_type"],
                    "roll": result.get("roll"),
                    "target": result.get("target"),
                    "description": result["description"],
                })
                logger.info("UNTOTE_VERTREIBEN: Kleriker L%d vs HD%.1f -> %s",
                            cleric_level, undead_hd, result["result_type"])
            except Exception as exc:
                logger.warning("UNTOTE_VERTREIBEN Fehler: %s", exc)

        # ── [BELASTUNG: Name | Gewicht] ───────────────────────────────────
        for m in self._RE_DMG_BELASTUNG.finditer(response_text):
            char_name  = m.group(1).strip()
            weight_str = m.group(2).strip()
            try:
                total_weight = float(weight_str)
                # STR-Wert aus Charakter oder Party-State bestimmen
                str_score = 10  # Fallback-Wert
                party_state = getattr(self.engine, "party_state", None)
                if party_state:
                    member = party_state.get_member(char_name)
                    if member:
                        str_score = member.stats.get("Staerke", member.stats.get("STR", 10))
                elif self.engine.character:
                    char = self.engine.character
                    str_score = char._stats.get("Staerke", char._stats.get("STR", 10))
                # Gewicht als Gesamt-Nutzlast uebergeben (ein Pseudo-Item-Eintrag)
                result = mechanics.calculate_encumbrance(
                    [("Gesamtausruestung", total_weight)],
                    int(str_score),
                )
                msg = f"[BELASTUNG] {char_name}: {result['description']}"
                print(f"\n{msg}")
                self._emit_game("stat", msg)
                bus.emit("game", "encumbrance_update", {
                    "character": char_name,
                    "total_weight": result["total_weight"],
                    "max_allowance": result["max_allowance"],
                    "category": result["category"],
                    "movement_factor": result["movement_factor"],
                    "description": result["description"],
                })
                logger.info("BELASTUNG: %s %.1f Pfund (STR %d) -> %s",
                            char_name, total_weight, int(str_score), result["category"])
            except Exception as exc:
                logger.warning("BELASTUNG Fehler fuer '%s': %s", char_name, exc)

        # ── [BEGEGNUNG: LocationTyp | Chance%] ───────────────────────────
        # Akzeptiert auch [BEGEGNUNG: Wandering] ohne Prozent-Angabe (Default 17%)
        for m in self._RE_DMG_BEGEGNUNG.finditer(response_text):
            location_type = m.group(1).strip()
            chance_raw    = m.group(2)   # None wenn Pipe-Teil fehlt
            try:
                chance = int(chance_raw.strip()) if chance_raw else 17
                result = mechanics.roll_encounter_check(chance)
                status = "BEGEGNUNG" if result["occurred"] else "Keine Begegnung"
                msg = f"[BEGEGNUNG] {location_type}: {result['description']}"
                print(f"\n{msg}")
                self._emit_game("combat" if result["occurred"] else "system", msg)
                bus.emit("game", "encounter_check", {
                    "location_type": location_type,
                    "chance": chance,
                    "roll": result["roll"],
                    "occurred": result["occurred"],
                    "description": result["description"],
                })
                logger.info("BEGEGNUNG %s: d100=%d Schwelle=%d -> %s",
                            location_type, result["roll"], chance, status)
            except Exception as exc:
                logger.warning("BEGEGNUNG Fehler fuer '%s': %s", location_type, exc)

        # ── [GIFT: Name | Typ | Save-Mod] ────────────────────────────────
        # Hinweis: GIFT wird AUCH als Monster-Mechanik-Tag (Session 19) verarbeitet.
        # Dieser Handler verarbeitet die neue zweiparametrige Form aus DMG-Mechaniken:
        # [GIFT: CharName | Typ | Save-Mod] — explizit mit 3 Parametern.
        for m in self._RE_DMG_GIFT.finditer(response_text):
            char_name   = m.group(1).strip()
            gift_typ    = m.group(2).strip().lower()
            save_mod_str = m.group(3).strip()
            try:
                save_mod = int(save_mod_str)
                # Standard-Rettungswurf vs. Gift (Save-Typ 0: Para/Poison/Tod)
                # Zielwert 14 = Krieger Level 1 (PHB Table 60), moderat fuer Anfaenger
                save_result = mechanics.saving_throw(target=14, modifiers=save_mod)
                if not save_result.is_success:
                    if gift_typ in ("tod", "toedlich", "death", "deadly"):
                        effekt_msg = "lebensgefaehrlich!"
                    elif gift_typ in ("paralyse", "paralysis", "laehmt"):
                        effekt_msg = "Paralyse fuer 1d6 Runden!"
                    elif gift_typ in ("krankheit", "disease", "seuche"):
                        effekt_msg = "Krankheit kontrahiert!"
                    elif gift_typ in ("schaden", "damage"):
                        effekt_msg = "Giftschaden erleidet!"
                    else:
                        effekt_msg = f"Effekt: {gift_typ}!"
                    msg = (
                        f"[GIFT] {char_name} — Typ: {gift_typ} | "
                        f"Rettungswurf MISSLUNGEN ({save_result.description}) — {effekt_msg}"
                    )
                else:
                    msg = (
                        f"[GIFT] {char_name} — Typ: {gift_typ} | "
                        f"Rettungswurf GELUNGEN ({save_result.description}) — kein Effekt!"
                    )
                print(f"\n{msg}")
                self._emit_game("combat", msg)
                bus.emit("game", "poison_save", {
                    "character": char_name,
                    "poison_type": gift_typ,
                    "save_modifier": save_mod,
                    "roll": save_result.roll,
                    "target": save_result.target,
                    "success": save_result.is_success,
                    "description": save_result.description,
                })
                logger.info("GIFT: %s Typ=%s Save-Mod=%d Wurf=%d -> %s",
                            char_name, gift_typ, save_mod, save_result.roll,
                            "gerettet" if save_result.is_success else "MISSLUNGEN")
            except Exception as exc:
                logger.warning("GIFT Fehler fuer '%s': %s", char_name, exc)

    def _handle_party_save(self, turn: int) -> None:
        """Speichert den Party-State nach jedem Zug."""
        party_state = getattr(self.engine, "party_state", None)
        if not party_state:
            return
        save_dir = Path(__file__).parent.parent / "data" / "party_saves"
        module = self.engine.module_name
        save_path = save_dir / f"party_state_{module}.json"
        party_state.save_state(str(save_path), turn)

    def _update_chronicle(self, turn_number: int) -> None:
        """
        Laesst die KI die letzten SUMMARY_INTERVAL Turns zusammenfassen
        und speichert die Chronik im Archivist.
        """
        if not self._archivist or not self.engine.ai_backend:
            return

        msg_start = f"[CHRONIK] Erstelle Zusammenfassung nach Runde {turn_number}..."
        print(f"\n{msg_start}")
        self._emit_game("system", msg_start)
        turns = self._archivist.get_recent_turns(15)

        if not turns:
            return

        summary = self.engine.ai_backend.summarize(turns)
        if summary:
            self._archivist.update_chronicle(summary)
            msg_done = f"[CHRONIK] Zusammenfassung gespeichert ({len(summary)} Zeichen)."
            print(f"{msg_done}\n")
            self._emit_game("system", msg_done)
        else:
            logger.warning("Chronik-Zusammenfassung war leer — uebersprungen.")

    # ------------------------------------------------------------------
    # I/O-Helfer (abstrahiert für spätere Voice-Integration in Task 03)
    # ------------------------------------------------------------------

    def _get_input(self) -> str | None:
        """
        Liest Spieler-Eingabe.

        GUI-Modus: Queue (blockierend bis Input kommt).
                   Voice wird dynamisch erkannt — auch wenn erst
                   nach Beginn des Wartens aktiviert.
        Voice:     STT-Handler (blockierend).
        Text:      stdin.
        """
        from core.event_bus import EventBus
        bus = EventBus.get()

        if self._gui_mode:
            bus.emit("game", "waiting_for_input", {})
            import threading

            result_holder: list[str | None] = [None]
            got_input = threading.Event()
            stt_running = threading.Event()

            def _stt_loop():
                """STT-Thread: lauscht wiederholt bis Input vorliegt."""
                stt_running.set()
                bus.emit("game", "output", {"tag": "system",
                         "text": "[Mikrofon aktiv — sprich jetzt]"})
                while not got_input.is_set():
                    try:
                        text = self.engine._stt.listen()
                        if text and not got_input.is_set():
                            result_holder[0] = text
                            got_input.set()
                            return
                    except Exception as exc:
                        logger.warning("STT-Fehler: %s", exc)
                        break

            stt_thread: threading.Thread | None = None

            # Voice schon aktiv? -> STT sofort starten
            if self.engine._voice_enabled and hasattr(self.engine, "_stt"):
                stt_thread = threading.Thread(
                    target=_stt_loop, daemon=True, name="ars-stt-gui",
                )
                stt_thread.start()

            # Unified Loop: Queue + dynamische Voice-Erkennung
            while self._active and not got_input.is_set():
                # Queue pruefen (Text-Eingabe)
                try:
                    text = self._input_queue.get(timeout=0.15)
                    got_input.set()
                    return text
                except queue.Empty:
                    pass

                # Voice mid-wait aktiviert? -> STT-Thread nachrüsten
                if (not stt_running.is_set()
                        and self.engine._voice_enabled
                        and hasattr(self.engine, "_stt")):
                    stt_thread = threading.Thread(
                        target=_stt_loop, daemon=True, name="ars-stt-gui",
                    )
                    stt_thread.start()

            return result_holder[0]

        # Klassischer Modus (CLI)
        if self.engine._voice_enabled and hasattr(self.engine, "_stt"):
            try:
                return self.engine._stt.listen()
            except Exception as exc:
                logger.warning("STT-Fehler, Fallback auf stdin: %s", exc)

        try:
            return input("[SPIELER] > ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

    def _emit_game(self, tag: str, text: str) -> None:
        """Emittiert Text-Output ueber EventBus fuer den Game-Tab."""
        from core.event_bus import EventBus
        EventBus.get().emit("game", "output", {"tag": tag, "text": text})

    def _gm_print(self, text: str) -> None:
        """Gibt GM-Text (Adventure-Intro) aus und spricht ihn ggf. vor."""
        print(f"[SPIELLEITER] {text}\n")
        self._emit_game("keeper", text)
        if self.engine._voice_enabled and hasattr(self.engine, "_tts"):
            try:
                self.engine._tts.speak(text)
            except Exception as exc:
                logger.warning("TTS-Fehler: %s", exc)

    def _stream_gm_response(self, user_input: str) -> str:
        """
        Streamt die KI-Antwort auf stdout und — bei Voice — an TTS.

        Ausgabe-Kanaele:
          Voice-Modus: VoicePipeline.speak_streaming() + stdout
          Text-Modus:  nur stdout
        """
        if not self.engine.ai_backend:
            fallback = (
                "[KI-Backend nicht initialisiert] "
                "Stelle sicher dass GEMINI_API_KEY in der .env gesetzt ist."
            )
            print(fallback, end="")
            return fallback

        # Text sammeln fuer History + Proben-Extraktion
        collected: list[str] = []

        if self.engine._voice_enabled and hasattr(self.engine, "_voice_pipeline"):
            # ── Voice-Modus: LLM-Stream → TagFilteredStream → TTS ──
            from audio.tag_filter import TagFilteredStream
            pipeline = self.engine._voice_pipeline
            tts = self.engine._tts

            def _voice_switch(role: str) -> None:
                """Callback fuer [STIMME:xxx] Tags — wechselt TTS-Stimme."""
                tts.set_voice(role)

            def _raw_stream():
                """Yieldet rohe LLM-Chunks (inkl. Tags) fuer stdout."""
                for chunk in self.engine.ai_backend.chat_stream(user_input):
                    print(chunk, end="", flush=True)
                    if self._gui_mode:
                        self._emit_game("stream_chunk", chunk)
                    yield chunk

            filtered = TagFilteredStream(_raw_stream(), voice_callback=_voice_switch)

            try:
                pipeline.speak_streaming(filtered)
            except Exception as exc:
                logger.warning("speak_streaming Fehler: %s", exc)

            # Vollen Text (inkl. Tags) fuer History/Proben-Extraktion sammeln
            collected.append(filtered.full)

        else:
            # ── Text-Modus: nur stdout ─────────────────────────────────────────
            for chunk in self.engine.ai_backend.chat_stream(user_input):
                print(chunk, end="", flush=True)
                collected.append(chunk)
                if self._gui_mode:
                    self._emit_game("stream_chunk", chunk)

        return "".join(collected)
