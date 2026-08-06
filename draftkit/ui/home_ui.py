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

_TONE = {"red": ("#fdecec", "#8c2320", "#b3261e"),
         "amber": ("#fdf3e3", "#7a4f06", "#a8570d"),
         "ok": ("#e6f4ec", "#14603f", "#1d7a55"),
         "nil": ("#eef2f6", "#54606d", "#8e9aa7")}

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


def _note(bg, fg, dot, text):
    return (f'<div class="hm-note" style="background:{bg};color:{fg}">'
            f'<i style="background:{dot}"></i><span>{text}</span></div>')


def _hub_or_platform(s):
    hub = HUBS.get(str(s.league_id))
    if hub:
        return hub
    if s.platform == "espn":
        return ("View on ESPN", ESPN_URL.format(lid=s.league_id, season=s.season))
    return None


def render(presets, on_pick, board_age_fn=None) -> None:
    head = st.columns([3, 2])
    with head[0]:
        st.markdown(f'<h1>{theme.logo_html(40)}</h1>', unsafe_allow_html=True)
    with head[1], st.container(key="hmphase"):
        # Same control as the per-league topbar, doing the analogous job: which half
        # of the year am I looking at. On Home it FILTERS rather than switching a
        # view, because Home is the only screen showing more than one league.
        view = st.radio("view", ["All", "Pre-season", "In-season"], horizontal=True,
                        key="home_phase", label_visibility="collapsed")

    rows = []
    for p in presets:
        age = None
        if board_age_fn:
            try:
                age = board_age_fn(f"{p['platform']}_{p['league_id']}")
            except Exception:  # noqa: BLE001 — a slow age lookup must not blank Home
                age = None
        rows.append((p, PH.summary(p, age), age))
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
    bg, fg, dot = _TONE.get(s.tone, _TONE["nil"])
    det = PH.detail(preset)
    key = f"hmhero_{s.platform}_{s.league_id}"
    with st.container(key=key):
        st.markdown(f'<style>.st-key-{key}{{border-top-color:{dot}}}</style>',
                    unsafe_allow_html=True)
        left, right = st.columns([1.5, 1])
        with left:
            st.markdown(
                f'<div class="hm-heroline"><span class="hm-heroname">{s.name or s.label}</span>'
                f'<span class="hm-badge" style="background:{bg};color:{fg}">'
                f'{_BADGE.get(s.tone, "")}</span></div>'
                f'<div class="hm-meta">{_meta_line(s)}</div>', unsafe_allow_html=True)

            t = st.columns(3)
            d = s.days_to_draft
            with t[0]:
                _tile("drafts in",
                      f"{max(1, int(round(d)))} days" if (d is not None and d >= 0) else "—",
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
            if a[0].button("Draft prep", key=f"hmgo_{s.league_id}", type="primary",
                           use_container_width=True):
                on_pick(preset)
            if a[1].button("Run a mock", key=f"hmmock_{s.league_id}",
                           use_container_width=True):
                st.session_state["nav_section"] = "Mock Draft"
                on_pick(preset)
            link = _hub_or_platform(s)
            if link:
                a[2].link_button(f"{link[0]} ↗", link[1], use_container_width=True)

        with right, st.container(key=f"hmwl_{s.league_id}"):
            st.markdown('<div class="hm-wl">What\'s left</div>', unsafe_allow_html=True)
            items = []
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
                b, f, dt = _TONE[tone]
                st.markdown(_note(b, f, dt, text), unsafe_allow_html=True)


def _tile(label, value, sub):
    st.markdown(f'<div class="hm-tile"><div class="tl">{label}</div>'
                f'<div class="tv">{value}</div><div class="ts">{sub}</div></div>',
                unsafe_allow_html=True)


def _render_quiet(preset, s, on_pick) -> None:
    bg, fg, dot = _TONE.get(s.tone, _TONE["nil"])
    key = f"hmq_{s.platform}_{s.league_id}"
    with st.container(key=key):
        st.markdown(
            f'<div class="hm-qline"><span class="hm-qname">{s.name or s.label}</span>'
            f'<span class="hm-badge" style="background:{bg};color:{fg}">'
            f'{_BADGE.get(s.tone, "")}</span></div>'
            f'<div class="hm-meta">{_meta_line(s)}</div>'
            f'<div class="hm-qnote">{s.note}</div>', unsafe_allow_html=True)
        a = st.columns(2)
        if a[0].button("Open", key=f"hmq_go_{s.league_id}", use_container_width=True):
            on_pick(preset)
        link = _hub_or_platform(s)
        if link:
            a[1].link_button(f"{link[0].split()[0]} ↗", link[1], use_container_width=True)
