"""Season fantasy-point projections from Sleeper — the fuel for the value engine.

Unlike the UDK scrape (great rankings, but IP-blocked from Streamlit Cloud's
datacenter), Sleeper's projections endpoint works everywhere we run. We pull the
upcoming season's projected points per position, cache to disk, and expose a
simple `pid -> projected points` map for the active scoring format.
"""
from __future__ import annotations

import json
import time
from typing import Dict

import requests

from . import config

_BASE = "https://api.sleeper.com/projections/nfl"
_HEADERS = {"User-Agent": "draft-dashboard/1.0 (personal fantasy tool)"}
_TTL = 60 * 60 * 24            # refresh projections at most daily
_POSITIONS = ("QB", "RB", "WR", "TE")
_PTS_KEY = {"ppr": "pts_ppr", "half": "pts_half_ppr", "std": "pts_std"}
# Sleeper's precomputed totals PLUS the components any scoring can be rebuilt from.
_COMPONENTS = ("pass_yd", "pass_td", "pass_int", "pass_2pt",
               "rush_yd", "rush_td", "rush_2pt",
               "rec", "rec_yd", "rec_td", "rec_2pt", "fum_lost", "gp")
_KEEP = tuple(_PTS_KEY.values()) + _COMPONENTS
_CACHE_VERSION = 2       # bump when _KEEP changes so old thin caches are rebuilt


def _fetch_pos(season: int, pos: str) -> list:
    url = (f"{_BASE}/{season}?season_type=regular&position[]={pos}"
           f"&order_by=pts_ppr")
    r = requests.get(url, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json() or []


def load_projections(season: int, scoring: str = "ppr", weights=None) -> Dict[str, float]:
    """`{sleeper_pid: projected_points}` for the season.

    `weights` (from draftkit.scoring) overrides `scoring` and computes points from
    the component stats, so a league with non-standard rules — 2 points a
    reception, 6-point passing TDs — is valued on its own terms rather than
    rounded to the nearest of ppr/half/std."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = config.DATA_DIR / f"proj_{season}.json"
    raw = None
    if cache.exists() and (time.time() - cache.stat().st_mtime) < _TTL:
        try:
            raw = json.loads(cache.read_text())
            # A cache written before components were kept has only pts_* keys —
            # unusable for custom scoring, so treat it as a miss and refetch.
            if raw and not any(k in next(iter(raw.values()), {}) for k in _COMPONENTS):
                raw = None
        except Exception:  # noqa: BLE001
            raw = None
    if raw is None:
        merged: Dict[str, dict] = {}
        try:
            for pos in _POSITIONS:
                for row in _fetch_pos(season, pos):
                    pid = str(row.get("player_id") or "")
                    st = row.get("stats") or {}
                    if pid and st:
                        # Keep the COMPONENT stats, not just Sleeper's three
                        # precomputed totals. A league that isn't ppr/half/std
                        # (the ESPN one pays 2.0 a reception) can only be scored
                        # correctly from the components — caching just the totals
                        # threw away the ability to do it. See draftkit/scoring.py.
                        merged[pid] = {k: st.get(k) for k in _KEEP if st.get(k) is not None}
            raw = merged
            cache.write_text(json.dumps(raw))
        except Exception:  # noqa: BLE001 — fall back to stale cache if present
            if cache.exists():
                raw = json.loads(cache.read_text())
            else:
                return {}
    if weights:
        from . import scoring as _sc
        out: Dict[str, float] = {}
        for pid, st in raw.items():
            # Only players Sleeper actually projected. Sleeper returns a row for
            # every rostered player, most with empty stats — scoring those from
            # components yields ~0 and floods the pool with 2500 non-players,
            # which drags the replacement level the whole value model rests on.
            # `pts_ppr` present is Sleeper's own signal that it made a projection.
            if st.get("pts_ppr") is None:
                continue
            # A row with no components (an old thin cache entry) would score 0 and
            # sink the player; fall back to the closest preset total instead.
            if any(k in st for k in _COMPONENTS):
                out[str(pid)] = _sc.points(st, weights)
            else:
                v = st.get(_PTS_KEY.get(_sc.label_for(weights), "pts_ppr")) or st.get("pts_ppr")
                if v is not None:
                    out[str(pid)] = float(v)
        return out
    key = _PTS_KEY.get(scoring, "pts_ppr")
    out: Dict[str, float] = {}
    for pid, pts in raw.items():
        v = pts.get(key)
        if v is None:
            v = pts.get("pts_ppr")
        try:
            out[str(pid)] = float(v)
        except (TypeError, ValueError):
            continue
    return out
