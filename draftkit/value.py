"""The value engine — turns raw projections into draft intelligence.

VORP (value over replacement player) is the core: a player is worth the points he
scores *above the best guy you could stream at his position*. Replacement level is
derived from the league's actual starting requirements, so a 10-team 2-RB league
and a 12-team flex-heavy league get different baselines. On top of VORP we expose
positional scarcity (how many startable players remain) and a grab-vs-wait verdict
that fuses scarcity with the survival probability.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List

_POSITIONS = ("QB", "RB", "WR", "TE")
# How a FLEX (and SUPER_FLEX) slot's demand splits across positions.
_FLEX_SPLIT = {"RB": 0.40, "WR": 0.45, "TE": 0.15}
_FLEX_NAMES = {"FLEX", "W/R/T", "WRT", "RB/WR/TE", "REC_FLEX", "WR/RB", "WR/TE"}
_SUPERFLEX_NAMES = {"SUPER_FLEX", "SFLEX", "Q/W/R/T", "OP"}


def replacement_ranks(roster_slots: List[str], n_teams: int) -> Dict[str, int]:
    """The positional rank that defines 'replacement level' — i.e. how many of each
    position are locked up as starters across the whole league."""
    c = Counter(roster_slots or [])
    flex = sum(c.get(name, 0) for name in _FLEX_NAMES)
    superflex = sum(c.get(name, 0) for name in _SUPERFLEX_NAMES)
    ranks: Dict[str, int] = {}
    for pos in _POSITIONS:
        demand = c.get(pos, 0)
        demand += flex * _FLEX_SPLIT.get(pos, 0)
        if pos == "QB":
            demand += superflex            # superflex is almost always a 2nd QB
        else:
            demand += superflex * _FLEX_SPLIT.get(pos, 0) * 0.5
        ranks[pos] = max(1, round(demand * max(1, n_teams)))
    return ranks


@dataclass
class ValueModel:
    proj: Dict[str, float]                       # pid -> projected points
    vorp: Dict[str, float]                       # pid -> value over replacement
    replacement_pts: Dict[str, float]            # pos -> replacement-level points
    pos_sorted: Dict[str, list] = field(default_factory=dict)  # pos -> [(pid, pts)] desc

    def vorp_of(self, pid) -> float:
        return self.vorp.get(str(pid), 0.0)

    def proj_of(self, pid) -> float:
        return self.proj.get(str(pid), 0.0)

    def startable_left(self, pos: str, drafted: set) -> int:
        """How many at this position are still above replacement and available."""
        repl = self.replacement_pts.get(pos)
        if repl is None:
            return 0
        return sum(1 for pid, pts in self.pos_sorted.get(pos, [])
                   if pts >= repl and str(pid) not in drafted)


def build_value(proj: Dict[str, float], registry, roster_slots, n_teams) -> ValueModel:
    """Compute VORP for every projected player from league-specific replacement
    levels."""
    pos_players: Dict[str, list] = {p: [] for p in _POSITIONS}
    for pid, pts in proj.items():
        pos = registry.meta(pid).position
        if pos in pos_players:
            pos_players[pos].append((str(pid), float(pts)))
    for pos in pos_players:
        pos_players[pos].sort(key=lambda x: x[1], reverse=True)

    ranks = replacement_ranks(roster_slots, n_teams)
    replacement_pts: Dict[str, float] = {}
    for pos, players in pos_players.items():
        if not players:
            replacement_pts[pos] = 0.0
            continue
        idx = min(ranks.get(pos, len(players)) - 1, len(players) - 1)
        replacement_pts[pos] = players[max(0, idx)][1]

    vorp: Dict[str, float] = {}
    for pos, players in pos_players.items():
        repl = replacement_pts.get(pos, 0.0)
        for pid, pts in players:
            vorp[pid] = round(pts - repl, 1)
    return ValueModel(proj=proj, vorp=vorp, replacement_pts=replacement_pts,
                      pos_sorted=pos_players)


def synergy(pm, my_pids, registry) -> List[tuple]:
    """Roster-fit tags for an available player vs. the team you've drafted:
    handcuffs (same-team RB behind your stud) and stacks (QB ↔ pass-catcher on the
    same NFL team). Returns [(kind, partner_name), ...]."""
    tags: List[tuple] = []
    if not getattr(pm, "team", None):
        return tags
    mine = [registry.meta(p) for p in (my_pids or [])]
    same_team = [m for m in mine if m.team == pm.team and m.name != pm.name]
    if pm.position == "RB":
        for m in same_team:
            if m.position == "RB":
                tags.append(("Handcuff", m.name))
    if pm.position in ("WR", "TE"):
        for m in same_team:
            if m.position == "QB":
                tags.append(("Stack", m.name))
    if pm.position == "QB":
        for m in same_team:
            if m.position in ("WR", "TE"):
                tags.append(("Stack", m.name))
    return tags


def best_pick(board_avail, model: "ValueModel", registry, needs, taken,
              next_pick=None, survival_fn=None):
    """Roster-aware recommendation: rank available players by VORP, boosted for
    positions you still need and for scarcity (few startable left / unlikely to
    survive to your next pick). Returns (row, score, reason) or (None, 0, '')."""
    needs = needs or set()
    taken_s = {str(x) for x in (taken or [])}
    best = None
    for r in board_avail[:60]:
        pid = str(r["pid"])
        pm = registry.meta(pid)
        v = model.vorp_of(pid)
        score = v
        reasons = [f"+{v:.0f} value"]
        if pm.position in needs:
            score += 18
            reasons.append(f"fills {pm.position} need")
        left = model.startable_left(pm.position, taken_s)
        if left <= 3:
            score += (4 - left) * 8
            reasons.append(f"{left} startable {pm.position}s left")
        if survival_fn and next_pick:
            sv = survival_fn(pid)
            if sv is not None and sv <= 35:
                score += (35 - sv) * 0.5
                reasons.append("unlikely to return")
        if best is None or score > best[1]:
            best = (r, score, " · ".join(reasons[:3]))
    return best or (None, 0, "")


def grab_verdict(survival_pct, startable_left, *, is_need=False):
    """Fuse 'how likely to fall to me' (survival) with 'how scarce' (startable left)
    into a call to action. Returns (label, css_class) or None."""
    if survival_pct is None:
        return None
    scarce = startable_left is not None and startable_left <= 3
    very_scarce = startable_left is not None and startable_left <= 1
    if survival_pct <= 25 or very_scarce or (scarce and survival_pct < 55):
        return ("GRAB NOW", "grab")
    if survival_pct >= 75 and not scarce:
        return ("CAN WAIT", "wait")
    if is_need and survival_pct < 60:
        return ("LEAN GRAB", "lean")
    return ("HOLD / OK", "ok")
