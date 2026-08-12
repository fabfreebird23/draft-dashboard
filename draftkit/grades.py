"""Post-draft Report Card — letter-grade every team and project the season.

After a draft (mock or live) we have each team's roster. This module turns that
into a league report card:

  * **Grade (A+…F)** — curved off each team's projected *starting-lineup* points
    (best legal lineup from the league's roster slots), so the grade reflects the
    talent a team actually drafted relative to the rest of the league.
  * **Projected record + playoff/title odds** — a Monte-Carlo season. Real fantasy
    head-to-head matchups aren't set until the season starts, so we play a neutral
    balanced round-robin: each week is a real game (team score ~ Normal(mean, σ)),
    tally wins, seed the top N by record, and run a single-elim bracket. Repeated a
    few thousand times this yields expected wins, playoff %, and title %.
  * **Past records** — each manager's historical win % (from the league's prior
    seasons) nudges their projection up or down, so a proven team gets a small
    bump and a perennial cellar-dweller a small fade on top of their draft.

Everything keys off the live ``ctx`` (value engine, roster slots, owners), so it
serves Sleeper or ESPN identically.
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Tuple

import numpy as np

# Which positions can fill each flex-type slot label (slots come pre-normalized
# from the provider, but we stay liberal about the spellings we accept).
_FIXED = {"QB", "RB", "WR", "TE", "K", "DST", "DEF"}
_FLEX_MAP = {
    "FLEX": {"RB", "WR", "TE"}, "WRT": {"RB", "WR", "TE"},
    "W/R/T": {"RB", "WR", "TE"}, "RB/WR/TE": {"RB", "WR", "TE"},
    "WR/RB": {"RB", "WR"}, "REC_FLEX": {"WR", "TE"}, "WR/TE": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"}, "SUPERFLEX": {"QB", "RB", "WR", "TE"},
    "SFLEX": {"QB", "RB", "WR", "TE"}, "OP": {"QB", "RB", "WR", "TE"},
    "Q/W/R/T": {"QB", "RB", "WR", "TE"},
}

_HIST_K = 0.35          # how hard past win% nudges a team's weekly mean (× σ)


def optimal_lineup(pids, roster_slots, registry, value) -> Tuple[List[str], float]:
    """Best legal starting lineup from a roster. Fills fixed slots first, then flex
    slots most-restrictive-first, each time taking the highest-projected eligible
    player still on the bench. Returns (starter_pids, projected_points)."""
    pool: Dict[str, list] = {}
    for p in pids:
        try:
            pos = registry.meta(p).position
        except Exception:  # noqa: BLE001
            continue
        if not pos:
            continue
        pool.setdefault(pos, []).append((float(value.proj_of(str(p)) or 0.0), str(p)))
    for pos in pool:
        pool[pos].sort(reverse=True)            # best projection first
    idx = {pos: 0 for pos in pool}              # next-available index per position

    def take(eligible):
        best, best_pos = None, None
        for pos in eligible:
            i = idx.get(pos, 0)
            lst = pool.get(pos, [])
            if i < len(lst) and (best is None or lst[i][0] > best[0]):
                best, best_pos = lst[i], pos
        if best is None:
            return None
        idx[best_pos] += 1
        return best

    fixed = [s for s in roster_slots if s.upper() in _FIXED]
    flex = [s for s in roster_slots if s.upper() not in _FIXED]
    flex.sort(key=lambda s: len(_FLEX_MAP.get(s.upper(), {"RB", "WR", "TE"})))

    starters, pts = [], 0.0
    for s in fixed:
        t = take({s.upper()})
        if t:
            starters.append(t[1])
            pts += t[0]
    for s in flex:
        t = take(_FLEX_MAP.get(s.upper(), {"RB", "WR", "TE"}))
        if t:
            starters.append(t[1])
            pts += t[0]
    return starters, pts


def _letter(z: float) -> str:
    """Map a within-league z-score of projected starter points to a letter grade."""
    cuts = [(1.30, "A+"), (0.90, "A"), (0.60, "A-"), (0.35, "B+"), (0.10, "B"),
            (-0.15, "B-"), (-0.40, "C+"), (-0.70, "C"), (-1.00, "C-"), (-1.40, "D")]
    for thr, g in cuts:
        if z >= thr:
            return g
    return "F"


def league_format(ctx) -> Tuple[int, int]:
    """(regular_season_weeks, playoff_teams) from the league settings; sane defaults
    (14 weeks, 6 teams) when unavailable or non-Sleeper."""
    reg_weeks, playoff_teams = 14, 6
    if ctx["meta"].platform == "sleeper":
        try:
            from . import sleeper_client as sleeper
            s = (sleeper.get_league(str(ctx["meta"].league_id)) or {}).get("settings") or {}
            reg_weeks = max(1, int(s.get("playoff_week_start") or 15) - 1)
            playoff_teams = int(s.get("playoff_teams") or 6)
        except Exception:  # noqa: BLE001
            pass
    return reg_weeks, max(2, playoff_teams)


def historical_winpct(ctx, max_seasons: int = 5) -> Dict[str, Tuple[float, int]]:
    """{owner_id: (win_pct, games)} across the league's prior seasons (ties = ½).
    Sleeper only; returns {} for ESPN or if no history is reachable."""
    if ctx["meta"].platform != "sleeper":
        return {}
    try:
        from . import sleeper_client as sleeper
        chain = sleeper.league_chain(str(ctx["meta"].league_id)) or []
    except Exception:  # noqa: BLE001
        return {}
    cur = int(ctx["meta"].season)
    acc: Dict[str, list] = {}
    for entry in chain[:max_seasons + 1]:
        if int(entry.get("season") or 0) >= cur:
            continue                                # only completed prior seasons
        try:
            rosters = sleeper.get_rosters(entry["league_id"]) or []
        except Exception:  # noqa: BLE001
            continue
        for r in rosters:
            oid = str(r.get("owner_id") or "")
            s = r.get("settings") or {}
            w = int(s.get("wins") or 0)
            l = int(s.get("losses") or 0)
            t = int(s.get("ties") or 0)
            if oid and (w + l + t) > 0:
                a = acc.setdefault(oid, [0.0, 0.0])
                a[0] += w + 0.5 * t
                a[1] += l + 0.5 * t
    return {oid: (wl[0] / (wl[0] + wl[1]), int(wl[0] + wl[1]))
            for oid, wl in acc.items() if (wl[0] + wl[1]) > 0}


def _round_robin(n: int) -> List[List[Tuple[int, int]]]:
    """Circle-method round-robin: a list of rounds, each a list of (i, j) pairs.
    Odd team counts get one bye per round."""
    teams = list(range(n))
    if n % 2:
        teams.append(None)
    half = len(teams) // 2
    arr = teams[:]
    rounds = []
    for _ in range(len(teams) - 1):
        pairs = [(arr[i], arr[len(teams) - 1 - i]) for i in range(half)
                 if arr[i] is not None and arr[len(teams) - 1 - i] is not None]
        rounds.append(pairs)
        arr = [arr[0]] + [arr[-1]] + arr[1:-1]      # rotate, anchor first team
    return rounds


def _sim_bracket(seeds: List[int], means, sigma: float, rng) -> int:
    """Single-elim playoff with reseeding (top seed plays the lowest survivor) and
    byes for the top seeds when the field isn't a power of two. Returns the
    champion's team index."""
    alive = list(seeds)                              # already in seed order (best first)
    while len(alive) > 1:
        nxt = []
        a = alive[:]
        if len(a) % 2 == 1:                          # odd → top seed gets a bye
            nxt.append(a.pop(0))
        while a:
            hi, lo = a.pop(0), a.pop()               # best vs worst remaining
            sh = rng.normal(means[hi], sigma)
            sl = rng.normal(means[lo], sigma)
            nxt.append(hi if sh >= sl else lo)
        nxt.sort(key=seeds.index)                    # reseed by original strength
        alive = nxt
    return alive[0]


def league_report(rosters: Dict[int, list], ctx, n_sims: int = 4000) -> List[dict]:
    """Grade every team and project the season.

    ``rosters`` maps draft-slot -> [player_id, ...] (keepers + picks). Returns a
    list of per-team dicts (one per slot), each with grade, projected starter
    points, record, playoff/title odds, projected finish and the past-record input,
    sorted best-projected-record first.
    """
    reg_weeks, playoff_teams = league_format(ctx)
    playoff_teams = min(playoff_teams, ctx["meta"].num_teams)
    value, registry = ctx["value"], ctx["registry"]
    slots = ctx["roster_slots"]
    owner_by_slot = ctx.get("owner_by_slot", {})
    hist = historical_winpct(ctx)

    teams = sorted(rosters.keys())
    starters, starter_vorp, points = {}, {}, {}
    for t in teams:
        sp, pts = optimal_lineup(rosters[t], slots, registry, value)
        starters[t] = sp
        points[t] = pts
        starter_vorp[t] = sum(float(value.vorp_of(p) or 0.0) for p in sp)

    pvals = list(points.values()) or [0.0]
    mu = statistics.fmean(pvals)
    sd = statistics.pstdev(pvals) if len(pvals) > 1 and statistics.pstdev(pvals) else 1.0
    sigma = max(15.0, 0.20 * (mu or 100.0))          # weekly scoring noise

    # past-record nudge: shift each team's weekly mean by a fraction of σ toward
    # their historical win rate (rosters reset at the draft, so keep it small).
    adj = {}
    for t in teams:
        oid = str(owner_by_slot.get(t, ""))
        wp = hist.get(oid, (0.5, 0))[0]
        adj[t] = points[t] + _HIST_K * sigma * (wp - 0.5) * 2.0

    idxs = list(range(len(teams)))
    means = np.array([adj[teams[i]] for i in idxs], dtype=float)
    rng = np.random.default_rng(20260601)            # fixed seed → stable across reruns

    # ---- regular season: balanced round-robin, real weekly games ----
    rr = _round_robin(len(teams))
    scores = rng.normal(means, sigma, size=(n_sims, reg_weeks, len(teams)))
    wins = np.zeros((n_sims, len(teams)))
    for w in range(reg_weeks):
        for i, j in rr[w % len(rr)]:
            wi = scores[:, w, i] > scores[:, w, j]
            wins[:, i] += wi
            wins[:, j] += ~wi
    pts_total = scores.sum(axis=1)                   # (n_sims, n_teams) season points

    made = np.zeros(len(teams))
    champ = np.zeros(len(teams))
    bye = np.zeros(len(teams))
    finish_sum = np.zeros(len(teams))
    n_byes = 0
    p2 = 1
    while p2 < playoff_teams:
        p2 *= 2
    n_byes = p2 - playoff_teams                      # top seeds with a first-round bye
    for s in range(n_sims):
        order = sorted(idxs, key=lambda t: (wins[s, t], pts_total[s, t]), reverse=True)
        for rank, t in enumerate(order, 1):
            finish_sum[t] += rank
        seeds = order[:playoff_teams]
        for t in seeds:
            made[t] += 1
        for t in seeds[:n_byes]:
            bye[t] += 1
        champ[_sim_bracket(seeds, means, sigma, rng)] += 1

    rows = []
    for i, t in enumerate(teams):
        z = (points[t] - mu) / sd
        rows.append({
            "slot": t,
            "owner_id": str(owner_by_slot.get(t, "")),
            "grade": _letter(z),
            "proj_points": round(points[t], 1),
            "starter_vorp": round(starter_vorp[t]),
            "exp_wins": round(float(wins[:, i].mean()), 1),
            "exp_losses": round(reg_weeks - float(wins[:, i].mean()), 1),
            "reg_weeks": reg_weeks,
            "playoff_pct": round(100 * made[i] / n_sims),
            "bye_pct": round(100 * bye[i] / n_sims) if n_byes else None,
            "title_pct": round(100 * champ[i] / n_sims, 1),
            "avg_finish": round(float(finish_sum[i] / n_sims), 1),
            "starters": starters[t],
            "hist_winpct": hist.get(str(owner_by_slot.get(t, "")), (None, 0))[0],
            "hist_games": hist.get(str(owner_by_slot.get(t, "")), (None, 0))[1],
            "n_players": len(rosters[t]),
        })
    rows.sort(key=lambda r: (r["exp_wins"], r["title_pct"]), reverse=True)
    for seed, r in enumerate(rows, 1):
        r["proj_seed"] = seed
    return rows


def pick_regrets(board: Dict[int, str], my_slot: int, ctx, *, keeper_overalls=None,
                 limit: int = 6, pool_cap: int = 140, mu=None, sd=None) -> List[dict]:
    """The swaps that would most have raised your Report Card, one player each.

    Scored on the SAME number the Report Card grades — projected starter points
    from ``optimal_lineup`` — because a recap that optimises a different quantity
    than the grade it claims to improve is just a second opinion in the grade's
    clothing.

    Greedy and NON-OVERLAPPING. Scoring every pick independently is the obvious
    implementation and it produces nonsense: the same star comes back as the answer
    to all fourteen picks, because he improves every one of them and nothing stops
    him being spent twice. You can only draft a man once. So: take the single best
    (pick, player) pair, retire both, recompute, repeat.

    Recompute is the operative word — after a swap lands, the roster has changed,
    and the next swap is measured against the NEW lineup. Otherwise the gains are
    counted against a roster that no longer exists and adding them up overstates
    the total, usually badly, since two swaps at the same position mostly overlap.

    ONE ASSUMPTION, load-bearing: every other team's picks are held fixed. Taking
    Chase at 3.05 would really have changed what everyone after you did, so these
    are an upper bound on what a swap was worth, not a replay.

    That assumption is weakest where it matters most, so each row reports ``both``:
    whether the player you actually took was STILL on the board at your next pick.
    When true, it was never either/or — you could have had both, and the regret is
    real rather than hypothetical.
    """
    value, registry = ctx["value"], ctx["registry"]
    slots = ctx["roster_slots"]
    owner = ctx["pick_owner_slot"]
    keeper_overalls = set(int(o) for o in (keeper_overalls or ()))

    mine = sorted((int(ov), str(pid)) for ov, pid in board.items()
                  if owner(int(ov)) == my_slot and int(ov) not in keeper_overalls)
    if not mine:
        return []
    # the whole roster, keepers included — the grade is graded on all of it
    my_pids = [str(pid) for ov, pid in board.items() if owner(int(ov)) == my_slot]
    my_next = {ov: nxt for (ov, _), (nxt, _) in zip(mine, mine[1:])}
    drafted_at = {}
    for ov, pid in board.items():
        drafted_at.setdefault(str(pid), int(ov))

    # adp_pool is [{pid, name, pos, adp}, ...] already in draft order.
    universe = [str(r["pid"]) for r in (ctx.get("adp_pool") or []) if r.get("pid")]

    roster = list(my_pids)
    out, used_picks, used_cands = [], set(), set()
    for _ in range(max(1, limit)):
        base_pts = optimal_lineup(roster, slots, registry, value)[1]
        best = None                      # (gain, overall, took, candidate)
        for ov, took in mine:
            if ov in used_picks or took not in roster:
                continue
            gone = {str(p) for o, p in board.items() if int(o) < ov}
            without = [p for p in roster if p != took]
            held = set(without)
            n_seen = 0
            for c in universe:
                if c in gone or c in held or c in used_cands:
                    continue
                n_seen += 1
                if n_seen > pool_cap:
                    break
                gain = optimal_lineup(without + [c], slots, registry, value)[1] - base_pts
                if gain > 0.05 and (best is None or gain > best[0]):
                    best = (gain, ov, took, c)
        if best is None:
            break
        gain, ov, took, cand = best
        roster = [p for p in roster if p != took] + [cand]
        used_picks.add(ov)
        used_cands.add(cand)
        nxt = my_next.get(ov)
        still_there = bool(nxt) and drafted_at.get(took, 10 ** 6) >= nxt
        new_pts = optimal_lineup(roster, slots, registry, value)[1]
        out.append({
            "overall": ov, "took": took, "pid": cand, "gain": round(gain, 1),
            "both": still_there, "next_pick": nxt,
            "cand_taken_at": drafted_at.get(cand),      # None => went undrafted
            "grade_if": _letter((new_pts - mu) / sd) if (mu is not None and sd) else None,
            "total_pts": round(new_pts, 1),
        })
    return out
