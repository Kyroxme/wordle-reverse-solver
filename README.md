# Reverse Wordle Solver

Du kennst die **Lösung** eines Wordle-Spiels und die **Farbmatrix** deiner
Versuche – aber nicht mehr, welche Wörter du getippt hast. Dieses Programm
brute-forct die offizielle Wortliste durch und zeigt für jede Zeile alle
Wörter, die genau diese Farben erzeugt hätten.

```
 REVERSE WORDLE                 2309 Wörter
────────────────────────────────────────────
Lösung  [C][R][A][N][E]       ✓ Lösungsliste
────────────────────────────────────────────
▸1 >X< [X] [G] [X] [G]  43
 2 [X] [G] [X] [X] [G]  26
 3 [X] [G] [X] [X] [G]  26
 4 [G] [X] [G] [X] [G]  3
 5 [ ] [ ] [ ] [ ] [ ]
 6 [ ] [ ] [ ] [ ] [ ]
────────────────────────────────────────────
 Zeile 1 · 43 Kandidaten            0.4 ms
  ABASE  ABATE  ADAGE  AGAPE  AGATE  AMAZE
  AWAKE  BLADE  BLAME  BLAZE  ELATE  EVADE
  FLAKE  FLAME  GLADE  GLAZE  HEAVE  IMAGE
  LEASE  LEAVE  OVATE  PHASE  PLATE  QUAKE
  1–24 von 43  ( , . blättern )
────────────────────────────────────────────
  fest: 3=A, 5=E · grau: 1≠C, 2≠R, 4≠N
 g/y/x · i Lösung · a Liste · ? · q
```

## Starten

```bash
python3 reverse_wordle.py            # TUI
```

Nur Standardbibliothek, kein `pip install` nötig. Python 3.9+.

## Windows und Docker

Windows kennt kein `termios`, deshalb läuft das TUI dort nicht nativ. Im
Container schon – dort ist es ein Linux, und Docker reicht das Terminal durch.
Der Batch-Modus funktioniert auch ohne Docker direkt in PowerShell.

```powershell
docker compose build
docker compose run --rm solver                    # TUI
docker compose run --rm solver -s crane -r GYXXG  # Batch
docker compose run --rm solver --info
```

Ohne Compose:

```powershell
docker build -t wordle-reverse-solver .
docker run -it --rm wordle-reverse-solver
```

Das Image ist schlank (Alpine-Basis, keine Zusatzpakete, ~200 KB Code) und
selbstständig: Wortlisten sind eingebaut, keine Volumes nötig.

* PowerShell oder Windows Terminal benutzen – Git-Bash braucht zusätzlich
  `winpty` vor dem `docker run`.
* Zeichen sehen verwürfelt aus oder die Fenstergröße kommt nicht an:
  `docker compose run --rm -e NO_COLOR=1 -e COLUMNS=100 -e LINES=30 solver`
* Selbsttest im Container:
  `docker compose run --rm --entrypoint python3 solver -m unittest discover -s tests`

Nativ ohne Docker geht immer: `python reverse_wordle.py -s crane -r GYXXG`.

## TUI-Bedienung

| Taste | Wirkung |
| --- | --- |
| `i` | Lösung eintippen (Enter übernimmt, Esc bricht ab) |
| `m` / `v` | Farbmuster einfügen – auch ein komplettes Emoji-Grid |
| `g` oder `2` | Zelle grün |
| `y` oder `1` | Zelle gelb |
| `x` / `0` / `-` | Zelle grau |
| Leertaste | Zelle leeren |
| `←` `→` | Zelle wählen |
| `↑` `↓` / Tab / Enter | Zeile bzw. Lösung wechseln |
| `h` `l` `j` `k` | dasselbe ohne Pfeiltasten |
| `⌫` / Entf | Zelle löschen / ganze Zeile leeren |
| `u` / `c` | Zelle löschen / Zeile leeren (ohne Sondertasten) |
| `D` | Tasten-Diagnose: zeigt die Rohbytes der letzten Taste |
| `a` | Wortliste umschalten: offizielle Lösungen ↔ alle erlaubten Tipps |
| `,` `.` / Bild↑ Bild↓ | Kandidatenliste blättern |
| `R` | alles zurücksetzen |
| `?` / `q` | Hilfe / beenden |

Die Farbmatrix muss nicht aus Buchstaben bestehen: `m` nimmt auch eingefügte
Wordle-Emojis an (`🟩🟨⬛⬛🟩`), mehrere Zeilen auf einmal inklusive.

### Tasten und Terminals

Pfeiltasten und Backspace sind Sondertasten: Pfeile kommen als `ESC [ D` an,
Backspace als `0x7F` oder `0x08`. Das TUI liest die Bytes direkt vom Terminal
(`os.read`) und wartet bis zu 120 ms auf den Rest einer ESC-Sequenz. Über
`sys.stdin.read()` ginge das nicht: Python puffert die Folgebytes im Userspace,
ein `select()` auf dem Filedescriptor sieht sie danach nicht mehr — genau
daran scheiterten Pfeiltasten.

Deshalb funktionieren die Tasten auch über SSH, tmux und im Container, und für
alle Fälle gibt es die Alternative ohne Sondertasten (`h` `l` `j` `k`, `u`, `c`).
Kommt eine Taste trotzdem nicht an: `D` zeigt ihre Rohbytes in der Statuszeile.

## Batch-Modus

```bash
python3 reverse_wordle.py -s crane -r GYXXG XGXXG
python3 reverse_wordle.py -s crane -r "🟩🟨⬛⬛🟩" --pool all
printf '🟩🟨⬛⬛🟩\n🟨🟨⬛⬛⬛\n' | python3 reverse_wordle.py -s crane --json
```

`--pool answers` (Standard) durchsucht die offiziellen Lösungen,
`--pool all` alle 14 855 erlaubten Tipps, `-n` begrenzt die Ausgabe,
`--json` liefert maschinenlesbare Ergebnisse.

## Wie die Rückwärtssuche arbeitet

Aus einem Farbmuster ist **nur bei Grün der Buchstabe sicher**. Gelb bedeutet
„der getippte Buchstabe kommt in der Lösung noch vor“, Grau „…nicht mehr“ –
welcher Buchstabe dort stand, ist genau die gesuchte Information.

Ein Kandidat ist deshalb jedes Wort, dessen vollständiges Feedback gegen die
Lösung an allen bekannten Stellen zum Muster passt:

```python
feedback(kandidat, lösung) == muster      # bei vollständiger Matrix
```

Daraus folgen mehrere Kandidaten pro Zeile – das ist keine Schwäche, sondern
die Wahrheit über die Informationsmenge einer Farbzeile. Grüne Zellen sind
fix, Gelb/Grau schließen nur Positionen aus.

Umsetzung in `wordle/core.py`:

1. **Positionsfilter** – grüne Stellen müssen exakt passen, gelbe und graue
   Stellen dürfen den Lösungsbuchstaben dort nicht haben.
2. **Feedback-Simulation** für die Überlebenden: grüne Treffer zuerst, gelbe
   aus dem Restvorrat von links nach rechts (Wordle-Regel bei Duplikaten).
3. **Cache** pro (Lösung, Muster, Wortliste), damit jedes Neuzeichnen der TUI
   ohne Neuberechnung auskommt.

Gemessen auf diesem Gerät: 2–9 ms für 14 855 Wörter (schwächstes Muster,
alles grau), typisch < 1 ms – die Kandidatenliste erscheint beim Tippen sofort.

## Wortlisten

`data/answers.txt` (2 309 Wörter) und `data/allowed_guesses.txt` (14 855
Wörter) stammen direkt aus dem JavaScript-Bundle der offiziellen
Wordle-Seite der New York Times. `tools/fetch_official_lists.py` lädt sie neu:

```bash
python3 tools/fetch_official_lists.py
```

Das Skript sucht das Bundle, das den Anker `"cigar"` (erstes Lösungswort)
enthält, und trennt die sortierte Rate-Liste von der Lösungsliste. Ein
erneuter Lauf reproduziert die mitgelieferten Dateien byte-identisch.

## Projektstruktur

```
reverse_wordle.py            Einstiegspunkt
wordle/core.py               Feedback, Vorfilter, Solver, Constraints
wordle/tui.py                Zustand, Tastenlogik, Rendering, Terminal-I/O
wordle/cli.py                Batch-Modus, JSON, stdin
data/                        offizielle Wortlisten
tools/fetch_official_lists.py  Listen aktualisieren
tests/                       65 Tests (core, tui, input, cli, pty)
Dockerfile                   Alpine-Image für Windows/macOS
docker-compose.yml           Build und Start mit einem Befehl
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Geprüft wird unter anderem: Wordle-Feedback gegen eine unabhängige
Referenzimplementierung (400 Zufallspaare), Kandidatenmengen gegen echte
Brute-Force-Ergebnisse (40 Zufallspaare), Duplikat-Regeln, Teil-Muster,
Emoji-Parsing, Cache, TUI-Tasten und -Layout (auch bei 30 Spalten), die
Eingabeschicht (Pfeil-, Bild-, Backspace- und Steuertasten, UTF-8 über mehrere
Lesepakete), ein Rauchtest, der das echte TUI im Pseudo-Terminal mit
Pfeiltasten und Backspace bedient, und der Windows-Fall (fehlendes `termios`).

## Grenzen

- Wortlisten sind englisch (Wordle-Standard); deutsche Wörter brauchen eigene
  `data/`-Dateien mit 5-Buchstaben-Wörtern.
- Bei sehr schwachen Mustern (viele graue Zellen) bleiben Hunderte Kandidaten
  übrig – das ist bei einer reinen Farbzeile nicht anders möglich.
- Die TUI braucht ein echtes Terminal; ohne TTY erklärt das Programm den
  Batch-Modus, unter Windows den Weg über Docker.
