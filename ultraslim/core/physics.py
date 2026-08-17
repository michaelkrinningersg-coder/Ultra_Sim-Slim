"""Physikmodell der schlanken Fassung.

Aus drei Fahrereigenschaften — FTP, Gewicht, Größe — und einem
Höhenprofil wird eine Geschwindigkeit. Mehr steht hier nicht, und das
ist Absicht.

Die Kräftebilanz je Zeitschritt::

    a = (P · η / v  −  Crr·m·g·cosα  −  m·g·sinα  −  ½·ρ·CdA·v²) / m

Alle Funktionen arbeiten vektorisiert über das ganze Feld: Die Eingaben
sind Arrays der Länge ``n_riders``. Die Schleifenlänge ist die Zahl der
Ticks, nicht die Zahl der Fahrer — dreihundert kosten kaum mehr als
vierzig.
"""

from __future__ import annotations

import numpy as np

#: Erdbeschleunigung.
G = 9.80665
#: Antriebsstrangverluste. Kette, Ritzel, Lager.
DRIVETRAIN_EFFICIENCY = 0.975
#: Spezifische Gaskonstante trockener Luft.
R_SPEC = 287.058

#: Rollwiderstandsbeiwert auf gutem Asphalt.
#:
#: BicycleRollingResistance misst 25–28-mm-Racing-Clincher mit rund
#: 8–10 W bei 28,8 km/h und 42,5 kg Last. Aus P = Crr·m·g·v folgt daraus
#: Crr ≈ 0,0030 — allerdings auf einer glatten Stahltrommel. Echter
#: Asphalt hat eine Textur, die der Trommel fehlt; der übliche Zuschlag
#: bringt den Wert auf rund 0,0040. Das ist die Zahl, mit der hier
#: gerechnet wird.
CRR_ASPHALT = 0.0040

#: Der Beiwert steigt mit dem Tempo: Die Walkarbeit im Reifen wächst,
#: weil dieselbe Verformung öfter je Sekunde durchlaufen wird. Grob
#: 0,0005 je 10 m/s, also bei 36 km/h rund ein Achtel Aufschlag.
CRR_SPEED_PER_MS = 0.00005

#: Gewicht des Straßenrennrads samt Flaschen und Licht. Alle Fahrer
#: starten mit demselben Rad — es gibt in dieser Fassung keine Radwahl.
BIKE_MASS_KG = 7.5

#: Positionsfaktoren auf die Frontalfläche: CdA = k · A_frontal.
#:
#: Mit A ≈ 0,265 m² (180 cm / 75 kg) ergibt k = 1,20 einen CdA von
#: 0,318 — der übliche Wert für einen Fahrer im Unterlenker. k = 1,45
#: ergibt 0,384, also die aufrechte Haltung am Anstieg.
K_DROPS = 1.20
K_CLIMBING = 1.45

#: Zwischen diesen Steigungen wechselt die Haltung gleitend. Ein harter
#: Umschaltpunkt ließe den CdA an jeder Segmentgrenze springen.
POSITION_BLEND_LO = 0.01
POSITION_BLEND_HI = 0.06

#: Bevorzugte Trittfrequenz und die Grenze, ab der nur noch leergedreht
#: wird. Dazwischen läuft die Leistung bergab aus.
CADENCE_PREFERRED = 87.0
CADENCE_MAX = 114.0
#: Entfaltung im größten Gang, in Metern je Kurbelumdrehung. 50×11 mit
#: 700×28 sind 9,55 m — bei 114 rpm gut 65 km/h, und dort ist Schluss
#: mit Mittreten.
DEV_MAX_M = 9.55

# ----------------------------------------------------------------------
# Bremsen in der Abfahrt
# ----------------------------------------------------------------------
#: Wie stark ein Fahrer mit Abfahrtswert 0 gegenüber einem mit 100
#: gebremst wird — **die Stellschraube dieses Modells.**
#:
#: Fünfzehn Prozent sind an der Enge des Feldes kalibriert. Auf der
#: Alpenstrecke (1000 km, 356 km Gefälle) kosten sie den schlechtesten
#: Abfahrer 52 Minuten gegenüber dem besten; dort liegt Rang 2 bei
#: +30 und Rang 5 bei +60 Minuten. Der Wert entscheidet damit Duelle und
#: kostet rund vier Plätze, dreht aber keine Hierarchie um.
#:
#: Zum Vergleich, falls hier jemand dreht: Bei 30 % verliert ein Fahrer
#: mit 5,6 W/kg und Abfahrtswert 0 gegen einen mit 5,0 W/kg und 100 —
#: dann wöge Abfahren schwerer als Klettern.
DESCENT_THROTTLE_MAX = 0.15

#: Zwischen diesen Gefällen blendet die Bremse ein. Bei zwei Prozent
#: bremst niemand — dort tritt der Fahrer noch mit drei Vierteln seiner
#: Zielleistung. Ab sechs Prozent rollt er ohnehin nur noch.
DESCENT_BRAKE_LO = 0.02
DESCENT_BRAKE_HI = 0.06

#: Spanne des Aerodynamikwerts auf den Luftwiderstand: der Unterschied
#: zwischen Wert 100 und Wert 0, symmetrisch um 50.
#:
#: Zehn Prozent heißt für einen Fahrer mit CdA 0,280 eine Spanne von
#: 0,266 bis 0,294 — Straßenräder im Unterlenker liegen real zwischen
#: etwa 0,26 und 0,32, der Wert bleibt also innerhalb dessen, was
#: zwischen einem Fahrer, der vierzig Stunden sauber liegt, und einem,
#: der sich ständig aufrichtet, tatsächlich vorkommt.
#:
#: Was er kostet, gemessen zwischen 100 und 0: 17 Minuten auf der
#: flachen Ostsee-Nachtfahrt, 40 auf dem Alpenmarathon. Absolut wächst
#: das mit der Renndauer, relativ fällt es mit den Höhenmetern — der
#: Wert greift dort am schärfsten, wo sonst nichts differenziert.
AERO_SPAN = 0.10

#: Globaler Sicherheitsdeckel gegen Ausreißer in der Abfahrt.
MAX_SPEED = 23.6  # 85 km/h
#: Untergrenze für die Antriebsrechnung — P/v ist bei v → 0 singulär.
MIN_SPEED = 1.5
#: Beschleunigungsdeckel. Ohne ihn schießt ein 20-%-Segment die
#: Geschwindigkeit in einem einzigen Tick ins Negative.
ACCEL_LIMIT = 4.0


def frontal_area(height_cm: np.ndarray | float, weight_kg: np.ndarray | float) -> np.ndarray:
    """Frontalfläche aus Körpergröße und Gewicht.

    ``A = 0,0276 · h[m]^0,725 · m[kg]^0,425`` — die Du-Bois-Form, die
    auch der Regression von Bassett et al. (1999) zugrunde liegt. Für
    180 cm und 75 kg ergibt das 0,265 m².
    """
    h_m = np.asarray(height_cm, dtype=np.float64) / 100.0
    m = np.asarray(weight_kg, dtype=np.float64)
    return 0.0276 * h_m**0.725 * m**0.425


def aero_cda_factor(aero_dev: np.ndarray | float) -> np.ndarray:
    """Faktor auf den Luftwiderstand aus dem Aerodynamikwert.

    ``aero_dev`` ist die Abweichung von der Mitte, −0,5 bis +0,5. Ein
    hoher Wert heißt **kleinere** Fläche — daher das Minus. Bei null
    kommt exakt 1,0 heraus.
    """
    return 1.0 - AERO_SPAN * np.asarray(aero_dev, dtype=np.float64)


def position_k(grade: np.ndarray | float) -> np.ndarray:
    """Haltungsfaktor als weiche Funktion der Steigung.

    Im Flachen und bergab wird aerodynamisch gefahren, am Anstieg
    aufrecht — dort ist bei 14 km/h ohnehin nichts zu gewinnen.
    """
    g = np.asarray(grade, dtype=np.float64)
    blend = np.clip((g - POSITION_BLEND_LO) / (POSITION_BLEND_HI - POSITION_BLEND_LO), 0.0, 1.0)
    return K_DROPS + blend * (K_CLIMBING - K_DROPS)


def air_density(elevation_m: np.ndarray | float, temperature_c: float = 15.0) -> np.ndarray:
    """Luftdichte aus Höhe und Temperatur, barometrische Höhenformel.

    Auf 2000 m fährt man bei gleicher Leistung im Flachen messbar
    schneller — das ist der einzige Wettereinfluss, den diese Fassung
    kennt.
    """
    ele = np.asarray(elevation_m, dtype=np.float64)
    pressure = 101325.0 * np.power(np.maximum(1.0 - 2.25577e-5 * ele, 1e-6), 5.25588)
    return pressure / (R_SPEC * (temperature_c + 273.15))


def rolling_crr(v: np.ndarray | float) -> np.ndarray:
    """Rollwiderstandsbeiwert bei der gefahrenen Geschwindigkeit."""
    return CRR_ASPHALT + CRR_SPEED_PER_MS * np.maximum(np.asarray(v, dtype=np.float64), 0.0)


def slope_trig(grade: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
    """(cos, sin) des Steigungswinkels ohne Umweg über ``arctan``.

    Mit ``grade = tan α`` gilt ``cos α = 1/√(1+grade²)`` und
    ``sin α = grade · cos α``. Beides hängt an der Strecke, nicht am
    Fahrer — es lässt sich damit einmal je Rasterpunkt vorrechnen.
    """
    g = np.asarray(grade, dtype=np.float64)
    cos = 1.0 / np.sqrt(1.0 + g * g)
    return cos, g * cos


def brake_ramp(grade: np.ndarray | float) -> np.ndarray:
    """Wie stark die Bremse bei dieser Steigung überhaupt greift.

    Null im Flachen und am Anstieg, eins ab sechs Prozent Gefälle,
    dazwischen linear. Hängt nur an der Strecke — die Engine rechnet sie
    einmal je Rasterpunkt vor.
    """
    g = np.asarray(grade, dtype=np.float64)
    return np.clip((-g - DESCENT_BRAKE_LO) / (DESCENT_BRAKE_HI - DESCENT_BRAKE_LO), 0.0, 1.0)


def descent_speed_factor(
    ramp: np.ndarray | float, skill_norm: np.ndarray | float
) -> np.ndarray:
    """Anteil der freien Endgeschwindigkeit, den ein Fahrer zulässt.

    ``skill_norm`` ist der Abfahrtswert auf 0 bis 1. Bei 1 bleibt alles,
    wie es ohne Bremse wäre; bei 0 greift ``DESCENT_THROTTLE_MAX``,
    soweit die Steilheit es hergibt.
    """
    return 1.0 - DESCENT_THROTTLE_MAX * (1.0 - np.asarray(skill_norm, dtype=np.float64)) * ramp


def brake_drag_factor(
    ramp: np.ndarray | float, skill_norm: np.ndarray | float
) -> np.ndarray:
    """Faktor auf den Luftwiderstand, der genau diese Drosselung erzeugt.

    **Warum über den Widerstand und nicht über die Watt:** Ab acht
    Prozent Gefälle tritt der Fahrer im größten Gang leer, die
    Antriebsleistung ist dort bereits null. Man kann nichts wegnehmen,
    was nicht da ist — Bremsen heißt Energie *vernichten*, nicht Antrieb
    reduzieren.

    Der Zusammenhang ist exakt: Im Gleichgewicht hält der Luftwiderstand
    die Hangabtriebskraft, also ``½·ρ·CdA·v² = const``. Wer auf den
    Anteil ``f`` der Endgeschwindigkeit will, braucht deshalb den
    ``1/f²``-fachen Widerstand.

    Dass daraus rechnerisch ein größerer CdA wird, ist Buchführung und
    keine Behauptung über die Sitzposition: Physikalisch sind es
    Bremsbeläge. Der Vorteil dieser Form ist, dass sie als *Kraft* in
    die Bilanz fällt — der Integrator bremst damit weich in die Kurve
    hinein und beschleunigt danach von selbst wieder, statt an einer
    harten Kante abzuschneiden.
    """
    f = descent_speed_factor(ramp, skill_norm)
    return 1.0 / (f * f)


def downhill_power_taper(v: np.ndarray | float) -> np.ndarray:
    """Anteil der Zielleistung, der bei hohem Tempo noch ankommt.

    Ohne diese Begrenzung drückt der Fahrer bei 70 km/h weiter 200 W in
    die Kurbel. Der Grund ist die Trittfrequenz: Im größten Gang ist
    irgendwann Schluss.
    """
    rpm = 60.0 * np.asarray(v, dtype=np.float64) / DEV_MAX_M
    return np.clip((CADENCE_MAX - rpm) / (CADENCE_MAX - CADENCE_PREFERRED), 0.0, 1.0)


def integrate_step(
    v: np.ndarray,
    power_w: np.ndarray,
    grade: np.ndarray,
    mass: np.ndarray,
    cda: np.ndarray,
    crr: np.ndarray,
    rho: np.ndarray,
    dt: float,
    cos_slope: np.ndarray | None = None,
    sin_slope: np.ndarray | None = None,
) -> np.ndarray:
    """Ein Euler-Schritt: neue Geschwindigkeit aus der Leistungsbilanz.

    Euler statt Newton-Raphson auf die kubische Gleichung: robuster,
    kein Löser nötig, und die Trägheit ist gratis mit dabei — Antritte
    und Anstiegsübergänge werden dadurch von selbst plausibel.
    """
    if cos_slope is None or sin_slope is None:
        cos_slope, sin_slope = slope_trig(grade)

    v_eff = np.maximum(v, MIN_SPEED)
    f_prop = power_w * DRIVETRAIN_EFFICIENCY / v_eff
    f_resist = crr * mass * G * cos_slope + mass * G * sin_slope + 0.5 * rho * cda * v * np.abs(v)

    a = np.clip((f_prop - f_resist) / mass, -ACCEL_LIMIT, ACCEL_LIMIT)
    return np.clip(v + a * dt, 0.5, MAX_SPEED)


def steady_state_speed(
    power_w: np.ndarray | float,
    grade: np.ndarray | float,
    mass: np.ndarray | float,
    cda: np.ndarray | float,
    crr: np.ndarray | float = CRR_ASPHALT,
    rho: np.ndarray | float = 1.225,
    iterations: int = 48,
) -> np.ndarray:
    """Gleichgewichtsgeschwindigkeit per Bisektion.

    Wird nicht im Tick benutzt, sondern für Abschätzungen: Renndauer,
    Zeithorizont der Wiedergabe und Tests. Bisektion statt Newton, weil
    sie garantiert konvergiert.
    """
    power = np.asarray(power_w, dtype=np.float64)
    cos_slope, sin_slope = slope_trig(grade)
    lo = np.full(np.shape(power) or (1,), 0.05, dtype=np.float64)
    hi = np.full(np.shape(power) or (1,), MAX_SPEED * 1.5, dtype=np.float64)
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        resist = (
            np.asarray(crr) * np.asarray(mass) * G * cos_slope
            + np.asarray(mass) * G * sin_slope
            + 0.5 * np.asarray(rho) * np.asarray(cda) * mid * mid
        )
        need = resist * mid / DRIVETRAIN_EFFICIENCY
        too_slow = need < power
        lo = np.where(too_slow, mid, lo)
        hi = np.where(too_slow, hi, mid)
    out = 0.5 * (lo + hi)
    return out if np.shape(power) else float(out[0])
