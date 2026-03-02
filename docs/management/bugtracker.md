# ARS Bugtracker

Quelle: 4-System Virtual Player Test (Session 6, 2026-03-02)

| ID | Severity | System | Status | Description |
|----|----------|--------|--------|-------------|
| BUG-001 | HIGH | Cthulhu 7e | FIXED | Keine PROBE-Tags generiert. Fix: Investigativ-Proben-Protokoll als `combat_note` Block in Cthulhu-Branch eingefuegt. Verifiziert: 2 Proben in 5 Zuegen. |
| BUG-002 | HIGH | Shadowrun 6 | FIXED | PROBE-Zielwerte 50-70 statt 1-30. Fix: PROBE-Protokoll check_mode-aware, Shadowrun `combat_note` mit Pool-Berechnung + "NIEMALS d100-Werte", System-Grenzen-Block. Alias-Detection erkennt Cross-System Kontamination. |
| BUG-003 | HIGH | Alle | FIXED | Monolog-Sperre ignoriert. Fix: `_pending_feedback` Liste, STIL-KORREKTUR in naechsten Turn injiziert, Prompt verschaerft ("ABSOLUTES LIMIT"). Feedback-Loop aktiv in allen 4 Systemen. KI braucht 2-3 Turns zum Anpassen. |
| BUG-004 | MED | Shadowrun 6 | FIXED | Skill-Mismatch. Fix: `SKILL_ALIASES` Dict in `rules_engine.py` (pro System), `resolve_skill_alias()` Methode, Alias-Resolution in `orchestrator._handle_probe()`, System-Grenzen-Block im Prompt. Verifiziert: Alias-Detection feuert bei "Bibliotheksnutzung" in Shadowrun. |
| BUG-005 | MED | AD&D 2e | FIXED | Skill-Mismatch: "Geschichte" (Cthulhu-Skill) in AD&D. Fix: System-Grenzen-Block mit VERBOTEN-Liste, `SKILL_ALIASES` mit leeren Mappings fuer ungueltige Skills. Verifiziert: Keine Cross-System Skills in AD&D-Test. |
| BUG-006 | LOW | Alle | WONTFIX | Barge-in False Positives bei Lautsprecherbetrieb. Hardware-Problem (akustisches Echo). Workaround: `--no-barge-in` Flag. |
| BUG-007 | MEDIUM | Shadowrun 6 | OPEN | Shadowrun emittiert Cthulhu-spezifische Sanity-Tags (STABILITAET_VERLUST). System-Boundary-Block in `core/ai_backend.py` vorhanden aber nicht vollstaendig wirksam. KI ignoriert Grenz-Protokoll im ersten Turn, Alias-System erkennt es erst nachtraeglich. |
| BUG-008 | LOW | Core | OPEN | `advertiser_chronology.md` liegt im Verzeichnis `core/` — Nicht-Code-Markdown in Source-Verzeichnis. Datei gehoert nach `data/lore/` oder soll entfernt werden. Kein funktionaler Defekt, verletzt aber Ablage-Konvention (§ core/ = Python only). |

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
