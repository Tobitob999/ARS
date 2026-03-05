#!/usr/bin/env python3
"""
Generiert individuelle JSON-Snippets fuer alle magischen Gegenstaende,
Edelsteine und Kunstgegenstaende aus den DMG-Tabellen in core/mechanics.py.

Ausgabe: data/lore/add_2e/items/{kategorie}/{item_slug}.json
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.mechanics import MechanicsEngine

# ── Kategorie → Unterverzeichnis Mapping ────────────────────────────────
CATEGORY_DIRS = {
    "Potions and Oils": "potions",
    "Scrolls": "scrolls",
    "Rings": "rings",
    "Rods": "rods",
    "Staves": "staves",
    "Wands": "wands",
    "Books and Tomes": "books",
    "Jewels and Jewelry": "jewelry_magic",
    "Cloaks and Robes": "cloaks_robes",
    "Boots and Gloves": "boots_gloves",
    "Girdles and Helms": "girdles_helms",
    "Bags and Bottles": "bags_bottles",
    "Dusts and Stones": "dusts_stones",
    "Household Items and Tools": "household",
    "Musical Instruments": "instruments",
    "The Weird Stuff": "weird",
    "Armor and Shields": "armor",
    "Weapons": "weapons",
}

# ── DMG Table Nummern pro Kategorie ─────────────────────────────────────
TABLE_NUMBERS = {
    "Potions and Oils": "89", "Scrolls": "90", "Rings": "91",
    "Rods": "92", "Staves": "93", "Wands": "94",
    "Books and Tomes": "95", "Jewels and Jewelry": "96",
    "Cloaks and Robes": "97", "Boots and Gloves": "98",
    "Girdles and Helms": "99", "Bags and Bottles": "100",
    "Dusts and Stones": "101", "Household Items and Tools": "102-105",
    "Musical Instruments": "106", "The Weird Stuff": "107",
    "Armor and Shields": "108", "Weapons": "108-110",
}

# ── Bekannte Item-Mechaniken ────────────────────────────────────────────
# Format: item_name -> {effect, weight, value_gp, xp_value, usable_by, charges}
KNOWN_MECHANICS = {
    # ── Potions ──────────────────────────────────────────────────────────
    "Potion of Healing": {"effect": "Heilt 1d8 Trefferpunkte", "weight": 0.5, "value_gp": 200, "xp_value": 200, "charges": 1},
    "Potion of Extra-Healing": {"effect": "Heilt 3d8 Trefferpunkte", "weight": 0.5, "value_gp": 400, "xp_value": 400, "charges": 1},
    "Potion of Giant Strength": {"effect": "STR 19+ fuer 1 Turn", "weight": 0.5, "value_gp": 550, "xp_value": 550, "charges": 1},
    "Potion of Speed": {"effect": "Haste fuer 5d4 Runden", "weight": 0.5, "value_gp": 200, "xp_value": 200, "charges": 1},
    "Potion of Flying": {"effect": "Fliegen (MV 12) fuer 1d4+1 Turns", "weight": 0.5, "value_gp": 500, "xp_value": 500, "charges": 1},
    "Potion of Invisibility": {"effect": "Unsichtbarkeit wie Zauber", "weight": 0.5, "value_gp": 250, "xp_value": 250, "charges": 1},
    "Potion of Fire Resistance": {"effect": "+3 Rettungswurf vs Feuer, halber Feuerschaden", "weight": 0.5, "value_gp": 250, "xp_value": 250, "charges": 1},
    "Potion of Heroism": {"effect": "Temporaere Levelsteigerung (Krieger)", "weight": 0.5, "value_gp": 300, "xp_value": 300, "charges": 1, "usable_by": "warrior"},
    "Potion of Invulnerability": {"effect": "Bessere AC und Rettungswuerfe (Krieger)", "weight": 0.5, "value_gp": 350, "xp_value": 350, "charges": 1, "usable_by": "warrior"},
    "Potion of Longevity": {"effect": "Verjuengt um 1-12 Jahre", "weight": 0.5, "value_gp": 500, "xp_value": 500, "charges": 1},
    "Potion of Delusion": {"effect": "Kein Effekt, Trinker glaubt an Wirkung", "weight": 0.5, "value_gp": 0, "xp_value": 0, "charges": 1},
    "Potion of Diminution": {"effect": "Schrumpft auf 6 Zoll Groesse", "weight": 0.5, "value_gp": 300, "xp_value": 300, "charges": 1},
    "Potion of Growth": {"effect": "Waechst auf 30 Fuss Hoehe", "weight": 0.5, "value_gp": 250, "xp_value": 250, "charges": 1},
    "Potion of Clairvoyance": {"effect": "Hellsicht wie Zauber", "weight": 0.5, "value_gp": 300, "xp_value": 300, "charges": 1},
    "Potion of Climbing": {"effect": "Klettern wie Dieb 95%", "weight": 0.5, "value_gp": 300, "xp_value": 300, "charges": 1},
    "Potion of ESP": {"effect": "Gedankenlesen wie Zauber", "weight": 0.5, "value_gp": 500, "xp_value": 500, "charges": 1},
    "Potion of Gaseous Form": {"effect": "Gasfoermig, durch Ritzen passierbar", "weight": 0.5, "value_gp": 300, "xp_value": 300, "charges": 1},
    "Potion of Levitation": {"effect": "Schweben wie Zauber", "weight": 0.5, "value_gp": 250, "xp_value": 250, "charges": 1},
    "Potion of Super-Heroism": {"effect": "Grosse temporaere Levelsteigerung (Krieger)", "weight": 0.5, "value_gp": 450, "xp_value": 450, "charges": 1, "usable_by": "warrior"},
    "Potion of Animal Control": {"effect": "Kontrolle ueber 1 Tierart", "weight": 0.5, "value_gp": 250, "xp_value": 250, "charges": 1},
    "Potion of Plant Control": {"effect": "Kontrolle ueber Pflanzen", "weight": 0.5, "value_gp": 250, "xp_value": 250, "charges": 1},
    "Potion of Undead Control": {"effect": "Kontrolle ueber Untote", "weight": 0.5, "value_gp": 700, "xp_value": 700, "charges": 1},
    "Potion of Polymorph Self": {"effect": "Verwandlung wie Zauber", "weight": 0.5, "value_gp": 200, "xp_value": 200, "charges": 1},
    "Potion of Treasure Finding": {"effect": "Zeigt Richtung zum naechsten Schatz", "weight": 0.5, "value_gp": 600, "xp_value": 600, "charges": 1},
    "Potion of Vitality": {"effect": "Stellt Erschoepfung wieder her", "weight": 0.5, "value_gp": 300, "xp_value": 300, "charges": 1},
    "Potion of Water Breathing": {"effect": "Unterwasseratmung fuer 1 Stunde", "weight": 0.5, "value_gp": 400, "xp_value": 400, "charges": 1},
    "Potion of Rainbow Hues": {"effect": "Schillernde Farben, hypnotisierend", "weight": 0.5, "value_gp": 200, "xp_value": 200, "charges": 1},
    "Oil of Acid Resistance": {"effect": "Immunitaet gegen Saeure fuer 1 Turn", "weight": 0.5, "value_gp": 500, "xp_value": 500, "charges": 1},
    "Oil of Disenchantment": {"effect": "Entfernt Magie von Gegenstaenden", "weight": 0.5, "value_gp": 750, "xp_value": 750, "charges": 1},
    "Oil of Etherealness": {"effect": "Uebergang in die Aetherische Ebene", "weight": 0.5, "value_gp": 600, "xp_value": 600, "charges": 1},
    "Oil of Fiery Burning": {"effect": "Entzuendet sich, 5d6 Feuerschaden", "weight": 0.5, "value_gp": 500, "xp_value": 500, "charges": 1},
    "Oil of Impact": {"effect": "+3 Schaden fuer eine Waffe", "weight": 0.5, "value_gp": 750, "xp_value": 750, "charges": 1},
    "Oil of Slipperiness": {"effect": "Ungreifbar, entkommt Fesseln", "weight": 0.5, "value_gp": 400, "xp_value": 400, "charges": 1},
    "Oil of Timelessness": {"effect": "Konserviert Gegenstaende ewig", "weight": 0.5, "value_gp": 500, "xp_value": 500, "charges": 1},
    "Philter of Glibness": {"effect": "Ueberzeugend reden, Luegen unerkannt", "weight": 0.5, "value_gp": 500, "xp_value": 500, "charges": 1},
    "Philter of Love": {"effect": "Ziel verliebt sich in den Naechsten", "weight": 0.5, "value_gp": 200, "xp_value": 200, "charges": 1},
    "Philter of Persuasiveness": {"effect": "CHA +5 beim Ueberzeugen", "weight": 0.5, "value_gp": 400, "xp_value": 400, "charges": 1},
    "Elixir of Health": {"effect": "Heilt Krankheit, Gift, Blindheit", "weight": 0.5, "value_gp": 350, "xp_value": 350, "charges": 1},
    "Elixir of Madness": {"effect": "Verursacht dauerhaften Wahnsinn", "weight": 0.5, "value_gp": 0, "xp_value": 0, "charges": 1},
    "Elixir of Youth": {"effect": "Verjuengt um 1d10 Jahre permanent", "weight": 0.5, "value_gp": 500, "xp_value": 500, "charges": 1},
    # ── Weapons ──────────────────────────────────────────────────────────
    "Long Sword +1": {"effect": "+1 Angriff und Schaden", "weight": 4, "value_gp": 1000, "xp_value": 400, "usable_by": "warrior, rogue"},
    "Long Sword +2": {"effect": "+2 Angriff und Schaden", "weight": 4, "value_gp": 2000, "xp_value": 800, "usable_by": "warrior, rogue"},
    "Long Sword +3": {"effect": "+3 Angriff und Schaden", "weight": 4, "value_gp": 3500, "xp_value": 1400, "usable_by": "warrior, rogue"},
    "Long Sword +3, Frost Brand": {"effect": "+3, +6 vs feuernutzende, loescht Feuer", "weight": 4, "value_gp": 4000, "xp_value": 1600, "usable_by": "warrior"},
    "Long Sword +4, Defender": {"effect": "+4, kann Bonus auf AC uebertragen", "weight": 4, "value_gp": 5000, "xp_value": 3000, "usable_by": "warrior"},
    "Long Sword +5, Defender": {"effect": "+5, kann Bonus auf AC uebertragen", "weight": 4, "value_gp": 6000, "xp_value": 3500, "usable_by": "warrior"},
    "Long Sword +5, Holy Avenger": {"effect": "+5/+10 vs Boese, Dispel Magic 5' Radius", "weight": 4, "value_gp": 8000, "xp_value": 4000, "usable_by": "paladin"},
    "Long Sword, Vorpal": {"effect": "Koepft bei nat. 20", "weight": 4, "value_gp": 7500, "xp_value": 4000, "usable_by": "warrior"},
    "Long Sword of Wounding": {"effect": "+1, Wunden heilen nicht normal", "weight": 4, "value_gp": 4500, "xp_value": 2000, "usable_by": "warrior"},
    "Long Sword of Life Stealing": {"effect": "+1, entzieht Lebensstufen bei nat. 20", "weight": 4, "value_gp": 4000, "xp_value": 2500, "usable_by": "warrior"},
    "Long Sword of Sharpness": {"effect": "+1, trennt Gliedmassen bei 18+", "weight": 4, "value_gp": 5000, "xp_value": 3000, "usable_by": "warrior"},
    "Long Sword, Luck Blade": {"effect": "+2, 1d4+1 Wishes", "weight": 4, "value_gp": 6000, "xp_value": 3000, "usable_by": "warrior, rogue"},
    "Long Sword, Nine Lives Stealer": {"effect": "+2, 9 sofortige Toetungen bei nat. 20", "weight": 4, "value_gp": 5000, "xp_value": 3000, "usable_by": "warrior"},
    "Battle Axe +1": {"effect": "+1 Angriff und Schaden", "weight": 7, "value_gp": 800, "xp_value": 400, "usable_by": "warrior"},
    "Axe +1": {"effect": "+1 Angriff und Schaden", "weight": 6, "value_gp": 800, "xp_value": 400, "usable_by": "warrior"},
    "Axe +2": {"effect": "+2 Angriff und Schaden", "weight": 6, "value_gp": 1500, "xp_value": 800, "usable_by": "warrior"},
    "Axe +3": {"effect": "+3 Angriff und Schaden", "weight": 6, "value_gp": 2500, "xp_value": 1200, "usable_by": "warrior"},
    "Dagger +1": {"effect": "+1 Angriff und Schaden", "weight": 1, "value_gp": 300, "xp_value": 100, "usable_by": "all"},
    "Dagger +2": {"effect": "+2 Angriff und Schaden", "weight": 1, "value_gp": 500, "xp_value": 300, "usable_by": "all"},
    "Dagger +2, +3 vs. Larger": {"effect": "+2/+3 vs groessere Kreaturen", "weight": 1, "value_gp": 500, "xp_value": 300, "usable_by": "all"},
    "Dagger of Venom": {"effect": "+1, Gift (Save or Die)", "weight": 1, "value_gp": 3000, "xp_value": 350, "usable_by": "all"},
    "Mace +1": {"effect": "+1 Angriff und Schaden", "weight": 8, "value_gp": 800, "xp_value": 350, "usable_by": "all"},
    "Mace +2": {"effect": "+2 Angriff und Schaden", "weight": 8, "value_gp": 1500, "xp_value": 700, "usable_by": "all"},
    "Mace +3": {"effect": "+3 Angriff und Schaden", "weight": 8, "value_gp": 2500, "xp_value": 1200, "usable_by": "all"},
    "Mace +4": {"effect": "+4 Angriff und Schaden", "weight": 8, "value_gp": 4000, "xp_value": 1750, "usable_by": "all"},
    "Mace of Disruption": {"effect": "+1, vernichtet Untote bei Beruehrung", "weight": 8, "value_gp": 4500, "xp_value": 2500, "usable_by": "priest"},
    "Mace of Smiting": {"effect": "+3, +5 vs Konstrukte, zerstoert Golems", "weight": 8, "value_gp": 5000, "xp_value": 2000, "usable_by": "all"},
    "Mace of Terror": {"effect": "+2, Fear-Aura 3x/Tag", "weight": 8, "value_gp": 4000, "xp_value": 1500, "usable_by": "all"},
    "Hammer +1": {"effect": "+1 Angriff und Schaden", "weight": 5, "value_gp": 800, "xp_value": 400, "usable_by": "warrior, priest"},
    "Hammer +2": {"effect": "+2 Angriff und Schaden", "weight": 5, "value_gp": 1500, "xp_value": 800, "usable_by": "warrior, priest"},
    "Hammer +3, Dwarven Thrower": {"effect": "+3, kehrt nach Wurf zurueck, +4 fuer Zwerge", "weight": 5, "value_gp": 4000, "xp_value": 2500, "usable_by": "warrior (dwarf)"},
    "Hammer of Thunderbolts": {"effect": "+3, Betaeubung, +5 mit Gauntlets+Girdle", "weight": 5, "value_gp": 6000, "xp_value": 3500, "usable_by": "warrior"},
    "Short Sword +1": {"effect": "+1 Angriff und Schaden", "weight": 3, "value_gp": 700, "xp_value": 300, "usable_by": "warrior, rogue"},
    "Short Sword +2": {"effect": "+2 Angriff und Schaden", "weight": 3, "value_gp": 1500, "xp_value": 600, "usable_by": "warrior, rogue"},
    "Spear +1": {"effect": "+1 Angriff und Schaden", "weight": 5, "value_gp": 500, "xp_value": 200, "usable_by": "all"},
    "Spear +2": {"effect": "+2 Angriff und Schaden", "weight": 5, "value_gp": 1000, "xp_value": 400, "usable_by": "all"},
    "Spear +3": {"effect": "+3 Angriff und Schaden", "weight": 5, "value_gp": 2000, "xp_value": 800, "usable_by": "all"},
    "Two-Handed Sword +1": {"effect": "+1 Angriff und Schaden", "weight": 10, "value_gp": 1000, "xp_value": 500, "usable_by": "warrior"},
    "Arrow +1 (2d6)": {"effect": "+1 Angriff und Schaden, 2d6 Stueck", "weight": 0.1, "value_gp": 20, "xp_value": 20, "usable_by": "warrior, rogue"},
    "Bow +1": {"effect": "+1 Angriff", "weight": 3, "value_gp": 1000, "xp_value": 500, "usable_by": "warrior, rogue"},
    "Flail +1": {"effect": "+1 Angriff und Schaden", "weight": 8, "value_gp": 800, "xp_value": 400, "usable_by": "warrior, priest"},
    "Morning Star +1": {"effect": "+1 Angriff und Schaden", "weight": 7, "value_gp": 800, "xp_value": 400, "usable_by": "warrior, priest"},
    "Scimitar +1": {"effect": "+1 Angriff und Schaden", "weight": 4, "value_gp": 700, "xp_value": 300, "usable_by": "warrior, rogue"},
    "Scimitar +2": {"effect": "+2 Angriff und Schaden", "weight": 4, "value_gp": 1500, "xp_value": 600, "usable_by": "warrior, rogue"},
    "War Hammer +1": {"effect": "+1 Angriff und Schaden", "weight": 5, "value_gp": 800, "xp_value": 400, "usable_by": "warrior, priest"},
    "War Hammer +2": {"effect": "+2 Angriff und Schaden", "weight": 5, "value_gp": 1500, "xp_value": 800, "usable_by": "warrior, priest"},
    "Javelin +2": {"effect": "+2 Angriff und Schaden (Wurfwaffe)", "weight": 2, "value_gp": 800, "xp_value": 400, "usable_by": "warrior"},
    "Javelin of Lightning": {"effect": "Verwandelt sich in Blitz (5d6)", "weight": 2, "value_gp": 3000, "xp_value": 1500, "usable_by": "warrior"},
    "Javelin of Piercing": {"effect": "+6 Angriff, 1d6+6 Schaden", "weight": 2, "value_gp": 2500, "xp_value": 1500, "usable_by": "warrior"},
    # ── Armor ────────────────────────────────────────────────────────────
    "Chain Mail +1": {"effect": "AC 4 (Basis AC 5, +1)", "weight": 40, "value_gp": 1500, "xp_value": 600, "usable_by": "warrior, priest"},
    "Chain Mail +2": {"effect": "AC 3", "weight": 40, "value_gp": 3000, "xp_value": 1200, "usable_by": "warrior, priest"},
    "Chain Mail +3": {"effect": "AC 2", "weight": 40, "value_gp": 5000, "xp_value": 2000, "usable_by": "warrior, priest"},
    "Plate Mail +1": {"effect": "AC 2 (Basis AC 3, +1)", "weight": 45, "value_gp": 3000, "xp_value": 1500, "usable_by": "warrior"},
    "Plate Mail +2": {"effect": "AC 1", "weight": 45, "value_gp": 5000, "xp_value": 2500, "usable_by": "warrior"},
    "Plate Mail +3": {"effect": "AC 0", "weight": 45, "value_gp": 8000, "xp_value": 3500, "usable_by": "warrior"},
    "Full Plate +1": {"effect": "AC 0 (Basis AC 1, +1)", "weight": 70, "value_gp": 5000, "xp_value": 2500, "usable_by": "warrior"},
    "Full Plate +2": {"effect": "AC -1", "weight": 70, "value_gp": 8000, "xp_value": 4000, "usable_by": "warrior"},
    "Leather Armor +1": {"effect": "AC 7 (Basis AC 8, +1)", "weight": 15, "value_gp": 500, "xp_value": 300, "usable_by": "all"},
    "Shield +1": {"effect": "AC -1 zum bestehenden AC", "weight": 5, "value_gp": 500, "xp_value": 250, "usable_by": "warrior, priest"},
    "Shield +2": {"effect": "AC -2", "weight": 5, "value_gp": 1000, "xp_value": 500, "usable_by": "warrior, priest"},
    "Shield +3": {"effect": "AC -3", "weight": 5, "value_gp": 1500, "xp_value": 750, "usable_by": "warrior, priest"},
    "Elven Chain Mail": {"effect": "AC 5, Diebe koennen es tragen, zaehlt nicht als Metallruestung", "weight": 15, "value_gp": 6000, "xp_value": 3500, "usable_by": "all"},
    # ── Rings ────────────────────────────────────────────────────────────
    "Ring of Protection +1": {"effect": "AC -1, Rettungswurf +1", "weight": 0, "value_gp": 2000, "xp_value": 1000},
    "Ring of Protection +2": {"effect": "AC -2, Rettungswurf +2", "weight": 0, "value_gp": 3000, "xp_value": 1500},
    "Ring of Protection +3": {"effect": "AC -3, Rettungswurf +3", "weight": 0, "value_gp": 4000, "xp_value": 2000},
    "Ring of Invisibility": {"effect": "Unsichtbarkeit nach Belieben", "weight": 0, "value_gp": 3500, "xp_value": 1500},
    "Ring of Free Action": {"effect": "Immun gegen Paralysis, Hold, Web", "weight": 0, "value_gp": 2000, "xp_value": 1000},
    "Ring of Fire Resistance": {"effect": "Rettungswurf +3 vs Feuer, halber Schaden", "weight": 0, "value_gp": 2000, "xp_value": 1000},
    "Ring of Regeneration": {"effect": "Heilt 1 HP/Runde", "weight": 0, "value_gp": 5000, "xp_value": 5000},
    "Ring of Spell Storing": {"effect": "Speichert 1d4+1 Zauber", "weight": 0, "value_gp": 4000, "xp_value": 2500},
    "Ring of Wizardry": {"effect": "Verdoppelt Zauberstufen-Slots", "weight": 0, "value_gp": 7000, "xp_value": 4000, "usable_by": "wizard"},
    "Ring of Multiple Wishes": {"effect": "1d4 Wuensche", "weight": 0, "value_gp": 25000, "xp_value": 5000},
    "Ring of the Ram": {"effect": "Telekinetischer Stoss, 1d6-3d6 Schaden", "weight": 0, "value_gp": 3000, "xp_value": 1500},
    "Ring of Shooting Stars": {"effect": "Ball Lightning, Shooting Stars, Faerie Fire", "weight": 0, "value_gp": 3000, "xp_value": 1500},
    # ── Wands ────────────────────────────────────────────────────────────
    "Wand of Magic Missiles": {"effect": "3 Magic Missiles pro Ladung", "weight": 1, "value_gp": 4000, "xp_value": 1000, "charges": 100, "usable_by": "wizard"},
    "Wand of Fire": {"effect": "Fireball/Wall of Fire", "weight": 1, "value_gp": 6000, "xp_value": 1500, "charges": 100, "usable_by": "wizard"},
    "Wand of Lightning": {"effect": "Lightning Bolt", "weight": 1, "value_gp": 5000, "xp_value": 1200, "charges": 100, "usable_by": "wizard"},
    "Wand of Frost": {"effect": "Cone of Cold/Wall of Ice", "weight": 1, "value_gp": 5000, "xp_value": 1200, "charges": 100, "usable_by": "wizard"},
    "Wand of Paralyzation": {"effect": "Paralysiert Ziel", "weight": 1, "value_gp": 4000, "xp_value": 1000, "charges": 100, "usable_by": "wizard"},
    "Wand of Wonder": {"effect": "Zufaelliger Effekt pro Ladung!", "weight": 1, "value_gp": 2000, "xp_value": 500, "charges": 100, "usable_by": "wizard"},
    "Wand of Polymorphing": {"effect": "Polymorph Other", "weight": 1, "value_gp": 4500, "xp_value": 1000, "charges": 100, "usable_by": "wizard"},
    "Wand of Negation": {"effect": "Loescht andere Wands/Staves aus", "weight": 1, "value_gp": 3500, "xp_value": 800, "charges": 100, "usable_by": "wizard"},
    # ── Staves ───────────────────────────────────────────────────────────
    "Staff of the Magi": {"effect": "Multiple Kraefte, Spell Absorption, Retributive Strike", "weight": 5, "value_gp": 15000, "xp_value": 8000, "charges": 25, "usable_by": "wizard"},
    "Staff of Power": {"effect": "Multiple Kampfkraefte, Spell Storing", "weight": 5, "value_gp": 12000, "xp_value": 6000, "charges": 25, "usable_by": "wizard"},
    "Staff of Striking": {"effect": "4d6 Schaden pro Ladung", "weight": 5, "value_gp": 3000, "xp_value": 1500, "charges": 25, "usable_by": "wizard, priest"},
    "Staff of Curing": {"effect": "Heilt Krankheit, Blindheit, Wunden", "weight": 5, "value_gp": 5000, "xp_value": 2500, "charges": 25, "usable_by": "priest"},
    "Staff of Healing": {"effect": "Cure Wounds mehrfach", "weight": 5, "value_gp": 4000, "xp_value": 2000, "charges": 25, "usable_by": "priest"},
    # ── Misc Magic ───────────────────────────────────────────────────────
    "Bag of Holding": {"effect": "Haelt 500 Pfund in kleinem Beutel", "weight": 15, "value_gp": 5000, "xp_value": 2500},
    "Boots of Speed": {"effect": "Verdoppelt Bewegungsrate", "weight": 1, "value_gp": 3000, "xp_value": 2500},
    "Boots of Elvenkind": {"effect": "Lautloses Gehen", "weight": 1, "value_gp": 2000, "xp_value": 1000},
    "Cloak of Elvenkind": {"effect": "Fast unsichtbar in natuerlicher Umgebung", "weight": 1, "value_gp": 2000, "xp_value": 1000},
    "Cloak of Displacement": {"effect": "-2 AC, Angreifer verfehlen bei erstem Angriff", "weight": 1, "value_gp": 3000, "xp_value": 1500},
    "Gauntlets of Ogre Power": {"effect": "STR 18/00", "weight": 1, "value_gp": 3000, "xp_value": 1000, "usable_by": "warrior"},
    "Girdle of Giant Strength": {"effect": "STR 19+", "weight": 1, "value_gp": 5000, "xp_value": 2500, "usable_by": "warrior"},
    "Crystal Ball": {"effect": "Fernwirkung/Scrying", "weight": 5, "value_gp": 5000, "xp_value": 1000, "usable_by": "wizard"},
    "Deck of Many Things": {"effect": "Zufaellige machtvolle Effekte pro Karte", "weight": 0.5, "value_gp": 10000, "xp_value": 0},
    "Carpet of Flying": {"effect": "Fliegender Teppich (MV 30)", "weight": 25, "value_gp": 8000, "xp_value": 3000},
    "Portable Hole": {"effect": "Extradimensionaler Raum (6'x10')", "weight": 0, "value_gp": 5000, "xp_value": 3500},
    "Helm of Brilliance": {"effect": "Prismatic Spray, Wall of Fire, Fireball, Detect Undead", "weight": 3, "value_gp": 8000, "xp_value": 3000, "usable_by": "warrior, priest"},
    "Helm of Telepathy": {"effect": "ESP 60', Suggestion 1x/Runde", "weight": 3, "value_gp": 3000, "xp_value": 1000},
    "Rope of Climbing": {"effect": "Klettert selbststaendig, 60 Fuss", "weight": 3, "value_gp": 2000, "xp_value": 1000},
    "Figurine of Wondrous Power": {"effect": "Verwandelt sich in echte Kreatur", "weight": 1, "value_gp": 4000, "xp_value": 2000},
    "Efreeti Bottle": {"effect": "Beschwoemrt Efreeti (3 Wuensche)", "weight": 5, "value_gp": 15000, "xp_value": 5000},
    "Sphere of Annihilation": {"effect": "Zerstoert alle Materie bei Beruehrung", "weight": 0, "value_gp": 20000, "xp_value": 3000, "usable_by": "wizard"},
}

# ── Gem-Beschreibungen ──────────────────────────────────────────────────
GEM_DESCRIPTIONS = {
    "Azurit": "Undurchsichtig, tiefblau gefleckt",
    "Banded Achat": "Braun, blau, rot und weiss gestreift",
    "Blauer Quarz": "Transparent blassblau",
    "Augen-Achat": "Grau, weiss, braun, blaue und gruene Kreise",
    "Haematit": "Grauschwarz",
    "Lapislazuli": "Hell- oder dunkelblau mit gelben Flecken",
    "Malachit": "Gestreiftes helles und dunkles Gruen",
    "Moos-Achat": "Rosa, gelbweiss mit moosartigen Markierungen",
    "Obsidian": "Tiefschwarz",
    "Rhodochrosit": "Hellrosa",
    "Tigerauge": "Goldbraun mit dunklen Streifen",
    "Tuerkis": "Aqua mit dunkler Marmorierung",
    "Blutstein": "Dunkelgrau mit roten Flecken",
    "Karneol": "Orange bis rotbraun",
    "Chalcedon": "Weiss",
    "Chrysopras": "Durchscheinend apfel- bis smaragdgruen",
    "Citrin": "Blassgelb-braun",
    "Jaspis": "Blau, schwarz bis braun",
    "Mondstein": "Weiss mit blassblauem Schimmer",
    "Onyx": "Schwarz, weiss oder Baender aus beidem",
    "Bergkristall": "Klar, transparent",
    "Sardonyx": "Baender aus Rot und Weiss",
    "Rauchquarz": "Hellgrau, gelb, braun oder blau",
    "Rosenquarz": "Rauchig rosa mit weissem Stern in der Mitte",
    "Zirkon": "Klar, blasses Aqua",
    "Bernstein": "Transparent goldgelb",
    "Alexandrit": "Dunkelgruen",
    "Amethyst": "Violetter Kristall",
    "Chrysoberyll": "Gruen oder gelbgruen",
    "Koralle": "Rosa bis karmesinrot",
    "Granat": "Tiefrot bis violetter Kristall",
    "Jade": "Hell- bis dunkelgruen oder weiss",
    "Jet": "Tiefschwarz",
    "Perle": "Reinweiss, rosa bis schwarz",
    "Aquamarin": "Blassblaugruen",
    "Peridot": "Olivgruen",
    "Spinell": "Rot, rotbraun, gruen oder tiefblau",
    "Topas": "Goldgelb",
    "Turmalin": "Blassgruen, blau, braun oder rot",
    "Opal": "Blassblau mit gruen-goldener Marmorierung",
    "Orient. Amethyst": "Tiefviolett",
    "Orient. Topas": "Feurig gelb",
    "Saphir": "Klar bis mittelblau",
    "Schwarzer Opal": "Dunkelgruen mit schwarzer Marmorierung",
    "Schwarzer Saphir": "Satt schwarz mit Lichtpunkten",
    "Diamant": "Klar blauweiss, hellblau, gelb oder rosa",
    "Smaragd": "Leuchtend gruen",
    "Jacinth": "Feurig orange",
    "Orient. Smaragd": "Leuchtend gruen",
    "Rubin": "Klar bis tief karmesinrot",
    "Sternrubin": "Durchscheinend rubinrot mit weissem Sternlicht",
    "Sternsaphir": "Durchscheinend blau mit weissem Sternlicht",
}


def slugify(name: str) -> str:
    """Konvertiert Item-Name zu Dateiname-Slug."""
    s = name.lower()
    s = s.replace("+", "plus")
    s = s.replace("'s", "s")
    s = s.replace("'s", "s")
    s = s.replace("/", "_")
    s = s.replace("&", "and")
    s = s.replace(",", "")
    s = s.replace(".", "")
    s = s.replace(":", "")
    s = s.replace("(", "").replace(")", "")
    s = s.replace("-", "_")
    s = re.sub(r"[^a-z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_")


def detect_type_tag(category: str) -> str:
    """Leitet einen kurzen Typ-Tag aus der Kategorie ab."""
    mapping = {
        "Potions and Oils": "potion", "Scrolls": "scroll", "Rings": "ring",
        "Rods": "rod", "Staves": "staff", "Wands": "wand",
        "Books and Tomes": "book", "Jewels and Jewelry": "amulet",
        "Cloaks and Robes": "cloak", "Boots and Gloves": "boots",
        "Girdles and Helms": "helm", "Bags and Bottles": "bag",
        "Dusts and Stones": "dust", "Household Items and Tools": "misc",
        "Musical Instruments": "instrument", "The Weird Stuff": "misc",
        "Armor and Shields": "armor", "Weapons": "weapon",
    }
    return mapping.get(category, "misc")


def generate_magic_item(name: str, category: str, out_dir: str) -> str:
    """Generiert ein Magic-Item-Snippet und gibt den Dateipfad zurueck."""
    slug = slugify(name)
    item_id = f"item_{slug}"
    type_tag = detect_type_tag(category)
    table_num = TABLE_NUMBERS.get(category, "88")

    mech = KNOWN_MECHANICS.get(name, {})
    mechanics_data = {
        "type": type_tag,
        "usable_by": mech.get("usable_by", "all"),
        "effect": mech.get("effect", f"Siehe DMG fuer Details"),
        "weight_lbs": mech.get("weight", 1),
        "value_gp": mech.get("value_gp", 1000),
        "xp_value": mech.get("xp_value", 500),
    }
    if "charges" in mech:
        mechanics_data["charges"] = mech["charges"]

    data = {
        "schema_version": "1.0.0",
        "id": item_id,
        "name": name,
        "category": "magic_item",
        "subcategory": category,
        "tags": ["add_2e", "magic_item", type_tag, "dmg"],
        "source": {
            "book": "Dungeon Master's Guide (2nd Edition)",
            "table": f"Table {table_num}: {category}",
        },
        "mechanics": mechanics_data,
        "description": mech.get("effect", f"Ein magischer Gegenstand der Kategorie {category}. Siehe DMG fuer vollstaendige Beschreibung."),
        "keeper_notes": f"Kann in Schaetzen gefunden werden (DMG Table 88 → {category}).",
    }

    fpath = os.path.join(out_dir, f"{slug}.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return fpath


def generate_gem(name: str, tier: str, base_value: int, out_dir: str) -> str:
    """Generiert ein Edelstein-Snippet."""
    slug = slugify(name)
    item_id = f"gem_{slug}"
    appearance = GEM_DESCRIPTIONS.get(name, "Keine Beschreibung verfuegbar")

    data = {
        "schema_version": "1.0.0",
        "id": item_id,
        "name": name,
        "category": "gem",
        "subcategory": tier,
        "tags": ["add_2e", "gem", "treasure", "dmg"],
        "source": {
            "book": "Dungeon Master's Guide (2nd Edition)",
            "table": "Table 85: Gem Base Value",
        },
        "mechanics": {
            "base_value_gp": base_value,
            "tier": tier,
            "appearance": appearance,
        },
        "description": f"{appearance}. Basiswert: {base_value} GP ({tier}).",
    }

    fpath = os.path.join(out_dir, f"gem_{slug}.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return fpath


def main():
    base = os.path.join("data", "lore", "add_2e", "items")
    counts = {}
    total = 0

    # ── Magische Gegenstaende ────────────────────────────────────────
    for category, items in MechanicsEngine._MAGIC_ITEM_SUBTABLES.items():
        dir_name = CATEGORY_DIRS.get(category, "misc")
        out_dir = os.path.join(base, dir_name)
        os.makedirs(out_dir, exist_ok=True)

        count = 0
        for item_name in items:
            generate_magic_item(item_name, category, out_dir)
            count += 1
        counts[category] = count
        total += count

    # ── Edelsteine ───────────────────────────────────────────────────
    gem_dir = os.path.join(base, "gems")
    os.makedirs(gem_dir, exist_ok=True)
    gem_count = 0
    for _, base_value, tier, examples in MechanicsEngine._GEM_VALUE_TABLE:
        for gem_name in examples:
            generate_gem(gem_name, tier, base_value, gem_dir)
            gem_count += 1
    counts["Gems"] = gem_count
    total += gem_count

    # ── Zusammenfassung ──────────────────────────────────────────────
    print("=" * 60)
    print("ITEM-SNIPPET-GENERATOR — Ergebnis")
    print("=" * 60)
    for cat, n in counts.items():
        print(f"  {cat:35s} {n:4d} Dateien")
    print("-" * 60)
    print(f"  {'GESAMT':35s} {total:4d} Dateien")
    print(f"\nAusgabe: {os.path.abspath(base)}")


if __name__ == "__main__":
    main()
