"""Mock Draft tab — AI opponents draft like their real managers (historical
tendency + ADP), keepers are pre-locked on the board, and you draft off your UDK
board with a war-room of value/tier/run intelligence. Board on top."""
from __future__ import annotations

import streamlit as st

from .. import draft_history
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
    kept_by_overall = ctx["keepers"]["by_overall"]   # {overall -> pid}, locked from start
    kept_pids = ctx["keepers"]["kept_pids"]
    tendencies = ctx["tendencies"]
    owner_by_slot = ctx["owner_by_slot"]
    adp_pool = ctx["adp_pool"]
    snake = C.snake(n)
    total = n * rounds

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
    if reset or not state or "made" not in state or state.get("slot") != my_slot:
        state = {"made": {}, "slot": my_slot}     # made: {overall -> pid} (user+AI only)
        st.session_state[mkey] = state
    made = state["made"]

    if undo and made:
        mine = [ov for ov in made if snake(ov - 1) == my_slot]
        if mine:
            del made[max(mine)]

    def resolved(ov):
        return ov in kept_by_overall or ov in made

    def taken_pids():
        return set(made.values()) | set(kept_pids)

    # Advance the draft: skip keeper slots (locked), AI drafts by tendency+ADP,
    # stop at the user's next open pick.
    overall = 1
    while overall <= total:
        if resolved(overall):
            overall += 1
            continue
        slot = snake(overall - 1)
        if slot == my_slot:
            break
        rnd = (overall - 1) // n + 1
        tk = taken_pids()
        pool = [p for p in adp_pool if p["pid"] not in tk]
        choice = draft_history.pick_for_owner(owner_by_slot.get(slot), rnd, pool, tendencies, reg)
        if not choice:
            break
        made[overall] = choice["pid"]
        overall += 1

    on_clock = overall if overall <= total else None
    done = on_clock is None
    pick_no = on_clock or total
    on_slot = snake(pick_no - 1)

    # ----- status + board on TOP (keepers always shown) -----
    st.markdown(C.status_html(pick_no, n, slot_names[on_slot], (not done) and on_slot == my_slot),
                unsafe_allow_html=True)
    st.markdown('<div class="dr-h">📋 Draft Board</div>', unsafe_allow_html=True)
    board = {**kept_by_overall, **made}
    st.markdown(C.grid_html(board, n, slot_names, my_slot, on_clock or 0, rounds, reg,
                            kept_overalls=set(kept_by_overall)), unsafe_allow_html=True)

    my_pids = ([pid for ov, pid in made.items() if snake(ov - 1) == my_slot]
               + [pid for ov, pid in kept_by_overall.items() if snake(ov - 1) == my_slot])
    needs = C.open_needs(my_pids, ctx["roster_slots"], reg)
    recent_positions = [reg.meta(board[ov]).position for ov in sorted(board)[-6:]]
    taken = taken_pids()

    left, right = st.columns([1, 2])
    with left:
        st.markdown('<div class="dr-h">🧢 My Team</div>', unsafe_allow_html=True)
        st.markdown(C.roster_needs_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
        st.markdown(C.lineup_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
    with right:
        board_avail = [r for r in C.filter_pos(ranks, pos_f, reg)
                       if r.get("pid") and str(r["pid"]) not in taken]
        if done:
            st.success("✅ Mock complete — your team is on the left. Reset to run another.")
        else:
            st.markdown(C.insights_html(board_avail, recent_positions, needs), unsafe_allow_html=True)
            avail = C.filter_search(board_avail, st.session_state.get(f"{mkey}_search", ""), reg)

            def draft(pid):
                made[on_clock] = str(pid)
                st.rerun()

            if avail:
                tp = avail[0]
                tpm = reg.meta(tp["pid"])
                why = C.rec_reason(tp, reg, ctx["adp_rank"], pick_no, needs)
                st.markdown(f'<div class="dr-rec">★ <b>{tp["name"]}</b> '
                            f'({tpm.position} · {tpm.team}) — <span class="why">{why}</span></div>',
                            unsafe_allow_html=True)
                if st.button(f'★ DRAFT {tp["name"]}', key=f'{mkey}_best_{pick_no}',
                             type="primary", use_container_width=True):
                    draft(tp["pid"])

            st.text_input("🔎 Search any player to draft", key=f"{mkey}_search",
                          placeholder="Type a name… e.g. Bijan, Chase, Nabers")
            st.caption(f"{len(avail)} available" + (" — showing 18, search to narrow"
                                                    if len(avail) > 18 else ""))
            bcols = st.columns(3)
            for i, r in enumerate(avail[:18]):
                pm = reg.meta(r["pid"])
                pr = ctx["pos_rank"].get(str(r["pid"]), pm.position)
                adp = ctx["adp_rank"](pm.name, pm.position)
                adp_s = f" · ADP {int(adp)}" if adp else ""
                if bcols[i % 3].button(f'{r["name"]}\n{pr} · {pm.team}{adp_s}',
                                       key=f'{mkey}_pk_{pick_no}_{r["pid"]}',
                                       use_container_width=True):
                    draft(r["pid"])
        st.markdown('<div class="dr-h" style="margin-top:10px;">🎯 Best Available — Your Board</div>',
                    unsafe_allow_html=True)
        st.markdown(C.avail_html(C.filter_pos(ranks, pos_f, reg), taken, reg, ctx["adp_rank"],
                                 pos_rank=ctx["pos_rank"], current_pick=pick_no),
                    unsafe_allow_html=True)

    kept_note = (f" · 🔒 {len(kept_pids)} keepers locked" if kept_pids else "")
    tnote = " · opponents draft by historical tendencies" if tendencies else ""
    st.caption("Draft anyone via ★, the quick buttons, or search. ↶ Undo rolls back your "
               f"last pick.{kept_note}{tnote}")
