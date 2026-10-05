"""Keeper value = talent minus what the cost round's pick lands in a
keeper-depleted draft (draftkit.weekly.replacement_by_round)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from draftkit import weekly as W  # noqa: E402


def _rank_of(table):
    return lambda name, pos: table.get(name)


def test_talent_curve_is_steep_at_the_top():
    assert W.talent_value(1) == 100
    assert W.talent_value(1) - W.talent_value(35) > W.talent_value(60) - W.talent_value(95)


def test_no_keepers_is_a_plain_draft():
    """8 teams, no keepers: round 1's middle pick is ~#5."""
    repl = W.replacement_by_round({}, 8, 3, _rank_of({}))
    assert repl[1] == W.talent_value(5)
    assert repl[1] > repl[2] > repl[3]


def test_keepers_drain_the_early_rounds():
    """The top 10 all kept (at R14): round 1's free picks now land #11+."""
    kept = {"a": [{"player_name": f"P{i}", "position": "RB", "cost_round": 14} for i in range(1, 11)]}
    ranks = {f"P{i}": i for i in range(1, 11)}
    repl = W.replacement_by_round(kept, 8, 14, _rank_of(ranks))
    assert repl[1] == W.talent_value(15)
    assert repl[1] < W.replacement_by_round({}, 8, 14, _rank_of({}))[1]


def test_keepers_occupy_their_rounds_picks():
    """Six keepers costing R1 leave two free 1st-round picks, so round 2
    starts sooner in the pool than it would otherwise."""
    kept = {"a": [{"player_name": f"K{i}", "position": "WR", "cost_round": 1} for i in range(6)]}
    repl = W.replacement_by_round(kept, 8, 3, _rank_of({}))
    plain = W.replacement_by_round({}, 8, 3, _rank_of({}))
    assert repl[2] > plain[2]


def test_elite_player_kept_early_is_worth_keeping():
    """With the top 10 kept, the #2 player kept in round 1 beats a round-1
    pick by a wide margin — the old pick-gap math scored this ~0."""
    kept = {"a": [{"player_name": f"P{i}", "position": "RB", "cost_round": 14} for i in range(3, 13)]}
    ranks = {f"P{i}": i for i in range(3, 13)}
    repl = W.replacement_by_round(kept, 8, 14, _rank_of(ranks))
    assert W.talent_value(2) - repl[1] > 25
