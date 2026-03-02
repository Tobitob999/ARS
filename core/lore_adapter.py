"""
core/lore_adapter.py — Lore-Adapter: Raw-Extrakte → Engine-kompatible Felder

Jedes Regelsystem speichert NPCs, Items, Organisationen etc. in eigenen
Feld-Formaten.  Die Engine (_build_adventure_block) erwartet aber fixe
Feldnamen wie  name, role, personality, secrets, dialogue_hints, physical_description.

Dieser Adapter fuegt die fehlenden Felder hinzu, ohne die Rohdaten zu
loeschen — so bleibt alles transparent und debugging-faehig.

Aufgerufen aus ai_backend._load_and_merge_lore() NACH dem Laden.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("ARS.lore_adapter")


# ---------------------------------------------------------------------------
# Adapter-Registry
# ---------------------------------------------------------------------------

def adapt_lore(adventure: dict[str, Any], system_id: str) -> dict[str, Any]:
    """Wendet system-spezifische Feld-Mappings auf alle Lore-Kategorien an.

    Gibt das (in-place) modifizierte adventure-Dict zurueck.
    """
    adapter = _SYSTEM_ADAPTERS.get(system_id)
    if adapter is None:
        # Fallback: generischer Adapter fuer unbekannte Systeme
        adapter = _adapt_generic
    adapted_count = adapter(adventure)
    if adapted_count:
        logger.info("Lore-Adapter (%s): %d Eintraege angepasst.", system_id, adapted_count)
    return adventure


# ---------------------------------------------------------------------------
# Generischer Adapter (Fallback)
# ---------------------------------------------------------------------------

def _adapt_generic(adventure: dict[str, Any]) -> int:
    """Generischer Adapter: fuellt fehlende Engine-Felder aus gaengigen Alternativen."""
    count = 0
    for npc in adventure.get("npcs", []):
        if _adapt_npc_generic(npc):
            count += 1
    for item in adventure.get("items", []):
        if _adapt_item_generic(item):
            count += 1
    for org in adventure.get("organizations", []):
        if _adapt_org_generic(org):
            count += 1
    for ent in adventure.get("entities", []):
        if _adapt_entity_generic(ent):
            count += 1
    return count


def _adapt_npc_generic(npc: dict[str, Any]) -> bool:
    """Fuellt fehlende NPC-Felder aus mechanics/summary."""
    changed = False
    mech = npc.get("mechanics", {})

    if not npc.get("role") and not npc.get("occupation"):
        role = mech.get("service_group", mech.get("class", mech.get("archetype", "")))
        if role:
            npc["role"] = role
            changed = True

    if not npc.get("personality") and not npc.get("description") and not npc.get("traits"):
        trait = mech.get("trait", mech.get("personality", ""))
        if trait:
            npc["personality"] = trait
            changed = True
        elif npc.get("summary"):
            npc["personality"] = npc["summary"]
            changed = True

    if not npc.get("secrets") and not npc.get("secret"):
        secret_parts = []
        if mech.get("secret_society"):
            secret_parts.append(f"Secret Society: {mech['secret_society']}")
        if mech.get("mutation"):
            secret_parts.append(f"Mutation: {mech['mutation']}")
        if mech.get("hidden_agenda"):
            secret_parts.append(f"Hidden Agenda: {mech['hidden_agenda']}")
        if secret_parts:
            npc["secrets"] = secret_parts
            changed = True

    if not npc.get("dialogue_hints"):
        use = mech.get("use_in_play", mech.get("play_hook", ""))
        if use:
            npc["dialogue_hints"] = [f"Use-in-play: {use}"]
            changed = True

    return changed


def _adapt_item_generic(item: dict[str, Any]) -> bool:
    """Fuellt fehlende Item-Felder aus mechanics/summary."""
    changed = False
    mech = item.get("mechanics", {})

    if not item.get("physical_description"):
        parts = []
        if mech.get("use_case"):
            parts.append(mech["use_case"])
        if mech.get("clearance_required"):
            parts.append(f"Clearance: {mech['clearance_required']}")
        if mech.get("risk"):
            parts.append(f"Risk: {mech['risk']}")
        if mech.get("charges"):
            parts.append(f"Charges: {mech['charges']}")
        if parts:
            item["physical_description"] = " | ".join(parts)
            changed = True
        elif item.get("summary"):
            item["physical_description"] = item["summary"]
            changed = True

    return changed


def _adapt_org_generic(org: dict[str, Any]) -> bool:
    """Fuellt fehlende Org-Felder aus mechanics/summary."""
    changed = False
    mech = org.get("mechanics", {})

    if not org.get("true_purpose") and not org.get("public_facade"):
        hook = mech.get("play_hook", "")
        if hook:
            org["public_facade"] = hook
            changed = True
        elif org.get("summary"):
            org["public_facade"] = org["summary"]
            changed = True

    return changed


def _adapt_entity_generic(ent: dict[str, Any]) -> bool:
    """Fuellt fehlende Entity-Felder aus mechanics/summary."""
    changed = False
    mech = ent.get("mechanics", {})

    if not ent.get("description"):
        summary = ent.get("summary", "")
        if summary:
            ent["description"] = summary
            changed = True

    if not ent.get("weakness"):
        gm_notes = mech.get("gm_notes", [])
        detection = mech.get("detection_risk", "")
        if gm_notes:
            ent["weakness"] = "; ".join(gm_notes[:2])
            changed = True
        elif detection:
            ent["weakness"] = detection
            changed = True

    return changed


# ---------------------------------------------------------------------------
# Paranoia 2E Adapter
# ---------------------------------------------------------------------------

def _adapt_paranoia(adventure: dict[str, Any]) -> int:
    """Paranoia-spezifisch: Service Group + Clearance als Role, etc."""
    count = 0

    for npc in adventure.get("npcs", []):
        mech = npc.get("mechanics", {})
        changed = False

        # Role: Service Group + Clearance
        if not npc.get("role") and not npc.get("occupation"):
            sg = mech.get("service_group", "")
            cl = mech.get("clearance", "")
            if sg or cl:
                npc["role"] = f"{sg} — {cl}".strip(" —") if sg and cl else (sg or cl)
                changed = True

        # Personality: trait
        if not npc.get("personality") and not npc.get("description") and not npc.get("traits"):
            trait = mech.get("trait", "")
            if trait:
                npc["personality"] = trait
                changed = True
            elif npc.get("summary"):
                npc["personality"] = npc["summary"]
                changed = True

        # Secrets: secret_society + mutation
        if not npc.get("secrets") and not npc.get("secret"):
            secret_parts = []
            if mech.get("secret_society"):
                secret_parts.append(f"Secret Society: {mech['secret_society']}")
            if mech.get("mutation"):
                secret_parts.append(f"Mutation: {mech['mutation']}")
            if secret_parts:
                npc["secrets"] = secret_parts
                changed = True

        # Dialogue hints: use_in_play
        if not npc.get("dialogue_hints"):
            use = mech.get("use_in_play", "")
            if use:
                npc["dialogue_hints"] = [f"Use-in-play: {use}"]
                changed = True

        if changed:
            count += 1

    # Items: gear_catalog Felder
    for item in adventure.get("items", []):
        if _adapt_item_generic(item):
            count += 1

    # Organizations: secret_societies + service_groups
    for org in adventure.get("organizations", []):
        if _adapt_org_generic(org):
            count += 1

    # Entities: mutations
    for ent in adventure.get("entities", []):
        if _adapt_entity_generic(ent):
            count += 1

    return count


# ---------------------------------------------------------------------------
# AD&D 2E Adapter
# ---------------------------------------------------------------------------

def _adapt_add2e(adventure: dict[str, Any]) -> int:
    """AD&D 2e: raw_text als Fallback, class/level als Role."""
    count = 0

    for npc in adventure.get("npcs", []):
        mech = npc.get("mechanics", {})
        changed = False

        if not npc.get("role") and not npc.get("occupation"):
            cls = mech.get("class", mech.get("archetype", ""))
            level = mech.get("level", "")
            if cls:
                npc["role"] = f"{cls} (Lvl {level})" if level else cls
                changed = True

        if not npc.get("personality") and not npc.get("description") and not npc.get("traits"):
            raw = npc.get("raw_text", npc.get("summary", ""))
            if raw:
                npc["personality"] = raw[:300]
                changed = True

        if changed:
            count += 1

    for item in adventure.get("items", []):
        changed = False
        mech = item.get("mechanics", {})
        if not item.get("physical_description"):
            raw = item.get("raw_text", item.get("summary", ""))
            if raw:
                item["physical_description"] = raw[:200]
                changed = True
        if changed:
            count += 1

    for ent in adventure.get("entities", []):
        if _adapt_entity_generic(ent):
            count += 1

    return count


# ---------------------------------------------------------------------------
# Cthulhu 7E Adapter
# ---------------------------------------------------------------------------

def _adapt_cthulhu(adventure: dict[str, Any]) -> int:
    """Cthulhu 7e: meist bereits gut gemappt, nur Luecken fuellen."""
    count = 0
    for npc in adventure.get("npcs", []):
        if _adapt_npc_generic(npc):
            count += 1
    for item in adventure.get("items", []):
        if _adapt_item_generic(item):
            count += 1
    for org in adventure.get("organizations", []):
        if _adapt_org_generic(org):
            count += 1
    for ent in adventure.get("entities", []):
        if _adapt_entity_generic(ent):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Shadowrun 6 Adapter
# ---------------------------------------------------------------------------

def _adapt_shadowrun(adventure: dict[str, Any]) -> int:
    """Shadowrun 6: Archetype als Role, Metatyp in Personality."""
    count = 0

    for npc in adventure.get("npcs", []):
        mech = npc.get("mechanics", {})
        changed = False

        if not npc.get("role") and not npc.get("occupation"):
            archetype = mech.get("archetype", mech.get("role", ""))
            metatype = mech.get("metatype", "")
            if archetype:
                npc["role"] = f"{archetype} ({metatype})" if metatype else archetype
                changed = True

        if not npc.get("personality") and not npc.get("description") and not npc.get("traits"):
            summary = npc.get("summary", "")
            if summary:
                npc["personality"] = summary
                changed = True

        if not npc.get("secrets") and not npc.get("secret"):
            affiliation = mech.get("affiliation", mech.get("faction", ""))
            if affiliation:
                npc["secrets"] = [f"Affiliation: {affiliation}"]
                changed = True

        if changed:
            count += 1

    for item in adventure.get("items", []):
        if _adapt_item_generic(item):
            count += 1
    for org in adventure.get("organizations", []):
        if _adapt_org_generic(org):
            count += 1
    for ent in adventure.get("entities", []):
        if _adapt_entity_generic(ent):
            count += 1

    return count


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_SYSTEM_ADAPTERS: dict[str, Any] = {
    "paranoia_2e": _adapt_paranoia,
    "paranoia": _adapt_paranoia,
    "add_2e": _adapt_add2e,
    "cthulhu_7e": _adapt_cthulhu,
    "cthulhu": _adapt_cthulhu,
    "shadowrun_6": _adapt_shadowrun,
    "shadowrun": _adapt_shadowrun,
    "mad_max": _adapt_generic,
}
