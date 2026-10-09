"""Check the phone's deep links without a phone or a browser.

    DRAFTKIT_LOCAL_ONLY=1 .venv/bin/python scripts/check_deeplinks.py

Streamlit's AppTest runs app.py headlessly with query params set, so every link
the Android tab bar and league chips can produce is checked for landing on the
right league and tab. Written after "7½ Men" broke every link to it: the label
slugged to "7½-men" and a link that said "7-1-2" landed on Home, and the only
way anyone found out was by tapping it on a phone.
"""
from __future__ import annotations

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

# app.py imports draftkit from the repo root, which isn't on the path when this
# runs as scripts/check_deeplinks.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CASES = [("kreeper", "Lineup"), ("babies", "Live"), ("seven-half", "Rankings"),
         ("tds", "Waivers")]
WANT = {"kreeper": "1310907162930733056", "babies": "1312885282554535936",
        "seven-half": "1388606375239643136", "tds": "798873"}


def main() -> int:
    bad = 0
    for lg, tab in CASES:
        at = AppTest.from_file("app.py", default_timeout=240)
        at.query_params.update({"shell": "android", "league": lg, "tab": tab})
        at.run()
        sel = at.session_state["league"] if "league" in at.session_state else None
        navk = [k for k in at.session_state.filtered_state if k.startswith("nav_in_")]
        nav = at.session_state[navk[0]] if navk else None
        ok = bool(sel) and str(sel["league_id"]) == WANT[lg] and nav == tab and not at.exception
        bad += not ok
        print(f'{"ok " if ok else "BAD"} {lg:11s} -> {sel and sel["league_id"]}  tab={nav}')
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
