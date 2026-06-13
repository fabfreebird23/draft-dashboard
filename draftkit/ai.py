"""AI player outlook + draft-room Q&A, powered by the Claude API.

This is the optional "Coach AI" layer (like FantasyPros' player modal): a short
draft-day outlook paragraph for the spotlighted player, plus a free-text Q&A box
to ask anything about him. It degrades gracefully — with no Anthropic API key
configured the spotlight simply omits the AI section, and the rest of the app is
unaffected.

The key is read from Streamlit secrets (`anthropic_api_key`) or the
`ANTHROPIC_API_KEY` environment variable. We never write or prompt for it here —
the user supplies it in `.streamlit/secrets.toml` or the hosted app's Secrets.

Outlooks are cached per (player, season, scoring, fact-fingerprint) so a given
card costs one request, not one-per-rerun. The model leans on its own football
knowledge (rosters, depth charts, situations) and grounds tone with the live
draft facts we pass in (ADP, tier, value rank, age/experience, injury).
"""
from __future__ import annotations

import hashlib
import os
from typing import Dict, List, Optional

_MODEL = "claude-opus-4-8"
_CLIENT = None  # lazily constructed anthropic.Anthropic
_OUTLOOK_CACHE: Dict[str, str] = {}

_SYSTEM = (
    "You are a sharp, concise fantasy-football draft analyst helping a manager who "
    "is on the clock. You know current NFL rosters, depth charts, coaching changes, "
    "and player situations. Be specific and honest — name the real upside and the "
    "real risk. No hedging filler, no restating the question, no markdown headers. "
    "Write in plain prose. Respond ONLY with the answer itself — do not narrate your "
    "reasoning or process."
)


def _api_key() -> Optional[str]:
    """Resolve the Anthropic key from Streamlit secrets, then env. Never raises."""
    try:
        import streamlit as st

        # st.secrets access raises if no secrets file exists — guard it.
        try:
            key = st.secrets.get("anthropic_api_key")  # type: ignore[attr-defined]
        except Exception:
            key = None
        if key:
            return str(key)
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY") or None


def available() -> bool:
    """True when an API key is configured and the SDK is importable."""
    if not _api_key():
        return False
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False
    return True


def _client():
    global _CLIENT
    if _CLIENT is None:
        import anthropic

        _CLIENT = anthropic.Anthropic(api_key=_api_key())
    return _CLIENT


def _facts_block(pm, facts: Dict[str, object]) -> str:
    """Render the structured draft facts we hand the model as grounding."""
    lines = [f"Player: {pm.name} — {pm.position}, {pm.team or 'FA'}"]
    label = {
        "season": "Context season",
        "scoring": "Scoring",
        "adp": "Consensus ADP",
        "overall": "Overall board rank",
        "pos_rank": "Positional rank",
        "tier": "Tier",
        "value_rank": "Our value rank (VORP)",
        "proj": "Projected points",
        "verdict": "Grab/wait read",
        "age": "Age",
        "years_exp": "NFL seasons",
        "injury": "Injury note",
        "bye": "Bye week",
    }
    for key, lbl in label.items():
        val = facts.get(key)
        if val not in (None, "", "None"):
            lines.append(f"{lbl}: {val}")
    return "\n".join(lines)


def _call(messages: List[dict], max_tokens: int) -> str:
    resp = _client().messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        thinking={"type": "disabled"},
        system=_SYSTEM,
        messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def outlook(pm, facts: Dict[str, object]) -> str:
    """A 2–3 sentence draft-day outlook for `pm`. Cached per fact-fingerprint."""
    block = _facts_block(pm, facts)
    fp = hashlib.sha1(f"{_MODEL}|{block}".encode()).hexdigest()
    if fp in _OUTLOOK_CACHE:
        return _OUTLOOK_CACHE[fp]
    prompt = (
        "Give a 2-3 sentence draft outlook for this player for the upcoming season. "
        "Cover his role/situation, the case to draft him here, and the main risk. "
        "End with one short clause on whether he's a value, fair, or reach at this ADP.\n\n"
        f"{block}"
    )
    text = _call([{"role": "user", "content": prompt}], max_tokens=400)
    _OUTLOOK_CACHE[fp] = text
    return text


def ask(pm, facts: Dict[str, object], question: str,
        history: Optional[List[dict]] = None) -> str:
    """Answer a manager's free-text question about `pm`. `history` is prior
    [{role, content}] turns for this player so follow-ups keep context."""
    block = _facts_block(pm, facts)
    msgs: List[dict] = []
    if not history:
        # Seed the first turn with the grounding facts.
        msgs.append({
            "role": "user",
            "content": (f"Here are the draft facts for {pm.name}:\n{block}\n\n"
                        f"Question: {question}"),
        })
    else:
        msgs.extend(history)
        msgs.append({"role": "user", "content": question})
    return _call(msgs, max_tokens=700)
