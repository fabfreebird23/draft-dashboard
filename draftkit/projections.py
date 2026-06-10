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


def _fetch_pos(season: int, pos: str) -> list:
    url = (f"{_BASE}/{season}?season_type=regular&position[]={pos}"
           f"&order_by=pts_ppr")
    r = requests.get(url, headers=_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json() or []


def load_projections(season: int, scoring: str = "ppr") -> Dict[str, float]:
    """`{sleeper_pid: projected_points}` for the season + scoring. Disk-cached
    (raw per-scoring points are all stored, so changing scoring is free)."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = config.DATA_DIR / f"proj_{season}.json"
    raw = None
    if cache.exists() and (time.time() - cache.stat().st_mtime) < _TTL:
        try:
            raw = json.loads(cache.read_text())
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
                        merged[pid] = {k: st.get(k) for k in _PTS_KEY.values()}
            raw = merged
            cache.write_text(json.dumps(raw))
        except Exception:  # noqa: BLE001 — fall back to stale cache if present
            if cache.exists():
                raw = json.loads(cache.read_text())
            else:
                return {}
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
