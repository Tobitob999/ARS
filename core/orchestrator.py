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
import time as _time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.engine import SimulatorEngine

logger = logging.getLogger("ARS.orchestrator")


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
    # Interner Game-Loop
    # ------------------------------------------------------------------

    def _game_loop(self) -> None:
        from core.mechanics import MechanicsEngine
        from core.ai_backend import extract_probes
        from core.character import extract_stat_changes, extract_inventory_changes, extract_time_changes, extract_combat_tags
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

            # ── Neue Kampfrunde starten (vor AI-Aufruf) ─────────────
            if self._combat_tracker and self._combat_tracker.active:
                round_info = self._combat_tracker.start_new_round(mechanics)
                print(f"\n{round_info['detail']}")
                self._emit_game("initiative", round_info["detail"])

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
            combat_tags = extract_combat_tags(gm_response)
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
            for change_type, value_str in stat_changes:
                self._handle_stat_change(change_type, value_str, mechanics)

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
                "stat_changes": len(stat_changes),
                "inventory_changes": len(inventory_changes),
                "time_changes": len(time_changes),
                "facts": len(facts_list),
                "rules_warnings": _rules_warning_count,
            })

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
    ) -> None:
        """
        Verarbeitet HP_VERLUST, STABILITAET_VERLUST und FERTIGKEIT_GENUTZT Tags.
        Alle Aenderungen werden sofort in die SQLite-DB geschrieben.
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
            amount = mechanics.roll_expression(value_str)
            result = character.update_stat("SAN", -amount)
            if "error" not in result:
                msg = (
                    f"[SAN-VERLUST] -{amount} "
                    f"(Wurf: {value_str}) | "
                    f"SAN: {result['old_value']} -> {result['new_value']}"
                    f"/{result['max_value']}"
                )
                print(f"\n{msg}")
                self._emit_game("stat", msg)
                if character.is_insane:
                    insane_msg = f"Der {self.engine.pc_title} verliert den Verstand!"
                    print(f"[SYSTEM] {insane_msg}")
                    self._emit_game("system", insane_msg)

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
            character.mark_skill_used(value_str)
            msg = f"[FERTIGKEIT] '{value_str}' fuer Steigerungsphase markiert."
            print(f"\n{msg}")
            self._emit_game("stat", msg)

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
                        "speed_factor": 5, "attacks_per_round": "1/1"}
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
            # Speed-Factor + Attacks-per-Round
            player_stats["speed_factor"] = mech.lookup_speed_factor(
                player_stats["weapon"],
            )
            player_stats["attacks_per_round"] = mech.lookup_attacks_per_round(
                cg, player_stats["level"],
            )

        self._combat_tracker = CombatTracker()
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
        # Stat-Changes (aber HP_VERLUST im Kampf ueberspringen)
        stat_changes = extract_stat_changes(narrative)
        for change_type, value_str in stat_changes:
            if change_type == "HP_VERLUST" and self._combat_tracker and self._combat_tracker.active:
                continue  # Tracker verwaltet HP mechanisch
            self._handle_stat_change(change_type, value_str, mechanics)

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
        else:
            return

        print(f"\n{msg}")
        self._emit_game("time", msg)

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
