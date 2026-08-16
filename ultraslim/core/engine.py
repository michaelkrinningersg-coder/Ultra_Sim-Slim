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


def intensity_for_distance(distance_km: float) -> float:
    """Intensitätsfaktor für eine Renndistanz, linear interpoliert."""
    xs = [k for k, _ in IF_BY_KM]
    ys = [v for _, v in IF_BY_KM]
    return float(np.interp(distance_km, xs, ys))


def grade_power_factor(grade: np.ndarray) -> np.ndarray:
    """Wie die Steigung die Zielleistung verschiebt.

    Steigt linear von 1,00 bei flach auf 1,15 ab acht Prozent und fällt
    ebenso linear auf 0,55 ab vier Prozent Gefälle.
    """
    g = np.asarray(grade, dtype=np.float64)
    up = np.clip(g / CLIMB_GRADE_FULL, 0.0, 1.0)
    down = np.clip(-g / DESCENT_GRADE_FULL, 0.0, 1.0)
    return 1.0 + CLIMB_POWER_GAIN * up - DESCENT_POWER_LOSS * down


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
        self.area = np.array([r.frontal_area_m2 for r in self.riders], dtype=np.float64)

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

        #: Zielleistung im Flachen, ohne Modulation.
        self.base_power = self.ftp * self.intensity_factor * self.form

        # --- Start ------------------------------------------------------
        # Einzelstart, aber **teamweise verzahnt**: erst je ein Fahrer
        # jedes Teams, dann die nächste Runde. Nach Startnummern sortiert
        # wären die ersten fünfundzwanzig Starter alle aus demselben
        # Team — die ersten vier Stunden Übertragung zeigten dann eine
        # Mannschaft statt eines Feldes.
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

        # --- Erinnerung ------------------------------------------------
        self._hist_t: list[float] = [0.0]
        self._hist_dist: list[np.ndarray] = [self.dist_m.astype(np.float32)]
        self._hist_v: list[np.ndarray] = [self.v_ms.astype(np.float32)]
        self._next_hist_t = HISTORY_INTERVAL_S

        self._gen = self._run()

    def _start_order(self) -> np.ndarray:
        """Startposition je Fahrer: erst je einer pro Team, dann Runde zwei."""
        n_teams = max((r.team_id for r in self.riders), default=0) + 1
        gezaehlt: dict[int, int] = {}
        positions = np.empty(len(self.riders), dtype=np.float64)
        for i, rider in enumerate(self.riders):
            runde = gezaehlt.get(rider.team_id, 0)
            gezaehlt[rider.team_id] = runde + 1
            positions[i] = runde * n_teams + rider.team_id
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
        power = self.base_power * terrain.power_factor[idx] * noise
        power *= physics.downhill_power_taper(self.v_ms)
        power = np.where(active, power, 0.0)

        cda = self.area * terrain.position_k[idx]
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
        return float(self.start_offset_s[-1]) + self._estimated_duration_s

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
            v = physics.steady_state_speed(
                self.base_power[weakest] * terrain.power_factor,
                terrain.grade,
                self.mass[weakest],
                self.area[weakest] * terrain.position_k,
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
    "STATE_WAITING",
    "STATE_RIDING",
    "STATE_FINISHED",
    "START_INTERVAL_S",
    "DT",
]
