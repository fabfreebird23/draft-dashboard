"""My Rankings tab — import a UDK board (stored login, paste, URL, or upload)."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .. import rankings, storage, udk


def _set(ctx, ranks):
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

    st.caption("Import your **UDK rankings** from The Fantasy Footballers. With a "
               "stored UDK login the app pulls them server-side; otherwise use the "
               "one-click bookmarklet, or paste / upload / link a CSV. Tiers, ranks, "
               "positions and teams are handled, and it's saved per league.")

    cookie = _udk_cookie()
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("⚡ Pull from UDK (stored login)", type="primary",
                     disabled=not cookie, use_container_width=True):
            with st.spinner("Scraping the UDK…"):
                got = udk.fetch_udk(cookie, reg, ctx["meta"].scoring)
            if got:
                _set(ctx, got)
                st.success(f"Pulled {len(got)} players from the UDK.")
            else:
                st.error("Couldn't scrape the UDK server-side (login/endpoint). "
                         "Use the bookmarklet + upload below instead.")
        if not cookie:
            st.caption("Add `udk_cookie` to secrets to enable server-side pull.")

    with st.expander("🔖 One-click UDK bookmarklet (no login needed)"):
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
        with st.expander(f"⚠️ {len(unmatched)} names didn't match — fix spelling & re-import"):
            st.write(", ".join(unmatched))
    st.download_button("⬇ Save my rankings (.json)", json.dumps(ranks),
                       file_name="my_rankings.json", mime="application/json")
    st.dataframe(pd.DataFrame([{"Rk": r["rank"], "Tier": r["tier"], "Player": r["name"],
                                "Matched": "✓" if r.get("pid") else "—"} for r in ranks]),
                 hide_index=True, use_container_width=True, height=320)
