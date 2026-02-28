# TASK 57: Thematic Packages (Presets)

## Ziel
Kapselung des Ist-Zustandes als "Cthulhu"-Standard und Vorbereitung der AD&D-Umgebung zur sauberen Trennung der Welten.

## 1. Verzeichnisstruktur
Erstelle einen neuen Ordner: `modules/presets/`.

## 2. Das Cthulhu-Paket (`modules/presets/coc_classic.json`)
Erstelle diese JSON mit dem Ist-Stand:
- `ruleset`: "cthulhu_7e"
- `adventure`: "spukhaus"
- `difficulty`: "hardcore"
- `atmosphere`: "1920s Cosmic Horror, duester, hoffnungslos, lovecraftian."
- `keeper_persona`: "Ein unheilvoller Archivar, der langsam spricht und das Unbekannte betont. Klinisch und unerbittlich bei Verletzungen."
- `language`: "de-DE"

## 3. Das AD&D-Paket (`modules/presets/add_fantasy.json`)
Erstelle den Prototyp fuer die naechste Engine:
- `ruleset`: "add_2e" (als Platzhalter fuer zukuenftiges JSON)
- `adventure`: "free_roam"
- `difficulty`: "heroic"
- `atmosphere`: "High Fantasy, episch, heroisch, gefaehrliche Dungeons, magisch."
- `keeper_persona`: "Ein epischer Barde und strenger Dungeon Master. Beschreibt Magie farbenfroh, Kaempfe taktisch und feiert heldenhafte Taten."
- `language`: "de-DE"

## Dokumentationspflicht
- Aktualisiere `modules/index.json` um die neue Kategorie "presets".
- Eintrag in `AGENTS.md` unter Agent Reports.
