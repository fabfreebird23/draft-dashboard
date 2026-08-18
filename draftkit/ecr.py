"""FantasyPros weekly + rest-of-season Expert Consensus Rankings.

Why this exists when we already have projections: a projection is one model's
point estimate, and it cannot tell you whether the call is close. ECR ships the
*spread* — `rank_min`, `rank_max`, `rank_std` across the panel — so "start Waddle
over Olave" can be labelled a coin flip when the experts are split and a genuine
mistake when they are not. That is the only number on the start/sit screen that
knows the difference, and it is the reason to pull this at all.

It also ships two things we had no source for:

  * ``owned_avg`` — percent rostered across the major sites. On the waiver board
    that is the market's urgency signal: a 3%-rostered breakout is a free add,
    a 60%-rostered one is a bidding war you may already have lost.
  * rest-of-season ranks — the right currency for trades. Weekly projections
    price a man on bye at zero, which is how a trade analyser talks you into
    selling a stud in his week 7 bye.

No login. These pages are public and server-render the whole panel into a
``var ecrData = {...}`` blob (the same mechanism ``rank_sources`` already reads
for draft cheat sheets), so a subscription buys nothing here except two extra
experts and custom weighting. Verified live: weekly QB/FLEX/K/DST and ROS all
return 8-10 experts with min/max/std intact.

A future week is not an error — FantasyPros publishes a week when its experts
have ranked it, so ``?week=12`` in August returns an empty players array. That
case returns {} and the callers show nothing rather than inventing a rank.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional

from . import config
from .adp.base import http_get
from .names import normalize_name
from .rank_sources import _extract_ecr_players

_BASE = "https://www.fantasypros.com/nfl/rankings/"

# Scoring prefix. FantasyPros spells standard as no prefix at all.
_PRE = {"ppr": "ppr-", "half": "half-point-ppr-", "std": ""}

# FLEX carries RB+WR+TE ranked against each other, which is a BETTER answer than
# three separate pages: the FLEX decision is inherently cross-position, and three
# per-position lists cannot be compared to each other.
_WEEKLY_PAGES = ("flex", "qb", "k", "dst")

# ...but FantasyPros omits start_sit_grade from the FLEX page (present on every
# per-position page, absent on all 255 FLEX rows — checked, not assumed). So the
# rank comes from FLEX and the grade is overlaid from rb/wr/te. Neither page alone
# gives both, and dropping the grade would throw away the one field that is a
# recommendation rather than an ordering.
_GRADE_PAGES = ("rb", "wr", "te")

# K and DST have no scoring variants — one panel, whatever your league does.
_NO_SCORING = {"qb", "k", "dst"}

_TTL = 60 * 60 * 3  # 3h — these move on practice reports, not on a schedule


def _url(page: str, scoring: str, week: Optional[int]) -> str:
    pre = "" if page in _NO_SCORING else _PRE.get(scoring, "ppr-")
    u = f"{_BASE}{pre}{page}.php"
    return f"{u}?week={week}" if week else u


def _ros_url(scoring: str) -> str:
    return f"{_BASE}ros-{_PRE.get(scoring, 'ppr-')}overall.php"


def _cache(kind: str, season: int, scoring: str, week) -> Path:
    return config.DATA_DIR / f"ecr_{kind}_{season}_{scoring}_{week or 0}.json"


def _fresh(p: Path) -> Optional[dict]:
    try:
        if p.exists() and (time.time() - p.stat().st_mtime) < _TTL:
            return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        pass
    return None


def _stale(p: Path) -> Optional[dict]:
    """Yesterday's consensus beats no consensus — the screen degrades to slightly
    old rather than to a blank column."""
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:  # noqa: BLE001
        return None


def _num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _row(p: dict, scale: str) -> dict:
    return {
        # WHICH LIST this rank came from. FantasyPros ranks QBs 1-35 on the QB
        # page and RB/WR/TE 1-255 on the FLEX page, so `ecr` values from different
        # pages are NOT comparable — sorting a mixed list by it puts every
        # startable quarterback above every running back alive, which is exactly
        # what the waiver board did until this field existed.
        "scale": scale,
        "name": p.get("player_name") or "",
        "team": p.get("player_team_id") or "",
        "pos": p.get("player_position_id") or "",
        "ecr": _num(p.get("rank_ecr")),
        "best": _num(p.get("rank_min")),
        "worst": _num(p.get("rank_max")),
        "avg": _num(p.get("rank_ave")),
        "std": _num(p.get("rank_std")),
        "pos_rank": p.get("pos_rank") or "",
        "grade": (p.get("start_sit_grade") or "") or "",
        "owned": _num(p.get("player_owned_avg")),
        "opp": (p.get("player_opponent") or "").replace("vs. ", "vs ").strip(),
        "note": (p.get("note") or "") if p.get("note") not in (None, "None") else "",
    }


def _harvest(pages, registry) -> Dict[str, dict]:
    """{pid: row}. Keyed by our pid, so callers never see a FantasyPros id.

    Name collisions are resolved by TEAM, because the alternative — first match
    wins — silently hands one Josh Allen the other's rank, and a start/sit screen
    that names the wrong man is worse than one with a gap in it.
    """
    idx: Dict[str, list] = {}
    for nm, p in registry.by_norm.items():
        if p.sleeper_pid:
            idx.setdefault(nm, []).append(p)
    out: Dict[str, dict] = {}
    for scale, players in pages:
        for raw in players or []:
            r = _row(raw, scale)
            cands = idx.get(normalize_name(r["name"])) or []
            if not cands:
                continue
            pick = cands[0]
            if len(cands) > 1:
                same = [c for c in cands
                        if (getattr(c, "team", "") or "").upper() == r["team"].upper()]
                if len(same) != 1:
                    continue  # ambiguous — say nothing rather than guess
                pick = same[0]
            pid = str(pick.sleeper_pid)
            # FLEX ranks RB/WR/TE against each other and the per-position pages do
            # not; keep whichever we saw first (FLEX leads _WEEKLY_PAGES) so the
            # numbers on one screen are all from one list.
            out.setdefault(pid, r)
    return out


def weekly(season: int, week: int, scoring: str, registry) -> Dict[str, dict]:
    """{pid: row} for one week, or {} if that week isn't ranked yet."""
    cp = _cache("wk", season, scoring, week)
    hit = _fresh(cp)
    if hit is not None:
        return hit
    def _pull(page):
        try:
            return _extract_ecr_players(http_get(_url(page, scoring, week)).text)
        except Exception:  # noqa: BLE001 — one dead page must not blank the rest
            return []

    pages = [(p_, _pull(p_)) for p_ in _WEEKLY_PAGES]
    if not any(pl for _sc, pl in pages):
        return _stale(cp) or {}
    out = _harvest(pages, registry)
    for pid, r in _harvest([(p_, _pull(p_)) for p_ in _GRADE_PAGES], registry).items():
        if r.get("grade") and pid in out:
            out[pid]["grade"] = r["grade"]
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(out))
    except Exception:  # noqa: BLE001
        pass
    return out


def ros(season: int, scoring: str, registry) -> Dict[str, dict]:
    """{pid: row} rest-of-season. One page, all positions, ~420 deep."""
    cp = _cache("ros", season, scoring, 0)
    hit = _fresh(cp)
    if hit is not None:
        return hit
    try:
        players = _extract_ecr_players(http_get(_ros_url(scoring)).text)
    except Exception:  # noqa: BLE001
        players = []
    if not players:
        return _stale(cp) or {}
    out = _harvest([("all", players)], registry)
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(out))
    except Exception:  # noqa: BLE001
        pass
    return out


# ------------------------------------------------------------------ judgements
def spread(row: dict) -> float:
    """Width of the panel's band, in ranks. Shown raw, deliberately.

    The first version normalised this to a 0-1 "controversy" score and rated
    Jayden Daniels (band 5-11) as MORE contested than Malik Nabers (band 54-96),
    because dividing by rank rewards being ranked high. There is no honest single
    number here — "54th to 96th" says it plainly and needs no threshold.
    """
    if not row:
        return 0.0
    lo, hi = row.get("best"), row.get("worst")
    return float(hi - lo) if (lo is not None and hi is not None) else 0.0


def band(row: dict) -> str:
    lo, hi = (row or {}).get("best"), (row or {}).get("worst")
    return f"{lo:.0f}–{hi:.0f}" if (lo is not None and hi is not None) else ""


def verdict(start_row: dict, bench_row: dict) -> Optional[str]:
    """Does the panel back swapping `bench_row` in for `start_row`?

    Returns "agree" / "split" / "against", or None when either man is unranked.
    The point is not to overrule the projection — it is to say how much of a
    limb you are out on. `best`/`worst` are the panel's extremes, so an overlap
    IS the disagreement, no p-values required.
    """
    if not start_row or not bench_row:
        return None
    # Two ranks from two different lists are two different units. A QB's "12" and
    # a receiver's "12" are not the same twelve, and there is no honest way to
    # convert — so this says nothing rather than something wrong.
    if start_row.get("scale") != bench_row.get("scale"):
        return None
    a, b = start_row.get("ecr"), bench_row.get("ecr")
    if a is None or b is None:
        return None
    if b < a:  # panel already ranks the bench man higher
        return "agree"
    lo_b, hi_a = bench_row.get("best"), start_row.get("worst")
    if lo_b is not None and hi_a is not None and lo_b <= hi_a:
        return "split"
    return "against"
