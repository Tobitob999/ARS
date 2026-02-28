"""
core/event_bus.py — Singleton EventBus (Observer Pattern)

Zentraler Nachrichten-Bus fuer lose Kopplung zwischen Engine und GUI.
Events werden als 'category.event_name' adressiert.

Verwendung:
    bus = EventBus.get()
    bus.on("keeper.prompt_sent", my_callback)
    bus.emit("keeper", "prompt_sent", {"user_message": "..."})

Thread-Safety: Callbacks werden im Thread des Emitters aufgerufen.
GUI-Listener muessen selbst via root.after() in den Main-Thread dispatchen.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

logger = logging.getLogger("ARS.event_bus")

Callback = Callable[[dict[str, Any]], None]


class EventBus:
    """Singleton Observer-Bus fuer Engine <-> GUI Kommunikation."""

    _instance: EventBus | None = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> EventBus:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Setzt die Singleton-Instanz zurueck (fuer Tests)."""
        with cls._lock:
            cls._instance = None

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callback]] = {}
        self._lock_listeners = threading.Lock()

    def on(self, event: str, callback: Callback) -> None:
        """
        Listener registrieren.

        event: 'category.event_name' oder '*' fuer alle Events.
        """
        with self._lock_listeners:
            self._listeners.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callback) -> None:
        """Listener entfernen."""
        with self._lock_listeners:
            listeners = self._listeners.get(event, [])
            try:
                listeners.remove(callback)
            except ValueError:
                pass

    def emit(self, category: str, event_name: str, data: dict[str, Any] | None = None) -> None:
        """
        Event feuern.

        Ruft alle Listener fuer 'category.event_name' und '*' auf.
        Fehler in Callbacks werden geloggt, aber nicht propagiert.
        """
        if data is None:
            data = {}
        key = f"{category}.{event_name}"

        with self._lock_listeners:
            specific = list(self._listeners.get(key, []))
            wildcard = list(self._listeners.get("*", []))

        for cb in specific:
            try:
                cb(data)
            except Exception:
                logger.exception("EventBus callback error for '%s'", key)

        if wildcard:
            wildcard_data = {"_event": key, **data}
            for cb in wildcard:
                try:
                    cb(wildcard_data)
                except Exception:
                    logger.exception("EventBus wildcard callback error for '%s'", key)
