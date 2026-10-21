"""Next season's draft, simulated pick by pick.

The 2027 draft preview answered "who is likely there at MY picks". This builds
the whole board: every pick in order, who holds it after trades, every team's
keepers sitting on the picks they will actually spend, and everybody else
taken best-available off the projected next-year ADP (draftkit/nextyear.py).

Pure functions: the screen hands in the order, the picks, the keepers and the
pool, so the placement rules can be tested without a league.

Rules it follows:
  * the order is a list of roster ids, slot 1 first; snake by default
  * a pick belongs to whoever holds it now (`origin` is whose it was)
  * a keeper lands on a pick his team holds in his cost round — the LATEST
    one in that round, so an earlier pick in the same round stays live — and
    if they traded that round away, the nearest EARLIER round they hold (the
    hubs' bylaw: never down to a cheaper pick). No pick at or before his
    round, and he is not placed.
  * everyone else goes best-available by projected rank, with a sanity cap
    (no team takes a third QB or TE) so the board reads like a real draft
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

CAPS = {"QB": 2, "TE": 2}


def sequence(order: List[int], rounds: int, snake: bool = True) -> List[Tuple[int, int, int]]:
    """[(pick_no, round, slot)] in draft order. Slot is 1-based."""
    n = len(order)
    out, pick = [], 0
    for r in range(1, rounds + 1):
        slots = list(range(1, n + 1))
        if snake and r % 2 == 0:
            slots.reverse()
        for s in slots:
            pick += 1
            out.append((pick, r, s))
    return out


def build(order: List[int], rounds: int, held: Dict[Tuple[int, int], int],
          keepers: Dict[int, List[Tuple[str, int]]], pool: List[str],
          pos_of: Dict[str, str], *, snake: bool = True,
          caps: Optional[Dict[str, int]] = None) -> Dict[Tuple[int, int], dict]:
    """{(round, slot): {pick, round, slot, holder, origin, traded, pid, keeper}}.

    `held` maps (round, origin_roster_id) -> the roster id holding that pick now.
    `keepers` maps roster id -> [(pid, cost_round)].
    `pool` is every candidate pid, best first.
    """
    caps = CAPS if caps is None else caps
    seq = sequence(order, rounds, snake)
    cells: Dict[Tuple[int, int], dict] = {}
    for pick, r, s in seq:
        origin = order[s - 1]
        holder = held.get((r, origin), origin)
        cells[(r, s)] = {"pick": pick, "round": r, "slot": s, "holder": holder, "origin": origin,
                         "traded": holder != origin, "pid": None, "keeper": False}

    # keepers first, on the picks their team will actually spend
    by_holder: Dict[int, Dict[int, List[dict]]] = {}
    for c in cells.values():
        by_holder.setdefault(c["holder"], {}).setdefault(c["round"], []).append(c)
    kept = set()
    for rid, ks in keepers.items():
        rounds_held = by_holder.get(rid, {})
        for pid, cost in sorted(ks, key=lambda k: (k[1] or 99)):
            if not cost:
                continue
            spot = None
            for rr in range(int(cost), 0, -1):          # the cost round, else earlier
                free = [c for c in rounds_held.get(rr, []) if c["pid"] is None]
                if free:
                    spot = max(free, key=lambda c: c["pick"])  # latest pick in the round
                    break
            if spot is None:
                continue
            spot.update(pid=str(pid), keeper=True)
            kept.add(str(pid))

    # everyone else, best available in pick order
    counts: Dict[int, Dict[str, int]] = {}
    for c in cells.values():
        if c["pid"]:
            p = pos_of.get(c["pid"], "")
            counts.setdefault(c["holder"], {})[p] = counts.setdefault(c["holder"], {}).get(p, 0) + 1
    avail = [p for p in pool if str(p) not in kept]
    for pick, r, s in seq:
        c = cells[(r, s)]
        if c["pid"]:
            continue
        mine = counts.setdefault(c["holder"], {})
        for i, p in enumerate(avail):
            pos = pos_of.get(p, "")
            if pos in caps and mine.get(pos, 0) >= caps[pos]:
                continue
            c["pid"] = p
            mine[pos] = mine.get(pos, 0) + 1
            avail.pop(i)
            break
    return cells
