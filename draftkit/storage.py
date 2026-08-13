"""Persistence for a personal rankings board, keyed per league.

Two backends, chosen automatically:
  * GitHub repo — when Streamlit secrets provide a `github_token`. Rankings are
    stored as data/rankings_<key>.json on a dedicated data branch, so they survive
    Streamlit Cloud restarts and reload on any device.
  * Local JSON under data/ — fallback when no token is configured (local dev).

`key` is "{platform}_{league_id}" so each imported league keeps its own board.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import requests

from . import config

_LOCK = threading.Lock()
_API = "https://api.github.com"


def _safe_key(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "", str(key)) or "default"


# ------------------------------------------------------------------- local JSON
def _local_path(key: str) -> Path:
    base = Path(os.environ.get("DRAFTKIT_DATA", config.DATA_DIR))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"rankings_{_safe_key(key)}.json"


# ---------------------------------------------------------------- GitHub backend
def _gh_config() -> Optional[Tuple[str, str, str]]:
    try:
        import streamlit as st
        tok = st.secrets.get("github_token")
        if tok:
            repo = st.secrets.get("github_repo", "")
            branch = st.secrets.get("github_branch", "draft-data")
            if repo:
                return str(tok), str(repo), str(branch)
    except Exception:  # noqa: BLE001
        pass
    return None


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}


def _gh_path(key: str) -> str:
    return f"data/rankings_{_safe_key(key)}.json"


def _ensure_branch(repo: str, branch: str, tok: str) -> None:
    h = _headers(tok)
    if requests.get(f"{_API}/repos/{repo}/branches/{branch}", headers=h, timeout=15).status_code == 200:
        return
    info = requests.get(f"{_API}/repos/{repo}", headers=h, timeout=15).json()
    default = info.get("default_branch", "main")
    ref = requests.get(f"{_API}/repos/{repo}/git/ref/heads/{default}", headers=h, timeout=15).json()
    requests.post(f"{_API}/repos/{repo}/git/refs", headers=h, timeout=15,
                  json={"ref": f"refs/heads/{branch}", "sha": ref["object"]["sha"]})


def _gh_read(path: str) -> Tuple[List[dict], Optional[str]]:
    tok, repo, branch = _gh_config()
    r = requests.get(f"{_API}/repos/{repo}/contents/{path}",
                     headers=_headers(tok), params={"ref": branch}, timeout=15)
    if r.status_code == 404:
        return [], None
    r.raise_for_status()
    j = r.json()
    content = base64.b64decode(j["content"]).decode()
    return (json.loads(content) if content.strip() else []), j["sha"]


def _gh_write(path: str, obj, message: str) -> None:
    tok, repo, branch = _gh_config()
    _ensure_branch(repo, branch, tok)
    for _ in range(3):
        _, sha = _gh_read(path)
        body = {
            "message": message,
            "content": base64.b64encode(json.dumps(obj, indent=2).encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        r = requests.put(f"{_API}/repos/{repo}/contents/{path}",
                         headers=_headers(tok), json=body, timeout=20)
        if r.status_code in (200, 201):
            return
        if r.status_code != 409:
            r.raise_for_status()
    raise RuntimeError("GitHub rankings save failed after retries")


# ------------------------------------------------------------------- public API
# When THIS process saved each board. The persisted stamp is the durable record;
# this is the immediate one, and it exists because the age is read through a cached
# wrapper — without something that changes the moment you save, a fresh pull kept
# reporting the old age until the cache expired.
_SAVED_AT: dict = {}


def save_epoch(key: str) -> float:
    """When this process last saved `key`, or 0. Free — no I/O. Callers pass it as
    a cache key so a save invalidates their cached age."""
    return float(_SAVED_AT.get(key, 0.0))


def save_rankings(key: str, rankings: List[dict]) -> None:
    """Persist a personal rankings list (repo-backed when configured, else local).

    Also stamps when it was saved. Nothing auto-refreshes your UDK board — by
    design, it is hand-tuned and must never be overwritten — which means it can
    quietly drift weeks out of date with no signal anywhere in the UI. The stamp
    is what lets the topbar show its age."""
    _SAVED_AT[key] = time.time()
    _save_doc("ranksmeta", key, {"saved_at": time.time(), "n": len(rankings or [])})
    if _gh_config() is not None:
        try:
            _gh_write(_gh_path(key), rankings, f"rankings ({key})")
            return
        except Exception:  # noqa: BLE001 - fall through to local on any GH error
            pass
    try:
        with _LOCK:
            _local_path(key).write_text(json.dumps(rankings, indent=2))
    except Exception:  # noqa: BLE001
        pass


_SEED = config.ROOT / "data_seed" / "udk_default.json"


def load_rankings(key: str) -> List[dict]:
    if _gh_config() is not None:
        try:
            data, _ = _gh_read(_gh_path(key))
            if data:
                return data
        except Exception:  # noqa: BLE001
            pass
    p = _local_path(key)
    if p.exists():
        try:
            with _LOCK:
                return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    # Committed UDK seed so a fresh / cloud deploy ships with a board even when the
    # server-side UDK pull is blocked (The Fantasy Footballers blocks datacenter IPs)
    # and local storage was wiped on reboot.
    if _SEED.exists():
        try:
            return json.loads(_SEED.read_text())
        except Exception:  # noqa: BLE001
            pass
    return []


# ---- generic per-league JSON doc (repo-backed when configured, else local) ----
def _doc_local(kind: str, key: str) -> Path:
    base = Path(os.environ.get("DRAFTKIT_DATA", config.DATA_DIR))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{kind}_{_safe_key(key)}.json"


def _save_doc(kind: str, key: str, obj) -> None:
    if _gh_config() is not None:
        try:
            _gh_write(f"data/{kind}_{_safe_key(key)}.json", obj, f"{kind} ({key})")
            return
        except Exception:  # noqa: BLE001 - fall through to local on any GH error
            pass
    try:
        with _LOCK:
            _doc_local(kind, key).write_text(json.dumps(obj, indent=2))
    except Exception:  # noqa: BLE001
        pass


def _load_doc(kind: str, key: str, default):
    if _gh_config() is not None:
        try:
            data, _ = _gh_read(f"data/{kind}_{_safe_key(key)}.json")
            if isinstance(data, type(default)):
                return data
        except Exception:  # noqa: BLE001
            pass
    p = _doc_local(kind, key)
    if p.exists():
        try:
            with _LOCK:
                return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    return default


# --- per-league rank/tier tweaks (overrides re-applied on every UDK refresh) ---
def _tweaks_local(key: str) -> Path:
    return _doc_local("tweaks", key)


def save_tweaks(key: str, tweaks: dict) -> None:
    _save_doc("tweaks", key, tweaks)


def load_tweaks(key: str) -> dict:
    return _load_doc("tweaks", key, {})


# --- per-league AI draft boards: which ranking source each manager drafts off ---
def save_ai_sources(key: str, sources: dict) -> None:
    """`sources` is {slot_index_as_str: source_name}. Stored per league so the
    boards you assign to each manager survive a restart instead of resetting to
    Consensus every session."""
    _save_doc("aisrc", key, {str(k): v for k, v in (sources or {}).items()})


def load_ai_sources(key: str) -> dict:
    return _load_doc("aisrc", key, {})


def _gh_last_commit_hours(path: str) -> Optional[float]:
    """Hours since the repo backend last committed `path`, or None.

    Needed because boards saved before stamping existed have no saved_at, and the
    repo backend has no mtime — without this the age reads "unknown" on exactly
    the league that matters until the next pull. One extra API call, so callers
    should cache it (app.get_board_age does)."""
    cfg = _gh_config()
    if not cfg:
        return None
    tok, repo, branch = cfg
    try:
        r = requests.get(f"{_API}/repos/{repo}/commits", headers=_headers(tok),
                         params={"path": path, "sha": branch, "per_page": 1}, timeout=15)
        if r.status_code != 200:
            return None
        js = r.json()
        if not js:
            return None
        iso = js[0]["commit"]["committer"]["date"]          # e.g. 2026-06-10T04:11:02Z
        from datetime import datetime, timezone
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    except Exception:  # noqa: BLE001
        return None


def rankings_age_hours(key: str) -> Optional[float]:
    """How old the saved board is, in hours, or None if we genuinely can't tell.

    Three fallbacks, because the board can live in either backend and may predate
    stamping: the saved_at stamp, then the repo file's last commit date, then the
    local file's mtime."""
    # This process just wrote it — more authoritative than any backend read, and it
    # cannot be stale.
    if _SAVED_AT.get(key):
        return max(0.0, (time.time() - _SAVED_AT[key]) / 3600.0)
    meta = _load_doc("ranksmeta", key, {})
    ts = meta.get("saved_at") if isinstance(meta, dict) else None
    if ts:
        try:
            return max(0.0, (time.time() - float(ts)) / 3600.0)
        except (TypeError, ValueError):
            pass
    gh = _gh_last_commit_hours(_gh_path(key))
    if gh is not None:
        return gh
    p = _local_path(key)
    try:
        if p.exists():
            return max(0.0, (time.time() - p.stat().st_mtime) / 3600.0)
    except OSError:
        pass
    return None
