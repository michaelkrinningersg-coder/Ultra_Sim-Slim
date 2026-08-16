"""Die Weboberfläche: Seiten, Schnittstelle und die Steuerung."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ultraslim.core.season import CALENDAR
from ultraslim.web.main import create_app

RACE_ID = "s2026-ostsee"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        yield c


@pytest.fixture
def laufendes_rennen(client):
    antwort = client.post("/season/s2026/race/ostsee/start", follow_redirects=False)
    assert antwort.status_code == 303
    assert antwort.headers["location"] == f"/race/{RACE_ID}"
    return client


@pytest.fixture
def token(laufendes_rennen):
    return laufendes_rennen.post(f"/api/race/{RACE_ID}/session").json()["token"]


# ----------------------------------------------------------------------
# Seiten
# ----------------------------------------------------------------------
def test_hauptmenue_listet_die_saisons(client):
    antwort = client.get("/")
    assert antwort.status_code == 200
    assert "Saison 2026" in antwort.text
    assert "Saison wählen" in antwort.text


@pytest.mark.parametrize("pfad", ["/", "/season/s2026", "/season/s2028", "/fahrer"])
def test_seiten_antworten(client, pfad):
    assert client.get(pfad).status_code == 200


def test_kalender_zeigt_alle_sechs_rennen(client):
    text = client.get("/season/s2026").text
    for spec in CALENDAR:
        assert spec.name in text


def test_fahrerseite_zeigt_das_ganze_feld(client):
    text = client.get("/fahrer").text
    assert "Vaude–Canyon" in text
    assert text.count('<tr id="f') == 300


def test_unbekannte_saison_ist_ein_vierhundertvier(client):
    assert client.get("/season/gibtsnicht").status_code == 404


def test_rennseite_ohne_uebertragung_erklaert_sich(client):
    antwort = client.get(f"/race/{RACE_ID}")
    assert antwort.status_code == 404
    assert "Übertragung" in antwort.text


def test_rennseite_mit_uebertragung(laufendes_rennen):
    text = laufendes_rennen.get(f"/race/{RACE_ID}").text
    assert "Höhenprofil" in text
    assert "Live-Telemetrie" in text
    assert "Startliste" in text
    assert "Ticker" in text


def test_ergebnis_vor_dem_ziel_verraet_nichts(laufendes_rennen):
    antwort = laufendes_rennen.get(f"/race/{RACE_ID}/ergebnis")
    assert antwort.status_code == 404
    assert "noch nicht zu Ende" in antwort.text


# ----------------------------------------------------------------------
# Schnittstelle
# ----------------------------------------------------------------------
def test_streckendaten_fuer_den_zeichner(laufendes_rennen):
    route = laufendes_rennen.get(f"/api/race/{RACE_ID}/route").json()
    assert route["distance_km"] == 300.0
    profil = route["profile"]
    assert profil["step_m"] == 100.0
    assert len(profil["ele_m"]) == len(profil["grade"]) + 1 == 3001
    assert route["splits"][-1]["kind"] == "finish"


def test_startliste_traegt_die_startzeiten(laufendes_rennen):
    daten = laufendes_rennen.get(f"/api/race/{RACE_ID}/startlist").json()
    assert daten["start_interval_s"] == 600.0
    eintraege = daten["entries"]
    assert len(eintraege) == 300
    # Teamweise verzahnt: Fahrer 0 (Team 0) startet zuerst, Fahrer 12
    # (der erste des zweiten Teams) zehn Minuten später, und der zweite
    # Fahrer des ersten Teams erst nach der ganzen ersten Runde.
    assert eintraege[0]["start_offset_s"] == 0.0
    assert eintraege[12]["start_offset_s"] == 600.0
    assert eintraege[1]["start_offset_s"] == 25 * 600.0
    versaetze = sorted(e["start_offset_s"] for e in eintraege)
    assert versaetze == [i * 600.0 for i in range(300)], "keine Lücken, keine Dubletten"
    assert {"ftp_w", "weight_kg", "height_cm", "nation", "team", "color"} <= set(eintraege[0])


def test_erste_startrunde_bringt_jedes_team_ins_bild(laufendes_rennen):
    """Die ersten fünfundzwanzig Starter sind fünfundzwanzig Teams."""
    eintraege = laufendes_rennen.get(f"/api/race/{RACE_ID}/startlist").json()["entries"]
    erste_runde = sorted(eintraege, key=lambda e: e["start_offset_s"])[:25]
    assert len({e["team"] for e in erste_runde}) == 25


def test_erstes_bild_zeigt_nur_den_ersten_starter(token, laufendes_rennen):
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    assert bild["t_wall"] == 0.0
    assert bild["field"]["on_course"] == 1
    assert bild["field"]["waiting"] == 299
    assert len(bild["positions"]) == 1, "Wartende gehören nicht ins Höhenprofil"
    assert bild["board"]["rows"], "das Board darf nie leer sein"


def test_bild_verraet_keine_zukunft(token, laufendes_rennen):
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    assert bild["field"]["finished"] == 0
    assert not [e for e in bild["ticker"] if e["type"] == "FINISH"]
    assert all(e["t_wall"] <= bild["t_wall"] + 1 for e in bild["ticker"])


def test_sprung_nach_vorn_rechnet_und_zeigt(token, laufendes_rennen):
    laufendes_rennen.post(
        f"/api/playback/{token}/control", json={"action": "seek", "value": 6 * 3600}
    )
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    assert bild["t_wall"] == pytest.approx(6 * 3600, abs=60)
    assert bild["field"]["on_course"] > 30
    assert len(bild["positions"]) == bild["field"]["on_course"] + bild["field"]["finished"]
    assert bild["ticker"]


def test_ruecksprung_geht_und_zeigt_weniger(token, laufendes_rennen):
    laufendes_rennen.post(
        f"/api/playback/{token}/control", json={"action": "seek", "value": 6 * 3600}
    )
    spaet = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    laufendes_rennen.post(
        f"/api/playback/{token}/control", json={"action": "seek", "value": 3600}
    )
    frueh = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    assert frueh["t_wall"] < spaet["t_wall"]
    assert len(frueh["positions"]) < len(spaet["positions"])
    assert len(frueh["ticker"]) <= len(spaet["ticker"])


@pytest.mark.parametrize(
    "aktion, wert",
    [
        ("toggle", None),
        ("speed", 60),
        ("focus", 42),
        ("mode", "split"),
        ("split", 3),
        ("split_follow", False),
        ("sort", "tempo"),
        ("pin", 7),
        ("auto_focus", True),
        ("next_split", None),
        ("next_event", None),
        ("distance", 25000),
    ],
)
def test_steuerbefehle_werden_angenommen(token, laufendes_rennen, aktion, wert):
    antwort = laufendes_rennen.post(
        f"/api/playback/{token}/control", json={"action": aktion, "value": wert}
    )
    assert antwort.status_code == 200
    assert laufendes_rennen.get(f"/api/playback/{token}/frame").status_code == 200


def test_unbekannter_befehl_bricht_nichts(token, laufendes_rennen):
    antwort = laufendes_rennen.post(
        f"/api/playback/{token}/control", json={"action": "quatsch", "value": 1}
    )
    assert antwort.status_code == 200
    assert laufendes_rennen.get(f"/api/playback/{token}/frame").status_code == 200


def test_hoechstens_zwei_fahrer_angeheftet(token, laufendes_rennen):
    for entry in (1, 2, 3):
        laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "pin", "value": entry})
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    assert bild["pinned"] == [2, 3]
    assert len(bild["board"]["pinned"]) == 2


def test_board_zeigt_einen_ausschnitt_um_den_fokus(token, laufendes_rennen):
    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 8 * 3600})
    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "focus", "value": 20})
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    zeilen = bild["board"]["rows"]
    assert len(zeilen) <= 40
    assert 20 in [z["entry_id"] for z in zeilen], "der Fokusfahrer muss im Ausschnitt sein"
    assert bild["board"]["leader"] is not None


def test_wartende_stehen_hinten_in_der_zeitwertung(token, laufendes_rennen):
    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 3600})
    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "sort", "value": "zeit"})
    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "focus", "value": 0})
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    fuehrender = bild["board"]["leader"]
    assert fuehrender["t_s"] is not None, "ein Wartender darf nie führen"
    assert fuehrender["state"] != -1


def test_abgelaufene_sitzung_meldet_sich(client):
    assert client.get("/api/playback/quatschtoken/frame").status_code == 404
    assert client.post("/api/race/gibtsnicht/session").status_code == 404


def test_uebertragung_beenden_fuehrt_zurueck(laufendes_rennen):
    antwort = laufendes_rennen.post(f"/race/{RACE_ID}/close", follow_redirects=False)
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/season/s2026"
    assert laufendes_rennen.get(f"/race/{RACE_ID}").status_code == 404
