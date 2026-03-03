"""
gui/tab_dungeon_view.py — Tab 12: Dungeon-Visualisierung

Canvas-basierte Dungeon-Karte mit:
  - BFS Auto-Layout aus Adventure-Exits (Richtungs-Parsing)
  - Fog of War (unbesuchte Raeume verdeckt)
  - Party- und Monster-Marker (Unicode-Symbole)
  - Klick-Navigation (angrenzende Raeume per Klick betreten)
  - Info-Panel (Raum-Beschreibung, Ausgaenge, Entities)
  - Aktions-Log (Kampf, Bewegung, Proben, Items)
  - Sound-Effekte (winsound.Beep fuer Kampf, Schaden, Proben, etc.)
  - Visuelle Flash-Effekte (Raum blinkt bei Kampf/Schaden)

Events:
  - adventure.loaded → Karten-Layout generieren
  - adventure.location_changed → Party-Marker bewegen
  - game.output (combat/stat/probe/dice/inventory) → Log + Sound + Flash
  - party.state_updated / member_died / tpk → Party-Anzeige
  - adventure.flag_changed → Monster-Tracking (besiegt-Flags)
"""

from __future__ import annotations

import logging
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

# ── Dungeon-Symbole (Unicode) ──────────────────────────────────────────────────

SYM_PARTY = "@"
SYM_MONSTER = "M"
SYM_DEAD = "\u2620"      # ☠
SYM_TRAP = "!"
SYM_TREASURE = "$"
SYM_ITEM = "\u2666"      # ♦

# ── Raum-Farben ────────────────────────────────────────────────────────────────

CLR_CURRENT = "#2A4A3A"          # Aktueller Raum (gruen-tint)
CLR_VISITED = "#2D2D3D"          # Besuchter Raum
CLR_UNVISITED = "#1A1A2A"        # Unbesuchter Raum (Fog)
CLR_BORDER_CURRENT = GREEN
CLR_BORDER_VISITED = FG_MUTED
CLR_BORDER_UNVISITED = "#333344"
CLR_CORRIDOR = FG_MUTED
CLR_CORRIDOR_FOG = "#222233"

# ── Raum-Dimensionen ──────────────────────────────────────────────────────────

ROOM_W = 180
ROOM_H = 100
ROOM_GAP = 60
GRID_DX = ROOM_W + ROOM_GAP
GRID_DY = ROOM_H + ROOM_GAP

# ── Richtungs-Hints aus deutschen Exit-Beschreibungen ─────────────────────────

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

_DIRECTIONS = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)]


class DungeonViewTab(ttk.Frame):
    """Dungeon-Visualisierung: Canvas-Karte, Info-Panel, Aktions-Log, Sounds."""

    def __init__(self, parent: ttk.Notebook, gui: "TechGUI") -> None:
        super().__init__(parent)
        self.gui = gui
        self.configure(style="TFrame")

        # State
        self._rooms: dict[str, dict] = {}
        self._current_room: str | None = None
        self._visited: set[str] = set()
        self._room_items: dict[str, list[int]] = {}
        self._monster_pos: dict[str, list[str]] = {}
        self._sounds_on: bool = True
        self._offset_x: int = 0
        self._offset_y: int = 0

        self._build_ui()

    # ══════════════════════════════════════════════════════════════════════════
    # UI Build
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)

        # ── Links: Canvas-Karte ──
        map_frame = ttk.LabelFrame(paned, text=" Dungeon-Karte ", style="TLabelframe")
        paned.add(map_frame, weight=3)

        self._canvas = tk.Canvas(
            map_frame, bg=BG_DARK, highlightthickness=0,
            scrollregion=(0, 0, 2000, 2000),
        )
        h_sb = ttk.Scrollbar(map_frame, orient=tk.HORIZONTAL, command=self._canvas.xview)
        v_sb = ttk.Scrollbar(map_frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(xscrollcommand=h_sb.set, yscrollcommand=v_sb.set)
        v_sb.pack(side=tk.RIGHT, fill=tk.Y)
        h_sb.pack(side=tk.BOTTOM, fill=tk.X)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # ── Rechts: Info-Panel ──
        info = ttk.Frame(paned, style="TFrame")
        paned.add(info, weight=1)

        # Aktueller Ort
        loc_lf = ttk.LabelFrame(info, text=" Aktueller Ort ", style="TLabelframe")
        loc_lf.pack(fill=tk.X, padx=PAD_SMALL, pady=PAD_SMALL)

        self._loc_name = ttk.Label(loc_lf, text="\u2014", style="Header.TLabel")
        self._loc_name.pack(anchor=tk.W, padx=PAD, pady=(PAD_SMALL, 0))

        self._loc_desc = tk.Text(
            loc_lf, height=5, bg=BG_PANEL, fg=FG_SECONDARY,
            font=FONT_SMALL, wrap=tk.WORD, state=tk.DISABLED,
            highlightthickness=0, borderwidth=0,
        )
        self._loc_desc.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        # Ausgaenge
        exits_lf = ttk.LabelFrame(info, text=" Ausg\u00e4nge ", style="TLabelframe")
        exits_lf.pack(fill=tk.X, padx=PAD_SMALL, pady=PAD_SMALL)
        self._exits_frame = ttk.Frame(exits_lf, style="TFrame")
        self._exits_frame.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        # Entities
        ent_lf = ttk.LabelFrame(info, text=" Im Raum ", style="TLabelframe")
        ent_lf.pack(fill=tk.X, padx=PAD_SMALL, pady=PAD_SMALL)

        self._ent_text = tk.Text(
            ent_lf, height=5, bg=BG_PANEL, fg=FG_PRIMARY,
            font=FONT_SMALL, wrap=tk.WORD, state=tk.DISABLED,
            highlightthickness=0, borderwidth=0,
        )
        self._ent_text.tag_configure("party", foreground=GREEN)
        self._ent_text.tag_configure("monster", foreground=RED)
        self._ent_text.tag_configure("dead", foreground=FG_MUTED)
        self._ent_text.pack(fill=tk.X, padx=PAD, pady=PAD_SMALL)

        # Aktions-Log
        log_lf = ttk.LabelFrame(info, text=" Aktionen ", style="TLabelframe")
        log_lf.pack(fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)

        self._log = tk.Text(
            log_lf, bg=BG_DARK, fg=FG_PRIMARY, font=FONT_SMALL,
            wrap=tk.WORD, state=tk.DISABLED, highlightthickness=0, borderwidth=0,
        )
        log_sb = ttk.Scrollbar(log_lf, orient=tk.VERTICAL, command=self._log.yview)
        self._log.configure(yscrollcommand=log_sb.set)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=PAD_SMALL, pady=PAD_SMALL)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y, pady=PAD_SMALL)

        for tag, color in [
            ("combat", RED), ("move", GREEN), ("probe", YELLOW),
            ("item", BLUE), ("stat", ORANGE), ("system", FG_MUTED),
        ]:
            self._log.tag_configure(tag, foreground=color)

        # Controls + Legende
        ctrl = ttk.Frame(info, style="TFrame")
        ctrl.pack(fill=tk.X, padx=PAD_SMALL, pady=PAD_SMALL)

        self._snd_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            ctrl, text="Sound", variable=self._snd_var,
            command=lambda: setattr(self, "_sounds_on", self._snd_var.get()),
        ).pack(side=tk.LEFT, padx=PAD_SMALL)
        ttk.Button(ctrl, text="Zentrieren", command=self._center_view).pack(
            side=tk.LEFT, padx=PAD_SMALL,
        )

        legend = ttk.LabelFrame(info, text=" Legende ", style="TLabelframe")
        legend.pack(fill=tk.X, padx=PAD_SMALL, pady=(0, PAD_SMALL))
        for sym, label, color in [
            (SYM_PARTY, "Party", GREEN), (SYM_MONSTER, "Monster", RED),
            (SYM_DEAD, "Tot", FG_MUTED), (SYM_TRAP, "Falle", YELLOW),
            (SYM_TREASURE, "Schatz", ORANGE), (SYM_ITEM, "Gegenstand", BLUE),
        ]:
            row = ttk.Frame(legend, style="TFrame")
            row.pack(fill=tk.X, padx=PAD_SMALL)
            tk.Label(row, text=sym, bg=BG_DARK, fg=color, font=FONT_BOLD, width=3).pack(side=tk.LEFT)
            ttk.Label(row, text=label).pack(side=tk.LEFT)

    # ══════════════════════════════════════════════════════════════════════════
    # Layout-Algorithmus (BFS mit Richtungs-Parsing)
    # ══════════════════════════════════════════════════════════════════════════

    def _generate_layout(self, adv_data: dict) -> None:
        """BFS-basiertes Auto-Layout der Dungeon-Raeume aus Adventure-Exits."""
        self._rooms.clear()
        self._room_items.clear()
        self._visited.clear()
        self._monster_pos.clear()

        locations: dict[str, dict] = {}
        for loc in adv_data.get("locations", []):
            if isinstance(loc, dict) and "id" in loc:
                locations[loc["id"]] = loc

        if not locations:
            return

        start = adv_data.get("start_location") or next(iter(locations))

        # BFS placement
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

            dir_idx = 0
            for dest_id, desc in exit_list:
                if dest_id in placed or dest_id not in locations:
                    continue

                # Richtung aus Beschreibung ableiten
                target = None
                dl = desc.lower() if desc else ""
                for hint, dvec in _DIR_HINTS.items():
                    if hint in dl:
                        target = dvec
                        break

                attempts = ([target] + [d for d in _DIRECTIONS if d != target]) if target \
                    else _DIRECTIONS[dir_idx:] + _DIRECTIONS[:dir_idx]
                dir_idx = (dir_idx + 1) % len(_DIRECTIONS)

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

        # Nicht platzierte (isolierte) Raeume
        ny = (max(gy for _, gy in placed.values()) + 2) if placed else 0
        for lid in locations:
            if lid not in placed:
                placed[lid] = (0, ny)
                grid[(0, ny)] = lid
                ny += 1

        # Monster-Positionen aus NPC-Daten
        npc_index = {}
        for npc in adv_data.get("npcs", []):
            if isinstance(npc, dict) and "id" in npc:
                npc_index[npc["id"]] = npc.get("name", npc["id"])

        for loc in adv_data.get("locations", []):
            if not isinstance(loc, dict) or "id" not in loc:
                continue
            npc_ids = loc.get("npcs_present", [])
            if npc_ids:
                self._monster_pos[loc["id"]] = [npc_index.get(n, n) for n in npc_ids]

        # Raeume speichern
        for lid, (gx, gy) in placed.items():
            self._rooms[lid] = {
                "gx": gx, "gy": gy,
                "data": locations.get(lid, {}),
                "visited": False,
            }

    # ══════════════════════════════════════════════════════════════════════════
    # Canvas-Rendering
    # ══════════════════════════════════════════════════════════════════════════

    def _render_map(self) -> None:
        """Zeichnet die komplette Dungeon-Karte neu."""
        self._canvas.delete("all")
        self._room_items.clear()

        if not self._rooms:
            self._canvas.create_text(
                400, 300, text="Kein Abenteuer geladen",
                fill=FG_MUTED, font=FONT_HEADER,
            )
            return

        # Bounds + Offset
        min_gx = min(r["gx"] for r in self._rooms.values())
        min_gy = min(r["gy"] for r in self._rooms.values())
        max_gx = max(r["gx"] for r in self._rooms.values())
        max_gy = max(r["gy"] for r in self._rooms.values())

        ox = 120 - min_gx * GRID_DX
        oy = 120 - min_gy * GRID_DY
        self._offset_x, self._offset_y = ox, oy

        tw = (max_gx - min_gx + 1) * GRID_DX + 240
        th = (max_gy - min_gy + 1) * GRID_DY + 240
        self._canvas.configure(scrollregion=(0, 0, tw, th))

        # Korridore (hinter Raeumen)
        drawn_corridors: set[tuple[str, str]] = set()
        for lid, room in self._rooms.items():
            cx = room["gx"] * GRID_DX + ox + ROOM_W // 2
            cy = room["gy"] * GRID_DY + oy + ROOM_H // 2
            exits = room["data"].get("exits", {})
            eids = exits.keys() if isinstance(exits, dict) else exits
            for did in eids:
                if did not in self._rooms:
                    continue
                pair = tuple(sorted([lid, did]))
                if pair in drawn_corridors:
                    continue
                drawn_corridors.add(pair)

                dest = self._rooms[did]
                dx = dest["gx"] * GRID_DX + ox + ROOM_W // 2
                dy = dest["gy"] * GRID_DY + oy + ROOM_H // 2

                visible = room["visited"] or dest["visited"]
                self._canvas.create_line(
                    cx, cy, dx, dy,
                    fill=CLR_CORRIDOR if visible else CLR_CORRIDOR_FOG,
                    width=2, dash=(4, 4),
                )

        # Raeume
        for lid, room in self._rooms.items():
            self._draw_room(lid, room, ox, oy)

    def _draw_room(self, lid: str, room: dict, ox: int, oy: int) -> None:
        """Zeichnet einen einzelnen Raum als Rechteck mit Symbolen."""
        x = room["gx"] * GRID_DX + ox
        y = room["gy"] * GRID_DY + oy
        is_cur = (lid == self._current_room)
        is_vis = room["visited"]

        if is_cur:
            bg, border, fg, bw = CLR_CURRENT, CLR_BORDER_CURRENT, FG_PRIMARY, 3
        elif is_vis:
            bg, border, fg, bw = CLR_VISITED, CLR_BORDER_VISITED, FG_SECONDARY, 1
        else:
            bg, border, fg, bw = CLR_UNVISITED, CLR_BORDER_UNVISITED, FG_MUTED, 1

        ids: list[int] = []

        # Rechteck
        rect = self._canvas.create_rectangle(
            x, y, x + ROOM_W, y + ROOM_H,
            fill=bg, outline=border, width=bw,
        )
        ids.append(rect)

        # Raum-Name (gekuerzt)
        name = room["data"].get("name", lid)
        if len(name) > 22:
            name = name[:20] + ".."
        ids.append(self._canvas.create_text(
            x + ROOM_W // 2, y + 16,
            text=name, fill=fg, font=FONT_SMALL,
            anchor=tk.CENTER, width=ROOM_W - 12,
        ))

        # Entity-Symbole oder Fog
        if is_vis or is_cur:
            syms = self._room_symbols(lid, is_cur)
            if syms:
                ids.append(self._canvas.create_text(
                    x + ROOM_W // 2, y + ROOM_H // 2 + 8,
                    text=syms, fill=FG_PRIMARY, font=("Consolas", 14),
                    anchor=tk.CENTER,
                ))
        else:
            ids.append(self._canvas.create_text(
                x + ROOM_W // 2, y + ROOM_H // 2 + 8,
                text="?", fill=FG_MUTED, font=("Consolas", 16, "bold"),
                anchor=tk.CENTER,
            ))

        # Ebene-Indikator (falls im Namen)
        name_full = room["data"].get("name", "")
        for lvl_key, lvl_label in [("Ebene 1", "E1"), ("Ebene 2", "E2"), ("Ebene 3", "E3")]:
            if lvl_key in name_full:
                ids.append(self._canvas.create_text(
                    x + ROOM_W - 8, y + ROOM_H - 8,
                    text=lvl_label, fill=FG_MUTED, font=FONT_SMALL,
                    anchor=tk.SE,
                ))
                break

        # Klick-Binding
        for item_id in ids:
            self._canvas.tag_bind(item_id, "<Button-1>",
                                  lambda _e, _lid=lid: self._on_room_click(_lid))

        self._room_items[lid] = ids

    def _room_symbols(self, lid: str, is_current: bool) -> str:
        """Baut die Entity-Symbol-Zeile fuer einen Raum."""
        parts: list[str] = []

        if is_current:
            engine = self.gui.engine
            ps = getattr(engine, "party_state", None)
            if ps and hasattr(ps, "alive_members"):
                n = len(ps.alive_members())
                parts.append(SYM_PARTY * min(n, 6))
            else:
                parts.append(SYM_PARTY)

        monsters = self._monster_pos.get(lid, [])
        if monsters:
            parts.append(SYM_MONSTER * min(len(monsters), 5))

        return " ".join(parts)

    # ══════════════════════════════════════════════════════════════════════════
    # Interaktion
    # ══════════════════════════════════════════════════════════════════════════

    def _on_room_click(self, lid: str) -> None:
        """Klick auf Raum: Info anzeigen, ggf. Teleport (wenn angrenzend)."""
        self._update_info(lid)

        if self._current_room and lid != self._current_room:
            cur_exits = self._rooms.get(self._current_room, {}).get("data", {}).get("exits", {})
            adj = cur_exits.keys() if isinstance(cur_exits, dict) else cur_exits
            if lid in adj:
                engine = self.gui.engine
                if hasattr(engine, "_adv_manager") and engine._adv_manager:
                    engine._adv_manager.teleport(lid)

    def _on_exit_click(self, dest_id: str) -> None:
        """Ausgaenge-Button: Teleport."""
        engine = self.gui.engine
        if hasattr(engine, "_adv_manager") and engine._adv_manager:
            engine._adv_manager.teleport(dest_id)

    def _update_info(self, lid: str) -> None:
        """Aktualisiert das Info-Panel fuer den gewaehlten Raum."""
        room = self._rooms.get(lid)
        if not room:
            return
        data = room["data"]

        # Name
        self._loc_name.configure(text=data.get("name", lid))

        # Beschreibung
        self._loc_desc.configure(state=tk.NORMAL)
        self._loc_desc.delete("1.0", tk.END)
        desc = data.get("description", "")
        atmo = data.get("atmosphere", "")
        if atmo:
            desc += f"\n\n{atmo}"
        self._loc_desc.insert(tk.END, desc[:400])
        self._loc_desc.configure(state=tk.DISABLED)

        # Ausgaenge als Buttons
        for w in self._exits_frame.winfo_children():
            w.destroy()
        exits = data.get("exits", {})
        if isinstance(exits, dict):
            for did, _desc in exits.items():
                dname = self._rooms.get(did, {}).get("data", {}).get("name", did)
                if len(dname) > 28:
                    dname = dname[:26] + ".."
                ttk.Button(
                    self._exits_frame, text=f"\u2192 {dname}",
                    command=lambda d=did: self._on_exit_click(d),
                ).pack(fill=tk.X, pady=1)

        # Entities
        self._ent_text.configure(state=tk.NORMAL)
        self._ent_text.delete("1.0", tk.END)

        monsters = self._monster_pos.get(lid, [])
        if monsters:
            for m in monsters:
                self._ent_text.insert(tk.END, f"  {SYM_MONSTER} {m}\n", "monster")

        if lid == self._current_room:
            engine = self.gui.engine
            ps = getattr(engine, "party_state", None)
            if ps and hasattr(ps, "alive_members"):
                for member in ps.alive_members():
                    hp_pct = (member.hp / member.hp_max * 100) if member.hp_max > 0 else 0
                    tag = "party" if hp_pct > 25 else "dead"
                    self._ent_text.insert(
                        tk.END,
                        f"  {SYM_PARTY} {member.name}  HP {member.hp}/{member.hp_max}"
                        f"  AC {member.ac}\n",
                        tag,
                    )
            elif engine.character:
                c = engine.character
                hp = c._stats.get("HP", "?")
                hp_max = c._stats_max.get("HP", "?")
                self._ent_text.insert(tk.END, f"  {SYM_PARTY} {c.name}  HP {hp}/{hp_max}\n", "party")

        if not monsters and lid != self._current_room:
            npcs = data.get("npcs_present", [])
            if npcs:
                for n in npcs:
                    self._ent_text.insert(tk.END, f"  {n}\n")

        if self._ent_text.get("1.0", tk.END).strip() == "":
            self._ent_text.insert(tk.END, "  (leer)")

        self._ent_text.configure(state=tk.DISABLED)

    # ══════════════════════════════════════════════════════════════════════════
    # Sound-System (winsound.Beep, Windows only, Thread-basiert)
    # ══════════════════════════════════════════════════════════════════════════

    def _play_sound(self, kind: str) -> None:
        if not self._sounds_on:
            return

        def _beep():
            try:
                import winsound
                if kind == "move":
                    winsound.Beep(500, 80)
                elif kind == "combat":
                    winsound.Beep(800, 80)
                    winsound.Beep(600, 80)
                elif kind == "hp_loss":
                    winsound.Beep(300, 200)
                    winsound.Beep(200, 200)
                elif kind == "probe":
                    winsound.Beep(1000, 50)
                    winsound.Beep(1200, 50)
                elif kind == "dice":
                    winsound.Beep(800, 40)
                    winsound.Beep(1000, 40)
                    winsound.Beep(1200, 40)
                elif kind == "item":
                    winsound.Beep(1000, 60)
                    winsound.Beep(1200, 60)
                    winsound.Beep(1400, 60)
                elif kind == "death":
                    winsound.Beep(200, 400)
                    winsound.Beep(150, 400)
                elif kind == "critical":
                    winsound.Beep(200, 150)
                    winsound.Beep(400, 100)
                    winsound.Beep(200, 150)
            except Exception:
                pass

        threading.Thread(target=_beep, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    # Visuelle Effekte
    # ══════════════════════════════════════════════════════════════════════════

    def _flash_room(self, lid: str, color: str, ms: int = 400) -> None:
        """Laesst den Raum-Hintergrund kurz in einer Farbe aufblitzen."""
        items = self._room_items.get(lid)
        if not items:
            return
        rect_id = items[0]
        try:
            original = self._canvas.itemcget(rect_id, "fill")
        except tk.TclError:
            return
        self._canvas.itemconfig(rect_id, fill=color)

        def _restore():
            try:
                if self._canvas.winfo_exists():
                    self._canvas.itemconfig(rect_id, fill=original)
            except tk.TclError:
                pass

        self._canvas.after(ms, _restore)

    # ══════════════════════════════════════════════════════════════════════════
    # Aktions-Log
    # ══════════════════════════════════════════════════════════════════════════

    def _log_action(self, text: str, tag: str = "system") -> None:
        self._log.configure(state=tk.NORMAL)
        self._log.insert(tk.END, f"  {text}\n", tag)
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    # ══════════════════════════════════════════════════════════════════════════
    # Zentrierung
    # ══════════════════════════════════════════════════════════════════════════

    def _center_view(self) -> None:
        """Zentriert Canvas auf den aktuellen Raum."""
        if not self._current_room or self._current_room not in self._rooms:
            return
        room = self._rooms[self._current_room]
        cx = room["gx"] * GRID_DX + self._offset_x + ROOM_W // 2
        cy = room["gy"] * GRID_DY + self._offset_y + ROOM_H // 2

        cw = self._canvas.winfo_width() or 800
        ch = self._canvas.winfo_height() or 600
        sr = self._canvas.cget("scrollregion").split()
        if len(sr) == 4:
            tw, th = float(sr[2]), float(sr[3])
            if tw > 0 and th > 0:
                self._canvas.xview_moveto(max(0, (cx - cw / 2) / tw))
                self._canvas.yview_moveto(max(0, (cy - ch / 2) / th))

    def _visit_room(self, lid: str) -> None:
        """Markiert Raum als besucht."""
        if lid in self._rooms:
            self._rooms[lid]["visited"] = True
            self._visited.add(lid)

    # ══════════════════════════════════════════════════════════════════════════
    # Engine Ready
    # ══════════════════════════════════════════════════════════════════════════

    def on_engine_ready(self) -> None:
        engine = self.gui.engine
        if hasattr(engine, "_adv_manager") and engine._adv_manager and engine._adv_manager.loaded:
            self._generate_layout(engine._adv_manager._data)
            self._current_room = engine._adv_manager.current_location_id
            if self._current_room:
                self._visit_room(self._current_room)
            self._render_map()
            self._canvas.after(200, self._center_view)
            if self._current_room:
                self._update_info(self._current_room)

    # ══════════════════════════════════════════════════════════════════════════
    # EventBus Handler
    # ══════════════════════════════════════════════════════════════════════════

    def handle_event(self, data: dict[str, Any]) -> None:
        event = data.get("_event", "")
        if not event:
            return

        # ── Adventure geladen → Karte generieren ──
        if event == "adventure.loaded":
            engine = self.gui.engine
            if hasattr(engine, "_adv_manager") and engine._adv_manager:
                self._generate_layout(engine._adv_manager._data)
                self._current_room = engine._adv_manager.current_location_id
                if self._current_room:
                    self._visit_room(self._current_room)
                self._render_map()
                self._canvas.after(200, self._center_view)
                if self._current_room:
                    self._update_info(self._current_room)
            return

        # ── Ortswechsel → Party bewegen ──
        if event == "adventure.location_changed":
            new_loc = data.get("new", "")
            loc_name = data.get("name", "?")
            self._current_room = new_loc
            self._visit_room(new_loc)
            self._render_map()
            self._center_view()
            self._update_info(new_loc)
            self._log_action(f"\u2192 {loc_name}", "move")
            self._play_sound("move")
            return

        # ── Game Output → Log + Sound + Flash ──
        if event == "game.output":
            tag = data.get("tag", "")
            text = data.get("text", "")

            if tag in ("combat", "combat_hit"):
                self._log_action(f"\u2694 {text[:80]}", "combat")
                self._play_sound("combat")
                if self._current_room:
                    self._flash_room(self._current_room, "#4A2020", 300)
                return

            if tag == "combat_miss":
                self._log_action(f"\u2694 {text[:80]}", "combat")
                self._play_sound("combat")
                return

            if tag == "stat":
                self._log_action(f"\u2665 {text[:80]}", "stat")
                txt_lower = text.lower()
                if "hp" in txt_lower and any(w in txt_lower for w in ("verlust", "verlier", "-")):
                    self._play_sound("hp_loss")
                    if self._current_room:
                        self._flash_room(self._current_room, "#4A1010", 500)
                return

            if tag == "probe":
                self._log_action(f"\u2728 {text[:80]}", "probe")
                self._play_sound("probe")
                return

            if tag == "dice":
                self._log_action(f"\u2728 {text[:80]}", "probe")
                self._play_sound("dice")
                return

            if tag == "inventory":
                self._log_action(f"{SYM_ITEM} {text[:80]}", "item")
                self._play_sound("item")
                return

            return

        # ── Party Events ──
        if event == "party.member_died":
            name = data.get("name", "?")
            self._log_action(f"{SYM_DEAD} {name} ist gefallen!", "combat")
            self._play_sound("death")
            if self._current_room:
                self._flash_room(self._current_room, "#4A0000", 800)
            return

        if event == "party.state_updated":
            if self._current_room:
                self._render_map()
                self._update_info(self._current_room)
            return

        if event == "party.tpk":
            self._log_action(f"{SYM_DEAD}{SYM_DEAD}{SYM_DEAD} TOTAL PARTY KILL {SYM_DEAD}{SYM_DEAD}{SYM_DEAD}", "combat")
            self._play_sound("death")
            return

        # ── Flag-Aenderung → Monster-Tracking ──
        if event == "adventure.flag_changed":
            key = data.get("key", "")
            if "besiegt" in key or "geraeumt" in key:
                # Versuche Monster aus dem zugehoerigen Raum zu entfernen
                stem = key.replace("_besiegt", "").replace("_geraeumt", "")
                for room_lid in list(self._monster_pos.keys()):
                    if stem in room_lid:
                        self._monster_pos[room_lid] = []
                self._render_map()
            return
