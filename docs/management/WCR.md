# ARS — World Creation Rules (WCR)

**Version:** 1.0
**Datum:** 2026-02-28
**Zweck:** Layoutvorgabe fuer KI-Agenten zur Erstellung von ARS-kompatiblem Content (Regelsysteme, Abenteuer, Presets, Lore-Daten).

---

## Inhaltsverzeichnis

1. [Ueberblick](#1-ueberblick)
2. [Verzeichnisstruktur](#2-verzeichnisstruktur)
3. [Ruleset-Module](#3-ruleset-module)
4. [Adventure-Module](#4-adventure-module)
5. [Preset-Dateien](#5-preset-dateien)
6. [Setting-Module](#6-setting-module)
7. [Keeper-Module](#7-keeper-module)
8. [Extras-Module](#8-extras-module)
9. [Character-Module](#9-character-module)
10. [Party-Module](#10-party-module)
11. [Lore-Daten](#11-lore-daten)
12. [Encoding & Formatierung](#12-encoding--formatierung)
13. [Checkliste fuer neue Module](#13-checkliste-fuer-neue-module)
14. [Referenz-Beispiele](#14-referenz-beispiele)
15. [Schema-Versionierung](#15-schema-versionierung)

---

## 1. Ueberblick

ARS (Advanced Roleplay Simulator) ist ein modulares Pen-&-Paper-Simulationssystem. Spielinhalte werden als JSON-Module bereitgestellt, die von der Engine zur Laufzeit geladen und validiert werden.

**Prinzipien:**
- Content-Erstellung ist **unabhaengig vom Hauptprogramm** — nur JSON-Dateien in der richtigen Struktur
- Jedes Modul (Ruleset, Adventure, Lore) ist **eigenstaendig einsetzbar**
- Die Engine **validiert** Rulesets beim Laden — fehlende Pflichtfelder fuehren zum Abbruch
- Adventures und Lore werden zur Laufzeit gelesen — sie muessen gueltige JSON-Dateien sein
- Alle Inhalte muessen dem hier dokumentierten Schema entsprechen

**Modultypen:**

| Typ | Verzeichnis | Zweck |
|-----|-------------|-------|
| Ruleset | `modules/rulesets/` | Regelsystem (Wuerfel, Attribute, Fertigkeiten, Kampf) |
| Adventure | `modules/adventures/` | Abenteuer-Szenario (Orte, NPCs, Hinweise, Handlung) |
| Setting | `modules/settings/` | Welt-Beschreibung (Geographie, Kultur, Technologie, Epoche) |
| Keeper | `modules/keepers/` | Spielleiter-Persoenlichkeit (Ton, Erzaehlstil, Philosophie) |
| Extras | `modules/extras/` | Optionale Erweiterungen (Atmosphaere-Pakete, Spielmodus-Modifier) |
| Character | `modules/characters/` | Charakter-Templates (Attribute, Fertigkeiten, Ausruestung) |
| Party | `modules/parties/` | Party-Zusammenstellungen (Platzhalter fuer Multi-Charakter) |
| Preset | `modules/presets/` | Session-Konfiguration (verbindet alle Module) |
| Lore | `data/lore/{system_id}/` | Hintergrunddaten (Monster, Items, Encounters, Loot) |

---

## 2. Verzeichnisstruktur

```
ARS/
├── modules/
│   ├── rulesets/
│   │   ├── cthulhu_7e.json          # Call of Cthulhu 7th Edition
│   │   ├── add_2e.json              # AD&D 2nd Edition
│   │   └── {system_id}.json         # Weiteres Ruleset
│   ├── adventures/
│   │   ├── template.json            # Referenz-Template (NICHT loeschen)
│   │   ├── spukhaus.json            # CoC: The Haunting
│   │   ├── goblin_cave.json         # AD&D: Goblin Cave
│   │   └── {adventure_id}.json      # Weiteres Abenteuer
│   ├── settings/
│   │   ├── cthulhu_1920.json        # Neuengland 1920er
│   │   ├── forgotten_realms.json    # Vergessene Reiche
│   │   └── {setting_id}.json        # Weiteres Setting
│   ├── keepers/
│   │   ├── arkane_archivar.json     # Horror-Keeper
│   │   ├── epischer_barde.json      # Fantasy-Keeper
│   │   └── {keeper_id}.json         # Weitere Persoenlichkeit
│   ├── extras/
│   │   ├── noir_atmosphere.json     # Film Noir Atmosphaere
│   │   ├── survival_mode.json       # Survival-Spielmodus
│   │   └── {extra_id}.json          # Weiteres Extra
│   ├── characters/
│   │   ├── _template.json           # Schema-Referenz
│   │   ├── coc_investigator.json    # CoC Investigator
│   │   ├── add_fighter.json         # AD&D Fighter
│   │   ├── add_mage.json            # AD&D Mage
│   │   └── {character_id}.json      # Weiterer Charakter
│   ├── parties/
│   │   ├── _template.json           # Schema-Referenz (Platzhalter)
│   │   └── {party_id}.json          # Weitere Party
│   └── presets/
│       ├── coc_classic.json         # Session-Preset fuer CoC
│       ├── add_demo.json            # Session-Preset fuer AD&D Demo
│       └── {preset_name}.json       # Weiteres Preset
├── data/
│   └── lore/
│       ├── index.json               # Zentraler Lore-Index (optional)
│       ├── {system_id}/             # Lore pro Regelsystem
│       │   ├── monsters/            # Monster/Kreaturen
│       │   ├── items/               # Gegenstaende/Waffen
│       │   ├── loot/                # Schaetze/Beute
│       │   ├── encounters/          # Zufallsbegegnungen
│       │   └── index.json           # Sub-Index (optional)
│       └── (allgemeine Lore-Ordner) # Systemuebergreifende Lore
```

### Namenskonventionen

| Element | Format | Beispiele |
|---------|--------|-----------|
| system_id | `snake_case` | `cthulhu_7e`, `add_2e`, `dnd_5e` |
| adventure_id | `snake_case` | `goblin_cave`, `spukhaus`, `lost_mine` |
| Dateinamen | `snake_case.json` | `bugbear.json`, `healing_potion.json` |
| Preset-Name | `snake_case` | `coc_classic`, `add_fantasy` |
| Verzeichnisnamen | `snake_case` | `monsters`, `items`, `encounters` |

**Zuordnung Adventure → Ruleset:** Adventures sind NICHT per Verzeichnis einem Ruleset zugeordnet, sondern per **Preset**. Ein Preset verbindet `ruleset` + `adventure`. Das gleiche Adventure kann theoretisch mit verschiedenen Rulesets gespielt werden, aber in der Praxis passen Adventures zu einem bestimmten Regelsystem (z.B. `goblin_cave` → `add_2e`).

---

## 3. Ruleset-Module — Universelles RPG-Regelgeruest

**Pfad:** `modules/rulesets/{system_id}.json`

Ein Ruleset beschreibt die **komplette Spielmechanik** eines Pen-&-Paper-Systems. Das Schema ist als universelles Geruest ("Skeleton") konzipiert, das **jedes denkbare RPG-System** abbilden kann.

**Prinzip:**
- **4 Pflichtfelder** werden von der Engine validiert — fehlt eines, wird das Ruleset abgelehnt
- **Alle anderen Sektionen sind optional** — sie werden vom KI-Backend im System-Prompt verwendet
- System-spezifische Besonderheiten gehoeren in `extensions`
- Wenn ein Konzept in 3+ Systemen vorkommt → eigenes Skeleton-Feld. Wenn nur 1-2 → `extensions`

### 3.1 Skeleton-Baum (Uebersicht)

```
ruleset.json
├── metadata            ← PFLICHT
├── dice_system         ← PFLICHT
├── characteristics     ← PFLICHT
├── skills              ← PFLICHT
├── derived_stats       ← optional (CoC: HP/MP/SAN, AD&D: -)
├── attribute_bonuses   ← optional (AD&D: STR 18/xx Tabellen)
├── races               ← optional (Spielbare Voelker)
├── classes             ← optional (Klassen mit Progression)
├── combat              ← optional (Initiative, AC, Angriff)
├── saving_throws       ← optional (Kategorien + Tabellen)
├── magic               ← optional (Magie-System)
├── alignment           ← optional (Gesinnungs-System)
├── movement            ← optional (Bewegung, Distanzen)
├── encumbrance         ← optional (Traglast)
├── economy             ← optional (Waehrung, Startgold)
├── conditions          ← optional (Zustaende: Gift, Laehmung, ...)
├── healing             ← optional (Heilung, Tod)
├── experience          ← optional (XP-Quellen, Stufenaufstieg)
├── time                ← optional (Runden, Zuege, Rasten)
├── senses              ← optional (Sicht, Licht, Wahrnehmung)
├── travel              ← optional (Reisen, Zufallsbegegnungen)
├── henchmen_hirelings  ← optional (Gefolge, Soeldner)
├── downtime            ← optional (Training, Handwerk)
├── sanity              ← optional (Horror-Mechanik, CoC)
├── extensions          ← optional (System-Sondermechaniken)
└── advancement         ← optional (Kurzform, siehe experience)
```

### 3.2 Pflichtfelder (Engine-Validierung)

Die Engine prueft beim Laden exakt diese 4 Top-Level-Keys. Fehlt einer, wird das Ruleset **abgelehnt**.

```json
{
  "metadata": {
    "name": "PFLICHT — Name des Systems",
    "version": "PFLICHT — Edition/Version",
    "system": "PFLICHT — system_id (muss dem Dateinamen entsprechen)",
    "schema_version": "PFLICHT — Semver (z.B. '1.0.0')",
    "publisher": "optional",
    "language": "optional (z.B. 'de')",
    "game_master_title": "optional (Default: 'Spielleiter')",
    "player_character_title": "optional (Default: 'Investigator')"
  },
  "dice_system": {
    "default_die": "PFLICHT — Notation: 'd20', 'd100', '2d6'",
    "bonus_penalty_die": "optional",
    "notes": "optional",
    "check_mode": "optional ('roll_under' oder 'roll_over')",
    "success_levels": {
      "critical": "PFLICHT — Absolutwert (z.B. 1)",
      "extreme": "PFLICHT — Multiplikator oder Absolutwert (z.B. 0.25)",
      "hard": "PFLICHT — Multiplikator oder Absolutwert (z.B. 0.5)",
      "fumble": "PFLICHT — Absolutwert (z.B. 20 bei d20, 96 bei d100)"
    }
  },
  "characteristics": {
    "ATTR_CODE": {
      "label": "PFLICHT — Anzeigename",
      "roll": "PFLICHT — Wuerfelmechanik (z.B. '3d6', '2d6+6')",
      "multiplier": "PFLICHT — Multiplikator fuer Proben (1 bei d20, 5 bei d100)"
    }
  },
  "skills": {
    "Fertigkeitsname": {
      "base": "PFLICHT — Basiswert (Zahl)",
      "base_formula": "alternativ zu base — Formel (z.B. 'DEX / 2')",
      "class": "optional — Klassen-Bindung (z.B. 'Rogue')",
      "category": "optional — Kategorie (z.B. 'Wissen', 'Kampf', 'Sozial')",
      "group": "optional — Fertigkeitsgruppe (z.B. 'Schusswaffen')"
    }
  }
}
```

### 3.3 Optionale Sektionen — Detaillierte Schemas

#### derived_stats — Abgeleitete Werte

```json
{
  "derived_stats": {
    "HP": {
      "label": "Trefferpunkte",
      "formula": "(CON + SIZ) / 10",
      "round": "floor"
    },
    "SAN": {
      "label": "Geistesgesundheit",
      "formula": "POW * 5",
      "max_formula": "99 - Cthulhu Mythos"
    },
    "MOV": {
      "label": "Bewegung",
      "value": 8,
      "notes": "Reduziert um 1 fuer jedes Jahrzehnt ab 40"
    },
    "Build": {
      "label": "Statur",
      "table": [
        { "condition": "STR+SIZ <= 64", "value": -2 }
      ]
    }
  }
}
```

#### attribute_bonuses — Attribut-Bonus-Tabellen

Fuer Systeme in denen Attributwerte mechanische Boni geben (z.B. AD&D STR-Tabelle, WIS Spell-Bonus).

```json
{
  "attribute_bonuses": {
    "STR": {
      "thresholds": [
        { "min": 3, "max": 5, "bonuses": { "hit": -2, "damage": -1, "weight_allow": 10 } },
        { "min": 16, "max": 16, "bonuses": { "hit": 0, "damage": 1, "weight_allow": 70 } },
        { "min": 18, "max": 18, "bonuses": { "hit": 1, "damage": 2, "weight_allow": 110 } }
      ]
    },
    "DEX": {
      "thresholds": [
        { "min": 3, "max": 3, "bonuses": { "reaction_adj": -3, "missile_adj": -3, "ac_adj": 4 } },
        { "min": 16, "max": 16, "bonuses": { "reaction_adj": 1, "missile_adj": 1, "ac_adj": -2 } }
      ]
    },
    "WIS": {
      "thresholds": [
        { "min": 13, "max": 13, "bonuses": { "bonus_spells": "1st", "spell_failure": 0 } }
      ]
    }
  }
}
```

#### races — Spielbare Voelker/Spezies

```json
{
  "races": {
    "elf": {
      "name": "Elf",
      "description": "Schlanke, langlebige Wesen mit natuerlicher Affinitaet zur Magie.",
      "ability_modifiers": { "DEX": 1, "CON": -1 },
      "size": "M",
      "base_movement": 12,
      "special_abilities": ["90% Widerstand gegen Schlaf/Bezauberung", "Infravision 60ft"],
      "class_restrictions": ["Fighter", "Mage", "Thief", "Fighter/Mage", "Fighter/Thief", "Mage/Thief"],
      "level_limits": { "Fighter": 7, "Mage": 11, "Thief": null },
      "thief_skill_modifiers": { "Pick Pockets": 5, "Hide in Shadows": 10 },
      "infravision": 60,
      "saving_throw_bonuses": {},
      "languages": ["Elfisch", "Gemeinsprache", "Gnomisch"]
    }
  }
}
```

Felder: `name` (PFLICHT), `ability_modifiers`, `size` (S/M/L), `base_movement`, `special_abilities`, `class_restrictions`, `level_limits`, `thief_skill_modifiers`, `infravision` (Reichweite oder null), `saving_throw_bonuses`, `languages`.

#### classes — Klassen/Berufe (erweitert)

Bestehende Felder (`base_weapon_proficiencies`, `thief_skills`) bleiben. Neue Felder:

```json
{
  "classes": {
    "Fighter": {
      "hit_die": "d10",
      "prime_requisite": ["STR"],
      "allowed_alignments": ["LG","NG","CG","LN","N","CN","LE","NE","CE"],
      "armor_allowed": ["all"],
      "weapons_allowed": ["all"],
      "base_weapon_proficiencies": ["Longsword", "Battle Axe", "Spear", "Bow"],
      "thief_skills": {},
      "special_abilities": ["Multiple Attacks at higher levels"],
      "spellcasting": null,
      "progression": [
        { "level": 1, "xp_required": 0, "thac0": 20, "saves": { "paralyzation": 14, "petrification": 15, "rod": 16, "breath": 17, "spell": 17 }, "title": "Veteran" },
        { "level": 2, "xp_required": 2000, "thac0": 19, "saves": { "paralyzation": 14, "petrification": 15, "rod": 16, "breath": 17, "spell": 17 }, "title": "Warrior" },
        { "level": 9, "xp_required": 250000, "thac0": 12, "saves": { "paralyzation": 8, "petrification": 9, "rod": 10, "breath": 10, "spell": 11 }, "title": "Lord" }
      ]
    },
    "Mage": {
      "hit_die": "d4",
      "prime_requisite": ["INT"],
      "armor_allowed": ["none"],
      "weapons_allowed": ["Dagger", "Staff", "Dart"],
      "spellcasting": {
        "type": "arcane",
        "spell_list_ref": "data/lore/{system_id}/spells/",
        "learning": "Spellbook — muss Zauber finden und ins Zauberbuch kopieren",
        "preparation": "Taegliches Memorieren aus Zauberbuch"
      },
      "progression": [
        { "level": 1, "xp_required": 0, "thac0": 20, "spells_per_day": { "1": 1 }, "title": "Prestidigitator" }
      ]
    }
  }
}
```

Neue Felder: `hit_die`, `prime_requisite`, `allowed_alignments`, `armor_allowed`, `weapons_allowed`, `special_abilities`, `spellcasting` (type, spell_list_ref, learning, preparation), `progression` (Array mit level, xp_required, thac0, saves, title, spells_per_day).

#### combat — Kampfsystem (erweitert)

Bestehende Felder (`hit_points`, `armor_class`, `attack_metric`, `attack_rule`) bleiben. Neue Felder:

```json
{
  "combat": {
    "hit_points": "HP",
    "armor_class": { "label": "AC", "direction": "descending" },
    "attack_metric": "THAC0",
    "attack_rule": "Wurf >= THAC0 - Ziel-AC",
    "initiative": {
      "method": "individual",
      "die": "d10",
      "modifiers": "DEX reaction adjustment + weapon speed factor"
    },
    "surprise": {
      "base_chance": "2 in 6",
      "modifier_source": "Rasse, Situation"
    },
    "actions_per_round": {
      "default": 1,
      "fighter_extra_attacks": "1 extra at level 7, 2 extra at level 13"
    },
    "morale": {
      "die": "2d6",
      "base": 7,
      "modifiers": "Situation, Fuehrung, Verluste"
    },
    "two_weapon_fighting": "Haupthand normal, Nebenhand -4 (anpassbar durch DEX)",
    "charging": "+2 Angriff, kein DEX-Bonus zur AC",
    "retreating": "Feind erhaelt freien Angriff bei Flucht",
    "critical_hits": "Nat 20 = automatischer Treffer (kein doppelter Schaden in AD&D 2e)",
    "fumbles": "Nat 1 = automatischer Fehlschlag"
  }
}
```

Neue Felder: `initiative`, `surprise`, `actions_per_round`, `morale`, `two_weapon_fighting`, `charging`, `retreating`, `critical_hits`, `fumbles`.

#### saving_throws — Rettungswuerfe (erweitert)

Bestehende Kurzform (Array von Namen) bleibt kompatibel. Neu: `tables` mit Klassen-Tabellen.

```json
{
  "saving_throws": {
    "categories": ["Paralyzation/Poison", "Petrification/Polymorph", "Rod/Staff/Wand", "Breath Weapon", "Spell"],
    "tables": {
      "Fighter": [
        { "level_range": "1-2", "saves": { "paralyzation": 14, "petrification": 15, "rod": 16, "breath": 17, "spell": 17 } },
        { "level_range": "3-4", "saves": { "paralyzation": 13, "petrification": 14, "rod": 15, "breath": 16, "spell": 16 } }
      ],
      "Mage": [
        { "level_range": "1-5", "saves": { "paralyzation": 14, "petrification": 13, "rod": 11, "breath": 15, "spell": 12 } }
      ]
    }
  }
}
```

**Hinweis:** Wenn `saving_throws` als einfaches Array angegeben wird (alter Stil), interpretiert die Engine nur die Kategorienamen. Die `tables`-Form ist die vollstaendige Variante.

#### magic — Magie-System

```json
{
  "magic": {
    "system_type": "vancian",
    "schools": ["Abjuration", "Alteration", "Conjuration", "Divination", "Enchantment", "Evocation", "Illusion", "Necromancy"],
    "spell_slots": {
      "Mage": {
        "1": { "1": 1 },
        "2": { "1": 2 },
        "3": { "1": 2, "2": 1 },
        "5": { "1": 4, "2": 2, "3": 1 }
      },
      "Cleric": {
        "1": { "1": 1 },
        "2": { "1": 2 },
        "3": { "1": 2, "2": 1 }
      }
    },
    "learning": "Zauberbuch-basiert. Chance zum Lernen: INT-abhaengig. Max Zauber pro Stufe: INT-abhaengig.",
    "components": {
      "V": "Verbal — Sprechen noetig",
      "S": "Somatic — Gesten noetig",
      "M": "Material — Materialkomponente noetig (verbraucht sich)"
    },
    "concentration": "Unterbrochen durch Schaden oder Bewegung",
    "spell_failure": "Arkane Zauber versagen in Ruestung",
    "spells_ref": "data/lore/{system_id}/spells/"
  }
}
```

Gueltige `system_type`-Werte: `vancian` (Slot-basiert, memorieren), `mana` (Mana-Punkte), `skill_based` (Fertigkeitswurf), `ritual` (Rituale mit Kosten), `none` (keine Magie).

#### alignment — Gesinnungs-System

```json
{
  "alignment": {
    "type": "nine_grid",
    "values": ["LG", "NG", "CG", "LN", "N", "CN", "LE", "NE", "CE"],
    "effects": "Bestimmt erlaubte Klassen, Interaktion mit magischen Gegenstaenden, NPC-Reaktionen"
  }
}
```

Gueltige `type`-Werte: `nine_grid` (D&D 3x3), `dual_axis` (Ordnung/Chaos + Gut/Boese), `single_axis` (nur Gut/Neutral/Boese), `none`.

#### movement — Bewegung & Distanzen

```json
{
  "movement": {
    "base_rates": {
      "walking": "12 (120ft/Runde, 120yd/Zug)",
      "running": "x2 Basis, kein Mapping",
      "swimming": "1/2 Basis",
      "climbing": "1/4 Basis"
    },
    "encumbrance_effect": "Schwere Last reduziert Bewegung stufenweise",
    "terrain_modifiers": {
      "road": 1.0,
      "clear": 1.0,
      "forest": 0.5,
      "swamp": 0.33,
      "mountain": 0.33,
      "desert": 0.66
    },
    "tactical_scale": "1 Feld = 10 Fuss",
    "overland_scale": "24 Meilen/Tag bei Basis 12, Gelaeende-Faktor anwenden"
  }
}
```

#### encumbrance — Traglast

```json
{
  "encumbrance": {
    "method": "weight",
    "thresholds": [
      { "max_weight": 35, "movement": 12, "combat_penalty": 0 },
      { "max_weight": 70, "movement": 9, "combat_penalty": 0 },
      { "max_weight": 105, "movement": 6, "combat_penalty": -1 },
      { "max_weight": 150, "movement": 3, "combat_penalty": -2 }
    ],
    "coin_weight": "10 Muenzen = 1 Pfund"
  }
}
```

Gueltige `method`-Werte: `weight` (Gewicht in Pfund), `slots` (Slot-basiert), `abstract` (leicht/mittel/schwer), `none`.

#### economy — Wirtschaft

```json
{
  "economy": {
    "currencies": [
      { "name": "Platinmuenze", "abbreviation": "PP", "value_in_base": 5 },
      { "name": "Goldmuenze", "abbreviation": "GP", "value_in_base": 1 },
      { "name": "Silbermuenze", "abbreviation": "SP", "value_in_base": 0.1 },
      { "name": "Kupfermuenze", "abbreviation": "CP", "value_in_base": 0.01 }
    ],
    "base_currency": "GP",
    "price_lists_ref": "data/lore/{system_id}/items/",
    "starting_gold": {
      "method": "roll",
      "by_class": {
        "Fighter": "5d4 * 10",
        "Mage": "1d4+1 * 10",
        "Rogue": "2d6 * 10",
        "Cleric": "3d6 * 10"
      }
    }
  }
}
```

#### conditions — Zustaende & Status-Effekte

```json
{
  "conditions": {
    "poisoned": {
      "name": "Vergiftet",
      "description": "Gift wirkt im Koerper",
      "mechanical_effect": "Rettungswurf gegen Gift oder Schaden/Tod",
      "cure": "Neutralize Poison, Slow Poison"
    },
    "paralyzed": {
      "name": "Gelaehmt",
      "description": "Kann sich nicht bewegen oder handeln",
      "mechanical_effect": "AC verschlechtert sich, keine Aktionen",
      "cure": "Zeitablauf, Remove Paralysis"
    },
    "petrified": {
      "name": "Versteinert",
      "description": "In Stein verwandelt",
      "mechanical_effect": "Effektiv tot bis geheilt",
      "cure": "Stone to Flesh"
    }
  }
}
```

#### healing — Heilung & Erholung

```json
{
  "healing": {
    "natural_healing": "1 HP pro Tag vollstaendiger Rast",
    "magical_healing": "Cure Light Wounds (1d8), Heiltraenke, Tempel (gegen Spende)",
    "death_and_dying": "Bei 0 HP: Tod. Optional: -1 bis -10 HP = bewusstlos, unter -10 = tot"
  }
}
```

#### experience — Erfahrung & Stufenaufstieg

Erweitert das bestehende `advancement`-Feld mit mehr Detail:

```json
{
  "experience": {
    "method": "experience_points",
    "sources": {
      "combat": "XP pro Monster gemaess Monster-XP-Tabelle",
      "treasure": "1 GP gefundener Schatz = 1 XP (optional)",
      "quest": "DM vergibt Quest-XP pauschal",
      "roleplaying": "Bonus-XP fuer gutes Rollenspiel (DM-Ermessen)",
      "individual_class": "Thief: Goldwert gestohlener Beute als XP"
    },
    "level_up_rules": "XP erreicht → Training noetig → Stufenaufstieg. HP-Wuerfel werfen, neue Faehigkeiten.",
    "training": {
      "required": true,
      "cost": "1500 GP pro Stufe (variabel)",
      "duration": "1-4 Wochen"
    }
  }
}
```

Gueltige `method`-Werte: `experience_points` (klassenbasierte XP-Tabelle), `experience_check` (Fertigkeitswurf nach Einsatz, CoC), `milestone` (DM-Entscheidung).

#### time — Zeit-System

```json
{
  "time": {
    "round_duration": "1 Minute",
    "turn_duration": "10 Minuten",
    "exploration_turn": "10 Minuten — Suchen, Fallen pruefen, langsam erkunden",
    "rest": {
      "short_rest": "1 Zug (10 Min) — Verschnaufen, keine Heilung",
      "long_rest": "8 Stunden — Natuerliche Heilung moeglich"
    }
  }
}
```

#### senses — Wahrnehmung & Sicht

```json
{
  "senses": {
    "vision_types": {
      "normal": "Benoetigt Lichtquelle in Dungeons",
      "infravision": "Waermebasiertes Sehen, 60ft Standard (Elfen, Zwerge)",
      "ultravision": "Sehen bei minimalstem Licht (selten)"
    },
    "light_sources": [
      { "name": "Fackel", "radius": "40ft", "duration": "6 Zuege (1h)" },
      { "name": "Laterne", "radius": "30ft", "duration": "24 Zuege (4h) pro Oelfuellung" },
      { "name": "Continual Light (Zauber)", "radius": "60ft", "duration": "permanent" }
    ],
    "detection": {
      "listen_chance": "1 in 6 (Menschen), 2 in 6 (Elfen)",
      "detect_secret_doors": "1 in 6 (Menschen), 2 in 6 (Elfen, aktiv), 1 in 6 (Elfen, passiv)",
      "detect_traps": "1 in 6 (Nicht-Dieb), Thief-Skill fuer Diebe"
    }
  }
}
```

#### travel — Reisen & Erkundung

```json
{
  "travel": {
    "overland": {
      "daily_distance": "24 Meilen/Tag (Basis-Movement 12)",
      "forced_march": "+50% Distanz, CON-Check oder Erschoepfung",
      "navigation": "Orientierung-Probe oder Verirrung"
    },
    "maritime": {
      "ship_types_ref": "data/lore/{system_id}/items/ (Schiffe)",
      "speed": "Abhaengig von Schiffstyp und Wind"
    },
    "aerial": {
      "flying_mounts": "Greif, Pegasus, Drache — abhaengig von Setting",
      "speed": "Doppelte Bodengeschwindigkeit"
    },
    "random_encounters": {
      "frequency": "1 in 6 pro Zug (Dungeon), 1 in 20 pro Tag (Wildnis)",
      "tables_ref": "data/lore/{system_id}/tables/"
    },
    "weather_effects": {
      "types": ["Regen", "Sturm", "Schnee", "Nebel", "Hitze"],
      "mechanical_impact": "Sichtweite, Bewegung, Fernkampf-Mali"
    }
  }
}
```

#### henchmen_hirelings — Gefolge & Soeldner

```json
{
  "henchmen_hirelings": {
    "max_henchmen": "CHA-abhaengig (z.B. CHA 15 = 7 Gefolgsleute)",
    "loyalty": {
      "base": "CHA-Modifikator",
      "modifiers": "Bezahlung, Behandlung, Gefahr"
    },
    "morale": {
      "die": "2d6",
      "base": 7
    },
    "costs": "Abhaengig von Typ und Stufe — Kaempfer teurer als Traeger"
  }
}
```

#### downtime — Zwischen-Abenteuer-Aktivitaeten

```json
{
  "downtime": {
    "training": "Stufenaufstieg, neue Fertigkeiten, Waffen-Uebung",
    "crafting": "Magische Gegenstaende (Mage), Traenke (Alchemie), Waffen (Schmied)",
    "research": "Zauber-Forschung, Bibliotheksnutzung, Informanten",
    "building": "Festungen ab Stufe 9 (Fighter), Magiertuerme (Mage), Tempel (Cleric)",
    "costs_and_time": "Abhaengig von Aktivitaet — siehe Klassentabellen"
  }
}
```

#### sanity — Horror-Mechanik (system-spezifisch)

```json
{
  "sanity": {
    "starting_san": "POW * 5",
    "max_san": 99,
    "indefinite_insanity_threshold": 5,
    "temporary_insanity_threshold": 0.2,
    "notes": "Verlust von >=1/5 der aktuellen SAN in einer Runde = temporaerer Wahnsinn"
  }
}
```

#### extensions — System-spezifische Sondermechaniken

Fuer Mechaniken die einzigartig fuer ein bestimmtes System sind und in kein anderes Skeleton-Feld passen:

```json
{
  "extensions": {
    "exceptional_strength": {
      "description": "STR 18 hat Sub-Werte (18/01 bis 18/00) nur fuer Fighter",
      "applies_to": ["Fighter", "Paladin", "Ranger"],
      "table": [
        { "range": "18/01-50", "hit": "+1", "damage": "+3", "weight_allow": 135 },
        { "range": "18/51-75", "hit": "+2", "damage": "+3", "weight_allow": 160 },
        { "range": "18/76-90", "hit": "+2", "damage": "+4", "weight_allow": 185 },
        { "range": "18/91-99", "hit": "+2", "damage": "+5", "weight_allow": 235 },
        { "range": "18/00", "hit": "+3", "damage": "+6", "weight_allow": 335 }
      ]
    },
    "weapon_speed_factor": {
      "description": "Jede Waffe hat einen Speed Factor der die Initiative beeinflusst"
    },
    "psionics": {
      "description": "Mentale Kraefte ausserhalb des Magie-Systems"
    }
  }
}
```

**Beispiele fuer Extensions nach System:**
- **AD&D 2e:** `exceptional_strength`, `weapon_speed_factor`, `weapon_vs_armor`, `psionics`
- **CoC 7e:** `luck_spending`, `credit_rating_system`, `bouts_of_madness`, `chase_rules`
- **D&D 5e:** `inspiration`, `proficiency_bonus`, `cantrips_at_will`

#### advancement — Kurzform (Legacy)

Bleibt fuer Rueckwaerts-Kompatibilitaet. Fuer neue Rulesets `experience` bevorzugen.

```json
{
  "advancement": {
    "method": "experience_points | experience_check | milestone",
    "notes": "Beschreibung der Steigerungsmechanik"
  }
}
```

### 3.4 System-Prompt-Generierung

Die `metadata.system`-ID bestimmt, welcher Prompt-Zweig aktiv wird:

| system_id startet mit | Prompt-Modus | Besonderheiten |
|------------------------|--------------|----------------|
| `cthulhu` | Horror/Keeper | SAN-Tracking, Stabilitaetsverlust-Protokoll, Keeper-Persona |
| alles andere | Fantasy/GM | THAC0/AC-Kampf, XP-Vergabe, HP-Heilung, Initiative |

Das `game_master_title` und `player_character_title` aus metadata werden direkt im Prompt eingesetzt (z.B. "Du bist der **Dungeon Master**" statt "Du bist der **Keeper**").

Das gesamte Ruleset-JSON wird dem System-Prompt injiziert — alle hier definierten optionalen Sektionen fliessen automatisch in die KI-Anweisungen ein.

### 3.5 Referenz

Bestehende Rulesets: `modules/rulesets/add_2e.json`, `modules/rulesets/cthulhu_7e.json`

---

## 4. Adventure-Module

**Pfad:** `modules/adventures/{adventure_id}.json`

### Schema

```json
{
  "title": "PFLICHT — Anzeigename des Abenteuers",
  "setting": "PFLICHT — Ort und Zeit (z.B. 'Boston, 1920')",
  "difficulty": "PFLICHT — Schwierigkeitsgrad als Freitext (z.B. 'Einsteiger', 'Fortgeschritten')",
  "intro": "PFLICHT — Einstiegstext fuer die Spieler",
  "hook": "PFLICHT — Kurzbeschreibung des Plot-Hooks",
  "keeper_lore": "PFLICHT — Hintergrundwissen nur fuer den Spielleiter",
  "start_location": "PFLICHT — id der Start-Location",

  "flags": {
    "flag_name": false
  },

  "locations": [],
  "npcs": [],
  "clues": [],
  "handouts": [],
  "resolution": {}
}
```

### KRITISCH: locations und npcs sind Arrays

**`locations` und `npcs` MUESSEN Arrays sein** (`[{...}, {...}]`), **NICHT Dicts/Maps** (`{"key": {...}}`).
Die Engine iteriert ueber diese Arrays und liest das `id`-Feld jedes Objekts.

Falsch:
```json
"locations": {
  "cave_entrance": { "name": "Eingang" }
}
```

Richtig:
```json
"locations": [
  { "id": "cave_entrance", "name": "Eingang", ... }
]
```

### Location-Objekt

```json
{
  "id": "PFLICHT — eindeutige ID (snake_case)",
  "name": "PFLICHT — Anzeigename",
  "description": "PFLICHT — Beschreibung fuer die Spieler",
  "atmosphere": "Empfohlen — Sinneseindruecke, Stimmung",
  "npcs_present": ["npc_id_1", "npc_id_2"],
  "clues_available": ["clue_id_1"],
  "exits": {
    "other_location_id": "Beschreibung des Ausgangs"
  },
  "keeper_notes": "Nur fuer den SL sichtbar — taktische Hinweise",
  "sub_locations": [
    {
      "id": "sub_id",
      "name": "Unterbereich",
      "description": "...",
      "clues": ["clue_id"],
      "events": [
        {
          "trigger": "Freitext-Ausloeser",
          "effect": "Was passiert",
          "sets_flag": "flag_name"
        }
      ]
    }
  ],
  "events": [
    {
      "trigger": "Freitext-Ausloeser",
      "effect": "Was passiert",
      "sets_flag": "flag_name"
    }
  ]
}
```

### NPC-Objekt

```json
{
  "id": "PFLICHT — eindeutige ID (snake_case)",
  "name": "PFLICHT — Anzeigename",
  "role": "Empfohlen — Rolle im Abenteuer (z.B. 'Auftraggeber', 'Antagonist')",
  "description": "PFLICHT — Kurzbeschreibung",
  "appearance": "Empfohlen — Aeusseres Erscheinungsbild",
  "personality": "Empfohlen — Persoenlichkeit",
  "knowledge": ["Was der NPC weiss"],
  "secrets": ["Was der NPC verbirgt"],
  "dialogue_hints": ["Typische Redewendungen oder Sprechmuster"],
  "stats": {
    "ac": 6,
    "hp": 8,
    "thac0": 19
  },
  "behavior": "Kampfverhalten oder Reaktionsmuster"
}
```

**Hinweis:** NPCs koennen narrativ ODER mechanisch sein:
- **Narrative NPCs** (Auftraggeber, Informanten): `knowledge`, `secrets`, `dialogue_hints` statt `stats`
- **Kampf-NPCs** (Monster, Gegner): `stats`, `behavior` statt `dialogue_hints`
- Beides kombinieren ist moeglich

### Clue-Objekt

```json
{
  "id": "PFLICHT — eindeutige ID",
  "location": "PFLICHT — Location-ID wo der Hinweis gefunden wird",
  "sub_location": "Optional — Sub-Location-ID",
  "name": "PFLICHT — Anzeigename",
  "description": "PFLICHT — Was der Spieler sieht/findet",
  "probe_required": "Fertigkeitsname oder null (frei zugaenglich)",
  "information": "PFLICHT — Was der Hinweis verraet",
  "sanity_loss": "Optional — Format: 'min/max' z.B. '0/1d3'",
  "mythos_gain": 0,
  "leads_to": ["andere_clue_ids"],
  "sets_flag": "flag_name oder null"
}
```

### Handout-Objekt

```json
{
  "id": "PFLICHT",
  "type": "text",
  "title": "PFLICHT — Anzeigename",
  "content": "PFLICHT — Inhalt des Handouts",
  "requires_flag": "Optional — Flag das gesetzt sein muss"
}
```

### Resolution-Objekt

```json
{
  "good_ending": "Beschreibung des guten Endes",
  "bad_ending": "Beschreibung des schlechten Endes",
  "conditions": {
    "good_requires": ["flag_1", "flag_2"],
    "bad_triggers": ["flag_3"]
  }
}
```

Alternativ (einfache Form):
```json
{
  "success": "Beschreibung",
  "condition": "flag_name == true"
}
```

### Flag-System

Flags sind boolsche Zustandsvariablen, die den Story-Fortschritt tracken.

**Konventionen:**
- Alle Flags in `flags` initial auf `false`
- Events setzen Flags via `sets_flag`
- Clues koennen Flags setzen via `sets_flag`
- Resolution prueft Flags via `conditions`
- Flag-Namen: `snake_case` (z.B. `boss_dead`, `trap_triggered`, `auftrag_angenommen`)

---

## 5. Preset-Dateien

**Pfad:** `modules/presets/{preset_name}.json`

Presets konfigurieren die Session und verbinden Ruleset mit Adventure.

### Schema

```json
{
  "ruleset": "PFLICHT — system_id (z.B. 'add_2e', 'cthulhu_7e')",
  "adventure": "adventure_id oder null (Free Roam)",
  "setting": "setting_id oder null (z.B. 'cthulhu_1920', 'forgotten_realms')",
  "keeper": "keeper_id oder null (z.B. 'arkane_archivar', 'epischer_barde')",
  "extras": ["extra_id", "..."],
  "character": "character_id oder null (z.B. 'coc_investigator', 'add_fighter')",
  "party": "party_id oder null (Platzhalter fuer Multi-Charakter)",
  "difficulty": "easy | normal | heroic | hardcore",
  "atmosphere": "Freitext-Fallback — nur wenn kein Setting-Modul gesetzt",
  "keeper_persona": "Freitext-Fallback — nur wenn kein Keeper-Modul gesetzt",
  "language": "de-DE | en-US | ...",
  "temperature": 0.92
}
```

### Gueltige difficulty-Werte

| Wert | Bedeutung |
|------|-----------|
| `easy` | Gnaedig, Hinweise, reduzierte Verluste |
| `normal` | Faire Balance, Konsequenzen aber Raum zum Atmen |
| `heroic` | Faire Kaempfe, clevere Taktik belohnt, klassische Fantasy |
| `hardcore` | Kein Erbarmen, Patzer verheerend, Hinweise rar |

### Felder

Alle Felder sind optional ausser `ruleset`. Nicht gesetzte Felder verwenden Defaults:

| Feld | Default |
|------|---------|
| adventure | `null` (kein Adventure, Free Roam) |
| setting | `null` (kein Setting-Modul, Fallback auf `atmosphere`) |
| keeper | `null` (kein Keeper-Modul, Fallback auf `keeper_persona`) |
| extras | `[]` (keine Extras) |
| character | `null` (kein Character-Template, Ruleset-Defaults) |
| party | `null` (kein Party-Modul) |
| difficulty | `"normal"` |
| atmosphere | `"1920s Cosmic Horror"` (Fallback) |
| keeper_persona | `"Mysterioes, detailverliebt, zynisch"` (Fallback) |
| language | `"de-DE"` |
| temperature | `0.92` |

**Prioritaet:** Wenn `setting` gesetzt → ueberschreibt `atmosphere`. Wenn `keeper` gesetzt → ueberschreibt `keeper_persona`.

---

## 6. Setting-Module

**Pfad:** `modules/settings/{setting_id}.json`

Settings beschreiben die Spielwelt: Geographie, Kultur, Technologie, Voelker, Waehrung.

### Schema

```json
{
  "id": "PFLICHT — snake_case Bezeichner",
  "name": "Lesbarer Name der Welt/Epoche",
  "compatible_rulesets": ["Liste kompatibler Ruleset-IDs"],
  "epoch": "Zeitepoche (z.B. '1920er Jahre', 'Zeitalter der Umwaelzungen')",
  "geography": "Geographische Beschreibung — Orte, Landschaften, Klima",
  "culture": "Gesellschaft, Normen, Religion, Recht",
  "technology": "Technologiestufe, verfuegbare Werkzeuge",
  "races_species": "Spielbare Voelker/Spezies",
  "atmosphere": "Grundstimmung der Welt",
  "currency": "Waehrungssystem mit Beispielpreisen",
  "language_style": "Sprachstil fuer Dialoge und Beschreibungen",
  "special_rules": "Weltspezifische Sonderregeln",
  "time": {
    "calendar": "Kalendersystem",
    "default_start": "HH:MM — Standard-Startzeit",
    "day_phases": ["Tagesphasen-Array"]
  }
}
```

### Pflichtfelder

`id`, `name`, `compatible_rulesets`, `epoch`, `geography`, `atmosphere`

### Vorhandene Settings

| ID | Welt | Kompatibel |
|----|------|------------|
| `cthulhu_1920` | Neuengland der 1920er | cthulhu_7e |
| `forgotten_realms` | Vergessene Reiche — Schwertkueste | add_2e |

---

## 7. Keeper-Module

**Pfad:** `modules/keepers/{keeper_id}.json`

Keeper-Module definieren die Persoenlichkeit und den Erzaehlstil des Spielleiters.

### Schema

```json
{
  "id": "PFLICHT — snake_case Bezeichner",
  "name": "Lesbarer Name der Persoenlichkeit",
  "compatible_rulesets": ["Liste kompatibler Ruleset-IDs"],
  "tone": "Grundton (z.B. 'Unheilvoll, leise, klinisch')",
  "philosophy": "Spielleiter-Philosophie",
  "narration_style": "Wie wird erzaehlt — Tempo, Fokus, Mittel",
  "combat_style": "Wie werden Kaempfe beschrieben",
  "npc_voice": "Wie sprechen und verhalten sich NPCs",
  "catch_phrases": ["Typische Wendungen oder Zitate"]
}
```

### Pflichtfelder

`id`, `name`, `tone`

### Vorhandene Keeper

| ID | Name | Ton | Kompatibel |
|----|------|-----|------------|
| `arkane_archivar` | Der Arkane Archivar | Unheilvoll, leise, klinisch | cthulhu_7e |
| `epischer_barde` | Der Epische Barde | Heroisch, farbenfroh, dramatisch | add_2e |

---

## 8. Extras-Module

**Pfad:** `modules/extras/{extra_id}.json`

Extras sind optionale Erweiterungen: Atmosphaere-Pakete, Spielmodus-Modifier, Regel-Erweiterungen. Mehrere koennen gleichzeitig aktiv sein.

### Schema

```json
{
  "id": "PFLICHT — snake_case Bezeichner",
  "name": "Lesbarer Name",
  "type": "atmosphere | game_mode | rule_extension",
  "compatible_rulesets": ["..."] ,
  "description": "Kurzbeschreibung",
  "prompt_injection": "Text der in den System-Prompt injiziert wird",
  "modifiers": {}
}
```

### Pflichtfelder

`id`, `name`, `type`, `prompt_injection`

### type-Werte

| Typ | Bedeutung |
|-----|-----------|
| `atmosphere` | Veraendert Erzaehlstil und Stimmung |
| `game_mode` | Veraendert Spielregeln (z.B. Survival, Hardcore) |
| `rule_extension` | Fuegt optionale Regeln hinzu |

### `compatible_rulesets`

- Array von Ruleset-IDs → nur mit diesen kompatibel
- `null` → universell einsetzbar

### `modifiers`

Optionales Objekt mit numerischen Modifikatoren fuer die Engine:

```json
{
  "healing_factor": 0.5,
  "loot_rarity_shift": 1
}
```

### Vorhandene Extras

| ID | Name | Typ | Kompatibel |
|----|------|-----|------------|
| `noir_atmosphere` | Film Noir | atmosphere | cthulhu_7e |
| `survival_mode` | Survival-Modus | game_mode | universal |

---

## 9. Character-Module

**Pfad:** `modules/characters/{character_id}.json`

Charakter-Templates definieren vorgefertigte Spielercharaktere mit Attributen, Fertigkeiten und Ausruestung. Sie sind an ein Regelsystem gebunden.

### Schema

```json
{
  "id": "PFLICHT — snake_case ID",
  "name": "PFLICHT — Anzeigename",
  "compatible_rulesets": ["PFLICHT — Liste kompatibler Regelsystem-IDs"],
  "archetype": "PFLICHT — Klasse/Beruf (z.B. 'Antiquar', 'Fighter', 'Mage')",
  "level": 1,
  "background": "Hintergrundgeschichte",
  "traits": "Persoenlichkeitsmerkmale",
  "appearance": "Aeussere Erscheinung",
  "characteristics": {
    "STAT_KEY": "Wert (Zahl)"
  },
  "derived_stats": {
    "HP": "Trefferpunkte",
    "SAN": "Stabilitaet (nur CoC)",
    "MP": "Magiepunkte (nur CoC)"
  },
  "skills": {
    "Fertigkeitsname": "Wert (Zahl)"
  },
  "equipment": ["Gegenstand 1", "Gegenstand 2"],
  "notes": "Optionale Anmerkungen"
}
```

### Pflichtfelder

- `id`, `name`, `compatible_rulesets`, `archetype`
- `characteristics` muss die Attribute des Regelsystems verwenden
- `derived_stats` muss mindestens `HP` enthalten

### Charakteristik-Schluessel nach Regelsystem

| Regelsystem | Attribute | Multiplier |
|-------------|-----------|------------|
| `cthulhu_7e` | STR, CON, SIZ, DEX, APP, INT, POW, EDU | x5 (Werte 15-90) |
| `add_2e` | STR, DEX, CON, INT, WIS, CHA | x1 (Werte 3-18) |

### Vorhandene Characters

| character_id | Name | Regelsystem | Klasse |
|-------------|------|-------------|--------|
| `coc_investigator` | Dr. Henry Walters | cthulhu_7e | Antiquar |
| `add_fighter` | Thorgar Eisenfaust | add_2e | Fighter |
| `add_mage` | Elara Sternenschein | add_2e | Mage |

---

## 10. Party-Module (Platzhalter)

**Pfad:** `modules/parties/{party_id}.json`

Party-Module fassen mehrere Charaktere zu einer Gruppe zusammen. Dies ist ein Platzhalter fuer zukuenftige Multi-Charakter-Unterstuetzung.

### Schema

```json
{
  "id": "PFLICHT — snake_case ID",
  "name": "Gruppenname",
  "compatible_rulesets": ["Ruleset-IDs"],
  "members": ["character_id_1", "character_id_2"],
  "formation": "Marschordnung oder taktische Aufstellung",
  "group_funds": "Gemeinsame Kasse",
  "notes": "Gruppennotizen"
}
```

### Pflichtfelder

- `id`, `name`, `members`
- `members` referenziert `character_id`s aus `modules/characters/`

---

## 11. Lore-Daten

**Pfad:** `data/lore/{system_id}/{kategorie}/{datei}.json`

Lore-Daten sind Hintergrundinformationen, die der KI-Spielleiter zur Laufzeit nutzen kann: Monster-Statistiken, Gegenstaende, Zufallsbegegnungen, Schaetze.

### Verzeichnisstruktur pro Regelsystem

```
data/lore/{system_id}/
├── monsters/           # Kreaturen und Gegner
│   ├── goblin.json
│   ├── skeleton.json
│   └── ...
├── items/              # Waffen, Ruestung, Ausruestung
│   ├── longsword.json
│   ├── healing_potion.json
│   └── ...
├── loot/               # Schaetze und Beute-Tabellen
│   ├── dungeon_hoard.json
│   └── ...
├── encounters/         # Zufallsbegegnungen und Events
│   ├── ambush_bandits.json
│   └── ...
├── spells/             # Zauber und magische Faehigkeiten
│   ├── magic_missile.json
│   └── ...
├── tables/             # Zufallstabellen (Wander-Monster, Schatz, Wetter)
│   ├── wandering_monsters_level_1.json
│   └── ...
└── index.json          # Sub-Index (optional aber empfohlen)
```

### Monster-Schema

```json
{
  "id": "PFLICHT — snake_case ID",
  "name": "Empfohlen — Anzeigename (falls abweichend von id)",
  "ac": "PFLICHT — Ruestungsklasse (Zahl)",
  "hit_dice": "PFLICHT — Trefferwuerfel (z.B. '3+1')",
  "hp_avg": "Empfohlen — Durchschnitts-HP",
  "thac0": "PFLICHT (AD&D) — Angriffsbonus",
  "attacks": "PFLICHT — Angriffsformat (z.B. '1 (1d8)')",
  "damage": "Empfohlen — Schadensformat (z.B. '2d4 or by weapon +1')",
  "morale": "Empfohlen — Moralwert",
  "xp_value": "Empfohlen — Erfahrungspunkte",
  "movement": "Optional — { base: 9, fly: 18, swim: 6 }",
  "alignment": "Optional — Gesinnung (z.B. 'CE')",
  "size": "Optional — S/M/L",
  "intelligence": "Optional — Intelligenzstufe (z.B. 'low', 'average', 'high')",
  "treasure_type": "Optional — Schatztyp-Buchstabe (z.B. 'B')",
  "number_appearing": "Optional — Wuerfelformel (z.B. '2d4')",
  "special_abilities": "Optional — Array besonderer Faehigkeiten",
  "habitat": "Optional — Lebensraum (z.B. 'subterranean, forests')",
  "description": "Optional — Beschreibung fuer Atmosphaere",
  "source_page": "Optional — Seitennummer im Quellbuch"
}
```

### Item-Schema

```json
{
  "id": "PFLICHT — snake_case ID",
  "item_type": "PFLICHT — weapon | armor | potion | scroll | tool | treasure | ammunition | shield",
  "name": "Empfohlen — Anzeigename",
  "damage_small_medium": "Bei Waffen — Schaden gegen kleine/mittlere Ziele",
  "damage_large": "Bei Waffen — Schaden gegen grosse Ziele",
  "ac_value": "Bei Ruestung — AC-Wert",
  "ac_bonus": "Bei Schilden — AC-Verbesserung",
  "weight": "Empfohlen — Gewicht in Pfund",
  "speed_factor": "Bei Waffen — Geschwindigkeitsfaktor",
  "cost_gp": "Empfohlen — Kosten in Goldmuenzen",
  "movement_penalty": "Bei Ruestung — Bewegungseinschraenkung",
  "bulk": "Optional — light | medium | heavy",
  "effect": "Bei Traenken/Schriftrollen — Wirkungsbeschreibung",
  "value_gp": "Empfohlen — Wert in Goldmuenzen",
  "source_page": "Optional — Seitennummer im Quellbuch"
}
```

### Spell-Schema

```json
{
  "id": "PFLICHT — snake_case ID (z.B. 'magic_missile')",
  "name": "PFLICHT — Anzeigename",
  "level": "PFLICHT — Zauberstufe (Zahl)",
  "school": "Empfohlen — Schule (z.B. 'Evocation', 'Necromancy')",
  "sphere": "Optional — Sphaere fuer Priester-Zauber",
  "range": "PFLICHT — Reichweite (z.B. '60 yards + 10/level')",
  "duration": "PFLICHT — Dauer (z.B. 'instantaneous', '1 round/level')",
  "casting_time": "PFLICHT — Zauberzeit (z.B. '1', '1 round')",
  "components": "PFLICHT — Array aus V, S, M",
  "area_of_effect": "Optional — Wirkungsbereich",
  "saving_throw": "PFLICHT — Rettungswurf oder 'none'",
  "description": "PFLICHT — Vollstaendige Wirkungsbeschreibung",
  "damage": "Optional — Schadensformel (z.B. '1d4+1 per missile')",
  "at_higher_levels": "Optional — Skalierung bei hoeherer Stufe",
  "reversible": "Optional — true wenn Zauber umkehrbar",
  "source_page": "Optional — Seitennummer im Quellbuch"
}
```

### Tables-Schema (Zufallstabellen)

```json
{
  "id": "PFLICHT — snake_case ID",
  "name": "PFLICHT — Anzeigename (z.B. 'Zufallsmonster — Dungeon Stufe 1')",
  "die": "PFLICHT — Wuerfel (z.B. 'd12', 'd100')",
  "entries": [
    {
      "roll": "PFLICHT — Wurfbereich (z.B. '1-3', '45-50')",
      "result": "PFLICHT — Ergebnis-Beschreibung",
      "monster_ref": "Optional — Verweis auf Monster-ID",
      "item_ref": "Optional — Verweis auf Item-ID",
      "quantity": "Optional — Anzahl (z.B. '1d6')"
    }
  ]
}
```

### Encounter-Schema

```json
{
  "id": "PFLICHT — snake_case ID",
  "module_type": "PFLICHT — combat | event | trap | puzzle",
  "trigger_condition": "PFLICHT — Wann wird die Begegnung ausgeloest",
  "description": "Empfohlen — Narrative Beschreibung",
  "monsters": ["monster_id_1", "monster_id_2"],
  "damage": "Schadenswert oder 'none'",
  "saving_throw": "Rettungswurf-Typ oder 'none'",
  "effect_description": "Was passiert bei Misserfolg",
  "loot": ["loot_id"],
  "xp_reward": 0
}
```

### Loot-Schema

```json
{
  "id": "PFLICHT — snake_case ID",
  "loot_type": "PFLICHT — coins | gems | magic_item | mundane | mixed",
  "description": "PFLICHT — Was gefunden wird",
  "contents": [
    { "item": "gold_pieces", "quantity": "2d6 * 10" },
    { "item": "healing_potion", "quantity": 1 }
  ],
  "value_gp_estimate": "Empfohlen — Geschaetzter Gesamtwert"
}
```

### Sub-Index (empfohlen)

```json
{
  "dataset": "add_2e",
  "generated_utc": "2026-02-28T12:00:00Z",
  "counts": {
    "monsters": 30,
    "items": 50,
    "loot": 40,
    "encounters": 30,
    "total": 150
  },
  "paths": {
    "monsters": ["data/lore/add_2e/monsters/goblin.json", "..."],
    "items": ["data/lore/add_2e/items/longsword.json", "..."],
    "loot": ["data/lore/add_2e/loot/dungeon_hoard.json", "..."],
    "encounters": ["data/lore/add_2e/encounters/ambush_bandits.json", "..."]
  }
}
```

### Systemuebergreifende Lore (CoC-Stil)

Fuer Regelsysteme mit umfangreicher Hintergrundwelt (z.B. Cthulhu) koennen zusaetzliche Lore-Kategorien direkt unter `data/lore/` angelegt werden:

```
data/lore/
├── npcs/               # NPCs mit Persoenlichkeit und Geheimnissen
├── locations/          # Orte mit Atmosphaere und Hinweisen
├── entities/           # Uebernatuerliche Wesenheiten
├── spells/             # Zauber und Rituale
├── organizations/      # Kulte, Firmen, Institutionen
├── documents/          # Schriftstuecke, Briefe, Tagebuecher
├── history/            # Historische Ereignisse
└── ...
```

Diese folgen freieren Schemata (narrativ statt mechanisch). Mindestfelder: `name` + mindestens ein beschreibendes Feld.

---

## 12. Encoding & Formatierung

### PFLICHT-Regeln

| Regel | Details |
|-------|---------|
| Encoding | **UTF-8 ohne BOM**. Kein `\xEF\xBB\xBF` am Dateianfang. |
| Format | Gueltiges JSON. Validierbar mit `python -c "import json; json.load(open('datei.json'))"` |
| Einrueckung | 2 Spaces (empfohlen, nicht erzwungen) |
| Umlaute | Entweder echte UTF-8-Zeichen (`ae`, `oe`, `ue`) oder ASCII-Ersetzungen (`ae`, `oe`, `ue`). Beides valide. |
| Zeilenenden | LF oder CRLF (beides akzeptiert) |
| Dateinamen | `snake_case.json` — keine Leerzeichen, keine Sonderzeichen |

### WICHTIG: BOM-Problem

Die Engine liest Preset-Dateien mit `utf-8-sig` (BOM-tolerant), aber andere Loader (z.B. Adventures, Lore) verwenden `utf-8`. Dateien mit BOM koennen `JSONDecodeError: Unexpected UTF-8 BOM` verursachen.

**Loesung:** Speichere IMMER ohne BOM. Falls du ein Tool verwendest, das BOM einfuegt (z.B. manche Windows-Editoren), entferne den BOM nachtraeglich:

```bash
# BOM von einer Datei entfernen:
sed -i 's/^\xEF\xBB\xBF//' datei.json

# BOM von allen JSONs in einem Verzeichnis entfernen:
find data/lore/system_id/ -name "*.json" -exec sed -i 's/^\xEF\xBB\xBF//' {} +
```

---

## 13. Checkliste fuer neue Module

### Neues Regelsystem anlegen

1. [ ] Datei erstellen: `modules/rulesets/{system_id}.json`
2. [ ] Pflichtfelder pruefen:
   - [ ] `metadata` mit `name`, `version`, `system`, `schema_version`
   - [ ] `dice_system` mit `default_die` und `success_levels` (critical, extreme, hard, fumble)
   - [ ] `characteristics` mit mindestens 1 Attribut (label, roll, multiplier)
   - [ ] `skills` mit mindestens 1 Fertigkeit (base)
3. [ ] `metadata.system` stimmt mit Dateiname ueberein
4. [ ] `metadata.schema_version` gesetzt (Semver, z.B. "1.0.0")
5. [ ] `metadata.game_master_title` und `player_character_title` gesetzt (fuer Prompt)
6. [ ] Skeleton-Sektionen befuellen (siehe Abschnitt 3.3):
   - [ ] Kernmechanik: `combat`, `saving_throws`, `classes`, `races`
   - [ ] Magie: `magic` (falls System Magie hat)
   - [ ] Welt: `alignment`, `movement`, `encumbrance`, `economy`
   - [ ] Zustaende: `conditions`, `healing`
   - [ ] Progression: `experience` (oder `advancement`)
   - [ ] Sonstiges: `time`, `senses`, `travel`, `henchmen_hirelings`, `downtime`
   - [ ] Sondermechaniken: `extensions`
7. [ ] JSON validieren: `python -c "import json; json.load(open('modules/rulesets/{system_id}.json'))"`
8. [ ] Mindestens 1 Preset erstellen (`modules/presets/`)
9. [ ] Lore-Verzeichnis anlegen: `data/lore/{system_id}/` (monsters, items, spells, loot, encounters, tables)

### Neues Abenteuer anlegen

1. [ ] Datei erstellen: `modules/adventures/{adventure_id}.json`
2. [ ] Pflichtfelder:
   - [ ] `title`, `setting`, `difficulty`, `intro`, `hook`, `keeper_lore`
   - [ ] `start_location` verweist auf gueltige Location-ID
   - [ ] `flags` — alle verwendeten Flags initial auf `false`
   - [ ] `locations` als **Array** (nicht Dict!) mit mind. 1 Location
   - [ ] `npcs` als **Array** (nicht Dict!)
3. [ ] Jede Location hat `id`, `name`, `description`
4. [ ] Jeder NPC hat `id`, `name`, `description`
5. [ ] `exits` in Locations verweisen auf gueltige Location-IDs
6. [ ] `start_location` existiert in `locations`
7. [ ] Alle `sets_flag` Referenzen existieren in `flags`
8. [ ] `resolution.conditions` referenzieren gueltige Flags
9. [ ] Preset erstellen das `adventure` und passendes `ruleset` verbindet
10. [ ] JSON validieren

### Neues Lore-Paket anlegen

1. [ ] Verzeichnis: `data/lore/{system_id}/{kategorie}/`
2. [ ] Jede Datei hat mindestens `id` (snake_case)
3. [ ] Dateien nach Schema (siehe Abschnitt 9)
4. [ ] Encoding: UTF-8 ohne BOM
5. [ ] Optional: `index.json` mit Bestandsuebersicht

### Neues Setting-Modul anlegen

1. [ ] Datei: `modules/settings/{setting_id}.json`
2. [ ] Pflichtfelder: `id`, `name`, `compatible_rulesets`, `epoch`, `geography`, `atmosphere`
3. [ ] Schema nach Abschnitt 6
4. [ ] Encoding: UTF-8 ohne BOM
5. [ ] `compatible_rulesets` korrekt (Array von Ruleset-IDs)
6. [ ] In mindestens einem Preset referenziert

### Neues Keeper-Modul anlegen

1. [ ] Datei: `modules/keepers/{keeper_id}.json`
2. [ ] Pflichtfelder: `id`, `name`, `tone`
3. [ ] Schema nach Abschnitt 7
4. [ ] Encoding: UTF-8 ohne BOM
5. [ ] `compatible_rulesets` korrekt
6. [ ] In mindestens einem Preset referenziert

### Neues Extras-Modul anlegen

1. [ ] Datei: `modules/extras/{extra_id}.json`
2. [ ] Pflichtfelder: `id`, `name`, `type`, `prompt_injection`
3. [ ] `type` ist `atmosphere`, `game_mode` oder `rule_extension`
4. [ ] Schema nach Abschnitt 8
5. [ ] Encoding: UTF-8 ohne BOM
6. [ ] `compatible_rulesets` korrekt (`null` fuer universal)

### Neuen Charakter anlegen

1. [ ] Datei: `modules/characters/{character_id}.json`
2. [ ] Pflichtfelder: `id`, `name`, `compatible_rulesets`, `archetype`
3. [ ] `characteristics` nutzt die Attribute des Ziel-Regelsystems
4. [ ] `derived_stats` enthaelt mindestens `HP`
5. [ ] Schema nach Abschnitt 9
6. [ ] Encoding: UTF-8 ohne BOM
7. [ ] In Preset referenzierbar via `"character": "character_id"`

### Neue Party anlegen (Platzhalter)

1. [ ] Datei: `modules/parties/{party_id}.json`
2. [ ] Pflichtfelder: `id`, `name`, `members`
3. [ ] `members` referenziert gueltige `character_id`s
4. [ ] Schema nach Abschnitt 10
5. [ ] Encoding: UTF-8 ohne BOM

---

## 14. Referenz-Beispiele

### Minimales Ruleset (lauffaehig)

```json
{
  "metadata": {
    "name": "Micro RPG",
    "version": "1.0",
    "system": "micro_rpg",
    "game_master_title": "Erzaehler",
    "player_character_title": "Held"
  },
  "dice_system": {
    "default_die": "d20",
    "success_levels": {
      "critical": 1,
      "extreme": 0.25,
      "hard": 0.5,
      "fumble": 20
    }
  },
  "characteristics": {
    "STR": { "label": "Staerke", "roll": "3d6", "multiplier": 1 },
    "DEX": { "label": "Geschick", "roll": "3d6", "multiplier": 1 },
    "WIL": { "label": "Wille", "roll": "3d6", "multiplier": 1 }
  },
  "skills": {
    "Kaempfen": { "base": 30 },
    "Schleichen": { "base": 20 },
    "Wahrnehmung": { "base": 25 }
  }
}
```

### Minimales Abenteuer (lauffaehig)

```json
{
  "title": "Die verlassene Muehle",
  "setting": "Ein Dorf am Waldrand",
  "difficulty": "Einsteiger",
  "intro": "Geruechte ueber seltsame Geraeusche in der alten Muehle.",
  "hook": "Findet heraus, was in der Muehle vor sich geht.",
  "keeper_lore": "Ein Wegelagerer hat die Muehle als Versteck bezogen.",
  "start_location": "dorfplatz",
  "flags": {
    "muehle_betreten": false,
    "bandit_besiegt": false
  },
  "locations": [
    {
      "id": "dorfplatz",
      "name": "Dorfplatz",
      "description": "Ein staubiger Platz mit einem Brunnen.",
      "atmosphere": "Ruhig, aber angespannt.",
      "npcs_present": [],
      "clues_available": [],
      "exits": {
        "muehle": "Ein Pfad fuehrt zur alten Muehle."
      }
    },
    {
      "id": "muehle",
      "name": "Alte Muehle",
      "description": "Ein verfallenes Gebaeude. Die Tuer steht halb offen.",
      "atmosphere": "Modrig, knarrend, verdaechtige Stille.",
      "npcs_present": ["bandit"],
      "clues_available": [],
      "exits": {
        "dorfplatz": "Zurueck zum Dorf."
      },
      "events": [
        {
          "trigger": "Spieler betreten die Muehle",
          "effect": "Der Bandit springt aus dem Schatten hervor.",
          "sets_flag": "muehle_betreten"
        }
      ]
    }
  ],
  "npcs": [
    {
      "id": "bandit",
      "name": "Raeubiger Tomas",
      "description": "Ein unrasierter Mann mit einem Kurzschwert.",
      "stats": { "ac": 8, "hp": 5, "thac0": 20 },
      "behavior": "Greift bei Entdeckung sofort an."
    }
  ],
  "clues": [],
  "resolution": {
    "success": "Der Bandit ist besiegt. Das Dorf ist sicher.",
    "condition": "bandit_besiegt == true"
  }
}
```

### Minimales Preset

```json
{
  "ruleset": "micro_rpg",
  "adventure": "verlassene_muehle",
  "difficulty": "normal",
  "atmosphere": "Rustikale Fantasy, erdverbunden, bodenstaendig.",
  "keeper_persona": "Ein freundlicher Dorfgeschichtenerzaehler."
}
```

### Minimaler Monster-Eintrag (Lore)

```json
{
  "id": "wolf",
  "ac": 7,
  "hit_dice": "2+2",
  "hp_avg": 11,
  "thac0": 19,
  "attacks": "1 (1d4+1)",
  "morale": 8,
  "xp_value": 35
}
```

---

## 15. Schema-Versionierung

### PFLICHT-Regel

Jede JSON-Datei in `modules/` **MUSS** das Feld `schema_version` tragen.

**Format:** Semver `"MAJOR.MINOR.PATCH"` (z.B. `"1.0.0"`, `"2.1.3"`)

**Platzierung:**
- Bei Rulesets: in `metadata.schema_version`
- Bei allen anderen Modulen: als Top-Level-Feld `"schema_version"`

### Wann Version bumpen?

| Aenderung | Bump | Beispiel |
|-----------|------|----------|
| Felder umbenannt, entfernt, Struktur gebrochen | **MAJOR** | `saving_throws` von Array zu Objekt |
| Neue optionale Felder hinzugefuegt | **MINOR** | `races`-Sektion ergaenzt |
| Inhaltliche Korrekturen, Tippfehler | **PATCH** | HP-Wert korrigiert |

### Regeln fuer Agents

1. **Agents die Module aendern MUESSEN die Version bumpen**
2. Neue Module starten bei `"1.0.0"`
3. Bei Schema-Breaking-Changes: MAJOR bump + Vermerk in Commit-Message
4. Die Engine validiert `schema_version` NICHT — es dient der Nachvollziehbarkeit

### Beispiel

```json
{
  "metadata": {
    "name": "AD&D",
    "version": "2nd Edition",
    "system": "add_2e",
    "schema_version": "1.0.0"
  }
}
```

```json
{
  "id": "cthulhu_1920",
  "schema_version": "1.0.0",
  "name": "Neuengland der 1920er"
}
```

---

## Anhang: Bestehende Module (Stand 2026-02-28)

### Rulesets

| system_id | Name | Wuerfel | Spielleiter-Titel |
|-----------|------|---------|-------------------|
| `cthulhu_7e` | Call of Cthulhu 7th Ed. | d100 | Keeper of Arcane Lore |
| `add_2e` | AD&D 2nd Edition | d20 | Dungeon Master |

### Adventures

| adventure_id | Titel | Regelsystem | Locations | NPCs |
|-------------|-------|-------------|-----------|------|
| `spukhaus` | The Haunting | cthulhu_7e | 4 | 3 |
| `template` | Template-Abenteuer | cthulhu_7e | 4 | 2 |
| `goblin_cave` | Goblin Cave | add_2e | 4 | 3 |

### Presets

| Name | Ruleset | Adventure | Difficulty |
|------|---------|-----------|------------|
| `coc_classic` | cthulhu_7e | spukhaus | hardcore |
| `add_demo` | add_2e | goblin_cave | heroic |
| `add_fantasy` | add_2e | null (Free Roam) | heroic |

### Characters

| character_id | Name | Regelsystem | Klasse |
|-------------|------|-------------|--------|
| `coc_investigator` | Dr. Henry Walters | cthulhu_7e | Antiquar |
| `add_fighter` | Thorgar Eisenfaust | add_2e | Fighter |
| `add_mage` | Elara Sternenschein | add_2e | Mage |

### Parties

(Platzhalter — noch keine konkreten Parties angelegt)

### Lore

| Verzeichnis | Dateien | Kategorien |
|-------------|---------|------------|
| `data/lore/` (CoC) | ~1573 | npcs, items, entities, spells, locations, ... |
| `data/lore/add_2e/` | ~150 | monsters, items, loot, encounters |
