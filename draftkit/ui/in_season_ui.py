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

from .. import (config, inseason, keepers as K, phase as PH, projections as PJ,
                schedule as SCH, sleeper_client as api, weekly as W)
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


def _tbl(head, rows) -> str:
    th = "".join(f'<th style="text-align:{"right" if h.startswith("~") else "left"}">'
                 f'{h.lstrip("~")}</th>' for h in head)
    return ('<table class="ws-t"><thead><tr>' + th + '</tr></thead><tbody>'
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


def _gather(ctx, week):
    """Everything the tabs share, fetched once."""
    meta, reg = ctx["meta"], ctx["registry"]
    season = config.current_season()
    rosters = _rosters(meta.platform, str(meta.league_id), season)
    me = str(ctx.get("my_team") or "")
    mine = (rosters.get(me) or {}).get("players") or []
    try:
        proj = PJ.for_league(meta, reg, season, week=week) or {}
    except Exception:  # noqa: BLE001
        proj = {}
    return {"rosters": rosters, "me": me, "mine": mine, "proj": proj,
            "slots": ctx["roster_slots"], "byes": ctx.get("byes"), "week": week,
            "season": season}


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
    stand-in before the schedule exists."""
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
    lc = W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"])
    oid, opp = _opponent(ctx, g)
    om, os_ = W.team_distribution(opp, g["slots"], g["proj"], reg, g["byes"], g["week"]) if opp else (0, 1)
    wp = W.win_prob(lc["mean"], lc["sd"], om, os_) if opp else None
    wp_fixed = (W.win_prob(lc["mean"] + lc["gain"], lc["sd"], om, os_) if (opp and lc["gain"]) else wp)

    _tiles([
        ("Lineup", f"{len(lc['fixes'])} fixes" if lc["fixes"] else "Optimal",
         f"worth +{lc['gain']} pts" if lc["fixes"] else "nothing to change",
         "var(--amber)" if lc["fixes"] else "var(--green)"),
        ("Projected", f"{lc['mean']:.1f}",
         f"vs {_owner_name(ctx, oid)} · {om:.1f}" if opp else "no opponent yet", "var(--ink)"),
        ("Win prob", f"{100*wp:.0f}%" if wp is not None else "—",
         (f"{100*wp_fixed:.0f}% if you make the fixes" if lc["fixes"] else "lineup already set"),
         "var(--green)" if (wp or 0) >= .5 else "var(--red)"),
        ("Bench points", f"{sum(float(g['proj'].get(p,0) or 0) for p in lc['bench']):.0f}",
         f"{len(lc['bench'])} players sitting", "var(--muted)"),
    ])

    left, right = st.columns([1.5, 1])
    with left:
        st.markdown('<div class="ws-h">Start / sit — every slot, with the cost of being wrong</div>',
                    unsafe_allow_html=True)
        fix_by_out = {f["out"]: f for f in lc["fixes"]}
        rows = []
        for slot, pid in lc["spots"]:
            if not pid:
                rows.append([f'<b class="ws-sl">{slot}</b>', '<span class="ws-dim">(empty)</span>',
                             "—", "—", "—", _chip("no one eligible", "bad")])
                continue
            pm = reg.meta(pid)
            f = fix_by_out.get(str(pid))
            better = (f'{reg.meta(f["in"]).name} <span class="ws-fnt">'
                      f'{reg.meta(f["in"]).team}</span>') if f else '<span class="ws-fnt">—</span>'
            delta = f'<b class="ws-up">+{f["gain"]}</b>' if f else '<span class="ws-fnt">—</span>'
            verdict = _chip(f'start {reg.meta(f["in"]).name.split()[-1]}', "ok") if f else _chip("optimal", "nil")
            rows.append([f'<b class="ws-sl">{slot}</b>',
                         f'<b>{pm.name}</b> {_pos_pill(pm.position)} <span class="ws-fnt">{pm.team}</span>',
                         f'{float(g["proj"].get(str(pid), 0) or 0):.1f}', better, delta, verdict])
        st.markdown(_tbl(["", "Starter", "~Proj", "Better on your bench", "~Δ", ""], rows),
                    unsafe_allow_html=True)
        st.caption("Δ is the change to your **projected team total**, not the two players' raw "
                   "projections — swapping a WR you would flex anyway moves nothing.")

    with right:
        st.markdown('<div class="ws-h">Needs a decision</div>', unsafe_allow_html=True)
        if lc["fixes"]:
            for f in lc["fixes"][:3]:
                _alert("amb", "↑", f'<b>{reg.meta(f["in"]).name} over {reg.meta(f["out"]).name}</b> '
                                   f'at {f["slot"]} — worth <b>+{f["gain"]}</b> to your total.')
        else:
            _alert("ok", "✓", "<b>Your lineup is already optimal</b> for this week's projections. "
                              "Nothing on your bench beats a starter.")
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
    fas = inseason.free_agents(meta, reg, g["proj"], taken, limit=60)
    board = W.waiver_board(g["mine"], g["slots"], g["proj"], reg, fas,
                           byes=g["byes"], week=g["week"], limit=14)
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

    st.markdown('<div class="ws-h">Ranked by what they add to YOUR starting lineup</div>',
                unsafe_allow_html=True)
    rows = []
    for r in board[:12]:
        bid = W.bid_guidance(r["gain"], left, weeks_left)
        if r["gain"] > 0.05:
            verdict, kind = f"${bid['low']}–{bid['high']}", "ok"
        else:
            verdict, kind = "$0 — no upgrade", "nil"
        rows.append([
            f'<b>{r["name"]}</b> {_pos_pill(r["pos"])}',
            f'{r["proj"]:.1f}',
            (f'<b class="ws-up">+{r["gain"]}</b>' if r["gain"] > 0.05
             else '<span class="ws-fnt">+0.0</span>'),
            _chip(verdict, kind),
        ])
    st.markdown(_tbl(["Player", "~Proj", "~Adds to lineup", "Bid"], rows), unsafe_allow_html=True)
    st.caption("A player who would not crack your starting lineup is worth **$0 to you**, however "
               "highly he is ranked elsewhere — that is what this column is for.")

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
        rules = K.load_keeper_rules(str(meta.league_id)) if meta.platform == "sleeper" else {}
        rws = []
        for p in sorted(g["mine"], key=lambda x: float(g["proj"].get(x, 0) or 0)):
            if p in started:
                continue
            kp = inseason.keeper_price(meta, p, reg, rules) or {}
            cheap = (kp.get("round") or 99) >= max(1, int(meta.draft_rounds) - 2)
            pm = reg.meta(p)
            rws.append([f'{pm.name} {_pos_pill(pm.position)}',
                        f'{float(g["proj"].get(p,0) or 0):.1f}',
                        _chip("safe drop", "ok") if cheap else
                        _chip(f'keeper R{kp.get("round","?")}', "warn")])
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
    mm, ms = W.team_distribution(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"])
    om, os_ = W.team_distribution(opp, g["slots"], g["proj"], reg, g["byes"], g["week"])
    wp = W.win_prob(mm, ms, om, os_)
    them = _owner_name(ctx, oid)

    st.markdown(
        f'<div class="ws-vs"><div><b>You</b><div class="ws-ts">{mm:.1f} ± {ms:.0f}</div></div>'
        f'<div class="ws-mid">WEEK {g["week"]}</div>'
        f'<div style="text-align:right"><b>{them}</b><div class="ws-ts">{om:.1f} ± {os_:.0f}</div></div></div>'
        f'<div class="ws-wp"><i style="width:{100*wp:.0f}%"></i>'
        f'<span>{100*wp:.0f}% you &nbsp;·&nbsp; {mm:.1f} – {om:.1f}</span></div>',
        unsafe_allow_html=True)
    st.caption("Win probability treats each team total as a normal distribution — the spread comes "
               "from position-level weekly variance, so a boom/bust roster reads differently from a "
               "steady one with the same projection.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="ws-h">Slot by slot</div>', unsafe_allow_html=True)
        ml = W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"])["spots"]
        ol = W.lineup_check(opp, g["slots"], g["proj"], reg, g["byes"], g["week"])["spots"]
        rows = []
        for (s, a), (_s2, b) in zip(ml, ol):
            pa = float(g["proj"].get(str(a), 0) or 0) if a else 0.0
            pb = float(g["proj"].get(str(b), 0) or 0) if b else 0.0
            d = pa - pb
            rows.append([f'<b class="ws-sl">{s}</b>',
                         f'{reg.meta(a).name if a else "—"} <span class="ws-fnt">{pa:.1f}</span>',
                         (f'<b class="ws-up">+{d:.1f}</b>' if d > 0 else f'<b class="ws-dn">{d:.1f}</b>'),
                         f'<span class="ws-dim">{reg.meta(b).name if b else "—"} {pb:.1f}</span>'])
        st.markdown(_tbl(["", "You", "~Edge", "Them"], rows), unsafe_allow_html=True)
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
def _trades(ctx, g) -> None:
    reg = ctx["registry"]
    partners = [(o, r["players"]) for o, r in g["rosters"].items()
                if o != g["me"] and r["players"]]
    if not partners:
        st.info("No other rosters found.")
        return
    names = [_owner_name(ctx, o) for o, _ in partners]
    pick = st.selectbox("Trade partner", names, key=f"ws_tp_{ctx['league_key']}")
    oid, opp = partners[names.index(pick)]

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

    ideas = W.trade_ideas(g["mine"], opp, g["slots"], g["proj"], reg,
                          byes=g["byes"], week=g["week"], max_ideas=6)
    st.markdown('<div class="ws-h">Proposals, scored for both sides</div>', unsafe_allow_html=True)
    if not ideas:
        st.caption("No one-for-one swap with this team improves your lineup this week.")
    else:
        st.markdown(_tbl(["You send", "You get", "~You", "~Them", ""],
                         [[f'{i["send_name"]}', f'<b>{i["get_name"]}</b>',
                           f'<b class="ws-up">+{i["you"]}</b>',
                           (f'<span class="ws-up">+{i["them"]}</span>' if i["them"] > 0
                            else f'<span class="ws-dn">{i["them"]}</span>'),
                           _chip("both win", "ok") if i["mutual"] else _chip("they'll refuse", "bad")]
                          for i in ideas]), unsafe_allow_html=True)
        st.caption("Deals that only help you are listed as such. A proposal your opponent loses on "
                   "is not a trade idea, it is a wish.")

    if ctx["meta"].platform == "sleeper":
        st.markdown('<div class="ws-h" style="margin-top:12px">Keeper-cost lens</div>',
                    unsafe_allow_html=True)
        rules = K.load_keeper_rules(str(ctx["meta"].league_id))
        rws = []
        for i in ideas[:4]:
            for pid, who in ((i["send"], "you send"), (i["get"], "you get")):
                kp = inseason.keeper_price(ctx["meta"], pid, reg, rules) or {}
                rws.append([f'{reg.meta(pid).name}', who, kp.get("note", "—")])
        st.markdown(_tbl(["Player", "Side", "Keeper cost next year"], rws), unsafe_allow_html=True)
        st.caption("In a keeper league every trade is two trades: this season's points and next "
                   "season's price.")


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
        st.markdown(_tbl(["Team", "Record", "~Proj/wk", "~Playoffs", "~Seed"], rws),
                    unsafe_allow_html=True)
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
    st.markdown(_tbl(["#", "Team", "Record", "~Proj/wk", "~Points for", "Luck"], rws),
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
def _keepers(ctx, g) -> None:
    meta, reg = ctx["meta"], ctx["registry"]
    if meta.platform != "sleeper":
        st.info("Keeper tracking is Sleeper-only for now.")
        return
    rules = K.load_keeper_rules(str(meta.league_id)) or {}
    per = (rules.get("max_regular_keepers") or 0) + (rules.get("max_rookie_keepers") or 0)
    if not per:
        st.info(f"**{meta.name}** isn't configured as a keeper league in its hub, so there is "
                "nothing to price. Set the keeper rules there and this fills in.")
        return
    used = inseason.keeper_slots_used(meta, g["mine"], reg, rules) or {}

    _tiles([
        ("Keeper slots", f"{per}", "per team next year", "var(--ink)"),
        ("Rookie slots used", f'{used.get("rookie_used", 0)} of {used.get("rookie_max", 0)}',
         "rookies on your roster", "var(--muted)"),
        ("Roster", f'{len(g["mine"])}', "candidates to price", "var(--muted)"),
        ("Draft rounds", f"{meta.draft_rounds}", "a waiver add costs the last round", "var(--muted)"),
    ])

    st.markdown('<div class="ws-h">Your roster, priced for next year</div>', unsafe_allow_html=True)
    rws = []
    for pid in sorted(g["mine"], key=lambda p: -float(g["proj"].get(p, 0) or 0)):
        pm = reg.meta(pid)
        kp = inseason.keeper_price(meta, pid, reg, rules) or {}
        rnd = kp.get("round")
        proj = float(g["proj"].get(pid, 0) or 0)
        # cheap = late round for a player you actually start
        if rnd and rnd >= max(1, int(meta.draft_rounds) - 3) and proj >= 10:
            verdict = _chip("bargain — lock it in", "ok")
        elif rnd and rnd <= 3 and proj < 14:
            verdict = _chip("expensive for the output", "bad")
        elif proj >= 10:
            verdict = _chip("fair", "nil")
        else:
            verdict = _chip("not worth a slot", "nil")
        rws.append([f'<b>{pm.name}</b> {_pos_pill(pm.position)} <span class="ws-fnt">{pm.team}</span>',
                    kp.get("note", "—"), f"{proj:.1f}", verdict])
    st.markdown(_tbl(["Player", "Keeper cost", "~Proj", "Verdict"], rws), unsafe_allow_html=True)
    st.caption("A waiver add inherits the **last round** as its keeper cost in most leagues — which "
               "makes a mid-season breakout the cheapest keeper you can get. Bid accordingly.")
    _alert("ok", "$", "Every add from here competes with the players above for a keeper slot, "
                      "not with your bench.")
