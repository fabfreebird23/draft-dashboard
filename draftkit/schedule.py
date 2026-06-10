"""Playoff strength-of-schedule from real defense-vs-position data.

Two ingredients, both from Sleeper (so it works on Streamlit Cloud):
  • the upcoming season's schedule (who plays whom each week), and
  • last season's defense-vs-position — how many fantasy points each defense
    allowed to each position, computed from every player-game and cached.

We grade each player's fantasy-playoff weeks (15-17) by how generous their
opponents' defenses were to that position. Last season is final, so the DvP
table is cached effectively permanently.
"""
from __future__ import annotations

import json
import time
from typing import Dict

import requests

from . import config

_HEADERS = {"User-Agent": "draft-dashboard/1.0 (personal fantasy tool)"}
_SKILL = ("QB", "RB", "WR", "TE")
_PTS_KEY = {"ppr": "pts_ppr", "half": "pts_half_ppr", "std": "pts_std"}
PLAYOFF_WEEKS = (15, 16, 17)
_SCHED_TTL = 60 * 60 * 24 * 7
_DVP_TTL = 60 * 60 * 24 * 30          # prior season is final — refresh rarely


def load_schedule(season: int) -> Dict[str, Dict[int, str]]:
    """{team: {week: opponent}} for the season."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = config.DATA_DIR / f"sched_{season}.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < _SCHED_TTL:
        try:
            return json.loads(cache.read_text())
        except Exception:  # noqa: BLE001
            pass
    try:
        url = f"https://api.sleeper.com/schedule/nfl/regular/{season}"
        games = requests.get(url, headers=_HEADERS, timeout=15).json() or []
    except Exception:  # noqa: BLE001
        if cache.exists():
            return json.loads(cache.read_text())
        return {}
    sched: Dict[str, Dict[int, str]] = {}
    for g in games:
        h, a, wk = g.get("home"), g.get("away"), g.get("week")
        if h and a and wk:
            sched.setdefault(h, {})[str(wk)] = a
            sched.setdefault(a, {})[str(wk)] = h
    cache.write_text(json.dumps(sched))
    return sched


def load_dvp(prev_season: int, registry, scoring: str = "ppr") -> Dict[str, Dict[str, int]]:
    """{position: {def_team: rank}} where rank 1 = stingiest defense vs that
    position, 32 = most generous. Built from every 2025 player-game."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = config.DATA_DIR / f"dvp_{prev_season}.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < _DVP_TTL:
        try:
            return json.loads(cache.read_text())
        except Exception:  # noqa: BLE001
            pass
    key = _PTS_KEY.get(scoring, "pts_ppr")
    # points allowed: pos -> def_team -> total fantasy points conceded
    allowed: Dict[str, Dict[str, float]] = {p: {} for p in _SKILL}
    weeks_ok = 0
    for wk in range(1, 19):
        try:
            url = f"https://api.sleeper.com/stats/nfl/{prev_season}/{wk}?season_type=regular"
            rows = requests.get(url, headers=_HEADERS, timeout=20).json() or []
        except Exception:  # noqa: BLE001
            continue
        weeks_ok += 1
        for rec in rows:
            opp = rec.get("opponent")
            pid = rec.get("player_id")
            pts = (rec.get("stats") or {}).get(key)
            if not opp or pid is None or pts is None:
                continue
            pos = registry.meta(pid).position
            if pos in allowed:
                allowed[pos][opp] = allowed[pos].get(opp, 0.0) + float(pts)
    if not weeks_ok:
        if cache.exists():
            return json.loads(cache.read_text())
        return {}
    # rank each position's defenses: most points allowed → highest rank (easiest)
    dvp: Dict[str, Dict[str, int]] = {}
    for pos, teams in allowed.items():
        order = sorted(teams.items(), key=lambda x: x[1])      # ascending = stingiest first
        dvp[pos] = {team: i + 1 for i, (team, _) in enumerate(order)}
    cache.write_text(json.dumps(dvp))
    return dvp


def playoff_sos(team: str, pos: str, dvp: dict, schedule: dict):
    """Grade a player's fantasy-playoff slate (weeks 15-17). Returns
    (label, css_class, detail) or None. Higher opponent DvP rank = more generous
    defense = easier."""
    if not team or not pos or not dvp or not schedule:
        return None
    pos_dvp = dvp.get(pos)
    games = schedule.get(team, {})
    if not pos_dvp or not games:
        return None
    n_def = max(pos_dvp.values()) or 32
    ranks, opps = [], []
    for wk in PLAYOFF_WEEKS:
        opp = games.get(str(wk))
        if opp and opp in pos_dvp:
            ranks.append(pos_dvp[opp])
            opps.append((wk, opp, pos_dvp[opp]))
    if not ranks:
        return None
    avg = sum(ranks) / len(ranks)
    frac = avg / n_def                                          # 0 hard … 1 easy
    if frac >= 0.60:
        label, cls = "Easy playoff slate", "easy"
    elif frac <= 0.40:
        label, cls = "Hard playoff slate", "hard"
    else:
        label, cls = "Avg playoff slate", "avg"
    detail = " · ".join(f"Wk{wk} {opp}" for wk, opp, _ in opps)
    return (label, cls, f"Wks 15-17: {detail}")
