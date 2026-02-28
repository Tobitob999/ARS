Zielsetzung

Verwandle den Simulator in eine persistente Welt. Der Keeper muss sich an Ereignisse von vor 100 Runden erinnern, ohne das Token-Limit zu sprengen oder die Latenz zu erhöhen.



Anforderungen

1\. Explizites Context Caching (Performance)

Implementiere in core/ai\_backend.py eine Logik für Gemini Explicit Caching:



Static Cache: Erstelle einen Cache für das cthulhu\_7e.json Regelwerk. Da sich Regeln selten ändern, spart dies bei jedem Turn Rechenzeit.



Adventure Cache: Cache die Lore-Beschreibungen des aktuellen Abenteuers (Orte, NPCs).



TTL-Management: Setze eine Time-to-Live (TTL) von mind. 2 Stunden für aktive Sessions.



2\. Die "Chronik" (Zusammenfassung)

Erstelle eine Klasse Archivist in core/memory.py:



Trigger: Nach jeweils 15 Runden (aus session\_turns) soll die KI eine kurze, faktische Zusammenfassung der bisherigen Ereignisse erstellen ("Chronik").



Injektion: Diese Chronik ersetzt die alten Einzel-Turns im Prompt. So bleibt der Kontext schlank, aber der "Rote Faden" erhalten.



3\. World-State-Tracking (Fakten)

Erweitere die SQLite-Logik, um einen World State (JSON-Blob) zu speichern: 



Die KI kann über ein neues Tag `` Fakten festschreiben (z.B. {"miller\_tot": true}).



Dieser Zustand wird bei jedem Turn als "Aktuelle Fakten" mitgesendet, um Widersprüche zu vermeiden (z.B. dass ein toter NPC plötzlich wieder spricht).



Abnahmekriterien

Beim Start einer Session wird geprüft, ob ein passender Cache existiert, und dieser wird geladen.



Nach 15 Runden Spielzeit erscheint in den Logs ein "Chronicle Update", das die Story zusammenfasst. 



Der Keeper "weiß" auch nach einem Neustart, welche NPCs bereits getroffen wurden (via World State).

