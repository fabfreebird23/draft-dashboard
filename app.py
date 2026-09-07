"""Bloody Sunday — one home for four fantasy leagues, both halves of the year.

Import any Sleeper or ESPN league, pull your UDK rankings, and run a mock draft or
a live draft assistant with a FantasyPros-style war room (tiered best-available
board, my-team lineup, snake draft grid, on-the-clock header). Both platforms
render from one normalized Pick shape.
"""
from __future__ import annotations

import dataclasses
import streamlit as st

from draftkit import positional as _PZ
from draftkit import seating as _SEAT

from draftkit import config, players, theme
from draftkit.adp import consensus
from draftkit.names import normalize_name
from draftkit.providers import get_provider, EspnAuthError
from draftkit import draft_history, keepers as keepers_mod, rankings as rankings_mod
from draftkit.ui import (assistant_ui, home_ui, in_season_ui, mock_ui,
                         prep_ui, rankings_ui, report_card_ui)
from draftkit.ui.components import board_pos_rank, health_html

st.set_page_config(page_title="Bloody Sunday", page_icon="🍒", layout="wide")
# Dark is the DEFAULT now, not the alternate. The badge set the identity came
# from contains the near-black, so the war room is the native look and light is
# the escape hatch — hence the default flipping to True.
theme.inject(st, dark=st.session_state.get("dark_mode", True))


# ----------------------------------------------------------------- cached data
@st.cache_resource(show_spinner="Loading player index…")
def get_registry(season: int):
    return players.build_registry(season)


# Rebuild the consensus board when it's older than this. ADP moves all summer
# (camp news, injuries, holdouts) and it drives survival %, value/reach chips,
# tier bands and the AI opponents' draft order — a board built in June is not
# the board your league is drafting off in late July.
ADP_MAX_AGE_HOURS = 12


@st.cache_data(ttl=3600, show_spinner="Building consensus ADP…")
def get_adp(season: int):
    df = consensus.load(season)
    age = consensus.age_hours(season)
    stale = age is None or age > ADP_MAX_AGE_HOURS
    if df is None or df.empty or stale:
        try:
            built = consensus.build(season)
            if built is not None and not built.empty:
                df = built
        except Exception:  # noqa: BLE001 - ADP is best-effort; keep what we had.
            pass           # a stale board still beats no board — never downgrade.
    return df, consensus.adp_lookup(season)


# Streamlit caches whatever these return — INCLUDING an empty failure result —
# for the whole TTL. One transient raw.githubusercontent blip therefore blanks all
# 37 keepers (they re-enter your best-available board) or reseats the entire draft
# order to Sleeper's roster order, and it stays wrong for 15 minutes.
#
# Every one of these describes something that CANNOT change during a draft — the
# keeper deadline has passed and the seating is fixed — so the last value we
# successfully fetched is strictly better than an empty one. Keep it and hand it
# back on failure.
_LAST_GOOD: dict = {}


def _sticky(key: str, value):
    """Return `value` when the fetch produced something, else the last good value.
    Prevents a momentary network failure from being cached as fact."""
    if value:
        _LAST_GOOD[key] = value
        return value
    return _LAST_GOOD.get(key, value)


@st.cache_data(ttl=900, show_spinner=False)
def get_keepers(platform: str, league_id: str, season: int):
    if platform != "sleeper":
        return {}
    return _sticky(f"keepers:{league_id}:{season}",
                   keepers_mod.load_keepers(league_id, season))


@st.cache_data(ttl=900, show_spinner=False)
def get_draft_order_override(platform: str, league_id: str):
    if platform != "sleeper":
        return []
    return _sticky(f"order:{league_id}", keepers_mod.load_draft_order(league_id))


@st.cache_data(ttl=900, show_spinner=False)
def get_manager_names(platform: str, league_id: str):
    if platform != "sleeper":
        return {}
    return _sticky(f"names:{league_id}", keepers_mod.load_manager_names(league_id))


@st.cache_data(ttl=86400, show_spinner=False)
def get_tendencies(platform: str, league_id: str):
    if platform != "sleeper":
        return {}
    try:
        return draft_history.owner_tendencies(league_id)
    except Exception:  # noqa: BLE001
        return {}


@st.cache_data(ttl=86400, show_spinner="Scouting opponents from draft history…")
def get_profiles(platform: str, league_id: str):
    if platform != "sleeper":
        return {}
    try:
        return draft_history.owner_profiles(league_id)
    except Exception:  # noqa: BLE001
        return {}


@st.cache_data(ttl=86400, show_spinner="Learning rookie draft tendencies…")
def get_rookie_curve(platform: str, league_id: str, season: int, _registry):
    """This league's empirical rookie slot curve — drives the league-specific
    rookie boost. Sleeper-only (needs draft history); empty curve = no boost."""
    if platform != "sleeper":
        return {}
    try:
        return draft_history.rookie_curve(league_id, _registry, season)
    except Exception:  # noqa: BLE001
        return {}


# AI-opponent ranking sources you can assign per team (Scouting tab). ESPN /
# FantasyPros / Underdog are per-source ADP columns in the consensus board;
# Sleeper ADP is a scraped data file; "Consensus" is the blended default.
MY_BOARD = "My UDK board"
AI_SOURCES = ["Consensus", "ESPN", "FantasyPros", "Underdog", "Sleeper", MY_BOARD]


@st.cache_data(ttl=86400, show_spinner=False)
def get_sleeper_adp(season: int):
    """{normalized_name: Sleeper ADP rank} from the committed Draft Sharks scrape."""
    import json
    p = config.ROOT / "data_seed" / f"sleeper_adp_{season}.json"
    try:
        return json.loads(p.read_text()).get("adp", {})
    except Exception:  # noqa: BLE001
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def get_source_pools(season: int, curve_key, _registry, _adp_df, _curve, _sleeper,
                     positions=("QB", "RB", "WR", "TE")):
    """{source: rookie-boosted draft pool ordered by that source's ADP} so an AI
    team set to 'ESPN' / 'Sleeper' drafts off that board. Cached by (season, curve)."""
    base = rankings_mod.adp_pool(_registry, _adp_df, positions=positions)
    pools = {}
    for src in AI_SOURCES:
        if src == MY_BOARD:
            continue          # built per-run from session_state; see main()
        if src == "Consensus":
            pool = base
        elif src == "Sleeper":
            pool = rankings_mod.apply_external_adp(base, _sleeper)
        else:
            pool = rankings_mod.adp_pool(_registry, _adp_df, source=src,
                                         positions=positions)
        pools[src] = rankings_mod.apply_rookie_curve(pool, _registry, _curve)
    return pools


@st.cache_data(ttl=300, show_spinner=False)
def get_league_phase(platform: str, league_id: str, season: int):
    """Where this league is in its year. Cached — it drives the nav default on
    every rerun and costs two API calls."""
    from draftkit import phase
    return phase.summary({"platform": platform, "league_id": league_id,
                          "season": season, "label": league_id})


@st.cache_data(ttl=600, show_spinner=False)
def get_board_age(league_key: str, _saved_at: float = 0.0):
    """Hours since the saved board was last written. Cached — the repo-backend path
    costs a GitHub API call and build_context runs on every rerun.

    `_saved_at` is unused inside and is the whole point: it puts the last save into
    the CACHE KEY. Without it, pulling a fresh board left the age reporting the old
    value for the full TTL — "loaded new rankings, board still says 7 days old"."""
    from draftkit import storage
    return storage.rankings_age_hours(league_key)


def board_age(league_key: str):
    from draftkit import storage
    return get_board_age(league_key, storage.save_epoch(league_key))


@st.cache_data(ttl=86400, show_spinner=False)
def get_byes(season: int):
    from draftkit import udk
    cookie = _secret("udk_cookie")
    return udk.ensure_byes(cookie, season)


@st.cache_data(ttl=1800, show_spinner=False)
def get_buzz():
    """League-wide add/drop velocity → {sleeper_pid: {'add': n, 'drop': m}}. A free
    breaking-news proxy (injuries/role changes spike adds). Never fatal."""
    from draftkit import sleeper_client
    try:
        adds = sleeper_client.get_trending("add", 24, 200)
        drops = sleeper_client.get_trending("drop", 24, 200)
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for pid, n in adds.items():
        out.setdefault(pid, {})["add"] = n
    for pid, n in drops.items():
        out.setdefault(pid, {})["drop"] = n
    return out


@st.cache_data(ttl=21600, show_spinner="Loading projections…")
def get_espn_projections(league_id: str, season: int):
    """ESPN's own season projections, already in that league's scoring."""
    from draftkit import projections
    return projections.espn_projections(league_id, season,
                                        registry=get_registry(season))


@st.cache_data(ttl=86400, show_spinner="Loading projections…")
def get_projections(season: int, scoring: str, weights: dict | None = None):
    """`weights` is unhashable, so it rides as a sorted tuple in the cache key —
    passing the dict straight in would make Streamlit raise on an unhashable arg."""
    from draftkit import projections
    return projections.load_projections(season, scoring,
                                        weights=dict(weights) if weights else None)


@st.cache_data(ttl=21600, show_spinner="Loading Juice's Value sheet…")
def get_juice_value(season: int, scoring: str, _registry):
    from draftkit import juice
    return juice.load(_registry, scoring)


# NOTE: this module runs as __main__ under Streamlit and calls main() at import
# time, so never `from app import ...` inside draftkit/ — that re-imports this
# file under a second module name and re-executes main(), which blows up on
# duplicate widget keys. Shared cached helpers belong in draftkit/, not here.


@st.cache_data(ttl=86400, show_spinner=False)
def get_schedule(season: int):
    from draftkit import schedule
    return schedule.load_schedule(season)


@st.cache_data(ttl=86400 * 7, show_spinner="Computing strength of schedule…")
def get_dvp(prev_season: int, _registry, scoring: str):
    from draftkit import schedule
    return schedule.load_dvp(prev_season, _registry, scoring)


@st.cache_data(ttl=3600 * 12, show_spinner="Loading rankings…")
def get_ranks_source(source: str, season: int, scoring: str, _registry):
    """(rows, status). The status rides along so the Rankings tab can say when a
    source fell back to an old cache instead of rendering it as if it were live."""
    from draftkit import rank_sources
    return rank_sources.load_with_status(source, season, scoring, _registry)


def _secret(name: str) -> str:
    try:
        return st.secrets.get(name, "") or ""
    except Exception:  # noqa: BLE001
        return ""


# Your saved leagues — one-click import (edit this list to add/remove).
# Brandon's own team in each league. Hardcoded rather than picked from a dropdown:
# these four leagues are his, the answer never changes, and a selectbox that
# defaults to the first manager is a live hazard — In-season would optimise
# someone else's roster. `my_team` is a Sleeper owner_id or an ESPN teamId.
MY_SLEEPER_ID = "964703051971887104"          # same account in all three leagues

SAVED_LEAGUES = [
    {"label": "The Kreeper League", "platform": "sleeper",
     "league_id": "1310907162930733056", "season": 2026, "my_team": MY_SLEEPER_ID,
     "keeper": True},
    {"label": "Babies and Boomer", "platform": "sleeper",
     "league_id": "1312885282554535936", "season": 2026, "my_team": MY_SLEEPER_ID,
     "keeper": True},
    {"label": "7\u00bd Men", "platform": "sleeper",
     "league_id": "1388606375239643136", "season": 2026, "my_team": MY_SLEEPER_ID,
     "keeper": True},
    # Public league — readable with no espn_s2/SWID, so no credentials are stored.
    {"label": "Show us your TD's", "platform": "espn",
     "league_id": "798873", "season": 2026, "my_team": "12", "keeper": False},
]


def _positional_ctx(league_id) -> dict:
    """{fixed_roster, roster_slots, bench_slots} for a fixed-roster league."""
    from draftkit import positional as PZ
    if not PZ.is_fixed_roster(league_id):
        return {}
    return {"fixed_roster": True,
            "roster_slots": PZ.roster_slots(league_id),
            "bench_slots": 0}


def _taxi_ctx(league_id, owner_slot) -> dict:
    """{taxi_by_slot, taxi_slots} for a staged league, or empty for a normal one."""
    from draftkit import draft_stages as DS
    stages = DS.stages_for(league_id)
    if not stages or len(stages) < 2:
        return {}
    try:
        return {"taxi_by_slot": DS.taxi_by_slot(league_id, owner_slot, stages[0]),
                "taxi_slots": DS.taxi_slots(league_id)}
    except Exception:  # noqa: BLE001 — no taxi read must not cost him the board
        return {}


def _select_league(preset: dict) -> None:
    st.session_state.league = {
        "platform": preset["platform"], "league_id": preset["league_id"],
        "season": int(preset.get("season") or config.current_season()),
        "espn_s2": preset.get("espn_s2"), "swid": preset.get("swid"),
        "keeper": preset.get("keeper", True),
        "my_team": preset.get("my_team"),
    }
    st.rerun()


# ------------------------------------------------------------------ league pick
def league_picker():
    """Home. All four leagues are baked into SAVED_LEAGUES, so this is purely the
    dashboard — the ad-hoc import form is gone. Adding a league is a one-line edit
    to SAVED_LEAGUES, which is the honest cost given how rarely it happens."""
    home_ui.render(SAVED_LEAGUES, _select_league, board_age_fn=board_age)



def build_context(sel: dict) -> dict:
    registry = get_registry(sel["season"])
    provider = get_provider(sel["platform"], sel["league_id"], sel["season"], registry,
                            espn_s2=sel.get("espn_s2"), swid=sel.get("swid"),
                            mock_draft_id=sel.get("mock_draft_id"))
    meta = provider.get_league_meta()
    order = provider.get_draft_order()
    # Real manager names + draft-slot order from the league's keeper dashboard.
    mgr_names = get_manager_names(meta.platform, meta.league_id)
    scraped = get_draft_order_override(meta.platform, meta.league_id)
    from draftkit.providers import Team

    def disp(oid, fallback):
        return mgr_names.get(str(oid)) or fallback

    if scraped:
        name_by_owner = {str(t.team_id): t.name for t in order}
        order = [Team(slot=i, team_id=str(oid),
                      name=disp(oid, name_by_owner.get(str(oid), f"Team {oid}")))
                 for i, oid in enumerate(scraped)]
    elif mgr_names:
        order = [Team(slot=t.slot, team_id=t.team_id, name=disp(t.team_id, t.name)) for t in order]
    # SEATING. A league whose order is drawn at the table has no seating chart
    # until draft night, so the seats are numbered and he fills in names as he
    # learns them (the editor lives on the draft toolbar). Untouched leagues keep
    # the provider's order exactly.
    _lk = f"{meta.platform}_{meta.league_id}"
    team_names = [t.name for t in order]
    _seat_mode = st.session_state.get(_SEAT.mode_key(_lk)) or _SEAT.default_mode(meta.league_id)
    _gen = int(st.session_state.get(_SEAT.gen_key(_lk), 0))
    order = _SEAT.apply(order, _seat_mode,
                        [st.session_state.get(_SEAT.seat_key(_lk, i, _gen))
                         for i in range(len(order))])
    slot_names = [t.name for t in order] or [f"Team {i+1}" for i in range(meta.num_teams)]
    owner_by_slot = {t.slot: t.team_id for t in order}
    owner_slot = {t.team_id: t.slot for t in order}

    # Traded draft picks: a snake assumes each team picks once per round at a fixed
    # slot, but leagues trade picks (you can hold 2 in a round, 0 in another). Build
    # pick_owner_slot(overall) so turn order, my-picks, and AI ownership are correct.
    from draftkit.ui import components as _C
    traded_failed = False
    try:
        traded = provider.get_traded_picks()
    except Exception:  # noqa: BLE001 — never break the draft over a trade fetch
        traded, traded_failed = {}, True
    # STICKY, like every other fetch here. Falling back to {} does not degrade the
    # board gracefully — it renders a clean, confident, WRONG snake in which every
    # traded pick silently returns to its original owner. Kreeper has 33 traded
    # picks; losing them moves six of his own picks to other managers and hands him
    # five he does not own. A blank board announces a problem; a plausible one does
    # not, which is why this specific fetch must never be allowed to fail quietly.
    traded = _sticky(f"traded:{meta.platform}:{meta.league_id}", traded)
    traded_failed = traded_failed and not traded
    # Following a mock with a different seat count cannot work: picks are placed by
    # draft_slot onto LEAGUE slots, so a 12-seat mock in a 10-team league puts two
    # managers' picks on nobody. Report it rather than draw it.
    mock_mismatch = None
    try:
        mock_mismatch = provider.mock_teams_mismatch()
    except AttributeError:
        pass
    _n = len(slot_names)
    _snake = _C.snake(_n)

    def pick_owner_slot(overall: int) -> int:
        """0-based slot of the manager who actually owns this overall pick."""
        col = _snake(overall - 1)
        if not traded:
            return col
        rnd = (overall - 1) // _n + 1
        orig_team = owner_by_slot.get(col)
        owner_team = traded.get((rnd, str(orig_team)), str(orig_team))
        return owner_slot.get(owner_team, col)
    # ADP for the current season (the draftable pool + best-available ranks).
    adp_df, adp_lk = get_adp(config.current_season())
    adp_age = consensus.age_hours(config.current_season())

    def adp_rank(name: str, position: str = ""):
        key = f"{normalize_name(name)}|{position.lower()}" if position else None
        if key and key in adp_lk:
            return adp_lk[key]
        return adp_lk.get(normalize_name(name))

    # A league that forces kickers and defenses needs them in the AI's pool, or
    # the mock runs dry in the rounds where they are the only legal pick.
    _pool_pos = (("QB", "RB", "WR", "TE", "K", "DST")
                 if _PZ.is_fixed_roster(meta.league_id) else ("QB", "RB", "WR", "TE"))
    try:
        adp_pool = rankings_mod.adp_pool(registry, adp_df, positions=_pool_pos)
    except TypeError:
        # Streamlit Cloud reloads app.py but keeps imported submodules, so a deploy
        # can run NEW app.py against an OLD rankings.py that has no `positions`
        # argument — and the whole app died on the home screen with a TypeError.
        # Degrading to the previous pool (no K/D-ST) beats locking him out of a
        # dashboard he drafts on. A reboot is still the real fix.
        adp_pool = rankings_mod.adp_pool(registry, adp_df)
    # League-specific rookie boost: pull rookies up to where THIS league's history
    # actually drafts them (keeper leagues hammer rookies; redraft leagues don't, so
    # the curve is empty and ai_pool == adp_pool). The AI opponents + predictor draft
    # from ai_pool so mocks/survival/run-alerts reflect the league's rookie aggression.
    rookie_curve = get_rookie_curve(meta.platform, meta.league_id,
                                    config.current_season(), registry)
    ai_pool = rankings_mod.apply_rookie_curve(adp_pool, registry,
                                              rookie_curve.get("curve", {}))
    # Per-source AI pools (ESPN / FantasyPros / Underdog) for per-team scouting
    # assignments; "Consensus" maps to ai_pool. Curve key makes the cache curve-aware.
    curve = rookie_curve.get("curve", {})
    # Juice's Value sheet, loaded HERE rather than further down because it now also
    # supplies the live Sleeper draft-room rank behind the "Sleeper" AI board. The
    # committed data_seed scrape is a static file (June 15) and had drifted ~7 weeks;
    # the sheet is fetched fresh and still backfills from the scrape for the tail it
    # doesn't cover. See juice.sleeper_rank_map.
    juice_map = get_juice_value(config.current_season(), meta.scoring, registry)
    from draftkit import juice as juice_mod
    _sleeper_ranks = juice_mod.sleeper_rank_map(
        juice_map, get_sleeper_adp(config.current_season()))
    try:
        source_pools = get_source_pools(config.current_season(),
                                        tuple(sorted(curve.items())), registry, adp_df,
                                        curve, _sleeper_ranks, positions=_pool_pos)
    except TypeError:                      # same stale-submodule guard as above
        source_pools = get_source_pools(config.current_season(),
                                        tuple(sorted(curve.items())), registry, adp_df,
                                        curve, _sleeper_ranks)
    source_pools["Consensus"] = ai_pool
    # Positional rank (RB5, WR7…) + per-position tiers (talent cliffs by ADP gap).
    pos_rank, counts = {}, {}
    pos_tier, by_pos = {}, {}
    for p in adp_pool:
        pos = p["pos"]
        counts[pos] = counts.get(pos, 0) + 1
        pos_rank[str(p["pid"])] = f"{pos}{counts[pos]}"
        by_pos.setdefault(pos, []).append(p)
    for pos, lst in by_pos.items():
        tier, prev = 1, None
        for p in lst:                       # lst is already ADP-ordered
            adp = p["adp"]
            if prev is not None and (adp - prev) > max(2.0, 0.13 * adp):
                tier += 1
            prev = adp
            pos_tier[str(p["pid"])] = tier

    # A fixed-roster league's real length is its own — ESPN reports 17 rounds for
    # 798873, but the last one is twelve picks with playerId -1 and nobody in them.
    if _PZ.is_fixed_roster(meta.league_id):
        meta = dataclasses.replace(meta, draft_rounds=_PZ.rounds(meta.league_id))

    # The platform's own starting lineup, read BEFORE anything overrides it — the
    # sanity check below and the fixed-roster branch both need it, and it used to
    # be fetched fifty lines later, which meant `len(roster_slots)` in the bench
    # fallback referenced a name that did not exist yet. It never fired only
    # because every provider we have does report a bench.
    roster_slots = provider.get_roster_slots()
    # THE WEEKLY LINEUP, kept separate from the draft roster from here on. They are
    # the same list in most leagues; in a fixed-roster one they are nothing alike —
    # the roster is the 16 you must END UP HOLDING, the lineup is the 9 you START
    # (QB/RB/RB/WR/WR/TE/FLEX/K/DST). In-season was reading the roster bag and so
    # produced advice like "start Denver Broncos at WR", legal in neither.
    lineup_slots = list(roster_slots)
    try:
        bench_slots = provider.get_bench_count()
    except Exception:  # noqa: BLE001
        bench_slots = 0
    # Sanity: starters + bench should equal the draft length. When a provider can't
    # report the bench, derive it so the roster panel still shows every pick.
    if _PZ.is_fixed_roster(meta.league_id):
        roster_slots = _PZ.roster_slots(meta.league_id)
        bench_slots = 0          # every pick is a roster spot; there is no bench
    elif not bench_slots:
        bench_slots = max(0, meta.draft_rounds - len(roster_slots))

    # Keepers (from the league's companion keeper dashboard) + placements.
    keepers_raw = get_keepers(meta.platform, meta.league_id, config.current_season())
    placements = keepers_mod.build_placements(
        keepers_raw, owner_slot, meta.num_teams, meta.draft_rounds,
        pick_owner_slot=pick_owner_slot)
    # Deep draft-history scouting profiles per manager (archetype, reach, fav
    # teams, predictability) + the round→position model the AI/predictor consumes.
    # Keepers are excluded from profiles, so derive cleaner tendencies from them;
    # fall back to the legacy keeper-inclusive model only if profiles are empty.
    profiles = get_profiles(meta.platform, meta.league_id)
    tendencies = {o: p["pos_by_round"] for o, p in profiles.items()
                  if p.get("pos_by_round")}
    if not tendencies:
        tendencies = get_tendencies(meta.platform, meta.league_id)

    # Value engine: projected points → VORP vs league-specific replacement level.
    from draftkit import value as value_mod
    # Projections come from the league's OWN host: Sleeper for Sleeper, ESPN for
    # ESPN. For the ESPN league that isn't a preference — its 38 scoring items have
    # no per-yard entries, so our own weights can't reproduce it (Gibbs computed
    # ~394 vs ESPN's 939.6). ESPN's projection already has the real rules applied.
    _w = getattr(meta, "scoring_weights", None)
    if meta.platform == "espn":
        proj = get_espn_projections(str(meta.league_id), config.current_season())
    else:
        proj = get_projections(config.current_season(), meta.scoring,
                               tuple(sorted(_w.items())) if _w else None)
    # The rookie premium is a KEEPER-league idea — it prices a rookie's future.
    # "Show us your TD's" is a redraft: a rookie is worth this season and nothing
    # more, and leaving the premium on had Jeremiyah Love valued above his own
    # projection and above every back who out-projects him.
    value = value_mod.build_value(proj, registry, roster_slots, meta.num_teams,
                                  rookie_premium=bool(sel.get("keeper", True)))
    # Playoff strength of schedule (weeks 15-17) from real defense-vs-position.
    schedule = get_schedule(config.current_season())
    dvp = get_dvp(config.current_season() - 1, registry, meta.scoring)

    def get_ranks(source: str):
        """(rows, status) for an alternate ranking source (FantasyPros ECR / ESPN),
        cached. UDK is the league's saved board, handled by the caller."""
        return get_ranks_source(source, config.current_season(), meta.scoring, registry)

    league_key = f"{meta.platform}_{meta.league_id}"
    from draftkit import storage as storage_mod
    board_age_h = board_age(league_key)
    return {
        "registry": registry, "provider": provider, "meta": meta,
        "get_ranks": get_ranks,
        "slot_names": slot_names, "roster_slots": roster_slots,
        "lineup_slots": lineup_slots,
        # The real manager names, kept separate from the seat labels: the
        # seat editor needs something to offer even when the board is numbered.
        "team_names": team_names, "seat_mode": _seat_mode,
        "bench_slots": bench_slots,
        "owner_by_slot": owner_by_slot, "owner_slot": owner_slot,
        "adp_df": adp_df, "adp_rank": adp_rank, "adp_pool": adp_pool,
        "ai_pool": ai_pool, "rookie_curve": rookie_curve,
        "source_pools": source_pools, "ai_sources": AI_SOURCES,
        "pos_rank": pos_rank, "pos_tier": pos_tier, "byes": get_byes(config.current_season()),
        "buzz": get_buzz(),
        "keepers_raw": keepers_raw, "keepers": placements, "tendencies": tendencies,
        "profiles": profiles,
        "value": value, "proj": proj, "schedule": schedule, "dvp": dvp,
        "juice": juice_map,
        # ...and the same sheet again, but only where its premise holds. Juice's
        # skew measures SLEEPER'S draft room against FantasyPros: "he'll fall
        # further than he should" is a claim about people drafting off Sleeper's
        # default board. "Show us your TD's" is on ESPN and is drafted live in a
        # room, results typed in afterwards — nobody there is looking at Sleeper's
        # order, so the signal has no mechanism and must not move the score. The
        # tab and the player card still show it; it is market context, not a call.
        "juice_market": juice_map if meta.platform == "sleeper" else None,
        # Every external fetch here degrades silently by design (a network blip
        # must not take the app down mid-draft). That's only safe if the
        # degradation is VISIBLE — health_html renders this in the topbar.
        "health": {
            "adp_age_h": adp_age, "keepers": len(placements["kept_pids"]),
            "keeper_league": keepers_mod.league_has_keepers(meta.league_id),
            "order_scraped": bool(scraped), "juice": len(juice_map or {}),
            "board_age_h": board_age_h,
            "names_scraped": bool(mgr_names),
        },
        "pick_owner_slot": pick_owner_slot, "traded_picks": traded,
        "traded_failed": traded_failed, "mock_draft_id": sel.get("mock_draft_id"),
        "mock_mismatch": mock_mismatch,
        "league_key": league_key, "ranks_key": f"ranks_{league_key}",
        "my_team": sel.get("my_team"),
        "board_age_h": board_age_h,
        # Fixed-roster leagues must finish with an exact positional shape, so the
        # roster and round count come from that rather than from the platform's
        # weekly-lineup settings.
        **_positional_ctx(meta.league_id),
        # Taxi squad: in a staged league the EARLIER draft's picks are the taxi.
        # 7 1/2 Men runs a 2-round rookie draft and carries 2 taxi spots, so a
        # team's rookie picks are exactly its taxi squad. Kept out of the roster
        # entirely — they don't fill a starting spot and can't be drafted over.
        **_taxi_ctx(meta.league_id, owner_slot),
    }


def main():
    if "league" not in st.session_state:
        league_picker()
        return

    sel = st.session_state.league
    # Following a Sleeper mock instead of the league's own draft changes the team
    # count and round count, so it has to be part of CONTEXT, not a live toggle —
    # the board, the pick clock and every survival % are built from those numbers.
    _mock = st.session_state.get(f"mockid_{sel['platform']}_{sel['league_id']}")
    sel = dict(sel, mock_draft_id=_mock) if _mock else sel
    try:
        ctx = build_context(sel)
    except EspnAuthError as e:
        st.error(str(e))
        if st.button("← Back to import"):
            del st.session_state.league
            st.rerun()
        return
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't import that league ({type(e).__name__}: {e}).")
        if st.button("← Back to import"):
            del st.session_state.league
            st.rerun()
        return

    # Preload the saved/seeded UDK board so every tab has rankings (not just after
    # visiting My Rankings) — the seed ships a board even when the server-side pull
    # is blocked on the hosted app.
    from draftkit import storage
    if ctx["ranks_key"] not in st.session_state:
        st.session_state[ctx["ranks_key"]] = storage.load_rankings(ctx["league_key"])
    # A fixed-roster league forces kickers and defenses, and no cheat sheet ranks
    # them — so the board he pulled has four compulsory picks per team it cannot
    # help with, and the roster filter empties the panel in exactly those rounds.
    # Top it up from consensus ADP, behind everything he ranked himself.
    if ctx.get("fixed_roster"):
        _topped = rankings_mod.top_up_required(
            st.session_state.get(ctx["ranks_key"]) or [], ctx["roster_slots"],
            ctx.get("adp_pool") or [], ctx["registry"], len(ctx["slot_names"]))
        if len(_topped) != len(st.session_state.get(ctx["ranks_key"]) or []):
            st.session_state[ctx["ranks_key"]] = _topped

    # Per-manager AI draft boards, saved per league. Seeded HERE rather than beside
    # the selectboxes because the mock tab owns the widgets but the live tab's pick
    # predictor reads the same session keys — seeding centrally means both tabs get
    # your saved boards even if you never open the mock. Once per session per league.
    # Your own board as an AI source, so a manager known to draft off the same UDK
    # rankings actually does. Built here, not in get_source_pools, because the board
    # lives in session_state — it changes on a pull or a hand edit without touching
    # that cache's key, so a cached pool would silently go stale.
    _my_board = st.session_state.get(ctx["ranks_key"]) or []
    ctx["source_pools"][MY_BOARD] = rankings_mod.board_pool(
        _my_board, ctx["adp_pool"], ctx["registry"])

    _ai_seeded = f"aisrc_seeded_{ctx['league_key']}"
    if _ai_seeded not in st.session_state:
        for _slot, _src in (storage.load_ai_sources(ctx["league_key"]) or {}).items():
            _k = f"aisrc_{ctx['league_key']}_{_slot}"
            if _src in ctx["ai_sources"] and _k not in st.session_state:
                st.session_state[_k] = _src
        st.session_state[_ai_seeded] = True

    # Positional rank (RB18, WR7…) shown next to each player must follow the SAME
    # board the overall rank (#30) comes from — otherwise UDK's Top-200 order (which
    # drives #rank) and consensus-ADP order (which drove RB##) disagree and a
    # higher-ranked player shows a WORSE positional rank than a lower one. Recompute
    # pos_rank from the active board's own overall order so RB## always rises with #.
    _bpr = board_pos_rank(st.session_state.get(ctx["ranks_key"]) or [], ctx["registry"])
    if _bpr:
        ctx["pos_rank"] = _bpr

    meta = ctx["meta"]
    n_keep = len(ctx["keepers"]["kept_pids"])
    # ---- ONE topbar row: identity · pills (health folded in) · phase ----
    # Previously this spread over three rows — identity+buttons, then the phase
    # radio on its own line, then the tabs. The health dots also trailed as a
    # separate strip repeating things the pills already named. Folding the dots
    # into their own pill and lifting phase into this row gets it to two.
    from draftkit import phase as PH
    lg_sum = get_league_phase(meta.platform, str(meta.league_id), config.current_season())

    h = ctx.get("health") or {}

    def _age(v):
        if v is None:
            return "—"
        return f"{int(v)}h" if v < 48 else f"{int(v / 24)}d"

    # HEALTH AS A CLUSTER, not four pills. Four readouts cost ~420px to say
    # "everything is fine" ~95% of the time, and by crowding the row they pushed
    # the wordmark out entirely. Collapsed to dots it costs ~90px — and the
    # DEGRADED case gets louder rather than quieter, because the cluster stops
    # saying "healthy" and names the offender instead of hiding among pills you
    # have stopped reading. The full readout still lives in the overflow.
    # (long label for the overflow list, SHORT label for the cluster, value, ok, warn)
    checks = [("ADP", "ADP", _age(h.get("adp_age_h")),
               h.get("adp_age_h") is not None, (h.get("adp_age_h") or 0) >= 24),
              ("Your board", "board", _age(h.get("board_age_h")),
               h.get("board_age_h") is not None, (h.get("board_age_h") or 0) / 24 >= 7)]
    if h.get("keeper_league"):
        nk = h.get("keepers") or 0
        checks.append(("Keepers", "keepers", str(nk), nk > 0, False))
    jz = h.get("juice") or 0
    checks.append(("Juice sheet", "Juice", str(jz), jz > 0, False))

    def _tone(ok, warn):
        return "var(--red)" if not ok else ("var(--amber)" if warn else "var(--green)")

    # Missing outranks stale: "no board" is a harder failure than "board 9d".
    worst = (next((c for c in checks if not c[3]), None)
             or next((c for c in checks if c[4]), None))
    cl_label = ("healthy" if worst is None
                else (f"{worst[1]} {worst[2]}" if worst[3] else f"no {worst[1]}"))
    cl_tone = "" if worst is None else (" hc-warn" if worst[3] else " hc-bad")
    cluster = (f'<span class="tb-hc{cl_tone}" title="'
               + " · ".join(f"{lbl} {val}" for lbl, _s, val, _o, _w in checks) + '">'
               + "".join(f'<i style="background:{_tone(ok, warn)}"></i>'
                         for _l, _s, _v, ok, warn in checks)
               + f'<span>{cl_label}</span></span>')

    # Two pills, not four. The mock fit three plus the cluster at 1320px; the real
    # pane is narrower, and a fourth pushed the group left over the phase control.
    # Rounds is the least useful of the four and the scoring label is the most —
    # it's the one that differs per league and changes what the board means.
    pills = "".join(f'<span class="tb-pill">{p}</span>' for p in
                    (f"{meta.num_teams} teams", meta.scoring.upper()))

    dark_on = st.session_state.get("dark_mode", True)
    pkey = f"phase_{ctx['league_key']}"
    if pkey not in st.session_state:
        # Derived from THIS league's own draft, never a global setting — Kreeper
        # drafts Aug 13 and B&B Sep 7, so a shared toggle would be wrong for one of
        # them for three weeks. Still overridable.
        st.session_state[pkey] = ("In-season" if lg_sum.phase in (PH.IN, PH.DONE)
                                  else "Pre-season")

    with st.container(key="dr_topbar"):
        head = st.columns([3.35, 1.7, 2.15, 0.4])
        with head[0]:
            st.markdown(f'<div class="tb-row tb-id">{theme.cherry_svg(19)}'
                        f'<span class="bs-word">Bloody<em>Sunday</em></span>'
                        f'<span class="tb-sep"></span>'
                        f'<span class="tb-name">{meta.name}</span></div>',
                        unsafe_allow_html=True)
        with head[1], st.container(key="tb_phase"):
            # st.segmented_control, NOT a styled radio. Hiding a radio's glyph means
            # selecting on Streamlit's internal DOM, and that DOM is not stable: on
            # 1.50 the glyph is label>div, on the newer build Cloud resolves to it's a
            # nested div behind a visually-hidden a11y span. Two attempts to pin it
            # with CSS both worked locally and failed on Cloud. This widget IS a
            # segmented control, so there is nothing to hide.
            ph_sel = st.segmented_control(
                "phase", ["Pre-season", "In-season"], key=pkey,
                selection_mode="single", label_visibility="collapsed") or st.session_state[pkey]
        with head[2]:
            st.markdown(f'<div class="tb-row tb-pills">{pills}{cluster}</div>',
                        unsafe_allow_html=True)
        with head[3], st.container(key="tb_more"):
            with st.popover("⋯", use_container_width=True):
                def _toggle_dark():
                    st.session_state["dark_mode"] = not st.session_state.get("dark_mode", True)
                st.button("Light mode" if dark_on else "War room", key="dark_btn",
                          use_container_width=True, on_click=_toggle_dark,
                          help="Toggle the light theme.")
                if st.button("Home — all leagues", use_container_width=True, key="tb_home"):
                    del st.session_state.league
                    st.rerun()
                st.markdown(f'<div class="tb-bf">build {theme.fingerprint()}</div>',
                            unsafe_allow_html=True)
                st.markdown('<div class="tb-hh">Data health</div>'
                            + "".join(f'<div class="tb-hr">'
                                      f'<i class="tb-dot" style="background:{_tone(ok, warn)}"></i>'
                                      f'<span>{lbl}</span><b>{val}</b></div>'
                                      for lbl, _s, val, ok, warn in checks),
                            unsafe_allow_html=True)

    if ph_sel == "In-season":
        # DEFENSIVE against Streamlit Cloud's stale-module behaviour. Cloud reloads
        # app.py on a new commit but KEEPS already-imported submodules, so a fresh
        # app.py can meet an old in_season_ui — which is exactly how a deploy turned
        # into `AttributeError: module has no attribute 'TABS'` on a live app rather
        # than a quiet visual regression. app.py itself always reloads, so reading
        # cross-module constants through getattr means a stale submodule degrades to
        # the old single-tab behaviour instead of crashing the page.
        nav = getattr(in_season_ui, "TABS", ["This Week"])
        ikey = f"nav_in_{ctx['league_key']}"
        st.session_state.setdefault(ikey, nav[0])
        with st.container(key="navbar"):
            itab = st.segmented_control("nav", nav, key=ikey, selection_mode="single",
                                        label_visibility="collapsed") or nav[0]
        try:
            in_season_ui.render(ctx, summary=lg_sum, tab=itab)
        except TypeError:
            # Same cause: an older render() has no `tab` parameter.
            in_season_ui.render(ctx, summary=lg_sum)
        return

    # Persisted nav (st.tabs resets to the first tab on every rerun — drafting
    # triggers reruns, so we use a keyed radio styled as tabs instead).
    nav = ["Overview", "My Rankings", "Mock Draft", "Live Draft", "Report Card"]
    # A button inside a section can ask to jump to another one ("Open war room").
    # It cannot write to "nav_section" directly: that is the segmented control's
    # own widget key, and by the time any section renders the widget already
    # exists for this run, so Streamlit raises. The request is parked under a
    # plain key and applied HERE — before the widget is created — which is the
    # only point in the run where writing to it is legal.
    _goto = st.session_state.pop("nav_goto", None)
    if _goto in nav:
        st.session_state["nav_section"] = _goto
    st.session_state.setdefault("nav_section", nav[0])
    with st.container(key="navbar"):
        # Same reasoning as the phase control. `or` guards the deselect case:
        # segmented_control returns None when you click the active segment, and the
        # nav must never resolve to nothing mid-draft.
        section = st.segmented_control("nav", nav, key="nav_section",
                                       selection_mode="single",
                                       label_visibility="collapsed") or nav[0]
    if section == nav[0]:
        prep_ui.render(ctx, summary=lg_sum)
    elif section == nav[1]:
        rankings_ui.render(ctx)
    elif section == nav[3]:
        # The LIVE war room needs the stage too, and never got it — draft_stages was
        # only ever applied to the mock. Two consequences for a real draft:
        #   · the board was Sleeper's round count for the draft it is bound to. A
        #     supplemental caps at 10, so a 14-round veteran draft drew 10 rounds.
        #   · the 16 players taken in the completed rookie draft were still in the
        #     pool, so the board would have offered men who are already rostered
        #     while he was actually on the clock.
        from draftkit import draft_stages as _DS
        _stage = _DS.live_stage(meta.league_id)
        if _stage:
            _stage = dataclasses.replace(
                _stage, rounds=_DS.scheduled_rounds(meta.league_id, _stage))
            assistant_ui.render(_DS.apply(ctx, _stage, _DS.already_taken(meta.league_id)))
        else:
            assistant_ui.render(ctx)
    elif section == nav[2]:
        # Leagues that draft in stages (7 1/2 Men: 2-round rookie draft, then the
        # veteran draft) mock one stage at a time. The stage changes the eligible
        # pool AND the round count, so it's applied to ctx before the mock renders
        # — mocking the veteran draft against the full pool would practise the
        # wrong draft entirely.
        from draftkit import draft_stages as DS
        stages = DS.stages_for(meta.league_id)
        if stages:
            skey = f"stage_{ctx['league_key']}"
            names = [x.name for x in stages]
            sel = st.radio("Draft stage", names, horizontal=True, key=skey,
                           help="This league drafts in two stages. Run the rookie "
                                "draft first — its picks are removed from the "
                                "veteran pool.")
            stage = stages[names.index(sel)]
            # Whatever is already GONE is gone. Two different sources, because
            # they answer different halves of the question:
            #   · the real league — his rookie draft actually happened, and all
            #     sixteen of those men were still being offered in the veteran
            #     pool because this only ever looked at the mock
            #   · the rookie MOCK in this session — so the two stages still
            #     connect when he is practising both back to back
            real, mock_taken = set(), []
            if stage.key != stages[0].key:
                real = DS.already_taken(meta.league_id)
                prev = st.session_state.get(f"mock_{ctx['league_key']}_{stages[0].key}") or {}
                mock_taken = [pid for pid in (prev.get("made") or {}).values() if pid]
            taken = sorted(real | {str(p) for p in mock_taken})
            # The commissioner sets the round count, not this repo — 7 1/2 Men's
            # pending veteran draft is 10 rounds where draft_stages said 14.
            stage = dataclasses.replace(stage, rounds=DS.scheduled_rounds(meta.league_id, stage))
            bits = [stage.blurb]
            if real:
                bits.append(f"{len(real)} already rostered from the real rookie draft.")
            if mock_taken:
                bits.append(f"{len(mock_taken)} taken in your rookie mock.")
            st.caption(" · ".join(bits))
            mock_ui.render(DS.apply(ctx, stage, taken), state_suffix=stage.key)
        else:
            mock_ui.render(ctx)
    else:
        report_card_ui.render(ctx)


main()
