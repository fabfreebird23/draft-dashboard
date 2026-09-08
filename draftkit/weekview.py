"""The week, seen from one roster: who plays when, who has played, where each
starter should SIT, and what the calendar makes urgent today.

Pure functions over `gametime` (the NFL schedule) and `lineup` (the optimiser).
No Streamlit here so every rule can be run against a made-up Sunday in a test.

Three questions this answers that nothing else in the engine did:

  * SLOT PLACEMENT. Who starts is settled by points. Where he sits is not, and it
    decides how much of the week is still open to you after the first kickoff:
    a Thursday receiver parked in FLEX spends the FLEX before any news arrives.
    `slot_advice` says which starters to re-seat so every flex holds the LATEST
    game. The starters never change — only the labels.
  * STILL TO PLAY. On a Sunday the projection is the wrong number; the score,
    and how much of each side has yet to kick off, is the right one.
  * WHAT DAY IT IS. The Command Center ranks actions by points at stake. The
    calendar changes what "at stake" means — a waiver claim is the top item on
    Tuesday and noise on Sunday morning — so `rank_actions` re-weights by phase.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from . import gametime as GT, lineup as LU

# Kickoff order matters only up to a tie: two games at 1:00 are the same lock.


def _team(registry, pid) -> str:
    try:
        return (registry.meta(pid).team or "").upper()
    except Exception:  # noqa: BLE001
        return ""


def game_of(registry, games: dict, pid) -> Optional[dict]:
    return (games or {}).get(_team(registry, pid))


def kickoff_of(registry, games: dict):
    """A `pid -> sortable kickoff` closure for the optimiser."""
    def _k(pid):
        return GT.kickoff_ts(game_of(registry, games, pid))
    return _k


def label_of(registry, games: dict):
    def _l(pid):
        return GT.day_label(game_of(registry, games, pid))
    return _l


# ------------------------------------------------------------- slot placement
def slot_advice(current, registry, games: dict) -> List[dict]:
    """[{pid, name, from_slot, to_slot, swap_pid, swap_name, day, swap_day, why}]

    `current` is the platform's set lineup as [(slot, pid)]. Only swaps that move
    an EARLIER kickoff out of a flex and a later one in. Empty when the placement
    is already right, when there is no flex, or when the schedule is unknown —
    advice built on a schedule we do not have is worse than silence.
    """
    if not games or not current:
        return []
    moves = LU.slot_moves(current, [s for s, _p in current], registry,
                          kickoff_of(registry, games), label_of(registry, games))
    out = []
    for m in moves:
        g1, g2 = game_of(registry, games, m["pid"]), game_of(registry, games, m["swap_pid"])
        # Both kick off at the same time → nothing gained, and saying so would be
        # a change for its own sake. The optimiser cannot see ties; this can.
        if GT.kickoff_ts(g1) >= GT.kickoff_ts(g2):
            continue
        # A game already under way or over cannot be re-seated on either platform.
        if GT.status(g1) != "pre" or GT.status(g2) != "pre":
            continue
        try:
            n1, n2 = registry.meta(m["pid"]).name, registry.meta(m["swap_pid"]).name
        except Exception:  # noqa: BLE001
            continue
        out.append({**m, "name": n1, "swap_name": n2,
                    "day": GT.day_label(g1), "swap_day": GT.day_label(g2),
                    "why": (f"{n1} plays {GT.day_label(g1)}, {n2} not until "
                            f"{GT.day_label(g2)} — keep the {m['from_slot']} open for the "
                            f"later game")})
    return out


# ------------------------------------------------------------- still to play
def played_state(current, registry, games: dict, live: Optional[dict] = None) -> dict:
    """{pre: [pids], live: [pids], done: [pids], bye: [pids], n: int} for a set
    lineup, plus each starter's actual points where `live` has them."""
    out = {"pre": [], "live": [], "done": [], "bye": [], "n": 0, "pts": {}}
    for _s, pid in (current or []):
        if not pid or str(pid) in ("0", "None"):
            continue
        out["n"] += 1
        g = game_of(registry, games, pid)
        s = GT.status(g)
        out[{"pre": "pre", "in": "live", "post": "done"}.get(s, "bye")].append(pid)
        if live and str(pid) in (live.get("players") or {}):
            out["pts"][str(pid)] = float(live["players"][str(pid)])
    return out


def live_projection(current, proj: dict, registry, games: dict, live: Optional[dict]) -> float:
    """Actual points for men who have played or are playing, projection for the
    rest — the honest "where this ends up" number once kickoff has happened."""
    tot = 0.0
    pp = (live or {}).get("players") or {}
    for _s, pid in (current or []):
        if not pid or str(pid) in ("0", "None"):
            continue
        g = game_of(registry, games, pid)
        s = GT.status(g)
        if s == "post":
            tot += float(pp.get(str(pid), 0.0) or 0.0)
        elif s == "in":
            # partway: actual so far plus a share of the projection for what's left.
            # Without a clock, half is the honest guess.
            tot += float(pp.get(str(pid), 0.0) or 0.0) + 0.5 * float(proj.get(str(pid), 0) or 0)
        else:
            tot += float(proj.get(str(pid), 0) or 0)
    return tot


# ------------------------------------------------------------- the calendar
_PHASE_LABEL = {
    "waivers": "waivers open",
    "setup": "set your lineup",
    "live": "games on",
    "late": "late games left",
    "done": "week over",
}


def phase_label(phase: str) -> str:
    return _PHASE_LABEL.get(phase, "")


def next_lock(current, registry, games: dict, now: Optional[float] = None):
    """(seconds until, pid, label) for the earliest starter yet to kick off, or
    None. The clock on the Command Center's top item."""
    now = now or time.time()
    best = None
    for _s, pid in (current or []):
        if not pid or str(pid) in ("0", "None"):
            continue
        g = game_of(registry, games, pid)
        if GT.status(g) != "pre":
            continue
        k = GT.kickoff_ts(g)
        if k == float("inf"):
            continue
        if best is None or k < best[0]:
            best = (k, pid, GT.day_label(g))
    if not best:
        return None
    return (best[0] - now, best[1], best[2])


def countdown(secs: float) -> str:
    if secs <= 0:
        return "locked"
    m = int(secs // 60)
    if m < 60:
        return f"{m}m"
    h = m // 60
    if h < 48:
        return f"{h}h {m % 60:02d}m" if h < 6 else f"{h}h"
    return f"{h // 24}d"


def rank_actions(acts: List[dict], phase: str) -> List[dict]:
    """Re-weight the Command Center's actions for the day.

    Each act is {kind, weight, ...}; kinds: waiver, injury, lineup, slot, bye,
    live, ok. The weight is points at stake and stays the tiebreak; the phase
    decides which kinds LEAD and which are dimmed (`dim`=True) as not-today.
    """
    lead = {"waivers": ("waiver", "bye"),
            "setup": ("injury", "lineup", "slot"),
            "live": ("live", "injury", "lineup"),
            "late": ("live", "lineup", "injury"),
            "done": ("live", "waiver")}.get(phase, ("lineup", "injury"))
    # Slot placement is never dimmed before Thursday: it is the one lineup move
    # that is right on Tuesday and stays right — the calendar is what it is about.
    dim = {"waivers": ("injury",),
           "setup": (),
           "live": ("waiver", "slot"),
           "late": ("waiver", "slot"),
           "done": ("injury", "lineup", "slot", "bye")}.get(phase, ())
    out = []
    for a in acts:
        k = a.get("kind", "")
        a = dict(a)
        a["dim"] = k in dim
        # lead kinds float above everything; dimmed sink; weight breaks ties
        a["_ord"] = (0 if k in lead else (2 if a["dim"] else 1), -float(a.get("weight") or 0))
        out.append(a)
    out.sort(key=lambda a: a["_ord"])
    # the all-clear confirmation always goes last
    ok = [a for a in out if a.get("kind") == "ok"]
    return [a for a in out if a.get("kind") != "ok"] + ok


# ------------------------------------------------------------- streaming
def stream_rank(cands: List[dict], registry, games: dict, pos: str) -> List[dict]:
    """Free-agent defenses or kickers ranked by THIS week's matchup.

    For a D/ST the number is the OPPONENT's implied total — fewer points allowed
    is the whole job. For a K it is the team's OWN implied total — a kicker on a
    26-point favourite gets attempts. Each candidate gains {implied, opp, day,
    edge}; sorted best first; a team on bye or with no line sorts last.
    """
    out = []
    for c in cands:
        g = game_of(registry, games, c.get("pid"))
        if not g:
            out.append({**c, "implied": None, "opp": "bye", "day": "—", "edge": None,
                        "spread": None})
            continue
        if pos in ("DST", "DEF"):
            val = g.get("opp_implied")
            edge = (None if val is None else round(22.0 - float(val), 1))
        else:
            val = g.get("implied")
            edge = (None if val is None else round(float(val) - 22.0, 1))
        out.append({**c, "implied": val, "opp": ("vs " if g.get("home") else "@ ") + g["opp"],
                    "day": GT.day_label(g), "edge": edge, "spread": g.get("spread")})
    out.sort(key=lambda r: (r["edge"] is None, -(r["edge"] or 0)))
    return out


# ------------------------------------------------------------- bench regret
def bench_regret(weeks: Dict[int, dict], slots, registry) -> dict:
    """{weeks: [{week, actual, best, left}], total_left, n}: what the set lineup
    scored each week against the best it could have, from actual points.

    `weeks` is {week: {"starters": [pid], "players": [pid], "points": {pid: pts}}}.
    """
    from . import weekly as W
    rows = []
    for wk in sorted(weeks):
        d = weeks[wk]
        pts = {str(k): float(v or 0) for k, v in (d.get("points") or {}).items()}
        if not pts:
            continue
        actual = sum(pts.get(str(p), 0.0) for p in (d.get("starters") or []) if p)
        try:
            best = W.fast_score([str(p) for p in (d.get("players") or [])], slots, pts, registry)
        except Exception:  # noqa: BLE001
            best = actual
        rows.append({"week": wk, "actual": round(actual, 1), "best": round(best, 1),
                     "left": round(max(0.0, best - actual), 1)})
    return {"weeks": rows, "total_left": round(sum(r["left"] for r in rows), 1), "n": len(rows)}
