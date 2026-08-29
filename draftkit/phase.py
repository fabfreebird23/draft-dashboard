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
    # Same rounding fix as the hero tile's _days_label: on the morning of a draft
    # "in 1 day" is wrong in the direction that matters, and the note sat right
    # beside a tile reading "3 hours". One draft, two numbers, is worse than either.
    hours = d * 24.0
    countdown = (f"in {max(1, int(round(hours)))} hours" if hours < 23.5
                 else f"in {days} day{'s' if days != 1 else ''}")
    # DISPLAY_TZ, not the host clock: Cloud runs UTC and was naming the wrong
    # day for a draft scheduled at 8pm Eastern.
    when = config.fmt_local(s.draft_at, "%a %b %-d")
    # A week-old board is fine in July and not fine on draft morning — the same
    # two-day rule the Home tile uses inside the last 48 hours.
    stale_days = 2.0 if d <= 2 else 7.0
    if board_age_h is not None and board_age_h / 24.0 >= stale_days and d <= 14:
        aged = (f"{int(board_age_h)}h old" if board_age_h < 48
                else f"{int(board_age_h / 24)} days old")
        s.note = f"Drafts {countdown} ({when}) — your board is {aged}."
        s.tone = "red" if d <= 7 else "amber"
        return
    s.note = f"Drafts {countdown} · {when}."
    s.tone = "red" if d <= 7 else ("amber" if d <= 21 else "nil")


_ORDER = {"red": 0, "amber": 1, "ok": 2, "nil": 3}


def sort_key(s: Summary):
    """Most urgent first; within a tone, the sooner draft wins."""
    return (_ORDER.get(s.tone, 9), s.days_to_draft if s.days_to_draft is not None else 9e9)


def detail(preset: dict, registry=None) -> dict:
    """Extra state for ONE league — the hero on Home, and nothing else.

    Kept off `summary()` on purpose: Home renders every league, and keeper +
    draft-order lookups per league would turn a fast screen into four round trips
    before anything appeared. Only the league promoted to the hero pays this.
    """
    out = {"kept": 0, "expected": 0, "short": "", "slot_names": []}
    lid = str(preset.get("league_id"))
    if preset.get("platform") != "sleeper":
        return out
    try:
        from . import keepers as K
        rules = K.load_keeper_rules(lid)
        per = (rules.get("max_regular_keepers") or 0) + (rules.get("max_rookie_keepers") or 0)
        raw = K.load_keepers(lid, int(preset.get("season") or config.current_season())) or {}
        out["kept"] = sum(len(v or []) for v in raw.values())
        teams = 0
        try:
            lg = api.get_league(lid) or {}
            teams = int(lg.get("total_rosters") or 0)
        except Exception:  # noqa: BLE001
            pass
        out["expected"] = per * teams if (per and teams) else 0
        if per and raw:
            names = K.load_manager_names(lid) or {}
            short = [(names.get(str(o), "A team"), per - len(v or []))
                     for o, v in raw.items() if len(v or []) < per]
            if short:
                who, n = short[0]
                out["short"] = (f"{who} still owes {n}" if len(short) == 1
                                else f"{len(short)} teams still owe keepers")
    except Exception:  # noqa: BLE001 — the hero must render even if this doesn't
        pass
    return out
