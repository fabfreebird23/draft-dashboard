"""Historical draft-tendency model — predict how each manager drafts.

From a Sleeper league's past drafts (walked via previous_league_id), we learn each
owner's positional tendency by round: P(position | owner, round). The mock AI then
blends this with ADP so opponents draft like their real managers (e.g. an owner who
always takes a QB early, or hammers RB) instead of strictly by ADP.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from . import sleeper_client as sleeper

_SKILL = ("QB", "RB", "WR", "TE")
_TEAM_NAMES = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
    "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
    "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
    "LV": "Raiders", "LAC": "Chargers", "LAR": "Rams", "MIA": "Dolphins",
    "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SF": "49ers",
    "SEA": "Seahawks", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders",
}


def owner_tendencies(league_id: str, max_seasons: int = 4) -> Dict[str, Dict[int, Dict[str, float]]]:
    """{owner_id: {round: {position: probability}}} from past drafts.

    Rounds beyond a draft's length are ignored; positions normalized per round.
    """
    counts: Dict[str, Dict[int, Dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float)))
    drafts = _gather_drafts(str(league_id), max_seasons)
    # Keepers are placed at a fixed cost round, not chosen there — counting them
    # teaches the AI a round->position habit the manager never actually had.
    is_keeper = _real_pick_filter(str(league_id), [s for s, _ in drafts])
    for season, picks in drafts:
        for p in picks:
            owner = str(p.get("picked_by") or "")
            rnd = p.get("round")
            pos = (p.get("metadata") or {}).get("position")
            if owner and rnd and pos in _SKILL and not is_keeper(season, p):
                counts[owner][int(rnd)][pos] += 1.0

    out: Dict[str, Dict[int, Dict[str, float]]] = {}
    for owner, by_round in counts.items():
        out[owner] = {}
        for rnd, posc in by_round.items():
            tot = sum(posc.values())
            if tot:
                out[owner][rnd] = {pos: c / tot for pos, c in posc.items()}
    return out


def tendency_score(owner_id: str, rnd: int, position: str,
                   tendencies: dict) -> float:
    """How much owner `owner_id` favours `position` in round `rnd` (0..1).

    Falls back to a neighbouring-round average, then a neutral 0.25, when this
    owner has no history for the exact round."""
    ot = tendencies.get(str(owner_id))
    if not ot:
        return 0.25
    if rnd in ot:
        return ot[rnd].get(position, 0.0)
    # nearest rounds we do have
    near = [r for r in (rnd - 1, rnd + 1, rnd - 2, rnd + 2) if r in ot]
    if near:
        return sum(ot[r].get(position, 0.0) for r in near) / len(near)
    return 0.25


# Roster caps for AI drafting: no sane team rosters more than two of these, so the
# AI (and the predictor) never reach for a 3rd QB/TE — keeps auto-drafted rosters
# realistic. Positions not listed are effectively uncapped.
POS_CAPS = {"QB": 2, "TE": 2}


def pick_for_owner(owner_id: str, rnd: int, available: list, tendencies: dict,
                   registry, top_k: int = 12, jitter: float = 0.0, rookie_lean: float = 0.12,
                   roster_counts: Optional[dict] = None,
                   pos_share: Optional[dict] = None,
                   drafted_counts: Optional[dict] = None) -> Optional[dict]:
    """Choose a player for an AI owner: blend ADP value with the owner's
    positional tendency for this round. `available` is ADP-ordered
    [{pid, name, pos, adp}, ...]. Returns the chosen item (or None).

    `jitter` adds per-candidate random noise so the same board doesn't produce
    the same draft twice — pass a small value (~0.15) for live mock picks to make
    every mock different, and leave it 0 for the predictor (stable predictions).

    `roster_counts` is this owner's current position→count; positions already at
    their POS_CAPS limit (QB/TE ≤ 2) are dropped from consideration."""
    if not available:
        return None
    rc = roster_counts or {}
    # drop positions this team has already filled to the cap (QB/TE), keeping the
    # ADP order; fall back to the raw pool only if everything is somehow capped.
    eligible = [p for p in available if rc.get(p["pos"], 0) < POS_CAPS.get(p["pos"], 99)]
    pool = list((eligible or available)[:top_k])
    # Guarantee a required QB/TE is always *considered* once a team has none — a
    # team that hoards RB/WR can push the last startable QB out of the top-k ADP
    # pool, so the fill nudge below never sees a QB and the team ends with 0.
    for need_pos in POS_CAPS:
        if rc.get(need_pos, 0) == 0:
            bestp = next((p for p in (eligible or available) if p["pos"] == need_pos), None)
            if bestp is not None and bestp not in pool:
                pool.append(bestp)
    best, best_score = None, -1.0
    for i, p in enumerate(pool):
        # ADP value: earlier in the pool = better (1.0 .. ~0)
        adp_val = 1.0 - (i / max(1, len(pool)))
        tend = tendency_score(owner_id, rnd, p["pos"], tendencies)
        # Blend: ADP dominates, tendency tilts among close-by players.
        score = 0.62 * adp_val + 0.38 * tend
        # Fill the one required QB/TE starter: if the team still has none, nudge
        # that position with urgency that grows through the draft, so every roster
        # ends with 1-2 (never 0, never 3+). The cap (1.4) exceeds the best a non-
        # nudged pick can score (~1.0 = ADP 1.0 + full tendency), so by the late
        # rounds an empty QB/TE is effectively forced rather than merely favoured.
        if p["pos"] in POS_CAPS and rc.get(p["pos"], 0) == 0:
            score += min(1.4, 0.12 * rnd)
        # Soft flex balance: RB/WR have no cap, so jitter can cascade a team into
        # 2-RB/9-WR. Gently discourage piling 6+ deep at one flex spot — a growing
        # penalty (never a hard cap), so a clearly better player is still taken but
        # a roster trends toward a realistic ~5-6 of each.
        if p["pos"] in ("RB", "WR"):
            over = rc.get(p["pos"], 0) - 5
            if over > 0:
                score -= 0.11 * over
        # Pull back toward this manager's OWN historical position mix. `tendencies`
        # is a per-round CONDITIONAL, P(position | round); taking its argmax round
        # after round does not reproduce his marginal share, and a board that
        # happens to be rich at one position compounds the drift. That is how a
        # manager who genuinely drafts 50% WR opened 58% of simulated mocks with
        # four straight WRs while sitting on two RBs. The 6+ penalty above can't
        # catch it — with two WR keepers he'd need four WR picks before it fires.
        #
        # Compared against DRAFTED picks only, because that is how pos_share itself
        # is measured (owner_profiles excludes keepers). Mixing the two is not a
        # rounding error, it inverts the correction: Jared's two RB keepers put him
        # at 40% RB against a 31% drafted-RB history, so a keeper-inclusive count
        # penalises RB — the exact position he is short of — and lets WR run free.
        dc = drafted_counts if drafted_counts is not None else rc
        if pos_share and p["pos"] in ("RB", "WR"):
            n_have = sum(dc.get(x, 0) for x in _SKILL)
            target = pos_share.get(p["pos"])
            if n_have >= 3 and target:
                actual = dc.get(p["pos"], 0) / n_have
                if actual > target:
                    score -= min(0.40, 1.8 * (actual - target))
        # Rookie lean: a small tiebreak so a rookie edges an equal-ADP vet (keeps the
        # top rookie at #1 when his curve-ADP ties the consensus #1). Kept small on
        # purpose — when a league's rookie curve is applied, the pool ADP already
        # encodes the league's rookie aggression, so a large lean would double-count
        # and overshoot (e.g. shove the #2 rookie past clearly better vets).
        try:
            if rookie_lean and registry.meta(p["pid"]).years_exp == 0:
                score += rookie_lean
        except Exception:  # noqa: BLE001
            pass
        # mock-draft variance: noise large enough to swap close-by players (so
        # every mock differs) but small relative to real ADP cliffs (so elites
        # still go early). The compounding board state amplifies it round to round.
        if jitter:
            score += random.uniform(0.0, jitter)
        if score > best_score:
            best, best_score = p, score
    return best


# ---------------------------------------------------------------- deep profiles
def _gather_drafts(league_id: str, max_seasons: int) -> List[tuple]:
    """Newest-first [(season, picks), ...] for past drafts (skipping empty ones).
    The season comes back too because separating keepers from real draft picks
    needs the dashboard's per-season record — see `_real_pick_filter`."""
    out: List[tuple] = []
    for entry in sleeper.league_chain(str(league_id)):
        did = entry.get("draft_id")
        if not did:
            continue
        picks = sleeper.get_draft_picks(did)
        if picks:
            out.append((int(entry.get("season") or 0), picks))
        if len(out) >= max_seasons:
            break
    return out


def _real_pick_filter(league_id: str, seasons: List[int]):
    """Returns is_keeper(season, pick) using the keeper dashboard as the source of
    truth, falling back to Sleeper's own flag where no dashboard exists.

    Sleeper's flag is unreliable across this league's history — 2024 marks 2 picks
    where the dashboard records 36 — so a profile built on it treats roughly 8
    keepers per manager as genuine draft decisions. Measured on the real data,
    that moved positional share by up to 7 points, one manager's average first-QB
    round by 3.5 rounds, and flipped another's "usually opens with" from RB to WR."""
    from . import keepers as _K
    truth = {}
    try:
        truth = _K.kept_pids_by_season(league_id, seasons) if _K.league_has_keepers(league_id) else {}
    except Exception:  # noqa: BLE001 — dashboard unreachable: fall back to the flag
        truth = {}

    def is_keeper(season: int, p: dict) -> bool:
        s = truth.get(season)
        if s:
            return str(p.get("player_id")) in s
        return bool(p.get("is_keeper"))
    return is_keeper


def rookie_curve(league_id: str, registry, current_season: int,
                 max_seasons: int = 4) -> dict:
    """Learn how aggressively THIS league drafts rookies, from its own draft history.

    For each past draft we find the players who were rookies *that* season (via the
    registry's years_exp) and record the overall pick where the 1st, 2nd, 3rd … rookie
    came off the board. Averaged across seasons this gives a 'rookie slot curve':
    {rookie_rank: avg_overall_pick}. A keeper/dynasty league that hammers rookies
    yields a curve well ahead of ADP (top rookie ~pick 1); a redraft league yields a
    curve ≈ ADP (so applying it is a no-op). That makes the rookie boost automatically
    league-specific — it only fires for leagues whose history shows rookie aggression.

    Returns {"curve": {rank: avg_pick}, "samples": [...], "n_seasons": int,
    "draft_size": int} (empty curve when there's no usable history)."""
    by_rank: Dict[int, List[int]] = defaultdict(list)
    samples: List[dict] = []
    sizes, n_seasons = [], 0
    for entry in sleeper.league_chain(str(league_id)):
        sea, did = entry.get("season"), entry.get("draft_id")
        if not did or sea is None or int(sea) >= current_season:
            continue
        picks = sleeper.get_draft_picks(did)
        if not picks:
            continue
        sizes.append(len(picks))
        rookies = []
        for pk in picks:
            m = registry.by_sleeper.get(str(pk.get("player_id") or ""))
            if m is None or m.years_exp is None:
                continue
            if (current_season - m.years_exp) == int(sea):
                rookies.append((int(pk.get("pick_no") or 0), m.name, m.position))
        if not rookies:
            continue
        n_seasons += 1
        rookies.sort(key=lambda x: x[0] or 9999)
        for rank, (pno, nm, pos) in enumerate(rookies, 1):
            by_rank[rank].append(pno)
            if rank <= 8:
                samples.append({"season": int(sea), "rank": rank, "pick": pno,
                                "name": nm, "pos": pos})
    curve = {k: round(sum(v) / len(v), 1) for k, v in by_rank.items() if v}
    return {"curve": curve, "samples": samples, "n_seasons": n_seasons,
            "draft_size": round(sum(sizes) / len(sizes)) if sizes else 0}


def _rec(p: dict, draft_idx: int) -> Optional[dict]:
    md = p.get("metadata") or {}
    pos = md.get("position")
    if pos not in _SKILL:
        return None
    return {
        "draft": draft_idx,
        "round": int(p.get("round") or 0),
        "pick_no": int(p.get("pick_no") or 0),
        "pos": pos,
        "team": (md.get("team") or "").upper(),
        "name": f"{md.get('first_name', '')} {md.get('last_name', '')}".strip(),
        "keeper": bool(p.get("is_keeper")),
    }


def owner_profiles(league_id: str, max_seasons: int = 4) -> Dict[str, dict]:
    """A deep scouting profile for every manager, mined from their real past
    drafts. Keeper picks are excluded so we measure *draft decisions*, not roster
    inheritance. Each profile carries the round→position model the AI uses plus
    human-readable scouting: archetype, position share, first-pick habit, how
    early they reach for each position vs the league, favourite NFL teams, and a
    predictability score. Returns {owner_id: profile}."""
    drafts = _gather_drafts(league_id, max_seasons)
    if not drafts:
        return {}

    by_owner: Dict[str, List[dict]] = defaultdict(list)
    # league baseline: first round each position is taken, per owner-draft
    league_first: Dict[str, List[int]] = defaultdict(list)
    is_keeper = _real_pick_filter(league_id, [s for s, _ in drafts])
    for di, (season, picks) in enumerate(drafts):
        per: Dict[str, List[dict]] = defaultdict(list)
        for p in picks:
            owner = str(p.get("picked_by") or "")
            r = _rec(p, di)
            if owner and r:
                r["keeper"] = is_keeper(season, p)   # dashboard truth, not the flag
                by_owner[owner].append(r)
                per[owner].append(r)
        for recs in per.values():
            seen = set()
            for r in sorted(recs, key=lambda x: x["pick_no"]):
                if r["keeper"] or r["pos"] in seen:
                    continue
                seen.add(r["pos"])
                league_first[r["pos"]].append(r["round"])
    league_avg_first = {p: (sum(v) / len(v)) for p, v in league_first.items() if v}

    profiles: Dict[str, dict] = {}
    for owner, recs in by_owner.items():
        skill = [r for r in recs if not r["keeper"]]
        n = len(skill)
        n_drafts = len({r["draft"] for r in skill})
        if n < 3:
            profiles[owner] = {"thin": True, "n_picks": n, "n_drafts": n_drafts,
                               "pos_by_round": {}, "pos_share": {}, "tendencies": [],
                               "archetype": "Unknown", "predictability": 0,
                               "fav_teams": [], "first_pick": {}, "reach": {}}
            continue

        pos_count = Counter(r["pos"] for r in skill)
        pos_share = {p: round(pos_count.get(p, 0) / n, 3) for p in _SKILL}

        # round → position probability (the model the AI/predictor consumes)
        by_round: Dict[int, Counter] = defaultdict(Counter)
        for r in skill:
            by_round[r["round"]][r["pos"]] += 1
        pos_by_round = {rnd: {p: c[p] / sum(c.values()) for p in c}
                        for rnd, c in by_round.items()}

        # first non-keeper pick each draft → habit at the top of the draft
        first_pos = Counter()
        # first round this owner takes each position, averaged across drafts
        first_round_by_pos: Dict[str, List[int]] = defaultdict(list)
        for di in {r["draft"] for r in skill}:
            ds = sorted([r for r in skill if r["draft"] == di], key=lambda x: x["pick_no"])
            if ds:
                first_pos[ds[0]["pos"]] += 1
            seen = set()
            for r in ds:
                if r["pos"] not in seen:
                    seen.add(r["pos"])
                    first_round_by_pos[r["pos"]].append(r["round"])
        avg_first = {p: sum(v) / len(v) for p, v in first_round_by_pos.items()}
        # How consistent he is at each position, so a "reaches early / waits" claim
        # can be held against his OWN scatter rather than a fixed round threshold.
        # Gentis took his first TE in rounds 6 and 11 — an 8.5 average that reads as
        # "waits on TE by 2 rounds" while the spread is wider than the claim.
        first_se = {}
        for p, v in first_round_by_pos.items():
            if len(v) >= 2:
                m = sum(v) / len(v)
                first_se[p] = ((sum((x - m) ** 2 for x in v) / len(v)) ** 0.5) / (len(v) ** 0.5)
            else:
                first_se[p] = None       # one draft is not a tendency

        # reach vs the league: positive = takes the position earlier than the field
        reach = {p: round(league_avg_first[p] - avg_first[p], 1)
                 for p in avg_first if p in league_avg_first}

        fav_teams = _fav_teams(skill)

        # predictability: how consistently they open with the same position (0..100)
        top_first = first_pos.most_common(1)
        predictability = round(100 * (top_first[0][1] / n_drafts)) if top_first and n_drafts else 0

        profiles[owner] = {
            "thin": False, "n_picks": n, "n_drafts": n_drafts,
            "pos_share": pos_share, "pos_by_round": pos_by_round,
            "first_pick": dict(first_pos), "avg_first": {p: round(v, 1) for p, v in avg_first.items()},
            "reach": reach, "fav_teams": fav_teams,
            "archetype": _archetype(pos_share, avg_first, reach, first_se),
            "predictability": predictability,
            "tendencies": _tendency_lines(pos_share, first_pos, n_drafts, avg_first,
                                          reach, fav_teams, first_se),
        }
    return profiles


_NFL_TEAMS = 32
_FAV_MIN_PLAYERS = 3      # never call two of anything a pattern, whatever the maths
_FAV_MAX_FWER = 0.10      # family-wise false-positive rate across all 32 teams


def _poisson_sf(k: int, lam: float) -> float:
    """P(X >= k) for Poisson(lam). Small k and lam here, so the direct sum is fine."""
    import math
    cdf = sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k))
    return max(0.0, 1.0 - cdf)


def _fav_teams(skill: List[dict]) -> List[str]:
    """NFL teams a manager demonstrably favours — or [] when nothing clears the bar.

    Two corrections over just taking the top of a Counter:

    1. Count DISTINCT PLAYERS, not picks. Re-drafting the same guy year after year
       is a player preference, not a team one — Mark Andrews alone supplied two of
       Jared's three "Ravens" picks.
    2. Demand actual significance. Spread ~31 players over 32 teams and per-team
       counts are about Poisson(1). P(X>=3) is 8%, but we take the MAX over 32
       teams, so ~2.6 teams clear 3 BY CHANCE for every manager. A raw "top team"
       is therefore noise almost every time. We keep a team only if its count
       would be unlikely even after that multiple comparison.

    With three drafts of history this bar is rarely met, which is the honest
    answer: you cannot read a team preference off ~30 picks. It scales on its own
    as seasons accumulate — a manager who really does hoard Ravens will clear it
    once there's enough evidence to say so."""
    by_team: Dict[str, set] = defaultdict(set)
    for r in skill:
        if r.get("team") and r.get("name"):
            by_team[r["team"]].add(r["name"])
    n_distinct = len({r["name"] for r in skill if r.get("name")})
    if not by_team or n_distinct < 1:
        return []
    lam = n_distinct / _NFL_TEAMS
    qualified = [(t, len(ps)) for t, ps in by_team.items()
                 if len(ps) >= _FAV_MIN_PLAYERS
                 and _poisson_sf(len(ps), lam) * _NFL_TEAMS < _FAV_MAX_FWER]
    # deterministic: most players first, then team code (never dict insertion order)
    qualified.sort(key=lambda tp: (-tp[1], tp[0]))
    return [t for t, _ in qualified[:3]]


def _archetype(pos_share: dict, avg_first: dict, reach: dict, first_se=None) -> str:
    """The badge must be held to the same evidence bar as the tendency lines, or
    the panel contradicts itself — asserting "Early-QB" beside a manager whose
    QB-timing line was dropped for being inside his own scatter."""
    def _reliable(pos):
        rc, se = reach.get(pos), (first_se or {}).get(pos)
        if rc is None or se is None or abs(rc) <= se:
            return 0.0
        return rc
    rb, wr = pos_share.get("RB", 0), pos_share.get("WR", 0)
    qb_reach, te_reach = _reliable("QB"), _reliable("TE")
    rb_first = avg_first.get("RB", 99)
    if qb_reach >= 1.5:
        return "Early-QB"
    if te_reach >= 1.5:
        return "Premium-TE"
    if rb_first >= 4 and rb < 0.32:
        return "Zero-RB"
    # Whichever flex position he actually leans on — testing RB first against a
    # LOWER bar (0.42 vs 0.46) badged a 43%-RB / 46%-WR manager "RB-heavy" while
    # the tendency line beneath it read "WR-heavy: 46%".
    if rb >= 0.42 or wr >= 0.46:
        return "RB-heavy" if rb >= wr else "WR-heavy"
    return "Balanced"


def _tendency_lines(pos_share, first_pos, n_drafts, avg_first, reach, fav_teams,
                    first_se=None) -> List[str]:
    lines: List[str] = []
    if first_pos:
        pos, cnt = first_pos.most_common(1)[0]
        if cnt >= max(2, n_drafts):
            lines.append(f"Always opens with a {pos} ({cnt}/{n_drafts} drafts)")
        elif cnt / max(1, n_drafts) >= 0.5:
            lines.append(f"Usually opens with a {pos} ({cnt}/{n_drafts})")
    for pos, label in (("QB", "QB"), ("TE", "TE")):
        rc = reach.get(pos)
        # Only claim a habit that is bigger than his own scatter at that position,
        # and never off a single draft — otherwise we report noise with the same
        # confidence as a real pattern (see first_se).
        se = (first_se or {}).get(pos)
        if rc is not None and (se is None or abs(rc) <= se):
            continue
        if rc is not None and rc >= 1.0:
            rnd = avg_first.get(pos)
            when = f" (~rd {rnd:.0f})" if rnd else ""
            lines.append(f"Reaches for {label} early{when} — {rc:.0f} rds ahead of the field")
        elif rc is not None and rc <= -1.5:
            lines.append(f"Waits on {label} — {abs(rc):.0f} rds later than the field")
    top_share = max(pos_share.items(), key=lambda x: x[1]) if pos_share else None
    if top_share and top_share[1] >= 0.42:
        lines.append(f"{top_share[0]}-heavy: {top_share[1]*100:.0f}% of picks")
    if fav_teams:
        names = ", ".join(_TEAM_NAMES.get(t, t) for t in fav_teams[:2])
        lines.append(f"Favours the {names}")
    return lines[:4]


def likely_positions(owner_id: str, rnd: int, profiles: dict, k: int = 2) -> List[str]:
    """The positions a manager most favours in a given round (for the predictor)."""
    prof = profiles.get(str(owner_id)) or {}
    pbr = prof.get("pos_by_round") or {}
    dist = pbr.get(rnd)
    if not dist:
        near = [r for r in (rnd - 1, rnd + 1) if r in pbr]
        if near:
            dist = {}
            for r in near:
                for p, v in pbr[r].items():
                    dist[p] = dist.get(p, 0) + v
    if not dist:
        return []
    return [p for p, _ in sorted(dist.items(), key=lambda x: -x[1])[:k]]
