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


def test_sleeper_scoring_reads_the_league_book_and_prices_bonuses():
    from draftkit import scoring as S
    w = S.from_sleeper({"rec": 1, "pass_yd": 0.04, "pass_td": 4, "pass_cmp": 0.25, "rush_yd": 0.1,
                        "rush_td": 6, "rec_yd": 0.1, "rec_td": 6, "bonus_rush_yd_100": 2,
                        "def_td": 6, "fgm_50p": 5})
    assert "def_td" not in w and w["pass_cmp"] == 0.25 and S.is_custom(w)
    qb = {"pass_yd": 250, "pass_td": 2, "pass_cmp": 22}
    assert abs(S.points(qb, w) - (10 + 8 + 5.5)) < 1e-6
    # a 100-yard back gets about half the bonus; a 40-yard back almost none
    assert 0.9 < S.points({"rush_yd": 100}, w) - 10 < 1.1
    assert S.points({"rush_yd": 40}, w) - 4 < 0.05
    # per game: a 12-game, 1,200-yard season is ~12 coin flips at 100, not one sure thing
    season = S.points({"rush_yd": 1200, "gp": 12}, w) - 120
    assert 10 < season < 14
