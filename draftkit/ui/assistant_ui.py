"""Live Draft Assistant tab — polls the live draft (Sleeper or ESPN), overlays
keepers, and renders a war-room board on top with value/tier/run intelligence."""
from __future__ import annotations

import streamlit as st

from ..providers.espn import EspnAuthError
from . import components as C
from .widgets import (predict_upcoming, predictor_widget, queue_manager,
                      rankings_tab, select_player, spotlight_panel, steals_traps_widget)


def render(ctx) -> None:
    reg = ctx["registry"]
    ranks = st.session_state.get(ctx["ranks_key"])
    if not ranks:
        st.info("Add your rankings on the **My Rankings** tab first.")
        return

    slot_names = ctx["slot_names"]
    n = len(slot_names)
    rounds = ctx["meta"].draft_rounds
    akey = f"live_{ctx['league_key']}"
    kept_overall = ctx["keepers"]["by_overall"]
    kept_pids = ctx["keepers"]["kept_pids"]

    top = st.columns([2, 1])
    me = top[0].selectbox("Your team", slot_names, key=f"{akey}_me")
    with top[1]:
        st.write("")
        auto = st.checkbox("Auto-refresh", key=f"{akey}_auto")
        st.button("Refresh", key=f"{akey}_refresh")
    # Position filtering lives in the Best Available panel ("By position" view).
    pos_f = "All"
    if auto:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=12000, key=f"{akey}_tick")
        except Exception:  # noqa: BLE001
            st.caption("(install streamlit-autorefresh for auto; use the button for now)")

    my_slot = slot_names.index(me)
    try:
        picks = ctx["provider"].get_live_picks()
    except EspnAuthError as e:
        st.error(str(e))
        return
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't read the live draft ({type(e).__name__}). Try Refresh.")
        return

    # Board = real picks; overlay keepers on any empty keeper slots.
    pick_pids = {p.overall: (p.player.sleeper_pid if p.player else None)
                 for p in picks if p.overall}
    kept_at = set()
    for ov, pid in kept_overall.items():
        if ov not in pick_pids or not pick_pids[ov]:
            pick_pids[ov] = pid
            kept_at.add(ov)
    drafted = {p.player.sleeper_pid for p in picks if p.player and p.player.sleeper_pid}
    drafted |= set(kept_pids)
    my_pids = [p.player.sleeper_pid for p in picks
               if p.slot == my_slot and p.player and p.player.sleeper_pid]
    owner = ctx["pick_owner_slot"]            # traded-pick-aware ownership
    my_pids += [pid for ov, pid in kept_overall.items()
                if owner(ov) == my_slot and pid not in my_pids]

    pick_no = len(picks) + 1
    on_slot = owner(pick_no)
    until = 0
    for k in range(pick_no, pick_no + n * rounds):
        if owner(k) == my_slot:
            until = k - pick_no
            break

    # ----- status + board on TOP -----
    st.markdown(C.status_html(pick_no, n, slot_names[on_slot], on_slot == my_slot,
                              picks_until_me=until), unsafe_allow_html=True)
    real_picks = {p.overall: p.player.sleeper_pid for p in picks
                  if p.player and p.player.sleeper_pid}
    st.markdown(C.recent_ticker_html(real_picks, reg), unsafe_allow_html=True)
    st.markdown('<div class="dr-h">Draft Board</div>', unsafe_allow_html=True)
    st.markdown(C.grid_html(pick_pids, n, slot_names, my_slot, pick_no, rounds, reg,
                            kept_overalls=kept_at, owner_fn=owner), unsafe_allow_html=True)

    needs = C.open_needs(my_pids, ctx["roster_slots"], reg)
    recent_positions = [p.player.position for p in sorted(picks, key=lambda x: x.overall)[-6:]
                        if p.player]
    qkey = f"queue_{ctx['league_key']}"
    pids_by_slot = {}
    for p in picks:
        if p.player and p.player.sleeper_pid:
            pids_by_slot.setdefault(p.slot, []).append(p.player.sleeper_pid)
    for ov, pid in kept_overall.items():
        pids_by_slot.setdefault(owner(ov), []).append(pid)
    # your next pick after the upcoming opponent run (skip back-to-back picks)
    total = n * rounds
    nxt = pick_no
    while nxt <= total and owner(nxt) == my_slot:
        nxt += 1
    while nxt <= total and owner(nxt) != my_slot:
        nxt += 1
    next_user_pick = nxt if nxt <= total else None

    queued = {str(x) for x in st.session_state.get(qkey, [])}

    def _inspect(pid):
        select_player(f"{akey}_sp", pid)
        st.rerun()

    def toggle_queue(pid):
        q = [str(x) for x in st.session_state.get(qkey, [])]
        pid = str(pid)
        q.remove(pid) if pid in q else q.append(pid)
        st.session_state[qkey] = q
        st.rerun()

    left, right = st.columns([1.85, 1.15])
    with left, st.container(key="dr_panel_board"):
        tabs = st.tabs(["Rankings", "Teams", "Queue"])
        with tabs[0]:
            ranks_active = rankings_tab(
                ctx, key_prefix=akey, taken=drafted, queued=queued, is_my_turn=True,
                pick_no=pick_no, next_pick=next_user_pick, on_click=_inspect,
                on_star=toggle_queue, quick_draft=None)
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
                          drafted, reg, f"{akey}_q", on_pick=_inspect)

    board_avail = [r for r in ranks_active
                   if r.get("pid") and str(r["pid"]) not in drafted]
    need_map = C.needs_by_slot(pids_by_slot, slot_names, ctx["roster_slots"], reg)
    upcoming_slots = ([owner(k) for k in range(pick_no + 1, next_user_pick)]
                      if next_user_pick else [])

    with right, st.container(key="dr_panel_intel"):
        st.markdown(C.insights_html(board_avail, recent_positions, needs), unsafe_allow_html=True)
        st.markdown(C.run_alert_html(upcoming_slots, need_map, ctx.get("value"), drafted, reg),
                    unsafe_allow_html=True)
        queue = [p for p in st.session_state.get(qkey, []) if str(p) not in drafted]
        rec_row = next((r for r in board_avail if str(r["pid"]) == str(queue[0])), None) if queue else None
        why = "from your queue"
        if rec_row is None and board_avail:
            from .. import value as V
            rec_row, _, why = V.best_pick(
                board_avail, ctx["value"], reg, needs, drafted, next_pick=next_user_pick,
                survival_fn=lambda pid: C.survival_pct(
                    ctx["adp_rank"](reg.meta(pid).name, reg.meta(pid).position), next_user_pick),
                my_pids=my_pids, roster_slots=ctx["roster_slots"])
            if rec_row is None:
                rec_row = board_avail[0]
        if rec_row:
            tpm = reg.meta(rec_row["pid"])
            st.markdown(f'<div class="dr-rec">★ <b>{rec_row["name"]}</b> ({tpm.position} · {tpm.team}) '
                        f'— <span class="why">{why}</span></div>', unsafe_allow_html=True)
        spotlight_panel(ctx, board_avail, reg, f"{akey}_sp",
                        default_pid=(rec_row["pid"] if rec_row else None),
                        next_pick=next_user_pick, my_pids=my_pids, needs=needs, taken=drafted)

        preds = predict_upcoming(ctx, drafted, pick_no, my_slot, kept_overall)
        predictor_widget(preds, slot_names, reg, n, f"{akey}_pw", _inspect)
        if ctx.get("value"):
            from .. import value as V
            steals, traps = V.steals_and_traps(board_avail, ctx["value"], reg, ctx["adp_rank"],
                                               pool_size=n * rounds)
            with st.expander("Steals & Traps", expanded=False):
                st.caption("Market value vs. ADP — click any player to open their card.")
                steals_traps_widget(steals, traps, reg, f"{akey}_st", _inspect)

    if not picks:
        kept_note = (f" {len(kept_pids)} keepers are pre-marked." if kept_pids else "")
        st.caption("Waiting on the draft to start — picks will stream in here." + kept_note +
                   " Toggle auto-refresh (or hit Refresh) once it's live.")
    else:
        st.caption("Live — best available is your UDK board, drafted+kept players removed, "
                   "★ = top pick · ▼ = falling value · tier-cliff and position-run alerts show on the right.")
