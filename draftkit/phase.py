"""Where each league is in its year, and a cheap summary of what it needs from you.

Phase is DERIVED from the league's own draft, never a setting you flip. That
matters here specifically: Kreeper drafts Aug 13 and Babies & Boomer Sep 7, so for
three weeks two of your leagues are in different halves of the year at once. A
single global pre/in-season switch would be wrong for one of them the whole time.

`summary()` is deliberately thin. The Home screen shows every league at once, and
building a full draft context for four leagues would mean four registries, four
ADP joins and four keeper fetches before anything renders.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from . import config, sleeper_client as api

PRE, LIVE, IN, DONE = "pre", "live", "in", "done"

_ESPN_LEAGUE = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
                "/seasons/{season}/segments/0/leagues/{lid}")
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


@dataclass
class Summary:
    label: str
    platform: str
    league_id: str
    season: int
    phase: str                       # pre | live | in | done
    name: str = ""
    num_teams: int = 0
    draft_at: Optional[float] = None  # epoch seconds, None when unscheduled
    drafted: bool = False
    note: str = ""                   # the single most urgent thing
    tone: str = "nil"                # red | amber | ok | nil
    error: str = ""

    @property
    def days_to_draft(self) -> Optional[float]:
        if not self.draft_at:
            return None
        return (self.draft_at - time.time()) / 86400.0


def _sleeper(preset: dict) -> Summary:
    lid = str(preset["league_id"])
    s = Summary(label=preset.get("label") or lid, platform="sleeper", league_id=lid,
                season=int(preset.get("season") or config.current_season()), phase=PRE)
    lg = api.get_league(lid) or {}
    s.name = lg.get("name") or s.label
    s.num_teams = int(lg.get("total_rosters") or 0)
    did = lg.get("draft_id")
    if did:
        d = api.get_draft(did) or {}
        st_ = (d.get("start_time") or 0) / 1000.0 or None
        s.draft_at = st_
        status = (d.get("status") or "").lower()
        s.drafted = status == "complete"
        if status == "drafting":
            s.phase = LIVE
        elif s.drafted:
            s.phase = IN
    return s


def _espn(preset: dict) -> Summary:
    import requests
    lid = str(preset["league_id"])
    season = int(preset.get("season") or config.current_season())
    s = Summary(label=preset.get("label") or lid, platform="espn", league_id=lid,
                season=season, phase=PRE)
    try:
        r = requests.get(_ESPN_LEAGUE.format(season=season, lid=lid), headers=_HEADERS,
                         params={"view": "mSettings"}, timeout=15)
        r.raise_for_status()
        j = r.json() or {}
    except Exception as e:  # noqa: BLE001 — a league that won't load must not break Home
        s.error = type(e).__name__
        return s
    st_ = j.get("settings") or {}
    s.name = st_.get("name") or s.label
    s.num_teams = int(st_.get("size") or 0)
    ms = (st_.get("draftSettings") or {}).get("date")
    s.draft_at = (ms / 1000.0) if ms else None
    s.drafted = bool((j.get("draftDetail") or {}).get("drafted"))
    if s.drafted:
        s.phase = IN
    return s


def summary(preset: dict, board_age_h: Optional[float] = None) -> Summary:
    """One league's phase plus the single line Home should show for it."""
    try:
        s = _sleeper(preset) if preset.get("platform") == "sleeper" else _espn(preset)
    except Exception as e:  # noqa: BLE001
        return Summary(label=preset.get("label") or str(preset.get("league_id")),
                       platform=preset.get("platform", ""), league_id=str(preset.get("league_id")),
                       season=int(preset.get("season") or config.current_season()),
                       phase=PRE, error=type(e).__name__,
                       note="Couldn't reach this league right now.", tone="nil")
    _annotate(s, board_age_h)
    return s


def _annotate(s: Summary, board_age_h: Optional[float]) -> None:
    """Pick the ONE thing worth saying. Ordered by what actually blocks you, so a
    league drafting this week always outranks a stale board on one drafting next
    month — the whole point of the screen is that you don't have to triage."""
    if s.error:
        s.note, s.tone = "Couldn't reach this league right now.", "nil"
        return
    if s.phase == LIVE:
        s.note, s.tone = "Draft is LIVE right now — open the war room.", "red"
        return
    if s.phase == IN:
        s.note, s.tone = "Drafted. In-season — check your lineup.", "ok"
        return
    d = s.days_to_draft
    if d is None:
        s.note, s.tone = ("No draft date set yet. Nothing to prep until there is.", "nil")
        return
    if d < 0:
        s.note, s.tone = ("Draft date has passed but Sleeper still shows it unstarted.", "amber")
        return
    days = max(1, int(round(d)))
    when = time.strftime("%a %b %-d", time.localtime(s.draft_at))
    if board_age_h is not None and board_age_h / 24.0 >= 7 and d <= 14:
        s.note = (f"Drafts in {days} day{'s' if days != 1 else ''} ({when}) — "
                  f"your board is {int(board_age_h / 24)} days old.")
        s.tone = "red" if d <= 7 else "amber"
        return
    s.note = f"Drafts in {days} day{'s' if days != 1 else ''} · {when}."
    s.tone = "red" if d <= 7 else ("amber" if d <= 21 else "nil")


_ORDER = {"red": 0, "amber": 1, "ok": 2, "nil": 3}


def sort_key(s: Summary):
    """Most urgent first; within a tone, the sooner draft wins."""
    return (_ORDER.get(s.tone, 9), s.days_to_draft if s.days_to_draft is not None else 9e9)
