"""
gui/tab_dungeon_pixel.py — Tab 14: Pixel-Art Dungeon-Visualisierung

Pixel-Art-Renderer fuer den Dungeon-Crawler. Empfaengt GridEngine-Events
via EventBus und visualisiert Raum, Entities, Kampf und Effekte mit
0x72 Dungeon Tileset v5 (16x16 Pixel-Art).

Reine Viewer-Komponente — keine eigene Spiellogik.
Input: GridEngine Events (grid.room_setup, grid.entity_moved, grid.combat_move)
Output: PIL → ImageTk → tkinter Canvas (8 FPS)
"""

from __future__ import annotations

import logging
import math
import os
import random
import tkinter as tk
import tkinter.ttk as ttk
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from gui.styles import (
    BG_DARK, BG_PANEL, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE, BLUE,
    FONT_NORMAL, FONT_SMALL, FONT_BOLD, PAD, PAD_SMALL,
)
from gui.pixel_renderer import (
    Autotiler as _Autotiler,
    CLASS_MAP as _CLASS_MAP,
    MONSTER_MAP as _MONSTER_MAP,
    load_asset as _load_asset,
    tint as _tint,
    ASSET_DIR, TILE, SCALE, FOG_NEAR, FOG_FAR,
    HAS_PIL,
)

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

logger = logging.getLogger("ARS.gui.dungeon_pixel")

# ── PIL Import ───────────────────────────────────────────────────────────────

if HAS_PIL:
    from PIL import Image, ImageDraw, ImageTk

# ── Lokale Konstanten ────────────────────────────────────────────────────────

FPS = 8             # Retro-Ruckel
TICK_MS = 1000 // FPS  # 125ms
MOVE_TICKS = 2      # Ticks pro Animations-Schritt
HUD_HEIGHT = 64      # Pixel fuer HUD-Frame unter Canvas


# ── Effekt-Datenstruktur ────────────────────────────────────────────────────

@dataclass
class _Effect:
    kind: str           # "slash", "projectile", "dmg_text", "heal_text"
    x: float            # Grid-X
    y: float            # Grid-Y
    tx: float = 0.0     # Ziel-X (fuer projectile)
    ty: float = 0.0     # Ziel-Y
    text: str = ""
    ttl: int = 12
    max_ttl: int = 12
    progress: float = 0.0
    color: tuple[int, int, int] = (255, 255, 0)


# ── Entity-zu-Asset-Mapping (importiert aus pixel_renderer) ─────────────────


# ═════════════════════════════════════════════════════════════════════════════
# DungeonPixelTab
# ═════════════════════════════════════════════════════════════════════════════

class DungeonPixelTab(ttk.Frame):
    """Tab 14: Pixel-Art Dungeon-Visualisierung mit 0x72-Tileset."""

    def __init__(self, parent: ttk.Notebook, gui: "TechGUI") -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        # Rendering-State
        self._static: "Image.Image | None" = None   # Gecachter statischer Layer
        self._tk_image: Any = None                   # ImageTk-Referenz (GC-Schutz)
        self._canvas_img_id: int | None = None
        self._room_w: int = 0
        self._room_h: int = 0

        # Kamera (Tile-Koordinaten, obere linke Ecke des Viewports)
        self._cam_x: int = 0
        self._cam_y: int = 0

        # Viewport-Groesse (Tiles)
        self._vp_tiles_x: int = 20
        self._vp_tiles_y: int = 15

        # Animationen
        self._anim_queue: deque[dict] = deque()
        self._anim_pos: dict[str, tuple[int, int]] = {}  # entity_id → visuell (gx,gy)
        self._animating: set[str] = set()

        # Effekte
        self._effects: list[_Effect] = []

        # Kampf-Log
        self._log_msgs: deque[str] = deque(maxlen=5)

        # Assets
        self._assets_loaded = False
        self._hero_imgs: dict[str, "Image.Image"] = {}
        self._monster_imgs: dict[str, "Image.Image"] = {}
        self._edge_tiles: dict[str, "Image.Image"] = {}
        self._floor_plain: "Image.Image | None" = None
        self._floor_stains: list["Image.Image"] = []
        self._wall_front: "Image.Image | None" = None
        self._wall_front_left: "Image.Image | None" = None
        self._wall_front_right: "Image.Image | None" = None
        self._wall_black: "Image.Image | None" = None
        self._door_img: "Image.Image | None" = None
        self._column_img: "Image.Image | None" = None
        self._chest_img: "Image.Image | None" = None
        self._skull_img: "Image.Image | None" = None
        self._torch_imgs: list["Image.Image"] = []
        self._torch_frame: int = 0
        self._torch_timer: int = 0
        self._default_monster: "Image.Image | None" = None

        # Torch-Positionen im aktuellen Raum
        self._torch_positions: list[tuple[int, int]] = []

        # Floor-Variety-Map pro Raum
        self._floor_map: dict[tuple[int, int], "Image.Image"] = {}

        # Render-Timer
        self._after_id: str | None = None
        self._fog_cache: "Image.Image | None" = None
        self._fog_hero_pos: list[tuple[int, int]] = []
        self._tick_count: int = 0

        # Auto-Crawl
        self._auto_crawl_active: bool = False
        self._auto_crawl_idx: int = 0
        self._auto_crawl_after: str | None = None

        # Demo-Modus (standalone Grid, keine Engine noetig)
        self._demo_grid: Any = None
        self._demo_active: bool = False
        self._demo_after: str | None = None

        self._build_ui()

    # ── UI-Aufbau ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        if not HAS_PIL:
            lbl = tk.Label(
                self, text="Pillow nicht installiert.\n"
                "pip install Pillow fuer Pixel-Art-Dungeon.",
                bg=BG_DARK, fg=FG_MUTED, font=FONT_BOLD,
                justify=tk.CENTER,
            )
            lbl.pack(expand=True)
            return

        # Canvas fuer Pixel-Art
        self._canvas = tk.Canvas(
            self, bg="#050308", highlightthickness=0, cursor="crosshair",
        )
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=(PAD, 0))
        self._canvas.bind("<Configure>", self._on_configure)

        # HUD-Frame (Auto-Crawl Button + Party HP + Log)
        hud = tk.Frame(self, bg=BG_PANEL, height=HUD_HEIGHT)
        hud.pack(fill=tk.X, padx=PAD, pady=(PAD_SMALL, PAD))
        hud.pack_propagate(False)

        # Buttons
        self._demo_btn = ttk.Button(
            hud, text="Demo", command=self._toggle_demo,
            style="Accent.TButton", width=8,
        )
        self._demo_btn.pack(side=tk.LEFT, padx=(PAD_SMALL, 2), pady=PAD_SMALL)
        self._crawl_btn = ttk.Button(
            hud, text="Auto-Crawl", command=self._toggle_auto_crawl,
            style="TButton", width=10,
        )
        self._crawl_btn.pack(side=tk.LEFT, padx=(2, PAD_SMALL), pady=PAD_SMALL)

        # Linke Haelfte: Party HP
        self._hp_frame = tk.Frame(hud, bg=BG_PANEL)
        self._hp_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=PAD_SMALL)
        self._hp_labels: dict[str, tuple[tk.Label, tk.Label]] = {}

        # Rechte Haelfte: Kampf-Log
        self._log_text = tk.Text(
            hud, bg=BG_PANEL, fg=FG_SECONDARY, font=FONT_SMALL,
            width=50, height=3, wrap=tk.WORD, state=tk.DISABLED,
            bd=0, highlightthickness=0, padx=4, pady=2,
        )
        self._log_text.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=PAD_SMALL)

    def _on_configure(self, event: Any) -> None:
        """Canvas-Groesse hat sich geaendert — Viewport neu berechnen."""
        cw = event.width
        ch = event.height
        if cw > 10 and ch > 10:
            self._vp_tiles_x = max(10, cw // (TILE * SCALE))
            self._vp_tiles_y = max(8, ch // (TILE * SCALE))

    # ── Asset-Laden ──────────────────────────────────────────────────────────

    def _load_assets(self) -> None:
        """Laedt alle Pixel-Art-Assets einmalig."""
        if self._assets_loaded:
            return
        self._assets_loaded = True

        A = _load_asset

        # Floor Tiles
        self._floor_plain = A("floor_plain.png")
        self._floor_stains = [
            A("floor_stain_1.png"), A("floor_stain_2.png"), A("floor_stain_3.png"),
        ]
        self._floor_light = A("floor_light.png")

        # Wall Tiles
        self._wall_front = A("Wall_front.png")
        self._wall_front_left = A("Wall_front_left.png")
        self._wall_front_right = A("Wall_front_right.png")
        self._wall_black = A("black.png")

        # Edge Tiles (alle 16 Varianten)
        for name in _Autotiler.EDGE_MAP.values():
            if name and name not in self._edge_tiles:
                self._edge_tiles[name] = A(f"{name}.png")

        # Tueren
        self._door_img = A("door_open.png")

        # Deko
        self._column_img = A("column.png", fallback_size=(TILE, 32))
        self._chest_img = A("chest_closed.png")
        self._skull_img = A("skull.png")

        # Fackeln (8 Frames)
        self._torch_imgs = [A(f"torch_{i}.png") for i in range(1, 9)]

        # Heroes (hero_basic.png gefaerbt)
        hero_base = A("hero_basic.png")
        for sym, (key, color) in _CLASS_MAP.items():
            self._hero_imgs[sym] = _tint(hero_base, color)
        # Default Hero (ungefaerbt)
        self._hero_imgs["?"] = hero_base

        # Monster
        for key, filename in _MONSTER_MAP.items():
            if filename not in [m for m in self._monster_imgs.values()]:
                self._monster_imgs[key] = A(filename)
        self._default_monster = A("monster_imp.png")

        # NPC-Sprites
        self._npc_img = A("npc_merchant.png")

        # Generierte Sprites (von SpriteExtractor)
        self._load_generated_sprites()

        logger.info("Pixel-Dungeon Assets geladen (%d Heroes, %d Monster, %d generated)",
                     len(self._hero_imgs), len(self._monster_imgs),
                     len(getattr(self, "_generated_sprites", {})))

    def _load_generated_sprites(self) -> None:
        """Laedt generierte Sprites aus data/tilesets/generated/."""
        from gui.pixel_renderer import GENERATED_DIR as _GEN_DIR
        self._generated_sprites: dict[str, "Image.Image"] = {}
        if not os.path.isdir(_GEN_DIR):
            return
        for fname in os.listdir(_GEN_DIR):
            if not fname.endswith(".png") or fname.startswith("_"):
                continue
            if fname.startswith("sprite_"):
                sprite_id = fname[len("sprite_"):-len(".png")]
                self._generated_sprites[sprite_id] = _load_asset(
                    fname, _GEN_DIR)
            elif fname.startswith("monster_") and fname.endswith("_01.png"):
                key = fname[len("monster_"):-len("_01.png")]
                if key not in self._monster_imgs:
                    self._monster_imgs[key] = _load_asset(fname, _GEN_DIR)

    # ── Event-Handler ────────────────────────────────────────────────────────

    def _on_room_setup(self, data: dict) -> None:
        """Neuer Raum — statischen Layer aufbauen."""
        if not HAS_PIL:
            return
        self._load_assets()

        self._room_w = data.get("width", 15)
        self._room_h = data.get("height", 9)
        self._anim_queue.clear()
        self._anim_pos.clear()
        self._animating.clear()
        self._effects.clear()

        self._build_static_layer()
        self._center_camera()
        self._start_render_loop()

    def _on_formation(self, data: dict) -> None:
        """Party aufgestellt — Kamera zentrieren."""
        self._center_camera()

    def _on_entity_moved(self, data: dict) -> None:
        """Entity bewegt sich — Animation in Queue schieben."""
        path = data.get("path", [])
        entity_id = data.get("entity_id", "")
        if not path or not entity_id:
            return
        # Startposition setzen
        self._anim_pos[entity_id] = tuple(path[0])
        self._animating.add(entity_id)
        self._anim_queue.append({
            "entity_id": entity_id,
            "path": path,
            "step": 0,
            "tick": 0,
        })
        # Log
        action = data.get("action", "")
        name = data.get("name", entity_id)
        if action:
            self._add_log(f"{name}: {action}")

    def _on_combat_move(self, data: dict) -> None:
        """Kampfbewegung — Animation + Effekt."""
        attacker_id = data.get("attacker_id", "")
        target_id = data.get("target_id", "")
        path = data.get("path", [])
        attack_type = data.get("attack_type", "melee")

        if path and attacker_id:
            self._anim_pos[attacker_id] = tuple(path[0])
            self._animating.add(attacker_id)
            self._anim_queue.append({
                "entity_id": attacker_id,
                "path": path,
                "step": 0,
                "tick": 0,
            })

        # Effekt am Ziel
        room = self._get_room()
        if room and target_id in room.entities:
            target = room.entities[target_id]
            if attack_type == "melee":
                self._effects.append(_Effect(
                    kind="slash", x=target.x, y=target.y,
                    ttl=6, max_ttl=6, color=(255, 200, 60),
                ))
            elif attack_type == "ranged" and attacker_id in room.entities:
                attacker = room.entities[attacker_id]
                self._effects.append(_Effect(
                    kind="projectile",
                    x=attacker.x, y=attacker.y,
                    tx=target.x, ty=target.y,
                    ttl=8, max_ttl=8, color=(200, 220, 255),
                ))

        # Log
        a_name = data.get("attacker_name", "?")
        t_name = data.get("target_name", "?")
        self._add_log(f"{a_name} greift {t_name} an!")

    def _on_hp_change(self, data: dict) -> None:
        """HP-Aenderung — Floating-Damage/Heal-Text."""
        name = data.get("name", "")
        delta = data.get("delta", 0)
        room = self._get_room()
        if not room or not name:
            return
        # Entity finden
        for ent in room.entities.values():
            if ent.name.lower() == name.lower() or name.lower() in ent.name.lower():
                if delta < 0:
                    self._effects.append(_Effect(
                        kind="dmg_text", x=ent.x, y=ent.y,
                        text=str(delta), ttl=18, max_ttl=18,
                        color=(255, 80, 80),
                    ))
                elif delta > 0:
                    self._effects.append(_Effect(
                        kind="dmg_text", x=ent.x, y=ent.y,
                        text=f"+{delta}", ttl=18, max_ttl=18,
                        color=(80, 255, 80),
                    ))
                break

    # ── Statischer Layer ─────────────────────────────────────────────────────

    def _build_static_layer(self) -> None:
        """Rendert Terrain als gecachtes PIL-Bild (Quelle fuer Viewport-Crop)."""
        room = self._get_room()
        if not room:
            return

        w, h = room.width, room.height
        self._room_w = w
        self._room_h = h

        # RoomGrid → 0/1 Wall-Grid fuer Autotiler
        wall_grid: list[list[int]] = []
        for y in range(h):
            row = []
            for x in range(w):
                row.append(1 if room.cells[y][x].terrain == "wall" else 0)
            wall_grid.append(row)

        autotiler = _Autotiler(wall_grid, self._edge_tiles)

        # Floor-Variety-Map (deterministic per room)
        rng = random.Random(hash(room.room_id))
        self._floor_map.clear()
        for y in range(h):
            for x in range(w):
                if wall_grid[y][x] == 0:
                    r = rng.random()
                    if r < 0.06:
                        self._floor_map[(x, y)] = rng.choice(self._floor_stains)
                    elif r < 0.10:
                        self._floor_map[(x, y)] = self._floor_light
                    else:
                        self._floor_map[(x, y)] = self._floor_plain

        # Static Layer rendern
        src_w = w * TILE
        src_h = h * TILE
        self._static = Image.new("RGBA", (src_w, src_h), (5, 3, 8, 255))

        for y in range(h):
            for x in range(w):
                px, py = x * TILE, y * TILE
                terrain = room.cells[y][x].terrain

                if terrain == "wall":
                    wname = autotiler.get_wall_asset_name(x, y)
                    if wname == "Wall_front":
                        wt = self._wall_front
                    elif wname == "Wall_front_left":
                        wt = self._wall_front_left
                    elif wname == "Wall_front_right":
                        wt = self._wall_front_right
                    else:
                        wt = self._wall_black
                    self._static.paste(wt, (px, py), wt)
                else:
                    # Floor-Basis
                    tile = self._floor_map.get((x, y), self._floor_plain)
                    self._static.paste(tile, (px, py), tile)

                    # Edge-Overlay
                    mask = autotiler.get_edge_mask(x, y)
                    ename = _Autotiler.EDGE_MAP.get(mask)
                    if ename and ename in self._edge_tiles:
                        etile = self._edge_tiles[ename]
                        self._static.paste(etile, (px, py), etile)

                    # Spezial-Terrain
                    if terrain == "door" and self._door_img:
                        self._static.paste(self._door_img, (px, py), self._door_img)
                    elif terrain == "obstacle" and self._column_img:
                        # Saeulen sind 16x32 — oben ueberlappend
                        col_h = self._column_img.height
                        self._static.paste(
                            self._column_img,
                            (px, py - (col_h - TILE)),
                            self._column_img,
                        )

        # Torch-Positionen berechnen: Wall_front mit Floor daneben
        self._torch_positions.clear()
        for y in range(h):
            for x in range(w):
                if wall_grid[y][x] == 1 and y + 1 < h and wall_grid[y + 1][x] == 0:
                    # Wall_front → Fackel-Kandidat
                    if rng.random() < 0.12:
                        self._torch_positions.append((x, y))

        # Skulls in Sackgassen
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if wall_grid[y][x] != 0:
                    continue
                nbrs = sum(
                    1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if 0 <= x + dx < w and 0 <= y + dy < h
                    and wall_grid[y + dy][x + dx] == 0
                )
                if nbrs == 1 and self._skull_img:
                    self._static.paste(
                        self._skull_img,
                        (x * TILE, y * TILE),
                        self._skull_img,
                    )

        logger.info("Static Layer gerendert: %dx%d (%d Fackeln)",
                     w, h, len(self._torch_positions))

    # ── Render-Loop ──────────────────────────────────────────────────────────

    def _start_render_loop(self) -> None:
        """Startet den 8-FPS Render-Loop (idempotent)."""
        if self._after_id:
            return
        self._tick()

    def _stop_render_loop(self) -> None:
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _tick(self) -> None:
        """Haupt-Loop: Update + Render (8 FPS, Tab-Visibility-Check)."""
        self._tick_count += 1
        # Skip wenn Tab nicht sichtbar
        try:
            if self.gui.notebook.select() != str(self):
                self._after_id = self.after(TICK_MS * 4, self._tick)
                return
        except Exception:
            pass
        self._update()
        # Idle-Skip: nur jeden 4. Tick rendern wenn nichts animiert wird
        is_active = bool(self._anim_queue or self._effects)
        if is_active or self._tick_count % 4 == 0:
            self._render()
        self._after_id = self.after(TICK_MS, self._tick)

    def _update(self) -> None:
        """Animationen abarbeiten, Effekte ticken."""
        # Torch-Animation
        self._torch_timer += 1
        if self._torch_timer >= 4:
            self._torch_timer = 0
            self._torch_frame = (self._torch_frame + 1) % len(self._torch_imgs) \
                if self._torch_imgs else 0

        # Bewegungs-Animationen (ALLE gleichzeitig, nicht sequentiell)
        if self._anim_queue:
            still_active: list[dict] = []
            for anim in self._anim_queue:
                anim["tick"] += 1
                if anim["tick"] >= MOVE_TICKS:
                    anim["tick"] = 0
                    anim["step"] += 1
                    eid = anim["entity_id"]
                    if anim["step"] >= len(anim["path"]):
                        self._animating.discard(eid)
                        self._anim_pos.pop(eid, None)
                    else:
                        x, y = anim["path"][anim["step"]]
                        self._anim_pos[eid] = (x, y)
                        still_active.append(anim)
                else:
                    still_active.append(anim)
            self._anim_queue = deque(still_active)

        # Effekte ticken
        for eff in self._effects[:]:
            eff.ttl -= 1
            if eff.kind == "projectile":
                eff.progress = 1.0 - (eff.ttl / eff.max_ttl) if eff.max_ttl else 1.0
            if eff.ttl <= 0:
                self._effects.remove(eff)

    def _render(self) -> None:
        """Rendert den Viewport: Static Crop → Entities → FoW → Scale → Effects."""
        if not self._static or not HAS_PIL:
            return

        room = self._get_room()
        if not room:
            return

        cam_x, cam_y = self._cam_x, self._cam_y
        vp_tw = min(self._vp_tiles_x, self._room_w)
        vp_th = min(self._vp_tiles_y, self._room_h)

        if vp_tw <= 0 or vp_th <= 0:
            return

        # Crop-Box (Source-Aufloesung)
        crop_x = max(0, min(self._room_w * TILE - vp_tw * TILE, cam_x * TILE))
        crop_y = max(0, min(self._room_h * TILE - vp_th * TILE, cam_y * TILE))
        crop_w = vp_tw * TILE
        crop_h = vp_th * TILE

        src = self._static.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
        src = src.copy()  # Crop ist Read-Only

        # Animierte Fackeln
        if self._torch_imgs:
            torch = self._torch_imgs[self._torch_frame]
            for gx, gy in self._torch_positions:
                vx = gx - cam_x
                vy = gy - cam_y
                if 0 <= vx < vp_tw and 0 <= vy < vp_th:
                    src.paste(torch, (vx * TILE, vy * TILE), torch)

        # Entities zeichnen (nach Y sortiert)
        entities = list(room.entities.values())
        entities.sort(key=lambda e: e.y)
        for ent in entities:
            if not ent.alive:
                continue
            # Visuelle Position (Animation oder Grid)
            if ent.entity_id in self._anim_pos:
                ex, ey = self._anim_pos[ent.entity_id]
            else:
                ex, ey = ent.x, ent.y

            vx = ex - cam_x
            vy = ey - cam_y
            if not (0 <= vx < vp_tw and 0 <= vy < vp_th):
                continue

            sprite = self._get_entity_sprite(ent)
            sp_w, sp_h = sprite.size
            px, py = vx * TILE, vy * TILE
            # Grosse Sprites zentriert auf Tile-Position
            if sp_w > TILE or sp_h > TILE:
                offset_x = -(sp_w - TILE) // 2
                offset_y = -(sp_h - TILE) // 2
                src.paste(sprite, (px + offset_x, py + offset_y), sprite)
            else:
                src.paste(sprite, (px, py), sprite)

            # HP-Balken
            bw = TILE
            by = py - 3
            if by >= 0:
                d = ImageDraw.Draw(src)
                hp, max_hp = self._get_entity_hp(ent)
                if max_hp > 0:
                    ratio = max(0.0, min(1.0, hp / max_hp))
                    d.rectangle([px, by, px + bw - 1, by + 1], fill=(40, 40, 40))
                    filled = max(1, int(bw * ratio))
                    if ratio > 0:
                        col = (70, 210, 70) if ent.entity_type == "party_member" \
                            else (210, 50, 50)
                        d.rectangle([px, by, px + filled, by + 1], fill=col)

        # Slash-Effekte (Source-Aufloesung)
        d_src = ImageDraw.Draw(src)
        for eff in self._effects:
            if eff.kind == "slash":
                sx = int(eff.x - cam_x) * TILE + TILE // 2
                sy = int(eff.y - cam_y) * TILE + TILE // 2
                col = eff.color
                d_src.line([(sx - 4, sy - 4), (sx + 4, sy + 4)], fill=col, width=1)
                d_src.line([(sx + 4, sy - 4), (sx - 4, sy + 4)], fill=col, width=1)

        # Fog of War
        self._render_fog(src, cam_x, cam_y, vp_tw, vp_th, room)

        # Scale Up (NEAREST fuer Pixel-Art)
        display_w = vp_tw * TILE * SCALE
        display_h = vp_th * TILE * SCALE
        big = src.resize((display_w, display_h), Image.NEAREST)

        # Effekte auf skaliertem Bild
        d = ImageDraw.Draw(big)
        for eff in self._effects:
            if eff.kind == "projectile":
                sx = (eff.x - cam_x) * TILE * SCALE
                sy = (eff.y - cam_y) * TILE * SCALE
                ex = (eff.tx - cam_x) * TILE * SCALE
                ey = (eff.ty - cam_y) * TILE * SCALE
                cx = sx + (ex - sx) * eff.progress
                cy = sy + (ey - sy) * eff.progress
                d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=eff.color)
            elif eff.kind == "dmg_text":
                rise = (1.0 - eff.ttl / eff.max_ttl) * 24
                sx = (eff.x - cam_x) * TILE * SCALE
                sy = (eff.y - cam_y) * TILE * SCALE - rise
                fade = eff.ttl / eff.max_ttl if eff.max_ttl else 0
                col = tuple(max(0, min(255, int(v * fade))) for v in eff.color)
                d.text((int(sx), int(sy)), eff.text, fill=col)

        # Auf Canvas anzeigen
        self._tk_image = ImageTk.PhotoImage(big)
        if self._canvas_img_id is None:
            self._canvas_img_id = self._canvas.create_image(
                0, 0, anchor=tk.NW, image=self._tk_image,
            )
        else:
            self._canvas.itemconfig(self._canvas_img_id, image=self._tk_image)

        # HUD aktualisieren
        self._update_hud(room)

    def _render_fog(self, src: "Image.Image", cam_x: int, cam_y: int,
                    vp_tw: int, vp_th: int, room: Any) -> None:
        """Fog of War: Party-Members beleuchten die Umgebung.

        Performance-Optimierung: Fog wird als Tiny-Image (1px/Tile) berechnet
        und per NEAREST-Resize auf Viewport-Groesse skaliert. ~100x schneller
        als per-Tile ImageDraw.rectangle().
        """
        # Party-Member-Positionen sammeln
        hero_positions: list[tuple[int, int]] = []
        for ent in room.entities.values():
            if ent.entity_type == "party_member" and ent.alive:
                if ent.entity_id in self._anim_pos:
                    hero_positions.append(self._anim_pos[ent.entity_id])
                else:
                    hero_positions.append((ent.x, ent.y))

        if not hero_positions:
            fog = Image.new("RGBA", src.size, (0, 0, 0, 230))
            src.alpha_composite(fog)
            return

        # Cache nutzen wenn Hero-Positionen unveraendert
        if hero_positions == self._fog_hero_pos and self._fog_cache \
                and self._fog_cache.size == (vp_tw * TILE, vp_th * TILE):
            src.alpha_composite(self._fog_cache)
            return

        self._fog_hero_pos = hero_positions[:]

        # Beleuchtete Tiles berechnen
        near_set: set[tuple[int, int]] = set()
        mid_set: set[tuple[int, int]] = set()
        for hx, hy in hero_positions:
            for dy in range(-FOG_FAR - 1, FOG_FAR + 2):
                for dx in range(-FOG_FAR - 1, FOG_FAR + 2):
                    tx, ty = hx + dx, hy + dy
                    dist_sq = dx * dx + dy * dy
                    if dist_sq <= FOG_NEAR * FOG_NEAR:
                        near_set.add((tx, ty))
                    elif dist_sq <= FOG_FAR * FOG_FAR:
                        mid_set.add((tx, ty))

        # Tiny-Image: 1 Pixel pro Tile (statt 256 Pixel pro Tile)
        fog_small = Image.new("RGBA", (vp_tw, vp_th), (0, 0, 0, 230))
        fog_px = fog_small.load()
        for vy in range(vp_th):
            for vx in range(vp_tw):
                pos = (vx + cam_x, vy + cam_y)
                if pos in near_set:
                    fog_px[vx, vy] = (0, 0, 0, 0)
                elif pos in mid_set:
                    fog_px[vx, vy] = (0, 0, 0, 128)

        # Resize auf Viewport-Groesse (C-optimiert, schnell)
        self._fog_cache = fog_small.resize(
            (vp_tw * TILE, vp_th * TILE), Image.NEAREST,
        )
        src.alpha_composite(self._fog_cache)

    # ── HUD ──────────────────────────────────────────────────────────────────

    def _update_hud(self, room: Any) -> None:
        """Aktualisiert die HP-Anzeige und den Kampf-Log."""
        if not room:
            return

        # Party-Member HP-Labels aktualisieren
        party_ents = [
            e for e in room.entities.values()
            if e.entity_type == "party_member"
        ]

        # Bestehende Labels ggf. erneuern
        current_ids = {e.entity_id for e in party_ents}
        if set(self._hp_labels.keys()) != current_ids:
            # Labels neu aufbauen
            for w1, w2 in self._hp_labels.values():
                w1.destroy()
                w2.destroy()
            self._hp_labels.clear()

            for ent in party_ents:
                name_lbl = tk.Label(
                    self._hp_frame, text=f"{ent.symbol}{ent.name}",
                    bg=BG_PANEL, fg=FG_PRIMARY, font=FONT_SMALL,
                    anchor=tk.W,
                )
                name_lbl.pack(side=tk.LEFT, padx=(4, 1))
                hp, max_hp = self._get_entity_hp(ent)
                hp_lbl = tk.Label(
                    self._hp_frame, text=f"{hp}/{max_hp}",
                    bg=BG_PANEL, fg=GREEN, font=FONT_SMALL,
                    anchor=tk.W,
                )
                hp_lbl.pack(side=tk.LEFT, padx=(0, 8))
                self._hp_labels[ent.entity_id] = (name_lbl, hp_lbl)
        else:
            # Nur HP-Werte aktualisieren
            for ent in party_ents:
                if ent.entity_id in self._hp_labels:
                    _, hp_lbl = self._hp_labels[ent.entity_id]
                    hp, max_hp = self._get_entity_hp(ent)
                    hp_lbl.config(text=f"{hp}/{max_hp}")
                    if max_hp > 0:
                        ratio = hp / max_hp
                        if ratio > 0.5:
                            hp_lbl.config(fg=GREEN)
                        elif ratio > 0.25:
                            hp_lbl.config(fg=YELLOW)
                        else:
                            hp_lbl.config(fg=RED)
                    if not ent.alive:
                        hp_lbl.config(fg=FG_MUTED)

        # Log aktualisieren
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        for msg in self._log_msgs:
            self._log_text.insert(tk.END, msg + "\n")
        self._log_text.config(state=tk.DISABLED)

    # ── Kamera ───────────────────────────────────────────────────────────────

    def _center_camera(self) -> None:
        """Zentriert die Kamera auf den Mittelpunkt der Party."""
        room = self._get_room()
        if not room:
            return

        alive = [
            e for e in room.entities.values()
            if e.entity_type == "party_member" and e.alive
        ]
        if not alive:
            self._cam_x = 0
            self._cam_y = 0
            return

        cx = sum(e.x for e in alive) // len(alive)
        cy = sum(e.y for e in alive) // len(alive)
        self._cam_x = max(0, min(
            self._room_w - self._vp_tiles_x,
            cx - self._vp_tiles_x // 2,
        ))
        self._cam_y = max(0, min(
            self._room_h - self._vp_tiles_y,
            cy - self._vp_tiles_y // 2,
        ))

    # ── Entity-Sprite-Zuordnung ──────────────────────────────────────────────

    def _get_entity_sprite(self, ent: Any) -> "Image.Image":
        """Mappt GridEntity auf ein Pixel-Art-Sprite.

        Prioritaet:
          1. sprite_{entity_id}.png in generated/ (exakter ID-Match)
          2. Name-Keywords in generated/ + monster_imgs
          3. MONSTER_MAP Fallback
        """
        if ent.entity_type == "party_member":
            sym = ent.symbol if ent.symbol in self._hero_imgs else "?"
            return self._hero_imgs.get(sym, self._hero_imgs["?"])

        # Fuer Monster und NPCs: generierte Sprites zuerst pruefen
        gen = getattr(self, "_generated_sprites", {})

        # 1. Exakter ID-Match
        eid = getattr(ent, "entity_id", "")
        if eid and eid in gen:
            return gen[eid]

        # 2. Normalisierter Name-Match
        import re as _re
        name_norm = _re.sub(r"[^a-z0-9_]", "_", ent.name.lower())
        name_norm = _re.sub(r"_+", "_", name_norm).strip("_")
        if name_norm in gen:
            return gen[name_norm]

        # 3. Keyword-Match in monster_imgs
        if ent.entity_type == "monster":
            name_lower = ent.name.lower()
            for keyword, img in self._monster_imgs.items():
                if keyword in name_lower:
                    return img
            return self._default_monster

        # NPC
        return self._npc_img

    def _get_entity_hp(self, ent: Any) -> tuple[int, int]:
        """Holt HP/Max-HP aus dem PartyState oder CombatTracker."""
        party_state = getattr(self.gui.engine, "party_state", None)
        if party_state and ent.entity_type == "party_member":
            member = party_state.get_member(ent.entity_id)
            if member:
                hp = member.get("current_hp", member.get("hp", 10))
                max_hp = member.get("max_hp", hp)
                return hp, max_hp

        combat = getattr(self.gui.engine, "_combat_tracker", None)
        if not combat:
            orch = getattr(self.gui.engine, "_orchestrator", None)
            if orch:
                combat = getattr(orch, "_combat_tracker", None)
        if combat:
            ct_ent = combat.get_entity(ent.entity_id)
            if ct_ent:
                return ct_ent.get("hp", 10), ct_ent.get("max_hp", 10)

        return 10, 10

    # ── Hilfsfunktionen ──────────────────────────────────────────────────────

    def _get_room(self) -> Any:
        """Holt das aktuelle RoomGrid (Demo-Grid bevorzugt)."""
        if self._demo_grid:
            return self._demo_grid.get_current_room()
        grid = getattr(self.gui.engine, "grid_engine", None)
        if grid:
            return grid.get_current_room()
        return None

    def _add_log(self, msg: str) -> None:
        """Fuegt eine Nachricht zum Kampf-Log hinzu."""
        self._log_msgs.append(msg)

    # ── Event-Router ─────────────────────────────────────────────────────────

    def handle_event(self, data: dict[str, Any]) -> None:
        """Dispatcht EventBus-Events an die entsprechenden Handler."""
        event = data.get("_event", "")

        if event == "grid.room_setup":
            self._on_room_setup(data)
        elif event == "grid.formation_placed":
            self._on_formation(data)
        elif event == "grid.entity_moved":
            self._on_entity_moved(data)
        elif event == "grid.combat_move":
            self._on_combat_move(data)
        elif event == "party.member_updated":
            # HP-Aenderung → Floating Text
            name = data.get("name", "")
            hp = data.get("hp", 0)
            prev_hp = data.get("prev_hp", hp)
            if prev_hp != hp:
                self._on_hp_change({
                    "name": name,
                    "delta": hp - prev_hp,
                })
        elif event == "keeper.response":
            # Kampf-Log aus Keeper-Antwort (gekuerzt)
            text = data.get("text", "")
            if text and len(text) > 5:
                short = text[:80] + "..." if len(text) > 80 else text
                self._add_log(short)
                self._center_camera()

    def on_engine_ready(self) -> None:
        """Initialer Sync wenn Engine fertig ist."""
        if not HAS_PIL:
            return
        self._load_assets()
        room = self._get_room()
        if room:
            self._room_w = room.width
            self._room_h = room.height
            self._build_static_layer()
            self._center_camera()
            self._start_render_loop()

    # ── Auto-Crawl ───────────────────────────────────────────────────────────

    _CRAWL_COMMANDS = [
        "Ich schaue mich vorsichtig im Raum um und untersuche jede Ecke.",
        "Ich greife das naechste Monster mit meiner Waffe an!",
        "Ich durchsuche die Umgebung nach verborgenen Schaetzen und Fallen.",
        "Ich gehe vorsichtig weiter und erkunde den naechsten Bereich.",
        "Wir formieren uns und ruecken geschlossen vor!",
        "Ich versuche die Tuer zu oeffnen und den Gang dahinter zu erkunden.",
        "Ich greife mit voller Kraft an — keine Gnade!",
        "Ich untersuche die Waende nach Geheimtueren.",
        "Wir kaempfen uns durch die Gegner hindurch!",
        "Ich sammle alles Nuetzliche ein und wir ziehen weiter.",
    ]

    def _toggle_auto_crawl(self) -> None:
        """Startet/Stoppt den automatischen Dungeon Crawl."""
        self._auto_crawl_active = not self._auto_crawl_active
        if self._auto_crawl_active:
            self._crawl_btn.config(text="STOP Crawl")
            self._add_log(">> Auto-Crawl gestartet")
            self._auto_crawl_tick()
        else:
            self._crawl_btn.config(text="Auto-Crawl")
            self._add_log(">> Auto-Crawl gestoppt")
            if self._auto_crawl_after:
                self.after_cancel(self._auto_crawl_after)
                self._auto_crawl_after = None

    def _auto_crawl_tick(self) -> None:
        """Sendet den naechsten Auto-Crawl-Befehl an die Engine."""
        if not self._auto_crawl_active:
            return

        orch = getattr(self.gui.engine, "_orchestrator", None)
        if not orch or not getattr(orch, "_active", False):
            self._add_log(">> Warte auf aktive Session...")
            self._auto_crawl_after = self.after(3000, self._auto_crawl_tick)
            return

        # Naechsten Befehl senden
        cmd = self._CRAWL_COMMANDS[self._auto_crawl_idx % len(self._CRAWL_COMMANDS)]
        self._auto_crawl_idx += 1
        try:
            orch._input_queue.put(cmd)
            self._add_log(f">> {cmd[:60]}...")
        except Exception:
            pass

        # Naechster Befehl in 4 Sekunden
        self._auto_crawl_after = self.after(4000, self._auto_crawl_tick)

    # ── Demo-Crawl (standalone, ohne Engine) ─────────────────────────────────

    def _toggle_demo(self) -> None:
        """Startet/Stoppt den Standalone-Demo-Crawl."""
        if self._demo_active:
            self._stop_demo()
        else:
            self._start_demo()

    def _start_demo(self) -> None:
        """Erzeugt Demo-Dungeon mit 6 Helden und startet Bewegungs-Loop."""
        if not HAS_PIL:
            return
        self._load_assets()

        from core.grid_engine import GridEngine, bfs_path as _bfs

        self._demo_grid = GridEngine()

        # Dungeon-Map: 28x20, 4 Raeume + Zentralhalle + Korridore
        W, H = 28, 20
        t = [["wall"] * W for _ in range(H)]

        def carve(x1, y1, x2, y2):
            for y in range(y1, y2 + 1):
                for x in range(x1, x2 + 1):
                    t[y][x] = "floor"

        # Zentralhalle (10x8)
        carve(9, 6, 18, 13)
        # NW-Raum
        carve(1, 1, 7, 5)
        # NE-Raum
        carve(20, 1, 26, 5)
        # SW-Raum
        carve(1, 14, 7, 18)
        # SE-Raum
        carve(20, 14, 26, 18)
        # Korridore (NW → Zentral)
        carve(4, 5, 5, 6)
        # Korridor (NE → Zentral)
        carve(18, 3, 20, 4)
        carve(18, 5, 19, 6)
        # Korridor (SW → Zentral)
        carve(4, 13, 5, 14)
        # Korridor (SE → Zentral)
        carve(18, 13, 19, 14)
        carve(18, 15, 20, 16)
        # Querkorridor Nord
        carve(7, 3, 9, 3)
        # Querkorridor Sued
        carve(7, 16, 9, 16)

        # Tueren
        for dx, dy in [(4, 5), (18, 6), (4, 14), (18, 13), (7, 3), (9, 3),
                        (7, 16), (9, 16), (20, 4), (20, 16)]:
            if 0 <= dy < H and 0 <= dx < W:
                t[dy][dx] = "door"

        # Saeulen in Zentralhalle
        for ox, oy in [(11, 8), (11, 11), (16, 8), (16, 11)]:
            t[oy][ox] = "obstacle"

        map_data = {"terrain": t, "exits": {}, "decorations": []}
        loc = {"id": "demo_dungeon", "name": "Demo-Dungeon", "map": map_data}

        self._demo_grid.setup_room(loc)
        room = self._demo_grid.get_current_room()

        # 6 Helden platzieren (im NW-Raum, verschiedene Klassen)
        from core.grid_engine import GridEntity
        heroes = [
            ("aldric",  "Aldric",  "F", 2, 2),
            ("elara",   "Elara",   "M", 4, 2),
            ("thorin",  "Thorin",  "C", 2, 4),
            ("kira",    "Kira",    "T", 4, 4),
            ("rowan",   "Rowan",   "R", 3, 3),
            ("sven",    "Sven",    "P", 5, 3),
        ]
        for eid, name, sym, gx, gy in heroes:
            ent = GridEntity(
                entity_id=eid, name=name, entity_type="party_member",
                x=gx, y=gy, symbol=sym, movement_rate=12,
            )
            room.place_entity(ent)

        # Static Layer bauen + Render starten
        self._room_w = room.width
        self._room_h = room.height
        self._fog_cache = None
        self._build_static_layer()
        self._center_camera()
        self._start_render_loop()

        self._demo_active = True
        self._demo_btn.config(text="STOP")
        self._add_log(">> Demo-Crawl: 6 Helden erkunden das Dungeon")

        # Bewegungs-Loop starten
        self._demo_move_tick()

    def _stop_demo(self) -> None:
        """Stoppt den Demo-Crawl."""
        self._demo_active = False
        self._demo_grid = None
        self._demo_btn.config(text="Demo")
        self._fog_cache = None
        if self._demo_after:
            self.after_cancel(self._demo_after)
            self._demo_after = None
        self._anim_queue.clear()
        self._anim_pos.clear()
        self._animating.clear()
        self._add_log(">> Demo gestoppt")

    def _demo_move_tick(self) -> None:
        """Bewegt alle Demo-Helden gleichzeitig zu zufaelligen Zielen."""
        if not self._demo_active or not self._demo_grid:
            return

        import random as _rng
        from core.grid_engine import bfs_path as _bfs
        from core.event_bus import EventBus

        room = self._demo_grid.get_current_room()
        if not room:
            return

        bus = EventBus.get()

        for eid, ent in list(room.entities.items()):
            if eid in self._animating:
                continue  # Noch in Bewegung

            # Zufaelliges begehbares Ziel in 3-8 Tiles Entfernung
            candidates = []
            for dy in range(-8, 9):
                for dx in range(-8, 9):
                    nx, ny = ent.x + dx, ent.y + dy
                    md = abs(dx) + abs(dy)
                    if 3 <= md <= 8 and room.in_bounds(nx, ny) \
                            and room.is_walkable(nx, ny):
                        candidates.append((nx, ny))

            if not candidates:
                continue

            tx, ty = _rng.choice(candidates)
            path = _bfs(room, (ent.x, ent.y), (tx, ty), max_steps=8)
            if path and len(path) > 1:
                path = path[:7]  # Max 6 Schritte
                final_x, final_y = path[-1]
                room.move_entity_to(eid, final_x, final_y)
                bus.emit("grid", "entity_moved", {
                    "entity_id": eid,
                    "name": ent.name,
                    "path": path,
                    "move_type": "walk",
                })

        self._center_camera()
        # Naechste Bewegung in 1.5s (genug Zeit fuer Animation)
        self._demo_after = self.after(1500, self._demo_move_tick)
