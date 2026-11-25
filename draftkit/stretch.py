"""The stretch run: every player, every week from now through the playoffs.

The weekly screens answer "who starts THIS week". In November the question
that wins a league is a different one — who do I want on my roster for the
three or four weeks that decide it, and who on the wire is worth a spot now
because his weeks 14–16 are good. That needs every player's projection for
each of those weeks, against his opponent that week, with byes as zeros.

Sleeper publishes a projection for every remaining week (all positions,
kickers and defenses included), opponent-aware: a receiver's week-15 number
already knows who he is playing. So this reads one list per week, scores it
under the league's own book, and keeps the opponent beside each number.

Nothing here touches Streamlit; the page and the warmer both call it.
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

import requests

from . import config

_BASE = "https://api.sleeper.com/projections/nfl/{season}/{week}?season_type=regular&position[]={pos}&order_by=pts_ppr"
_UA = {"User-Agent": "draft-dashboard/1.0 (personal fantasy tool)"}
_POS = ("QB", "RB", "WR", "TE", "K", "DEF")
_TTL = 3 * 3600
_MEM: Dict[tuple, tuple] = {}
_PTS = {"ppr": "pts_ppr", "half": "pts_half_ppr", "std": "pts_std"}


def _raw(season: int, week: int) -> Dict[str, dict]:
    """{pid: {"s": stats, "opp": team, "team": team}} for one week, all positions.
    Cached on disk for three hours (projections move with news, not by the minute)."""
    k = (int(season), int(week))
    hit = _MEM.get(k)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    cp = config.DATA_DIR / f"stretch_{season}_w{week}.json"
    try:
        if cp.exists() and time.time() - cp.stat().st_mtime < _TTL:
            out = json.loads(cp.read_text())
            _MEM[k] = (time.time(), out)
            return out
    except Exception:  # noqa: BLE001
        pass
    out: Dict[str, dict] = {}
    try:
        from concurrent.futures import ThreadPoolExecutor

        def one(pos):
            r = requests.get(_BASE.format(season=season, week=week, pos=pos), headers=_UA, timeout=20)
            r.raise_for_status()
            return r.json() or []
        with ThreadPoolExecutor(len(_POS)) as ex:
            for rows in ex.map(one, _POS):
                for x in rows:
                    pid = str(x.get("player_id") or "")
                    st = x.get("stats") or {}
                    if pid and st:
                        out[pid] = {"s": st, "opp": x.get("opponent") or "", "team": x.get("team") or ""}
    except Exception:  # noqa: BLE001
        out = {}
    if out:
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(out))
        except Exception:  # noqa: BLE001
            pass
    elif cp.exists():
        try:
            out = json.loads(cp.read_text())
        except Exception:  # noqa: BLE001
            out = {}
    _MEM[k] = (time.time(), out)
    return out


def week(season: int, wk: int, weights: Optional[dict] = None, scoring: str = "ppr") -> Dict[str, dict]:
    """{pid: {"pts", "opp", "team"}} for one future week under this league's scoring.
    A team on bye simply has no rows that week."""
    key = _PTS.get(scoring, "pts_ppr")
    out = {}
    if weights:
        from . import scoring as SC
    for pid, r in _raw(season, wk).items():
        st = r["s"]
        pts = None
        if weights:
            try:
                pts = SC.points(st, weights)
            except Exception:  # noqa: BLE001
                pts = None
            # a book with no kicker/defense keys would score them zero —
            # Sleeper's own number is closer than nothing
            if not pts and st.get(key):
                pts = None
        if pts is None:
            v = st.get(key, st.get("pts_ppr"))
            try:
                pts = float(v or 0)
            except (TypeError, ValueError):
                pts = 0.0
        out[pid] = {"pts": round(float(pts), 1), "opp": r["opp"], "team": r["team"]}
    return out


def weeks(season: int, wks, weights=None, scoring: str = "ppr") -> Dict[int, Dict[str, dict]]:
    return {int(w): week(season, int(w), weights, scoring) for w in wks}


def board(by_week: Dict[int, Dict[str, dict]], pids=None) -> Dict[str, dict]:
    """{pid: {"wk": {week: {pts, opp}}, "total", "avg", "byes": [week]}}.
    A week he isn't in the list for is a bye (or an injury Sleeper has zeroed)."""
    pool = set(map(str, pids)) if pids is not None else set().union(*[set(d) for d in by_week.values()] or [set()])
    out = {}
    for pid in pool:
        wk = {}
        for w, d in by_week.items():
            r = d.get(pid)
            wk[w] = {"pts": r["pts"], "opp": r["opp"]} if r else {"pts": 0.0, "opp": ""}
        tot = sum(v["pts"] for v in wk.values())
        out[pid] = {"wk": wk, "total": round(tot, 1), "avg": round(tot / max(1, len(wk)), 1),
                    "byes": [w for w, v in wk.items() if not v["opp"]]}
    return out


def lineup_by_week(pids, slots, by_week, registry) -> Dict[int, dict]:
    """{week: {"pts", "starters": [pid]}} — the best lineup this roster can set
    each week, from that week's projections (byes and all)."""
    from . import grades

    class _V:
        __slots__ = ("p",)

        def __init__(self, p):
            self.p = p

        def proj_of(self, pid):
            r = self.p.get(str(pid))
            return float(r["pts"]) if r else 0.0
    out = {}
    for w, d in by_week.items():
        ids, pts = grades.optimal_lineup([str(p) for p in pids], slots, registry, _V(d))
        out[w] = {"pts": round(pts, 1), "starters": [str(p) for p in ids]}
    return out


def pickups(mine, slots, by_week, registry, candidates, *, playoff=None, limit: int = 12) -> List[dict]:
    """Free agents ranked by what they add to YOUR best lineup over these weeks.

    `candidates` = pids to try. Each is added to the roster and every week's
    best lineup re-scored; the gain is the sum (playoff weeks only, when
    `playoff` names them, else every week). A man who only starts in week 16
    still counts — that is the point of looking ahead.
    [{pid, gain, by_week{w: gain}, starts, total}]"""
    from . import weekly as W
    mine = [str(p) for p in mine]
    wks = sorted(by_week)
    count = [w for w in wks if not playoff or w in playoff]
    base = {}
    views = {}
    for w in wks:
        views[w] = {pid: r["pts"] for pid, r in by_week[w].items()}
        base[w] = W.fast_score(mine, slots, views[w], registry)
    out = []
    for c in candidates:
        c = str(c)
        if c in mine:
            continue
        g = {}
        for w in wks:
            if not views[w].get(c):
                g[w] = 0.0
                continue
            g[w] = round(max(0.0, W.fast_score(mine + [c], slots, views[w], registry) - base[w]), 1)
        gain = sum(g[w] for w in count)
        if gain < 0.5:
            continue
        out.append({"pid": c, "gain": round(gain, 1), "by_week": g,
                    "starts": sum(1 for w in count if g[w] >= 0.5),
                    "total": round(sum(views[w].get(c, 0.0) for w in count), 1)})
    out.sort(key=lambda r: -r["gain"])
    return out[:limit]


def team_strength(rosters: Dict[str, list], slots, by_week, registry, weeks_=None) -> Dict[str, float]:
    """{owner: average best-lineup points over these weeks} — who has the
    strongest playoff roster, not the strongest roster today."""
    out = {}
    for o, pids in rosters.items():
        lb = lineup_by_week(pids, slots, {w: d for w, d in by_week.items() if not weeks_ or w in weeks_}, registry)
        out[o] = round(sum(v["pts"] for v in lb.values()) / max(1, len(lb)), 1)
    return out
