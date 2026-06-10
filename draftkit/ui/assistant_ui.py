"""Live Draft Assistant tab — polls the live draft (Sleeper or ESPN) and renders
the same FantasyPros-style board from a normalized Pick list."""
from __future__ import annotations

import streamlit as st

from ..providers.espn import EspnAuthError
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
    akey = f"live_{ctx['league_key']}"

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

    drafted = {p.player.sleeper_pid for p in picks if p.player and p.player.sleeper_pid}
    my_pids = [p.player.sleeper_pid for p in picks
               if p.slot == my_slot and p.player and p.player.sleeper_pid]

    pick_no = len(picks) + 1
    on_slot = C.snake(n)(pick_no - 1)
    st.markdown(C.status_html(pick_no, n, slot_names[on_slot], on_slot == my_slot),
                unsafe_allow_html=True)

    left, right = st.columns([1, 2])
    with left:
        st.markdown('<div class="dr-h">🧢 My Team</div>', unsafe_allow_html=True)
        st.markdown(C.lineup_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
    with right:
        st.markdown('<div class="dr-h">🎯 Best Available — Your Board</div>', unsafe_allow_html=True)
        st.markdown(C.avail_html(C.filter_pos(ranks, pos_f, reg), drafted, reg, ctx["adp_rank"]),
                    unsafe_allow_html=True)

    with st.expander("📋 Draft Board"):
        cell = {p.overall: (p.player.name.split()[-1] if p.player else p.raw_id)
                for p in picks if p.overall}
        st.markdown(C.grid_html(cell, n, slot_names, my_slot, pick_no, rounds),
                    unsafe_allow_html=True)
    if not picks:
        st.caption("Waiting on the draft to start — picks will stream in here. "
                   "Toggle auto-refresh (or hit Refresh) once it's live.")
    else:
        st.caption("Live from your draft — best available is your UDK board, tier-colored, "
                   "drafted players removed, ★ = top recommendation.")
