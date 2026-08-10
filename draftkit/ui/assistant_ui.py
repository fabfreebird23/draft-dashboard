"""Live Draft Assistant tab — polls the live draft (Sleeper or ESPN), overlays
keepers, and renders a war-room board on top with value/tier/run intelligence."""
from __future__ import annotations

import streamlit as st

from ..providers.espn import EspnAuthError
from . import components as C
from . import sleeper_handoff as SH
from .widgets import (juice_tab, predict_upcoming, predictor_widget, queue_manager,
                      player_card_dialog, rankings_tab, select_player,
                      spotlight_panel,
                      rerun_here,
                      steals_traps_widget, suggestions_tab)


def render(ctx) -> None:
    """Bind the auto-refresh cadence, then hand the whole screen to one fragment.

    Only the cadence lives out here. run_every is fixed when the fragment object
    is built, so it can only change on a full script run — everything else,
    controls included, belongs inside where it repaints without touching the page.
    """
    if not st.session_state.get(ctx["ranks_key"]):
        st.info("Add your rankings on the **My Rankings** tab first.")
        return
    akey = f"live_{ctx['league_key']}"
    auto = bool(st.session_state.get(f"{akey}_auto"))
    st.fragment(run_every=(12 if auto else None))(_live)(ctx, bound_auto=auto)


def _live(ctx, *, bound_auto: bool) -> None:
    """Controls, clock, pick entry and board — the whole war room, repainting as
    one block.

    Everything a pick touches is in here, so a pick redraws this and nothing
    else: the masthead, nav and league chrome above never re-run. That is what
    removes the flash and the scroll jump between picks.

    Buttons are safe in here. A fragment re-executes with the same ARGUMENTS on
    an auto-rerun, but widget state is not replayed — a button reports True only
    on the run following its click, so Reset cannot re-fire on a tick. (Measured,
    not assumed: 6 consecutive ticks after one click, still one fire.)
    """
    from .. import value as V
    reg = ctx["registry"]
    slot_names = ctx["slot_names"]
    n = len(slot_names)
    rounds = ctx["meta"].draft_rounds
    total = n * rounds
    akey = f"live_{ctx['league_key']}"
    mankey = f"livemade_{ctx['league_key']}"
    kept_overall = ctx["keepers"]["by_overall"]
    kept_pids = ctx["keepers"]["kept_pids"]
    owner = ctx["pick_owner_slot"]            # traded-pick-aware ownership
    ranks = st.session_state.get(ctx["ranks_key"])

    # ---- setup/config tucked into a gear dropdown; only actions stay on top ----
    ctrl = st.columns([0.5, 2.4, 1.2, 1, 1])
    with ctrl[0].popover("⚙", use_container_width=True):
        me = st.selectbox("Your team", slot_names, key=f"{akey}_me")
        mode = st.radio("Draft source", ["Live sync", "Manual entry"], horizontal=True,
                        key=f"{akey}_mode",
                        help="Live sync = pull picks automatically from Sleeper/ESPN. "
                             "Manual entry = tap the player each team takes.")
        strategy = st.selectbox(
            "Strategy", V.STRATEGIES, key=f"{akey}_strategy",
            help="Biases the ★ recommendation and Suggestions toward a plan "
                 "(Hero/Zero/Robust RB, Elite TE, Late-Round QB, or pure value).")
        _mkey = f"mockid_{ctx['meta'].platform}_{ctx['meta'].league_id}"
        if ctx["meta"].platform == "sleeper":
            _raw = st.text_input(
                "Follow a Sleeper mock", key=f"{akey}_mockin",
                value=st.session_state.get(_mkey) or "",
                placeholder="paste the mock draft URL or ID",
                help="Point the war room at a standalone Sleeper mock instead of "
                     "this league's draft. Mocks are readable on the same public "
                     "API. Your scoring and roster slots stay THIS league's — the "
                     "mock only supplies the picks, team count and rounds.")
            # accept a full URL: .../draft/nfl/<id>
            _id = "".join(ch for ch in (_raw or "").strip().split("/")[-1] if ch.isdigit())
            if (_id or None) != (st.session_state.get(_mkey) or None):
                if _id:
                    st.session_state[_mkey] = _id
                else:
                    st.session_state.pop(_mkey, None)
                # A full rerun, not a fragment one: the whole context is rebuilt.
                st.rerun()
        st.slider(
            "My board influence", 0.0, 6.0, 0.0, 0.5, key=f"{akey}_boardedge",
            help="How much YOUR UDK board sways Suggestions. Your board already "
                 "decides WHO is eligible and supplies the tier cliffs; this adds "
                 "its DISAGREEMENT with market ADP as a score nudge, per 10 spots. "
                 "0 = off (Suggestions stays a pure second opinion). Raise it to "
                 "let your own tuning pull players up.")
    manual = mode == "Manual entry"
    my_slot = slot_names.index(me)
    auto = False
    if not manual:
        auto = ctrl[2].checkbox("Auto-refresh", key=f"{akey}_auto")
        # Refresh needs no body: reaching here IS the re-poll. Inside the fragment
        # that costs a fragment rerun rather than a page rerun.
        ctrl[3].button("Refresh", key=f"{akey}_refresh")
    else:
        if ctrl[3].button("Reset", key=f"{akey}_mreset", use_container_width=True):
            st.session_state[mankey] = {}
        if ctrl[4].button("Undo", key=f"{akey}_mundo", use_container_width=True):
            _made = st.session_state.get(mankey) or {}
            if _made:
                del _made[max(_made)]                 # drop the most recent entry
                st.session_state[mankey] = _made
    if auto != bound_auto:
        # The cadence changed. run_every was fixed when this fragment was built, so
        # only a full run can rebind it — otherwise ticking would never start or,
        # worse, never stop. The one place a page rerun is still correct.
        st.rerun()

    # ----- gather picks from the chosen source into a common {overall: pid} map -----
    if manual:
        made = st.session_state.setdefault(mankey, {})
        # Seed manual entry from whatever Live sync already pulled. This is the
        # escape hatch the sync-failure message tells him to take, so starting it
        # from a blank board threw away every pick synced so far — exactly when
        # things are already going wrong. Only seeds once, and never overwrites
        # picks he has since typed himself.
        if not made:
            synced = st.session_state.get(f"{mankey}_synced") or {}
            if synced:
                made.update(synced)
                st.session_state[mankey] = made
        pick_pids = {ov: pid for ov, pid in made.items()}
        filled = {ov for ov, pid in made.items() if pid}
        picks_exist = bool(made)
    else:
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
        # A pick Sleeper reports but we can't resolve to a registry player still
        # OCCUPIES that slot. Track occupancy separately from identity: the
        # on-the-clock scan below walks forward while slots are filled, so a single
        # unresolvable pick would otherwise stop it dead for the rest of the draft.
        # (raw_id survives even when player is None.)
        filled = {p.overall for p in picks if p.overall and (p.player or p.raw_id)}
        picks_exist = bool(picks)
        # Keep the last good sync so flipping to Manual entry inherits the board
        # rather than starting blank (see the manual branch above).
        if pick_pids:
            st.session_state[f"{mankey}_synced"] = {ov: pid for ov, pid in pick_pids.items() if pid}

    # overlay keepers onto any empty keeper slots
    kept_at = set()
    for ov, pid in kept_overall.items():
        # never paint a keeper over a slot the draft has actually used — including
        # a real pick we couldn't resolve to a player (see `filled`).
        if ov in filled:
            continue
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

    # the pick on the clock: next overall not yet filled (keepers + entered picks).
    # `filled` covers picks we couldn't resolve to a player, so an unrecognized
    # pick can't stall the clock here for the remainder of the draft.
    pick_no = 1
    while pick_no <= total and (pick_no in kept_overall or pick_pids.get(pick_no)
                                or pick_no in filled):
        pick_no += 1
    pick_no = min(pick_no, total)
    on_slot = owner(pick_no)

    def _my_open_pick(k: int) -> bool:
        """A pick I own AND will actually get to use. A slot already spent on one
        of my keepers is not a turn I draft on — counting it makes 'next turn in
        N picks' wrong and, worse, computes every survival % against a pick I'm
        never selecting at (my first Kreeper keeper sits in round 7, so
        everything from there on was measured against the wrong target)."""
        return (k <= total and owner(k) == my_slot
                and k not in kept_overall and k not in filled)

    until = 0
    for k in range(pick_no, pick_no + total + 1):
        if _my_open_pick(k):
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
    # your next pick after the upcoming opponent run (skip back-to-back picks).
    # Uses _my_open_pick so keeper slots don't masquerade as turns you draft on —
    # this value is the target every survival % is measured against.
    nxt = pick_no
    while nxt <= total and _my_open_pick(nxt):
        nxt += 1
    while nxt <= total and not _my_open_pick(nxt):
        nxt += 1
    next_user_pick = nxt if nxt <= total else None

    # One board-anchored survival model per render, shared by the cheat sheet, the
    # suggestion scorer and the rankings rows so every % on screen agrees.
    surv_fn = C.board_survival_fn(ctx["adp_pool"], drafted, pick_no, next_user_pick) \
        if next_user_pick else (lambda pid, adp=None: None)

    queued = {str(x) for x in st.session_state.get(qkey, [])}

    def _inspect(pid):
        """Clicking a player stages him for the card; the dialog is opened once,
        further down, after board_avail/needs exist."""
        st.session_state[f"{akey}_cardpid"] = str(pid)
        rerun_here()

    def toggle_queue(pid):
        q = [str(x) for x in st.session_state.get(qkey, [])]
        pid = str(pid)
        q.remove(pid) if pid in q else q.append(pid)
        st.session_state[qkey] = q
        rerun_here()

    def draft(pid):
        """Manual mode: record this player at the pick on the clock and advance."""
        made[pick_no] = str(pid)
        st.session_state[mankey] = made
        rerun_here()

    round_no = (pick_no - 1) // n + 1
    need_map = C.needs_by_slot(pids_by_slot, slot_names, ctx["roster_slots"], reg)

    # ---- draft board: static, full width, pinned on top ----
    if ctx.get("mock_draft_id"):
        mm = ctx.get("mock_mismatch")
        if mm:
            st.error(f"That mock has **{mm[0]} teams** and this league has **{mm[1]}** — "
                     "picks are placed by draft slot, so they would land on the wrong "
                     "managers. Use a mock with the same number of teams.", icon="⚠️")
        else:
            st.caption(f"Following Sleeper mock `{ctx['mock_draft_id']}` — picks come from "
                       "the mock; your league's draft order, manager names and traded "
                       "picks are unchanged. Clear the field in ⚙ to go back.")
    if ctx.get("traded_failed"):
        # Say it out loud. A board drawn as a plain snake looks entirely normal.
        st.warning("Couldn't read traded picks just now — the board below is showing "
                   "the plain snake order, so any pick you traded for or away is in "
                   "the wrong column. Hit Refresh before trusting it.", icon="⚠️")
    with st.container(key="dr_board_top"):
        st.markdown(C.recent_ticker_html(real_picks, reg), unsafe_allow_html=True)
        st.markdown(C.grid_html(pick_pids, n, slot_names, my_slot, pick_no, rounds, reg,
                                kept_overalls=kept_at, owner_fn=owner),
                    unsafe_allow_html=True)
        # snaps the (freely-scrollable) board back to the current pick after every
        # draft action — see current_pick_scroll_html's docstring for why this has
        # to be a components.html iframe rather than plain st.markdown.
        st.components.v1.html(C.current_pick_scroll_html(), height=0)
        # Live tab only: surface your turn on the browser tab itself, since this is
        # the screen sitting behind the real Sleeper draft room.
        st.components.v1.html(
            C.turn_alert_html(on_slot == my_slot, picks_until=until), height=0)

    left, center, right = st.columns([1.05, 1.9, 1.05])

    # ---- LEFT: rankings · queue · trends (buzz / steals / rookie reach) ----
    from .. import value as V
    with left, st.container(key="dr_panel_board"):
        ltabs = st.tabs(["Rankings", "Cheat Sheet", "Juice's Value", "Queue", "Trends",
                        "League", "Scouting"])
        with ltabs[0]:
            ranks_active = rankings_tab(
                ctx, key_prefix=akey, taken=drafted, queued=queued, is_my_turn=True,
                pick_no=pick_no, next_pick=next_user_pick, on_click=_inspect,
                on_star=toggle_queue, quick_draft=(draft if manual else None),
                my_pids=my_pids)
        board_avail = [r for r in ranks_active
                       if r.get("pid") and str(r["pid"]) not in drafted]
        with ltabs[1]:
            show_cs_drafted = st.toggle("Show drafted", key=f"{akey}_cs_showdrafted")
            st.markdown(C.cheat_sheet_html(
                ranks_active, reg, taken=drafted, show_drafted=show_cs_drafted,
                survival_fn=surv_fn), unsafe_allow_html=True)
        with ltabs[2]:
            juice_tab(ctx, key_prefix=akey, taken=drafted, queued=queued, on_star=toggle_queue)
        with ltabs[3]:
            queue_manager(ctx, qkey, st.session_state.get(ctx["ranks_key"]) or ranks_active,
                          drafted, reg, f"{akey}_q", on_pick=_inspect,
                          quick_draft=(draft if manual else None))
        with ltabs[4]:
            st.markdown(C.buzz_list_html(board_avail, reg, ctx.get("buzz")),
                        unsafe_allow_html=True)
            if ctx.get("value"):
                steals, traps = V.steals_and_traps(board_avail, ctx["value"], reg,
                                                   ctx["adp_rank"], pool_size=n * rounds)
                st.markdown('<div class="dr-h">Steals &amp; Traps</div>', unsafe_allow_html=True)
                st.caption("Market value vs. ADP — biggest gaps between value and where he's going.")
                steals_traps_widget(steals, traps, reg, f"{akey}_st", _inspect)
            rh = C.rookie_history_html(ctx.get("rookie_curve"), reg, ctx["adp_pool"])
            if rh:
                st.markdown('<div class="dr-h">Rookie reach</div>', unsafe_allow_html=True)
                st.caption("Your league drafts rookies earlier than ADP — predictions reflect it.")
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
            st.markdown(C.scouting_report_html(ctx.get("profiles", {}), slot_names,
                                               ctx["owner_by_slot"], my_slot,
                                               on_clock_slot=on_slot, round_no=round_no),
                        unsafe_allow_html=True)

    # ---- player card popup ----
    # pop(), not get(): Streamlit gives no signal when a dialog is dismissed with the
    # X, so leaving the pid in state would reopen the card on the very next rerun.
    # Clearing it as we read means Draft / Queue / X all close it, and only a fresh
    # click re-stages one.
    _cardpid = st.session_state.pop(f"{akey}_cardpid", None)
    if _cardpid:
        player_card_dialog(
            ctx, _cardpid, on_draft=(draft if manual else None), on_star=toggle_queue,
            queued=queued, next_pick=next_user_pick, survival=surv_fn(_cardpid),
            my_pids=my_pids, needs=needs, taken=drafted,
            board_avail=board_avail, pick=pick_no)

    upcoming_slots = ([owner(k) for k in range(pick_no + 1, next_user_pick)]
                      if next_user_pick else [])

    queue = [p for p in st.session_state.get(qkey, []) if str(p) not in drafted]
    rec_row = next((r for r in board_avail if str(r["pid"]) == str(queue[0])), None) if queue else None
    why = "from your queue"
    if rec_row is None and board_avail:
        rec_row, _, why = V.best_pick(
            board_avail, ctx["value"], reg, needs, drafted, next_pick=next_user_pick,
            survival_fn=surv_fn,
            my_pids=my_pids, roster_slots=ctx["roster_slots"],
            strategy=strategy, round_no=round_no,
            byes=ctx.get("byes"), juice_map=ctx.get("juice"))
        if rec_row is None:
            rec_row = board_avail[0]

    # ---- CENTER: Suggestions (focal) · Board, with the Player Spotlight below ----
    with center, st.container(key="dr_panel_boardc"):
        st.markdown(C.run_banner_html(board_avail, recent_positions, next_user_pick,
                                      ctx["adp_rank"], reg, needs=needs),
                    unsafe_allow_html=True)
        if rec_row:
            tpm = reg.meta(rec_row["pid"])
            _rc = st.columns([3.4, 1])
            with _rc[0]:
                st.markdown(f'<div class="dr-rec">★ <b>{rec_row["name"]}</b> ({tpm.position} · {tpm.team}) '
                            f'— <span class="why">{why}</span></div>',
                            unsafe_allow_html=True)
            with _rc[1]:
                # The pick you take most often, one click from the Sleeper draft room.
                SH.copy_button(rec_row["name"], key=f"rec_sl_{ctx['league_key']}", height=46)
        if strategy and strategy != "Balanced":
            _sg = V.top_suggestions(board_avail, ctx["value"], reg, needs, drafted,
                                    my_pids=my_pids, roster_slots=ctx["roster_slots"], k=3,
                                    strategy=strategy, round_no=round_no,
                                    next_pick=next_user_pick)
            _names = ", ".join(reg.meta(t["row"]["pid"]).name for t in _sg) or "—"
            st.markdown(C.strategy_banner_html(strategy, V.STRATEGY_HELP.get(strategy, ""),
                                               _names), unsafe_allow_html=True)
        # Always-visible top-4 suggestions (replaces the deep player spotlight — the
        # rows already carry ADP/bye/value, so no in-depth card is needed).
        suggestions_tab(ctx, key_prefix=akey, ranks=ranks_active, taken=drafted,
                        my_pids=my_pids, needs=needs, next_pick=next_user_pick,
                        pick_no=pick_no, on_click=None, on_star=toggle_queue,
                        quick_draft=(draft if manual else None), queued=queued,
                        strategy=strategy, round_no=round_no, k=12)

    # ---- RIGHT: live Picks feed (with predicted picks folded in) + draft intel ----
    preds = predict_upcoming(ctx, drafted, pick_no, my_slot, kept_overall,
                             pids_by_slot=pids_by_slot, limit=16)
    pred_map = {ov: pid for ov, _s, pid in preds}
    with right, st.container(key="dr_panel_intel"):
        rtabs = st.tabs(["Pick Predictor", "My Team"])
        with rtabs[0]:
            st.markdown(C.insights_html(board_avail, recent_positions, needs), unsafe_allow_html=True)
            st.markdown(C.picks_feed_html(pick_pids, pick_no, n, rounds, slot_names, my_slot, owner,
                                          need_map, reg, kept_overalls=kept_at,
                                          predictions=pred_map, queued=queued, lookahead=18),
                        unsafe_allow_html=True)
        with rtabs[1]:
            _labels = [f"{slot_names[s]} (you)" if s == my_slot else slot_names[s]
                       for s in range(n)]
            _pick = st.selectbox("View team", _labels, index=my_slot,
                                 key=f"{akey}_teamview", label_visibility="collapsed")
            _vslot = _labels.index(_pick)
            _vpids = pids_by_slot.get(_vslot, [])
            st.markdown(C.lineup_html(_vpids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            st.markdown(C.roster_balance_html(_vpids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            st.markdown(C.roster_needs_html(_vpids, ctx["roster_slots"], reg), unsafe_allow_html=True)
            if _vslot == my_slot:
                st.markdown(C.bye_conflict_html(_vpids, ctx["byes"], reg), unsafe_allow_html=True)
                if ctx.get("value") and board_avail:
                    my_left = [k for k in range(pick_no, n * rounds + 1) if owner(k) == my_slot]
                    plan = V.draft_plan(_vpids, ctx["roster_slots"], min(4, len(my_left)),
                                        board_avail, ctx["value"], reg, taken=drafted)
                    st.markdown(C.draft_plan_html(plan), unsafe_allow_html=True)
                st.markdown(C.run_alert_html(upcoming_slots, need_map, ctx.get("value"), drafted, reg,
                                             profiles=ctx.get("profiles"),
                                             owner_by_slot=ctx["owner_by_slot"], round_no=round_no),
                            unsafe_allow_html=True)

    if not manual:
        SH.setup_note()

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
