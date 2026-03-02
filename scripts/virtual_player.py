"""
scripts/virtual_player.py — Automatisierter Spieltest-Agent

Fuehrt N Zuege gegen die KI aus und protokolliert:
  - Keeper-Antworten (Laenge, Tags, Regelkonformitaet)
  - Wuerfelergebnisse und Stat-Aenderungen
  - Regelcheck-Warnungen
  - Timing-Metriken (Latenz pro Zug)

Test Cases (--case):
  1 = Generic (Default, bisheriges Verhalten)
  2 = Investigation (Recherche, Hinweise, PROBE-Tags)
  3 = Combat (Angriff, HP, XP)
  4 = Horror/Sanity (nur Cthulhu: Stabilitaet, Atmosphaere)
  5 = Social/NPC (Dialog, STIMME-Tags)

Verwendung:
  py -3 scripts/virtual_player.py --module cthulhu_7e --turns 10
  py -3 scripts/virtual_player.py --module cthulhu_7e -a spukhaus --case 2 -t 8 --save
  py -3 scripts/virtual_player.py --module add_2e -a testkampf --case 3 -t 8 --save
  py -3 scripts/virtual_player.py --module cthulhu_7e --turns 3 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ARS-Root in sys.path einfuegen
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# .env laden (API-Keys etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

from core.event_bus import EventBus

logger = logging.getLogger("ARS.virtual_player")

# ──────────────────────────────────────────────────────────────
# Default-Aktionen je Regelsystem
# ──────────────────────────────────────────────────────────────

DEFAULT_ACTIONS: dict[str, list[str]] = {
    "cthulhu_7e": [
        "Ich schaue mich im Raum um.",
        "Ich untersuche die Buecher auf dem Schreibtisch.",
        "Ich oeffne die Tuer zum Keller.",
        "Ich leuchte mit der Taschenlampe in die Dunkelheit.",
        "Ich rufe nach meinen Begleitern.",
        "Ich pruefe die Schriftrollen genauer.",
        "Ich versuche das Schloss zu knacken.",
        "Ich spreche den alten Mann an.",
        "Ich fluechte aus dem Raum.",
        "Ich schreibe meine Erkenntnisse auf.",
    ],
    "add_2e": [
        "Ich betrete die Taverne und schaue mich um.",
        "Ich spreche den Wirt an und bestelle ein Bier.",
        "Ich frage nach Geruechten ueber die Goblin-Hoehle.",
        "Ich pruefe meine Ausruestung und breche auf.",
        "Ich untersuche den Eingang der Hoehle.",
        "Ich ziehe mein Schwert und gehe vorsichtig hinein.",
        "Ich lausche an der naechsten Tuer.",
        "Ich oeffne die Truhe.",
        "Ich greife den Goblin an!",
        "Ich durchsuche den Raum nach Schaetzen.",
    ],
    "paranoia_2e": [
        "Ich melde mich bei Friend Computer zur Pflichterfuellung.",
        "Ich ueberprüfe meine Sicherheitsfreigabe.",
        "Ich beschuldige meinen Teamkollegen des Hochverrats.",
        "Ich oeffne die verdaechtige Tuer in Sektor B.",
        "Ich folge den Befehlen von Friend Computer bedingungslos.",
        "Ich inspiziere das defekte Geraet.",
        "Ich versuche den mutierten Gegner zu eliminieren.",
        "Ich melde die Anomalie an Friend Computer.",
        "Ich durchsuche die geheime Kammer.",
        "Ich fliehe vor der Explosion.",
    ],
    "shadowrun_6": [
        "Ich scanne die Matrix nach Infos ueber den Auftraggeber.",
        "Ich betrete den Club und suche den Kontakt.",
        "Ich aktiviere meine Cyberaugen und scanne den Raum.",
        "Ich versuche die Sicherheitstuer zu hacken.",
        "Ich ziehe meine Waffe und gebe Deckungsfeuer.",
        "Ich rufe einen Geist zur Unterstuetzung.",
        "Ich untersuche den Tatort auf magische Spuren.",
        "Ich verhandle mit dem Schieber.",
        "Ich fluechte ueber die Daechter.",
        "Ich melde den Job als erledigt.",
    ],
}

# Generische Fallback-Aktionen
DEFAULT_ACTIONS["_fallback"] = [
    "Ich schaue mich um.",
    "Was sehe ich hier?",
    "Ich untersuche den naechsten Gegenstand.",
    "Ich spreche mit der naechsten Person.",
    "Ich gehe weiter.",
    "Was passiert als naechstes?",
    "Ich pruefe meinen Zustand.",
    "Ich versuche etwas Neues.",
    "Ich warte ab.",
    "Ich reagiere auf die Situation.",
]


# ──────────────────────────────────────────────────────────────
# Test Cases
# ──────────────────────────────────────────────────────────────

@dataclass
class TestCaseConfig:
    """Konfiguration fuer einen gezielten Testfall."""
    case_id: int
    name: str
    description: str
    actions: dict[str, list[str]]       # system -> action list
    adventures: dict[str, str | None]   # system -> empfohlenes adventure
    expected_tags: dict[str, int]        # tag_name -> min_count


TEST_CASES: dict[int, TestCaseConfig] = {
    1: TestCaseConfig(
        case_id=1,
        name="generic",
        description="Generischer Test — bisheriges Verhalten, Baseline",
        actions={},  # Leer = DEFAULT_ACTIONS verwenden
        adventures={},
        expected_tags={},  # Keine spezifischen Erwartungen
    ),
    2: TestCaseConfig(
        case_id=2,
        name="investigation",
        description="Recherche-Loop: PROBE-Tags, Hinweis-Kette, Fakten",
        actions={
            "cthulhu_7e": [
                "Ich nehme den Auftrag an und gehe ins Zeitungsarchiv.",
                "Ich recherchiere alte Berichte ueber das Corbitt-Haus.",
                "Ich pruefe die Sterberegister nach Walter Corbitt.",
                "Ich untersuche die Kirchenakten auf Hinweise.",
                "Ich betrete das Corbitt-Haus und schaue mich im Erdgeschoss um.",
                "Ich suche nach versteckten Tueren oder Zugaengen.",
                "Ich oeffne die Kellertuer und steige hinab.",
                "Ich untersuche den Sarkophag genauer.",
            ],
            "add_2e": [
                "Ich untersuche den Hoehleneingang auf Spuren.",
                "Ich lausche an der Hoehle nach Geraueschen.",
                "Ich schleiche vorsichtig in den ersten Raum.",
                "Ich suche nach Fallen am Boden.",
                "Ich pruefe die Truhe auf Fallen bevor ich sie oeffne.",
                "Ich untersuche die Wandinschriften genauer.",
            ],
        },
        adventures={"cthulhu_7e": "spukhaus", "add_2e": "goblin_cave"},
        expected_tags={"PROBE": 3, "FERTIGKEIT_GENUTZT": 1, "FAKT": 1},
    ),
    3: TestCaseConfig(
        case_id=3,
        name="combat",
        description="Kampf-Szenario: ANGRIFF, HP_VERLUST, XP_GEWINN",
        actions={
            "add_2e": [
                "Ich gehe durch das Gittertor in die Arena.",
                "Ich ziehe mein Langschwert und greife den Goblin-Krieger an!",
                "Ich wende mich dem Bogenschuetzen zu und greife an!",
                "Ich trinke den Heiltrank.",
                "Ich gehe durch das Steintor zum naechsten Raum.",
                "Ich greife den Oger mit meinem Schwert an!",
                "Ich weiche seinem Schlag aus und schlage zurueck!",
                "Ich durchsuche die Truhe nach Beute.",
            ],
            "cthulhu_7e": [
                "Ich gehe direkt ins Corbitt-Haus und steige in den Keller.",
                "Ich naehre mich dem Sarkophag vorsichtig.",
                "Ich versuche den Deckel zu oeffnen.",
                "Ich wehre mich gegen die unsichtbare Kraft!",
                "Ich greife nach dem Tagebuch auf dem Boden.",
            ],
        },
        adventures={"add_2e": "testkampf", "cthulhu_7e": "spukhaus"},
        expected_tags={"ANGRIFF": 2, "HP_VERLUST": 1},
    ),
    4: TestCaseConfig(
        case_id=4,
        name="horror",
        description="Horror/Sanity — Stabilitaetsverlust, atmosphaerische Dichte (nur Cthulhu)",
        actions={
            "cthulhu_7e": [
                "Ich betrete das Corbitt-Haus bei Nacht alleine.",
                "Ich hoere seltsame Geraeusche und folge ihnen.",
                "Ich oeffne die Tuer aus der die Geraeusche kommen.",
                "Ich starre in die Dunkelheit des Kellers.",
                "Ich steige die Treppe hinab obwohl alles in mir schreit.",
                "Ich sehe etwas im Sarkophag. Ich schaue genauer hin.",
                "Ich lese die alten Texte an der Wand laut vor.",
                "Ich versuche zu verstehen was hier geschehen ist.",
            ],
        },
        adventures={"cthulhu_7e": "spukhaus"},
        expected_tags={"STABILITAET_VERLUST": 1, "PROBE": 2, "FAKT": 1},
    ),
    5: TestCaseConfig(
        case_id=5,
        name="social",
        description="Social/NPC — Dialog, STIMME-Tags, Informationsgewinn",
        actions={
            "cthulhu_7e": [
                "Ich frage Mr. Knott nach den frueheren Mietern.",
                "Ich frage nach der Geschichte des Hauses.",
                "Ich bitte die Archivarin Webb um Hilfe bei der Suche.",
                "Ich versuche sie zu ueberzeugen mir die gesperrten Akten zu zeigen.",
                "Ich befrage Nachbarn des Corbitt-Hauses.",
                "Ich kehre zu Mr. Knott zurueck und berichte.",
            ],
            "add_2e": [
                "Ich spreche den Wirt an und frage nach Geruechten.",
                "Ich versuche den Wirt zu ueberzeugen mir mehr zu erzaehlen.",
                "Ich frage die anderen Gaeste nach der Goblin-Hoehle.",
                "Ich verhandle mit dem Haendler ueber Ausruestung.",
                "Ich versuche den gefangenen Goblin auszufragen.",
            ],
        },
        adventures={"cthulhu_7e": "spukhaus", "add_2e": "goblin_cave"},
        expected_tags={"STIMME": 1, "PROBE": 1},
    ),
}


# ──────────────────────────────────────────────────────────────
# Datenstrukturen fuer Metriken
# ──────────────────────────────────────────────────────────────

@dataclass
class TurnMetrics:
    """Metriken fuer einen einzelnen Zug."""
    turn: int = 0
    player_input: str = ""
    keeper_response: str = ""
    response_chars: int = 0
    response_sentences: int = 0
    latency_ms: float = 0.0
    tags_found: list[str] = field(default_factory=list)
    probes: int = 0
    stat_changes: int = 0
    combat_tags: int = 0
    inventory_changes: int = 0
    time_changes: int = 0
    facts: int = 0
    rules_warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class SessionMetrics:
    """Aggregierte Metriken fuer die gesamte Simulation."""
    module: str = ""
    adventure: str | None = None
    case_id: int = 1
    case_name: str = "generic"
    expected_tags: dict[str, int] = field(default_factory=dict)
    total_turns: int = 0
    total_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    avg_response_chars: float = 0.0
    avg_sentences: float = 0.0
    total_probes: int = 0
    total_combat_tags: int = 0
    total_stat_changes: int = 0
    total_rules_warnings: int = 0
    character_alive: bool = True
    turns: list[TurnMetrics] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# Tag-Zaehlung (leichtgewichtig, ohne Orchestrator-Imports)
# ──────────────────────────────────────────────────────────────

import re

_TAG_PATTERNS = {
    "PROBE": re.compile(r"\[PROBE:\s*[^\]]+\]"),
    "HP_VERLUST": re.compile(r"\[HP_VERLUST:\s*\d+\s*\]"),
    "HP_HEILUNG": re.compile(r"\[HP_HEILUNG:\s*[^\]]+\]"),
    "STABILITAET_VERLUST": re.compile(r"\[STABILITAET_VERLUST:\s*[^\]]+\]"),
    "XP_GEWINN": re.compile(r"\[XP_GEWINN:\s*\d+\s*\]"),
    "FERTIGKEIT_GENUTZT": re.compile(r"\[FERTIGKEIT_GENUTZT:\s*[^\]]+\]"),
    "INVENTAR": re.compile(r"\[INVENTAR:\s*[^\]]+\]"),
    "ANGRIFF": re.compile(r"\[ANGRIFF:\s*[^\]]+\]"),
    "RETTUNGSWURF": re.compile(r"\[RETTUNGSWURF:\s*[^\]]+\]"),
    "ZEIT_VERGEHT": re.compile(r"\[ZEIT_VERGEHT:\s*[^\]]+\]"),
    "TAGESZEIT": re.compile(r"\[TAGESZEIT:\s*[^\]]+\]"),
    "WETTER": re.compile(r"\[WETTER:\s*[^\]]+\]"),
    "FAKT": re.compile(r"\[FAKT:\s*[^\]]+\]"),
    "STIMME": re.compile(r"\[STIMME:\s*[^\]]+\]"),
    "TREASON_POINT": re.compile(r"\[TREASON_POINT:\s*[^\]]+\]"),
    "CLONE_TOD": re.compile(r"\[CLONE_TOD\]"),
    "EDGE": re.compile(r"\[EDGE:\s*[^\]]+\]"),
}


def count_tags(text: str) -> dict[str, int]:
    """Zaehlt alle Tags in einer KI-Antwort."""
    result = {}
    for tag_name, pattern in _TAG_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            result[tag_name] = len(matches)
    return result


def count_sentences(text: str) -> int:
    """Zaehlt Saetze (grob: Punkt/Ausrufezeichen/Fragezeichen gefolgt von Leerzeichen oder Ende)."""
    # Tags entfernen vor dem Zaehlen
    clean = re.sub(r"\[[^\]]+\]", "", text).strip()
    if not clean:
        return 0
    return len(re.findall(r"[.!?]+(?:\s|$)", clean))


# ──────────────────────────────────────────────────────────────
# VirtualPlayer
# ──────────────────────────────────────────────────────────────

class VirtualPlayer:
    """Automatisierter Spieler fuer Regressions- und Lasttests."""

    def __init__(
        self,
        module_name: str,
        adventure: str | None = None,
        actions: list[str] | None = None,
        max_turns: int = 10,
        dry_run: bool = False,
        preset: str | None = None,
        turn_delay: float = 2.0,
        case_id: int = 1,
    ) -> None:
        self.module_name = module_name
        self.max_turns = max_turns
        self.dry_run = dry_run
        self.preset = preset
        self.turn_delay = turn_delay  # Verzögerung zwischen Zügen (Sekunden)

        # Test Case laden
        self._case = TEST_CASES.get(case_id, TEST_CASES[1])

        # Aktionen bestimmen: CLI --actions > Case-Aktionen > DEFAULT_ACTIONS
        if actions:
            self._actions = actions
        elif self._case.case_id != 1 and module_name in self._case.actions:
            self._actions = self._case.actions[module_name]
        else:
            self._actions = DEFAULT_ACTIONS.get(
                module_name, DEFAULT_ACTIONS["_fallback"]
            )

        # Adventure: CLI --adventure > Case-Empfehlung > None
        if adventure is not None:
            self.adventure = adventure
        elif self._case.adventures.get(module_name):
            self.adventure = self._case.adventures[module_name]
        else:
            self.adventure = None

        self._engine = None
        self._metrics = SessionMetrics(
            module=module_name,
            adventure=self.adventure,
            case_id=self._case.case_id,
            case_name=self._case.name,
            expected_tags=dict(self._case.expected_tags),
        )
        self._rules_warnings: list[str] = []

        # EventBus-Listener
        self._bus = EventBus.get()
        self._current_response_chunks: list[str] = []

    # -- Setup ---------------------------------------------------------------

    def setup(self) -> None:
        """Engine initialisieren (ohne Voice, ohne GUI-Fenster)."""
        from core.engine import SimulatorEngine
        from core.session_config import SessionConfig

        # SessionConfig bauen
        if self.preset:
            cfg = SessionConfig.from_preset(self.preset)
        else:
            cfg = SessionConfig(ruleset=self.module_name)

        self._engine = SimulatorEngine(self.module_name, session_config=cfg)
        self._engine.initialize()

        # Abenteuer laden (optional)
        if self.adventure:
            self._engine.load_adventure(self.adventure)

        # GUI-Modus fuer Queue-basiertes Input
        orchestrator = self._engine._orchestrator
        orchestrator.set_gui_mode(enabled=True)

        # EventBus: Regelcheck-Warnungen abfangen
        self._bus.on("game.output", self._on_game_event)

        logger.info(
            "VirtualPlayer bereit: %s (Adventure: %s, Case: %d-%s, Turns: %d)",
            self.module_name, self.adventure or "keins",
            self._case.case_id, self._case.name, self.max_turns,
        )

    def _on_game_event(self, data: Any) -> None:
        """EventBus-Listener fuer Regelcheck-Warnungen."""
        if isinstance(data, dict):
            tag = data.get("tag", "")
            text = data.get("text", "")
            if tag == "rules_warning":
                self._rules_warnings.append(text)

    # -- Simulation ----------------------------------------------------------

    def run(self) -> SessionMetrics:
        """Fuehrt die Simulation durch und gibt Metriken zurueck."""
        if self.dry_run:
            return self._dry_run()

        import threading

        orchestrator = self._engine._orchestrator

        # Game-Loop im Hintergrund starten
        game_thread = threading.Thread(
            target=self._engine.run,
            daemon=True,
            name="VirtualPlayer-GameLoop",
        )
        game_thread.start()

        # Kurze Verzoegerung damit start_session() den Loop oeffnet
        time.sleep(1.0)

        for turn_idx in range(self.max_turns):
            if not orchestrator._active:
                logger.info("Session vom Orchestrator beendet (Spieler tot?).")
                break

            action = self._actions[turn_idx % len(self._actions)]
            tm = self._play_turn(turn_idx + 1, action, orchestrator)
            self._metrics.turns.append(tm)

            # Charakter-Tod pruefen
            if self._engine.character and self._engine.character.is_dead:
                logger.info("Charakter ist tot nach Zug %d.", turn_idx + 1)
                self._metrics.character_alive = False
                break

            # Verzögerung zwischen Zügen (zur Vermeidung von Systemüberlastung)
            if turn_idx < self.max_turns - 1:
                logger.info("Warte %.1fs vor nächstem Zug...", self.turn_delay)
                time.sleep(self.turn_delay)

        # Session sauber beenden
        orchestrator.submit_input("quit")
        game_thread.join(timeout=5.0)

        # Aggregierte Metriken berechnen
        self._aggregate_metrics()
        return self._metrics

    def _play_turn(
        self, turn_num: int, action: str, orchestrator: Any
    ) -> TurnMetrics:
        """Spielt einen einzelnen Zug und sammelt Metriken."""
        import threading

        tm = TurnMetrics(turn=turn_num, player_input=action)
        self._rules_warnings.clear()

        # Response-Sammlung: warte auf stream_end Event
        response_event = threading.Event()
        collected_response = {"text": ""}

        def _listener(data: Any) -> None:
            if isinstance(data, dict) and data.get("tag") == "stream_end":
                collected_response["text"] = data.get("text", str(data))
                response_event.set()

        self._bus.on("game.output", _listener)

        # Input abschicken + Timer starten
        t0 = time.perf_counter()
        orchestrator.submit_input(action)

        # Auf Antwort warten (Timeout: 120s)
        if not response_event.wait(timeout=120.0):
            self._bus.off("game.output", _listener)
            tm.error = "Timeout: Keine Antwort innerhalb von 120 Sekunden."
            tm.latency_ms = 120_000.0
            logger.error("Turn %d: %s", turn_num, tm.error)
            return tm

        self._bus.off("game.output", _listener)

        t1 = time.perf_counter()
        tm.latency_ms = (t1 - t0) * 1000.0

        # Response analysieren
        response = collected_response["text"]
        tm.keeper_response = response
        tm.response_chars = len(response)
        tm.response_sentences = count_sentences(response)

        tags = count_tags(response)
        tm.tags_found = list(tags.keys())
        tm.probes = tags.get("PROBE", 0)
        tm.stat_changes = sum(
            tags.get(t, 0)
            for t in ("HP_VERLUST", "HP_HEILUNG", "STABILITAET_VERLUST", "XP_GEWINN")
        )
        tm.combat_tags = sum(tags.get(t, 0) for t in ("ANGRIFF", "RETTUNGSWURF"))
        tm.inventory_changes = tags.get("INVENTAR", 0)
        tm.time_changes = sum(
            tags.get(t, 0) for t in ("ZEIT_VERGEHT", "TAGESZEIT", "WETTER")
        )
        tm.facts = tags.get("FAKT", 0)
        tm.rules_warnings = list(self._rules_warnings)

        # Zug-Report
        logger.info(
            "Turn %d: %d Zeichen, %d Saetze, %.0fms, Tags: %s",
            turn_num, tm.response_chars, tm.response_sentences,
            tm.latency_ms, tm.tags_found,
        )

        return tm

    def _dry_run(self) -> SessionMetrics:
        """Trockenlauf: zeigt geplante Aktionen ohne KI-Aufruf."""
        print(f"\n{'='*60}")
        print(f"  TROCKENLAUF — {self.module_name}")
        print(f"  Abenteuer: {self.adventure or 'keins'}")
        print(f"  Test Case: {self._case.case_id} — {self._case.name}")
        print(f"  Beschreibung: {self._case.description}")
        print(f"  Geplante Zuege: {self.max_turns}")
        if self._case.expected_tags:
            tags_str = ", ".join(f"{k}>={v}" for k, v in self._case.expected_tags.items())
            print(f"  Erwartete Tags: {tags_str}")
        print(f"{'='*60}\n")

        for i in range(self.max_turns):
            action = self._actions[i % len(self._actions)]
            print(f"  Zug {i+1:3d}: {action}")
            tm = TurnMetrics(turn=i + 1, player_input=action)
            self._metrics.turns.append(tm)

        self._metrics.total_turns = self.max_turns
        print(f"\n  (Keine KI-Aufrufe im Trockenlauf)\n")
        return self._metrics

    # -- Aggregation ---------------------------------------------------------

    def _aggregate_metrics(self) -> None:
        """Berechnet Durchschnittsmetriken."""
        turns = self._metrics.turns
        n = len(turns)
        if n == 0:
            return

        self._metrics.total_turns = n
        self._metrics.total_latency_ms = sum(t.latency_ms for t in turns)
        self._metrics.avg_latency_ms = self._metrics.total_latency_ms / n
        self._metrics.avg_response_chars = sum(t.response_chars for t in turns) / n
        self._metrics.avg_sentences = sum(t.response_sentences for t in turns) / n
        self._metrics.total_probes = sum(t.probes for t in turns)
        self._metrics.total_combat_tags = sum(t.combat_tags for t in turns)
        self._metrics.total_stat_changes = sum(t.stat_changes for t in turns)
        self._metrics.total_rules_warnings = sum(len(t.rules_warnings) for t in turns)

    # -- Report --------------------------------------------------------------

    def print_report(self) -> None:
        """Gibt einen menschenlesbaren Report aus."""
        m = self._metrics
        print(f"\n{'='*60}")
        print(f"  SIMULATIONS-REPORT: {m.module}")
        if m.adventure:
            print(f"  Abenteuer: {m.adventure}")
        print(f"  Test Case: {m.case_id} — {m.case_name}")
        print(f"{'='*60}")
        print(f"  Zuege gespielt:        {m.total_turns}")
        print(f"  Charakter lebt:        {'Ja' if m.character_alive else 'NEIN'}")
        print(f"  Gesamt-Latenz:         {m.total_latency_ms:,.0f} ms")
        print(f"  Durchschn. Latenz:     {m.avg_latency_ms:,.0f} ms")
        print(f"  Durchschn. Antwort:    {m.avg_response_chars:,.0f} Zeichen")
        print(f"  Durchschn. Saetze:     {m.avg_sentences:.1f}")
        print(f"  Proben ausgeloest:     {m.total_probes}")
        print(f"  Kampf-Tags:            {m.total_combat_tags}")
        print(f"  Stat-Aenderungen:      {m.total_stat_changes}")
        print(f"  Regelcheck-Warnungen:  {m.total_rules_warnings}")

        if m.total_rules_warnings > 0:
            print(f"\n  Warnungen:")
            for t in m.turns:
                for w in t.rules_warnings:
                    print(f"    Zug {t.turn}: {w}")

        print(f"\n  Zug-Details:")
        print(f"  {'Zug':>4} | {'Latenz':>8} | {'Zeichen':>7} | {'Saetze':>6} | Tags")
        print(f"  {'-'*4}-+-{'-'*8}-+-{'-'*7}-+-{'-'*6}-+-{'-'*30}")
        for t in m.turns:
            tags_str = ", ".join(t.tags_found) if t.tags_found else "-"
            err = f" [FEHLER: {t.error}]" if t.error else ""
            print(
                f"  {t.turn:4d} | {t.latency_ms:7.0f}ms | {t.response_chars:7d} | "
                f"{t.response_sentences:6d} | {tags_str}{err}"
            )

        print(f"{'='*60}\n")

    def save_report(self, path: Path | None = None) -> Path:
        """Speichert den Report als JSON."""
        if path is None:
            ts = time.strftime("%Y%m%d_%H%M%S")
            case_name = self._case.name
            path = _ROOT / "data" / "test_results" / f"test_{self.module_name}_{case_name}_{ts}.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        data = asdict(self._metrics)
        # Volle Keeper-Response speichern (kein Truncation)

        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

        logger.info("Report gespeichert: %s", path)
        return path


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARS Virtual Player — Automatisierter Spieltest-Agent",
    )
    parser.add_argument(
        "--module", "-m", required=True,
        help="Regelsystem (z.B. cthulhu_7e, add_2e, paranoia_2e, shadowrun_6)",
    )
    parser.add_argument(
        "--adventure", "-a", default=None,
        help="Abenteuer laden (z.B. spukhaus)",
    )
    parser.add_argument(
        "--preset", "-p", default=None,
        help="Preset laden (z.B. coc_classic)",
    )
    parser.add_argument(
        "--turns", "-t", type=int, default=10,
        help="Anzahl Zuege (Default: 10)",
    )
    parser.add_argument(
        "--actions", nargs="+", default=None,
        help="Benutzerdefinierte Aktionen (ueberschreibt Defaults)",
    )
    parser.add_argument(
        "--case", "-c", type=int, default=1, choices=[1, 2, 3, 4, 5],
        help="Test Case: 1=generic, 2=investigation, 3=combat, 4=horror, 5=social (Default: 1)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Trockenlauf: zeigt Aktionen ohne KI-Aufruf",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Report als JSON in data/test_results/ speichern",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Debug-Logging aktivieren",
    )
    parser.add_argument(
        "--turn-delay", type=float, default=2.0,
        help="Verzögerung zwischen Zügen in Sekunden (Default: 2.0)",
    )

    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    vp = VirtualPlayer(
        module_name=args.module,
        adventure=args.adventure,
        actions=args.actions,
        max_turns=args.turns,
        dry_run=args.dry_run,
        preset=args.preset,
        turn_delay=args.turn_delay,
        case_id=args.case,
    )

    if not args.dry_run:
        vp.setup()

    metrics = vp.run()
    vp.print_report()

    if args.save:
        path = vp.save_report()
        print(f"Report gespeichert: {path}")


if __name__ == "__main__":
    main()
