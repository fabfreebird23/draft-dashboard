"""A projected NEXT-SEASON ADP — what a keeper actually costs against.

A keeper's ADP option ("up 3 rounds or ADP, whichever is better") is priced
against next summer's draft, and nobody publishes that until next summer. The
Draft Room was using THIS season's preseason ADP, frozen in August — Breece
Hall at 39.4 when the market has moved since.

The projection comes from FantasyCalc, whose values are built from real
trades between managers, keyed by Sleeper id:

  * dynasty value — what a player is worth across seasons. It keeps a player
    on IR or out for the year at his real value, which every rest-of-season
    list drops to nothing.
  * redraft value — what he is worth for the rest of THIS season.

Next summer's ADP is a one-season price set after this season's results, so it
sits between the two: the projection averages them. A player whose redraft
value has collapsed while his dynasty value holds — out for the season, on IR
— is priced on dynasty alone, which is exactly the case the rest-of-season
boards get wrong.

Ranks are rescaled to the market's draft pool (overall, QB/RB/WR/TE), so a
projected rank reads like an ADP and divides into rounds the same way.
"""
from __future__ import annotations

import json
import time
from typing import Dict

import requests

from . import config, sleeper_client as api

_URL = "https://api.fantasycalc.com/values/current"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130 Safari/537.36"}
_TTL = 12 * 3600
# season-long designations; a plain "Out" is often one week
_LONG = {"IR", "PUP", "NFI", "DNR"}
_OUT = {"Out", "OUT", "Sus", "SUS"}


def _fetch(n_teams: int, ppr: float) -> list:
    p = config.DATA_DIR / "nextyear" / f"fc_dyn_{n_teams}_{ppr}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and time.time() - p.stat().st_mtime < _TTL:
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    try:
        r = requests.get(_URL, params={"isDynasty": "true", "numQbs": 1, "numTeams": int(n_teams),
                                       "ppr": ppr}, headers=_UA, timeout=20)
        r.raise_for_status()
        rows = r.json() or []
        if rows:
            p.write_text(json.dumps(rows))
            return rows
    except Exception:  # noqa: BLE001
        pass
    try:
        return json.loads(p.read_text()) if p.exists() else []
    except Exception:  # noqa: BLE001
        return []


def projected(n_teams: int = 10, ppr: float = 1.0) -> Dict[str, dict]:
    """{sleeper_pid: {rank, value, dyn_rank, redraft, dynasty, injured, basis}}."""
    rows = _fetch(n_teams, ppr)
    if not rows:
        return {}
    try:
        players = api.get_players() or {}
    except Exception:  # noqa: BLE001
        players = {}
    out = {}
    for x in rows:
        p = x.get("player") or {}
        pid = str(p.get("sleeperId") or "")
        if not pid or (p.get("position") or "").upper() not in ("QB", "RB", "WR", "TE"):
            continue
        dyn = float(x.get("value") or 0)
        red = float(x.get("redraftValue") or 0)
        inj = (players.get(pid) or {}).get("injury_status") or ""
        # On IR / PUP, or listed Out with a redraft price that has collapsed
        # while the dynasty price holds (out for the year, not for the week):
        # next year is the dynasty number. A healthy young player with a low
        # redraft price is NOT this — his dynasty premium is his age — so he
        # gets the ordinary blend.
        collapsed = dyn > 0 and red < 0.45 * dyn
        injured = inj in _LONG or (inj in _OUT and collapsed)
        val = dyn if injured or not red else 0.5 * dyn + 0.5 * red
        out[pid] = {"value": val, "dynasty": dyn, "redraft": red, "dyn_rank": x.get("overallRank"),
                    "injured": injured, "status": inj,
                    "basis": "dynasty (out / IR)" if injured else "dynasty + redraft"}
    for i, (pid, r) in enumerate(sorted(out.items(), key=lambda kv: -kv[1]["value"]), 1):
        r["rank"] = i
    return out


def rank_lookup(registry, n_teams: int = 10, ppr: float = 1.0):
    """A drop-in for the context's `adp_rank(name, position)`: projected
    next-season rank by name, falling back to None (the caller then uses this
    season's ADP) for anyone FantasyCalc doesn't price."""
    from .names import normalize_name
    proj = projected(n_teams, ppr)
    by_name: Dict[str, int] = {}
    by_name_pos: Dict[str, int] = {}
    for pid, r in proj.items():
        try:
            pm = registry.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        if not getattr(pm, "name", None):
            continue
        k = normalize_name(pm.name)
        by_name.setdefault(k, r["rank"])
        by_name_pos[f"{k}|{(pm.position or '').lower()}"] = r["rank"]

    def lookup(name: str, position: str = ""):
        k = normalize_name(name or "")
        if position and f"{k}|{position.lower()}" in by_name_pos:
            return by_name_pos[f"{k}|{position.lower()}"]
        return by_name.get(k)
    return lookup
