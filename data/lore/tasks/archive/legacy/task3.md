Task 03: Lokale Audio-Pipeline Realisierung (für Claude Code)

Kopiere diesen Inhalt in eine Datei namens task\_03\_audio\_realization.md.



ARS Task 03: Funktionale STT/TTS Implementierung

Akteur: Claude Code

Kontext: Umwandlung der Audio-Stubs in performante, lokale KI-Dienste.



Zielsetzung

Implementiere die lokale Sprachverarbeitung mit minimaler Latenz (< 500ms), um ein flüssiges Gespräch zu ermöglichen .



Anforderungen

STT (Speech-to-Text):



Implementiere in audio/stt\_handler.py die Faster-Whisper Bibliothek .



Integriere Silero VAD, um das Ende der Spielersprache automatisch zu erkennen, damit kein Tastendruck nötig ist .



TTS (Text-to-Speech):



Implementiere in audio/tts\_handler.py das Modell Kokoro-82M (via ONNX oder direktem Python-Wrapper) .



Wichtig: Aktiviere Audio-Streaming. Die Sprachausgabe muss starten, sobald der erste Satz vom LLM generiert wurde .



Interruption Logic: Implementiere ein "Barge-in" Feature. Wenn der Spieler spricht (VAD-Signal), während die KI noch antwortet, muss die TTS-Ausgabe sofort stoppen.



Dependencies: Aktualisiere die requirements.txt mit allen notwendigen Paketen (faster-whisper, kokoro, sounddevice, pyaudio).



Abnahmekriterien

python main.py --voice startet das Spiel im Sprachmodus.



Die Latenz zwischen "Spieler hört auf zu sprechen" und "KI fängt an zu sprechen" liegt bei einem schnellen lokalen Rechner unter 1 Sekunde.

