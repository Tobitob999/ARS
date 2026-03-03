"""
gui/tab_dungeon_view.py — Tab 12: ASCII Dungeon-Crawler (Ultima-Stil)

Live-Visualisierung des Dungeon Crawls mit:
  - 8-Bit ASCII-Karte (Waende, Tueren, Boden, Entities)
  - Animierte Charakter-Bewegung (Schritt fuer Schritt, 150ms/Frame)
  - Kampf-Animationen (Angreifer rueckt vor, Blitz, Schaden)
  - Auto-Crawl: KI spielt automatisch, Spieler schaut zu
  - 4-Panel-Layout: Karte | Party | Spiel-Log | Regel-Log
  - Fog of War, Sound-Effekte, Flash-Effekte
"""

from __future__ import annotations

import logging
import random
import threading
import tkinter as tk
import tkinter.ttk as ttk
from collections import deque
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE, BLUE,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, FONT_HEADER,
    PAD, PAD_SMALL,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.dungeon")

# ═══════════════════════════════════════════════════════════════════════════════
# 8-Bit Symbole & Konstanten
# ═══════════════════════════════════════════════════════════════════════════════

# Waende (Box Drawing)
W_H = "\u2550"          # ═
W_V = "\u2551"          # ║
W_TL = "\u2554"         # ╔
W_TR = "\u2557"         # ╗
W_BL = "\u255A"         # ╚
W_BR = "\u255D"         # ╝

# Entities
S_DOOR = "\u25A1"       # □
S_FLOOR = "\u00B7"      # ·
S_FOG = "\u2591"        # ░
S_MONSTER = "\u2666"    # ♦
S_DEAD = "\u2620"       # ☠
S_TRAP = "!"
S_TREASURE = "$"
S_WATER = "~"
S_RUBBLE = "#"
S_STAIRS_UP = "\u25B2"  # ▲
S_STAIRS_DN = "\u25BC"  # ▼
S_SWORD = "\u2694"      # ⚔
S_SPARK = "\u2726"      # ✦
S_HEART = "\u2665"      # ♥
S_SHIELD = "\u25C6"     # ◆

# Klassen-Kuerzel
_CLS: dict[str, str] = {
    "fighter": "F", "kaempfer": "F", "mage": "M", "magier": "M", "wizard": "M",
    "cleric": "C", "kleriker": "C", "priester": "C", "thief": "T", "dieb": "T",
    "schurke": "T", "ranger": "R", "waldlaeufer": "R", "paladin": "P",
    "ritter": "P", "bard": "B", "barde": "B", "druid": "D", "druide": "D",
}
_COLORS = [GREEN, YELLOW, BLUE, ORANGE, "#CBA6F7", "#F5C2E7"]

# Raum-Groesse (Defaults, GridEngine ueberschreibt dynamisch)
RW = 17      # Breite inkl. Waende
RH = 11      # Hoehe inkl. Waende

# Animation
FRAME_MS = 150      # ms pro Animations-Frame
FLASH_MS = 400      # ms fuer Flash-Effekte
AUTO_DELAY_DEFAULT = 4000  # ms zwischen Auto-Zuegen

# Fonts
F_MAP = ("Consolas", 12)
F_MAP_B = ("Consolas", 12, "bold")
F_LOG = ("Consolas", 9)

# Richtungs-Hints
_DIR_HINTS: dict[str, tuple[int, int]] = {
    "nord": (0, -1), "norden": (0, -1), "oben": (0, -1), "hinauf": (0, -1),
    "sued": (0, 1), "sueden": (0, 1), "unten": (0, 1),
    "hinunter": (0, 1), "hinab": (0, 1), "tiefer": (0, 1),
    "ost": (1, 0), "osten": (1, 0), "rechts": (1, 0),
    "west": (-1, 0), "westen": (-1, 0), "links": (-1, 0),
    "nordost": (1, -1), "suedost": (1, 1),
    "nordwest": (-1, -1), "suedwest": (-1, 1),
    "ebene 2": (0, 1), "ebene 3": (0, 1),
}
_DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)]

# ── Auto-Crawl Aktionen ──────────────────────────────────────────────────────

_ACT_EXPLORE = [
    "Die Gruppe untersucht den Raum gruendlich. Lyra sucht nach Fallen und Geheimtueren.",
    "Thorin fuehrt die Party zum naechsten Ausgang. Alle folgen in Formation.",
    "Die Party betritt vorsichtig den naechsten Raum. Waffen gezueckt.",
    "Kaelen spaeht voraus und gibt das Zeichen — vorwaerts, naechster Raum!",
    "Elara untersucht die Umgebung auf magische Auren und Gefahren.",
    "Die Gruppe sammelt sich und marschiert weiter in die Tiefe des Dungeons.",
    "Sir Aldric geht voran, Schild erhoben. Die Party folgt durch den Gang.",
    "Bruder Aldhelm segnet die Gruppe. Dann weiter — der naechste Raum wartet.",
]

_ACT_COMBAT = [
    "Thorin stuermt vor und greift mit seiner Axt an! Die anderen unterstuetzen ihn.",
    "Die Party greift koordiniert an — Nahkaempfer vorne, Elara zaubert von hinten!",
    "Kaelen schiesst mit dem Bogen, waehrend Thorin und Aldric den Feind bedraengen.",
    "Lyra schleicht sich von hinten an und sticht zu! Thorin haelt die Front.",
    "Sir Aldric ruft Tyrs Segen und schlaegt mit dem heiligen Schwert zu!",
    "Bruder Aldhelm heilt die Verwundeten, waehrend die Kaempfer zuschlagen!",
]

_ACT_NUDGE = (
    "Alle Monster sind BESIEGT. Die Party sammelt die Beute ein und "
    "marschiert SOFORT in den NAECHSTEN RAUM. Beschreibe den neuen Ort."
)


class DungeonViewTab(ttk.Frame):
    """8-Bit ASCII Dungeon-Crawler mit Live-Animation und Auto-Crawl."""

    def __init__(self, parent: ttk.Notebook, gui: "TechGUI") -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        # ── Dungeon State ──
        self._rooms: dict[str, dict] = {}
        self._current_room: str | None = None
        self._visited: set[str] = set()
        self._char_pos: dict[str, tuple[int, int]] = {}   # name → (x,y)
        self._monster_cells: dict[str, list[tuple[int, int, str]]] = {}  # room → [(x,y,name)]
        self._sounds_on: bool = True
        self._view_mode: str = "room"

        # ── Animation State ──
        self._anim_queue: list[tuple[Any, int]] = []  # [(callable, delay_ms), ...]
        self._anim_running: bool = False
        self._flash_active: bool = False
        self._status_msg: str = ""
        self._status_tag: str = "info"

        # ── Auto-Crawl State ──
        self._auto_play: bool = False
        self._auto_delay: int = AUTO_DELAY_DEFAULT
        self._auto_turn: int = 0
        self._explore_idx: int = 0
        self._combat_idx: int = 0
        self._combat_turns: int = 0
        self._stagnant_turns: int = 0
        self._waiting_for_input: bool = False
        self._pending_auto_id: str | None = None

        # Dynamische Raumgroesse (vom GridEngine ueberschrieben)
        self._rw: int = RW
        self._rh: int = RH

        self._build_ui()
        self._preload_from_config()

    # ══════════════════════════════════════════════════════════════════════════
    # UI Build
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        main_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ── Oben: Karte + Party ──
        top_paned = ttk.PanedWindow(main_paned, orient=tk.HORIZONTAL)
        main_paned.add(top_paned, weight=3)

        # Karte
        map_frame = ttk.LabelFrame(top_paned, text=" Dungeon ", style="TLabelframe")
        top_paned.add(map_frame, weight=3)

        # Toolbar
        tb = ttk.Frame(map_frame, style="TFrame")
        tb.pack(fill=tk.X, padx=2, pady=(2, 0))

        self._view_var = tk.StringVar(value="room")
        ttk.Radiobutton(tb, text="Raum", variable=self._view_var, value="room",
                        command=self._on_view_change).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(tb, text="Karte", variable=self._view_var, value="map",
                        command=self._on_view_change).pack(side=tk.LEFT, padx=2)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        # Auto-Crawl Controls
        self._auto_btn = ttk.Button(tb, text="\u25B6 Auto-Crawl", command=self._toggle_auto_play)
        self._auto_btn.pack(side=tk.LEFT, padx=4)

        ttk.Label(tb, text="Tempo:").pack(side=tk.LEFT, padx=(8, 2))
        self._speed_var = tk.IntVar(value=4)
        speed_scale = ttk.Scale(tb, from_=1, to=10, variable=self._speed_var,
                                orient=tk.HORIZONTAL, length=80,
                                command=self._on_speed_change)
        speed_scale.pack(side=tk.LEFT, padx=2)

        self._snd_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="Sound", variable=self._snd_var,
                        command=lambda: setattr(self, "_sounds_on", self._snd_var.get()),
                        ).pack(side=tk.RIGHT, padx=4)

        self._room_label = ttk.Label(tb, text="", style="Header.TLabel")
        self._room_label.pack(side=tk.LEFT, padx=8)

        self._turn_label = ttk.Label(tb, text="Zug: 0")
        self._turn_label.pack(side=tk.RIGHT, padx=8)

        # Karten-Text
        self._map = tk.Text(
            map_frame, bg="#0A0A1A", fg=FG_PRIMARY, font=F_MAP,
            wrap=tk.NONE, state=tk.DISABLED, cursor="arrow",
            highlightthickness=0, borderwidth=0, padx=12, pady=8,
        )
        map_vs = ttk.Scrollbar(map_frame, orient=tk.VERTICAL, command=self._map.yview)
        self._map.configure(yscrollcommand=map_vs.set)
        map_vs.pack(side=tk.RIGHT, fill=tk.Y)
        self._map.pack(fill=tk.BOTH, expand=True)

        # Text-Tags
        self._map.tag_configure("wall", foreground="#666688")
        self._map.tag_configure("door", foreground=YELLOW, font=F_MAP_B)
        self._map.tag_configure("floor", foreground="#333355")
        self._map.tag_configure("fog", foreground="#222244", background="#0A0A14")
        self._map.tag_configure("monster", foreground=RED, font=F_MAP_B)
        self._map.tag_configure("dead", foreground="#444444")
        self._map.tag_configure("trap", foreground=YELLOW, font=F_MAP_B)
        self._map.tag_configure("treasure", foreground=ORANGE, font=F_MAP_B)
        self._map.tag_configure("water", foreground="#5588CC")
        self._map.tag_configure("rubble", foreground="#555566")
        self._map.tag_configure("stairs", foreground=GREEN, font=F_MAP_B)
        self._map.tag_configure("sword", foreground=RED, font=F_MAP_B)
        self._map.tag_configure("spark", foreground=YELLOW, font=F_MAP_B)
        self._map.tag_configure("heal", foreground=GREEN, font=F_MAP_B)
        self._map.tag_configure("info", foreground=FG_ACCENT)
        self._map.tag_configure("desc", foreground=FG_SECONDARY)
        self._map.tag_configure("status", foreground=FG_ACCENT, font=F_MAP_B)
        self._map.tag_configure("room_current", foreground=GREEN, font=F_MAP_B)
        self._map.tag_configure("room_visited", foreground=FG_SECONDARY)
        self._map.tag_configure("room_fog", foreground="#222244")
        self._map.tag_configure("corridor", foreground="#444466")
        self._map.tag_configure("flash_red", background="#3A0A0A")
        self._map.tag_configure("flash_green", background="#0A2A0A")
        # Bewegungsradius + Waffenreichweite (Kampf-Overlays)
        self._map.tag_configure("move_range", background="#0A1A2A")       # Blau-schimmer: erreichbar
        self._map.tag_configure("reach_zone", background="#2A1A0A")       # Orange-schimmer: Nahkampf-Reichweite
        self._map.tag_configure("range_short", background="#0A2A0A")      # Gruen: Kurzreichweite
        self._map.tag_configure("range_medium", background="#1A1A0A")     # Gelb: Mittelreichweite
        self._map.tag_configure("range_long", background="#2A0A0A")       # Rot: Langreichweite
        for i, c in enumerate(_COLORS):
            self._map.tag_configure(f"c{i}", foreground=c, font=F_MAP_B)

        # ── Party-Panel ──
        party_frame = ttk.LabelFrame(top_paned, text=" Party ", style="TLabelframe")
        top_paned.add(party_frame, weight=1)

        self._party = tk.Text(
            party_frame, bg="#0A0A1A", fg=FG_PRIMARY, font=F_MAP,
            wrap=tk.WORD, state=tk.DISABLED, cursor="arrow",
            highlightthickness=0, borderwidth=0, padx=6, pady=6, width=26,
        )
        self._party.pack(fill=tk.BOTH, expand=True)
        self._party.tag_configure("header", foreground=FG_ACCENT, font=F_MAP_B)
        self._party.tag_configure("alive", foreground=GREEN)
        self._party.tag_configure("hurt", foreground=YELLOW)
        self._party.tag_configure("critical", foreground=RED, font=F_MAP_B)
        self._party.tag_configure("dead", foreground="#555555")
        self._party.tag_configure("label", foreground=FG_SECONDARY)
        self._party.tag_configure("spell", foreground="#CBA6F7")
        for i, c in enumerate(_COLORS):
            self._party.tag_configure(f"m{i}", foreground=c, font=F_MAP_B)

        # ── Unten: Logs ──
        bot_paned = ttk.PanedWindow(main_paned, orient=tk.HORIZONTAL)
        main_paned.add(bot_paned, weight=2)

        # Spiel-Log
        gl_frame = ttk.LabelFrame(bot_paned, text=" Spiel-Log ", style="TLabelframe")
        bot_paned.add(gl_frame, weight=2)
        self._glog = tk.Text(gl_frame, bg="#0A0A1A", fg=FG_PRIMARY, font=F_LOG,
                             wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
                             borderwidth=0, padx=4, pady=4)
        gl_sb = ttk.Scrollbar(gl_frame, orient=tk.VERTICAL, command=self._glog.yview)
        self._glog.configure(yscrollcommand=gl_sb.set)
        self._glog.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        gl_sb.pack(side=tk.RIGHT, fill=tk.Y)
        for t, c in [("narr", FG_PRIMARY), ("combat", RED), ("move", GREEN),
                      ("item", BLUE), ("sys", FG_MUTED), ("keeper", FG_ACCENT)]:
            self._glog.tag_configure(t, foreground=c)

        # Regel-Log
        rl_frame = ttk.LabelFrame(bot_paned, text=" Regel-Log ", style="TLabelframe")
        bot_paned.add(rl_frame, weight=1)
        self._rlog = tk.Text(rl_frame, bg="#0A0A1A", fg=FG_PRIMARY, font=F_LOG,
                             wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0,
                             borderwidth=0, padx=4, pady=4)
        rl_sb = ttk.Scrollbar(rl_frame, orient=tk.VERTICAL, command=self._rlog.yview)
        self._rlog.configure(yscrollcommand=rl_sb.set)
        self._rlog.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rl_sb.pack(side=tk.RIGHT, fill=tk.Y)
        for t, c in [("probe", YELLOW), ("dice", ORANGE), ("stat", GREEN),
                      ("warn", RED), ("rule", FG_ACCENT), ("sys", FG_MUTED)]:
            self._rlog.tag_configure(t, foreground=c)

        # ── Manuelle Eingabe (unter den Logs) ──
        input_frame = ttk.Frame(self, style="TFrame")
        input_frame.pack(fill=tk.X, padx=4, pady=(2, 4))

        self._input_label = ttk.Label(
            input_frame, text="Aktion:", font=FONT_SMALL,
        )
        self._input_label.pack(side=tk.LEFT, padx=(4, 2))

        self._input_var = tk.StringVar()
        self._input_entry = ttk.Entry(
            input_frame, textvariable=self._input_var, font=FONT_NORMAL,
        )
        self._input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self._input_entry.bind("<Return>", self._on_manual_send)

        self._send_btn = ttk.Button(
            input_frame, text="Senden", command=self._on_manual_send,
        )
        self._send_btn.pack(side=tk.LEFT, padx=(2, 4))

    def _on_manual_send(self, _event: Any = None) -> None:
        """Sendet manuelle Eingabe an den Orchestrator."""
        text = self._input_var.get().strip()
        if not text:
            return
        self._input_var.set("")

        # Auto-Crawl stoppen wenn aktiv
        if self._auto_play:
            self._toggle_auto_play()

        orch = getattr(self.gui.engine, "_orchestrator", None)
        if not orch:
            self._log_game("  [Engine nicht bereit]", "sys")
            return

        self._log_game(f"> {text}", "narr")
        orch.submit_input(text)
        self._waiting_for_input = False

    def _on_view_change(self) -> None:
        self._view_mode = self._view_var.get()
        self._render()

    def _on_speed_change(self, _val: str) -> None:
        v = self._speed_var.get()
        self._auto_delay = max(500, 6000 - v * 500)

    # ══════════════════════════════════════════════════════════════════════════
    # Animation System
    # ══════════════════════════════════════════════════════════════════════════

    def _queue_anim(self, steps: list[tuple[Any, int]]) -> None:
        self._anim_queue.extend(steps)
        if not self._anim_running:
            self._anim_running = True
            self._play_next()

    def _play_next(self) -> None:
        if not self._anim_queue:
            self._anim_running = False
            return
        action, delay = self._anim_queue.pop(0)
        try:
            action()
        except Exception:
            logger.exception("Animation error")
        self.after(delay, self._play_next)

    def _anim_move_char(self, name: str, tx: int, ty: int, steps: int = 0) -> None:
        """Bewegt einen Charakter Schritt fuer Schritt zum Ziel."""
        if name not in self._char_pos:
            return
        cx, cy = self._char_pos[name]
        rw, rh = self._rw, self._rh
        if (cx, cy) == (tx, ty) or steps > 20:
            return
        nx = cx + (1 if tx > cx else -1 if tx < cx else 0)
        ny = cy + (1 if ty > cy else -1 if ty < cy else 0)
        nx = max(1, min(rw - 2, nx))
        ny = max(1, min(rh - 2, ny))
        self._char_pos[name] = (nx, ny)
        self._queue_anim([
            (self._render, FRAME_MS),
        ])
        if (nx, ny) != (tx, ty):
            self._queue_anim([
                (lambda n=name, x=tx, y=ty, s=steps + 1: self._anim_move_char(n, x, y, s), 0),
            ])

    def _anim_combat_flash(self, attacker: str, color: str = "flash_red") -> None:
        """Blitz-Effekt bei Kampf."""
        self._flash_active = True
        self._queue_anim([
            (self._render, FLASH_MS),
            (lambda: setattr(self, "_flash_active", False), 0),
            (self._render, 50),
        ])
        self._play_sound("combat")

    def _anim_status(self, msg: str, tag: str = "info", duration: int = 2000) -> None:
        """Zeigt eine Status-Nachricht unter der Karte."""
        self._status_msg = msg
        self._status_tag = tag
        self._queue_anim([
            (self._render, duration),
            (lambda: setattr(self, "_status_msg", ""), 0),
            (self._render, 50),
        ])

    # ══════════════════════════════════════════════════════════════════════════
    # Auto-Crawl System
    # ══════════════════════════════════════════════════════════════════════════

    def _toggle_auto_play(self) -> None:
        self._auto_play = not self._auto_play
        if self._auto_play:
            self._auto_btn.configure(text="\u25A0 Stop")
            self._log_game(f"{S_SPARK} Auto-Crawl gestartet!", "move")
            # Engine starten falls noetig
            self.gui.start_engine()
            # Wenn schon auf Input gewartet wird, sofort loslegen
            if self._waiting_for_input:
                self._schedule_auto_input()
        else:
            self._auto_btn.configure(text="\u25B6 Auto-Crawl")
            self._log_game(f"  Auto-Crawl gestoppt.", "sys")
            if self._pending_auto_id:
                self.after_cancel(self._pending_auto_id)
                self._pending_auto_id = None

    def _schedule_auto_input(self) -> None:
        if not self._auto_play:
            return
        if self._pending_auto_id:
            self.after_cancel(self._pending_auto_id)
        # Warten bis Animation fertig + Delay
        delay = self._auto_delay
        if self._anim_running:
            delay += 500
        self._pending_auto_id = self.after(delay, self._do_auto_input)

    def _do_auto_input(self) -> None:
        self._pending_auto_id = None
        if not self._auto_play:
            return
        # Warten auf Animation
        if self._anim_running:
            self._pending_auto_id = self.after(300, self._do_auto_input)
            return

        orch = getattr(self.gui.engine, "_orchestrator", None)
        if not orch:
            return

        # Stagnation/Combat-Loop Detection
        if self._stagnant_turns >= 3:
            action = _ACT_NUDGE
            self._stagnant_turns = 0
        elif self._combat_turns >= 5:
            action = _ACT_NUDGE
            self._combat_turns = 0
        elif self._combat_turns > 0:
            action = _ACT_COMBAT[self._combat_idx % len(_ACT_COMBAT)]
            self._combat_idx += 1
        else:
            action = _ACT_EXPLORE[self._explore_idx % len(_ACT_EXPLORE)]
            self._explore_idx += 1

        self._auto_turn += 1
        self._turn_label.configure(text=f"Zug: {self._auto_turn}")
        self._log_game(f"> {action[:80]}", "narr")
        orch.submit_input(action)
        self._waiting_for_input = False

    # ══════════════════════════════════════════════════════════════════════════
    # Preload
    # ══════════════════════════════════════════════════════════════════════════

    def _preload_from_config(self) -> None:
        try:
            import json
            from pathlib import Path
            sc = self.gui.engine.session_config
            adv_name = getattr(sc, "adventure", None) if sc else None
            if not adv_name:
                return
            adv_path = Path(__file__).parent.parent / "modules" / "adventures" / f"{adv_name}.json"
            if not adv_path.exists():
                return
            with adv_path.open(encoding="utf-8-sig") as f:
                adv_data = json.load(f)
            self._generate_layout(adv_data)
            start = adv_data.get("start_location")
            if start:
                self._current_room = start
                self._visit_room(start)
                self._place_party(start)
            self._render()
            self._update_party()
            logger.info("Dungeon-Vorschau: %s (%d Raeume)", adv_name, len(self._rooms))
        except Exception:
            logger.exception("Fehler bei Dungeon-Vorschau")

    # ══════════════════════════════════════════════════════════════════════════
    # GridEngine-Integration
    # ══════════════════════════════════════════════════════════════════════════

    def _get_grid_engine(self):
        """Gibt GridEngine zurueck falls vorhanden, sonst None."""
        return getattr(self.gui.engine, "grid_engine", None)

    def _sync_from_grid(self) -> None:
        """Synchronisiert _char_pos und Raumgroesse aus GridEngine."""
        grid = self._get_grid_engine()
        if not grid or not grid._current_room:
            return
        # Raumgroesse uebernehmen
        self._rw = grid._current_room.width
        self._rh = grid._current_room.height
        # Positionen uebernehmen
        for eid, ent in grid._current_room.entities.items():
            if ent.entity_type == "party_member":
                self._char_pos[ent.name] = (ent.x, ent.y)
        # Monster-Positionen uebernehmen
        if self._current_room:
            m_cells = []
            for eid, ent in grid._current_room.entities.items():
                if ent.entity_type in ("monster", "npc") and ent.alive:
                    m_cells.append((ent.x, ent.y, ent.name))
            if m_cells:
                self._monster_cells[self._current_room] = m_cells

    # ══════════════════════════════════════════════════════════════════════════
    # BFS Layout
    # ══════════════════════════════════════════════════════════════════════════

    def _generate_layout(self, adv_data: dict) -> None:
        self._rooms.clear()
        self._visited.clear()
        self._char_pos.clear()
        self._monster_cells.clear()

        locations: dict[str, dict] = {}
        for loc in adv_data.get("locations", []):
            if isinstance(loc, dict) and "id" in loc:
                locations[loc["id"]] = loc
        if not locations:
            return

        start = adv_data.get("start_location") or next(iter(locations))

        grid: dict[tuple[int, int], str] = {}
        placed: dict[str, tuple[int, int]] = {}
        bfs_q: deque[str] = deque()
        grid[(0, 0)] = start
        placed[start] = (0, 0)
        bfs_q.append(start)

        while bfs_q:
            lid = bfs_q.popleft()
            loc_data = locations.get(lid)
            if not loc_data:
                continue
            px, py = placed[lid]
            exits = loc_data.get("exits", {})
            exit_list = list(exits.items()) if isinstance(exits, dict) else [(e, "") for e in exits]
            di = 0
            for dest_id, desc in exit_list:
                if dest_id in placed or dest_id not in locations:
                    continue
                target = None
                dl = desc.lower() if desc else ""
                for hint, dvec in _DIR_HINTS.items():
                    if hint in dl:
                        target = dvec
                        break
                attempts = ([target] + [d for d in _DIRS if d != target]) if target \
                    else _DIRS[di:] + _DIRS[:di]
                di = (di + 1) % len(_DIRS)
                ok = False
                for dx, dy in attempts:
                    gx, gy = px + dx, py + dy
                    if (gx, gy) not in grid:
                        grid[(gx, gy)] = dest_id
                        placed[dest_id] = (gx, gy)
                        bfs_q.append(dest_id)
                        ok = True
                        break
                if not ok:
                    for r in range(2, 8):
                        for ddx in range(-r, r + 1):
                            for ddy in range(-r, r + 1):
                                if (px + ddx, py + ddy) not in grid:
                                    grid[(px + ddx, py + ddy)] = dest_id
                                    placed[dest_id] = (px + ddx, py + ddy)
                                    bfs_q.append(dest_id)
                                    ok = True
                                    break
                            if ok:
                                break
                        if ok:
                            break

        ny = (max(gy for _, gy in placed.values()) + 2) if placed else 0
        for lid in locations:
            if lid not in placed:
                placed[lid] = (0, ny)
                ny += 1

        # NPC-Index
        npc_idx = {}
        for npc in adv_data.get("npcs", []):
            if isinstance(npc, dict) and "id" in npc:
                npc_idx[npc["id"]] = npc.get("name", npc["id"])

        for lid, (gx, gy) in placed.items():
            loc_data = locations.get(lid, {})
            exits = loc_data.get("exits", {})
            exit_dirs: dict[str, str] = {}
            if isinstance(exits, dict):
                for dest_id, desc in exits.items():
                    if dest_id in placed:
                        dx = placed[dest_id][0] - gx
                        dy = placed[dest_id][1] - gy
                        if abs(dx) >= abs(dy):
                            exit_dirs[dest_id] = "e" if dx > 0 else "w"
                        else:
                            exit_dirs[dest_id] = "s" if dy > 0 else "n"

            # Monster im Raum
            npc_ids = loc_data.get("npcs_present", [])
            monsters = [(npc_idx.get(n, n)) for n in npc_ids]
            m_cells = []
            for i, mname in enumerate(monsters):
                mx = self._rw - 4 - (i % 3) * 2
                my = 2 + (i // 3) * 2
                m_cells.append((mx, my, mname))
            if m_cells:
                self._monster_cells[lid] = m_cells

            self._rooms[lid] = {
                "gx": gx, "gy": gy, "data": loc_data,
                "visited": False, "exit_dirs": exit_dirs,
            }

    # ══════════════════════════════════════════════════════════════════════════
    # Raum-Grid: ASCII
    # ══════════════════════════════════════════════════════════════════════════

    def _build_grid(self, room_id: str) -> list[list[tuple[str, str]]]:
        """Baut Grid[y][x] = (char, tag). Nutzt GridEngine-Dimensionen falls vorhanden."""
        room = self._rooms.get(room_id)
        if not room:
            return []

        # GridEngine-Daten synchronisieren
        self._sync_from_grid()

        rw, rh = self._rw, self._rh

        g: list[list[tuple[str, str]]] = [
            [(S_FLOOR, "floor") for _ in range(rw)] for _ in range(rh)
        ]

        # GridEngine-Terrain uebernehmen falls vorhanden
        grid = self._get_grid_engine()
        grid_room = grid._current_room if grid else None
        if grid_room and grid_room.room_id == room_id:
            for y in range(min(rh, grid_room.height)):
                for x in range(min(rw, grid_room.width)):
                    cell = grid_room.cells[y][x]
                    if cell.terrain == "wall":
                        # Ecken und Raender
                        if y == 0 and x == 0:
                            g[y][x] = (W_TL, "wall")
                        elif y == 0 and x == rw - 1:
                            g[y][x] = (W_TR, "wall")
                        elif y == rh - 1 and x == 0:
                            g[y][x] = (W_BL, "wall")
                        elif y == rh - 1 and x == rw - 1:
                            g[y][x] = (W_BR, "wall")
                        elif y == 0 or y == rh - 1:
                            g[y][x] = (W_H, "wall")
                        else:
                            g[y][x] = (W_V, "wall")
                    elif cell.terrain == "door":
                        g[y][x] = (S_DOOR, "door")
                    elif cell.terrain == "water":
                        g[y][x] = (S_WATER, "water")
                    elif cell.terrain == "obstacle":
                        g[y][x] = (S_RUBBLE, "rubble")
        else:
            # Fallback: altes Verhalten mit statischen Dimensionen
            ed = room.get("exit_dirs", {})
            has = {d for d in ed.values()}

            for x in range(rw):
                g[0][x] = (W_H, "wall")
                g[rh - 1][x] = (W_H, "wall")
            for y in range(rh):
                g[y][0] = (W_V, "wall")
                g[y][rw - 1] = (W_V, "wall")
            g[0][0] = (W_TL, "wall")
            g[0][rw - 1] = (W_TR, "wall")
            g[rh - 1][0] = (W_BL, "wall")
            g[rh - 1][rw - 1] = (W_BR, "wall")

            mx, my = rw // 2, rh // 2
            if "n" in has:
                g[0][mx] = (S_DOOR, "door")
            if "s" in has:
                g[rh - 1][mx] = (S_DOOR, "door")
            if "w" in has:
                g[my][0] = (S_DOOR, "door")
            if "e" in has:
                g[my][rw - 1] = (S_DOOR, "door")

            desc = (room["data"].get("description", "") + " " +
                    room["data"].get("atmosphere", "")).lower()
            if any(w in desc for w in ("wasser", "fluss", "bach", "see")):
                for x in range(3, rw - 3):
                    if rh - 3 > 0:
                        g[rh - 3][x] = (S_WATER, "water")
            if any(w in desc for w in ("schutt", "truemmer", "eingestuerzt")):
                if 4 < rw - 1 and 3 < rh - 1:
                    g[3][4] = (S_RUBBLE, "rubble")
                if rw - 5 > 0 and 4 < rh - 1:
                    g[4][rw - 5] = (S_RUBBLE, "rubble")
            if any(w in desc for w in ("treppe", "stufen", "hinauf")):
                if rw - 2 > 0:
                    g[1][rw - 2] = (S_STAIRS_UP, "stairs")
            if any(w in desc for w in ("hinab", "hinunter", "schacht")):
                if rh - 2 > 0 and rw - 2 > 0:
                    g[rh - 2][rw - 2] = (S_STAIRS_DN, "stairs")
            if any(w in desc for w in ("saeule", "pfeiler")):
                for sx, sy in [(4, 3), (rw - 5, 3), (4, rh - 4), (rw - 5, rh - 4)]:
                    if 1 <= sx < rw - 1 and 1 <= sy < rh - 1:
                        g[sy][sx] = (S_RUBBLE, "rubble")

        # Monster
        m_cells = self._monster_cells.get(room_id, [])
        for mx, my, _mn in m_cells:
            if 1 <= mx < rw - 1 and 1 <= my < rh - 1:
                g[my][mx] = (S_MONSTER, "monster")

        # Combat-Overlay: Bewegungsradius + Waffenreichweite
        overlay = self._calc_combat_overlay(room_id, rw, rh)
        for (ox, oy), otag in overlay.items():
            if 1 <= ox < rw - 1 and 1 <= oy < rh - 1:
                ch, base_tag = g[oy][ox]
                if base_tag == "floor":
                    g[oy][ox] = (ch, otag)

        # Party
        if room_id == self._current_room:
            ps = getattr(self.gui.engine, "party_state", None)
            members = list(ps.members.values()) if ps and hasattr(ps, "members") else []
            for i, m in enumerate(members):
                pos = self._char_pos.get(m.name)
                if not pos:
                    continue
                cx, cy = pos
                if 1 <= cx < rw - 1 and 1 <= cy < rh - 1:
                    arch = getattr(m, "archetype", "?").lower()
                    sym = _CLS.get(arch, arch[0].upper() if arch else "?")
                    tag = f"c{i % len(_COLORS)}"
                    if not m.alive:
                        sym = S_DEAD
                        tag = "dead"
                    g[cy][cx] = (sym, tag)

        return g

    def _calc_combat_overlay(
        self, room_id: str, rw: int, rh: int,
    ) -> dict[tuple[int, int], str]:
        """
        Berechnet Kampf-Overlays fuer Bewegungsradius und Waffenreichweite.

        Nur aktiv wenn CombatTracker laeuft. Zeigt:
          - move_range: Erreichbare Felder (blaues Highlight)
          - reach_zone: Nahkampf-Reichweite (orange Highlight)
          - range_short/medium/long: Fernkampf-Zonen (gruen/gelb/rot)
        """
        overlay: dict[tuple[int, int], str] = {}

        # Nur im aktuellen Raum + aktiver Kampf
        if room_id != self._current_room:
            return overlay

        orch = getattr(self.gui.engine, "orchestrator", None)
        ct = getattr(orch, "_combat_tracker", None) if orch else None
        if not ct or not ct.active:
            return overlay

        grid = self._get_grid_engine()
        if not grid or not grid._current_room:
            return overlay

        # Fuer jeden lebenden Party-Member: Bewegungsradius markieren
        for cid, combatant in ct.combatants.items():
            if not combatant.is_alive or not combatant.is_player:
                continue
            ent = grid._current_room.entities.get(cid)
            if not ent:
                # Fallback: ueber Name suchen
                for eid, e in grid._current_room.entities.items():
                    if e.entity_type == "party_member" and e.alive:
                        ent = e
                        break
            if not ent:
                continue

            mv_left = combatant.movement - combatant.movement_used
            reach = combatant.reach

            # Bewegungsradius (Chebyshev-Distanz <= mv_left)
            for dy in range(-mv_left, mv_left + 1):
                for dx in range(-mv_left, mv_left + 1):
                    dist = max(abs(dx), abs(dy))
                    if dist == 0 or dist > mv_left:
                        continue
                    tx, ty = ent.x + dx, ent.y + dy
                    if (tx, ty) not in overlay:
                        overlay[(tx, ty)] = "move_range"

            # Nahkampf-Reichweite (nur bei reach > 1, z.B. Stangenwaffen)
            if reach > 1:
                for dy in range(-reach, reach + 1):
                    for dx in range(-reach, reach + 1):
                        dist = max(abs(dx), abs(dy))
                        if dist <= 1 or dist > reach:
                            continue
                        tx, ty = ent.x + dx, ent.y + dy
                        overlay[(tx, ty)] = "reach_zone"

        return overlay

    # ══════════════════════════════════════════════════════════════════════════
    # Rendering
    # ══════════════════════════════════════════════════════════════════════════

    def _render(self) -> None:
        if self._view_mode == "room":
            self._render_room()
        else:
            self._render_map()

    def _render_room(self) -> None:
        self._map.configure(state=tk.NORMAL)
        self._map.delete("1.0", tk.END)

        if not self._current_room or self._current_room not in self._rooms:
            self._map.insert(tk.END, "\n  Kein Raum geladen.\n", "info")
            self._map.configure(state=tk.DISABLED)
            return

        room = self._rooms[self._current_room]
        name = room["data"].get("name", self._current_room)
        self._room_label.configure(text=name)

        grid = self._build_grid(self._current_room)

        # Raum rendern
        self._map.insert(tk.END, "\n", "floor")
        for row in grid:
            self._map.insert(tk.END, "    ", "floor")
            for ch, tag in row:
                if self._flash_active:
                    self._map.insert(tk.END, ch, (tag, "flash_red"))
                else:
                    self._map.insert(tk.END, ch, tag)
            self._map.insert(tk.END, "\n", "floor")

        # Legende: Party-Member
        self._map.insert(tk.END, "\n", "floor")
        ps = getattr(self.gui.engine, "party_state", None)
        if ps and hasattr(ps, "members"):
            members = list(ps.members.values())
            for i, m in enumerate(members):
                arch = getattr(m, "archetype", "?").lower()
                sym = _CLS.get(arch, "?")
                tag = f"c{i % len(_COLORS)}"
                status = "TOT" if not m.alive else f"HP {m.hp}/{m.hp_max}"
                self._map.insert(tk.END, f"    {sym}", tag)
                self._map.insert(tk.END, f" = {m.name} ({status})", "desc")
                if i < len(members) - 1:
                    self._map.insert(tk.END, "  ", "floor")
            self._map.insert(tk.END, "\n", "floor")

        # Ausgaenge
        exits = room["data"].get("exits", {})
        if isinstance(exits, dict) and exits:
            self._map.insert(tk.END, "\n    Ausg\u00e4nge: ", "info")
            parts = []
            for did, _d in exits.items():
                dname = self._rooms.get(did, {}).get("data", {}).get("name", did)
                direction = room.get("exit_dirs", {}).get(did, "?")
                dl = {"n": "N", "s": "S", "e": "O", "w": "W"}.get(direction, "?")
                parts.append(f"[{dl}] {dname}")
            self._map.insert(tk.END, "  |  ".join(parts) + "\n", "desc")

        # Status-Nachricht
        if self._status_msg:
            self._map.insert(tk.END, f"\n    {self._status_msg}\n", self._status_tag)

        self._map.configure(state=tk.DISABLED)

    def _render_map(self) -> None:
        self._map.configure(state=tk.NORMAL)
        self._map.delete("1.0", tk.END)
        if not self._rooms:
            self._map.insert(tk.END, "\n  Kein Dungeon.\n", "info")
            self._map.configure(state=tk.DISABLED)
            return

        min_gx = min(r["gx"] for r in self._rooms.values())
        max_gx = max(r["gx"] for r in self._rooms.values())
        min_gy = min(r["gy"] for r in self._rooms.values())
        max_gy = max(r["gy"] for r in self._rooms.values())

        MW, MH, GX, GY = 13, 3, 3, 1
        pos_map: dict[tuple[int, int], str] = {}
        for rid, rm in self._rooms.items():
            pos_map[(rm["gx"], rm["gy"])] = rid

        self._map.insert(tk.END, "\n", "floor")
        for gy in range(min_gy, max_gy + 1):
            for row in range(MH):
                self._map.insert(tk.END, "  ", "floor")
                for gx in range(min_gx, max_gx + 1):
                    rid = pos_map.get((gx, gy))
                    if rid:
                        rm = self._rooms[rid]
                        cur = rid == self._current_room
                        vis = rm["visited"]
                        if not vis and not cur:
                            self._map.insert(tk.END, S_FOG * MW, "fog")
                        else:
                            nm = rm["data"].get("name", rid)
                            tag = "room_current" if cur else "room_visited"
                            if row == 0:
                                self._map.insert(tk.END, W_TL + W_H * (MW - 2) + W_TR, tag)
                            elif row == MH - 1:
                                self._map.insert(tk.END, W_BL + W_H * (MW - 2) + W_BR, tag)
                            else:
                                inner = MW - 2
                                short = nm[:inner] if len(nm) <= inner else nm[:inner - 1] + "."
                                self._map.insert(tk.END, W_V + short.center(inner) + W_V, tag)
                    else:
                        self._map.insert(tk.END, " " * MW, "floor")
                    if gx < max_gx:
                        right = pos_map.get((gx + 1, gy))
                        if rid and right and row == MH // 2:
                            ex = self._rooms.get(rid, {}).get("data", {}).get("exits", {})
                            if isinstance(ex, dict) and right in ex:
                                self._map.insert(tk.END, W_H * GX, "corridor")
                            else:
                                self._map.insert(tk.END, " " * GX, "floor")
                        else:
                            self._map.insert(tk.END, " " * GX, "floor")
                self._map.insert(tk.END, "\n", "floor")
            if gy < max_gy:
                self._map.insert(tk.END, "  ", "floor")
                for gx in range(min_gx, max_gx + 1):
                    rid = pos_map.get((gx, gy))
                    below = pos_map.get((gx, gy + 1))
                    pad = " " * MW
                    if rid and below:
                        ex = self._rooms.get(rid, {}).get("data", {}).get("exits", {})
                        if isinstance(ex, dict) and below in ex:
                            h = MW // 2
                            pad = " " * h + W_V + " " * (MW - h - 1)
                            self._map.insert(tk.END, pad, "corridor")
                        else:
                            self._map.insert(tk.END, pad, "floor")
                    else:
                        self._map.insert(tk.END, pad, "floor")
                    if gx < max_gx:
                        self._map.insert(tk.END, " " * GX, "floor")
                self._map.insert(tk.END, "\n", "floor")

        self._map.insert(tk.END, "\n", "floor")
        cn = self._rooms.get(self._current_room, {}).get("data", {}).get("name", "?")
        self._map.insert(tk.END, f"  {S_SHIELD} {cn}\n", "info")
        self._map.insert(tk.END, f"  {len(self._visited)}/{len(self._rooms)} erkundet\n", "desc")
        self._map.configure(state=tk.DISABLED)

    # ══════════════════════════════════════════════════════════════════════════
    # Party Panel
    # ══════════════════════════════════════════════════════════════════════════

    def _update_party(self) -> None:
        self._party.configure(state=tk.NORMAL)
        self._party.delete("1.0", tk.END)

        ps = getattr(self.gui.engine, "party_state", None)
        if not ps or not hasattr(ps, "members"):
            c = getattr(self.gui.engine, "character", None)
            if c:
                self._party.insert(tk.END, f" {c.name}\n", "header")
                hp = c._stats.get("HP", "?")
                hp_max = c._stats_max.get("HP", "?")
                self._party.insert(tk.END, f" HP: {hp}/{hp_max}\n", "alive")
            else:
                self._party.insert(tk.END, " Warte auf Start...\n", "label")
            self._party.configure(state=tk.DISABLED)
            return

        members = list(ps.members.values())
        alive = len(ps.alive_members())
        total = len(members)
        self._party.insert(tk.END, f" Party ({alive}/{total})\n", "header")
        self._party.insert(tk.END, " " + "\u2500" * 22 + "\n", "label")

        for i, m in enumerate(members):
            arch = getattr(m, "archetype", "?").lower()
            sym = _CLS.get(arch, "?")
            ctag = f"m{i % len(_COLORS)}"

            if not m.alive:
                self._party.insert(tk.END, f" {S_DEAD} {m.name}", "dead")
                self._party.insert(tk.END, "  TOT\n", "dead")
                continue

            hp_pct = (m.hp / m.hp_max * 100) if m.hp_max > 0 else 0
            hp_tag = "alive" if hp_pct > 50 else "hurt" if hp_pct > 25 else "critical"
            bar_n = 8
            filled = max(0, min(bar_n, int(hp_pct / 100 * bar_n)))
            bar = "\u2588" * filled + "\u2591" * (bar_n - filled)

            self._party.insert(tk.END, f" [{sym}] ", ctag)
            self._party.insert(tk.END, f"{m.name:<10s}", ctag)
            self._party.insert(tk.END, f" {bar}", hp_tag)
            self._party.insert(tk.END, f" {m.hp}/{m.hp_max}\n", hp_tag)

            if m.spells_remaining:
                sp = [f"L{l}:{c}" for l, c in sorted(m.spells_remaining.items()) if c > 0]
                if sp:
                    self._party.insert(tk.END, f"       {', '.join(sp)}\n", "spell")

        # Kampf-Info: Bewegung + Reichweite (nur bei aktivem Kampf)
        self._render_combat_info()

        self._party.configure(state=tk.DISABLED)

    def _render_combat_info(self) -> None:
        """Zeigt Kampf-Mechanik-Info im Party-Panel (Bewegung, Reichweite, Runde)."""
        orch = getattr(self.gui.engine, "orchestrator", None)
        ct = getattr(orch, "_combat_tracker", None) if orch else None
        if not ct or not ct.active:
            return

        self._party.insert(tk.END, "\n", "label")
        self._party.insert(tk.END, " " + "\u2500" * 22 + "\n", "label")
        rnd = ct.round
        who = "Spieler" if ct.player_first else "Monster"
        self._party.insert(tk.END, f" Runde {rnd} ({who})\n", "header")

        for cid, c in ct.combatants.items():
            if not c.is_alive:
                continue
            mv_left = c.movement - c.movement_used
            mv_total = c.movement
            atk_left = ct.get_max_attacks(cid) - c.attacks_this_round
            atk_total = ct.get_max_attacks(cid)

            # Bewegungsbalken (8 Zeichen)
            bar_n = 8
            pct = (mv_left / mv_total * 100) if mv_total > 0 else 0
            filled = max(0, min(bar_n, int(pct / 100 * bar_n)))
            bar = "\u2588" * filled + "\u2591" * (bar_n - filled)
            mv_tag = "alive" if pct > 50 else "hurt" if pct > 25 else "critical"

            prefix = " \u2192 " if c.is_player else " \u2666 "
            self._party.insert(tk.END, prefix, "label")
            self._party.insert(tk.END, f"{c.name[:8]:<8s} ", "label")
            self._party.insert(tk.END, f"{bar}", mv_tag)
            self._party.insert(tk.END, f" {mv_left}/{mv_total}", mv_tag)

            # Reichweite + Angriffe
            extras = []
            if c.reach > 1:
                extras.append(f"Rw:{c.reach}")
            extras.append(f"Atk:{atk_left}/{atk_total}")
            if extras:
                self._party.insert(tk.END, f" {' '.join(extras)}", "label")
            self._party.insert(tk.END, "\n", "label")

    # ══════════════════════════════════════════════════════════════════════════
    # Charakter-Positionierung
    # ══════════════════════════════════════════════════════════════════════════

    def _place_party(self, room_id: str, entry: str = "w") -> None:
        # GridEngine hat die Positionen? Dann von dort lesen.
        grid = self._get_grid_engine()
        if grid and grid._current_room and grid._party_members:
            self._sync_from_grid()
            return

        self._char_pos.clear()
        ps = getattr(self.gui.engine, "party_state", None)
        if not ps or not hasattr(ps, "members"):
            return
        members = list(ps.members.values())
        rw, rh = self._rw, self._rh
        # Startposition nach Eingangsrichtung
        configs = {
            "w": (2, 3, 1, 1), "e": (rw - 3, 3, -1, 1),
            "n": (3, 2, 2, 1), "s": (3, rh - 3, 2, -1),
        }
        sx, sy, dx, dy = configs.get(entry, (2, 3, 1, 1))
        for i, m in enumerate(members):
            x = sx + (i % 3) * abs(dx) * (1 if dx >= 0 else -1)
            y = sy + (i // 3) * abs(dy) * (1 if dy >= 0 else -1)
            self._char_pos[m.name] = (max(1, min(rw - 2, x)), max(1, min(rh - 2, y)))

    # ══════════════════════════════════════════════════════════════════════════
    # Logging
    # ══════════════════════════════════════════════════════════════════════════

    def _log_game(self, text: str, tag: str = "narr") -> None:
        self._glog.configure(state=tk.NORMAL)
        self._glog.insert(tk.END, f" {text}\n", tag)
        self._glog.see(tk.END)
        self._glog.configure(state=tk.DISABLED)

    def _log_rules(self, text: str, tag: str = "sys") -> None:
        self._rlog.configure(state=tk.NORMAL)
        self._rlog.insert(tk.END, f" {text}\n", tag)
        self._rlog.see(tk.END)
        self._rlog.configure(state=tk.DISABLED)

    # ══════════════════════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _visit_room(self, lid: str) -> None:
        if lid in self._rooms:
            self._rooms[lid]["visited"] = True
            self._visited.add(lid)

    def _play_sound(self, kind: str) -> None:
        if not self._sounds_on:
            return
        def _beep():
            try:
                import winsound
                sounds = {
                    "move": [(500, 80)],
                    "combat": [(800, 80), (600, 80)],
                    "hp_loss": [(300, 200), (200, 200)],
                    "probe": [(1000, 50), (1200, 50)],
                    "dice": [(800, 40), (1000, 40), (1200, 40)],
                    "item": [(1000, 60), (1200, 60), (1400, 60)],
                    "death": [(200, 400), (150, 400)],
                    "heal": [(800, 60), (1000, 60), (1200, 60)],
                    "xp": [(600, 50), (800, 50), (1000, 50), (1200, 80)],
                }
                for freq, dur in sounds.get(kind, []):
                    winsound.Beep(freq, dur)
            except Exception:
                pass
        threading.Thread(target=_beep, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    # Engine Ready
    # ══════════════════════════════════════════════════════════════════════════

    def on_engine_ready(self) -> None:
        try:
            engine = self.gui.engine
            if hasattr(engine, "_adv_manager") and engine._adv_manager and engine._adv_manager.loaded:
                self._generate_layout(engine._adv_manager._data)
                self._current_room = engine._adv_manager.current_location_id
                if self._current_room:
                    self._visit_room(self._current_room)
                    self._place_party(self._current_room)
                # GridEngine-Sync (falls bereits initialisiert)
                self._sync_from_grid()
                self._render()
                self._update_party()
                try:
                    notebook = self.master
                    if notebook and hasattr(notebook, "select"):
                        notebook.select(self)
                except Exception:
                    pass
                logger.info("Dungeon: %d Raeume, Start=%s", len(self._rooms), self._current_room)
            else:
                logger.info("on_engine_ready: Kein Adventure.")
        except Exception:
            logger.exception("Fehler in on_engine_ready")

    # ══════════════════════════════════════════════════════════════════════════
    # Event Handler — Das Herzstueck der Animation
    # ══════════════════════════════════════════════════════════════════════════

    def handle_event(self, data: dict[str, Any]) -> None:
        event = data.get("_event", "")
        if not event:
            return
        # Debug: Grid/Party/Adventure Events loggen
        if event.startswith(("grid.", "party.", "adventure.")):
            logger.info("DungeonView Event: %s", event)
        try:
            self._on_event(event, data)
        except Exception:
            logger.exception("Event error: %s", event)

    def _on_event(self, event: str, data: dict[str, Any]) -> None:

        # ── Adventure geladen ──
        if event == "adventure.loaded":
            engine = self.gui.engine
            if hasattr(engine, "_adv_manager") and engine._adv_manager:
                self._generate_layout(engine._adv_manager._data)
                self._current_room = engine._adv_manager.current_location_id
                if self._current_room:
                    self._visit_room(self._current_room)
                    self._place_party(self._current_room)
                self._render()
                self._update_party()
            return

        # ── Warten auf Input → Auto-Crawl ──
        if event == "game.waiting_for_input":
            self._waiting_for_input = True
            if self._auto_play:
                self._schedule_auto_input()
            return

        # ── Ortswechsel → Animierte Bewegung ──
        if event == "adventure.location_changed":
            old = self._current_room
            new_loc = data.get("new", "")
            loc_name = data.get("name", "?")
            self._current_room = new_loc
            self._visit_room(new_loc)
            self._combat_turns = 0
            self._stagnant_turns = 0

            # GridEngine-Sync: Raumgroesse + Positionen aktualisieren
            self._sync_from_grid()

            # Eingangsrichtung
            entry = "w"
            if old and old in self._rooms:
                leave = self._rooms[old].get("exit_dirs", {}).get(new_loc, "e")
                entry = {"n": "s", "s": "n", "e": "w", "w": "e"}.get(leave, "w")

            self._place_party(new_loc, entry)
            self._render()  # Sofort rendern mit neuen Positionen
            self._anim_status(f"{S_SHIELD} {loc_name}", "move", 1500)
            self._log_game(f"\u2192 {loc_name}", "move")
            self._play_sound("move")
            self._update_party()

            # Monster im neuen Raum? Kampf-Ankuendigung
            m_cells = self._monster_cells.get(new_loc, [])
            if m_cells:
                names = ", ".join(mn for _, _, mn in m_cells[:3])
                self._queue_anim([
                    (lambda n=names: self._anim_status(
                        f"{S_SWORD} Feinde: {n}", "combat", 1500), 800),
                ])
            return

        # ── Game Output → Logs + Animation ──
        if event == "game.output":
            tag = data.get("tag", "")
            text = data.get("text", "")

            if tag in ("combat", "combat_hit"):
                self._combat_turns += 1
                self._stagnant_turns = 0
                self._log_game(f"{S_SWORD} {text[:120]}", "combat")
                self._log_rules(f"{S_SWORD} {text[:100]}", "stat")

                # Animation: Party rueckt zu Monstern
                m_cells = self._monster_cells.get(self._current_room, [])
                if m_cells:
                    tx, ty = m_cells[0][0], m_cells[0][1]
                    ps = getattr(self.gui.engine, "party_state", None)
                    if ps:
                        fighters = [m for m in ps.alive_members()
                                    if getattr(m, "archetype", "").lower()
                                    in ("fighter", "kaempfer", "paladin", "ritter",
                                        "ranger", "waldlaeufer")]
                        for f in fighters[:3]:
                            self._anim_move_char(f.name, tx - 1, ty)
                self._anim_combat_flash()
                self._anim_status(f"{S_SWORD} {text[:60]}", "combat", 1200)
                return

            if tag == "combat_miss":
                self._log_game(f"{S_SWORD} {text[:120]}", "combat")
                self._log_rules(f"  Verfehlt: {text[:80]}", "sys")
                self._play_sound("combat")
                return

            if tag == "stat":
                self._log_rules(f"{S_HEART} {text[:100]}", "stat")
                tl = text.lower()
                if "hp" in tl and any(w in tl for w in ("verlust", "verlier", "-")):
                    self._play_sound("hp_loss")
                    self._anim_combat_flash("flash_red")
                elif "heil" in tl or "+" in tl:
                    self._play_sound("heal")
                    self._flash_active = True
                    self._queue_anim([
                        (self._render, 300),
                        (lambda: setattr(self, "_flash_active", False), 0),
                        (self._render, 50),
                    ])
                self._update_party()
                return

            if tag == "probe":
                self._log_rules(f"{S_SPARK} {text[:100]}", "probe")
                self._play_sound("probe")
                self._stagnant_turns = 0
                return

            if tag == "dice":
                self._log_rules(f"{S_SPARK} {text[:100]}", "dice")
                self._play_sound("dice")
                return

            if tag == "inventory":
                self._log_game(f"  {S_TREASURE} {text[:100]}", "item")
                self._log_rules(f"  {S_TREASURE} {text[:60]}", "rule")
                self._play_sound("item")
                self._stagnant_turns = 0
                return

            if tag == "player":
                self._log_game(f"> {text[:150]}", "narr")
                return

            if tag == "stream_end":
                if text.strip():
                    # Nur kurzen Auszug in Game-Log
                    short = text.strip()[:200]
                    self._log_game(short, "keeper")
                return

            if tag == "rules_warning":
                self._log_rules(f"\u26A0 {text[:100]}", "warn")
                return

            if tag == "system":
                self._log_game(f"  {text[:100]}", "sys")
                return

            return

        # ── Keeper fertig ──
        if event == "keeper.response_complete":
            self._auto_turn += 1
            self._turn_label.configure(text=f"Zug: {self._auto_turn}")
            # Stagnation checken
            self._stagnant_turns += 1
            return

        if event == "keeper.usage_update":
            # Kosten im Rules-Log
            cost = data.get("total_cost", 0)
            if cost > 0:
                self._log_rules(f"  API: ${cost:.4f}", "sys")
            return

        # ── Party Events ──
        if event == "party.state_updated":
            self._update_party()
            self._render()
            action = data.get("action", "")
            if action == "damage":
                char = data.get("character", "?")
                amt = data.get("amount", 0)
                self._anim_status(f"{S_HEART} {char} -{amt} HP!", "combat", 1000)
            elif action == "healing":
                char = data.get("character", "?")
                amt = data.get("amount", 0)
                self._anim_status(f"{S_HEART} {char} +{amt} HP", "heal", 1000)
            elif action == "xp_gain":
                amt = data.get("amount", 0)
                self._anim_status(f"{S_SPARK} +{amt} XP!", "info", 1000)
                self._play_sound("xp")
                self._combat_turns = 0
            return

        if event == "party.member_died":
            name = data.get("name", "?")
            self._log_game(f"\n  {S_DEAD} {name} ist gefallen!\n", "combat")
            self._log_rules(f"{S_DEAD} {name} TOT", "warn")
            self._play_sound("death")
            self._anim_status(f"{S_DEAD} {name} ist gefallen!", "combat", 2000)
            self._update_party()
            self._render()
            return

        if event == "party.tpk":
            self._log_game(f"\n  {S_DEAD}{S_DEAD}{S_DEAD} TOTAL PARTY KILL {S_DEAD}{S_DEAD}{S_DEAD}\n", "combat")
            self._play_sound("death")
            self._auto_play = False
            self._auto_btn.configure(text="\u25B6 Auto-Crawl")
            self._update_party()
            return

        # ── Flag → Monster-Tracking ──
        if event == "adventure.flag_changed":
            key = data.get("key", "")
            if "besiegt" in key or "geraeumt" in key:
                stem = key.replace("_besiegt", "").replace("_geraeumt", "")
                for rl in list(self._monster_cells.keys()):
                    if stem in rl:
                        self._monster_cells[rl] = []
                self._render()
                self._combat_turns = 0
            return

        # ── Grid-Engine Events ──
        if event == "grid.room_setup":
            self._rw = data.get("width", RW)
            self._rh = data.get("height", RH)
            self._sync_from_grid()
            self._render()
            return

        if event == "grid.formation_placed":
            positions = data.get("positions", {})
            # Entity-IDs zu Namen aufloesen
            grid = self._get_grid_engine()
            if grid and grid._current_room:
                for eid, (x, y) in positions.items():
                    ent = grid._current_room.entities.get(eid)
                    if ent:
                        self._char_pos[ent.name] = (x, y)
            self._render()
            self._update_party()
            return

        if event == "grid.entity_moved":
            path = data.get("path", [])
            name = data.get("name", "")
            if path and name:
                # Animierte Pfad-Bewegung
                tx, ty = path[-1]
                self._anim_move_char(name, tx, ty)
            return

        if event == "grid.combat_move":
            path = data.get("path", [])
            attacker_name = data.get("attacker_name", "")
            target_name = data.get("target_name", "")
            if path and attacker_name:
                tx, ty = path[-1]
                self._anim_move_char(attacker_name, tx, ty)
                self._anim_combat_flash()
                self._anim_status(
                    f"{S_SWORD} {attacker_name} \u2192 {target_name}", "combat", 1000)
            return
