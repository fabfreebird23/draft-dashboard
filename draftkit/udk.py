"""Ultimate Draft Kit (The Fantasy Footballers) rankings — server-side scrape.

The UDK position-rankings page is gated behind a WordPress "UDK+" login. It does
NOT fetch rankings from an API — the full board is server-rendered inline into the
page HTML as a big JSON `"projections":[...]` array (confirmed via DevTools: no
XHR fires, the data is in `window.udk.data.projections`). So the scrape is simply:

  1. GET the page with the stored login cookie, extract the inline `projections`
     JSON, dedupe (the array has one row per analyst — Andy/Mike/Jason — so each
     player appears ~3x), and order by the scoring-appropriate ADP.
  2. (fallback) parse a rendered <table>, if the page layout ever changes.
  3. (UI) the one-click bookmarklet + CSV upload — always works, no credentials.

Each projection row carries: name, fantasy_position, team, adp / adp_ppr /
adp_half_ppr / adp_2qb, plus full projection stats. We rank by ADP (matching the
bookmarklet's behavior) and tier by natural ADP gaps.
"""
from __future__ import annotations

import io
import json
import re
from typing import Dict, List, Optional

import pandas as pd
import requests

from . import config
from .adp.base import BROWSER_HEADERS
from .names import normalize_name

UDK_PAGE = "https://www.thefantasyfootballers.com/2026-ultimate-draft-kit/udk-position-rankings/"

# Pick the ADP column that matches league scoring.
_ADP_FIELD = {"ppr": "adp_ppr", "half": "adp_half_ppr", "std": "adp", "2qb": "adp_2qb"}
_SUFFIX_RE = re.compile(r"\s+[A-Z]{2,4}\s*\(\d+\)\s*$")

# One-click UDK grabber bookmarklet (no credentials needed — runs in the user's
# already-logged-in browser). Cycles QB/RB/WR/TE, sorts by ADP, downloads
# udk_rankings.csv (Player,Tier) to upload in the app.
BOOKMARKLET = (
    "javascript:(async()=>{const w=m=>new Promise(r=>setTimeout(r,m));"
    "const P=['QB','RB','WR','TE'],A=[];for(const p of P){const b=[...document."
    "querySelectorAll('button')].find(x=>x.textContent.trim()===p);if(b)b.click();"
    "await w(2600);for(const tr of document.querySelectorAll('table tr')){const c="
    "[...tr.querySelectorAll('td')].map(x=>x.innerText.replace(/\\s+/g,' ').trim());"
    "if(c.length<7||!/^\\d+$/.test(c[1]))continue;A.push({n:c[0].replace("
    "/\\s+[A-Z]{2,4}\\s*\\(\\d+\\)\\s*$/,'').trim(),a:parseFloat(c[5]),t:c[6]});}}"
    "A.sort((x,y)=>x.a-y.a);const csv='Player,Tier\\n'+A.map(r=>'\"'+r.n+'\",'+r.t)"
    ".join('\\n');const u=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));"
    "const e=document.createElement('a');e.href=u;e.download='udk_rankings.csv';"
    "document.body.appendChild(e);e.click();e.remove();alert('UDK exported: '+"
    "A.length+' players. Now upload udk_rankings.csv in your Draft Kit.');})();"
)


def _cookie_header(cookie: str) -> dict:
    return {**BROWSER_HEADERS, "Cookie": cookie.strip()}


def _extract_json_array(html: str, key: str):
    """Balanced-bracket extraction of a `"key":[ ... ]` JSON array from raw HTML."""
    start = html.find(f'"{key}":')
    if start < 0:
        return None
    i = html.find("[", start)
    if i < 0:
        return None
    depth, in_str, esc = 0, False, False
    for j in range(i, len(html)):
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
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[i:j + 1])
                    except json.JSONDecodeError:
                        return None
    return None


def _byes_path(season: int):
    return config.DATA_DIR / f"byes_{season}.json"


def save_byes(byes: Dict[str, int], season: int) -> None:
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _byes_path(season).write_text(json.dumps(byes))
    except Exception:  # noqa: BLE001
        pass


def load_byes(season: int) -> Dict[str, int]:
    for p in (_byes_path(season), config.ROOT / "data_seed" / f"byes_{season}.json"):
        if p.exists():
            try:
                return {k: int(v) for k, v in json.loads(p.read_text()).items()}
            except Exception:  # noqa: BLE001
                continue
    return {}


def _via_inline(cookie: str, scoring: str = "ppr") -> List[dict]:
    """Strategy 1 — pull the inline `projections` array out of the page HTML."""
    r = requests.get(UDK_PAGE, headers=_cookie_header(cookie), timeout=25)
    r.raise_for_status()
    proj = _extract_json_array(r.text, "projections")
    if not proj:
        return []
    # Capture team bye weeks (per-team) for conflict warnings — best effort.
    byes = {}
    for p in proj:
        t, b = p.get("team"), p.get("bye_week")
        if t and b:
            byes[t] = int(b)
    if byes:
        save_byes(byes, config.current_season())
    adp_field = _ADP_FIELD.get(scoring, "adp_ppr")
    # Dedupe by player (the array repeats each player once per analyst). ADP is
    # identical across analysts, so keep the first occurrence.
    seen, players = set(), []
    for p in proj:
        name = (p.get("name") or "").strip()
        pos = p.get("fantasy_position")
        if not name or pos not in ("QB", "RB", "WR", "TE"):
            continue
        pkey = str(p.get("player_id") or normalize_name(name))
        if pkey in seen:
            continue
        seen.add(pkey)
        adp = _to_float(p.get(adp_field)) or _to_float(p.get("adp_ppr")) or _to_float(p.get("adp"))
        players.append({"name": name, "pos": pos, "team": p.get("team") or "", "adp": adp})
    # Order by ADP (no-ADP players sink to the bottom), then assign gap-based tiers.
    players.sort(key=lambda x: (x["adp"] is None, x["adp"] if x["adp"] is not None else 1e9))
    return _tier_by_gap(players)


def _tier_by_gap(players: List[dict]) -> List[dict]:
    """Assign tiers from natural ADP gaps (a jump opens a new tier)."""
    rows, tier, prev = [], 1, None
    for p in players:
        adp = p["adp"]
        if prev is not None and adp is not None and (adp - prev) > max(1.6, 0.10 * adp):
            tier += 1
        if adp is not None:
            prev = adp
        rows.append({"name": p["name"], "tier": tier, "adp": adp})
    return rows


def ensure_byes(cookie: str, season: int) -> Dict[str, int]:
    """Team byes from disk; derive from the UDK page if missing and a cookie is set."""
    byes = load_byes(season)
    if byes or not cookie:
        return byes
    try:
        r = requests.get(UDK_PAGE, headers=_cookie_header(cookie), timeout=25)
        r.raise_for_status()
        proj = _extract_json_array(r.text, "projections") or []
        byes = {p["team"]: int(p["bye_week"]) for p in proj
                if p.get("team") and p.get("bye_week")}
        if byes:
            save_byes(byes, season)
    except Exception:  # noqa: BLE001
        return {}
    return byes


def _via_html(cookie: str, scoring: str = "ppr") -> List[dict]:
    """Strategy 2 — parse a rendered <table>, if the inline JSON ever disappears."""
    r = requests.get(UDK_PAGE, headers=_cookie_header(cookie), timeout=20)
    r.raise_for_status()
    tables = pd.read_html(io.StringIO(r.text))
    if not tables:
        return []
    df = max(tables, key=lambda t: t.shape[0] * t.shape[1])
    cols = [str(c).lower() for c in df.columns]
    name_col = next((c for c, l in zip(df.columns, cols) if "player" in l or "name" in l), df.columns[0])
    tier_col = next((c for c, l in zip(df.columns, cols) if "tier" in l), None)
    adp_col = next((c for c, l in zip(df.columns, cols) if "adp" in l), None)
    out = []
    for _, row in df.iterrows():
        name = _SUFFIX_RE.sub("", str(row[name_col])).strip()
        if not name or name.lower() in ("nan", "player"):
            continue
        tier = 1
        if tier_col is not None:
            m = re.search(r"\d+", str(row[tier_col]))
            tier = int(m.group()) if m else 1
        out.append({"name": name, "tier": tier,
                    "adp": _to_float(row[adp_col]) if adp_col is not None else None})
    return out


def fetch_udk(cookie: str, registry, scoring: str = "ppr") -> Optional[List[dict]]:
    """Try the authenticated strategies in order. Returns ranking rows
    [{rank,name,tier,pid}], or None if every strategy failed (the caller then
    falls back to the bookmarklet + CSV upload)."""
    if not cookie:
        return None
    for strategy in (_via_inline, _via_html):
        try:
            rows = strategy(cookie, scoring)
        except Exception:  # noqa: BLE001 - try the next strategy
            rows = []
        if rows:
            return _match(rows, registry)
    return None


def _match(rows: List[dict], registry) -> List[dict]:
    """Order by ADP when present (else input order), assign ranks, attach pid."""
    have_adp = any(r.get("adp") for r in rows)
    if have_adp:
        rows = sorted(rows, key=lambda r: (r.get("adp") is None, r.get("adp") or 1e9))
    idx = {nm: p.sleeper_pid for nm, p in registry.by_norm.items() if p.sleeper_pid}
    out = []
    for i, r in enumerate(rows, 1):
        out.append({"rank": i, "name": r["name"], "tier": int(r.get("tier") or 1),
                    "pid": idx.get(normalize_name(r["name"]))})
    return out


def _to_float(x):
    try:
        v = float(str(x).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None
