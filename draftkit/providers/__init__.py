"""Provider factory."""
from __future__ import annotations

from .base import LeagueMeta, Pick, Provider, Team
from .espn import EspnAuthError, EspnProvider
from .sleeper import SleeperProvider

__all__ = ["LeagueMeta", "Pick", "Provider", "Team",
           "EspnProvider", "EspnAuthError", "SleeperProvider", "get_provider"]


def get_provider(platform, league_id, season, registry, *, espn_s2=None, swid=None,
                 mock_draft_id=None) -> Provider:
    p = (platform or "").lower()
    if p == "sleeper":
        prov = SleeperProvider(league_id, season, registry)
        # Follow a standalone Sleeper mock instead of the league's own draft. Only
        # Sleeper: ESPN has no equivalent public read.
        prov.mock_draft_id = str(mock_draft_id) if mock_draft_id else None
        return prov
    if p == "espn":
        return EspnProvider(league_id, season, registry, espn_s2=espn_s2, swid=swid)
    raise ValueError(f"Unknown platform: {platform!r}")
