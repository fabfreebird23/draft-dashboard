# Draft Room — Mock + Live Draft Dashboard

A standalone, multi-platform fantasy football draft dashboard. Import any
**Sleeper** or **ESPN** league, pull your **Ultimate Draft Kit** rankings from The
Fantasy Footballers, and run a **mock draft** or a **live draft assistant** with a
FantasyPros-style war room: tiered best-available board, my-team lineup, snake
draft grid, and an on-the-clock header. Both platforms render from one normalized
pick shape, so the UI is identical whichever league you import.

## Features

- **Import leagues** — Sleeper by league ID (public API); ESPN public by ID and
  private with `espn_s2` + `SWID` cookies (degrades gracefully to public).
- **UDK rankings** — server-side scrape with a stored UDK+ login cookie, with a
  one-click browser bookmarklet + CSV upload as a no-credentials fallback. Saved
  per league.
- **Mock draft** — AI opponents auto-pick by consensus ADP (ESPN + FantasyPros +
  FootballGuys); you draft off your UDK board. Snake order.
- **Live draft assistant** — polls the live draft (Sleeper or ESPN) and removes
  drafted players from your board in real time; optional auto-refresh.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # optional — edit it
streamlit run app.py
```

Open the URL it prints, choose a platform, paste a league ID, and import.

## Secrets

All optional — see `.streamlit/secrets.toml.example`. `udk_cookie` enables the
server-side UDK pull; `espn_s2`/`swid` enable private ESPN leagues; a
`github_token` + `github_repo` persists rankings across Streamlit Cloud restarts.

## Layout

```
app.py                 league picker + 3 tabs
draftkit/
  players.py           cross-platform player-identity registry (the join hub)
  providers/           Sleeper + ESPN providers behind one interface
  rankings.py          ranking import/parse + ADP pool
  udk.py               server-side UDK scraper (+ bookmarklet fallback)
  adp/                 consensus ADP (ESPN, FantasyPros, FootballGuys)
  storage.py           per-league rankings persistence (local or GitHub)
  theme.py             shared CSS + headshots
  ui/                  components + rankings / assistant / mock tabs
```

Lifted and decoupled from the Kreeper keeper-league app's draft kit.
