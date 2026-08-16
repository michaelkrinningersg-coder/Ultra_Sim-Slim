"""Das Physikmodell gegen Werte prüfen, die man nachschlagen kann.

Ein Test, der nur bestätigt, was der Code gerade tut, merkt nicht, wenn
der Code falsch ist. Diese hier prüfen gegen Größen aus der Literatur
und gegen Rechnungen, die man von Hand nachvollziehen kann.
"""

from __future__ import annotations

import numpy as np
import pytest

from ultraslim.core import physics


def test_frontalflaeche_liegt_im_erwarteten_bereich():
    # 180 cm / 75 kg ist der Referenzfahrer aus der Kalibrierung.
    area = float(physics.frontal_area(180.0, 75.0))
    assert 0.26 == pytest.approx(area, abs=0.01)

    # Sie wächst mit beidem, aber deutlich schwächer als linear: Ein
    # doppelt so schwerer Fahrer hat keine doppelte Stirnfläche.
    doppelt = float(physics.frontal_area(180.0, 150.0))
    assert 1.25 < doppelt / area < 1.45


def test_cda_im_unterlenker_und_am_anstieg():
    area = physics.frontal_area(180.0, 75.0)
    flach = float(area * physics.position_k(0.0))
    berg = float(area * physics.position_k(0.10))
    # Richtwerte aus dem Windkanal: Unterlenker rund 0,30–0,33,
    # aufrecht am Anstieg rund 0,37–0,40.
    assert 0.30 < flach < 0.34
    assert 0.36 < berg < 0.40
    # Der Übergang ist gleitend, nicht sprunghaft.
    assert flach < float(area * physics.position_k(0.03)) < berg


def test_rollwiderstand_steigt_mit_dem_tempo():
    assert float(physics.rolling_crr(0.0)) == pytest.approx(physics.CRR_ASPHALT)
    bei_36 = float(physics.rolling_crr(10.0))
    assert bei_36 > physics.CRR_ASPHALT
    # Rund ein Achtel Aufschlag bei 36 km/h.
    assert 1.10 < bei_36 / physics.CRR_ASPHALT < 1.16


def test_luftdichte_faellt_mit_der_hoehe():
    assert float(physics.air_density(0.0)) == pytest.approx(1.225, abs=0.01)
    # Auf 2000 m rund 20 % weniger als auf Meereshöhe.
    verhaeltnis = float(physics.air_density(2000.0)) / float(physics.air_density(0.0))
    assert 0.78 < verhaeltnis < 0.85


@pytest.mark.parametrize(
    "grade, erwartet_kmh, toleranz",
    [
        (0.00, 38.3, 1.0),   # flach: 280 W, CdA 0,318
        (0.08, 13.8, 0.8),   # 8 % Steigung: schwerkraftdominiert
    ],
)
def test_gleichgewichtstempo_referenzfahrer(grade, erwartet_kmh, toleranz):
    """280 W, 75 kg, 180 cm — die Zahlen aus der Modellbeschreibung."""
    area = physics.frontal_area(180.0, 75.0)
    v = physics.steady_state_speed(
        power_w=280.0,
        grade=grade,
        mass=75.0 + physics.BIKE_MASS_KG,
        cda=area * physics.position_k(grade),
        crr=physics.CRR_ASPHALT,
        rho=1.225,
    )
    assert float(v) * 3.6 == pytest.approx(erwartet_kmh, abs=toleranz)


def test_vam_am_achtprozenter_ist_plausibel():
    """Aus dem Tempo am Anstieg folgt eine nachprüfbare Steiggeschwindigkeit."""
    area = physics.frontal_area(180.0, 75.0)
    v = float(
        physics.steady_state_speed(
            280.0, 0.08, 75.0 + physics.BIKE_MASS_KG, area * physics.position_k(0.08)
        )
    )
    vam = v * 0.08 * 3600.0  # Höhenmeter je Stunde
    assert 1000 < vam < 1250


def test_integration_naehert_sich_dem_gleichgewicht():
    """Der Euler-Schritt muss dorthin laufen, wo die Bisektion steht."""
    area = float(physics.frontal_area(180.0, 75.0))
    mass = 75.0 + physics.BIKE_MASS_KG
    grade = 0.02
    cda = area * float(physics.position_k(grade))
    ziel = float(physics.steady_state_speed(280.0, grade, mass, cda))

    v = np.array([4.0])
    for _ in range(1200):
        v = physics.integrate_step(
            v,
            np.array([280.0]),
            np.array([grade]),
            np.array([mass]),
            np.array([cda]),
            physics.rolling_crr(v) * 0.0 + physics.CRR_ASPHALT,
            np.array([1.225]),
            dt=1.0,
        )
    assert float(v[0]) == pytest.approx(ziel, rel=0.02)


def test_abfahrt_laeuft_die_leistung_aus():
    """Bei 65 km/h im größten Gang kommt nichts mehr an."""
    assert float(physics.downhill_power_taper(5.0)) == pytest.approx(1.0)
    assert 0.0 < float(physics.downhill_power_taper(15.0)) < 1.0
    assert float(physics.downhill_power_taper(20.0)) == pytest.approx(0.0)


def test_steigungsgeometrie():
    cos, sin = physics.slope_trig(np.array([0.0, 0.10]))
    assert cos[0] == pytest.approx(1.0)
    assert sin[0] == pytest.approx(0.0)
    # tan α = 0,10  ->  sin α ≈ 0,0995
    assert sin[1] == pytest.approx(0.0995, abs=1e-3)
    assert (cos**2 + sin**2) == pytest.approx(np.ones(2))
