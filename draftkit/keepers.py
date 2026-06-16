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


def load_manager_names(league_id: str) -> dict:
    """{owner_id: real manager name} scraped from the keeper-dashboard config.yaml
    `managers` map, so we can show people's names instead of Sleeper team names."""
    import re
    cfg = KEEPER_REPOS.get(str(league_id))
    if not cfg:
        return {}
    for branch in ("main", "master"):
        url = _CONFIG_RAW.format(repo=cfg["repo"], branch=branch)
        try:
            r = requests.get(url, timeout=12)
            if r.status_code != 200 or "managers" not in r.text:
                continue
            out = {}
            for m in re.finditer(r'"(\d+)"\s*:\s*\{[^}]*?\bname:\s*"([^"]+)"', r.text):
                out[m.group(1)] = m.group(2)
            if out:
                return out
        except Exception:  # noqa: BLE001
            continue
    return {}


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


def predict_keepers(league_id: str, value, current_season: int,
                    have_owners: set, registry=None, rounds: int = 0) -> Dict[str, List[dict]]:
    """Predict keepers for owners who haven't entered any on the keeper dashboard.

    Uses last season's draft: each owner's drafted players become keeper candidates,
    and we keep their top `max_keepers` by VORP. Cost round: a player drafted *as a
    rookie* (his rookie season was the draft season) is a ROOKIE keeper, kept at the
    last round (the cheap, career-long way keeper leagues hold rookies) — otherwise
    he costs the round he was drafted. Returns {owner_id: [{player_id, cost_round,
    is_rookie_keeper, predicted}]} for owners NOT in `have_owners`.
    """
    from collections import defaultdict
    from . import sleeper_client as sleeper
    try:
        league = sleeper.get_league(str(league_id))
        max_keepers = int((league.get("settings") or {}).get("max_keepers") or 0)
    except Exception:  # noqa: BLE001
        max_keepers = 0
    if max_keepers <= 0:
        return {}

    def _years_exp(pid: str):
        if registry is None:
            return None
        try:
            return getattr(registry.meta(pid), "years_exp", None)
        except Exception:  # noqa: BLE001
            return None

    out: Dict[str, List[dict]] = {}
    for entry in sleeper.league_chain(str(league_id)):
        draft_season = int(entry.get("season") or 0)
        if draft_season >= int(current_season):
            continue                                   # find the most recent PRIOR draft
        picks = sleeper.get_draft_picks(entry.get("draft_id")) or []
        by_owner: Dict[str, list] = defaultdict(list)
        for pk in picks:
            owner = str(pk.get("picked_by") or "")
            pid = str(pk.get("player_id") or "")
            rnd = int(pk.get("round") or 0)
            if owner and pid and rnd:
                by_owner[owner].append((pid, rnd))
        if not by_owner:
            continue
        # A player is a rookie keeper if his rookie season was the draft season —
        # i.e. current years_exp == seasons since that draft (he entered that year).
        rookie_gap = int(current_season) - draft_season
        for owner, plist in by_owner.items():
            if str(owner) in have_owners:
                continue                               # they already set keepers
            ranked = sorted(plist, key=lambda x: -(value.vorp_of(x[0]) if value else 0.0))
            kept = []
            for pid, rnd in ranked[:max_keepers]:
                ye = _years_exp(pid)
                is_rookie = ye is not None and ye == rookie_gap
                cost = rounds if (is_rookie and rounds) else rnd
                kept.append({"player_id": pid, "cost_round": cost,
                             "is_rookie_keeper": is_rookie, "predicted": True})
            if kept:
                out[owner] = kept
        return out                                     # only the most recent prior season
    return out


def build_placements(keepers: Dict[str, List[dict]], owner_slot: Dict[str, int],
                     n_teams: int, rounds: int, pick_owner_slot=None) -> dict:
    """Map each keeper onto the draft board.

    Returns {
      "by_overall": {overall_pick -> pid},   # where each keeper sits on the board
      "kept_pids":  set(pid),                 # all kept players (remove from pool)
      "by_owner":   {owner_id -> [pid,...]},
    }
    A keeper occupies one of its owner's *actual* picks nearest `cost_round`. When
    `pick_owner_slot(overall)` is given it respects traded picks (an owner may hold
    two picks in a round, or none); otherwise it falls back to a plain snake.
    """
    by_overall: Dict[int, str] = {}
    kept_pids = set()
    by_owner: Dict[str, list] = {}
    total = n_teams * rounds

    def snake_overall(slot: int, rnd: int) -> int:
        col = slot if rnd % 2 == 1 else n_teams - 1 - slot
        return (rnd - 1) * n_teams + col + 1

    # owner slot -> {round -> [overall picks they actually own]}
    owned: Dict[int, Dict[int, list]] = {}
    if pick_owner_slot:
        for ov in range(1, total + 1):
            s = pick_owner_slot(ov)
            rnd = (ov - 1) // n_teams + 1
            owned.setdefault(s, {}).setdefault(rnd, []).append(ov)

    for owner_id, klist in keepers.items():
        slot = owner_slot.get(str(owner_id))
        if slot is None:
            continue
        slot_owned = owned.get(slot, {})
        used_ov = set()
        # place lowest-round (most expensive) keepers first for stable assignment
        for k in sorted(klist, key=lambda x: x.get("cost_round") or rounds):
            pid = str(k.get("player_id") or "")
            if not pid:
                continue
            want = max(1, min(rounds, int(k.get("cost_round") or rounds)))
            ov = None
            # search outward from the cost round for one of this owner's free picks
            for d in range(rounds):
                for cand in ((want + d), (want - d)):
                    if not (1 <= cand <= rounds):
                        continue
                    if pick_owner_slot:
                        free = [o for o in slot_owned.get(cand, []) if o not in used_ov]
                        if free:
                            ov = free[0]
                            break
                    else:
                        cov = snake_overall(slot, cand)
                        if cov not in used_ov:
                            ov = cov
                            break
                if ov is not None:
                    break
            if ov is None:
                ov = snake_overall(slot, want)      # last-resort fallback
            used_ov.add(ov)
            by_overall[ov] = pid
            kept_pids.add(pid)
            by_owner.setdefault(str(owner_id), []).append(pid)
    return {"by_overall": by_overall, "kept_pids": kept_pids, "by_owner": by_owner}
