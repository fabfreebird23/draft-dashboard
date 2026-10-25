from draftkit.ui import components as C


def test_flap_folds_only_changed_digits():
    h = C.flap_html("80.1", "78.6")
    assert h.count('m3-fl go') == 3          # 7->8, 8->0, 6->1; the point never flaps
    assert 'aria-label="80.1"' in h
    assert C.flap_html("80.1", "80.1").count(" go") == 0


def test_flap_handles_a_longer_score():
    assert C.flap_html("101.2", "99.8").count('m3-fl go') == 4


def test_towers_and_ring_render():
    assert C.towers_html([("QB", 20.0, 18.0), ("RB", 30.0, 35.0)]).count("m3-pr ") == 4
    assert C.league_ring_html([{"name": "A", "rec": "1-0"}]) == ""
    assert "m3-lc" in C.league_ring_html([{"name": "A"}, {"name": "B"}])


def test_scoreboard_flashes_the_side_that_scored():
    kw = dict(me_name="You", me_rec="", me_sub="", me_photo=None, opp_name="X", opp_rec="", opp_sub="",
              opp_photo=None, label="LIVE")
    h = C.scoreboard_html(me_pts="80.1", opp_pts="50.0", flaps=("78.6", "50.0"), **kw)
    assert 'xb-side me up' in h and 'xb-side op up' not in h
