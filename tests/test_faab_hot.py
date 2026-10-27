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
