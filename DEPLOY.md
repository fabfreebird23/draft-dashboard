# Deploying Draft Room (Streamlit Community Cloud)

## 1. Push to GitHub (one-time)

Easiest, with the GitHub CLI:

```bash
cd ~/draft-dashboard
gh auth login            # follow the browser/device prompt (one-time)
gh repo create fabfreebird23/draft-dashboard --public --source=. --remote=origin --push
```

Or manually: create an empty repo `draft-dashboard` on github.com (no README), then:

```bash
git remote add origin https://github.com/fabfreebird23/draft-dashboard.git
git push -u origin main
```

`.streamlit/secrets.toml` and `data/` are gitignored — no credentials are pushed.

## 2. Deploy on Streamlit Community Cloud

1. Go to https://share.streamlit.io → **New app** → **Deploy from GitHub**.
2. Repository: `fabfreebird23/draft-dashboard`, branch `main`, main file `app.py`.
3. Click **Deploy**.

## 3. Add secrets (so the UDK pull / private ESPN work)

In the app's **⋮ → Settings → Secrets**, paste the same contents as your local
`.streamlit/secrets.toml`:

```toml
udk_cookie = "wordpress_logged_in_<hash>=<value>"   # for the server-side UDK pull
# espn_s2 = "..."     # optional, private ESPN leagues
# swid    = "{...}"
# github_token = "..."  # optional, to persist saved rankings to a repo branch
```

The UDK cookie expires periodically — when the UDK pull starts failing, grab a
fresh cookie (DevTools → Application → Cookies → thefantasyfootballers.com) and
update the secret.

That's it — the app builds player data / ADP fresh on first load.
