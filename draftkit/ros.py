"""Rest-of-season rankings from the panels we already read weekly.

Four sources have a rest-of-season board; Vegas doesn't (props are weekly):

  * FantasyPros — the ROS Expert Consensus (`ecr.ros`), overall + positional.
  * Flock — its REDRAFT board. In season Flock's analysts keep it current
    (eight of them, re-ranked within the day), which makes it their
    rest-of-season list; the weekly board is a different format.
  * The Ballers — Andy, Jason and Mike's ROS ranks, embedded in their
    rest-of-season rankings page as `window.tool.rosRankings.data`, per
    position, with each player's remaining games and ROS points.
  * Sleeper — its weekly projections for every remaining regular-season
    week, summed and scored with THIS league's settings. The only source that
    sees bye weeks and the number of games left.

`board()` lines them up per player and builds a consensus: positional ranks
averaged for a single position, and for FLEX each source re-ranked among
RB/WR/TE only first, so every source's numbers mean the same thing.
"""
from __future__ import annotations

import ast
import hashlib
import json
import time
from typing import Dict, Optional

import requests

from . import config, ecr, panels as P, projections as PJ, scoring as _sc
from .udk import _extract_json_array

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130 Safari/537.36"}
_FLOCK = "https://api.flockfantasy.com/rankings"
_FFB_ROS = "https://www.thefantasyfootballers.com/footclan/rest-of-season-rankings/"
SKILL = ("RB", "WR", "TE")
LAST_WEEK = 17                     # fantasy seasons end in week 17
_TTL = 6 * 3600


def _cache(name: str):
    p = config.DATA_DIR / "ros" / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _cached(name: str, ttl: int, fetch):
    p = _cache(name)
    if p.exists() and time.time() - p.stat().st_mtime < ttl:
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    try:
        out = fetch()
    except Exception:  # noqa: BLE001
        out = None
    if out:
        p.write_text(json.dumps(out))
        return out
    try:                         # stale beats empty
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _pos_num(pr) -> Optional[float]:
    s = "".join(ch for ch in str(pr or "") if ch.isdigit())
    return float(s) if s else None


# ------------------------------------------------------------- sources
def fantasypros(season: int, scoring: str, registry) -> Dict[str, dict]:
    out = {}
    for pid, r in (ecr.ros(season, scoring, registry) or {}).items():
        out[str(pid)] = {"ov": r.get("ecr"), "pr": _pos_num(r.get("pos_rank")),
                         "best": r.get("best"), "worst": r.get("worst"), "pos": r.get("pos")}
    return out


def flock(season: int, registry) -> Dict[str, dict]:
    def fetch():
        r = requests.get(_FLOCK, params={"format": "REDRAFT"},
                         headers={**_UA, "Origin": "https://flockfantasy.com"}, timeout=20)
        r.raise_for_status()
        d = r.json() or {}
        if int(d.get("year") or 0) != int(season):
            return {}
        return {"updated": max((d.get("lastUpdated") or {}).values(), default=""), "rows": d.get("data") or []}
    raw = _cached(f"flock_{season}", _TTL, fetch) or {}
    idx = P._index(registry)
    out = {}
    for x in raw.get("rows") or []:
        pid = P._pid_for(idx, x.get("playerName"), x.get("team"))
        if not pid:
            continue
        try:
            by = ast.literal_eval(x.get("positionalRanks") or "{}") if isinstance(
                x.get("positionalRanks"), str) else (x.get("positionalRanks") or {})
        except Exception:  # noqa: BLE001
            by = {}
        vals = sorted(v for v in by.values() if v)
        out[pid] = {"ov": x.get("averageRank"), "pr": x.get("averagePositionalRank"),
                    "best": vals[0] if vals else None, "worst": vals[-1] if vals else None,
                    "n": len(vals), "pos": x.get("position")}
    return out


def ballers(season: int, registry, weights=None) -> Dict[str, dict]:
    def fetch():
        r = requests.get(_FFB_ROS, headers=_UA, timeout=30)
        r.raise_for_status()
        t = r.text
        i = t.find("window.tool.rosRankings.data")
        if i < 0:
            return []
        rows = _extract_json_array('{"data":' + t[t.find("=", i) + 1:].lstrip(), "data") or []
        return [x for x in rows if str(x.get("season")) == str(season)]
    raw = _cached(f"ffb_{season}", _TTL, fetch) or []
    idx = P._index(registry)
    acc: Dict[str, dict] = {}
    names = {"1": "Andy", "2": "Jason", "3": "Mike"}
    for x in raw:
        if not str(x.get("type") or "").startswith("ros_"):
            continue
        pid = P._pid_for(idx, x.get("name"), x.get("team"))
        if not pid:
            continue
        a = acc.setdefault(pid, {"by": {}, "pts": [], "games": None, "pos": x.get("fantasy_position")})
        try:
            a["by"][names.get(str(x.get("analyst_id")), str(x.get("analyst_id")))] = float(x.get("rank"))
        except (TypeError, ValueError):
            continue
        # their ROS points are PPR; with the league's book, rescore their own
        # stat line for the remaining games (bonuses priced per game)
        lp = None
        if weights:
            line = {P._STAT_KEYS[k]: float(x[k]) for k in P._STAT_KEYS if x.get(k) not in (None, "")}
            # their ROS rows leave completions and carries at 0; a league that
            # pays for them (Kreeper: 0.25 a completion, 0.1 a carry) would see
            # every QB and back short. League-average yards per completion
            # (~11) and per carry (~4.3) stand in.
            if line.get("pass_yd") and not line.get("pass_cmp"):
                line["pass_cmp"] = line["pass_yd"] / 11.0
            if line.get("rush_yd") and not line.get("rush_att"):
                line["rush_att"] = line["rush_yd"] / 4.3
            if line:
                games = float(x.get("remaining_games") or 0) or None
                if games:
                    line["gp"] = games
                lp = _sc.points(line, weights)
        if lp is not None:
            a["pts"].append(lp)
        elif x.get("ros_fantasy_points") is not None:
            a["pts"].append(float(x["ros_fantasy_points"]))
        a["games"] = x.get("remaining_games") or a["games"]
    out = {}
    for pid, a in acc.items():
        v = sorted(a["by"].values())
        out[pid] = {"pr": sum(v) / len(v), "best": v[0], "worst": v[-1], "by": a["by"],
                    "pts": (sum(a["pts"]) / len(a["pts"])) if a["pts"] else None,
                    "games": a["games"], "pos": a["pos"]}
    return out


def sleeper(season: int, first_week: int, scoring: str, weights=None) -> Dict[str, dict]:
    """{pid: {pts, games}} — Sleeper's projections for weeks first..17, summed
    under this league's scoring. `games` counts weeks he's projected to play."""
    wkey = "_".join(f"{k}{v}" for k, v in sorted((weights or {}).items()))[:80] or scoring

    def fetch():
        tot: Dict[str, list] = {}
        for wk in range(int(first_week), LAST_WEEK + 1):
            for pid, v in (PJ.sleeper_week(season, wk, scoring, weights) or {}).items():
                t = tot.setdefault(str(pid), [0.0, 0])
                t[0] += float(v or 0)
                t[1] += 1 if (v or 0) > 0.5 else 0
        return {p: {"pts": round(t[0], 1), "games": t[1]} for p, t in tot.items()}
    return _cached(f"sleeper_{season}_{first_week}_{hashlib.sha1(wkey.encode()).hexdigest()[:10]}",
                   _TTL, fetch) or {}


# ---------------------------------------------------------------- board
SOURCES = ("fp", "flock", "ffb", "sleeper")
LABEL = {"fp": "FantasyPros", "flock": "Flock", "ffb": "The Ballers", "sleeper": "Sleeper proj"}


def board(season: int, week: int, scoring: str, registry, weights=None) -> Dict[str, dict]:
    """{pid: {pos, src: {source: {...}}}} — every player any source ranks."""
    data = {"fp": fantasypros(season, scoring, registry), "flock": flock(season, registry),
            "ffb": ballers(season, registry, weights), "sleeper": sleeper(season, week, scoring, weights)}
    out: Dict[str, dict] = {}
    for s, rows in data.items():
        for pid, r in rows.items():
            if s == "sleeper" and (r.get("pts") or 0) < 5:
                continue                      # Sleeper projects everyone; keep the relevant
            try:
                pos = (registry.meta(pid).position or "").upper()
            except Exception:  # noqa: BLE001
                pos = (r.get("pos") or "").upper()
            if pos not in ("QB", "RB", "WR", "TE"):
                continue
            out.setdefault(pid, {"pid": pid, "pos": pos, "src": {}})["src"][s] = r
    return out


def rank(rows: Dict[str, dict], pos: str) -> list:
    """Rows for one view, each with `r` = {source: rank on this view's scale}
    and `cons` = their mean. pos is a position, "FLEX" (RB/WR/TE against each
    other) or "ALL" (positional ranks, sorted by Sleeper's ROS points)."""
    if pos in ("FLEX", "ALL"):
        pool = [r for r in rows.values() if (r["pos"] in SKILL if pos == "FLEX" else True)]
    else:
        pool = [r for r in rows.values() if r["pos"] == pos]
    for r in pool:
        r["r"] = {}
    if pos == "FLEX":
        # each source re-ranked among RB/WR/TE so the numbers share a scale
        keyfns = {"fp": lambda s: s.get("ov"), "flock": lambda s: s.get("ov"),
                  "ffb": lambda s: -(s.get("pts") or 0) if s.get("pts") else None,
                  "sleeper": lambda s: -(s.get("pts") or 0) if s.get("pts") else None}
        for k, fn in keyfns.items():
            have = [(fn(r["src"][k]), r) for r in pool if k in r["src"] and fn(r["src"][k]) is not None]
            for i, (_v, r) in enumerate(sorted(have, key=lambda x: x[0]), 1):
                r["r"][k] = float(i)
    else:
        by_pos: Dict[str, list] = {}
        for r in pool:
            by_pos.setdefault(r["pos"], []).append(r)
        for _p, grp in by_pos.items():
            for k in ("fp", "flock", "ffb"):
                for r in grp:
                    v = (r["src"].get(k) or {}).get("pr")
                    if v is not None:
                        r["r"][k] = float(v)
            have = [r for r in grp if (r["src"].get("sleeper") or {}).get("pts")]
            for i, r in enumerate(sorted(have, key=lambda r: -r["src"]["sleeper"]["pts"]), 1):
                r["r"]["sleeper"] = float(i)
    for r in pool:
        vals = [v for v in r["r"].values()]
        r["cons"] = sum(vals) / len(vals) if vals else None
        r["n"] = len(vals)
        r["spread"] = (max(vals) - min(vals)) if len(vals) > 1 else None
        r["pts"] = (r["src"].get("sleeper") or {}).get("pts")
        r["games"] = (r["src"].get("sleeper") or {}).get("games")
    if pos == "ALL":
        pool = [r for r in pool if r["pts"]]
        pool.sort(key=lambda r: -r["pts"])
    else:
        # a man only one source ranks sorts behind the agreed-on, not above them
        pool = [r for r in pool if r["cons"] is not None]
        pool.sort(key=lambda r: (r["n"] < 2, r["cons"]))
    return pool
