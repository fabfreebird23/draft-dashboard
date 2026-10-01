"""Keeper prices follow each league's ladder (copied from the hubs' engine.py)."""
from types import SimpleNamespace

from draftkit.weekly import keeper_outlook

RULES = {"max_regular_keepers": 3, "max_rookie_keepers": 2, "max_keep_years": 3,
         "year2_bump_rounds": 3, "_last_round": 14}


class Reg:
    def __init__(self, people):
        self.people = people

    def meta(self, pid):
        return SimpleNamespace(name=pid, position="WR", team="X", years_exp=3)


def run(pids, *, drafted=None, existing=None, adp=None, policy="raise_only", me="me"):
    adp = adp or {}
    rows = keeper_outlook(pids, drafted_round=drafted or {}, existing=existing or {},
                          rules=dict(RULES, _adp_policy=policy), n_teams=8,
                          adp_rank=lambda n, p: adp.get(n), registry=Reg(pids),
                          proj={}, me=me)
    return {r["pid"]: r for r in rows}


def test_traded_for_player_keeps_the_drafting_teams_round():
    # Ned drafted Walker in round 3; he traded for him. Not a waiver add.
    r = run(["walker"], drafted={"walker": (3, "ned")}, adp={"walker": 16})["walker"]
    assert r["cost_round"] == 3 and "traded for" in r["note"]


def test_year_three_is_adp_in_every_league():
    for policy in ("raise_only", "discount", "relief"):
        r = run(["jsn"], existing={"jsn": {"keep_year": 2, "cost_round": 6}},
                adp={"jsn": 5}, policy=policy)["jsn"]
        assert r["cost_round"] == 1, policy          # ADP 5 in 8 teams -> R1


def test_year_two_kreeper_ladders_and_adp_never_discounts():
    r = run(["p"], existing={"p": {"keep_year": 1, "cost_round": 8}}, adp={"p": 90})["p"]
    assert r["cost_round"] == 5                      # 8 - 3, ADP R12 ignored


def test_year_two_bnb_takes_the_cheaper_adp():
    r = run(["p"], existing={"p": {"keep_year": 1, "cost_round": 8}}, adp={"p": 90},
            policy="discount")["p"]
    assert r["cost_round"] == 12                     # ADP round 12 is cheaper than R5


def test_year_two_seven_half_is_capped_at_year_one():
    r = run(["p"], existing={"p": {"keep_year": 1, "cost_round": 8}}, adp={"p": 90},
            policy="relief")["p"]
    assert r["cost_round"] == 8                      # relief, but never later than yr1


def test_past_the_cap_is_blocked():
    r = run(["mcb"], existing={"mcb": {"keep_year": 3, "cost_round": 3}}, adp={"mcb": 26})["mcb"]
    assert r["verdict"] == "blocked"


def test_round_one_keeper_in_year_two_is_floored_not_blocked():
    r = run(["arsb"], existing={"arsb": {"keep_year": 1, "cost_round": 1}}, adp={"arsb": 7})["arsb"]
    assert r["cost_round"] == 1 and r["verdict"] != "blocked"


def test_adp_discount_stops_at_the_last_round():
    r = run(["k"], drafted={"k": (13, "me")}, adp={"k": 217}, policy="discount")["k"]
    assert r["cost_round"] == 14                     # 14 rounds in this test league


SEVEN = dict(RULES, max_rookie_keepers=2, rookie_last_rounds=True, rookie_must_be_own_draft=True,
             rookie_draft_premium_round=5, _adp_policy="relief")


def run7(pids, drafted, adp, rookies=(), me="me"):
    class R(Reg):
        def meta(self, pid):
            return SimpleNamespace(name=pid, position="WR", team="X",
                                   years_exp=0 if pid in rookies else 3)
    rows = keeper_outlook(pids, drafted_round=drafted, existing={}, rules=SEVEN, n_teams=8,
                          adp_rank=lambda n, p: adp.get(n), registry=R(pids), proj={}, me=me)
    return {r["pid"]: r for r in rows}


def test_seven_rookie_board_pick_prices_at_the_premium():
    r = run7(["rb"], {"rb": (1, "other", "rookie")}, {"rb": 60})["rb"]
    assert r["cost_round"] == 5 and "premium" in r["note"]      # traded for: not a rookie slot


def test_seven_own_rookie_takes_a_rookie_slot_at_the_last_round():
    r = run7(["rk"], {"rk": (12, "me", "veteran")}, {"rk": 90}, rookies={"rk"})["rk"]
    assert r["cost_round"] == 14 and r["slot_used"] == "rookie"


def test_seven_traded_for_rookie_is_a_regular_keeper_at_his_round():
    r = run7(["rk"], {"rk": (9, "ned", "veteran")}, {"rk": 90}, rookies={"rk"})["rk"]
    assert r["cost_round"] == 9 and "rookie slot" not in r["note"]
