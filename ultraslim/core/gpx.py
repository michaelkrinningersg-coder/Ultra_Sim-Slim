"""GPX einlesen und in ein Höhenprofil verwandeln.

Aus einer Datei mit ein paar tausend Trackpunkten wird dieselbe Sorte
Strecke, die auch der Generator liefert: Steigungen auf einem
gleichmäßigen Hundert-Meter-Raster. Was danach im Spiel liegt, ist ein
Profil — die GPX-Datei selbst wird nicht aufgehoben, sie wäre ein
Vielfaches größer und würde nie wieder gelesen.

**Die Glättung ist der eigentliche Schritt, nicht Beiwerk.** Rohe
GPX-Höhen schwanken um ein bis drei Meter von Punkt zu Punkt — mal
barometrisch gemessen, mal aus einem Höhenmodell nachgeschlagen, immer
verrauscht. Über zehntausend Punkte summiert sich dieses Rauschen zu
Höhenmetern, die es nie gab: Eine Alpenetappe kommt ungeglättet leicht
auf das Doppelte des echten Werts. Und im Modell ist das nicht nur eine
falsche Zahl, sondern falsche Physik — jeder erfundene Meter kostet den
Fahrer echte Energie.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np

from .route import STEP_M, Climb, Route, _build_splits, _categorise, CLIMB_MIN_ASCENT_M

#: Erdradius für die Haversine-Formel.
EARTH_RADIUS_M = 6371008.8

#: Standardfenster der Glättung, in Metern Wegstrecke. Rund zweihundert
#: Meter entsprechen ungefähr dem, was Strava und Komoot anzeigen — die
#: Höhenmeter kommen damit nah an das, was auf dem Portal steht, aus dem
#: die Datei stammt.
DEFAULT_SMOOTH_M = 200.0
SMOOTH_RANGE_M = (0.0, 1000.0)

#: Steigungsdeckel für importierte Profile. Auch nach der Glättung
#: bleiben in GPX-Dateien einzelne Ausreißer stehen — ein Tunnel, ein
#: Brückenpfeiler, ein Sprung im Höhenmodell. Dreißig Prozent fährt
#: niemand, und im Integrator wäre so eine Rampe eine Vollbremsung.
MAX_IMPORT_GRADE = 0.25

#: Weniger als das ergibt keine Strecke.
MIN_DISTANCE_M = 1000.0


class GpxError(ValueError):
    """Die Datei lässt sich nicht als Strecke lesen."""


@dataclass
class GpxTrack:
    """Die rohe Spur: kumulierte Distanz und Höhe, Punkt für Punkt.

    Zwischenschritt zwischen Datei und Profil. Sie bleibt erhalten,
    solange der Nutzer am Glättungsregler dreht — jede Stellung baut aus
    derselben Spur ein neues Profil, ohne die Datei erneut zu lesen.
    """

    name: str
    dist_m: np.ndarray
    ele_m: np.ndarray

    @property
    def distance_m(self) -> float:
        return float(self.dist_m[-1])

    @property
    def n_points(self) -> int:
        return int(self.dist_m.size)

    @property
    def raw_ascent_m(self) -> float:
        """Höhenmeter ohne jede Glättung — die Zahl, die zu hoch ist."""
        return float(np.sum(np.maximum(np.diff(self.ele_m), 0.0)))


# ----------------------------------------------------------------------
# Lesen
# ----------------------------------------------------------------------
def _local(tag: str) -> str:
    """Tagname ohne Namensraum.

    GPX gibt es als 1.0 und 1.1, und manche Programme hängen eigene
    Namensräume an. Auf den Namensraum zu prüfen hieße, an der nächsten
    Uhr zu scheitern.
    """
    return tag.rsplit("}", 1)[-1]


def _points(root: ET.Element) -> list[tuple[float, float, float | None]]:
    """Alle Trackpunkte in Dateireihenfolge, sonst Routenpunkte."""
    for wanted in ("trkpt", "rtept", "wpt"):
        found: list[tuple[float, float, float | None]] = []
        for node in root.iter():
            if _local(node.tag) != wanted:
                continue
            try:
                lat = float(node.attrib["lat"])
                lon = float(node.attrib["lon"])
            except (KeyError, ValueError):
                continue
            ele: float | None = None
            for child in node:
                if _local(child.tag) == "ele" and child.text:
                    try:
                        ele = float(child.text.strip())
                    except ValueError:
                        ele = None
                    break
            found.append((lat, lon, ele))
        if len(found) >= 2:
            return found
    return []


def _track_name(root: ET.Element, fallback: str) -> str:
    for node in root.iter():
        if _local(node.tag) == "name" and node.text and node.text.strip():
            return node.text.strip()[:80]
    return fallback


def _haversine(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Abstand zweier Punktfolgen auf der Kugel, in Metern."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def read_gpx(data: bytes | str, fallback_name: str = "Importierte Strecke") -> GpxTrack:
    """Eine GPX-Datei in eine Spur verwandeln.

    Fehlende Höhen werden zwischen den Nachbarn interpoliert; fehlt sie
    überall, ist die Datei für diesen Zweck wertlos und das wird gesagt.
    """
    if isinstance(data, bytes):
        # Manche Exporte tragen eine BOM oder eine falsche Deklaration.
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = data
    text = text.lstrip()

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise GpxError(f"Die Datei ist kein gültiges XML: {exc}") from exc

    raw = _points(root)
    if len(raw) < 2:
        raise GpxError("Die Datei enthält keine Trackpunkte.")

    lat = np.array([p[0] for p in raw], dtype=np.float64)
    lon = np.array([p[1] for p in raw], dtype=np.float64)
    ele = np.array([np.nan if p[2] is None else p[2] for p in raw], dtype=np.float64)

    if np.all(np.isnan(ele)):
        raise GpxError(
            "Die Datei enthält keine Höhenangaben. Ohne Höhenprofil gibt es "
            "nichts zu simulieren."
        )
    if np.any(np.isnan(ele)):
        gueltig = ~np.isnan(ele)
        ele = np.interp(np.arange(ele.size), np.flatnonzero(gueltig), ele[gueltig])

    schritte = _haversine(lat[:-1], lon[:-1], lat[1:], lon[1:])
    dist = np.concatenate([[0.0], np.cumsum(schritte)])

    # Stehende Punkte werfen den Interpolator; eine Pause an der Ampel
    # ist kein Streckenabschnitt.
    behalten = np.concatenate([[True], np.diff(dist) > 1e-6])
    dist, ele = dist[behalten], ele[behalten]

    if dist.size < 2 or dist[-1] < MIN_DISTANCE_M:
        raise GpxError(
            f"Die Strecke ist nur {dist[-1] if dist.size else 0:.0f} m lang — "
            f"mindestens {MIN_DISTANCE_M:.0f} m werden gebraucht."
        )

    return GpxTrack(name=_track_name(root, fallback_name), dist_m=dist, ele_m=ele)


# ----------------------------------------------------------------------
# Profil bauen
# ----------------------------------------------------------------------
def _resample(track: GpxTrack, n_cells: int) -> np.ndarray:
    """Höhe an jedem Rasterpunkt, gemittelt statt gegriffen.

    Nicht die Höhe *am* Rasterpunkt, sondern der Mittelwert aller
    Trackpunkte davor und danach. Bloßes Abgreifen würde das Rauschen des
    zufällig getroffenen Punktes übernehmen; der Mittelwert nimmt schon
    hier den größten Teil heraus, bevor die eigentliche Glättung greift.
    """
    grid = np.arange(n_cells + 1, dtype=np.float64) * STEP_M
    # Zuordnung jedes Trackpunkts zu seiner Zelle.
    zelle = np.clip((track.dist_m / STEP_M).astype(np.int64), 0, n_cells)
    summe = np.bincount(zelle, weights=track.ele_m, minlength=n_cells + 1)
    anzahl = np.bincount(zelle, minlength=n_cells + 1)

    ele = np.full(n_cells + 1, np.nan)
    belegt = anzahl > 0
    ele[belegt] = summe[belegt] / anzahl[belegt]
    if not belegt.all():
        # Lücken schließen — bei grob aufgezeichneten Spuren liegen
        # zwischen zwei Punkten schon mal mehr als hundert Meter.
        ele = np.interp(grid, grid[belegt], ele[belegt])
    return ele


def _smooth_m(values: np.ndarray, window_m: float) -> np.ndarray:
    """Gleitender Mittelwert über ein Fenster in Metern Wegstrecke."""
    fenster = int(round(window_m / STEP_M))
    if fenster < 2 or values.size < 3:
        return values
    fenster = min(fenster, values.size)
    if fenster % 2 == 0:
        fenster += 1  # ungerade, damit das Fenster mittig sitzt
    rand = fenster // 2
    # Ränder spiegeln statt mit Nullen aufzufüllen: Sonst zieht die
    # Glättung Start und Ziel künstlich in die Ebene.
    erweitert = np.concatenate([values[1 : rand + 1][::-1], values, values[-rand - 1 : -1][::-1]])
    kern = np.ones(fenster) / fenster
    return np.convolve(erweitert, kern, mode="valid")


def build_route(
    track: GpxTrack,
    route_id: str,
    name: str | None = None,
    smooth_m: float = DEFAULT_SMOOTH_M,
    target_ascent_m: float | None = None,
) -> Route:
    """Aus einer Spur ein fahrbares Profil.

    ``smooth_m`` ist die Fensterbreite der Glättung in Metern
    Wegstrecke — der Regler, an dem der Nutzer dreht. ``target_ascent_m``
    skaliert das Ergebnis anschließend auf eine vorgegebene Höhenmeterzahl;
    ohne Vorgabe bleibt stehen, was die Glättung ergeben hat.
    """
    smooth_m = float(np.clip(smooth_m, *SMOOTH_RANGE_M))
    n_cells = max(int(round(track.distance_m / STEP_M)), 1)

    ele = _smooth_m(_resample(track, n_cells), smooth_m)
    grade = np.clip(np.diff(ele) / STEP_M, -MAX_IMPORT_GRADE, MAX_IMPORT_GRADE)

    if target_ascent_m is not None:
        ascent = float(np.sum(np.maximum(grade, 0.0)) * STEP_M)
        if ascent > 1e-6:
            grade = np.clip(
                grade * (target_ascent_m / ascent), -MAX_IMPORT_GRADE, MAX_IMPORT_GRADE
            )

    # Die Höhe aus der (gedeckelten, ggf. skalierten) Steigung neu
    # aufbauen, damit Profil und Steigung zueinander passen.
    ele = np.concatenate([[float(ele[0])], float(ele[0]) + np.cumsum(grade * STEP_M)])
    dip = float(np.min(ele))
    if dip < 0.0:
        ele = ele - dip

    distance_m = n_cells * STEP_M
    climbs = _detect_climbs(grade)
    return Route(
        id=route_id,
        name=name or track.name,
        archetype=_archetype_for(distance_m, float(np.sum(np.maximum(grade, 0.0)) * STEP_M)),
        distance_m=distance_m,
        step_m=STEP_M,
        ele_m=ele,
        grade=grade,
        climbs=climbs,
        splits=_build_splits(distance_m, climbs),
    )


def _detect_climbs(grade: np.ndarray) -> list[Climb]:
    """Anstiege aus der Steigungsfolge herauslesen.

    Der Generator weiß, wo er einen Anstieg gebaut hat. Eine importierte
    Strecke weiß es nicht — hier muss er gefunden werden: eine Folge
    überwiegend steigender Zellen, unterbrochen höchstens von kurzen
    Flachstücken.
    """
    #: So weit darf es flach oder abwärts gehen, ohne dass der Anstieg
    #: als beendet gilt. Achthundert Meter Zwischenflachstück gehören
    #: noch zum Pass, zwei Kilometer nicht mehr.
    LUECKE = 8
    STEIGT = 0.015

    climbs: list[Climb] = []
    start: int | None = None
    luecke = 0
    for i, g in enumerate(grade):
        if g >= STEIGT:
            if start is None:
                start = i
            luecke = 0
        elif start is not None:
            luecke += 1
            if luecke > LUECKE:
                climbs.append(_climb_from(grade, start, i - luecke + 1))
                start, luecke = None, 0
    if start is not None:
        climbs.append(_climb_from(grade, start, len(grade)))

    return [c for c in climbs if c is not None]


def _climb_from(grade: np.ndarray, start: int, end: int) -> Climb | None:
    if end <= start:
        return None
    gain = float(np.sum(grade[start:end]) * STEP_M)
    if gain < CLIMB_MIN_ASCENT_M:
        return None
    kategorie = _categorise(gain)
    if kategorie is None:
        return None
    length = (end - start) * STEP_M
    return Climb(
        dist_start_m=start * STEP_M,
        dist_end_m=end * STEP_M,
        length_m=length,
        ascent_m=gain,
        avg_grade=gain / length,
        category=kategorie,
    )


def _archetype_for(distance_m: float, ascent_m: float) -> str:
    """Nur eine Beschriftung — importierte Profile haben keinen Archetyp."""
    je_100km = ascent_m / max(distance_m / 100_000.0, 1e-6)
    if je_100km < 500:
        return "flach"
    if je_100km < 1200:
        return "wellig"
    if je_100km < 1900:
        return "mittelgebirge"
    return "hochgebirge"


def slugify(name: str, prefix: str = "gpx") -> str:
    """Eine Kennung, die als Dateiname und in einer URL taugt."""
    klein = name.strip().lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        klein = klein.replace(alt, neu)
    klein = re.sub(r"[^a-z0-9]+", "-", klein).strip("-")
    return f"{prefix}-{klein}"[:60] if klein else prefix


__all__ = [
    "GpxError",
    "GpxTrack",
    "read_gpx",
    "build_route",
    "slugify",
    "DEFAULT_SMOOTH_M",
    "SMOOTH_RANGE_M",
    "MAX_IMPORT_GRADE",
]
