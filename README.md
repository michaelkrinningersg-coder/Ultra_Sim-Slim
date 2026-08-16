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
- Drei Saisonwertungen: **Punkte**, **Gesamtzeit** und **Teams**.
- **Eigene GPX-Dateien** importieren und daraus eigene Saisons bauen.

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

### Watt je Kilogramm am Berg

Die im Radsport gebräuchliche Näherung für die Steiggeschwindigkeit
lautet `W/kg = VAM / (200 + 10 · Steigung in Prozent)`. Das Modell trifft
sie über Steigungen von 6 bis 10 % und 3,5 bis 6,0 W/kg auf **unter neun
Prozent** genau, an steilen Anstiegen auf unter vier — und die Abweichung
hat das richtige Vorzeichen: Zum schwachen Ende hin liegt das Modell
darüber, zum starken darunter. Die Näherung ist linear in W/kg, die
Physik ist es nicht, weil der Luftwiderstand mit `v³` wächst. Ein Modell
ohne diese Krümmung hätte den Luftwiderstand am Berg vergessen.

| W/kg | Modell (8 %) | Näherung | Abw. |
|---|---|---|---|
| 3,5 | 1034 m/h | 980 | +5,5 % |
| 4,5 | 1296 m/h | 1260 | +2,9 % |
| 5,5 | 1542 m/h | 1540 | +0,1 % |
| 6,5 | 1770 m/h | 1820 | −2,8 % |

Bei gleichen W/kg klettern 52 und 88 Kilogramm innerhalb von 5,6 Prozent
gleich schnell — der Rest ist der Rahmen: 7,5 kg sind beim leichten
Fahrer vierzehn Prozent Zusatzmasse, beim schweren achteinhalb.

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

## Eigene Strecken aus GPX

Unter *Strecken* lässt sich eine GPX-Datei hochladen. Daraus wird dieselbe
Sorte Profil, die auch der Generator liefert: Steigungen auf einem
Hundert-Meter-Raster. Unter *Editor* werden mehrere davon zu einem
eigenen Kalender zusammengestellt, der neben den mitgelieferten Saisons
steht — mit demselben Feld und denselben Wertungen.

### Die Glättung ist der eigentliche Schritt

Rohe GPX-Höhen schwanken um ein bis drei Meter von Punkt zu Punkt. Über
zehntausend Punkte summiert sich das zu Höhenmetern, die es nie gab — und
im Modell ist das nicht nur eine falsche Zahl, sondern falsche Physik:
**Jeder erfundene Meter kostet den Fahrer echte Energie.**

Gemessen an einem erzeugten Profil mit bekannten 2400 Höhenmetern, aus dem
eine GPX-Datei mit realistischem Rauschen gebaut wurde:

| Rauschen | roh | nach Glättung (200 m) |
|---|---|---|
| ±0 m | 2400 | 2373 |
| ±1 m | 7314 | 2379 |
| ±2 m | 13 872 | 2391 |
| ±4 m | 27 316 | 2433 |

Der Regler beim Import stellt die Fensterbreite in Metern Wegstrecke und
zeigt sofort, was sie kostet; 200 m entsprechen ungefähr dem, was Strava
und Komoot anzeigen. Wahlweise lässt sich die Höhenmeterzahl auch fest
vorgeben — dann skaliert der Import das geglättete Profil linear darauf.

Steigungen werden bei 25 % gedeckelt: Auch nach der Glättung bleibt in
GPX-Dateien einzelne Ausreißer stehen — ein Tunnel, ein Brückenpfeiler,
ein Sprung im Höhenmodell.

## Wo das liegt

Alles neben dem Programm, alles überlebt den Neustart:

```
data/routes/<kennung>.json.gz    importierte Profile (gepackt, ~30 kB je 1000 km)
data/seasons/<kennung>.json      eigene Kalender
data/results/<saison>/*.json     Ergebnisse
```

Gespeichert wird die **Steigung**, nicht die Höhe: Sie ist das, womit die
Physik rechnet, und die Höhe folgt daraus durch Aufsummieren. Die
GPX-Datei selbst wird nicht aufgehoben — nach dem Import ist sie
überflüssig und um ein Vielfaches größer.

## Erzeugte Strecken

Die mitgelieferten Höhenprofile werden erzeugt, nicht importiert — aber
deterministisch:
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

  In der Wertung steht dabei nur, wer die **vorherige** Messstelle schon
  hinter sich hat; bei der ersten genügt der Start. Ohne diese Schranke
  stand die Tabellenspitze dauerhaft voll mit Fahrern, die vor fünf
  Minuten losgerollt sind — alle zehn Minuten kommt einer dazu, seine Uhr
  steht bei fast null, und die beste gefahrene Zeit rutscht auf Rang
  achtzehn.

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

## Gesamtwertung nach Zeit

Die zweite Art, eine Saison zu gewinnen: die addierten Fahrzeiten aller
gefahrenen Rennen. Die Punktewertung ist gnädig — wer ein Rennen
verliert, verliert höchstens hundert Punkte. Die Zeit addiert stur, und
eine schlechte Nacht auf tausend Kilometern kostet zwei Stunden, die kein
späteres Rennen zurückgibt. Beide Wertungen können auseinanderlaufen, und
genau dafür gibt es die zweite.

Gewertet wird nur, wer in **allen** bislang gefahrenen Rennen eine Zeit
hat; die übrigen stehen dahinter. Ohne diese Regel führte jeder, der nur
das kürzeste Rennen bestritten hat.

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
    gpx.py       GPX einlesen, glätten, in ein Profil verwandeln
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
pytest -q                                   # 177 Tests
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
