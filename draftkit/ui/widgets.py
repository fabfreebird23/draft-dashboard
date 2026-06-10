"""Shared interactive widgets used by both the mock and live tabs."""
from __future__ import annotations

import streamlit as st

from . import components as C


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
