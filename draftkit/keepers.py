"""Keeper integration — pull current-season keepers from our keeper dashboards.

The two Sleeper leagues each have a companion keeper dashboard (separate repos)
that stores submitted keepers on a public `keeper-data` branch as
data/keepers_<season>.json: {owner_id: [{player_id, player_name, position,
cost_round, is_rookie_keeper, ...}]}. We read those (no auth — public raw URL)
and apply them to the draft: kept players are removed from the pool and placed on
the board at each owner's pick in their keeper's cost_round.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

import requests

# Sleeper league_id -> the keeper dashboard repo that owns its keeper data.
KEEPER_REPOS: Dict[str, dict] = {
    "1310907162930733056": {"repo": "fabfreebird23/kreeper-league", "branch": "keeper-data"},
    "1312885282554535936": {"repo": "fabfreebird23/babies-and-boomer", "branch": "keeper-data"},
}
_RAW = "https://raw.githubusercontent.com/{repo}/{branch}/data/keepers_{season}.json"


def league_has_keepers(league_id: str) -> bool:
    return str(league_id) in KEEPER_REPOS


_CONFIG_RAW = "https://raw.githubusercontent.com/{repo}/{branch}/config.yaml"


def load_draft_order(league_id: str) -> List[str]:
    """Owner IDs in draft-slot order (slot 1 first), scraped from the league's
    keeper-dashboard config.yaml. Returns [] if the dashboard hasn't set one
    (then we fall back to Sleeper's own order)."""
    cfg = KEEPER_REPOS.get(str(league_id))
    if not cfg:
        return []
    for branch in ("main", "master"):
        url = _CONFIG_RAW.format(repo=cfg["repo"], branch=branch)
        try:
            r = requests.get(url, timeout=12)
            if r.status_code == 200 and "draft_order" in r.text:
                return _parse_draft_order(r.text)
        except Exception:  # noqa: BLE001
            continue
    return []


def _parse_draft_order(text: str) -> List[str]:
    import re
    out, in_block = [], False
    for line in text.splitlines():
        if re.match(r"^draft_order\s*:", line):
            in_block = True
            continue
        if not in_block:
            continue
        m = re.match(r'^\s*-\s*"?(\d+)"?', line)
        if m:
            out.append(m.group(1))
            continue
        # a new top-level key (no indent, has a colon) ends the block
        if line.strip() and not line[0].isspace() and not line.lstrip().startswith("#"):
            break
    return out


def load_keepers(league_id: str, season: int) -> Dict[str, List[dict]]:
    """{owner_id: [keeper dicts]} for the league/season, or {} if none/unknown."""
    cfg = KEEPER_REPOS.get(str(league_id))
    if not cfg:
        return {}
    for yr in (season, season - 1):   # fall back to last year as a preview
        url = _RAW.format(repo=cfg["repo"], branch=cfg["branch"], season=yr)
        try:
            r = requests.get(url, timeout=12)
            if r.status_code == 200 and r.text.strip():
                data = json.loads(r.text)
                if any(data.values()):
                    return data
        except Exception:  # noqa: BLE001
            continue
    return {}


def build_placements(keepers: Dict[str, List[dict]], owner_slot: Dict[str, int],
                     n_teams: int, rounds: int) -> dict:
    """Map each keeper onto the draft board.

    Returns {
      "by_overall": {overall_pick -> pid},   # where each keeper sits on the board
      "kept_pids":  set(pid),                 # all kept players (remove from pool)
      "by_owner":   {owner_id -> [pid,...]},
    }
    Snake order; a keeper occupies its owner's pick in `cost_round`. If two
    keepers collide on a round, the second bumps to the owner's next free round.
    """
    by_overall: Dict[int, str] = {}
    kept_pids = set()
    by_owner: Dict[str, list] = {}

    def overall_for(slot: int, rnd: int) -> int:
        # 0-based slot, 1-based round, snake.
        if rnd % 2 == 1:
            col = slot
        else:
            col = n_teams - 1 - slot
        return (rnd - 1) * n_teams + col + 1

    for owner_id, klist in keepers.items():
        slot = owner_slot.get(str(owner_id))
        if slot is None:
            continue
        used_rounds = set()
        # place lowest-round (most expensive) keepers first for stable assignment
        for k in sorted(klist, key=lambda x: x.get("cost_round") or rounds):
            pid = str(k.get("player_id") or "")
            if not pid:
                continue
            want = max(1, min(rounds, int(k.get("cost_round") or rounds)))
            # nearest free round to the cost round (search outward), so two keepers
            # never collide even at the last round.
            rnd = want
            for d in range(rounds):
                for cand in ((want + d), (want - d)):
                    if 1 <= cand <= rounds and cand not in used_rounds:
                        rnd = cand
                        break
                else:
                    continue
                break
            used_rounds.add(rnd)
            ov = overall_for(slot, rnd)
            by_overall[ov] = pid
            kept_pids.add(pid)
            by_owner.setdefault(str(owner_id), []).append(pid)
    return {"by_overall": by_overall, "kept_pids": kept_pids, "by_owner": by_owner}
