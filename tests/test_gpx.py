"""GPX einlesen, glätten, speichern.

Der wichtigste Test hier ist der gegen die **Wahrheit**: Aus einem
erzeugten Profil mit bekannten Höhenmetern wird eine GPX-Datei mit
realistischem Rauschen gebaut, wieder eingelesen — und die Höhenmeter
müssen zurückkommen.
"""

from __future__ import annotations

import numpy as np
import pytest

from ultraslim.core import gpx
from ultraslim.core.route import STEP_M, Route, generate_route
from ultraslim.core.season import Season, Store


def synth_gpx(route: Route, punktabstand_m: float = 10.0, rauschen_m: float = 2.0, seed: int = 1) -> bytes:
    """Eine GPX-Datei aus einem bekannten Profil, mit Höhenrauschen.

    Zehn Meter Punktabstand und ein bis drei Meter Rauschen sind das,
    was ein Fahrradcomputer oder ein Tourenportal liefert.
    """
    rng = np.random.default_rng(seed)
    n = int(route.distance_m / punktabstand_m)
    d = np.arange(n + 1) * punktabstand_m
    ele = np.interp(d, np.arange(len(route.ele_m)) * STEP_M, route.ele_m)
    ele = ele + rng.normal(0.0, rauschen_m, ele.size)
    lat = 47.0 + d / 111_320.0  # gerade nach Norden
    punkte = "".join(
        f'<trkpt lat="{la:.7f}" lon="11.0000000"><ele>{e:.1f}</ele></trkpt>'
        for la, e in zip(lat, ele)
    )
    return (
        '<?xml version="1.0"?><gpx version="1.1" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Testberg</name>'
        f"<trkseg>{punkte}</trkseg></trk></gpx>"
    ).encode("utf-8")


@pytest.fixture(scope="module")
def wahrheit() -> Route:
    return generate_route("t", "Testberg", 120, "mittelgebirge", 2400, seed=42)


# ----------------------------------------------------------------------
# Lesen
# ----------------------------------------------------------------------
def test_liest_spur_und_laenge(wahrheit):
    track = gpx.read_gpx(synth_gpx(wahrheit, rauschen_m=0.0))
    assert track.name == "Testberg"
    assert track.n_points > 10_000
    assert track.distance_m == pytest.approx(wahrheit.distance_m, rel=0.01)


def test_rohe_hoehenmeter_sind_grotesk_zu_hoch(wahrheit):
    """Der Grund, warum es die Glättung überhaupt gibt."""
    ohne = gpx.read_gpx(synth_gpx(wahrheit, rauschen_m=0.0)).raw_ascent_m
    mit = gpx.read_gpx(synth_gpx(wahrheit, rauschen_m=2.0)).raw_ascent_m
    assert ohne == pytest.approx(wahrheit.ascent_m, rel=0.02)
    assert mit > 4 * wahrheit.ascent_m, "zwei Meter Rauschen vervielfachen die Summe"


@pytest.mark.parametrize(
    "inhalt, stichwort",
    [
        (b"kein xml", "XML"),
        (b'<?xml version="1.0"?><gpx></gpx>', "Trackpunkte"),
        (
            b'<?xml version="1.0"?><gpx><trk><trkseg>'
            b'<trkpt lat="47.0" lon="11.0"/><trkpt lat="47.1" lon="11.0"/>'
            b"</trkseg></trk></gpx>",
            "Höhenangaben",
        ),
    ],
)
def test_unbrauchbare_dateien_sagen_warum(inhalt, stichwort):
    with pytest.raises(gpx.GpxError, match=stichwort):
        gpx.read_gpx(inhalt)


def test_zu_kurze_strecke_wird_abgelehnt():
    punkte = "".join(
        f'<trkpt lat="{47.0 + i * 0.00001:.7f}" lon="11.0"><ele>100</ele></trkpt>'
        for i in range(20)
    )
    with pytest.raises(gpx.GpxError, match="lang"):
        gpx.read_gpx(f'<?xml version="1.0"?><gpx><trk><trkseg>{punkte}</trkseg></trk></gpx>'.encode())


def test_fehlende_einzelhoehen_werden_ergaenzt():
    zeilen = []
    for i in range(400):
        lat = 47.0 + i * 0.0001
        hoehe = f"<ele>{100 + i}</ele>" if i % 3 else ""
        zeilen.append(f'<trkpt lat="{lat:.7f}" lon="11.0">{hoehe}</trkpt>')
    track = gpx.read_gpx(
        f'<?xml version="1.0"?><gpx><trk><trkseg>{"".join(zeilen)}</trkseg></trk></gpx>'.encode()
    )
    assert not np.any(np.isnan(track.ele_m))
    assert track.ele_m[-1] > track.ele_m[0]


def test_namensraeume_und_bom_stoeren_nicht(wahrheit):
    roh = synth_gpx(wahrheit, punktabstand_m=50.0, rauschen_m=0.0)
    assert gpx.read_gpx(b"\xef\xbb\xbf" + roh).n_points > 100


# ----------------------------------------------------------------------
# Glätten
# ----------------------------------------------------------------------
@pytest.mark.parametrize("rauschen", [0.0, 1.0, 2.0, 4.0])
def test_glaettung_holt_die_wahren_hoehenmeter_zurueck(wahrheit, rauschen):
    """Mit dem Standardfenster muss die Wahrheit herauskommen."""
    track = gpx.read_gpx(synth_gpx(wahrheit, rauschen_m=rauschen))
    route = gpx.build_route(track, "x", smooth_m=gpx.DEFAULT_SMOOTH_M)
    assert route.ascent_m == pytest.approx(wahrheit.ascent_m, rel=0.03)


def test_mehr_glaettung_heisst_weniger_hoehenmeter(wahrheit):
    track = gpx.read_gpx(synth_gpx(wahrheit, rauschen_m=2.0))
    werte = [gpx.build_route(track, "x", smooth_m=s).ascent_m for s in (0, 200, 400, 700, 1000)]
    assert werte == sorted(werte, reverse=True), "der Regler muss monoton wirken"
    # Und selbst starkes Glätten darf das Profil nicht einebnen.
    assert werte[-1] > 0.9 * wahrheit.ascent_m


def test_hoehenmeter_lassen_sich_erzwingen(wahrheit):
    track = gpx.read_gpx(synth_gpx(wahrheit, rauschen_m=2.0))
    route = gpx.build_route(track, "x", smooth_m=300, target_ascent_m=1800.0)
    assert route.ascent_m == pytest.approx(1800.0, rel=0.02)


def test_steigung_wird_gedeckelt():
    """Ein Sprung im Höhenmodell darf keine 200-Prozent-Rampe werden."""
    zeilen = []
    for i in range(600):
        lat = 47.0 + i * 0.0001  # rund 11 m Punktabstand
        hoehe = 100.0 + (300.0 if i == 300 else 0.0)  # ein Ausreißer
        zeilen.append(f'<trkpt lat="{lat:.7f}" lon="11.0"><ele>{hoehe}</ele></trkpt>')
    track = gpx.read_gpx(
        f'<?xml version="1.0"?><gpx><trk><trkseg>{"".join(zeilen)}</trkseg></trk></gpx>'.encode()
    )
    route = gpx.build_route(track, "x", smooth_m=0)
    assert np.abs(route.grade).max() <= gpx.MAX_IMPORT_GRADE + 1e-9


def test_profil_bleibt_ueber_normalnull(wahrheit):
    track = gpx.read_gpx(synth_gpx(wahrheit, rauschen_m=2.0))
    assert gpx.build_route(track, "x").ele_m.min() >= -0.01


def test_importierte_strecke_ist_eine_ganz_normale_strecke(wahrheit):
    """Sie muss alles können, was der Generator liefert."""
    track = gpx.read_gpx(synth_gpx(wahrheit, rauschen_m=2.0))
    route = gpx.build_route(track, "alpen-tour", "Alpen-Tour")

    assert route.id == "alpen-tour" and route.name == "Alpen-Tour"
    assert len(route.ele_m) == len(route.grade) + 1
    assert route.splits and route.splits[-1].kind == "finish"
    assert route.splits[-1].dist_m == pytest.approx(route.distance_m)
    assert [s.idx for s in route.splits] == list(range(len(route.splits)))
    assert route.climbs, "im Mittelgebirge müssen Anstiege gefunden werden"
    for climb in route.climbs:
        assert 0 <= climb.dist_start_m < climb.dist_end_m <= route.distance_m
        assert climb.ascent_m > 0
    assert route.archetype in ("flach", "wellig", "mittelgebirge", "hochgebirge")


def test_kennungen_taugen_als_dateiname():
    assert gpx.slugify("Alpen-Überquerung 2026") == "gpx-alpen-ueberquerung-2026"
    assert gpx.slugify("Große Straße / Höhenweg") == "gpx-grosse-strasse-hoehenweg"
    assert gpx.slugify("   ") == "gpx"
    assert "~" not in gpx.slugify("a~b")


# ----------------------------------------------------------------------
# Speichern
# ----------------------------------------------------------------------
def test_strecke_uebersteht_speichern_und_laden(tmp_path, wahrheit):
    store = Store(tmp_path)
    track = gpx.read_gpx(synth_gpx(wahrheit, rauschen_m=2.0))
    route = gpx.build_route(track, "meine-tour", "Meine Tour")

    assert store.has_route("meine-tour") is False
    store.save_route(route)
    assert store.has_route("meine-tour") is True

    wieder = store.load_route("meine-tour")
    assert wieder is not None
    assert wieder.id == route.id and wieder.name == route.name
    assert np.allclose(wieder.grade, route.grade, atol=1e-5)
    assert np.allclose(wieder.ele_m, route.ele_m, atol=0.1)
    assert wieder.ascent_m == pytest.approx(route.ascent_m, rel=1e-3)
    assert len(wieder.splits) == len(route.splits)
    assert len(wieder.climbs) == len(route.climbs)

    assert [r.id for r in store.list_routes()] == ["meine-tour"]
    store.delete_route("meine-tour")
    assert store.load_route("meine-tour") is None
    assert store.list_routes() == []


def test_gespeicherte_strecke_ist_gepackt_und_klein(tmp_path, wahrheit):
    store = Store(tmp_path)
    store.save_route(gpx.build_route(gpx.read_gpx(synth_gpx(wahrheit)), "gross"))
    datei = tmp_path / "routes" / "gross.json.gz"
    assert datei.exists()
    assert datei.stat().st_size < 60_000, "120 km dürfen keine 60 kB kosten"


def test_kaputte_streckendatei_wirft_nicht(tmp_path):
    store = Store(tmp_path)
    ordner = tmp_path / "routes"
    ordner.mkdir(parents=True)
    (ordner / "murks.json.gz").write_bytes(b"kein gzip")
    assert store.load_route("murks") is None
    assert store.list_routes() == []


def test_eigene_saison_uebersteht_speichern_und_laden(tmp_path, wahrheit):
    from ultraslim.core.season import RaceSpec, all_seasons, build_route as spec_route

    store = Store(tmp_path)
    route = gpx.build_route(gpx.read_gpx(synth_gpx(wahrheit)), "etappe-1", "Etappe 1")
    store.save_route(route)

    saison = Season(
        id="saison-alpenserie",
        year=2030,
        name="Alpenserie",
        races=(
            RaceSpec(0, "etappe-1", "Etappe 1", route.distance_km, route.archetype,
                     route.ascent_m, route_seed=None),
        ),
        custom=True,
        seed=777000,
    )
    store.save_season(saison)

    geladen = store.load_seasons()
    assert len(geladen) == 1
    wieder = geladen[0]
    assert wieder.id == "saison-alpenserie" and wieder.name == "Alpenserie"
    assert wieder.custom is True and wieder.seed == 777000
    assert len(wieder.races) == 1 and wieder.races[0].imported is True
    assert wieder.race_seed(wieder.races[0]) == 777000

    # Und sie taucht neben den mitgelieferten auf.
    assert [s.id for s in all_seasons(store)][-1] == "saison-alpenserie"
    # Die Strecke lässt sich über den Termin laden.
    assert spec_route(wieder.races[0], store).id == "etappe-1"

    store.delete_season("saison-alpenserie")
    assert store.load_seasons() == []
    assert store.has_route("etappe-1"), "die Strecke bleibt im Lager"


def test_fehlende_strecke_meldet_sich_deutlich(tmp_path):
    from ultraslim.core.season import RaceSpec, build_route as spec_route

    store = Store(tmp_path)
    spec = RaceSpec(0, "weg", "Weg", 100, "wellig", 1000, route_seed=None)
    with pytest.raises(LookupError, match="weg"):
        spec_route(spec, store)
