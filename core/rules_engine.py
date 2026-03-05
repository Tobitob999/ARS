# ---------------------------------------------------------------------------
# core/rules_engine.py — Offline Rules Index, Pre-Injection & Post-Validation
# ---------------------------------------------------------------------------
"""
Schicht 3: Indiziert Regelwerk-JSON in durchsuchbare Sektionen.
Schicht 1: Injiziert relevante Regelsektionen in den KI-Kontext (pre-call).
Schicht 2: Validiert extrahierte Tags gegen Regelwerk (post-response).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from core.event_bus import EventBus

logger = logging.getLogger("ARS.rules_engine")

# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class RuleSection:
    """A single indexed chunk of rule text."""
    section_id: str          # e.g. "combat.initiative"
    category: str            # top-level: "combat", "sanity", "skills" ...
    title: str               # human-readable: "Initiative System"
    keywords: list[str]      # trigger words
    text: str                # formatted rule text for injection
    char_count: int = 0      # len(text), set in __post_init__
    priority: str = "support"  # permanent | core | support | flavor

    def __post_init__(self) -> None:
        self.char_count = len(self.text)


@dataclass
class ValidationResult:
    """Result of a tag validation check."""
    tag_type: str            # "PROBE", "ANGRIFF", ...
    is_valid: bool
    severity: str            # "ok" | "warning" | "error"
    message: str
    original_value: Any
    suggested_value: Any = None

# ---------------------------------------------------------------------------
# Priority Scoring
# ---------------------------------------------------------------------------

_PRIORITY_MULTIPLIER: dict[str, float] = {
    "permanent": 10.0,   # Always included
    "core": 3.0,         # High priority on keyword match
    "support": 1.0,      # Normal
    "flavor": 0.3,       # Low — only with generous budget
}

# ---------------------------------------------------------------------------
# Keyword Maps
# ---------------------------------------------------------------------------

_KEYWORD_MAP: dict[str, list[str]] = {
    "combat": [
        "kampf", "angriff", "angreif", "treffer", "waffe", "ruestung", "schaden",
        "combat", "attack", "hit", "weapon", "armor", "damage",
        "nahkampf", "fernkampf", "melee", "missile", "ranged",
        "schwert", "axt", "bogen", "sword", "axe", "bow",
        "schiessen", "schuss", "kaempf", "zuschlag", "stich",
        "greif", "schlag", "messer", "dolch", "klinge",
    ],
    "combat.initiative": [
        "initiative", "reihenfolge", "ueberraschung", "surprise",
        "kampfrunde", "round",
    ],
    "combat.attack_resolution": [
        "thac0", "angriffswurf", "trefferwurf", "ruestungsklasse",
        "attack roll", "armor class",
    ],
    "combat.vehicle": [
        "fahrzeug", "rammen", "vehicle", "ram", "sideswipe",
        "montiert", "mounted",
    ],
    "magic": [
        "zauber", "magie", "spell", "magic", "wirken", "cast",
        "spruchbuch", "spellbook", "memorize", "auswendig",
        "arkane", "goettlich", "arcane", "divine",
    ],
    "healing": [
        "heilung", "heal", "rast", "rest", "genesung", "recovery",
        "erste hilfe", "first aid", "heiltrank", "potion",
        "verbinden", "bandage", "wunde", "wunden", "verletzt",
        "verarzten", "pflegen",
    ],
    "advancement": [
        "steigerung", "erfahrung", "level", "aufstieg", "xp",
        "advancement", "experience", "training", "levelaufstieg",
    ],
    "saving_throws": [
        "rettungswurf", "saving throw", "save", "gift", "poison",
        "laehmung", "versteinerung", "drachenodem", "breath weapon",
    ],
    "conditions": [
        "zustand", "condition", "vergiftet", "gelaehmt", "paralyzed",
        "blind", "fear", "angst", "betaeubt", "stunned",
    ],
    "economy": [
        "geld", "gold", "muenzen", "handeln", "kaufen", "verkaufen",
        "money", "coin", "trade", "buy", "sell", "tauschen",
    ],
    "stats": [
        "trefferpunkte", "lebenspunkte", "hit points",
        "magiepunkte", "magic points", "bewegung", "movement",
    ],
    "classes": [
        "klasse", "class", "krieger", "warrior", "magier", "wizard",
        "priester", "priest", "dieb", "thief", "bard", "paladin",
        "ranger", "druide", "druid",
    ],
    # --- AD&D 2E ---
    "proficiencies": [
        "fertigkeit", "proficiency", "proficiencies", "nwp",
        "waffenfertigkeit", "weapon proficiency", "spezialisierung",
        "specialization", "nicht-waffen", "nonweapon",
    ],
    "racial_abilities": [
        "rasse", "race", "zwerg", "dwarf", "elf", "gnom", "gnome",
        "halbling", "halfling", "halbelf", "half-elf", "mensch", "human",
        "infravision", "nachtsicht", "stufenlimit", "level limit",
        "rassenfaehigkeit", "racial ability",
    ],
    "turn_undead": [
        "untote", "undead", "vertreiben", "turn", "turn undead",
        "skelett", "zombie", "ghoul", "vampir", "geist", "ghost",
        "mumie", "mummy", "wraith", "spectre", "lich",
    ],
    "spell_slots": [
        "zauberplaetze", "spell slot", "memorieren", "memorize",
        "vorbereiten", "prepare", "zauber pro tag", "spells per day",
        "spruchliste", "spell list",
    ],
    "encumbrance": [
        "belastung", "encumbrance", "traglast", "gewicht", "weight",
        "movement rate", "bewegungsrate", "behinderung",
    ],
    "surprise": [
        "ueberraschung", "surprise", "hinterhalt", "ambush",
        "wachsamkeit", "awareness", "begegnungsdistanz",
    ],
    "treasure": [
        "schatz", "treasure", "loot", "beute", "gold", "muenzen", "edelstein",
        "schmuck", "gems", "jewelry", "hort", "truhe", "chest", "schaetze",
    ],
    "encounter_generation": [
        "begegnung", "encounter", "wandering", "monster_check", "zufallsbegegnung",
        "wandernde_monster", "patrouille", "streifzug",
    ],
    "morale": [
        "moral", "morale", "flucht", "fliehen", "flee", "retreat", "mut",
        "kampfmoral", "desertieren", "aufgeben", "surrender",
    ],
    "reaction": [
        "reaktion", "reaction", "einstellung", "attitude", "gesinnung",
        "freundlich", "feindlich", "neutral", "npc_reaktion",
    ],
    "loyalty": [
        "loyalitaet", "loyalty", "gefolge", "henchman", "henchmen", "hireling",
        "soeldner", "gefolgsmann", "treue", "diener",
    ],
    "light_vision": [
        "licht", "light", "dunkelheit", "darkness", "fackel", "torch", "laterne",
        "lantern", "sicht", "vision", "infravision", "sichtweite", "beleuchtung",
    ],
    "poison_disease": [
        "gift", "poison", "krankheit", "disease", "vergiftung", "gegengift",
        "antidot", "antidote", "seuche", "infektion",
    ],
    "thief_skills": [
        "diebeskuenste", "thief_skill", "schleichen", "verstecken", "hide",
        "move_silently", "schloss_knacken", "pick_lock", "taschendiebstahl",
        "pick_pocket", "fallen_finden", "find_trap", "klettern", "climb",
    ],
}

# Valid saving throw category fragments (for fuzzy matching)
_VALID_SAVE_CATEGORIES = {
    "gift", "laehmung", "paralyzation", "poison", "tod", "death",
    "stab", "rute", "rod", "staff", "wand",
    "versteinerung", "petrification", "polymorph",
    "drachenodem", "breath", "odem",
    "zauber", "spell",
}

# ---------------------------------------------------------------------------
# Cross-System Tag Boundaries
# ---------------------------------------------------------------------------
# Tags that require a sanity system — AD&D 2e has none, so these are always invalid.
_SANITY_ONLY_TAGS: frozenset[str] = frozenset({
    "STABILITAET_VERLUST",
    "SANITY_CHECK",
    "SAN_LOSS",
})

# ---------------------------------------------------------------------------
# RulesEngine
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Skill Aliases — maps common AI-generated wrong names to canonical skill names
# ---------------------------------------------------------------------------

SKILL_ALIASES: dict[str, dict[str, str]] = {
    "add_2e": {
        # Englische Aliase → kanonische AD&D 2e Namen
        "Stealth": "Heimlichkeit",
        "Perception": "Wahrnehmung",
        "Persuasion": "Ueberreden",
        # Deutsche Aliase → kanonische AD&D 2e Skill-Namen
        "Fallen entdecken": "Find/Remove Traps",
        "Fallen suchen": "Find/Remove Traps",
        "Fallen-Suchen": "Find/Remove Traps",
        "Schloesser oeffnen": "Open Locks",
        "Schloss oeffnen": "Open Locks",
        "Lautlos bewegen": "Move Silently",
        "Schleichen": "Move Silently",
        "Im Schatten verbergen": "Hide in Shadows",
        "Verstecken": "Hide in Shadows",
        "Faehrtensuche": "Tracking",
        "Faehrten lesen": "Tracking",
        "Heilkunde": "Healing",
        "Erste Hilfe": "Healing",
        "Taschendiebstahl": "Pick Pockets",
        "Mauern erklimmen": "Climb Walls",
        "Klettern": "Climb Walls",
        "Geraeusche hoeren": "Detect Noise",
        "Lauschen": "Detect Noise",
    },
}


class RulesEngine:
    """
    Offline rules index with search and validation capabilities.

    Ruleset-agnostic: works with any JSON ruleset following the ARS schema.
    Observable: emits events via EventBus.
    """

    DEFAULT_RULES_BUDGET = 6000    # ~1500 Tokens
    MIN_RULES_BUDGET = 1000
    MAX_RULES_BUDGET = 2000000     # ~500000 Tokens (50% von 1M Kontext)

    def __init__(
        self,
        ruleset: dict[str, Any],
        tables_data: dict[str, Any] | None = None,
        rules_budget: int | None = None,
    ) -> None:
        self._ruleset = ruleset
        self._tables = tables_data
        self._sections: dict[str, RuleSection] = {}
        self._keyword_index: dict[str, list[str]] = {}  # keyword -> [section_ids]
        self._skill_names: set[str] | None = None
        self._stat_names: set[str] | None = None
        self._rules_budget = rules_budget or self.DEFAULT_RULES_BUDGET

        # Detect dice system
        ds = ruleset.get("dice_system", {})
        die_str = ds.get("default_die", "d100")
        try:
            self._die_max = int(die_str.lower().replace("d", ""))
        except ValueError:
            self._die_max = 100

        # Detect if system has sanity
        self._has_sanity = "sanity" in ruleset
        # Detect if system has survival
        self._has_survival = "survival" in ruleset
        # Detect system type
        meta = ruleset.get("metadata", {})
        self._system = meta.get("system", "")
        self._module_name = meta.get("module_name", self._system)
        self._is_add2e = self._system.startswith("add_2e")

    def set_rules_budget(self, chars: int) -> None:
        """Set the injection budget (in characters). Clamped to valid range."""
        self._rules_budget = max(self.MIN_RULES_BUDGET,
                                 min(self.MAX_RULES_BUDGET, chars))

    # ======================================================================
    # Schicht 3 — Index & Lookup
    # ======================================================================

    def index(self) -> None:
        """Build the section index from ruleset + tables. Called once."""
        self._sections.clear()
        self._keyword_index.clear()

        # Index ruleset sections
        self._index_combat()
        self._index_sanity()
        self._index_survival()
        self._index_derived_stats()
        self._index_advancement()
        self._index_healing()
        self._index_conditions()
        self._index_economy()
        self._index_magic()
        self._index_saving_throws()
        self._index_classes()

        # Index tables (AD&D 2e)
        if self._tables:
            self._index_tables()

        # AD&D 2e specific
        self._index_racial_abilities()

        # Index lore chunks from data/lore/{system}/rules_fulltext_chunks/
        self._index_lore_chunks()

        logger.info(
            "RulesEngine indexed: %d sections, %d keywords, %d total chars",
            len(self._sections),
            len(self._keyword_index),
            sum(s.char_count for s in self._sections.values()),
        )

    def get_section(self, section_id: str) -> RuleSection | None:
        return self._sections.get(section_id)

    def get_relevant_sections(
        self,
        keywords: list[str],
        max_chars: int | None = None,
    ) -> list[RuleSection]:
        """Find sections matching keywords, sorted by relevance, capped by char limit.

        Uses a 3-layer selection:
        1. Permanent sections are always included.
        2. Keyword-index match: score * priority-multiplier.
        3. Fulltext scan: search section text for keywords (fills remaining budget).
        """
        budget = max_chars if max_chars is not None else self._rules_budget

        # Layer 1: permanent sections (always included)
        permanent: list[RuleSection] = []
        permanent_ids: set[str] = set()
        for s in self._sections.values():
            if s.priority == "permanent":
                permanent.append(s)
                permanent_ids.add(s.section_id)
        result: list[RuleSection] = list(permanent)
        used = sum(s.char_count + 20 for s in permanent)

        # Layer 2: score-based selection from keyword index
        scores: dict[str, float] = {}
        kw_lower = [k.lower() for k in keywords]
        for kw in kw_lower:
            for idx_kw, section_ids in self._keyword_index.items():
                if kw == idx_kw or kw in idx_kw or idx_kw in kw:
                    for sid in section_ids:
                        if sid not in permanent_ids:
                            mult = _PRIORITY_MULTIPLIER.get(
                                self._sections[sid].priority, 1.0)
                            scores[sid] = scores.get(sid, 0) + mult

        # Layer 3: fulltext scan for sections not yet scored
        # Searches section text directly for keyword matches
        scored_ids = set(scores.keys()) | permanent_ids
        for sid, s in self._sections.items():
            if sid in scored_ids:
                continue
            text_lower = s.text.lower()
            match_count = sum(1 for kw in kw_lower if kw in text_lower)
            if match_count > 0:
                mult = _PRIORITY_MULTIPLIER.get(s.priority, 1.0)
                # Fulltext matches score lower than keyword-index matches
                scores[sid] = match_count * mult * 0.5

        if not scores and not permanent:
            return []

        # Sort by weighted score descending, then char_count ascending
        ranked = sorted(
            scores.keys(),
            key=lambda sid: (-scores[sid], self._sections[sid].char_count),
        )

        # Greedy-pack within remaining budget
        for sid in ranked:
            s = self._sections[sid]
            if used + s.char_count + 20 > budget:
                continue  # skip large ones, try smaller
            result.append(s)
            used += s.char_count + 20  # overhead for title + newlines

        return result

    def get_all_sections(self) -> list[RuleSection]:
        return list(self._sections.values())

    def get_skill_names(self) -> set[str]:
        if self._skill_names is None:
            skills = self._ruleset.get("skills", {})
            self._skill_names = set(skills.keys())
        return self._skill_names

    def resolve_skill_alias(self, skill_name: str) -> tuple[str, bool]:
        """Resolve a potentially wrong skill name via SKILL_ALIASES.

        Returns (canonical_name, was_aliased).
        If alias maps to empty string → skill is invalid for this system.
        If no alias found → returns original name unchanged.
        """
        aliases = SKILL_ALIASES.get(self._module_name, {})
        if skill_name in aliases:
            canonical = aliases[skill_name]
            if canonical:
                logger.info("Skill-Alias aufgeloest: '%s' -> '%s'", skill_name, canonical)
                return canonical, True
            else:
                logger.warning("Skill '%s' existiert nicht in %s (Cross-System Kontamination)",
                               skill_name, self._module_name)
                return skill_name, False
        # Case-insensitive fallback
        for alias_key, canonical in aliases.items():
            if alias_key.lower() == skill_name.lower():
                if canonical:
                    logger.info("Skill-Alias aufgeloest (fuzzy): '%s' -> '%s'", skill_name, canonical)
                    return canonical, True
                else:
                    logger.warning("Skill '%s' existiert nicht in %s", skill_name, self._module_name)
                    return skill_name, False
        return skill_name, False

    def get_stat_names(self) -> set[str]:
        if self._stat_names is None:
            ds = self._ruleset.get("derived_stats", {})
            chars = self._ruleset.get("characteristics", {})
            self._stat_names = set(ds.keys()) | set(chars.keys())
        return self._stat_names

    # ======================================================================
    # Schicht 1 — Pre-Injection Context
    # ======================================================================

    def get_context_for_prompt(
        self,
        player_input: str,
        previous_response: str = "",
        active_combat: bool = False,
        current_stats: dict[str, int] | None = None,
    ) -> str | None:
        """
        Determine which rule sections to inject based on situation.
        Returns formatted text, or None if nothing relevant.
        """
        keywords: set[str] = set()

        # Extract from player input
        words = set(re.findall(r"\w+", player_input.lower()))
        for kw in self._keyword_index:
            if kw in words:
                keywords.add(kw)
            # Substring-Match in beiden Richtungen (Stemming-Ersatz)
            elif any(
                (kw in w or w in kw)
                for w in words if len(w) >= 4
            ):
                keywords.add(kw)

        # Extract from previous response tags
        if "[ANGRIFF:" in previous_response or "[RETTUNGSWURF:" in previous_response:
            keywords.update(["kampf", "angriff", "combat"])
        if "[STABILITAET_VERLUST:" in previous_response:
            keywords.update(["san", "stabilitaet", "wahnsinn"])
        if "[HP_VERLUST:" in previous_response:
            keywords.update(["schaden", "heilung"])
        if "[PROBE:" in previous_response:
            # Check which skill was probed — might need context
            pass

        # From combat state
        if active_combat:
            keywords.update(["kampf", "angriff", "initiative", "combat"])

        # From character stats (low thresholds)
        if current_stats:
            san = current_stats.get("SAN")
            hp = current_stats.get("HP")
            hp_max = current_stats.get("HP_max")
            if san is not None and san < 30:
                keywords.update(["san", "wahnsinn"])
            if hp is not None and hp_max and hp < hp_max * 0.3:
                keywords.update(["heilung", "healing"])

        if not keywords:
            return None

        sections = self.get_relevant_sections(list(keywords))
        if not sections:
            return None

        parts = ["=== RELEVANTE REGELN ==="]
        for s in sections:
            parts.append(f"[{s.title}] {s.text}")

        result = "\n".join(parts)

        # Emit event
        permanent_count = sum(1 for s in sections if s.priority == "permanent")
        bus = EventBus.get()
        bus.emit("rules", "section_injected", {
            "sections": [s.section_id for s in sections],
            "char_count": len(result),
            "budget": self._rules_budget,
            "budget_used_pct": round(len(result) / self._rules_budget * 100, 1),
            "permanent_count": permanent_count,
            "keywords_matched": list(keywords),
        })

        return result

    # ======================================================================
    # Schicht 2 — Post-Response Validation
    # ======================================================================

    def validate_tags(
        self,
        probes: list[tuple[str, int]] | None = None,
        stat_changes: list[tuple[str, str]] | None = None,
        combat_tags: list[tuple[str, dict]] | None = None,
        inventory_changes: list[tuple[str, str]] | None = None,
        character_stats: dict[str, int] | None = None,
        character_skills: dict[str, int] | None = None,
    ) -> list[ValidationResult]:
        """
        Validate all extracted tags. Returns only non-ok results.
        Emits 'rules.validation_warning' for each warning/error.
        """
        results: list[ValidationResult] = []
        bus = EventBus.get()

        for skill_name, target_value in (probes or []):
            vr = self.validate_probe(skill_name, target_value, character_skills)
            if vr.severity != "ok":
                results.append(vr)

        for stat_tuple in (stat_changes or []):
            change_type = stat_tuple[0]
            value_str = stat_tuple[1] if len(stat_tuple) > 1 else ""
            # ── Sanity-Tag Guard ──────────────────────────────────────────
            # AD&D 2e hat kein Sanity-System. Blocke Sanity-Tags.
            if change_type in _SANITY_ONLY_TAGS:
                msg = (
                    f"[Sanity-Tag geblockt] Tag '{change_type}' ist fuer "
                    f"'{self._system}' ungueltig (kein Sanity-System)."
                )
                logger.warning(msg)
                vr = ValidationResult(
                    tag_type=change_type,
                    is_valid=False,
                    severity="error",
                    message=msg,
                    original_value=value_str,
                )
                results.append(vr)
                continue
            # ── Normal per-tag routing ────────────────────────────────────
            if change_type == "STABILITAET_VERLUST":
                vr = self.validate_san_loss(value_str, character_stats)
            elif change_type in ("HP_VERLUST", "HP_HEILUNG"):
                vr = self.validate_hp_change(change_type, value_str, character_stats)
            elif change_type == "XP_GEWINN":
                vr = self.validate_xp_gain(value_str)
            elif change_type == "FERTIGKEIT_GENUTZT":
                vr = self.validate_skill_used(value_str)
            # ── Monster-Mechanik Tags ─────────────────────────────────────
            elif change_type == "MAGIC_RESISTANCE":
                vr = self.validate_magic_resistance(value_str)
            elif change_type == "WAFFEN_IMMUNITAET":
                vr = self.validate_weapon_immunity(value_str)
            elif change_type == "GIFT":
                vr = self.validate_poison(value_str)
            elif change_type == "LEVEL_DRAIN":
                vr = self.validate_level_drain(value_str)
            elif change_type == "MORAL_CHECK":
                vr = self.validate_morale_check(value_str)
            elif change_type == "REGENERATION":
                vr = self.validate_regeneration(value_str)
            elif change_type == "FURCHT":
                vr = self.validate_fear(value_str)
            elif change_type == "ATEM_WAFFE":
                vr = self.validate_breath_weapon(value_str)
            else:
                continue
            if vr.severity != "ok":
                results.append(vr)

        for tag_type, data in (combat_tags or []):
            if tag_type == "ANGRIFF":
                vr = self.validate_attack(data)
            elif tag_type == "RETTUNGSWURF":
                vr = self.validate_saving_throw(data)
            else:
                continue
            if vr.severity != "ok":
                results.append(vr)

        # Emit warnings
        for vr in results:
            bus.emit("rules", "validation_warning", {
                "tag_type": vr.tag_type,
                "severity": vr.severity,
                "message": vr.message,
                "original_value": str(vr.original_value),
            })

        return results

    # -- Individual Validators -----------------------------------------------

    def validate_probe(
        self,
        skill_name: str,
        target_value: int,
        character_skills: dict[str, int] | None = None,
    ) -> ValidationResult:
        # Alias resolution first
        resolved, was_aliased = self.resolve_skill_alias(skill_name)
        if was_aliased:
            skill_name = resolved

        valid_skills = self.get_skill_names()

        # Fuzzy match: case-insensitive, substring
        exact = skill_name in valid_skills
        fuzzy = any(
            skill_name.lower() == s.lower()
            or skill_name.lower() in s.lower()
            or s.lower() in skill_name.lower()
            for s in valid_skills
        )

        if not exact and not fuzzy:
            return ValidationResult(
                tag_type="PROBE", is_valid=False, severity="warning",
                message=f"Fertigkeit '{skill_name}' nicht im Regelwerk gefunden.",
                original_value={"skill": skill_name, "target": target_value},
            )

        # Range check — AD&D 2e: d20 + Prozent-Skills (Thief: Move Silently 35% etc.) bis 100
        max_target = 100
        if target_value < 1 or target_value > max_target:
            return ValidationResult(
                tag_type="PROBE", is_valid=False, severity="warning",
                message=f"Zielwert {target_value} ausserhalb Bereich 1-{max_target}.",
                original_value={"skill": skill_name, "target": target_value},
                suggested_value=max(1, min(target_value, max_target)),
            )

        # Character skill deviation check
        if character_skills:
            for cs_name, cs_val in character_skills.items():
                if cs_name.lower() == skill_name.lower():
                    if abs(target_value - cs_val) > 20:
                        return ValidationResult(
                            tag_type="PROBE", is_valid=True, severity="warning",
                            message=(
                                f"Zielwert {target_value} weicht stark vom "
                                f"Charakter-Wert {cs_val} ab."
                            ),
                            original_value={"skill": skill_name, "target": target_value},
                            suggested_value=cs_val,
                        )
                    break

        return ValidationResult(
            tag_type="PROBE", is_valid=True, severity="ok",
            message="", original_value={"skill": skill_name, "target": target_value},
        )

    def validate_attack(self, data: dict[str, Any]) -> ValidationResult:
        # THAC0 validation only applies to AD&D
        if not self._is_add2e:
            return ValidationResult(
                tag_type="ANGRIFF", is_valid=True, severity="ok",
                message="", original_value=data,
            )
        thac0 = data.get("thac0", 20)
        target_ac = data.get("target_ac", 10)
        modifiers = data.get("modifiers", 0)

        issues: list[str] = []
        if isinstance(thac0, int) and not (1 <= thac0 <= 20):
            issues.append(f"THAC0 {thac0} ausserhalb 1-20")
        if isinstance(target_ac, int) and not (-10 <= target_ac <= 10):
            issues.append(f"AC {target_ac} ausserhalb -10 bis 10")
        if isinstance(modifiers, int) and abs(modifiers) > 10:
            issues.append(f"Modifikator {modifiers} ungewoehnlich hoch")

        if issues:
            return ValidationResult(
                tag_type="ANGRIFF", is_valid=len(issues) <= 1,
                severity="warning",
                message="; ".join(issues),
                original_value=data,
            )

        return ValidationResult(
            tag_type="ANGRIFF", is_valid=True, severity="ok",
            message="", original_value=data,
        )

    def validate_saving_throw(self, data: dict[str, Any]) -> ValidationResult:
        category = str(data.get("category", "")).lower()
        target = data.get("target", 20)

        if not any(vc in category for vc in _VALID_SAVE_CATEGORIES):
            return ValidationResult(
                tag_type="RETTUNGSWURF", is_valid=True, severity="warning",
                message=f"Unbekannte Rettungswurf-Kategorie: '{data.get('category')}'",
                original_value=data,
            )

        if isinstance(target, int) and not (2 <= target <= 20):
            return ValidationResult(
                tag_type="RETTUNGSWURF", is_valid=False, severity="warning",
                message=f"Rettungswurf-Zielwert {target} ausserhalb 2-20.",
                original_value=data,
            )

        return ValidationResult(
            tag_type="RETTUNGSWURF", is_valid=True, severity="ok",
            message="", original_value=data,
        )

    def validate_hp_change(
        self,
        change_type: str,
        value_str: str,
        character_stats: dict[str, int] | None = None,
    ) -> ValidationResult:
        # HP_HEILUNG can be a dice expression like "1d6"
        if change_type == "HP_HEILUNG" and re.match(r"^\d+d\d+", value_str.strip()):
            return ValidationResult(
                tag_type=change_type, is_valid=True, severity="ok",
                message="", original_value=value_str,
            )

        try:
            amount = int(value_str.strip())
        except ValueError:
            return ValidationResult(
                tag_type=change_type, is_valid=False, severity="error",
                message=f"'{value_str}' ist keine gueltige Zahl.",
                original_value=value_str,
            )

        max_plausible = 100 if change_type == "HP_VERLUST" else 50
        if amount < 0:
            return ValidationResult(
                tag_type=change_type, is_valid=False, severity="warning",
                message=f"HP-Aenderung sollte positiv sein (erhalten: {amount}).",
                original_value=value_str,
            )
        if amount > max_plausible:
            return ValidationResult(
                tag_type=change_type, is_valid=True, severity="warning",
                message=f"HP-Aenderung {amount} ungewoehnlich hoch (max erwartet: {max_plausible}).",
                original_value=value_str,
            )

        return ValidationResult(
            tag_type=change_type, is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    def validate_san_loss(
        self,
        value_str: str,
        character_stats: dict[str, int] | None = None,
    ) -> ValidationResult:
        if not self._has_sanity:
            return ValidationResult(
                tag_type="STABILITAET_VERLUST", is_valid=False, severity="error",
                message="Dieses Regelwerk hat kein Sanity-System.",
                original_value=value_str,
            )

        expr = value_str.strip().lower()
        dice_match = re.match(r"^(\d+)d(\d+)$", expr)
        if dice_match:
            count = int(dice_match.group(1))
            faces = int(dice_match.group(2))
            max_loss = count * faces
            if max_loss > 20:
                return ValidationResult(
                    tag_type="STABILITAET_VERLUST", is_valid=True, severity="warning",
                    message=f"SAN-Verlust {value_str} (max {max_loss}) ungewoehnlich hoch.",
                    original_value=value_str,
                )
        elif expr.isdigit():
            amount = int(expr)
            if amount > 20:
                return ValidationResult(
                    tag_type="STABILITAET_VERLUST", is_valid=True, severity="warning",
                    message=f"SAN-Verlust {amount} ungewoehnlich hoch.",
                    original_value=value_str,
                )
        else:
            return ValidationResult(
                tag_type="STABILITAET_VERLUST", is_valid=False, severity="error",
                message=f"'{value_str}' ist kein gueltiger Wuerfelausdruck (erwartet: NdN oder N).",
                original_value=value_str,
            )

        return ValidationResult(
            tag_type="STABILITAET_VERLUST", is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    def validate_xp_gain(self, value_str: str) -> ValidationResult:
        try:
            amount = int(value_str.strip())
        except ValueError:
            return ValidationResult(
                tag_type="XP_GEWINN", is_valid=False, severity="error",
                message=f"'{value_str}' ist keine gueltige Zahl.",
                original_value=value_str,
            )

        if amount < 0:
            return ValidationResult(
                tag_type="XP_GEWINN", is_valid=False, severity="error",
                message=f"XP-Gewinn kann nicht negativ sein ({amount}).",
                original_value=value_str,
            )
        if amount > 10000:
            return ValidationResult(
                tag_type="XP_GEWINN", is_valid=True, severity="warning",
                message=f"XP-Gewinn {amount} ungewoehnlich hoch.",
                original_value=value_str,
            )

        return ValidationResult(
            tag_type="XP_GEWINN", is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    def validate_skill_used(self, skill_name: str) -> ValidationResult:
        valid_skills = self.get_skill_names()
        fuzzy = any(
            skill_name.lower() == s.lower()
            or skill_name.lower() in s.lower()
            or s.lower() in skill_name.lower()
            for s in valid_skills
        )

        if not fuzzy:
            return ValidationResult(
                tag_type="FERTIGKEIT_GENUTZT", is_valid=False, severity="warning",
                message=f"Fertigkeit '{skill_name}' nicht im Regelwerk.",
                original_value=skill_name,
            )

        return ValidationResult(
            tag_type="FERTIGKEIT_GENUTZT", is_valid=True, severity="ok",
            message="", original_value=skill_name,
        )

    # -- Monster-Mechanik Validatoren ----------------------------------------

    def validate_magic_resistance(self, value_str: str) -> ValidationResult:
        """Validiert [MAGIC_RESISTANCE: MonsterName | Prozent].

        Erwartet Format: "MonsterName | Prozent" (Prozent 1-100).
        """
        parts = [p.strip() for p in value_str.split("|")]
        if len(parts) != 2:
            return ValidationResult(
                tag_type="MAGIC_RESISTANCE", is_valid=False, severity="error",
                message=(
                    f"MAGIC_RESISTANCE erwartet 'MonsterName | Prozent', "
                    f"erhalten: '{value_str}'"
                ),
                original_value=value_str,
            )
        monster_name, pct_str = parts
        if not monster_name:
            return ValidationResult(
                tag_type="MAGIC_RESISTANCE", is_valid=False, severity="error",
                message="MonsterName darf nicht leer sein.",
                original_value=value_str,
            )
        try:
            pct = int(pct_str)
        except ValueError:
            return ValidationResult(
                tag_type="MAGIC_RESISTANCE", is_valid=False, severity="error",
                message=f"Prozent '{pct_str}' ist keine gueltige Zahl.",
                original_value=value_str,
            )
        if not 1 <= pct <= 100:
            return ValidationResult(
                tag_type="MAGIC_RESISTANCE", is_valid=False, severity="warning",
                message=f"Magieresistenz {pct}% ausserhalb gueltiger Bereich 1-100.",
                original_value=value_str,
                suggested_value=max(1, min(pct, 100)),
            )
        return ValidationResult(
            tag_type="MAGIC_RESISTANCE", is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    def validate_weapon_immunity(self, value_str: str) -> ValidationResult:
        """Validiert [WAFFEN_IMMUNITAET: MonsterName | +N].

        Erwartet Format: "MonsterName | +N" (Bonus +1 bis +5).
        """
        parts = [p.strip() for p in value_str.split("|")]
        if len(parts) != 2:
            return ValidationResult(
                tag_type="WAFFEN_IMMUNITAET", is_valid=False, severity="error",
                message=(
                    f"WAFFEN_IMMUNITAET erwartet 'MonsterName | +N', "
                    f"erhalten: '{value_str}'"
                ),
                original_value=value_str,
            )
        monster_name, bonus_str = parts
        if not monster_name:
            return ValidationResult(
                tag_type="WAFFEN_IMMUNITAET", is_valid=False, severity="error",
                message="MonsterName darf nicht leer sein.",
                original_value=value_str,
            )
        # Akzeptiere "+1", "+2" etc. oder auch "1", "2"
        bonus_clean = bonus_str.lstrip("+").strip()
        try:
            bonus = int(bonus_clean)
        except ValueError:
            return ValidationResult(
                tag_type="WAFFEN_IMMUNITAET", is_valid=False, severity="error",
                message=f"Mindest-Bonus '{bonus_str}' ist nicht erkennbar (erwartet: +1 bis +5).",
                original_value=value_str,
            )
        if not 1 <= bonus <= 5:
            return ValidationResult(
                tag_type="WAFFEN_IMMUNITAET", is_valid=False, severity="warning",
                message=f"Waffen-Bonus +{bonus} ausserhalb gueltiger Bereich +1 bis +5.",
                original_value=value_str,
                suggested_value=max(1, min(bonus, 5)),
            )
        return ValidationResult(
            tag_type="WAFFEN_IMMUNITAET", is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    _VALID_GIFT_TYPEN: frozenset[str] = frozenset({
        "tod", "paralyse", "schaden", "krankheit",
    })

    def validate_poison(self, value_str: str) -> ValidationResult:
        """Validiert [GIFT: MonsterName | Typ | Save-Modifikator].

        Erwartet Format: "MonsterName | Typ | Save-Mod" (-4 bis +4).
        Typen: Tod, Paralyse, Schaden, Krankheit.
        """
        parts = [p.strip() for p in value_str.split("|")]
        if len(parts) != 3:
            return ValidationResult(
                tag_type="GIFT", is_valid=False, severity="error",
                message=(
                    f"GIFT erwartet 'MonsterName | Typ | Save-Mod', "
                    f"erhalten: '{value_str}'"
                ),
                original_value=value_str,
            )
        monster_name, typ, save_mod_str = parts
        if not monster_name:
            return ValidationResult(
                tag_type="GIFT", is_valid=False, severity="error",
                message="MonsterName darf nicht leer sein.",
                original_value=value_str,
            )
        if typ.lower() not in self._VALID_GIFT_TYPEN:
            return ValidationResult(
                tag_type="GIFT", is_valid=False, severity="warning",
                message=(
                    f"Gift-Typ '{typ}' ungueltig. "
                    f"Erlaubt: Tod, Paralyse, Schaden, Krankheit."
                ),
                original_value=value_str,
            )
        try:
            save_mod = int(save_mod_str)
        except ValueError:
            return ValidationResult(
                tag_type="GIFT", is_valid=False, severity="error",
                message=f"Save-Modifikator '{save_mod_str}' ist keine gueltige Zahl.",
                original_value=value_str,
            )
        if not -4 <= save_mod <= 4:
            return ValidationResult(
                tag_type="GIFT", is_valid=False, severity="warning",
                message=f"Save-Modifikator {save_mod:+d} ausserhalb gueltiger Bereich -4 bis +4.",
                original_value=value_str,
                suggested_value=max(-4, min(save_mod, 4)),
            )
        return ValidationResult(
            tag_type="GIFT", is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    def validate_level_drain(self, value_str: str) -> ValidationResult:
        """Validiert [LEVEL_DRAIN: CharName | Stufen].

        Erwartet Format: "CharName | Anzahl_Stufen" (1-4).
        """
        parts = [p.strip() for p in value_str.split("|")]
        if len(parts) != 2:
            return ValidationResult(
                tag_type="LEVEL_DRAIN", is_valid=False, severity="error",
                message=(
                    f"LEVEL_DRAIN erwartet 'CharName | Stufen', "
                    f"erhalten: '{value_str}'"
                ),
                original_value=value_str,
            )
        char_name, stufen_str = parts
        if not char_name:
            return ValidationResult(
                tag_type="LEVEL_DRAIN", is_valid=False, severity="error",
                message="CharName darf nicht leer sein.",
                original_value=value_str,
            )
        try:
            stufen = int(stufen_str)
        except ValueError:
            return ValidationResult(
                tag_type="LEVEL_DRAIN", is_valid=False, severity="error",
                message=f"Stufen '{stufen_str}' ist keine gueltige Zahl.",
                original_value=value_str,
            )
        if not 1 <= stufen <= 4:
            return ValidationResult(
                tag_type="LEVEL_DRAIN", is_valid=False, severity="warning",
                message=f"Level-Drain {stufen} Stufen ausserhalb gueltiger Bereich 1-4.",
                original_value=value_str,
                suggested_value=max(1, min(stufen, 4)),
            )
        return ValidationResult(
            tag_type="LEVEL_DRAIN", is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    def validate_morale_check(self, value_str: str) -> ValidationResult:
        """Validiert [MORAL_CHECK: MonsterName | Schwelle].

        Erwartet Format: "MonsterName | Schwelle" (2-20).
        """
        parts = [p.strip() for p in value_str.split("|")]
        if len(parts) != 2:
            return ValidationResult(
                tag_type="MORAL_CHECK", is_valid=False, severity="error",
                message=(
                    f"MORAL_CHECK erwartet 'MonsterName | Schwelle', "
                    f"erhalten: '{value_str}'"
                ),
                original_value=value_str,
            )
        monster_name, schwelle_str = parts
        if not monster_name:
            return ValidationResult(
                tag_type="MORAL_CHECK", is_valid=False, severity="error",
                message="MonsterName darf nicht leer sein.",
                original_value=value_str,
            )
        try:
            schwelle = int(schwelle_str)
        except ValueError:
            return ValidationResult(
                tag_type="MORAL_CHECK", is_valid=False, severity="error",
                message=f"Schwelle '{schwelle_str}' ist keine gueltige Zahl.",
                original_value=value_str,
            )
        if not 2 <= schwelle <= 20:
            return ValidationResult(
                tag_type="MORAL_CHECK", is_valid=False, severity="warning",
                message=f"Moral-Schwelle {schwelle} ausserhalb gueltiger Bereich 2-20.",
                original_value=value_str,
                suggested_value=max(2, min(schwelle, 20)),
            )
        return ValidationResult(
            tag_type="MORAL_CHECK", is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    def validate_regeneration(self, value_str: str) -> ValidationResult:
        """Validiert [REGENERATION: MonsterName | HP_pro_Runde].

        Erwartet Format: "MonsterName | HP" (1-20).
        """
        parts = [p.strip() for p in value_str.split("|")]
        if len(parts) != 2:
            return ValidationResult(
                tag_type="REGENERATION", is_valid=False, severity="error",
                message=(
                    f"REGENERATION erwartet 'MonsterName | HP_pro_Runde', "
                    f"erhalten: '{value_str}'"
                ),
                original_value=value_str,
            )
        monster_name, hp_str = parts
        if not monster_name:
            return ValidationResult(
                tag_type="REGENERATION", is_valid=False, severity="error",
                message="MonsterName darf nicht leer sein.",
                original_value=value_str,
            )
        try:
            hp = int(hp_str)
        except ValueError:
            return ValidationResult(
                tag_type="REGENERATION", is_valid=False, severity="error",
                message=f"HP/Runde '{hp_str}' ist keine gueltige Zahl.",
                original_value=value_str,
            )
        if not 1 <= hp <= 20:
            return ValidationResult(
                tag_type="REGENERATION", is_valid=False, severity="warning",
                message=f"Regeneration {hp} HP/Runde ausserhalb gueltiger Bereich 1-20.",
                original_value=value_str,
                suggested_value=max(1, min(hp, 20)),
            )
        return ValidationResult(
            tag_type="REGENERATION", is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    _VALID_FURCHT_EFFEKTE: frozenset[str] = frozenset({
        "flucht", "paralyse", "alterung",
    })
    # Akzeptierte Dauer-Muster: Wuerfelausdruck oder 'permanent'
    _FURCHT_DAUER_PATTERN = re.compile(r"^\d+d\d+$|^permanent$", re.IGNORECASE)

    def validate_fear(self, value_str: str) -> ValidationResult:
        """Validiert [FURCHT: CharName | Effekt | Dauer].

        Erwartet Format: "CharName | Effekt | Dauer".
        Effekte: Flucht, Paralyse, Alterung.
        Dauer: Wuerfelausdruck (z.B. 1d6) oder 'permanent'.
        """
        parts = [p.strip() for p in value_str.split("|")]
        if len(parts) != 3:
            return ValidationResult(
                tag_type="FURCHT", is_valid=False, severity="error",
                message=(
                    f"FURCHT erwartet 'CharName | Effekt | Dauer', "
                    f"erhalten: '{value_str}'"
                ),
                original_value=value_str,
            )
        char_name, effekt, dauer = parts
        if not char_name:
            return ValidationResult(
                tag_type="FURCHT", is_valid=False, severity="error",
                message="CharName darf nicht leer sein.",
                original_value=value_str,
            )
        if effekt.lower() not in self._VALID_FURCHT_EFFEKTE:
            return ValidationResult(
                tag_type="FURCHT", is_valid=False, severity="warning",
                message=(
                    f"Furcht-Effekt '{effekt}' ungueltig. "
                    f"Erlaubt: Flucht, Paralyse, Alterung."
                ),
                original_value=value_str,
            )
        if not self._FURCHT_DAUER_PATTERN.match(dauer):
            return ValidationResult(
                tag_type="FURCHT", is_valid=False, severity="warning",
                message=(
                    f"Furcht-Dauer '{dauer}' ungueltig. "
                    f"Erwartet: Wuerfelausdruck (z.B. '1d6') oder 'permanent'."
                ),
                original_value=value_str,
            )
        return ValidationResult(
            tag_type="FURCHT", is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    _VALID_ATEM_TYPEN: frozenset[str] = frozenset({
        "feuer", "kaelte", "blitz", "gift", "saeure", "gas",
    })
    # Wuerfelausdruck: NdN oder NdN+M oder NdN-M
    _DICE_EXPR_PATTERN = re.compile(r"^\d+d\d+([+-]\d+)?$", re.IGNORECASE)

    def validate_breath_weapon(self, value_str: str) -> ValidationResult:
        """Validiert [ATEM_WAFFE: MonsterName | Typ | Schaden].

        Erwartet Format: "MonsterName | Typ | Schaden".
        Typen: Feuer, Kaelte, Blitz, Gift, Saeure, Gas.
        Schaden: Wuerfelausdruck (z.B. 10d10, 3d8).
        """
        parts = [p.strip() for p in value_str.split("|")]
        if len(parts) != 3:
            return ValidationResult(
                tag_type="ATEM_WAFFE", is_valid=False, severity="error",
                message=(
                    f"ATEM_WAFFE erwartet 'MonsterName | Typ | Schaden', "
                    f"erhalten: '{value_str}'"
                ),
                original_value=value_str,
            )
        monster_name, typ, schaden = parts
        if not monster_name:
            return ValidationResult(
                tag_type="ATEM_WAFFE", is_valid=False, severity="error",
                message="MonsterName darf nicht leer sein.",
                original_value=value_str,
            )
        if typ.lower() not in self._VALID_ATEM_TYPEN:
            return ValidationResult(
                tag_type="ATEM_WAFFE", is_valid=False, severity="warning",
                message=(
                    f"Atemwaffe-Typ '{typ}' ungueltig. "
                    f"Erlaubt: Feuer, Kaelte, Blitz, Gift, Saeure, Gas."
                ),
                original_value=value_str,
            )
        if not self._DICE_EXPR_PATTERN.match(schaden):
            return ValidationResult(
                tag_type="ATEM_WAFFE", is_valid=False, severity="warning",
                message=(
                    f"Schaden '{schaden}' ist kein gueltiger Wuerfelausdruck "
                    f"(erwartet: z.B. '10d10', '3d8')."
                ),
                original_value=value_str,
            )
        return ValidationResult(
            tag_type="ATEM_WAFFE", is_valid=True, severity="ok",
            message="", original_value=value_str,
        )

    # ======================================================================
    # Private — Section Indexers
    # ======================================================================

    # Categories that get auto-promoted to permanent (fundamental rules)
    _PERMANENT_CATEGORIES = frozenset({
        "combat", "stats", "saving_throws", "death",
    })
    # Categories auto-promoted to core (important rules)
    _CORE_CATEGORIES = frozenset({
        "tables", "magic", "healing", "conditions", "classes",
        "skills", "economy", "movement", "advancement", "equipment",
        # AD&D 2e
        "proficiencies", "racial_abilities", "turn_undead",
    })

    def _add_section(self, section: RuleSection) -> None:
        # Auto-promote priority for ruleset-derived sections (small, important)
        # Only promote if still at default "support" and section is compact
        if section.priority == "support" and section.char_count < 500:
            if section.category in self._PERMANENT_CATEGORIES:
                section.priority = "permanent"
            elif section.category in self._CORE_CATEGORIES:
                section.priority = "core"

        self._sections[section.section_id] = section
        for kw in section.keywords:
            self._keyword_index.setdefault(kw, []).append(section.section_id)

    # -- Combat --------------------------------------------------------------

    def _index_combat(self) -> None:
        combat = self._ruleset.get("combat")
        if not combat:
            return

        # Initiative
        init_data = combat.get("initiative")
        if init_data:
            if isinstance(init_data, dict):
                text = f"Initiative: {init_data.get('default', 'Gruppeninitiative per d10')}"
                modes = init_data.get("optional_modes", [])
                if modes:
                    text += f". Optionale Modi: {', '.join(modes)}"
            else:
                text = f"Initiative: {init_data}"
            self._add_section(RuleSection(
                section_id="combat.initiative",
                category="combat",
                title="Initiative",
                keywords=_KEYWORD_MAP.get("combat.initiative", []),
                text=text,
            ))

        # Attack resolution
        attack = combat.get("attack_resolution")
        if attack:
            if isinstance(attack, dict):
                text = f"Angriffsloesung: {attack.get('model', 'd20 vs AC')}"
            else:
                text = f"Angriffsloesung: {attack}"
            self._add_section(RuleSection(
                section_id="combat.attack_resolution",
                category="combat",
                title="Angriffsaufloesung",
                keywords=_KEYWORD_MAP.get("combat.attack_resolution", []),
                text=text,
            ))

        # Actions per round
        apr = combat.get("actions_per_round")
        if apr:
            if isinstance(apr, dict):
                text = f"Aktionen/Runde: {apr.get('baseline', '1 Aktion pro Runde')}"
                specials = apr.get("special", [])
                if specials:
                    text += f". Spezial: {', '.join(specials)}"
            else:
                text = f"Aktionen/Runde: {apr}"
            self._add_section(RuleSection(
                section_id="combat.actions",
                category="combat",
                title="Aktionen pro Runde",
                keywords=_KEYWORD_MAP["combat"],
                text=text,
            ))

        # Damage bonus table
        dmg_table = combat.get("damage_bonus_table")
        if dmg_table and isinstance(dmg_table, list):
            rows = []
            for entry in dmg_table:
                cond = entry.get("condition", "")
                bonus = entry.get("damage_bonus") or entry.get("bonus", "0")
                rows.append(f"{cond} = {bonus}")
            text = "Schadensbonus: " + "; ".join(rows)
            self._add_section(RuleSection(
                section_id="combat.damage_bonus",
                category="combat",
                title="Schadensbonus-Tabelle",
                keywords=_KEYWORD_MAP["combat"] + ["schadensbonus", "damage bonus", "build"],
                text=text,
            ))

        # Vehicle combat (Mad Max)
        vehicle = combat.get("vehicle_combat")
        if vehicle and isinstance(vehicle, dict):
            parts = []
            for k, v in vehicle.items():
                if k != "notes":
                    parts.append(f"{k}: {v}")
            text = "Fahrzeugkampf: " + ". ".join(parts)
            if vehicle.get("notes"):
                text += f". {vehicle['notes']}"
            self._add_section(RuleSection(
                section_id="combat.vehicle",
                category="combat",
                title="Fahrzeugkampf",
                keywords=_KEYWORD_MAP.get("combat.vehicle", []),
                text=text,
            ))

        # Combat flow
        flow = combat.get("flow")
        if flow and isinstance(flow, list):
            text = "Kampfablauf: " + " -> ".join(
                step.replace("_", " ").title() for step in flow
            )
            self._add_section(RuleSection(
                section_id="combat.flow",
                category="combat",
                title="Kampfablauf",
                keywords=_KEYWORD_MAP["combat"],
                text=text,
            ))

        # Saving throws in combat
        stc = combat.get("saving_throw_in_combat")
        if stc and isinstance(stc, dict):
            cats = stc.get("categories", [])
            if cats:
                text = "Rettungswurf-Kategorien: " + ", ".join(
                    c.replace("_", " ").title() for c in cats
                )
                self._add_section(RuleSection(
                    section_id="combat.saving_throws",
                    category="combat",
                    title="Rettungswuerfe im Kampf",
                    keywords=_KEYWORD_MAP.get("saving_throws", []),
                    text=text,
                ))

        # Impalement (CoC)
        impale = combat.get("impalement")
        if impale and isinstance(impale, dict):
            text = f"Aufspiessung: {impale.get('rules', '')}"
            self._add_section(RuleSection(
                section_id="combat.impalement",
                category="combat",
                title="Aufspiessung",
                keywords=_KEYWORD_MAP["combat"] + ["aufspiessung", "impalement", "critical"],
                text=text,
            ))

        # Ammo tracking
        if combat.get("ammo_tracking"):
            notes = combat.get("notes", "Munition ist begrenzt.")
            self._add_section(RuleSection(
                section_id="combat.ammo",
                category="combat",
                title="Munitionsverfolgung",
                keywords=["munition", "ammo", "schuss", "nachladen", "ladehemmung"],
                text=f"Munition: {notes}",
            ))

        # Missile combat
        missile = combat.get("missile_combat")
        if missile and isinstance(missile, dict):
            fields = missile.get("fields", [])
            text = "Fernkampf: " + ", ".join(
                f.replace("_", " ").title() for f in fields
            )
            self._add_section(RuleSection(
                section_id="combat.missile",
                category="combat",
                title="Fernkampf",
                keywords=_KEYWORD_MAP["combat"] + ["fernkampf", "bogen", "armbrust", "missile"],
                text=text,
            ))

    # -- Sanity ---------------------------------------------------------------

    def _index_sanity(self) -> None:
        sanity = self._ruleset.get("sanity")
        if not sanity:
            return

        parts: list[str] = []
        parts.append(f"Start-SAN: {sanity.get('starting_san', 'POW*5')}")
        parts.append(f"Max-SAN: {sanity.get('max_san', 99)}")

        threshold = sanity.get("temporary_insanity_threshold")
        if threshold:
            pct = int(threshold * 100) if isinstance(threshold, float) else threshold
            parts.append(f"Temporaerer Wahnsinn: Verlust >= {pct}% der aktuellen SAN")

        indef = sanity.get("indefinite_insanity_threshold")
        if indef:
            parts.append(f"Indefiniter Wahnsinn bei SAN <= {indef}")

        notes = sanity.get("notes", "")
        if notes:
            parts.append(notes)

        text = ". ".join(parts)
        self._add_section(RuleSection(
            section_id="sanity.overview",
            category="sanity",
            title="Geistesgesundheit (SAN)",
            keywords=_KEYWORD_MAP.get("sanity", []),
            text=text,
        ))

    # -- Survival -------------------------------------------------------------

    def _index_survival(self) -> None:
        survival = self._ruleset.get("survival")
        if not survival:
            return

        for key, data in survival.items():
            if not isinstance(data, dict):
                continue
            parts: list[str] = []
            for k, v in data.items():
                if k not in ("notes",):
                    parts.append(f"{k}: {v}")
            notes = data.get("notes", "")
            if notes:
                parts.append(notes)
            text = ". ".join(parts)

            self._add_section(RuleSection(
                section_id=f"survival.{key}",
                category="survival",
                title=f"Ueberleben: {key.replace('_', ' ').title()}",
                keywords=_KEYWORD_MAP.get("survival", []) + [key],
                text=text,
            ))

    # -- Derived Stats --------------------------------------------------------

    def _index_derived_stats(self) -> None:
        ds = self._ruleset.get("derived_stats")
        if not ds:
            return

        parts: list[str] = []
        for stat_name, stat_data in ds.items():
            if isinstance(stat_data, dict):
                label = stat_data.get("label", stat_name)
                formula = stat_data.get("formula", "")
                notes = stat_data.get("notes", "")
                line = f"{label} ({stat_name}): {formula}"
                if notes:
                    line += f" — {notes}"
                parts.append(line)

        if parts:
            self._add_section(RuleSection(
                section_id="stats.formulas",
                category="stats",
                title="Abgeleitete Werte",
                keywords=_KEYWORD_MAP.get("stats", []) + ["hp", "san", "mp", "ac", "thac0"],
                text=". ".join(parts),
            ))

    # -- Advancement ----------------------------------------------------------

    def _index_advancement(self) -> None:
        adv = self._ruleset.get("advancement")
        if not adv:
            return

        parts: list[str] = []
        method = adv.get("method", "")
        parts.append(f"Methode: {method}")
        notes = adv.get("notes", "")
        if notes:
            parts.append(notes)

        self._add_section(RuleSection(
            section_id="advancement.overview",
            category="advancement",
            title="Steigerung & Erfahrung",
            keywords=_KEYWORD_MAP.get("advancement", []),
            text=". ".join(parts),
        ))

    # -- Healing --------------------------------------------------------------

    def _index_healing(self) -> None:
        healing = self._ruleset.get("healing")
        if not healing:
            return

        if isinstance(healing, dict):
            parts = []
            for k, v in healing.items():
                if isinstance(v, str):
                    parts.append(f"{k}: {v}")
                elif isinstance(v, list):
                    parts.append(f"{k}: {', '.join(v)}")
            text = ". ".join(parts) if parts else str(healing)
        else:
            text = str(healing)

        self._add_section(RuleSection(
            section_id="healing.overview",
            category="healing",
            title="Heilung & Tod",
            keywords=_KEYWORD_MAP.get("healing", []),
            text=text,
        ))

    # -- Conditions -----------------------------------------------------------

    def _index_conditions(self) -> None:
        cond = self._ruleset.get("conditions")
        if not cond:
            return

        if isinstance(cond, dict):
            parts = []
            for k, v in cond.items():
                if isinstance(v, list):
                    parts.append(f"{k}: {', '.join(str(x) for x in v)}")
                else:
                    parts.append(f"{k}: {v}")
            text = ". ".join(parts)
        else:
            text = str(cond)

        self._add_section(RuleSection(
            section_id="conditions.overview",
            category="conditions",
            title="Zustaende & Statuseffekte",
            keywords=_KEYWORD_MAP.get("conditions", []),
            text=text,
        ))

    # -- Economy --------------------------------------------------------------

    def _index_economy(self) -> None:
        econ = self._ruleset.get("economy")
        if not econ:
            return

        if isinstance(econ, dict):
            parts = []
            currencies = econ.get("currencies", [])
            if currencies:
                parts.append(f"Waehrungen: {', '.join(currencies)}")
            exchange = econ.get("exchange")
            if exchange and isinstance(exchange, dict):
                rates = [f"{k}={v}" for k, v in exchange.items()]
                parts.append(f"Wechselkurse: {', '.join(rates)}")
            text = ". ".join(parts) if parts else str(econ)
        else:
            text = str(econ)

        self._add_section(RuleSection(
            section_id="economy.overview",
            category="economy",
            title="Wirtschaft & Waehrung",
            keywords=_KEYWORD_MAP.get("economy", []),
            text=text,
        ))

    # -- Magic ----------------------------------------------------------------

    def _index_magic(self) -> None:
        magic = self._ruleset.get("magic")
        if not magic:
            return

        # Arcane
        arcane = magic.get("arcane")
        if arcane and isinstance(arcane, dict):
            schools = arcane.get("schools", [])
            text = "Arkane Magie — Schulen: " + ", ".join(schools)
            self._add_section(RuleSection(
                section_id="magic.arcane",
                category="magic",
                title="Arkane Magie",
                keywords=_KEYWORD_MAP.get("magic", []) + ["arkane", "school", "schule"],
                text=text,
            ))

        # Divine
        divine = magic.get("divine")
        if divine and isinstance(divine, dict):
            spheres = divine.get("spheres", [])
            text = "Goettliche Magie — Sphaeren: " + ", ".join(spheres)
            self._add_section(RuleSection(
                section_id="magic.divine",
                category="magic",
                title="Goettliche Magie",
                keywords=_KEYWORD_MAP.get("magic", []) + ["goettlich", "divine", "sphaere", "sphere"],
                text=text,
            ))

        # Casting
        casting = magic.get("casting")
        if casting and isinstance(casting, dict):
            parts = []
            parts.append(f"Vorbereitung: {casting.get('preparation', '?')}")
            comps = casting.get("components", [])
            if comps:
                parts.append(f"Komponenten: {', '.join(comps)}")
            ct = casting.get("casting_time", "")
            if ct:
                parts.append(f"Wirkzeit: {ct}")
            disrupt = casting.get("disruption", "")
            if disrupt:
                parts.append(f"Stoerung: {disrupt}")
            self._add_section(RuleSection(
                section_id="magic.casting",
                category="magic",
                title="Zauberwirken",
                keywords=_KEYWORD_MAP.get("magic", []) + ["wirken", "casting", "komponente"],
                text=". ".join(parts),
            ))

    # -- Saving Throws --------------------------------------------------------

    def _index_saving_throws(self) -> None:
        st = self._ruleset.get("saving_throws")
        if not st:
            return

        cats = st.get("categories", [])
        if cats:
            text = "Rettungswurf-Kategorien: " + ", ".join(
                c.replace("_", " ").title() for c in cats
            )
            self._add_section(RuleSection(
                section_id="saving_throws.overview",
                category="saving_throws",
                title="Rettungswuerfe",
                keywords=_KEYWORD_MAP.get("saving_throws", []),
                text=text,
            ))

    # -- Classes --------------------------------------------------------------

    def _index_classes(self) -> None:
        classes = self._ruleset.get("classes")
        if not classes:
            return

        parts: list[str] = []
        for cls_name, cls_data in classes.items():
            if not isinstance(cls_data, dict):
                continue
            hit_die = cls_data.get("hit_die", "?")
            subs = cls_data.get("subclasses", [])
            features = cls_data.get("core_features", [])
            line = f"{cls_name.title()} ({hit_die})"
            if subs:
                line += f": {', '.join(subs)}"
            if features:
                line += f" — {'; '.join(features)}"
            parts.append(line)

        if parts:
            self._add_section(RuleSection(
                section_id="classes.overview",
                category="classes",
                title="Klassen-Uebersicht",
                keywords=_KEYWORD_MAP.get("classes", []),
                text=". ".join(parts),
            ))

    # -- Lore Chunks (fulltext rules from data/lore/) --------------------------

    def _index_lore_chunks(self) -> None:
        """Load lore chunks from data/lore/{system_id}/ into index.

        Scans multiple subdirectories in priority order:
        1. rules_fulltext_chunks/ — new format with topic/keywords/priority
        2. chapters/ — chapter-level dumps with source_text.text
        3. fulltext/ — page-level dumps with source_text.text
        """
        from pathlib import Path
        base_dir = Path(__file__).parent.parent / "data" / "lore" / self._module_name

        if not base_dir.is_dir():
            logger.debug("No lore dir: %s", base_dir)
            return

        # Scan directories in priority order
        scan_dirs = [
            ("rules_fulltext_chunks", "chunk"),
            ("chapters", "chapter"),
            ("fulltext", "page"),
        ]

        loaded = 0
        for subdir_name, source_kind in scan_dirs:
            lore_dir = base_dir / subdir_name
            if not lore_dir.is_dir():
                continue

            for fp in sorted(lore_dir.glob("*.json")):
                try:
                    with fp.open(encoding="utf-8") as fh:
                        data = json.load(fh)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Skipping bad chunk %s: %s", fp.name, exc)
                    continue

                mechanics = data.get("mechanics", {})
                source_text = data.get("source_text", {})

                # Extract raw text — try mechanics.raw_text first, then source_text.text
                raw_text = mechanics.get("raw_text", "")
                if not raw_text:
                    raw_text = source_text.get("text", "")
                if not raw_text:
                    continue

                chunk_id = data.get("id", fp.stem)
                # Skip if already indexed (ruleset sections take precedence)
                if chunk_id in self._sections:
                    continue

                topic = mechanics.get("topic", "general")
                priority = mechanics.get("injection_priority", "support")
                kw_list = mechanics.get("keywords", [])

                # Fallback: extract keywords from tags if chunk has no keywords
                if not kw_list:
                    tags = data.get("tags", [])
                    kw_list = [t for t in tags if t not in (
                        self._module_name, "rules", "injection_chunk",
                        "player_handbook", "fulltext", "pdf_page",
                        "chapter", "book_page")]

                # For chapters/pages: derive keywords from slug words
                if not kw_list and source_kind in ("chapter", "page"):
                    slug = source_text.get("chapter_slug", "")
                    if slug:
                        kw_list = [w for w in slug.split("_")
                                   if len(w) > 2 and w not in ("and", "the")]

                # For chapters: derive topic from chapter slug
                if source_kind == "chapter" and topic == "general":
                    slug = source_text.get("chapter_slug", "")
                    if slug:
                        topic = slug  # e.g. "combat", "magic", "experience"

                summary = data.get("summary", chunk_id)

                self._add_section(RuleSection(
                    section_id=chunk_id,
                    category=topic,
                    title=summary,
                    keywords=kw_list,
                    text=raw_text,
                    priority=priority,
                ))
                loaded += 1

        if loaded:
            logger.info("Indexed %d lore chunks from %s", loaded, base_dir)

    # -- Tables (AD&D 2e) ----------------------------------------------------

    def _index_tables(self) -> None:
        tables = self._tables
        if not tables:
            return

        # THAC0
        thac0 = tables.get("thac0_by_group")
        if thac0:
            parts = []
            for group, values in thac0.items():
                if group.startswith("_"):
                    continue
                parts.append(f"{group}: L1={values[0]}, L10={values[9]}, L20={values[19]}")
            self._add_section(RuleSection(
                section_id="tables.thac0",
                category="tables",
                title="THAC0-Tabelle",
                keywords=["thac0", "angriffswurf", "attack", "treffer"] + _KEYWORD_MAP["combat"],
                text="THAC0 nach Klasse/Level: " + ". ".join(parts),
            ))

        # Saving throws table
        saves = tables.get("saving_throws")
        if saves:
            save_types = saves.get("save_types", [])
            groups = [g for g in saves if not g.startswith("_") and g != "save_types"]
            text = f"Rettungswurf-Kategorien: {', '.join(save_types)}. Gruppen: {', '.join(groups)}"
            self._add_section(RuleSection(
                section_id="tables.saving_throws",
                category="tables",
                title="Rettungswurf-Tabellen",
                keywords=_KEYWORD_MAP.get("saving_throws", []) + ["save", "rettungswurf"],
                text=text,
            ))

        # Hit dice
        hd = tables.get("hit_dice")
        if hd:
            parts = []
            for group, data in hd.items():
                if group.startswith("_"):
                    continue
                if isinstance(data, dict):
                    parts.append(f"{group}: {data.get('die', '?')}")
            self._add_section(RuleSection(
                section_id="tables.hit_dice",
                category="tables",
                title="Trefferwuerfel",
                keywords=["trefferwuerfel", "hit dice", "hp", "lebenspunkte"],
                text="Trefferwuerfel: " + ", ".join(parts),
            ))

        # Attacks per round
        apr = tables.get("attacks_per_round")
        if apr:
            parts = []
            for group, entries in apr.items():
                if group.startswith("_"):
                    continue
                if isinstance(entries, list):
                    for e in entries:
                        parts.append(f"{group} L{e['levels']}: {e['attacks']}")
            self._add_section(RuleSection(
                section_id="tables.attacks_per_round",
                category="tables",
                title="Angriffe pro Runde",
                keywords=["angriffe", "attacks", "runde", "round", "mehrfachangriff"],
                text=". ".join(parts),
            ))

        # Armor class
        ac = tables.get("armor_class_table")
        if ac and isinstance(ac, dict):
            rows = [f"{k}: AC {v}" for k, v in ac.items() if not k.startswith("_")]
            self._add_section(RuleSection(
                section_id="tables.armor_class",
                category="tables",
                title="Ruestungsklasse-Tabelle",
                keywords=["ruestung", "armor", "ac", "ruestungsklasse", "schild", "shield"],
                text=". ".join(rows),
            ))

        # Combat modifiers
        cm = tables.get("combat_modifiers")
        if cm and isinstance(cm, dict):
            rows = [f"{k.replace('_', ' ')}: {v:+d}" if isinstance(v, int) else f"{k.replace('_', ' ')}: {v}"
                    for k, v in cm.items() if not k.startswith("_")]
            self._add_section(RuleSection(
                section_id="tables.combat_modifiers",
                category="tables",
                title="Kampfmodifikatoren",
                keywords=_KEYWORD_MAP["combat"] + ["modifikator", "modifier", "bonus", "malus"],
                text=". ".join(rows),
            ))

        # Backstab
        bs = tables.get("backstab_multiplier")
        if bs and isinstance(bs, dict):
            rows = [f"Level {k}: x{v}" for k, v in bs.items() if not k.startswith("_")]
            self._add_section(RuleSection(
                section_id="tables.backstab",
                category="tables",
                title="Hinterhalt-Multiplikator",
                keywords=["backstab", "hinterhalt", "meucheln", "dieb", "thief"],
                text="Backstab: " + ", ".join(rows),
            ))

        # Thieving skills base
        ts = tables.get("thieving_skills_base")
        if ts and isinstance(ts, dict):
            rows = [f"{k.replace('_', ' ').title()}: {v}%"
                    for k, v in ts.items() if not k.startswith("_")]
            self._add_section(RuleSection(
                section_id="tables.thieving_skills",
                category="tables",
                title="Diebes-Fertigkeiten (Basis)",
                keywords=["dieb", "thief", "rogue", "schloss", "falle", "schleichen"],
                text=", ".join(rows),
            ))

        # Monster THAC0
        mt = tables.get("monster_thac0", {}).get("by_hd")
        if mt and isinstance(mt, dict):
            rows = [f"HD {k}: THAC0 {v}" for k, v in mt.items() if not k.startswith("_")]
            self._add_section(RuleSection(
                section_id="tables.monster_thac0",
                category="tables",
                title="Monster-THAC0 nach Hit Dice",
                keywords=["monster", "thac0", "hit dice", "npc", "gegner"],
                text=". ".join(rows),
            ))

        # --- New AD&D 2e table indexers (v2.0.0 tables) ---

        # Weapon tables
        melee = tables.get("melee_weapons")
        if melee and isinstance(melee, list):
            rows = []
            for w in melee[:10]:  # top 10 for injection budget
                rows.append(
                    f"{w['name']}: {w['damage_sm']}/{w['damage_l']}, "
                    f"Spd {w['speed']}, {w['size']}, {w['type']}"
                )
            self._add_section(RuleSection(
                section_id="tables.melee_weapons",
                category="equipment",
                title="Nahkampfwaffen-Tabelle",
                keywords=_KEYWORD_MAP["combat"] + ["waffe", "weapon", "schaden",
                         "schwert", "axt", "dolch", "keule", "streitkolben"],
                text="Nahkampfwaffen (Schaden S-M/L, Speed, Groesse, Typ): " + ". ".join(rows),
            ))

        missile = tables.get("missile_weapons")
        if missile and isinstance(missile, list):
            rows = []
            for w in missile[:8]:
                rows.append(
                    f"{w['name']}: {w['damage_sm']}/{w['damage_l']}, "
                    f"ROF {w['rof']}, Range {w['range_s']}/{w['range_m']}/{w['range_l']}"
                )
            self._add_section(RuleSection(
                section_id="tables.missile_weapons",
                category="equipment",
                title="Fernkampfwaffen-Tabelle",
                keywords=_KEYWORD_MAP["combat"] + ["fernkampf", "bogen", "armbrust",
                         "missile", "reichweite", "range", "schiessen"],
                text="Fernkampf (Schaden S-M/L, ROF, Reichweite S/M/L): " + ". ".join(rows),
            ))

        # Spell slot progression
        wiz_slots = tables.get("wizard_spell_slots")
        if wiz_slots and isinstance(wiz_slots, dict):
            sample = []
            for lvl in ["1", "5", "10", "15", "20"]:
                slots = wiz_slots.get(lvl)
                if slots:
                    non_zero = [f"L{i+1}:{s}" for i, s in enumerate(slots) if s > 0]
                    sample.append(f"Wiz L{lvl}: {', '.join(non_zero)}")
            self._add_section(RuleSection(
                section_id="tables.wizard_spell_slots",
                category="magic",
                title="Magier-Zauberplaetze",
                keywords=_KEYWORD_MAP.get("spell_slots", []) + ["magier", "wizard", "arkane"],
                text=". ".join(sample),
            ))

        pri_slots = tables.get("priest_spell_slots")
        if pri_slots and isinstance(pri_slots, dict):
            sample = []
            for lvl in ["1", "5", "9", "14", "20"]:
                slots = pri_slots.get(lvl)
                if slots:
                    non_zero = [f"L{i+1}:{s}" for i, s in enumerate(slots) if s > 0]
                    sample.append(f"Priest L{lvl}: {', '.join(non_zero)}")
            self._add_section(RuleSection(
                section_id="tables.priest_spell_slots",
                category="magic",
                title="Priester-Zauberplaetze",
                keywords=_KEYWORD_MAP.get("spell_slots", []) + ["priester", "priest", "kleriker",
                         "cleric", "goettlich", "divine"],
                text=". ".join(sample),
            ))

        # Turn Undead
        tu = tables.get("turn_undead")
        if tu and isinstance(tu, dict):
            sample = []
            for lvl in ["1", "3", "5", "7", "9"]:
                entry = tu.get(lvl, {})
                if entry:
                    vals = [f"{k}:{v}" for k, v in entry.items()
                            if not k.startswith("_") and v != "-"]
                    sample.append(f"Priest L{lvl}: {', '.join(vals[:5])}")
            self._add_section(RuleSection(
                section_id="tables.turn_undead",
                category="tables",
                title="Untote Vertreiben",
                keywords=_KEYWORD_MAP.get("turn_undead", []),
                text="Turn Undead (Wuerfelwert oder T=auto, D=zerstoert): " + ". ".join(sample),
            ))

        # Non-weapon Proficiencies
        nwp = tables.get("nonweapon_proficiencies")
        if nwp and isinstance(nwp, list):
            groups = {}
            for p in nwp:
                for g in p.get("groups", ["general"]):
                    groups.setdefault(g, []).append(p["name"])
            parts = [f"{g.title()}: {', '.join(names[:8])}"
                     for g, names in sorted(groups.items())]
            self._add_section(RuleSection(
                section_id="tables.proficiencies",
                category="skills",
                title="Nicht-Waffen-Fertigkeiten",
                keywords=_KEYWORD_MAP.get("proficiencies", []),
                text="NWP nach Gruppe: " + ". ".join(parts),
            ))

        # Armor catalog
        armor = tables.get("armor_catalog")
        if armor and isinstance(armor, list):
            rows = [f"{a['name']}: AC {a['ac']}, {a['weight']} lb, {a['cost_gp']} gp"
                    for a in armor if not isinstance(a.get("name"), type(None))]
            self._add_section(RuleSection(
                section_id="tables.armor",
                category="equipment",
                title="Ruestungs-Katalog",
                keywords=["ruestung", "armor", "ac", "schild", "shield",
                          "leder", "kette", "platte", "leather", "chain", "plate"],
                text=". ".join(rows),
            ))

    # -- AD&D 2e Racial Abilities (from expanded races in ruleset) ----------

    def _index_racial_abilities(self) -> None:
        """Index AD&D 2e racial abilities for context injection."""
        if not self._is_add2e:
            return
        races = self._ruleset.get("races", {})
        if not races:
            return

        parts: list[str] = []
        for race_id, data in races.items():
            if not isinstance(data, dict):
                continue
            name = race_id.replace("_", "-").title()
            adj = data.get("ability_adjustments", {})
            specials = data.get("special_abilities", [])
            movement = data.get("movement", 12)
            adj_str = ", ".join(f"{k}{v:+d}" for k, v in adj.items()) if adj else "keine"
            spec_str = ", ".join(specials[:4]) if specials else "keine"
            parts.append(f"{name}: Bew {movement}, Adj {adj_str}, Spezial: {spec_str}")

        if parts:
            self._add_section(RuleSection(
                section_id="add2e.racial_abilities",
                category="classes",
                title="Rassenfaehigkeiten (AD&D 2e)",
                keywords=_KEYWORD_MAP.get("racial_abilities", []),
                text=". ".join(parts),
            ))
