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
    st.markdown('<div class="ws-h">Proposals, scored for both sides</div>', unsafe_allow_html=True)
    if not ideas:
        st.caption("Nothing with this team improves your lineup this week — one-for-one or packaged.")
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
        st.markdown(_tbl(["", "You send", "You get", "~You", "~Them", ""], rows),
                    unsafe_allow_html=True)
        if mutual:
            st.caption(f"**{len(mutual)} of these actually clear** — both lineups improve. Those are "
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
            st.caption("**None of these help both sides.** One-for-ones only work when two managers "
                       "have mirrored holes, which is rare; packages are where most real trades "
                       "live, and none clears here either. Try another partner.")
        st.caption("A 2-for-1 also costs you a roster spot, which this does not price — the freed "
                   "slot is only worth something if there is a waiver add worth making.")

    if ctx["meta"].platform == "sleeper":
        st.markdown('<div class="ws-h" style="margin-top:12px">Keeper-cost lens</div>',
                    unsafe_allow_html=True)
        krows = {r["pid"]: r for r in _keeper_rows(ctx, g)}
        rws = []
        for i in ideas[:3]:
            for pids, who in ((i["send"], "you send"), (i["get"], "you get")):
                for pid in pids:
                    r = krows.get(str(pid))
                    if r:
                        sur = (f'<b class="ws-up">+{r["surplus"]}</b>' if (r["surplus"] or 0) > 0
                               else f'<span class="ws-dn">{r["surplus"]}</span>')
                        cost = f'R{r["cost_round"]} <span class="ws-fnt">{r["note"]}</span>'
                    else:
                        # not on your roster — you cannot know his history, only what
                        # he would cost you as a new addition
                        sur = '<span class="ws-fnt">—</span>'
                        cost = f'R{ctx["meta"].draft_rounds} <span class="ws-fnt">if added</span>'
                    rws.append([f'{reg.meta(pid).name}', who, cost, sur])
        st.markdown(_tbl(["Player", "Side", "Keeper cost next year", "~Surplus"], rws),
                    unsafe_allow_html=True)
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
    st.markdown(_tbl(["Player", "Costs", "~Worth", "~Surplus", "Verdict", ""], body),
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
