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


# ---------------------------------------------------------------- display time
# Streamlit Cloud runs in UTC, so time.localtime() renders every league date in
# UTC there while rendering correctly on a local machine. Concretely: the Kreeper
# draft is Thu Aug 13 8:00pm Eastern, which is Fri Aug 14 00:00 UTC — so the
# deployed app was naming the WRONG DAY for a draft a week away. Fantasy leagues
# are scheduled in a human timezone, so pin one.
DISPLAY_TZ = "America/New_York"        # matches America/Indiana/Indianapolis


def to_local(epoch):
    """`epoch` seconds -> aware datetime in DISPLAY_TZ, falling back to the host's
    own local time if the tz database isn't present."""
    import datetime
    if not epoch:
        return None
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.fromtimestamp(float(epoch), ZoneInfo(DISPLAY_TZ))
    except Exception:  # noqa: BLE001 — missing tzdata must not break a date
        return datetime.datetime.fromtimestamp(float(epoch))


def fmt_local(epoch, fmt="%a %b %-d"):
    dt = to_local(epoch)
    return dt.strftime(fmt) if dt else "—"
