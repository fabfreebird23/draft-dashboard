"""Mock Draft tab — AI opponents auto-pick by consensus ADP; you draft off your
UDK board. Search or click ANY available player, undo, snake order, both
platforms. No keepers (standalone)."""
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
        cc = st.columns(2)
        reset = cc[0].button("🔁 Reset", key=f"{mkey}_reset", use_container_width=True)
        undo = cc[1].button("↶ Undo", key=f"{mkey}_undo", use_container_width=True)

    my_slot = slot_names.index(me)
    state = st.session_state.get(mkey)
    if reset or not state:
        state = {"log": []}
        st.session_state[mkey] = state

    snake = C.snake(n)
    total = n * rounds

    if undo and state["log"]:
        # Roll back to (and including) the user's last pick so they re-pick.
        mine = [i for i, p in enumerate(state["log"]) if p["slot"] == my_slot]
        if mine:
            state["log"] = state["log"][:mine[-1]]

    def taken_ids():
        return {p["pid"] for p in state["log"]}

    # Auto-run AI picks (by ADP) until it's the user's pick or the draft is full.
    adp_pool = ctx["adp_pool"]
    while len(state["log"]) < total and snake(len(state["log"])) != my_slot:
        tk = taken_ids()
        nxt = next((p for p in adp_pool if p["pid"] not in tk), None)
        if not nxt:
            break
        state["log"].append({"slot": snake(len(state["log"])), "pid": nxt["pid"]})

    taken = taken_ids()
    done = len(state["log"]) >= total
    pick_no = min(len(state["log"]) + 1, total)
    on_slot = snake(len(state["log"])) if not done else my_slot
    st.markdown(C.status_html(pick_no, n, slot_names[on_slot], (not done) and on_slot == my_slot),
                unsafe_allow_html=True)

    my_pids = [p["pid"] for p in state["log"] if p["slot"] == my_slot]
    left, right = st.columns([1, 2])
    with left:
        st.markdown('<div class="dr-h">🧢 My Team</div>', unsafe_allow_html=True)
        st.markdown(C.roster_needs_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
        st.markdown(C.lineup_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
    with right:
        if done:
            st.success("✅ Mock complete — your team is on the left. Reset to run another.")
        else:
            st.markdown('<div class="dr-h">⏰ On the Clock — Draft Anyone</div>',
                        unsafe_allow_html=True)
            avail = [r for r in C.filter_pos(ranks, pos_f, reg)
                     if r.get("pid") and str(r["pid"]) not in taken]
            search = st.text_input("🔎 Search a player to draft", key=f"{mkey}_search",
                                   placeholder="Type a name… e.g. Bijan, Chase, Nabers")
            avail = C.filter_search(avail, search, reg)

            def draft(pid):
                state["log"].append({"slot": my_slot, "pid": str(pid)})
                st.rerun()

            if avail:
                top_pick = avail[0]
                tp = reg.meta(top_pick["pid"])
                if st.button(f'★ DRAFT BEST: {top_pick["name"]} — {tp.position} · {tp.team} '
                             f'(T{top_pick["tier"]})', key=f'{mkey}_best_{len(state["log"])}',
                             type="primary", use_container_width=True):
                    draft(top_pick["pid"])

            st.caption(f"{len(avail)} available" + (" (showing first 18 — search to narrow)"
                                                   if len(avail) > 18 else ""))
            bcols = st.columns(3)
            for i, r in enumerate(avail[:18]):
                pm = reg.meta(r["pid"])
                pr = ctx["pos_rank"].get(str(r["pid"]), pm.position)
                adp = ctx["adp_rank"](pm.name, pm.position)
                adp_s = f" · ADP {int(adp)}" if adp else ""
                if bcols[i % 3].button(f'{r["name"]}\n{pr} · {pm.team}{adp_s}',
                                       key=f'{mkey}_pk_{len(state["log"])}_{r["pid"]}',
                                       use_container_width=True):
                    draft(r["pid"])
        st.markdown('<div class="dr-h" style="margin-top:10px;">🎯 Best Available — Your Board</div>',
                    unsafe_allow_html=True)
        st.markdown(C.avail_html(C.filter_pos(ranks, pos_f, reg), taken, reg, ctx["adp_rank"],
                                 pos_rank=ctx["pos_rank"], current_pick=pick_no),
                    unsafe_allow_html=True)

    st.markdown('<div class="dr-h" style="margin-top:12px;">📋 Draft Board</div>',
                unsafe_allow_html=True)
    pick_pids = {i: p["pid"] for i, p in enumerate(state["log"], 1)}
    st.markdown(C.grid_html(pick_pids, n, slot_names, my_slot, len(state["log"]) + 1, rounds, reg),
                unsafe_allow_html=True)
    st.caption("Other teams auto-pick by consensus ADP. Draft anyone via search, the quick "
               "buttons, or ★ Draft Best. ↶ Undo rolls back your last pick.")
