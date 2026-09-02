"""Leagues with a FIXED roster — you must end with an exact positional shape.

"Show us your TD's" (ESPN 798873) does not let you build the roster you like. Every
team finishes with the same 16:

    2 QB · 4 RB · 4 WR · 2 TE · 2 K · 2 D/ST

ESPN states it as caps — positionLimits of 2 QB, 4 RB, 4 WR, 2 TE, 2 K, 2 D/ST —
and since those caps sum to 16 against a 16-man draft, every maximum is also a
minimum. There is no bench to spend on upside and no flexibility to punt a
position: two kickers and two defenses are compulsory, and a fifth running back is
impossible however the board falls.

WHAT THIS IS NOT. The league's ESPN draft data shows a tidy QB-QB-RB-RB-RB-RB-WR…
round order, and it is tempting to read that as a positional draft. It is not.
They draft live and enter the results into ESPN afterwards, position block by
position block, so that order is the DATA ENTRY, not the draft. Constraining the
board by round on the strength of it would have locked him out of every player he
could actually take. The caps below are real; the round order is an artefact.

The 17th round ESPN reports is a phantom — twelve picks with playerId -1 and
nobody in them. The draft is 16 real rounds.
"""
from __future__ import annotations

from typing import Dict, List

# league id -> the exact roster every team must finish with, in a sensible
# draft-board order (the order here is presentational only).
ROSTER: Dict[str, List[tuple]] = {
    "798873": [("QB", 2), ("RB", 4), ("WR", 4), ("TE", 2), ("K", 2), ("DST", 2)],
}


def is_fixed_roster(league_id) -> bool:
    return str(league_id) in ROSTER


def rounds(league_id) -> int:
    """Real rounds — 16 here, not the 17 ESPN reports."""
    return sum(n for _pos, n in ROSTER.get(str(league_id), []))


def roster_slots(league_id) -> List[str]:
    """The roster as a flat slot list.

    This is what the team OWNS, which in a fixed-roster league is the only thing
    the draft can produce. ESPN's lineupSlotCounts describes the weekly lineup
    (QB/RB/RB/WR/WR/TE/FLEX/D-ST/K plus bench) — that is what you start, not what
    you must end up holding, and a roster panel built from it shows a bench this
    league does not have.
    """
    out: List[str] = []
    for pos, n in ROSTER.get(str(league_id), []):
        out.extend([pos] * n)
    return out


def caps(league_id) -> Dict[str, int]:
    return {pos: n for pos, n in ROSTER.get(str(league_id), [])}


def _pos_of(pid, registry) -> str:
    try:
        q = (registry.meta(pid).position or "").upper()
    except Exception:  # noqa: BLE001
        return ""
    return "DST" if q in ("DEF", "D/ST") else q


def still_needed(pids, league_id, registry) -> Dict[str, int]:
    """{position: how many more you MUST draft}.

    In a fixed-roster league this is the whole of "what's left" — every remaining
    pick is spoken for, so a position you have filled is closed and one you have
    not is compulsory.
    """
    want = caps(league_id)
    if not want:
        return {}
    for pid in pids or []:
        pos = _pos_of(pid, registry)
        if want.get(pos):
            want[pos] -= 1
    return {p: n for p, n in want.items() if n > 0}


def is_full(pids, league_id, registry, pos: str) -> bool:
    """Has this roster already used every slot at `pos`? Drafting one more is not
    a bad idea in this league, it is an illegal roster."""
    return still_needed(pids, league_id, registry).get((pos or "").upper(), 0) <= 0


def must_reserve(pids, league_id, registry, picks_left: int) -> Dict[str, int]:
    """Positions he can no longer defer, given how many picks remain.

    Two kickers and two defenses are compulsory here, so with four picks left and
    none of them taken, every remaining pick is spoken for and the board should
    say so rather than keep recommending a fifth receiver he cannot roster.
    """
    need = still_needed(pids, league_id, registry)
    if not need:
        return {}
    return need if sum(need.values()) >= int(picks_left or 0) else {}


# The strategy a league's own history argues for. Only set where it has actually
# been measured — a default nobody checked is worse than no default.
DEFAULT_STRATEGY = {
    "798873": "Carries & Catches",
}


def default_strategy(league_id):
    return DEFAULT_STRATEGY.get(str(league_id))
