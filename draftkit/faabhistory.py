"""Every FAAB waiver claim in a league's history — who won, what everyone bid.

faabmarket keeps only what pricing needs (the winning bid and the losing
amounts); this keeps the whole claim so the Waivers tab can list it: the
player, the team that won and its bid, and every other team that bid and how
much, for each season in the league's chain that ran FAAB.

Past seasons never change, so their transactions are cached for good; the
current season refreshes every 10 minutes. Sleeper only.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from . import config, sleeper_client as api

FAAB = 2
PAST_TTL = 365 * 86400
LIVE_TTL = 600


def _bid(t: dict) -> int:
    return int((t.get("settings") or {}).get("waiver_bid") or 0)


def _owners(league_id: str) -> Dict[int, dict]:
    """{roster_id: {name, team, user}} for one season. The manager's name is
    what's shown — team names change every season ("2025 Manager of the year")."""
    try:
        users = {u.get("user_id"): u for u in api.get_users(league_id) or []}
        rosters = api.get_rosters(league_id) or []
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for r in rosters:
        u = users.get(r.get("owner_id")) or {}
        out[int(r.get("roster_id"))] = {"name": str(u.get("display_name") or f"Team {r.get('roster_id')}").strip(),
                                        "team": str((u.get("metadata") or {}).get("team_name") or "").strip(),
                                        "user": r.get("owner_id")}
    return out


def _player(players: dict, pid: str) -> dict:
    p = players.get(str(pid)) or {}
    name = p.get("full_name") or " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
    if not name and str(pid).isalpha():
        name = f"{pid} D/ST"                       # team defenses are keyed by abbreviation
    return {"name": name or str(pid), "pos": p.get("position") or ("DEF" if str(pid).isalpha() else ""),
            "team": p.get("team") or ""}


def season_claims(league_id: str, season: int, budget: int, live: bool, players: dict,
                  last_week: int = 18) -> List[dict]:
    """Every claim of one season: one row per player per week's run."""
    owners = _owners(league_id)
    rows = []
    for wk in range(1, last_week + 1):
        try:
            tx = api._disk(f"txh_{league_id}_{wk}", LIVE_TTL if live else PAST_TTL,
                           lambda wk=wk: api._get(f"league/{league_id}/transactions/{wk}") or [])
        except Exception:  # noqa: BLE001
            continue
        by_player = defaultdict(list)
        for t in tx or []:
            if t.get("type") == "waiver" and t.get("status") in ("complete", "failed"):
                for pid in (t.get("adds") or {}):
                    by_player[str(pid)].append(t)
        for pid, ts in by_player.items():
            win = next((t for t in ts if t.get("status") == "complete"), None)
            def who(t):
                return owners.get((t.get("roster_ids") or [None])[0]) or {"name": "?", "team": "", "user": None}
            bids = sorted(({"team": who(t)["name"], "team_name": who(t)["team"], "user": who(t)["user"],
                            "bid": _bid(t), "won": t is win} for t in ts), key=lambda b: (-b["bid"], not b["won"]))
            won = _bid(win) if win else None
            runner = next((b["bid"] for b in bids if not b["won"]), None)
            pl = _player(players, pid)
            rows.append({"season": season, "week": wk, "pid": pid, **pl, "budget": budget,
                         "winner": next((b["team"] for b in bids if b["won"]), None),
                         "winner_team": next((b["team_name"] for b in bids if b["won"]), ""),
                         "winner_user": next((b["user"] for b in bids if b["won"]), None),
                         "won": won, "runner_up": runner, "bidders": len(ts), "bids": bids,
                         "pct": round(won / budget, 4) if (won is not None and budget) else None,
                         "over": (won - runner) if (won is not None and runner is not None) else None,
                         "at": max((t.get("status_updated") or t.get("created") or 0) for t in ts)})
    return rows


def all_claims(league_id: str, season: Optional[int] = None) -> List[dict]:
    """Every FAAB claim across the league's history, newest season first."""
    season = int(season or config.current_season())
    try:
        chain = api.league_chain(str(league_id))
    except Exception:  # noqa: BLE001
        chain = []
    try:
        players = api.get_players() or {}
    except Exception:  # noqa: BLE001
        players = {}
    out: List[dict] = []
    for c in chain:
        s = int(c["season"])
        if s > season:
            continue
        try:
            lg = api.get_league(c["league_id"]) or {}
        except Exception:  # noqa: BLE001
            continue
        st = lg.get("settings") or {}
        if int(st.get("waiver_type") or 0) != FAAB or not int(st.get("waiver_budget") or 0):
            continue
        out += season_claims(c["league_id"], s, int(st["waiver_budget"]), live=(s == season), players=players)
    return out


SORTS = {
    "Price": lambda r: (-(r["won"] if r["won"] is not None else -1), -r["season"], -r["week"]),
    "% of budget": lambda r: (-(r["pct"] if r["pct"] is not None else -1), -r["season"], -r["week"]),
    "Overpay": lambda r: (-(r["over"] if r["over"] is not None else -1), -(r["won"] or 0)),
    "Most bidders": lambda r: (-r["bidders"], -(r["won"] or 0)),
    "Newest": lambda r: (-r["season"], -r["week"], -(r["won"] or 0)),
}


def summary(rows: List[dict]) -> dict:
    """Per season: claims won, dollars spent, the median winning bid, the top claim."""
    by = defaultdict(list)
    for r in rows:
        if r["won"] is not None:
            by[r["season"]].append(r)
    out = {}
    for s, rs in sorted(by.items(), reverse=True):
        bids = sorted(r["won"] for r in rs)
        top = max(rs, key=lambda r: r["won"])
        out[s] = {"n": len(rs), "spent": sum(bids), "median": bids[len(bids) // 2],
                  "free": sum(1 for b in bids if b == 0), "budget": rs[0]["budget"], "top": top}
    return out
