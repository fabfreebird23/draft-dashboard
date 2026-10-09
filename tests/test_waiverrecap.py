from draftkit import waiverrecap as WR


def tx(rid, pid, bid, status, ts=1000):
    return {"type": "waiver", "status": status, "roster_ids": [rid], "adds": {pid: rid},
            "settings": {"waiver_bid": bid}, "status_updated": ts}


def test_recap_lines_up_runner_up_and_season(monkeypatch):
    weeks = {1: [tx(3, "a", 3, "complete"), tx(5, "a", 2, "failed"),
                 tx(3, "b", 2, "failed"), tx(2, "b", 9, "complete")],
             2: [tx(3, "c", 4, "complete", 5000)]}

    def fake(lid, wk):
        out = {}
        for t in weeks.get(wk, []):
            for p in t["adds"]:
                out.setdefault(p, []).append(t)
        return out
    monkeypatch.setattr(WR, "_week_claims", fake)
    rec = WR.recap("L", 3, 2)
    assert rec["week"] == 2 and [r["pid"] for r in rec["claims"]] == ["c"]
    s = rec["season"]
    assert (s["won"], s["tried"], s["paid"]) == (2, 3, 7)
    # a: paid 3 vs runner-up 2 -> 0 over; c: uncontested $4 -> 4 over
    assert s["over"] == 4
    rec1 = WR.recap("L", 3, 1)
    lost = next(r for r in rec1["claims"] if r["pid"] == "b")
    assert not lost["won"] and lost["win_bid"] == 9 and lost["winner"] == 2


def test_all_failed_has_no_runner_up(monkeypatch):
    monkeypatch.setattr(WR, "_week_claims", lambda lid, wk: {"x": [tx(3, "x", 0, "failed"), tx(4, "x", 4, "failed")]} if wk == 1 else {})
    r = WR.recap("L", 3, 1)["claims"][0]
    assert r["runner_up"] is None and r["winner"] is None
