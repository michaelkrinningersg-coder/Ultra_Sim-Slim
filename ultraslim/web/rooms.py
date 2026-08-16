"""Laufende Rennen und die Zuschauer, die ihnen zusehen.

Zwei Dinge stecken hier drin:

**Der Raum** hält ein Rennen, das gerade entsteht. Er zieht den
Generator der Engine genau so weit, wie die Uhr des Zuschauers steht —
nicht weiter. Ein Schloss je Raum genügt, aber es ist nötig: Ein
Generator verträgt keine zwei gleichzeitigen ``next``-Aufrufe, und ein
Webserver liefert genau das, sobald der Ereignisstrom Bilder zieht,
während ein Klick hereinkommt.

**Die Sitzung** ist der Blick eines Zuschauers auf diesen Raum: seine
Uhr, sein Fokusfahrer, seine Sortierung. Mehrere Sitzungen können
denselben Raum betrachten, jede mit eigener Uhr.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from ..core.engine import STATE_FINISHED, STATE_WAITING, LiveRace, RaceConfig
from ..core.rider import Rider, Team
from ..core.route import Route
from ..core.season import RaceResult, Season, Store

#: So viele Zeilen zeigt das Board um den Fokusfahrer herum. Dreihundert
#: Zeilen je Bild wären ein Vielfaches an Daten für eine Tabelle, von der
#: man zwanzig Zeilen sieht — der Führende und die angehefteten Fahrer
#: kommen getrennt dazu, damit sie nie fehlen.
BOARD_WINDOW = 40

#: Verfügbare Zeitraffer-Stufen. Deckungsgleich mit ``live.js``.
SPEEDS = (1, 5, 10, 30, 60, 300, 1000)

#: Obergrenze für einen Sprung „zum nächsten Ereignis": So viel Rennzeit
#: darf ein Klick höchstens rechnen lassen, bevor er aufgibt. Beim
#: Einzelstart im Zehn-Minuten-Takt können zwischen zwei Zeitmessungen
#: eines Fahrers mehrere Stunden liegen.
JUMP_LIMIT_S = 12.0 * 3600.0
#: Schrittweite dieser Sprünge. Feiner heißt genauer treffen, gröber
#: heißt weniger Python-Runden um dieselbe Rechenarbeit.
JUMP_STEP_S = 60.0

#: Sortierschlüssel, die das Board kennt.
SORT_FIELDS = frozenset(
    {"zeit", "nr", "name", "team", "rueckstand", "km", "biscp", "trend", "tempo", "leistung"}
)


@dataclass
class LiveRoom:
    """Ein Rennen, das gerade entsteht."""

    race_id: str
    season: Season
    route: Route
    live: LiveRace
    riders: list[Rider]
    teams: list[Team]
    store: Store | None = None

    _lock: threading.RLock = field(default_factory=threading.RLock)
    _saved: bool = False

    @classmethod
    def start(
        cls,
        race_id: str,
        season: Season,
        route: Route,
        riders: list[Rider],
        teams: list[Team],
        config: RaceConfig,
        store: Store | None = None,
    ) -> LiveRoom:
        return cls(
            race_id=race_id,
            season=season,
            route=route,
            live=LiveRace(route, riders, teams, config),
            riders=riders,
            teams=teams,
            store=store,
        )

    # ------------------------------------------------------------------
    @property
    def finished(self) -> bool:
        return self.live.finished

    @property
    def horizon_s(self) -> float:
        return self.live.horizon_s

    def advance(self, t: float) -> None:
        """Bis zur Rennzeit ``t`` rechnen — und dabei niemanden überholen."""
        with self._lock:
            self.live.advance_to(t)
            if self.live.finished and not self._saved:
                self._save()

    def _save(self) -> None:
        """Das Ergebnis sichern, sobald der letzte Fahrer im Ziel ist."""
        self._saved = True
        if self.store is None:
            return
        times = self.live.finish_time_s
        order = np.argsort(np.where(np.isnan(times), np.inf, times), kind="stable")
        finishers = [
            (self.riders[int(i)].id, float(times[int(i)]))
            for i in order
            if not np.isnan(times[int(i)])
        ]
        self.store.save(
            RaceResult(
                season_id=self.season.id,
                route_id=self.route.id,
                finishers=finishers,
            )
        )


class LiveRegistry:
    """Alle Rennen, die dieser Prozess gerade rechnet."""

    def __init__(self, max_rooms: int = 3) -> None:
        self._rooms: dict[str, LiveRoom] = {}
        self._max = max_rooms
        self._lock = threading.Lock()

    def add(self, room: LiveRoom) -> LiveRoom:
        with self._lock:
            self._rooms[room.race_id] = room
            # Ein laufendes Rennen hält dreihundert Fahrer samt
            # Positionsverlauf im Speicher. Wer ein viertes aufmacht,
            # verliert das älteste.
            while len(self._rooms) > self._max:
                oldest = next(iter(self._rooms))
                self._rooms.pop(oldest, None)
            return room

    def get(self, race_id: str) -> LiveRoom | None:
        return self._rooms.get(race_id)

    def close(self, race_id: str) -> None:
        with self._lock:
            self._rooms.pop(race_id, None)

    def ids(self) -> list[str]:
        return list(self._rooms)


# ----------------------------------------------------------------------
@dataclass
class ViewSession:
    """Der Blick eines Zuschauers auf einen Raum."""

    token: str
    room: LiveRoom

    t_wall: float = 0.0
    playing: bool = False
    speed: int = 10
    focus_id: int = 0
    auto_focus: bool = False
    mode: str = "virtual"          # 'virtual' | 'split'
    split_idx: int = 0
    split_follow: bool = True
    sort: str = "zeit"
    sort_desc: bool = False
    pinned: list[int] = field(default_factory=list)

    _last_wall: float = field(default_factory=time.monotonic)
    _seen_events: int = 0

    # ------------------------------------------------------------------
    @property
    def horizon_s(self) -> float:
        return self.room.horizon_s

    def tick_clock(self) -> None:
        """Die Uhr um die vergangene Echtzeit weiterstellen."""
        now = time.monotonic()
        elapsed = now - self._last_wall
        self._last_wall = now
        if self.playing:
            self.t_wall = min(self.t_wall + elapsed * self.speed, self.horizon_s)
            if self.room.finished and self.t_wall >= self.horizon_s:
                self.playing = False

    def sync(self) -> None:
        """Uhr stellen und das Rennen bis dorthin rechnen lassen."""
        self.tick_clock()
        self.room.advance(self.t_wall)
        if self.auto_focus:
            self._follow_action()

    # ------------------------------------------------------------------
    def control(self, action: str, value=None) -> None:
        live = self.room.live
        if action == "toggle":
            self.playing = not self.playing
        elif action == "play":
            self.playing = bool(value) if value is not None else True
        elif action == "pause":
            self.playing = False
        elif action == "speed" and int(value) in SPEEDS:
            self.speed = int(value)
        elif action == "seek":
            self.t_wall = max(0.0, min(float(value), self.horizon_s))
            self.room.advance(self.t_wall)
        elif action == "focus":
            self.focus_id = int(value)
            # Ein Klick auf einen Fahrer schaltet die Regie ab — sonst
            # zieht sie den Fokus im nächsten Bild wieder weg.
            self.auto_focus = False
            if self.split_follow:
                self._follow_split()
        elif action == "auto_focus":
            self.auto_focus = bool(value)
        elif action == "mode" and value in ("virtual", "split"):
            self.mode = value
        elif action == "split":
            self.split_idx = int(np.clip(int(value), 0, len(self.room.route.splits) - 1))
            self.split_follow = False
        elif action == "split_follow":
            self.split_follow = bool(value)
        elif action == "sort" and value in SORT_FIELDS:
            self.sort_desc = not self.sort_desc if self.sort == value else False
            self.sort = value
        elif action == "pin":
            entry = int(value)
            if entry in self.pinned:
                self.pinned.remove(entry)
            else:
                # Zwei genügen: Ein Duell hat zwei Seiten.
                self.pinned = ([*self.pinned, entry])[-2:]
        elif action == "distance":
            self._seek_distance(float(value))
        elif action == "next_split":
            self._jump_next_split()
        elif action == "next_event":
            self._jump_next_event()
        _ = live

    # ------------------------------------------------------------------
    def _focus_index(self) -> int:
        return int(np.clip(self.focus_id, 0, len(self.room.riders) - 1))

    def _follow_split(self) -> None:
        """Board auf die zuletzt passierte Zeitmessung des Fokus ziehen."""
        i = self._focus_index()
        live = self.room.live
        own = float(live.own_time(self.t_wall)[i])
        times = live.split_times[i]
        reached = np.nonzero(~np.isnan(times) & (times <= own))[0]
        if reached.size:
            self.split_idx = int(reached[-1])

    def _follow_action(self) -> None:
        """Regie: Der Fokus folgt dem, bei dem gerade etwas passiert."""
        events = self.room.live.events_until(self.t_wall)
        for event in reversed(events):
            if event.type in ("BEST_TIME", "FINISH"):
                self.focus_id = event.entry_id
                return

    def _advance_until(self, predicate, limit_s: float = JUMP_LIMIT_S) -> None:
        """Vorwärts rechnen, bis ``predicate`` zutrifft oder Schluss ist.

        Ein Sprung nach vorn kostet genau die Rechenzeit, die er
        überspringt — das ist der Preis dafür, dass nichts vorberechnet
        wird, und er wird hier ehrlich bezahlt.
        """
        self.playing = False
        target = self.t_wall
        end = min(self.t_wall + limit_s, self.horizon_s)
        step = JUMP_STEP_S
        while target < end:
            target = min(target + step, end)
            self.room.advance(target)
            if predicate(target):
                self.t_wall = target
                return
            if self.room.finished and target >= self.room.live.sim_t:
                break
        self.t_wall = min(target, self.horizon_s)

    def _jump_next_split(self) -> None:
        i = self._focus_index()
        live = self.room.live
        times = live.split_times[i]
        own_now = float(live.own_time(self.t_wall)[i])
        nxt = int(np.count_nonzero(~np.isnan(times) & (times <= own_now)))
        if nxt >= len(times):
            return

        def hit(t: float) -> bool:
            value = live.split_times[i][nxt]
            return not np.isnan(value) and value <= float(live.own_time(t)[i])

        self._advance_until(hit)
        if self.split_follow:
            self._follow_split()

    def _jump_next_event(self) -> None:
        i = self._focus_index()
        rider_id = self.room.riders[i].id
        live = self.room.live
        now = self.t_wall

        def hit(t: float) -> bool:
            return any(e.entry_id == rider_id and now < e.t_wall <= t for e in live.events)

        self._advance_until(hit)

    def _seek_distance(self, dist_m: float) -> None:
        """Zu dem Moment springen, in dem der Fokusfahrer dort war."""
        i = self._focus_index()
        live = self.room.live
        dist_m = float(np.clip(dist_m, 0.0, self.room.route.distance_m))

        current, _ = live.positions_at(self.t_wall)
        if dist_m <= current[i]:
            # Rückwärts: im Positionsverlauf nachschlagen.
            history = np.array([snap[i] for snap in live._hist_dist], dtype=np.float64)
            j = int(np.searchsorted(history, dist_m, side="left"))
            j = min(max(j, 0), len(live._hist_t) - 1)
            self.t_wall = float(live._hist_t[j])
            self.playing = False
            return

        self._advance_until(lambda t: live.positions_at(t)[0][i] >= dist_m)

    # ------------------------------------------------------------------
    # Frame
    # ------------------------------------------------------------------
    def frame(self) -> dict:
        self.sync()
        room = self.room
        live = room.live
        route = room.route
        t = self.t_wall

        dist, v = live.positions_at(t)
        grade = live.grade_at(dist)
        started = live.started_mask(t)
        finished = live.finished_mask(t)
        reached = live.reached_mask(t)
        state = np.where(finished, STATE_FINISHED, np.where(started, 0, STATE_WAITING))

        rows_all = self._build_rows(t, dist, v, started, finished, reached)
        order = self._sorted_order(rows_all)

        focus_i = self._focus_index()
        if self.split_follow and self.mode == "split":
            self._follow_split()

        pos_in_order = {entry: k for k, entry in enumerate(order)}
        centre = pos_in_order.get(room.riders[focus_i].id, 0)
        lo = max(0, centre - BOARD_WINDOW // 2)
        window = order[lo : lo + BOARD_WINDOW]

        leader_entry = self._leader_entry(order, rows_all, reached)
        split = route.splits[self.split_idx]

        return {
            "t_wall": round(t, 1),
            "horizon_s": round(self.horizon_s, 1),
            "playing": self.playing,
            "speed": self.speed,
            "mode": self.mode,
            "split_follow": self.split_follow,
            "auto_focus": self.auto_focus,
            "sort": self.sort,
            "sort_desc": self.sort_desc,
            "pinned": list(self.pinned),
            "focus": self._focus_payload(focus_i, t, dist, v, grade, started, finished),
            # Wer noch nicht gestartet ist, kommt nicht ins Profil: Bei
            # zehn Minuten Startabstand stünden sonst zweihundert Punkte
            # als Klumpen auf Kilometer null.
            "positions": [
                [int(r.id), round(float(dist[k]), 1), round(float(v[k]) * 3.6, 1), int(state[k])]
                for k, r in enumerate(room.riders)
                if started[k]
            ],
            "ticker": [e.to_dict(room.riders[focus_i].id) for e in live.events_until(t)[-40:]],
            "board": {
                "split": {"idx": split.idx, "name": split.name, "dist_m": round(split.dist_m, 1)},
                "n_reached": int(np.count_nonzero(reached[:, self.split_idx])),
                "n_total": len(room.riders),
                "leader": rows_all[leader_entry] if leader_entry is not None else None,
                "rows": [rows_all[e] for e in window],
                "pinned": [rows_all[e] for e in self.pinned if e in rows_all],
            },
            "field": {
                "waiting": int(np.count_nonzero(~started)),
                "on_course": int(np.count_nonzero(started & ~finished)),
                "finished": int(np.count_nonzero(finished)),
            },
        }

    # ------------------------------------------------------------------
    def _build_rows(self, t, dist, v, started, finished, reached) -> dict[int, dict]:
        """Eine Zeile je Fahrer, in der Zeitrechnung des Einzelstarts.

        Gewertet wird ausschließlich die **Eigenzeit**. Die Rennuhr sagt,
        wann etwas zu sehen war; wer gewinnt, entscheidet sie nicht.
        """
        room = self.room
        live = room.live
        route = room.route
        n_splits = len(route.splits)
        split_times = live.split_times
        own = live.own_time(t)

        if self.mode == "split":
            # Splitwertung: gemessene Zeit, sonst die **laufende Uhr**.
            #
            # Keine Hochrechnung. Wer die Messstelle noch vor sich hat,
            # steht mit dem da, was seine Uhr gerade zeigt — und die
            # zählt weiter. Er startet damit ganz oben und wandert nach
            # unten, sobald seine Uhr eine gefahrene Zeit überholt. Das
            # ist die Live-Zeitnahme, wie sie an der Strecke steht: Der
            # Fahrer hat die Zeit noch nicht verloren, solange die Uhr
            # sie nicht abgelaufen hat.
            #
            # Zwischen zwei Bildern sortiert der Client selbst nach, sonst
            # ruckelte die Rangfolge im Takt des Ereignisstroms.
            s = self.split_idx
            has = reached[:, s]
            times = np.where(has, split_times[:, s], own)
            running = started & ~has
            provisional = ~has
            best = float(np.min(times[has])) if np.any(has) else 0.0
            gaps = times - best
        else:
            # Virtuelle Rangliste: die hochgerechnete Endzeit. Beim
            # Einzelstart ist die Distanz allein keine Rangfolge — wer
            # fünf Stunden früher losgefahren ist, liegt weiter vorn,
            # ohne schneller zu sein.
            eta = self._hochrechnung(own, dist, route.distance_m)
            times = np.where(finished, np.nan_to_num(live.finish_time_s, nan=0.0), eta)
            running = np.zeros_like(started)
            provisional = ~finished
            best = float(np.min(times[started])) if np.any(started) else 0.0
            gaps = times - best

        trend = self._trend(reached)

        next_idx = np.clip(np.count_nonzero(reached, axis=1), 0, n_splits - 1)
        split_dist = np.array([s.dist_m for s in route.splits])
        to_next = np.where(finished | ~started, np.nan, split_dist[next_idx] - dist)

        rows: dict[int, dict] = {}
        for k, rider in enumerate(room.riders):
            waiting = not started[k]
            rows[rider.id] = {
                "entry_id": rider.id,
                "bib": rider.bib,
                "name": rider.name,
                "nation": rider.nation,
                "team": room.teams[rider.team_id].name,
                "color": room.teams[rider.team_id].color,
                "start_offset_s": round(float(live.start_offset_s[k]), 1),
                "t_s": None if waiting else round(float(times[k]), 1),
                "gap_s": None if waiting else round(float(gaps[k]), 1),
                "running": bool(running[k]),
                "provisional": bool(provisional[k]) and not waiting,
                "dist_km": round(float(dist[k]) / 1000.0, 2),
                "to_next_m": None if np.isnan(to_next[k]) else int(max(to_next[k], 0)),
                "next_split": route.splits[int(next_idx[k])].name,
                "trend": int(trend[k]),
                "v_kmh": round(float(v[k]) * 3.6, 1),
                "power_w": int(round(float(live.power_w[k]))) if started[k] and not finished[k] else 0,
                "state": (
                    STATE_FINISHED if finished[k] else (STATE_WAITING if waiting else 0)
                ),
                "rank": 0,
            }
        return rows

    def _leader_entry(self, order: list[int], rows: dict[int, dict], reached) -> int | None:
        """Wer in der angehefteten Kopfzeile steht.

        In der Splitwertung **der Halter der besten gefahrenen Zeit** —
        nicht Rang eins. Rang eins ist dort regelmäßig ein Fahrer, dessen
        Uhr erst fünf Minuten läuft; er steht oben, weil er die Bestzeit
        noch schlagen *kann*, nicht weil er sie geschlagen *hat*. Die
        Rückstandsspalte misst gegen die beste gefahrene Zeit, und die
        Kopfzeile muss zeigen, worauf sich diese Zahlen beziehen.

        In der virtuellen Rangliste bleibt es Rang eins: Dort ist jede
        Zeit eine Hochrechnung, es gibt also keine gemessene Referenz.
        """
        if not order:
            return None
        if self.mode != "split":
            return order[0]

        # Nach der Zeit gesucht, nicht nach der Position in ``order``:
        # Sortiert der Zuschauer gerade nach Tempo, stünde dort sonst der
        # schnellste Fahrer statt des schnellsten Durchgangs.
        durch = reached[:, self.split_idx]
        gemessen = [
            entry
            for i, entry in enumerate(r.id for r in self.room.riders)
            if durch[i] and rows[entry]["t_s"] is not None
        ]
        if not gemessen:
            return order[0]
        return min(gemessen, key=lambda e: rows[e]["t_s"])

    @staticmethod
    def _hochrechnung(own: np.ndarray, dist: np.ndarray, ziel_m: float) -> np.ndarray:
        """Hochgerechnete Zeit bis Kilometer ``ziel_m``.

        Über den **Schnitt bisher**, nicht über das Momentantempo. Der
        erste Ansatz nahm die aktuelle Geschwindigkeit und rechnete sie
        auf die Restdistanz hoch — damit projizierte ein Fahrer, der
        gerade mit 11,9 km/h eine Rampe hochfuhr, sechsundfünfzig
        Stunden für ein Rennen, das er in einundzwanzig fährt, und die
        Rangliste sprang bei jedem Anstieg durcheinander.

        ``t_ziel = t_bisher · s_ziel / s_bisher`` ist stabil, braucht
        kein Geländewissen und ist für alle Fahrer derselbe Maßstab.
        Was sie nicht kann: wissen, dass die Berge erst kommen. Für eine
        Rangfolge genügt das, für eine Prognose auf die Minute nicht —
        deshalb steht sie kursiv.
        """
        gefahren = np.maximum(dist, 1.0)
        return np.where(dist >= ziel_m, own, own * (ziel_m / gefahren))

    def _trend(self, reached) -> np.ndarray:
        """Plätze gegenüber dem vorletzten erreichten Split.

        Nur in der Splitwertung sinnvoll — aber billig genug, um ihn
        immer zu haben.
        """
        n = len(self.room.riders)
        s = self.split_idx
        if s < 1:
            return np.zeros(n, dtype=np.int32)
        split_times = self.room.live.split_times
        prev = s - 1
        both = reached[:, s] & reached[:, prev]
        if not both.any():
            return np.zeros(n, dtype=np.int32)

        def ranks(col: int) -> np.ndarray:
            values = np.where(both, split_times[:, col], np.inf)
            out = np.empty(n, dtype=np.int32)
            out[np.argsort(values, kind="stable")] = np.arange(n)
            return out

        return np.where(both, ranks(prev) - ranks(s), 0).astype(np.int32)

    #: Sortierungen, in denen ein Fahrer ohne gefahrene Zeit nichts zu
    #: suchen hat. Seine Uhr steht bei null — in einer Zeitwertung stünde
    #: er damit an der Spitze, obwohl er noch am Starthaus steht.
    _TIME_SORTS = frozenset({"zeit", "rueckstand", "biscp"})

    def _sorted_order(self, rows: dict[int, dict]) -> list[int]:
        key = self.sort

        def value(row: dict):
            if key == "nr":
                return row["bib"]
            if key == "name":
                return row["name"]
            if key == "team":
                return (row["team"], row["name"])
            if key == "rueckstand":
                return row["gap_s"]
            if key == "km":
                return -row["dist_km"]
            if key == "biscp":
                return row["to_next_m"] if row["to_next_m"] is not None else 1e12
            if key == "trend":
                return -row["trend"]
            if key == "tempo":
                return -row["v_kmh"]
            if key == "leistung":
                return -row["power_w"]
            # 'zeit': die Wertung selbst. Rein nach der Zeit, ohne
            # gemessene und laufende zu trennen — genau darum kann eine
            # laufende Uhr einen Fahrer nach hinten schieben.
            return row["t_s"]

        items = list(rows.values())
        if key in self._TIME_SORTS:
            waiting = [r for r in items if r["t_s"] is None]
            items = [r for r in items if r["t_s"] is not None]
            waiting.sort(key=lambda r: r["bib"])
        else:
            waiting = []

        items.sort(key=value, reverse=self.sort_desc)
        items.extend(waiting)
        for i, row in enumerate(items):
            row["rank"] = i + 1
        return [row["entry_id"] for row in items]

    def _focus_payload(self, i: int, t, dist, v, grade, started, finished) -> dict:
        room = self.room
        rider = room.riders[i]
        live = room.live
        own = float(live.own_time(t)[i])
        return {
            "entry_id": rider.id,
            "bib": rider.bib,
            "name": rider.name,
            "nation": rider.nation,
            "team": room.teams[rider.team_id].name,
            "color": room.teams[rider.team_id].color,
            "ftp_w": round(rider.ftp_w),
            "weight_kg": round(rider.weight_kg, 1),
            "height_cm": round(rider.height_cm),
            "w_per_kg": round(rider.w_per_kg, 2),
            "dist_m": round(float(dist[i]), 1),
            "remaining_m": round(max(room.route.distance_m - float(dist[i]), 0.0), 1),
            "v_kmh": round(float(v[i]) * 3.6, 1),
            "grade_pct": round(float(grade[i]) * 100.0, 1),
            "power_w": int(round(float(live.power_w[i]))) if started[i] and not finished[i] else 0,
            "form_pct": round(float(live.form[i]) * 100.0, 1),
            "state": (
                STATE_FINISHED if finished[i] else (0 if started[i] else STATE_WAITING)
            ),
            "started": bool(started[i]),
            "start_offset_s": round(float(live.start_offset_s[i]), 1),
            "own_time_s": round(float(live.finish_time_s[i]) if finished[i] else own, 1),
        }


class SessionRegistry:
    """Alle Zuschauersitzungen. Ein Token, eine Uhr."""

    def __init__(self, max_sessions: int = 24) -> None:
        self._sessions: dict[str, ViewSession] = {}
        self._max = max_sessions

    def create(self, room: LiveRoom) -> ViewSession:
        token = secrets.token_urlsafe(12)
        # Der Fokus beginnt beim ersten Starter, nicht bei Startnummer 1.
        # Seit die Setzliste nach Stärke sortiert, sind das verschiedene
        # Fahrer — und ein Rennen, das mit „wartet auf Start" aufgeht,
        # zeigt beim Aufschlagen nichts.
        erster = min(
            range(len(room.riders)), key=lambda i: float(room.live.start_offset_s[i])
        )
        session = ViewSession(token=token, room=room, focus_id=room.riders[erster].id)
        self._sessions[token] = session
        while len(self._sessions) > self._max:
            self._sessions.pop(next(iter(self._sessions)), None)
        return session

    def get(self, token: str) -> ViewSession | None:
        return self._sessions.get(token)


__all__ = ["LiveRoom", "LiveRegistry", "ViewSession", "SessionRegistry", "SPEEDS", "BOARD_WINDOW"]
