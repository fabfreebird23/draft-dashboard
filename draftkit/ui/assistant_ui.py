"""Live Draft Assistant tab — polls the live draft (Sleeper or ESPN), overlays
keepers, and renders a war-room board on top with value/tier/run intelligence."""
from __future__ import annotations

import streamlit as st

from ..providers.espn import EspnAuthError
from . import components as C
from .widgets import queue_manager


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

    top = st.columns([2, 1, 1])
    me = top[0].selectbox("Your team", slot_names, key=f"{akey}_me")
    pos_f = top[1].selectbox("Position", ["All", "QB", "RB", "WR", "TE", "FLEX"], key=f"{akey}_pos")
    with top[2]:
        st.write("")
        auto = st.checkbox("Auto-refresh", key=f"{akey}_auto")
        st.button("🔄 Refresh", key=f"{akey}_refresh")
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
    my_pids += [pid for ov, pid in kept_overall.items()
                if C.snake(n)(ov - 1) == my_slot and pid not in my_pids]

    pick_no = len(picks) + 1
    snake = C.snake(n)
    on_slot = snake(pick_no - 1)
    until = 0
    for k in range(pick_no - 1, pick_no - 1 + n * rounds):
        if snake(k) == my_slot:
            until = k - (pick_no - 1)
            break

    # ----- status + board on TOP -----
    st.markdown(C.status_html(pick_no, n, slot_names[on_slot], on_slot == my_slot,
                              picks_until_me=until), unsafe_allow_html=True)
    real_picks = {p.overall: p.player.sleeper_pid for p in picks
                  if p.player and p.player.sleeper_pid}
    st.markdown(C.recent_ticker_html(real_picks, reg), unsafe_allow_html=True)
    st.markdown('<div class="dr-h">📋 Draft Board</div>', unsafe_allow_html=True)
    st.markdown(C.grid_html(pick_pids, n, slot_names, my_slot, pick_no, rounds, reg,
                            kept_overalls=kept_at), unsafe_allow_html=True)

    needs = C.open_needs(my_pids, ctx["roster_slots"], reg)
    recent_positions = [p.player.position for p in sorted(picks, key=lambda x: x.overall)[-6:]
                        if p.player]
    qkey = f"queue_{ctx['league_key']}"
    # roster value per team (live picks + keepers)
    pids_by_slot = {}
    for p in picks:
        if p.player and p.player.sleeper_pid:
            pids_by_slot.setdefault(p.slot, []).append(p.player.sleeper_pid)
    for ov, pid in kept_overall.items():
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
        board = C.filter_pos(ranks, pos_f, reg)
        board_avail = [r for r in board if r.get("pid") and str(r["pid"]) not in drafted]
        st.markdown(C.insights_html(board_avail, recent_positions, needs), unsafe_allow_html=True)
        # recommendation prefers your top queued available player
        queue = [p for p in st.session_state.get(qkey, []) if str(p) not in drafted]
        rec_row = next((r for r in board_avail if str(r["pid"]) == str(queue[0])), None) if queue else None
        if rec_row is None and board_avail:
            rec_row = board_avail[0]
        if rec_row:
            tpm = reg.meta(rec_row["pid"])
            why = ("from your queue" if (queue and str(rec_row["pid"]) == str(queue[0]))
                   else C.rec_reason(rec_row, reg, ctx["adp_rank"], pick_no, needs))
            st.markdown(f'<div class="dr-rec">★ <b>{rec_row["name"]}</b> ({tpm.position} · {tpm.team}) '
                        f'— <span class="why">{why}</span></div>', unsafe_allow_html=True)
        queue_manager(ctx, qkey, ranks, drafted, reg, f"{akey}_q")
        head = st.columns([3, 2])
        head[0].markdown('<div class="dr-h" style="margin:2px 0;">🎯 Best Available — Your Board</div>',
                         unsafe_allow_html=True)
        view = head[1].radio("view", ["By position", "Overall"], horizontal=True,
                             key=f"{akey}_view", label_visibility="collapsed")
        if view == "By position":
            st.markdown(C.by_position_html(board_avail, reg, ctx["adp_rank"], ctx["pos_rank"],
                                           pick_no, pos_tier=ctx["pos_tier"]), unsafe_allow_html=True)
        else:
            search = st.text_input("🔎 Search the board", key=f"{akey}_search",
                                   placeholder="Filter by name or team…", label_visibility="collapsed")
            st.markdown(C.avail_html(C.filter_search(board, search, reg), drafted, reg,
                                     ctx["adp_rank"], pos_rank=ctx["pos_rank"], current_pick=pick_no),
                        unsafe_allow_html=True)

    if not picks:
        kept_note = (f" {len(kept_pids)} keepers are pre-marked." if kept_pids else "")
        st.caption("Waiting on the draft to start — picks will stream in here." + kept_note +
                   " Toggle auto-refresh (or hit Refresh) once it's live.")
    else:
        st.caption("Live — best available is your UDK board, drafted+kept players removed, "
                   "★ = top pick, ▼ = falling value, ⚠ = tier cliff, 🔥 = position run.")
