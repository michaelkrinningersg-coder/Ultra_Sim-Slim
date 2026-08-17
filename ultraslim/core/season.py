"""Saison: Kalender, Punkte, Wertungen — und der Speicher dahinter.

Eine Saison ist eine feste Liste von sechs Terminen. Die Strecken sind
über alle Saisons hinweg dieselben; was sich ändert, ist die Tagesform
des Feldes, und die hängt am Renn-Seed.

Gerechnet wird ein Rennen erst, wenn jemand zusieht. Was hier liegt,
sind ausschließlich **Ergebnisse abgeschlossener Rennen** — die
Wertungstabellen sind die Summe dessen, was schon passiert ist, nie eine
Vorhersage dessen, was noch kommt.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .rider import Rider, Team
from .route import Route, generate_route

#: So viele Fahrer eines Rennens bekommen Punkte.
SCORING_PLACES = 150

#: Die Punkte der Ränge eins bis zwanzig, von Hand gesetzt. Steil oben,
#: damit ein Sieg zählt.
TOP_POINTS: tuple[int, ...] = (
    100, 80, 65, 55, 50, 45, 40, 36, 32, 28,
    26, 24, 22, 20, 18, 16, 14, 12, 10, 8,
)

#: Der Rest bis Rang 150, als abklingende Kurve statt als Zahlenwüste.
#:
#: Sie beginnt bei sieben (Rang 20 hat acht) und endet bei eins. Der
#: Exponent 1,5 macht sie oben steiler als unten: Zwischen Rang 25 und
#: 35 liegt spürbar mehr als zwischen 130 und 140, und das ist auch
#: richtig so. Der Sockel von einem Punkt sorgt dafür, dass Rang 150
#: noch etwas wert ist — sonst wäre die Grenze eine Klippe statt eines
#: Auslaufs.
_TAIL_TOP = 6
_TAIL_EXP = 1.5


def _build_points() -> tuple[int, ...]:
    tail_span = SCORING_PLACES - len(TOP_POINTS) - 1
    tail = [
        round(_TAIL_TOP * ((SCORING_PLACES - rank) / tail_span) ** _TAIL_EXP) + 1
        for rank in range(len(TOP_POINTS) + 1, SCORING_PLACES + 1)
    ]
    return TOP_POINTS + tuple(tail)


#: Punkte je Rang, Index null ist Rang eins.
POINTS: tuple[int, ...] = _build_points()


def points_for_rank(rank: int) -> int:
    return POINTS[rank - 1] if 1 <= rank <= len(POINTS) else 0


@dataclass(frozen=True)
class RaceSpec:
    """Ein Termin im Kalender.

    Zwei Herkünfte, ein Typ: Ein Termin verweist entweder auf ein
    erzeugtes Profil — dann steht in ``route_seed``, woraus es entsteht —
    oder auf ein importiertes, das im Streckenlager liegt.
    """

    idx: int
    route_id: str
    name: str
    distance_km: float
    archetype: str
    ascent_m: float
    #: Seed des erzeugten Profils. Über alle Saisons gleich — die Strecke
    #: bleibt. ``None`` heißt: aus einer GPX-Datei importiert.
    route_seed: int | None = None
    #: Gastgebernationen der Strecke. Ihre Fahrer bekommen den
    #: Heimvorteil. Es dürfen mehrere sein — die Alpen liegen in vier
    #: Ländern —, und es dürfen keine sein: Eine importierte Strecke
    #: weiß nicht, wo sie liegt, und für die Pyrenäen hat das Feld keine
    #: passende Nation.
    home_nations: tuple[str, ...] = ()

    @property
    def imported(self) -> bool:
        return self.route_seed is None

    def to_dict(self) -> dict:
        return {
            "idx": self.idx,
            "route_id": self.route_id,
            "name": self.name,
            "distance_km": self.distance_km,
            "archetype": self.archetype,
            "ascent_m": self.ascent_m,
            "route_seed": self.route_seed,
            "home_nations": list(self.home_nations),
        }

    @classmethod
    def from_dict(cls, data: dict) -> RaceSpec:
        return cls(
            idx=int(data["idx"]),
            route_id=str(data["route_id"]),
            name=str(data["name"]),
            distance_km=float(data["distance_km"]),
            archetype=str(data.get("archetype", "wellig")),
            ascent_m=float(data["ascent_m"]),
            route_seed=data.get("route_seed"),
        )


#: Der Kalender. Sechs Rennen von 300 bis 1000 Kilometern: eines flach,
#: zwei wellig, zwei im Mittelgebirge, eines im Hochgebirge.
CALENDAR: tuple[RaceSpec, ...] = (
    RaceSpec(0, "ostsee", "Ostsee-Nachtfahrt", 300, "flach", 900, 1000, ("GER", "NED")),
    RaceSpec(1, "toskana", "Toskana-Hügelmarathon", 400, "wellig", 3600, 1001, ("ITA",)),
    RaceSpec(2, "ardennen", "Ardennen-Wellenritt", 600, "wellig", 5400, 1002, ("BEL", "NED")),
    RaceSpec(3, "karpaten", "Karpaten-Traverse", 700, "mittelgebirge", 10500, 1003, ("AUT",)),
    # Die Pyrenäen liegen in keinem Land, das im Feld vertreten ist —
    # dort gibt es keinen Heimvorteil, und das ist ehrlicher, als eine
    # Nation dazuzuerfinden.
    RaceSpec(4, "pyrenaeen", "Pyrenäen-Überquerung", 850, "mittelgebirge", 13000, 1004),
    RaceSpec(5, "alpen", "Alpen-Hochgebirgsmarathon", 1000, "hochgebirge", 23000, 1005,
             ("AUT", "SUI", "ITA", "GER")),
)

#: Die mitgelieferten Saisons. Gleiche Strecken, andere Tagesform.
SEASON_YEARS: tuple[int, ...] = (2026, 2027, 2028)


@dataclass(frozen=True)
class Season:
    """Ein Kalender mit Namen.

    Die mitgelieferten Saisons teilen sich ``CALENDAR``; eine
    selbstgebaute bringt ihre eigene Rennliste mit.
    """

    id: str
    year: int
    name: str
    races: tuple[RaceSpec, ...] = CALENDAR
    #: Selbst angelegt und damit löschbar.
    custom: bool = False
    #: Basis für Tagesform und Trittrauschen. Ohne Angabe aus dem Jahr.
    seed: int | None = None

    def race_seed(self, spec: RaceSpec) -> int:
        """Der Seed, aus dem Tagesform und Trittrauschen entstehen."""
        return (self.seed if self.seed is not None else self.year * 1000) + spec.idx

    def race_id(self, spec: RaceSpec) -> str:
        return f"{self.id}-{spec.route_id}"

    def spec_for(self, route_id: str) -> RaceSpec | None:
        return next((r for r in self.races if r.route_id == route_id), None)

    def to_dict(self) -> dict:
        return {
            "format": 1,
            "id": self.id,
            "year": self.year,
            "name": self.name,
            "seed": self.seed,
            "races": [r.to_dict() for r in self.races],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Season:
        rennen = [RaceSpec.from_dict(r) for r in data.get("races", [])]
        # Die Indizes bestimmen die Spalten jeder Wertungstabelle; eine
        # Lücke darin wäre eine leere Spalte.
        rennen = [
            RaceSpec.from_dict({**r.to_dict(), "idx": i}) for i, r in enumerate(rennen)
        ]
        return cls(
            id=str(data["id"]),
            year=int(data.get("year", 0)),
            name=str(data["name"]),
            races=tuple(rennen),
            custom=True,
            seed=data.get("seed"),
        )


BUILTIN_SEASONS: tuple[Season, ...] = tuple(
    Season(id=f"s{y}", year=y, name=f"Saison {y}") for y in SEASON_YEARS
)


def all_seasons(store: "Store | None" = None) -> list[Season]:
    """Mitgelieferte Saisons, danach die selbst angelegten."""
    eigene = store.load_seasons() if store is not None else []
    return [*BUILTIN_SEASONS, *eigene]


def get_season(season_id: str, store: "Store | None" = None) -> Season | None:
    return next((s for s in all_seasons(store) if s.id == season_id), None)


def get_race_spec(route_id: str, season: Season | None = None) -> RaceSpec | None:
    quelle = season.races if season is not None else CALENDAR
    return next((r for r in quelle if r.route_id == route_id), None)


def build_route(spec: RaceSpec, store: "Store | None" = None) -> Route:
    """Das Profil eines Termins.

    Erzeugt aus dem Seed, oder aus dem Streckenlager geladen — von außen
    ist beides dasselbe.
    """
    if spec.imported:
        if store is None:
            raise LookupError(f"Für '{spec.route_id}' wird das Streckenlager gebraucht.")
        route = store.load_route(spec.route_id)
        if route is None:
            raise LookupError(f"Die importierte Strecke '{spec.route_id}' fehlt.")
        return route
    return generate_route(
        route_id=spec.route_id,
        name=spec.name,
        distance_km=spec.distance_km,
        archetype=spec.archetype,
        ascent_m=spec.ascent_m,
        seed=spec.route_seed,
    )


# ----------------------------------------------------------------------
# Speicher
# ----------------------------------------------------------------------
@dataclass
class RaceResult:
    """Das Ergebnis eines abgeschlossenen Rennens."""

    season_id: str
    route_id: str
    #: (rider_id, Zielzeit in Sekunden), nach Zeit sortiert.
    finishers: list[tuple[int, float]]
    #: Bergpunkte dieses Rennens, ``rider_id → Punkte``. Nur wer welche
    #: hat, steht drin — bei dreihundert Fahrern und einer Handvoll
    #: Kletterern wäre der Rest eine Liste von Nullen.
    climb_points: dict[int, int] = field(default_factory=dict)

    @property
    def winner_time_s(self) -> float | None:
        return self.finishers[0][1] if self.finishers else None

    def ranking(self) -> list[tuple[int, int, float]]:
        """(Rang, rider_id, Zeit) — Rang eins beginnt bei eins."""
        return [(i + 1, rid, t) for i, (rid, t) in enumerate(self.finishers)]

    def to_dict(self) -> dict:
        return {
            "season_id": self.season_id,
            "route_id": self.route_id,
            "finishers": [[int(r), round(float(t), 2)] for r, t in self.finishers],
            "climb_points": {str(k): int(v) for k, v in self.climb_points.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> RaceResult:
        return cls(
            season_id=data["season_id"],
            route_id=data["route_id"],
            finishers=[(int(r), float(t)) for r, t in data["finishers"]],
            climb_points={int(k): int(v) for k, v in data.get("climb_points", {}).items()},
        )


class Store:
    """Ergebnisse auf der Platte. Ein JSON je Rennen, mehr braucht es nicht."""

    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, season_id: str, route_id: str) -> Path:
        directory = self.root / "results" / season_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{route_id}.json"

    def save(self, result: RaceResult) -> None:
        self._write_atomic(self._path(result.season_id, result.route_id), result.to_dict())

    def load(self, season_id: str, route_id: str) -> RaceResult | None:
        data = self._read(self._path(season_id, route_id))
        try:
            return RaceResult.from_dict(data) if data else None
        except (KeyError, TypeError, ValueError):
            return None

    def load_season(self, season_id: str, races: Sequence[RaceSpec] = CALENDAR) -> dict[str, RaceResult]:
        return {
            spec.route_id: result
            for spec in races
            if (result := self.load(season_id, spec.route_id)) is not None
        }

    def delete(self, season_id: str, route_id: str) -> None:
        self._path(season_id, route_id).unlink(missing_ok=True)

    # -- Streckenlager --------------------------------------------------
    #
    # Importierte Profile liegen gzip-komprimiert: Zehntausend
    # Steigungswerte sind als Text rund 80 kB und gepackt keine 30 —
    # und gelesen werden sie einmal beim Start einer Übertragung.
    def _route_path(self, route_id: str) -> Path:
        directory = self.root / "routes"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{route_id}.json.gz"

    def save_route(self, route: Route) -> None:
        self._write_atomic(self._route_path(route.id), route.to_storage(), packed=True)

    def load_route(self, route_id: str) -> Route | None:
        data = self._read(self._route_path(route_id), packed=True)
        try:
            return Route.from_storage(data) if data else None
        except (KeyError, TypeError, ValueError):
            return None

    def list_routes(self) -> list[Route]:
        directory = self.root / "routes"
        if not directory.exists():
            return []
        gefunden = [self.load_route(p.name[: -len(".json.gz")]) for p in sorted(directory.glob("*.json.gz"))]
        return [r for r in gefunden if r is not None]

    def has_route(self, route_id: str) -> bool:
        return self._route_path(route_id).exists()

    def delete_route(self, route_id: str) -> None:
        self._route_path(route_id).unlink(missing_ok=True)

    # -- Eigene Saisons -------------------------------------------------
    def _season_path(self, season_id: str) -> Path:
        directory = self.root / "seasons"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{season_id}.json"

    def save_season(self, season: Season) -> None:
        self._write_atomic(self._season_path(season.id), season.to_dict())

    def load_seasons(self) -> list[Season]:
        directory = self.root / "seasons"
        if not directory.exists():
            return []
        out: list[Season] = []
        for pfad in sorted(directory.glob("*.json")):
            data = self._read(pfad)
            if not data:
                continue
            try:
                out.append(Season.from_dict(data))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def delete_season(self, season_id: str) -> None:
        self._season_path(season_id).unlink(missing_ok=True)
        # Die Ergebnisse gehören zur Saison und gehen mit ihr.
        ordner = self.root / "results" / season_id
        if ordner.exists():
            for pfad in ordner.glob("*.json"):
                pfad.unlink(missing_ok=True)
            ordner.rmdir()

    # -- gemeinsames Schreiben und Lesen ---------------------------------
    @staticmethod
    def _write_atomic(path: Path, payload: dict, packed: bool = False) -> None:
        """Erst daneben schreiben, dann umbenennen.

        Ein Absturz mitten im Schreiben soll keine halbe Datei
        hinterlassen, die beim nächsten Start die ganze Saison unlesbar
        macht.
        """
        tmp = path.with_suffix(path.suffix + ".tmp")
        roh = json.dumps(payload).encode("utf-8")
        if packed:
            tmp.write_bytes(gzip.compress(roh, compresslevel=6))
        else:
            tmp.write_bytes(roh)
        tmp.replace(path)

    @staticmethod
    def _read(path: Path, packed: bool = False) -> dict | None:
        if not path.exists():
            return None
        try:
            roh = path.read_bytes()
            return json.loads(gzip.decompress(roh) if packed else roh)
        except (OSError, json.JSONDecodeError, EOFError, gzip.BadGzipFile):
            return None


# ----------------------------------------------------------------------
# Wertungen
# ----------------------------------------------------------------------
@dataclass
class RiderStanding:
    rider: Rider
    team: Team
    points: int
    wins: int
    podiums: int
    starts: int
    #: Punkte je Rennen, in Kalenderreihenfolge.
    per_race: list[int]
    best_rank: int | None


@dataclass
class TimeStanding:
    """Ein Platz in der Gesamtwertung nach Zeit."""

    rider: Rider
    team: Team
    #: Summe der Fahrzeiten über alle bislang gefahrenen Rennen.
    total_time_s: float
    #: Rückstand auf den Führenden.
    gap_s: float
    #: Zeit je Rennen, in Kalenderreihenfolge. ``None`` = nicht gewertet.
    per_race: list[float | None]
    #: In wie vielen der gefahrenen Rennen er eine Zeit hat.
    races: int
    #: Ob er in **allen** gefahrenen Rennen eine Zeit hat. Nur wer
    #: vollständig ist, steht in der Gesamtwertung.
    complete: bool


@dataclass
class TeamStanding:
    team: Team
    points: int
    wins: int
    #: Der punktbeste Fahrer des Teams.
    top_rider: Rider | None
    per_race: list[int]


def rider_standings(
    results: dict[str, RaceResult],
    riders: list[Rider],
    teams: list[Team],
    races: Sequence[RaceSpec] = CALENDAR,
) -> list[RiderStanding]:
    """Die Fahrerwertung über alle bislang gefahrenen Rennen."""
    by_id = {r.id: r for r in riders}
    n_races = len(races)
    points: dict[int, int] = {}
    per_race: dict[int, list[int]] = {}
    wins: dict[int, int] = {}
    podiums: dict[int, int] = {}
    starts: dict[int, int] = {}
    best: dict[int, int] = {}

    for spec in races:
        result = results.get(spec.route_id)
        if result is None:
            continue
        for rank, rider_id, _ in result.ranking():
            if rider_id not in by_id:
                continue
            pts = points_for_rank(rank)
            points[rider_id] = points.get(rider_id, 0) + pts
            per_race.setdefault(rider_id, [0] * n_races)[spec.idx] = pts
            starts[rider_id] = starts.get(rider_id, 0) + 1
            if rank == 1:
                wins[rider_id] = wins.get(rider_id, 0) + 1
            if rank <= 3:
                podiums[rider_id] = podiums.get(rider_id, 0) + 1
            if rider_id not in best or rank < best[rider_id]:
                best[rider_id] = rank

    standings = [
        RiderStanding(
            rider=rider,
            team=teams[rider.team_id],
            points=points.get(rider.id, 0),
            wins=wins.get(rider.id, 0),
            podiums=podiums.get(rider.id, 0),
            starts=starts.get(rider.id, 0),
            per_race=per_race.get(rider.id, [0] * n_races),
            best_rank=best.get(rider.id),
        )
        for rider in riders
    ]
    # Punktgleiche trennt zuerst die Zahl der Siege, dann der Podien,
    # zuletzt die beste Einzelplatzierung. Ohne diese Reihenfolge stünde
    # bei Punktgleichheit die Startnummer über dem sportlichen Ergebnis.
    standings.sort(
        key=lambda s: (-s.points, -s.wins, -s.podiums, s.best_rank or 999, s.rider.bib)
    )
    return standings


def time_standings(
    results: dict[str, RaceResult],
    riders: list[Rider],
    teams: list[Team],
    races: Sequence[RaceSpec] = CALENDAR,
) -> list[TimeStanding]:
    """Die Gesamtwertung nach Zeit — addierte Fahrzeiten aller Rennen.

    Die zweite Art, eine Saison zu gewinnen. Die Punktewertung belohnt
    Platzierungen und ist damit gnädig: Wer ein Rennen verliert, verliert
    höchstens hundert Punkte. Die Zeitwertung addiert stur, und eine
    schlechte Nacht auf tausend Kilometern kostet zwei Stunden, die
    kein späteres Rennen zurückgibt.

    Gewertet wird nur, wer in **allen** bislang gefahrenen Rennen eine
    Zeit hat. Die anderen stehen dahinter — ohne diese Regel führte
    jeder, der nur das kürzeste Rennen bestritten hat.
    """
    gefahren = [spec for spec in races if spec.route_id in results]
    n_races = len(races)

    zeiten: dict[int, list[float | None]] = {r.id: [None] * n_races for r in riders}
    for spec in gefahren:
        for _, rider_id, t in results[spec.route_id].ranking():
            if rider_id in zeiten:
                zeiten[rider_id][spec.idx] = t

    standings: list[TimeStanding] = []
    for rider in riders:
        eigene = zeiten[rider.id]
        gefahrene = [eigene[spec.idx] for spec in gefahren]
        vorhanden = [t for t in gefahrene if t is not None]
        standings.append(
            TimeStanding(
                rider=rider,
                team=teams[rider.team_id],
                total_time_s=float(sum(vorhanden)),
                gap_s=0.0,
                per_race=eigene,
                races=len(vorhanden),
                complete=bool(gefahren) and len(vorhanden) == len(gefahren),
            )
        )

    # Unvollständige nach hinten, sonst führt der, der am wenigsten
    # gefahren ist. Die Startnummer trennt exakte Gleichstände.
    standings.sort(key=lambda s: (not s.complete, s.total_time_s, s.rider.bib))
    fuehrend = next((s for s in standings if s.complete), None)
    if fuehrend is not None:
        for s in standings:
            s.gap_s = s.total_time_s - fuehrend.total_time_s if s.complete else 0.0
    return standings


def team_standings(
    results: dict[str, RaceResult],
    riders: list[Rider],
    teams: list[Team],
    races: Sequence[RaceSpec] = CALENDAR,
) -> list[TeamStanding]:
    """Die Teamwertung: Summe der Punkte aller zwölf Fahrer."""
    riders_by_team: dict[int, list[RiderStanding]] = {t.id: [] for t in teams}
    for standing in rider_standings(results, riders, teams, races):
        riders_by_team[standing.rider.team_id].append(standing)

    n_races = len(races)
    out: list[TeamStanding] = []
    for team in teams:
        members = riders_by_team[team.id]
        per_race = [0] * n_races
        for member in members:
            for i, pts in enumerate(member.per_race):
                per_race[i] += pts
        out.append(
            TeamStanding(
                team=team,
                points=sum(m.points for m in members),
                wins=sum(m.wins for m in members),
                top_rider=members[0].rider if members and members[0].points > 0 else None,
                per_race=per_race,
            )
        )
    out.sort(key=lambda s: (-s.points, -s.wins, s.team.name))
    return out


__all__ = [
    "CALENDAR",
    "POINTS",
    "TOP_POINTS",
    "SCORING_PLACES",
    "RaceSpec",
    "BUILTIN_SEASONS",
    "RaceResult",
    "Season",
    "Store",
    "RiderStanding",
    "TeamStanding",
    "TimeStanding",
    "ClimbStanding",
    "all_seasons",
    "get_season",
    "get_race_spec",
    "build_route",
    "points_for_rank",
    "rider_standings",
    "team_standings",
    "time_standings",
    "climb_standings",
]


@dataclass
class ClimbStanding:
    """Ein Platz in der Bergwertung."""

    rider: Rider
    team: Team
    points: int
    #: Punkte je Rennen, in Kalenderreihenfolge.
    per_race: list[int]
    races: int


def climb_standings(
    results: dict[str, RaceResult],
    riders: list[Rider],
    teams: list[Team],
    races: Sequence[RaceSpec] = CALENDAR,
) -> list[ClimbStanding]:
    """Die Bergwertung über alle bislang gefahrenen Rennen.

    Sie fällt schmal aus, und das ist keine Schwäche: Am Berg entscheidet
    Watt je Kilogramm, und die besten fünf Kletterer eines Feldes von
    dreihundert holen die Gipfel unter sich aus. Genau dafür gibt es die
    Wertung — sie beantwortet eine andere Frage als die Gesamtzeit.
    """
    n_races = len(races)
    punkte: dict[int, int] = {}
    per_race: dict[int, list[int]] = {}
    starts: dict[int, int] = {}

    for spec in races:
        result = results.get(spec.route_id)
        if result is None:
            continue
        for rider_id, p in result.climb_points.items():
            if p <= 0:
                continue
            punkte[rider_id] = punkte.get(rider_id, 0) + p
            per_race.setdefault(rider_id, [0] * n_races)[spec.idx] = p
            starts[rider_id] = starts.get(rider_id, 0) + 1

    standings = [
        ClimbStanding(
            rider=rider,
            team=teams[rider.team_id],
            points=punkte.get(rider.id, 0),
            per_race=per_race.get(rider.id, [0] * n_races),
            races=starts.get(rider.id, 0),
        )
        for rider in riders
        if punkte.get(rider.id, 0) > 0
    ]
    standings.sort(key=lambda s: (-s.points, -s.races, s.rider.bib))
    return standings
