"""Today's inbox: only what can still be done, in the order it stops mattering."""
import time
from types import SimpleNamespace

from draftkit import weekpulse as WP


class Reg:
    def meta(self, pid):
        return SimpleNamespace(name=f"P{pid}", team="KC", position="WR")


def _games(monkeypatch, kicks):
    monkeypatch.setattr(WP.WV, "game_of", lambda reg, games, pid: {"pid": pid} if pid else None)
    monkeypatch.setattr(WP.GT, "kickoff_ts", lambda g: kicks.get((g or {}).get("pid"), 0.0))


def test_a_swap_with_a_locked_player_is_not_offered(monkeypatch):
    now = time.time()
    _games(monkeypatch, {"walker": now - 3600, "nabers": now + 3600})   # Walker already played
    out = {"moves": [{"out": "nabers", "in": "walker", "gain": 6.0}], "injury_rows": []}
    items = WP._inbox(out, Reg(), {}, 4, {"label": "Kreeper", "league_id": "1"}, started=True)
    assert items == []


def test_an_open_swap_is_offered_with_its_lock_time(monkeypatch):
    now = time.time()
    _games(monkeypatch, {"olave": now + 7200, "waddle": now + 7200})
    out = {"moves": [{"out": "olave", "in": "waddle", "gain": 2.9}],
           "injury_rows": [{"pid": "olave", "name": "Chris Olave", "status": "Questionable",
                            "cost_if_out": 2.9, "team": "NO"}]}
    it = WP._inbox(out, Reg(), {}, 5, {"label": "Kreeper", "league_id": "1"}, started=False)[0]
    assert it["kind"] == "LOCK" and it["title"] == "Polave is questionable"
    assert it["nav"] == "Lineup" and abs(it["ts"] - (now + 7200)) < 1


def test_a_claim_is_due_at_the_next_wednesday_run():
    ts = WP._next_waivers_ts(time.mktime((2026, 10, 4, 12, 0, 0, 0, 0, -1)))   # a Sunday
    assert time.gmtime(ts).tm_wday == 2 and time.gmtime(ts).tm_hour == 7       # Wed 07:00 UTC
