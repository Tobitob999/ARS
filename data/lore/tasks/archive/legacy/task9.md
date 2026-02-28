Anweisung für Claude Code: Task 09 — GUI-Implementierung "The Investigator's Desk"

Kontext:

Das ARS-Backend ist stabil. Wir benötigen nun ein atmosphärisches Frontend, das die Immersion eines Lovecraft-Horrorspiels der 1920er Jahre unterstützt. Die Wahl des Frameworks fällt auf CustomTkinter, um moderne Dark-Mode-Ästhetik mit einfacher Python-Integration zu verbinden.



1\. Architektur \& Datei-Struktur

Neues Modul: Erstelle ui/dashboard.py mit der Klasse InvestigatorDashboard.



Asynchronität: Die GUI muss in einem separaten Thread oder via asyncio.loop laufen, um den Orchestrator und die VoicePipeline nicht zu blockieren.



Integration: Erweitere main.py, um die GUI optional via --gui Flag zu starten.



2\. Visuelles Design (Thema \& Layout)

Ästhetik: Dark-Mode (Hintergrund: #1A1A1A). Akzentfarben: Pergament (#F5F5DC), Blutrot (#8B0000) für Warnungen/HP.



Schriftarten: Serif (z. B. "Times New Roman") für den Keeper-Text; Monospace (z. B. "Courier") für technische Statusmeldungen.



Layout (4-Säulen-Grid):



Links (Investigator Stats): Vertikale Progress-Bars für HP (rot), SAN (blau), MP (violett). Anzeige von Name (Dr. Silas Moore), Beruf (Professor), INT (85) und EDU (90).



Mitte (Narrative Feed): Ein großes CTkTextbox-Element. Text wird mit einem "Typewriter-Effekt" (verzögerte Zeichenausgabe) angezeigt, um die TTS-Generierung visuell zu kaschieren.



Rechts (Case Folder): Ein Bereich für Handouts. Nutze PIL (Pillow), um Bilder oder Dokument-Texte aus spukhaus.json darzustellen.



Unten (Console \& Status): Ein pulsierender Indikator für das silero-vad Signal (Grün = hört zu, Grau = Stille).



3\. Funktionale Logik \& Data Binding

Live-Update: Binde die UI an data/ars\_vault.sqlite. Sobald der Orchestrator ein Zustands-Tag (z. B. <SUB\_HP:2>) verarbeitet, muss die UI den entsprechenden Balken sofort aktualisieren.



Tag-Filtering: Der Narrative Feed muss alle technischen Tags (z. B. <ROLL:LibraryUse> oder <FACTS:...>) aus dem Text entfernen, bevor sie angezeigt werden.



Handout-Trigger: Implementiere einen Event-Handler. Wenn der Keeper ein Handout erwähnt (z. B. handout\_1), soll das entsprechende Asset automatisch im rechten Bereich eingeblendet werden.



Barge-in Button: Ein manueller "Stopp"-Button, der das interrupt\_signal an die TTS-Engine sendet, falls die automatische VAD-Erkennung versagt.



4\. Akzeptanzkriterien

Start von main.py --gui --module cthulhu\_7e öffnet das Dashboard.



Die Stats von Dr. Silas Moore werden korrekt aus der DB geladen.



Der Keeper-Text erscheint im Narrative Feed, ohne technische Tags anzuzeigen.



Der VAD-Status visualisiert Echtzeit-Spracherkennung.



Nächste Schritte für dich (Claude):



Erstelle die Datei ui/dashboard.py.



Passe core/orchestrator.py an, um Signale (Text, Stats, Handouts) an die UI-Instanz zu senden.



Teste die Darstellung mit dem "Spukhaus"-Szenario.

