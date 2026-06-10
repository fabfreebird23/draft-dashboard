"""Mock Draft tab — history-aware AI opponents, locked keepers, a pick queue,
bye-week warnings, roster-strength ranking, a by-position cheat sheet, and a
war-room of value/tier/run intelligence. Board on top."""
from __future__ import annotations

import streamlit as st

from .. import draft_history
from . import components as C
from .widgets import clickable_board, queue_manager


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
    qkey = f"queue_{ctx['league_key']}"
    kept_by_overall = ctx["keepers"]["by_overall"]
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
        state = {"made": {}, "slot": my_slot}
        st.session_state[mkey] = state
    made = state["made"]

    if undo and made:
        mine = [ov for ov in made if snake(ov - 1) == my_slot]
        if mine:
            del made[max(mine)]

    def taken_pids():
        return set(made.values()) | set(kept_pids)

    overall = 1
    while overall <= total:
        if overall in kept_by_overall or overall in made:
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
    taken = taken_pids()
    board = {**kept_by_overall, **made}

    # ----- status + board on TOP -----
    st.markdown(C.status_html(pick_no, n, slot_names[on_slot], (not done) and on_slot == my_slot),
                unsafe_allow_html=True)
    st.markdown('<div class="dr-h">📋 Draft Board</div>', unsafe_allow_html=True)
    st.markdown(C.grid_html(board, n, slot_names, my_slot, on_clock or 0, rounds, reg,
                            kept_overalls=set(kept_by_overall)), unsafe_allow_html=True)

    my_pids = ([pid for ov, pid in made.items() if snake(ov - 1) == my_slot]
               + [pid for ov, pid in kept_by_overall.items() if snake(ov - 1) == my_slot])
    needs = C.open_needs(my_pids, ctx["roster_slots"], reg)
    recent_positions = [reg.meta(board[ov]).position for ov in sorted(board)[-6:]]
    pids_by_slot = {}
    for ov, pid in board.items():
        pids_by_slot.setdefault(snake(ov - 1), []).append(pid)

    left, right = st.columns([1, 2])
    with left:
        st.markdown('<div class="dr-h">🧢 My Team</div>', unsafe_allow_html=True)
        st.markdown(C.roster_needs_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
        st.markdown(C.bye_conflict_html(my_pids, ctx["byes"], reg), unsafe_allow_html=True)
        st.markdown(C.lineup_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
        st.markdown(C.roster_strength_html(pids_by_slot, my_slot, slot_names, reg, ctx["adp_rank"]),
                    unsafe_allow_html=True)

    with right:
        board_avail = [r for r in C.filter_pos(ranks, pos_f, reg)
                       if r.get("pid") and str(r["pid"]) not in taken]
        if done:
            st.success("✅ Mock complete — your team is on the left. Reset to run another.")
            return

        def draft(pid):
            made[on_clock] = str(pid)
            st.rerun()

        st.markdown(C.insights_html(board_avail, recent_positions, needs), unsafe_allow_html=True)

        # compact recommendation line (the board's ★ row is the same player — click it)
        queue = [p for p in st.session_state.get(qkey, []) if str(p) not in taken]
        rec_row = next((r for r in board_avail if str(r["pid"]) == str(queue[0])), None) if queue else None
        if rec_row is None and board_avail:
            rec_row = board_avail[0]
        if rec_row:
            rpm = reg.meta(rec_row["pid"])
            tag = ("from your queue" if (queue and str(rec_row["pid"]) == str(queue[0]))
                   else C.rec_reason(rec_row, reg, ctx["adp_rank"], pick_no, needs))
            st.markdown(f'<div class="dr-rec">★ <b>{rec_row["name"]}</b> ({rpm.position} · {rpm.team}) '
                        f'— <span class="why">{tag}</span> · <i>click the board to draft</i></div>',
                        unsafe_allow_html=True)

        head = st.columns([3, 2])
        head[0].markdown('<div class="dr-h" style="margin:2px 0;">🎯 Click to Draft — Best Available</div>',
                         unsafe_allow_html=True)
        view = head[1].radio("view", ["By position", "Overall"], horizontal=True,
                             key=f"{mkey}_view", label_visibility="collapsed")
        search = st.text_input("🔎 Search", key=f"{mkey}_search",
                               placeholder="Filter by name or team…", label_visibility="collapsed")
        avail = C.filter_search(board_avail, search, reg)
        clickable_board(ctx, avail, draft, mkey, current_pick=pick_no, view=view)

        queue_manager(ctx, qkey, ranks, taken, reg, f"{mkey}_q")

    kept_note = (f" · 🔒 {len(kept_pids)} keepers locked" if kept_pids else "")
    tnote = " · opponents draft by historical tendencies" if tendencies else ""
    st.caption("Click any player on the board to draft them. ★ Queue players to plan ahead. "
               f"↶ Undo rolls back your last pick.{kept_note}{tnote}")
