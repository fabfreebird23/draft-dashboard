"""One line of Sunday for the Mac app's menu bar.

    .venv/bin/python -m draftkit.macstatus --loop 90

Prints one JSON object per line: a short `title` for the NSStatusItem
("3-1 · 2 live") and the per-league `lines` behind it. The Mac app reads stdout; it
never imports this, because the bundle carries pywebview and nothing else —
the numbers come from the repo's own venv, the same one running Streamlit.

Long-lived on purpose. The player registry costs seconds to build and the
static half of a league (rosters, slots, projections) costs a couple more, so
both are built once and the loop re-reads only the live matchup, which is the
one thing that changes minute to minute.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

_STATIC_TTL = 900.0   # rosters and projections, 15 min like the app's clock


def _leagues() -> list:
    """The four leagues, read from the app where they are already written."""
    import app as _app  # imports streamlit; bare mode warns and works
    return [dict(p) for p in _app.SAVED_LEAGUES]


def _tone_mark(wp) -> str:
    if wp is None:
        return "·"
    return "W" if wp >= 0.65 else ("L" if wp <= 0.35 else "~")


def snapshot(state: dict) -> dict:
    """{title, lines, ts} for right now, rebuilding statics when they age out."""
    from . import config, gametime as GT, liveall as LA, players as PL, udk as _udk
    from .ui.in_season_ui import current_week

    season = config.current_season()
    week = current_week()
    if state.get("reg") is None:
        state["reg"] = PL.build_registry(season)
    reg = state["reg"]
    stale = (time.time() - state.get("stat_ts", 0)) > _STATIC_TTL or state.get("week") != week
    if stale:
        try:
            byes = _udk.ensure_byes(None, season)
        except Exception:  # noqa: BLE001
            byes = None
        with ThreadPoolExecutor(max_workers=4) as ex:
            state["stats"] = list(ex.map(lambda p: LA.static_for(p, reg, week, byes),
                                         state["presets"]))
        state["stat_ts"], state["week"] = time.time(), week
    try:
        games = GT.load_week(season, week, max_age=60) or {}
    except Exception:  # noqa: BLE001
        games = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        lvs = list(ex.map(lambda s: LA.live_for(s, week, games), state["stats"]))
    leagues = [LA.assemble(s, l, reg, games, week)
               for s, l in zip(state["stats"], lvs)]
    ok = [lg for lg in leagues if lg.get("ok")]

    lines, ahead, live = [], 0, 0
    for lg in ok:
        wp = lg.get("wp")
        if wp is not None and wp > 0.5:
            ahead += 1
        live += len(lg.get("on_now") or [])
        pct = f"{round(wp * 100)}%" if wp is not None else "—"
        lines.append(f'{lg["name"]}  {lg["me_pts"]:.1f}–{lg["opp_pts"]:.1f}  '
                     f'{_tone_mark(wp)} {pct}  ({lg["left"]} to play)')
    if not ok:
        title = "Bloody Sunday"
    else:
        title = f"{ahead}-{len(ok) - ahead}"
        if live:
            title += f" · {live} live"
    return {"title": title, "lines": lines or ["No live matchups"], "ts": time.time()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=float, default=0.0,
                    help="seconds between polls; 0 prints once and exits")
    a = ap.parse_args(argv)
    state = {"presets": _leagues(), "reg": None, "stats": [], "stat_ts": 0.0, "week": None}
    while True:
        try:
            out = snapshot(state)
        except Exception as e:  # noqa: BLE001  one bad poll must not end the loop
            out = {"title": "Bloody Sunday", "lines": [f"status error: {e}"],
                   "ts": time.time()}
        print(json.dumps(out), flush=True)
        if not a.loop:
            return 0
        time.sleep(a.loop)


if __name__ == "__main__":
    raise SystemExit(main())
