from types import SimpleNamespace

from draftkit import blend as BL, usage as U, review as RV


class Reg:
    def __init__(self, pos):
        self.pos = pos

    def meta(self, pid):
        return SimpleNamespace(position=self.pos[str(pid)], team="AAA", name=str(pid))


REG = Reg({"a": "RB", "b": "RB", "c": "RB", "q": "QB", "out": "RB"})
BASE = {"a": 20.0, "b": 12.0, "c": 6.0, "q": 18.0, "out": 0.0}


def test_rank_reads_off_the_base_curve():
    by = BL.to_points(BASE, {"fp": {"c": {"pos_rank": "RB1"}, "a": {"pr": 3.0}}}, REG)
    assert by["fp"]["c"] == 20.0 and by["fp"]["a"] == 6.0


def test_blend_averages_and_keeps_everyone():
    proj, det = BL.blend(BASE, {"fp": {"c": {"pos_rank": "RB1"}}, "ffb": {"c": {"pts": 10.0}}}, REG)
    assert proj["c"] == 12.0                      # (6 + 20 + 10) / 3
    assert proj["a"] == 20.0 and det["c"]["n"] == 3 and det["c"]["spread"] == 14.0
    assert BL.split(det["c"], proj["c"])


def test_a_ruled_out_player_stays_at_zero():
    proj, _ = BL.blend(BASE, {"fp": {"out": {"pos_rank": "RB1"}}}, REG)
    assert proj["out"] == 0.0


def test_a_lone_td_prop_is_not_a_projection():
    by = BL.to_points(BASE, {"vegas": {"a": {"pts": 2.0, "exp": {"td": 0.4}},
                                       "q": {"pts": 17.0, "exp": {"pass_yd": 250, "pass_td": 1.5}}}}, REG)
    assert "a" not in by["vegas"] and by["vegas"]["q"] == 17.0


def test_weights_lean_toward_the_closer_source(monkeypatch):
    g = {str(w): {"n": 100, "src": {"sleeper": {"mae": 6.0, "n": 100}, "fp": {"mae": 5.0, "n": 100},
                                    "flock": {"mae": 6.0, "n": 100}, "ffb": {"mae": 6.0, "n": 100}}}
         for w in (1, 2, 3)}
    monkeypatch.setattr(RV, "grades", lambda season: g)
    w = RV.weights(2026, 4)
    assert w["fp"] > w["sleeper"] and 0.6 <= w["sleeper"] <= 1.5
    monkeypatch.setattr(RV, "grades", lambda season: {"1": g["1"]})
    assert RV.weights(2026, 4) is None             # one week is not a record


def test_usage_opportunity_and_lists():
    assert abs(U.opportunity({"rush_att": 10, "rec_tgt": 5}, 1.0) - 13.35) < 0.06
    profs = {"x": {"n": 3, "opp3": 14.0, "pts3": 6.0, "gap": 8.0},
             "star": {"n": 3, "opp3": 20.0, "pts3": 26.0, "gap": -6.0},
             "lucky": {"n": 3, "opp3": 8.0, "pts3": 18.0, "gap": -10.0}}
    profs["fading"] = {"n": 3, "opp3": 14.0, "pts3": 6.0, "gap": 8.0, "trend": "down"}
    assert U.buys(profs, profs) == ["x"]           # a shrinking role isn't a buy
    assert U.sells(profs, profs) == ["lucky"]      # the star beats his workload on talent
    assert U.tag({"trend": "up", "d_snap": -14, "snap": 64, "opp": 12.0, "d_opp": 5.0,
                  "weeks": []}).startswith("workload")


def test_underdog_takes_the_volatile_flex_and_favourite_does_not():
    from draftkit import weekly as W
    reg = Reg({"s": "RB", "b": "WR", "q": "QB"})
    proj = {"s": 12.0, "b": 11.5, "q": 20.0}
    sd = {"s": 3.0, "b": 11.0, "q": 6.0}
    lineup, bench = [("QB", "q"), ("FLEX", "s")], ["b"]
    dog = W.odds_swaps(lineup, bench, proj, reg, opp_mean=45.0, opp_sd=8.0, sd_of=lambda p: sd[p])
    assert dog and dog[0]["in"] == "b" and dog[0]["kind"] == "swing" and dog[0]["cost"] == 0.5
    fav = W.odds_swaps(lineup, bench, proj, reg, opp_mean=20.0, opp_sd=8.0, sd_of=lambda p: sd[p])
    assert not fav                                # he's already holding the safe one
    assert W.blended_sd("WR", 10.0, [2, 25, 4, 22]) > W.blended_sd("WR", 10.0, [9, 11, 10, 10])


def test_sweep_skips_byes_and_lists_designations(monkeypatch):
    from draftkit import weekpulse as WP, gametime as GT, weather as WX
    import time
    monkeypatch.setattr(WX, "for_week", lambda games, s, w: {"AAA": {"bad": True, "label": "22 mph wind"}})
    k = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(time.time() + 86400))
    games = {"AAA": {"opp": "BBB", "home": True, "kickoff": k, "state": "pre"}}

    class R:
        def meta(self, pid):
            return SimpleNamespace(position={"q": "QB", "r": "RB", "bye": "WR"}[pid], name=pid,
                                   team={"q": "AAA", "r": "AAA", "bye": "ZZZ"}[pid],
                                   injury_status={"r": "Questionable"}.get(pid))
    rows = WP._sweep([("QB", "q"), ("RB", "r"), ("WR", "bye")], R(), games, [], 2026, 10)
    kinds = {(r["name"], r["kind"]) for r in rows}
    assert kinds == {("q", "wx"), ("r", "inj")}       # the RB isn't a weather position; the bye isn't listed
