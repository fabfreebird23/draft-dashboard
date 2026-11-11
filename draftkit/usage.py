"""What a player's ROLE is doing, before his points say so.

Projections follow production, and production follows opportunity by a week
or two: the back whose snaps went 38% -> 61% -> 70% is a starter before any
ranking calls him one, and the receiver whose targets are drying up is still
priced on last month. So this reads the box scores for the finished weeks and
keeps the opportunity lines:

    snap share      his offensive snaps / his team's
    target share    his targets / the team's
    carry share     his carries / the team's
    red-zone work   targets and carries inside the 20

and one number that adds them up — OPPORTUNITY POINTS, what an average player
scores on that workload (a carry is worth about 0.55, a target about a point
plus the reception, red-zone looks most of a point more). Points above it are
touchdowns and long plays, which don't repeat; points below it usually come.
That gap is the buy-low / sell-high list.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import nflstats as NS

_POS = ("RB", "WR", "TE")


def _f(row: dict, k: str) -> float:
    try:
        return float(row.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def opportunity(row: dict, ppr: float = 1.0) -> float:
    """Expected fantasy points from the workload alone."""
    return round(_f(row, "rush_att") * 0.55 + _f(row, "rush_rz_att") * 0.9
                 + _f(row, "rec_tgt") * (0.95 + 0.62 * ppr) + _f(row, "rec_rz_tgt") * 1.0, 1)


def _pts(row: dict, scoring: str, weights) -> float:
    if weights:
        from . import scoring as SC
        return round(SC.points(row, weights), 1)
    return _f(row, {"ppr": "pts_ppr", "half": "pts_half_ppr", "std": "pts_std"}.get(scoring, "pts_ppr"))


def profiles(season: int, week: int, registry, *, scoring: str = "ppr", weights=None,
             lookback: int = 4) -> Dict[str, dict]:
    """{pid: profile} for every RB/WR/TE with work in the last `lookback`
    finished weeks (the weeks before `week`).

    profile = {weeks: [{week, snap, tgt, tgt_sh, att, att_sh, rz, opp, pts}],
               snap, d_snap, opp, d_opp, opp3, pts3, gap, trend}
    `weeks` holds only the games he PLAYED, oldest first; the deltas compare his
    latest game with the average of the (up to two) before it."""
    ppr = 1.0 if scoring == "ppr" else 0.5 if scoring == "half" else 0.0
    if weights and weights.get("rec") is not None:
        ppr = float(weights["rec"])
    out: Dict[str, dict] = {}
    for wk in range(max(1, int(week) - lookback), int(week)):
        rows = NS.final(season, wk)
        if not rows:
            continue
        for pid, r in rows.items():
            if pid.startswith("TEAM_") or not _f(r, "off_snp"):
                continue
            try:
                pm = registry.meta(pid)
            except Exception:  # noqa: BLE001
                continue
            pos = (pm.position or "").upper()
            if pos not in _POS:
                continue
            team = rows.get(f"TEAM_{(pm.team or '').upper()}") or {}
            tm_snp = _f(r, "tm_off_snp")
            out.setdefault(pid, {"weeks": []})["weeks"].append({
                "week": wk,
                "snap": round(100 * _f(r, "off_snp") / tm_snp) if tm_snp else None,
                "tgt": int(_f(r, "rec_tgt")), "att": int(_f(r, "rush_att")),
                "tgt_sh": (round(100 * _f(r, "rec_tgt") / _f(team, "rec_tgt")) if _f(team, "rec_tgt") else None),
                "att_sh": (round(100 * _f(r, "rush_att") / _f(team, "rush_att")) if _f(team, "rush_att") else None),
                "rz": int(_f(r, "rec_rz_tgt") + _f(r, "rush_rz_att")),
                "opp": opportunity(r, ppr), "pts": _pts(r, scoring, weights)})
    for pid, p in out.items():
        ws = p["weeks"]
        last, prev = ws[-1], ws[-3:-1]
        p["snap"], p["opp"] = last["snap"], last["opp"]
        if prev:
            ps = [w["snap"] for w in prev if w["snap"] is not None]
            p["d_snap"] = (last["snap"] - round(sum(ps) / len(ps))) if (ps and last["snap"] is not None) else None
            p["d_opp"] = round(last["opp"] - sum(w["opp"] for w in prev) / len(prev), 1)
        else:
            p["d_snap"], p["d_opp"] = None, None
        l3 = ws[-3:]
        p["opp3"] = round(sum(w["opp"] for w in l3) / len(l3), 1)
        p["pts3"] = round(sum(w["pts"] for w in l3) / len(l3), 1)
        p["gap"] = round(p["opp3"] - p["pts3"], 1)
        p["n"] = len(ws)
        p["last_week"] = last["week"]
        # a real change of role, not a normal week's wobble: fifteen points of
        # snap share, or five opportunity points, on a workload that matters
        up = ((p["d_snap"] or 0) >= 15 or (p["d_opp"] or 0) >= 5) and last["opp"] >= 7
        down = (((p["d_snap"] or 0) <= -15 or (p["d_opp"] or 0) <= -5)
                and prev and (sum(w["opp"] for w in prev) / len(prev)) >= 8)
        p["trend"] = "up" if up and not down else "down" if down and not up else ""
    return out


def tag(p: Optional[dict]) -> str:
    """"snaps 48→71%" / "5.2 fewer opp pts" — the one line a row can carry."""
    if not p or not p.get("trend"):
        return ""
    sign = 1 if p["trend"] == "up" else -1
    # the line has to say the same thing the arrow does
    if p.get("d_snap") is not None and sign * p["d_snap"] >= 15:
        return f'snaps {p["snap"] - p["d_snap"]}→{p["snap"]}%'
    return f'workload {p["opp"] - p["d_opp"]:.0f}→{p["opp"]:.0f} pts'


def buys(profs: Dict[str, dict], pids, *, min_opp: float = 9.0, min_gap: float = 3.5) -> List[str]:
    """Players whose WORKLOAD is running ahead of their points: buy before the
    points arrive. Needs two played games in the window."""
    c = [p for p in map(str, pids) if p in profs and profs[p]["n"] >= 2
         and profs[p]["opp3"] >= min_opp and profs[p]["gap"] >= min_gap
         and profs[p]["pts3"] <= 0.7 * profs[p]["opp3"]]
    return sorted(c, key=lambda p: -profs[p]["gap"])


def sells(profs: Dict[str, dict], pids, *, min_pts: float = 10.0, min_gap: float = 4.5) -> List[str]:
    """Players scoring well past their workload: touchdowns and long plays that
    don't repeat. Sell while the points are on the board."""
    # ...and by half again, not just by a few points: the best players beat
    # their workload every week, and that is talent, not luck
    c = [p for p in map(str, pids) if p in profs and profs[p]["n"] >= 2
         and profs[p]["pts3"] >= min_pts and -profs[p]["gap"] >= min_gap
         and profs[p]["pts3"] >= 1.5 * profs[p]["opp3"]]
    return sorted(c, key=lambda p: profs[p]["gap"])
