"""Der Fahrerpool: dreihundert Fahrer, fünfundzwanzig Teams, acht Nationen."""

from __future__ import annotations

import numpy as np

from ultraslim.core.names import NATIONS, TEAM_NAMES
from ultraslim.core.rider import (
    FIELD_SIZE,
    HEIGHT_RANGE,
    N_TEAMS,
    RIDERS_PER_TEAM,
    WEIGHT_RANGE,
    WKG_RANGE,
    generate_pool,
)


def test_feldgroesse_und_teamgroesse():
    teams, riders = generate_pool()
    assert len(riders) == FIELD_SIZE == 300
    assert len(teams) == N_TEAMS == 25
    for team in teams:
        assert sum(1 for r in riders if r.team_id == team.id) == RIDERS_PER_TEAM == 12


def test_acht_nationen_und_alle_kommen_vor():
    _, riders = generate_pool()
    assert len(NATIONS) == 8
    vorhanden = {r.nation for r in riders}
    assert vorhanden == set(NATIONS)


def test_teamnamen_sind_ausruester_und_radmarke():
    teams, _ = generate_pool()
    assert [t.name for t in teams] == list(TEAM_NAMES)
    for team in teams:
        assert "–" in team.name, f"{team.name} ist kein Ausrüster–Radmarke-Paar"
    assert len({t.color for t in teams}) == len(teams), "Teamfarben müssen unterscheidbar sein"


def test_startnummern_sind_luecken_und_dublettenfrei():
    _, riders = generate_pool()
    assert sorted(r.bib for r in riders) == list(range(1, FIELD_SIZE + 1))
    assert len({r.id for r in riders}) == FIELD_SIZE


def test_namen_sind_eindeutig():
    _, riders = generate_pool()
    assert len({r.name for r in riders}) == FIELD_SIZE


def test_koerpermasse_bleiben_in_den_vorgegebenen_grenzen():
    _, riders = generate_pool()
    h = np.array([r.height_cm for r in riders])
    w = np.array([r.weight_kg for r in riders])
    wkg = np.array([r.w_per_kg for r in riders])
    assert HEIGHT_RANGE[0] <= h.min() and h.max() <= HEIGHT_RANGE[1]
    assert WEIGHT_RANGE[0] <= w.min() and w.max() <= WEIGHT_RANGE[1]
    assert WKG_RANGE[0] - 1e-9 <= wkg.min() and wkg.max() <= WKG_RANGE[1] + 1e-9


def test_koerperbau_ist_plausibel_gekoppelt():
    """Kein 190-cm-Fahrer mit 58 kg — das Gewicht folgt dem BMI."""
    _, riders = generate_pool()
    bmi = np.array([r.weight_kg / (r.height_cm / 100) ** 2 for r in riders])
    assert 17.5 < bmi.min() and bmi.max() < 26.0


def test_ftp_folgt_aus_gewicht_und_relativer_leistung():
    _, riders = generate_pool()
    for rider in riders[:50]:
        assert rider.ftp_w == rider.w_per_kg * rider.weight_kg
    ftp = np.array([r.ftp_w for r in riders])
    assert 180 < ftp.min() and ftp.max() < 470


def test_teams_sind_unterschiedlich_stark():
    """Ohne Team-Offset wäre die Teamwertung eine Zufallszahl."""
    teams, riders = generate_pool()
    mittel = [
        float(np.mean([r.w_per_kg for r in riders if r.team_id == t.id])) for t in teams
    ]
    assert max(mittel) - min(mittel) > 0.35


def test_systemmasse_und_frontalflaeche_sind_abgeleitet():
    _, riders = generate_pool()
    rider = riders[0]
    assert rider.system_mass_kg == rider.weight_kg + 7.5
    assert 0.20 < rider.frontal_area_m2 < 0.32


def test_derselbe_seed_liefert_denselben_pool():
    _, a = generate_pool(seed=4711)
    _, b = generate_pool(seed=4711)
    _, c = generate_pool(seed=4712)
    assert [r.to_dict() for r in a] == [r.to_dict() for r in b]
    assert [r.name for r in a] != [r.name for r in c]
