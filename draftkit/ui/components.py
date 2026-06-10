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
            body.append(f'<tr class="tierband"><td colspan="3">TIER {r["tier"]}</td></tr>')
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


def grid_html(pick_pids, n, slot_names, my_slot, current_pick, rounds, registry) -> str:
    """Readable color-coded draft board: rounds × teams, snake order, names shown.

    `pick_pids` maps overall pick number -> sleeper pid (or None)."""
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
                cells.append(
                    f'<div class="{klass}"><span class="pk">{r}.{c:02d}</span>'
                    f'<span class="nm">{short_name(pm.name)}</span>'
                    f'<span class="meta">{pm.position} · {pm.team}</span></div>')
            else:
                cells.append(f'<div class="{klass} empty"><span class="pk">{r}.{c:02d}</span>'
                             f'<span class="nm">—</span></div>')
    grid = (f'<div class="dr-grid" style="grid-template-columns:34px repeat({n},{cw});">'
            + "".join(cells) + "</div>")
    return '<div class="neonwrap" style="overflow:auto;">' + grid + "</div>"


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
