"""Der Fahrerpool: dreihundert Fahrer, fünfundzwanzig Teams, acht Nationen."""

from __future__ import annotations

import numpy as np
import pytest

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


def test_abfahrtswert_liegt_um_fuenfzig_und_streut_breit():
    """Die Glocke um fünfzig, aber breiter als die Normalverteilung.

    Die Beta-Verteilung ist von Haus aus auf null bis hundert begrenzt —
    anders als eine abgeschnittene Gaußkurve staut sich nichts an den
    Rändern, und trotzdem kommen die Extremwerte wirklich vor.
    """
    _, riders = generate_pool()
    werte = np.array([r.descent_skill for r in riders])
    assert werte.min() >= 0.0 and werte.max() <= 100.0
    assert werte.mean() == pytest.approx(50.0, abs=3.0)
    assert werte.std() > 19.0, "breiter als Gauß(50, 18) nach dem Abschneiden"
    assert werte.min() < 10.0 and werte.max() > 90.0
    # Kein Klumpen auf den Rändern: das war der Grund gegen das Abschneiden.
    assert np.count_nonzero(werte < 2.0) + np.count_nonzero(werte > 98.0) < 5
    # Und der normierte Wert ist genau der Hundertstel davon.
    assert riders[0].descent_norm == pytest.approx(riders[0].descent_skill / 100.0)


def test_ausdauerwert_ist_verteilt_wie_der_abfahrtswert():
    """Dieselbe Kurve, dieselbe Lesart — nur eine andere Wirkung."""
    _, riders = generate_pool()
    werte = np.array([r.endurance for r in riders])
    assert werte.min() >= 0.0 and werte.max() <= 100.0
    assert werte.mean() == pytest.approx(50.0, abs=3.0)
    assert werte.std() > 19.0
    assert werte.min() < 10.0 and werte.max() > 90.0

    # Fünfzig ist die Mitte: Dort ist die Abweichung null, und der
    # Verfall kostet nichts.
    mitte = [r for r in riders if abs(r.endurance - 50.0) < 0.5]
    for rider in mitte:
        assert abs(rider.endurance_dev) < 0.005
    assert riders[0].endurance_dev == pytest.approx(riders[0].endurance / 100.0 - 0.5)


def test_der_ausdauerwert_hat_das_feld_nicht_ausgetauscht():
    """Die neue Ziehung darf den Zufallsstrom nicht verschieben.

    Sie kommt nach allen anderen — sonst hätten dreihundert Fahrer neue
    Namen, Körpermaße und FTP-Werte bekommen, nur weil eine Eigenschaft
    dazugekommen ist.
    """
    _, riders = generate_pool()
    assert riders[0].name == "Oliver Kingsley"
    assert riders[0].ftp_w == pytest.approx(227.4, abs=0.1)
    assert riders[0].descent_skill == pytest.approx(69.4, abs=0.1)


def test_derselbe_seed_liefert_denselben_pool():
    _, a = generate_pool(seed=4711)
    _, b = generate_pool(seed=4711)
    _, c = generate_pool(seed=4712)
    assert [r.to_dict() for r in a] == [r.to_dict() for r in b]
    assert [r.name for r in a] != [r.name for r in c]


def test_aerowert_ist_verteilt_wie_die_anderen():
    _, riders = generate_pool()
    werte = np.array([r.aero for r in riders])
    assert werte.min() >= 0.0 and werte.max() <= 100.0
    assert werte.mean() == pytest.approx(50.0, abs=3.0)
    assert werte.std() > 19.0
    assert riders[0].aero_dev == pytest.approx(riders[0].aero / 100.0 - 0.5)


def test_rouleure_sind_die_schweren_kletterer_die_leichten():
    """Das Kletterprofil folgt dem Gewicht — aber nicht sklavisch."""
    _, riders = generate_pool()
    gewicht = np.array([r.weight_kg for r in riders])
    profil = np.array([r.climb_profile for r in riders])

    assert profil.min() >= 0.0 and profil.max() <= 100.0
    korrelation = float(np.corrcoef(gewicht, profil)[0, 1])
    assert korrelation < -0.7, "schwer heißt Rouleur"
    assert korrelation > -0.95, "aber es ist keine Formel aus der Waage"

    leicht = profil[gewicht < np.percentile(gewicht, 25)].mean()
    schwer = profil[gewicht > np.percentile(gewicht, 75)].mean()
    assert leicht > schwer + 30.0

    # Den leichten Rouleur muss es weiterhin geben.
    leichte_haelfte = profil[gewicht < np.median(gewicht)]
    assert (leichte_haelfte < 40.0).any(), "sonst wäre der Wert nur das Gewicht"


def test_startprofil_und_endspurt_sind_gezogen():
    _, riders = generate_pool()
    anlauf = np.array([r.start_profile for r in riders])
    spurt = np.array([r.finish_kick for r in riders])

    for werte in (anlauf, spurt):
        assert werte.min() >= 0.0 and werte.max() <= 100.0
        assert werte.mean() == pytest.approx(50.0, abs=3.5)
        assert werte.std() > 19.0

    # Das Startprofil ist um fünfzig zentriert, der Endspurt ist
    # einseitig — dort heißt null wirklich null.
    assert riders[0].start_profile_dev == pytest.approx(riders[0].start_profile / 100 - 0.5)
    assert riders[0].finish_kick_norm == pytest.approx(riders[0].finish_kick / 100)


def test_die_beiden_neuen_werte_haben_das_feld_nicht_ausgetauscht():
    """Wieder ganz am Ende gezogen — alles davor bleibt, wie es war."""
    _, riders = generate_pool()
    assert riders[0].name == "Oliver Kingsley"
    assert riders[0].ftp_w == pytest.approx(227.4, abs=0.1)
    assert riders[0].descent_skill == pytest.approx(69.4, abs=0.1)
    assert riders[0].endurance == pytest.approx(47.9, abs=0.1)
    assert riders[0].aero == pytest.approx(17.0, abs=0.1)
    assert riders[0].climb_profile == pytest.approx(76.3, abs=0.1)
