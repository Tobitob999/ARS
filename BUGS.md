# ARS Known Bugs

## BUG-001: Audio-Ein/Ausgabe funktioniert nicht im Spiel (2026-03-01)

**Status:** Offen
**Prioritaet:** Mittel
**Betrifft:** Voice I/O (STT + TTS) im Game Tab

### Beschreibung
Voice wird korrekt initialisiert (STT: faster_whisper, TTS: piper), aber waehrend
des Spiels kommt weder Audio-Eingabe (Mikrofon -> STT) noch Audio-Ausgabe (TTS)
zum Einsatz. Alle Interaktion lief ueber Texteingabe.

### Beobachtetes Verhalten
- STT zeigt "Hoere zu..." im Log, erkennt aber keine Sprache oder der erkannte
  Text wird nicht als Spielereingabe verarbeitet
- TTS-Ausgabe der Keeper-Antworten fehlt
- Mic-Level-Anzeige im Game Tab nicht getestet (abhaengig von funktionierendem STT)

### Erwartetes Verhalten
- Bei aktiviertem Voice-Modus: Spieler spricht ins Mikrofon -> STT transkribiert ->
  Text wird als Spielereingabe an Orchestrator gesendet
- Keeper-Antworten werden via TTS vorgelesen
- Mic-Level-Bar im Game Tab zeigt Live-Pegel

### Moegliche Ursachen
- Voice-Pipeline wird moeglicherweise nicht korrekt in den Game Loop integriert
  wenn Auto-Voice aktiv ist
- STT-Listen-Loop blockiert oder wird nicht aufgerufen wenn Engine auf Input wartet
- TTS-Streaming wird moeglicherweise nicht getriggert bei stream_end Event

### Relevante Dateien
- `core/orchestrator.py` — Game Loop, Voice-Integration
- `audio/pipeline.py` — VoicePipeline (STT + TTS Koordination)
- `audio/stt_handler.py` — Speech-to-Text
- `audio/tts_handler.py` — Text-to-Speech
- `gui/tab_game.py` — Voice Toggle, Mic-Level Anzeige

### Reproduktion
1. `py -3 main.py --module add_2e --preset testkampf --techgui`
2. Session starten
3. Voice-Checkbox aktivieren (warten bis "Voice aktiviert" erscheint)
4. Ins Mikrofon sprechen -> keine Reaktion
