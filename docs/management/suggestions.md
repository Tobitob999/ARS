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
| **Phase E** | ADD2e Lore-Vollextraktion | Alle 108 PDFs aus ADD2e/ vollstaendig in data/lore/add_2e/ integriert. KI-Keeper hat Vollzugriff auf Klassen, Kits, Rassen, Zauber, Artefakte, DM-Werkzeuge, Dragonlance-Setting. |

---

## 📚 2. ADD2e Langzeit-Konvertierungsprojekt (Strategischer Kontext)

**Initiiert:** 2026-03-04 | **Status:** Planung abgeschlossen, Batch B-C01 ausstehend

### Ausgangslage
- 108 PDFs (alle als `_text.pdf` OCR-Variante oder Scan vorhanden) in `G:\Meine Ablage\ARS\ADD2e\`
- Bisherige Extraktion: nur Monstrous Compendium Vol.1 → 106 Monster-JSONs
- Das restliche AD&D-2e-Regelwerk ist der KI unbekannt: Klassen, Kits, Rassen, Artefakte, Goetterpantheons, Dragonlance-Lore sind nicht im Kontext

### Ziel
Vollstaendige Lore-Abdeckung des AD&D-2e-Universums fuer den KI-Keeper:
- **21 PHBR-Handbooks + Player's Options + Legends + Tome:** Klassen, Kits, Rassen, Kampfoptionen → direkte Spielqualitaetssteigerung (Keeper kann Kits, Spezialfaehigkeiten und Pantheons korrekt beschreiben)
- **Monster Compendiums (10 Buecher):** +600-800 Monster → massiv mehr Encounter-Vielfalt
- **Spell Compendiums (7 Buecher) + Encyclopedia Magica (4 Bde):** vollstaendige Zauber- und Artefakt-Datenbank
- **DM-Guides (9 Buecher):** Kampagnen-Design, Weltenbau, Encounter-Tabellen
- **Dragonlance (44 Buecher):** vollstaendiges Setting fuer Dragonlance-Kampagnen
- **Historical Reference (7 Buecher):** Historische Settings (Wikinger, Kelten, Rom, Kreuzzuege)

### Auswirkung auf Spielqualitaet
| Kategorie | Vor Extraktion | Nach Extraktion |
|-----------|----------------|-----------------|
| Klassen/Kits | Fighter/Thief/etc. nur Grundklassen | 120+ Kits, Psionik, Barbar, Ninja |
| Monster | 106 | ~900+ |
| Zauber | 331 (Grundliste) | ~2000+ (Vollkompendium) |
| Artefakte | 0 | ~400+ (Encyclopedia Magica 4 Bde) |
| Goetter/Pantheons | 0 | ~200+ (Legends and Lore + DMGR4) |
| Settings | Forgotten Realms (basic) | + Dragonlance (vollstaendig) |

### Empfehlung zur Priorisierung
Batch B-C01 (PHBR01-10) als naechstes ausfuehren — groesster unmittelbarer Impact auf Spieler-Experience.
Danach B-C02 fuer restliche PHBR + Player's Options. Erst dann Monster/Spell Compendiums (P2).

### Technische Voraussetzung
- OCR-Varianten (`_text.pdf`) direkt verwertbar
- Neue Unterordner benoetigt: `classes/`, `kits/`, `races/`, `deities/`, `magic_items/`, `magic_items/artifacts/`, `dm_tools/`, `rules/player_options/`, `rules/high_level/`, `settings/dragonlance/`, `settings/historical/`, `spells/wizard/`, `spells/priest/`
- Bestehende `spells/` und `equipment/` ggf. reorganisieren (Unterordner) wenn Volumen es erfordert

---

## 🏛 3. Lore & Data Vault (Background-Tasks)
*Agenten sind ermutigt, hier Entwürfe für die Spielwelt zu deponieren. Freigabe erfolgt im Review.*

### Personen (NPCs)
- [ ] *Idee:* Ein zwielichtiger Antiquitätenhändler für Arkham (Bezug: Spukhaus).

### Gebäude & Orte
- [ ] *Idee:* Grundrisse und Beschreibungen für die Miskatonic University Bibliothek.

### Gegenstände & Artefakte
- [ ] *Idee:* Generische CoC-Ausrüstungsliste (Taschenlampe, Erste-Hilfe-Set) in JSON-Format.

---

## 💡 4. Feature-Brainstorming (Ideen-Pool)
*Hier alles sammeln, was später in das operative Backlog ([agents.md](agents.md)) wandern könnte.*

- **Adaptive Musik:** Der Orchestrator sendet Stimmungs-Tags an die GUI, die Spotify oder lokale MP3s steuert.
- **Auto-Chronik:** Nach jeder Session wird automatisch ein PDF-Tagebuch der Erlebnisse generiert.
- **Multilingual-Support:** Testen, ob Kokoro auch Englisch/Deutsch-Mix sauber ausgibt (für Zitate).
- **Grid-Items:** Truhen/Loot als sichtbare Entities auf dem Grid platzieren. Renderer hat `chest_img` bereits geladen. Neuer Entity-Typ `"item"`, Map-Spawns fuer Items, Interaktion bei Kontakt (→ `[INVENTAR: +Item]`). ~50Z Code + JSON-Eintraege in Crawl-Adventures.

---

## 📓 5. Strategie-Log & Diskussion
*Format: [YYYY-MM-DD HH:MM] | FROM: [Agent] | [Beitrag]*

[2026-02-26 23:35] | FROM: Gemini | Strategische Struktur erstellt. Lore-Sektion für Hintergrund-Tasks (Menschen, Orte, Items) initialisiert.
[2026-02-27 12:00] | FROM: Claude Code | Phase A Teilschritt: Piper TTS integriert, --no-barge-in Flag, Barge-in Bugfixes (Cooldown/Threshold/Consecutive), Kokoro-Retry-Bug, .env konfigurierbar (WHISPER_MODEL, PIPER_VOICE). Whisper small jetzt per .env umschaltbar.
[2026-02-27 13:00] | FROM: Claude Code | TASK 50/51 abgeschlossen: Diagnostic Center (scripts/tech_gui.py) mit 3 Tabs — Audio-Panel (Device-Auswahl, Mic Check, Live-VAD-Pegel, TTS-Test, .env-Export), AI-Backend (API-Status, Token-Counter, Prompt-Test), Engine-State (Character-Daten, Skill-Check, Wuerfelausdruecke).
[2026-02-27 14:30] | FROM: Claude Code | TASK 06 + 52/53: Adventure Engine (core/adventure_manager.py) + Schema + Location-Tracking + Flag-System. Orchestrator: /orte, /teleport, /flags. spukhaus.json: 14 Flags. Diagnostic Center: 5 Tabs (+ Story & State, + Memory Engine).