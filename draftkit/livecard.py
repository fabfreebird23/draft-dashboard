"""One man, as both live screens want him.

The Live tab and the all-leagues drawer draw the same card at two sizes, so the
card is built in one place: who he is, the points he has, where he ends up, his
share of the seat, his game in ONE muted string and his stat line. Two screens
that computed this separately would drift, and the first thing to drift would
be the projection, which is the number he acts on.
"""
from __future__ import annotations

from typing import Optional

from . import gametime as GT, nflstats as NS, weekview as WV


def _game_line(gm: Optional[dict], state: str) -> str:
    """The game as one string: clock and score while it is on, kickoff before.

    Never two competing typographic objects — the card has exactly one bright
    line and this is not it.
    """
    if not gm:
        return "bye"
    if state in ("in", "post"):
        sc, osc = int(gm.get("score") or 0), int(gm.get("opp_score") or 0)
        vs = f'{"vs" if gm.get("home") else "@"} {gm.get("opp") or ""}'.strip()
        return f'{GT.live_label(gm)} · {sc}-{osc} {vs}'.strip(" ·")
    return f'{GT.day_label(gm)} · {"vs" if gm.get("home") else "@"} {gm.get("opp") or ""}'.strip(" ·")


def _left_of(gm: Optional[dict]) -> float:
    """How much of his game is still to come, from the scoreboard clock.

    Without a clock, half — which is what `weekview.live_projection` has always
    assumed for a game in progress.
    """
    try:
        mins, secs = (str((gm or {}).get("clock") or "0:00").split(":") + ["0"])[:2]
        played = (min(int((gm or {}).get("period") or 1), 4) - 1) * 15 \
            + (15 - (int(mins) + int(secs) / 60.0))
        return max(0.0, min(1.0, 1 - played / 60.0))
    except Exception:  # noqa: BLE001
        return 0.5


def build(pid, *, registry, games: dict, pts: float, proj: float,
          stats: Optional[dict] = None, sleeper_pid=None) -> dict:
    """A card dict for `components.h2h_side_html`. Empty seat -> {}."""
    if not pid or str(pid) in ("0", "None"):
        return {}
    try:
        pm = registry.meta(pid)
    except Exception:  # noqa: BLE001
        return {}
    gm = WV.game_of(registry, games, pid)
    state = GT.status(gm)
    pos = (pm.position or "").upper()
    sp = sleeper_pid or getattr(pm, "sleeper_pid", None) or (str(pid) if str(pid).isdigit() else None)
    row = (stats or {}).get(str(sp)) if sp else None
    card = {"face": sp, "name": pm.name, "pos": pos, "team": (pm.team or "").upper(),
            "state": state, "pts": float(pts or 0) if state in ("in", "post") else None,
            "proj": float(proj or 0), "game": _game_line(gm, state),
            "stat": NS.line(pos, row),
            "redzone": bool(gm and gm.get("redzone") and state == "in"),
            "pid": str(pid)}
    # Where he ENDS UP: what he has for a finished game, what he has plus the
    # rest of his projection for one in progress, the projection before kickoff.
    if state == "post":
        card["final"] = card["pts"]
    elif state == "in":
        card["final"] = (card["pts"] or 0) + (card["proj"] or 0) * _left_of(gm)
    if card.get("final") is not None:
        card["trend"] = card["final"] - (card["proj"] or 0)
    return card


def end(card: Optional[dict]) -> float:
    """His projected final — the number both the rail and the margin are built on."""
    if not card:
        return 0.0
    v = card.get("final")
    return float(v if v is not None else (card.get("proj") or 0))


def face_off(mine: Optional[dict], theirs: Optional[dict]):
    """Fill in each man's share of the seat and the slot's projected margin.

    Share is measured on where they end up, not on points so far: on points a
    finished man against one who has not kicked off pins the rail at 100%, which
    is a full crimson bar saying nothing.
    """
    a, b = end(mine), end(theirs)
    tot = a + b
    if mine:
        mine["share"] = (100 * a / tot) if tot else 50
    if theirs:
        theirs["share"] = (100 * b / tot) if tot else 50
    return (a - b) if (mine and theirs) else None
