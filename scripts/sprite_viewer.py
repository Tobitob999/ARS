"""
scripts/sprite_viewer.py — Sprite-Galerie & Animations-Viewer

Zeigt alle generierten Sprites aus data/tilesets/generated/ in einer
scrollbaren Galerie mit Live-Animationsvorschau.

Kategorien: Monster, Animationen (6 Klassen x 6 Aktionen), Biome/Environments
Sprites werden 4x skaliert (16px → 64px) fuer bessere Sichtbarkeit.

Starten:  py -3 scripts/sprite_viewer.py
"""

from __future__ import annotations

import os
import re
import sys
import tkinter as tk
import tkinter.ttk as ttk
from collections import defaultdict
from typing import Any

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from gui.styles import (
    configure_dark_theme,
    BG_DARK, BG_PANEL, BG_INPUT,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE,
    FONT_FAMILY,
)

try:
    from PIL import Image, ImageTk, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

GENERATED_DIR = os.path.join(_PROJECT_ROOT, "data", "tilesets", "generated")
SCALE = 4  # 16px → 64px
ANIM_MS = 180  # ms pro Animations-Frame

FONT_N = (FONT_FAMILY, 10)
FONT_S = (FONT_FAMILY, 9)
FONT_B = (FONT_FAMILY, 10, "bold")
FONT_L = (FONT_FAMILY, 14, "bold")
FONT_XL = (FONT_FAMILY, 18, "bold")


# ══════════════════════════════════════════════════════════════════════════════
# Sprite-Katalog einlesen
# ══════════════════════════════════════════════════════════════════════════════

def _scan_sprites() -> dict[str, Any]:
    """Scannt generated/ und gruppiert Sprites nach Kategorie."""
    catalog: dict[str, Any] = {
        "monsters": {},       # name → [path, ...]
        "monsters_gen": {},   # name → [path, ...]
        "animations": {},     # "class_action" → [frame_paths]
        "environments": {},   # "biome_type" → [path, ...]
        "sheets": {},         # name → path
        "other": [],
    }

    if not os.path.isdir(GENERATED_DIR):
        return catalog

    for fname in sorted(os.listdir(GENERATED_DIR)):
        if not fname.endswith(".png"):
            continue
        fpath = os.path.join(GENERATED_DIR, fname)
        base = fname[:-4]  # ohne .png

        # Sprite-Sheets
        if base.startswith("sheet_"):
            catalog["sheets"][base[6:]] = fpath
            continue

        # Monster (Compendium): monster_beholder_01
        m = re.match(r"monster_(?!gen_)(.+?)_(\d+)$", base)
        if m:
            name = m.group(1)
            catalog["monsters"].setdefault(name, []).append(fpath)
            continue

        # Monster (generiert): monster_gen_undead_humanoid_001
        m = re.match(r"monster_gen_(.+?)_(\d+)$", base)
        if m:
            name = m.group(1)
            catalog["monsters_gen"].setdefault(name, []).append(fpath)
            continue

        # Animationen: anim_fighter_attack_01
        m = re.match(r"anim_(.+?)_(\d+)$", base)
        if m:
            key = m.group(1)
            catalog["animations"].setdefault(key, []).append(fpath)
            continue

        # Environments: env_cave_floor.png, env_cave_floor_v1.png
        m = re.match(r"env_(.+)", base)
        if m:
            parts = m.group(1).split("_")
            biome = parts[0]
            tile_type = "_".join(parts[1:]) if len(parts) > 1 else "misc"
            key = f"{biome}"
            catalog["environments"].setdefault(key, []).append(fpath)
            continue

        # Preview / Sonstiges
        if base != "_preview":
            catalog["other"].append(fpath)

    return catalog


# ══════════════════════════════════════════════════════════════════════════════
# SpriteViewer GUI
# ══════════════════════════════════════════════════════════════════════════════

class SpriteViewer:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ARS Sprite-Galerie")
        self.root.geometry("1400x900")
        self.root.configure(bg=BG_DARK)
        configure_dark_theme(self.root)

        if not HAS_PIL:
            tk.Label(self.root, text="Pillow nicht installiert!\npip install Pillow",
                     bg=BG_DARK, fg=RED, font=FONT_XL).pack(expand=True)
            return

        self.catalog = _scan_sprites()
        self._tk_images: list[Any] = []  # GC-Schutz
        self._anim_after: str | None = None
        self._anim_frames: list[ImageTk.PhotoImage] = []
        self._anim_idx: int = 0
        self._anim_label: tk.Label | None = None
        self._selected_category = tk.StringVar(value="monsters")

        self._build_ui()
        self._show_category("monsters")

        # Monster-Parade Tab
        self._parade = MonsterParade(self._notebook, self.catalog)
        self._notebook.add(self._parade, text="  Monster-Parade  ")

    def _build_ui(self) -> None:
        # ── Notebook (Galerie + Parade) ────────────────────────────────
        self._notebook = ttk.Notebook(self.root)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Galerie
        gallery_tab = tk.Frame(self._notebook, bg=BG_DARK)
        self._notebook.add(gallery_tab, text="  Sprite-Galerie  ")

        # ── Top-Bar: Kategorie-Buttons ───────────────────────────────────
        top = tk.Frame(gallery_tab, bg=BG_PANEL, height=50)
        top.pack(fill=tk.X)
        top.pack_propagate(False)

        tk.Label(top, text="  ARS Sprite-Galerie  ", bg=BG_PANEL,
                 fg=FG_ACCENT, font=FONT_XL).pack(side=tk.LEFT, padx=12, pady=8)

        cats = [
            ("Monster (Compendium)", "monsters"),
            ("Monster (Generiert)", "monsters_gen"),
            ("Animationen", "animations"),
            ("Environments", "environments"),
            ("Sprite-Sheets", "sheets"),
        ]
        for label, key in cats:
            btn = ttk.Button(top, text=label,
                             command=lambda k=key: self._show_category(k))
            btn.pack(side=tk.LEFT, padx=4, pady=8)

        # ── Zähler ──────────────────────────────────────────────────────
        self._count_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self._count_var, bg=BG_PANEL,
                 fg=FG_MUTED, font=FONT_S).pack(side=tk.RIGHT, padx=12)

        # ── Haupt-Bereich: Scrollbare Galerie + Detail-Panel ────────────
        body = tk.Frame(gallery_tab, bg=BG_DARK)
        body.pack(fill=tk.BOTH, expand=True)

        # Scrollbare Galerie (links, gross)
        gallery_frame = tk.Frame(body, bg=BG_DARK)
        gallery_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(gallery_frame, bg=BG_DARK,
                                 highlightthickness=0)
        scrollbar = ttk.Scrollbar(gallery_frame, orient=tk.VERTICAL,
                                  command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = tk.Frame(self._canvas, bg=BG_DARK)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._inner, anchor=tk.NW)

        self._inner.bind("<Configure>",
                         lambda e: self._canvas.configure(
                             scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        # Mausrad-Scrolling
        self._canvas.bind_all("<MouseWheel>",
                              lambda e: self._canvas.yview_scroll(
                                  -1 * (e.delta // 120), "units"))

        # Detail-Panel (rechts, 320px)
        self._detail = tk.Frame(body, bg=BG_PANEL, width=320)
        self._detail.pack(side=tk.RIGHT, fill=tk.Y)
        self._detail.pack_propagate(False)

        tk.Label(self._detail, text="  VORSCHAU  ", bg=BG_DARK,
                 fg=FG_ACCENT, font=FONT_L).pack(fill=tk.X, padx=4, pady=(8, 4))

        # Grosses Preview-Bild (8x skaliert = 128px)
        self._preview_label = tk.Label(self._detail, bg=BG_INPUT,
                                       width=160, height=160)
        self._preview_label.pack(padx=12, pady=8)

        # Animations-Label (darunter)
        tk.Label(self._detail, text="  ANIMATION  ", bg=BG_DARK,
                 fg=FG_ACCENT, font=FONT_L).pack(fill=tk.X, padx=4, pady=(8, 4))
        self._anim_preview = tk.Label(self._detail, bg=BG_INPUT,
                                      width=160, height=160)
        self._anim_preview.pack(padx=12, pady=8)

        # Info-Text
        self._info_text = tk.Text(
            self._detail, bg=BG_INPUT, fg=FG_SECONDARY, font=FONT_S,
            wrap=tk.WORD, state=tk.DISABLED, bd=0,
            highlightthickness=0, padx=8, pady=4, height=10,
        )
        self._info_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))
        self._info_text.tag_configure("head", foreground=FG_ACCENT, font=FONT_B)
        self._info_text.tag_configure("val", foreground=FG_PRIMARY)

    def _on_canvas_resize(self, event: Any) -> None:
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    # ── Kategorie anzeigen ───────────────────────────────────────────────

    def _show_category(self, category: str) -> None:
        self._selected_category.set(category)
        self._stop_anim()
        # Galerie leeren
        for w in self._inner.winfo_children():
            w.destroy()
        self._tk_images.clear()

        if category == "monsters":
            self._show_monster_grid(self.catalog["monsters"], "Compendium-Monster")
        elif category == "monsters_gen":
            self._show_monster_grid(self.catalog["monsters_gen"], "Generierte Monster")
        elif category == "animations":
            self._show_animations()
        elif category == "environments":
            self._show_environments()
        elif category == "sheets":
            self._show_sheets()

    # ── Monster-Grid ─────────────────────────────────────────────────────

    def _show_monster_grid(self, data: dict[str, list[str]], title: str) -> None:
        count = sum(len(v) for v in data.values())
        self._count_var.set(f"{len(data)} Monster, {count} Sprites")

        for name, paths in sorted(data.items()):
            # Gruppen-Frame
            grp = tk.Frame(self._inner, bg=BG_PANEL, bd=1, relief=tk.GROOVE)
            grp.pack(fill=tk.X, padx=8, pady=4)

            # Name
            display_name = name.replace("_", " ").title()
            tk.Label(grp, text=display_name, bg=BG_PANEL, fg=FG_ACCENT,
                     font=FONT_B, anchor=tk.W).pack(fill=tk.X, padx=8, pady=(4, 2))

            # Sprites nebeneinander
            row = tk.Frame(grp, bg=BG_PANEL)
            row.pack(fill=tk.X, padx=8, pady=(0, 4))

            for i, path in enumerate(paths):
                img = Image.open(path).convert("RGBA")
                big = img.resize((img.width * SCALE, img.height * SCALE),
                                 Image.NEAREST)
                tk_img = ImageTk.PhotoImage(big)
                self._tk_images.append(tk_img)

                lbl = tk.Label(row, image=tk_img, bg=BG_INPUT, bd=1,
                               relief=tk.RAISED, cursor="hand2")
                lbl.pack(side=tk.LEFT, padx=2, pady=2)
                lbl.bind("<Button-1>",
                         lambda e, p=path, n=display_name, idx=i:
                         self._show_detail(p, n, idx))

            # Sheet daneben (wenn vorhanden)
            sheet_key = f"monster_{name}"
            sheet_path = self.catalog["sheets"].get(sheet_key)
            if sheet_path:
                img = Image.open(sheet_path).convert("RGBA")
                big = img.resize((img.width * 3, img.height * 3), Image.NEAREST)
                tk_img = ImageTk.PhotoImage(big)
                self._tk_images.append(tk_img)
                lbl = tk.Label(row, image=tk_img, bg=BG_INPUT, bd=1,
                               relief=tk.FLAT)
                lbl.pack(side=tk.LEFT, padx=(12, 2), pady=2)

    # ── Animationen ──────────────────────────────────────────────────────

    def _show_animations(self) -> None:
        data = self.catalog["animations"]
        count = sum(len(v) for v in data.values())
        self._count_var.set(f"{len(data)} Animationen, {count} Frames")

        # Gruppieren nach Klasse
        by_class: dict[str, dict[str, list[str]]] = defaultdict(dict)
        for key, paths in sorted(data.items()):
            parts = key.rsplit("_", 1)
            if len(parts) == 2:
                cls, action = parts
            else:
                cls, action = key, "misc"
            by_class[cls][action] = paths

        for cls_name, actions in sorted(by_class.items()):
            # Klassen-Header
            grp = tk.Frame(self._inner, bg=BG_PANEL, bd=1, relief=tk.GROOVE)
            grp.pack(fill=tk.X, padx=8, pady=4)

            display = cls_name.replace("_", " ").title()
            tk.Label(grp, text=display, bg=BG_PANEL, fg=FG_ACCENT,
                     font=FONT_L, anchor=tk.W).pack(fill=tk.X, padx=8, pady=(4, 2))

            for action, paths in sorted(actions.items()):
                act_frame = tk.Frame(grp, bg=BG_PANEL)
                act_frame.pack(fill=tk.X, padx=8, pady=2)

                tk.Label(act_frame, text=f"  {action}:", bg=BG_PANEL,
                         fg=FG_SECONDARY, font=FONT_S, width=10,
                         anchor=tk.W).pack(side=tk.LEFT)

                for path in paths:
                    img = Image.open(path).convert("RGBA")
                    big = img.resize((img.width * SCALE, img.height * SCALE),
                                     Image.NEAREST)
                    tk_img = ImageTk.PhotoImage(big)
                    self._tk_images.append(tk_img)

                    lbl = tk.Label(act_frame, image=tk_img, bg=BG_INPUT,
                                   bd=1, relief=tk.FLAT, cursor="hand2")
                    lbl.pack(side=tk.LEFT, padx=1, pady=1)

                # Abspielen-Button
                btn = ttk.Button(
                    act_frame, text="\u25B6", width=3,
                    command=lambda p=paths: self._play_anim(p))
                btn.pack(side=tk.LEFT, padx=(8, 2))

                # Sheet
                sheet_key = f"{cls_name}_{action}"
                sheet_path = self.catalog["sheets"].get(sheet_key)
                if sheet_path:
                    img = Image.open(sheet_path).convert("RGBA")
                    big = img.resize((img.width * 3, img.height * 3),
                                     Image.NEAREST)
                    tk_img = ImageTk.PhotoImage(big)
                    self._tk_images.append(tk_img)
                    lbl = tk.Label(act_frame, image=tk_img, bg=BG_INPUT,
                                   bd=0)
                    lbl.pack(side=tk.LEFT, padx=(8, 2))

    # ── Environments ─────────────────────────────────────────────────────

    def _show_environments(self) -> None:
        data = self.catalog["environments"]
        count = sum(len(v) for v in data.values())
        self._count_var.set(f"{len(data)} Biome, {count} Tiles")

        for biome, paths in sorted(data.items()):
            grp = tk.Frame(self._inner, bg=BG_PANEL, bd=1, relief=tk.GROOVE)
            grp.pack(fill=tk.X, padx=8, pady=4)

            display = biome.replace("_", " ").title()
            tk.Label(grp, text=display, bg=BG_PANEL, fg=FG_ACCENT,
                     font=FONT_B, anchor=tk.W).pack(fill=tk.X, padx=8, pady=(4, 2))

            row = tk.Frame(grp, bg=BG_PANEL)
            row.pack(fill=tk.X, padx=8, pady=(0, 4))

            for path in paths:
                fname = os.path.basename(path)[:-4]
                # Tile-Typ aus Dateiname
                tile_name = fname.replace(f"env_{biome}_", "")

                img = Image.open(path).convert("RGBA")
                big = img.resize((img.width * SCALE, img.height * SCALE),
                                 Image.NEAREST)
                tk_img = ImageTk.PhotoImage(big)
                self._tk_images.append(tk_img)

                cell = tk.Frame(row, bg=BG_PANEL)
                cell.pack(side=tk.LEFT, padx=2, pady=2)
                lbl = tk.Label(cell, image=tk_img, bg=BG_INPUT, bd=1,
                               relief=tk.FLAT)
                lbl.pack()
                tk.Label(cell, text=tile_name, bg=BG_PANEL, fg=FG_MUTED,
                         font=(FONT_FAMILY, 7)).pack()

    # ── Sprite-Sheets ────────────────────────────────────────────────────

    def _show_sheets(self) -> None:
        data = self.catalog["sheets"]
        self._count_var.set(f"{len(data)} Sprite-Sheets")

        for name, path in sorted(data.items()):
            grp = tk.Frame(self._inner, bg=BG_PANEL, bd=1, relief=tk.GROOVE)
            grp.pack(fill=tk.X, padx=8, pady=4)

            display = name.replace("_", " ").title()

            row = tk.Frame(grp, bg=BG_PANEL)
            row.pack(fill=tk.X, padx=8, pady=4)

            tk.Label(row, text=display, bg=BG_PANEL, fg=FG_ACCENT,
                     font=FONT_B, anchor=tk.W, width=28).pack(side=tk.LEFT)

            img = Image.open(path).convert("RGBA")
            big = img.resize((img.width * 3, img.height * 3), Image.NEAREST)
            tk_img = ImageTk.PhotoImage(big)
            self._tk_images.append(tk_img)

            lbl = tk.Label(row, image=tk_img, bg=BG_INPUT, bd=1,
                           relief=tk.FLAT)
            lbl.pack(side=tk.LEFT, padx=4)

    # ── Detail-Anzeige (rechtes Panel) ───────────────────────────────────

    def _show_detail(self, path: str, name: str, variant: int) -> None:
        # Grosses Preview (8x)
        img = Image.open(path).convert("RGBA")
        preview_scale = 8
        big = img.resize((img.width * preview_scale, img.height * preview_scale),
                         Image.NEAREST)
        tk_img = ImageTk.PhotoImage(big)
        self._tk_images.append(tk_img)
        self._preview_label.config(image=tk_img)

        # Info
        fname = os.path.basename(path)
        self._info_text.config(state=tk.NORMAL)
        self._info_text.delete("1.0", tk.END)
        self._info_text.insert(tk.END, f"{name}\n", "head")
        self._info_text.insert(tk.END, f"Variante {variant + 1}\n\n", "val")
        self._info_text.insert(tk.END, "Datei: ", "head")
        self._info_text.insert(tk.END, f"{fname}\n", "val")
        self._info_text.insert(tk.END, "Groesse: ", "head")
        self._info_text.insert(tk.END, f"{img.width}x{img.height}px\n", "val")
        self._info_text.insert(tk.END, "Skaliert: ", "head")
        self._info_text.insert(tk.END,
                               f"{img.width * preview_scale}x"
                               f"{img.height * preview_scale}px "
                               f"({preview_scale}x)\n", "val")

        # Sidecar-JSON?
        json_path = path.replace(".png", ".json")
        if os.path.exists(json_path):
            import json
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self._info_text.insert(tk.END, "\nMetadaten:\n", "head")
                for k, v in meta.items():
                    self._info_text.insert(tk.END, f"  {k}: {v}\n", "val")
            except Exception:
                pass

        self._info_text.config(state=tk.DISABLED)

    # ── Animations-Playback ──────────────────────────────────────────────

    def _play_anim(self, paths: list[str]) -> None:
        self._stop_anim()
        self._anim_frames.clear()

        for path in paths:
            img = Image.open(path).convert("RGBA")
            big = img.resize((img.width * 8, img.height * 8), Image.NEAREST)
            self._anim_frames.append(ImageTk.PhotoImage(big))

        if not self._anim_frames:
            return
        self._anim_idx = 0
        self._anim_label = self._anim_preview
        self._tick_anim()

    def _tick_anim(self) -> None:
        if not self._anim_frames or not self._anim_label:
            return
        frame = self._anim_frames[self._anim_idx % len(self._anim_frames)]
        self._anim_label.config(image=frame)
        self._anim_idx += 1
        # 3 Durchlaeufe dann stoppen
        if self._anim_idx >= len(self._anim_frames) * 3:
            return
        self._anim_after = self.root.after(ANIM_MS, self._tick_anim)

    def _stop_anim(self) -> None:
        if self._anim_after:
            self.root.after_cancel(self._anim_after)
            self._anim_after = None

    # ── Run ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# Monster-Parade: Alle Monster laufen in richtiger Groesse herum
# ══════════════════════════════════════════════════════════════════════════════

PARADE_SCALE = 3       # Skalierung fuer die Parade-Ansicht
PARADE_FPS = 8         # Frames pro Sekunde
PARADE_TICK = 1000 // PARADE_FPS
ARENA_W = 600          # Arena-Breite in Pixel (vor Skalierung)
ARENA_H = 380          # Arena-Hoehe

# Groessen-Mapping (Name → AD&D Size → Pixel)
_SIZE_KEYWORDS: dict[str, int] = {
    # G (48px)
    "red_dragon": 48, "purple_worm": 48, "drache": 48,
    # H (32px)
    "fire_giant": 32, "treant": 32, "hydra": 32, "wyvern": 32,
    "manticore": 32, "troll": 32,
    # L (24px)
    "owlbear": 24, "displacer_beast": 24, "rust_monster": 24,
    "basilisk": 24, "iron_golem": 24, "gelatinous_cube": 24,
    "carrion_crawler": 24, "oger": 24,
}
# Alles andere: 16px (M/S)


class _ParadeMonster:
    """Ein Monster das in der Arena herumlaeuft."""

    def __init__(self, name: str, frames: list["Image.Image"],
                 x: float, y: float, size_px: int) -> None:
        self.name = name
        self.frames = frames  # Walk/Idle-Frames (native Groesse)
        self.size_px = size_px
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        self.frame_idx = 0
        self.frame_timer = 0
        self.facing_right = True
        self.move_timer = 0  # Ticks bis Richtungswechsel
        # Kampf-Animationen
        self.combat_frames: dict[str, list["Image.Image"]] = {}  # "attack"/"hit"/"death" -> frames
        self.combat_state: str = ""  # "" = idle/walk, "attack"/"hit"/"death"
        self.combat_frame_idx: int = 0
        self.combat_timer: int = 0
        self.combat_cooldown: int = 0  # Ticks bis naechster Kampf moeglich

    @property
    def display_size(self) -> int:
        return self.size_px * PARADE_SCALE


class MonsterParade(tk.Frame):
    """Tab: Monster laufen in richtiger Groesse durch eine Arena."""

    def __init__(self, parent: ttk.Notebook, catalog: dict[str, Any]) -> None:
        super().__init__(parent, bg=BG_DARK)
        self._catalog = catalog
        self._monsters: list[_ParadeMonster] = []
        self._hero_frames: list["Image.Image"] = []
        self._hero_x: float = ARENA_W / 2
        self._hero_y: float = ARENA_H / 2
        self._tk_image: Any = None
        self._after_id: str | None = None
        self._running = False
        self._rng = __import__("random").Random(42)
        self._tick_count = 0

        self._build_parade_ui()
        self._load_parade_monsters()

    def _build_parade_ui(self) -> None:
        # Top-Bar
        top = tk.Frame(self, bg=BG_PANEL, height=44)
        top.pack(fill=tk.X)
        top.pack_propagate(False)

        tk.Label(top, text="  Monster-Parade  ", bg=BG_PANEL,
                 fg=FG_ACCENT, font=FONT_XL).pack(side=tk.LEFT, padx=12, pady=6)

        self._start_btn = ttk.Button(top, text="  Start  ",
                                     command=self._toggle_parade,
                                     style="Accent.TButton")
        self._start_btn.pack(side=tk.LEFT, padx=8, pady=6)

        self._info_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self._info_var, bg=BG_PANEL,
                 fg=FG_MUTED, font=FONT_S).pack(side=tk.RIGHT, padx=12)

        # Legende
        legend = tk.Frame(self, bg=BG_PANEL, height=28)
        legend.pack(fill=tk.X)
        legend.pack_propagate(False)
        sizes = [("S/M: 16px", FG_SECONDARY), ("L: 24px", YELLOW),
                 ("H: 32px", ORANGE), ("G: 48px", RED),
                 ("Humanoide Rassen", "#80c0ff"),
                 ("Kampf (bei Naehe)", "#ff6060"),
                 ("Mensch (Referenz)", GREEN)]
        for txt, col in sizes:
            tk.Label(legend, text=f"  {txt}  ", bg=BG_PANEL,
                     fg=col, font=FONT_S).pack(side=tk.LEFT, padx=4)

        # Canvas
        canvas_w = ARENA_W * PARADE_SCALE
        canvas_h = ARENA_H * PARADE_SCALE
        self._canvas = tk.Canvas(self, bg="#0a0812", highlightthickness=0,
                                 width=canvas_w, height=canvas_h)
        self._canvas.pack(padx=12, pady=8)
        self._canvas_img_id = self._canvas.create_image(0, 0, anchor=tk.NW)

        # Namens-Labels unten
        self._names_frame = tk.Frame(self, bg=BG_DARK)
        self._names_frame.pack(fill=tk.X, padx=12)

    def _load_parade_monsters(self) -> None:
        """Laedt alle Compendium-Monster + Humanoide Rassen + generierte Sprites."""
        if not HAS_PIL:
            return

        monsters_loaded = []

        # 1. Compendium-Monster (animiert, 4 Frames + Kampf)
        _combat_gen_imported = False
        try:
            from scripts.pixel_art_creator import generate_combat_frames as _gcf
            _combat_gen_imported = True
        except Exception:
            _gcf = None
        for name, paths in sorted(self._catalog.get("monsters", {}).items()):
            frames = [Image.open(p).convert("RGBA") for p in sorted(paths)]
            size_px = _SIZE_KEYWORDS.get(name, 16)
            if frames and frames[0].size[0] != size_px:
                frames = [f.resize((size_px, size_px), Image.NEAREST) for f in frames]
            combat = {}
            if _combat_gen_imported and frames:
                for anim in ("attack", "hit", "death"):
                    combat[anim] = _gcf(frames[0], anim)
            monsters_loaded.append((name, frames, size_px, combat))

        # 2. 20 Humanoide Rassen (frisch generiert, mit Walk-Animation + Kampf)
        try:
            from scripts.pixel_art_creator import (
                generate_humanoid_walk_cycle, generate_humanoid_race,
                generate_combat_frames, HUMANOID_RACES,
            )
            import random as _random
            h_rng = _random.Random(1337)
            for race_name in HUMANOID_RACES:
                frames = generate_humanoid_walk_cycle(h_rng, race_name, 16, 6)
                display = race_name.replace("_humanoid", "").replace("_", " ")
                # Kampf-Frames erzeugen
                combat = {}
                base = generate_humanoid_race(h_rng, race_name, 16)
                for anim in ("attack", "hit", "death"):
                    combat[anim] = generate_combat_frames(base, anim)
                monsters_loaded.append((f"race:{display}", frames, 16, combat))
        except Exception as e:
            print(f"[Parade] Humanoide-Rassen konnten nicht geladen werden: {e}")

        # 3. Generierte Sprites (sprite_*.png, evtl. groesser)
        gen_dir = GENERATED_DIR
        if os.path.isdir(gen_dir):
            for fname in sorted(os.listdir(gen_dir)):
                if fname.startswith("sprite_") and fname.endswith(".png"):
                    sid = fname[len("sprite_"):-len(".png")]
                    if sid.startswith("effect_"):
                        continue
                    if any(n == sid for n, _, _, *_ in monsters_loaded):
                        continue
                    fimg = Image.open(os.path.join(gen_dir, fname)).convert("RGBA")
                    size_px = fimg.size[0]
                    combat = {}
                    if _combat_gen_imported:
                        for anim in ("attack", "hit", "death"):
                            combat[anim] = _gcf(fimg, anim)
                    monsters_loaded.append((sid, [fimg], size_px, combat))

        # Referenz-Mensch laden (hero_basic.png)
        hero_path = os.path.join(
            _PROJECT_ROOT, "data", "tilesets", "0x72_dungeon_v5", "hero_basic.png")
        if os.path.exists(hero_path):
            hero_img = Image.open(hero_path).convert("RGBA")
            self._hero_frames = [hero_img]
        else:
            hero_img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            d = ImageDraw.Draw(hero_img)
            d.ellipse([5, 1, 10, 6], fill=(60, 200, 80, 255))
            d.rectangle([6, 7, 9, 11], fill=(60, 200, 80, 255))
            d.line([(6, 12), (5, 15)], fill=(60, 200, 80, 255))
            d.line([(9, 12), (10, 15)], fill=(60, 200, 80, 255))
            self._hero_frames = [hero_img]

        # Monster in Arena platzieren
        margin = 60
        for entry in monsters_loaded:
            name, frames, size_px = entry[0], entry[1], entry[2]
            combat = entry[3] if len(entry) > 3 else {}
            x = self._rng.uniform(margin, ARENA_W - margin)
            y = self._rng.uniform(margin, ARENA_H - margin)
            m = _ParadeMonster(name, frames, x, y, size_px)
            m.combat_frames = combat
            m.move_timer = self._rng.randint(10, 60)
            m.combat_cooldown = self._rng.randint(60, 200)
            self._new_direction(m)
            self._monsters.append(m)

        self._info_var.set(
            f"{len(self._monsters)} Monster + 1 Mensch (Referenz)")

        # Namens-Labels
        for w in self._names_frame.winfo_children():
            w.destroy()
        row = tk.Frame(self._names_frame, bg=BG_DARK)
        row.pack(fill=tk.X)
        per_row = 10
        for i, m in enumerate(self._monsters):
            if i > 0 and i % per_row == 0:
                row = tk.Frame(self._names_frame, bg=BG_DARK)
                row.pack(fill=tk.X)
            if m.name.startswith("race:"):
                col = "#80c0ff"  # Hellblau fuer Humanoide
                display = m.name[5:].title()
            else:
                col = FG_SECONDARY
                if m.size_px >= 48:
                    col = RED
                elif m.size_px >= 32:
                    col = ORANGE
                elif m.size_px >= 24:
                    col = YELLOW
                display = m.name.replace("_", " ").title()
            tk.Label(row, text=f" {display}({m.size_px}px) ",
                     bg=BG_DARK, fg=col, font=(FONT_FAMILY, 8)).pack(
                side=tk.LEFT, padx=1)

    def _new_direction(self, m: _ParadeMonster) -> None:
        speed = 0.4 + (16 / max(m.size_px, 16)) * 0.6  # Grosse = langsamer
        angle = self._rng.uniform(0, 2 * __import__("math").pi)
        m.vx = __import__("math").cos(angle) * speed
        m.vy = __import__("math").sin(angle) * speed
        m.facing_right = m.vx >= 0
        m.move_timer = self._rng.randint(30, 120)

    def _toggle_parade(self) -> None:
        if self._running:
            self._running = False
            if self._after_id:
                self.after_cancel(self._after_id)
                self._after_id = None
            self._start_btn.config(text="  Start  ")
        else:
            self._running = True
            self._start_btn.config(text="  Stop  ")
            self._tick_parade()

    def _tick_parade(self) -> None:
        if not self._running:
            return
        self._tick_count += 1

        margin = 10
        # Monster bewegen + Kampf-Logik
        for m in self._monsters:
            # Kampf-Cooldown runterzaehlen
            if m.combat_cooldown > 0:
                m.combat_cooldown -= 1

            # Kampf-Animation laeuft?
            if m.combat_state:
                m.combat_timer += 1
                if m.combat_timer >= 5:  # 5 Ticks pro Frame
                    m.combat_timer = 0
                    m.combat_frame_idx += 1
                    c_frames = m.combat_frames.get(m.combat_state, [])
                    if m.combat_frame_idx >= len(c_frames):
                        # Kampf-Anim fertig → zurueck zu walk
                        m.combat_state = ""
                        m.combat_frame_idx = 0
                        m.combat_timer = 0
                        m.combat_cooldown = self._rng.randint(80, 250)
                # Waehrend Kampf-Anim: nicht bewegen (ausser bei attack → leichter Lunge)
                if m.combat_state == "attack":
                    lunge = 0.3 if m.combat_frame_idx in (2, 3) else 0.0
                    m.x += lunge * (1 if m.facing_right else -1)
                continue  # Rest der Bewegungs-Logik ueberspringen

            m.x += m.vx
            m.y += m.vy

            # Rand-Kollision → abprallen
            if m.x < margin or m.x > ARENA_W - margin:
                m.vx = -m.vx
                m.x = max(margin, min(ARENA_W - margin, m.x))
                m.facing_right = m.vx >= 0
            if m.y < margin or m.y > ARENA_H - margin:
                m.vy = -m.vy
                m.y = max(margin, min(ARENA_H - margin, m.y))

            # Richtungswechsel
            m.move_timer -= 1
            if m.move_timer <= 0:
                self._new_direction(m)

            # Animation (walk/idle)
            m.frame_timer += 1
            if m.frame_timer >= 4:
                m.frame_timer = 0
                m.frame_idx = (m.frame_idx + 1) % len(m.frames)

        # Kampf-Ausloesung: Wenn zwei Monster nah genug → attack/hit
        if self._tick_count % 8 == 0:  # Nicht jeden Tick pruefen
            self._check_combat_triggers()

        # Rendern
        self._render_parade()
        self._after_id = self.after(PARADE_TICK, self._tick_parade)

    def _check_combat_triggers(self) -> None:
        """Prueft ob Monster nah genug fuer Kampf-Interaktion sind."""
        import math
        for i, a in enumerate(self._monsters):
            if a.combat_state or a.combat_cooldown > 0 or not a.combat_frames:
                continue
            for j, b in enumerate(self._monsters):
                if i == j or b.combat_state:
                    continue
                dist = math.hypot(a.x - b.x, a.y - b.y)
                trigger_dist = (a.size_px + b.size_px) * 0.8
                if dist < trigger_dist and self._rng.random() < 0.15:
                    # a greift an, b wird getroffen
                    a.combat_state = "attack"
                    a.combat_frame_idx = 0
                    a.combat_timer = 0
                    a.facing_right = b.x > a.x
                    if b.combat_frames and "hit" in b.combat_frames:
                        b.combat_state = "hit"
                        b.combat_frame_idx = 0
                        b.combat_timer = 0
                    break  # Nur ein Kampf pro Tick

    def _render_parade(self) -> None:
        if not HAS_PIL:
            return

        img = Image.new("RGBA", (ARENA_W, ARENA_H), (10, 8, 18, 255))

        # Boden-Gitter (subtil)
        draw = ImageDraw.Draw(img)
        grid_color = (25, 22, 35, 255)
        for x in range(0, ARENA_W, 16):
            draw.line([(x, 0), (x, ARENA_H)], fill=grid_color)
        for y in range(0, ARENA_H, 16):
            draw.line([(0, y), (ARENA_W, y)], fill=grid_color)

        # Referenz-Mensch (Mitte, statisch, gruen getintet)
        if self._hero_frames:
            hero = self._hero_frames[0].copy()
            # Gruen einfaerben
            px = hero.load()
            for hy in range(hero.height):
                for hx in range(hero.width):
                    r, g, b, a = px[hx, hy]
                    if a > 30:
                        px[hx, hy] = (
                            int(r * 0.3 + 60 * 0.7),
                            int(g * 0.3 + 220 * 0.7),
                            int(b * 0.3 + 80 * 0.7),
                            a,
                        )
            hx_ = int(self._hero_x) - hero.width // 2
            hy_ = int(self._hero_y) - hero.height // 2
            img.paste(hero, (hx_, hy_), hero)
            # "MENSCH" Label direkt ins Bild
            draw.rectangle(
                [hx_ - 4, hy_ + hero.height + 1,
                 hx_ + hero.width + 4, hy_ + hero.height + 8],
                fill=(10, 8, 18, 200))
            # Kein Text-Rendering in PIL ohne Font, stattdessen Punkt-Marker
            draw.rectangle(
                [int(self._hero_x) - 1, hy_ + hero.height + 2,
                 int(self._hero_x) + 1, hy_ + hero.height + 4],
                fill=(60, 220, 80, 255))

        # Monster rendern (nach Y sortiert fuer korrekte Ueberlappung)
        sorted_monsters = sorted(self._monsters, key=lambda m: m.y)
        for m in sorted_monsters:
            # Kampf-Frame oder Walk-Frame?
            if m.combat_state and m.combat_state in m.combat_frames:
                c_frames = m.combat_frames[m.combat_state]
                fidx = min(m.combat_frame_idx, len(c_frames) - 1)
                frame = c_frames[fidx]
            else:
                frame = m.frames[m.frame_idx % len(m.frames)]
            # Spiegeln wenn nach links
            if not m.facing_right:
                frame = frame.transpose(Image.FLIP_LEFT_RIGHT)
            px_ = int(m.x) - frame.width // 2
            py_ = int(m.y) - frame.height // 2
            # Sicherstellen dass Paste innerhalb des Bildes bleibt
            if (px_ + frame.width > 0 and px_ < ARENA_W
                    and py_ + frame.height > 0 and py_ < ARENA_H):
                # Clip-sicher pasten
                img.paste(frame, (px_, py_), frame)

            # Schatten unter Monster
            shadow_y = int(m.y) + frame.height // 2 - 1
            shadow_w = frame.width // 2
            shadow_x = int(m.x)
            if 0 <= shadow_y < ARENA_H:
                draw.ellipse(
                    [shadow_x - shadow_w, shadow_y,
                     shadow_x + shadow_w, shadow_y + 3],
                    fill=(0, 0, 0, 60))

        # Hochskalieren
        display = img.resize(
            (ARENA_W * PARADE_SCALE, ARENA_H * PARADE_SCALE),
            Image.NEAREST)
        self._tk_image = ImageTk.PhotoImage(display)
        self._canvas.itemconfig(self._canvas_img_id, image=self._tk_image)


def main() -> None:
    viewer = SpriteViewer()
    viewer.run()


if __name__ == "__main__":
    main()
