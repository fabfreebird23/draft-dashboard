"""Historical draft-tendency model — predict how each manager drafts.

From a Sleeper league's past drafts (walked via previous_league_id), we learn each
owner's positional tendency by round: P(position | owner, round). The mock AI then
blends this with ADP so opponents draft like their real managers (e.g. an owner who
always takes a QB early, or hammers RB) instead of strictly by ADP.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Optional

from . import sleeper_client as sleeper

_SKILL = ("QB", "RB", "WR", "TE")


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


def pick_for_owner(owner_id: str, rnd: int, available: list, tendencies: dict,
                   registry, top_k: int = 12) -> Optional[dict]:
    """Choose a player for an AI owner: blend ADP value with the owner's
    positional tendency for this round. `available` is ADP-ordered
    [{pid, name, pos, adp}, ...]. Returns the chosen item (or None)."""
    if not available:
        return None
    pool = available[:top_k]
    best, best_score = None, -1.0
    for i, p in enumerate(pool):
        # ADP value: earlier in the pool = better (1.0 .. ~0)
        adp_val = 1.0 - (i / max(1, len(pool)))
        tend = tendency_score(owner_id, rnd, p["pos"], tendencies)
        # Blend: ADP dominates, tendency tilts among close-by players.
        score = 0.62 * adp_val + 0.38 * tend
        if score > best_score:
            best, best_score = p, score
    return best
