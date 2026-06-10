"""Mock Draft tab — AI opponents auto-pick by consensus ADP; you draft off your
UDK board. Snake order, both platforms. No keepers (standalone)."""
from __future__ import annotations

import streamlit as st

from . import components as C


def render(ctx) -> None:
    reg = ctx["registry"]
    ranks = st.session_state.get(ctx["ranks_key"])
    if not ranks:
        st.info("Add your rankings on the **My Rankings** tab first.")
        return

    slot_names = ctx["slot_names"]
    n = len(slot_names)
    rounds = ctx["meta"].draft_rounds
    mkey = f"mock_{ctx['league_key']}"

    top = st.columns([2, 1, 1])
    me = top[0].selectbox("Your draft slot", slot_names, key=f"{mkey}_slot")
    pos_f = top[1].selectbox("Position", ["All", "QB", "RB", "WR", "TE", "FLEX"], key=f"{mkey}_pos")
    with top[2]:
        st.write("")
        if st.button("🔁 Reset mock", key=f"{mkey}_reset"):
            st.session_state[mkey] = {"taken": [], "log": []}
            st.rerun()

    my_slot = slot_names.index(me)
    state = st.session_state.get(mkey)
    if not state:
        state = {"taken": [], "log": []}
        st.session_state[mkey] = state
    taken = set(state["taken"])
    adp_pool = ctx["adp_pool"]
    snake = C.snake(n)
    total = n * rounds

    # Auto-run AI picks (by ADP) until it's the user's pick or the draft is full.
    while len(state["log"]) < total and snake(len(state["log"])) != my_slot:
        nxt = next((p for p in adp_pool if p["pid"] not in taken), None)
        if not nxt:
            break
        taken.add(nxt["pid"])
        state["log"].append({"slot": snake(len(state["log"])), "pid": nxt["pid"]})
    state["taken"] = list(taken)

    done = len(state["log"]) >= total
    pick_no = min(len(state["log"]) + 1, total)
    on_slot = snake(len(state["log"])) if not done else my_slot
    st.markdown(C.status_html(pick_no, n, slot_names[on_slot], (not done) and on_slot == my_slot),
                unsafe_allow_html=True)

    my_pids = [p["pid"] for p in state["log"] if p["slot"] == my_slot]
    left, right = st.columns([1, 2])
    with left:
        st.markdown('<div class="dr-h">🧢 My Team</div>', unsafe_allow_html=True)
        st.markdown(C.lineup_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
    with right:
        if done:
            st.success("✅ Mock complete — your team is on the left. Reset to run another.")
        else:
            st.markdown('<div class="dr-h">⏰ On the Clock — Make Your Pick</div>',
                        unsafe_allow_html=True)
            avail = [r for r in C.filter_pos(ranks, pos_f, reg)
                     if r.get("pid") and str(r["pid"]) not in taken]
            bcols = st.columns(3)
            for i, r in enumerate(avail[:6]):
                pm = reg.meta(r["pid"])
                if bcols[i % 3].button(f'➕ {r["name"]} · {pm.position} T{r["tier"]}',
                                       key=f'{mkey}_pk_{len(state["log"])}_{r["pid"]}',
                                       use_container_width=True):
                    taken.add(str(r["pid"]))
                    state["taken"] = list(taken)
                    state["log"].append({"slot": my_slot, "pid": str(r["pid"])})
                    st.rerun()
        st.markdown('<div class="dr-h" style="margin-top:10px;">🎯 Best Available — Your Board</div>',
                    unsafe_allow_html=True)
        st.markdown(C.avail_html(C.filter_pos(ranks, pos_f, reg), taken, reg, ctx["adp_rank"]),
                    unsafe_allow_html=True)

    with st.expander("📋 Draft Board"):
        cell = {i: reg.meta(p["pid"]).name.split()[-1]
                for i, p in enumerate(state["log"], 1)}
        st.markdown(C.grid_html(cell, n, slot_names, my_slot, len(state["log"]) + 1, rounds),
                    unsafe_allow_html=True)
    st.caption("Practice mock — other teams auto-pick by consensus ADP; you draft off "
               "your UDK board (top 6 as quick buttons, ★ = top pick).")
