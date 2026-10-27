"""What the experts say a waiver add is worth — FAAB as a share of budget.

Two public weekly lists, each with a price on every player it names:

  Footballguys   "Top Waiver Wire Pickups" (Sigmund Bloom), one article a week:
                 /article/<season>-email-feature-top-waiver-wire-pickups-week<NN>
                 — "Jonah Coleman (RB-DEN) … Bid Recommendation: 50-100% of
                 Annual FAAB Budget". A handful of names, priced for a deep,
                 competitive league.
  Footballers    the Ballers' waiver board (udk_waivers.fetch): ~40 names,
                 faab_low / faab_high, priced tighter (Coleman 10-15% the same week).

values() averages the sources that list a player. It is what he is WORTH;
faabmarket.hot_bid works out what he COSTS in this league and bids the smaller.
A player no expert prices — however many people are adding him — isn't a
contested claim worth paying up for: on 10/26 the trending list alone put
Brenton Strange and Dameon Pierce at the same $26 as Coleman.
"""
from __future__ import annotations

import json
import re
import time
from typing import Dict, List, Optional

import requests

from . import config
from .names import normalize_name

FBG_URL = "https://www.footballguys.com/article/{season}-email-feature-top-waiver-wire-pickups-week{week:02d}"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/141.0 Safari/537.36"}
_TTL = 3 * 3600
_FBG_ROW = re.compile(r"([A-Z][A-Za-z.'\- ]{2,40}?)\s*\|*\s*\((QB|RB|WR|TE|K|DST|DEF)-([A-Z]{2,3})\)[\s|]*"
                      r"Bid Recommendation:\s*(\d+)\s*(?:-|–|to)\s*(\d+)\s*%", re.S)


def parse_fbg(html: str) -> List[dict]:
    """[{name, pos, team, lo, hi}] from a Footballguys waiver article."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", html or ""))
    out, seen = [], set()
    for m in _FBG_ROW.finditer(text):
        name = m.group(1).strip(" |")
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "pos": m.group(2), "team": m.group(3),
                    "lo": float(m.group(4)), "hi": float(m.group(5))})
    return out


def fbg(season: int, week: int) -> List[dict]:
    """This week's Footballguys list, cached three hours; [] before it's posted."""
    cp = config.DATA_DIR / f"fbg_waivers_{season}_w{week}.json"
    try:
        if cp.exists() and time.time() - cp.stat().st_mtime < _TTL:
            return json.loads(cp.read_text())
    except Exception:  # noqa: BLE001
        pass
    try:
        r = requests.get(FBG_URL.format(season=season, week=week), headers=_UA, timeout=25)
        rows = parse_fbg(r.text) if r.status_code == 200 else []
    except Exception:  # noqa: BLE001
        rows = []
    if rows:
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(rows))
        except Exception:  # noqa: BLE001
            pass
        return rows
    try:
        return json.loads(cp.read_text()) if cp.exists() else []
    except Exception:  # noqa: BLE001
        return []


def ballers(season: int, week: int) -> List[dict]:
    from . import udk_waivers as UW
    out = []
    for x in UW.fetch(season, week) or []:
        lo, hi = x.get("faab_low"), x.get("faab_high")
        if hi is None:
            continue
        pos = (x.get("fantasy_position") or "").upper()
        out.append({"name": x.get("name") or "", "pos": "DST" if pos in ("D", "DEF", "D/ST") else pos,
                    "team": (x.get("team") or "").upper(), "lo": float(lo or 0), "hi": float(hi)})
    return out


def _index(players: dict) -> Dict[str, List[tuple]]:
    idx: Dict[str, List[tuple]] = {}
    for pid, p in players.items():
        nm = p.get("full_name") or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
        if nm:
            idx.setdefault(normalize_name(nm), []).append((str(pid), (p.get("team") or "").upper()))
    return idx


def _pid(idx: dict, name: str, team: str) -> Optional[str]:
    cands = idx.get(normalize_name(name)) or []
    if len(cands) == 1:
        return cands[0][0]
    same = [c for c in cands if c[1] == (team or "").upper()]
    return same[0][0] if len(same) == 1 else None


_MEMO: Dict[tuple, tuple] = {}


def values(season: int, week: int, players: Optional[dict] = None) -> Dict[str, dict]:
    """{sleeper pid: {lo, hi, src: {source: (lo, hi)}}} — shares of budget (0-1),
    averaged over the sources that price him. The list for `week` (the waiver
    run ahead), falling back to the week before when this one isn't up yet."""
    key = (int(season), int(week))
    hit = _MEMO.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    if players is None:
        from . import sleeper_client as api
        try:
            players = api.get_players() or {}
        except Exception:  # noqa: BLE001
            players = {}
    idx = _index(players)
    # Each source's list for the week asked, else the week before — and then
    # only the NEWEST week's lists count. A Footballers board that hasn't
    # turned over is last week's targets; mixing it with a current
    # Footballguys article would price this week's breakout off stale advice.
    lists = {}
    for src, fn in (("Footballguys", fbg), ("Footballers", ballers)):
        for wk in (week, week - 1):
            rows = fn(season, wk)
            if rows:
                lists[src] = (wk, rows)
                break
    newest = max((wk for wk, _rows in lists.values()), default=None)
    used = {src: wk for src, (wk, _rows) in lists.items() if wk == newest}
    by: Dict[str, dict] = {}
    for src, (wk, rows) in lists.items():
        if wk != newest:
            continue
        for r in rows:
            pid = _pid(idx, r["name"], r["team"])
            if pid:
                by.setdefault(pid, {"src": {}})["src"][src] = (r["lo"] / 100.0, r["hi"] / 100.0)
    for v in by.values():
        los, his = [x[0] for x in v["src"].values()], [x[1] for x in v["src"].values()]
        v["lo"], v["hi"] = sum(los) / len(los), sum(his) / len(his)
        v["week"], v["lists"] = newest, used
    _MEMO[key] = (time.time(), by)
    return by
