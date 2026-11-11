"""Injury designations that are minutes old, not a day old.

Sleeper's player map — where every status in the app came from — is 5 MB and
refreshed once a day. That is fine on a Wednesday and wrong on a Sunday: a man
ruled out at 11:30 was still "Questionable" here until the next morning.

ESPN publishes the whole league's injury report in one small call. This reads
it (ten-minute cache) and lays it over the registry IN PLACE, so every screen
that reads `registry.meta(pid).injury_status` gets the fresh designation with
no other change:

    Questionable / Doubtful / Out      set as given
    Injured Reserve                    "IR"
    Active                             clears a Questionable / Doubtful / Out
                                       (never an IR, PUP or suspension — those
                                       aren't this report's to clear)
"""
from __future__ import annotations

import time
from typing import Dict, Optional

import requests

from .names import normalize_name

_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_TTL = 600.0
_MEM = {"at": 0.0, "rows": {}, "stamp": ""}
_TEAM = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR"}
_MAP = {"questionable": "Questionable", "doubtful": "Doubtful", "out": "Out",
        "injured reserve": "IR", "active": ""}
_SOFT = {"QUESTIONABLE", "DOUBTFUL", "OUT"}


def report(max_age: float = _TTL) -> Dict[tuple, dict]:
    """{(normalised name, team): {status, date}} — the league's report now.
    Never raises; a failed call keeps the last good copy."""
    if _MEM["rows"] and time.time() - _MEM["at"] < max_age:
        return _MEM["rows"]
    try:
        r = requests.get(_URL, headers=_UA, timeout=12)
        r.raise_for_status()
        d = r.json() or {}
    except Exception:  # noqa: BLE001
        _MEM["at"] = time.time() - max_age + 60      # try again in a minute, not every call
        return _MEM["rows"]
    rows = {}
    for t in d.get("injuries") or []:
        for i in t.get("injuries") or []:
            a = i.get("athlete") or {}
            st = _MAP.get(str(i.get("status") or "").strip().lower())
            if st is None or not a.get("displayName"):
                continue
            team = ((a.get("team") or {}).get("abbreviation") or "").upper()
            rows[(normalize_name(a["displayName"]), _TEAM.get(team, team))] = {
                "status": st, "date": i.get("date") or ""}
    if rows:
        _MEM.update(at=time.time(), rows=rows, stamp=str(d.get("timestamp") or time.time()))
    return _MEM["rows"]


def age_minutes() -> Optional[int]:
    """How old the report in hand is, for the line that says so."""
    return int((time.time() - _MEM["at"]) / 60) if _MEM["at"] and _MEM["rows"] else None


def apply(registry, max_age: float = _TTL) -> int:
    """Lay the fresh report over the registry in place. Returns how many
    designations changed. Cheap to call on every gather: the fetch is cached
    and a registry that already carries this report is skipped."""
    rows = report(max_age)
    if not rows or getattr(registry, "_inj_stamp", None) == _MEM["stamp"]:
        return 0
    changed = 0
    for (nm, team), row in rows.items():
        cands = registry.by_norm.get(nm)
        if not cands:
            continue
        cands = cands if isinstance(cands, (list, tuple)) else [cands]
        if len(cands) > 1:
            cands = [c for c in cands if (c.team or "").upper() == team]
        if len(cands) != 1:
            continue
        pl = cands[0]
        if (pl.team or "").upper() not in ("", team):
            continue                                 # a namesake on another team
        cur = (getattr(pl, "injury_status", None) or "").strip()
        new = row["status"]
        if new == "":
            if cur.upper() not in _SOFT:
                continue
            new = None
        if (cur or None) != new:
            pl.injury_status = new
            changed += 1
    try:
        registry._inj_stamp = _MEM["stamp"]
    except Exception:  # noqa: BLE001
        pass
    return changed
