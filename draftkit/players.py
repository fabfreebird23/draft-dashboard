"""Unified player-identity registry — the cross-platform join hub.

Rankings, ADP, Sleeper picks and ESPN picks all live in different id spaces.
`normalize_name` is the common key: we build one `Player` record per player and
index it by normalized name, Sleeper id, and ESPN id. This replaces the keeper
app's `H.player_meta`, `get_name_index`, and `get_espn_headshots`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from . import sleeper_client as sleeper, theme
from .names import normalize_name

_SKILL = ("QB", "RB", "WR", "TE")


@dataclass
class Player:
    sleeper_pid: Optional[str]
    espn_id: Optional[str]
    name: str
    position: str
    team: str
    # status/bio (from Sleeper's player blob; absent for synthetic/ESPN-only recs)
    age: Optional[int] = None
    years_exp: Optional[int] = None
    injury_status: Optional[str] = None
    injury_body_part: Optional[str] = None
    status: Optional[str] = None
    depth_chart_order: Optional[int] = None
    number: Optional[int] = None
    college: Optional[str] = None


class PlayerRegistry:
    def __init__(self) -> None:
        self.by_norm: Dict[str, Player] = {}
        self.by_sleeper: Dict[str, Player] = {}
        self.by_espn: Dict[str, Player] = {}

    # ---- lookups -------------------------------------------------------
    def resolve_name(self, name: str) -> Optional[Player]:
        return self.by_norm.get(normalize_name(name or ""))

    def resolve_sleeper(self, pid) -> Optional[Player]:
        return self.by_sleeper.get(str(pid))

    def resolve_espn(self, espn_id) -> Optional[Player]:
        return self.by_espn.get(str(espn_id))

    def meta(self, pid) -> Player:
        """Drop-in for the keeper app's H.player_meta(sleeper_pid). Always
        returns a Player — a synthetic one for ids we don't know."""
        p = self.by_sleeper.get(str(pid))
        if p:
            return p
        return Player(sleeper_pid=str(pid), espn_id=None, name=str(pid), position="", team="")

    # ---- mutation (used by the ESPN lazy player fetch) -----------------
    def add_espn(self, espn_id: str, name: str, position: str = "", team: str = "") -> Player:
        """Register/augment a player seen by ESPN id but missing from the index
        (deep bench / K / DST). Matches an existing record by name when possible."""
        key = normalize_name(name)
        p = self.by_norm.get(key)
        if p:
            if not p.espn_id:
                p.espn_id = str(espn_id)
        else:
            p = Player(sleeper_pid=None, espn_id=str(espn_id), name=name,
                       position=position, team=team)
            self.by_norm[key] = p
        self.by_espn[str(espn_id)] = p
        return p


def build_registry(season: int) -> PlayerRegistry:
    """Build the registry from Sleeper's player blob + ESPN's headshot board."""
    reg = PlayerRegistry()
    for pid, p in sleeper.get_players().items():
        if p.get("position") not in _SKILL:
            continue
        name = p.get("full_name") or ""
        nm = normalize_name(name)
        if not nm:
            continue
        # On a name collision, prefer the player who currently has a team.
        existing = reg.by_norm.get(nm)
        if existing is not None and existing.team and not p.get("team"):
            continue
        rec = Player(sleeper_pid=str(pid), espn_id=p.get("espn_id"),
                     name=name, position=p.get("position", ""), team=p.get("team") or "",
                     age=p.get("age"), years_exp=p.get("years_exp"),
                     injury_status=p.get("injury_status"),
                     injury_body_part=p.get("injury_body_part"),
                     status=p.get("status"),
                     depth_chart_order=p.get("depth_chart_order"),
                     number=p.get("number"), college=p.get("college"))
        reg.by_norm[nm] = rec
        reg.by_sleeper[str(pid)] = rec

    # Fill ESPN ids by name-joining ESPN's board (covers rookies with no Sleeper
    # photo, and gives us the espn_id -> Player index live drafts need).
    try:
        from .adp import espn as espn_adp
        espn_ids = espn_adp.headshot_ids(season)   # {normalized_name: espn_id}
    except Exception:  # noqa: BLE001 - ESPN unreachable: degrade, keep Sleeper-only
        espn_ids = {}
    for nm, eid in espn_ids.items():
        rec = reg.by_norm.get(nm)
        if rec is not None:
            if not rec.espn_id:
                rec.espn_id = str(eid)
    # Index every record that ended up with an espn_id.
    for rec in list(reg.by_norm.values()):
        if rec.espn_id:
            reg.by_espn[str(rec.espn_id)] = rec

    # Wire headshots: theme.img_tag prefers ESPN ids when present.
    theme.set_espn_ids({rec.sleeper_pid: rec.espn_id
                        for rec in reg.by_sleeper.values() if rec.espn_id})
    return reg
