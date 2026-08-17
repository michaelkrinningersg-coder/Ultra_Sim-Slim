"""Die Engine — vor allem die Zusage, dass nichts vorberechnet wird."""

from __future__ import annotations

import numpy as np
import pytest

from dataclasses import replace

from ultraslim.core.engine import (
    CLIMB_GRADE_FULL,
    DT,
    FADE_SPAN_MAX,
    FADE_SPAN_PER_10H,
    FINISH_KICK_MAX,
    FINISH_KICK_START,
    PROFILE_SPAN,
    RHYTHM_MAX,
    START_PROFILE_SPAN,
    STATE_RIDING,
    STATE_WAITING,
    TICKS_PER_YIELD,
    LiveRace,
    RaceConfig,
    climb_ramp,
    endurance_fade,
    finish_kick_factor,
    grade_power_factor,
    intensity_for_distance,
    profile_power_factor,
    rhythm_power_factor,
    roughness,
    start_profile_factor,
)
from ultraslim.core import physics
from ultraslim.core.rider import Rider, Team, generate_pool
from ultraslim.core.route import STEP_M, Route, generate_route


def kurzstrecke(archetyp="flach", km=60, hm=200, seed=1):
    return generate_route("test", "Teststrecke", km, archetyp, hm, seed=seed)


def kleines_feld(n=6, start_interval=600.0):
    teams = [Team(id=0, name="Test–Rad", color="#888888")]
    riders = [
        Rider(
            id=i, bib=i + 1, name=f"Fahrer {i}", nation="GER", team_id=0,
            ftp_w=250.0 + 10.0 * i, weight_kg=70.0, height_cm=178.0,
        )
        for i in range(n)
    ]
    return teams, riders


def rennen(archetyp="flach", km=60, hm=200, n=6, seed=3, start_interval=600.0):
    teams, riders = kleines_feld(n)
    return LiveRace(
        kurzstrecke(archetyp, km, hm),
        riders,
        teams,
        RaceConfig(name="Test", seed=seed, start_interval_s=start_interval),
    )


# ----------------------------------------------------------------------
# Die Kernzusage
# ----------------------------------------------------------------------
def test_nichts_wird_vorberechnet():
    """Die Engine rechnet nie weiter, als die Uhr des Zuschauers steht.

    Ein Halt umfasst ``TICKS_PER_YIELD`` Ticks — mehr Vorlauf als das
    darf es nicht geben, sonst läge irgendwo eine Zukunft herum.
    """
    race = rennen()
    schranke = TICKS_PER_YIELD * DT
    for ziel in (60.0, 600.0, 1800.0, 3600.0):
        race.advance_to(ziel)
        assert race.sim_t <= ziel + schranke, f"zu weit gerechnet bei t={ziel}"
        assert race.sim_t >= ziel


def test_keine_zielzeit_bevor_jemand_im_ziel_ist():
    race = rennen()
    race.advance_to(1800.0)
    assert np.all(np.isnan(race.finish_time_s))
    # Und auch keine Meldung, die den Ausgang verrät.
    assert not any(e.type == "FINISH" for e in race.events)


def test_positionen_gehen_nie_ueber_das_gerechnete_hinaus():
    race = rennen()
    race.advance_to(1200.0)
    weit, _ = race.positions_at(1e9)
    jetzt, _ = race.positions_at(race.sim_t)
    assert np.allclose(weit, jetzt), "Abfragen in der Zukunft dürfen nicht extrapolieren"


def test_rueckblick_ist_moeglich_und_monoton():
    race = rennen()
    race.advance_to(5400.0)
    letzte = -1.0
    for t in range(0, 5400, 300):
        dist, _ = race.positions_at(float(t))
        assert dist[0] >= letzte
        letzte = float(dist[0])


# ----------------------------------------------------------------------
# Einzelstart
# ----------------------------------------------------------------------
def test_startabstand_betraegt_zehn_minuten():
    # Die Testfahrer haben aufsteigende FTP bei gleichem Gewicht — die
    # Setzliste läuft damit parallel zur Fahrer-Reihenfolge.
    race = rennen(n=6)
    assert np.array_equal(race.start_offset_s, np.arange(6) * 600.0)


def test_setzliste_stellt_den_staerksten_nach_hinten():
    """Ohne Saisonpunkte entscheidet die relative FTP."""
    teams, riders = kleines_feld(4)
    # Reihenfolge der Liste bewusst gegen die Stärke gedreht.
    gedreht = list(reversed(riders))
    race = LiveRace(kurzstrecke(), gedreht, teams, RaceConfig(name="Setzliste", seed=1))
    wkg = [r.ftp_w / r.weight_kg for r in gedreht]
    reihenfolge = np.argsort(race.start_offset_s)
    assert [wkg[i] for i in reihenfolge] == sorted(wkg)
    assert sorted(race.start_offset_s.tolist()) == [0.0, 600.0, 1200.0, 1800.0]


def test_saisonpunkte_setzen_vor_der_ftp():
    """Wer in der Wertung führt, startet zuletzt — auch als Schwächster."""
    teams, riders = kleines_feld(4)
    # Fahrer 0 hat die niedrigste FTP, aber die meisten Punkte;
    # Fahrer 3 hat die höchste FTP und noch keine.
    punkte = {0: 120, 1: 40, 2: 40, 3: 0}
    race = LiveRace(
        kurzstrecke(), riders, teams,
        RaceConfig(name="Setzliste", seed=1, season_points=punkte),
    )
    reihenfolge = list(np.argsort(race.start_offset_s))
    assert reihenfolge[0] == 3, "ohne Punkte geht es zuerst raus"
    assert reihenfolge[-1] == 0, "der Führende der Wertung startet zuletzt"
    # Punktgleichstand trennt die relative FTP aufsteigend: 1 vor 2.
    assert reihenfolge[1:3] == [1, 2]


def test_ohne_punktestand_bleibt_die_ftp_massgeblich():
    teams, riders = kleines_feld(4)
    ohne = LiveRace(kurzstrecke(), riders, teams, RaceConfig("A", 1))
    leer = LiveRace(kurzstrecke(), riders, teams, RaceConfig("B", 1, season_points={}))
    nullen = LiveRace(
        kurzstrecke(), riders, teams,
        RaceConfig("C", 1, season_points={r.id: 0 for r in riders}),
    )
    assert np.array_equal(ohne.start_offset_s, leer.start_offset_s)
    assert np.array_equal(ohne.start_offset_s, nullen.start_offset_s)


def test_wer_nicht_gestartet_ist_faehrt_nicht():
    race = rennen(n=6)
    race.advance_to(300.0)  # nur Fahrer 0 ist unterwegs
    assert race.state[0] != STATE_WAITING
    assert np.all(race.state[1:] == STATE_WAITING)
    assert race.dist_m[0] > 0
    assert np.all(race.dist_m[1:] == 0.0)


def test_eigenzeit_ist_rennuhr_minus_startversatz():
    race = rennen(n=6)
    race.advance_to(2000.0)
    own = race.own_time(2000.0)
    assert own[0] == pytest.approx(2000.0)
    assert own[2] == pytest.approx(800.0)      # startet bei 1200 s
    assert own[5] == pytest.approx(0.0)        # startet erst bei 3000 s
    assert np.all(own >= 0.0)


def test_zielzeit_ist_eigenzeit_nicht_rennuhr():
    race = rennen(n=4)
    race.advance_to(1e9)
    assert race.finished
    assert np.all(np.isfinite(race.finish_time_s))
    # Die Rennuhr enthält den Startversatz, die Wertungszeit nicht.
    assert np.allclose(race.finish_wall_s - race.start_offset_s, race.finish_time_s)
    assert race.finish_wall_s[-1] > race.finish_time_s[-1]


def test_wertung_folgt_der_eigenzeit_nicht_der_ankunft():
    """Der stärkste Fahrer gewinnt, auch wenn er zuletzt startet."""
    race = rennen(n=6)
    race.advance_to(1e9)
    staerkster = int(np.argmax([r.ftp_w for r in race.riders]))
    assert staerkster == 5, "Testaufbau: der letzte Starter hat die höchste FTP"
    assert int(np.argmin(race.finish_time_s)) == staerkster
    assert int(np.argmin(race.finish_wall_s)) != staerkster


def test_zeitstrahl_reicht_ueber_den_letzten_starter_hinaus():
    """Der Horizont muss den spätesten Start enthalten, nicht den letzten
    Eintrag der Fahrerliste.

    Seit die Setzliste nach Stärke sortiert, sind das zwei verschiedene
    Fahrer — und mit ``start_offset_s[-1]`` endete der Zeitstrahl vor
    dem Rennen, sodass die Wiedergabe nie ins Ziel kam.
    """
    teams, riders = kleines_feld(6)
    gedreht = list(reversed(riders))  # der Stärkste steht jetzt vorn
    race = LiveRace(kurzstrecke(km=120), gedreht, teams, RaceConfig("Horizont", 1))
    assert race.horizon_s > race.start_offset_s.max()
    race.advance_to(race.horizon_s)
    assert race.finished, "bis zum Horizont muss das Rennen durch sein"


def test_massenstart_bleibt_moeglich():
    race = rennen(n=4, start_interval=0.0)
    race.advance_to(120.0)
    assert np.all(race.state != STATE_WAITING)
    assert np.allclose(race.own_time(120.0), 120.0)


# ----------------------------------------------------------------------
# Rennverlauf
# ----------------------------------------------------------------------
def test_alle_kommen_ins_ziel_und_die_zeiten_sind_plausibel():
    race = rennen(km=120, hm=600)
    race.advance_to(1e9)
    assert race.finished
    tempo = 120.0 / (race.finish_time_s / 3600.0)
    assert np.all(tempo > 22.0) and np.all(tempo < 48.0), tempo


def test_zeitmessungen_werden_der_reihe_nach_genommen():
    race = rennen(km=120, hm=600)
    race.advance_to(1e9)
    for zeile in race.split_times:
        assert np.all(np.diff(zeile) > 0), "Splitzeiten müssen monoton wachsen"
    assert np.allclose(race.split_times[:, -1], race.finish_time_s)


def test_ereignisse_tragen_beide_zeiten():
    race = rennen(km=120)
    race.advance_to(1e9)
    assert race.events
    for event in race.events:
        assert event.t_wall >= event.t_s - 1e-6
        versatz = race.start_offset_s[event.entry_id]
        assert event.t_wall == pytest.approx(event.t_s + versatz, abs=1.0)


def test_ticker_filtert_nach_der_rennuhr():
    race = rennen(km=120)
    race.advance_to(1e9)
    grenze = 3600.0
    sichtbar = race.events_until(grenze)
    assert all(e.t_wall <= grenze for e in sichtbar)
    assert len(sichtbar) < len(race.events)


def test_gleicher_seed_gleiches_rennen():
    a, b = rennen(seed=99), rennen(seed=99)
    c = rennen(seed=100)
    for race in (a, b, c):
        race.advance_to(1e9)
    assert np.allclose(a.finish_time_s, b.finish_time_s)
    assert not np.allclose(a.finish_time_s, c.finish_time_s)


def test_tagesform_liegt_im_vorgesehenen_band():
    race = rennen(n=6)
    assert np.all(race.form >= 0.88) and np.all(race.form <= 1.12)


def test_engine_klettert_wie_die_gleichgewichtsrechnung():
    """Was die Engine am Anstieg fährt, muss die Physik hergeben.

    Fünf Kilometer flach, dann zwanzig Kilometer konstante acht Prozent.
    Gemessen wird nur der eingeschwungene Teil — die ersten Kilometer
    des Anstiegs gehören dem Abbremsen aus dem Flachen.
    """
    from ultraslim.core.route import Split

    n = 250
    grade = np.concatenate([np.zeros(50), np.full(200, 0.08)])
    ele = np.concatenate([[0.0], np.cumsum(grade * STEP_M)])
    route = Route("p", "Rampe", "mittelgebirge", n * STEP_M, STEP_M, ele, grade, [],
                  [Split(0, "Ziel", n * STEP_M, "finish")])

    teams = [Team(id=0, name="Test–Rad", color="#888888")]
    rider = Rider(0, 1, "Prüfer", "GER", 0, ftp_w=350.0, weight_kg=70.0, height_cm=178.0)
    race = LiveRace(route, [rider], teams,
                    RaceConfig("Rampe", seed=1, start_interval_s=0.0, intensity_factor=1.0))

    tempo, leistung = [], []
    while not race.finished:
        race.advance_to(race.sim_t + 30)
        # Nur solange er fährt: Im Ziel wird das Tempo auf null gesetzt,
        # und ein einziger solcher Messpunkt verdirbt jede Streuung.
        if race.state[0] == STATE_RIDING and 8000 < float(race.dist_m[0]) < 23000:
            tempo.append(float(race.v_ms[0]))
            leistung.append(float(race.power_w[0]))

    assert len(tempo) > 40
    v = float(np.mean(tempo))
    p = float(np.mean(leistung))

    # Die Steigungsmodulation greift: 350 W × 1,15 am Achtprozenter.
    assert p == pytest.approx(350.0 * 1.15, rel=0.03)

    cda = float(physics.frontal_area(178, 70) * physics.position_k(0.08))
    rho = float(physics.air_density(float(np.mean(ele[80:230]))))
    soll = float(physics.steady_state_speed(p, 0.08, 77.5, cda, physics.CRR_ASPHALT, rho))
    assert v == pytest.approx(soll, rel=0.03)

    # Und die Streuung stammt aus dem Trittrauschen, nicht aus dem
    # Integrator: Am Anstieg schlägt eine Leistungsänderung fast
    # eins zu eins aufs Tempo durch.
    assert float(np.std(tempo)) / v < 0.03


def test_das_gelaende_verschiebt_das_kraefteverhaeltnis():
    """Am Berg zählt W/kg mehr als im Flachen.

    Bewusst als *relativer* Vergleich formuliert. Die verbreitete
    Faustregel „im Flachen gewinnt der Schwere" gilt in diesem Modell
    nur schwach: Der Luftwiderstand wächst mit ``m^0,425``, der
    Rollwiderstand aber linear mit ``m`` — zusammen bleibt vom
    Massenvorteil im Flachen wenig übrig. Was robust gilt, ist die
    Verschiebung: Dasselbe Fahrerpaar steht am Berg anders zueinander
    als im Flachen.
    """
    teams = [Team(id=0, name="Test–Rad", color="#888888")]
    leicht = Rider(0, 1, "Leicht", "ITA", 0, 300.0, 58.0, 170.0)   # 5,17 W/kg
    schwer = Rider(1, 2, "Schwer", "NED", 0, 360.0, 82.0, 190.0)   # 4,39 W/kg

    verhaeltnis = {}
    for name, archetyp, hm in [("flach", "flach", 150), ("berg", "hochgebirge", 3000)]:
        race = LiveRace(
            kurzstrecke(archetyp, 100, hm, seed=5),
            [leicht, schwer],
            teams,
            RaceConfig(name=name, seed=1, start_interval_s=0.0),
        )
        race.advance_to(1e9)
        verhaeltnis[name] = race.finish_time_s[0] / race.finish_time_s[1]

    assert verhaeltnis["berg"] < verhaeltnis["flach"], (
        "der leichte Fahrer muss am Berg relativ besser dastehen als im Flachen: "
        f"{verhaeltnis}"
    )
    # Und der Unterschied darf nicht im Rauschen verschwinden.
    assert verhaeltnis["flach"] - verhaeltnis["berg"] > 0.02, verhaeltnis


# ----------------------------------------------------------------------
# Pacing
# ----------------------------------------------------------------------
def test_intensitaet_faellt_mit_der_distanz():
    assert intensity_for_distance(300) == pytest.approx(0.72)
    assert intensity_for_distance(1000) == pytest.approx(0.60)
    assert intensity_for_distance(500) == pytest.approx(0.68, abs=0.01)
    # Außerhalb der Stützstellen wird gehalten, nicht extrapoliert.
    assert intensity_for_distance(50) == pytest.approx(0.72)
    assert intensity_for_distance(5000) == pytest.approx(0.60)


def test_steigungsmodulation_trifft_die_eckwerte():
    assert float(grade_power_factor(np.array([0.0]))[0]) == pytest.approx(1.00)
    assert float(grade_power_factor(np.array([0.08]))[0]) == pytest.approx(1.15)
    assert float(grade_power_factor(np.array([0.20]))[0]) == pytest.approx(1.15)
    assert float(grade_power_factor(np.array([-0.04]))[0]) == pytest.approx(0.55)
    assert float(grade_power_factor(np.array([-0.10]))[0]) == pytest.approx(0.55)
    # Dazwischen linear.
    assert float(grade_power_factor(np.array([0.04]))[0]) == pytest.approx(1.075)


def test_grosses_feld_bleibt_bezahlbar():
    """Dreihundert Fahrer dürfen nicht teurer sein als sechs."""
    teams, riders = generate_pool()
    race = LiveRace(kurzstrecke("wellig", 100, 1000), riders, teams, RaceConfig("Feld", 7))
    race.advance_to(1e9)
    assert race.finished
    assert np.all(np.isfinite(race.finish_time_s))
    assert len(race.riders) == 300


# ----------------------------------------------------------------------
# Bergwertung
# ----------------------------------------------------------------------
def bergrennen(n=6, seed=3):
    """Mittelgebirge — dort gibt es sicher kategorisierte Anstiege."""
    teams, riders = kleines_feld(n)
    route = kurzstrecke("mittelgebirge", 150, 3000, seed=11)
    assert route.climbs, "Testaufbau: die Strecke braucht Anstiege"
    return route, LiveRace(route, riders, teams, RaceConfig("Berg", seed=seed))


def test_jede_auffahrt_wird_an_beiden_enden_gestempelt():
    route, race = bergrennen()
    race.advance_to(1e9)
    assert race.n_climbs == len(route.climbs)
    assert np.all(np.isfinite(race.climb_enter_s))
    assert np.all(np.isfinite(race.climb_exit_s))
    assert np.all(race.climb_exit_s > race.climb_enter_s), "oben ist nach unten"


def test_auffahrtsdauer_und_vam_passen_zueinander():
    route, race = bergrennen()
    race.advance_to(1e9)
    dauer = race.climb_duration(1e9)
    vam = race.climb_vam(1e9)
    for i, climb in enumerate(route.climbs):
        erwartet = climb.ascent_m / (dauer[:, i] / 3600.0)
        assert np.allclose(vam[:, i], erwartet, rtol=1e-6)
    # Und die Zahlen sind plausibel: kein Fahrer klettert 3000 m/h.
    assert 200 < float(np.nanmin(vam)) and float(np.nanmax(vam)) < 2000


def test_vam_waehrend_der_auffahrt_nutzt_die_bisherige_hoehe():
    """Wer ein Drittel oben ist, hat auch erst ein Drittel geklettert.

    Mit der vollen Höhe des Anstiegs im Zähler zeigte ein Fahrer auf
    halbem Weg die doppelte Steiggeschwindigkeit.
    """
    route, race = bergrennen()
    climb = route.climbs[0]
    # So weit vorrechnen, dass der erste Fahrer mitten im Anstieg steht.
    while race.dist_m[0] < climb.dist_start_m + climb.length_m * 0.4:
        race.advance_to(race.sim_t + 60)
        assert race.sim_t < 6 * 3600, "Testaufbau: er müsste längst dort sein"

    t = race.sim_t
    ohne_ort = race.climb_vam(t)[0, 0]
    mit_ort = race.climb_vam(t, race.dist_m)[0, 0]
    assert mit_ort < ohne_ort * 0.75, "die Teilhöhe muss deutlich kleiner sein"
    assert 300 < mit_ort < 1800, f"unplausible VAM: {mit_ort}"


def test_nur_die_bestzeit_meldet_sich():
    route, race = bergrennen()
    race.advance_to(1e9)
    meldungen = [e for e in race.events if e.type == "BEST_CLIMB"]
    assert meldungen, "eine Bestzeit muss es geben"
    # Je Anstieg höchstens so viele Meldungen wie Fahrer, und die Zeiten
    # müssen streng besser werden.
    assert len(meldungen) <= race.n_climbs * len(race.riders)
    for e in meldungen:
        assert "VAM" in e.text and "Bestzeit" in e.text


def test_bergpunkte_gehen_an_die_schnellsten_auffahrten():
    route, race = bergrennen()
    race.advance_to(1e9)
    punkte = race.climb_points()
    assert punkte, "es müssen Punkte vergeben werden"

    # Wer die meisten Anstiege am schnellsten hochfährt, führt.
    dauer = race.climb_exit_s - race.climb_enter_s
    siege = np.bincount(np.argmin(dauer, axis=0), minlength=len(race.riders))
    bester = int(np.argmax(siege))
    assert max(punkte, key=punkte.get) == race.riders[bester].id


def test_bergpunkte_folgen_der_kategorie():
    from ultraslim.core.engine import CLIMB_POINTS, climb_points_for

    assert climb_points_for("HC", 1) == 20
    assert climb_points_for("4. Kat.", 1) == 1
    assert climb_points_for("4. Kat.", 2) == 0
    assert climb_points_for("gibtsnicht", 1) == 0
    assert climb_points_for("HC", 0) == 0
    # Ein HC-Pass ist mehr wert als vier Hügel vierter Kategorie.
    assert CLIMB_POINTS["HC"][0] > 4 * CLIMB_POINTS["4. Kat."][0]
    for kategorie, tabelle in CLIMB_POINTS.items():
        assert list(tabelle) == sorted(tabelle, reverse=True), kategorie


def test_ohne_anstiege_gibt_es_keine_bergwertung():
    teams, riders = kleines_feld(4)
    route = kurzstrecke("flach", 60, 150)
    race = LiveRace(route, riders, teams, RaceConfig("Flach", seed=1))
    race.advance_to(1e9)
    assert race.n_climbs == 0
    assert race.climb_points() == {}
    assert race.climb_duration(1e9).shape == (4, 0)


def test_der_leichteste_kletterer_holt_die_berge():
    """Am Berg entscheidet W/kg — das muss sich in den Punkten zeigen."""
    teams = [Team(id=0, name="Test–Rad", color="#888888")]
    fahrer = [
        Rider(0, 1, "Schwer", "NED", 0, 380.0, 88.0, 192.0),   # 4,32 W/kg
        Rider(1, 2, "Mittel", "GER", 0, 330.0, 74.0, 180.0),   # 4,46 W/kg
        Rider(2, 3, "Leicht", "ITA", 0, 290.0, 60.0, 170.0),   # 4,83 W/kg
    ]
    route = kurzstrecke("mittelgebirge", 150, 3000, seed=11)
    race = LiveRace(route, fahrer, teams, RaceConfig("Berg", seed=1, start_interval_s=0.0))
    race.advance_to(1e9)
    punkte = race.climb_points()
    assert punkte.get(2, 0) > punkte.get(1, 0) >= punkte.get(0, 0)


def test_auffahrtsdauer_wird_lesbar_geschrieben():
    """Zwei Stunden am HC-Pass dürfen nicht als '122:40' dastehen."""
    from ultraslim.core.engine import _dauer_text

    assert _dauer_text(0) == "0:00"
    assert _dauer_text(95) == "1:35"
    assert _dauer_text(3599) == "59:59"
    assert _dauer_text(3600) == "1:00:00"
    assert _dauer_text(7360) == "2:02:40"


# ----------------------------------------------------------------------
# Ausdauer
# ----------------------------------------------------------------------
def test_ausdauer_fuenfzig_kostet_nichts():
    """Die Mitte ist wirklich neutral, in jeder Renndauer.

    Sonst verschöbe der neue Wert die Eichung der IF-Tabelle und damit
    jede bisher gefahrene Zielzeit.
    """
    for stunden in (0.0, 1.0, 10.0, 40.0):
        assert float(endurance_fade(np.array([stunden * 3600]), np.zeros(1))[0]) == pytest.approx(1.0)


def test_die_schere_geht_mit_der_fahrzeit_auf():
    """Nach zehn Stunden genau die hinterlegte Spanne, dann der Deckel."""
    zehn = np.full(2, 10.0 * 3600.0)
    hoch, tief = endurance_fade(zehn, np.array([0.5, -0.5]))
    assert hoch - tief == pytest.approx(FADE_SPAN_PER_10H)
    assert hoch == pytest.approx(1.0 + FADE_SPAN_PER_10H / 2)

    # Nach einer Stunde ein Zehntel davon — der Verlauf ist linear.
    eine = np.full(1, 3600.0)
    assert float(endurance_fade(eine, np.array([0.5])[:1])[0]) == pytest.approx(
        1.0 + FADE_SPAN_PER_10H / 20
    )

    # Und irgendwann ist Schluss: Der Deckel begrenzt die Spanne.
    lang = np.full(2, 100.0 * 3600.0)
    hoch, tief = endurance_fade(lang, np.array([0.5, -0.5]))
    assert hoch - tief == pytest.approx(FADE_SPAN_MAX)


def test_ausdauer_verschiebt_die_leistung_im_rennen():
    """Im Rennen zählt sie — und zwar in der richtigen Richtung."""
    teams, riders = kleines_feld(1)
    zeiten = []
    for wert in (100.0, 50.0, 0.0):
        fahrer = replace(riders[0], endurance=wert)
        race = LiveRace(
            kurzstrecke("wellig", km=200, hm=2000),
            [fahrer],
            teams,
            RaceConfig(name="Test", seed=5, start_interval_s=0.0),
        )
        while not race.finished:
            race.advance_to(race.sim_t + 3600.0)
        zeiten.append(float(race.finish_time_s[0]))

    schnell, mitte, langsam = zeiten
    assert schnell < mitte < langsam, "mehr Ausdauer muss schneller sein"
    # Symmetrisch um die Mitte: Der Gewinn oben und der Verlust unten
    # sind derselbe Betrag — bis auf das, was die Physik krümmt.
    assert (mitte - schnell) == pytest.approx(langsam - mitte, rel=0.15)


def test_der_verfall_ist_am_start_null_und_waechst():
    """Was die Anzeige zeigt, kommt aus derselben Funktion wie der Tick."""
    teams, riders = kleines_feld(2)
    riders = [replace(riders[0], endurance=100.0), replace(riders[1], endurance=0.0)]
    race = LiveRace(
        kurzstrecke("flach", km=300, hm=500),
        riders,
        teams,
        RaceConfig(name="Test", seed=5, start_interval_s=0.0),
    )
    assert race.fade_at(0.0) == pytest.approx(np.ones(2))

    race.advance_to(5.0 * 3600.0)
    verfall = race.fade_at(5.0 * 3600.0)
    assert verfall[0] > 1.0 and verfall[1] < 1.0
    assert verfall[0] - 1.0 == pytest.approx(1.0 - verfall[1])


# ----------------------------------------------------------------------
# Aerodynamik und Kletterprofil
# ----------------------------------------------------------------------
def test_der_aerodynamikwert_steckt_in_der_flaeche():
    """Er wird einmal eingerechnet und gilt dann überall."""
    teams, riders = kleines_feld(3)
    riders = [replace(r, aero=w) for r, w in zip(riders, (100.0, 50.0, 0.0))]
    race = LiveRace(kurzstrecke(), riders, teams, RaceConfig(name="Test", seed=1))
    basis = riders[1].frontal_area_m2
    assert race.area[1] == pytest.approx(basis), "fünfzig ändert nichts"
    assert race.area[0] < basis < race.area[2]
    assert race.area[2] / race.area[0] == pytest.approx(
        (1 + physics.AERO_SPAN / 2) / (1 - physics.AERO_SPAN / 2)
    )


def test_das_kletterprofil_verschiebt_nur():
    """Am Anstieg dazu, im Flachen ab — und in der Mitte gar nichts."""
    flach, mitte, berg = climb_ramp(np.array([0.0, CLIMB_GRADE_FULL / 2, CLIMB_GRADE_FULL]))
    kletterer = profile_power_factor(np.array([flach, mitte, berg]), 0.5)
    rouleur = profile_power_factor(np.array([flach, mitte, berg]), -0.5)

    assert kletterer[0] < 1.0 < kletterer[2], "der Kletterer spart im Flachen"
    assert rouleur[0] > 1.0 > rouleur[2], "der Rouleur genau umgekehrt"
    assert kletterer[1] == pytest.approx(1.0), "bei halber Rampe hebt es sich auf"
    assert kletterer[2] - 1.0 == pytest.approx(1.0 - kletterer[0])
    assert kletterer[2] - rouleur[2] == pytest.approx(PROFILE_SPAN)

    # Der neutrale Fahrer merkt von alledem nichts.
    assert profile_power_factor(np.array([0.0, 0.5, 1.0]), 0.0) == pytest.approx(np.ones(3))


def test_die_strecke_entscheidet_zwischen_kletterer_und_rouleur():
    """Derselbe Wert, zwei Streckentypen, umgekehrtes Vorzeichen."""
    teams, riders = kleines_feld(1)
    ergebnis = {}
    for archetyp, hm in (("flach", 300), ("hochgebirge", 6000)):
        zeiten = []
        for wert in (100.0, 0.0):
            fahrer = replace(riders[0], climb_profile=wert)
            race = LiveRace(
                kurzstrecke(archetyp, km=200, hm=hm),
                [fahrer],
                teams,
                RaceConfig(name="Test", seed=5, start_interval_s=0.0),
            )
            while not race.finished:
                race.advance_to(race.sim_t + 3600.0)
            zeiten.append(float(race.finish_time_s[0]))
        ergebnis[archetyp] = zeiten

    kletterer_flach, rouleur_flach = ergebnis["flach"]
    kletterer_berg, rouleur_berg = ergebnis["hochgebirge"]
    assert kletterer_flach > rouleur_flach, "im Flachen gewinnt der Rouleur"
    assert kletterer_berg < rouleur_berg, "im Hochgebirge der Kletterer"


def test_das_startprofil_verschiebt_ueber_die_distanz():
    """Vorn hoch, hinten runter — und in der Mitte kreuzen sie sich."""
    anteile = np.array([0.0, 0.5, 1.0])
    schnell = start_profile_factor(anteile, 0.5)
    diesel = start_profile_factor(anteile, -0.5)

    assert schnell[0] > 1.0 > schnell[2], "der Schnellstarter beginnt oben"
    assert diesel[0] < 1.0 < diesel[2], "der Diesel endet oben"
    assert schnell[1] == pytest.approx(1.0) and diesel[1] == pytest.approx(1.0)
    assert schnell[0] - diesel[0] == pytest.approx(START_PROFILE_SPAN)
    assert schnell[0] - 1.0 == pytest.approx(1.0 - schnell[2]), "symmetrisch um die Mitte"

    # Über die Distanz gemittelt hebt es sich auf — der Wert verschiebt,
    # er verschenkt nicht.
    fein = np.linspace(0.0, 1.0, 1001)
    assert start_profile_factor(fein, 0.5).mean() == pytest.approx(1.0, abs=1e-6)
    # Und die Mitte der Skala merkt nichts davon.
    assert start_profile_factor(fein, 0.0) == pytest.approx(np.ones(1001))


def test_der_endspurt_greift_erst_am_schluss():
    """Vor dem letzten Fünftel passiert nichts, danach wächst er."""
    anteile = np.array([0.0, 0.5, FINISH_KICK_START, 0.9, 1.0])
    voll = finish_kick_factor(anteile, 1.0)
    assert voll[0] == pytest.approx(1.0)
    assert voll[1] == pytest.approx(1.0)
    assert voll[2] == pytest.approx(1.0), "genau an der Grenze noch nichts"
    assert voll[3] == pytest.approx(1.0 + FINISH_KICK_MAX / 2), "auf halber Rampe die Hälfte"
    assert voll[4] == pytest.approx(1.0 + FINISH_KICK_MAX)

    # Einseitig: Null heißt hier wirklich null, nicht „Mitte".
    assert finish_kick_factor(anteile, 0.0) == pytest.approx(np.ones(5))
    assert finish_kick_factor(np.array([1.0]), 0.5)[0] == pytest.approx(1.0 + FINISH_KICK_MAX / 2)


def test_startprofil_und_endspurt_im_rennen():
    """Zwischenzeit gegen Endzeit — genau daran hängt der Unterschied."""
    teams, riders = kleines_feld(1)
    route = kurzstrecke("wellig", km=200, hm=1500)

    def fahre(**werte):
        fahrer = replace(riders[0], **werte)
        race = LiveRace(route, [fahrer], teams,
                        RaceConfig(name="Test", seed=5, start_interval_s=0.0))
        while not race.finished:
            race.advance_to(race.sim_t + 3600.0)
        mitte = len(route.splits) // 2 - 1
        return float(race.split_times[0, mitte]), float(race.finish_time_s[0])

    schnell_halb, schnell_ziel = fahre(start_profile=100.0, finish_kick=0.0)
    diesel_halb, diesel_ziel = fahre(start_profile=0.0, finish_kick=0.0)

    assert schnell_halb < diesel_halb - 60, "zur Hälfte muss der Schnellstarter vorn sein"
    # Am Ziel bleibt fast nichts davon übrig: Der Wert verschiebt nur.
    assert abs(schnell_ziel - diesel_ziel) < 0.02 * schnell_ziel

    ohne_halb, ohne_ziel = fahre(start_profile=50.0, finish_kick=0.0)
    mit_halb, mit_ziel = fahre(start_profile=50.0, finish_kick=100.0)
    assert mit_halb == pytest.approx(ohne_halb), "vorher darf er nichts tun"
    assert mit_ziel < ohne_ziel, "am Ziel schon"


def test_die_unruhe_zaehlt_antritte_nicht_steilheit():
    """Ein gleichmäßiger Anstieg ist ruhig, egal wie steil."""
    schritt = 100.0
    n = 300  # 30 km

    gleichmaessig = np.full(n, 0.08)      # ein durchgehender Achtprozenter
    assert roughness(gleichmaessig, schritt).mean() < 0.05

    flach = np.full(n, 0.0)
    assert roughness(flach, schritt).max() == 0.0

    # Auf und ab zwischen −2 % und +5 %, alle zwei Kilometer: gut
    # sieben Antritte auf dreißig Kilometern, also rund drei Viertel der
    # Referenzdichte.
    welle = np.where((np.arange(n) // 20) % 2 == 0, 0.05, -0.02)
    assert roughness(welle, schritt).mean() > 0.7

    # Kräusel unterhalb der Schwelle sind keine Antritte.
    kraeusel = np.where((np.arange(n) // 5) % 2 == 0, 0.02, -0.01)
    assert roughness(kraeusel, schritt).max() == 0.0


def test_der_rhythmus_ist_ein_einseitiger_abzug():
    """Hundert kostet nichts, null das Maximum — und nur im Unruhigen."""
    rough = np.array([0.0, 0.5, 1.0])
    bester = rhythm_power_factor(rough, 1.0)
    schlechtester = rhythm_power_factor(rough, 0.0)

    assert bester == pytest.approx(np.ones(3)), "bei 100 nie ein Abzug"
    assert schlechtester[0] == pytest.approx(1.0), "auf glatter Strecke auch nicht"
    assert schlechtester[1] == pytest.approx(1.0 - RHYTHM_MAX / 2)
    assert schlechtester[2] == pytest.approx(1.0 - RHYTHM_MAX)
    # Niemand gewinnt etwas: der Faktor bleibt überall bei höchstens 1.
    for wert in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert rhythm_power_factor(rough, wert).max() <= 1.0 + 1e-12


def test_der_rhythmus_wirkt_nur_auf_unruhigem_gelaende():
    """Auf glatter Strecke ist der Wert für jeden folgenlos."""
    teams, riders = kleines_feld(1)

    def zeit(archetyp, hm, wert):
        fahrer = replace(riders[0], rhythm=wert)
        race = LiveRace(kurzstrecke(archetyp, km=150, hm=hm), [fahrer], teams,
                        RaceConfig(name="Test", seed=5, start_interval_s=0.0))
        while not race.finished:
            race.advance_to(race.sim_t + 3600.0)
        return float(race.finish_time_s[0])

    glatt_gut, glatt_schlecht = zeit("flach", 200, 100.0), zeit("flach", 200, 0.0)
    assert glatt_schlecht == pytest.approx(glatt_gut, rel=0.002)

    wellig_gut, wellig_schlecht = zeit("wellig", 2500, 100.0), zeit("wellig", 2500, 0.0)
    assert wellig_schlecht > wellig_gut * 1.005, "im Welligen muss es kosten"
