# TASK 52: Tech-GUI Erweiterung (Konzept)
**Status:** Geplant | **Typ:** Technische GUI (Diagnostic Center).

## Ziel
Manuelle Manipulation des Spielzustands zum Testen von Edge-Cases (z.B. "Was passiert, wenn Flag X gesetzt ist?").

## Neue Module (Tabs)
1. **Tab: Scenario & World**
   - Szenario-Waehler: Dropdown aller JSON-Dateien in `/modules/adventures/`.
   - Location-Teleport: Dropdown aller Raeume im geladenen Szenario.
   - Flag-Editor: Liste aller World-Flags mit Toggle (True/False) oder Value-Edit.
2. **Tab: Memory & Archivist**
   - Raw-Memory-View: Anzeige der letzten 10 Turns im Klartext.
   - Summary-Trigger: Button zum manuellen Ausloesen der Zusammenfassung durch den Archivist.
   - Context-Preview: Anzeige des finalen Strings, der an Gemini gesendet wird.
