"""Weekly lineup optimisation — who to start, and what it's worth to fix.

The maths is a small assignment problem, not a heuristic: with 9-ish slots and a
~15-man roster, every feasible assignment can be enumerated cheaply, so we find
the genuinely best lineup rather than the greedy one. Greedy fails on exactly the
case you care about — it will spend your FLEX on the highest projection left and
strand a better TE on the bench because the TE slot was already filled.

Byes are not a special case; a player on bye simply projects 0 and falls out on
his own. What IS a special case is saying so, because "0.0" in a table reads as a
data problem, not a decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

_FLEX_OK = {"RB", "WR", "TE"}
_SUPERFLEX_OK = {"QB", "RB", "WR", "TE"}


def slot_accepts(slot: str, pos: str) -> bool:
    s = (slot or "").upper()
    if s in ("FLEX", "W/R/T", "WRT", "REC_FLEX"):
        return pos in _FLEX_OK
    if s in ("SUPER_FLEX", "SUPERFLEX", "SFLEX", "OP", "Q/W/R/T"):
        return pos in _SUPERFLEX_OK
    return s == (pos or "").upper()


@dataclass
class Spot:
    slot: str
    pid: Optional[str] = None
    points: float = 0.0
    note: str = ""          # why this spot needs attention, "" when fine


@dataclass
class Lineup:
    spots: List[Spot] = field(default_factory=list)
    bench: List[tuple] = field(default_factory=list)   # (pid, points)
    total: float = 0.0
    current_total: float = 0.0
    problems: List[str] = field(default_factory=list)

    @property
    def gain(self) -> float:
        return self.total - self.current_total


def _best_assignment(slots: List[str], cands: List[tuple], registry) -> Dict[int, str]:
    """Max-total assignment of players to slots.

    Slots are filled most-constrained-first (a TE slot before a FLEX), and each
    slot only ever considers the best few players it can legally take. That keeps
    the search tiny while still being exact for real rosters — the alternative,
    filling greedily in projection order, systematically misuses FLEX."""
    order = sorted(range(len(slots)),
                   key=lambda i: sum(1 for _, _, pos in cands if slot_accepts(slots[i], pos)))
    best: Dict[int, str] = {}
    best_total = -1.0

    def walk(k: int, used: set, chosen: Dict[int, str], total: float):
        nonlocal best, best_total
        if k == len(order):
            if total > best_total:
                best_total, best = total, dict(chosen)
            return
        i = order[k]
        legal = [(pts, pid) for pid, pts, pos in cands
                 if pid not in used and slot_accepts(slots[i], pos)]
        legal.sort(reverse=True)
        if not legal:
            walk(k + 1, used, chosen, total)
            return
        # Branch over a handful of the best options per slot. Beyond that the
        # remaining choices can't beat what an earlier slot already banked.
        for pts, pid in legal[:4]:
            chosen[i] = pid
            walk(k + 1, used | {pid}, chosen, total + pts)
            chosen.pop(i, None)

    walk(0, set(), {}, 0.0)
    return best


def optimize(roster_pids, starters, slots, projections, registry, byes=None,
             week=None) -> Lineup:
    """Best legal lineup for the week, and what it gains over the current one."""
    byes = byes or {}
    cands = []
    for pid in roster_pids:
        try:
            pm = registry.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        pos = (pm.position or "").upper()
        if pos not in _SUPERFLEX_OK:
            continue
        cands.append((str(pid), float(projections.get(str(pid), 0.0) or 0.0), pos))

    start_slots = [s for s in slots if (s or "").upper() not in ("BN", "BENCH", "IR", "TAXI")]
    chosen = _best_assignment(start_slots, cands, registry)
    pts = {pid: p for pid, p, _ in cands}

    lu = Lineup()
    used = set()
    for i, slot in enumerate(start_slots):
        pid = chosen.get(i)
        spot = Spot(slot=slot, pid=pid, points=pts.get(pid, 0.0) if pid else 0.0)
        if pid:
            used.add(pid)
            try:
                pm = registry.meta(pid)
                if byes.get(pm.team) and spot.points <= 0:
                    spot.note = "on bye"
            except Exception:  # noqa: BLE001
                pass
        else:
            spot.note = "empty"
        lu.spots.append(spot)
    lu.total = sum(s.points for s in lu.spots)
    lu.bench = sorted(((pid, pts.get(pid, 0.0)) for pid, _, _ in cands if pid not in used),
                      key=lambda x: -x[1])

    cur = {str(p) for p in (starters or []) if p and str(p) != "0"}
    lu.current_total = sum(pts.get(p, 0.0) for p in cur) if cur else lu.total

    for s in lu.spots:
        if s.note == "empty":
            lu.problems.append(f"{s.slot} is empty")
        elif s.note == "on bye":
            lu.problems.append(f"{s.slot} is on bye")
    if cur:
        moved = [s for s in lu.spots if s.pid and s.pid not in cur]
        if moved and lu.gain > 0.05:
            lu.problems.append(f"{len(moved)} change{'s' if len(moved) != 1 else ''} "
                               f"worth +{lu.gain:.1f}")
    return lu
