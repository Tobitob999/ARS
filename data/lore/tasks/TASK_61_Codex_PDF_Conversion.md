# TASK 61 — Codex: Massenkonvertierung aller verfuegbaren PDFs

**Erstellt:** 2026-03-02
**Batch-Nr:** 61
**Agent:** Content Specialist (Codex)
**Status:** Pending (Warte auf pdf_queue.json von Claude Code)
**Prioritaet:** HOCH

---

## Ziel

Vollstaendige und kompromisslose Konvertierung aller verfuegbaren RPG-PDFs in das ARS-Format.

---

## Voraussetzungen

- `data/lore/pdf_queue.json` muss von Claude Code generiert worden sein (TASK 60, B1/B7)
- Queue-Format:
  ```json
  {
    "generated_at": "...",
    "total": 12,
    "entries": [
      {
        "id": "pdf_001",
        "path": "g:/Meine Ablage/shadowrun/SR6E_Core.pdf",
        "filename": "SR6E_Core.pdf",
        "size_mb": 42.3,
        "status": "pending",
        "priority": 1,
        "detected_system": "shadowrun_6",
        "created_at": "2026-03-02T..."
      }
    ]
  }
  ```

---

## Prozess (pro PDF)

### Schritt 1: Queue lesen
- `data/lore/pdf_queue.json` lesen
- Eintraege mit `status: "pending"` und hoechster `priority` zuerst abarbeiten
- Eintrag auf `status: "in_progress"` setzen, bevor Konvertierung beginnt

### Schritt 2: 12-Phasen-Pipeline anwenden
Vollstaendige Pipeline aus [Book_ARS_Tool.md](Book_ARS_Tool.md):

1. **Phase 1:** Buch-Scan — Kapitelstruktur identifizieren
2. **Phase 2:** Regelwerk-Kern extrahieren (Attribute, Wuerfel, Werte)
3. **Phase 3:** Klassen / Archetypen / Rollen
4. **Phase 4:** Fertigkeiten / Skills
5. **Phase 5:** Ausruestung / Waffen / Geraet
6. **Phase 6:** Magie / Technologie / Spezial-Faehigkeiten
7. **Phase 7:** Kampf-System (Initiative, Angriff, Schaden, Wunden)
8. **Phase 8:** NPCs / Gegner / Kreaturen
9. **Phase 9:** Setting / Lore / Weltbeschreibung
10. **Phase 10:** Abenteuer-Hooks / Starter-Szenarien
11. **Phase 11:** Tabellen / Referenz-Daten
12. **Phase 12:** Qualitaets-Check (Schema-Validierung, Querverweise)

### Schritt 3: Outputs erstellen

**Ruleset:** `modules/rulesets/{system_id}.json`
- Pflichtfelder: metadata, dice_system, characteristics, skills
- Optional: classes, combat, magic, equipment, saving_throws, tables

**Lore-Dateien:** `data/lore/{system_id}/`
```
data/lore/{system_id}/
  npcs/           — Charaktere, NSCs, Begleiter
  locations/      — Orte, Regionen, Gebaeude
  items/          — Ausruestung, Waffen, Magie-Items
  organizations/  — Fraktionen, Gilden, Korporationen
  rules_chunks/   — Regelwerk-Auszuege (injizierbar)
  chapters/       — Kapitel-Zusammenfassungen
  monsters/       — Kreaturen, Gegner
  lore/           — Hintergrundgeschichte, Mythos
```

**Characters:** `modules/characters/{system_id}_{archetype}.json`
- Mindestens 3 repraesantative Charakter-Templates

**Adventures:** `modules/adventures/{system_id}_{name}.json`
- Mindestens 1 Starter-Abenteuer (4 Locations, 2 NPCs, 3 Clues, 5 Flags)

**Presets:** `modules/presets/{system_id}_classic.json`

### Schritt 4: Index aktualisieren

Nach Abschluss jedes Buches:
1. `modules/index.json` aktualisieren (neues Ruleset + Adventures eintragen)
2. `data/lore/pdf_queue.json`: Eintrag auf `status: "done"` setzen
3. Agent Report in `docs/management/agents.md` schreiben:
   ```
   [DATUM] | FROM: Codex | {Buchtitel} konvertiert: Ruleset, N Characters, N Adventures, N Lore-Dateien.
   ```

### Fehlerbehandlung

- Bei Parse-Fehler: `status: "error"` + `error_msg` im Queue-Eintrag
- Teilweise konvertierte Dateien NICHT loeschen — Fortschritt behalten
- Fehlende Kapitel: Leere Sektionen mit `"todo": true` markieren

---

## Prioritaets-Reihenfolge

1. Regelwerke mit vorhandenen Lore-Daten (ergaenzen statt neu erstellen)
2. Neue Regelsysteme (vollstaendiger Aufbau)
3. Ergaenzungs-Baende und Supplements

---

## Qualitaets-Kriterien

- [ ] Ruleset besteht Engine-Validierung (`py -3 main.py --module {id}`)
- [ ] Schema-Version gesetzt (`metadata.schema_version`)
- [ ] Mindestens 50 Lore-Chunks im `rules_chunks/` Verzeichnis
- [ ] Mindestens 1 spielbares Abenteuer
- [ ] Keine hartcodierten deutschen Texte in Schema-Feldern (Trennung Inhalt/Struktur)

---

## Verknuepfte Dokumente

- [Book_ARS_Tool.md](Book_ARS_Tool.md) — 12-Phasen-Pipeline (Referenz)
- [WCR.md](WCR.md) — JSON-Schema-Spezifikation
- [agents.md](agents.md) — Abschluss-Reports hier eintragen
- `data/lore/pdf_queue.json` — Verarbeitungs-Queue (von Claude Code generiert)
