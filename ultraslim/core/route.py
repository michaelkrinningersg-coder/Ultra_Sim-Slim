"""Strecken: ein zweidimensionales Höhenprofil, sonst nichts.

Keine Karte, keine Koordinaten, keine Oberfläche, keine Kurven. Eine
Strecke ist ein Array von Steigungen auf einem gleichmäßigen
Hundert-Meter-Raster und die Höhe, die sich daraus aufsummiert.

Die Profile werden erzeugt, nicht importiert — aber deterministisch:
Derselbe Seed liefert dasselbe Profil. Die „Alpen-Rundfahrt" der zweiten
Saison ist Meter für Meter dieselbe wie die der ersten.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Auflösung des Rasters. Feiner bringt nichts — eine 100-Meter-Rampe
#: ist in einem Ultrarennen keine Entscheidung.
STEP_M = 100.0

#: Charakter der Archetypen. ``gap_km`` ist der welligen Zwischenteil
#: zwischen zwei Anstiegen, ``climb_km``/``climb_grade`` der Anstieg
#: selbst, ``descent_grade`` die Abfahrt danach. ``roll_amp`` ist die
#: Amplitude der Wellen im Zwischenteil, ``max_grade`` der Deckel.
ARCHETYPES: dict[str, dict] = {
    "flach": {
        "gap_km": (6.0, 15.0),
        "climb_km": (0.4, 1.4),
        "climb_grade": (0.015, 0.035),
        "descent_grade": (0.015, 0.035),
        "roll_amp": 0.008,
        "max_grade": 0.06,
        "base_ele_m": 5.0,
        "label": "flach",
    },
    "wellig": {
        "gap_km": (5.0, 13.0),
        "climb_km": (2.0, 6.5),
        "climb_grade": (0.035, 0.070),
        "descent_grade": (0.035, 0.080),
        "roll_amp": 0.012,
        "max_grade": 0.10,
        "base_ele_m": 180.0,
        "label": "wellig",
    },
    "mittelgebirge": {
        "gap_km": (7.0, 20.0),
        "climb_km": (6.0, 16.0),
        "climb_grade": (0.050, 0.085),
        "descent_grade": (0.045, 0.090),
        "roll_amp": 0.010,
        "max_grade": 0.13,
        "base_ele_m": 340.0,
        "label": "Mittelgebirge",
    },
    "hochgebirge": {
        "gap_km": (9.0, 24.0),
        "climb_km": (10.0, 24.0),
        "climb_grade": (0.060, 0.095),
        "descent_grade": (0.055, 0.090),
        "roll_amp": 0.010,
        "max_grade": 0.16,
        "base_ele_m": 700.0,
        "label": "Hochgebirge",
    },
}

#: Kategorie eines Anstiegs nach Höhenmetern. Die Grenzen sind an die
#: Radsportkonvention angelehnt, aber bewusst grob: Sie beschriften das
#: Profil, sie berechnen nichts.
CLIMB_CATEGORIES: tuple[tuple[float, str], ...] = (
    (1200.0, "HC"),
    (800.0, "1. Kat."),
    (500.0, "2. Kat."),
    (300.0, "3. Kat."),
    (150.0, "4. Kat."),
)

#: Unter dieser Höhe taucht ein Anstieg gar nicht erst im Profil auf.
CLIMB_MIN_ASCENT_M = 150.0

#: Ab dieser Kategorie kommt der Gipfel für eine eigene Zeitmessung in
#: Frage — höchstens ``MAX_SUMMIT_SPLITS`` davon, die höchsten zuerst.
#: Ohne Deckel hat die Alpenrunde dreiundzwanzig Zeitmessungen, und die
#: Auswahlliste im Board wird zur Bleiwüste.
SUMMIT_SPLIT_CATEGORIES = frozenset({"HC", "1. Kat."})
MAX_SUMMIT_SPLITS = 5

#: Ungefähre Zahl der Kontrollpunkte, Ziel nicht mitgezählt.
N_CONTROL_POINTS = 8


@dataclass(frozen=True)
class Climb:
    dist_start_m: float
    dist_end_m: float
    length_m: float
    ascent_m: float
    avg_grade: float
    category: str

    def to_dict(self) -> dict:
        return {
            "dist_start_m": round(self.dist_start_m, 1),
            "dist_end_m": round(self.dist_end_m, 1),
            "length_m": round(self.length_m, 1),
            "ascent_m": round(self.ascent_m, 1),
            "avg_grade": round(self.avg_grade, 4),
            "category": self.category,
        }


@dataclass(frozen=True)
class Split:
    idx: int
    name: str
    dist_m: float
    kind: str  # 'interval' | 'summit' | 'finish'

    def to_dict(self) -> dict:
        return {"idx": self.idx, "name": self.name, "dist_m": round(self.dist_m, 1), "kind": self.kind}


@dataclass
class Route:
    id: str
    name: str
    archetype: str
    distance_m: float
    step_m: float
    ele_m: np.ndarray      # (n+1,) Höhe an jedem Rasterpunkt
    grade: np.ndarray      # (n,)   Steigung jedes Segments
    climbs: list[Climb]
    splits: list[Split]

    # ------------------------------------------------------------------
    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000.0

    @property
    def ascent_m(self) -> float:
        return float(np.sum(np.maximum(self.grade, 0.0)) * self.step_m)

    @property
    def descent_m(self) -> float:
        return float(-np.sum(np.minimum(self.grade, 0.0)) * self.step_m)

    @property
    def max_elevation_m(self) -> float:
        return float(np.max(self.ele_m))

    @property
    def finish_split(self) -> Split:
        return self.splits[-1]

    def grade_at_index(self, idx: np.ndarray) -> np.ndarray:
        """Steigung an Rasterindizes — der heiße Pfad der Engine."""
        return self.grade[np.clip(idx, 0, len(self.grade) - 1)]

    def elevation_at_index(self, idx: np.ndarray) -> np.ndarray:
        return self.ele_m[np.clip(np.asarray(idx).astype(np.int64), 0, len(self.ele_m) - 1)]

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Was das Höhenprofil im Browser braucht.

        Das Raster ist gleichmäßig, deshalb reicht ``step_m`` — die
        Distanzachse baut der Client selbst. Das spart bei tausend
        Kilometern zehntausend Zahlen und macht die Indexsuche im
        Zeichner zu einer Division statt zu einer Schleife.
        """
        return {
            "id": self.id,
            "name": self.name,
            "archetype": self.archetype,
            "distance_m": round(self.distance_m, 1),
            "distance_km": round(self.distance_km, 2),
            "ascent_m": round(self.ascent_m),
            "max_elevation_m": round(self.max_elevation_m),
            "profile": {
                "step_m": self.step_m,
                "ele_m": [round(float(e), 1) for e in self.ele_m],
                "grade": [round(float(g), 4) for g in self.grade],
            },
            "climbs": [c.to_dict() for c in self.climbs],
            "splits": [s.to_dict() for s in self.splits],
        }

    # ------------------------------------------------------------------
    def to_storage(self) -> dict:
        """Die Fassung für die Platte.

        Gespeichert wird die **Steigung**, nicht die Höhe: Sie ist das,
        womit die Physik rechnet, und die Höhe folgt daraus durch
        Aufsummieren. Andersherum — Höhe speichern, Steigung ableiten —
        würde jeder Rundungsfehler in der Höhe zu einem Fehler in der
        Steigung, und fünf Nachkommastellen auf der Steigung sind ein
        Tausendstel Prozent, während dieselbe Genauigkeit auf der Höhe
        ein Vielfaches an Zeichen kostet.
        """
        return {
            "format": 1,
            "id": self.id,
            "name": self.name,
            "archetype": self.archetype,
            "step_m": self.step_m,
            "base_ele_m": round(float(self.ele_m[0]), 2),
            "grade": [round(float(g), 5) for g in self.grade],
            "climbs": [c.to_dict() for c in self.climbs],
            "splits": [s.to_dict() for s in self.splits],
        }

    @classmethod
    def from_storage(cls, data: dict) -> Route:
        grade = np.asarray(data["grade"], dtype=np.float64)
        step = float(data.get("step_m", STEP_M))
        ele = np.concatenate(
            [[float(data["base_ele_m"])], float(data["base_ele_m"]) + np.cumsum(grade * step)]
        )
        return cls(
            id=data["id"],
            name=data["name"],
            archetype=data.get("archetype", "wellig"),
            distance_m=len(grade) * step,
            step_m=step,
            ele_m=ele,
            grade=grade,
            climbs=[
                Climb(
                    dist_start_m=c["dist_start_m"],
                    dist_end_m=c["dist_end_m"],
                    length_m=c["length_m"],
                    ascent_m=c["ascent_m"],
                    avg_grade=c["avg_grade"],
                    category=c["category"],
                )
                for c in data.get("climbs", [])
            ],
            splits=[
                Split(idx=s["idx"], name=s["name"], dist_m=s["dist_m"], kind=s["kind"])
                for s in data.get("splits", [])
            ],
        )

    def summary(self) -> dict:
        """Die Zeile für Kalender und Übersicht — ohne das Profil."""
        return {
            "id": self.id,
            "name": self.name,
            "archetype": self.archetype,
            "archetype_label": ARCHETYPES[self.archetype]["label"],
            "distance_km": round(self.distance_km, 1),
            "ascent_m": round(self.ascent_m),
            "max_elevation_m": round(self.max_elevation_m),
            "n_climbs": len(self.climbs),
            "n_splits": len(self.splits),
        }


# ----------------------------------------------------------------------
# Generator
# ----------------------------------------------------------------------
def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    """Gleitender Mittelwert mit gespiegelten Rändern.

    Ohne Glättung ist das Profil ein Zackenkamm, in dem jede Steigung
    eine Sekunde hält — die Trägheit im Integrator bügelt das zwar aus,
    aber gezeichnet sieht es aus wie ein Messfehler.
    """
    if window < 2 or values.size == 0:
        return values
    pad = min(window, values.size)
    padded = np.concatenate([values[:pad][::-1], values, values[-pad:][::-1]])
    kernel = np.ones(window) / window
    return np.convolve(padded, kernel, mode="same")[pad : pad + values.size]


def _rolling(rng: np.random.Generator, n: int, amp: float) -> np.ndarray:
    """Welliger Zwischenteil mit Mittelwert null.

    Er darf keine Höhe aufbauen — sonst driftet das Profil über
    tausend Kilometer in den Weltraum oder unter den Meeresspiegel.
    """
    if n <= 0:
        return np.zeros(0)
    raw = _smooth(rng.normal(0.0, 1.0, n), max(2, min(n, 15)))
    raw -= raw.mean()
    scale = np.max(np.abs(raw))
    return raw * (amp / scale) if scale > 1e-9 else raw


def _climb_shape(rng: np.random.Generator, n: int, mean_grade: float) -> np.ndarray:
    """Ein Anstieg mit Rampen und Flachstücken, im Mittel ``mean_grade``.

    Ein Pass mit konstanten 7 % ist eine Rechenaufgabe, kein Anstieg.
    Die Variation macht daraus eine Reihenfolge von Abschnitten, in der
    die steile Stelle irgendwo liegt und nicht überall.
    """
    if n <= 0:
        return np.zeros(0)
    variation = _smooth(rng.normal(0.0, 1.0, n), max(2, min(n, 20)))
    variation -= variation.mean()
    scale = np.max(np.abs(variation))
    if scale > 1e-9:
        variation *= (mean_grade * 0.55) / scale
    return np.maximum(mean_grade + variation, 0.004)


def _raw_grades(rng: np.random.Generator, n: int, params: dict) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Die Steigungsfolge und wo darin die Anstiege liegen.

    Aufgebaut in Blöcken: welliger Zwischenteil, Anstieg, Abfahrt. Die
    Abfahrt gibt genau die Höhe zurück, die der Anstieg geholt hat —
    dadurch endet die Strecke ungefähr dort, wo sie angefangen hat.
    """
    grade = np.zeros(n)
    climbs: list[tuple[int, int]] = []
    i = 0
    while i < n:
        gap = int(rng.uniform(*params["gap_km"]) * 1000 / STEP_M)
        gap = min(gap, n - i)
        if gap > 0:
            grade[i : i + gap] = _rolling(rng, gap, params["roll_amp"])
            i += gap
        if i >= n:
            break

        climb_len = int(rng.uniform(*params["climb_km"]) * 1000 / STEP_M)
        climb_len = min(climb_len, n - i)
        if climb_len <= 0:
            break
        mean_grade = float(rng.uniform(*params["climb_grade"]))
        shape = _climb_shape(rng, climb_len, mean_grade)
        grade[i : i + climb_len] = shape
        climbs.append((i, i + climb_len))
        gained = float(np.sum(shape) * STEP_M)
        i += climb_len
        if i >= n:
            break

        desc_grade = float(rng.uniform(*params["descent_grade"]))
        desc_len = min(max(int(gained / desc_grade / STEP_M), 1), n - i)
        if desc_len > 0:
            # Die Abfahrt trägt exakt die gewonnene Höhe ab, verteilt
            # mit derselben Unruhe wie der Anstieg.
            shape = _climb_shape(rng, desc_len, gained / (desc_len * STEP_M))
            grade[i : i + desc_len] = -shape
            i += desc_len
    return grade, climbs


def _categorise(ascent_m: float) -> str | None:
    for limit, label in CLIMB_CATEGORIES:
        if ascent_m >= limit:
            return label
    return None


def _build_splits(distance_m: float, climbs: list[Climb]) -> list[Split]:
    """Kontrollpunkte in gleichen Abständen, dazu große Gipfel und Ziel."""
    marks: list[tuple[float, str, str]] = []
    spacing = distance_m / (N_CONTROL_POINTS + 1)
    for k in range(1, N_CONTROL_POINTS + 1):
        marks.append((spacing * k, f"KP {k}", "interval"))
    big = [c for c in climbs if c.category in SUMMIT_SPLIT_CATEGORIES]
    big.sort(key=lambda c: c.ascent_m, reverse=True)
    for climb in big[:MAX_SUMMIT_SPLITS]:
        marks.append((climb.dist_end_m, f"Gipfel km {climb.dist_end_m / 1000:.0f}", "summit"))
    marks.append((distance_m, "Ziel", "finish"))

    marks.sort(key=lambda m: m[0])
    return [Split(idx=i, name=name, dist_m=dist, kind=kind) for i, (dist, name, kind) in enumerate(marks)]


def generate_route(
    route_id: str,
    name: str,
    distance_km: float,
    archetype: str,
    ascent_m: float,
    seed: int,
) -> Route:
    """Ein Profil aus Archetyp, Länge und Ziel-Höhenmetern.

    Die Höhenmeter werden nicht erwürfelt, sondern getroffen: Erst
    entsteht die Form, dann wird sie linear skaliert, bis die Summe der
    positiven Steigungen dem Ziel entspricht. Ascent ist exakt linear im
    Skalierungsfaktor, ein Durchgang genügt also — nur die anschließende
    Begrenzung auf die Maximalsteigung braucht ein paar Korrekturen.
    """
    params = ARCHETYPES[archetype]
    rng = np.random.default_rng(seed)
    n = int(round(distance_km * 1000 / STEP_M))

    grade, climb_spans = _raw_grades(rng, n, params)

    for _ in range(6):
        current = float(np.sum(np.maximum(grade, 0.0)) * STEP_M)
        if current <= 1e-6:
            break
        grade = np.clip(grade * (ascent_m / current), -params["max_grade"], params["max_grade"])
        if abs(float(np.sum(np.maximum(grade, 0.0)) * STEP_M) - ascent_m) < ascent_m * 0.005:
            break

    ele = np.empty(n + 1)
    ele[0] = params["base_ele_m"]
    np.cumsum(grade * STEP_M, out=ele[1:])
    ele[1:] += params["base_ele_m"]
    # Kein Profil unter Normalnull: Die Blöcke gleichen sich nur
    # ungefähr aus, und eine Strecke, die 40 m unter dem Meer verläuft,
    # sieht im Diagramm nach Fehler aus.
    dip = float(np.min(ele))
    if dip < 0.0:
        ele -= dip

    climbs: list[Climb] = []
    for start, end in climb_spans:
        gain = float(np.sum(grade[start:end]) * STEP_M)
        if gain < CLIMB_MIN_ASCENT_M:
            continue
        category = _categorise(gain)
        if category is None:
            continue
        length = (end - start) * STEP_M
        climbs.append(
            Climb(
                dist_start_m=start * STEP_M,
                dist_end_m=end * STEP_M,
                length_m=length,
                ascent_m=gain,
                avg_grade=gain / length,
                category=category,
            )
        )

    distance_m = n * STEP_M
    return Route(
        id=route_id,
        name=name,
        archetype=archetype,
        distance_m=distance_m,
        step_m=STEP_M,
        ele_m=ele,
        grade=grade,
        climbs=climbs,
        splits=_build_splits(distance_m, climbs),
    )


__all__ = ["Route", "Climb", "Split", "generate_route", "ARCHETYPES", "STEP_M"]
