"""Player stats + status surfaces — the hover tooltip (A) and the click-to-inspect
Player Spotlight card (B).

Status is the injury/availability flag derived from Sleeper's player blob (already
in the registry, no network call). Season stats are pulled lazily for a single
inspected player and cached to disk, so the rich card never slows the board.
"""
from __future__ import annotations

import json
import time
from typing import Optional

import requests

from .. import config, theme

_STATS_BASE = "https://api.sleeper.com/stats/nfl/player"
_HEADERS = {"User-Agent": "draft-dashboard/1.0 (personal fantasy tool)"}
_STATS_TTL = 60 * 60 * 24 * 7  # season stats are static once a year ends


# ---- status flag (no network) ------------------------------------------------
def injury_flag(pm) -> tuple[str, str]:
    """(label, css_class) for a player's current availability. css_class is one of
    ok/ques/out and drives the pill color (no emoji)."""
    s = (getattr(pm, "injury_status", None) or "").lower()
    status = (getattr(pm, "status", None) or "").lower()
    if "ir" in status or s in ("ir", "injured reserve"):
        return ("IR", "out")
    if s in ("out", "doubtful") or "suspend" in status:
        return ("Doubtful" if s == "doubtful" else "Out", "out")
    if s in ("questionable", "q"):
        return ("Questionable", "ques")
    if s:
        return (getattr(pm, "injury_status"), "ques")
    return ("Healthy", "ok")


def _bio_bits(pm, byes: dict) -> list[str]:
    bits = []
    if getattr(pm, "age", None):
        bits.append(f"Age {pm.age}")
    yx = getattr(pm, "years_exp", None)
    if yx is not None:
        bits.append("Rookie" if yx == 0 else f"{yx} yr{'s' if yx != 1 else ''}")
    bye = byes.get(pm.team) if byes else None
    if bye:
        bits.append(f"Bye {bye}")
    return bits


def tooltip_text(pm, *, pos_rank="", adp=None, tier=None, byes=None) -> str:
    """One-line hover string for `help=` / `title=`: rank · ADP · bio · status."""
    parts = []
    head = " ".join(x for x in [pos_rank, pm.name] if x).strip()
    if head:
        parts.append(head)
    if adp:
        parts.append(f"ADP {int(adp)}")
    if tier:
        parts.append(f"Tier {tier}")
    parts += _bio_bits(pm, byes or {})
    flag, fcls = injury_flag(pm)
    inj = getattr(pm, "injury_body_part", None)
    parts.append(f"{flag} ({inj})" if (inj and fcls != "ok") else flag)
    return "  ·  ".join(parts)


# ---- season stats (lazy, disk-cached) ----------------------------------------
def _cache_path(pid, season) -> "object":
    return config.DATA_DIR / f"pstats_{season}_{pid}.json"


def season_stats(pid, season: int) -> Optional[dict]:
    """Per-player regular-season totals from Sleeper, cached to disk. Returns the
    raw `stats` dict (pts_ppr, rush_yd, rec, …) or None."""
    if not pid:
        return None
    p = _cache_path(pid, season)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if p.exists() and (time.time() - p.stat().st_mtime) < _STATS_TTL:
        try:
            return json.loads(p.read_text()) or None
        except Exception:  # noqa: BLE001
            pass
    try:
        url = f"{_STATS_BASE}/{pid}?season_type=regular&season={season}&grouping=season"
        r = requests.get(url, headers=_HEADERS, timeout=8)
        r.raise_for_status()
        stats = (r.json() or {}).get("stats") or {}
    except Exception:  # noqa: BLE001
        if p.exists():
            try:
                return json.loads(p.read_text()) or None
            except Exception:  # noqa: BLE001
                return None
        return None
    p.write_text(json.dumps(stats))
    return stats or None


def weekly_profile(pid, season: int, scoring: str = "ppr"):
    """Floor/ceiling/consistency from last season's week-by-week scores. Returns
    {games, ppg, floor, ceiling, boom, bust} or None. Lazy + disk-cached."""
    if not pid:
        return None
    p = config.DATA_DIR / f"wk_{season}_{pid}.json"
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = None
    if p.exists() and (time.time() - p.stat().st_mtime) < _STATS_TTL:
        try:
            data = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            data = None
    if data is None:
        try:
            url = f"{_STATS_BASE}/{pid}?season_type=regular&season={season}&grouping=week"
            wk = requests.get(url, headers=_HEADERS, timeout=8).json() or {}
            key = {"ppr": "pts_ppr", "half": "pts_half_ppr", "std": "pts_std"}.get(scoring, "pts_ppr")
            data = [round(float((wk[w].get("stats") or {}).get(key)), 1)
                    for w in wk if isinstance(wk[w], dict)
                    and (wk[w].get("stats") or {}).get(key) is not None]
            p.write_text(json.dumps(data))
        except Exception:  # noqa: BLE001
            return None
    pts = sorted([x for x in (data or []) if x is not None])
    g = len(pts)
    if g < 4:
        return None
    floor = sum(pts[:max(1, g // 4)]) / max(1, g // 4)           # avg of worst quartile
    ceiling = sum(pts[-max(1, g // 4):]) / max(1, g // 4)        # avg of best quartile
    return {"games": g, "ppg": sum(pts) / g, "floor": floor, "ceiling": ceiling, "all": pts}


_BOOM_BUST = {"QB": (24, 14), "RB": (20, 8), "WR": (20, 8), "TE": (14, 5)}


def boom_bust(profile, pos):
    """(boom%, bust%) — share of games above the elite / below the dud threshold."""
    if not profile:
        return None
    boom_t, bust_t = _BOOM_BUST.get(pos, (20, 8))
    pts = profile["all"]
    g = len(pts)
    boom = round(100 * sum(1 for x in pts if x >= boom_t) / g)
    bust = round(100 * sum(1 for x in pts if x <= bust_t) / g)
    return boom, bust


def opportunity_stats(s: dict, pos: str, games):
    """Usage that predicts fantasy better than past points: snap share, volume,
    red-zone looks. Returns [(label, value), ...]."""
    out = []
    off, tm = s.get("off_snp"), s.get("tm_off_snp")
    if off and tm:
        out.append(("Snap %", f"{round(100 * off / tm)}%"))
    g = games or s.get("gp") or s.get("gms_active") or 0
    tgt, rush = s.get("rec_tgt"), s.get("rush_att")
    if pos in ("WR", "TE"):
        if tgt and g:
            out.append(("Tgt/g", f"{tgt / g:.1f}"))
        if s.get("rec_rz_tgt"):
            out.append(("RZ tgt", _fmt(s["rec_rz_tgt"])))
    elif pos == "RB":
        if rush and g:
            out.append(("Carry/g", f"{rush / g:.1f}"))
        if tgt and g:
            out.append(("Tgt/g", f"{tgt / g:.1f}"))
        rz = (s.get("rush_rz_att") or 0) + (s.get("rec_rz_tgt") or 0)
        if rz:
            out.append(("RZ touch", _fmt(rz)))
    elif pos == "QB":
        if s.get("pass_att") and g:
            out.append(("Pass att/g", f"{s['pass_att'] / g:.1f}"))
        if s.get("rush_att") and g:
            out.append(("Rush/g", f"{s['rush_att'] / g:.1f}"))
    return out


def _fmt(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else f"{f:.1f}"


def _statline(pos: str, s: dict) -> list[tuple[str, str]]:
    """Position-appropriate (label, value) counting stats for the card grid."""
    g = s.get("gp") or s.get("gms_active")
    rows: list[tuple[str, str]] = []
    if g:
        rows.append(("Games", _fmt(g)))
    if pos == "QB":
        for lbl, k in [("Pass Yds", "pass_yd"), ("Pass TD", "pass_td"),
                       ("INT", "pass_int"), ("Rush Yds", "rush_yd"), ("Rush TD", "rush_td")]:
            if s.get(k) is not None:
                rows.append((lbl, _fmt(s[k])))
    elif pos == "RB":
        for lbl, k in [("Rush Yds", "rush_yd"), ("Rush TD", "rush_td"), ("Rec", "rec"),
                       ("Rec Yds", "rec_yd"), ("Rec TD", "rec_td")]:
            if s.get(k) is not None:
                rows.append((lbl, _fmt(s[k])))
    else:  # WR/TE
        for lbl, k in [("Rec", "rec"), ("Tgt", "rec_tgt"), ("Rec Yds", "rec_yd"),
                       ("Rec TD", "rec_td"), ("Rush Yds", "rush_yd")]:
            if s.get(k) is not None:
                rows.append((lbl, _fmt(s[k])))
    return rows


def _scoring_pts(s: dict, scoring: str) -> Optional[float]:
    key = {"ppr": "pts_ppr", "half": "pts_half_ppr", "std": "pts_std"}.get(scoring, "pts_ppr")
    v = s.get(key)
    if v is None:
        v = s.get("pts_ppr") or s.get("pts_half_ppr") or s.get("pts_std")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ---- Spotlight card (B) ------------------------------------------------------
def spotlight_html(pm, *, pos_rank="", adp=None, tier=None, byes=None, next_pick=None,
                   season: int, scoring: str = "ppr", prev_label: str = "",
                   vorp=None, proj=None, verdict=None, synergy=None, drop_next=None,
                   marg=None, sos=None, overall=None, compact=False) -> str:
    """Rich inspect card: headshot, identity, VORP value, grab/wait verdict, survival
    %, roster synergy, tier drop-off, playoff SoS, prior-season stats + opportunity
    usage + boom/bust profile, injury."""
    from . import components as C
    flag, fcls = injury_flag(pm)
    inj = getattr(pm, "injury_body_part", None)
    flag_full = f"{flag} · {inj}" if (inj and fcls != "ok") else flag
    bye = (byes or {}).get(pm.team)

    # value row — VORP (points over replacement) + projection + grab/wait verdict
    val_bits = []
    if vorp is not None:
        sign = "+" if vorp >= 0 else ""
        val_bits.append(
            f'<span class="pc-vorp" title="VORP — projected fantasy points above a '
            f'replacement-level starter at this position. Higher = more draft value; '
            f'it accounts for scarcity, so a 0 here is a waiver-wire-level player.">'
            f'VALUE {sign}{vorp:.0f}</span>')
    if marg is not None:
        ms = "+" if marg >= 0 else ""
        val_bits.append(
            f'<span class="pc-marg" title="Value adjusted for YOUR roster — depth at a '
            f'position you have already filled is worth less to you than this player\'s '
            f'raw value.">{ms}{marg:.0f} for you</span>')
    if proj:
        val_bits.append(f'<span class="pc-proj" title="Projected {scoring.upper()} fantasy '
                        f'points for the upcoming season.">{proj:.0f} proj</span>')
    if verdict:
        val_bits.append(
            f'<span class="pc-verdict {verdict[1]}" title="Draft urgency — combines how '
            f'likely this player survives to your next pick with how few startable players '
            f'remain at the position. GRAB NOW = scarce & unlikely to return; CAN WAIT = '
            f'likely still there next time.">{verdict[0]}</span>')
    val_block = f'<div class="pc-value">{"".join(val_bits)}</div>' if val_bits else ""

    # survival % — chance this player is still on the board at your next pick
    sv_block = ""
    sv = C.survival_pct(adp, next_pick) if next_pick else None
    if sv is not None:
        sc = C.survival_colors(sv)
        extra = ""
        if drop_next:
            extra = (f' · <span class="pc-drop" title="Projected-point drop from this tier '
                     f'to the best player in the next tier — how steep the cliff is.">'
                     f'−{drop_next:.0f} to next tier</span>')
        sv_block = (f'<div class="pc-surv" title="Chance this player is still on the board at '
                    f'your next pick, modeled from ADP. Low % = grab now.">'
                    f'There at your next pick (#{int(next_pick)}): '
                    f'<span class="svbox" style="background:{sc[0]};color:{sc[1]}">{sv}%</span>{extra}</div>')

    syn_block = ""
    syns = list(synergy or [])
    if sos:
        syns = [("SoS", sos[0])] + syns        # surface playoff schedule first
    if syns:
        def _cls(kind, who):
            return f"sos-{sos[1]}" if (kind == "SoS" and sos) else ""
        chips = "".join(f'<span class="pc-syn {_cls(k, w)}" title="{sos[2] if k == "SoS" else ""}">'
                        f'{w if k == "SoS" else f"{k}: {w}"}</span>' for k, w in syns)
        syn_block = f'<div class="pc-syns">{chips}</div>'

    meta_bits = []
    if overall:
        meta_bits.append(f'<b>#{overall}</b> <span class="pc-mlbl">overall</span>')
    if pos_rank:
        meta_bits.append(f"<b>{pos_rank}</b>")
    if adp:
        meta_bits.append(f"ADP {int(adp)}")
    if tier:
        meta_bits.append(f"Tier {tier}")
    if bye:
        meta_bits.append(f"Bye {bye}")
    meta = " · ".join(meta_bits)

    bio = " · ".join(_bio_bits(pm, byes or {})) or "—"
    if getattr(pm, "college", None):
        bio += f" · {pm.college}"

    s = season_stats(pm.sleeper_pid, season)
    if s:
        pts = _scoring_pts(s, scoring)
        g = s.get("gp") or s.get("gms_active")
        grid = _statline(pm.position, s)
        cells = "".join(f'<div class="pc-stat"><span class="pc-v">{v}</span>'
                        f'<span class="pc-k">{k}</span></div>' for k, v in grid)
        ppg = f" · {pts / g:.1f}/g" if (pts and g) else ""
        pts_line = (f'<div class="pc-pts">{prev_label} fantasy: <b>{pts:.0f}</b> pts{ppg}</div>'
                    if pts is not None else "")
        # opportunity usage (snap %, volume, red-zone)
        opp = opportunity_stats(s, pm.position, g)
        opp_title = ("Opportunity / usage last season — snap share, volume per game, and "
                     "red-zone looks. Usage predicts fantasy points better than past points "
                     "do, so it's a leading indicator for breakouts.")
        opp_block = (f"<div class='pc-opp' title='{opp_title}'>" + "".join(
            f'<span class="pc-ochip"><b>{v}</b> {k}</span>' for k, v in opp) + "</div>") if opp else ""
        # boom / bust from week-to-week scores
        prof = weekly_profile(pm.sleeper_pid, season, scoring)
        bb_block = ""
        if prof:
            bb = boom_bust(prof, pm.position)
            boom = (f'<span class="pc-boom" title="Share of games last season with an elite, '
                    f'league-winning score. High = big upside.">{bb[0]}% boom</span>') if bb else ""
            bust = (f'<span class="pc-bust" title="Share of games last season with a dud score '
                    f'that sinks your week. High = risky.">{bb[1]}% bust</span>') if bb else ""
            bb_block = (f'<div class="pc-bb"><span class="pc-fc" title="Floor = average of the '
                        f'worst quarter of games; Ceiling = average of the best quarter. The '
                        f'gap is the player\'s week-to-week range.">Floor '
                        f'<b>{prof["floor"]:.0f}</b> · Ceiling <b>{prof["ceiling"]:.0f}</b></span>'
                        f'{boom}{bust}</div>')
        statblock = f'{pts_line}<div class="pc-grid">{cells}</div>{opp_block}{bb_block}'
    else:
        statblock = f'<div class="pc-nostat">No {prev_label} stats (rookie or DNP).</div>'

    return (
        f'<div class="pcard{" compact" if compact else ""}">'
        f'  <div class="pc-head">{theme.img_tag(pm.sleeper_pid, "pc-img")}'
        f'    <div class="pc-id"><div class="pc-name">{pm.name}</div>'
        f'      <div class="pc-pos">{pm.position} · {pm.team or "FA"}</div>'
        f'      <div class="pc-flag {fcls}">{flag_full}</div></div></div>'
        f'  {val_block}'
        f'  <div class="pc-meta">{meta}</div>'
        f'  <div class="pc-bio">{bio}</div>'
        f'  {syn_block}'
        f'  {sv_block}'
        f'  {statblock}'
        f'</div>'
    )
