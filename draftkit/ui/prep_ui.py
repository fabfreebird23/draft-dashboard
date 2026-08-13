"""Pre-season Overview — the prep desk.

The landing screen for a league that hasn't drafted. Answers, in order, the
questions you actually have: how long have I got, where am I picking, is my board
current, and what's left to do. Each card carries the action that resolves it, so
the screen is a to-do list rather than a status report.

Every number is read from state the app already loads. Where something genuinely
isn't known it says so rather than showing a plausible placeholder.

Keepers are read-only: each league's keeper and contract logic lives in its own
standalone hub, and Bloody Sunday owns drafting and in-season.
"""
from __future__ import annotations

import time

import streamlit as st

from .. import config, draft_stages as DS, keepers as K, phase as PH
from . import components as C

_HUBS = {
    "1310907162930733056": ("Kreeper hub", "https://kreeper-league.streamlit.app"),
    "1312885282554535936": ("B&B hub", "https://babies-and-boomer.streamlit.app"),
    "1388606375239643136": ("7½ Men hub", "https://seven-half-men.streamlit.app"),
}

def _my_slot(ctx):
    """(label, slot) for the configured team. No picker — every league here is his,
    so the team is configured on the league and can't drift to someone else's."""
    names = ctx.get("slot_names") or []
    owners = ctx.get("owner_by_slot") or {}
    mine = ctx.get("my_team")
    for slot, key in owners.items():
        if mine and str(key) == str(mine) and slot < len(names):
            return names[slot], slot
    return None, None


def _picks_for_slot(ctx, slot, limit=4):
    """Your first few picks, via the traded-pick-aware owner map so a dealt pick
    isn't listed as yours and a keeper-consumed slot isn't listed at all."""
    if slot is None:
        return []
    n = len(ctx.get("slot_names") or []) or 1
    owner = ctx.get("pick_owner_slot")
    kept = (ctx.get("keepers") or {}).get("by_overall") or {}
    out = []
    for ov in range(1, n * ctx["meta"].draft_rounds + 1):
        if owner and owner(ov) == slot and ov not in kept:
            out.append(f"{(ov - 1) // n + 1}.{(ov - 1) % n + 1:02d}")
            if len(out) >= limit:
                break
    return out


def _keeper_progress(ctx):
    """(locked, expected, shortfall_note). Sleeper only exposes a flat max, so the
    per-league regular/rookie split comes from that league's own config."""
    kept = len((ctx.get("keepers") or {}).get("kept_pids") or [])
    try:
        rules = K.load_keeper_rules(str(ctx["meta"].league_id))
        per = (rules.get("max_regular_keepers") or 0) + (rules.get("max_rookie_keepers") or 0)
    except Exception:  # noqa: BLE001
        per = 0
    teams = len(ctx.get("slot_names") or []) or ctx["meta"].num_teams
    expected = per * teams if per else 0

    note = ""
    raw = ctx.get("keepers_raw") or {}
    if per and raw:
        names = ctx.get("slot_names") or []
        owners = ctx.get("owner_by_slot") or {}
        by_owner = {str(owners.get(i)): (names[i] if i < len(names) else "?")
                    for i in range(len(names))}
        short = [(by_owner.get(str(o), "?"), per - len(v or []))
                 for o, v in raw.items() if len(v or []) < per]
        if short:
            who, n = short[0]
            note = (f"{who} still owes {n}" if len(short) == 1
                    else f"{len(short)} teams still owe keepers")
        else:
            note = "all in"
    return kept, expected, note


def _goto(section: str):
    """Ask app.py to switch sections on the NEXT run.

    Writing st.session_state["nav_section"] here raises StreamlitAPIException:
    the nav is a segmented_control keyed on that name and it is instantiated
    before any section body renders. app.py drains "nav_goto" at the top of the
    run, ahead of the widget."""
    st.session_state["nav_goto"] = section
    st.rerun()


def _tile(key, label, value, sub):
    with st.container(key=key):
        st.markdown(f'<div class="tl">{label}</div><div class="tv">{value}</div>'
                    f'<div class="ts">{sub}</div>', unsafe_allow_html=True)


def render(ctx, summary=None) -> None:
    meta = ctx["meta"]
    names = ctx.get("slot_names") or []
    lid = str(meta.league_id)

    _label, slot = _my_slot(ctx)
    st.markdown(f'<div class="dr-h dr-title">Draft prep'
                f'{" · " + _label if _label else ""}</div>', unsafe_allow_html=True)

    # ---- the three numbers that decide what you do next ----
    tiles = st.columns(3)
    days = summary.days_to_draft if summary else None
    with tiles[0]:
        if days is not None and days >= 0:
            when = config.fmt_local(summary.draft_at,
                                    "%a, %b %-d · %-I:%M%p").replace("AM", "am").replace("PM", "pm")
            _n = max(1, int(round(days)))
            _tile(f"pk1_{lid}", "draft in", f"{_n} day" if _n == 1 else f"{_n} days", when)
        else:
            _tile(f"pk1_{lid}", "draft in", "—", "no date set on the platform yet")
    with tiles[1]:
        picks = _picks_for_slot(ctx, slot)
        _tile(f"pk2_{lid}", "your slot", picks[0] if picks else "—",
              ("then " + " · ".join(picks[1:])) if len(picks) > 1
              else "draft order not published yet")
    with tiles[2]:
        kept, expected, note = _keeper_progress(ctx)
        val = (f'{kept}<span class="pk-of"> / {expected}</span>') if expected else str(kept)
        _tile(f"pk3_{lid}", "keepers locked", val, note or "none submitted yet")

    # ---- what's left to do, each with the action that resolves it ----
    st.markdown('<div class="dr-h">Where things stand</div>', unsafe_allow_html=True)
    row1 = st.columns(3)

    ranks = st.session_state.get(ctx["ranks_key"]) or []
    age = ctx.get("board_age_h")
    stale = age is not None and age / 24.0 >= 7
    with row1[0], st.container(key=f"pc1_{lid}"):
        st.markdown(
            f'<div class="pk-t">My Rankings</div>'
            f'<div class="pk-m">{len(ranks)} players · UDK · '
            f'{C.age_phrase(age) if age is not None else "age unknown"}</div>'
            f'<div class="pk-n {"pk-amb" if stale else "pk-ok"}">'
            f'{"Stale enough to matter — pull a fresh board." if stale else "Board is current."}'
            f'</div>', unsafe_allow_html=True)
        if st.button("Pull from UDK", key=f"pk_go_ranks_{lid}", type="primary",
                     use_container_width=True):
            _goto("My Rankings")

    hub = _HUBS.get(lid)
    with row1[1], st.container(key=f"pc2_{lid}"):
        kept, expected, _ = _keeper_progress(ctx)
        st.markdown(
            f'<div class="pk-t">Keepers{" ↗" if hub else ""}</div>'
            f'<div class="pk-m">{"Lives in the " + hub[0] if hub else "not a keeper league"}</div>'
            f'<div class="pk-n {"pk-ok" if kept else "pk-nil"}">'
            f'{f"{kept} locked league-wide. Read-only here." if kept else "Nothing submitted yet."}'
            f'</div>', unsafe_allow_html=True)
        if hub:
            st.link_button(f"Open {hub[0]} ↗", hub[1], use_container_width=True)

    stages = DS.stages_for(lid)
    with row1[2], st.container(key=f"pc3_{lid}"):
        st.markdown(
            f'<div class="pk-t">Mock Draft</div>'
            f'<div class="pk-m">AI opponents from past drafts</div>'
            f'<div class="pk-n pk-nil">'
            f'{"Two stages: " + " then ".join(s.name.lower() for s in stages) + "." if stages else "Practise the board before it counts."}'
            f'</div>', unsafe_allow_html=True)
        if st.button("Run a mock", key=f"pk_go_mock_{lid}", type="primary",
                     use_container_width=True):
            _goto("Mock Draft")

    row2 = st.columns(3)
    live = summary.phase == PH.LIVE if summary else False
    offline = meta.platform == "espn" and not (summary and summary.draft_at)
    with row2[0], st.container(key=f"pc4_{lid}"):
        st.markdown(
            f'<div class="pk-t">Live Draft</div>'
            f'<div class="pk-m">syncs picks from '
            f'{"ESPN" if meta.platform == "espn" else "Sleeper"}</div>'
            f'<div class="pk-n {"pk-red" if live else "pk-nil"}">'
            f'{"Draft is LIVE — open the war room." if live else ("ESPN has this draft as offline with no date, so there is nothing to sync." if offline else "Arms automatically when the draft opens.")}'
            f'</div>', unsafe_allow_html=True)
        if st.button("Open war room", key=f"pk_go_live_{lid}",
                     type="primary" if live else "secondary", use_container_width=True):
            _goto("Live Draft")
