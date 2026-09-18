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
    IS._fa_gain_cached(lk, week, slow, ctx, g, taken)           # the optimiser pass
    IS._waiver_board_cached(lk, week, slow, ctx, g, taken)
    d = mark()
    # FLEX is what Rankings opens on; ALL is the second click most days.
    for pos in ("FLEX", "ALL"):
        IS._rk_rows_cached(lk, week, slow, pos, reg, g, pn, owner_of, IS._PANEL_VER)
    e = mark()
    return (f"ctx {a}s · gather {b}s · panels {c}s · waivers {d}s · ranks {e}s "
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

    Off by default on Streamlit Cloud, where four leagues' worth of background
    work on a shared 1GB container costs more than the clicks it saves; the Mac
    app sets DRAFTROOM_WARM=1 and gets the whole board built before he looks.
    """
    global _started
    import os
    if enabled is None:
        enabled = os.environ.get("DRAFTROOM_WARM", "") not in ("", "0")
    if not enabled:
        return
    with _lock:
        if _started:
            return
        _fns.update(fns or {})
        if not all(k in _fns for k in ("sel", "ctx", "phase")):
            return
        _started = True
        threading.Thread(target=_loop, args=([dict(p) for p in presets],),
                         daemon=True, name="draftroom-warm").start()
