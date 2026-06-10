"""Clean hybrid draft theme — FantasyPros' light, tabular layout with Draft
Sharks' value badges and war-room intel. Restrained blue/green accents, system
fonts, position color-coding, plus shared CSS for the custom draft surfaces and
player headshots."""
from __future__ import annotations

SLEEPER_IMG = "https://sleepercdn.com/content/nfl/players/thumb/{pid}.jpg"
SLEEPER_DEFAULT = "https://sleepercdn.com/images/v2/icons/player_default.webp"
ESPN_IMG = "https://a.espncdn.com/i/headshots/nfl/players/full/{eid}.png"

# sleeper_pid -> espn player/headshot id, populated by app at startup.
_ESPN_BY_PID: dict = {}


def set_espn_ids(mapping: dict) -> None:
    _ESPN_BY_PID.clear()
    _ESPN_BY_PID.update({str(k): str(v) for k, v in mapping.items() if v})


# accent palette
BLUE = "#1f4e9b"
GREEN = "#1c8a4d"
NAVY = "#16263f"

CSS = """
<style>
:root{
  --bg:#eef1f5; --panel:#ffffff; --panel2:#fafbfc; --line:#e3e8ef; --line2:#eef1f5;
  --ink:#1d2733; --muted:#7b8694; --mut2:#9aa4b1;
  --blue:#1f4e9b; --green:#1c8a4d; --red:#d23b3b; --amber:#e08a1e;
  --qb:#d23b3b; --rb:#2e9e5b; --wr:#2f72c4; --te:#e08a1e; --k:#7a7f87; --dst:#6f5bd0;
}
.stApp{ background:var(--bg); }
html,body,[class*="css"]{ font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;
  color:var(--ink); font-size:13px; }
[data-testid="stHeader"]{ background:transparent; }
[data-testid="stSidebar"]{ background:#fff; border-right:1px solid var(--line); }

/* layout density (desktop) */
.block-container{ padding:1.4rem 2rem 2rem; max-width:100%; }
[data-testid="stVerticalBlock"]{ gap:.45rem; }
[data-testid="stHorizontalBlock"]{ gap:.8rem; }
[data-testid="stExpander"]{ border:none; }
[data-testid="stCaptionContainer"]{ font-size:11px; color:var(--mut2); }

h1,h2,h3{ font-weight:800; letter-spacing:-.2px; }
h1{ color:var(--blue); } h2{ color:var(--ink); font-size:1.35rem; } h3{ font-size:1.05rem; }
.neon-logo{ font-weight:900; font-size:inherit; color:var(--blue); letter-spacing:-.5px;
  display:inline-block; }
.neon-logo::first-letter{ color:var(--green); }
.neon-tag{ font-weight:700; font-size:10px; letter-spacing:2px; color:var(--mut2);
  text-transform:uppercase; }

/* buttons: flat, compact; green primary */
.stButton>button{ font-weight:700; font-size:12.5px; border-radius:7px; padding:5px 14px;
  transition:.12s; }
.stButton>button[kind="secondary"]{ background:#fff; color:var(--ink); border:1.5px solid var(--line); }
.stButton>button[kind="secondary"]:hover{ border-color:var(--blue); color:var(--blue); }
.stButton>button[kind="primary"],.stButton>button[kind="primaryFormSubmit"]{
  background:var(--green); color:#fff; border:none; }
.stButton>button[kind="primary"]:hover{ background:#15703d; }
div[data-testid="stRadio"] label{ font-size:12px; }

/* nav styled as underline tabs (persisted radio) */
[class*="navbar"]{ margin-bottom:10px; }
[class*="navbar"] [role="radiogroup"]{ gap:2px; border-bottom:2px solid var(--line); }
[class*="navbar"] [role="radiogroup"] label{ padding:9px 18px; font-weight:800; font-size:14px;
  color:var(--muted); cursor:pointer; margin-bottom:-2px; }
[class*="navbar"] [role="radiogroup"] label:hover{ color:var(--blue); }
[class*="navbar"] [role="radiogroup"] label>div:first-child{ display:none; }
[class*="navbar"] [role="radiogroup"] label:has(input:checked){ color:var(--blue);
  border-bottom:2px solid var(--blue); }

/* ---- shared card / scroll wrappers ---- */
.neonwrap{ overflow:auto; border:1px solid var(--line); border-radius:10px; background:#fff; }
.dr-h{ font-weight:800; font-size:11px; text-transform:uppercase; letter-spacing:.6px;
  color:var(--mut2); margin:6px 0 5px; }

/* ---- status bar ---- */
.dr-status{ display:flex; align-items:center; gap:16px; flex-wrap:wrap; background:#fff;
  border:1px solid var(--line); border-radius:10px; padding:10px 16px; margin-bottom:12px; }
.dr-status .rd{ font-weight:900; font-size:20px; color:var(--blue); line-height:1; }
.dr-status .rd small{ display:block; font-size:9px; letter-spacing:1.5px; color:var(--mut2); font-weight:700; }
.dr-status .clk{ font-weight:600; font-size:13px; color:var(--muted); }
.dr-status .clk b{ color:var(--ink); }
.dr-status .yours{ background:#e9f8ef; color:var(--green); border:1px solid #b7e6c9;
  padding:5px 14px; border-radius:20px; font-weight:800; }

/* ---- My Team lineup ---- */
.dr-lineup .slot{ display:flex; align-items:center; gap:8px; background:#fff;
  border:1px solid var(--line); border-radius:8px; padding:6px 11px; margin-bottom:4px; }
.dr-lineup .slot .pos{ font-weight:800; color:#fff; background:#5b6b7f; border-radius:4px;
  font-size:10px; padding:2px 7px; min-width:40px; text-align:center; }
.dr-lineup .slot .pos.QB{ background:var(--qb);} .dr-lineup .slot .pos.RB{ background:var(--rb);}
.dr-lineup .slot .pos.WR{ background:var(--wr);} .dr-lineup .slot .pos.TE{ background:var(--te);}
.dr-lineup .slot .pos.FLEX{ background:#6f5bd0; } .dr-lineup .slot .pos.BN{ background:#aab3bf; }
.dr-lineup .slot .nm{ font-size:13px; font-weight:600; }
.dr-lineup .slot.empty .nm{ color:var(--mut2); font-style:italic; font-weight:400; }

/* ---- needs / alerts / rec ---- */
.dr-needs{ display:flex; gap:6px; flex-wrap:wrap; margin:2px 0 8px; }
.dr-needs .need{ font-weight:700; font-size:11px; padding:3px 10px; border-radius:14px;
  border:1.5px solid var(--line); background:#fff; }
.dr-needs .need.open{ border-color:var(--red); color:var(--red); }
.dr-needs .need.full{ color:var(--mut2); border-color:var(--line); }
.dr-alerts{ display:flex; gap:8px; flex-wrap:wrap; margin:0 0 9px; }
.dr-alerts .alert{ font-weight:700; font-size:12px; padding:4px 11px; border-radius:8px; }
.alert.cliff{ background:#fdecec; color:var(--red); border:1px solid #f5c2c2; }
.alert.run{ background:#fff3e6; color:#b3650a; border:1px solid #f6d3a8; }
.alert.need{ background:#e9f1fb; color:var(--blue); border:1px solid #c2d6f0; }
.dr-rec{ background:#f3f9f5; border:1px solid #c7e6d2; border-left:4px solid var(--green);
  border-radius:8px; padding:8px 13px; margin-bottom:9px; font-size:13px; }
.dr-rec b{ color:var(--green); } .dr-rec .why{ color:var(--muted); }

/* ---- pick predictor ---- */
.dr-predict{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:8px 10px;
  margin-bottom:9px; }
.pp-row{ display:flex; align-items:center; gap:6px; padding:4px 4px; border-bottom:1px solid var(--line2);
  font-size:12px; border-left:4px solid var(--mut2); padding-left:7px; border-radius:0; margin-bottom:1px; }
.pp-row.pos-QB{ border-left-color:var(--qb);} .pp-row.pos-RB{ border-left-color:var(--rb);}
.pp-row.pos-WR{ border-left-color:var(--wr);} .pp-row.pos-TE{ border-left-color:var(--te);}
.pp-pk{ font-weight:800; color:var(--mut2); font-size:10px; min-width:26px; }
.pp-tm{ color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:80px; }
.pp-arrow{ color:var(--mut2); }
.pp-img{ width:20px; height:20px; border-radius:50%; object-fit:cover; background:var(--line2); }
.pp-pl{ font-weight:700; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pp-pos{ font-size:9px; font-weight:800; color:#fff; border-radius:3px; padding:1px 5px; }
.pp-pos.pos-QB{ background:var(--qb);} .pp-pos.pos-RB{ background:var(--rb);}
.pp-pos.pos-WR{ background:var(--wr);} .pp-pos.pos-TE{ background:var(--te);}
.dr-avail td.sv{ text-align:right; white-space:nowrap; }
.svbox{ display:inline-block; font-weight:800; font-size:11px; padding:3px 7px; border-radius:5px;
  min-width:36px; text-align:center; }

/* ---- player spotlight card (inspect) ---- */
.pcard{ background:#fff; border:1px solid var(--line); border-radius:11px; padding:11px 12px;
  margin:4px 0 10px; box-shadow:0 1px 3px rgba(0,0,0,.05); }
.pc-head{ display:flex; align-items:center; gap:11px; }
.pc-img{ width:52px; height:52px; border-radius:50%; object-fit:cover; background:#eef1f4;
  border:2px solid var(--line); }
.pc-name{ font-weight:800; font-size:16px; line-height:1.1; }
.pc-pos{ color:var(--muted); font-size:12px; font-weight:600; margin-top:1px; }
.pc-flag{ display:inline-block; font-size:11px; font-weight:800; margin-top:3px;
  padding:1px 7px; border-radius:20px; }
.pc-flag.ok{ background:#eaf7ef; color:#1c7a44; } .pc-flag.ques{ background:#fef6e7; color:#9a6b07; }
.pc-flag.out{ background:#fdecec; color:#b3261e; }
.pc-meta{ margin-top:8px; font-size:12px; color:var(--ink); font-weight:600; }
.pc-bio{ font-size:11.5px; color:var(--muted); margin-top:2px; }
.pc-value{ display:flex; align-items:center; gap:7px; margin-top:9px; flex-wrap:wrap; }
.pc-vorp{ font-weight:800; font-size:13px; color:#fff; background:var(--green);
  padding:2px 9px; border-radius:6px; }
.pc-marg{ font-size:11px; font-weight:800; color:#7a4ddb; background:#f1ecfb;
  padding:1px 7px; border-radius:5px; }
.pc-proj{ font-size:11.5px; font-weight:700; color:var(--muted); }
.pc-verdict{ font-size:10.5px; font-weight:800; padding:2px 8px; border-radius:20px;
  letter-spacing:.3px; margin-left:auto; }
.pc-verdict.grab{ background:#fdecec; color:#b3261e; } .pc-verdict.lean{ background:#fff4e5; color:#b3650a; }
.pc-verdict.wait{ background:#eaf2fd; color:#1457b0; } .pc-verdict.ok{ background:#eef1f4; color:#55606b; }
.pc-syns{ display:flex; flex-wrap:wrap; gap:5px; margin-top:8px; }
.pc-syn{ font-size:10.5px; font-weight:700; background:#f0ecfb; color:#5b34c7;
  padding:2px 8px; border-radius:6px; }
.pc-drop{ color:#b3232a; font-weight:700; }
.pc-surv{ margin-top:9px; font-size:12px; font-weight:600; color:var(--muted);
  display:flex; align-items:center; gap:7px; flex-wrap:wrap; }
.pc-pts{ margin-top:9px; font-size:12.5px; } .pc-pts b{ color:var(--green); }
.pc-grid{ display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-top:7px; }
.pc-stat{ background:#f7f9fb; border:1px solid var(--line); border-radius:7px; padding:5px 4px;
  text-align:center; }
.pc-v{ display:block; font-weight:800; font-size:14px; } .pc-k{ display:block; font-size:9.5px;
  color:var(--mut2); text-transform:uppercase; letter-spacing:.3px; }
.pc-nostat{ margin-top:8px; font-size:12px; color:var(--mut2); font-style:italic; }
.pc-syn.sos-easy{ background:#eaf7ef; color:#1c7a44; } .pc-syn.sos-hard{ background:#fdecec; color:#b3261e; }
.pc-syn.sos-avg{ background:#eef1f4; color:#55606b; }
.pc-opp{ display:flex; flex-wrap:wrap; gap:5px; margin-top:8px; }
.pc-ochip{ font-size:10.5px; font-weight:600; color:var(--muted); background:#f1f5f9;
  border:1px solid var(--line); border-radius:6px; padding:2px 7px; }
.pc-ochip b{ color:var(--ink); font-weight:800; }
.pc-bb{ display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-top:8px; font-size:11px; }
.pc-fc{ color:var(--muted); font-weight:600; } .pc-fc b{ color:var(--ink); }
.pc-boom{ font-weight:800; color:#1c7a44; background:#eaf7ef; padding:1px 7px; border-radius:5px; }
.pc-bust{ font-weight:800; color:#b3261e; background:#fdecec; padding:1px 7px; border-radius:5px; }

/* ---- steals & traps ---- */
.st-wrap{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.st-head{ font-size:10.5px; font-weight:800; letter-spacing:.4px; margin-bottom:4px; }
.st-head small{ display:block; font-weight:600; color:var(--mut2); letter-spacing:0; }
.st-head.steal{ color:#1c7a44; } .st-head.trap{ color:#b3261e; }
.st-row{ display:flex; align-items:center; gap:6px; padding:3px 4px; border-radius:6px; font-size:11.5px; }
.st-row.steal{ background:#f0faf3; } .st-row.trap{ background:#fdf1f1; }
.st-img{ width:20px; height:20px; border-radius:50%; object-fit:cover; }
.st-nm{ flex:1; font-weight:700; line-height:1.05; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.st-nm small{ display:block; font-weight:600; color:var(--mut2); font-size:9.5px; }
.st-gap{ font-weight:800; } .st-gap.steal{ color:#1c7a44; } .st-gap.trap{ color:#b3261e; }
.st-none{ color:var(--mut2); font-size:11px; padding:3px; }

/* ---- league board (opponent rosters/needs) ---- */
.lb{ display:flex; flex-direction:column; gap:3px; }
.lb-row{ display:flex; align-items:center; gap:6px; font-size:11px; padding:2px 5px; border-radius:6px; }
.lb-row.me{ background:#f3f9f5; font-weight:700; } .lb-row.clk{ box-shadow:inset 0 0 0 1.5px var(--blue); }
.lb-nm{ width:84px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.lb-chips{ display:flex; gap:3px; }
.lb-pc{ font-size:9.5px; font-weight:800; background:#eef1f4; color:var(--mut2); padding:1px 5px; border-radius:4px; }
.lb-pc.lb-low{ background:#fdecec; color:#b3261e; }
.lb-need{ margin-left:auto; font-size:10px; color:var(--mut2); font-weight:600; }

/* ---- post-draft recap ---- */
.recap{ background:#fff; border:1px solid var(--line); border-radius:11px; padding:13px; margin:6px 0; }
.rc-top{ display:flex; align-items:center; gap:13px; }
.rc-grade{ font-size:30px; font-weight:900; width:54px; height:54px; border-radius:12px;
  display:flex; align-items:center; justify-content:center; color:#fff; }
.rc-grade.gA{ background:#1c8a4d; } .rc-grade.gB{ background:#1f6fd6; }
.rc-grade.gC{ background:#b3650a; } .rc-grade.gD{ background:#b3232a; }
.rc-rank{ font-size:14px; } .rc-pts{ font-size:12px; color:var(--muted); margin-top:2px; }
.rc-line{ font-size:12px; margin-top:8px; } .rc-line b{ color:var(--ink); }

/* ---- roster strength ---- */
.rs{ display:flex; flex-direction:column; gap:3px; margin-bottom:8px; }
.rs-row{ display:flex; align-items:center; gap:7px; font-size:12px; padding:2px 4px; border-radius:6px; }
.rs-row.me{ background:#f3f9f5; font-weight:700; }
.rs-rk{ width:14px; color:var(--mut2); font-weight:800; text-align:center; }
.rs-nm{ width:96px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rs-bar{ flex:1; height:8px; background:var(--line2); border-radius:5px; overflow:hidden; }
.rs-bar i{ display:block; height:100%; background:var(--blue); }
.rs-row.me .rs-bar i{ background:var(--green); }
.rs-val{ width:32px; text-align:right; color:var(--mut2); font-weight:700; }

/* ---- best-available TABLE (FantasyPros-style) ---- */
table.dr-avail{ width:100%; border-collapse:collapse; }
table.dr-avail td{ padding:6px 10px; border-bottom:1px solid var(--line2); font-size:13px; }
table.dr-avail td.r{ color:var(--mut2); width:30px; text-align:center; font-weight:700; }
table.dr-avail td.a{ text-align:right; color:var(--ink); white-space:nowrap; font-weight:700; }
.dr-avail .tierband td{ background:var(--blue); color:#fff; font-weight:800; font-size:11px;
  letter-spacing:1.5px; text-transform:uppercase; padding:5px 10px; }
.dr-avail tr.rec td{ background:#fbfdff; box-shadow:inset 3px 0 0 var(--blue); }
.dr-avail .recbadge{ background:var(--blue); color:#fff; font-size:9px; padding:1px 6px;
  border-radius:4px; font-weight:800; margin-left:6px; }
.dr-avail .pp{ font-size:10px; color:var(--mut2); }

/* position chips + value badges (Draft Sharks intel) */
.posrank{ display:inline-block; font-weight:800; font-size:10px; color:#fff; border-radius:4px;
  padding:1px 6px; margin-right:5px; vertical-align:middle; }
.posrank.QB,.cheat-head.QB{ background:var(--qb);} .posrank.RB,.cheat-head.RB{ background:var(--rb);}
.posrank.WR,.cheat-head.WR{ background:var(--wr);} .posrank.TE,.cheat-head.TE{ background:var(--te);}
.posrank.K{ background:var(--k);} .posrank.DST,.posrank.D{ background:var(--dst);}
.vchip{ font-size:9px; font-weight:800; padding:2px 6px; border-radius:5px; margin-left:6px; }
.vchip.value{ background:#e6f6ec; color:var(--green); }
.vchip.reach{ background:#fdecec; color:var(--red); }
.hs{ width:28px; height:28px; border-radius:50%; object-fit:cover; background:var(--line2);
  vertical-align:middle; margin-right:7px; }

/* FantasyPros-style clickable row (markdown half; Draft button is a real widget) */
.fp-row{ display:flex; align-items:center; gap:4px; }
.fp-row img.hs{ margin-right:5px; }
.fp-row .nm{ font-weight:700; }
.fp-row .pb{ color:#fff; font-size:9px; font-weight:800; border-radius:3px; padding:1px 5px; margin:0 5px; }
.fp-row .pb.QB{ background:var(--qb);} .fp-row .pb.RB{ background:var(--rb);}
.fp-row .pb.WR{ background:var(--wr);} .fp-row .pb.TE{ background:var(--te);}
.fp-row .pb.K{ background:var(--k);} .fp-row .pb.DST{ background:var(--dst);}
.fp-row .tm{ color:var(--mut2); font-size:11px; }
.fp-row .sp{ flex:1; }
.fp-row .by{ color:var(--mut2); font-size:10px; margin-right:8px; }
.fp-row .adp{ font-weight:800; width:34px; text-align:right; }
.fp-row .adp small{ color:var(--mut2); font-weight:600; font-size:9px; }
.fp-star{ color:var(--amber); font-weight:900; margin-right:3px; }

/* ---- by-position cheat sheet ---- */
.dr-cheat{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }
.cheat-col{ border:1px solid var(--line); border-radius:9px; background:#fff; overflow:hidden; }
.cheat-head{ font-weight:800; color:#fff; text-align:center; padding:5px; font-size:12px; letter-spacing:1px; }
.cheat-row{ display:flex; align-items:center; gap:6px; padding:5px 8px; font-size:12px;
  border-bottom:1px solid var(--line2); }
.cheat-row .chs{ width:22px; height:22px; border-radius:50%; object-fit:cover; background:var(--line2); }
.cheat-row .cn{ font-weight:600; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.cheat-row .ca{ color:var(--mut2); font-size:10px; white-space:nowrap; }
.ptier{ font-weight:800; font-size:11px; letter-spacing:1.5px; color:#fff; background:var(--blue);
  padding:4px 10px; margin:6px 0 3px; border-radius:5px; text-transform:uppercase; }

/* ---- pick queue ---- */
.dr-queue{ display:flex; flex-direction:column; gap:3px; }
.q-row{ display:flex; align-items:center; gap:6px; font-size:12.5px; padding:3px 8px;
  border:1px solid var(--line); border-radius:7px; background:#fff; }
.q-row.gone{ opacity:.45; text-decoration:line-through; }
.q-row .qn{ font-weight:600; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.q-row .qp{ font-size:10px; color:var(--mut2); }

/* ---- draft board grid ---- */
.dr-grid{ display:grid; gap:3px; min-width:max-content; }
.dr-cell{ position:relative; font-size:11px; line-height:1.15; padding:5px 6px 5px 8px;
  border-radius:6px; background:#fff; min-height:44px; border:1px solid var(--line2);
  display:flex; flex-direction:column; justify-content:center; }
.dr-cell .pk{ position:absolute; top:2px; right:4px; font-size:8px; color:var(--mut2); font-weight:700; }
.dr-cell .nm{ font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%; }
.dr-cell .meta{ font-size:9px; color:var(--mut2); font-weight:600; }
.dr-cell.pos-QB{ box-shadow:inset 4px 0 0 var(--qb); } .dr-cell.pos-RB{ box-shadow:inset 4px 0 0 var(--rb); }
.dr-cell.pos-WR{ box-shadow:inset 4px 0 0 var(--wr); } .dr-cell.pos-TE{ box-shadow:inset 4px 0 0 var(--te); }
.dr-cell.pos-K{ box-shadow:inset 4px 0 0 var(--k); } .dr-cell.pos-DST,.dr-cell.pos-D{ box-shadow:inset 4px 0 0 var(--dst); }
.dr-cell.me{ outline:2px solid #c7e6d2; outline-offset:-2px; }
.dr-cell.now{ box-shadow:0 0 0 2px var(--blue); }
.dr-cell.kept .ktag{ position:absolute; top:2px; left:5px; font-weight:800; font-size:8px;
  color:#fff; background:var(--amber); border-radius:3px; padding:0 3px; }
.dr-cell.empty{ background:var(--panel2); } .dr-cell.empty .nm{ color:var(--mut2); font-weight:400; font-style:italic; }
.dr-colhead{ font-weight:800; font-size:10px; text-align:center; color:var(--muted);
  text-transform:uppercase; padding:5px 3px; background:var(--line2); border-radius:6px 6px 0 0;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.dr-colhead.me{ background:var(--green); color:#fff; }
.dr-colhead.rd{ background:var(--blue); color:#fff; }
.dr-rdlabel{ display:flex; align-items:center; justify-content:center; font-weight:800;
  font-size:12px; color:#fff; background:var(--blue); border-radius:6px; }

/* ---- last-pick / on-the-clock banners ---- */
.dr-lastpick{ display:flex; align-items:center; gap:9px; background:#fff; border:1px solid var(--line);
  border-left:5px solid var(--blue); border-radius:8px; padding:7px 12px; margin-bottom:8px; font-size:13px; }
.dr-lastpick.pos-QB{ border-left-color:var(--qb);} .dr-lastpick.pos-RB{ border-left-color:var(--rb);}
.dr-lastpick.pos-WR{ border-left-color:var(--wr);} .dr-lastpick.pos-TE{ border-left-color:var(--te);}
.dr-lastpick .lp-pk{ font-weight:800; color:var(--mut2); font-size:11px; min-width:30px; }
.dr-lastpick .lp-img{ width:26px; height:26px; border-radius:50%; object-fit:cover; background:#eef1f5;
  border:1px solid var(--line); }
.dr-lastpick .lp-nm{ color:var(--ink); }
.dr-lastpick small{ color:var(--mut2); }
.dr-onclock{ background:#fff8ec; border:1px solid #f6d3a8; color:#9a6500; border-radius:8px;
  padding:7px 12px; margin-bottom:8px; font-weight:700; font-size:13px; animation:ocpulse 1.3s ease-in-out infinite; }
@keyframes ocpulse{ 0%,100%{opacity:1;} 50%{opacity:.6;} }

/* ---- recent-picks ticker ---- */
.dr-ticker{ display:flex; align-items:center; gap:6px; overflow-x:auto; padding:2px 0 8px;
  white-space:nowrap; }
.dr-ticker .tk-l{ font-weight:800; font-size:9px; letter-spacing:1px; color:var(--mut2); }
.tk-chip{ font-size:11px; font-weight:600; background:#fff; border:1px solid var(--line);
  border-left-width:3px; border-radius:6px; padding:3px 9px; }
.tk-chip b{ color:var(--mut2); font-weight:800; margin-right:3px; }
.tk-chip small{ color:var(--mut2); }
.tk-chip.pos-QB{ border-left-color:var(--qb);} .tk-chip.pos-RB{ border-left-color:var(--rb);}
.tk-chip.pos-WR{ border-left-color:var(--wr);} .tk-chip.pos-TE{ border-left-color:var(--te);}
.tk-chip.pos-K{ border-left-color:var(--k);} .tk-chip.pos-DST,.tk-chip.pos-D{ border-left-color:var(--dst);}

/* keep the draft board compact so the rest of the page stays visible */
.dr-board-scroll{ max-height:430px; overflow:auto; border:1px solid var(--line); border-radius:10px;
  margin-bottom:18px; }

/* ---- whole-row clickable draft cards ---- */
[class*="_board_"] [data-testid="stVerticalBlock"]{ gap:3px; }
[class*="_brow_"]{ margin:0 !important; }
[class*="_brow_"] .stButton{ margin:0; }
[class*="_brow_"] .stButton button{ width:100%; text-align:left; justify-content:flex-start;
  padding:8px 58px 8px 46px; font-size:13px; font-weight:700; min-height:42px; line-height:1.25;
  border:1px solid var(--line); border-left-width:5px; border-radius:7px; background:#fff;
  color:var(--ink); white-space:normal; position:relative; }
[class*="_brow_"] .stButton button>div{ width:100%; text-align:left; }
/* player headshot as a ::before circle (per-row background-image injected inline) */
[class*="_brow_"] .stButton button::before{ content:""; position:absolute; left:9px; top:50%;
  transform:translateY(-50%); width:28px; height:28px; border-radius:50%; background:#eef1f5 center/cover no-repeat;
  border:1px solid var(--line); }
/* availability % as a shaded ::after box (per-row content+colors injected inline) */
[class*="_brow_"] .stButton button::after{ position:absolute; right:7px; top:50%;
  transform:translateY(-50%); font-size:11px; font-weight:800; padding:3px 6px; border-radius:5px;
  line-height:1.1; min-width:34px; text-align:center; }
[class*="_brow_"] .stButton button:hover{ border-color:var(--ink); box-shadow:0 2px 8px rgba(0,0,0,.10); }
[class*="_brow_QB"] .stButton button{ border-left-color:var(--qb); }
[class*="_brow_QB"] .stButton button:hover{ background:#fdf2f2; }
[class*="_brow_RB"] .stButton button{ border-left-color:var(--rb); }
[class*="_brow_RB"] .stButton button:hover{ background:#eefaf2; }
[class*="_brow_WR"] .stButton button{ border-left-color:var(--wr); }
[class*="_brow_WR"] .stButton button:hover{ background:#eef4fc; }
[class*="_brow_TE"] .stButton button{ border-left-color:var(--te); }
[class*="_brow_TE"] .stButton button:hover{ background:#fdf6ec; }
/* by-position cheat columns are narrow — compact the clickable rows (no headshot/
   survival box, tighter padding) so labels word-wrap instead of going vertical */
[class*="_board_QB"] .stButton button,[class*="_board_RB"] .stButton button,
[class*="_board_WR"] .stButton button,[class*="_board_TE"] .stButton button{
  padding:6px 7px; min-height:32px; font-size:10.5px; line-height:1.2; font-weight:700; }
[class*="_board_QB"] .stButton button::before,[class*="_board_RB"] .stButton button::before,
[class*="_board_WR"] .stButton button::before,[class*="_board_TE"] .stButton button::before,
[class*="_board_QB"] .stButton button::after,[class*="_board_RB"] .stButton button::after,
[class*="_board_WR"] .stButton button::after,[class*="_board_TE"] .stButton button::after{ display:none; }
</style>
"""


def crt(key: str = "top") -> str:
    return ""


def headshot(pid: str) -> str:
    return SLEEPER_IMG.format(pid=pid)


def headshot_src(pid: str) -> str:
    """Best headshot URL for a player (ESPN if known, else Sleeper thumb)."""
    eid = _ESPN_BY_PID.get(str(pid))
    return ESPN_IMG.format(eid=eid) if eid else headshot(pid)


def img_tag(pid: str, cls: str = "hs") -> str:
    return f'<img class="{cls}" src="{headshot_src(pid)}" loading="lazy">'


def logo_html(size: int = 30, tag: str | None = "Mock + Live Draft") -> str:
    t = f'<div class="neon-tag">{tag}</div>' if tag else ""
    return f'<span class="neon-logo" style="font-size:{size}px;">Draft Room</span>{t}'


def inject(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
