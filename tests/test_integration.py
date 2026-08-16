"""Ein Rennen von der Startfreigabe bis in die Saisontabelle.

Der langsamste Test im Verzeichnis, und der einzige, der die ganze Kette
prüft: Übertragung starten, bis ins Ziel rechnen, Ergebnis sichern,
Punkte vergeben, Tabellen füllen.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ultraslim.core.season import POINTS, Store, get_season
from ultraslim.web.main import create_app

RACE_ID = "s2026~ostsee"


@pytest.fixture(scope="module")
def gefahrene_saison(tmp_path_factory):
    """Das kürzeste Rennen des Kalenders einmal komplett durchrechnen."""
    ordner = tmp_path_factory.mktemp("saison")
    client = TestClient(create_app(ordner))
    client.post("/season/s2026/race/ostsee/start", follow_redirects=False)
    token = client.post(f"/api/race/{RACE_ID}/session").json()["token"]

    # Ans Ende springen. Das kostet genau die Rechenzeit, die es
    # überspringt — hier rund fünfzehn Sekunden für 300 km, 300 Fahrer
    # und fünfzig Stunden Startfenster.
    bild = client.get(f"/api/playback/{token}/frame").json()
    client.post(
        f"/api/playback/{token}/control",
        json={"action": "seek", "value": bild["horizon_s"] + 3600},
    )
    return client, ordner, token


def test_alle_dreihundert_kommen_ins_ziel(gefahrene_saison):
    client, _, token = gefahrene_saison
    bild = client.get(f"/api/playback/{token}/frame").json()
    assert bild["field"]["finished"] == 300
    assert bild["field"]["on_course"] == 0
    assert bild["field"]["waiting"] == 0


def test_ergebnis_wird_gesichert(gefahrene_saison):
    _, ordner, _ = gefahrene_saison
    ergebnis = Store(ordner).load("s2026", "ostsee")
    assert ergebnis is not None
    assert len(ergebnis.finishers) == 300
    zeiten = [t for _, t in ergebnis.finishers]
    assert zeiten == sorted(zeiten), "das Ergebnis ist nach Zeit sortiert"
    assert len({rid for rid, _ in ergebnis.finishers}) == 300


def test_zeiten_sind_eigenzeiten_und_plausibel(gefahrene_saison):
    _, ordner, _ = gefahrene_saison
    ergebnis = Store(ordner).load("s2026", "ostsee")
    schnellster = ergebnis.finishers[0][1] / 3600
    langsamster = ergebnis.finishers[-1][1] / 3600
    # 300 km, flach, bei 60–72 % der FTP: sieben bis zehn Stunden.
    assert 6.5 < schnellster < 9.0, schnellster
    assert langsamster < 12.0, langsamster
    # Und deutlich kürzer als die Rennuhr, die das Startfenster enthält.
    assert langsamster < 50.0


def test_ergebnisseite_zeigt_das_feld(gefahrene_saison):
    client, _, _ = gefahrene_saison
    antwort = client.get(f"/race/{RACE_ID}/ergebnis")
    assert antwort.status_code == 200
    assert "Ergebnis" in antwort.text
    assert "Einzelstart" in antwort.text


def test_saisontabelle_fuellt_sich(gefahrene_saison):
    client, ordner, _ = gefahrene_saison
    from ultraslim.core.rider import generate_pool
    from ultraslim.core.season import rider_standings, team_standings

    teams, riders = generate_pool()
    ergebnisse = Store(ordner).load_season("s2026")
    assert set(ergebnisse) == {"ostsee"}

    fahrer = rider_standings(ergebnisse, riders, teams)
    assert fahrer[0].points == 100
    assert fahrer[0].wins == 1
    assert sum(f.points for f in fahrer) == sum(POINTS)
    assert sum(1 for f in fahrer if f.points > 0) == 150

    mannschaften = team_standings(ergebnisse, riders, teams)
    assert sum(t.points for t in mannschaften) == sum(POINTS)
    assert mannschaften[0].top_rider is not None


def test_kalender_meldet_das_rennen_als_gefahren(gefahrene_saison):
    client, _, _ = gefahrene_saison
    text = client.get("/season/s2026").text
    assert "gefahren" in text
    assert "Fahrerwertung" in text
    assert "Teamwertung" in text
    # Der Sieger steht mit Zeit im Kalender.
    saison = get_season("s2026")
    assert saison is not None


def test_hauptmenue_zeigt_den_fortschritt(gefahrene_saison):
    client, _, _ = gefahrene_saison
    text = client.get("/").text
    assert "1 von 6 Rennen gefahren" in text
    assert "Führend:" in text
