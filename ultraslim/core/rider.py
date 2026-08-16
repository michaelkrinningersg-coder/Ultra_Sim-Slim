"""Fahrer, Teams und der Generator für den Pool.

Ein Fahrer hat in dieser Fassung genau drei Eigenschaften: **FTP,
Gewicht, Größe**. Alles andere — Form, Ermüdung, Magen, Schlaf,
Charakter — ist bewusst nicht da. Was ein Fahrer kann, steckt
vollständig in diesen drei Zahlen und in dem, was die Physik daraus
macht.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

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
WEIGHT_RANGE = (55.0, 88.0)

#: Relative FTP in Watt je Kilogramm Körpergewicht.
WKG_MEAN = 4.40
WKG_SD = 0.45
WKG_RANGE = (3.30, 5.60)

#: Spannweite des Team-Offsets auf die relative FTP. Ohne ihn wären die
#: fünfundzwanzig Teams statistisch nicht unterscheidbar und die
#: Teamwertung eine Zufallszahl.
TEAM_OFFSET_SPAN = 0.35


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

    # ------------------------------------------------------------------
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
            bmi = float(rng.normal(BMI_MEAN, BMI_SD))
            weight = float(np.clip(bmi * (height / 100.0) ** 2, *WEIGHT_RANGE))
            wkg = float(np.clip(rng.normal(WKG_MEAN, WKG_SD) + offsets[team.id], *WKG_RANGE))

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
                )
            )
            rid += 1
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
]
