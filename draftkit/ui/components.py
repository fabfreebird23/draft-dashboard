"""FantasyPros-style (and better) draft surfaces — platform-agnostic HTML builders.

They take a PlayerRegistry, the league's roster slots, and an adp_rank lookup, so
the same render serves Sleeper or ESPN. Adds positional ranks, ADP value/reach
chips, bye weeks, a readable color-coded draft board, and a roster-needs strip.
"""
from __future__ import annotations

import functools
import math
from typing import Callable, List

from .. import theme


def board_pos_rank(board, registry) -> dict:
    """{pid: 'RB18'} computed from a board's OWN overall order, so a player's
    positional rank always rises with its overall rank. Without this, the displayed
    RB## (consensus-ADP order) can contradict the #overall (UDK-Top-200 order) and a
    higher-ranked player shows a worse positional rank than a lower one."""
    counts, out = {}, {}
    for r in sorted([x for x in (board or []) if x.get("pid")],
                    key=lambda x: x.get("rank") or 9999):
        try:
            pos = registry.meta(r["pid"]).position
        except Exception:  # noqa: BLE001
            continue
        if pos not in ("QB", "RB", "WR", "TE"):
            continue
        counts[pos] = counts.get(pos, 0) + 1
        out[str(r["pid"])] = f"{pos}{counts[pos]}"
    return out


def _phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


@functools.lru_cache(maxsize=256)
def _sigma_for_horizon(h):
    """The spread of the room's deviation from board order, SOLVED from the
    conservation identity rather than picked by hand.

    Over a horizon of h picks, sum(1 - survival) across the board must equal h —
    h picks remove h players, exactly. With the mean pinned at `current + rank`,
    that sum has a closed form, T*Phi(T/s) + s*phi(T/s) with T = h - 0.5, which is
    strictly increasing in s. So exactly one sigma satisfies the identity and
    there is no free parameter left to tune. Bisection converges in ~40 steps.

    The old hand-set `max(4, 0.16 * depth)` scaled with draft DEPTH, which is the
    wrong variable — it overshot the identity by 28% at round 10 and by 177% at a
    back-to-back turn. Spread should track how far ahead you're looking, not how
    deep the draft is."""
    t = h - 0.5
    lo, hi = 1e-3, 5.0 * h + 10.0

    def f(s):
        return t * _phi(t / s) + s * math.exp(-0.5 * (t / s) ** 2) / math.sqrt(2 * math.pi)
    for _ in range(40):
        mid = (lo + hi) / 2
        if f(mid) < h:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def survival_pct(adp, next_pick, current_pick=None, avail_rank=None):
    """Probability (0-100) a player is still available at your next pick.

    `avail_rank` (1-based position in ADP order among UNDRAFTED players) is the
    accurate anchor and should be supplied wherever the board is known — see
    `board_survival_fn`. Market ADP is an *absolute* pick number, and it is only
    a valid anchor in a draft whose board tracks that number. Ours doesn't: with
    38 keepers locked, the best available player at pick 26 has ADP 46, so the
    room is running ~20 picks ahead of the market and every ADP-anchored estimate
    reads a player as "not due for a while" when he is in fact next off the board.

    The conservation identity makes the error exact and unarguable: the H picks
    between now and your next turn remove exactly H players from the board, so
    sum(1 - survival) over the available pool MUST equal H. Measured on the real
    pool at pick 26 with H=12, the ADP anchor accounted for 1.02 of those 12
    picks — 12x too optimistic, which is why the whole column read 83-100%.
    Ranking against the board instead gives 13.05, and reduces to the identical
    ADP answer in a plain redraft where board and market agree.

    The `adp`/`current_pick` path below is the fallback for callers with no board
    (e.g. a standalone player card) and keeps the older conditioning fix.

    Probability (0-100) a player with this ADP is still available at your next
    pick — models draft position as Normal(adp, sigma) with sigma growing for
    later ADPs.

    Conditioned on him being available RIGHT NOW when `current_pick` is given:
    P(survives to next | survived to now) = P(X > next) / P(X > now). Without
    that conditioning a player who has fallen well past his ADP reads 0% — the
    model keeps insisting he's already gone while he's sitting on the board in
    front of you — which then hands him the maximum 'unlikely to return' urgency
    bonus and a GRAB NOW verdict. The evidence that he lasted this long is
    exactly what should raise his odds of lasting a bit longer."""
    if not next_pick:
        return None
    if avail_rank and current_pick:
        # He is taken at pick `current_pick + avail_rank` if the room drafts the
        # board in order; sigma carries the room's deviation from that order, and
        # is solved rather than guessed (see _sigma_for_horizon).
        # Survives iff he lasts past every pick before yours, i.e. X > next - 0.5.
        h = int(next_pick) - int(current_pick) - 1
        if h <= 0:                      # you pick again immediately — nobody moves
            return 100
        mu = float(current_pick) + float(avail_rank)
        sigma = _sigma_for_horizon(h)
        p = 1 - _phi((float(next_pick) - 0.5 - mu) / sigma)
        return max(0, min(100, round(p * 100)))
    if not adp:
        return None
    # Measure from wherever the market actually has him NOW. A player still on the
    # board past his ADP has already falsified the original estimate, so anchoring
    # to the stale ADP is what produced the 0%. (A Normal's tail decays fast enough
    # that the textbook conditional P(X>next)/P(X>now) underflows to exactly 0 for
    # a top-5 ADP player who fell 35 picks — this is equivalent where the maths is
    # well behaved, and stays finite where it isn't.)
    eff = max(float(adp), float(current_pick)) if current_pick else float(adp)
    sigma = max(4.0, 0.16 * eff)
    p = 1 - _phi((float(next_pick) - eff) / sigma)
    return max(0, min(100, round(p * 100)))


def board_survival_fn(adp_pool, drafted, current_pick, next_pick):
    """pid -> survival %, anchored to the live board rather than to market ADP.

    Ranks the UNDRAFTED players in ADP order — that ordering is the room's own
    queue, so the j-th name on it is expected to go j picks from now. This is
    self-calibrating: keepers, positional runs and a reachy room all shift the
    board, and ranking against what's actually left absorbs the shift for free.

    Returns a callable so every row shares one pass over the pool. Falls back to
    the ADP anchor for a player the ADP pool doesn't rank (deep/unranked names),
    who by definition isn't near the top of the queue anyway."""
    ranks, j = {}, 0
    taken = {str(x) for x in (drafted or ())}
    for p in (adp_pool or ()):
        pid = str(p.get("pid") or "")
        if not pid or pid in taken:
            continue
        j += 1
        ranks[pid] = j

    def _fn(pid, adp=None):
        return survival_pct(adp, next_pick, current_pick,
                            avail_rank=ranks.get(str(pid)))
    _fn.ranks = ranks
    return _fn


def reach_note(adp, at_pick, n_teams, *, name=None, min_rounds=1.0, max_pick=None,
               survival=None, board_rank=None, next_pick=None, min_survival=75):
    """Warn that taking this player now spends a pick earlier than you need to.

    TWO paths, because raw market ADP is not a safe yardstick in this league.

    1. In a draft (`survival` + `next_pick` given) the question is decided by the
       board-calibrated survival model: your board wants him now (board_rank at or
       before the current pick) but he is very likely to still be there at your
       next turn. That is exactly a reach, and it is immune to the two biases that
       wreck the ADP comparison here:
         * 38 keepers are locked, so the board runs ~20 picks AHEAD of market ADP.
           Comparing ADP to the raw pick number flags nearly everyone at pick 26.
         * Our board ranks QBs on overall value while a 1-QB market pushes them
           down for replacement-level reasons. Measured on the real 305-row UDK
           board, a plain ADP-vs-rank rule flagged 17 of 19 draftable QBs (89%) —
           a positional-philosophy difference wearing a reach warning's clothes.
       Survival is board-relative, so both distortions cancel.

    2. Outside a draft there is no next pick to calibrate against, so fall back to
       the plain ADP-vs-board-rank reading (the FantasyPros-style static one).
       Same caveat applies, hence the deliberately blunt round threshold.
    """
    if survival is not None and next_pick and at_pick:
        # Only players your board would actually take around now — otherwise every
        # deep name on a 300-row board has ~100% survival and would light up.
        if board_rank and float(board_rank) > float(at_pick):
            return None
        if survival < min_survival:
            return None
        who = name or "This player"
        rnd = int((int(at_pick) - 1) // int(n_teams) + 1) if n_teams else None
        adp_s = f" Market ADP has him at {int(adp)}." if adp else ""
        return {
            "survival": survival, "at_round": rnd, "rounds": None,
            "tip": (f"Reach — {who} is ~{int(survival)}% to still be on the board at "
                    f"your next pick (#{int(next_pick)}), so a"
                    f"{' round-' + str(rnd) if rnd else ''} pick spent on him here is "
                    f"a pick you didn't have to spend.{adp_s} Take a need now and "
                    f"circle back."),
        }
    """Warn that spending pick `at_pick` on this player is earlier than the market
    makes you. Returns a dict of the details, or None when it isn't a reach.

    Measured in ROUNDS rather than raw picks, because raw picks don't mean the
    same thing twice: a 10-pick gap is a full round in a 10-team league but only
    two-thirds of one in a 16-teamer, and it costs you far less in round 12 than
    in round 2. Rounds normalise both.

    `at_pick` is the pick you would actually spend — the live pick when you're on
    the clock, otherwise the player's own board rank, which gives the static "if
    you took him where your board has him" reading.

    NB the ADP behind this is our CONSENSUS board (ESPN / FantasyPros /
    FootballGuys ...), not Sleeper's own draft-room order, so the wording says so
    rather than naming a platform we didn't measure."""
    if not adp or not at_pick or not n_teams:
        return None
    # Only warn about picks that exist. The Rankings list runs ~300 deep, so without
    # this every undraftable name whose ADP sits below his board rank lights up red
    # and the warning stops meaning anything.
    if max_pick and float(at_pick) > float(max_pick):
        return None
    gap = float(adp) - float(at_pick)
    if gap <= 0:                       # market has him going EARLIER — not a reach
        return None
    rounds = gap / float(n_teams)
    if rounds < min_rounds:
        return None

    def _rnd(p):
        return int((int(p) - 1) // int(n_teams) + 1)

    who = name or "This player"
    return {
        "rounds": rounds, "picks": int(gap),
        "at_round": _rnd(at_pick), "adp_round": _rnd(adp),
        "tip": (f"Reach — taking {who} here spends a round-{_rnd(at_pick)} pick, but "
                f"consensus ADP has him going around pick {int(adp)} "
                f"(round {_rnd(adp)}). That's ~{rounds:.1f} rounds early, so you "
                f"could likely address another need and still get him."),
    }


def survival_colors(pct):
    """(bg, fg) for a shaded availability box — a smooth red→amber→green gradient."""
    if pct is None:
        return None
    hue = int(max(0, min(100, pct)) * 1.2)   # 0=red … 120=green
    return (f"hsl({hue},70%,85%)", f"hsl({hue},60%,30%)")


def survival_box_html(pct):
    c = survival_colors(pct)
    if not c:
        return ""
    return f'<span class="svbox" style="background:{c[0]};color:{c[1]}">{pct}%</span>'


def predictor_html(predictions, slot_names, registry, n) -> str:
    """Pick Predictor — the most-likely upcoming picks before your next turn."""
    if not predictions:
        return ""
    rows = []
    for ov, slot, pid in predictions:
        pm = registry.meta(pid)
        rd, inrd = (ov - 1) // n + 1, (ov - 1) % n + 1
        nm = slot_names[slot] if slot < len(slot_names) else f"Team {slot + 1}"
        rows.append(
            f'<div class="pp-row pos-{pm.position}"><span class="pp-pk">{rd}.{inrd:02d}</span>'
            f'<span class="pp-tm">{nm[:13]}</span>'
            f'<span class="pp-arrow">→</span>'
            f'{theme.img_tag(pid, "pp-img")}'
            f'<span class="pp-pl">{pm.name}</span>'
            f'<span class="pp-pos pos-{pm.position}">{pm.position}</span></div>')
    return ('<div class="dr-predict"><div class="dr-h" style="margin-bottom:4px;">Pick '
            'Predictor — likely before you\'re up</div>' + "".join(rows) + "</div>")

_FLEX_OK = {"RB", "WR", "TE"}
_STARTABLE = {"QB", "RB", "WR", "TE", "K", "DST", "D"}

# Distinct, high-contrast tier colors (white text) so tier breaks pop.
_TIER_COLORS = ["#4338ca", "#1f6fd6", "#0e9488", "#1c8a4d", "#b3650a",
                "#c2410c", "#b3232a", "#7c3aed", "#0b7285", "#5f6b7a"]


def tier_color(tier) -> str:
    try:
        return _TIER_COLORS[(int(tier) - 1) % len(_TIER_COLORS)]
    except (TypeError, ValueError):
        return _TIER_COLORS[0]


def tier_band(label, tier, cls="ptier") -> str:
    """A slim, color-coded tier divider (tinted bg + colored text + left accent)."""
    c = tier_color(tier)
    return (f'<div class="{cls}" style="color:{c};border-left:3px solid {c};'
            f'background:{c}14">{label}</div>')


def snake(n: int) -> Callable[[int], int]:
    def slot(i: int) -> int:
        rd, j = divmod(i, n)
        return j if rd % 2 == 0 else n - 1 - j
    return slot


def short_name(name: str) -> str:
    """'Ja'Marr Chase' -> 'J. Chase' for tight board cells."""
    parts = (name or "").split()
    if len(parts) < 2:
        return name or ""
    return f"{parts[0][0]}. {' '.join(parts[1:])}"


def fill_lineup(pids: list, roster_slots: List[str], registry):
    """Greedily place players into starter slots; overflow to bench. Returns
    (slots, filled, bench) where filled[i] is the pid in slots[i] (or None)."""
    slots = roster_slots or ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]
    filled = [None] * len(slots)
    bench = []
    for pid in pids:
        pos = registry.meta(pid).position
        placed = False
        for i, s in enumerate(slots):
            if filled[i] is None and s == pos:
                filled[i] = pid
                placed = True
                break
        if not placed:
            for i, s in enumerate(slots):
                if filled[i] is None and s == "FLEX" and pos in _FLEX_OK:
                    filled[i] = pid
                    placed = True
                    break
        if not placed:
            bench.append(pid)
    return slots, filled, bench


def lineup_html(pids: list, roster_slots: List[str], registry, bench_cap: int = 8) -> str:
    """My-Team panel: fill starter slots (QB/RB/WR/TE/FLEX/…), overflow to bench."""
    slots, filled, bench = fill_lineup(pids, roster_slots, registry)
    rows = []
    for s, pid in zip(slots, filled):
        if pid:
            nm_html = f'<span class="nm">{registry.meta(pid).name}</span>'
            empty = ""
        else:
            nm_html = '<span class="nm"><span class="empty-pill">Empty</span></span>'
            empty = " empty"
        rows.append(f'<div class="slot{empty}"><span class="pos {s}">{s}</span>{nm_html}</div>')
    for pid in bench[:bench_cap]:
        rows.append(f'<div class="slot"><span class="pos BN">BN</span>'
                    f'<span class="nm">{registry.meta(pid).name}</span></div>')
    return '<div class="dr-lineup">' + "".join(rows) + "</div>"


def roster_needs_html(my_pids: list, roster_slots: List[str], registry) -> str:
    """A 'needs' strip: how many of each starting slot are still open."""
    need = {}
    for s in roster_slots:
        if s in _STARTABLE or s == "FLEX":
            need[s] = need.get(s, 0) + 1
    have = {}
    flex_pool = 0
    for pid in my_pids:
        pos = registry.meta(pid).position
        if pos in need and have.get(pos, 0) < need[pos]:
            have[pos] = have.get(pos, 0) + 1
        elif pos in _FLEX_OK:
            flex_pool += 1
    chips = []
    order = []
    for s in roster_slots:
        if s not in order and (s in _STARTABLE or s == "FLEX"):
            order.append(s)
    for s in order:
        total = need.get(s, 0)
        if s == "FLEX":
            got = min(flex_pool, total)
        else:
            got = have.get(s, 0)
        open_n = max(0, total - got)
        cls = "need open" if open_n else "need full"
        label = f"{s} {got}/{total}"
        chips.append(f'<span class="{cls}">{label}</span>')
    return '<div class="dr-needs">' + "".join(chips) + "</div>"


def roster_balance_html(my_pids: list, roster_slots: List[str], registry) -> str:
    """A one-glance read on YOUR roster construction — balanced vs lopsided, plus
    the position counts — like Draft Sharks' balance indicator."""
    if not my_pids:
        return ""
    from collections import Counter
    have = Counter(registry.meta(p).position for p in my_pids)
    rb, wr, qb, te = (have.get("RB", 0), have.get("WR", 0),
                      have.get("QB", 0), have.get("TE", 0))
    needs = open_needs(my_pids, roster_slots, registry)
    n = len(my_pids)
    diff = rb - wr
    label, cls = "Balanced build", "bal-ok"
    if "QB" in needs and qb == 0 and n >= 4:
        label, cls = "Still no QB", "bal-warn"
    elif "TE" in needs and te == 0 and n >= 5:
        label, cls = "Still no TE", "bal-warn"
    elif diff >= 3:
        label, cls = "RB-heavy", "bal-warn"
    elif diff <= -3:
        label, cls = "WR-heavy", "bal-warn"
    elif rb <= 1 and n >= 6:
        label, cls = "Thin at RB", "bal-warn"
    elif wr <= 1 and n >= 6:
        label, cls = "Thin at WR", "bal-warn"
    icon = "✓" if cls == "bal-ok" else "⚠"
    detail = " · ".join(f"{p} {have.get(p, 0)}" for p in ("QB", "RB", "WR", "TE")
                        if have.get(p, 0) or p in ("RB", "WR"))
    return (f'<div class="dr-balance"><span class="bal-chip {cls}">{icon} {label}</span>'
            f'<span class="bal-detail">{detail}</span></div>')


def status_html(pick_no: int, n: int, on_clock_name: str, is_yours: bool,
                picks_until_me: int | None = None) -> str:
    rd = (pick_no - 1) // n + 1
    inrd = (pick_no - 1) % n + 1
    clk = ('<span class="yours">YOUR PICK</span>' if is_yours
           else f'<span class="clk">On the clock: <b>{on_clock_name}</b></span>')
    until = ""
    if not is_yours and picks_until_me is not None and picks_until_me > 0:
        until = f'<span class="clk"><b>{picks_until_me}</b> until you</span>'
    return (f'<div class="dr-status"><span class="rd">{pick_no}'
            f'<small>OVERALL</small></span>'
            f'<span class="clk">Round <b>{rd}</b> · Pick <b>{rd}.{inrd:02d}</b></span>'
            f'{clk}{until}</div>')


def _value_chip(adp: float | None, current_pick: int | None) -> str:
    """Compare a player's ADP to the current overall pick → value/reach chip."""
    if not adp or not current_pick:
        return ""
    diff = adp - current_pick     # positive = falling past ADP = value
    if diff >= 8:
        return f'<span class="vchip value">▼ +{int(diff)}</span>'
    if diff <= -8:
        return f'<span class="vchip reach">▲ {int(diff)}</span>'
    return ""


def _tooltip(pm, pos_rank, adp, tier) -> str:
    from . import playercard as PC  # local to avoid import-order coupling
    return PC.tooltip_text(pm, pos_rank=pos_rank, adp=adp, tier=tier)


def avail_html(rows, drafted, registry, adp_rank: Callable, *, pos_rank=None,
               current_pick=None, next_pick=None, limit=140, recommend=True,
               strike_taken=False) -> str:
    """Tiered best-available board: positional rank, ADP, value/reach chips, and a
    survival % (chance the player lasts to your next pick). When `strike_taken`,
    drafted players stay in their tier struck-through instead of being removed."""
    pos_rank = pos_rank or {}
    drafted = {str(x) for x in (drafted or set())}
    body, shown, last_tier, first = [], 0, None, True
    for r in rows:
        if shown >= limit:
            break
        if not r.get("pid"):
            continue
        is_taken = str(r["pid"]) in drafted
        if is_taken and not strike_taken:
            continue
        shown += 1
        if r["tier"] != last_tier:
            c = tier_color(r["tier"])
            body.append(f'<tr class="tierband" style="background:{c}"><td colspan="4" '
                        f'style="color:#fff">TIER {r["tier"]}</td></tr>')
            last_tier = r["tier"]
        pm = registry.meta(r["pid"])
        if is_taken:
            body.append(
                f'<tr class="drafted"><td class="r">{r["rank"]}</td>'
                f'<td>{theme.img_tag(r["pid"])}<b>{r["name"]}</b>'
                f'<span class="drafted-tag">DRAFTED</span>'
                f'<div class="pp">{pm.position} · {pm.team}</div></td>'
                f'<td class="a">—</td><td class="sv"></td></tr>')
            continue
        rec = ' class="rec"' if (recommend and first) else ""
        badge = '<span class="recbadge">★ PICK</span>' if (recommend and first) else ""
        first = False
        adp = adp_rank(pm.name, pm.position)
        adp_disp = int(adp) if adp else "—"
        pr = pos_rank.get(str(r["pid"]), "")
        pr_html = f'<span class="posrank {pm.position}">{pr}</span>' if pr else ""
        vchip = _value_chip(adp, current_pick)
        sv = survival_pct(adp, next_pick, current_pick) if next_pick else None
        sv_td = f'<td class="sv">{survival_box_html(sv)}</td>'
        body.append(
            f'<tr{rec}><td class="r">{r["rank"]}</td>'
            f'<td>{theme.img_tag(r["pid"])}{pr_html}<b>{r["name"]}</b>{badge}{vchip}'
            f'<div class="pp">{pm.position} · {pm.team}</div></td>'
            f'<td class="a">ADP<br>{adp_disp}</td>{sv_td}</tr>'
        )
    return ('<div class="neonwrap" style="max-height:620px;overflow:auto;">'
            '<table class="dr-avail"><tbody>' + "".join(body) + '</tbody></table></div>')


def grid_html(pick_pids, n, slot_names, my_slot, current_pick, rounds, registry,
              kept_overalls=None, owner_fn=None, window_rounds=None) -> str:
    """Readable color-coded draft board: rounds × teams, snake order, names shown.

    `pick_pids` maps overall pick number -> sleeper pid (or None).
    `kept_overalls` is a set of overall picks that are keepers (badged 'K').
    `owner_fn(overall)` -> slot of the pick's real owner (handles traded picks); when
    given, your cells are highlighted by ownership rather than by column.
    `window_rounds`, if given, renders only that many rounds centered on the
    current pick's round (clamped to the board), so the board stays short and
    scrolls forward with the draft instead of showing every round at once."""
    kept_overalls = kept_overalls or set()
    cw = "minmax(0,1fr)"          # fill the container so the whole board fits
    cur_round = max(1, min(rounds, (current_pick - 1) // n + 1)) if current_pick else 1
    if window_rounds and window_rounds < rounds:
        half = window_rounds // 2
        r_lo = max(1, cur_round - half)
        r_hi = min(rounds, r_lo + window_rounds - 1)
        r_lo = max(1, r_hi - window_rounds + 1)      # re-clamp near the end
    else:
        r_lo, r_hi = 1, rounds
    head = ['<div class="dr-colhead rd">RD</div>']
    for c, s in enumerate(slot_names):
        me = " me" if c == my_slot else ""
        head.append(f'<div class="dr-colhead{me}" title="{s}">{s[:13]}</div>')
    cells = ["".join(head)]
    for r in range(r_lo, r_hi + 1):
        # snake direction: odd rounds run left→right, even rounds right→left.
        arrow = "→" if r % 2 == 1 else "←"
        cells.append(f'<div class="dr-rdlabel">{r}'
                     f'<span class="dr-snk">{arrow}</span></div>')
        for c in range(1, n + 1):
            overall = (r - 1) * n + (c if r % 2 == 1 else n - c + 1)
            # label by the pick's real position in the round (snake order), not the
            # physical column — in even rounds the order reverses, so column 10 of a
            # 10-team round 2 is pick 2.01, not 2.10.
            pk = f'{r}.{(overall - 1) % n + 1:02d}'
            pid = pick_pids.get(overall)
            klass = "dr-cell"
            actual = owner_fn(overall) if owner_fn else (c - 1)
            owned = actual == my_slot
            if owned:
                klass += " me"
            # traded pick: this cell sits in its ORIGINAL owner's column (c-1) but is
            # now owned by a different team — flag it and name the new owner.
            trade_badge = ""
            if owner_fn is not None and actual != (c - 1):
                klass += " traded"
                onm = slot_names[actual] if actual < len(slot_names) else f"T{actual + 1}"
                short = (onm.split()[0] if onm.split() else onm)[:8]
                trade_badge = f'<span class="dr-trade" title="Traded to {onm}">⇄{short}</span>'
            is_now = overall == current_pick
            # a stable id on whichever cell is the current pick, so a tiny script
            # (see current_pick_scroll_html) can find and scroll to it after every
            # draft action — the board can be freely scrolled by hand in between.
            now_id = ' id="dr-current-pick"' if is_now else ""
            if is_now:
                klass += " now"
            if pid:
                pm = registry.meta(pid)
                klass += f" pos-{pm.position or 'NA'}"
                kept = overall in kept_overalls
                if kept:
                    klass += " kept"
                first, _, last = pm.name.partition(" ")
                tag = ' <span class="ktag">K</span>' if kept else ""
                if getattr(pm, "years_exp", None) == 0:
                    tag += ' <span class="rtag">R</span>'
                img = (f'<img class="c-img" loading="lazy" alt="" '
                       f'src="{theme.headshot_src(pid)}">')
                cells.append(
                    f'<div class="{klass}"{now_id}><span class="pk">{pk}</span>'
                    f'<div class="c-name"><span>{first}</span>'
                    f'<span>{last or "&nbsp;"}</span></div>{img}'
                    f'<span class="c-meta">{pm.position}-{pm.team}{tag}</span>{trade_badge}</div>')
            elif is_now:
                # on-the-clock card — solid blue with a prominent pick number
                cells.append(f'<div class="{klass} onclk"{now_id}><span class="oc-arrow">‹</span>'
                             f'<span class="oc-pk">{pk}</span>{trade_badge}</div>')
            else:
                cells.append(f'<div class="{klass} empty"><span class="pk">{pk}</span>'
                             f'{trade_badge}</div>')
    # roomy leagues (≤8 teams) keep the player headshots; larger boards go text-only
    grid_cls = "dr-grid wide" if n <= 8 else "dr-grid"
    grid = (f'<div class="{grid_cls}" style="grid-template-columns:30px repeat({n},{cw});">'
            + "".join(cells) + "</div>")
    return '<div class="neonwrap dr-board-scroll">' + grid + "</div>"


def turn_alert_html(is_my_turn: bool, picks_until: int = 0) -> str:
    """Tell him it's his pick even when this tab is in the background.

    Every existing turn cue is in-page — the YOUR PICK badge and the pulsing board
    cell — so all of them are invisible in the one scenario this app is built for:
    a second screen sitting behind the Sleeper draft room. This rewrites the parent
    page's <title> (which the browser shows on the tab strip whether or not the tab
    is visible) and chimes once on the TRANSITION into your turn, not on every
    rerun. Same components.v1.html iframe route as current_pick_scroll_html — a
    <script> injected through st.markdown never executes.

    The chime uses a WebAudio oscillator rather than an asset, so there's nothing
    to ship and nothing to 404; browsers gate audio behind a prior user gesture,
    which drafting has obviously already provided."""
    import json as _json
    base = "Draft Room"
    if is_my_turn:
        title = "⏰ YOUR PICK — " + base
    elif picks_until:
        title = f"{picks_until} until your pick — {base}"
    else:
        title = base
    return (
        "<script>try{var w=window.parent,d=w.document;"
        f"d.title={_json.dumps(title)};"
        f"var mine={'true' if is_my_turn else 'false'};"
        "if(mine&&!w.__drTurn){w.__drTurn=1;try{"
        "var C=w.AudioContext||w.webkitAudioContext;var c=new C();"
        "var o=c.createOscillator(),g=c.createGain();o.connect(g);g.connect(c.destination);"
        "o.frequency.value=880;g.gain.setValueAtTime(0.0001,c.currentTime);"
        "g.gain.exponentialRampToValueAtTime(0.25,c.currentTime+0.02);"
        "g.gain.exponentialRampToValueAtTime(0.0001,c.currentTime+0.45);"
        "o.start();o.stop(c.currentTime+0.5);}catch(e){}}"
        "if(!mine){w.__drTurn=0;}"
        "}catch(e){}</script>"
    )


def current_pick_scroll_html() -> str:
    """A near-invisible snippet for st.components.v1.html: components render as a
    real <iframe>, so unlike st.markdown its <script> actually executes (a script
    inserted via unsafe_allow_html's innerHTML-style injection never runs — the
    iframe route is the only way to run JS after a rerun). It reaches into the
    PARENT page (same-origin, so window.parent.document works) and scrolls the
    #dr-current-pick cell (tagged in grid_html) into view — every draft action
    triggers a full script rerun, so this fires fresh each time and 'snaps back'
    to the current pick, while manual scrolling in between is untouched."""
    return (
        "<script>try{var d=window.parent.document;"
        "var el=d.getElementById('dr-current-pick');"
        "if(el)el.scrollIntoView({block:'center',inline:'center',behavior:'auto'});"
        "}catch(e){}</script>"
    )


def last_pick_html(overall, n, team_name, pid, registry) -> str:
    """A prominent 'who was just taken' banner for the most recent pick."""
    pm = registry.meta(pid)
    rd, inrd = (overall - 1) // n + 1, (overall - 1) % n + 1
    return (f'<div class="dr-lastpick pos-{pm.position}">'
            f'<span class="lp-pk">{rd}.{inrd:02d}</span>'
            f'{theme.img_tag(pid, "lp-img")}'
            f'<span class="lp-txt"><b>{team_name}</b> selected '
            f'<b class="lp-nm">{pm.name}</b> <small>{pm.position} · {pm.team}</small></span></div>')


def on_clock_html(team_name) -> str:
    return f'<div class="dr-onclock"><b>{team_name}</b> is on the clock…</div>'


def recent_ticker_html(picks_by_overall, registry, n=7) -> str:
    """A horizontal strip of the most recent picks (newest first)."""
    if not picks_by_overall:
        return ""
    items = sorted(picks_by_overall.items(), key=lambda x: -x[0])[:n]
    chips = []
    for ov, pid in items:
        pm = registry.meta(pid)
        chips.append(f'<span class="tk-chip pos-{pm.position}"><b>{ov}</b> '
                     f'{short_name(pm.name)} <small>{pm.position}</small></span>')
    return ('<div class="dr-ticker"><span class="tk-l">RECENT</span>'
            + "".join(chips) + "</div>")


def open_needs(my_pids, roster_slots, registry) -> set:
    """Set of starting positions the team still needs (QB/RB/WR/TE + FLEX)."""
    need = {}
    for s in roster_slots:
        if s in _STARTABLE or s == "FLEX":
            need[s] = need.get(s, 0) + 1
    have, flex = {}, 0
    for pid in my_pids:
        pos = registry.meta(pid).position
        if pos in need and have.get(pos, 0) < need[pos]:
            have[pos] = have.get(pos, 0) + 1
        elif pos in _FLEX_OK:
            flex += 1
    out = set()
    for s, total in need.items():
        got = min(flex, total) if s == "FLEX" else have.get(s, 0)
        if got < total:
            out.add(s)
    if "FLEX" in out:
        out |= _FLEX_OK
    return out


def insights_html(board_avail, recent_positions, needs_open) -> str:
    """War-room alert chips: tier cliff + need cues (the positional run lives in the
    prominent run_banner now)."""
    chips = []
    if board_avail:
        top_tier = board_avail[0]["tier"]
        left = sum(1 for r in board_avail if r["tier"] == top_tier)
        if left <= 4:
            chips.append(f'<span class="alert cliff">Tier {top_tier} cliff — '
                         f'{left} left</span>')
    # (positional-run is shown prominently by run_banner_html now — not duplicated here)
    if needs_open:
        order = [p for p in ("QB", "RB", "WR", "TE") if p in needs_open]
        if order:
            chips.append('<span class="alert need">Need: ' + ", ".join(order) + "</span>")
    if not chips:
        return ""
    return '<div class="dr-alerts">' + "".join(chips) + "</div>"


def run_banner_html(board_avail, recent_positions, next_pick, adp_rank, registry,
                    *, needs=None, window=8) -> str:
    """Prominent 'on the clock' run alert: when a positional run is underway, say
    how many quality players are left at that position and how many will likely be
    gone before your next pick. Empty string when no run is detected."""
    from collections import Counter
    recent = [p for p in (recent_positions or [])[-window:] if p in ("QB", "RB", "WR", "TE")]
    if len(recent) < 3:
        return ""
    pos, ct = Counter(recent).most_common(1)[0]
    # A run = ≥4 of the last `window`, or a hot streak of ≥3 of the last 4.
    last4 = [p for p in recent[-4:] if p == pos]
    if not (ct >= 4 or len(last4) >= 3):
        return ""
    at_pos = [r for r in board_avail if registry.meta(r["pid"]).position == pos]
    # "Quality left" = players in the top 2 remaining tiers at this position.
    tiers = sorted({r.get("tier") for r in at_pos if r.get("tier") is not None})
    top2 = set(tiers[:2])
    quality = [r for r in at_pos if r.get("tier") in top2] if top2 else at_pos[:8]
    gone = 0
    if next_pick:
        for r in quality:
            pm = registry.meta(r["pid"])
            sv = survival_pct(adp_rank(pm.name, pm.position), next_pick)
            if sv is not None and sv < 50:
                gone += 1
    is_need = needs and pos in needs
    css = "grab" if is_need else "run"
    tail = f"{len(quality)} quality left"
    if next_pick and gone:
        tail += f" · ~{gone} likely gone by your pick"
    urge = " — you need one" if is_need else ""
    return (f'<div class="dr-runban {css}"><b>{pos} run</b> · {ct} of last '
            f'{len(recent)} picks · {tail}{urge}</div>')


def act_now_html(board_avail, next_pick, adp_rank, registry, value=None,
                 *, limit=5, threshold=50) -> str:
    """'Gone by your next pick' — the best available players unlikely to survive to
    your next turn. Promotes per-card survival math into one act-now list."""
    if not next_pick or not board_avail:
        return ""
    rows = []
    for r in board_avail:
        pm = registry.meta(r["pid"])
        sv = survival_pct(adp_rank(pm.name, pm.position), next_pick)
        if sv is not None and sv < threshold:
            rows.append((sv, r, pm))
    if not rows:
        return ""
    # Order by board rank (best players first), not by survival.
    rows.sort(key=lambda x: (x[1].get("rank") or 9999))
    rows = rows[:limit]
    items = []
    for sv, r, pm in rows:
        pr = r.get("rank")
        rk = f'<span class="an-rk">#{int(pr)}</span>' if pr else ""
        items.append(
            f'<div class="an-row pos-{pm.position}">{theme.img_tag(r["pid"], "an-img")}'
            f'{rk}<span class="an-nm">{short_name(pm.name)}</span>'
            f'<span class="an-tm">{pm.position}·{pm.team}</span>'
            f'<span class="an-sv">{sv}%</span></div>')
    return ('<div class="dr-actnow"><div class="an-h">Likely gone by your next pick</div>'
            + "".join(items) + "</div>")


def _buzz_for(pid, registry, buzz):
    """(kind, count) for a player from the trending map, or None. kind ∈ up/down."""
    if not buzz:
        return None
    pm = registry.meta(pid)
    key = str(pm.sleeper_pid or pid)
    rec = buzz.get(key)
    if not rec:
        return None
    add, drop = rec.get("add", 0), rec.get("drop", 0)
    if add >= max(1, drop):
        return ("up", add)
    if drop:
        return ("down", drop)
    return None


def buzz_chip_html(pid, registry, buzz) -> str:
    """A rising / falling chip for the spotlight, from Sleeper add/drop velocity."""
    b = _buzz_for(pid, registry, buzz)
    if not b:
        return ""
    kind, ct = b
    if kind == "up":
        return (f'<span class="dr-buzz up" title="Added in {ct:,} Sleeper leagues in 24h">'
                f'Rising · {ct:,} adds/24h</span>')
    return (f'<span class="dr-buzz down" title="Dropped in {ct:,} Sleeper leagues in 24h">'
            f'Cooling · {ct:,} drops/24h</span>')


def buzz_list_html(board_avail, registry, buzz, *, limit=6) -> str:
    """A small 'Waiver Buzz' list: the most-added available players (breaking-news
    proxy). Helps catch a beat-the-room handcuff/injury bump mid-draft."""
    if not buzz or not board_avail:
        return ""
    rows = []
    for r in board_avail:
        b = _buzz_for(r["pid"], registry, buzz)
        if b and b[0] == "up":
            rows.append((b[1], r, registry.meta(r["pid"])))
    if not rows:
        return ""
    rows.sort(key=lambda x: -x[0])
    rows = rows[:limit]
    items = []
    for ct, r, pm in rows:
        items.append(
            f'<div class="bz-row pos-{pm.position}">{theme.img_tag(r["pid"], "bz-img")}'
            f'<span class="bz-nm">{short_name(pm.name)}</span>'
            f'<span class="bz-tm">{pm.position}·{pm.team}</span>'
            f'<span class="bz-ct">{ct:,}</span></div>')
    return ('<div class="dr-buzzlist"><div class="bz-h">Waiver Buzz · most-added (24h)</div>'
            + "".join(items) + "</div>")


def needs_strip_html(my_pids, roster_slots, registry) -> str:
    """A slim, always-visible 'roster tray': one chip per starter slot, filled (✓pos)
    or open (highlighted), so you read your needs without leaving the board. FLEX
    slots fill from leftover RB/WR/TE. (Underdog-style.)"""
    order = ["QB", "RB", "WR", "TE", "FLEX"]
    need = {}
    for s in roster_slots:
        if s in _STARTABLE or s == "FLEX":
            need[s] = need.get(s, 0) + 1
    if not need:
        return ""
    have, flex_pool = {}, 0
    for pid in my_pids or []:
        pos = registry.meta(pid).position
        if pos in need and have.get(pos, 0) < need[pos]:
            have[pos] = have.get(pos, 0) + 1
        elif pos in _FLEX_OK:
            flex_pool += 1
    chips = []
    for s in order:
        total = need.get(s, 0)
        if not total:
            continue
        got = min(flex_pool, total) if s == "FLEX" else have.get(s, 0)
        for i in range(total):
            filled = i < got
            cls = "ns-fill" if filled else "ns-open"
            chips.append(f'<span class="ns-chip {cls} ns-{s}">{"✓ " if filled else ""}{s}</span>')
    open_n = sum(1 for s in order for i in range(need.get(s, 0))
                 if not (i < (min(flex_pool, need.get(s, 0)) if s == "FLEX" else have.get(s, 0))))
    head = "Starters set ✓" if open_n == 0 else f"Need {open_n}"
    return (f'<div class="dr-needs"><span class="ns-h">{head}</span>'
            + "".join(chips) + "</div>")


def rookie_history_html(rookie_curve, registry, adp_pool, *, limit=6) -> str:
    """The 'clearer picture' on rookies: how early THIS league has historically
    taken the Nth rookie, and where this year's rookies map vs their consensus ADP.
    Empty when the league has no rookie-aggressive history (so the boost is off)."""
    curve = (rookie_curve or {}).get("curve") or {}
    if not curve:
        return ""
    n_seasons = rookie_curve.get("n_seasons", 0)
    rookies = sorted(
        [p for p in adp_pool if _row_is_rookie(registry, p["pid"])],
        key=lambda p: p["adp"])[:limit]
    rows = []
    for k, p in enumerate(rookies, 1):
        slot = curve.get(k)
        if slot is None:
            continue
        adp = p["adp"]
        delta = adp - slot                      # positive = league drafts him earlier
        pm = registry.meta(p["pid"])
        chip = (f'<span class="rh-up">▲{int(round(delta))}</span>' if delta >= 2
                else f'<span class="rh-flat">≈</span>')
        rows.append(
            f'<div class="rh-row pos-{pm.position}">{theme.img_tag(p["pid"], "rh-img")}'
            f'<span class="rh-nm">{short_name(pm.name)}</span>'
            f'<span class="rh-tm">{pm.position}</span>'
            f'<span class="rh-adp">ADP {int(adp)}</span>'
            f'<span class="rh-arrow">→</span>'
            f'<span class="rh-slot">~pick {int(round(slot))}</span>{chip}</div>')
    if not rows:
        return ""
    # one-line evidence: the most recent season's first three rookies
    samples = sorted(rookie_curve.get("samples", []),
                     key=lambda s: (-s["season"], s["rank"]))
    ev = [s for s in samples if s["rank"] <= 3][:3]
    foot = ""
    if ev:
        yr = ev[0]["season"]
        foot = ('<div class="rh-foot">e.g. ' + str(yr) + ': '
                + ", ".join(f'{short_name(s["name"])} #{s["pick"]}' for s in ev)
                + "</div>")
    return ('<div class="dr-rookhist"><div class="rh-h">Rookie reach · your last '
            + f'{n_seasons} drafts</div>' + "".join(rows) + foot + "</div>")


def _row_is_rookie(registry, pid) -> bool:
    try:
        return registry.meta(pid).years_exp == 0
    except Exception:  # noqa: BLE001
        return False


def bye_conflict_html(my_pids, byes, registry) -> str:
    """Warn when ≥3 of your players share a bye week (a lineup hole that week)."""
    if not byes:
        return ""
    from collections import Counter
    weeks = Counter()
    for pid in my_pids:
        pm = registry.meta(pid)
        if pm.position in ("QB", "RB", "WR", "TE"):
            wk = byes.get(pm.team)
            if wk:
                weeks[wk] += 1
    bad = [(wk, c) for wk, c in sorted(weeks.items()) if c >= 3]
    if not bad:
        return ""
    chips = "".join(f'<span class="alert run">Bye {wk}: {c} players</span>' for wk, c in bad)
    return '<div class="dr-alerts">' + chips + "</div>"


def player_value(pid, registry, adp_rank) -> float:
    """A simple draft-value proxy from overall ADP rank (higher = better)."""
    pm = registry.meta(pid)
    r = adp_rank(pm.name, pm.position)
    return max(0.0, 220.0 - float(r)) if r else 8.0


def roster_strength_html(pids_by_slot, my_slot, slot_names, registry, adp_rank) -> str:
    """Project each team's roster value and rank yours against the league."""
    rows = []
    for slot, pids in pids_by_slot.items():
        val = sum(player_value(p, registry, adp_rank) for p in pids)
        rows.append((slot, val, len(pids)))
    if not rows:
        return ""
    rows.sort(key=lambda x: -x[1])
    rank = next((i + 1 for i, r in enumerate(rows) if r[0] == my_slot), None)
    maxv = max((r[1] for r in rows), default=1) or 1
    bars = []
    for pos, (slot, val, cnt) in enumerate(rows, 1):
        me = " me" if slot == my_slot else ""
        nm = slot_names[slot] if slot < len(slot_names) else f"Team {slot+1}"
        pct = int(100 * val / maxv)
        bars.append(f'<div class="rs-row{me}"><span class="rs-rk">{pos}</span>'
                    f'<span class="rs-nm">{nm[:14]}</span>'
                    f'<span class="rs-bar"><i style="width:{pct}%"></i></span>'
                    f'<span class="rs-val">{int(val)}</span></div>')
    head = (f'<div class="dr-h">Roster Strength — you\'re #{rank} of {len(rows)}</div>'
            if rank else '<div class="dr-h">Roster Strength</div>')
    return head + '<div class="rs">' + "".join(bars) + "</div>"


def steals_traps_html(steals, traps, registry) -> str:
    """Market-inefficiency board: STEALS falling past their value, TRAPS going
    too early. `steals`/`traps` are (row, gap, value_rank, adp) tuples."""
    def cell(item, sym, cls):
        r, gap, vr, adp = item
        pm = registry.meta(r["pid"])
        return (f'<div class="st-row {cls}">{theme.img_tag(r["pid"], "st-img")}'
                f'<span class="st-nm">{r["name"]}<small>{pm.position}·{pm.team}</small></span>'
                f'<span class="st-gap {cls}">{sym}{abs(int(gap))}</span></div>')
    if not steals and not traps:
        return ""
    s_html = "".join(cell(x, "+", "steal") for x in steals) or '<div class="st-none">—</div>'
    t_html = "".join(cell(x, "−", "trap") for x in traps) or '<div class="st-none">—</div>'
    return ('<div class="st-wrap"><div class="st-col"><div class="st-head steal">STEALS '
            '<small>falling past value</small></div>' + s_html + '</div>'
            '<div class="st-col"><div class="st-head trap">TRAPS <small>going too early</small>'
            '</div>' + t_html + '</div></div>')


def _pos_counts(pids, registry):
    c = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
    for pid in pids:
        p = registry.meta(pid).position
        if p in c:
            c[p] += 1
    return c


def league_board_html(pids_by_slot, slot_names, my_slot, roster_slots, registry,
                      on_clock_slot=None) -> str:
    """Every manager's roster-by-position and what they still need — so you can read
    the room (and anticipate runs)."""
    demand = {}
    for s in (roster_slots or []):
        if s in ("QB", "RB", "WR", "TE"):
            demand[s] = demand.get(s, 0) + 1
    rows = []
    for slot in range(len(slot_names)):
        pids = pids_by_slot.get(slot, [])
        cnt = _pos_counts(pids, registry)
        need = [p for p in ("QB", "RB", "WR", "TE") if cnt[p] < demand.get(p, 0)]
        chips = "".join(
            f'<span class="lb-pc {("lb-low" if cnt[p] < demand.get(p, 0) else "")}">'
            f'{p} {cnt[p]}</span>' for p in ("QB", "RB", "WR", "TE"))
        me = " me" if slot == my_slot else ""
        clk = " clk" if slot == on_clock_slot else ""
        nm = slot_names[slot] if slot < len(slot_names) else f"Team {slot+1}"
        need_s = ("needs " + ", ".join(need)) if need else "set"
        rows.append(f'<div class="lb-row{me}{clk}"><span class="lb-nm">{nm[:13]}</span>'
                    f'<span class="lb-chips">{chips}</span>'
                    f'<span class="lb-need">{need_s}</span></div>')
    return '<div class="lb">' + "".join(rows) + "</div>"


_ARCH_COLOR = {
    "Early-QB": "#7c3aed", "Premium-TE": "#e08a1e", "Zero-RB": "#1f4e9b",
    "RB-heavy": "#1c8a4d", "WR-heavy": "#2563c9", "Balanced": "#64748b",
    "Unknown": "#94a3b8",
}


def scouting_report_html(profiles, slot_names, owner_by_slot, my_slot, *,
                         on_clock_slot=None, round_no=None) -> str:
    """Opponent scouting cards built from each manager's real draft history:
    their archetype, how predictable they are, their signature tendencies, and —
    when a round is supplied — what they're most likely to target next."""
    if not profiles:
        return ('<div class="dr-scout"><div class="sc-empty">No draft history found for '
                'this league yet — scouting builds once past drafts are available.</div></div>')
    from .. import draft_history as DH
    cards = []
    order = sorted(range(len(slot_names)),
                   key=lambda s: (s == my_slot, s != on_clock_slot, s))
    for slot in order:
        if slot == my_slot:
            continue
        oid = str(owner_by_slot.get(slot, ""))
        prof = profiles.get(oid) or {}
        nm = slot_names[slot] if slot < len(slot_names) else f"Team {slot+1}"
        arch = prof.get("archetype", "Unknown")
        col = _ARCH_COLOR.get(arch, "#94a3b8")
        clk = " clk" if slot == on_clock_slot else ""
        pred = prof.get("predictability", 0)
        if prof.get("thin", True) or not prof.get("tendencies"):
            body = '<div class="sc-thin">Not enough draft history to profile.</div>'
        else:
            bullets = "".join(f'<li>{t}</li>' for t in prof["tendencies"])
            target = ""
            if round_no:
                likely = DH.likely_positions(oid, round_no, profiles, k=2)
                if likely:
                    target = (f'<div class="sc-target">Likely next: '
                              + " / ".join(f'<b>{p}</b>' for p in likely) + "</div>")
            body = f'<ul class="sc-tend">{bullets}</ul>{target}'
        cards.append(
            f'<div class="sc-card{clk}" style="border-left-color:{col}">'
            f'<div class="sc-head"><span class="sc-nm">{nm[:16]}</span>'
            f'<span class="sc-arch" style="background:{col}1a;color:{col}">{arch}</span></div>'
            f'<div class="sc-pred"><span class="sc-pbar"><span style="width:{pred}%;'
            f'background:{col}"></span></span><span class="sc-plabel">{pred}% predictable</span></div>'
            f'{body}</div>')
    return '<div class="dr-scout">' + "".join(cards) + "</div>"


def run_alert_html(upcoming_slots, need_map, value, taken, registry,
                   profiles=None, owner_by_slot=None, round_no=None) -> str:
    """Flag a likely positional run before your next turn — now scouting-aware: a
    manager who *needs* a position AND whose archetype/history leans that way is a
    much stronger run signal than need alone."""
    if not upcoming_slots or value is None:
        return ""
    from .. import value as V
    taken_s = {str(x) for x in (taken or [])}
    chips = []
    for pos in ("RB", "WR", "TE", "QB"):
        if profiles is not None and owner_by_slot is not None:
            needy, biased, n = V.position_pressure(pos, upcoming_slots, need_map,
                                                   profiles, owner_by_slot, round_no=round_no)
        else:
            uniq = list(dict.fromkeys(upcoming_slots))
            needy = sum(1 for s in uniq if pos in need_map.get(s, ()))
            biased, n = 0, len(uniq)
        left = value.startable_left(pos, taken_s)
        if needy >= 2 and needy >= left:
            lean = f" ({biased} lean {pos})" if biased else ""
            chips.append(f'<span class="alert run">{pos} run likely — {needy} of {n} '
                         f'managers before you need {pos}{lean}, {left} startable left</span>')
    return ('<div class="dr-alerts">' + "".join(chips) + "</div>") if chips else ""


def draft_plan_html(plan) -> str:
    """Render the roster-construction path (next few picks → positions to target)."""
    if not plan:
        return ""
    pos_c = {"QB": "var(--qb)", "RB": "var(--rb)", "WR": "var(--wr)", "TE": "var(--te)"}
    steps = []
    for i, step in enumerate(plan, 1):
        col = pos_c.get(step["pos"], "var(--muted)")
        arrow = '<span class="pl-arrow">→</span>' if i > 1 else ""
        steps.append(f'{arrow}<span class="pl-step"><span class="pl-pos" '
                     f'style="background:{col}1a;color:{col}">{step["pos"]}</span>'
                     f'<span class="pl-nm">{short_name(step["name"])}</span></span>')
    return ('<div class="dr-plan"><div class="pl-h">Your draft path</div>'
            '<div class="pl-row">' + "".join(steps) + "</div></div>")


def draft_grade_html(grade_info, my_pids, roster_slots, registry) -> str:
    """Post-draft grade card: letter grade, starter value, and per-position
    strengths/weaknesses vs your starting requirements."""
    g = grade_info.get("grade", "—")
    gcol = ("#1c8a4d" if g.startswith("A") else "#2f72c4" if g.startswith("B")
            else "#e08a1e" if g.startswith("C") else "#d23b3b")
    have = _pos_counts(my_pids, registry)
    demand = {}
    for s in (roster_slots or []):
        if s in ("QB", "RB", "WR", "TE"):
            demand[s] = demand.get(s, 0) + 1
    bits = []
    for p in ("QB", "RB", "WR", "TE"):
        d = demand.get(p, 0)
        cls = "g-ok" if have[p] >= d else "g-low"
        bits.append(f'<span class="g-pc {cls}">{p} {have[p]}/{d}</span>')
    best = grade_info.get("best_pick")
    best_s = (f'<div class="g-best">Best value: <b>{registry.meta(best).name}</b></div>'
              if best else "")
    return (f'<div class="dr-grade"><div class="g-badge" style="background:{gcol}">{g}</div>'
            f'<div class="g-body"><div class="g-top">Draft grade · '
            f'{grade_info.get("starter_vorp", 0)} starter value over replacement</div>'
            f'<div class="g-pcs">{"".join(bits)}</div>{best_s}</div></div>')


def strategy_html(suggestions, board_avail) -> str:
    """A one-line strategic call atop Suggestions — what to prioritize right now,
    synthesised from the top pick's scarcity, survival, tier cliff and roster fit."""
    if not suggestions:
        return ""
    # Headline the top suggestion that actually fills a starting/flex need — a
    # high-VORP backup at a position you've already locked (e.g. a 2nd elite TE)
    # should NOT drive a "grab now" call. mult >= 0.6 ≈ unfilled starter or RB/WR
    # flex; below that it's bench depth at a filled spot.
    need_top = next((s for s in suggestions if s.get("mult", 1.0) >= 0.6), None)
    starters_set = need_top is None
    top = need_top or suggestions[0]
    pm = top["pm"]
    pos = pm.position
    name = top["row"].get("name", pm.name)
    left, sv, mult = top.get("left"), top.get("sv"), top.get("mult", 1.0)
    cliff = None
    if board_avail:
        tt = board_avail[0].get("tier")
        if tt is not None:
            cliff = sum(1 for r in board_avail if r.get("tier") == tt)
    if starters_set:
        msg = (f"Your starters are set — <b>{name}</b> ({pos}) is the best value left, but "
               "it's bench depth. Draft for upside, handcuffs, or a position run.")
    elif sv is not None and sv <= 30:
        msg = (f"Grab <b>{name}</b> ({pos}) now — only ~{sv}% chance he lasts until you "
               "pick again.")
    elif left is not None and left <= 3:
        msg = f"Prioritize <b>{pos}</b> — just {left} startable left at the position."
    elif cliff is not None and cliff <= 2:
        msg = (f"Tier cliff — only {cliff} left in this tier; take the best (<b>{name}</b>) "
               "before the drop-off.")
    elif mult >= 0.999:
        msg = f"<b>{name}</b> ({pos}) is your best value and fills a starting need — safe pick."
    else:
        msg = (f"<b>{name}</b> ({pos}) is the top value; you can also wait and fill another "
               "need if you prefer.")
    return f'<div class="dr-strategy"><span class="ds-tag">Strategy</span>{msg}</div>'


def picks_feed_html(board, pick_no, n, rounds, slot_names, my_slot, owner_fn,
                    need_map, registry, kept_overalls=None, *, predictions=None,
                    queued=None, lookback=2, lookahead=14) -> str:
    """A live 'Picks' rail (FantasyPros-style): a vertical window of picks around the
    clock — recent selections with the player, your upcoming pick highlighted, and
    each opponent's open team needs *plus the predicted pick* (``predictions`` maps
    overall→pid) folded right into the feed — under a 'next turn in N picks' header."""
    predictions = predictions or {}
    queued = {str(x) for x in (queued or set())}
    total = n * rounds
    kept_overalls = kept_overalls or set()
    lo, hi = max(1, pick_no - lookback), min(total, pick_no + lookahead)
    nxt = next((k for k in range(pick_no, total + 1) if owner_fn(k) == my_slot), None)
    until = (nxt - pick_no) if nxt is not None else None
    head = (f'Next turn in <b>{until} pick{"" if until == 1 else "s"}</b>'
            if until is not None else 'No more picks')

    rows, last_rd = [], None
    for ov in range(lo, hi + 1):
        rd, inrd = (ov - 1) // n + 1, (ov - 1) % n + 1
        if rd != last_rd:
            rows.append(f'<div class="pf-rd">Rd {rd}</div>')
            last_rd = rd
        slot = owner_fn(ov)
        mgr = slot_names[slot] if slot < len(slot_names) else f"Team {slot+1}"
        is_me, is_cur = slot == my_slot, ov == pick_no
        cls = "pf-card" + (" me" if is_me else "") + (" cur" if is_cur else "")
        pklbl = f'{rd}.{inrd:02d}'
        pid = board.get(ov)
        if pid:
            pm = registry.meta(pid)
            kept = ' <span class="ktag">K</span>' if ov in kept_overalls else ''
            rows.append(
                f'<div class="{cls}"><div class="pf-l"><span class="pf-pk">{pklbl}</span>'
                f'<span class="pf-mgr">{mgr[:15]}</span></div>'
                f'<div class="pf-player">{theme.img_tag(pid, "pf-img")}'
                f'<span class="pf-nm">{short_name(pm.name)}</span>'
                f'<span class="pf-meta"><span class="pf-pos pos-{pm.position}">{pm.position}</span>'
                f'{pm.team}{kept}</span></div></div>')
        elif is_cur and is_me:
            rows.append(
                f'<div class="{cls} yours"><div class="pf-l"><span class="pf-pk">{pklbl}</span>'
                f'<span class="pf-mgr">Your Team</span></div>'
                f'<div class="pf-yours">Your Pick!</div></div>')
        else:
            needs = need_map.get(slot, set())
            pills = "".join(f'<span class="pf-need pos-{p}">{p}</span>'
                            for p in ("QB", "RB", "WR", "TE") if p in needs)
            label = "Your Team" if is_me else mgr[:15]
            need_html = (f'<span class="pf-needl">needs</span>{pills}' if pills
                         else '<span class="pf-needl set">set</span>')
            # the predicted pick, folded right into the feed
            pred = predictions.get(ov) if not is_me else None
            pred_html = ""
            if pred:
                ppm = registry.meta(pred)
                # if YOU have him queued, this opponent may snipe him — flag it
                yours = str(pred) in queued
                tag = ('<span class="pf-snipe">★ your queue</span>' if yours
                       else '<span class="pf-likely">likely</span>')
                pred_html = (
                    f'<div class="pf-player pf-pred{" pf-warn" if yours else ""}">'
                    f'{theme.img_tag(pred, "pf-img")}'
                    f'<span class="pf-nm">{short_name(ppm.name)}</span>'
                    f'<span class="pf-meta"><span class="pf-pos pos-{ppm.position}">'
                    f'{ppm.position}</span>{ppm.team}</span>{tag}</div>')
            rows.append(
                f'<div class="{cls}"><div class="pf-l"><span class="pf-pk">{pklbl}</span>'
                f'<span class="pf-mgr">{label}</span></div>{pred_html}'
                f'<div class="pf-needs">{need_html}</div></div>')
    return f'<div class="dr-picks"><div class="pf-head">{head}</div>' + "".join(rows) + "</div>"


def needs_by_slot(pids_by_slot, slot_names, roster_slots, registry):
    """{slot: set(open positions)} — drives the need-aware pick predictor."""
    demand = {}
    for s in (roster_slots or []):
        if s in ("QB", "RB", "WR", "TE"):
            demand[s] = demand.get(s, 0) + 1
    out = {}
    for slot in range(len(slot_names)):
        cnt = _pos_counts(pids_by_slot.get(slot, []), registry)
        out[slot] = {p for p in ("QB", "RB", "WR", "TE") if cnt[p] < demand.get(p, 0)}
    return out


_ADP_META_COLS = {"key", "name_key", "name", "position", "consensus_adp",
                  "n_sources", "consensus_rank"}


def adp_market_html(adp_df, name, position, value_rank=None) -> str:
    """A market read for a player: his ADP across the individual sources (the
    spread = where the market disagrees) plus a buy/'going early' tag vs his
    value. Like Draft Sharks' ADP Market Index, from our multi-source consensus."""
    if adp_df is None or getattr(adp_df, "empty", True):
        return ""
    import pandas as pd
    from ..names import normalize_name
    nk = normalize_name(name)
    rows = adp_df[adp_df["name_key"] == nk]
    if rows.empty:
        return ""
    row = rows.iloc[0]
    srcs = {c: row[c] for c in adp_df.columns
            if c not in _ADP_META_COLS and pd.notna(row.get(c))}
    srcs = {s: v for s, v in srcs.items() if isinstance(v, (int, float))}
    if len(srcs) < 2:
        return ""
    vals = sorted(srcs.values())
    spread = vals[-1] - vals[0]
    cons = row.get("consensus_adp")
    n = len(srcs)
    lo = min(srcs.items(), key=lambda x: x[1])
    hi = max(srcs.items(), key=lambda x: x[1])
    if cons and spread >= max(4, 0.25 * cons):
        tag, cls = f"Split market · ±{int(spread)}", "mk-split"
        chips = (f'<span class="mk-src">earliest {lo[0][:4].upper()} {int(lo[1])}</span>'
                 f'<span class="mk-src">latest {hi[0][:4].upper()} {int(hi[1])}</span>')
    else:
        tag, cls = "Market agrees", "mk-ok"
        chips = f'<span class="mk-src">{n} sources · ADP {int(vals[0])}–{int(vals[-1])}</span>'
    buy = ""
    if value_rank and cons:
        gap = int(cons - value_rank)            # ADP later than value → undervalued
        if gap >= 8:
            buy = f'<span class="mk-buy">Market sleeping (value #{int(value_rank)})</span>'
        elif gap <= -8:
            buy = f'<span class="mk-sell">Going early (value #{int(value_rank)})</span>'
    return (f'<div class="dr-market"><span class="mk-tag {cls}">{tag}</span>{buy}'
            f'<span class="mk-srcs">{chips}</span></div>')


def cheat_sheet_html(board_rows, registry, survival_fn=None, *, per_pos=14,
                     positions=("QB", "RB", "WR", "TE"), taken=None,
                     show_drafted=False) -> str:
    """All-positions cheat sheet: QB/RB/WR/TE side-by-side as tiered columns, each
    available player tagged with the % chance he's still there at your next pick
    (a pick-predictor). Like FantasyPros' Cheat Sheets tab — see every position's
    run/scarcity at a glance instead of one position at a time. When
    ``show_drafted``, drafted players stay in their tier struck-through instead of
    being removed (``board_rows`` should then be the FULL board, not pre-filtered)."""
    taken = {str(x) for x in (taken or set())}
    cols = []
    for pos in positions:
        rows = [r for r in board_rows
                if r.get("pid") and registry.meta(r["pid"]).position == pos]
        if not show_drafted:
            rows = [r for r in rows if str(r["pid"]) not in taken]
        rows = rows[:per_pos]
        if not rows:
            continue
        # the source (UDK) tier is absolute and never renumbered — Tier 1 always
        # means the same players, whether or not they're still on the board.
        cells, last = [], None
        for r in rows:
            t = r.get("pos_tier") or r.get("tier") or 1
            if t != last:
                cells.append(f'<div class="cs-tier">Tier {t}</div>')
                last = t
            pm = registry.meta(r["pid"])
            if str(r["pid"]) in taken:
                cells.append(
                    f'<div class="cs-row drafted"><span class="cs-nm">{r["name"]}</span>'
                    f'<span class="drafted-tag">DRAFTED</span></div>')
                continue
            sv = survival_fn(r["pid"]) if survival_fn else None
            chip = ""
            if sv is not None:
                c = survival_colors(sv)
                chip = (f'<span class="cs-sv" style="background:{c[0]};color:{c[1]}">'
                        f'{sv}%</span>')
            pr = r.get("pos_rank") or ""
            cells.append(
                f'<div class="cs-row"><span class="cs-nm">{r["name"]}</span>'
                f'<span class="cs-tm">{pm.team or "FA"}</span>{chip}</div>')
        cols.append(f'<div class="cs-col"><div class="cs-head pos-{pos}">{pos}</div>'
                    + "".join(cells) + "</div>")
    if not cols:
        return '<div class="cs-empty">No players available.</div>'
    return ('<div class="cheat-sheet"><div class="cs-cap">% = chance he lasts to your '
            'next pick</div><div class="cs-cols">' + "".join(cols) + "</div></div>")


def age_phrase(hours) -> str:
    """'12 minutes ago' / '3 hours ago' / '9 days ago' — one way to say age so the
    board chip, the stale-source warning and the ADP chip can't disagree."""
    if hours is None:
        return "age unknown"
    h = float(hours)
    if h < 1:
        m = max(1, int(round(h * 60)))
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if h < 48:
        n = int(round(h))
        return f"{n} hour{'s' if n != 1 else ''} ago"
    return f"{int(h / 24)} days ago"


def health_html(h: dict) -> str:
    """A one-line data-health strip for the topbar.

    Every external fetch in build_context degrades silently so a network blip
    can't take the app down mid-draft — but a silent fallback is exactly how you
    end up drafting off a stale board, a board with no keepers on it, or a board
    where every manager is in the wrong seat. This surfaces each one: green when
    the data is live, amber/red when we're running on a fallback."""
    if not h:
        return ""
    def chip(label, ok, warn=False):
        c = "var(--red)" if not ok else ("var(--amber)" if warn else "var(--green)")
        return (f'<span class="hz"><i style="background:{c}"></i>{label}</span>')
    bits = []
    age = h.get("adp_age_h")
    if age is None:
        bits.append(chip("ADP missing", False))
    elif age < 24:
        bits.append(chip(f"ADP {int(age)}h", True))
    else:
        bits.append(chip(f"ADP {int(age / 24)}d old", True, warn=True))
    if h.get("keeper_league"):
        n = h.get("keepers") or 0
        bits.append(chip(f"{n} keepers", n > 0))
        bits.append(chip("draft order" if h.get("order_scraped") else "order: Sleeper fallback",
                        bool(h.get("order_scraped")), warn=not h.get("order_scraped")))
    # Your UDK board never auto-refreshes (by design — it's hand-tuned), so its age
    # is the one number nothing else in this strip would ever reveal.
    ba = h.get("board_age_h")
    if ba is not None:
        if ba < 48:
            bits.append(chip(f"board {int(max(1, round(ba)))}h", True))
        else:
            d = int(ba / 24)
            bits.append(chip(f"board {d}d old", d < 30, warn=d >= 7))
    j = h.get("juice") or 0
    bits.append(chip(f"Juice {j}", j > 0, warn=j == 0))
    return f'<div class="dr-health">{"".join(bits)}</div>'


def juice_colhead_html() -> str:
    """Column header for the Juice's Value rows (see ``juice_row_html``) — a plain
    grid div so it lines up with each row's own grid, same trick as ``sg-colhead``
    lining up with ``sg-row`` in the Suggestions tab."""
    return ('<div class="jc-colhead"><span></span><span>PLAYER</span>'
            '<span class="c">ADP</span><span class="c">ECR</span>'
            '<span class="c">&Delta;</span><span class="r">LANDMINE</span></div>')


def juice_row_html(r, *, is_taken=False) -> str:
    """One Juice's Value row as a div (not a `<tr>`) so the caller can place a real
    ☆ queue button beside it (a `<table>` can't have a Streamlit widget spliced
    between rows — see ``juice_tab``). **Δ** is the plain rank-spot gap (Sleeper
    rank − ECR rank): positive/green = Sleeper ranks him LATER than the experts
    (he'll fall further than he should — a value); negative/red = Sleeper ranks
    him EARLIER (a reach if you chase him at that slot). **Landmine** is the
    sheet's own 0-10 risk scale (0 = great value, 10 = avoid). ``r`` is a dict with
    pid/name/position/team/adp_rank/ecr_rank/sleeper_rank/skew/landmine, e.g. one
    value from ``ctx["juice"]``."""
    pid = str(r.get("pid") or "")
    name, pos, team = r.get("name", ""), r.get("position", ""), r.get("team", "")
    rank = r.get("sleeper_rank")
    rank_disp = int(rank) if rank is not None else "—"
    if is_taken:
        return (f'<div class="jc-row drafted"><span class="jc-rk">{rank_disp}</span>'
                f'<span class="jc-who">{theme.img_tag(pid)}<span class="jc-nm-wrap">'
                f'<span class="jc-nm">{name}</span>'
                f'<span class="drafted-tag">DRAFTED</span>'
                f'<div class="pp">{pos} · {team}</div></span></span>'
                f'<span class="c">—</span><span class="c">—</span><span class="c">—</span>'
                f'<span class="r"></span></div>')
    adp, ecr = r.get("adp_rank"), r.get("ecr_rank")
    adp_disp = int(adp) if adp is not None else "—"
    ecr_disp = int(ecr) if ecr is not None else "—"
    delta = (rank - ecr) if (rank is not None and ecr is not None) else None
    delta_html = "—"
    if delta is not None:
        color = ("var(--green)" if delta > 0 else
                 ("var(--red)" if delta < 0 else "var(--mut2)"))
        sign = "+" if delta > 0 else ""
        tip = ("value — falls later than ECR" if delta > 0 else
               "reach — goes earlier than ECR" if delta < 0 else "matches ECR")
        delta_html = f'<b style="color:{color}" title="{tip}">{sign}{delta:.0f}</b>'
    lm = r.get("landmine")
    lm_html = "—"
    if lm is not None:
        c = "var(--red)" if lm >= 7 else ("var(--amber)" if lm >= 5 else "var(--green)")
        lm_html = (f'<div class="lm-wrap" title="Landmine risk {lm:.1f}/10">'
                   f'<span style="color:{c};font-weight:800">{lm:.1f}</span>'
                   f'<div class="lm-track"><i style="width:{min(100, lm * 10):.0f}%;'
                   f'background:{c}"></i></div></div>')
    return (f'<div class="jc-row"><span class="jc-rk">{rank_disp}</span>'
            f'<span class="jc-who">{theme.img_tag(pid)}<span class="jc-nm-wrap">'
            f'<span class="jc-nm">{name}</span>'
            f'<div class="pp">{pos} · {team}</div></span></span>'
            f'<span class="c">{adp_disp}</span><span class="c">{ecr_disp}</span>'
            f'<span class="c">{delta_html}</span><span class="r">{lm_html}</span></div>')


def draft_csv(board, n, rounds, slot_names, owner_fn, registry, adp_rank,
              kept_overalls=None, value=None) -> str:
    """The full draft as CSV (Overall, Pick, Team, Player, Pos, NFLTeam, ADP, Proj,
    Keeper) — for exporting/sharing a completed mock."""
    import csv as _csv
    import io as _io
    kept = kept_overalls or set()
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["Overall", "Pick", "Team", "Player", "Pos", "NFLTeam", "ADP",
                "Proj", "Keeper"])
    for ov in range(1, n * rounds + 1):
        pid = board.get(ov)
        if not pid:
            continue
        pm = registry.meta(pid)
        slot = owner_fn(ov)
        team = slot_names[slot] if slot < len(slot_names) else f"Team {slot + 1}"
        rd, inrd = (ov - 1) // n + 1, (ov - 1) % n + 1
        adp = adp_rank(pm.name, pm.position) if adp_rank else None
        proj = value.proj_of(pid) if value else None
        w.writerow([ov, f"{rd}.{inrd:02d}", team, pm.name, pm.position,
                    pm.team or "", f"{adp:.0f}" if adp else "",
                    f"{proj:.0f}" if proj else "", "Y" if ov in kept else ""])
    return buf.getvalue()


def draft_recap_html(pids_by_slot, my_slot, slot_names, roster_slots, registry,
                     value, adp_rank) -> str:
    """Post-draft scorecard: grade your starters vs the league, project a finish,
    and surface your best values and biggest reaches."""
    if value is None:
        return ""

    def starter_pts(pids):
        _, filled, _ = fill_lineup(pids, roster_slots, registry)
        return sum(value.proj_of(p) for p in filled if p)

    teams = [(slot, starter_pts(pids_by_slot.get(slot, [])))
             for slot in range(len(slot_names))]
    teams.sort(key=lambda x: -x[1])
    rank = next((i + 1 for i, t in enumerate(teams) if t[0] == my_slot), None)
    n = len(teams)
    mine = pids_by_slot.get(my_slot, [])
    my_pts = starter_pts(mine)
    avg = (sum(t[1] for t in teams) / n) if n else 0
    # letter grade from rank percentile
    pct_rank = 1 - ((rank - 1) / max(1, n - 1)) if rank else 0.5
    grade = ("A+" if pct_rank >= 0.95 else "A" if pct_rank >= 0.82 else "B+" if pct_rank >= 0.68
             else "B" if pct_rank >= 0.5 else "C+" if pct_rank >= 0.34 else "C"
             if pct_rank >= 0.18 else "D")

    # best values / reaches among MY picks (value rank vs ADP)
    scored = []
    for pid in mine:
        pm = registry.meta(pid)
        vr = value.rank_of(pid)
        adp = adp_rank(pm.name, pm.position)
        if vr and adp:
            scored.append((pid, int(adp - vr), pm))
    scored.sort(key=lambda x: -x[1])
    steals = [s for s in scored if s[1] >= 6][:3]
    reaches = [s for s in scored if s[1] <= -6][-3:][::-1]

    def names(items):
        return ", ".join(f'{m.name} (+{g})' if g > 0 else f'{m.name} ({g})'
                         for _, g, m in items) or "—"

    diff = my_pts - avg
    diff_s = f'{"+" if diff >= 0 else ""}{diff:.0f} vs league avg'
    return (
        f'<div class="recap"><div class="rc-top">'
        f'<div class="rc-grade g{grade[0]}">{grade}</div>'
        f'<div class="rc-sum"><div class="rc-rank">Projected finish: '
        f'<b>#{rank} of {n}</b></div>'
        f'<div class="rc-pts">{my_pts:.0f} starter pts · {diff_s}</div></div></div>'
        f'<div class="rc-line"><b>Best values:</b> {names(steals)}</div>'
        f'<div class="rc-line"><b>Biggest reaches:</b> {names(reaches)}</div></div>')


def by_position_html(board_avail, registry, adp_rank, pos_rank, current_pick,
                     pos_tier=None, per=16, show_tiers=True, value=None) -> str:
    """Cheat-sheet view: best available in side-by-side QB/RB/WR/TE columns.
    Grouped by per-position UDK tiers, unless ``value`` is supplied — then the
    rows are already value-sorted and tier bands are suppressed (``show_tiers``)
    in favour of a VORP chip."""
    pos_tier = pos_tier or {}
    cols = {"QB": [], "RB": [], "WR": [], "TE": []}
    for r in board_avail:
        pm = registry.meta(r["pid"])
        if pm.position in cols and len(cols[pm.position]) < per:
            cols[pm.position].append((r, pm))
    out = ['<div class="dr-cheat">']
    for pos in ("QB", "RB", "WR", "TE"):
        out.append(f'<div class="cheat-col"><div class="cheat-head {pos}">{pos}</div>')
        last_t = None
        for r, pm in cols[pos]:
            if show_tiers:
                t = pos_tier.get(str(r["pid"]))
                if t is not None and t != last_t:
                    out.append(tier_band(f"{pos} TIER {t}", t))
                    last_t = t
            adp = adp_rank(pm.name, pm.position)
            adp_s = int(adp) if adp else "—"
            if value is not None:
                vv = value.vorp_of(r["pid"])
                cls = "value" if vv >= 0 else "reach"
                chip = f'<span class="vchip {cls}">V {"+" if vv >= 0 else ""}{int(round(vv))}</span>'
            else:
                v = _value_chip(adp, current_pick)
                chip = (" " + v) if v else ""
            out.append(f'<div class="cheat-row">{theme.img_tag(r["pid"], "chs")}'
                       f'<span class="cn">{r["name"]}</span>'
                       f'<span class="ca">{pm.team} · {adp_s}{chip}</span></div>')
        out.append("</div>")
    out.append("</div>")
    return "".join(out)


def queue_html(queue_pids, drafted, registry) -> str:
    """The pick queue / watchlist: ordered, drafted players struck through."""
    if not queue_pids:
        return '<div class="dr-queue"><div class="q-row gone">— queue is empty —</div></div>'
    rows = []
    for pid in queue_pids:
        pm = registry.meta(pid)
        gone = " gone" if str(pid) in drafted else ""
        rows.append(f'<div class="q-row{gone}">{theme.img_tag(pid, "chs")}'
                    f'<span class="qn">{pm.name}</span>'
                    f'<span class="qp">{pm.position} · {pm.team}</span></div>')
    return '<div class="dr-queue">' + "".join(rows) + "</div>"


def rec_reason(top_row, registry, adp_rank, current_pick, needs_open) -> str:
    """One-line reasoning for the top recommended pick (VBD/need/value/tier)."""
    pm = registry.meta(top_row["pid"])
    bits = []
    adp = adp_rank(pm.name, pm.position)
    if adp and current_pick and adp - current_pick >= 6:
        bits.append(f"falling +{int(adp - current_pick)} vs ADP")
    if pm.position in needs_open:
        bits.append(f"fills {pm.position} need")
    bits.append(f"top of your board · T{top_row['tier']}")
    return " · ".join(bits)


def strategy_banner_html(strategy, help_text, targets) -> str:
    """A small always-visible banner showing the active draft strategy, its plan, and
    the players it's steering you toward right now — so switching strategies visibly
    changes the screen on any tab."""
    return (f'<div class="dr-strat"><b>{strategy}</b> — {help_text}'
            f'<span class="st-tgt">Targets now: <b>{targets}</b></span></div>')


ROOKIE_FILTER = "Rook"


def filter_pos(rows, pos_f, registry):
    if pos_f == "All":
        return rows
    if pos_f in (ROOKIE_FILTER, "Rookies"):
        return [r for r in rows if r.get("pid")
                and getattr(registry.meta(r["pid"]), "years_exp", None) == 0]
    tgt = {"RB", "WR", "TE"} if pos_f == "FLEX" else {pos_f}
    return [r for r in rows if r.get("pid") and registry.meta(r["pid"]).position in tgt]


def filter_search(rows, query, registry):
    """Filter board rows by a name/team query.

    Matches on the NORMALIZED name as well as the raw one, so punctuation you
    won't stop to type mid-draft doesn't matter: 'jamarr' finds Ja'Marr Chase,
    'aj brown' finds A.J. Brown, 'cj stroud' finds C.J. Stroud. A raw substring
    match alone returned nothing for every one of those."""
    from ..names import normalize_name
    q = (query or "").strip().lower()
    if not q:
        return rows
    qn = normalize_name(q)
    out = []
    for r in rows:
        nm = (r.get("name") or "").lower()
        team = registry.meta(r["pid"]).team.lower() if r.get("pid") else ""
        if q in nm or (qn and qn in normalize_name(r.get("name") or "")):
            out.append(r)
        elif team and q == team:
            out.append(r)
    return out
