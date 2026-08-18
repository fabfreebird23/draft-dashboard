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


def team_distribution(pids, slots, proj: dict, registry, byes=None, week=None,
                      current=None):
    """(mean, sd) of a lineup — the one that is SET if we know it, else the best legal one.

    `current` is the platform's starters. Pass it and you get what this team will
    actually score if nobody touches anything; leave it off and you get the team's
    ceiling. The distinction is the whole matchup screen: two rosters at the same
    strength are not the same opponent if one of them left a bye week in at RB.

    Without `current` this uses the optimiser, so it still answers "what will this
    team score" rather than "what do its best players project" — a roster forced to
    start a bench body is weaker than its names suggest.
    """
    cur = [str(x) for x in (current or []) if str(x) not in ("0", "")]
    if cur:
        used = cur
    else:
        lu = LU.optimize(list(pids or []), None, slots, proj, registry, byes=byes, week=week)
        used = [getattr(sp, "pid", None) for sp in (getattr(lu, "spots", []) or [])]
    mean, var = 0.0, 0.0
    for pid in used:
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


# ---------------------------------------------------------------- fast scoring
class _ProjView:
    """Adapter so the greedy lineup filler can read a plain {pid: points} dict."""
    __slots__ = ("_p",)

    def __init__(self, proj):
        self._p = proj

    def proj_of(self, pid):
        return float(self._p.get(str(pid)) or 0.0)


def fast_score(pids, slots, proj, registry) -> float:
    """Best-lineup points, greedily.

    The exact optimiser costs ~21ms, which is fine once and ruinous inside a search:
    a 2-for-1 sweep is ~650 evaluations per trade partner, so ~95 SECONDS across a
    league. The greedy filler in ``grades`` costs 0.023ms — 900x faster — and on 400
    random rosters of 9-18 players it returned an IDENTICAL score every time, worst
    gap 0.00. So searches run on this and the handful of surviving ideas are
    re-scored exactly, which is the only place the difference could ever show.
    """
    from . import grades
    return grades.optimal_lineup(list(pids or []), slots, registry, _ProjView(proj))[1]


# ---------------------------------------------------------------- lineup check
def lineup_check(pids, slots, proj: dict, registry, byes=None, week=None,
                 current=None) -> dict:
    """Your ACTUAL lineup, the best available one, and the moves between them.

    The first version took no `current` at all: it optimised the roster, called the
    result "your lineup", and then looked for improvements to it. Comparing a lineup
    to itself can only ever return "optimal, nothing to change", which is what it
    told him while he had a different lineup set on Sleeper leaving 0.7 points on
    the bench. A screen whose headline answer is structurally fixed is worse than no
    screen.

    `current` is the platform's own starter list, in slot order ("0" for an empty
    slot). When it is missing — a platform that does not expose it — that is stated
    rather than papered over by substituting the optimal.

    Moves are computed on the SET of starters, not slot by slot. Sleeper reports
    Love at RB and Brown at FLEX where the optimiser says the reverse; nobody's week
    changes, and telling him to make five moves when only one alters who plays would
    burn the screen's credibility on noise.
    """
    lu = LU.optimize(list(pids or []), None, slots, proj, registry, byes=byes, week=week)
    opt = [(getattr(s, "slot", ""), getattr(s, "pid", None)) for s in (getattr(lu, "spots", []) or [])]
    opt_total, opt_sd = team_distribution(pids, slots, proj, registry, byes, week)

    have_current = bool(current)
    cur = [(sl, (str(p) if str(p) not in ("0", "None", "") else None))
           for sl, p in zip(slots, list(current or []))] if have_current else list(opt)
    cur_total = sum(float(proj.get(str(p)) or 0.0) for _s, p in cur if p)

    cur_set = {p for _s, p in cur if p}
    opt_set = {str(p) for _s, p in opt if p}
    to_start = [p for p in (str(x) for _s, x in opt if x) if p not in cur_set]
    to_bench = [p for _s, p in cur if p and p not in opt_set]

    # Pair each benching with the start it pays for, cheapest pairing first, so the
    # per-move gain adds up to the total instead of double counting.
    moves, running = [], list(cur_set)
    for out_p, in_p in zip(to_bench, to_start):
        before = fast_score(running, slots, proj, registry)
        after_set = [x for x in running if x != out_p] + [in_p]
        gain = fast_score(after_set, slots, proj, registry) - before
        moves.append({"out": out_p, "in": in_p, "gain": round(gain, 1),
                      "out_pos": _pos(registry, out_p), "in_pos": _pos(registry, in_p)})
        running = after_set
    moves.sort(key=lambda m: -m["gain"])

    started = {str(p) for _s, p in (cur if have_current else opt) if p}
    bench = [str(p) for p in (pids or []) if str(p) not in started]
    return {"spots": opt, "current": cur, "optimal": opt,
            "have_current": have_current,
            "mean": opt_total, "sd": opt_sd,
            "current_total": round(cur_total, 1), "optimal_total": round(opt_total, 1),
            "bench": bench, "fixes": moves, "moves": moves,
            "gain": round(opt_total - cur_total, 1) if have_current else 0.0,
            "is_optimal": have_current and not moves}


# ---------------------------------------------------------------- waivers
def waiver_board(my_pids, slots, proj: dict, registry, free_agents: List[dict],
                 *, byes=None, week=None, limit: int = 12, ecr: dict = None) -> List[dict]:
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
                     "ecr": ((ecr or {}).get(pid) or {}).get("ecr"),
                     "gain": round(gain, 1), "starts": gain > 0.05})
    # Most weeks nothing on the wire cracks the lineup, so every gain ties at 0.0
    # and the TIEBREAK is what the reader actually sees. Projected points is the
    # wrong one: it is not comparable across positions and buries the wire's best
    # running back under a dozen replacement-level quarterbacks.
    rows.sort(key=lambda r: (-r["gain"], r["ecr"] is None, r["ecr"] or 0.0, -r["proj"]))
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
    my_base = fast_score(my_pids, slots, proj, registry)
    th_base = fast_score(their_pids, slots, proj, registry)
    ideas = []
    for mine in my_pids:
        for theirs in their_pids:
            if _pos(registry, mine) == _pos(registry, theirs):
                continue                     # same-position swaps rarely move a lineup
            m_after = [p for p in my_pids if str(p) != str(mine)] + [str(theirs)]
            t_after = [p for p in their_pids if str(p) != str(theirs)] + [str(mine)]
            mg = fast_score(m_after, slots, proj, registry) - my_base
            tg = fast_score(t_after, slots, proj, registry) - th_base
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

    # Re-score the survivors with the exact optimiser. Cheap at this size, and it
    # means the numbers on screen never come from the approximation.
    exact_mine = team_distribution(my_pids, slots, proj, registry, byes, week)[0]
    exact_th = team_distribution(their_pids, slots, proj, registry, byes, week)[0]
    for i in uniq:
        m_after = [p for p in my_pids if str(p) not in i["send"]] + list(i["get"])
        t_after = [p for p in their_pids if str(p) not in i["get"]] + list(i["send"])
        i["you"] = round(team_distribution(m_after, slots, proj, registry, byes, week)[0] - exact_mine, 1)
        i["them"] = round(team_distribution(t_after, slots, proj, registry, byes, week)[0] - exact_th, 1)
        i["mutual"] = i["them"] > 0.05
    uniq.sort(key=lambda i: (not i["mutual"], -(i["you"] + max(0.0, i["them"]))))
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
    def _int(v, default=0):
        """Keeper records are hand-maintained in the hub, so a field that is an int
        for one player is the string "Rookie" for another. Coerce, never crash."""
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    bump = _int(rules.get("year2_bump_rounds"))
    max_years = _int(rules.get("max_keep_years"), 99)
    rookie_round = rules.get("rookie_fixed_round")
    last_round = _int(rules.get("_last_round"))
    out = []
    for pid in my_pids:
        pid = str(pid)
        try:
            pm = registry.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        is_rookie = getattr(pm, "years_exp", None) == 0
        prev = existing.get(pid) or {}
        rookie_slot = False
        # "Rookie" appears here as a keep_year for rookie-slot keepers.
        raw_year = prev.get("keep_year")
        rookie_slot = str(raw_year).strip().lower() == "rookie" or bool(prev.get("is_rookie_keeper"))
        years_kept = _int(raw_year, 1 if rookie_slot else 0)
        note, cost, blocked = "", None, None

        if prev:
            cost = _int(prev.get("cost_round")) - (0 if rookie_slot else bump)
            years_kept += 1
            note = f"kept {years_kept}x · was R{prev.get('cost_round')}"
            if years_kept > max_years:
                blocked = f"max {max_years} keeper years reached"
        elif is_rookie and rookie_round:
            cost = _int(rookie_round)
            rookie_slot = True
            note = "rookie slot"
        elif pid in drafted_round:
            cost = _int(drafted_round[pid])
            note = f"drafted R{drafted_round[pid]}"
        elif last_round:
            cost = last_round
            note = "waiver add"

        if not cost or cost < 1:
            if cost is not None and cost < 1:
                blocked = blocked or "cost would pass round 1"
            cost = max(1, cost or 1)

        cost_pick = (cost - 1) * max(1, n_teams) + 1
        # a rookie-slot keeper occupies a rookie slot, not a regular one
        rookie_slotted = bool(rookie_slot)
        worth = None
        try:
            worth = adp_rank(pm.name, pm.position)
        except Exception:  # noqa: BLE001
            worth = None
        surplus = (cost_pick - worth) if worth else None
        out.append({"pid": pid, "name": pm.name, "pos": pm.position, "team": pm.team,
                    "cost_round": cost, "cost_pick": cost_pick, "worth": worth,
                    "surplus": round(surplus) if surplus is not None else None,
                    "rookie": bool(rookie_slotted or is_rookie), "note": note,
                    "blocked": blocked,
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
            r["verdict"], r["slot_used"], k_used = "keep", "rookie", k_used + 1
        elif r_used < reg_max:
            # A rookie who misses the rookie allowance falls back to a REGULAR slot
            # rather than being cut. Barring him produced the obviously wrong call
            # of keeping a −19 player over a +64 one purely because the +64 happened
            # to be a rookie. ASSUMPTION: a rookie may be kept as a regular keeper.
            # If this league forbids that, the rookie rows are the ones to check.
            r["verdict"], r["slot_used"], r_used = "keep", "regular", r_used + 1
        else:
            r["verdict"] = "cut"
    for r in out:
        r.setdefault("verdict", "blocked" if r["blocked"] else "cut")
    out.sort(key=lambda r: (r["verdict"] != "keep", -(r["surplus"] or -9999)))
    return out


# ---------------------------------------------------------------- packages
def trade_packages(my_pids, their_pids, slots, proj, registry, *, byes=None, week=None,
                   shapes=((2, 1), (1, 2)), pool: int = 9, max_ideas: int = 6) -> List[dict]:
    """Multi-player deals — 2-for-1 consolidation and 1-for-2 depth.

    One-for-one swaps rarely clear in a real league: they only work when two
    managers happen to have exactly mirrored holes. Consolidation is the shape
    most trades actually take — two useful players for one better one, which suits
    the side with depth and a hole, and the other side with a stud and thin slots.

    Cost control matters here. The naive search is C(16,2) x 16 per partner, which
    is ~2k optimiser runs for one team and ~14k across a league. Both sides are cut
    to their `pool` most relevant players first: for the sender, the ones whose
    removal costs the least; for the receiver, the ones worth having. That turns it
    into a few hundred evaluations without losing the deals a human would spot.

    A 2-for-1 also SHRINKS your roster by one, which is a real cost this does not
    model — the freed slot is worth something only if there is a waiver add worth
    making. Treat the gains as the lineup effect, not the whole story.
    """
    my_base = fast_score(my_pids, slots, proj, registry)
    th_base = fast_score(their_pids, slots, proj, registry)

    def _rank(pids, reverse=False):
        vals = sorted(((float(proj.get(str(p)) or 0.0), str(p)) for p in pids), reverse=not reverse)
        return [p for _v, p in vals]

    # senders: cheapest to lose first; receivers: best first
    mine_cheap = _rank(my_pids, reverse=True)[:pool]
    mine_best = _rank(my_pids)[:pool]
    theirs_best = _rank(their_pids)[:pool]
    theirs_cheap = _rank(their_pids, reverse=True)[:pool]

    ideas = []
    for out_n, in_n in shapes:
        if out_n == 2 and in_n == 1:
            senders = [(a, b) for i, a in enumerate(mine_cheap) for b in mine_cheap[i + 1:]]
            receivers = [(c,) for c in theirs_best]
        elif out_n == 1 and in_n == 2:
            senders = [(a,) for a in mine_best]
            receivers = [(c, d) for i, c in enumerate(theirs_cheap) for d in theirs_cheap[i + 1:]]
        else:
            continue
        for outs in senders:
            for ins in receivers:
                m_after = [p for p in my_pids if str(p) not in outs] + list(ins)
                t_after = [p for p in their_pids if str(p) not in ins] + list(outs)
                mg = fast_score(m_after, slots, proj, registry) - my_base
                if mg <= 0.05:
                    continue
                tg = fast_score(t_after, slots, proj, registry) - th_base
                ideas.append({
                    "shape": f"{out_n}-for-{in_n}",
                    "send": list(outs), "get": list(ins),
                    "send_names": [_name(registry, p) for p in outs],
                    "get_names": [_name(registry, p) for p in ins],
                    "you": round(mg, 1), "them": round(tg, 1),
                    "mutual": tg > 0.05,
                    "roster_delta": in_n - out_n,
                })

    ideas.sort(key=lambda i: (not i["mutual"], -(i["you"] + max(0.0, i["them"]))))
    # Same rule as everywhere else: a player can only be in one deal. Without it the
    # one obvious target comes back attached to every package you could build.
    used, uniq = set(), []
    for i in ideas:
        names = set(i["send"]) | set(i["get"])
        if names & used:
            continue
        used |= names
        uniq.append(i)
        if len(uniq) >= max_ideas:
            break
    return uniq


# ---------------------------------------------------------------- analyzer
def analyze_trade(my_pids, their_pids, send, get, slots, proj, registry, *,
                  byes=None, week=None, keeper_rows=None, weeks_left: int = 11) -> dict:
    """Judge a SPECIFIC proposal — the one sitting in your inbox.

    The finder answers "what deals exist"; this answers "should I accept this one",
    which is the question you actually get asked. Same engine, opposite direction.

    Four things are reported and deliberately kept separate, because they can point
    different ways and averaging them into a single score would hide exactly the
    disagreement you need to see:

      week      what it does to your lineup THIS week
      rest      the same, multiplied out over the weeks left — a small weekly edge
                compounds, and a 2-point gain for eleven weeks is a real haul
      keeper    surplus handed over vs surplus received, in draft picks
      roster    spots gained or lost, which a 2-for-1 quietly costs you

    `verdict` is a recommendation, not a score, and it says which of the four drove
    it. A deal that wins the week and loses a +76 keeper is not "slightly positive",
    it is two facts in tension.
    """
    send, get = [str(p) for p in send], [str(p) for p in get]
    mine_after = [p for p in my_pids if str(p) not in send] + get
    theirs_after = [p for p in their_pids if str(p) not in get] + send

    m0, s0 = team_distribution(my_pids, slots, proj, registry, byes, week)
    m1, s1 = team_distribution(mine_after, slots, proj, registry, byes, week)
    t0, _ = team_distribution(their_pids, slots, proj, registry, byes, week)
    t1, _ = team_distribution(theirs_after, slots, proj, registry, byes, week)

    # Only players the model would actually KEEP count as keeper value. Counting
    # every rostered player's surplus made shipping a -30 player look like a keeper
    # cost, and listed him under "shipping keepers" as though he were an asset. A
    # negative-surplus player is one you were never going to keep; losing him costs
    # nothing next year.
    krows = {r["pid"]: r for r in (keeper_rows or []) if r.get("verdict") == "keep"}
    out_k = [(p, krows[p]) for p in send if p in krows]
    in_k = [(p, krows[p]) for p in get if p in krows]
    k_out = sum(max(0, r["surplus"] or 0) for _p, r in out_k)
    k_in = sum(max(0, r["surplus"] or 0) for _p, r in in_k)

    week_delta = round(m1 - m0, 1)
    rest_delta = round(week_delta * max(1, weeks_left), 1)
    their_delta = round(t1 - t0, 1)
    keeper_delta = round(k_in - k_out) if (out_k or in_k) else None
    # incoming players are not on your roster, so their keeper cost to YOU is the
    # league's last round — priced by the UI, not guessed at here
    roster_delta = len(get) - len(send)

    # The verdict names its own driver rather than blending everything into a number.
    if week_delta <= 0.05:
        verdict, why = "reject", "it does not improve your lineup this week"
    elif keeper_delta is not None and keeper_delta <= -40 and week_delta < 4:
        verdict, why = ("reject",
                        f"a {week_delta:+.1f}/wk lineup gain does not pay for "
                        f"{abs(keeper_delta)} picks of keeper surplus")
    elif their_delta <= 0.05:
        verdict, why = ("send it, but expect a no",
                        "you gain and they do not — they have no reason to accept")
    elif week_delta >= 3:
        verdict, why = "accept", f"a clear {week_delta:+.1f}/wk upgrade that also helps them"
    else:
        verdict, why = ("marginal",
                        f"{week_delta:+.1f}/wk is inside the projections' own error bars")

    return {
        "week": week_delta, "rest": rest_delta, "them": their_delta,
        "keeper": keeper_delta, "roster": roster_delta,
        "mine_before": round(m0, 1), "mine_after": round(m1, 1),
        "theirs_before": round(t0, 1), "theirs_after": round(t1, 1),
        "out_keepers": [(_name(registry, p), r) for p, r in out_k],
        "in_keepers": [(_name(registry, p), r) for p, r in in_k],
        "verdict": verdict, "why": why,
        # lineup effect, slot by slot — where the change actually lands
        "before": lineup_check(my_pids, slots, proj, registry, byes, week)["spots"],
        "after": lineup_check(mine_after, slots, proj, registry, byes, week)["spots"],
    }


def counter_offers(my_pids, their_pids, send, get, slots, proj, registry, *,
                   byes=None, week=None, limit: int = 3) -> List[dict]:
    """If the proposal is close, what small change would make it work.

    Holds their ask fixed and varies what you send: the realistic negotiation is
    "not him, but I'll do this instead", not a different trade entirely.
    """
    get = [str(p) for p in get]
    base = team_distribution(my_pids, slots, proj, registry, byes, week)[0]
    th_base = team_distribution(their_pids, slots, proj, registry, byes, week)[0]
    out = []
    for cand in my_pids:
        cand = str(cand)
        if cand in get:
            continue
        mine_after = [p for p in my_pids if str(p) != cand] + get
        theirs_after = [p for p in their_pids if str(p) not in get] + [cand]
        mg = fast_score(mine_after, slots, proj, registry) - base
        tg = fast_score(theirs_after, slots, proj, registry) - th_base
        if mg <= 0.05 or tg <= 0.05:
            continue
        out.append({"send": [cand], "send_names": [_name(registry, cand)],
                    "get": get, "you": round(mg, 1), "them": round(tg, 1)})
    out.sort(key=lambda r: -(r["you"] + r["them"]))
    return out[:limit]


# ---------------------------------------------------------------- availability
#
# Sleeper ships injury_status, injury_body_part, injury_notes, practice_participation
# and practice_description on the player payload we ALREADY download for the
# registry — and until now nothing in-season read any of it. Four of his sixteen
# players were Questionable, three of them in the lineup the Command Center called
# fine. Availability is the single thing most likely to change a lineup, and it was
# the one thing the lineup screen could not see.
_SEV = {"OUT": 4, "IR": 4, "PUP": 4, "SUS": 4, "NA": 4,
        "DOUBTFUL": 3, "QUESTIONABLE": 2, "PROBABLE": 1, "DTD": 2}
_PRACTICE_RISK = {"DNP": 1, "LIMITED": 0, "FULL": -1}


def availability(pm) -> dict:
    """What we know about whether he plays, and how loudly to say it.

    Deliberately does NOT discount the projection. The host's projection already
    prices known absences, and quietly shaving points would make every number on
    every screen disagree with Sleeper for reasons the user cannot see. Flag it,
    show the evidence, offer the contingency — let him decide.
    """
    status = (getattr(pm, "injury_status", None) or "").strip()
    key = status.upper().replace(" ", "")
    sev = _SEV.get(key, 0)
    practice = (getattr(pm, "practice_participation", None) or "").strip()
    pkey = practice.upper().replace(" ", "").replace("PARTICIPATION", "")
    # Practice participation is the tell that moves a Questionable either way: a
    # DNP Friday is a different player from a full participant with the same tag.
    sev += _PRACTICE_RISK.get(pkey, 0) if sev else 0

    parts = [x for x in (getattr(pm, "injury_body_part", None),
                         getattr(pm, "injury_notes", None),
                         getattr(pm, "practice_description", None)) if x]
    return {
        "status": status or None,
        "severity": max(0, sev),
        "practice": practice or None,
        "detail": " · ".join(dict.fromkeys(parts)) or None,
        "playing": sev < 3,               # OUT/DOUBTFUL are effectively not playing
        "risky": sev >= 2,                # worth a flag on a starter
    }


def availability_report(pids, slots, proj, registry, *, byes=None, week=None,
                        starters=None) -> dict:
    """Roster-wide availability, and what it costs if the doubtful ones sit.

    The contingency is the useful half: knowing Nabers is Questionable is a fact,
    knowing your week drops 12.7 points and who replaces him is a decision.
    """
    rows, at_risk = [], []
    start_set = {str(p) for p in (starters or []) if str(p) not in ("0", "")}
    for pid in pids or []:
        pid = str(pid)
        try:
            pm = registry.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        av = availability(pm)
        if not av["status"] and not av["practice"]:
            continue
        av.update({"pid": pid, "name": pm.name, "pos": pm.position, "team": pm.team,
                   "starting": pid in start_set,
                   "proj": round(float(proj.get(pid) or 0.0), 1)})
        rows.append(av)
        if av["starting"] and av["risky"]:
            at_risk.append(av)

    # Contingency, measured against the lineup he ACTUALLY has set — not the
    # optimal one. Measured against optimal, a starter the optimiser would have
    # benched anyway "costs 0.0 if he sits", which is true of a lineup he is not
    # using and useless to a man deciding whether to bench him.
    start_list = [str(p) for p in (starters or []) if str(p) not in ("0", "")]
    cur_total = sum(float(proj.get(p) or 0.0) for p in start_list)
    risky_ids = {r["pid"] for r in at_risk}

    def _best_replacement(out_pid):
        """Best eligible bench player, preferring one who is himself healthy.

        The first cut happily nominated another Questionable player as the cover
        for a Questionable starter — advice that solves nothing."""
        out_pos = _pos(registry, out_pid)
        cands = []
        for b in pids:
            b = str(b)
            if b in start_list or b == out_pid:
                continue
            if not any(LU.slot_accepts(sl, _pos(registry, b)) for sl, sp in
                       zip(slots, start_list + [None] * len(slots)) if sp == out_pid or True):
                continue
            if _pos(registry, b) != out_pos and not any(
                    LU.slot_accepts("FLEX", _pos(registry, b)) for _ in (1,)):
                continue
            av_b = availability(registry.meta(b))
            cands.append((av_b["severity"] >= 2, -float(proj.get(b) or 0.0), b))
        cands.sort()
        return cands[0][2] if cands else None

    for r in at_risk:
        rep_pid = _best_replacement(r["pid"])
        r["replacement"] = _name(registry, rep_pid) if rep_pid else None
        r["replacement_risky"] = bool(rep_pid) and availability(
            registry.meta(rep_pid))["severity"] >= 2
        repl_pts = float(proj.get(rep_pid) or 0.0) if rep_pid else 0.0
        r["cost_if_out"] = round(r["proj"] - repl_pts, 1)

    # Several risky starters often nominate the SAME healthy body — he can only
    # cover one of them. Per-player "if he sits" is still the right question (they
    # rarely all sit), but the sharing has to be visible.
    from collections import Counter
    _rc = Counter(r.get("replacement") for r in at_risk if r.get("replacement"))
    for r in at_risk:
        r["replacement_shared"] = _rc.get(r.get("replacement"), 0) > 1

    all_out_total = cur_total
    for r in at_risk:
        all_out_total -= max(0.0, r["cost_if_out"])

    rows.sort(key=lambda r: (-r["severity"], -r["proj"]))
    return {"rows": rows, "at_risk": at_risk,
            "current_total": round(cur_total, 1),
            "cost_if_all_out": round(cur_total - all_out_total, 1),
            "n_risky_starters": len(at_risk)}
