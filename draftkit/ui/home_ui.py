"""Home — every league at once, sorted by what actually needs you.

Each card shows the SINGLE most urgent thing about that league, never a summary,
and the ordering does the triage so you never have to open a league to find out
whether it needs you.

Kept cheap: `phase.summary` is two small API calls per league, not a full draft
context. Four contexts here would mean four registries, four ADP joins and four
keeper fetches before anything appeared.

LAYOUT NOTE: the card is drawn by styling the st.container, NOT by emitting a
<div class="card"> around everything. A wrapper div from st.markdown does not wrap
a widget — Streamlit closes each markdown block on its own — so the Draft-prep
button and the hub link ended up rendered BELOW the box instead of inside it.
Everything that belongs in the card therefore goes inside `st.container(key=...)`
and the border/background hang off `.st-key-<key>`.
"""
from __future__ import annotations

import streamlit as st

from .. import phase as PH, theme

_TONE = {"red": ("#fdecec", "#8c2320", "#b3261e"),
         "amber": ("#fdf3e3", "#7a4f06", "#a8570d"),
         "ok": ("#e6f4ec", "#14603f", "#1d7a55"),
         "nil": ("#eef2f6", "#54606d", "#8e9aa7")}

# Where each league's keeper/contract logic actually lives. Those hubs stay
# standalone by design — Draft Room owns drafting and in-season, not keepers.
HUBS = {
    "1310907162930733056": ("Kreeper hub", "https://kreeper-league.streamlit.app"),
    "1312885282554535936": ("B&B hub", "https://babies-and-boomer.streamlit.app"),
    "1388606375239643136": ("7½ Men hub", "https://seven-half-men.streamlit.app"),
}


def render(presets, on_pick, board_age_fn=None) -> None:
    st.markdown(f'<h1>{theme.logo_html(40)}</h1>', unsafe_allow_html=True)

    rows = []
    for p in presets:
        age = None
        if board_age_fn:
            try:
                age = board_age_fn(f"{p['platform']}_{p['league_id']}")
            except Exception:  # noqa: BLE001 — a slow age lookup must not blank Home
                age = None
        rows.append((p, PH.summary(p, age)))
    rows.sort(key=lambda r: PH.sort_key(r[1]))

    st.markdown('<div class="hm-h">Your leagues</div>', unsafe_allow_html=True)
    cols = st.columns(len(rows) or 1)
    for col, (preset, s) in zip(cols, rows):
        bg, fg, dot = _TONE.get(s.tone, _TONE["nil"])
        # Distinct prefix from every widget key inside the card: a container key of
        # "hm_…" is also a prefix of the button's "hm_open_…" container, so
        # [class*="st-key-hm_"] styled the BUTTON as a second card — a nested box
        # around every action. "hmcard_" can't collide.
        key = f"hmcard_{s.platform}_{s.league_id}"
        with col, st.container(key=key):
            # Per-card accent — the tone varies per league, so it can't live in a
            # static class. Same trick the board rows use for headshots.
            st.markdown(f'<style>.st-key-{key}{{border-top-color:{dot}}}</style>',
                        unsafe_allow_html=True)
            bits = [b for b in (s.platform.upper(),
                                f"{s.num_teams} teams" if s.num_teams else "",
                                {"pre": "pre-season", "live": "drafting now",
                                 "in": "in-season", "done": "season over"}.get(s.phase, ""))
                    if b]
            st.markdown(
                f'<div class="hm-name">{s.name or s.label}</div>'
                f'<div class="hm-meta">{" · ".join(bits)}</div>'
                f'<div class="hm-note" style="background:{bg};color:{fg}">'
                f'<i style="background:{dot}"></i><span>{s.note}</span></div>',
                unsafe_allow_html=True)
            label = ("Open war room" if s.phase == PH.LIVE else
                     "This week" if s.phase in (PH.IN, PH.DONE) else "Draft prep")
            if st.button(label, key=f"hmgo_{s.league_id}", use_container_width=True,
                         type="primary"):
                on_pick(preset)
            hub = HUBS.get(str(s.league_id))
            if hub:
                st.markdown(f'<a class="hm-hub" href="{hub[1]}" target="_blank" '
                            f'rel="noopener">{hub[0]} ↗</a>', unsafe_allow_html=True)
