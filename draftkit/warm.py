"""Build the expensive caches before he clicks, not after.

Measured in the Mac app on week 2: the FIRST visit to a tab cost 5–8s
(Lineup 6.6s, Rankings 8.0s, Waivers 5.3s) and every visit after that cost
126–550ms. So the app is not slow — it is cold. Everything behind those first
clicks is `st.cache_data`, and a cache in Streamlit is process-wide, not
per-session: anything a background thread computes, the next click gets for
free.

So a daemon thread walks the four leagues at boot and builds exactly what the
tabs build — the same functions with the same keys, because a warm entry under
a different key is no warmer than none. It re-warms when the refresh bucket
rolls over, so the board stays warm all day rather than only at launch.

No `st.*` output happens here. Cached functions call `st.spinner`, which warns
about the missing ScriptRunContext from a thread and does nothing else; the
value is still computed and still stored.
"""
from __future__ import annotations

import json
import threading
import time
from typing import List, Optional

_lock = threading.Lock()
_started = False
_fns: dict = {}      # the SCRIPT module's cached functions — see kick()
_state = {"bucket": None, "at": 0.0, "ms": {}, "error": ""}

RECHECK_S = 30.0      # how often to look at the clock
MIN_GAP_S = 110.0     # never re-warm more often than this; one fast bucket
MODE = "full"         # set by kick(); "light" skips the heavy boards


def _on_cloud() -> bool:
    """Streamlit Community Cloud runs the repo out of /mount/src."""
    import os
    return os.path.isdir("/mount/src")


def status() -> dict:
    """What the warmer has done — read by the ⋯ menu and the logs."""
    return dict(_state)


def _warm_league(preset: dict, week: int) -> str:
    """One league, in the order the tabs need it. Returns a timing line.

    Two clocks, the same two the tabs read: the scores in `_gather` ride the
    fast one, everything derived from them rides the 15-minute one.
    """
    from .ui import in_season_ui as IS

    from . import config
    season = int(preset.get("season") or 0) or config.current_season()
    slow, fast = IS._slow_bucket(season, week), IS._refresh_bucket(season, week)
    t = [time.time()]

    def mark():
        t.append(time.time())
        return round(t[-1] - t[-2], 1)

    sel = _fns["sel"](preset)
    try:
        _fns["phase"](sel["platform"], str(sel["league_id"]), sel["season"])
    except Exception:  # noqa: BLE001
        pass
    ctx = _fns["ctx"](json.dumps(sel, sort_keys=True, default=str), slow)
    a = mark()
    g = IS._gather_cached(ctx["league_key"], week, fast, ctx)   # Command Center, Matchup
    b = mark()
    pn = IS._panels(ctx, g)                                    # Flock / Ballers / Vegas
    # The movers ticker reads a snapshot index per panel — five GitHub round
    # trips, memoised for a quarter hour once somebody pays for them.
    try:
        from . import panels as P
        P.movers(season, week, pn, since="yesterday", cross=True)
        P.baseline_day("flock", season, week, "yesterday")
    except Exception:  # noqa: BLE001
        pass
    c = mark()
    lk, reg = ctx["league_key"], ctx["registry"]
    owner_of = {}
    for oid, r in (g.get("rosters") or {}).items():
        for pid in r.get("players") or []:
            owner_of[str(pid)] = str(oid)
    taken = frozenset(owner_of)
    if MODE == "light":
        # Streamlit Cloud gives the app about a gigabyte. The free-agent
        # optimiser pass and the rankings rows are the two that hold real memory
        # per league, and they are also the two he does not open from a phone
        # first — so on Cloud the warm stops here and those stay on demand.
        d = e = 0.0
    else:
        IS._fa_gain_cached(lk, week, slow, ctx, g, taken)       # the optimiser pass
        IS._waiver_board_cached(lk, week, slow, ctx, g, taken)
        d = mark()
        # FLEX is what Rankings opens on; ALL is the second click most days.
        for pos in ("FLEX", "ALL"):
            IS._rk_rows_cached(lk, week, slow, pos, reg, g, pn, owner_of, IS._PANEL_VER)
        e = mark()
    return (f"[{MODE}] ctx {a}s · gather {b}s · panels {c}s · waivers {d}s · ranks {e}s "
            f"= {round(t[-1] - t[0], 1)}s")


def _pass(presets: List[dict]) -> None:
    from . import config
    from .ui import in_season_ui as IS

    week = IS.current_week()
    season = config.current_season()
    # Either clock rolling is a reason to go again: the fast one leaves the
    # scores stale, the slow one leaves the whole board cold.
    bucket = (IS._slow_bucket(season, week), IS._refresh_bucket(season, week))
    if _state["bucket"] == bucket or (time.time() - _state["at"]) < MIN_GAP_S:
        return
    t0 = time.time()
    # The header's league switcher draws every league's Home dot, so the four
    # pulses are paid on the FIRST league open, not on Home. Warm them first.
    try:
        from .ui import home_ui as H
        H._pulses(json.dumps(presets, sort_keys=True, default=str), week)
        print(f"[warm] pulses {round(time.time() - t0, 1)}s", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[warm] pulses FAILED {type(e).__name__}: {e}", flush=True)
    for p in presets:
        lbl = p.get("label") or p.get("league_id")
        try:
            _state["ms"][lbl] = _warm_league(p, week)
            print(f'[warm] {lbl}: {_state["ms"][lbl]}', flush=True)
        except Exception as e:  # noqa: BLE001  a cold tab is better than a dead thread
            _state["error"] = f"{lbl}: {type(e).__name__}: {e}"
            print(f"[warm] {lbl} FAILED {_state['error']}", flush=True)
    print(f"[warm] pass done in {round(time.time() - t0, 1)}s bucket={bucket}", flush=True)
    _state["bucket"], _state["at"] = bucket, time.time()


def _loop(presets: List[dict]) -> None:
    while True:
        try:
            _pass(presets)
        except Exception as e:  # noqa: BLE001
            _state["error"] = f"{type(e).__name__}: {e}"
        time.sleep(RECHECK_S)


def kick(presets: List[dict], fns: Optional[dict] = None,
         enabled: Optional[bool] = None) -> None:
    """Start the warmer once per process. Safe to call on every rerun.

    `fns` carries app.py's own cached functions — `sel_for`, `_ctx_cached`,
    `get_league_phase`. They have to be PASSED rather than imported: Streamlit
    executes app.py as the script module, so `import app` from here builds a
    second, separate copy of it, and a value cached against that copy is in a
    different namespace from the one the page reads. Warming the league context
    through an imported `app` looked like it worked and saved nothing — the
    open still cost five seconds.

    Three settings, read from DRAFTROOM_WARM: "0"/unset is off, "1"/"full"
    builds everything (the Mac), "light" builds only what Home, Live and
    Live · all need. Streamlit Cloud defaults to LIGHT rather than off, because
    the phone opens on exactly those screens and a cold one over cellular is
    the slowest thing in the app — but the heavy boards stay on demand there,
    where memory is a gigabyte and shared.
    """
    global _started, MODE
    import os
    want = (os.environ.get("DRAFTROOM_WARM") or "").lower()
    if not want and _on_cloud():
        want = "light"
    if enabled is None:
        enabled = want not in ("", "0", "off", "false")
    if not enabled:
        return
    MODE = "light" if want == "light" else "full"
    import sys
    with _lock:
        # Process-wide, not module-wide: app.py drops stale draftkit modules
        # after a deploy, and a re-imported warm.py would otherwise start a
        # second warming thread beside the first.
        if _started or getattr(sys, "_bs_warm_started", False):
            return
        sys._bs_warm_started = True
        _fns.update(fns or {})
        if not all(k in _fns for k in ("sel", "ctx", "phase")):
            return
        _started = True
        threading.Thread(target=_loop, args=([dict(p) for p in presets],),
                         daemon=True, name="draftroom-warm").start()


# --------------------------------------------------------- the league he is in
# Light mode (Streamlit Cloud) builds Home and the live screens for all four
# leagues and stops there: the free-agent optimiser and the rankings rows are the
# two that hold real memory, four leagues of them on a 1 GB container is a
# restart waiting to happen, and so Rankings opened cold — about thirty seconds
# on the phone. But he is only ever IN one league. So when a league opens, its
# heavy boards are built in the background for that league alone, and by the
# time he taps Rankings or Waivers they are already there.
_focus_lock = threading.Lock()
_focus = {"want": None, "running": False, "done": set()}


def focus(ctx: dict) -> None:
    """Build this league's heavy boards in the background. Safe on every rerun.

    Skipped in full mode, where the pass above already builds every league.
    One league at a time: if he switches while one is building, the newest
    request wins and the old one finishes what it started and stops.
    """
    if MODE == "full" and _started:
        return
    try:
        from .ui import in_season_ui as IS
        from . import config
        week = IS.current_week()
        key = (ctx["league_key"], week, IS._slow_bucket(config.current_season(), week))
    except Exception:  # noqa: BLE001
        return
    with _focus_lock:
        if key in _focus["done"]:
            return
        _focus["want"] = (key, ctx)
        if _focus["running"]:
            return
        _focus["running"] = True
    threading.Thread(target=_focus_loop, daemon=True, name="draftroom-focus").start()


def _focus_loop() -> None:
    while True:
        with _focus_lock:
            job = _focus["want"]
            _focus["want"] = None
            if job is None:
                _focus["running"] = False
                return
        key, ctx = job
        t0 = time.time()
        try:
            _heavy(ctx, key[1], key[2])
            with _focus_lock:
                _focus["done"].add(key)
                # remember a handful, not the season
                if len(_focus["done"]) > 12:
                    _focus["done"] = set(list(_focus["done"])[-8:])
            print(f"[warm] focus {key[0]} {round(time.time() - t0, 1)}s", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[warm] focus {key[0]} FAILED {type(e).__name__}: {e}", flush=True)


def _heavy(ctx: dict, week: int, slow: int) -> None:
    """The two boards light mode leaves cold: the optimiser pass and the rows."""
    from .ui import in_season_ui as IS
    from . import config
    fast = IS._refresh_bucket(config.current_season(), week)
    g = IS._gather_cached(ctx["league_key"], week, fast, ctx)
    pn = IS._panels(ctx, g)
    lk, reg = ctx["league_key"], ctx["registry"]
    owner_of = {}
    for oid, r in (g.get("rosters") or {}).items():
        for pid in r.get("players") or []:
            owner_of[str(pid)] = str(oid)
    taken = frozenset(owner_of)
    IS._fa_gain_cached(lk, week, slow, ctx, g, taken)
    IS._waiver_board_cached(lk, week, slow, ctx, g, taken)
    for pos in ("FLEX", "ALL"):
        IS._rk_rows_cached(lk, week, slow, pos, reg, g, pn, owner_of, IS._PANEL_VER)
