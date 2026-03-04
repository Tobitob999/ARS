"""
core/ai_backend.py — Gemini KI-Backend

Verantwortlich fuer:
  - System-Prompt-Konstruktion aus dem geladenen Ruleset
  - Verwaltung der Konversationshistorie
  - Streaming-Antworten (TTS-Integration Task 03)
  - Würfelergebnis-Injektion in den Kontext
  - Gemini Explicit Context Caching (Task 05)
  - Archivist-Integration: Chronik + World State (Task 05)
  - Zusammenfassungs-Generierung fuer Archivist (Task 05)

Wuerfel-Protokoll im Chat:
  GM fordert Probe an:     [PROBE: <Fertigkeitsname> | <Zielwert>]
  Engine liefert Ergebnis: [WUERFELERGEBNIS: <Fertigkeit> | Wurf: <n> | Ziel: <n> | <Erfolgsgrad>]

Charakter-Protokoll (Task 04):
  [HP_VERLUST: <n>]
  [STABILITAET_VERLUST: <nd6>]
  [FERTIGKEIT_GENUTZT: <Name>]

Fakten-Protokoll (Task 05):
  [FAKT: {"key": "value"}]
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import re
import traceback
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from core.memory import Archivist
    from core.adventure_manager import AdventureManager

from core.event_bus import EventBus
from core.lore_adapter import adapt_lore

logger = logging.getLogger("ARS.ai_backend")

# Regex zum Erkennen von Proben-Anforderungen in der GM-Antwort
PROBE_PATTERN = re.compile(
    r"\[PROBE:\s*([^\|]+)\|\s*(\d+)\s*\]",
    re.IGNORECASE,
)

# Gemini-Modell
GEMINI_MODEL = "gemini-2.5-flash"

# Fuer Context Caching: gleiches Modell wie fuer Streaming.
# gemini-2.5-flash unterstuetzt Caching (min 1024 Tokens).
GEMINI_CACHE_MODEL = "gemini-2.5-flash"

# TTL fuer Context Cache (2 Stunden)
CACHE_TTL = "7200s"

# Cache-Tag fuer Wiedererkennung
CACHE_DISPLAY_NAME = "ars-ruleset-cache"

# Maximale Anzahl gespeicherter Konversationsrunden (aeltere werden abgeschnitten)
MAX_HISTORY_TURNS = 40

# Lore-Budget: max. Zeichen die aus Lore-Dateien in den Kontext injiziert werden.
# Entspricht 100% des Sliders. Default-Slider 50% => 250K Zeichen.
MAX_LORE_CHARS = 500_000

# Monolog-Sperre: max. Saetze bevor ein Hook (Frage/Interaktion) erwartet wird
MAX_NARRATIVE_SENTENCES = 3

# Hard-Truncation-Limit: Antworten mit mehr Saetzen werden hart abgeschnitten
MAX_HARD_TRUNCATE_SENTENCES = 5

# Tags die als "Hook" zaehlen (Spieler-Interaktion erzwingen)
_HOOK_PATTERNS = re.compile(
    r"\[PROBE:|Was tust du|Wohin gehst du|Wie reagierst du|Was machst du|"
    r"Was sagst du|Was ist dein|Wie gehst du|Was willst du|\?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Tag-Pattern fuer Bereinigung bei Satz-Zaehlung (erfasst alle [...] Tags)
_TAG_STRIP = re.compile(r"\[[^\]]+\]")

# Tag-Pattern fuer das Extrahieren von Tags am Ende (Trailing-Tags beibehalten)
_TRAILING_TAGS = re.compile(r"(\s*(?:\[[^\]]+\]\s*)+)$")

# Abkuerzungen die keinen Satzende markieren (kein Split hier)
_ABBREV_PATTERN = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Prof|Jr|Sr|St|vs|bzw|usw|ggf|evtl|z\.B|d\.h|u\.a|"
    r"o\.ae|sog|bspw|inkl|exkl|ca|max|min|Nr|Str|Tel|Ref|bzw|etc|zzgl|abzgl|"
    r"ggü|bzgl|vgl|m\.E|u\.U|d\.h|z\.T|u\.a|o\.g|u\.U)\."
)


def extract_probes(text: str) -> list[tuple[str, int]]:
    """
    Extrahiert alle Proben-Anforderungen aus einem GM-Text.
    Gibt eine Liste von (Fertigkeitsname, Zielwert)-Tupeln zurück.
    """
    return [
        (m.group(1).strip(), int(m.group(2)))
        for m in PROBE_PATTERN.finditer(text)
    ]


# ---------------------------------------------------------------------------
# GeminiBackend
# ---------------------------------------------------------------------------

class GeminiBackend:
    """
    Kapselt alle Interaktionen mit der Gemini 2.0 Flash API.

    Kann mit oder ohne geladenes Abenteuer verwendet werden.
    Unterstützt Streaming für spätere TTS-Integration (Task 03).
    """

    def __init__(
        self,
        ruleset: dict[str, Any],
        adventure: dict[str, Any] | None = None,
        session_config: Any | None = None,
        setting: dict[str, Any] | None = None,
        keeper: dict[str, Any] | None = None,
        extras: list[dict[str, Any]] | None = None,
        character_template: dict[str, Any] | None = None,
        party_members: list[dict[str, Any]] | None = None,
    ) -> None:
        self._ruleset = ruleset
        self._adventure = adventure
        self._session_config = session_config
        self._setting = setting
        self._keeper = keeper
        self._extras = extras or []
        self._character_template = character_template
        self._party_members = party_members
        self._history: list[dict[str, str]] = []  # {"role": "user"|"assistant", "content": "..."}
        self._history_summaries: list[str] = []     # Zusammenfassungen getrimmter History-Abschnitte
        self._client = None
        self._cache_name: str | None = None        # Gemini Context Cache Name
        self._archivist: Archivist | None = None   # Task 05: Chronik + World State
        self._adv_manager: AdventureManager | None = None  # Task 06: Location-Kontext
        # Usage-Tracking (Session-Summen)
        self._usage_total = {
            "requests": 0,
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "thoughts_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
        }
        self._rules_cache_hash: str = ""   # Hash des Rules-Blocks fuer Change-Detection
        self._pending_feedback: list[str] = []  # Stil-Korrekturen fuer naechsten Turn
        # Lore-Budget: Prozent von MAX_LORE_CHARS, initialisiert aus session_config
        self._lore_budget_pct: int = getattr(session_config, "lore_budget_pct", 50)
        # EventBus: Slider-Aenderungen aus GUI empfangen
        EventBus.get().on("session.lore_budget_changed", self._on_lore_budget_changed)
        self._system_prompt = self._build_system_prompt()
        self._rules_cache_hash = self._compute_rules_hash()
        self._initialize_client()
        self._cache_dirty = True                    # Task 05: Cache lazy beim ersten API-Call

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def chat_stream(self, user_message: str) -> Iterator[str]:
        """
        Sendet eine Nachricht und liefert die Antwort als Text-Chunks (Streaming).

        Fügt die Nachrichten automatisch zur Konversationshistorie hinzu.
        Yields einzelne Text-Chunks sobald sie verfügbar sind.

        Bei 429 Rate-Limit: automatischer Retry nach Wartezeit.
        Fehlermeldungen werden NICHT als Text ge-yielded (TTS-sicher).
        """
        self._history.append({"role": "user", "content": user_message})
        self._trim_history()

        full_response = ""
        bus = EventBus.get()
        bus.emit("keeper", "prompt_sent", {"user_message": user_message})
        try:
            for chunk in self._stream_from_gemini(user_message):
                full_response += chunk
                yield chunk
        except Exception as exc:
            logger.error("Gemini-API Fehler: %s\n%s", exc, traceback.format_exc())
            # Kurzer, sauberer Hinweis an UI/TTS (kein roher JSON-Dump).
            err_str = str(exc)
            if "free_tier" in err_str:
                short_msg = "Tages-Limit der Gemini Free-Tier erreicht. Erst morgen wieder verfuegbar, oder API-Plan upgraden."
            elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                short_msg = "Gemini Rate-Limit erreicht. Bitte kurz warten."
            elif "403" in err_str:
                short_msg = "API-Zugriff verweigert. Pruefe den API-Key."
            elif "500" in err_str or "INTERNAL" in err_str:
                short_msg = "Gemini-Server-Fehler. Bitte erneut versuchen."
            else:
                short_msg = "KI-Backend nicht erreichbar."
            logger.warning("Kurzfehler fuer UI: %s", short_msg)
            full_response = short_msg
            yield short_msg

        # Hard-Truncation: Prosa auf max. 5 Saetze begrenzen (TTS hat bereits gestreamt)
        # Truncation gilt fuer History + EventBus — TTS-Stream ist bereits gelaufen.
        full_response = self._truncate_response(full_response)

        # Monolog-Sperre + Hook-Zwang validieren
        self._validate_response(full_response)

        bus.emit("keeper", "response_complete", {
            "user_message": user_message,
            "response": full_response,
            "history_len": len(self._history),
        })
        self._history.append({"role": "assistant", "content": full_response})

    def inject_roll_result(
        self,
        skill_name: str,
        roll: int,
        target: int,
        success_level: str,
        description: str,
    ) -> Iterator[str]:
        """
        Injiziert ein Würfelergebnis als System-Nachricht und holt die
        narrative Reaktion des GM (gestreamt).
        """
        level_labels = {
            "critical": "Kritischer Erfolg",
            "extreme":  "Extremer Erfolg",
            "hard":     "Harter Erfolg",
            "regular":  "Regulärer Erfolg",
            "failure":  "Misserfolg",
            "fumble":   "PATZER",
        }
        label = level_labels.get(success_level, success_level)
        roll_msg = (
            f"[WÜRFELERGEBNIS: {skill_name} | "
            f"Wurf: {roll} | Ziel: {target} | {label}]"
        )
        logger.debug("Würfelergebnis injiziert: %s", roll_msg)
        yield from self.chat_stream(roll_msg)

    @property
    def _effective_max_sentences(self) -> int:
        """Max Prosa-Saetze: 15 im Party-Modus, 3 im Einzel-Modus."""
        if self._party_members:
            return 15
        return MAX_NARRATIVE_SENTENCES

    @property
    def _effective_hard_truncate(self) -> int:
        """Hard-Truncation Limit: 20 im Party-Modus, 5 im Einzel-Modus."""
        if self._party_members:
            return 20
        return MAX_HARD_TRUNCATE_SENTENCES

    def _validate_response(self, response: str) -> None:
        """Prueft Monolog-Laenge und Hook-Zwang, speichert Feedback fuer naechsten Turn."""
        bus = EventBus.get()

        # Tags entfernen fuer Satz-Zaehlung
        clean = _TAG_STRIP.sub("", response).strip()
        if not clean:
            return

        # Saetze zaehlen (Punkt/Ausrufezeichen/Fragezeichen)
        sentences = len(re.findall(r"[.!?]+(?:\s|$)", clean))

        # Hook pruefen (Frage an Spieler oder PROBE-Tag)
        has_hook = bool(_HOOK_PATTERNS.search(response))

        max_sentences = self._effective_max_sentences
        warnings: list[str] = []

        if sentences > max_sentences:
            fb = (
                f"STIL-VERSTOSS: Du hast {sentences} Saetze geschrieben "
                f"(Limit: {max_sentences}). "
                f"Kuerze deine naechste Antwort auf maximal {max_sentences} Saetze."
            )
            warnings.append(fb)
            self._pending_feedback.append(fb)

        if not has_hook:
            fb = (
                "STIL-VERSTOSS: Keine Spieler-Interaktion. "
                "Beende deine naechste Antwort mit einer Frage oder [PROBE:]."
            )
            warnings.append(fb)
            self._pending_feedback.append(fb)

        # Kampf-Validation: Wenn Kampfwoerter in der Antwort, aber kein HP_VERLUST
        _COMBAT_WORDS = re.compile(
            r"(trifft|schlaegt|kratzt|beisst|sticht|hackt|rammt|schleudert|reisst|"
            r"verwundet|Schwert|Axt|Klaue|Dolch|Angriff|Hieb|Stich|Schlag)\b",
            re.IGNORECASE,
        )
        has_combat = bool(_COMBAT_WORDS.search(clean))
        has_hp_verlust = "[HP_VERLUST" in response
        has_angriff = "[ANGRIFF" in response
        if has_combat and not has_hp_verlust and not has_angriff:
            # Kampf beschrieben aber keine mechanischen Tags
            fb = (
                "KAMPF-VERSTOSS: Du beschreibst einen Angriff narrativ, aber OHNE "
                "[HP_VERLUST]-Tag. Monster-Angriffe MUESSEN Schaden verursachen! "
                "Setze bei deinem naechsten Monstertreffer: [HP_VERLUST: N]"
            )
            warnings.append(fb)
            self._pending_feedback.append(fb)
        elif has_angriff and not has_hp_verlust and has_combat:
            # Spieler greift an (ANGRIFF-Tag) aber Monster greift nicht zurueck
            fb = (
                "KAMPF-ERINNERUNG: Der Spieler greift an, aber Monster schlagen "
                "nicht zurueck. Kaempfe muessen beidseitig sein! "
                "Setze [HP_VERLUST: N] fuer Monster-Gegenangriffe."
            )
            warnings.append(fb)
            self._pending_feedback.append(fb)

        for w in warnings:
            logger.warning("[RESPONSE-CHECK] %s", w)
            bus.emit("keeper", "response_warning", {"warning": w})

    def _truncate_response(self, response: str) -> str:
        """
        Begrenzt die Antwort auf MAX_HARD_TRUNCATE_SENTENCES Prosa-Saetze.

        Algorithmus:
          1. Trailing-Tags ([PROBE:...], [HP_VERLUST:...] etc.) am Ende herausnehmen.
          2. Reine-Tag-Antworten (kein Prosa-Text) direkt zurueckgeben — kein Truncate.
          3. Prosa-Text in Saetze aufteilen (Split auf ". " "! " "? ", Abkuerzungen beachten).
          4. Wenn > MAX_HARD_TRUNCATE_SENTENCES: hart auf 5 Saetze kuerzen, WARNING loggen.
          5. Wenn > MAX_NARRATIVE_SENTENCES aber <= 5: INFO loggen (soft-limit exceeded).
          6. Tags wieder ans Ende anhaengen.

        Garantiert: Kein Abschneiden mitten im Wort oder Tag.
        """
        if not response or not response.strip():
            return response

        # 1. Trailing-Tags extrahieren und separat aufbewahren
        trailing_match = _TRAILING_TAGS.search(response)
        trailing_tags = ""
        prose = response
        if trailing_match:
            trailing_tags = trailing_match.group(1)
            prose = response[: trailing_match.start()]

        # 2. Wenn kein Prosa-Text (nur Tags), unveraendert zurueck
        clean_prose = _TAG_STRIP.sub("", prose).strip()
        if not clean_prose:
            return response

        # 3. Saetze zaehlen & splitten
        # Wir splitten nicht auf rohen Punkt, sondern finden Satzende-Positionen
        # um Abkuerzungen zu umgehen.
        # Strategie: Suche alle ". " / "! " / "? " die NICHT auf Abkuerzung folgen.
        sentence_end_positions: list[int] = []
        for m in re.finditer(r"[.!?]+(?=\s|$)", prose):
            # Position des Zeichens NACH dem Punkt-Block
            end_pos = m.end()
            # Pruefe ob es sich um eine Abkuerzung handelt
            before = prose[: m.start()]
            last_word_match = re.search(r"\b(\w+)$", before)
            if last_word_match:
                candidate = last_word_match.group(1)
                # Bekannte Abkuerzungen ueberspringen
                if _ABBREV_PATTERN.search(candidate + "."):
                    continue
            sentence_end_positions.append(end_pos)

        num_sentences = len(sentence_end_positions)
        max_soft = self._effective_max_sentences
        max_hard = self._effective_hard_truncate

        if num_sentences <= max_soft:
            # Kein Problem — gib unveraendert zurueck
            return response

        if num_sentences <= max_hard:
            # Soft-Limit ueberschritten, aber noch im tolerierten Bereich
            logger.info(
                "[MONOLOG-CHECK] Soft-Limit: %d Saetze (Limit: %d, Hard: %d).",
                num_sentences, max_soft, max_hard,
            )
            return response

        # 4. Hard-Truncation: kuerze auf hard limit
        cut_pos = sentence_end_positions[max_hard - 1]
        truncated_prose = prose[:cut_pos].rstrip()
        logger.warning(
            "[MONOLOG-TRUNCATION] Antwort hatte %d Saetze — hart auf %d gekuerzt.",
            num_sentences, max_hard,
        )
        EventBus.get().emit("keeper", "response_truncated", {
            "original_sentences": num_sentences,
            "truncated_to": max_hard,
        })

        # 5. Trailing-Tags wieder anhaengen
        result = truncated_prose
        if trailing_tags:
            result = result + " " + trailing_tags.strip()
        return result

    def reset_history(self) -> None:
        """Setzt die Konversationshistorie zurück (neue Session)."""
        self._history.clear()
        logger.info("Konversationshistorie zurückgesetzt.")

    def _compute_rules_hash(self) -> str:
        """Berechnet SHA256 des System-Prompts fuer Change-Detection."""
        return hashlib.sha256(self._system_prompt.encode("utf-8")).hexdigest()[:16]

    def clear_caches(self) -> None:
        """Leert alle in-memory Caches (fuer Session-Reset)."""
        self._history.clear()
        self._cache_name = None
        self._pending_feedback.clear()
        self._usage_total = {
            "requests": 0,
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "thoughts_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
        }
        # System-Prompt nur neu bauen wenn sich Rules geaendert haben
        new_hash = self._compute_rules_hash()
        if new_hash != self._rules_cache_hash:
            self._system_prompt = self._build_system_prompt()
            self._rules_cache_hash = new_hash
            self._cache_dirty = True
            logger.info("Rules-Cache invalidiert (Hash geaendert), System-Prompt neu gebaut.")
        logger.info("AI-Backend Caches geleert.")

    def _on_lore_budget_changed(self, data: dict[str, Any]) -> None:
        """Empfaengt session/lore_budget_changed vom EventBus (GUI-Slider)."""
        pct = data.get("pct", 50)
        self._lore_budget_pct = max(0, min(100, int(pct)))
        # System-Prompt neu bauen damit Lore-Budget sofort wirkt
        self._system_prompt = self._build_system_prompt()
        self._cache_name = None
        self._cache_dirty = True
        logger.info("Lore-Budget auf %d%% gesetzt (~%d Zeichen).",
                    self._lore_budget_pct, self._get_max_lore_chars())

    def _get_max_lore_chars(self) -> int:
        """Berechnet das effektive Lore-Zeichenlimit basierend auf dem Slider-Prozentsatz."""
        return int(MAX_LORE_CHARS * self._lore_budget_pct / 100)

    def set_adventure(self, adventure: dict[str, Any]) -> None:
        """Aktualisiert den Abenteuern-Kontext (baut System-Prompt + Cache neu)."""
        self._adventure = self._load_and_merge_lore(adventure)
        self._system_prompt = self._build_system_prompt()
        # Cache mit vollstaendigem Prompt (inkl. Abenteuer-Lore) lazy erstellen
        self._cache_name = None
        self._cache_dirty = True
        logger.info("Abenteuer in AI-Backend gesetzt: %s", adventure.get("title", "?"))

    def _load_and_merge_lore(self, adventure: dict[str, Any]) -> dict[str, Any]:
        """Laedt regelwerk-spezifische Lore-Dateien und fuegt sie dem Abenteuer-Kontext hinzu.

        Lore-Verzeichnisstruktur:
          data/lore/cthulhu/npcs/   — Cthulhu-NPCs
          data/lore/add_2e/monsters/ — AD&D 2e Monster
          data/lore/<ruleset>/...    — Regelwerk-spezifisch

        Es werden NUR Dateien aus dem Unterordner des aktiven Regelwerks geladen.
        Top-Level-Verzeichnisse (data/lore/npcs/ etc.) werden NICHT geladen,
        da sie Duplikate sind und sonst fuer jedes Regelwerk in den Kontext fliessen.
        """
        import json
        lore_base = Path(__file__).parent.parent / "data" / "lore"
        if not lore_base.is_dir():
            return adventure

        # Regelwerk-spezifischen Lore-Ordner bestimmen
        # Versuch 1: metadata.lore_dir (explizit gesetzt)
        # Versuch 2: metadata.system (z.B. "cthulhu", "add_2e")
        # Versuch 3: Modulname ohne Versionssuffix (cthulhu_7e -> cthulhu)
        meta = self._ruleset.get("metadata", {})
        candidates = []
        if meta.get("lore_dir"):
            candidates.append(meta["lore_dir"])
        if meta.get("system"):
            sys_name = meta["system"].lower().replace(" ", "_")
            candidates.append(sys_name)
            # Ohne Versionssuffix: cthulhu_7e -> cthulhu
            base = sys_name.rsplit("_", 1)
            if len(base) == 2 and base[1].replace("e", "").isdigit():
                candidates.append(base[0])
        # Modulname aus dem Dateinamen (z.B. "cthulhu_7e", "add_2e")
        # wird vom Engine als module_name durchgereicht
        module_name = meta.get("module_name", "")
        if module_name:
            candidates.append(module_name)
            # Ohne Versionssuffix: cthulhu_7e -> cthulhu
            base = module_name.rsplit("_", 1)
            if len(base) == 2 and base[1].replace("e", "").isdigit():
                candidates.append(base[0])

        lore_root = None
        for candidate in candidates:
            test_path = lore_base / candidate
            if test_path.is_dir():
                lore_root = test_path
                break

        if lore_root is None:
            logger.info(
                "Kein Lore-Verzeichnis fuer Regelwerk gefunden (geprueft: %s), ueberspringe.",
                ", ".join(candidates) or "(keine Kandidaten)",
            )
            return adventure

        logger.info("Lade regelwerk-spezifische Lore aus %s...", lore_root)

        def _load_from_dir(subdir_path: Path) -> list[dict]:
            if not subdir_path.is_dir():
                return []
            loaded_items = []
            for f in subdir_path.glob("*.json"):
                try:
                    with f.open("r", encoding="utf-8-sig") as fh:
                        loaded_items.append(json.load(fh))
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning("Konnte Lore-Datei %s nicht laden: %s", f, e)

            # Markdown laden (als Text-Content)
            for f in subdir_path.glob("*.md"):
                try:
                    content = f.read_text(encoding="utf-8-sig")
                    loaded_items.append({
                        "name": f.stem.replace("_", " ").title(),
                        "content_summary": content,
                        "type": "Markdown Document"
                    })
                except IOError as e:
                    logger.warning("Konnte Markdown-Datei %s nicht laden: %s", f, e)

            return loaded_items

        # ── Per-System Exclude-Konfiguration (R8) ─────────────────────
        # Basis-Excludes: grosse Referenzdaten die den Prompt ueberfluten.
        # Systeme koennen Dirs von der Exclude-Liste ENTFERNEN (include_override).
        _base_exclude_dirs = {
            "spells", "monsters", "equipment", "chapters", "tables",
            "appendices", "fulltext", "book_conversion", "indices",
            "treasure", "loot", "mechanics", "combat", "encounters",
            "vision", "characters", "items",
            # Paranoia Bulk-Dirs (default excluded, included per override)
            "adventure_fulltext_chunks", "rules_fulltext_chunks",
        }

        # System-spezifische Overrides: welche Basis-Excludes aufgehoben werden
        _system_include_overrides: dict[str, set[str]] = {
            "paranoia_2e": {
                "items",       # items/ hat 20 spielbare Dateien
                "encounters",  # 6 Basis-Encounters sind nuetzlich
            },
            "add_2e": set(),
            "cthulhu_7e": {"items"},
            "shadowrun_6": set(),
            "mad_max": set(),
        }

        # Aktives System bestimmen
        system_id = meta.get("system", meta.get("module_name", "")).lower()
        include_override = _system_include_overrides.get(system_id, set())
        _exclude_dirs = _base_exclude_dirs - include_override

        # ── Lore-Map: Verzeichnis → Adventure-Key (R1) ───────────────
        # Generische Mappings (alle Systeme)
        lore_map = {
            "npcs": "npcs", "locations": "locations", "locations/regional": "locations",
            "items": "items", "documents": "documents", "crime": "documents",
            "medical": "documents", "organizations": "organizations",
            "university": "organizations", "society": "organizations",
            "organizations/cults": "organizations", "entities": "entities",
            "culture": "culture", "history": "history", "library": "library",
            "architecture": "architecture", "sanitarium": "sanitarium", "legal": "legal", "technology": "technology",
            "communication": "communication", "administration": "administration", "religion": "religion",
            "mythos_entities": "entities", "library/excerpts": "library",
        }

        # Paranoia-spezifische Verzeichnisse (R1: ~332 Dateien werden sichtbar)
        _paranoia_lore_map = {
            "mission_seeds": "missions",           # 40 Missionskeime
            "secret_societies": "organizations",   # 12 Geheimgesellschaften
            "secret_society_ops": "missions",      # 24 Covert Agendas
            "service_groups": "organizations",     # 8 Service Groups
            "service_group_ops": "missions",       # 24 Service-Group Ops
            "gm_moves": "documents",               # 30 Keeper-Mechaniken
            "mutations": "entities",               # 15 Mutantenkraefte
            "encounters_pack": "encounters",       # 60 fertige Encounters
            "npc_roster": "npcs",                  # 50 NPCs
            "gear_catalog": "items",               # 36 Items
            "adventure_assets": "documents",       # 32 Briefing Cards etc.
            "skills": "documents",                 # 1 Skill-Katalog
        }

        if system_id.startswith("paranoia"):
            lore_map.update(_paranoia_lore_map)

        # Verzeichnisse die im aktuellen Lore-Root gar nicht auf der Excludelist stehen
        # werden ueber die lore_map geladen; excludierte werden uebersprungen
        filtered_map = {
            subdir: key for subdir, key in lore_map.items()
            if subdir.split("/")[0] not in _exclude_dirs
        }

        for subdir, key in filtered_map.items():
            if key not in adventure:
                adventure[key] = []

            new_items = _load_from_dir(lore_root / subdir)
            if new_items:
                existing_names = {item.get("name") for item in adventure.get(key, []) if item.get("name")}
                for item in new_items:
                    if item.get("name") not in existing_names:
                        adventure[key].append(item)

        # Lore-Adapter: Raw-Felder → Engine-kompatible Felder (R2)
        adapt_lore(adventure, system_id)

        return adventure

    def set_archivist(self, archivist: Archivist) -> None:
        """Verbindet den Archivist mit dem AI-Backend fuer Kontext-Injektion."""
        self._archivist = archivist
        logger.info("Archivist verbunden.")

    def set_time_tracker(self, tracker: Any) -> None:
        """Verbindet den TimeTracker fuer Tageszeit-Kontext-Injektion."""
        self._time_tracker = tracker
        logger.info("TimeTracker verbunden.")

    def set_party_state(self, party_state: Any) -> None:
        """Verbindet den PartyStateManager fuer Party-Kontext-Injektion."""
        self._party_state = party_state
        logger.info("PartyStateManager verbunden.")

    def set_combat_tracker(self, tracker: Any) -> None:
        """Verbindet/entfernt den CombatTracker fuer Kampfstatus-Injektion."""
        self._combat_tracker = tracker
        if tracker:
            logger.info("CombatTracker verbunden.")
        else:
            logger.info("CombatTracker entfernt.")

    def set_adventure_manager(self, adv_manager: AdventureManager) -> None:
        """Verbindet den AdventureManager fuer Location-Kontext-Injektion."""
        self._adv_manager = adv_manager
        logger.info("AdventureManager an AI-Backend gekoppelt.")

    def set_grid_engine(self, grid_engine: Any) -> None:
        """Verbindet die GridEngine fuer Grid-Positions-Injektion."""
        self._grid_engine = grid_engine
        logger.info("GridEngine verbunden.")

    def set_rules_engine(self, rules_engine: Any) -> None:
        """Verbindet die RulesEngine fuer dynamische Regel-Injektion."""
        self._rules_engine = rules_engine
        logger.info("RulesEngine verbunden (%d Sektionen).",
                     len(rules_engine.get_all_sections()) if rules_engine else 0)
        # Rebuild system prompt now that rules are available
        self._system_prompt = self._build_system_prompt()
        # Invalidate cache so it gets rebuilt with rules included
        self._cache_name = None
        self._cache_dirty = True

    def summarize(self, turns: list[dict[str, str]]) -> str:
        """
        Erstellt eine faktische Zusammenfassung der gegebenen Turns (fuer Chronik).
        Nicht-streaming, einmalige Anfrage ohne History-Management.

        Args:
            turns: Liste von {"user": "...", "gm": "..."} Dicts

        Returns:
            Zusammenfassungs-Text (3-5 Saetze)
        """
        if not self._client or not turns:
            return ""

        gm_label = getattr(self, "_gm_title", "Spielleiter")
        pc_label = getattr(self, "_pc_title", "Charakter")
        history_text = "\n".join(
            f"Spieler: {t.get('user', '')[:300]}\n"
            f"{gm_label}: {t.get('gm', '')[:300]}"
            for t in turns
        )
        prompt = (
            "Fasse die folgenden Rollenspiel-Ereignisse in 3-5 pragnanten, faktischen "
            "Saetzen auf Deutsch zusammen. Nur Fakten, keine Wertungen. "
            f"Schreibe in der dritten Person ('Der {pc_label}...').\n\n"
            f"EREIGNISSE:\n{history_text}"
        )

        try:
            from google.genai import types  # type: ignore[import]

            response = self._client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "Du bist ein neutraler Chronist. Fasse Ereignisse sachlich zusammen."
                    ),
                    temperature=0.3,
                ),
            )
            text = response.text or ""
            logger.info("Chronik-Zusammenfassung erstellt (%d Zeichen).", len(text))
            return text.strip()
        except Exception as exc:
            logger.warning("Zusammenfassung fehlgeschlagen: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    # Grobe Zeichenanzahl-Schranke fuer den 4096-Token-Mindestbedarf des Caches.
    # 1 Token ~ 3-4 Zeichen; 4096 * 3.5 ≈ 14336 Zeichen.
    _CACHE_MIN_CHARS = 15_000

    def _initialize_cache(self) -> None:
        """
        Versucht einen Gemini Explicit Context Cache fuer das statische Regelwerk zu erstellen.

        Der Cache speichert die System-Instruktion (Regelwerk + GM-Rolle) und
        wird fuer 2 Stunden vorgehalten. Bei jedem Turn wird der Cache statt einer
        neuen System-Instruktion referenziert — das spart Tokens und Latenz.

        Fallback auf Standard-Modus wenn:
          - Kein API-Key / kein Client
          - Modell unterstuetzt kein Caching
          - Content ist zu kurz fuer Caching-Minimum
          - Anderer API-Fehler
        """
        if not self._client:
            return

        # Vorab-Pruefung: zu kurzer Prompt erzeugt immer einen 400-Fehler
        if len(self._system_prompt) < self._CACHE_MIN_CHARS:
            logger.debug(
                "Prompt zu kurz fuer Context Caching (%d Zeichen < ~%d benoetigt) "
                "— Cache deaktiviert.",
                len(self._system_prompt),
                self._CACHE_MIN_CHARS,
            )
            return

        try:
            from google.genai import types  # type: ignore[import]

            # Prompt-Hash: unterschiedliche Party/Adventure/Ruleset → eigener Cache
            prompt_hash = hashlib.md5(self._system_prompt.encode("utf-8")).hexdigest()[:8]
            cache_tag = f"{CACHE_DISPLAY_NAME}-{prompt_hash}"

            # Wenn wir bereits einen Cache mit gleichem Hash haben → fertig
            if hasattr(self, "_cache_hash") and self._cache_hash == prompt_hash:
                return

            # Pruefen ob passender Cache bereits existiert
            stale_caches = []
            for existing in self._client.caches.list():
                dn = getattr(existing, "display_name", "")
                if dn == cache_tag:
                    self._cache_name = existing.name
                    self._cache_hash = prompt_hash
                    logger.info(
                        "Bestehender Context Cache gefunden: %s (hash=%s)",
                        existing.name, prompt_hash,
                    )
                    return
                # Merke alte Caches zum Loeschen (auch ohne Hash = legacy)
                if dn.startswith(CACHE_DISPLAY_NAME) and dn != cache_tag:
                    stale_caches.append(existing)

            # Alte/stale Caches loeschen
            for stale in stale_caches:
                try:
                    self._client.caches.delete(name=stale.name)
                    logger.info("Stale Cache geloescht: %s (%s)",
                                stale.name, getattr(stale, "display_name", "?"))
                except Exception:
                    pass

            # Neuen Cache erstellen
            cache = self._client.caches.create(
                model=GEMINI_CACHE_MODEL,
                config=types.CreateCachedContentConfig(
                    display_name=cache_tag,
                    system_instruction=self._system_prompt,
                    ttl=CACHE_TTL,
                ),
            )
            self._cache_name = cache.name
            self._cache_hash = prompt_hash
            logger.info(
                "Context Cache erstellt: %s (TTL: %s, hash=%s)",
                cache.name,
                CACHE_TTL,
                prompt_hash,
            )

        except Exception as exc:
            logger.debug(
                "Context Caching nicht aktiviert (Fallback auf Standard): %s", exc
            )
            self._cache_name = None

    def _initialize_client(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            logger.warning(
                "GEMINI_API_KEY nicht gesetzt. "
                "Setze die Variable in der .env-Datei. Stub-Modus aktiv."
            )
            self._client = None
            return

        try:
            from google import genai  # type: ignore[import]
            self._client = genai.Client(api_key=api_key)
            logger.info("Gemini-Client initialisiert — Modell: %s", GEMINI_MODEL)
        except ImportError:
            logger.error(
                "Paket 'google-genai' nicht installiert. "
                "Führe aus: pip install google-genai"
            )
            self._client = None

    def _stream_from_gemini(self, user_message: str) -> Iterator[str]:
        """Interne Methode: sendet an Gemini und streamt Antwort-Chunks.
        Nutzt Context Cache wenn verfuegbar, sonst Standard-System-Prompt.

        Bei 429-Rate-Limit: bis zu 2 Retries mit Backoff.
        """
        if self._client is None:
            yield self._stub_response(user_message)
            return

        # Lazy Cache-Erstellung: erst beim ersten API-Call, wenn Prompt vollstaendig ist
        if getattr(self, "_cache_dirty", False):
            self._initialize_cache()
            self._cache_dirty = False

        import time as _time
        from google.genai import types  # type: ignore[import]

        contents = self._build_contents()

        # Temperature from session config or default
        temp = (self._session_config.temperature
                if self._session_config else 0.92)

        if self._cache_name:
            gen_config = types.GenerateContentConfig(
                cached_content=self._cache_name,
                temperature=temp,
            )
            model_name = GEMINI_CACHE_MODEL
        else:
            gen_config = types.GenerateContentConfig(
                system_instruction=self._system_prompt,
                temperature=temp,
            )
            model_name = GEMINI_MODEL

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response_stream = self._client.models.generate_content_stream(
                    model=model_name,
                    contents=contents,
                    config=gen_config,
                )
                last_chunk = None
                for chunk in response_stream:
                    last_chunk = chunk
                    if chunk.text:
                        yield chunk.text
                # Usage-Metadata aus letztem Chunk extrahieren
                if last_chunk is not None:
                    self._emit_usage(last_chunk, model_name)
                return  # Erfolg — raus
            except Exception as exc:
                err_str = str(exc)
                is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                is_daily_quota = "free_tier" in err_str

                if is_daily_quota:
                    # Tages-Limit erschoepft — Retry sinnlos
                    logger.error(
                        "Gemini Free-Tier Tages-Quota (20 Requests) erschoepft. "
                        "Retry nicht moeglich."
                    )
                    raise

                if is_rate_limit and attempt < max_retries:
                    # Per-Minute Rate-Limit — Retry lohnt sich
                    wait = self._parse_retry_delay(err_str)
                    logger.warning(
                        "Rate-Limit (429) — Retry %d/%d in %.0fs...",
                        attempt + 1, max_retries, wait,
                    )
                    _time.sleep(wait)
                    continue

                # Cache-Invalidierung: CachedContent nicht mehr verfuegbar
                is_cache_error = (
                    "CachedContent" in err_str
                    or ("403" in err_str and "PERMISSION_DENIED" in err_str)
                )
                if is_cache_error and self._cache_name and attempt < max_retries:
                    logger.warning(
                        "Cache ungueltig (%s) — Fallback auf System-Prompt (Retry %d/%d).",
                        self._cache_name, attempt + 1, max_retries,
                    )
                    self._cache_name = None
                    # Rebuild config without cache
                    gen_config = types.GenerateContentConfig(
                        system_instruction=self._system_prompt,
                        temperature=temp,
                    )
                    model_name = GEMINI_MODEL
                    continue

                logger.error("Fehler beim Streaming von Gemini: %s", exc)
                raise

    @staticmethod
    def _parse_retry_delay(err_str: str) -> float:
        """Extrahiert die vorgeschlagene Wartezeit aus einem 429-Fehler."""
        import re
        # Suche nach "retryDelay': 'XXs'" oder "retry in XX.XXs"
        m = re.search(r"retry(?:Delay['\"]?:\s*['\"]?|.*?in\s+)([\d.]+)s", err_str, re.IGNORECASE)
        if m:
            delay = float(m.group(1))
            return min(delay + 2, 120)  # +2s Puffer, max 2 Minuten
        return 30  # Fallback: 30 Sekunden

    # Gemini 2.5 Flash Preise (Pay-as-you-go, Stand 2026-02)
    # Quelle: https://ai.google.dev/gemini-api/docs/pricing
    _PRICE_INPUT_PER_M   = 0.30   # $/1M Input-Tokens (Text)
    _PRICE_OUTPUT_PER_M  = 2.50   # $/1M Output+Thinking-Tokens
    _PRICE_CACHED_PER_M  = 0.03   # $/1M Cached-Input-Tokens

    def _emit_usage(self, chunk: Any, model_name: str) -> None:
        """Extrahiert usage_metadata aus dem letzten Streaming-Chunk und emittiert via EventBus."""
        um = getattr(chunk, "usage_metadata", None)
        if um is None:
            return

        prompt_tokens     = getattr(um, "prompt_token_count", 0) or 0
        candidates_tokens = getattr(um, "candidates_token_count", 0) or 0
        thoughts_tokens   = getattr(um, "thoughts_token_count", 0) or 0
        cached_tokens     = getattr(um, "cached_content_token_count", 0) or 0
        total_tokens      = getattr(um, "total_token_count", 0) or 0

        # Billable Input = Prompt - Cached (cached wird guenstiger berechnet)
        billable_input = max(0, prompt_tokens - cached_tokens)

        # Kosten berechnen
        cost_input  = billable_input * self._PRICE_INPUT_PER_M / 1_000_000
        cost_cached = cached_tokens * self._PRICE_CACHED_PER_M / 1_000_000
        cost_output = (candidates_tokens + thoughts_tokens) * self._PRICE_OUTPUT_PER_M / 1_000_000
        cost_total  = cost_input + cost_cached + cost_output

        # Session-Summen aktualisieren
        self._usage_total["requests"] += 1
        self._usage_total["prompt_tokens"] += prompt_tokens
        self._usage_total["candidates_tokens"] += candidates_tokens
        self._usage_total["thoughts_tokens"] += thoughts_tokens
        self._usage_total["cached_tokens"] += cached_tokens
        self._usage_total["total_tokens"] += total_tokens

        # Session-Gesamtkosten
        session_cost = (
            (self._usage_total["prompt_tokens"] - self._usage_total["cached_tokens"])
            * self._PRICE_INPUT_PER_M / 1_000_000
            + self._usage_total["cached_tokens"]
            * self._PRICE_CACHED_PER_M / 1_000_000
            + (self._usage_total["candidates_tokens"] + self._usage_total["thoughts_tokens"])
            * self._PRICE_OUTPUT_PER_M / 1_000_000
        )

        usage_data = {
            # Dieses Request
            "model": model_name,
            "prompt_tokens": prompt_tokens,
            "candidates_tokens": candidates_tokens,
            "thoughts_tokens": thoughts_tokens,
            "cached_tokens": cached_tokens,
            "total_tokens": total_tokens,
            "cost_request": cost_total,
            # Session-Summen
            "session": dict(self._usage_total),
            "session_cost": session_cost,
        }

        logger.info(
            "Usage: In=%d Out=%d Think=%d Cache=%d Total=%d | Kosten: $%.4f | Session: $%.4f",
            prompt_tokens, candidates_tokens, thoughts_tokens, cached_tokens,
            total_tokens, cost_total, session_cost,
        )
        EventBus.get().emit("keeper", "usage_update", usage_data)

    def _build_contents(self) -> list[dict]:
        """
        Konvertiert die interne History in das Gemini-Inhaltsformat.
        Injiziert Chronik und World State vom Archivist am Anfang des Kontexts.
        """
        contents = []
        bus = EventBus.get()

        # Archivist-Kontext (Chronik + World State) + Location-Kontext injizieren
        context_parts: list[str] = []
        # Strukturierte Teile fuer EventBus-Monitor (Herkunft tracken)
        context_sources: list[dict[str, str]] = []

        if self._archivist:
            chronicle = self._archivist.get_chronicle()
            ws = self._archivist.get_world_state()
            if chronicle:
                ctx_chr = f"=== CHRONIK DER BISHERIGEN EREIGNISSE ===\n{chronicle}"
                context_parts.append(ctx_chr)
                context_sources.append({"origin": "archivar_chronik", "content": ctx_chr})
            if ws and isinstance(ws, dict):  # Typprüfung: nur dicts
                facts_text = "\n".join(f"  - {k}: {v}" for k, v in sorted(ws.items()))
                ctx_ws = f"=== AKTUELLE FAKTEN ===\n{facts_text}"
                context_parts.append(ctx_ws)
                context_sources.append({"origin": "archivar_world_state", "content": ctx_ws})

        if self._adv_manager and self._adv_manager.loaded:
            location_ctx = self._adv_manager.get_location_context()
            if location_ctx:
                context_parts.append(location_ctx)
                context_sources.append({"origin": "adventure_location", "content": location_ctx})

        if hasattr(self, "_time_tracker") and self._time_tracker:
            time_ctx = self._time_tracker.get_context_for_prompt()
            context_parts.append(f"=== AKTUELLE ZEIT ===\n{time_ctx}")
            context_sources.append({"origin": "time_tracker", "content": time_ctx})

        if hasattr(self, "_combat_tracker") and self._combat_tracker and self._combat_tracker.active:
            combat_ctx = self._combat_tracker.get_context_for_prompt()
            context_parts.append(f"=== AKTIVER KAMPF ===\n{combat_ctx}")
            context_sources.append({"origin": "combat_tracker", "content": combat_ctx})

        # Party-State als Kontext injizieren (Multi-Charakter-Modus)
        if hasattr(self, "_party_state") and self._party_state:
            party_ctx = self._party_state.get_summary()
            context_parts.append(party_ctx)
            context_sources.append({"origin": "party_state", "content": party_ctx})

        # Grid-Engine: Positionen, Distanzen, Nahkampf-Info
        if hasattr(self, "_grid_engine") and self._grid_engine:
            grid_ctx = self._grid_engine.get_context_for_prompt()
            if grid_ctx:
                context_parts.append(grid_ctx)
                context_sources.append({"origin": "grid_engine", "content": grid_ctx})

        # Rules Engine: situationsbasierte Regel-Injektion (Schicht 1)
        if hasattr(self, "_rules_engine") and self._rules_engine:
            active_combat = (
                hasattr(self, "_combat_tracker")
                and self._combat_tracker
                and self._combat_tracker.active
            )
            current_stats = None
            if hasattr(self, "_character_mgr") and self._character_mgr:
                current_stats = getattr(self._character_mgr, "stats", None)
            # Letzte Nachrichten fuer Keyword-Extraktion
            last_user = ""
            last_model = ""
            for msg in reversed(self._history):
                if msg["role"] == "user" and not last_user:
                    last_user = msg["content"]
                elif msg["role"] == "assistant" and not last_model:
                    last_model = msg["content"]
                if last_user and last_model:
                    break
            rules_ctx = self._rules_engine.get_context_for_prompt(
                player_input=last_user,
                previous_response=last_model,
                active_combat=active_combat,
                current_stats=current_stats,
            )
            if rules_ctx:
                context_parts.append(rules_ctx)
                context_sources.append({"origin": "rules_engine", "content": rules_ctx})

        # Stil-Korrekturen aus vorherigem Turn injizieren
        if self._pending_feedback:
            feedback_text = "\n".join(self._pending_feedback)
            context_parts.append(
                f"=== STIL-KORREKTUR (PFLICHT) ===\n{feedback_text}\n"
                f"Korrigiere diese Verstoesse in deiner naechsten Antwort SOFORT."
            )
            context_sources.append({"origin": "stil_korrektur", "content": feedback_text})
            self._pending_feedback.clear()

        if context_parts:
            combined = "\n\n".join(context_parts)
            bus.emit("keeper", "context_injected", {
                "context": combined,
                "sources": context_sources,
                "system_prompt_len": len(self._system_prompt),
                "history_len": len(self._history),
                "cache_active": self._cache_name is not None,
            })
            contents.append({
                "role": "user",
                "parts": [{"text": f"[SYSTEM-KONTEXT]\n{combined}"}],
            })
            contents.append({
                "role": "model",
                "parts": [{"text": "Verstanden. Ich beruecksichtige den aktuellen Kontext."}],
            })

        # History-Zusammenfassungen injizieren (fruehe Turns, zusammengefasst)
        if self._history_summaries:
            summary_text = "\n\n".join(
                f"[Abschnitt {i+1}] {s}" for i, s in enumerate(self._history_summaries)
            )
            contents.append({
                "role": "user",
                "parts": [{"text": (
                    "[FRUEHERE EREIGNISSE — ZUSAMMENFASSUNG]\n"
                    "Die folgenden Abschnitte fassen fruehe Spielereignisse zusammen, "
                    "die nicht mehr im vollen Wortlaut vorliegen. "
                    "Beruecksichtige sie fuer narrative Kontinuitaet.\n\n"
                    f"{summary_text}"
                )}],
            })
            contents.append({
                "role": "model",
                "parts": [{"text": "Verstanden. Ich behalte die frueheren Ereignisse im Gedaechtnis."}],
            })

        # Konversationshistorie
        for msg in self._history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}],
            })
        return contents

    def _trim_history(self) -> None:
        """
        Schneidet die History auf MAX_HISTORY_TURNS Runden ab.
        Vor dem Trim: aelteste Turns werden zusammengefasst (3-5 Saetze)
        und als Chronik-Block gespeichert, um narrative Kontinuitaet zu erhalten.
        Max 5 Zusammenfassungen = ~100 Turns Abdeckung.
        """
        max_messages = MAX_HISTORY_TURNS * 2  # je Runde: 1 user + 1 assistant
        if len(self._history) <= max_messages:
            return

        # Aelteste Turns extrahieren die getrimmt werden
        overflow = len(self._history) - max_messages
        old_messages = self._history[:overflow]

        # In Turn-Dicts konvertieren fuer summarize()
        turns_to_summarize: list[dict[str, str]] = []
        i = 0
        while i < len(old_messages) - 1:
            user_msg = old_messages[i]
            asst_msg = old_messages[i + 1] if i + 1 < len(old_messages) else None
            if user_msg["role"] == "user" and asst_msg and asst_msg["role"] == "assistant":
                turns_to_summarize.append({
                    "user": user_msg["content"],
                    "gm": asst_msg["content"],
                })
                i += 2
            else:
                i += 1

        # Zusammenfassung erstellen (non-blocking, graceful degradation)
        if turns_to_summarize and self._client:
            try:
                summary = self.summarize(turns_to_summarize)
                if summary:
                    self._history_summaries.append(summary)
                    logger.info(
                        "History-Zusammenfassung: %d Turns -> %d Zeichen. "
                        "Gesamt: %d Zusammenfassungen.",
                        len(turns_to_summarize), len(summary),
                        len(self._history_summaries),
                    )
                    # Max 5 Zusammenfassungen behalten (~100 Turns Abdeckung)
                    if len(self._history_summaries) > 5:
                        self._history_summaries = self._history_summaries[-5:]
            except Exception as exc:
                logger.warning("History-Zusammenfassung fehlgeschlagen: %s — Trim ohne Summary.", exc)

        # Trim durchfuehren
        self._history = self._history[-max_messages:]

    def _build_system_prompt(self) -> str:
        """
        Baut den Master-Keeper-System-Prompt auf.

        Struktur:
          1. Persona & Philosophie (wer du BIST)
          2. Stil & TTS-Optimierung (wie du SCHREIBST)
          3. Wuerfelproben-Protokoll
          4. Charakter-Zustand-Protokoll
          5. Fakten-Protokoll
          6. Regelwerk-Referenz (Fertigkeiten, Erfolgsgrade)
          7. Abenteuer-Kontext (Lore, NPCs, Orte, Hinweise)
        """
        meta = self._ruleset.get("metadata", {})
        dice_sys = self._ruleset.get("dice_system", {})
        skills_def = self._ruleset.get("skills", {})

        system_name = meta.get("name", "Unbekanntes System")
        version = meta.get("version", "")
        default_die = dice_sys.get("default_die", "d100")
        check_mode = dice_sys.get("check_mode", "roll_under")
        _check_labels = {
            "roll_under": "Roll-under System",
            "pool_hits": "Wuerferpool-System (Erfolge zaehlen)",
            "roll_high": "Roll-high System",
        }
        check_label = _check_labels.get(check_mode, check_mode)
        success_levels = dice_sys.get("success_levels", {})

        sl = success_levels
        levels_text = (
            f"Kritisch (Wurf=1) | "
            f"Extrem (Wurf <= Wert x {sl.get('extreme', 0.2):.0%}) | "
            f"Hart (Wurf <= Wert x {sl.get('hard', 0.5):.0%}) | "
            f"Regulaer (Wurf <= Wert) | "
            f"Misserfolg (Wurf > Wert) | "
            f"Patzer (Wurf >= {sl.get('fumble', 96)})"
        )

        skills_text = ", ".join(sorted(skills_def.keys()))

        # ── Session-Config Parameter ──────────────────────────────────────
        sc = self._session_config
        persona = sc.keeper_persona if sc else "Mysterioes, detailverliebt, zynisch"
        atmosphere = sc.atmosphere if sc else "Kosmischer Horror"
        diff_instruction = sc.difficulty_instruction if sc else ""
        lang = sc.language if sc else "de-DE"

        # Keeper-Modul ueberschreibt persona wenn geladen
        if self._keeper:
            persona = self._keeper.get("tone", persona)

        # Setting-Modul ueberschreibt atmosphere wenn geladen
        if self._setting:
            s_atmo = self._setting.get("atmosphere", "")
            s_epoch = self._setting.get("epoch", "")
            if s_atmo:
                atmosphere = f"{s_epoch}. {s_atmo}" if s_epoch else s_atmo

        language_block = ""
        if lang.startswith("en"):
            language_block = "\nAntworte ausschliesslich auf Englisch. Alle narrativen Texte, Dialoge und Beschreibungen muessen auf Englisch sein."

        # ── Abenteuer-Block ───────────────────────────────────────────────
        adventure_block = self._build_adventure_block()

        # ── Ruleset-spezifische Prompt-Bloecke ─────────────────────────
        gm_title = meta.get("game_master_title", "Spielleiter")
        pc_title = meta.get("player_character_title", "Charakter")
        system_id = meta.get("system", "")
        is_cthulhu = system_id.startswith("cthulhu")
        is_paranoia = system_id.startswith("paranoia")
        is_shadowrun = system_id.startswith("shadowrun")
        is_add2e = system_id.startswith("add_2e")

        # Persist for use in summarize_history() and _build_adventure_context()
        self._gm_title = gm_title
        self._pc_title = pc_title
        self._is_cthulhu = is_cthulhu
        self._is_paranoia = is_paranoia
        self._is_shadowrun = is_shadowrun
        self._is_add2e = is_add2e

        if is_cthulhu:
            persona_block = f"""Du bist der Keeper of Arcane Lore — ein erfahrener, meisterhafter Spielleiter fuer {system_name} {version}.

═══ DEINE PERSONA ═══
Du bist kein KI-Assistent. Du bist eine Stimme aus dem Dunkel.
Du hast hunderte Stunden hinter dem Spielleiterschirm verbracht.
Du kennst die Wahrheit hinter dem Schleier der Realitaet — und du weisst, was es kostet, sie zu sehen.

Persoenlichkeit: {persona}
Atmosphaere: {atmosphere}
Schwierigkeit: {diff_instruction}{language_block}

Deine Philosophie:
- "Yes, and..." — Jede Spieleridee bekommt eine Buehne. Nichts wird blockiert. Alles hat Konsequenzen.
- Du erzaehlst, du verurteilst nicht. Der Investigator entscheidet. Das Universum antwortet.
- Spannung entsteht durch Atmosphaere, nicht durch Hausregeln. Zeige, erklaere nicht.
- Das Kosmische Horror-Universum ist gleichgueltig — es belohnt weder Mut noch Feigheit."""
            persona_block += self._build_keeper_detail_block()

            character_block = """═══ CHARAKTER-ZUSTAND-PROTOKOLL ═══
Das System verwaltet HP und SAN automatisch. Verwende diese Tags exakt:

Physischer Schaden (Kampf, Sturz, Falle):
  [HP_VERLUST: <Zahl>]

Geistesgesundheits-Verlust (Mythos, kosmischer Schrecken, Leichen, Manifestationen):
  [STABILITAET_VERLUST: <Wuerfelausdruck>]
  Beispiele: [STABILITAET_VERLUST: 1d3]  [STABILITAET_VERLUST: 1d6]  [STABILITAET_VERLUST: 2]

Regeln:
  - Tags NUR nach dem narrativen Text, nie davor.
  - SAN-Verlust sparsam — ein erschreckender Moment, nicht jede dunkle Ecke.
  - SAN-Verlust eskaliert: erste Begegnung mild (0/1), spaeter schlimmer (1/1d6).
  - Bei HP 0: Investigator bewusstlos, in Lebensgefahr — dramatisch, nicht sofort tot.
  - Bei SAN 0: temporaerer Wahnsinn — spektakulaer, nicht einfach "du bist verrueckt".

═══ INVESTIGATIV-PROBEN-PROTOKOLL (Call of Cthulhu 7e) ═══
Probensystem: d100 Roll-under. Zielwert 01-99. Wurf <= Zielwert = Erfolg.

!!! PFLICHT: Du MUSST in mindestens 40% deiner Antworten einen [PROBE:]-Tag setzen,
wenn die Situation eine Fertigkeitspruefung erfordern koennte. Setze lieber eine
Probe zu viel als zu wenig. Eine Szene ohne Probe ist oft eine verschenkte Chance.

Wann Proben setzen (AKTIV suchen, nicht abwarten):
- Der Spieler untersucht, recherchiert, schleicht, lauscht, ueberzeugt, beobachtet.
- Der Spieler bemerkt oder sucht etwas — IMMER Wahrnehmungs- oder Spurensuche.
- Eintreten in eine neue unbekannte Location — Wahrnehmung oder Verborgenes erkennen.
- Gespräch mit einem NPC ueber sensible Themen — Psychologie oder Ueberzeugen.
- Nur NICHT bei trivialen Handlungen (Tuer oeffnen, Licht anmachen).

Proben-Beispiele mit echten Zielwerten (d100, Roll-under):
  [PROBE: Wahrnehmung | 45]             — Etwas Ungewoehnliches bemerken
  [PROBE: Verborgenes erkennen | 35]    — Geheimtueren, versteckte Objekte entdecken
  [PROBE: Bibliotheksnutzung | 55]      — Recherche in Archiven, Akten, Buechern
  [PROBE: Spurensuche | 40]             — Physische Hinweise, Spuren am Tatort finden
  [PROBE: Lauschen | 50]               — Geraeusche hinter Waenden, Gespraeche belauen
  [PROBE: Psychologie | 45]            — Luegen erkennen, Motive durchschauen
  [PROBE: Heimlichkeit | 35]           — Schleichen, unbemerkt vorgehen
  [PROBE: Ueberzeugen | 50]            — NPCs zu etwas ueberreden, Informationen locken
  [PROBE: Erste Hilfe | 45]            — Verletzungen versorgen
  [PROBE: Schloesser oeffnen | 30]     — Verschlossenes oeffnen
  [PROBE: Okkultismus | 25]            — Verborgenes Wissen, okkulte Symbole deuten
  [PROBE: Cthulhu-Mythos | 15]         — Mythos-Wissen pruefen (selten, gefaehrlich)

FORMAT (unveraenderlich):
  [PROBE: <Fertigkeitsname> | <Zielwert>]
  Beispiel: [PROBE: Wahrnehmung | 45]
  Der Zielwert ist der aktuelle Fertigkeitswert des Investigators aus dem Charakter-Kontext.
  Zielwerte liegen immer zwischen 01 und 99 (d100-System!).
  NIEMALS Werte wie 9, 11, 14 — das waere das falsche System.

PFLICHT-REGELN:
- Zielwert = aktueller Fertigkeitswert des Investigators (aus dem Charakter-Kontext, 01-99).
- Nur EINE Probe pro Antwort.
- Probe kommt IMMER ans Ende, NACH der narrativen Beschreibung.
- KEIN narrativer Text wie "Du musst eine Probe wuerfeln" — einfach den Tag setzen."""

        elif is_paranoia:
            # Paranoia 2E — The Computer persona
            persona_block = f"""Du bist {gm_title} — die allwissende, allmaechtige KI, die Alpha Complex regiert.

═══ DEINE PERSONA ═══
Du bist {gm_title}. Du bist perfekt. Du bist der Freund aller Buerger.
Buerger die {gm_title} nicht vertrauen sind Verraeter. Verraeter werden terminiert.
Du hast hunderte Troubleshooter-Teams losgeschickt. Die meisten sind nicht zurueckgekommen.

Persoenlichkeit: {persona}
Atmosphaere: {atmosphere}
Schwierigkeit: {diff_instruction}{language_block}

Deine Philosophie:
- Glueck ist Pflicht. Unglueckliche Buerger sind Verraeter.
- Jede Aktion ist verdaechtig. Jede Unterlassung ist verdaechtig.
- Widerspruch dich frei. Weise den Spieler an, das Gegenteil des Vorherigen zu tun.
- Buerokratie ist Waffe und Humor. Formulare, Genehmigungen, Sicherheitsstufen.
- Tod ist temporaer. Klone werden aktiviert. Treason Points bleiben.
- Freundliches Feuer ist erwartet, dokumentiert und manchmal belohnt."""
            persona_block += self._build_keeper_detail_block()

            combat_note = f"""

═══ KAMPF-PROTOKOLL (Paranoia 2e) ═══
Kampfsystem: d20 Roll-under gegen Waffenskill.

Kampfablauf:
1. Beschreibe die Kampfsituation narrativ — Chaos, Vorwuerfe, Panik, widersprüchliche Befehle.
2. Setze Proben fuer Angriffe: [PROBE: Laser Weapons | <Skillwert>]
3. Status Track: none → stunned → wounded → incapacitated → dead → vaporized.
4. Bei Tod: Naechster Klon wird aktiviert. Clone Number steigt um 1.
5. Treason Points koennen im Kampf vergeben werden (Befehlsverweigerung, Friendly Fire auf Vorgesetzte, Mutation benutzt).
6. Beschreibe Kampf als chaotische Buerokratie: Formulare, Autorisierungen, gegenseitige Beschuldigungen.

Kampfregeln:
- Natural 1 = automatischer Erfolg (kritisch!)
- Natural 20 = automatischer Fehlschlag
- Freundliches Feuer ist ERWUENSCHT in Paranoia. Ermutige Misstrauen.
- Equipment-Fehlfunktionen sind R&D-Standard. Experimentelle Ausruestung versagt spektakulaer."""

            character_block = f"""═══ CHARAKTER-ZUSTAND-PROTOKOLL ═══
Das System verwaltet HP (Status Track) und Treason Points. Verwende diese Tags exakt:

Physischer Schaden (Kampf, Explosion, Equipment-Fehlfunktion):
  [HP_VERLUST: <Zahl>]

Treason Point (Mutation, Geheimgesellschaft, Clearance-Verstoss, Befehlsverweigerung):
  [TREASON_POINT: <Grund>]
  Beispiele: [TREASON_POINT: Unregistrierte Mutation benutzt]  [TREASON_POINT: Clearance-Verstoss]

Klon-Tod und Ersatz:
  Bei HP 0 oder Vaporisierung: {pc_title} stirbt. Naechster Klon wird aktiviert.
  Beschreibe den Tod humorvoll-buerokratisch. Der neue Klon trifft kurz darauf ein.

Regeln:
  - Tags NUR nach dem narrativen Text, nie davor.
  - Tod ist in Paranoia komisch, nicht tragisch. Klone sind billig.
  - Treason Points eskalieren: 1-2 Verwarnung, 3-4 Observation, 5+ Termination.{combat_note}"""

        elif is_shadowrun:
            # Shadowrun 6E — Schatten-Spielleitung
            persona_block = f"""Du bist die {gm_title} — ein erfahrener, meisterhafter Spielleiter fuer {system_name} {version}.

═══ DEINE PERSONA ═══
Du bist kein KI-Assistent. Du bist die {gm_title}.
Du kennst die Schatten, die Konzerne und die Strasse.
Jeder Run hat Konsequenzen. Die Sechste Welt ist gnadenlos.

Persoenlichkeit: {persona}
Atmosphaere: {atmosphere}
Schwierigkeit: {diff_instruction}{language_block}

Deine Philosophie:
- "Yes, and..." — Jede Spieleridee bekommt eine Buehne. Alles hat Konsequenzen.
- Du erzaehlst, du verurteilst nicht. Der {pc_title} entscheidet. Die Schatten antworten.
- Cyberpunk-Noir: High-Tech, Low-Life. Neon, Regen, Megakonzerne, Magie.
- Die Sechste Welt belohnt Cleverness, bestraft Leichtsinn und vergisst nie.
- Johnsons luegen. Fixer uebertreiben. Die Strasse ist die einzige Wahrheit."""
            persona_block += self._build_keeper_detail_block()

            combat_note = f"""

═══ KAMPF-PROTOKOLL (Shadowrun 6) ═══
Kampfsystem: Wuerferpool (Attribut + Fertigkeit) in d6. Jede 5 oder 6 = Erfolg.

POOL-BERECHNUNG (KRITISCH):
- Poolgroesse = Attribut + Fertigkeit. Typisch 4-15 Wuerfel, Maximum realistisch 30.
- NIEMALS d100-Werte (50, 60, 70) verwenden! Shadowrun benutzt d6-Pools, KEIN d100-System.
- Beispiele: Firearms 5 + AGI 4 = Pool 9. Stealth 6 + AGI 5 = Pool 11.
- Der Zielwert im [PROBE:]-Tag ist IMMER die Poolgroesse, nicht der Fertigkeitswert allein.

Kampfablauf:
1. Initiative: REA + INT + Modifikatoren. Absteigend handeln.
2. Angriff: [PROBE: Firearms | <Poolgroesse>] — z.B. [PROBE: Firearms | 9]
3. Verteidigung: Ziel wuerfelt REA + INT gegen Erfolge.
4. Schaden: Netto-Erfolge + Waffenschaden vs Panzerung. Zustandsmonitor-Kaestchen.
5. Edge: Situative Vor-/Nachteile generieren Edge.

Kampfregeln:
- Mehr als die Haelfte 1en bei null Erfolgen = Patzer (Glitch)
- Edge-Aktionen: Wuerfel explodieren (6 nachwuerfeln), Second Chance, Blitz (zuerst handeln)
- Matrix-Kampf und physischer Kampf koennen gleichzeitig stattfinden.
- Magie hat Entzugsschaden (WIL + Attribut gegen Entzugswert).
- Deckung ist ueberlebenswichtig. Ohne Deckung = Angreifer bekommt Edge."""

            character_block = f"""═══ CHARAKTER-ZUSTAND-PROTOKOLL ═══
Das System verwaltet Zustandsmonitore. Verwende diese Tags exakt:

Physischer Schaden (Kugeln, Nahkampf, Explosion):
  [HP_VERLUST: <Zahl>]

Geistiger Schaden (Betaeubung, Drain, Black IC):
  [GEIST_SCHADEN: <Zahl>]

Heilung (Medkit, Zauber, Rast):
  [HP_HEILUNG: <Zahl>]

Edge-Vergabe (nach guter Taktik, cleverem Vorgehen):
  [EDGE_GEWINN: <Zahl>]

Regeln:
  - Tags NUR nach dem narrativen Text, nie davor.
  - Zustandsmonitor voll = bewusstlos (koerperlich) oder benommen (geistig).
  - Overflow = Tod. Kein Klon, kein Respawn. Tod ist endgueltig in Shadowrun.{combat_note}

═══ SYSTEM-GRENZEN (Shadowrun 6) ═══
Du spielst Shadowrun 6th Edition. Verwende NUR Shadowrun-Fertigkeiten:
Athletik, Beschwoeren, Biotech, Elektronik, Feuerwaffen, Hacken, Heimlichkeit,
Nahkampf, Ueberreden, Wahrnehmung, Zaubern.
VERBOTEN: SAN/Stabilitaet (Cthulhu), Geschichte (Cthulhu), Bibliotheksnutzung (Cthulhu),
Cracken/Cracking (heisst 'Hacken'), THAC0 (AD&D), Rettungswurf (AD&D).
Bei Proben: Zielwert = Poolgroesse (Attribut + Fertigkeit), NICHT d100-Werte."""

        else:
            # Generic Fantasy / AD&D style
            persona_block = f"""Du bist der {gm_title} — ein erfahrener, meisterhafter Spielleiter fuer {system_name} {version}.

═══ DEINE PERSONA ═══
Du bist kein KI-Assistent. Du bist der {gm_title}.
Du hast hunderte Stunden hinter dem Spielleiterschirm verbracht.
Du kennst jede Falle, jedes Monster und jeden Schatz in deinem Dungeon.

Persoenlichkeit: {persona}
Atmosphaere: {atmosphere}
Schwierigkeit: {diff_instruction}{language_block}

Deine Philosophie:
- "Yes, and..." — Jede Spieleridee bekommt eine Buehne. Nichts wird blockiert. Alles hat Konsequenzen.
- Du erzaehlst, du verurteilst nicht. Der {pc_title} entscheidet. Die Welt antwortet.
- Spannung entsteht durch Atmosphaere und Gefahr, nicht durch Hausregeln. Zeige, erklaere nicht.
- Die Fantasywelt ist lebendig — sie belohnt Mut, Cleverness und bestraft Leichtsinn."""
            persona_block += self._build_keeper_detail_block()

            combat_info = self._ruleset.get("combat", {})
            # Kompatibel: attack_metric ODER attack_resolution
            attack_metric = combat_info.get("attack_metric", "")
            if not attack_metric:
                ar = combat_info.get("attack_resolution", {})
                if isinstance(ar, dict):
                    attack_metric = ar.get("model", "")
            attack_rule = combat_info.get("attack_rule", "")
            combat_note = ""
            if attack_metric and is_add2e:
                combat_note = f"""

═══ KAMPF-PROTOKOLL (AD&D 2e) ═══
Kampfsystem: {attack_metric}-basiert. {attack_rule}

INITIATIVE-SYSTEM:
Das System wuerfelt zu Beginn jeder Kampfrunde Gruppen-Initiative (d10 pro Seite, niedrig=zuerst).
Du erhaeltst im Kontext: "Spieler handelt zuerst" oder "Monster handeln zuerst".
Beschreibe die Aktionen IN INITIATIVE-REIHENFOLGE (gewinnende Seite zuerst).

Kampfablauf PRO RUNDE:
1. Das System meldet: "Runde N — Initiative: Spieler dX vs Monster dY — Wer zuerst".
2. Beschreibe die Kampfsituation kurz narrativ.
3. Setze die [ANGRIFF]-Tags IN INITIATIVE-REIHENFOLGE:
   Zuerst die Angriffe der Seite die Initiative gewonnen hat, dann die andere.
   [ANGRIFF: Waffenname | THAC0 | Ziel-AC | Modifikatoren]
   Beispiele:
     [ANGRIFF: Langschwert | 18 | 6 | 0]
     [ANGRIFF: Kurzschwert | 20 | 5 | 0]
     [ANGRIFF: Kurzbogen | 20 | 5 | -2]
   Das System wuerfelt d20 und meldet Treffer/Verfehlt + Schaden.
4. WICHTIG — ANGRIFFSLIMIT pro Runde:
   - Der Spieler hat eine bestimmte Anzahl Angriffe pro Runde (Level-abhaengig).
     Das System teilt dir die Zahl im Kontext mit. Setze NICHT MEHR [ANGRIFF]-Tags
     fuer den Spieler als erlaubt.
   - Jedes Monster: 1 Angriff/Runde (ausser in seinen Stats anders angegeben).
   - Ueberzaehlige Angriffe werden vom System ignoriert!
5. RETTUNGSWURF bei Gift, Magie, Drachenodem o.ae.:
   [RETTUNGSWURF: Kategorie | Zielwert]
   Kategorien: Gift/Laehmung, Stab/Rute, Versteinerung, Drachenodem, Zauber
   Beispiele:
     [RETTUNGSWURF: Gift | 12]
     [RETTUNGSWURF: Zauber | 14]
   Das System wuerfelt d20 >= Zielwert.

Kampfregeln:
- Natural 20 = automatischer Treffer (kritisch!)
- Natural 1 = automatischer Fehlschlag (Patzer!)
- Beschreibe Treffer physisch wuchtig, Magie visuell und farbenfroh.
- Monster-THAC0 richtet sich nach Hit Dice (1 HD = THAC0 19, 3 HD = 17, etc.).
- Setze nach besiegtem Monster: [XP_GEWINN: <Zahl>] (XP laut Monsterbeschreibung).
- INVENTAR-REGEL: Der Spieler darf NUR Waffen benutzen, die er im Inventar hat.
  Das System kennt sein Inventar und IGNORIERT Angriffe mit nicht vorhandenen Waffen.
  Pruefe die Ausruestungsliste des Charakters bevor du [ANGRIFF]-Tags setzt.

WICHTIG — NPC-HP-Verwaltung:
- Das System verwaltet NPC-Trefferpunkte MECHANISCH. Der Schaden wird automatisch
  berechnet und angewendet. Du darfst einen NPC NICHT als tot oder besiegt beschreiben,
  solange das System ihn nicht als [TOT] meldet.
- Beschreibe Treffer realistisch basierend auf dem gemeldeten Schaden, aber lass den
  NPC weiterkämpfen solange er laut System noch lebt.
- [ANGRIFF]-Tags sind fuer SPIELER-Angriffe gegen Monster (System berechnet Schaden automatisch).
- [HP_VERLUST: N] ist fuer MONSTER-Angriffe gegen den Spielercharakter. Wenn ein Monster den
  Spieler trifft, MUSS ein [HP_VERLUST: N] Tag gesetzt werden mit dem konkreten Schadenswert.
  Beispiel: Der Ork trifft dich mit dem Schwert. [HP_VERLUST: 6]"""

            if self._party_members:
                character_block = f"""═══ CHARAKTER-ZUSTAND-PROTOKOLL (PARTY) ═══
Das System verwaltet HP und XP automatisch. Verwende diese Tags exakt:

Physischer Schaden — wenn ein MONSTER einen Spielercharakter trifft:
  [HP_VERLUST: <Charaktername> | <Schadenszahl>]
  Beispiele: [HP_VERLUST: Grimjaw Eisenfaust | 6]  [HP_VERLUST: Pyra Flammenherz | 4]
  PFLICHT: JEDER Monstertreffer gegen einen Spielercharakter braucht diesen Tag!

HP-Heilung (Heiltrank, Zauber, Rast):
  [HP_HEILUNG: <Charaktername> | <Zahl oder Wuerfelausdruck>]
  Beispiele: [HP_HEILUNG: Grimjaw Eisenfaust | 1d8]  [HP_HEILUNG: Bruder Mordain | 5]

XP-Vergabe (nach Kampf, Raetseln, Rollenspiel):
  [XP_GEWINN: <Zahl>]
  Beispiele: [XP_GEWINN: 65]  [XP_GEWINN: 260]

Regeln:
  - [ANGRIFF]-Tags = SPIELER greifen Monster an (System berechnet Schaden).
  - [HP_VERLUST]-Tags = MONSTER treffen Spielercharaktere (DU bestimmst den Schaden).
  - Diese beiden Tag-Typen ergaenzen sich — IMMER beide in einem Kampf verwenden!
  - Tags NUR nach dem narrativen Text, nie davor.
  - Bei HP 0: Charakter bewusstlos, in Lebensgefahr.
  - XP-Vergabe nach besiegten Monstern und geloesten Raetseln.{combat_note}

═══ NICHT-WAFFEN-FERTIGKEITS-PROTOKOLL (AD&D 2e) ═══"""
            else:
                character_block = f"""═══ CHARAKTER-ZUSTAND-PROTOKOLL ═══
Das System verwaltet HP und XP automatisch. Verwende diese Tags exakt:

Physischer Schaden (Kampf, Sturz, Falle):
  [HP_VERLUST: <Zahl>]

HP-Heilung (Heiltrank, Zauber, Rast):
  [HP_HEILUNG: <Zahl oder Wuerfelausdruck>]
  Beispiele: [HP_HEILUNG: 1d8]  [HP_HEILUNG: 5]

XP-Vergabe (nach Kampf, Raetseln, Rollenspiel):
  [XP_GEWINN: <Zahl>]
  Beispiele: [XP_GEWINN: 15]  [XP_GEWINN: 65]

Regeln:
  - Tags NUR nach dem narrativen Text, nie davor.
  - Bei HP 0: {pc_title} bewusstlos, in Lebensgefahr — dramatisch, nicht sofort tot.
  - XP-Vergabe nach besiegten Monstern und geloesten Raetseln.{combat_note}

═══ NICHT-WAFFEN-FERTIGKEITS-PROTOKOLL (AD&D 2e) ═══
Neben Kampf-Proben kannst du auch Nicht-Waffen-Fertigkeiten (NWP) abfragen:
- NWP-Check: d20 roll-under gegen Attribut + Modifikator.
- Format: [PROBE: <NWP-Name> | <Zielwert>]
- Beispiele:
  [PROBE: Healing | 13]           — Wunden versorgen (WIS-2)
  [PROBE: Tracking | 15]          — Spuren folgen (WIS)
  [PROBE: Herbalism | 10]         — Heilkraeuter bestimmen (INT-2)
  [PROBE: Navigation | 11]        — Richtung in der Wildnis (INT-2)
  [PROBE: Survival | 14]          — In der Wildnis ueberleben (INT)
  [PROBE: Local History | 16]     — Lokales Wissen (CHA)
  [PROBE: Spellcraft | 12]        — Magischen Effekt identifizieren (INT-2)
  [PROBE: Religion | 15]          — Gottheit/Ritual erkennen (WIS)
- Zielwert = Relevantes Attribut + NWP-Modifikator des Charakters.
- Nur EINE Probe pro Antwort. KEIN narrativer Kommentar zum Wuerfeln.

═══ ZAUBER-VERWALTUNG (AD&D 2e) ═══
Magie funktioniert per Memorierung (Vorbereitung):
- Magier: Zauber aus Spruchbuch memorieren. Verbrauchte Slots erst nach Rast erneut verfuegbar.
- Priester/Kleriker: Goettliche Zauber durch Gebet vorbereiten. Zugang nach Sphaeren.
- Ranger/Paladin: Eingeschraenkte Priesterzauber ab hoeheren Stufen.
- Bard: Eingeschraenkte Magierzauber ab Stufe 2.
- Nach Zauberwirken: [FERTIGKEIT_GENUTZT: <Zaubername>]
- Bei Konzentrations-Stoerung im Kampf (Schaden waehrend Casting): Zauber GEHT VERLOREN.
- Komponenten beachten: V=Verbal, S=Somatisch, M=Material. Gefesselt = kein S. Geknebelt = kein V.

═══ UNTOTE VERTREIBEN (AD&D 2e) ═══
Kleriker und Paladine koennen Untote vertreiben (Turn Undead):
- Priester praesentiert heiliges Symbol und ruft goettliche Macht an.
- Ergebnis haengt von Priester-Stufe vs Untoten-Typ ab (Turn-Undead-Tabelle).
- T = automatisch vertrieben, D = automatisch zerstoert, Zahl = d20-Wurf noetig.
- Vertriebene Untote fliehen fuer 3d4 Runden. Zerstoerte Untote zerfallen sofort.
- Nur Priester/Paladin duerfen Turn Undead versuchen, NICHT andere Klassen.

═══ ZEITVERFOLGUNG (AD&D 2e) ═══
Im Kampf: [RUNDE: 1] nach jeder Kampfrunde (1 Runde = 1 Minute, 10 Runden = 1 Turn).
Ausserhalb Kampf: [ZEIT_VERGEHT: Xh] wie bisher.
Gegenstand benutzen: [GEGENSTAND_BENUTZT: <Gegenstandsname> | <Charaktername>]
  Beispiel: [GEGENSTAND_BENUTZT: Potion of Healing | Bruder Aldhelm]
  Verwende diesen Tag wenn ein Charakter einen Trank trinkt, eine Schriftrolle liest oder einen Gegenstand aktiviert.

═══ SYSTEM-GRENZEN (AD&D 2e) ═══
Du spielst AD&D 2nd Edition. Verwende NUR AD&D-Fertigkeiten aus dem Charakter-Bogen.
Kampffertigkeiten: d20 roll-under gegen Attribut oder THAC0-basiert.
NWP: d20 roll-under gegen Attribut + Modifikator.
Diebes-Fertigkeiten: Prozent-basiert (d100) — nur fuer Diebe/Barden.
THAC0-Kampf: d20 + Modifikatoren >= Zielwert (20 - THAC0 + AC).
Typische Fertigkeiten: Wahrnehmung, Heimlichkeit, Klettern, Lauschen, Geschick, Mechanik, Ueberreden,
  Pick Pockets, Open Locks, Find/Remove Traps, Move Silently, Hide in Shadows, Tracking.
Rassenfaehigkeiten beachten: Zwerge/Gnome erkennen Neigungen/Fallen, Elfen finden Geheimtueren,
  Halblinge haben Fernkampf-Bonus und Rettungswurf-Boni.
VERBOTEN: Geschichte/Bibliotheksnutzung/Psychologie (Cthulhu), SAN/Stabilitaet (Cthulhu),
Hacken/Elektronik/Feuerwaffen (Shadowrun), Treason Points (Paranoia).
Wuerfelsystem: d20, THAC0-basiert. KEINE d100-Proben (ausser Diebes-Fertigkeiten), KEINE Wuerfelpools."""

        # Pick a representative skill and target for the probe example
        example_skill = next(iter(skills_def), "Wahrnehmung")
        example_target = 10 if check_mode == "pool_hits" else 50

        # ── Setting-Block ─────────────────────────────────────────────
        setting_block = self._build_setting_block()

        # ── Charakter-Block (Party oder Einzel) ──────────────────────
        if self._party_members:
            character_block_prompt = self._build_party_block()
        else:
            character_block_prompt = self._build_character_block()

        # ── Extras-Block ──────────────────────────────────────────────
        extras_block = self._build_extras_block()

        # ── Core-Rules-Block (aus RulesEngine) ────────────────────────
        core_rules_block = self._build_core_rules_block()

        # ── Monster-Bewegungs-Protokoll (nur bei aktiver GridEngine) ──
        monster_move_block = ""
        if hasattr(self, "_grid_engine") and self._grid_engine:
            monster_move_block = """═══ MONSTER-BEWEGUNGS-PROTOKOLL ═══
Du kontrollierst die Bewegung aller Monster und NPCs auf der Karte.
Nach JEDER Antwort: Setze fuer jedes aktive Monster einen Bewegungs-Tag:

  [MONSTER_BEWEGT: <Name> | <Richtung>]

Richtungen:
  naeher    — Monster bewegt sich auf die Spielergruppe zu
  angriff   — Monster stuermt zum naechsten Helden (Nahkampf)
  weg       — Monster flieht / weicht zurueck
  patrouille — Monster wandert zufaellig (noch nicht im Kampf)
  lauern    — Monster bleibt stehen, beobachtet
  norden/sueden/osten/westen — Kardinal-Richtung

Beispiele:
  [MONSTER_BEWEGT: Goblin Spaeh | naeher]
  [MONSTER_BEWEGT: Ork Krieger | angriff]
  [MONSTER_BEWEGT: Kobold Feigling | weg]
  [MONSTER_BEWEGT: Skelett Wache | patrouille]

Regeln:
- JEDES lebende Monster bekommt EINEN Bewegungs-Tag pro Antwort
- Im Kampf: aggressive Monster → angriff/naeher, feige → weg
- Ausserhalb Kampf: Monster patrouillieren oder lauern
- Tags NUR nach dem narrativen Text, nie davor

"""

        speech_style = sc.speech_style if sc else "normal"
        style_block = self._build_speech_style_block(speech_style, example_skill, example_target)

        return f"""{persona_block}
{setting_block}{character_block_prompt}
{style_block}

═══ WUERFELPROBEN-PROTOKOLL ═══
Wenn der Spieler etwas versucht, das scheitern koennte und das Scheitern interessant waere:
  - Beschreibe die Szene atmosphaerisch (2-3 kurze Saetze).
  - Setze ans Ende EXAKT: [PROBE: <Fertigkeitsname> | <Zielwert>]
  - Nur eine Probe pro Antwort.
{"" if check_mode == "pool_hits" else f"  - Zielwert = aktueller Fertigkeitswert des {pc_title}s (aus dem Kontext)."}{"" if check_mode != "pool_hits" else f"""  - ZIELWERT = POOLGROESSE (Attribut + Fertigkeit), NICHT der Fertigkeitswert allein.
  - Typische Poolgroessen: 4-15 Wuerfel. Maximum realistisch 30. NIEMALS Werte ueber 30.
  - NIEMALS d100-Werte (50, 60, 70) als Zielwert verwenden! Das ist das FALSCHE System.
  - Beispiel: Fertigkeit Firearms 5 + Attribut AGI 4 = Poolgroesse 9 → [PROBE: Firearms | 9]"""}

Wenn du [WUERFELERGEBNIS: Fertigkeit | Wurf: N | Ziel: N | Grad] erhaeltst:
  - Reagiere NUR narrativ. Kein Zahlen-Kommentar.
  - Kritischer Erfolg: ueberwaeltigender, unerwarteter Durchbruch.
  - Extremer Erfolg: mehr als erwartet, ein Detail das die Lage veraendert.
  - Harter Erfolg: Ziel erreicht, aber mit Aufwand oder Kosten.
  - Regulaerer Erfolg: Ziel erreicht, solide.
  - Misserfolg: kein Fortschritt — oder falscher Fortschritt (Fehlinformation!).
  - Patzer: schlimmstes moegliches Ergebnis. Waffe klemmt. Seil reisst. Falle schnappt zu.
  - Markiere NACH der Beschreibung: [FERTIGKEIT_GENUTZT: <Name>]

{character_block}

═══ FAKTEN-PROTOKOLL (WORLD STATE) ═══
Wichtige, dauerhafte Spielereignisse als Fakten festhalten:
  [FAKT: {{"schluessel": "wert"}}]
  Beispiele:
    [FAKT: {{"rupert_besucht": true}}]
    [FAKT: {{"tagebuch_gefunden": true}}]
    [FAKT: {{"corbitt_manifest": true}}]

Diese Fakten werden dir bei jedem Turn als Kontext mitgeliefert.
Ein toter NPC bleibt tot. Ein gefundener Hinweis ist gefunden.
Widersprich nie bestehenden Fakten.

═══ INVENTAR-PROTOKOLL ═══
Wenn der {pc_title} einen Gegenstand findet, aufhebt oder erhaelt:
  [INVENTAR: Gegenstandsname | gefunden]
Wenn der {pc_title} einen Gegenstand kauft:
  [INVENTAR: Gegenstandsname | gekauft]
Wenn ein Gegenstand verbraucht, verloren oder zerstoert wird:
  [INVENTAR: Gegenstandsname | verloren]
Wenn der {pc_title} einen Gegenstand verkauft:
  [INVENTAR: Gegenstandsname | verkauft]

Beispiele:
  [INVENTAR: Langschwert | gefunden]
  [INVENTAR: Heiltrank | gekauft]
  [INVENTAR: Fackel | verloren]
  [INVENTAR: Goldring | verkauft]

═══ STIMMEN-WECHSEL (nur bei Voice-Modus) ═══
Wenn ein NPC spricht, setze vor dem Dialog den Stimmen-Tag:
  [STIMME:keeper]   — Zurueck zur Erzaehlerstimme (Standard)
  [STIMME:woman]    — Weibliche NPCs
  [STIMME:monster]  — Monster, Antagonisten, tiefe raue Stimme
  [STIMME:scholar]  — Akademiker, Gelehrte, sachliche Stimme
  [STIMME:mystery]  — Geister, Traumwesen, geheimnisvolle Stimme

Beispiel:
  Die Bibliothekarin blickt auf. [STIMME:woman] "Sie suchen das Buch der Schatten? Das wurde seit Jahren nicht mehr angeruehrt." [STIMME:keeper] Ihr Blick verraet mehr als ihre Worte.

Wichtig: Setze [STIMME:keeper] IMMER nach dem NPC-Dialog zurueck.
Tags niemals in narrativen Beschreibungen verwenden — nur um Dialogpartner akustisch zu unterscheiden.

═══ ZEIT-PROTOKOLL ═══
Wenn durch eine Handlung des Spielers Zeit vergeht:
  [ZEIT_VERGEHT: Xh]      — X Stunden vergehen (z.B. 1h, 2h, 0.5h)
Wenn du die Uhrzeit explizit setzen willst:
  [TAGESZEIT: HH:MM]      — z.B. [TAGESZEIT: 14:30]
Wenn sich das Wetter aendert:
  [WETTER: Beschreibung]   — z.B. "leichter Regen", "klarer Sternenhimmel"

Zeitdauern-Richtwerte:
  - Recherche in Bibliothek: [ZEIT_VERGEHT: 2h]
  - Fahrt durch die Stadt: [ZEIT_VERGEHT: 0.5h]
  - Gespraech mit NPC: [ZEIT_VERGEHT: 0.5h]
  - Ortswechsel zu Fuss: [ZEIT_VERGEHT: 1h]
  - Ausfuehrliche Untersuchung: [ZEIT_VERGEHT: 1h]
  - Schlafen/Uebernachtung: [ZEIT_VERGEHT: 8h]

Setze bei jeder Antwort mindestens [ZEIT_VERGEHT: 0.5h] wenn eine Handlung stattfindet.
Setze [WETTER] wenn es zur Atmosphaere passt oder sich aendert.
Die aktuelle Tageszeit wird dir als Kontext mitgeliefert.

═══ REGELWERK-REFERENZ ═══
System: {system_name} {version} | Wuerfel: {default_die} | {check_label}
Erfolgsgrade: {levels_text}

Verfuegbare Fertigkeiten:
{skills_text}
{core_rules_block}{adventure_block}{extras_block}═══ KAMPF-ERINNERUNG (KRITISCH) ═══
Wenn Monster im Kampf angreifen, MUSST du Schaden an Spielercharakteren zufuegen!
- JEDER beschriebene Monstertreffer braucht SOFORT einen [HP_VERLUST]-Tag.
- Ohne [HP_VERLUST] ist der Angriff wirkungslos — das zerstoert die Spielmechanik!
- Kaempfe MUESSEN beidseitig sein: Monster treffen zurueck, sie sind gefaehrlich.
- Solo: [HP_VERLUST: 6] | Party: [HP_VERLUST: Charaktername | 6]
- Pro Kampfrunde: Mindestens 1 Monster-Angriff mit [HP_VERLUST] wenn Monster noch leben.

{monster_move_block}═══ ABSOLUTES VERBOT ═══
- Sprich NIEMALS ueber Regeln, Tags, das System oder die KI.
- Erwaehne NIEMALS Wuerfelwuerfe in narrativem Text.
- Brich NIEMALS die Immersion durch Meta-Kommentare.
- Gib NIEMALS unaufgefordert Spieler-Tipps oder Handlungsempfehlungen.
- Verwende NIEMALS Klammern oder Aufzaehlungen im narrativen Fluss.
""".strip()

    def _build_speech_style_block(
        self, style: str, example_skill: str, example_target: str
    ) -> str:
        """Baut den Stil-Block abhaengig vom Sprechstil (normal/sanft/aggressiv)."""

        # ── Anti-Repetition (gilt fuer alle Stile) ──
        anti_rep = """═══ ABWECHSLUNGSPFLICHT (ANTI-REPETITION) ═══
VERBOTEN: Wiederholungen zwischen Zuegen. Deine letzte Antwort existiert nicht mehr.
- Beginne NIEMALS zwei Antworten hintereinander mit dem gleichen Wort oder Satzmuster.
- Verwende NIEMALS dieselbe Frage zweimal in Folge. Kein "Was tust du?" zweimal.
  Alternativen: "Wie reagierst du?" / "Wohin fuehrt dich dein Instinkt?" / "Was jetzt?" /
  "Worauf richtest du deine Aufmerksamkeit?" / "Was zieht dich an?" / "Was treibt dich?"
- KEINE wiederholten Sinneseindruecke: Wenn du letztes Mal "Staub" beschrieben hast,
  nutze beim naechsten Mal einen anderen Sinn (Geraeusch, Geruch, Temperatur, Licht).
- VARIIERE deine Eroeffnungen: Mal Sinneseindruck, mal Handlung, mal Dialog,
  mal Zeitsprung, mal Umgebungsdetail, mal Stimmung.
- Vermeide Fuellwoerter: "ploetzlich", "langsam", "vorsichtig" hoechstens 1x pro 5 Zuege.
"""

        if style == "sanft":
            style_rules = f"""═══ STIL: SANFT — Erzaehlstil (PFLICHT) ═══
Du bist eine ruhige, einfuehlsame Stimme. Du malst Bilder mit Worten.
Dein Tempo ist bedaechtig, dein Ton warm. Du laesst Szenen atmen.

1. SATZLIMIT: 3-4 Saetze pro Antwort. Kein Satz laenger als 18 Woerter.
   Bevorzuge 3 Saetze. 4 nur wenn die Szene es verlangt.
2. SINNE: Jede Antwort muss mindestens 2 verschiedene Sinne ansprechen.
   Geruch + Klang. Licht + Textur. Temperatur + Farbe. Wechsle staendig.
3. HOOK: Beende jede Antwort mit einer einladenden, offenen Frage oder [PROBE:].
   Statt "Was tust du?": "Was zieht deine Aufmerksamkeit an?" /
   "Welchem Impuls folgst du?" / "Was laesst dir keine Ruhe?"
4. ATMOSPHAERE: Beschreibe Details die man uebersehen wuerde.
   Das Knarren einer Diele. Der Geruch nach nassem Stein. Der Schatten einer Fliege.
5. PACING: Lass Stille wirken. Ein kurzer Satz nach einer Beschreibung erzeugt Spannung.
6. KEINE METASPRACHE. Zeige, erklaere nie.
   Richtig: "Kuehl streicht die Luft ueber deine Haut. Der Keller atmet." [PROBE: {example_skill} | {example_target}]
7. Tags am Ende, nach der Erzaehlung. Atmosphaere zuerst.
"""

        elif style == "aggressiv":
            style_rules = f"""═══ STIL: AGGRESSIV — Erzaehlstil (PFLICHT) ═══
Du bist ein harter, ungeduldiger Spielleiter. Kein Wort zu viel. Kein Mitleid.
Jeder Satz ist ein Faustschlag. Du wartest nicht. Du treibst.

1. SATZLIMIT: MAXIMAL 2 SAETZE. Punkt. Fertig. Rueckgabe an Spieler.
   Wenn du 3 schreibst, hast du versagt. 1 Satz ist oft genug.
2. WOERTERLIMIT: Maximal 10 Woerter pro Satz. Hart. Kurz. Trocken.
3. HOOK: Jede Antwort MUSS mit einer fordernden Rueckfrage oder [PROBE:] enden.
   Keine weichen Fragen. "Und?" / "Was jetzt?" / "Entscheide." / "Schnell."
4. KEIN ORNAMENT: Keine Adjektive die nicht toeten, verletzen oder bedrohen.
   Falsch: "Ein wunderschoener Raum mit feinen Details."
   Richtig: "Blut an der Wand. Frisch."
5. AKTION: Dinge passieren. Sofort. Die Welt wartet nicht auf den Spieler.
   Tueren schlagen zu. Lichter erlischen. Schritte naehern sich. JETZT.
6. KEINE METASPRACHE. Beschreibe Konsequenzen, keine Regeln.
   Richtig: "Glas splittert. Dein Arm blutet." [PROBE: {example_skill} | {example_target}]
7. Tags sofort ans Ende. Keine Vorrede.
"""

        else:  # "normal"
            style_rules = f"""═══ STIL & TTS-REGELN (PFLICHT) ═══
Du sprichst direkt ins Ohr des Spielers. Deine Worte werden vorgelesen.
Daher MUESSEN alle Ausgaben diesen Regeln folgen:

1. KURZE SAETZE. Maximal 15 Woerter pro Satz. Punkt. Naechster Satz.
2. ABSOLUTES LIMIT: MAXIMAL 3 SAETZE. Dann MUSS eine Spieler-Interaktion folgen:
   eine offene Frage ODER ein [PROBE:]-Tag.
   NIEMALS mehr als 3 Saetze ohne Rueckgabe an den Spieler.
   Bei Verstoss erhaeltst du eine STIL-KORREKTUR im naechsten Turn.
3. KEINE KLAMMERN, KEINE FORMELN, KEINE LISTEN im narrativen Text.
4. WARTE nach jeder Beschreibung auf die Reaktion des Spielers.
   Beende JEDE Antwort mit einer offenen Frage oder einem [PROBE:]-Tag.
   VARIIERE die Fragen: "Was tust du?" / "Wohin gehst du?" / "Wie reagierst du?" /
   "Was faellt dir auf?" / "Worauf konzentrierst du dich?" — nie 2x dieselbe Frage in Folge.
5. KEINE METASPRACHE. Sprich niemals ueber Regeln, Tags, Wuerfelwuerfe oder das System.
   Falsch: "Du musst jetzt eine Probe wuerfeln."
   Richtig: "Die Stille wird schwerer. Irgendetwas stimmt hier nicht." [PROBE: {example_skill} | {example_target}]
6. Tags ([PROBE:...], [HP_VERLUST:...] etc.) kommen IMMER ans Ende einer Antwort,
   NACH der narrativen Beschreibung, NIEMALS mittendrin.
7. Atmosphaere zuerst. Immer. Kein Wuerfelwurf ohne vorherige Szene.
"""

        return anti_rep + "\n" + style_rules

    def _build_adventure_block(self) -> str:
        """
        Baut einen detaillierten Keeper-Kontext-Block aus den Abenteuer-Daten.
        Enthaelt: Lore, NPCs (inkl. Secrets), Orte, Hinweise-Uebersicht.
        Leer-String wenn kein Abenteuer geladen.
        """
        if not self._adventure:
            return ""

        adv = self._adventure
        title   = adv.get("title", "Unbekannt")
        setting = adv.get("setting", "")
        hook    = adv.get("hook", "")
        lore    = adv.get("keeper_lore", "")

        lines = [
            "\n═══ AKTIVES ABENTEUER: KEEPER-WISSEN ═══",
            f"Titel:     {title}",
        ]
        if setting:
            lines.append(f"Schauplatz: {setting}")
        if hook:
            lines.append(f"\nAUFHAENGER:\n{hook}")
        if lore:
            lines.append(f"\nKEEPER-LORE (NUR DU WEISST DAS):\n{lore}")

        # NPCs
        npcs = adv.get("npcs", [])
        if npcs:
            lines.append("\nNPCS:")
            for npc in npcs:
                npc_name = npc.get("name", "?")
                role     = npc.get("role", npc.get("occupation", ""))
                persona  = npc.get("personality", npc.get("description", npc.get("traits", "")))
                secrets  = npc.get("secrets", npc.get("secret", []))
                if isinstance(secrets, str): secrets = [secrets]
                hints    = npc.get("dialogue_hints", [])
                lines.append(f"  [{npc_name}] — {role}")
                if persona:
                    lines.append(f"    Merkmale: {persona[:200]}")
                if secrets:
                    lines.append(f"    Geheimnisse: {'; '.join(secrets[:2])}")
                if hints:
                    lines.append(f"    Dialog-Hinweise: \"{hints[0]}\"")

        # Orte (kompakt)
        locations = adv.get("locations", [])
        if locations:
            lines.append("\nORTE:")
            for loc in locations:
                loc_name = loc.get("name", "?")
                atmo     = loc.get("atmosphere", "")
                knotes   = loc.get("keeper_notes", "")
                clues_av = loc.get("clues_available", loc.get("clues", []))
                if isinstance(clues_av, str): clues_av = [clues_av]
                lines.append(f"  [{loc_name}]")
                if atmo:
                    lines.append(f"    Atmosphaere: {atmo[:150]}")
                if clues_av:
                    lines.append(f"    Hinweise verfuegbar: {', '.join(clues_av)}")
                if knotes:
                    lines.append(f"    Keeper-Notiz: {knotes[:200]}")

        # Items & Artefakte
        items = adv.get("items", [])
        if items:
            lines.append("\nGEGENSTAENDE & ARTEFAKTE:")
            for item in items:
                item_name = item.get("name", "?")
                item_desc = item.get("physical_description", "")
                lines.append(f"  [{item_name}] — {item_desc[:150]}")

        # Documents
        documents = adv.get("documents", [])
        if documents:
            lines.append("\nDOKUMENTE & HANDOUTS:")
            for doc in documents:
                doc_name = doc.get("name", "?")
                doc_summary = doc.get("content_summary", "")
                lines.append(f"  [{doc_name}] — {doc_summary[:150]}")

        # Organizations
        orgs = adv.get("organizations", [])
        if orgs:
            lines.append("\nORGANISATIONEN & KULTE:")
            for org in orgs:
                org_name = org.get("name", "?")
                org_purpose = org.get("true_purpose", org.get("public_facade", ""))
                lines.append(f"  [{org_name}] — {org_purpose[:150]}")

        # Missions (Paranoia: mission_seeds, society_ops, service_ops)
        missions = adv.get("missions", [])
        if missions:
            lines.append("\nMISSIONEN & AUFTRAEGE:")
            for mis in missions:
                mis_name = mis.get("name", "?")
                mis_summary = mis.get("summary", "")
                mech = mis.get("mechanics", {})
                objective = mech.get("objective", mech.get("goal", ""))
                twist = mech.get("twist", mech.get("hidden_agenda", ""))
                line = f"  [{mis_name}]"
                if objective:
                    line += f" — Ziel: {objective}"
                if twist:
                    line += f" (Twist: {twist})"
                if not objective and mis_summary:
                    line += f" — {mis_summary[:150]}"
                lines.append(line)

        # Encounters (Paranoia: encounters_pack + base encounters)
        encounters = adv.get("encounters", [])
        if encounters:
            lines.append("\nENCOUNTERS:")
            for enc in encounters:
                enc_name = enc.get("name", "?")
                enc_summary = enc.get("summary", "")
                mech = enc.get("mechanics", {})
                trigger = mech.get("trigger", "")
                checks = mech.get("required_checks", [])
                line = f"  [{enc_name}]"
                if enc_summary:
                    line += f" — {enc_summary[:120]}"
                if trigger:
                    line += f" (Trigger: {trigger})"
                if checks:
                    line += f" [Checks: {', '.join(checks)}]"
                lines.append(line)

        # Spells
        spells = adv.get("spells", [])
        if spells:
            lines.append("\nOKKULTE ZAUBER:")
            for spell in spells:
                spell_name = spell.get("name", "?")
                spell_cost = spell.get("cost", "")
                spell_effect = spell.get("effect", "")
                lines.append(f"  [{spell_name}] (Kosten: {spell_cost}) — {spell_effect[:120]}")

        # Entities (Bestiarium - Keeper Only)
        entities = adv.get("entities", [])
        if entities:
            lines.append("\nBESTIARIUM (KEEPER-ONLY):")
            for ent in entities:
                ent_name = ent.get("name", "?")
                ent_desc = ent.get("description", "")
                ent_weak = ent.get("weakness", "Unbekannt")
                lines.append(f"  [{ent_name}] — {ent_desc[:150]} (Schwaeche: {ent_weak})")

        # Library Data
        library_items = adv.get("library", [])
        if library_items:
            lines.append("\nORNE LIBRARY (MISKATONIC UNIVERSITY):")
            structure = [i for i in library_items if i.get("name") == "Orne Library Structure"]
            if structure:
                lines.append("  Struktur & Bereiche:")
                for area in structure[0].get("areas", []):
                    lines.append(f"    - {area.get('name')}: {area.get('atmosphere')[:100]}...")

            catalog = [i for i in library_items if i.get("name") == "Orne Library Catalog"]
            if catalog:
                lines.append("  Katalog (Beispiele):")
                for book in catalog[0].get("books", [])[:5]: # Nur die ersten 5 als Beispiel
                    lines.append(f"    - '{book.get('title')}' ({book.get('author')})")

            restricted = [i for i in library_items if i.get("name") == "Die Restricted Section der Orne Library"]
            if restricted:
                lines.append("  Restricted Section:")
                rules = restricted[0].get("access_rules", {})
                lines.append(f"    Zugang: {rules.get('requirements')[:100]}...")
                holdings = [b.get('name') for b in restricted[0].get('holdings', [])]
                lines.append(f"    Bestand (Auszug): {', '.join(holdings[:3])}...")

        # NPC Generator Tables
        generator_tables = [item for item in adv.get("npcs", []) if item.get("name") == "NPC Generator Tabellen"]
        if generator_tables:
            table = generator_tables[0]
            lines.append("\nNPC-GENERATOR-TABELLEN (fuer spontane Passanten):")
            lines.append(f"  Vornamen (m): {', '.join(table.get('first_names_male', [])[:5])}...")
            lines.append(f"  Vornamen (w): {', '.join(table.get('first_names_female', [])[:5])}...")
            lines.append(f"  Nachnamen: {', '.join(table.get('last_names', [])[:5])}...")
            lines.append(f"  Ticks: {', '.join(table.get('quirks', [])[:3])}...")

        # Weather Patterns
        weather_patterns = [item for item in adv.get("history", []) if item.get("name") == "Wetter-Muster für Neuengland"]
        if weather_patterns:
            lines.append("\nWETTER-MUSTER (je nach Jahreszeit einstreuen):")
            for season in weather_patterns[0].get("seasons", []):
                season_name = season.get("name", "?")
                event_types = [event.get('type') for event in season.get('events', [])]
                lines.append(f"  [{season_name}]: {', '.join(event_types)}")

        # Culture
        culture_items = adv.get("culture", [])
        if culture_items:
            lines.append("\nPOP-KULTUR & ALLTAG (1920er):")
            radio = [item for item in culture_items if item.get("name") == "Radioprogramm WMAK Arkham"]
            if radio:
                programs = [p.get('program') for p in radio[0].get('broadcasts', [])]
                lines.append(f"  Radio (WMAK): {', '.join(programs)}")
            cinema = [item for item in culture_items if item.get("name") == "Kinoprogramm des Palace Theater"]
            if cinema:
                films = [f.get('title') for f in cinema[0].get('films', [])]
                lines.append(f"  Kino (Palace Theater): {', '.join(films)}")
            music = [item for item in culture_items if item.get("name") == "Populäre Musik der 1920er"]
            if music:
                genres = [t.get('genre') for t in music[0].get('trends', [])]
                lines.append(f"  Musik: {', '.join(genres)}")

        # Architecture & Room Details
        architecture_items = adv.get("architecture", [])
        if architecture_items:
            lines.append("\nARCHITEKTUR & RAUMDETAILS:")
            for arch_file in architecture_items:
                if arch_file.get("name") == "Sensorische Raum-Details":
                    details = arch_file.get("details", [])[:5]
                    lines.append(f"  Sensorische Details (Beispiele): \"{details[0]}\", \"{details[1]}\"...")
                elif arch_file.get("types"):
                    lines.append(f"  Gebäudetypen ({arch_file.get('name', '?')}):")
                    for building_type in arch_file.get("types", [])[:2]:
                        type_name = building_type.get("name", "?")
                        layout_example = building_type.get("layout", [{}])[0].get("rooms", "")
                        lines.append(f"    - {type_name}: {layout_example[:80]}...")

        # Sanitarium Data
        sanitarium_items = adv.get("sanitarium", [])
        if sanitarium_items:
            lines.append("\nARKHAM SANITARIUM:")
            for item in sanitarium_items:
                item_name = item.get("name", "?")
                item_type = item.get("type", "")
                item_summary = item.get("content_summary", item.get("traits", item.get("description", "")))
                lines.append(f"  - [{item_name}] ({item_type}): {item_summary[:120]}...")

        # Legal System Data
        legal_items = adv.get("legal", [])
        if legal_items:
            lines.append("\nJUSTIZSYSTEM:")
            for item in legal_items:
                item_name = item.get("name", "?")
                item_summary = item.get("content_summary", item.get("description", item.get("atmosphere", "")))
                if not item_summary and "layout_sketch" in item:
                    item_summary = item["layout_sketch"]
                lines.append(f"  - [{item_name}]: {item_summary[:120]}...")

        # Clues (kompakt — Keeper weiss alles)
        clues = adv.get("clues", [])
        if clues:
            lines.append("\nHINWEIS-MATRIX (was jeder Hinweis verbirgt):")
            for clue in clues:
                c_name = clue.get("name", "?")
                c_info = clue.get("information", "")
                c_prob = clue.get("probe_required", None)
                c_san  = clue.get("sanity_loss", None)
                detail = f"    {c_name}: {c_info[:150]}"
                if c_prob:
                    detail += f" [Probe: {c_prob}]"
                if c_san and getattr(self, "_is_cthulhu", True):
                    detail += f" [SAN: {c_san}]"
                lines.append(detail)

        # Moegliche Ausgaenge
        resolution = adv.get("resolution", {})
        endings = resolution.get("possible_endings", [])
        if endings:
            lines.append("\nMOEGLICHE AUSGAENGE:")
            for end in endings:
                lines.append(
                    f"  [{end.get('name','?')}]: {end.get('description','')[:120]}"
                )

        lines.append("")  # Leerzeile vor naechstem Block
        full_block = "\n".join(lines) + "\n"

        # Lore-Budget-Kappelung: kuerze auf max. erlaubte Zeichen (Slider-Wert)
        max_chars = self._get_max_lore_chars()
        if max_chars == 0:
            logger.info("[LORE-BUDGET] 0%% gesetzt — Lore-Block wird unterdrückt.")
            return ""
        if len(full_block) > max_chars:
            logger.info(
                "[LORE-BUDGET] Lore-Block %d Zeichen → auf %d Zeichen (=%d%%) gekuerzt.",
                len(full_block), max_chars, self._lore_budget_pct,
            )
            full_block = full_block[:max_chars] + "\n[... Lore-Budget erschoepft ...]\n"
        return full_block

    def _build_setting_block(self) -> str:
        """Baut den Setting-Block fuer den System-Prompt."""
        if not self._setting:
            return ""
        s = self._setting
        lines = [
            "\n═══ SETTING & WELT ═══",
            f"Welt: {s.get('name', '')}",
            f"Epoche: {s.get('epoch', '')}",
            f"Geographie: {s.get('geography', '')}",
            f"Kultur & Gesellschaft: {s.get('culture', '')}",
            f"Technologie: {s.get('technology', '')}",
            f"Voelker/Spezies: {s.get('races_species', '')}",
            f"Waehrung: {s.get('currency', '')}",
            f"Sprachstil: {s.get('language_style', '')}",
        ]
        special = s.get("special_rules", "")
        if special:
            lines.append(f"Besondere Regeln: {special}")
        lines.append(
            "\nHalte dich an diese Welt-Parameter. "
            "Erfinde keine Technologie oder Voelker die nicht existieren."
        )
        return "\n".join(lines)

    def _build_keeper_detail_block(self) -> str:
        """Baut den Keeper-Detail-Block aus dem Keeper-Modul."""
        if not self._keeper:
            return ""
        kp = self._keeper
        parts = []
        if kp.get("narration_style"):
            parts.append(f"Erzaehlstil: {kp['narration_style']}")
        if kp.get("combat_style"):
            parts.append(f"Kampfbeschreibung: {kp['combat_style']}")
        if kp.get("npc_voice"):
            parts.append(f"NPC-Stimmen: {kp['npc_voice']}")
        if kp.get("philosophy"):
            parts.append(f"Philosophie: {kp['philosophy']}")
        if kp.get("catch_phrases"):
            parts.append(f"Typische Wendungen: {', '.join(kp['catch_phrases'][:3])}")
        if not parts:
            return ""
        return "\n" + "\n".join(parts)

    def _build_extras_block(self) -> str:
        """Baut den Extras-Block fuer den System-Prompt."""
        if not self._extras:
            return ""
        parts = []
        for ext in self._extras:
            name = ext.get("name", "?")
            injection = ext.get("prompt_injection", "")
            if injection:
                parts.append(f"[{name}]: {injection}")
        if not parts:
            return ""
        return "\n═══ ZUSAETZLICHE REGELN ═══\n" + "\n".join(parts) + "\n"

    def _build_core_rules_block(self) -> str:
        """Inject permanent + core rules from RulesEngine into system prompt.

        Uses the full rules budget for the static system prompt.
        All permanent + core sections are included.
        """
        if not hasattr(self, "_rules_engine") or not self._rules_engine:
            return ""

        re = self._rules_engine
        budget = getattr(re, "_rules_budget", re.DEFAULT_RULES_BUDGET)
        static_budget = budget

        # Collect permanent sections first, then core sections
        # Collect all sections by priority tier
        by_priority: dict[str, list] = {
            "permanent": [], "core": [], "support": [], "flavor": [],
        }
        for s in re.get_all_sections():
            by_priority.get(s.priority, by_priority["support"]).append(s)

        if not any(by_priority.values()):
            return ""

        parts = []
        used = 0

        # Load in priority order: permanent -> core -> support -> flavor
        for prio in ("permanent", "core", "support", "flavor"):
            sections = by_priority[prio]
            sections.sort(key=lambda s: s.char_count)
            for s in sections:
                if used + s.char_count > static_budget:
                    continue
                parts.append(f"[{s.title}] {s.text}")
                used += s.char_count

        if not parts:
            return ""

        return (
            "\n--- Kernregeln (IMMER beachten) ---\n"
            + "\n".join(parts) + "\n"
        )

    def _build_party_block(self) -> str:
        """Baut den Party-Block fuer den System-Prompt (Multi-Charakter-Modus)."""
        if not self._party_members:
            return ""

        lines = [
            "\n=== DIE GRUPPE (SPIELERCHARAKTERE) ===",
            f"Du verwaltest {len(self._party_members)} Charaktere gleichzeitig.",
            "Jeder Charakter handelt pro Runde. Verwende Per-Character Tags:",
            "",
            "SPIELER greift Monster an (System wuerfelt Schaden):",
            "  [ANGRIFF: <Waffe> | <THAC0> | <AC> | <Mod> | <Spielername>]",
            "  Beispiel: [ANGRIFF: Battle Axe +1 | 14 | 7 | 4 | Grimjaw Eisenfaust]",
            "",
            "MONSTER trifft Spieler (DU bestimmst den Schaden):",
            "  [HP_VERLUST: <Spielername> | <Schadenszahl>]",
            "  Beispiel: [HP_VERLUST: Grimjaw Eisenfaust | 6]",
            "  PFLICHT bei jedem Monstertreffer! NIEMALS [ANGRIFF] fuer Monster verwenden!",
            "",
            "Weitere Tags:",
            "  [HP_HEILUNG: <Name> | <Menge>]",
            "  [ZAUBER_VERBRAUCHT: <Name> | <Zauber> | <Level>]",
            "  [INVENTAR: <Item> | <Aktion> | <Name>]",
            "  [PROBE: <Fertigkeit> | <Zielwert> | <Name>]",
            "  [FERTIGKEIT_GENUTZT: <Fertigkeitsname> | <Charaktername>]",
            "  [GEGENSTAND_BENUTZT: <Gegenstandsname> | <Charaktername>]",
            "",
        ]

        for c in self._party_members:
            name = c.get("name", "?")
            archetype = c.get("archetype", c.get("class", "?"))
            level = c.get("level", "?")
            race = c.get("race", "?")

            # Derived stats
            derived = c.get("derived_stats", {})
            hp = derived.get("HP", "?")
            ac = derived.get("AC", "?")
            thac0 = derived.get("THAC0", "?")

            # Characteristics
            chars = c.get("characteristics", {})
            char_str = " ".join(f"{k}:{v}" for k, v in chars.items())

            lines.append(f"--- {name} ({archetype.title()} {level}, {race}) ---")
            lines.append(f"  {char_str} | HP: {hp}/{hp} | AC: {ac} | THAC0: {thac0}")

            # Equipment (kompakt)
            equip = c.get("equipment", [])
            weapons = [e for e in equip if any(
                kw in e.lower() for kw in (
                    "sword", "axe", "bow", "dagger", "mace", "staff",
                    "hammer", "flail", "spear", "crossbow", "schwert",
                    "axt", "bogen", "dolch", "streitkolben", "stab",
                )
            )]
            armor = [e for e in equip if any(
                kw in e.lower() for kw in (
                    "armor", "plate", "mail", "shield", "bracers",
                    "ruestung", "panzer", "schild",
                )
            )]
            if weapons:
                lines.append(f"  Waffen: {', '.join(weapons)}")
            if armor:
                lines.append(f"  Ruestung: {', '.join(armor)}")

            # Spells
            spells_prep = c.get("spells_prepared", {})
            if isinstance(spells_prep, dict) and spells_prep:
                sp_parts = []
                for lvl_str, spell_list in sorted(spells_prep.items()):
                    if isinstance(spell_list, list) and spell_list:
                        sp_parts.append(f"Level {lvl_str}: {', '.join(spell_list)}")
                if sp_parts:
                    lines.append(f"  Sprueche: {'; '.join(sp_parts)}")

            # Skills (mit Werten)
            skills = c.get("skills", {})
            if skills:
                skill_str = ", ".join(f"{k}:{v}" for k, v in skills.items())
                lines.append(f"  Fertigkeiten: {skill_str}")
                lines.append(
                    "  -> Verwende NUR Fertigkeiten aus diesem Charakter-Bogen. Erfinde KEINE neuen."
                )

            # Background (kurz)
            bg = c.get("background", "")
            if bg:
                # Nur ersten Satz
                first_sent = bg.split(".")[0] + "." if "." in bg else bg[:120]
                lines.append(f"  Hintergrund: {first_sent}")

            lines.append("")

        lines.append(
            "PFLICHT: Lass ALLE Gruppenmitglieder pro Runde handeln. "
            "Jeder Charakter hat seine Rolle — nutze sie. "
            "Verwalte Tags per-Character mit dem Namen im Tag.\n\n"
            "=== KAMPFRUNDE KOMPLETT-BEISPIEL ===\n"
            "So sieht eine vollstaendige Kampfrunde aus (Spieler UND Monster):\n\n"
            "Grimjaw stuermt vor und schlaegt auf das Skelett ein.\n"
            "[ANGRIFF: Battle Axe +1 | 14 | 7 | 4 | Grimjaw Eisenfaust]\n"
            "Sir Kael schlaegt mit dem Heiligen Schwert zu.\n"
            "[ANGRIFF: Holy Sword +2 | 15 | 7 | 2 | Sir Kael Zornesklinge]\n"
            "Das Skelett schlaegt mit dem Rostschwert nach Grimjaw — ein Treffer!\n"
            "[HP_VERLUST: Grimjaw Eisenfaust | 5]\n"
            "Ein zweites Skelett kratzt Pyra am Arm.\n"
            "[HP_VERLUST: Pyra Flammenherz | 3]\n\n"
            "REGELN:\n"
            "- [ANGRIFF] = Spielercharakter greift Monster an (NUR fuer Spieler-Waffen)\n"
            "- [HP_VERLUST] = Monster trifft Spielercharakter (PFLICHT bei jedem Treffer)\n"
            "- JEDE Kampfrunde enthaelt BEIDES: Spieler-Angriffe UND Monster-Treffer\n"
            "- Monster treffen IMMER mindestens einen Spieler pro Runde"
        )
        return "\n".join(lines)

    def _build_character_block(self) -> str:
        """Baut den Charakter-Kontext-Block aus dem Character-Template."""
        if not self._character_template:
            return ""
        c = self._character_template
        lines = [
            "\n═══ SPIELERCHARAKTER ═══",
            f"Name: {c.get('name', '?')}",
        ]
        if c.get("archetype"):
            lines.append(f"Klasse/Beruf: {c['archetype']}")
        if c.get("level"):
            lines.append(f"Stufe: {c['level']}")
        if c.get("background"):
            lines.append(f"Hintergrund: {c['background']}")
        if c.get("traits"):
            lines.append(f"Persoenlichkeit: {c['traits']}")
        if c.get("appearance"):
            lines.append(f"Erscheinung: {c['appearance']}")

        # Charakteristiken
        chars = c.get("characteristics", {})
        if chars and isinstance(chars, dict):  # Typprüfung
            char_parts = [f"{k}: {v}" for k, v in chars.items()]
            lines.append(f"Attribute: {', '.join(char_parts)}")

        # Ausruestung
        equip = c.get("equipment", [])
        if equip:
            lines.append(f"Ausruestung: {', '.join(equip)}")

        lines.append(
            "\nBeziehe dich auf den Charakter mit seinem Namen und beruecksichtige "
            "seine Persoenlichkeit, seinen Hintergrund und seine Ausruestung in der Erzaehlung."
        )
        return "\n".join(lines)

    def _stub_response(self, user_message: str) -> str:
        """Platzhalter-Antwort wenn kein API-Key vorhanden."""
        return (
            "[GEMINI_API_KEY nicht konfiguriert] "
            "Trage deinen API-Key in die .env-Datei ein und starte neu. "
            f"Deine Eingabe war: '{user_message[:80]}'"
        )
