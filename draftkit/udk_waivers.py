"""The Fantasy Footballers' weekly waiver list — who to add and what to bid.

The Ballers publish a waiver board every week at
``/fantasy-football-waivers/?position=ALL`` and it is fully public: the page
embeds two JSON arrays, ``rankings`` (48 skill players) and ``defenseRankings``
(6 streamers), each row carrying

    rank, name, team, fantasy_position, faab_low, faab_high,
    andy / jason / mike (each analyst's own rank), avg, consensus

That is a different thing from every other source in this app. The panels rank
players for a LINEUP; this ranks them for a CLAIM, and it is the only source
with a price on it. `faab_low`/`faab_high` are a PERCENT of budget, so a "0–15"
is $0–15 in a $100 league and $0–3 in a $20 one — converted per league rather
than printed raw.

What it cannot know is his league. Half their list is rostered in an 8-team
league, and a target that is already owned is not a target. So the app's job is
the join: their ranking and their price, against who is actually free here and
what the man would add to THIS lineup.

Week-stamped like Flock: a page that has not turned over yet returns the
previous week, and a stale waiver list is worse than none on a Tuesday.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional

import requests

from . import config
from .names import normalize_name
from .udk import _extract_json_array

_URL = "https://www.thefantasyfootballers.com/fantasy-football-waivers/"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
_TTL = 3 * 3600
_ANALYSTS = ("andy", "jason", "mike")


def _cache(season: int, week: int) -> Path:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR / f"udk_waivers_{season}_w{week}.json"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch(season: int, week: int) -> list:
    """The raw rows for THIS week, or [] when the page has not turned over."""
    cp = _cache(season, week)
    try:
        if cp.exists() and (time.time() - cp.stat().st_mtime) < _TTL:
            return json.loads(cp.read_text())
    except Exception:  # noqa: BLE001
        pass
    try:
        r = requests.get(_URL, params={"position": "ALL"}, headers=_UA, timeout=25)
        r.raise_for_status()
        rows = (_extract_json_array(r.text, "rankings") or [])
        rows += (_extract_json_array(r.text, "defenseRankings") or [])
    except Exception:  # noqa: BLE001
        rows = []
    # Their week, not ours. Showing last week's targets on a Tuesday is the one
    # failure that would actually cost him a claim.
    rows = [x for x in rows
            if str(x.get("week") or "") == str(week) and str(x.get("season") or "") == str(season)]
    if not rows:
        try:
            return json.loads(cp.read_text()) if cp.exists() else []
        except Exception:  # noqa: BLE001
            return []
    try:
        cp.write_text(json.dumps(rows))
    except Exception:  # noqa: BLE001
        pass
    return rows


def weekly(season: int, week: int, registry) -> Dict[str, dict]:
    """{pid: {rank, avg, consensus, by{analyst: rank}, faab_pct(lo,hi), pos,
    team, name, is_dst}} — their list, keyed by our pid.

    `rank` is their published overall rank within the list; `consensus` is the
    order the page actually shows, which is by the three analysts' average.
    """
    rows = fetch(season, week)
    if not rows:
        return {}
    idx: Dict[str, list] = {}
    for nm, p in registry.by_norm.items():
        if p.sleeper_pid:
            idx.setdefault(nm, []).append(p)
    out: Dict[str, dict] = {}
    for x in rows:
        pos = (x.get("fantasy_position") or "").upper()
        pos = "DST" if pos in ("D", "DEF", "D/ST") else pos
        team = (x.get("team") or "").upper()
        cands = idx.get(normalize_name(x.get("name") or "")) or []
        pick = None
        if cands:
            pick = cands[0]
            if len(cands) > 1:
                same = [c for c in cands if (c.team or "").upper() == team]
                if len(same) != 1:
                    continue
                pick = same[0]
        if pick is None:
            continue
        by = {a: _num(x.get(a)) for a in _ANALYSTS if _num(x.get(a)) is not None}
        out[str(pick.sleeper_pid)] = {
            "src": "udk_wv", "name": x.get("name") or "", "pos": pos, "team": team,
            "rank": _num(x.get("rank")), "avg": _num(x.get("avg")),
            "consensus": _num(x.get("consensus")), "by": by,
            "faab_lo": _num(x.get("faab_low")), "faab_hi": _num(x.get("faab_high")),
            "is_dst": pos == "DST",
        }
    return out


def bid(row: Optional[dict], budget: int) -> Optional[tuple]:
    """Their FAAB range in THIS league's dollars. Their numbers are a percent of
    budget, so a 0–15 is $15 in a $100 league and $3 in a $20 one."""
    if not row or row.get("faab_hi") is None or not budget:
        return None
    lo = int(round((row.get("faab_lo") or 0) / 100.0 * budget))
    hi = int(round(row["faab_hi"] / 100.0 * budget))
    return (lo, max(hi, lo))


def label(row: Optional[dict], budget: int = 0) -> str:
    """"Ballers #3 · $0–10" for a chip or an action line."""
    if not row:
        return ""
    n = row.get("consensus") or row.get("rank")
    out = f'Ballers #{int(n)}' if n else "on the Ballers' list"
    b = bid(row, budget)
    if b:
        out += f' · ${b[0]}–{b[1]}'
    return out
