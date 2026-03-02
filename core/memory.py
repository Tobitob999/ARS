"""
core/memory.py — Archivist: Langzeit-Gedaechtnis des Keepers

Loest zwei Probleme des Token-Limits:
  1. Chronik:     Alle 15 Runden erstellt die KI eine faktische Zusammenfassung
                  der bisherigen Ereignisse. Diese Zusammenfassung ersetzt die
                  alten Einzel-Turns im Prompt — der Kontext bleibt schlank,
                  aber der "rote Faden" bleibt erhalten.

  2. World State: Die KI kann ueber das Tag [FAKT: {...}] Fakten festschreiben
                  (z.B. {"miller_tot": true}). Diese werden bei jedem Turn als
                  "Aktuelle Fakten" mitgesendet um Widersprueche zu vermeiden.

Tag-Protokoll (GM -> Engine):
  [FAKT: {"npc_name_tot": true}]   → Fakt in World State persistieren

DB-Schema:
  chronicles:  id, session_id, turn_number, content, created_at
  sessions:    + world_state TEXT (Migration)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from core.event_bus import EventBus

logger = logging.getLogger("ARS.memory")

# Trigger-Schwelle fuer neue Chronik-Zusammenfassung
SUMMARY_INTERVAL = 15

# Regex fuer [FAKT: {...}] Tags im GM-Text
FAKT_PATTERN = re.compile(
    r"\[FAKT:\s*(\{[^}]*\})\s*\]",
    re.IGNORECASE,
)


def extract_facts(text: str) -> list[dict[str, Any]]:
    """
    Parst alle [FAKT: {...}] Tags aus dem GM-Text.
    Ungueltige JSON-Bloecke werden mit Warnung uebersprungen.
    Nur dict-Typen werden zurueckgegeben — Listen oder Primitives werden ignoriert.
    Returns list of fact-dicts.
    """
    facts: list[dict[str, Any]] = []
    for m in FAKT_PATTERN.finditer(text):
        try:
            parsed = json.loads(m.group(1))
        except json.JSONDecodeError:
            logger.warning("Ungueltige FAKT-JSON: '%s' — uebersprungen.", m.group(1))
            continue
        # Sicherheitscheck: nur dicts als Facts erlaubt
        # (KI koennte theoretisch ein Array oder Primitiv liefern)
        if not isinstance(parsed, dict):
            logger.warning(
                "FAKT-Tag enthaelt kein dict (sondern %s): '%s' — uebersprungen.",
                type(parsed).__name__,
                m.group(1),
            )
            continue
        facts.append(parsed)
    return facts


# ── Archivist ─────────────────────────────────────────────────────────────────


class Archivist:
    """
    Verwaltet die Langzeit-Erinnerung des Keepers fuer eine Spielsession.

    Oeffentliche API:
      should_summarize(turn_number) -> bool  True wenn Chronik-Update faellig
      update_chronicle(summary: str)         Neue Chronik-Fassung speichern
      get_chronicle() -> str                 Aktuelle Chronik-Zusammenfassung
      merge_world_state(facts: dict)         Fakten in World State einpflegen
      get_world_state() -> dict              Aktueller World State
      get_context_for_prompt() -> str        Kombinierten Kontext-Block liefern
      get_recent_turns(count) -> list[dict]  Letzte N Turns aus DB laden
    """

    def __init__(self, session_id: int, conn: sqlite3.Connection) -> None:
        self._session_id = session_id
        self._conn = conn
        self._chronicle: str = ""
        self._world_state: dict[str, Any] = {}
        self._ensure_schema()
        self._load_state()

    # ------------------------------------------------------------------
    # Oeffentliche API — Chronik
    # ------------------------------------------------------------------

    def should_summarize(self, turn_number: int) -> bool:
        """True wenn nach dieser Runde eine neue Zusammenfassung erstellt werden soll."""
        return turn_number > 0 and turn_number % SUMMARY_INTERVAL == 0

    def update_chronicle(self, summary: str) -> None:
        """
        Fuegt eine neue Zusammenfassungs-Sektion zur Chronik hinzu und
        persistiert sie in der DB.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        if self._chronicle:
            self._chronicle = f"{self._chronicle}\n\n[{timestamp}]\n{summary}"
        else:
            self._chronicle = f"[{timestamp}]\n{summary}"

        self._save_chronicle()
        EventBus.get().emit("archivar", "chronicle_updated", {
            "length": len(self._chronicle),
            "session_id": self._session_id,
            "preview": summary[:200],
        })
        logger.info(
            "Chronik aktualisiert (%d Zeichen, Session %d).",
            len(self._chronicle),
            self._session_id,
        )

    def get_chronicle(self) -> str:
        return self._chronicle

    # ------------------------------------------------------------------
    # Oeffentliche API — World State
    # ------------------------------------------------------------------

    def merge_world_state(self, facts: dict[str, Any]) -> None:
        """
        Fuegt neue Fakten in den World State ein (merge, nicht replace).
        Persistiert sofort in der DB.

        Nur dict-Werte werden akzeptiert — nicht-dict Argumente werden
        protokolliert und ignoriert um Datenkorrumption zu verhindern.
        Verschachtelte dict-Werte (z.B. {"data": {"sub": 1}}) werden
        als JSON-String gespeichert um die Flat-Struktur zu erhalten und
        spaetere sorted()-Aufrufe stabil zu halten.
        """
        if not isinstance(facts, dict):
            logger.warning(
                "merge_world_state: facts ist kein dict (sondern %s) — uebersprungen.",
                type(facts).__name__,
            )
            return

        # Nur flache Werte speichern — nested dicts als JSON-String serialisieren
        safe_facts: dict[str, Any] = {}
        for k, v in facts.items():
            if isinstance(v, dict):
                # Nested dict -> JSON-String damit sorted() und str-Formatierung
                # nicht von der Tiefe der Verschachtelung abhaengen
                safe_facts[k] = json.dumps(v, ensure_ascii=False)
            elif isinstance(v, list):
                # Listen ebenfalls als JSON-String
                safe_facts[k] = json.dumps(v, ensure_ascii=False)
            else:
                safe_facts[k] = v

        self._world_state.update(safe_facts)
        self._save_world_state()
        EventBus.get().emit("archivar", "world_state_updated", {
            "new_facts": safe_facts,
            "total_facts": len(self._world_state),
        })
        logger.info(
            "World State aktualisiert: %s | Gesamt: %d Fakten.",
            safe_facts,
            len(self._world_state),
        )

    def get_world_state(self) -> dict[str, Any]:
        return dict(self._world_state)

    # ------------------------------------------------------------------
    # Oeffentliche API — Kontext fuer KI
    # ------------------------------------------------------------------

    def get_context_for_prompt(self) -> str:
        """
        Gibt einen formatierten Kontext-Block zurueck, der am Anfang jedes
        Turns in die KI-Contents injiziert wird.
        Enthaelt: Chronik (falls vorhanden) + World State (falls vorhanden).
        """
        sections: list[str] = []

        if self._chronicle:
            sections.append(
                f"=== CHRONIK DER BISHERIGEN EREIGNISSE ===\n{self._chronicle}"
            )

        if self._world_state:
            try:
                facts_text = "\n".join(
                    f"  - {k}: {v}" for k, v in sorted(self._world_state.items())
                )
            except (AttributeError, TypeError) as exc:
                # Sicherheitsnetz: _world_state sollte immer ein dict sein,
                # aber falls es korrumpiert wurde, graceful degradieren
                logger.warning(
                    "get_context_for_prompt: _world_state korrumpiert (%s: %s) — "
                    "World State wird zurueckgesetzt.",
                    type(exc).__name__, exc,
                )
                self._world_state = {}
                facts_text = ""
            if facts_text:
                sections.append(f"=== AKTUELLE FAKTEN ===\n{facts_text}")

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Oeffentliche API — Datenbank-Abfragen
    # ------------------------------------------------------------------

    def get_recent_turns(self, count: int) -> list[dict[str, str]]:
        """
        Laedt die letzten <count> Turns der aktuellen Session aus der DB.
        Returns list of {"user": "...", "gm": "..."} dicts.
        """
        cur = self._conn.execute(
            """SELECT user_input, gm_response
               FROM session_turns
               WHERE session_id = ?
               ORDER BY turn_number DESC
               LIMIT ?""",
            (self._session_id, count),
        )
        rows = cur.fetchall()
        # Umkehren: aelteste zuerst
        return [
            {"user": row[0] or "", "gm": row[1] or ""}
            for row in reversed(rows)
        ]

    # ------------------------------------------------------------------
    # Private — Schema & Persistenz
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Erstellt chronicles-Tabelle und migriert sessions.world_state."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS chronicles (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   INTEGER NOT NULL,
                turn_number  INTEGER NOT NULL DEFAULT 0,
                content      TEXT    NOT NULL DEFAULT '',
                created_at   TEXT    NOT NULL DEFAULT ''
            )
        """)
        self._conn.commit()

        # Migration: world_state Spalte zu sessions hinzufuegen
        try:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN world_state TEXT NOT NULL DEFAULT '{}'"
            )
            self._conn.commit()
            logger.debug("Migration: sessions.world_state hinzugefuegt.")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits

    def _load_state(self) -> None:
        """Laedt die letzte Chronik und den World State fuer diese Session."""
        # Neueste Chronik dieser Session
        cur = self._conn.execute(
            """SELECT content FROM chronicles
               WHERE session_id = ?
               ORDER BY turn_number DESC
               LIMIT 1""",
            (self._session_id,),
        )
        row = cur.fetchone()
        self._chronicle = row[0] if row else ""

        # World State aus der Session-Zeile
        cur2 = self._conn.execute(
            "SELECT world_state FROM sessions WHERE id = ?",
            (self._session_id,),
        )
        row2 = cur2.fetchone()
        if row2 and row2[0]:
            try:
                ws = json.loads(row2[0])
                # Sicherheitscheck: nur dicts erlaubt (keine lists)
                if isinstance(ws, dict):
                    self._world_state = ws
                else:
                    logger.warning(
                        "world_state ist keine dict (sondern %s). "
                        "Setze auf leeres dict.",
                        type(ws).__name__,
                    )
                    self._world_state = {}
            except json.JSONDecodeError:
                self._world_state = {}
        else:
            self._world_state = {}

        if self._chronicle:
            logger.info(
                "Chronik geladen (%d Zeichen) | World State: %d Fakten.",
                len(self._chronicle),
                len(self._world_state),
            )

    def _save_chronicle(self) -> None:
        """Schreibt die aktuelle Chronik als neue Zeile in chronicles."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO chronicles (session_id, turn_number, content, created_at)
               VALUES (?, (SELECT COALESCE(MAX(turn_number), 0) + 1
                           FROM chronicles WHERE session_id = ?),
                       ?, ?)""",
            (self._session_id, self._session_id, self._chronicle, now),
        )
        self._conn.commit()

    def _save_world_state(self) -> None:
        """Persistiert den World State in der sessions-Tabelle."""
        self._conn.execute(
            "UPDATE sessions SET world_state = ? WHERE id = ?",
            (json.dumps(self._world_state), self._session_id),
        )
        self._conn.commit()
