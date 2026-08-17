"""Fahrer, Teams und der Generator für den Pool.

Ein Fahrer hat in dieser Fassung genau drei körperliche Eigenschaften:
**FTP, Gewicht, Größe**. Was er damit anfängt, sagen vier Zahlen von 0
bis 100: **Abfahrt**, **Ausdauer**, **Aerodynamik** und das
**Kletterprofil**. Alles andere — Magen, Schlaf, Charakter — ist
bewusst nicht da.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, replace

import numpy as np

from . import physics
from .names import FIRST_NAMES, LAST_NAMES, NATION_WEIGHTS, NATIONS, TEAM_NAMES

#: Fahrer je Team. Zwölf mal fünfundzwanzig Teams ergibt das Feld.
RIDERS_PER_TEAM = 12
N_TEAMS = len(TEAM_NAMES)
FIELD_SIZE = N_TEAMS * RIDERS_PER_TEAM  # 300

#: Körpergröße in Zentimetern.
HEIGHT_MEAN = 178.0
HEIGHT_SD = 6.5
HEIGHT_RANGE = (163.0, 195.0)

#: Körperbau über den BMI statt über das Gewicht direkt. Sonst entstehen
#: 190-cm-Fahrer mit 58 kg und 165-cm-Fahrer mit 85 kg — beide gibt es
#: im Radsport nicht.
BMI_MEAN = 21.5
BMI_SD = 1.2
#: Der BMI wird **vor** dem Gewicht begrenzt. Ohne das schlug der
#: Gewichtsdeckel unten durch: Ein 180-cm-Fahrer mit einem sehr tiefen
#: Zug landete bei 55 kg und damit bei einem BMI von 16,9 — den gibt es
#: im Radsport nicht. Der Deckel auf dem Gewicht bleibt trotzdem, er
#: fängt nur noch die Ränder ab.
BMI_RANGE = (18.5, 25.0)
WEIGHT_RANGE = (55.0, 88.0)

#: Relative FTP in Watt je Kilogramm Körpergewicht.
WKG_MEAN = 4.40
WKG_SD = 0.45
WKG_RANGE = (3.30, 5.60)

#: Spannweite des Team-Offsets auf die relative FTP. Ohne ihn wären die
#: fünfundzwanzig Teams statistisch nicht unterscheidbar und die
#: Teamwertung eine Zufallszahl.
TEAM_OFFSET_SPAN = 0.35

#: Form der Verteilung des Abfahrtswerts: eine Beta-Verteilung mit
#: gleichen Parametern, auf 0 bis 100 gestreckt.
#:
#: Warum nicht die Normalverteilung: Sie ist unbegrenzt und müsste an
#: beiden Enden abgeschnitten werden — dann sammelt sich Masse genau auf
#: 0 und 100, also ausgerechnet dort, wo sie am wenigsten hingehört. Die
#: Beta-Verteilung läuft an den Rändern von selbst auf null aus und
#: braucht keinen Schnitt.
#:
#: ``2,0`` ergibt eine liegende Parabel um 50 mit einer Streuung von
#: 22,4 Punkten — mittig, aber spürbar breiter als eine gewöhnliche
#: Glockenkurve. Größere Werte machen die Kurve schmaler, kleinere
#: flacher; bei 1,0 wäre sie gleichverteilt.
DESCENT_BETA = 2.0

#: Form der Verteilung des Ausdauerwerts. Dieselbe Kurve wie beim
#: Abfahrtswert, aus denselben Gründen — und damit auch dieselbe
#: Lesart: 50 ist die Mitte, 0 und 100 sind selten, aber sie kommen vor.
ENDURANCE_BETA = 2.0

#: Ebenso für den Aerodynamikwert.
AERO_BETA = 2.0

#: Das Kletterprofil ist der einzige Wert, der **nicht** frei gewürfelt
#: wird: Rouleure sind eher schwere Fahrer, Kletterer eher leichte. Der
#: Anteil sagt, wie stark das Gewicht ihn bestimmt — der Rest ist Zufall,
#: damit es den leichten Rouleur weiterhin geben kann.
#:
#: Bei 0,6 liegt die Korrelation mit dem Gewicht bei −0,85: Das
#: leichteste Viertel des Feldes kommt im Mittel auf Profil 71, das
#: schwerste auf 28 — deutlich sichtbar, aber kein Wert, den man aus
#: der Waage ablesen könnte.
CLIMB_PROFILE_WEIGHT_SHARE = 0.6
CLIMB_PROFILE_BETA = 2.0


@dataclass(frozen=True)
class Team:
    id: int
    name: str
    color: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color}


@dataclass(frozen=True)
class Rider:
    id: int
    bib: int
    name: str
    nation: str
    team_id: int
    ftp_w: float
    weight_kg: float
    height_cm: float
    #: Wie beherzt er bergab fährt, 0 bis 100. Die einzige Eigenschaft,
    #: die nicht aus der Physik folgt — bei 100 rollt er ungebremst aus,
    #: bei 0 nimmt er die maximale Drosselung mit.
    descent_skill: float = 100.0
    #: Wie gut er die Leistung über die Stunden hält, 0 bis 100.
    #: **Fünfzig ist neutral**: Dort verläuft das Rennen wie ohne diesen
    #: Wert. Darüber wächst die Leistung mit der Fahrzeit, darunter
    #: fällt sie — je länger das Rennen, desto weiter geht die Schere
    #: auf.
    endurance: float = 50.0
    #: Wie sauber er auf dem Rad liegt, 0 bis 100. Wirkt auf den
    #: Luftwiderstand und damit überall dort, wo Luft der Hauptgegner
    #: ist — im Flachen also am stärksten. 50 ist neutral.
    aero: float = 50.0
    #: Kletterer oder Rouleur, 0 bis 100. Bei 100 drückt er am Anstieg
    #: und spart im Flachen, bei 0 umgekehrt; 50 fährt beides gleich.
    #: Der Wert folgt überwiegend dem Gewicht — Rouleure sind eher
    #: schwere Fahrer.
    climb_profile: float = 50.0

    # ------------------------------------------------------------------
    @property
    def descent_norm(self) -> float:
        """Der Abfahrtswert auf 0 bis 1, wie ihn die Physik erwartet."""
        return float(np.clip(self.descent_skill / 100.0, 0.0, 1.0))

    @property
    def endurance_dev(self) -> float:
        """Die Abweichung von der Mitte, −0,5 bis +0,5.

        In dieser Form geht der Wert in den Verfall ein: Bei fünfzig ist
        er null, und dann ist der Faktor unabhängig von der Fahrzeit
        genau eins.
        """
        return float(np.clip(self.endurance / 100.0, 0.0, 1.0)) - 0.5

    @property
    def aero_dev(self) -> float:
        """Der Aerodynamikwert als Abweichung von der Mitte."""
        return float(np.clip(self.aero / 100.0, 0.0, 1.0)) - 0.5

    @property
    def climb_profile_dev(self) -> float:
        """Das Kletterprofil als Abweichung von der Mitte.

        Positiv ist der Kletterer, negativ der Rouleur — und bei null
        verhält sich der Fahrer wie vor der Einführung des Werts.
        """
        return float(np.clip(self.climb_profile / 100.0, 0.0, 1.0)) - 0.5

    @property
    def frontal_area_m2(self) -> float:
        return float(physics.frontal_area(self.height_cm, self.weight_kg))

    @property
    def system_mass_kg(self) -> float:
        """Fahrer plus Rad — die Masse, die den Berg hinaufmuss."""
        return self.weight_kg + physics.BIKE_MASS_KG

    @property
    def w_per_kg(self) -> float:
        return self.ftp_w / self.weight_kg

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "bib": self.bib,
            "name": self.name,
            "nation": self.nation,
            "team_id": self.team_id,
            "ftp_w": round(self.ftp_w, 1),
            "weight_kg": round(self.weight_kg, 1),
            "height_cm": round(self.height_cm, 1),
            "descent_skill": round(self.descent_skill, 1),
            "endurance": round(self.endurance, 1),
            "aero": round(self.aero, 1),
            "climb_profile": round(self.climb_profile, 1),
        }


# ----------------------------------------------------------------------
def _team_color(index: int) -> str:
    """Farben gleichmäßig über den Farbkreis, mit Sprung.

    Der goldene Schnitt als Schrittweite verhindert, dass benachbarte
    Teams in der Startliste benachbarte Farbtöne bekommen — die Farbe
    ist das Einzige, was ein Team im Höhenprofil unterscheidbar macht.
    """
    hue = (index * 0.6180339887) % 1.0
    light = 0.52 + 0.10 * ((index % 3) - 1)
    r, g, b = colorsys.hls_to_rgb(hue, light, 0.62)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def generate_teams() -> list[Team]:
    """Die fünfundzwanzig Teams, in fester Reihenfolge."""
    return [Team(id=i, name=name, color=_team_color(i)) for i, name in enumerate(TEAM_NAMES)]


def generate_pool(seed: int = 20260101) -> tuple[list[Team], list[Rider]]:
    """Fünfundzwanzig Teams zu je zwölf Fahrern.

    Der Pool wird einmal erzeugt und bleibt dann stehen: Derselbe Seed
    liefert dieselben dreihundert Fahrer, Saison für Saison.
    """
    rng = np.random.default_rng(seed)
    teams = generate_teams()

    # Team-Offsets gleichmäßig verteilt, aber in zufälliger Zuordnung —
    # sonst wäre das erste Team der Liste immer das schwächste.
    offsets = np.linspace(-TEAM_OFFSET_SPAN, TEAM_OFFSET_SPAN, N_TEAMS)
    offsets = offsets[rng.permutation(N_TEAMS)]

    nations = list(NATIONS)
    weights = np.array([NATION_WEIGHTS[n] for n in nations], dtype=np.float64)
    weights /= weights.sum()

    riders: list[Rider] = []
    used_names: set[str] = set()
    rid = 0
    for team in teams:
        for _ in range(RIDERS_PER_TEAM):
            nation = nations[int(rng.choice(len(nations), p=weights))]
            name = _draw_name(rng, nation, used_names)

            height = float(np.clip(rng.normal(HEIGHT_MEAN, HEIGHT_SD), *HEIGHT_RANGE))
            bmi = float(np.clip(rng.normal(BMI_MEAN, BMI_SD), *BMI_RANGE))
            weight = float(np.clip(bmi * (height / 100.0) ** 2, *WEIGHT_RANGE))
            wkg = float(np.clip(rng.normal(WKG_MEAN, WKG_SD) + offsets[team.id], *WKG_RANGE))
            abfahrt = float(rng.beta(DESCENT_BETA, DESCENT_BETA) * 100.0)

            riders.append(
                Rider(
                    id=rid,
                    bib=rid + 1,
                    name=name,
                    nation=nation,
                    team_id=team.id,
                    ftp_w=wkg * weight,
                    weight_kg=weight,
                    height_cm=height,
                    descent_skill=abfahrt,
                )
            )
            rid += 1

    # Der Ausdauerwert wird **nach** allen anderen Ziehungen gewürfelt,
    # in einem Zug für das ganze Feld. Eine Ziehung mitten in der
    # Schleife hätte den Zufallsstrom verschoben — und damit Namen,
    # Körpermaße und FTP aller dreihundert Fahrer ausgetauscht, obwohl
    # nur eine Eigenschaft dazugekommen ist.
    n = len(riders)
    ausdauer = rng.beta(ENDURANCE_BETA, ENDURANCE_BETA, n) * 100.0
    aero = rng.beta(AERO_BETA, AERO_BETA, n) * 100.0

    # Das Kletterprofil: überwiegend das Gewicht, der Rest Zufall. Als
    # Rang statt als Kilogramm, damit der Wert die volle Skala von 0 bis
    # 100 nutzt, egal wie eng das Feld beieinanderliegt — und invertiert,
    # weil der leichteste Fahrer der Kletterer ist.
    gewicht = np.array([r.weight_kg for r in riders])
    rang = np.argsort(np.argsort(gewicht)) / (n - 1)
    wuerfel = rng.beta(CLIMB_PROFILE_BETA, CLIMB_PROFILE_BETA, n)
    profil = 100.0 * (
        CLIMB_PROFILE_WEIGHT_SHARE * (1.0 - rang)
        + (1.0 - CLIMB_PROFILE_WEIGHT_SHARE) * wuerfel
    )

    riders = [
        replace(r, endurance=float(e), aero=float(a), climb_profile=float(p))
        for r, e, a, p in zip(riders, ausdauer, aero, profil)
    ]
    return teams, riders


def _draw_name(rng: np.random.Generator, nation: str, used: set[str]) -> str:
    """Ein Name, der im Feld noch nicht vorkommt.

    Sechzehn mal sechzehn Kombinationen je Nation reichen für
    dreihundert Fahrer bequem; nach fünfzig Fehlversuchen bekommt der
    Nachname trotzdem ein Kürzel, damit die Schleife nicht hängt.
    """
    first = FIRST_NAMES[nation]
    last = LAST_NAMES[nation]
    for _ in range(50):
        name = f"{first[rng.integers(len(first))]} {last[rng.integers(len(last))]}"
        if name not in used:
            used.add(name)
            return name
    name = f"{first[rng.integers(len(first))]} {last[rng.integers(len(last))]}-{len(used)}"
    used.add(name)
    return name


__all__ = [
    "Rider",
    "Team",
    "generate_pool",
    "generate_teams",
    "FIELD_SIZE",
    "N_TEAMS",
    "RIDERS_PER_TEAM",
    "DESCENT_BETA",
    "ENDURANCE_BETA",
    "AERO_BETA",
    "CLIMB_PROFILE_BETA",
    "CLIMB_PROFILE_WEIGHT_SHARE",
]
