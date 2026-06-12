"""FantasyPros-style (and better) draft surfaces — platform-agnostic HTML builders.

They take a PlayerRegistry, the league's roster slots, and an adp_rank lookup, so
the same render serves Sleeper or ESPN. Adds positional ranks, ADP value/reach
chips, bye weeks, a readable color-coded draft board, and a roster-needs strip.
"""
from __future__ import annotations

import math
from typing import Callable, List

from .. import theme


def _phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def survival_pct(adp, next_pick):
    """Probability (0-100) a player with this ADP is still available at your next
    pick — models draft position as Normal(adp, sigma) with sigma growing for
    later ADPs, and returns P(not drafted before next_pick)."""
    if not adp or not next_pick:
        return None
    sigma = max(3.0, 0.16 * float(adp))
    p = 1 - _phi((float(next_pick) - float(adp)) / sigma)
    return max(0, min(100, round(p * 100)))


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


def status_html(pick_no: int, n: int, on_clock_name: str, is_yours: bool,
                picks_until_me: int | None = None) -> str:
    rd = (pick_no - 1) // n + 1
    inrd = (pick_no - 1) % n + 1
    clk = ('<span class="yours">YOUR PICK</span>' if is_yours
           else f'<span class="clk">On the clock: <b>{on_clock_name}</b></span>')
    until = ""
    if not is_yours and picks_until_me is not None and picks_until_me > 0:
        until = f'<span class="clk">⏳ <b>{picks_until_me}</b> until you</span>'
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
        sv = survival_pct(adp, next_pick) if next_pick else None
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
              kept_overalls=None, owner_fn=None) -> str:
    """Readable color-coded draft board: rounds × teams, snake order, names shown.

    `pick_pids` maps overall pick number -> sleeper pid (or None).
    `kept_overalls` is a set of overall picks that are keepers (badged 'K').
    `owner_fn(overall)` -> slot of the pick's real owner (handles traded picks); when
    given, your cells are highlighted by ownership rather than by column."""
    kept_overalls = kept_overalls or set()
    cw = "minmax(86px,1fr)"
    head = ['<div class="dr-colhead rd">RD</div>']
    for c, s in enumerate(slot_names):
        me = " me" if c == my_slot else ""
        head.append(f'<div class="dr-colhead{me}" title="{s}">{s[:9]}</div>')
    cells = ["".join(head)]
    for r in range(1, rounds + 1):
        cells.append(f'<div class="dr-rdlabel">{r}</div>')
        for c in range(1, n + 1):
            overall = (r - 1) * n + (c if r % 2 == 1 else n - c + 1)
            pid = pick_pids.get(overall)
            klass = "dr-cell"
            owned = (owner_fn(overall) == my_slot) if owner_fn else ((c - 1) == my_slot)
            if owned:
                klass += " me"
            if overall == current_pick:
                klass += " now"
            if pid:
                pm = registry.meta(pid)
                klass += f" pos-{pm.position or 'NA'}"
                kept = overall in kept_overalls
                if kept:
                    klass += " kept"
                tag = '<span class="ktag">K</span>' if kept else ""
                cells.append(
                    f'<div class="{klass}"><span class="pk">{r}.{c:02d}</span>{tag}'
                    f'<span class="nm">{short_name(pm.name)}</span>'
                    f'<span class="meta">{pm.position} · {pm.team}</span></div>')
            else:
                cells.append(f'<div class="{klass} empty"><span class="pk">{r}.{c:02d}</span>'
                             f'<span class="nm">—</span></div>')
    grid = (f'<div class="dr-grid" style="grid-template-columns:34px repeat({n},{cw});">'
            + "".join(cells) + "</div>")
    return '<div class="neonwrap dr-board-scroll">' + grid + "</div>"


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
    return f'<div class="dr-onclock">⏳ <b>{team_name}</b> is on the clock…</div>'


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
    """War-room alert chips: tier cliff, positional run, and need cues."""
    from collections import Counter
    chips = []
    if board_avail:
        top_tier = board_avail[0]["tier"]
        left = sum(1 for r in board_avail if r["tier"] == top_tier)
        if left <= 4:
            chips.append(f'<span class="alert cliff">Tier {top_tier} cliff — '
                         f'{left} left</span>')
    recent = [p for p in recent_positions[-6:] if p]
    if recent:
        pos, ct = Counter(recent).most_common(1)[0]
        if ct >= 4:
            chips.append(f'<span class="alert run">{pos} run — {ct} of last '
                         f'{len(recent)}</span>')
    if needs_open:
        order = [p for p in ("QB", "RB", "WR", "TE") if p in needs_open]
        if order:
            chips.append('<span class="alert need">Need: ' + ", ".join(order) + "</span>")
    if not chips:
        return ""
    return '<div class="dr-alerts">' + "".join(chips) + "</div>"


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


def run_alert_html(upcoming_slots, need_map, value, taken, registry) -> str:
    """Flag a likely positional run: when more of the managers picking before your
    next turn need a position than there are startable players left at it."""
    if not upcoming_slots or value is None:
        return ""
    from collections import Counter
    # count UNIQUE managers picking before you who still need each position — a
    # manager who picks twice only takes ~one player at a given position
    unique_slots = set(upcoming_slots)
    tally = Counter()
    for s in unique_slots:
        for pos in need_map.get(s, ()):
            tally[pos] += 1
    taken_s = {str(x) for x in (taken or [])}
    n_mgrs = len(unique_slots)
    chips = []
    for pos, dem in sorted(tally.items(), key=lambda x: -x[1]):
        left = value.startable_left(pos, taken_s)
        if dem >= 2 and dem >= left:
            chips.append(f'<span class="alert run">{pos} run likely — {dem} of {n_mgrs} '
                         f'managers before you need {pos}, {left} startable left</span>')
    return ('<div class="dr-alerts">' + "".join(chips) + "</div>") if chips else ""


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


def filter_pos(rows, pos_f, registry):
    if pos_f == "All":
        return rows
    tgt = {"RB", "WR", "TE"} if pos_f == "FLEX" else {pos_f}
    return [r for r in rows if r.get("pid") and registry.meta(r["pid"]).position in tgt]


def filter_search(rows, query, registry):
    """Filter board rows by a name/team substring query."""
    q = (query or "").strip().lower()
    if not q:
        return rows
    out = []
    for r in rows:
        nm = (r.get("name") or "").lower()
        team = registry.meta(r["pid"]).team.lower() if r.get("pid") else ""
        if q in nm or (team and q == team):
            out.append(r)
    return out
