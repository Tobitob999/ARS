"""
gui/tab_map_viewer.py — Map Viewer Tab

Zeigt generierte Karten aus data/generated_maps/ und aus Adventure-JSONs
mit map-Feldern an. Dropdown-Auswahl, Zoom, Info-Panel.

Reine Viewer-Komponente — keine Spiellogik.
"""
from __future__ import annotations

import json
import logging
import os
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path
from typing import Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, PAD, PAD_SMALL,
)
from gui.pixel_renderer import (
    PixelTileset, render_terrain_image,
    TILE, SCALE, HAS_PIL,
)

if HAS_PIL:
    from PIL import Image, ImageDraw, ImageTk, ImageFont

logger = logging.getLogger("ARS.gui.map_viewer")

# ── Pfade ──────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATED_MAPS_DIR = os.path.join(_PROJECT_ROOT, "data", "generated_maps")
ADVENTURES_DIR = os.path.join(_PROJECT_ROOT, "modules", "adventures")

# ── Terrain-Symbole fuer Info ──────────────────────────────────────────────────

_TILE_LABELS = {
    "wall": "Wand",
    "floor": "Boden",
    "door": "Tuer",
    "obstacle": "Hindernis",
    "water": "Wasser",
}


# ===========================================================================
# MapViewerTab
# ===========================================================================

class MapViewerTab(ttk.Frame):
    """Tab zum Betrachten generierter Maps mit Auswahl und Zoom."""

    def __init__(self, parent: ttk.Notebook, gui: Any) -> None:
        super().__init__(parent)
        self.gui = gui

        self._tileset: PixelTileset | None = None
        self._maps: dict[str, dict] = {}          # key -> map data dict
        self._current_key: str = ""
        self._tk_image: ImageTk.PhotoImage | None = None
        self._canvas_img_id: int | None = None
        self._zoom: int = 2                        # 1x, 2x, 3x, 4x
        self._pan_offset: list[int] = [0, 0]
        self._drag_start: tuple[int, int] | None = None

        self._build_ui()
        self._load_tileset()
        self._scan_maps()

    # ── UI aufbauen ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # --- Toolbar ---
        toolbar = tk.Frame(self, bg=BG_PANEL)
        toolbar.pack(fill=tk.X, padx=PAD, pady=(PAD, 0))

        tk.Label(toolbar, text="Karte:", bg=BG_PANEL, fg=FG_PRIMARY,
                 font=FONT_BOLD).pack(side=tk.LEFT, padx=(4, 2))

        self._map_var = tk.StringVar()
        self._combo = ttk.Combobox(
            toolbar, textvariable=self._map_var,
            state="readonly", width=40, font=FONT_NORMAL,
        )
        self._combo.pack(side=tk.LEFT, padx=4, pady=4)
        self._combo.bind("<<ComboboxSelected>>", self._on_map_selected)

        ttk.Button(toolbar, text="Neu laden",
                   command=self._scan_maps).pack(side=tk.LEFT, padx=4)

        # Zoom
        tk.Label(toolbar, text="Zoom:", bg=BG_PANEL, fg=FG_MUTED,
                 font=FONT_SMALL).pack(side=tk.LEFT, padx=(16, 2))

        self._zoom_var = tk.StringVar(value="2x")
        zoom_combo = ttk.Combobox(
            toolbar, textvariable=self._zoom_var,
            values=["1x", "2x", "3x", "4x"],
            state="readonly", width=4, font=FONT_SMALL,
        )
        zoom_combo.pack(side=tk.LEFT, padx=2, pady=4)
        zoom_combo.bind("<<ComboboxSelected>>", self._on_zoom_changed)

        # Adventure-Filter
        tk.Label(toolbar, text="Adventure:", bg=BG_PANEL, fg=FG_MUTED,
                 font=FONT_SMALL).pack(side=tk.LEFT, padx=(16, 2))

        self._adv_var = tk.StringVar(value="(Alle)")
        self._adv_combo = ttk.Combobox(
            toolbar, textvariable=self._adv_var,
            state="readonly", width=20, font=FONT_SMALL,
        )
        self._adv_combo.pack(side=tk.LEFT, padx=4, pady=4)
        self._adv_combo.bind("<<ComboboxSelected>>", self._on_adventure_filter)

        # --- Hauptbereich: Canvas + Info-Panel ---
        main = tk.Frame(self, bg=BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        # Canvas
        self._canvas = tk.Canvas(main, bg="#050308", highlightthickness=0,
                                 cursor="crosshair")
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._canvas.bind("<Configure>", self._on_configure)
        self._canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag_motion)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Motion>", self._on_mouse_move)

        # Info-Panel rechts
        info_frame = tk.Frame(main, bg=BG_PANEL, width=220)
        info_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(PAD_SMALL, 0))
        info_frame.pack_propagate(False)

        tk.Label(info_frame, text="  MAP INFO  ", bg=BG_DARK, fg=FG_ACCENT,
                 font=FONT_BOLD).pack(fill=tk.X, padx=2, pady=(4, 2))

        self._info_text = tk.Text(
            info_frame, bg=BG_PANEL, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, bd=0,
            highlightthickness=0, padx=6, pady=4,
        )
        self._info_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        self._info_text.tag_configure("head", foreground=FG_ACCENT, font=FONT_BOLD)
        self._info_text.tag_configure("key", foreground=FG_SECONDARY)
        self._info_text.tag_configure("val", foreground=FG_PRIMARY)
        self._info_text.tag_configure("exit", foreground=GREEN)
        self._info_text.tag_configure("spawn", foreground=ORANGE)
        self._info_text.tag_configure("deco", foreground=YELLOW)

        # Status-Leiste
        self._status_var = tk.StringVar(value="Keine Karten geladen")
        tk.Label(self, textvariable=self._status_var, bg=BG_DARK, fg=FG_MUTED,
                 font=FONT_SMALL, anchor=tk.W).pack(fill=tk.X, padx=PAD, pady=(0, 2))

        # Hover-Info
        self._hover_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self._hover_var, bg=BG_DARK, fg=FG_SECONDARY,
                 font=FONT_SMALL, anchor=tk.W).pack(fill=tk.X, padx=PAD, pady=(0, PAD_SMALL))

    # ── Tileset ────────────────────────────────────────────────────────────

    def _load_tileset(self) -> None:
        if not HAS_PIL:
            return
        self._tileset = PixelTileset()
        self._tileset.load()

    # ── Maps scannen ───────────────────────────────────────────────────────

    def _scan_maps(self) -> None:
        """Scannt generated_maps/ und adventures/ nach Maps."""
        self._maps.clear()
        adventures_found: set[str] = set()

        # 1. data/generated_maps/*.json
        if os.path.isdir(GENERATED_MAPS_DIR):
            for fn in sorted(os.listdir(GENERATED_MAPS_DIR)):
                if not fn.endswith(".json"):
                    continue
                path = os.path.join(GENERATED_MAPS_DIR, fn)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if "terrain" in data:
                        room_id = data.get("room_id", fn.replace(".json", ""))
                        key = f"[generated] {room_id}"
                        data["_source"] = "generated"
                        data["_source_file"] = fn
                        self._maps[key] = data
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Map-JSON Fehler: %s: %s", fn, e)

        # 2. Adventures mit map-Feldern
        if os.path.isdir(ADVENTURES_DIR):
            for fn in sorted(os.listdir(ADVENTURES_DIR)):
                if not fn.endswith(".json"):
                    continue
                path = os.path.join(ADVENTURES_DIR, fn)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        adv = json.load(f)
                    title = adv.get("title", fn.replace(".json", ""))
                    adv_stem = fn.replace(".json", "")
                    for loc in adv.get("locations", []):
                        if "map" in loc and loc["map"]:
                            m = loc["map"]
                            room_id = loc["id"]
                            key = f"[{adv_stem}] {loc.get('name', room_id)}"
                            data = {
                                "room_id": room_id,
                                "terrain": m.get("terrain", []),
                                "exits": m.get("exits", {}),
                                "decorations": m.get("decorations", []),
                                "spawns": m.get("spawns", {}),
                                "biome": m.get("biome", "dungeon"),
                                "quality_score": m.get("quality_score", 0),
                                "_source": "adventure",
                                "_source_file": fn,
                                "_adventure_title": title,
                                "_location_name": loc.get("name", room_id),
                                "_description": loc.get("description", ""),
                                "_atmosphere": loc.get("atmosphere", ""),
                            }
                            self._maps[key] = data
                            adventures_found.add(adv_stem)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Adventure-JSON Fehler: %s: %s", fn, e)

        # Combobox aktualisieren
        keys = list(self._maps.keys())
        self._combo["values"] = keys

        # Adventure-Filter
        advs = ["(Alle)"] + sorted(adventures_found) + (["generated"] if any(
            d.get("_source") == "generated" for d in self._maps.values()) else [])
        self._adv_combo["values"] = advs

        if keys:
            self._combo.current(0)
            self._status_var.set(f"{len(keys)} Karten gefunden")
            self._on_map_selected(None)
        else:
            self._status_var.set("Keine Karten gefunden")
            self._clear_display()

        logger.info("MapViewer: %d Karten gescannt", len(self._maps))

    # ── Filter ─────────────────────────────────────────────────────────────

    def _on_adventure_filter(self, _event: Any) -> None:
        selected = self._adv_var.get()
        if selected == "(Alle)":
            keys = list(self._maps.keys())
        else:
            keys = [k for k, v in self._maps.items()
                    if v.get("_source_file", "").startswith(selected)
                    or (selected == "generated" and v.get("_source") == "generated")]

        self._combo["values"] = keys
        if keys:
            self._combo.current(0)
            self._on_map_selected(None)
        self._status_var.set(f"{len(keys)} Karten ({selected})")

    # ── Map ausgewaehlt ────────────────────────────────────────────────────

    def _on_map_selected(self, _event: Any) -> None:
        key = self._map_var.get()
        if key not in self._maps:
            return
        self._current_key = key
        self._pan_offset = [0, 0]
        self._render_current_map()
        self._update_info_panel()

    def _on_zoom_changed(self, _event: Any) -> None:
        z = self._zoom_var.get().replace("x", "")
        try:
            self._zoom = int(z)
        except ValueError:
            self._zoom = 2
        self._render_current_map()

    def _on_configure(self, _event: Any) -> None:
        if self._current_key:
            self._render_current_map()

    # ── Rendering ──────────────────────────────────────────────────────────

    def _render_current_map(self) -> None:
        if not HAS_PIL or not self._tileset:
            return
        if self._current_key not in self._maps:
            return

        data = self._maps[self._current_key]
        terrain = data.get("terrain", [])
        if not terrain:
            return

        room_id = data.get("room_id", "")

        # Basis-Bild via pixel_renderer
        base_img = render_terrain_image(terrain, self._tileset, room_id)
        if base_img is None:
            return

        h = len(terrain)
        w = len(terrain[0]) if terrain else 0

        # Exits, Spawns, Decorations als Overlay zeichnen
        overlay = base_img.copy()
        draw = ImageDraw.Draw(overlay)

        # Exit-Markierungen (gruen)
        for exit_id, pos in data.get("exits", {}).items():
            if isinstance(pos, list) and len(pos) == 2:
                ex, ey = pos[0], pos[1]
                px, py = ex * TILE, ey * TILE
                # Gruener Rahmen um Exit-Tile
                draw.rectangle([px, py, px + TILE - 1, py + TILE - 1],
                               outline=(0, 200, 80, 200), width=1)
                # Kleiner Label
                draw.text((px + 1, py + 1), "E", fill=(0, 255, 100, 255))

        # Spawn-Markierungen (orange)
        for npc_id, pos in data.get("spawns", {}).items():
            if isinstance(pos, list) and len(pos) == 2:
                sx, sy = pos[0], pos[1]
                px, py = sx * TILE, sy * TILE
                # Orangener Marker
                cx, cy = px + TILE // 2, py + TILE // 2
                r = TILE // 3
                draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                             outline=(255, 160, 0, 220), width=1)
                draw.text((px + 1, py + 1), "S", fill=(255, 180, 0, 255))

        # Skalierung
        zoom = self._zoom
        new_w = overlay.width * zoom
        new_h = overlay.height * zoom
        big = overlay.resize((new_w, new_h), Image.NEAREST)

        # Pan-Offset anwenden (zentriert + Verschiebung)
        canvas_w = self._canvas.winfo_width()
        canvas_h = self._canvas.winfo_height()
        if canvas_w < 2 or canvas_h < 2:
            return

        # Zentrieren wenn Bild kleiner als Canvas
        off_x = max(0, (canvas_w - new_w) // 2) + self._pan_offset[0]
        off_y = max(0, (canvas_h - new_h) // 2) + self._pan_offset[1]

        # ImageTk (Referenz halten!)
        self._tk_image = ImageTk.PhotoImage(big)

        if self._canvas_img_id is None:
            self._canvas_img_id = self._canvas.create_image(
                off_x, off_y, anchor=tk.NW, image=self._tk_image)
        else:
            self._canvas.coords(self._canvas_img_id, off_x, off_y)
            self._canvas.itemconfig(self._canvas_img_id, image=self._tk_image)

        # Interne Referenz fuer Hover
        self._render_offset = (off_x, off_y)
        self._render_size = (new_w, new_h)
        self._grid_size = (w, h)

    def _clear_display(self) -> None:
        if self._canvas_img_id is not None:
            self._canvas.delete(self._canvas_img_id)
            self._canvas_img_id = None
        self._tk_image = None

    # ── Info-Panel ─────────────────────────────────────────────────────────

    def _update_info_panel(self) -> None:
        if self._current_key not in self._maps:
            return

        data = self._maps[self._current_key]
        terrain = data.get("terrain", [])
        h = len(terrain)
        w = len(terrain[0]) if terrain else 0

        self._info_text.config(state=tk.NORMAL)
        self._info_text.delete("1.0", tk.END)

        # Titel
        room_id = data.get("room_id", "?")
        loc_name = data.get("_location_name", room_id)
        self._info_text.insert(tk.END, f"{loc_name}\n", "head")
        self._info_text.insert(tk.END, f"ID: {room_id}\n\n", "key")

        # Grid-Groesse
        self._info_text.insert(tk.END, "Grid: ", "key")
        self._info_text.insert(tk.END, f"{w} x {h}\n", "val")

        # Biome
        biome = data.get("biome", "?")
        self._info_text.insert(tk.END, "Biome: ", "key")
        self._info_text.insert(tk.END, f"{biome}\n", "val")

        # Quelle
        source = data.get("_source", "?")
        self._info_text.insert(tk.END, "Quelle: ", "key")
        self._info_text.insert(tk.END, f"{source}\n", "val")

        # Score
        score = data.get("quality_score", 0)
        if score:
            self._info_text.insert(tk.END, "Score: ", "key")
            self._info_text.insert(tk.END, f"{score:.2f}\n", "val")

        # Tile-Statistik
        counts: dict[str, int] = {}
        for row in terrain:
            for cell in row:
                counts[cell] = counts.get(cell, 0) + 1
        self._info_text.insert(tk.END, "\n--- Tiles ---\n", "head")
        for tile_type, count in sorted(counts.items(), key=lambda x: -x[1]):
            label = _TILE_LABELS.get(tile_type, tile_type)
            self._info_text.insert(tk.END, f"  {label}: ", "key")
            self._info_text.insert(tk.END, f"{count}\n", "val")

        # Exits
        exits = data.get("exits", {})
        if exits:
            self._info_text.insert(tk.END, "\n--- Exits ---\n", "head")
            for eid, pos in exits.items():
                self._info_text.insert(tk.END, f"  {eid}: ", "key")
                self._info_text.insert(tk.END, f"[{pos[0]}, {pos[1]}]\n", "exit")

        # Spawns
        spawns = data.get("spawns", {})
        if spawns:
            self._info_text.insert(tk.END, "\n--- Spawns ---\n", "head")
            for sid, pos in spawns.items():
                self._info_text.insert(tk.END, f"  {sid}: ", "key")
                self._info_text.insert(tk.END, f"[{pos[0]}, {pos[1]}]\n", "spawn")

        # Decorations
        decos = data.get("decorations", [])
        if decos:
            self._info_text.insert(tk.END, "\n--- Dekorationen ---\n", "head")
            for d in decos:
                dtype = d.get("type", "?")
                self._info_text.insert(tk.END, f"  {dtype}: ", "key")
                self._info_text.insert(tk.END, f"[{d.get('x', '?')}, {d.get('y', '?')}]\n", "deco")

        # Beschreibung
        desc = data.get("_description", "")
        if desc:
            self._info_text.insert(tk.END, "\n--- Beschreibung ---\n", "head")
            self._info_text.insert(tk.END, f"{desc}\n", "val")

        atmo = data.get("_atmosphere", "")
        if atmo:
            self._info_text.insert(tk.END, f"\n{atmo}\n", "key")

        self._info_text.config(state=tk.DISABLED)

    # ── Drag/Pan ───────────────────────────────────────────────────────────

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_start = (event.x, event.y)

    def _on_drag_motion(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        self._pan_offset[0] += dx
        self._pan_offset[1] += dy
        self._drag_start = (event.x, event.y)
        self._render_current_map()

    def _on_drag_end(self, _event: tk.Event) -> None:
        self._drag_start = None

    def _on_mousewheel(self, event: tk.Event) -> None:
        if event.delta > 0:
            self._zoom = min(4, self._zoom + 1)
        else:
            self._zoom = max(1, self._zoom - 1)
        self._zoom_var.set(f"{self._zoom}x")
        self._render_current_map()

    # ── Hover ──────────────────────────────────────────────────────────────

    def _on_mouse_move(self, event: tk.Event) -> None:
        if not hasattr(self, "_render_offset") or self._current_key not in self._maps:
            self._hover_var.set("")
            return

        ox, oy = self._render_offset
        mx, my = event.x - ox, event.y - oy
        rw, rh = self._render_size
        gw, gh = self._grid_size

        if mx < 0 or my < 0 or mx >= rw or my >= rh:
            self._hover_var.set("")
            return

        # Pixel -> Grid-Koordinate
        tile_px = TILE * self._zoom
        gx = mx // tile_px
        gy = my // tile_px

        if gx < 0 or gy < 0 or gx >= gw or gy >= gh:
            self._hover_var.set("")
            return

        data = self._maps[self._current_key]
        terrain = data.get("terrain", [])
        cell = terrain[gy][gx] if gy < len(terrain) and gx < len(terrain[gy]) else "?"
        label = _TILE_LABELS.get(cell, cell)

        # Check if exit/spawn at this position
        extras: list[str] = []
        for eid, pos in data.get("exits", {}).items():
            if isinstance(pos, list) and pos[0] == gx and pos[1] == gy:
                extras.append(f"Exit: {eid}")
        for sid, pos in data.get("spawns", {}).items():
            if isinstance(pos, list) and pos[0] == gx and pos[1] == gy:
                extras.append(f"Spawn: {sid}")

        info = f"[{gx}, {gy}] {label}"
        if extras:
            info += " | " + ", ".join(extras)
        self._hover_var.set(info)
