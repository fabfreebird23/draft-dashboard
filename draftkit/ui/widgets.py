"""Shared interactive widgets used by both the mock and live tabs."""
from __future__ import annotations

import streamlit as st

from .. import draft_history, theme
from . import components as C
from . import playercard as PC

_POSCOL = {"QB": "red", "RB": "green", "WR": "blue", "TE": "orange"}


def player_label(ctx, r, pm, *, pick=None) -> str:
    """The rich markdown row label shared by the board and the queue: overall rank,
    color-coded positional rank, name, team · ADP · bye, and the VORP value chip
    (plus a ▼/▲ ADP-delta chip when a current pick is supplied)."""
    pos_rank, adp_rank, byes = ctx["pos_rank"], ctx["adp_rank"], ctx.get("byes", {})
    vm = ctx.get("value")
    pid = str(r["pid"])
    pr = pos_rank.get(pid, pm.position)
    pc = _POSCOL.get(pm.position, "gray")
    adp = adp_rank(pm.name, pm.position)
    adps = int(adp) if adp else "—"
    bye = byes.get(pm.team, "")
    bye_s = f" · Bye {bye}" if bye else ""
    rk = r.get("rank")
    rk_s = f":gray[#{rk}] " if rk else ""
    v = vm.vorp_of(pid) if vm else None
    vchip = ""
    if v is not None:
        vchip = f"  :{'green' if v >= 0 else 'red'}[**V {'+' if v >= 0 else ''}{v:.0f}**]"
    vt = ""
    if pick:
        d = (adp - pick) if (adp and pick) else 0
        vt = f"  :red[▼+{int(d)}]" if d >= 8 else (f"  :violet[▲{int(d)}]" if d <= -8 else "")
    rook = "  :violet[**R**]" if getattr(pm, "years_exp", None) == 0 else ""
    meta = f":gray[{pm.team} · ADP {adps}{bye_s}]"
    return f'{rk_s}:{pc}[**{pr}**] **{r["name"]}**{rook} {meta}{vchip}{vt}'


def _headshot_css(container_key, pid) -> str:
    """Inline CSS that paints a player's headshot into a `_brow_`-styled row."""
    return (f'.st-key-{container_key} .stButton button::before{{'
            f'background-image:url("{theme.headshot_src(pid)}")}}')


def predict_upcoming(ctx, taken_pids, current_overall, my_slot, kept_by_overall, *,
                     limit=9):
    """Simulate the most-likely OPPONENT picks coming up. Your own picks are
    simulated (assumed best-available) so the predictor keeps showing opponents
    even at the snake turn where you pick back-to-back. Returns
    [(overall, slot, pid), ...]."""
    reg, adp_pool, tend = ctx["registry"], ctx["adp_pool"], ctx["tendencies"]
    owner_by_slot = ctx["owner_by_slot"]
    owner = ctx["pick_owner_slot"]            # traded-pick-aware ownership
    n = len(ctx["slot_names"])
    total = n * ctx["meta"].draft_rounds
    sim = {str(p) for p in taken_pids}
    out, ov = [], current_overall
    while ov <= total and len(out) < limit:
        slot = owner(ov)
        if ov in kept_by_overall:
            sim.add(str(kept_by_overall[ov]))
            ov += 1
            continue
        rnd = (ov - 1) // n + 1
        pool = [p for p in adp_pool if p["pid"] not in sim]
        if slot == my_slot:
            # assume you take the best available, so the sim keeps moving
            if pool:
                sim.add(pool[0]["pid"])
            ov += 1
            continue
        ch = draft_history.pick_for_owner(owner_by_slot.get(slot), rnd, pool, tend, reg)
        if not ch:
            break
        sim.add(ch["pid"])
        out.append((ov, slot, ch["pid"]))
        ov += 1
    return out


def clickable_board(ctx, board_avail, draft_fn, key_prefix, current_pick=None, *,
                    view="List", per_pos=16, limit=70, next_pick=None,
                    show_bands=True, on_star=None, queued=None, taken=None,
                    quick_draft=None) -> None:
    """Best-available board. Clicking a player row opens their Spotlight card
    (`draft_fn` here is really the inspect handler); when `quick_draft` is given,
    each List-view row also gets a small **Draft** button to draft without opening
    the card. Position-colored left bar (scoped `[class*="_brow_<POS>"]`), bold
    color-coded tier bands, and a survival % (chance the player lasts to your next
    pick). `view`='List' groups by overall tier; 'By position' splits into
    QB/RB/WR/TE columns grouped by per-position tier."""
    reg, pick = ctx["registry"], current_pick
    pos_tier, pos_rank, adp_rank = ctx["pos_tier"], ctx["pos_rank"], ctx["adp_rank"]
    byes = ctx.get("byes", {})
    vm = ctx.get("value")

    # Streamlit button labels support markdown (bold + :color[]) — use it to make
    # the rank / name / meta / value visually distinct instead of one flat string.
    poscol = _POSCOL

    def label(r, pm):
        return player_label(ctx, r, pm, pick=pick)

    def compact_label(r, pm):
        """Short label for the narrow by-position columns: rank, short name, value."""
        pr = pos_rank.get(str(r["pid"]), pm.position)
        pc = poscol.get(pm.position, "gray")
        v = vm.vorp_of(r["pid"]) if vm else None
        vchip = ""
        if v is not None:
            vchip = f"  :{'green' if v >= 0 else 'red'}[V {'+' if v >= 0 else ''}{v:.0f}]"
        return f':{pc}[**{pr}**] **{C.short_name(r["name"])}**{vchip}'

    taken_s = {str(x) for x in (taken or set())}

    def emit_row(r, compact=False):
        pm = reg.meta(r["pid"])
        rk = f'{key_prefix}_brow_{pm.position}_{r["pid"]}'
        # drafted players (Show-drafted mode): keep them in their tier, struck-through
        # and non-interactive, so tier depletion / runs stay visible.
        if str(r["pid"]) in taken_s:
            pr = pos_rank.get(str(r["pid"]), pm.position)
            st.markdown(
                f'<div class="brow-drafted">{theme.img_tag(r["pid"], "bd-img")}'
                f'<span class="bd-nm">{pr} · {pm.name} · {pm.team}</span>'
                f'<span class="bd-tag">DRAFTED</span></div>', unsafe_allow_html=True)
            return
        # per-row painted pseudo-elements: headshot (::before) + survival box (::after)
        # NB: `.stButton button` (descendant) not `>button` — st.button(help=…) wraps
        # the button in tooltip divs, so a direct-child selector wouldn't match.
        css = (f'.st-key-{rk} .stButton button::before{{'
               f'background-image:url("{theme.headshot_src(r["pid"])}")}}')
        if next_pick:
            adp = adp_rank(pm.name, pm.position)
            sc = C.survival_colors(C.survival_pct(adp, next_pick))
            if sc:
                pct = C.survival_pct(adp, next_pick)
                css += (f'.st-key-{rk} .stButton button::after{{content:"{pct}%";'
                        f'background:{sc[0]};color:{sc[1]}}}')
        pid = str(r["pid"])
        text = compact_label(r, pm) if compact else label(r, pm)

        def _player_btn():
            with st.container(key=rk):
                # always inject the headshot (::before); survival ::after is hidden by
                # the narrow-column CSS in compact/by-position mode. No help tooltip —
                # the full detail lives in the player card.
                st.markdown(f'<style>{css}</style>', unsafe_allow_html=True)
                if st.button(text, key=f'{key_prefix}_pick_{pid}', use_container_width=True):
                    draft_fn(pid)

        def _star_btn():
            with st.container(key=f"{key_prefix}_qstar_{pid}"):
                starred = pid in (queued or set())
                if st.button("★" if starred else "☆", key=f"{key_prefix}_star_{pid}",
                             use_container_width=True):
                    on_star(pid)

        def _draft_btn():
            with st.container(key=f"{key_prefix}_qdraft_{pid}"):
                if st.button("Draft", key=f"{key_prefix}_qd_{pid}",
                             use_container_width=True):
                    quick_draft(pid)

        show_star = on_star is not None and not compact
        show_draft = quick_draft is not None and not compact
        # Layout the row: optional ★ (queue) · player (opens card) · optional Draft.
        if show_star and show_draft:
            sc_ = st.columns([0.5, 7.1, 1.1], gap="small")
            with sc_[0]:
                _star_btn()
            with sc_[1]:
                _player_btn()
            with sc_[2]:
                _draft_btn()
        elif show_star:
            sc_ = st.columns([0.5, 8], gap="small")
            with sc_[0]:
                _star_btn()
            with sc_[1]:
                _player_btn()
        elif show_draft:
            sc_ = st.columns([7.4, 1.1], gap="small")
            with sc_[0]:
                _player_btn()
            with sc_[1]:
                _draft_btn()
        else:
            _player_btn()

    if view == "By position":
        cols = st.columns(4, gap="small")
        for col, pos in zip(cols, ("QB", "RB", "WR", "TE")):
            plist = [r for r in board_avail if reg.meta(r["pid"]).position == pos][:per_pos]
            with col:
                st.markdown(f'<div class="cheat-head {pos}">{pos}</div>', unsafe_allow_html=True)
                with st.container(key=f"{key_prefix}_board_{pos}"):
                    last = None
                    for r in plist:
                        t = pos_tier.get(str(r["pid"]))
                        if t != last:
                            st.markdown(f'<div class="ptier-mini">Tier {t}</div>',
                                        unsafe_allow_html=True)
                            last = t
                        emit_row(r, compact=True)
                    if not plist:
                        st.caption("—")
    else:
        with st.container(key=f"{key_prefix}_board_all"):
            last = None
            if not show_bands:
                st.markdown(C.tier_band("Sorted by value (VORP)", 1), unsafe_allow_html=True)
            for r in board_avail[:limit]:
                if show_bands and r["tier"] != last:
                    st.markdown(C.tier_band(f"Tier {r['tier']}", r["tier"]), unsafe_allow_html=True)
                    last = r["tier"]
                emit_row(r)


def _position_tiers(rows, pos_tier_map):
    """Renumber tiers for a single-position view so the list starts at Tier 1 and
    bumps at real (ADP-gap) tier breaks — instead of inheriting the overall board's
    tier numbers (which skip around, e.g. Tier 1, Tier 3, Tier 6 for one position)."""
    out, disp, prev = [], 0, None
    for r in rows:
        src = pos_tier_map.get(str(r["pid"]))
        if disp == 0:
            disp = 1
        elif src is not None and prev is not None and src > prev:
            disp += 1
        if src is not None:
            prev = src
        nr = dict(r)
        nr["tier"] = disp
        out.append(nr)
    return out


def rankings_tab(ctx, *, key_prefix, taken, queued=None, is_my_turn=False,
                 pick_no=None, next_pick=None, on_click=None, on_star=None,
                 quick_draft=None):
    """The Rankings tab: a source dropdown (UDK / FantasyPros ECR / ESPN), position
    pills (All/QB/RB/WR/TE/K/DST), Show-drafted, a Rank/Value sort, search, and the
    tiered list. Returns the active source's board rows so the caller can drive the
    intel panel from the same list. The list is clickable when it's your pick (open
    card / ☆ queue / quick Draft), static HTML otherwise."""
    from .. import rank_sources as RS
    reg = ctx["registry"]
    taken_s = {str(x) for x in (taken or set())}

    # ---- ranking source ----
    src_key = f"{key_prefix}_ranksrc"
    source = st.selectbox("Ranking source", RS.SOURCES, key=src_key,
                          label_visibility="collapsed")
    if source == RS.UDK:
        ranks = st.session_state.get(ctx["ranks_key"]) or []
    else:
        ranks = ctx["get_ranks"](source)
        if not ranks:
            st.caption(f"Couldn't load {source} right now (the host may block server "
                       "pulls) — showing your UDK board.")
            ranks = st.session_state.get(ctx["ranks_key"]) or []

    # ---- position pills ----
    present = {reg.meta(r["pid"]).position for r in ranks if r.get("pid")}
    positions = ["All"] + [p for p in ("QB", "RB", "WR", "TE", "K", "DST") if p in present]
    with st.container(key=f"{key_prefix}_posf"):
        pos_f = st.radio("Position", positions, horizontal=True,
                         key=f"{key_prefix}_pos", label_visibility="collapsed")

    # ---- search (own line) · then sort + show-drafted (so nothing crams/wraps) ----
    search = st.text_input("Search", key=f"{key_prefix}_search",
                           placeholder="Search…", label_visibility="collapsed")
    ctrl = st.columns([1.25, 1])
    sort = ctrl[0].radio("Sort", ["Rank", "Value"], horizontal=True,
                         key=f"{key_prefix}_sort", label_visibility="collapsed")
    show_drafted = ctrl[1].toggle("Show drafted", key=f"{key_prefix}_showdrafted")
    st.caption("**#** overall rank · **V** value over replacement · ▼ falling past ADP "
               "· tap **☆** to queue")

    base = [r for r in C.filter_pos(ranks, pos_f, reg) if r.get("pid")]
    if not show_drafted:
        base = [r for r in base if str(r["pid"]) not in taken_s]
    avail = C.filter_search(base, search, reg)
    by_value = sort == "Value" and ctx.get("value")
    if by_value:
        avail = sorted(avail, key=lambda r: ctx["value"].vorp_of(r["pid"]), reverse=True)
    elif pos_f != "All":
        # filtering to one position → show that position's own tiers (T1, T2, …)
        avail = _position_tiers(avail, ctx.get("pos_tier", {}))
    strike = taken if show_drafted else None

    # the list scrolls inside its own box, so paging through it doesn't move the page
    with st.container(key=f"{key_prefix}_ranklist"):
        if is_my_turn and on_click is not None:
            clickable_board(ctx, avail, on_click, key_prefix, current_pick=pick_no,
                            view="List", next_pick=next_pick, show_bands=not by_value,
                            on_star=on_star, queued=queued, taken=strike,
                            quick_draft=quick_draft)
        else:
            st.markdown(C.avail_html(avail, taken, reg, ctx["adp_rank"],
                                     pos_rank=ctx["pos_rank"], current_pick=pick_no,
                                     next_pick=next_pick, strike_taken=bool(strike)),
                        unsafe_allow_html=True)
    return ranks


def suggestions_tab(ctx, *, key_prefix, ranks, taken, my_pids, needs, next_pick,
                    pick_no, on_click=None, on_star=None, quick_draft=None, queued=None):
    """The Suggestions tab (FantasyPros-style): the model's top picks right now,
    ranked by value × roster fit + starter need + positional scarcity + whether
    he survives to your next pick (ADP vs your pick). Each row shows the headshot,
    pos·team·bye, the survival % (chance he's there next time), a **FIT** badge
    (the model's share of preference), and a one-tap Draft."""
    from .. import value as V
    reg = ctx["registry"]
    taken_s = {str(x) for x in (taken or set())}

    present = {reg.meta(r["pid"]).position for r in ranks if r.get("pid")}
    positions = ["All"] + [p for p in ("QB", "RB", "WR", "TE", "K", "DST") if p in present]
    with st.container(key=f"{key_prefix}_sg_posf"):
        pos_f = st.radio("Position", positions, horizontal=True,
                         key=f"{key_prefix}_spos", label_visibility="collapsed")
    st.caption("Top picks by value, roster fit, scarcity & survival to your next pick. "
               "**FIT** = the model's share of preference · the **%** box = chance he lasts "
               "to your next pick.")

    avail = [r for r in ranks if r.get("pid") and str(r["pid"]) not in taken_s
             and (pos_f == "All" or reg.meta(r["pid"]).position == pos_f)]
    sugg = V.top_suggestions(
        avail, ctx["value"], reg, needs, taken_s, next_pick=next_pick,
        survival_fn=lambda pid: C.survival_pct(
            ctx["adp_rank"](reg.meta(pid).name, reg.meta(pid).position), next_pick),
        my_pids=my_pids, roster_slots=ctx["roster_slots"], byes=ctx.get("byes"), k=7)
    if not sugg:
        st.caption("— no players available —")
        return
    # FIT %: the model's share of preference across the shown suggestions
    lo = min(s["score"] for s in sugg)
    shifted = [max(0.1, s["score"] - lo + 1.0) for s in sugg]
    tot = sum(shifted) or 1.0
    for s, w in zip(sugg, shifted):
        s["fit"] = max(1, round(100 * w / tot))

    for s in sugg:
        r, pm = s["row"], s["pm"]
        pid = str(r["pid"])
        adp = ctx["adp_rank"](pm.name, pm.position)
        d = (adp - pick_no) if (adp and pick_no) else 0
        if s["mult"] >= 0.999:
            reason = f"  :green[**fills {pm.position}**]"
        elif d >= 8:
            reason = "  :red[**▼ falling**]"
        elif s["left"] <= 2:
            reason = f"  :orange[**{s['left']} {pm.position} left**]"
        elif s["mult"] < 0.5:
            reason = "  :gray[bench depth]"
        else:
            reason = "  :green[**value**]"
        if getattr(pm, "years_exp", None) == 0:
            reason += "  :violet[**rookie**]"
        if s.get("stack"):
            reason += "  :violet[**stack**]"
        if s.get("bye_clash"):
            reason += "  :red[bye clash]"
        label = player_label(ctx, r, pm) + f"  :blue[**FIT {s['fit']}**]" + reason

        rk = f"{key_prefix}_sg_brow_{pm.position}_{pid}"
        css = _headshot_css(rk, pid)
        if next_pick:
            sc = C.survival_colors(s["sv"]) if s["sv"] is not None else None
            if sc:
                css += (f'.st-key-{rk} .stButton button::after{{content:"{s["sv"]}%";'
                        f'background:{sc[0]};color:{sc[1]}}}')

        layout = [0.5, 7.0, 1.1] if quick_draft else [0.5, 8.0]
        cols = st.columns(layout, gap="small")
        with cols[0], st.container(key=f"{key_prefix}_sg_qstar_{pid}"):
            starred = pid in (queued or set())
            if st.button("★" if starred else "☆", key=f"{key_prefix}_sgstar_{pid}",
                         use_container_width=True) and on_star:
                on_star(pid)
        with cols[1], st.container(key=rk):
            st.markdown(f'<style>{css}</style>', unsafe_allow_html=True)
            if st.button(label, key=f"{key_prefix}_sgp_{pid}",
                         use_container_width=True) and on_click:
                on_click(pid)
        if quick_draft:
            with cols[2], st.container(key=f"{key_prefix}_sg_qdraft_{pid}"):
                if st.button("Draft", key=f"{key_prefix}_sgqd_{pid}",
                             use_container_width=True):
                    quick_draft(pid)


def predictor_widget(predictions, slot_names, registry, n, key_prefix, on_click) -> None:
    """Pick Predictor as clickable rows — the most-likely opponent picks before your
    next turn; click one to open that player's card (e.g. to grab him first)."""
    st.markdown('<div class="dr-h" style="margin:2px 0 4px;" title="Simulated most-likely '
                'picks by the managers between now and your next turn, from their draft '
                'history and ADP. Click a player to open his card.">Pick Predictor — likely '
                'before you\'re up</div>', unsafe_allow_html=True)
    if not predictions:
        st.caption("—")
        return
    for ov, slot, pid in predictions:
        pm = registry.meta(pid)
        rd, inrd = (ov - 1) // n + 1, (ov - 1) % n + 1
        nm = slot_names[slot] if slot < len(slot_names) else f"Team {slot + 1}"
        rk = f'{key_prefix}_pp_{pm.position}_{ov}'
        css = (f'.st-key-{rk} .stButton button::before{{'
               f'background-image:url("{theme.headshot_src(pid)}")}}')
        with st.container(key=rk):
            st.markdown(f'<style>{css}</style>', unsafe_allow_html=True)
            if st.button(f'{rd}.{inrd:02d}  {nm[:11]}  →  {pm.name} · {pm.position}',
                         key=f'{key_prefix}_ppb_{ov}', use_container_width=True):
                on_click(pid)


def steals_traps_widget(steals, traps, registry, key_prefix, on_click) -> None:
    """Steals & Traps as clickable rows — click a player to open their card.
    STEAL = value rank beats ADP (falling past worth); TRAP = ADP beats value
    (over-drafted). Each row's tooltip explains the number."""
    cols = st.columns(2, gap="small")
    blocks = [
        ("STEALS", "steals", steals, "+",
         "Undervalued: their value rank (VORP) is better than where they're drafted "
         "(ADP). The number is how many spots they're falling past their worth — a "
         "bargain if they reach you."),
        ("TRAPS", "traps", traps, "−",
         "Overvalued: they're drafted (ADP) earlier than their value rank (VORP) "
         "warrants. The number is how many spots they're being over-drafted — usually "
         "a reach to avoid."),
    ]
    for col, (head, cls, items, sym, helptext) in zip(cols, blocks):
        with col:
            st.markdown(f'<div class="st-head {("steal" if cls=="steals" else "trap")}" '
                        f'title="{helptext}">{head} ⓘ</div>', unsafe_allow_html=True)
            with st.container(key=f"{key_prefix}_{cls}"):
                if not items:
                    st.caption("—")
                for r, gap, vr, adp in items:
                    pm = registry.meta(r["pid"])
                    g = abs(int(gap))
                    if st.button(f'{sym}{g}  {C.short_name(r["name"])} · {pm.position}',
                                 key=f'{key_prefix}_{cls}_{r["pid"]}',
                                 use_container_width=True):
                        on_click(r["pid"])


def select_player(widget_key, pid):
    """Stage a player to be shown in the spotlight (called when a board square is
    clicked). Consumed by `spotlight_panel` on the next run."""
    st.session_state[f"{widget_key}_pending"] = str(pid)


def spotlight_panel(ctx, board_avail, registry, widget_key, *, default_pid=None,
                    next_pick=None, draft_fn=None, my_pids=None, needs=None,
                    taken=None, upcoming_slots=None, need_map=None, round_no=None) -> None:
    """Player Spotlight (B): the focal detail card. Clicking a board square stages a
    player here (via `select_player`); a dropdown also lets you browse. Shows the
    headshot, VORP value + grab/wait verdict, roster synergy, survival %, tier
    drop-off, prior-season stats, and injury. The Draft button here drafts."""
    from .. import config, value as V
    if not board_avail:
        return
    label_to_pid, pid_to_label, options = {}, {}, []
    for r in board_avail:
        pid = str(r["pid"])
        pm = registry.meta(pid)
        lbl = f'{r["name"]} · {pm.position}·{pm.team}'
        label_to_pid[lbl] = pid
        pid_to_label[pid] = lbl
        options.append(lbl)

    sb_key = f"{widget_key}_inspect"
    pend_key = f"{widget_key}_pending"
    # A board click stages a pid here → drive the dropdown to it.
    pending = st.session_state.pop(pend_key, None)
    if pending and str(pending) in pid_to_label:
        st.session_state[sb_key] = pid_to_label[str(pending)]
    # Keep the selection valid (player may have just been drafted/removed).
    want = str(default_pid) if default_pid else options and label_to_pid[options[0]]
    if st.session_state.get(sb_key) not in options:
        st.session_state[sb_key] = pid_to_label.get(str(want), options[0])

    with st.expander("Player Spotlight", expanded=True):
        sel = st.selectbox("Inspect a player", options, key=sb_key,
                           label_visibility="collapsed")
        pid = label_to_pid[sel]
        pm = registry.meta(pid)
        row = next((r for r in board_avail if str(r["pid"]) == pid), {})
        tier = row.get("tier")
        overall = row.get("rank")

        # value signals
        vm = ctx.get("value")
        adp = ctx["adp_rank"](pm.name, pm.position)
        vorp = vm.vorp_of(pid) if vm else None
        proj = vm.proj_of(pid) if vm else None
        marg = None
        if vm and my_pids is not None:
            m = V.marginal_vorp(vm, pid, my_pids, registry, ctx["roster_slots"])
            if vorp is not None and abs(m - vorp) >= 1:
                marg = m
        verdict = None
        drop_next = None
        if vm:
            taken_s = {str(x) for x in (taken or [])}
            left = vm.startable_left(pm.position, taken_s)
            sv = C.survival_pct(adp, next_pick) if next_pick else None
            mult = (V.roster_multiplier(pm.position, my_pids, ctx["roster_slots"], registry)
                    if my_pids is not None else None)
            verdict = V.grab_verdict(sv, left, is_need=(pm.position in (needs or set())),
                                     mult=mult)
            # tier drop-off: my projection minus the best available in the next tier
            if tier is not None and proj:
                nxt = [vm.proj_of(r["pid"]) for r in board_avail
                       if r.get("tier") == tier + 1 and str(r["pid"]) != pid]
                if nxt:
                    drop_next = max(0.0, proj - max(nxt))
        synergy = V.synergy(pm, my_pids, registry) if my_pids else None
        sos = None
        if ctx.get("dvp") and ctx.get("schedule"):
            from .. import schedule as SCH
            sos = SCH.playoff_sos(pm.team, pm.position, ctx["dvp"], ctx["schedule"])

        st.markdown(
            PC.spotlight_html(
                pm, pos_rank=ctx["pos_rank"].get(pid, pm.position),
                adp=adp, tier=tier, byes=ctx["byes"],
                next_pick=next_pick, season=config.current_season() - 1,
                scoring=ctx["meta"].scoring, prev_label=str(config.current_season() - 1),
                vorp=vorp, proj=proj, verdict=verdict, synergy=synergy, drop_next=drop_next,
                marg=marg, sos=sos, overall=overall),
            unsafe_allow_html=True)
        # 'Beat the room' read: who picks before you & whether they're chasing his pos
        if vm and upcoming_slots and ctx.get("profiles") and need_map is not None:
            note = V.room_note(pm, upcoming_slots, need_map, ctx["profiles"],
                               ctx["owner_by_slot"], vm, taken, round_no=round_no,
                               survival=(sv if next_pick else None))
            if note:
                lbl, css, detail = note
                st.markdown(f'<div class="dr-room {css}"><b>{lbl}</b> · {detail}</div>',
                            unsafe_allow_html=True)
        if draft_fn is not None:
            if st.button(f"Draft {pm.name}", key=f"{widget_key}_spdraft", type="primary",
                         use_container_width=True):
                draft_fn(pid)


def queue_manager(ctx, qkey, ranks, taken, registry, widget_key, on_pick=None) -> None:
    """Pick-queue UI: search to add, ★ on the board to add, and each queued player
    is a clickable row that opens their card (so you can draft from your queue).
    A ✕ removes it. `qkey` is the shared queue store; `widget_key` is per-tab."""
    label_to_pid, options = {}, []
    for r in ranks:
        pid = r.get("pid")
        if not pid:
            continue
        pm = registry.meta(pid)
        lbl = f'{r["name"]} ({pm.position}·{pm.team})'
        label_to_pid[lbl] = str(pid)
        options.append(lbl)
    taken_s = {str(x) for x in taken}
    cur = [str(x) for x in st.session_state.get(qkey, [])]
    cur_labels = [lbl for lbl in options if label_to_pid[lbl] in cur]
    n_avail = len([p for p in cur if p not in taken_s])
    ms_key = f"{widget_key}_ms"

    def _sync_to_queue():
        sel = st.session_state.get(ms_key, [])
        st.session_state[qkey] = [label_to_pid[l] for l in sel if l in label_to_pid]

    def _remove(pid):
        q = [str(x) for x in st.session_state.get(qkey, [])]
        if str(pid) in q:
            q.remove(str(pid))
        st.session_state[qkey] = q
        st.rerun()

    # Reconcile the widget value FROM the queue (so the ★ toggles show up here)
    # without clobbering a fresh edit (the callback already synced those).
    if set(st.session_state.get(ms_key, [])) != set(cur_labels):
        st.session_state[ms_key] = cur_labels
    # rank/tier rows so the queue can render the SAME rich row as the board
    row_by_pid = {str(r["pid"]): r for r in ranks if r.get("pid")}
    with st.expander(f"My Queue ({n_avail})", expanded=bool(cur)):
        st.multiselect("Add to queue", options, key=ms_key, on_change=_sync_to_queue,
                       label_visibility="collapsed", placeholder="Search to add a player…")
        if not cur:
            st.caption("Tap the ☆ next to a player on the board, or search above.")
        for pid in cur:
            pm = registry.meta(pid)
            drafted = str(pid) in taken_s
            r = row_by_pid.get(str(pid), {"pid": str(pid), "name": pm.name, "rank": None})
            # reuse the board's `_brow_` row styling (headshot, pos bar, value chip)
            rk = f"{widget_key}_qb_brow_{pm.position}_{pid}"
            row = st.columns([8, 1], gap="small")
            with row[0], st.container(key=rk):
                st.markdown(f'<style>{_headshot_css(rk, pid)}</style>', unsafe_allow_html=True)
                if st.button(player_label(ctx, r, pm), key=f"{widget_key}_qpick_{pid}",
                             use_container_width=True, disabled=drafted) and on_pick:
                    on_pick(pid)
            with row[1], st.container(key=f"{widget_key}_qx_{pid}"):
                if st.button("✕", key=f"{widget_key}_qrm_{pid}", use_container_width=True):
                    _remove(pid)
