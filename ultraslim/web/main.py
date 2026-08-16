"""Die Weboberfläche: Hauptmenü, Saison, Rennen.

Alles, was der Browser sieht, kommt von hier. Das Renn-Interface selbst
ist unverändert das des großen Simulators — Ticker, Startliste,
Steuerleiste, Höhenprofil und Telemetrie-Board —, nur ohne die
Anzeigen, für die es in dieser Fassung keine Daten gibt.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..core.engine import RaceConfig
from ..core.rider import generate_pool
from ..core.route import Route
from ..core.season import (
    CALENDAR,
    Store,
    all_seasons,
    build_route,
    get_race_spec,
    get_season,
    points_for_rank,
    rider_standings,
    team_standings,
)
from .rooms import SPEEDS, LiveRegistry, LiveRoom, SessionRegistry

HERE = Path(__file__).parent

#: Bildabstand des Ereignisstroms, nach Zeitraffer. Deckungsgleich mit
#: der Interpolation in ``live.js`` — läuft der Client schneller als der
#: Server liefert, korrigiert sich die Anzeige sichtbar rückwärts.
def frame_interval(speed: int) -> float:
    return 0.25 if speed <= 10 else 0.5 if speed <= 60 else 1.0


def hms(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = int(round(abs(seconds)))
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def create_app(data_dir: str | Path = "data") -> FastAPI:
    app = FastAPI(title="UltraSim Slim", docs_url=None, redoc_url=None)

    teams, riders = generate_pool()
    store = Store(data_dir)
    rooms = LiveRegistry()
    sessions = SessionRegistry()
    route_cache: dict[str, Route] = {}

    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["hms"] = hms
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    # ------------------------------------------------------------------
    def route_for(route_id: str) -> Route:
        if route_id not in route_cache:
            spec = get_race_spec(route_id)
            if spec is None:
                raise HTTPException(404, "Strecke unbekannt")
            route_cache[route_id] = build_route(spec)
        return route_cache[route_id]

    def room_or_404(race_id: str) -> LiveRoom:
        room = rooms.get(race_id)
        if room is None:
            raise HTTPException(404, "Für dieses Rennen läuft keine Übertragung.")
        return room

    def session_or_404(token: str):
        session = sessions.get(token)
        if session is None:
            raise HTTPException(404, "Sitzung abgelaufen. Seite neu laden.")
        return session

    # ------------------------------------------------------------------
    # Seiten
    # ------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        seasons = []
        for season in all_seasons():
            results = store.load_season(season.id)
            seasons.append(
                {
                    "season": season,
                    "n_done": len(results),
                    "n_races": len(CALENDAR),
                    "leader": _leader_name(results),
                }
            )
        return templates.TemplateResponse(
            request, "index.html", {"seasons": seasons, "n_riders": len(riders), "n_teams": len(teams)}
        )

    def _leader_name(results) -> str | None:
        if not results:
            return None
        standings = rider_standings(results, riders, teams)
        return standings[0].rider.name if standings and standings[0].points else None

    @app.get("/season/{season_id}", response_class=HTMLResponse)
    def season_page(request: Request, season_id: str):
        season = get_season(season_id)
        if season is None:
            raise HTTPException(404, "Saison unbekannt")
        results = store.load_season(season.id)

        calendar = []
        for spec in CALENDAR:
            route = route_for(spec.route_id)
            result = results.get(spec.route_id)
            race_id = season.race_id(spec)
            calendar.append(
                {
                    "spec": spec,
                    "route": route.summary(),
                    "done": result is not None,
                    "live": rooms.get(race_id) is not None,
                    "race_id": race_id,
                    "winner": _winner_of(result),
                    "winner_time_s": result.winner_time_s if result else None,
                }
            )

        return templates.TemplateResponse(
            request,
            "season.html",
            {
                "season": season,
                "calendar": calendar,
                "riders_table": rider_standings(results, riders, teams)[:30],
                "teams_table": team_standings(results, riders, teams),
                "n_done": len(results),
            },
        )

    def _winner_of(result):
        if result is None or not result.finishers:
            return None
        rider_id = result.finishers[0][0]
        return next((r for r in riders if r.id == rider_id), None)

    @app.post("/season/{season_id}/race/{route_id}/start")
    def start_race(season_id: str, route_id: str, reset: bool = False):
        season = get_season(season_id)
        spec = get_race_spec(route_id)
        if season is None or spec is None:
            raise HTTPException(404, "Rennen unbekannt")

        race_id = season.race_id(spec)
        if reset:
            store.delete(season.id, route_id)
            rooms.close(race_id)

        if rooms.get(race_id) is None:
            # Die Setzliste entsteht aus dem Stand **vor** diesem Rennen.
            # Ein eigenes Ergebnis darf nicht mitzählen — beim „neu
            # fahren" wäre sonst die alte Platzierung die Setzung.
            vorher = {
                rid: result
                for rid, result in store.load_season(season.id).items()
                if rid != route_id
            }
            punkte = {
                s.rider.id: s.points for s in rider_standings(vorher, riders, teams)
            }
            rooms.add(
                LiveRoom.start(
                    race_id=race_id,
                    season=season,
                    route=route_for(route_id),
                    riders=riders,
                    teams=teams,
                    config=RaceConfig(
                        name=spec.name,
                        seed=season.race_seed(spec),
                        season_points=punkte,
                    ),
                    store=store,
                )
            )
        return RedirectResponse(f"/race/{race_id}", status_code=303)

    @app.get("/race/{race_id}", response_class=HTMLResponse)
    def race_page(request: Request, race_id: str):
        room = rooms.get(race_id)
        if room is None:
            return templates.TemplateResponse(
                request,
                "error.html",
                {
                    "title": "Keine Übertragung",
                    "message": "Für dieses Rennen läuft gerade keine Übertragung. "
                    "Im Kalender der Saison lässt sie sich starten.",
                },
                status_code=404,
            )
        return templates.TemplateResponse(
            request,
            "race.html",
            {
                "race_id": race_id,
                "race_name": room.live.config.name,
                "season": room.season,
                "route": room.route.summary(),
                "n_entries": len(room.riders),
                "intensity": round(room.live.intensity_factor * 100),
                "is_live": not room.finished,
            },
        )

    @app.get("/race/{race_id}/ergebnis", response_class=HTMLResponse)
    def race_results(request: Request, race_id: str):
        season_id, _, route_id = race_id.partition("-")
        season = get_season(season_id)
        spec = get_race_spec(route_id)
        if season is None or spec is None:
            raise HTTPException(404, "Rennen unbekannt")
        result = store.load(season.id, route_id)
        if result is None:
            return templates.TemplateResponse(
                request,
                "error.html",
                {
                    "title": "Noch kein Ergebnis",
                    "message": "Dieses Rennen ist noch nicht zu Ende gefahren. "
                    "Ein Ergebnis entsteht erst, wenn der letzte Fahrer im Ziel ist.",
                },
                status_code=404,
            )
        by_id = {r.id: r for r in riders}
        rows = [
            {
                "rank": rank,
                "rider": by_id[rider_id],
                "team": teams[by_id[rider_id].team_id],
                "time_s": t,
                "gap_s": t - result.finishers[0][1],
                "points": points_for_rank(rank),
            }
            for rank, rider_id, t in result.ranking()
            if rider_id in by_id
        ]
        return templates.TemplateResponse(
            request,
            "results.html",
            {"season": season, "spec": spec, "route": route_for(route_id).summary(), "rows": rows},
        )

    @app.post("/race/{race_id}/close")
    def close_race(race_id: str):
        room = rooms.get(race_id)
        season_id = room.season.id if room else race_id.partition("-")[0]
        rooms.close(race_id)
        return RedirectResponse(f"/season/{season_id}", status_code=303)

    @app.get("/fahrer", response_class=HTMLResponse)
    def pool_page(request: Request):
        rows = sorted(riders, key=lambda r: -r.w_per_kg)
        return templates.TemplateResponse(
            request, "pool.html", {"riders": rows, "teams": teams}
        )

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------
    @app.get("/api/race/{race_id}/route")
    def api_route(race_id: str):
        return JSONResponse(room_or_404(race_id).route.to_dict())

    @app.get("/api/race/{race_id}/startlist")
    def api_startlist(race_id: str):
        room = room_or_404(race_id)
        offsets = room.live.start_offset_s
        return {
            "start_interval_s": room.live.config.start_interval_s,
            "entries": [
                {
                    "entry_id": r.id,
                    "bib": r.bib,
                    "name": r.name,
                    "nation": r.nation,
                    "team": room.teams[r.team_id].name,
                    "color": room.teams[r.team_id].color,
                    "ftp_w": round(r.ftp_w),
                    "weight_kg": round(r.weight_kg, 1),
                    "height_cm": round(r.height_cm),
                    "w_per_kg": round(r.w_per_kg, 2),
                    "start_offset_s": round(float(offsets[k]), 1),
                }
                for k, r in enumerate(room.riders)
            ],
        }

    @app.post("/api/race/{race_id}/session")
    def api_session(race_id: str):
        return {"token": sessions.create(room_or_404(race_id)).token, "speeds": list(SPEEDS)}

    @app.get("/api/playback/{token}/frame")
    async def api_frame(token: str):
        session = session_or_404(token)
        return JSONResponse(await asyncio.to_thread(session.frame))

    @app.post("/api/playback/{token}/control")
    async def api_control(token: str, request: Request):
        session = session_or_404(token)
        payload = await request.json()
        # Die Steuerung kann rechnen — ein Sprung zum nächsten Ereignis
        # zieht den Generator vorwärts. Das gehört nicht in die
        # Ereignisschleife, sonst steht der ganze Server dabei still.
        await asyncio.to_thread(session.control, payload.get("action", ""), payload.get("value"))
        return {"ok": True}

    @app.get("/api/playback/{token}/stream")
    async def api_stream(token: str):
        session = session_or_404(token)

        async def pump():
            while True:
                frame = await asyncio.to_thread(session.frame)
                yield f"event: frame\ndata: {json.dumps(frame)}\n\n"
                await asyncio.sleep(frame_interval(session.speed))

        return StreamingResponse(
            pump(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
