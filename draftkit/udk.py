"""Ultimate Draft Kit (The Fantasy Footballers) rankings — server-side scrape.

The UDK position-rankings page is gated behind a WordPress "UDK+" login and is
JS-rendered, so there's no single stable public endpoint. We try a swappable
fallback chain with a stored session cookie, and the app keeps a no-credentials
fallback (the one-click bookmarklet + CSV upload, in the rankings UI):

  1. authenticated JSON (admin-ajax / wp-json) — the real data call
  2. authenticated rendered-HTML <table> parse
  3. (UI) bookmarklet + CSV upload — always works

The exact JSON route can only be confirmed from a logged-in browser's DevTools
Network tab. It lives in ONE constant below so discovery is a one-line swap; until
then strategies 1/2 simply fail and the UI falls back to upload.
"""
from __future__ import annotations

import io
import re
from typing import List, Optional

import pandas as pd
import requests

from .adp.base import BROWSER_HEADERS
from .names import normalize_name

UDK_PAGE = "https://www.thefantasyfootballers.com/2026-ultimate-draft-kit/udk-position-rankings/"
# Swap this once the real data call is found in DevTools (admin-ajax action or a
# /wp-json/ REST route). Leave as None to skip Strategy 1 cleanly.
UDK_JSON_URL: Optional[str] = None
UDK_JSON_PARAMS: dict = {}

_POSITIONS = ("QB", "RB", "WR", "TE")
# Strip a trailing "WR (10)" / "RB BUF (3)" style suffix from a UDK name cell.
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


def _via_json(cookie: str) -> List[dict]:
    if not UDK_JSON_URL:
        return []
    r = requests.get(UDK_JSON_URL, headers=_cookie_header(cookie),
                     params=UDK_JSON_PARAMS or None, timeout=20)
    r.raise_for_status()
    data = r.json()
    rows = data if isinstance(data, list) else data.get("data") or data.get("players") or []
    out = []
    for it in rows:
        name = it.get("name") or it.get("player") or ""
        if not name:
            continue
        out.append({"name": _SUFFIX_RE.sub("", str(name)).strip(),
                    "tier": int(it.get("tier") or 1),
                    "adp": _to_float(it.get("adp"))})
    return out


def _via_html(cookie: str) -> List[dict]:
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


def fetch_udk(cookie: str, registry) -> Optional[List[dict]]:
    """Try the authenticated strategies in order. Returns ranking rows
    [{rank,name,tier,pid}] sorted by ADP, or None if every strategy failed (the
    caller then falls back to the bookmarklet + CSV upload)."""
    if not cookie:
        return None
    for strategy in (_via_json, _via_html):
        try:
            rows = strategy(cookie)
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
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None
