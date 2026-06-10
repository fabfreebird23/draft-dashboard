"""Retro pastel-synthwave theme: graffiti wordmark, soft neon grid + glows on a
light lavender/sunset field, light panels with dark text, plus shared CSS for the
custom HTML surfaces (leaderboard, team cards, draft board) and Sleeper headshots.
"""
from __future__ import annotations

SLEEPER_IMG = "https://sleepercdn.com/content/nfl/players/thumb/{pid}.jpg"
SLEEPER_DEFAULT = "https://sleepercdn.com/images/v2/icons/player_default.webp"
ESPN_IMG = "https://a.espncdn.com/i/headshots/nfl/players/full/{eid}.png"

# sleeper_pid -> espn player/headshot id, populated by app at startup
# (set_espn_ids). Lets newly-added rookies — who have no Sleeper photo — fall
# back to ESPN's headshot before the generic silhouette.
_ESPN_BY_PID: dict = {}


def set_espn_ids(mapping: dict) -> None:
    _ESPN_BY_PID.clear()
    _ESPN_BY_PID.update({str(k): str(v) for k, v in mapping.items() if v})

# Pastel palette
PINK = "#ff4f9d"
PURPLE = "#7b5cff"
TEAL = "#16b8a6"
CYAN = "#2bb5e8"
AMBER = "#f5a524"
RED = "#e5484d"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Anton&family=Oswald:wght@400;500;600;700&family=Rubik+Wet+Paint&display=swap');

:root{
  --bg:#f4f0fb; --panel:#ffffff; --panel2:#f7f3fe;
  --pink:#ff4f9d; --purple:#7b5cff; --teal:#16b8a6; --cyan:#2bb5e8; --amber:#f5a524; --red:#e5484d;
  --ink:#2b2540; --muted:#8a83a6; --line:#e4ddf2;
}

/* warm pastel sunset-synthwave field */
.stApp{
  background-color:#fbf3ec;
  background-image:
    radial-gradient(74% 56% at 3% -8%, rgba(255,116,134,.30), transparent 58%),
    radial-gradient(70% 52% at 105% -6%, rgba(54,196,206,.26), transparent 58%),
    radial-gradient(72% 40% at 50% 86%, rgba(255,176,92,.24), transparent 66%),
    radial-gradient(130% 130% at 50% 42%, transparent 56%, rgba(150,90,120,.09)),
    linear-gradient(rgba(196,128,120,.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(196,128,120,.06) 1px, transparent 1px),
    linear-gradient(180deg,#fef8f1,#f6eae1);
  background-size:auto,auto,auto,auto,48px 48px,48px 48px,auto;
  background-attachment:fixed;
}
html, body, [class*="css"]{ font-family:'Oswald', sans-serif; color:var(--ink); }

/* faint CRT scanlines */
.stApp::before{ content:""; position:fixed; inset:0; pointer-events:none; z-index:9998;
  background:repeating-linear-gradient(to bottom, transparent 0 2px, rgba(80,60,120,.045) 2px 3px); }
/* soft glowing perspective floor grid, behind content */
.stApp::after{ content:""; position:fixed; left:-25%; right:-25%; bottom:-2vh; height:48vh;
  z-index:-1; pointer-events:none; opacity:.55;
  background-image:
    repeating-linear-gradient(90deg, rgba(255,116,134,.55) 0 1px, transparent 1px 7%),
    repeating-linear-gradient(0deg, rgba(54,196,206,.45) 0 1px, transparent 1px 20%);
  transform:perspective(32vh) rotateX(65deg); transform-origin:bottom center;
  -webkit-mask-image:linear-gradient(to top,#000 4%, transparent 72%);
  mask-image:linear-gradient(to top,#000 4%, transparent 72%);
  filter:drop-shadow(0 0 5px rgba(255,140,120,.35)); }

[data-testid="stHeader"]{ background:transparent; }
[data-testid="stSidebar"]{ background:rgba(255,255,255,.72); backdrop-filter:blur(4px);
  border-right:1px solid var(--line); }

/* headings */
h1,h2,h3{ font-family:'Anton', sans-serif !important; letter-spacing:1px; text-transform:uppercase; }
h1{ color:var(--pink); }
h2{ color:var(--purple); font-size:1.5rem; }
h3{ color:var(--ink); }

/* desktop density: wider content, tighter padding + vertical rhythm */
.block-container{ padding-top:2rem; padding-left:2.4rem; padding-right:2.4rem;
  max-width:100%; }
[data-testid="stVerticalBlock"]{ gap:.5rem; }
[data-testid="stHorizontalBlock"]{ gap:.7rem; }
[data-testid="stExpander"]{ border:none; }
[data-testid="stCaptionContainer"]{ font-size:11.5px; }
div[data-testid="stRadio"] label{ font-size:12px; }

/* graffiti wordmark — pink with teal retro offset */
.neon-logo{ font-family:'Rubik Wet Paint', cursive; color:var(--pink); line-height:1;
  text-shadow:0 0 6px rgba(255,79,157,.35), 3px 4px 0 rgba(43,181,232,.55);
  transform:rotate(-3deg); display:inline-block; }
.neon-tag{ font-family:'Oswald'; letter-spacing:5px; font-weight:700; font-size:11px;
  color:var(--purple); text-transform:uppercase; }

/* sidebar nav radio -> pastel pills */
[data-testid="stSidebar"] [role="radiogroup"] label{ border:1px solid var(--line); border-radius:6px;
  padding:6px 10px; margin-bottom:6px; background:#fff; transition:.15s; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover{ border-color:var(--pink); }
[data-testid="stSidebar"] [role="radiogroup"] label p{ font-weight:600; text-transform:uppercase; letter-spacing:.5px; font-size:13px;}

/* refined, compact buttons (desktop) — flat secondary, pink primary */
.stButton>button{ font-family:'Oswald'; font-weight:600; letter-spacing:.3px;
  border-radius:7px; padding:5px 13px; font-size:13px; transition:.12s; }
.stButton>button[kind="secondary"]{ background:#fff; color:var(--ink);
  border:1.5px solid var(--line); }
.stButton>button[kind="secondary"]:hover{ border-color:var(--pink); color:var(--pink); }
.stButton>button[kind="primary"],
.stButton>button[kind="primaryFormSubmit"]{ background:var(--pink); color:#fff; border:none; }
.stButton>button[kind="primary"]:hover{ background:var(--purple); }

/* per-position tier band */
.ptier{ font-family:'Anton'; font-size:9px; letter-spacing:1.5px; color:var(--purple);
  background:#f1ebfb; border-radius:4px; padding:2px 8px; margin:5px 0 2px; }

/* clickable best-available rows (scoped to keyed containers per position) */
[class*="_col_"] .stButton{ margin-bottom:2px; }
[class*="_col_"] .stButton>button{ width:100%; text-align:left; justify-content:flex-start;
  padding:3px 9px; font-size:12px; font-weight:600; min-height:0; line-height:1.35;
  border:1px solid #eee6f7; border-left-width:4px; border-radius:5px; background:#fff; }
[class*="_col_"] .stButton>button>div{ width:100%; text-align:left; }
[class*="_col_"] .stButton>button:hover{ background:#faf7ff; border-color:var(--pink);
  transform:none; }
[class*="_col_QB"] .stButton>button{ border-left-color:var(--amber); }
[class*="_col_RB"] .stButton>button{ border-left-color:var(--teal); }
[class*="_col_WR"] .stButton>button{ border-left-color:var(--cyan); }
[class*="_col_TE"] .stButton>button{ border-left-color:var(--pink); }
[class*="_col_ALL"] .stButton>button{ border-left-color:var(--purple); }

/* ---- shared custom tables ---- */
.neonwrap{ overflow-x:auto; border:1px solid var(--line); border-radius:10px;
  background:rgba(255,255,255,.78); backdrop-filter:blur(2px);
  box-shadow:0 10px 30px rgba(123,92,255,.12), 0 0 0 1px rgba(255,79,157,.06); }
table.lb{ width:100%; border-collapse:collapse; font-family:'Oswald'; font-size:14px; }
table.lb th{ background:#f1ebfb; color:var(--muted); text-transform:uppercase; letter-spacing:1px;
  font-size:11px; text-align:left; padding:8px 10px; border-bottom:2px solid var(--line); position:sticky; top:0; }
table.lb td{ padding:6px 10px; border-bottom:1px solid #efeaf8; }
table.lb tr:hover td{ background:#faf7ff; }
table.lb tr.kept td{ background:linear-gradient(90deg, rgba(22,184,166,.18), rgba(22,184,166,.04)); }
table.lb tr.kept td:first-child{ box-shadow:inset 3px 0 0 var(--teal); }
.lb .rk{ font-family:'Anton'; color:var(--pink); width:34px; text-align:center; }
.lb .pl{ font-weight:600; }
.lb .pos{ color:var(--muted); font-size:11px; font-weight:600; }
.lb .val{ font-family:'Anton'; color:var(--teal); text-align:right; }
.lb .num{ text-align:right; color:var(--ink); }
.lb .kept-badge{ color:#fff; background:var(--teal); font-weight:700; font-size:10px;
  padding:1px 6px; border-radius:3px; text-transform:uppercase; letter-spacing:.5px; }
.lb .rk-badge{ color:#fff; background:var(--purple); font-weight:700; font-size:10px;
  padding:1px 6px; border-radius:3px; text-transform:uppercase; letter-spacing:.5px; margin-left:4px; }
.lb .fa-tag{ color:var(--cyan); font-weight:600; font-size:12px; font-style:italic; }
table.lb tr.fa td{ background:rgba(43,181,232,.05); }
.hs{ width:30px; height:30px; border-radius:50%; object-fit:cover; vertical-align:middle;
  background:#efeaf8; border:1px solid var(--line); margin-right:8px; }
.posdot{ display:inline-block; width:6px;height:6px;border-radius:50%;margin-right:5px;vertical-align:middle;}
.p-QB{background:var(--amber);} .p-RB{background:var(--teal);} .p-WR{background:var(--cyan);} .p-TE{background:var(--pink);}

/* team cards */
.kcards{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
.kcard{ border:1px solid var(--line); border-top:3px solid var(--pink); border-radius:10px;
  background:#fff; padding:10px 12px; min-height:96px; box-shadow:0 6px 18px rgba(123,92,255,.10); }
.kcard h4{ font-family:'Anton'; font-size:15px; margin:0 0 6px; color:var(--purple); letter-spacing:.5px; }
.kcard .kp{ display:flex; align-items:center; font-size:13px; padding:2px 0; }
.kcard .kp img{ width:22px;height:22px;border-radius:50%;margin-right:6px;object-fit:cover;background:#efeaf8; }
.kcard .kp .rd{ margin-left:auto; color:var(--teal); font-weight:700; }
.kcard .empty{ color:var(--muted); font-style:italic; font-size:12px; }
.kcard .rk-tag{ color:var(--amber); font-size:9px; font-weight:700; margin-left:4px; }

/* draft board */
table.dboard{ width:100%; border-collapse:collapse; table-layout:fixed; font-family:'Oswald'; font-size:12px; }
table.dboard th{ background:#f1ebfb; color:var(--ink); text-align:center; font-size:11px; padding:5px;
  border:1px solid var(--line); text-transform:uppercase; letter-spacing:.5px; }
.dbcell{ border:1px solid #efeaf8; padding:3px 4px; vertical-align:top; height:48px; }
/* higher specificity so our padding beats Streamlit's default table td padding */
table.dboard td.dbcell{ padding:3px 4px; }
.dbpick{ color:#b6aecd; font-size:9px; white-space:nowrap; }
.db-base{ background:#faf7ff; color:#9089ab; }
.db-traded{ background:rgba(255,79,157,.16); color:#b21e6b; }
.db-keep{ background:rgba(22,184,166,.20); color:#0c7a6e; box-shadow:inset 0 0 0 1px rgba(22,184,166,.45); }
.db-conflict{ background:rgba(229,72,77,.18); color:#b3232a; box-shadow:inset 0 0 0 1px rgba(229,72,77,.45); }
.db-rd{ background:#f1ebfb; color:var(--purple); font-family:'Anton'; text-align:center; white-space:nowrap; }

/* classic basketball sneaker icon for section headers */
.sneak{ display:inline-block; vertical-align:middle; height:52px; margin:0 14px 6px 0;
  filter:drop-shadow(2px 4px 4px rgba(80,40,70,.32)); }
.lb .pos{ white-space:nowrap; }

/* top navigation bar */
.kbar{ display:flex; align-items:center; gap:16px; flex-wrap:wrap;
  padding-bottom:8px; margin-bottom:10px; border-bottom:1.5px solid var(--line); }
.khome{ text-decoration:none !important; line-height:1; }
.khome .neon-logo{ font-size:30px; margin:0; }
.topnav{ display:flex; gap:6px; flex-wrap:wrap; }
.navlink{ font-family:'Anton'; text-transform:uppercase; letter-spacing:1px; font-size:13px;
  color:var(--ink) !important; text-decoration:none !important; padding:6px 13px; border-radius:9px;
  border:1.5px solid var(--line); background:#fff; transition:.15s; white-space:nowrap; }
.navlink:hover{ border-color:var(--pink); color:var(--pink) !important; }
.navlink.active{ background:var(--pink); color:#fff !important; border-color:var(--pink); }

/* ---------- Draft Kit "war room" (FantasyPros-style) ---------- */
.dr-status{ display:flex; align-items:center; gap:18px; flex-wrap:wrap;
  background:linear-gradient(90deg,#241544,#3a1d63); color:#fff; border-radius:12px;
  padding:12px 20px; margin-bottom:14px; box-shadow:0 4px 16px rgba(80,40,120,.25); }
.dr-status .rd{ font-family:'Anton'; font-size:24px; line-height:1; color:#ff7ab8; }
.dr-status .rd small{ display:block; font-size:10px; letter-spacing:2px; color:#cdbff0; }
.dr-status .clk{ font-family:'Oswald'; font-weight:600; letter-spacing:.5px; font-size:15px; }
.dr-status .clk b{ color:#7be0d3; }
.dr-status .yours{ background:#16b8a6; color:#fff; padding:5px 14px; border-radius:8px;
  font-family:'Anton'; letter-spacing:1px; animation:drpulse 1.4s ease-in-out infinite; }
@keyframes drpulse{ 0%,100%{box-shadow:0 0 0 0 rgba(22,184,166,.5);} 50%{box-shadow:0 0 0 7px rgba(22,184,166,0);} }
.dr-h{ font-family:'Anton'; text-transform:uppercase; letter-spacing:1px; font-size:14px;
  color:var(--purple); margin:2px 0 6px; }
.dr-lineup .slot{ display:flex; align-items:center; gap:8px; background:#fff;
  border:1.5px solid var(--line); border-radius:9px; padding:7px 10px; margin-bottom:5px; }
.dr-lineup .slot .pos{ font-family:'Anton'; color:#fff; background:var(--purple); border-radius:6px;
  font-size:11px; padding:2px 7px; min-width:42px; text-align:center; }
.dr-lineup .slot .pos.FLEX{ background:#d98a00; } .dr-lineup .slot .pos.BN{ background:#9089ab; }
.dr-lineup .slot .nm{ font-size:13px; font-weight:600; }
.dr-lineup .slot.empty .nm{ opacity:.45; font-style:italic; font-weight:400; }
table.dr-avail{ width:100%; border-collapse:collapse; font-family:'Oswald'; }
table.dr-avail td{ padding:6px 9px; border-bottom:1px solid #efeaf8; font-size:13px; }
table.dr-avail td.r{ color:#b6aecd; width:26px; }
table.dr-avail td.a{ text-align:right; color:#8b86a0; white-space:nowrap; }
.dr-avail .tierband td{ background:#f1ebfb; font-family:'Anton'; font-size:10px; letter-spacing:2px;
  color:#7b5cff; padding:3px 9px; }
.dr-avail tr.rec td{ background:rgba(22,184,166,.10); box-shadow:inset 4px 0 0 #16b8a6; }
.dr-avail .recbadge{ background:#16b8a6; color:#fff; font-size:9px; padding:1px 6px; border-radius:5px;
  font-family:'Anton'; letter-spacing:.5px; margin-left:6px; }
.dr-avail .pp{ font-size:10px; color:#8b86a0; }
/* ---- redesigned, readable draft board ---- */
.dr-grid{ display:grid; gap:3px; font-family:'Oswald'; min-width:max-content; }
.dr-cell{ position:relative; font-size:11px; line-height:1.15; padding:5px 6px 5px 8px;
  border-radius:6px; background:#fbf9ff; min-height:46px; border:1px solid #ece5f8;
  overflow:hidden; display:flex; flex-direction:column; justify-content:center; }
.dr-cell .pk{ position:absolute; top:2px; right:4px; font-size:8px; color:#c3b8db; font-weight:600; }
.dr-cell .nm{ font-weight:700; color:var(--ink); white-space:nowrap; overflow:hidden;
  text-overflow:ellipsis; max-width:100%; }
.dr-cell .meta{ font-size:9px; color:#9089ab; font-weight:600; letter-spacing:.3px; }
/* position-colored left bar + tint */
.dr-cell.pos-QB{ background:rgba(245,165,36,.13); box-shadow:inset 4px 0 0 var(--amber); }
.dr-cell.pos-RB{ background:rgba(22,184,166,.13); box-shadow:inset 4px 0 0 var(--teal); }
.dr-cell.pos-WR{ background:rgba(43,181,232,.13); box-shadow:inset 4px 0 0 var(--cyan); }
.dr-cell.pos-TE{ background:rgba(255,79,157,.12); box-shadow:inset 4px 0 0 var(--pink); }
.dr-cell.pos-K{ background:rgba(144,137,171,.13); box-shadow:inset 4px 0 0 #9089ab; }
.dr-cell.pos-DST,.dr-cell.pos-D{ background:rgba(123,92,255,.12); box-shadow:inset 4px 0 0 var(--purple); }
.dr-cell.me{ outline:2px solid rgba(22,184,166,.45); outline-offset:-2px; }
.dr-cell.now{ box-shadow:0 0 0 3px var(--pink), 0 4px 14px rgba(255,79,157,.35);
  animation:drpulse 1.4s ease-in-out infinite; }
.dr-cell.empty{ background:#f7f4fd; color:#cabfe2; min-height:46px; }
.dr-cell.empty .nm{ color:#cabfe2; font-weight:400; font-style:italic; font-size:10px; }
.dr-colhead{ font-family:'Anton'; font-size:10px; text-align:center; color:var(--ink);
  text-transform:uppercase; padding:5px 3px; background:#f1ebfb; border-radius:6px 6px 0 0;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; letter-spacing:.5px; }
.dr-colhead.me{ background:var(--teal); color:#fff; }
.dr-colhead.rd{ background:var(--purple); color:#fff; font-size:11px; }
.dr-rdlabel{ display:flex; align-items:center; justify-content:center; font-family:'Anton';
  font-size:12px; color:#fff; background:var(--purple); border-radius:6px; }

/* ---- value / context chips on the available board ---- */
.dr-avail .posrank{ display:inline-block; font-family:'Anton'; font-size:9px; color:#fff;
  border-radius:4px; padding:1px 5px; margin-right:5px; vertical-align:middle; }
.posrank.QB{ background:var(--amber);} .posrank.RB{ background:var(--teal);}
.posrank.WR{ background:var(--cyan);} .posrank.TE{ background:var(--pink);}
.posrank.K{ background:#9089ab;} .posrank.DST,.posrank.D{ background:var(--purple);}
.dr-avail .vchip{ font-size:9px; font-weight:700; padding:1px 5px; border-radius:4px; margin-left:6px; }
.vchip.value{ background:rgba(22,184,166,.18); color:#0c7a6e; }
.vchip.reach{ background:rgba(229,72,77,.15); color:#b3232a; }
.dr-avail .bye{ font-size:9px; color:#b6aecd; }

/* keeper cells on the board */
.dr-cell.kept{ outline:2px dashed rgba(217,138,0,.8); outline-offset:-2px; }
.dr-cell .ktag{ position:absolute; top:2px; left:5px; font-family:'Anton'; font-size:8px;
  color:#fff; background:#d98a00; border-radius:3px; padding:0 3px; letter-spacing:.5px; }

/* war-room alert chips */
.dr-alerts{ display:flex; gap:8px; flex-wrap:wrap; margin:0 0 10px; }
.dr-alerts .alert{ font-family:'Oswald'; font-weight:700; font-size:12px; padding:4px 11px;
  border-radius:14px; }
.alert.cliff{ background:rgba(229,72,77,.14); color:#b3232a; border:1.5px solid rgba(229,72,77,.4); }
.alert.run{ background:rgba(245,165,36,.16); color:#9a6500; border:1.5px solid rgba(245,165,36,.5); }
.alert.need{ background:rgba(22,184,166,.14); color:#0c7a6e; border:1.5px solid rgba(22,184,166,.4); }
.dr-rec{ background:linear-gradient(90deg,rgba(22,184,166,.14),rgba(22,184,166,.03));
  border:1.5px solid rgba(22,184,166,.4); border-radius:10px; padding:8px 12px; margin-bottom:8px;
  font-family:'Oswald'; font-size:13px; }
.dr-rec b{ color:#0c7a6e; } .dr-rec .why{ color:#6a6580; font-size:12px; }

/* roster strength vs league */
.rs{ display:flex; flex-direction:column; gap:3px; margin-bottom:8px; }
.rs-row{ display:flex; align-items:center; gap:7px; font-family:'Oswald'; font-size:12px;
  padding:2px 6px; border-radius:6px; }
.rs-row.me{ background:rgba(22,184,166,.14); font-weight:700; }
.rs-rk{ width:16px; color:#b6aecd; font-family:'Anton'; font-size:11px; text-align:center; }
.rs-nm{ width:96px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rs-bar{ flex:1; height:9px; background:#efeaf8; border-radius:5px; overflow:hidden; }
.rs-bar i{ display:block; height:100%; background:linear-gradient(90deg,var(--teal),var(--cyan)); }
.rs-row.me .rs-bar i{ background:linear-gradient(90deg,var(--pink),var(--purple)); }
.rs-val{ width:34px; text-align:right; color:#8b86a0; font-weight:600; }

/* by-position cheat sheet */
.dr-cheat{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; }
.cheat-col{ border:1px solid var(--line); border-radius:9px; background:rgba(255,255,255,.7);
  overflow:hidden; }
.cheat-head{ font-family:'Anton'; color:#fff; text-align:center; padding:4px; font-size:13px;
  letter-spacing:1px; }
.cheat-head.QB{ background:var(--amber);} .cheat-head.RB{ background:var(--teal);}
.cheat-head.WR{ background:var(--cyan);} .cheat-head.TE{ background:var(--pink);}
.cheat-row{ display:flex; align-items:center; gap:5px; padding:4px 6px; font-family:'Oswald';
  font-size:11.5px; border-bottom:1px solid #f1ecfa; }
.cheat-row .chs{ width:20px; height:20px; border-radius:50%; object-fit:cover; background:#efeaf8; }
.cheat-row .cn{ font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:1; }
.cheat-row .ca{ color:#9089ab; font-size:10px; white-space:nowrap; }

/* pick queue */
.dr-queue{ display:flex; flex-direction:column; gap:3px; }
.q-row{ display:flex; align-items:center; gap:6px; font-family:'Oswald'; font-size:12.5px;
  padding:3px 7px; border:1px solid var(--line); border-radius:7px; background:#fff; }
.q-row.gone{ opacity:.4; text-decoration:line-through; }
.q-row .qn{ font-weight:600; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.q-row .qp{ font-size:10px; color:#8b86a0; }

/* roster-needs strip */
.dr-needs{ display:flex; gap:6px; flex-wrap:wrap; margin:2px 0 8px; }
.dr-needs .need{ font-family:'Oswald'; font-weight:600; font-size:11px; padding:3px 9px;
  border-radius:14px; border:1.5px solid var(--line); background:#fff; }
.dr-needs .need.open{ border-color:var(--pink); color:var(--pink); }
.dr-needs .need.full{ opacity:.5; text-decoration:line-through; }

/* ---------------- mobile ---------------- */
@media (max-width: 640px){
  .neon-logo{ font-size:40px !important; }
  .neon-tag{ font-size:8px; letter-spacing:3px; }
  .kbar{ gap:8px; }
  .khome .neon-logo{ font-size:24px !important; }
  .navlink{ font-size:11px; padding:5px 9px; letter-spacing:.5px; }
  h1{ font-size:1.5rem !important; }
  h2{ font-size:1.25rem !important; }
  h3{ font-size:1.15rem !important; }
  .sneak{ height:30px; margin:0 8px 2px 0; }
  .block-container{ padding-left:.6rem !important; padding-right:.6rem !important; padding-top:2.5rem !important; }
  /* flow the tall scroll panels with the page (no nested scrollbox) */
  .neonwrap{ max-height:none !important; }

  /* compact custom tables */
  table.lb{ font-size:11px; }
  table.lb th{ padding:5px 5px; font-size:8px; }
  table.lb td{ padding:4px 5px; }
  .hs{ width:22px; height:22px; margin-right:5px; }
  .lb .rk{ width:20px; }
  .lb .kept-badge, .lb .rk-badge{ font-size:8px; padding:1px 4px; margin-left:3px; }
  /* value board: drop Keep Yr (5) + ADP (7) so the essentials fit without scroll */
  .lb-value th:nth-child(5), .lb-value td:nth-child(5),
  .lb-value th:nth-child(7), .lb-value td:nth-child(7){ display:none; }
  /* rookies: drop the redundant Consensus ADP column (6) */
  .lb-rook th:nth-child(6), .lb-rook td:nth-child(6){ display:none; }
  /* title odds: drop Top Keepers (8) so the line fits without tall rows */
  .lb-odds th:nth-child(8), .lb-odds td:nth-child(8){ display:none; }

  /* team cards stack two-up */
  .kcards{ grid-template-columns:1fr 1fr; gap:8px; }
  .kcard{ min-height:auto; padding:8px 9px; }
  .kcard h4{ font-size:13px; }
  .kcard .kp{ font-size:12px; }

  /* draft board: tiny + horizontal scroll */
  table.dboard{ font-size:9px; }
  table.dboard th{ padding:3px 2px; font-size:8px; }
  .dbcell{ height:auto; }
  table.dboard td.dbcell{ padding:2px 3px; }   /* win over Streamlit's td padding */
  .db-rd{ font-size:10px; }                      /* keep two-digit rounds legible */
}
</style>
"""


def crt(key: str = "top") -> str:
    """Section-header icon. The standalone app ships no sneaker art, so this is a
    no-op kept for call-site compatibility with the original draft-kit code."""
    return ""


def headshot(pid: str) -> str:
    return SLEEPER_IMG.format(pid=pid)


def img_tag(pid: str, cls: str = "hs") -> str:
    """Headshot <img>. Source is picked server-side because Streamlit's HTML
    sanitizer strips `onerror`, so an in-browser fallback chain can't run.

    ESPN's headshots cover both veterans and incoming rookies (where Sleeper's
    CDN often has no photo), so we use ESPN whenever we have an id for the
    player and fall back to the Sleeper thumb otherwise.
    """
    eid = _ESPN_BY_PID.get(str(pid))
    src = ESPN_IMG.format(eid=eid) if eid else headshot(pid)
    return f'<img class="{cls}" src="{src}" loading="lazy">'


def logo_html(size: int = 52, tag: str | None = "Mock + Live Draft") -> str:
    t = f'<div class="neon-tag">{tag}</div>' if tag else ""
    return (f'<div class="neon-logo" style="font-size:{size}px;">DRAFT ROOM</div>{t}')


def inject(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
