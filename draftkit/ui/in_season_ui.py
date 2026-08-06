"""In-season — lineup, waivers, matchup, playoff planning.

Honest about the calendar throughout. Before a league drafts there is no roster,
no opponent and no lineup to set, so each tab says so and shows what it WILL run
on rather than rendering an empty shell that looks broken.

Projections come from the league's OWN host, so the numbers match the site you
actually set the lineup on — which matters most for the ESPN league, whose scoring
our own weights cannot reproduce.
"""
from __future__ import annotations

import streamlit as st

from .. import (config, inseason as INS, lineup as LU, phase as PH,
                projections as PROJ, rosters as RO, schedule as SCH)

_START_WEEK = 1
TABS = ["This Week", "Waivers", "Matchup", "Playoffs"]


def current_week() -> int:
    """The NFL week. The calendar belongs to the NFL, not the host, so Sleeper's
    state endpoint is right for the ESPN league too. Pre-season reports 0, which
    clamps to week 1 — the first week anyone would set a lineup for."""
    try:
        from .. import sleeper_client as api
        wk = int((api.get_state() or {}).get("week") or 0)
        return max(_START_WEEK, min(18, wk or _START_WEEK))
    except Exception:  # noqa: BLE001
        return _START_WEEK


def _team_label(ctx, team_key):
    names, owners = ctx.get("slot_names") or [], ctx.get("owner_by_slot") or {}
    for slot, key in owners.items():
        if str(key) == str(team_key) and slot < len(names):
            return names[slot]
    return ""


def _name_of(ctx, owner_id):
    return _team_label(ctx, owner_id) or "your opponent"


def render(ctx, summary=None, tab="This Week") -> None:
    meta, reg = ctx["meta"], ctx["registry"]
    season, week = config.current_season(), current_week()
    host = "ESPN" if meta.platform == "espn" else "Sleeper"
    tkey = ctx.get("my_team")
    me = _team_label(ctx, tkey)

    st.markdown(f'<div class="dr-h dr-title">Week {week}{" · " + me if me else ""}</div>',
                unsafe_allow_html=True)

    drafted = bool(summary and summary.phase in (PH.IN, PH.DONE))
    if not drafted:
        st.info(f"**{meta.name} hasn't drafted yet.** {summary.note if summary else ''}\n\n"
                f"In-season opens once it has. Everything below is live but will be "
                f"thin until there are rosters — projections come from {host}, in "
                f"this league's own scoring.")

    if tab == "This Week":
        _this_week(ctx, season, week, host, tkey)
    elif tab == "Waivers":
        _waivers(ctx, season, week, host, tkey)
    elif tab == "Matchup":
        _matchup(ctx, week, tkey)
    else:
        _playoffs(ctx, season)


# ------------------------------------------------------------------- this week
def _this_week(ctx, season, week, host, tkey) -> None:
    meta, reg = ctx["meta"], ctx["registry"]
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
        st.caption(f"No roster yet — showing the top week-{week} projections from {host}.")
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


# --------------------------------------------------------------------- waivers
def _waivers(ctx, season, week, host, tkey) -> None:
    """Free agents priced on what they ADD, plus what they'd cost to keep.

    The keeper column is the reason this screen exists — neither platform can tell
    you a $2 waiver claim becomes a 14th-round keeper next season, and in three of
    these four leagues that is often worth more than the points."""
    meta, reg = ctx["meta"], ctx["registry"]
    with st.spinner("Loading free agents…"):
        proj = PROJ.for_league(meta, reg, season, week=week,
                               espn_s2=ctx.get("espn_s2"), swid=ctx.get("swid"))
        taken = INS.rostered_pids(meta, reg, ctx.get("espn_s2"), ctx.get("swid"))
        fas = INS.free_agents(meta, reg, proj, taken, limit=25)

    money = INS.faab(meta)
    if money:
        spent = money["spent"].get(str(tkey), 0)
        left = money["budget"] - spent
        m = st.columns(3)
        m[0].metric("FAAB left", f"${left}")
        m[1].metric("Spent", f"${spent} of ${money['budget']}")
        m[2].metric("League median left", f"${money['median_left']}")
        if str(meta.league_id) == "1388606375239643136":
            st.caption("**7½ Men inverts the usual advice** — unspent FAAB is owed to "
                       "the Chase-bracket pot, so hoarding costs real money here.")

    if not taken:
        st.info("No rosters yet, so everyone is a free agent. This becomes useful "
                "once the league has drafted.")
        return
    if not fas:
        st.warning("No projected free agents found.")
        return

    roster = RO.for_league(meta, reg, tkey, espn_s2=ctx.get("espn_s2"),
                           swid=ctx.get("swid")) if tkey else {}
    mine = roster.get("players") or []
    slots = INS.keeper_slots_used(meta, mine, reg)
    if slots and slots["rookie_max"]:
        st.caption(f"Rookie keeper slots: {slots['rookie_used']} of "
                   f"{slots['rookie_max']} used.")

    # What he'd replace: the weakest starter at his position in the optimal lineup.
    lu = None
    if mine:
        lu = LU.optimize(mine, roster.get("starters"), ctx["roster_slots"], proj, reg,
                         byes=ctx.get("byes"), week=week)
    worst = {}
    for s in (lu.spots if lu else []):
        if s.pid:
            try:
                p = reg.meta(s.pid).position
            except Exception:  # noqa: BLE001
                continue
            if p not in worst or s.points < worst[p][1]:
                worst[p] = (s.pid, s.points)

    st.markdown('<div class="dr-h">Available · what they add, and what they cost next year</div>',
                unsafe_allow_html=True)
    head = st.columns([2.6, 1, 1.2, 2, 0.9])
    for col, lbl in zip(head, ("PLAYER", "PROJ", "GAIN", "KEEPS NEXT YEAR AT", "BID")):
        col.markdown(f'<div class="pcd-sl">{lbl}</div>', unsafe_allow_html=True)
    for r in fas[:15]:
        rep = worst.get(r["pos"])
        gain = r["proj"] - (rep[1] if rep else 0.0)
        kp = INS.keeper_price(meta, r["pid"], reg)
        c = st.columns([2.6, 1, 1.2, 2, 0.9])
        c[0].markdown(f"**{r['name']}** · {r['pos']} · {r['team']}")
        c[1].markdown(f"{r['proj']:.1f}")
        c[2].markdown(f":green[**+{gain:.1f}**]" if gain > 0.5 else f"{gain:+.1f}")
        c[3].markdown(kp["note"] if kp else ":gray[not a keeper league]")
        # Bid scaled to the GAIN, not the projection — a player who out-projects
        # your bench but replaces nobody is worth a dollar.
        bid = max(1, int(round(gain * 3))) if money and gain > 0 else 1
        c[4].markdown(f"**${bid}**" if money else "—")


# -------------------------------------------------------------------- matchup
def _matchup(ctx, week, tkey) -> None:
    """This week's opponent, with what four seasons of draft history already know
    about them. Tendencies are free — the profiles are already computed."""
    meta = ctx["meta"]
    opp = INS.opponent(meta, week, tkey)
    if not opp:
        st.info(f"No week-{week} matchup published yet. This fills in once the "
                "season starts.")
        _tendency_block(ctx, None)
        return
    name = _name_of(ctx, opp["owner_id"])
    h = st.columns([3, 1])
    h[0].markdown(f'<div class="dr-h dr-title">vs {name}</div>', unsafe_allow_html=True)
    if opp.get("points") is not None:
        h[1].metric("Their points", f"{opp['points']:.1f}")
    _tendency_block(ctx, opp["owner_id"])


def _tendency_block(ctx, owner_id) -> None:
    profiles = ctx.get("profiles") or {}
    prof = profiles.get(str(owner_id)) if owner_id else None
    money = INS.faab(ctx["meta"])
    if prof:
        share = prof.get("pos_share") or {}
        if share:
            top = max(share, key=share.get)
            st.markdown(f"- **Drafts {top}-heavy** — {share[top]*100:.0f}% of their picks.")
        if prof.get("archetype"):
            st.markdown(f"- **{prof['archetype']}**")
    elif owner_id:
        st.caption("No draft history for this manager yet.")
    if money and owner_id:
        spent = money["spent"].get(str(owner_id))
        if spent is not None:
            left = money["budget"] - spent
            st.markdown(f"- **FAAB:** spent ${spent} of ${money['budget']} — "
                        f"${left} left"
                        + (" — can't outbid you on anything meaningful."
                           if left < 10 else "."))
    if not owner_id:
        st.caption("Opponent scouting uses the same draft-history profiles as the "
                   "Scouting tab, plus their FAAB spend. Both are live now; only the "
                   "matchup itself is waiting on the season.")


# ------------------------------------------------------------------- playoffs
def _playoffs(ctx, season) -> None:
    """Your starters' fantasy-playoff slate — using THIS league's playoff weeks.

    Those weeks were hardcoded to 15-17, which is wrong for three of the four
    leagues here; they now come from each league's own settings."""
    meta, reg = ctx["meta"], ctx["registry"]
    weeks = SCH.playoff_weeks(meta)
    dvp, sched = ctx.get("dvp"), ctx.get("schedule")
    st.caption(f"This league's fantasy playoffs: **weeks "
               f"{' · '.join(str(w) for w in weeks)}** "
               f"({(meta.playoff_settings or {}).get('teams', '?')} teams). "
               "Read from the league's own settings, not assumed.")
    if not dvp or not sched:
        st.warning("No defence-vs-position data available.")
        return
    roster = RO.for_league(meta, reg, ctx.get("my_team"), espn_s2=ctx.get("espn_s2"),
                           swid=ctx.get("swid"))
    mine = roster.get("players") or []
    if not mine:
        st.info("No roster yet — this rates your starters' playoff matchups once "
                "the league has drafted.")
        return
    rows = []
    for pid in mine:
        try:
            pm = reg.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        slate = SCH.playoff_slate(pm.team, pm.position, dvp, sched, weeks=weeks)
        if slate:
            rows.append((slate["frac"], pm, slate))
    rows.sort(key=lambda r: r[0])
    st.markdown('<div class="dr-h">Your roster, hardest playoff slate first</div>',
                unsafe_allow_html=True)
    for frac, pm, slate in rows[:12]:
        c = st.columns([2.4, 1.1, 3])
        c[0].markdown(f"**{pm.name}** · {pm.position} · {pm.team}")
        tone = {"hard": "red", "easy": "green"}.get(slate["cls"], "gray")
        c[1].markdown(f":{tone}[**{slate['cls']}**]")
        c[2].markdown(" · ".join(f"Wk{w} {o} ({r})" for w, o, r, _ in slate["weeks"]))


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
    for i, (pts, pm, bye) in enumerate(rows[:15], 1):
        c = st.columns([0.5, 3, 1, 1, 1])
        c[0].markdown(f'<span class="pcd-tn">{i}</span>', unsafe_allow_html=True)
        c[1].markdown(f"**{pm.name}** · {pm.team}")
        c[2].markdown(f'<span class="pcd-chip">{pm.position}</span>', unsafe_allow_html=True)
        c[3].markdown(f"{bye or '—'}")
        c[4].markdown(f"**{pts:.1f}**")
