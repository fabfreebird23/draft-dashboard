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

import re
from typing import Optional

import streamlit as st

from .. import faabmarket as FM
from .. import (config, ecr as ECR, gametime as GT, inseason, keepers as K, lineup as LU, phase as PH,
                picks as PK, projections as PJ, schedule as SCH, sleeper_client as api,
                weekly as W, weekview as WV)
from . import components as C
from .widgets import rerun_here
from .. import theme as _T

# Bump when a panel's numbers change MEANING: Streamlit's in-memory caches key on
# arguments, not on what the fetcher returns, so a fixed parser would otherwise
# keep serving the broken rows until the process restarts. (2 = Flock's FLEX rank
# rebuilt from per-analyst overall lists; it had been a positional rank.)
_PANEL_VER = 2

TABS = ["Command Center", "Live", "Lineup", "Rankings", "Waivers", "Matchup", "Trades", "Playoffs", "League", "Keepers"]

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
    """A tab's headline facts as ONE line, not a row of four boxes.

    The boxes were 90px tall on every tab and two of the four rarely changed a
    decision; one strip reads left to right and leaves the screen to the answer.
    `items` keeps its old shape — (label, value, sub, colour) — so every tab
    switched over without being touched. A None item is skipped."""
    parts = []
    for it in items:
        if not it:
            continue
        label, value, sub, colour = it
        parts.append(f'<span class="ws-sf"><b style="color:{colour}">{value}</b>'
                     f'<em>{label}</em>' + (f'<i>{sub}</i>' if sub else "") + '</span>')
    st.markdown('<div class="ws-strip">' + "".join(parts) + '</div>', unsafe_allow_html=True)


def _md_inline(text: str) -> str:
    """**bold**, *italic* and `code` → HTML, for notes rendered as raw HTML."""
    t = C._esc(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


def _note(text: str, where=None) -> None:
    """The explanations that used to sit under every section as a caption.

    Short ones (a status — "nobody else plays TE") stay visible as one quiet
    line. Long ones fold behind ⓘ with their first sentence as the label, so
    the gist is still on screen and the paragraph is a tap away. 16 captions
    across the tabs were mostly read once; this keeps them without the wall."""
    tgt = where or st
    plain = re.sub(r"[*`]", "", text or "").strip()
    if not plain:
        return
    if len(plain) <= 110:
        tgt.markdown(f'<div class="ws-note">{_md_inline(text)}</div>', unsafe_allow_html=True)
        return
    first = re.split(r"(?<=[.!?—])\s", plain, maxsplit=1)[0].rstrip("—").strip()
    if len(first) > 84:
        first = first[:82].rsplit(" ", 1)[0] + "…"
    tgt.markdown(f'<details class="ws-why"><summary><span>ⓘ</span>{C._esc(first)}</summary>'
                 f'<div>{_md_inline(text)}</div></details>', unsafe_allow_html=True)


def _alert(kind, icon, html) -> None:
    st.markdown(f'<div class="ws-al ws-{kind}"><span>{icon}</span><div>{html}</div></div>',
                unsafe_allow_html=True)


# ------------------------------------------------------------------ data gather
@st.cache_data(ttl=900, show_spinner=False)
def _espn_rosters(league_id: str, season: int, _provider):
    """ESPN rosters, in Sleeper's shape. Cached on (league, season) — the provider
    is a leading-underscore arg so Streamlit doesn't try to hash it."""
    try:
        return _provider.get_rosters() or {}
    except Exception:  # noqa: BLE001 — a dead read must not take the tab down
        return {}


@st.cache_data(ttl=60, show_spinner=False)
def _live(platform: str, league_id: str, week: int, _provider):
    """Actual points this week, 60s fresh — the one read that has to be current."""
    try:
        return _provider.get_live_scores(week) or {}
    except Exception:  # noqa: BLE001
        return {}


@st.cache_data(ttl=900, show_spinner=False)
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


def _refresh_bucket(season: int, week: int) -> int:
    """A number that changes every 15 minutes — or every 2 while a game is on.

    The tabs used to re-read rosters, projections, the panels and the schedule
    on every click, and a click took ten seconds. Nothing on a Tuesday changes
    in a quarter of an hour; on a Sunday afternoon the score does.
    """
    import time as _t
    try:
        # Two minutes ONLY while a game is in progress. "late" (between
        # windows on a Sunday) has nothing changing on the field.
        live = GT.week_phase(GT.load_week(season, week)) == "live"
    except Exception:  # noqa: BLE001
        live = False
    return int(_t.time() // (120 if live else 900))


def _slow_bucket(season: int, week: int) -> int:
    """A number that changes every 15 minutes, GAME OR NO GAME.

    The two-minute clock is right for a score and wrong for everything built
    on top of one. Rankings rows, the free-agent optimiser pass and the waiver
    board cost 4–10s to build and none of them mean anything different two
    minutes later — so on a Sunday the fast clock was throwing away exactly the
    work that takes the longest, every two minutes, and every first click after
    a roll paid for it again. Ranks ride this one; scores ride the other.
    """
    import time as _t
    return int(_t.time() // 900)


def _gather(ctx, week):
    """Everything the tabs share, fetched once per refresh bucket (see
    `_refresh_bucket`) — the same dict for every tab until then."""
    season = config.current_season()
    return _gather_cached(ctx["league_key"], week, _refresh_bucket(season, week), ctx, _GATHER_V)


# Bump when _gather_raw changes shape: st.cache_data hashes only the cached
# function's own code, so a fix inside _gather_raw (the 7½ pick book) sat
# behind a stale cache on Cloud until the bucket rolled over.
_GATHER_V = 2


@st.cache_data(show_spinner=False, max_entries=8)
def _gather_cached(league_key: str, week: int, bucket: int, _ctx, version: int = 0):
    return _gather_raw(_ctx, week)


def _gather_raw(ctx, week):
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
    # the keeper rules' round count, not the latest draft's: 7½ Men's latest
    # draft was the 4-round rookie draft, which made every team look like it
    # owned only rounds 1-4 of next year and shoved every keeper into them
    try:
        _kr = K.price_rounds(K.load_keeper_rules(str(meta.league_id)) or {}, season, 0)
    except Exception:  # noqa: BLE001
        _kr = 0
    book = _pick_book(meta.platform, str(meta.league_id), season,
                      max(int(getattr(meta, "draft_rounds", 14) or 14), _kr),
                      _json.dumps(sorted(int(x) for x in rids)))
    # The NFL week itself — kickoffs, game state, the line — and this league's
    # actual points. Both degrade to empty; every screen below checks before use.
    games = GT.load_week(season, week)
    phase = GT.week_phase(games)
    # The one read that has to be fresh, and only while there is something to be
    # fresh about: before kickoff it is a wasted round trip on every tab.
    live = (_live(meta.platform, str(meta.league_id), week, ctx["provider"])
            if (games and phase in ("live", "late", "done")) else {})
    return {"rosters": rosters, "me": me, "mine": mine, "starters": starters,
            "games": games, "phase": phase, "live": live,
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


def _record(g, owner_id) -> str:
    """'4-2' (or '4-2-1') from the roster's settings; '' before week 1."""
    se = ((g.get("rosters") or {}).get(str(owner_id)) or {}).get("settings") or {}
    w, l, t = int(se.get("wins") or 0), int(se.get("losses") or 0), int(se.get("ties") or 0)
    if not (w or l or t):
        return ""
    return f"{w}-{l}" + (f"-{t}" if t else "")


def _top_photo(reg, g, pids):
    """The Sleeper photo id of the best projected player in `pids` — the face
    a scoreboard side wears."""
    best = max((p for p in pids if p), key=lambda p: float(g["proj"].get(str(p), 0) or 0), default=None)
    if not best:
        return None
    try:
        return getattr(reg.meta(best), "sleeper_pid", None) or best
    except Exception:  # noqa: BLE001
        return best


def _opponent(ctx, g):
    """(owner_id, pids) of this week's opponent, or the closest-strength team as a
    stand-in before the schedule exists.

    Callers that need the lineup he has SET (not the one he should set) get it from
    `_opp_starters` rather than a third return value, because most callers — trades,
    keepers — only ever want the roster.
    """
    meta = ctx["meta"]
    # ESPN keeps the schedule somewhere Sleeper's client cannot reach, so ask the
    # provider. Skipping this is not a cosmetic loss: the fallback below picks the
    # closest-strength team as a STAND-IN, which produces a scoreboard, a win
    # probability and a swing player for a game that is not being played.
    if meta.platform != "sleeper":
        try:
            _pairs = ctx["provider"].get_week_pairs(g["week"]) or {}
            _oid = _pairs.get(str(g["me"]))
            if _oid and (g["rosters"].get(str(_oid)) or {}).get("players"):
                return str(_oid), g["rosters"][str(_oid)]["players"]
        except Exception:  # noqa: BLE001 — fall through to the stand-in
            pass
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


# ------------------------------------------------------------------ deep links
def _links(ctx, week: int) -> dict:
    """{key: (label, url)} into the league's own site — the page each tab is
    about, so the app never makes him hunt for where to actually click."""
    meta = ctx["meta"]
    lid, me, season = str(meta.league_id), str(ctx.get("my_team") or ""), config.current_season()
    if meta.platform == "espn":
        q = f"leagueId={lid}&seasonId={season}"
        return {"team": ("My team", f"https://fantasy.espn.com/football/team?{q}&teamId={me}"),
                "waivers": ("Free agents", f"https://fantasy.espn.com/football/players/add?leagueId={lid}"),
                "matchup": ("Matchup", f"https://fantasy.espn.com/football/boxscore?{q}&teamId={me}"
                                       f"&matchupPeriodId={week}&scoringPeriodId={week}&view=scoringperiod"),
                "trades": ("Trade", f"https://fantasy.espn.com/football/team/tradecenter?{q}&teamId={me}"),
                "league": ("League", f"https://fantasy.espn.com/football/league?leagueId={lid}"),
                "standings": ("Standings", f"https://fantasy.espn.com/football/league/standings?leagueId={lid}")}
    base = f"https://sleeper.com/leagues/{lid}"
    return {"team": ("My team", f"{base}/team"),
            "waivers": ("Players", f"{base}/players"),
            "matchup": ("Matchup", f"{base}/matchup"),
            "trades": ("Trades", f"{base}/trades"),
            "league": ("League", f"{base}"),
            "standings": ("Standings", f"{base}/standings")}


_TAB_LINK = {"Command Center": "team", "Live": "matchup", "Lineup": "team", "Rankings": "waivers", "Waivers": "waivers", "Matchup": "matchup",
             "Trades": "trades", "Playoffs": "standings", "League": "league", "Keepers": "team"}


def _link_bar(ctx, tab: str, week: int) -> str:
    """One link: the league site's page for the tab he's on. Five links on the
    nav row were five things to read on every screen to use one of them."""
    ln = _links(ctx, week)
    plat = "ESPN" if ctx["meta"].platform == "espn" else "Sleeper"
    lab, url = ln[_TAB_LINK.get(tab, "team")]
    return (f'<div class="ws-ext"><a class="on" href="{url}" target="_blank" rel="noopener" '
            f'title="{lab} on {plat}">{plat} ↗</a></div>')


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
        _note("**Preseason** — projections are live, but records, results and "
                   "transactions stay empty until week 1 kicks off.")

    if tab == "Command Center":
        _command(ctx, g)
    elif tab == "Live":
        _live_view(ctx, g)
    elif tab == "Lineup":
        _lineup(ctx, g)
    elif tab == "Rankings":
        _rankings(ctx, g)
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


def _top_claim(ctx, g):
    """The one waiver add worth making, or None. Cheap enough to sit on the
    Command Center because it reuses the Waivers tab's own (cached) board."""
    meta, reg = ctx["meta"], ctx["registry"]
    try:
        taken = {p for r in g["rosters"].values() for p in r["players"]}
        board = _waiver_board_cached(ctx["league_key"], g["week"],
                                     _slow_bucket(g["season"], g["week"]), ctx, g, taken)
        # under a point it is a tiebreak, not a claim — the Waivers tab lists those
        top = next((r for r in board if r["gain"] >= 1.0), None)
        if not top:
            return None
        fa = inseason.faab(meta) or {}
        budget = int(fa.get("budget") or 0)
        left = max(0, budget - int((fa.get("by_owner") or {}).get(str(g["me"]), 0) or 0))
        bid = FM.bid(meta, g["week"], top, budget, left, max(1, 14 - g["week"])) if left else None
        own = ((g.get("ros") or {}).get(str(top["pid"])) or {}).get("owned")
        from .. import udk_waivers as UW
        _wv = (_udk_wv(g["season"], g["week"], reg) or {}).get(str(top["pid"]))
        return {**top, "bid": bid, "left": left, "budget": budget, "owned": own,
                "udk": UW.label(_wv, left or budget)}
    except Exception:  # noqa: BLE001
        return None


def _day_line(g, cur, reg) -> str:
    """"Tuesday · waivers open · first lock Wed 8:20 in 33h" — the calendar, once."""
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        now = _dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001
        now = _dt.datetime.now()
    bits = [f"<b>{now.strftime('%A')}</b>", WV.phase_label(g.get("phase") or "")]
    nl = WV.next_lock(cur, reg, g.get("games") or {})
    if nl and g.get("phase") in ("waivers", "setup"):
        bits.append(f'first lock <b>{nl[2]}</b> in <span class="on">{WV.countdown(nl[0])}</span>')
    elif g.get("phase") in ("live", "late"):
        bits.append('<span class="on">live</span>')
    return '<div class="ws-day">' + " · ".join(b for b in bits if b) + '</div>'


def _still_rows(cur, reg, g, live, proj):
    """[(name, sub, state)] for one side, kickoff order, played men last."""
    games = g.get("games") or {}
    pp = (live or {}).get("players") or {}
    rows = []
    for _s, pid in cur:
        if not pid or str(pid) in ("0", "None"):
            continue
        gm = WV.game_of(reg, games, pid)
        st_ = GT.status(gm)
        nm = reg.meta(pid).name
        pj = float(proj.get(str(pid), 0) or 0)
        if st_ == "post":
            rows.append((GT.kickoff_ts(gm), nm, f'{pp.get(str(pid), 0.0):.1f}', "done"))
        elif st_ == "in":
            rows.append((GT.kickoff_ts(gm), nm, f'{pp.get(str(pid), 0.0):.1f} · live', "now"))
        elif st_ == "bye":
            rows.append((float("inf"), nm, "bye", "bye"))
        else:
            rows.append((GT.kickoff_ts(gm), nm, f'{GT.day_label(gm)} · proj {pj:.0f}', "now"))
    order = {"now": 0, "pre": 0, "done": 1, "bye": 2}
    rows.sort(key=lambda r: (order.get(r[3], 1), r[0]))
    return [(n, s, st_) for _k, n, s, st_ in rows]


# ------------------------------------------------------------- 1 command centre
def _command(ctx, g) -> None:
    reg = ctx["registry"]
    games, phase, live = g.get("games") or {}, g.get("phase") or "setup", g.get("live") or {}
    lc = _open_moves(W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"],
                                    current=g.get("starters")), reg, games)
    avail = W.availability_report(g["mine"], g["slots"], g["proj"], reg,
                                  byes=g["byes"], week=g["week"], starters=g["starters"])
    oid, opp = _opponent(ctx, g)
    ost = _opp_starters(g, oid) if opp else []
    # His SET lineup, same as yours — scoring yourself on what you have and him on
    # what he ought to have is a thumb on the scale, and it made this tile disagree
    # with the Matchup tab about the same game.
    om, os_ = (W.team_distribution(opp, g["slots"], g["proj"], reg, g["byes"], g["week"],
                                   current=ost) if opp else (0, 1))
    _now = lc["current_total"] if lc["have_current"] else lc["mean"]
    wp = W.win_prob(_now, lc["sd"], om, os_) if opp else None
    wp_fixed = (W.win_prob(_now + lc["gain"], lc["sd"], om, os_) if (opp and lc["gain"]) else wp)

    # ---- kickoff placement, played state, the clock --------------------
    cur = lc["current"]
    adv = WV.slot_advice(cur, reg, games) if lc["have_current"] else []
    # Don't advise re-seating a man the list above tells him to bench — once
    # that move is made the seat advice is moot, and two rows about the same
    # player pulling different ways is how a list stops being read.
    _benching = {str(m["out"]) for m in lc["moves"]}
    adv = [a for a in adv if str(a["pid"]) not in _benching and str(a["swap_pid"]) not in _benching]
    me_live = live.get(str(g["me"])) or {}
    opp_live = (live.get(str(oid)) or {}) if oid else {}
    ps = WV.played_state(cur, reg, games, me_live)
    ops = WV.played_state(list(zip(g["slots"], ost)), reg, games, opp_live) if opp else None
    started = phase in ("live", "late", "done") and bool(games)
    if started:
        # Once a game has kicked off the projection is the wrong number. Actual for
        # the men who have played, projection for the rest.
        _me_pts = float(me_live.get("points") or 0.0)
        _opp_pts = float(opp_live.get("points") or 0.0) if opp else 0.0
        _me_end = WV.live_projection(cur, g["proj"], reg, games, me_live)
        _opp_end = (WV.live_projection(list(zip(g["slots"], ost)), g["proj"], reg, games, opp_live)
                    if opp else 0.0)
        wp_live = W.win_prob(_me_end, lc["sd"] * 0.7, _opp_end, os_ * 0.7) if opp else None
    else:
        _me_pts, _opp_pts, _me_end, _opp_end, wp_live = _now, om, _now, om, wp

    # ---- THE WEEK, as one hero -------------------------------------------
    _tone_lineup = ("mid" if lc["moves"] else ("up" if lc["have_current"] else ""))
    _n_set = len([1 for _s, p in cur if p])
    if started:
        me_sub = f'you · {ps["n"] - len(ps["pre"]) - len(ps["live"])} of {ps["n"]} played'
        opp_sub = (f'{ops["n"] - len(ops["pre"]) - len(ops["live"])} of {ops["n"]} played'
                   if ops else "none scheduled")
        tiles = [
            ("Still to play", f'{len(ps["pre"]) + len(ps["live"])}',
             ("all done" if not (ps["pre"] or ps["live"]) else
              ", ".join(reg.meta(p).name.split()[-1] for p in (ps["live"] + ps["pre"])[:3])),
             "up" if (ps["pre"] or ps["live"]) else ""),
            ("Projected final", f"{_me_end:.0f} – {_opp_end:.0f}" if opp else f"{_me_end:.0f}",
             "actual so far + projection for the rest", "up" if _me_end >= _opp_end else "dn"),
            ("Win prob now", f"{100*wp_live:.0f}%" if wp_live is not None else "—",
             (f"was {100*wp:.0f}% before kickoff" if wp is not None else ""),
             "up" if (wp_live or 0) >= .5 else "dn"),
            ("Bench so far", f'{sum(float(v) for k, v in (me_live.get("players") or {}).items() if k not in {str(p) for _s, p in cur if p}):.1f}',
             "points from men you sat", ""),
        ]
    else:
        me_sub = f'you · {_n_set} starters set'
        opp_sub = "their set lineup" if opp else "none scheduled"
        tiles = [
            ("Lineup", (f"{len(lc['moves'])} change{'s' if len(lc['moves']) != 1 else ''}"
                        if lc["moves"] else ("Optimal" if lc["have_current"] else "Unknown")),
             (f"worth +{lc['gain']} pts" if lc["moves"] else
              ("nothing on your bench beats a starter" if lc["have_current"]
               else "couldn't read your lineup")), _tone_lineup),
            ("Slots", (f"{len(adv)} to re-seat" if adv else "By kickoff"),
             ("earliest kickoffs in rigid slots" if not adv
              else f'{adv[0]["name"].split()[-1]} → {adv[0]["to_slot"]}'),
             "mid" if adv else "up"),
            ("Injury risk", f'{avail["n_risky_starters"]}' if avail["n_risky_starters"] else "Clear",
             (f'starters flagged · {avail["cost_if_all_out"]:+.1f} worst case'
              if avail["n_risky_starters"] else "nobody flagged"),
             "mid" if avail["n_risky_starters"] else "up"),
            ("Win prob if fixed", f"{100*wp_fixed:.0f}%" if wp_fixed is not None else "—",
             ("no change to make" if not lc["moves"]
              else f"from {100*wp:.0f}% as the lineup stands"),
             "up" if (wp_fixed or 0) >= .5 else "dn"),
        ]
    # the hero: your chance this week as the number, the score as the line,
    # the four tiles as its grid
    _wp = (wp_live if started else wp)
    _opp_nm = _owner_name(ctx, oid) if opp else ""
    if not opp:
        _num, _line = f"{_me_end:.0f}", "projected — no opponent this week"
    elif phase == "done":
        _num = f"{_me_pts:.1f}"
        _line = f'{"beat" if _me_pts > _opp_pts else "lost to"} <b>{_esc_(_opp_nm)}</b>, {_me_pts:.1f}–{_opp_pts:.1f}'
    elif started:
        _num = f"{100 * (_wp or 0):.0f}%"
        _line = f'to beat <b>{_esc_(_opp_nm)}</b> — {_me_pts:.1f}–{_opp_pts:.1f} now, {_me_end:.0f}–{_opp_end:.0f} projected'
    else:
        _num = f"{100 * (_wp or 0):.0f}%"
        _line = f'to beat <b>{_esc_(_opp_nm)}</b> — projected {_me_end:.0f}–{_opp_end:.0f}'
    st.markdown(C.hero_html(f"WEEK {g['week']}" + (" · LIVE" if started and phase != "done" else "")
                            + (f" · VS {_opp_nm.upper()}" if opp else ""),
                            _num, _line,
                            grid=[(lbl, val, sub) for lbl, val, sub, _tone in tiles[:4]], tone="ink"),
                unsafe_allow_html=True)

    # ---- WHAT TO DO, ranked by what it is worth — and by what day it is ----
    # The list ranks by points at stake. The calendar decides what "at stake"
    # means today: a claim leads on Tuesday and dims on Sunday, an injury the
    # other way round, and a game on the screen beats both.
    byes = ctx.get("byes") or {}
    acts = []
    if started and opp:
        lead_ = _me_pts - _opp_pts
        left_ = ps["pre"] + ps["live"]
        acts.append({"kind": "live", "weight": 100.0, "tone": "live", "icon": "●",
                     "title": (f'{"Up" if lead_ >= 0 else "Down"} {abs(lead_):.1f} · '
                               f'{len(left_)} still to play') if phase != "done"
                     else (f'{"Won" if lead_ > 0 else "Lost"} by {abs(lead_):.1f}'),
                     "detail": (", ".join(reg.meta(p).name for p in left_[:4])
                                + (f' still to go · {100*wp_live:.0f}% now' if wp_live is not None else ""))
                     if phase != "done" else f'{_me_pts:.1f} – {_opp_pts:.1f} final',
                     "num": f"{_me_pts:.1f}", "lab": f"vs {_opp_pts:.1f}"})
    # a man whose game has started is locked in his slot: nothing to tell him
    def _locked(pid):
        return GT.status(WV.game_of(reg, games, pid)) in ("in", "post") if games else False
    for a in [x for x in avail["at_risk"] if not _locked(x.get("pid"))][:3]:
        cost = a.get("cost_if_out")
        if cost is None:
            body, num, lab = "", None, ""
        elif cost > 0.05:
            body = (f'If he sits you lose <b>{cost:.1f}</b> and '
                    f'<b>{a["replacement"] or "nobody"}</b> covers.')
            num, lab = f"-{cost:.1f}", "if he sits"
        else:
            body = (f'<b>You would gain {abs(cost):.1f}</b> by starting '
                    f'{a["replacement"]} regardless.')
            num, lab = f"+{abs(cost):.1f}", "by benching"
        if a.get("replacement_shared"):
            body += (" That same body is covering another questionable starter — "
                     "only one of them can.")
        gm = WV.game_of(reg, games, a.get("pid"))
        if gm and GT.status(gm) == "pre":
            secs = GT.kickoff_ts(gm) - __import__("time").time()
            if secs < 36 * 3600:
                body += f' Decide before <b>{GT.day_label(gm)}</b> ({WV.countdown(secs)}).'
        acts.append({"kind": "injury", "weight": abs(cost or 0),
                     "tone": "bad" if a["severity"] >= 3 else "warn", "icon": "⚕",
                     "title": f'{a["name"]} — {a["status"]}'
                     + (f' <span class="ws-fnt">({a["detail"]})</span>' if a["detail"] else ""),
                     "detail": body, "num": num, "lab": lab})
    for m in [x for x in lc["moves"] if not (_locked(x["out"]) or _locked(x["in"]))][:3]:
        _in, _out = reg.meta(m["in"]), reg.meta(m["out"])
        _v = ECR.verdict((g.get("ecr") or {}).get(str(m["out"])),
                         (g.get("ecr") or {}).get(str(m["in"])))
        _panel_note = {"against": " The expert panel sees it the other way.",
                 "split": " The panel is split — call it a coin flip."}.get(_v, "")
        acts.append({"kind": "lineup", "weight": float(m["gain"]), "tone": "warn", "icon": "↑",
                     "title": f'Start {_in.name}, bench {_out.name}',
                     "detail": f'Worth <b>+{m["gain"]}</b> to your total this week.{_panel_note}',
                     "num": f'+{m["gain"]}', "lab": "points"})
    # Where each starter SITS. Same nine men, but the early kickoff goes in the
    # rigid slot so the flex is still open when Sunday's inactives land.
    for a in adv[:3]:
        acts.append({"kind": "slot", "weight": 0.5, "tone": "info", "icon": "⇄",
                     "title": f'Move {a["name"]} to {a["to_slot"]}, {a["swap_name"]} to {a["from_slot"]}',
                     "detail": (f'{a["name"]} plays <b>{a["day"]}</b>; {a["swap_name"]} not until '
                                f'<b>{a["swap_day"]}</b>. Same starters — but the {a["from_slot"]} '
                                f'stays open for the later game if news breaks.'),
                     "num": a["day"].split()[0], "lab": "kickoff"})
    _claim = _top_claim(ctx, g) if phase in ("waivers", "setup", "done") else None
    if _claim:
        _b = _claim["bid"]
        acts.append({"kind": "waiver", "weight": float(_claim["gain"]), "tone": "go", "icon": "+",
                     "title": f'Claim {_claim["name"]}',
                     "detail": ((f'{_claim["udk"]} · ' if _claim.get("udk") else "")
                                + (f'${_b["low"]}–{_b["high"]} of ${_claim["left"]} · ' if _b else "")
                                + f'<b>+{_claim["gain"]:.1f}</b> to your week'
                                + (f' · {_claim["owned"]:.0f}% rostered, so bid low'
                                   if (_claim.get("owned") or 0) < 25 else
                                   (f' · {_claim["owned"]:.0f}% rostered' if _claim.get("owned") is not None else ""))),
                     "num": f'+{_claim["gain"]:.1f}', "lab": "a week"})
    on_bye = [p for p in g["mine"] if byes.get(reg.meta(p).team) == g["week"]]
    if on_bye:
        acts.append({"kind": "bye", "weight": 99.0, "tone": "bad", "icon": "⊘",
                     "title": f'{len(on_bye)} on bye this week',
                     "detail": ", ".join(reg.meta(p).name for p in on_bye[:4]),
                     "num": str(len(on_bye)), "lab": "out"})
    fut = {}
    for p in g["mine"]:
        b = byes.get(reg.meta(p).team)
        if b and b > g["week"]:
            fut.setdefault(b, []).append(p)
    if fut:
        worst = max(fut.items(), key=lambda kv: len(kv[1]))
        if len(worst[1]) >= 3:
            acts.append({"kind": "bye", "weight": float(len(worst[1])), "tone": "bad", "icon": "▲",
                         "title": f'Week {worst[0]} takes {len(worst[1])} of yours at once',
                         "detail": ", ".join(reg.meta(p).name for p in worst[1][:4])
                         + ". Two waiver claims now cost less than two panic starts then.",
                         "num": str(len(worst[1])), "lab": "on bye"})
    if not lc["moves"] and not adv:
        acts.append({"kind": "ok", "weight": 0.0, "tone": "go", "icon": "✓",
                     "title": "Lineup is the best available, seated by kickoff",
                     "detail": "No bench player beats the man in front of him, and every flex "
                               "holds the latest game.", "num": "0", "lab": "changes"}
                    if lc["have_current"] else
                    {"kind": "ok", "weight": 0.0, "tone": "warn", "icon": "?",
                     "title": "Couldn't read your set lineup",
                     "detail": "So this shows the best available one instead. Everything else on "
                               "this screen is unaffected.", "num": None, "lab": ""})
    acts = WV.rank_actions(acts, phase)

    left, right = st.columns([1.15, 1])
    with left:
        st.markdown(_day_line(g, cur, reg), unsafe_allow_html=True)
        st.markdown('<div class="ws-h">What to do</div>', unsafe_allow_html=True)
        # the one that needs you is a red card; the rest stay quiet
        _hot = next((i for i, a in enumerate(acts[:6]) if a.get("kind") != "ok" and not a.get("dim")), None)
        for _i, a in enumerate(acts[:6]):
            tone = a["tone"] + (" dim" if a.get("dim") else "") + (" hot" if _i == _hot else "")
            st.markdown(C.action_html(tone, a["icon"], a["title"], a["detail"], a.get("num"),
                                      a.get("lab", "")), unsafe_allow_html=True)
        _fa = inseason.faab(ctx["meta"]) or {}
        _budget = int(_fa.get("budget") or 0)
        _left_faab = max(0, _budget - int((_fa.get("by_owner") or {}).get(str(g["me"]), 0) or 0))
        st.markdown(f'<div class="ws2-quiet">Nothing else needs you this week.'
                    + (f' Waivers · <b>${_left_faab}</b> of ${_budget} FAAB left.'
                       if _budget else "")
                    + '</div>', unsafe_allow_html=True)
        if started and opp:
            st.markdown('<div class="ws-h" style="margin-top:12px">Still to play</div>',
                        unsafe_allow_html=True)
            st.markdown(C.still_to_play_html([
                (f'Yours · {len(ps["pre"]) + len(ps["live"])} left',
                 _still_rows(cur, reg, g, me_live, g["proj"])),
                (f'{_owner_name(ctx, oid)} · {len(ops["pre"]) + len(ops["live"])} left',
                 _still_rows(list(zip(g["slots"], ost)), reg, g, opp_live, g["proj"])),
            ]), unsafe_allow_html=True)
        else:
            st.markdown('<div class="ws-h" style="margin-top:12px">Your bench</div>',
                        unsafe_allow_html=True)
            brows = sorted(((float(g["proj"].get(p, 0) or 0), p) for p in lc["bench"]), reverse=True)
            st.markdown(_tbl(["Player", "Plays", "~Proj"],
                             [[f'{reg.meta(p).name} {_pos_pill(reg.meta(p).position)}',
                               GT.day_label(WV.game_of(reg, games, p)), f"{v:.1f}"]
                              for v, p in brows[:8]]), unsafe_allow_html=True)

    with right:
        _plat = "ESPN" if ctx["meta"].platform == "espn" else "Sleeper"
        st.markdown(f'<div class="ws-h">Your lineup on {_plat}</div>' if lc["have_current"]
                    else '<div class="ws-h">Best available lineup</div>',
                    unsafe_allow_html=True)
        _risky = {str(a["pid"]): a for a in avail["at_risk"] if a.get("pid")}
        _moves = {str(m["out"]): m for m in lc["moves"]}
        _reseat = {str(a["pid"]): a["to_slot"] for a in adv}
        _reseat.update({str(a["swap_pid"]): a["swap_to"] for a in adv})
        _pp = me_live.get("players") or {}
        rows = []
        for slot, pid in cur:
            if not pid:
                rows.append((slot, '<span class="ws-dim">(empty)</span>', "nobody set",
                             0.0, "var(--mut2)", True))
                continue
            pm = reg.meta(pid)
            av = W.availability(pm)
            nm = f'{pm.name}'
            if av["status"]:
                nm += f' <span class="ws-q">{av["status"][:4].upper()}</span>'
            if str(pid) in _reseat:
                nm += f' <span class="ws-q" style="color:var(--blue,#6aa6f0)">→ {_reseat[str(pid)]}</span>'
            gm = WV.game_of(reg, games, pid)
            st_ = GT.status(gm)
            when = ("FINAL" if st_ == "post" else "LIVE" if st_ == "in"
                    else "bye" if st_ == "bye" else GT.day_label(gm))
            val = (float(_pp.get(str(pid), 0.0)) if st_ in ("post", "in") and _pp
                   else float(g["proj"].get(str(pid), 0) or 0))
            rows.append((slot, nm, f'{pm.team} · {when}', val,
                         _POSC.get(pm.position, "var(--mut2)"),
                         bool(av["status"]) or str(pid) in _moves or str(pid) in _reseat,
                         getattr(pm, "sleeper_pid", None) or pid))
        st.markdown(C.lineup_bars_html(rows, header="Starting",
                                       proj_label="Pts" if started else "Projected"),
                    unsafe_allow_html=True)
        _note((f"Actual points for men who have played, projections for the rest. "
                    f"Read from {_plat}.") if started else
                   (f"Bars are shares of your biggest starter. Read from {_plat}: your lineup "
                    f"projects **{lc['current_total']:.1f}**, the best available is "
                    f"**{lc['optimal_total']:.1f}**." if lc["have_current"] else
                    "Couldn't read the lineup you have set, so this shows the best available one."))

    # The full slot-by-slot table, with the expert panel, for when he wants the
    # detail rather than the shape. Nothing was removed — it was demoted.
    with st.expander("Slot by slot, with the expert panel"):
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
        _note("Only changes that alter *who plays* are listed — the platform labelling a "
                   "man RB where the optimiser calls him FLEX is not a move.")
        if _ecr_missing(g):
            _note(_ecr_missing(g))






# --------------------------------------------------------------- 1a live feed
_LIVE_CADENCE = {"5s": 5, "10s": 10, "30s": 30}


def _open_moves(lc: dict, reg, games: dict) -> dict:
    """The lineup check with the swaps nobody can make taken out: once either
    man's game has kicked off he is locked in his slot. Sunday afternoon was
    telling him to bench a starter already on the field."""
    if not games or not lc.get("moves"):
        return lc
    def locked(pid):
        return GT.status(WV.game_of(reg, games, pid)) in ("in", "post")
    keep = [m for m in lc["moves"] if not (locked(m["out"]) or locked(m["in"]))]
    if len(keep) == len(lc["moves"]):
        return lc
    return dict(lc, moves=keep, gain=round(sum(float(m.get("gain") or 0) for m in keep), 1),
                locked_moves=len(lc["moves"]) - len(keep))


def _dpc(ps: dict) -> str:
    """"3 done · 3 playing · 3 to come" — "0 of 9 played" beside 50 points read
    as a bug, because a man mid-game has scored but hasn't finished."""
    if not ps:
        return ""
    done = len(ps.get("done") or [])
    bits = [f"{done} done"] if done else []
    if ps.get("live"):
        bits.append(f'{len(ps["live"])} playing')
    if ps.get("pre"):
        bits.append(f'{len(ps["pre"])} to come')
    return " · ".join(bits) or "all done"


def _live_view(ctx, g) -> None:
    """Bind the polling cadence, then hand the screen to one fragment.

    `run_every` is fixed when the fragment object is built, so only the cadence
    can live out here — everything else repaints inside without touching the
    page, which is what keeps the scroll position while the numbers move.
    """
    lk = ctx["league_key"]
    akey = f"lv_{lk}"
    st.session_state.setdefault(f"{akey}_auto", True)
    st.session_state.setdefault(f"{akey}_every", "10s")
    auto = bool(st.session_state.get(f"{akey}_auto"))
    every = _LIVE_CADENCE.get(st.session_state.get(f"{akey}_every"), 10)
    st.fragment(run_every=(every if auto else None))(_live_body)(
        ctx, g, bound_auto=auto, bound_every=every)


def _live_body(ctx, g, *, bound_auto: bool, bound_every: int) -> None:
    import time as _t
    reg = ctx["registry"]
    lk, akey = ctx["league_key"], f"lv_{ctx['league_key']}"
    week, season = g["week"], g["season"]

    # ---- the two moving reads, both uncached -------------------------------
    # The whole point of this screen is that these are NOW. Everything else on
    # it (rosters, slots, projections) comes from the shared 15-minute gather.
    # The scoreboard, the live scores and the stat lines are three hosts that
    # don't depend on each other; read one after another they were ~4s of a
    # cold open, together they're the slowest one. (Stats are only prefetched
    # here — the box score below reads them from nflstats' own cache.)
    from concurrent.futures import ThreadPoolExecutor
    from .. import nflstats as _NS
    _age = bound_every if bound_auto else 0
    with ThreadPoolExecutor(3) as _ex:
        f_games = _ex.submit(GT.load_week, season, week, max_age=_age)
        f_live = _ex.submit(ctx["provider"].get_live_scores, week, fresh=True)
        _ex.submit(_NS.weekly, season, week, max_age=_age)
        try:
            games = f_games.result() or {}
        except Exception:  # noqa: BLE001
            games = g.get("games") or {}
        try:
            live = f_live.result() or {}
            err = ""
        except Exception as e:  # noqa: BLE001
            live, err = {}, type(e).__name__
    now = _t.time()

    oid, opp = _opponent(ctx, g)
    ost = _opp_starters(g, oid) if opp else []
    me_live = live.get(str(g["me"])) or {}
    opp_live = (live.get(str(oid)) or {}) if oid else {}
    mcur = [(s_, p) for s_, p in zip(g["slots"], g.get("starters") or [])]
    ocur = list(zip(g["slots"], ost))

    # ---- what changed since the last tick ----------------------------------
    # Sleeper's own numbers move in bursts — measured at roughly once a minute
    # during play, not per second — so a delta is worth keeping on screen for a
    # while after it lands rather than flashing for one repaint.
    fkey = f"{akey}_feed"
    prev = st.session_state.get(fkey) or {"pts": {}, "events": [], "ts": 0.0}
    pts_now = {}
    for side in (me_live, opp_live):
        for pid, v in (side.get("players") or {}).items():
            pts_now[str(pid)] = float(v or 0)
    events = list(prev.get("events") or [])
    if prev.get("pts"):
        mine_set = {str(p) for _s, p in mcur if p}
        for pid, v in pts_now.items():
            was = prev["pts"].get(pid)
            if was is None or abs(v - was) < 0.05:
                continue
            try:
                nm = reg.meta(pid).name
            except Exception:  # noqa: BLE001
                nm = pid
            events.insert(0, {"pid": pid, "name": nm, "d": v - was, "to": v, "ts": now,
                              "mine": pid in mine_set})
    events = events[:12]
    st.session_state[fkey] = {"pts": pts_now, "events": events, "ts": now}
    recent = {e["pid"]: e for e in events if now - e["ts"] <= 150}

    # ---- controls ----------------------------------------------------------
    with st.container(key="lv_ctl"):
        c = st.columns([1.1, 1.5, 1.0, 3.4])
        auto = c[0].toggle("Auto", key=f"{akey}_auto", help="Poll while this tab is open.")
        c[1].segmented_control("Every", list(_LIVE_CADENCE), key=f"{akey}_every",
                               selection_mode="single", label_visibility="collapsed")
        if c[2].button("Refresh", key=f"{akey}_now", use_container_width=True):
            rerun_here()
        _ago = int(max(0, now - (prev.get("ts") or now)))
        _n_live = sum(1 for v in games.values() if v.get("state") == "in")
        c[3].markdown(
            f'<div class="lv-meta">updated <b>just now</b>'
            + (f' · last poll {_ago}s before' if _ago else "")
            + (f' · <span class="on">{_n_live} game{"s" if _n_live != 1 else ""} live</span>'
               if _n_live else " · no game in progress")
            + (f' · <span class="bad">feed error: {err}</span>' if err else "")
            + "</div>", unsafe_allow_html=True)
    if (auto != bound_auto) or (_LIVE_CADENCE.get(st.session_state.get(f"{akey}_every"), 10)
                                != bound_every):
        # run_every was fixed when this fragment was built, so only a full run
        # can rebind it — otherwise the cadence would never start, or never stop.
        st.rerun()

    # ---- the scoreboard ----------------------------------------------------
    ps = WV.played_state(mcur, reg, games, me_live)
    ops = WV.played_state(ocur, reg, games, opp_live) if opp else None
    me_pts = float(me_live.get("points") or 0)
    opp_pts = float(opp_live.get("points") or 0) if opp else 0.0
    me_end = WV.live_projection(mcur, g["proj"], reg, games, me_live)
    opp_end = WV.live_projection(ocur, g["proj"], reg, games, opp_live) if opp else 0.0
    _, ms_ = W.team_distribution(g["mine"], g["slots"], g["proj"], reg, g["byes"], week,
                                 current=g.get("starters"))
    os_ = ms_
    if opp:
        _, os_ = W.team_distribution(opp, g["slots"], g["proj"], reg, g["byes"], week, current=ost)
    wp = W.win_prob(me_end, ms_ * 0.7, opp_end, os_ * 0.7) if opp else None
    left_me = len(ps["pre"]) + len(ps["live"])
    left_op = (len(ops["pre"]) + len(ops["live"])) if ops else 0
    _kicked = bool(ps["live"] or ps["done"])
    _wk_lab = ("LIVE" if _n_live else "FINAL" if left_me == 0 else
               "BETWEEN GAMES" if _kicked else "BEFORE KICKOFF") + f" · WEEK {week}"
    # the split-flap score: whatever changed since the last poll folds over
    _fk = f"lv_prev_{ctx['league_key']}"
    _flaps = st.session_state.get(_fk) or (f"{me_pts:.1f}", f"{opp_pts:.1f}" if opp else "—")
    st.session_state[_fk] = (f"{me_pts:.1f}", f"{opp_pts:.1f}" if opp else "—")
    st.markdown(C.scoreboard_html(
        flaps=_flaps,
        me_name="You", me_rec=_record(g, g["me"]), me_pts=f"{me_pts:.1f}",
        me_sub=f"{_dpc(ps)} · {me_end:.0f} projected",
        me_photo=_top_photo(reg, g, [p for _s, p in mcur]),
        opp_name=(_owner_name(ctx, oid) if opp else "No opponent"),
        opp_rec=(_record(g, oid) if opp else ""),
        opp_pts=(f"{opp_pts:.1f}" if opp else "—"),
        opp_sub=(f"{_dpc(ops)} · {opp_end:.0f} projected" if opp else "none scheduled"),
        opp_photo=(_top_photo(reg, g, [p for _s, p in ocur]) if opp else None),
        label=_wk_lab, win_pct=(100 * wp) if wp is not None else None,
        tiles=[
            ("Projected final", f"{me_end:.0f} – {opp_end:.0f}" if opp else f"{me_end:.0f}",
             "actual so far plus the rest"),
            ("Margin", f"{me_end - opp_end:+.1f}" if opp else "—", "where it projects to end"),
            ("Still to play", f"{left_me}", f"theirs {left_op}" if opp else ""),
            ("Live now", f'{len(ps["live"])}', "of yours on the field"),
        ]), unsafe_allow_html=True)

    # ---- the games themselves ---------------------------------------------
    mine_teams = []
    for _s, p in mcur + (ocur if opp else []):
        if not p:
            continue
        t = (reg.meta(p).team or "").upper()
        if t and t not in mine_teams:
            mine_teams.append(t)
    seen, cards = set(), []
    for t in mine_teams:
        gm = games.get(t)
        if not gm or gm.get("state") == "pre":
            continue
        key = tuple(sorted([t, gm["opp"]]))
        if key in seen:
            continue
        seen.add(key)
        cards.append((t, gm))
    if cards:
        st.markdown('<div class="ws-h">Games your players are in</div>', unsafe_allow_html=True)
        st.markdown("".join(
            C.live_game_html(
                home=(t if gm.get("home") else gm["opp"]),
                away=(gm["opp"] if gm.get("home") else t),
                home_score=int(gm["score"] if gm.get("home") else gm.get("opp_score") or 0),
                away_score=int(gm.get("opp_score") or 0 if gm.get("home") else gm["score"]),
                label=GT.live_label(gm), live=(gm.get("state") == "in"),
                note=(gm.get("down") or ""), redzone=bool(gm.get("redzone")),
                last_play=(gm.get("last_play") or ""))
            for t, gm in cards), unsafe_allow_html=True)

    # ---- the slots, head to head ------------------------------------------
    # One row per SLOT rather than two stacked lineups: the eye should not have
    # to carry a number across the screen to find out who is winning a seat.
    # The card itself is built in draftkit/livecard.py, because the all-leagues
    # drawer draws the same one at a smaller size.
    from .. import livecard as LC, nflstats as NS
    try:
        stats = NS.weekly(season, week, max_age=(bound_every if bound_auto else 0))
    except Exception:  # noqa: BLE001
        stats = {}

    def _card(pid, side_live):
        pp = (side_live or {}).get("players") or {}
        c = LC.build(pid, registry=reg, games=games,
                     pts=float(pp.get(str(pid), 0) or 0),
                     proj=float(g["proj"].get(str(pid)) or 0), stats=stats)
        # moved on THIS tick only, so the flash plays once and not on every repaint
        ev = recent.get(str(pid))
        if c and ev and ev["ts"] == now:
            c["fresh"] = "up" if ev["d"] > 0 else "dn"
        return c

    st.markdown('<div class="ws-h">Slot by slot</div>', unsafe_allow_html=True)
    pairs = []
    for i, (slot, pid) in enumerate(mcur):
        mine = _card(pid, me_live)
        theirs = _card(ocur[i][1], opp_live) if (opp and i < len(ocur)) else {}
        swing = LC.face_off(mine, theirs)
        pairs.append(C.h2h_pair_html(mine, theirs, slot=slot, swing=swing))
    st.markdown('<div class="h2h">' + "".join(pairs) + "</div>", unsafe_allow_html=True)

    # ---- what just happened ------------------------------------------------
    if events:
        st.markdown('<div class="ws-h">Scoring feed</div>', unsafe_allow_html=True)
        st.markdown("".join(
            C.live_event_html(name=e["name"], delta=e["d"], total=e["to"],
                              ago=int(max(0, now - e["ts"])), mine=e["mine"])
            for e in events[:8]), unsafe_allow_html=True)
    _note("Polls on the cadence above. The clock, score and possession come from ESPN and "
               "move every few seconds; the fantasy points come from Sleeper, whose own feed "
               "updates in bursts — measured at roughly once a minute during play, so a change "
               "stays marked for a couple of minutes after it lands rather than blinking once.")


# --------------------------------------------------------------- 1b lineup
def _panels(ctx, g) -> dict:
    """{"fp": ecr rows, "flock": rows, "ffb": rows} — the three expert panels,
    every one optional."""
    from .. import panels as P
    meta, reg = ctx["meta"], ctx["registry"]
    out = {"fp": g.get("ecr") or {}}
    try:
        out["flock"] = _flock(g["season"], g["week"], reg, _PANEL_VER)
    except Exception:  # noqa: BLE001
        out["flock"] = {}
    try:
        w = getattr(meta, "scoring_weights", None) or {}
        if not w and meta.platform == "sleeper":
            # Sleeper's scoring_settings use the same keys the Ballers' stats
            # are mapped to (pass_yd, rec, ...), so the league's own book scores
            # their projections directly.
            w = (api.get_league(str(meta.league_id)) or {}).get("scoring_settings") or {}
        out["ffb"] = _ffb(g["season"], g["week"], reg, tuple(sorted(w.items())),
                          f'{meta.platform}_{meta.league_id}')
    except Exception:  # noqa: BLE001
        out["ffb"] = {}
    try:
        from .. import vegas as VG
        _win = VG.week_window(g.get("games") or {})
        out["vegas"] = _vegas(g["season"], g["week"], reg, tuple(sorted((w or {}).items())),
                              _win, f'{meta.platform}_{meta.league_id}')
    except Exception:  # noqa: BLE001
        out["vegas"] = {}
    # today's copy of each panel, once — movers are a diff of these
    try:
        P.snapshot_all(g["season"], g["week"], out)
    except Exception:  # noqa: BLE001
        pass
    return out


@st.cache_data(ttl=3600, show_spinner=False, hash_funcs={"builtins.object": id})
def _flock(season: int, week: int, _registry, ver: int = 0):
    from .. import panels as P
    return P.flock_weekly(season, week, _registry)


@st.cache_data(ttl=3600, show_spinner=False, hash_funcs={"builtins.object": id})
def _udk_wv(season: int, week: int, _registry):
    from .. import udk_waivers as UW
    return UW.weekly(season, week, _registry)


@st.cache_data(ttl=3600, show_spinner="Reading the book…", hash_funcs={"builtins.object": id})
def _vegas(season: int, week: int, _registry, weights, window, tag: str):
    from .. import vegas as VG
    return VG.weekly(season, week, _registry, dict(weights), window=window, tag=tag)


@st.cache_data(ttl=3600, show_spinner=False, hash_funcs={"builtins.object": id})
def _ffb(season: int, week: int, _registry, weights, tag: str):
    from .. import panels as P
    return P.ffb_weekly(season, week, _registry, dict(weights), tag=tag)


def _panel_cell(pn: dict, pid) -> str:
    """"FP WR12 · Flock WR9 · Ballers WR14" for one man, only the panels that
    have him."""
    bits = []
    fp = (pn.get("fp") or {}).get(str(pid))
    if fp and fp.get("pos_rank"):
        bits.append(f'<span title="FantasyPros">FP <b>{fp["pos_rank"]}</b></span>')
    fl = (pn.get("flock") or {}).get(str(pid))
    if fl and fl.get("pos_rank") is not None:
        bits.append(f'<span title="Flock · {fl.get("n", 0)} analysts">Flock <b>{fl["pos"]}{float(fl["pos_rank"]):.0f}</b></span>')
    fb = (pn.get("ffb") or {}).get(str(pid))
    if fb and fb.get("pos_rank"):
        bits.append(f'<span title="The Ballers · {", ".join(f"{k} {v}" for k, v in (fb.get("pts_by") or {}).items())}">'
                    f'Ballers <b>{fb["pos"]}{fb["pos_rank"]}</b> · {fb["pts"]}</span>')
    vg = (pn.get("vegas") or {}).get(str(pid))
    if vg and vg.get("pos_rank"):
        from .. import vegas as VG
        bits.append(f'<span title="Bovada · {VG.headline(vg)}">Vegas <b>{vg["pos"]}{vg["pos_rank"]}</b> · {vg["pts"]}</span>')
    return " · ".join(bits) if bits else '<span class="ws-fnt">—</span>'


def _panel_verdicts(pn: dict, out_pid, in_pid) -> list:
    """[(panel, verdict)] for "start IN over OUT" across the three panels."""
    from .. import panels as P
    v = []
    fp = pn.get("fp") or {}
    r = ECR.verdict(fp.get(str(out_pid)), fp.get(str(in_pid)))
    if r:
        v.append(("FP", r))
    for key, label in (("flock", "Flock"), ("ffb", "Ballers"), ("vegas", "Vegas")):
        rows = pn.get(key) or {}
        r = P.verdict(rows.get(str(out_pid)), rows.get(str(in_pid)))
        if r:
            v.append((label, r))
    return v


def _verdict_chips(vs: list) -> str:
    def _n(v):
        return "for" if v in ("for", "agree", "agrees") else "against" if v in ("against", "disagree") else "split"
    return " ".join(_chip(f'{p} {"agrees" if _n(v) == "for" else "disagrees" if _n(v) == "against" else "split"}',
                          {"for": "ok", "against": "bad", "split": "warn"}[_n(v)]) for p, v in vs)


def _source_scores(pn: dict, g: dict, src: str):
    """(score {pid: higher-is-better}, label(pid) -> str) for one ranking source.

    Projections score in points. FantasyPros ranks RB/WR/TE together on its FLEX
    list and QB/K/DST on their own, so a rank becomes `1000 - rank` — only ever
    compared within a slot's eligible positions, where the scales agree. Flock's
    weekly OVERALL rank does the same job across RB/WR/TE/QB. The Ballers project
    points, so those are used as they are. K and D/ST fall back to projections on
    every panel, because no panel but FantasyPros ranks them.
    """
    proj = g["proj"] or {}
    if src == "Projections":
        return proj, (lambda pid: f'{float(proj.get(str(pid), 0) or 0):.1f}')
    reg = None
    score, labels = {}, {}
    if src in ("The Ballers", "Vegas"):
        rows = pn.get("ffb" if src == "The Ballers" else "vegas") or {}
        for pid, r in rows.items():
            if r.get("pts") is not None:
                score[pid] = float(r["pts"])
                labels[pid] = f'{r["pts"]:.1f}'
    else:
        key = "fp" if src == "FantasyPros" else "flock"
        rows = pn.get(key) or {}
        for pid, r in rows.items():
            rk = r.get("ecr") if key == "fp" else (r.get("rank") or r.get("pos_rank"))
            if rk is None:
                continue
            score[pid] = 1000.0 - float(rk)
            labels[pid] = (f'{r.get("pos_rank") or ""}' if key == "fp"
                           else f'{r.get("pos") or ""}{float(r.get("pos_rank") or 0):.0f}')
    # K / D/ST: projections, scaled so they never outrank a ranked skill player
    # (they never compete for the same slot anyway).
    for pid, v in proj.items():
        if pid not in score:
            score[pid] = 0.0
    return score, (lambda pid: labels.get(str(pid)) or f'{float(proj.get(str(pid), 0) or 0):.1f}')


def _start_sit(ctx, g, lc) -> None:
    """Two players at one position, side by side: floor/median/ceiling, the
    matchup, the kickoff, and what starting each does to the win probability.

    The default pair is the closest call on the roster — a starter and the best
    bench man at his position — because that's the one he'd open this for."""
    reg, lk = ctx["registry"], ctx["league_key"]
    games, proj = g.get("games") or {}, g["proj"]
    starters = [str(p) for p in (g.get("starters") or []) if p and str(p) != "0"]
    roster = [str(p) for p in g["mine"]]
    pos = lambda p: (reg.meta(p).position or "").upper()
    pj = lambda p: float(proj.get(str(p), 0) or 0)
    if not starters:
        return
    # the closest call: smallest gap between a starter and a bench man at his position
    best = None
    for s_ in starters:
        for b in roster:
            if b in starters or pos(b) != pos(s_) or pos(b) in ("K", "DEF", "DST"):
                continue
            gap = abs(pj(s_) - pj(b))
            if best is None or gap < best[0]:
                best = (gap, s_, b)
    cands = [p for p in roster if pos(p) not in ("K", "DEF", "DST")]
    if len(cands) < 2:
        return
    lab = lambda p: f"{reg.meta(p).name} · {pos(p)} · {pj(p):.1f}"
    c1, c2 = st.columns(2)
    ka, kb = f"ss_a_{lk}", f"ss_b_{lk}"
    a_def = best[1] if best else cands[0]
    a = c1.selectbox("Player", cands, format_func=lab, key=ka,
                     index=cands.index(a_def) if a_def in cands else 0, on_change=_keep_open(f"ss_{lk}"))
    same = [p for p in cands if p != a and pos(p) == pos(a)]
    if not same:
        _note(f"Nobody else on your roster plays {pos(a)}.")
        return
    b_def = best[2] if (best and best[1] == a and best[2] in same) else max(same, key=pj)
    b = c2.selectbox(f"vs another {pos(a)}", same, format_func=lab, key=f"{kb}_{pos(a)}",
                     index=same.index(b_def), on_change=_keep_open(f"ss_{lk}"))

    dvp = ctx.get("dvp") or {}

    def card(p):
        pm = reg.meta(p)
        m = pj(p)
        sd = W.player_sd(pm.position, m)
        gm = games.get((pm.team or "").upper()) or {}
        opp = gm.get("opp") or ""
        rank = (dvp.get(pm.position) or dvp.get((pm.position or "").upper()) or {}).get(opp)
        return {"pid": p, "name": pm.name, "team": pm.team or "", "pos": pm.position,
                "face": getattr(pm, "sleeper_pid", None) or p, "mean": m,
                "floor": max(0.0, m - 1.28 * sd), "ceil": m + 1.28 * sd,
                "opp": opp, "home": gm.get("home"), "when": GT.day_label(gm) if gm else "",
                "kick": GT.kickoff_ts(gm) if gm else 0.0, "dvp": rank,
                "starting": p in starters}
    A, B = card(a), card(b)

    # win probability with each in the lineup: swap whichever is starting for
    # the other; if neither starts, each takes the weakest starter's seat at
    # that position; if both start, there's no decision between them
    wp = None
    oid, opp_pids = _opponent(ctx, g)
    if oid and opp_pids and not (A["starting"] and B["starting"]):
        om, osd = W.team_distribution(opp_pids, g["slots"], proj, reg, g["byes"], g["week"],
                                      current=_opp_starters(g, oid))
        if A["starting"] or B["starting"]:
            seat = a if A["starting"] else b
        else:
            same_st = [s_ for s_ in starters if pos(s_) == pos(a)]
            seat = min(same_st, key=pj) if same_st else None
        if seat:
            def total(with_p):
                ids = [with_p if s_ == seat else s_ for s_ in starters]
                mean = sum(pj(x) for x in ids)
                var = sum(W.player_sd(pos(x), pj(x)) ** 2 for x in ids)
                return mean, var ** 0.5
            pa, pb = W.win_prob(*total(a), om, osd), W.win_prob(*total(b), om, osd)
            wp = (round(100 * pa), round(100 * pb))
    st.markdown(C.start_sit_html(A, B, wp, n_def=max([len(v) for v in dvp.values()] or [32]),
                                 dvp_label=ctx.get("dvp_label") or "last season"),
                unsafe_allow_html=True)


def _lineup(ctx, g) -> None:
    """What is on the platform beside what to set, slot by slot, seated by
    kickoff, with the taps to make in the order the platform will take them."""
    reg = ctx["registry"]
    games = g.get("games") or {}
    lc = _open_moves(W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"],
                                    current=g.get("starters")), reg, games)
    if not lc["have_current"]:
        st.warning("Couldn't read the lineup you have set, so there is nothing to compare "
                   "against. The Command Center shows the best available lineup.")
        return
    pn = _panels(ctx, g)
    # ---- which panel decides ---------------------------------------------
    # Projections are the default; the others rank instead of scoring, so the
    # optimiser is fed "rank turned into a score" and the POINTS shown are still
    # the projection for whatever set that panel picks — the two panels are
    # then comparable on one number.
    _srcs = ["Projections", "FantasyPros", "Flock", "The Ballers", "Vegas"]
    _skey = f"lineup_src_{ctx['league_key']}"
    with st.container(key="lineup_src"):
        st.session_state.setdefault(_skey, _srcs[0])
        src = st.segmented_control("Rank by", _srcs, key=_skey, selection_mode="single",
                                   label_visibility="collapsed") or _srcs[0]
    score, score_label = _source_scores(pn, g, src)
    if src != "Projections":
        lc_src = W.lineup_check(g["mine"], g["slots"], score, reg, g["byes"], g["week"],
                                current=g.get("starters"))
        # points, not rank units, for the totals and the gains
        _p = g["proj"]
        _opt_set = [str(p) for _s, p in lc_src["optimal"] if p]
        lc_src["optimal_total"] = round(sum(float(_p.get(x, 0) or 0) for x in _opt_set), 1)
        lc_src["current_total"] = round(sum(float(_p.get(str(x), 0) or 0)
                                            for _s, x in lc_src["current"] if x), 1)
        for m in lc_src["moves"]:
            m["gain"] = round(float(_p.get(m["in"], 0) or 0) - float(_p.get(m["out"], 0) or 0), 1)
        lc_src["gain"] = round(lc_src["optimal_total"] - lc_src["current_total"], 1)
        missing = [p for p in g["mine"] if str(p) not in score and reg.meta(p).position in ("QB", "RB", "WR", "TE")]
        if missing:
            _note(f"{src} doesn't rank " + ", ".join(reg.meta(p).name for p in missing[:5])
                       + (" and others" if len(missing) > 5 else "")
                       + " — they sort behind everyone it does.")
        lc = _open_moves(lc_src, reg, games)
    cur = lc["current"]
    slots = [s for s, _p in cur]
    # The set to start: the optimiser's. Then SEAT it by kickoff.
    chosen = {i: str(p) for i, (_s, p) in enumerate(lc["optimal"]) if p}
    # A slot the optimiser leaves EMPTY while the platform has a man in it
    # (a defense with no projection, say) keeps that man: "bench him for
    # nobody" is not advice. Sleeper-projection gaps are at K and D/ST.
    _used = set(chosen.values())
    for i, (_s, p) in enumerate(cur):
        if i not in chosen and p and str(p) not in _used:
            chosen[i] = str(p)
            _used.add(str(p))
    opt_pids = list(chosen.values())
    _cur_idx = {str(p): i for i, (_s, p) in enumerate(cur) if p}
    seated = (LU.place_by_kickoff(chosen, slots, reg, WV.kickoff_of(reg, games), current=_cur_idx)
              if games else chosen)
    # men the current lineup benches / starts
    cur_set = {p for _s, p in cur if p}
    opt_set = set(opt_pids)
    ins, outs = opt_set - cur_set, cur_set - opt_set
    _pos_of = {}
    for i, (s, p) in enumerate(cur):
        if p:
            _pos_of[p] = s
    # the slot each man ends up in
    end_slot = {pid: slots[i] for i, pid in seated.items()}
    # a re-seat: the same man, moved to a different slot so a later game holds the flex
    n_reseat = 0
    for i, (slot, pid) in enumerate(cur):
        new = seated.get(i)
        if new and new not in ins and new != pid and _pos_of.get(new) != slot:
            n_reseat += 1

    n_moves, n_seat = len(lc["moves"]), n_reseat
    _plat = "ESPN" if ctx["meta"].platform == "espn" else "Sleeper"
    # the lead: what to do, as a sentence; the calendar rides in the kicker
    _day = re.sub(r"<[^>]+>", "", _day_line(g, cur, reg)).strip()
    _gain = float(lc["optimal_total"]) - float(lc["current_total"])
    # the hero: the projected total, the moves as the sentence, the best
    # starter in duotone
    _top = max((p for p in opt_pids if p), key=lambda p: float(g["proj"].get(str(p), 0) or 0), default=None)
    _photo = getattr(reg.meta(_top), "sleeper_pid", None) or _top if _top else None
    if n_moves or n_seat:
        _t = " · ".join(x for x in (f'{n_moves} move{"s" if n_moves != 1 else ""}' if n_moves else "",
                                     f'{n_seat} re-seat{"s" if n_seat != 1 else ""}' if n_seat else "") if x)
        _s = (f'projected with <b>{_t}</b>' + (f' — worth {_gain:+.1f}' if n_moves else " — same starters, better seats")
              + f'. The taps are below, in the order {_plat} takes them.')
    else:
        _s = "projected — your lineup is set"
    st.markdown(C.hero_html(f"LINEUP · WEEK {g['week']} · {_day.split(' · ', 1)[-1]}",
                            f'{lc["optimal_total"]:.1f}', _s, photo=_photo,
                            tone="red" if (n_moves or n_seat) else "ink"), unsafe_allow_html=True)
    # ---- the lineup: ONE list, the change inline ---------------------------
    # Two nine-man columns ("now" and "set this") were the same nine most
    # weeks. One list says it once; a row that changes turns red and names who
    # comes in and who sits.
    _gain_of = {m["in"]: (m["out"], float(m["gain"])) for m in lc["moves"]}
    _photo_of = lambda q: getattr(reg.meta(q), "sleeper_pid", None) or q  # noqa: E731
    one = []
    for i, (slot, pid) in enumerate(cur):
        new = seated.get(i)
        if not new:
            one.append({"slot": slot, "name": '<span class="ws-dim">(empty)</span>', "sub": "nobody set",
                        "pts": 0.0, "pid": None})
            continue
        pm = reg.meta(new)
        gm = WV.game_of(reg, games, new)
        opp_ = (("vs " if gm.get("home") else "@ ") + gm["opp"]) if gm else "bye"
        av = W.availability(pm)
        sub = f'{pm.team} · {opp_} · {GT.day_label(gm)}'
        # kicked off = locked in this slot: say so, so the lack of advice reads
        if gm and GT.status(gm) in ("in", "post"):
            sub = f'<b class="xl-lk">{"LIVE" if GT.status(gm) == "in" else "DONE"} · LOCKED</b> ' + sub
        if av["status"]:
            sub += f' · <b class="xl-q">{av["status"][:4].upper()}</b>'
        state, gain = "", ""
        if new in ins:
            state = "in"
            out_pid, g_ = _gain_of.get(new, (None, None))
            if out_pid:
                sub += f' · for {reg.meta(out_pid).name.split()[-1]}, who sits'
            if g_ is not None:
                gain = f"{g_:+.1f}"
        elif new != pid and _pos_of.get(new) != slot:
            state = "mv"
            sub += f' · from {_pos_of.get(new, "bench")}, so the later game holds the {slot}'
        one.append({"slot": slot, "name": pm.name, "sub": sub, "pid": _photo_of(new),
                    "pts": float(g["proj"].get(str(new), 0) or 0), "pts_label": score_label(new),
                    "state": state, "gain": gain})
    if n_moves or n_seat:
        _head = " · ".join(x for x in (f'{n_moves} MOVE{"S" if n_moves != 1 else ""} · {_gain:+.1f}' if n_moves else "",
                                       f'{n_seat} RE-SEAT{"S" if n_seat != 1 else ""}' if n_seat else "") if x)
    else:
        _head = "SET"
    _sub_head = ("the taps are below, in the order " + _plat + " takes them" if (n_moves or n_seat)
                 else "nothing to change · every flex holds the latest game")
    _bench = sorted((float(g["proj"].get(str(q), 0) or 0), str(q)) for q in g["mine"]
                    if str(q) not in set(map(str, seated.values())))
    def _bsub(q):
        _st = W.availability(reg.meta(q))["status"]
        return (f'{reg.meta(q).team} · {GT.day_label(WV.game_of(reg, games, q))}'
                + (f' · <b class="xl-q">{_esc_(_st[:4].upper())}</b>' if _st else ""))
    _bench = [(reg.meta(q).name, _bsub(q), v, _photo_of(q)) for v, q in sorted(_bench, reverse=True)[:7]]
    c_l, c_b = st.columns([1.55, 1])
    with c_l:
        st.markdown(C.lineup_one_html(one, head=_head, hot=bool(n_moves or n_seat))
                    .replace('</span></div>', f'</span><span class="xl-hs">{_sub_head}</span></div>', 1)
                    + ("" if src == "Projections" else
                       f'<div class="xl-src">sorted by {_esc_(src)} · points are our projections</div>'),
                    unsafe_allow_html=True)
    with c_b:
        st.markdown('<div class="ws-h">Bench</div>' + C.bench_list_html(_bench), unsafe_allow_html=True)

    # ---- the taps, in order -------------------------------------------------
    pairs = []
    for i, (slot, pid) in enumerate(cur):
        new = seated.get(i)
        if (new and pid and new != pid and new not in ins and pid not in outs
                and _pos_of.get(new) != slot):
            pairs.append((pid, slot, new))
    steps = []
    for m in lc["moves"]:
        steps.append(f'Bench <b>{reg.meta(m["out"]).name}</b>, start <b>{reg.meta(m["in"]).name}</b> '
                     f'<em>· lineup change · {float(m["gain"]):+.1f}</em>')
    seen = set()
    for pid, slot, new in pairs:
        if new in seen or pid in seen:
            continue
        seen.update({pid, new})
        steps.append(f'Swap <b>{reg.meta(new).name}</b> ({_pos_of.get(new, "?")}) with '
                     f'<b>{reg.meta(pid).name}</b> ({slot}) <em>· tap one, then the other</em>')
    if steps:
        st.markdown(C.steps_html(f"On {_plat}, in this order", steps), unsafe_allow_html=True)
        _note(f"{_plat} swaps two players when you tap them in turn, so every re-seat is written "
                   "as a pair. Ties in kickoff are not moves. Seating never changes the points, "
                   "only how much of the week stays open.")

    # ---- the rest, folded ------------------------------------------------------
    with st.container(key="drawers"):
        with _drawer("Start or sit", "compare any two at a position", key=f"ss_{ctx['league_key']}"):
            _start_sit(ctx, g, lc)
        with _drawer("Why each move", (f'{n_moves} start/bench · {n_seat} re-seat' if (n_moves or n_seat) else 'nothing to change')):
            # ---- the moves, and what each panel thinks -----------------------------
            c1, c2 = st.columns(2)
            with c1:
                st.markdown('<div class="ws-h">Start / bench</div>', unsafe_allow_html=True)
                if not lc["moves"]:
                    st.markdown(C.action_html("go", "✓", "Nobody on the bench beats a starter",
                                              "The nine you have set are the nine to play.", "0", "moves"),
                                unsafe_allow_html=True)
                for m in lc["moves"]:
                    _in, _out = reg.meta(m["in"]), reg.meta(m["out"])
                    vs = _panel_verdicts(pn, m["out"], m["in"])
                    st.markdown(C.action_html("go" if float(m["gain"]) >= 0 else "warn", "↑",
                                              f'Start {_in.name}, bench {_out.name}',
                                              f'Worth <b>{float(m["gain"]):+.1f}</b> this week by our projections. '
                                              + (_verdict_chips(vs) if vs else "No panel ranks both."),
                                              f'{float(m["gain"]):+.1f}', "points"), unsafe_allow_html=True)
            with c2:
                st.markdown('<div class="ws-h">Seat by kickoff</div>', unsafe_allow_html=True)
                pairs = []
                for i, (slot, pid) in enumerate(cur):
                    new = seated.get(i)
                    if (new and pid and new != pid and new not in ins and pid not in outs
                            and _pos_of.get(new) != slot):
                        pairs.append((pid, slot, new))
                if not pairs:
                    st.markdown(C.action_html("go", "✓", "Every flex holds the latest game",
                                              "Earliest kickoffs are already in the rigid slots.", "0", "re-seats"),
                                unsafe_allow_html=True)
                seen = set()
                for pid, slot, new in pairs:
                    if new in seen or pid in seen:
                        continue
                    seen.update({pid, new})
                    g1, g2 = WV.game_of(reg, games, new), WV.game_of(reg, games, pid)
                    st.markdown(C.action_html(
                        "info", "⇄", f'{reg.meta(new).name} to {slot}, {reg.meta(pid).name} to {end_slot.get(pid, "FLEX")}',
                        f'{reg.meta(new).name.split()[-1]} plays <b>{GT.day_label(g1)}</b>; '
                        f'{reg.meta(pid).name.split()[-1]} not until <b>{GT.day_label(g2)}</b>. Same starters — '
                        f'the {end_slot.get(pid, "FLEX")} stays open for the later game.',
                        GT.day_label(g1).split()[0], "first kickoff"), unsafe_allow_html=True)


        with _drawer("What the panels say", "FantasyPros · Flock · The Ballers on your starters"):
            # ---- every starter against the three panels -----------------------------
            rows = []
            for i, (slot, pid) in enumerate(cur):
                new = seated.get(i)
                if not new:
                    continue
                pm = reg.meta(new)
                rows.append([f'<b class="ws-sl">{slot}</b>', f'<b>{pm.name}</b> {_pos_pill(pm.position)}',
                             f'{float(g["proj"].get(str(new), 0) or 0):.1f}', _panel_cell(pn, new)])
            st.markdown(_tbl(["", "Set this", "~Proj", "FantasyPros · Flock · The Ballers"], rows,
                             widths=["44px", "30%", "60px", "auto"], wide=True), unsafe_allow_html=True)
            _n = {k: len(v) for k, v in pn.items()}
            _note(f"Positional rank on each panel. FantasyPros {_n.get('fp', 0)} players · "
                       f"Flock {_n.get('flock', 0)} ({', '.join(sorted({a for r in (pn.get('flock') or {}).values() for a in (r.get('ranks') or {})}))}) · "
                       f"The Ballers {_n.get('ffb', 0)} (Andy, Mike, Jason — their projections scored under this "
                       f"league's settings). Neither Flock nor the Ballers rank K or D/ST.")




# ------------------------------------------------------------- 1c rankings
_RK_SRC = ["Consensus", "FantasyPros", "Flock", "The Ballers", "Vegas"]
_RK_WHO = ["Mine + FA", "All", "Mine", "Free agents"]
_RK_POS = ["ALL", "QB", "RB", "WR", "TE", "FLEX", "K", "DST", "▲▼ Movers", "＋ Waivers"]
_RK_SINCE = [("yesterday", "1d"), ("week", "Tue"), ("last", "wk")]
# Tier cuts by how deep the position is: a WR22 is a WR2, a TE22 is a bench man.
_TIERS_DEEP = ((5, "S", "elite"), (12, "A", "start without thinking"),
               (24, "B", "solid start · flex"), (36, "C", "flex call · bench"),
               (10 ** 6, "D", "deep"))
_TIERS_POS = ((3, "S", "elite"), (8, "A", "start without thinking"),
              (14, "B", "streamable"), (20, "C", "bench"),
              (10 ** 6, "D", "deep"))
_TIERS_ALL = ((6, "S", "every panel agrees"), (18, "A", "start without thinking"),
              (40, "B", "flex calls · the panels split"), (80, "C", "bench · streamers"),
              (10 ** 6, "D", "deep"))


def _pos_rank_num(r: Optional[dict], key: str):
    """A positional rank as a number from any panel row, or None."""
    if not r:
        return None
    if key == "fp":
        pr = str(r.get("pos_rank") or "")
        digits = "".join(ch for ch in pr if ch.isdigit())
        return float(digits) if digits else None
    v = r.get("pos_rank")
    return float(v) if v is not None else None


def _overall_num(r: Optional[dict], key: str):
    if not r:
        return None
    if key == "fp":
        return float(r["ecr"]) if r.get("ecr") is not None and r.get("scale") == "flex" else None
    if key == "flock":
        return float(r["rank"]) if r.get("rank") is not None else None
    return None


def _third(v, pool: list) -> str:
    """g / y / r by which third of `pool` (sorted ascending = better) `v` sits in."""
    if v is None or not pool:
        return "dim"
    n = len(pool)
    i = sum(1 for x in pool if x < v)
    return "g" if i < n / 3 else ("y" if i < 2 * n / 3 else "r")


@st.cache_data(show_spinner=False, max_entries=24, hash_funcs={"builtins.object": id})
def _rk_rows_cached(league_key: str, week: int, bucket: int, pos: str, _reg, _g, _pn, _owner_of,
                    ver: int = 0):
    reg, g, owner_of = _reg, _g, _owner_of
    fp, fl, fb = _pn.get("fp") or {}, _pn.get("flock") or {}, _pn.get("ffb") or {}
    vg = _pn.get("vegas") or {}
    pids = set(fp) | set(fl) | set(fb) | set(vg) | {str(p) for p in g["mine"]}
    want = {"ALL": None, "FLEX": {"RB", "WR", "TE"}}.get(pos, {pos, "DEF"} if pos == "DST" else {pos})
    if pos == "WAIVERS":
        # the board becomes the Ballers' waiver list: their targets, every position
        pids, want = set(_pn.get("wv") or {}), None
    rows = []
    for pid in pids:
        try:
            pm = reg.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        p_pos = (pm.position or "").upper()
        p_pos = "DST" if p_pos == "DEF" else p_pos
        if want and p_pos not in want:
            continue
        if p_pos not in ("QB", "RB", "WR", "TE", "K", "DST"):
            continue
        a, b, cc, v = fp.get(pid), fl.get(pid), fb.get(pid), vg.get(pid)
        pr = {"fp": _pos_rank_num(a, "fp"), "flock": _pos_rank_num(b, "flock"),
              "ffb": _pos_rank_num(cc, "ffb"), "vegas": _pos_rank_num(v, "vegas")}
        ov = {"fp": _overall_num(a, "fp"), "flock": _overall_num(b, "flock"), "ffb": None,
              "vegas": None}
        from .. import vegas as VG
        rows.append({"pid": pid, "name": pm.name, "pos": p_pos, "team": pm.team or "",
                     "pr": pr, "ov": ov, "pts": (cc or {}).get("pts"),
                     "vpts": (v or {}).get("pts"), "vline": VG.headline(v) if v else "",
                     "proj": float(g["proj"].get(pid, 0) or 0),
                     "owner": owner_of.get(pid), "tier_flock": (b or {}).get("tier"),
                     "inj": W.availability(pm)})
    return rows


@st.cache_data(ttl=1800, show_spinner="Pulling the rest-of-season boards…")
def _ros_board_cached(season: int, week: int, scoring: str, weights_key: str, _reg, _weights):
    from .. import ros as R
    return R.board(season, week, scoring, _reg, _weights)


_ROS_POS = ["FLEX", "QB", "RB", "WR", "TE", "ALL"]
_ROS_SORT = {"Consensus": "cons", "FantasyPros": "fp", "Flock": "flock", "The Ballers": "ffb",
             "Sleeper proj": "sleeper"}


def _rankings_ros(ctx, g) -> None:
    """Rest-of-season rankings: FantasyPros' ROS consensus, Flock's in-season
    redraft board, the Ballers' ROS ranks and Sleeper's projections for every
    remaining week under this league's scoring — side by side, with their
    consensus. The board for trades and keepers; the weekly one is for lineups."""
    import copy
    from .. import ros as R, scoring as _SC
    reg, lk, meta = ctx["registry"], ctx["league_key"], ctx["meta"]
    week = int(g["week"])
    weights = getattr(meta, "scoring_weights", None)
    try:
        b = _ros_board_cached(int(g["season"]), week, meta.scoring,
                              str(sorted((weights or {}).items())), reg, weights)
    except Exception as e:  # noqa: BLE001
        _note(f"Couldn't load the rest-of-season boards: {type(e).__name__}.")
        return
    with st.container(key="rk_ctl"):
        c = st.columns([1.6, 2.2, 2.2, 0.9])
        who = c[0].segmented_control("Who", _RK_WHO, key=f"ros_who_{lk}", selection_mode="single",
                                     default=_RK_WHO[1], label_visibility="collapsed") or _RK_WHO[1]
        pos = c[1].segmented_control("Pos", _ROS_POS, key=f"ros_pos_{lk}", selection_mode="single",
                                     default="FLEX", label_visibility="collapsed") or "FLEX"
        sort_lab = c[2].segmented_control("Sort", list(_ROS_SORT), key=f"ros_sort_{lk}",
                                          selection_mode="single", default="Consensus",
                                          label_visibility="collapsed") or "Consensus"
        limit = c[3].selectbox("Rows", [40, 80, 150, 400], key=f"ros_n_{lk}",
                               label_visibility="collapsed", format_func=lambda n: f"top {n}")
    rows = R.rank(copy.deepcopy(b), pos)
    sk = _ROS_SORT[sort_lab]
    if sk != "cons" and pos != "ALL":
        rows = [r for r in rows if r["r"].get(sk) is not None]
        rows.sort(key=lambda r: r["r"][sk])
    owner_of = {str(p): str(oid) for oid, r in g["rosters"].items() for p in (r.get("players") or [])}
    me = str(g["me"])
    _top10 = rows[:10]
    _mine10 = [r for r in _top10 if owner_of.get(r["pid"]) == me]
    st.markdown(C.hero_html(f"REST OF SEASON · {pos}", str(len(_mine10)),
                            "of the top ten are yours" + (f' — <b>{_esc_(reg.meta(_mine10[0]["pid"]).name)}</b> leads them'
                                                          if _mine10 else ""),
                            photo=(_mine10[0]["pid"] if _mine10 else (_top10[0]["pid"] if _top10 else None)), tone="ink"),
                unsafe_allow_html=True)
    if who == "Mine":
        rows = [r for r in rows if owner_of.get(r["pid"]) == me]
    elif who == "Free agents":
        rows = [r for r in rows if r["pid"] not in owner_of]
    elif who == "Mine + FA":
        rows = [r for r in rows if owner_of.get(r["pid"]) in (me, None)]
    total = len(rows)
    rows = rows[:limit]
    srcs = [k for k in R.SOURCES if any(k in r["src"] for r in b.values())]
    _tiles([
        ("weeks", f"{week}–{R.LAST_WEEK}", "remaining", "var(--ink)"),
        ("sources", f"{len(srcs)}", " · ".join(R.LABEL[k] for k in srcs), "var(--ink)"),
        ("scored", "league" if weights else meta.scoring.upper(),
         _SC.describe(weights) if weights else "", "var(--ink)"),
        ("shown", f"{min(limit, total)}", f"of {total} · {pos} · {who}", "var(--mut2)"),
    ])
    if not rows:
        _note("Nobody fits that filter.")
        return
    pool = {k: sorted(r["r"][k] for r in rows if r["r"].get(k) is not None) for k in (*R.SOURCES, )}
    pool["cons"] = sorted(r["cons"] for r in rows if r["cons"] is not None)
    cols = "330fr 70fr 70fr 78fr 78fr 84fr 78fr 92fr 230fr"
    out = [f'<div class="rk" style="--cols:{cols}"><div class="rk-hd">'
           + "".join(f'<span class="{"on" if (lab == sort_lab or (lab == "Sleeper" and sort_lab == "Sleeper proj") or (lab == "Ballers" and sort_lab == "The Ballers") or (lab == "FP" and sort_lab == "FantasyPros")) else ""}{" lbl" if lab == "Owner" else ""}">{lab}</span>'
                     for lab in ("", "FP", "Flock", "Ballers", "Sleeper", "Consensus", "Spread", "ROS pts", "Owner"))
           + '</div>']
    tiers = _TIERS_ALL if pos in ("FLEX", "ALL") else _TIERS_DEEP if pos in ("RB", "WR") else _TIERS_POS
    band = -1
    for idx, r in enumerate(rows, 1):
        tr = float(idx) if (pos == "ALL" or sk != "cons") else (r["cons"] or 10 ** 6)
        ti = next(i for i, (cut, _l, _w) in enumerate(tiers) if tr <= cut)
        if ti != band:
            band = ti
            _cut, lab, why = tiers[ti]
            out.append(f'<div class="rk-tier"><div class="band t{lab}"><em>{lab}</em>Tier {ti + 1}'
                       f'<small>{_esc_(why)}</small></div><i></i></div>')
        pm = reg.meta(r["pid"])

        def cell(k, label, sub=""):
            v = r["r"].get(k)
            if v is None:
                return f'<div data-k="{label}" class="c dim">—</div>'
            return (f'<div data-k="{label}" class="c {_third(v, pool.get(k, []))}{" sort" if k == sk else ""}">'
                    f'{v:.0f}{sub}</div>')
        fb = r["src"].get("ffb") or {}
        fb_sub = ("<small>" + " · ".join(f"{a[:1]}{int(v)}" for a, v in (fb.get("by") or {}).items()) + "</small>"
                  if fb.get("by") and pos not in ("FLEX",) else "")
        cons = (f'<div data-k="Consensus" class="c {_third(r["cons"], pool["cons"])}{" sort" if sk == "cons" else ""}">'
                f'{r["cons"]:.1f}</div>' if r["cons"] is not None else '<div data-k="Consensus" class="c dim">—</div>')
        if r["spread"] is not None:
            vals = list(r["r"].values())
            wide = r["spread"] > max(4.0, 0.35 * (r["cons"] or 0))
            sp = f'<div data-k="Spread" class="c {"r" if wide else "g"}">{min(vals):.0f}–{max(vals):.0f}</div>'
        else:
            sp = '<div data-k="Spread" class="c dim">—</div>'
        pts = (f'<div data-k="ROS pts" class="c">{r["pts"]:.0f}<small>{r["pts"] / max(1, r["games"] or 1):.1f}/g · {r["games"]}g</small></div>'
               if r.get("pts") else '<div data-k="ROS pts" class="c dim">—</div>')
        o = owner_of.get(r["pid"])
        if o == me:
            own, cls, tag = '<b class="me">You</b>', "me", '<span class="tag me">yours</span>'
        elif o:
            own, cls, tag = f'<b>{_esc_(_owner_name(ctx, o))}</b>', "", ""
        else:
            own, cls, tag = '<b class="fa">Free agent</b>', "fa", '<span class="tag fa">free agent</span>'
        out.append(
            f'<div class="rk-row {cls}"><div class="pl">{_T.img_tag(r["pid"], "")}'
            f'<b>{idx}. {_esc_(pm.name)}<small>{_esc_(pm.team or "")} · {r["pos"]}</small></b>{tag}</div>'
            + cell("fp", "FP") + cell("flock", "Flock") + cell("ffb", "Ballers", fb_sub)
            + cell("sleeper", "Sleeper") + cons + sp + pts + f'<div class="own">{own}</div></div>')
    out.append("</div>")
    st.markdown("".join(out), unsafe_allow_html=True)
    _note(f"**Rest of season**, weeks {week}–{R.LAST_WEEK}. **FP** is FantasyPros' ROS expert consensus; "
          "**Flock** is its eight analysts' in-season redraft board; **Ballers** is Andy, Jason and Mike's "
          "ROS ranks (A·J·M underneath at a single position); **Sleeper** ranks Sleeper's projections for "
          "every remaining week. **Scoring:** Sleeper's points and the Ballers' points are scored with this "
          "league's own book (completions, carries, yardage bonuses as an expectation, turnovers); "
          "FantasyPros and Flock only publish PPR/half/standard boards, so their ranks are those. "
          "Sleeper is the only source that counts byes and games left. **Consensus** averages them; for FLEX each source is re-ranked among RB/WR/TE first so "
          "the numbers share a scale. A wide **Spread** is where the sources disagree — the trade targets. "
          "Vegas is weekly only, so it's not here.")


def _rankings(ctx, g) -> None:
    """Every ranked player, in tiers, on any of three panels or their consensus,
    cut to the men you can actually start or claim."""
    _hz = st.segmented_control("Horizon", ["This week", "Rest of season"],
                               key=f"rk_hz_{ctx['league_key']}", selection_mode="single",
                               default="This week", label_visibility="collapsed") or "This week"
    if _hz == "Rest of season":
        _rankings_ros(ctx, g)
        return
    reg = ctx["registry"]
    games = g.get("games") or {}
    pn = _panels(ctx, g)
    fp, fl, fb = pn.get("fp") or {}, pn.get("flock") or {}, pn.get("ffb") or {}
    lk = ctx["league_key"]
    # The column headers ARE the source switch (a click on FP / Flock / Ballers /
    # Consensus / Proj sorts by it), so the strip is only who + position.
    skey = f"rk_src_{lk}"
    st.session_state.setdefault(skey, "Consensus")
    src = st.session_state[skey]
    from .. import panels as P
    with st.container(key="rk_ctl"):
        c = st.columns([1.6, 2.9, 0.9, 0.9])
        who = c[0].segmented_control("Who", _RK_WHO, key=f"rk_who_{lk}", selection_mode="single",
                                     label_visibility="collapsed") or _RK_WHO[0]
        # FLEX by default: the cross-position list is the one a lineup or a
        # claim is decided from. ALL is every position by projection.
        st.session_state.setdefault(f"rk_pos_{lk}", "FLEX")
        # "all ↗" on the ticker parks a request here; it can only be applied
        # BEFORE the control exists for this run.
        _goto = st.session_state.pop(f"rk_pos_goto_{lk}", None)
        if _goto in _RK_POS:
            st.session_state[f"rk_pos_{lk}"] = _goto
        pos = c[1].segmented_control("Pos", _RK_POS, key=f"rk_pos_{lk}", selection_mode="single",
                                     label_visibility="collapsed") or "FLEX"
        _since_labels = [b for _a, b in _RK_SINCE]
        st.session_state.setdefault(f"rk_since_{lk}", "1d")
        since_lab = c[2].segmented_control("Since", _since_labels, key=f"rk_since_{lk}",
                                           selection_mode="single", label_visibility="collapsed",
                                           help="Movers since: yesterday · Tuesday · last week") or "1d"
        since = next(a for a, b in _RK_SINCE if b == since_lab)
        limit = c[3].selectbox("Rows", [40, 80, 150, 400], key=f"rk_n_{lk}",
                               label_visibility="collapsed",
                               format_func=lambda n: f"top {n}")
    movers_view = pos == "▲▼ Movers"
    if movers_view:
        pos = "FLEX"
    waivers_view = pos == "＋ Waivers"
    wv = {}
    if waivers_view:
        pos = "WAIVERS"
        wv = _udk_wv(g["season"], g["week"], reg) or {}
        if not wv:
            st.markdown(C.action_html(
                "info", "＋", f"The Fantasy Footballers haven't posted week {g['week']} waivers yet",
                "Their list usually goes up Monday night after the late game. This view fills in "
                "as soon as it does — last week's targets are never shown in its place.",
                "0", "targets"), unsafe_allow_html=True)
            return
        pn = dict(pn, wv=wv)
        from .. import udk_waivers as UW
        _fa = inseason.faab(ctx["meta"]) or {}
        _budget = int(_fa.get("budget") or 0)
        _left = max(0, _budget - int((_fa.get("by_owner") or {}).get(str(g["me"]), 0) or 0))
    # a click on a mover chip parks the pid here; the board scrolls to him
    fkey = f"rk_focus_{lk}"
    focus = st.session_state.get(fkey)

    # ---- ownership, the league lens -----------------------------------------
    owner_of = {}
    for oid, r in g["rosters"].items():
        for p in r.get("players") or []:
            owner_of[str(p)] = str(oid)
    me = str(g["me"])
    started = {str(p) for p in (g.get("starters") or []) if p and str(p) != "0"}
    # what a free agent adds to YOUR week — the waiver board's number. An
    # optimiser pass per free agent, so it rides the refresh clock: uncached it
    # was six of the seven seconds this tab took.
    fa_gain = _fa_gain_cached(lk, g["week"], _slow_bucket(g["season"], g["week"]),
                              ctx, g, frozenset(owner_of))

    # ---- the universe: every pid any panel ranks, plus my roster ------------
    # Built once per refresh window: six hundred registry lookups and an
    # availability read each is two seconds a click otherwise.
    rows = _rk_rows_cached(lk, g["week"], _slow_bucket(g["season"], g["week"]), pos,
                           reg, g, pn, owner_of, _PANEL_VER)
    for r in rows:
        r["wv"] = wv.get(r["pid"]) if waivers_view else None
    if not rows:
        st.info("Nothing ranked for that position yet.")
        return
    # Cross-position ranks for the FLEX view, RB/WR/TE against each other on
    # every panel: FantasyPros' FLEX list already is; Flock's overall rank is
    # re-ranked with the quarterbacks taken out so its numbers mean the same
    # thing as FantasyPros'; the Ballers rank by their points.
    _skill = [r for r in rows if r["pos"] in ("RB", "WR", "TE")]
    for i, r in enumerate(sorted((r for r in _skill if r["pts"] is not None), key=lambda r: -r["pts"]), 1):
        r["ov"]["ffb"] = float(i)
    for i, r in enumerate(sorted((r for r in _skill if r["ov"]["flock"] is not None),
                                 key=lambda r: r["ov"]["flock"]), 1):
        r["ov"]["flock"] = float(i)
    for i, r in enumerate(sorted((r for r in _skill if r.get("vpts") is not None),
                                 key=lambda r: -r["vpts"]), 1):
        r["ov"]["vegas"] = float(i)
    cross = pos in ("ALL", "FLEX")
    # ALL mixes positions no panel ranks against each other, so it sorts by
    # projection and shows the positional ranks; pick a position to rank by a panel.
    all_view = pos == "ALL"
    if all_view:
        cross = False
    # ---- the day's moves, per panel and on average ----------------------------
    try:
        mv = P.movers(g["season"], g["week"], pn, since=since, cross=cross)
        base_day = P.baseline_day("flock", g["season"], g["week"], since) or \
            P.baseline_day("fp", g["season"], g["week"], since)
    except Exception:  # noqa: BLE001
        mv, base_day = {}, None
    for r in rows:
        r["mv"] = mv.get(r["pid"])
    if movers_view:
        if base_day is None:
            # Nothing to diff against yet. Say so rather than draw an empty board.
            _when = {"yesterday": "yesterday", "week": "Tuesday", "last": "last week"}[since]
            _days = P._snap_days("flock", g["season"], g["week"]) or P._snap_days("fp", g["season"], g["week"])
            st.markdown(C.action_html(
                "info", "▲▼", f"No snapshot to compare against for '{_when}' yet",
                (f"The panels are photographed once a day; the first one this week was taken "
                 f"{'today' if _days else 'just now'}. Moves since yesterday show from tomorrow, "
                 f"since Tuesday from Thursday, and 'last week' from week 2 on. Every rank cell on "
                 f"the board picks up its ▲/▼ at the same time."),
                str(len(_days)), "snapshots"), unsafe_allow_html=True)
            return
        _depth = 30
        rows = [r for r in rows if P.is_mover(r.get("mv"), _depth)]
        if not rows:
            _since_txt0 = {"yesterday": "since yesterday", "week": "since Tuesday", "last": "since last week"}[since]
            st.markdown(C.action_html("go", "✓", f"Nobody moved {_since_txt0}",
                                      "No consensus move of 3+ places and no panel moved anyone 6+.",
                                      "0", "movers"), unsafe_allow_html=True)
            return
    for r in rows:
        # Consensus is the HUMANS — the market sits beside it, so the spread
        # between them stays visible instead of averaging away.
        src_ = (r["ov"] if cross else r["pr"])
        vals = [v for k, v in src_.items() if v is not None and k != "vegas"]
        r["cons"] = (sum(vals) / len(vals)) if vals else None
        r["best"] = min(vals) if vals else None
        r["worst"] = max(vals) if vals else None
        r["n"] = len(vals)
    # projected points, unranked men sort last; K/DST in ALL sort by proj after the skill men
    key_src = {"Consensus": "cons", "FantasyPros": "fp", "Flock": "flock", "The Ballers": "ffb",
               "Vegas": "vegas", "Proj": "proj"}[src]

    def _sort_val(r):
        if waivers_view:
            w = r.get("wv") or {}
            # their order, skill targets first, then the defense streamers
            return (bool(w.get("is_dst")), w.get("consensus") or 99.0, -r["proj"])
        if movers_view:
            m = r.get("mv") or {}
            return (m.get("cons") is None, -abs(m.get("cons") or 0), -r["proj"])
        if all_view or key_src == "proj":
            return (False, -r["proj"], 0.0)
        if key_src == "cons":
            v = r["cons"]
        else:
            v = (r["ov"] if cross else r["pr"]).get(key_src)
        return (v is None, v if v is not None else 0.0, -r["proj"])
    rows.sort(key=_sort_val)
    # colour thirds are computed on the WHOLE position pool, before the who-cut
    pools = {}
    for k in ("fp", "flock", "ffb", "vegas"):
        for r in rows:
            v = (r["ov"] if cross else r["pr"]).get(k)
            if v is not None:
                pools.setdefault((r["pos"] if not cross else "*", k), []).append(v)
    for r in rows:
        pools.setdefault((r["pos"] if not cross else "*", "cons"), []).append(r["cons"]) if r["cons"] is not None else None
        pools.setdefault((r["pos"] if not cross else "*", "proj"), []).append(-r["proj"])
    # the hero counts YOUR men in the top ten of the whole view, before the
    # who-cut (on "Mine" every row is yours, which says nothing)
    _top10 = rows[:10]
    _mine10 = [r for r in _top10 if r["owner"] == me]
    st.markdown(C.hero_html(f"THIS WEEK · {pos if pos not in ('WAIVERS',) else 'WAIVERS'}", str(len(_mine10)),
                            "of the top ten are yours" + (f' — <b>{_esc_(_mine10[0]["name"])}</b> leads them'
                                                          if _mine10 else ""),
                            photo=(_mine10[0]["pid"] if _mine10 else (_top10[0]["pid"] if _top10 else None)), tone="ink"),
                unsafe_allow_html=True)
    # the who-cut
    if who == "Mine":
        rows = [r for r in rows if r["owner"] == me]
    elif who == "Free agents":
        rows = [r for r in rows if not r["owner"]]
    elif who == "Mine + FA":
        rows = [r for r in rows if r["owner"] in (None, me)]
    total = len(rows)
    rows = rows[:limit]

    # ---- render ---------------------------------------------------------------
    lit = "proj" if (all_view or key_src == "proj") else key_src
    # ---- the ticker: the biggest moves, one line, click to jump ---------------
    _tick = sorted((r for r in rows if r.get("mv") and P.is_mover(r["mv"])),
                   key=lambda r: -abs((r["mv"].get("cons") or 0)))[:8]
    _since_txt = {"yesterday": "since yesterday", "week": "since Tuesday", "last": "since last week"}[since]
    if not movers_view and not waivers_view:
        with st.container(key="rk_tick"):
            if base_day is None:
                st.markdown(f'<div class="rk-tk"><span class="k"><b>Movers</b> · first snapshot today — '
                            f'moves show from tomorrow</span></div>', unsafe_allow_html=True)
            elif not _tick:
                st.markdown(f'<div class="rk-tk"><span class="k"><b>Movers</b> · {_since_txt} · '
                            f'nobody moved more than 2</span></div>', unsafe_allow_html=True)
            else:
                tc = st.columns([1.3] + [1] * len(_tick) + [0.7])
                tc[0].markdown(f'<div class="rk-tk"><span class="k"><b>Movers</b> · {_since_txt}</span></div>',
                               unsafe_allow_html=True)
                for col, r in zip(tc[1:], _tick):
                    m = r["mv"]
                    d = m.get("cons") or 0
                    lab = f'{"▲" if d > 0 else "▼"}{abs(d):.0f} {r["name"].split()[-1]}'
                    if col.button(lab, key=f"rk_tk_{lk}_{r['pid']}", use_container_width=True,
                                  help=f'{r["name"]} · {_why(r, mv, rows)}',
                                  type="primary" if r["owner"] == me else "secondary"):
                        st.session_state[fkey] = r["pid"]
                        st.rerun()
                if tc[-1].button("all ↗", key=f"rk_tk_all_{lk}", use_container_width=True):
                    st.session_state[f"rk_pos_goto_{lk}"] = "▲▼ Movers"
                    st.rerun()
    # The header row is real buttons in columns of the SAME weights as the
    # board's grid, so they sit over their columns. Opp, Spread and Owner are
    # labels; the rest switch the source.
    head = (("", None), ("Opp", None), ("FP", "FantasyPros"), ("Flock", "Flock"),
            ("Ballers", "The Ballers"), ("Consensus", "Consensus"), ("Vegas", "Vegas"),
            ("Lines", None), ("Spread", None), ("Proj", "Proj"), ("Owner", None))
    if waivers_view:
        head = (("", None), ("Opp", None), ("FP", None), ("Flock", None), ("Ballers", None),
                ("Waiver #", None), ("Vegas", None), ("Andy · Jason · Mike", None),
                ("Their bid", None), ("Proj", None), ("Adds · Owner", None))
    if movers_view:
        head = (("", None), ("Opp", None), ("FP Δ", None), ("Flock Δ", None), ("Ballers Δ", None),
                ("Move", None), ("Vegas Δ", None), ("Lines", None), ("Was → now", None),
                ("Proj", None), ("Why · Owner", None))
    _lit_label = {"fp": "FantasyPros", "flock": "Flock", "ffb": "The Ballers",
                  "cons": "Consensus", "vegas": "Vegas", "proj": "Proj"}[lit]
    with st.container(key="rk_hd"):
        hc = st.columns([330, 92, 70, 70, 78, 84, 74, 100, 78, 66, 230])
        for col, (label, source) in zip(hc, head):
            with col:
                if source is None:
                    st.markdown(f'<div class="rk-hl{" lbl" if label in ("Owner", "Why · Owner", "Adds · Owner") else ""}'
                                f'{" on" if label in ("Move", "Waiver #") else ""}">{label}</div>',
                                unsafe_allow_html=True)
                    continue
                on = source == _lit_label
                if st.button(("● " if on else "○ ") + label + (" ▾" if on else ""),
                             key=f"rk_h_{lk}_{source}", use_container_width=True,
                             type="primary" if on else "secondary",
                             disabled=(all_view and source != "Proj")):
                    st.session_state[skey] = source
                    st.rerun()
    st.markdown(_day_line(g, list(zip(g["slots"], g.get("starters") or [])), reg)
                .replace("</div>", (f' · <b>the Ballers\' waiver list</b> · week {g["week"]} · {who} · {total} of {len(wv)}' if waivers_view else
                                    f' · <b>movers {_since_txt}</b> · {total}' if movers_view else
                                    f' · sorted by <b>{_lit_label if not all_view else "projection"}</b> · {pos} · {who} · {min(limit, total)} of {total}') + '</div>'),
                unsafe_allow_html=True)
    out = ['<div class="rk">']
    tiers = (_TIERS_ALL if (cross or all_view)
             else _TIERS_DEEP if pos in ("RB", "WR") else _TIERS_POS)
    band_i = -1
    for idx, r in enumerate(rows, 1):
        if waivers_view:
            _dst = bool((r.get("wv") or {}).get("is_dst"))
            if int(_dst) != band_i:
                band_i = int(_dst)
                out.append('<div class="rk-tier"><div class="band ' + ("tD" if _dst else "tA") + '">'
                           + ("<em>D</em>Defense streamers<small>their order · by matchup</small>" if _dst
                              else "<em>＋</em>Waiver targets<small>their order · with their FAAB</small>")
                           + '</div><i></i></div>')
        rank_for_tier = (float(idx) if (all_view or waivers_view) else
                         (_sort_val(r)[1] if _sort_val(r)[0] is False else 10 ** 6))
        if waivers_view:
            ti = band_i
        elif src == "Flock" and r["tier_flock"] and not all_view:
            ti = min(int(r["tier_flock"]) - 1, len(tiers) - 1)
        else:
            ti = next(i for i, (cut, _l, _w) in enumerate(tiers) if rank_for_tier <= cut)
        if ti != band_i and not waivers_view:
            band_i = ti
            _cut, lab, why = tiers[ti]
            out.append(f'<div class="rk-tier"><div class="band t{lab}"><em>{lab}</em>Tier {ti + 1}'
                       f'<small>{_esc_(why)}</small></div><i></i></div>')
        gm = WV.game_of(reg, games, r["pid"])
        opp = (("vs " if gm.get("home") else "@ ") + gm["opp"]) if gm else "bye"
        k_lab = GT.day_label(gm)
        early = bool(gm) and GT.kickoff_ts(gm) == min((GT.kickoff_ts(x) for x in games.values()), default=0)
        pool_key = (r["pos"] if not cross else "*")
        vals = r["ov"] if cross else r["pr"]

        m = r.get("mv") or {}

        def dsub(k):
            d = (m.get("d") or {}).get(k)
            if k in (m.get("gone") or []):
                return '<sub class="dn">gone</sub>'
            if k in (m.get("new") or []):
                return '<sub class="up">new</sub>'
            if d is None or abs(d) < 0.5:
                return ""
            return f'<sub class="{"up" if d > 0 else "dn"}">{"▲" if d > 0 else "▼"}{abs(d):.0f}</sub>'

        def dcell(k):
            d = (m.get("d") or {}).get(k)
            if k in (m.get("gone") or []):
                return '<div class="c r">gone</div>'
            if k in (m.get("new") or []):
                return '<div class="c g">new</div>'
            if d is None:
                return '<div class="c dim">—</div>'
            if abs(d) < 0.5:
                return '<div class="c dim">–</div>'
            return f'<div class="c {"g" if d > 0 else "r"}">{"▲" if d > 0 else "▼"}{abs(d):.0f}</div>'

        def cell(k, v, fmt="{:.0f}"):
            if v is None:
                return '<div class="c dim">—</div>'
            return (f'<div class="c {_third(v, pools.get((pool_key, k), []))}'
                    f'{" sort" if k == lit else ""}">{fmt.format(v)}{dsub(k)}</div>')
        vg_line = (f'<div class="c ln">{_esc_(r.get("vline") or "—")}</div>')
        if movers_view:
            fp_c, fl_c, fb_c = dcell("fp"), dcell("flock"), dcell("ffb")
            vg_c = dcell("vegas")
            dc = m.get("cons")
            cons_c = (f'<div class="c mvc {"g" if dc > 0 else "r"}">{"▲" if dc > 0 else "▼"} {abs(dc):.0f}</div>'
                      if dc is not None else '<div class="c dim">—</div>')
            sp = (f'<div class="c y">{m["was_avg"]:.0f} → {m["now_avg"]:.0f}</div>'
                  if m.get("was_avg") is not None and m.get("now_avg") is not None else '<div class="c dim">—</div>')
        else:
            fp_c = cell("fp", vals["fp"])
            fl_c = cell("flock", vals["flock"], "{:.1f}" if not cross else "{:.0f}")
            vg_c = (f'<div class="c {_third(vals["vegas"], pools.get((pool_key, "vegas"), []))}{" sort" if lit == "vegas" else ""}">'
                    f'{vals["vegas"]:.0f}<small>{r["vpts"]:.1f}</small>{dsub("vegas")}</div>'
                    if vals.get("vegas") is not None else '<div class="c dim">—</div>')
            fb_c = (f'<div class="c {_third(vals["ffb"], pools.get((pool_key, "ffb"), []))}{" sort" if lit == "ffb" else ""}">'
                    f'{vals["ffb"]:.0f}<small>{r["pts"]:.1f}</small>{dsub("ffb")}</div>'
                    if vals["ffb"] is not None else '<div class="c dim">—</div>')
            cons_c = cell("cons", r["cons"], "{:.1f}").replace("</div>", dsub_cons(m) + "</div>") \
                if r["cons"] is not None else '<div class="c dim">—</div>'
            if r["n"] >= 2:
                wide = (r["worst"] - r["best"]) > max(4.0, 0.35 * (r["cons"] or 0))
                sp = f'<div class="c {"r" if wide else "g"}">{r["best"]:.0f}–{r["worst"]:.0f}</div>'
            else:
                sp = '<div class="c dim">—</div>'
        proj_c = (f'<div class="c {_third(-r["proj"], pools.get((pool_key, "proj"), []))}'
                  f'{" sort" if lit == "proj" else ""}">{r["proj"]:.1f}</div>')
        if waivers_view:
            w = r.get("wv") or {}
            _n = w.get("consensus")
            cons_c = (f'<div class="c mvc {"g" if (_n or 99) <= 5 else "y" if (_n or 99) <= 15 else ""} sort">'
                      f'#{int(_n)}</div>' if _n else '<div class="c dim">—</div>')
            _by = w.get("by") or {}
            vg_line = ('<div class="c ln">' + " · ".join(
                f'{a[:1].upper()}{int(v)}' for a, v in _by.items()) + '</div>'
                if _by else '<div class="c ln">—</div>')
            _b = UW.bid(w, _left or _budget)
            sp = (f'<div class="c {"g" if _b[1] >= 10 else "y" if _b[1] else ""}">${_b[0]}–{_b[1]}</div>'
                  if _b else '<div class="c dim">—</div>')
        # On a phone the board becomes a card per player and the column headers
        # are gone, so every cell carries its own label to show there instead.
        def _k(html: str, label: str) -> str:
            return html.replace("<div ", f'<div data-k="{label}" ', 1)
        fp_c, fl_c = _k(fp_c, "FP"), _k(fl_c, "Flock")
        fb_c, vg_c = _k(fb_c, "Ballers"), _k(vg_c, "Vegas")
        cons_c = _k(cons_c, "Move" if movers_view else "Waiver #" if waivers_view else "Consensus")
        sp = _k(sp, "Was → now" if movers_view else "Their bid" if waivers_view else "Spread")
        proj_c = _k(proj_c, "Proj")
        vg_line = _k(vg_line, "A · J · M" if waivers_view else "Lines")
        # owner
        if r["owner"] == me:
            tag = ('<span class="tag st">you · start</span>' if r["pid"] in started
                   else '<span class="tag me">you · bench</span>')
            own = f'<b class="me">You</b> · {"starting" if r["pid"] in started else "bench"}'
            cls = "me"
        elif r["owner"]:
            tag, cls = "", ""
            own = f'<b>{_esc_(_owner_name(ctx, r["owner"]))}</b>'
        else:
            tag, cls = '<span class="tag fa">free agent</span>', "fa"
            gn = fa_gain.get(r["pid"])
            own = '<b class="fa">Free agent</b>' + (f' · +{gn:.1f} to your week' if (gn or 0) > 0.05
                                                    else ' · no upgrade')
        inj = (f'<small style="color:var(--amber)"> {r["inj"]["status"][:1].upper()}</small>'
               if r["inj"].get("status") else "")
        dc = m.get("cons")
        badge = (f'<span class="dl {"up" if dc > 0 else "dn"}">{"▲" if dc > 0 else "▼"} {abs(dc):.0f}</span>'
                 if (dc is not None and abs(dc) >= 3 and not movers_view and not waivers_view) else "")
        if movers_view:
            own = f'{_esc_(_why(r, mv, rows))} · ' + own
        is_focus = focus and str(focus) == r["pid"]
        out.append(
            f'<div class="rk-row {cls}{" focus" if is_focus else ""}" id="rk-{r["pid"]}"><div class="pl">{_T.img_tag(r["pid"], "")}'
            f'<b>{idx}. {_esc_(r["name"])}<small>{_esc_(r["team"])}{" · " + r["pos"] if (cross or movers_view or waivers_view) else ""}{inj}</small></b>{badge}{tag}</div>'
            f'<div class="opp{" early" if early else ""}">{_esc_(opp)}<small>{_esc_(k_lab)}</small></div>'
            f'{fp_c}{fl_c}{fb_c}{cons_c}{vg_c}{vg_line}{sp}{proj_c}<div class="own">{own}</div></div>')
    out.append("</div>")
    st.markdown("".join(out), unsafe_allow_html=True)
    if focus:
        # Scroll the page to the man he clicked. A markdown block cannot run a
        # script; a components iframe can, and it is same-origin with the app.
        import streamlit.components.v1 as _cmp
        _cmp.html(f"""<script>
          const el = window.parent.document.getElementById("rk-{focus}");
          if (el) el.scrollIntoView({{behavior: "smooth", block: "center"}});
        </script>""", height=0)
        st.session_state.pop(fkey, None)
    _n = {"fp": len(fp), "flock": len(fl), "ffb": len(fb), "vegas": len(pn.get("vegas") or {})}
    _vpub = next((r.get("published") for r in (pn.get("vegas") or {}).values() if r.get("published")), None)
    _note(f"Colour is by third of the position on each column — a yellow 22 at WR is a WR2, not a "
               f"warning. **Spread** is best–worst across the panels, red when they disagree. "
               f"{'ALL sorts by projection and shows positional ranks — pick a position to rank by a panel.' if all_view else ('Cross-position ranks, RB/WR/TE against each other (FantasyPros FLEX list, Flock with the QBs taken out, the Ballers by points).' if cross else 'Positional ranks.')} "
               f"FantasyPros {_n['fp']} · Flock {_n['flock']} · the Ballers {_n['ffb']} · Vegas "
               f"{_n.get('vegas', 0)} players. **Vegas** is Bovada's player props scored under this "
               f"league's settings — yards and receptions lines nudged by their juice, anytime-TD "
               f"odds devigged against the game's total-touchdowns line; **Lines** is the position's "
               f"yards line and the TD price. Consensus is the three human panels; the market sits "
               f"beside it. Only FantasyPros ranks D/ST."
               + (f" Lines published from the Mac at {_vpub}." if _vpub else
                  (" **No lines yet** — Bovada refuses this host; the Mac publishes them hourly."
                   if not _n.get('vegas') else "")))


@st.cache_data(show_spinner=False, max_entries=8)
def _fa_gain_cached(league_key: str, week: int, bucket: int, _ctx, _g, _taken) -> dict:
    out = {}
    try:
        reg = _ctx["registry"]
        fas = inseason.free_agents(_ctx["meta"], reg, _g["proj"], set(_taken), limit=150,
                                   ecr=_g.get("ros"))
        for r in W.waiver_board(_g["mine"], _g["slots"], _g["proj"], reg, fas, byes=_g["byes"],
                                week=_g["week"], limit=150, ecr=_g.get("ros")):
            out[str(r["pid"])] = float(r["gain"])
    except Exception:  # noqa: BLE001
        pass
    return out


def _esc_(s) -> str:
    return C._esc(s)


def dsub_cons(m: dict) -> str:
    d = (m or {}).get("cons")
    if d is None or abs(d) < 0.5:
        return ""
    return f'<sub class="{"up" if d > 0 else "dn"}">{"▲" if d > 0 else "▼"}{abs(d):.0f}</sub>'


def _why(r: dict, mv: dict, rows: list) -> str:
    """One derived line for a move: his own status, a teammate at his position
    who went down, or "one panel alone". Never typed — always from the data."""
    m = r.get("mv") or {}
    st_ = (r.get("inj") or {}).get("status")
    if st_:
        return f'{st_}'
    if (m.get("cons") or 0) > 0:
        # a riser: is a teammate at the same position out?
        for o in rows:
            if o["pid"] != r["pid"] and o["team"] == r["team"] and o["pos"] == r["pos"]:
                ost = (o.get("inj") or {}).get("status") or ""
                if ost.upper().startswith(("OUT", "IR", "DOUB")):
                    return f'{o["name"].split()[-1]} {ost.lower()}'
    d = {k: v for k, v in (m.get("d") or {}).items() if abs(v) >= 0.5}
    if len(d) == 1:
        k = next(iter(d))
        return {"fp": "FantasyPros", "flock": "Flock", "ffb": "the Ballers", "vegas": "the book"}[k] + " alone"
    if len(d) >= 2 and all((v > 0) == ((m.get("cons") or 0) > 0) for v in d.values()):
        return "every panel" if len(d) >= 3 else "two panels"
    return "panels split"


# ------------------------------------------------------------------- 2 waivers
@st.cache_data(show_spinner=False, max_entries=8)
def _waiver_board_cached(league_key: str, week: int, bucket: int, _ctx, _g, _taken):
    meta, reg = _ctx["meta"], _ctx["registry"]
    # ROS consensus picks the candidate pool, weekly consensus breaks ties on the
    # board: who is worth rostering is a rest-of-season question, who helps you on
    # Sunday is a weekly one.
    fas = inseason.free_agents(meta, reg, _g["proj"], _taken, limit=60, ecr=_g.get("ros"))
    # ROS for the tiebreak too, NOT the weekly map: rest-of-season is one list
    # covering every position, so its ranks can be compared to each other. The
    # weekly ranks cannot — see ecr._row's "scale".
    return W.waiver_board(_g["mine"], _g["slots"], _g["proj"], reg, fas,
                          byes=_g["byes"], week=_g["week"], limit=14, ecr=_g.get("ros"))



def _claim_builder(ctx, g, board, left: int, budget: int, weeks_left: int) -> None:
    """The whole Wednesday: claims in priority order, a bid and a drop for each,
    and what the budget looks like if they all clear.

    The tab used to show one claim card and leave the order, the bids and the
    drops to be worked out in Sleeper. This keeps the plan — persisted, because
    on the phone every tab press is a fresh session and a queue that forgot
    itself between Today and Waivers would not be a queue. Sleeper still takes
    the claims; this hands it a finished list.
    """
    from .. import userstate as US
    reg, lk = ctx["registry"], ctx["league_key"]
    queue = US.claims(lk)

    # the drop candidates: his bench, lowest projection first — the suggestion
    # is the first one, and he can pick any other
    lc = W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"])
    bench = sorted(((float(g["proj"].get(str(p), 0) or 0), str(p)) for p in lc.get("bench") or []))
    drop_opts = ["(no drop — open spot)"] + [reg.meta(p).name for _v, p in bench]
    drop_pid = {reg.meta(p).name: p for _v, p in bench}

    def _fill(c: dict) -> dict:
        """Price and face a queued claim from today's board, once."""
        c = dict(c)
        row = next((r for r in board if str(r["pid"]) == str(c.get("pid"))), None)
        if c.get("gain") is None and row:
            c["gain"] = row["gain"]
        if c.get("gain") is not None and (c.get("range") or {}).get("mode") is None:
            c["range"] = FM.bid(ctx["meta"], g["week"], dict(row or {}, gain=c["gain"], pid=c.get("pid")),
                                  budget, left, weeks_left)
            # a bid saved under the old value-only pricing ($28 for a $2
            # market) goes with it, unless he picked that number himself
            if "bid" not in (c.get("_set") or []):
                c["bid"] = None
        if c.get("bid") is None:
            c["bid"] = (c.get("range") or {}).get("low") or 1
        try:
            pm = reg.meta(c["pid"])
            c.setdefault("name", pm.name)
            c["face"] = getattr(pm, "sleeper_pid", None) or c["pid"]
            c["team"] = pm.team or ""
        except Exception:  # noqa: BLE001
            pass
        if c.get("drop") is None and "drop" not in c.get("_set", []) and bench:
            # Each claim drops a DIFFERENT man by default, lowest projection
            # first in priority order — if two claims clear, he cannot cut the
            # same player twice. A drop he chose himself is left alone.
            free = [p for _v, p in bench if p not in used_drops]
            c["drop"] = free[0] if free else None
        if c.get("drop"):
            used_drops.add(c["drop"])
        c["drop_name"] = reg.meta(c["drop"]).name if c.get("drop") else None
        return c

    used_drops = {c.get("drop") for c in queue if c.get("drop") and "drop" in c.get("_set", [])}
    queue = [_fill(c) for c in queue]
    # A claim for a man who's on a roster now is settled — he won it, lost it,
    # or the player was never a free agent. Those leave the queue (their
    # suggested bids are kept for the waiver recap) instead of sitting there
    # until he clears them by hand.
    taken = {str(p) for r in g["rosters"].values() for p in (r.get("players") or [])}
    try:
        US.note_suggestions(lk, queue)
    except Exception:  # noqa: BLE001
        pass
    if any(str(c.get("pid")) in taken for c in queue):
        queue = [c for c in queue if str(c.get("pid")) not in taken]
        US.save_claims(lk, [{k: v for k, v in r.items()
                             if k in ("pid", "name", "bid", "range", "gain", "drop", "_set")}
                            for r in queue])
    queued = sum(int(c.get("bid") or 0) for c in queue)
    st.markdown('<div class="ws-h">Your claims for Wednesday</div>', unsafe_allow_html=True)
    st.markdown(C.claim_budget_html(left, budget, queued), unsafe_allow_html=True)

    def _save(rows):
        US.save_claims(lk, [{k: v for k, v in r.items()
                             if k in ("pid", "name", "bid", "range", "gain", "drop", "_set")}
                            for r in rows])

    if not queue:
        st.markdown('<div class="cb-empty">No claims queued. Add one from the board below, '
                    'or from Today.</div>', unsafe_allow_html=True)
    for i, c in enumerate(queue):
        st.markdown(C.claim_row_html(i + 1, c), unsafe_allow_html=True)
        with st.container(key=f"cbctl_{lk}_{c['pid']}"):
            a, b, u, d, x = st.columns([2.6, 3.2, 0.8, 0.8, 0.8])
            rng = c.get("range") or {}
            lo, hi = int(rng.get("low") or 1), int(rng.get("high") or max(1, int(c["bid"])))
            opts = sorted({lo, (lo + hi) // 2, hi, int(c["bid"])})
            bid = a.selectbox("Bid", opts, index=opts.index(int(c["bid"])), key=f"cb_bid_{lk}_{c['pid']}",
                              format_func=lambda v: f"${v}", label_visibility="collapsed")
            cur_drop = c.get("drop_name") or drop_opts[0]
            dname = b.selectbox("Drop", drop_opts,
                                index=drop_opts.index(cur_drop) if cur_drop in drop_opts else 0,
                                key=f"cb_drop_{lk}_{c['pid']}", label_visibility="collapsed")
            changed = False
            if bid != int(c["bid"]):
                queue[i]["bid"], changed = int(bid), True
                queue[i]["_set"] = list(set(queue[i].get("_set", [])) | {"bid"})
            new_drop = drop_pid.get(dname)
            if new_drop != c.get("drop"):
                queue[i]["drop"], changed = new_drop, True
                queue[i]["_set"] = list(set(queue[i].get("_set", [])) | {"drop"})
            if u.button("↑", key=f"cb_up_{lk}_{c['pid']}", disabled=i == 0):
                queue[i - 1], queue[i] = queue[i], queue[i - 1]
                changed = True
            if d.button("↓", key=f"cb_dn_{lk}_{c['pid']}", disabled=i == len(queue) - 1):
                queue[i + 1], queue[i] = queue[i], queue[i + 1]
                changed = True
            if x.button("✕", key=f"cb_rm_{lk}_{c['pid']}", help="Take him off the list"):
                queue.pop(i)
                _save(queue)
                rerun_here()
            if changed:
                _save(queue)
                rerun_here()

    # add from the board: the best adds not already queued
    have = {str(c["pid"]) for c in queue}
    adds = [r for r in board if r.get("gain", 0) > 0.05 and str(r["pid"]) not in have][:4]
    if adds:
        cols = st.columns(len(adds))
        for col, r in zip(cols, adds):
            if col.button(f'+ {r["name"].split()[-1]} {r["gain"]:+.1f}', key=f"cb_add_{lk}_{r['pid']}",
                          use_container_width=True):
                US.add_claim(lk, {"pid": str(r["pid"]), "name": r["name"], "gain": r["gain"],
                                  "range": FM.bid(ctx["meta"], g["week"], r, budget, left, weeks_left),
                                  "bid": None, "drop": None})
                rerun_here()
    if queue:
        lid = str(ctx["meta"].league_id)
        st.markdown(f'<a class="cb-go" href="https://sleeper.com/leagues/{lid}/players" '
                    f'target="_blank" rel="noopener">Open these claims in Sleeper ↗</a>',
                    unsafe_allow_html=True)
        _note("Sleeper takes the claims. This works out the order, the bids and the drops, "
                   "and keeps them until you clear them — claim #1 first, the rest as contingencies.")

def _waiver_recap(ctx, g):
    """The last waiver run he was in, for six days after it ran:
    (rec, dressed rows, "Tue 12:01 PM") or None."""
    import datetime as _dt, time as _t
    from .. import userstate as US, waiverrecap as WR
    meta = ctx["meta"]
    if getattr(meta, "platform", "") != "sleeper":
        return None
    try:
        rosters = api.get_rosters(str(meta.league_id)) or []
        rid = next((r["roster_id"] for r in rosters if str(r.get("owner_id")) == str(g["me"])), None)
        if rid is None:
            return None
        rec = WR.recap(str(meta.league_id), rid, g["week"])
    except Exception:  # noqa: BLE001
        return None
    if not rec or not rec["claims"] or _t.time() - rec["ts"] / 1000 > 6 * 86400:
        return None
    owner_of_rid = {r["roster_id"]: str(r.get("owner_id")) for r in rosters}
    sugg = US.suggestions(ctx["league_key"])
    reg = ctx["registry"]
    rows = []
    for r in rec["claims"]:
        r = dict(r)
        try:
            pm = reg.meta(r["pid"])
            r["name"], r["team"] = pm.name, pm.team or ""
            r["face"] = getattr(pm, "sleeper_pid", None) or r["pid"]
        except Exception:  # noqa: BLE001
            r["name"], r["face"] = r["pid"], r["pid"]
        if r.get("winner") is not None:
            r["winner_name"] = _owner_name(ctx, owner_of_rid.get(r["winner"], ""))
        r["sugg"] = sugg.get(str(r["pid"]))
        rows.append(r)
    try:
        from zoneinfo import ZoneInfo
        when = _dt.datetime.fromtimestamp(rec["ts"] / 1000, ZoneInfo("America/New_York"))
        when_s = when.strftime("%a %-I:%M %p")
    except Exception:  # noqa: BLE001
        when_s = f"week {rec['week']}"
    return rec, rows, when_s


def _drawer(title: str, summary: str = "", expanded: bool = False, key: str = ""):
    """A section folded to one line that says what's in it.

    Streamlit 1.50 can't report whether an expander is open, and a rerun closes
    it — so a widget inside that causes a rerun marks its drawer (`_keep_open`)
    and the drawer opens itself again on the way back."""
    if key and st.session_state.get(f"drawer_{key}"):
        expanded = True
    return st.expander(f"**{title}**" + (f"  ·  {summary}" if summary else ""), expanded=expanded)


def _lazy(key: str, label: str) -> bool:
    """Inside a drawer: True once he has asked for its contents this session.

    Streamlit runs an expander's body even when it's shut, so the Keepers tab
    was building every team's keepers, next year's board and every player's
    history before any drawer was opened. A drawer that's expensive shows one
    button until it's wanted, then stays built (and open) for the session."""
    flag = f"lazy_{key}"
    if st.session_state.get(flag):
        return True

    def _go():
        st.session_state[flag] = True
        st.session_state[f"drawer_{key}"] = True
    st.button(label, key=f"lazybtn_{key}", on_click=_go)
    return False


def _keep_open(key: str):
    """on_change callback for a widget that lives in drawer `key`."""
    return lambda: st.session_state.__setitem__(f"drawer_{key}", True)


def _waivers_run_label() -> str:
    import datetime as _dt, time as _t
    from .. import weekpulse as WP
    try:
        from zoneinfo import ZoneInfo
        ts = WP._next_waivers_ts(_t.time())
        return _dt.datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).strftime("%a %-I:%M %p")
    except Exception:  # noqa: BLE001
        return "Wed 3:00 AM"


def _best_stash(ctx, g, taken) -> Optional[dict]:
    """In a keeper league: the free agent with the best projected NEXT-season
    ADP who can actually be kept, at the price the keeper rules give him.

    A waiver add usually keeps at the last round — but not a dropped keeper,
    whose clock keeps running (Achane: kept 2025 and 2026, so 2027 is past
    the three-year limit). So each candidate is priced through _keeper_rows,
    and anyone blocked is skipped. None in a redraft league or when nobody
    keepable projects inside 10 rounds."""
    from .. import nextyear as NY
    meta, reg = ctx["meta"], ctx["registry"]
    if meta.platform != "sleeper" or not K.league_has_keepers(str(meta.league_id)):
        return None
    n = int(getattr(meta, "num_teams", 10) or 10)
    try:
        proj = NY.projected(n, 1.0)
    except Exception:  # noqa: BLE001
        return None
    last = K.price_rounds(K.load_keeper_rules(str(meta.league_id)) or {}, int(g["season"]), meta.draft_rounds or 14)
    _taken = {str(t) for t in taken}
    cands = sorted((r["rank"], pid) for pid, r in proj.items() if pid not in _taken and r["rank"] <= n * 10)[:12]
    if not cands:
        return None
    priced = {str(r["pid"]): r for r in _keeper_rows(ctx, g, pids=[p for _r, p in cands], as_owner=None)}
    for rank, pid in cands:
        r = priced.get(str(pid))
        if r is not None and (r.get("blocked") or r.get("verdict") == "blocked"):
            continue
        cost = (r or {}).get("cost_round") or last
        return {"pid": pid, "name": reg.meta(pid).name, "rank": rank, "cost": cost}
    return None


def _fa_list(ctx, g, board, taken, wv, gain_of, budget, left, weeks_left) -> None:
    """Every free agent worth a look in ONE table, each source a column.

    This used to be four sections — the Ballers' list, our own ranking, Sleeper's
    trending adds and (further down) the drop list — and the same men appeared
    in up to three of them. Now the sources are columns and the lenses are
    pills over the same rows."""
    from .. import udk_waivers as UW
    reg, meta, lk = ctx["registry"], ctx["meta"], ctx["league_key"]
    try:
        tr = api.get_trending("add", 24, 200) or {}
    except Exception:  # noqa: BLE001
        tr = {}
    ecr, ros = g.get("ecr") or {}, g.get("ros") or {}
    by_pid = {str(r["pid"]): r for r in board}
    skill_wv = {pid: r for pid, r in (wv or {}).items() if not r.get("is_dst")}
    pids = set(by_pid) | {p for p in skill_wv if p not in taken}
    pids |= {str(p) for p in list(tr)[:60] if str(p) not in taken}
    # next season's cheap keepers: the free agents projected inside ten rounds
    # join the pool whether or not anything else would list them — in B&B,
    # first in line every week, the starters crowded the stash tier off the board
    from .. import nextyear as NY
    keeper_lg = meta.platform == "sleeper" and K.league_has_keepers(str(meta.league_id))
    n_t = int(getattr(meta, "num_teams", 10) or 10)
    nxt, keep_px = {}, {}
    if keeper_lg:
        try:
            nxt = NY.projected(n_t, 1.0)
        except Exception:  # noqa: BLE001
            nxt = {}
        _taken = {str(t) for t in taken}
        _st = [pid for _r, pid in sorted((r["rank"], pid) for pid, r in nxt.items()
                                         if pid not in _taken and r["rank"] <= n_t * 10)[:12]]
        pids |= set(_st)
        # priced through the keeper rules: a dropped keeper's clock keeps running
        keep_px = {str(r["pid"]): r for r in _keeper_rows(ctx, g, pids=_st)} if _st else {}
    rows = []
    for pid in pids:
        try:
            pm = reg.meta(pid)
        except Exception:  # noqa: BLE001
            continue
        if (pm.position or "").upper() not in ("QB", "RB", "WR", "TE"):
            continue
        gain = by_pid.get(pid, {}).get("gain")
        if gain is None:
            gain = gain_of.get(pid)
        wr = skill_wv.get(pid)
        rows.append({"pid": pid, "name": pm.name, "pos": pm.position, "team": pm.team or "",
                     "proj": float(g["proj"].get(pid, 0) or 0), "gain": float(gain or 0),
                     "ballers": int(wr["consensus"]) if (wr and wr.get("consensus")) else None,
                     "ballers_bid": UW.bid(wr, left or budget) if wr else None,
                     "adds": int(tr.get(pid) or tr.get(int(pid) if pid.isdigit() else pid) or 0),
                     "owned": (ros.get(pid) or ecr.get(pid) or {}).get("owned")})
    lenses = {"All": lambda r: True,
              "Starts for you": lambda r: r["gain"] > 0.05,
              "Trending": lambda r: r["adds"] > 0,
              "Ballers' list": lambda r: r["ballers"] is not None}
    counts = {k: sum(1 for r in rows if f(r)) for k, f in lenses.items()}
    # plain labels: a count in the label would change under the saved choice
    labels = list(lenses)
    pick = st.segmented_control("lens", labels, key=f"fa_lens_{lk}", selection_mode="single",
                                default=labels[0], label_visibility="collapsed",
                                on_change=_keep_open(f"fa_{lk}")) or labels[0]
    lens = pick if pick in lenses else labels[0]
    show = [r for r in rows if lenses[lens](r)]
    _note(" · ".join(f"{k.lower()} {counts[k]}" for k in lenses))
    order = {"Trending": lambda r: (-r["adds"], -r["gain"]),
             "Ballers' list": lambda r: (r["ballers"] or 999, -r["gain"])}
    show.sort(key=order.get(lens, lambda r: (-r["gain"], r["ballers"] or 999, -r["adds"], -r["proj"])))
    # ---- the board: the Rankings look — photo pills, tiers, coloured columns
    ecr = g.get("ecr") or {}

    def _blocked(pid):
        k = keep_px.get(str(pid))
        return bool(k and (k.get("blocked") or k.get("verdict") == "blocked"))

    def tier(r):
        nr = (nxt.get(r["pid"]) or {}).get("rank")
        if r["gain"] >= 1.0:
            return ("S", "Starts for you", "a real claim")
        if r["gain"] > 0.05:
            return ("A", "Closest to starting", "a tiebreak, not a claim")
        if nr and nr <= n_t * 10 and not _blocked(r["pid"]):
            return ("B", "Stash for next year", "next year's cheap keepers")
        if r["adds"] >= 50000:
            return ("C", "Rising", "the league is adding him")
        return ("D", "Depth", "")
    if lens == "All":
        order_t = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
        show.sort(key=lambda r: (order_t[tier(r)[0]], -r["gain"], (nxt.get(r["pid"]) or {}).get("rank") or 999, -r["adds"]))
    cols = "320fr 64fr 72fr 78fr 72fr 78fr 74fr" + (" 72fr" if keeper_lg else "") + " 120fr"
    heads = ["", "Proj", "+You", "Ballers", "FP", "Adds 24h", "Rostered"] + (["2027"] if keeper_lg else []) + ["Bid here"]
    out = [f'<div class="rk" style="--cols:{cols}"><div class="rk-hd">'
           + "".join(f'<span class="{"lbl" if h == "Bid here" else "on" if h == "+You" else ""}">{h}</span>' for h in heads)
           + '</div>']
    if lens == "All":
        _by = {}
        for r in show:
            _by.setdefault(tier(r)[0], []).append(r)
        _sb = _by.get("B", [])[:8]
        _top = (_by.get("S", []) + _by.get("A", []))[:30 - len(_sb)]
        _rest = (_by.get("C", []) + _by.get("D", []))[:max(0, 30 - len(_top) - len(_sb))]
        show = _top + _sb + _rest
    band = None
    for r in show[:30]:
        t = tier(r) if lens == "All" else None
        if t and t[0] != band:
            band = t[0]
            out.append(f'<div class="rk-tier"><div class="band t{t[0]}"><em>{t[0]}</em>{_esc_(t[1])}'
                       f'<small>{_esc_(t[2])}</small></div><i></i></div>')
        if r["gain"] > 0.05:
            b = FM.bid(meta, g["week"], r, budget, left, weeks_left) if budget else None
            bid = ("claim" if (b is None or b.get("mode") == "priority") else f'${b["low"]}–{b["high"]}')
        else:
            bid = "—"
        _av = W.availability(reg.meta(r["pid"]))
        inj = (f'<small style="color:var(--amber)"> {_av["status"][:1].upper()}</small>' if _av["status"] else "")
        e = ecr.get(r["pid"]) or {}
        fp = e.get("pos_rank") or ""
        bl = r["ballers"]
        nr = (nxt.get(r["pid"]) or {}).get("rank")

        def c(v, cls, label):
            return f'<div data-k="{label}" class="c {cls}">{v}</div>'
        cells = [
            c(f'{r["proj"]:.1f}', "", "Proj"),
            c((f'+{r["gain"]:.1f}' if r["gain"] > 0.05 else "+0.0"), ("g sort" if r["gain"] > 0.05 else "dim sort"), "+You"),
            c((f'#{bl}' + (f'<small>${r["ballers_bid"][0]}–{r["ballers_bid"][1]}</small>' if r["ballers_bid"] else "")) if bl else "—",
              ("g" if bl and bl <= 8 else "y" if bl and bl <= 20 else "dim"), "Ballers"),
            c(fp or "—", "y" if fp else "dim", "FP"),
            c((f'+{r["adds"] / 1000:.0f}k' if r["adds"] >= 1000 else (f'+{r["adds"]}' if r["adds"] else "—")),
              ("g" if r["adds"] >= 100000 else "y" if r["adds"] >= 20000 else "dim"), "Adds 24h"),
            c(f'{r["owned"]:.0f}%' if r["owned"] is not None else "—", "", "Rostered"),
        ]
        if keeper_lg:
            _k = keep_px.get(str(r["pid"]))
            _px = ("<small>aged out</small>" if _blocked(r["pid"]) else
                   f'<small>keeps R{_k["cost_round"]}</small>' if (_k and _k.get("cost_round")) else "")
            cells.append(c((f"#{nr}" if nr else "—") + _px,
                           ("dim" if _blocked(r["pid"]) else "g" if nr and nr <= n_t * 6 else "y" if nr and nr <= n_t * 10 else "dim"),
                           "2027"))
        out.append(f'<div class="rk-row fa"><div class="pl">{_T.img_tag(r["pid"], "")}'
                   f'<b>{_esc_(r["name"])}<small>{_esc_(r["team"])} · {r["pos"]}{inj}</small></b>'
                   f'<span class="tag fa">free agent</span></div>' + "".join(cells)
                   + f'<div class="own"><b class="{"bid" if bid != "—" else ""}">{_esc_(bid)}</b></div></div>')
    out.append("</div>")
    if show:
        st.markdown("".join(out), unsafe_allow_html=True)
    else:
        _note("Nobody fits this filter right now.")
    _mk = FM.market_for(meta, g["week"]) if budget else None
    _note("**+You** is what he'd add to your starting lineup this week — a player who doesn't crack "
          "your nine is worth $0 to you however highly he's ranked elsewhere. **Ballers** is the "
          "Fantasy Footballers' rank and their FAAB range in this league's dollars. **Adds 24h** is "
          "Sleeper-wide. **2027** (keeper leagues) is his projected next-season ADP and, for the stash tier, the round "
          "he'd keep at under this league's rules — a dropped keeper's clock keeps running, so he isn't "
          "always a last-round add. **Bid here** is priced from this league's own history"
          + (f" — {_mk.summary()}." if (_mk and _mk.summary()) else "."))


def _waivers(ctx, g) -> None:
    """Lead with the claim (or that there isn't one), then everything else in
    drawers that say what they hold. Was five sections and four tables."""
    meta, reg = ctx["meta"], ctx["registry"]
    taken = {p for r in g["rosters"].values() for p in r["players"]}
    # The board is the slow part of this tab (an optimiser pass per free agent),
    # so it rides the 15-minute clock rather than the score's two-minute one.
    board = _waiver_board_cached(ctx["league_key"], g["week"],
                                 _slow_bucket(g["season"], g["week"]), ctx, g, taken)
    fa = inseason.faab(meta) or {}
    budget = int(fa.get("budget") or 0)
    spent = int((fa.get("by_owner") or {}).get(str(g["me"]), 0) or 0)
    left = max(0, budget - spent) if budget else 0
    weeks_left = max(1, 14 - g["week"])
    _wpos = None if budget else inseason.waiver_position(meta, str(g["me"]))
    run_at = _waivers_run_label()
    n_up = sum(1 for r in board if r["starts"])

    _tiles([
        ("FAAB", f"${left}", f"of ${budget}", "var(--ink)") if budget else
        (("waiver priority", f"#{_wpos}", "", "var(--ink)") if _wpos else None),
        ("weeks left", f"{weeks_left}", "", "var(--ink)"),
        ("waivers run", run_at, "", "var(--ink)"),
        ("free agents start for you", f"{n_up}", "", "var(--green)" if n_up else "var(--mut2)"),
    ])

    # ---- the lead: the claim, or that there isn't one ------------------------
    top = next((r for r in board if r["gain"] >= 1.0), None)
    close = next((r for r in board if r["gain"] > 0.05), None)
    _lc = W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"])
    _bench = sorted(((float(g["proj"].get(str(p), 0) or 0), str(p)) for p in _lc.get("bench") or []))
    drop = reg.meta(_bench[0][1]).name if _bench else None
    kick = f"WAIVERS · WEEK {g['week']} · CLAIMS RUN {run_at.upper()}"
    _ph = lambda pid: getattr(reg.meta(pid), "sleeper_pid", None) or pid  # noqa: E731
    stash = _best_stash(ctx, g, taken)
    if not budget and _wpos:
        # a priority league (B&B): the number is your place in line. Last in
        # the standings is first on the wire every week — the other half of a tank.
        line = ("first in line every week while you're last — anyone you claim is yours" if _wpos == 1
                else f"in the waiver order — {_wpos - 1} team{'s' if _wpos != 2 else ''} claim before you")
        if top:
            line += f'. <b>{_esc_(top["name"])}</b> starts for you: {top["gain"]:+.1f} a week'
        if stash:
            line += (f'. Best stash for next year: <b>{_esc_(stash["name"])}</b>, projected #{stash["rank"]} '
                     f'and keepable at R{stash["cost"]}')
        st.markdown(C.hero_html(f"WAIVER PRIORITY · WEEK {g['week']}", f"#{_wpos}", line,
                                photo=_ph((top or stash or {}).get("pid")) if (top or stash) else None, tone="ink"),
                    unsafe_allow_html=True)
    elif top:
        b = FM.bid(meta, g["week"], top, budget, left, weeks_left) if budget else None
        how = (f'bid <b>${b["low"]}–{b["high"]}</b>' if (b and b.get("mode") != "priority") else "claim him")
        st.markdown(C.hero_html(kick, f'+{top["gain"]:.1f}',
                                f'a week from <b>{_esc_(top["name"])}</b> — {how}'
                                + (f', drop {_esc_(drop)}' if drop else ""), photo=_ph(top["pid"])),
                    unsafe_allow_html=True)
    else:
        line = "free agents would start for you — no claim this week"
        if close:
            line += f'. The closest is <b>{_esc_(close["name"])}</b>, {close["gain"]:+.1f}: a tiebreak'
        st.markdown(C.hero_html(kick, str(n_up), line, photo=_ph(close["pid"]) if close else None),
                    unsafe_allow_html=True)

    # the claim builder shows only when there's something to build
    from .. import userstate as US
    queued = US.claims(ctx["league_key"])
    if budget and (queued or top):
        _claim_builder(ctx, g, board, left, budget, weeks_left)

    # ---- everything else, folded ----------------------------------------------
    from .. import udk_waivers as UW
    wv = _udk_wv(g["season"], g["week"], reg)
    gain_of = _fa_gain_cached(ctx["league_key"], g["week"], _slow_bucket(g["season"], g["week"]),
                              ctx, g, frozenset(taken))
    _fa_list(ctx, g, board, taken, wv, gain_of, budget, left, weeks_left)
    with st.container(key="drawers"):
        if budget and not (queued or top):
            with _drawer("Your claims", "none queued"):
                _claim_builder(ctx, g, board, left, budget, weeks_left)
        if budget and getattr(meta, "platform", "") == "sleeper":
            _lk = ctx["league_key"]
            with _drawer("Every claim", "all seasons · sort by price, team, position", key=f"fh_{_lk}"):
                if _lazy(f"fh_{_lk}", "Load every FAAB claim in this league's history"):
                    _claims_history(ctx, g)
        rc = _waiver_recap(ctx, g) if budget else None
        if rc:
            rec, rrows, when_s = rc
            won = [r for r in rrows if r["won"]]
            summ = (f'won {len(won)} of {len(rrows)} · ${sum(r["bid"] for r in won)} spent'
                    + (f' · {won[0]["name"]}' if won else ""))
            with _drawer("Last waiver run", summ):
                st.markdown(C.waiver_recap_html(rec, when=when_s, left=left, budget=budget, rows=rrows),
                            unsafe_allow_html=True)

        _start_kd = [p for p in g["slots"] if p in ("K", "DST")]
        if (g.get("games") or {}) and _start_kd:
            with _drawer("Streaming", "defenses and kickers by this week's matchup"):
                _streaming(ctx, g, taken, wv, _start_kd)
        started = {str(p) for _, p in _lc["spots"] if p}
        krows = {r["pid"]: r for r in _keeper_rows(ctx, g)}
        safe = next((reg.meta(p).name for p in sorted(g["mine"], key=lambda x: float(g["proj"].get(x, 0) or 0))
                     if p not in started and not (krows.get(str(p)) and krows[str(p)]["verdict"] == "keep")), None)
        with _drawer("Drop candidates", (f"{safe} first" if safe else "") + " · keeper-aware"):
            _drop_list(ctx, g, started, krows)


@st.cache_data(ttl=600, show_spinner="Reading every waiver run…")
def _claims_cached(league_id: str, season: int) -> list:
    from .. import faabhistory as FH
    return FH.all_claims(league_id, season)


@st.cache_data(ttl=600, show_spinner=False)
def _faab_left_cached(league_id: str) -> dict:
    from .. import faabhistory as FH
    return FH.faab_left(league_id)


def _hot_claims(ctx, g, rows, seasons) -> None:
    """What a top-tier claim costs here, and how each team bids on one.

    A hot claim is one two or more teams put money on, or that went for 15%+
    of the budget. Per team: what it bid when it put money down, its biggest
    hot bid, and what it has left — a team can't bid more than that, so its
    likely ceiling is the smaller of the two. The line on top is the bid that
    beats every rival's ceiling, and the one that wins a typical hot claim."""
    from .. import faabhistory as FH
    meta, lk = ctx["meta"], ctx["league_key"]
    budget = int((inseason.faab(meta) or {}).get("budget") or 0) or 100
    opts = ["Since 2024", "All seasons"] if min(seasons) < 2024 else ["All seasons"]
    pick = st.segmented_control("Hot claims", opts, key=f"fh_hot_{lk}", selection_mode="single", default=opts[0],
                                on_change=_keep_open(f"fh_{lk}")) or opts[0]
    since = 2024 if pick == "Since 2024" else None
    m = FH.hot_market(rows, since)
    if not m["n"]:
        return
    prof = FH.hot_profiles(rows, since)
    left = _faab_left_cached(str(meta.league_id))
    me_name = next((b["team"] for r in rows for b in r["bids"] if str(b.get("user") or "") == str(g.get("me"))), None)
    usd = lambda share: int(round(share * budget))  # noqa: E731
    # each rival's likely ceiling: its biggest hot bid, but never more than it has left
    ceil = {}
    for t, p in prof.items():
        if t == me_name:
            continue
        cap = left.get(t)
        ceil[t] = min(usd(p["max"]), cap) if cap is not None else usd(p["max"])
    top_rival = max(ceil.items(), key=lambda kv: kv[1]) if ceil else None
    typical = usd(m["won_avg"] or 0)
    beat_most = usd(m["second_p90"] or 0) + 1
    line = (f'A top-tier claim here has gone for <b>${typical}</b> on average (median ${usd(m["won_med"] or 0)}, '
            f'top quarter ${usd(m["won_p75"] or 0)}+). The second bid — what the winner actually had to beat — '
            f'was under <b>${beat_most}</b> nine times in ten.')
    if top_rival:
        line += (f' To beat every rival\'s biggest hot bid (capped by what they have left), bid '
                 f'<b>${top_rival[1] + 1}</b> — {_esc_(top_rival[0])} is the one to beat.')
    st.markdown(f'<div class="ws-note">{line}</div>', unsafe_allow_html=True)
    rws = []
    for t, p in sorted(prof.items(), key=lambda kv: -kv[1]["avg_paid"]):
        tp = p["top"] or {}
        rws.append([f'<b>{_esc_(t)}</b>' + (' <span class="ws-dim">(you)</span>' if t == me_name else ""),
                    f'${left[t]}' if t in left else "—",
                    f'{p["n"]}', f'{p["wins"]}',
                    f'<b>${usd(p["avg_paid"])}</b>' if p["n_money"] else "—",
                    f'${usd(p["max"])}',
                    f'{_esc_(tp.get("name", ""))} <span class="ws-dim">{tp.get("season", "")} · ${tp.get("bid", "")}</span>' if tp else "",
                    "—" if t == me_name else f'${ceil.get(t, 0)}'])
    st.markdown(_tbl(["Team", "~FAAB left", "~Hot claims", "~Won", "~Avg bid", "~Biggest", "Biggest on", "~Can bid up to"], rws,
                     widths=["18%", "80px", "86px", "60px", "76px", "76px", "auto", "100px"], wide=True),
                unsafe_allow_html=True)
    _note(f"{m['n']} hot claims · bids in today's ${budget} budget (2023's $250 budget scaled down) · "
          "avg bid counts only the claims a team put money on · a team can't bid more than it has left")


def _claims_history(ctx, g) -> None:
    """Every FAAB claim the league has made, every season it ran FAAB: who won,
    what they paid, and who else bid what. Sorted by price by default — the
    whole history at once, since budgets changed ($250 in 2023) there's a
    share-of-budget sort too."""
    from .. import faabhistory as FH
    meta, lk = ctx["meta"], ctx["league_key"]
    rows = _claims_cached(str(meta.league_id), int(g["season"]))
    if not rows:
        _note("No FAAB claims on record for this league yet.")
        return
    seasons = sorted({r["season"] for r in rows}, reverse=True)
    _hot_claims(ctx, g, rows, seasons)
    teams = sorted({b["team"] for r in rows for b in r["bids"] if b["team"] and b["team"] != "?"}, key=str.lower)
    c = st.columns([2.2, 3.2, 2.2])
    s_lab = ["All"] + [str(x) for x in seasons]
    s_pick = c[0].segmented_control("Season", s_lab, key=f"fh_season_{lk}", selection_mode="single", default="All",
                                    on_change=_keep_open(f"fh_{lk}")) or "All"
    sort = c[1].segmented_control("Sort", list(FH.SORTS), key=f"fh_sort_{lk}", selection_mode="single", default="Price",
                                  on_change=_keep_open(f"fh_{lk}")) or "Price"
    pos = c[2].segmented_control("Pos", ["All", "QB", "RB", "WR", "TE", "K", "DEF"], key=f"fh_pos_{lk}",
                                 selection_mode="single", default="All", on_change=_keep_open(f"fh_{lk}")) or "All"
    c2 = st.columns([3, 2, 2])
    team = c2[0].selectbox("Team", ["All teams"] + teams, key=f"fh_team_{lk}", on_change=_keep_open(f"fh_{lk}"))
    q = c2[1].text_input("Player", key=f"fh_q_{lk}", placeholder="search a player", on_change=_keep_open(f"fh_{lk}"))
    failed = c2[2].toggle("Include claims nobody won", key=f"fh_failed_{lk}", on_change=_keep_open(f"fh_{lk}"))

    show = [r for r in rows if (failed or r["won"] is not None)
            and (s_pick == "All" or str(r["season"]) == s_pick)
            and (pos == "All" or r["pos"] == pos or (pos == "DEF" and r["pos"] in ("DEF", "DST")))
            and (team == "All teams" or any(b["team"] == team for b in r["bids"]))
            and (not q or q.strip().lower() in r["name"].lower())]
    show.sort(key=FH.SORTS.get(sort, FH.SORTS["Price"]))

    # one line per season: what the league spent and the claim that cost most
    summ = FH.summary([r for r in rows if s_pick == "All" or str(r["season"]) == s_pick])
    _tiles([(f"{s} · {v['n']} claims", f"${v['spent']:,}",
             f"of ${v['budget']} budgets · {v['free'] / v['n']:.0%} for $0 · top {v['top']['name']} ${v['top']['won']}",
             "var(--ink)") for s, v in summ.items()])

    me = str(g.get("me") or "")
    cap = 150
    full = st.session_state.get(f"fh_all_{lk}")
    vis = show if full else show[:cap]
    rws = []
    for i, r in enumerate(vis, 1):
        mine = me and str(r.get("winner_user") or "") == me
        others = [b for b in r["bids"] if not b["won"]]
        other_s = " · ".join(f'{_esc_(b["team"])} ${b["bid"]}' for b in others[:4]) + (f" · +{len(others) - 4}" if len(others) > 4 else "")
        win_s = (f'<b title="{_esc_(r.get("winner_team") or "")}">{_esc_(r["winner"] or "")}</b>' + (' <span class="ws-dim">(you)</span>' if mine else "")) \
            if r["won"] is not None else '<span class="ws-dim">nobody — every claim failed</span>'
        rws.append([str(i), f'{r["season"]} · W{r["week"]}',
                    f'<b>{_esc_(r["name"])}</b> <span class="ws-dim">{_esc_(r["pos"])}{(" " + _esc_(r["team"])) if r["team"] else ""}</span>',
                    win_s,
                    f'<b>${r["won"]}</b>' if r["won"] is not None else "—",
                    f'{r["pct"]:.0%}' if r["pct"] is not None else "—",
                    f'${r["runner_up"]}' if r["runner_up"] is not None else '<span class="ws-dim">—</span>',
                    other_s or '<span class="ws-dim">no other bids</span>',
                    str(r["bidders"])])
    _note(f"{len(show)} claim{'s' if len(show) != 1 else ''}" + (f" · showing the first {cap}" if len(show) > cap and not full else "")
          + " · hover a manager for that season's team name")
    st.markdown(_tbl(["#", "When", "Player", "Won by", "~Paid", "~% budget", "~2nd bid", "Other bids", "~Bids"], rws,
                     widths=["38px", "92px", "22%", "15%", "64px", "76px", "70px", "auto", "48px"], wide=True),
                unsafe_allow_html=True)
    if len(show) > cap and not full:
        st.button(f"Show all {len(show)}", key=f"fh_allbtn_{lk}",
                  on_click=lambda: (st.session_state.__setitem__(f"fh_all_{lk}", True),
                                    st.session_state.__setitem__(f"drawer_fh_{lk}", True)))


def _streaming(ctx, g, taken, wv, _start_kd) -> None:
    """The wire's defenses and kickers ranked by THIS week's matchup."""
    reg, games = ctx["registry"], g.get("games") or {}
    sc = st.columns(2)
    for col, pos in zip(sc, ("DST", "K")):
        if pos not in _start_kd:
            continue
        # Candidates come from the REGISTRY, not the projection map: ESPN's
        # weekly projections carry no kickers or defenses, so ranking from
        # the map showed his own two and nobody to stream for.
        cands, _seen = [], set()
        _want = (pos, "DEF") if pos == "DST" else (pos,)
        for pl in reg.by_norm.values():
            pid = str(getattr(pl, "sleeper_pid", "") or "")
            if not pid or pid in taken or pid in _seen:
                continue
            if (pl.position or "").upper() not in _want or not pl.team:
                continue
            _seen.add(pid)
            cands.append({"pid": pid, "name": pl.name, "team": pl.team,
                          "proj": float(g["proj"].get(pid, 0) or 0)})
        # yours, for the comparison row
        mine_pos = [p for p in g["mine"]
                    if (reg.meta(p).position or "").upper() in ((pos, "DEF") if pos == "DST" else (pos,))]
        ranked = WV.stream_rank(cands, reg, games, pos)[:6]
        mine_r = WV.stream_rank([{"pid": p, "name": reg.meta(p).name, "team": reg.meta(p).team,
                                  "proj": float(g["proj"].get(p, 0) or 0)} for p in mine_pos],
                                reg, games, pos)
        rws = []
        for r in (mine_r + ranked):
            own = r["pid"] in set(mine_pos)
            imp = "—" if r["implied"] is None else f'{r["implied"]:.1f}'
            edge = ("" if r["edge"] is None else
                    _chip(f'{r["edge"]:+.1f}', "ok" if r["edge"] > 1 else "warn" if r["edge"] > -1 else "bad"))
            _sw = (wv or {}).get(str(r["pid"]))
            rws.append([(f'<b>{r["name"]}</b>' if own else r["name"])
                        + (" " + _chip("yours", "acc") if own else "")
                        + (" " + _chip(f'Ballers #{int(_sw["consensus"])}', "ok")
                           if (_sw and _sw.get("consensus")) else ""),
                        f'{r["opp"]} · {r["day"]}', imp, f'{r["proj"]:.1f}', edge])
        with col:
            st.markdown(_tbl(["", "Game", ("Opp implied" if pos == "DST" else "Own implied"),
                              "~Proj", "Edge"], rws,
                             widths=["auto", "118px", "78px", "56px", "64px"]),
                        unsafe_allow_html=True)
    _note("**Opp implied** is the points Vegas expects the defense to give up — lower is "
               "better for a D/ST. **Own implied** is the points a kicker's own team is expected "
               "to score — a kicker on a favourite gets attempts. Edge is the gap from a 22-point "
               "average game.")



def _drop_list(ctx, g, started, krows) -> None:
    """Bench men, lowest projection first, with what dropping each costs next year."""
    reg = ctx["registry"]
    rws = []
    for p in sorted(g["mine"], key=lambda x: float(g["proj"].get(x, 0) or 0)):
        if p in started:
            continue
        r = krows.get(str(p))
        pm = reg.meta(p)
        if r and r["verdict"] == "keep":
            verdict = _chip(f'keeper +{r["surplus"]} — hold', "bad")
        elif r and (r["surplus"] or -99) > -5:
            verdict = _chip(f'next keeper up (R{r["cost_round"]})', "warn")
        else:
            verdict = _chip("safe drop", "ok")
        rws.append([f'{pm.name} {_pos_pill(pm.position)}',
                    f'{float(g["proj"].get(p,0) or 0):.1f}', verdict])
        if len(rws) >= 5:
            break
    st.markdown(_tbl(["Player", "~Proj", "Verdict"], rws), unsafe_allow_html=True)
    _note("Dropping a cheap keeper is a next-season decision disguised as a roster move.")




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
    _gap = mm - om
    # Once a game has kicked off, the board shows the SCORE: actual points, how
    # much of each side has played, and where it projects to end.
    games, phase, live = g.get("games") or {}, g.get("phase") or "setup", g.get("live") or {}
    started = phase in ("live", "late", "done") and bool(games)
    me_live, opp_live = live.get(str(g["me"])) or {}, live.get(str(oid)) or {}
    mcur = list(zip(g["slots"], g["starters"]))
    ocur = list(zip(g["slots"], ost))
    ps, ops = (WV.played_state(mcur, reg, games, me_live), WV.played_state(ocur, reg, games, opp_live))
    ws = W.weakest_slot(opp, g["slots"], g["proj"], reg, byes=g["byes"], week=g["week"])
    _sw = swing[0] if swing else None
    _tiles_m = [
        ("Margin", f"{_gap:+.1f}", "projected, lineups as set"),
        ("The game", (_sw["name"].split()[-1] if _sw else "—"),
         (f'{_sw["swing"]} pts of win % on him' if _sw else "")),
        ("If both play best", f"{100*wp_best:.0f}%", f"{bm:.1f} – {obm:.1f}"),
        ("Their soft spot", (ws[0] if ws else "—"),
         (f"{reg.meta(ws[2]).name} {ws[1]:.1f}" if ws else "")),
    ]
    if started:
        me_now, opp_now = float(me_live.get("points") or 0), float(opp_live.get("points") or 0)
        me_end = WV.live_projection(mcur, g["proj"], reg, games, me_live)
        opp_end = WV.live_projection(ocur, g["proj"], reg, games, opp_live)
        wp_now = W.win_prob(me_end, ms * 0.7, opp_end, os_ * 0.7)
        _tiles_m[0] = ("Projected final", f"{me_end:.0f} – {opp_end:.0f}", f"was {100*wp:.0f}% at kickoff")
        _sb = dict(me_pts=f"{me_now:.1f}", opp_pts=f"{opp_now:.1f}", win_pct=100 * wp_now,
                   label=("FINAL" if phase == "done" else "LIVE") + f' · WEEK {g["week"]}',
                   me_sub=_dpc(ps), opp_sub=_dpc(ops))
    else:
        _sb = dict(me_pts=f"{mm:.1f}", opp_pts=f"{om:.1f}", win_pct=100 * wp,
                   label=f'PROJECTED · WEEK {g["week"]}',
                   me_sub=f"set lineup · {ms:.0f}-pt spread", opp_sub=f"set lineup · {os_:.0f}-pt spread")
    if started:
        _fk = f"mu_prev_{ctx['league_key']}"
        _sb["flaps"] = st.session_state.get(_fk) or (_sb["me_pts"], _sb["opp_pts"])
        st.session_state[_fk] = (_sb["me_pts"], _sb["opp_pts"])
    st.markdown(C.scoreboard_html(
        me_name="You", me_rec=_record(g, g["me"]), me_photo=_top_photo(reg, g, g["starters"]),
        opp_name=them, opp_rec=_record(g, oid), opp_photo=_top_photo(reg, g, ost),
        tiles=_tiles_m, **_sb), unsafe_allow_html=True)
    # the two lineups as towers, position by position, projected
    try:
        def _by_pos(pids, lv):
            out = {}
            for p_ in pids or []:
                if not p_ or str(p_) == "0":
                    continue
                ps_ = (reg.meta(str(p_)).position or "").upper()
                ps_ = "DEF" if ps_ in ("DST", "D/ST") else ps_
                # once games are on: the same "where it ends" as the scoreboard
                v = (WV.live_projection([("", p_)], g["proj"], reg, games, lv) if started
                     else float(g["proj"].get(str(p_), 0) or 0))
                out[ps_] = out.get(ps_, 0.0) + v
            return out
        _tw = st.segmented_control("Towers", ["By position", "By slot"], key=f"mu_tw_{ctx['league_key']}",
                                   selection_mode="single", default="By position",
                                   label_visibility="collapsed") or "By position"

        def _pv(p_, lv):
            if not p_ or str(p_) == "0":
                return 0.0
            return (WV.live_projection([("", p_)], g["proj"], reg, games, lv) if started
                    else float(g["proj"].get(str(p_), 0) or 0))
        if _tw == "By slot":
            # slot against slot: his QB against yours, RB1 against RB1
            _seen, _groups = {}, []
            for s_, a_, b_ in zip(g["slots"], g["starters"], ost):
                if s_ in ("BN", "IR", "TAXI"):
                    continue
                _seen[s_] = _seen.get(s_, 0) + 1
                _lab = s_ if g["slots"].count(s_) == 1 else f"{s_}{_seen[s_]}"
                _groups.append((_lab.replace("SUPER_FLEX", "SF"), _pv(a_, me_live), _pv(b_, opp_live)))
            _order = []
        else:
            _groups = None
        _a, _b = _by_pos(g["starters"], me_live), _by_pos(ost, opp_live)
        _order = [x for x in ("QB", "RB", "WR", "TE", "K", "DEF") if x in _a or x in _b]
        if _groups:
            st.markdown(C.towers_html(_groups, me="You", them=them,
                                      note="slot against slot — " + ("actual so far plus the rest" if started else "projected")),
                        unsafe_allow_html=True)
        elif _order:
            st.markdown(C.towers_html([(x, _a.get(x, 0.0), _b.get(x, 0.0)) for x in _order],
                                      me="You", them=them,
                                      note="projected finish by position — actual so far plus the rest"
                                      if started else "projected points by position"), unsafe_allow_html=True)
    except Exception:  # noqa: BLE001 — a picture, never worth the tab
        pass
    if started:
        st.markdown(C.still_to_play_html([
            (f'Yours still to play · {len(ps["pre"]) + len(ps["live"])}',
             _still_rows(mcur, reg, g, me_live, g["proj"])),
            (f'Theirs still to play · {len(ops["pre"]) + len(ops["live"])}',
             _still_rows(ocur, reg, g, opp_live, g["proj"])),
        ]), unsafe_allow_html=True)
    _plat = "ESPN" if ctx["meta"].platform == "espn" else "Sleeper"
    _note(f"Both lineups as currently **set** on {_plat}. Play your best lineup and he plays "
               f"his and it's {bm:.1f} – {obm:.1f}, {100*wp_best:.0f}% you. Win probability treats "
               f"each team total as a normal distribution — the spread comes from position-level "
               f"weekly variance, so a boom/bust roster reads differently from a steady one with "
               f"the same projection.")

    c1, c2 = st.columns([1.25, 1])
    with c1:
        st.markdown('<div class="ws-h">Slot by slot</div>', unsafe_allow_html=True)
        # ["current"], not ["spots"] — "spots" is the OPTIMAL lineup, and this
        # column has to name the men who will actually be on the field.
        ml = W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"],
                            current=g["starters"])["current"]
        ol = W.lineup_check(opp, g["slots"], g["proj"], reg, g["byes"], g["week"],
                            current=ost)["current"]
        rows, empty = [], []
        for (s_, a), (_s2, b) in zip(ml, ol):
            pa = float(g["proj"].get(str(a), 0) or 0) if a else 0.0
            pb = float(g["proj"].get(str(b), 0) or 0) if b else 0.0
            rows.append((s_, reg.meta(a).name if a else "", pa, reg.meta(b).name if b else "", pb))
            if b and pb == 0:
                empty.append(reg.meta(b).name)
        st.markdown(C.slot_rows_html(rows), unsafe_allow_html=True)
        if empty:
            st.markdown(C.callout_html(
                f"{len(empty)} of {_esc_(them)}'s starters project <b>0.0</b> — {_esc_(', '.join(empty))}. "
                f"If {'they stay' if len(empty) > 1 else 'that slot stays'} empty, that's points you don't have to earn."),
                unsafe_allow_html=True)
        if weak:
            st.markdown(C.callout_html(
                f"<b>Your {weak[0]} slot projects {weak[1]:.1f}</b> — your weakest starter, and the first "
                f"place a waiver add pays."), unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="ws-h">Whose week decides it</div>', unsafe_allow_html=True)
        sw = W.swing_players(g["mine"], opp, g["slots"], g["proj"], reg,
                             byes=g["byes"], week=g["week"], top=4)
        for s_ in sw:
            try:
                s_["photo"] = getattr(reg.meta(s_["pid"]), "sleeper_pid", None) or s_["pid"]
            except Exception:  # noqa: BLE001
                pass
        st.markdown(C.swing_cards_html(sw, them), unsafe_allow_html=True)
        if ws:
            st.markdown(C.callout_html(
                f"<b>Their soft spot is {ws[0]}.</b> {_esc_(reg.meta(ws[2]).name)} projects {ws[1]:.1f} — "
                f"beat that slot and you probably win the week.", red=True), unsafe_allow_html=True)


# -------------------------------------------------------------------- 4 trades
_NEXT_ADP: dict = {}


def _next_adp(ctx):
    """adp_rank(name, pos) for keeper prices: the PROJECTED next-season ADP
    (draftkit.nextyear), falling back to this season's ADP for anyone the
    projection doesn't price. A keeper's ADP option is next summer's price."""
    import time as _t
    from .. import nextyear as NY
    meta = ctx["meta"]
    w = getattr(meta, "scoring_weights", None) or {}
    rec = float(w.get("rec", 1.0 if meta.scoring == "ppr" else 0.5 if meta.scoring == "half" else 0.0))
    ppr = 1.0 if rec >= 0.75 else 0.5 if rec >= 0.25 else 0.0
    key = (int(getattr(meta, "num_teams", 10) or 10), ppr, int(_t.time() // 3600))
    if key not in _NEXT_ADP:
        try:
            _NEXT_ADP.clear()
            _NEXT_ADP[key] = NY.rank_lookup(ctx["registry"], key[0], ppr)
        except Exception:  # noqa: BLE001
            _NEXT_ADP[key] = lambda name, position="": None
    nxt, cur = _NEXT_ADP[key], ctx["adp_rank"]

    def lookup(name, position=""):
        v = nxt(name, position)
        return v if v is not None else cur(name, position)
    return lookup


def _keeper_rows(ctx, g, pids=None, from_owner=None, as_owner=None) -> list:
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
        rules["_last_round"] = K.price_rounds(rules, int(g["season"]), meta.draft_rounds)
        rules["_adp_policy"] = K.adp_policy(str(meta.league_id))
        raw = K.load_keepers(str(meta.league_id), g["season"]) or {}
        who = str(as_owner or g["me"])
        existing = {str(k.get("player_id")): k for k in (raw.get(who) or [])}
        if pids is None and as_owner is not None:
            pids = list((g["rosters"].get(who) or {}).get("players") or [])
        if from_owner is not None:
            # a player coming over in a trade brings his keeper years with him
            for k in raw.get(str(from_owner)) or []:
                existing.setdefault(str(k.get("player_id")), k)
        # a dropped keeper is a free agent with his clock still running — his
        # record is in the season's file under whoever filed him, not on a roster
        if pids is not None:
            hist = K.keeper_history(str(meta.league_id), g["season"])
            for q in pids:
                if str(q) in hist:
                    existing.setdefault(str(q), hist[str(q)])
        return W.keeper_outlook(
            list(pids) if pids is not None else g["mine"], drafted_round=_draft_rounds(str(meta.league_id)), me=who,
            existing=existing, rules=rules, n_teams=meta.num_teams,
            adp_rank=_next_adp(ctx), registry=reg, proj=g["proj"],
            next_season=int(g["season"]) + 1, league_kept=raw,
            owned_rounds=_owned_rounds(ctx, g, who))
    except Exception:  # noqa: BLE001 — a missing keeper config must not break a tab
        return []


def _owned_rounds(ctx, g, owner) -> Optional[dict]:
    """{round: count} of NEXT season's picks this manager holds, or None when
    the league's picks aren't known (then no keeper is blocked for it)."""
    nxt = int(g["season"]) + 1
    out: dict = {}
    for pk in _pick_menu(ctx, g, owner).values():
        try:
            if int(pk.get("season")) == nxt:
                out[int(pk["round"])] = out.get(int(pk["round"]), 0) + 1
        except Exception:  # noqa: BLE001
            continue
    return out or None


def _keep_list(ctx, g) -> dict:
    """{pid: surplus} for the players keeper_outlook says to keep.

    The trade screen scores lineups. In a keeper league that is only half the
    ledger: a deal can raise your week by 2 points while handing away a player who
    costs a last-round pick and is worth an early one. Marking those keeps the
    "both win" verdict honest — it is a verdict about THIS WEEK.
    """
    return {r["pid"]: r["surplus"] for r in _keeper_rows(ctx, g)
            if r["verdict"] == "keep" and r["surplus"] is not None}


# ------------------------------------------------------- tank / contend mode
@st.cache_data(ttl=1800, show_spinner=False, max_entries=8)
def _league_status_cached(lk: str, week: int, bucket: int, _ctx, _g) -> dict:
    """{owner: {odds, seed}} — every team's playoff odds on the real schedule."""
    si = _sim_inputs(_ctx, _g)
    if not si["fx"]:
        return {}
    sim = W.season_sim(si["means"], si["sds"], si["recs"], si["pf"],
                       {int(k): v for k, v in si["fx"].items()}, si["pt"], str(_g["me"]),
                       n_sims=3000, median=si["median"])
    return {o: {"odds": v["playoff_pct"], "seed": v["avg_seed"]} for o, v in (sim.get("teams") or {}).items()}


@st.cache_data(ttl=1800, show_spinner=False, max_entries=8)
def _ros_ppg_cached(season: int, week: int, scoring: str, wkey: str, _weights) -> dict:
    from .. import ros as R
    return R.sleeper(season, week, scoring, _weights)


def _mode(ctx, g, status) -> tuple:
    """(setting, resolved): what he picked, and what it means right now."""
    from .. import userstate as US
    setting = US.league_mode(ctx["league_key"])
    if setting != "auto":
        return setting, setting
    odds = (status.get(str(g["me"])) or {}).get("odds")
    if odds is None:
        return setting, "balanced"
    return setting, ("contend" if odds >= 40 else "tank" if odds <= 12 else "balanced")


def _win_now(ctx, g) -> dict:
    """{pid: {ppg, games, par}} — rest-of-season points a game, games left, and
    the season's worth ABOVE a replacement starter at his position (what a
    contender actually gains by having him)."""
    meta, reg = ctx["meta"], ctx["registry"]
    w = getattr(meta, "scoring_weights", None)
    ros = _ros_ppg_cached(int(g["season"]), int(g["week"]), meta.scoring,
                          str(sorted((w or {}).items())), w) or {}
    rostered = [str(p) for r in g["rosters"].values() for p in (r.get("players") or [])]
    by_pos: dict = {}
    vals = {}
    for p in rostered:
        r = ros.get(p) or {}
        games = int(r.get("games") or 0)
        ppg = (float(r.get("pts") or 0) / games) if games else 0.0
        pos = (reg.meta(p).position or "").upper()
        vals[p] = {"ppg": ppg, "games": games, "pos": pos}
        by_pos.setdefault(pos, []).append(ppg)
    n = max(2, int(getattr(meta, "num_teams", 10) or 10))
    depth = {"QB": 1.0, "RB": 2.5, "WR": 3.0, "TE": 1.0}
    repl = {}
    for pos, xs in by_pos.items():
        xs = sorted(xs, reverse=True)
        k = int(round(n * depth.get(pos, 1.0)))
        repl[pos] = xs[min(len(xs) - 1, k)] if xs else 0.0
    for p, v in vals.items():
        v["par"] = max(0.0, v["ppg"] - repl.get(v["pos"], 0.0)) * v["games"]
    return vals


def _sellables(ctx, g, vals=None, my_k=None) -> list:
    """[(pid, win-now, keeper row)] — your players with real rest-of-season value
    to a contender who aren't one of your cheap keepers. Tank mode's sell list."""
    vals = vals if vals is not None else _win_now(ctx, g)
    my_k = my_k if my_k is not None else {r["pid"]: r for r in _keeper_rows(ctx, g)}
    out = []
    for p in g["mine"]:
        v = vals.get(str(p)) or {}
        k = my_k.get(str(p))
        if (v.get("par") or 0) <= 5:
            continue
        # anyone in your keeper five with real value is next year's team — the
        # thing a tank is FOR; selling him for a pick is a different trade
        if k and k.get("verdict") == "keep" and (k.get("surplus") or 0) >= 8:
            continue
        out.append((str(p), v, k))
    out.sort(key=lambda t: -t[1]["par"])
    return out


def _lottery_block(ctx, g) -> None:
    """Next season's draft lottery for a league that has one (B&B): where you
    land as you are, and after selling the sell list."""
    from .. import lottery as LT
    spec = K.lottery_spec(str(ctx["meta"].league_id))
    if not spec or spec.get("style", "chase") != "chase":
        return
    si = _sim_inputs(ctx, g)
    if not si["fx"]:
        return
    me, reg = str(g["me"]), ctx["registry"]
    fx = {int(k): v for k, v in si["fx"].items()}
    base = LT.simulate(si["means"], si["sds"], si["recs"], si["pf"], fx, si["pt"], spec["weights"], me,
                       chase_teams=spec.get("chase_teams", 4), median=si["median"])
    sell = [p for p, _v, _k in _sellables(ctx, g)]
    sold = None
    if sell:
        means, sds = dict(si["means"]), dict(si["sds"])
        left = [p for p in g["mine"] if str(p) not in set(sell)]
        means[me], sds[me] = W.team_distribution(left, g["slots"], g["proj"], reg, g["byes"], g["week"])
        sold = LT.simulate(means, sds, si["recs"], si["pf"], fx, si["pt"], spec["weights"], me,
                           chase_teams=spec.get("chase_teams", 4), median=si["median"])
    if not base:
        return
    lo, hi = base["chase_seeds"]
    names = ", ".join(reg.meta(p).name for p in sell[:3]) + (" …" if len(sell) > 3 else "")
    rows = [("As you are", base)] + ([(f"After selling {len(sell)} ({names})", sold)] if sold else [])
    st.markdown(C.lottery_html(rows, weights=spec["weights"], chase=(lo, hi), season=int(g["season"]) + 1),
                unsafe_allow_html=True)
    _priority_note(ctx, g)


def _priority_note(ctx, g) -> None:
    """In a reverse-standings waiver league, last place is also first on the wire
    every week — the other thing a tank buys, and the way to stock next year's
    cheap keepers (a waiver add keeps at the last round)."""
    meta = ctx["meta"]
    if inseason.faab(meta):
        return
    pos = inseason.waiver_position(meta, str(g["me"]))
    if pos == 1:
        _note("**You're #1 on waivers.** This league runs reverse-standings priority, so staying last "
              "keeps you first in line every week — any free agent you want is yours. Use it on players "
              "who'd be cheap keepers next year: a waiver add keeps at the last round (Waivers → the 2027 column).")
    elif pos:
        _note(f"You're #{pos} on waivers (reverse standings) — finishing lower moves you up the line.")


def _prefill_button(ctx, label: str, key: str, oid: str, send=(), get=(), sendp=(), getp=(),
                    primary: bool = False) -> None:
    """Load a suggestion into the trade checker below (partner + both sides)."""
    if st.button(label, key=key, use_container_width=True, type="primary" if primary else "secondary"):
        st.session_state[f"td_prefill_{ctx['league_key']}"] = {
            "oid": str(oid), "send": list(send), "get": list(get),
            "sendp": list(sendp), "getp": list(getp)}
        rerun_here()


def _mode_panel(ctx, g, status, resolved) -> None:
    """Tank: who to sell, to whom, for what. Contend: who to buy from sellers."""
    from .. import userstate as US
    reg, lk = ctx["registry"], ctx["league_key"]
    me = str(g["me"])
    vals = _win_now(ctx, g)
    weeks_left = max(1, 14 - int(g["week"]))
    base = {o: W.team_distribution(r["players"], g["slots"], g["proj"], reg, g["byes"], g["week"])[0]
            for o, r in g["rosters"].items() if r.get("players")}
    my_k = {r["pid"]: r for r in _keeper_rows(ctx, g)}
    started = {str(p) for _s, p in W.lineup_check(g["mine"], g["slots"], g["proj"], reg,
                                                  g["byes"], g["week"])["spots"] if p}

    def pick_labels(owner, max_round=4, min_round=1):
        menu = _pick_menu(ctx, g, owner)
        return [lab for lab, pk in sorted(menu.items(), key=lambda kv: (kv[1]["season"], kv[1]["round"]))
                if min_round <= int(pk["round"]) <= max_round]

    def fair_round(season_pts: float) -> int:
        """Roughly what a rest-of-season of +N points over replacement fetches:
        a difference-maker a 1st/2nd, a useful starter a 3rd, a depth piece a 4th.
        A starting point for the ask — the checker below judges the real offer."""
        return 1 if season_pts >= 90 else 2 if season_pts >= 50 else 3 if season_pts >= 25 else 4

    if resolved == "tank":
        buyers = sorted([o for o, v in status.items() if o != me and v["odds"] >= 35],
                        key=lambda o: -status[o]["odds"])
        if not buyers:
            _note("No team is a clear contender yet (35%+ to make it), so there's nobody to sell to.")
            return
        sell = _sellables(ctx, g, vals, my_k)
        _my = (status.get(me) or {}).get("odds")
        st.markdown(C.hero_html(f"TANK · {_my}% TO MAKE IT" if _my is not None else "TANK",
                                str(len(buyers)), "contenders who'd pay for what you have",
                                photo=(sell[0][0] if sell else None), red=True), unsafe_allow_html=True)
        _priority_note(ctx, g)
        if not sell:
            _note("Nothing on your roster is worth much to a contender that you aren't keeping.")
            return
        st.markdown('<div class="ws-h">Sell to contenders</div>', unsafe_allow_html=True)
        their_k: dict = {}
        for pid, v, k in sell[:6]:
            pm = reg.meta(pid)
            fits = []
            for o in buyers:
                gain = W.team_distribution(list(g["rosters"][o]["players"]) + [pid], g["slots"], g["proj"],
                                           reg, g["byes"], g["week"])[0] - base.get(o, 0)
                fits.append((gain, o))
            fits.sort(reverse=True)
            gain, o = fits[0]
            if o not in their_k:
                their_k[o] = [r for r in (_all_keeper_rows(ctx, g).get(o) or [])
                              if (r.get("surplus") or 0) >= 10 and not r.get("blocked")]
            theirs_start = {str(q) for _s, q in W.lineup_check(g["rosters"][o]["players"], g["slots"],
                                                               g["proj"], reg, g["byes"], g["week"])["spots"] if q}
            kt = [r for r in their_k[o] if str(r["pid"]) not in theirs_start][:2]
            rnd = fair_round(v["par"])
            picks = pick_labels(o, max_round=rnd + 1, min_round=rnd)[:3] or pick_labels(o, min_round=rnd)[:3]
            ktxt = (f'keeps R{k["cost_round"]} for you, {k["surplus"]:+d}' if k and k.get("cost_round")
                    else "not one of your keepers")
            ask = " · ".join([f"<b>{_esc_(x)}</b>" for x in picks[:2]] +
                             [f'<b>{_esc_(reg.meta(r["pid"]).name)}</b> (R{r["cost_round"]} keeper, +{r["surplus"]})'
                              for r in kt])
            _ph = getattr(pm, "sleeper_pid", None) or pid
            st.markdown(C.trade_card_html(
                pid=_ph, tone="sell",
                kick=f"SELL TO {_owner_name(ctx, o).upper()} · {status[o]['odds']}% PLAYOFFS · {ktxt.upper()}",
                title=f"{pm.name}",
                body=(f'{pm.position} · {v["ppg"]:.1f} a game rest of season. Ask for: {ask or "their best future pick"}.'
                      + (f' Also fits: {", ".join(_owner_name(ctx, x) for _g2, x in fits[1:3])}.' if len(fits) > 1 else "")),
                num=f"{gain:+.1f}", num_sub="a week for them"), unsafe_allow_html=True)
            with st.container(key=f"tcact_{lk}_{pid}"):
                c = st.columns(3)
                if picks:
                    with c[0]:
                        _prefill_button(ctx, f"Ask for {picks[0]}", f"tk_{lk}_{pid}_p", o,
                                        send=[pm.name], getp=[picks[0]], primary=True)
                for i, r in enumerate(kt[:2], 1):
                    with c[i]:
                        _prefill_button(ctx, f'Ask for {reg.meta(r["pid"]).name.split()[-1]}',
                                        f'tk_{lk}_{pid}_{r["pid"]}', o, send=[pm.name],
                                        get=[reg.meta(r["pid"]).name], primary=not picks and i == 1)
        return

    if resolved == "contend":
        tanking = set(US.tankers(lk))
        sellers = sorted([o for o, v in status.items() if o != me and (v["odds"] <= 15 or o in tanking)],
                         key=lambda o: status[o]["odds"])
        if not sellers:
            _note("No team is out of it yet (under 15%) and none is marked as tanking — "
                  "mark the ones you know are below.")
            return
        st.markdown('<div class="ws-h">Buy from teams that are out of it</div>', unsafe_allow_html=True)
        targets = []
        for o in sellers:
            tk = {str(r["pid"]): r for r in (_all_keeper_rows(ctx, g).get(o) or [])}
            for p in g["rosters"][o]["players"]:
                v = vals.get(str(p)) or {}
                if (v.get("par") or 0) <= 5:
                    continue
                gain = W.team_distribution(list(g["mine"]) + [str(p)], g["slots"], g["proj"], reg,
                                           g["byes"], g["week"])[0] - base.get(me, 0)
                if gain < 0.5:
                    continue
                k = tk.get(str(p))
                rental = not (k and k.get("verdict") == "keep")
                targets.append((gain, str(p), o, v, k, rental))
        targets.sort(key=lambda t: (-(t[0] * (1.3 if t[5] else 1.0))))
        _my = (status.get(me) or {}).get("odds")
        st.markdown(C.hero_html(f"CONTEND · {_my}% TO MAKE IT" if _my is not None else "CONTEND",
                                str(len(sellers)),
                                f"team{'s' if len(sellers) != 1 else ''} out of it and selling"
                                + (f' — <b>{_esc_(reg.meta(targets[0][1]).name)}</b> adds {targets[0][0]:+.1f} a week'
                                   if targets else ""),
                                photo=(targets[0][1] if targets else None)), unsafe_allow_html=True)
        if not targets:
            _note("Nobody on those rosters would start for you.")
            return
        my_picks_all = pick_labels(me, max_round=6)
        # what a rebuilding team wants that a contender can spare: keeper value
        # OUTSIDE your best five (those are next year's team) and off this
        # week's lineup
        spare = sorted([r for r in my_k.values() if (r.get("surplus") or 0) > 0
                        and r.get("verdict") != "keep" and str(r["pid"]) not in started
                        and not r.get("blocked")], key=lambda r: -(r.get("surplus") or 0))[:2]
        for gain, pid, o, v, k, rental in targets[:6]:
            pm = reg.meta(pid)
            rnd = fair_round(gain * weeks_left) + (0 if rental else -1)
            rnd = max(1, rnd)
            offer_picks = ([x for x in my_picks_all if f" R{rnd}" in x][:1]
                           + [x for x in my_picks_all if f" R{rnd + 1}" in x][:1]) or my_picks_all[-2:]
            why = ("he isn't one of their keepers — a rental they should sell" if rental else
                   f'he\'s a keeper for them (R{k["cost_round"]}, +{k["surplus"]}) — it will cost more')
            offer = " · ".join([f"<b>{_esc_(x)}</b>" for x in offer_picks[:2]] +
                               [f'<b>{_esc_(reg.meta(r["pid"]).name)}</b> (keeps R{r["cost_round"]})' for r in spare])
            _ph = getattr(pm, "sleeper_pid", None) or pid
            st.markdown(C.trade_card_html(
                pid=_ph, tone="buy",
                kick=f'FROM {_owner_name(ctx, o).upper()} · {status[o]["odds"]}% PLAYOFFS · {"RENTAL" if rental else "THEIR KEEPER"}',
                title=f"{pm.name}",
                body=(f'{pm.position} · {v["ppg"]:.1f} a game rest of season, <b>{gain * weeks_left:+.0f}</b> over '
                      f'the rest of the season. {why[:1].upper() + why[1:]}. Offer: {offer or "a future pick"}.'),
                num=f"{gain:+.1f}", num_sub="a week for you"), unsafe_allow_html=True)
            with st.container(key=f"tcact_{lk}_{pid}"):
                c = st.columns(3)
                for i, lab in enumerate(offer_picks[:2]):
                    with c[i]:
                        _prefill_button(ctx, f"Offer {lab}", f"ct_{lk}_{pid}_{i}", o, get=[pm.name], sendp=[lab],
                                        primary=(i == 0))
                if spare:
                    with c[2]:
                        _prefill_button(ctx, f'Offer {reg.meta(spare[0]["pid"]).name.split()[-1]}',
                                        f"ct_{lk}_{pid}_s", o, get=[pm.name],
                                        send=[reg.meta(spare[0]["pid"]).name], primary=not offer_picks)
        return
    _note("You're on the bubble, so the Trades tab looks both ways — proposals below are scored on "
          "this week; switch to Contend or Tank to aim it.")



# ---------------------------------------------------- byes & playoff weeks
def _bye_planner(ctx, g) -> None:
    """Every starter's bye through the last playoff week, the weeks you're
    short, and who could cover each: a rental on a team that's out of it, or a
    free agent who plays that week."""
    reg, meta = ctx["registry"], ctx["meta"]
    byes = g.get("byes") or {}
    wks = SCH.playoff_weeks(meta)
    last = (wks[-1] if wks else 17)
    weeks = list(range(int(g["week"]), last + 1))
    if not weeks or not byes:
        return
    lc = W.lineup_check(g["mine"], g["slots"], g["proj"], reg, g["byes"], g["week"])
    starters = [(sl, str(p)) for sl, p in lc["spots"] if p]
    rows, outs = [], {w: [] for w in weeks}
    for sl, p in starters:
        pm = reg.meta(p)
        b = byes.get((pm.team or "").upper())
        rows.append((sl, pm.name, pm.position, b))
        if b in outs:
            outs[b].append((pm.position, pm.name))
    # who could cover a hole: rentals on teams that are out of it, then free agents
    try:
        status = _league_status_cached(ctx["league_key"], g["week"], _slow_bucket(g["season"], g["week"]), ctx, g)
    except Exception:  # noqa: BLE001
        status = {}
    w8 = getattr(meta, "scoring_weights", None)
    ros = _ros_ppg_cached(int(g["season"]), int(g["week"]), meta.scoring, str(sorted((w8 or {}).items())), w8) or {}
    owner_of = {str(q): str(o) for o, r in g["rosters"].items() for q in (r.get("players") or [])}
    sellers = {o for o, v in status.items() if o != str(g["me"]) and v["odds"] <= 15}

    def cover(pos, week):
        best = []
        for pid, r in ros.items():
            try:
                pm = reg.meta(pid)
            except Exception:  # noqa: BLE001
                continue
            if (pm.position or "").upper() != pos or byes.get((pm.team or "").upper()) == week:
                continue
            o = owner_of.get(str(pid))
            if o and o not in sellers:
                continue
            games = int(r.get("games") or 0)
            if not games:
                continue
            best.append((float(r.get("pts") or 0) / games, pm.name, o))
        best.sort(reverse=True)
        return best[:2]
    po = set(wks or [])
    grid = []
    for sl, name, pos, b in rows:
        cells = "".join(f'<td class="{"po" if w in po else ""}{" bye" if w == b else ""}">'
                        f'{"BYE" if w == b else "<i></i>"}</td>' for w in weeks)
        grid.append(f'<tr><td class="nm"><span class="bp-ps">{_esc_(sl)}</span>{_esc_(name)}</td>{cells}</tr>')
    tot = "".join(f'<td class="{"po" if w in po else ""}{" bad" if len(outs[w]) >= 3 or (outs[w] and w in po) else " warn" if len(outs[w]) == 2 else ""}">'
                  f'{len(outs[w]) or ""}</td>' for w in weeks)
    head = "".join(f'<th class="{"po" if w in po else ""}">{w}</th>' for w in weeks)
    worst = max(weeks, key=lambda w: (len(outs[w]) + (2 if w in po else 0)) if outs[w] else -1)
    sev = outs.get(worst) or []
    lead = ""
    if sev:
        names = ", ".join(n for _p, n in sev)
        lead = (f'<div class="bp-lead"><b>Week {worst}</b>{" — a playoff week" if worst in po else ""}: '
                f'{_esc_(names)} {"is" if len(sev) == 1 else "are"} on bye.</div>')
    fixes = []
    for w in weeks:
        if not outs[w] or (len(outs[w]) < 2 and w not in po):
            continue
        for pos, name in outs[w]:
            c = cover(pos, w)
            if c:
                opts = " · ".join(f'<b>{_esc_(n)}</b> ({ppg:.1f}/g, {"free agent" if not o else _owner_name(ctx, o) + ", out of it"})'
                                  for ppg, n, o in c)
                fixes.append(f'<div class="bp-fix"><span>Wk {w} · {_esc_(pos)}</span><div>for {_esc_(name)}: {opts}</div></div>')
    st.markdown('<div class="bp">' + lead
                + f'<table class="bp-g"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(grid)}'
                + f'<tr class="tot"><td class="nm">starters out</td>{tot}</tr></tbody></table>'
                + ("".join(fixes[:8]) if fixes else '<div class="ws-note">Every short week is one starter — the bench covers it.</div>')
                + '</div>', unsafe_allow_html=True)


# --------------------------------------------------------- league GM board
def _gm_board(ctx, g, status) -> None:
    """Every team at once: where they stand, what they need, what they can
    spare, which picks they own — and the matches with you."""
    reg = ctx["registry"]
    me = str(g["me"])
    vals = _win_now(ctx, g)
    from .. import userstate as US
    tank = set(US.tankers(ctx["league_key"]))
    info = {}
    for o, r in g["rosters"].items():
        pids = [str(p) for p in (r.get("players") or [])]
        if not pids:
            continue
        lc = W.lineup_check(pids, g["slots"], g["proj"], reg, g["byes"], g["week"])
        starting = {str(p) for _s, p in lc["spots"] if p}
        weak = W.weakest_slot(pids, g["slots"], g["proj"], reg, byes=g["byes"], week=g["week"])
        bench_par: dict = {}
        for p in pids:
            if p in starting:
                continue
            v = vals.get(p) or {}
            bench_par[v.get("pos") or "?"] = bench_par.get(v.get("pos") or "?", 0) + (v.get("par") or 0)
        spare = max(bench_par.items(), key=lambda kv: kv[1]) if bench_par else None
        odds = (status.get(str(o)) or {}).get("odds")
        mode = ("seller" if (odds is not None and odds <= 15) or str(o) in tank else
                "contend" if (odds or 0) >= 35 else "bubble")
        menu = _pick_menu(ctx, g, o)
        nxt = [int(pk["round"]) for pk in menu.values() if str(pk["season"]) == str(int(g["season"]) + 1)]
        top = sorted(((vals.get(p) or {}).get("par") or 0, p) for p in pids)[-1:] if mode == "seller" else []
        info[str(o)] = {"odds": odds, "mode": mode, "weak": weak, "spare": spare if spare and spare[1] > 5 else None,
                        "picks": nxt, "sell": [reg.meta(p).name for v, p in top if v > 10], "pids": pids}
    rows = []
    for o, v in sorted(info.items(), key=lambda kv: -(kv[1]["odds"] or 0)):
        weak = v["weak"]
        need = f'{weak[0]} ({weak[1]:.0f})' if weak else "—"
        sp = v["spare"][0] if v["spare"] else "—"
        # only the differences from a normal set of one pick a round
        rnds = v["picks"]
        last = int(ctx["meta"].draft_rounds or (max(rnds) if rnds else 0) or 0)
        cnt = {r: rnds.count(r) for r in set(rnds)}
        missing = [r for r in range(1, last + 1) if cnt.get(r, 0) == 0]
        extra = sorted(r for r, c in cnt.items() for _ in range(c - 1)) + sorted(r for r in cnt if r > last)
        parts = ([("no R" + ", R".join(map(str, missing)))] if missing else []) + \
                ([("+R" + ", +R".join(map(str, extra)))] if extra else [])
        picks = " · ".join(parts) if rnds else "none"
        picks = picks or "all"
        rows.append(f'<tr class="{"me" if o == me else ""}"><td><b>{"You" if o == me else _esc_(_owner_name(ctx, o))}</b></td>'
                    f'<td class="n">{v["odds"] if v["odds"] is not None else "—"}%</td>'
                    f'<td><span class="gm-md {v["mode"]}">{v["mode"]}</span></td><td>{_esc_(need)}</td><td>{_esc_(sp)}</td>'
                    f'<td class="sm">{_esc_(picks)}</td><td class="sm">{_esc_(", ".join(v["sell"]))}</td></tr>')
    mine = info.get(me) or {}
    my_need = ((mine.get("weak") or ("", 0, ""))[0] or "").rstrip("0123456789")
    my_spare = (mine.get("spare") or ("",))[0]
    matches = []
    for o, v in info.items():
        if o == me:
            continue
        if v["mode"] == "seller" and my_need:
            hit = [reg.meta(p).name for p in v["pids"]
                   if (vals.get(p) or {}).get("pos") in (my_need, "RB", "WR", "TE") and my_need in ("FLEX",)
                   or (vals.get(p) or {}).get("pos") == my_need]
            hit = [h for h in hit if any(reg.meta(q).name == h and ((vals.get(q) or {}).get("par") or 0) > 5 for q in v["pids"])]
            if hit:
                matches.append(f'<b>{_esc_(_owner_name(ctx, o))}</b> is selling and has your {my_need}: {_esc_(", ".join(hit[:2]))}')
        if v["mode"] == "contend" and my_spare and v["weak"] and v["weak"][0].rstrip("0123456789") == my_spare:
            matches.append(f'<b>{_esc_(_owner_name(ctx, o))}</b> is contending and short at {my_spare} — your spare {my_spare}s')
    st.markdown('<table class="gm-t"><thead><tr><th>Team</th><th>Playoffs</th><th>Mode</th><th>Weakest starter</th>'
                '<th>Can spare</th><th>' + str(int(g["season"]) + 1) + ' picks</th><th>Worth a call</th></tr></thead><tbody>'
                + "".join(rows) + '</tbody></table>'
                + ('<div class="gm-m">' + "".join(f"<div>{m}</div>" for m in matches[:4]) + '</div>' if matches else ""),
                unsafe_allow_html=True)


# ------------------------------------------------------ next year's draft
@st.cache_data(ttl=1800, show_spinner=False, max_entries=8)
def _slot_odds_cached(lk: str, week: int, bucket: int, version: int, _ctx, _g) -> dict:
    """{owner: [P(slot 1) .. P(slot N)]} from the league's own lottery, run over
    the rest of the season (draftkit/lottery.slot_odds). {} without a spec."""
    from .. import lottery as LT
    spec = K.lottery_spec(str(_ctx["meta"].league_id))
    if not spec:
        return {}
    si = _sim_inputs(_ctx, _g)
    fx = {int(k): v for k, v in (si["fx"] or {}).items()}
    return LT.slot_odds(si["means"], si["sds"], si["recs"], si["pf"], fx, si["pt"], spec,
                        median=si["median"], n_sims=10000)


def _odds_html(odds: dict, owners: list, me: str, name) -> str:
    """Heat map: one row per team (likeliest first), one column per slot."""
    n = len(owners)
    exp = {o: sum((i + 1) * p for i, p in enumerate(odds.get(o) or [])) / 100 for o in owners}
    rows = ['<div class="lo-r hd"><span>Team</span>' + "".join(f"<span>{i}</span>" for i in range(1, n + 1))
            + "<span>Avg</span></div>"]
    for o in sorted(owners, key=lambda o: exp[o]):
        ps = (odds.get(o) or [0] * n)[:n]
        top = max(range(n), key=lambda i: ps[i]) if ps else 0
        cells = "".join(
            f'<span class="lo-c{" top" if i == top and ps[i] else ""}" style="--a:{min(1.0, p / 45):.2f}">'
            f'{p:.0f}</span>' if p >= 0.5 else '<span class="lo-c z">·</span>'
            for i, p in enumerate(ps))
        rows.append(f'<div class="lo-r{" me" if o == me else ""}"><span class="lo-t">{_esc_(name(o))}</span>'
                    f'{cells}<span class="lo-e">{exp[o]:.1f}</span></div>')
    return f'<div class="lo" style="--n:{n}">{"".join(rows)}</div>'


@st.cache_data(ttl=1800, show_spinner=False, max_entries=12)
def _league_keeper_rows_cached(lk: str, week: int, bucket: int, version: int, _ctx, _g) -> dict:
    """{owner_id: [every keeper row for that team]} — priced once per league on
    the 15-minute clock and shared by the 2027 board, the preview, the trade
    market and the tank/contend panel (which each used to run their own pass
    per team). The warmer fills it off the request."""
    out = {}
    for o in _g["rosters"]:
        try:
            out[o] = _keeper_rows(_ctx, _g, as_owner=o)
        except Exception:  # noqa: BLE001
            out[o] = []
    return out


def _all_keeper_rows(ctx, g) -> dict:
    return _league_keeper_rows_cached(ctx["league_key"], g["week"], _slow_bucket(g["season"], g["week"]),
                                      _GATHER_V, ctx, g)


def _league_keepers(ctx, g) -> dict:
    """{owner_id: [keeper rows that would be kept]} — every team's projected
    keepers, priced through the league's rules."""
    return {o: [r for r in rows if r.get("verdict") == "keep"] for o, rows in _all_keeper_rows(ctx, g).items()}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _player_history(league_id: str, season: int) -> dict:
    """The keeper history, from a day-old copy on disk if there is one — it
    walks four seasons of Sleeper drafts and the keeper files, a dozen requests
    that never change for past seasons, so a restart shouldn't pay them."""
    import json as _json
    import time as _t
    p = config.DATA_DIR / f"history_{league_id}_{season}.json"
    try:
        if p.exists() and _t.time() - p.stat().st_mtime < 24 * 3600:
            raw = _json.loads(p.read_text())
            return {pid: {int(y): e for y, e in yrs.items()} for pid, yrs in raw.items()}
    except Exception:  # noqa: BLE001
        pass
    out = _player_history_live(league_id, season)
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps(out))
    except Exception:  # noqa: BLE001
        pass
    return out


def _player_history_live(league_id: str, season: int) -> dict:
    """{pid: {season: {...}}} — every season this league has a record of him:
    the round he went in that year's draft and who took him, and, from the
    league's keeper files, whether he was kept, at what round and which year of
    the clock. One entry per season; the screen turns it into lines.

    Walks the Sleeper previous_league_id chain for the drafts, and the hub's
    keeper files for the keeper years."""
    out: dict = {}
    lid, hops = str(league_id), 0
    while lid and lid != "0" and hops < 5:
        hops += 1
        try:
            lg = api.get_league(lid) or {}
        except Exception:  # noqa: BLE001
            break
        yr = int(lg.get("season") or 0)
        try:
            names = {str(u.get("user_id")): (u.get("display_name") or "") for u in (api.get_users(lid) or [])}
        except Exception:  # noqa: BLE001
            names = {}
        named = K.configured_drafts(str(league_id)) if lid == str(league_id) else {}
        dids = ([d for k in ("veteran", "rookie") for d in (named.get(k) or [])] if named
                else [lg.get("draft_id")])
        for did in [d for d in dids if d]:
            try:
                picks = api.get_draft_picks(did) or []
            except Exception:  # noqa: BLE001
                continue
            for q in picks:
                pid = str(q.get("player_id") or "")
                if not pid or not q.get("round"):
                    continue
                e = out.setdefault(pid, {}).setdefault(yr, {})
                e.setdefault("round", int(q["round"]))
                e.setdefault("by", str(q.get("picked_by") or ""))
                e.setdefault("by_name", names.get(str(q.get("picked_by") or ""), ""))
                if q.get("is_keeper"):
                    e["kept"] = True
        lid = str(lg.get("previous_league_id") or "")
    for yr in range(int(season) - 3, int(season) + 1):
        try:
            filed = K.load_keepers(str(league_id), yr, rostered=False) or {}
        except Exception:  # noqa: BLE001
            continue
        for oid, recs in filed.items():
            for r in recs or []:
                pid = str(r.get("player_id") or "")
                if not pid:
                    continue
                e = out.setdefault(pid, {}).setdefault(yr, {})
                e["kept"] = True
                e["by"] = str(oid)
                if r.get("cost_round"):
                    e["round"] = int(r["cost_round"])
                if r.get("is_rookie_keeper"):
                    e["rookie"] = True
                elif r.get("keep_year"):
                    e["year"] = int(r["keep_year"])
    return out


def _hist_pop(ctx, g, pid, label_html: str, future: str = "") -> str:
    """`label_html` that opens a small keeper-history card in place — one line
    per season, oldest first, then next year's price."""
    hist = _player_history(str(ctx["meta"].league_id), int(g["season"])).get(str(pid)) or {}
    lines = []
    for yr in sorted(hist):
        e = hist[yr]
        who = _owner_name(ctx, e.get("by")) if e.get("by") else ""
        if not who or who == "Team":
            who = e.get("by_name") or "?"
        rd = f' R{e["round"]}' if e.get("round") else ""
        if e.get("kept"):
            kind = (" · rookie keeper" if e.get("rookie") else f' · year {e["year"]}' if e.get("year") else "")
            lines.append(f'<li><b class="k">{yr}</b> kept{rd} by {_esc_(who)}{kind}</li>')
        else:
            lines.append(f'<li><b>{yr}</b> drafted{rd} by {_esc_(who)}</li>')
    body = "".join(lines) or "<li>no draft or keeper record in this league</li>"
    try:
        nm_ = ctx["registry"].meta(pid).name
    except Exception:  # noqa: BLE001
        nm_ = str(pid)
    fut = f'<div class="nbh-f">{future}</div>' if future else ""
    return (f'<details class="nbh"><summary>{label_html}</summary><div class="nbh-pop">'
            f'<strong>{_esc_(nm_)}</strong><ul>{body}</ul>{fut}</div></details>')


def _practice_panel(ctx, cells, clock, state, key, pool, pos_of, proj, nm, nxt, n, my_rid) -> None:
    """The practice draft's controls: who's on the clock, the best still there,
    Draft / Auto-pick / Undo / Reset. The CPU drafts every other pick
    best-available off the projected ADP (no third QB or TE)."""
    lk = ctx["league_key"]
    keep = _keep_open(f"nb_{lk}")
    taken = {c["pid"] for c in cells.values() if c["pid"] and not c.get("future")}
    avail = [p for p in pool if p not in taken]
    mine = sorted((c for c in cells.values() if c.get("forced")), key=lambda c: c["pick"])

    def _set(pick, pid):
        def go():
            keep()
            if pid:
                state["picks"][pick] = str(pid)
            st.session_state[key] = state
        return go

    def _undo():
        keep()
        if state["picks"]:
            state["picks"].pop(max(state["picks"]))
        st.session_state[key] = state

    def _reset():
        keep()
        state["picks"] = {}
        st.session_state[key] = state

    def lab(pid):
        rk = (proj.get(pid) or {}).get("rank")
        return f"{nm(pid)} · {pos_of.get(pid, '')} · #{rk}" if rk else nm(pid)
    if clock:
        gone = sum(1 for c in cells.values() if c["pick"] < clock["pick"])
        _lab = f'{clock["round"]}.{clock["slot"]:02d}'
        _lk = f"np_last_{lk}"
        _prev = st.session_state.get(_lk)
        st.session_state[_lk] = _lab
        _cube = C.clock_cube_html(_lab, "YOU", _prev if _prev and _prev != _lab else None, "DRAFTED")
        st.markdown(f'<div class="np-clk"><span>ON THE CLOCK</span>{_cube}'
                    f'<i>pick #{clock["pick"]} &middot; {gone} gone, keepers included &middot; '
                    f'best left: {_esc_(nm(avail[0])) if avail else "—"}</i></div>', unsafe_allow_html=True)
        # his roster so far shapes the CPU's caps, not his: he can take a 3rd QB
        opts = avail[:60]
        c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 1, 1])
        with c1:
            sel = st.selectbox("Best available", opts, format_func=lab, key=f"np_sel_{lk}_{clock['pick']}",
                               on_change=keep, label_visibility="collapsed")
        with c2:
            st.button("Draft", key=f"np_go_{lk}", type="primary", on_click=_set(clock["pick"], sel),
                      use_container_width=True)
        with c3:
            # auto-pick takes what the CPU would: best available inside the caps
            have = {}
            for c in cells.values():
                if c["holder"] == my_rid and c["pid"] and not c.get("future"):
                    have[pos_of.get(c["pid"], "")] = have.get(pos_of.get(c["pid"], ""), 0) + 1
            from ..nextboard import CAPS
            auto = next((p for p in avail if have.get(pos_of.get(p, ""), 0) < CAPS.get(pos_of.get(p, ""), 99)), None)
            st.button("Auto-pick", key=f"np_auto_{lk}", on_click=_set(clock["pick"], auto),
                      use_container_width=True)
        with c4:
            st.button("Undo", key=f"np_undo_{lk}", on_click=_undo, disabled=not state["picks"],
                      use_container_width=True)
        with c5:
            st.button("Reset", key=f"np_reset_{lk}", on_click=_reset, disabled=not state["picks"],
                      use_container_width=True)
    else:
        # the grade: every team's whole class (keepers + picks) by projected
        # next-year value, and the pick of yours that beat its slot the most
        tot = {}
        for c in cells.values():
            if c["pid"]:
                tot[c["holder"]] = tot.get(c["holder"], 0.0) + float((proj.get(c["pid"]) or {}).get("value") or 0)
        order_ = sorted(tot, key=lambda h: -tot[h])
        place = order_.index(my_rid) + 1 if my_rid in order_ else None
        steals = sorted(((c["pick"] - int((proj.get(c["pid"]) or {}).get("rank") or c["pick"]), c) for c in mine),
                        key=lambda x: -x[0])
        grade = ("A" if place == 1 else "A-" if place == 2 else "B+" if place and place <= n // 3 + 1
                 else "B" if place and place <= n // 2 else "C+" if place and place <= 2 * n // 3 else "C")
        st.markdown(f'<div class="np-clk done"><span>DRAFT DONE</span><b>{grade}</b>'
                    f'<i>your class ranks <strong>{place} of {n}</strong> by projected {nxt} value'
                    + (f' &middot; best value: <strong>{_esc_(nm(steals[0][1]["pid"]))}</strong> at #{steals[0][1]["pick"]}, '
                       f'ranked #{(proj.get(steals[0][1]["pid"]) or {}).get("rank")} ({steals[0][0]:+d})'
                       if steals and steals[0][0] > 0 else "")
                    + ' &middot; Reset to run it again</i></div>', unsafe_allow_html=True)
        st.button("Reset", key=f"np_reset_{lk}", on_click=_reset)
    if mine:
        chips = "".join(f'<span class="np-p {pos_of.get(c["pid"], "")}"><em>{c["round"]}.{c["slot"]:02d}</em>'
                        f'{_esc_(nm(c["pid"]))}<small>{_esc_(pos_of.get(c["pid"], ""))}</small></span>'
                        for c in mine)
        st.markdown(f'<div class="np-mine"><span class="np-h">Your picks</span>{chips}</div>',
                    unsafe_allow_html=True)


def _next_board(ctx, g) -> None:
    """Next season's draft, every pick simulated (draftkit/nextboard.py)."""
    from .. import nextboard as NB, nextyear as NY
    reg, meta = ctx["registry"], ctx["meta"]
    n = int(getattr(meta, "num_teams", 10) or 10)
    nxt = int(g["season"]) + 1
    rules = K.load_keeper_rules(str(meta.league_id)) or {}
    rounds = K.price_rounds(rules, int(g["season"]), getattr(meta, "draft_rounds", 14) or 14)
    rid_of = {o: r.get("roster_id") for o, r in g["rosters"].items() if r.get("roster_id") is not None}
    owner_of = {v: k for k, v in rid_of.items()}
    if len(rid_of) < 2:
        _note("No rosters to build a board from yet.")
        return
    # the order: projected finish, worst first (the lotteries reshuffle it)
    try:
        status = _league_status_cached(ctx["league_key"], g["week"], _slow_bucket(g["season"], g["week"]), ctx, g)
    except Exception:  # noqa: BLE001
        status = {}

    def _finish(o):
        if o in status:
            return status[o]["seed"]
        se = g["rosters"][o].get("settings") or {}
        return -(int(se.get("wins") or 0) * 1000 + float(se.get("fpts") or 0))
    owners = sorted(rid_of, key=_finish, reverse=True)
    me = str(g["me"])
    try:
        odds = _slot_odds_cached(ctx["league_key"], g["week"], _slow_bucket(g["season"], g["week"]),
                                 _GATHER_V, ctx, g)
    except Exception:  # noqa: BLE001 — odds are a nicety; the board stands without them
        odds = {}
    odds = {o: odds.get(str(o)) for o in owners if odds.get(str(o))}
    opts = ["Projected"] + (["Likeliest"] if len(odds) == len(owners) else []) + [str(i) for i in range(1, len(owners) + 1)]
    _c1, _c2 = st.columns([1, 2])
    with _c1:
        view = st.segmented_control("View", ["Full board", "Keepers only", "Practice"], key=f"nb_view_{ctx['league_key']}", on_change=_keep_open(f"nb_{ctx['league_key']}"),
                                    selection_mode="single", default="Full board") or "Full board"
    with _c2:
        pick_slot = st.segmented_control("Your slot", opts, key=f"nb_slot_{ctx['league_key']}", on_change=_keep_open(f"nb_{ctx['league_key']}"),
                                         selection_mode="single", default="Projected") or "Projected"
    # the odds read before the board — they decide its order — but they're
    # drawn last, once the board's names exist; this holds their place
    _odds_box = st.container()
    if pick_slot == "Likeliest":
        # every team on its single likeliest slot, clashes settled by who wants it most
        left, placed = set(range(len(owners))), {}
        for p, o, i in sorted(((odds[o][i], o, i) for o in owners for i in range(len(owners))), reverse=True):
            if o not in placed and i in left:
                placed[o] = i
                left.discard(i)
        owners = sorted(owners, key=lambda o: placed.get(o, 99))
    elif pick_slot != "Projected" and me in owners:
        owners.remove(me)
        owners.insert(int(pick_slot) - 1, me)
    order = [rid_of[o] for o in owners]
    held = {}
    for rid, picks in (g.get("picks") or {}).items():
        for pk in picks:
            if str(pk.get("season")) == str(nxt):
                held[(int(pk["round"]), int(pk["origin"]))] = int(rid)
    keepers = {rid_of[o]: [(str(r["pid"]), r.get("cost_round")) for r in rows]
               for o, rows in _league_keepers(ctx, g).items() if o in rid_of}
    w8 = getattr(meta, "scoring_weights", None) or {}
    ppr = 1.0 if float(w8.get("rec", 1.0)) >= 0.75 else 0.5 if float(w8.get("rec", 1.0)) >= 0.25 else 0.0
    proj = NY.projected(n, ppr)
    pool = [pid for pid, _r in sorted(proj.items(), key=lambda kv: kv[1]["rank"])]
    pos_of = {}
    for pid in pool + [p for ks in keepers.values() for p, _c in ks]:
        try:
            pos_of[pid] = (reg.meta(pid).position or "").upper()
        except Exception:  # noqa: BLE001
            pos_of[pid] = ""
    # the practice draft: his picks, kept per order (a new slot is a new draft)
    _pk = f"np_{ctx['league_key']}"
    _ps = st.session_state.get(_pk) or {}
    if _ps.get("order") != tuple(order):
        _ps = {"order": tuple(order), "picks": {}}
        st.session_state[_pk] = _ps
    practice = view == "Practice"
    cells = NB.build(order, rounds, held, keepers, pool, pos_of, forced=_ps["picks"] if practice else None)
    clock = None
    if practice:
        _rid = rid_of.get(me)
        _open = sorted((c for c in cells.values() if c["holder"] == _rid and not c["keeper"]
                        and c["pick"] not in _ps["picks"]), key=lambda c: c["pick"])
        clock = _open[0] if _open else None
        if clock:
            for c in cells.values():
                if c["pick"] >= clock["pick"] and not c["keeper"]:
                    c["future"] = True
    _kfut = {str(r["pid"]): f'{nxt}: keeps at R{r.get("cost_round")} &middot; {_esc_(r.get("note") or "")}'
             for rows_ in _league_keepers(ctx, g).values() for r in rows_}

    def nm(pid):
        try:
            return reg.meta(pid).name
        except Exception:  # noqa: BLE001
            return str(pid)
    my_rid = rid_of.get(me)
    mine = sorted((c for c in cells.values() if c["holder"] == my_rid), key=lambda c: c["pick"])
    live = [c for c in mine if not c["keeper"] and c["pid"]]
    if practice:
        _practice_panel(ctx, cells, clock, _ps, _pk, pool, pos_of, proj, nm, nxt, len(order), my_rid)
    elif live:
        c0 = live[0]
        _ph = getattr(reg.meta(c0["pid"]), "sleeper_pid", None) or c0["pid"]
        st.markdown(C.hero_html(
            f"{nxt} DRAFT · SIMULATED · {len(order)} TEAMS · {rounds} ROUNDS",
            f'{c0["round"]}.{c0["slot"]:02d}',
            f'your first live pick (#{c0["pick"]}) — projected to land <b>{_esc_(nm(c0["pid"]))}</b>'
            + (f', after {sum(1 for c in mine if c["keeper"])} of yours go to keepers'
               if any(c["keeper"] for c in mine) else ""),
            photo=_ph, tone="ink"), unsafe_allow_html=True)
    first = lambda o: _owner_name(ctx, o).split()[0]  # noqa: E731
    head = '<div class="nb-r hd"><span></span>' + "".join(
        f'<span class="{"me" if owners[i] == me else ""}">{i + 1}. {_esc_(first(owners[i]))}</span>'
        for i in range(len(order))) + "</div>"
    body = []
    for r in range(1, rounds + 1):
        row = [f'<span class="nb-rd">{r}</span>']
        for sl in range(1, len(order) + 1):
            c = cells[(r, sl)]
            if practice and c.get("future"):
                _on = clock and c["pick"] == clock["pick"]
                tag = ("ON THE CLOCK" if _on else "your pick" if c["holder"] == my_rid else
                       f'{_esc_(first(owner_of.get(c["holder"], "")))}' if c["traded"] else "")
                row.append(f'<div class="nb-c open{" me" if c["holder"] == my_rid else ""}{" clock" if _on else ""}">'
                           f'<span class="nb-p">#{c["pick"]}</span><small>{tag}</small></div>')
                continue
            if view == "Keepers only" and not c["keeper"]:
                tag = ("your pick" if c["holder"] == my_rid else
                       f'open &middot; {_esc_(first(owner_of.get(c["holder"], "")))}' if c["traded"] else "open")
                row.append(f'<div class="nb-c open{" me" if c["holder"] == my_rid else ""}">'
                           f'<span class="nb-p">#{c["pick"]}</span><small>{tag}</small></div>')
                continue
            cls = ["nb-c", (c["pid"] and pos_of.get(c["pid"], "")) or ""]
            if c["keeper"]:
                cls.append("keep")
            if c.get("forced"):
                cls.append("mine")
            if c["holder"] == my_rid:
                cls.append("me")
            via = (f'<i>&#9668; {_esc_(first(owner_of.get(c["origin"], "")))}</i>' if c["traded"] else "")
            who = (f'<b>{_esc_(nm(c["pid"]).split()[-1] if c["pid"] else "—")}</b>'
                   f'<small>{_esc_(pos_of.get(c["pid"], "") if c["pid"] else "")}'
                   f'{" · KEEP" if c["keeper"] else ""}</small>')
            holder = (f'<em>{_esc_(first(owner_of.get(c["holder"], "")))}</em>' if c["traded"] else "")
            if c["pid"]:
                _rk = (proj.get(c["pid"]) or {}).get("rank")
                who = _hist_pop(ctx, g, c["pid"], who, _kfut.get(c["pid"]) or (f"{nxt}: projected rank #{_rk}" if _rk else ""))
            row.append(f'<div class="{" ".join(x for x in cls if x)}"><span class="nb-p">#{c["pick"]}</span>{who}{holder}{via}</div>')
        body.append('<div class="nb-r">' + "".join(row) + "</div>")
    grid = f'<div class="nb" style="--n:{len(order)}">{head}{"".join(body)}</div>'
    if view != "Keepers only":
        st.markdown(grid, unsafe_allow_html=True)
    else:
        # everyone not kept, best to worst, with where the full simulation sends
        # him — and a marker at each of your picks: everyone below it is still there
        kept_ids = {c["pid"] for c in cells.values() if c["keeper"]}
        live = sorted((c for c in cells.values() if not c["keeper"]), key=lambda c: c["pick"])
        goes = {c["pid"]: c for c in live if c["pid"]}
        posf = st.segmented_control("Position", ["All", "QB", "RB", "WR", "TE"], key=f"nb_pos_{ctx['league_key']}", on_change=_keep_open(f"nb_{ctx['league_key']}"),
                                    selection_mode="single", default="All") or "All"
        avail = [p for p in pool if p not in kept_ids]
        marks = {}
        for c in live:
            if c["holder"] == my_rid:
                marks.setdefault(sum(1 for x in live if x["pick"] < c["pick"]), []).append(c)
        rows_l, shown = [], 0
        for i, pid in enumerate(avail[:max(rounds * len(order), 80)]):
            for c in marks.get(i, []):
                rows_l.append(f'<div class="nbl-mark"><span>YOUR PICK &middot; {c["round"]}.{c["slot"]:02d} (#{c["pick"]})</span>'
                              f'<i>{i} players gone before it — everyone below is still there</i></div>')
            pp = pos_of.get(pid, "")
            if posf != "All" and pp != posf:
                continue
            g_ = goes.get(pid)
            mine_ = bool(g_ and g_["holder"] == my_rid)
            rk = (proj.get(pid) or {}).get("rank")
            try:
                tm = reg.meta(pid).team or "FA"
            except Exception:  # noqa: BLE001
                tm = ""
            _phid = getattr(reg.meta(pid), "sleeper_pid", None) or pid
            dest = (f"&rarr; you at #{g_['pick']}" if mine_ else
                    f"~#{g_['pick']} {_esc_(first(owner_of.get(g_['holder'], '')))}" if g_ else "after the board")
            rows_l.append(
                f'<div class="nbl{" mine" if mine_ else ""}"><span class="nbl-n">{i + 1}</span>'
                f'<img class="nbl-f" src="https://sleepercdn.com/content/nfl/players/thumb/{_esc_(_phid)}.jpg" alt="" loading="lazy">'
                f'<div class="nbl-t">' + _hist_pop(ctx, g, pid, f'<b>{_esc_(nm(pid))}</b>', f"{nxt}: projected rank #{rk}")
                + f'<span>{_esc_(pp)} &middot; {_esc_(tm)}</span></div>'
                f'<span class="nbl-r">#{rk}<small>{nxt} rank &middot; R{-(-int(rk or 0) // max(1, len(order)))}</small></span>'
                f'<span class="nbl-g">{dest}</span></div>')
            shown += 1
        lc, rc = st.columns([1.25, 1])
        with lc:
            st.markdown(f'<div class="ws-h">{len(kept_ids)} projected keepers &middot; every other pick open</div>{grid}',
                        unsafe_allow_html=True)
        with rc:
            st.markdown(f'<div class="ws-h">Available &middot; best to worst &middot; projected {nxt} rank</div>'
                        f'<div class="nbl-list">{"".join(rows_l)}</div>', unsafe_allow_html=True)
    if odds:
        _spec = K.lottery_spec(str(meta.league_id)) or {}
        _mine = odds.get(me) or []
        _best = max(range(len(_mine)), key=lambda i: _mine[i]) + 1 if _mine else None
        _how = {"inverted": "placement inverted inside each bracket; the draw is the order",
                "final": "final standing incl. the Chase, champion floored, two choices drawn",
                "chase": "Chase winner, then worst to best, champion last"}.get(_spec.get("style"), "")
        with _odds_box, st.container(key=f"lo_{ctx['league_key']}"):
            if _best:
                st.markdown(C.drum_html(slot=_best, pct=_mine[_best - 1], top3=sum(_mine[:3]), n_teams=len(owners),
                                        my_share=(_mine[0] / 100 if _mine else 0.1), season=nxt), unsafe_allow_html=True)
            st.markdown(f'<div class="ws-h">{nxt} draft-order odds &middot; 10,000 seasons &middot; '
                        f'{_esc_(_how)}</div>' + _odds_html(odds, owners, me, first)
                        + (f'<div class="lo-k">You: likeliest <b>slot {_best}</b> ({_mine[_best - 1]:.0f}%) '
                           f'&middot; top three {sum(_mine[:3]):.0f}%</div>' if _best else ""),
                        unsafe_allow_html=True)
    _note(f"Order is the projected finish, worst first — the league's lottery will reshuffle it, so "
          f"set **Your slot** to see a different spot, or **Likeliest** to put every team on the slot "
          f"its lottery odds favour. Keepers sit on the picks their teams will "
          f"spend (the latest in their cost round, or the nearest earlier round they hold); everyone "
          f"else goes best-available off the projected {nxt} ADP, with no team taking a third QB or TE. "
          f"Next year's NFL rookies aren't priced until they're drafted, so the board leans veteran.")


def _draft_preview(ctx, g) -> None:
    """Next season's draft as it would look today: every team's projected
    keepers off the board, then who's likely there at each pick you own."""
    from .. import nextyear as NY
    reg, meta = ctx["registry"], ctx["meta"]
    n = int(getattr(meta, "num_teams", 10) or 10)
    kept, kept_rounds = set(), []
    for _o, rows in _league_keepers(ctx, g).items():
        for r in rows:
            kept.add(str(r["pid"]))
            if r.get("cost_round"):
                kept_rounds.append(int(r["cost_round"]))
    w8 = getattr(meta, "scoring_weights", None) or {}
    ppr = 1.0 if float(w8.get("rec", 1.0)) >= 0.75 else 0.5
    proj = NY.projected(n, ppr)
    pool = [pid for pid, _r in sorted(proj.items(), key=lambda kv: kv[1]["rank"]) if pid not in kept]
    nxt = str(int(g["season"]) + 1)
    menu = {lab: pk for lab, pk in _pick_menu(ctx, g, g["me"]).items() if str(pk["season"]) == nxt}
    if not menu or not pool:
        _note("No pick or projection data for next year's draft yet.")
        return
    cells = []
    for lab, pk in sorted(menu.items(), key=lambda kv: kv[1]["round"]):
        rnd = int(pk["round"])
        overall = PK.overall(rnd, n)
        # picks before this one that keepers use up: earlier rounds whole, this round half
        k_before = sum(1 for kr in kept_rounds if kr < rnd) + sum(0.5 for kr in kept_rounds if kr == rnd)
        i = int(max(0, overall - 1 - k_before))
        names = [reg.meta(p).name for p in pool[i:i + 3]]
        cells.append(f'<div class="dp-pk"><b>{_esc_(lab)}</b><span>≈ pick {overall:.0f}</span>'
                     f'<em>{_esc_(names[0]) if names else "—"}</em><i>{_esc_(" · ".join(names[1:]))}</i></div>')
    drain = []
    for pos, depth in (("QB", n), ("RB", 2 * n), ("WR", 2 * n), ("TE", n)):
        top = [pid for pid, r in sorted(proj.items(), key=lambda kv: kv[1]["rank"])
               if (reg.meta(pid).position or "").upper() == pos][:depth]
        k = sum(1 for p in top if p in kept)
        drain.append(f'<div class="dp-dr"><b>{pos}</b><span>{k} of the top {depth} kept</span></div>')
    st.markdown(f'<div class="dp"><div class="sa-k">{nxt} DRAFT · AFTER {len(kept)} PROJECTED KEEPERS · WHO\'S LIKELY THERE</div>'
                f'<div class="dp-pks">{"".join(cells)}</div><div class="dp-drs">{"".join(drain)}</div></div>',
                unsafe_allow_html=True)
    _note("Keepers are each team's projected five (the keeper engine, priced on the next-season ADP projection). "
          "Picks are placed mid-round, since the order isn't set; the names are the best left by projected ADP "
          "once the keepers ahead of that pick are off the board.")


def _scan_sig(g, partners) -> tuple:
    return (tuple(sorted(map(str, g["mine"]))),
            tuple((str(o), tuple(map(str, pl))) for o, pl in partners), len(g["proj"]))


@st.cache_data(ttl=600, show_spinner=False)
def _scan_cached(sig, _mine, _slots, _proj, _reg) -> dict:
    """Mutual deals per partner. Module level (it lived inside _trades) so the
    background warmer can build it before Trades is opened — the scan was most
    of a 20-second first visit."""
    out = {}
    for o, pids in sig[1]:
        n = len([1 for i in W.trade_ideas(_mine, list(pids), _slots, _proj, _reg,
                                          max_ideas=4) if i["mutual"]])
        n += len([1 for i in W.trade_packages(_mine, list(pids), _slots, _proj, _reg,
                                              max_ideas=5) if i["mutual"]])
        out[o] = n
    return out


@st.cache_data(ttl=900, show_spinner=False)
def _partner_ideas(mine, opp, week, nproj, _g, _reg):
    """One partner's one-for-ones and packages. The exact re-scoring behind them
    is most of a Trades visit, and the same pair is asked for on every rerun."""
    ones = W.trade_ideas(list(mine), list(opp), _g["slots"], _g["proj"], _reg,
                         byes=_g["byes"], week=week, max_ideas=4)
    pkgs = W.trade_packages(list(mine), list(opp), _g["slots"], _g["proj"], _reg,
                            byes=_g["byes"], week=week, max_ideas=5)
    return ones, pkgs


def _trades(ctx, g) -> None:
    from .. import userstate as US
    reg, lk = ctx["registry"], ctx["league_key"]
    partners = [(o, r["players"]) for o, r in g["rosters"].items()
                if o != g["me"] and r["players"]]
    if not partners:
        st.info("No other rosters found.")
        return

    # ---- mode: playing for this season or the next --------------------------
    try:
        status = _league_status_cached(lk, g["week"], _slow_bucket(g["season"], g["week"]), ctx, g)
    except Exception:  # noqa: BLE001
        status = {}
    _labels = {"auto": "Auto", "contend": "Contend", "tank": "Tank"}
    mkey = f"td_mode_{lk}"
    if mkey not in st.session_state:
        st.session_state[mkey] = _labels[US.league_mode(lk)]

    def _save_mode():
        inv = {v: k for k, v in _labels.items()}
        US.set_league_mode(lk, inv.get(st.session_state.get(mkey) or "Auto", "auto"))
    mc = st.columns([1.4, 3])
    mc[0].segmented_control("Mode", list(_labels.values()), key=mkey, selection_mode="single",
                            label_visibility="collapsed", on_change=_save_mode)
    setting, resolved = _mode(ctx, g, status)
    my_odds = (status.get(str(g["me"])) or {}).get("odds")
    contenders = sum(1 for o, v in status.items() if o != str(g["me"]) and v["odds"] >= 35)
    out_of_it = sum(1 for o, v in status.items() if o != str(g["me"]) and v["odds"] <= 15)
    mc[1].markdown(
        f'<div class="ws-note" style="margin-top:9px"><b>{resolved.capitalize()}</b>'
        + (f" (auto: you're {my_odds}% to make it)" if setting == "auto" and my_odds is not None else "")
        + f' · {contenders} contender{"s" if contenders != 1 else ""} · {out_of_it} out of it · '
        + {"tank": "selling this season for picks and cheap keepers",
           "contend": "buying from the teams that are out of it",
           "balanced": "on the bubble"}[resolved] + '</div>', unsafe_allow_html=True)
    if resolved == "contend":
        with _drawer("Teams tanking", "mark the ones you know are selling", key=f"tk_{lk}"):
            names = {o: _owner_name(ctx, o) for o, _p in partners}
            cur = [o for o in US.tankers(lk) if o in names]
            pick_t = st.multiselect("Tanking", list(names), default=cur, format_func=lambda o: names[o],
                                    key=f"td_tankers_{lk}", label_visibility="collapsed",
                                    on_change=_keep_open(f"tk_{lk}"))
            if sorted(pick_t) != sorted(cur):
                US.set_tankers(lk, pick_t)
    _mode_panel(ctx, g, status, resolved)
    st.session_state[f"td_resolved_{lk}"] = resolved
    if status:
        with st.container(key="drawers_gm"), _drawer("League GM board", "every team's odds, needs, spare parts and picks"):
            _gm_board(ctx, g, status)
    # Which partners are actually worth talking to. Clicking through seven teams to
    # discover that three of them have a deal is a search the app should do.
    with st.spinner("Scanning the league for deals that clear…"):
        _cs = _scan_cached(_scan_sig(g, partners), g["mine"], g["slots"], g["proj"], reg)
        counts = {o: _cs.get(str(o), 0) for o, _pl in partners}
    # partners in the order this mode wants them: a tank sells to contenders
    # (best odds first), a contender buys from the teams that are out of it
    _odds = lambda o: (status.get(str(o)) or {}).get("odds", 50)  # noqa: E731
    if resolved == "tank":
        order = sorted(partners, key=lambda kv: (-_odds(kv[0]), -counts.get(kv[0], 0)))
        _how = "contenders first"
    elif resolved == "contend":
        order = sorted(partners, key=lambda kv: (_odds(kv[0]), -counts.get(kv[0], 0)))
        _how = "teams out of it first"
    else:
        order = sorted(partners, key=lambda kv: -counts.get(kv[0], 0))
        _how = "by deals that help both sides"
    labels = []
    for o, _pl in order:
        n = counts.get(o, 0)
        labels.append(f"{_owner_name(ctx, o)}"
                      + (f"  ·  {_odds(o)}% playoffs" if status else "")
                      + (f"  ·  {n} deal{'s' if n != 1 else ''}" if n else ""))
    # a "Check this deal" button parked a proposal: point the partner at it and
    # pre-fill the checker's boxes before they're drawn this run
    _pf = st.session_state.pop(f"td_prefill_{lk}", None)
    if _pf:
        for lab, (o, _pl) in zip(labels, order):
            if str(o) == _pf["oid"]:
                st.session_state[f"ws_tp_{lk}"] = lab
        st.session_state[f"ws_an_send_{lk}"] = _pf["send"]
        st.session_state[f"ws_an_get_{lk}"] = _pf["get"]
        st.session_state[f"ws_an_sendp_{lk}"] = _pf["sendp"]
        st.session_state[f"ws_an_getp_{lk}"] = _pf["getp"]
    if st.session_state.get(f"ws_tp_{lk}") not in labels:
        st.session_state.pop(f"ws_tp_{lk}", None)
    pick = st.selectbox(f"Trade partner — {_how}", labels, key=f"ws_tp_{lk}")
    oid, opp = order[labels.index(pick)]
    if not any(counts.values()):
        _note("No team in the league has a deal that improves both lineups right now. "
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
        ("Your lineup", f"{base_mine:.1f}", "projected this week", "var(--muted)"),
    ])
    _analyzer(ctx, g, oid, opp)

    with st.spinner("Searching one-for-ones and packages…"):
        ones, pkgs = _partner_ideas(tuple(map(str, g["mine"])), tuple(map(str, opp)),
                                    g["week"], len(g["proj"]), g, reg)
    ideas = []
    for i in ones:
        ideas.append({"shape": "1-for-1", "send_names": [i["send_name"]],
                      "get_names": [i["get_name"]], "send": [i["send"]], "get": [i["get"]],
                      "you": i["you"], "them": i["them"], "mutual": i["mutual"],
                      "roster_delta": 0})
    ideas += pkgs
    ideas.sort(key=lambda i: (not i["mutual"], -(i["you"] + max(0.0, i["them"]))))

    mutual = [i for i in ideas if i["mutual"]]
    # The two halves of every suggestion, folded: the deals, and what they cost
    # in keepers. Each drawer's line says what's in it.
    with st.container(key="drawers"):
        deal_col = _drawer("Proposals", (f"{len(mutual)} clear for both sides" if mutual
                                         else f"{len(ideas)} considered · none help both sides"))
        keep_col = _drawer("Keeper cost", "what the players in these deals cost to keep next year")
    _tables = deal_col
    with keep_col:
        # C — the keeper lens sits BESIDE the deals, not 400px below them. These are
        # the two facts you have to weigh against each other, and having to scroll
        # between them was the real reason this screen felt wrong.
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
            _note("In a keeper league every trade is two trades: this season's points and "
                       "next season's price. A player who costs a last-round pick and is worth "
                       "an early one is rarely worth a couple of points a week.")
        else:
            _note("No keeper rules configured for this league.")

    if not ideas:
        _note(where=_tables, text="Nothing with this team improves your lineup this week — one-for-one or packaged.")
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
            _note(where=_tables, text=f"**{len(mutual)} of these actually clear** — both lineups improve. Those are "
                       "the ones to send. The rest are listed so you can see they were considered "
                       "and rejected, not overlooked.")
            risky = [i for i in mutual if i.get("_ships_keeper")]
            if risky:
                worst = max((s_ for i in risky for _p, s_ in i["_ships_keeper"]))
                who = next(n for i in risky for p, n in zip(i["send"], i["send_names"])
                           if any(p == q for q, _s in i["_ships_keeper"]))
                _alert("amb", "!", f'<b>These verdicts are about this week only.</b> The deal above '
                                   f'ships <b>{who}</b>, who the Keepers tab rates at <b>+{worst} '
                                   f'keeper value</b> next year. A couple of points a week is '
                                   f'rarely worth a keeper that cheap — check the Keepers tab before '
                                   f'you send it.')
        else:
            _note(where=_tables, text="**None of these help both sides.** One-for-ones only work when two managers "
                       "have mirrored holes, which is rare; packages are where most real trades "
                       "live, and none clears here either. Try another partner.")
        _note(where=_tables, text="A 2-for-1 also costs you a roster spot, which this does not price — the freed "
                   "slot is only worth something if there is a waiver add worth making.")


def _roster_id(g, owner_id):
    return (g["rosters"].get(str(owner_id)) or {}).get("roster_id")


def _team_of(ctx, g, roster_id):
    """Manager name for a roster_id — for "2027 R4 (via Ned)"."""
    for owner, r in g["rosters"].items():
        if r.get("roster_id") == roster_id:
            return _owner_name(ctx, owner)
    return None


def _pool_watch_data(ctx, g) -> Optional[dict]:
    """This week's 2027 pool against the last snapshot: who fell into it (a
    projected keeper nobody would keep now), who left it (newly kept), and the
    projected-ADP movers. Saves this week's snapshot the first time it's seen."""
    from .. import nextyear as NY, userstate as US
    meta = ctx["meta"]
    n = int(getattr(meta, "num_teams", 10) or 10)
    w8 = getattr(meta, "scoring_weights", None) or {}
    ppr = 1.0 if float(w8.get("rec", 1.0)) >= 0.75 else 0.5 if float(w8.get("rec", 1.0)) >= 0.25 else 0.0
    proj = NY.projected(n, ppr)
    if not proj:
        return None
    kept = sorted({str(r["pid"]) for rows_ in _league_keepers(ctx, g).values() for r in rows_})
    ranks = {pid: v["rank"] for pid, v in proj.items() if v.get("rank") and v["rank"] <= 220}
    lk = ctx["league_key"]
    wk = f'{g["season"]}-{int(g["week"]):02d}'
    snaps = US.pool_snaps(lk)
    if wk not in snaps:
        US.save_pool_snap(lk, wk, {"ranks": ranks, "kept": kept})
    prev_keys = sorted(k for k in snaps if k < wk)
    if not prev_keys:
        return {"since": None}
    pk = prev_keys[-1]
    prev = snaps[pk]
    pr, pkept = prev.get("ranks") or {}, set(prev.get("kept") or [])
    into = [p for p in pkept if p not in set(kept)]
    out_ = [p for p in kept if p not in pkept]
    movers = sorted(((pr[p] - ranks[p], p) for p in ranks if p in pr and ranks[p] <= 150),
                    key=lambda x: -abs(x[0]))
    up = [(d, p) for d, p in movers if d > 0][:6]
    down = [(d, p) for d, p in movers if d < 0][:6]
    since = "week " + str(int(pk.split("-")[1]))
    bits = [f"{len(into)} into the pool" if into else "", f"{len(out_)} newly kept" if out_ else "",
            f"top riser {_esc_(ctx['registry'].meta(up[0][1]).name)} +{up[0][0]}" if up else ""]
    return {"since": since, "into": into, "out": out_, "up": up, "down": down, "ranks": ranks,
            "summary": f"since {since} · " + (" · ".join(b for b in bits if b) or "no change")}


def _pool_watch(ctx, g, d) -> None:
    reg = ctx["registry"]
    nxt = int(g["season"]) + 1

    def nm(p):
        try:
            m = reg.meta(p)
            return f"{m.name} · {m.position}"
        except Exception:  # noqa: BLE001
            return str(p)

    def col(title, items, cls):
        body = "".join(f'<div class="pw-r"><span>{_esc_(t)}</span><b class="{cls}">{v}</b></div>' for t, v in items) \
            or '<div class="pw-r"><span class="ws-dim">nobody</span></div>'
        return f'<div class="pw-c"><div class="ws-h">{title}</div>{body}</div>'
    rk = d["ranks"]
    html = ('<div class="pw">'
            + col(f"Fell into the {nxt} pool", [(nm(p), f"#{rk.get(p, '—')}") for p in d["into"][:8]], "in")
            + col("Newly kept (left the pool)", [(nm(p), f"#{rk.get(p, '—')}") for p in d["out"][:8]], "out")
            + col("Projected ADP risers", [(nm(p), f"+{x}") for x, p in d["up"]], "in")
            + col("Projected ADP fallers", [(nm(p), f"{x}") for x, p in d["down"]], "out")
            + '</div>')
    st.markdown(html, unsafe_allow_html=True)
    _note(f"Compared with the snapshot from {d['since']}. The pool is everyone no team is projected to keep; "
          f"a player falls into it when his keeper price stops being worth it to whoever holds him. "
          f"Ranks are the projected {nxt} ADP.")


# a draft pick's rough trade weight by round — the shape every pick chart
# shares (a first is worth about two thirds again a second, and the gap
# narrows): enough to say what a fair "get my first back" offer looks like
def _pick_weight(rnd: int) -> float:
    return 100.0 * max(1, int(rnd)) ** -0.8


def _unlock_panel(ctx, g, rows) -> None:
    """Keepers the bylaw blocks because the pick they'd cost was traded away:
    who holds a pick that would let him be kept, a fair package of your later
    picks for it, and a button that loads the deal into the Trades checker."""
    nxt = str(int(g["season"]) + 1)
    me = str(g["me"])
    my_rid = _roster_id(g, me)
    owner_of_rid = {r.get("roster_id"): o for o, r in g["rosters"].items()}
    allp = g.get("picks") or {}
    mine = sorted((pk for pk in allp.get(int(my_rid), []) if str(pk.get("season")) == nxt),
                  key=lambda pk: int(pk["round"])) if my_rid is not None else []
    my_menu = {lab: pk for lab, pk in _pick_menu(ctx, g, me).items()}
    lk = ctx["league_key"]
    # never offer a pick one of your planned keepers already sits on
    _kept = {}
    for k_ in _keeper_rows(ctx, g):
        if k_.get("verdict") == "keep" and k_.get("cost_round"):
            _kept[int(k_["cost_round"])] = _kept.get(int(k_["cost_round"]), 0) + 1
    _held = {}
    for pk in mine:
        _held[int(pk["round"])] = _held.get(int(pk["round"]), 0) + 1

    def _spare(rnd):
        return _held.get(rnd, 0) > _kept.get(rnd, 0)
    _need = {}
    for r in rows:
        _need[int(r.get("cost_round") or 1)] = _need.get(int(r.get("cost_round") or 1), 0) + 1
    shown = 0
    for r in rows[:4]:
        need = int(r.get("cost_round") or 1)
        offers = []
        for rid, pks in allp.items():
            if my_rid is not None and int(rid) == int(my_rid):
                continue
            oid = owner_of_rid.get(int(rid))
            if not oid:
                continue
            menu = _pick_menu(ctx, g, oid)
            for lab, pk in menu.items():
                if str(pk.get("season")) == nxt and int(pk["round"]) <= need:
                    offers.append((int(pk["round"]), str(oid), lab, pk))
        if not offers:
            continue
        # your own original pick first (the one that's easiest to ask back),
        # then the latest pick that still unlocks him — the cheapest to buy
        offers.sort(key=lambda x: (int(x[3].get("origin") or -1) != int(my_rid or -2), -x[0], _owner_name(ctx, x[1])))
        st.markdown(f'<div class="un-h"><b>{_esc_(r["name"])}</b><span>{_esc_(r.get("pos") or "")} · '
                    f'keeps at R{need} · <em>+{r.get("surplus")}</em> keeper value</span></div>',
                    unsafe_allow_html=True)
        for rnd, oid, lab, pk in offers[:3]:
            target = _pick_weight(rnd) * 0.95
            send, tot = [], 0.0
            for mp in [x for x in mine if int(x["round"]) > rnd and _spare(int(x["round"]))]:
                if tot >= target:
                    break
                send.append(mp)
                tot += _pick_weight(int(mp["round"]))
            sendl = [l for l, pk_ in my_menu.items() if any(pk_ is x for x in send)]
            ok = tot >= target
            c1, c2 = st.columns([4, 1.3], vertical_alignment="center")
            with c1:
                st.markdown(
                    f'<div class="un-r"><span class="un-w">{_esc_(_owner_name(ctx, oid))}</span>'
                    f'<span class="un-p">{_esc_(lab)}</span><span class="un-a">for</span>'
                    f'<span class="un-s">{_esc_(" + ".join(sendl) if sendl else "a player (no later picks to send)")}</span>'
                    f'<span class="un-v{"" if ok else " thin"}">{"fair by the pick chart" if ok else "light — add a player"}</span></div>',
                    unsafe_allow_html=True)
            with c2:
                def _go(oid=oid, lab=lab, sendl=sendl):
                    st.session_state[f"td_prefill_{lk}"] = {"oid": oid, "send": [], "get": [],
                                                           "sendp": list(sendl), "getp": [lab]}
                    st.session_state[f"nav_in_{lk}"] = "Trades"
                st.button("Load in Trades", key=f"unl_go_{lk}_{r['pid']}_{oid}_{rnd}", on_click=_go,
                          use_container_width=True)
            shown += 1
    _dup = [rd for rd, c in _need.items() if c > 1]
    if _dup:
        _note(f"One pick unlocks one keeper: {', '.join(f'{_need[d]} of these need R{d}' for d in _dup)}, "
              f"so it takes that many picks to keep them all.")
    if not shown:
        _note("Nobody else holds a pick early enough to unlock these.")
    else:
        _note(f"A keeper whose cost round you traded away moves **up** to the nearest earlier pick you own; "
              f"with none, he can't be kept. Any {nxt} pick in his round or earlier fixes that. The package "
              f"is your later {nxt} picks summed on a standard pick chart to just over the pick you get — "
              f"a starting offer, not a price.")


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
    st.markdown('<div class="ws-h">Build or check a trade</div>', unsafe_allow_html=True)
    _note(f"Paste in a real proposal — yours or one **{them}** sent you — and see what it "
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
        _note("Put at least one player or pick on each side.")
        return

    weeks_left = max(1, 14 - g["week"])
    n_teams = int(getattr(ctx["meta"], "num_teams", 12) or 12)
    # Keeper value both ways. Who you'd ship is priced on today's roster; who
    # you'd get is priced on the roster AFTER the trade — his own draft round
    # and keeper years travel with him, and "worth keeping" means making your
    # best five once he's there. Before this, only the outgoing half counted.
    _get_p = [opp_names[n] for n in get]
    _sent = {str(mine_names[n]) for n in send}
    in_rows = []
    if _get_p:
        try:
            _after = [p for p in g["mine"] if str(p) not in _sent] + _get_p
            in_rows = [k for k in _keeper_rows(ctx, g, pids=_after, from_owner=oid)
                       if str(k["pid"]) in {str(p) for p in _get_p}]
        except Exception:  # noqa: BLE001
            in_rows = []
    in_keep = [(reg.meta(k["pid"]).name, k) for k in in_rows]
    r = W.analyze_trade(g["mine"], opp, [mine_names[n] for n in send], _get_p,
                        g["slots"], g["proj"], reg, byes=g["byes"], week=g["week"],
                        keeper_rows=_keeper_rows(ctx, g) + in_rows, weeks_left=weeks_left,
                        send_picks=[my_picks[k] for k in sendp],
                        get_picks=[their_picks[k] for k in getp], n_teams=n_teams,
                        mode=st.session_state.get(f"td_resolved_{ctx['league_key']}", "balanced"))


    # What the deal does to the season, not just the week: the real remaining
    # schedule played 4,000 times with both teams' new lineups.
    odds = None
    try:
        si = _sim_inputs(ctx, g)
        if si["fx"]:
            me = str(g["me"])
            sent = {str(mine_names[n]) for n in send}
            got = {str(opp_names[n]) for n in get}
            my_new = [p for p in g["mine"] if str(p) not in sent] + [opp_names[n] for n in get]
            th_new = [p for p in opp if str(p) not in got] + [mine_names[n] for n in send]
            fx = {int(k): v for k, v in si["fx"].items()}
            base = W.season_sim(si["means"], si["sds"], si["recs"], si["pf"], fx, si["pt"], me,
                                median=si["median"],
                                n_sims=4000)
            means, sds = dict(si["means"]), dict(si["sds"])
            for who, pids in ((me, my_new), (str(oid), th_new)):
                means[who], sds[who] = W.team_distribution(pids, g["slots"], g["proj"], reg,
                                                           g["byes"], g["week"])
            after = W.season_sim(means, sds, si["recs"], si["pf"], fx, si["pt"], me, n_sims=4000,
                                 median=si["median"])
            odds = (base["teams"][me]["playoff_pct"], after["teams"][me]["playoff_pct"])
    except Exception:  # noqa: BLE001
        odds = None

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
    if odds:
        _cells.append(("Playoff odds", f'{odds[0]}→{odds[1]}%',
                       "on" if odds[1] > odds[0] else ("bad" if odds[1] < odds[0] else "")))
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

    # (the verdict is the card's own footer; it was printed twice)

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
        if in_keep:
            st.markdown('<div class="ws-h">Next year\'s price for who you get</div>',
                        unsafe_allow_html=True)
            st.markdown(_tbl(["Player", "Costs", "~Surplus"],
                             [[n, (f'R{k["cost_round"]} <span class="ws-fnt">{k["note"]}</span>'
                                   if k.get("cost_round") else '<span class="ws-fnt">—</span>'),
                               ('<span class="ws-dn">can\'t be kept</span>' if k.get("blocked") else
                                (f'<b class="ws-up">+{k["surplus"]}</b>' if (k.get("surplus") or 0) > 0
                                 else f'<span class="ws-fnt">{k.get("surplus") if k.get("surplus") is not None else "—"}</span>'))]
                              for n, k in in_keep],
                             widths=["auto", "44%", "96px"], wide=True), unsafe_allow_html=True)
        if r["out_keepers"]:
            st.markdown('<div class="ws-h">Keepers you would be shipping</div>',
                        unsafe_allow_html=True)
            st.markdown(_tbl(["Player", "Costs", "~Surplus"],
                             [[n, f'R{k["cost_round"]} <span class="ws-fnt">{k["note"]}</span>',
                               f'<b class="ws-up">+{k["surplus"]}</b>']
                              for n, k in r["out_keepers"]],
                             widths=["auto", "44%", "84px"], wide=True), unsafe_allow_html=True)
            _note("These cost a late pick and are worth an early one. Giving one up is a "
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
            _note("Every pick is priced at the **middle of its round** — next year's draft "
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
            _note("Same ask, different player from you — the realistic negotiation.")
            st.markdown(_tbl(["Send instead", "~You", "~Them"],
                             [[c["send_names"][0], f'<b class="ws-up">+{c["you"]}</b>',
                               f'<span class="ws-up">+{c["them"]}</span>'] for c in counters],
                             widths=["auto", "78px", "78px"], wide=True), unsafe_allow_html=True)


# ------------------------------------------------------------------ 5 playoffs
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _fixtures(platform: str, league_id: str, first: int, last: int, _provider=None) -> dict:
    """{week: [(owner_a, owner_b), ...]} for the weeks still to play.

    Keyed by the same owner ids g["rosters"] uses: Sleeper owner_id (matchups
    come by roster_id and are paired on matchup_id), ESPN teamId."""
    out = {}
    if platform == "sleeper":
        try:
            r2o = {r["roster_id"]: str(r.get("owner_id")) for r in api.get_rosters(league_id) or []}
        except Exception:  # noqa: BLE001
            return {}
        for wk in range(first, last + 1):
            try:
                rows = api.get_matchups(league_id, wk) or []
            except Exception:  # noqa: BLE001
                continue
            by = {}
            for r in rows:
                if r.get("matchup_id") is not None:
                    by.setdefault(r["matchup_id"], []).append(r2o.get(r["roster_id"]))
            pairs = [tuple(v) for v in by.values() if len(v) == 2 and all(v)]
            if pairs:
                out[wk] = pairs
    elif _provider is not None and hasattr(_provider, "get_week_pairs"):
        for wk in range(first, last + 1):
            try:
                pr = _provider.get_week_pairs(wk) or {}
            except Exception:  # noqa: BLE001
                continue
            seen, pairs = set(), []
            for a, b in pr.items():
                if a not in seen:
                    seen |= {a, b}
                    pairs.append((str(a), str(b)))
            if pairs:
                out[wk] = pairs
    return out


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def _season_sim_cached(lk: str, week: int, bucket: int, means: dict, sds: dict, recs: dict,
                       pf: dict, fixtures: dict, pt: int, me: str, median: bool = False) -> dict:
    return W.season_sim(means, sds, recs, pf, {int(k): v for k, v in fixtures.items()}, pt, me,
                        median=median)


def _median_game(meta) -> bool:
    """Does this league also play the weekly median? (B&B and 7½ Men do: a
    second result every week, a win for each team in the top half.)"""
    if getattr(meta, "platform", "") != "sleeper":
        return False
    try:
        return bool(int(((api.get_league(str(meta.league_id)) or {}).get("settings") or {})
                        .get("league_average_match") or 0))
    except Exception:  # noqa: BLE001
        return False


def _sim_inputs(ctx, g) -> dict:
    """Everything the season sim needs, built once for Playoffs and the trade desk."""
    reg, meta = ctx["registry"], ctx["meta"]
    wks = SCH.playoff_weeks(meta)
    means, sds, recs, pf = {}, {}, {}, {}
    for oid, r in g["rosters"].items():
        if not r["players"]:
            continue
        m, s_ = W.team_distribution(r["players"], g["slots"], g["proj"], reg, g["byes"], g["week"])
        means[str(oid)], sds[str(oid)] = m, s_
        se = r.get("settings") or {}
        recs[str(oid)] = (int(se.get("wins") or 0), int(se.get("losses") or 0))
        pf[str(oid)] = float(se.get("fpts") or 0) + float(se.get("fpts_decimal") or 0) / 100
    pt = int((getattr(meta, "playoff_settings", None) or {}).get("teams") or 0)
    if not pt and meta.platform == "sleeper":
        pt = int(((api.get_league(str(meta.league_id)) or {}).get("settings") or {})
                 .get("playoff_teams") or 0)
    pt = min(pt or 4, max(1, len(means)))
    last_reg = (wks[0] - 1) if wks else 14
    fx = _fixtures(meta.platform, str(meta.league_id), g["week"], last_reg,
                   _provider=ctx.get("provider")) if last_reg >= g["week"] else {}
    return {"means": means, "sds": sds, "recs": recs, "pf": pf, "pt": pt, "fx": fx,
            "median": _median_game(meta)}


def _playoffs(ctx, g) -> None:
    reg, meta = ctx["registry"], ctx["meta"]
    wks = SCH.playoff_weeks(meta)
    means, sds, recs, pf = {}, {}, {}, {}
    for oid, r in g["rosters"].items():
        if not r["players"]:
            continue
        m, s = W.team_distribution(r["players"], g["slots"], g["proj"], reg, g["byes"], g["week"])
        means[str(oid)] = m
        sds[str(oid)] = s
        se = r.get("settings") or {}
        recs[str(oid)] = (int(se.get("wins") or 0), int(se.get("losses") or 0))
        pf[str(oid)] = float(se.get("fpts") or 0) + float(se.get("fpts_decimal") or 0) / 100
    # From the league meta, which both providers fill in — reading Sleeper's
    # endpoint here 404'd the whole tab for the ESPN league.
    pt = int((getattr(meta, "playoff_settings", None) or {}).get("teams") or 0)
    if not pt and meta.platform == "sleeper":
        pt = int(((api.get_league(str(meta.league_id)) or {}).get("settings") or {})
                 .get("playoff_teams") or 0)
    pt = pt or 4
    last_reg = (wks[0] - 1) if wks else 14
    weeks_left = max(0, last_reg - g["week"] + 1)
    me = str(g["me"])
    fx = _fixtures(meta.platform, str(meta.league_id), g["week"], last_reg,
                   _provider=ctx.get("provider")) if weeks_left else {}
    sim = {}
    if fx:
        sim = _season_sim_cached(ctx["league_key"], g["week"], _slow_bucket(g["season"], g["week"]),
                                 means, sds, recs, pf, {str(k): v for k, v in fx.items()},
                                 min(pt, len(means)), me, _median_game(meta))
    if sim:
        odds = sim["teams"]
    else:
        odds = {str(k): v for k, v in
                W.season_odds(means, sds, recs, weeks_left, min(pt, len(means))).items()}
    mine = odds.get(me, {})

    _tiles([
        ("Playoff odds", f'{mine.get("playoff_pct", 0)}%', f"top {pt} make it",
         "var(--green)" if mine.get("playoff_pct", 0) >= 50 else "var(--amber)"),
        ("Projected seed", f'{mine.get("avg_seed", 0):.1f}', f"of {len(means)} teams", "var(--ink)"),
        ("Playoff weeks", (f"{wks[0]}–{wks[-1]}" if len(wks) > 1 else str(wks[0])) if wks else "—",
         "derived from this league's settings", "var(--muted)"),
        ("Weeks to play", f"{weeks_left}", "before the bracket", "var(--muted)"),
    ])
    _odds = mine.get("playoff_pct", 0)
    _grid = []
    if sim and sim.get("seeds"):
        _likely = sim["seeds"].index(max(sim["seeds"])) + 1
        _line = f"to make it — most likely the {C._ordinal(_likely)} seed"
        _wk = sim.get("weeks") or []
        if _wk:
            _lev = lambda w: w["swing"] * 4 * (w["p_win"] / 100) * (1 - w["p_win"] / 100)  # noqa: E731
            _big = max(_wk, key=_lev)
            if _lev(_big) >= 3:
                _grid.append(("Biggest game", f'W{_big["week"]}',
                              f'vs {_owner_name(ctx, _big["opp"])} · {_big["p_win"]}%'))
    else:
        _line = f"to make it — top {pt} of {len(means)}"
    _rec = recs.get(me, (0, 0))
    _grid.append(("Record", f"{_rec[0]}-{_rec[1]}", f"{weeks_left} weeks to play"))
    st.markdown(C.hero_html(f"PLAYOFF ODDS · {g['season']}", f"{_odds}%", _line, grid=_grid, tone="ink"),
                unsafe_allow_html=True)
    if sim and sim.get("weeks"):
        wk_rows = [dict(w, opp_name=_owner_name(ctx, w["opp"])) for w in sim["weeks"]]
        rec = recs.get(me, (0, 0))
        st.markdown(C.season_arc_html(
            pct=mine.get("playoff_pct", 0), record=f"{rec[0]}-{rec[1]}", seeds=sim["seeds"],
            playoff_teams=min(pt, len(means)), weeks=wk_rows, n_sims=10000),
            unsafe_allow_html=True)
    try:
        _lottery_block(ctx, g)
    except Exception:  # noqa: BLE001 — a lottery hiccup must not take the tab down
        pass

    with st.container(key="drawers"):
        _lead = max(odds.items(), key=lambda kv: kv[1]["playoff_pct"])[0] if odds else None
        c1 = _drawer("Where everyone lands",
                     f"{len(odds)} teams" + (f" · {_owner_name(ctx, _lead)} most likely in" if _lead else ""))
        c2 = _drawer("Your players in the playoff weeks",
                     f"weeks {wks[0]}–{wks[-1]} strength of schedule" if wks else "strength of schedule")
        c3 = _drawer("Byes, through the playoffs", "every starter's bye and who could cover it")
    with c3:
        try:
            _bye_planner(ctx, g)
        except Exception:  # noqa: BLE001
            _note("Couldn't build the bye grid right now.")
    with c1:
        rws = []
        for oid, o in sorted(odds.items(), key=lambda kv: -kv[1]["playoff_pct"]):
            nm = _owner_name(ctx, oid)
            rws.append([f'<b>{nm}</b>' if oid == me else nm,
                        f'{recs.get(oid,(0,0))[0]}–{recs.get(oid,(0,0))[1]}',
                        f'{means.get(oid,0):.0f}',
                        f'{o["playoff_pct"]}%', f'{o["avg_seed"]:.1f}'])
        st.markdown(_tbl(["Team", "Record", "~Proj/wk", "~Playoffs", "~Seed"], rws,
                         widths=["auto", "76px", "84px", "84px", "68px"]), unsafe_allow_html=True)
    with c2:
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
            _note("Playoff strength-of-schedule needs the DvP table — it builds on the "
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
    for r in rows:
        games = r["w"] + r["l"]
        r["luck"] = W.luck(r["pf"], r["w"], games, all_pts) if games else None

    # every team's rank at every position, by projected points
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
    pos_rank = {pos: {o: i for i, o in enumerate(sorted(tot, key=lambda o: -tot[o]), 1)}
                for pos, tot in pos_tot.items()}

    # ---- the cover: your power rank, what the bench cost, luck, best spot -----
    me_row = next((r for r in rows if r["oid"] == g["me"]), None)
    my_rank = (rows.index(me_row) + 1) if me_row else None
    _grid = []
    # What the set lineup scored each finished week against the best it could
    # have, from ACTUAL points. Sleeper keeps players_points per week; ESPN's
    # history read is a per-week roster fetch and is left for later.
    if meta.platform == "sleeper" and g["week"] > 1:
        _hist = _bench_history(str(meta.league_id), g["me"], g["week"])
        br = WV.bench_regret(_hist, g["slots"], reg)
        if br["n"]:
            _grid += [("Bench regret", f'{br["total_left"]:.1f}',
                       f'points left on your bench · {br["n"]} wk{"s" if br["n"] != 1 else ""}'),
                      ("Perfect weeks", f'{sum(1 for r in br["weeks"] if r["left"] < 0.05)}',
                       f'of {br["n"]}')]
    _lk = (me_row or {}).get("luck")
    if _lk and _lk["label"] != "—":
        _grid.append(("Your luck", f'{_lk["delta"]:+.1f}',
                      "wins vs your all-play record"))
    _mine_ranks = {pos: rk[g["me"]] for pos, rk in pos_rank.items() if g["me"] in rk}
    if _mine_ranks:
        _bp = min(_mine_ranks, key=lambda p: _mine_ranks[p])
        _grid.append(("Best position", _bp, f"{C._ordinal(_mine_ranks[_bp])} of {len(pos_rank[_bp])}"))
    if my_rank:
        _rec = f'{me_row["w"]}-{me_row["l"]}'
        _how = ("and the record undersells you" if _lk and _lk["label"] == "unlucky" else
                "and the record flatters you" if _lk and _lk["label"] == "lucky" else
                "and the record is about right")
        st.markdown(C.hero_html(f"{meta.name.upper() if getattr(meta, 'name', '') else 'THE LEAGUE'} · POWER RANKINGS",
                                C._ordinal(my_rank), f"by roster strength — you're {_rec}, {_how}",
                                grid=_grid[:4] or None, tone="ink"), unsafe_allow_html=True)

    c1, c2 = st.columns([1.25, 1])
    with c1:
        st.markdown('<div class="ws-h">Power rankings — projected points a week</div>',
                    unsafe_allow_html=True)
        st.markdown(C.power_list_html([
            {"rank": i, "name": r["name"], "rec": f'{r["w"]}–{r["l"]}', "pf": r["pf"], "proj": r["proj"],
             "luck": ((r["luck"] or {}).get("label") if (r["luck"] or {}).get("label") != "—" else ""),
             "me": r["oid"] == g["me"]} for i, r in enumerate(rows, 1)]), unsafe_allow_html=True)
        _note("Luck compares wins to an all-play record — how often this team's scoring would have "
              "beaten the rest of the league. A lucky team scoring bottom-third regresses, and that is "
              "the week to trade with them.")
    with c2:
        st.markdown('<div class="ws-h">Positional strength — rank of '
                    f'{len(rows)}, redder is stronger</div>', unsafe_allow_html=True)
        st.markdown(C.pos_heat_html([
            ("You" if r["oid"] == g["me"] else r["name"].split()[0],
             {pos: rk.get(r["oid"]) for pos, rk in pos_rank.items()}, r["oid"] == g["me"])
            for r in rows]), unsafe_allow_html=True)
        st.markdown('<div class="ws-h" style="margin-top:14px">On the wire</div>', unsafe_allow_html=True)
        tx = W.transactions(str(meta.league_id), g["week"]) if meta.platform == "sleeper" else []
        if not tx:
            _note("No completed transactions yet.")
        else:
            rid_to_name = {r.get("roster_id"): _owner_name(ctx, oid) for oid, r in g["rosters"].items()}
            _verb = {"waiver": "claimed", "free_agent": "added", "trade": "traded for"}
            feed = []
            for t in tx[:8]:
                who = " & ".join(rid_to_name.get(x, "?") for x in (t["roster_ids"] or [])[:2])
                adds = ", ".join(reg.meta(p).name for p in list(t["adds"] or {})[:2])
                if not adds:
                    drops = ", ".join(reg.meta(p).name for p in list(t.get("drops") or {})[:2])
                    feed.append((f'W{t["week"]}', who, "dropped", drops or "—", ""))
                    continue
                feed.append((f'W{t["week"]}', who, _verb.get(t["type"], t["type"]), adds,
                             f'${t["bid"]}' if t.get("bid") else ""))
            st.markdown(C.feed_html(feed), unsafe_allow_html=True)


@st.cache_data(ttl=3600, show_spinner=False)
def _bench_history(league_id: str, owner_id: str, upto_week: int) -> dict:
    """{week: {starters, players, points}} for every FINISHED week."""
    rid = next((r.get("roster_id") for r in (api.get_rosters(league_id) or [])
                if str(r.get("owner_id")) == str(owner_id)), None)
    out = {}
    if rid is None:
        return out
    for wk in range(1, int(upto_week)):
        try:
            ms = api.get_matchups(league_id, wk) or []
        except Exception:  # noqa: BLE001
            continue
        m = next((x for x in ms if x.get("roster_id") == rid), None)
        if not m or not m.get("players_points"):
            continue
        out[wk] = {"starters": [str(p) for p in (m.get("starters") or [])],
                   "players": [str(p) for p in (m.get("players") or [])],
                   "points": m.get("players_points") or {}}
    return out


# ------------------------------------------------------------------- 7 keepers
@st.cache_data(ttl=900, show_spinner=False)
def _draft_rounds(league_id: str, owner: str = ""):
    """{pid: (round, picked_by)} for EVERY pick in the league's own draft.

    Every pick, not just his: the round travels with the player. He traded for
    Kenneth Walker and George Pickens precisely so he could keep them at the
    rounds Ned drafted them in — and when this kept only his own picks, both fell
    through to "waiver add" at the last round, which made every traded-for
    keeper look like a steal it was not.
    """
    named = K.configured_drafts(league_id)
    if named:
        # A league that names its drafts (7½ Men): only those boards count, a
        # board continued from another sits after it (its round 1 is the
        # league's round 11), and rookie-board picks are marked so they price
        # at the rookie-draft premium instead of their rookie-board round.
        out = {}
        for kind in ("veteran", "rookie"):
            offset = 0
            for did in named.get(kind) or []:
                try:
                    d = api.get_draft(did) or {}
                    picks = api.get_draft_picks(did) or []
                except Exception:  # noqa: BLE001
                    continue
                for q in picks:
                    if q.get("player_id") and q.get("round"):
                        out.setdefault(str(q["player_id"]),
                                       (int(q["round"]) + offset, str(q.get("picked_by") or ""), kind))
                offset += int((d.get("settings") or {}).get("rounds") or 0)
        return out
    try:
        did = (api.get_league(league_id) or {}).get("draft_id")
        return {str(q["player_id"]): (int(q["round"]), str(q.get("picked_by") or ""))
                for q in (api.get_draft_picks(did) or [])
                if q.get("player_id") and q.get("round")}
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
    rules["_last_round"] = K.price_rounds(rules, int(g["season"]), meta.draft_rounds)
    rules["_adp_policy"] = K.adp_policy(str(meta.league_id))

    raw = K.load_keepers(str(meta.league_id), g["season"]) or {}
    existing = {str(k.get("player_id")): k for k in (raw.get(str(g["me"])) or [])}
    rows = W.keeper_outlook(
        g["mine"], drafted_round=_draft_rounds(str(meta.league_id)), me=str(g["me"]),
        existing=existing, rules=rules, n_teams=meta.num_teams,
        adp_rank=_next_adp(ctx), registry=reg, proj=g["proj"],
            next_season=int(g["season"]) + 1, league_kept=raw,
            owned_rounds=_owned_rounds(ctx, g, g["me"]))

    keeps = [r for r in rows if r["verdict"] == "keep"]
    blocked = [r for r in rows if r["verdict"] == "blocked"]
    best = keeps[0] if keeps else None
    # the old tile strip, folded into the hero's grid
    _kgrid = [
        ("Keeper slots", f"{reg_max + rook_max}", f"{reg_max} regular + {rook_max} rookie"),
        ("Best value", best["name"].split()[-1] if best else "—",
         f"+{best['surplus']} keeper value" if best else ""),
        ("Blocked", f"{len(blocked)}", blocked[0]["blocked"] if blocked else "none aged out"),
        ("Escalation", f"−{rules.get('year2_bump_rounds', 0)} rds",
         f"a year · max {rules.get('max_keep_years', '—')} years"),
    ]

    # The answer first — the five he would keep, as faces in their slots — then
    # every player's whole price ladder. The table this replaces showed one
    # number per player, which is why the keeper bugs of September were
    # invisible: a price with no rule beside it cannot be checked.
    _last = int(rules.get("_last_round") or meta.draft_rounds or 14)
    _cheap = [r for r in keeps if (r.get("cost_round") or 0) >= _last - 2]
    if _cheap:
        _num, _line = str(len(_cheap)), (f"of your {len(keeps)} would cost a round-{_last - 2}-or-later pick"
                                         f" — <b>{_esc_(_cheap[0]['name'])}</b> at R{_cheap[0]['cost_round']}")
    elif keeps:
        _best = max(keeps, key=lambda r: r.get("surplus") or -99)
        _num, _line = f"+{_best.get('surplus') or 0}", f"keeper value — <b>{_esc_(_best['name'])}</b> is your best keep"
    else:
        _num, _line = "0", "keepers worth their price yet"
    st.markdown(C.hero_html(f"{int(g['season']) + 1} KEEPERS · IF THE SEASON ENDED TODAY", _num, _line, grid=_kgrid, tone="ink"),
                unsafe_allow_html=True)
    st.markdown(C.keeper_tray_html(keeps, reg_max, rook_max), unsafe_allow_html=True)
    # The tray above is the answer; the rest folds, each drawer saying what's in it.
    _best = keeps[0] if keeps else None
    with st.container(key="drawers"):
        _unl = [r for r in rows if r.get("blocked") and "you don't own" in str(r["blocked"])
                and (r.get("surplus") or 0) > 0]
        if _unl:
            with _drawer("Unlock blocked keepers",
                         f'{len(_unl)} keepable if you get the pick back · best {_unl[0]["name"]} +{_unl[0]["surplus"]}'
                         if len(_unl) else "", key=f"unl_{ctx['league_key']}"):
                _unlock_panel(ctx, g, sorted(_unl, key=lambda r: -(r.get("surplus") or 0)))
        try:
            _pw = _pool_watch_data(ctx, g)
        except Exception:  # noqa: BLE001 — a watch list, never worth the tab
            _pw = None
        if _pw:
            with _drawer("Pool watch", _pw.get("summary") or "first snapshot saved · changes show from next week",
                         key=f"pw_{ctx['league_key']}"):
                if _pw.get("since"):
                    _pool_watch(ctx, g, _pw)
                else:
                    _note(f"This week's {int(g['season']) + 1} pool is saved — every team's projected keepers and "
                          f"the projected ADP. From next week this shows who fell into the pool, who got kept, "
                          f"and who moved.")
        with _drawer("Your roster, priced year by year",
                     f"{len(rows)} players" + (f" · best value {_best['name']} +{_best['surplus']}" if _best else "")):
            st.markdown('<div class="kl-grid">' + "".join(C.keeper_card_html(r) for r in rows) + '</div>',
                        unsafe_allow_html=True)
            _note("**Value** is what keeping him is worth: his talent (a draft-value curve, the #1 "
                       "player ≈ 100) minus what his cost round's pick would actually land in this "
                       "league's draft once everyone's keepers are off the board. So an elite player "
                       "kept early still scores — an early pick only lands whoever's left — and a star "
                       "at a last-round price scores best of all. Cost comes from where he actually came "
                       "from — an existing keeper's round plus this league's "
                       f"−{rules.get('year2_bump_rounds', 0)}-round-per-year escalation, the round you "
                       "drafted him, the fixed rookie round, or the last round for a waiver add. **ADP** is "
               "next summer's ADP, projected from FantasyCalc's trade market: dynasty and redraft "
               "value averaged, and dynasty alone for a player on IR or out for the year, who "
               "keeps his value when every rest-of-season list drops him.")

        with _drawer(f"{int(g['season']) + 1} board", "every pick simulated — keepers in their slots, the rest by projected ADP",
                     key=f"nb_{ctx['league_key']}"):
            if _lazy(f"nb_{ctx['league_key']}", "Build next year's board"):
                try:
                    _next_board(ctx, g)
                except Exception:  # noqa: BLE001
                    _note("Couldn't build next year's board right now.")
        with _drawer(f"{int(g['season']) + 1} draft preview", "every team's keepers off the board, then your picks",
                     key=f"dp_{ctx['league_key']}"):
            if _lazy(f"dp_{ctx['league_key']}", "Show the preview"):
                try:
                    _draft_preview(ctx, g)
                except Exception:  # noqa: BLE001
                    _note("Couldn't build the draft preview right now.")
        _ch = (f"{blocked[0]['name']} has aged out" if blocked else
               "build trades around your cheap keepers")
        with _drawer("What this changes now", _ch):
            if blocked:
                b = blocked[0]
                _alert("red", "⊘", f'<b>{b["name"]} has aged out</b> — {b["blocked"]}. He is a rental '
                                   f'from here, so his trade value only falls. If you are selling, sell early.')
            cheap = [r for r in keeps if (r["surplus"] or 0) >= 25]
            if cheap:
                _alert("ok", "◎", "<b>" + ", ".join(r["name"] for r in cheap[:3]) + "</b> "
                                  "cost a late pick and are worth an early one. Those are the players "
                                  "an in-season trade should be built around, not the ones you sell.")
            edge = [r for r in rows if r["verdict"] == "cut" and (r["surplus"] or -99) > -5]
            if edge:
                _alert("amb", "!", f'<b>{edge[0]["name"]}</b> is the first man out — '
                                   f'{edge[0]["surplus"]:+d} value. If anyone above him gets hurt or '
                                   f'traded, he is your replacement keeper.')
            _alert("ok", "$", f'A waiver add costs <b>round {meta.draft_rounds}</b> to keep, so a '
                              f'mid-season breakout is the cheapest keeper available. Every claim '
                              f'from here competes with the list above, not with your bench.')

            used_r = sum(1 for r in keeps if r.get("slot_used") == "regular")
            used_k = sum(1 for r in keeps if r.get("slot_used") == "rookie")
            st.markdown(_tbl(["Slot type", "~Used", "~Max"],
                             [["Regular", str(used_r), str(reg_max)],
                              ["Rookie", str(used_k), str(rook_max)]]), unsafe_allow_html=True)
            _note("A rookie who misses the rookie allowance falls back to a regular slot rather "
                       "than being cut — otherwise a +64 rookie loses his place to a −19 veteran. "
                       "**If this league forbids that**, the rookie rows are the ones to check.")
