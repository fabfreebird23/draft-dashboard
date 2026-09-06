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
from . import components as C

_GRADE_COLOR = {
    "A+": "#22d3aa", "A": "#22d3aa", "A-": "#4ade80", "B+": "#84cc16",
    "B": "#a3e635", "B-": "#d9f99d", "C+": "#fbbf24", "C": "#f59e0b",
    "C-": "#fb923c", "D": "#f87171", "F": "#ef4444",
}
_POSCOL = {"QB": "#ef4444", "RB": "#22c55e", "WR": "#3b82f6", "TE": "#f59e0b",
           "K": "#a78bfa", "DST": "#94a3b8"}


def _all_rounds(ctx) -> int:
    """Rounds in the draft being graded, so "picks made of total" compares like
    with like.

    meta.draft_rounds is Sleeper's number for ONE draft — 2 for 7 1/2 Men while
    the league is configured as dynasty — which would have read "104 of 16".
    Counting every stage instead reads "104 of 120" and calls a finished 13-round
    veteran mock incomplete, because the rookie stage he never mocked (it was
    played for real months ago) is 16 of that 120. So: only stages that actually
    have a board on the screen count toward the total.
    """
    from .. import draft_stages as DS
    lid = ctx["meta"].league_id
    stages = DS.stages_for(lid)
    if not stages:
        return ctx["meta"].draft_rounds
    played = [x for x in stages
              if (st.session_state.get(f"mock_{ctx['league_key']}_{x.key}") or {}).get("made")]
    return sum(DS.scheduled_rounds(lid, x) for x in (played or stages))


def _mock_states(ctx) -> list:
    """Every mock board for this league, staged or not, most recent stage last.

    Unsuffixed first for ordinary leagues; then one per stage for the leagues that
    draft in two (7 1/2 Men). Anything missing is simply absent, so a league that
    has only run one of its two stages still grades.
    """
    from .. import draft_stages as DS
    keys = [f"mock_{ctx['league_key']}"]
    for stage in (DS.stages_for(ctx["meta"].league_id) or []):
        keys.append(f"mock_{ctx['league_key']}_{stage.key}")
    return [st.session_state.get(k) or {} for k in keys]


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
        # A staged league keeps each stage on its own board — mock_<key>_rookie and
        # mock_<key>_veteran — so reading only mock_<key> found nothing at all and
        # the report card came up empty after a 7 1/2 Men mock. Same class of miss
        # as the veteran pool: the stage split the state and one consumer was never
        # told.
        for st_state in _mock_states(ctx):
            for ov, pid in (st_state.get("made") or {}).items():
                if pid:
                    board[int(ov)] = str(pid)

    rosters = {s: [] for s in range(ctx["meta"].num_teams)}
    for ov, pid in board.items():
        rosters.setdefault(owner(int(ov)), []).append(pid)
    # Rosters are unioned across stages, but each stage numbers its picks from 1,
    # so a rookie 1.01 and a veteran 1.01 are different picks with the same key.
    # They are the same OWNER either way (both are round 1, slot 1 of the same
    # snake), so team rosters come out right; only the recap's sense of "when" is
    # per-stage, which is why it reads the stage board rather than this merge.
    picks_made = len([ov for ov in board if ov not in keeper_overalls])
    total = ctx["meta"].num_teams * _all_rounds(ctx) - len(keeper_overalls)
    # the board itself goes back too: the recap needs to know WHEN each player went,
    # not just who ended up where.
    return rosters, picks_made, max(0, total), board, keeper_overalls


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
    st.markdown('<div class="dr-h">Draft Report Card</div>', unsafe_allow_html=True)
    st.caption("After a draft, grade every team and project the season — records, "
               "playoff & title odds — from the rosters drafted, the value captured, "
               "and each manager's past results.")

    # Same unsuffixed-key miss as _assemble_rosters, second instance: a staged
    # league always looked like it had no mock, so the source defaulted to "Live
    # draft" and the tab opened on "no live picks yet". Between that and the empty
    # board, the screen had two independent ways of showing him nothing.
    have_mock = any(st_.get("made") for st_ in _mock_states(ctx))
    default_src = "Live draft" if not have_mock else "Mock draft"
    src = st.radio("Grade which draft?", ["Mock draft", "Live draft"],
                   index=["Mock draft", "Live draft"].index(default_src),
                   horizontal=True, key=f"rc_src_{ctx['league_key']}")

    rosters, made, total, board, keeper_ovs = _assemble_rosters(ctx, src)
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
    if my_slot is None:
        # grading a LIVE draft — the mock tab's slot doesn't exist, so fall back
        # to the team picked on the Live Draft Assistant rather than highlighting
        # nobody (or whoever the last mock happened to use).
        _me = st.session_state.get(f"live_{ctx['league_key']}_me")
        if _me in (ctx.get("slot_names") or []):
            my_slot = ctx["slot_names"].index(_me)
    if my_slot is None:
        # ...and if he hasn't opened either draft tab this session, the league
        # itself knows which team is his. Without this the tab graded everyone and
        # highlighted nobody — including on a live draft he never mocked.
        my_slot = (ctx.get("owner_slot") or {}).get(str(ctx.get("my_team")))
    champ = max(rows, key=lambda r: r["title_pct"])

    # ---- YOUR draft, as a card ---------------------------------------------
    # The standings table below answers "how did everyone do". This answers the
    # question he actually opened the tab with, in the shape the war room now uses
    # everywhere else: the grade where a score would be, the roster as cells, and
    # the two picks that moved the needle as reasons.
    mine = next((r for r in rows if r["slot"] == my_slot), None)
    if mine is not None:
        from .. import value as _V
        my_pids = rosters.get(my_slot) or []
        gi = _V.grade_team(my_pids, ctx["value"], ctx["registry"], ctx["roster_slots"],
                           len(slot_names))
        have = {}
        for _p in my_pids:
            _q = (ctx["registry"].meta(_p).position or "").upper()
            have[_q] = have.get(_q, 0) + 1
        demand = {}
        for _s in (ctx["roster_slots"] or []):
            if _s in ("QB", "RB", "WR", "TE"):
                demand[_s] = demand.get(_s, 0) + 1
        cells = [(p, f'{have.get(p, 0)}/{demand.get(p, 0)}',
                  "on" if have.get(p, 0) >= demand.get(p, 0) else "bad")
                 for p in ("QB", "RB", "WR", "TE")]
        reasons = []
        if gi.get("best_pick"):
            _b = ctx["registry"].meta(gi["best_pick"])
            reasons.append((f"Best value · {_b.name}",
                            f'{ctx["value"].vorp_of(gi["best_pick"]):+.0f} over replacement',
                            "steal", "g"))
        reasons.append((f'Projected {mine["exp_wins"]:.0f}–{mine["exp_losses"]:.0f}',
                        f'playoffs {mine["playoff_pct"]}% · title {mine["title_pct"]:.1f}%',
                        "season", "" if mine["playoff_pct"] < 50 else "g"))
        st.markdown(C.card_html(
            wash="var(--accent-fill)", wash2="var(--panel2)",
            left={"crest": "".join(w[0] for w in slot_names[my_slot].split()[:2]).upper(),
                  "name": slot_names[my_slot],
                  "sub": f'{src.lower()} · {made} picks'},
            right={"badge": mine["grade"]},
            mid={"pill": f'projected #{mine["proj_seed"]} of {len(rows)}',
                 "sit": f'<b>{mine["proj_points"]:.0f} pts/wk</b> · '
                        f'{gi["starter_vorp"]} starter value'},
            cells=cells, reasons=reasons,
            tone="good" if mine["playoff_pct"] >= 50 else ""), unsafe_allow_html=True)

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
    st.caption(f"**Title favorite:** {slot_names[champ['slot']]} "
               f"({champ['title_pct']:.1f}%) · {rows[0]['reg_weeks']}-week season, "
               f"top {min(len(rows), grades.league_format(ctx)[1])} make the playoffs.")

    # ---- per-team cards (best lineup) ----
    st.markdown('<div class="dr-h" style="margin-top:14px;">Team-by-team</div>',
                unsafe_allow_html=True)
    reg, value = ctx["registry"], ctx["value"]
    for r in rows:
        nm = slot_names[r["slot"]] if r["slot"] < len(slot_names) else f"Team {r['slot']+1}"
        tag = " ★" if r["slot"] == my_slot else ""
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

    # ---- what you left on the board ----
    if my_slot is not None:
        _mine = next((r for r in rows if r["slot"] == my_slot), None)
        _pts = [r["proj_points"] for r in rows]
        _mu = sum(_pts) / len(_pts)
        _sd = (sum((x - _mu) ** 2 for x in _pts) / len(_pts)) ** 0.5 or 1.0
        st.markdown('<div class="dr-h" style="margin-top:14px;">What you left on the '
                    'board</div>', unsafe_allow_html=True)
        with st.spinner("Replaying your picks…"):
            regs = grades.pick_regrets(board, my_slot, ctx, keeper_overalls=keeper_ovs,
                                       limit=6, mu=_mu, sd=_sd)
        if not regs:
            st.success("Nothing available at any of your picks would have scored higher. "
                       "That is the best board you could have drafted.")
        else:
            n = ctx["meta"].num_teams
            rws = []
            for r in regs:
                took, alt = reg.meta(r["took"]), reg.meta(r["pid"])
                rnd, pk = (r["overall"] - 1) // n + 1, (r["overall"] - 1) % n + 1
                if r["cand_taken_at"]:
                    ta = (r["cand_taken_at"] - 1) // n + 1, (r["cand_taken_at"] - 1) % n + 1
                    where = f'went {ta[0]}.{ta[1]:02d}'
                else:
                    where = '<b style="color:#f59e0b;">went undrafted</b>'
                both = ('<span style="color:#22d3aa;"> · you could have had both</span>'
                        if r["both"] else "")
                rws.append(
                    f'<tr><td style="color:#64748b;">{rnd}.{pk:02d}</td>'
                    f'<td>{took.name} <span style="color:#64748b;">{took.position}</span></td>'
                    f'<td style="color:#22d3aa;font-weight:600;">{alt.name} '
                    f'<span style="color:#64748b;font-weight:400;">{alt.position}</span></td>'
                    f'<td style="text-align:right;color:#22d3aa;">+{r["gain"]:.0f}</td>'
                    f'<td style="font-size:.86em;color:#94a3b8;">{where}{both}</td></tr>')
            st.markdown(
                '<table style="width:100%;border-collapse:collapse;font-size:.92rem;">'
                '<thead style="color:#94a3b8;text-align:left;font-size:.8rem;'
                'text-transform:uppercase;letter-spacing:.04em;"><tr><th>Pick</th>'
                '<th>You took</th><th>Better option</th><th style="text-align:right;">'
                '+pts/wk</th><th>Notes</th></tr></thead><tbody>'
                + "".join(rws) + '</tbody></table>', unsafe_allow_html=True)
            _best, _end = regs[0], regs[-1]
            _from = _mine["grade"] if _mine else "?"
            st.caption(
                f"All {len(regs)} swaps together would have taken you from "
                f"**{_from}** to **{_end['grade_if'] or '?'}** "
                f"({_end['total_pts']:.0f} pts/wk). Each row is measured against the "
                f"roster *after* the rows above it, so the gains do not double-count "
                f"two fixes to the same hole — and no player is offered twice, since "
                f"you can only draft him once.")
            st.caption(
                "⚠️ Every other team's picks are held fixed. Taking a different player "
                "would really have changed what everyone after you did, so treat these "
                "as an upper bound on what the swap was worth. The rows marked *you "
                "could have had both* are the solid ones: the player you actually took "
                "was still on the board at your next pick, so it was never a choice "
                "between them.")

    st.caption("How it works: each team's **best legal starting lineup** projects its "
               "weekly points; the **grade** curves that across the league. Records & "
               "odds come from a Monte-Carlo season (a balanced round-robin, since real "
               "matchups aren't set yet) — each week is a game with realistic scoring "
               "noise, the top seeds make a single-elim bracket. Past results nudge each "
               "team up or down on top of the draft.")
