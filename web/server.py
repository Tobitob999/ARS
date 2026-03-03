"""
web/server.py — ARS Web GUI Backend

FastAPI server mit WebSocket-Bridge zum EventBus.
Ersetzt die tkinter-GUI durch eine Webanwendung.

Start:
  py -3 main.py --module cthulhu_7e --webgui
  py -3 main.py --module cthulhu_7e --webgui --port 8080
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("ARS.web")

_WEB_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _WEB_DIR / "static"
_TEMPLATE_DIR = _WEB_DIR / "templates"

# ── Global State ────────────────────────────────────────────────────

_engine = None          # SimulatorEngine instance
_engine_thread = None   # daemon thread running the engine
_engine_state = "stopped"   # stopped | initializing | running | paused | error | dead
_loop: asyncio.AbstractEventLoop | None = None
_clients: set[WebSocket] = set()
_discovery_cache: dict[str, Any] = {}
_engine_config: dict[str, Any] = {}


def create_app() -> FastAPI:
    app = FastAPI(title="ARS Web GUI", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ── Pages ───────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html_path = _TEMPLATE_DIR / "index.html"
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/favicon.ico")
    async def favicon():
        ico = _STATIC_DIR / "favicon.ico"
        if ico.is_file():
            return FileResponse(str(ico))
        return HTMLResponse("", status_code=204)

    # ── REST API ────────────────────────────────────────────────

    @app.get("/api/discovery")
    async def api_discovery():
        return _discovery_cache

    @app.get("/api/engine/state")
    async def api_engine_state():
        state = _build_engine_state()
        return state

    @app.post("/api/engine/start")
    async def api_engine_start(body: dict | None = None):
        return _start_engine(body or {})

    @app.post("/api/engine/pause")
    async def api_engine_pause():
        return _pause_engine()

    @app.post("/api/engine/stop")
    async def api_engine_stop():
        return _stop_engine()

    @app.post("/api/input")
    async def api_input(body: dict):
        text = body.get("text", "")
        return _submit_input(text)

    # ── Test Monitor API ───────────────────────────────────────

    @app.get("/api/test/status")
    async def api_test_status():
        return _get_test_status()

    @app.get("/api/test/run/{filename}")
    async def api_test_run(filename: str):
        return _get_test_run(filename)

    @app.post("/api/test/start")
    async def api_test_start(body: dict):
        return _start_test(body)

    @app.post("/api/test/stop")
    async def api_test_stop():
        return _stop_tests()

    # ── WebSocket ───────────────────────────────────────────────

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        _clients.add(ws)
        logger.info("WebSocket client connected (%d total)", len(_clients))

        # Send current state on connect
        try:
            await ws.send_json({
                "type": "state",
                "data": _build_engine_state(),
            })
        except Exception:
            pass

        try:
            while True:
                msg = await ws.receive_json()
                _handle_ws_message(msg)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.debug("WebSocket error: %s", exc)
        finally:
            _clients.discard(ws)
            logger.info("WebSocket client disconnected (%d remaining)", len(_clients))

    return app


# ── Engine Control ──────────────────────────────────────────────────

def _build_engine_state() -> dict[str, Any]:
    """Build current engine state for API/WS."""
    global _engine, _engine_state
    state: dict[str, Any] = {
        "state": _engine_state,
        "module": _engine_config.get("module", ""),
        "adventure": _engine_config.get("adventure"),
    }

    if _engine:
        orch = getattr(_engine, "_orchestrator", None)
        if orch:
            state["turn"] = getattr(orch, "_turn_number", 0)
            state["active"] = getattr(orch, "_active", False)

        char = getattr(_engine, "character", None)
        if char:
            state["character"] = {
                "name": getattr(char, "name", ""),
                "hp": getattr(char, "hp", 0),
                "hp_max": getattr(char, "hp_max", 0),
                "san": getattr(char, "san", None),
                "san_max": getattr(char, "san_max", None),
                "mp": getattr(char, "mp", None),
                "mp_max": getattr(char, "mp_max", None),
                "is_dead": getattr(char, "is_dead", False),
            }

        # AI backend usage
        ai = getattr(_engine, "_ai_backend", None)
        if ai:
            usage = getattr(ai, "_usage_total", {})
            state["usage"] = dict(usage)

    return state


def _start_engine(config: dict) -> dict[str, Any]:
    """Start the engine in a background thread."""
    global _engine, _engine_thread, _engine_state, _engine_config
    from core.engine import SimulatorEngine
    from core.event_bus import EventBus
    from core.session_config import SessionConfig

    if _engine_state == "running":
        return {"ok": False, "error": "Engine laeuft bereits"}

    module = config.get("module", _engine_config.get("module", "cthulhu_7e"))
    adventure = config.get("adventure")
    preset = config.get("preset")
    difficulty = config.get("difficulty", "normal")
    temperature = config.get("temperature")
    lore_budget = config.get("lore_budget")
    speech_style = config.get("speech_style", "normal")
    character = config.get("character")
    party = config.get("party")
    extras = config.get("extras", [])
    keeper = config.get("keeper")
    setting = config.get("setting")

    _engine_config.update({
        "module": module,
        "adventure": adventure,
    })

    def _run():
        global _engine, _engine_state
        try:
            _engine_state = "initializing"
            _broadcast_event("techgui", "state_changed", {"state": "initializing"})

            # Build session config
            if preset:
                cfg = SessionConfig.from_preset(preset)
            else:
                cfg = SessionConfig(ruleset=module)

            cfg.difficulty = difficulty
            cfg.speech_style = speech_style
            if temperature is not None:
                cfg.temperature = float(temperature)
            if lore_budget is not None:
                cfg.lore_budget_pct = int(lore_budget)
            if character:
                cfg.character = character
            if party:
                cfg.party = party
            if extras:
                cfg.extras = extras
            if keeper:
                cfg.keeper = keeper
            if setting:
                cfg.setting = setting

            _engine = SimulatorEngine(module, session_config=cfg)
            _engine.initialize()

            if adventure:
                _engine.load_adventure(adventure)

            # GUI mode for queue-based input
            orch = _engine._orchestrator
            orch.set_gui_mode(enabled=True)

            # Update discovery cache after engine init
            _update_discovery()

            _engine_state = "running"
            _broadcast_event("techgui", "engine_ready", _build_engine_state())
            _broadcast_event("techgui", "state_changed", {"state": "running"})

            _engine.run()

        except Exception as exc:
            logger.exception("Engine error: %s", exc)
            _engine_state = "error"
            _broadcast_event("techgui", "engine_error", {"error": str(exc)})
            _broadcast_event("techgui", "state_changed", {"state": "error", "error": str(exc)})

    _engine_thread = threading.Thread(target=_run, daemon=True, name="ARS-Engine")
    _engine_thread.start()

    return {"ok": True}


def _pause_engine() -> dict[str, Any]:
    global _engine_state
    if not _engine:
        return {"ok": False, "error": "Keine Engine"}

    orch = getattr(_engine, "_orchestrator", None)
    if orch:
        orch._active = False
        _engine_state = "paused"
        _broadcast_event("techgui", "state_changed", {"state": "paused"})
    return {"ok": True}


def _stop_engine() -> dict[str, Any]:
    global _engine_state
    if not _engine:
        return {"ok": False, "error": "Keine Engine"}

    orch = getattr(_engine, "_orchestrator", None)
    if orch:
        orch.submit_input("quit")
        _engine_state = "stopped"
        _broadcast_event("techgui", "state_changed", {"state": "stopped"})
    return {"ok": True}


def _submit_input(text: str) -> dict[str, Any]:
    if not _engine:
        return {"ok": False, "error": "Keine Engine"}

    orch = getattr(_engine, "_orchestrator", None)
    if orch:
        orch.submit_input(text)
        return {"ok": True}
    return {"ok": False, "error": "Kein Orchestrator"}


def _handle_ws_message(msg: dict) -> None:
    """Handle incoming WebSocket message from client."""
    msg_type = msg.get("type", "")

    if msg_type == "player_input":
        _submit_input(msg.get("text", ""))
    elif msg_type == "engine_control":
        action = msg.get("action", "")
        if action == "start":
            _start_engine(msg.get("config", {}))
        elif action == "pause":
            _pause_engine()
        elif action == "stop":
            _stop_engine()
    elif msg_type == "lore_budget":
        from core.event_bus import EventBus
        EventBus.get().emit("session", "lore_budget_changed", msg.get("value", 50))


# ── Test Monitor ───────────────────────────────────────────────────

_PROGRESS_DIR = Path(__file__).resolve().parent.parent / "data" / "test_progress"


def _get_test_status() -> dict[str, Any]:
    """Read all progress files and return active/done test status."""
    active = []
    if _PROGRESS_DIR.is_dir():
        now = time.time()
        for fp in _PROGRESS_DIR.glob("*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            updated = data.get("updated_at", "")
            try:
                from datetime import datetime as _dt
                updated_dt = _dt.fromisoformat(updated)
                age_s = now - updated_dt.timestamp()
            except (ValueError, TypeError):
                age_s = 9999

            entry = {
                "file": fp.name,
                "pid": data.get("pid"),
                "module": data.get("module", "?"),
                "case_id": data.get("case_id", 0),
                "case_name": data.get("case_name", "?"),
                "current_turn": data.get("current_turn", 0),
                "total_turns": data.get("total_turns", 0),
                "status": data.get("status", "?"),
                "avg_latency_ms": data.get("avg_latency_ms", 0),
                "total_cost_usd": data.get("total_cost_usd", 0),
                "prompt_tokens": data.get("prompt_tokens", 0),
                "output_tokens": data.get("output_tokens", 0),
                "character_alive": data.get("character_alive", True),
                "errors": data.get("errors", 0),
                "age_s": round(age_s, 0),
                "stale": age_s > 300,
                "started_at": data.get("started_at", ""),
                "updated_at": updated,
            }
            active.append(entry)

    return {"active": active}


_RESULTS_DIR = Path(__file__).resolve().parent.parent / "data" / "test_results"


def _get_test_run(filename: str) -> dict[str, Any]:
    """Read a single test run (progress or result) by filename."""
    # Sanitize: strip path separators to prevent traversal
    safe = Path(filename).name
    if not safe or safe.startswith("."):
        return {"ok": False, "error": "Invalid filename"}

    # Ensure .json extension
    if not safe.endswith(".json"):
        safe += ".json"

    # Try progress dir first (running tests), then results dir (completed)
    for search_dir in (_PROGRESS_DIR, _RESULTS_DIR):
        fp = search_dir / safe
        if fp.is_file():
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                data["_source"] = search_dir.name
                return data
            except (json.JSONDecodeError, OSError) as exc:
                return {"ok": False, "error": f"Read error: {exc}"}

    return {"ok": False, "error": "File not found"}


def _start_test(config: dict) -> dict[str, Any]:
    """Start a test series in a background thread."""
    import subprocess

    module = config.get("module", "cthulhu_7e")
    case = config.get("case", "1")
    turns = config.get("turns", 5)
    runs = config.get("runs", 3)

    _ROOT = Path(__file__).resolve().parent.parent
    cmd = [
        sys.executable, str(_ROOT / "scripts" / "testbot.py"),
        "run", "-t", str(case), "-n", str(runs),
        "-m", module, "--turns", str(turns),
    ]

    try:
        proc = subprocess.Popen(
            cmd, cwd=str(_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return {"ok": True, "pid": proc.pid}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def _stop_tests() -> dict[str, Any]:
    """Stop all running test processes."""
    stopped = 0
    if _PROGRESS_DIR.is_dir():
        for fp in _PROGRESS_DIR.glob("*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                pid = data.get("pid")
                if pid:
                    import signal
                    os.kill(pid, signal.SIGTERM)
                    stopped += 1
            except (json.JSONDecodeError, OSError, ProcessLookupError):
                pass
    return {"ok": True, "stopped": stopped}


# ── EventBus → WebSocket Bridge ────────────────────────────────────

def setup_event_bridge() -> None:
    """Register wildcard EventBus listener that forwards all events to WebSocket clients."""
    from core.event_bus import EventBus
    bus = EventBus.get()
    bus.on("*", _on_bus_event)
    logger.info("EventBus -> WebSocket bridge active")


def _on_bus_event(data: Any) -> None:
    """Called from engine thread for every EventBus event."""
    global _engine_state

    if not _loop or not _clients:
        return

    # Extract event name
    event_name = ""
    if isinstance(data, dict):
        event_name = data.get("_event", "")

    # Update engine state on key events
    if event_name == "game.player_dead":
        _engine_state = "dead"

    # Serialize and broadcast
    try:
        payload = _serialize_event(event_name, data)
        if payload:
            asyncio.run_coroutine_threadsafe(_broadcast_json(payload), _loop)
    except Exception as exc:
        logger.debug("Event bridge error: %s", exc)


def _serialize_event(event_name: str, data: Any) -> dict | None:
    """Convert EventBus event to JSON-safe dict for WebSocket."""
    try:
        if isinstance(data, dict):
            # Already a dict — clean up non-serializable values
            clean = {}
            for k, v in data.items():
                if k == "_event":
                    continue
                try:
                    json.dumps(v)
                    clean[k] = v
                except (TypeError, ValueError):
                    clean[k] = str(v)

            return {
                "type": "event",
                "event": event_name,
                "data": clean,
            }
        else:
            return {
                "type": "event",
                "event": event_name,
                "data": {"value": str(data)},
            }
    except Exception:
        return None


async def _broadcast_json(payload: dict) -> None:
    """Send JSON to all connected WebSocket clients."""
    dead: list[WebSocket] = []
    msg = json.dumps(payload, ensure_ascii=False, default=str)

    for ws in list(_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)

    for ws in dead:
        _clients.discard(ws)


def _broadcast_event(category: str, event_name: str, data: dict) -> None:
    """Convenience: broadcast an event from any thread."""
    if not _loop:
        return
    payload = {
        "type": "event",
        "event": f"{category}.{event_name}",
        "data": data,
    }
    try:
        asyncio.run_coroutine_threadsafe(_broadcast_json(payload), _loop)
    except Exception:
        pass


# ── Discovery ───────────────────────────────────────────────────────

def _update_discovery() -> None:
    """Update cached discovery data from DiscoveryService."""
    global _discovery_cache
    try:
        from core.discovery import DiscoveryService
        ds = DiscoveryService()
        manifest = ds.get_manifest()

        def _items(key: str) -> list[dict[str, str]]:
            """Extract id/name/module from manifest dict entries."""
            raw = manifest.get(key, {})
            result = []
            for item_id, info in raw.items():
                entry = {"id": item_id, "name": info.get("title", info.get("name", item_id))}
                if "module" in info:
                    entry["module"] = info["module"]
                elif "ruleset" in info:
                    entry["module"] = info["ruleset"]
                result.append(entry)
            return result

        _discovery_cache = {
            "rulesets": _items("rulesets"),
            "adventures": _items("adventures"),
            "characters": _items("characters"),
            "parties": _items("parties"),
            "settings": _items("settings"),
            "keepers": _items("keepers"),
            "scenarios": _items("scenarios"),
            "extras": _items("extras"),
        }
    except Exception as exc:
        logger.warning("Discovery update failed: %s", exc)
        _discovery_cache = {}


def init_discovery() -> None:
    """Run initial discovery (before engine start)."""
    _update_discovery()


# ── Server Launch ───────────────────────────────────────────────────

def run_server(
    module: str = "cthulhu_7e",
    host: str = "0.0.0.0",
    port: int = 7860,
) -> None:
    """Start the web server (blocking)."""
    global _loop, _engine_config
    import uvicorn

    _engine_config["module"] = module

    # Initial discovery
    init_discovery()

    # EventBus bridge
    setup_event_bridge()

    app = create_app()

    logger.info("ARS Web GUI: http://%s:%d", host, port)

    config = uvicorn.Config(
        app, host=host, port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)

    # Capture the asyncio loop for the EventBus bridge
    original_startup = server.startup

    async def patched_startup(sockets=None):
        global _loop
        _loop = asyncio.get_event_loop()
        await original_startup(sockets)

    server.startup = patched_startup
    server.run()
