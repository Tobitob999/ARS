"""
core/orchestrator.py — Session-Orchestrator

Verantwortlich für:
  - Verwaltung des Spielzustands (aktive Szene, Charaktere, Inventar)
  - Koordination zwischen Engine, Mechanics und KI-Backend
  - Haupt-Game-Loop (Eingabe → KI-Antwort → Probe → Würfelergebnis → Loop)
"""

from __future__ import annotations

import logging
import queue
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
        # GUI-Modus: Input kommt aus Queue statt stdin
        self._gui_mode = False
        self._input_queue: queue.Queue[str | None] = queue.Queue()
        self._turn_number: int = 0

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

    # ------------------------------------------------------------------
    # Interner Game-Loop
    # ------------------------------------------------------------------

    def _game_loop(self) -> None:
        from core.mechanics import MechanicsEngine
        from core.ai_backend import extract_probes
        from core.character import extract_stat_changes
        from core.memory import extract_facts

        mechanics = MechanicsEngine(dice_config=self.engine.dice_config)
        turn_number = 0

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

            # ── KI-Antwort streamen ────────────────────────────────────
            self._session_history.append({"role": "user", "content": user_input})
            self._emit_game("player", user_input)

            print("[SPIELLEITER] ", end="", flush=True)
            self._emit_game("stream_start", "")
            gm_response = self._stream_gm_response(user_input)
            print()  # Zeilenumbruch nach Stream-Ende
            self._emit_game("stream_end", gm_response)

            self._session_history.append({"role": "assistant", "content": gm_response})

            # ── Proben-Marker verarbeiten ──────────────────────────────
            probes = extract_probes(gm_response)
            for skill_name, target_value in probes:
                self._handle_probe(skill_name, target_value, mechanics)

            # ── Zustandsaenderungs-Tags verarbeiten ────────────────────
            stat_changes = extract_stat_changes(gm_response)
            for change_type, value_str in stat_changes:
                self._handle_stat_change(change_type, value_str, mechanics)

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

        # Ergebnis an KI schicken — GM antwortet narrativ
        if self.engine.ai_backend:
            print("[SPIELLEITER] ", end="", flush=True)
            self._emit_game("stream_start", "")
            narrative_chunks = self.engine.ai_backend.inject_roll_result(
                skill_name=skill_name,
                roll=result.roll,
                target=result.target,
                success_level=result.success_level,
                description=result.description,
            )
            narrative = ""
            for chunk in narrative_chunks:
                print(chunk, end="", flush=True)
                narrative += chunk
                if self._gui_mode:
                    self._emit_game("stream_chunk", chunk)
            print()
            self._emit_game("stream_end", narrative)

            self._session_history.append({"role": "assistant", "content": narrative})

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
            msg = f"[XP] +{amount} Erfahrungspunkte erhalten."
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
        Voice:     STT-Handler (blockierend).
        Text:      stdin.
        """
        from core.event_bus import EventBus
        bus = EventBus.get()

        if self._gui_mode:
            bus.emit("game", "waiting_for_input", {})
            # Voice: STT parallel pruefen
            if self.engine._voice_enabled and hasattr(self.engine, "_stt"):
                # Non-blocking: pruefe Queue, sonst hoere via STT
                import threading

                result_holder: list[str | None] = [None]
                got_input = threading.Event()

                def _stt_listen():
                    try:
                        text = self.engine._stt.listen()
                        if text and not got_input.is_set():
                            result_holder[0] = text
                            got_input.set()
                    except Exception as exc:
                        logger.warning("STT-Fehler: %s", exc)

                stt_thread = threading.Thread(target=_stt_listen, daemon=True)
                stt_thread.start()

                # Warte auf Queue ODER STT
                while self._active and not got_input.is_set():
                    try:
                        text = self._input_queue.get(timeout=0.1)
                        got_input.set()
                        return text
                    except queue.Empty:
                        pass

                return result_holder[0]
            else:
                # Nur Queue-Input (Text)
                while self._active:
                    try:
                        return self._input_queue.get(timeout=0.2)
                    except queue.Empty:
                        pass
                return None

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
