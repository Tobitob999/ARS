# TASK 60 — Tech & Admin Batch (10 Tasks)

**Erstellt:** 2026-03-02
**Batch-Nr:** 60
**Agent:** Lead Developer (Claude Code)
**Status:** Abgeschlossen

---

## Uebersicht

10 zusammenhaengende technische und administrative Aufgaben aus Session 6.

---

## A. Regel-Updates

### A1 — rules.md erweitert
- §6: Keine Gegenfragen (Claude Code stellt keine Bestaetigungs-Rueckfragen)
- §7: Sekretariats-Protokoll (Claude Code uebertraegt Gemini-Outputs eigenstaendig)
- §8: Standard-Arbeitspaket = 10 Tasks pro Batch
- §6 (alt) umbenannt zu §9: Ablage-Erzwingung

### A2 — organization.md erweitert
- Lead Developer-Rolle erweitert um Sekretariats-Pflichten
- Kommunikationsregeln-Tabelle um Gegenfragen-Verbot, Gemini-Transfer, Standard-Batch ergaenzt

---

## B. Technische Tasks

### B1 — scripts/pdf_scanner.py (NEU)
- Rekursiver PDF-Scanner im Projektverzeichnis
- Erstellt `data/lore/pdf_queue.json` als Verarbeitungs-Queue fuer Codex
- Felder: path, size_mb, status, priority, detected_system, created_at
- Status-Werte: pending, in_progress, done, error
- CLI: `py -3 scripts/pdf_scanner.py [--dir PATH] [--reset]`

### B2 — gui/tab_conversion_monitor.py (NEU) + Integration in tech_gui.py
- Neuer Tab "PDF Conversion" in TechGUI
- Zeigt pdf_queue.json live (Auto-Refresh alle 5s)
- Tabelle: Dateiname, Groesse, System, Status, Prioritaet
- Controls: Refresh, Reset Queue, Open in Explorer
- Farbkodierung: pending=grau, in_progress=gelb, done=gruen, error=rot

### B3 — core/ai_backend.py: Prompt-Cache Optimierung
- Cache-Invalidierung nur bei tatsaechlicher Regelwerk-Aenderung
- `_rules_cache_hash`: MD5 des Regelwerk-Blocks — verhindert unnoetige Rebuilds
- Batch-Modus: Cache-TTL auf 4h erhoehen fuer Massenverarbeitung
- `clear_caches()` Methode fuer vollstaendigen Reset

### B4 — audio/stt_handler.py: Noise-Gate Filter
- RMS-basierter Noise-Gate vor VAD-Verarbeitung
- Konfigurierbarer Threshold via ENV: `NOISE_GATE_RMS=0.005`
- Chunks unterhalb Threshold werden direkt als Stille behandelt
- Reduziert False-Positives bei ruhiger Umgebung

### B5 — gui/tab_game.py: GUI Stat-Bars bidirektional
- HP/SAN/MP Balken reagieren auf SQLite-Aenderungen via EventBus
- Event `character.stat_changed` aktualisiert Balken sofort
- Kein Polling — rein event-getrieben
- Robustheit: Nicht-numerische Stats (z.B. Paranoia) zeigen Text statt Balken

### B6 — core/adventure_manager.py: Multi-Flag Story Trigger
- Flag-Bedingungen unterstuetzen logische Operatoren:
  - `{"AND": ["flag_a", "flag_b"]}` — alle muessen true sein
  - `{"OR": ["flag_a", "flag_b"]}` — mindestens einer muss true sein
  - `{"NOT": "flag_a"}` — Flag muss false/absent sein
  - `{"NOT": {"AND": [...]}}` — Kombination moeglich
- `evaluate_condition(condition)` Methode in AdventureManager
- Clue/Event requires_flag unterstuetzt jetzt komplexe Bedingungen

### B7 — main.py: CLI --convert-all Flag
- `--convert-all`: Startet PDF-Scanner, laedt Queue, signalisiert Codex
- Erstellt/aktualisiert `data/lore/pdf_queue.json`
- Gibt Queue-Statistik aus und beendet (kein Game-Loop)
- Optional: `--convert-dir PATH` fuer alternativen Scan-Pfad

### B8 — Latency Logger (STT→Gemini→TTS)
- `core/latency_logger.py` (NEU): Singleton-Logger
- Misst exakte Durchlaufzeit: STT-Ende → Gemini-Antwort-Start → TTS-Ende
- Schreibt nach `logs/latency.log` (CSV-Format: timestamp, stt_ms, gemini_ms, tts_ms, total_ms)
- Integration: orchestrator.py fuer Gemini-Teil, pipeline.py fuer STT/TTS
- EventBus-Event: `performance.latency` mit Metriken fuer GUI

### B9 — Session Reset Hardening
- Reset-Button loescht zusaetzlich:
  - `_lore_cache` im AI-Backend (Lore-Lade-Cache)
  - `_rules_cache_hash` im AI-Backend
  - `_metrics_log` im Orchestrator
  - TTS-Chunk-Buffer und Audio-Queue
  - CombatTracker-State und Initiative-Liste
  - TimeTracker-State (Tageszeit / Wetter)
  - Archivist In-Memory-Chronik (nicht SQLite)
- Confirmation-Dialog zeigt Liste der zu leerenden Caches

---

## C. Admin-Task

### TASK_61 erstellt
- Vollstaendige Aufgabenbeschreibung fuer Codex-Massenkonvertierung
- 12-Phasen-Pipeline-Referenz + Queue-Format + Abschluss-Protokoll

---

## Agent Report

`[2026-03-02] | FROM: Claude Code | TASK 60 vollstaendig abgeschlossen: rules.md + organization.md (§6-9), pdf_scanner.py, tab_conversion_monitor.py, ai_backend Cache-Hash, Noise-Gate (stt_handler), Stat-Bars EventBus, Multi-Flag evaluate_condition, --convert-all CLI, latency_logger.py, Session-Reset Hardening.`
