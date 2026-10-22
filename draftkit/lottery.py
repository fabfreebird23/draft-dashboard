"""Next season's draft-order lottery, simulated from where the season stands.

Babies & Boomer's lottery (the hub's kreeper/lottery.py and config.yaml):
ball weights are handed to 10 tiers —

  1.   the "Chase for the Pick" winner: the consolation bracket's champion.
       The Chase is the four teams just OUTSIDE the playoffs — this year's
       bracket is seeded 5 v 8 and 6 v 7 — so the worst record is NOT in it;
  2-9. the other eight teams by regular-season record, worst to best;
  10.  the league champion.

and the draw is weighted, without replacement, for the selection order (first
choice of draft slot, then second, …).

So "tank" has two paths: finish last and take tier 2's balls, or finish 5th-8th
and win the Chase for tier 1's — twice as many. This simulates the rest of
the regular season, both brackets (two-week rounds), and the draw, and reports
where each path lands.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np


def simulate(team_means: Dict[str, float], team_sds: Dict[str, float], records: Dict[str, tuple],
             points_for: Dict[str, float], schedule: Dict[int, List[tuple]], playoff_teams: int,
             weights: List[int], me: str, *, chase_teams: int = 4, median: bool = False,
             n_sims: int = 6000, seed: int = 11) -> dict:
    """{"select": [P(selection k)], "tier": {...}, "paths": {...}} for `me`."""
    teams = sorted(team_means)
    n = len(teams)
    if n < 6 or me not in team_means or len(weights) < n:
        return {}
    idx = {t: i for i, t in enumerate(teams)}
    m = idx[me]
    rng = np.random.default_rng(seed)
    mu = np.array([team_means[t] for t in teams])
    sd = np.array([team_sds.get(t, 20) or 20 for t in teams])
    wins = np.tile(np.array([float(records.get(t, (0, 0))[0]) for t in teams]), (n_sims, 1))
    pts = np.tile(np.array([float(points_for.get(t, 0) or 0) for t in teams]), (n_sims, 1))
    for wk in sorted(schedule):
        score = rng.normal(mu, sd, size=(n_sims, n))
        pts += score
        for a, b in schedule[wk]:
            if a in idx and b in idx:
                ia, ib = idx[a], idx[b]
                aw = score[:, ia] >= score[:, ib]
                wins[:, ia] += aw
                wins[:, ib] += ~aw
        if median:
            playing = sorted({idx[t] for pr in schedule[wk] for t in pr if t in idx})
            sub = score[:, playing]
            wins[:, playing] += np.argsort(np.argsort(-sub, axis=1), axis=1) < len(playing) // 2
    order = np.argsort(-(wins * 1e5 + pts), axis=1)          # best -> worst, per sim

    w = np.array(weights[:n], dtype=float)
    select = np.zeros(n)
    tier_hits = {"chase_win": 0, "in_chase": 0, "worst": 0, "champion": 0}
    for s in range(n_sims):
        o = order[s]
        # two-week rounds: a round is two weeks' scoring summed
        def game(a, b):
            sa = rng.normal(mu[a], sd[a]) + rng.normal(mu[a], sd[a])
            sb = rng.normal(mu[b], sd[b]) + rng.normal(mu[b], sd[b])
            return a if sa >= sb else b
        p = o[:playoff_teams]
        champ = game(game(p[0], p[3]), game(p[1], p[2])) if playoff_teams >= 4 else p[0]
        c = o[playoff_teams:playoff_teams + chase_teams]
        chase = game(game(c[0], c[3]), game(c[1], c[2])) if len(c) >= 4 else None
        if m in c:
            tier_hits["in_chase"] += 1
        if chase == m:
            tier_hits["chase_win"] += 1
        if champ == m:
            tier_hits["champion"] += 1
        if o[-1] == m:
            tier_hits["worst"] += 1
        # tiers: chase winner, then the rest worst -> best, then the champion
        rest = [t for t in o[::-1] if t not in (chase, champ)]
        tiers = ([chase] if chase is not None else []) + rest + [champ]
        tw = {t: w[i] for i, t in enumerate(tiers)}
        pool = list(tw)
        probs = np.array([tw[t] for t in pool], dtype=float)
        # one weighted draw without replacement for the selection order
        draw = rng.choice(len(pool), size=len(pool), replace=False, p=probs / probs.sum())
        pos = int(np.where(np.array(pool)[draw] == m)[0][0])
        select[pos] += 1
    sel = select / n_sims
    return {"select": [round(100 * x) for x in sel],
            "expected": round(float(sum((i + 1) * x for i, x in enumerate(sel))), 1),
            "paths": {k: round(100 * v / n_sims) for k, v in tier_hits.items()},
            "chase_seeds": (playoff_teams + 1, playoff_teams + chase_teams)}


# ------------------------------------------------------------- every team's odds
# The three keeper leagues draw their order three different ways. `style` names
# which, and each is copied from that hub's own lottery module:
#
#   chase     B&B — tiers: Chase winner, the rest worst -> best record, champion
#             last; a full weighted draw for the selection order.
#   inverted  Kreeper — placement INVERTED onto lottery rank inside each bracket:
#             the consolation bracket's last place gets weights[0], its champion
#             the worst of that group; then the playoff bracket's 4th place down
#             to the champion on weights[-1]. The draw IS the draft order.
#   final     7½ Men — final standing incl. the Chase, worst first; the champion
#             is floored to the smallest weight; only `draws` selections are
#             drawn and everyone after falls in ball-weight order.
#
# Selection order is read as draft slot: whoever chooses first takes 1.01. That
# is what nearly everyone does, and the hubs deliberately don't model the rest.

def _bracket(rng, mu, sd, seeds):
    """Four seeds -> finish order [champ, runner-up, 3rd, 4th] (two-week rounds)."""
    def score(t):
        return rng.normal(mu[t], sd[t]) + rng.normal(mu[t], sd[t])
    if len(seeds) < 4:
        return list(seeds)
    a, b, c, d = seeds[:4]
    s1 = (a, d) if score(a) >= score(d) else (d, a)
    s2 = (b, c) if score(b) >= score(c) else (c, b)
    w1, l1 = s1
    w2, l2 = s2
    champ, ru = (w1, w2) if score(w1) >= score(w2) else (w2, w1)
    third, fourth = (l1, l2) if score(l1) >= score(l2) else (l2, l1)
    return [champ, ru, third, fourth] + list(seeds[4:])


def slot_odds(team_means: Dict[str, float], team_sds: Dict[str, float], records: Dict[str, tuple],
              points_for: Dict[str, float], schedule: Dict[int, List[tuple]], playoff_teams: int,
              spec: dict, *, median: bool = False, n_sims: int = 4000, seed: int = 7) -> Dict[str, list]:
    """{team: [P(slot 1) .. P(slot N)] in percent} for every team."""
    teams = sorted(team_means)
    n = len(teams)
    weights = list(spec.get("weights") or [])
    style = spec.get("style", "chase")
    if n < 4 or len(weights) < n:
        return {}
    weights = weights[:n]
    idx = {t: i for i, t in enumerate(teams)}
    rng = np.random.default_rng(seed)
    mu = np.array([team_means[t] for t in teams])
    sd = np.array([team_sds.get(t, 20) or 20 for t in teams])
    wins = np.tile(np.array([float(records.get(t, (0, 0))[0]) for t in teams]), (n_sims, 1))
    pts = np.tile(np.array([float(points_for.get(t, 0) or 0) for t in teams]), (n_sims, 1))
    for wk in sorted(schedule):
        score = rng.normal(mu, sd, size=(n_sims, n))
        pts += score
        for a, b in schedule[wk]:
            if a in idx and b in idx:
                ia, ib = idx[a], idx[b]
                aw = score[:, ia] >= score[:, ib]
                wins[:, ia] += aw
                wins[:, ib] += ~aw
        if median:
            playing = sorted({idx[t] for pr in schedule[wk] for t in pr if t in idx})
            sub = score[:, playing]
            wins[:, playing] += np.argsort(np.argsort(-sub, axis=1), axis=1) < len(playing) // 2
    order = np.argsort(-(wins * 1e5 + pts), axis=1)          # best -> worst, per sim
    pt = max(1, min(playoff_teams, n))
    chase_n = int(spec.get("chase_teams", 4))
    draws = spec.get("draws")
    hits = np.zeros((n, n))
    w = np.array(weights, dtype=float)
    for s in range(n_sims):
        o = list(order[s])
        po = _bracket(rng, mu, sd, o[:pt])
        rest = o[pt:]
        if style == "inverted":
            co = _bracket(rng, mu, sd, rest[:4]) + rest[4:]
            # consolation last place first ... its champion; then playoff 4th ... champion
            ranked = co[::-1] + po[::-1]
        elif style == "final":
            co = _bracket(rng, mu, sd, rest[:chase_n]) + rest[chase_n:]
            final = po + co                                   # 1 = champion .. N = last
            ranked = final[1:][::-1] + [final[0]]             # champion floored
        else:                                                 # chase
            co = _bracket(rng, mu, sd, rest[:chase_n]) if len(rest) >= 4 else []
            chase = co[0] if co else None
            champ = po[0]
            others = [t for t in o[::-1] if t not in (chase, champ)]
            ranked = ([chase] if chase is not None else []) + others + [champ]
        k = n if not draws else min(int(draws), n)
        pool = list(range(n))
        pw = w.copy()
        got = []
        for _ in range(k):
            p = pw[pool] / pw[pool].sum()
            j = pool[int(rng.choice(len(pool), p=p))]
            got.append(j)
            pool.remove(j)
        got += pool                                           # the rest in weight order
        for slot, j in enumerate(got):
            hits[ranked[j], slot] += 1
    return {t: [round(100 * float(x) / n_sims, 1) for x in hits[idx[t]]] for t in teams}
