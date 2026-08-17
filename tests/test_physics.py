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


def _klettertempo(wkg: float, kg: float, grade: float, groesse: float = 178.0) -> float:
    """Gleichgewichtstempo am Anstieg, in m/s."""
    cda = physics.frontal_area(groesse, kg) * physics.position_k(grade)
    return float(
        physics.steady_state_speed(
            wkg * kg, grade, kg + physics.BIKE_MASS_KG, cda, physics.CRR_ASPHALT, 1.225
        )
    )


def _vam(wkg: float, kg: float, grade: float, groesse: float = 178.0) -> float:
    """Höhenmeter je Stunde."""
    return _klettertempo(wkg, kg, grade, groesse) * grade * 3600.0


@pytest.mark.parametrize("grade", [0.06, 0.08, 0.10])
@pytest.mark.parametrize("wkg", [3.5, 4.0, 4.5, 5.0, 5.5, 6.0])
def test_vam_trifft_die_gebraeuchliche_naeherung(grade, wkg):
    """Watt je Kilogramm gegen die Steiggeschwindigkeit.

    Die im Radsport gebräuchliche Näherung lautet

        W/kg = VAM / (200 + 10 · Steigung in Prozent)

    Sie ist eine lineare Anpassung an Messwerte von Rennfahrern an
    Anstiegen zwischen sechs und elf Prozent. Das Modell darf davon
    abweichen — es *muss* sogar: Die Näherung ist linear in W/kg, die
    Physik ist es nicht, weil der Luftwiderstand mit ``v³`` wächst. Was
    hier geprüft wird, ist die Größenordnung.
    """
    naeherung = wkg * (200.0 + 10.0 * grade * 100.0)
    assert _vam(wkg, 70.0, grade) == pytest.approx(naeherung, rel=0.09)


def test_die_abweichung_von_der_naeherung_hat_das_richtige_vorzeichen():
    """Unten darüber, oben darunter — und genau das gehört so.

    Die lineare Näherung ist an starken Fahrern kalibriert. Zum
    schwachen Ende hin unterschätzt sie das Tempo, zum starken hin
    überschätzt sie es, weil sie den mit ``v³`` wachsenden
    Luftwiderstand nicht kennt. Ein Modell, das diese Krümmung *nicht*
    zeigte, hätte den Luftwiderstand am Berg vergessen.
    """
    def abweichung(wkg: float) -> float:
        return _vam(wkg, 70.0, 0.08) / (wkg * 280.0) - 1.0

    assert abweichung(3.0) > 0.0
    assert abweichung(6.5) < 0.0
    assert abweichung(3.0) > abweichung(4.5) > abweichung(6.5)


def test_am_berg_entscheidet_watt_je_kilogramm():
    """Gleiche relative Leistung, gleiches Bergtempo — fast.

    Über 52 bis 88 Kilogramm dürfen bei identischen W/kg keine großen
    Unterschiede stehen. Der Rest ist der Rahmen: Ein 7,5-kg-Rad sind
    beim leichten Fahrer vierzehn Prozent Zusatzmasse, beim schweren
    achteinhalb — deshalb klettert der Schwere minimal schneller, nicht
    langsamer.
    """
    tempi = [
        _vam(5.0, kg, 0.08, groesse)
        for kg, groesse in [(52, 163), (58, 168), (65, 174), (72, 180), (80, 186), (88, 192)]
    ]
    assert max(tempi) / min(tempi) - 1.0 < 0.08, "W/kg muss das Bergtempo bestimmen"
    assert tempi == sorted(tempi), "der Radrahmen wiegt für den Leichten relativ mehr"


def test_am_berg_traegt_die_masse_anders_als_im_flachen():
    """Dieselbe absolute Leistung, doppelte Frage.

    Im Flachen zählt Watt gegen Luftwiderstand, am Berg Watt gegen
    Gewicht. Ein schwerer Fahrer mit denselben Watt ist deshalb im
    Flachen kaum langsamer und am Berg deutlich.
    """
    leicht_flach = float(
        physics.steady_state_speed(
            300.0, 0.0, 60 + physics.BIKE_MASS_KG,
            physics.frontal_area(170, 60) * physics.position_k(0.0),
        )
    )
    schwer_flach = float(
        physics.steady_state_speed(
            300.0, 0.0, 85 + physics.BIKE_MASS_KG,
            physics.frontal_area(190, 85) * physics.position_k(0.0),
        )
    )
    leicht_berg = _klettertempo(300.0 / 60, 60, 0.08, 170)
    schwer_berg = _klettertempo(300.0 / 85, 85, 0.08, 190)

    assert schwer_flach / leicht_flach > 0.90, "im Flachen kostet Masse wenig"
    assert schwer_berg / leicht_berg < 0.80, "am Berg kostet Masse viel"


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


def test_die_bremse_greift_erst_im_gefaelle():
    """Bergauf und im Flachen wird nicht gebremst, unten voll."""
    rampe = physics.brake_ramp(np.array([0.05, 0.0, -physics.DESCENT_BRAKE_LO,
                                         -0.04, -physics.DESCENT_BRAKE_HI, -0.15]))
    assert rampe[0] == 0.0 and rampe[1] == 0.0 and rampe[2] == 0.0
    assert 0.0 < rampe[3] < 1.0, "dazwischen läuft sie linear hoch"
    assert rampe[4] == pytest.approx(1.0)
    assert rampe[5] == pytest.approx(1.0), "steiler wird nicht mehr stärker gebremst"


def test_der_abfahrtswert_staffelt_die_drosselung():
    """Hundert fährt ungebremst, null nimmt die volle Drosselung mit."""
    voll = np.ones(3)
    faktor = physics.descent_speed_factor(voll, np.array([1.0, 0.5, 0.0]))
    assert faktor[0] == pytest.approx(1.0)
    assert faktor[1] == pytest.approx(1.0 - physics.DESCENT_THROTTLE_MAX / 2)
    assert faktor[2] == pytest.approx(1.0 - physics.DESCENT_THROTTLE_MAX)

    # Gebremst wird über den Widerstand: Wer fünfzehn Prozent langsamer
    # rollen soll, braucht den Luftwiderstand von 1/f².
    luft = physics.brake_drag_factor(np.ones(2), np.array([1.0, 0.0]))
    assert luft[0] == pytest.approx(1.0), "ohne Drosselung kein Zuschlag"
    assert luft[1] == pytest.approx(1.0 / (1.0 - physics.DESCENT_THROTTLE_MAX) ** 2)

    # Und ohne Gefälle ist auch der schlechteste Abfahrer unbehelligt.
    assert physics.brake_drag_factor(np.zeros(1), np.zeros(1))[0] == pytest.approx(1.0)


def test_die_gedrosselte_abfahrt_ist_wirklich_langsamer():
    """Die Drosselung ist auf das Tempo geeicht, nicht auf den Widerstand."""
    grade = np.array([-0.08])
    gemessen = []
    for skill in (1.0, 0.0):
        v = np.array([12.0])
        cda = np.array([0.30]) * physics.brake_drag_factor(
            physics.brake_ramp(grade), np.array([skill])
        )
        for _ in range(4000):
            v = physics.integrate_step(
                v, np.zeros(1), grade, np.array([78.0]), cda,
                physics.rolling_crr(v), np.array([1.2]), 1.0,
                *physics.slope_trig(grade),
            )
        gemessen.append(float(v[0]))
    schnell, langsam = gemessen
    assert langsam == pytest.approx(schnell * (1.0 - physics.DESCENT_THROTTLE_MAX), rel=0.02)


def test_steigungsgeometrie():
    cos, sin = physics.slope_trig(np.array([0.0, 0.10]))
    assert cos[0] == pytest.approx(1.0)
    assert sin[0] == pytest.approx(0.0)
    # tan α = 0,10  ->  sin α ≈ 0,0995
    assert sin[1] == pytest.approx(0.0995, abs=1e-3)
    assert (cos**2 + sin**2) == pytest.approx(np.ones(2))


def test_der_aerodynamikwert_staffelt_den_luftwiderstand():
    """Ein hoher Wert heißt kleinere Fläche, fünfzig heißt gar nichts."""
    faktor = physics.aero_cda_factor(np.array([0.5, 0.0, -0.5]))
    assert faktor[0] == pytest.approx(1.0 - physics.AERO_SPAN / 2)
    assert faktor[1] == pytest.approx(1.0), "die Mitte kostet nichts"
    assert faktor[2] == pytest.approx(1.0 + physics.AERO_SPAN / 2)
    assert faktor[0] - faktor[2] == pytest.approx(-physics.AERO_SPAN)


def test_die_aerodynamik_wirkt_im_flachen_am_staerksten():
    """Der Luftwiderstand ist dort der Hauptgegner, wo es flach ist."""
    def tempo(cda, grade, leistung):
        v = np.array([8.0])
        for _ in range(9000):
            v = physics.integrate_step(
                v, np.array([leistung]), np.array([grade]), np.array([78.0]),
                np.array([cda]), physics.rolling_crr(v), np.array([1.2]), 1.0,
                *physics.slope_trig(np.array([grade])),
            )
        return float(v[0])

    gewinn = {}
    for grade in (0.0, 0.06):
        schnell = tempo(0.30 * physics.aero_cda_factor(0.5), grade, 200.0)
        langsam = tempo(0.30 * physics.aero_cda_factor(-0.5), grade, 200.0)
        gewinn[grade] = schnell / langsam - 1.0

    assert gewinn[0.0] > 0.0 and gewinn[0.06] > 0.0
    assert gewinn[0.0] > 3.0 * gewinn[0.06], "am Berg darf kaum etwas übrig bleiben"
