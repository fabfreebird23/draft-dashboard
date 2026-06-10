"""Shared interactive widgets used by both the mock and live tabs."""
from __future__ import annotations

import streamlit as st

from .. import theme
from . import components as C


def clickable_board(ctx, board_avail, draft_fn, key_prefix, current_pick=None, *,
                    view="List", per_pos=16, limit=70) -> None:
    """Best-available board where the WHOLE player row is the draft button
    (no separate button). Position-colored left bar (scoped `[class*="_brow_<POS>"]`),
    bold color-coded tier bands. `view`='List' groups by overall tier; 'By position'
    splits into QB/RB/WR/TE columns grouped by per-position tier."""
    reg, pick = ctx["registry"], current_pick
    pos_tier, pos_rank, adp_rank = ctx["pos_tier"], ctx["pos_rank"], ctx["adp_rank"]
    byes = ctx.get("byes", {})
    star_pid = str(board_avail[0]["pid"]) if board_avail else None

    def label(r, pm):
        adp = adp_rank(pm.name, pm.position)
        pr = pos_rank.get(str(r["pid"]), pm.position)
        bye = byes.get(pm.team, "")
        d = (adp - pick) if (adp and pick) else 0
        vt = f"   ▼ +{int(d)}" if d >= 8 else (f"   ▲ {int(d)}" if d <= -8 else "")
        adps = int(adp) if adp else "—"
        star = "★ " if str(r["pid"]) == star_pid else ""
        bye_s = f" · Bye {bye}" if bye else ""
        return f'{star}{pr} · {r["name"]} · {pm.team} · ADP {adps}{bye_s}{vt}'

    def emit_row(r):
        pm = reg.meta(r["pid"])
        with st.container(key=f'{key_prefix}_brow_{pm.position}_{r["pid"]}'):
            if st.button(label(r, pm), key=f'{key_prefix}_pick_{r["pid"]}',
                         use_container_width=True):
                draft_fn(r["pid"])

    if view == "By position":
        cols = st.columns(4, gap="small")
        for col, pos in zip(cols, ("QB", "RB", "WR", "TE")):
            plist = [r for r in board_avail if reg.meta(r["pid"]).position == pos][:per_pos]
            with col:
                st.markdown(f'<div class="cheat-head {pos}">{pos}</div>', unsafe_allow_html=True)
                with st.container(key=f"{key_prefix}_board_{pos}"):
                    last = None
                    for r in plist:
                        t = pos_tier.get(str(r["pid"]))
                        if t != last:
                            st.markdown(C.tier_band(f"{pos} Tier {t}", t), unsafe_allow_html=True)
                            last = t
                        emit_row(r)
                    if not plist:
                        st.caption("—")
    else:
        with st.container(key=f"{key_prefix}_board_all"):
            last = None
            for r in board_avail[:limit]:
                if r["tier"] != last:
                    st.markdown(C.tier_band(f"Tier {r['tier']}", r["tier"]), unsafe_allow_html=True)
                    last = r["tier"]
                emit_row(r)


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
