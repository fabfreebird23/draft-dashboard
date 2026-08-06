"""Pre-season Overview — the prep desk.

The landing screen for a league that hasn't drafted. Answers, in order: how long
have I got, where am I picking, is my board current, and what's left to do. Every
number is read from state the app already loads — nothing here is estimated, and
where something genuinely isn't known it says so rather than showing a plausible
placeholder.

Keepers are read-only here on purpose. Each league's keeper and contract logic
lives in its own standalone hub; Draft Room owns drafting and in-season.
"""
from __future__ import annotations

import streamlit as st

from .. import draft_stages as DS, phase as PH
from . import components as C

_HUBS = {
    "1310907162930733056": ("Kreeper hub", "https://kreeper-league.streamlit.app"),
    "1312885282554535936": ("B&B hub", "https://babies-and-boomer.streamlit.app"),
    "1388606375239643136": ("7½ Men hub", "https://seven-half-men.streamlit.app"),
}


# A keyed selectbox writes its default into session_state on first render, so a
# plain list would silently make the FIRST manager "your team" — and then show his
# picks as yours. An explicit prompt option means unselected stays unselected.
PROMPT = "Select your team…"


def team_options(names):
    return [PROMPT] + list(names)


def _my_slot(ctx):
    """(label, slot_index) for the team picked on this league, or (None, None).
    Shares the `myteam_` key with the in-season screen — one answer to 'which team
    is mine' per league, not one per tab."""
    names = ctx.get("slot_names") or []
    sel = st.session_state.get(f"myteam_{ctx['league_key']}")
    if sel and sel != PROMPT and sel in names:
        return sel, names.index(sel)
    return None, None


def _picks_for_slot(ctx, slot):
    """Your first few overall picks, using the traded-pick-aware owner map so a
    dealt pick isn't listed as yours."""
    if slot is None:
        return []
    n = len(ctx.get("slot_names") or []) or 1
    rounds = ctx["meta"].draft_rounds
    owner = ctx.get("pick_owner_slot")
    kept = (ctx.get("keepers") or {}).get("by_overall") or {}
    out = []
    for ov in range(1, n * rounds + 1):
        if owner and owner(ov) == slot and ov not in kept:
            out.append(f"{(ov - 1) // n + 1}.{(ov - 1) % n + 1:02d}")
        if len(out) >= 4:
            break
    return out


def render(ctx, summary=None) -> None:
    meta = ctx["meta"]
    names = ctx.get("slot_names") or []
    lid = str(meta.league_id)

    # ---- team picker: one answer per league, shared with In-season ----
    head = st.columns([2.4, 1.6, 2])
    head[0].markdown('<div class="dr-h dr-title">Draft prep</div>', unsafe_allow_html=True)
    if names:
        sk = f"myteam_{ctx['league_key']}"
        opts = team_options(names)
        cur = st.session_state.get(sk)
        head[1].selectbox("Your team", opts,
                          index=opts.index(cur) if cur in opts else 0, key=sk)
    label, slot = _my_slot(ctx)

    # ---- the three numbers that decide what you do next ----
    days = summary.days_to_draft if summary else None
    tiles = st.columns(3)
    with tiles[0], st.container(key=f"pk1_{lid}"):
        if days is not None and days >= 0:
            st.markdown(f'<div class="tl">draft in</div><div class="tv">{max(1, int(round(days)))} days</div>'
                        f'<div class="ts">{summary.note.split("·")[-1].strip().rstrip(".") if summary else ""}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<div class="tl">draft in</div><div class="tv">—</div>'
                        '<div class="ts">no date set on the platform yet</div>',
                        unsafe_allow_html=True)
    with tiles[1], st.container(key=f"pk2_{lid}"):
        picks = _picks_for_slot(ctx, slot)
        st.markdown(f'<div class="tl">your picks</div>'
                    f'<div class="tv">{picks[0] if picks else "—"}</div>'
                    f'<div class="ts">'
                    f'{" · ".join(picks[1:]) if len(picks) > 1 else "choose your team above"}'
                    f'</div>', unsafe_allow_html=True)
    with tiles[2], st.container(key=f"pk3_{lid}"):
        kept = len((ctx.get("keepers") or {}).get("kept_pids") or [])
        st.markdown(f'<div class="tl">keepers locked</div><div class="tv">{kept}</div>'
                    f'<div class="ts">{"league-wide" if kept else "none submitted yet"}</div>',
                    unsafe_allow_html=True)

    # ---- what's left to do ----
    st.markdown('<div class="dr-h">Where things stand</div>', unsafe_allow_html=True)
    cards = st.columns(4)

    ranks = st.session_state.get(ctx["ranks_key"]) or []
    age = ctx.get("board_age_h")
    stale = age is not None and age / 24.0 >= 7
    with cards[0], st.container(key=f"pc1_{lid}"):
        st.markdown(f'<div class="pk-t">My Rankings</div>'
                    f'<div class="pk-m">{len(ranks)} players · '
                    f'{C.age_phrase(age) if age is not None else "age unknown"}</div>'
                    f'<div class="pk-n {"pk-amb" if stale else "pk-ok"}">'
                    f'{"Stale enough to matter — pull a fresh board." if stale else "Board is current."}'
                    f'</div>', unsafe_allow_html=True)

    hub = _HUBS.get(lid)
    with cards[1], st.container(key=f"pc2_{lid}"):
        st.markdown(f'<div class="pk-t">Keepers</div>'
                    f'<div class="pk-m">{"read-only here" if hub else "not a keeper league"}</div>'
                    f'<div class="pk-n pk-nil">'
                    f'{"Costs and contracts live in the " + hub[0] + "." if hub else "No keeper hub for this league."}'
                    f'</div>', unsafe_allow_html=True)
        if hub:
            st.markdown(f'<a class="hm-hub" href="{hub[1]}" target="_blank" '
                        f'rel="noopener">{hub[0]} ↗</a>', unsafe_allow_html=True)

    stages = DS.stages_for(lid)
    with cards[2], st.container(key=f"pc3_{lid}"):
        st.markdown(f'<div class="pk-t">Mock Draft</div>'
                    f'<div class="pk-m">AI opponents from past drafts</div>'
                    f'<div class="pk-n pk-nil">'
                    f'{"Two stages: " + " then ".join(s.name.lower() for s in stages) + "." if stages else "Practise the board before it counts."}'
                    f'</div>', unsafe_allow_html=True)

    live = summary.phase == PH.LIVE if summary else False
    with cards[3], st.container(key=f"pc4_{lid}"):
        st.markdown(f'<div class="pk-t">Live Draft</div>'
                    f'<div class="pk-m">syncs picks from '
                    f'{"ESPN" if meta.platform == "espn" else "Sleeper"}</div>'
                    f'<div class="pk-n {"pk-red" if live else "pk-nil"}">'
                    f'{"Draft is LIVE — open the war room." if live else "Arms itself when the draft opens."}'
                    f'</div>', unsafe_allow_html=True)

    if meta.platform == "espn":
        st.caption("ESPN reports this league's draft as **offline** with no date, so "
                   "there's nothing for Live Draft to sync. Mocks work either way.")
