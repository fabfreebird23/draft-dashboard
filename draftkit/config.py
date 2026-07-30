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
    """Which ADP providers the consensus builder runs. All public, no keys.

    fantasypros is OFF: the page stopped shipping its ADP table in static HTML
    (only a 5x4 "Expert/Site/Date" table survives, so read_html raises "could not
    locate player column"), and there is no embedded JSON to fall back on the way
    UDK has — it is fetched client-side now. It has been contributing nothing
    while still costing a request and printing a FAILED status on every rebuild.
    FootballGuys still supplies the per-platform sub-columns (CBS, DraftKings,
    Drafters, NFFC, Underdog), so the consensus is unaffected. Flip back on if
    the scraper is ever reworked against their XHR endpoint."""
    return {"espn": True, "fantasypros": False, "footballguys": True}


def league() -> dict:
    """Default ADP scoring when an imported league hasn't supplied one."""
    return {"scoring": "ppr"}
