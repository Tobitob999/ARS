# ARS Bugtracker

Quelle: 4-System Virtual Player Test (Session 6, 2026-03-02)

| ID | Severity | System | Status | Description |
|----|----------|--------|--------|-------------|
| BUG-001 | HIGH | Paranoia 2e | ROOT CAUSE FIXED | Keine PROBE-Tags generiert (urspruengliche Diagnose: Cthulhu 7e). Root Cause Session 9: Shared mutable state zwischen AdventureManager und ai_backend's Lore-Merger. Fix: Deep-Copy + Type Guards in `adventure_manager.py` + `memory.py`. Commit 324e4f2. |
| BUG-002 | HIGH | Shadowrun 6 | FIXED | PROBE-Zielwerte 50-70 statt 1-30. Fix: PROBE-Protokoll check_mode-aware, Shadowrun `combat_note` mit Pool-Berechnung + "NIEMALS d100-Werte", System-Grenzen-Block. Alias-Detection erkennt Cross-System Kontamination. |
| BUG-003 | HIGH | Alle | FIXED | Monolog-Sperre ignoriert. Fix: `_pending_feedback` Liste, STIL-KORREKTUR in naechsten Turn injiziert, Prompt verschaerft ("ABSOLUTES LIMIT"). Feedback-Loop aktiv in allen 4 Systemen. KI braucht 2-3 Turns zum Anpassen. |
| BUG-004 | MED | Shadowrun 6 | FIXED | Skill-Mismatch. Fix: `SKILL_ALIASES` Dict in `rules_engine.py` (pro System), `resolve_skill_alias()` Methode, Alias-Resolution in `orchestrator._handle_probe()`, System-Grenzen-Block im Prompt. Verifiziert: Alias-Detection feuert bei "Bibliotheksnutzung" in Shadowrun. |
| BUG-005 | MED | AD&D 2e | FIXED | Skill-Mismatch: "Geschichte" (Cthulhu-Skill) in AD&D. Fix: System-Grenzen-Block mit VERBOTEN-Liste, `SKILL_ALIASES` mit leeren Mappings fuer ungueltige Skills. Verifiziert: Keine Cross-System Skills in AD&D-Test. |
| BUG-006 | LOW | Alle | WONTFIX | Barge-in False Positives bei Lautsprecherbetrieb. Hardware-Problem (akustisches Echo). Workaround: `--no-barge-in` Flag. |
| BUG-007 | MEDIUM | Shadowrun 6 | FIXED | Shadowrun emittierte Cthulhu-spezifische Sanity-Tags (STABILITAET_VERLUST). Fix Session 9: STABILITAET_VERLUST / SANITY_CHECK / SAN_LOSS-Tags werden in `core/rules_engine.py` fuer Non-Cthulhu-Systeme hart geblockt. Commit e0a4f4f. |
| BUG-008 | LOW | Core | OPEN | `advertiser_chronology.md` liegt im Verzeichnis `core/` — Nicht-Code-Markdown in Source-Verzeichnis. Datei gehoert nach `data/lore/` oder soll entfernt werden. Kein funktionaler Defekt, verletzt aber Ablage-Konvention (§ core/ = Python only). |
| BUG-009 | CRITICAL | All Systems | FIXED | Preset-Adventure Passthrough: _set_combo() in gui/tab_session.py schlaegt still fehl wenn Preset-Adventure nicht im Dropdown steht. Setzt auf "(keine)" zurueck. Fix: Wert wird jetzt in Dropdown eingefuegt wenn nicht vorhanden. |
| BUG-010 | HIGH | All Systems (Kampf) | MITIGATED | Monster-HP_VERLUST fehlt: KI emittiert keine [HP_VERLUST]-Tags fuer Monster-Gegenangriffe trotz expliziter Prompt-Anweisung. Kaempfe risikolos. Fix: (1) Prompt-Verstaerkung am Ende des System-Prompts (KAMPF-ERINNERUNG Block), (2) Post-Validation Warning in _validate_response() wenn Kampfwoerter ohne HP_VERLUST-Tag. Status MITIGATED weil Prompt-Compliance nicht 100% garantiert. |
| BUG-011 | HIGH | All Systems | OPEN | Context-Saettigung ab ~80 Zuegen: KI-Antworten werden repetitiv bei langen Sessions. Erfordert History-Truncation oder Zusammenfassungs-Mechanismus. Design-Konzept noch offen. |
| BUG-012 | HIGH | AD&D 2e | FIXED | validate_tags() crashte bei 3+-Tupel stat_changes (MORAL_CHECK). Ursache: `for change_type, value_str in stat_changes` erwartet 2 Werte, MORAL_CHECK gibt (check_type, dc, modifier). Fix Session 19b: Tupel-Unpacking auf stat_tuple[0], stat_tuple[1] mit len-Check in rules_engine.py und orchestrator.py. |

## Test-Ergebnisse (Session 7, Post-Fix)

| System | Turns | Proben | Cross-System Fehler | Avg Saetze | Status |
|--------|-------|--------|---------------------|------------|--------|
| Cthulhu 7e | 5 | 2 | 0 | 4.2 | OK |
| Shadowrun 6 | 5 | 1 | 1 (Turn 1, vor Feedback) | 4.6 | OK |
| AD&D 2e | 5 | 0 | 0 | 4.6 | OK |
| Paranoia 2e | 5 | 0 | 0 | 5.4 | OK |

**Anmerkungen:**
- Monolog-Sperre: Feedback-Loop funktioniert, aber KI braucht 2-3 Turns zum Anpassen. Durchschn. Saetze bei 4-5 statt 3 — deutliche Verbesserung gegenueber vorher (6-8).
- Shadowrun Turn 1: "Bibliotheksnutzung | 50" trotz Prompt-Verschaerfung — Alias-System erkennt und loggt den Fehler. Ab Turn 2 durch STIL-KORREKTUR korrigiert.
- AD&D/Paranoia: Keine Proben in 5 Zuegen — Virtual Player erzeugt generische Eingaben, kein gezielter Abenteuer-Kontext.

## Changelog

- 2026-03-02: Bugtracker erstellt nach Session 6 Virtual Player Test
- 2026-03-02: Bugs 1-5 gefixt, verifiziert mit 4-System Virtual Player Test
- 2026-03-02: BUG-007 (Shadowrun false STABILITAET_VERLUST) + BUG-008 (advertiser_chronology.md in core/) eroeffnet (QM-Session 9 Baseline)
- 2026-03-02: BUG-007 FIXED (Session 9 Round 1, Commit e0a4f4f) — Tag-Blocking in rules_engine.py
- 2026-03-02: BUG-001 ROOT CAUSE FIXED (Session 9 Round 3, Commit 324e4f2) — Deep-Copy + Type Guards in adventure_manager.py + memory.py
- 2026-03-03: BUG-009 (Preset-Adventure Passthrough) + BUG-010 (Monster-HP_VERLUST) + BUG-011 (Context-Saettigung) eroeffnet (Session 12, QM-Report)
- 2026-03-03: BUG-009 FIXED (Session 12) — _set_combo() fuegt fehlende Werte ins Dropdown ein (gui/tab_session.py)
- 2026-03-03: BUG-010 MITIGATED (Session 12) — KAMPF-ERINNERUNG Block im System-Prompt + Post-Validation Warning in _validate_response() (core/ai_backend.py)
- 2026-03-04: BUG-012 (validate_tags Tupel-Crash bei MORAL_CHECK) eroeffnet (Session 19b)
- 2026-03-04: BUG-012 FIXED (Session 19b) — Tupel-Unpacking mit len-Check in rules_engine.py + orchestrator.py
