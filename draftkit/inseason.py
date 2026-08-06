"""In-season data: free agents, keeper cost of an add, FAAB, and this week's opponent.

The through-line is the same as the rest of the app — only compute what Sleeper and
ESPN can't already show you. A free-agent list is not interesting; a free-agent list
that knows what a player costs to KEEP next year is, because three of these four
leagues are keeper leagues and every add has a next-season price.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import keepers as K, sleeper_client as api


# --------------------------------------------------------------- rostered / free
def rostered_pids(meta, registry=None, espn_s2=None, swid=None) -> set:
    """Every player on a roster in this league."""
    from . import rosters as RO
    if getattr(meta, "platform", "") == "espn":
        all_ = RO.espn_rosters(str(meta.league_id), int(meta.season), registry,
                               espn_s2=espn_s2, swid=swid)
    else:
        all_ = RO.sleeper_rosters(str(meta.league_id))
    out = set()
    for r in all_.values():
        out.update(str(p) for p in (r.get("players") or []))
    return out


def free_agents(meta, registry, projections: dict, taken: set, limit: int = 40) -> List[dict]:
    """Unrostered players with a projection, best first.

    Ranked on projected points rather than ADP: in-season, what a player is
    expected to score this week is the only thing that matters, and ADP has been
    meaningless since the draft."""
    out = []
    for pid, pts in (projections or {}).items():
        if str(pid) in taken:
            continue
        try:
            pm = registry.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        if pm.position not in ("QB", "RB", "WR", "TE"):
            continue
        out.append({"pid": str(pid), "name": pm.name, "pos": pm.position,
                    "team": pm.team, "proj": float(pts or 0.0)})
    out.sort(key=lambda r: -r["proj"])
    return out[:limit]


# ------------------------------------------------------------------ keeper price
def keeper_price(meta, pid, registry, rules: Optional[dict] = None) -> Optional[dict]:
    """What this player would cost to keep NEXT year if you added him now.

    This is the whole point of the in-season waiver view and the one thing neither
    platform can tell you. A free agent has no draft round, so he prices at the
    league's last round — or at the fixed rookie round if he's an NFL rookie and
    the league has rookie keeper slots. Both come from that league's own config.

    Returns None for a non-keeper league, which is the honest answer rather than a
    fabricated round."""
    try:
        rules = rules if rules is not None else K.load_keeper_rules(str(meta.league_id))
    except Exception:  # noqa: BLE001
        return None
    if not rules or not (rules.get("max_regular_keepers") or rules.get("max_rookie_keepers")):
        return None
    try:
        rookie = getattr(registry.meta(pid), "years_exp", None) == 0
    except Exception:  # noqa: BLE001
        rookie = False
    fixed = rules.get("rookie_fixed_round")
    if rookie and fixed:
        return {"round": int(fixed), "slot": "rookie",
                "note": f"R{int(fixed)} rookie slot"}
    last = int(getattr(meta, "draft_rounds", 0) or 0)
    if not last:
        return None
    return {"round": last, "slot": "regular", "note": f"R{last} regular slot"}


def keeper_slots_used(meta, my_pids, registry, rules: Optional[dict] = None) -> Optional[dict]:
    """{regular_used, regular_max, rookie_used, rookie_max} for your roster, or None.

    Approximate by design: it counts NFL rookies on your roster against the rookie
    cap. Actual eligibility in these leagues turns on draft provenance, which lives
    in each league's own hub — this is enough to answer "do I have a slot open",
    which is the question the waiver view asks."""
    try:
        rules = rules if rules is not None else K.load_keeper_rules(str(meta.league_id))
    except Exception:  # noqa: BLE001
        return None
    reg_max = rules.get("max_regular_keepers")
    rook_max = rules.get("max_rookie_keepers")
    if not (reg_max or rook_max):
        return None
    rook = 0
    for pid in (my_pids or []):
        try:
            if getattr(registry.meta(pid), "years_exp", None) == 0:
                rook += 1
        except Exception:  # noqa: BLE001
            continue
    return {"rookie_used": rook, "rookie_max": int(rook_max or 0),
            "regular_used": None, "regular_max": int(reg_max or 0)}


# -------------------------------------------------------------------------- FAAB
def faab(meta) -> Optional[dict]:
    """{budget, by_owner:{owner_id: spent}, median_left} or None.

    NB 7 1/2 Men inverts the usual advice — unspent FAAB is owed to the Chase
    bracket pot, so hoarding costs real money there. That rule lives in its own
    hub; this only reports the numbers."""
    if getattr(meta, "platform", "") != "sleeper":
        return None
    try:
        lg = api.get_league(str(meta.league_id)) or {}
        budget = int((lg.get("settings") or {}).get("waiver_budget") or 0)
        if not budget:
            return None
        rows = api.get_rosters(str(meta.league_id)) or []
    except Exception:  # noqa: BLE001
        return None
    spent = {str(r.get("owner_id")): int((r.get("settings") or {}).get("waiver_budget_used") or 0)
             for r in rows if r.get("owner_id")}
    left = sorted(budget - v for v in spent.values()) or [budget]
    return {"budget": budget, "spent": spent,
            "median_left": left[len(left) // 2]}


# --------------------------------------------------------------------- opponent
def opponent(meta, week: int, my_team: str) -> Optional[dict]:
    """{owner_id, roster_id, points} for this week's opponent, or None before the
    season starts (no matchups published yet)."""
    if getattr(meta, "platform", "") != "sleeper" or not my_team:
        return None
    try:
        rows = api.get_matchups(str(meta.league_id), int(week)) or []
        rosters = api.get_rosters(str(meta.league_id)) or []
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    owner_of = {r.get("roster_id"): str(r.get("owner_id")) for r in rosters}
    mine = next((r for r in rows if owner_of.get(r.get("roster_id")) == str(my_team)), None)
    if not mine or mine.get("matchup_id") is None:
        return None
    opp = next((r for r in rows
                if r.get("matchup_id") == mine.get("matchup_id")
                and r.get("roster_id") != mine.get("roster_id")), None)
    if not opp:
        return None
    return {"owner_id": owner_of.get(opp.get("roster_id")),
            "roster_id": opp.get("roster_id"),
            "points": opp.get("points"),
            "starters": [str(p) for p in (opp.get("starters") or []) if p and str(p) != "0"]}
