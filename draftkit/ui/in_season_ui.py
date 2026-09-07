"""In-season — seven screens, each ending in a decision.

The first version of this tab was four read-outs: a projected lineup, a list of
free agents, an opponent's roster, the playoff weeks. All true, none actionable,
and all of it visible on Sleeper already.

The organising rule here is that every number is expressed as what it does to
YOUR lineup. The top waiver add in fantasy is worth nothing to a team that starts
someone better at that slot, and saying so is the entire value of the screen.

Heavy lifting lives in ``draftkit.weekly``; this module gathers and paints.
"""
from __future__ import annotations

import streamlit as st

from .. import (config, ecr as ECR, inseason, keepers as K, phase as PH,
                picks as PK, projections as PJ, schedule as SCH, sleeper_client as api,
                weekly as W)
from . import components as C

TABS = ["Command Center", "Waivers", "Matchup", "Trades", "Playoffs", "League", "Keepers"]

_POSC = {"QB": "var(--qb)", "RB": "var(--rb)", "WR": "var(--wr)", "TE": "var(--te)",
         "K": "var(--k)", "DST": "var(--dst)"}


# ------------------------------------------------------------------ small utils
def current_week() -> int:
    try:
        st_ = api.get_state("nfl") or {}
        wk = int(st_.get("week") or 1)
        return max(1, wk if (st_.get("season_type") == "regular") else 1)
    except Exception:  # noqa: BLE001
        return 1


def _preseason() -> bool:
    try:
        return (api.get_state("nfl") or {}).get("season_type") != "regular"
    except Exception:  # noqa: BLE001
        return True


def _ecr_cell(row) -> str:
    """One cell of expert consensus: where the panel has him, and how much they
    argued about it. The band is printed raw — a 54-96 spread explains itself, and
    every attempt to compress it into a single "controversy" score got the top of
    the board wrong (see ecr.spread)."""
    if not row or row.get("ecr") is None:
        return '<span class="ws-fnt">—</span>'
    b = ECR.band(row)
    wide = ECR.spread(row) >= max(8.0, 0.4 * (row.get("ecr") or 0))
    grade = (f' <span class="ws-fnt">{row["grade"]}</span>') if row.get("grade") else ""
    return (f'<b>{row.get("pos_rank") or int(row["ecr"])}</b>{grade}'
            f'<div class="ws-fnt{" ws-dn" if wide else ""}">{b}</div>')


def _ecr_missing(g) -> str:
    """A caption when the expert panel is unreachable, or "" when it is fine.

    A column of em-dashes reads as "nobody ranks these players", which is a claim
    about the players. The truth would be a claim about US — FantasyPros is public
    but their host can refuse a datacenter, and Streamlit Cloud is a datacenter.
    Whichever it turns out to be, the screen should say which.
    """
    if g.get("ecr") or g.get("ros"):
        return ""
    return ("**Expert consensus is unavailable right now** — the Experts and Rostered "
            "columns are blank because FantasyPros didn't answer, not because these "
            "players are unranked. Everything else on this screen is our own numbers "
            "and is unaffected.")


def _owned_cell(row) -> str:
    """Percent of leagues everywhere that already roster him.

    This is the only market signal on the board. Our own "adds to lineup" number
    says whether he helps YOU; this says how long he will be sitting there.
    """
    if not row or row.get("owned") is None:
        return '<span class="ws-fnt">—</span>'
    o = float(row["owned"])
    cls = "ws-up" if o < 40 else ("ws-dn" if o > 75 else "")
    return f'<b class="{cls}">{o:.0f}%</b>'


def _pos_pill(pos: str) -> str:
    return (f'<span style="font-size:9.5px;font-weight:900;padding:1px 5px;border-radius:4px;'
            f'color:#161415;background:{_POSC.get(pos, "var(--muted)")}">{pos}</span>')


def _chip(text: str, kind: str = "nil") -> str:
    bg = {"ok": "var(--green-bg,#12312a);color:var(--green,#7fd8b4)",
          "warn": "var(--amber-bg,#33231a);color:var(--amber,#f0b357)",
          "bad": "var(--red-bg,#3a1d22);color:var(--red,#ff8fae)",
          "acc": "var(--accent-soft,#3a1020);color:var(--accent,#ff336c)",
          "nil": "var(--panel2,#2c282a);color:var(--muted,#a2989c)"}[kind]
    return (f'<span style="font-size:9.5px;font-weight:800;letter-spacing:.05em;'
            f'text-transform:uppercase;padding:2px 7px;border-radius:5px;background:{bg}">{text}</span>')


def _tbl(head, rows, widths=None, wide: bool = False) -> str:
    """A table. `widths` declares column widths and switches on fixed layout, so
    the slack goes to the columns that can use it instead of being split evenly
    among columns that cannot — a number column needs ~72px and no more."""
    th = "".join(f'<th style="text-align:{"right" if h.startswith("~") else "left"}">'
                 f'{h.lstrip("~")}</th>' for h in head)
    cls = "ws-t" + (" ws-fixed" if widths else "") + (" ws-wide" if wide else "")
    cols = ("<colgroup>" + "".join(f'<col style="width:{w}">' for w in widths) + "</colgroup>"
            if widths else "")
    return (f'<table class="{cls}">' + cols + '<thead><tr>' + th + '</tr></thead><tbody>'
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
            + "</tbody></table>")


def _tiles(items) -> None:
    cols = st.columns(len(items))
    for c, (label, value, sub, colour) in zip(cols, items):
        with c:
            st.markdown(
                f'<div class="ws-tile"><div class="ws-tl">{label}</div>'
                f'<div class="ws-tv" style="color:{colour}">{value}</div>'
                f'<div class="ws-ts">{sub}</div></div>', unsafe_allow_html=True)


def _alert(kind, icon, html) -> None:
    st.markdown(f'<div class="ws-al ws-{kind}"><span>{icon}</span><div>{html}</div></div>',
                unsafe_allow_html=True)


# ------------------------------------------------------------------ data gather
@st.cache_data(ttl=300, show_spinner=False)
def _espn_rosters(league_id: str, season: int, _provider):
    """ESPN rosters, in Sleeper's shape. Cached on (league, season) — the provider
    is a leading-underscore arg so Streamlit doesn't try to hash it."""
    try:
        return _provider.get_rosters() or {}
    except Exception:  # noqa: BLE001 — a dead read must not take the tab down
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def _rosters(platform: str, league_id: str, season: int):
    """{owner_id: {players, starters, settings}} for the whole league."""
    if platform != "sleeper":
        return {}
    out = {}
    for r in (api.get_rosters(league_id) or []):
        out[str(r.get("owner_id"))] = {
            "players": [str(p) for p in (r.get("players") or [])],
            "starters": [str(p) for p in (r.get("starters") or [])],
            "settings": r.get("settings") or {},
            "roster_id": r.get("roster_id"),
        }
    return out


@st.cache_data(ttl=900, show_spinner=False, hash_funcs={"builtins.object": id})
def _ecr(season: int, week: int, scoring: str, _registry):
    """Expert consensus for this week and for the rest of the season.

    Both, because they answer different questions and the screens ask both: weekly
    for start/sit, rest-of-season for whether a waiver add or a trade is worth
    anything past Sunday. Empty dicts if FantasyPros hasn't ranked the week yet —
    every caller treats a missing player as "no opinion" rather than as rank 0.
    """
    try:
        return {"wk": ECR.weekly(season, week, scoring, _registry),
                "ros": ECR.ros(season, scoring, _registry)}
    except Exception:  # noqa: BLE001 — a third party must not be able to blank the tab
        return {"wk": {}, "ros": {}}


@st.cache_data(ttl=600, show_spinner=False)
def _pick_book(platform: str, league_id: str, season: int, rounds: int, rosters_json: str):
    """Who holds which FUTURE draft pick, league-wide.

    Sleeper's per-draft traded_picks can't see next year, and next year's picks
    are the ones that actually get traded in October. The league-level endpoint
    covers every season at once.
    """
    import json as _json
    if platform != "sleeper":
        return {}
    try:
        rids = sorted(int(r) for r in _json.loads(rosters_json))
        traded = api.get_league_traded_picks(league_id) or []
        seasons = PK.future_seasons(traded, int(season))
        own = PK.ownership(traded, rids, seasons, int(rounds or 14))
        # tuple keys don't survive Streamlit's cache serialisation — hand back the
        # per-roster lists the callers actually want.
        return {int(r): PK.held_by(own, r) for r in rids}
    except Exception:  # noqa: BLE001 — no pick data must not break the tab
        return {}


def _gather(ctx, week):
    """Everything the tabs share, fetched once."""
    meta, reg = ctx["meta"], ctx["registry"]
    season = config.current_season()
    # ESPN rosters come through the provider (same shape); everything below is
    # platform-blind from here. Without this the whole in-season tab read an empty
    # league and every screen drew nothing — for a league whose rosters were full.
    rosters = (_rosters(meta.platform, str(meta.league_id), season)
               if meta.platform == "sleeper"
               else _espn_rosters(str(meta.league_id), season, ctx["provider"]))
    me = str(ctx.get("my_team") or "")
    mine = (rosters.get(me) or {}).get("players") or []
    # the lineup he ACTUALLY has set, not the one we would pick for him
    starters = (rosters.get(me) or {}).get("starters") or []
    try:
        proj = PJ.for_league(meta, reg, season, week=week) or {}
    except Exception:  # noqa: BLE001
        proj = {}
    ecr = _ecr(season, week, getattr(meta, "scoring", "ppr") or "ppr", reg)
    import json as _json
    rids = [r.get("roster_id") for r in rosters.values() if r.get("roster_id") is not None]
    book = _pick_book(meta.platform, str(meta.league_id), season,
                      getattr(meta, "draft_rounds", 14) or 14,
                      _json.dumps(sorted(int(x) for x in rids)))
    return {"rosters": rosters, "me": me, "mine": mine, "starters": starters,
            # The LINEUP, not the draft roster: in-season every question is about
            # the nine you start, and in a fixed-roster league the two lists are
            # completely different shapes.
            "proj": proj, "slots": ctx.get("lineup_slots") or ctx["roster_slots"],
            "byes": ctx.get("byes"),
            "week": week, "season": season,
            "ecr": ecr["wk"], "ros": ecr["ros"], "picks": book}


def _owner_name(ctx, owner_id) -> str:
    names = ctx.get("manager_names") or {}
    if names.get(str(owner_id)):
        return names[str(owner_id)]
    try:
        osl = ctx.get("owner_slot") or {}
        return ctx["slot_names"][osl[str(owner_id)]]
    except Exception:  # noqa: BLE001
        return "Team"


def _opponent(ctx, g):
    """(owner_id, pids) of this week's opponent, or the closest-strength team as a
    stand-in before the schedule exists.

    Callers that need the lineup he has SET (not the one he should set) get it from
    `_opp_starters` rather than a third return value, because most callers — trades,
    keepers — only ever want the roster.
    """
    meta = ctx["meta"]
    try:
        ms = api.get_matchups(str(meta.league_id), g["week"]) or []
        rid_me = (g["rosters"].get(g["me"]) or {}).get("roster_id")
        mine_m = next((m for m in ms if m.get("roster_id") == rid_me), None)
        if mine_m and mine_m.get("matchup_id") is not None:
            opp_m = next((m for m in ms if m.get("matchup_id") == mine_m["matchup_id"]
                          and m.get("roster_id") != rid_me), None)
            if opp_m:
                for oid, r in g["rosters"].items():
                    if r.get("roster_id") == opp_m.get("roster_id"):
                        return oid, r["players"]
    except Exception:  # noqa: BLE001
        pass
    others = [(o, r["players"]) for o, r in g["rosters"].items() if o != g["me"] and r["players"]]
    return others[0] if others else (None, [])


def _opp_starters(g, oid) -> list:
    return (g["rosters"].get(str(oid)) or {}).get("starters") or []


# ---------------------------------------------------------------------- render
def render(ctx, summary=None, tab="Command Center") -> None:
    meta = ctx["meta"]
    week = current_week()
    drafted = bool(summary and summary.phase in (PH.IN, PH.DONE))
    if not drafted:
        st.info(f"**{meta.name} hasn't drafted yet.** In-season opens once it has.")
        return

    g = _gather(ctx, week)
    if not g["mine"]:
        st.warning("Couldn't find your roster on this league. Check the team set for "
                   "this league in the app config.")
        return
    if _preseason():
        st.caption("**Preseason** — projections are live, but records, results and "
                   "transactions stay empty until week 1 kicks off.")

    if tab == "Command Center":
        _command(ctx, g)
    elif tab == "Waivers":
        _waivers(ctx, g)
    elif tab == "Matchup":
        _matchup(ctx, g)
    elif tab == "Trades":
        _trades(ctx, g)
    elif tab == "Playoffs":
        _playoffs(ctx, g)
    elif tab == "League":
        _league(ctx, g)
    else:
        _keepers(ctx, g)


# ------------------------------------------------------------- 1 command centre
def _command(ctx, g) -> None:
    reg = ctx["registry"]
    lc = W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"],
                        current=g.get("starters"))
    avail = W.availability_report(g["mine"], g["slots"], g["proj"], reg,
                                  byes=g["byes"], week=g["week"], starters=g["starters"])
    oid, opp = _opponent(ctx, g)
    # His SET lineup, same as yours — scoring yourself on what you have and him on
    # what he ought to have is a thumb on the scale, and it made this tile disagree
    # with the Matchup tab about the same game.
    om, os_ = (W.team_distribution(opp, g["slots"], g["proj"], reg, g["byes"], g["week"],
                                   current=_opp_starters(g, oid)) if opp else (0, 1))
    # the lineup he has, not the one we would pick — that is what will actually score
    _now = lc["current_total"] if lc["have_current"] else lc["mean"]
    wp = W.win_prob(_now, lc["sd"], om, os_) if opp else None
    wp_fixed = (W.win_prob(_now + lc["gain"], lc["sd"], om, os_) if (opp and lc["gain"]) else wp)

    _tiles([
        ("Lineup", (f"{len(lc['moves'])} change{'s' if len(lc['moves']) != 1 else ''}"
                    if lc["moves"] else ("Optimal" if lc["have_current"] else "Unknown")),
         (f"worth +{lc['gain']} pts" if lc["moves"] else
          ("your lineup is the best available" if lc["have_current"]
           else "couldn't read your lineup")),
         "var(--amber)" if lc["moves"] else
         ("var(--green)" if lc["have_current"] else "var(--muted)")),
        ("Projected", f"{lc['current_total']:.1f}" if lc["have_current"] else f"{lc['mean']:.1f}",
         f"vs {_owner_name(ctx, oid)} · {om:.1f}" if opp else "no opponent yet", "var(--ink)"),
        ("Win prob", f"{100*wp:.0f}%" if wp is not None else "—",
         (f"{100*wp_fixed:.0f}% if you make the change{'s' if len(lc['moves']) != 1 else ''}"
          if lc["moves"] else "lineup already set"),
         "var(--green)" if (wp or 0) >= .5 else "var(--red)"),
        ("Injury risk", f'{avail["n_risky_starters"]}' if avail["n_risky_starters"] else "clear",
         (f'starters flagged · {avail["cost_if_all_out"]:+.1f} worst case'
          if avail["n_risky_starters"] else "nobody flagged"),
         "var(--red)" if avail["n_risky_starters"] else "var(--green)"),
    ])

    left, right = st.columns([1.5, 1])
    with left:
        _plat = "ESPN" if ctx["meta"].platform == "espn" else "Sleeper"
        hdr = (f"Your lineup on {_plat} — and what to change" if lc["have_current"]
               else "Best available lineup (couldn't read your set lineup)")
        st.markdown(f'<div class="ws-h">{hdr}</div>', unsafe_allow_html=True)
        bench_now = {m["out"]: m for m in lc["moves"]}
        ecr = g.get("ecr") or {}
        rows = []
        for slot, pid in lc["current"]:
            if not pid:
                rows.append([f'<b class="ws-sl">{slot}</b>',
                             '<span class="ws-dim">(empty)</span>', "—", "—", "—", "—",
                             _chip("nobody set", "bad")])
                continue
            pm = reg.meta(pid)
            mv = bench_now.get(str(pid))
            if mv:
                inm = reg.meta(mv["in"])
                better = (f'<b>{inm.name}</b> {_pos_pill(inm.position)} '
                          f'<span class="ws-fnt">{inm.team}</span>')
                delta = f'<b class="ws-up">+{mv["gain"]}</b>'
                # Our projection says swap; the panel is a second opinion on how far
                # out on a limb that is. "against" is not a veto — it is the fact
                # that eight people who do this for a living see it the other way.
                v = ECR.verdict(ecr.get(str(pid)), ecr.get(str(mv["in"])))
                verdict = _chip(f'start {inm.name.split()[-1]}',
                                {"against": "warn", "split": "warn"}.get(v, "ok"))
                if v == "against":
                    verdict += ' ' + _chip("panel disagrees", "bad")
                elif v == "split":
                    verdict += ' ' + _chip("coin flip", "warn")
            else:
                better = '<span class="ws-fnt">—</span>'
                delta = '<span class="ws-fnt">—</span>'
                verdict = _chip("keep", "nil")
            av = W.availability(pm)
            flag = (" " + _chip(av["status"][:4], "bad" if av["severity"] >= 3 else "warn")
                    ) if av["status"] else ""
            rows.append([f'<b class="ws-sl">{slot}</b>',
                         f'<b>{pm.name}</b> {_pos_pill(pm.position)} '
                         f'<span class="ws-fnt">{pm.team}</span>{flag}',
                         f'{float(g["proj"].get(str(pid), 0) or 0):.1f}',
                         _ecr_cell(ecr.get(str(pid))), better, delta, verdict])
        st.markdown(_tbl(["", "You are starting", "~Proj", "Experts", "Start instead", "~Δ", ""],
                         rows,
                         widths=["44px", "31%", "56px", "92px", "22%", "54px", "146px"],
                         wide=True), unsafe_allow_html=True)
        if lc["have_current"]:
            st.caption(f"Read from {_plat}: your lineup projects **{lc['current_total']:.1f}**, "
                       f"the best available is **{lc['optimal_total']:.1f}**. Only changes that "
                       f"alter *who plays* are listed — Sleeper labelling a man RB where the "
                       f"optimiser calls him FLEX is not a move.")
        else:
            st.caption("Couldn't read the lineup you have set, so this shows the best available "
                       "one instead. Everything else on this screen is unaffected.")
        if _ecr_missing(g):
            st.caption(_ecr_missing(g))

    with right:
        st.markdown('<div class="ws-h">Needs a decision</div>', unsafe_allow_html=True)
        # Availability first: it is the thing most likely to change a lineup, and
        # until now the screen could not see it at all.
        for a in avail["at_risk"][:3]:
            cost = a.get("cost_if_out")
            if cost is None:
                body = ""
            elif cost > 0.05:
                body = (f'If he sits you lose <b>{cost:.1f}</b> and '
                        f'<b>{a["replacement"] or "nobody"}</b> covers.')
            else:
                body = (f'<b>You would gain {abs(cost):.1f}</b> by starting '
                        f'{a["replacement"]} regardless.')
            extra = (" That same body is covering another questionable starter — "
                     "only one of them can.") if a.get("replacement_shared") else ""
            _alert("red" if a["severity"] >= 3 else "amb", "\u2695",
                   f'<b>{a["name"]} — {a["status"]}</b>'
                   + (f' <span class="ws-fnt">({a["detail"]})</span>' if a["detail"] else "")
                   + f'. {body}{extra}')
        if lc["moves"]:
            for m in lc["moves"][:3]:
                _alert("amb", "↑", f'<b>Start {reg.meta(m["in"]).name}, bench '
                                   f'{reg.meta(m["out"]).name}</b> — worth <b>+{m["gain"]}</b> '
                                   f'to your total this week.')
        elif lc["have_current"]:
            _alert("ok", "✓", "<b>The lineup you have set is the best available.</b> Nothing on "
                              "your bench beats a starter this week.")
        else:
            _alert("amb", "?", "<b>Couldn't read your set lineup</b> from the platform, so there "
                               "is nothing to compare against.")
        byes = ctx.get("byes") or {}
        on_bye = [p for p in g["mine"] if byes.get(reg.meta(p).team) == g["week"]]
        if on_bye:
            _alert("red", "⊘", f'<b>{len(on_bye)} on bye</b>: '
                               + ", ".join(reg.meta(p).name for p in on_bye[:4]))
        fut = {}
        for p in g["mine"]:
            b = byes.get(reg.meta(p).team)
            if b and b > g["week"]:
                fut.setdefault(b, []).append(p)
        if fut:
            worst = max(fut.items(), key=lambda kv: len(kv[1]))
            if len(worst[1]) >= 3:
                _alert("amb", "!", f'<b>Week {worst[0]} is your bye crunch</b> — {len(worst[1])} '
                                   f'players off: ' + ", ".join(reg.meta(p).name for p in worst[1][:4])
                                   + ". Plan the waiver two weeks out.")
        st.markdown('<div class="ws-h" style="margin-top:12px">Your bench</div>', unsafe_allow_html=True)
        brows = sorted(((float(g["proj"].get(p, 0) or 0), p) for p in lc["bench"]), reverse=True)
        st.markdown(_tbl(["Player", "~Proj"],
                         [[f'{reg.meta(p).name} {_pos_pill(reg.meta(p).position)}', f"{v:.1f}"]
                          for v, p in brows[:8]]), unsafe_allow_html=True)


# ------------------------------------------------------------------- 2 waivers
def _waivers(ctx, g) -> None:
    meta, reg = ctx["meta"], ctx["registry"]
    taken = {p for r in g["rosters"].values() for p in r["players"]}
    # ROS consensus picks the candidate pool, weekly consensus breaks ties on the
    # board: who is worth rostering is a rest-of-season question, who helps you on
    # Sunday is a weekly one.
    fas = inseason.free_agents(meta, reg, g["proj"], taken, limit=60,
                               ecr=g.get("ros"))
    # ROS for the tiebreak too, NOT the weekly map: rest-of-season is one list
    # covering every position, so its ranks can be compared to each other. The
    # weekly ranks cannot — see ecr._row's "scale".
    board = W.waiver_board(g["mine"], g["slots"], g["proj"], reg, fas,
                           byes=g["byes"], week=g["week"], limit=14,
                           ecr=g.get("ros"))
    fa = inseason.faab(meta) or {}
    budget = int(fa.get("budget") or 0)
    spent = int((fa.get("by_owner") or {}).get(str(g["me"]), 0) or 0)
    left = max(0, budget - spent) if budget else 0
    weeks_left = max(1, 14 - g["week"])

    _tiles([
        ("FAAB left", f"${left}" if budget else "—",
         f"of ${budget}" if budget else "no FAAB in this league", "var(--ink)"),
        ("Weeks left", f"{weeks_left}", f"≈ ${left/weeks_left:.0f} per week" if left else "—",
         "var(--muted)"),
        ("Upgrades available", f"{sum(1 for r in board if r['starts'])}",
         "free agents who would start for you", "var(--green)"),
        ("Roster", f"{len(g['mine'])}", "players", "var(--muted)"),
    ])

    # ---- the top add, as the swap it actually is -----------------------------
    # A waiver claim is two moves, not one: the table below ranks the adds, and
    # this card names the drop that pays for it — the lowest-projected man who is
    # NOT in your starting lineup. It is a suggestion, not a rule; a stash you are
    # holding on purpose is something only you know about.
    _top = next((r for r in board if r["gain"] > 0.05), None)
    if _top:
        _bid = W.bid_guidance(_top["gain"], left, weeks_left)
        _lc = W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"])
        _bench = sorted(((float(g["proj"].get(str(p), 0) or 0), str(p))
                         for p in _lc.get("bench") or []))
        _drop = _bench[0] if _bench else None
        _weak = W.weakest_slot(g["mine"], g["slots"], g["proj"], reg,
                               byes=g["byes"], week=g["week"])
        _own = ((g.get("ros") or {}).get(str(_top["pid"]))
                or (g.get("ecr") or {}).get(str(_top["pid"])) or {}).get("owned")
        _reasons = []
        if _weak:
            _reasons.append((f'He plays your weakest slot' if _top["pos"] in str(_weak[0])
                             else 'He cracks your starting lineup',
                             f'your {_weak[0]} projects {_weak[1]:.1f} · '
                             f'this adds {_top["gain"]:+.1f} to the week', "starter", "g"))
        if _own is not None:
            _reasons.append((f'{_own:.0f}% rostered everywhere',
                             'under ~40% is a quiet add; over that and you are in a '
                             'bidding war whether you like it or not',
                             "contested" if _own >= 40 else "quiet",
                             "w" if _own >= 40 else ""))
        st.markdown(C.card_html(
            wash="var(--green)", wash2="var(--panel2)",
            left={"crest": "+", "name": _top["name"],
                  "sub": f'add · {_top["pos"]} · {_top["proj"]:.1f} proj'},
            right=({"crest": "−", "name": reg.meta(_drop[1]).name,
                    "sub": f'drop · {(reg.meta(_drop[1]).position or "")} · '
                           f'{_drop[0]:.1f} proj'} if _drop else None),
            mid={"pill": (f'${_bid["low"]}–{_bid["high"]} of ${left}' if left
                          else f'{_top["gain"]:+.1f}/wk'),
                 "sit": f'<b>{_top["gain"]:+.1f}</b> to your week'},
            cells=[("Bid", f'${_bid["low"]}–{_bid["high"]}' if left else "—", "on" if left else ""),
                   ("Gain", f'{_top["gain"]:+.1f}', "on"),
                   ("Rostered", f'{_own:.0f}%' if _own is not None else "—",
                    "warn" if (_own or 0) >= 40 else ""),
                   ("FAAB left", f"${left}" if budget else "—", "")],
            reasons=_reasons,
            foot=f'{_bid["note"]} · {weeks_left} weeks left',
            tone="good"), unsafe_allow_html=True)

    st.markdown('<div class="ws-h">Ranked by what they add to YOUR starting lineup</div>',
                unsafe_allow_html=True)
    rows = []
    ecr, ros = g.get("ecr") or {}, g.get("ros") or {}
    for r in board[:12]:
        bid = W.bid_guidance(r["gain"], left, weeks_left)
        if r["gain"] > 0.05:
            verdict, kind = f"${bid['low']}–{bid['high']}", "ok"
        else:
            verdict, kind = "$0 — no upgrade", "nil"
        _av = W.availability(reg.meta(r["pid"]))
        _fl = (" " + _chip(_av["status"][:4], "bad" if _av["severity"] >= 3 else "warn")
               ) if _av["status"] else ""
        rows.append([
            f'<b>{r["name"]}</b> {_pos_pill(r["pos"])}{_fl}',
            f'{r["proj"]:.1f}',
            _ecr_cell(ecr.get(str(r["pid"]))),
            _owned_cell(ros.get(str(r["pid"])) or ecr.get(str(r["pid"]))),
            (f'<b class="ws-up">+{r["gain"]}</b>' if r["gain"] > 0.05
             else '<span class="ws-fnt">+0.0</span>'),
            _chip(verdict, kind),
        ])
    st.markdown(_tbl(["Player", "~Proj", "Experts", "~Rostered", "~Adds to lineup", "Bid"], rows,
                     widths=["auto", "62px", "92px", "92px", "112px", "126px"], wide=True),
                unsafe_allow_html=True)
    st.caption("A player who would not crack your starting lineup is worth **$0 to you**, however "
               "highly he is ranked elsewhere — that is what this column is for. **Rostered** is "
               "the percentage of leagues everywhere that already have him: under ~40% and he is "
               "probably a quiet add, over that and you are in a bidding war whether you like it "
               "or not.")
    if _ecr_missing(g):
        st.caption(_ecr_missing(g))

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="ws-h">Trending across fantasy</div>', unsafe_allow_html=True)
        try:
            tr = api.get_trending("add", 24, 8) or {}
        except Exception:  # noqa: BLE001
            tr = {}
        mine_set = {str(p) for p in g["mine"]}
        rws = []
        for pid, ct in list(tr.items())[:6]:
            pid = str(pid)
            gain = next((r["gain"] for r in board if r["pid"] == pid), None)
            note = (_chip("already yours", "acc") if pid in mine_set else
                    _chip("rostered", "nil") if pid in taken else
                    _chip(f"+{gain} to you", "ok") if (gain or 0) > 0.05 else
                    _chip("no upgrade for you", "nil"))
            try:
                pm = reg.meta(pid)
                rws.append([f'{pm.name} {_pos_pill(pm.position)}', f"+{ct:,}", note])
            except Exception:  # noqa: BLE001
                continue
        st.markdown(_tbl(["Player", "~24h adds", "For you"], rws), unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="ws-h">Drop candidates — keeper aware</div>', unsafe_allow_html=True)
        started = {str(p) for _, p in W.lineup_check(g["mine"], g["slots"], g["proj"], reg,
                                                     g["byes"], g["week"])["spots"] if p}
        krows = {r["pid"]: r for r in _keeper_rows(ctx, g)}
        rws = []
        for p in sorted(g["mine"], key=lambda x: float(g["proj"].get(x, 0) or 0)):
            if p in started:
                continue
            r = krows.get(str(p))
            pm = reg.meta(p)
            if r and r["verdict"] == "keep":
                verdict = _chip(f'keeper +{r["surplus"]} — hold', "bad")
            elif r and (r["surplus"] or -99) > -10:
                verdict = _chip(f'next keeper up (R{r["cost_round"]})', "warn")
            else:
                verdict = _chip("safe drop", "ok")
            rws.append([f'{pm.name} {_pos_pill(pm.position)}',
                        f'{float(g["proj"].get(p,0) or 0):.1f}', verdict])
            if len(rws) >= 5:
                break
        st.markdown(_tbl(["Player", "~Proj", "Verdict"], rws), unsafe_allow_html=True)
        st.caption("Dropping a cheap keeper is a next-season decision disguised as a roster move.")


# ------------------------------------------------------------------- 3 matchup
def _matchup(ctx, g) -> None:
    reg = ctx["registry"]
    oid, opp = _opponent(ctx, g)
    if not opp:
        st.info("No opponent found for this week yet.")
        return
    ost = _opp_starters(g, oid)
    # BOTH sides as the lineups they have SET. Scoring yourself on what you'd play
    # and the other guy on what he should play is how a screen ends up disagreeing
    # with the Command Center about your own projection.
    mm, ms = W.team_distribution(g["mine"], g["slots"], g["proj"], reg, g["byes"],
                                 g["week"], current=g["starters"])
    om, os_ = W.team_distribution(opp, g["slots"], g["proj"], reg, g["byes"],
                                  g["week"], current=ost)
    wp = W.win_prob(mm, ms, om, os_)
    # What the week looks like if you make your moves and he makes his — the upside
    # you're leaving on the table, and the risk that he doesn't leave his there.
    bm, bs = W.team_distribution(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"])
    obm, obs = W.team_distribution(opp, g["slots"], g["proj"], reg, g["byes"], g["week"])
    wp_best = W.win_prob(bm, bs, obm, obs)
    them = _owner_name(ctx, oid)

    # The matchup as a card. Of everything on this dashboard it is the closest to
    # an actual game — two sides, two numbers, a probability — so it gets the same
    # treatment a live game does. The win-probability bar is ours, not a market's:
    # it comes out of the projection distribution, which is why the spread differs
    # between a boom/bust roster and a steady one with the same total.
    swing = W.swing_players(g["mine"], opp, g["slots"], g["proj"], reg,
                            byes=g["byes"], week=g["week"], top=1)
    weak = W.weakest_slot(g["mine"], g["slots"], g["proj"], reg,
                          byes=g["byes"], week=g["week"])
    _reasons = []
    if swing:
        _sw = swing[0]
        _reasons.append((f'{_sw["name"]} is the game',
                         f'floor {_sw["floor"]:.0f} → ceiling {_sw["ceiling"]:.0f} · '
                         f'{_sw["swing"]} points of win probability rest on him',
                         "watch", "g" if _sw["side"] == "you" else "w"))
    if weak:
        _reasons.append((f'Your {weak[0]} slot projects {weak[1]:.1f}',
                         'weakest starting slot — the first place a waiver add pays',
                         "fix", "w"))
    _gap = mm - om
    st.markdown(C.card_html(
        wash="var(--accent-fill)", wash2="var(--panel2)",
        left={"crest": "YOU", "name": "You", "sub": f'set lineup · {ms:.0f} pt spread',
              "big": f"{mm:.1f}"},
        right={"crest": "".join(w[0] for w in str(them).split()[:2]).upper() or "OPP",
               "name": them, "sub": f'set lineup · {os_:.0f} pt spread',
               "big": f"{om:.1f}", "trail": _gap > 0},
        mid={"pill": f'week {g["week"]}', "live": True,
             "sit": f'<b>{"+" if _gap >= 0 else ""}{_gap:.1f}</b> projected margin'},
        bar={"pct": 100 * wp, "l": f"{100*wp:.0f}% you", "m": "win probability",
             "r": f"{100*(1-wp):.0f}%",
             "color": "var(--green)" if wp >= 0.5 else "var(--amber)"},
        cells=[("You", f"{mm:.1f}", "on" if _gap >= 0 else ""),
               ("Them", f"{om:.1f}", "" if _gap >= 0 else "bad"),
               ("Best case", f"{bm:.1f}", "on" if bm > mm + 0.5 else ""),
               ("If both play best", f"{100*wp_best:.0f}%",
                "on" if wp_best >= 0.5 else "warn")],
        reasons=_reasons,
        tone="good" if wp >= 0.55 else "bad" if wp < 0.45 else "warn"),
        unsafe_allow_html=True)
    _plat = "ESPN" if ctx["meta"].platform == "espn" else "Sleeper"
    st.caption(f"Both lineups as currently **set** on {_plat}. Play your best lineup and he plays "
               f"his and it's {bm:.1f} – {obm:.1f}, {100*wp_best:.0f}% you. Win probability treats "
               f"each team total as a normal distribution — the spread comes from position-level "
               f"weekly variance, so a boom/bust roster reads differently from a steady one with "
               f"the same projection.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="ws-h">Slot by slot</div>', unsafe_allow_html=True)
        # ["current"], not ["spots"] — "spots" is the OPTIMAL lineup, and this
        # column has to name the men who will actually be on the field.
        ml = W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"],
                            current=g["starters"])["current"]
        ol = W.lineup_check(opp, g["slots"], g["proj"], reg, g["byes"], g["week"],
                            current=ost)["current"]
        rows = []
        for (s, a), (_s2, b) in zip(ml, ol):
            pa = float(g["proj"].get(str(a), 0) or 0) if a else 0.0
            pb = float(g["proj"].get(str(b), 0) or 0) if b else 0.0
            d = pa - pb
            rows.append([f'<b class="ws-sl">{s}</b>',
                         f'{reg.meta(a).name if a else "—"} <span class="ws-fnt">{pa:.1f}</span>',
                         (f'<b class="ws-up">+{d:.1f}</b>' if d > 0 else f'<b class="ws-dn">{d:.1f}</b>'),
                         f'<span class="ws-dim">{reg.meta(b).name if b else "—"} {pb:.1f}</span>'])
        st.markdown(_tbl(["", "You", "~Edge", "Them"], rows,
                         widths=["46px", "38%", "70px", "38%"], wide=True), unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="ws-h">Swing players — whose week decides it</div>',
                    unsafe_allow_html=True)
        sw = W.swing_players(g["mine"], opp, g["slots"], g["proj"], reg,
                             byes=g["byes"], week=g["week"], top=5)
        st.markdown(_tbl(["Player", "Ceiling", "Floor", "~Swings"],
                         [[f'<b>{s["name"]}</b> {_pos_pill(s["pos"])} '
                           f'<span class="ws-fnt">{"you" if s["side"]=="you" else them}</span>',
                           f'<span class="ws-up">{s["ceiling"]} → {s["p_hi"]}%</span>',
                           f'<span class="ws-dn">{s["floor"]} → {s["p_lo"]}%</span>',
                           f'<b>{s["swing"]}%</b>'] for s in sw]), unsafe_allow_html=True)
        ws = W.weakest_slot(opp, g["slots"], g["proj"], reg, byes=g["byes"], week=g["week"])
        if ws:
            _alert("ok", "◎", f'<b>{them}\'s soft spot is {ws[0]}</b> — '
                              f'{reg.meta(ws[2]).name} projects {ws[1]:.1f}. '
                              f'If you can beat that slot, you probably win the week.')


# -------------------------------------------------------------------- 4 trades
def _keeper_rows(ctx, g) -> list:
    """The keeper table, priced properly — the ONE place that answers "what does
    this player cost to keep".

    inseason.keeper_price answers a narrower question (what a WAIVER ADD costs) and
    returns the last round for everybody. Three screens were calling it: Keepers
    (fixed), the Trades keeper lens and the Waivers drop warnings — both of which
    were therefore telling him every player on his roster was an R14 keeper, which
    is exactly the failure the Keepers tab already had.
    """
    meta, reg = ctx["meta"], ctx["registry"]
    if meta.platform != "sleeper":
        return []
    try:
        rules = dict(K.load_keeper_rules(str(meta.league_id)) or {})
        if not ((rules.get("max_regular_keepers") or 0) + (rules.get("max_rookie_keepers") or 0)):
            return []
        rules["_last_round"] = meta.draft_rounds
        raw = K.load_keepers(str(meta.league_id), g["season"]) or {}
        existing = {str(k.get("player_id")): k for k in (raw.get(str(g["me"])) or [])}
        return W.keeper_outlook(
            g["mine"], drafted_round=_draft_rounds(str(meta.league_id), str(g["me"])),
            existing=existing, rules=rules, n_teams=meta.num_teams,
            adp_rank=ctx["adp_rank"], registry=reg, proj=g["proj"])
    except Exception:  # noqa: BLE001 — a missing keeper config must not break a tab
        return []


def _keep_list(ctx, g) -> dict:
    """{pid: surplus} for the players keeper_outlook says to keep.

    The trade screen scores lineups. In a keeper league that is only half the
    ledger: a deal can raise your week by 2 points while handing away a player who
    costs a last-round pick and is worth an early one. Marking those keeps the
    "both win" verdict honest — it is a verdict about THIS WEEK.
    """
    return {r["pid"]: r["surplus"] for r in _keeper_rows(ctx, g)
            if r["verdict"] == "keep" and r["surplus"] is not None}


def _trades(ctx, g) -> None:
    reg = ctx["registry"]
    partners = [(o, r["players"]) for o, r in g["rosters"].items()
                if o != g["me"] and r["players"]]
    if not partners:
        st.info("No other rosters found.")
        return
    # Which partners are actually worth talking to. Clicking through seven teams to
    # discover that three of them have a deal is a search the app should do.
    @st.cache_data(ttl=600, show_spinner=False)
    def _scan(sig, _mine, _slots, _proj):
        out = {}
        for o, pids in sig:
            n = len([1 for i in W.trade_ideas(_mine, list(pids), _slots, _proj, reg,
                                              max_ideas=4) if i["mutual"]])
            n += len([1 for i in W.trade_packages(_mine, list(pids), _slots, _proj, reg,
                                                  max_ideas=5) if i["mutual"]])
            out[o] = n
        return out

    with st.spinner("Scanning the league for deals that clear…"):
        counts = _scan(tuple((o, tuple(pl)) for o, pl in partners),
                       g["mine"], g["slots"], g["proj"])
    labels, order = [], sorted(partners, key=lambda kv: -counts.get(kv[0], 0))
    for o, _pl in order:
        n = counts.get(o, 0)
        labels.append(f"{_owner_name(ctx, o)}" + (f"  ·  {n} deal{'s' if n != 1 else ''}" if n else ""))
    pick = st.selectbox("Trade partner — sorted by deals that help both sides", labels,
                        key=f"ws_tp_{ctx['league_key']}")
    oid, opp = order[labels.index(pick)]
    if not any(counts.values()):
        st.caption("No team in the league has a deal that improves both lineups right now. "
                   "That is common with freshly drafted rosters — it changes as byes and "
                   "injuries create real holes.")

    base_mine, _ = W.team_distribution(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"])
    ml = W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"])
    by_pos = {}
    for _s, pid in ml["spots"]:
        if pid:
            by_pos.setdefault(reg.meta(pid).position, []).append(
                float(g["proj"].get(str(pid), 0) or 0))
    weakest = min(((p, min(v)) for p, v in by_pos.items() if v), key=lambda x: x[1], default=None)
    surplus = max(((p, len(v)) for p, v in by_pos.items()), key=lambda x: x[1], default=None)

    _tiles([
        ("Your weakest starter", f"{weakest[0]} {weakest[1]:.1f}" if weakest else "—",
         "lowest-projected slot you start", "var(--amber)"),
        ("Deepest position", f"{surplus[0]} ×{surplus[1]}" if surplus else "—",
         "where you can afford to sell", "var(--green)"),
        ("Partner", pick, f"{len(opp)} players", "var(--ink)"),
        ("Your lineup", f"{base_mine:.1f}", "projected this week", "var(--muted)"),
    ])

    with st.spinner("Searching one-for-ones and packages…"):
        ones = W.trade_ideas(g["mine"], opp, g["slots"], g["proj"], reg,
                             byes=g["byes"], week=g["week"], max_ideas=4)
        pkgs = W.trade_packages(g["mine"], opp, g["slots"], g["proj"], reg,
                                byes=g["byes"], week=g["week"], max_ideas=5)
    ideas = []
    for i in ones:
        ideas.append({"shape": "1-for-1", "send_names": [i["send_name"]],
                      "get_names": [i["get_name"]], "send": [i["send"]], "get": [i["get"]],
                      "you": i["you"], "them": i["them"], "mutual": i["mutual"],
                      "roster_delta": 0})
    ideas += pkgs
    ideas.sort(key=lambda i: (not i["mutual"], -(i["you"] + max(0.0, i["them"]))))

    mutual = [i for i in ideas if i["mutual"]]
    deal_col, keep_col = st.columns([1.35, 1], gap="medium")
    _tables = deal_col
    with keep_col:
        # C — the keeper lens sits BESIDE the deals, not 400px below them. These are
        # the two facts you have to weigh against each other, and having to scroll
        # between them was the real reason this screen felt wrong.
        st.markdown('<div class="ws-h">Keeper cost — the other half of every trade</div>',
                    unsafe_allow_html=True)
        krows = {r["pid"]: r for r in _keeper_rows(ctx, g)}
        seen, rws = set(), []
        for i in ideas[:4]:
            for pids, who in ((i["send"], "send"), (i["get"], "get")):
                for pid in pids:
                    if pid in seen:
                        continue
                    seen.add(pid)
                    r = krows.get(str(pid))
                    if r:
                        sur = (f'<b class="ws-up">+{r["surplus"]}</b>' if (r["surplus"] or 0) > 0
                               else f'<span class="ws-dn">{r["surplus"]}</span>')
                        cost = f'R{r["cost_round"]} <span class="ws-fnt">{r["note"]}</span>'
                    else:
                        sur = '<span class="ws-fnt">—</span>'
                        cost = (f'R{ctx["meta"].draft_rounds} '
                                f'<span class="ws-fnt">if added</span>')
                    rws.append([f'<span class="{"" if who == "send" else "ws-dim"}">'
                                f'{reg.meta(pid).name}</span>', who, cost, sur])
        if rws:
            st.markdown(_tbl(["Player", "", "Costs", "~Surplus"], rws,
                             widths=["auto", "48px", "38%", "76px"], wide=True),
                        unsafe_allow_html=True)
            st.caption("In a keeper league every trade is two trades: this season's points and "
                       "next season's price. A player who costs a last-round pick and is worth "
                       "an early one is rarely worth a couple of points a week.")
        else:
            st.caption("No keeper rules configured for this league.")

    with _tables:
        st.markdown('<div class="ws-h">Proposals, scored for both sides</div>',
                    unsafe_allow_html=True)
    if not ideas:
        _tables.caption("Nothing with this team improves your lineup this week — one-for-one or packaged.")
    else:
        keeps = _keep_list(ctx, g)
        rows = []
        for i in ideas[:8]:
            slot_note = ("" if not i["roster_delta"] else
                         f' <span class="ws-fnt">({i["roster_delta"]:+d} roster spot)</span>')
            shipped = [(p, keeps[p]) for p in i["send"] if p in keeps]
            send_html = " + ".join(
                (f'{n} {_chip("keeper", "warn")}' if p in keeps else n)
                for p, n in zip(i["send"], i["send_names"]))
            i["_ships_keeper"] = shipped
            rows.append([
                _chip(i["shape"], "acc" if i["shape"] != "1-for-1" else "nil"),
                send_html,
                "<b>" + " + ".join(i["get_names"]) + "</b>" + slot_note,
                f'<b class="ws-up">+{i["you"]}</b>',
                (f'<span class="ws-up">+{i["them"]}</span>' if i["them"] > 0
                 else f'<span class="ws-dn">{i["them"]}</span>'),
                _chip("both win", "ok") if i["mutual"] else _chip("they'll refuse", "bad")])
        _tables.markdown(_tbl(["", "You send", "You get", "~You", "~Them", ""], rows,
                              widths=["84px", "31%", "31%", "68px", "68px", "126px"], wide=True),
                         unsafe_allow_html=True)
        if mutual:
            _tables.caption(f"**{len(mutual)} of these actually clear** — both lineups improve. Those are "
                       "the ones to send. The rest are listed so you can see they were considered "
                       "and rejected, not overlooked.")
            risky = [i for i in mutual if i.get("_ships_keeper")]
            if risky:
                worst = max((s_ for i in risky for _p, s_ in i["_ships_keeper"]))
                who = next(n for i in risky for p, n in zip(i["send"], i["send_names"])
                           if any(p == q for q, _s in i["_ships_keeper"]))
                _alert("amb", "!", f'<b>These verdicts are about this week only.</b> The deal above '
                                   f'ships <b>{who}</b>, who the Keepers tab rates at <b>+{worst} '
                                   f'picks of surplus</b> next year. A couple of points a week is '
                                   f'rarely worth a keeper that cheap — check the Keepers tab before '
                                   f'you send it.')
        else:
            _tables.caption("**None of these help both sides.** One-for-ones only work when two managers "
                       "have mirrored holes, which is rare; packages are where most real trades "
                       "live, and none clears here either. Try another partner.")
        _tables.caption("A 2-for-1 also costs you a roster spot, which this does not price — the freed "
                   "slot is only worth something if there is a waiver add worth making.")

    _analyzer(ctx, g, oid, opp)


def _roster_id(g, owner_id):
    return (g["rosters"].get(str(owner_id)) or {}).get("roster_id")


def _team_of(ctx, g, roster_id):
    """Manager name for a roster_id — for "2027 R4 (via Ned)"."""
    for owner, r in g["rosters"].items():
        if r.get("roster_id") == roster_id:
            return _owner_name(ctx, owner)
    return None


def _pick_menu(ctx, g, owner_id) -> dict:
    """{label: pick} of the future picks this manager holds, in order.

    Labels carry the origin so a manager holding three 2027 fourths can tell them
    apart — they are genuinely different assets to the other side of the table.
    """
    rid = _roster_id(g, owner_id)
    if rid is None:
        return {}
    out = {}
    for pk in (g.get("picks") or {}).get(int(rid), []):
        out[PK.label(pk, _team_of(ctx, g, pk.get("origin")))] = pk
    return out


def _analyzer(ctx, g, oid, opp) -> None:
    """Judge a SPECIFIC offer — the one in your inbox.

    The finder answers "what deals exist". This answers "should I accept this",
    which is the question you actually get asked, and the two want opposite inputs.
    """
    reg = ctx["registry"]
    them = _owner_name(ctx, oid)
    st.markdown('<div class="ws-h" style="margin-top:18px">Analyze a specific offer</div>',
                unsafe_allow_html=True)
    st.caption(f"Paste in a real proposal — yours or one **{them}** sent you — and see what it "
               "does to your week, your rest of season, and your keepers.")

    mine_names = {reg.meta(p).name: p for p in g["mine"]}
    opp_names = {reg.meta(p).name: p for p in opp}
    my_picks, their_picks = _pick_menu(ctx, g, g["me"]), _pick_menu(ctx, g, oid)
    c1, c2 = st.columns(2, gap="medium")
    send = c1.multiselect("You send", sorted(mine_names),
                          key=f"ws_an_send_{ctx['league_key']}",
                          placeholder="pick from your roster")
    get = c2.multiselect(f"You get from {them}", sorted(opp_names),
                         key=f"ws_an_get_{ctx['league_key']}",
                         placeholder="pick from theirs")
    # Picks are their own two boxes rather than being mixed into the player lists.
    # In a keeper league the offer is usually "player for pick", and a single
    # jumbled dropdown makes you hunt for the 2027 second among forty names.
    sendp = c1.multiselect("…and these picks", list(my_picks),
                           key=f"ws_an_sendp_{ctx['league_key']}",
                           placeholder="your future draft picks")
    getp = c2.multiselect("…and these picks", list(their_picks),
                          key=f"ws_an_getp_{ctx['league_key']}",
                          placeholder=f"{them}'s future draft picks")
    if (not send and not sendp) or (not get and not getp):
        st.caption("Put at least one player or pick on each side.")
        return

    weeks_left = max(1, 14 - g["week"])
    n_teams = int(getattr(ctx["meta"], "num_teams", 12) or 12)
    r = W.analyze_trade(g["mine"], opp, [mine_names[n] for n in send], [opp_names[n] for n in get],
                        g["slots"], g["proj"], reg, byes=g["byes"], week=g["week"],
                        keeper_rows=_keeper_rows(ctx, g), weeks_left=weeks_left,
                        send_picks=[my_picks[k] for k in sendp],
                        get_picks=[their_picks[k] for k in getp], n_teams=n_teams)

    tone = {"accept": "var(--green)", "reject": "var(--red)",
            "marginal": "var(--amber)"}.get(r["verdict"], "var(--amber)")

    # ---- the offer as a card: two sides, four numbers, the verdict -----------
    # A trade is the most two-sided screen in the app, so it takes the card shape
    # most naturally. The tiles below still carry the detail; this is the sentence
    # you would say out loud — what goes, what comes back, and whether to do it.
    _sd = ", ".join(list(send) + list(sendp)) or "—"
    _gt = ", ".join(list(get) + list(getp)) or "—"
    _cells = [("This week", f'{r["week"]:+.1f}', "on" if r["week"] > 0 else "bad"),
              ("Rest of season", f'{r["rest"]:+.0f}', "on" if r["rest"] > 0 else "bad")]
    if r["keeper"] is not None:
        _cells.append(("Keeper surplus", f'{r["keeper"]:+d}',
                       "on" if r["keeper"] > 0 else "bad"))
    if r["capital"] is not None:
        _cells.append(("Draft capital", f'{r["capital"]:+d}',
                       "on" if r["capital"] > 0 else "bad"))
    _rs = [(f'They gain {r["them"]:+.1f} a week',
            ("they have a reason to say yes" if r["them"] > 0.05 else
             (f'lineup no, but {abs(r["capital"])} picks of capital yes'
              if (r["capital"] or 0) < 0 else
              "no lineup reason for them to say yes — expect a counter")),
            "for them", "g" if (r["them"] > 0.05 or (r["capital"] or 0) < 0) else "w")]
    if r["out_keepers"]:
        _rs.append((f'{len(r["out_keepers"])} keeper(s) leaving',
                    "you would be shipping next year's discount with them",
                    "cost", "b"))
    st.markdown(C.card_html(
        wash="var(--wr)", wash2="var(--te)",
        left={"crest": "OUT", "name": _sd, "sub": "you send"},
        right={"crest": "IN", "name": _gt, "sub": "you get"},
        mid={"swap": "⇄", "sit": f'<b>{r["verdict"].upper()}</b>'},
        cells=_cells, reasons=_rs, foot=r["why"],
        tone={"accept": "good", "reject": "bad"}.get(r["verdict"], "warn")),
        unsafe_allow_html=True)

    _tiles([
        ("This week", f'{r["week"]:+.1f}', f'{r["mine_before"]:.0f} → {r["mine_after"]:.0f} pts',
         "var(--green)" if r["week"] > 0 else "var(--red)"),
        ("Rest of season", f'{r["rest"]:+.0f}', f"over {weeks_left} weeks",
         "var(--green)" if r["rest"] > 0 else "var(--red)"),
        ("Keeper surplus", "—" if r["keeper"] is None else f'{r["keeper"]:+d}',
         "in draft picks, next year" if r["keeper"] is not None else "no keepers involved",
         "var(--green)" if (r["keeper"] or 0) > 0 else
         ("var(--red)" if r["keeper"] is not None else "var(--muted)")),
        ("Draft capital", "—" if r["capital"] is None else f'{r["capital"]:+d}',
         ("in pick positions, next year" if r["capital"] is not None
          else "no picks in this deal"),
         "var(--green)" if (r["capital"] or 0) > 0 else
         ("var(--red)" if r["capital"] is not None else "var(--muted)")),
        # Their capital is the mirror of ours, so a deal that reads as nothing for
        # them on lineup can still be an obvious yes on picks. Say which.
        ("For them", f'{r["them"]:+.1f}',
         ("they accept" if r["them"] > 0.05 else
          (f'lineup no, but +{abs(r["capital"])} picks yes' if (r["capital"] or 0) < 0
           else "they have no reason to")),
         "var(--green)" if (r["them"] > 0.05 or (r["capital"] or 0) < 0) else "var(--muted)"),
    ])
    st.markdown(f'<div class="ws-verdict" style="border-color:{tone}">'
                f'<b style="color:{tone}">{r["verdict"].upper()}</b> — {r["why"]}</div>',
                unsafe_allow_html=True)

    a, b = st.columns([1, 1], gap="medium")
    with a:
        st.markdown('<div class="ws-h">Your lineup, before and after</div>', unsafe_allow_html=True)
        rows = []
        for (s1, p1), (_s2, p2) in zip(r["before"], r["after"]):
            changed = str(p1) != str(p2)
            n1 = reg.meta(p1).name if p1 else "—"
            n2 = reg.meta(p2).name if p2 else "—"
            rows.append([f'<b class="ws-sl">{s1}</b>',
                         f'<span class="{"ws-dn" if changed else "ws-dim"}">{n1}</span>',
                         f'<b class="ws-up">{n2}</b>' if changed else
                         f'<span class="ws-fnt">unchanged</span>'])
        st.markdown(_tbl(["", "Now", "After the trade"], rows,
                         widths=["46px", "42%", "42%"], wide=True), unsafe_allow_html=True)
    with b:
        if r["out_keepers"]:
            st.markdown('<div class="ws-h">Keepers you would be shipping</div>',
                        unsafe_allow_html=True)
            st.markdown(_tbl(["Player", "Costs", "~Surplus"],
                             [[n, f'R{k["cost_round"]} <span class="ws-fnt">{k["note"]}</span>',
                               f'<b class="ws-up">+{k["surplus"]}</b>']
                              for n, k in r["out_keepers"]],
                             widths=["auto", "44%", "84px"], wide=True), unsafe_allow_html=True)
            st.caption("These cost a late pick and are worth an early one. Giving one up is a "
                       "next-season decision, and the week number above does not price it.")
        if r["picks_out"] or r["picks_in"]:
            st.markdown('<div class="ws-h">Picks changing hands</div>', unsafe_allow_html=True)
            prows = []
            for lbl, side, cls in (("You send", r["picks_out"], "ws-dn"),
                                   ("You get", r["picks_in"], "ws-up")):
                for pk in side:
                    prows.append([f'<span class="ws-fnt">{lbl}</span>',
                                  f'<b class="{cls}">{PK.label(pk, _team_of(ctx, g, pk.get("origin")))}</b>',
                                  f'<span class="ws-fnt">≈ pick {PK.overall(pk["round"], n_teams):.0f} '
                                  f'overall</span>'])
            st.markdown(_tbl(["", "Pick", "~Worth"], prows,
                             widths=["78px", "auto", "42%"], wide=True), unsafe_allow_html=True)
            st.caption("Every pick is priced at the **middle of its round** — next year's draft "
                       "order follows standings that haven't happened, so a 2027 1st is not "
                       "assumed to be the 1.01. The scale is linear in picks, which understates "
                       "the very top of round one.")
        if r["roster"]:
            _alert("amb", "!", f'This changes your roster size by <b>{r["roster"]:+d}</b>. '
                               f'{"A freed spot is only worth something if there is a waiver add worth making." if r["roster"] < 0 else "You will need to drop someone to fit them."}')
        # Counters swap one of YOUR players for a different one; with no players on
        # a side there is nothing to swap, and a pick-for-pick deal has no counter
        # of that shape to offer.
        counters = (W.counter_offers(g["mine"], opp, [mine_names[n] for n in send],
                                     [opp_names[n] for n in get], g["slots"], g["proj"], reg,
                                     byes=g["byes"], week=g["week"], limit=3)
                    if (send and get) else [])
        if counters and r["them"] <= 0.05:
            st.markdown('<div class="ws-h">Counters that might actually clear</div>',
                        unsafe_allow_html=True)
            st.caption("Same ask, different player from you — the realistic negotiation.")
            st.markdown(_tbl(["Send instead", "~You", "~Them"],
                             [[c["send_names"][0], f'<b class="ws-up">+{c["you"]}</b>',
                               f'<span class="ws-up">+{c["them"]}</span>'] for c in counters],
                             widths=["auto", "78px", "78px"], wide=True), unsafe_allow_html=True)


# ------------------------------------------------------------------ 5 playoffs
def _playoffs(ctx, g) -> None:
    reg, meta = ctx["registry"], ctx["meta"]
    wks = SCH.playoff_weeks(meta)
    means, sds, recs = {}, {}, {}
    for oid, r in g["rosters"].items():
        if not r["players"]:
            continue
        m, s = W.team_distribution(r["players"], g["slots"], g["proj"], reg, g["byes"], g["week"])
        means[oid] = m
        sds[oid] = s
        se = r.get("settings") or {}
        recs[oid] = (int(se.get("wins") or 0), int(se.get("losses") or 0))
    pt = int(((api.get_league(str(meta.league_id)) or {}).get("settings") or {})
             .get("playoff_teams") or 4)
    weeks_left = max(0, (wks[0] - 1) - g["week"] + 1) if wks else 0
    odds = W.season_odds(means, sds, recs, weeks_left, min(pt, len(means)))
    mine = odds.get(g["me"], {})

    _tiles([
        ("Playoff odds", f'{mine.get("playoff_pct", 0)}%', f"top {pt} make it",
         "var(--green)" if mine.get("playoff_pct", 0) >= 50 else "var(--amber)"),
        ("Projected seed", f'{mine.get("avg_seed", 0):.1f}', f"of {len(means)} teams", "var(--ink)"),
        ("Playoff weeks", "–".join(str(w) for w in wks) if wks else "—",
         "derived from this league's settings", "var(--muted)"),
        ("Weeks to play", f"{weeks_left}", "before the bracket", "var(--muted)"),
    ])

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="ws-h">Where everyone lands</div>', unsafe_allow_html=True)
        rws = []
        for oid, o in sorted(odds.items(), key=lambda kv: -kv[1]["playoff_pct"]):
            nm = _owner_name(ctx, oid)
            rws.append([f'<b>{nm}</b>' if oid == g["me"] else nm,
                        f'{recs.get(oid,(0,0))[0]}–{recs.get(oid,(0,0))[1]}',
                        f'{means.get(oid,0):.0f}',
                        f'{o["playoff_pct"]}%', f'{o["avg_seed"]:.1f}'])
        st.markdown(_tbl(["Team", "Record", "~Proj/wk", "~Playoffs", "~Seed"], rws,
                         widths=["auto", "76px", "84px", "84px", "68px"]), unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="ws-h">Your players in the playoff weeks</div>',
                    unsafe_allow_html=True)
        dvp, sched = ctx.get("dvp"), ctx.get("schedule")
        rws = []
        for pid in [p for _s, p in W.lineup_check(g["mine"], g["slots"], g["proj"], reg,
                                                  g["byes"], g["week"])["spots"] if p][:8]:
            pm = reg.meta(pid)
            sos = SCH.playoff_sos(pm.team, pm.position, dvp, sched, weeks=wks) if (dvp and sched) else None
            if sos:
                kind = {"easy": "ok", "hard": "bad"}.get(sos[1], "nil")
                rws.append([f'{pm.name} {_pos_pill(pm.position)}', sos[2].split(":")[-1].strip(),
                            _chip(sos[0], kind)])
        if rws:
            st.markdown(_tbl(["Player", f"Weeks {wks[0]}–{wks[-1]}" if wks else "Slate", "Grade"], rws),
                        unsafe_allow_html=True)
        else:
            st.caption("Playoff strength-of-schedule needs the DvP table — it builds on the "
                       "Live Draft tab and is cached for the season.")


# -------------------------------------------------------------------- 6 league
def _league(ctx, g) -> None:
    reg, meta = ctx["registry"], ctx["meta"]
    rows = []
    all_pts = []
    for oid, r in g["rosters"].items():
        if not r["players"]:
            continue
        m, _s = W.team_distribution(r["players"], g["slots"], g["proj"], reg, g["byes"], g["week"])
        se = r.get("settings") or {}
        pf = float(se.get("fpts") or 0) + float(se.get("fpts_decimal") or 0) / 100.0
        rows.append({"oid": oid, "name": _owner_name(ctx, oid), "proj": m,
                     "w": int(se.get("wins") or 0), "l": int(se.get("losses") or 0), "pf": pf})
        all_pts.append(pf)
    rows.sort(key=lambda r: -r["proj"])

    st.markdown('<div class="ws-h">Power rankings — by roster strength, not by record</div>',
                unsafe_allow_html=True)
    rws = []
    for i, r in enumerate(rows, 1):
        games = r["w"] + r["l"]
        lk = W.luck(r["pf"], r["w"], games, all_pts) if games else None
        chip = (_chip(lk["label"], {"lucky": "bad", "unlucky": "warn", "earned": "ok"}[lk["label"]])
                if lk and lk["label"] != "—" else _chip("no games yet", "nil"))
        rws.append([str(i), f'<b>{r["name"]}</b>' if r["oid"] == g["me"] else r["name"],
                    f'{r["w"]}–{r["l"]}', f'{r["proj"]:.0f}', f'{r["pf"]:.0f}', chip])
    st.markdown(_tbl(["#", "Team", "Record", "~Proj/wk", "~Points for", "Luck"], rws,
                     widths=["34px", "auto", "76px", "84px", "94px", "120px"]),
                unsafe_allow_html=True)
    st.caption("Luck compares wins to an all-play record — how often this team's scoring would have "
               "beaten the rest of the league. A 2–0 team scoring bottom-third regresses, and that is "
               "the week to trade with them.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="ws-h">Recent league activity</div>', unsafe_allow_html=True)
        tx = W.transactions(str(meta.league_id), g["week"]) if meta.platform == "sleeper" else []
        if not tx:
            st.caption("No completed transactions yet.")
        else:
            rid_to_name = {}
            for oid, r in g["rosters"].items():
                rid_to_name[r.get("roster_id")] = _owner_name(ctx, oid)
            rws = []
            for t in tx[:8]:
                who = ", ".join(rid_to_name.get(x, "?") for x in (t["roster_ids"] or [])[:2])
                adds = ", ".join(reg.meta(p).name for p in list(t["adds"] or {})[:2]) or "—"
                bid = f'${t["bid"]}' if t.get("bid") else ""
                rws.append([f'W{t["week"]}', who, f'{t["type"]}: {adds} {bid}'])
            st.markdown(_tbl(["Wk", "Team", "Move"], rws), unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="ws-h">Positional strength across the league</div>',
                    unsafe_allow_html=True)
        pos_tot = {}
        for oid, r in g["rosters"].items():
            for p in r["players"]:
                try:
                    pm = reg.meta(p)
                except Exception:  # noqa: BLE001
                    continue
                if pm.position in ("QB", "RB", "WR", "TE"):
                    pos_tot.setdefault(pm.position, {}).setdefault(oid, 0.0)
                    pos_tot[pm.position][oid] += float(g["proj"].get(str(p), 0) or 0)
        rws = []
        for pos in ("QB", "RB", "WR", "TE"):
            tot = pos_tot.get(pos, {})
            if not tot:
                continue
            rank = sorted(tot, key=lambda o: -tot[o]).index(g["me"]) + 1 if g["me"] in tot else 0
            pct = 100 * (1 - (rank - 1) / max(1, len(tot))) if rank else 0
            colour = "var(--green)" if pct >= 66 else "var(--amber)" if pct >= 33 else "var(--red)"
            rws.append([_pos_pill(pos),
                        f'<div class="ws-bar"><i style="width:{pct:.0f}%;background:{colour}"></i></div>',
                        f'{rank} of {len(tot)}'])
        st.markdown(_tbl(["", "", "~You"], rws), unsafe_allow_html=True)


# ------------------------------------------------------------------- 7 keepers
@st.cache_data(ttl=900, show_spinner=False)
def _draft_rounds(league_id: str, owner: str):
    """{pid: round} for the picks THIS owner made in the league's own draft."""
    try:
        did = (api.get_league(league_id) or {}).get("draft_id")
        return {str(q["player_id"]): int(q["round"])
                for q in (api.get_draft_picks(did) or [])
                if q.get("player_id") and q.get("round") and str(q.get("picked_by")) == owner}
    except Exception:  # noqa: BLE001
        return {}


def _keepers(ctx, g) -> None:
    meta, reg = ctx["meta"], ctx["registry"]
    if meta.platform != "sleeper":
        st.info("Keeper tracking is Sleeper-only for now.")
        return
    rules = dict(K.load_keeper_rules(str(meta.league_id)) or {})
    reg_max = int(rules.get("max_regular_keepers") or 0)
    rook_max = int(rules.get("max_rookie_keepers") or 0)
    if not (reg_max or rook_max):
        st.info(f"**{meta.name}** isn't configured as a keeper league in its hub, so there is "
                "nothing to price. Set the keeper rules there and this fills in.")
        return
    rules["_last_round"] = meta.draft_rounds

    raw = K.load_keepers(str(meta.league_id), g["season"]) or {}
    existing = {str(k.get("player_id")): k for k in (raw.get(str(g["me"])) or [])}
    rows = W.keeper_outlook(
        g["mine"], drafted_round=_draft_rounds(str(meta.league_id), str(g["me"])),
        existing=existing, rules=rules, n_teams=meta.num_teams,
        adp_rank=ctx["adp_rank"], registry=reg, proj=g["proj"])

    keeps = [r for r in rows if r["verdict"] == "keep"]
    blocked = [r for r in rows if r["verdict"] == "blocked"]
    best = keeps[0] if keeps else None
    _tiles([
        ("Keeper slots", f"{reg_max + rook_max}",
         f"{reg_max} regular + {rook_max} rookie", "var(--ink)"),
        ("Your best value", best["name"].split()[-1] if best else "—",
         f"+{best['surplus']} picks of surplus" if best else "—", "var(--green)"),
        ("Blocked", f"{len(blocked)}",
         blocked[0]["blocked"] if blocked else "none aged out", 
         "var(--red)" if blocked else "var(--muted)"),
        ("Escalation", f"−{rules.get('year2_bump_rounds', 0)} rds/yr",
         f"max {rules.get('max_keep_years', '—')} keep years", "var(--muted)"),
    ])

    st.markdown('<div class="ws-h">Your roster, priced for next year</div>', unsafe_allow_html=True)
    body = []
    for r in rows:
        worth = f"pick {r['worth']:.0f}" if r["worth"] else '<span class="ws-fnt">unranked</span>'
        if r["surplus"] is None:
            sur = '<span class="ws-fnt">—</span>'
        elif r["surplus"] > 0:
            sur = f'<b class="ws-up">+{r["surplus"]}</b>'
        else:
            sur = f'<span class="ws-dn">{r["surplus"]}</span>'
        if r["verdict"] == "keep":
            v = _chip(f'keep · {r.get("slot_used", "")} slot', "ok")
        elif r["verdict"] == "blocked":
            v = _chip(r["blocked"] or "can't keep", "bad")
        else:
            v = _chip("cut", "nil")
        body.append([
            f'<b>{r["name"]}</b> {_pos_pill(r["pos"])} <span class="ws-fnt">{r["team"]}</span>',
            f'R{r["cost_round"]} <span class="ws-fnt">≈ pick {r["cost_pick"]}</span>',
            worth, sur, v, f'<span class="ws-fnt">{r["note"]}</span>'])
    st.markdown(_tbl(["Player", "Costs", "~Worth", "~Surplus", "Verdict", ""], body,
                     widths=["26%", "22%", "88px", "82px", "168px", "auto"], wide=True),
                unsafe_allow_html=True)
    st.caption("**Surplus is in draft picks**: a player who would go at pick 27 costing a "
               "round-14 pick (≈105th) is +78. Cost comes from where he actually came from — "
               "an existing keeper's round plus this league's "
               f"−{rules.get('year2_bump_rounds', 0)}-round-per-year escalation, the round you "
               "drafted him, the fixed rookie round, or the last round for a waiver add.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="ws-h">What this changes now</div>', unsafe_allow_html=True)
        if blocked:
            b = blocked[0]
            _alert("red", "⊘", f'<b>{b["name"]} has aged out</b> — {b["blocked"]}. He is a rental '
                               f'from here, so his trade value only falls. If you are selling, sell early.')
        cheap = [r for r in keeps if (r["surplus"] or 0) > 40]
        if cheap:
            _alert("ok", "◎", "<b>" + ", ".join(r["name"] for r in cheap[:3]) + "</b> "
                              "cost a late pick and are worth an early one. Those are the players "
                              "an in-season trade should be built around, not the ones you sell.")
        edge = [r for r in rows if r["verdict"] == "cut" and (r["surplus"] or -99) > -10]
        if edge:
            _alert("amb", "!", f'<b>{edge[0]["name"]}</b> is the first man out — '
                               f'{edge[0]["surplus"]} picks. If anyone above him gets hurt or '
                               f'traded, he is your replacement keeper.')
        _alert("ok", "$", f'A waiver add costs <b>round {meta.draft_rounds}</b> to keep, so a '
                          f'mid-season breakout is the cheapest keeper available. Every claim '
                          f'from here competes with the list above, not with your bench.')
    with c2:
        st.markdown('<div class="ws-h">Slots, filled</div>', unsafe_allow_html=True)
        used_r = sum(1 for r in keeps if r.get("slot_used") == "regular")
        used_k = sum(1 for r in keeps if r.get("slot_used") == "rookie")
        st.markdown(_tbl(["Slot type", "~Used", "~Max"],
                         [["Regular", str(used_r), str(reg_max)],
                          ["Rookie", str(used_k), str(rook_max)]]), unsafe_allow_html=True)
        st.caption("A rookie who misses the rookie allowance falls back to a regular slot rather "
                   "than being cut — otherwise a +64 rookie loses his place to a −19 veteran. "
                   "**If this league forbids that**, the rookie rows are the ones to check.")
