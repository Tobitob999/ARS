"""
scripts/anim_demo.py — ARS Pixel Animation Demo

Zeigt alle generierten Charakter-Animationen in einem tkinter-Fenster.
Laedt Einzel-Frame-PNGs aus data/tilesets/generated/ und spielt sie als
Loops ab. Skaliert 16x16 → 96x96 per Nearest-Neighbor fuer Pixel-Art-Optik.

Verwendung:
    py -3 scripts/anim_demo.py

Tastenkuerzel:
    Space  — Play All neu starten
    Escape — Beenden
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk
from typing import Optional

try:
    from PIL import Image, ImageTk
except ImportError:
    print("FEHLER: Pillow nicht installiert. pip install Pillow")
    sys.exit(1)

# ── Konstanten ────────────────────────────────────────────────────────────────

TILE_SRC = 16           # Original-Tile-Groesse in Pixeln
SCALE = 6               # Skalierungsfaktor: 16 → 96 px
TILE_DST = TILE_SRC * SCALE  # 96 px

DEFAULT_FPS = 8         # Standard-Framerate
MIN_FPS = 4
MAX_FPS = 16

# Alle moeglichen Charakter-Typen (Reihen-Reihenfolge)
ALL_SKINS = ["fighter", "mage", "rogue", "cleric", "skeleton", "orc"]

# Alle moeglichen Animationstypen (Spalten-Reihenfolge)
ALL_ANIMS = ["idle", "walk", "attack", "hit", "death", "cast"]

# Lore-Monster (nur idle-Animation, Pattern: monster_{name}_01.png)
ALL_MONSTERS = [
    "beholder", "mind_flayer", "red_dragon", "owlbear", "gelatinous_cube",
    "rust_monster", "displacer_beast", "carrion_crawler", "fire_giant", "mimic",
]

# Farben (Dark Theme)
BG_COLOR     = "#1a1a2e"   # Hintergrund Fenster
CELL_BG      = "#16213e"   # Hintergrund Zelle
LABEL_FG     = "#a0c4ff"   # Animationsname-Label
CHAR_LABEL_FG = "#ffd6a5"  # Charaktername seitlich
MISSING_FG   = "#444466"   # Farbe fuer leere Zellen
BUTTON_BG    = "#0f3460"
BUTTON_FG    = "#e0e0e0"
BUTTON_ACTIVE = "#1a5a99"
SLIDER_BG    = "#0f3460"

# Pfad zum Tileset-Verzeichnis (relativ zu diesem Skript)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
TILESET_DIR = os.path.join(PROJECT_ROOT, "data", "tilesets", "generated")


# ── Frame-Loader ──────────────────────────────────────────────────────────────

def discover_characters() -> list[str]:
    """Gibt alle Charakter-Typen zurueck, fuer die mindestens eine idle-Frame-Datei existiert."""
    found: list[str] = []
    for skin in ALL_SKINS:
        probe = os.path.join(TILESET_DIR, f"anim_{skin}_idle_01.png")
        if os.path.isfile(probe):
            found.append(skin)
    return found


def discover_monsters() -> list[str]:
    """Gibt alle Lore-Monster zurueck, fuer die Frame-Dateien existieren."""
    found: list[str] = []
    for name in ALL_MONSTERS:
        probe = os.path.join(TILESET_DIR, f"monster_{name}_01.png")
        if os.path.isfile(probe):
            found.append(name)
    return found


def load_frames(skin: str, anim: str, scale: int = SCALE) -> list[ImageTk.PhotoImage]:
    """Laedt alle Frames fuer (skin, anim) als skalierte PhotoImages."""
    frames: list[ImageTk.PhotoImage] = []
    frame_num = 1
    while True:
        path = os.path.join(TILESET_DIR, f"anim_{skin}_{anim}_{frame_num:02d}.png")
        if not os.path.isfile(path):
            break
        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize((TILE_SRC * scale, TILE_SRC * scale), Image.NEAREST)
            frames.append(ImageTk.PhotoImage(img))
        except Exception as e:
            print(f"WARNUNG: Konnte {path} nicht laden: {e}")
            break
        frame_num += 1
    return frames


def load_monster_frames(name: str, scale: int = SCALE) -> list[ImageTk.PhotoImage]:
    """Laedt alle Idle-Frames fuer ein Lore-Monster."""
    frames: list[ImageTk.PhotoImage] = []
    frame_num = 1
    while True:
        path = os.path.join(TILESET_DIR, f"monster_{name}_{frame_num:02d}.png")
        if not os.path.isfile(path):
            break
        try:
            img = Image.open(path).convert("RGBA")
            img = img.resize((TILE_SRC * scale, TILE_SRC * scale), Image.NEAREST)
            frames.append(ImageTk.PhotoImage(img))
        except Exception as e:
            print(f"WARNUNG: Konnte {path} nicht laden: {e}")
            break
        frame_num += 1
    return frames


# ── AnimCell: Einzelne animierte Zelle ───────────────────────────────────────

class AnimCell(tk.Frame):
    """
    Eine Zelle im Grid: zeigt Animationsname + animiertes Sprite.
    Handhabt eigenstaendiges Timing ueber after()-Callbacks.
    """

    def __init__(
        self,
        parent: tk.Widget,
        skin: str,
        anim: str,
        fps: int = DEFAULT_FPS,
        **kwargs,
    ) -> None:
        super().__init__(parent, bg=CELL_BG, bd=1, relief="flat", **kwargs)
        self.skin = skin
        self.anim = anim
        self._fps = fps
        self._frame_idx = 0
        self._frames: list[ImageTk.PhotoImage] = []
        self._after_id: Optional[str] = None

        # Label: Animationsname
        self._name_label = tk.Label(
            self,
            text=anim,
            fg=LABEL_FG,
            bg=CELL_BG,
            font=("Consolas", 8, "bold"),
            pady=2,
        )
        self._name_label.pack(side=tk.TOP)

        # Canvas: Sprite-Anzeige
        self._canvas = tk.Canvas(
            self,
            width=TILE_DST,
            height=TILE_DST,
            bg=CELL_BG,
            highlightthickness=0,
        )
        self._canvas.pack(side=tk.TOP, padx=4, pady=4)
        self._canvas_img_id: Optional[int] = None

        # Frames laden
        self._frames = (load_monster_frames(skin) if anim == "__monster__"
                        else load_frames(skin, anim))
        if not self._frames:
            self._show_missing()
        else:
            self._show_frame(0)

    def _show_missing(self) -> None:
        """Zeigt Platzhalter fuer fehlende Animation."""
        self._canvas.create_text(
            TILE_DST // 2,
            TILE_DST // 2,
            text="—",
            fill=MISSING_FG,
            font=("Consolas", 18),
        )
        self._name_label.configure(fg=MISSING_FG)

    def _show_frame(self, idx: int) -> None:
        """Rendert einen Frame auf den Canvas."""
        if not self._frames:
            return
        photo = self._frames[idx]
        if self._canvas_img_id is None:
            self._canvas_img_id = self._canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        else:
            self._canvas.itemconfigure(self._canvas_img_id, image=photo)

    def start(self, restart: bool = False) -> None:
        """Startet (oder startet neu) die Animations-Schleife."""
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        if not self._frames:
            return
        if restart:
            self._frame_idx = 0
            self._show_frame(0)
        self._tick()

    def stop(self) -> None:
        """Stoppt die Animation."""
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _tick(self) -> None:
        """Naechster Frame-Tick."""
        if not self._frames:
            return
        self._frame_idx = (self._frame_idx + 1) % len(self._frames)
        self._show_frame(self._frame_idx)
        delay_ms = max(1, 1000 // self._fps)
        self._after_id = self.after(delay_ms, self._tick)

    def set_fps(self, fps: int) -> None:
        """Aktualisiert die Framerate."""
        self._fps = max(MIN_FPS, min(MAX_FPS, fps))

    @property
    def has_frames(self) -> bool:
        return bool(self._frames)


# ── Hauptfenster ─────────────────────────────────────────────────────────────

class AnimDemoApp(tk.Tk):
    """Hauptfenster der Animation Demo."""

    def __init__(self) -> None:
        super().__init__()
        self.title("ARS Pixel Animation Demo")
        self.configure(bg=BG_COLOR)
        self.resizable(True, True)

        # Gefundene Charaktere und Monster ermitteln
        self._skins = discover_characters()
        self._monsters = discover_monsters()
        if not self._skins and not self._monsters:
            self._show_no_assets()
            return

        # Alle AnimCell-Widgets (skin -> anim -> cell)
        self._cells: dict[str, dict[str, AnimCell]] = {}
        self._fps = DEFAULT_FPS

        self._build_ui()
        self._start_all(restart=False)

        # Tastenkuerzel
        self.bind("<space>", lambda _e: self._on_play_all())
        self.bind("<Escape>", lambda _e: self.destroy())

        # Fenster mittig positionieren
        self.update_idletasks()
        self._center_window()

    def _center_window(self) -> None:
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _show_no_assets(self) -> None:
        """Zeigt Fehlermeldung wenn keine Assets gefunden wurden."""
        msg = (
            f"Keine Animations-Assets gefunden in:\n{TILESET_DIR}\n\n"
            "Bitte zuerst pixel_art_creator.py ausfuehren:\n"
            "  py -3 scripts/pixel_art_creator.py --category animations"
        )
        tk.Label(
            self,
            text=msg,
            fg="#ff6b6b",
            bg=BG_COLOR,
            font=("Consolas", 10),
            justify=tk.LEFT,
            padx=20,
            pady=20,
        ).pack()

    def _build_ui(self) -> None:
        """Baut das komplette UI auf."""
        # ── Titelzeile ──
        title_frame = tk.Frame(self, bg=BG_COLOR)
        title_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 4))

        tk.Label(
            title_frame,
            text="ARS Pixel Animation Demo",
            fg="#e0e0ff",
            bg=BG_COLOR,
            font=("Consolas", 14, "bold"),
        ).pack(side=tk.LEFT, padx=8)

        # Charakteranzahl-Info
        info_txt = f"{len(self._skins)} Chars | {len(self._monsters)} Monster | 16x16 @ {SCALE}x"
        tk.Label(
            title_frame,
            text=info_txt,
            fg="#7878aa",
            bg=BG_COLOR,
            font=("Consolas", 9),
        ).pack(side=tk.LEFT, padx=16)

        # ── Steuerleiste ──
        ctrl_frame = tk.Frame(self, bg=BG_COLOR)
        ctrl_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 8))

        play_btn = tk.Button(
            ctrl_frame,
            text="Play All  [Space]",
            command=self._on_play_all,
            bg=BUTTON_BG,
            fg=BUTTON_FG,
            activebackground=BUTTON_ACTIVE,
            activeforeground=BUTTON_FG,
            font=("Consolas", 9, "bold"),
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=4,
        )
        play_btn.pack(side=tk.LEFT, padx=(0, 16))

        tk.Label(
            ctrl_frame,
            text="FPS:",
            fg=LABEL_FG,
            bg=BG_COLOR,
            font=("Consolas", 9),
        ).pack(side=tk.LEFT)

        self._fps_var = tk.IntVar(value=DEFAULT_FPS)
        self._fps_display = tk.Label(
            ctrl_frame,
            text=f"{DEFAULT_FPS:2d}",
            fg=LABEL_FG,
            bg=BG_COLOR,
            font=("Consolas", 9, "bold"),
            width=3,
        )
        self._fps_display.pack(side=tk.LEFT, padx=(4, 0))

        fps_slider = tk.Scale(
            ctrl_frame,
            from_=MIN_FPS,
            to=MAX_FPS,
            orient=tk.HORIZONTAL,
            variable=self._fps_var,
            command=self._on_fps_change,
            bg=BG_COLOR,
            fg=LABEL_FG,
            troughcolor=SLIDER_BG,
            highlightthickness=0,
            showvalue=False,
            length=160,
            sliderlength=16,
        )
        fps_slider.pack(side=tk.LEFT, padx=4)

        tk.Label(
            ctrl_frame,
            text=f"({MIN_FPS}–{MAX_FPS})",
            fg="#555577",
            bg=BG_COLOR,
            font=("Consolas", 8),
        ).pack(side=tk.LEFT, padx=2)

        # ── Grid-Bereich mit Scrollbar ──
        outer = tk.Frame(self, bg=BG_COLOR)
        outer.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        canvas_scroll = tk.Canvas(outer, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas_scroll.yview)
        canvas_scroll.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas_scroll.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._grid_frame = tk.Frame(canvas_scroll, bg=BG_COLOR)
        canvas_win = canvas_scroll.create_window((0, 0), window=self._grid_frame, anchor=tk.NW)

        def _on_frame_configure(event):
            canvas_scroll.configure(scrollregion=canvas_scroll.bbox("all"))
        self._grid_frame.bind("<Configure>", _on_frame_configure)

        def _on_canvas_configure(event):
            canvas_scroll.itemconfig(canvas_win, width=event.width)
        canvas_scroll.bind("<Configure>", _on_canvas_configure)

        # Mausrad-Scroll
        def _on_mousewheel(event):
            canvas_scroll.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas_scroll.bind("<MouseWheel>", _on_mousewheel)

        self._build_grid()

    def _build_grid(self) -> None:
        """Baut das Animations-Grid auf."""
        frame = self._grid_frame
        CELL_PAD_X = 3
        CELL_PAD_Y = 3
        cur_row = 0

        # ══ CHARAKTER-SEKTION ══
        if self._skins:
            # Sektions-Titel
            sec_lbl = tk.Label(
                frame, text="-- CHARAKTERE --", fg="#8888bb", bg=BG_COLOR,
                font=("Consolas", 10, "bold"),
            )
            sec_lbl.grid(row=cur_row, column=0, columnspan=len(ALL_ANIMS) + 1,
                         padx=CELL_PAD_X, pady=(4, 2), sticky=tk.W)
            cur_row += 1

            # Kopfzeile: Animationsname-Spalten
            corner = tk.Label(frame, text="", bg=BG_COLOR, width=10)
            corner.grid(row=cur_row, column=0, padx=CELL_PAD_X, pady=CELL_PAD_Y)

            for col_idx, anim in enumerate(ALL_ANIMS):
                lbl = tk.Label(
                    frame, text=anim.upper(), fg="#c0c0e0", bg=BG_COLOR,
                    font=("Consolas", 9, "bold"), width=12,
                )
                lbl.grid(row=cur_row, column=col_idx + 1, padx=CELL_PAD_X, pady=(4, 2))
            cur_row += 1

            # Zeilen: Charaktere
            for skin in self._skins:
                self._cells[skin] = {}

                row_lbl = tk.Label(
                    frame, text=skin.upper(), fg=CHAR_LABEL_FG, bg=BG_COLOR,
                    font=("Consolas", 9, "bold"), anchor=tk.E, width=10,
                )
                row_lbl.grid(row=cur_row, column=0, padx=(8, 4), pady=CELL_PAD_Y, sticky=tk.E)

                for col_idx, anim in enumerate(ALL_ANIMS):
                    cell = AnimCell(frame, skin=skin, anim=anim, fps=self._fps)
                    cell.grid(row=cur_row, column=col_idx + 1,
                              padx=CELL_PAD_X, pady=CELL_PAD_Y, sticky=tk.NSEW)
                    self._cells[skin][anim] = cell
                cur_row += 1

        # ══ MONSTER-SEKTION ══
        if self._monsters:
            # Trennlinie
            sep = tk.Frame(frame, height=2, bg="#4a3a5a")
            sep.grid(row=cur_row, column=0, columnspan=len(ALL_ANIMS) + 1,
                     sticky=tk.EW, pady=8)
            cur_row += 1

            sec_lbl = tk.Label(
                frame, text="-- LORE MONSTER --", fg="#bb8888", bg=BG_COLOR,
                font=("Consolas", 10, "bold"),
            )
            sec_lbl.grid(row=cur_row, column=0, columnspan=len(ALL_ANIMS) + 1,
                         padx=CELL_PAD_X, pady=(4, 2), sticky=tk.W)
            cur_row += 1

            # Monster in Reihen zu je 5
            MONSTERS_PER_ROW = 5
            for i, mon_name in enumerate(self._monsters):
                col = i % MONSTERS_PER_ROW
                if col == 0 and i > 0:
                    cur_row += 1

                cell = AnimCell(
                    frame, skin=mon_name, anim="__monster__", fps=self._fps,
                )
                cell.grid(row=cur_row, column=col + 1,
                          padx=CELL_PAD_X, pady=CELL_PAD_Y, sticky=tk.NSEW)

                # Name als Label in der Zelle aktualisieren
                display_name = mon_name.replace("_", " ").title()
                cell._name_label.configure(text=display_name, fg="#dd9999")

                self._cells.setdefault(mon_name, {})["__monster__"] = cell

            cur_row += 1

    def _start_all(self, restart: bool = True) -> None:
        """Startet alle AnimCells (optional: Neustart von Frame 0)."""
        for anim_dict in self._cells.values():
            for cell in anim_dict.values():
                cell.start(restart=restart)

    def _on_play_all(self) -> None:
        """Play-All-Button: alle Animationen von Frame 0 neu starten."""
        self._start_all(restart=True)

    def _on_fps_change(self, value: str) -> None:
        """Slider-Callback: FPS aendern."""
        fps = int(float(value))
        self._fps = fps
        self._fps_display.configure(text=f"{fps:2d}")
        for anim_dict in self._cells.values():
            for cell in anim_dict.values():
                cell.set_fps(fps)

    def run(self) -> None:
        """Startet die tkinter-Hauptschleife."""
        self.mainloop()


# ── Einstiegspunkt ────────────────────────────────────────────────────────────

def main() -> None:
    if not os.path.isdir(TILESET_DIR):
        print(f"FEHLER: Tileset-Verzeichnis nicht gefunden: {TILESET_DIR}")
        sys.exit(1)

    app = AnimDemoApp()
    app.run()


if __name__ == "__main__":
    main()
