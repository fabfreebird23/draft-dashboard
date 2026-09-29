"""FAAB left is budget minus what HE has spent — read from the key callers use."""
from types import SimpleNamespace

from draftkit import inseason


def test_faab_reports_spend_by_owner(monkeypatch):
    monkeypatch.setattr(inseason.api, "get_league",
                        lambda lid: {"settings": {"waiver_budget": 100}})
    monkeypatch.setattr(inseason.api, "get_rosters", lambda lid: [
        {"owner_id": "me", "settings": {"waiver_budget_used": 6}},
        {"owner_id": "them", "settings": {"waiver_budget_used": 40}},
    ])
    fa = inseason.faab(SimpleNamespace(platform="sleeper", league_id="1"))
    # the exact expression every screen uses
    left = fa["budget"] - int((fa.get("by_owner") or {}).get("me", 0) or 0)
    assert left == 94
    assert fa["by_owner"] == fa["spent"]
