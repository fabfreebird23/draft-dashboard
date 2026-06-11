"""Mock Draft tab — history-aware AI opponents, locked keepers, a pick queue,
bye-week warnings, roster-strength ranking, a by-position cheat sheet, and a
war-room of value/tier/run intelligence. Board on top."""
from __future__ import annotations

import time

import streamlit as st

from .. import draft_history
from . import components as C
from .widgets import (predict_upcoming, predictor_widget, queue_manager,
                      rankings_tab, select_player, spotlight_panel, steals_traps_widget)

_PICK_DELAY = 0.7  # seconds between AI picks in live-pace mode


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
    owner = ctx["pick_owner_slot"]   # who owns each overall pick (handles traded picks)
    total = n * rounds

    top = st.columns([2, 1, 1])
    me = top[0].selectbox("Your draft slot", slot_names, key=f"{mkey}_slot")
    live_pace = top[1].checkbox("Live pace", value=True, key=f"{mkey}_pace",
                                help="Opponents pick one at a time with a short delay.")
    with top[2]:
        st.write("")
        cc = st.columns(2)
        reset = cc[0].button("Reset", key=f"{mkey}_reset", use_container_width=True)
        undo = cc[1].button("Undo", key=f"{mkey}_undo", use_container_width=True)
    # Position filtering lives in the Best Available panel ("By position" view), so
    # the top-level dropdown was redundant — the List view now shows all positions.
    pos_f = "All"

    my_slot = slot_names.index(me)
    state = st.session_state.get(mkey)
    if reset or not state or "made" not in state or state.get("slot") != my_slot:
        state = {"made": {}, "slot": my_slot}
        st.session_state[mkey] = state
    made = state["made"]

    if undo and made:
        mine = [ov for ov in made if owner(ov) == my_slot]
        if mine:
            del made[max(mine)]

    def taken_pids():
        return set(made.values()) | set(kept_pids)

    def first_unresolved():
        ov = 1
        while ov <= total and (ov in kept_by_overall or ov in made):
            ov += 1
        return ov if ov <= total else None

    def ai_pick(ov):
        rnd = (ov - 1) // n + 1
        tk = taken_pids()
        pool = [p for p in adp_pool if p["pid"] not in tk]
        choice = draft_history.pick_for_owner(owner_by_slot.get(owner(ov)), rnd, pool, tendencies, reg)
        if choice:
            made[ov] = choice["pid"]
            return True
        return False

    on_clock = first_unresolved()
    # Instant mode: resolve all opponent picks up to your turn right now.
    if not live_pace:
        while on_clock and owner(on_clock) != my_slot:
            if not ai_pick(on_clock):
                break
            on_clock = first_unresolved()

    done = on_clock is None
    pick_no = on_clock or total
    on_slot = owner(pick_no)
    is_my_turn = (not done) and on_slot == my_slot
    ai_on_clock = (not done) and not is_my_turn
    taken = taken_pids()
    board = {**kept_by_overall, **made}

    # ----- status + who-was-just-taken + board on TOP -----
    st.markdown(C.status_html(pick_no, n, slot_names[on_slot], is_my_turn), unsafe_allow_html=True)
    if made:
        lo = max(made)
        st.markdown(C.last_pick_html(lo, n, slot_names[owner(lo)], made[lo], reg),
                    unsafe_allow_html=True)
    if ai_on_clock:
        st.markdown(C.on_clock_html(slot_names[on_slot]), unsafe_allow_html=True)
    non_keeper = {ov: pid for ov, pid in board.items() if ov not in kept_by_overall}
    st.markdown(C.recent_ticker_html(non_keeper, reg), unsafe_allow_html=True)
    st.markdown('<div class="dr-h">Draft Board</div>', unsafe_allow_html=True)
    st.markdown(C.grid_html(board, n, slot_names, my_slot, on_clock or 0, rounds, reg,
                            kept_overalls=set(kept_by_overall), owner_fn=owner),
                unsafe_allow_html=True)

    my_pids = ([pid for ov, pid in made.items() if owner(ov) == my_slot]
               + [pid for ov, pid in kept_by_overall.items() if owner(ov) == my_slot])
    needs = C.open_needs(my_pids, ctx["roster_slots"], reg)
    recent_positions = [reg.meta(board[ov]).position for ov in sorted(board)[-6:]]
    pids_by_slot = {}
    for ov, pid in board.items():
        pids_by_slot.setdefault(owner(ov), []).append(pid)
    # your next pick AFTER the upcoming opponent run (skip back-to-back snake
    # picks so survival % reflects who'll be gone once opponents pick) — for survival %
    nxt = pick_no + 1
    while nxt <= total and owner(nxt) == my_slot:           # skip your consecutive picks
        nxt += 1
    while nxt <= total and (owner(nxt) != my_slot or nxt in kept_by_overall):
        nxt += 1
    next_user_pick = nxt if nxt <= total else None

    if done:
        st.success("Mock complete — your team is on the left. Reset to run another.")
        st.markdown('<div class="dr-h">Draft Recap</div>', unsafe_allow_html=True)
        st.markdown(C.draft_recap_html(pids_by_slot, my_slot, slot_names, ctx["roster_slots"],
                                       reg, ctx.get("value"), ctx["adp_rank"]),
                    unsafe_allow_html=True)
        return

    def draft(pid):
        made[on_clock] = str(pid)
        st.rerun()

    def show_card(pid):
        # clicking a board square no longer drafts — it opens the player card,
        # and the Draft button inside that card is what actually drafts.
        select_player(f"{mkey}_sp", pid)
        st.rerun()

    def toggle_queue(pid):
        q = [str(x) for x in st.session_state.get(qkey, [])]
        pid = str(pid)
        q.remove(pid) if pid in q else q.append(pid)
        st.session_state[qkey] = q
        st.rerun()

    queued = {str(x) for x in st.session_state.get(qkey, [])}

    left, right = st.columns([1.85, 1.15])
    with left, st.container(key="dr_panel_board"):
        tabs = st.tabs(["Rankings", "Teams", "Queue"])
        with tabs[0]:
            ranks_active = rankings_tab(
                ctx, key_prefix=mkey, taken=taken, queued=queued,
                is_my_turn=is_my_turn, pick_no=pick_no, next_pick=next_user_pick,
                on_click=show_card, on_star=toggle_queue,
                quick_draft=(draft if is_my_turn else None))
        with tabs[1]:
            st.markdown('<div class="dr-h dr-title">My Team</div>', unsafe_allow_html=True)
            st.markdown(C.roster_needs_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            st.markdown(C.bye_conflict_html(my_pids, ctx["byes"], reg), unsafe_allow_html=True)
            st.markdown(C.lineup_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            st.markdown(C.roster_strength_html(pids_by_slot, my_slot, slot_names, reg, ctx["adp_rank"]),
                        unsafe_allow_html=True)
            st.markdown('<div class="dr-h">League Board</div>', unsafe_allow_html=True)
            st.markdown(C.league_board_html(pids_by_slot, slot_names, my_slot,
                                            ctx["roster_slots"], reg, on_clock_slot=on_slot),
                        unsafe_allow_html=True)
        with tabs[2]:
            queue_manager(ctx, qkey, st.session_state.get(ctx["ranks_key"]) or ranks_active,
                          taken, reg, f"{mkey}_q", on_pick=show_card)

    board_avail = [r for r in ranks_active
                   if r.get("pid") and str(r["pid"]) not in taken]

    # opponent needs + the slots picking before your next turn (for run detection)
    need_map = C.needs_by_slot(pids_by_slot, slot_names, ctx["roster_slots"], reg)
    upcoming_slots = ([owner(k) for k in range(pick_no + 1, next_user_pick)]
                      if next_user_pick else [])

    with right, st.container(key="dr_panel_intel"):
        st.markdown(C.insights_html(board_avail, recent_positions, needs), unsafe_allow_html=True)
        st.markdown(C.run_alert_html(upcoming_slots, need_map, ctx.get("value"), taken, reg),
                    unsafe_allow_html=True)
        queue = [p for p in st.session_state.get(qkey, []) if str(p) not in taken]
        rec_row = next((r for r in board_avail if str(r["pid"]) == str(queue[0])), None) if queue else None
        rec_tag = "from your queue"
        if rec_row is None and board_avail:
            # roster-aware: best VORP weighted by your needs + positional scarcity
            from .. import value as V
            rec_row, _, rec_tag = V.best_pick(
                board_avail, ctx["value"], reg, needs, taken, next_pick=next_user_pick,
                survival_fn=lambda pid: C.survival_pct(
                    ctx["adp_rank"](reg.meta(pid).name, reg.meta(pid).position), next_user_pick),
                my_pids=my_pids, roster_slots=ctx["roster_slots"])
            if rec_row is None:
                rec_row = board_avail[0]
        if rec_row:
            rpm = reg.meta(rec_row["pid"])
            cue = "click any player to inspect" if is_my_turn else "your top target"
            st.markdown(f'<div class="dr-rec">★ <b>{rec_row["name"]}</b> ({rpm.position} · {rpm.team}) '
                        f'— <span class="why">{rec_tag}</span> · <i>{cue}</i></div>', unsafe_allow_html=True)
        preds = predict_upcoming(ctx, taken, pick_no, my_slot, kept_by_overall)
        predictor_widget(preds, slot_names, reg, n, f"{mkey}_pw", show_card)
        spotlight_panel(ctx, board_avail, reg, f"{mkey}_sp",
                        default_pid=(rec_row["pid"] if rec_row else None),
                        next_pick=next_user_pick, my_pids=my_pids, needs=needs, taken=taken,
                        draft_fn=(draft if is_my_turn else None))
        if ctx.get("value"):
            from .. import value as V
            steals, traps = V.steals_and_traps(board_avail, ctx["value"], reg, ctx["adp_rank"],
                                               pool_size=total)
            with st.expander("Steals & Traps", expanded=False):
                st.caption("Market value vs. ADP — click any player to open their card.")
                steals_traps_widget(steals, traps, reg, f"{mkey}_st", show_card)

    kept_note = (f" · {len(kept_pids)} keepers locked" if kept_pids else "")
    tnote = " · opponents draft by historical tendencies" if tendencies else ""
    st.caption("Click any player on the board to open their card, then Draft from the card. "
               f"Queue players to plan ahead. Undo rolls back your last pick.{kept_note}{tnote}")

    # ----- live pace: advance one opponent pick after rendering, with a slight delay -----
    if live_pace and ai_on_clock:
        time.sleep(_PICK_DELAY)
        if ai_pick(on_clock):
            st.rerun()
