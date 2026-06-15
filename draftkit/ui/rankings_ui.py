"""My Rankings tab — import a UDK board (stored login, paste, URL, or upload)."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .. import rankings, storage, udk


def _set(ctx, ranks):
    # re-apply the user's saved hand-tweaks on top of any fresh import/pull
    ranks = rankings.apply_tweaks(ranks, storage.load_tweaks(ctx["league_key"]))
    st.session_state[ctx["ranks_key"]] = ranks
    storage.save_rankings(ctx["league_key"], ranks)


def _nudge(ctx, ranks, ia, ib):
    """Swap two adjacent players, renumber, and remember both as tweaks."""
    ranks[ia], ranks[ib] = ranks[ib], ranks[ia]
    for i, r in enumerate(ranks, 1):
        r["rank"] = i
    tw = storage.load_tweaks(ctx["league_key"])
    for r in (ranks[ia], ranks[ib]):
        pid = str(r.get("pid"))
        if pid:
            tw.setdefault(pid, {})["rank"] = r["rank"]
    storage.save_tweaks(ctx["league_key"], tw)
    st.session_state[ctx["ranks_key"]] = ranks
    storage.save_rankings(ctx["league_key"], ranks)
    st.rerun()


def _set_tier(ctx, ranks, pid, tier):
    tw = storage.load_tweaks(ctx["league_key"])
    tw.setdefault(str(pid), {})["tier"] = int(tier)
    storage.save_tweaks(ctx["league_key"], tw)
    for r in ranks:
        if str(r.get("pid")) == str(pid):
            r["tier"] = r["pos_tier"] = int(tier)
    st.session_state[ctx["ranks_key"]] = ranks
    storage.save_rankings(ctx["league_key"], ranks)


def _udk_cookie() -> str:
    try:
        return st.secrets.get("udk_cookie", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def render(ctx) -> None:
    reg = ctx["registry"]
    rkey = ctx["ranks_key"]
    if rkey not in st.session_state:
        st.session_state[rkey] = storage.load_rankings(ctx["league_key"])

    st.caption("Your league ships with a current **UDK board** already loaded. To "
               "refresh it from The Fantasy Footballers, use the one-click bookmarklet "
               "(it runs in your browser, where you're logged in), or paste / upload / "
               "link a CSV. Tiers, ranks, positions and teams are handled, saved per league.")

    cookie = _udk_cookie()
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Pull from UDK (stored login)", type="primary",
                     disabled=not cookie, use_container_width=True):
            with st.spinner("Scraping the UDK…"):
                got = udk.fetch_udk(cookie, reg, ctx["meta"].scoring)
            if got:
                _set(ctx, got)
                st.success(f"Pulled {len(got)} players from the UDK.")
            else:
                st.warning("Server-side pull is blocked on the hosted app — The Fantasy "
                           "Footballers blocks cloud-server IPs (it works when you run the "
                           "app locally). Your seeded UDK board is already loaded below; to "
                           "refresh, use the **one-click bookmarklet** and upload the CSV.")
        if not cookie:
            st.caption("Server-side pull only runs locally (the host blocks cloud IPs). "
                       "Use the bookmarklet below to refresh on the hosted app.")

    with st.expander("One-click UDK bookmarklet (no login needed)"):
        st.markdown(
            "Runs **in your browser** (where you're already logged into the UDK):\n\n"
            "1. Bookmark this page, edit the bookmark, name it *Grab UDK*, and replace "
            "its **URL** with the code below.\n"
            "2. Open your **UDK → Position Rankings** page.\n"
            "3. Click **Grab UDK** — it cycles QB/RB/WR/TE and downloads "
            "`udk_rankings.csv`.\n"
            "4. Back here, choose **Upload file** and pick that CSV.")
        st.code(udk.BOOKMARKLET, language="text")

    src = st.radio("Other sources", ["Paste", "CSV / Sheet URL", "Upload file"],
                   horizontal=True, key=f"{rkey}_src")
    if src == "Paste":
        text = st.text_area("Paste rankings (or CSV)", height=200, key=f"{rkey}_text",
                            placeholder="Tier 1\nJa'Marr Chase\nBijan Robinson\nTier 2\n...")
        if st.button("Parse & save"):
            _set(ctx, rankings.smart_parse(text, reg))
    elif src == "CSV / Sheet URL":
        url = st.text_input("CSV or published Google-Sheet URL", key=f"{rkey}_url")
        if st.button("Fetch & save") and url:
            try:
                _set(ctx, rankings.smart_parse(rankings.fetch_url(url), reg))
                st.success("Fetched from URL.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Couldn't fetch that URL ({type(e).__name__}). Make sure it's "
                         "public / published to the web as CSV.")
    else:
        up = st.file_uploader("Upload rankings (.csv or .json)", type=["csv", "json"],
                              key=f"{rkey}_up")
        if up is not None:
            try:
                raw = up.getvalue().decode("utf-8", "ignore")
                parsed = json.loads(raw) if up.name.endswith(".json") else rankings.smart_parse(raw, reg)
                _set(ctx, parsed)
                st.success(f"Loaded {len(parsed)} players.")
            except Exception:  # noqa: BLE001
                st.error("Couldn't read that file.")

    ranks = st.session_state.get(rkey)
    if not ranks:
        return
    unmatched = [r["name"] for r in ranks if not r.get("pid")]
    st.success(f"**{len(ranks)}** ranked · **{len(ranks) - len(unmatched)}** matched"
               f" · **{len(unmatched)}** unmatched.")
    if unmatched:
        with st.expander(f"{len(unmatched)} names didn't match — fix spelling & re-import"):
            st.write(", ".join(unmatched))
    st.download_button("Save my rankings (.json)", json.dumps(ranks),
                       file_name="my_rankings.json", mime="application/json")

    # ---- edit mode: hand-tweak the board; tweaks persist + re-apply on every pull ----
    tw = storage.load_tweaks(ctx["league_key"])
    tcol1, tcol2 = st.columns([3, 1])
    edit = tcol1.toggle("✏️ Edit my board (nudge players ↑/↓, set tiers)",
                        key=f"{rkey}_edit")
    if tw:
        if tcol2.button(f"Reset {len(tw)} tweaks", use_container_width=True):
            storage.save_tweaks(ctx["league_key"], {})
            with st.spinner("Reverting to the UDK board…"):
                _set(ctx, storage.load_rankings(ctx["league_key"]))  # tweaks now empty
            st.rerun()
    if not edit:
        st.caption(f"{len(tw)} active tweak(s) — they re-apply automatically when you "
                   "refresh from UDK." if tw else "No tweaks yet — turn on Edit to nudge "
                   "players up/down or change tiers; your changes survive UDK refreshes.")
        st.dataframe(pd.DataFrame([{"Rk": r["rank"], "Tier": r.get("pos_tier") or r["tier"],
                                    "Player": r["name"], "✎": "•" if str(r.get("pid")) in tw else ""}
                                   for r in ranks]),
                     hide_index=True, use_container_width=True, height=320)
        return

    pos_f = st.radio("Position", ["All", "QB", "RB", "WR", "TE"], horizontal=True,
                     key=f"{rkey}_editpos")
    view = [r for r in ranks if r.get("pid") and
            (pos_f == "All" or reg.meta(r["pid"]).position == pos_f)]
    cap = 80
    st.caption(f"Showing the top {min(cap, len(view))} — use the ▲▼ to nudge, the box to set tier. "
               "Edits save instantly and stick through UDK refreshes.")
    for vi, r in enumerate(view[:cap]):
        pid = str(r["pid"])
        pm = reg.meta(pid)
        c = st.columns([0.5, 0.5, 5.2, 1.2], gap="small")
        # ▲ swaps with the player above in this view; ▼ with the one below
        idx = ranks.index(r)
        if vi > 0 and c[0].button("▲", key=f"{rkey}_up_{pid}", use_container_width=True):
            _nudge(ctx, ranks, idx, ranks.index(view[vi - 1]))
        if vi < min(cap, len(view)) - 1 and c[1].button("▼", key=f"{rkey}_dn_{pid}",
                                                        use_container_width=True):
            _nudge(ctx, ranks, idx, ranks.index(view[vi + 1]))
        tweaked = "✎ " if pid in tw else ""
        c[2].markdown(f"**{r['rank']}.** {tweaked}{pm.position}{r.get('pos_rank') or ''} · "
                      f"{r['name']} · {pm.team}")
        cur_tier = int(r.get("pos_tier") or r.get("tier") or 1)
        nt = c[3].number_input("tier", min_value=1, max_value=20, value=cur_tier,
                               key=f"{rkey}_tier_{pid}", label_visibility="collapsed")
        if int(nt) != cur_tier:
            _set_tier(ctx, ranks, pid, nt)
            st.rerun()
