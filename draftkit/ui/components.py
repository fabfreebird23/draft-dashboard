"""FantasyPros-style (and better) draft surfaces — platform-agnostic HTML builders.

They take a PlayerRegistry, the league's roster slots, and an adp_rank lookup, so
the same render serves Sleeper or ESPN. Adds positional ranks, ADP value/reach
chips, bye weeks, a readable color-coded draft board, and a roster-needs strip.
"""
from __future__ import annotations

from typing import Callable, List

from .. import theme

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
    """A bold, color-coded tier separator."""
    c = tier_color(tier)
    return (f'<div class="{cls}" style="background:{c};color:#fff;border-left:5px solid '
            f'rgba(0,0,0,.25)">{label}</div>')


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


def lineup_html(pids: list, roster_slots: List[str], registry, bench_cap: int = 8) -> str:
    """My-Team panel: fill starter slots (QB/RB/WR/TE/FLEX/…), overflow to bench."""
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
    rows = []
    for s, pid in zip(slots, filled):
        nm = registry.meta(pid).name if pid else "—"
        empty = "" if pid else " empty"
        rows.append(f'<div class="slot{empty}"><span class="pos {s}">{s}</span>'
                    f'<span class="nm">{nm}</span></div>')
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


def avail_html(rows, drafted, registry, adp_rank: Callable, *, pos_rank=None,
               current_pick=None, limit=140, recommend=True) -> str:
    """Tiered best-available board: positional rank, ADP, and value/reach chips."""
    pos_rank = pos_rank or {}
    body, shown, last_tier, first = [], 0, None, True
    for r in rows:
        if shown >= limit:
            break
        if not r.get("pid") or str(r["pid"]) in drafted:
            continue
        shown += 1
        if r["tier"] != last_tier:
            c = tier_color(r["tier"])
            body.append(f'<tr class="tierband" style="background:{c}"><td colspan="3" '
                        f'style="color:#fff">TIER {r["tier"]}</td></tr>')
            last_tier = r["tier"]
        pm = registry.meta(r["pid"])
        rec = ' class="rec"' if (recommend and first) else ""
        badge = '<span class="recbadge">★ PICK</span>' if (recommend and first) else ""
        first = False
        adp = adp_rank(pm.name, pm.position)
        adp_disp = int(adp) if adp else "—"
        pr = pos_rank.get(str(r["pid"]), "")
        pr_html = f'<span class="posrank {pm.position}">{pr}</span>' if pr else ""
        vchip = _value_chip(adp, current_pick)
        body.append(
            f'<tr{rec}><td class="r">{r["rank"]}</td>'
            f'<td>{theme.img_tag(r["pid"])}{pr_html}<b>{r["name"]}</b>{badge}{vchip}'
            f'<div class="pp">{pm.position} · {pm.team}</div></td>'
            f'<td class="a">ADP<br>{adp_disp}</td></tr>'
        )
    return ('<div class="neonwrap" style="max-height:620px;overflow:auto;">'
            '<table class="dr-avail"><tbody>' + "".join(body) + '</tbody></table></div>')


def grid_html(pick_pids, n, slot_names, my_slot, current_pick, rounds, registry,
              kept_overalls=None) -> str:
    """Readable color-coded draft board: rounds × teams, snake order, names shown.

    `pick_pids` maps overall pick number -> sleeper pid (or None).
    `kept_overalls` is a set of overall picks that are keepers (badged 'K')."""
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
            if (c - 1) == my_slot:
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
            chips.append(f'<span class="alert cliff">⚠ Tier {top_tier} cliff — '
                         f'{left} left</span>')
    recent = [p for p in recent_positions[-6:] if p]
    if recent:
        pos, ct = Counter(recent).most_common(1)[0]
        if ct >= 4:
            chips.append(f'<span class="alert run">🔥 {pos} run — {ct} of last '
                         f'{len(recent)}</span>')
    if needs_open:
        order = [p for p in ("QB", "RB", "WR", "TE") if p in needs_open]
        if order:
            chips.append('<span class="alert need">🎯 Need: ' + ", ".join(order) + "</span>")
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
    chips = "".join(f'<span class="alert run">🗓 Bye {wk}: {c} players</span>' for wk, c in bad)
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
    head = (f'<div class="dr-h">💪 Roster Strength — you\'re #{rank} of {len(rows)}</div>'
            if rank else '<div class="dr-h">💪 Roster Strength</div>')
    return head + '<div class="rs">' + "".join(bars) + "</div>"


def by_position_html(board_avail, registry, adp_rank, pos_rank, current_pick,
                     pos_tier=None, per=16) -> str:
    """Cheat-sheet view: best available in side-by-side QB/RB/WR/TE columns,
    grouped by per-position tiers."""
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
            t = pos_tier.get(str(r["pid"]))
            if t is not None and t != last_t:
                out.append(tier_band(f"{pos} TIER {t}", t))
                last_t = t
            adp = adp_rank(pm.name, pm.position)
            adp_s = int(adp) if adp else "—"
            v = _value_chip(adp, current_pick)
            out.append(f'<div class="cheat-row">{theme.img_tag(r["pid"], "chs")}'
                       f'<span class="cn">{r["name"]}</span>'
                       f'<span class="ca">{pm.team} · {adp_s}{(" "+v) if v else ""}</span></div>')
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
