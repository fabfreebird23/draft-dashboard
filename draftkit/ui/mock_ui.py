"""Mock Draft tab — history-aware AI opponents, locked keepers, a pick queue,
bye-week warnings, roster-strength ranking, a by-position cheat sheet, and a
war-room of value/tier/run intelligence. Board on top."""
from __future__ import annotations

import time

import streamlit as st

from .. import positional as PZ
from .. import draft_history
from . import components as C
from .widgets import (juice_tab, predict_upcoming, predictor_widget, queue_manager,
                      player_card_dialog, rankings_tab, select_player,
                      spotlight_panel,
                      steals_traps_widget, suggestions_tab)

@st.cache_data(ttl=1800, show_spinner="Predicting keepers…")
def _predicted_keepers(league_id: str, season: int, have_owners: tuple,
                       rounds: int, _value, _registry):
    """Cached predict_keepers. Uncached it fires ~5 GitHub requests (config.yaml,
    a keepers_<year>.json per streak season, the league chain, traded picks) on
    EVERY Streamlit rerun — which self-inflicts the rate limiting that makes those
    same fetches silently fall back to wrong defaults. `have_owners` is a tuple so
    the cache key changes the moment someone submits real keepers."""
    from .. import keepers as _K
    return _K.predict_keepers(league_id, _value, season, set(have_owners),
                              registry=_registry, rounds=rounds)


@st.cache_data(ttl=3600, show_spinner=False)
def _rookie_pool(aggression: float, curve_key: tuple, src: str, _pool, _registry):
    """The AI board at a given rookie temperature. Cached on (aggression, curve,
    source) — the pools themselves are big lists, so recomputing this on every
    rerun of a live-pace mock would be wasteful."""
    from .. import rankings as _R
    return _R.apply_rookie_curve(_pool, _registry, dict(curve_key), aggression=aggression)


_PICK_DELAY = 0.7  # seconds between AI picks in live-pace mode
_AI_JITTER = 0.15  # per-pick randomness so every mock draft plays out differently


def render(ctx, state_suffix: str = "") -> None:
    """`state_suffix` keeps each draft STAGE on its own board — without it the
    rookie and veteran drafts would share one `made` dict and overwrite each
    other."""
    reg = ctx["registry"]
    ranks = st.session_state.get(ctx["ranks_key"])
    if not ranks:
        st.info("Add your rankings on the **My Rankings** tab first.")
        return
    # A staged draft scopes the visible board too, not just the pools the AI picks
    # from. Filtered here, once, at the source — every panel below (rankings, cheat
    # sheet, queue, suggestions) reads this same list.
    if ctx.get("stage"):
        from .. import draft_stages as _DS
        ranks = _DS.eligible(ranks, ctx["stage"], reg, ctx.get("stage_taken"))
        if not ranks:
            st.warning("Nobody in your rankings is eligible for this stage. Pull a "
                       "fresh board on **My Rankings**.")
            return
        # Every panel below reads the board through ctx, not through session state,
        # so the scoping survives the trip down. Filtering only the local variable
        # changed nothing at all — rankings_tab went back to session state itself.
        ctx = {**ctx, "ranks_override": ranks}

    slot_names = ctx["slot_names"]
    n = len(slot_names)
    rounds = ctx["meta"].draft_rounds
    mkey = f"mock_{ctx['league_key']}" + (f"_{state_suffix}" if state_suffix else "")
    qkey = f"queue_{ctx['league_key']}"
    # Keepers: the dashboard placements, or — when the toggle is on — those PLUS
    # predicted keepers for teams that haven't entered any on the keeper dashboard.
    if st.session_state.get(f"{mkey}_predictkp", False):
        from .. import keepers as _K, config as _cfg
        keepers_raw = ctx.get("keepers_raw") or {}
        have_kp = {str(o) for o, kl in keepers_raw.items() if kl}
        predicted = _predicted_keepers(
            ctx["meta"].league_id, _cfg.current_season(), tuple(sorted(have_kp)),
            rounds, ctx.get("value"), ctx["registry"])
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
    # Rookie aggression slider (read here; the widget lives in the gear popover
    # below, so fall back to its stored value / the league default of 1.0).
    rookie_aggr = float(st.session_state.get(f"{mkey}_rookieaggr", 1.0))
    _curve_key = tuple(sorted((ctx.get("rookie_curve") or {}).get("curve", {}).items()))
    if abs(rookie_aggr - 1.0) > 1e-9:
        # retemper the default board too, and hand the same one to the Pick
        # Predictor so its forecast matches the mock the AI is actually running
        adp_pool = _rookie_pool(rookie_aggr, _curve_key, "Consensus", ctx["adp_pool"], reg)
        ctx = {**ctx, "ai_pool": adp_pool}

    from .. import value as V
    # ---- setup/config tucked into a gear dropdown; only actions stay on top ----
    ctrl = st.columns([0.5, 1.6, 1.5, 1.4, 1, 1])
    with ctrl[0].popover("⚙", use_container_width=True):
        # Same miss as the war room's "Your team": no index means the first name in
        # draft order wins, so every mock he has ever run was played from Maybe
        # Later's seat rather than his own — wrong picks highlighted, wrong roster
        # in My Team, wrong recap.
        _mine = ctx.get("owner_slot", {}).get(str(ctx.get("my_team")))
        me = st.selectbox("Your draft slot", slot_names, key=f"{mkey}_slot",
                          index=_mine if isinstance(_mine, int) and 0 <= _mine < len(slot_names)
                          else 0)
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
        rookie_aggr = st.slider(
            "Rookie aggression", 0.0, 2.0, 1.0, 0.1, key=f"{mkey}_rookieaggr",
            help="How hard the AI chases rookies. 1.0 = how this league has actually "
                 "drafted them (learned from past drafts). Below 1 they fly off even "
                 "earlier; above 1 they slide past their ADP. Change it between mocks "
                 "to practise against very different boards.")
        st.slider(
            "My board influence", 0.0, 6.0, 0.0, 0.5, key=f"{mkey}_boardedge",
            help="How much YOUR UDK board sways Suggestions. Your board already "
                 "decides WHO is eligible and supplies the tier cliffs; this adds "
                 "its DISAGREEMENT with market ADP as a score nudge, per 10 spots. "
                 "0 = off (Suggestions stays a pure second opinion). Raise it to "
                 "let your own tuning pull players up.")
        npred = st.session_state.get(f"{mkey}_npred", 0)
        if st.session_state.get(f"{mkey}_predictkp", False) and npred:
            st.caption(f"+{npred} predicted keepers")
        # Default to the strategy this league's own history argues for, rather
        # than making him remember. Still a dropdown — it is a default, not a lock.
        _dflt = PZ.default_strategy(ctx["meta"].league_id)
        strategy = st.selectbox(
            "Strategy", V.STRATEGIES, key=f"{mkey}_strategy",
            index=V.STRATEGIES.index(_dflt) if _dflt in V.STRATEGIES else 0,
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

    def _slot_drafted_counts(slot):
        """Position→count of this owner's DRAFTED picks only (no keepers) — the
        basis pos_share is measured on, so the share correction compares like
        with like."""
        rc = {}
        for o, pid in made.items():
            if owner(o) == slot:
                pos = reg.meta(pid).position
                rc[pos] = rc.get(pos, 0) + 1
        return rc

    def _slot_pos_share(slot):
        """This manager's HISTORICAL position mix, so the AI drifts back toward it
        instead of riding a hot board into an unrealistic 6-WR/2-RB roster."""
        return (ctx.get("profiles", {}).get(owner_by_slot.get(slot), {}) or {}).get("pos_share")

    def _slot_pool(slot):
        """The draft board this AI manager uses — their assigned ranking source
        (Scouting tab) or the consensus default, re-tempered to the Rookie
        aggression slider. Applied per SOURCE so a manager scouting off ESPN's
        board feels the slider too, not just the consensus default."""
        src = st.session_state.get(f"aisrc_{ctx['league_key']}_{slot}", "Consensus")
        base = ctx.get("source_pools", {}).get(src) or ctx["adp_pool"]
        # Your own board is exempt from the rookie slider. The slider exists because
        # the market's ADP under-rates rookies relative to how THIS league drafts
        # them; your board already reflects your own rookie lean, so re-tempering it
        # would apply that correction twice and stop it being your board.
        if src == "My UDK board" or abs(rookie_aggr - 1.0) < 1e-9:
            return ctx.get("source_pools", {}).get(src) or adp_pool   # prebuilt
        return _rookie_pool(rookie_aggr, _curve_key, src, base, reg)

    def ai_pick(ov):
        rnd = (ov - 1) // n + 1
        tk = taken_pids()
        pool = [p for p in _slot_pool(owner(ov)) if p["pid"] not in tk]

        choice = draft_history.pick_for_owner(owner_by_slot.get(owner(ov)), rnd, pool,
                                              tendencies, reg, jitter=_AI_JITTER,
                                              roster_counts=_slot_pos_counts(owner(ov)),
                                              pos_share=_slot_pos_share(owner(ov)),
                                              drafted_counts=_slot_drafted_counts(owner(ov)))
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

    # One board-anchored survival model per render, shared by the cheat sheet, the
    # suggestion scorer and the rankings rows so every % on screen agrees.
    # Same horizon rule as the war room: the pick on the clock counts toward the
    # players who come off the board before your next turn unless it is yours.
    _horizon = ((next_user_pick - pick_no) - (1 if owner(pick_no) == my_slot else 0)
                if next_user_pick else None)
    ctx = {**ctx, "survival_horizon": _horizon}   # every panel reads the same number
    surv_fn = C.board_survival_fn(ctx["adp_pool"], taken, pick_no, next_user_pick,
                                  horizon=_horizon) \
        if next_user_pick else (lambda pid, adp=None: None)

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
        """Stage the player for the popup card; opened once board_avail exists."""
        st.session_state[f"{mkey}_cardpid"] = str(pid)
        st.rerun()

    def toggle_queue(pid):
        q = [str(x) for x in st.session_state.get(qkey, [])]
        pid = str(pid)
        q.remove(pid) if pid in q else q.append(pid)
        st.session_state[qkey] = q
        st.rerun()

    queued = {str(x) for x in st.session_state.get(qkey, [])}
    round_no = (pick_no - 1) // n + 1
    # FIXED ROSTER: a position he has already filled is not a bad pick here, it is
    # an illegal roster — so it comes off his board. And once the compulsory spots
    # left equal the picks left (two kickers and two defenses are mandatory), every
    # remaining pick is spoken for and the board says so instead of recommending a
    # fifth receiver he cannot roster.
    # NB: scoped by ROSTER NEED, never by round. The tidy QB-QB-RB-RB order in
    # ESPN's data is how they type the results in afterwards, not how they pick.
    _need = (PZ.still_needed(my_pids, ctx["meta"].league_id, reg)
             if PZ.is_fixed_roster(ctx["meta"].league_id) else {})
    if _need:
        _left = len([k for k in range(pick_no, total + 1) if owner(k) == my_slot])
        _forced = PZ.must_reserve(my_pids, ctx["meta"].league_id, reg, _left)
        _open = set(_forced or _need)
        def _keep(r):
            try:
                q = (reg.meta(r["pid"]).position or "").upper()
            except Exception:  # noqa: BLE001
                return False
            return ("DST" if q in ("DEF", "D/ST") else q) in _open
        ctx = {**ctx,
               "ranks_override": [r for r in (ctx.get("ranks_override") or ranks) if _keep(r)],
               "roster_need": _need, "roster_forced": _forced}

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
        ltabs = st.tabs(["Rankings", "Cheat Sheet", "Juice's Value", "Queue", "Trends",
                        "League", "Scouting"])
        with ltabs[0]:
            ranks_active = rankings_tab(
                ctx, key_prefix=mkey, taken=taken, queued=queued,
                is_my_turn=can_draft, pick_no=pick_no, next_pick=next_user_pick,
                on_click=show_card, on_star=toggle_queue,
                quick_draft=(draft if can_draft else None), my_pids=my_pids)
        board_avail = [r for r in ranks_active
                       if r.get("pid") and str(r["pid"]) not in taken]
        with ltabs[1]:
            show_cs_drafted = st.toggle("Show drafted", key=f"{mkey}_cs_showdrafted")
            st.markdown(C.cheat_sheet_html(
                ranks_active, reg, taken=taken, show_drafted=show_cs_drafted,
                survival_fn=surv_fn), unsafe_allow_html=True)
        with ltabs[2]:
            juice_tab(ctx, key_prefix=mkey, taken=taken, queued=queued, on_star=toggle_queue)
        with ltabs[3]:
            queue_manager(ctx, qkey, ctx.get("ranks_override")
                          or st.session_state.get(ctx["ranks_key"]) or ranks_active,
                          taken, reg, f"{mkey}_q", on_pick=show_card,
                          quick_draft=(draft if can_draft else None))
        with ltabs[4]:
            st.markdown(C.buzz_list_html(board_avail, reg, ctx.get("buzz")),
                        unsafe_allow_html=True)
            if ctx.get("value"):
                steals, traps = V.steals_and_traps(board_avail, ctx["value"], reg,
                                                   ctx["adp_rank"], pool_size=total)
                st.markdown('<div class="dr-h">Steals &amp; Traps</div>', unsafe_allow_html=True)
                st.caption("Market value vs. ADP — biggest gaps between value and where he's going.")
                steals_traps_widget(steals, traps, reg, f"{mkey}_st", show_card)
            rh = C.rookie_history_html(ctx.get("rookie_curve"), reg, ctx["adp_pool"])
            if rh:
                st.markdown('<div class="dr-h">Rookie reach</div>', unsafe_allow_html=True)
                st.caption("Your league drafts rookies earlier than ADP — the mock reflects it.")
                st.markdown(rh, unsafe_allow_html=True)
        with ltabs[5]:
            st.markdown('<div class="dr-h dr-title">Roster Strength</div>', unsafe_allow_html=True)
            st.markdown(C.roster_strength_html(pids_by_slot, my_slot, slot_names, reg,
                                               ctx["adp_rank"]), unsafe_allow_html=True)
            st.markdown('<div class="dr-h">League Board</div>', unsafe_allow_html=True)
            st.markdown(C.league_board_html(pids_by_slot, slot_names, my_slot,
                                            ctx["roster_slots"], reg, on_clock_slot=on_slot),
                        unsafe_allow_html=True)
        with ltabs[6]:
            with st.expander("AI draft boards — set each manager's ranking source"):
                st.caption("Pick which board each AI manager drafts from — saved per "
                           "league, so you only set these once. Sleeper doesn't publish "
                           "ADP, so Underdog (best-ball) stands in.")

                def _persist_ai_sources():
                    """Write the whole map on any change. Streamlit fires on_change
                    BEFORE the rerun, so reading session_state here already sees the
                    new value for the box that changed."""
                    from .. import storage as _storage
                    lk = ctx["league_key"]
                    _storage.save_ai_sources(lk, {
                        str(s2): st.session_state.get(f"aisrc_{lk}_{s2}")
                        for s2 in range(n)
                        if s2 != my_slot and st.session_state.get(f"aisrc_{lk}_{s2}")})

                for s in range(n):
                    if s == my_slot:
                        continue
                    st.selectbox(slot_names[s], ctx["ai_sources"],
                                 key=f"aisrc_{ctx['league_key']}_{s}",
                                 on_change=_persist_ai_sources,
                                 help="The board this manager drafts off in the mock.")
            st.markdown(C.scouting_report_html(ctx.get("profiles", {}), slot_names,
                                               owner_by_slot, my_slot, on_clock_slot=on_slot,
                                               round_no=round_no), unsafe_allow_html=True)

    upcoming_slots = ([owner(k) for k in range(pick_no + 1, next_user_pick)]
                      if next_user_pick else [])

    # ---- player card popup ----
    # pop(), not get(): Streamlit gives no signal when a dialog is dismissed with the
    # X, so leaving the pid in state would reopen the card on the very next rerun.
    # Clearing it as we read means Draft / Queue / X all close it, and only a fresh
    # click re-stages one.
    _cardpid = st.session_state.pop(f"{mkey}_cardpid", None)
    if _cardpid:
        player_card_dialog(
            ctx, _cardpid, on_draft=(draft if can_draft else None), on_star=toggle_queue,
            queued=queued, next_pick=next_user_pick, survival=surv_fn(_cardpid),
            my_pids=my_pids, needs=needs, taken=taken,
            board_avail=board_avail, pick=pick_no)

    # top recommendation (drives the spotlight default + the ★ line)
    queue = [p for p in st.session_state.get(qkey, []) if str(p) not in taken]
    rec_row = next((r for r in board_avail if str(r["pid"]) == str(queue[0])), None) if queue else None
    rec_tag = "from your queue"
    if rec_row is None and board_avail:
        rec_row, _, rec_tag = V.best_pick(
            board_avail, ctx["value"], reg, needs, taken, next_pick=next_user_pick,
            survival_fn=surv_fn,
            my_pids=my_pids, roster_slots=ctx["roster_slots"],
            strategy=strategy, round_no=round_no,
            byes=ctx.get("byes"), juice_map=ctx.get("juice"))
        if rec_row is None:
            rec_row = board_avail[0]

    # ---- CENTER: compact Player Spotlight on TOP, then Suggestions (focal) · Board ----
    with center, st.container(key="dr_panel_boardc"):
        st.markdown(C.run_banner_html(board_avail, recent_positions, next_user_pick,
                                      ctx["adp_rank"], reg, needs=needs),
                    unsafe_allow_html=True)
        if rec_row:
            rpm = reg.meta(rec_row["pid"])
            cue = "Draft him, or ★ to queue" if can_draft else "your top target"
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
            st.markdown(C.taxi_html((ctx.get("taxi_by_slot") or {}).get(_vslot, []),
                                    ctx.get("taxi_slots") or 0, reg), unsafe_allow_html=True)
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
        st.caption("Draft straight from the row, or ★ to queue him. Undo rolls back to "
                   f"your last pick, erasing the opponent picks after it.{kept_note}{tnote}")

    # ----- live pace: advance one opponent pick after rendering, with a slight delay -----
    if live_pace and ai_on_clock:
        time.sleep(_PICK_DELAY)
        if ai_pick(on_clock):
            st.rerun()
