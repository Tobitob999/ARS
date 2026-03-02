# ARS — Organisationsstruktur

**Version:** 1.0
**Datum:** 2026-03-02
**Zweck:** Rollendefinition und Verantwortlichkeiten aller Agenten im ARS-Projekt.

---

## Organigramm

```
                    ┌─────────────────┐
                    │   Human Lead    │
                    │     (User)      │
                    │ Entscheidungen  │
                    │ Freigaben       │
                    └───────┬─────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
    ┌─────────▼──────┐ ┌────▼─────────┐ ┌─▼──────────────┐
    │ Strategic Lead │ │Lead Developer│ │Content Specialist│
    │   (Gemini)     │ │(Claude Code) │ │    (Codex)      │
    │ Keeper-KI      │ │ Engine, GUI  │ │ Lore, Module    │
    └─────────┬──────┘ └────┬─────────┘ └─┬──────────────┘
              │             │             │
              └─────────────┼─────────────┘
                            │
                   ┌────────▼────────┐
                   │ Virtual Player  │
                   │  (AI-Script)    │
                   │ Spieltest, QA   │
                   └─────────────────┘
```

---

## Rollendefinitionen

### Human Lead (User)

| Aspekt | Detail |
|--------|--------|
| **Rolle** | Projektleiter, Entscheider, Freigabeinstanz |
| **Verantwortung** | Strategische Richtung, Feature-Priorisierung, Qualitaetsabnahme, Budget-Entscheidungen |
| **Entscheidungen** | Welche Systeme integriert werden, wann deployed wird, Architektur-Grundsatzfragen |
| **Kommunikation** | Direktanweisungen an alle Agenten, Review von Agent Reports |

### Strategic Lead (Gemini)

| Aspekt | Detail |
|--------|--------|
| **Rolle** | Keeper-KI im Spiel, Regelwerk-Planung, Strategie |
| **Verantwortung** | In-Game Spielleitung (Gemini 2.5 Flash), Regelwerk-Konsistenz, Prompt-Architektur |
| **Staerken** | 1M Token Kontextfenster, Echtzeit-Spielleitung, Regelinterpretation |
| **Outputs** | Spieler-Antworten (in-game), Regelwerk-Feedback, Strategie-Empfehlungen |
| **Dokumente** | [suggestions.md](suggestions.md) (strategische Planung) |

### Lead Developer & Sekretaer (Claude Code)

| Aspekt | Detail |
|--------|--------|
| **Rolle** | Technische Implementierung, Code-Architektur, Debugging, **administratives Sekretariat** |
| **Verantwortung** | Python-Codebase (core/, gui/, audio/, scripts/), Modul-Integration, System-Tests, Bug-Fixes, **Dokumentations-Pflege** |
| **Staerken** | Code-Analyse, Multi-File-Refactoring, Shell-Zugriff, Build & Test, Dokumenten-Verwaltung |
| **Outputs** | Code-Commits, technische Dokumentation, Integrations-Tests, **Admin-Dokumente** |
| **Dokumente** | [agents.md](agents.md) (operatives Dashboard, Agent Reports) |
| **Sekretariats-Pflichten** | Gemini-Outputs in Dokumente uebertragen, Tasks dokumentieren, Berichte schreiben (ohne Rueckfrage) |
| **Arbeitspaket** | Standard: **10 zusammenhaengende Tasks** pro Batch, vollstaendig in einer Session |

### Content Specialist (Codex)

| Aspekt | Detail |
|--------|--------|
| **Rolle** | Buch-Konvertierung, Lore-Erstellung, JSON-Content |
| **Verantwortung** | RPG-Buecher in ARS-Format konvertieren (12-Phasen-Pipeline), Lore-Daten pflegen, Schema-Konformitaet |
| **Staerken** | Massenverarbeitung von Textdaten, Schema-konforme JSON-Generierung, Batch-Operationen |
| **Outputs** | Rulesets, Adventures, Lore-Chunks, Characters, Settings, Keepers |
| **Dokumente** | [WCR.md](WCR.md) (Schema-Spezifikation), [Book_ARS_Tool.md](Book_ARS_Tool.md) (Konvertierungs-Pipeline) |
| **Regeln** | Muss vor jeder Aktion [agents.md](agents.md) lesen, nach Abschluss Report schreiben |

### Virtual Player (AI-Script)

| Aspekt | Detail |
|--------|--------|
| **Rolle** | Automatisierter Spieltester, Qualitaetssicherung |
| **Verantwortung** | Spielsessions ausfuehren, Regelkonsistenz pruefen, Edge Cases finden |
| **Staerken** | Automatisierte Wiederholung, Konsistenz-Checks, Metriken-Erfassung |
| **Outputs** | Test-Reports, Bug-Meldungen, Regelwerk-Inkonsistenzen |
| **Status** | Geplant — noch nicht implementiert |

---

## Kommunikationsregeln

| Regel | Detail |
|-------|--------|
| **Zentrale Ablage** | Alle Management-Dokumente in `docs/management/` |
| **Lesepflicht** | Jeder Agent liest [agents.md](agents.md) vor jeder Aktion |
| **Berichtspflicht** | Nach Aufgabenabschluss Report in [agents.md](agents.md) unter "Agent Reports" |
| **Report-Format** | `[YYYY-MM-DD HH:MM] \| FROM: [Agent] \| [Status/Ergebnis]` |
| **Strategische Ideen** | In [suggestions.md](suggestions.md) deponieren, Review alle 3 Tage |
| **Schema-Fragen** | [WCR.md](WCR.md) ist die Referenz, [rules.md](rules.md) definiert Prozesse |
| **Keine Gegenfragen** | Claude Code stellt KEINE Bestaetigungs-Rueckfragen (siehe [rules.md](rules.md) §6) |
| **Gemini-Transfer** | Claude Code uebertraegt Gemini-Outputs/Entscheidungen eigenstaendig in Dokumente |
| **Standard-Batch** | 10 Tasks pro Arbeitspaket, vollstaendig abzuarbeiten ohne Unterbrechung |

---

## Dokumenten-Matrix

| Dokument | Zweck | Hauptverantwortlich |
|----------|-------|---------------------|
| [agents.md](agents.md) | Operatives Dashboard, Task-Tracking, Agent Reports | Lead Developer |
| [rules.md](rules.md) | Globale Agenten-Regeln, Kommunikations-Protokoll | Human Lead |
| [suggestions.md](suggestions.md) | Strategische Planung, Feature-Brainstorming, Lore-Ideen | Strategic Lead |
| [WCR.md](WCR.md) | World Creation Rules — JSON-Schema-Spezifikation | Content Specialist |
| [Book_ARS_Tool.md](Book_ARS_Tool.md) | Buch-Konvertierungs-Pipeline (12 Phasen) | Content Specialist |
| [organization.md](organization.md) | Dieses Dokument — Rollen & Verantwortlichkeiten | Human Lead |
