"""Shared interactive widgets used by both the mock and live tabs."""
from __future__ import annotations

import streamlit as st

from . import components as C

_POSCOLS = ("QB", "RB", "WR", "TE")


def _vtxt(adp, pick):
    if not adp or not pick:
        return ""
    d = adp - pick
    if d >= 8:
        return f"  ▼+{int(d)}"
    if d <= -8:
        return f"  ▲{int(d)}"
    return ""


def clickable_board(ctx, board_avail, draft_fn, key_prefix, current_pick=None, *,
                    view="By position", per_pos=15, top_overall=50) -> None:
    """The best-available board, rendered as CLICKABLE rows (no big buttons).

    Grouped by per-position tiers (By position) or overall tiers (Overall list).
    Clicking a row calls draft_fn(pid). Row styling is scoped via keyed
    containers (CSS matches `[class*="_col_<POS>"]`)."""
    reg, pick = ctx["registry"], current_pick
    pos_tier, pos_rank, adp_rank = ctx["pos_tier"], ctx["pos_rank"], ctx["adp_rank"]
    star_pid = str(board_avail[0]["pid"]) if board_avail else None

    if view == "Overall":
        with st.container(key=f"{key_prefix}_col_ALL"):
            last = None
            for r in board_avail[:top_overall]:
                pm = reg.meta(r["pid"])
                if r["tier"] != last:
                    st.markdown(f'<div class="ptier">TIER {r["tier"]}</div>', unsafe_allow_html=True)
                    last = r["tier"]
                adp = adp_rank(pm.name, pm.position)
                pr = pos_rank.get(str(r["pid"]), pm.position)
                star = "★ " if str(r["pid"]) == star_pid else ""
                lbl = f'{star}{pr} · {r["name"]} · {pm.team} · {int(adp) if adp else "—"}{_vtxt(adp, pick)}'
                if st.button(lbl, key=f'{key_prefix}_ALL_{r["pid"]}', use_container_width=True):
                    draft_fn(r["pid"])
        return

    cols = st.columns(4, gap="small")
    for col, pos in zip(cols, _POSCOLS):
        plist = [r for r in board_avail if reg.meta(r["pid"]).position == pos][:per_pos]
        with col:
            st.markdown(f'<div class="cheat-head {pos}">{pos}</div>', unsafe_allow_html=True)
            with st.container(key=f"{key_prefix}_col_{pos}"):
                last = None
                for r in plist:
                    pm = reg.meta(r["pid"])
                    t = pos_tier.get(str(r["pid"]))
                    if t != last:
                        st.markdown(f'<div class="ptier">{pos} TIER {t}</div>',
                                    unsafe_allow_html=True)
                        last = t
                    adp = adp_rank(pm.name, pm.position)
                    star = "★ " if str(r["pid"]) == star_pid else ""
                    lbl = f'{star}{r["name"]} · {pm.team} · {int(adp) if adp else "—"}{_vtxt(adp, pick)}'
                    if st.button(lbl, key=f'{key_prefix}_{pos}_{r["pid"]}', use_container_width=True):
                        draft_fn(r["pid"])
                if not plist:
                    st.caption("—")


def queue_manager(ctx, qkey, ranks, taken, registry, widget_key) -> None:
    """Pick-queue UI: a searchable multiselect builds the queue; it renders as a
    watchlist with drafted players struck through, and drives the recommendation.

    `qkey` is the shared session store (queue persists across tabs); `widget_key`
    must be unique per tab so the two multiselects don't collide."""
    label_to_pid, options = {}, []
    for r in ranks:
        pid = r.get("pid")
        if not pid:
            continue
        pm = registry.meta(pid)
        lbl = f'{r["name"]} ({pm.position}·{pm.team})'
        label_to_pid[lbl] = str(pid)
        options.append(lbl)
    taken_s = {str(x) for x in taken}
    cur = [str(x) for x in st.session_state.get(qkey, [])]
    cur_labels = [lbl for lbl in options if label_to_pid[lbl] in cur]
    n_avail = len([p for p in cur if p not in taken_s])
    with st.expander(f"⭐ My Queue ({n_avail} available)"):
        picked = st.multiselect("Queue players to target", options,
                                default=cur_labels, key=f"{widget_key}_ms")
        st.session_state[qkey] = [label_to_pid[lbl] for lbl in picked]
        st.markdown(C.queue_html(st.session_state[qkey], taken_s, registry),
                    unsafe_allow_html=True)
