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
from typing import List, Optional

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
        Stage(VETERAN, "Veteran draft", 14, "all",
              "The main draft, with rookie-draft picks already off the board."),
    ],
}


def stages_for(league_id) -> Optional[List[Stage]]:
    return STAGES.get(str(league_id))


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
    return new
