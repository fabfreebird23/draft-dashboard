"""What a man actually did, this week, in one line.

Sleeper's matchup feed carries fantasy points and nothing else — 43.8 with no
account of how. The public stats endpoint

    https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}

carries the box score for every player who has taken a snap, keyed by the same
player id the whole app joins on, and it updates while the game is on. One call
covers the entire league, so this is a per-tick read for the screen, not a read
per player.

`line()` is the other half: the same facts in the same ORDER for every player at
a position, so a column of live rows reads as a column rather than as a set of
sentences. Efficiency, then yards, then touchdowns, then the second phase.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional

import requests

from . import config

_URL = "https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"
_TTL = 45.0                      # live; the endpoint moves with the game
_MEM: Dict[str, tuple] = {}      # key -> (fetched_at, rows)


def _cache(season: int, week: int) -> Path:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR / f"nflstats_{season}_w{week}.json"


def weekly(season: int, week: int, max_age: float = _TTL) -> Dict[str, dict]:
    """{pid: {stat: value}} for the week. Never raises; a failed call keeps the
    last good copy, because a missing stat line must not blank a live row."""
    key = f"{season}_{week}"
    hit = _MEM.get(key)
    # 5s floor: Live prefetches this alongside the scoreboard and reads it again
    # a moment later — that second read must be the same copy, not a refetch
    if hit and (time.time() - hit[0]) < max(5.0, max_age):
        return hit[1]
    rows: Dict[str, dict] = {}
    try:
        r = requests.get(_URL.format(season=season, week=week), timeout=12)
        r.raise_for_status()
        rows = {str(k): v for k, v in (r.json() or {}).items() if isinstance(v, dict)}
    except Exception:  # noqa: BLE001
        rows = {}
    cp = _cache(season, week)
    if not rows:
        if hit:
            return hit[1]
        try:
            rows = json.loads(cp.read_text()) if cp.exists() else {}
        except Exception:  # noqa: BLE001
            rows = {}
    else:
        try:
            cp.write_text(json.dumps(rows))
        except Exception:  # noqa: BLE001
            pass
    _MEM[key] = (time.time(), rows)
    return rows


def _n(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _i(row: dict, key: str) -> int:
    return int(round(_n(row, key)))


def line(pos: str, row: Optional[dict]) -> str:
    """"20/31 · 248 yd · 3 TD · 11 car, 72 yd, 2 TD" — his week, in position order.

    Empty when he has not touched the ball, which the row draws as the kickoff
    time instead. A zero that MATTERS is kept (a back with no receptions still
    shows the catch line); a zero that does not is dropped.
    """
    if not row:
        return ""
    p = (pos or "").upper()
    bits = []
    if p == "QB":
        att, cmp_ = _i(row, "pass_att"), _i(row, "pass_cmp")
        if att:
            bits.append(f"{cmp_}/{att}")
            bits.append(f'{_i(row, "pass_yd")} yd')
            if _i(row, "pass_td"):
                bits.append(f'{_i(row, "pass_td")} TD')
            if _i(row, "pass_int"):
                bits.append(f'{_i(row, "pass_int")} INT')
        if _i(row, "rush_att"):
            r = f'{_i(row, "rush_att")} car, {_i(row, "rush_yd")} yd'
            if _i(row, "rush_td"):
                r += f', {_i(row, "rush_td")} TD'
            bits.append(r)
    elif p == "RB":
        if _i(row, "rush_att"):
            r = f'{_i(row, "rush_att")} car, {_i(row, "rush_yd")} yd'
            if _i(row, "rush_td"):
                r += f', {_i(row, "rush_td")} TD'
            bits.append(r)
        if _i(row, "rec_tgt") or _i(row, "rec"):
            r = f'{_i(row, "rec")}/{_i(row, "rec_tgt")} rec, {_i(row, "rec_yd")} yd'
            if _i(row, "rec_td"):
                r += f', {_i(row, "rec_td")} TD'
            bits.append(r)
    elif p in ("WR", "TE"):
        if _i(row, "rec_tgt") or _i(row, "rec"):
            r = f'{_i(row, "rec")}/{_i(row, "rec_tgt")} rec, {_i(row, "rec_yd")} yd'
            if _i(row, "rec_td"):
                r += f', {_i(row, "rec_td")} TD'
            bits.append(r)
        if _i(row, "rush_att"):
            r = f'{_i(row, "rush_att")} car, {_i(row, "rush_yd")} yd'
            if _i(row, "rush_td"):
                r += f', {_i(row, "rush_td")} TD'
            bits.append(r)
    elif p == "K":
        fgm, fga = _i(row, "fgm"), _i(row, "fga")
        if fga:
            bits.append(f"{fgm}/{fga} FG")
        if _i(row, "xpa"):
            bits.append(f'{_i(row, "xpm")}/{_i(row, "xpa")} XP')
        if _i(row, "fgm_50p"):
            bits.append(f'{_i(row, "fgm_50p")} from 50+')
    elif p in ("DST", "DEF", "D/ST"):
        if _i(row, "def_st_td") or _i(row, "def_td"):
            bits.append(f'{_i(row, "def_td") + _i(row, "def_st_td")} TD')
        if _n(row, "sack"):
            bits.append(f'{_n(row, "sack"):g} sack')
        if _i(row, "int"):
            bits.append(f'{_i(row, "int")} INT')
        if _i(row, "ff") or _i(row, "fum_rec"):
            bits.append(f'{_i(row, "fum_rec")} fum rec')
        if row.get("pts_allow") is not None:
            bits.append(f'{_i(row, "pts_allow")} allowed')
    if _i(row, "fum_lost"):
        bits.append(f'{_i(row, "fum_lost")} fum lost')
    return " · ".join(bits)


# ------------------------------------------------------------ finished weeks
# A week that is over never changes, and the usage trends and the Monday
# review both want several of them at once. The live feed above is ~1.5 MB a
# week; this keeps the fields those two read and holds each week for good.
_FINAL_KEEP = ("gp", "gs", "off_snp", "tm_off_snp", "rec_tgt", "rec", "rec_yd", "rec_td", "rec_air_yd",
               "rec_rz_tgt", "rush_att", "rush_yd", "rush_td", "rush_rz_att", "pass_att", "pass_cmp",
               "pass_yd", "pass_td", "pass_int", "pass_2pt", "pass_inc", "pass_fd", "pass_sack",
               "rush_2pt", "rush_fd", "rec_2pt", "rec_fd", "bonus_rec_te", "bonus_rec_rb",
               "bonus_rec_wr", "fum_lost", "fum", "pts_ppr", "pts_half_ppr", "pts_std",
               "fgm", "fga", "xpm", "xpa")
_FINAL: Dict[str, Dict[str, dict]] = {}


def final(season: int, week: int) -> Dict[str, dict]:
    """{pid | "TEAM_XXX": slim stat row} for a FINISHED week. {} if unreachable."""
    key = f"{season}_{week}"
    if key in _FINAL:
        return _FINAL[key]
    cp = config.DATA_DIR / f"nflfinal_{season}_w{week}.json"
    rows: Dict[str, dict] = {}
    try:
        if cp.exists():
            rows = json.loads(cp.read_text())
    except Exception:  # noqa: BLE001
        rows = {}
    if not rows:
        try:
            r = requests.get(_URL.format(season=season, week=week), timeout=15)
            r.raise_for_status()
            for k, v in (r.json() or {}).items():
                if not isinstance(v, dict):
                    continue
                slim = {f: v[f] for f in _FINAL_KEEP if v.get(f) is not None}
                if slim:
                    rows[str(k)] = slim
            if rows:
                config.DATA_DIR.mkdir(parents=True, exist_ok=True)
                cp.write_text(json.dumps(rows))
        except Exception:  # noqa: BLE001
            rows = {}
    if rows:
        _FINAL[key] = rows
    return rows
