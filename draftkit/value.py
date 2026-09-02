"""The value engine — turns raw projections into draft intelligence.

VORP (value over replacement player) is the core: a player is worth the points he
scores *above the best guy you could stream at his position*. Replacement level is
derived from the league's actual starting requirements, so a 10-team 2-RB league
and a 12-team flex-heavy league get different baselines. On top of VORP we expose
positional scarcity (how many startable players remain) and a grab-vs-wait verdict
that fuses scarcity with the survival probability.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List

_POSITIONS = ("QB", "RB", "WR", "TE")
# Keeper-league rookie premium ("strong"): a rookie's value is boosted by this
# fraction PLUS a flat keeper-value floor (rookies project low in year one but
# carry real long-term keeper upside, so even near-startable rookies should rise).
# Tune here to dial the rookie lean up or down across the whole app.
# KEEPER LEAGUES ONLY. A rookie is worth more than his rookie-year points there
# because he converts to a cheap long-term keeper. In a REDRAFT league he is worth
# exactly what he scores this season and nothing else, so applying this premium
# unconditionally is not a lean, it is a wrong number: it lifted Jeremiyah Love to
# a VORP of 795 off a 777-point projection — above his own projection, and above
# Achane and Henry, who both out-project him. Callers say which kind of league
# they are in; see build_value(rookie_premium=...).
ROOKIE_PREMIUM = 0.65
ROOKIE_FLOOR = 16.0
# Board-derived scoring weights. Defined UP HERE because best_pick() uses
# BOARD_EDGE_WEIGHT as a DEFAULT ARGUMENT, which is evaluated at def-time — leaving
# it further down the module raised NameError on import.
TIER_CLIFF_BONUS = 10.0
BOARD_EDGE_WEIGHT = 0.0


def is_rookie(registry, pid) -> bool:
    """True for a first-year player (rookie) per the registry's years_exp."""
    try:
        return registry.meta(pid).years_exp == 0
    except Exception:  # noqa: BLE001
        return False
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

    def is_projected(self, pid) -> bool:
        """Whether we actually have a projection for this player. Unprojected
        players (fullbacks, deep camp bodies) fall through vorp_of to a NEUTRAL
        0.0, which silently outranks a real contributor carrying a negative VORP —
        so late-round suggestions filled up with players nobody would draft.
        Callers rank these below anyone we can genuinely evaluate."""
        return str(pid) in self.proj

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


def build_value(proj: Dict[str, float], registry, roster_slots, n_teams, rookie_premium: bool = True) -> ValueModel:
    """Compute VORP for every projected player from league-specific replacement
    levels.

    `rookie_premium` says whether this league pays for a rookie's FUTURE. In a
    keeper or dynasty league it does; in a redraft it does not, and leaving it on
    there overstates every first-year player by 65% plus a flat floor.
    """
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
    # Keeper-league rookie premium: a rookie is worth more than his rookie-year
    # points because he converts to a cheap long-term keeper. Boost rookies (a %
    # bump plus a keeper-value floor) so good AND near-startable rookies rise on
    # the board, recommendations and Suggestions; truly deep rookies still sink.
    if rookie_premium:
        for pid, v in list(vorp.items()):
            if is_rookie(registry, pid):
                vorp[pid] = round(v * (1 + ROOKIE_PREMIUM) + ROOKIE_FLOOR, 1)
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
    # A 2nd TE only counts as flex depth in a league with NO dedicated TE slot; when
    # you already start a TE you'd play an RB/WR in the flex, so a redundant TE (like
    # a 2nd QB) is a low-value backup, not flex depth.
    te_flexes = pos == "TE" and c.get("TE", 0) == 0
    flex_elig = pos in ("RB", "WR") or te_flexes or (pos == "QB" and superflex)
    # Only RB/WR (and a flex-only TE) actually occupy flex slots — a bench 2nd TE
    # doesn't eat a flex slot away from your RBs/WRs.
    flex_fillers = ("RB", "WR", "TE") if c.get("TE", 0) == 0 else ("RB", "WR")
    flex_used = sum(max(0, have.get(p, 0) - c.get(p, 0)) for p in flex_fillers)
    flex_open = max(0, flex_slots - flex_used)
    if flex_elig and flex_open > 0:
        base = 0.9 if pos in ("RB", "WR") else 0.6
        return round(max(0.4, base * (0.85 ** surplus)), 2)
    if pos in ("QB", "TE", "K", "DST"):
        return round(max(0.08, 0.22 ** (surplus + 1)), 2)  # backup 1-slot spot: low
    # RB/WR bench depth once flex is numerically full: still worth real bench/trade
    # value (unlike a redundant QB/TE), so decay gently off the same 0.85 curve as
    # flex depth above rather than cliffing to near-zero.
    return round(max(0.4, 0.75 * (0.85 ** surplus)), 2)


def redundant_single_slot(pos: str, my_pids, roster_slots, registry) -> bool:
    """True for a player you could no longer get into your starting lineup.

    In a 1-QB league a second QB never starts — you'd stream the one bye week.
    Once your TE slot is full a second TE only plays if a FLEX is still open and
    the league's flex accepts TE. These are the picks managers describe as "I
    would never draft two QBs in this league."

    VORP alone cannot see this, because VORP is measured against each position's
    OWN replacement level. Late in a keeper draft the best remaining TE can be
    TE5 (+12 over TE replacement) while the best remaining WR is WR60 (-20), so
    positional value says take the TE — correctly, and uselessly, because he'd
    never crack your lineup. Suggestions rank these below anything startable
    instead of letting a positional-scarcity artifact win the pick."""
    if pos not in ("QB", "TE", "K", "DST"):
        return False
    c = Counter(roster_slots or [])
    superflex = sum(c.get(n, 0) for n in _SUPERFLEX_NAMES)
    if pos == "QB" and superflex:
        return False                       # superflex — a 2nd QB genuinely starts
    dedicated = c.get(pos, 0) + (superflex if pos == "QB" else 0)
    have = Counter(registry.meta(p).position for p in (my_pids or []))
    if have.get(pos, 0) < dedicated:
        return False                       # that starting slot is still open
    if pos == "TE":
        if c.get("TE", 0) == 0:
            return False                   # TE-only-via-flex league: flex logic owns it
        # a dedicated TE is filled — an extra TE still plays if a FLEX is open
        flex_slots = sum(c.get(n, 0) for n in _FLEX_NAMES)
        flex_used = sum(max(0, have.get(p, 0) - c.get(p, 0)) for p in ("RB", "WR"))
        if max(0, flex_slots - flex_used) > 0:
            return False
    return True


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


# ---- draft strategies: bias the recommendation engine by position × round ----
STRATEGIES = ["Balanced", "Hero RB", "Zero RB", "Robust RB", "Elite TE",
              "Late-Round QB", "Carries & Catches", "Value (BPA)"]
STRATEGY_HELP = {
    "Balanced": "No positional bias — value, roster fit, scarcity & survival.",
    "Hero RB": "Lock one elite RB early, then load WR/TE and wait on RB2.",
    "Zero RB": "Fade RB early for elite WR/TE, then hammer RB value in the mid rounds.",
    "Robust RB": "Pound RB early — aim for ~3 of your first 4–5 picks at RB.",
    "Elite TE": "Land a top-tier TE early for a weekly positional edge.",
    "Late-Round QB": "Wait on QB; spend early picks on RB/WR, grab your QB late.",
    "Carries & Catches": ("For leagues that score volume — 1 pt per carry, 2 per "
                          "catch. Hammers RB, treats the top ~24 RBs as one tier, "
                          "and refuses to pay up at QB."),
    "Value (BPA)": "Best player available — rank purely by value, ignore roster needs.",
}
_SUPERFLEX_SLOTS = {"SUPER_FLEX", "SUPERFLEX", "SFLEX", "OP", "Q/W/R/T"}


def _is_superflex(roster_slots) -> bool:
    return any(str(s).upper() in _SUPERFLEX_SLOTS for s in (roster_slots or []))


def strategy_weight(strategy, pos, round_no, my_pids, registry, roster_slots) -> float:
    """Multiplier on a candidate's score implementing a draft strategy's positional
    lean, given the round and your current roster. >1 leans toward the position, <1
    away; 1.0 is neutral. Multiplicative (not additive) so it scales with value and
    actually reorders elite players. 'Balanced'/'Value (BPA)' are neutral here (BPA is
    handled by the caller as pure value)."""
    if not strategy or strategy in ("Balanced", "Value (BPA)"):
        return 1.0
    cnt = {}
    for p in (my_pids or []):
        try:
            pp = registry.meta(p).position
        except Exception:  # noqa: BLE001
            continue
        cnt[pp] = cnt.get(pp, 0) + 1
    rb, te, qb = cnt.get("RB", 0), cnt.get("TE", 0), cnt.get("QB", 0)
    rd = round_no or 1
    if strategy == "Hero RB":
        if pos == "RB":
            return 1.15 if (rb == 0 and rd <= 2) else (0.55 if (rb >= 1 and rd <= 6) else 1.0)
        if pos in ("WR", "TE") and rd <= 5:
            return 1.12
    elif strategy == "Zero RB":
        if pos == "RB":
            return 0.45 if rd <= 4 else (1.10 if rd <= 7 else 1.25)
        if pos == "WR" and rd <= 6:
            return 1.18
        if pos == "TE" and rd <= 6:
            return 1.10
        if pos == "QB" and rd <= 6:
            return 1.05
    elif strategy == "Robust RB":
        if pos == "RB" and rd <= 5 and rb < 3:
            return 1.25
        if pos in ("WR", "TE", "QB") and rd <= 3 and rb < 2:
            return 0.82                     # steer the early picks toward RB
    elif strategy == "Elite TE":
        if pos == "TE" and te == 0 and rd <= 4:
            return 1.85
        if pos == "RB" and rd <= 2 and te == 0:
            return 0.85                     # make room for the elite TE in the first picks
    elif strategy == "Carries & Catches":
        # Measured on "Show us your TD's" (ESPN 798873), 36 team-seasons 2023-25,
        # a league scoring 1 point per rush attempt and 2 per reception. This rests
        # ONLY on actual season points and team points-for — no draft ranks. ESPN's
        # draftRanksByRankType for past seasons turned out not to be that season's
        # preseason board (the 2023 file returns 2024's ranks; the 2024 file has
        # Kamara 2nd and Kyren Williams 3rd, which no preseason board ever said),
        # so every rank-derived claim was dropped rather than encoded here.
        #
        #   drafted starters -> season points     r = +0.72 overall
        #      RB +0.47   FLEX +0.42   WR +0.36   TE +0.21   QB +0.06
        #
        # Points spread among drafted players, pooled and rank-free:
        #      RB 1047 best / 602 worst-you-must-roster   swing 445
        #      WR  736      / 402                         swing 334
        # RB is both the highest ceiling and the widest swing, which is what 1
        # point per carry does to a league.
        if pos == "RB":
            return 1.30 if rb < 3 else (1.10 if rb < 4 else 0.85)
        # QB scores heavily here but every team gets one — 24 drafted for 12
        # starting spots — so it is points nobody gains on. r = +0.06 is the whole
        # argument for spending the pick elsewhere.
        if pos == "QB":
            return 0.45 if (qb == 0 and rd <= 6) else (1.15 if qb == 0 else 0.35)
        # TE r = +0.21: one real tight end is worth having, the second is a
        # formality in a league that forces you to roster two.
        if pos == "TE":
            return 1.15 if (te == 0 and 3 <= rd <= 8) else (0.60 if te >= 1 else 1.0)
        if pos == "WR":
            return 0.88 if rd <= 3 else 1.0
    elif strategy == "Late-Round QB":
        if _is_superflex(roster_slots):
            return 1.0                      # QB is premium in superflex — don't fade
        if pos == "QB":
            return 0.40 if (qb == 0 and rd < 8) else (1.15 if rd >= 9 else 1.0)
    return 1.0


def best_pick(board_avail, model: "ValueModel", registry, needs, taken,
              next_pick=None, survival_fn=None, my_pids=None, roster_slots=None,
              strategy=None, round_no=None, byes=None, juice_map=None,
              board_edge_weight=BOARD_EDGE_WEIGHT, adp_rank_fn=None):
    """The single ★ recommendation. Returns (row, score, reason) or (None, 0, '').

    This DELEGATES to ``top_suggestions`` and takes its #1 rather than scoring
    independently. It used to carry its own near-copy of that scoring, which
    silently drifted: it capped the search at the top 60 rows, never got the
    needs-bump double-count fix, and never learned about Juice's Value or bye
    clashes — so the ★ banner could confidently name a different player than the
    #1 row rendered directly beneath it. One scorer, one answer."""
    sugg = top_suggestions(board_avail, model, registry, needs, taken,
                           next_pick=next_pick, survival_fn=survival_fn,
                           my_pids=my_pids, roster_slots=roster_slots, byes=byes,
                           k=1, strategy=strategy, round_no=round_no,
                           juice_map=juice_map, board_edge_weight=board_edge_weight,
                           adp_rank_fn=adp_rank_fn)
    if not sugg:
        return (None, 0, "")
    s = sugg[0]
    pm, mult, raw = s["pm"], s["mult"], s["raw"]
    # {:+} rather than a literal "+": raw VORP is routinely NEGATIVE in a rookie
    # draft, where every pick sits below the veteran replacement level, and the
    # hardcoded sign rendered that as "+-32 value".
    reasons = [f"{raw:+.0f} value"]
    if mult >= 0.999:
        reasons.append(f"fills {pm.position} starter")
    elif mult >= 0.55:
        reasons.append(f"{pm.position} depth")
    else:
        reasons.append(f"{pm.position} bench — already set")
    if mult >= 0.6 and s.get("left") is not None and s["left"] <= 3:
        reasons.append(f'{s["left"]} startable {pm.position}s left')
    if s.get("sv") is not None and s["sv"] <= 35:
        reasons.append("unlikely to return")
    if s.get("stack"):
        reasons.append("stacks with your QB")
    if strategy and strategy not in ("Balanced", "Value (BPA)"):
        reasons.insert(0, strategy)
    return (s["row"], s["score"], " · ".join(reasons[:3]))


def bye_clash(pm, my_pids, registry, byes) -> bool:
    """True if this player shares a bye week with a starter you already roster at
    the same position (a lineup hole on that week)."""
    if not byes or not my_pids:
        return False
    b = byes.get(getattr(pm, "team", ""))
    if not b:
        return False
    for p in my_pids:
        mp = registry.meta(p)
        if mp.position == pm.position and byes.get(mp.team) == b:
            return True
    return False


def upside_score(model: "ValueModel", registry, pid) -> float:
    """An 'upside' re-weighting of VORP for Upside Mode: favour rookies and young,
    ascending players (high ceiling) and fade aging vets (capped floor). Falls back
    to raw VORP when age/experience is unknown."""
    base = model.vorp_of(pid) or 0.0
    pm = registry.meta(pid)
    age = getattr(pm, "age", None)
    yexp = getattr(pm, "years_exp", None)
    bonus = 0.0
    if yexp == 0:
        bonus += 16                         # rookie — pure ceiling
    elif yexp is not None and yexp <= 2:
        bonus += 9                          # ascending second/third year
    if age is not None:
        if age <= 23:
            bonus += 9
        elif age <= 25:
            bonus += 4
        elif age >= 30:
            bonus -= 9
        elif age >= 28:
            bonus -= 4
    return base + bonus


JUICE_SKEW_WEIGHT = 9.0  # points of score nudge per full unit of Juice's Value skew
# Your own board (UDK) reaches the scorer two ways, deliberately NOT as raw rank.
# Blending rank into the score would mostly double-count: UDK's order is itself
# largely projection-derived, i.e. the same input VORP already uses, so it drags
# Suggestions toward Rankings and costs you the second opinion that makes the
# panel worth having. What it adds instead is information VORP structurally
# cannot hold:
#   TIER_CLIFF_BONUS - VORP sees a smooth points gradient; a published tier says
#     "these are interchangeable, and there is a drop after them". Being the last
#     man before that drop is worth more than his VORP implies.
#   BOARD_EDGE_WEIGHT - a DELTA, not a level: how far your board disagrees with
#     the market, per 10 spots. Defaults to 0 so it changes nothing until asked.


def tier_cliff_bonus(row, board_avail, registry) -> float:
    """Extra value for the last players in a positional tier.

    Scaled by how thin the tier is: the sole survivor of a tier gets the full
    bonus, four-left gets a quarter of it. Uses the board's own `pos_tier` (UDK
    publishes per-position tiers), so this is your ranking source's structure —
    not something re-derived from ADP gaps."""
    pos = registry.meta(str(row["pid"])).position
    tier = row.get("pos_tier") or row.get("tier")
    if tier is None or not pos:
        return 0.0
    same = sum(1 for r in board_avail
               if (r.get("pos_tier") or r.get("tier")) == tier
               and registry.meta(str(r["pid"])).position == pos)
    if same <= 0 or same > 4:
        return 0.0
    return TIER_CLIFF_BONUS * (1.0 / same)


def top_suggestions(board_avail, model: "ValueModel", registry, needs, taken, *,
                    next_pick=None, survival_fn=None, my_pids=None, roster_slots=None,
                    byes=None, k=6, upside=False, strategy=None, round_no=None,
                    juice_map=None, board_edge_weight=BOARD_EDGE_WEIGHT,
                    adp_rank_fn=None):
    """A ranked list of the best picks right now — the engine behind the Suggestions
    tab. Roster-aware scoring like ``best_pick`` (value × roster fit + starter need +
    positional scarcity + 'won't survive to your next pick'), now also nudged by
    **stacks** (a pass-catcher with your QB, or vice-versa) and away from **bye-week
    clashes** with a starter you already own. ``juice_map`` (Juice's Value — Sleeper's
    in-draft-room rank vs FantasyPros ECR) nudges the score by a market-inefficiency
    signal independent of roster fit: positive skew means Sleeper ranks him later
    than the experts (he'll likely fall further than he should — a value bump);
    negative means Sleeper ranks him earlier (a reach if you chase him here). Applied
    after roster/strategy adjustments so it holds even under Value (BPA). Returns the
    top ``k`` with the raw signals so the UI can render reasons and a FIT %. Each item
    carries {row, pm, score, raw, mult, sv, left, stack, bye_clash, skew, landmine}."""
    needs = needs or set()
    taken_s = {str(x) for x in (taken or [])}
    use_roster = my_pids is not None and roster_slots is not None
    out = []
    for r in board_avail:
        pid = str(r["pid"])
        pm = registry.meta(pid)
        mult = (roster_multiplier(pm.position, my_pids, roster_slots, registry)
                if use_roster else 1.0)
        raw = model.vorp_of(pid)
        base = upside_score(model, registry, pid) if upside else raw
        score = base * mult
        if mult >= 0.999:
            score += 22
        elif mult >= 0.55:
            score += 6
        # moderate need-nudge: a player at a position with an OPEN starting need
        # gets an extra bump so a real need (e.g. your first WR) surfaces in the
        # top few over a high-VORP backup that only fills the flex — without
        # burying a genuinely elite value at a filled spot. Skip when mult>=0.999
        # already applied the +22 starter-fill bonus above for this same signal —
        # stacking both let an empty single-slot spot (QB/TE) swamp every other
        # position's suggestions regardless of raw value (e.g. a bench-caliber TE
        # outscoring a true difference-maker WR).
        if pm.position in needs and mult < 0.999:
            score += 10
        left = model.startable_left(pm.position, taken_s)
        sv = survival_fn(pid) if (survival_fn and next_pick) else None
        if mult >= 0.6:
            # Scarcity urgency peaks at 1 startable left ("last one — take him"),
            # NOT at zero. `left <= 3` handed the LARGEST bonus (+32) to a position
            # with nothing startable remaining, where every option is by definition
            # below replacement — which is how sub-replacement players floated to
            # the top of the late rounds.
            if 1 <= left <= 3:
                score += (4 - left) * 8
            if sv is not None and sv <= 35:
                score += (35 - sv) * 0.5
        stacks = synergy(pm, my_pids, registry) if my_pids else []
        is_stack = any(t[0] == "Stack" for t in stacks)
        if is_stack:
            score += 7
        clash = bye_clash(pm, my_pids, registry, byes)
        if clash and mult < 0.999:        # don't punish a true starter need over a bye
            score -= 9
        if strategy == "Value (BPA)":
            score = base                  # pure value, ignore roster construction nudges
        elif strategy and strategy != "Balanced":
            score *= strategy_weight(strategy, pm.position, round_no, my_pids,
                                     registry, roster_slots)
        j = (juice_map or {}).get(pid)
        skew = j.get("skew") if j else None
        landmine = j.get("landmine") if j else None
        if skew is not None:
            score += skew * JUICE_SKEW_WEIGHT
        # --- YOUR board, as structure and disagreement rather than as rank ---
        cliff = tier_cliff_bonus(r, board_avail, registry)
        score += cliff
        # How far your board departs from the market, per 10 spots. Positive =
        # your board rates him ABOVE consensus ADP. The market rank has to come
        # from adp_rank_fn — a board row's own `adp` is UDK's round.pick figure
        # (1.01), not a consensus rank, so reading it off the row silently yields
        # nothing.
        edge = 0.0
        if board_edge_weight and r.get("rank") and adp_rank_fn:
            mkt = adp_rank_fn(pm.name, pm.position)
            if mkt:
                edge = (float(mkt) - float(r["rank"])) / 10.0 * board_edge_weight
                score += edge
        redundant = (redundant_single_slot(pm.position, my_pids, roster_slots, registry)
                     if use_roster else False)
        out.append({"row": r, "pm": pm, "score": round(score, 1), "raw": raw,
                    "mult": mult, "sv": sv, "left": left,
                    "stack": is_stack, "bye_clash": clash,
                    "skew": skew, "landmine": landmine, "redundant": redundant,
                    "unprojected": not model.is_projected(pid),
                    "cliff": round(cliff, 1), "board_edge": round(edge, 1),
                    "board_rank": r.get("rank")})
    # Rank in tiers, not on score alone:
    #   1. can he reach your lineup at all?  (redundant_single_slot)
    #   2. do we actually have a projection?  (is_projected — an unprojected
    #      player's neutral 0.0 otherwise beats a real player at -10)
    #   3. then score.
    # Sorted rather than dropped so they still appear when nothing better is left,
    # and so the position pills can still surface them deliberately.
    #   4. within a point of each other the score is not really distinguishing
    #      them, so defer to YOUR board rather than to float noise.
    out.sort(key=lambda x: (x["redundant"], x["unprojected"], -round(x["score"]),
                            x["board_rank"] if x["board_rank"] is not None else 9999))
    return out[:k]


# ----------------------------------------------------------- room / opponent read
_ARCH_BIAS = {
    "Early-QB": {"QB"}, "Premium-TE": {"TE"}, "Zero-RB": {"WR"},
    "RB-heavy": {"RB"}, "WR-heavy": {"WR"}, "Balanced": set(), "Unknown": set(),
}


def position_pressure(position, upcoming_slots, need_map, profiles, owner_by_slot,
                      *, round_no=None):
    """How many managers picking before your next turn are likely to grab
    ``position`` — a manager counts if he *needs* it, and is flagged 'biased' if his
    archetype or this-round history leans that way. Returns (needy, biased, n_unique)."""
    from . import draft_history as DH
    unique = list(dict.fromkeys(upcoming_slots))
    needy = biased = 0
    for s in unique:
        oid = str(owner_by_slot.get(s, ""))
        if position not in need_map.get(s, ()):
            continue
        needy += 1
        arch = (profiles.get(oid) or {}).get("archetype", "")
        lean = position in _ARCH_BIAS.get(arch, set())
        if not lean and round_no:
            lean = position in DH.likely_positions(oid, round_no, profiles)
        if lean:
            biased += 1
    return needy, biased, len(unique)


def room_note(pm, upcoming_slots, need_map, profiles, owner_by_slot, model, taken, *,
              round_no=None, survival=None):
    """A 'beat the room' read for one player. The player's own survival % (his ADP
    vs your next pick) is the primary driver — it's *his* chance of returning — and
    the room context (who picks before you + their needs/archetypes vs startable
    players left) refines it. Returns (label, css_class, detail)."""
    pos = pm.position
    taken_s = {str(x) for x in (taken or [])}
    needy, biased, n = position_pressure(pos, upcoming_slots, need_map, profiles,
                                         owner_by_slot, round_no=round_no)
    left = model.startable_left(pos, taken_s)
    who = f"{needy} of {n} managers before you need {pos}"
    if biased:
        who += f" ({biased} lean {pos})"
    sv = f"~{int(survival)}% to return" if survival is not None else None
    room_chasing = needy >= max(2, left) and (biased or left <= needy)

    # 1) He himself is unlikely to make it back → grab, regardless of the position.
    if survival is not None and survival <= 45:
        d = f"only {sv} to your next pick" + (f"; {who}" if room_chasing else "") + "."
        return ("GRAB — won't make it back", "grab", d)
    # 2) The room is clearly running his position.
    if room_chasing:
        d = f"{who}; only {left} startable left" + (f"; {sv}" if sv else "") + "."
        return ("GRAB — room is chasing", "grab", d)
    # 3) High personal survival AND the room isn't chasing the spot → wait.
    if (survival is None or survival >= 60) and (needy == 0 or left > needy + 1):
        base = (f"{sv}" if sv else f"{who}; {left} startable left")
        return ("SAFE TO WAIT", "wait", f"{base} — he should come back.")
    # 4) Anything in between is a judgement call.
    d = (f"{sv}; {who}" if sv else f"{who}; {left} startable left") + "."
    return ("LEAN GRAB", "lean", d)


def draft_plan(my_pids, roster_slots, n_picks, board_avail, model: "ValueModel",
               registry, *, taken=None) -> list:
    """Greedy roster-construction path for your next ``n_picks``: at each step take
    the position whose best-available player gives the most roster-adjusted value
    (so it fills starters first, then flex/depth, and avoids over-loading a spot).
    Returns [{pos, name, mult}, ...]."""
    sim_pids = list(my_pids or [])
    sim_taken = {str(x) for x in (taken or [])}
    plan = []
    for _ in range(max(0, n_picks)):
        best = None
        for pos in ("RB", "WR", "TE", "QB"):
            mult = roster_multiplier(pos, sim_pids, roster_slots, registry)
            cand = next((r for r in board_avail
                         if str(r["pid"]) not in sim_taken
                         and registry.meta(r["pid"]).position == pos), None)
            if not cand:
                continue
            score = model.vorp_of(cand["pid"]) * mult
            if best is None or score > best[0]:
                best = (score, pos, cand, mult)
        if not best:
            break
        _, pos, cand, mult = best
        plan.append({"pos": pos, "name": cand["name"], "mult": round(mult, 2)})
        sim_pids.append(str(cand["pid"]))
        sim_taken.add(str(cand["pid"]))
    return plan


def grade_team(my_pids, model: "ValueModel", registry, roster_slots, n_teams) -> dict:
    """Letter-grade a finished roster by its starters' value vs a league-average
    team, and surface the best-value pick and biggest reach. Returns a dict for the
    recap UI."""
    starters = team_demand(roster_slots)
    by_pos = {}
    for p in (my_pids or []):
        by_pos.setdefault(registry.meta(p).position, []).append(p)
    # starter VORP total: best N at each position by starter demand (+ one flex)
    total = 0.0
    for pos, dem in starters.items():
        vals = sorted((model.vorp_of(p) for p in by_pos.get(pos, [])), reverse=True)
        total += sum(vals[:max(1, round(dem))])
    # crude league baseline: an average team gets ~ the median starter value
    avg = sum(model.replacement_pts.values()) * 0.0  # baseline 0 (VORP already vs repl)
    # grade by total VORP per starting slot
    n_start = max(1, round(sum(starters.values())))
    per = total / n_start
    grade = ("A+" if per >= 55 else "A" if per >= 42 else "B+" if per >= 32 else
             "B" if per >= 22 else "C+" if per >= 14 else "C" if per >= 7 else "D")
    ranked = sorted(((model.rank_of(p) or 999, p) for p in (my_pids or [])))
    best = ranked[0][1] if ranked else None
    return {"grade": grade, "starter_vorp": round(total), "best_pick": best}


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
