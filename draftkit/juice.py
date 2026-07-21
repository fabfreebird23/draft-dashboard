"""Juice's Value — Sleeper's in-draft-room rank vs FantasyPros ECR, so you can spot
who Sleeper's default draft order over/undervalues relative to the experts before
you draft off its board.

Public Google Sheet (no auth needed), one tab per scoring format:
https://docs.google.com/spreadsheets/d/1HTixsrRtIIpnUafVkOIhET83vCFjKXSUGiG24-5jTHY

Positive skew (SleepvFP) = Sleeper ranks him LATER than FantasyPros' consensus —
he'll likely fall further than he should, a value. Negative = Sleeper ranks him
EARLIER — a reach if you chase him at that draft slot. Landmine is the sheet's own
0-10 risk scale (0 = great value, 10 = avoid).
"""
from __future__ import annotations

import io
from typing import Dict

import pandas as pd
import requests

SHEET_ID = "1HTixsrRtIIpnUafVkOIhET83vCFjKXSUGiG24-5jTHY"
# One tab per scoring format — same "ppr"/"half"/"std" convention used across the
# app (see providers/*.py _scoring_label and udk._ADP_FIELD).
_GID = {"ppr": "1312116043", "half": "1623712694", "std": "914126469"}
_CSV_URL = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
_COLS = {
    "Name": "name", "Team": "team", "BYE": "bye", "Pos": "position",
    "ADP": "adp_rank", "FantasyPros": "ecr_rank", "Sleeper ADP": "sleeper_rank",
    "SleepvFP": "skew", "Landmine": "landmine",
}


def _fetch_df(scoring: str) -> pd.DataFrame:
    gid = _GID.get(scoring, _GID["ppr"])
    resp = requests.get(_CSV_URL.format(sid=SHEET_ID, gid=gid), timeout=15)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df = df.rename(columns=_COLS)
    keep = [c for c in _COLS.values() if c in df.columns]
    return df[keep].dropna(subset=["name"]).reset_index(drop=True)


def load(registry, scoring: str = "ppr") -> Dict[str, dict]:
    """{sleeper_pid: {name, position, team, bye, adp_rank, ecr_rank, sleeper_rank,
    skew, landmine}}. Sheet rows that don't match a known Sleeper player (mostly
    deep bench/practice-squad names) are dropped. Degrades to {} if the sheet is
    unreachable — never fatal, the app just falls back to hiding the tab."""
    try:
        df = _fetch_df(scoring)
    except Exception:  # noqa: BLE001 — sheet unreachable/renamed: degrade quietly
        return {}
    out: Dict[str, dict] = {}
    for row in df.to_dict("records"):
        p = registry.resolve_name(row.get("name", ""))
        if not p or not p.sleeper_pid:
            continue
        out[p.sleeper_pid] = row
    return out
