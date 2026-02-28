# TASK 51: Diagnostic Center Programmierung

**Akteur:** Claude Code

## Anweisungen
1. Erstelle `scripts/tech_gui.py`.
2. **Audio-Initialisierung:**
   - Nutze `sounddevice`, um verfuegbare Geraete aufzulisten.
   - Implementiere zwei Dropdowns zur Auswahl von `input_device` und `output_device`.
   - Fuege Buttons hinzu, die kurze Testtoene ueber das gewaehlte Geraet abspielen oder eine Testaufnahme triggern.
3. **Engine-Link:**
   - Importiere `SimulatorEngine` aus `core/engine.py`.
   - Erstelle ein Fenster, das die aktuellen `self.character.stats` in einer Tabelle anzeigt.
4. **Integration:**
   - Die gewaehlten Hardware-IDs muessen optional in die `.env` geschrieben werden koennen, damit `main.py` diese uebernimmt.

## Struktur-Regeln
- Code-Kommentare: Knapp und funktional.
- Keine GUI-Elemente im Spiel-Dashboard aendern.
- Log-Ausgabe parallel im TUI-Fenster behalten.
