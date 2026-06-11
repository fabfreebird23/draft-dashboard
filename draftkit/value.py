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
    overall_rank: Dict[str, int] = field(default_factory=dict)  # pid -> rank by VORP

    def vorp_of(self, pid) -> float:
        return self.vorp.get(str(pid), 0.0)

    def proj_of(self, pid) -> float:
        return self.proj.get(str(pid), 0.0)

    def rank_of(self, pid):
        return self.overall_rank.get(str(pid))

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
    # overall draft-value rank: every player ordered by VORP (cross-position)
    overall_rank = {pid: i + 1 for i, (pid, _) in
                    enumerate(sorted(vorp.items(), key=lambda x: x[1], reverse=True))}
    return ValueModel(proj=proj, vorp=vorp, replacement_pts=replacement_pts,
                      pos_sorted=pos_players, overall_rank=overall_rank)


def team_demand(roster_slots) -> Dict[str, float]:
    """Per-team starter demand at each position (slots + flex share, no ×teams)."""
    c = Counter(roster_slots or [])
    flex = sum(c.get(name, 0) for name in _FLEX_NAMES)
    superflex = sum(c.get(name, 0) for name in _SUPERFLEX_NAMES)
    d: Dict[str, float] = {}
    for pos in _POSITIONS:
        v = c.get(pos, 0) + flex * _FLEX_SPLIT.get(pos, 0)
        if pos == "QB":
            v += superflex
        d[pos] = v
    return d


def roster_multiplier(pos: str, my_pids, roster_slots, registry) -> float:
    """How much YOU still value another player at ``pos``, given the roster you've
    built. 1.0 = an unfilled *starting* slot (a real need); ~0.6-0.9 = useful
    flex/bench depth; low = a luxury (the classic 'a 2nd QB or TE once your single
    slot is full' that the recommender should stop pushing).

    This is the heart of the roster-aware AI: it separates a dedicated starting
    requirement (QB×1, TE×1, …) from FLEX depth, so once your one QB/TE is in, the
    engine stops treating elite-but-redundant players at that position as top picks
    and steers you to positions you actually still start."""
    c = Counter(roster_slots or [])
    flex_slots = sum(c.get(n, 0) for n in _FLEX_NAMES)
    superflex = sum(c.get(n, 0) for n in _SUPERFLEX_NAMES)
    have = Counter(registry.meta(p).position for p in (my_pids or []))
    dedicated = c.get(pos, 0) + (superflex if pos == "QB" else 0)
    h = have.get(pos, 0)
    if h < dedicated:
        return 1.0                                   # unfilled starter — full value
    surplus = h - dedicated                          # extras already rostered
    flex_elig = pos in ("RB", "WR", "TE") or (pos == "QB" and superflex)
    flex_used = sum(max(0, have.get(p, 0) - c.get(p, 0)) for p in ("RB", "WR", "TE"))
    flex_open = max(0, flex_slots - flex_used)
    if flex_elig and flex_open > 0:
        # can slot into a FLEX — useful, but a 2nd TE rarely actually flexes
        base = 0.9 if pos in ("RB", "WR") else 0.55
        return round(max(0.4, base * (0.85 ** surplus)), 2)
    if pos in ("QB", "TE", "K", "DST"):
        return round(max(0.1, 0.28 ** (surplus + 1)), 2)   # backup 1-slot spot: low
    return round(max(0.3, 0.55 ** (surplus + 1)), 2)       # RB/WR bench depth


def marginal_vorp(model: "ValueModel", pid, my_pids, registry, roster_slots) -> float:
    """VORP adjusted for YOUR roster (see ``roster_multiplier``): once your starter
    slots at a position are full, each additional player there depreciates."""
    pm = registry.meta(pid)
    mult = roster_multiplier(pm.position, my_pids, roster_slots, registry)
    return round(model.vorp_of(pid) * mult, 1)


def steals_and_traps(board_avail, model: "ValueModel", registry, adp_rank, *,
                     k=6, thresh=8, pool_size=180):
    """Find market inefficiencies among *draftable* players: STEALS go later than
    their value warrants (ADP rank ≫ value rank), TRAPS go earlier. Restricted to
    players whose ADP and value rank are both inside the draftable pool, so deep
    waiver-wire names with projection-noise don't pollute the list. Returns
    (steals, traps) as lists of (row, gap, value_rank, adp)."""
    cap = pool_size * 1.25                     # a little past the last pick
    steals, traps = [], []
    for r in board_avail:
        pid = str(r["pid"])
        pm = registry.meta(pid)
        vr = model.rank_of(pid)
        adp = adp_rank(pm.name, pm.position)
        if not vr or not adp or adp > cap or vr > cap:
            continue
        gap = adp - vr                        # +: falling past value → steal
        if gap >= thresh:
            steals.append((r, gap, vr, int(adp), pm.position))
        elif gap <= -thresh:
            traps.append((r, gap, vr, int(adp), pm.position))
    steals.sort(key=lambda x: -x[1])
    traps.sort(key=lambda x: x[1])

    def diversify(items, per_pos=2):
        seen, out = {}, []
        for it in items:
            pos = it[4]
            if seen.get(pos, 0) >= per_pos:
                continue
            seen[pos] = seen.get(pos, 0) + 1
            out.append(it[:4])
            if len(out) >= k:
                break
        return out

    return diversify(steals), diversify(traps)


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
              next_pick=None, survival_fn=None, my_pids=None, roster_slots=None):
    """Roster-aware recommendation: rank available players by VORP (marginal —
    adjusted for the roster you've already built), boosted for positions you still
    need and for scarcity. Returns (row, score, reason) or (None, 0, '')."""
    needs = needs or set()
    taken_s = {str(x) for x in (taken or [])}
    use_roster = my_pids is not None and roster_slots is not None
    best = None
    for r in board_avail[:60]:
        pid = str(r["pid"])
        pm = registry.meta(pid)
        mult = (roster_multiplier(pm.position, my_pids, roster_slots, registry)
                if use_roster else 1.0)
        raw = model.vorp_of(pid)
        score = raw * mult                       # roster-discounted value
        reasons = [f"+{raw:.0f} value"]
        # reward filling an actual starting need; only lightly reward depth, and
        # never push a redundant 1-slot position (a 2nd QB/TE) up the board.
        if mult >= 0.999:
            score += 22
            reasons.append(f"fills {pm.position} starter")
        elif mult >= 0.55:
            score += 6
            reasons.append(f"{pm.position} depth")
        else:
            reasons.append(f"{pm.position} bench — already set")
        # scarcity & 'won't return' only matter for a spot you'd actually start
        if mult >= 0.6:
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


def grab_verdict(survival_pct, startable_left, *, is_need=False, mult=None):
    """Fuse 'how likely to fall to me' (survival) with 'how scarce' (startable left)
    into a call to action. ``mult`` is the roster multiplier — when you've already
    filled this position's starting slots, the verdict says so instead of urging a
    redundant grab. Returns (label, css_class) or None."""
    if mult is not None and mult < 0.5:
        return ("BENCH DEPTH", "wait")        # starters here are already set
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
