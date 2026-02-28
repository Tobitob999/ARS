ARS Task 06: Abenteuer-Modul "Das Spukhaus"

Akteur: Gemini 2.5 Flash

Kontext: Erstellung der Datenbasis für ein Call of Cthulhu Einstiegs-Szenario.



Zielsetzung

Erstelle eine adventure\_spukhaus.json und eine dazugehörige Lore-Datei, die alle Informationen für den Keeper enthält.



Anforderungen

Szenario-Struktur: Erstelle ein JSON-Objekt für /modules/adventures/spukhaus.json:



hook: Der Einstieg (Ein Hilferuf eines sterbenden Freundes).



locations: Mindestens 3 Orte (Das Krankenhaus, die Bibliothek von Arkham, das alte Corbitt-Haus).



npcs: Profile für wichtige Charaktere (Rupert Merriweather, der Geist von Corbitt).



clues: Hinweise, die an Orten gefunden werden können.



Keeper-Lore: Erstelle einen ausführlichen Text-Block "Hintergrund für den Spielleiter". Dieser enthält das dunkle Geheimnis, das der Spieler erst am Ende erfahren darf.



Integration: Das JSON muss so aufgebaut sein, dass der ModuleLoader aus Task 01 es einlesen kann.



Task 07: Charakter-Generierung \& Initial-Zustand (für Claude Code)

Hier lassen wir Claude Code einen spielbaren Investigator erstellen und ihn direkt in die Datenbank "beamen", damit du nicht tippen musst.

