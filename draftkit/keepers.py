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


# Fallback house rules for a league whose dashboard config.yaml is unreachable or
# doesn't define a `rules:` block — max_keep_years=99 makes the year-cap a no-op
# rather than guessing a number that isn't this league's actual rule.
_DEFAULT_KEEPER_RULES = {
    "max_regular_keepers": None, "max_rookie_keepers": None,
    "max_keep_years": 99, "year2_bump_rounds": 0, "rookie_fixed_round": None,
    # Whether a keeper must land on a pick the team still owns. Kreeper enforces
    # it implicitly; Babies and Boomer sets it False ("a keeper just costs its
    # computed round regardless of which picks were traded").
    "enforce_owned_picks": True,
}
_INT_RULES = ("max_regular_keepers", "max_rookie_keepers", "max_keep_years",
              "year2_bump_rounds", "rookie_fixed_round")
_BOOL_RULES = ("enforce_owned_picks",)


def load_keeper_rules(league_id: str) -> dict:
    """House keeper rules from the dashboard's config.yaml `league:`/`rules:`
    blocks — Sleeper's own settings only expose a flat `max_keepers` total, not
    the regular/rookie split, the year cap, or the cost-escalation-per-year rule."""
    import re
    cfg = KEEPER_REPOS.get(str(league_id))
    if not cfg:
        return dict(_DEFAULT_KEEPER_RULES)
    for branch in ("main", "master"):
        url = _CONFIG_RAW.format(repo=cfg["repo"], branch=branch)
        try:
            r = requests.get(url, timeout=12)
            if r.status_code != 200:
                continue
            text = r.text
            out = dict(_DEFAULT_KEEPER_RULES)
            found = False
            for key in _INT_RULES:
                m = re.search(rf'^\s*{key}\s*:\s*(\d+)', text, re.M)
                if m:
                    out[key] = int(m.group(1))
                    found = True
            for key in _BOOL_RULES:
                m = re.search(rf'^\s*{key}\s*:\s*(true|false)\b', text, re.M | re.I)
                if m:
                    out[key] = m.group(1).lower() == "true"
                    found = True
            if found:
                return out
        except Exception:  # noqa: BLE001
            continue
    return dict(_DEFAULT_KEEPER_RULES)


def _kept_pid_sets(league_id: str, seasons: List[int]) -> Dict[int, dict]:
    """{season: {"all": {pid kept that season}, "rookie": {pid kept in a ROOKIE
    slot}}} from the dashboard's own historical keepers_<season>.json files — the
    authoritative record of who was actually kept, and how. (Sleeper's own per-pick
    `is_keeper` flag turns out to be set inconsistently in older drafts in
    practice, so we go straight to the dashboard's history instead of trying to
    infer it from the draft record.)

    The rookie set matters because rookie status is CARRIED, not re-derived: this
    league keeps rookies "for their whole career", so a player kept in a rookie
    slot since 2022 is still a rookie keeper today even though his years_exp is
    now 5. Inferring it from years_exp alone only ever catches last year's rookie
    class — of the 14 real rookie keepers in Kreeper 2026, that caught 4."""
    cfg = KEEPER_REPOS.get(str(league_id))
    out: Dict[int, dict] = {}
    if not cfg:
        return out
    for yr in seasons:
        url = _RAW.format(repo=cfg["repo"], branch=cfg["branch"], season=yr)
        try:
            r = requests.get(url, timeout=12)
            if r.status_code == 200 and r.text.strip():
                data = json.loads(r.text)
                allp, rook = set(), set()
                for ks in data.values():
                    for k in ks:
                        pid = k.get("player_id")
                        if not pid:
                            continue
                        allp.add(str(pid))
                        if k.get("is_rookie_keeper"):
                            rook.add(str(pid))
                out[yr] = {"all": allp, "rookie": rook}
        except Exception:  # noqa: BLE001
            continue
    return out


def _owned_rounds(league_id: str, rounds: int) -> Dict[str, Dict[int, int]]:
    """{owner_id: {round: how many picks currently owned}} for THIS season's draft,
    accounting for trades — so a predicted keeper never lands on a round the owner
    doesn't actually hold a pick in (you can't pay a keeper's draft-pick cost with
    a pick you traded away)."""
    from . import sleeper_client as sleeper
    try:
        league = sleeper.get_league(str(league_id))
        draft_id = league.get("draft_id")
        rosters = sleeper.get_rosters(str(league_id)) or []
        trades = sleeper.get_traded_picks(draft_id) if draft_id else []
    except Exception:  # noqa: BLE001
        return {}
    rid_to_uid = {r.get("roster_id"): str(r.get("owner_id"))
                  for r in rosters if r.get("owner_id")}
    owned: Dict[str, Dict[int, int]] = {
        uid: {r: 1 for r in range(1, rounds + 1)} for uid in set(rid_to_uid.values())
    }
    for t in (trades or []):
        rnd = t.get("round")
        orig = rid_to_uid.get(t.get("roster_id"))
        new = rid_to_uid.get(t.get("owner_id"))
        if not (rnd and orig and new) or orig == new:
            continue
        owned.setdefault(orig, {})[rnd] = owned.get(orig, {}).get(rnd, 0) - 1
        owned.setdefault(new, {})[rnd] = owned.get(new, {}).get(rnd, 0) + 1
    return owned


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
    """{owner_id: [keeper dicts]} for the league/season, or {} if none/unknown.
    Filtered to players each manager still rosters, so a player traded after a
    keeper was submitted can't be kept by two teams."""
    cfg = KEEPER_REPOS.get(str(league_id))
    if not cfg:
        return {}
    # Fall back to last season ONLY when this season's file genuinely isn't
    # published yet (404) — that's a fair preview. On a transient error we must
    # NOT silently substitute a different season: last year's file has
    # cost_round: null on every entry, which lands all ~37 keepers in the final
    # round. Returning {} instead surfaces as "0 keepers" in the health strip,
    # and visibly-missing beats confidently-wrong.
    for yr in (season, season - 1):
        url = _RAW.format(repo=cfg["repo"], branch=cfg["branch"], season=yr)
        try:
            r = requests.get(url, timeout=12)
        except Exception:  # noqa: BLE001 — network blip: don't swap seasons
            return {}
        if r.status_code == 404:
            continue                       # not published yet — try the preview
        if r.status_code == 200 and r.text.strip():
            try:
                data = json.loads(r.text)
            except Exception:  # noqa: BLE001 — malformed/truncated JSON
                return {}
            if any(data.values()):
                return _filter_to_rosters(data, league_id)
        return {}                          # any other status: don't guess
    return {}


def _filter_to_rosters(data: Dict[str, List[dict]], league_id: str) -> Dict[str, List[dict]]:
    """Drop keepers a manager no longer rosters (e.g. traded away after submitting),
    using the live Sleeper rosters as the source of truth — otherwise a traded
    player shows up kept by both his old and new team. Keepers without a player_id,
    or if rosters can't be fetched, pass through unchanged."""
    from . import sleeper_client as sleeper
    try:
        rosters = sleeper.get_rosters(str(league_id)) or []
    except Exception:  # noqa: BLE001
        return data
    owned = {str(r.get("owner_id")): {str(p) for p in (r.get("players") or [])}
             for r in rosters if r.get("owner_id")}
    if not owned:
        return data
    out: Dict[str, List[dict]] = {}
    for oid, picks in data.items():
        roster = owned.get(str(oid), set())
        kept = [s for s in picks
                if not s.get("player_id") or str(s["player_id"]) in roster]
        if kept:
            out[oid] = kept
    return out


def predict_keepers(league_id: str, value, current_season: int,
                    have_owners: set, registry=None, rounds: int = 0) -> Dict[str, List[dict]]:
    """Predict keepers for owners who haven't entered any on the keeper dashboard,
    honoring this league's actual house rules (config.yaml `rules:`) instead of a
    flat "top N by value":

    - Candidates = each owner's CURRENT roster, costed by the round that player was
      drafted in the most recent prior season — his league-wide draft cost, NOT
      tied to who originally picked him (a player traded in since that draft is a
      candidate for his new owner, not his old one) — EXCEPT the rookie-slot
      privilege itself, which does NOT transfer by trade (see below).
    - Regular and rookie keepers are separate buckets with separate caps
      (``max_regular_keepers`` / ``max_rookie_keepers``) — a rookie candidate never
      displaces a regular one or vice versa. A rookie only qualifies for the cheap
      ROOKIE bucket if the current owner is the one who ORIGINALLY drafted him that
      rookie season; a team that traded for him since is still a valid keeper
      candidate, just as a REGULAR keeper at his drafted round — otherwise you
      could rent a cheap rookie-keeper slot via trade instead of drafting the
      rookie yourself.
    - A REGULAR candidate already kept ``max_keep_years`` seasons in a row (per the
      dashboard's own keeper history, any owner — a trade doesn't reset the clock)
      has used up his eligibility and is dropped; rookies are exempt (kept "for
      their whole career" per this league's rules).
    - A candidate whose cost round the owner doesn't currently hold a pick in
      (traded away since) is dropped — you can't pay a keeper's draft-pick cost
      with a pick you no longer have.
    - Rookie cost follows ``rookie_keeper_cost: last_rounds`` — the 1st rookie slot
      costs the LAST round, the 2nd costs the round before that, and so on.

    Returns {owner_id: [{player_id, cost_round, is_rookie_keeper, predicted}]} for
    owners NOT in `have_owners`.
    """
    from . import sleeper_client as sleeper
    try:
        league = sleeper.get_league(str(league_id))
        settings_max = int((league.get("settings") or {}).get("max_keepers") or 0)
    except Exception:  # noqa: BLE001
        settings_max = 0
    if settings_max <= 0:
        return {}

    rules = load_keeper_rules(league_id)
    max_regular = rules["max_regular_keepers"] or settings_max
    max_rookie = rules["max_rookie_keepers"] or 0

    try:
        rosters = sleeper.get_rosters(str(league_id)) or []
    except Exception:  # noqa: BLE001
        rosters = []
    owned_players = {str(r.get("owner_id")): {str(p) for p in (r.get("players") or [])}
                     for r in rosters if r.get("owner_id")}
    if not owned_players:
        return {}
    owned_rounds = _owned_rounds(league_id, rounds) if rounds else {}

    def _years_exp(pid: str):
        if registry is None:
            return None
        try:
            return getattr(registry.meta(pid), "years_exp", None)
        except Exception:  # noqa: BLE001
            return None

    for entry in sleeper.league_chain(str(league_id)):
        draft_season = int(entry.get("season") or 0)
        if draft_season >= int(current_season):
            continue                                   # find the most recent PRIOR draft
        picks = sleeper.get_draft_picks(entry.get("draft_id")) or []
        pid_round: Dict[str, int] = {}
        pid_drafter: Dict[str, str] = {}
        for pk in picks:
            pid = str(pk.get("player_id") or "")
            rnd = int(pk.get("round") or 0)
            if pid and rnd:
                pid_round[pid] = rnd
                pid_drafter[pid] = str(pk.get("picked_by") or "")
        if not pid_round:
            continue
        # A player is a rookie keeper if his rookie season was the draft season —
        # i.e. current years_exp == seasons since that draft (he entered that year).
        rookie_gap = int(current_season) - draft_season
        # Consecutive-kept-year streak per candidate, from the dashboard's own
        # history (only fetched for leagues that actually have a dashboard).
        streak_seasons = (list(range(int(current_season) - 1,
                                     int(current_season) - 1 - rules["max_keep_years"], -1))
                          if league_has_keepers(league_id) else [])
        kept_sets = _kept_pid_sets(league_id, streak_seasons) if streak_seasons else {}
        # Anyone ever kept in a ROOKIE slot keeps that status for his whole career.
        ever_rookie = set()
        for _s in kept_sets.values():
            ever_rookie |= _s.get("rookie", set())

        def _kept_streak(pid: str) -> int:
            n = 0
            for yr in streak_seasons:
                if pid in kept_sets.get(yr, {}).get("all", set()):
                    n += 1
                else:
                    break
            return n

        out: Dict[str, List[dict]] = {}
        for owner, roster in owned_players.items():
            if str(owner) in have_owners:
                continue                               # they already set keepers
            plist = [(pid, pid_round[pid]) for pid in roster if pid in pid_round]
            ranked = sorted(plist, key=lambda x: -(value.vorp_of(x[0]) if value else 0.0))
            regular, rookies = [], []
            for pid, rnd in ranked:
                ye = _years_exp(pid)
                # A rookie keeper slot only stays with whoever ORIGINALLY drafted
                # him that rookie season — a team that traded for him since keeps
                # him (if at all) as a regular keeper at his drafted round, not a
                # cheap rookie slot (otherwise you could rent a cheap rookie-keeper
                # spot via trade instead of drafting the rookie yourself).
                # Rookie status is CARRIED FORWARD from the dashboard's history
                # (these leagues keep rookies for their whole career), and only
                # falls back to the years_exp heuristic for someone whose rookie
                # year IS the prior draft — i.e. this year's first-time rookie
                # keepers, who have no history to carry yet.
                is_rookie = (pid_drafter.get(pid) == str(owner)
                            and (pid in ever_rookie
                                 or (ye is not None and ye == rookie_gap)))
                (rookies if is_rookie else regular).append((pid, rnd))

            oround = owned_rounds.get(str(owner), {})
            _enforce = bool(rules.get("enforce_owned_picks", True))

            def _has_pick(rnd: int) -> bool:
                # Leagues that set enforce_owned_picks: false charge the computed
                # round regardless of which picks were traded, so a traded-away
                # round must not disqualify the keeper there.
                if not _enforce:
                    return True
                return not oround or oround.get(rnd, 0) > 0

            bump = int(rules.get("year2_bump_rounds") or 0)
            kept, n = [], 0
            for pid, rnd in regular:
                if n >= max_regular:
                    break
                streak = _kept_streak(pid)
                if streak >= rules["max_keep_years"]:
                    continue                           # used up his keeper years
                # Each additional keeper year costs `year2_bump_rounds` earlier.
                # `rnd` is the round he occupied in the PRIOR draft, which already
                # includes every bump applied up to now, so this is one
                # subtraction rather than bump x streak. Verified against the real
                # submitted board: JSN 10->7, Breece Hall 13->10, Zay Flowers
                # 13->10, Bucky Irving 12->9, and first-time keepers unchanged.
                cost = max(1, rnd - bump) if streak >= 1 else rnd
                if not _has_pick(cost):
                    continue                           # owner traded that pick away
                kept.append({"player_id": pid, "cost_round": cost,
                            "is_rookie_keeper": False, "predicted": True})
                n += 1

            slot_round, n = rounds, 0
            for pid, rnd in rookies:
                if n >= max_rookie:
                    break
                cost = slot_round if rounds else rnd
                if not _has_pick(cost):
                    continue
                kept.append({"player_id": pid, "cost_round": cost,
                            "is_rookie_keeper": True, "predicted": True})
                n += 1
                slot_round -= 1

            if kept:
                out[owner] = kept
        return out                                     # only the most recent prior season
    return {}


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
    two picks in a round, or none) — and when they hold more than one in that
    round, the keeper takes the LAST of them, not the first, so the owner's
    earliest pick in the round stays free for the live draft. Otherwise it falls
    back to a plain snake.
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
            try:
                want = int(k.get("cost_round") or rounds)
            except (TypeError, ValueError):
                # externally-authored JSON: a stray "Round 7" must not take the
                # whole app down with a ValueError inside build_context
                want = rounds
            want = max(1, min(rounds, want))
            ov = None
            # search outward from the cost round for one of this owner's free picks
            for d in range(rounds):
                for cand in ((want + d), (want - d)):
                    if not (1 <= cand <= rounds):
                        continue
                    if pick_owner_slot:
                        free = [o for o in slot_owned.get(cand, []) if o not in used_ov]
                        if free:
                            # when this owner holds MULTIPLE picks in the round
                            # (via trade), the keeper takes the LAST one — the
                            # owner keeps their earliest pick free for the live
                            # draft instead of losing it to the keeper.
                            ov = free[-1]
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
