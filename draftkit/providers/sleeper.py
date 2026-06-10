"""Sleeper provider — wraps the thin Sleeper client as a uniform Provider."""
from __future__ import annotations

from typing import List

from .. import sleeper_client as api
from .base import LeagueMeta, Pick, Provider, Team

_BENCH = {"BN", "IR", "TAXI"}
_DEFAULT_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "FLEX"]


def _scoring_label(lg: dict) -> str:
    rec = (lg.get("scoring_settings") or {}).get("rec", 0) or 0
    if rec >= 1:
        return "ppr"
    if rec >= 0.5:
        return "half"
    return "std"


class SleeperProvider(Provider):
    platform = "sleeper"

    def _league(self) -> dict:
        return api.get_league(self.league_id) or {}

    def get_league_meta(self) -> LeagueMeta:
        lg = self._league()
        roster_pos = lg.get("roster_positions") or []
        n_teams = int(lg.get("total_rosters") or lg.get("settings", {}).get("num_teams") or 0)
        draft_id = lg.get("draft_id")
        rounds = 0
        if draft_id:
            d = api.get_draft(draft_id) or {}
            rounds = int((d.get("settings") or {}).get("rounds") or 0)
        if not rounds:
            rounds = len([p for p in roster_pos if p not in _BENCH]) or 15
        return LeagueMeta(
            platform="sleeper",
            league_id=self.league_id,
            season=int(lg.get("season") or self.season),
            name=lg.get("name") or "Sleeper League",
            num_teams=n_teams or 12,
            draft_rounds=rounds,
            scoring=_scoring_label(lg),
            draft_id=draft_id,
        )

    def get_draft_order(self) -> List[Team]:
        lg = self._league()
        users = {u["user_id"]: u for u in (api.get_users(self.league_id) or [])}
        draft_id = lg.get("draft_id")
        order_map = {}
        if draft_id:
            order_map = (api.get_draft(draft_id) or {}).get("draft_order") or {}

        def uname(uid) -> str:
            u = users.get(str(uid)) or {}
            md = u.get("metadata") or {}
            return md.get("team_name") or u.get("display_name") or f"Team {uid}"

        teams: List[Team] = []
        if order_map:
            # draft_order is {user_id: 1-based slot}
            for uid, slot in order_map.items():
                teams.append(Team(slot=int(slot) - 1, team_id=str(uid), name=uname(uid)))
            teams.sort(key=lambda t: t.slot)
            return teams
        # Fallback: roster order (no draft order published yet).
        rosters = api.get_rosters(self.league_id) or []
        for i, r in enumerate(rosters):
            teams.append(Team(slot=i, team_id=str(r.get("owner_id")), name=uname(r.get("owner_id"))))
        return teams

    def get_traded_picks(self) -> dict:
        """{(round, original_owner_user_id): current_owner_user_id}. Sleeper tracks
        traded picks by roster_id, so we translate to the user_id space the rest of
        the app keys teams on."""
        lg = self._league()
        draft_id = lg.get("draft_id")
        if not draft_id:
            return {}
        rosters = api.get_rosters(self.league_id) or []
        rid_to_uid = {r.get("roster_id"): str(r.get("owner_id")) for r in rosters}
        out = {}
        for t in (api.get_traded_picks(draft_id) or []):
            rnd = t.get("round")
            orig = rid_to_uid.get(t.get("roster_id"))
            owner = rid_to_uid.get(t.get("owner_id"))
            if rnd and orig and owner:
                out[(int(rnd), orig)] = owner
        return out

    def get_roster_slots(self) -> List[str]:
        roster_pos = self._league().get("roster_positions") or []
        starters = [p for p in roster_pos if p not in _BENCH]
        # Sleeper uses SUPER_FLEX / WRRB_FLEX / REC_FLEX — normalize to FLEX label.
        starters = [("FLEX" if "FLEX" in p else p) for p in starters]
        return starters or list(_DEFAULT_SLOTS)

    def get_live_picks(self) -> List[Pick]:
        lg = self._league()
        draft_id = lg.get("draft_id")
        if not draft_id:
            return []
        n = self.get_league_meta().num_teams or 12
        raw = api.get_draft_picks_fresh(draft_id)
        picks: List[Pick] = []
        for p in raw:
            pid = p.get("player_id")
            overall = int(p.get("pick_no") or (len(picks) + 1))
            # draft_slot is 1-based; fall back to snake math from pick_no.
            slot = p.get("draft_slot")
            slot = (int(slot) - 1) if slot else _snake_slot(overall - 1, n)
            player = self.registry.resolve_sleeper(pid) if pid else None
            picks.append(Pick(overall=overall, slot=slot, player=player, raw_id=str(pid or "")))
        return picks


def _snake_slot(i: int, n: int) -> int:
    rd, j = divmod(i, n)
    return j if rd % 2 == 0 else n - 1 - j
