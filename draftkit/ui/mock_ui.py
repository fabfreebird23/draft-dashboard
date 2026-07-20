"""Mock Draft tab — history-aware AI opponents, locked keepers, a pick queue,
bye-week warnings, roster-strength ranking, a by-position cheat sheet, and a
war-room of value/tier/run intelligence. Board on top."""
from __future__ import annotations

import time

import streamlit as st

from .. import draft_history
from . import components as C
from .widgets import (predict_upcoming, predictor_widget, queue_manager,
                      rankings_tab, select_player, spotlight_panel,
                      steals_traps_widget, suggestions_tab)

_PICK_DELAY = 0.7  # seconds between AI picks in live-pace mode
_AI_JITTER = 0.15  # per-pick randomness so every mock draft plays out differently


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
    # Keepers: the dashboard placements, or — when the toggle is on — those PLUS
    # predicted keepers for teams that haven't entered any on the keeper dashboard.
    if st.session_state.get(f"{mkey}_predictkp", False):
        from .. import keepers as _K, config as _cfg
        keepers_raw = ctx.get("keepers_raw") or {}
        have_kp = {str(o) for o, kl in keepers_raw.items() if kl}
        predicted = _K.predict_keepers(ctx["meta"].league_id, ctx.get("value"),
                                       _cfg.current_season(), have_kp,
                                       registry=ctx["registry"], rounds=rounds)
        _pl = _K.build_placements({**keepers_raw, **predicted}, ctx["owner_slot"],
                                  n, rounds, pick_owner_slot=ctx["pick_owner_slot"])
        kept_by_overall, kept_pids = _pl["by_overall"], _pl["kept_pids"]
        st.session_state[f"{mkey}_npred"] = sum(len(v) for v in predicted.values())
    else:
        kept_by_overall = ctx["keepers"]["by_overall"]
        kept_pids = ctx["keepers"]["kept_pids"]
    tendencies = ctx["tendencies"]
    owner_by_slot = ctx["owner_by_slot"]
    adp_pool = ctx.get("ai_pool") or ctx["adp_pool"]   # rookie-boosted for the AI
    owner = ctx["pick_owner_slot"]   # who owns each overall pick (handles traded picks)
    total = n * rounds

    from .. import value as V
    # ---- setup/config tucked into a gear dropdown; only actions stay on top ----
    ctrl = st.columns([0.5, 1.6, 1.5, 1.4, 1, 1])
    with ctrl[0].popover("⚙", use_container_width=True):
        me = st.selectbox("Your draft slot", slot_names, key=f"{mkey}_slot")
        mode = st.radio("Opponents", ["AI mock", "Manual / live"], horizontal=True,
                        key=f"{mkey}_mode",
                        help="AI mock = opponents auto-draft from their tendencies. "
                             "Manual / live = you enter every pick yourself.")
        live_pace = st.checkbox("Live pace", value=True, key=f"{mkey}_pace",
                                disabled=(mode == "Manual / live"),
                                help="ON: opponents pick one at a time with a short delay. "
                                     "OFF: opponents resolve instantly up to your pick.")
        st.toggle("Predict missing keepers", key=f"{mkey}_predictkp",
                  help="For teams without dashboard keepers, predict their likely keepers "
                       "so the board reflects a realistic keeper draft.")
        npred = st.session_state.get(f"{mkey}_npred", 0)
        if st.session_state.get(f"{mkey}_predictkp", False) and npred:
            st.caption(f"+{npred} predicted keepers")
        strategy = st.selectbox(
            "Strategy", V.STRATEGIES, key=f"{mkey}_strategy",
            help="Biases the ★ recommendation and Suggestions toward a plan "
                 "(Hero/Zero/Robust RB, Elite TE, Late-Round QB, or pure value).")
    manual = mode == "Manual / live"
    autopick = ctrl[2].button("Pick for me", key=f"{mkey}_autome", use_container_width=True,
                              disabled=manual,
                              help="Let the AI make YOUR current pick from your draft tendencies.")
    sim_end = ctrl[3].button("Sim to end", key=f"{mkey}_simend", use_container_width=True,
                             disabled=manual,
                             help="Auto-draft every remaining pick straight to the recap.")
    reset = ctrl[4].button("Reset", key=f"{mkey}_reset", use_container_width=True)
    undo = ctrl[5].button("Undo", key=f"{mkey}_undo", use_container_width=True)
    pos_f = "All"

    my_slot = slot_names.index(me)
    state = st.session_state.get(mkey)
    if reset or not state or "made" not in state or state.get("slot") != my_slot:
        state = {"made": {}, "slot": my_slot}
        st.session_state[mkey] = state
    made = state["made"]

    if undo and made:
        if manual:
            del made[max(made)]                       # roll back the most recent entry
        else:
            # roll back to your last pick: erase your last selection AND every
            # opponent pick that came after it, so you're back on the clock.
            mine = [ov for ov in made if owner(ov) == my_slot]
            if mine:
                cut = max(mine)
                for ov in [o for o in list(made) if o >= cut]:
                    del made[ov]

    def taken_pids():
        return set(made.values()) | set(kept_pids)

    def first_unresolved():
        ov = 1
        while ov <= total and (ov in kept_by_overall or ov in made):
            ov += 1
        return ov if ov <= total else None

    def _slot_pos_counts(slot):
        """This owner's current roster as position→count (made picks + keepers),
        so the AI respects QB/TE caps."""
        rc = {}
        for o, pid in made.items():
            if owner(o) == slot:
                p = reg.meta(pid).position
                rc[p] = rc.get(p, 0) + 1
        for o, pid in kept_by_overall.items():
            if owner(o) == slot:
                p = reg.meta(pid).position
                rc[p] = rc.get(p, 0) + 1
        return rc

    def _slot_pool(slot):
        """The draft board this AI manager uses — their assigned ranking source
        (Scouting tab) or the consensus default."""
        src = st.session_state.get(f"aisrc_{ctx['league_key']}_{slot}", "Consensus")
        return ctx.get("source_pools", {}).get(src) or adp_pool

    def ai_pick(ov):
        rnd = (ov - 1) // n + 1
        tk = taken_pids()
        pool = [p for p in _slot_pool(owner(ov)) if p["pid"] not in tk]
        choice = draft_history.pick_for_owner(owner_by_slot.get(owner(ov)), rnd, pool,
                                              tendencies, reg, jitter=_AI_JITTER,
                                              roster_counts=_slot_pos_counts(owner(ov)))
        if choice:
            made[ov] = choice["pid"]
            return True
        return False

    on_clock = first_unresolved()
    # Instant mode: resolve all opponent picks up to your turn right now (AI only).
    if not live_pace and not manual:
        while on_clock and owner(on_clock) != my_slot:
            if not ai_pick(on_clock):
                break
            on_clock = first_unresolved()

    done = on_clock is None
    pick_no = on_clock or total
    on_slot = owner(pick_no)
    is_my_turn = (not done) and on_slot == my_slot
    # ---- Auto-draft controls (AI fills picks for you) ----
    if sim_end and not manual:                 # auto-draft EVERYONE to the end
        ov, guard = first_unresolved(), 0
        while ov and guard <= total + 2:
            if not ai_pick(ov):
                break
            ov = first_unresolved()
            guard += 1
        st.rerun()
    if autopick and is_my_turn and not manual:  # AI makes just your current pick
        ai_pick(on_clock)
        st.rerun()
    # Manual/live: YOU enter every pick, so the board is draftable on every pick
    # (whoever is on the clock); no AI ever fires.
    can_draft = (not done) and (is_my_turn or manual)
    ai_on_clock = (not done) and not is_my_turn and not manual
    taken = taken_pids()
    board = {**kept_by_overall, **made}

    # ----- slim status header (the full board lives in the center 'Board' tab) -----
    st.markdown(C.status_html(pick_no, n, slot_names[on_slot], is_my_turn), unsafe_allow_html=True)
    non_keeper = {ov: pid for ov, pid in board.items() if ov not in kept_by_overall}

    my_pids = ([pid for ov, pid in made.items() if owner(ov) == my_slot]
               + [pid for ov, pid in kept_by_overall.items() if owner(ov) == my_slot])
    needs = C.open_needs(my_pids, ctx["roster_slots"], reg)
    recent_positions = [reg.meta(board[ov]).position for ov in sorted(board)[-6:]]
    pids_by_slot = {s: [] for s in range(n)}   # every team present (even 0-pick teams)
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
        st.success("Mock complete — review the full board or your recap below. "
                   "Reset to run another.")
        csv_str = C.draft_csv(board, n, rounds, slot_names, owner, reg,
                              ctx["adp_rank"], set(kept_by_overall), ctx.get("value"))
        st.download_button("Export full draft (CSV)", csv_str,
                           file_name="mock_draft.csv", mime="text/csv")
        # let the user flip back to the full draft board after the draft finishes
        fview = st.radio("Final view", ["Draft board", "Recap & grade"], horizontal=True,
                         key=f"{mkey}_finalview", label_visibility="collapsed")
        if fview == "Draft board":
            st.markdown(C.grid_html(board, n, slot_names, my_slot, 0, rounds, reg,
                                    kept_overalls=set(kept_by_overall), owner_fn=owner),
                        unsafe_allow_html=True)
        else:
            if ctx.get("value"):
                from .. import value as V
                grade = V.grade_team(my_pids, ctx["value"], reg, ctx["roster_slots"], n)
                st.markdown(C.draft_grade_html(grade, my_pids, ctx["roster_slots"], reg),
                            unsafe_allow_html=True)
            st.markdown('<div class="dr-h">Draft Recap</div>', unsafe_allow_html=True)
            st.markdown(C.draft_recap_html(pids_by_slot, my_slot, slot_names,
                                           ctx["roster_slots"], reg, ctx.get("value"),
                                           ctx["adp_rank"]), unsafe_allow_html=True)
        return

    def draft(pid):
        made[on_clock] = str(pid)
        st.rerun()

    def show_card(pid):
        # deep player card removed — the compact rows already carry ADP/bye/value,
        # so a player-name click is a no-op; the Draft/★ buttons carry the actions.
        return
        st.rerun()

    def toggle_queue(pid):
        q = [str(x) for x in st.session_state.get(qkey, [])]
        pid = str(pid)
        q.remove(pid) if pid in q else q.append(pid)
        st.session_state[qkey] = q
        st.rerun()

    queued = {str(x) for x in st.session_state.get(qkey, [])}
    round_no = (pick_no - 1) // n + 1
    need_map = C.needs_by_slot(pids_by_slot, slot_names, ctx["roster_slots"], reg)

    # ---- draft board: static, full width, pinned on top ----
    with st.container(key="dr_board_top"):
        if made:
            _lo = max(made)
            st.markdown(C.last_pick_html(_lo, n, slot_names[owner(_lo)], made[_lo], reg),
                        unsafe_allow_html=True)
        if ai_on_clock:
            st.markdown(C.on_clock_html(slot_names[on_slot]), unsafe_allow_html=True)
        st.markdown(C.grid_html(board, n, slot_names, my_slot, on_clock or 0, rounds, reg,
                                kept_overalls=set(kept_by_overall), owner_fn=owner),
                    unsafe_allow_html=True)
        # snaps the (freely-scrollable) board back to the current pick after every
        # draft action — see current_pick_scroll_html's docstring for why this has
        # to be a components.html iframe rather than plain st.markdown.
        st.components.v1.html(C.current_pick_scroll_html(), height=0)

    left, center, right = st.columns([1.05, 1.9, 1.05])

    # ---- LEFT: rankings · queue · trends (buzz / steals / rookie reach) ----
    from .. import value as V
    with left, st.container(key="dr_panel_board"):
        ltabs = st.tabs(["Rankings", "Cheat Sheet", "Queue", "Trends", "League", "Scouting"])
        with ltabs[0]:
            ranks_active = rankings_tab(
                ctx, key_prefix=mkey, taken=taken, queued=queued,
                is_my_turn=can_draft, pick_no=pick_no, next_pick=next_user_pick,
                on_click=show_card, on_star=toggle_queue,
                quick_draft=(draft if can_draft else None), my_pids=my_pids)
        board_avail = [r for r in ranks_active
                       if r.get("pid") and str(r["pid"]) not in taken]
        with ltabs[1]:
            st.markdown(C.cheat_sheet_html(
                board_avail, reg,
                survival_fn=lambda pid: C.survival_pct(
                    ctx["adp_rank"](reg.meta(pid).name, reg.meta(pid).position),
                    next_user_pick)), unsafe_allow_html=True)
        with ltabs[2]:
            queue_manager(ctx, qkey, st.session_state.get(ctx["ranks_key"]) or ranks_active,
                          taken, reg, f"{mkey}_q", on_pick=show_card)
        with ltabs[3]:
            st.markdown(C.buzz_list_html(board_avail, reg, ctx.get("buzz")),
                        unsafe_allow_html=True)
            if ctx.get("value"):
                steals, traps = V.steals_and_traps(board_avail, ctx["value"], reg,
                                                   ctx["adp_rank"], pool_size=total)
                st.markdown('<div class="dr-h">Steals &amp; Traps</div>', unsafe_allow_html=True)
                st.caption("Market value vs. ADP — click any player to open their card.")
                steals_traps_widget(steals, traps, reg, f"{mkey}_st", show_card)
            rh = C.rookie_history_html(ctx.get("rookie_curve"), reg, ctx["adp_pool"])
            if rh:
                st.markdown('<div class="dr-h">Rookie reach</div>', unsafe_allow_html=True)
                st.caption("Your league drafts rookies earlier than ADP — the mock reflects it.")
                st.markdown(rh, unsafe_allow_html=True)
        with ltabs[4]:
            st.markdown('<div class="dr-h dr-title">Roster Strength</div>', unsafe_allow_html=True)
            st.markdown(C.roster_strength_html(pids_by_slot, my_slot, slot_names, reg,
                                               ctx["adp_rank"]), unsafe_allow_html=True)
            st.markdown('<div class="dr-h">League Board</div>', unsafe_allow_html=True)
            st.markdown(C.league_board_html(pids_by_slot, slot_names, my_slot,
                                            ctx["roster_slots"], reg, on_clock_slot=on_slot),
                        unsafe_allow_html=True)
        with ltabs[5]:
            with st.expander("AI draft boards — set each manager's ranking source"):
                st.caption("Pick which board each AI manager drafts from. "
                           "Sleeper doesn't publish ADP, so Underdog (best-ball) stands in.")
                for s in range(n):
                    if s == my_slot:
                        continue
                    st.selectbox(slot_names[s], ctx["ai_sources"],
                                 key=f"aisrc_{ctx['league_key']}_{s}",
                                 help="The board this manager drafts off in the mock.")
            st.markdown(C.scouting_report_html(ctx.get("profiles", {}), slot_names,
                                               owner_by_slot, my_slot, on_clock_slot=on_slot,
                                               round_no=round_no), unsafe_allow_html=True)

    upcoming_slots = ([owner(k) for k in range(pick_no + 1, next_user_pick)]
                      if next_user_pick else [])

    # top recommendation (drives the spotlight default + the ★ line)
    queue = [p for p in st.session_state.get(qkey, []) if str(p) not in taken]
    rec_row = next((r for r in board_avail if str(r["pid"]) == str(queue[0])), None) if queue else None
    rec_tag = "from your queue"
    if rec_row is None and board_avail:
        rec_row, _, rec_tag = V.best_pick(
            board_avail, ctx["value"], reg, needs, taken, next_pick=next_user_pick,
            survival_fn=lambda pid: C.survival_pct(
                ctx["adp_rank"](reg.meta(pid).name, reg.meta(pid).position), next_user_pick),
            my_pids=my_pids, roster_slots=ctx["roster_slots"],
            strategy=strategy, round_no=round_no)
        if rec_row is None:
            rec_row = board_avail[0]

    # ---- CENTER: compact Player Spotlight on TOP, then Suggestions (focal) · Board ----
    with center, st.container(key="dr_panel_boardc"):
        st.markdown(C.run_banner_html(board_avail, recent_positions, next_user_pick,
                                      ctx["adp_rank"], reg, needs=needs),
                    unsafe_allow_html=True)
        if rec_row:
            rpm = reg.meta(rec_row["pid"])
            cue = "click a player in the list to inspect" if can_draft else "your top target"
            st.markdown(f'<div class="dr-rec">★ <b>{rec_row["name"]}</b> ({rpm.position} · {rpm.team}) '
                        f'— <span class="why">{rec_tag}</span> · <i>{cue}</i></div>',
                        unsafe_allow_html=True)
        if strategy and strategy != "Balanced":
            _sg = V.top_suggestions(board_avail, ctx["value"], reg, needs, taken,
                                    my_pids=my_pids, roster_slots=ctx["roster_slots"], k=3,
                                    strategy=strategy, round_no=round_no,
                                    next_pick=next_user_pick)
            _names = ", ".join(reg.meta(t["row"]["pid"]).name for t in _sg) or "—"
            st.markdown(C.strategy_banner_html(strategy, V.STRATEGY_HELP.get(strategy, ""),
                                               _names), unsafe_allow_html=True)
        # Always-visible top-4 suggestions (replaces the deep player spotlight — the
        # rows already carry ADP/bye/value, so no in-depth card is needed).
        suggestions_tab(ctx, key_prefix=mkey, ranks=ranks_active, taken=taken,
                        my_pids=my_pids, needs=needs, next_pick=next_user_pick,
                        pick_no=pick_no, on_click=None, on_star=toggle_queue,
                        quick_draft=(draft if can_draft else None), queued=queued,
                        strategy=strategy, round_no=round_no, k=12)

    # ---- RIGHT: live Picks feed (with predicted picks folded in) + draft intel ----
    preds = predict_upcoming(ctx, taken, pick_no, my_slot, kept_by_overall,
                             pids_by_slot=pids_by_slot, limit=16)
    pred_map = {ov: pid for ov, _s, pid in preds}
    with right, st.container(key="dr_panel_intel"):
        rtabs = st.tabs(["Pick Predictor", "My Team"])
        with rtabs[0]:
            st.markdown(C.insights_html(board_avail, recent_positions, needs), unsafe_allow_html=True)
            st.markdown(C.picks_feed_html(board, pick_no, n, rounds, slot_names, my_slot, owner,
                                          need_map, reg, kept_overalls=set(kept_by_overall),
                                          predictions=pred_map, queued=queued, lookahead=18),
                        unsafe_allow_html=True)
        with rtabs[1]:
            # switch between your team and any leaguemate's roster
            _labels = [f"{slot_names[s]} (you)" if s == my_slot else slot_names[s]
                       for s in range(n)]
            _pick = st.selectbox("View team", _labels, index=my_slot,
                                 key=f"{mkey}_teamview", label_visibility="collapsed")
            _vslot = _labels.index(_pick)
            _vpids = pids_by_slot.get(_vslot, [])
            st.markdown(C.lineup_html(_vpids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            st.markdown(C.roster_balance_html(_vpids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            st.markdown(C.roster_needs_html(_vpids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            if _vslot == my_slot:
                st.markdown(C.bye_conflict_html(_vpids, ctx["byes"], reg), unsafe_allow_html=True)
                if ctx.get("value") and board_avail:
                    my_left = [k for k in range(pick_no, total + 1) if owner(k) == my_slot]
                    plan = V.draft_plan(_vpids, ctx["roster_slots"], min(4, len(my_left)),
                                        board_avail, ctx["value"], reg, taken=taken)
                    st.markdown(C.draft_plan_html(plan), unsafe_allow_html=True)
            st.markdown(C.run_alert_html(upcoming_slots, need_map, ctx.get("value"), taken, reg,
                                         profiles=ctx.get("profiles"), owner_by_slot=owner_by_slot,
                                         round_no=round_no), unsafe_allow_html=True)

    kept_note = (f" · {len(kept_pids)} keepers locked" if kept_pids else "")
    if manual:
        st.caption("Manual / live mode — tap the player each team takes (the green "
                   "**Draft** button assigns him to whoever's on the clock) to track a "
                   "real draft. Undo removes the last pick." + kept_note)
    else:
        tnote = " · opponents draft by historical tendencies" if tendencies else ""
        st.caption("Click any player on the board to open their card, then Draft from the "
                   "card. Undo rolls back to your last pick, erasing the opponent picks "
                   f"after it.{kept_note}{tnote}")

    # ----- live pace: advance one opponent pick after rendering, with a slight delay -----
    if live_pace and ai_on_clock:
        time.sleep(_PICK_DELAY)
        if ai_pick(on_clock):
            st.rerun()
