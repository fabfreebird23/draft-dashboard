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


# ------------------------------------------------------------------ hot claims
HOT_TEAMS = 2           # at least two different teams putting real money on him…
HOT_SHARE = 0.15        # …or a winning bid of 15% of the budget


def team_bids(r: dict) -> Dict[str, int]:
    """{team: its highest bid} on one claim. Sleeper logs one claim per drop,
    so a team's two $0 claims on a player are one bidder, not two."""
    out: Dict[str, int] = {}
    for b in r["bids"]:
        out[b["team"]] = max(out.get(b["team"], 0), int(b["bid"]))
    return out


def is_hot(r: dict) -> bool:
    """A top-tier claim: two or more teams bidding money, or a big winning bid."""
    paying = sum(1 for v in team_bids(r).values() if v >= 1)
    return paying >= HOT_TEAMS or bool(r["won"] is not None and r["budget"] and r["won"] >= HOT_SHARE * r["budget"])


def hot_profiles(rows: List[dict], since: Optional[int] = None) -> Dict[str, dict]:
    """How each team bids when a claim is contested: on every hot claim it was
    in, its bid as a share of that season's budget (budgets changed: $250 in
    2023, $100 since). `since` limits to seasons from that year on."""
    out: Dict[str, dict] = {}
    for r in rows:
        if not r["budget"] or (since and r["season"] < since) or not is_hot(r):
            continue
        for team, bid in team_bids(r).items():
            p = out.setdefault(team, {"team": team, "n": 0, "wins": 0, "shares": [], "money": [], "top": None})
            p["n"] += 1
            share = bid / r["budget"]
            p["shares"].append(share)
            if bid >= 1:
                p["money"].append(share)
            if r["winner"] == team:
                p["wins"] += 1
            if p["top"] is None or share > p["top"]["share"]:
                p["top"] = {"share": share, "bid": bid, "name": r["name"], "season": r["season"], "week": r["week"]}
    for p in out.values():
        s, m = p.pop("shares"), p.pop("money")
        p["avg"] = sum(s) / len(s) if s else 0.0             # every hot claim it was in, $0s included
        p["avg_paid"] = sum(m) / len(m) if m else 0.0        # only when it put money down
        p["max"] = max(s) if s else 0.0
        p["n_money"] = len(m)
    return out


def hot_market(rows: List[dict], since: Optional[int] = None) -> dict:
    """The league's hot claims overall: what won them and the 2nd bid (the
    price that actually had to be beaten), as shares of the budget."""
    hot = [r for r in rows if r["won"] is not None and r["budget"] and (not since or r["season"] >= since) and is_hot(r)]

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None
    won = [r["won"] / r["budget"] for r in hot]
    second = []
    for r in hot:
        tb = sorted(team_bids(r).values(), reverse=True)
        second.append((tb[1] if len(tb) > 1 else 0) / r["budget"])
    return {"n": len(hot), "won_med": q(won, .5), "won_p75": q(won, .75), "won_avg": sum(won) / len(won) if won else None,
            "second_med": q(second, .5), "second_p75": q(second, .75), "second_p90": q(second, .9),
            "second_max": max(second) if second else None, "claims": hot}


def faab_left(league_id: str) -> Dict[str, int]:
    """{manager: FAAB left this season} from Sleeper's rosters."""
    try:
        lg = api.get_league(str(league_id)) or {}
        budget = int((lg.get("settings") or {}).get("waiver_budget") or 0)
        users = {u.get("user_id"): str(u.get("display_name") or "").strip() for u in api.get_users(str(league_id)) or []}
        rosters = api.get_rosters(str(league_id)) or []
    except Exception:  # noqa: BLE001
        return {}
    return {users.get(r.get("owner_id"), f"Team {r.get('roster_id')}"):
            budget - int((r.get("settings") or {}).get("waiver_budget_used") or 0) for r in rosters}
