"""Hand a player from this board to the Sleeper draft room.

Sleeper's API cannot make picks — their docs are explicit that it is "a read-only
HTTP API" and that "you cannot modify contents via this API". No endpoint submits
a pick. FantasyPros lives under the same constraint: their "Draft on Sleeper"
button only works with their browser extension installed, because the click has
to happen inside the draft room page.

So the pick travels by CLIPBOARD, and a userscript in the Sleeper tab does the
rest (assets/bloody-sunday-sleeper.user.js). The dashboard is on streamlit.app and
the draft room is on sleeper.com — different origins, so localStorage,
BroadcastChannel and postMessage are all off the table, and a relay would mean
storing a Sleeper credential somewhere, which is the one thing worth refusing.
The clipboard costs a keystroke and holds no secrets.
"""
from __future__ import annotations

import json

import streamlit as st

_HEIGHT = 58   # room for the fallback input + its hint


def copy_button(name: str, key: str, label: str = "Draft on Sleeper",
                height: int = _HEIGHT) -> None:
    """A button that puts `name` on the clipboard, styled like the rest of the app.

    Deliberately a raw component rather than st.button: st.button round-trips to
    the server, and the clipboard write has to happen inside the click's own event
    handler or the browser drops it as un-gestured. It also means no rerun, which
    matters on a screen we just spent two commits keeping still.

    Tries the async Clipboard API first and falls back to execCommand, because
    the component iframe is not always granted clipboard-write.
    """
    payload = json.dumps(str(name or ""))
    st.components.v1.html(f"""
<style>
  :root{{color-scheme:dark}}
  html,body{{margin:0;background:transparent}}
  #b{{width:100%;box-sizing:border-box;font:700 12.5px/1 -apple-system,BlinkMacSystemFont,
     "Segoe UI",sans-serif;padding:9px 10px;border-radius:8px;cursor:pointer;
     background:#e02557;border:1px solid #e02557;color:#fff;transition:filter .12s}}
  #b:hover{{filter:brightness(1.12)}}
  #b.ok{{background:#12312a;border-color:#1f5a46;color:#7fd8b4}}
  #f{{width:100%;box-sizing:border-box;font:700 12.5px/1 inherit;padding:9px 10px;border-radius:8px;
     background:#232022;border:1px solid #ff336c;color:#f2eef0}}
  #h{{font:600 10.5px/1.3 -apple-system,sans-serif;color:#f0b357;margin-top:3px}}
</style>
<button id="b">{label}</button>
<script>
const NAME = {payload}, b = document.getElementById('b'), was = b.textContent;
function legacy(t){{
  const a = document.createElement('textarea');
  a.value = t; a.style.position = 'fixed'; a.style.opacity = '0';
  document.body.appendChild(a); a.select();
  let ok = false; try {{ ok = document.execCommand('copy'); }} catch (e) {{}}
  a.remove(); return ok;
}}
/* If the write is refused — a locked-down browser, a missing gesture, an iframe
   without clipboard-write — do NOT leave a dead end mid-draft. Swap in the name,
   already selected, so Cmd+C still works and the pick still moves. */
function fallback(){{
  const i = document.createElement('input');
  i.readOnly = true; i.value = NAME; i.id = 'f';
  b.replaceWith(i); i.focus(); i.select();
  const h = document.createElement('div'); h.id = 'h';
  h.textContent = 'Clipboard blocked \\u2014 press \\u2318C';
  document.body.appendChild(h);
}}
b.onclick = async () => {{
  let ok = false;
  try {{ await navigator.clipboard.writeText(NAME); ok = true; }} catch (e) {{ ok = legacy(NAME); }}
  if (!ok) {{ fallback(); return; }}
  b.classList.add('ok');
  b.textContent = '\\u2713 Copied \\u2014 \\u2325\\u21e7V in Sleeper';
  setTimeout(() => {{ b.textContent = was; b.classList.remove('ok'); }}, 2600);
}};
</script>""", height=height)


def installed() -> bool:
    """Whether he has said the userscript is in place.

    Purely a UI hint — the dashboard cannot see into the Sleeper tab, and pretending
    otherwise would be worse than asking once.
    """
    return bool(st.session_state.get("bs_userscript_ready"))


def setup_note() -> None:
    """One-time install instructions, shown until dismissed."""
    with st.expander("Set up one-click drafting on Sleeper", expanded=not installed()):
        st.markdown(
            "Sleeper has **no API for making picks** — their API is read-only, and "
            "FantasyPros needs a browser extension for the same reason. This does the "
            "same job with a userscript.\n\n"
            "1. Install **Tampermonkey** (Chrome/Safari/Firefox).\n"
            "2. Add `assets/bloody-sunday-sleeper.user.js` from this repo.\n"
            "3. Open your Sleeper draft — a panel appears bottom-right.\n\n"
            "Then: hit **Draft on Sleeper** here, switch to the Sleeper tab, press "
            "**⌥⇧V**. It fills the search and highlights him; *you* press Sleeper's "
            "Draft button. Auto-confirm is available in the panel and off by default — "
            "a wrong click spends a real pick."
        )
        st.checkbox("Installed — stop reminding me", key="bs_userscript_ready")
