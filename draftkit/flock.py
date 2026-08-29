"""Flock Fantasy rankings — imported from the browser, served as a ranking source.

Flock gates its board behind a login and its API sits behind CORS, so the
server-side scrape that works for UDK is not available here. Verified against the
live site while logged in:

  * ``api.flockfantasy.com/player-comparison/bulk`` is a POST the Angular app
    makes on load; a plain fetch from the page for any path on that host fails
    preflight, so a stored cookie would not help us the way UDK's does.
  * the table is not a ``<table>`` — it is a grid whose frozen name column and
    scrolling stat columns are separate elements, so a row has to be reassembled
    by vertical position.
  * rows render lazily on a REAL scroll. Setting scrollTop from script renders
    nothing, which is why the bookmarklet dispatches wheel events and collects as
    it goes rather than reading the DOM once.

Hence the same shape as the UDK fallback he already uses: a bookmarklet that runs
in his own logged-in browser, and an import here. The free tier exposes "Expert
Average" (the consensus); individual analysts are subscriber-locked, and the
consensus is the one we would want anyway.

The imported board is stored through `storage`, not in the rank_sources disk
cache, so it survives a Streamlit Cloud reboot — that cache is a local file and
Cloud's filesystem is ephemeral.
"""
from __future__ import annotations

import csv
import io
import re
import time
from typing import Dict, List, Optional

from . import storage
from .names import normalize_name

SOURCE = "Flock Fantasy"
RANKINGS_URL = "https://flockfantasy.com/rankings"

# One-click grabber. Runs in the logged-in browser, scrolls the board so the lazy
# rows actually render, reassembles each row from its separately-positioned cells,
# and downloads flock_rankings.csv (Rank,Name,Position,Team,Tier).
BOOKMARKLET = (
    # Matches the ROW CONTAINER, not individual cells. The first cut bucketed leaf
    # cells by vertical position and reassembled a row from them; that found the
    # names but returned empty position and team, because those cells sit in a
    # separate scrolling column and did not land in the same bucket. Matching the
    # element whose own text carries "12. Name RB7 MIA" — and rejecting any that
    # contains a smaller element matching the same shape, so ancestors don't
    # duplicate — gets all four fields at once. Measured on the live board: 347
    # rows in a single pass.
    #
    # It still collects WHILE HE SCROLLS rather than scrolling for him: Flock only
    # renders rows on a real scroll (assigning scrollTop and dispatching synthetic
    # wheel events both render nothing), and rendered rows stay in the DOM.
    "javascript:(()=>{if(window.__flockOn){alert('Flock grabber already running.');return;}"
    "window.__flockOn=1;const F=new Map();"
    "const RE=/^(\\d+)\\.\\s+(.+?)\\s+(QB|RB|WR|TE|K|D|DST)(\\d+)\\s+([A-Z]{2,4})\\b/;"
    "const grab=()=>{for(const e of document.querySelectorAll('div,li')){"
    "const t=(e.innerText||'').replace(/\\s+/g,' ').trim();"
    "if(t.length>120||!RE.test(t))continue;let inner=false;"
    "for(const c of e.children){const ct=(c.innerText||'').replace(/\\s+/g,' ').trim();"
    "if(RE.test(ct)){inner=true;break;}}if(inner)continue;const m=t.match(RE);"
    "F.set(m[1],{r:+m[1],n:m[2].replace(/\\s+\\d+$/,'').trim(),p:m[3],t:m[5]});}};"
    "const b=document.createElement('button');"
    "b.style.cssText='position:fixed;z-index:2147483647;right:18px;bottom:18px;"
    "padding:12px 16px;font:600 14px system-ui;background:#f27b1f;color:#111;border:0;"
    "border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.45);cursor:pointer';"
    "const paint=()=>{b.textContent='Flock: '+F.size+' \\u2014 click to download';};"
    "grab();paint();document.body.appendChild(b);"
    "const iv=setInterval(()=>{grab();paint();},400);"
    "b.onclick=()=>{clearInterval(iv);"
    "const rows=[...F.values()].sort((a,b)=>a.r-b.r);"
    "const csv='Rank,Name,Position,Team\\n'+rows.map(o=>"
    "[o.r,'\"'+o.n.replace(/\"/g,'')+'\"',o.p,o.t].join(',')).join('\\n');"
    "const a=document.createElement('a');"
    "a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));"
    "a.download='flock_rankings.csv';a.click();b.remove();window.__flockOn=0;};})()"
)


_POS = {"QB", "RB", "WR", "TE", "K", "D", "DST"}


def parse_csv(text: str) -> List[dict]:
    """Bookmarklet CSV -> [{rank, name, pos, team, tier}] in board order.

    Tolerant of a hand-pasted list too: any line that starts with "12. Name" or
    "12 Name" parses, so he is not stuck if the bookmarklet is blocked.
    """
    text = (text or "").strip()
    if not text:
        return []
    out: List[dict] = []
    if "," in text.splitlines()[0]:
        for row in csv.DictReader(io.StringIO(text)):
            low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            name = low.get("name") or low.get("player") or ""
            if not name:
                continue
            try:
                rank = int(float(low.get("rank") or low.get("rk") or len(out) + 1))
            except ValueError:
                rank = len(out) + 1
            out.append({"rank": rank, "name": name,
                        "pos": (low.get("position") or low.get("pos") or "").upper(),
                        "team": (low.get("team") or low.get("tm") or "").upper(),
                        "tier": low.get("tier") or ""})
    else:
        for line in text.splitlines():
            m = re.match(r"^\s*(\d+)[.)]?\s+(.+?)\s*$", line)
            if not m:
                continue
            out.append({"rank": int(m.group(1)), "name": m.group(2).strip(),
                        "pos": "", "team": "", "tier": ""})
    out.sort(key=lambda r: r["rank"])
    return out


def attach(rows: List[dict], registry) -> List[dict]:
    """Board rows -> the {rank, name, tier, pid, pos} shape every source returns.

    Letter tiers (S/A/B/C…) become the integers the board expects, in the order
    they appear rather than by alphabet, so an S tier stays above an A. The
    bookmarklet does not currently capture Flock's tier bands — they are separate
    band rows, not part of a player row — so an import without a Tier column lands
    as one flat tier rather than as a guess.
    """
    idx = {nm: p.sleeper_pid for nm, p in registry.by_norm.items() if p.sleeper_pid}
    seen: Dict[str, int] = {}
    out, rank = [], 0
    for r in rows:
        pid = idx.get(normalize_name(r["name"]))
        if not pid:
            continue
        letter = (r.get("tier") or "").strip()
        if letter and letter not in seen:
            seen[letter] = len(seen) + 1
        rank += 1
        out.append({"rank": rank, "name": r["name"], "tier": seen.get(letter, 1),
                    "pid": str(pid), "pos": (r.get("pos") or "").upper() or None})
    return out


def _key(season: int, scoring: str) -> str:
    """Flock's board is one board for everyone — not per league — so it is stored
    per (season, scoring) and shared by every league in the app."""
    return f"{int(season)}_{scoring}"


def save(season: int, scoring: str, rows: List[dict]) -> None:
    storage.save_doc("flock", _key(season, scoring),
                     {"saved": time.time(), "rows": rows})


def load(season: int, scoring: str) -> Optional[dict]:
    doc = storage.load_doc("flock", _key(season, scoring), {})
    return doc or None
