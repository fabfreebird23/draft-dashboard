"""Two-way sync with a league's own live draft board.

Babies and Boomer drafts OFFLINE — the room calls picks out and Sleeper is
updated by hand afterwards — so Sleeper's draft endpoint stays empty all night
and there is nothing for the war room to follow. What the league actually uses is
its own keeper app's **Live Draft Board**, which records every pick as it is
called into `data/live_draft_<season>.json` on a GitHub branch.

That file is the source of truth for the night, so this module treats it as one:

  READ  — the public raw URL, no token needed. Every pick the room has logged
          arrives in the war room within a poll, whoever logged it.
  WRITE — the GitHub contents API with the app's own token, which already has
          push on that repo. Drafting here logs the pick THERE, so he doesn't
          have to type it twice with a room waiting.

The record's shape is the keeper app's, not ours, and is matched exactly:

    {"season": 2026,
     "picks": {"<overall pick no>": {"player_id", "player_name", "position", "nfl"}}}

`player_id` is a Sleeper id in both apps, so no mapping is needed — that is the
whole reason this is worth doing rather than scraping a rendered board.

A write is a read-modify-write against a file two apps can touch, so it retries
on GitHub's 409 (SHA conflict) exactly as the keeper app does. Losing a race here
would silently drop somebody's pick.
"""
from __future__ import annotations

import base64
import json
import os
import time
from typing import Dict, Optional, Tuple

import requests

_API = "https://api.github.com"
_RAW = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"

# league_id -> where that league keeps its live board.
BOARDS: Dict[str, dict] = {
    # Babies and Boomer
    "1312885282554535936": {"repo": "fabfreebird23/babies-and-boomer",
                            "branch": "keeper-data",
                            "path": "data/live_draft_{season}.json",
                            "label": "the B&B draft board"},
}


def board_for(league_id) -> Optional[dict]:
    return BOARDS.get(str(league_id))


def label(league_id) -> str:
    return (board_for(league_id) or {}).get("label", "the league board")


def _path(cfg: dict, season: int) -> str:
    return cfg["path"].format(season=int(season))


# ------------------------------------------------------------------------ read
def _read_doc(cfg: dict, season: int) -> Optional[dict]:
    """The board file, preferring the API and falling back to the raw URL.

    THE API FIRST, and this is not a preference. raw.githubusercontent serves a
    cached copy that a query-string cache-buster does NOT defeat — measured: a
    pick deleted through the API was still coming back from the raw URL a full
    minute later, while the API copy was already correct. On draft night that is
    picks arriving late, or a player showing as available after somebody took him,
    which is the one failure this whole feature exists to prevent.

    The raw URL stays as the fallback for a deploy with no token, where slightly
    stale is still enormously better than nothing.
    """
    tok = _token()
    if tok:
        try:
            r = requests.get(
                f"{_API}/repos/{cfg['repo']}/contents/{_path(cfg, season)}",
                headers={**_headers(tok), "Cache-Control": "no-cache"},
                params={"ref": cfg["branch"]}, timeout=12)
            if r.status_code == 200:
                body = base64.b64decode(r.json()["content"]).decode()
                return json.loads(body) if body.strip() else {}
            if r.status_code == 404:
                return {}
        except Exception:  # noqa: BLE001 — fall through to raw
            pass
    url = _RAW.format(repo=cfg["repo"], branch=cfg["branch"], path=_path(cfg, season))
    try:
        r = requests.get(url, params={"t": int(time.time())},
                         headers={"Cache-Control": "no-cache"}, timeout=12)
        if r.status_code != 200:
            return None
        return json.loads(r.text or "{}") or {}
    except Exception:  # noqa: BLE001
        return None


def load(league_id, season: int) -> Dict[int, str]:
    """{overall pick number: sleeper pid} — every pick the room has logged."""
    return load_full(league_id, season)[0]


def load_full(league_id, season: int):
    """({pick: pid}, {picks that are TAKEN}) — identity and occupancy, separately.

    They are not the same set and conflating them stopped the draft dead. The
    keeper app logs a pick it cannot name with an empty `player_id` — Joey's
    "49ers D/ST" resolved to nothing in ITS name index — and a pick with no name
    is still a pick. Dropping it left slot 2 looking empty, so the on-the-clock
    walk halted at 1.02 while the room was in round 3.
    """
    cfg = board_for(league_id)
    if not cfg:
        return {}, set()
    doc = _read_doc(cfg, season)
    if doc is None:
        return {}, set()
    out: Dict[int, str] = {}
    taken = set()
    for k, v in (doc.get("picks") or {}).items():
        try:
            ov = int(k)
        except (TypeError, ValueError):
            continue
        taken.add(ov)                      # the slot is used, named or not
        pid = str((v or {}).get("player_id") or "")
        if pid:
            out[ov] = pid
    return out, taken


# ----------------------------------------------------------------------- write
def _token() -> Optional[str]:
    """`board_token` if present, else the app's own `github_token`.

    They are separate settings on purpose. The app's token is fine-grained and
    scoped to THIS repo, so it can read the league's public board but cannot write
    to it — GitHub answers 403, and the repo metadata is no help because the
    `permissions` block it returns describes the USER's access, not the token's.
    Rather than widen the app's own token, a second one can be dropped in for the
    board alone.
    """
    if os.environ.get("DRAFTKIT_LOCAL_ONLY") == "1":
        return None
    try:
        import streamlit as st
        tok = st.secrets.get("board_token") or st.secrets.get("github_token")
        return str(tok) if tok else None
    except Exception:  # noqa: BLE001
        return None


def write_hint(league_id) -> str:
    """What to fix when a post is refused, in the words of the thing to change."""
    cfg = board_for(league_id) or {}
    return (f"Give the app a token that can write **{cfg.get('repo', 'the board repo')}** — "
            "either add that repo to the existing fine-grained token's repository "
            "access with **Contents: Read and write**, or add a second secret "
            "`board_token`. Reads keep working either way.")


def can_write(league_id) -> bool:
    return bool(board_for(league_id)) and bool(_token())


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}


def _fetch(cfg: dict, season: int, tok: str) -> Tuple[dict, Optional[str]]:
    r = requests.get(f"{_API}/repos/{cfg['repo']}/contents/{_path(cfg, season)}",
                     headers=_headers(tok), params={"ref": cfg["branch"]}, timeout=15)
    if r.status_code == 404:
        return {}, None
    r.raise_for_status()
    j = r.json()
    body = base64.b64decode(j["content"]).decode()
    return (json.loads(body) if body.strip() else {}), j.get("sha")


def post_pick(league_id, season: int, overall: int, pid: str, registry,
              *, remove: bool = False) -> Tuple[bool, str]:
    """Log (or unlog) one pick on the league's board. Returns (ok, message).

    Read-modify-write with a retry on 409: two people can be logging picks at the
    same time — him here and whoever is at the keyboard there — and a lost update
    means a pick that everyone believes was recorded and wasn't.

    Never raises. A failed post is reported to the caller so the war room can say
    "recorded here, NOT on the board" rather than implying both.
    """
    cfg = board_for(league_id)
    tok = _token()
    if not cfg:
        return False, "no board configured for this league"
    if not tok:
        return False, "no GitHub token configured"
    try:
        meta = registry.meta(pid) if pid else None
    except Exception:  # noqa: BLE001
        meta = None
    for attempt in range(4):
        try:
            doc, sha = _fetch(cfg, season, tok)
            picks = dict(doc.get("picks") or {})
            key = str(int(overall))
            if remove:
                if key not in picks:
                    return True, "already absent"
                picks.pop(key, None)
            else:
                picks[key] = {
                    "player_id": str(pid),
                    "player_name": getattr(meta, "name", "") or "",
                    "position": (getattr(meta, "position", "") or ""),
                    "nfl": (getattr(meta, "team", "") or ""),
                }
            doc["picks"] = picks
            doc.setdefault("season", int(season))
            body = {
                "message": f"live draft: pick {overall} from the draft dashboard",
                "content": base64.b64encode(
                    json.dumps(doc, indent=2).encode()).decode(),
                "branch": cfg["branch"],
            }
            if sha:
                body["sha"] = sha
            put = requests.put(f"{_API}/repos/{cfg['repo']}/contents/{_path(cfg, season)}",
                               headers=_headers(tok), json=body, timeout=20)
            if put.status_code in (200, 201):
                return True, "posted"
            if put.status_code != 409:
                return False, f"GitHub said {put.status_code}"
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                return False, type(e).__name__
        time.sleep(0.4 * (attempt + 1))
    return False, "conflict after retries"
