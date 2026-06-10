"""Lightweight standalone config.

Unlike the keeper-league app, there's no config.yaml / managers / draft-order
map here — leagues are imported at runtime (Sleeper or ESPN). This module only
provides the data dir and the defaults the copied ADP package expects
(`DATA_DIR`, `current_season`, `adp_sources`, `league().scoring`).
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DRAFTKIT_DATA", ROOT / "data"))


def current_season() -> int:
    """The ADP season to build. NFL drafts happen pre-season, so once we're past
    roughly June we target the current calendar year, else the prior year."""
    override = os.environ.get("DRAFTKIT_SEASON")
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    now = _dt.date.today()
    return now.year if now.month >= 4 else now.year - 1


def adp_sources() -> dict:
    """Which ADP providers the consensus builder runs. All public, no keys."""
    return {"espn": True, "fantasypros": True, "footballguys": True}


def league() -> dict:
    """Default ADP scoring when an imported league hasn't supplied one."""
    return {"scoring": "ppr"}
