"""Leagues that draft in more than one stage.

7 1/2 Men runs a 2-round ROOKIE draft and then a separate VETERAN draft, with the
players taken in the rookie draft removed from the veteran pool. Sleeper can only
describe one draft at a time — and while the league is still configured as dynasty
it reports a 2-round draft full stop — so the shape lives here rather than being
inferred from the platform.

A stage is not cosmetic: it changes the eligible pool, the round count, and which
players are already gone. Mocking the veteran draft against the full pool would
practise the wrong draft.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Set

ROOKIE, VETERAN = "rookie", "veteran"


@dataclass
class Stage:
    key: str
    name: str
    rounds: int
    pool: str          # "rookies" | "all"
    blurb: str = ""


# Keyed by league id. 7 1/2 Men: 2-round rookie draft, then the veteran draft.
STAGES = {
    "1388606375239643136": [
        Stage(ROOKIE, "Rookie draft", 2, "rookies",
              "2 rounds, NFL rookies only. Everyone taken here is out of the "
              "veteran pool."),
        Stage(VETERAN, "Veteran draft", 13, "all",
              "The main draft, with rookie-draft picks already off the board."),
    ],
}


def stages_for(league_id) -> Optional[List[Stage]]:
    return STAGES.get(str(league_id))


def already_taken(league_id) -> Set[str]:
    """Everyone already on a roster in this league — the real, played drafts.

    The veteran stage used to subtract only what the ROOKIE MOCK took in this
    browser session, which meant a league whose rookie draft had actually happened
    still offered all sixteen of those players in the veteran pool. Practising
    against men who are already gone is practising the wrong draft, which is the
    one thing this module exists to prevent.

    Current rosters rather than a replay of the completed drafts, because rosters
    are downstream of everything: the draft, plus every add, drop and trade since.
    Checked against 7 1/2 Men — its 2-round rookie draft made 16 picks and all 16
    are still rostered, so the two agree there and rosters keep agreeing after the
    first waiver claim.
    """
    from . import sleeper_client as api
    try:
        return {str(p) for r in (api.get_rosters(str(league_id)) or [])
                for p in (r.get("players") or [])}
    except Exception:  # noqa: BLE001 — no roster data just means no head start
        return set()


def scheduled_rounds(league_id, stage: "Stage") -> int:
    """Rounds for this stage. The CONFIG above wins; the platform is not asked.

    This briefly read the round count off the league's pending Sleeper draft, on
    the theory that the commissioner is a better source than this repo. He isn't,
    here — Sleeper caps a supplemental draft at 10 rounds, so 7 1/2 Men runs its
    13-round veteran draft as more than one supplemental. The 10 on the platform
    is a limit of the tool, not a description of the league, and a mock built from
    it would practise ten rounds of a thirteen-round draft.

    Kept as a function rather than inlined so the seam stays visible: if a league
    ever does need its rounds read from the platform, this is where that goes.
    """
    return stage.rounds


def is_rookie(pid, registry) -> bool:
    """NFL rookie. Deliberately years_exp == 0 and not draft provenance: this
    decides who may be TAKEN in the rookie draft, which is a question about the
    player's NFL experience. (Keeper PRICING in that league turns on provenance
    instead, but that lives in its own hub.)"""
    try:
        return getattr(registry.meta(pid), "years_exp", None) == 0
    except Exception:  # noqa: BLE001
        return False


def eligible(pool, stage: Stage, registry, taken=None):
    """Filter a draft pool for this stage, dropping anyone already taken earlier."""
    gone = {str(p) for p in (taken or ())}
    out = []
    for p in pool or []:
        pid = str(p.get("pid") if isinstance(p, dict) else p)
        if pid in gone:
            continue
        if stage.pool == "rookies" and not is_rookie(pid, registry):
            continue
        out.append(p)
    return out


def apply(ctx, stage: Stage, taken=None):
    """A ctx scoped to one stage: right round count, right pool, earlier picks gone.

    Returns a shallow copy — the cached originals must stay intact, since the other
    stage (and every other tab) still needs the full board."""
    import dataclasses
    reg = ctx["registry"]
    new = dict(ctx)
    new["meta"] = dataclasses.replace(ctx["meta"], draft_rounds=stage.rounds)
    for key in ("adp_pool", "ai_pool"):
        if ctx.get(key):
            new[key] = eligible(ctx[key], stage, reg, taken)
    if ctx.get("source_pools"):
        new["source_pools"] = {k: eligible(v, stage, reg, taken)
                               for k, v in ctx["source_pools"].items()}
    new["stage"] = stage
    # His SAVED RANKINGS live in session state, not in ctx, so filtering the pools
    # above left the visible board untouched: the AI would not draft a man who was
    # already gone, but the list in front of him still offered Jeremiyah Love with
    # a DRAFT button next to him. Hand the set down so the renderer can scope the
    # one list this module cannot reach.
    new["stage_taken"] = {str(p) for p in (taken or ())}
    return new
