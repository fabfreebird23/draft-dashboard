"""Who sits in which seat — for leagues that don't publish a draft order.

"Show us your TD's" (ESPN 798873) draws its order at the table, so until draft day
there is no such thing as "slot 4 is Ned". Every other league here gets its order
from the platform (or from a keeper dashboard's config), and this module leaves
those completely alone: an untouched league returns the provider's order unchanged.

Two modes, because there are two things he might know when the draft starts:

  * NUMBERED — he knows his own pick number and nothing else. Seats are "Seat 1"
    … "Seat N" and the names come off the board entirely. This is the honest
    default for a room whose order is drawn on the night: labelling a seat with a
    manager who may not be sitting there is worse than labelling it with nothing.
  * NAMES — he learns the order seat by seat and fills it in. A seat he has
    assigned shows that manager; one he hasn't stays "Seat k", so the board never
    claims to know something he hasn't told it.

In NAMES mode the teams he hasn't placed fill the empty seats in the provider's
order. That keeps every seat backed by a REAL team — the AI tendencies, keeper
placements and roster panels are all keyed by team_id and would break on a
placeholder — while the label stays generic to say we're guessing.
"""
from __future__ import annotations

from typing import List, Optional

from .providers.base import Team

NUMBERED = "Numbered"
NAMES = "Names"
UNSET = "—"


def seat_label(i: int) -> str:
    return f"Seat {i + 1}"


def mode_key(league_key: str) -> str:
    return f"seatmode_{league_key}"


def gen_key(league_key: str) -> str:
    return f"seatgen_{league_key}"


def seat_key(league_key: str, i: int, gen: int = 0) -> str:
    """Widget key for seat `i`.

    `gen` is a generation counter, bumped by "Clear seats". Deleting a widget's
    session key does NOT reliably reset the widget — Streamlit re-registers it
    from its own widget state and the old manager comes straight back, which is
    what the first cut of the clear button did. A new key is a new widget, and a
    new widget starts empty.
    """
    return f"seat_{league_key}_{gen}_{i}"


def apply(order: List[Team], mode: str, picked: Optional[List[Optional[str]]] = None
          ) -> List[Team]:
    """Rearrange/relabel the draft order for the seats he has told us about.

    `picked[i]` is the DISPLAY NAME he assigned to seat i (or None/"—"). Names,
    not ids, because that is what the selectbox on the toolbar holds.
    """
    order = list(order or [])
    if not order:
        return order
    n = len(order)
    if mode == NUMBERED:
        return [Team(slot=i, team_id=t.team_id, name=seat_label(i))
                for i, t in enumerate(order)]
    if mode != NAMES or not picked:
        return order

    by_name = {t.name: t for t in order}
    placed: dict = {}
    used = set()
    for i, nm in enumerate(picked[:n]):
        if not nm or nm == UNSET:
            continue
        t = by_name.get(nm)
        # A team can only sit in one seat. If he has somehow named the same
        # manager twice, the first seat wins rather than the board losing a team.
        if t is None or t.team_id in used:
            continue
        placed[i] = t.team_id
        used.add(t.team_id)
    if not placed:
        return order

    rest = [t.team_id for t in order if t.team_id not in used]
    by_id = {t.team_id: t for t in order}
    out: List[Team] = []
    for i in range(n):
        tid = placed.get(i)
        if tid is None:
            tid = rest.pop(0)
        out.append(Team(slot=i, team_id=tid,
                        name=by_id[tid].name if i in placed else seat_label(i)))
    return out


# Leagues whose draft order is drawn at the table, so we start NUMBERED rather
# than pretending the platform's team list is a seating chart.
DRAWN_AT_TABLE = {"798873"}


def default_mode(league_id) -> str:
    return NUMBERED if str(league_id) in DRAWN_AT_TABLE else NAMES
