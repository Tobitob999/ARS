"""
gui/tech_gui.py — ARS TechGUI Hauptfenster

Entwickler-GUI mit 5 Tabs + persistenter Statusleiste.
Kommuniziert mit der Engine ueber EventBus (Observer Pattern).
Engine laeuft in eigenem Thread — GUI im Tkinter Main-Thread.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
import tkinter.ttk as ttk
from typing import TYPE_CHECKING, Any

from core.event_bus import EventBus
from gui.styles import (
    BG_DARK, FG_ACCENT, FONT_HEADER, WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT,
    configure_dark_theme,
)
from gui.status_bar import StatusBar

if TYPE_CHECKING:
    from core.engine import SimulatorEngine

logger = logging.getLogger("ARS.techgui")


class TechGUI:
    """
    Hauptfenster der ARS TechGUI.

    Startet die Engine in einem separaten Thread und verbindet
    alle Tabs ueber den EventBus.
    """

    def __init__(self, engine: "SimulatorEngine") -> None:
        self.engine = engine
        self._engine_thread: threading.Thread | None = None
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()

        # ── Tkinter Root ──
        self.root = tk.Tk()
        self.root.title("ARS TechGUI — Advanced Roleplay Simulator")
        self.root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.root.geometry(f"{WINDOW_MIN_WIDTH}x{WINDOW_MIN_HEIGHT}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        configure_dark_theme(self.root)

        # ── Mausrad-Scrolling fuer alle scrollbaren Widgets ──
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

        # ── Layout ──
        self._build_ui()

        # ── EventBus Wildcard-Listener ──
        bus = EventBus.get()
        bus.on("*", self._on_engine_event)

        # ── Event-Queue Polling ──
        self._poll_events()

    def _build_ui(self) -> None:
        """Erstellt das UI: Notebook (Tabs) + Statusleiste."""
        # Header
        header = tk.Frame(self.root, bg=BG_DARK)
        header.pack(fill=tk.X, padx=8, pady=(8, 0))
        tk.Label(
            header, text="ARS TechGUI", bg=BG_DARK, fg=FG_ACCENT,
            font=FONT_HEADER,
        ).pack(side=tk.LEFT)

        # Notebook (Tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Tabs importieren und erstellen
        from gui.tab_session import SessionTab
        from gui.tab_game import GameTab
        from gui.tab_audio import AudioTab
        from gui.tab_ki_monitor import KIMonitorTab
        from gui.tab_ki_connection import KIConnectionTab
        from gui.tab_gamestate import GameStateTab

        self.tab_session = SessionTab(self.notebook, self)
        self.tab_game = GameTab(self.notebook, self)
        self.tab_audio = AudioTab(self.notebook, self)
        self.tab_ki_monitor = KIMonitorTab(self.notebook, self)
        self.tab_ki_connection = KIConnectionTab(self.notebook, self)
        self.tab_gamestate = GameStateTab(self.notebook, self)

        self.notebook.add(self.tab_session, text="  Session Setup  ")
        self.notebook.add(self.tab_game, text="  Game  ")
        self.notebook.add(self.tab_audio, text="  Audio  ")
        self.notebook.add(self.tab_ki_monitor, text="  KI-Monitor  ")
        self.notebook.add(self.tab_ki_connection, text="  KI-Connection  ")
        self.notebook.add(self.tab_gamestate, text="  Spielstand  ")

        # Statusleiste
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # ── Engine Thread Management ──

    def start_engine(self) -> None:
        """Startet die Engine in einem separaten Daemon-Thread."""
        if self._engine_thread and self._engine_thread.is_alive():
            logger.warning("Engine laeuft bereits.")
            return

        self.status_bar.set_engine_state("Initializing")

        def _run() -> None:
            try:
                self.engine.initialize()
                # Adventure laden falls konfiguriert
                sc = self.engine.session_config
                if sc and getattr(sc, "adventure", None):
                    self.engine.load_adventure(sc.adventure)
                # Voice aktivieren falls konfiguriert
                if getattr(self, "_voice_enabled", False):
                    barge_in = getattr(self, "_barge_in", True)
                    self.engine.enable_voice(barge_in=barge_in)

                # GUI-Modus aktivieren: Input via Queue statt stdin
                if self.engine._orchestrator:
                    self.engine._orchestrator.set_gui_mode(True)

                self._queue_event({"_event": "techgui.engine_ready"})
                self.engine.run()
            except Exception as exc:
                logger.exception("Engine-Thread Fehler")
                self._queue_event({
                    "_event": "techgui.engine_error",
                    "error": str(exc),
                })

        self._engine_thread = threading.Thread(target=_run, daemon=True, name="ARS-Engine")
        self._engine_thread.start()
        self.status_bar.start_timer()
        logger.info("Engine-Thread gestartet.")

    def pause_engine(self) -> None:
        """Pausiert den Game-Loop."""
        if self.engine._orchestrator:
            self.engine._orchestrator._active = False
            self.status_bar.set_engine_state("Paused")
            logger.info("Engine pausiert.")

    def stop_engine(self) -> None:
        """Stoppt den Game-Loop."""
        if self.engine._orchestrator:
            self.engine._orchestrator.stop_session()
        self.status_bar.set_engine_state("Stopped")
        self.status_bar.stop_timer()
        logger.info("Engine gestoppt.")

    # ── Event-System ──

    def _on_engine_event(self, data: dict[str, Any]) -> None:
        """EventBus Wildcard-Callback (wird im Engine-Thread aufgerufen)."""
        self._event_queue.put(data)

    def _queue_event(self, data: dict[str, Any]) -> None:
        """Enqueued ein internes Event fuer den GUI-Thread."""
        self._event_queue.put(data)

    def _poll_events(self) -> None:
        """Pollt die Event-Queue und dispatcht an GUI-Komponenten (Main-Thread)."""
        try:
            while True:
                data = self._event_queue.get_nowait()
                self._dispatch_event(data)
        except queue.Empty:
            pass
        self.root.after(50, self._poll_events)

    def _dispatch_event(self, data: dict[str, Any]) -> None:
        """Verteilt ein Event an alle relevanten GUI-Komponenten."""
        event = data.get("_event", "")

        # Interne TechGUI-Events
        if event == "techgui.engine_ready":
            self.status_bar.set_engine_state("Running")
            self.tab_session.on_engine_ready()
            self.tab_game.on_engine_ready()
            self.tab_ki_connection.on_engine_ready()
            self.tab_gamestate.on_engine_ready()
            # Zum Game-Tab wechseln
            self.notebook.select(self.tab_game)
            return

        if event == "techgui.engine_error":
            self.status_bar.set_engine_state("Error")
            return

        # StatusBar bekommt alles
        self.status_bar.handle_event(data)

        # An die einzelnen Tabs weiterleiten
        self.tab_game.handle_event(data)
        self.tab_ki_monitor.handle_event(data)
        self.tab_ki_connection.handle_event(data)
        self.tab_gamestate.handle_event(data)

    # ── Mausrad ──

    def _on_mousewheel(self, event: Any) -> None:
        """Scrollt das Widget unter dem Mauszeiger mit dem Mausrad."""
        widget = event.widget
        # Aufwaerts durch die Widget-Hierarchie bis ein scrollbares Widget gefunden wird
        while widget:
            if isinstance(widget, (tk.Text, tk.Listbox, tk.Canvas)):
                try:
                    widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
                except tk.TclError:
                    pass
                return
            try:
                widget_class = widget.winfo_class()
            except tk.TclError:
                return
            if widget_class == "Treeview":
                try:
                    widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
                except tk.TclError:
                    pass
                return
            widget = widget.master

    # ── Lifecycle ──

    def _on_close(self) -> None:
        """Fenster schliessen — Engine stoppen."""
        self.stop_engine()
        self.root.destroy()

    def run(self) -> None:
        """Startet die Tkinter Main-Loop."""
        logger.info("TechGUI gestartet.")
        self.root.mainloop()
