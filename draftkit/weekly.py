"""In-season analysis: the numbers behind the weekly screens.

Deliberately separate from the UI, and from the draft path. Everything here
answers one shape of question — *what does this do to my lineup this week* —
because that is what makes an in-season screen worth opening. A projection you
can read on Sleeper is not worth a tab.

Nothing in this module writes anywhere or touches the draft modules.
"""
from __future__ import annotations

import math
import statistics
from typing import Dict, List, Optional

from . import lineup as LU, sleeper_client as api

# ---------------------------------------------------------------- variance
#
# Win probability needs a spread, not just a mean: a QB projected 21 with a 9-point
# floor is not the asset a steady 18 is. Real per-player variance would come from
# game logs, but early in a season there are none, and a projection-scaled
# positional coefficient of variation is close enough to rank decisions by — it
# gets the ORDER of risk right, which is all these screens use it for.
#
# Values are the rough within-season CV of weekly PPR scoring by position: QBs are
# the steadiest startable asset, TEs and DSTs the most volatile.
_CV = {"QB": 0.34, "RB": 0.52, "WR": 0.58, "TE": 0.62, "K": 0.48, "DST": 0.75}
_CV_DEFAULT = 0.55
_FLOOR_SD = 1.5          # even a 2-point projection is not deterministic


def player_sd(pos: str, mean: float) -> float:
    """Standard deviation of one player's week."""
    return max(_FLOOR_SD, float(mean or 0.0) * _CV.get((pos or "").upper(), _CV_DEFAULT))


def team_distribution(pids, slots, proj: dict, registry, byes=None, week=None):
    """(mean, sd) of a roster's BEST legal lineup — not of the roster.

    Uses the optimiser, so it answers "what will this team actually score" rather
    than "what do its best players project", which differ whenever someone is
    forced to start a bench body.
    """
    lu = LU.optimize(list(pids or []), None, slots, proj, registry, byes=byes, week=week)
    mean, var = 0.0, 0.0
    for sp in getattr(lu, "spots", []) or []:
        pid = getattr(sp, "pid", None)
        if not pid:
            continue
        p = float(proj.get(str(pid)) or 0.0)
        mean += p
        var += player_sd(_pos(registry, pid), p) ** 2
    return mean, math.sqrt(var) if var else 1.0


def win_prob(a_mean: float, a_sd: float, b_mean: float, b_sd: float) -> float:
    """P(A beats B), treating each team total as normal and independent.

    Independent is a simplification — shared game stacks correlate — but the error
    is small next to projection error, and it keeps this explainable.
    """
    sd = math.sqrt((a_sd or 1.0) ** 2 + (b_sd or 1.0) ** 2) or 1.0
    z = (a_mean - b_mean) / sd
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _pos(registry, pid) -> str:
    try:
        return (registry.meta(str(pid)).position or "").upper()
    except Exception:  # noqa: BLE001
        return ""


def _name(registry, pid) -> str:
    try:
        return registry.meta(str(pid)).name
    except Exception:  # noqa: BLE001
        return str(pid)


# ---------------------------------------------------------------- lineup check
def lineup_check(pids, slots, proj: dict, registry, byes=None, week=None) -> dict:
    """Current best lineup, and what each slot costs if it is wrong.

    Returns {spots: [...], mean, sd, gain, fixes: [...]}. A "fix" is only reported
    when swapping actually raises the TEAM total — swapping a WR you would flex
    anyway moves nothing, and saying otherwise is how a tool loses trust.
    """
    lu = LU.optimize(list(pids or []), None, slots, proj, registry, byes=byes, week=week)
    best = [(getattr(s, "slot", ""), getattr(s, "pid", None)) for s in (getattr(lu, "spots", []) or [])]
    base_mean, base_sd = team_distribution(pids, slots, proj, registry, byes, week)
    started = {str(p) for _, p in best if p}
    bench = [str(p) for p in (pids or []) if str(p) not in started]

    fixes = []
    for i, (slot, pid) in enumerate(best):
        if not pid:
            continue
        for b in bench:
            if not LU.slot_accepts(slot, _pos(registry, b)):
                continue
            swapped = [p for p in pids if str(p) != str(pid)] + [b]
            m, _ = team_distribution(swapped, slots, proj, registry, byes, week)
            gain = m - base_mean
            if gain > 0.05:
                fixes.append({"slot": slot, "out": str(pid), "in": b, "gain": round(gain, 1)})
                break
    fixes.sort(key=lambda f: -f["gain"])
    return {"spots": best, "mean": base_mean, "sd": base_sd,
            "bench": bench, "fixes": fixes,
            "gain": round(sum(f["gain"] for f in fixes), 1)}


# ---------------------------------------------------------------- waivers
def waiver_board(my_pids, slots, proj: dict, registry, free_agents: List[dict],
                 *, byes=None, week=None, limit: int = 12) -> List[dict]:
    """Free agents ranked by what they add to YOUR starting lineup.

    This is the whole reason the tab exists. The top add in fantasy is worth
    nothing to a team that already starts someone better at that slot, and a
    generic "best available" list cannot tell you that.
    """
    base, _ = team_distribution(my_pids, slots, proj, registry, byes, week)
    rows = []
    for fa in free_agents or []:
        pid = str(fa.get("pid") or fa.get("player_id") or "")
        if not pid or pid in {str(p) for p in my_pids}:
            continue
        m, _ = team_distribution(list(my_pids) + [pid], slots, proj, registry, byes, week)
        gain = m - base
        rows.append({"pid": pid, "name": _name(registry, pid), "pos": _pos(registry, pid),
                     "proj": round(float(proj.get(pid) or 0.0), 1),
                     "gain": round(gain, 1), "starts": gain > 0.05})
    rows.sort(key=lambda r: (-r["gain"], -r["proj"]))
    return rows[:limit]


def bid_guidance(gain: float, budget_left: int, weeks_left: int) -> dict:
    """A bid range from what the player is worth to YOU, not from his ADP.

    Anchored on points-per-week gained over the rest of the season as a share of
    the budget you have left to spend across the weeks you have left.
    """
    if gain <= 0.05 or budget_left <= 0:
        return {"low": 0, "high": 0, "note": "no lineup upgrade — don't spend"}
    season_pts = gain * max(1, weeks_left)
    # 1 point of season-long upgrade ≈ 1.5% of the remaining budget, capped so a
    # single claim can never eat a budget that has to last the rest of the year.
    pct = min(0.35, 0.015 * season_pts)
    mid = budget_left * pct
    return {"low": max(1, int(mid * 0.8)), "high": max(1, int(mid * 1.25)),
            "note": f"{gain:+.1f}/wk over {weeks_left} weeks"}


# ---------------------------------------------------------------- matchup
def swing_players(my_pids, opp_pids, slots, proj, registry, *, byes=None, week=None,
                  top: int = 4) -> List[dict]:
    """Whose week decides this game.

    For each starter on both sides, the win probability if he hits his ceiling
    versus his floor. The gap is how much of the result rests on him — which is a
    far more useful thing to look at on Sunday morning than a projection.
    """
    mm, ms = team_distribution(my_pids, slots, proj, registry, byes, week)
    om, os_ = team_distribution(opp_pids, slots, proj, registry, byes, week)
    out = []
    for side, pids in (("you", my_pids), ("opp", opp_pids)):
        lu = LU.optimize(list(pids or []), None, slots, proj, registry, byes=byes, week=week)
        for sp in getattr(lu, "spots", []) or []:
            pid = getattr(sp, "pid", None)
            if not pid:
                continue
            mean = float(proj.get(str(pid)) or 0.0)
            sd = player_sd(_pos(registry, pid), mean)
            hi, lo = mean + 1.5 * sd, max(0.0, mean - 1.5 * sd)
            if side == "you":
                p_hi = win_prob(mm - mean + hi, ms, om, os_)
                p_lo = win_prob(mm - mean + lo, ms, om, os_)
            else:
                p_hi = win_prob(mm, ms, om - mean + hi, os_)
                p_lo = win_prob(mm, ms, om - mean + lo, os_)
            out.append({"pid": str(pid), "name": _name(registry, pid), "side": side,
                        "pos": _pos(registry, pid), "proj": round(mean, 1),
                        "ceiling": round(hi, 1), "floor": round(lo, 1),
                        "p_hi": round(100 * p_hi), "p_lo": round(100 * p_lo),
                        "swing": round(100 * abs(p_hi - p_lo))})
    out.sort(key=lambda r: -r["swing"])
    return out[:top]


def weakest_slot(pids, slots, proj, registry, *, byes=None, week=None):
    """The opponent's softest starting slot — where streaming beats them."""
    lu = LU.optimize(list(pids or []), None, slots, proj, registry, byes=byes, week=week)
    worst = None
    for sp in getattr(lu, "spots", []) or []:
        pid = getattr(sp, "pid", None)
        if not pid:
            continue
        p = float(proj.get(str(pid)) or 0.0)
        if worst is None or p < worst[1]:
            worst = (getattr(sp, "slot", ""), p, str(pid))
    return worst


# ---------------------------------------------------------------- trades
def trade_ideas(my_pids, their_pids, slots, proj, registry, *, byes=None, week=None,
                max_ideas: int = 4) -> List[dict]:
    """One-for-one swaps, scored for BOTH sides.

    Deals that only help you are noise — they never get accepted. Ranked so the
    mutually positive ones come first, and the lopsided ones are labelled as the
    fantasies they are rather than quietly listed alongside.
    """
    my_base, _ = team_distribution(my_pids, slots, proj, registry, byes, week)
    th_base, _ = team_distribution(their_pids, slots, proj, registry, byes, week)
    ideas = []
    for mine in my_pids:
        for theirs in their_pids:
            if _pos(registry, mine) == _pos(registry, theirs):
                continue                     # same-position swaps rarely move a lineup
            m_after = [p for p in my_pids if str(p) != str(mine)] + [str(theirs)]
            t_after = [p for p in their_pids if str(p) != str(theirs)] + [str(mine)]
            mg = team_distribution(m_after, slots, proj, registry, byes, week)[0] - my_base
            tg = team_distribution(t_after, slots, proj, registry, byes, week)[0] - th_base
            if mg <= 0.05:
                continue
            ideas.append({"send": str(mine), "send_name": _name(registry, mine),
                          "get": str(theirs), "get_name": _name(registry, theirs),
                          "you": round(mg, 1), "them": round(tg, 1),
                          "mutual": tg > 0.05})
    ideas.sort(key=lambda i: (not i["mutual"], -(i["you"] + max(0.0, i["them"]))))
    # One idea per player, each side. Without this the single best target on their
    # roster comes back as the answer to every one of your tradeable players —
    # "send Nabers for Bijan / send Golden for Bijan / send Cooper for Bijan" — which
    # is one idea printed three times, and reads as a tool that cannot count.
    seen_out, seen_in, uniq = set(), set(), []
    for i in ideas:
        if i["send"] in seen_out or i["get"] in seen_in:
            continue
        seen_out.add(i["send"])
        seen_in.add(i["get"])
        uniq.append(i)
        if len(uniq) >= max_ideas:
            break
    return uniq


# ---------------------------------------------------------------- season odds
def season_odds(team_means: Dict[int, float], team_sds: Dict[int, float],
                records: Dict[int, tuple], weeks_left: int, playoff_teams: int,
                *, n_sims: int = 3000, seed: int = 7) -> Dict[int, dict]:
    """Playoff odds from here: current records + simulated remaining weeks.

    A balanced round-robin stands in for the real remaining schedule, the same
    approximation the Report Card already makes, for the same reason — the actual
    fixture list is not exposed uniformly across platforms.
    """
    import random
    rng = random.Random(seed)
    teams = sorted(team_means)
    n = len(teams)
    if n < 2:
        return {}
    made = {t: 0 for t in teams}
    seeds = {t: 0.0 for t in teams}
    for _ in range(n_sims):
        wins = {t: float(records.get(t, (0, 0))[0]) for t in teams}
        pts = {t: 0.0 for t in teams}
        for _w in range(max(0, weeks_left)):
            shuffled = teams[:]
            rng.shuffle(shuffled)
            for i in range(0, n - 1, 2):
                a, b = shuffled[i], shuffled[i + 1]
                sa = rng.gauss(team_means[a], team_sds.get(a, 20) or 20)
                sb = rng.gauss(team_means[b], team_sds.get(b, 20) or 20)
                pts[a] += sa
                pts[b] += sb
                wins[a if sa >= sb else b] += 1
        order = sorted(teams, key=lambda t: (-wins[t], -pts[t]))
        for i, t in enumerate(order):
            seeds[t] += i + 1
            if i < playoff_teams:
                made[t] += 1
    return {t: {"playoff_pct": round(100 * made[t] / n_sims),
                "avg_seed": round(seeds[t] / n_sims, 1)} for t in teams}


# ---------------------------------------------------------------- league pulse
def luck(points_for: float, wins: int, games: int, league_points: List[float]) -> dict:
    """Wins above/below what this team's scoring deserved.

    Expected wins = the share of the league you would beat with your own scoring,
    which is the standard "all-play" record. A 2-0 team scoring 8th of 8 is not
    good, and the standings will not tell you that until it is too late to trade
    with them.
    """
    if not games or len(league_points) < 2:
        return {"exp_wins": 0.0, "delta": 0.0, "label": "—"}
    per = points_for / games
    others = [p for p in league_points if p != points_for] or [per]
    beat = sum(1 for o in others if per > (o / games if games else o))
    exp = beat / max(1, len(others)) * games
    d = wins - exp
    label = ("lucky" if d >= 1 else "unlucky" if d <= -1 else "earned")
    return {"exp_wins": round(exp, 1), "delta": round(d, 1), "label": label}


def transactions(league_id: str, week: int, limit: int = 12) -> List[dict]:
    """Recent adds/drops/trades. Sleeper only; empty elsewhere or on failure —
    an activity feed is never worth breaking a page for."""
    out = []
    for w in range(week, max(0, week - 3), -1):
        try:
            rows = api._get(f"league/{league_id}/transactions/{w}") or []
        except Exception:  # noqa: BLE001
            continue
        for t in rows:
            if (t.get("status") or "") != "complete":
                continue
            out.append({"type": t.get("type"), "week": w,
                        "adds": t.get("adds") or {}, "drops": t.get("drops") or {},
                        "bid": ((t.get("settings") or {}).get("waiver_bid")),
                        "roster_ids": t.get("roster_ids") or []})
            if len(out) >= limit:
                return out
    return out


# ---------------------------------------------------------------- keepers
def keeper_outlook(my_pids, *, drafted_round: Dict[str, int], existing: Dict[str, dict],
                   rules: dict, n_teams: int, adp_rank, registry, proj: dict) -> List[dict]:
    """What each player on your roster costs to keep NEXT year, and whether he is
    worth it.

    The first cut of this screen priced every player at the last round, because it
    reused ``inseason.keeper_price`` — which answers a different question: what a
    WAIVER ADD would cost. A player you drafted in round 3 does not cost round 14,
    and a screen that says he does is worse than no screen, because it reads as a
    roster full of bargains.

    Cost comes from where he actually came from:
      · already a keeper  -> his current cost round, escalated by the league's
        per-year bump, and unkeepable once he passes max_keep_years
      · drafted this year -> the round he went in
      · rookie in a rookie slot -> the league's fixed rookie round
      · free-agent add    -> the last round

    Worth is his consensus draft position. Surplus is the gap, in picks: a player
    who would go at pick 25 costing a round-14 pick (≈105th) is +80 picks of
    surplus, and that is a number you can rank a roster by.
    """
    bump = int(rules.get("year2_bump_rounds") or 0)
    max_years = int(rules.get("max_keep_years") or 99)
    rookie_round = rules.get("rookie_fixed_round")
    last_round = int(rules.get("_last_round") or 0)
    out = []
    for pid in my_pids:
        pid = str(pid)
        try:
            pm = registry.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        is_rookie = getattr(pm, "years_exp", None) == 0
        prev = existing.get(pid) or {}
        years_kept = int(prev.get("keep_year") or 0)
        note, cost, blocked = "", None, None

        if prev:
            cost = int(prev.get("cost_round") or 0) - bump
            years_kept += 1
            note = f"kept {years_kept}x · was R{prev.get('cost_round')}"
            if years_kept > max_years:
                blocked = f"max {max_years} keeper years reached"
        elif is_rookie and rookie_round:
            cost = int(rookie_round)
            note = "rookie slot"
        elif pid in drafted_round:
            cost = int(drafted_round[pid])
            note = f"drafted R{drafted_round[pid]}"
        elif last_round:
            cost = last_round
            note = "waiver add"

        if not cost or cost < 1:
            if cost is not None and cost < 1:
                blocked = blocked or "cost would pass round 1"
            cost = max(1, cost or 1)

        cost_pick = (cost - 1) * max(1, n_teams) + 1
        worth = None
        try:
            worth = adp_rank(pm.name, pm.position)
        except Exception:  # noqa: BLE001
            worth = None
        surplus = (cost_pick - worth) if worth else None
        out.append({"pid": pid, "name": pm.name, "pos": pm.position, "team": pm.team,
                    "cost_round": cost, "cost_pick": cost_pick, "worth": worth,
                    "surplus": round(surplus) if surplus is not None else None,
                    "rookie": bool(is_rookie), "note": note, "blocked": blocked,
                    "proj": round(float(proj.get(pid) or 0.0), 1)})

    # Fill the league's actual slots, best surplus first, rookies against their own
    # allowance — telling someone eleven players are bargains when he may keep five
    # is not advice.
    reg_max = int(rules.get("max_regular_keepers") or 0)
    rook_max = int(rules.get("max_rookie_keepers") or 0)
    ranked = sorted([r for r in out if r["surplus"] is not None and not r["blocked"]],
                    key=lambda r: -r["surplus"])
    r_used = k_used = 0
    for r in ranked:
        if r["rookie"] and rookie_round and k_used < rook_max:
            r["verdict"], k_used = "keep", k_used + 1
        elif not r["rookie"] and r_used < reg_max:
            r["verdict"], r_used = "keep", r_used + 1
        else:
            r["verdict"] = "cut"
    for r in out:
        r.setdefault("verdict", "blocked" if r["blocked"] else "cut")
    out.sort(key=lambda r: (r["verdict"] != "keep", -(r["surplus"] or -9999)))
    return out
