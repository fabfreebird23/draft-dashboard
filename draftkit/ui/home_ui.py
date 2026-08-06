"""Home — every league at once, sorted by what actually needs you.

Replaces the bare league picker. The rule for this screen: each card shows the
SINGLE most urgent thing about that league, never a summary of everything. You
shouldn't have to pick a league to find out whether it needs you — the ordering
does the triage, so the league drafting this week sits above the one drafting next
month regardless of what else is true about either.

Kept deliberately cheap: `phase.summary` does two small API calls per league, not
a full draft context. Building four contexts here would mean four registries, four
ADP joins and four keeper fetches before anything appeared.
"""
from __future__ import annotations

import streamlit as st

from .. import phase as PH, theme

_TONE = {"red": ("#fdecec", "#8c2320", "#b3261e"),
         "amber": ("#fdf3e3", "#7a4f06", "#a8570d"),
         "ok": ("#e6f4ec", "#14603f", "#1d7a55"),
         "nil": ("#eef2f6", "#54606d", "#8e9aa7")}

# Where a league's keeper/contract logic actually lives. Those hubs stay
# standalone by design — Draft Room owns drafting and in-season, not keepers.
HUBS = {
    "1310907162930733056": ("Kreeper hub", "https://kreeper-league.streamlit.app"),
    "1312885282554535936": ("B&B hub", "https://babies-and-boomer.streamlit.app"),
    "1388606375239643136": ("7½ Men hub", "https://seven-half-men.streamlit.app"),
}


def card_html(s: PH.Summary) -> str:
    bg, fg, dot = _TONE.get(s.tone, _TONE["nil"])
    bits = [b for b in (s.platform.upper(),
                        f"{s.num_teams} teams" if s.num_teams else "",
                        {"pre": "pre-season", "live": "DRAFTING", "in": "in-season",
                         "done": "season over"}.get(s.phase, "")) if b]
    return (f'<div class="hm-card" style="border-top-color:{dot}">'
            f'<div class="hm-name">{s.name or s.label}</div>'
            f'<div class="hm-meta">{" · ".join(bits)}</div>'
            f'<div class="hm-note" style="background:{bg};color:{fg}">'
            f'<i style="background:{dot}"></i><span>{s.note}</span></div></div>')


def render(presets, on_pick, board_age_fn=None) -> None:
    """`presets` are the saved leagues; `on_pick(preset)` selects one."""
    st.markdown(f'<h1>{theme.logo_html(40)}</h1>', unsafe_allow_html=True)

    rows = []
    for p in presets:
        age = None
        if board_age_fn:
            try:
                age = board_age_fn(f"{p['platform']}_{p['league_id']}")
            except Exception:  # noqa: BLE001 — a slow/failed age must not blank Home
                age = None
        rows.append((p, PH.summary(p, age)))
    rows.sort(key=lambda r: PH.sort_key(r[1]))

    st.markdown('<div class="hm-h">Your leagues</div>', unsafe_allow_html=True)
    cols = st.columns(len(rows) or 1)
    for col, (preset, s) in zip(cols, rows):
        with col, st.container(key=f"hm_{s.league_id}"):
            st.markdown(card_html(s), unsafe_allow_html=True)
            label = ("Open war room" if s.phase == PH.LIVE else
                     "This week" if s.phase == PH.IN else "Draft prep")
            if st.button(label, key=f"hm_open_{s.league_id}", use_container_width=True,
                         type="primary"):
                on_pick(preset)
            hub = HUBS.get(str(s.league_id))
            if hub:
                st.markdown(f'<a class="hm-hub" href="{hub[1]}" target="_blank" '
                            f'rel="noopener">{hub[0]} ↗</a>', unsafe_allow_html=True)
