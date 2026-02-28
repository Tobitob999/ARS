# ARS Tech-GUI — Entwicklungsplan

**Zweck:** Debugging- und Kontroll-GUI für die ARS-Engine-Entwicklung.
Keine Spieler-GUI — sondern ein Werkzeug für den Entwickler, um jeden Aspekt der Engine in Echtzeit zu beobachten, zu konfigurieren und zu testen.

**Framework:** Python `tkinter` (keine externe Dependency, sofort verfügbar)
**Einstieg:** `py -3 main.py --techgui [--voice] [--module ...] [--adventure ...]`

---

## Architektur-Übersicht

```
┌──────────────────────────────────────────────────────────────────────┐
│  TechGUI (Tkinter Toplevel)                                         │
│                                                                      │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐ │
│  │ Session  │ │  Audio  │ │ KI-      │ │ KI-      │ │  Spielstand │ │
│  │ Setup    │ │  Panel  │ │ Monitor  │ │ Connect  │ │  & Log      │ │
│  └─────────┘ └─────────┘ └──────────┘ └──────────┘ └─────────────┘ │
│       Tab 1      Tab 2       Tab 3        Tab 4         Tab 5       │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Status Bar: Engine-State │ Turn │ Char │ Location │ Tokens   │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
         │
         │  EventBus (Observer Pattern)
         ▼
┌──────────────────┐
│  SimulatorEngine  │  ← läuft in eigenem Thread
│  Orchestrator     │
│  GeminiBackend    │
│  VoicePipeline    │
└──────────────────┘
```

**Kernprinzip:** Die GUI hört dem EventBus zu und stellt dar. Sie greift nie direkt in den Engine-Thread ein — alle Befehle (Start, Stop, Save) laufen über thread-safe Queues.

---

## Voraussetzung: EventBus

Die Engine referenziert bereits `core.event_bus.EventBus`, die Datei existiert aber noch nicht. Sie muss zuerst implementiert werden.

```python
# core/event_bus.py — Singleton Observer
class EventBus:
    _instance = None

    @classmethod
    def get(cls) -> "EventBus":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}

    def on(self, event: str, callback: Callable):
        """Listener registrieren. Event-Format: 'category.event_name'"""
        self._listeners.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable):
        """Listener entfernen."""
        ...

    def emit(self, category: str, event_name: str, data: dict):
        """Event feuern. Ruft alle Listener für 'category.event_name' auf."""
        key = f"{category}.{event_name}"
        for cb in self._listeners.get(key, []):
            cb(data)
        # Wildcard: auch '*' Listener informieren
        for cb in self._listeners.get("*", []):
            cb({"event": key, **data})
```

---

## Tab 1: Session Setup

Konfiguration der Grundparameter **vor** dem Spielstart.

```
┌─ Session Setup ──────────────────────────────────────────────────┐
│                                                                   │
│  Regelwerk    [▼ cthulhu_7e    ]   ← DiscoveryService.scan()    │
│  Abenteuer    [▼ spukhaus      ]                                 │
│  Setting      [▼ cthulhu_1920  ]                                 │
│  Keeper       [▼ arkane_archivar]                                │
│  Character    [▼ coc_investigator]                               │
│  Party        [▼ (keine)       ]                                 │
│  Extras       [☑ noir_atmosphere] [☐ survival_mode]              │
│  Preset       [▼ coc_classic   ]  [Load Preset]                 │
│                                                                   │
│  ── Feineinstellungen ──────────────────────────────────────     │
│  Schwierigkeit   (●) Normal  (○) Easy  (○) Heroic  (○) Hardcore │
│  Atmosphäre      [ 1920s Cosmic Horror_________________ ]       │
│  Keeper-Persona  [ Mysterioes, detailverliebt__________ ]       │
│  Sprache         [▼ de-DE   ]                                    │
│  KI-Temperatur   [====●=====] 0.92                               │
│                                                                   │
│  ── Charakter-Übersicht (readonly, nach Load) ──────────────    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Name: Thomas Blackwood                                   │   │
│  │  Archetyp: Antiquarian    Stufe: Erfahren                │   │
│  │  HP: 11/11 │ SAN: 55/55 │ MP: 11/11                     │   │
│  │  Skills: Bibliothek(65) Okkultes(45) Spurensuche(50)...  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  [▶ Start Session]  [⏸ Pause]  [⏹ Stop]                        │
└───────────────────────────────────────────────────────────────────┘
```

**Datenquellen:**
- Alle Dropdowns befüllt via `DiscoveryService.scan()` → `.list_rulesets()`, `.list_adventures()`, etc.
- Preset-Load: `SessionConfig.from_preset(name)` → füllt alle Felder
- Charakter-Info: `CharacterManager.load_latest()` → `.stats`, `.name`, `.status_line()`

**Aktionen:**
| Button          | Funktion                                               |
|-----------------|--------------------------------------------------------|
| Start Session   | Baut `SessionConfig`, ruft `engine.initialize()`, startet Engine-Thread |
| Pause           | Setzt `orchestrator._active = False` (pausiert Game Loop) |
| Stop            | `orchestrator.stop_session()`, beendet Engine-Thread   |

---

## Tab 2: Audio Panel

Konfiguration, Test und Monitoring der Audio-Pipeline.

```
┌─ Audio Panel ────────────────────────────────────────────────────┐
│                                                                   │
│  ── Geräte ──────────────────────────────────────────────────   │
│  Mikrofon     [▼ Rode NT-USB (ID:3)     ]  [🔄 Refresh]        │
│  Speaker      [▼ Speakers (Realtek) (ID:1)]  [🔄 Refresh]      │
│                                                                   │
│  [🎤 Mic Test]  ← 3s aufnehmen, abspielen                      │
│  VAD-Meter    [████████░░░░░░░░] 0.72    ← Live Silero VAD     │
│  Mic Status   ● Listening (grün) / ● Idle (grau)               │
│                                                                   │
│  ── TTS Stimmen ─────────────────────────────────────────────   │
│  Backend      piper (erkannt)                                    │
│  Profil       [▼ standard (thorsten-high)]                      │
│                                                                   │
│  Stimmen-Test:                                                    │
│  ┌────────────┬────────────────────┬─────────┐                  │
│  │ Rolle      │ Voice-ID           │ Test    │                  │
│  ├────────────┼────────────────────┼─────────┤                  │
│  │ keeper     │ de_DE-thorsten-high│ [▶ Play]│                  │
│  │ woman      │ de_DE-kerstin-low  │ [▶ Play]│                  │
│  │ monster    │ de_DE-pavoque-low  │ [▶ Play]│                  │
│  │ scholar    │ de_DE-amadeus-med. │ [▶ Play]│                  │
│  │ mystery    │ de_DE-eva_k-x_low  │ [▶ Play]│                  │
│  └────────────┴────────────────────┴─────────┘                  │
│  Test-Text    [ Willkommen, Ermittler.________________ ]        │
│                                                                   │
│  ── STT Einstellungen ───────────────────────────────────────   │
│  Whisper-Modell  [▼ base ] (small / medium / large-v3)          │
│  Sprache         [▼ de   ]                                       │
│  VAD Threshold   [====●=====] 0.50                               │
│  Max Silence     [====●=====] 800ms                              │
│                                                                   │
│  ── Barge-in ────────────────────────────────────────────────   │
│  [☑ Barge-in aktiv]  Threshold: [====●=] 0.90                  │
│  Hinweis: Ohne Kopfhörer deaktivieren (Echo-Probleme)           │
│                                                                   │
│  ── Letzte Transkription ────────────────────────────────────   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ "Ich untersuche den Keller genauer"  (1.2s, conf: 0.94) │   │
│  └──────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

**Datenquellen:**
- Geräteliste: `sounddevice.query_devices()` → Dropdown
- VAD-Meter: Live-Feed aus `stt_handler._vad_model` Confidence-Werten
- TTS-Test: `tts_handler.speak("Testtext")` direkt
- Letzte Transkription: EventBus `stt.transcription_complete`

---

## Tab 3: KI-Monitor (Herzstück)

**Totale Transparenz** über alles, was die KI sieht und produziert. Farblich kodiert.

```
┌─ KI-Monitor ─────────────────────────────────────────────────────┐
│                                                                   │
│  ── Context-Zusammenbau (was die KI als Input bekommt) ───────  │
│                                                                   │
│  [System Prompt ▼]  [Context Injection ▼]  [History ▼]          │
│                      ← Klappbare Sektionen                       │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ ██ SYSTEM PROMPT (15.234 tokens)              [Expand ▼]│   │
│  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│   │
│  │ Persona: "Du bist der Keeper of Arcane Lore..."          │   │
│  │ Regelwerk: cthulhu_7e (45 Skills, d100)                  │   │
│  │ Abenteuer: The Haunting (12 Locations, 8 NPCs)           │   │
│  │ [Volltext anzeigen...]                                    │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │ ██ ARCHIVAR-KONTEXT                           [Expand ▼]│   │
│  │ Chronik: "Die Ermittler haben das Büro von..."           │   │
│  │ World State: {auftrag_angenommen: true, ...}             │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │ ██ LOCATION-KONTEXT                           [Expand ▼]│   │
│  │ Aktuell: knott_office — "Büro von Mr. Knott"            │   │
│  │ NPCs: mr_knott (anwesend)                                │   │
│  │ Hinweise: auftrag_dossier (verfügbar)                    │   │
│  │ Ausgänge: newspaper_archive, courthouse                   │   │
│  ├──────────────────────────────────────────────────────────┤   │
│  │ ██ HISTORY (12 Turns, 3.450 tokens)           [Expand ▼]│   │
│  │ ...                                                       │   │
│  │ [USR] "Ich frage Mr. Knott nach dem Haus"               │   │
│  │ [KI]  "Mr. Knott blickt nervös..."                       │   │
│  │ [USR] "Ich nehme den Auftrag an"                         │   │
│  │ [KI]  "Knott reicht Ihnen zitternd..." [FAKT:{...}]     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ── Live-Stream (aktuelle Interaktion) ──────────────────────   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ ▶ SPIELER (STT/Text):                                    │   │
│  │   "Ich untersuche die Dokumente auf dem Schreibtisch"    │   │
│  │                                                           │   │
│  │ ◀ KEEPER (Streaming...):                                  │   │
│  │   Sie beugen sich über den antiken Mahagoni-Schreibtisch │   │
│  │   und entdecken zwischen verstaubten Aktenordnern ein    │   │
│  │   vergilbtes Dokument...                                  │   │
│  │                                                           │   │
│  │ ⚙ TAGS (geparst):                                        │   │
│  │   [FAKT: {"dokument_gefunden": true}]                    │   │
│  │   [INVENTAR: Vergilbtes Dokument | gefunden]             │   │
│  │                                                           │   │
│  │ 🎲 PROBE (ausstehend):                                   │   │
│  │   [PROBE: Bibliotheksnutzung | 65]                       │   │
│  │   → Wurf: 34 / Ziel: 65 → Regulärer Erfolg              │   │
│  │                                                           │   │
│  │ 📝 ARCHIVAR:                                              │   │
│  │   "Chronicle updated: Die Ermittler fanden im Büro..."   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ── Token-Aufschlüsselung (letzte Anfrage) ──────────────────  │
│  Prompt: 18.734  │  Cached: 15.234  │  Output: 312  │  Think: 0│
│  Kosten: $0.0019                                                 │
└───────────────────────────────────────────────────────────────────┘
```

### Farbkodierung

| Farbe              | Herkunft / Bedeutung                                    |
|--------------------|---------------------------------------------------------|
| `#2D2D3F` (Dunkelblau)  | System Prompt — statisch, gecached                |
| `#1A3A2A` (Dunkelgrün)  | Archivar-Kontext — Chronik, World State           |
| `#3A2A1A` (Dunkelbraun) | Location-Kontext — Ort, NPCs, Hinweise            |
| `#1A2A3A` (Dunkel-Teal) | History — vergangene Turns                        |
| `#E8E8FF` (Hellblau)    | Spieler-Input (STT oder Text)                     |
| `#FFE8D0` (Hellorange)  | Keeper-Output (KI-Antwort, narrativ)              |
| `#D0FFD0` (Hellgrün)    | Geparste Tags (FAKT, INVENTAR, ZEIT...)           |
| `#FFD0D0` (Hellrot)     | Proben & Würfelergebnisse                         |
| `#D0D0FF` (Hellviolett) | Archivar-Aktionen (Chronicle, World State Update) |
| `#FFFF99` (Gelb)        | Warnungen / Fehler                                |

### EventBus-Events für diesen Tab

```
keeper.prompt_sent          → zeigt Spieler-Input
keeper.response_complete    → zeigt KI-Antwort (vollständig)
keeper.context_injected     → zeigt Context-Teile mit Herkunft
keeper.usage_update         → Token-Aufschlüsselung
archivar.chronicle_updated  → zeigt Archivar-Zusammenfassung
archivar.world_state_updated→ zeigt World-State-Delta
adventure.location_changed  → aktualisiert Location-Kontext
adventure.flag_changed      → zeigt Flag-Änderung
```

---

## Tab 4: KI-Connection

Monitoring der API-Verbindung, Token-Verbrauch und Kosten.

```
┌─ KI-Connection ──────────────────────────────────────────────────┐
│                                                                   │
│  ── Verbindungsstatus ───────────────────────────────────────   │
│  API-Key      ● Geladen (.env)        [Test Connection]         │
│  Modell       gemini-2.5-flash                                   │
│  Status       ● Connected (grün) / ● Disconnected (rot)        │
│  Letzte Antwort  vor 3s                                          │
│  Rate Limits  0 / 2 Retries in Session                          │
│                                                                   │
│  ── Context Cache ───────────────────────────────────────────   │
│  Cache Status    ● Aktiv (grün)                                  │
│  Cache Name      cachedContents/abc123...                        │
│  Cache Größe     15.234 tokens                                   │
│  TTL             7200s (verbleibend: 5.832s)                     │
│  Ersparnis       ~$0.041 gespart in dieser Session              │
│                                                                   │
│  ── Session Token-Verbrauch ─────────────────────────────────   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │           │  Tokens      │  Kosten                       │   │
│  │  Prompt   │  142.830     │  $0.0429                      │   │
│  │  Cached   │  121.872     │  $0.0037                      │   │
│  │  Output   │   4.560      │  $0.0114                      │   │
│  │  Thinking │       0      │  $0.0000                      │   │
│  │  ─────────┼──────────────┼───────────                    │   │
│  │  GESAMT   │  148.390     │  $0.0580                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ── Verlauf (pro Turn) ──────────────────────────────────────   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Turn │ Prompt │ Cached │ Output │ Think │ Cost │ Lat.  │   │
│  │  #1   │  15402 │  15234 │    287 │     0 │ $.002│ 1.3s  │   │
│  │  #2   │  15891 │  15234 │    342 │     0 │ $.003│ 1.1s  │   │
│  │  #3   │  16320 │  15234 │    198 │     0 │ $.002│ 0.9s  │   │
│  │  ...  │   ...  │   ...  │   ...  │  ...  │  ... │  ...  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ── Token-Trend (Grafik) ────────────────────────────────────   │
│  Tokens ▲                                                        │
│  20k    │          ╭──────╮                                      │
│  15k    │  ╭───────╯      ╰──╮     ← Prompt (inkl. History)    │
│  10k    │──╯                  ╰──                                │
│   5k    │                                                        │
│    0    │▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄  ← Output                   │
│         └──────────────────────── ▶ Turns                       │
│                                                                   │
│  ── History Management ──────────────────────────────────────   │
│  History Turns   12 / 40 (max)                                   │
│  History Tokens  ~3.450                                          │
│  [Clear History]  [Export Session Log]                           │
└───────────────────────────────────────────────────────────────────┘
```

**Datenquellen:**
- `ai_backend._usage_total` → Session-Summen
- `keeper.usage_update` Event → pro-Turn Aufschlüsselung
- `ai_backend._cache_name` → Cache-Status
- `ai_backend._history` → History-Länge
- Latenz: Zeitdifferenz zwischen `prompt_sent` und `response_complete`

---

## Tab 5: Spielstand & Log

Spielstand-Management und Session-Protokoll.

```
┌─ Spielstand & Log ───────────────────────────────────────────────┐
│                                                                   │
│  ── Spielstand ──────────────────────────────────────────────   │
│                                                                   │
│  ┌─ Charakter ────────────────────────────────────────────┐    │
│  │  Thomas Blackwood — Antiquarian                         │    │
│  │  HP: [████████░░] 8/11  │  SAN: [██████████] 52/55    │    │
│  │  MP: [██████████] 11/11                                 │    │
│  │  Skills Used: Bibliothek, Okkultes, Spurensuche         │    │
│  │  Inventar: Vergilbtes Dokument, Taschenlampe            │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌─ World State ──────────────────────────────────────────┐    │
│  │  auftrag_angenommen: true                               │    │
│  │  dokument_gefunden: true                                 │    │
│  │  haus_betreten: false                                    │    │
│  │  corbitt_besiegt: false                                  │    │
│  │  ... (12 Flags)                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌─ Location ─────────────────────────────────────────────┐    │
│  │  📍 knott_office — Büro von Mr. Knott                   │    │
│  │  Turn: 12 │ Session: #3 │ Dauer: 00:23:15              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  [💾 Save]  [📂 Load]  [📤 Export JSON]                         │
│                                                                   │
│  ── Session-Saves ───────────────────────────────────────────   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  #3  │ spukhaus │ Turn 12 │ knott_office │ 2026-02-28   │   │
│  │  #2  │ spukhaus │ Turn 8  │ newspaper    │ 2026-02-27   │   │
│  │  #1  │ spukhaus │ Turn 3  │ knott_office │ 2026-02-26   │   │
│  │                                              [Load ▶]    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ── Event-Log (chronologisch) ───────────────────────────────   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ 14:23:01  keeper.prompt_sent          user_input=...     │   │
│  │ 14:23:03  keeper.response_complete    tokens=312         │   │
│  │ 14:23:03  adventure.flag_changed      dokument_ge...     │   │
│  │ 14:23:03  keeper.usage_update         cost=$0.002        │   │
│  │ 14:25:12  keeper.prompt_sent          user_input=...     │   │
│  │ 14:25:14  archivar.chronicle_updated  summary=...        │   │
│  │ ...                                                       │   │
│  │                                                           │   │
│  │ Filter: [▼ Alle] [☑ keeper] [☑ archivar] [☑ adventure]  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  [Clear Log]  [Export Log (.txt)]                                │
└───────────────────────────────────────────────────────────────────┘
```

---

## Status Bar (permanent sichtbar)

Am unteren Rand des Fensters, immer sichtbar, egal welcher Tab aktiv ist:

```
┌────────────────────────────────────────────────────────────────────┐
│ ● Running │ Turn 12 │ Thomas Blackwood HP:8/11 SAN:52/55 │       │
│ 📍 knott_office │ 🎤 Listening │ 💰 $0.058 │ ⏱ 23:15           │
└────────────────────────────────────────────────────────────────────┘
```

| Segment          | Quelle                                     |
|------------------|--------------------------------------------|
| Engine State     | `Running / Paused / Stopped / Error`       |
| Turn             | `orchestrator._session_history` Länge      |
| Character Stats  | `character.status_line()`                  |
| Location         | `adventure_manager.get_current_location()` |
| Mic Status       | VAD live state                             |
| Session Cost     | `ai_backend._usage_total`                  |
| Session Duration | Laufzeit seit `start_session()`            |

---

## Dateistruktur (neue Dateien)

```
ARS/
├── core/
│   └── event_bus.py          ← NEU: Singleton EventBus
│
├── gui/
│   ├── __init__.py           ← NEU
│   ├── tech_gui.py           ← NEU: Hauptfenster, Tab-Container
│   ├── tab_session.py        ← NEU: Tab 1 — Session Setup
│   ├── tab_audio.py          ← NEU: Tab 2 — Audio Panel
│   ├── tab_ki_monitor.py     ← NEU: Tab 3 — KI Monitor
│   ├── tab_ki_connection.py  ← NEU: Tab 4 — KI Connection
│   ├── tab_gamestate.py      ← NEU: Tab 5 — Spielstand & Log
│   ├── status_bar.py         ← NEU: Persistente Statusleiste
│   └── styles.py             ← NEU: Farb-/Style-Konstanten
│
└── main.py                   ← ÄNDERUNG: --techgui Flag hinzufügen
```

---

## Implementierungs-Reihenfolge

### Phase 1 — Fundament
| #  | Aufgabe                                              | Abhängigkeit |
|----|------------------------------------------------------|--------------|
| 1  | `core/event_bus.py` implementieren                   | —            |
| 2  | Bestehende `emit()`-Aufrufe validieren/ergänzen      | #1           |
| 3  | `gui/styles.py` — Farbkonstanten, Fonts              | —            |
| 4  | `gui/tech_gui.py` — Hauptfenster mit ttk.Notebook    | #3           |
| 5  | `gui/status_bar.py` — Statusleiste                   | #1, #4       |
| 6  | `main.py` — `--techgui` Flag, GUI-Thread-Start       | #4           |

### Phase 2 — Tabs (parallel möglich)
| #  | Aufgabe                                              | Abhängigkeit |
|----|------------------------------------------------------|--------------|
| 7  | `gui/tab_session.py` — Setup-Formulare + Start/Stop  | #4, #1       |
| 8  | `gui/tab_audio.py` — Geräte, TTS-Test, VAD-Meter    | #4           |
| 9  | `gui/tab_ki_monitor.py` — Context-Viewer, Live-Stream| #4, #1       |
| 10 | `gui/tab_ki_connection.py` — Token-Tracking, Grafik  | #4, #1       |
| 11 | `gui/tab_gamestate.py` — Save/Load, Event-Log        | #4, #1       |

### Phase 3 — Integration & Polish
| #  | Aufgabe                                              | Abhängigkeit |
|----|------------------------------------------------------|--------------|
| 12 | Engine-Thread-Management (Start/Pause/Stop sicher)   | #7           |
| 13 | Save/Load Integration mit SQLite                     | #11          |
| 14 | Token-Trend Canvas-Grafik                            | #10          |
| 15 | VAD Live-Meter Integration                           | #8           |
| 16 | Gesamttest: --techgui --voice --module --adventure   | Alle         |

---

## Offene Design-Entscheidungen

1. **Token-Trend Grafik** — tkinter Canvas reicht für einfache Liniendiagramme. Soll matplotlib eingebettet werden (schöner, aber Dependency)?
   → Empfehlung: Canvas. Keine neue Dependency.

2. **Live-Streaming im KI-Monitor** — Chunks in Echtzeit anzeigen oder erst nach Abschluss?
   → Empfehlung: Live. Chunks per `root.after()` in Text-Widget einfügen.

3. **Existierende GUI (`--gui`)** — Es gibt laut `stand.md` bereits eine Spieler-GUI ("The Investigator's Desk"). Die TechGUI ist ein separates Werkzeug. Beide können koexistieren, aber nie gleichzeitig laufen.
   → `--gui` = Spieler-GUI (existierend), `--techgui` = Entwickler-GUI (neu)

4. **Dark Mode** — Die Farbkodierung im KI-Monitor funktioniert besser auf dunklem Hintergrund.
   → Empfehlung: TechGUI grundsätzlich dunkel (`#1E1E2E` Hintergrund, Catppuccin-artig).
