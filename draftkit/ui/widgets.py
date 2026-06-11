"""Shared interactive widgets used by both the mock and live tabs."""
from __future__ import annotations

import streamlit as st

from .. import draft_history, theme
from . import components as C
from . import playercard as PC


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
                    show_bands=True, on_star=None, queued=None) -> None:
    """Best-available board where the WHOLE player row is the draft button
    (no separate button). Position-colored left bar (scoped `[class*="_brow_<POS>"]`),
    bold color-coded tier bands, and a survival % (chance the player lasts to your
    next pick). `view`='List' groups by overall tier; 'By position' splits into
    QB/RB/WR/TE columns grouped by per-position tier."""
    reg, pick = ctx["registry"], current_pick
    pos_tier, pos_rank, adp_rank = ctx["pos_tier"], ctx["pos_rank"], ctx["adp_rank"]
    byes = ctx.get("byes", {})
    vm = ctx.get("value")

    # Streamlit button labels support markdown (bold + :color[]) — use it to make
    # the rank / name / meta / value visually distinct instead of one flat string.
    poscol = {"QB": "red", "RB": "green", "WR": "blue", "TE": "orange"}

    def label(r, pm):
        adp = adp_rank(pm.name, pm.position)
        pr = pos_rank.get(str(r["pid"]), pm.position)
        bye = byes.get(pm.team, "")
        d = (adp - pick) if (adp and pick) else 0
        vt = f"  :red[▼+{int(d)}]" if d >= 8 else (f"  :violet[▲{int(d)}]" if d <= -8 else "")
        adps = int(adp) if adp else "—"
        bye_s = f" · Bye {bye}" if bye else ""
        pc = poscol.get(pm.position, "gray")
        meta = f":gray[{pm.team} · ADP {adps}{bye_s}]"
        v = vm.vorp_of(r["pid"]) if vm else None
        vchip = ""
        if v is not None:
            vchip = f"  :{'green' if v >= 0 else 'red'}[**V {'+' if v >= 0 else ''}{v:.0f}**]"
        return f':{pc}[**{pr}**] **{r["name"]}** {meta}{vchip}{vt}'

    def compact_label(r, pm):
        """Short label for the narrow by-position columns: rank, short name, value."""
        pr = pos_rank.get(str(r["pid"]), pm.position)
        pc = poscol.get(pm.position, "gray")
        v = vm.vorp_of(r["pid"]) if vm else None
        vchip = ""
        if v is not None:
            vchip = f"  :{'green' if v >= 0 else 'red'}[V {'+' if v >= 0 else ''}{v:.0f}]"
        return f':{pc}[**{pr}**] **{C.short_name(r["name"])}**{vchip}'

    def emit_row(r, compact=False):
        pm = reg.meta(r["pid"])
        rk = f'{key_prefix}_brow_{pm.position}_{r["pid"]}'
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

        # a ★ to add/remove the player from your queue, beside the row (List view)
        if on_star is not None and not compact:
            sc_ = st.columns([0.5, 8], gap="small")
            with sc_[0]:
                with st.container(key=f"{key_prefix}_qstar_{pid}"):
                    starred = pid in (queued or set())
                    if st.button("★" if starred else "☆", key=f"{key_prefix}_star_{pid}",
                                 use_container_width=True):
                        on_star(pid)
            with sc_[1]:
                _player_btn()
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
                    taken=None) -> None:
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
        tier = next((r.get("tier") for r in board_avail if str(r["pid"]) == pid), None)

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
            verdict = V.grab_verdict(sv, left, is_need=(pm.position in (needs or set())))
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
                marg=marg, sos=sos),
            unsafe_allow_html=True)
        if draft_fn is not None:
            if st.button(f"Draft {pm.name}", key=f"{widget_key}_spdraft", type="primary",
                         use_container_width=True):
                draft_fn(pid)


def queue_manager(ctx, qkey, ranks, taken, registry, widget_key) -> None:
    """Pick-queue UI: a searchable multiselect builds the queue; it renders as a
    watchlist with drafted players struck through, and drives the recommendation.

    `qkey` is the shared session store (queue persists across tabs); `widget_key`
    must be unique per tab so the two multiselects don't collide."""
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
        # user edited the multiselect → push selection to the shared queue
        sel = st.session_state.get(ms_key, [])
        st.session_state[qkey] = [label_to_pid[l] for l in sel if l in label_to_pid]

    # Reconcile the widget value FROM the queue (so the ★ row toggles show up here),
    # but not on a run where the user just edited it (the callback already synced).
    if set(st.session_state.get(ms_key, [])) != set(cur_labels):
        st.session_state[ms_key] = cur_labels
    with st.expander(f"My Queue ({n_avail} available)"):
        st.multiselect("Queue players to target", options, key=ms_key,
                       on_change=_sync_to_queue)
        st.caption("Tap the ☆ next to a player on the board to add them too.")
        st.markdown(C.queue_html([str(x) for x in st.session_state.get(qkey, [])],
                                 taken_s, registry), unsafe_allow_html=True)
