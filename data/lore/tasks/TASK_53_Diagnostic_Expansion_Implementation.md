# TASK 53: Tech-GUI Erweiterung (Programmierung)
**Akteur:** Claude Code | **Abhaengigkeit:** TASK 06.

## Anweisungen
1. Erweitere `scripts/tech_gui.py` um zwei neue Tabs: "Story & State" und "Memory Engine".
2. **Story & State:**
   - Implementiere eine `refresh_locations()` Methode, die Raeume aus dem geladenen Szenario liest.
   - Baue ein `ttk.Treeview`, um die SQLite-Tabelle `world_state` live anzuzeigen und per Doppelklick zu editieren.
3. **Memory Engine:**
   - Binde den `Archivist` aus `core/memory.py` an.
   - Erstelle ein Text-Area, das den aktuellen `get_context_for_prompt()` Output in Echtzeit anzeigt.
4. **Logic-Bridge:**
   - Stelle sicher, dass Aenderungen in der GUI (z.B. Ortswechsel) sofort die `SimulatorEngine` im Hintergrund aktualisieren.
