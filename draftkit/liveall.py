"""Every league at once, live: four scoreboards, four sets of lineups, and the
one thing no single-league screen can tell you — which of your players are on
the field right now, and how many of your teams each of them is playing for.

The split here is deliberate and is what keeps a ten-second tick cheap:

  STATIC (`static_for`)  rosters, starters, slots, projections, names, this
      week's opponent. Four leagues of host round trips, ~8s cold. Refetched on
      the app's normal fifteen-minute clock.
  LIVE (`live_for`)      one uncached read of the league's live scores, joined
      against the static half and the shared ESPN scoreboard. One HTTP call per
      league per tick, and the four run in parallel.

Nothing in here touches Streamlit, so the UI can run the live half in a thread
pool without fighting the session's script-run context.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from . import config, gametime as GT, sleeper_client as api, weekly as W, weekview as WV
from .providers import get_provider


def _rosters(provider, platform: str, league_id: str) -> dict:
    if platform == "sleeper":
        out = {}
        for r in (api.get_rosters(league_id) or []):
            out[str(r.get("owner_id"))] = {
                "players": [str(p) for p in (r.get("players") or [])],
                "starters": [str(p) for p in (r.get("starters") or [])],
                "settings": r.get("settings") or {}, "roster_id": r.get("roster_id")}
        return out
    return provider.get_rosters() or {}


def _names(provider, platform: str, league_id: str) -> dict:
    out = {}
    try:
        for t in provider.get_draft_order() or []:
            out[str(t.team_id)] = t.name
    except Exception:  # noqa: BLE001
        pass
    if platform == "sleeper":
        try:
            for u in api.get_users(league_id) or []:
                md = u.get("metadata") or {}
                out.setdefault(str(u.get("user_id")),
                               md.get("team_name") or u.get("display_name") or "")
        except Exception:  # noqa: BLE001
            pass
    return out


def _opponent(provider, platform, league_id, rosters, me, week):
    if platform != "sleeper":
        try:
            oid = (provider.get_week_pairs(week) or {}).get(str(me))
            return str(oid) if oid and oid in rosters else None
        except Exception:  # noqa: BLE001
            return None
    try:
        ms = api.get_matchups(league_id, week) or []
        rid = (rosters.get(me) or {}).get("roster_id")
        mine = next((m for m in ms if m.get("roster_id") == rid), None)
        if mine and mine.get("matchup_id") is not None:
            o = next((m for m in ms if m.get("matchup_id") == mine["matchup_id"]
                      and m.get("roster_id") != rid), None)
            if o:
                return next((oid for oid, r in rosters.items()
                             if r.get("roster_id") == o.get("roster_id")), None)
    except Exception:  # noqa: BLE001
        pass
    return None


def static_for(preset: dict, registry, week: int, byes: Optional[dict] = None) -> dict:
    """The half of a league that does not change minute to minute."""
    lid, plat = str(preset["league_id"]), preset.get("platform", "sleeper")
    season = int(preset.get("season") or config.current_season())
    me = str(preset.get("my_team") or "")
    out = {"ok": False, "league_id": lid, "platform": plat,
           "name": preset.get("label") or lid, "error": "", "preset": preset}
    try:
        provider = get_provider(plat, lid, season, registry,
                                espn_s2=preset.get("espn_s2"), swid=preset.get("swid"))
        meta = provider.get_league_meta()
        rosters = _rosters(provider, plat, lid)
        if not (rosters.get(me) or {}).get("players"):
            out["error"] = "no roster"
            return out
        from . import projections as PJ
        names = _names(provider, plat, lid)
        oid = _opponent(provider, plat, lid, rosters, me, week)
        slots = provider.get_roster_slots()
        proj = PJ.for_league(meta, registry, season, week=week) or {}
        mine = rosters[me]["players"]
        starters = rosters[me]["starters"]
        ost = ((rosters.get(oid) or {}).get("starters") or []) if oid else []
        opp = ((rosters.get(oid) or {}).get("players") or []) if oid else []
        _, me_sd = W.team_distribution(mine, slots, proj, registry, byes, week, current=starters)
        opp_sd = me_sd
        if opp:
            _, opp_sd = W.team_distribution(opp, slots, proj, registry, byes, week, current=ost)
        se = (rosters.get(me) or {}).get("settings") or {}
        out.update({
            "ok": True, "provider": provider, "meta": meta, "season": season, "me": me,
            "oid": oid, "slots": slots, "proj": proj, "mine": mine, "starters": starters,
            "opp": opp, "ost": ost, "me_sd": me_sd, "opp_sd": opp_sd,
            "name": meta.name or out["name"],
            "me_name": names.get(me) or "You",
            "opp_name": (names.get(oid) or "Opponent") if oid else "No opponent",
            "record": (f'{int(se.get("wins") or 0)}–{int(se.get("losses") or 0)}'
                       if se.get("wins") is not None else ""),
        })
        return out
    except Exception as e:  # noqa: BLE001
        out["error"] = type(e).__name__
        return out


def _row(slot, pid, registry, games, pp, proj):
    """One lineup line: who, his game, his points, and whether he is on now."""
    if not pid or str(pid) in ("0", "None"):
        return {"slot": slot, "pid": "", "name": "(empty)", "sub": "nobody set",
                "clock": "—", "state": "pre", "pts": 0.0, "proj": 0.0}
    try:
        pm = registry.meta(pid)
    except Exception:  # noqa: BLE001
        return {"slot": slot, "pid": str(pid), "name": str(pid), "sub": "", "clock": "—",
                "state": "pre", "pts": float(pp.get(str(pid), 0) or 0), "proj": 0.0}
    gm = WV.game_of(registry, games, pid)
    opp = (("vs " if gm.get("home") else "@ ") + gm["opp"]) if gm else "bye"
    return {"slot": slot, "pid": str(pid), "name": pm.name, "pos": (pm.position or ""),
            "team": (pm.team or ""), "sub": f'{pm.team} · {opp}',
            "clock": GT.live_label(gm), "state": GT.status(gm),
            "pts": float(pp.get(str(pid), 0) or 0),
            "proj": float(proj.get(str(pid), 0) or 0)}


def live_for(stat: dict, week: int, games: dict) -> dict:
    """The moving half. One uncached read; everything else is arithmetic."""
    out = {"ok": False, "name": stat.get("name"), "league_id": stat.get("league_id"),
           "error": stat.get("error", ""), "preset": stat.get("preset")}
    if not stat.get("ok"):
        return out
    try:
        live = stat["provider"].get_live_scores(week, fresh=True) or {}
    except Exception as e:  # noqa: BLE001
        live, out["error"] = {}, type(e).__name__
    me_live = live.get(str(stat["me"])) or {}
    opp_live = (live.get(str(stat["oid"])) or {}) if stat.get("oid") else {}
    return {**out, "ok": True, "me_live": me_live, "opp_live": opp_live,
            "me_pts": float(me_live.get("points") or 0),
            "opp_pts": float(opp_live.get("points") or 0) if stat.get("oid") else 0.0}


def assemble(stat: dict, lv: dict, registry, games: dict, week: int) -> dict:
    """Static + live → everything one league row and its drawer need."""
    if not (stat.get("ok") and lv.get("ok")):
        return {"ok": False, "name": stat.get("name"), "error": stat.get("error") or lv.get("error"),
                "preset": stat.get("preset")}
    me_pp = (lv["me_live"].get("players") or {})
    op_pp = (lv["opp_live"].get("players") or {})
    mine_rows = [_row(s, p, registry, games, me_pp, stat["proj"])
                 for s, p in zip(stat["slots"], stat["starters"])]
    opp_rows = [_row(s, p, registry, games, op_pp, stat["proj"])
                for s, p in zip(stat["slots"], stat["ost"])] if stat.get("oid") else []
    started = {r["pid"] for r in mine_rows if r["pid"]}
    bench = []
    for pid in stat["mine"]:
        if str(pid) in started:
            continue
        bench.append(_row("BN", pid, registry, games, me_pp, stat["proj"]))
    bench.sort(key=lambda r: -r["pts"])
    cur = list(zip(stat["slots"], stat["starters"]))
    ocur = list(zip(stat["slots"], stat["ost"]))
    me_end = WV.live_projection(cur, stat["proj"], registry, games, lv["me_live"])
    opp_end = (WV.live_projection(ocur, stat["proj"], registry, games, lv["opp_live"])
               if stat.get("oid") else 0.0)
    wp = (W.win_prob(me_end, stat["me_sd"] * .7, opp_end, stat["opp_sd"] * .7)
          if stat.get("oid") else None)
    left = sum(1 for r in mine_rows if r["pid"] and r["state"] in ("pre", "in"))
    on_now = [r for r in mine_rows if r["state"] == "in"]
    tone = "close"
    if wp is not None:
        tone = "win" if wp >= 0.65 else ("lose" if wp <= 0.35 else "close")
    return {"ok": True, "name": stat["name"], "league_id": stat["league_id"],
            "platform": stat["platform"], "preset": stat["preset"], "record": stat["record"],
            "me_name": stat["me_name"], "opp_name": stat["opp_name"],
            "me_pts": lv["me_pts"], "opp_pts": lv["opp_pts"],
            "me_end": me_end, "opp_end": opp_end, "wp": wp, "tone": tone,
            "left": left, "on_now": on_now, "mine": mine_rows, "opp": opp_rows,
            "bench": bench[:6], "bench_pts": round(sum(r["pts"] for r in bench), 1),
            "me_live": lv["me_live"], "opp_live": lv["opp_live"]}


# ------------------------------------------------------------- the cross-league join
def exposure(leagues: List[dict]) -> Dict[str, dict]:
    """{pid: {name, team, pos, clock, state, pts, mine:[league names],
    against:[league names]}} — the same man across every league at once.

    This is the whole reason for a consolidated screen: a player you start in
    three leagues is three times the afternoon, and one who is also on an
    opponent's roster somewhere cuts both ways.
    """
    out: Dict[str, dict] = {}
    for lg in leagues:
        if not lg.get("ok"):
            continue
        for r in lg["mine"]:
            if not r["pid"]:
                continue
            d = out.setdefault(r["pid"], {**r, "mine": [], "against": []})
            d["mine"].append(lg["name"])
            d["pts"] = max(d.get("pts") or 0, r["pts"])
        for r in lg.get("opp") or []:
            if not r["pid"]:
                continue
            d = out.setdefault(r["pid"], {**r, "mine": [], "against": []})
            d["against"].append(lg["name"])
            d["pts"] = max(d.get("pts") or 0, r["pts"])
    return out


def game_exposure(leagues: List[dict], games: dict) -> List[dict]:
    """Every NFL game you have a starter in, with how many starters that is
    across all leagues. The slate is 16 games; this is the four you care about."""
    counts: Dict[str, int] = {}
    for lg in leagues:
        if not lg.get("ok"):
            continue
        for r in lg["mine"]:
            t = (r.get("team") or "").upper()
            if t:
                counts[t] = counts.get(t, 0) + 1
    seen, out = set(), []
    for t, n in counts.items():
        gm = (games or {}).get(t)
        if not gm:
            continue
        key = tuple(sorted([t, gm["opp"]]))
        if key in seen:
            continue
        seen.add(key)
        mine_n = n + counts.get(gm["opp"], 0)
        out.append({"team": t, "game": gm, "n": mine_n,
                    "home": (t if gm.get("home") else gm["opp"]),
                    "away": (gm["opp"] if gm.get("home") else t),
                    "home_score": int(gm["score"] if gm.get("home") else gm.get("opp_score") or 0),
                    "away_score": int((gm.get("opp_score") or 0) if gm.get("home") else gm["score"]),
                    "state": gm.get("state"), "label": GT.live_label(gm),
                    "down": gm.get("down") or "", "redzone": bool(gm.get("redzone")),
                    "kick": GT.kickoff_ts(gm)})
    order = {"in": 0, "post": 1, "pre": 2}
    out.sort(key=lambda x: (order.get(x["state"], 3), -x["n"]))
    return out


def red_zone(leagues: List[dict], games: dict) -> Optional[dict]:
    """The loudest thing that can be true right now: a team in the red zone that
    you have starters on. Returns the one with the most of your players."""
    best = None
    exp = exposure(leagues)
    for pid, d in exp.items():
        if d["state"] != "in" or not d["mine"]:
            continue
        gm = (games or {}).get((d.get("team") or "").upper())
        if not gm or not gm.get("redzone") or not gm.get("has_ball"):
            continue
        cand = {"name": d["name"], "team": d["team"], "leagues": d["mine"],
                "down": gm.get("down") or "", "opp": gm.get("opp"),
                "n": len(d["mine"]), "pts": d["pts"]}
        if best is None or cand["n"] > best["n"]:
            best = cand
    return best
