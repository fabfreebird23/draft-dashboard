from draftkit import lottery as L

TEAMS = [str(i) for i in range(8)]
MEANS = {t: 100 + 5 * i for i, t in enumerate(TEAMS)}
SDS = {t: 20 for t in TEAMS}
RECS = {t: (i, 7 - i) for i, t in enumerate(TEAMS)}
PF = {t: 1000 + 10 * i for i, t in enumerate(TEAMS)}


def _run(spec):
    return L.slot_odds(MEANS, SDS, RECS, PF, {}, 4, spec, n_sims=1500)


def test_every_slot_sums_to_100_in_every_style():
    for spec in ({"style": "inverted", "weights": [25, 22, 19, 14, 10, 6, 3, 1]},
                 {"style": "final", "weights": [24, 21, 18, 15, 10, 7, 3, 2], "draws": 2},
                 {"style": "chase", "weights": [640, 320, 160, 80, 40, 20, 8, 4]}):
        r = _run(spec)
        for slot in range(8):
            assert abs(sum(r[t][slot] for t in TEAMS) - 100) < 1
        for t in TEAMS:
            assert abs(sum(r[t]) - 100) < 1


def test_worst_team_beats_the_best_to_the_top_pick():
    r = _run({"style": "inverted", "weights": [25, 22, 19, 14, 10, 6, 3, 1]})
    assert r["0"][0] > r["7"][0]


def test_final_style_only_draws_two():
    # past the two drawn choices the order is fixed by weight, so no team that
    # is certain to finish best can land slot 3+ ahead of the bottom of the board
    r = _run({"style": "final", "weights": [24, 21, 18, 15, 10, 7, 3, 2], "draws": 2})
    assert r["7"][2] == 0
