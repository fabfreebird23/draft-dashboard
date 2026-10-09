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
PLAYOFF_WEEKS = (15, 16, 17)   # fallback only — see playoff_weeks()
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


def _allowed(season: int, weeks, registry, key: str):
    """(points, games): {pos: {def_team: fantasy points conceded}} and
    {pos: {def_team: games}} over the given weeks. One Sleeper stats read per week,
    each cached on disk — a finished week only changes with stat corrections."""
    pts: Dict[str, Dict[str, float]] = {p: {} for p in _SKILL}
    games: Dict[str, Dict[str, int]] = {p: {} for p in _SKILL}
    for wk in weeks:
        cache = config.DATA_DIR / f"stats_{season}_{wk}.json"
        rows = None
        if cache.exists() and (time.time() - cache.stat().st_mtime) < 3 * 86400:
            try:
                rows = json.loads(cache.read_text())
            except Exception:  # noqa: BLE001
                rows = None
        if rows is None:
            try:
                url = f"https://api.sleeper.com/stats/nfl/{season}/{wk}?season_type=regular"
                raw = requests.get(url, headers=_HEADERS, timeout=20).json() or []
                rows = [{"o": r.get("opponent"), "p": r.get("player_id"),
                         "s": {k: v for k, v in (r.get("stats") or {}).items() if k.startswith("pts_")}}
                        for r in raw if r.get("opponent") and r.get("player_id") is not None]
                if rows:
                    cache.write_text(json.dumps(rows))
            except Exception:  # noqa: BLE001
                rows = json.loads(cache.read_text()) if cache.exists() else []
        seen = set()
        for rec in rows or []:
            v = (rec.get("s") or {}).get(key)
            if v is None:
                continue
            pos = registry.meta(rec["p"]).position
            if pos in pts:
                pts[pos][rec["o"]] = pts[pos].get(rec["o"], 0.0) + float(v)
                if (pos, rec["o"]) not in seen:
                    seen.add((pos, rec["o"]))
                    games[pos][rec["o"]] = games[pos].get(rec["o"], 0) + 1
    return pts, games


def load_dvp_season(season: int, through_week: int, registry, scoring: str = "ppr"):
    """THIS season's defense-vs-position, from the weeks already played.

    ({position: {def_team: rank}}, label). Rank 1 = stingiest, 32 = most
    generous, by fantasy points allowed PER GAME (a defense that has had its bye
    has played one game fewer, so totals would flatter it).

    The draft screens use last season (`load_dvp`) because no games exist yet;
    in season that's the wrong question — a defense that lost its two best
    linebackers isn't last year's run defense. For the first two weeks there's
    too little to rank on, so last season counts as two games' worth of prior
    and fades out; from week 3 on it's this season alone.
    """
    key = _PTS_KEY.get(scoring, "pts_ppr")
    done = max(0, int(through_week))
    if done <= 0:
        return load_dvp(season - 1, registry, scoring), f"last season (no {season} games yet)"
    pts, games = _allowed(season, range(1, done + 1), registry, key)
    prior_w = 2.0 if done < 3 else 0.0
    if prior_w:
        ppts, pgames = _allowed(season - 1, range(1, 19), registry, key)
    dvp: Dict[str, Dict[str, int]] = {}
    for pos in _SKILL:
        per = {}
        teams = set(pts[pos]) | (set(ppts[pos]) if prior_w else set())
        for t in teams:
            g = games[pos].get(t, 0)
            tot = pts[pos].get(t, 0.0)
            if prior_w and pgames[pos].get(t):
                prior_pg = ppts[pos][t] / pgames[pos][t]
                per[t] = (tot + prior_pg * prior_w) / (g + prior_w)
            elif g:
                per[t] = tot / g
        order = sorted(per.items(), key=lambda x: x[1])
        dvp[pos] = {team: i + 1 for i, (team, _) in enumerate(order)}
    label = (f"{season} through week {done}" + (", blended with last season" if prior_w else ""))
    return dvp, label


def playoff_weeks(meta=None, settings=None) -> tuple:
    """The weeks THIS league actually plays its fantasy playoffs.

    Was hardcoded to (15, 16, 17), which is wrong for three of the four leagues
    here — Kreeper starts week 13 and B&B and 7 1/2 Men start week 14. Rating a
    player's "playoff schedule" against weeks he will not be playing is worse than
    not rating it, because it reads as information.

        Kreeper   start 13, 4 teams  -> 13, 14
        B&B       start 14, 4 teams  -> 14, 15
        7 1/2 Men start 14, 4 teams  -> 14, 15
        ESPN      reg season 14 wks, 6 teams -> 15, 16, 17

    Rounds are ceil(log2(playoff_teams)) — 4 teams is semis + final, 6 teams adds a
    wildcard round. ASSUMPTION: one week per round. Sleeper exposes
    `playoff_round_type` but its enum isn't documented reliably, and a window that
    is one week short beats one that is three weeks wrong.
    """
    import math
    st = settings or {}
    if meta is not None and not settings:
        st = getattr(meta, "playoff_settings", None) or {}
    start = st.get("start")
    teams = int(st.get("teams") or 0)
    if not start:
        return PLAYOFF_WEEKS
    rounds = max(1, math.ceil(math.log2(teams))) if teams > 1 else 1
    end = min(18, int(start) + rounds - 1)
    return tuple(range(int(start), end + 1))


def playoff_slate(team: str, pos: str, dvp: dict, schedule: dict, weeks=None):
    """Full fantasy-playoff picture (weeks 15-17) for the player card, rather than
    the one-line grade `playoff_sos` returns.

    {label, cls, frac, avg_rank, n_def, weeks: [(wk, opp, rank, hardness)]} or None.
    `rank` is the opponent's DvP rank against this position (1 = stingiest, 32 =
    most generous), so `hardness` = 1 - rank/n_def runs 0 (easy) … 1 (hard) and can
    drive a per-week bar. Beware the direction: a HIGH DvP rank is a GOOD matchup.

    NB DvP is built from LAST season's games — load_dvp's first arg is named
    prev_season for that reason. Passing the current season yields empty dicts and
    every slate silently grades as None, which is what made this feature look
    broken when it is in fact fine."""
    if not team or not pos or not dvp or not schedule:
        return None
    pos_dvp = dvp.get(pos)
    games = schedule.get(team, {})
    if not pos_dvp or not games:
        return None
    n_def = max(pos_dvp.values()) or 32
    wk_list = weeks or PLAYOFF_WEEKS
    weeks = []
    for wk in wk_list:
        opp = games.get(str(wk))
        if opp and opp in pos_dvp:
            rank = pos_dvp[opp]
            weeks.append((wk, opp, rank, 1.0 - (rank / n_def)))
    if not weeks:
        return None
    avg = sum(w[2] for w in weeks) / len(weeks)
    frac = avg / n_def                                          # 0 hard … 1 easy
    if frac >= 0.60:
        label, cls = "Easy playoff slate", "easy"
    elif frac <= 0.40:
        label, cls = "Hard playoff slate", "hard"
    else:
        label, cls = "Average playoff slate", "avg"
    return {"label": label, "cls": cls, "frac": frac, "avg_rank": avg,
            "n_def": n_def, "weeks": weeks}


def playoff_sos(team: str, pos: str, dvp: dict, schedule: dict, weeks=None):
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
    for wk in (weeks or PLAYOFF_WEEKS):
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
    span = f"Wks {opps[0][0]}-{opps[-1][0]}" if opps else "Playoffs"
    return (label, cls, f"{span}: {detail}")
