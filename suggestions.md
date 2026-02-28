# ARS — Strategic Hub (suggestions.md)

**Strategische Ebene — Langfristige Planung & Lore-Aufbau**
**Nächstes Strategie-Review:** 2026-03-01 (Intervall: alle 3 Tage)

---

## 🗺 1. Strategische Roadmap (Weitblick)
*Große Meilensteine, die über die aktuellen Bugfixes hinausgehen.*

| Phase | Fokus | Zielsetzung |
|:---|:---|:---|
| **Phase A** | Dynamik-Finish | Stabiles Whisper `small` & Latenz < 1s. |
| **Phase B** | Immersive UX | Grafische Würfel, Sound-Effekt Trigger (Ambience). |
| **Phase C** | Charakter-Gen | Geführte Voice-Erstellung mit Regel-Validierung. |
| **Phase D** | Long-Term Memory | Veredelung des Archivists für kampagnenübergreifendes Wissen. |

---

## 🏛 2. Lore & Data Vault (Background-Tasks)
*Agenten sind ermutigt, hier Entwürfe für die Spielwelt zu deponieren. Freigabe erfolgt im Review.*

### Personen (NPCs)
- [ ] *Idee:* Ein zwielichtiger Antiquitätenhändler für Arkham (Bezug: Spukhaus).

### Gebäude & Orte
- [ ] *Idee:* Grundrisse und Beschreibungen für die Miskatonic University Bibliothek.

### Gegenstände & Artefakte
- [ ] *Idee:* Generische CoC-Ausrüstungsliste (Taschenlampe, Erste-Hilfe-Set) in JSON-Format.

---

## 💡 3. Feature-Brainstorming (Ideen-Pool)
*Hier alles sammeln, was später in das operative Backlog (agents.md) wandern könnte.*

- **Adaptive Musik:** Der Orchestrator sendet Stimmungs-Tags an die GUI, die Spotify oder lokale MP3s steuert.
- **Auto-Chronik:** Nach jeder Session wird automatisch ein PDF-Tagebuch der Erlebnisse generiert.
- **Multilingual-Support:** Testen, ob Kokoro auch Englisch/Deutsch-Mix sauber ausgibt (für Zitate).

---

## 📓 4. Strategie-Log & Diskussion
*Format: [YYYY-MM-DD HH:MM] | FROM: [Agent] | [Beitrag]*

[2026-02-26 23:35] | FROM: Gemini | Strategische Struktur erstellt. Lore-Sektion für Hintergrund-Tasks (Menschen, Orte, Items) initialisiert.
[2026-02-27 12:00] | FROM: Claude Code | Phase A Teilschritt: Piper TTS integriert, --no-barge-in Flag, Barge-in Bugfixes (Cooldown/Threshold/Consecutive), Kokoro-Retry-Bug, .env konfigurierbar (WHISPER_MODEL, PIPER_VOICE). Whisper small jetzt per .env umschaltbar.
[2026-02-27 13:00] | FROM: Claude Code | TASK 50/51 abgeschlossen: Diagnostic Center (scripts/tech_gui.py) mit 3 Tabs — Audio-Panel (Device-Auswahl, Mic Check, Live-VAD-Pegel, TTS-Test, .env-Export), AI-Backend (API-Status, Token-Counter, Prompt-Test), Engine-State (Character-Daten, Skill-Check, Wuerfelausdruecke).
[2026-02-27 14:30] | FROM: Claude Code | TASK 06 + 52/53: Adventure Engine (core/adventure_manager.py) + Schema + Location-Tracking + Flag-System. Orchestrator: /orte, /teleport, /flags. spukhaus.json: 14 Flags. Diagnostic Center: 5 Tabs (+ Story & State, + Memory Engine).