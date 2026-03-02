# PDF Bild-Extraktor (GUI)

Dieses Tool durchsucht eine PDF-Datei und extrahiert alle eingebetteten Bilder.
Die Bilder werden in einen Unterordner gespeichert, dessen Name dem PDF-Dateinamen entspricht.

## Funktionen
- GUI mit Dateiauswahl (`PDF auswählen`)
- Zielordner-Auswahl (`Ordner wählen`)
- Statusbar + Fortschrittsanzeige
- Automatische Ordnerstruktur: `<Zielordner>/<PDF-Name>/...`

## Voraussetzungen
- Python 3.10+
- `PyMuPDF` (Modulname: `fitz`)

Falls nötig installieren:

```bash
pip install pymupdf
```

## Starten

```bash
python app.py
```

## Automatischer Funktionstest
Erzeugt eine kleine Test-PDF mit Bild und prüft die Extraktion:

```bash
python app.py --self-test
```

Die Testdateien landen in:
- `_selftest_output/test_input.pdf`
- `_selftest_output/test_input/` (extrahierte Bilder)
