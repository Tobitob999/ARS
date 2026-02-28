# TASK 50: Diagnostic Center Konzept

## Ziel
Entwicklung einer technischen Steuerzentrale zur Hardware-Kalibrierung und Engine-Ueberwachung.

## Funktionsmodule
1. **Audio-Panel:**
   - Dropdown fuer Input-Geraete (Mikrofone).
   - Dropdown fuer Output-Geraete (Speaker).
   - "Mic Check"-Button: 3 Sek. Aufnahme mit sofortiger Wiedergabe.
   - Live-Pegelanzeige (VAD-Level).
2. **AI-Backend-Panel:**
   - Anzeige des aktuellen API-Status (Gemini).
   - Token-Counter der aktuellen Session.
   - Manuelle Prompt-Eingabe zum Testen der Keeper-Persoenlichkeit.
3. **Engine-State:**
   - Rohdaten-Ansicht der geladenen `Character`- und `World`-Flags.
   - Button zum manuellen Ausloesen von Wuerfelproben (Test der `mechanics.py`).

## Tech-Stack
- **Framework:** CustomTkinter (fuer konsistente UI).
- **Dateipfad:** `scripts/tech_gui.py` (Zentrales Test-Script).
