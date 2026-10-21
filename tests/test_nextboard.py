from draftkit import nextboard as NB


def test_snake_order():
    seq = NB.sequence([10, 20, 30], 2)
    assert [(p, r, s) for p, r, s in seq] == [(1, 1, 1), (2, 1, 2), (3, 1, 3), (4, 2, 3), (5, 2, 2), (6, 2, 1)]


def test_traded_pick_belongs_to_holder():
    cells = NB.build([10, 20], 1, {(1, 10): 20}, {}, ["a", "b"], {"a": "RB", "b": "WR"})
    assert cells[(1, 1)]["holder"] == 20 and cells[(1, 1)]["traded"]
    assert cells[(1, 1)]["pid"] == "a"


def test_keeper_takes_latest_pick_in_his_round():
    # team 10 holds both round-1 picks; its keeper costs R1 -> the later one (slot 2)
    cells = NB.build([10, 20], 2, {(1, 20): 10}, {10: [("k", 1)]}, ["a", "b", "c", "k"],
                     {"a": "RB", "b": "RB", "c": "WR", "k": "WR"})
    assert cells[(1, 2)]["pid"] == "k" and cells[(1, 2)]["keeper"]
    assert cells[(1, 1)]["pid"] == "a"


def test_traded_round_moves_up_never_down():
    # team 10 traded its R2; a R2 keeper moves UP to its R1
    cells = NB.build([10, 20], 2, {(2, 10): 20}, {10: [("k", 2)]}, ["a", "b", "c", "k"],
                     {p: "RB" for p in "abck"})
    assert cells[(1, 1)]["pid"] == "k"
    # a R1 keeper with no R1 left is not placed at all
    cells = NB.build([10, 20], 2, {(1, 10): 20}, {10: [("k", 1)]}, ["a", "b", "c", "d", "k"],
                     {p: "RB" for p in "abcdk"})
    assert all(c["pid"] != "k" or not c["keeper"] for c in cells.values())


def test_no_third_qb():
    pool = ["q1", "q2", "q3", "r1"]
    pos = {"q1": "QB", "q2": "QB", "q3": "QB", "r1": "RB"}
    cells = NB.build([10], 4, {}, {}, pool, pos)
    picked = [cells[(r, 1)]["pid"] for r in range(1, 5)]
    assert picked[:2] == ["q1", "q2"] and picked[2] == "r1"
