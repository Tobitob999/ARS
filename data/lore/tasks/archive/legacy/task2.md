ARS Task 02: KI-Backend \& Narrator-Orchestration

Akteur: Gemini 2.0 Flash (via Google AI Studio API)

Kontext: Integration des LLM als "Keeper" (Spielleiter) für Call of Cthulhu.



Zielsetzung

Ersetze die Placeholder-Antworten in orchestrator.py durch echte KI-Aufrufe. Die KI muss den Spielzustand (Charakterwerte, Regeln, bisherige Story) kennen und darauf reagieren.



Anforderungen

API-Anbindung: Erstelle core/ai\_client.py. Nutze das google-generativeai SDK. Implementiere eine Methode, die Text-Streaming unterstützt .



Keeper-Prompting: Erstelle einen System-Prompt, der Gemini in die Rolle eines CoC-Keepers versetzt.



Regel-Fokus: Die KI soll nicht selbst würfeln, sondern die MechanicsEngine auffordern, wenn eine Probe nötig ist (Tools/Function Calling oder spezifische Tags).



Atmosphäre: Fokus auf Lovecraft’schen Horror, subtile Spannung und detaillierte Beschreibungen .



Kontext-Management:



Übermittle bei jedem Turn den aktuellen Charakter-Status aus der SQLite-DB.



Nutze Gemini's Context Caching, um das geladene cthulhu\_7e.json und die Lore permanent im Gedächtnis zu behalten, ohne jedes Mal Token zu verschwenden .



Integration: Verbinde orchestrator.py so mit dem neuen Client, dass die Antwort des Keepers für die Sprachausgabe bereitgestellt wird.



Abnahmekriterien

Ein Testlauf in der Konsole zeigt eine atmosphärische Beschreibung des Keepers.



Die KI erkennt, wenn der Spieler eine Aktion versucht (z.B. "Ich untersuche die Bibliothek"), und schlägt eine "Library Use"-Probe vor.

