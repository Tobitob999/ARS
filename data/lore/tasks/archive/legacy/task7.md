ARS Task 07: Investigator-Erstellung \& DB-Injektion

Akteur: Claude Code

Kontext: Vorbereitung eines Test-Charakters in ars\_vault.sqlite.



Zielsetzung

Erstelle einen vollständigen CoC 7e Investigator und speichere ihn als Start-Zustand in der Datenbank.



Anforderungen

Investigator-Profil: Erstelle einen Charakter (z.B. Dr. Silas Moore, Professor an der Miskatonic University).



Werte-Generierung: Berechne die Attribute und Skills gemäß cthulhu\_7e.json (z.B. Bibliotheksnutzung 70%, Psychologie 50%, HP 12, SAN 60).



Automatisierung: Schreibe ein Hilfsskript scripts/create\_test\_char.py, das diesen Charakter per SQL direkt in die Tabelle characters deiner ars\_vault.sqlite schreibt.



Verknüpfung: Stelle sicher, dass beim Start von main.py --module cthulhu\_7e dieser Charakter als Standard geladen wird.

