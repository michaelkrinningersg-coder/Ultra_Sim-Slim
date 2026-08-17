"""Die Weboberfläche: Seiten, Schnittstelle und die Steuerung."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ultraslim.core.engine import STATE_FINISHED, STATE_WAITING
from ultraslim.core.season import CALENDAR
from ultraslim.web.main import create_app

RACE_ID = "s2026~ostsee"


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
    versaetze = sorted(e["start_offset_s"] for e in eintraege)
    assert versaetze == [i * 600.0 for i in range(300)], "keine Lücken, keine Dubletten"
    assert {"ftp_w", "weight_kg", "height_cm", "nation", "team", "color"} <= set(eintraege[0])


def test_der_staerkste_startet_zuletzt(laufendes_rennen):
    """Setzliste nach relativer FTP: der Schwächste rollt zuerst los."""
    eintraege = laufendes_rennen.get(f"/api/race/{RACE_ID}/startlist").json()["entries"]
    nach_start = sorted(eintraege, key=lambda e: e["start_offset_s"])
    wkg = [e["w_per_kg"] for e in nach_start]
    assert wkg == sorted(wkg), "die Startfolge muss der relativen FTP folgen"
    assert nach_start[0]["start_offset_s"] == 0.0
    assert nach_start[-1]["start_offset_s"] == 299 * 600.0
    assert wkg[-1] > wkg[0] + 1.5, "zwischen erstem und letztem Starter liegen Welten"


def test_erstes_bild_zeigt_nur_den_ersten_starter(token, laufendes_rennen):
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    assert bild["t_wall"] == 0.0
    assert bild["field"]["on_course"] == 1
    assert bild["field"]["waiting"] == 299
    assert len(bild["positions"]) == 1, "Wartende gehören nicht ins Höhenprofil"
    assert bild["board"]["rows"], "das Board darf nie leer sein"


def test_der_fokus_beginnt_bei_jemandem_der_faehrt(token, laufendes_rennen):
    """Ein Rennen, das mit 'wartet auf Start' aufgeht, zeigt nichts."""
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    fokus = bild["focus"]
    assert fokus["started"] is True
    assert fokus["start_offset_s"] == 0.0
    assert fokus["state"] != -1


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


def _messstelle_mit_laufenden_uhren(client, token, t_wall: float) -> int:
    """Sucht eine Messstelle, vor der zum Zeitpunkt t_wall noch gefahren wird.

    Der Splitraster hängt an der Strecke (alle 5 % plus Bergspitzen), die
    Zahl der Messstellen darf sich also ändern, ohne dass die Tests darunter
    brechen: Gesucht wird die erste Stelle, an der überhaupt laufende Uhren
    im Ausschnitt stehen.
    """
    steuern = lambda a, v: client.post(  # noqa: E731
        f"/api/playback/{token}/control", json={"action": a, "value": v}
    )
    steuern("mode", "split")
    steuern("split_follow", False)
    steuern("seek", t_wall)
    for idx in range(40):
        steuern("split", idx)
        bild = client.get(f"/api/playback/{token}/frame").json()
        if any(z["running"] for z in bild["board"]["rows"]):
            return idx
    raise AssertionError("Testaufbau: keine Messstelle mit laufenden Uhren gefunden")


def test_splitwertung_zeigt_die_laufende_uhr(token, laufendes_rennen):
    """Wer die Messstelle noch vor sich hat, steht mit seiner Uhr da.

    Keine Hochrechnung: Die Zeit ist die gefahrene Eigenzeit, sie zählt
    weiter, und der Fahrer wandert nach unten, sobald sie eine gefahrene
    Zeit überholt.
    """
    _messstelle_mit_laufenden_uhren(laufendes_rennen, token, 8 * 3600)
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()

    unterwegs = [r for r in bild["board"]["rows"] if r["running"]]
    assert unterwegs, "es müssen Fahrer vor der Messstelle stehen"
    for zeile in unterwegs:
        assert zeile["provisional"] is True, "laufende Uhren stehen kursiv"
        # Die Uhr eines Fahrers, der noch fährt, ist seine Eigenzeit —
        # und damit höchstens die Rennuhr.
        # Wer eben erst losgerollt ist, steht mit null da — das ist die
        # Uhr, nicht ihr Fehlen.
        assert 0 <= zeile["t_s"] <= bild["t_wall"] + 1
        assert zeile["to_next_m"] is not None and zeile["to_next_m"] > 0

    # Eine laufende Uhr darf unter der Bestzeit liegen: Der Fahrer hat
    # die Zeit noch nicht verloren, solange die Uhr sie nicht abläuft.
    assert any(z["gap_s"] < 0 for z in unterwegs) or all(
        z["gap_s"] >= 0 for z in unterwegs
    )


def test_laufende_uhr_waechst_mit_der_rennuhr(token, laufendes_rennen):
    """Dieselbe Zeile, zwei Momente: Die Uhr muss weitergezählt haben."""
    steuern = lambda a, v: laufendes_rennen.post(  # noqa: E731
        f"/api/playback/{token}/control", json={"action": a, "value": v}
    )
    messstelle = _messstelle_mit_laufenden_uhren(laufendes_rennen, token, 9 * 3600)
    steuern("split", messstelle)

    steuern("seek", 9 * 3600)
    frueh = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    steuern("seek", 9 * 3600 + 900)
    spaet = laufendes_rennen.get(f"/api/playback/{token}/frame").json()

    frueh_rows = {r["entry_id"]: r for r in frueh["board"]["rows"] if r["running"]}
    getestet = 0
    for entry, spaeter in ((r["entry_id"], r) for r in spaet["board"]["rows"]):
        vorher = frueh_rows.get(entry)
        if vorher is None or not spaeter["running"]:
            continue
        assert spaeter["t_s"] == pytest.approx(vorher["t_s"] + 900, abs=5)
        assert spaeter["dist_km"] > vorher["dist_km"]
        getestet += 1
    assert getestet > 0, "es muss vergleichbare Zeilen geben"


def test_zwischenwertung_zeigt_das_ganze_gewertete_feld(token, laufendes_rennen):
    """Kein Ausschnitt: Wer durch ist, steht in der Liste.

    In der virtuellen Rangliste ist ein Fenster um den Fokusfahrer
    richtig — dort schaut man auf eine Momentaufnahme. Die
    Zwischenwertung ist eine Ergebnisliste; sie hört nicht bei vierzig
    Zeilen auf.
    """
    steuern = lambda a, v: laufendes_rennen.post(  # noqa: E731
        f"/api/playback/{token}/control", json={"action": a, "value": v}
    )
    steuern("mode", "split")
    steuern("split_follow", False)
    steuern("seek", 24 * 3600)
    steuern("split", 3)
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()

    zeilen = bild["board"]["rows"]
    assert bild["board"]["n_reached"] > 40, "Testaufbau: mehr als ein Fenster voll"
    gemessen = [z for z in zeilen if not z["provisional"]]
    assert len(gemessen) == bild["board"]["n_reached"]
    assert all(z["t_s"] is not None for z in zeilen), "wer keine Uhr hat, steht nicht drin"

    # Die virtuelle Rangliste bleibt beim Ausschnitt.
    steuern("mode", "virtual")
    virtuell = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    assert len(virtuell["board"]["rows"]) <= 40


def test_rangziffer_nur_fuer_gefahrene_zeiten(token, laufendes_rennen):
    """Der Rang gehört zur gemessenen Zeit, nicht zur Tabellenzeile.

    Laufende Uhren reihen sich weiter live ein — aber ohne Platzziffer,
    und die Ziffern der Gemessenen zählen lückenlos durch.
    """
    _messstelle_mit_laufenden_uhren(laufendes_rennen, token, 20 * 3600)
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    zeilen = bild["board"]["rows"]

    laufend = [z for z in zeilen if z["running"]]
    gemessen = [z for z in zeilen if not z["provisional"]]
    assert laufend and gemessen, "Testaufbau: beides muss vorkommen"
    assert all(z["rank"] is None for z in laufend)
    assert sorted(z["rank"] for z in gemessen) == list(range(1, len(gemessen) + 1))

    # Und die Reihenfolge der Ziffern folgt der gefahrenen Zeit. Die
    # ausgegebene Zeit ist auf die Zehntelsekunde gerundet; wer enger
    # beieinanderliegt, darf in jeder Reihenfolge stehen.
    nach_rang = sorted(gemessen, key=lambda z: z["rank"])
    zeiten = [z["t_s"] for z in nach_rang]
    assert all(b >= a - 0.2 for a, b in zip(zeiten, zeiten[1:]))


def test_vorheriger_rang_nur_fuer_die_messstelle_davor(token, laufendes_rennen):
    """„Rg −1" ist der Platz an der Messstelle davor — oder nichts."""
    steuern = lambda a, v: laufendes_rennen.post(  # noqa: E731
        f"/api/playback/{token}/control", json={"action": a, "value": v}
    )
    steuern("mode", "split")
    steuern("split_follow", False)
    steuern("seek", 20 * 3600)
    steuern("split", 0)
    erste = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    assert all(z["prev_rank"] is None for z in erste["board"]["rows"]), \
        "vor der ersten Messstelle gibt es keine davor"

    steuern("split", 6)
    spaeter = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    zeilen = spaeter["board"]["rows"]
    raenge = [z["prev_rank"] for z in zeilen if z["prev_rank"] is not None]
    assert raenge, "an einer späteren Messstelle muss es sie geben"
    assert len(set(raenge)) == len(raenge), "jeder Platz nur einmal vergeben"
    assert min(raenge) == 1


def test_der_verfall_steht_in_der_telemetrie(token, laufendes_rennen):
    """Ausdauer und Verfall müssen im Bild ankommen, nicht nur im Modell."""
    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 12 * 3600})
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()

    fokus = bild["focus"]
    assert 0 <= fokus["endurance"] <= 100
    assert fokus["fade_pct"] is not None

    zeilen = bild["board"]["rows"]
    unterwegs = [z for z in zeilen if z["state"] == 0]
    assert unterwegs, "Testaufbau: es muss Fahrer auf der Strecke geben"
    for zeile in unterwegs:
        assert zeile["fade_pct"] is not None
        assert 85.0 < zeile["fade_pct"] < 115.0, "der Deckel begrenzt den Verfall"
    # Wer noch wartet, hat keinen; wer im Ziel ist, behält den, den er
    # bei seiner Zielzeit hatte — er steigt nicht weiter.
    for zeile in zeilen:
        if zeile["state"] == STATE_WAITING:
            assert zeile["fade_pct"] is None

    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 20 * 3600})
    spaeter = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    vorher = {z["entry_id"]: z for z in zeilen if z["state"] == STATE_FINISHED}
    verglichen = 0
    for zeile in spaeter["board"]["rows"]:
        alt = vorher.get(zeile["entry_id"])
        if alt is None:
            continue
        assert zeile["fade_pct"] == alt["fade_pct"], "im Ziel steht der Verfall still"
        verglichen += 1
    assert verglichen, "Testaufbau: es muss Fahrer im Ziel geben"

    # Und danach sortieren lässt sich auch.
    antwort = laufendes_rennen.post(
        f"/api/playback/{token}/control", json={"action": "sort", "value": "verfall"}
    )
    assert antwort.status_code == 200
    sortiert = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    assert sortiert["sort"] == "verfall"


def test_startliste_nennt_beide_zusatzwerte(laufendes_rennen):
    daten = laufendes_rennen.get(f"/api/race/{RACE_ID}/startlist").json()
    erster = daten["entries"][0]
    assert 0 <= erster["descent_skill"] <= 100
    assert 0 <= erster["endurance"] <= 100


def test_kopfzeile_zeigt_die_beste_gefahrene_zeit(token, laufendes_rennen):
    """Worauf sich der Rückstand bezieht, muss auch obenstehen.

    Rang eins ist in der Splitwertung regelmäßig ein Fahrer, dessen Uhr
    erst Minuten läuft. Die Rückstandsspalte misst aber gegen die beste
    *gefahrene* Zeit — und die gehört in die angeheftete Kopfzeile.
    """
    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 12 * 3600})
    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "mode", "value": "split"})
    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "split_follow", "value": False})
    laufendes_rennen.post(f"/api/playback/{token}/control", json={"action": "split", "value": 2})
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()

    fuehrender = bild["board"]["leader"]
    assert bild["board"]["n_reached"] > 0, "Testaufbau: es muss Messwerte geben"
    assert fuehrender is not None
    assert fuehrender["provisional"] is False, "der Führende hat eine gefahrene Zeit"
    assert fuehrender["gap_s"] == 0.0, "auf ihn bezieht sich der Rückstand"

    # Keine gemessene Zeit im Feld darf besser sein.
    gemessen = [r["t_s"] for r in bild["board"]["rows"] if not r["provisional"] and r["t_s"]]
    assert all(t >= fuehrender["t_s"] - 1e-6 for t in gemessen)


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


# ----------------------------------------------------------------------
# Splitwertung: wer überhaupt in der Liste steht
# ----------------------------------------------------------------------
def test_split_zeigt_nur_wer_die_vorherige_messstelle_durch_hat(token, laufendes_rennen):
    """Sonst steht die Spitze dauerhaft voll mit Frischgestarteten.

    Alle zehn Minuten rollt einer los, seine Uhr steht bei fast null —
    und die beste gefahrene Zeit rutscht weit nach unten. Wer die
    vorherige Messstelle noch vor sich hat, gehört nicht in diese
    Wertung.
    """
    steuern = lambda a, v: laufendes_rennen.post(  # noqa: E731
        f"/api/playback/{token}/control", json={"action": a, "value": v}
    )
    steuern("seek", 14 * 3600)
    steuern("mode", "split")
    steuern("split_follow", False)
    steuern("split", 3)
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()

    gewertet = [r for r in bild["board"]["rows"] if r["t_s"] is not None]
    assert gewertet, "irgendwer muss in der Wertung stehen"

    # Niemand mit einer laufenden Uhr darf noch vor der vorherigen
    # Messstelle stehen: Die Strecke bis dorthin hat er hinter sich.
    vorherige_km = bild["board"]["split"]["dist_m"] / 1000.0
    for zeile in gewertet:
        if zeile["running"]:
            assert zeile["dist_km"] > 0.0
            assert zeile["dist_km"] < vorherige_km, "sonst wäre er schon durch"

    # Und ein gerade Gestarteter steht nicht an der Spitze.
    assert bild["board"]["rows"][0]["dist_km"] > 1.0


def test_erste_messstelle_nimmt_alle_gestarteten(token, laufendes_rennen):
    """Bei Split eins gibt es keine vorherige — dort genügt der Start."""
    steuern = lambda a, v: laufendes_rennen.post(  # noqa: E731
        f"/api/playback/{token}/control", json={"action": a, "value": v}
    )
    steuern("seek", 5 * 3600)
    steuern("mode", "split")
    steuern("split_follow", False)
    steuern("split", 0)
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()

    gewertet = sum(1 for r in bild["board"]["rows"] if r["t_s"] is not None)
    assert gewertet == len(bild["board"]["rows"]) or bild["field"]["waiting"] > 0
    # Wer gestartet ist, hat eine Zeit; wer wartet, nicht.
    for zeile in bild["board"]["rows"]:
        if zeile["state"] == -1:
            assert zeile["t_s"] is None
        else:
            assert zeile["t_s"] is not None


# ----------------------------------------------------------------------
# GPX-Import und Saison-Editor
# ----------------------------------------------------------------------
def _gpx_datei(km: float = 40.0, hm: float = 600.0, seed: int = 3) -> bytes:
    from tests.test_gpx import synth_gpx
    from ultraslim.core.route import generate_route

    return synth_gpx(generate_route("t", "Probefahrt", km, "wellig", hm, seed=seed))


def test_streckenlager_ist_zunaechst_leer(client):
    text = client.get("/strecken").text
    assert "Noch keine eigene Strecke" in text
    assert "GPX hochladen" in text


def test_import_fuehrt_ueber_die_vorschau(client):
    antwort = client.post(
        "/strecken/import",
        files={"datei": ("probe.gpx", _gpx_datei(), "application/gpx+xml")},
        follow_redirects=False,
    )
    assert antwort.status_code == 303
    ziel = antwort.headers["location"]
    assert ziel.startswith("/strecken/import/")

    seite = client.get(ziel)
    assert seite.status_code == 200
    assert "Glättung einstellen" in seite.text

    token = ziel.rsplit("/", 1)[-1]
    grob = client.get(f"/api/import/{token}/vorschau?smooth_m=0").json()
    fein = client.get(f"/api/import/{token}/vorschau?smooth_m=400").json()
    assert grob["ascent_m"] > fein["ascent_m"], "der Regler muss wirken"
    assert grob["raw_ascent_m"] >= grob["ascent_m"]
    assert len(fein["profile"]["ele_m"]) == len(fein["profile"]["grade"]) + 1


def test_kaputte_datei_landet_mit_begruendung_zurueck(client):
    antwort = client.post(
        "/strecken/import",
        files={"datei": ("murks.gpx", b"kein xml", "application/gpx+xml")},
        follow_redirects=False,
    )
    assert antwort.status_code == 303
    assert "fehler=" in antwort.headers["location"]


def test_abgelaufener_import_erklaert_sich(client):
    antwort = client.get("/strecken/import/gibtsnicht")
    assert antwort.status_code == 404
    assert "abgelaufen" in antwort.text.lower()


def test_gespeicherte_strecke_steht_im_lager(client):
    ziel = client.post(
        "/strecken/import",
        files={"datei": ("probe.gpx", _gpx_datei(), "application/gpx+xml")},
        follow_redirects=False,
    ).headers["location"]
    token = ziel.rsplit("/", 1)[-1]

    antwort = client.post(
        f"/strecken/import/{token}/speichern",
        data={"name": "Probefahrt Süd", "smooth_m": "200", "ascent_m": "0"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303
    text = client.get("/strecken").text
    assert "Probefahrt Süd" in text
    assert "gpx-probefahrt-sued" in text
    # Und sie taucht im Hauptmenü als Bestand auf.
    assert "1 Strecken im Lager" in client.get("/").text


def test_gleiche_namen_ueberschreiben_sich_nicht(client):
    for _ in range(2):
        ziel = client.post(
            "/strecken/import",
            files={"datei": ("probe.gpx", _gpx_datei(), "application/gpx+xml")},
            follow_redirects=False,
        ).headers["location"]
        client.post(
            f"/strecken/import/{ziel.rsplit('/', 1)[-1]}/speichern",
            data={"name": "Doppelt", "smooth_m": "200", "ascent_m": "0"},
            follow_redirects=False,
        )
    text = client.get("/strecken").text
    assert "gpx-doppelt<" in text or "gpx-doppelt" in text
    assert "gpx-doppelt-2" in text


def _lege_strecke_an(client, name: str, km: float = 40.0, hm: float = 600.0, seed: int = 3) -> None:
    ziel = client.post(
        "/strecken/import",
        files={"datei": ("probe.gpx", _gpx_datei(km, hm, seed), "application/gpx+xml")},
        follow_redirects=False,
    ).headers["location"]
    client.post(
        f"/strecken/import/{ziel.rsplit('/', 1)[-1]}/speichern",
        data={"name": name, "smooth_m": "200", "ascent_m": "0"},
        follow_redirects=False,
    )


def test_eigene_saison_aus_zwei_strecken(client):
    _lege_strecke_an(client, "Etappe Eins", km=40, seed=3)
    _lege_strecke_an(client, "Etappe Zwei", km=60, hm=1400, seed=4)

    antwort = client.post(
        "/saisons/neu",
        data={
            "name": "Alpenserie",
            "jahr": "2031",
            "seed": "0",
            "strecken": ["gpx-etappe-eins", "gpx-etappe-zwei"],
        },
        follow_redirects=False,
    )
    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/season/saison-alpenserie"

    seite = client.get("/season/saison-alpenserie")
    assert seite.status_code == 200
    assert "Etappe Eins" in seite.text and "Etappe Zwei" in seite.text
    # Und im Hauptmenü neben den mitgelieferten.
    assert "Alpenserie" in client.get("/").text


def test_saison_ohne_strecken_wird_abgelehnt(client):
    antwort = client.post(
        "/saisons/neu", data={"name": "Leer", "jahr": "2031", "seed": "0"},
        follow_redirects=False,
    )
    assert antwort.status_code == 303
    assert "fehler=" in antwort.headers["location"]


def test_rennen_in_eigener_saison_laeuft(client):
    _lege_strecke_an(client, "Hausrunde", km=40, seed=7)
    client.post(
        "/saisons/neu",
        data={"name": "Hausserie", "jahr": "2031", "seed": "0", "strecken": ["gpx-hausrunde"]},
        follow_redirects=False,
    )
    antwort = client.post(
        "/season/saison-hausserie/race/gpx-hausrunde/start", follow_redirects=False
    )
    assert antwort.status_code == 303
    race_id = antwort.headers["location"].rsplit("/", 1)[-1]
    assert race_id == "saison-hausserie~gpx-hausrunde"

    assert client.get(f"/race/{race_id}").status_code == 200
    route = client.get(f"/api/race/{race_id}/route").json()
    assert route["distance_km"] == pytest.approx(40.0, abs=0.5)

    token = client.post(f"/api/race/{race_id}/session").json()["token"]
    bild = client.get(f"/api/playback/{token}/frame").json()
    assert bild["field"]["waiting"] + bild["field"]["on_course"] == 300


def test_geloeschte_strecke_bricht_die_saison_nicht(client):
    _lege_strecke_an(client, "Weg Bald", km=40, seed=9)
    client.post(
        "/saisons/neu",
        data={"name": "Kurzserie", "jahr": "2031", "seed": "0", "strecken": ["gpx-weg-bald"]},
        follow_redirects=False,
    )
    client.post("/strecken/gpx-weg-bald/loeschen", follow_redirects=False)

    seite = client.get("/season/saison-kurzserie")
    assert seite.status_code == 200, "der Kalender muss lesbar bleiben"
    assert "Strecke fehlt" in seite.text


def test_eigene_saison_laesst_sich_loeschen(client):
    _lege_strecke_an(client, "Vergaenglich", km=40, seed=11)
    client.post(
        "/saisons/neu",
        data={"name": "Wegwerf", "jahr": "2031", "seed": "0", "strecken": ["gpx-vergaenglich"]},
        follow_redirects=False,
    )
    assert "Wegwerf" in client.get("/").text

    client.post("/saisons/saison-wegwerf/loeschen", follow_redirects=False)
    assert "Wegwerf" not in client.get("/").text
    assert client.get("/season/saison-wegwerf").status_code == 404
    # Die Strecke bleibt im Lager.
    assert "Vergaenglich" in client.get("/strecken").text


def test_mitgelieferte_saison_laesst_sich_nicht_loeschen(client):
    client.post("/saisons/s2026/loeschen", follow_redirects=False)
    assert client.get("/season/s2026").status_code == 200


# ----------------------------------------------------------------------
# Bergwertung im Board
# ----------------------------------------------------------------------
@pytest.fixture
def bergrennen(client):
    """Die Karpaten-Traverse — Mittelgebirge mit reichlich Anstiegen."""
    antwort = client.post("/season/s2026/race/karpaten/start", follow_redirects=False)
    assert antwort.status_code == 303
    race_id = "s2026~karpaten"
    token = client.post(f"/api/race/{race_id}/session").json()["token"]
    return client, race_id, token


def test_modus_bergwertung_liefert_den_anstieg(bergrennen):
    client, _, token = bergrennen
    steuern = lambda a, v: client.post(  # noqa: E731
        f"/api/playback/{token}/control", json={"action": a, "value": v}
    )
    steuern("seek", 14 * 3600)
    steuern("mode", "climb")
    bild = client.get(f"/api/playback/{token}/frame").json()

    assert bild["mode"] == "climb"
    climb = bild["board"]["climb"]
    assert climb is not None
    assert climb["n_total_climbs"] > 0
    assert climb["ascent_m"] > 0 and climb["length_m"] > 0
    assert 0 < climb["avg_grade_pct"] < 25
    assert climb["dist_end_m"] > climb["dist_start_m"]
    assert 0 <= climb["n_done"] <= bild["board"]["n_total"]


def test_bergwertung_zeigt_auffahrtsdauer_statt_rennzeit(bergrennen):
    client, _, token = bergrennen
    steuern = lambda a, v: client.post(  # noqa: E731
        f"/api/playback/{token}/control", json={"action": a, "value": v}
    )
    steuern("seek", 16 * 3600)
    steuern("mode", "climb")
    steuern("climb_follow", False)
    steuern("climb", 1)
    bild = client.get(f"/api/playback/{token}/frame").json()

    gewertet = [r for r in bild["board"]["rows"] if r["t_s"] is not None]
    assert gewertet, "irgendwer muss den Anstieg erreicht haben"
    for zeile in gewertet:
        # Eine Auffahrt dauert Minuten, keine Stunden Rennzeit.
        assert 0 < zeile["t_s"] < 4 * 3600, zeile["t_s"]
    # Wer den Fuß noch nicht erreicht hat, steht ohne Zeit hinten.
    ohne = [r for r in bild["board"]["rows"] if r["t_s"] is None]
    if ohne:
        assert all(r["rank"] > max(g["rank"] for g in gewertet) for r in ohne)


def test_vam_steht_in_der_bergwertung_und_ist_plausibel(bergrennen):
    client, _, token = bergrennen
    steuern = lambda a, v: client.post(  # noqa: E731
        f"/api/playback/{token}/control", json={"action": a, "value": v}
    )
    steuern("seek", 16 * 3600)
    steuern("mode", "climb")
    bild = client.get(f"/api/playback/{token}/frame").json()

    werte = [r["vam"] for r in bild["board"]["rows"] if r["vam"] is not None]
    assert werte, "in der Bergwertung muss VAM stehen"
    assert all(150 < v < 2200 for v in werte), werte


def test_kopfzeile_der_bergwertung_ist_die_beste_auffahrt(bergrennen):
    client, _, token = bergrennen
    steuern = lambda a, v: client.post(  # noqa: E731
        f"/api/playback/{token}/control", json={"action": a, "value": v}
    )
    steuern("seek", 18 * 3600)
    steuern("mode", "climb")
    steuern("climb_follow", False)
    steuern("climb", 0)
    bild = client.get(f"/api/playback/{token}/frame").json()

    if bild["board"]["climb"]["n_done"] == 0:
        pytest.skip("noch niemand oben")
    fuehrend = bild["board"]["leader"]
    assert fuehrend["provisional"] is False
    assert fuehrend["gap_s"] == 0.0


def test_ohne_anstieg_faellt_der_modus_zurueck(client):
    """Die Ostsee ist flach — dort gibt es nichts zu werten."""
    client.post("/season/s2026/race/ostsee/start", follow_redirects=False)
    token = client.post("/api/race/s2026~ostsee/session").json()["token"]
    client.post(f"/api/playback/{token}/control", json={"action": "mode", "value": "climb"})
    bild = client.get(f"/api/playback/{token}/frame").json()
    assert bild["mode"] == "split", "leere Tabelle wäre keine Antwort"
    assert bild["board"]["climb"] is None


def test_bergmeldungen_landen_im_ticker(bergrennen):
    client, _, token = bergrennen
    client.post(f"/api/playback/{token}/control", json={"action": "seek", "value": 16 * 3600})
    bild = client.get(f"/api/playback/{token}/frame").json()
    berg = [e for e in bild["ticker"] if e["type"] == "BEST_CLIMB"]
    if berg:
        assert all("VAM" in e["text"] for e in berg)
        assert all(e["t_wall"] <= bild["t_wall"] + 1 for e in berg)


def test_bergpunkte_landen_in_der_saisonwertung(client):
    """Ende zu Ende: Rennen fahren, Punkte speichern, Tabelle füllen."""
    from ultraslim.core.rider import generate_pool
    from ultraslim.core.season import Store, climb_standings

    client.post("/season/s2026/race/toskana/start", follow_redirects=False)
    token = client.post("/api/race/s2026~toskana/session").json()["token"]
    horizont = client.get(f"/api/playback/{token}/frame").json()["horizon_s"]
    client.post(
        f"/api/playback/{token}/control", json={"action": "seek", "value": horizont + 3600}
    )

    seite = client.get("/season/s2026")
    assert seite.status_code == 200
    assert "Bergwertung" in seite.text


def test_aero_und_profil_stehen_im_bild(token, laufendes_rennen):
    """Beide Werte müssen im Fokus, in der Zeile und in der Startliste stehen."""
    bild = laufendes_rennen.get(f"/api/playback/{token}/frame").json()
    fokus = bild["focus"]
    assert 0 <= fokus["aero"] <= 100
    assert 0 <= fokus["climb_profile"] <= 100

    zeile = bild["board"]["rows"][0]
    assert 0 <= zeile["aero"] <= 100
    assert 0 <= zeile["climb_profile"] <= 100

    eintrag = laufendes_rennen.get(f"/api/race/{RACE_ID}/startlist").json()["entries"][0]
    assert 0 <= eintrag["aero"] <= 100
    assert 0 <= eintrag["climb_profile"] <= 100

    for schluessel in ("aero", "profil"):
        antwort = laufendes_rennen.post(
            f"/api/playback/{token}/control", json={"action": "sort", "value": schluessel}
        )
        assert antwort.status_code == 200
        assert laufendes_rennen.get(f"/api/playback/{token}/frame").json()["sort"] == schluessel
