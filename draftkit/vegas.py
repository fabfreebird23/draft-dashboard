"""The market's projection: every NFL player prop Bovada posts, turned into a
fantasy line under each league's own scoring.

Why the book and not another set of rankings: a sportsbook does not publish a
fantasy projection, but it publishes every ingredient of one, priced by people
with money on it. Per game Bovada lists passing yards / attempts / touchdowns,
rushing yards, receptions, receiving yards, an anytime-touchdown price for every
skill player and kicking points for the kicker. Score those under PPR or half
or whatever the league uses and you have a fourth panel that reacts to news
faster than any human list.

Reading it:
  * the over/under line is the market's MEDIAN. The juice says which way the
    mean leans — Over −145 / Under +110 on 4.5 receptions is "a bit more than
    4.5" — so the line is nudged by the implied-probability gap. Small, real.
  * anytime-TD odds carry vig. They are devigged by normalising the game's
    scorer list against Bovada's own "Total Touchdowns" line for that game, so
    the probabilities have something honest to sum to.
  * QB passing TDs, interceptions and kicking points are their own markets.
  * no player market for D/ST — that stays with the implied-total streamer.

Public API, no key, no login: `www.bovada.lv/services/sports/event/coupon/...`,
the same feed sportsbot's Bovada lookup reads. One list call, then one call per
game (~16), cached to disk for an hour.
"""
from __future__ import annotations

import json
import math
import re
import time
from typing import Dict, List, Optional, Tuple

import requests

from . import config
from .names import normalize_name

_BASE = "https://www.bovada.lv/services/sports/event/coupon/events/A/description"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36",
            "Accept": "application/json"}
_TTL = 3600

# Bovada team code in "(ATL)" → ours. Only the ones that differ.
_TEAM = {"JAC": "JAX", "WSH": "WAS", "LA": "LAR"}

_GROUPS = {"TD Scorer Props", "Passing Props", "Passing Yards", "Rushing Yards",
           "Receiving Props", "Receiving Yards", "Kicking Props", "Touchdown Props"}


# ------------------------------------------------------------------ odds math
def american_to_prob(a) -> Optional[float]:
    """Implied probability (with vig) from an American price."""
    if a is None:
        return None
    s = str(a).strip().upper()
    if s in ("EVEN", "EV"):
        return 0.5
    try:
        v = int(s.replace("+", ""))
    except ValueError:
        return None
    return 100.0 / (v + 100.0) if v > 0 else (-v) / ((-v) + 100.0)


def _lean(line: float, over, under) -> float:
    """The line nudged toward the favoured side. The gap between the two implied
    probabilities says how far the mean sits from the median; a half-point of
    line per 10 points of probability gap is a modest, conventional scale."""
    po, pu = american_to_prob(over), american_to_prob(under)
    if po is None or pu is None:
        return line
    gap = (po - pu) / (po + pu)               # −1..1, positive = over favoured
    return line + gap * max(0.5, 0.05 * abs(line))


# ------------------------------------------------------------------ fetching
def _cache_path(season: int, week: int):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return config.DATA_DIR / f"vegas_{season}_w{week}.json"


def _get(url: str, timeout: int = 20):
    r = requests.get(url, headers=_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _events(doc) -> list:
    return [e for g in (doc or []) for e in (g.get("events") or [])]


def week_window(games: dict) -> Optional[Tuple[float, float]]:
    """(first kickoff − 12h, last kickoff + 12h) in epoch seconds for a
    gametime week, or None when the schedule is unknown."""
    from . import gametime as _GT
    ks = [_GT.kickoff_ts(g) for g in (games or {}).values()]
    ks = [k for k in ks if k != float("inf")]
    if not ks:
        return None
    return (min(ks) - 12 * 3600, max(ks) + 12 * 3600)


def fetch_raw(window: Optional[Tuple[float, float]] = None) -> List[dict]:
    """Every NFL event Bovada lists, with its full market list. `window` (from
    `week_window`) keeps it to this week's games — Bovada lists next week's
    Thursday game early, and a player must not carry two games' lines. Its
    event list names teams in full ("Atlanta Falcons"), so kickoff time is the
    honest filter, not abbreviations."""
    lst = _events(_get(f"{_BASE}/football/nfl?lang=en"))
    out = []
    for e in lst:
        link = e.get("link")
        if not link:
            continue
        if window:
            try:
                t = float(e.get("startTime") or 0) / 1000.0
            except (TypeError, ValueError):
                t = 0.0
            if t and not (window[0] <= t <= window[1]):
                continue
        try:
            full = _events(_get(f"{_BASE}{link}?lang=en"))
        except Exception:  # noqa: BLE001 — one game down must not lose the slate
            continue
        if full:
            out.append(full[0])
    return out


def _event_teams(e: dict) -> set:
    out = set()
    for c in e.get("competitors") or []:
        nm = (c.get("name") or "")
        out.add(nm)
    # "(ATL)" codes live on outcomes, not the event; names are matched later
    return out


def _pl(desc: str) -> Tuple[str, str]:
    """"Total Receiving Yards - DK Metcalf (PIT)" → ("DK Metcalf", "PIT")."""
    m = re.search(r"-\s*(.+?)\s*\((\w{2,3})\)\s*$", desc or "")
    if not m:
        return "", ""
    return m.group(1).strip(), _TEAM.get(m.group(2).upper(), m.group(2).upper())


def _outcome_pl(desc: str) -> Tuple[str, str]:
    """"Zachariah Branch (ATL)" → ("Zachariah Branch", "ATL")."""
    m = re.search(r"^(.+?)\s*\((\w{2,3})\)", desc or "")
    if not m:
        return "", ""
    return m.group(1).strip(), _TEAM.get(m.group(2).upper(), m.group(2).upper())


def parse(events: List[dict]) -> Dict[str, dict]:
    """{"name|TEAM": {name, team, lines{...}, exp{...}}} from raw events.

    `lines` keeps the raw market (line, over, under, or the TD price) for the
    board; `exp` is the expected stat the score is built from.
    """
    players: Dict[str, dict] = {}

    def slot(name, team):
        k = f"{name}|{team}"
        return players.setdefault(k, {"name": name, "team": team, "lines": {}, "exp": {}})

    for ev in events:
        game_td_total = None
        td_prices = {}                       # (name, team) -> american
        for g in ev.get("displayGroups") or []:
            gd = g.get("description") or ""
            if gd not in _GROUPS:
                continue
            for m in g.get("markets") or []:
                md = m.get("description") or ""
                per = ((m.get("period") or {}).get("description") or "Game")
                if per != "Game":
                    continue
                outs = m.get("outcomes") or []
                if gd == "Touchdown Props" and md == "Total Touchdowns":
                    ou = {o.get("description"): o for o in outs}
                    try:
                        game_td_total = _lean(float(ou["Over"]["price"]["handicap"]),
                                              ou["Over"]["price"].get("american"),
                                              ou["Under"]["price"].get("american"))
                    except Exception:  # noqa: BLE001
                        pass
                    continue
                if gd == "TD Scorer Props" and md == "Anytime Touchdown Scorer":
                    for o in outs:
                        nm, tm = _outcome_pl(o.get("description"))
                        if nm and "Def/ST" not in nm:
                            td_prices[(nm, tm)] = (o.get("price") or {}).get("american")
                    continue
                # over/under player markets
                nm, tm = _pl(md)
                if not nm:
                    continue
                ou = {o.get("description"): o for o in outs}
                if "Over" not in ou or "Under" not in ou:
                    continue
                try:
                    line = float(ou["Over"]["price"]["handicap"])
                except Exception:  # noqa: BLE001
                    continue
                key = {"Total Passing Yards": "pass_yd", "Total Passing Touchdowns": "pass_td",
                       "Total Interceptions Thrown": "pass_int", "Total Rushing Yards": "rush_yd",
                       "Total Receptions": "rec", "Total Receiving Yards": "rec_yd",
                       "Total Kicking Points": "kick_pts",
                       "Total Rushing Attempts": "rush_att", "Total Passing Attempts": "pass_att",
                       "Total Passing Completions": "pass_cmp"}.get(md.split(" - ")[0])
                if not key:
                    continue
                over, under = (ou["Over"]["price"].get("american"), ou["Under"]["price"].get("american"))
                p = slot(nm, tm)
                p["lines"][key] = {"line": line, "over": over, "under": under}
                p["exp"][key] = round(_lean(line, over, under), 2)
        # TD probabilities, devigged against the game's total-touchdowns line
        if td_prices:
            raw = {k: american_to_prob(v) for k, v in td_prices.items()}
            raw = {k: v for k, v in raw.items() if v is not None}
            # expected TDs per player from an anytime price: p(≥1) → λ with
            # λ = −ln(1−p) (Poisson), then scale so the game's λ sums to the
            # posted total. That strips the vig and the "everyone is +800" tail.
            lam = {k: -math.log(max(1e-6, 1.0 - v)) for k, v in raw.items()}
            tot = sum(lam.values())
            scale = (game_td_total / tot) if (game_td_total and tot) else 1.0
            for (nm, tm), price in td_prices.items():
                p = slot(nm, tm)
                p["lines"]["td"] = {"price": price, "prob": raw.get((nm, tm))}
                p["exp"]["td"] = round(lam.get((nm, tm), 0.0) * scale, 3)
    return players


# ------------------------------------------------------------------ scoring
_DEFAULT_W = {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6,
              "rec": 1.0, "rec_yd": 0.1, "rec_td": 6}


def score(exp: dict, weights: Optional[dict], pos: str) -> Optional[float]:
    """Fantasy points from expected stats. A non-passer's TD is rushing or
    receiving — priced the same in every league here, so `rush_td` stands in.
    Kicking points are already fantasy points."""
    if not exp:
        return None
    w = dict(_DEFAULT_W)
    for k, v in (weights or {}).items():
        if k in w:
            w[k] = v
    pts = 0.0
    for k, v in exp.items():
        if k == "td":
            if pos == "QB":
                # a QB's anytime TD is a rushing score
                pts += float(v) * float(w.get("rush_td", 6))
            else:
                pts += float(v) * float(w.get("rec_td", 6) if pos in ("WR", "TE") else w.get("rush_td", 6))
        elif k == "kick_pts":
            pts += float(v)
        elif k in w:
            pts += float(v) * float(w[k])
    return round(pts, 1)


def weekly(season: int, week: int, registry, weights: Optional[dict] = None,
           window: Optional[Tuple[float, float]] = None, tag: str = "") -> Dict[str, dict]:
    """{pid: {src:'vegas', pos, team, pts, pos_rank, exp{...}, lines{...}}}."""
    cp = _cache_path(season, week)
    raw = None
    try:
        if cp.exists() and (time.time() - cp.stat().st_mtime) < _TTL:
            raw = json.loads(cp.read_text())
    except Exception:  # noqa: BLE001
        raw = None
    if raw is None:
        try:
            events = fetch_raw(window)
            raw = parse(events)
        except Exception:  # noqa: BLE001
            raw = {}
        if not raw:
            # Bovada answers a Mac and refuses Streamlit Cloud (datacenter IP),
            # so the Mac PUBLISHES the parsed lines to the repo-backed doc store
            # on a schedule (`python -m draftkit.vegas publish`, launchd hourly)
            # and Cloud reads that copy. Stale disk is the last resort.
            try:
                from . import storage as _S
                doc = _S.load_doc("vegas", f"{season}_w{week}", {})
                raw = (doc or {}).get("players") or {}
                if raw:
                    raw = dict(raw)
                    raw["__meta__"] = {"published": (doc or {}).get("published"), "source": "mac"}
            except Exception:  # noqa: BLE001
                raw = {}
        if not raw:
            try:
                raw = json.loads(cp.read_text()) if cp.exists() else {}
            except Exception:  # noqa: BLE001
                raw = {}
        if raw:
            try:
                cp.write_text(json.dumps(raw))
            except Exception:  # noqa: BLE001
                pass
    meta = (raw or {}).pop("__meta__", None) if isinstance(raw, dict) else None
    idx: Dict[str, list] = {}
    for nm, p in registry.by_norm.items():
        if p.sleeper_pid:
            idx.setdefault(nm, []).append(p)
    out: Dict[str, dict] = {}
    for _k, r in (raw or {}).items():
        cands = idx.get(normalize_name(r["name"])) or []
        if not cands:
            continue
        pick = cands[0]
        if len(cands) > 1:
            same = [c for c in cands if (c.team or "").upper() == r["team"]]
            if len(same) != 1:
                continue
            pick = same[0]
        pos = (pick.position or "").upper()
        pos = "DST" if pos == "DEF" else pos
        if pos not in ("QB", "RB", "WR", "TE", "K"):
            continue
        pts = score(r.get("exp") or {}, weights, pos)
        if pts is None:
            continue
        out[str(pick.sleeper_pid)] = {"src": "vegas", "pos": pos, "team": r["team"], "pts": pts,
                                      "exp": r.get("exp") or {}, "lines": r.get("lines") or {}}
    for pos in {d["pos"] for d in out.values()}:
        ranked = sorted((pid for pid, d in out.items() if d["pos"] == pos),
                        key=lambda p: -(out[p]["pts"] or 0))
        for i, pid in enumerate(ranked, 1):
            out[pid]["pos_rank"] = i
    if meta and out:
        # carried on every row so a caption can say where the lines came from
        for d in out.values():
            d["published"] = meta.get("published")
    return out


# ------------------------------------------------------------------ publish
def publish(season: int, week: int, window: Optional[Tuple[float, float]] = None) -> int:
    """Fetch from Bovada HERE and write the parsed lines to the doc store, so a
    host Bovada refuses (Streamlit Cloud) can still read them. Returns the
    player count. Run hourly from the Mac by launchd."""
    import datetime as _dt
    from . import storage as _S
    raw = parse(fetch_raw(window))
    if not raw:
        return 0
    doc = {"season": season, "week": week, "published": _dt.datetime.now().isoformat(timespec="minutes"),
           "players": raw}
    _S.save_doc("vegas", f"{season}_w{week}", doc)
    try:
        _cache_path(season, week).write_text(json.dumps(raw))
    except Exception:  # noqa: BLE001
        pass
    return len(raw)


if __name__ == "__main__":
    import sys
    from . import gametime as _GT, sleeper_client as _api
    if len(sys.argv) > 1 and sys.argv[1] == "publish":
        season = config.current_season()
        st_ = _api.get_state("nfl") or {}
        week = max(1, int(st_.get("week") or 1)) if st_.get("season_type") == "regular" else 1
        n = publish(season, week, week_window(_GT.load_week(season, week)))
        print(f"vegas: published {n} players for {season} week {week}")


def headline(row: dict) -> str:
    """"62.5 yds · +140" — the position's yards line and the TD price."""
    if not row:
        return ""
    ln, pos = row.get("lines") or {}, row.get("pos")
    key = {"QB": "pass_yd", "RB": "rush_yd", "WR": "rec_yd", "TE": "rec_yd", "K": "kick_pts"}.get(pos)
    bits = []
    if key and key in ln:
        bits.append(f'{ln[key]["line"]:g} {"pts" if key == "kick_pts" else "yds"}')
    if pos == "QB" and "pass_td" in ln:
        bits.append(f'{ln["pass_td"]["line"]:g} TD')
    elif "td" in ln and ln["td"].get("price"):
        bits.append(str(ln["td"]["price"]))
    return " · ".join(bits)
