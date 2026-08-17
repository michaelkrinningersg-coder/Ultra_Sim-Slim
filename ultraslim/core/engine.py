"""Die Rennengine: ein Rennen, das entsteht, während man zusieht.

Das Rennen wird **nie vorberechnet**. Die Engine ist ein angehaltener
Generator, der genau so weit gezogen wird, wie die Uhr des Zuschauers
steht. Was nicht gerechnet ist, kann auch nicht verraten werden — die
Zusage „keine Daten aus der Zukunft" ist damit keine Zusage, sondern
eine Tatsache über den Programmzustand.

Rückwärts blättern geht trotzdem: Alle dreißig Sekunden Rennzeit legt
die Engine einen Schnappschuss der Positionen ab. Das ist Erinnerung,
keine Vorausberechnung.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import physics
from .rider import Rider, Team
from .route import Route

#: Zeitschritt der Integration. Eine Sekunde ist fein genug, dass der
#: Euler-Schritt an einer 15-%-Rampe stabil bleibt, und grob genug, dass
#: ein 1000-km-Rennen in wenigen Sekunden Rechenzeit durchläuft.
DT = 1.0

#: So viele Ticks rechnet der Generator, bevor er das nächste Mal
#: anhält. Bei 1000-fachem Zeitraffer und einem Bild je Sekunde sind das
#: hundert Halte je Bild — fein genug, um die Uhr nicht zu überspringen.
TICKS_PER_YIELD = 10

#: Abstand der Positions-Schnappschüsse in Sekunden Rennuhr.
#:
#: Eine Minute reicht: Sie ist die Auflösung, mit der man *zurück*
#: blättern kann, und selbst bei 1000-fachem Zeitraffer deckt ein Bild
#: je Sekunde tausend Sekunden ab. Bei fünfzig Stunden Startfenster plus
#: fünfzig Stunden Rennen macht der Unterschied zu dreißig Sekunden rund
#: fünfzehn Megabyte aus.
HISTORY_INTERVAL_S = 60.0

#: Intensitätsfaktor nach Renndistanz: Anteil der FTP, den ein Fahrer
#: über die volle Distanz hält. Zwischen den Stützstellen wird linear
#: interpoliert, außerhalb gehalten.
#:
#: Die Werte sind an dem orientiert, was Ultrafahrer über solche
#: Distanzen tatsächlich treten: knapp drei Viertel der Schwelle über
#: zehn Stunden, gut die Hälfte über anderthalb Tage.
IF_BY_KM: tuple[tuple[float, float], ...] = (
    (300.0, 0.72),
    (400.0, 0.70),
    (600.0, 0.66),
    (700.0, 0.64),
    (850.0, 0.62),
    (1000.0, 0.60),
)

#: Steigungsmodulation der Zielleistung. Am Anstieg wird gedrückt, aber
#: nicht gesprengt; bergab läuft die Leistung zurück.
CLIMB_GRADE_FULL = 0.08     # ab hier voller Aufschlag
CLIMB_POWER_GAIN = 0.15     # +15 %
DESCENT_GRADE_FULL = 0.04   # ab hier voller Abschlag
DESCENT_POWER_LOSS = 0.45   # −45 %, also 0,55×

#: Tagesform: ein Faktor je Fahrer und Rennen auf die FTP.
FORM_SD = 0.04
FORM_RANGE = (0.88, 1.12)

#: Der Ausdauerwert, in Zahlen. Er verschiebt nicht die Leistung, er
#: verschiebt ihren **Verlauf**: Je länger ein Fahrer unterwegs ist,
#: desto weiter geht die Schere zwischen den Ausdauernden und den
#: Verfallenden auf.
#:
#: ``FADE_SPAN_PER_10H`` ist die Spanne zwischen Ausdauer 0 und 100 nach
#: zehn Stunden Eigenzeit, ``FADE_SPAN_MAX`` der Deckel darauf — ohne
#: ihn triebe ein Vierzig-Stunden-Rennen den Effekt ins Absurde. Ein
#: Fahrer mit 50 bleibt in jeder Renndauer bei genau 1,0; die Verteilung
#: ist symmetrisch um 50, damit die IF-Tabelle geeicht bleibt.
#:
#: Was die beiden Zahlen kosten, in Endzeitunterschied zwischen 0 und
#: 100: rund 6 Minuten auf der flachen Nachtfahrt, gut eine Stunde auf
#: der Karpaten-Traverse, gut zwei auf dem Alpenmarathon.
FADE_SPAN_PER_10H = 0.06
FADE_SPAN_MAX = 0.15
FADE_REFERENCE_S = 10.0 * 3600.0

#: Spanne des Kletterprofils auf die Zielleistung, zwischen Kletterer
#: und Rouleur. Sie wirkt in beide Richtungen: Wer am Anstieg die halbe
#: Spanne dazubekommt, gibt sie im Flachen ab.
#:
#: Anders als bei Aerodynamik und Ausdauer ist das **nicht** von selbst
#: zeitneutral: Die Empfindlichkeit von Leistung auf Zeit ist am Berg
#: mehr als doppelt so hoch wie im Flachen. Wer am Berg drückt, gewinnt
#: unterm Strich also etwas — auf flachen Strecken kehrt sich das um.
#: Genau das ist der Zweck: Die Strecke soll entscheiden, welcher Typ
#: gewinnt.
PROFILE_SPAN = 0.08

#: Spanne des Startprofils zwischen Schnellstarter und Diesel, je Ende
#: der Distanz. Der Schnellstarter rollt mit der halben Spanne über
#: seiner Zielleistung los und liegt am Ziel ebenso weit darunter, der
#: Diesel umgekehrt.
#:
#: Bezugsgröße ist der **Streckenanteil**, nicht die Zeit: Er ist exakt
#: bekannt, ohne irgendetwas über die Restdauer annehmen zu müssen. Über
#: die Distanz gemittelt hebt sich der Faktor auf — der Wert verschiebt,
#: wo im Rennen ein Fahrer stark ist, nicht wie stark er insgesamt ist.
START_PROFILE_SPAN = 0.08

#: Endspurt. Anders als alles andere einseitig: Bei 0 passiert nichts,
#: bei 100 tritt der Fahrer am Ziel ``FINISH_KICK_MAX`` über seiner
#: Zielleistung. Er blendet über das letzte Fünftel der Distanz linear
#: ein und ist erst auf der Ziellinie voll da.
FINISH_KICK_START = 0.80
FINISH_KICK_MAX = 0.10

#: Rhythmusbruch. Die Streckengröße dahinter ist die **Antrittsdichte**:
#: wie oft die Steigung in einem Fenster von zehn Kilometern die
#: Schwelle von drei Prozent von unten nach oben kreuzt, je Kilometer.
#:
#: Warum nicht die Streuung der Steigung, die zuerst naheliegt: Sie
#: unterscheidet die Strecken kaum. Über die sechs Kalenderstrecken
#: liegt sie zwischen 0,68 und 1,02 Prozentpunkten — die flache Ostsee
#: und das Hochgebirge trennt Faktor 1,5, weil jede erzeugte Strecke
#: dieselbe feine Welligkeit trägt. Die Antrittsdichte trennt um Faktor
#: sieben und in der richtigen Form: Der Wellenritt steht oben, die
#: flache Strecke (deren Kräusel die drei Prozent nie erreichen) und
#: das Hochgebirge (wenige, lange Anstiege) stehen unten.
#:
#: Mittlere Unruhe der Kalenderstrecken bei ``RHYTHM_REFERENCE``:
#: Toskana 0,58 · Ardennen 0,43 · Pyrenäen 0,28 · Ostsee 0,27 ·
#: Karpaten 0,21 · Alpen 0,09.
RHYTHM_THRESHOLD = 0.03
RHYTHM_WINDOW_M = 10_000.0
RHYTHM_REFERENCE = 0.3      # Antritte je Kilometer für Unruhe 1
#: Einseitig, als Abzug: Bei Rhythmus 100 kostet unruhiges Gelände
#: nichts, bei 0 die volle Spanne — und auf glatter Strecke niemanden.
RHYTHM_MAX = 0.06

#: „Energiegeladen": An jeder Zeitmessung kann ein Fahrer mit dieser
#: Wahrscheinlichkeit einen Schub bekommen, der bis zur nächsten
#: Messstelle hält. Der Gewinn liegt auf der **FTP** — was davon als
#: Tretleistung ankommt, ist der Intensitätsfaktor mal Tagesform davon,
#: also gut zwei Drittel.
#:
#: Bei einem Prozent, zwanzig Messstellen und 270 möglichen Fahrern sind
#: das rund fünfzig Ereignisse je Rennen — selten genug, dass es eine
#: Meldung wert ist, häufig genug, dass es vorkommt.
ENERGY_EVENT_P = 0.01
ENERGY_BONUS_W = (10.0, 50.0)
#: Wen es nicht treffen kann: die stärksten Fahrer des Feldes nach
#: relativer FTP. Ein Zufallsgeschenk soll das Rennen aufmischen, nicht
#: den Favoriten noch weiter nach vorn tragen.
ENERGY_EXCLUDE_TOP = 30

#: Rauschen im Tritt. Zwei langsam wandernde Wellen, deren Summe
#: höchstens zwei Prozent ausmacht — sichtbar in der Wattanzeige,
#: praktisch wirkungslos auf die Endzeit.
NOISE_AMP_SLOW = 0.014
NOISE_AMP_FAST = 0.006
NOISE_PERIOD_SLOW = (90.0, 190.0)
NOISE_PERIOD_FAST = (22.0, 45.0)

#: So viele Fahrer je Zeitmessung schaffen es in den Ticker. Bei
#: dreihundert Startern und vierzehn Messstellen wären das sonst
#: viertausend Meldungen für ein Laufband, das zehn zeigt.
TICKER_SPLIT_LIMIT = 10

#: Punkte der Bergwertung je Kategorie und Rang am Gipfel.
#:
#: Die Staffelung folgt der Radsportkonvention: Ein Hors-Catégorie-Pass
#: ist mehr wert als vier Hügel vierter Kategorie zusammen, und die
#: Punkte reichen tiefer ins Feld, je größer der Berg. Anders als bei
#: der Etappenwertung geht es hier nicht darum, das ganze Feld zu
#: erfassen — eine Bergwertung, die bis Rang 150 zahlt, ist keine.
CLIMB_POINTS: dict[str, tuple[int, ...]] = {
    "HC": (20, 15, 12, 10, 8, 6, 4, 2),
    "1. Kat.": (10, 8, 6, 4, 2, 1),
    "2. Kat.": (5, 3, 2, 1),
    "3. Kat.": (2, 1),
    "4. Kat.": (1,),
}


def climb_points_for(category: str, rank: int) -> int:
    tabelle = CLIMB_POINTS.get(category, ())
    return tabelle[rank - 1] if 1 <= rank <= len(tabelle) else 0


def _dauer_text(sekunden: float) -> str:
    """Eine Auffahrtsdauer, wie man sie liest.

    Unter einer Stunde ``m:ss``, darüber ``h:mm:ss``. Ein HC-Pass mit
    zwei Stunden Auffahrt stand vorher als „122:40" da — richtig
    gerechnet, aber niemand liest das als zwei Stunden.
    """
    ganz = int(round(sekunden))
    if ganz < 3600:
        return f"{ganz // 60}:{ganz % 60:02d}"
    return f"{ganz // 3600}:{ganz % 3600 // 60:02d}:{ganz % 60:02d}"

#: Startabstand zwischen zwei Fahrern, in Sekunden. Einzelstart wie im
#: Zeitfahren: Es gibt kein Feld, in dem man sich verstecken könnte, und
#: die Wertung ist die gefahrene Zeit, nicht die Reihenfolge im Ziel.
#:
#: **Das dehnt das Rennen erheblich.** Dreihundert Fahrer im
#: Zehn-Minuten-Takt bedeuten allein fünfzig Stunden Startfenster — der
#: letzte Starter rollt los, wenn der erste längst im Ziel ist.
START_INTERVAL_S = 600.0

STATE_WAITING = -1
STATE_RIDING = 0
STATE_FINISHED = 2


@dataclass
class RaceEvent:
    entry_id: int
    type: str
    #: Eigenzeit des Fahrers — was auf seiner Uhr stand.
    t_s: float
    #: Rennuhr — wann es für den Zuschauer passiert ist. Danach wird
    #: gefiltert und gesprungen; angezeigt wird ``t_s``.
    t_wall: float
    text: str

    def to_dict(self, focus_id: int | None = None) -> dict:
        return {
            "entry_id": self.entry_id,
            "type": self.type,
            "t_s": round(self.t_s, 1),
            "t_wall": round(self.t_wall, 1),
            "text": self.text,
            "focus": self.entry_id == focus_id,
        }


@dataclass
class RaceConfig:
    name: str
    seed: int = 42
    #: Wird aus der Distanz abgeleitet, kann aber überschrieben werden.
    intensity_factor: float | None = None
    start_interval_s: float = START_INTERVAL_S
    #: Stand der Saisonwertung **vor** diesem Rennen, ``rider_id → Punkte``.
    #: Bestimmt die Setzliste. Fehlt sie oder ist sie leer, entscheidet
    #: allein die relative FTP.
    season_points: dict[int, int] | None = None


def intensity_for_distance(distance_km: float) -> float:
    """Intensitätsfaktor für eine Renndistanz, linear interpoliert."""
    xs = [k for k, _ in IF_BY_KM]
    ys = [v for _, v in IF_BY_KM]
    return float(np.interp(distance_km, xs, ys))


def roughness(grade: np.ndarray, step_m: float) -> np.ndarray:
    """Antrittsdichte je Punkt, auf 0 bis 1 normiert.

    Gezählt wird, wie oft die Steigung im Fenster die Schwelle von unten
    nach oben kreuzt — ein Antritt eben. Ein zwanzig Kilometer langer
    Pass zählt einen, ein Wellenritt derselben Länge ein Dutzend.
    """
    g = np.asarray(grade, dtype=np.float64)
    drueber = g > RHYTHM_THRESHOLD
    start = np.zeros_like(g)
    start[1:] = (drueber[1:] & ~drueber[:-1]).astype(np.float64)

    n = int(round(RHYTHM_WINDOW_M / step_m)) | 1
    kern = np.ones(n)
    antritte = np.convolve(start, kern, mode="same")
    # Am Rand ist das Fenster kürzer — sonst zählte dort systematisch zu
    # wenig, und Start und Ziel wären künstlich ruhig.
    breite = np.convolve(np.ones_like(g), kern, mode="same") * step_m / 1000.0
    return np.clip(antritte / breite / RHYTHM_REFERENCE, 0.0, 1.0)


def rhythm_power_factor(rough: np.ndarray, rhythm_norm: np.ndarray) -> np.ndarray:
    """Abzug auf die Zielleistung aus Rhythmuswert und Unruhe.

    Einseitig: Bei ``rhythm_norm`` 1 kommt überall exakt 1,0 heraus, und
    auf glatter Strecke (``rough`` null) ebenfalls — dort ist der Wert
    für jeden wirkungslos.
    """
    fehlt = 1.0 - np.asarray(rhythm_norm, dtype=np.float64)
    return 1.0 - RHYTHM_MAX * fehlt * np.asarray(rough, dtype=np.float64)


def climb_ramp(grade: np.ndarray) -> np.ndarray:
    """Wie sehr dieses Gelände ein Anstieg ist: null flach, eins ab 8 %."""
    return np.clip(np.asarray(grade, dtype=np.float64) / CLIMB_GRADE_FULL, 0.0, 1.0)


def grade_power_factor(grade: np.ndarray) -> np.ndarray:
    """Wie die Steigung die Zielleistung verschiebt.

    Steigt linear von 1,00 bei flach auf 1,15 ab acht Prozent und fällt
    ebenso linear auf 0,55 ab vier Prozent Gefälle.
    """
    g = np.asarray(grade, dtype=np.float64)
    down = np.clip(-g / DESCENT_GRADE_FULL, 0.0, 1.0)
    return 1.0 + CLIMB_POWER_GAIN * climb_ramp(g) - DESCENT_POWER_LOSS * down


def start_profile_factor(share: np.ndarray, start_dev: np.ndarray) -> np.ndarray:
    """Wie das Startprofil die Leistung über die Distanz verteilt.

    ``share`` ist der gefahrene Anteil der Strecke, 0 bis 1. Der
    Schnellstarter (``start_dev`` positiv) beginnt oben und endet unten,
    der Diesel umgekehrt; bei der Hälfte kreuzen sich beide. Bei null
    kommt überall 1,0 heraus.
    """
    s = np.clip(np.asarray(share, dtype=np.float64), 0.0, 1.0)
    return 1.0 + START_PROFILE_SPAN * np.asarray(start_dev, dtype=np.float64) * (1.0 - 2.0 * s)


def finish_kick_factor(share: np.ndarray, kick_norm: np.ndarray) -> np.ndarray:
    """Der Endspurt über das letzte Fünftel der Distanz.

    ``kick_norm`` ist der Endspurtwert auf 0 bis 1. Vor
    ``FINISH_KICK_START`` ist der Faktor genau 1,0, danach läuft er
    linear auf ``1 + FINISH_KICK_MAX · kick_norm`` an der Ziellinie zu.
    """
    s = np.clip(np.asarray(share, dtype=np.float64), 0.0, 1.0)
    rampe = np.clip((s - FINISH_KICK_START) / (1.0 - FINISH_KICK_START), 0.0, 1.0)
    return 1.0 + FINISH_KICK_MAX * np.asarray(kick_norm, dtype=np.float64) * rampe


def profile_power_factor(ramp: np.ndarray, profile_dev: np.ndarray) -> np.ndarray:
    """Wie das Kletterprofil die Leistung zwischen Berg und Flach verschiebt.

    ``profile_dev`` ist die Abweichung von der Mitte, −0,5 bis +0,5.
    Positiv ist der Kletterer: Er drückt am Anstieg und spart im
    Flachen, der Rouleur genau umgekehrt. Bei null kommt überall exakt
    1,0 heraus — der Wert **verschiebt** Leistung, er verschenkt keine.
    """
    return 1.0 + PROFILE_SPAN * np.asarray(profile_dev, dtype=np.float64) * (
        2.0 * np.asarray(ramp, dtype=np.float64) - 1.0
    )


def endurance_fade(own_time_s: np.ndarray, endurance_dev: np.ndarray) -> np.ndarray:
    """Faktor auf die Zielleistung aus Ausdauerwert und Fahrzeit.

    ``endurance_dev`` ist die Abweichung von der Mitte, −0,5 bis +0,5.
    Bei null kommt unabhängig von der Zeit exakt 1,0 heraus — der Wert
    kostet nichts, solange ihn niemand hat.
    """
    spanne = np.minimum(
        FADE_SPAN_PER_10H * np.asarray(own_time_s, dtype=np.float64) / FADE_REFERENCE_S,
        FADE_SPAN_MAX,
    )
    return 1.0 + spanne * np.asarray(endurance_dev, dtype=np.float64)


# ----------------------------------------------------------------------
@dataclass
class _Terrain:
    """Alles, was nur von der Strecke abhängt — einmal vorgerechnet.

    Im Tick bleiben damit Indexzugriffe und Grundrechenarten übrig. Der
    barometrische Ausdruck für die Luftdichte etwa hängt allein an der
    Höhe und würde sonst hunderttausendmal dasselbe rechnen.
    """

    grade: np.ndarray
    cos_slope: np.ndarray
    sin_slope: np.ndarray
    rho: np.ndarray
    position_k: np.ndarray
    power_factor: np.ndarray
    #: Wie stark die Bremse hier greifen darf — null bis eins.
    brake_ramp: np.ndarray
    #: Wie sehr dieses Segment ein Anstieg ist — null im Flachen und
    #: bergab, eins ab acht Prozent. Daran hängt das Kletterprofil.
    climb_ramp: np.ndarray
    #: Antrittsdichte, 0 bis 1. Daran hängt der Rhythmuswert.
    roughness: np.ndarray

    @classmethod
    def build(cls, route: Route) -> _Terrain:
        grade = route.grade
        cos_slope, sin_slope = physics.slope_trig(grade)
        # Höhe in der Mitte des Segments — auf hundert Metern ist der
        # Unterschied zum Randwert bedeutungslos, aber er ist gratis.
        mid_ele = 0.5 * (route.ele_m[:-1] + route.ele_m[1:])
        return cls(
            grade=grade,
            cos_slope=cos_slope,
            sin_slope=sin_slope,
            rho=physics.air_density(mid_ele),
            position_k=physics.position_k(grade),
            power_factor=grade_power_factor(grade),
            brake_ramp=physics.brake_ramp(grade),
            climb_ramp=climb_ramp(grade),
            roughness=roughness(grade, route.step_m),
        )


@dataclass
class LiveRace:
    """Ein laufendes Rennen samt allem, was daran hängt."""

    route: Route
    riders: list[Rider]
    teams: list[Team]
    config: RaceConfig

    sim_t: float = 0.0
    finished: bool = False
    events: list[RaceEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        n = len(self.riders)
        route = self.route
        rng = np.random.default_rng(self.config.seed)

        self._terrain = _Terrain.build(route)
        self._n_cells = len(route.grade)

        # --- Fahrerkonstanten -----------------------------------------
        self.ftp = np.array([r.ftp_w for r in self.riders], dtype=np.float64)
        self.mass = np.array([r.system_mass_kg for r in self.riders], dtype=np.float64)
        #: Frontalfläche samt Aerodynamikwert. Der Wert steckt hier
        #: fest drin, statt im Tick jedes Mal aufgeschlagen zu werden:
        #: Er ändert sich während des Rennens nicht, und so gilt er
        #: überall, wo mit der Fläche gerechnet wird — auch in der
        #: Schätzung des Zeitstrahls.
        self.area = np.array(
            [r.frontal_area_m2 for r in self.riders], dtype=np.float64
        ) * physics.aero_cda_factor(np.array([r.aero_dev for r in self.riders]))

        #: Der Abfahrtswert, schon in die Form gebracht, die der Tick
        #: braucht: ``f = 1 − brems_coeff · Rampe``. Bei Wert 100 ist der
        #: Beiwert null, und die Bremse ist damit wirkungslos — ohne
        #: Sonderfall, ohne Verzweigung.
        self.descent_norm = np.array([r.descent_norm for r in self.riders], dtype=np.float64)
        self._brake_coeff = physics.DESCENT_THROTTLE_MAX * (1.0 - self.descent_norm)

        #: Der Ausdauerwert als Abweichung von der Mitte, −0,5 bis +0,5.
        self.endurance_dev = np.array([r.endurance_dev for r in self.riders], dtype=np.float64)
        #: Ebenso das Kletterprofil: positiv der Kletterer, negativ der
        #: Rouleur.
        self.profile_dev = np.array([r.climb_profile_dev for r in self.riders], dtype=np.float64)
        #: Das Startprofil: positiv der Schnellstarter, negativ der Diesel.
        self.start_dev = np.array([r.start_profile_dev for r in self.riders], dtype=np.float64)
        #: Der Endspurt, 0 bis 1.
        self.kick_norm = np.array([r.finish_kick_norm for r in self.riders], dtype=np.float64)
        #: Der Rhythmuswert, 0 bis 1 — 1 heißt: kein Verlust.
        self.rhythm_norm = np.array([r.rhythm_norm for r in self.riders], dtype=np.float64)

        intensity = self.config.intensity_factor
        if intensity is None:
            intensity = intensity_for_distance(route.distance_km)
        self.intensity_factor = float(intensity)

        # Tagesform und Trittrauschen: beide aus dem Renn-Seed, also für
        # dasselbe Rennen jedes Mal gleich.
        self.form = np.clip(rng.normal(1.0, FORM_SD, n), *FORM_RANGE)
        self._w_slow = 2.0 * math.pi / rng.uniform(*NOISE_PERIOD_SLOW, n)
        self._w_fast = 2.0 * math.pi / rng.uniform(*NOISE_PERIOD_FAST, n)
        self._phi_slow = rng.uniform(0.0, 2.0 * math.pi, n)
        self._phi_fast = rng.uniform(0.0, 2.0 * math.pi, n)

        # „Energiegeladen": eine Tabelle je Fahrer und Messstelle,
        # einmal aus dem Renn-Seed gezogen. Sie ist **keine**
        # Vorausberechnung des Rennens — sie ist Würfelwerk wie die
        # Tagesform, und wirksam wird ein Eintrag erst, wenn der Fahrer
        # die zugehörige Messstelle tatsächlich erreicht. Der Vorteil
        # gegenüber einem Würfel im Tick: Der Zustand hängt allein an
        # der Zahl der passierten Messstellen, und damit stimmt er auch
        # nach einem Rücksprung in der Wiedergabe.
        n_splits = len(self.route.splits)
        treffer = rng.random((n, n_splits)) < ENERGY_EVENT_P
        hoehe = rng.uniform(*ENERGY_BONUS_W, (n, n_splits))
        # Die dreißig Stärksten nach Watt je Kilogramm bleiben außen vor.
        wkg = self.ftp / np.array([r.weight_kg for r in self.riders], dtype=np.float64)
        stark = np.argsort(-wkg, kind="stable")[:ENERGY_EXCLUDE_TOP]
        treffer[stark, :] = False
        self.energy_table = np.where(treffer, hoehe, 0.0)

        #: Zielleistung im Flachen, ohne Modulation.
        self.base_power = self.ftp * self.intensity_factor * self.form

        # --- Start ------------------------------------------------------
        # Einzelstart wie im Zeitfahren: **der Schwächste zuerst, der
        # Stärkste zuletzt**. Damit fällt die Entscheidung am Ende der
        # Übertragung und nicht in ihrer Mitte — wer als Letzter losrollt,
        # kennt die Zeit, die er schlagen muss.
        #
        # Die Engine rechnet in Rennuhr; was ein Fahrer auf seiner
        # eigenen Uhr hat, ist die Rennuhr minus seinem Startversatz.
        self.start_offset_s = self._start_order() * self.config.start_interval_s

        # --- Zustand ---------------------------------------------------
        self.dist_m = np.zeros(n)
        self.v_ms = np.full(n, 4.0)
        self.power_w = np.zeros(n)
        self.state = np.full(n, STATE_WAITING, dtype=np.int8)
        #: Zielzeit in Eigenzeit — die Wertungsgröße.
        self.finish_time_s = np.full(n, np.nan)
        #: Zielzeit auf der Rennuhr — wann es zu sehen war.
        self.finish_wall_s = np.full(n, np.nan)

        # --- Zeitmessung ----------------------------------------------
        self.split_dist = np.array([s.dist_m for s in route.splits], dtype=np.float64)
        self._n_splits = len(self.split_dist)
        self.next_split = np.zeros(n, dtype=np.int32)
        self.split_times = np.full((n, self._n_splits), np.nan)
        self._split_seen = np.zeros(self._n_splits, dtype=np.int32)
        self._split_best = np.full(self._n_splits, np.inf)

        # --- Bergwertung -----------------------------------------------
        #
        # Jeder kategorisierte Anstieg wird an beiden Enden gestoppt. Die
        # Grenzen liegen als eine gemeinsame, nach Distanz sortierte
        # Liste vor — dann genügt derselbe Zeiger-über-Marken-Ansatz wie
        # bei den Zeitmessungen, statt für jeden Anstieg einzeln zu
        # prüfen.
        self.n_climbs = len(route.climbs)
        marken = sorted(
            [(c.dist_start_m, i, 0) for i, c in enumerate(route.climbs)]
            + [(c.dist_end_m, i, 1) for i, c in enumerate(route.climbs)]
        )
        self._mark_dist = np.array([m[0] for m in marken], dtype=np.float64)
        self._mark_climb = np.array([m[1] for m in marken], dtype=np.int32)
        self._mark_kind = np.array([m[2] for m in marken], dtype=np.int8)
        self._n_marks = len(marken)
        self.next_mark = np.zeros(n, dtype=np.int32)
        #: Eigenzeit am Fuß und am Gipfel jedes Anstiegs.
        self.climb_enter_s = np.full((n, self.n_climbs), np.nan)
        self.climb_exit_s = np.full((n, self.n_climbs), np.nan)
        self._climb_best = np.full(self.n_climbs, np.inf)

        # --- Erinnerung ------------------------------------------------
        self._hist_t: list[float] = [0.0]
        self._hist_dist: list[np.ndarray] = [self.dist_m.astype(np.float32)]
        self._hist_v: list[np.ndarray] = [self.v_ms.astype(np.float32)]
        self._next_hist_t = HISTORY_INTERVAL_S

        self._gen = self._run()

    def _start_order(self) -> np.ndarray:
        """Startposition je Fahrer: Saisonpunkte aufsteigend, dann FTP.

        Wer in der Saisonwertung vorn steht, startet zuletzt — die
        Entscheidung fällt damit am Ende der Übertragung und nicht in
        ihrer Mitte. Vor dem ersten Rennen haben alle null Punkte, und
        dann setzt die relative FTP die Reihenfolge; sie trennt auch
        Punktgleichheit, die bei dreihundert Fahrern und einer
        Punkteliste bis Rang 150 die Regel ist, nicht die Ausnahme.

        Die Setzliste ist die Papierform, nicht das Ergebnis: Sie kennt
        Punkte, FTP und Gewicht, aber nicht die Tagesform und nicht das
        Gelände. Der Gesetzte startet zuletzt und verliert trotzdem
        regelmäßig.

        Ganz zuletzt entscheidet die Startnummer, damit die Reihenfolge
        reproduzierbar ist.
        """
        punkte_je_fahrer = self.config.season_points or {}
        punkte = np.array(
            [punkte_je_fahrer.get(r.id, 0) for r in self.riders], dtype=np.float64
        )
        wkg = np.array([r.ftp_w / r.weight_kg for r in self.riders], dtype=np.float64)
        bibs = np.array([r.bib for r in self.riders])
        # ``lexsort`` sortiert nach dem *letzten* Schlüssel zuerst.
        gesetzt = np.lexsort((bibs, wkg, punkte))
        positions = np.empty(len(self.riders), dtype=np.float64)
        positions[gesetzt] = np.arange(len(self.riders), dtype=np.float64)
        return positions

    # ------------------------------------------------------------------
    # Rechnen
    # ------------------------------------------------------------------
    def _run(self):
        """Der Generator. Läuft, bis der letzte Fahrer im Ziel ist."""
        while True:
            for _ in range(TICKS_PER_YIELD):
                self._tick()
                if self.finished:
                    break
            self._record()
            yield self.sim_t
            if self.finished:
                return

    def _tick(self) -> None:
        t = self.sim_t + DT

        # Wer jetzt an der Reihe ist, rollt los.
        starting = np.nonzero((self.state == STATE_WAITING) & (self.start_offset_s <= t))[0]
        if starting.size:
            self.state[starting] = STATE_RIDING
            for i in starting:
                rider = self.riders[int(i)]
                self.events.append(
                    RaceEvent(rider.id, "START", 0.0, float(self.start_offset_s[i]),
                              f"{rider.name} startet")
                )

        active = self.state == STATE_RIDING
        if not active.any():
            self.sim_t = t
            # Kein Fahrer unterwegs heißt nur dann Rennende, wenn auch
            # keiner mehr auf seinen Start wartet — bei fünfzig Stunden
            # Startfenster ist das ein Unterschied.
            if not (self.state == STATE_WAITING).any():
                self.finished = True
            return

        terrain = self._terrain
        idx = np.clip((self.dist_m / self.route.step_m).astype(np.int64), 0, self._n_cells - 1)

        # Zielleistung: Grundwert × Steigung × Trittrauschen, danach
        # gedeckelt durch die Trittfrequenz in der Abfahrt.
        noise = (
            1.0
            + NOISE_AMP_SLOW * np.sin(self._w_slow * t + self._phi_slow)
            + NOISE_AMP_FAST * np.sin(self._w_fast * t + self._phi_fast)
        )
        # Der Verfall zählt in **Eigenzeit**, nicht in Rennuhr: Wer erst
        # seit einer Stunde fährt, ist eine Stunde alt, auch wenn die
        # Übertragung seit dreißig läuft.
        # Das Kletterprofil verschiebt dieselbe Leistung zwischen Berg
        # und Flach — es kommt keine dazu. Das Startprofil tut dasselbe
        # zwischen Anfang und Ende der Strecke; nur der Endspurt legt
        # wirklich etwas drauf, dafür erst auf dem letzten Fünftel.
        anteil = self.dist_m / self.route.distance_m
        profil = profile_power_factor(terrain.climb_ramp[idx], self.profile_dev)
        profil = profil * start_profile_factor(anteil, self.start_dev)
        profil = profil * finish_kick_factor(anteil, self.kick_norm)
        profil = profil * rhythm_power_factor(terrain.roughness[idx], self.rhythm_norm)
        # Der Schub liegt auf der FTP, nicht auf der Tretleistung —
        # deshalb geht er denselben Weg wie sie: mal Intensitätsfaktor,
        # mal Tagesform.
        grund = self.base_power + self.energy_bonus_w * self.intensity_factor * self.form
        power = grund * self.fade_at(t) * terrain.power_factor[idx] * profil * noise
        power *= physics.downhill_power_taper(self.v_ms)
        power = np.where(active, power, 0.0)

        # Bremsen in der Abfahrt: ein Zuschlag auf den Widerstand, kein
        # Abzug von der Leistung. Ab acht Prozent Gefälle tritt der
        # Fahrer im größten Gang leer — die Watt sind dort schon null,
        # und was null ist, kann man nicht kleiner machen.
        f_brems = 1.0 - self._brake_coeff * terrain.brake_ramp[idx]
        cda = self.area * terrain.position_k[idx] / (f_brems * f_brems)
        crr = physics.rolling_crr(self.v_ms)

        v_new = physics.integrate_step(
            self.v_ms,
            power,
            terrain.grade[idx],
            self.mass,
            cda,
            crr,
            terrain.rho[idx],
            DT,
            cos_slope=terrain.cos_slope[idx],
            sin_slope=terrain.sin_slope[idx],
        )
        self.v_ms = np.where(active, v_new, 0.0)
        self.power_w = power
        self.dist_m = self.dist_m + self.v_ms * DT
        self.sim_t = t

        self._check_splits(t)
        self._check_climbs(t)
        self._check_finish(t)

    def _check_splits(self, t: float) -> None:
        """Zeitmessungen abarbeiten — auch mehrere in einem Tick."""
        while True:
            pending = self.next_split < self._n_splits
            if not pending.any():
                return
            probe = np.where(pending, self.next_split, 0)
            crossed = pending & (self.dist_m >= self.split_dist[probe])
            ids = np.nonzero(crossed)[0]
            if ids.size == 0:
                return

            s_idx = self.next_split[ids]
            # Der Übertritt liegt zwischen zwei Ticks; ohne Interpolation
            # wäre jede Splitzeit auf die Sekunde nach oben gerundet, und
            # bei dreihundert Fahrern stünden Dutzende gleichauf.
            over = self.dist_m[ids] - self.split_dist[s_idx]
            t_cross = t - over / np.maximum(self.v_ms[ids], 0.1)
            # Gewertet wird die Eigenzeit — beim Einzelstart ist die
            # Rennuhr keine Wertungsgröße, sondern nur die Sendezeit.
            own = t_cross - self.start_offset_s[ids]
            self.split_times[ids, s_idx] = own
            self.next_split[ids] = s_idx + 1

            for k in np.argsort(t_cross, kind="stable"):
                self._on_split(int(ids[k]), int(s_idx[k]), float(own[k]), float(t_cross[k]))

    def _on_split(self, rider_idx: int, split_idx: int, own_s: float, t_wall: float) -> None:
        split = self.route.splits[split_idx]
        if split.kind == "finish":
            return  # das Ziel meldet ``_check_finish``

        rank = int(self._split_seen[split_idx]) + 1
        self._split_seen[split_idx] = rank
        rider = self.riders[rider_idx]

        # Der Schub gilt ab dieser Messstelle bis zur nächsten. Ohne
        # Meldung wäre er unsichtbar — und ein Ereignis, das niemand
        # bemerkt, ist keins.
        bonus = float(self.energy_table[rider_idx, split_idx])
        if bonus > 0.0:
            naechste = self.route.splits[min(split_idx + 1, self._n_splits - 1)]
            self.events.append(
                RaceEvent(
                    rider.id,
                    "ENERGY",
                    own_s,
                    t_wall,
                    f"{rider.name} fährt energiegeladen — +{bonus:.0f} W bis {naechste.name}",
                )
            )

        # „Führung" heißt beim Einzelstart: die schnellste Zeit, nicht
        # der erste am Messpunkt.
        if own_s < self._split_best[split_idx]:
            self._split_best[split_idx] = own_s
            self.events.append(
                RaceEvent(
                    rider.id,
                    "BEST_TIME",
                    own_s,
                    t_wall,
                    f"{rider.name} übernimmt die Führung bei {split.name}",
                )
            )
        elif rank <= TICKER_SPLIT_LIMIT:
            self.events.append(
                RaceEvent(
                    rider.id,
                    "SPLIT_PASSED",
                    own_s,
                    t_wall,
                    f"{split.name}: {rider.name} als {rank}. durch",
                )
            )

    def _check_climbs(self, t: float) -> None:
        """Fuß und Gipfel jedes Anstiegs stempeln.

        Derselbe Ablauf wie bei den Zeitmessungen, nur über die
        gemeinsame Markenliste. Gestempelt wird in Eigenzeit — eine
        Auffahrt dauert, was sie dauert, unabhängig davon, wann der
        Fahrer losgerollt ist.
        """
        if self._n_marks == 0:
            return
        while True:
            offen = self.next_mark < self._n_marks
            if not offen.any():
                return
            probe = np.where(offen, self.next_mark, 0)
            crossed = offen & (self.dist_m >= self._mark_dist[probe])
            ids = np.nonzero(crossed)[0]
            if ids.size == 0:
                return

            m_idx = self.next_mark[ids]
            over = self.dist_m[ids] - self._mark_dist[m_idx]
            own = (t - over / np.maximum(self.v_ms[ids], 0.1)) - self.start_offset_s[ids]
            self.next_mark[ids] = m_idx + 1

            climb = self._mark_climb[m_idx]
            am_fuss = self._mark_kind[m_idx] == 0
            self.climb_enter_s[ids[am_fuss], climb[am_fuss]] = own[am_fuss]
            self.climb_exit_s[ids[~am_fuss], climb[~am_fuss]] = own[~am_fuss]

            for k in np.nonzero(~am_fuss)[0]:
                self._on_summit(int(ids[k]), int(climb[k]))

    def _on_summit(self, rider_idx: int, climb_idx: int) -> None:
        dauer = float(
            self.climb_exit_s[rider_idx, climb_idx] - self.climb_enter_s[rider_idx, climb_idx]
        )
        if not np.isfinite(dauer) or dauer <= 0.0:
            return
        # Nur die Bestzeit meldet sich. Dreihundert Auffahrten je Anstieg
        # wären ein Laufband, das niemand liest.
        if dauer >= self._climb_best[climb_idx]:
            return
        self._climb_best[climb_idx] = dauer

        climb = self.route.climbs[climb_idx]
        rider = self.riders[rider_idx]
        vam = climb.ascent_m / (dauer / 3600.0)
        self.events.append(
            RaceEvent(
                rider.id,
                "BEST_CLIMB",
                float(self.climb_exit_s[rider_idx, climb_idx]),
                float(self.climb_exit_s[rider_idx, climb_idx] + self.start_offset_s[rider_idx]),
                f"{climb.category} km {climb.dist_end_m / 1000:.0f}: {rider.name} "
                f"in {_dauer_text(dauer)} — {vam:.0f} VAM, Bestzeit",
            )
        )

    # ------------------------------------------------------------------
    def climb_duration(self, t_wall: float) -> np.ndarray:
        """Auffahrtsdauer je Fahrer und Anstieg, in Sekunden.

        Wer noch im Anstieg ist, bekommt die **laufende** Dauer — dieselbe
        Logik wie bei einer Zeitmessung, die er noch vor sich hat. Wer
        ihn noch nicht erreicht hat, bekommt ``nan``.
        """
        own = self.own_time(t_wall)[:, None]
        drin = ~np.isnan(self.climb_enter_s) & (self.climb_enter_s <= own)
        oben = ~np.isnan(self.climb_exit_s) & (self.climb_exit_s <= own)
        laufend = np.where(oben, self.climb_exit_s, own)
        return np.where(drin, laufend - self.climb_enter_s, np.nan)

    def climb_done(self, t_wall: float) -> np.ndarray:
        own = self.own_time(t_wall)[:, None]
        return ~np.isnan(self.climb_exit_s) & (self.climb_exit_s <= own)

    def climb_vam(self, t_wall: float, dist_m: np.ndarray | None = None) -> np.ndarray:
        """Höhenmeter je Stunde, je Fahrer und Anstieg.

        Für eine **abgeschlossene** Auffahrt sind das die Höhenmeter des
        Anstiegs geteilt durch die gefahrene Zeit. Für eine laufende
        aber nur die **bis hierher gewonnene** Höhe: Wer ein Drittel
        oben ist, hat auch erst ein Drittel geklettert, und mit der
        vollen Höhe im Zähler zeigte er die dreifache
        Steiggeschwindigkeit.

        Ohne ``dist_m`` bleibt es bei der vollen Höhe — für fertige
        Auffahrten ist das richtig, und die Punktevergabe fragt nur
        danach.
        """
        dauer = self.climb_duration(t_wall)
        hm = np.broadcast_to(
            np.array([c.ascent_m for c in self.route.climbs], dtype=np.float64),
            dauer.shape,
        ).copy()

        if dist_m is not None and self.n_climbs:
            aktuell = self.current_climb(dist_m)
            drin = np.nonzero(aktuell >= 0)[0]
            if drin.size:
                ci = aktuell[drin]
                step = self.route.step_m
                jetzt = self.route.elevation_at_index((dist_m[drin] / step).astype(np.int64))
                fuss = self.route.elevation_at_index(
                    np.array([self.route.climbs[c].dist_start_m for c in ci]) / step
                )
                hm[drin, ci] = np.maximum(jetzt - fuss, 0.0)

        with np.errstate(invalid="ignore", divide="ignore"):
            return hm / np.maximum(dauer, 1.0) * 3600.0

    def current_climb(self, dist_m: np.ndarray) -> np.ndarray:
        """In welchem Anstieg jeder Fahrer gerade steckt, sonst -1."""
        out = np.full(len(self.riders), -1, dtype=np.int32)
        for i, climb in enumerate(self.route.climbs):
            drin = (dist_m >= climb.dist_start_m) & (dist_m < climb.dist_end_m)
            out[drin] = i
        return out

    def climb_points(self) -> dict[int, int]:
        """Punkte der Bergwertung nach dem Rennen, je Fahrer.

        Erst am Ende, und nur aus gefahrenen Auffahrten: Eine Wertung
        über ein Rennen, das noch läuft, wäre eine Prognose.
        """
        punkte: dict[int, int] = {}
        for i, climb in enumerate(self.route.climbs):
            dauer = self.climb_exit_s[:, i] - self.climb_enter_s[:, i]
            gueltig = np.nonzero(np.isfinite(dauer) & (dauer > 0))[0]
            if gueltig.size == 0:
                continue
            for rang, k in enumerate(gueltig[np.argsort(dauer[gueltig], kind="stable")], start=1):
                p = climb_points_for(climb.category, rang)
                if p == 0:
                    break
                rider_id = self.riders[int(k)].id
                punkte[rider_id] = punkte.get(rider_id, 0) + p
        return punkte

    def _check_finish(self, t: float) -> None:
        done = (self.state == STATE_RIDING) & (self.dist_m >= self.route.distance_m)
        ids = np.nonzero(done)[0]
        if ids.size == 0:
            return
        over = self.dist_m[ids] - self.route.distance_m
        t_wall = t - over / np.maximum(self.v_ms[ids], 0.1)
        own = t_wall - self.start_offset_s[ids]

        self.state[ids] = STATE_FINISHED
        self.finish_time_s[ids] = own
        self.finish_wall_s[ids] = t_wall
        self.dist_m[ids] = self.route.distance_m
        self.v_ms[ids] = 0.0
        self.split_times[ids, self._n_splits - 1] = own

        for k in np.argsort(t_wall, kind="stable"):
            i = int(ids[k])
            rider = self.riders[i]
            # Der Rang ist der in der Zeitwertung, nicht die Reihenfolge
            # am Zielstrich: Wer eine Stunde später startet und dieselbe
            # Zeit fährt, steht vor dem, der langsamer war.
            rank = int(np.count_nonzero(self.finish_time_s <= own[k]))
            self.events.append(
                RaceEvent(rider.id, "FINISH", float(own[k]), float(t_wall[k]),
                          f"{rider.name} im Ziel — Rang {rank}")
            )
        if not ((self.state == STATE_RIDING) | (self.state == STATE_WAITING)).any():
            self.finished = True

    def _record(self) -> None:
        """Positionen für den Rückblick ablegen."""
        if self.sim_t < self._next_hist_t and not self.finished:
            return
        self._hist_t.append(self.sim_t)
        self._hist_dist.append(self.dist_m.astype(np.float32))
        self._hist_v.append(self.v_ms.astype(np.float32))
        while self._next_hist_t <= self.sim_t:
            self._next_hist_t += HISTORY_INTERVAL_S

    # ------------------------------------------------------------------
    # Steuerung von außen
    # ------------------------------------------------------------------
    def advance_to(self, t: float) -> None:
        """Bis zur Rennzeit ``t`` rechnen — und keine Sekunde weiter."""
        while self.sim_t < t and not self.finished:
            if next(self._gen, None) is None:
                self.finished = True
                return

    @property
    def horizon_s(self) -> float:
        """Das rechte Ende des Zeitstrahls.

        Nach dem Ziel die Wahrheit, davor eine Schätzung aus dem
        langsamsten Fahrer im Gleichgewicht. Ein zu kurzer Zeitstrahl
        hielte die Wiedergabe vor dem Ende an; ein zu langer verzieht
        nur einen Balken.
        """
        if self.finished:
            return float(np.nanmax(self.finish_wall_s))
        # ``max``, nicht ``[-1]``: Seit die Setzliste nach Stärke sortiert,
        # ist der letzte Fahrer der Liste nicht mehr der letzte Starter.
        return float(self.start_offset_s.max()) + self._estimated_duration_s

    @property
    def _estimated_duration_s(self) -> float:
        """Wie lange der langsamste Fahrer voraussichtlich braucht.

        Nicht über eine Durchschnittssteigung geschätzt — die ist bei
        einem Profil mit 23 000 Höhenmetern und ebenso viel Abfahrt
        null und damit wertlos. Stattdessen wird die
        Gleichgewichtsgeschwindigkeit für **jedes** Segment berechnet
        und die Fahrzeit aufsummiert. Zehntausend Bisektionen
        vektorisiert kosten Millisekunden und liefern einen Zeitstrahl,
        der auch im Hochgebirge stimmt.
        """
        if not hasattr(self, "_duration_cache"):
            weakest = int(np.argmin(self.base_power / self.mass))
            terrain = self._terrain
            # Mit der stärksten Bremse gerechnet, nicht mit der des
            # schwächsten Fahrers: Der Zeitstrahl darf zu lang sein,
            # aber nie zu kurz — sonst hielte die Wiedergabe vor dem
            # letzten Zieleinlauf an.
            f_brems = physics.descent_speed_factor(terrain.brake_ramp, 0.0)
            # Ebenso beim Verfall: gerechnet wird mit der schlechtesten
            # Ausdauer, die es geben kann, nicht mit der des schwächsten
            # Fahrers.
            verfall = 1.0 - FADE_SPAN_MAX / 2.0
            # Und beim Kletterprofil das, was an dieser Stelle jeweils
            # am langsamsten ist: am Anstieg der Rouleur, im Flachen der
            # Kletterer. Kein einzelner Fahrer ist beides — der
            # Zeitstrahl soll aber auch keinen von beiden abschneiden.
            profil = profile_power_factor(terrain.climb_ramp, -0.5)
            profil = np.minimum(profil, profile_power_factor(terrain.climb_ramp, 0.5))
            # Und beim Startprofil ebenso das jeweils langsamere Ende:
            # vorn der Diesel, hinten der Schnellstarter. Der Endspurt
            # bleibt außen vor — er macht nur schneller, und eine zu
            # lange Schätzung schadet nicht.
            anteil = (np.arange(len(terrain.grade)) + 0.5) / len(terrain.grade)
            profil = profil * np.minimum(
                start_profile_factor(anteil, -0.5), start_profile_factor(anteil, 0.5)
            )
            # Beim Rhythmus der schlechteste denkbare Wert, also null.
            profil = profil * rhythm_power_factor(terrain.roughness, 0.0)
            # Ebenso die schlechteste Position im Feld statt der des
            # schwächsten Fahrers.
            v = physics.steady_state_speed(
                self.base_power[weakest] * verfall * profil * terrain.power_factor,
                terrain.grade,
                self.mass[weakest],
                float(self.area.max()) * terrain.position_k / (f_brems * f_brems),
                physics.CRR_ASPHALT,
                terrain.rho,
            )
            v = np.clip(v, 1.5, physics.MAX_SPEED)
            self._duration_cache = float(np.sum(self.route.step_m / v) * 1.10)
        return self._duration_cache

    # ------------------------------------------------------------------
    # Ablesen
    # ------------------------------------------------------------------
    def positions_at(self, t: float) -> tuple[np.ndarray, np.ndarray]:
        """Distanz und Tempo aller Fahrer zur Rennzeit ``t``.

        Für ``t`` in der Vergangenheit wird zwischen zwei Schnappschüssen
        interpoliert. Für ``t`` jenseits des Gerechneten gibt es den
        aktuellen Stand — weiter zu gehen hieße, in die Zukunft zu sehen.
        """
        t = max(0.0, min(t, self.sim_t))
        times = self._hist_t
        if t >= times[-1]:
            return self.dist_m, self.v_ms

        j = int(np.searchsorted(times, t, side="right"))
        j = min(max(j, 1), len(times) - 1)
        t0, t1 = times[j - 1], times[j]
        f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
        d0, d1 = self._hist_dist[j - 1], self._hist_dist[j]
        v0, v1 = self._hist_v[j - 1], self._hist_v[j]
        return (
            d0.astype(np.float64) + f * (d1 - d0),
            v0.astype(np.float64) + f * (v1 - v0),
        )

    def grade_at(self, dist_m: np.ndarray) -> np.ndarray:
        idx = np.clip((np.asarray(dist_m) / self.route.step_m).astype(np.int64), 0, self._n_cells - 1)
        return self._terrain.grade[idx]

    def events_until(self, t: float) -> list[RaceEvent]:
        """Alle Meldungen bis zur Rennuhrzeit ``t``, jüngste zuletzt.

        Gefiltert wird nach der Rennuhr, angezeigt wird die Eigenzeit:
        Der Zuschauer sieht die Meldung, wenn sie passiert, aber er
        liest die Zeit, die auf der Uhr des Fahrers stand.
        """
        return [e for e in self.events if e.t_wall <= t]

    # -- Zeitrechnung beim Einzelstart ---------------------------------
    def own_time(self, t_wall: float) -> np.ndarray:
        """Was auf der Uhr jedes Fahrers steht, bei Rennuhr ``t_wall``.

        Vor dem eigenen Start null: Wer noch am Starthaus steht, hat
        keine Zeit — und ihm welche anzudichten hieße, ihn in der
        Wertung an die Spitze zu setzen.
        """
        return np.maximum(t_wall - self.start_offset_s, 0.0)

    @property
    def energy_bonus_w(self) -> np.ndarray:
        """Der Schub, der gerade gilt — in Watt auf die FTP.

        Er hängt allein daran, wie viele Messstellen ein Fahrer hinter
        sich hat: Ausgelöst wird an einer Messstelle, und er hält bis
        zur nächsten. Damit braucht das Ereignis kein Gedächtnis, und
        ein Rücksprung in der Wiedergabe zeigt denselben Zustand wie
        beim ersten Durchlauf.
        """
        return self._energy_for(self.next_split)

    def energy_at(self, t_wall: float) -> np.ndarray:
        """Derselbe Schub, aber zur Uhr des Zuschauers."""
        return self._energy_for(np.count_nonzero(self.reached_mask(t_wall), axis=1))

    def _energy_for(self, passiert: np.ndarray) -> np.ndarray:
        letzte = np.clip(np.asarray(passiert) - 1, 0, self._n_splits - 1)
        bonus = self.energy_table[np.arange(len(self.riders)), letzte]
        return np.where(np.asarray(passiert) >= 1, bonus, 0.0)

    def roughness_at(self, dist_m: np.ndarray) -> np.ndarray:
        """Die Unruhe des Geländes an der Stelle jedes Fahrers."""
        idx = np.clip((np.asarray(dist_m) / self.route.step_m).astype(np.int64),
                      0, self._n_cells - 1)
        return self._terrain.roughness[idx]

    def rhythm_factor_at(self, dist_m: np.ndarray) -> np.ndarray:
        """Was der Rhythmus jeden Fahrer an seiner Stelle gerade kostet."""
        return rhythm_power_factor(self.roughness_at(dist_m), self.rhythm_norm)

    def fade_at(self, t_wall: float) -> np.ndarray:
        """Der Verfallsfaktor zur Rennuhr ``t_wall``, für die Anzeige.

        Dieselbe Funktion, die im Tick die Leistung verschiebt — nur zur
        Uhr des Zuschauers statt zur Rechenzeit der Engine.
        """
        return endurance_fade(self.own_time(t_wall), self.endurance_dev)

    def started_mask(self, t_wall: float) -> np.ndarray:
        return self.start_offset_s <= t_wall

    def finished_mask(self, t_wall: float) -> np.ndarray:
        return ~np.isnan(self.finish_wall_s) & (self.finish_wall_s <= t_wall)

    def reached_mask(self, t_wall: float) -> np.ndarray:
        """Welche Zeitmessung welcher Fahrer schon hinter sich hat."""
        own = self.own_time(t_wall)[:, None]
        return ~np.isnan(self.split_times) & (self.split_times <= own)


__all__ = [
    "LiveRace",
    "RaceConfig",
    "RaceEvent",
    "intensity_for_distance",
    "grade_power_factor",
    "endurance_fade",
    "climb_ramp",
    "profile_power_factor",
    "start_profile_factor",
    "finish_kick_factor",
    "START_PROFILE_SPAN",
    "FINISH_KICK_MAX",
    "roughness",
    "rhythm_power_factor",
    "RHYTHM_MAX",
    "RHYTHM_REFERENCE",
    "ENERGY_EVENT_P",
    "ENERGY_BONUS_W",
    "ENERGY_EXCLUDE_TOP",
    "PROFILE_SPAN",
    "FADE_SPAN_PER_10H",
    "FADE_SPAN_MAX",
    "climb_points_for",
    "CLIMB_POINTS",
    "STATE_WAITING",
    "STATE_RIDING",
    "STATE_FINISHED",
    "START_INTERVAL_S",
    "DT",
]
