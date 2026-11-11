"""Monday: what actually happened, and who called it.

Advice nobody checks never gets better. Every finished week this grades two
things:

  THE SOURCES   For every startable player, what each source said he would
                score (its projection, or its rank read off the scale — see
                blend.to_points) against what he scored. The average miss per
                source is the grade, and the blend's weights follow it: a
                source that has been closest for a month counts for more.

  THE LINEUP    In one league: what the lineup he set scored, the best his
                roster could have scored, and what each source's lineup — and
                the blend's — would have scored on the same roster. Plus every
                place the blend disagreed with the lineup he set, and whether
                it was right.

A week's panels come from the daily snapshots (panels.snapshot_all), the last
one taken on or before that week's Sunday. Grades are kept in the doc store,
one document a season, so a cold start reads them in one round trip instead
of re-deriving a month of weeks.
"""
from __future__ import annotations

import datetime as _dt
import time
from typing import Dict, List, Optional

from . import blend as BL
from . import nflstats as NS

MAIN = ("sleeper", "fp", "flock", "ffb")
_MIN_PROJ = 6.0        # "startable": worth grading a projection on
_MIN_N = 40            # a week with fewer graded players than this isn't a grade
_GRADES: Dict[int, tuple] = {}
_GRADES_TTL = 900.0


def actuals(season: int, week: int, scoring: str = "ppr", weights=None) -> Dict[str, float]:
    """{pid: points} for everyone who played, under this scoring."""
    rows = NS.final(season, week)
    key = {"ppr": "pts_ppr", "half": "pts_half_ppr", "std": "pts_std"}.get(scoring, "pts_ppr")
    out = {}
    if weights:
        from . import scoring as SC
    for pid, r in rows.items():
        if pid.startswith("TEAM_") or not r.get("gp"):
            continue
        try:
            out[pid] = round(SC.points(r, weights), 2) if weights else float(r.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return out


def _sunday(season: int, week: int) -> Optional[str]:
    """YYYYMMDD (Eastern) of the week's Sunday — the last day a lineup could move."""
    try:
        from . import gametime as GT
        ks = sorted(g["kickoff"] for g in (GT.load_week(season, week, max_age=10 ** 9) or {}).values()
                    if g.get("kickoff"))
        if not ks:
            return None
        days = []
        for k in ks:
            t = _dt.datetime.fromisoformat(k.replace("Z", "+00:00")) - _dt.timedelta(hours=5)
            days.append(t)
        sun = [d for d in days if d.weekday() == 6]
        return (sun[-1] if sun else days[-1]).strftime("%Y%m%d")
    except Exception:  # noqa: BLE001
        return None


def snap_panels(season: int, week: int) -> dict:
    """{fp, flock, ffb, vegas} as they stood going into that week's games."""
    from . import panels as P
    cut = _sunday(season, week)
    out = {}
    for kind in ("fp", "flock", "ffb", "vegas"):
        try:
            days = P._snap_days(kind, season, week)
        except Exception:  # noqa: BLE001
            days = []
        if not days:
            out[kind] = {}
            continue
        ok = [d for d in days if not cut or d <= cut]
        day = ok[-1] if ok else days[0]
        try:
            out[kind] = P._snap_read(kind, season, week, day) or {}
        except Exception:  # noqa: BLE001
            out[kind] = {}
    return out


def source_points(base: Dict[str, float], season: int, week: int, registry,
                  weights=None) -> Dict[str, Dict[str, float]]:
    """{source: {pid: points}} for a past week, plus "blend"."""
    by = BL.to_points(base, snap_panels(season, week), registry)
    proj, _d = BL.combine(by, weights)
    for pid, v in (base or {}).items():
        proj.setdefault(str(pid), float(v or 0))
    by["blend"] = proj
    return by


def grade(by_src: Dict[str, Dict[str, float]], actual: Dict[str, float], registry) -> dict:
    """{src: {mae, n}} over startable players who played; "common" = the same
    players for every main source, so no source is graded on an easier list."""
    base = by_src.get("sleeper") or {}
    pool = []
    for pid, b in base.items():
        if b >= _MIN_PROJ and pid in actual and BL._pos(registry, pid) in ("QB", "RB", "WR", "TE"):
            pool.append(pid)
    common = [p for p in pool if all(p in (by_src.get(s) or {}) for s in MAIN if by_src.get(s))]
    out = {"n": len(common), "src": {}}
    for s, d in by_src.items():
        own = [p for p in (common if s in MAIN or s == "blend" else pool) if p in d]
        if not own:
            continue
        out["src"][s] = {"mae": round(sum(abs(d[p] - actual[p]) for p in own) / len(own), 3), "n": len(own)}
    return out


# ------------------------------------------------------------------ the record
def _doc_key(season: int) -> str:
    return f"grades_{season}"


def grades(season: int) -> Dict[str, dict]:
    """{"<week>": grade} for every week graded so far (memoised 15 min)."""
    hit = _GRADES.get(season)
    if hit and time.time() - hit[0] < _GRADES_TTL:
        return hit[1]
    try:
        from . import storage as S
        d = S.load_doc("review", _doc_key(season), {}) or {}
    except Exception:  # noqa: BLE001
        d = {}
    _GRADES[season] = (time.time(), d)
    return d


def ensure(season: int, week: int, registry, max_new: int = 8) -> Dict[str, dict]:
    """Grade any finished week (before `week`) that isn't graded yet, and save.
    The slow part — a week's box score, projections and snapshots — so it runs
    in the warmer and on the Review page, never inside a projection read."""
    from . import projections as PJ
    have = dict(grades(season))
    new = 0
    for wk in range(int(week) - 1, 0, -1):
        if str(wk) in have or new >= max_new:
            continue
        try:
            act = actuals(season, wk, "ppr")
            base = {str(k): float(v or 0) for k, v in (PJ.sleeper_week(season, wk, "ppr") or {}).items()}
            if not act or not base:
                continue
            g = grade(source_points(base, season, wk, registry), act, registry)
        except Exception:  # noqa: BLE001
            continue
        if g["n"] >= _MIN_N:
            have[str(wk)] = g
            new += 1
    if new:
        try:
            from . import storage as S
            S.save_doc("review", _doc_key(season), have)
        except Exception:  # noqa: BLE001
            pass
        _GRADES[season] = (time.time(), have)
    return have


def table(season: int, week: int, last: int = 6) -> dict:
    """{src: {mae, weeks}} averaged over the last `last` graded weeks before `week`."""
    g = grades(season)
    wks = sorted((int(k) for k in g if int(k) < int(week)), reverse=True)[:last]
    out = {}
    for s in BL.SOURCES + ("blend",):
        vals = [g[str(w)]["src"][s]["mae"] for w in wks if s in (g[str(w)].get("src") or {})]
        if vals:
            out[s] = {"mae": round(sum(vals) / len(vals), 2), "weeks": len(vals)}
    return out


def weights(season: int, week: int, registry=None) -> Optional[Dict[str, float]]:
    """Blend weights from the record: 1/miss², the four main sources averaging
    1.0, each held between 0.6 and 1.5 so one hot month can't take over. None
    until three weeks are graded. Vegas keeps its half weight, scaled the same."""
    t = table(season, week)
    main = {s: t[s] for s in MAIN if s in t and t[s]["weeks"] >= 3}
    if len(main) < 3:
        return None
    raw = {s: 1.0 / max(0.5, v["mae"]) ** 2 for s, v in main.items()}
    mean = sum(raw.values()) / len(raw)
    out = {s: round(min(1.5, max(0.6, r / mean)), 3) for s, r in raw.items()}
    if "vegas" in t and t["vegas"]["weeks"] >= 3:
        out["vegas"] = round(0.5 * min(1.5, max(0.6, (1.0 / max(0.5, t["vegas"]["mae"]) ** 2) / mean)), 3)
    return out


# ------------------------------------------------------------- one league's week
class _View:
    __slots__ = ("_p",)

    def __init__(self, p):
        self._p = p

    def proj_of(self, pid):
        return float(self._p.get(str(pid)) or 0.0)


def lineup_review(hist: dict, slots, base: Dict[str, float], season: int, week: int, registry,
                  weights_=None) -> Optional[dict]:
    """One finished week of one team.

    `hist` = {"starters": [pid], "players": [pid], "points": {pid: pts}} (the
    league's own scoring). Returns {set, best, left, should_start[(pid, pts)],
    should_sit[(pid, pts)], lineups{src: pts}, calls[{start, sit, right, swing}]}.
    """
    from . import grades as GR
    pts = {str(k): float(v or 0) for k, v in (hist.get("points") or {}).items()}
    players = [str(p) for p in (hist.get("players") or [])]
    starters = [str(p) for p in (hist.get("starters") or []) if p and str(p) != "0"]
    if not pts or not players:
        return None
    set_pts = round(sum(pts.get(p, 0.0) for p in starters), 1)
    best_pids, best = GR.optimal_lineup(players, slots, registry, _View(pts))
    best_pids = [str(p) for p in best_pids]
    by = source_points(base, season, week, registry, weights_)
    lineups, picks = {}, {}
    for s, d in by.items():
        if not d:
            continue
        # a source with no number for a man falls back to the base for him
        val = {p: d.get(p, by["sleeper"].get(p, 0.0)) for p in players}
        ids, _ = GR.optimal_lineup(players, slots, registry, _View(val))
        ids = [str(p) for p in ids]
        picks[s] = ids
        lineups[s] = round(sum(pts.get(p, 0.0) for p in ids), 1)
    # where the blend would have differed from the lineup he set, man for man
    calls = []
    bl = picks.get("blend") or []
    ins = [p for p in bl if p not in starters]
    outs = [p for p in starters if p not in bl]
    pos = lambda p: BL._pos(registry, p)  # noqa: E731
    for i in ins:
        o = next((x for x in outs if pos(x) == pos(i)), None) or (outs[0] if outs else None)
        if o is None:
            continue
        outs.remove(o)
        swing = round(pts.get(i, 0.0) - pts.get(o, 0.0), 1)
        calls.append({"start": i, "sit": o, "swing": swing, "right": swing > 0})
    return {"week": week, "set": set_pts, "best": round(best, 1), "left": round(max(0.0, best - set_pts), 1),
            "should_start": sorted(((p, pts.get(p, 0.0)) for p in best_pids if p not in starters),
                                   key=lambda x: -x[1]),
            "should_sit": sorted(((p, pts.get(p, 0.0)) for p in starters if p not in best_pids),
                                 key=lambda x: x[1]),
            "lineups": lineups, "calls": calls}


def pickups(adds: List[dict], hist: Dict[int, dict]) -> List[dict]:
    """What each add has done since: `adds` = [{pid, week, bid, type}], `hist`
    = {week: {starters, players, points}}. Points count only while rostered."""
    out = []
    for a in adds:
        pid, wk0 = str(a["pid"]), int(a["week"])
        tot = started = weeks = starts = 0.0
        for wk, d in sorted(hist.items()):
            if wk < wk0 or pid not in [str(p) for p in d.get("players") or []]:
                continue
            p = float((d.get("points") or {}).get(pid) or 0)
            weeks += 1
            tot += p
            if pid in [str(x) for x in d.get("starters") or []]:
                starts += 1
                started += p
        out.append(dict(a, weeks=int(weeks), starts=int(starts), total=round(tot, 1),
                        started=round(started, 1)))
    return out
