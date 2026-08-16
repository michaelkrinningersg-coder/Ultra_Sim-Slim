"""Der Streckengenerator: trifft er, was er treffen soll?"""

from __future__ import annotations

import numpy as np
import pytest

from ultraslim.core.route import ARCHETYPES, STEP_M, generate_route
from ultraslim.core.season import CALENDAR, build_route


def test_hoehenmeter_werden_getroffen():
    """Die Höhenmeter sind eine Vorgabe, kein Zufallsergebnis."""
    for spec in CALENDAR:
        route = build_route(spec)
        assert route.ascent_m == pytest.approx(spec.ascent_m, rel=0.01), spec.name


def test_distanz_und_raster_stimmen():
    route = generate_route("t", "Test", 300, "wellig", 3000, seed=1)
    assert route.distance_m == 300_000
    assert len(route.grade) == 3000
    assert len(route.ele_m) == 3001
    assert route.step_m == STEP_M


def test_profil_beginnt_und_endet_ungefaehr_auf_einer_hoehe():
    """Die Abfahrten tragen ab, was die Anstiege geholt haben.

    Ohne das driftet ein Tausend-Kilometer-Profil in den Weltraum oder
    unter den Meeresspiegel.
    """
    for spec in CALENDAR:
        route = build_route(spec)
        drift = abs(route.ascent_m - route.descent_m)
        assert drift < route.ascent_m * 0.05 + 100, spec.name


def test_keine_strecke_faellt_unter_normalnull():
    for spec in CALENDAR:
        assert build_route(spec).ele_m.min() >= -0.01, spec.name


def test_steigung_bleibt_im_rahmen_des_archetyps():
    for spec in CALENDAR:
        route = build_route(spec)
        deckel = ARCHETYPES[spec.archetype]["max_grade"]
        assert np.abs(route.grade).max() <= deckel + 1e-9, spec.name


def test_gebirge_ist_hoeher_als_flachland():
    flach = build_route(CALENDAR[0])
    hoch = build_route(CALENDAR[-1])
    assert hoch.max_elevation_m > flach.max_elevation_m + 1000
    assert len(hoch.climbs) > len(flach.climbs)


def test_gleicher_seed_gleiches_profil():
    """Die Strecke der zweiten Saison ist die der ersten."""
    a = build_route(CALENDAR[3])
    b = build_route(CALENDAR[3])
    assert np.array_equal(a.grade, b.grade)
    assert np.array_equal(a.ele_m, b.ele_m)


def test_zeitmessungen_sind_sortiert_und_enden_im_ziel():
    for spec in CALENDAR:
        route = build_route(spec)
        dists = [s.dist_m for s in route.splits]
        assert dists == sorted(dists), spec.name
        assert route.splits[-1].kind == "finish"
        assert route.splits[-1].dist_m == pytest.approx(route.distance_m)
        assert [s.idx for s in route.splits] == list(range(len(route.splits)))


def test_anstiege_liegen_innerhalb_der_strecke():
    route = build_route(CALENDAR[-1])
    assert route.climbs, "im Hochgebirge muss es Anstiege geben"
    for climb in route.climbs:
        assert 0 <= climb.dist_start_m < climb.dist_end_m <= route.distance_m
        assert climb.ascent_m > 0
        assert climb.avg_grade > 0


def test_json_ist_vollstaendig_fuer_den_zeichner():
    """Was der Browser braucht, muss auch drinstehen."""
    data = build_route(CALENDAR[1]).to_dict()
    assert data["profile"]["step_m"] == STEP_M
    assert len(data["profile"]["ele_m"]) == len(data["profile"]["grade"]) + 1
    assert {"dist_start_m", "dist_end_m", "category"} <= set(
        data["climbs"][0]
    ) if data["climbs"] else True
    assert {"idx", "name", "dist_m", "kind"} <= set(data["splits"][0])
