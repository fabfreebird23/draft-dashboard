"""What happened when waivers ran — his claims, the runner-up, and our bid.

The league-specific bids (faabmarket) are only worth trusting if they're
checked against what actually cleared. This reads Sleeper's transactions for
the last waiver run he took part in and lines up, per claim: did he win, what
he bid, what the winner paid, the second bid (the price that actually had to
be beaten) and what the app had suggested. A season tally sits underneath:
claims won, dollars spent, and how much of that was more than the runner-up.

Sleeper only. ESPN's TD's league has no FAAB in this app.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from . import sleeper_client as api


def _bid(t: dict) -> int:
    return int((t.get("settings") or {}).get("waiver_bid") or 0)


def _week_claims(league_id: str, week: int) -> Dict[str, List[dict]]:
    """{pid: [waiver tx, ...]} for one week (fresh-ish: 10 min)."""
    try:
        tx = api._disk(f"tx_{league_id}_{week}", 600,
                       lambda: api._get(f"league/{league_id}/transactions/{week}") or [])
    except Exception:  # noqa: BLE001
        return {}
    out = defaultdict(list)
    for t in tx or []:
        if t.get("type") == "waiver" and t.get("status") in ("complete", "failed"):
            for pid in (t.get("adds") or {}):
                out[str(pid)].append(t)
    return out


def _mine(ts: List[dict], rid: int) -> Optional[dict]:
    return next((t for t in ts if rid in (t.get("roster_ids") or [])), None)


def _row(pid: str, ts: List[dict], rid: int) -> Optional[dict]:
    me = _mine(ts, rid)
    if not me:
        return None
    win = next((t for t in ts if t.get("status") == "complete"), None)
    bids = sorted((_bid(t) for t in ts), reverse=True)
    won = me.get("status") == "complete"
    return {"pid": pid, "won": won, "bid": _bid(me),
            "win_bid": _bid(win) if win else None,
            "winner": (win.get("roster_ids") or [None])[0] if win else None,
            # the price that had to be beaten: the best bid that lost to the winner
            # (no winner = every claim failed — roster limits, a drop that
            # was no longer there — so there was no price to beat)
            "runner_up": (bids[1] if (win and len(bids) > 1) else None),
            "bidders": len(ts),
            "ts": int(me.get("status_updated") or me.get("created") or 0)}


def recap(league_id: str, roster_id: int, week: int) -> Optional[dict]:
    """The latest waiver run he was in (this week, else last), plus the season.

    {"week", "ts", "claims": [row...], "season": {"won","tried","paid","over"}}"""
    rid = int(roster_id)
    latest, season_rows = None, []
    for wk in range(1, int(week) + 1):
        rows = [r for r in (_row(p, ts, rid) for p, ts in _week_claims(league_id, wk).items()) if r]
        season_rows += rows
        if rows:
            latest = (wk, rows)
    if not latest:
        return None
    wk, rows = latest
    # one waiver run per recap: the last processing time he was part of
    last_ts = max(r["ts"] for r in rows)
    run = [r for r in rows if last_ts - r["ts"] < 6 * 3600 * 1000]
    run.sort(key=lambda r: (not r["won"], -r["bid"]))
    won = [r for r in season_rows if r["won"]]
    over = sum(r["bid"] - ((r["runner_up"] + 1) if r["runner_up"] is not None else 0) for r in won)
    return {"week": wk, "ts": last_ts, "claims": run,
            "season": {"won": len(won), "tried": len(season_rows),
                       "paid": sum(r["bid"] for r in won), "over": max(0, over)}}


def resolved(league_id: str, week: int, pids) -> set:
    """Which of these queued pids have already gone through waivers (won or
    lost) — they leave the queue instead of haunting it."""
    pids = {str(p) for p in pids}
    done = set()
    for wk in range(max(1, int(week) - 1), int(week) + 1):
        done |= pids & set(_week_claims(league_id, wk))
    return done
