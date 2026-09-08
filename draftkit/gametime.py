"""The NFL week as it is actually played: kickoffs, game state, scores, and the
betting line — per team, per week, from ESPN's public scoreboard.

Sleeper's schedule feed gives the DAY of each game and nothing else. That is
enough to know a Thursday from a Sunday, but not enough for the three things the
in-season screens need on a Sunday:

  * WHICH SLOT a starter belongs in. A man who plays Thursday must sit in a
    rigid RB/WR slot so the FLEX stays open for a Sunday decision; that needs
    the ORDER of kickoffs, not just the day.
  * WHO IS STILL TO PLAY, live — needs each game's state (pre / in / post).
  * STREAMING. Ranking a defense or kicker by matchup needs the line: the
    opponent's implied total for a D/ST, the team's own for a K.

One call per week returns all of it. It is cached to disk for an hour while no
game is live and for two minutes while one is, and the cache is keyed by week so
last Sunday never leaks into this one.

Everything degrades to "unknown" rather than raising: a screen that cannot
reach ESPN must still render, it just cannot order by kickoff.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

from . import config

_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
# NO User-Agent, deliberately. ESPN's site API answers a browser UA with a 403
# HTML page and a custom one the same way; the bare default gets JSON every
# time. Measured, not guessed — three header variants, one of them worked.
_HEADERS: Dict[str, str] = {}

# ESPN's abbreviations differ from Sleeper's in a few places.
_ABBR = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR"}


def _abbr(a: str) -> str:
    a = (a or "").upper()
    return _ABBR.get(a, a)


def _cache_path(season: int, week: int):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR / f"games_{season}_w{week}.json"


def load_week(season: int, week: int, *, max_age: Optional[int] = None) -> Dict[str, dict]:
    """{team: {opp, home, kickoff (ISO UTC), state, score, opp_score, spread,
    total, implied, opp_implied, name}} for every team playing that week.

    `state` is ESPN's: "pre", "in", "post". A team on bye is simply absent.
    """
    p = _cache_path(season, week)
    cached = None
    if p.exists():
        try:
            cached = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            cached = None
    if cached is not None:
        live = any(v.get("state") == "in" for v in cached.values())
        ttl = max_age if max_age is not None else (120 if live else 3600)
        if (time.time() - p.stat().st_mtime) < ttl:
            return cached
    try:
        r = requests.get(_URL, params={"week": int(week), "seasontype": 2,
                                       "dates": int(season)},
                         headers=_HEADERS, timeout=15)
        r.raise_for_status()
        events = (r.json() or {}).get("events") or []
    except Exception:  # noqa: BLE001
        return cached or {}
    out: Dict[str, dict] = {}
    for e in events:
        comp = (e.get("competitions") or [{}])[0]
        state = ((comp.get("status") or {}).get("type") or {}).get("state") or "pre"
        kick = e.get("date") or ""
        odds = (comp.get("odds") or [{}])[0] or {}
        total = odds.get("overUnder")
        details = str(odds.get("details") or "")       # "SEA -3"
        teams = comp.get("competitors") or []
        if len(teams) != 2:
            continue
        by_side = {}
        for t in teams:
            ab = _abbr((t.get("team") or {}).get("abbreviation"))
            by_side[t.get("homeAway")] = (ab, t)
        if "home" not in by_side or "away" not in by_side:
            continue
        (hab, ht), (aab, at) = by_side["home"], by_side["away"]
        # Favourite from the odds string; spread is the favourite's number.
        fav, spread = None, None
        try:
            parts = details.split()
            if len(parts) == 2:
                fav, spread = _abbr(parts[0]), abs(float(parts[1]))
        except Exception:  # noqa: BLE001
            fav, spread = None, None
        implied = {}
        if total is not None and spread is not None and fav in (hab, aab):
            dog = aab if fav == hab else hab
            implied[fav] = round((float(total) + spread) / 2, 1)
            implied[dog] = round((float(total) - spread) / 2, 1)
        elif total is not None:
            implied[hab] = implied[aab] = round(float(total) / 2, 1)
        for ab, t, opp, home in ((hab, ht, aab, True), (aab, at, hab, False)):
            try:
                sc = float(t.get("score") or 0)
            except (TypeError, ValueError):
                sc = 0.0
            out[ab] = {"opp": opp, "home": home, "kickoff": kick, "state": state,
                       "score": sc, "spread": (spread if fav == ab else (-spread if spread else None)),
                       "total": total, "implied": implied.get(ab),
                       "opp_implied": implied.get(opp),
                       "name": e.get("shortName") or f"{aab} @ {hab}"}
        # opponent scores, second pass
    for ab, g in out.items():
        g["opp_score"] = out.get(g["opp"], {}).get("score", 0.0)
    # Never cache nothing: an empty week written to disk is served as "no games"
    # for the next hour, which is how a single failed call blanked the screen.
    if out:
        try:
            p.write_text(json.dumps(out))
        except Exception:  # noqa: BLE001
            pass
    return out or (cached or {})


def kickoff_ts(g: Optional[dict]) -> float:
    """Kickoff as a unix timestamp, or +inf for a team with no game (bye / unknown)
    so it sorts LAST — a bye-week man belongs nowhere early."""
    if not g or not g.get("kickoff"):
        return float("inf")
    try:
        return datetime.fromisoformat(g["kickoff"].replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return float("inf")


def day_label(g: Optional[dict]) -> str:
    """"Thu 8:15", "Sun 1:00", "Mon 8:15" — local to US Eastern, which is how
    every fantasy player already thinks about kickoff."""
    if not g or not g.get("kickoff"):
        return "—"
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(g["kickoff"].replace("Z", "+00:00")).astimezone(
            ZoneInfo("America/New_York"))
        h = dt.strftime("%I:%M").lstrip("0")
        return f"{dt.strftime('%a')} {h}"
    except Exception:  # noqa: BLE001
        return "—"


def status(g: Optional[dict]) -> str:
    """"pre" / "in" / "post" / "bye"."""
    if not g:
        return "bye"
    return g.get("state") or "pre"


def any_live(games: Dict[str, dict]) -> bool:
    return any(v.get("state") == "in" for v in (games or {}).values())


def week_phase(games: Dict[str, dict], now: Optional[float] = None) -> str:
    """Where the week is: "waivers" (before the first kickoff, Tue-Wed),
    "setup" (Thu-Sun before 1:00), "live" (a game is on), "late" (only SNF/MNF
    left), "done" (every game final)."""
    now = now or time.time()
    if not games:
        return "setup"
    states = [v.get("state") for v in games.values()]
    if all(s == "post" for s in states):
        return "done"
    if any(s == "in" for s in states):
        return "live"
    kicks = sorted(kickoff_ts(v) for v in games.values() if v.get("state") == "pre")
    if not kicks:
        return "done"
    first = kicks[0]
    # Tue/Wed of NFL week: more than ~2 days before the first pre-game kickoff.
    try:
        from zoneinfo import ZoneInfo
        wd = datetime.fromtimestamp(now, ZoneInfo("America/New_York")).weekday()
    except Exception:  # noqa: BLE001
        wd = 1
    if wd in (1, 2) and first - now > 6 * 3600:
        return "waivers"
    if any(s == "post" for s in states):
        return "late"
    return "setup"
