# TASK 06: Adventure Engine & Story Logic
**Status:** Konzept | **Ziel:** Strukturierte Welt-Daten.

## 1. Schema Definition (`modules/adventures/schema.json`)
- Definition von `locations` (ID, Description, Clues).
- Definition von `flags` (initial_state).

## 2. Adventure Manager (`core/adventure_manager.py`)
- Klasse zum Laden von JSON-Szenarien.
- `get_location(id)`: Liefert Lore-Strings fuer die KI.
- `update_world_state(key, value)`: Schreibt in die SQLite-DB.

## 3. Integration
- Kopplung an den `Orchestrator`, um den KI-Prompt dynamisch mit Ortsbeschreibungen zu fuettern.
