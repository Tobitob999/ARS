"""
scripts/bot_graphics_test.py — Bot-Szenario: Grafik-Test ohne KI

Standalone-Skript: MinimalGUI mit Pixel-Dungeon-Tab, Start-Button, Helden-Stats,
Kampf-Log und Sound-Effekten. 6 Helden mit Ausruestung, Inventar, XP und
Zauberspruechen durchlaufen 5 Raeume mit Erkundung, Loot und Kaempfen.

Starten:  py -3 scripts/bot_graphics_test.py
Dauer:    ~2.5 Minuten, dann Fenster offen lassen.
"""

from __future__ import annotations

import io
import logging
import math
import os
import random
import struct
import sys
import threading
import time
import tkinter as tk
import tkinter.ttk as ttk
import wave
from queue import Queue, Empty
from typing import Any

# Projekt-Root in sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.event_bus import EventBus
from core.grid_engine import GridEngine, GridEntity, RoomGrid, bfs_path
from scripts.sprite_extractor import SpriteExtractor
from gui.styles import (
    configure_dark_theme,
    BG_DARK, BG_PANEL, BG_INPUT,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED, FG_ACCENT,
    GREEN, RED, YELLOW, ORANGE,
    FONT_FAMILY,
)
from gui.tab_dungeon_pixel import DungeonPixelTab
from gui.tab_world_map import WorldMapTab

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("BotTest")

FONT_N = (FONT_FAMILY, 10)
FONT_S = (FONT_FAMILY, 9)
FONT_XS = (FONT_FAMILY, 8)
FONT_B = (FONT_FAMILY, 10, "bold")
FONT_L = (FONT_FAMILY, 12, "bold")


# ══════════════════════════════════════════════════════════════════════════════
# Helden-Profile
# ══════════════════════════════════════════════════════════════════════════════

HERO_PROFILES: dict[str, dict[str, Any]] = {
    "aldric": {
        "name": "Aldric", "sym": "F", "hp": 14,
        "weapon": "Langschwert", "armor": "Kettenhemd",
        "spells": [],
    },
    "elara": {
        "name": "Elara", "sym": "M", "hp": 9,
        "weapon": "Zauberstab", "armor": "Magierrobe",
        "spells": ["Feuerpfeil", "Eissplitter", "Magisches Geschoss"],
    },
    "thorin": {
        "name": "Thorin", "sym": "C", "hp": 16,
        "weapon": "Streitkolben", "armor": "Schuppenpanzer",
        "spells": ["Heiliges Licht", "Goettlicher Segen"],
    },
    "kira": {
        "name": "Kira", "sym": "T", "hp": 10,
        "weapon": "Dolchpaar", "armor": "Lederruestung",
        "spells": [],
    },
    "rowan": {
        "name": "Rowan", "sym": "R", "hp": 12,
        "weapon": "Langbogen", "armor": "Lederruestung",
        "spells": [],
    },
    "sven": {
        "name": "Sven", "sym": "P", "hp": 15,
        "weapon": "Zweihaender", "armor": "Plattenpanzer",
        "spells": ["Handauflegen"],
    },
}

HERO_ORDER = ["aldric", "elara", "thorin", "kira", "rowan", "sven"]

MONSTER_WEAPONS: dict[str, str] = {
    "goblin": "Krummsaebel", "skeleton": "Rostschwert",
    "orc": "Kriegsaxt", "zombie": "Klauen",
}

MONSTER_XP: dict[str, int] = {
    "goblin": 40, "skeleton": 50, "orc": 65, "zombie": 55,
}


# ══════════════════════════════════════════════════════════════════════════════
# Sound-Effekte (generierte WAV-Daten, winsound)
# ══════════════════════════════════════════════════════════════════════════════

try:
    import winsound as _winsound
    _HAS_SOUND = True
except ImportError:
    _HAS_SOUND = False


def _wav_bytes(samples: list[int], sample_rate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def _clamp16(v: float) -> int:
    return max(-32767, min(32767, int(v)))


class SFX:
    """Generiert und spielt einfache Sound-Effekte via winsound."""

    def __init__(self) -> None:
        self._sounds: dict[str, bytes] = {}
        if not _HAS_SOUND:
            return
        sr = 22050
        # Schritt
        n = int(sr * 0.035)
        rng = random.Random(42)
        self._sounds["step"] = _wav_bytes(
            [_clamp16(rng.randint(-2000, 2000) * (1 - i / n)) for i in range(n)], sr)
        # Schwerthieb (Swing)
        n = int(sr * 0.1)
        self._sounds["slash"] = _wav_bytes([
            _clamp16(7000 * (1 - i / n) * math.sin(
                2 * math.pi * (700 - 550 * i / n) * i / sr))
            for i in range(n)], sr)
        # Treffer (Thud)
        n = int(sr * 0.09)
        self._sounds["hit"] = _wav_bytes([
            _clamp16(11000 * ((1 - i / n) ** 2) * math.sin(
                2 * math.pi * 100 * i / sr))
            for i in range(n)], sr)
        # Tod
        n = int(sr * 0.45)
        self._sounds["death"] = _wav_bytes([
            _clamp16(9000 * (1 - i / n) * math.sin(
                2 * math.pi * (500 - 420 * i / n) * i / sr))
            for i in range(n)], sr)
        # Heilung
        n = int(sr * 0.25)
        self._sounds["heal"] = _wav_bytes([
            _clamp16(6000 * min(1.0, 2 * i / n) * (1 - i / n) * math.sin(
                2 * math.pi * (300 + 500 * i / n) * i / sr))
            for i in range(n)], sr)
        # Zauberspruch (Warble)
        n = int(sr * 0.22)
        self._sounds["spell"] = _wav_bytes([
            _clamp16(5500 * (1 - i / n) * 0.8 * math.sin(
                2 * math.pi * (400 + 600 * i / n
                               + 80 * math.sin(2 * math.pi * 12 * i / sr)) * i / sr))
            for i in range(n)], sr)
        # Verfehlt (Whoosh)
        n = int(sr * 0.08)
        self._sounds["miss"] = _wav_bytes([
            _clamp16(3000 * (1 - i / n) * math.sin(
                2 * math.pi * (900 - 700 * i / n) * i / sr))
            for i in range(n)], sr)
        # Level Up (C5 → G5 Fanfare)
        n1, n2 = int(sr * 0.15), int(sr * 0.25)
        smp = [_clamp16(7000 * math.sin(2 * math.pi * 523 * i / sr))
               for i in range(n1)]
        smp += [_clamp16(7000 * (1 - i / n2) * math.sin(2 * math.pi * 784 * i / sr))
                for i in range(n2)]
        self._sounds["levelup"] = _wav_bytes(smp, sr)
        # Item aufheben (kurzes Pling)
        n = int(sr * 0.12)
        self._sounds["pickup"] = _wav_bytes([
            _clamp16(5000 * (1 - i / n) * math.sin(2 * math.pi * 880 * i / sr))
            for i in range(n)], sr)

    def play(self, name: str) -> None:
        data = self._sounds.get(name)
        if not data:
            return
        threading.Thread(target=self._play_sync, args=(data,), daemon=True).start()

    @staticmethod
    def _play_sync(data: bytes) -> None:
        try:
            _winsound.PlaySound(data, _winsound.SND_MEMORY)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# Stub-Objekte (Duck-Typing fuer DungeonPixelTab)
# ══════════════════════════════════════════════════════════════════════════════

class _StubPartyState:
    def __init__(self) -> None:
        self._members: dict[str, dict[str, Any]] = {}

    def init_hero(self, eid: str) -> None:
        p = HERO_PROFILES[eid]
        self._members[eid] = {
            "current_hp": p["hp"], "max_hp": p["hp"],
            "name": p["name"], "symbol": p["sym"],
            "level": 1, "xp": 0, "xp_next": 80,
            "weapon": p["weapon"], "armor": p["armor"],
            "inventory": [], "spells": list(p["spells"]),
        }

    def init_monster(self, eid: str, hp: int, weapon: str) -> None:
        self._members[eid] = {"current_hp": hp, "max_hp": hp, "weapon": weapon}

    def get_member(self, eid: str) -> dict[str, Any] | None:
        return self._members.get(eid)

    def set_hp(self, eid: str, hp: int, max_hp: int) -> None:
        m = self._members.get(eid)
        if m:
            m["current_hp"] = hp
            m["max_hp"] = max_hp
        else:
            self._members[eid] = {"current_hp": hp, "max_hp": max_hp}

    def add_xp(self, eid: str, amount: int) -> bool:
        """Gibt XP. Returniert True bei Level-Up."""
        m = self._members.get(eid)
        if not m or "xp" not in m:
            return False
        m["xp"] += amount
        if m["xp"] >= m.get("xp_next", 80):
            m["level"] = m.get("level", 1) + 1
            m["xp"] -= m["xp_next"]
            m["xp_next"] = int(m["xp_next"] * 1.6)
            m["max_hp"] += 2
            m["current_hp"] = m["max_hp"]  # Voll-Heal bei Level-Up
            return True
        return False

    def add_item(self, eid: str, item: str) -> None:
        m = self._members.get(eid)
        if m:
            m.setdefault("inventory", []).append(item)


class _StubEngine:
    def __init__(self) -> None:
        self.grid_engine = GridEngine()
        self.party_state = _StubPartyState()
        self._orchestrator = None
        self._combat_tracker = None


# ══════════════════════════════════════════════════════════════════════════════
# Handgebaute Maps (5 Raeume)
# ══════════════════════════════════════════════════════════════════════════════

def _make_entrance_hall() -> list[list[str]]:
    """Eingangshalle 24x16."""
    W, H = 24, 16
    t = [["wall"] * W for _ in range(H)]
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            t[y][x] = "floor"
    for sx, sy in [(5, 4), (18, 4), (5, 11), (18, 11), (11, 4), (11, 11)]:
        t[sy][sx] = "obstacle"
    for x in range(9, 16):
        t[8][x] = "wall"
    t[8][12] = "door"
    t[H - 1][12] = "door"
    return t


def _make_corridor() -> list[list[str]]:
    """Korridor 12x24."""
    W, H = 12, 24
    t = [["wall"] * W for _ in range(H)]
    for y in range(1, H - 1):
        for x in range(4, 8):
            t[y][x] = "floor"
    for y in range(9, 13):
        for x in range(1, 5):
            t[y][x] = "floor"
    t[11][2] = "obstacle"
    for y in range(16, 20):
        for x in range(7, 11):
            t[y][x] = "floor"
    t[18][9] = "obstacle"
    t[0][5] = "door"
    t[H - 1][5] = "door"
    return t


def _make_catacombs() -> list[list[str]]:
    """Katakomben 28x20."""
    W, H = 28, 20
    t = [["wall"] * W for _ in range(H)]
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            t[y][x] = "floor"
    for y in range(8, 12):
        for x in range(10, 18):
            t[y][x] = "water"
    for y in range(8, 12):
        t[y][14] = "floor"
    for sx, sy in [(8, 7), (19, 7), (8, 12), (19, 12)]:
        t[sy][sx] = "obstacle"
    for y in range(4, 8):
        t[y][6] = "wall"
    t[6][6] = "door"
    t[0][14] = "door"
    t[H - 1][14] = "door"
    t[9][W - 1] = "door"
    return t


def _make_throne_room() -> list[list[str]]:
    """Thronsaal 22x14."""
    W, H = 22, 14
    t = [["wall"] * W for _ in range(H)]
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            t[y][x] = "floor"
    for x in range(8, 14):
        t[2][x] = "obstacle"
    for sx, sy in [(4, 4), (17, 4), (4, 10), (17, 10)]:
        t[sy][sx] = "obstacle"
    t[0][11] = "door"
    t[H - 1][11] = "door"
    return t


def _make_treasure() -> list[list[str]]:
    """Schatzkammer 18x12."""
    W, H = 18, 12
    t = [["wall"] * W for _ in range(H)]
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            t[y][x] = "floor"
    for sx, sy in [(3, 2), (14, 2), (3, 9), (14, 9),
                    (8, 5), (9, 5), (8, 6), (9, 6)]:
        t[sy][sx] = "obstacle"
    t[5][0] = "door"
    return t


# ══════════════════════════════════════════════════════════════════════════════
# Hilfsfunktion: Text-Bar
# ══════════════════════════════════════════════════════════════════════════════

def _bar(val: int, max_val: int, width: int = 10) -> str:
    ratio = max(0.0, min(1.0, val / max_val)) if max_val > 0 else 0
    filled = int(width * ratio)
    return "\u2588" * filled + "\u2591" * (width - filled)


# ══════════════════════════════════════════════════════════════════════════════
# MinimalGUI
# ══════════════════════════════════════════════════════════════════════════════

class MinimalGUI:
    """GUI-Fenster mit Pixel-Dungeon-Tab, Helden-Stats und Kampf-Log."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("ARS Bot Graphics Test")
        self.root.geometry("1300x900")
        self.root.configure(bg=BG_DARK)
        configure_dark_theme(self.root)

        self.engine = _StubEngine()
        self._scenario: BotScenario | None = None
        self._phase_var = tk.StringVar(value="Bereit — Start druecken")
        self._log_lines: list[str] = []

        self._build_ui()

        # EventBus → Queue → Tab
        self._event_queue: Queue[dict] = Queue()
        EventBus.get().on("*", self._on_bus_event)
        self._poll_events()
        self._update_stats_loop()

    def _build_ui(self) -> None:
        # ── Top-Bar ──────────────────────────────────────────────────────
        top = tk.Frame(self.root, bg=BG_PANEL, height=40)
        top.pack(fill=tk.X)
        top.pack_propagate(False)

        self._start_btn = ttk.Button(
            top, text="  \u25B6  Start Szenario  ", command=self._on_start,
            style="Accent.TButton",
        )
        self._start_btn.pack(side=tk.LEFT, padx=8, pady=6)

        tk.Label(top, textvariable=self._phase_var,
                 bg=BG_PANEL, fg=FG_ACCENT, font=FONT_B).pack(
            side=tk.LEFT, padx=16, pady=6)

        # ── Body (Dungeon + Sidebar) ────────────────────────────────────
        body = tk.Frame(self.root, bg=BG_DARK)
        body.pack(fill=tk.BOTH, expand=True)

        # Notebook
        self.notebook = ttk.Notebook(body)
        self.notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tab = DungeonPixelTab(self.notebook, self)  # type: ignore[arg-type]
        self.notebook.add(self.tab, text="Pixel Dungeon")

        # World Map Tab
        self.map_tab = WorldMapTab(self.notebook, self)
        self.notebook.add(self.map_tab, text="World Map")

        self.notebook.select(self.tab)
        if hasattr(self.tab, "_demo_btn"):
            self.tab._demo_btn.config(state=tk.DISABLED)
        if hasattr(self.tab, "_crawl_btn"):
            self.tab._crawl_btn.config(state=tk.DISABLED)

        # ── Rechte Sidebar (280px) ──────────────────────────────────────
        sidebar = tk.Frame(body, bg=BG_PANEL, width=280)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # --- Party-Stats (Text-Widget, obere Haelfte) ---
        tk.Label(sidebar, text="  PARTY  ", bg=BG_DARK, fg=FG_ACCENT,
                 font=FONT_L, anchor=tk.W).pack(fill=tk.X, padx=4, pady=(6, 2))

        self._stats_text = tk.Text(
            sidebar, bg=BG_PANEL, fg=FG_PRIMARY, font=FONT_S,
            wrap=tk.NONE, state=tk.DISABLED, bd=0,
            highlightthickness=0, padx=4, pady=2, height=22,
        )
        self._stats_text.pack(fill=tk.X, padx=4, pady=(0, 2))
        # Text-Tags fuer Farben
        self._stats_text.tag_configure("hp_good", foreground=GREEN)
        self._stats_text.tag_configure("hp_warn", foreground=YELLOW)
        self._stats_text.tag_configure("hp_crit", foreground=RED)
        self._stats_text.tag_configure("hp_dead", foreground=FG_MUTED)
        self._stats_text.tag_configure("xp", foreground=FG_ACCENT)
        self._stats_text.tag_configure("equip", foreground=FG_MUTED)
        self._stats_text.tag_configure("inv", foreground=ORANGE)
        self._stats_text.tag_configure("head", foreground=FG_PRIMARY, font=FONT_B)
        self._stats_text.tag_configure("levelup", foreground=YELLOW, font=FONT_B)

        # --- Trennlinie ---
        tk.Frame(sidebar, bg=FG_MUTED, height=1).pack(fill=tk.X, padx=8, pady=4)

        # --- Kampf-Log (untere Haelfte) ---
        tk.Label(sidebar, text="  KAMPF-LOG  ", bg=BG_DARK, fg=FG_ACCENT,
                 font=FONT_L, anchor=tk.W).pack(fill=tk.X, padx=4, pady=(0, 2))

        self._log_text = tk.Text(
            sidebar, bg=BG_INPUT, fg=FG_SECONDARY, font=FONT_XS,
            wrap=tk.WORD, state=tk.DISABLED, bd=0,
            highlightthickness=0, padx=6, pady=4,
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 6))
        self._log_text.tag_configure("dmg", foreground=RED)
        self._log_text.tag_configure("heal", foreground=GREEN)
        self._log_text.tag_configure("miss", foreground=FG_MUTED)
        self._log_text.tag_configure("kill", foreground=ORANGE)
        self._log_text.tag_configure("loot", foreground=YELLOW)
        self._log_text.tag_configure("xp", foreground=FG_ACCENT)
        self._log_text.tag_configure("lvl", foreground=YELLOW, font=FONT_B)
        self._log_text.tag_configure("spell", foreground="#C0A0FF")
        self._log_text.tag_configure("phase", foreground=FG_ACCENT, font=FONT_B)

    # ── Start ────────────────────────────────────────────────────────────

    def _on_start(self) -> None:
        if self._scenario and self._scenario.is_alive():
            return
        # Reset
        self.engine.party_state = _StubPartyState()
        self.engine.grid_engine._rooms_cache.clear()
        self.engine.grid_engine._current_room = None
        self._log_lines.clear()
        self._start_btn.config(state=tk.DISABLED, text="  Laeuft...  ")

        # SpriteExtractor: fehlende Sprites erzeugen
        self._generate_test_sprites()

        self._scenario = BotScenario(self)
        self._scenario.start()

    def _generate_test_sprites(self) -> None:
        """Erzeugt Sprites fuer Test-Adventure-Daten via SpriteExtractor."""
        try:
            extractor = SpriteExtractor()
            test_adventure = {
                "npcs": [
                    {"name": "Goblin", "type": "monster", "hd": 1,
                     "spells": [], "abilities": []},
                    {"name": "Skeleton", "type": "monster", "hd": 1,
                     "spells": [], "abilities": []},
                    {"name": "Orc", "type": "monster", "hd": 3,
                     "spells": [], "abilities": ["Kriegsschrei"]},
                    {"name": "Zombie", "type": "monster", "hd": 2,
                     "spells": [], "abilities": []},
                    {"name": "Oger", "type": "monster", "hd": 5, "size": "L",
                     "spells": [], "abilities": []},
                    {"name": "Troll", "type": "monster", "hd": 8, "size": "H",
                     "spells": [], "abilities": ["Regeneration"]},
                    {"name": "Drache", "type": "monster", "hd": 15, "size": "G",
                     "spells": ["Feueratem"], "abilities": ["Furcht-Aura"]},
                    {"name": "Lich", "type": "monster", "hd": 10,
                     "spells": ["Todesstrahl", "Eissturm"], "abilities": []},
                    {"name": "Wyvern", "type": "monster", "hd": 7, "size": "H",
                     "spells": [], "abilities": ["Giftstachel"]},
                    {"name": "Iron Golem", "type": "monster", "hd": 12, "size": "L",
                     "spells": [], "abilities": ["Giftgas"]},
                    {"name": "Merchant", "type": "friendly",
                     "spells": [], "abilities": []},
                ],
                "locations": [],
            }
            reqs = extractor.extract_requirements(test_adventure)
            generated = extractor.ensure_sprites(reqs)
            logger.info("SpriteExtractor: %d Sprites bereit", len(generated))
        except Exception as e:
            logger.warning("SpriteExtractor fehlgeschlagen: %s", e)

    def set_phase(self, text: str) -> None:
        self._phase_var.set(text)

    def add_log(self, msg: str, tag: str = "") -> None:
        self._log_lines.append((msg, tag))
        if len(self._log_lines) > 80:
            self._log_lines = self._log_lines[-80:]

    # ── EventBus ─────────────────────────────────────────────────────────

    def _on_bus_event(self, data: dict) -> None:
        self._event_queue.put(data)

    def _poll_events(self) -> None:
        try:
            for _ in range(20):
                data = self._event_queue.get_nowait()
                self.tab.handle_event(data)
        except Empty:
            pass
        self.root.after(50, self._poll_events)

    # ── Stats + Log Update (250ms) ───────────────────────────────────────

    def _update_stats_loop(self) -> None:
        ps = self.engine.party_state
        st = self._stats_text
        st.config(state=tk.NORMAL)
        st.delete("1.0", tk.END)

        for eid in HERO_ORDER:
            m = ps.get_member(eid)
            p = HERO_PROFILES[eid]
            sym = p["sym"]
            name = p["name"]

            if not m or "level" not in m:
                st.insert(tk.END, f" {sym} {name}\n", "head")
                st.insert(tk.END, "   ---\n", "equip")
                continue

            hp = m["current_hp"]
            max_hp = m["max_hp"]
            level = m.get("level", 1)
            xp = m.get("xp", 0)
            xp_next = m.get("xp_next", 80)
            weapon = m.get("weapon", "---")
            armor = m.get("armor", "---")

            # Zeile 1: Name + Level
            st.insert(tk.END, f" {sym} {name:<8} Lv{level}", "head")
            st.insert(tk.END, f"  {weapon}\n", "equip")

            # Zeile 2: HP-Bar
            hp_bar = _bar(hp, max_hp, 12)
            hp_tag = "hp_good"
            if hp <= 0:
                hp_tag = "hp_dead"
            elif hp / max_hp <= 0.25:
                hp_tag = "hp_crit"
            elif hp / max_hp <= 0.5:
                hp_tag = "hp_warn"
            st.insert(tk.END, f"   HP {hp_bar} {hp:>2}/{max_hp:<2}", hp_tag)

            # XP-Bar
            xp_bar = _bar(xp, xp_next, 6)
            st.insert(tk.END, f"  XP {xp_bar} {xp}/{xp_next}\n", "xp")

            # Zeile 3: Ruestung + Inventar
            st.insert(tk.END, f"   {armor}", "equip")
            inv = m.get("inventory", [])
            if inv:
                st.insert(tk.END, f" | {', '.join(inv)}", "inv")
            st.insert(tk.END, "\n")

        st.config(state=tk.DISABLED)

        # Log aktualisieren
        lt = self._log_text
        lt.config(state=tk.NORMAL)
        lt.delete("1.0", tk.END)
        for msg, tag in self._log_lines[-30:]:
            lt.insert(tk.END, msg + "\n", tag if tag else ())
        lt.see(tk.END)
        lt.config(state=tk.DISABLED)

        # Re-enable Start
        if self._scenario and not self._scenario.is_alive():
            self._start_btn.config(state=tk.NORMAL, text="  \u25B6  Neustart  ")

        self.root.after(250, self._update_stats_loop)

    def run(self) -> None:
        self.root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# BotScenario — 5 Akte mit Kampf, Magie, Loot, XP, Level-Up
# ══════════════════════════════════════════════════════════════════════════════

class BotScenario(threading.Thread):
    """Daemon-Thread — spielt erweitertes Szenario ab."""

    def __init__(self, gui: MinimalGUI) -> None:
        super().__init__(daemon=True)
        self.gui = gui
        self.engine = gui.engine
        self.grid = self.engine.grid_engine
        self.bus = EventBus.get()
        self.ps = self.engine.party_state
        self.sfx = SFX()
        self._rng = random.Random(42)
        self._spell_idx: dict[str, int] = {}  # caster_id → aktueller Spell-Index

    def run(self) -> None:
        try:
            time.sleep(0.5)
            # Helden initialisieren
            for eid in HERO_ORDER:
                self.ps.init_hero(eid)
            self._act1_entrance()
            self._act2_corridor()
            self._act3_catacombs()
            self._act4_throne()
            self._act5_treasure()
            self._act6_large_creatures()
            self._act7_spell_effects()
            self._phase("Szenario beendet!")
            self._log("=== Abenteuer beendet! ===", "phase")
        except Exception:
            logger.exception("BotScenario Fehler")

    # ── Logging ──────────────────────────────────────────────────────────

    def _phase(self, text: str) -> None:
        logger.info(text)
        self.gui.set_phase(text)

    def _log(self, msg: str, tag: str = "") -> None:
        self.gui.add_log(msg, tag)

    # ── Raum-Setup ───────────────────────────────────────────────────────

    def _setup_room(self, room_id: str, terrain: list[list[str]],
                    exits: dict[str, list[int]] | None = None) -> RoomGrid:
        map_data: dict[str, Any] = {
            "terrain": terrain,
            "exits": {k: v for k, v in (exits or {}).items()},
            "decorations": [],
        }
        location = {"id": room_id, "name": room_id, "description": "", "map": map_data}
        self.grid._rooms_cache.pop(room_id, None)
        return self.grid.setup_room(location, room_id)

    def _place_heroes(self, room: RoomGrid,
                      positions: list[tuple[str, int, int]]) -> None:
        for eid, gx, gy in positions:
            p = HERO_PROFILES[eid]
            ent = GridEntity(
                entity_id=eid, name=p["name"], entity_type="party_member",
                x=gx, y=gy, symbol=p["sym"], movement_rate=12,
            )
            room.place_entity(ent)
        self.bus.emit("grid", "formation_placed", {
            "room_id": room.room_id,
            "positions": {eid: (gx, gy) for eid, gx, gy in positions},
        })

    # ── Bewegung ─────────────────────────────────────────────────────────

    def _move(self, room: RoomGrid, eid: str, goal: tuple[int, int],
              pause: float = 1.8) -> None:
        ent = room.entities.get(eid)
        if not ent:
            return
        path = bfs_path(room, (ent.x, ent.y), goal)
        if not path or len(path) < 2:
            return
        room.move_entity_to(eid, path[-1][0], path[-1][1])
        self.bus.emit("grid", "entity_moved", {
            "entity_id": eid, "name": ent.name,
            "path": path, "move_type": "walk",
        })
        self.sfx.play("step")
        time.sleep(pause)

    # ── Angriff (mit Treffer/Verfehlen, Waffe, Auto-Kill) ───────────────

    def _get_weapon(self, eid: str) -> str:
        m = self.ps.get_member(eid)
        if m and "weapon" in m:
            return m["weapon"]
        # Monster-Waffe aus Name ableiten
        room = self.grid.get_current_room()
        if room and eid in room.entities:
            name_lower = room.entities[eid].name.lower()
            for key, w in MONSTER_WEAPONS.items():
                if key in name_lower:
                    return w
        return "Waffe"

    def _attack(self, room: RoomGrid, atk_id: str, tgt_id: str,
                attack_type: str, dmg: int,
                pause: float = 2.0) -> tuple[bool, bool]:
        """Angriff. Returniert (hit, killed)."""
        atk = room.entities.get(atk_id)
        tgt = room.entities.get(tgt_id)
        if not atk or not tgt:
            return False, False

        weapon = self._get_weapon(atk_id)

        # Treffer-Check (80% Trefferchance)
        if self._rng.random() > 0.80:
            self._log(
                f"{atk.name} greift {tgt.name} mit {weapon} an... Verfehlt!", "miss")
            self.sfx.play("miss")
            time.sleep(pause * 0.5)
            return False, False

        # Combat-Event (fuer Visuell)
        path = [(atk.x, atk.y)]
        if attack_type == "melee":
            dx = 1 if tgt.x > atk.x else (-1 if tgt.x < atk.x else 0)
            dy = 1 if tgt.y > atk.y else (-1 if tgt.y < atk.y else 0)
            path.append((atk.x + dx, atk.y + dy))
        self.bus.emit("grid", "combat_move", {
            "attacker_id": atk_id, "attacker_name": atk.name,
            "target_id": tgt_id, "target_name": tgt.name,
            "path": path, "attack_type": attack_type,
        })
        self.sfx.play("slash")
        time.sleep(0.4)

        # Schaden anwenden
        member = self.ps.get_member(tgt_id)
        old_hp = member["current_hp"] if member else 10
        new_hp = max(0, old_hp - dmg)
        max_hp = member["max_hp"] if member else 10
        self.ps.set_hp(tgt_id, new_hp, max_hp)
        self.bus.emit("party", "member_updated", {
            "name": tgt.name, "hp": new_hp, "prev_hp": old_hp, "max_hp": max_hp,
        })
        self.sfx.play("hit")
        self._log(
            f"{atk.name} trifft {tgt.name} mit {weapon}! (-{dmg} HP)", "dmg")

        killed = new_hp <= 0
        if killed:
            time.sleep(0.5)
            self._kill_entity(room, tgt_id, killer_id=atk_id)
        time.sleep(pause)
        return True, killed

    # ── Zauberspruch ─────────────────────────────────────────────────────

    def _next_spell(self, caster_id: str) -> str:
        """Gibt den naechsten Zauberspruch im Zyklus zurueck."""
        m = self.ps.get_member(caster_id)
        spells = m.get("spells", []) if m else []
        if not spells:
            return "Magie"
        idx = self._spell_idx.get(caster_id, 0)
        spell = spells[idx % len(spells)]
        self._spell_idx[caster_id] = idx + 1
        return spell

    def _cast_offensive(self, room: RoomGrid, caster_id: str,
                        tgt_id: str, dmg: int,
                        spell: str | None = None,
                        pause: float = 2.0) -> tuple[bool, bool]:
        """Offensiver Zauber. Returniert (hit, killed)."""
        caster = room.entities.get(caster_id)
        tgt = room.entities.get(tgt_id)
        if not caster or not tgt:
            return False, False

        if spell is None:
            spell = self._next_spell(caster_id)

        self.sfx.play("spell")

        # Treffer-Check (85% fuer Zauber)
        if self._rng.random() > 0.85:
            self._log(
                f"{caster.name} wirkt '{spell}' auf {tgt.name}... Widersteht!", "miss")
            time.sleep(pause * 0.5)
            return False, False

        # Visuell: Ranged-Projektil
        self.bus.emit("grid", "combat_move", {
            "attacker_id": caster_id, "attacker_name": caster.name,
            "target_id": tgt_id, "target_name": tgt.name,
            "path": [(caster.x, caster.y)], "attack_type": "ranged",
        })
        time.sleep(0.4)

        # Schaden
        member = self.ps.get_member(tgt_id)
        old_hp = member["current_hp"] if member else 10
        new_hp = max(0, old_hp - dmg)
        max_hp = member["max_hp"] if member else 10
        self.ps.set_hp(tgt_id, new_hp, max_hp)
        self.bus.emit("party", "member_updated", {
            "name": tgt.name, "hp": new_hp, "prev_hp": old_hp, "max_hp": max_hp,
        })
        self.sfx.play("hit")
        self._log(
            f"{caster.name} wirkt '{spell}' auf {tgt.name}! (-{dmg} HP)", "spell")

        killed = new_hp <= 0
        if killed:
            time.sleep(0.5)
            self._kill_entity(room, tgt_id, killer_id=caster_id)
        time.sleep(pause)
        return True, killed

    def _cast_heal(self, room: RoomGrid, caster_id: str,
                   tgt_id: str, amount: int,
                   spell: str | None = None) -> None:
        """Heil-Zauber."""
        caster = room.entities.get(caster_id)
        if not caster:
            return
        if spell is None:
            spell = self._next_spell(caster_id)

        member = self.ps.get_member(tgt_id)
        if not member:
            return
        tgt_ent = room.entities.get(tgt_id)
        tgt_name = tgt_ent.name if tgt_ent else tgt_id

        old_hp = member["current_hp"]
        max_hp = member["max_hp"]
        new_hp = min(max_hp, old_hp + amount)
        self.ps.set_hp(tgt_id, new_hp, max_hp)
        self.bus.emit("party", "member_updated", {
            "name": tgt_name, "hp": new_hp, "prev_hp": old_hp, "max_hp": max_hp,
        })
        self.sfx.play("heal")
        self._log(
            f"{caster.name} wirkt '{spell}' auf {tgt_name} (+{amount} HP)", "heal")
        time.sleep(1.5)

    # ── Tod + XP ─────────────────────────────────────────────────────────

    def _kill_entity(self, room: RoomGrid, eid: str,
                     killer_id: str | None = None) -> None:
        ent = room.entities.get(eid)
        if not ent:
            return
        ent.alive = False
        room.remove_entity(eid)
        self.sfx.play("death")
        self._log(f"{ent.name} faellt!", "kill")

        # XP verteilen (alle lebenden Helden, Killer bekommt Bonus)
        name_lower = ent.name.lower()
        xp = 30
        for key, val in MONSTER_XP.items():
            if key in name_lower:
                xp = val
                break
        # Boss-Check
        m = self.ps.get_member(eid)
        if m and m.get("max_hp", 0) >= 25:
            xp = max(xp, 120)

        living = [h for h in HERO_ORDER
                  if h in room.entities and room.entities[h].alive]
        if not living:
            return
        share = max(1, xp // len(living))
        bonus = 15

        for hero_id in living:
            total = share + (bonus if hero_id == killer_id else 0)
            leveled = self.ps.add_xp(hero_id, total)
            hero_m = self.ps.get_member(hero_id)
            hero_name = hero_m["name"] if hero_m else hero_id
            self._log(f"  {hero_name} +{total} XP", "xp")
            if leveled:
                new_lvl = hero_m.get("level", 2) if hero_m else 2
                self.sfx.play("levelup")
                self._log(
                    f"  >>> {hero_name} erreicht Level {new_lvl}! <<<", "lvl")
                time.sleep(1.0)

    # ── Items ────────────────────────────────────────────────────────────

    def _pickup(self, room: RoomGrid, eid: str,
                item: str, x: int, y: int) -> None:
        """Held bewegt sich zu Position und hebt Item auf."""
        self._move(room, eid, (x, y), pause=1.2)
        self.ps.add_item(eid, item)
        ent = room.entities.get(eid)
        name = ent.name if ent else eid
        self.sfx.play("pickup")
        self._log(f"{name} findet: {item}", "loot")
        time.sleep(0.8)

    # ── Helfer: Monster spawnen ──────────────────────────────────────────

    def _spawn(self, room: RoomGrid, eid: str, name: str,
               x: int, y: int, hp: int) -> None:
        ent = GridEntity(
            entity_id=eid, name=name, entity_type="monster",
            x=x, y=y, symbol="?", movement_rate=8,
        )
        room.place_entity(ent)
        name_lower = name.lower()
        weapon = "Klauen"
        for key, w in MONSTER_WEAPONS.items():
            if key in name_lower:
                weapon = w
                break
        self.ps.init_monster(eid, hp, weapon)
        self._log(f"{name} erscheint!", "kill")

    # ══════════════════════════════════════════════════════════════════════
    # Akt 1: Eingangshalle
    # ══════════════════════════════════════════════════════════════════════

    def _act1_entrance(self) -> None:
        self._phase("Akt 1: Eingangshalle")
        self._log("--- Akt 1: Eingangshalle ---", "phase")
        room = self._setup_room("eingangshalle", _make_entrance_hall(),
                                exits={"sued": [12, 15]})
        time.sleep(1.0)

        self._log("Die Gruppe betritt die Halle...")
        self._place_heroes(room, [
            ("aldric", 10, 2), ("elara", 12, 2), ("thorin", 14, 2),
            ("kira", 10, 3), ("rowan", 12, 3), ("sven", 14, 3),
        ])
        time.sleep(2.0)

        # Erkunden
        self._log("Die Helden schwärmen aus...")
        self._move(room, "aldric", (3, 6))
        self._move(room, "kira", (20, 6))
        self._move(room, "elara", (12, 6))
        self._move(room, "rowan", (12, 10))
        self._move(room, "thorin", (6, 12))
        self._move(room, "sven", (18, 12))

        # Loot in der Halle
        self._pickup(room, "aldric", "Heiltrank", 2, 4)
        self._pickup(room, "kira", "Dietrich-Set", 20, 3)

        # Sammeln am Ausgang
        self._log("Sammeln am Suedausgang...")
        for eid, gx in [("aldric", 10), ("elara", 11), ("thorin", 12),
                         ("kira", 13), ("rowan", 11), ("sven", 13)]:
            self._move(room, eid, (gx, 13), pause=1.0)
        time.sleep(1.0)

    # ══════════════════════════════════════════════════════════════════════
    # Akt 2: Korridor — Goblin-Hinterhalt
    # ══════════════════════════════════════════════════════════════════════

    def _act2_corridor(self) -> None:
        self._phase("Akt 2: Korridor")
        self._log("--- Akt 2: Korridor ---", "phase")
        room = self._setup_room("korridor", _make_corridor(),
                                exits={"nord": [5, 0], "sued": [5, 23]})
        time.sleep(0.5)

        self._place_heroes(room, [
            ("aldric", 5, 2), ("elara", 6, 2), ("thorin", 5, 3),
            ("kira", 6, 3), ("rowan", 5, 4), ("sven", 6, 4),
        ])
        time.sleep(1.5)

        self._log("Durch den engen Gang...")
        self._move(room, "aldric", (5, 8))
        self._move(room, "kira", (5, 7))

        # Kira erkundet Nische
        self._log("Kira schleicht in die westliche Nische...")
        self._move(room, "kira", (2, 10))

        # Goblin-Hinterhalt!
        self._log("Hinterhalt aus den Schatten!", "kill")
        time.sleep(0.5)
        self._spawn(room, "gob_1", "Goblin", 2, 12, 7)
        self._spawn(room, "gob_2", "Goblin", 3, 11, 6)
        time.sleep(1.5)

        # Kampf
        self._attack(room, "kira", "gob_2", "melee", 4)
        self._attack(room, "gob_1", "kira", "melee", 3)
        self._move(room, "aldric", (3, 10), pause=1.2)
        self._attack(room, "aldric", "gob_1", "melee", 5)
        self._attack(room, "kira", "gob_2", "melee", 4)  # Kill

        # Falls gob_1 noch lebt
        if "gob_1" in room.entities:
            self._attack(room, "aldric", "gob_1", "melee", 4)

        # Heilung
        self._cast_heal(room, "thorin", "kira", 3, "Heiliges Licht")
        time.sleep(1.0)

        # Loot in der Nische
        self._pickup(room, "kira", "Silberdolch", 2, 11)

        # Weiter nach Sueden
        self._log("Weiter durch den Korridor...")
        self._move(room, "aldric", (5, 16))
        self._move(room, "kira", (6, 16))
        self._move(room, "rowan", (5, 18))

        # Oestliche Nische erkunden
        self._move(room, "rowan", (8, 18))
        self._pickup(room, "rowan", "Goldmuenzen x30", 9, 18)

        # Zum Ausgang
        for eid, gx in [("aldric", 4), ("elara", 5), ("thorin", 6),
                         ("kira", 5), ("rowan", 6), ("sven", 5)]:
            self._move(room, eid, (gx, 21), pause=0.8)
        time.sleep(1.0)

    # ══════════════════════════════════════════════════════════════════════
    # Akt 3: Katakomben — Grosse Schlacht
    # ══════════════════════════════════════════════════════════════════════

    def _act3_catacombs(self) -> None:
        self._phase("Akt 3: Katakomben")
        self._log("--- Akt 3: Katakomben ---", "phase")
        room = self._setup_room("katakomben", _make_catacombs(),
                                exits={"nord": [14, 0], "sued": [14, 19],
                                       "ost": [27, 9]})
        time.sleep(0.5)

        self._place_heroes(room, [
            ("aldric", 13, 2), ("elara", 15, 2), ("thorin", 14, 3),
            ("kira", 13, 3), ("rowan", 15, 3), ("sven", 14, 4),
        ])
        time.sleep(2.0)

        self._log("Ein unterirdischer See liegt vor euch...")
        self._move(room, "aldric", (10, 6))
        self._move(room, "rowan", (20, 5))

        # Loot vor dem Kampf
        self._pickup(room, "elara", "Runenstein", 4, 5)

        # Monster!
        self._log("Untote erheben sich!", "kill")
        time.sleep(0.5)
        self._spawn(room, "skel_1", "Skeleton", 5, 13, 9)
        time.sleep(0.4)
        self._spawn(room, "skel_2", "Skeleton", 22, 14, 9)
        time.sleep(0.4)
        self._spawn(room, "orc_1", "Orc", 10, 15, 16)
        time.sleep(0.4)
        self._spawn(room, "zomb_1", "Zombie", 18, 16, 12)
        time.sleep(1.5)

        # Bruecke ueberqueren
        self._log("Ueber die Bruecke!")
        self._move(room, "aldric", (14, 13))
        self._move(room, "sven", (14, 14))

        # Kampf Runde 1
        self._log("Kampf in den Katakomben!")
        self._move(room, "aldric", (7, 13))
        self._attack(room, "aldric", "skel_1", "melee", 5)
        self._attack(room, "skel_1", "aldric", "melee", 3)

        # Rowan schiesst
        self._move(room, "rowan", (22, 7))
        self._attack(room, "rowan", "skel_2", "ranged", 4)

        # Elara zaubert
        self._move(room, "elara", (14, 13))
        self._cast_offensive(room, "elara", "zomb_1", 5)

        # Sven vs Orc
        self._move(room, "sven", (11, 14))
        self._attack(room, "sven", "orc_1", "melee", 5)
        self._attack(room, "orc_1", "sven", "melee", 4)

        # Runde 2
        self._attack(room, "aldric", "skel_1", "melee", 5)
        if "skel_1" in room.entities:
            self._attack(room, "aldric", "skel_1", "melee", 4)

        self._cast_offensive(room, "elara", "zomb_1", 5)
        self._attack(room, "rowan", "skel_2", "ranged", 5)
        if "skel_2" in room.entities:
            self._attack(room, "rowan", "skel_2", "ranged", 4)

        # Runde 3: Orc
        self._attack(room, "sven", "orc_1", "melee", 5)
        self._attack(room, "orc_1", "sven", "melee", 5)
        self._attack(room, "aldric", "orc_1", "melee", 6)
        if "orc_1" in room.entities:
            self._attack(room, "sven", "orc_1", "melee", 5)

        # Zombie aufräumen
        if "zomb_1" in room.entities:
            self._cast_offensive(room, "elara", "zomb_1", 6)
        if "zomb_1" in room.entities:
            self._attack(room, "kira", "zomb_1", "melee", 4)

        # Loot nach Kampf
        self._pickup(room, "sven", "Schild der Ahnen", 19, 13)

        # Heilung
        self._log("Thorin spricht Heilgebete...")
        self._cast_heal(room, "thorin", "aldric", 4, "Heiliges Licht")
        self._cast_heal(room, "thorin", "sven", 5, "Goettlicher Segen")
        # Sven heilt sich selbst
        self._cast_heal(room, "sven", "sven", 3, "Handauflegen")
        time.sleep(1.5)

    # ══════════════════════════════════════════════════════════════════════
    # Akt 4: Thronsaal — Boss
    # ══════════════════════════════════════════════════════════════════════

    def _act4_throne(self) -> None:
        self._phase("Akt 4: Thronsaal — Bosskampf")
        self._log("--- Akt 4: Thronsaal ---", "phase")
        room = self._setup_room("thronsaal", _make_throne_room(),
                                exits={"sued": [11, 13]})
        time.sleep(0.5)

        self._place_heroes(room, [
            ("aldric", 9, 11), ("elara", 11, 11), ("thorin", 13, 11),
            ("kira", 10, 12), ("rowan", 12, 12), ("sven", 11, 10),
        ])
        time.sleep(2.0)

        # Boss + Wachen
        self._log("Ein gewaltiger Ork-Kriegsherr erhebt sich!", "kill")
        self._spawn(room, "boss", "Orc", 11, 3, 32)
        time.sleep(0.5)
        self._spawn(room, "guard_1", "Skeleton", 7, 5, 10)
        self._spawn(room, "guard_2", "Skeleton", 15, 5, 10)
        time.sleep(2.0)

        # Angriff!
        self._log("Zum Angriff!", "phase")
        self._move(room, "aldric", (9, 6))
        self._move(room, "sven", (13, 6))
        self._move(room, "kira", (8, 7))

        # Wachen bekaempfen
        self._attack(room, "aldric", "guard_1", "melee", 6)
        self._attack(room, "guard_1", "aldric", "melee", 3)
        self._attack(room, "sven", "guard_2", "melee", 5)
        self._attack(room, "guard_2", "sven", "melee", 2)

        # Magie auf Boss
        self._cast_offensive(room, "elara", "boss", 5)
        self._attack(room, "rowan", "boss", "ranged", 4)

        # Wachen erledigen
        if "guard_1" in room.entities:
            self._attack(room, "aldric", "guard_1", "melee", 6)
        if "guard_2" in room.entities:
            self._attack(room, "kira", "guard_2", "melee", 6)
        if "guard_1" in room.entities:
            self._attack(room, "kira", "guard_1", "melee", 5)
        if "guard_2" in room.entities:
            self._attack(room, "sven", "guard_2", "melee", 5)

        # Boss greift an
        if "boss" in room.entities:
            self._move(room, "boss", (11, 6))
            self._attack(room, "boss", "aldric", "melee", 6)
            self._attack(room, "boss", "sven", "melee", 5)

        # Alle auf den Boss
        self._log("Alle auf den Kriegsherrn!", "phase")
        for _ in range(3):
            if "boss" not in room.entities:
                break
            self._attack(room, "aldric", "boss", "melee", 5)
            if "boss" not in room.entities:
                break
            self._cast_offensive(room, "elara", "boss", 6)
            if "boss" not in room.entities:
                break
            self._attack(room, "sven", "boss", "melee", 5)
            if "boss" not in room.entities:
                break
            self._attack(room, "rowan", "boss", "ranged", 4)

        # Sicherheits-Kill falls Boss noch lebt
        if "boss" in room.entities:
            self._attack(room, "kira", "boss", "melee", 99)

        self._log("Der Kriegsherr faellt!", "phase")
        time.sleep(1.5)

        # Loot
        self._pickup(room, "thorin", "Kronjuwel", 11, 3)

        # Heilung
        self._log("Thorin heilt die Verwundeten...")
        self._cast_heal(room, "thorin", "aldric", 5, "Heiliges Licht")
        self._cast_heal(room, "thorin", "sven", 4, "Goettlicher Segen")
        self._cast_heal(room, "sven", "sven", 3, "Handauflegen")
        time.sleep(2.0)

    # ══════════════════════════════════════════════════════════════════════
    # Akt 5: Schatzkammer — Finale
    # ══════════════════════════════════════════════════════════════════════

    def _act5_treasure(self) -> None:
        self._phase("Akt 5: Schatzkammer")
        self._log("--- Akt 5: Schatzkammer ---", "phase")
        room = self._setup_room("schatzkammer", _make_treasure(),
                                exits={"west": [0, 5]})
        time.sleep(0.5)

        self._place_heroes(room, [
            ("aldric", 2, 5), ("elara", 2, 6), ("thorin", 3, 5),
            ("kira", 3, 6), ("rowan", 2, 7), ("sven", 3, 7),
        ])
        time.sleep(2.0)

        # NPC
        npc = GridEntity(
            entity_id="merchant", name="Merchant",
            entity_type="npc", x=12, y=4, symbol="?",
        )
        room.place_entity(npc)
        self._log("Ein Haendler wartet in der Schatzkammer...")
        time.sleep(1.5)

        # Helden erkunden + Loot
        self._log("Die Helden durchsuchen die Kammer...")
        self._pickup(room, "kira", "Magischer Ring", 14, 2)
        self._pickup(room, "aldric", "Goldpokal", 3, 2)
        self._pickup(room, "elara", "Zaubertrank", 14, 9)
        self._pickup(room, "rowan", "Elfenbogen", 3, 9)
        self._pickup(room, "sven", "Adamant-Helm", 8, 6)
        self._pickup(room, "thorin", "Heilige Schriftrolle", 9, 6)

        # Kira zum Haendler
        self._move(room, "kira", (11, 4))
        self._log("Kira handelt mit dem Haendler...")
        time.sleep(2.0)

        self._log("Schaetze gefunden! Abenteuer beendet.", "phase")
        time.sleep(3.0)

    # ══════════════════════════════════════════════════════════════════════
    # Akt 6: Grosse Kreaturen — Groessen-Test
    # ══════════════════════════════════════════════════════════════════════

    def _act6_large_creatures(self) -> None:
        self._phase("Akt 6: Grosse Kreaturen")
        self._log("--- Akt 6: Grosse Kreaturen ---", "phase")

        # Grosse Arena
        W, H = 28, 20
        t = [["wall"] * W for _ in range(H)]
        for y in range(1, H - 1):
            for x in range(1, W - 1):
                t[y][x] = "floor"
        t[0][14] = "door"

        room = self._setup_room("arena", t, exits={"nord": [14, 0]})
        time.sleep(0.5)

        self._place_heroes(room, [
            ("aldric", 5, 16), ("elara", 7, 16), ("thorin", 9, 16),
            ("kira", 11, 16), ("rowan", 13, 16), ("sven", 15, 16),
        ])
        time.sleep(2.0)

        # Oger (L) spawnen
        self._log("Ein gewaltiger Oger betritt die Arena!", "kill")
        oger = GridEntity(
            entity_id="oger_boss", name="Oger", entity_type="monster",
            x=10, y=5, symbol="?", movement_rate=8, size="L",
        )
        room.place_entity(oger)
        self.ps.init_monster("oger_boss", 25, "Keule")
        time.sleep(2.0)

        # Troll (H) spawnen
        self._log("Ein riesiger Troll erscheint!", "kill")
        troll = GridEntity(
            entity_id="troll_boss", name="Troll", entity_type="monster",
            x=18, y=5, symbol="?", movement_rate=10, size="H",
        )
        room.place_entity(troll)
        self.ps.init_monster("troll_boss", 35, "Klauen")
        time.sleep(2.0)

        # Drache (G) spawnen
        self._log("Ein gewaltiger Drache landet in der Mitte!", "kill")
        drache = GridEntity(
            entity_id="drache_boss", name="Drache", entity_type="monster",
            x=14, y=8, symbol="?", movement_rate=12, size="G",
        )
        room.place_entity(drache)
        self.ps.init_monster("drache_boss", 80, "Feueratem")
        time.sleep(3.0)

        # Kampf gegen den Oger
        self._log("Angriff auf den Oger!")
        self._move(room, "aldric", (9, 6))
        self._attack(room, "aldric", "oger_boss", "melee", 6)
        self._attack(room, "sven", "oger_boss", "melee", 7)
        self._cast_offensive(room, "elara", "oger_boss", 8)
        if "oger_boss" in room.entities:
            self._attack(room, "aldric", "oger_boss", "melee", 99)
        time.sleep(1.0)

        # Kampf gegen den Troll
        self._log("Der Troll regeneriert!")
        self._move(room, "sven", (17, 6))
        self._attack(room, "sven", "troll_boss", "melee", 8)
        self._cast_offensive(room, "elara", "troll_boss", 10)
        self._attack(room, "rowan", "troll_boss", "ranged", 6)
        if "troll_boss" in room.entities:
            self._attack(room, "sven", "troll_boss", "melee", 99)
        time.sleep(1.0)

        # Drache: alle zusammen
        self._log("Alle auf den Drachen!", "phase")
        for _ in range(3):
            if "drache_boss" not in room.entities:
                break
            self._attack(room, "aldric", "drache_boss", "melee", 8)
            if "drache_boss" not in room.entities:
                break
            self._cast_offensive(room, "elara", "drache_boss", 12)
            if "drache_boss" not in room.entities:
                break
            self._attack(room, "sven", "drache_boss", "melee", 10)
            if "drache_boss" not in room.entities:
                break
            self._attack(room, "rowan", "drache_boss", "ranged", 8)
        if "drache_boss" in room.entities:
            self._attack(room, "kira", "drache_boss", "melee", 99)

        self._log("Die Kreaturen sind besiegt!", "phase")

        # Heilung
        self._cast_heal(room, "thorin", "aldric", 6, "Heiliges Licht")
        self._cast_heal(room, "thorin", "sven", 5, "Goettlicher Segen")
        time.sleep(2.0)

    # ══════════════════════════════════════════════════════════════════════
    # Akt 7: Zauber-Effekte — Effekt-Demo
    # ══════════════════════════════════════════════════════════════════════

    def _act7_spell_effects(self) -> None:
        self._phase("Akt 7: Zauber-Effekte")
        self._log("--- Akt 7: Zauber-Effekte ---", "phase")

        # Kleine Arena
        W, H = 20, 14
        t = [["wall"] * W for _ in range(H)]
        for y in range(1, H - 1):
            for x in range(1, W - 1):
                t[y][x] = "floor"

        room = self._setup_room("zauberarena", t)
        time.sleep(0.5)

        self._place_heroes(room, [
            ("aldric", 4, 10), ("elara", 6, 10), ("thorin", 8, 10),
            ("kira", 10, 10), ("rowan", 12, 10), ("sven", 14, 10),
        ])
        time.sleep(1.5)

        # Dummy-Monster fuer Zielscheiben
        dummies = [
            ("dummy_1", "Skelett-Dummy", 4, 3, 50),
            ("dummy_2", "Zombie-Dummy", 10, 3, 50),
            ("dummy_3", "Daemon-Dummy", 16, 3, 50),
        ]
        for did, dname, dx, dy, dhp in dummies:
            self._spawn(room, did, dname, dx, dy, dhp)
        time.sleep(1.5)

        # Elara demonstriert verschiedene Zauber
        spells = [
            ("Feuerpfeil", "dummy_1", 8),
            ("Eissplitter", "dummy_2", 7),
            ("Magisches Geschoss", "dummy_3", 6),
        ]
        for spell_name, target, dmg in spells:
            self._log(f"Elara wirkt '{spell_name}'!", "spell")
            self._cast_offensive(room, "elara", target, dmg, spell=spell_name)
            time.sleep(0.5)

        # Thorin demonstriert Heil-Zauber
        self._log("Thorin demonstriert Heil-Magie...", "spell")
        self._cast_heal(room, "thorin", "aldric", 3, "Heiliges Licht")
        self._cast_heal(room, "thorin", "sven", 3, "Goettlicher Segen")

        # Sven: Handauflegen
        self._cast_heal(room, "sven", "sven", 2, "Handauflegen")

        # Offensive Zauber auf verbleibende Dummies
        if "dummy_1" in room.entities:
            self._cast_offensive(room, "elara", "dummy_1", 50, spell="Feuerpfeil")
        if "dummy_2" in room.entities:
            self._cast_offensive(room, "elara", "dummy_2", 50, spell="Eissplitter")
        if "dummy_3" in room.entities:
            self._cast_offensive(room, "elara", "dummy_3", 50, spell="Magisches Geschoss")

        self._log("Zauber-Demo beendet!", "phase")
        time.sleep(3.0)


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    logger.info("Bot Graphics Test gestartet")
    EventBus.reset()
    gui = MinimalGUI()
    gui.run()


if __name__ == "__main__":
    main()
