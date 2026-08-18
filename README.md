# UltraSim Slim

Ultracycling-Simulator, schlanke Fassung. Ein Fahrer hat genau drei
körperliche Eigenschaften — **FTP, Gewicht, Größe** — und neun Zahlen
von 0 bis 100, die sagen, was er damit anfängt: **Abfahrt**,
**Ausdauer**, **Aerodynamik**, **Kletterprofil**, **Startprofil**,
**Endspurt**, **Rhythmus**, **Verfolgerinstinkt** und
**Höhentoleranz**. Eine Strecke ist ein zweidimensionales Höhenprofil, und
alles andere folgt aus der Physik.

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
- Vier Saisonwertungen: **Punkte**, **Gesamtzeit**, **Berg** und **Teams**.
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

Zielleistung = `FTP · IF · Tagesform · Verfall · Steigungsfaktor · Profil ·
Startprofil · Endspurt · Rhythmus · Höhe · Verfolger · Teamgeist ·
Trittrauschen`, dazu ein Zuschlag auf die FTP aus Schub oder Hungerast
und der Heimvorteil auf die Grundleistung.

- **IF** folgt der Renndistanz: 0,72 bei 300 km, 0,70 bei 400, 0,66 bei
  600, 0,64 bei 700, 0,62 bei 850, 0,60 bei 1000 km.
- **Steigungsfaktor** steigt linear von 1,00 im Flachen auf 1,15 ab 8 %
  und fällt auf 0,55 ab 4 % Gefälle.
- **Tagesform** ist ein Faktor je Fahrer und Rennen, N(1,00; 0,04),
  begrenzt auf 0,88–1,12. Reproduzierbar aus dem Renn-Seed. Sie ist kein
  fester Wert über die Distanz, sondern **schwankt um ihren Startwert**:
  An jeder Messstelle gilt ein neuer Ausschlag von höchstens **±2 %**
  (`FORM_DRIFT`), gezogen vor dem Rennen in eine Tabelle
  Fahrer × Messstelle. Wirksam ist immer der Eintrag der zuletzt
  passierten Messstelle — vor der ersten gilt der Startwert. Weil die
  Tabelle steht und nicht mitgezählt wird, zeigt ein Rücksprung in der
  Wiedergabe denselben Wert wie beim ersten Durchlauf. Im Fokusfeld steht
  der laufende Wert, der Startwert hängt als Titel daran. Gemessen über
  alle sechs Strecken wandert ein Fahrer damit über **3,6 bis 3,8 %**
  seines Startwerts — bei zwanzig Messstellen fast die volle Spanne, weil
  jeder Zug unabhängig ist. Auf die Endzeit wirkt das **im Mittel gar
  nicht** (gemessen ±0,05 min), es verschiebt sie nur: auf der Ostsee um
  0,7 min Streuung (−3,2 … +4,8), auf den Karpaten um 2,8 min (−9,3 …
  +7,3). Genau das war die Absicht — die Reihenfolge an den Messstellen
  soll leben, das Ergebnis soll dadurch nicht zufälliger werden.
- **Trittrauschen** sind zwei langsam wandernde Wellen, zusammen
  höchstens ±2 % — sichtbar in der Wattanzeige, praktisch wirkungslos auf
  die Endzeit.
- Bergab läuft die Leistung über die Trittfrequenz aus: Im größten Gang
  (9,55 m Entfaltung) ist bei 114 rpm Schluss.

### Der Abfahrtswert

Die erste der neun Zahlen, die nicht aus dem Körper folgen. **Bei 100 rollt er ungebremst aus, bei 0 nimmt er die
volle Drosselung mit** — höchstens **15 %** Tempo, hinterlegt als
`DESCENT_THROTTLE_MAX` in `core/physics.py`.

Gebremst wird über den **Widerstand**, nicht über die Watt. Ab 8 %
Gefälle tritt der Fahrer im größten Gang ohnehin leer — dort sind die
Watt schon null, und was null ist, kann man nicht kleiner machen. Wer
15 % langsamer rollen soll, bekommt darum den Luftwiderstand von `1/f²`.
Die Bremsrampe läuft zwischen 2 % und 6 % Gefälle linear hoch; im Flachen
und bergauf ist der Wert wirkungslos.

Die Verteilung ist eine **Beta(2, 2)**, auf 0 bis 100 gestreckt: eine
Glocke um 50, aber breiter als die Normalverteilung (σ ≈ 22 statt 16,5)
und von Haus aus begrenzt — eine abgeschnittene Gaußkurve hätte einen
Klumpen auf 0 und 100 gelegt. Über den Alpenmarathon kostet der
Unterschied zwischen 100 und 0 rund **44 Minuten**, und zwar linear
gestaffelt: 100 → 47,222 h, 75 → 47,388, 50 → 47,564, 25 → 47,749,
0 → 47,948 h.

### Der Ausdauerwert

Die zweite Zahl von 0 bis 100, und die einzige, bei der **50 neutral**
ist: Dort läuft das Rennen exakt so wie ohne sie. Sie verschiebt nicht
die Leistung, sondern ihren **Verlauf** — je länger ein Fahrer unterwegs
ist, desto weiter geht die Schere auf:

```
Verfall(t) = 1 + Spanne(t) · (Ausdauer/100 − 0,5)
Spanne(t)  = min(FADE_SPAN_PER_10H · Eigenzeit / 10 h,  FADE_SPAN_MAX)
```

Mit `FADE_SPAN_PER_10H = 0,06` und `FADE_SPAN_MAX = 0,15` (beide in
`core/engine.py`) trennen nach zehn Stunden sechs Prozent Leistung die
Ausdauer 100 von der Ausdauer 0, ab fünfundzwanzig Stunden fünfzehn.
Bezugsgröße ist die **Eigenzeit**, nicht der Streckenanteil: Damit wirkt
der Wert von allein dort, wo Ausdauer zählt.

Gemessen, ein Fahrer über drei Strecken, sonst alles gleich:

| Strecke | Ausdauer 100 | 50 | 0 | Spanne |
|---|---|---|---|---|
| Ostsee 300 km | 9,251 h | 9,301 | 9,354 | 6 min |
| Karpaten 700 km | 27,010 h | 27,640 | 28,358 | 81 min |
| Alpen 1000 km | 45,715 h | 47,427 | 49,400 | 3 h 41 |

Weil die Verteilung symmetrisch um 50 liegt, bleibt die Eichung der
IF-Tabelle stehen: Das Feld als Ganzes fährt weiterhin dieselben Zeiten.
Im Board zeigt die Spalte **Verfall**, was der Wert bis zu diesem Moment
gemacht hat — die Abweichung von der Leistung, mit der der Fahrer
losgerollt ist.

### Der Aerodynamikwert

Wie sauber ein Fahrer auf dem Rad liegt — die Zahl greift dort an, wo
Luft der Hauptgegner ist:

```
CdA = A · k(Steigung) · (1 − AERO_SPAN · (Aero/100 − 0,5))
```

`AERO_SPAN = 0,10` in `core/physics.py`. Für den Beispielfahrer heißt das
CdA 0,266 bis 0,294 statt 0,280 — Straßenräder im Unterlenker liegen real
zwischen etwa 0,26 und 0,32, der Wert bleibt also innerhalb dessen, was
zwischen einem Fahrer, der vierzig Stunden ruhig liegt, und einem, der
sich ständig aufrichtet, tatsächlich vorkommt.

Gemessen zwischen Aero 100 und Aero 0, ein Fahrer, sonst alles gleich:

| Strecke | 100 | 50 | 0 | Spanne |
|---|---|---|---|---|
| Ostsee 300 km | 9,161 h | 9,303 | 9,442 | 16,9 min (3,03 %) |
| Toskana 400 km | 13,458 h | 13,635 | 13,807 | 21,0 min (2,57 %) |
| Karpaten 700 km | 27,430 h | 27,707 | 27,978 | 32,9 min (1,98 %) |
| Alpen 1000 km | 47,224 h | 47,562 | 47,893 | 40,1 min (1,41 %) |

**Absolut wächst der Effekt mit der Renndauer, relativ fällt er mit den
Höhenmetern.** Je 100 km kostet die Spanne im Flachen 5,6 Minuten, im
Hochgebirge 4,0. Auf der flachen Nachtfahrt ist Aerodynamik damit der
wichtigste der vier Werte, im Hochgebirge der kleinste — genau die
Arbeitsteilung, die gemeint ist: flach → Position, bergab →
Abfahrtswert, lang → Ausdauer, bergauf → W/kg.

### Kletterer und Rouleur

Der einzige Wert, der **nicht** frei gewürfelt wird: Er folgt zu 60 %
dem Gewicht (Rangplatz im Feld) und zu 40 % dem Zufall. Die Korrelation
mit dem Gewicht liegt bei **−0,85** — das leichteste Viertel des Feldes
kommt im Mittel auf Profil 71, das schwerste auf 28. Den leichten
Rouleur gibt es weiterhin, nur selten.

Der Wert **verschiebt** Leistung, er verschenkt keine:

```
Profil = 1 + PROFILE_SPAN · (Profil/100 − 0,5) · (2 · Rampe − 1)
Rampe  = Steigung / 8 %, auf 0…1 begrenzt
```

`PROFILE_SPAN = 0,08` in `core/engine.py`. Ab 8 % Steigung bekommt der
Kletterer die halbe Spanne dazu, im Flachen und bergab gibt er sie ab;
der Angelpunkt liegt bei **4 % Steigung**, dort ist der Faktor für
jeden genau 1,0.

Damit entscheidet zum ersten Mal die **Strecke**, welcher Fahrertyp
gewinnt (Kletterer 100 gegen Rouleur 0, positiv heißt: der Kletterer ist
schneller):

| Strecke | Höhenmeter je km | Kletterer |
|---|---|---|
| Ostsee 300 km | 3 | **−15,1 min** |
| Toskana 400 km | 9 | −14,4 min |
| Ardennen 600 km | 9 | −20,3 min |
| Karpaten 700 km | 15 | +1,0 min |
| Pyrenäen 850 km | 15 | +1,1 min |
| Alpen 1000 km | 23 | **+81,3 min** |

Über die ganze Saison bleiben dem Kletterer rund **34 Minuten** — drei
Rennen gehen an den Rouleur, zwei sind ausgeglichen, und das
Hochgebirge entscheidet die Gesamtwertung. Anders als bei Aerodynamik
und Ausdauer ist der Wert also **nicht** von selbst zeitneutral: Die
Empfindlichkeit von Leistung auf Zeit ist am Berg mehr als doppelt so
hoch wie im Flachen. Das ist Absicht, nicht Nachlässigkeit — der Zweck
des Werts ist, dass die Strecke entscheidet.

### Startprofil und Endspurt

Die vier Werte davor sagen, **wo** ein Fahrer stark ist. Diese beiden
sagen, **wann** — und sie sind die ersten, die den Verlauf eines Rennens
verändern, ohne die Endzeit zu bestimmen.

**Startprofil**, symmetrisch um 50, Bezugsgröße ist der Streckenanteil:

```
Startprofil = 1 + START_PROFILE_SPAN · (Start/100 − 0,5) · (1 − 2 · Anteil)
```

Bei 100 rollt der Fahrer mit der halben Spanne über seiner Zielleistung
los und liegt am Ziel ebenso weit darunter, bei 0 umgekehrt; bei der
Hälfte der Strecke kreuzen sich beide. Über die Distanz gemittelt hebt
sich der Faktor exakt auf. `START_PROFILE_SPAN = 0,08`.

Der Streckenanteil ist bewusst gewählt: Er ist exakt bekannt, ohne
irgendetwas über die Restdauer annehmen zu müssen — für eine Engine, die
nichts vorberechnet, ist das der Unterschied zwischen einer Zahl und
einer Vermutung.

Gemessen, Schnellstarter (100) gegen Diesel (0):

| Strecke | bei ¼ | bei ½ | im Ziel |
|---|---|---|---|
| Ostsee 300 km | 3,3 min | 4,4 min | **0,1 min** |
| Karpaten 700 km | 14,7 min | 19,6 min | **0,2 min** |
| Alpen 1000 km | 30,1 min | 40,9 min | **3,2 min** |

Genau das war die Absicht: Die Zwischenwertung steht auf dem Kopf, das
Ergebnis nicht. Die drei Minuten auf dem Alpenmarathon sind der Rest,
den die Umverteilung übrig lässt, weil dort die zweite Hälfte anderes
Gelände hat als die erste — über die Distanz ist der Faktor neutral,
über die *Zeit* nicht ganz.

**Endspurt**, als einziger Wert einseitig — 0 heißt wirklich null:

```
Rampe    = clip((Anteil − 0,80) / 0,20, 0, 1)
Endspurt = 1 + FINISH_KICK_MAX · (Spurt/100) · Rampe
```

Er greift erst auf dem letzten Fünftel der Distanz und ist erst auf der
Ziellinie voll da. `FINISH_KICK_MAX = 0,10`. Vor km 240 einer
300-km-Strecke ist er nachweislich wirkungslos — die Zwischenzeiten bei
¼ und ½ sind auf die Hundertstelminute identisch.

| Strecke | Spurt 100 gegen 0 |
|---|---|
| Ostsee 300 km | 2,1 min |
| Karpaten 700 km | 8,2 min |
| Alpen 1000 km | 14,9 min |

### Der Rhythmuswert

Die einzige Eigenschaft, die an einer Streckengröße hängt, für die es
vorher **keine Zahl gab**: der Unruhe. Ein 600-km-Wellenritt mit 5400
Höhenmetern in vierhundert kurzen Rampen und dieselben 5400 Meter in
vier langen Anstiegen waren im Modell bis dahin dasselbe.

**Die Unruhe ist die Antrittsdichte**: wie oft die Steigung in einem
Fenster von zehn Kilometern die Schwelle von drei Prozent von unten nach
oben kreuzt, je Kilometer, normiert auf 0 bis 1 (Referenz 0,3 je km).

Der naheliegende erste Versuch — die *Streuung* der Steigung — ist
gemessen und verworfen worden: Über die sechs Kalenderstrecken liegt sie
zwischen 0,68 und 1,02 Prozentpunkten, zwischen der flachen Ostsee und
dem Hochgebirge also Faktor 1,5. Sie hätte einen Wert ergeben, der
überall gleich viel kostet — eine Steuer, keine Streckeneigenschaft. Die
Antrittsdichte trennt um Faktor sieben und in der richtigen Form:

| Strecke | hm/km | mittlere Unruhe |
|---|---|---|
| Toskana 400 km | 9 | **0,58** |
| Ardennen 600 km | 9 | 0,43 |
| Pyrenäen 850 km | 15 | 0,28 |
| Ostsee 300 km | 3 | 0,27 |
| Karpaten 700 km | 15 | 0,21 |
| Alpen 1000 km | 23 | **0,09** |

Oben steht der Wellenritt, unten die flache Strecke (deren Kräusel die
drei Prozent nie erreichen) **und** das Hochgebirge (wenige, sehr lange
Anstiege). Genau die Buckelform, die „welliges Gelände" meint.

Gewirkt wird einseitig, als Abzug — bei 100 kostet Unruhe nichts, bei 0
das Maximum, und auf glatter Strecke niemanden:

```
Rhythmus = 1 − RHYTHM_MAX · (1 − Rhythmus/100) · Unruhe(x)
```

`RHYTHM_MAX = 0,06` in `core/engine.py`. Gemessen zwischen 100 und 0:

| Strecke | Spanne | Anteil der Fahrzeit |
|---|---|---|
| Ostsee 300 km | 3,7 min | 0,66 % |
| Toskana 400 km | 17,4 min | **2,13 %** |
| Ardennen 600 km | 22,7 min | 1,80 % |
| Karpaten 700 km | 23,0 min | 1,38 % |
| Pyrenäen 850 km | 37,8 min | 1,83 % |
| Alpen 1000 km | 18,1 min | 0,63 % |

Im Fokusfenster steht der Wert in einer Zeile mit dem, was ihn erklärt:
`RHYTHMUS 58 · UNRUHE 0,33 · BRUCH −0,8 %` — die Eigenschaft, das
Gelände an dieser Stelle und der Abzug, der daraus gerade folgt.

Weil der Wert ein reiner Abzug ist, dauern wellige Strecken im Mittel
gut ein Prozent länger als vor seiner Einführung. Das ist der Preis der
Einseitigkeit und bewusst so gewählt.

### Energiegeladen

Das einzige **Ereignis** im Modell — alles andere folgt aus Eigenschaften
und Gelände. An jeder Zeitmessung kann ein Fahrer mit **1 %**
Wahrscheinlichkeit einen Schub bekommen, der bis zur **nächsten**
Messstelle hält: **10 bis 50 Watt auf die FTP**, gleichverteilt gezogen.

Der Gewinn liegt auf der FTP, nicht auf der Tretleistung — er geht also
denselben Weg wie sie, mal Intensitätsfaktor und Tagesform. Aus 50 W FTP
werden so rund 33 W am Pedal.

**Die dreißig stärksten Fahrer des Feldes nach relativer FTP kann es
nicht treffen.** Ein Zufallsgeschenk soll das Rennen aufmischen, nicht
den Favoriten noch weiter nach vorn tragen.

Über zwanzig Renn-Seeds kommen im Mittel **52 Schübe je Rennen** vor
(35 bis 66), verteilt auf rund fünfzig verschiedene Fahrer.

Was einer wert ist, hängt daran, wo er anspringt — gemessen an einem
Fahrer mit 227 W FTP:

| Abschnitt | +10 W | +30 W | +50 W |
|---|---|---|---|
| Ostsee, 15 km flach | 29 s | 80 s | 126 s |
| Karpaten, 8 km mit 5,1 % | 81 s | 215 s | **333 s** |
| Karpaten, 13,7 km Abfahrt | 4 s | 13 s | 27 s |

Am Berg zählt jedes Watt fast eins zu eins, im Flachen mit der dritten
Wurzel, und in der Abfahrt fast gar nicht — dort tritt der Fahrer
ohnehin kaum. Das ist keine Sonderregel, sondern fällt aus der Physik
heraus.

**Kein neuer veränderlicher Zustand.** Die Auslösung steht in einer
Tabelle je Fahrer und Messstelle, einmal aus dem Renn-Seed gezogen —
Würfelwerk wie die Tagesform, und wirksam wird ein Eintrag erst, wenn
der Fahrer die Messstelle tatsächlich erreicht. Was gerade gilt, hängt
allein an der Zahl der passierten Messstellen. Damit stimmt der Zustand
auch nach einem Rücksprung in der Wiedergabe, ohne dass er
mitgeschrieben werden müsste.

Sichtbar wird der Schub als Chip neben dem Namen (`energiegeladen
+24 W`), als eigene Ticker-Gruppe und als sortierbare Board-Spalte.

### Hungerast

Das Spiegelbild des Schubs, gleiche Mechanik, umgekehrtes Vorzeichen:
**0,1 %** je Zeitmessung — ein Zehntel der Schubwahrscheinlichkeit — und
**10 bis 40 Watt Abzug** auf die FTP bis zur nächsten Messstelle. Drei
Unterschiede:

- Die Wahrscheinlichkeit **wächst mit der Fahrzeit** — nach fünfzehn
  Stunden auf der eigenen Uhr ist sie doppelt so hoch. Damit fällt der
  Wurf erst beim Durchfahren, nicht vorher: Gespeichert ist der Würfel,
  entschieden wird an der Messstelle, und reproduzierbar bleibt es
  trotzdem, weil beides aus der Splitzeit folgt.
- Verschont sind die **dreißig schwächsten** Fahrer statt der stärksten.
- Die niedrige Grundwahrscheinlichkeit macht ihn zum **Einschlag statt
  zur Begleiterscheinung**. Der Zeitfaktor verdoppelt die Rate über die
  langen Distanzen; bei einem Prozent überwog das Pech dadurch dauerhaft
  das Glück.

| Wahrscheinlichkeit | Ostsee (9 h) | Alpen (48 h) |
|---|---|---|
| 1,0 % | 82 gegen 50 Schübe | 218 gegen 89 |
| 0,5 % | 44 gegen 50 | 108 gegen 89 |
| **0,1 %** | **6 gegen 50** | **23 gegen 89** |

Bei einem Zehntelprozent trifft es in einem Rennen mit dreihundert
Startern eine Handvoll Fahrer — selten genug, dass eine Meldung im
Ticker wirklich etwas heißt.

### Materialschaden

Als einziges Ereignis **vor dem Rennen** gewürfelt: 2 % je Fahrer, also
rund sechs im Feld. Wo genau, liegt zwischen 5 % und 95 % der Distanz.
Der Halt kostet **30 bis 180 Sekunden** Standzeit; danach rollt der
Fahrer auf dem Ersatzrad weiter, mit `Crr + 0,0005` bis ins Ziel.

Der Fahrer steht wirklich: Tempo null, Leistung null, Distanz
unverändert. Der Zeitpunkt des Halts wird festgehalten wie eine
Splitzeit — eine Tatsache, kein laufender Zähler, damit der Rücksprung
stimmt.

### Verfolgerinstinkt

Der erste Wert, der die **Rangliste liest**. An einer Messstelle sieht
der Fahrer, wie weit er hinter dem Nächstbesseren liegt, der dort schon
durch ist. Unter **60 Sekunden** drückt er bis zur nächsten Messstelle,
und zwar linear stärker, je näher er dran ist — bei null Rückstand die
vollen 4 %.

Einseitig: Bei 0 lässt ihn das kalt, bei 100 reagiert er am stärksten.
Beim Einzelstart gibt es keine Duelle auf der Straße; dieser Wert
erzeugt sie in der Rangliste. Gemessen kommt die Lage in einem Rennen
rund viertausendmal vor.

Der Rückstand wird beim Durchfahren **festgehalten**: Später ließe er
sich nicht mehr rekonstruieren, weil dann mehr Fahrer durch sind als in
dem Moment.

### Teamgeist

Kein Fahrerwert, sondern eine Lage: Wessen Teamkollege bei der letzten
Messstelle die Bestzeit hielt, tritt bis zur nächsten **2 %** fester.
Das koppelt die Teamwertung erstmals ans Renngeschehen, statt sie nur
am Ende zu summieren. Kommt je Rennen etwa 350-mal vor.

### Heimvorteil

Jede erzeugte Strecke hat Gastgebernationen; ihre Fahrer bekommen
**1,5 %** auf die Zielleistung.

| Strecke | Gastgeber | betroffene Fahrer |
|---|---|---|
| Ostsee | GER, NED | 78 |
| Toskana | ITA | — |
| Ardennen | BEL, NED | — |
| Karpaten | AUT | — |
| Pyrenäen | *keine* | 0 |
| Alpen | AUT, SUI, ITA, GER | 168 |

Die Pyrenäen liegen in keinem Land, das im Feld vertreten ist — dort
gibt es keinen Heimvorteil, und das ist ehrlicher, als eine Nation
dazuzuerfinden. Importierte GPX-Strecken wissen nicht, wo sie liegen;
dort wirkt der Wert bei niemandem.

### Duelle

Vor **jedem** Rennen werden **drei Paare** ähnlich starker Fahrer
gebildet — in der Rangfolge der relativen FTP direkt benachbart, also
mit weniger als ein paar Hundertstel W/kg Unterschied. Jeder der sechs
bekommt **0,5 bis 1,5 Prozent** Aufschlag auf die Tagesform.

Die Paare werden aus dem Renn-Seed gezogen: In jedem Rennen andere,
über die Saison also andere Geschichten. Im Ticker steht das Duell,
sobald der Erste der beiden losrollt.

### Höhentoleranz

Die **Luftdichte** fällt schon mit der Höhe — sie steht in der
Kräftebilanz und macht den Fahrer dort oben sogar schneller. Was
fehlte, ist der physiologische Preis: Über tausend Metern kommt weniger
Sauerstoff an.

Der Abzug blendet zwischen **1000 m und 2500 m** linear ein, bis zu
**8 %** bei Toleranz 0; bei 100 kostet die Höhe nichts. Von den sechs
Strecken erreicht nur der Alpenmarathon die Einsatzhöhe nennenswert
(52 % der Strecke über 1000 m, höchster Punkt 2542 m), Karpaten und
Pyrenäen streifen sie auf gut einem Prozent. Das ist gewollt: Ein
Höhenwert, der im Flachland wirkt, wäre keiner.

Was es **nicht** gibt: W′-Bilanz, Verpflegung, Schlaf, Wetter, Wind,
Defekte, Stürze, Taktik, Windschatten, Pausen — und keine
Geschwindigkeitsgrenze in der Abfahrt außer der, die der Abfahrtswert
setzt. Das ist Absicht.

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

**Die Setzliste** folgt den Saisonpunkten absteigend: Rang eins der
Wertung ist der Gesetzte. Vor dem ersten Rennen haben alle null Punkte —
dann setzt die relative FTP die Reihenfolge, und sie trennt auch
Punktgleichheit, die bei 300 Fahrern und Punkten bis Rang 150 die Regel
ist, nicht die Ausnahme. Ganz zuletzt entscheidet die Startnummer, damit
die Reihenfolge reproduzierbar bleibt.

Die Setzliste ist dabei die Papierform, nicht das Ergebnis: Sie kennt
Punkte, FTP und Gewicht, aber weder die Tagesform noch das Gelände.

**Die Startgruppen** verteilen diese Rangliste in drei Blöcke — das Feld
wird gedrittelt, bei 300 Fahrern also 100/100/100:

| Rang in der Setzliste | Startplätze | Reihenfolge |
|---|---|---|
| 1–100 (die Gesetzten) | 101–200 | Rang 1 zuerst |
| 101–200 | 1–100 | rückwärts, Rang 200 zuerst |
| 201–300 | 201–300 | Rang 201 zuerst |

Die Gesetzten starten damit **in der Mitte** statt am Ende: Vor ihnen
liegt das Mittelfeld, das die Zeiten vorlegt, hinter ihnen das
Schlussdrittel, das die letzten gut sechzehn Stunden des Startfensters
füllt. Ein Sieger fährt so nicht mehr zwangsläufig gegen ein bereits
komplettes Ergebnis, und die Zwischenwertung bleibt bis zum Schluss in
Bewegung.

### Wo gemessen wird

Zeitmessungen liegen **alle 5 % der Distanz** — und zusätzlich auf jedem
**Gipfel** eines Anstiegs der Kategorien HC, 1 und 2. Fällt ein Gipfel
ohnehin fast auf einen Rasterpunkt (weniger als 2 km daneben, und
höchstens 40 % des Rasterabstands), ersetzt er ihn, statt eine zweite
Messstelle daneben zu setzen.

Auf einer flachen Strecke sind das genau zwanzig Messstellen, im
Hochgebirge fünfunddreißig — achtzehn davon Gipfel.

| Strecke | Messstellen | davon Gipfel |
|---|---|---|
| Ostsee, Toskana, Ardennen | 20 | – |
| Karpaten | 29 | 9 |
| Pyrenäen | 31 | 12 |
| Alpen | 35 | 18 |

Zwei Wertungen im Board:

- **Splitwertung** — die gemessene Zeit an einer Messstelle. Wer noch
  nicht durch ist, steht mit seiner **laufenden Uhr** da (kursiv): Er
  reiht sich oben ein, solange er die Bestzeit noch schlagen kann, und
  wandert nach unten, sobald seine Uhr eine gefahrene Zeit überholt. So
  steht es an der Strecke, und so steht es hier.

  Solange seine Uhr die **Bestzeit noch nicht erreicht** hat, steht er
  ganz oben — und dort untereinander **nach der Entfernung zur
  Messstelle**, der Nächste zuerst. Das ist die einzige Reihenfolge, die
  in diesem Moment etwas aussagt: Zwei Uhren bei zwei Stunden sagen
  nichts, aber zwei Kilometer gegen dreißig sagen alles. Überholt die Uhr
  die Bestzeit, fällt er in die gewohnte Sortierung nach Zeit zurück.

  Wer noch keinen Rang hat, steht **hervorgehoben** — dieselbe
  Zeilenfarbe wie der Fokusfahrer, nur ohne dessen Balken. Man sieht auf
  einen Blick, wer sich noch einranken muss. Die Markierung erlischt
  nicht in dem Moment, in dem er durchfährt, sondern **fünf Spielminuten
  danach**: Genau die Zeile, die eben ihren Platz gefunden hat, bleibt
  noch kurz sichtbar. Gerechnet wird das aus der aufgezeichneten
  Splitzeit, nicht aus einem mitlaufenden Zähler — ein Rücksprung zeigt
  darum dieselbe Markierung wie der erste Durchlauf.

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
  auf das nächste erwartete Bild gedeckelt, genau wie bei der Uhr. Die
  **Restmeter zählen dabei auch für die Sortierung mit** — sonst sortierte
  der Kopf der Tabelle nach einem sechzehn Minuten alten Stand, während
  die Spalte daneben schon den neuen zeigt.

  Eine **Rangziffer trägt nur, wer die Messstelle gefahren hat.** Die
  laufenden Uhren reihen sich weiter live zwischen die gemessenen Zeiten
  ein, stehen dort aber mit einem Strich: 1, 2, –, 3. Der Rang gehört zur
  Zeit, nicht zur Tabellenzeile, und wechselt darum nicht den Besitzer,
  nur weil eine fremde Uhr weiterläuft.

  Die Splitwertung zeigt **das ganze gewertete Feld**, nicht den
  Vierzig-Zeilen-Ausschnitt der virtuellen Rangliste: Sie ist eine
  Ergebnisliste, und wer bei Rang 180 steht, will dort auch stehen. Die
  Spaltenköpfe bleiben beim Scrollen kleben.

  Die angeheftete Kopfzeile zeigt den Halter der besten **gefahrenen**
  Zeit — auf ihn bezieht sich der Rückstand, und Rang eins ist dort
  regelmäßig jemand, dessen Uhr erst fünf Minuten läuft.

  Die Spalte **Rg −1** ist der Platz an der Messstelle davor — in der
  Splitwertung für alle dieselbe, sodass die Trendspalte daneben genau
  die Differenz ist. Wer die Messstelle davor noch nicht passiert hat,
  bekommt auch dort keine Ziffer.
- **Bergwertung** — die Auffahrtsdauer eines Anstiegs. Dieselbe
  Live-Zeitnahme wie am Split, nur beginnt die Uhr am Fuß des Berges;
  gewertet wird, wer den Fuß erreicht hat. Dazu die VAM: Höhenmeter je
  Stunde, für eine laufende Auffahrt aus der **bis dahin gewonnenen**
  Höhe — wer ein Drittel oben ist, hat auch erst ein Drittel geklettert.
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

## Bergwertung

Jeder kategorisierte Anstieg wird an beiden Enden gestoppt. Am Gipfel
gibt es Punkte nach Kategorie:

| Kategorie | Punkte |
|---|---|
| HC | 20/15/12/10/8/6/4/2 |
| 1. Kat. | 10/8/6/4/2/1 |
| 2. Kat. | 5/3/2/1 |
| 3. Kat. | 2/1 |
| 4. Kat. | 1 |

Die Tabelle fällt schmal aus, und das ist keine Schwäche: Am Berg
entscheidet Watt je Kilogramm, und die besten Kletterer eines Feldes von
dreihundert machen die Gipfel unter sich aus. Genau dafür gibt es die
Wertung — sie beantwortet eine andere Frage als die Gesamtzeit.

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
pytest -q                                   # 263 Tests
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
