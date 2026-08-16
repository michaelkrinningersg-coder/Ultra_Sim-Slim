# UltraSim Slim

Ultracycling-Simulator, schlanke Fassung. Ein Fahrer hat genau drei
Eigenschaften — **FTP, Gewicht, Größe** —, eine Strecke ist ein
zweidimensionales Höhenprofil, und alles andere folgt aus der Physik.

Ein Rennen wird **nie vorberechnet**. Die Engine ist ein angehaltener
Generator, der genau so weit gezogen wird, wie die Uhr des Zuschauers
steht. Was nicht gerechnet ist, kann auch nicht verraten werden.

```
python -m ultraslim.app          # startet den Server und öffnet den Browser
```

## Was drin ist

- **300 Fahrer** aus 8 Nationen, verteilt auf **25 Teams** zu je 12.
- **6 Rennen** je Saison, 300 bis 1000 km, von flach bis Hochgebirge.
- **3 Saisons** über dieselben Strecken — was sich unterscheidet, ist die
  Tagesform des Feldes.
- **Einzelstart im Zehn-Minuten-Takt**, gesetzt nach dem Stand der
  Saisonwertung: die wenigsten Punkte zuerst, der Führende zuletzt.
  Gewertet wird die gefahrene Eigenzeit.
- Live-Interface mit Ticker, Startliste, Höhenprofil und Telemetrie-Board,
  Zeitraffer bis 1000×, Vor- und Rücksprung.
- Fahrer- und Teamwertung über die Saison.

## Das Physikmodell

Je Zeitschritt eine Kräftebilanz, integriert nach Euler:

```
a = (P · η / v  −  Crr·m·g·cosα  −  m·g·sinα  −  ½·ρ·CdA·v²) / m
```

| Größe | Wert | Herkunft |
|---|---|---|
| Antriebsstrang | η = 0,975 | Kette, Ritzel, Lager |
| Rollwiderstand | Crr = 0,0040 + 0,00005·v | Racing-Clincher 25–28 mm, gemessen auf der Trommel bei rund 0,0030, plus Zuschlag für echten Asphalt |
| Rad | 7,5 kg | Straßenrennrad, für alle gleich |
| Frontalfläche | A = 0,0276 · h[m]^0,725 · m[kg]^0,425 | Du-Bois-Form; dieselbe Form liegt der Regression von Bassett et al. (1999) zugrunde |
| Luftwiderstand | CdA = A · k | k = 1,20 Unterlenker, 1,45 am Anstieg, gleitend zwischen 1 % und 6 % Steigung |
| Luftdichte | ρ(h) | barometrische Höhenformel der Standardatmosphäre, 15 °C |
| Zeitschritt | 1 s | fein genug für eine 15-%-Rampe |

Zwei Kontrollpunkte, die im Test stehen — 280 W, 75 kg, 180 cm:

- flach → **38,3 km/h** (CdA 0,318)
- 8 % Steigung → **13,8 km/h**, das sind 1104 Höhenmeter je Stunde

### Pacing

Zielleistung = `FTP · IF · Tagesform · Steigungsfaktor · Trittrauschen`.

- **IF** folgt der Renndistanz: 0,72 bei 300 km, 0,70 bei 400, 0,66 bei
  600, 0,64 bei 700, 0,62 bei 850, 0,60 bei 1000 km.
- **Steigungsfaktor** steigt linear von 1,00 im Flachen auf 1,15 ab 8 %
  und fällt auf 0,55 ab 4 % Gefälle.
- **Tagesform** ist ein Faktor je Fahrer und Rennen, N(1,00; 0,04),
  begrenzt auf 0,88–1,12. Reproduzierbar aus dem Renn-Seed.
- **Trittrauschen** sind zwei langsam wandernde Wellen, zusammen
  höchstens ±2 % — sichtbar in der Wattanzeige, praktisch wirkungslos auf
  die Endzeit.
- Bergab läuft die Leistung über die Trittfrequenz aus: Im größten Gang
  (9,55 m Entfaltung) ist bei 114 rpm Schluss.

Was es **nicht** gibt: Ermüdung, W′-Bilanz, Verpflegung, Schlaf, Wetter,
Wind, Defekte, Stürze, Taktik, Windschatten, Pausen. Das ist Absicht.

## Strecken

Die Höhenprofile werden erzeugt, nicht importiert — aber deterministisch:
Derselbe Seed liefert dasselbe Profil, Saison für Saison. Ein Profil ist
eine Folge von Steigungen auf einem 100-Meter-Raster, aufgebaut aus
Blöcken (welliger Zwischenteil, Anstieg, Abfahrt) und anschließend linear
skaliert, bis die Höhenmeter der Vorgabe entsprechen.

| # | Rennen | Distanz | Profil | Höhenmeter |
|---|---|---|---|---|
| 1 | Ostsee-Nachtfahrt | 300 km | flach | 900 |
| 2 | Toskana-Hügelmarathon | 400 km | wellig | 3 600 |
| 3 | Ardennen-Wellenritt | 600 km | wellig | 5 400 |
| 4 | Karpaten-Traverse | 700 km | Mittelgebirge | 10 500 |
| 5 | Pyrenäen-Überquerung | 850 km | Mittelgebirge | 13 000 |
| 6 | Alpen-Hochgebirgsmarathon | 1 000 km | Hochgebirge | 23 000 |

## Zeitrechnung beim Einzelstart

Zwei Uhren, und sie zu verwechseln macht jede Rangliste falsch:

- Die **Rennuhr** läuft ab dem ersten Starter. Sie steuert die
  Wiedergabe und sagt, wann etwas zu sehen war.
- Die **Eigenzeit** eines Fahrers ist die Rennuhr minus seinem
  Startversatz. Sie ist die Wertungsgröße — Splitzeiten, Zielzeiten und
  jede Tabelle rechnen in ihr.

Bei 300 Fahrern im Zehn-Minuten-Takt umfasst allein das Startfenster
knapp **50 Stunden**: Der letzte Starter rollt los, wenn der erste längst
im Ziel ist. Beim Alpen-Rennen läuft die Rennuhr damit über hundert
Stunden — bei 1000× sind das gut sechs Minuten Zuschauen.

**Die Setzliste** folgt den Saisonpunkten aufsteigend: Wer in der Wertung
führt, startet zuletzt und kennt die Zeit, die er schlagen muss. Vor dem
ersten Rennen haben alle null Punkte — dann setzt die relative FTP die
Reihenfolge, und sie trennt auch Punktgleichheit, die bei 300 Fahrern und
Punkten bis Rang 150 die Regel ist, nicht die Ausnahme. Ganz zuletzt
entscheidet die Startnummer, damit die Reihenfolge reproduzierbar bleibt.

Die Setzliste ist dabei die Papierform, nicht das Ergebnis: Sie kennt
Punkte, FTP und Gewicht, aber weder die Tagesform noch das Gelände.

Zwei Wertungen im Board:

- **Splitwertung** — die gemessene Zeit an einer Messstelle. Wer noch
  nicht durch ist, steht mit seiner **laufenden Uhr** da (kursiv): Er
  reiht sich oben ein, solange er die Bestzeit noch schlagen kann, und
  wandert nach unten, sobald seine Uhr eine gefahrene Zeit überholt. So
  steht es an der Strecke, und so steht es hier.

  Die Rangfolge wird deshalb auch **zwischen zwei Bildern** neu sortiert.
  Bei 1000× liegen zwischen zwei Bildern über sechzehn Minuten Rennzeit —
  ohne das stimmte die Tabelle eine ganze Sekunde lang sichtbar nicht.
  Aus demselben Grund laufen Kilometer und Restmeter mit, statt im
  Sekundentakt zu springen. Gerechnet wird dabei nichts: Der Vorlauf ist
  auf das nächste erwartete Bild gedeckelt, genau wie bei der Uhr.

  Die angeheftete Kopfzeile zeigt den Halter der besten **gefahrenen**
  Zeit — auf ihn bezieht sich der Rückstand, und Rang eins ist dort
  regelmäßig jemand, dessen Uhr erst fünf Minuten läuft.
- **Virtuelle Rangliste** — die hochgerechnete Endzeit. Hochgerechnet
  wird über den Schnitt bisher (`t_ziel = t_bisher · s_ziel / s_bisher`),
  nicht über das Momentantempo: Sonst projizierte ein Fahrer am Anstieg
  das Doppelte seiner tatsächlichen Zeit.

## Punkte

Punkte bekommen die **ersten 150** jedes Rennens, zusammen 1142 je
Rennen. Die Ränge eins bis zwanzig stehen von Hand —
100/80/65/55/50/45/40/36/32/28/26/24/22/20/18/16/14/12/10/8 —, danach
läuft eine Kurve von sieben auf eins aus. Sie ist oben steiler als unten:
Zwischen Rang 25 und 35 liegt mehr als zwischen 130 und 140. Der Sockel
von einem Punkt macht aus der Grenze bei 150 einen Auslauf statt einer
Klippe.

Die Teamwertung ist die Summe aller zwölf Fahrer. Punktgleichheit trennen
Siege, dann Podien, dann die beste Einzelplatzierung.

## Teams

Fünfundzwanzig feste Paare aus Ausrüster und Radmarke, wie im echten
Radsport. **Die Marken sind echt, die Teams sind es nicht** — keine der
genannten Firmen hat mit diesem Programm zu tun, sponsert nichts und weiß
nichts davon. Alle Fahrer sind fiktiv; Übereinstimmungen mit realen
Personen sind Zufall.

## Aufbau

```
ultraslim/
  core/
    physics.py   Kräftebilanz, CdA, Rollwiderstand, Luftdichte
    rider.py     Fahrer, Teams, Generator für den Pool
    route.py     Höhenprofile: Generator, Anstiege, Zeitmessungen
    engine.py    die Rennengine — der angehaltene Generator
    season.py    Kalender, Punkte, Wertungen, Speicher
  web/
    rooms.py     laufende Rennen und die Zuschauersitzungen
    main.py      FastAPI: Seiten und Schnittstelle
    static/js/   live.js (Alpine-Komponente), profile.js (Höhenprofil)
```

Kein Node, kein Build-Schritt. Alpine.js liegt als Datei bei.

## Entwicklung

```
pip install -r requirements-dev.txt
pytest -q                                   # 114 Tests
python -m ultraslim.app --no-browser        # Server ohne Browser
```

## Windows-EXE

Ein Tag `v*` baut über GitHub Actions auf `windows-latest` eine
`UltraSimSlim.exe` und hängt sie an das Release:

```
git tag v0.1.0 && git push origin v0.1.0
```

Ohne Tag geht es auch über *Actions → Release → Run workflow*; die EXE
liegt dann als Artefakt am Lauf. Der Build läuft erst nach `pytest` und
startet die fertige EXE einmal zur Probe — ein Build, der nur
„erfolgreich" ist, aber nicht startet, hat schon oft genug ein Release
gekostet.

Lokal auf einem Windows-Rechner:

```
pip install -r requirements-dev.txt
pyinstaller ultraslim.spec --noconfirm --clean
```

Die EXE ist eigenständig: Streckendaten werden beim Start erzeugt, nicht
geladen. Ergebnisse landen in `data/` neben der EXE — ist der Ordner
schreibgeschützt, weicht die Anwendung nach `%USERPROFILE%\UltraSimSlim`
aus.
