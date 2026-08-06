"""In-season — set this week's lineup, on the league's own numbers.

Honest about the calendar. Before a league drafts there is no roster and no lineup
to set, so the screen says that and shows what it WILL run on rather than
rendering an empty optimiser that just looks broken.

Projections come from the league's OWN host, so the numbers match the site you
actually set the lineup on. That matters most for the ESPN league, whose scoring
our own weights cannot reproduce.
"""
from __future__ import annotations

import streamlit as st

from .. import config, lineup as LU, phase as PH, projections as PROJ, rosters as RO

_START_WEEK = 1


def _current_week() -> int:
    """The NFL week. The calendar belongs to the NFL, not the host, so Sleeper's
    state endpoint is right for the ESPN league too. Pre-season reports 0, which
    clamps to week 1 — the first week anyone would be setting a lineup for."""
    try:
        from .. import sleeper_client as api
        wk = int((api.get_state() or {}).get("week") or 0)
        return max(_START_WEEK, min(18, wk or _START_WEEK))
    except Exception:  # noqa: BLE001
        return _START_WEEK


def _team_label(ctx, team_key):
    """Display name for the configured team, or '' if the roster map doesn't
    resolve it (a league whose draft order hasn't published yet)."""
    names, owners = ctx.get("slot_names") or [], ctx.get("owner_by_slot") or {}
    for slot, key in owners.items():
        if str(key) == str(team_key) and slot < len(names):
            return names[slot]
    return ""


def render(ctx, summary=None) -> None:
    meta, reg = ctx["meta"], ctx["registry"]
    season, week = config.current_season(), _current_week()
    host = "ESPN" if meta.platform == "espn" else "Sleeper"

    # No team picker: every league here is his, so the team is configured on the
    # league itself. A dropdown that defaults to the first manager was a live
    # hazard — it would have optimised someone else's roster.
    tkey = ctx.get("my_team")
    me = _team_label(ctx, tkey)
    st.markdown(f'<div class="dr-h dr-title">Week {week}'
                f'{" · " + me if me else ""}</div>', unsafe_allow_html=True)

    drafted = bool(summary and summary.phase in (PH.IN, PH.DONE))
    if not drafted:
        st.info(f"**{meta.name} hasn't drafted yet.** "
                f"{summary.note if summary else ''}\n\n"
                f"Lineups open once it has. Below is what this screen will run on: "
                f"week {week} projections from {host}, in this league's scoring.")

    with st.spinner(f"Loading week {week} projections from {host}…"):
        proj = PROJ.for_league(meta, reg, season, week=week,
                               espn_s2=ctx.get("espn_s2"), swid=ctx.get("swid"))
    if not proj:
        st.warning(f"No week {week} projections from {host} yet.")
        return

    roster = (RO.for_league(meta, reg, tkey, espn_s2=ctx.get("espn_s2"),
                            swid=ctx.get("swid"))
              if tkey else {"players": [], "starters": []})
    mine = roster.get("players") or []

    if not mine:
        st.caption(f"No roster yet for this team — showing the top week-{week} "
                   f"projections from {host} instead.")
        _preview(proj, reg, ctx)
        return

    lu = LU.optimize(mine, roster.get("starters"), ctx["roster_slots"], proj, reg,
                     byes=ctx.get("byes"), week=week)

    m = st.columns(3)
    m[0].metric("Optimal lineup", f"{lu.total:.1f}")
    m[1].metric("As currently set", f"{lu.current_total:.1f}")
    m[2].metric("Gain if you fix it", f"{lu.gain:+.1f}")
    if lu.problems:
        st.warning(" · ".join(lu.problems))
    else:
        st.success("Lineup is already optimal — nothing to change.")

    cur = {str(p) for p in (roster.get("starters") or [])}
    st.markdown('<div class="dr-h">Best lineup</div>', unsafe_allow_html=True)
    for s in lu.spots:
        c = st.columns([0.9, 3, 1.4, 0.9])
        c[0].markdown(f'<span class="pcd-sl">{s.slot}</span>', unsafe_allow_html=True)
        if s.pid:
            pm = reg.meta(s.pid)
            tag = "  :green[**swap in**]" if (cur and s.pid not in cur) else ""
            c[1].markdown(f"**{pm.name}** · {pm.position} · {pm.team}{tag}")
            c[2].markdown(f":red[**{s.note}**]" if s.note else "")
            c[3].markdown(f"**{s.points:.1f}**")
        else:
            c[1].markdown(":red[**— empty —**]")
    if lu.bench:
        st.markdown('<div class="dr-h">Bench</div>', unsafe_allow_html=True)
        for pid, pts in lu.bench[:8]:
            pm = reg.meta(pid)
            b = st.columns([0.9, 3, 1.4, 0.9])
            b[1].markdown(f"{pm.name} · {pm.position} · {pm.team}")
            b[3].markdown(f"{pts:.1f}")


def _preview(proj, reg, ctx) -> None:
    byes = ctx.get("byes") or {}
    rows = []
    for pid, pts in proj.items():
        try:
            pm = reg.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        if pm.position in ("QB", "RB", "WR", "TE"):
            rows.append((pts, pm, byes.get(pm.team)))
    rows.sort(key=lambda r: -r[0])
    for i, (pts, pm, bye) in enumerate(rows[:20], 1):
        c = st.columns([0.5, 3, 1, 1, 1])
        c[0].markdown(f'<span class="pcd-tn">{i}</span>', unsafe_allow_html=True)
        c[1].markdown(f"**{pm.name}** · {pm.team}")
        c[2].markdown(f'<span class="pcd-chip">{pm.position}</span>', unsafe_allow_html=True)
        c[3].markdown(f"{bye or '—'}")
        c[4].markdown(f"**{pts:.1f}**")
