"""Draft Room — a standalone multi-platform fantasy mock + live draft dashboard.

Import any Sleeper or ESPN league, pull your UDK rankings, and run a mock draft or
a live draft assistant with a FantasyPros-style war room (tiered best-available
board, my-team lineup, snake draft grid, on-the-clock header). Both platforms
render from one normalized Pick shape.
"""
from __future__ import annotations

import streamlit as st

from draftkit import config, players, theme
from draftkit.adp import consensus
from draftkit.names import normalize_name
from draftkit.providers import get_provider, EspnAuthError
from draftkit import rankings as rankings_mod
from draftkit.ui import assistant_ui, mock_ui, rankings_ui

st.set_page_config(page_title="Draft Room — Mock + Live Draft", page_icon="🏈", layout="wide")
theme.inject(st)


# ----------------------------------------------------------------- cached data
@st.cache_resource(show_spinner="Loading player index…")
def get_registry(season: int):
    return players.build_registry(season)


@st.cache_data(ttl=3600, show_spinner="Building consensus ADP…")
def get_adp(season: int):
    df = consensus.load(season)
    if df is None or df.empty:
        try:
            df = consensus.build(season)
        except Exception:  # noqa: BLE001 - ADP is best-effort; mock degrades without it
            df = consensus.load(season)
    return df, consensus.adp_lookup(season)


def _secret(name: str) -> str:
    try:
        return st.secrets.get(name, "") or ""
    except Exception:  # noqa: BLE001
        return ""


# Your saved leagues — one-click import (edit this list to add/remove).
SAVED_LEAGUES = [
    {"label": "🏈 The Kreeper League", "platform": "sleeper",
     "league_id": "1310907162930733056", "season": 2026},
    {"label": "👶 Babies and Boomer", "platform": "sleeper",
     "league_id": "1312885282554535936", "season": 2026},
]


def _select_league(preset: dict) -> None:
    st.session_state.league = {
        "platform": preset["platform"], "league_id": preset["league_id"],
        "season": int(preset.get("season") or config.current_season()),
        "espn_s2": preset.get("espn_s2"), "swid": preset.get("swid"),
    }
    st.rerun()


# ------------------------------------------------------------------ league pick
def league_picker():
    st.markdown(f'<h1>{theme.logo_html(40)}</h1>', unsafe_allow_html=True)

    if SAVED_LEAGUES:
        st.markdown("##### Your leagues")
        cols = st.columns(len(SAVED_LEAGUES))
        for col, preset in zip(cols, SAVED_LEAGUES):
            if col.button(preset["label"], use_container_width=True, key=f"saved_{preset['league_id']}"):
                _select_league(preset)
        st.divider()

    st.caption("…or import another league. Sleeper is public by league ID; ESPN works "
               "for public leagues by ID, and private leagues with espn_s2 + SWID cookies.")
    platform = st.radio("Platform", ["Sleeper", "ESPN"], horizontal=True)
    with st.form("import"):
        if platform == "Sleeper":
            league_id = st.text_input("Sleeper league ID",
                                      help="The number in your league URL: sleeper.com/leagues/<ID>/…")
            season, s2, swid = config.current_season(), None, None
        else:
            league_id = st.text_input("ESPN league ID",
                                      help="The leagueId in your ESPN URL.")
            season = st.number_input("Season", min_value=2018, max_value=2100,
                                     value=config.current_season(), step=1)
            with st.expander("Private league? Paste your ESPN cookies"):
                s2 = st.text_input("espn_s2", value=_secret("espn_s2"), type="password")
                swid = st.text_input("SWID", value=_secret("swid"))
        go = st.form_submit_button("Import league", type="primary")
    if go and league_id:
        st.session_state.league = {
            "platform": platform.lower(), "league_id": league_id.strip(),
            "season": int(season), "espn_s2": (s2 or None), "swid": (swid or None),
        }
        st.rerun()


def build_context(sel: dict) -> dict:
    registry = get_registry(sel["season"])
    provider = get_provider(sel["platform"], sel["league_id"], sel["season"], registry,
                            espn_s2=sel.get("espn_s2"), swid=sel.get("swid"))
    meta = provider.get_league_meta()
    order = provider.get_draft_order()
    slot_names = [t.name for t in order] or [f"Team {i+1}" for i in range(meta.num_teams)]
    # ADP for the current season (the draftable pool + best-available ranks).
    adp_df, adp_lk = get_adp(config.current_season())

    def adp_rank(name: str, position: str = ""):
        key = f"{normalize_name(name)}|{position.lower()}" if position else None
        if key and key in adp_lk:
            return adp_lk[key]
        return adp_lk.get(normalize_name(name))

    adp_pool = rankings_mod.adp_pool(registry, adp_df)
    # Positional rank (RB5, WR7…) keyed by sleeper pid, from ADP order.
    pos_rank, counts = {}, {}
    for p in adp_pool:
        pos = p["pos"]
        counts[pos] = counts.get(pos, 0) + 1
        pos_rank[str(p["pid"])] = f"{pos}{counts[pos]}"

    league_key = f"{meta.platform}_{meta.league_id}"
    return {
        "registry": registry, "provider": provider, "meta": meta,
        "slot_names": slot_names, "roster_slots": provider.get_roster_slots(),
        "adp_df": adp_df, "adp_rank": adp_rank, "adp_pool": adp_pool,
        "pos_rank": pos_rank,
        "league_key": league_key, "ranks_key": f"ranks_{league_key}",
    }


def main():
    if "league" not in st.session_state:
        league_picker()
        return

    sel = st.session_state.league
    try:
        ctx = build_context(sel)
    except EspnAuthError as e:
        st.error(str(e))
        if st.button("← Back to import"):
            del st.session_state.league
            st.rerun()
        return
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't import that league ({type(e).__name__}: {e}).")
        if st.button("← Back to import"):
            del st.session_state.league
            st.rerun()
        return

    meta = ctx["meta"]
    head = st.columns([4, 1])
    with head[0]:
        st.markdown(f'<h2>{theme.logo_html(28, tag=None)} · {meta.name}</h2>', unsafe_allow_html=True)
        st.caption(f"{meta.platform.upper()} · {meta.num_teams} teams · {meta.draft_rounds} rounds "
                   f"· {meta.scoring.upper()} · {len(ctx['adp_pool'])} players in ADP pool")
    with head[1]:
        if st.button("↺ Switch league"):
            del st.session_state.league
            st.rerun()

    t1, t2, t3 = st.tabs(["📥 My Rankings", "🎯 Live Draft Assistant", "🧪 Mock Draft"])
    with t1:
        rankings_ui.render(ctx)
    with t2:
        assistant_ui.render(ctx)
    with t3:
        mock_ui.render(ctx)


main()
