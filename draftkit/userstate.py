"""The two things he decides that have to outlive a page load.

On the phone every tab press is a fresh page and a fresh Streamlit session, so
anything kept in session_state is gone the moment he looks somewhere else. A
claim queue that forgets itself between Waivers and Today is not a queue, and an
inbox item he waved away that comes straight back is nagging. Both live in the
doc store (repo-backed on Cloud), with a short in-process cache so reading them
is not a network round trip on every rerun.

    dismissed  {inbox item key: when}       — "Not now" on Today
    claims     {league_key: [claim, ...]}   — the Wednesday plan, in priority order
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List

from . import storage

_TTL = 60.0
_lock = threading.Lock()
_cache: Dict[str, tuple] = {}


def _get(kind: str, key: str, default):
    with _lock:
        hit = _cache.get(f"{kind}/{key}")
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
    val = storage.load_doc(kind, key, default)
    with _lock:
        _cache[f"{kind}/{key}"] = (time.time(), val)
    return val


def _put(kind: str, key: str, val) -> None:
    with _lock:
        _cache[f"{kind}/{key}"] = (time.time(), val)
    storage.save_doc(kind, key, val)


# --------------------------------------------------------------- inbox
def dismissed() -> Dict[str, float]:
    d = _get("inbox", "dismissed", {}) or {}
    # forget dismissals older than a fortnight — the week they belonged to is over
    cutoff = time.time() - 14 * 86400
    return {k: v for k, v in d.items() if v >= cutoff}


def dismiss(item_key: str) -> None:
    d = dict(dismissed())
    d[item_key] = time.time()
    _put("inbox", "dismissed", d)


# --------------------------------------------------------------- claims
def claims(league_key: str) -> List[dict]:
    return list(_get("claims", league_key, []) or [])


def save_claims(league_key: str, rows: List[dict]) -> None:
    _put("claims", league_key, list(rows))


def add_claim(league_key: str, row: dict) -> None:
    """Append unless he is already queued; the caller decides bid and drop."""
    rows = claims(league_key)
    if any(str(r.get("pid")) == str(row.get("pid")) for r in rows):
        return
    rows.append(row)
    save_claims(league_key, rows)


# --------------------------------------------------------------- suggestions
# What the app suggested for each claim, kept after the claim leaves the queue
# so the waiver recap can put "we said $1–4" next to what it actually took.
def suggestions(league_key: str) -> Dict[str, dict]:
    return dict(_get("faab_sugg", league_key, {}) or {})


def note_suggestions(league_key: str, rows: List[dict]) -> None:
    """{pid: {low, high, bid, ts}} for queued claims, newest wins; a month kept."""
    cur = suggestions(league_key)
    now = time.time()
    changed = False
    for r in rows:
        rng = r.get("range") or {}
        if not r.get("pid") or not rng.get("high"):
            continue
        rec = {"low": rng.get("low"), "high": rng.get("high"), "bid": r.get("bid"), "ts": now}
        old = cur.get(str(r["pid"])) or {}
        if (old.get("low"), old.get("high"), old.get("bid")) != (rec["low"], rec["high"], rec["bid"]):
            cur[str(r["pid"])] = rec
            changed = True
    cur = {k: v for k, v in cur.items() if now - float(v.get("ts") or 0) < 30 * 86400}
    if changed:
        _put("faab_sugg", league_key, cur)
