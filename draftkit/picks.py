"""Future draft picks as tradeable assets.

The trade analyzer could weigh players and keepers but not picks, which in a
keeper league is most of the point: the thing you actually get offered in October
is "my 2027 second for your Chase". A screen that cannot represent the offer
cannot judge it.

Sleeper's league-level ``traded_picks`` gives every swap for every season, and
un-traded picks are implicit — each roster starts holding its own pick in every
round of every season, and a row moves one. So ownership is: start from the
identity mapping, apply the rows.

VALUING a pick is the honest difficulty, and this module deliberately does the
simple thing rather than the clever one:

  * A pick is priced by its expected OVERALL position, and a trade's effect is
    the difference in those positions. Same unit as the keeper screen's surplus
    ("+80 picks"), so the two numbers on the trade screen can sit side by side
    without a conversion factor nobody could check.
  * Position within the round is unknowable in-season — it depends on where the
    other guy finishes — so every pick is priced at the MIDDLE of its round. A
    2027 1st is not assumed to be the 1.01.
  * The scale is linear in picks, which understates the top of round one: the
    gap between 1.01 and 1.08 is worth more than the gap between 12.01 and
    12.08. It is stated on the screen rather than silently corrected, because a
    made-up convex curve would be a second unverifiable number on top of the
    first.

None of this needs next year's rankings, which do not exist yet. That is a
feature: a pick's worth here is its draft capital, not a guess at who will be
sitting there in eight months.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple


def ownership(traded: List[dict], roster_ids: List[int], seasons: List[str],
              rounds: int) -> Dict[Tuple[str, int, int], int]:
    """{(season, round, original_roster_id): current_owner_roster_id}.

    Every pick is listed, traded or not — the caller wants "what does this manager
    hold", and a dict of only the exceptions cannot answer that without repeating
    this logic at the call site.
    """
    own: Dict[Tuple[str, int, int], int] = {}
    for s in seasons:
        for r in range(1, max(1, rounds) + 1):
            for rid in roster_ids:
                own[(str(s), r, int(rid))] = int(rid)
    for row in traded or []:
        try:
            key = (str(row["season"]), int(row["round"]), int(row["roster_id"]))
        except (KeyError, TypeError, ValueError):
            continue
        if key in own:
            own[key] = int(row["owner_id"])
    return own


def held_by(own: Dict[Tuple[str, int, int], int], roster_id: int) -> List[dict]:
    """Picks this roster currently holds, earliest season and round first.

    `origin` is whose pick it started as — a manager holding three seconds needs
    them told apart, and "2027 R2 (via Ned)" is how everyone already says it.
    """
    out = []
    for (season, rnd, orig), owner in own.items():
        if int(owner) != int(roster_id):
            continue
        out.append({"season": str(season), "round": int(rnd), "origin": int(orig),
                    "own": int(orig) == int(roster_id)})
    out.sort(key=lambda p: (p["season"], p["round"], p["origin"]))
    return out


def overall(rnd: int, n_teams: int) -> float:
    """Expected overall pick number, priced at the MIDDLE of the round.

    Draft order for a future season isn't set — it follows standings that haven't
    happened. The midpoint is the only defensible point estimate, and it keeps a
    round-for-round swap correctly worth zero instead of whatever two arbitrary
    slot guesses happened to differ by.
    """
    n = max(1, int(n_teams or 1))
    return (int(rnd) - 1) * n + (n + 1) / 2.0


def capital(picks: List[dict], n_teams: int) -> float:
    """Total draft capital of a bundle, in 'picks of position'.

    Higher is better, so the number moves the same direction as every other
    figure on the trade screen. An early pick is worth more, and `overall` counts
    the wrong way round, so it is subtracted from a fixed ceiling — the ceiling
    cancels out entirely in any comparison of two bundles OF THE SAME SIZE, and
    is stated on screen for the case where it does not (a 2-for-1).
    """
    n = max(1, int(n_teams or 1))
    ceiling = _ceiling(n)
    return sum(max(0.0, ceiling - overall(p["round"], n)) for p in picks or [])


def _ceiling(n_teams: int) -> float:
    """One pick past a 15-round draft — deep enough that no real round prices as
    worthless, shallow enough that a last-rounder is still visibly cheap."""
    return 15.0 * max(1, int(n_teams or 1)) + 1


def label(p: dict, team_name=None) -> str:
    """"2027 R2" — plus "(via Ned)" when it isn't originally his."""
    base = f'{p["season"]} R{p["round"]}'
    if p.get("own") or team_name is None:
        return base
    return f'{base} (via {team_name})'


def future_seasons(traded: List[dict], current_season: int, ahead: int = 2) -> List[str]:
    """Seasons worth offering in a picker: the next two, plus any further-out one
    the league has actually traded into — a 2029 nobody has touched is 14 rows of
    noise in a dropdown, but a 2029 first that has already moved is a real asset. Never the current season — that draft
    has already happened, and a pick in it is not an asset, it is a memory."""
    out = {str(current_season + i) for i in range(1, max(1, ahead) + 1)}
    for row in traded or []:
        try:
            s = int(row.get("season"))
        except (TypeError, ValueError):
            continue
        if s > int(current_season):
            out.add(str(s))
    return sorted(out)
