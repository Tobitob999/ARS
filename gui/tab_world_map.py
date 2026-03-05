"""
gui/tab_world_map.py — World Map Tab (Karte 2.0)

Ersetzt tab_map_viewer.py: Zeigt eine zusammenhaengende, scrollbare Weltkarte
die alle Raeume eines Abenteuers organisch verbindet.

Features:
  - Viewport-Crop aus vorgerenderten Static-Layer
  - Fog of War (3 Stufen, togglebar)
  - Minimap (untere rechte Ecke des Canvas)
  - 3 Kamera-Modi: Player / Group / Free
  - Zoom 1x-4x, Mausrad, Drag, WASD/Pfeiltasten
  - Hover: Tile-Info + Raum-Name in Status-Leiste
  - Klick auf Raum: Info-Panel zeigt Details
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
import tkinter.ttk as ttk
from typing import Any

from gui.styles import (
    BG_DARK, BG_PANEL, BG_INPUT,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, PAD, PAD_SMALL,
)
from gui.pixel_renderer import (
    PixelTileset, render_terrain_image,
    TILE, HAS_PIL,
)
from gui.world_stitcher import (
    WorldLayout, stitch_adventure, load_adventure, scan_adventures_with_maps,
)

if HAS_PIL:
    from PIL import Image, ImageDraw, ImageTk

logger = logging.getLogger("ARS.gui.world_map")

# ── Konstanten ────────────────────────────────────────────────────────────────

MINIMAP_MAX_W = 160
MINIMAP_MAX_H = 120
MINIMAP_PAD = 8

FOG_ALPHA_HIDDEN = 230
FOG_ALPHA_VOID = 255

_TILE_LABELS = {
    "wall": "Wand",
    "floor": "Boden",
    "door": "Tuer",
    "obstacle": "Hindernis",
    "water": "Wasser",
    "void": "Void",
}

# Farben fuer Minimap
_MM_FLOOR = (180, 170, 150)
_MM_WALL = (50, 45, 55)
_MM_VOID = (5, 3, 8)
_MM_WATER = (40, 80, 130)
_MM_DOOR = (160, 140, 80)
_MM_SPAWN = (255, 160, 0)
_MM_VP_COLOR = (255, 255, 255)


# ===========================================================================
# WorldMapTab
# ===========================================================================

class WorldMapTab(ttk.Frame):
    """Tab fuer die zusammenhaengende Weltkarte eines Abenteuers."""

    def __init__(self, parent: ttk.Notebook, gui: Any) -> None:
        super().__init__(parent)
        self.gui = gui

        # State
        self._layout: WorldLayout | None = None
        self._world_static: "Image.Image | None" = None
        self._minimap_img: "Image.Image | None" = None
        self._discovered_rooms: set[str] = set()
        self._camera_mode: str = "free"       # "player" | "party" | "free"
        self._cam_x: int = 0                  # Viewport links-oben in Tiles
        self._cam_y: int = 0
        self._vp_tiles_x: int = 30            # Viewport-Groesse
        self._vp_tiles_y: int = 20
        self._zoom: int = 2                   # 1-4
        self._selected_room: str | None = None
        self._fog_enabled: bool = False
        self._drag_start: tuple[int, int] | None = None
        self._tk_image: "ImageTk.PhotoImage | None" = None
        self._canvas_img_id: int | None = None
        self._tk_minimap: "ImageTk.PhotoImage | None" = None
        self._minimap_canvas_id: int | None = None
        self._render_scheduled: bool = False
        self._adventures: list[tuple[str, str, str]] = []  # (fn, title, stem)

        # Tileset
        self._tileset: PixelTileset | None = None

        self._build_ui()
        self._load_tileset()
        self._scan_adventures()

    # ── UI aufbauen ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # --- Toolbar ---
        toolbar = tk.Frame(self, bg=BG_PANEL)
        toolbar.pack(fill=tk.X, padx=PAD, pady=(PAD, 0))

        tk.Label(toolbar, text="Adventure:", bg=BG_PANEL, fg=FG_PRIMARY,
                 font=FONT_BOLD).pack(side=tk.LEFT, padx=(4, 2))

        self._adv_var = tk.StringVar()
        self._adv_combo = ttk.Combobox(
            toolbar, textvariable=self._adv_var,
            state="readonly", width=30, font=FONT_NORMAL,
        )
        self._adv_combo.pack(side=tk.LEFT, padx=4, pady=4)
        self._adv_combo.bind("<<ComboboxSelected>>", self._on_adventure_selected)

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

        # Kamera-Modi
        tk.Label(toolbar, text="Kamera:", bg=BG_PANEL, fg=FG_MUTED,
                 font=FONT_SMALL).pack(side=tk.LEFT, padx=(16, 2))

        self._cam_var = tk.StringVar(value="F")
        for label, mode in [("P", "player"), ("G", "party"), ("F", "free")]:
            rb = tk.Radiobutton(
                toolbar, text=label, variable=self._cam_var, value=label,
                bg=BG_PANEL, fg=FG_PRIMARY, selectcolor=BG_INPUT,
                activebackground=BG_PANEL, activeforeground=FG_ACCENT,
                font=FONT_BOLD, indicatoron=0, width=3, relief=tk.FLAT,
                command=lambda m=mode, v=label: self._set_camera_mode(m),
            )
            rb.pack(side=tk.LEFT, padx=1, pady=4)

        # Fog Toggle
        self._fog_var = tk.BooleanVar(value=False)
        fog_cb = ttk.Checkbutton(
            toolbar, text="Fog", variable=self._fog_var,
            command=self._on_fog_toggled,
        )
        fog_cb.pack(side=tk.LEFT, padx=(16, 4), pady=4)

        # Reload
        ttk.Button(toolbar, text="Neu laden",
                   command=self._reload).pack(side=tk.LEFT, padx=4)

        # Discover-All (fuer Fog-Modus)
        ttk.Button(toolbar, text="Alle aufdecken",
                   command=self._discover_all).pack(side=tk.LEFT, padx=4)

        # --- Hauptbereich: Canvas + Info-Panel ---
        main = tk.Frame(self, bg=BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        # Canvas
        self._canvas = tk.Canvas(main, bg="#050308", highlightthickness=0,
                                 cursor="crosshair")
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._canvas.bind("<Configure>", self._on_configure)
        self._canvas.bind("<ButtonPress-1>", self._on_click)
        self._canvas.bind("<B1-Motion>", self._on_drag_motion)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Motion>", self._on_mouse_move)
        # Keyboard (Canvas muss Fokus haben)
        self._canvas.bind("<Key>", self._on_key)
        self._canvas.bind("<FocusIn>", lambda e: None)

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
        status_frame = tk.Frame(self, bg=BG_DARK)
        status_frame.pack(fill=tk.X, padx=PAD, pady=(0, PAD_SMALL))

        self._status_var = tk.StringVar(value="Kein Adventure geladen")
        tk.Label(status_frame, textvariable=self._status_var, bg=BG_DARK,
                 fg=FG_MUTED, font=FONT_SMALL, anchor=tk.W).pack(
            side=tk.LEFT, fill=tk.X, expand=True)

        self._hover_var = tk.StringVar(value="")
        tk.Label(status_frame, textvariable=self._hover_var, bg=BG_DARK,
                 fg=FG_SECONDARY, font=FONT_SMALL, anchor=tk.E).pack(
            side=tk.RIGHT)

    # ── Tileset / Adventures ────────────────────────────────────────────────

    def _load_tileset(self) -> None:
        if not HAS_PIL:
            return
        self._tileset = PixelTileset()
        self._tileset.load()

    def _scan_adventures(self) -> None:
        self._adventures = scan_adventures_with_maps()
        names = [f"{title} ({stem})" for _, title, stem in self._adventures]
        self._adv_combo["values"] = names
        if names:
            self._adv_combo.current(0)
            self._status_var.set(f"{len(names)} Adventures mit Karten")
            self._on_adventure_selected(None)
        else:
            self._status_var.set("Keine Adventures mit Karten gefunden")

    def _on_adventure_selected(self, _event: Any) -> None:
        idx = self._adv_combo.current()
        if idx < 0 or idx >= len(self._adventures):
            return
        fn, title, stem = self._adventures[idx]
        self._load_adventure(fn)

    def _reload(self) -> None:
        self._scan_adventures()

    # ── Adventure laden ─────────────────────────────────────────────────────

    def _load_adventure(self, filename: str) -> None:
        if not HAS_PIL or not self._tileset:
            return

        adv = load_adventure(filename)
        if adv is None:
            self._status_var.set(f"Fehler beim Laden: {filename}")
            return

        layout = stitch_adventure(adv)
        if layout is None:
            self._status_var.set("Keine map-Daten im Adventure")
            return

        self._layout = layout
        self._selected_room = None

        # Alle Raeume discovern (Default: kein Fog)
        self._discovered_rooms = set(layout.room_bounds.keys())

        # Statisches World-Image rendern (mit Biome + Tile-to-Room fuer Cave-Tiles)
        self._world_static = render_terrain_image(
            layout.terrain, self._tileset, "world_static",
            biome="cave",
            tile_to_room=layout.tile_to_room,
            decorations=layout.decorations,
        )

        if self._world_static is None:
            self._status_var.set("Render-Fehler")
            return

        # Void-Tiles schwarz malen (render_terrain_image setzt sie als dunklen BG)
        # Das ist bereits der Fall durch den (5,3,8) Hintergrund

        # Spawn-Marker und Exit-Marker auf das statische Bild zeichnen
        self._draw_markers_on_static()

        # Minimap generieren
        self._build_minimap()

        # Kamera auf Start-Location zentrieren
        if layout.start_location in layout.room_bounds:
            bx, by, bw, bh = layout.room_bounds[layout.start_location]
            self._cam_x = bx + bw // 2 - self._vp_tiles_x // 2
            self._cam_y = by + bh // 2 - self._vp_tiles_y // 2
        else:
            self._cam_x = 0
            self._cam_y = 0

        n_rooms = len(layout.room_bounds)
        self._status_var.set(
            f"{n_rooms} Raeume, {layout.width}x{layout.height} Tiles"
        )

        # Info-Panel: Uebersicht
        self._update_overview_info()

        self._schedule_render()

    def _draw_markers_on_static(self) -> None:
        """Zeichnet Spawn- und Exit-Marker auf das statische Bild."""
        if self._world_static is None or self._layout is None:
            return

        draw = ImageDraw.Draw(self._world_static)
        layout = self._layout

        # Exit-Markierungen (gruen) - nur fuer Exits die zwischen Raeumen liegen
        for rid, loc_data in layout.locations.items():
            rmap = loc_data.get("map", {})
            if rid not in layout.room_bounds:
                continue
            bx, by, _, _ = layout.room_bounds[rid]
            for eid, epos in rmap.get("exits", {}).items():
                if isinstance(epos, list) and len(epos) == 2:
                    px = (bx + epos[0]) * TILE
                    py = (by + epos[1]) * TILE
                    draw.rectangle(
                        [px, py, px + TILE - 1, py + TILE - 1],
                        outline=(0, 200, 80, 200), width=1,
                    )

        # Spawn-Markierungen (orange Kreise)
        for npc_id, (sx, sy) in layout.spawns.items():
            px = sx * TILE + TILE // 2
            py = sy * TILE + TILE // 2
            r = TILE // 3
            draw.ellipse(
                [px - r, py - r, px + r, py + r],
                outline=(255, 160, 0, 220), width=2,
            )

    # ── Minimap ─────────────────────────────────────────────────────────────

    def _build_minimap(self) -> None:
        """Generiert Minimap: 1px pro Tile, skaliert auf max 160x120."""
        if not HAS_PIL or self._layout is None:
            return

        layout = self._layout
        w, h = layout.width, layout.height

        mm = Image.new("RGB", (w, h), _MM_VOID)
        px = mm.load()

        for y in range(h):
            for x in range(w):
                cell = layout.terrain[y][x]
                if cell == "void":
                    continue
                elif cell == "wall":
                    px[x, y] = _MM_WALL
                elif cell == "water":
                    px[x, y] = _MM_WATER
                elif cell == "door":
                    px[x, y] = _MM_DOOR
                else:
                    px[x, y] = _MM_FLOOR

        # Spawns einzeichnen
        for _, (sx, sy) in layout.spawns.items():
            if 0 <= sx < w and 0 <= sy < h:
                px[sx, sy] = _MM_SPAWN

        # Skalieren (Aspect-Ratio beibehalten)
        scale = min(MINIMAP_MAX_W / w, MINIMAP_MAX_H / h, 1.0)
        if scale < 1.0:
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            mm = mm.resize((new_w, new_h), Image.NEAREST)

        self._minimap_img = mm

    # ── Rendering ───────────────────────────────────────────────────────────

    def _schedule_render(self) -> None:
        """Plant ein Render im naechsten after()-Zyklus."""
        if not self._render_scheduled:
            self._render_scheduled = True
            self.after(16, self._render_frame)

    def _render_frame(self) -> None:
        """Rendert einen Frame: Viewport-Crop, Fog, Minimap."""
        self._render_scheduled = False

        if not HAS_PIL or self._world_static is None or self._layout is None:
            return

        layout = self._layout
        zoom = self._zoom

        # Canvas-Groesse
        canvas_w = self._canvas.winfo_width()
        canvas_h = self._canvas.winfo_height()
        if canvas_w < 2 or canvas_h < 2:
            return

        # Viewport in Tiles
        tile_display = TILE * zoom
        self._vp_tiles_x = max(1, canvas_w // tile_display + 2)
        self._vp_tiles_y = max(1, canvas_h // tile_display + 2)

        # Kamera-Position je nach Modus
        if self._camera_mode == "player" and layout.start_location in layout.room_bounds:
            bx, by, bw, bh = layout.room_bounds[layout.start_location]
            self._cam_x = bx + bw // 2 - self._vp_tiles_x // 2
            self._cam_y = by + bh // 2 - self._vp_tiles_y // 2
        elif self._camera_mode == "party" and layout.spawns:
            cx = sum(s[0] for s in layout.spawns.values()) // len(layout.spawns)
            cy = sum(s[1] for s in layout.spawns.values()) // len(layout.spawns)
            self._cam_x = cx - self._vp_tiles_x // 2
            self._cam_y = cy - self._vp_tiles_y // 2
        # "free" mode: cam_x/cam_y managed by input handlers

        # Clamp
        self._cam_x = max(0, min(self._cam_x, layout.width - self._vp_tiles_x))
        self._cam_y = max(0, min(self._cam_y, layout.height - self._vp_tiles_y))

        # Viewport-Crop aus Static-Image (Pixel-Coords)
        crop_x1 = self._cam_x * TILE
        crop_y1 = self._cam_y * TILE
        crop_x2 = crop_x1 + self._vp_tiles_x * TILE
        crop_y2 = crop_y1 + self._vp_tiles_y * TILE

        # Clamp crop to image bounds
        img_w, img_h = self._world_static.size
        crop_x2 = min(crop_x2, img_w)
        crop_y2 = min(crop_y2, img_h)
        crop_x1 = max(0, crop_x1)
        crop_y1 = max(0, crop_y1)

        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            return

        viewport = self._world_static.crop((crop_x1, crop_y1, crop_x2, crop_y2)).copy()

        # Raum-Labels zeichnen
        self._draw_room_labels(viewport, crop_x1, crop_y1, crop_x2, crop_y2)

        # Fog of War
        if self._fog_enabled:
            self._apply_fog(viewport, crop_x1, crop_y1)

        # Zoom
        vp_w = viewport.width * zoom
        vp_h = viewport.height * zoom
        display = viewport.resize((vp_w, vp_h), Image.NEAREST)

        # Minimap compositen
        if self._minimap_img is not None:
            display = self._composite_minimap(display, canvas_w, canvas_h)

        # -> Canvas
        self._tk_image = ImageTk.PhotoImage(display)

        if self._canvas_img_id is None:
            self._canvas_img_id = self._canvas.create_image(
                0, 0, anchor=tk.NW, image=self._tk_image)
        else:
            self._canvas.coords(self._canvas_img_id, 0, 0)
            self._canvas.itemconfig(self._canvas_img_id, image=self._tk_image)

        # Canvas-Fokus fuer Keyboard
        self._canvas.focus_set()

    def _draw_room_labels(
        self, viewport: "Image.Image",
        crop_x1: int, crop_y1: int, crop_x2: int, crop_y2: int,
    ) -> None:
        """Zeichnet halbtransparente Raum-Labels auf den Viewport."""
        if self._layout is None:
            return

        draw = ImageDraw.Draw(viewport)

        for rid, (bx, by, bw, bh) in self._layout.room_bounds.items():
            # Raum-Mitte in Pixel
            center_px = (bx + bw // 2) * TILE
            center_py = (by + bh // 2) * TILE

            # Nur rendern wenn im Viewport
            if center_px < crop_x1 or center_px > crop_x2:
                continue
            if center_py < crop_y1 or center_py > crop_y2:
                continue

            # Fog-Check
            if self._fog_enabled and rid not in self._discovered_rooms:
                continue

            # Viewport-lokale Koordinaten
            lx = center_px - crop_x1
            ly = center_py - crop_y1

            # Label-Text
            loc = self._layout.locations.get(rid, {})
            label = loc.get("name", rid)

            # Halbtransparenter Hintergrund + Text
            # Schriftgroesse schaetzen
            text_w = len(label) * 6
            text_h = 10
            bg_x1 = lx - text_w // 2 - 2
            bg_y1 = ly - text_h // 2 - 1
            bg_x2 = lx + text_w // 2 + 2
            bg_y2 = ly + text_h // 2 + 1

            # Overlay fuer Halbtransparenz
            overlay = Image.new("RGBA", viewport.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            od.rectangle([bg_x1, bg_y1, bg_x2, bg_y2], fill=(0, 0, 0, 140))
            od.text((lx - text_w // 2, ly - text_h // 2), label,
                    fill=(240, 230, 200, 220))
            viewport.paste(Image.alpha_composite(
                viewport.convert("RGBA"), overlay), (0, 0))

    def _apply_fog(
        self, viewport: "Image.Image", crop_x1: int, crop_y1: int,
    ) -> None:
        """Wendet Fog of War auf den Viewport an."""
        if self._layout is None:
            return

        layout = self._layout
        fog = Image.new("RGBA", viewport.size, (0, 0, 0, 0))
        fog_px = fog.load()

        vw, vh = viewport.size

        for py in range(vh):
            for px in range(vw):
                # Welches Tile?
                wx = (crop_x1 + px) // TILE
                wy = (crop_y1 + py) // TILE

                if wx < 0 or wy < 0 or wx >= layout.width or wy >= layout.height:
                    fog_px[px, py] = (0, 0, 0, FOG_ALPHA_VOID)
                    continue

                cell = layout.terrain[wy][wx]
                if cell == "void":
                    fog_px[px, py] = (0, 0, 0, FOG_ALPHA_VOID)
                    continue

                room = layout.tile_to_room[wy][wx]
                if room and room != "_passage" and room not in self._discovered_rooms:
                    fog_px[px, py] = (0, 0, 0, FOG_ALPHA_HIDDEN)
                elif room == "_passage":
                    # Passage sichtbar wenn mindestens ein angrenzender Raum entdeckt
                    adjacent_discovered = False
                    for dy in range(-2, 3):
                        for dx in range(-2, 3):
                            ny, nx = wy + dy, wx + dx
                            if 0 <= ny < layout.height and 0 <= nx < layout.width:
                                r = layout.tile_to_room[ny][nx]
                                if r and r != "_passage" and r in self._discovered_rooms:
                                    adjacent_discovered = True
                                    break
                        if adjacent_discovered:
                            break
                    if not adjacent_discovered:
                        fog_px[px, py] = (0, 0, 0, FOG_ALPHA_HIDDEN)

        viewport_rgba = viewport.convert("RGBA")
        result = Image.alpha_composite(viewport_rgba, fog)
        viewport.paste(result)

    def _composite_minimap(
        self, display: "Image.Image", canvas_w: int, canvas_h: int,
    ) -> "Image.Image":
        """Composited die Minimap mit Viewport-Rechteck in die untere rechte Ecke."""
        if self._minimap_img is None or self._layout is None:
            return display

        layout = self._layout
        mm = self._minimap_img.copy()
        mm_w, mm_h = mm.size

        # Viewport-Rechteck auf Minimap zeichnen
        draw = ImageDraw.Draw(mm)
        # Skalierung: Minimap-Pixel pro World-Tile
        sx = mm_w / layout.width
        sy = mm_h / layout.height

        vp_x1 = int(self._cam_x * sx)
        vp_y1 = int(self._cam_y * sy)
        vp_x2 = int((self._cam_x + self._vp_tiles_x) * sx)
        vp_y2 = int((self._cam_y + self._vp_tiles_y) * sy)
        vp_x2 = min(vp_x2, mm_w - 1)
        vp_y2 = min(vp_y2, mm_h - 1)
        draw.rectangle([vp_x1, vp_y1, vp_x2, vp_y2],
                       outline=_MM_VP_COLOR, width=1)

        # Auf display compositen
        result = display.copy().convert("RGBA")
        mm_rgba = mm.convert("RGBA")

        # Halbtransparenter Hintergrund
        bg = Image.new("RGBA", (mm_w + 4, mm_h + 4), (0, 0, 0, 160))
        paste_x = result.width - mm_w - MINIMAP_PAD - 4
        paste_y = result.height - mm_h - MINIMAP_PAD - 4
        paste_x = max(0, paste_x)
        paste_y = max(0, paste_y)

        result.paste(bg, (paste_x, paste_y), bg)
        result.paste(mm_rgba, (paste_x + 2, paste_y + 2), mm_rgba)

        return result

    # ── Info-Panel ──────────────────────────────────────────────────────────

    def _update_overview_info(self) -> None:
        """Zeigt Uebersichts-Info (kein Raum ausgewaehlt)."""
        if self._layout is None:
            return

        layout = self._layout
        self._info_text.config(state=tk.NORMAL)
        self._info_text.delete("1.0", tk.END)

        self._info_text.insert(tk.END, "World Map\n", "head")
        self._info_text.insert(tk.END, f"Grid: ", "key")
        self._info_text.insert(tk.END, f"{layout.width} x {layout.height}\n", "val")
        self._info_text.insert(tk.END, f"Raeume: ", "key")
        self._info_text.insert(tk.END, f"{len(layout.room_bounds)}\n\n", "val")

        # Raum-Liste
        self._info_text.insert(tk.END, "--- Raeume ---\n", "head")
        for rid, (bx, by, bw, bh) in layout.room_bounds.items():
            loc = layout.locations.get(rid, {})
            name = loc.get("name", rid)
            biome = layout.room_biome.get(rid, "?")
            self._info_text.insert(tk.END, f"  {name}\n", "val")
            self._info_text.insert(tk.END, f"    {bw}x{bh}, {biome}\n", "key")

        # Spawns
        if layout.spawns:
            self._info_text.insert(tk.END, "\n--- Spawns ---\n", "head")
            for sid, (sx, sy) in layout.spawns.items():
                self._info_text.insert(tk.END, f"  {sid}: ", "key")
                self._info_text.insert(tk.END, f"[{sx}, {sy}]\n", "spawn")

        self._info_text.config(state=tk.DISABLED)

    def _update_room_info(self, room_id: str) -> None:
        """Zeigt Details fuer einen ausgewaehlten Raum."""
        if self._layout is None or room_id not in self._layout.room_bounds:
            return

        layout = self._layout
        loc = layout.locations.get(room_id, {})
        bx, by, bw, bh = layout.room_bounds[room_id]

        self._info_text.config(state=tk.NORMAL)
        self._info_text.delete("1.0", tk.END)

        name = loc.get("name", room_id)
        self._info_text.insert(tk.END, f"{name}\n", "head")
        self._info_text.insert(tk.END, f"ID: {room_id}\n\n", "key")

        self._info_text.insert(tk.END, "Grid: ", "key")
        self._info_text.insert(tk.END, f"{bw} x {bh}\n", "val")

        biome = layout.room_biome.get(room_id, "?")
        self._info_text.insert(tk.END, "Biome: ", "key")
        self._info_text.insert(tk.END, f"{biome}\n", "val")

        self._info_text.insert(tk.END, "Position: ", "key")
        self._info_text.insert(tk.END, f"({bx}, {by})\n", "val")

        # Exits
        rmap = loc.get("map", {})
        exits = rmap.get("exits", {})
        if exits:
            self._info_text.insert(tk.END, "\n--- Exits ---\n", "head")
            for eid, pos in exits.items():
                target_name = eid
                if eid in layout.locations:
                    target_name = layout.locations[eid].get("name", eid)
                self._info_text.insert(tk.END, f"  -> {target_name}\n", "exit")

        # Spawns in diesem Raum
        room_spawns = {k: v for k, v in layout.spawns.items()
                       if bx <= v[0] < bx + bw and by <= v[1] < by + bh}
        if room_spawns:
            self._info_text.insert(tk.END, "\n--- Spawns ---\n", "head")
            for sid, (sx, sy) in room_spawns.items():
                self._info_text.insert(tk.END, f"  {sid}: ", "key")
                self._info_text.insert(tk.END, f"[{sx}, {sy}]\n", "spawn")

        # Beschreibung
        desc = loc.get("description", "")
        if desc:
            self._info_text.insert(tk.END, "\n--- Beschreibung ---\n", "head")
            self._info_text.insert(tk.END, f"{desc}\n", "val")

        atmo = loc.get("atmosphere", "")
        if atmo:
            self._info_text.insert(tk.END, f"\n{atmo}\n", "key")

        # Tile-Statistik fuer diesen Raum
        counts: dict[str, int] = {}
        for ry in range(by, by + bh):
            for rx in range(bx, bx + bw):
                if 0 <= ry < layout.height and 0 <= rx < layout.width:
                    cell = layout.terrain[ry][rx]
                    counts[cell] = counts.get(cell, 0) + 1
        if counts:
            self._info_text.insert(tk.END, "\n--- Tiles ---\n", "head")
            for tt, cnt in sorted(counts.items(), key=lambda x: -x[1]):
                label = _TILE_LABELS.get(tt, tt)
                self._info_text.insert(tk.END, f"  {label}: ", "key")
                self._info_text.insert(tk.END, f"{cnt}\n", "val")

        self._info_text.config(state=tk.DISABLED)

    # ── Input Handlers ──────────────────────────────────────────────────────

    def _on_configure(self, _event: Any) -> None:
        self._schedule_render()

    def _on_zoom_changed(self, _event: Any) -> None:
        z = self._zoom_var.get().replace("x", "")
        try:
            self._zoom = int(z)
        except ValueError:
            self._zoom = 2
        self._schedule_render()

    def _set_camera_mode(self, mode: str) -> None:
        self._camera_mode = mode
        self._schedule_render()

    def _on_fog_toggled(self) -> None:
        self._fog_enabled = self._fog_var.get()
        if self._fog_enabled:
            # Im Fog-Modus: nur Start-Raum sichtbar
            if self._layout and self._layout.start_location:
                self._discovered_rooms = {self._layout.start_location}
            else:
                self._discovered_rooms = set()
        else:
            # Fog aus: alle Raeume sichtbar
            if self._layout:
                self._discovered_rooms = set(self._layout.room_bounds.keys())
        self._schedule_render()

    def _discover_all(self) -> None:
        if self._layout:
            self._discovered_rooms = set(self._layout.room_bounds.keys())
            self._schedule_render()

    def _on_click(self, event: tk.Event) -> None:
        self._drag_start = (event.x, event.y)

        if self._layout is None:
            return

        # Minimap-Klick?
        if self._minimap_img and self._check_minimap_click(event.x, event.y):
            return

        # Tile bestimmen
        tile_display = TILE * self._zoom
        tx = self._cam_x + event.x // tile_display
        ty = self._cam_y + event.y // tile_display

        if 0 <= tx < self._layout.width and 0 <= ty < self._layout.height:
            room = self._layout.tile_to_room[ty][tx]
            if room and room != "_passage":
                self._selected_room = room
                self._update_room_info(room)
                # Im Fog-Modus: Raum aufdecken bei Klick
                if self._fog_enabled:
                    self._discovered_rooms.add(room)
                    self._schedule_render()
            else:
                self._selected_room = None
                self._update_overview_info()

    def _check_minimap_click(self, mx: int, my: int) -> bool:
        """Prueft ob Klick auf Minimap war und springt zur Position."""
        if self._minimap_img is None or self._layout is None:
            return False

        canvas_w = self._canvas.winfo_width()
        canvas_h = self._canvas.winfo_height()
        mm_w, mm_h = self._minimap_img.size

        mm_x1 = canvas_w - mm_w - MINIMAP_PAD - 4
        mm_y1 = canvas_h - mm_h - MINIMAP_PAD - 4
        mm_x2 = mm_x1 + mm_w + 4
        mm_y2 = mm_y1 + mm_h + 4

        if mm_x1 <= mx <= mm_x2 and mm_y1 <= my <= mm_y2:
            # Relative Position in Minimap
            rel_x = (mx - mm_x1 - 2) / mm_w
            rel_y = (my - mm_y1 - 2) / mm_h
            # In World-Tiles umrechnen
            self._cam_x = int(rel_x * self._layout.width - self._vp_tiles_x // 2)
            self._cam_y = int(rel_y * self._layout.height - self._vp_tiles_y // 2)
            self._camera_mode = "free"
            self._cam_var.set("F")
            self._schedule_render()
            return True
        return False

    def _on_drag_motion(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        if self._camera_mode != "free":
            self._camera_mode = "free"
            self._cam_var.set("F")

        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        tile_display = TILE * self._zoom

        # Pixel-Drag in Tile-Offset umrechnen
        if abs(dx) >= tile_display:
            self._cam_x -= dx // tile_display
            self._drag_start = (
                self._drag_start[0] + (dx // tile_display) * tile_display,
                self._drag_start[1],
            )
        if abs(dy) >= tile_display:
            self._cam_y -= dy // tile_display
            self._drag_start = (
                self._drag_start[0],
                self._drag_start[1] + (dy // tile_display) * tile_display,
            )

        self._schedule_render()

    def _on_drag_end(self, _event: tk.Event) -> None:
        self._drag_start = None

    def _on_mousewheel(self, event: tk.Event) -> None:
        if event.delta > 0:
            self._zoom = min(4, self._zoom + 1)
        else:
            self._zoom = max(1, self._zoom - 1)
        self._zoom_var.set(f"{self._zoom}x")
        self._schedule_render()

    def _on_key(self, event: tk.Event) -> None:
        """WASD/Pfeiltasten fuer Free-Roam, Home=Reset."""
        scroll_speed = 3

        if event.keysym in ("Up", "w", "W"):
            self._cam_y -= scroll_speed
        elif event.keysym in ("Down", "s", "S"):
            self._cam_y += scroll_speed
        elif event.keysym in ("Left", "a", "A"):
            self._cam_x -= scroll_speed
        elif event.keysym in ("Right", "d", "D"):
            self._cam_x += scroll_speed
        elif event.keysym == "Home":
            if self._layout and self._layout.start_location in self._layout.room_bounds:
                bx, by, bw, bh = self._layout.room_bounds[self._layout.start_location]
                self._cam_x = bx + bw // 2 - self._vp_tiles_x // 2
                self._cam_y = by + bh // 2 - self._vp_tiles_y // 2
        elif event.keysym == "Tab":
            # Kamera-Modus durchschalten
            modes = ["player", "party", "free"]
            labels = ["P", "G", "F"]
            idx = modes.index(self._camera_mode) if self._camera_mode in modes else 2
            idx = (idx + 1) % len(modes)
            self._camera_mode = modes[idx]
            self._cam_var.set(labels[idx])
        elif event.keysym in ("plus", "equal"):
            self._zoom = min(4, self._zoom + 1)
            self._zoom_var.set(f"{self._zoom}x")
        elif event.keysym in ("minus",):
            self._zoom = max(1, self._zoom - 1)
            self._zoom_var.set(f"{self._zoom}x")
        else:
            return

        if self._camera_mode != "free" and event.keysym in (
            "Up", "Down", "Left", "Right", "w", "W", "a", "A", "s", "S", "d", "D"
        ):
            self._camera_mode = "free"
            self._cam_var.set("F")

        self._schedule_render()

    def _on_mouse_move(self, event: tk.Event) -> None:
        """Hover: Tile-Typ + Raum-Name in Status-Leiste."""
        if self._layout is None:
            self._hover_var.set("")
            return

        tile_display = TILE * self._zoom
        tx = self._cam_x + event.x // tile_display
        ty = self._cam_y + event.y // tile_display

        if tx < 0 or ty < 0 or tx >= self._layout.width or ty >= self._layout.height:
            self._hover_var.set("")
            return

        cell = self._layout.terrain[ty][tx]
        label = _TILE_LABELS.get(cell, cell)
        room = self._layout.tile_to_room[ty][tx]

        info_parts = [f"[{tx}, {ty}]", label]

        if room and room != "_passage":
            loc = self._layout.locations.get(room, {})
            room_name = loc.get("name", room)
            info_parts.append(f"({room_name})")
        elif room == "_passage":
            info_parts.append("(Durchgang)")

        # Spawn?
        for sid, (sx, sy) in self._layout.spawns.items():
            if sx == tx and sy == ty:
                info_parts.append(f"Spawn: {sid}")
                break

        self._hover_var.set(" ".join(info_parts))
