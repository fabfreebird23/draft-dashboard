"""In-season — your roster for the week ahead, scored on the league's own numbers.

Deliberately honest about where we are in the calendar. Before a league has
drafted, "your roster" is just your keepers, and there is no meaningful lineup to
set — so the screen says that rather than rendering an empty optimiser and letting
you think it's broken.

Projections come from the league's OWN host (Sleeper for Sleeper, ESPN for ESPN)
so the numbers here match the site you actually set the lineup on. That matters
most for the ESPN league, whose scoring our own weights can't reproduce.
"""
from __future__ import annotations

import streamlit as st

from .. import config, phase as PH, projections as PROJ
from . import components as C

_START_WEEK = 1


def _current_week(season: int) -> int:
    """NFL week, clamped to the regular season. Sleeper's state endpoint is the
    cheapest source and is right for both platforms — the calendar is the NFL's,
    not the host's."""
    try:
        from .. import sleeper_client as api
        st_ = api.get_state() if hasattr(api, "get_state") else {}
        wk = int((st_ or {}).get("week") or 0)
        return max(_START_WEEK, min(18, wk or _START_WEEK))
    except Exception:  # noqa: BLE001
        return _START_WEEK


def render(ctx, summary=None) -> None:
    meta, reg = ctx["meta"], ctx["registry"]
    season = config.current_season()
    week = _current_week(season)

    drafted = bool(summary and summary.phase == PH.IN)
    st.markdown(f'<div class="dr-h dr-title">Week {week}</div>', unsafe_allow_html=True)

    if not drafted:
        when = summary.note if summary else "This league hasn't drafted yet."
        st.info(f"**{meta.name} hasn't drafted yet.** {when}\n\n"
                "Lineups open once the draft is done. Until then the numbers below "
                "are a preview of what this screen will use — week "
                f"{week} projections from "
                f"{'ESPN' if meta.platform == 'espn' else 'Sleeper'}, this league's "
                "own scoring.")

    with st.spinner(f"Loading week {week} projections…"):
        wk = PROJ.for_league(meta, reg, season, week=week,
                             espn_s2=ctx.get("espn_s2"), swid=ctx.get("swid"))
    if not wk:
        st.warning(f"No week {week} projections available from "
                   f"{'ESPN' if meta.platform == 'espn' else 'Sleeper'} yet.")
        return

    byes = ctx.get("byes") or {}
    rows = []
    for pid, pts in wk.items():
        try:
            pm = reg.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        if pm.position not in ("QB", "RB", "WR", "TE"):
            continue
        rows.append((pts, pid, pm, byes.get(pm.team)))
    rows.sort(reverse=True, key=lambda r: r[0])

    st.caption(f"Top week-{week} projections · "
               f"{'ESPN' if meta.platform == 'espn' else 'Sleeper'} · "
               f"{len(wk)} players projected · "
               f"{C.age_phrase(0)} — weekly numbers are fetched live, never cached, "
               "because they move with news right up to kickoff.")

    head = st.columns([0.5, 3, 1, 1, 1])
    for col, lbl in zip(head, ("#", "PLAYER", "POS", "BYE", "PROJ")):
        col.markdown(f'<div class="pcd-sl">{lbl}</div>', unsafe_allow_html=True)
    for i, (pts, pid, pm, bye) in enumerate(rows[:25], 1):
        c = st.columns([0.5, 3, 1, 1, 1])
        c[0].markdown(f'<span class="pcd-tn">{i}</span>', unsafe_allow_html=True)
        c[1].markdown(f"**{pm.name}** · {pm.team}")
        c[2].markdown(f'<span class="pcd-chip">{pm.position}</span>', unsafe_allow_html=True)
        c[3].markdown(f"{bye or '—'}")
        c[4].markdown(f"**{pts:.1f}**")
