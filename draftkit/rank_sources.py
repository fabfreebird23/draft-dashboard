"""Alternate ranking sources for the draft board.

The board is driven by an ordered list of ``{rank, name, tier, pid}`` rows. UDK is
the league's saved/seeded board; this module adds two live sources — FantasyPros
Expert Consensus Rankings (ECR) and ESPN draft ranks — in the *same* shape, so the
Rankings tab can swap the active source without touching the value engine, ADP
labels, or positional ranks (all of which are derived from consensus ADP and are
source-independent).

Each fetch is disk-cached per (season, scoring); a network failure (some hosts IP-
block datacenters) returns ``[]`` and the UI shows a fallback note rather than
crashing — UDK always remains available.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import List, Optional

from . import config
from .adp.base import http_get
from .names import normalize_name

# Display labels for the source picker. UDK is handled by the caller (saved board).
UDK = "UDK"
FP_ECR = "FantasyPros ECR"
ESPN = "ESPN"
SOURCES = [UDK, FP_ECR, ESPN]

_CACHE_TTL = 60 * 60 * 12  # 12h — rankings move slowly in-season

_FP_URLS = {
    "ppr": "https://www.fantasypros.com/nfl/rankings/ppr-cheatsheets.php",
    "half": "https://www.fantasypros.com/nfl/rankings/half-point-ppr-cheatsheets.php",
    "std": "https://www.fantasypros.com/nfl/rankings/consensus-cheatsheets.php",
}
_ESPN_HOST = "https://lm-api-reads.fantasy.espn.com"
_ESPN_URL = (_ESPN_HOST + "/apis/v3/games/ffl/seasons/{season}"
             "/segments/0/leaguedefaults/3?view=kona_player_info")
_ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
_ESPN_RANKTYPE = {"ppr": "PPR", "half": "PPR", "std": "STANDARD"}


# --------------------------------------------------------------------- caching
def _cache_path(source: str, season: int, scoring: str) -> Path:
    tag = source.lower().replace(" ", "_")
    return config.DATA_DIR / f"ranks_{tag}_{season}_{scoring}.json"


def _read_cache(p: Path) -> Optional[List[dict]]:
    try:
        if p.exists() and (time.time() - p.stat().st_mtime) < _CACHE_TTL:
            return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None
    return None


def _write_cache(p: Path, rows: List[dict]) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows, indent=2))
    except Exception:  # noqa: BLE001
        pass


def _read_cache_any_age(p: Path) -> Optional[List[dict]]:
    """Stale-but-present fallback when a fresh fetch fails."""
    try:
        if p.exists():
            return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None
    return None


# ------------------------------------------------------------------- assembly
def _attach(ordered: List[dict], registry) -> List[dict]:
    """``ordered`` = source-ordered ``[{name, tier, pos?}]`` → board rows with a
    rank number and a resolved Sleeper pid (dropping any we can't match)."""
    idx = {nm: p.sleeper_pid for nm, p in registry.by_norm.items() if p.sleeper_pid}
    out, rank = [], 0
    for r in ordered:
        pid = idx.get(normalize_name(r["name"]))
        if not pid:
            continue
        rank += 1
        out.append({"rank": rank, "name": r["name"], "tier": int(r.get("tier") or 1),
                    "pid": str(pid), "pos": r.get("pos")})
    return out


def _tier_by_gap(ordered: List[dict]) -> List[dict]:
    """Assign tiers from natural ADP gaps when a source has no tiers of its own."""
    tier, prev = 1, None
    for r in ordered:
        adp = r.get("adp")
        if prev is not None and adp is not None and (adp - prev) > max(1.6, 0.10 * adp):
            tier += 1
        if adp is not None:
            prev = adp
        r["tier"] = tier
    return ordered


# ------------------------------------------------------------- FantasyPros ECR
def _extract_ecr_players(html: str) -> List[dict]:
    """Pull the embedded ``ecrData`` object's players array from the page."""
    m = re.search(r"var\s+ecrData\s*=\s*\{", html)
    if not m:
        return []
    i = m.end() - 1  # index of the opening brace
    depth, j = 0, i
    in_str, esc = False, False
    while j < len(html):
        c = html[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
        j += 1
    try:
        obj = json.loads(html[i:j + 1])
    except Exception:  # noqa: BLE001
        return []
    return obj.get("players", []) or []


def _fetch_fp_ecr(season: int, scoring: str) -> List[dict]:
    url = _FP_URLS.get(scoring, _FP_URLS["ppr"])
    html = http_get(url).text
    players = _extract_ecr_players(html)
    ordered = []
    for p in players:
        name = (p.get("player_name") or "").strip()
        if not name:
            continue
        try:
            rk = float(p.get("rank_ecr") or 0)
        except (TypeError, ValueError):
            rk = 0
        pos = (p.get("player_position_id") or "").upper().replace("DEF", "DST")
        tier = p.get("tier")
        ordered.append({"name": name, "pos": pos,
                        "tier": int(tier) if tier else 1, "_rk": rk})
    ordered = [r for r in ordered if r["_rk"] > 0]
    ordered.sort(key=lambda r: r["_rk"])
    return ordered


# ----------------------------------------------------------------- ESPN ranks
def _fetch_espn(season: int, scoring: str) -> List[dict]:
    rank_type = _ESPN_RANKTYPE.get(scoring, "PPR")
    flt = {"players": {"limit": 400,
                       "sortDraftRanks": {"sortPriority": 1, "value": rank_type}}}
    resp = http_get(_ESPN_URL.format(season=season),
                    headers={"X-Fantasy-Filter": json.dumps(flt)})
    ordered = []
    for item in resp.json().get("players", []):
        p = item.get("player", {})
        name = (p.get("fullName") or "").strip()
        if not name:
            continue
        pos = _ESPN_POS.get(p.get("defaultPositionId"), "")
        adp = (p.get("ownership") or {}).get("averageDraftPosition")
        adp = float(adp) if adp and adp > 0 else None
        ordered.append({"name": name, "pos": pos, "adp": adp})
    # ESPN returns draft-rank order already; synthesize tiers from ADP gaps.
    return _tier_by_gap(ordered)


# --------------------------------------------------------------------- public
def load(source: str, season: int, scoring: str, registry) -> List[dict]:
    """Return board rows for ``source`` (FP ECR or ESPN). Cached; stale-then-empty
    on failure. UDK is handled by the caller via the saved board."""
    p = _cache_path(source, season, scoring)
    cached = _read_cache(p)
    if cached is not None:
        return cached
    try:
        if source == FP_ECR:
            ordered = _fetch_fp_ecr(season, scoring)
        elif source == ESPN:
            ordered = _fetch_espn(season, scoring)
        else:
            return []
        rows = _attach(ordered, registry)
        if rows:
            _write_cache(p, rows)
            return rows
    except Exception:  # noqa: BLE001
        pass
    return _read_cache_any_age(p) or []
