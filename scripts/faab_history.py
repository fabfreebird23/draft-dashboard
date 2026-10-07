"""Pull every waiver claim (won AND lost) for the Sleeper leagues, with context.

    .venv/bin/python scripts/faab_history.py   -> data/faab/claims_<league>.json

Per player-week: the winning bid, every losing bid, how many teams wanted him,
the league's budget, and Sleeper's own projection for him that week (the value
signal that exists for past weeks; nobody kept the Ballers' ranges).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import requests

LEAGUES = {"kreeper": "1310907162930733056", "babies": "1312885282554535936",
           "seven-half": "1388606375239643136"}
OUT = Path(__file__).resolve().parent.parent / "data" / "faab"
S = requests.Session()


def get(url):
    r = S.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


_proj = {}


def proj(season: int, week: int) -> dict:
    """{pid: projected PPR points} for that week, from Sleeper."""
    k = (season, week)
    if k not in _proj:
        try:
            rows = get(f"https://api.sleeper.app/projections/nfl/{season}/{week}?season_type=regular")
        except Exception:
            rows = []
        _proj[k] = {str(r.get("player_id")): float((r.get("stats") or {}).get("pts_ppr") or 0)
                    for r in (rows or []) if r.get("player_id")}
    return _proj[k]


def chain(lid: str):
    """This league and every previous season it was renewed from."""
    out = []
    while lid and lid != "0":
        lg = get(f"https://api.sleeper.app/v1/league/{lid}")
        out.append(lg)
        lid = lg.get("previous_league_id")
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, lid in LEAGUES.items():
        rows = []
        for lg in chain(lid):
            season = int(lg["season"])
            budget = int((lg.get("settings") or {}).get("waiver_budget") or 0)
            if not budget:
                continue
            for wk in range(1, 19):
                try:
                    tx = get(f"https://api.sleeper.app/v1/league/{lg['league_id']}/transactions/{wk}")
                except Exception:
                    continue
                by_player = defaultdict(list)
                for t in tx or []:
                    if t.get("type") != "waiver":
                        continue
                    for pid in (t.get("adds") or {}):
                        by_player[pid].append(t)
                if not by_player:
                    continue
                pj = proj(season, wk)
                for pid, ts in by_player.items():
                    win = [t for t in ts if t.get("status") == "complete"]
                    lose = [t for t in ts if t.get("status") == "failed"]
                    wbid = int((win[0].get("settings") or {}).get("waiver_bid") or 0) if win else None
                    lbids = sorted((int((t.get("settings") or {}).get("waiver_bid") or 0) for t in lose),
                                   reverse=True)
                    rows.append({"season": season, "week": wk, "pid": pid, "budget": budget,
                                 "won": wbid, "lost": lbids, "bidders": len(ts),
                                 "winner": (win[0].get("roster_ids") or [None])[0] if win else None,
                                 "proj": round(pj.get(pid, 0.0), 2)})
        (OUT / f"claims_{slug}.json").write_text(json.dumps(rows))
        seasons = sorted({r["season"] for r in rows})
        print(f"{slug:11s} {len(rows):4d} player-weeks  seasons={seasons}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
