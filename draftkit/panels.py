"""Two more expert panels for the week: Flock Fantasy and the Fantasy Footballers.

FantasyPros' consensus (``ecr``) is the panel the app already reads. These are
the two he actually listens to, and both turn out to be readable with no login:

  * FLOCK — ``api.flockfantasy.com/rankings?format=WEEKLY`` answers an
    unsubscribed request with every analyst's weekly overall and positional rank
    for ~300 players (six analysts in week 1), plus the averages and tiers. The
    ``subscribed:false`` flag hides nothing that matters here.
  * THE BALLERS — the public weekly rankings pages embed a ``projections`` JSON
    array: Andy, Mike and Jason's weekly STAT projections for every QB/RB/WR/TE
    (~540 players × 3). Not ranks — projections — so they are scored under each
    league's own settings and ranked from that. Which is better than a rank: a
    rank cannot tell you a league that gives 6 a passing TD from one that gives 4.

Neither carries K or D/ST, so those keep FantasyPros only.

Rows are keyed by our pid like ``ecr`` is, with the same ``pos_rank`` idea, so
any screen that shows one panel can show three. A source that fails returns {}
and the screen says nothing for it, never an invented rank.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional

import requests

from . import config
from .names import normalize_name
from .udk import _extract_json_array

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36"}
_FLOCK = "https://api.flockfantasy.com/rankings"
_FFB = "https://www.thefantasyfootballers.com/{season}-{page}-rankings/"
_FFB_PAGES = ("quarterback", "running-back", "wide-receiver", "tight-end")
_TTL = 3 * 3600


def _cache(kind: str, season: int, week: int, tag: str = "") -> Path:
    return config.DATA_DIR / f"panel_{kind}_{season}_w{week}{('_' + tag) if tag else ''}.json"


def _fresh(p: Path) -> Optional[dict]:
    try:
        if p.exists() and (time.time() - p.stat().st_mtime) < _TTL:
            return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        pass
    return None


def _stale(p: Path) -> dict:
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _index(registry) -> Dict[str, list]:
    idx: Dict[str, list] = {}
    for nm, p in registry.by_norm.items():
        if p.sleeper_pid:
            idx.setdefault(nm, []).append(p)
    return idx


def _pid_for(idx, name: str, team: str) -> Optional[str]:
    cands = idx.get(normalize_name(name or "")) or []
    if not cands:
        return None
    if len(cands) > 1:
        same = [c for c in cands if (getattr(c, "team", "") or "").upper() == (team or "").upper()]
        if len(same) != 1:
            return None
        return str(same[0].sleeper_pid)
    return str(cands[0].sleeper_pid)


# ------------------------------------------------------------------- Flock
def flock_weekly(season: int, week: int, registry) -> Dict[str, dict]:
    """{pid: {pos_rank, rank, ranks{analyst: pos rank}, best, worst, std, tier,
    opp, n}} from Flock's weekly panel. `rank` is the weekly OVERALL rank
    (RB/WR/TE/QB against each other), `pos_rank` the positional one."""
    cp = _cache("flock", season, week)
    hit = _fresh(cp)
    if hit is not None:
        return hit
    try:
        r = requests.get(_FLOCK, params={"format": "WEEKLY"},
                         headers={**_UA, "Origin": "https://flockfantasy.com"}, timeout=20)
        r.raise_for_status()
        d = r.json() or {}
    except Exception:  # noqa: BLE001
        return _stale(cp)
    if int(d.get("week") or 0) != int(week) or not d.get("data"):
        # Flock's "current week" is theirs, not ours — a mismatch means the
        # panel has not turned over yet; stale is better than the wrong week.
        return _stale(cp)
    idx = _index(registry)
    out: Dict[str, dict] = {}
    for x in d.get("data") or []:
        pid = _pid_for(idx, x.get("playerName"), x.get("team"))
        if not pid:
            continue
        ranks = {k: v for k, v in (x.get("weeklyPositionalRanks") or {}).items() if v}
        vals = sorted(ranks.values())
        n = len(vals)
        avg = (sum(vals) / n) if n else None
        std = ((sum((v - avg) ** 2 for v in vals) / n) ** 0.5) if n and avg is not None else None
        out[pid] = {"src": "flock", "pos": x.get("position"), "team": x.get("team"),
                    "pos_rank": x.get("averageWeeklyPositionalRank") or avg,
                    "rank": x.get("averageRank"),
                    "ranks": ranks, "best": (vals[0] if vals else None),
                    "worst": (vals[-1] if vals else None), "std": std,
                    "tier": x.get("averagePositionalTier"), "opp": x.get("opponent") or "",
                    "n": n, "injury": x.get("injury")}
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(out))
    except Exception:  # noqa: BLE001
        pass
    return out


# ------------------------------------------------------------- the Ballers
_STAT_KEYS = {
    "passing_yards": "pass_yd", "passing_touchdowns": "pass_td",
    "interceptions_thrown": "pass_int", "passing_completions": "pass_cmp",
    "passing_attempts": "pass_att",
    "rushing_yards": "rush_yd", "rushing_touchdowns": "rush_td",
    "rushing_attempts": "rush_att",
    "receptions": "rec", "receiving_yards": "rec_yd", "receiving_touchdowns": "rec_td",
    "fumbles_lost": "fum_lost",
}
# a plain PPR book when the league's own weights are not known
_DEFAULT_W = {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6,
              "rec": 1.0, "rec_yd": 0.1, "rec_td": 6, "fum_lost": -2}


def _score(stats: dict, weights: dict) -> float:
    return sum(float(stats.get(k, 0) or 0) * float(weights.get(k, 0) or 0) for k in stats)


def ffb_raw(season: int, week: int) -> list:
    """The Ballers' weekly projection rows, every analyst, every skill player.
    All four pages embed the SAME array, so one page is enough; the others are
    fallbacks for a page that is slow or moved."""
    cp = _cache("ffb_raw", season, week)
    hit = _fresh(cp)
    if hit is not None:
        return hit
    rows = []
    for page in _FFB_PAGES:
        try:
            r = requests.get(_FFB.format(season=season, page=page), headers=_UA, timeout=25)
            r.raise_for_status()
            rows = _extract_json_array(r.text, "projections") or []
        except Exception:  # noqa: BLE001
            rows = []
        rows = [x for x in rows if int(x.get("week") or 0) == int(week)]
        if rows:
            break
    if not rows:
        return _stale(cp) or []
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(rows))
    except Exception:  # noqa: BLE001
        pass
    return rows


def ffb_weekly(season: int, week: int, registry, weights: Optional[dict] = None,
               tag: str = "") -> Dict[str, dict]:
    """{pid: {pos, pos_rank, pts, pts_by{analyst}, best, worst, std, risk, n,
    injury}} — the Ballers' projections scored under `weights` (Sleeper-style
    keys: pass_yd, pass_td, rec, ...), ranked within position by the average."""
    cp = _cache("ffb", season, week, tag or "ppr")
    hit = _fresh(cp)
    if hit is not None:
        return hit
    rows = ffb_raw(season, week)
    if not rows:
        return _stale(cp)
    w = dict(_DEFAULT_W)
    for k, v in (weights or {}).items():
        if k in w or k in _STAT_KEYS.values():
            w[k] = v
    idx = _index(registry)
    by_pid: Dict[str, dict] = {}
    for x in rows:
        pid = _pid_for(idx, x.get("name"), x.get("team"))
        if not pid:
            continue
        stats = {_STAT_KEYS[k]: x.get(k) for k in _STAT_KEYS if k in x}
        pts = round(_score(stats, w), 1)
        d = by_pid.setdefault(pid, {"src": "ffb", "pos": x.get("fantasy_position"),
                                    "team": x.get("team"), "pts_by": {}, "risk": 0.0,
                                    "injury": x.get("injury_status")})
        d["pts_by"][x.get("analyst_name") or "?"] = pts
        try:
            d["risk"] = max(d["risk"], float(x.get("risk") or 0))
        except (TypeError, ValueError):
            pass
    for pid, d in by_pid.items():
        vals = sorted(d["pts_by"].values())
        n = len(vals)
        d["n"] = n
        d["pts"] = round(sum(vals) / n, 1) if n else None
        d["best"], d["worst"] = (vals[-1] if vals else None), (vals[0] if vals else None)
        d["std"] = (round((sum((v - d["pts"]) ** 2 for v in vals) / n) ** 0.5, 1)
                    if n else None)
    # positional rank by average points
    for pos in {d["pos"] for d in by_pid.values()}:
        ranked = sorted((pid for pid, d in by_pid.items() if d["pos"] == pos),
                        key=lambda p: -(by_pid[p]["pts"] or 0))
        for i, pid in enumerate(ranked, 1):
            by_pid[pid]["pos_rank"] = i
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(by_pid))
    except Exception:  # noqa: BLE001
        pass
    return by_pid


# ------------------------------------------------------------- the verdict
def verdict(out_row: Optional[dict], in_row: Optional[dict]) -> Optional[str]:
    """"for" / "against" / "split" / None for "start IN over OUT", from one panel.

    Both panels here carry the positional rank, and a start/sit is usually
    within a position; across positions (a FLEX call) the Flock overall rank is
    used, and the Ballers' points are compared directly.
    """
    if not out_row or not in_row:
        return None
    if out_row.get("src") == "ffb":
        a, b = out_row.get("pts"), in_row.get("pts")
        if a is None or b is None:
            return None
        gap = b - a
        return "for" if gap > 1.0 else "against" if gap < -1.0 else "split"
    same = (out_row.get("pos") == in_row.get("pos"))
    a = out_row.get("pos_rank") if same else out_row.get("rank")
    b = in_row.get("pos_rank") if same else in_row.get("rank")
    if a is None or b is None:
        return None
    gap = float(a) - float(b)          # positive → IN ranked better
    return "for" if gap > 1.5 else "against" if gap < -1.5 else "split"


# ------------------------------------------------------------- snapshots
def _snap_path(kind: str, season: int, week: int, day: str) -> Path:
    return config.DATA_DIR / f"panel_snap_{kind}_{season}_w{week}_{day}.json"


def _today() -> str:
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    except Exception:  # noqa: BLE001
        return _dt.datetime.now().strftime("%Y%m%d")


def _slim(kind: str, rows: dict) -> dict:
    """Just the numbers a mover needs, so a day's snapshot is a few KB."""
    out = {}
    for pid, r in (rows or {}).items():
        if kind == "fp":
            pr = str(r.get("pos_rank") or "")
            digits = "".join(ch for ch in pr if ch.isdigit())
            out[pid] = {"pr": float(digits) if digits else None,
                        "ov": (float(r["ecr"]) if r.get("ecr") is not None and r.get("scale") == "flex" else None),
                        "pos": r.get("pos")}
        elif kind == "flock":
            out[pid] = {"pr": (float(r["pos_rank"]) if r.get("pos_rank") is not None else None),
                        "ov": (float(r["rank"]) if r.get("rank") is not None else None),
                        "pos": r.get("pos")}
        else:
            out[pid] = {"pr": (float(r["pos_rank"]) if r.get("pos_rank") else None),
                        "ov": None, "pts": r.get("pts"), "pos": r.get("pos")}
    return out


def _idx_key(kind: str, season: int, week: int) -> str:
    return f"index_{kind}_{season}_w{week}"


def snapshot_all(season: int, week: int, panels: dict) -> None:
    """Write today's snapshot of each panel, once. Movers are a diff of these:
    a rank means nothing until you know what it was yesterday.

    Written to disk AND to the repo-backed doc store: Cloud's disk does not
    survive a reboot, and a reboot follows every push, so a snapshot kept only
    on disk would never live to see tomorrow.
    """
    from . import storage as _S
    day = _today()
    for kind in ("fp", "flock", "ffb"):
        rows = panels.get(kind) or {}
        if not rows:
            continue
        p = _snap_path(kind, season, week, day)
        if p.exists():
            continue
        slim = _slim(kind, rows)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(slim))
        except Exception:  # noqa: BLE001
            pass
        try:
            days = _S.load_doc("panel_snap", _idx_key(kind, season, week), [])
            if day not in days:
                _S.save_doc("panel_snap", f"{kind}_{season}_w{week}_{day}", slim)
                _S.save_doc("panel_snap", _idx_key(kind, season, week), sorted(set(days) | {day}))
        except Exception:  # noqa: BLE001
            pass


def _snap_days(kind: str, season: int, week: int) -> list:
    pat = f"panel_snap_{kind}_{season}_w{week}_"
    days = set()
    try:
        for p in config.DATA_DIR.glob(pat + "*.json"):
            days.add(p.stem[len(pat):])
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import storage as _S
        days |= set(_S.load_doc("panel_snap", _idx_key(kind, season, week), []) or [])
    except Exception:  # noqa: BLE001
        pass
    return sorted(days)


def _snap_read(kind: str, season: int, week: int, day: str) -> Optional[dict]:
    p = _snap_path(kind, season, week, day)
    try:
        if p.exists():
            return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import storage as _S
        d = _S.load_doc("panel_snap", f"{kind}_{season}_w{week}_{day}", {})
        if d:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(d))       # warm the disk for the next read
            except Exception:  # noqa: BLE001
                pass
            return d
    except Exception:  # noqa: BLE001
        pass
    return None


def _baseline(kind: str, season: int, week: int, since: str) -> Optional[dict]:
    """The snapshot to diff against: "yesterday" = the latest day before today
    this week; "week" = the first snapshot of this week; "last" = the last
    snapshot of the previous week (positional ranks carry across weeks, overall
    ones do too)."""
    today = _today()
    if since == "last":
        days = _snap_days(kind, season, week - 1)
        if not days:
            return None
        return _snap_read(kind, season, week - 1, days[-1])
    days = [d for d in _snap_days(kind, season, week) if d < today]
    if not days:
        return None
    return _snap_read(kind, season, week, days[0] if since == "week" else days[-1])


def baseline_day(kind: str, season: int, week: int, since: str) -> Optional[str]:
    today = _today()
    if since == "last":
        days = _snap_days(kind, season, week - 1)
        return days[-1] if days else None
    days = [d for d in _snap_days(kind, season, week) if d < today]
    if not days:
        return None
    return days[0] if since == "week" else days[-1]


def movers(season: int, week: int, panels: dict, since: str = "yesterday",
           cross: bool = False) -> Dict[str, dict]:
    """{pid: {d: {fp, flock, ffb}, cons, was, now, n}} — rank moves per panel
    and their average. Positive = rose. `cross` uses the cross-position number
    (FantasyPros FLEX / Flock overall) instead of the positional one.

    A man who dropped OFF a panel gets that panel's delta as None and a `gone`
    flag on that panel; a man who appeared gets `new`.
    """
    key = "ov" if cross else "pr"
    out: Dict[str, dict] = {}
    for kind in ("fp", "flock", "ffb"):
        base = _baseline(kind, season, week, since)
        if base is None:
            continue
        now = _slim(kind, panels.get(kind) or {})
        for pid in set(base) | set(now):
            a = (base.get(pid) or {}).get(key)
            b = (now.get(pid) or {}).get(key)
            d = out.setdefault(pid, {"d": {}, "was": {}, "now": {}, "gone": [], "new": []})
            if a is not None and b is not None:
                d["d"][kind] = a - b
                d["was"][kind], d["now"][kind] = a, b
            elif a is not None and b is None:
                d["gone"].append(kind)
            elif a is None and b is not None:
                d["new"].append(kind)
    for pid, d in out.items():
        vals = list(d["d"].values())
        d["n"] = len(vals)
        d["cons"] = (sum(vals) / len(vals)) if vals else None
        d["was_avg"] = (sum(d["was"].values()) / len(d["was"])) if d["was"] else None
        d["now_avg"] = (sum(d["now"].values()) / len(d["now"])) if d["now"] else None
    return out


def is_mover(m: Optional[dict], pos_depth: int = 30) -> bool:
    """A consensus move of 3+ (or 10% of the position), or one panel 6+."""
    if not m:
        return False
    thr = max(3.0, 0.1 * pos_depth)
    if m.get("cons") is not None and abs(m["cons"]) >= thr:
        return True
    return any(abs(v) >= 6 for v in (m.get("d") or {}).values()) or bool(m.get("gone"))
