"""FantasyPros-style draft surfaces (HTML builders) — extracted from the keeper
app's draft kit. Platform-agnostic: they take a PlayerRegistry, the league's
roster slots, and an adp_rank lookup, so the same render serves Sleeper or ESPN.
"""
from __future__ import annotations

from typing import Callable, List

from .. import theme

_FLEX_OK = {"RB", "WR", "TE"}


def snake(n: int) -> Callable[[int], int]:
    def slot(i: int) -> int:
        rd, j = divmod(i, n)
        return j if rd % 2 == 0 else n - 1 - j
    return slot


def lineup_html(pids: list, roster_slots: List[str], registry, bench_cap: int = 6) -> str:
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


def status_html(pick_no: int, n: int, on_clock_name: str, is_yours: bool) -> str:
    rd = (pick_no - 1) // n + 1
    inrd = (pick_no - 1) % n + 1
    clk = ('<span class="yours">YOUR PICK</span>' if is_yours
           else f'<span class="clk">On the clock: <b>{on_clock_name}</b></span>')
    return (f'<div class="dr-status"><span class="rd">{pick_no}'
            f'<small>OVERALL</small></span>'
            f'<span class="clk">Round <b>{rd}</b> · Pick <b>{rd}.{inrd:02d}</b></span>'
            f'{clk}</div>')


def avail_html(rows, drafted, registry, adp_rank: Callable, limit=120, recommend=True) -> str:
    """Tiered best-available board with a recommendation highlight on the top pick."""
    body, shown, last_tier, first = [], 0, None, True
    for r in rows:
        if shown >= limit:
            break
        if not r.get("pid") or str(r["pid"]) in drafted:
            continue
        shown += 1
        if r["tier"] != last_tier:
            body.append(f'<tr class="tierband"><td colspan="4">TIER {r["tier"]}</td></tr>')
            last_tier = r["tier"]
        pm = registry.meta(r["pid"])
        rec = ' class="rec"' if (recommend and first) else ""
        badge = '<span class="recbadge">★ PICK</span>' if (recommend and first) else ""
        first = False
        adp = adp_rank(pm.name, pm.position)
        adp = int(adp) if adp else "—"
        body.append(
            f'<tr{rec}><td class="r">{r["rank"]}</td>'
            f'<td>{theme.img_tag(r["pid"])}<b>{r["name"]}</b>{badge}'
            f'<div class="pp">{pm.position} · {pm.team}</div></td>'
            f'<td class="a">ADP<br>{adp}</td></tr>'
        )
    return ('<div class="neonwrap" style="max-height:600px;overflow:auto;">'
            '<table class="dr-avail"><tbody>' + "".join(body) + '</tbody></table></div>')


def grid_html(cell_by_pick, n, slot_names, my_slot, current_pick, rounds) -> str:
    """Draft board grid: rounds x draft slots, snake order, picks filled in."""
    cw = "minmax(0,1fr)"
    head = '<div class="dr-colhead"></div>' + "".join(
        f'<div class="dr-colhead">{s.split()[0][:6]}</div>' for s in slot_names)
    cells = [head]
    for r in range(1, rounds + 1):
        cells.append(f'<div class="dr-colhead">{r}</div>')
        for c in range(1, n + 1):
            overall = (r - 1) * n + (c if r % 2 == 1 else n - c + 1)
            info = cell_by_pick.get(overall)
            klass = "dr-cell"
            if (c - 1) == my_slot:
                klass += " me"
            if overall == current_pick:
                klass += " now"
            if info:
                cells.append(f'<div class="{klass}"><span class="pk">{r}.{c:02d}</span><br>{info}</div>')
            else:
                cells.append(f'<div class="{klass} empty"><span class="pk">{r}.{c:02d}</span></div>')
    grid = (f'<div class="dr-grid" style="grid-template-columns:26px repeat({n},{cw});">'
            + "".join(cells) + "</div>")
    return '<div class="neonwrap" style="overflow:auto;">' + grid + "</div>"


def filter_pos(rows, pos_f, registry):
    if pos_f == "All":
        return rows
    tgt = {"RB", "WR", "TE"} if pos_f == "FLEX" else {pos_f}
    return [r for r in rows if r.get("pid") and registry.meta(r["pid"]).position in tgt]
