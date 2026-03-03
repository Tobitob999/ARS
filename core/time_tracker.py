"""
core/time_tracker.py — Spielzeit- und Wetter-Tracking

Verwaltet die In-Game-Tageszeit, verstrichene Tage und Wetterbedingungen.
Wird vom Orchestrator ueber GM-Tags gesteuert:
  [ZEIT_VERGEHT: 2h]      → 2 Stunden vergehen
  [TAGESZEIT: 14:30]      → Setzt die Uhrzeit explizit
  [WETTER: Regen]         → Setzt die aktuelle Wetterlage

Der AI-Backend liest ueber get_context_for_prompt() den aktuellen
Zustand und injiziert ihn in den System-Prompt, damit Gemini
zeitkonsistente Erzaehlungen generieren kann.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("ARS.time_tracker")


class TimeTracker:
    """
    Verfolgt In-Game-Zeit (Stunde, Minute, Tag) und Wetter.

    API:
      advance(hours)             → Zeit voranschreiten lassen
      set_time(h, m)             → Uhrzeit explizit setzen
      set_weather(description)   → Wetterbeschreibung setzen
      get_context_for_prompt()   → Kontextstring fuer System-Prompt
      get_time_of_day()          → "Morgen" | "Mittag" | ... | "Nacht"
    """

    def __init__(
        self,
        hour: int = 8,
        minute: int = 0,
        day: int = 1,
        weather: str = "klar",
    ) -> None:
        self._hour = hour
        self._minute = minute
        self._day = day
        self._weather = weather
        # Runden-Tracking (AD&D 2e: 1 Kampfrunde = 1 Minute, 10 Runden = 1 Turn)
        self._round_total: int = 0
        self._round_current_combat: int = 0
        self._in_combat: bool = False

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    def advance(self, hours: float) -> None:
        """
        Laesst die angegebene Anzahl Stunden vergehen.
        Unterstuetzt Fliesskomma (z.B. 0.5 = 30 Minuten).
        Tageswechsel wird automatisch behandelt.
        """
        total_minutes = self._hour * 60 + self._minute + int(hours * 60)
        extra_days, remaining = divmod(total_minutes, 1440)  # 24*60
        self._day += extra_days
        self._hour, self._minute = divmod(remaining, 60)
        logger.info(
            "Zeit vorgerueckt um %.1fh -> Tag %d, %02d:%02d",
            hours, self._day, self._hour, self._minute,
        )

    def set_time(self, hour: int, minute: int = 0) -> None:
        """Setzt die Uhrzeit explizit. Aendert den Tag nicht."""
        self._hour = max(0, min(23, hour))
        self._minute = max(0, min(59, minute))
        logger.info("Uhrzeit gesetzt: %02d:%02d", self._hour, self._minute)

    def set_weather(self, description: str) -> None:
        """Setzt die aktuelle Wetterbeschreibung."""
        self._weather = description.strip()
        logger.info("Wetter gesetzt: %s", self._weather)

    def get_time_of_day(self) -> str:
        """
        Gibt die Tageszeit als lesbaren String zurueck.

        Einteilung:
          05–08  Morgen
          09–11  Vormittag
          12–13  Mittag
          14–17  Nachmittag
          18–20  Abend
          21–04  Nacht
        """
        h = self._hour
        if 5 <= h <= 8:
            return "Morgen"
        if 9 <= h <= 11:
            return "Vormittag"
        if 12 <= h <= 13:
            return "Mittag"
        if 14 <= h <= 17:
            return "Nachmittag"
        if 18 <= h <= 20:
            return "Abend"
        return "Nacht"

    def advance_rounds(self, n: int) -> None:
        """
        Laesst n Kampfrunden vergehen (AD&D 2e: 1 Runde = 1 Minute).
        Ruft intern advance() auf um die Uhrzeit mitzufuehren.
        """
        self._round_total += n
        if self._in_combat:
            self._round_current_combat += n
        self.advance(n / 60.0)  # n Minuten in Stunden
        logger.info(
            "Runden vorgerueckt: +%d (Gesamt: %d, Kampf: %d)",
            n, self._round_total, self._round_current_combat,
        )

    def start_combat(self) -> None:
        """Markiert den Beginn eines Kampfes — setzt Kampfrunden-Zaehler zurueck."""
        self._in_combat = True
        self._round_current_combat = 0
        logger.info("Kampf begonnen (Runde 0).")

    def end_combat(self) -> None:
        """Markiert das Ende eines Kampfes."""
        rounds = self._round_current_combat
        self._in_combat = False
        self._round_current_combat = 0
        logger.info("Kampf beendet nach %d Runden.", rounds)

    def get_context_for_prompt(self) -> str:
        """
        Gibt einen kompakten Kontextstring fuer den System-Prompt zurueck.
        Beispiel: "Tag 1, 14:30 (Nachmittag) | Wetter: klar"
        Im Kampf zusaetzlich: "Kampfrunde: N"
        """
        base = (
            f"Tag {self._day}, {self._hour:02d}:{self._minute:02d} "
            f"({self.get_time_of_day()}) | Wetter: {self._weather}"
        )
        if self._in_combat:
            base += f" | Kampfrunde: {self._round_current_combat}"
        return base

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def hour(self) -> int:
        return self._hour

    @property
    def minute(self) -> int:
        return self._minute

    @property
    def day(self) -> int:
        return self._day

    @property
    def weather(self) -> str:
        return self._weather

    @property
    def round_total(self) -> int:
        return self._round_total

    @property
    def in_combat(self) -> bool:
        return self._in_combat
