"""Die Weboberfläche: Hauptmenü, Saison, Rennen, Strecken.

Alles, was der Browser sieht, kommt von hier. Das Renn-Interface selbst
ist unverändert das des großen Simulators — Ticker, Startliste,
Steuerleiste, Höhenprofil und Telemetrie-Board —, nur ohne die
Anzeigen, für die es in dieser Fassung keine Daten gibt.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..core import gpx
from ..core.engine import RaceConfig
from ..core.rider import generate_pool
from ..core.route import Route
from ..core.season import (
    RaceSpec,
    Season,
    Store,
    all_seasons,
    build_route,
    climb_standings,
    get_season,
    points_for_rank,
    rider_standings,
    team_standings,
    time_standings,
)
from .rooms import SPEEDS, LiveRegistry, LiveRoom, SessionRegistry

HERE = Path(__file__).parent

#: Trennzeichen in der Renn-Kennung. Bewusst nicht der Bindestrich:
#: Streckenkennungen aus einem Dateinamen enthalten reihenweise welche,
#: und ``"s2026-gpx-alpen-tour"`` ließe sich nicht mehr eindeutig
#: auseinandernehmen.
RACE_SEP = "~"

#: Obergrenze für eine hochgeladene GPX-Datei. Eine Tagestour mit
#: Sekundenaufzeichnung liegt bei ein bis zwei Megabyte; zwanzig sind
#: großzügig und schützen trotzdem vor der versehentlich gewählten
#: Videodatei.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

#: So viele Importe dürfen gleichzeitig auf ihre Bestätigung warten.
MAX_PENDING_IMPORTS = 8


def frame_interval(speed: int) -> float:
    """Bildabstand des Ereignisstroms, nach Zeitraffer.

    Deckungsgleich mit der Interpolation in ``live.js`` — läuft der
    Client schneller als der Server liefert, korrigiert sich die Anzeige
    sichtbar rückwärts.
    """
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
    pending: dict[str, gpx.GpxTrack] = {}

    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["hms"] = hms
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    # ------------------------------------------------------------------
    # Nachschlagen
    # ------------------------------------------------------------------
    def season_or_404(season_id: str) -> Season:
        season = get_season(season_id, store)
        if season is None:
            raise HTTPException(404, "Saison unbekannt")
        return season

    def route_for(spec: RaceSpec) -> Route:
        if spec.route_id not in route_cache:
            try:
                route_cache[spec.route_id] = build_route(spec, store)
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
        return route_cache[spec.route_id]

    def split_race_id(race_id: str) -> tuple[str, str]:
        season_id, _, route_id = race_id.partition(RACE_SEP)
        if not route_id:
            raise HTTPException(404, "Rennen unbekannt")
        return season_id, route_id

    def race_id_for(season: Season, spec: RaceSpec) -> str:
        return f"{season.id}{RACE_SEP}{spec.route_id}"

    def spec_or_404(season: Season, route_id: str) -> RaceSpec:
        spec = season.spec_for(route_id)
        if spec is None:
            raise HTTPException(404, "Dieses Rennen gehört nicht zu dieser Saison.")
        return spec

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

    def fehlerseite(request: Request, titel: str, text: str, status: int = 404):
        return templates.TemplateResponse(
            request, "error.html", {"title": titel, "message": text}, status_code=status
        )

    # ------------------------------------------------------------------
    # Hauptmenü und Saison
    # ------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        eintraege = []
        for season in all_seasons(store):
            results = store.load_season(season.id, season.races)
            tabelle = rider_standings(results, riders, teams, season.races)
            eintraege.append(
                {
                    "season": season,
                    "n_done": len(results),
                    "n_races": len(season.races),
                    "leader": tabelle[0].rider.name if results and tabelle[0].points else None,
                }
            )
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "seasons": eintraege,
                "n_riders": len(riders),
                "n_teams": len(teams),
                "n_routes": len(store.list_routes()),
            },
        )

    @app.get("/season/{season_id}", response_class=HTMLResponse)
    def season_page(request: Request, season_id: str):
        season = season_or_404(season_id)
        results = store.load_season(season.id, season.races)

        calendar = []
        for spec in season.races:
            result = results.get(spec.route_id)
            race_id = race_id_for(season, spec)
            try:
                zusammenfassung = route_for(spec).summary()
                fehlt = False
            except HTTPException:
                # Eine importierte Strecke wurde gelöscht, die Saison
                # verweist aber noch darauf. Der Kalender soll das sagen,
                # nicht mit einem Fehler abbrechen.
                zusammenfassung = {
                    "distance_km": spec.distance_km,
                    "ascent_m": int(spec.ascent_m),
                    "archetype_label": spec.archetype,
                    "max_elevation_m": 0,
                }
                fehlt = True
            calendar.append(
                {
                    "spec": spec,
                    "route": zusammenfassung,
                    "missing": fehlt,
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
                "riders_table": rider_standings(results, riders, teams, season.races)[:30],
                "time_table": time_standings(results, riders, teams, season.races)[:30],
                "climbs_table": climb_standings(results, riders, teams, season.races)[:20],
                "teams_table": team_standings(results, riders, teams, season.races),
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
        season = season_or_404(season_id)
        spec = spec_or_404(season, route_id)

        race_id = race_id_for(season, spec)
        if reset:
            store.delete(season.id, route_id)
            rooms.close(race_id)

        if rooms.get(race_id) is None:
            # Die Setzliste entsteht aus dem Stand **vor** diesem Rennen.
            # Ein eigenes Ergebnis darf nicht mitzählen — beim „neu
            # fahren" wäre sonst die alte Platzierung die Setzung.
            vorher = {
                rid: ergebnis
                for rid, ergebnis in store.load_season(season.id, season.races).items()
                if rid != route_id
            }
            punkte = {
                s.rider.id: s.points
                for s in rider_standings(vorher, riders, teams, season.races)
            }
            rooms.add(
                LiveRoom.start(
                    race_id=race_id,
                    season=season,
                    route=route_for(spec),
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

    # ------------------------------------------------------------------
    # Rennen
    # ------------------------------------------------------------------
    @app.get("/race/{race_id}", response_class=HTMLResponse)
    def race_page(request: Request, race_id: str):
        room = rooms.get(race_id)
        if room is None:
            return fehlerseite(
                request,
                "Keine Übertragung",
                "Für dieses Rennen läuft gerade keine Übertragung. "
                "Im Kalender der Saison lässt sie sich starten.",
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
        season_id, route_id = split_race_id(race_id)
        season = season_or_404(season_id)
        spec = spec_or_404(season, route_id)
        result = store.load(season.id, route_id)
        if result is None:
            return fehlerseite(
                request,
                "Noch kein Ergebnis",
                "Dieses Rennen ist noch nicht zu Ende gefahren. Ein Ergebnis "
                "entsteht erst, wenn der letzte Fahrer im Ziel ist.",
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
            {"season": season, "spec": spec, "route": route_for(spec).summary(), "rows": rows},
        )

    @app.post("/race/{race_id}/close")
    def close_race(race_id: str):
        season_id, _ = split_race_id(race_id)
        rooms.close(race_id)
        return RedirectResponse(f"/season/{season_id}", status_code=303)

    @app.get("/fahrer", response_class=HTMLResponse)
    def pool_page(request: Request):
        return templates.TemplateResponse(
            request, "pool.html", {"riders": sorted(riders, key=lambda r: -r.w_per_kg), "teams": teams}
        )

    # ------------------------------------------------------------------
    # Streckenlager
    # ------------------------------------------------------------------
    @app.get("/strecken", response_class=HTMLResponse)
    def routes_page(request: Request, fehler: str | None = None):
        eigene = store.list_routes()
        benutzt: dict[str, list[str]] = {}
        for season in all_seasons(store):
            for spec in season.races:
                if spec.imported:
                    benutzt.setdefault(spec.route_id, []).append(season.name)
        return templates.TemplateResponse(
            request,
            "routes.html",
            {
                "routes": [r.summary() for r in eigene],
                "used_by": benutzt,
                "fehler": fehler,
                "smooth_default": gpx.DEFAULT_SMOOTH_M,
            },
        )

    @app.post("/strecken/import")
    async def import_gpx(datei: UploadFile = File(...)):
        roh = await datei.read()
        if len(roh) > MAX_UPLOAD_BYTES:
            return RedirectResponse(
                f"/strecken?fehler=Die+Datei+ist+größer+als+{MAX_UPLOAD_BYTES // 1024 // 1024}+MB.",
                status_code=303,
            )
        name = Path(datei.filename or "Importierte Strecke").stem
        try:
            track = await asyncio.to_thread(gpx.read_gpx, roh, name)
        except gpx.GpxError as exc:
            return RedirectResponse(f"/strecken?fehler={exc}", status_code=303)

        token = secrets.token_urlsafe(9)
        pending[token] = track
        while len(pending) > MAX_PENDING_IMPORTS:
            pending.pop(next(iter(pending)), None)
        return RedirectResponse(f"/strecken/import/{token}", status_code=303)

    def track_or_404(token: str) -> gpx.GpxTrack:
        track = pending.get(token)
        if track is None:
            raise HTTPException(404, "Der Import ist abgelaufen. Datei bitte neu hochladen.")
        return track

    @app.get("/strecken/import/{token}", response_class=HTMLResponse)
    def import_preview(request: Request, token: str):
        track = pending.get(token)
        if track is None:
            return fehlerseite(
                request,
                "Import abgelaufen",
                "Dieser Import ist nicht mehr im Speicher. Lade die Datei "
                "einfach noch einmal hoch.",
            )
        return templates.TemplateResponse(
            request,
            "import.html",
            {
                "token": token,
                "track": {
                    "name": track.name,
                    "n_points": track.n_points,
                    "distance_km": round(track.distance_m / 1000.0, 1),
                    "raw_ascent_m": round(track.raw_ascent_m),
                },
                "smooth_default": gpx.DEFAULT_SMOOTH_M,
                "smooth_min": gpx.SMOOTH_RANGE_M[0],
                "smooth_max": gpx.SMOOTH_RANGE_M[1],
            },
        )

    @app.get("/api/import/{token}/vorschau")
    async def import_preview_data(token: str, smooth_m: float = gpx.DEFAULT_SMOOTH_M):
        track = track_or_404(token)
        route = await asyncio.to_thread(
            gpx.build_route, track, "vorschau", track.name, smooth_m
        )
        daten = route.to_dict()
        daten["smooth_m"] = smooth_m
        daten["raw_ascent_m"] = round(track.raw_ascent_m)
        return JSONResponse(daten)

    @app.post("/strecken/import/{token}/speichern")
    def import_commit(
        token: str,
        name: str = Form(...),
        smooth_m: float = Form(gpx.DEFAULT_SMOOTH_M),
        ascent_m: float = Form(0.0),
    ):
        track = track_or_404(token)
        name = name.strip()[:80] or track.name
        route_id = gpx.slugify(name)
        # Zwei Strecken gleichen Namens sollen sich nicht überschreiben.
        basis, n = route_id, 2
        while store.has_route(route_id):
            route_id, n = f"{basis}-{n}", n + 1

        route = gpx.build_route(
            track, route_id, name, smooth_m,
            target_ascent_m=ascent_m if ascent_m > 0 else None,
        )
        store.save_route(route)
        route_cache[route_id] = route
        pending.pop(token, None)
        return RedirectResponse("/strecken", status_code=303)

    @app.post("/strecken/{route_id}/loeschen")
    def delete_route(route_id: str):
        store.delete_route(route_id)
        route_cache.pop(route_id, None)
        return RedirectResponse("/strecken", status_code=303)

    # ------------------------------------------------------------------
    # Saison-Editor
    # ------------------------------------------------------------------
    @app.get("/saisons", response_class=HTMLResponse)
    def seasons_page(request: Request, fehler: str | None = None):
        return templates.TemplateResponse(
            request,
            "seasons.html",
            {
                "seasons": [s for s in all_seasons(store) if s.custom],
                "routes": [r.summary() for r in store.list_routes()],
                "fehler": fehler,
            },
        )

    @app.post("/saisons/neu")
    def create_season(
        name: str = Form(...),
        jahr: int = Form(2030),
        seed: int = Form(0),
        strecken: list[str] = Form(default=[]),
    ):
        name = name.strip()[:60]
        if not name:
            return RedirectResponse("/saisons?fehler=Die+Saison+braucht+einen+Namen.", status_code=303)
        if not strecken:
            return RedirectResponse(
                "/saisons?fehler=Wähle+mindestens+eine+Strecke+für+den+Kalender.", status_code=303
            )

        rennen: list[RaceSpec] = []
        for i, route_id in enumerate(strecken):
            route = store.load_route(route_id)
            if route is None:
                continue
            rennen.append(
                RaceSpec(
                    idx=len(rennen),
                    route_id=route.id,
                    name=route.name,
                    distance_km=round(route.distance_km, 1),
                    archetype=route.archetype,
                    ascent_m=round(route.ascent_m),
                    route_seed=None,
                )
            )
            _ = i
        if not rennen:
            return RedirectResponse(
                "/saisons?fehler=Keine+der+gewählten+Strecken+liegt+noch+im+Lager.", status_code=303
            )

        # Die Kennung muss ohne Trennzeichen auskommen, sonst lässt sich
        # eine Renn-Kennung nicht mehr auseinandernehmen.
        basis = gpx.slugify(name, prefix="saison").replace(RACE_SEP, "-")
        season_id, n = basis, 2
        vorhanden = {s.id for s in all_seasons(store)}
        while season_id in vorhanden:
            season_id, n = f"{basis}-{n}", n + 1

        store.save_season(
            Season(
                id=season_id,
                year=int(jahr),
                name=name,
                races=tuple(rennen),
                custom=True,
                seed=int(seed) if seed else int(jahr) * 1000,
            )
        )
        return RedirectResponse(f"/season/{season_id}", status_code=303)

    @app.post("/saisons/{season_id}/loeschen")
    def delete_season(season_id: str):
        season = get_season(season_id, store)
        if season is not None and season.custom:
            for spec in season.races:
                rooms.close(f"{season.id}{RACE_SEP}{spec.route_id}")
            store.delete_season(season_id)
        return RedirectResponse("/saisons", status_code=303)

    # ------------------------------------------------------------------
    # API des Renn-Interfaces
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
                    "descent_skill": round(r.descent_skill),
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
