"""League-specific FAAB pricing."""
from draftkit import faabmarket as FM


def _rows(n_free=40, contested=((2, 9), (1, 8), (5, 12), (3, 10), (2, 11), (8, 14))):
    rows = [{"season": 2025, "week": 6, "pid": f"f{i}", "budget": 100, "won": 0,
             "lost": [], "proj": 8.0} for i in range(n_free)]
    for i, (second, proj) in enumerate(contested):
        rows.append({"season": 2025, "week": 6, "pid": f"c{i}", "budget": 100,
                     "won": second + 4, "lost": [second], "proj": float(proj)})
    return rows


def test_market_prices_far_below_value_ceiling():
    mk = FM.Market(_rows(), 2026, 6)
    r = FM.recommend(mk, gain=3.0, proj=10.0, budget=100, left=94, weeks_left=8)
    assert r["mode"] == "market"
    assert 1 <= r["low"] <= r["high"] <= 15          # the market, not the old $28–43
    assert r["high"] < r["ceiling"]


def test_never_bids_zero_on_a_real_upgrade():
    mk = FM.Market(_rows(contested=()), 2026, 6)
    r = FM.recommend(mk, gain=2.0, proj=9.0, budget=100, left=50, weeks_left=8)
    assert r["low"] >= 1


def test_value_ceiling_caps_a_hot_market():
    hot = [(60, 12)] * 30
    mk = FM.Market(_rows(n_free=0, contested=hot), 2026, 6)
    r = FM.recommend(mk, gain=1.0, proj=12.0, budget=100, left=100, weeks_left=2)
    assert r["high"] <= r["ceiling"] < 61
    assert "worth" in r["note"]


def test_bigger_upgrade_bids_surer():
    mk = FM.Market(_rows(), 2026, 6)
    small = FM.recommend(mk, gain=0.8, proj=10.0, budget=100, left=94, weeks_left=8)
    big = FM.recommend(mk, gain=6.0, proj=10.0, budget=100, left=94, weeks_left=8)
    assert big["high"] >= small["high"]


def test_budget_share_survives_a_bigger_budget_season():
    rows = [dict(r, budget=250, lost=[x * 2.5 for x in r["lost"]]) for r in _rows()]
    a = FM.recommend(FM.Market(_rows(), 2026, 6), gain=3, proj=10, budget=100, left=100, weeks_left=8)
    b = FM.recommend(FM.Market(rows, 2026, 6), gain=3, proj=10, budget=100, left=100, weeks_left=8)
    assert abs(a["high"] - b["high"]) <= 1


def test_priority_league_gets_no_dollar_figure():
    mk = FM.Market([], 2026, 6, faab=False)
    r = FM.recommend(mk, gain=4.0, proj=12.0, budget=100, left=100, weeks_left=8)
    assert r["mode"] == "priority" and r["high"] == 0


def test_no_upgrade_means_no_spend():
    mk = FM.Market(_rows(), 2026, 6)
    r = FM.recommend(mk, gain=0.0, proj=10.0, budget=100, left=94, weeks_left=8)
    assert r["high"] == 0


def test_season_sim_real_schedule():
    from draftkit import weekly as W
    means = {"a": 120, "b": 100, "c": 100, "d": 80}
    sds = {t: 15 for t in means}
    recs = {t: (2, 2) for t in means}
    sched = {6: [("a", "b"), ("c", "d")], 7: [("a", "c"), ("b", "d")], 8: [("a", "d"), ("b", "c")]}
    out = W.season_sim(means, sds, recs, {t: 0 for t in means}, sched, 2, "b", n_sims=4000)
    assert out["teams"]["a"]["playoff_pct"] > out["teams"]["d"]["playoff_pct"]
    assert abs(sum(out["seeds"]) - 100) <= 2
    wk = {w["week"]: w for w in out["weeks"]}
    assert wk[6]["opp"] == "a" and wk[6]["p_win"] < 30          # b vs the best team
    assert all(w["if_win"] >= w["if_lose"] for w in out["weeks"])
