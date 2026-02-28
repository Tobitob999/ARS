"""
gui/styles.py — Farb- und Style-Konstanten fuer die ARS TechGUI

Dark Theme (Catppuccin-inspiriert) mit farbkodiertem KI-Monitor.
"""

# ── Basis-Palette (Dark) ─────────────────────────────────────────────────────

BG_DARK = "#1E1E2E"           # Haupthintergrund
BG_PANEL = "#252537"          # Panel/Frame-Hintergrund
BG_INPUT = "#313244"          # Eingabefelder
BG_BUTTON = "#45475A"         # Button-Hintergrund
BG_BUTTON_HOVER = "#585B70"   # Button Hover
BG_HEADER = "#181825"         # Header/Tabs

FG_PRIMARY = "#CDD6F4"        # Haupttext
FG_SECONDARY = "#A6ADC8"      # Sekundaertext
FG_MUTED = "#6C7086"          # Gedimmter Text
FG_ACCENT = "#89B4FA"         # Akzentfarbe (Links, aktive Elemente)

# ── Status-Farben ────────────────────────────────────────────────────────────

GREEN = "#A6E3A1"             # Verbunden / Aktiv / Erfolg
RED = "#F38BA8"               # Fehler / Getrennt / Kritisch
YELLOW = "#F9E2AF"            # Warnung
ORANGE = "#FAB387"            # Warnung (sekundaer)
BLUE = "#89B4FA"              # Info
LAVENDER = "#B4BEFE"          # Highlight

# ── KI-Monitor Farbkodierung ─────────────────────────────────────────────────

# Hintergrundfarben fuer Context-Sektionen
CTX_SYSTEM_PROMPT = "#2D2D4F"   # System Prompt — statisch, gecached
CTX_ARCHIVAR = "#1A3A2A"        # Archivar-Kontext — Chronik, World State
CTX_LOCATION = "#3A2A1A"        # Location-Kontext — Ort, NPCs, Hinweise
CTX_HISTORY = "#1A2A3A"         # History — vergangene Turns

# Vordergrundfarben fuer Live-Stream
STREAM_PLAYER = "#B4D0FF"       # Spieler-Input (STT oder Text)
STREAM_KEEPER = "#FFE0C0"       # Keeper-Output (KI-Antwort, narrativ)
STREAM_TAG = "#A0F0A0"          # Geparste Tags (FAKT, INVENTAR, ZEIT...)
STREAM_PROBE = "#FFA0A0"        # Proben & Wuerfelergebnisse
STREAM_ARCHIVAR = "#C0C0FF"     # Archivar-Aktionen (Chronicle Update)
STREAM_WARNING = "#F9E2AF"      # Warnungen / Fehler

# ── Schriftarten ──────────────────────────────────────────────────────────────

FONT_FAMILY = "Consolas"
FONT_SIZE = 10
FONT_SIZE_SMALL = 9
FONT_SIZE_LARGE = 12
FONT_SIZE_HEADER = 14

FONT_NORMAL = (FONT_FAMILY, FONT_SIZE)
FONT_SMALL = (FONT_FAMILY, FONT_SIZE_SMALL)
FONT_LARGE = (FONT_FAMILY, FONT_SIZE_LARGE)
FONT_HEADER = (FONT_FAMILY, FONT_SIZE_HEADER, "bold")
FONT_BOLD = (FONT_FAMILY, FONT_SIZE, "bold")

# ── Geometrie ─────────────────────────────────────────────────────────────────

WINDOW_MIN_WIDTH = 1200
WINDOW_MIN_HEIGHT = 800
PAD = 8                        # Standard-Padding
PAD_SMALL = 4
PAD_LARGE = 12


def configure_dark_theme(root) -> None:
    """Wendet das Dark Theme auf das Tkinter-Root-Fenster und ttk-Widgets an."""
    import tkinter.ttk as ttk

    root.configure(bg=BG_DARK)

    style = ttk.Style(root)
    style.theme_use("clam")

    # Notebook (Tab-Container)
    style.configure("TNotebook", background=BG_DARK, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=BG_PANEL,
        foreground=FG_SECONDARY,
        padding=[12, 6],
        font=FONT_BOLD,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", BG_DARK)],
        foreground=[("selected", FG_ACCENT)],
    )

    # Frame
    style.configure("TFrame", background=BG_DARK)
    style.configure("Dark.TFrame", background=BG_PANEL)

    # Label
    style.configure("TLabel", background=BG_DARK, foreground=FG_PRIMARY, font=FONT_NORMAL)
    style.configure("Header.TLabel", font=FONT_HEADER, foreground=FG_ACCENT)
    style.configure("Muted.TLabel", foreground=FG_MUTED)
    style.configure("Status.TLabel", background=BG_HEADER, foreground=FG_PRIMARY, font=FONT_SMALL)
    style.configure("Green.TLabel", foreground=GREEN)
    style.configure("Red.TLabel", foreground=RED)
    style.configure("Yellow.TLabel", foreground=YELLOW)

    # Button
    style.configure(
        "TButton",
        background=BG_BUTTON,
        foreground=FG_PRIMARY,
        font=FONT_NORMAL,
        padding=[10, 5],
    )
    style.map(
        "TButton",
        background=[("active", BG_BUTTON_HOVER)],
    )
    style.configure(
        "Accent.TButton",
        background="#45855A",
        foreground="#FFFFFF",
    )
    style.map(
        "Accent.TButton",
        background=[("active", "#55957A")],
    )
    style.configure(
        "Danger.TButton",
        background="#85454A",
        foreground="#FFFFFF",
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#95555A")],
    )

    # Combobox
    style.configure(
        "TCombobox",
        fieldbackground=BG_INPUT,
        background=BG_BUTTON,
        foreground=FG_PRIMARY,
        selectbackground=BG_BUTTON_HOVER,
        selectforeground=FG_PRIMARY,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", BG_INPUT)],
        foreground=[("readonly", FG_PRIMARY)],
    )

    # Scale (Slider)
    style.configure(
        "TScale",
        background=BG_DARK,
        troughcolor=BG_INPUT,
    )

    # Checkbutton
    style.configure(
        "TCheckbutton",
        background=BG_DARK,
        foreground=FG_PRIMARY,
        font=FONT_NORMAL,
    )

    # Radiobutton
    style.configure(
        "TRadiobutton",
        background=BG_DARK,
        foreground=FG_PRIMARY,
        font=FONT_NORMAL,
    )

    # Separator
    style.configure("TSeparator", background=BG_BUTTON)

    # Treeview
    style.configure(
        "Treeview",
        background=BG_PANEL,
        foreground=FG_PRIMARY,
        fieldbackground=BG_PANEL,
        font=FONT_NORMAL,
        rowheight=24,
    )
    style.configure(
        "Treeview.Heading",
        background=BG_BUTTON,
        foreground=FG_ACCENT,
        font=FONT_BOLD,
    )
    style.map(
        "Treeview",
        background=[("selected", BG_BUTTON_HOVER)],
        foreground=[("selected", FG_PRIMARY)],
    )

    # LabelFrame
    style.configure(
        "TLabelframe",
        background=BG_DARK,
        foreground=FG_ACCENT,
    )
    style.configure(
        "TLabelframe.Label",
        background=BG_DARK,
        foreground=FG_ACCENT,
        font=FONT_BOLD,
    )

    # Progressbar
    style.configure(
        "TProgressbar",
        background=GREEN,
        troughcolor=BG_INPUT,
    )
    style.configure(
        "Red.Horizontal.TProgressbar",
        background=RED,
        troughcolor=BG_INPUT,
    )
    style.configure(
        "Yellow.Horizontal.TProgressbar",
        background=YELLOW,
        troughcolor=BG_INPUT,
    )
