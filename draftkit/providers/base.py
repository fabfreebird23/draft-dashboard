"""Platform-agnostic shapes + Provider interface.

A Provider turns one imported league (Sleeper or ESPN) into a uniform API the
mock/live UIs consume. The key normalized type is `Pick` — both platforms emit
the same shape, so the FantasyPros-style render code never branches on platform.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from ..players import Player


@dataclass
class LeagueMeta:
    platform: str            # "sleeper" | "espn"
    league_id: str
    season: int
    name: str
    num_teams: int
    draft_rounds: int
    scoring: str             # "ppr" | "half" | "std"
    draft_id: Optional[str] = None


@dataclass
class Team:
    slot: int                # 0-based draft slot
    team_id: str             # sleeper roster/owner id OR espn teamId (as str)
    name: str


@dataclass
class Pick:
    """One drafted player, normalized across platforms."""
    overall: int             # 1-based overall pick number
    slot: int                # 0-based draft slot of the team that made the pick
    player: Optional[Player] = None     # resolved via the registry; None if unmatched
    raw_id: str = ""         # platform player id, for debugging / unmatched display


class Provider(ABC):
    platform: str = ""

    def __init__(self, league_id, season, registry, *, espn_s2=None, swid=None):
        self.league_id = str(league_id)
        self.season = int(season)
        self.registry = registry
        self.espn_s2 = espn_s2
        self.swid = swid

    @abstractmethod
    def get_league_meta(self) -> LeagueMeta: ...

    @abstractmethod
    def get_draft_order(self) -> List[Team]:
        """Teams ordered by 0-based draft slot."""

    @abstractmethod
    def get_roster_slots(self) -> List[str]:
        """Starter lineup slots, e.g. ['QB','RB','RB','WR','WR','TE','FLEX']."""

    @abstractmethod
    def get_live_picks(self) -> List[Pick]:
        """Fresh (uncached) normalized picks. Empty list before a draft starts."""
