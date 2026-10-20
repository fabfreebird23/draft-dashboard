"""Rest-of-season consensus."""
from draftkit import ros as R


def _row(pid, pos, **src):
    return {"pid": pid, "pos": pos, "src": src}


def test_flex_reranks_each_source_among_skill_players():
    b = {
        "qb": _row("qb", "QB", fp={"ov": 1, "pr": 1}, sleeper={"pts": 300, "games": 11}),
        "rb": _row("rb", "RB", fp={"ov": 2, "pr": 1}, flock={"ov": 3, "pr": 1},
                   ffb={"pr": 1, "pts": 200}, sleeper={"pts": 220, "games": 11}),
        "wr": _row("wr", "WR", fp={"ov": 5, "pr": 1}, flock={"ov": 1, "pr": 1},
                   ffb={"pr": 1, "pts": 210}, sleeper={"pts": 180, "games": 10}),
    }
    rows = R.rank(b, "FLEX")
    assert [r["pid"] for r in rows] == ["rb", "wr"]          # no QB in FLEX
    rb = rows[0]
    # FP 2 -> 1st among skill; Flock 3 -> 2nd; Ballers by pts -> 2nd; Sleeper -> 1st
    assert rb["r"] == {"fp": 1.0, "flock": 2.0, "ffb": 2.0, "sleeper": 1.0}
    assert rb["cons"] == 1.5 and rb["spread"] == 1.0


def test_single_source_players_sort_behind_agreed_ones():
    b = {"a": _row("a", "TE", fp={"pr": 3}, flock={"pr": 3}),
         "b": _row("b", "TE", ffb={"pr": 1})}
    assert [r["pid"] for r in R.rank(b, "TE")] == ["a", "b"]


def test_position_view_ranks_sleeper_by_points_within_position():
    b = {"x": _row("x", "WR", sleeper={"pts": 100, "games": 10}),
         "y": _row("y", "WR", sleeper={"pts": 150, "games": 10})}
    rows = R.rank(b, "WR")
    assert {r["pid"]: r["r"]["sleeper"] for r in rows} == {"y": 1.0, "x": 2.0}
