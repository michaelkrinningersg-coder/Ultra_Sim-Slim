"""Die Engine — vor allem die Zusage, dass nichts vorberechnet wird."""

from __future__ import annotations

import numpy as np
import pytest

from ultraslim.core.engine import (
    DT,
    STATE_WAITING,
    TICKS_PER_YIELD,
    LiveRace,
    RaceConfig,
    grade_power_factor,
    intensity_for_distance,
)
from ultraslim.core.rider import Rider, Team, generate_pool
from ultraslim.core.route import generate_route


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
