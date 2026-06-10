"""Thin client for Sleeper's public read-only API (no auth required).

Docs: https://docs.sleeper.com/ — all endpoints are GET + JSON. We cache the big
players blob and league/draft reads to disk so the app doesn't hammer the API.
Adapted verbatim from the keeper-league app's kreeper/sleeper.py.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import requests

from . import config

BASE = "https://api.sleeper.app/v1"
HEADERS = {"User-Agent": "draft-dashboard/1.0 (personal fantasy tool)"}
_PLAYERS_CACHE = config.DATA_DIR / "players_nfl.json"
_PLAYERS_MAX_AGE = 60 * 60 * 24  # refresh the players map at most daily


def _get(path: str) -> Any:
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}/{path}", headers=HEADERS, timeout=8)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(1.0 * (attempt + 1))


def _disk(key: str, ttl: int, fetch):
    """Cache a Sleeper read to disk. On a fetch failure, fall back to stale cache
    so a flaky/slow API never takes the whole app down."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = config.DATA_DIR / f"cache_{key}.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < ttl:
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    try:
        data = fetch()
    except Exception:  # noqa: BLE001
        if p.exists():
            return json.loads(p.read_text())
        raise
    p.write_text(json.dumps(data))
    return data


def get_league(league_id: str) -> Dict[str, Any]:
    return _disk(f"league_{league_id}", 3600, lambda: _get(f"league/{league_id}"))


def get_users(league_id: str) -> List[Dict[str, Any]]:
    return _disk(f"users_{league_id}", 3600, lambda: _get(f"league/{league_id}/users"))


def get_rosters(league_id: str) -> List[Dict[str, Any]]:
    return _disk(f"rosters_{league_id}", 1800, lambda: _get(f"league/{league_id}/rosters"))


def get_draft(draft_id: str) -> Dict[str, Any]:
    return _disk(f"draft_{draft_id}", 3600, lambda: _get(f"draft/{draft_id}"))


def get_draft_picks_fresh(draft_id: str) -> List[Dict[str, Any]]:
    """Uncached draft picks — for a LIVE draft where freshness matters."""
    return _get(f"draft/{draft_id}/picks") or []


def get_traded_picks(draft_id: str) -> List[Dict[str, Any]]:
    """Picks swapped between rosters — [{round, roster_id, owner_id, previous_owner_id}]
    (ids are roster_ids). Lets us reflect real, traded draft capital."""
    return _disk(f"tpicks_{draft_id}", 1800, lambda: _get(f"draft/{draft_id}/traded_picks") or [])


def get_draft_picks(draft_id: str) -> List[Dict[str, Any]]:
    """Cached past-draft picks (for history/tendency analysis, not live use)."""
    return _disk(f"picks_{draft_id}", 86400, lambda: _get(f"draft/{draft_id}/picks") or [])


def league_chain(league_id: str) -> List[Dict[str, Any]]:
    """Walk previous_league_id back to the start. Newest-first list of
    {season, league_id, draft_id}."""
    chain: List[Dict[str, Any]] = []
    lid: Optional[str] = league_id
    seen = set()
    while lid and lid not in ("0", None) and lid not in seen:
        seen.add(lid)
        lg = get_league(lid)
        if not lg:
            break
        chain.append({"season": int(lg["season"]), "league_id": lg["league_id"],
                      "draft_id": lg.get("draft_id")})
        lid = lg.get("previous_league_id")
    return chain


def get_players() -> Dict[str, Any]:
    """Sleeper's full NFL player map (~5MB), cached to disk and refreshed daily."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _PLAYERS_CACHE.exists():
        age = time.time() - _PLAYERS_CACHE.stat().st_mtime
        if age < _PLAYERS_MAX_AGE:
            return json.loads(_PLAYERS_CACHE.read_text())
    data = _get("players/nfl")
    _PLAYERS_CACHE.write_text(json.dumps(data))
    return data


def find_league_id(username: str, season: int) -> Optional[str]:
    """Convenience: resolve a Sleeper username's first NFL league for a season."""
    user = _get(f"user/{username}")
    if not user:
        return None
    leagues = _get(f"user/{user['user_id']}/leagues/nfl/{season}") or []
    return leagues[0]["league_id"] if leagues else None
