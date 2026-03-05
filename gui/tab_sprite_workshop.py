"""
gui/tab_sprite_workshop.py — Sprite-Werkstatt Tab

GUI-gesteuerte Varianten-Generierung mit Queue:
- Konfigurator fuer Kategorie, Typ, Koerperbau, Farbe
- Queue-basierte Batch-Erzeugung
- Vorschau-Galerie mit Auswahl
- Uebernahme nach data/tilesets/generated/
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, simpledialog, filedialog
from typing import TYPE_CHECKING

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

if TYPE_CHECKING:
    from gui.tech_gui import TechGUI

# Mapping: GUI-Label → interner Key
BODY_LABELS = {
    "Normal": "normal",
    "Schlank": "slim",
    "Kraeftig": "stocky",
    "Gross": "tall",
    "Klein": "tiny",
    "Bullig": "bulky",
}

COLOR_LABELS = {
    "Normal": "normal",
    "Hell": "bright",
    "Dunkel": "dark",
    "Blass": "pale",
    "Leuchtend": "vivid",
}

ANIM_LABELS = {
    "Leerlauf": "idle",
    "Gehen": "walk",
    "Angriff": "attack",
    "Treffer": "hit",
    "Tod": "death",
    "Zauber": "cast",
    "Stolpern": "stumble",
    "Jubeln": "celebrate",
    "Schleichen": "sneak",
    "Provozieren": "taunt",
    "Ausweichen": "dodge",
    "Zittern": "shiver",
    "Verbeugung": "bow",
    "Lachen": "laugh",
}

CATEGORY_TYPES = {
    "Monster": [
        "undead_humanoid", "undead_blob", "demon_humanoid", "demon_tall",
        "beast_beast", "beast_flying", "elemental_blob", "elemental_tall",
        "insect_beast", "insect_flying", "arcane_humanoid", "arcane_blob",
    ],
    "Charakter": [
        "fighter", "mage", "rogue", "cleric", "skeleton", "orc",
    ],
    "Umgebung": [
        "dungeon", "cave", "crypt", "forest", "swamp", "river",
        "beach", "volcano", "ice", "desert", "temple", "sewer", "mine", "underdark",
    ],
    "Animation": [
        "fighter", "mage", "rogue", "cleric", "skeleton", "orc",
        "undead_humanoid", "undead_blob", "demon_humanoid", "demon_tall",
        "beast_beast", "beast_flying", "elemental_blob", "elemental_tall",
        "insect_beast", "insect_flying", "arcane_humanoid", "arcane_blob",
    ],
    "Bild\u2192Sprite": [
        "fighter", "mage", "rogue", "cleric", "skeleton", "orc",
    ],
}

CATEGORY_MAP = {
    "Monster": "monsters",
    "Charakter": "characters",
    "Umgebung": "environments",
    "Animation": "animations",
    "Bild\u2192Sprite": "image_sprite",
}


class SpriteWorkshopTab(ttk.Frame):
    """Tab 'Sprite-Werkstatt' — Varianten-Generator mit Vorschau-Galerie."""

    def __init__(self, parent: ttk.Notebook, gui: "TechGUI"):
        super().__init__(parent)
        self.gui = gui
        self._gen_queue: queue.Queue = queue.Queue()
        self._result_queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._polling = False
        self._total_jobs = 0
        self._done_jobs = 0

        # Galerie-Daten: [(name, pil_img, tk_photo, params, selected)]
        self._gallery: list[dict] = []

        # Bild→Sprite State
        self._ref_image_path: str | None = None
        self._ref_tk_photo = None  # Haelt Referenz fuer GC
        self._last_analysis: dict | None = None
        self._api_calls = 0
        self._api_tokens = 0

        self._build_ui()
        self._anim_timer_id = None
        # Mausrad-Binding fuer alle Kinder im linken Panel
        self._bind_wheel_recursive(self._left_frame, self._left_canvas)

    def _build_ui(self):
        """Baut die komplette UI auf."""
        # Hauptsplitter: Links=Konfigurator, Rechts=Galerie
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ── Linkes Panel: Konfigurator (scrollbar) ──
        left_outer = ttk.Frame(paned, width=220)
        paned.add(left_outer, weight=0)

        left_canvas = tk.Canvas(left_outer, width=210, highlightthickness=0)
        left_scroll = ttk.Scrollbar(left_outer, orient=tk.VERTICAL, command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        left = ttk.Frame(left_canvas)
        left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda e: left_canvas.configure(
            scrollregion=left_canvas.bbox("all")))
        # Mausrad im linken Panel
        def _on_left_wheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        left_canvas.bind("<MouseWheel>", _on_left_wheel)
        left.bind("<MouseWheel>", _on_left_wheel)
        self._left_canvas = left_canvas
        self._left_frame = left

        row = 0
        ttk.Label(left, text="SPRITE-WERKSTATT", font=("", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 10))
        row += 1

        # Kategorie
        ttk.Label(left, text="Kategorie:").grid(row=row, column=0, sticky="w", padx=6)
        row += 1
        self._cat_var = tk.StringVar(value="Monster")
        for cat in ("Monster", "Charakter", "Umgebung", "Animation", "Bild\u2192Sprite"):
            ttk.Radiobutton(left, text=cat, variable=self._cat_var, value=cat,
                            command=self._on_category_change).grid(
                row=row, column=0, sticky="w", padx=20)
            row += 1

        # Typ-Dropdown
        ttk.Label(left, text="Typ:").grid(row=row, column=0, sticky="w", padx=6, pady=(6, 0))
        row += 1
        self._type_var = tk.StringVar()
        self._type_combo = ttk.Combobox(left, textvariable=self._type_var, state="readonly", width=22)
        self._type_combo.grid(row=row, column=0, sticky="ew", padx=6)
        row += 1
        self._on_category_change()

        # Koerperbau-Checkbuttons
        ttk.Label(left, text="Koerperbau:").grid(row=row, column=0, sticky="w", padx=6, pady=(8, 0))
        row += 1
        self._body_vars: dict[str, tk.BooleanVar] = {}
        for label in BODY_LABELS:
            var = tk.BooleanVar(value=True)
            self._body_vars[label] = var
            ttk.Checkbutton(left, text=label, variable=var).grid(
                row=row, column=0, sticky="w", padx=20)
            row += 1

        # Farb-Checkbuttons
        ttk.Label(left, text="Farbe:").grid(row=row, column=0, sticky="w", padx=6, pady=(8, 0))
        row += 1
        self._color_vars: dict[str, tk.BooleanVar] = {}
        for label in COLOR_LABELS:
            var = tk.BooleanVar(value=True)
            self._color_vars[label] = var
            ttk.Checkbutton(left, text=label, variable=var).grid(
                row=row, column=0, sticky="w", padx=20)
            row += 1

        # Seed
        ttk.Label(left, text="Seed:").grid(row=row, column=0, sticky="w", padx=6, pady=(8, 0))
        row += 1
        self._seed_var = tk.IntVar(value=42)
        ttk.Entry(left, textvariable=self._seed_var, width=10).grid(
            row=row, column=0, sticky="w", padx=6)
        row += 1

        # Animations-Sequenz (nur bei Kategorie "Animation")
        self._anim_frame = ttk.LabelFrame(left, text="Sequenz:")
        self._anim_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(6, 0))
        row += 1
        self._anim_vars: dict[str, tk.BooleanVar] = {}
        for label, key in ANIM_LABELS.items():
            var = tk.BooleanVar(value=(key in ("idle", "stumble", "celebrate")))
            self._anim_vars[label] = var
            ttk.Checkbutton(self._anim_frame, text=label, variable=var).pack(
                anchor="w", padx=10)
        self._anim_frame.grid_remove()  # Initial versteckt

        # ── Varianz-Slider (nur bei Animation sichtbar) ──
        self._variance_frame = ttk.LabelFrame(left, text="Varianz:")
        self._variance_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(6, 0))
        row += 1

        self._amplitude_var = tk.DoubleVar(value=1.0)
        self._chaos_var = tk.DoubleVar(value=0.0)
        self._jitter_var = tk.DoubleVar(value=0)
        self._noise_var = tk.DoubleVar(value=0.0)

        sliders = [
            ("Amplitude", self._amplitude_var, 0.1, 3.0, 0.1),
            ("Chaos", self._chaos_var, 0.0, 5.0, 0.1),
            ("Farb-Jitter", self._jitter_var, 0, 50, 1),
            ("Pixel-Rauschen", self._noise_var, 0.0, 1.0, 0.05),
        ]
        self._slider_value_labels: list[ttk.Label] = []
        for s_idx, (label, var, from_, to_, res) in enumerate(sliders):
            sf = ttk.Frame(self._variance_frame)
            sf.pack(fill=tk.X, padx=4, pady=1)
            ttk.Label(sf, text=label, width=13, anchor="w").pack(side=tk.LEFT)
            val_lbl = ttk.Label(sf, text=str(var.get()), width=5, anchor="e")
            val_lbl.pack(side=tk.RIGHT)
            self._slider_value_labels.append(val_lbl)
            scale = ttk.Scale(sf, orient=tk.HORIZONTAL, length=140,
                              from_=from_, to=to_, variable=var,
                              command=lambda v, lbl=val_lbl, r=res: lbl.config(
                                  text=f"{round(float(v) / r) * r:.2g}"))
            scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Tag-Eingabe im Varianz-Frame
        tag_f = ttk.Frame(self._variance_frame)
        tag_f.pack(fill=tk.X, padx=4, pady=(4, 2))
        ttk.Label(tag_f, text="Tag:", width=5, anchor="w").pack(side=tk.LEFT)
        self._tag_var = tk.StringVar()
        ttk.Entry(tag_f, textvariable=self._tag_var, width=16).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._variance_frame.grid_remove()  # Initial versteckt

        # ── Referenzbild-Frame (nur bei Bild→Sprite sichtbar) ──
        self._ref_frame = ttk.LabelFrame(left, text="Referenzbild:")
        self._ref_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(6, 0))
        row += 1

        ttk.Button(self._ref_frame, text="Bild laden...",
                   command=self._load_reference_image).pack(fill=tk.X, padx=4, pady=2)
        self._ref_img_label = tk.Label(self._ref_frame, bg="#2a2a2a",
                                        width=64, height=64)
        self._ref_img_label.pack(padx=4, pady=2)
        self._ref_path_label = ttk.Label(self._ref_frame, text="(kein Bild)", font=("", 7),
                                          wraplength=180)
        self._ref_path_label.pack(padx=4, pady=(0, 2))
        self._api_label = ttk.Label(self._ref_frame, text="API: 0 Calls / 0 Tokens",
                                     font=("", 7))
        self._api_label.pack(padx=4, pady=(0, 4))
        self._ref_frame.grid_remove()  # Initial versteckt

        # Pro Kombination
        ttk.Label(left, text="Pro Kombination:").grid(row=row, column=0, sticky="w", padx=6, pady=(4, 0))
        row += 1
        self._count_var = tk.IntVar(value=1)
        ttk.Spinbox(left, from_=1, to=5, textvariable=self._count_var, width=5).grid(
            row=row, column=0, sticky="w", padx=6)
        row += 1

        # Buttons
        btn_frame = ttk.Frame(left)
        btn_frame.grid(row=row, column=0, sticky="ew", padx=6, pady=(10, 2))
        row += 1

        ttk.Button(btn_frame, text="\u25b6 Generieren", command=self._start_generation).pack(
            fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="\u2713 Uebernehmen", command=self._adopt_selected).pack(
            fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="Tag setzen", command=self._set_tag_on_selected).pack(
            fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="Alle markieren", command=self._select_all).pack(
            fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="Batch: Tag exportieren", command=self._batch_export_tag).pack(
            fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="\u2717 Loeschen", command=self._delete_selected).pack(
            fill=tk.X, pady=2)

        # ── Rechtes Panel: Galerie + Statusbar ──
        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        # Scrollable Canvas fuer Galerie
        gallery_frame = ttk.Frame(right)
        gallery_frame.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(gallery_frame, bg="#2a2a2a", highlightthickness=0)
        scrollbar = ttk.Scrollbar(gallery_frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner_frame = ttk.Frame(self._canvas)
        self._canvas_window = self._canvas.create_window((0, 0), window=self._inner_frame, anchor="nw")

        self._inner_frame.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Statusbar unten
        status_frame = ttk.Frame(right)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=4, pady=4)

        self._progress_var = tk.DoubleVar(value=0)
        self._progress = ttk.Progressbar(status_frame, variable=self._progress_var, maximum=100)
        self._progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self._status_label = ttk.Label(status_frame, text="Bereit")
        self._status_label.pack(side=tk.RIGHT)

    def _bind_wheel_recursive(self, widget, canvas):
        """Bindet Mausrad-Scrolling an alle Kinder eines Widgets."""
        def _scroll(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        widget.bind("<MouseWheel>", _scroll)
        for child in widget.winfo_children():
            self._bind_wheel_recursive(child, canvas)

    def _on_canvas_resize(self, event):
        """Canvas-Breite an Frame anpassen."""
        self._canvas.itemconfig(self._canvas_window, width=event.width)
        self._relayout_gallery()

    def _on_mousewheel(self, event):
        """Mausrad-Scrolling."""
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_category_change(self):
        """Aktualisiert Typ-Dropdown bei Kategorie-Wechsel."""
        cat = self._cat_var.get()
        is_img = (cat == "Bild\u2192Sprite")
        is_anim = (cat == "Animation")
        types = CATEGORY_TYPES.get(cat, [])
        self._type_combo["values"] = types
        if types:
            self._type_var.set(types[0])
        # Sequenz- und Varianz-Auswahl bei Animation oder Bild→Sprite sichtbar
        if hasattr(self, "_anim_frame"):
            if is_anim or is_img:
                self._anim_frame.grid()
            else:
                self._anim_frame.grid_remove()
        if hasattr(self, "_variance_frame"):
            if is_anim or is_img:
                self._variance_frame.grid()
            else:
                self._variance_frame.grid_remove()
        # Referenzbild-Frame nur bei Bild→Sprite
        if hasattr(self, "_ref_frame"):
            if is_img:
                self._ref_frame.grid()
            else:
                self._ref_frame.grid_remove()

    def _load_reference_image(self):
        """Oeffnet Dateidialog und laedt ein Referenzbild fuer Bild→Sprite."""
        path = filedialog.askopenfilename(
            title="Referenzbild waehlen",
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.bmp *.webp")],
        )
        if not path:
            return
        self._ref_image_path = path
        self._last_analysis = None  # Cache invalidieren
        # Vorschau anzeigen (64x64 Thumbnail)
        try:
            img = Image.open(path)
            img.thumbnail((64, 64), Image.LANCZOS)
            self._ref_tk_photo = ImageTk.PhotoImage(img)
            self._ref_img_label.config(image=self._ref_tk_photo)
        except Exception:
            self._ref_img_label.config(image="")
        # Pfad-Label (abgekuerzt)
        display = os.path.basename(path)
        if len(display) > 30:
            display = "..." + display[-27:]
        self._ref_path_label.config(text=display)

    def _start_generation(self):
        """Baut Auftrags-Queue auf und startet Worker."""
        # Laufenden Worker stoppen
        if self._worker and self._worker.is_alive():
            self._gen_queue.put(None)  # Poison pill
            self._worker.join(timeout=2)

        # Queue leeren
        while not self._gen_queue.empty():
            try:
                self._gen_queue.get_nowait()
            except queue.Empty:
                break
        while not self._result_queue.empty():
            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                break

        # Galerie leeren
        self._gallery.clear()
        for widget in self._inner_frame.winfo_children():
            widget.destroy()

        cat = self._cat_var.get()
        sub_type = self._type_var.get()
        seed = self._seed_var.get()
        count = self._count_var.get()
        category = CATEGORY_MAP.get(cat, "monsters")

        # Gewaehlte Modifikatoren
        body_mods = [BODY_LABELS[k] for k, v in self._body_vars.items() if v.get()]
        color_mods = [COLOR_LABELS[k] for k, v in self._color_vars.items() if v.get()]

        if not body_mods:
            body_mods = ["normal"]
        if not color_mods:
            color_mods = ["normal"]

        # Jobs aufbauen
        jobs = []
        variant_idx = 0

        if category == "image_sprite":
            # Bild→Sprite: Referenzbild erforderlich
            if not self._ref_image_path:
                self._status_label.config(text="Kein Referenzbild geladen!")
                return
            amp = self._amplitude_var.get()
            chaos = self._chaos_var.get()
            jitter = int(self._jitter_var.get())
            noise = self._noise_var.get()
            # Gewaehlte Animations-Sequenzen (optional)
            anim_keys = [ANIM_LABELS[k] for k, v in self._anim_vars.items() if v.get()]
            if anim_keys:
                # Animierte Bild-Sprites
                for anim_key in anim_keys:
                    for i in range(count):
                        jobs.append({
                            "_image_sprite": True,
                            "_image_path": self._ref_image_path,
                            "anim_name": anim_key,
                            "seed": seed,
                            "variant_idx": variant_idx,
                            "amplitude": amp,
                            "chaos": chaos,
                            "color_jitter": jitter,
                            "pixel_noise": noise,
                        })
                        variant_idx += 1
            else:
                # Statische Bild-Sprites
                for i in range(count):
                    jobs.append({
                        "_image_sprite": True,
                        "_image_path": self._ref_image_path,
                        "seed": seed,
                        "variant_idx": variant_idx,
                        "amplitude": amp,
                        "chaos": chaos,
                        "color_jitter": jitter,
                        "pixel_noise": noise,
                    })
                    variant_idx += 1
        elif category == "animations":
            # Slider-Werte auslesen
            amp = self._amplitude_var.get()
            chaos = self._chaos_var.get()
            jitter = int(self._jitter_var.get())
            noise = self._noise_var.get()
            # Gewaehlte Animations-Sequenzen
            anim_keys = [ANIM_LABELS[k] for k, v in self._anim_vars.items() if v.get()]
            if not anim_keys:
                anim_keys = ["idle"]
            for anim_key in anim_keys:
                for bm in body_mods:
                    for cm in color_mods:
                        for i in range(count):
                            jobs.append({
                                "sub_type": sub_type,
                                "anim_name": anim_key,
                                "body_mod": bm,
                                "color_mod": cm,
                                "seed": seed,
                                "variant_idx": variant_idx,
                                "amplitude": amp,
                                "chaos": chaos,
                                "color_jitter": jitter,
                                "pixel_noise": noise,
                            })
                            variant_idx += 1
        else:
            for bm in body_mods:
                for cm in color_mods:
                    for i in range(count):
                        jobs.append({
                            "category": category,
                            "sub_type": sub_type,
                            "body_mod": bm,
                            "color_mod": cm,
                            "seed": seed,
                            "variant_idx": variant_idx,
                        })
                        variant_idx += 1

        self._total_jobs = len(jobs)
        self._done_jobs = 0
        self._progress_var.set(0)
        self._status_label.config(text=f"Queue: 0/{self._total_jobs}")

        for job in jobs:
            self._gen_queue.put(job)

        # Worker starten
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        # Polling starten
        if not self._polling:
            self._polling = True
            self._poll_results()

    def _worker_loop(self):
        """Arbeitet die Queue ab (laeuft im Hintergrund)."""
        try:
            from scripts.pixel_art_creator import generate_single_variant, generate_animated_variant
        except ImportError:
            return

        # Bild→Sprite: Analyse-Cache und API-Key
        image_analysis_cache: dict[str, dict] = {}

        while True:
            try:
                params = self._gen_queue.get(timeout=1)
            except queue.Empty:
                continue
            if params is None:
                break
            try:
                if params.get("_image_sprite"):
                    # Bild→Sprite Job
                    image_path = params.pop("_image_path")
                    params.pop("_image_sprite")
                    anim_name = params.pop("anim_name", None)

                    # Analyse einmalig pro Bildpfad (gecacht)
                    if image_path not in image_analysis_cache:
                        try:
                            from scripts.sprite_from_image import analyze_image_for_sprite
                            import dotenv
                            env = dotenv.dotenv_values()
                            api_key = env.get("GEMINI_API_KEY", "")
                            if not api_key:
                                import os as _os
                                api_key = _os.environ.get("GEMINI_API_KEY", "")
                            analysis = analyze_image_for_sprite(image_path, api_key)
                            image_analysis_cache[image_path] = analysis
                            self._api_calls += 1
                            self._api_tokens += analysis.get("token_count", 0)
                        except Exception as exc:
                            self._result_queue.put((
                                f"error_analysis", None,
                                {"error": f"Bild-Analyse fehlgeschlagen: {exc}"}
                            ))
                            continue
                    analysis = image_analysis_cache[image_path]

                    if anim_name:
                        # Animierter Bild-Sprite
                        from scripts.sprite_from_image import _build_char_def
                        char_def = _build_char_def(analysis)
                        name, frames, meta = generate_animated_variant(
                            sub_type=analysis["char_type"],
                            anim_name=anim_name,
                            body_mod=analysis.get("body_mod", "normal"),
                            color_mod=analysis.get("color_mod", "normal"),
                            custom_char_def=char_def,
                            **params,
                        )
                        meta["source"] = "image_analysis"
                        meta["description"] = analysis.get("description", "")
                        self._result_queue.put((name, frames, meta))
                    else:
                        # Statischer Bild-Sprite
                        from scripts.sprite_from_image import generate_sprite_from_analysis
                        name, img, meta = generate_sprite_from_analysis(analysis, **params)
                        self._result_queue.put((name, img, meta))
                elif "anim_name" in params:
                    name, frames, meta = generate_animated_variant(**params)
                    self._result_queue.put((name, frames, meta))
                else:
                    name, img, meta = generate_single_variant(**params)
                    self._result_queue.put((name, img, meta))
            except Exception as e:
                self._result_queue.put((f"error_{params.get('variant_idx', 0)}", None, {"error": str(e)}))

    def _poll_results(self):
        """Pollt die Result-Queue und fuegt Thumbnails ein (50ms-Intervall)."""
        last_meta: dict = {}
        batch = 0
        while batch < 5:  # Max 5 pro Poll-Zyklus
            try:
                name, img, meta = self._result_queue.get_nowait()
                self._done_jobs += 1
                last_meta = meta
                if isinstance(img, list):
                    self._add_animated_thumbnail(name, img, meta)
                elif img is not None:
                    self._add_thumbnail(name, img, meta)
                batch += 1
            except queue.Empty:
                break

        # Fortschritt aktualisieren
        if self._total_jobs > 0:
            pct = (self._done_jobs / self._total_jobs) * 100
            self._progress_var.set(pct)
            bm = last_meta.get("body_mod", "") if last_meta else ""
            cm = last_meta.get("color_mod", "") if last_meta else ""
            if self._done_jobs < self._total_jobs:
                self._status_label.config(text=f"Queue: {self._done_jobs}/{self._total_jobs}  {bm}/{cm}")
            else:
                self._status_label.config(text=f"Fertig: {self._total_jobs} Sprites generiert")

        # API-Budget aktualisieren
        if hasattr(self, "_api_label"):
            self._api_label.config(text=f"API: {self._api_calls} Calls / {self._api_tokens} Tokens")

        # Weiter pollen, solange Jobs ausstehen
        if self._done_jobs < self._total_jobs:
            self.after(50, self._poll_results)
        else:
            self._polling = False

    def _add_thumbnail(self, name: str, pil_img: "Image.Image", meta: dict):
        """Fuegt ein Thumbnail zur Galerie hinzu."""
        if Image is None or ImageTk is None:
            return

        # 16x16 → 64x64 (4x NEAREST fuer Pixel-Art)
        thumb = pil_img.resize((64, 64), Image.NEAREST)
        tk_photo = ImageTk.PhotoImage(thumb)

        idx = len(self._gallery)
        entry = {
            "name": name,
            "pil_img": pil_img,
            "tk_photo": tk_photo,
            "meta": meta,
            "selected": False,
            "idx": idx,
        }
        self._gallery.append(entry)

        # Widget-Container
        container = ttk.Frame(self._inner_frame)
        entry["container"] = container

        # Bild-Label
        img_label = tk.Label(container, image=tk_photo, bg="#2a2a2a",
                             borderwidth=2, relief="flat", cursor="hand2")
        img_label.pack(padx=2, pady=2)
        entry["img_label"] = img_label

        # Beschriftung
        bm = meta.get("body_mod", "?")
        cm = meta.get("color_mod", "?")
        tag = meta.get("tag", "")
        lbl_text = f"{bm}/{cm}"
        if tag:
            lbl_text += f"\n[{tag}]"
        text_label = ttk.Label(container, text=lbl_text, font=("", 7))
        text_label.pack()
        entry["text_label"] = text_label

        # Klick-Handler
        img_label.bind("<Button-1>", lambda e, i=idx: self._toggle_selection(i))
        text_label.bind("<Button-1>", lambda e, i=idx: self._toggle_selection(i))

        self._relayout_gallery()

    def _add_animated_thumbnail(self, name: str, frames: list["Image.Image"], meta: dict):
        """Fuegt ein animiertes Thumbnail (Frame-Loop) zur Galerie hinzu."""
        if Image is None or ImageTk is None or not frames:
            return

        first_thumb = frames[0].resize((64, 64), Image.NEAREST)
        tk_photo = ImageTk.PhotoImage(first_thumb)

        idx = len(self._gallery)
        entry = {
            "name": name,
            "pil_img": frames[0],
            "frames": frames,
            "frame_idx": 0,
            "tk_photo": tk_photo,
            "meta": meta,
            "selected": False,
            "idx": idx,
        }
        self._gallery.append(entry)

        container = ttk.Frame(self._inner_frame)
        entry["container"] = container

        img_label = tk.Label(container, image=tk_photo, bg="#2a2a2a",
                             borderwidth=2, relief="flat", cursor="hand2")
        img_label.pack(padx=2, pady=2)
        entry["img_label"] = img_label

        anim = meta.get("anim_name", "?")
        bm = meta.get("body_mod", "?")
        cm = meta.get("color_mod", "?")
        tag = meta.get("tag", "")
        lbl_text = f"{anim}\n{bm}/{cm}"
        if tag:
            lbl_text += f"\n[{tag}]"
        text_label = ttk.Label(container, text=lbl_text, font=("", 7))
        text_label.pack()
        entry["text_label"] = text_label

        img_label.bind("<Button-1>", lambda e, i=idx: self._toggle_selection(i))
        text_label.bind("<Button-1>", lambda e, i=idx: self._toggle_selection(i))

        # Animation-Timer starten falls noch nicht aktiv
        if self._anim_timer_id is None:
            self._anim_timer_id = self.after(150, self._tick_animations)

        self._relayout_gallery()

    def _relayout_gallery(self):
        """Ordnet Thumbnails im Grid an."""
        if not self._gallery:
            return

        canvas_width = self._canvas.winfo_width()
        if canvas_width < 10:
            canvas_width = 400
        cols = max(1, canvas_width // 80)

        for i, entry in enumerate(self._gallery):
            r = i // cols
            c = i % cols
            entry["container"].grid(row=r, column=c, padx=4, pady=4)

    def _toggle_selection(self, idx: int):
        """Markiert/Demarkiert ein Thumbnail und zeigt Parameter in Statusbar."""
        if idx >= len(self._gallery):
            return
        entry = self._gallery[idx]
        entry["selected"] = not entry["selected"]
        if entry["selected"]:
            entry["img_label"].config(highlightbackground="#00cc00", highlightthickness=3,
                                       borderwidth=0, relief="solid")
        else:
            entry["img_label"].config(highlightbackground="#2a2a2a", highlightthickness=0,
                                       borderwidth=2, relief="flat")
        # Parameter-Anzeige in Statusbar
        meta = entry.get("meta", {})
        st = meta.get("sub_type", "?")
        anim = meta.get("anim_name", "")
        amp = meta.get("amplitude", "")
        chaos = meta.get("chaos", "")
        jit = meta.get("color_jitter", "")
        noi = meta.get("pixel_noise", "")
        seed = meta.get("seed", "?")
        vi = meta.get("variant_idx", "")
        tag = meta.get("tag", "")
        parts = [f"{st}"]
        if anim:
            parts[0] += f"/{anim}"
        if amp != "":
            parts.append(f"amp={amp}")
        if chaos != "":
            parts.append(f"chaos={chaos}")
        if jit != "":
            parts.append(f"jit={jit}")
        if noi != "":
            parts.append(f"noi={noi}")
        parts.append(f"seed={seed}+{vi}")
        if tag:
            parts.append(f"[{tag}]")
        self._status_label.config(text=" ".join(parts))

    def _select_all(self):
        """Markiert alle Thumbnails."""
        for entry in self._gallery:
            entry["selected"] = True
            entry["img_label"].config(highlightbackground="#00cc00", highlightthickness=3,
                                       borderwidth=0, relief="solid")

    def _delete_selected(self):
        """Entfernt markierte Thumbnails aus der Galerie."""
        self._gallery = [e for e in self._gallery if not e["selected"]]
        # Widgets neu aufbauen
        for widget in self._inner_frame.winfo_children():
            widget.destroy()
        for i, entry in enumerate(self._gallery):
            entry["idx"] = i
            entry["container"] = ttk.Frame(self._inner_frame)

            img_label = tk.Label(entry["container"], image=entry["tk_photo"], bg="#2a2a2a",
                                 borderwidth=2, relief="flat", cursor="hand2")
            img_label.pack(padx=2, pady=2)
            entry["img_label"] = img_label

            bm = entry["meta"].get("body_mod", "?")
            cm = entry["meta"].get("color_mod", "?")
            anim = entry["meta"].get("anim_name", "")
            tag = entry["meta"].get("tag", "")
            lbl_text = f"{anim}\n{bm}/{cm}" if anim else f"{bm}/{cm}"
            if tag:
                lbl_text += f"\n[{tag}]"
            text_label = ttk.Label(entry["container"], text=lbl_text, font=("", 7))
            text_label.pack()
            entry["text_label"] = text_label

            # Animierte Eintraege: Frames beibehalten
            if entry.get("frames"):
                entry["frame_idx"] = 0

            img_label.bind("<Button-1>", lambda e, idx=i: self._toggle_selection(idx))
            text_label.bind("<Button-1>", lambda e, idx=i: self._toggle_selection(idx))

        self._relayout_gallery()
        self._status_label.config(text=f"{len(self._gallery)} Sprites in Galerie")

    def _adopt_selected(self):
        """Speichert markierte Sprites nach data/tilesets/generated/."""
        selected = [e for e in self._gallery if e["selected"]]
        if not selected:
            self._status_label.config(text="Keine Sprites markiert!")
            return

        out_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "tilesets", "generated",
        )
        os.makedirs(out_dir, exist_ok=True)

        saved = []
        for entry in selected:
            tag = entry["meta"].get("tag", "")
            prefix = f"{tag}_" if tag else ""
            if entry.get("frames"):
                # Animierte Sprites: Einzelframes + Spritesheet
                for f_idx, frame in enumerate(entry["frames"]):
                    fname = f"{prefix}{entry['name']}_f{f_idx:02d}.png"
                    frame.save(os.path.join(out_dir, fname))
                    saved.append(fname)
                # Spritesheet
                try:
                    from scripts.pixel_art_creator import _create_spritesheet
                    sheet = _create_spritesheet(entry["frames"])
                    sheet_name = f"sheet_{prefix}{entry['name']}.png"
                    sheet.save(os.path.join(out_dir, sheet_name))
                    saved.append(sheet_name)
                except Exception:
                    pass
                # JSON-Sidecar
                meta_name = f"{prefix}{entry['name']}.meta.json"
                sidecar = {**entry["meta"], "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
                with open(os.path.join(out_dir, meta_name), "w", encoding="utf-8") as f:
                    json.dump(sidecar, f, indent=2, ensure_ascii=False)
                saved.append(meta_name)
            else:
                fname = f"{prefix}{entry['name']}"
                path = os.path.join(out_dir, fname)
                entry["pil_img"].save(path)
                saved.append(fname)
                # JSON-Sidecar
                base = os.path.splitext(fname)[0]
                meta_name = f"{base}.meta.json"
                sidecar = {**entry["meta"], "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
                with open(os.path.join(out_dir, meta_name), "w", encoding="utf-8") as f:
                    json.dump(sidecar, f, indent=2, ensure_ascii=False)
                saved.append(meta_name)

        # EventBus-Benachrichtigung
        try:
            from core.event_bus import EventBus
            bus = EventBus.get()
            bus.emit("sprites", "updated", {"files": saved})
        except Exception:
            pass

        self._status_label.config(text=f"{len(saved)} Sprites uebernommen nach data/tilesets/generated/")

    def _tick_animations(self):
        """Wechselt Frame fuer alle animierten Galerie-Eintraege (150ms)."""
        for entry in self._gallery:
            if not entry.get("frames"):
                continue
            entry["frame_idx"] = (entry["frame_idx"] + 1) % len(entry["frames"])
            frame = entry["frames"][entry["frame_idx"]]
            thumb = frame.resize((64, 64), Image.NEAREST)
            tk_photo = ImageTk.PhotoImage(thumb)
            entry["tk_photo"] = tk_photo
            entry["img_label"].config(image=tk_photo)
        self._anim_timer_id = self.after(150, self._tick_animations)

    def _set_tag_on_selected(self):
        """Setzt den Tag auf alle markierten Galerie-Eintraege."""
        tag = self._tag_var.get().strip()
        if not tag:
            self._status_label.config(text="Kein Tag eingegeben!")
            return
        selected = [e for e in self._gallery if e["selected"]]
        if not selected:
            self._status_label.config(text="Keine Sprites markiert!")
            return
        for entry in selected:
            entry["meta"]["tag"] = tag
            # Label aktualisieren
            bm = entry["meta"].get("body_mod", "?")
            cm = entry["meta"].get("color_mod", "?")
            anim = entry["meta"].get("anim_name", "")
            lbl_text = f"{anim}\n{bm}/{cm}" if anim else f"{bm}/{cm}"
            lbl_text += f"\n[{tag}]"
            entry["text_label"].config(text=lbl_text)
        self._status_label.config(text=f"Tag [{tag}] auf {len(selected)} Sprites gesetzt")

    def _batch_export_tag(self):
        """Exportiert alle Galerie-Eintraege mit bestimmtem Tag."""
        tag = simpledialog.askstring("Batch-Export", "Tag-Name:", parent=self)
        if not tag:
            return
        tag = tag.strip()
        matching = [e for e in self._gallery if e.get("meta", {}).get("tag") == tag]
        if not matching:
            self._status_label.config(text=f"Kein Sprite mit Tag [{tag}] gefunden")
            return

        out_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "tilesets", "generated",
        )
        os.makedirs(out_dir, exist_ok=True)

        saved = 0
        for entry in matching:
            prefix = f"{tag}_"
            if entry.get("frames"):
                for f_idx, frame in enumerate(entry["frames"]):
                    fname = f"{prefix}{entry['name']}_f{f_idx:02d}.png"
                    frame.save(os.path.join(out_dir, fname))
                    saved += 1
                try:
                    from scripts.pixel_art_creator import _create_spritesheet
                    sheet = _create_spritesheet(entry["frames"])
                    sheet.save(os.path.join(out_dir, f"sheet_{prefix}{entry['name']}.png"))
                    saved += 1
                except Exception:
                    pass
                sidecar = {**entry["meta"], "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
                with open(os.path.join(out_dir, f"{prefix}{entry['name']}.meta.json"),
                          "w", encoding="utf-8") as f:
                    json.dump(sidecar, f, indent=2, ensure_ascii=False)
                saved += 1
            else:
                fname = f"{prefix}{entry['name']}"
                entry["pil_img"].save(os.path.join(out_dir, fname))
                base = os.path.splitext(fname)[0]
                sidecar = {**entry["meta"], "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
                with open(os.path.join(out_dir, f"{base}.meta.json"),
                          "w", encoding="utf-8") as f:
                    json.dump(sidecar, f, indent=2, ensure_ascii=False)
                saved += 2
        self._status_label.config(text=f"Batch-Export [{tag}]: {saved} Dateien exportiert")

    def handle_event(self, data: dict):
        """Event-Handler (EventBus-Kompatibilitaet)."""
        pass
