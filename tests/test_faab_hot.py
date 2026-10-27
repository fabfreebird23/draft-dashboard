import types

from draftkit import faabhistory as FH
from draftkit import faabmarket as FM


def claim(season, week, name, bids, budget=100):
    win = max(bids, key=lambda b: b[1])
    return {"season": season, "week": week, "name": name, "pos": "RB", "budget": budget,
            "won": win[1], "winner": win[0],
            "bids": [{"team": t, "bid": v, "won": (t, v) == win, "user": None} for t, v in bids]}


def test_one_team_two_zero_claims_is_one_bidder():
    r = claim(2025, 3, "X", [("a", 0), ("a", 0), ("b", 5)])
    assert FH.team_bids(r) == {"a": 0, "b": 5}
    assert not FH.is_hot(r)                       # one team paying, $5 of $100
    assert FH.is_hot(claim(2025, 3, "Y", [("a", 4), ("b", 6)]))
    assert FH.is_hot(claim(2025, 3, "Z", [("a", 20)]))


def test_profiles_scale_old_budgets():
    rows = [claim(2023, 3, "Ford", [("t", 191), ("b", 23)], budget=250), claim(2025, 3, "Benson", [("b", 52), ("m", 15)])]
    p = FH.hot_profiles(rows)
    assert round(p["t"]["max"], 2) == 0.76 and p["b"]["max"] == 0.52
    assert FH.hot_profiles(rows, since=2024)["b"]["n"] == 1


def test_needs_tiers(monkeypatch):
    rosters = [{"roster_id": i, "owner_id": f"u{i}", "players": [f"p{i}a", f"p{i}b"]} for i in range(3)]
    proj = {"p0a": 5, "p0b": 2, "p1a": 12, "p1b": 9, "p2a": 18, "p2b": 15}
    players = {k: {"position": "RB", "full_name": k} for k in proj}
    monkeypatch.setattr(FM.api, "get_league", lambda lid: {"roster_positions": ["RB", "RB", "FLEX"]})
    monkeypatch.setattr(FM.api, "get_rosters", lambda lid: rosters)
    monkeypatch.setattr(FM.api, "get_users", lambda lid: [{"user_id": f"u{i}", "display_name": f"T{i}"} for i in range(3)])
    monkeypatch.setattr(FM.api, "get_players", lambda: players)
    monkeypatch.setattr(FM, "_week_proj", lambda s, w: proj)
    n = FM.position_needs(types.SimpleNamespace(league_id="L", season=2026), "RB", 8)
    assert n["T0"]["tier"] == "need" and n["T2"]["tier"] == "set" and n["T1"]["tier"] == "ok"


FBG_HTML = """<p>Here's a look:</p><h3><strong>Jonah Coleman</strong> (RB-DEN)</h3>
<p><strong>Bid Recommendation: 50-100% of Annual FAAB Budget</strong></p><p>If Coleman wasn't…</p>
<h3>Caleb Douglas (WR-MIA)</h3><p>Bid Recommendation: 15-30% of Annual FAAB Budget</p>"""


def test_parse_footballguys():
    from draftkit import expertfaab as EF
    rows = EF.parse_fbg(FBG_HTML)
    assert [(r["name"], r["pos"], r["team"], r["lo"], r["hi"]) for r in rows] == [
        ("Jonah Coleman", "RB", "DEN", 50.0, 100.0), ("Caleb Douglas", "WR", "MIA", 15.0, 30.0)]


def test_expert_values_average_the_sources(monkeypatch):
    from draftkit import expertfaab as EF
    EF._MEMO.clear()
    monkeypatch.setattr(EF, "fbg", lambda s, w: [{"name": "Jonah Coleman", "pos": "RB", "team": "DEN", "lo": 50.0, "hi": 100.0}])
    monkeypatch.setattr(EF, "ballers", lambda s, w: [{"name": "Jonah Coleman", "pos": "RB", "team": "DEN", "lo": 10.0, "hi": 15.0},
                                                       {"name": "Brenton Strange", "pos": "TE", "team": "JAX", "lo": 0.0, "hi": 0.0}])
    players = {"1": {"full_name": "Jonah Coleman", "team": "DEN"}, "2": {"full_name": "Brenton Strange", "team": "JAX"}}
    v = EF.values(2026, 8, players)
    assert round(v["1"]["lo"], 3) == 0.3 and round(v["1"]["hi"], 3) == 0.575
    assert v["2"]["hi"] == 0.0


def test_a_list_a_week_behind_is_dropped(monkeypatch):
    from draftkit import expertfaab as EF
    EF._MEMO.clear()
    monkeypatch.setattr(EF, "fbg", lambda s, w: [{"name": "Jonah Coleman", "pos": "RB", "team": "DEN", "lo": 50.0, "hi": 100.0}] if w == 8 else [])
    # The Footballers board hasn't turned over: only last week's list exists.
    monkeypatch.setattr(EF, "ballers", lambda s, w: [{"name": "Jonah Coleman", "pos": "RB", "team": "DEN", "lo": 0.0, "hi": 0.0}] if w == 7 else [])
    v = EF.values(2026, 8, {"1": {"full_name": "Jonah Coleman", "team": "DEN"}})
    assert list(v["1"]["src"]) == ["Footballguys"] and v["1"]["lists"] == {"Footballguys": 8}
