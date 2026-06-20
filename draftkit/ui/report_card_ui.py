"""Draft Report Card tab — after a draft, grade every team and project the season.

Reads the finished board (mock or live), assembles each team's roster, and renders
a league-wide standings table (grade · projected record · playoff & title odds ·
projected finish) plus a per-team card with the best lineup. All the heavy lifting
lives in ``draftkit.grades``; this module just gathers rosters and paints them.
"""
from __future__ import annotations

import streamlit as st

from .. import grades, theme
from ..providers import EspnAuthError

_GRADE_COLOR = {
    "A+": "#22d3aa", "A": "#22d3aa", "A-": "#4ade80", "B+": "#84cc16",
    "B": "#a3e635", "B-": "#d9f99d", "C+": "#fbbf24", "C": "#f59e0b",
    "C-": "#fb923c", "D": "#f87171", "F": "#ef4444",
}
_POSCOL = {"QB": "#ef4444", "RB": "#22c55e", "WR": "#3b82f6", "TE": "#f59e0b",
           "K": "#a78bfa", "DST": "#94a3b8"}


def _assemble_rosters(ctx, source: str):
    """{slot: [pid, ...]} for every team, keepers + picks, from the chosen draft.
    Returns (rosters, picks_made, picks_total)."""
    owner = ctx["pick_owner_slot"]
    board = {int(ov): str(pid) for ov, pid in ctx["keepers"]["by_overall"].items()}
    keeper_overalls = set(board)
    if source == "Live draft":
        try:
            for p in ctx["provider"].get_live_picks():
                if p.overall and p.player and p.player.sleeper_pid:
                    board[int(p.overall)] = str(p.player.sleeper_pid)
        except EspnAuthError as e:
            st.error(str(e))
        except Exception:  # noqa: BLE001
            st.warning("Couldn't read the live draft — switch the source to Mock, or "
                       "sync the draft on the Live Draft Assistant tab first.")
    else:  # Mock draft
        state = st.session_state.get(f"mock_{ctx['league_key']}") or {}
        for ov, pid in (state.get("made") or {}).items():
            if pid:
                board[int(ov)] = str(pid)

    rosters = {s: [] for s in range(ctx["meta"].num_teams)}
    for ov, pid in board.items():
        rosters.setdefault(owner(int(ov)), []).append(pid)
    picks_made = len([ov for ov in board if ov not in keeper_overalls])
    total = ctx["meta"].num_teams * ctx["meta"].draft_rounds - len(keeper_overalls)
    return rosters, picks_made, max(0, total)


@st.cache_data(show_spinner=False)
def _report(sig, _ctx):
    rosters = {slot: list(pids) for slot, pids in sig}
    return grades.league_report(rosters, _ctx)


def _grade_pill(g: str) -> str:
    c = _GRADE_COLOR.get(g, "#94a3b8")
    return (f'<span style="display:inline-block;min-width:2.2em;text-align:center;'
            f'font-weight:800;color:#0e1424;background:{c};border-radius:7px;'
            f'padding:2px 8px;">{g}</span>')


def _odds_bar(pct, color) -> str:
    pct = pct or 0
    return (f'<div style="display:flex;align-items:center;gap:6px;">'
            f'<div style="flex:1;height:7px;border-radius:4px;background:rgba(148,163,184,.18);">'
            f'<div style="height:100%;width:{min(100, pct)}%;border-radius:4px;background:{color};">'
            f'</div></div><span style="min-width:2.6em;text-align:right;">{pct}%</span></div>')


def render(ctx) -> None:
    st.markdown('<div class="dr-h">🏁 Draft Report Card</div>', unsafe_allow_html=True)
    st.caption("After a draft, grade every team and project the season — records, "
               "playoff & title odds — from the rosters drafted, the value captured, "
               "and each manager's past results.")

    have_mock = bool((st.session_state.get(f"mock_{ctx['league_key']}") or {}).get("made"))
    default_src = "Live draft" if not have_mock else "Mock draft"
    src = st.radio("Grade which draft?", ["Mock draft", "Live draft"],
                   index=["Mock draft", "Live draft"].index(default_src),
                   horizontal=True, key=f"rc_src_{ctx['league_key']}")

    rosters, made, total = _assemble_rosters(ctx, src)
    if made == 0:
        st.info("No picks yet for this source. Run a **Mock Draft** (or sync a **Live "
                "Draft**), then come back for the report card." if src == "Mock draft"
                else "No live picks yet — start/sync your draft on the **Live Draft "
                     "Assistant** tab, or switch the source to **Mock draft**.")
        return
    if total and made < total:
        st.warning(f"Draft looks **incomplete** ({made}/{total} picks). Grades & "
                   "projections will sharpen once every pick is in.")
    if not ctx.get("value"):
        st.error("Projections aren't loaded for this league, so teams can't be graded.")
        return

    sig = tuple(sorted((s, tuple(sorted(p))) for s, p in rosters.items() if p))
    with st.spinner("Grading teams & simulating the season…"):
        rows = _report(sig, ctx)
    if not rows:
        st.info("Couldn't assemble any rosters to grade.")
        return

    slot_names = ctx["slot_names"]
    my_slot = (st.session_state.get(f"mock_{ctx['league_key']}") or {}).get("slot")
    champ = max(rows, key=lambda r: r["title_pct"])

    # ---- standings table ----
    head = ("<tr><th>#</th><th>Team</th><th>Grade</th><th>Proj record</th>"
            "<th>Make playoffs</th><th>Win title</th><th>Pts/wk</th><th>Past</th></tr>")
    trs = []
    for r in rows:
        nm = slot_names[r["slot"]] if r["slot"] < len(slot_names) else f"Team {r['slot']+1}"
        mine = " style=\"background:rgba(34,211,170,.10);\"" if r["slot"] == my_slot else ""
        rec = f'{r["exp_wins"]:.0f}–{r["exp_losses"]:.0f}'
        past = (f'{round(100*r["hist_winpct"])}% <span style="color:#64748b;">'
                f'({r["hist_games"]}g)</span>' if r["hist_winpct"] is not None else
                '<span style="color:#64748b;">—</span>')
        bye = (f' <span style="color:#22d3aa;font-size:.8em;">·bye {r["bye_pct"]}%</span>'
               if r.get("bye_pct") else "")
        trs.append(
            f'<tr{mine}>'
            f'<td style="color:#64748b;">{r["proj_seed"]}</td>'
            f'<td style="font-weight:600;">{nm}</td>'
            f'<td>{_grade_pill(r["grade"])}</td>'
            f'<td>{rec} <span style="color:#64748b;font-size:.82em;">'
            f'({r["avg_finish"]:.1f} avg)</span></td>'
            f'<td>{_odds_bar(r["playoff_pct"], "#3b82f6")}{bye}</td>'
            f'<td>{_odds_bar(round(r["title_pct"]), "#22d3aa")}</td>'
            f'<td style="text-align:right;">{r["proj_points"]:.0f}</td>'
            f'<td style="text-align:right;font-size:.86em;">{past}</td>'
            f'</tr>')
    st.markdown(
        '<table style="width:100%;border-collapse:collapse;font-size:.92rem;">'
        '<thead style="color:#94a3b8;text-align:left;font-size:.8rem;'
        'text-transform:uppercase;letter-spacing:.04em;">' + head + '</thead>'
        '<tbody>' + "".join(trs) + '</tbody></table>',
        unsafe_allow_html=True)
    st.caption(f"🏆 **Title favorite:** {slot_names[champ['slot']]} "
               f"({champ['title_pct']:.1f}%) · {rows[0]['reg_weeks']}-week season, "
               f"top {min(len(rows), grades.league_format(ctx)[1])} make the playoffs.")

    # ---- per-team cards (best lineup) ----
    st.markdown('<div class="dr-h" style="margin-top:14px;">Team-by-team</div>',
                unsafe_allow_html=True)
    reg, value = ctx["registry"], ctx["value"]
    for r in rows:
        nm = slot_names[r["slot"]] if r["slot"] < len(slot_names) else f"Team {r['slot']+1}"
        tag = " ⭐" if r["slot"] == my_slot else ""
        with st.expander(f"{r['proj_seed']}. {nm}{tag} — {r['grade']} · "
                         f"{r['exp_wins']:.0f}-{r['exp_losses']:.0f} · "
                         f"playoffs {r['playoff_pct']}% · title {r['title_pct']:.1f}%"):
            cells = []
            for pid in r["starters"]:
                pm = reg.meta(pid)
                c = _POSCOL.get(pm.position, "#94a3b8")
                cells.append(
                    f'<span style="display:inline-flex;align-items:center;gap:4px;'
                    f'margin:2px 8px 2px 0;">'
                    f'<b style="color:{c};">{pm.position}</b> {pm.name} '
                    f'<span style="color:#64748b;">{value.proj_of(pid):.0f}</span></span>')
            st.markdown(
                f'<div style="line-height:1.9;">{"".join(cells)}</div>',
                unsafe_allow_html=True)
            st.caption(f"Starters project **{r['proj_points']:.0f} pts/wk** "
                       f"(VORP {r['starter_vorp']:+d}) · {r['n_players']} players rostered"
                       + (f" · past win% {round(100*r['hist_winpct'])}%"
                          if r["hist_winpct"] is not None else ""))

    st.caption("How it works: each team's **best legal starting lineup** projects its "
               "weekly points; the **grade** curves that across the league. Records & "
               "odds come from a Monte-Carlo season (a balanced round-robin, since real "
               "matchups aren't set yet) — each week is a game with realistic scoring "
               "noise, the top seeds make a single-elim bracket. Past results nudge each "
               "team up or down on top of the draft.")
