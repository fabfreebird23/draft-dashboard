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


def _adp_key(s) -> float:
    """UDK ADP is 'round.pick' (e.g. '4.04'); blanks sink to the bottom."""
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return 9999.0


def parse_position_csv(text: str, registry) -> list:
    """Parse the UDK **position-rankings** export (columns: Name, Position, …, ADP,
    Tier, …). Its Tier column is POSITIONAL (QB Tier 1, RB Tier 1, …), so we keep it
    per-player in ``pos_tier`` and order the overall board by ADP. A coarse overall
    ``tier`` (by ADP round) drives the All view. Returns rows with rank/name/tier/
    pos_tier/pid, or [] if the CSV isn't this format."""
    reader = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if len(reader) < 2:
        return []
    header = [h.lower().strip() for h in reader[0]]

    def col(*names):
        for i, h in enumerate(header):
            if any(h == n or n in h for n in names):
                return i
        return None

    name_c, pos_c, tier_c, adp_c, rank_c = (
        col("name", "player"), col("position", "pos"), col("tier"), col("adp"),
        col("rank"))
    if name_c is None or pos_c is None or tier_c is None:
        return []                                  # not a position-rankings export
    idx = _name_index(registry)
    items = []
    for i, r in enumerate(reader[1:]):
        if len(r) <= max(name_c, pos_c, tier_c):
            continue
        nm = re.sub(r"\([^)]*\)", "", r[name_c]).strip()
        if not nm:
            continue
        tm = re.search(r"\d+", r[tier_c] if len(r) > tier_c else "")
        adp = _adp_key(r[adp_c]) if (adp_c is not None and len(r) > adp_c) else 9999.0
        # UDK's POSITIONAL rank (their expert order within the position) — tiers
        # follow it, not ADP. Fall back to file order if no Rank column.
        prm = re.search(r"\d+", r[rank_c]) if (rank_c is not None and len(r) > rank_c) else None
        items.append({"name": nm, "pos": (r[pos_c].strip().upper() if len(r) > pos_c else ""),
                      "pos_tier": int(tm.group()) if tm else 1,
                      "pos_rank": int(prm.group()) if prm else (i + 1),
                      "adp": adp, "pid": idx.get(normalize_name(nm))})
    if not items:
        return []
    # Overall order: interleave the per-position lists (each in UDK's EXPERT pos_rank
    # order) by ADP. This keeps the overall board consistent with the per-position
    # tier view — within a position the expert order is preserved (RB1 before RB2),
    # so a positional #1 always outranks a positional #2 overall — instead of a raw
    # ADP sort where a lower-ADP RB2 could jump its own RB1.
    from collections import defaultdict
    bypos = defaultdict(list)
    for it in items:
        bypos[it["pos"]].append(it)
    for lst in bypos.values():
        lst.sort(key=lambda x: x["pos_rank"])
    ptr = {p: 0 for p in bypos}
    merged = []
    while True:
        fronts = [(bypos[p][ptr[p]]["adp"], bypos[p][ptr[p]]["pos_rank"], p)
                  for p in bypos if ptr[p] < len(bypos[p])]
        if not fronts:
            break
        fronts.sort()
        p = fronts[0][2]
        merged.append(bypos[p][ptr[p]])
        ptr[p] += 1
    out, prev_round, otier, rank = [], None, 0, 0
    for it in merged:
        rank += 1
        rnd = int(it["adp"]) if it["adp"] < 9999 else (prev_round or 0) + 1
        if rnd != prev_round:                      # coarse overall tier = ADP round
            otier += 1
            prev_round = rnd
        out.append({"rank": rank, "name": it["name"], "tier": otier, "adp": it["adp"],
                    "pos_tier": it["pos_tier"], "pos_rank": it["pos_rank"],
                    "pid": it["pid"]})
    return out


def smart_parse(text: str, registry) -> list:
    """Parse from a CSV export or a plain ranked list. Prefer the UDK position-tier
    CSV (real positional tiers), then a generic CSV, else a plain ranked list."""
    if "," in text or "\t" in text:
        postiers = parse_position_csv(text, registry)
        if postiers and sum(1 for r in postiers if r.get("pid")) >= 5:
            return postiers
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


def adp_pool(registry, adp_df: pd.DataFrame, source: str = None) -> list:
    """ADP-ordered draftable players (pid, name, pos, adp) for the mock AI. With
    `source` (a per-source column name like 'ESPN' / 'FantasyPros' / 'Underdog'),
    order by that source's ADP instead of the consensus — so an AI team can be set
    to draft like an ESPN-board manager. Players the source doesn't rank fall to the
    back (after the ranked ones), kept in consensus order, so the pool stays full."""
    idx = _name_index(registry)
    out, tail = [], []
    if adp_df is None or adp_df.empty:
        return out
    col = source if (source and source in adp_df.columns) else "consensus_rank"
    for _, ar in adp_df.iterrows():
        pos = ar.get("position")
        if pos not in ("QB", "RB", "WR", "TE"):
            continue
        pid = idx.get(normalize_name(ar["name"]))
        if not pid:
            continue
        val, cons = ar.get(col), ar.get("consensus_rank")
        row = {"pid": str(pid), "name": ar["name"], "pos": pos}
        if pd.notna(val):
            out.append({**row, "adp": float(val)})
        elif pd.notna(cons):                       # source didn't rank him → tail
            tail.append({**row, "adp": float(cons) + 1000})
    out.sort(key=lambda x: x["adp"])
    tail.sort(key=lambda x: x["adp"])
    return out + tail


def apply_tweaks(board: list, tweaks: dict) -> list:
    """Re-apply the user's saved per-player rank/tier tweaks on top of a board, so
    their hand edits survive a fresh UDK pull. ``tweaks`` is {pid: {rank, tier}}.
    A tweaked player is pinned to their saved rank; tiers are overridden; the board
    is renumbered. Untweaked players keep the board's order."""
    if not tweaks or not board:
        return board
    out = [dict(r) for r in board]
    for i, r in enumerate(out):
        r["_ord"] = i
        t = tweaks.get(str(r.get("pid")))
        if t and t.get("tier") is not None:
            r["tier"] = r["pos_tier"] = int(t["tier"])
    pins = {str(p): float(v["rank"]) for p, v in tweaks.items()
            if isinstance(v, dict) and v.get("rank") is not None}
    # pinned players sort to their pinned rank; others keep their slot (+.5 so a
    # pin at rank N lands just ahead of the player currently at slot N).
    out.sort(key=lambda r: (pins.get(str(r.get("pid")), r["_ord"] + 0.5), r["_ord"]))
    for i, r in enumerate(out, 1):
        r["rank"] = i
        r.pop("_ord", None)
    return out


def apply_rookie_curve(pool: list, registry, curve: dict) -> list:
    """Return a copy of the AI draft pool with rookies pulled up to where THIS
    league historically drafts them (from draft_history.rookie_curve). The k-th
    rookie by ADP gets effective_adp = min(his_adp, curve[k]) — a pull-only boost,
    never a demotion — then the pool is re-sorted. With an empty curve (no rookie
    history) this is a no-op, so non-rookie-aggressive leagues are unaffected."""
    if not curve:
        return pool
    rookies = [p for p in pool if _is_rookie(registry, p["pid"])]
    rookies.sort(key=lambda p: p["adp"])
    boost = {}
    for rank, p in enumerate(rookies, 1):
        tgt = curve.get(rank)
        if tgt is not None and tgt < p["adp"]:
            boost[p["pid"]] = float(tgt)
    if not boost:
        return pool
    out = [dict(p) for p in pool]
    for p in out:
        if p["pid"] in boost:
            p["adp"] = boost[p["pid"]]
    out.sort(key=lambda x: x["adp"])
    return out


def _is_rookie(registry, pid) -> bool:
    try:
        return registry.meta(pid).years_exp == 0
    except Exception:  # noqa: BLE001
        return False
