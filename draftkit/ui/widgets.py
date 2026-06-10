"""Shared interactive widgets used by both the mock and live tabs."""
from __future__ import annotations

import streamlit as st

from .. import theme
from . import components as C


def _vchip(adp, pick):
    if not adp or not pick:
        return ""
    d = adp - pick
    if d >= 8:
        return f'<span class="vchip value">▼ +{int(d)}</span>'
    if d <= -8:
        return f'<span class="vchip reach">▲ {int(d)}</span>'
    return ""


def clickable_board(ctx, board_avail, draft_fn, key_prefix, current_pick=None, *,
                    limit=70) -> None:
    """Best-available as a clean FantasyPros-style table — rich rows (headshot,
    position badge, ADP, value badge) grouped by tier, each with a green Draft
    button. Clicking Draft calls draft_fn(pid)."""
    reg, pick = ctx["registry"], current_pick
    pos_rank, adp_rank = ctx["pos_rank"], ctx["adp_rank"]
    byes = ctx.get("byes", {})
    star_pid = str(board_avail[0]["pid"]) if board_avail else None

    with st.container(key=f"{key_prefix}_fpbtn"):
        last = None
        for r in board_avail[:limit]:
            pm = reg.meta(r["pid"])
            if r["tier"] != last:
                st.markdown(f'<div class="ptier">TIER {r["tier"]}</div>', unsafe_allow_html=True)
                last = r["tier"]
            adp = adp_rank(pm.name, pm.position)
            pr = pos_rank.get(str(r["pid"]), pm.position)
            bye = byes.get(pm.team, "")
            st_ = '<span class="fp-star">★</span>' if str(r["pid"]) == star_pid else ""
            row = (f'<div class="fp-row">{st_}{theme.img_tag(r["pid"])}'
                   f'<span class="posrank {pm.position}">{pr}</span>'
                   f'<span class="nm">{r["name"]}</span><span class="tm">{pm.team}</span>'
                   f'{_vchip(adp, pick)}<span class="sp"></span>'
                   f'<span class="by">Bye {bye}</span>'
                   f'<span class="adp">{int(adp) if adp else "—"} <small>ADP</small></span></div>')
            c = st.columns([8, 1.2], vertical_alignment="center")
            c[0].markdown(row, unsafe_allow_html=True)
            if c[1].button("Draft", key=f'{key_prefix}_d_{r["pid"]}'):
                draft_fn(r["pid"])


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
