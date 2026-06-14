"""Render real component HTML under the dark theme into a static page, so we can
screenshot it (Streamlit's live socket blocks screenshots) and audit dark-mode
readability in one shot. Writes scripts/dark_check.html."""
import re
from draftkit import players, config, rankings as R, theme
from draftkit.adp import consensus
from draftkit.ui import components as C

season = config.current_season()
reg = players.build_registry(season)
pool = R.adp_pool(reg, consensus.load(season))
slots = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "FLEX", "BN", "BN"]

def pid_for(pos, i=0):
    hits = [p["pid"] for p in pool if reg.meta(p["pid"]).position == pos]
    return hits[i] if len(hits) > i else hits[0]

my = [pid_for("RB"), pid_for("RB", 1), pid_for("WR"), pid_for("WR", 1),
      pid_for("TE"), pid_for("WR", 2)]
n, rounds = 8, 3
slot_names = ["You", "Bri", "Cliff", "Dre", "Eli", "Fitz", "Gus", "Hank"]
board = {ov: pool[ov - 1]["pid"] for ov in range(1, 17)}
owner = lambda ov: C.snake(n)(ov - 1)
need_map = {s: {"QB", "TE"} for s in range(n)}
adp_rank = lambda name, posn="": next((p["adp"] for p in pool if p["name"] == name), None)
survival = lambda pid: C.survival_pct(adp_rank(reg.meta(pid).name), 14)

blocks = {
    "Lineup (My Team)": C.lineup_html(my, slots, reg),
    "Roster needs": C.roster_needs_html(my, slots, reg),
    "Roster balance": C.roster_balance_html(my, slots, reg),
    "Draft grid": C.grid_html(board, n, slot_names, 0, 3, rounds, reg, owner_fn=owner),
    "Cheat sheet": C.cheat_sheet_html([{"pid": p["pid"], "name": p["name"],
                                        "tier": (i // 6) + 1, "rank": i + 1}
                                       for i, p in enumerate(pool[:40])], reg,
                                      survival_fn=survival),
    "Picks feed": C.picks_feed_html(board, 5, n, rounds, slot_names, 0, owner,
                                    need_map, reg, predictions={6: pool[20]["pid"]}),
    "Run banner": C.run_banner_html([{"pid": p["pid"], "name": p["name"], "tier": 2,
                                      "rank": i + 1} for i, p in enumerate(pool[:12])],
                                     ["RB", "WR", "RB", "RB", "RB"], 14, adp_rank, reg,
                                     needs={"RB"}),
    "Waiver buzz": C.buzz_list_html([{"pid": p["pid"], "name": p["name"]} for p in pool[:8]],
                                    reg, {reg.meta(pool[0]["pid"]).sleeper_pid: {"add": 9100}}),
}

style = theme.CSS + theme.DARK            # light base + dark overrides (dark wins)
style = re.sub(r"</?style>", "", style)   # strip the <style> wrappers; we add our own
sections = "".join(
    f'<h3 style="color:#9fb2cc;font:700 12px Inter;margin:18px 0 6px">{title}</h3>'
    f'<div class="dr_panel_x" style="max-width:560px">{html}</div>'
    for title, html in blocks.items())
out = (f'<!doctype html><html><head><meta charset="utf-8"><style>{style}\n'
       f'body{{background:#0e1424;padding:20px;}}</style></head>'
       f'<body class="dark">{sections}</body></html>')
open("scripts/dark_check.html", "w").write(out)
print("wrote scripts/dark_check.html with", len(blocks), "blocks")
