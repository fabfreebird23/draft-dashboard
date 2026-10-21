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
