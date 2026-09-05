"""Leagues with a FIXED roster — you must end with an exact positional shape.

"Show us your TD's" (ESPN 798873) does not let you build the roster you like.
Seventeen players, and the shape is almost entirely fixed:

    2 QB · 2 TE · 2 K · 2 D/ST — exactly, no more and no less
    9 between RB and WR, at least 4 of each — so 5 RB + 4 WR, or 4 RB + 5 WR

ESPN states it as maximums (2 QB, 5 RB, 5 WR, 2 TE, 2 K, 2 D/ST) which sum to 18
against 17 roster spots. That one spare is the whole of his freedom in this draft:
the 17th slot is an RB or a WR and nothing else. It is why the roster read as
"one extra slot we can't use" — a fifth back and a fifth receiver each look legal
on their own, and only the total says you cannot have both.

Everywhere else the maximum IS the minimum. There is no bench to spend on upside
and no punting a position: two kickers and two defenses are compulsory, and a
third quarterback is not a bad idea, it is a roster ESPN will not register.

WHAT THIS IS NOT. The league's ESPN draft data shows a tidy QB-QB-RB-RB-RB-RB-WR…
round order, and it is tempting to read that as a positional draft. It is not.
They draft live and enter the results into ESPN afterwards, position block by
position block, so that order is the DATA ENTRY, not the draft. Constraining the
board by round on the strength of it would have locked him out of every player he
could actually take. The shape below is real; the round order is an artefact.
"""
from __future__ import annotations

from typing import Dict, List

# league id -> the MINIMUM at each position, in a sensible draft-board order (the
# order here is presentational only).
ROSTER: Dict[str, List[tuple]] = {
    "798873": [("QB", 2), ("RB", 4), ("WR", 4), ("TE", 2), ("K", 2), ("DST", 2)],
}

# ...plus the slots that float. `pos` is who may actually fill them; the LABEL is
# the generic "FLEX" every roster panel already knows how to draw and fill, and
# which value.py counts toward replacement level. The label is deliberately looser
# than the rule — a tight-end could sit in a slot drawn as FLEX — because the rule
# is enforced where it belongs, in `legal()`, which never offers a third tight end
# in a league capped at two.
FLEX: Dict[str, dict] = {
    "798873": {"n": 1, "pos": ("RB", "WR"), "label": "FLEX"},
}


def is_fixed_roster(league_id) -> bool:
    return str(league_id) in ROSTER


def _flex(league_id) -> dict:
    return FLEX.get(str(league_id)) or {"n": 0, "pos": (), "label": "FLEX"}


def rounds(league_id) -> int:
    """Real rounds. 17 here: the 16 compulsory slots plus the floating one.

    (ESPN's own draft history reports an 18th round of twelve picks with playerId
    -1 and nobody in them. That one is a phantom.)"""
    if not is_fixed_roster(league_id):
        return 0
    return sum(n for _pos, n in ROSTER[str(league_id)]) + int(_flex(league_id)["n"])


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
    fx = _flex(league_id)
    out.extend([fx["label"]] * int(fx["n"]))
    return out


def minimums(league_id) -> Dict[str, int]:
    return {pos: n for pos, n in ROSTER.get(str(league_id), [])}


def caps(league_id) -> Dict[str, int]:
    """The hard maximum at each position, on its own.

    RB and WR both read 5 because either can take the floating slot. They cannot
    BOTH take it — `legal` is the function that knows that, and it is the one the
    board and the AI filter through.
    """
    fx = _flex(league_id)
    return {pos: n + (int(fx["n"]) if pos in fx["pos"] else 0)
            for pos, n in minimums(league_id).items()}


def _pos_of(pid, registry) -> str:
    try:
        q = (registry.meta(pid).position or "").upper()
    except Exception:  # noqa: BLE001
        return ""
    return "DST" if q in ("DEF", "D/ST") else q


def _counts(pids, registry) -> Dict[str, int]:
    have: Dict[str, int] = {}
    for pid in pids or []:
        pos = _pos_of(pid, registry)
        if pos:
            have[pos] = have.get(pos, 0) + 1
    return have


def still_needed(pids, league_id, registry) -> Dict[str, int]:
    """{position: how many more you MUST draft} — the compulsory shortfall.

    This is what the roster panel means by "needs", and what says a pick can no
    longer be deferred. It is NOT the same as what is legal: with the minimums met
    there is still one floating slot, and `legal` is what may be spent on it.
    """
    want = minimums(league_id)
    if not want:
        return {}
    have = _counts(pids, registry)
    return {p: n - have.get(p, 0) for p, n in want.items() if n - have.get(p, 0) > 0}


def legal(pids, league_id, registry) -> Dict[str, int]:
    """{position: how many more you MAY draft}, floating slot included.

    The floating slot is shared, so it is counted once and offered to every
    position that could fill it. Take a fifth back and it is gone — the receivers
    drop straight back to four, without anyone having to encode "5 RB or 5 WR, not
    both" as a special case.
    """
    want = minimums(league_id)
    if not want:
        return {}
    have = _counts(pids, registry)
    fx = _flex(league_id)
    spent = sum(max(0, have.get(p, 0) - want.get(p, 0)) for p in fx["pos"])
    spare = max(0, int(fx["n"]) - spent)
    out = {}
    for pos, n in want.items():
        room = max(0, n - have.get(pos, 0)) + (spare if pos in fx["pos"] else 0)
        if room > 0:
            out[pos] = room
    return out


def is_full(pids, league_id, registry, pos: str) -> bool:
    """Has this roster no room left at `pos`? Drafting one more is not a bad idea
    in this league, it is a roster the platform will not register."""
    return legal(pids, league_id, registry).get((pos or "").upper(), 0) <= 0


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


# How hard the AI opponents chase running backs, per league. 1.0 is "straight off
# their board". This is NOT measured — the league's recorded pick order is data
# entry, so there is nothing to learn it from. It is his own read of the room,
# written down so the mock starts where he says the draft actually starts, and
# left on a slider so he can move it.
DEFAULT_RB_LEAN = {
    "798873": 1.5,      # "we do draft rb heavy"
}


def default_rb_lean(league_id) -> float:
    return float(DEFAULT_RB_LEAN.get(str(league_id), 1.0))


def lean_pool(pool, registry, lean: float, n_teams: int, pos: str = "RB"):
    """Reorder an AI's board so `pos` comes off earlier, without forcing it.

    A lean of 2.0 moves a back a full round earlier in the queue; 1.0 returns the
    pool untouched. Nudging the ORDER rather than filtering keeps the opponents
    capable of taking anyone — a hard positional rule would make them predictable
    in a way a real room never is.
    """
    if abs(float(lean) - 1.0) < 1e-9 or not pool:
        return pool
    bump = (float(lean) - 1.0) * max(1, int(n_teams or 1))
    want = (pos or "RB").upper()

    def _is(p):
        pid = p.get("pid") if isinstance(p, dict) else p
        try:
            q = (registry.meta(pid).position or "").upper()
        except Exception:  # noqa: BLE001
            return False
        return ("DST" if q in ("DEF", "D/ST") else q) == want

    idx = {id(p): i for i, p in enumerate(pool)}
    return sorted(pool, key=lambda p: idx[id(p)] - (bump if _is(p) else 0))
