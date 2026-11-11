"""Kickoff weather for the games played outdoors.

Wind is the one that matters: past about 15 mph the deep ball and the long
field goal start to go, and past 20 it shows up in every passing line. Heavy
rain or snow drags a game toward the run. None of this moves a projection
here — the sources already price what they price — it is a FLAG on the players
in those games, so the call is his.

Stadium roofs come from ESPN's scoreboard (venue.indoor), with one correction:
SoFi is listed outdoor and has a roof. Forecasts are Open-Meteo's (free, no
key), one call for every outdoor game of the week, cached an hour.
"""
from __future__ import annotations

import datetime as _dt
import json
import time
from typing import Dict, Optional

import requests

from . import config

# home team -> (lat, lon) of its stadium
_AT = {"ARI": (33.5276, -112.2626), "ATL": (33.7554, -84.4008), "BAL": (39.2780, -76.6227),
       "BUF": (42.7738, -78.7870), "CAR": (35.2258, -80.8528), "CHI": (41.8623, -87.6167),
       "CIN": (39.0954, -84.5160), "CLE": (41.5061, -81.6995), "DAL": (32.7473, -97.0945),
       "DEN": (39.7439, -105.0201), "DET": (42.3400, -83.0456), "GB": (44.5013, -88.0622),
       "HOU": (29.6847, -95.4107), "IND": (39.7601, -86.1639), "JAX": (30.3239, -81.6373),
       "KC": (39.0489, -94.4839), "LAC": (33.9535, -118.3392), "LAR": (33.9535, -118.3392),
       "LV": (36.0909, -115.1833), "MIA": (25.9580, -80.2389), "MIN": (44.9736, -93.2575),
       "NE": (42.0909, -71.2643), "NO": (29.9511, -90.0812), "NYG": (40.8135, -74.0745),
       "NYJ": (40.8135, -74.0745), "PHI": (39.9008, -75.1675), "PIT": (40.4468, -80.0158),
       "SEA": (47.5952, -122.3316), "SF": (37.4033, -121.9694), "TB": (27.9759, -82.5033),
       "TEN": (36.1665, -86.7713), "WAS": (38.9076, -76.8645)}
_ROOFED = {"SoFi Stadium"}
_URL = "https://api.open-meteo.com/v1/forecast"
_TTL = 3600
_MEM: Dict[str, tuple] = {}


def _outdoor_games(games: dict) -> list:
    """[(home, lat, lon, kickoff_dt)] for outdoor games still to be played at
    the home team's own stadium (a neutral-site game is skipped: wrong city)."""
    out, seen = [], set()
    for team, g in (games or {}).items():
        if not g.get("home") or team in seen or g.get("state") != "pre":
            continue
        seen.add(team)
        if g.get("indoor") or g.get("neutral") or (g.get("venue") in _ROOFED) or team not in _AT:
            continue
        try:
            k = _dt.datetime.fromisoformat(str(g["kickoff"]).replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            continue
        if not (0 <= (k.timestamp() - time.time()) <= 7 * 86400):
            continue
        out.append((team, _AT[team][0], _AT[team][1], k))
    return out


def label(w: Optional[dict]) -> str:
    """"22 mph wind · 70% rain · 41°" — only the parts worth saying."""
    if not w:
        return ""
    bits = []
    if w["wind"] >= 15 or w["gust"] >= 30:
        bits.append(f'{w["wind"]:.0f} mph wind' + (f' (gusts {w["gust"]:.0f})' if w["gust"] >= 30 else ""))
    if w["pop"] >= 60 and w["precip"] >= 0.03:
        bits.append(f'{w["pop"]:.0f}% {"snow" if w["temp"] <= 34 else "rain"}')
    if w["temp"] <= 20:
        bits.append(f'{w["temp"]:.0f}°')
    return " · ".join(bits)


def for_week(games: dict, season: int, week: int) -> Dict[str, dict]:
    """{team: {temp, wind, gust, pop, precip, bad, label}} for BOTH teams of every
    outdoor game with weather worth a flag or not (bad=False when it's fine)."""
    key = f"{season}_{week}"
    hit = _MEM.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    cp = config.DATA_DIR / f"weather_{season}_w{week}.json"
    try:
        if cp.exists() and time.time() - cp.stat().st_mtime < _TTL:
            out = json.loads(cp.read_text())
            _MEM[key] = (time.time(), out)
            return out
    except Exception:  # noqa: BLE001
        pass
    og = _outdoor_games(games)
    out: Dict[str, dict] = {}
    if og:
        try:
            r = requests.get(_URL, params={
                "latitude": ",".join(f"{x[1]:.4f}" for x in og),
                "longitude": ",".join(f"{x[2]:.4f}" for x in og),
                "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m",
                "wind_speed_unit": "mph", "temperature_unit": "fahrenheit", "precipitation_unit": "inch",
                "timezone": "UTC", "forecast_days": 8}, timeout=15)
            r.raise_for_status()
            docs = r.json()
            docs = docs if isinstance(docs, list) else [docs]
            for (home, _la, _lo, k), d in zip(og, docs):
                h = d.get("hourly") or {}
                times = h.get("time") or []
                want = k.strftime("%Y-%m-%dT%H:00")
                if want not in times:
                    continue
                i = times.index(want)
                # the game is three hours: take the worst of them
                sl = slice(i, min(len(times), i + 4))
                num = lambda f, agg: float(agg([x for x in (h.get(f) or [])[sl] if x is not None] or [0]))  # noqa: E731
                w = {"temp": num("temperature_2m", min), "wind": num("wind_speed_10m", max),
                     "gust": num("wind_gusts_10m", max), "pop": num("precipitation_probability", max),
                     "precip": num("precipitation", max)}
                w["label"] = label(w)
                w["bad"] = bool(w["label"])
                out[home] = w
                out[games[home]["opp"]] = w
        except Exception:  # noqa: BLE001
            out = {}
    if out or not og:
        _MEM[key] = (time.time(), out)
        try:
            cp.write_text(json.dumps(out))
        except Exception:  # noqa: BLE001
            pass
    return out
