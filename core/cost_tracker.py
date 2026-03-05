"""
core/cost_tracker.py — Persistente KI-Kosten-Ueberwachung

Verfolgt alle Gemini-API-Kosten ueber Sessions hinweg in einem JSON-Ledger.
Prueft Limits (taeglich/woechentlich/monatlich/pro Session) und emittiert
Warnungen/Blocks via EventBus.

Thread-safe: Alle Schreibzugriffe auf das Ledger sind durch einen Lock geschuetzt.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("ARS.cost_tracker")

_DEFAULT_LIMITS = {
    "daily_max_usd": 5.00,
    "weekly_max_usd": 20.00,
    "monthly_max_usd": 50.00,
    "per_session_max_usd": 3.00,
    "warn_at_pct": 80,
}


class CostTracker:
    """Persistentes Kosten-Tracking mit Limit-Pruefung."""

    def __init__(self, ledger_path: str | Path | None = None) -> None:
        if ledger_path is None:
            root = Path(__file__).resolve().parent.parent
            ledger_path = root / "data" / "costs" / "cost_ledger.json"
        self._path = Path(ledger_path)
        self._lock = threading.Lock()
        self._data = self._load()
        # Laufende Session-Kosten (live pro Call aktualisiert)
        self._session_cost: float = 0.0

    # -- Persistenz -----------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                logger.warning("Ledger korrupt oder nicht lesbar — neues Ledger.")
        return {"currency": "USD", "entries": [], "limits": dict(_DEFAULT_LIMITS)}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2)
        tmp.replace(self._path)

    # -- Eintraege ------------------------------------------------------------

    def record_call(self, cost_usd: float, prompt_tokens: int = 0,
                    output_tokens: int = 0, cached_tokens: int = 0,
                    think_tokens: int = 0) -> None:
        """Aktualisiert die laufenden Session-Kosten (pro API-Call)."""
        self._session_cost += cost_usd

    def record_session(self, session_id: int = 0, module: str = "",
                       adventure: str = "", source: str = "manual",
                       turns: int = 0, prompt_tokens: int = 0,
                       output_tokens: int = 0, cached_tokens: int = 0,
                       think_tokens: int = 0, cost_usd: float = 0.0) -> None:
        """Schreibt einen Session-Eintrag ins Ledger."""
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "session_id": session_id,
            "module": module,
            "adventure": adventure,
            "source": source,
            "turns": turns,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "think_tokens": think_tokens,
            "cost_usd": round(cost_usd, 6),
        }
        with self._lock:
            self._data.setdefault("entries", []).append(entry)
            self._save()
        self._session_cost = 0.0
        logger.info("Kosten-Eintrag: $%.4f (%s/%s, %d Turns)",
                     cost_usd, module, adventure, turns)

    # -- Abfragen -------------------------------------------------------------

    def _entries(self) -> list[dict[str, Any]]:
        return self._data.get("entries", [])

    def _limits(self) -> dict[str, Any]:
        return self._data.get("limits", dict(_DEFAULT_LIMITS))

    def get_daily_spend(self, date: datetime | None = None) -> float:
        if date is None:
            date = datetime.now()
        day_str = date.strftime("%Y-%m-%d")
        return sum(
            e.get("cost_usd", 0.0) for e in self._entries()
            if e.get("timestamp", "").startswith(day_str)
        )

    def get_weekly_spend(self, ref: datetime | None = None) -> float:
        if ref is None:
            ref = datetime.now()
        # Montag der aktuellen Woche
        monday = ref - timedelta(days=ref.weekday())
        monday_str = monday.strftime("%Y-%m-%d")
        return sum(
            e.get("cost_usd", 0.0) for e in self._entries()
            if e.get("timestamp", "")[:10] >= monday_str
        )

    def get_monthly_spend(self, ref: datetime | None = None) -> float:
        if ref is None:
            ref = datetime.now()
        month_prefix = ref.strftime("%Y-%m")
        return sum(
            e.get("cost_usd", 0.0) for e in self._entries()
            if e.get("timestamp", "").startswith(month_prefix)
        )

    def get_total_spend(self) -> float:
        return sum(e.get("cost_usd", 0.0) for e in self._entries())

    def check_limits(self) -> dict[str, Any]:
        """Prueft alle Limits. Gibt dict mit Warnungen und Blocks zurueck."""
        limits = self._limits()
        warn_pct = limits.get("warn_at_pct", 80) / 100.0
        result: dict[str, Any] = {"warnings": [], "blocked": False, "block_reason": ""}

        checks = [
            ("daily", self.get_daily_spend(), limits.get("daily_max_usd", 999)),
            ("weekly", self.get_weekly_spend(), limits.get("weekly_max_usd", 999)),
            ("monthly", self.get_monthly_spend(), limits.get("monthly_max_usd", 999)),
        ]

        for name, spent, limit in checks:
            if limit <= 0:
                continue
            pct = spent / limit
            if pct >= 1.0:
                result["blocked"] = True
                result["block_reason"] = f"{name} Limit erreicht: ${spent:.2f} / ${limit:.2f}"
                result["warnings"].append(result["block_reason"])
            elif pct >= warn_pct:
                result["warnings"].append(
                    f"{name} Warnung: ${spent:.2f} / ${limit:.2f} ({pct*100:.0f}%)"
                )

        return result

    def check_session_limit(self) -> tuple[bool, str]:
        """Prueft ob die laufende Session das per_session_max ueberschreitet."""
        limit = self._limits().get("per_session_max_usd", 0)
        if limit <= 0:
            return False, ""
        if self._session_cost >= limit:
            return True, f"Session-Limit erreicht: ${self._session_cost:.2f} / ${limit:.2f}"
        return False, ""

    def can_start_session(self, estimated_cost: float = 0.0) -> tuple[bool, str]:
        """Prueft ob eine neue Session gestartet werden darf."""
        result = self.check_limits()
        if result["blocked"]:
            return False, result["block_reason"]
        return True, ""

    def update_limits(self, **kwargs: float) -> None:
        """Limits aendern. Gueltige Keys: daily_max_usd, weekly_max_usd, etc."""
        with self._lock:
            limits = self._data.setdefault("limits", dict(_DEFAULT_LIMITS))
            for key, val in kwargs.items():
                if key in _DEFAULT_LIMITS:
                    limits[key] = val
            self._save()

    def get_summary(self) -> dict[str, Any]:
        """Gesamtuebersicht: heute, Woche, Monat, gesamt, Limits, Session."""
        return {
            "daily_usd": round(self.get_daily_spend(), 4),
            "weekly_usd": round(self.get_weekly_spend(), 4),
            "monthly_usd": round(self.get_monthly_spend(), 4),
            "total_usd": round(self.get_total_spend(), 4),
            "session_usd": round(self._session_cost, 4),
            "limits": dict(self._limits()),
            "total_sessions": len(self._entries()),
        }

    @property
    def session_cost(self) -> float:
        return self._session_cost

    # -- Retroaktiver Import --------------------------------------------------

    def import_from_test_results(self, results_dir: str | Path | None = None) -> int:
        """Importiert Kosten aus bestehenden test_results JSON-Dateien.

        Ueberspringt Dateien die schon im Ledger sind (anhand Timestamp-Match).
        Gibt die Anzahl importierter Eintraege zurueck.
        """
        if results_dir is None:
            root = Path(__file__).resolve().parent.parent
            results_dir = root / "data" / "test_results"
        results_dir = Path(results_dir)
        if not results_dir.exists():
            return 0

        # Bestehende Timestamps sammeln (Deduplizierung)
        existing_ts = {e.get("timestamp", "") for e in self._entries()}

        imported = 0
        for fp in sorted(results_dir.glob("*.json")):
            try:
                with fp.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                continue

            tokens = data.get("tokens", {})
            cost = tokens.get("total_cost_usd", 0.0)
            if cost <= 0:
                continue

            # Timestamp aus Dateinamen extrahieren: test_add_2e_xxx_YYYYMMDD_HHMMSS.json
            fname = fp.stem
            parts = fname.rsplit("_", 2)
            if len(parts) >= 3:
                try:
                    ts_str = parts[-2] + parts[-1]  # YYYYMMDDHHMMSS
                    ts = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
                    ts_iso = ts.isoformat(timespec="seconds")
                except ValueError:
                    ts_iso = datetime.fromtimestamp(fp.stat().st_mtime).isoformat(timespec="seconds")
            else:
                ts_iso = datetime.fromtimestamp(fp.stat().st_mtime).isoformat(timespec="seconds")

            if ts_iso in existing_ts:
                continue

            entry = {
                "timestamp": ts_iso,
                "session_id": 0,
                "module": data.get("module", ""),
                "adventure": data.get("adventure", ""),
                "source": "import_test_results",
                "turns": data.get("total_turns", 0),
                "prompt_tokens": tokens.get("prompt_tokens", 0),
                "output_tokens": tokens.get("output_tokens", 0),
                "cached_tokens": tokens.get("cached_tokens", 0),
                "think_tokens": tokens.get("think_tokens", 0),
                "cost_usd": round(cost, 6),
            }
            with self._lock:
                self._data.setdefault("entries", []).append(entry)
                existing_ts.add(ts_iso)
            imported += 1

        if imported > 0:
            with self._lock:
                self._save()
            logger.info("%d Eintraege aus test_results importiert.", imported)

        return imported
