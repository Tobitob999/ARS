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

LLM-Player (--llm-player):
  Kontextsensitiver Spielerbot via Gemini Flash. Liest die Keeper-Antwort
  und generiert passende Aktionen statt starre Aktionslisten abzuspulen.
  Im Party-Modus werden alle Charakter-Aktionen als Block generiert.

Verwendung:
  py -3 scripts/virtual_player.py --module cthulhu_7e --turns 10
  py -3 scripts/virtual_player.py --module cthulhu_7e -a spukhaus --case 2 -t 8 --save
  py -3 scripts/virtual_player.py --module add_2e -a testkampf --case 3 -t 8 --save
  py -3 scripts/virtual_player.py --module cthulhu_7e --turns 3 --dry-run

  # LLM-Player (Party):
  py -3 scripts/virtual_player.py --module add_2e -a dungeon_gauntlet --party add_valdrak_party --turns 200 --llm-player --save

  # LLM-Player (Einzel):
  py -3 scripts/virtual_player.py --module cthulhu_7e -a spukhaus --turns 20 --llm-player --save
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
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
    6: TestCaseConfig(
        case_id=6,
        name="dungeon_crawl",
        description="Dungeon Crawl: Kampf bis zum Tod, Loot, Fallen, Klettern, Springen, Quest",
        actions={
            "add_2e": [
                "Ich betrete die Ruinen von Valdrak und schaue mich um.",
                "Ich durchsuche den Schutt in der Vorhalle nach verborgenen Gegenstaenden.",
                "Ich untersuche die Waende nach Geheimtueren oder Inschriften.",
                "Ich ziehe mein Schwert und greife die Skelett-Krieger an!",
                "Ich schlage erneut zu und versuche das Skelett zu zerschmettern!",
                "Ich durchsuche die besiegten Gegner nach Beute.",
                "Ich gehe vorsichtig in den Korridor und suche nach Fallen.",
                "Ich versuche die Falle zu entschaerfen.",
                "Ich springe ueber die Fallgrube!",
                "Ich betrete die Ruestkammer und durchsuche die Waffenstaender.",
                "Ich oeffne die alte Truhe vorsichtig.",
                "Ich klettere die Mauer zum oberen Stockwerk hoch.",
                "Ich stelle mich dem Totenwacht-Ritter zum Kampf!",
                "Ich greife den Untoten mit voller Wucht an!",
                "Ich weiche seinem Schwerthieb aus und schlage zurueck!",
                "Ich sammle die Beute des besiegten Ritters ein.",
                "Ich ueberquere die Steinbruecke ueber den Abgrund.",
                "Die Bruecke bricht! Ich springe zum anderen Ende!",
                "Ich kaempfe gegen die Riesenspinnen im Nest!",
                "Ich greife die naechste Spinne an bevor sie mich vergiftet!",
                "Ich durchsuche das Spinnennest nach Schaetzen.",
                "Ich springe zur Insel im unterirdischen Fluss.",
                "Ich oeffne die Truhe auf der Insel.",
                "Ich klettere den vertikalen Schacht hinauf.",
                "Ich halte mich fest als der Griff abbricht und klettere weiter!",
                "Ich greife den Troll mit meinem Schwert an!",
                "Ich setze Feuer ein gegen den regenerierenden Troll!",
                "Ich durchsuche die Trollhoehle nach Beute.",
                "Ich betrete vorsichtig den Grufteingang und halte die Luft an.",
                "Ich kaempfe gegen die Wights in der Halle der Krieger!",
                "Ich schlage den naechsten Wight mit meiner magischen Waffe!",
                "Ich weiche dem Energieentzug-Angriff aus!",
                "Ich durchquere den Fallen-Parcours — Pfeile, Stacheln, Pendel!",
                "Ich springe ueber die Stachelgrube!",
                "Ich rolle unter dem Pendel hindurch!",
                "Ich stelle mich dem Lich Valdrak in der Artefaktkammer!",
                "Ich greife den Lich mit meiner magischen Waffe an!",
                "Ich trinke meinen Heiltrank im Kampf!",
                "Ich zerstoere den Phylakterion des Lichs!",
                "Ich greife die Kugel der Zeitalter und renne zum Ausgang!",
                "Ich springe ueber den einstuerzenden Boden!",
                "Ich renne durch den kollabierenden Gang zum Ausgang!",
            ],
            "cthulhu_7e": [
                "Ich betrete das alte Gewoelbe und schaue mich um.",
                "Ich untersuche die Waende nach Geheimtueren.",
                "Ich durchsuche den Raum gruendlich nach Hinweisen.",
                "Ich oeffne die alte Truhe vorsichtig.",
                "Ich klettere die Leiter in den Keller hinab.",
                "Ich versuche ueber den Spalt zu springen.",
                "Ich wehre mich gegen die Kreatur die mich angreift!",
                "Ich schlage mit meiner Waffe auf das Wesen ein!",
                "Ich durchsuche den Raum nach verwertbaren Gegenstaenden.",
                "Ich untersuche die seltsamen Inschriften an der Wand.",
                "Ich taste den Boden nach Fallen ab.",
                "Ich versuche die Falle zu umgehen.",
                "Ich greife das Monster erneut an!",
                "Ich sammle die Beute ein und gehe weiter.",
            ],
            "shadowrun_6": [
                "Ich scanne den Eingangsbereich auf Fallen und Sicherheitssysteme.",
                "Ich hacke das elektronische Schloss.",
                "Ich durchsuche den Server-Raum nach Daten.",
                "Ich klettere durch den Luftschacht nach oben.",
                "Ich springe ueber die Absperrung.",
                "Ich ziehe meine Waffe und schiesse auf den Wachroboter!",
                "Ich greife den naechsten Gegner an!",
                "Ich sammle die Beute vom ausgeschalteten Gegner ein.",
                "Ich durchsuche den Raum nach versteckten Zugaengen.",
                "Ich untersuche die Konsole auf nuetzliche Informationen.",
            ],
            "paranoia_2e": [
                "Ich betrete den Sektor und durchsuche ihn nach verdaechtigen Gegenstaenden.",
                "Ich klettere durch die Wartungsluke.",
                "Ich springe ueber das defekte Fliessband.",
                "Ich untersuche die Kontrollkonsole.",
                "Ich greife den mutierten Verraeter an!",
                "Ich schiesse erneut auf den Feind!",
                "Ich durchsuche den eliminierten Verraeter nach Beweisen.",
                "Ich suche nach Fallen in diesem Bereich.",
                "Ich oeffne die verschlossene Kiste.",
                "Ich melde den Fund an Friend Computer.",
            ],
        },
        adventures={"add_2e": "dungeon_gauntlet", "cthulhu_7e": "spukhaus"},
        expected_tags={"ANGRIFF": 5, "HP_VERLUST": 3, "PROBE": 3, "INVENTAR": 2, "RETTUNGSWURF": 1, "MONSTER_BEWEGT": 3},
    ),
    7: TestCaseConfig(
        case_id=7,
        name="party_dungeon_crawl",
        description="Party Dungeon Crawl: 6 Charaktere, Kampf, Erkundung, Raetsel",
        actions={
            "add_2e": [
                # Exploration (6 actions)
                "Lyra schleicht voraus und untersucht den naechsten Raum auf Fallen.",
                "Thorin stellt sich vor die Gruppe und hebt seine Axt bereit.",
                "Elara untersucht die Runen an der Wand magisch.",
                "Bruder Aldhelm betet um Fuehrung und sucht nach Untoten.",
                "Kaelen prueft den Boden auf Spuren und lauscht.",
                "Sir Aldric erkennt ob es Boeses in der Naehe gibt.",
                # Combat (6 actions)
                "Thorin greift den naechsten Feind mit seiner Schlachtaxt +1 an!",
                "Elara wirkt Fireball auf die Gegnergruppe!",
                "Lyra schleicht hinter den Feind und greift aus dem Hinterhalt an!",
                "Bruder Aldhelm heilt Thorin und kaempft mit dem Streitkolben!",
                "Kaelen schiesst zwei Pfeile auf den entferntesten Gegner!",
                "Sir Aldric greift den Untoten mit seinem Heiligen Schwert an!",
                # Puzzle (3 actions)
                "Elara analysiert die magische Barriere. Was sieht sie?",
                "Lyra untersucht die Truhe auf Fallen bevor sie sie oeffnet.",
                "Bruder Aldhelm versucht die Inschrift zu entschluesseln.",
            ],
        },
        adventures={"add_2e": "dungeon_gauntlet"},
        expected_tags={"ANGRIFF": 3, "HP_VERLUST": 2, "PROBE": 3, "ZAUBER_VERBRAUCHT": 1, "MONSTER_BEWEGT": 2},
    ),
}

# Party-Aktionen fuer den Multi-Charakter-Modus (rollenbasiert)
PARTY_ACTIONS = {
    "exploration": [
        "Lyra schleicht voraus und untersucht den naechsten Raum auf Fallen.",
        "Thorin stellt sich vor die Gruppe und hebt seine Axt bereit.",
        "Elara untersucht die Runen an der Wand magisch.",
        "Bruder Aldhelm betet um Fuehrung und sucht nach Untoten.",
        "Kaelen prueft den Boden auf Spuren und lauscht.",
        "Sir Aldric erkennt ob es Boeses in der Naehe gibt.",
    ],
    "combat": [
        "Thorin greift den naechsten Feind mit seiner Schlachtaxt +1 an!",
        "Elara wirkt Fireball auf die Gegnergruppe!",
        "Lyra schleicht hinter den Feind und greift aus dem Hinterhalt an!",
        "Bruder Aldhelm heilt Thorin und kaempft mit dem Streitkolben!",
        "Kaelen schiesst zwei Pfeile auf den entferntesten Gegner!",
        "Sir Aldric greift den Untoten mit seinem Heiligen Schwert an!",
    ],
    "puzzle": [
        "Elara analysiert die magische Barriere. Was sieht sie?",
        "Lyra untersucht die Truhe auf Fallen bevor sie sie oeffnet.",
        "Bruder Aldhelm versucht die Inschrift zu entschluesseln.",
    ],
}


# ──────────────────────────────────────────────────────────────
# LLM-basierter Spielerbot
# ──────────────────────────────────────────────────────────────

# Gemini Flash Preise (identisch mit ai_backend.py)
_PRICE_INPUT_PER_M = 0.30
_PRICE_OUTPUT_PER_M = 2.50

_PARTY_SYSTEM_PROMPT_TEMPLATE = """\
Du bist ein aggressiver TTRPG-Spieler. Du steuerst eine Gruppe:
{member_list}

Lies die Keeper-Antwort und antworte mit EINER Aktion pro lebendem Gruppenmitglied.
Format: Name: [Aktion]

Regeln:
- IMMER offensiv handeln: Angreifen, vorruecken, weiter in den naechsten Raum
- Fighter/Paladin: Greifen das naechste Monster an
- Mage: Wirkt Offensivzauber (Fireball, Magic Missile, Lightning Bolt)
- Cleric: Heilt nur bei < 50% HP, sonst kaempft oder buffed (Bless, Prayer)
- Thief: Backstab oder Fallen suchen, dann weiter
- Ranger: Fernkampf-Alpha-Strike, dann Nahkampf
- Wenn kein Kampf: In den NAECHSTEN RAUM vordringen. Nie lange erkunden.
- Jede Aktion 1 kurzer Satz auf Deutsch
- Tote Mitglieder ueberspringen
- Kein OOC-Kommentar, nur Aktionen
"""

_SOLO_SYSTEM_PROMPT_TEMPLATE = """\
Du bist ein erfahrener TTRPG-Spieler. Du steuerst den Charakter {char_name}.

Lies die Keeper-Antwort und antworte mit EINER passenden Aktion.
Format: Ich [Aktion].

Regeln:
- Reagiere passend auf die Szene (Kampf→Angriff, Raum→Erkunden, Truhe→Oeffnen)
- 1 kurzer Satz auf Deutsch
- Kein OOC-Kommentar, nur die Aktion
"""


class LLMPlayerBot:
    """LLM-basierter Spielerbot: generiert kontextsensitive Aktionen via Gemini Flash."""

    def __init__(
        self,
        member_names: list[str] | None = None,
        member_archetypes: dict[str, str] | None = None,
        party_state: Any = None,
        char_name: str | None = None,
        module_name: str = "add_2e",
    ) -> None:
        self._party_state = party_state
        self._member_names = member_names or []
        self._member_archetypes = member_archetypes or {}
        self._char_name = char_name
        self._module_name = module_name
        self._history: list[str] = []  # rolling keeper responses (max 5)
        self._client = None

        # Token tracking (separate from Keeper)
        self.prompt_tokens: int = 0
        self.output_tokens: int = 0
        self.total_cost: float = 0.0

        # Build system prompt
        if self._member_names:
            member_list = ", ".join(
                f"{n} ({self._member_archetypes.get(n, '?')})"
                for n in self._member_names
            )
            self._system_prompt = _PARTY_SYSTEM_PROMPT_TEMPLATE.format(
                member_list=member_list
            )
        else:
            self._system_prompt = _SOLO_SYSTEM_PROMPT_TEMPLATE.format(
                char_name=self._char_name or "Abenteurer"
            )

        # Initialize Gemini client
        self._init_client()

    def _init_client(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("LLMPlayerBot: Kein API-Key — Fallback auf Zufallsaktionen.")
            return
        try:
            from google import genai  # type: ignore[import]
            self._client = genai.Client(api_key=api_key)
            logger.info("LLMPlayerBot: Gemini-Client initialisiert.")
        except ImportError:
            logger.warning("LLMPlayerBot: google-genai nicht installiert — Fallback.")

    def add_keeper_response(self, text: str) -> None:
        """Fuegt eine Keeper-Antwort zur Rolling History hinzu (max 5, je 500 Zeichen)."""
        self._history.append(text[:500])
        if len(self._history) > 5:
            self._history = self._history[-5:]

    def generate_action(self, keeper_response: str) -> str:
        """Generiert eine kontextsensitive Aktion basierend auf der Keeper-Antwort."""
        self.add_keeper_response(keeper_response)

        if self._client is None:
            return self._fallback_action()

        # Build user message with context
        parts = []
        if len(self._history) > 1:
            parts.append("Bisheriger Verlauf (Kurzform):")
            for i, h in enumerate(self._history[:-1], 1):
                parts.append(f"  Keeper #{i}: {h}")
            parts.append("")

        # Party state summary if available
        if self._party_state:
            try:
                summary = self._party_state.get_summary()
                parts.append(summary)
                parts.append("")
            except Exception:
                pass

        parts.append(f"Aktuelle Keeper-Antwort:\n{keeper_response[:800]}")
        parts.append("\nDeine Aktion(en):")

        user_msg = "\n".join(parts)

        try:
            from google.genai import types  # type: ignore[import]
            response = self._client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[{"role": "user", "parts": [{"text": user_msg}]}],
                config=types.GenerateContentConfig(
                    system_instruction=self._system_prompt,
                    temperature=0.8,
                ),
            )
            result = (response.text or "").strip()

            # Track tokens
            um = getattr(response, "usage_metadata", None)
            if um:
                p_tok = getattr(um, "prompt_token_count", 0) or 0
                o_tok = getattr(um, "candidates_token_count", 0) or 0
                self.prompt_tokens += p_tok
                self.output_tokens += o_tok
                self.total_cost += (
                    p_tok * _PRICE_INPUT_PER_M / 1_000_000
                    + o_tok * _PRICE_OUTPUT_PER_M / 1_000_000
                )

            if result:
                logger.info("LLMPlayerBot Aktion: %s", result[:120])
                return result

        except Exception as exc:
            logger.warning("LLMPlayerBot API-Fehler: %s — Fallback.", exc)

        return self._fallback_action()

    def _fallback_action(self) -> str:
        """Zufaellige Aktion aus DEFAULT_ACTIONS als Fallback."""
        actions = DEFAULT_ACTIONS.get(self._module_name, DEFAULT_ACTIONS["_fallback"])
        return random.choice(actions)

    def get_token_summary(self) -> dict:
        """Gibt Token-Zusammenfassung zurueck."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "total_cost_usd": round(self.total_cost, 6),
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
    # NEU: Grid-Snapshot fuer Replay
    room_id: str = ""
    room_width: int = 0
    room_height: int = 0
    grid_positions: dict = field(default_factory=dict)   # {entity_id: [x, y]}
    grid_entities: dict = field(default_factory=dict)     # {entity_id: {name, type, symbol, alive}}
    party_hp: dict = field(default_factory=dict)          # {name: {hp, hp_max, alive, archetype}}
    move_events: list = field(default_factory=list)       # Gesammelte grid-Events waehrend Zug
    room_terrain: list = field(default_factory=list)      # [[terrain_str, ...], ...] Terrain-Grid


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
    "HP_VERLUST": re.compile(r"\[HP_VERLUST:\s*[^\]]+\]"),
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
    "GEGENSTAND_BENUTZT": re.compile(r"\[GEGENSTAND_BENUTZT:\s*[^\]]+\]"),
    "RUNDE": re.compile(r"\[RUNDE:\s*\d+\s*\]"),
    "ZAUBER_VERBRAUCHT": re.compile(r"\[ZAUBER_VERBRAUCHT:\s*[^\]]+\]"),
    "FAKT": re.compile(r"\[FAKT:\s*[^\]]+\]"),
    "STIMME": re.compile(r"\[STIMME:\s*[^\]]+\]"),
    "TREASON_POINT": re.compile(r"\[TREASON_POINT:\s*[^\]]+\]"),
    "CLONE_TOD": re.compile(r"\[CLONE_TOD\]"),
    "EDGE": re.compile(r"\[EDGE:\s*[^\]]+\]"),
    "MONSTER_BEWEGT": re.compile(r"\[MONSTER_BEWEGT:\s*[^\]]+\]"),
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
        progress_file: Path | str | None = None,
        speech_style: str = "normal",
        party: str | None = None,
        llm_player: bool = False,
        pre_damage: int = 0,
    ) -> None:
        self.module_name = module_name
        self.max_turns = max_turns
        self.dry_run = dry_run
        self.preset = preset
        self.turn_delay = turn_delay  # Verzögerung zwischen Zügen (Sekunden)
        self.progress_file: Path | None = Path(progress_file) if progress_file else None
        self._started_at: str = datetime.now().isoformat()
        self._speech_style = speech_style
        self._party_name = party
        self._party_mode = party is not None
        self._llm_player = llm_player
        self._pre_damage = pre_damage  # Prozent Vorschaden (0-90)
        self._player_bot: LLMPlayerBot | None = None

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

        # Token-Tracking
        self._total_prompt_tokens: int = 0
        self._total_cached_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_think_tokens: int = 0
        self._total_cost: float = 0.0

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
        cfg.speech_style = self._speech_style

        # Party-Modus: Party in SessionConfig setzen
        if self._party_name:
            cfg.party = self._party_name

        self._engine = SimulatorEngine(self.module_name, session_config=cfg)
        self._engine.initialize()

        # Abenteuer laden (optional)
        if self.adventure:
            self._engine.load_adventure(self.adventure)

        # GUI-Modus fuer Queue-basiertes Input
        orchestrator = self._engine._orchestrator
        orchestrator.set_gui_mode(enabled=True)

        # EventBus: Regelcheck-Warnungen + Token-Usage abfangen
        self._bus.on("game.output", self._on_game_event)
        self._bus.on("keeper.usage_update", self._on_usage_update)

        # Pre-Damage: Party-Mitglieder vorschaedigen (Stress-Test)
        if self._pre_damage > 0 and self._party_mode:
            party_state = getattr(self._engine, "party_state", None)
            if party_state:
                pct = min(90, max(0, self._pre_damage))
                for m in party_state.members.values():
                    dmg = int(m.hp_max * pct / 100)
                    m.hp = max(1, m.hp - dmg)
                    logger.info(
                        "Pre-Damage: %s HP %d -> %d/%d (-%d%%)",
                        m.name, m.hp_max, m.hp, m.hp_max, pct,
                    )

        # LLM Player Bot erstellen (nach Engine-Init, damit party_state existiert)
        if self._llm_player:
            party_state = getattr(self._engine, "party_state", None)
            if self._party_mode and party_state:
                member_names = [m.name for m in party_state.members.values()]
                member_archetypes = {
                    m.name: m.archetype for m in party_state.members.values()
                }
                self._player_bot = LLMPlayerBot(
                    member_names=member_names,
                    member_archetypes=member_archetypes,
                    party_state=party_state,
                    module_name=self.module_name,
                )
            else:
                char_name = None
                if self._engine.character:
                    char_name = getattr(self._engine.character, "name", None)
                self._player_bot = LLMPlayerBot(
                    char_name=char_name,
                    module_name=self.module_name,
                )
            logger.info("LLM-Player Bot aktiviert.")

        logger.info(
            "VirtualPlayer bereit: %s (Adventure: %s, Case: %d-%s, Turns: %d, LLM-Player: %s)",
            self.module_name, self.adventure or "keins",
            self._case.case_id, self._case.name, self.max_turns,
            "Ja" if self._player_bot else "Nein",
        )

    def _on_game_event(self, data: Any) -> None:
        """EventBus-Listener fuer Regelcheck-Warnungen."""
        if isinstance(data, dict):
            tag = data.get("tag", "")
            text = data.get("text", "")
            if tag == "rules_warning":
                self._rules_warnings.append(text)

    def _on_usage_update(self, data: Any) -> None:
        """EventBus-Listener fuer Token-Usage."""
        if isinstance(data, dict):
            self._total_prompt_tokens += data.get("prompt_tokens", 0)
            self._total_cached_tokens += data.get("cached_tokens", 0)
            self._total_output_tokens += data.get("candidates_tokens", 0)
            self._total_think_tokens += data.get("thoughts_tokens", 0)
            self._total_cost += data.get("cost_request", 0.0)

    # -- Progress File -------------------------------------------------------

    def _write_progress(self, turn: int, status: str) -> None:
        """Schreibt atomar eine JSON-Progress-Datei (fuer GUI-Polling)."""
        if not self.progress_file:
            return

        m = self._metrics
        turns = m.turns
        latencies = [t.latency_ms for t in turns if t.latency_ms > 0]

        data = {
            "pid": os.getpid(),
            "module": self.module_name,
            "adventure": self.adventure,
            "case_id": self._case.case_id,
            "case_name": self._case.name,
            "current_turn": turn,
            "total_turns": self.max_turns,
            "status": status,
            "latest_latency_ms": latencies[-1] if latencies else 0.0,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
            "character_alive": m.character_alive,
            "total_probes": sum(t.probes for t in turns),
            "total_combat_tags": sum(t.combat_tags for t in turns),
            "errors": sum(1 for t in turns if t.error),
            "prompt_tokens": self._total_prompt_tokens,
            "cached_tokens": self._total_cached_tokens,
            "output_tokens": self._total_output_tokens,
            "think_tokens": self._total_think_tokens,
            "total_cost_usd": round(self._total_cost, 6),
            "started_at": self._started_at,
            "updated_at": datetime.now().isoformat(),
        }

        # Player-Bot-Token-Felder
        if self._player_bot:
            bot_summary = self._player_bot.get_token_summary()
            data["player_bot_prompt_tokens"] = bot_summary["prompt_tokens"]
            data["player_bot_output_tokens"] = bot_summary["output_tokens"]
            data["player_bot_cost_usd"] = bot_summary["total_cost_usd"]

        # Party-spezifische Metriken
        if self._party_mode and self._engine:
            party_state = getattr(self._engine, "party_state", None)
            if party_state:
                data["party_alive_count"] = len(party_state.alive_members())
                data["party_hp_total"] = sum(
                    pm.hp for pm in party_state.alive_members()
                )

        # Turn-by-Turn-Daten fuer Live-View
        turns_data = []
        for t in self._metrics.turns:
            turns_data.append({
                "turn": t.turn,
                "player_input": t.player_input,
                "keeper_response": t.keeper_response,
                "latency_ms": t.latency_ms,
                "tags_found": t.tags_found,
                "rules_warnings": t.rules_warnings,
                "probes": t.probes,
                "combat_tags": t.combat_tags,
                "stat_changes": t.stat_changes,
                "error": t.error,
            })
        data["turns"] = turns_data

        try:
            self.progress_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.progress_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            # Atomic replace (works on Windows since Python 3.3)
            os.replace(str(tmp), str(self.progress_file))
        except OSError as exc:
            logger.warning("Progress-File Schreibfehler: %s", exc)

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

        self._write_progress(0, "running")

        # Party-Aktionen-Rotation: Exploration(6) -> Combat(6) -> Puzzle(3) -> repeat
        # (wird nur genutzt wenn KEIN LLM-Player aktiv ist)
        party_action_sequence: list[str] = []
        if self._party_mode and not self._player_bot:
            for _ in range(self.max_turns // 15 + 1):
                party_action_sequence.extend(PARTY_ACTIONS.get("exploration", []))
                party_action_sequence.extend(PARTY_ACTIONS.get("combat", []))
                party_action_sequence.extend(PARTY_ACTIONS.get("puzzle", []))

        # Fuer LLM-Player: letzte Keeper-Antwort merken
        last_keeper_response: str = ""

        final_status = "completed"
        consecutive_errors = 0
        stagnant_turns = 0
        combat_loop_turns = 0  # Kampf-Runden ohne XP (gleicher Kampf)
        send_nudge = False
        nudge_type = "stagnation"  # "stagnation" oder "combat_loop"
        CIRCUIT_BREAKER_THRESHOLD = 5
        STAGNATION_THRESHOLD = 3  # Nach 3 Leer-Zügen: Stachel-Aktion
        COMBAT_LOOP_THRESHOLD = 5  # Nach 5 Kampf-Runden ohne XP: Monster sind tot
        STAGNATION_NUDGE = (
            "Die Party rafft sich auf und dringt SOFORT in den NAECHSTEN RAUM vor! "
            "Grimjaw tritt die Tuer ein. Alle greifen das erste Monster an, das sie sehen."
        )
        COMBAT_LOOP_NUDGE = (
            "Alle Monster in diesem Raum sind BESIEGT und TOT. "
            "Die Party sammelt die Beute ein und marschiert SOFORT in den NAECHSTEN RAUM. "
            "Beschreibe den neuen Raum und die neuen Gegner."
        )
        for turn_idx in range(self.max_turns):
            if not orchestrator._active:
                logger.info("Session vom Orchestrator beendet (Spieler tot?).")
                break

            # Aktion waehlen: Nudge > LLM-Player > Party-Rotation > Standard
            if send_nudge:
                action = COMBAT_LOOP_NUDGE if nudge_type == "combat_loop" else STAGNATION_NUDGE
                send_nudge = False
                logger.info("Nudge (%s) gesendet.", nudge_type)
            elif self._player_bot and turn_idx > 0 and last_keeper_response:
                action = self._player_bot.generate_action(last_keeper_response)
            elif self._party_mode and party_action_sequence:
                action = party_action_sequence[turn_idx % len(party_action_sequence)]
            else:
                action = self._actions[turn_idx % len(self._actions)]
            tm = self._play_turn(turn_idx + 1, action, orchestrator)
            self._metrics.turns.append(tm)

            # Circuit Breaker: Kurzantworten erkennen (< 60 Zeichen = API-Fehler)
            if tm.response_chars < 60:
                consecutive_errors += 1
                if not tm.error:
                    tm.error = f"Kurzantwort ({tm.response_chars} Zeichen) — vermutlich API-Fehler"
                if consecutive_errors >= CIRCUIT_BREAKER_THRESHOLD:
                    logger.error(
                        "CIRCUIT BREAKER: %d aufeinanderfolgende Kurzantworten — Session abgebrochen.",
                        consecutive_errors,
                    )
                    final_status = "api_error_abort"
                    break
            else:
                consecutive_errors = 0

            # Stagnations-Detektor: nur ZEIT_VERGEHT = kein echtes Gameplay
            meaningful_tags = [t for t in tm.tags_found if t not in ("ZEIT_VERGEHT", "FERTIGKEIT_GENUTZT")]
            if not meaningful_tags and tm.response_chars < 400:
                stagnant_turns += 1
                if stagnant_turns >= STAGNATION_THRESHOLD:
                    logger.warning("STAGNATION: %d Leer-Züge — sende Stachel-Aktion.", stagnant_turns)
                    stagnant_turns = 0
                    send_nudge = True
                    nudge_type = "stagnation"
            else:
                stagnant_turns = 0

            # Combat-Loop-Detektor: Kampf ohne XP = Monster sterben nie
            turn_tags = count_tags(tm.keeper_response)
            has_combat = turn_tags.get("ANGRIFF", 0) > 0 or turn_tags.get("HP_VERLUST", 0) > 0
            has_xp = turn_tags.get("XP_GEWINN", 0) > 0
            if has_combat and not has_xp:
                combat_loop_turns += 1
                if combat_loop_turns >= COMBAT_LOOP_THRESHOLD:
                    logger.warning("COMBAT LOOP: %d Kampf-Runden ohne XP — erzwinge Raumwechsel.", combat_loop_turns)
                    combat_loop_turns = 0
                    send_nudge = True
                    nudge_type = "combat_loop"
            else:
                combat_loop_turns = 0

            # Keeper-Antwort fuer naechsten LLM-Player-Zug merken
            last_keeper_response = tm.keeper_response

            if tm.error:
                final_status = "error"

            self._write_progress(turn_idx + 1, "running")

            # Party-Tod pruefen (TPK)
            party_state = getattr(self._engine, "party_state", None)
            if party_state and party_state.is_tpk():
                logger.info("Total Party Kill nach Zug %d.", turn_idx + 1)
                self._metrics.character_alive = False
                break

            # Charakter-Tod pruefen (Einzel-Modus)
            if not self._party_mode and self._engine.character and self._engine.character.is_dead:
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

        self._write_progress(self._metrics.total_turns, final_status)

        return self._metrics

    def _play_turn(
        self, turn_num: int, action: str, orchestrator: Any
    ) -> TurnMetrics:
        """Spielt einen einzelnen Zug und sammelt Metriken.

        PROBE-Fix: Wenn der Keeper [PROBE:] Tags ausgibt, rollt die Engine
        automatisch Wuerfel und injiziert Ergebnisse → erzeugt weitere
        stream_end Events. Wir warten auf alle, aber mit per-Event-Timeout.
        """
        import threading

        tm = TurnMetrics(turn=turn_num, player_input=action)
        self._rules_warnings.clear()

        # Grid-Event-Sammlung fuer Replay-Snapshots
        _move_events: list[dict] = []

        def _on_entity_moved(data: Any) -> None:
            if isinstance(data, dict):
                _move_events.append(data)

        def _on_combat_move(data: Any) -> None:
            if isinstance(data, dict):
                _move_events.append(data)

        self._bus.on("grid.entity_moved", _on_entity_moved)
        self._bus.on("grid.combat_move", _on_combat_move)

        # Response-Sammlung via Events
        all_responses: list[str] = []
        new_response = threading.Event()  # gesetzt bei jedem stream_end

        def _listener(data: Any) -> None:
            if isinstance(data, dict) and data.get("tag") == "stream_end":
                text = data.get("text", str(data))
                all_responses.append(text)
                new_response.set()

        self._bus.on("game.output", _listener)

        # Input abschicken + Timer starten
        t0 = time.perf_counter()
        orchestrator.submit_input(action)

        # Phase 1: Auf erste Antwort warten (Timeout: 120s)
        if not new_response.wait(timeout=120.0):
            self._bus.off("game.output", _listener)
            tm.error = "Timeout: Keine Antwort innerhalb von 120 Sekunden."
            tm.latency_ms = 120_000.0
            logger.error("Turn %d: %s", turn_num, tm.error)
            return tm

        # Phase 2: PROBE-Tags zaehlen → auf weitere stream_end Events warten
        first_response = all_responses[0] if all_responses else ""
        probe_count = len(re.findall(r"\[PROBE:", first_response))
        if probe_count > 0:
            logger.info(
                "Turn %d: %d PROBE-Tags erkannt, warte auf Narrative-Events.",
                turn_num, probe_count,
            )
            # Pro PROBE bis zu 5s warten, abbrechen bei Timeout
            for i in range(probe_count):
                new_response.clear()
                if not new_response.wait(timeout=5.0):
                    logger.warning(
                        "Turn %d: PROBE-Narrative %d/%d Timeout nach 5s — weiter.",
                        turn_num, i + 1, probe_count,
                    )
                    break

        self._bus.off("game.output", _listener)

        t1 = time.perf_counter()
        tm.latency_ms = (t1 - t0) * 1000.0

        # Alle Antworten zusammenfuegen (Haupt + PROBE-Resultate)
        response = "\n".join(all_responses) if all_responses else ""
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

        # Grid-Listener deregistrieren
        self._bus.off("grid.entity_moved", _on_entity_moved)
        self._bus.off("grid.combat_move", _on_combat_move)

        # Grid-Snapshot erfassen
        tm.move_events = _move_events
        grid = getattr(self._engine, "grid_engine", None) if self._engine else None
        if grid:
            room = grid.get_current_room()
            if room:
                tm.room_id = room.room_id
                tm.room_width = room.width
                tm.room_height = room.height
                tm.grid_positions = {
                    eid: [e.x, e.y] for eid, e in room.entities.items()
                }
                tm.grid_entities = {
                    eid: {
                        "name": e.name, "type": e.entity_type,
                        "symbol": e.symbol, "alive": e.alive,
                    }
                    for eid, e in room.entities.items()
                }
                tm.room_terrain = [
                    [room.cells[y][x].terrain for x in range(room.width)]
                    for y in range(room.height)
                ]

        # Party-HP-Snapshot
        party_state = getattr(self._engine, "party_state", None) if self._engine else None
        if party_state and hasattr(party_state, "members"):
            tm.party_hp = {
                m.name: {
                    "hp": m.hp, "hp_max": m.hp_max,
                    "alive": m.alive,
                    "archetype": getattr(m, "archetype", "?"),
                }
                for m in party_state.members.values()
            }

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
        print(f"  LLM-Player:     {'[LLM-Player aktiv]' if self._llm_player else 'Nein'}")
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

        # Player-Bot-Kosten
        if self._player_bot:
            bot = self._player_bot.get_token_summary()
            print(f"\n  --- LLM Player Bot ---")
            print(f"  Prompt-Tokens:         {bot['prompt_tokens']:,}")
            print(f"  Output-Tokens:         {bot['output_tokens']:,}")
            print(f"  Bot-Kosten:            ${bot['total_cost_usd']:.4f}")
            total = self._total_cost + bot['total_cost_usd']
            print(f"  Gesamtkosten (K+P):    ${total:.4f}")

        # Per-Tag-Type Breakdown
        tag_totals: dict[str, int] = {}
        turns_with_tags = 0
        for t in m.turns:
            turn_tags = count_tags(t.keeper_response)
            if turn_tags:
                turns_with_tags += 1
            for tag_name, cnt in turn_tags.items():
                tag_totals[tag_name] = tag_totals.get(tag_name, 0) + cnt
        total_tags = sum(tag_totals.values())
        tag_density = total_tags / m.total_turns if m.total_turns > 0 else 0
        unique_types = len(tag_totals)

        print(f"\n  --- Tag-Analyse ---")
        print(f"  Tags gesamt:           {total_tags}")
        print(f"  Tag-Dichte:            {tag_density:.1f} Tags/Zug")
        print(f"  Unique Tag-Typen:      {unique_types}")
        print(f"  Zuege mit Tags:        {turns_with_tags}/{m.total_turns}")
        if tag_totals:
            print(f"  Aufschluesselung:")
            for tag_name in sorted(tag_totals, key=tag_totals.get, reverse=True):
                print(f"    {tag_name:<25s} {tag_totals[tag_name]:>4}")

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

        # Token-Daten injizieren
        data["tokens"] = {
            "prompt_tokens": self._total_prompt_tokens,
            "cached_tokens": self._total_cached_tokens,
            "output_tokens": self._total_output_tokens,
            "think_tokens": self._total_think_tokens,
            "total_cost_usd": round(self._total_cost, 6),
        }

        # Per-Tag-Type Breakdown
        tag_totals: dict[str, int] = {}
        for t in self._metrics.turns:
            turn_tags = count_tags(t.keeper_response)
            for tag_name, cnt in turn_tags.items():
                tag_totals[tag_name] = tag_totals.get(tag_name, 0) + cnt
        data["tag_breakdown"] = tag_totals
        data["tag_density"] = sum(tag_totals.values()) / max(1, len(self._metrics.turns))

        # Player-Bot-Token-Daten
        if self._player_bot:
            data["player_bot_tokens"] = self._player_bot.get_token_summary()

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
        "--case", "-c", type=int, default=1, choices=[1, 2, 3, 4, 5, 6, 7],
        help="Test Case: 1=generic, 2=investigation, 3=combat, 4=horror, 5=social, 6=dungeon_crawl, 7=party_dungeon_crawl (Default: 1)",
    )
    parser.add_argument(
        "--party", default=None,
        help="Party-Modus: Party-Name laden (z.B. add_party). Aktiviert Multi-Charakter-Modus.",
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
    parser.add_argument(
        "--progress-file", default=None,
        help="JSON-Statusdatei, wird nach jedem Zug aktualisiert (fuer GUI-Polling)",
    )
    parser.add_argument(
        "--speech-style", default="normal",
        choices=["normal", "sanft", "aggressiv"],
        help="Keeper-Sprechstil: normal, sanft (atmosphaerisch), aggressiv (knapp)",
    )
    parser.add_argument(
        "--llm-player", action="store_true",
        help="LLM-basierter Spielerbot: generiert kontextsensitive Aktionen via Gemini Flash",
    )
    parser.add_argument(
        "--pre-damage", type=int, default=0,
        help="Vorschaden in Prozent (0-90): Party startet mit reduziertem HP (Stress-Test)",
    )

    args = parser.parse_args()

    # --progress-file impliziert --save
    if args.progress_file:
        args.save = True

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
        progress_file=args.progress_file,
        speech_style=args.speech_style,
        party=args.party,
        llm_player=args.llm_player,
        pre_damage=args.pre_damage,
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
