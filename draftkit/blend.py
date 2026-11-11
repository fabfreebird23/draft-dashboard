"""One number per player, from every source that has an opinion.

Until this existed a lineup was scored on the host's projections alone and the
expert panels could only re-sort it. Five sources each see something the others
miss — a projection model, two panels of rankers, three analysts' stat lines
and the betting market — and the average of them beats any one of them more
weeks than not. So every screen now reads the BLEND, and the single sources
are kept beside it for the places that show where they disagree.

Getting five sources onto one scale:

  * sleeper / espn  the host's projection, already points under this league's
                    scoring. The base: it covers everyone.
  * ffb             the Ballers' stat lines scored under this league's book —
                    points.
  * vegas           points from the props, but only where the book posts a
                    whole line for the player (an anytime-TD price alone is
                    two points, not a projection) — and at half weight.
  * fp / flock      RANKS. A positional rank becomes points by reading it off
                    the base's own curve at that position: FantasyPros' RB12
                    is worth what the 12th-best projected RB is worth. That
                    keeps the panel's ORDER and the host's SCALE.

Weights start equal (Vegas a half) and, once the Monday review has graded a
few weeks, lean toward whichever sources have been closest (`review.weights`).
"""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

SOURCES = ("sleeper", "fp", "flock", "ffb", "vegas")
LABEL = {"sleeper": "Sleeper", "fp": "FantasyPros", "flock": "Flock", "ffb": "The Ballers",
         "vegas": "Vegas", "blend": "Blend"}
DEFAULT_W = {"sleeper": 1.0, "fp": 1.0, "flock": 1.0, "ffb": 1.0, "vegas": 0.5}

_MEMO: Dict[tuple, tuple] = {}
_TTL = 600.0


def _pos(registry, pid) -> str:
    try:
        p = (registry.meta(str(pid)).position or "").upper()
    except Exception:  # noqa: BLE001
        return ""
    return "DEF" if p in ("DST", "D/ST") else p


def curves(base: Dict[str, float], registry) -> Dict[str, list]:
    """{pos: [points, best first]} — the scale a positional rank is read off."""
    out: Dict[str, list] = {}
    for pid, v in (base or {}).items():
        try:
            v = float(v or 0)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out.setdefault(_pos(registry, pid), []).append(v)
    for v in out.values():
        v.sort(reverse=True)
    return out


def _at(curve: list, rank: float) -> Optional[float]:
    """Points at a (possibly fractional) rank on a curve; None off the scale."""
    if not curve or rank is None or rank < 1:
        return None
    i = rank - 1
    lo = int(i)
    if lo >= len(curve) - 1:
        # past the end of the projected pool: the last value, fading
        return round(curve[-1] * max(0.3, 1 - 0.03 * (i - (len(curve) - 1))), 2)
    f = i - lo
    return round(curve[lo] * (1 - f) + curve[lo + 1] * f, 2)


def _rank(row: dict) -> Optional[float]:
    """A positional rank out of a live panel row ("RB12", 12.0) or a snapshot ("pr")."""
    v = row.get("pr") if "pr" in row else row.get("pos_rank")
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    digits = "".join(ch for ch in str(v) if ch.isdigit() or ch == ".")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


_VEGAS_WHOLE = {"QB": ({"pass_yd"},), "RB": ({"rush_yd", "rec_yd"}, {"rush_yd", "rec"}),
                "WR": ({"rec_yd", "rec"},), "TE": ({"rec_yd", "rec"},), "K": ({"kick_pts"},)}


def _vegas_ok(row: dict, pos: str, base: float) -> bool:
    exp = row.get("exp")
    if isinstance(exp, dict):
        return any(need <= set(exp) for need in _VEGAS_WHOLE.get(pos, ()))
    # a snapshot keeps the points and not the lines: take it only when it is
    # plainly a whole projection rather than a lone prop
    return base > 0 and float(row.get("pts") or 0) >= 0.6 * base


def to_points(base: Dict[str, float], panels: dict, registry) -> Dict[str, Dict[str, float]]:
    """{source: {pid: points}} — every source on the base's scale."""
    cv = curves(base, registry)
    out: Dict[str, Dict[str, float]] = {"sleeper": {}}
    for pid, v in (base or {}).items():
        try:
            out["sleeper"][str(pid)] = float(v or 0)
        except (TypeError, ValueError):
            pass
    for src in ("fp", "flock"):
        rows, d = (panels or {}).get(src) or {}, {}
        for pid, r in rows.items():
            rk = _rank(r or {})
            pts = _at(cv.get(_pos(registry, pid)) or [], rk) if rk else None
            if pts is not None:
                d[str(pid)] = pts
        out[src] = d
    for src in ("ffb", "vegas"):
        rows, d = (panels or {}).get(src) or {}, {}
        for pid, r in rows.items():
            if not r or r.get("pts") is None:
                continue
            if src == "vegas" and not _vegas_ok(r, _pos(registry, pid),
                                                float(out["sleeper"].get(str(pid), 0) or 0)):
                continue
            d[str(pid)] = float(r["pts"])
        out[src] = d
    return out


def combine(by_src: Dict[str, Dict[str, float]],
            weights: Optional[Dict[str, float]] = None) -> Tuple[Dict[str, float], Dict[str, dict]]:
    """(blend {pid: points}, detail {pid: {by{src: pts}, n, spread}})."""
    w = dict(DEFAULT_W)
    w.update({k: float(v) for k, v in (weights or {}).items() if k in w and v is not None})
    base = by_src.get("sleeper") or {}
    pids = set()
    for d in by_src.values():
        pids.update(d)
    proj, detail = {}, {}
    for pid in pids:
        b = base.get(pid)
        if b is not None and b < 0.5:
            # the host has him at nothing — out, on bye, inactive. A rank that
            # hasn't caught up with the news must not put points back on him.
            proj[pid] = float(b)
            continue
        by = {s: d[pid] for s, d in by_src.items() if pid in d}
        tw = sum(w.get(s, 0) for s in by)
        if not by or tw <= 0:
            continue
        proj[pid] = round(sum(v * w.get(s, 0) for s, v in by.items()) / tw, 2)
        if len(by) > 1:
            vals = list(by.values())
            detail[pid] = {"by": by, "n": len(by), "spread": round(max(vals) - min(vals), 1)}
    return proj, detail


def split(detail_row: Optional[dict], pts: float) -> bool:
    """Do the sources disagree SHARPLY on this player? Three or more opinions and
    a gap worth a starting decision: 5 points, or 35% of what he projects."""
    if not detail_row or detail_row.get("n", 0) < 3:
        return False
    return float(detail_row.get("spread") or 0) >= max(5.0, 0.35 * float(pts or 0))


def blend(base, panels, registry, weights=None):
    return combine(to_points(base, panels, registry), weights)


def panels_for(meta, registry, season: int, week: int, games: Optional[dict] = None,
               ecr: Optional[dict] = None) -> dict:
    """The four panels for this league and week, straight from their own
    (disk-cached) modules — no Streamlit, so Home and the warmer can ask too."""
    from . import ecr as ECR, panels as P, vegas as VG
    out = {}
    try:
        out["fp"] = ecr if ecr is not None else ECR.weekly(
            season, week, getattr(meta, "scoring", "ppr") or "ppr", registry)
    except Exception:  # noqa: BLE001
        out["fp"] = {}
    try:
        out["flock"] = P.flock_weekly(season, week, registry)
    except Exception:  # noqa: BLE001
        out["flock"] = {}
    w = getattr(meta, "scoring_weights", None) or {}
    if not w and getattr(meta, "platform", "") == "sleeper":
        try:
            from . import sleeper_client as api
            w = (api.get_league(str(meta.league_id)) or {}).get("scoring_settings") or {}
        except Exception:  # noqa: BLE001
            w = {}
    tag = f'{getattr(meta, "platform", "")}_{getattr(meta, "league_id", "")}'
    try:
        out["ffb"] = P.ffb_weekly(season, week, registry, w, tag)
    except Exception:  # noqa: BLE001
        out["ffb"] = {}
    try:
        out["vegas"] = VG.weekly(season, week, registry, w, window=VG.week_window(games or {}), tag=tag)
    except Exception:  # noqa: BLE001
        out["vegas"] = {}
    return out


def for_league(meta, registry, season: int, week: int, base: Dict[str, float],
               games: Optional[dict] = None, ecr: Optional[dict] = None):
    """(blend, detail) for this league's week. Falls back to the base, whole,
    if nothing else answers — never an empty dict where projections were."""
    if not base:
        return base, {}
    key = (getattr(meta, "platform", ""), str(getattr(meta, "league_id", "")), int(season), int(week),
           len(base))
    hit = _MEMO.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1], hit[2]
    try:
        pn = panels_for(meta, registry, season, week, games, ecr)
        try:
            from . import review as RV
            wts = RV.weights(season, week, registry)
        except Exception:  # noqa: BLE001
            wts = None
        proj, detail = blend(base, pn, registry, wts)
        # everyone the base covers stays covered
        for pid, v in base.items():
            proj.setdefault(str(pid), float(v or 0))
    except Exception:  # noqa: BLE001
        proj, detail = dict(base), {}
    _MEMO[key] = (time.time(), proj, detail)
    if len(_MEMO) > 24:
        for k in sorted(_MEMO, key=lambda k: _MEMO[k][0])[:8]:
            _MEMO.pop(k, None)
    return proj, detail
