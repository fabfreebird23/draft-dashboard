"""Every league's week in one row each — the numbers Home needs to answer "does
anything need me" without a click.

This deliberately reuses the in-season engine (`weekly`, `weekview`) rather than
inventing a cheaper approximation: a Home that says "lineup optimal" from a
different calculation than the Command Center is a Home that gets caught lying.
The cost is one roster read, one projection read and one optimiser pass per
league; Home caches the result for two minutes.

Everything is best-effort. A league that will not load gets a row that says so
and the other three still render — Home must never be blank because one host is
slow.
"""
from __future__ import annotations

from typing import Optional

from . import config, gametime as GT, inseason, phase as PH, sleeper_client as api, weekly as W, weekview as WV
from .providers import get_provider


def _names(provider, platform: str, league_id: str) -> dict:
    """{team_id: display name} — the same names the league page shows."""
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
                out.setdefault(str(u.get("user_id")), md.get("team_name") or u.get("display_name") or "")
        except Exception:  # noqa: BLE001
            pass
    return out


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


def _opponent(provider, platform, league_id, rosters, me, week):
    if platform != "sleeper":
        try:
            oid = (provider.get_week_pairs(week) or {}).get(str(me))
            return (str(oid) if oid and oid in rosters else None)
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


def pulse(preset: dict, registry, week: int, byes: Optional[dict] = None) -> dict:
    """One league's week. Keys: ok, name, platform, n_teams, record, me_name,
    opp_name, me_pts, opp_pts, win_pct, started, phase, played (n_played, n),
    chips [(text, kind)], tone, action ("Open"/"Decide"/"Fix lineup"), nav,
    n_claims, claim (dict|None), slot_moves, injuries, moves, error."""
    lid, plat = str(preset["league_id"]), preset.get("platform", "sleeper")
    season = int(preset.get("season") or config.current_season())
    me = str(preset.get("my_team") or "")
    out = {"ok": False, "name": preset.get("label") or lid, "platform": plat, "league_id": lid,
           "chips": [], "tone": "", "action": "Open", "nav": "Command Center", "n_claims": 0,
           "claim": None, "slot_moves": [], "injuries": [], "moves": [], "error": ""}
    try:
        provider = get_provider(plat, lid, season, registry,
                                espn_s2=preset.get("espn_s2"), swid=preset.get("swid"))
        meta = provider.get_league_meta()
        slots = provider.get_roster_slots()
        rosters = _rosters(provider, plat, lid)
        names = _names(provider, plat, lid)
        mine = (rosters.get(me) or {}).get("players") or []
        starters = (rosters.get(me) or {}).get("starters") or []
        if not mine:
            out["error"] = "no roster"
            return out
        from . import projections as PJ
        proj = PJ.for_league(meta, registry, season, week=week) or {}
        games = GT.load_week(season, week)
        phase = GT.week_phase(games)
        out.update({"name": meta.name or out["name"], "n_teams": meta.num_teams, "phase": phase})
        se = (rosters.get(me) or {}).get("settings") or {}
        if se.get("wins") is not None:
            out["record"] = f'{int(se.get("wins") or 0)}–{int(se.get("losses") or 0)}'
        lc = W.lineup_check(mine, slots, proj, registry, byes, week, current=starters)
        cur = lc["current"]
        oid = _opponent(provider, plat, lid, rosters, me, week)
        ost = ((rosters.get(oid) or {}).get("starters") or []) if oid else []
        opp = ((rosters.get(oid) or {}).get("players") or []) if oid else []
        om, os_ = (W.team_distribution(opp, slots, proj, registry, byes, week, current=ost)
                   if opp else (0.0, 1.0))
        me_mean = lc["current_total"] if lc["have_current"] else lc["mean"]
        wp = W.win_prob(me_mean, lc["sd"], om, os_) if opp else None
        live = {}
        started = phase in ("live", "late", "done") and bool(games)
        if started:
            try:
                live = provider.get_live_scores(week) or {}
            except Exception:  # noqa: BLE001
                live = {}
        me_live, opp_live = live.get(me) or {}, (live.get(oid) or {}) if oid else {}
        ps = WV.played_state(cur, registry, games, me_live)
        if started:
            me_pts = float(me_live.get("points") or 0)
            opp_pts = float(opp_live.get("points") or 0)
            me_end = WV.live_projection(cur, proj, registry, games, me_live)
            opp_end = WV.live_projection(list(zip(slots, ost)), proj, registry, games, opp_live) if opp else 0
            wp_now = W.win_prob(me_end, lc["sd"] * .7, opp_end, os_ * .7) if opp else None
            n_left = len(ps["pre"]) + len(ps["live"])
            mid = (f'{"WON" if me_pts > opp_pts else "LOST"} · {100*(wp or 0):.0f}% pre'
                   if phase == "done" else f'LIVE · {n_left} to play · {100*(wp_now or 0):.0f}%')
            out.update({"me_pts": f"{me_pts:.1f}", "opp_pts": f"{opp_pts:.1f}" if opp else "—",
                        "win_pct": 100 * (wp_now if wp_now is not None else (wp or 0)),
                        "mid": mid})
        else:
            out.update({"me_pts": f"{me_mean:.1f}", "opp_pts": f"{om:.1f}" if opp else "—",
                        "win_pct": (100 * wp) if wp is not None else None,
                        "mid": (f'NEXT · {100*wp:.0f}% you' if wp is not None else "NEXT")})
        out.update({"me_name": names.get(me) or "You",
                    "opp_name": (names.get(oid) or "Opponent") if oid else "No opponent",
                    "started": started, "played": (ps["n"] - len(ps["pre"]) - len(ps["live"]), ps["n"])})

        # ---- the chips: worst thing first ---------------------------------
        chips, worst = [], 0      # 0 fine · 1 amber · 2 red
        avail = W.availability_report(mine, slots, proj, registry, byes=byes, week=week,
                                      starters=starters)
        risky = avail["at_risk"]
        out["injuries"] = [(a["name"], a["status"], a.get("cost_if_out")) for a in risky]
        out["moves"] = lc["moves"]
        adv = WV.slot_advice(cur, registry, games) if lc["have_current"] else []
        _benching = {str(m["out"]) for m in lc["moves"]}
        adv = [a for a in adv if str(a["pid"]) not in _benching and str(a["swap_pid"]) not in _benching]
        out["slot_moves"] = adv
        if lc["moves"]:
            chips.append((f'{len(lc["moves"])} change{"s" if len(lc["moves"]) != 1 else ""} · +{lc["gain"]}', "w"))
            worst = max(worst, 1)
        elif adv:
            chips.append((f'{adv[0]["name"].split()[-1]} → {adv[0]["to_slot"]} ({adv[0]["day"].split()[0]})', "w"))
            worst = max(worst, 1)
        elif lc["have_current"]:
            chips.append(("lineup optimal", "g"))
        else:
            chips.append(("lineup unread", ""))
        if risky:
            a = risky[0]
            sev = max(x["severity"] for x in risky)
            _st = a["status"][:1].upper() if a["status"] else "?"
            txt = (f'{a["name"].split()[-1]} {_st}'
                   + (f' · {-(a["cost_if_out"] or 0):.1f}' if a.get("cost_if_out") else "")
                   + (f' +{len(risky) - 1}' if len(risky) > 1 else ""))
            chips.append((txt, "b" if sev >= 3 else "w"))
            worst = max(worst, 2 if sev >= 3 else 1)
        # the claim — only when waivers are the thing to do
        if phase in ("waivers", "setup", "done") and not started:
            try:
                taken = {p for r in rosters.values() for p in r["players"]}
                fas = inseason.free_agents(meta, registry, proj, taken, limit=60)
                board = W.waiver_board(mine, slots, proj, registry, fas, byes=byes, week=week, limit=3)
                # A claim worth six tenths is not "worth making before Wednesday";
                # under a point it is a tiebreak, and Home should not nag about it.
                top = next((r for r in board if r["gain"] >= 1.0), None)
                if top:
                    fa = inseason.faab(meta) or {}
                    budget = int(fa.get("budget") or 0)
                    left = max(0, budget - int((fa.get("by_owner") or {}).get(me, 0) or 0))
                    bid = W.bid_guidance(top["gain"], left, max(1, 14 - week)) if left else None
                    out["claim"] = {**top, "bid": bid, "left": left}
                    out["n_claims"] = 1
                    chips.append((f'{top["name"].split()[-1]} +{top["gain"]:.1f}'
                                  + (f' · ${bid["low"]}–{bid["high"]}' if bid else ""), "w"))
                    worst = max(worst, 1)
                else:
                    chips.append(("wire: nothing", ""))
            except Exception:  # noqa: BLE001
                pass
        if started and phase != "done":
            chips.insert(0, (f'{len(ps["pre"]) + len(ps["live"])} still to play', "l"))
        out["chips"] = chips[:3]
        out["tone"] = ("live" if (started and phase != "done") else
                       {0: "go", 1: "warn", 2: "bad"}[worst])
        # the button says what the click will DO
        if worst >= 2 or (risky and phase in ("setup", "live")):
            out["action"], out["nav"] = "Fix lineup", "Command Center"
        elif lc["moves"] or adv:
            out["action"], out["nav"] = "Decide", "Command Center"
        elif out["claim"] and phase in ("waivers", "done"):
            out["action"], out["nav"] = "Claim", "Waivers"
        elif started:
            out["action"], out["nav"] = "Watch", "Matchup"
        out["ok"] = True
        return out
    except Exception as e:  # noqa: BLE001
        out["error"] = type(e).__name__
        return out


def day_band(pulses: list, week: int, phase: str) -> dict:
    """The one line across every league: what today is for and how many things
    need doing. Returns {kicker, title, sub, number, label}."""
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        now = _dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001
        now = _dt.datetime.now()
    day = now.strftime("%A")
    ok = [p for p in pulses if p.get("ok")]
    claims = [p for p in ok if p.get("claim")]
    fixes = [p for p in ok if p.get("injuries") or p.get("moves")]
    seats = [p for p in ok if p.get("slot_moves")]
    live = [p for p in ok if p.get("started") and p.get("phase") != "done"]
    kicker = f"{day} · week {week} · {WV.phase_label(phase)}"
    if live:
        lead = sum(1 for p in live if _num(p.get("me_pts")) > _num(p.get("opp_pts")))
        return {"kicker": kicker, "title": f"Games on — leading in {lead} of {len(live)}",
                "sub": " · ".join(f'{p["name"]} {p.get("me_pts")}–{p.get("opp_pts")}' for p in live[:4]),
                "number": str(sum(len(p.get("chips") or []) and 1 for p in live)), "label": "live"}
    if phase == "waivers" and claims:
        return {"kicker": kicker,
                "title": f'{_n(len(claims), "claim")} worth making before Wednesday',
                "sub": " · ".join(f'{p["claim"]["name"]} for {p["name"]} (+{p["claim"]["gain"]:.1f})'
                                  for p in claims[:3]),
                "number": str(len(claims)), "label": "claims"}
    if fixes:
        return {"kicker": kicker,
                "title": f'{_n(len(fixes), "lineup")} to look at before kickoff',
                "sub": " · ".join((f'{p["name"]}: ' + (f'{p["injuries"][0][0]} {p["injuries"][0][1].lower()}'
                                                        if p.get("injuries") else f'{len(p["moves"])} change'))
                                  for p in fixes[:3]),
                "number": str(len(fixes)), "label": "to decide"}
    if seats:
        return {"kicker": kicker,
                "title": f'{_n(len(seats), "lineup")} to re-seat by kickoff',
                "sub": " · ".join(f'{p["name"]}: {p["slot_moves"][0]["name"]} → {p["slot_moves"][0]["to_slot"]}'
                                  for p in seats[:3]),
                "number": str(len(seats)), "label": "re-seat"}
    if phase == "done":
        return {"kicker": kicker, "title": "Week over — waivers open Tuesday",
                "sub": " · ".join(f'{p["name"]} {p.get("me_pts")}–{p.get("opp_pts")}' for p in ok[:4]),
                "number": None, "label": ""}
    return {"kicker": kicker, "title": "Nothing needs you right now",
            "sub": "Every lineup is optimal and seated by kickoff; nothing on the wire beats a starter.",
            "number": None, "label": ""}


def _n(n: int, word: str) -> str:
    return f"{'One' if n == 1 else 'Two' if n == 2 else 'Three' if n == 3 else str(n)} {word}{'' if n == 1 else 's'}"


def _num(s) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0
