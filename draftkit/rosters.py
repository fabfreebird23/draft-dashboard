"""Who is actually on each team, for in-season lineups.

Separate from providers/ because drafting only ever needs the draft board — the
providers deliberately don't model a roster. This is the smallest thing that can
answer "what do I have this week", for both platforms, keyed on Sleeper pids so
everything downstream (projections, registry, byes) lines up.
"""
from __future__ import annotations

from typing import Dict, List

_ESPN = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
         "/seasons/{season}/segments/0/leagues/{lid}")
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def sleeper_rosters(league_id: str) -> Dict[str, dict]:
    """{owner_id: {name_key, players, starters}}."""
    from . import sleeper_client as api
    out: Dict[str, dict] = {}
    for r in (api.get_rosters(league_id) or []):
        oid = str(r.get("owner_id") or r.get("roster_id") or "")
        if not oid:
            continue
        out[oid] = {
            "players": [str(p) for p in (r.get("players") or [])],
            # Sleeper pads empty starter slots with "0" — keep them out so a half-set
            # lineup doesn't read as "you started a player called 0".
            "starters": [str(p) for p in (r.get("starters") or []) if p and str(p) != "0"],
            "roster_id": r.get("roster_id"),
        }
    return out


def espn_rosters(league_id: str, season: int, registry=None,
                 espn_s2=None, swid=None) -> Dict[str, dict]:
    """{teamId: {players, starters}} with ESPN ids resolved to Sleeper pids.

    Anyone we can't resolve is dropped rather than kept under an id the rest of the
    app can't look up — a roster entry we can't project is worse than a short list,
    because it would silently occupy a slot."""
    import requests
    try:
        r = requests.get(_ESPN.format(season=season, lid=league_id), headers=_HEADERS,
                         params={"view": "mRoster"},
                         cookies=({"espn_s2": espn_s2, "SWID": swid}
                                  if (espn_s2 and swid) else None), timeout=25)
        r.raise_for_status()
        teams = (r.json() or {}).get("teams") or []
    except Exception:  # noqa: BLE001
        return {}

    BENCH = {20, 21}          # ESPN lineupSlotId: 20 bench, 21 IR
    out: Dict[str, dict] = {}
    for t in teams:
        players, starters = [], []
        for e in ((t.get("roster") or {}).get("entries") or []):
            pid = str((e.get("playerPoolEntry") or {}).get("id") or e.get("playerId") or "")
            if registry is not None and pid:
                hit = registry.resolve_espn(pid)
                pid = getattr(hit, "sleeper_pid", None) or ""
            if not pid:
                continue
            players.append(pid)
            if e.get("lineupSlotId") not in BENCH:
                starters.append(pid)
        out[str(t.get("id"))] = {"players": players, "starters": starters}
    return out


def for_league(meta, registry, team_key: str, espn_s2=None, swid=None) -> dict:
    """One team's {players, starters}. `team_key` is a Sleeper owner_id or an ESPN
    teamId — whichever identifies a team on that platform."""
    if getattr(meta, "platform", "") == "espn":
        all_ = espn_rosters(str(meta.league_id), int(meta.season), registry,
                            espn_s2=espn_s2, swid=swid)
    else:
        all_ = sleeper_rosters(str(meta.league_id))
    return all_.get(str(team_key)) or {"players": [], "starters": []}
