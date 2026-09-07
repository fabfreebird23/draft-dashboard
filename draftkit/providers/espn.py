"""ESPN provider — public + private (espn_s2/SWID cookie) league reads.

ESPN's fantasy API is undocumented/reverse-engineered. We read three views off
the league endpoint: mSettings (name/size/roster/scoring), mTeam (team names),
mDraftDetail (the picks). Private leagues need the espn_s2 + SWID cookies; public
leagues work with none. We never crash the app — a 401 surfaces as a clear
"needs cookies" message and an empty board.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

import requests

from ..adp.base import BROWSER_HEADERS
from .base import LeagueMeta, Pick, Provider, Team

_HOST = "https://lm-api-reads.fantasy.espn.com"
_LEAGUE_URL = _HOST + "/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{lid}"
_PLAYERS_URL = _HOST + "/apis/v3/games/ffl/seasons/{season}/players?scoringPeriodId=0&view=players_wl"

# ESPN lineupSlotId -> our label. FLEX-ish slots collapse to FLEX.
_SLOT_LABEL = {
    0: "QB", 1: "QB", 2: "RB", 3: "FLEX", 4: "WR", 5: "FLEX", 6: "TE",
    7: "FLEX", 16: "DST", 17: "K", 23: "FLEX",
}
_SKIP_SLOTS = {20, 21, 24}        # bench, IR, error
_SLOT_ORDER = [0, 1, 2, 4, 6, 23, 3, 5, 7, 17, 16]   # display order for starters
_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}

# ESPN proTeamId -> the abbreviation Sleeper uses as a DEFENSE's player id.
# Defenses are the one roster entry ESPN gives a NEGATIVE playerId (-16000 minus
# the pro team), so they resolve through nothing the player index knows about —
# which is how two D/STs went missing from a sixteen-man roster.
_PRO_TEAM = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET",
    9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA",
    16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI",
    23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS", 29: "CAR",
    30: "JAX", 33: "BAL", 34: "HOU",
}


class EspnAuthError(RuntimeError):
    """Raised when a private league rejects the read (missing/expired cookies)."""


class EspnProvider(Provider):
    platform = "espn"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._cache: Dict[str, dict] = {}
        self._players_loaded = False

    # ---- HTTP ----------------------------------------------------------
    def _cookies(self) -> Optional[dict]:
        if self.espn_s2 and self.swid:
            swid = self.swid if self.swid.startswith("{") else "{%s}" % self.swid
            return {"espn_s2": self.espn_s2, "SWID": swid}
        return None

    def _read(self, views, fresh: bool = False) -> dict:
        key = ",".join(views)
        if not fresh and key in self._cache:
            return self._cache[key]
        url = _LEAGUE_URL.format(season=self.season, lid=self.league_id)
        try:
            r = requests.get(url, headers=BROWSER_HEADERS, params={"view": list(views)},
                             cookies=self._cookies(), timeout=20)
        except requests.RequestException as e:
            raise RuntimeError(f"ESPN unreachable: {e}") from e
        if r.status_code in (401, 403):
            raise EspnAuthError(
                "ESPN denied this league (401/403). If it's private, paste fresh "
                "espn_s2 + SWID cookies; if public, double-check the league ID/season."
            )
        r.raise_for_status()
        data = r.json()
        if not fresh:
            self._cache[key] = data
        return data

    # ---- provider API --------------------------------------------------
    def get_league_meta(self) -> LeagueMeta:
        d = self._read(["mSettings"])
        s = d.get("settings", {})
        slot_counts = (s.get("rosterSettings", {}) or {}).get("lineupSlotCounts", {}) or {}
        roster_size = sum(int(v) for k, v in slot_counts.items() if int(k) not in (21, 24))
        rounds = roster_size or 15
        return LeagueMeta(
            platform="espn",
            league_id=self.league_id,
            season=self.season,
            name=s.get("name") or "ESPN League",
            num_teams=int(s.get("size") or len(d.get("teams") or []) or 10),
            draft_rounds=rounds,
            scoring=_scoring_label(s),
            scoring_weights=_scoring_weights(s),
            playoff_settings={
                # ESPN gives the regular-season length, so playoffs start after it.
                "start": int((s.get("scheduleSettings") or {}).get("matchupPeriodCount") or 0) + 1,
                "teams": (s.get("scheduleSettings") or {}).get("playoffTeamCount"),
            },
            draft_id=self.league_id,   # ESPN has no separate draft id
            offline_draft=(str((s.get("draftSettings") or {}).get("type") or "").upper()
                           == "OFFLINE"),
        )

    def get_draft_order(self) -> List[Team]:
        d = self._read(["mSettings", "mTeam"])
        names = {t.get("id"): _team_name(t) for t in (d.get("teams") or [])}
        order = ((d.get("settings", {}).get("draftSettings") or {}).get("pickOrder")) or []
        teams: List[Team] = []
        if order:
            for slot, tid in enumerate(order):
                teams.append(Team(slot=slot, team_id=str(tid), name=names.get(tid, f"Team {tid}")))
            return teams
        for slot, (tid, nm) in enumerate(sorted(names.items())):
            teams.append(Team(slot=slot, team_id=str(tid), name=nm))
        return teams

    def get_roster_slots(self) -> List[str]:
        d = self._read(["mSettings"])
        counts = ((d.get("settings", {}).get("rosterSettings") or {})
                  .get("lineupSlotCounts", {})) or {}
        slots: List[str] = []
        for sid in _SLOT_ORDER:
            n = int(counts.get(str(sid), 0) or 0)
            slots.extend([_SLOT_LABEL[sid]] * n)
        # Any unmapped non-bench starter slots → labelled if known, else FLEX.
        for k, v in counts.items():
            sid = int(k)
            if sid in _SKIP_SLOTS or sid in _SLOT_ORDER:
                continue
            slots.extend([_SLOT_LABEL.get(sid, "FLEX")] * int(v))
        return slots or ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]

    def get_bench_count(self) -> int:
        # ESPN's lineupSlotCounts has bench under slot 20; fall back to the gap
        # between draft rounds and starters when it is missing.
        d = self._read(["mSettings"])
        counts = ((d.get("settings", {}).get("rosterSettings") or {})
                  .get("lineupSlotCounts", {})) or {}
        bn = int(counts.get("20", 0) or 0)
        if bn:
            return bn
        return max(0, self.get_league_meta().draft_rounds - len(self.get_roster_slots()))

    def get_live_picks(self) -> List[Pick]:
        d = self._read(["mDraftDetail"], fresh=True)
        dd = d.get("draftDetail", {}) or {}
        raw = dd.get("picks") or []
        if not raw:
            return []
        order = ((self._read(["mSettings"]).get("settings", {})
                  .get("draftSettings") or {}).get("pickOrder")) or []
        team_to_slot = {tid: i for i, tid in enumerate(order)}
        n = self.get_league_meta().num_teams or 10
        picks: List[Pick] = []
        for p in raw:
            espn_pid = p.get("playerId")
            # ESPN publishes the WHOLE GRID before a pick is made — 204 rows with
            # playerId -1, one per slot, from the moment the league is created. Read
            # literally, that is a complete draft: the war room opened on draft day
            # saying "192 of 192 · no more picks" and offered nothing, because every
            # empty slot counted as a pick that had happened. An empty slot is not a
            # pick; drop it and let the app see the draft that is actually there.
            try:
                if int(espn_pid) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            overall = int(p.get("overallPickNumber") or (len(picks) + 1))
            tid = p.get("teamId")
            slot = team_to_slot.get(tid)
            if slot is None:
                slot = _snake_slot(overall - 1, n)
            player = self.registry.resolve_espn(espn_pid) if espn_pid else None
            if player is None and espn_pid:
                player = self._lazy_player(espn_pid)
            picks.append(Pick(overall=overall, slot=slot, player=player, raw_id=str(espn_pid or "")))
        return picks

    def get_rosters(self) -> dict:
        """{team_id: {players, starters, ...}} — every roster in the league.

        The in-season screens were built on Sleeper, whose rosters endpoint this
        mirrors exactly, so they can read an ESPN league without knowing it is one.

        This is also the ONLY honest source of who was drafted in a league that
        drafts offline. "Show us your TD's" enters its results by adding players to
        rosters, not into ESPN's draft tool — which is why the draft grid is still
        204 rows of playerId -1 while all twelve rosters are full.

        `scoringPeriodId` is deliberately omitted: without it ESPN returns the
        CURRENT week, which is what every caller here means by "the roster".
        """
        d = self._read(["mRoster", "mTeam"], fresh=True)
        out = {}
        # Starters have to come back in the SAME ORDER as get_roster_slots() lists
        # the slots, because the lineup screens pair the two lists by position.
        # ESPN returns roster entries in whatever order it likes, which is how the
        # Command Center ended up labelling a defense "K" and a kicker "DST".
        _rank = {sid: i for i, sid in enumerate(_SLOT_ORDER)}
        for t in d.get("teams") or []:
            players, starters = [], []
            for e in ((t.get("roster") or {}).get("entries") or []):
                espn_pid = e.get("playerId")
                pid = None
                if espn_pid is not None and int(espn_pid) < 0:
                    # A defense. Its id carries the pro team and nothing else, so
                    # go straight to the abbreviation Sleeper keys defenses by.
                    _pe = (e.get("playerPoolEntry") or {}).get("player") or {}
                    pid = _PRO_TEAM.get(int(_pe.get("proTeamId") or 0)) or \
                        _PRO_TEAM.get(-int(espn_pid) - 16000)
                if pid is None:
                    p = self.registry.resolve_espn(espn_pid) if espn_pid else None
                    if p is None and espn_pid:
                        p = self._lazy_player(espn_pid)
                    if p is None or not p.sleeper_pid:
                        continue
                    pid = str(p.sleeper_pid)
                players.append(pid)
                sid = e.get("lineupSlotId")
                if sid not in _SKIP_SLOTS:
                    starters.append((_rank.get(sid, 99), pid))
            starters = [pid for _r, pid in sorted(starters, key=lambda x: x[0])]
            out[str(t.get("id"))] = {"players": players, "starters": starters,
                                     "settings": {}, "roster_id": t.get("id")}
        return out

    # ---- ESPN id -> name (bench/K/DST the headshot board missed) --------
    def _lazy_player(self, espn_pid):
        if not self._players_loaded:
            self._load_player_universe()
        return self.registry.resolve_espn(espn_pid)

    def _load_player_universe(self) -> None:
        self._players_loaded = True
        flt = {"players": {"limit": 5000}}
        try:
            r = requests.get(
                _PLAYERS_URL.format(season=self.season),
                headers={**BROWSER_HEADERS, "X-Fantasy-Filter": json.dumps(flt)},
                cookies=self._cookies(), timeout=25,
            )
            r.raise_for_status()
            data = r.json()
        except Exception:  # noqa: BLE001 - best effort; unmatched picks show raw id
            return
        items = data if isinstance(data, list) else data.get("players", [])
        for it in items:
            p = it.get("player", it) if isinstance(it, dict) else {}
            eid = it.get("id") if isinstance(it, dict) else None
            eid = eid or p.get("id")
            name = p.get("fullName") or ""
            if eid and name:
                self.registry.add_espn(str(eid), name, _POS.get(p.get("defaultPositionId"), ""))


def _scoring_weights(settings: dict):
    """Exact weights from the league's own scoring settings, or None."""
    from .. import scoring as _sc
    return _sc.from_espn(settings)


def _scoring_label(settings: dict) -> str:
    """Closest ppr/half/std label. Lossy on purpose — see LeagueMeta.scoring."""
    from .. import scoring as _sc
    w = _sc.from_espn(settings)
    if w:
        return _sc.label_for(w)
    items = (settings.get("scoringSettings", {}) or {}).get("scoringItems", []) or []
    for it in items:
        if it.get("statId") == 53:        # receptions
            pts = it.get("points", 0) or 0
            return "ppr" if pts >= 1 else "half" if pts >= 0.5 else "std"
    return "ppr"


def _team_name(t: dict) -> str:
    loc, nick = (t.get("location") or "").strip(), (t.get("nickname") or "").strip()
    full = (loc + " " + nick).strip()
    return full or t.get("name") or t.get("abbrev") or f"Team {t.get('id')}"


def _snake_slot(i: int, n: int) -> int:
    rd, j = divmod(i, n)
    return j if rd % 2 == 0 else n - 1 - j
