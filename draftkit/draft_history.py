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
    chain = sleeper.league_chain(str(league_id))
    used = 0
    for entry in chain:
        did = entry.get("draft_id")
        if not did:
            continue
        picks = sleeper.get_draft_picks(did)
        if not picks:
            continue
        used += 1
        for p in picks:
            owner = str(p.get("picked_by") or "")
            rnd = p.get("round")
            pos = (p.get("metadata") or {}).get("position")
            if owner and rnd and pos in _SKILL:
                counts[owner][int(rnd)][pos] += 1.0
        if used >= max_seasons:
            break

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
                   registry, top_k: int = 12, jitter: float = 0.0,
                   roster_counts: Optional[dict] = None) -> Optional[dict]:
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
        # Keeper-league rookie lean: managers reach for rookies (cheap future
        # keepers), so opponents and the predictor favour them among close picks.
        try:
            if registry.meta(p["pid"]).years_exp == 0:
                score += 0.30
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
def _gather_drafts(league_id: str, max_seasons: int) -> List[List[dict]]:
    """Newest-first list of past drafts' picks (skipping empty / current draft)."""
    out: List[List[dict]] = []
    for entry in sleeper.league_chain(str(league_id)):
        did = entry.get("draft_id")
        if not did:
            continue
        picks = sleeper.get_draft_picks(did)
        if picks:
            out.append(picks)
        if len(out) >= max_seasons:
            break
    return out


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
    for di, picks in enumerate(drafts):
        per: Dict[str, List[dict]] = defaultdict(list)
        for p in picks:
            owner = str(p.get("picked_by") or "")
            r = _rec(p, di)
            if owner and r:
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

        # reach vs the league: positive = takes the position earlier than the field
        reach = {p: round(league_avg_first[p] - avg_first[p], 1)
                 for p in avg_first if p in league_avg_first}

        fav_teams = [t for t, _ in Counter(r["team"] for r in skill if r["team"]).most_common(3)]

        # predictability: how consistently they open with the same position (0..100)
        top_first = first_pos.most_common(1)
        predictability = round(100 * (top_first[0][1] / n_drafts)) if top_first and n_drafts else 0

        profiles[owner] = {
            "thin": False, "n_picks": n, "n_drafts": n_drafts,
            "pos_share": pos_share, "pos_by_round": pos_by_round,
            "first_pick": dict(first_pos), "avg_first": {p: round(v, 1) for p, v in avg_first.items()},
            "reach": reach, "fav_teams": fav_teams,
            "archetype": _archetype(pos_share, avg_first, reach),
            "predictability": predictability,
            "tendencies": _tendency_lines(pos_share, first_pos, n_drafts, avg_first,
                                          reach, fav_teams),
        }
    return profiles


def _archetype(pos_share: dict, avg_first: dict, reach: dict) -> str:
    rb, wr = pos_share.get("RB", 0), pos_share.get("WR", 0)
    qb_reach, te_reach = reach.get("QB", 0), reach.get("TE", 0)
    rb_first = avg_first.get("RB", 99)
    if qb_reach >= 1.5:
        return "Early-QB"
    if te_reach >= 1.5:
        return "Premium-TE"
    if rb_first >= 4 and rb < 0.32:
        return "Zero-RB"
    if rb >= 0.42:
        return "RB-heavy"
    if wr >= 0.46:
        return "WR-heavy"
    return "Balanced"


def _tendency_lines(pos_share, first_pos, n_drafts, avg_first, reach, fav_teams) -> List[str]:
    lines: List[str] = []
    if first_pos:
        pos, cnt = first_pos.most_common(1)[0]
        if cnt >= max(2, n_drafts):
            lines.append(f"Always opens with a {pos} ({cnt}/{n_drafts} drafts)")
        elif cnt / max(1, n_drafts) >= 0.5:
            lines.append(f"Usually opens with a {pos} ({cnt}/{n_drafts})")
    for pos, label in (("QB", "QB"), ("TE", "TE")):
        rc = reach.get(pos)
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
