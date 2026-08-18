"""Home — the league that needs you, up front; the rest quiet.

The premise of the screen is that it already knows which league is most urgent, so
it acts on that: one league gets the room and the detail, the others sit still
until their turn. Sorted by urgency, so you never pick a league to find out
whether it needs you.

The hero adapts rather than always shouting. Most of the year nothing is urgent —
the badge and tone follow the actual state, so a league drafting in five weeks
reads as "next up", not as an emergency. That failure mode (a loud hero with
nothing urgent in it) is the main risk of this layout and is handled explicitly.

Cost: `phase.summary` is two small calls per league, and only the HERO pays for
`phase.detail` (keepers, who's short). Four full contexts here would mean four
registries and four ADP joins before anything appeared.

LAYOUT NOTE: cards are drawn by styling the st.container, never by wrapping a
<div> around widgets — a markdown div does not enclose a widget, which is what put
the buttons outside the box the first time.
"""
from __future__ import annotations

import streamlit as st

from .. import phase as PH, theme

# Tone is a CLASS, not inline hex — inline colours can't follow the theme, which
# is exactly how the notes and badges stayed pale-on-dark when dark became the
# default. The palette for each tone lives in theme.py, once per theme.
_TONES = ("red", "amber", "ok", "nil")

HUBS = {
    "1310907162930733056": ("Kreeper hub", "https://kreeper-league.streamlit.app"),
    "1312885282554535936": ("B&B hub", "https://babies-and-boomer.streamlit.app"),
    "1388606375239643136": ("7½ Men hub", "https://seven-half-men.streamlit.app"),
}
ESPN_URL = "https://fantasy.espn.com/football/team?leagueId={lid}&seasonId={season}"

_BADGE = {"red": "needs you now", "amber": "next up",
          "ok": "in season", "nil": "nothing urgent"}


def _meta_line(s):
    bits = [s.platform.capitalize()]
    if s.num_teams:
        bits.append(f"{s.num_teams} teams")
    bits.append({"pre": "pre-season", "live": "drafting now", "in": "in-season",
                 "done": "season over"}.get(s.phase, ""))
    return " · ".join(b for b in bits if b)


def _note(tone, text):
    return (f'<div class="hm-note tone-{tone}"><i></i><span>{text}</span></div>')


def _hub_or_platform(s):
    hub = HUBS.get(str(s.league_id))
    if hub:
        return hub
    if s.platform == "espn":
        return ("View on ESPN", ESPN_URL.format(lid=s.league_id, season=s.season))
    return None


def _nfl_week() -> int:
    """The week the in-season screens will open on — the SAME function they use.

    Sleeper's state counts preseason weeks, so in August it says week 2 while the
    first week anyone scores is week 1. Home was reading the raw number, so the
    button said "Open week 2" and landed you on a page headed WEEK 1.
    """
    from .in_season_ui import current_week
    return current_week()


def _nfl_pre() -> bool:
    from .. import sleeper_client as api
    try:
        return (api.get_state("nfl") or {}).get("season_type") != "regular"
    except Exception:  # noqa: BLE001
        return True


def _days_label(d) -> str:
    """"1 days" on the tile the night before a draft is a small thing that makes the
    whole screen look unattended."""
    n = max(1, int(round(d)))
    return f"{n} day" if n == 1 else f"{n} days"


def render(presets, on_pick, board_age_fn=None) -> None:
    head = st.columns([3, 2])
    with head[0]:
        st.markdown(f'<h1>{theme.logo_html(34)}</h1>', unsafe_allow_html=True)
    with head[1], st.container(key="hmphase"):
        # Same control as the per-league topbar, doing the analogous job: which half
        # of the year am I looking at. On Home it FILTERS rather than switching a
        # view, because Home is the only screen showing more than one league.
        st.session_state.setdefault("home_phase", "All")
        view = st.segmented_control(
            "view", ["All", "Pre-season", "In-season"], key="home_phase",
            selection_mode="single", label_visibility="collapsed") or "All"

    rows = []
    for p in presets:
        age = None
        if board_age_fn:
            try:
                age = board_age_fn(f"{p['platform']}_{p['league_id']}")
            except Exception:  # noqa: BLE001 — a slow age lookup must not blank Home
                age = None
        summ = PH.summary(p, age)
        # A drafted league whose note reads "check your lineup" every week is a
        # note nobody reads. If a starter might not play, say WHO — and let that
        # raise the league's urgency so it sorts up instead of sitting third.
        if summ.phase in (PH.IN, PH.DONE):
            alert = _injury_alert(p)
            if alert:
                summ.tone, summ.note = alert
        rows.append((p, summ, age))
    rows.sort(key=lambda r: PH.sort_key(r[1]))
    if view == "Pre-season":
        rows = [r for r in rows if r[1].phase in (PH.PRE, PH.LIVE)]
    elif view == "In-season":
        rows = [r for r in rows if r[1].phase in (PH.IN, PH.DONE)]
    if not rows:
        st.info("**Nothing here yet.** No league has drafted, so there are no "
                "in-season lineups to set. This fills in as each draft finishes."
                if view == "In-season" else
                "**No leagues in this phase.**")
        return

    hero, rest = rows[0], rows[1:]
    _render_hero(*hero, on_pick=on_pick)
    if rest:
        st.markdown('<div class="hm-h">Your other leagues</div>', unsafe_allow_html=True)
        cols = st.columns(len(rest))
        for col, (preset, s, age) in zip(cols, rest):
            with col:
                _render_quiet(preset, s, on_pick)


def _render_hero(preset, s, age, on_pick) -> None:
    det = PH.detail(preset)
    key = f"hmhero_{s.platform}_{s.league_id}"
    with st.container(key=key):
        st.markdown(f'<style>.st-key-{key}{{border-top-color:'
                    f'var(--tone-{s.tone})}}</style>', unsafe_allow_html=True)
        left, right = st.columns([1.5, 1])
        with left:
            st.markdown(
                f'<div class="hm-heroline"><span class="hm-heroname">{s.name or s.label}</span>'
                f'<span class="hm-badge tone-{s.tone}">'
                f'{_BADGE.get(s.tone, "")}</span></div>'
                f'<div class="hm-meta">{_meta_line(s)}</div>', unsafe_allow_html=True)

            t = st.columns(3)
            d = s.days_to_draft
            in_season = s.phase in (PH.IN, PH.DONE)
            with t[0]:
                if in_season:
                    # A drafted league counting down to a draft that already happened
                    # is the tile telling you the wrong thing about the wrong half of
                    # the year. Once it drafts, the number that matters is the week.
                    _tile("week", str(_nfl_week()), "regular season" if not _nfl_pre() else "preseason")
                else:
                    _tile("drafts in",
                          _days_label(d) if (d is not None and d >= 0) else "—",
                          s.note.split("·")[-1].strip().rstrip(".") if (d is not None and d >= 0)
                          else "no date set yet")
            with t[1]:
                _tile("keepers",
                      (f'{det["kept"]}<span class="hm-of"> / {det["expected"]}</span>'
                       if det["expected"] else (str(det["kept"]) if det["kept"] else "—")),
                      det["short"] or ("all in" if det["kept"] else "none submitted"))
            with t[2]:
                _tile("your board",
                      "—" if age is None else (f"{int(age)}h" if age < 48 else f"{int(age/24)}d"),
                      "current" if (age is not None and age / 24 < 7) else
                      ("stale — pull a fresh one" if age is not None else "never pulled"))

            with st.container(key=f"hmact_{s.league_id}"):
                a = st.columns([1.1, 1, 1])
            # The actions have to match the half of the year the league is in. Sending
            # a drafted league to "Draft prep" is how the in-season screens ended up
            # behind a button that reads like it goes somewhere else entirely.
            lkey = f"{s.platform}_{s.league_id}"
            if in_season:
                if a[0].button(f"Open week {_nfl_week()}", key=f"hmgo_{s.league_id}",
                               type="primary", use_container_width=True):
                    st.session_state[f"nav_in_{lkey}"] = "Command Center"
                    on_pick(preset)
                if a[1].button("Waivers", key=f"hmmock_{s.league_id}", use_container_width=True):
                    # app.py setdefaults this key, so writing it BEFORE the league page
                    # exists lands you on the tab you asked for.
                    st.session_state[f"nav_in_{lkey}"] = "Waivers"
                    on_pick(preset)
            else:
                if a[0].button("Draft prep", key=f"hmgo_{s.league_id}", type="primary",
                               use_container_width=True):
                    on_pick(preset)
                if a[1].button("Run a mock", key=f"hmmock_{s.league_id}",
                               use_container_width=True):
                    # via the pending key — see _goto in prep_ui. Home renders before
                    # the league nav exists, but routing both the same way keeps it safe.
                    st.session_state["nav_goto"] = "Mock Draft"
                    on_pick(preset)
            link = _hub_or_platform(s)
            if link:
                a[2].link_button(f"{link[0]} ↗", link[1], use_container_width=True)

        with right, st.container(key=f"hmwl_{s.league_id}"):
            st.markdown('<div class="hm-wl">What\'s left</div>', unsafe_allow_html=True)
            items = []
            # In-season, the thing most likely to need him is a starter who might
            # not play. It leads, because a stale board matters less on a Tuesday
            # than a Questionable WR does on a Sunday.
            if age is None:
                items.append(("nil", "No board saved for this league yet."))
            elif age / 24 >= 7:
                items.append(("amber", f"Board is {int(age/24)} days old — pull a fresh one."))
            else:
                items.append(("ok", f"Board pulled {int(age)}h ago — current."))
            if det["short"]:
                items.append(("amber", det["short"] + "."))
            elif det["expected"]:
                items.append(("ok", "All keepers submitted."))
            items.append(("nil", s.note))
            for tone, text in items[:3]:
                st.markdown(_note(tone, text), unsafe_allow_html=True)


@st.cache_data(ttl=600, show_spinner=False)
def _injury_alert(preset: dict):
    """(tone, text) when this league has questionable starters, else None.

    Cheap on purpose — it runs for every league card on Home, so it reads the
    roster and the player payload we already cache and does no lineup maths.
    """
    if preset.get("platform") != "sleeper" or not preset.get("my_team"):
        return None
    try:
        from .. import players as PL, sleeper_client as api, weekly as W, config
        reg = PL.build_registry(int(preset.get("season") or config.current_season()))
        r = next((x for x in (api.get_rosters(str(preset["league_id"])) or [])
                  if str(x.get("owner_id")) == str(preset["my_team"])), None)
        if not r:
            return None
        starters = [str(x) for x in (r.get("starters") or []) if str(x) not in ("0", "")]
        flagged = []
        for pid in starters:
            av = W.availability(reg.meta(pid))
            if av["risky"]:
                flagged.append((reg.meta(pid).name, av["status"]))
        if not flagged:
            return None
        who = ", ".join(n for n, _s in flagged[:3])
        tone = "red" if any(s and s.upper().startswith(("OUT", "DOUB")) for _n, s in flagged) else "amber"
        return (tone, f"{len(flagged)} starter{'s' if len(flagged) != 1 else ''} "
                      f"questionable — {who}.")
    except Exception:  # noqa: BLE001 — Home must render even if a league is unreachable
        return None


def _tile(label, value, sub):
    st.markdown(f'<div class="hm-tile"><div class="tl">{label}</div>'
                f'<div class="tv">{value}</div><div class="ts">{sub}</div></div>',
                unsafe_allow_html=True)


def _render_quiet(preset, s, on_pick) -> None:
    key = f"hmq_{s.platform}_{s.league_id}"
    with st.container(key=key):
        st.markdown(
            f'<div class="hm-qline"><span class="hm-qname">{s.name or s.label}</span>'
            f'<span class="hm-badge tone-{s.tone}">'
            f'{_BADGE.get(s.tone, "")}</span></div>'
            f'<div class="hm-meta">{_meta_line(s)}</div>'
            f'<div class="hm-qnote">{s.note}</div>', unsafe_allow_html=True)
        a = st.columns(2)
        if a[0].button("Open", key=f"hmq_go_{s.league_id}", use_container_width=True):
            on_pick(preset)
        link = _hub_or_platform(s)
        if link:
            a[1].link_button(f"{link[0].split()[0]} ↗", link[1], use_container_width=True)
