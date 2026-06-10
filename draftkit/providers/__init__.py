"""Provider factory."""
from __future__ import annotations

from .base import LeagueMeta, Pick, Provider, Team
from .espn import EspnAuthError, EspnProvider
from .sleeper import SleeperProvider

__all__ = ["LeagueMeta", "Pick", "Provider", "Team",
           "EspnProvider", "EspnAuthError", "SleeperProvider", "get_provider"]


def get_provider(platform, league_id, season, registry, *, espn_s2=None, swid=None) -> Provider:
    p = (platform or "").lower()
    if p == "sleeper":
        return SleeperProvider(league_id, season, registry)
    if p == "espn":
        return EspnProvider(league_id, season, registry, espn_s2=espn_s2, swid=swid)
    raise ValueError(f"Unknown platform: {platform!r}")
