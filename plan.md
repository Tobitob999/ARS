# Plan: TXT-basiertes Dungeon-Crawl-Visualisierungssystem

## Ziel
Kompletter Rewrite von `gui/tab_dungeon_view.py`: Statt Canvas-Rechtecken ein monospace-Text-basiertes ASCII-Dungeon mit individueller Charakter-Bewegung, Fog of War, und niedlicher Darstellung.

## Layout (4-Panel-Ansicht im Tab)

```
+----------------------------------+------------------+
|                                  |  PARTY (6 Slots) |
|     ASCII DUNGEON MAP            |  [F] Borin  18/22|
|     (tk.Text, monospace,         |  [M] Elara  12/15|
|      scrollbar, read-only)       |  [C] Theron 20/20|
|                                  |  [T] Kira   14/16|
|                                  |  [R] Aldric 16/18|
|                                  |  [P] Seraph 24/28|
+----------------------------------+------------------+
|  SPIEL-LOG                       |  REGEL-LOG       |
|  (KI-Ausgabe, Aktionen,         |  (Proben, Wuerfel,|
|   Erzaehlung)                    |   Regelwarnungen) |
+----------------------------------+------------------+
```

## ASCII-Raum-Darstellung

Jeder Raum = festes Raster aus Zeichen. Beispiel eines 11x7-Raums:

```
+---[ ]---+
|    .    .|
|  F . M  .|
[ ]  .   .[ ]
|  T C   .|
|    R P  .|
+---[ ]---+
```

Zeichensatz:
- `+` Ecken, `-` horizontale Wand, `|` vertikale Wand
- `[ ]` Tuer/Ausgang (offen)
- `[X]` Tuer (gesperrt)
- `.` Boden (begehbar)
- `F/M/C/T/R/P` Party-Mitglieder (erster Buchstabe der Klasse, farbig)
- `m` Monster, `$` Schatz, `!` Falle, `☠` Leiche
- `~` Wasser, `#` Saeulen/Schutt, `^` Treppe hoch, `v` Treppe runter
- `?` Fog of War (nicht aufgedeckt)

## Implementierung — 6 Schritte

### Schritt 1: Raum-Grid-Generator (`_generate_room_grid`)
- Jeder Adventure-Location bekommt ein 11x7 char-Grid
- Exits → Tueren an N/S/O/W Waenden platzieren
- NPCs → Monster-Symbole (`m`) platzieren
- Atmosphaere-Keywords → Deko (`~` Wasser, `#` Schutt, `^v` Treppen)
- Party-Members → individuelle Symbole an Startposition (Tuer-Eingang)

### Schritt 2: Weltkarte (Uebersichtskarte aller Raeume)
- BFS-Layout bleibt (bestehender `_generate_layout` Algorithmus)
- Aber statt Canvas-Rechtecke: kompakte 5x3-Miniatur pro Raum in Text
- Verbindungslinien als `---` horizontal, `|` vertikal
- Aktueller Raum hervorgehoben, Fog fuer unbesuchte

### Schritt 3: Party-Panel (rechts oben)
- 6 Slots mit Klassen-Symbol, Name, HP-Balken (farbig)
- Aktiver Charakter hervorgehoben
- Tot = durchgestrichen/ausgegraut
- Equipment-Kurzliste bei Hover/Klick

### Schritt 4: Dual-Log (unten)
- Links: Spiel-Log (KI-Erzaehlung, Bewegung, Kampf-Narration)
- Rechts: Regel-Log (Proben, Wuerfel, HP-Aenderungen, Regelwarnungen)
- Farbige Tags wie bisher

### Schritt 5: Bewegungs-Integration
- Party bewegt sich als Gruppe von Raum zu Raum (via AdventureManager.teleport)
- INNERHALB eines Raums: Charakter-Positionen werden durch KI-Erzaehlung bewegt
- Neue Events: `dungeon.char_moved` (Name, x, y) fuer Intra-Raum-Bewegung
- KI-Antwort-Parser: Wenn Erzaehlung "betritt", "geht zu", "schleicht" enthaelt → Position updaten
- Einfache Heuristik: Kampf → Chars ruecken zu Monstern, Erkundung → verteilt

### Schritt 6: Sound + Effekte
- Bestehende winsound.Beep-Sounds bleiben
- Text-Flash: Raum-Hintergrund kurz aendern bei Kampf/Schaden
- Animations-Illusion: Charakter-Bewegung Schritt fuer Schritt rendern (after-Callbacks)

## Dateien

| Datei | Aktion | Beschreibung |
|-------|--------|------------|
| `gui/tab_dungeon_view.py` | REWRITE | Kompletter Neuaufbau mit tk.Text statt Canvas |
| `gui/tech_gui.py` | KEINE AENDERUNG | Tab-Registration bleibt identisch |
| Core-Dateien | KEINE AENDERUNG | Engine, Orchestrator, PartyState bleiben unberuehrt |

## Wichtig
- Nur 1 Datei wird geaendert: `gui/tab_dungeon_view.py`
- Keine Core-Aenderungen — das ist rein GUI/Visualisierung
- Bestehende Event-Handler-Signatur (`handle_event`, `on_engine_ready`) bleibt
- Sound-System wird uebernommen
