"""Live Draft Assistant tab — polls the live draft (Sleeper or ESPN), overlays
keepers, and renders a war-room board on top with value/tier/run intelligence."""
from __future__ import annotations

import streamlit as st

from ..providers.espn import EspnAuthError
from . import components as C
from .widgets import (predict_upcoming, predictor_widget, queue_manager,
                      rankings_tab, select_player, spotlight_panel,
                      steals_traps_widget, suggestions_tab)


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

    owner = ctx["pick_owner_slot"]            # traded-pick-aware ownership
    total = n * rounds
    mankey = f"livemade_{ctx['league_key']}"

    # 'Focus' mode hides the setup row + the top-bar pills so more of the board fits
    focus = st.session_state.get("draft_focus", False)
    if focus:
        st.markdown(
            f'<style>.st-key-{akey}_setup{{display:none !important}}'
            '.tb-pill{display:none !important}'
            '[class*="dr_topbar"]{padding-top:2px !important;padding-bottom:2px !important}'
            '</style>', unsafe_allow_html=True)
    auto = reset = undo = False
    with st.container(key=f"{akey}_setup"):
        top = st.columns([1.5, 1.6, 1.1])
        me = top[0].selectbox("Your team", slot_names, key=f"{akey}_me")
        mode = top[1].radio("Draft source", ["Live sync", "Manual entry"], horizontal=True,
                            key=f"{akey}_mode",
                            help="Live sync = pull picks automatically from Sleeper/ESPN. "
                                 "Manual entry = tap the player each team takes (no sync "
                                 "needed — works for any draft room).")
        manual = mode == "Manual entry"
        if not manual:
            with top[2]:
                st.write("")
                auto = st.checkbox("Auto-refresh", key=f"{akey}_auto")
                st.button("Refresh", key=f"{akey}_refresh")
    my_slot = slot_names.index(me)
    act = st.columns([7, 1.3, 1, 1])
    act[1].toggle("Focus", key="draft_focus",
                  help="Hide the setup row & league pills to fit more of the board on screen.")
    if manual:
        reset = act[2].button("Reset", key=f"{akey}_mreset", use_container_width=True)
        undo = act[3].button("Undo", key=f"{akey}_mundo", use_container_width=True)

    # ----- gather picks from the chosen source into a common {overall: pid} map -----
    if manual:
        made = st.session_state.setdefault(mankey, {})
        if reset:
            made = {}
            st.session_state[mankey] = made
        if undo and made:
            del made[max(made)]                       # remove the most recent entry
        pick_pids = {ov: pid for ov, pid in made.items()}
        picks_exist = bool(made)
    else:
        if auto:
            try:
                from streamlit_autorefresh import st_autorefresh
                st_autorefresh(interval=12000, key=f"{akey}_tick")
            except Exception:  # noqa: BLE001
                st.caption("(install streamlit-autorefresh for auto; use Refresh for now)")
        try:
            picks = ctx["provider"].get_live_picks()
        except EspnAuthError as e:
            st.error(str(e))
            return
        except Exception as e:  # noqa: BLE001
            st.error(f"Couldn't read the live draft ({type(e).__name__}). Switch to "
                     "**Manual entry** above, or try Refresh.")
            return
        pick_pids = {p.overall: (p.player.sleeper_pid if p.player else None)
                     for p in picks if p.overall}
        picks_exist = bool(picks)

    # overlay keepers onto any empty keeper slots
    kept_at = set()
    for ov, pid in kept_overall.items():
        if ov not in pick_pids or not pick_pids[ov]:
            pick_pids[ov] = pid
            kept_at.add(ov)
    # everything below is derived from pick_pids + owner() — identical for both modes
    drafted = {str(pid) for pid in pick_pids.values() if pid} | {str(p) for p in kept_pids}
    pids_by_slot = {}
    for ov, pid in pick_pids.items():
        if pid:
            pids_by_slot.setdefault(owner(ov), []).append(pid)
    my_pids = [pid for ov, pid in pick_pids.items() if pid and owner(ov) == my_slot]

    # the pick on the clock: next overall not yet filled (keepers + entered picks)
    pick_no = 1
    while pick_no <= total and (pick_no in kept_overall or pick_pids.get(pick_no)):
        pick_no += 1
    pick_no = min(pick_no, total)
    on_slot = owner(pick_no)
    until = 0
    for k in range(pick_no, pick_no + total):
        if owner(k) == my_slot:
            until = k - pick_no
            break

    # ----- slim status header (the full board lives in the center 'Board' tab) -----
    st.markdown(C.status_html(pick_no, n, slot_names[on_slot], on_slot == my_slot,
                              picks_until_me=until), unsafe_allow_html=True)
    real_picks = {ov: pid for ov, pid in pick_pids.items() if pid and ov not in kept_at}

    needs = C.open_needs(my_pids, ctx["roster_slots"], reg)
    recent_positions = [reg.meta(pid).position
                        for ov, pid in sorted(real_picks.items())[-6:] if pid]
    qkey = f"queue_{ctx['league_key']}"
    # your next pick after the upcoming opponent run (skip back-to-back picks)
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

    def draft(pid):
        """Manual mode: record this player at the pick on the clock and advance."""
        made[pick_no] = str(pid)
        st.session_state[mankey] = made
        st.rerun()

    round_no = (pick_no - 1) // n + 1
    need_map = C.needs_by_slot(pids_by_slot, slot_names, ctx["roster_slots"], reg)

    left, center, right = st.columns([1.05, 1.9, 1.05])

    # ---- LEFT: rankings · queue · trends (buzz / steals / rookie reach) ----
    from .. import value as V
    with left, st.container(key="dr_panel_board"):
        ltabs = st.tabs(["Rankings", "Queue", "Trends", "League", "Scouting"])
        with ltabs[0]:
            ranks_active = rankings_tab(
                ctx, key_prefix=akey, taken=drafted, queued=queued, is_my_turn=True,
                pick_no=pick_no, next_pick=next_user_pick, on_click=_inspect,
                on_star=toggle_queue, quick_draft=(draft if manual else None),
                my_pids=my_pids)
        board_avail = [r for r in ranks_active
                       if r.get("pid") and str(r["pid"]) not in drafted]
        with ltabs[1]:
            queue_manager(ctx, qkey, st.session_state.get(ctx["ranks_key"]) or ranks_active,
                          drafted, reg, f"{akey}_q", on_pick=_inspect)
        with ltabs[2]:
            st.markdown(C.buzz_list_html(board_avail, reg, ctx.get("buzz")),
                        unsafe_allow_html=True)
            if ctx.get("value"):
                steals, traps = V.steals_and_traps(board_avail, ctx["value"], reg,
                                                   ctx["adp_rank"], pool_size=n * rounds)
                st.markdown('<div class="dr-h">Steals &amp; Traps</div>', unsafe_allow_html=True)
                st.caption("Market value vs. ADP — click any player to open their card.")
                steals_traps_widget(steals, traps, reg, f"{akey}_st", _inspect)
            rh = C.rookie_history_html(ctx.get("rookie_curve"), reg, ctx["adp_pool"])
            if rh:
                st.markdown('<div class="dr-h">📜 Rookie reach</div>', unsafe_allow_html=True)
                st.caption("Your league drafts rookies earlier than ADP — predictions reflect it.")
                st.markdown(rh, unsafe_allow_html=True)
        with ltabs[3]:
            st.markdown('<div class="dr-h dr-title">Roster Strength</div>', unsafe_allow_html=True)
            st.markdown(C.roster_strength_html(pids_by_slot, my_slot, slot_names, reg,
                                               ctx["adp_rank"]), unsafe_allow_html=True)
            st.markdown('<div class="dr-h">League Board</div>', unsafe_allow_html=True)
            st.markdown(C.league_board_html(pids_by_slot, slot_names, my_slot,
                                            ctx["roster_slots"], reg, on_clock_slot=on_slot),
                        unsafe_allow_html=True)
        with ltabs[4]:
            st.markdown(C.scouting_report_html(ctx.get("profiles", {}), slot_names,
                                               ctx["owner_by_slot"], my_slot,
                                               on_clock_slot=on_slot, round_no=round_no),
                        unsafe_allow_html=True)

    upcoming_slots = ([owner(k) for k in range(pick_no + 1, next_user_pick)]
                      if next_user_pick else [])

    queue = [p for p in st.session_state.get(qkey, []) if str(p) not in drafted]
    rec_row = next((r for r in board_avail if str(r["pid"]) == str(queue[0])), None) if queue else None
    why = "from your queue"
    if rec_row is None and board_avail:
        rec_row, _, why = V.best_pick(
            board_avail, ctx["value"], reg, needs, drafted, next_pick=next_user_pick,
            survival_fn=lambda pid: C.survival_pct(
                ctx["adp_rank"](reg.meta(pid).name, reg.meta(pid).position), next_user_pick),
            my_pids=my_pids, roster_slots=ctx["roster_slots"])
        if rec_row is None:
            rec_row = board_avail[0]

    # ---- CENTER: Suggestions (focal) · Board, with the Player Spotlight below ----
    with center, st.container(key="dr_panel_boardc"):
        st.markdown(C.run_banner_html(board_avail, recent_positions, next_user_pick,
                                      ctx["adp_rank"], reg, needs=needs),
                    unsafe_allow_html=True)
        if rec_row:
            tpm = reg.meta(rec_row["pid"])
            st.markdown(f'<div class="dr-rec">★ <b>{rec_row["name"]}</b> ({tpm.position} · {tpm.team}) '
                        f'— <span class="why">{why}</span> · <i>click a player in the list to inspect</i></div>',
                        unsafe_allow_html=True)
        spotlight_panel(ctx, board_avail, reg, f"{akey}_sp",
                        default_pid=(rec_row["pid"] if rec_row else None),
                        next_pick=next_user_pick, my_pids=my_pids, needs=needs, taken=drafted,
                        draft_fn=(draft if manual else None),
                        upcoming_slots=upcoming_slots, need_map=need_map, round_no=round_no)
        ctabs = st.tabs(["Suggestions", "Cheat Sheet", "Board"])
        with ctabs[0]:
            st.markdown(C.act_now_html(board_avail, next_user_pick, ctx["adp_rank"], reg,
                                       ctx.get("value")), unsafe_allow_html=True)
            suggestions_tab(ctx, key_prefix=akey, ranks=ranks_active, taken=drafted,
                            my_pids=my_pids, needs=needs, next_pick=next_user_pick,
                            pick_no=pick_no, on_click=_inspect, on_star=toggle_queue,
                            quick_draft=(draft if manual else None), queued=queued)
        with ctabs[1]:
            st.markdown(C.cheat_sheet_html(
                board_avail, reg,
                survival_fn=lambda pid: C.survival_pct(
                    ctx["adp_rank"](reg.meta(pid).name, reg.meta(pid).position),
                    next_user_pick)), unsafe_allow_html=True)
        with ctabs[2]:
            st.markdown(C.recent_ticker_html(real_picks, reg), unsafe_allow_html=True)
            st.markdown(C.grid_html(pick_pids, n, slot_names, my_slot, pick_no, rounds, reg,
                                    kept_overalls=kept_at, owner_fn=owner), unsafe_allow_html=True)

    # ---- RIGHT: live Picks feed (with predicted picks folded in) + draft intel ----
    preds = predict_upcoming(ctx, drafted, pick_no, my_slot, kept_overall,
                             pids_by_slot=pids_by_slot)
    pred_map = {ov: pid for ov, _s, pid in preds}
    with right, st.container(key="dr_panel_intel"):
        rtabs = st.tabs(["Pick Predictor", "My Team"])
        with rtabs[0]:
            st.markdown(C.insights_html(board_avail, recent_positions, needs), unsafe_allow_html=True)
            st.markdown(C.picks_feed_html(pick_pids, pick_no, n, rounds, slot_names, my_slot, owner,
                                          need_map, reg, kept_overalls=kept_at,
                                          predictions=pred_map, queued=queued),
                        unsafe_allow_html=True)
        with rtabs[1]:
            st.markdown(C.roster_needs_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            st.markdown(C.roster_balance_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            st.markdown(C.bye_conflict_html(my_pids, ctx["byes"], reg), unsafe_allow_html=True)
            st.markdown(C.lineup_html(my_pids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            if ctx.get("value") and board_avail:
                my_left = [k for k in range(pick_no, n * rounds + 1) if owner(k) == my_slot]
                plan = V.draft_plan(my_pids, ctx["roster_slots"], min(4, len(my_left)),
                                    board_avail, ctx["value"], reg, taken=drafted)
                st.markdown(C.draft_plan_html(plan), unsafe_allow_html=True)
            st.markdown(C.run_alert_html(upcoming_slots, need_map, ctx.get("value"), drafted, reg,
                                         profiles=ctx.get("profiles"),
                                         owner_by_slot=ctx["owner_by_slot"], round_no=round_no),
                        unsafe_allow_html=True)

    kept_note = (f" {len(kept_pids)} keepers are pre-marked." if kept_pids else "")
    if manual:
        st.caption("Manual entry — tap the player each team takes (the green **Draft** "
                   "button assigns him to whoever's on the clock). Undo removes the last "
                   "pick." + kept_note)
    elif not picks_exist:
        st.caption("Waiting on the draft to start — picks will stream in here." + kept_note +
                   " Toggle auto-refresh (or hit Refresh) once it's live. No draft on this "
                   "platform? Switch to **Manual entry** above.")
    else:
        st.caption("Live — best available is your board, drafted + kept players removed, "
                   "★ = top pick · ▼ = falling value · tier-cliff and position-run alerts show on the right.")
