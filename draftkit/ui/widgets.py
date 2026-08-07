"""Shared interactive widgets used by both the mock and live tabs."""
from __future__ import annotations

import streamlit as st

from .. import draft_history, theme
from . import components as C
from . import playercard as PC


def rerun_here() -> None:
    """Repaint the current fragment, or the page when we aren't inside one.

    st.rerun(scope="fragment") is ONLY legal during a fragment rerun. The first
    full script run that happens to render the fragment is not one, so a bare
    scope="fragment" raises there — i.e. on the very first pick of the night,
    which is precisely when it must not. Try the cheap repaint, fall back to the
    page. StreamlitAPIException only: st.rerun signals by raising RerunException,
    and swallowing that would turn every rerun into a no-op."""
    from streamlit.errors import StreamlitAPIException
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        rerun_here()

_POSCOL = {"QB": "red", "RB": "green", "WR": "blue", "TE": "orange"}


def stack_badge(pm, my_pids, registry) -> str:
    """A 'STK' (stack: QB↔pass-catcher) / 'CUF' (handcuff: same-team RB) badge when
    this player correlates with someone already on your roster, else ''. For board rows."""
    if not my_pids:
        return ""
    from .. import value as V
    tags = V.synergy(pm, my_pids, registry)
    if any(t[0] == "Stack" for t in tags):
        return ":violet[**STK**] "
    if any(t[0] == "Handcuff" for t in tags):
        return ":violet[**CUF**] "
    return ""


def reach_for(ctx, r, pm, pick=None, *, survival=None, next_pick=None):
    """The reach warning for one board row, or None. In a draft this is decided by
    the board-calibrated survival model; outside one it falls back to the plain
    ADP-vs-board-rank reading. See components.reach_note for why."""
    n = len(ctx.get("slot_names") or [])
    rounds = getattr(ctx.get("meta"), "draft_rounds", 0) or 0
    return C.reach_note(ctx["adp_rank"](pm.name, pm.position),
                        pick or r.get("rank"), n,
                        name=r.get("name") or pm.name,
                        max_pick=(n * rounds) or None,
                        survival=survival, board_rank=r.get("rank"),
                        next_pick=next_pick)


def player_label(ctx, r, pm, *, pick=None, my_pids=None, survival=None,
                 next_pick=None) -> str:
    """The rich markdown row label shared by the board and the queue: overall rank,
    color-coded positional rank, name, team · ADP · bye, and the VORP value chip
    (plus a ▼/▲ ADP-delta chip when a current pick is supplied). When `my_pids` is
    given, a STK/CUF badge marks stacks/handcuffs with your roster."""
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
    # Reach warning takes precedence over the raw ▼ delta — same underlying gap, but
    # once it's a full round it's a real "you can wait" signal rather than noise, and
    # it deserves the louder chip. Sub-round gaps keep the quiet ▼ they had before.
    vt = ""
    reach = reach_for(ctx, r, pm, pick, survival=survival, next_pick=next_pick)
    if reach:
        vt = ('  :red[**❗ can wait**]' if reach.get("survival") is not None
              else f'  :red[**❗{reach["rounds"]:.1f} rds early**]')
    elif pick:
        d = (adp - pick) if (adp and pick) else 0
        vt = f"  :red[▼+{int(d)}]" if d >= 8 else (f"  :violet[▲{int(d)}]" if d <= -8 else "")
    rook = "  :violet[**R**]" if getattr(pm, "years_exp", None) == 0 else ""
    stk = stack_badge(pm, my_pids, ctx["registry"])
    meta = f":gray[{pm.team} · ADP {adps}{bye_s}]"
    return f'{rk_s}:{pc}[**{pr}**] {stk}**{r["name"]}**{rook} {meta}{vchip}{vt}'


def _headshot_css(container_key, pid) -> str:
    """Inline CSS that paints a player's headshot into a `_brow_`-styled row."""
    return (f'.st-key-{container_key} .stButton button::before{{'
            f'background-image:url("{theme.headshot_src(pid)}")}}')


def predict_upcoming(ctx, taken_pids, current_overall, my_slot, kept_by_overall, *,
                     limit=9, pids_by_slot=None):
    """Simulate the most-likely OPPONENT picks coming up. Your own picks are
    simulated (assumed best-available) so the predictor keeps showing opponents
    even at the snake turn where you pick back-to-back. Returns
    [(overall, slot, pid), ...]. Respects the QB/TE roster caps so it never
    predicts a 3rd QB/TE for a team."""
    reg, tend = ctx["registry"], ctx["tendencies"]
    adp_pool = ctx.get("ai_pool") or ctx["adp_pool"]   # rookie-boosted pool
    src_pools = ctx.get("source_pools", {})
    lk = ctx.get("league_key", "")

    def slot_board(slot):                              # per-manager ranking source
        src = st.session_state.get(f"aisrc_{lk}_{slot}", "Consensus")
        return src_pools.get(src) or adp_pool
    owner_by_slot = ctx["owner_by_slot"]
    owner = ctx["pick_owner_slot"]            # traded-pick-aware ownership
    n = len(ctx["slot_names"])
    total = n * ctx["meta"].draft_rounds
    sim = {str(p) for p in taken_pids}
    # per-slot position counts (seed from current rosters; updated as we predict)
    counts = {}
    for slot, pids in (pids_by_slot or {}).items():
        c = {}
        for pid in pids:
            pos = reg.meta(pid).position
            c[pos] = c.get(pos, 0) + 1
        counts[slot] = c
    # keeper positions per slot, so the share correction can look at DRAFTED
    # picks only (pos_share is measured on non-keeper picks).
    kept_counts = {}
    for kov, kpid in (kept_by_overall or {}).items():
        ks = owner(kov)
        pos = reg.meta(kpid).position
        kept_counts.setdefault(ks, {})[pos] = kept_counts.setdefault(ks, {}).get(pos, 0) + 1
    drafted = {s2: {p2: max(0, c2 - kept_counts.get(s2, {}).get(p2, 0))
                    for p2, c2 in cc.items()} for s2, cc in counts.items()}

    out, ov = [], current_overall
    while ov <= total and len(out) < limit:
        slot = owner(ov)
        if ov in kept_by_overall:
            sim.add(str(kept_by_overall[ov]))
            ov += 1
            continue
        rnd = (ov - 1) // n + 1
        pool = [p for p in slot_board(slot) if p["pid"] not in sim]
        if slot == my_slot:
            # assume you take the best available, so the sim keeps moving
            if pool:
                sim.add(pool[0]["pid"])
            ov += 1
            continue
        ch = draft_history.pick_for_owner(owner_by_slot.get(slot), rnd, pool, tend, reg,
                                          roster_counts=counts.get(slot, {}),
                                          pos_share=(ctx.get("profiles", {})
                                                     .get(owner_by_slot.get(slot), {})
                                                     .get("pos_share")),
                                          drafted_counts=drafted.get(slot, {}))
        if not ch:
            break
        sim.add(ch["pid"])
        pos = reg.meta(ch["pid"]).position
        counts.setdefault(slot, {})[pos] = counts.setdefault(slot, {}).get(pos, 0) + 1
        drafted.setdefault(slot, {})[pos] = drafted.setdefault(slot, {}).get(pos, 0) + 1
        out.append((ov, slot, ch["pid"]))
        ov += 1
    return out


def clickable_board(ctx, board_avail, draft_fn, key_prefix, current_pick=None, *,
                    view="List", per_pos=16, limit=70, next_pick=None,
                    show_bands=True, on_star=None, queued=None, taken=None,
                    quick_draft=None, my_pids=None) -> None:
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

    def label(r, pm, survival=None):
        return player_label(ctx, r, pm, pick=pick, my_pids=my_pids,
                            survival=survival, next_pick=next_pick)

    def compact_label(r, pm):
        """Short label for the narrow by-position columns: rank, short name, value."""
        pr = pos_rank.get(str(r["pid"]), pm.position)
        pc = poscol.get(pm.position, "gray")
        v = vm.vorp_of(r["pid"]) if vm else None
        vchip = ""
        if v is not None:
            vchip = f"  :{'green' if v >= 0 else 'red'}[V {'+' if v >= 0 else ''}{v:.0f}]"
        stk = stack_badge(pm, my_pids, reg)
        return f':{pc}[**{pr}**] {stk}**{C.short_name(r["name"])}**{vchip}'

    taken_s = {str(x) for x in (taken or set())}
    # Survival is measured against the LIVE board (ADP order among the undrafted),
    # not against market ADP — see components.board_survival_fn. `taken` here is
    # the full drafted set, which is exactly the input that anchor needs.
    surv_fn = (C.board_survival_fn(ctx.get("adp_pool"), taken_s, pick, next_pick)
               if (next_pick and pick) else None)

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
        _sv = None                       # this row's survival %, reused by the reach chip
        if next_pick:
            adp = adp_rank(pm.name, pm.position)
            pct = _sv = (surv_fn(r["pid"], adp) if surv_fn
                         else C.survival_pct(adp, next_pick, pick))
            sc = C.survival_colors(pct)
            if sc:
                css += (f'.st-key-{rk} .stButton button::after{{content:"{pct}%";'
                        f'background:{sc[0]};color:{sc[1]}}}')
        pid = str(r["pid"])
        text = compact_label(r, pm) if compact else label(r, pm, survival=_sv)

        # Hover explanation for the ❗ chip. Attached ONLY on a reach: a tooltip on
        # every row would be noise, and the rest of the detail lives in the card.
        reach_tip = ((reach_for(ctx, r, pm, pick, survival=_sv, next_pick=next_pick)
                      or {}).get("tip") if not compact else None)

        def _player_btn():
            with st.container(key=rk):
                # always inject the headshot (::before); survival ::after is hidden by
                # the narrow-column CSS in compact/by-position mode.
                st.markdown(f'<style>{css}</style>', unsafe_allow_html=True)
                if st.button(text, key=f'{key_prefix}_pick_{pid}', use_container_width=True,
                             help=reach_tip):
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


def _position_tiers(rows):
    """Tag each row with the active ranking source's OWN positional tier for a
    single-position view — i.e. UDK's published tier (each row carries `tier` from
    the parsed board), not a synthetic ADP-gap scheme. The tier number is the
    source's ABSOLUTE tier and never changes as players are drafted: Tier 1 always
    means the same players, whether or not they're still on the board. (An earlier
    version renumbered from 1 for whatever was currently available, which made
    Tier 1 drift to different players once the real Tier 1 emptied out — fixed.)"""
    out = []
    for r in rows:
        # prefer UDK's real POSITIONAL tier (from a position-rankings import) over
        # the overall board tier
        src = r.get("pos_tier") or r.get("tier") or 1
        nr = dict(r)
        nr["tier"] = src
        out.append(nr)
    return out


def rankings_tab(ctx, *, key_prefix, taken, queued=None, is_my_turn=False,
                 pick_no=None, next_pick=None, on_click=None, on_star=None,
                 quick_draft=None, my_pids=None):
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
        age = ctx.get("board_age_h")
        st.caption(f"Your saved board · {C.age_phrase(age)}. Nothing refreshes it "
                   "automatically — pull from UDK on **My Rankings** to update."
                   if age is not None else
                   "Your saved board. Pull from UDK on **My Rankings** to refresh it.")
    else:
        ranks, status = ctx["get_ranks"](source)
        if not ranks:
            st.caption(f"Couldn't load {source} right now (the host may block server "
                       "pulls) — showing your UDK board.")
            ranks = st.session_state.get(ctx["ranks_key"]) or []
        elif status.get("stale"):
            # The fallback that used to be invisible: upstream is down, so these
            # rows came off an old cache. Say so rather than render it as live.
            st.warning(f"{source} is unreachable — showing a cached board from "
                       f"{C.age_phrase(status.get('age_h'))}. It may not reflect "
                       "recent news.", icon="⚠️")
        elif status.get("age_h") is not None and status["age_h"] >= 24:
            st.caption(f"{source} · cached {C.age_phrase(status['age_h'])}.")

    # Positional rank labels follow THIS source's overall order (so RB## never
    # contradicts the #overall when a non-UDK source is active).
    _bpr = C.board_pos_rank(ranks, reg)
    if _bpr:
        ctx = {**ctx, "pos_rank": _bpr}

    # ---- position pills (+ a Rookies pill when the board has any) ----
    present = {reg.meta(r["pid"]).position for r in ranks if r.get("pid")}
    positions = ["All"] + [p for p in ("QB", "RB", "WR", "TE", "K", "DST") if p in present]
    if any(getattr(reg.meta(r["pid"]), "years_exp", None) == 0
           for r in ranks if r.get("pid")):
        positions.append(C.ROOKIE_FILTER)
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
    elif pos_f not in ("All", C.ROOKIE_FILTER):
        # filtering to one position → order by UDK's positional rank (its tiers
        # follow that, not overall ADP), tagged with the source's absolute tier
        if any(r.get("pos_rank") for r in avail):
            avail = sorted(avail, key=lambda r: (r.get("pos_rank") or r.get("rank") or 9999))
        avail = _position_tiers(avail)
    strike = taken if show_drafted else None

    # the list scrolls inside its own box, so paging through it doesn't move the page
    with st.container(key=f"{key_prefix}_ranklist"):
        if is_my_turn and on_click is not None:
            clickable_board(ctx, avail, on_click, key_prefix, current_pick=pick_no,
                            view="List", next_pick=next_pick, show_bands=not by_value,
                            on_star=on_star, queued=queued, taken=strike,
                            quick_draft=quick_draft, my_pids=my_pids)
        else:
            st.markdown(C.avail_html(avail, taken, reg, ctx["adp_rank"],
                                     pos_rank=ctx["pos_rank"], current_pick=pick_no,
                                     next_pick=next_pick, strike_taken=bool(strike)),
                        unsafe_allow_html=True)
    return ranks


_JUICE_SORTS = {
    "Sleeper Rank": lambda x: (x.get("sleeper_rank") if x.get("sleeper_rank") is not None else 9999),
    "Biggest Value": lambda x: -(x.get("skew") if x.get("skew") is not None else -99),
    "Biggest Reach": lambda x: (x.get("skew") if x.get("skew") is not None else 99),
    "Biggest Landmine": lambda x: -(x.get("landmine") if x.get("landmine") is not None else -1),
}


def juice_tab(ctx, *, key_prefix, taken, queued=None, on_star=None, limit=80) -> None:
    """Juice's Value tab: Sleeper's default draft-room rank vs FantasyPros ADP/ECR,
    so you can spot who your draft site over/undervalues before you draft off its
    board. Sourced from a public, periodically-updated sheet, scoped to this
    league's own scoring format. **Δ** = Sleeper rank − ECR rank in plain spots:
    positive/green = Sleeper ranks him later than the experts — a value, he'll
    likely fall further than he should. Negative/red = Sleeper ranks him earlier —
    a reach if you chase him at that slot. **Landmine** is the sheet's own 0-10
    risk scale (0 = great value, 10 = avoid). Each row gets a real ☆ so you can
    queue him straight from here (same shared queue as the board/Rankings)."""
    reg = ctx["registry"]
    jmap = ctx.get("juice") or {}
    if not jmap:
        st.caption("Couldn't load Juice's Value sheet right now — try again shortly.")
        return
    taken_s = {str(x) for x in (taken or set())}
    queued_s = {str(x) for x in (queued or set())}
    present = {row.get("position") for row in jmap.values()}
    positions = ["All"] + [p for p in ("QB", "RB", "WR", "TE") if p in present]
    with st.container(key=f"{key_prefix}_jc_posf"):
        pos_f = st.radio("Position", positions, horizontal=True,
                         key=f"{key_prefix}_jcpos", label_visibility="collapsed")
    ctrl = st.columns([1.6, 1])
    sort = ctrl[0].radio("Sort", list(_JUICE_SORTS), horizontal=True,
                        key=f"{key_prefix}_jcsort", label_visibility="collapsed")
    show_drafted = ctrl[1].toggle("Show drafted", key=f"{key_prefix}_jc_showdrafted")
    st.caption("**ADP**/**ECR** = FantasyPros market ADP / expert consensus rank · "
               "**Δ** = Sleeper rank − ECR, in spots (green = value, falls later "
               "than deserved · red = reach, goes earlier) · **Landmine** = risk "
               "of overpaying in your room, 0-10 (10 = avoid). Tap **☆** to queue.")
    rows = [{"pid": pid, **row} for pid, row in jmap.items()
            if pos_f == "All" or row.get("position") == pos_f]
    rows.sort(key=_JUICE_SORTS[sort])
    if not show_drafted:
        rows = [r for r in rows if str(r["pid"]) not in taken_s]
    rows = rows[:limit]
    # The header must go through the SAME column split as the rows. Each row lives in
    # cols[0] of a [7.6, 0.42] split (the ☆ takes the rest), so a full-width header is
    # ~5% wider — and because the name column is minmax(0,1fr), every fixed-width
    # column after it is anchored to the right edge and slides by that whole
    # difference. ADP/ECR/Δ/LANDMINE then sit right of their numbers. Splitting the
    # header identically keeps the two grids the same width at any container size,
    # which a hardcoded padding wouldn't.
    head = st.columns([7.6, 0.42], gap="small")
    with head[0]:
        st.markdown(C.juice_colhead_html(), unsafe_allow_html=True)
    for r in rows:
        pid = str(r["pid"])
        is_taken = pid in taken_s
        cols = st.columns([7.6, 0.42], gap="small")
        with cols[0]:
            st.markdown(C.juice_row_html(r, is_taken=is_taken), unsafe_allow_html=True)
        with cols[1], st.container(key=f"{key_prefix}_jcstar_{pid}"):
            if not is_taken:
                starred = pid in queued_s
                if st.button("★" if starred else "☆", key=f"{key_prefix}_jcst_{pid}") and on_star:
                    on_star(pid)


def suggestions_tab(ctx, *, key_prefix, ranks, taken, my_pids, needs, next_pick,
                    pick_no, on_click=None, on_star=None, quick_draft=None, queued=None,
                    strategy=None, round_no=None, k=7):
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
    trow = st.columns([3.1, 1.1])
    trow[0].caption("Top picks by value, roster fit, scarcity & survival to your next "
                    "pick. **FIT** = the model's share of preference · the **%** box = "
                    "chance he lasts to your next pick.")
    upside = trow[1].toggle("Upside", key=f"{key_prefix}_upside",
                            help="Upside Mode — re-rank toward high-ceiling, younger and "
                                 "rookie players instead of safe floor/value.")

    avail = [r for r in ranks if r.get("pid") and str(r["pid"]) not in taken_s
             and (pos_f == "All" or reg.meta(r["pid"]).position == pos_f)]
    # Board-anchored, so a keeper league (where the room runs well ahead of market
    # ADP) doesn't read every suggestion as ~100% likely to fall back to you.
    sugg = V.top_suggestions(
        avail, ctx["value"], reg, needs, taken_s, next_pick=next_pick,
        survival_fn=C.board_survival_fn(ctx.get("adp_pool"), taken_s, pick_no, next_pick),
        my_pids=my_pids, roster_slots=ctx["roster_slots"], byes=ctx.get("byes"), k=k,
        upside=upside, strategy=strategy, round_no=round_no, juice_map=ctx.get("juice"),
        adp_rank_fn=ctx["adp_rank"],
        board_edge_weight=float(st.session_state.get(f"{key_prefix}_boardedge", 0.0)))
    if strategy and strategy != "Balanced":
        st.caption(f"**{strategy}** — {V.STRATEGY_HELP.get(strategy, '')}")
    if not sugg:
        st.caption("— no players available —")
        return
    # FIT %: the model's share of preference across the shown suggestions
    lo = min(s["score"] for s in sugg)
    shifted = [max(0.1, s["score"] - lo + 1.0) for s in sugg]
    tot = sum(shifted) or 1.0
    for s, w in zip(sugg, shifted):
        s["fit"] = max(1, round(100 * w / tot))

    # one-line strategic call (what to prioritize right now)
    st.markdown(C.strategy_html(sugg, avail), unsafe_allow_html=True)

    _POSVAR = {"QB": "var(--qb)", "RB": "var(--rb)", "WR": "var(--wr)", "TE": "var(--te)",
              "K": "var(--k)", "DST": "var(--dst)"}
    vm = ctx.get("value")
    pos_rank = ctx["pos_rank"]

    # header sits in the SAME 3-column split as each row (Draft | info-grid | star)
    # so its ADP/Rank/Value/Survival labels land exactly over the row's own grid,
    # instead of spanning the full width and drifting out of alignment.
    hcols = st.columns([0.9, 7.6, 0.42], gap="small")
    with hcols[1]:
        st.markdown('<div class="sg-colhead"><span></span><span class="r">ADP</span>'
                    '<span class="r">Rank</span><span class="r">Value</span>'
                    '<span class="r">Survival</span></div>', unsafe_allow_html=True)

    for s in sugg:
        r, pm = s["row"], s["pm"]
        pid = str(r["pid"])
        adp = ctx["adp_rank"](pm.name, pm.position)
        adp_s = f"{int(adp)}" if adp else "—"
        d = (adp - pick_no) if (adp and pick_no) else 0
        pr = pos_rank.get(pid, pm.position)
        pc = _POSVAR.get(pm.position, "var(--mut2)")
        byes = ctx.get("byes", {})
        bye = byes.get(pm.team, "")
        sub = f"{pm.position} · {pm.team}" + (f" · Bye {bye}" if bye else "")

        tags = ""
        if getattr(pm, "years_exp", None) == 0:
            tags += '<span class="sg-tag rook">R</span>'
        if d >= 8:
            tags += '<span class="sg-tag fall">▼</span>'
        if s.get("stack"):
            tags += '<span class="sg-tag stack">STK</span>'
        if s.get("bye_clash"):
            tags += '<span class="sg-tag bye">bye</span>'
        skew = s.get("skew")
        if skew is not None and skew >= 0.5:
            tags += ('<span class="sg-tag value" title="Juice\'s Value: Sleeper '
                     'ranks him later than FantasyPros ECR — likely value">V</span>')
        elif (s.get("landmine") or 0) >= 7:
            tags += ('<span class="sg-tag landmine" title="Juice\'s Value: Sleeper '
                     'ranks him well ahead of FantasyPros ECR — reach risk">LM</span>')

        v = vm.vorp_of(pid) if vm else None
        val_html = "—"
        val_cls = " lo"
        if v is not None:
            val_html = f"{'+' if v >= 0 else ''}{v:.0f}"
            val_cls = "" if v >= 45 else " lo"

        sv = s.get("sv")
        if sv is not None:
            svcolor = "var(--green)" if sv >= 60 else ("var(--amber)" if sv >= 30 else "var(--red)")
            surv_html = (f'<div class="sg-surv"><div class="lab" style="color:{svcolor}">{sv}%</div>'
                        f'<div class="sg-track"><i style="width:{sv}%;background:{svcolor}"></i></div></div>')
        else:
            surv_html = '<div class="sg-surv"><div class="lab" style="color:var(--mut2)">—</div></div>'

        row_html = (
            '<div class="sg-row">'
            f'<div class="sg-who">{theme.img_tag(pid, "sg-av")}'
            f'<div class="sg-nm-wrap"><div class="sg-nm">{r["name"]}{tags}</div>'
            f'<div class="sg-sub"><span class="dot" style="background:{pc}"></span>{sub}</div></div></div>'
            f'<div class="sg-num">{adp_s}</div>'
            f'<div class="sg-rank" style="color:{pc}">{pr}</div>'
            f'<div class="sg-val{val_cls}">{val_html}</div>'
            f'{surv_html}'
            '</div>')

        # Draft sits leftmost (before the headshot), the info row in the middle,
        # and the ☆ queue-star on the far right.
        cols = st.columns([0.9, 7.6, 0.42], gap="small")
        if quick_draft:
            with cols[0], st.container(key=f"{key_prefix}_sgdraft2_{pid}"):
                if st.button("Draft", key=f"{key_prefix}_sgqd_{pid}", use_container_width=True):
                    quick_draft(pid)
        with cols[1]:
            st.markdown(row_html, unsafe_allow_html=True)
        with cols[2], st.container(key=f"{key_prefix}_sgstar2_{pid}"):
            starred = pid in (queued or set())
            if st.button("★" if starred else "☆", key=f"{key_prefix}_sgstar_{pid}") and on_star:
                on_star(pid)


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


def _ai_section(pm, pid, facts, widget_key) -> None:
    """Coach-AI block in the spotlight: an on-demand outlook paragraph + a Q&A box,
    powered by the Claude API. Renders nothing unless an Anthropic key is set."""
    from .. import ai as AI

    if not AI.available():
        return
    ok = f"{widget_key}_ai_outlook_{pid}"          # cached outlook text per player
    qhist = f"{widget_key}_ai_chat_{pid}"          # [{role, content}] for follow-ups
    with st.expander("Coach AI — outlook & ask"):
        if ok not in st.session_state:
            if st.button("Generate outlook", key=f"{widget_key}_ai_go_{pid}",
                         use_container_width=True):
                with st.spinner("Reading the room…"):
                    try:
                        st.session_state[ok] = AI.outlook(pm, facts)
                    except Exception as e:
                        st.session_state[ok] = f"AI unavailable: {e}"
                rerun_here()
        else:
            st.markdown(f'<div class="dr-ai">{st.session_state[ok]}</div>',
                        unsafe_allow_html=True)

        # Prior Q&A turns for this player.
        for turn in st.session_state.get(qhist, []):
            who = "You" if turn["role"] == "user" else "Coach AI"
            css = "dr-ai-q" if turn["role"] == "user" else "dr-ai-a"
            st.markdown(f'<div class="{css}"><b>{who}:</b> {turn["content"]}</div>',
                        unsafe_allow_html=True)

        q = st.text_input(f"Ask about {C.short_name(pm.name)}",
                          key=f"{widget_key}_ai_q_{pid}",
                          placeholder="e.g. What's his ceiling if the offense clicks?")
        if st.button("Ask", key=f"{widget_key}_ai_ask_{pid}",
                     use_container_width=True) and q.strip():
            hist = st.session_state.get(qhist, [])
            with st.spinner("Thinking…"):
                try:
                    ans = AI.ask(pm, facts, q.strip(), history=hist or None)
                except Exception as e:
                    ans = f"AI unavailable: {e}"
            hist = hist + [{"role": "user", "content": q.strip()},
                           {"role": "assistant", "content": ans}]
            st.session_state[qhist] = hist
            rerun_here()


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

    with st.container(key=f"{widget_key}_box"):
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
            # NB: no current_pick in this function's scope — the previous line here
            # passed one anyway and was a latent NameError, unnoticed because
            # spotlight_panel currently has no callers. ADP fallback until it does.
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
                marg=marg, sos=sos, overall=overall, compact=True),
            unsafe_allow_html=True)
        # ADP market read: cross-source spread + buy/'going early' vs value
        vrank = vm.rank_of(pid) if vm and hasattr(vm, "rank_of") else None
        st.markdown(C.adp_market_html(ctx.get("adp_df"), pm.name, pm.position, vrank),
                    unsafe_allow_html=True)
        # Waiver buzz: rising / cooling from Sleeper add-drop velocity (news proxy)
        buzz_chip = C.buzz_chip_html(pid, registry, ctx.get("buzz"))
        if buzz_chip:
            st.markdown(buzz_chip, unsafe_allow_html=True)
        # 'Beat the room' read: who picks before you & whether they're chasing his pos
        if vm and upcoming_slots and ctx.get("profiles") and need_map is not None:
            note = V.room_note(pm, upcoming_slots, need_map, ctx["profiles"],
                               ctx["owner_by_slot"], vm, taken, round_no=round_no,
                               survival=(sv if next_pick else None))
            if note:
                lbl, css, detail = note
                st.markdown(f'<div class="dr-room {css}"><b>{lbl}</b> · {detail}</div>',
                            unsafe_allow_html=True)
        # Coach AI: on-demand outlook + Q&A grounded in the live draft facts.
        ai_facts = {
            "season": config.current_season(),
            "scoring": ctx["meta"].scoring,
            "adp": int(adp) if adp else None,
            "overall": overall,
            "pos_rank": ctx["pos_rank"].get(pid, pm.position),
            "tier": tier,
            "value_rank": vrank,
            "proj": round(proj, 1) if proj else None,
            "verdict": verdict[0] if isinstance(verdict, (tuple, list)) and verdict else None,
            "age": pm.age,
            "years_exp": pm.years_exp,
            "injury": pm.injury_status,
            "bye": ctx.get("byes", {}).get(pm.team),
        }
        _ai_section(pm, pid, ai_facts, widget_key)

        if draft_fn is not None:
            if st.button(f"Draft {pm.name}", key=f"{widget_key}_spdraft", type="primary",
                         use_container_width=True):
                draft_fn(pid)


def queue_manager(ctx, qkey, ranks, taken, registry, widget_key, on_pick=None,
                  quick_draft=None) -> None:
    """Pick-queue UI: search to add, ★ on the board to add, and each queued player
    is a clickable row that opens their card. When `quick_draft` is given (i.e. it's
    actually your turn), a green **Draft** button drafts him straight from the
    queue without switching tabs. A ✕ removes it. `qkey` is the shared queue
    store; `widget_key` is per-tab."""
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
    # Follow the QUEUE's own order, not the board's. Iterating `options` here
    # re-sorted the queue into board order on every rerun, and queue[0] drives the
    # ★ "from your queue" recommendation — so simply opening the tab could change
    # which player the app told you to take.
    pid_to_label = {p: l for l, p in label_to_pid.items()}
    cur_labels = [pid_to_label[p] for p in cur if p in pid_to_label]
    # Queued players who aren't on the active board (different ranking source, or
    # already drafted) have no label, so they can't appear in the multiselect —
    # keep them so a later edit doesn't silently delete them.
    off_board = [p for p in cur if p not in pid_to_label]
    n_avail = len([p for p in cur if p not in taken_s])
    ms_key = f"{widget_key}_ms"

    def _sync_to_queue():
        sel = st.session_state.get(ms_key, [])
        # keep off-board entries the widget can't represent (see `off_board`)
        st.session_state[qkey] = ([label_to_pid[l] for l in sel if l in label_to_pid]
                                  + off_board)

    def _remove(pid):
        q = [str(x) for x in st.session_state.get(qkey, [])]
        if str(pid) in q:
            q.remove(str(pid))
        st.session_state[qkey] = q
        rerun_here()

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
            row = st.columns([0.9, 6.4, 0.7], gap="small")
            if quick_draft and not drafted:
                with row[0], st.container(key=f"{widget_key}_qdraft_{pid}"):
                    if st.button("Draft", key=f"{widget_key}_qd_{pid}", use_container_width=True):
                        quick_draft(pid)
            with row[1], st.container(key=rk):
                st.markdown(f'<style>{_headshot_css(rk, pid)}</style>', unsafe_allow_html=True)
                if st.button(player_label(ctx, r, pm), key=f"{widget_key}_qpick_{pid}",
                             use_container_width=True, disabled=drafted) and on_pick:
                    on_pick(pid)
            with row[2], st.container(key=f"{widget_key}_qx_{pid}"):
                if st.button("✕", key=f"{widget_key}_qrm_{pid}", use_container_width=True):
                    _remove(pid)


def _card_facts(ctx, pid, *, next_pick=None, survival=None, my_pids=None,
                needs=None, taken=None, board_avail=None, pick=None):
    """Gather everything the player card shows. Kept separate from rendering so the
    dialog stays a thin shell."""
    from .. import config, schedule as SCH, value as V
    reg = ctx["registry"]
    pm = reg.meta(pid)
    vm = ctx.get("value")
    adp = ctx["adp_rank"](pm.name, pm.position)
    row = next((r for r in (board_avail or []) if str(r["pid"]) == str(pid)), {})
    tier = row.get("tier")

    tier_left = None
    if tier is not None and board_avail:
        tier_left = sum(1 for r in board_avail
                        if r.get("tier") == tier
                        and reg.meta(r["pid"]).position == pm.position)

    verdict = None
    if vm:
        left = vm.startable_left(pm.position, {str(x) for x in (taken or [])})
        mult = (V.roster_multiplier(pm.position, my_pids, ctx["roster_slots"], reg)
                if my_pids is not None else None)
        verdict = V.grab_verdict(survival, left, is_need=(pm.position in (needs or set())),
                                 mult=mult)

    # bye-week clash: how many of your CURRENT starters already sit out that week
    bye = (ctx.get("byes") or {}).get(pm.team)
    clash = 0
    if bye and my_pids:
        clash = sum(1 for p in my_pids
                    if (ctx.get("byes") or {}).get(reg.meta(p).team) == bye)

    # market read: each source's own board position, and how far it sits from ours
    market = []
    for src, pool in (ctx.get("source_pools") or {}).items():
        hit = next((i + 1 for i, p in enumerate(pool) if str(p["pid"]) == str(pid)), None)
        if hit:
            market.append((src, hit, (adp - hit) if adp else None))
    market.sort(key=lambda m: m[1])
    if row.get("rank"):
        market.append(("your board", row["rank"], (adp - row["rank"]) if adp else None))

    return {
        "pm": pm, "pid": str(pid), "adp": adp, "tier": tier, "tier_left": tier_left,
        "overall": row.get("rank"), "pos_rank": ctx["pos_rank"].get(str(pid), ""),
        "vorp": vm.vorp_of(pid) if vm else None,
        "survival": survival, "verdict": verdict,
        "reach": reach_for(ctx, row or {"pid": pid, "name": pm.name}, pm, pick,
                           survival=survival, next_pick=next_pick),
        "synergy": V.synergy(pm, my_pids, reg) if my_pids else None,
        "juice": (ctx.get("juice") or {}).get(str(pid)),
        "slate": SCH.playoff_slate(pm.team, pm.position, ctx.get("dvp"), ctx.get("schedule"),
                                   weeks=SCH.playoff_weeks(ctx["meta"])),
        "season": config.current_season() - 1, "scoring": ctx["meta"].scoring,
        "prev_label": str(config.current_season() - 1),
        "market": market, "bye_clash": clash, "byes": ctx.get("byes"),
        "next_pick": next_pick,
    }


def player_card_dialog(ctx, pid, *, on_draft=None, on_star=None, queued=None, **facts_kw):
    """Open the player card as a real modal. Streamlit closes a dialog on any rerun,
    so Draft/Queue naturally dismiss it — no close-state to manage."""
    f = _card_facts(ctx, pid, **facts_kw)

    @st.dialog(f["pm"].name, width="large")
    def _dlg():
        # Two columns, not one long scroll: the action bar was overlapping the last
        # stats row, and halving the height fixes that at the source rather than
        # padding around it. This app is desktop-only, so the usual caveat about
        # st.columns stacking on a narrow viewport doesn't apply.
        st.markdown(PC.card_header_html(
            f["pm"], pid=f["pid"], pos_rank=f["pos_rank"], overall=f["overall"],
            adp=f["adp"], byes=f["byes"], reach=f["reach"], juice=f["juice"],
            verdict=f["verdict"]), unsafe_allow_html=True)
        left, right = st.columns(2, gap="medium")
        with left:
            st.markdown(PC.card_left_html(
                f["pm"], next_pick=f["next_pick"], survival=f["survival"],
                vorp=f["vorp"], tier=f["tier"], tier_left=f["tier_left"],
                reach=f["reach"], slate=f["slate"]), unsafe_allow_html=True)
        with right:
            st.markdown(PC.card_right_html(
                f["pm"], pid=f["pid"], adp=f["adp"], market=f["market"],
                synergy=f["synergy"], bye_clash=f["bye_clash"], byes=f["byes"],
                season=f["season"], prev_label=f["prev_label"]), unsafe_allow_html=True)
        cols = st.columns([2, 1])
        if on_draft and cols[0].button(f'Draft {f["pm"].name}', use_container_width=True,
                                       key=f"pcd_draft_{pid}"):
            on_draft(pid)
        if on_star:
            starred = str(pid) in {str(x) for x in (queued or set())}
            if cols[1].button("★ Queued" if starred else "☆ Queue", use_container_width=True,
                              key=f"pcd_star_{pid}"):
                on_star(pid)

    _dlg()
