# Aktueller Projektstand: ARS

**Datum:** 2026-02-25

## 1. Zusammenfassung (Executive Summary)

Das Projekt hat einen entscheidenden Meilenstein erreicht: Die Kern-Entwicklung (Tasks 01-09) ist abgeschlossen. Das System ist technisch vollständig, inklusive des KI-Backends, der Charakter-Verwaltung, des Abenteuer-Moduls "Das Spukhaus" und der GUI "The Investigator's Desk".

Nach dem ersten vollständigen Testlauf wurden kritische Fehler in der Audio-Pipeline und der GUI-Interaktion identifiziert. Diese Fehler wurden analysiert, und es wurde ein detaillierter Bug-Fix-Report erstellt, der **inzwischen vollständig abgearbeitet wurde.**

**Kurz gesagt: Das System ist jetzt stabil und bereit für einen erneuten, umfassenden Testlauf.**

---

## 2. Letzter Sprint: Bug-Fixing nach dem ersten Test

Der letzte große Schritt war die Behebung der Fehler, die beim ersten Start mit der GUI (`--gui --voice`) aufgetreten sind. Hier ist eine Übersicht der behobenen Probleme:

### Fix 1 — KRITISCH: Kokoro-TTS-Modell nicht gefunden (404-Fehler)
*   **Problem:** Die Sprachausgabe klang schlecht, weil das hochwertige Kokoro-Modell nicht von HuggingFace geladen werden konnte (der Link war veraltet). Das System nutzte eine minderwertige Fallback-Stimme (`pyttsx3`).
*   **Fix:** Der Download-Pfad wurde auf eine stabile Version auf GitHub aktualisiert. Das Modell wird jetzt beim ersten Start korrekt heruntergeladen und lokal in `data/models/` gespeichert, um zukünftige Downloads zu vermeiden.

### Fix 2 — KRITISCH: Mikrofon hat nicht funktioniert
*   **Problem:** Im GUI-Modus wurde die Spracheingabe (STT) übersprungen, weshalb das Spiel nicht auf Sprache reagierte und die Session mit "0 Züge gespielt" beendet wurde.
*   **Fix:** Die Logik in `core/orchestrator.py` (`_get_input`) wurde überarbeitet. Für den Modus `--gui --voice` startet nun ein separater Daemon-Thread, der permanent auf Spracheingaben lauscht. Die Texteingabe in der GUI funktioniert parallel als Fallback.

### Fix 3 — MITTEL: Intro-Text wurde vorgelesen
*   **Problem:** Der technische Start-Text und die Einleitung des Abenteuers wurden von der TTS gesprochen, was die Atmosphäre störte.
*   **Fix:** Der Orchestrator (`_gm_print`) wurde so angepasst, dass der Intro-Text nur noch im Textfeld der GUI angezeigt, aber nicht mehr an die Sprachausgabe gesendet wird.

### Fix 4 — NIEDRIG: Unnötige "Context Cache"-Fehler
*   **Problem:** Die Logs wurden mit `400 INVALID_ARGUMENT`-Fehlern überflutet, weil das System versuchte, zu kurze Prompts zu cachen.
*   **Fix:** In `core/ai_backend.py` wurde eine Prüfung (`_CACHE_MIN_CHARS`) eingebaut, die den Caching-Versuch überspringt, wenn der Prompt zu kurz ist. Die Log-Meldungen wurden auf ein niedrigeres Level (Debug) gesetzt.

### Fix 5 — GUI-Verbesserung: VAD-Statusanzeige
*   **Problem:** Die visuelle Anzeige für das Mikrofon hatte nur zwei Zustände, was unklares Feedback gab.
*   **Fix:** Die Anzeige wurde auf drei Zustände erweitert, um klareres Feedback zu geben:
    *   **Grau:** Stille / Inaktiv
    *   **Grün:** System hört zu (wartet auf Spieler-Input)
    *   **Rot:** Der Keeper spricht gerade (LLM generiert + TTS läuft)

---

## 3. Nächster Schritt: Verifikationstest

Der nächste logische Schritt ist, das Spiel erneut zu starten, um die Bug-Fixes zu verifizieren und das gesamte Spielerlebnis von Anfang bis Ende zu testen.

**Start-Befehl:**
```bash
py -3 main.py --module cthulhu_7e --adventure spukhaus --gui --voice
```

**Zu beachten:** Beim ersten Start nach den Fixes wird das System einmalig das ca. 310 MB große Kokoro-TTS-Modell von GitHub herunterladen und in `data/models/` speichern. Danach sollte die Audio-Pipeline stabil und mit hoher Qualität laufen.