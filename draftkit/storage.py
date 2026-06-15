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
def save_rankings(key: str, rankings: List[dict]) -> None:
    """Persist a personal rankings list (repo-backed when configured, else local)."""
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


# --- per-league rank/tier tweaks (overrides re-applied on every UDK refresh) ---
def _tweaks_local(key: str) -> Path:
    base = Path(os.environ.get("DRAFTKIT_DATA", config.DATA_DIR))
    base.mkdir(parents=True, exist_ok=True)
    return base / f"tweaks_{_safe_key(key)}.json"


def save_tweaks(key: str, tweaks: dict) -> None:
    if _gh_config() is not None:
        try:
            _gh_write(f"data/tweaks_{_safe_key(key)}.json", tweaks, f"tweaks ({key})")
            return
        except Exception:  # noqa: BLE001
            pass
    try:
        with _LOCK:
            _tweaks_local(key).write_text(json.dumps(tweaks, indent=2))
    except Exception:  # noqa: BLE001
        pass


def load_tweaks(key: str) -> dict:
    if _gh_config() is not None:
        try:
            data, _ = _gh_read(f"data/tweaks_{_safe_key(key)}.json")
            if isinstance(data, dict):
                return data
        except Exception:  # noqa: BLE001
            pass
    p = _tweaks_local(key)
    if p.exists():
        try:
            with _LOCK:
                return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {}
