"""What a waiver claim actually costs in THIS league — priced from its own history.

The old guidance (`weekly.bid_guidance`) priced a claim from what the player is
worth to you: a +3/wk upgrade came out at "$28–43 of $100". That's the most you
should pay, not what you need to pay. In Kreeper, 430 claims won since 2023:
55% went for $0, only 18% drew a second bid, and the median price to beat the
runner-up was $2. The app was telling him to pay ten times the market.

So a recommendation now has two parts:

  market  — the price that beat the runner-up on similar claims in this league
            (similar = projected about as well, same part of the season,
             recent seasons weighted up), at a win rate set by how much he
             matters to you;
  ceiling — `weekly.bid_guidance`, what he is worth to YOUR lineup.

The bid is the market, capped by the ceiling. A league that doesn't use FAAB
(Babies & Boomer: Sleeper waiver_type 1, reverse standings) gets no dollar
figure at all, because there priority decides and a bid means nothing.

Past seasons are committed under data_seed/faab/ (they never change); the
current season is pulled live from Sleeper and cached to disk.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional

from . import config, sleeper_client as api

SEED = config.ROOT / "data_seed" / "faab"
FAAB = 2                  # Sleeper settings.waiver_type: 0 rolling, 1 reverse standings, 2 FAAB
# Pseudo-claims of the pooled prior a thin league borrows from. 7½ Men has one
# season (24 claims); on its own a single $9 claim would set its price.
PRIOR_N = 25.0
_PRIOR = {"p_cont": 0.20, "fracs": [0.01, 0.01, 0.02, 0.02, 0.03, 0.05, 0.08, 0.12, 0.20]}


# ------------------------------------------------------------------ settings
def waiver_type(league_id: str) -> Optional[int]:
    try:
        lg = api.get_league(str(league_id)) or {}
        return int((lg.get("settings") or {}).get("waiver_type"))
    except Exception:  # noqa: BLE001
        return None


def uses_faab(league_id: str) -> bool:
    """True unless Sleeper says this league runs on waiver priority.

    A league with a `waiver_budget` set but waiver_type 1 still shows a budget
    in its settings — Sleeper leaves the field there — which is how B&B ended
    up with bid advice it can't use."""
    wt = waiver_type(league_id)
    return wt is None or wt == FAAB


# --------------------------------------------------------------------- claims
def _phase(week: int) -> int:
    """0 = weeks 1–4 (breakouts, full budgets), 1 = 5–9, 2 = 10+."""
    return 0 if week <= 4 else 1 if week <= 9 else 2


def _week_proj(season: int, week: int) -> Dict[str, float]:
    def _fetch():
        import requests
        r = requests.get(f"https://api.sleeper.app/projections/nfl/{season}/{week}"
                         "?season_type=regular", headers=api.HEADERS, timeout=20)
        r.raise_for_status()
        rows = r.json() or []
        return {str(r.get("player_id")): round(float((r.get("stats") or {}).get("pts_ppr") or 0), 2)
                for r in rows if r.get("player_id")}
    try:
        return api._disk(f"wkproj_{season}_{week}", 7 * 86400, _fetch)
    except Exception:  # noqa: BLE001
        return {}


def season_claims(league_id: str, season: int, budget: int, through_week: int) -> List[dict]:
    """Every waiver claim in one season: winning bid, losing bids, projection."""
    from collections import defaultdict
    out = []
    for wk in range(1, max(1, through_week) + 1):
        try:
            tx = api._disk(f"tx_{league_id}_{wk}", 6 * 3600,
                           lambda wk=wk: api._get(f"league/{league_id}/transactions/{wk}") or [])
        except Exception:  # noqa: BLE001
            continue
        by_player = defaultdict(list)
        for t in tx or []:
            if t.get("type") == "waiver":
                for pid in (t.get("adds") or {}):
                    by_player[pid].append(t)
        if not by_player:
            continue
        pj = _week_proj(season, wk)
        for pid, ts in by_player.items():
            win = [t for t in ts if t.get("status") == "complete"]
            lose = [t for t in ts if t.get("status") == "failed"]
            bid = lambda t: int((t.get("settings") or {}).get("waiver_bid") or 0)  # noqa: E731
            out.append({"season": season, "week": wk, "pid": str(pid), "budget": budget,
                        "won": bid(win[0]) if win else None,
                        "lost": sorted((bid(t) for t in lose), reverse=True),
                        "bidders": len(ts),
                        "winner": (win[0].get("roster_ids") or [None])[0] if win else None,
                        "proj": float(pj.get(str(pid), 0.0))})
    return out


def history(league_id: str, season: int, week: int) -> List[dict]:
    """Seeded past seasons + this season so far (through last week's run)."""
    rows: List[dict] = []
    seed = SEED / f"{league_id}.json"
    seeded = set()
    if seed.exists():
        try:
            rows = [r for r in json.loads(seed.read_text()) if int(r["season"]) < season]
            seeded = {int(r["season"]) for r in rows}
        except Exception:  # noqa: BLE001
            rows = []
    try:
        chain = api.league_chain(str(league_id))
    except Exception:  # noqa: BLE001
        chain = []
    for c in chain:
        s = int(c["season"])
        if s in seeded or s > season:
            continue
        try:
            lg = api.get_league(c["league_id"]) or {}
        except Exception:  # noqa: BLE001
            continue
        st = lg.get("settings") or {}
        if int(st.get("waiver_type") or 0) != FAAB or not int(st.get("waiver_budget") or 0):
            continue
        thru = max(0, week - 1) if s == season else 18
        if thru:
            rows += season_claims(c["league_id"], s, int(st["waiver_budget"]), thru)
    return rows


# ---------------------------------------------------------------------- model
def _wq(pairs: List[tuple], q: float) -> float:
    """Weighted quantile of [(value, weight)]."""
    pairs = sorted(pairs)
    tot = sum(w for _v, w in pairs) or 1.0
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc / tot >= q:
            return v
    return pairs[-1][0] if pairs else 0.0


class Market:
    """A league's waiver market, fit once a week, asked once per player."""

    def __init__(self, rows: List[dict], season: int, week: int, faab: bool = True):
        self.faab, self.season, self.week = faab, season, week
        # The price that beat the runner-up, as a share of that season's budget
        # (Kreeper ran $250 in 2023). Uncontested claims cleared at $0.
        self.rows = [dict(r, clear=((max(r["lost"]) + 1) / r["budget"]) if r["lost"] else 0.0)
                     for r in rows if r.get("won") is not None and r.get("budget")]
        self.n = len(self.rows)

    def summary(self) -> Optional[str]:
        """One line on how this league bids, for the Waivers caption."""
        if not self.faab or not self.n:
            return None
        cont = [r for r in self.rows if r["lost"]]
        free = sum(1 for r in self.rows if not r["won"])
        seasons = sorted({int(r["season"]) for r in self.rows})
        med = sorted(r["clear"] for r in cont)[len(cont) // 2] if cont else 0
        since = f"since {seasons[0]}" if len(seasons) > 1 else f"in {seasons[0]}"
        return (f"{self.n} claims won here {since}: {free / self.n:.0%} for $0, "
                f"{len(cont) / self.n:.0%} drew a second bid, and the typical price "
                f"to beat the runner-up was {med:.0%} of the budget")

    def _weight(self, r: dict, proj: float, phase: int) -> float:
        w = math.exp(-abs(float(r["proj"] or 0) - proj) / 4.0)
        w *= 1.0 if _phase(int(r["week"])) == phase else 0.45
        w *= 0.8 ** max(0, self.season - int(r["season"]))
        return w

    def comps(self, proj: float, week: Optional[int] = None) -> dict:
        """P(someone else bids), and the price that wins at a chosen rate."""
        phase = _phase(week or self.week)
        ws = [(r, self._weight(r, proj, phase)) for r in self.rows]
        wt = sum(w for _r, w in ws)
        cont = [(r["clear"], w) for r, w in ws if r["lost"]]
        wc = sum(w for _c, w in cont)
        # shrink toward the pooled prior by how much evidence there is
        k = wt / (wt + PRIOR_N * 0.3)
        p_cont = k * (wc / wt if wt else 0) + (1 - k) * _PRIOR["p_cont"]
        prior = [(f, PRIOR_N * 0.3 * (1 - k) / len(_PRIOR["fracs"])) for f in _PRIOR["fracs"]]
        return {"p_cont": p_cont, "pairs": cont + prior, "n": self.n,
                "n_like": wt, "n_cont": len(cont)}

    def price(self, proj: float, win: float, week: Optional[int] = None) -> float:
        """Budget share that beat the runner-up on `win` of similar contested claims."""
        c = self.comps(proj, week)
        return _wq(c["pairs"], win) if c["pairs"] else 0.0


def target_win(gain: float, hot: bool) -> float:
    """How sure he wants to be: a tiebreak bench add isn't worth a bidding war;
    a new every-week starter is worth beating nine in ten rivals."""
    t = 0.50 + min(0.40, max(0.0, gain) / 10.0)
    return min(0.95, t + (0.10 if hot else 0.0))


def recommend(market: Optional["Market"], *, gain: float, proj: float, budget: int,
              left: int, weeks_left: int, hot: bool = False,
              ceiling: Optional[dict] = None) -> dict:
    """{low, high, note, market, ceiling, p_cont, mode} — drop-in for bid_guidance."""
    from . import weekly as W
    ceil = ceiling or W.bid_guidance(gain, left, weeks_left)
    if market is not None and not market.faab:
        return {"low": 0, "high": 0, "mode": "priority",
                "note": "waiver priority decides here — no bid to make"}
    if gain <= 0.05 or left <= 0:
        return dict(ceil, mode="faab")
    if market is None or not market.n:
        return dict(ceil, mode="value")
    c = market.comps(proj)
    win = target_win(gain, hot)
    hi_frac = _wq(c["pairs"], win)
    lo_frac = _wq(c["pairs"], max(0.40, win - 0.25))
    # $1 beats every $0 bidder, and a third of the contested claims were
    # decided by exactly that — so a claim worth making is never a $0 claim.
    m_lo = max(1, math.ceil(lo_frac * budget))
    m_hi = max(m_lo, math.ceil(hi_frac * budget))
    cap = max(1, int(ceil.get("high") or 1))
    lo, hi = min(m_lo, cap, left), min(m_hi, cap, left)
    note = (f"{c['p_cont']:.0%} of similar claims drew a 2nd bid · "
            f"${m_hi} beat {win:.0%} of those")
    if m_hi > cap:
        note += f" · worth ≤${cap} to you"
    return {"low": lo, "high": hi, "note": note, "mode": "market",
            "market": (m_lo, m_hi), "ceiling": cap, "p_cont": c["p_cont"]}


_MEMO: Dict[tuple, Market] = {}


def market_for(meta, week: int) -> Optional[Market]:
    """The league's market, fit once per (league, week) per process."""
    if getattr(meta, "platform", "") != "sleeper":
        return None
    lid = str(meta.league_id)
    season = int(getattr(meta, "season", 0) or config.current_season())
    key = (lid, season, int(week))
    if key not in _MEMO:
        faab = uses_faab(lid)
        rows = history(lid, season, int(week)) if faab else []
        _MEMO[key] = Market(rows, season, int(week), faab=faab)
    return _MEMO[key]


def hot_pids(limit: int = 25) -> set:
    """The most-added players across Sleeper in the last day — demand the
    league's own history can't see yet (a starter just got hurt)."""
    try:
        tr = api.get_trending("add", 24, 200) or {}
        return set(sorted(tr, key=lambda p: -tr[p])[:limit])
    except Exception:  # noqa: BLE001
        return set()


def bid(meta, week: int, row: dict, budget: int, left: int, weeks_left: int) -> dict:
    """The one call the screens make: a waiver-board row → a priced claim."""
    try:
        mk = market_for(meta, week)
    except Exception:  # noqa: BLE001 — no history is the old value-only advice
        mk = None
    return recommend(mk, gain=float(row.get("gain") or 0), proj=float(row.get("proj") or 0),
                     budget=budget, left=left, weeks_left=weeks_left,
                     hot=str(row.get("pid")) in hot_pids())
