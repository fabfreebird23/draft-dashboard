"""Ranking import + parsing — extracted from the keeper app's draft kit.

Parses a personal ranking board from pasted text, a CSV/Sheet export, or a URL,
matching each name to a player via the registry. Tiers, rank numbers, positions
and teams are all handled. Also builds the ADP-ordered pool the mock AI drafts
from. `pid` here is the Sleeper player id (the board resolves through it for both
Sleeper and ESPN leagues).
"""
from __future__ import annotations

import csv
import io
import re
from typing import List

import pandas as pd
import requests

from .names import normalize_name


def _name_index(registry) -> dict:
    """normalized name -> sleeper_pid (the id the board/headshots use)."""
    return {nm: p.sleeper_pid for nm, p in registry.by_norm.items() if p.sleeper_pid}


def parse_rankings(text: str, registry) -> list:
    """Parse pasted rankings: one player per line (leading rank/pos/team stripped);
    a line like 'Tier 3' sets the tier for players below it."""
    idx = _name_index(registry)
    rows, tier, rank = [], 1, 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^[\-\*\s>]*tier\s*[:#]?\s*(\d+)", s, re.I)
        if m:
            tier = int(m.group(1))
            continue
        nm = re.sub(r"^\s*\d+[\.\):]?\s*", "", s)        # leading "12." / "12)"
        nm = re.sub(r"[,\t|].*$", "", nm)                # CSV/extra columns
        nm = re.sub(r"\([^)]*\)", "", nm)                # "(WR - PHI)"
        nm = re.sub(r"\b(QB|RB|WR|TE|K|DST|DEF)\d*\b", "", nm, flags=re.I).strip(" -–")
        if not nm:
            continue
        rank += 1
        rows.append({"rank": rank, "name": nm, "tier": tier,
                     "pid": idx.get(normalize_name(nm))})
    return rows


def parse_csv(text: str, registry) -> list:
    """Parse a CSV export (UDK / Google-Sheets): auto-detect the player-name column
    (matching the most players) and a tier column."""
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if len(rows) < 2:
        return []
    idx = _name_index(registry)
    body = rows[1:]
    ncols = max(len(r) for r in rows)
    name_col, best = 0, -1
    for c in range(ncols):
        hits = sum(1 for r in body if len(r) > c and idx.get(normalize_name(r[c])))
        if hits > best:
            best, name_col = hits, c
    if best <= 0:
        return []
    header = [h.lower() for h in rows[0]]
    tier_col = next((i for i, h in enumerate(header) if "tier" in h), None)
    out, rank = [], 0
    for r in body:
        if len(r) <= name_col:
            continue
        nm = re.sub(r"\([^)]*\)", "", r[name_col]).strip()
        if not nm:
            continue
        tier = 1
        if tier_col is not None and len(r) > tier_col:
            tm = re.search(r"\d+", r[tier_col])
            tier = int(tm.group()) if tm else 1
        rank += 1
        out.append({"rank": rank, "name": nm, "tier": tier, "pid": idx.get(normalize_name(nm))})
    return out


def smart_parse(text: str, registry) -> list:
    """Parse from a CSV export or a plain ranked list. Prefer the CSV parse for
    comma/tab data unless the plain-list parse clearly matches more players."""
    line = parse_rankings(text, registry)
    if "," in text or "\t" in text:
        csvp = parse_csv(text, registry)
        if csvp and sum(1 for r in csvp if r.get("pid")) >= sum(1 for r in line if r.get("pid")):
            return csvp
    return line


def fetch_url(url: str) -> str:
    """Fetch ranking text from a CSV / published-Google-Sheet URL."""
    u = url.strip()
    m = re.search(r"docs\.google\.com/spreadsheets/d/([\w-]+)", u)
    if m and "output=csv" not in u and "format=csv" not in u:
        gid = re.search(r"[#&?]gid=(\d+)", u)
        u = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
        if gid:
            u += f"&gid={gid.group(1)}"
    r = requests.get(u, timeout=15, headers={"User-Agent": "draft-dashboard/1.0"})
    r.raise_for_status()
    return r.text


def adp_pool(registry, adp_df: pd.DataFrame) -> list:
    """ADP-ordered draftable players (pid, name, pos, adp) for the mock AI."""
    idx = _name_index(registry)
    out = []
    if adp_df is None or adp_df.empty:
        return out
    for _, ar in adp_df.iterrows():
        pos, rank = ar.get("position"), ar.get("consensus_rank")
        if pos not in ("QB", "RB", "WR", "TE") or pd.isna(rank):
            continue
        pid = idx.get(normalize_name(ar["name"]))
        if pid:
            out.append({"pid": str(pid), "name": ar["name"], "pos": pos, "adp": int(rank)})
    out.sort(key=lambda x: x["adp"])
    return out
