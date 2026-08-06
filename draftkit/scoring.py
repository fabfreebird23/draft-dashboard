"""League scoring weights — so a league that isn't PPR/half/standard is valued correctly.

Everything downstream used to collapse a league's scoring to one of three labels.
That is fine for most leagues and quietly wrong for the rest: the ESPN league
"Show us your TD's" pays **2.0 points per reception** and **6 points per passing
TD**, and reading it as "ppr" understates every pass-catching back and slot
receiver while badly under-rating quarterbacks. Rankings built that way are
confidently wrong rather than roughly right.

Sleeper's projections endpoint returns the component stats (rec, rec_yd, rush_td,
pass_int …) alongside its own pts_ppr/half/std, so once we keep those components
we can score any weighting ourselves. This module is the weighting.

Keys are Sleeper's stat names, so a weights dict applies directly to a Sleeper
projection row without translation.
"""
from __future__ import annotations

from typing import Dict, Optional

# --- named presets -----------------------------------------------------------
_BASE = {
    "pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0, "pass_2pt": 2.0,
    "rush_yd": 0.1, "rush_td": 6.0, "rush_2pt": 2.0,
    "rec_yd": 0.1, "rec_td": 6.0, "rec_2pt": 2.0,
    "fum_lost": -2.0,
}
PRESETS: Dict[str, Dict[str, float]] = {
    "std": {**_BASE, "rec": 0.0},
    "half": {**_BASE, "rec": 0.5},
    "ppr": {**_BASE, "rec": 1.0},
}

# ESPN statId -> Sleeper stat key. Only the ones that move a projection; ESPN
# publishes dozens of defensive/kicking items we don't project on.
_ESPN_STAT = {
    3: "pass_yd", 4: "pass_td", 20: "pass_int", 19: "pass_2pt",
    24: "rush_yd", 25: "rush_td", 26: "rush_2pt",
    42: "rec_yd", 43: "rec_td", 44: "rec_2pt", 53: "rec",
    72: "fum_lost",
}


def from_espn(settings: dict) -> Optional[Dict[str, float]]:
    """Weights from an ESPN league's mSettings payload, or None if unreadable.

    Starts from PPR and overlays whatever ESPN actually declares, so a stat ESPN
    omits keeps a sane default instead of silently scoring zero — an omitted
    `pass_yd` scoring 0 would rank every QB last."""
    items = ((settings or {}).get("scoringSettings") or {}).get("scoringItems") or []
    if not items:
        return None
    w = dict(PRESETS["ppr"])
    seen = False
    for it in items:
        key = _ESPN_STAT.get(it.get("statId"))
        if not key:
            continue
        try:
            w[key] = float(it.get("points") or 0.0)
            seen = True
        except (TypeError, ValueError):
            continue
    return w if seen else None


def label_for(weights: Optional[Dict[str, float]]) -> str:
    """The closest ppr/half/std label. Still needed because ADP boards, DvP and
    the Juice sheet are only published in those three flavours — only the
    projections can honour exact weights."""
    if not weights:
        return "ppr"
    rec = float(weights.get("rec", 1.0))
    return "ppr" if rec >= 0.75 else ("half" if rec >= 0.25 else "std")


def is_custom(weights: Optional[Dict[str, float]]) -> bool:
    """True when these weights differ from the preset their label would pick —
    i.e. when treating the league as that label would actually mislead."""
    if not weights:
        return False
    preset = PRESETS[label_for(weights)]
    return any(abs(float(weights.get(k, v)) - v) > 1e-9 for k, v in preset.items())


def describe(weights: Optional[Dict[str, float]]) -> str:
    """Short human summary of what makes these weights unusual, for the UI."""
    if not is_custom(weights):
        return label_for(weights).upper()
    preset = PRESETS[label_for(weights)]
    bits = []
    for k, v in preset.items():
        got = float(weights.get(k, v))
        if abs(got - v) > 1e-9:
            bits.append(f"{k.replace('_', ' ')} {got:g}")
    return " · ".join(bits[:4]) or "custom"


def points(stats: dict, weights: Optional[Dict[str, float]]) -> float:
    """Fantasy points for one projection row under these weights."""
    if not stats:
        return 0.0
    w = weights or PRESETS["ppr"]
    total = 0.0
    for key, mult in w.items():
        v = stats.get(key)
        if v is None:
            continue
        try:
            total += float(v) * float(mult)
        except (TypeError, ValueError):
            continue
    return total
