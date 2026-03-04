"""
gui/tab_replay_viewer.py — Tab 13: Replay-Viewer fuer Testlaeufe

Spielt JSON-Reports aus virtual_player.py visuell ab:
  - Pixel-Art Grid-Ansicht mit Terrain, Entities, Party-Member (0x72 Tileset)
  - Animierte Move-Trails (gruen=Party, rot=Monster, gelb=Combat)
  - Party-HP-Balken pro Zug
  - Keeper-Text mit farbig hervorgehobenen Tags
  - Play/Pause, Prev/Next, Speed-Slider, Turn-Slider
"""

from __future__ import annotations

import json
import logging
import re
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE, BLUE, LAVENDER,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, FONT_HEADER,
    PAD, PAD_SMALL,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.replay")

# ── PIL + Pixel-Renderer ────────────────────────────────────────────────────

try:
    from PIL import Image, ImageDraw, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from gui.pixel_renderer import (
        PixelTileset, render_room_to_image, TILE, SCALE,
    )
    HAS_RENDERER = True
except ImportError:
    HAS_RENDERER = False

# ── Klassen-Symbole ─────────────────────────────────────────────────────────

_CLS: dict[str, str] = {
    "fighter": "F", "kaempfer": "F", "mage": "M", "magier": "M", "wizard": "M",
    "cleric": "C", "kleriker": "C", "priester": "C", "thief": "T", "dieb": "T",
    "schurke": "T", "ranger": "R", "waldlaeufer": "R", "paladin": "P",
    "ritter": "P", "bard": "B", "barde": "B", "druid": "D", "druide": "D",
}
_COLORS = [GREEN, YELLOW, BLUE, ORANGE, "#CBA6F7", "#F5C2E7"]

# Tag-Regex fuer Highlighting
_TAG_RE = re.compile(r"(\[[A-Z_]+:[^\]]*\])")
_TAG_COLORS: dict[str, str] = {
    "ANGRIFF": RED,
    "HP_VERLUST": RED,
    "STABILITAET_VERLUST": RED,
    "RETTUNGSWURF": RED,
    "MONSTER_BEWEGT": RED,
    "PROBE": YELLOW,
    "FERTIGKEIT_GENUTZT": YELLOW,
    "ZAUBER_VERBRAUCHT": YELLOW,
    "FAKT": GREEN,
    "HP_HEILUNG": GREEN,
    "XP_GEWINN": GREEN,
    "INVENTAR": BLUE,
    "STIMME": BLUE,
    "ZEIT_VERGEHT": ORANGE,
    "TAGESZEIT": ORANGE,
    "WETTER": ORANGE,
}


class ReplayViewerTab(ttk.Frame):
    """Replay-Viewer: Testlaeufe visuell abspielen mit Pixel-Art."""

    def __init__(self, parent: ttk.Notebook, gui: "TechGUI") -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        # State
        self._data: dict | None = None
        self._turns: list[dict] = []
        self._current_idx: int = 0
        self._playing: bool = False
        self._play_after_id: str | None = None
        self._speed_ms: int = 2000
        self._entity_color_map: dict[str, int] = {}

        # Pixel-Renderer
        self._tileset: PixelTileset | None = None
        self._tk_image: Any = None  # GC-Schutz
        self._canvas_img_id: int | None = None

        if HAS_PIL and HAS_RENDERER:
            self._tileset = PixelTileset()
            self._tileset.load()

        self._build_ui()

    # ── UI-Aufbau ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """4-Panel-Layout: Grid links, Controls+Text+HP rechts, Datei-Bar unten."""
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        # ── Linkes Panel: Grid-Ansicht (Canvas) ─────────────────────────────
        left = ttk.Frame(pane, style="Dark.TFrame")
        pane.add(left, weight=2)

        ttk.Label(left, text="Grid-Ansicht", style="Header.TLabel").pack(
            anchor=tk.W, padx=PAD, pady=(PAD, 0),
        )
        self._room_label = ttk.Label(left, text="", style="Muted.TLabel")
        self._room_label.pack(anchor=tk.W, padx=PAD)

        # Canvas fuer Pixel-Art (statt tk.Text)
        self._canvas = tk.Canvas(
            left, bg="#050308", highlightthickness=0, cursor="arrow",
        )
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        # Legende unter dem Canvas
        self._legend_frame = ttk.Frame(left, style="Dark.TFrame")
        self._legend_frame.pack(fill=tk.X, padx=PAD, pady=(0, PAD))

        # ── Rechtes Panel: Controls + Keeper-Text + HP ──────────────────────
        right = ttk.Frame(pane, style="Dark.TFrame")
        pane.add(right, weight=3)

        # Controls-Frame
        ctrl = ttk.Frame(right, style="Dark.TFrame")
        ctrl.pack(fill=tk.X, padx=PAD, pady=(PAD, 0))

        self._btn_prev = ttk.Button(ctrl, text="\u25C4 Prev", command=self._prev_turn)
        self._btn_prev.pack(side=tk.LEFT, padx=2)
        self._btn_play = ttk.Button(ctrl, text="\u25B6 Play", command=self._play_toggle)
        self._btn_play.pack(side=tk.LEFT, padx=2)
        self._btn_next = ttk.Button(ctrl, text="Next \u25BA", command=self._next_turn)
        self._btn_next.pack(side=tk.LEFT, padx=2)

        ttk.Label(ctrl, text="  Zug:", style="TLabel").pack(side=tk.LEFT, padx=(12, 2))
        self._turn_var = tk.IntVar(value=0)
        self._turn_slider = ttk.Scale(
            ctrl, from_=0, to=0, variable=self._turn_var,
            orient=tk.HORIZONTAL, command=self._on_slider_change,
        )
        self._turn_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self._turn_label = ttk.Label(ctrl, text="0/0", style="TLabel", width=8)
        self._turn_label.pack(side=tk.LEFT, padx=2)

        # Speed-Frame
        speed_f = ttk.Frame(right, style="Dark.TFrame")
        speed_f.pack(fill=tk.X, padx=PAD, pady=(PAD_SMALL, 0))
        ttk.Label(speed_f, text="Geschw:", style="TLabel").pack(side=tk.LEFT)
        self._speed_var = tk.IntVar(value=2000)
        self._speed_slider = ttk.Scale(
            speed_f, from_=500, to=5000, variable=self._speed_var,
            orient=tk.HORIZONTAL,
        )
        self._speed_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._speed_label = ttk.Label(speed_f, text="2.0s", style="Muted.TLabel", width=6)
        self._speed_label.pack(side=tk.LEFT)
        self._speed_var.trace_add("write", self._on_speed_change)

        # Separator
        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        # Keeper-Text
        ttk.Label(right, text="Keeper-Antwort", style="Header.TLabel").pack(
            anchor=tk.W, padx=PAD,
        )
        self._keeper_text = tk.Text(
            right, bg=BG_PANEL, fg=FG_PRIMARY, font=FONT_NORMAL,
            wrap=tk.WORD, state=tk.DISABLED, height=12,
            borderwidth=0, highlightthickness=0,
        )
        self._keeper_text.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=(PAD_SMALL, 0))
        self._configure_keeper_tags()

        # Separator
        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        # Party-HP-Panel
        ttk.Label(right, text="Party HP", style="Header.TLabel").pack(
            anchor=tk.W, padx=PAD,
        )
        self._hp_canvas = tk.Canvas(
            right, bg=BG_PANEL, height=80, highlightthickness=0,
        )
        self._hp_canvas.pack(fill=tk.X, padx=PAD, pady=(PAD_SMALL, PAD))

        # ── Datei-Bar (unten) ─────────────────────────────────────────────────
        file_bar = ttk.Frame(self, style="Dark.TFrame")
        file_bar.pack(fill=tk.X, padx=PAD, pady=(0, PAD))
        ttk.Button(file_bar, text="Datei laden...", command=self._load_file).pack(
            side=tk.LEFT, padx=2,
        )
        self._file_label = ttk.Label(file_bar, text="Keine Datei geladen", style="Muted.TLabel")
        self._file_label.pack(side=tk.LEFT, padx=8)

    def _configure_keeper_tags(self) -> None:
        """Text-Tags fuer die Keeper-Textansicht."""
        self._keeper_text.tag_configure("player", foreground=FG_ACCENT, font=FONT_BOLD)
        self._keeper_text.tag_configure("normal", foreground=FG_PRIMARY)
        self._keeper_text.tag_configure("tag_red", foreground=RED, font=FONT_BOLD)
        self._keeper_text.tag_configure("tag_yellow", foreground=YELLOW, font=FONT_BOLD)
        self._keeper_text.tag_configure("tag_green", foreground=GREEN, font=FONT_BOLD)
        self._keeper_text.tag_configure("tag_orange", foreground=ORANGE, font=FONT_BOLD)
        self._keeper_text.tag_configure("tag_blue", foreground=BLUE, font=FONT_BOLD)

    # ── Datei laden ──────────────────────────────────────────────────────────

    def _load_file(self) -> None:
        """JSON-Report laden und Replay vorbereiten."""
        path = filedialog.askopenfilename(
            title="Testlauf-Report laden",
            initialdir=str(Path("data/test_results")),
            filetypes=[("JSON-Reports", "*.json"), ("Alle Dateien", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                self._data = json.load(fh)
        except Exception as exc:
            logger.error("Fehler beim Laden von %s: %s", path, exc)
            self._file_label.configure(text=f"Fehler: {exc}")
            return

        self._turns = self._data.get("turns", [])
        if not self._turns:
            self._file_label.configure(text="Keine Zuege im Report.")
            return

        # Entity-Farb-Map aufbauen (stabil ueber alle Zuege)
        self._entity_color_map.clear()
        color_idx = 0
        for turn in self._turns:
            for eid, einfo in turn.get("grid_entities", {}).items():
                if einfo.get("type") == "party_member" and eid not in self._entity_color_map:
                    self._entity_color_map[eid] = color_idx % len(_COLORS)
                    color_idx += 1

        # Slider konfigurieren
        max_idx = len(self._turns) - 1
        self._turn_slider.configure(from_=0, to=max_idx)
        self._current_idx = 0
        self._turn_var.set(0)

        fname = Path(path).name
        module = self._data.get("module", "?")
        adventure = self._data.get("adventure", "?")
        self._file_label.configure(text=f"{fname}  ({module} / {adventure})")

        self._goto_turn(0)
        logger.info("Replay geladen: %s (%d Zuege)", fname, len(self._turns))

    # ── Navigation ───────────────────────────────────────────────────────────

    def _goto_turn(self, idx: int) -> None:
        """Zeigt einen bestimmten Zug an."""
        if not self._turns:
            return
        idx = max(0, min(idx, len(self._turns) - 1))
        self._current_idx = idx
        self._turn_var.set(idx)
        self._turn_label.configure(text=f"{idx + 1}/{len(self._turns)}")

        turn = self._turns[idx]
        self._render_grid(turn)
        self._update_keeper_text(turn)
        self._update_party_hp(turn.get("party_hp", {}))

    def _prev_turn(self) -> None:
        if self._current_idx > 0:
            self._goto_turn(self._current_idx - 1)

    def _next_turn(self) -> None:
        if self._current_idx < len(self._turns) - 1:
            self._goto_turn(self._current_idx + 1)

    def _on_slider_change(self, _val: str) -> None:
        idx = int(float(_val))
        if idx != self._current_idx:
            self._goto_turn(idx)

    def _on_speed_change(self, *_args: Any) -> None:
        ms = self._speed_var.get()
        self._speed_ms = ms
        self._speed_label.configure(text=f"{ms / 1000:.1f}s")

    # ── Play/Pause ───────────────────────────────────────────────────────────

    def _play_toggle(self) -> None:
        if self._playing:
            self._playing = False
            self._btn_play.configure(text="\u25B6 Play")
            if self._play_after_id:
                self.after_cancel(self._play_after_id)
                self._play_after_id = None
        else:
            self._playing = True
            self._btn_play.configure(text="\u23F8 Pause")
            self._play_step()

    def _play_step(self) -> None:
        """Auto-Advance einen Zug weiter."""
        if not self._playing:
            return
        if self._current_idx < len(self._turns) - 1:
            self._goto_turn(self._current_idx + 1)
            self._play_after_id = self.after(self._speed_ms, self._play_step)
        else:
            self._playing = False
            self._btn_play.configure(text="\u25B6 Play")

    # ── Grid-Rendering (Pixel-Art) ───────────────────────────────────────────

    def _render_grid(self, turn: dict) -> None:
        """Rendert die Grid-Ansicht fuer einen Zug als Pixel-Art."""
        room_id = turn.get("room_id", "")
        terrain = turn.get("room_terrain", [])
        positions = turn.get("grid_positions", {})
        entities = turn.get("grid_entities", {})
        move_events = turn.get("move_events", [])

        self._room_label.configure(text=room_id or "\u2014")

        if not terrain or not self._tileset or not HAS_PIL:
            # Kein Grid-Snapshot — Fallback-Text auf Canvas
            self._canvas.delete("all")
            msg = "Kein Grid-Snapshot" if not terrain else "PIL nicht verfuegbar"
            self._canvas.create_text(
                120, 40, text=msg, fill=FG_MUTED, font=FONT_NORMAL, anchor=tk.W,
            )
            self._update_legend(entities, turn.get("party_hp", {}))
            return

        # Entity-Liste fuer Renderer aufbauen
        entity_list: list[dict] = []
        for eid, pos in positions.items():
            if not pos or len(pos) < 2:
                continue
            einfo = entities.get(eid, {})
            entity_list.append({
                "entity_id": eid,
                "x": int(pos[0]),
                "y": int(pos[1]),
                "type": einfo.get("type", ""),
                "name": einfo.get("name", eid),
                "symbol": einfo.get("symbol", "?"),
                "alive": einfo.get("alive", True),
            })

        # Move-Trails aufbereiten
        trails: list[dict] = []
        for me in move_events:
            trail_type = me.get("move_type", "party_member")
            trails.append({
                "move_type": trail_type,
                "path": me.get("path", []),
                "from": me.get("from"),
                "to": me.get("to"),
            })

        # Rendern
        img = render_room_to_image(
            terrain, self._tileset,
            room_id=room_id,
            entities=entity_list,
            party_color_map=self._entity_color_map,
            move_trails=trails if self._playing else None,
            scale=SCALE,
        )

        if img is None:
            return

        # Auto-Center: Canvas-Groesse anpassen
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        iw, ih = img.width, img.height

        # Wenn Bild groesser als Canvas: runterskalieren
        if cw > 10 and ch > 10 and (iw > cw or ih > ch):
            ratio = min(cw / iw, ch / ih)
            if ratio < 1.0:
                nw = max(1, int(iw * ratio))
                nh = max(1, int(ih * ratio))
                img = img.resize((nw, nh), Image.NEAREST)

        self._tk_image = ImageTk.PhotoImage(img)
        if self._canvas_img_id is None:
            self._canvas_img_id = self._canvas.create_image(
                0, 0, anchor=tk.NW, image=self._tk_image,
            )
        else:
            self._canvas.itemconfig(self._canvas_img_id, image=self._tk_image)

        # Legende aktualisieren
        self._update_legend(entities, turn.get("party_hp", {}))

    def _update_legend(self, entities: dict, party_hp: dict) -> None:
        """Aktualisiert die Legende unter dem Canvas."""
        for w in self._legend_frame.winfo_children():
            w.destroy()

        for eid, einfo in entities.items():
            if einfo.get("type") != "party_member":
                continue
            ci = self._entity_color_map.get(eid, 0)
            color = _COLORS[ci % len(_COLORS)]
            name = einfo.get("name", eid)
            symbol = einfo.get("symbol", "?")
            alive = einfo.get("alive", True)
            hp_info = party_hp.get(name, {})
            hp = hp_info.get("hp", "?")
            hp_max = hp_info.get("hp_max", "?")
            status = "TOT" if not alive else f"HP {hp}/{hp_max}"
            lbl = tk.Label(
                self._legend_frame,
                text=f" {symbol} {name} ({status}) ",
                fg=color, bg=BG_DARK, font=FONT_SMALL,
            )
            lbl.pack(side=tk.LEFT, padx=2)

    # ── Keeper-Text mit Tag-Highlighting ─────────────────────────────────────

    def _update_keeper_text(self, turn: dict) -> None:
        """Zeigt Player-Input + Keeper-Response mit Tag-Highlighting."""
        self._keeper_text.configure(state=tk.NORMAL)
        self._keeper_text.delete("1.0", tk.END)

        player = turn.get("player_input", "")
        response = turn.get("keeper_response", "")
        turn_num = turn.get("turn", 0)
        latency = turn.get("latency_ms", 0)

        self._keeper_text.insert(tk.END, f"Zug {turn_num}", "player")
        self._keeper_text.insert(tk.END, f"  ({latency:.0f}ms)\n", "normal")

        if player:
            self._keeper_text.insert(tk.END, f"\u25B6 {player}\n\n", "player")

        if response:
            self._insert_highlighted(response)

        self._keeper_text.configure(state=tk.DISABLED)

    def _insert_highlighted(self, text: str) -> None:
        """Fuegt Text mit farbigen Tags ein."""
        parts = _TAG_RE.split(text)
        for part in parts:
            if _TAG_RE.match(part):
                tag_type = part.split(":")[0].strip("[")
                color_name = _TAG_COLORS.get(tag_type)
                if color_name == RED:
                    tag = "tag_red"
                elif color_name == YELLOW:
                    tag = "tag_yellow"
                elif color_name == GREEN:
                    tag = "tag_green"
                elif color_name == BLUE:
                    tag = "tag_blue"
                else:
                    tag = "tag_orange"
                self._keeper_text.insert(tk.END, part, tag)
            else:
                self._keeper_text.insert(tk.END, part, "normal")

    # ── Party-HP-Balken ──────────────────────────────────────────────────────

    def _update_party_hp(self, party_hp: dict) -> None:
        """Zeichnet HP-Balken pro Party-Member."""
        self._hp_canvas.delete("all")

        if not party_hp:
            self._hp_canvas.create_text(
                10, 20, text="Keine Party-HP-Daten", fill=FG_MUTED,
                font=FONT_SMALL, anchor=tk.W,
            )
            return

        bar_h = 16
        spacing = 4
        y = 4
        max_bar_w = 200

        for name, info in party_hp.items():
            hp = info.get("hp", 0)
            hp_max = info.get("hp_max", 1)
            alive = info.get("alive", True)
            archetype = info.get("archetype", "?")

            ratio = max(0, min(1, hp / max(1, hp_max)))
            bar_w = int(max_bar_w * ratio)

            if not alive:
                bar_color = "#6C7086"
            elif ratio > 0.5:
                bar_color = GREEN
            elif ratio > 0.25:
                bar_color = YELLOW
            else:
                bar_color = RED

            sym = _CLS.get(archetype.lower(), "?")
            label = f"{sym} {name}"

            self._hp_canvas.create_text(
                4, y + bar_h // 2, text=label, fill=FG_PRIMARY,
                font=FONT_SMALL, anchor=tk.W,
            )
            bx = 130
            self._hp_canvas.create_rectangle(
                bx, y, bx + max_bar_w, y + bar_h,
                fill=BG_INPUT, outline="",
            )
            if bar_w > 0:
                self._hp_canvas.create_rectangle(
                    bx, y, bx + bar_w, y + bar_h,
                    fill=bar_color, outline="",
                )
            hp_text = "TOT" if not alive else f"{hp}/{hp_max}"
            self._hp_canvas.create_text(
                bx + max_bar_w + 8, y + bar_h // 2, text=hp_text,
                fill=FG_SECONDARY, font=FONT_SMALL, anchor=tk.W,
            )

            y += bar_h + spacing

        total_h = max(80, y + 4)
        self._hp_canvas.configure(height=total_h)

    # ── Event-Handler (No-Op fuer Live-Engine) ───────────────────────────────

    def handle_event(self, data: dict[str, Any]) -> None:
        """Kein Live-Engine-Bedarf — No-Op."""
        pass

    def on_engine_ready(self) -> None:
        """Kein Live-Engine-Bedarf — No-Op."""
        pass
