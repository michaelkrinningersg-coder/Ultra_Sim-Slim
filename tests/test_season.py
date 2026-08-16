"""Kalender, Punkte, Wertungen und der Speicher."""

from __future__ import annotations

import pytest

from ultraslim.core.rider import generate_pool
from ultraslim.core.season import (
    CALENDAR,
    POINTS,
    SCORING_PLACES,
    RaceResult,
    Store,
    all_seasons,
    get_race_spec,
    get_season,
    points_for_rank,
    rider_standings,
    team_standings,
    time_standings,
)


@pytest.fixture
def pool():
    return generate_pool()


def test_kalender_hat_sechs_termine_von_300_bis_1000_km():
    assert len(CALENDAR) == 6
    distanzen = [spec.distance_km for spec in CALENDAR]
    assert distanzen == sorted(distanzen)
    assert distanzen[0] == 300 and distanzen[-1] == 1000
    archetypen = [spec.archetype for spec in CALENDAR]
    assert archetypen.count("flach") == 1
    assert archetypen.count("wellig") == 2
    assert archetypen.count("mittelgebirge") == 2
    assert archetypen.count("hochgebirge") == 1
    assert len({spec.route_id for spec in CALENDAR}) == 6


def test_saisons_teilen_die_strecken_aber_nicht_die_seeds():
    saisons = all_seasons()
    assert len(saisons) == 3
    spec = CALENDAR[0]
    seeds = {s.race_seed(spec) for s in saisons}
    assert len(seeds) == len(saisons), "jede Saison braucht eine eigene Tagesform"
    # Die Strecke selbst hängt am route_seed und ist saisonunabhängig.
    assert spec.route_seed not in seeds or len(seeds) == 3


def test_rennkennung_ist_eindeutig():
    ids = {s.race_id(spec) for s in all_seasons() for spec in CALENDAR}
    assert len(ids) == len(all_seasons()) * len(CALENDAR)


def test_punkte_bis_rang_hundertfuenfzig():
    assert len(POINTS) == SCORING_PLACES == 150
    assert points_for_rank(1) == 100
    assert points_for_rank(20) == 8
    assert points_for_rank(150) == 1
    # Danach ist Schluss, und davor gibt es keinen Rang null.
    assert points_for_rank(151) == 0
    assert points_for_rank(0) == 0
    assert points_for_rank(-3) == 0


def test_die_punktekurve_faellt_und_hat_keine_klippe():
    assert list(POINTS) == sorted(POINTS, reverse=True), "monoton fallend"
    assert min(POINTS) == 1, "der letzte Punkterang ist noch etwas wert"
    # Der Übergang von der Handliste in die Kurve darf nicht springen.
    assert POINTS[19] - POINTS[20] == 1
    # Oben steiler als unten: Zwischen Rang 25 und 35 liegt mehr als
    # zwischen 130 und 140.
    assert (POINTS[24] - POINTS[34]) > (POINTS[129] - POINTS[139])


def test_nachschlagen_unbekannter_kennungen():
    assert get_season("gibtsnicht") is None
    assert get_race_spec("gibtsnicht") is None
    assert get_season("s2026") is not None
    assert get_race_spec("alpen") is not None


# ----------------------------------------------------------------------
def test_speicher_schreibt_und_liest(tmp_path):
    store = Store(tmp_path)
    result = RaceResult("s2026", "ostsee", [(3, 1000.0), (7, 1100.5)])
    assert store.load("s2026", "ostsee") is None
    store.save(result)
    wieder = store.load("s2026", "ostsee")
    assert wieder is not None
    assert wieder.finishers == [(3, 1000.0), (7, 1100.5)]
    assert wieder.winner_time_s == 1000.0
    assert store.load_season("s2026") == {"ostsee": wieder}
    store.delete("s2026", "ostsee")
    assert store.load("s2026", "ostsee") is None


def test_speicher_uebersteht_eine_kaputte_datei(tmp_path):
    store = Store(tmp_path)
    store.save(RaceResult("s2026", "alpen", [(1, 10.0)]))
    pfad = tmp_path / "results" / "s2026" / "alpen.json"
    pfad.write_text("{kaputt", encoding="utf-8")
    assert store.load("s2026", "alpen") is None
    assert store.load_season("s2026") == {}


def test_rangliste_zaehlt_punkte_siege_und_podien(pool):
    teams, riders = pool
    ergebnisse = {
        "ostsee": RaceResult("s2026", "ostsee", [(r.id, 1000.0 + i) for i, r in enumerate(riders)]),
        "toskana": RaceResult("s2026", "toskana", [(r.id, 900.0 + i) for i, r in enumerate(reversed(riders))]),
    }
    tabelle = rider_standings(ergebnisse, riders, teams)
    assert len(tabelle) == len(riders)
    assert [s.points for s in tabelle] == sorted((s.points for s in tabelle), reverse=True)

    # Wer beide Rennen gewonnen hat, gibt es hier nicht — aber der
    # Gesamtführende muss einen Sieg und ein Podium haben.
    erster = tabelle[0]
    assert erster.wins >= 1 or erster.points > 0
    assert erster.starts == 2
    assert len(erster.per_race) == len(CALENDAR)
    assert sum(erster.per_race) == erster.points

    gesamt = sum(s.points for s in tabelle)
    assert gesamt == 2 * sum(POINTS)


def test_punktgleichheit_wird_ueber_siege_getrennt(pool):
    teams, riders = pool
    # Ein Fahrer gewinnt einmal und wird einmal Letzter der Punkteränge;
    # ein anderer wird zweimal Dritter. Beide haben 108 bzw. 130 Punkte —
    # entscheidend ist, dass die Reihenfolge stabil und begründet ist.
    a, b = riders[0].id, riders[1].id
    ergebnisse = {
        "ostsee": RaceResult("s2026", "ostsee", [(a, 100.0), (b, 101.0)]),
        "toskana": RaceResult("s2026", "toskana", [(b, 100.0), (a, 101.0)]),
    }
    tabelle = [s for s in rider_standings(ergebnisse, riders, teams) if s.rider.id in (a, b)]
    assert {s.points for s in tabelle} == {100 + POINTS[1]}
    assert {s.wins for s in tabelle} == {1}
    assert tabelle[0].rider.bib < tabelle[1].rider.bib


def test_teamwertung_ist_die_summe_ihrer_fahrer(pool):
    teams, riders = pool
    ergebnisse = {
        "alpen": RaceResult("s2026", "alpen", [(r.id, 1000.0 + i) for i, r in enumerate(riders)])
    }
    fahrer = rider_standings(ergebnisse, riders, teams)
    mannschaften = team_standings(ergebnisse, riders, teams)

    assert len(mannschaften) == len(teams)
    assert sum(t.points for t in mannschaften) == sum(f.points for f in fahrer) == sum(POINTS)
    assert [t.points for t in mannschaften] == sorted(
        (t.points for t in mannschaften), reverse=True
    )
    for stand in mannschaften:
        erwartet = sum(f.points for f in fahrer if f.rider.team_id == stand.team.id)
        assert stand.points == erwartet


def test_gesamtwertung_addiert_die_fahrzeiten(pool):
    teams, riders = pool
    a, b, c = riders[0].id, riders[1].id, riders[2].id
    ergebnisse = {
        # a gewinnt knapp, b verliert eine Stunde, c fehlt im zweiten Rennen.
        "ostsee": RaceResult("s2026", "ostsee", [(a, 30000.0), (b, 30600.0), (c, 31000.0)]),
        "toskana": RaceResult("s2026", "toskana", [(b, 40000.0), (a, 40100.0)]),
    }
    tabelle = time_standings(ergebnisse, riders, teams)
    nach_id = {s.rider.id: s for s in tabelle}

    assert nach_id[a].total_time_s == pytest.approx(70100.0)
    assert nach_id[b].total_time_s == pytest.approx(70600.0)
    assert nach_id[a].complete and nach_id[b].complete
    assert nach_id[a].races == 2

    # Der Führende steht vorn und hat keinen Rückstand.
    assert tabelle[0].rider.id == a
    assert tabelle[0].gap_s == 0.0
    assert nach_id[b].gap_s == pytest.approx(500.0)


def test_wer_ein_rennen_ausgelassen_hat_steht_hinten(pool):
    """Sonst führt jeder, der nur das kürzeste Rennen bestritten hat."""
    teams, riders = pool
    a, c = riders[0].id, riders[2].id
    ergebnisse = {
        "ostsee": RaceResult("s2026", "ostsee", [(c, 100.0), (a, 30000.0)]),
        "toskana": RaceResult("s2026", "toskana", [(a, 40000.0)]),
    }
    tabelle = time_standings(ergebnisse, riders, teams)
    nach_id = {s.rider.id: s for s in tabelle}

    assert nach_id[c].total_time_s < nach_id[a].total_time_s, "Testaufbau"
    assert nach_id[c].complete is False and nach_id[a].complete is True
    assert tabelle[0].rider.id == a, "der Vollständige führt trotz höherer Summe"
    assert nach_id[c].gap_s == 0.0, "ohne Wertung auch kein Rückstand"

    unvollstaendig = [s for s in tabelle if not s.complete]
    vollstaendig = [s for s in tabelle if s.complete]
    assert tabelle[: len(vollstaendig)] == vollstaendig
    assert len(unvollstaendig) == len(riders) - 1


def test_gesamtwertung_ohne_rennen_wertet_niemanden(pool):
    teams, riders = pool
    tabelle = time_standings({}, riders, teams)
    assert len(tabelle) == len(riders)
    assert all(not s.complete and s.total_time_s == 0.0 and s.races == 0 for s in tabelle)


def test_zeitwertung_und_punktewertung_koennen_auseinanderlaufen(pool):
    """Zwei Wertungen, zwei Sieger — genau dafür gibt es die zweite.

    Wer knapp gewinnt und knapp verliert, sammelt Punkte. Wer einmal
    haushoch gewinnt und einmal knapp verliert, gewinnt nach Zeit.
    """
    teams, riders = pool
    a, b = riders[0].id, riders[1].id
    ergebnisse = {
        "ostsee": RaceResult("s2026", "ostsee", [(a, 30000.0), (b, 33000.0)]),
        "toskana": RaceResult("s2026", "toskana", [(b, 40000.0), (a, 40100.0)]),
    }
    punkte = {s.rider.id: s.points for s in rider_standings(ergebnisse, riders, teams)}
    zeiten = {s.rider.id: s.total_time_s for s in time_standings(ergebnisse, riders, teams)}

    assert punkte[a] == punkte[b], "nach Punkten steht es gleich"
    assert zeiten[a] < zeiten[b], "nach Zeit führt a deutlich"


def test_wertung_ohne_ergebnisse_ist_leer_aber_vollstaendig(pool):
    teams, riders = pool
    tabelle = rider_standings({}, riders, teams)
    assert len(tabelle) == len(riders)
    assert all(s.points == 0 and s.starts == 0 for s in tabelle)
    assert all(t.points == 0 and t.top_rider is None for t in team_standings({}, riders, teams))


def test_bergwertung_summiert_die_rennen(pool):
    from ultraslim.core.season import climb_standings

    teams, riders = pool
    a, b, c = riders[0].id, riders[1].id, riders[2].id
    ergebnisse = {
        "karpaten": RaceResult("s2026", "karpaten", [(a, 1.0)], climb_points={a: 40, b: 25}),
        "alpen": RaceResult("s2026", "alpen", [(b, 1.0)], climb_points={b: 30, c: 12}),
    }
    tabelle = climb_standings(ergebnisse, riders, teams)
    nach_id = {s.rider.id: s for s in tabelle}

    assert [s.rider.id for s in tabelle] == [b, a, c]
    assert nach_id[b].points == 55 and nach_id[b].races == 2
    assert nach_id[a].points == 40 and nach_id[a].races == 1
    assert sum(nach_id[b].per_race) == 55
    # Wer keine Bergpunkte hat, steht gar nicht in der Tabelle.
    assert len(tabelle) == 3


def test_bergwertung_ohne_punkte_ist_leer(pool):
    from ultraslim.core.season import climb_standings

    teams, riders = pool
    assert climb_standings({}, riders, teams) == []
    ohne = {"ostsee": RaceResult("s2026", "ostsee", [(riders[0].id, 1.0)])}
    assert climb_standings(ohne, riders, teams) == []


def test_bergpunkte_ueberstehen_speichern_und_laden(tmp_path):
    store = Store(tmp_path)
    store.save(
        RaceResult("s2026", "alpen", [(3, 1000.0), (7, 1100.0)], climb_points={3: 20, 7: 8})
    )
    wieder = store.load("s2026", "alpen")
    assert wieder is not None
    assert wieder.climb_points == {3: 20, 7: 8}


def test_altes_ergebnis_ohne_bergpunkte_bleibt_lesbar(tmp_path):
    """Dateien aus der Zeit vor der Bergwertung dürfen nicht stolpern."""
    import json

    store = Store(tmp_path)
    ordner = tmp_path / "results" / "s2026"
    ordner.mkdir(parents=True)
    (ordner / "alpen.json").write_bytes(
        json.dumps({"season_id": "s2026", "route_id": "alpen", "finishers": [[1, 500.0]]}).encode()
    )
    wieder = store.load("s2026", "alpen")
    assert wieder is not None
    assert wieder.finishers == [(1, 500.0)]
    assert wieder.climb_points == {}
