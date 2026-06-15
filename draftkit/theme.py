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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Sora:wght@600;700;800;900&display=swap');
/* ===== Night Draft — light variant (teal accent) ===== */
:root{
  --bg:#eef1f6; --panel:#ffffff; --panel2:#f5f7fa; --line:#e3e8ef; --line2:#eef1f6;
  --ink:#101b2c; --muted:#5d6b7e; --mut2:#93a1b2;
  --blue:#0d9488; --green:#1c8a4d; --red:#d23b3b; --amber:#e08a1e; --violet:#6248c8;
  --accent:#0d9488; --accent-soft:#e6f6f3; --accent-line:#bfe6df;
  --qb:#d23b3b; --rb:#2e9e5b; --wr:#2f72c4; --te:#e08a1e; --k:#7a7f87; --dst:#6248c8;
  --shadow:0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.05);
  --shadow-lg:0 4px 14px rgba(16,24,40,.08);
}
/* Sora as the display face for brand, section heads, and player names */
h1,h2,h3,.neon-logo,.dr-h,.dr-status .rd,.tb-name,.pc-name,.pf-nm,.an-nm,.bz-nm,
.rh-nm,.dr-rec b,.dr-runban b{ font-family:'Sora',-apple-system,'Segoe UI',sans-serif; }
.stApp{ background:var(--bg); }
html,body,[class*="css"],button,input,textarea,select,[data-testid="stMarkdownContainer"]{
  font-family:'Inter',-apple-system,'Segoe UI',Roboto,Arial,sans-serif; color:var(--ink); }
html,body{ font-size:13px; }
/* tabular figures so every ADP / V / % column lines up cleanly */
.dr-status,.dr-avail,.rs,.lb,.pcard,.dr-grid,.dr-predict,[class*="_brow_"],[class*="_pp_"],
[class*="_steals"],[class*="_traps"]{ font-feature-settings:'tnum' 1,'ss01' 1; }
/* The Streamlit header + its full-width toolbar wrapper sit on top of our sticky
   topbar (z-index 999990) and would otherwise eat clicks on the War-room / Switch
   controls. Make the empty header + toolbar container click-through, and re-enable
   only the actual action controls (app menu, deploy, status) on the right. */
[data-testid="stHeader"]{ background:transparent; pointer-events:none !important; }
[data-testid="stToolbar"],
[data-testid="stToolbar"] *{ pointer-events:none !important; }
[data-testid="stToolbar"] button,
[data-testid="stToolbar"] a,
[data-testid="stMainMenu"] button,
[data-testid="stToolbarActions"] button,
[data-testid="stStatusWidget"]{ pointer-events:auto !important; }
[data-testid="stSidebar"]{ background:#fff; border-right:1px solid var(--line); }

/* layout density (desktop) */
.block-container{ padding:.5rem .9rem 1.5rem; max-width:100%; }
[data-testid="stVerticalBlock"]{ gap:.4rem; }
[data-testid="stHorizontalBlock"]{ gap:.55rem; }
[data-testid="stExpander"]{ border:none; }
[data-testid="stCaptionContainer"]{ font-size:11px; color:var(--mut2); }

h1,h2,h3{ font-weight:800; letter-spacing:-.2px; }
h1{ color:var(--blue); line-height:1.3; overflow:visible; padding-top:2px; }
h2{ color:var(--ink); font-size:1.35rem; } h3{ font-size:1.05rem; }
.neon-logo{ font-weight:900; font-size:inherit; color:var(--blue); letter-spacing:-.5px;
  display:inline-block; line-height:1.3; padding-top:.12em; overflow:visible; }
.neon-logo::first-letter{ color:var(--blue); }
.neon-tag{ font-weight:700; font-size:10px; letter-spacing:2px; color:var(--mut2);
  text-transform:uppercase; }

/* buttons: flat, compact; teal primary (Night Draft accent) */
.stButton>button{ font-weight:700; font-size:12.5px; border-radius:7px; padding:5px 14px;
  transition:.12s; }
.stButton>button[kind="secondary"]{ background:#fff; color:var(--ink); border:1.5px solid var(--line); }
.stButton>button[kind="secondary"]:hover{ border-color:var(--blue); color:var(--blue); }
.stButton>button[kind="primary"],.stButton>button[kind="primaryFormSubmit"]{
  background:var(--blue); color:#fff; border:none; }
.stButton>button[kind="primary"]:hover,.stButton>button[kind="primaryFormSubmit"]:hover{
  filter:brightness(1.06); }
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

/* ---- sticky top app bar ---- */
[class*="dr_topbar"]{ position:sticky; top:0; z-index:999;
  background:rgba(242,244,248,.9); backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line); margin:-.5rem -.9rem 10px; padding:8px .9rem 8px; }
/* War-room button — compact pill, highlighted when dark mode is on */
[class*="tb_war"] .stButton button{ float:none !important; width:100%; min-height:34px;
  border-radius:18px; font-size:12px; font-weight:700; padding:4px 10px; }
[class*="dr_topbar"] .stColumn [data-testid="stVerticalBlock"]{ gap:0; justify-content:center; }
.tb-row{ display:flex; align-items:center; gap:9px; flex-wrap:wrap; min-height:32px; }
.tb-name{ font-weight:800; font-size:16px; color:var(--ink); margin-right:3px; }
.tb-pill{ font-size:10px; font-weight:700; color:var(--muted); background:var(--panel2);
  border:1px solid var(--line); border-radius:20px; padding:2px 9px; text-transform:uppercase;
  letter-spacing:.3px; }
[class*="dr_topbar"] .stButton button{ float:right; }

/* ---- shared card / scroll wrappers ---- */
.neonwrap{ overflow:auto; border:1px solid var(--line); border-radius:10px; background:#fff; }
.dr-h{ font-weight:800; font-size:11px; text-transform:uppercase; letter-spacing:.7px;
  color:var(--muted); margin:16px 0 9px; padding-top:14px; border-top:1px solid var(--line2);
  display:flex; align-items:center; gap:8px; }
.dr-h.dr-title{ margin-top:2px; padding-top:0; border-top:none; }   /* panel titles: no divider */
.dr-h::before{ content:""; width:3px; height:13px; border-radius:2px; background:var(--blue);
  flex:none; }

/* ---- panel cards: the three main columns read as distinct modules ---- */
[class*="dr_panel_"]{ background:var(--panel); border:1px solid var(--line); border-radius:12px;
  padding:11px 12px 9px; box-shadow:var(--shadow); }
/* the three draft columns are pinned to one screen height so their bottoms align
   and the page itself never scrolls — each scrolls its own content internally */
[class*="dr_panel_board"],[class*="dr_panel_intel"]{
  height:calc(100vh - 112px); overflow-y:auto; overflow-x:hidden; }
[class*="dr_panel_"] [data-testid="stExpander"]{ background:var(--panel2); border:1px solid var(--line);
  border-radius:10px; margin-top:8px; }
[class*="dr_panel_"] [data-testid="stExpander"] summary{ font-size:11px; font-weight:800;
  text-transform:uppercase; letter-spacing:.5px; color:var(--muted); }

/* segmented pill toggles for the List/By-position + UDK/Value radios */
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"]{ gap:0; padding:3px;
  background:var(--line2); border:1px solid var(--line); border-radius:9px; display:inline-flex; }
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"] label{ padding:4px 13px;
  margin:0; border-radius:6px; font-size:11.5px; font-weight:700; color:var(--muted); cursor:pointer; }
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"] label>div:first-child{ display:none; }
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"] label:hover{ color:var(--ink); }
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked){
  background:#fff; color:var(--ink); box-shadow:var(--shadow); }

/* ---- left-panel tabs: Rankings / Teams / Queue ---- */
[class*="dr_panel_board"] [data-baseweb="tab-list"]{ gap:6px; margin-bottom:10px;
  border-bottom:1px solid var(--line); }
[class*="dr_panel_board"] button[data-baseweb="tab"]{ padding:7px 18px 9px; font-weight:800;
  font-size:15px; color:var(--muted); }
[class*="dr_panel_board"] button[data-baseweb="tab"]:hover{ color:var(--ink); }
[class*="dr_panel_board"] button[data-baseweb="tab"][aria-selected="true"]{ color:var(--ink); }
[class*="dr_panel_board"] [data-baseweb="tab-highlight"]{ background:var(--blue); height:3px;
  border-radius:3px; }
[class*="dr_panel_board"] [data-baseweb="tab-border"]{ display:none; }

/* ---- position filter pills (All/QB/RB/WR/TE/K/DST) — flat, blue-selected ---- */
[class*="_posf"] [data-testid="stRadio"] [role="radiogroup"]{ background:transparent !important;
  border:none !important; padding:2px 0 !important; gap:3px !important; flex-wrap:wrap; }
[class*="_posf"] [data-testid="stRadio"] [role="radiogroup"] label{ padding:3px 11px !important;
  border-radius:14px; font-weight:800 !important; font-size:12.5px !important; color:var(--muted); }
[class*="_posf"] [data-testid="stRadio"] [role="radiogroup"] label:hover{ color:var(--ink); }
[class*="_posf"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked){
  background:#eaf1fb !important; color:var(--blue) !important; box-shadow:none !important; }

/* ---- ranking source dropdown (prominent, like the cheat-sheet picker) ---- */
[class*="dr_panel_board"] [data-testid="stSelectbox"] > div > div{ border-radius:9px;
  font-weight:700; }

/* ---- status bar ---- */
.dr-status{ display:flex; align-items:center; gap:18px; flex-wrap:wrap;
  background:linear-gradient(180deg,#ffffff,#f7f9fc);
  border:1px solid var(--line); border-radius:13px; padding:12px 20px; margin-bottom:14px;
  box-shadow:var(--shadow); }
.dr-status .rd{ font-weight:900; font-size:26px; color:var(--blue); line-height:1.1;
  letter-spacing:-.5px; }
.dr-status .rd small{ display:block; font-size:8.5px; letter-spacing:1.6px; color:var(--mut2);
  font-weight:800; margin-top:2px; }
.dr-status .clk{ font-weight:600; font-size:13.5px; color:var(--muted); }
.dr-status .clk b{ color:var(--ink); font-weight:800; }
.dr-status .yours{ background:var(--green); color:#fff; border:none; margin-left:auto;
  padding:7px 18px; border-radius:8px; font-weight:900; font-size:13px; letter-spacing:.5px;
  box-shadow:0 2px 6px rgba(28,138,77,.3); }

/* ---- My Team lineup ---- */
.dr-lineup{ margin-bottom:16px; }
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
.dr-balance{ display:flex; align-items:center; gap:8px; margin:0 0 9px; flex-wrap:wrap; }
.bal-chip{ font-weight:800; font-size:11px; padding:3px 10px; border-radius:14px; }
.bal-chip.bal-ok{ background:#eaf7ef; color:#1c7a44; }
.bal-chip.bal-warn{ background:#fff4e5; color:#b3650a; }
.bal-detail{ font-size:11px; font-weight:600; color:var(--mut2); }
/* all-positions cheat sheet (QB/RB/WR/TE columns + pick-predictor %) */
.cheat-sheet{ font-size:11.5px; }
.cs-cap{ font-size:10.5px; color:var(--mut2); margin:2px 0 7px; }
.cs-cols{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
.cs-col{ min-width:0; }
.cs-head{ font-weight:900; font-size:12px; text-align:center; padding:4px; border-radius:6px;
  color:#fff; margin-bottom:4px; }
.cs-head.pos-QB{ background:var(--qb); } .cs-head.pos-RB{ background:var(--rb); }
.cs-head.pos-WR{ background:var(--wr); } .cs-head.pos-TE{ background:var(--te); }
.cs-tier{ font-size:9.5px; font-weight:800; color:var(--mut2); text-transform:uppercase;
  letter-spacing:.4px; margin:5px 0 2px; border-top:1px solid var(--line2); padding-top:3px; }
.cs-row{ display:flex; align-items:center; gap:4px; padding:2px; border-radius:4px; }
.cs-row:hover{ background:var(--panel2); }
.cs-nm{ font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:1;
  color:var(--ink); }
.cs-tm{ font-size:9.5px; color:var(--mut2); font-weight:600; }
.cs-sv{ font-size:9.5px; font-weight:800; border-radius:8px; padding:0 5px; }
/* ADP market read (cross-source spread + buy/sell vs value) */
.dr-market{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin:7px 0 0; font-size:11px; }
.mk-tag{ font-weight:800; padding:2px 8px; border-radius:10px; }
.mk-tag.mk-ok{ background:#eef1f4; color:#55606b; }
.mk-tag.mk-split{ background:#fff4e5; color:#b3650a; }
.mk-buy{ font-weight:700; color:#1c7a44; }
.mk-sell{ font-weight:700; color:#b3261e; }
.mk-srcs{ display:flex; gap:4px; flex-wrap:wrap; }
.mk-src{ font-size:10px; font-weight:700; color:var(--mut2); background:#f7f9fb;
  border:1px solid var(--line); border-radius:5px; padding:1px 6px; }
.dr-alerts{ display:flex; gap:8px; flex-wrap:wrap; margin:0 0 9px; }
.dr-alerts .alert{ font-weight:700; font-size:12px; padding:4px 11px; border-radius:8px; }
.alert.cliff{ background:#fdecec; color:var(--red); border:1px solid #f5c2c2; }
.alert.run{ background:#fff3e6; color:#b3650a; border:1px solid #f6d3a8; }
.alert.need{ background:#e9f1fb; color:var(--blue); border:1px solid #c2d6f0; }
.dr-rec{ background:linear-gradient(180deg,#f1faf4,#e9f6ef); border:1px solid #bfe3cd;
  border-left:4px solid var(--green); border-radius:10px; padding:10px 14px; margin:4px 0 10px;
  font-size:13px; box-shadow:0 1px 3px rgba(28,138,77,.10); }
.dr-rec b{ color:#15703d; font-weight:800; } .dr-rec .why{ color:var(--muted); }

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
.pc-meta .pc-mlbl{ font-weight:600; color:var(--mut2); font-size:10px; }
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
/* ---- compact spotlight: a horizontal banner that sits ABOVE the board/list ---- */
.pcard.compact{ display:flex; flex-wrap:wrap; align-items:center; gap:6px 14px;
  padding:8px 13px; margin:0 0 9px; }
.pcard.compact .pc-head{ flex:0 0 auto; gap:9px; }
.pcard.compact .pc-img{ width:42px; height:42px; border-width:1.5px; }
.pcard.compact .pc-name{ font-size:15px; }
.pcard.compact .pc-pos{ margin-top:0; }
.pcard.compact .pc-flag{ margin-top:2px; }
.pcard.compact .pc-value{ margin-top:0; }
.pcard.compact .pc-meta{ margin-top:0; font-size:11.5px; }
.pcard.compact .pc-surv{ margin-top:0; font-size:11.5px; }
.pcard.compact .pc-syns{ margin-top:0; }
.pcard.compact .pc-bio{ display:none; }               /* drop verbose bio when compact */
/* Keep the compact card a true banner: drop the bulky last-season blocks (deep
   stat grid, opportunity chips, boom/bust) — the season points stay as a one-liner.
   Full stats live in the player's spotlight elsewhere; this is the on-the-clock card. */
.pcard.compact .pc-grid,
.pcard.compact .pc-opp,
.pcard.compact .pc-bb,
.pcard.compact .pc-nostat{ display:none; }
.pcard.compact .pc-pts{ margin-top:0; font-size:11.5px; }
.pcard.compact .pc-verdict{ margin-left:0; }

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
.st-head{ cursor:help; }
/* clickable steal/trap rows */
[class*="_steals"] .stButton, [class*="_traps"] .stButton{ margin:0; }
[class*="_steals"] .stButton button, [class*="_traps"] .stButton button{
  width:100%; text-align:left; justify-content:flex-start; padding:4px 8px; min-height:30px;
  font-size:11px; font-weight:700; border-radius:6px; line-height:1.15; margin:2px 0;
  white-space:normal; border:1px solid var(--line); }
[class*="_steals"] .stButton button{ background:#f0faf3; color:#15663a; border-left:3px solid #1c8a4d; }
[class*="_steals"] .stButton button:hover{ background:#e2f5e9; border-color:#1c8a4d; }
[class*="_traps"] .stButton button{ background:#fdf1f1; color:#9a2820; border-left:3px solid #b3261e; }
[class*="_traps"] .stButton button:hover{ background:#fbe4e4; border-color:#b3261e; }
/* clickable pick-predictor rows (headshot ::before injected per row) */
[class*="_pp_"] .stButton{ margin:0; }
[class*="_pp_"] .stButton button{ width:100%; text-align:left; justify-content:flex-start;
  position:relative; padding:5px 8px 5px 34px; min-height:32px; font-size:11px; font-weight:700;
  line-height:1.15; margin:2px 0; border:1px solid var(--line); border-left-width:4px;
  border-radius:7px; background:#fff; color:var(--ink); white-space:normal; }
[class*="_pp_"] .stButton button::before{ content:""; position:absolute; left:7px; top:50%;
  transform:translateY(-50%); width:22px; height:22px; border-radius:50%;
  background:#eef1f5 center/cover no-repeat; border:1px solid var(--line); }
[class*="_pp_"] .stButton button:hover{ box-shadow:0 2px 8px rgba(0,0,0,.10); }
[class*="_pp_QB"] .stButton button{ border-left-color:var(--qb); }
[class*="_pp_RB"] .stButton button{ border-left-color:var(--rb); }
[class*="_pp_WR"] .stButton button{ border-left-color:var(--wr); }
[class*="_pp_TE"] .stButton button{ border-left-color:var(--te); }
/* force left-aligned labels inside every custom clickable row (Streamlit centers
   button text by default; keep its inner markdown/p left no matter the wrapper) */
[class*="_steals"] .stButton button, [class*="_traps"] .stButton button,
[class*="_pp_"] .stButton button{ text-align:left !important; justify-content:flex-start !important; }
[class*="_steals"] .stButton button *, [class*="_traps"] .stButton button *,
[class*="_pp_"] .stButton button *{ text-align:left !important; justify-content:flex-start !important; }

/* ---- queue ★ toggle beside each best-available row ---- */
[class*="_qstar_"] .stButton{ margin:0; }
[class*="_qstar_"] .stButton button{ border:none !important; background:transparent !important;
  box-shadow:none !important; padding:0 !important; min-height:42px; min-width:0;
  font-size:20px; line-height:1; color:#e0a106; }
[class*="_qstar_"] .stButton button:hover{ background:transparent !important; color:#b87f00; }
[class*="_qstar_"] .stButton button:focus,[class*="_qstar_"] .stButton button:active{
  box-shadow:none !important; background:transparent !important; }

/* ---- opponent scouting cards (built from real draft history) ---- */
.dr-scout{ display:flex; flex-direction:column; gap:8px; }
.sc-card{ background:#fff; border:1px solid var(--line); border-left:4px solid #94a3b8;
  border-radius:9px; padding:9px 12px; box-shadow:var(--shadow); }
.sc-card.clk{ box-shadow:0 0 0 2px var(--blue), var(--shadow); }
.sc-head{ display:flex; align-items:center; justify-content:space-between; gap:8px; }
.sc-nm{ font-weight:800; font-size:13px; color:var(--ink); }
.sc-arch{ font-size:10px; font-weight:800; letter-spacing:.3px; padding:2px 8px;
  border-radius:11px; text-transform:uppercase; white-space:nowrap; }
.sc-pred{ display:flex; align-items:center; gap:7px; margin:5px 0 3px; }
.sc-pbar{ flex:1; height:5px; border-radius:3px; background:var(--line2); overflow:hidden; }
.sc-pbar>span{ display:block; height:100%; border-radius:3px; }
.sc-plabel{ font-size:9.5px; font-weight:700; color:var(--mut2); white-space:nowrap; }
.sc-tend{ margin:4px 0 0; padding-left:16px; }
.sc-tend li{ font-size:11.5px; color:var(--ink); margin:2px 0; line-height:1.3; }
.sc-target{ margin-top:6px; font-size:11px; font-weight:700; color:var(--muted);
  border-top:1px dashed var(--line); padding-top:5px; }
.sc-target b{ color:var(--blue); }
.sc-thin,.sc-empty{ font-size:11px; color:var(--mut2); font-style:italic; }

/* ---- rankings list scrolls inside its own box (page stays put) ---- */
[class*="_ranklist"]{ max-height:calc(100vh - 250px); overflow-y:auto; overflow-x:hidden;
  padding-right:4px; margin-top:2px; }

/* ---- live 'Picks' rail (FantasyPros-style) ---- */
.dr-picks{ display:flex; flex-direction:column; gap:5px; max-height:calc(100vh - 250px);
  overflow:auto; padding-right:3px; margin-bottom:8px; }
.pf-head{ font-size:12px; font-weight:700; color:var(--ink); padding:3px 2px 6px;
  position:sticky; top:0; background:var(--panel); z-index:2; }
.pf-head b{ color:var(--blue); }
.pf-rd{ font-size:9px; font-weight:800; letter-spacing:1px; text-transform:uppercase;
  color:var(--mut2); text-align:center; margin:7px 0 0; }
.pf-card{ background:#fff; border:1px solid var(--line); border-radius:9px; padding:6px 10px; }
.pf-card.me{ border-color:var(--blue); background:#f4f8ff; }
.pf-card.cur{ box-shadow:0 0 0 2px var(--blue); }
.pf-card.yours{ background:var(--blue); border:none; box-shadow:0 3px 10px rgba(31,78,155,.3); }
.pf-l{ display:flex; align-items:center; gap:7px; }
.pf-pk{ font-size:10px; font-weight:800; color:var(--mut2); min-width:30px; }
.pf-mgr{ font-size:11px; font-weight:700; color:var(--muted); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.pf-player{ display:flex; align-items:center; gap:7px; margin-top:3px; }
.pf-img{ width:26px; height:26px; border-radius:6px; object-fit:cover; background:var(--line2); }
.pf-nm{ font-weight:800; font-size:12.5px; color:var(--ink); flex:1; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.pf-meta{ font-size:10px; font-weight:700; color:var(--mut2); white-space:nowrap; }
.pf-pos{ color:#fff; font-size:9px; font-weight:800; border-radius:3px; padding:0 4px; margin-right:3px; }
.pf-pos.pos-QB{ background:var(--qb);} .pf-pos.pos-RB{ background:var(--rb);}
.pf-pos.pos-WR{ background:var(--wr);} .pf-pos.pos-TE{ background:var(--te);}
.pf-needs{ margin-top:4px; display:flex; align-items:center; gap:3px; flex-wrap:wrap; }
.pf-needl{ font-size:10px; color:var(--mut2); margin-right:2px; }
.pf-needl.set{ color:var(--green); font-weight:700; }
.pf-need{ color:#fff; font-size:9px; font-weight:800; border-radius:9px; padding:1px 6px; }
.pf-need.pos-QB{ background:var(--qb);} .pf-need.pos-RB{ background:var(--rb);}
.pf-need.pos-WR{ background:var(--wr);} .pf-need.pos-TE{ background:var(--te);}
.pf-yours{ font-size:14px; font-weight:900; color:#fff; margin-top:2px; }
.pf-pred .pf-likely{ font-size:8px; font-weight:800; text-transform:uppercase; letter-spacing:.4px;
  color:var(--mut2); border:1px solid var(--line); border-radius:8px; padding:0 5px; margin-left:auto; }
.pf-pred .pf-snipe{ font-size:8px; font-weight:900; text-transform:uppercase; letter-spacing:.3px;
  color:#fff; background:var(--red); border-radius:8px; padding:1px 6px; margin-left:auto; }
.pf-card .pf-pred.pf-warn{ background:#fdecec; border-radius:6px; padding:3px 5px; margin-top:3px; }

/* ---- one-line draft-strategy bar atop Suggestions ---- */
.dr-strategy{ display:flex; align-items:center; gap:8px; background:#fff8e6;
  border:1px solid #f3d98a; border-radius:9px; padding:7px 11px; margin:2px 0 9px;
  font-size:12.5px; color:#7a5b14; }
.dr-strategy b{ color:#5a430d; }
.ds-tag{ font-size:9px; font-weight:900; letter-spacing:.5px; text-transform:uppercase;
  color:#fff; background:#e0a106; border-radius:6px; padding:2px 7px; flex:none; }

/* ---- 'beat the room' read in the spotlight ---- */
.dr-room{ font-size:11.5px; border-radius:7px; padding:6px 10px; margin:8px 0 2px;
  border:1px solid var(--line); }
.dr-room.grab{ background:#fdecec; border-color:#f3c4c4; color:#9a2820; }
.dr-room.lean{ background:#fff6e8; border-color:#f3dcb0; color:#8a5a12; }
.dr-room.wait{ background:#eef6f0; border-color:#cfe6d6; color:#1c6b3f; }

/* ---- Coach AI (outlook + Q&A) ---- */
.dr-ai{ font-size:12.5px; line-height:1.5; color:#27303b; background:#f3f7fc;
  border:1px solid #d9e4f0; border-left:3px solid #6c8fd6; border-radius:7px;
  padding:8px 11px; margin:2px 0 8px; }
.dr-ai-q{ font-size:12px; color:#3a4150; margin:5px 0 1px; }
.dr-ai-a{ font-size:12.5px; line-height:1.5; color:#27303b; background:#f6f8fa;
  border:1px solid #e2e8ef; border-radius:7px; padding:7px 10px; margin:1px 0 6px; }

/* ---- on-the-clock run banner + act-now list + waiver buzz ---- */
.dr-runban{ font-size:12.5px; font-weight:500; border-radius:8px; padding:7px 11px;
  margin:2px 0 9px; border:1px solid #f3c4b0; background:#fdeee6; color:#8a3d1c; }
.dr-runban.grab{ background:#fdecec; border-color:#f0b3b3; color:#9a2820; }
.dr-actnow,.dr-buzzlist{ border:1px solid var(--line); border-radius:9px;
  padding:7px 9px; margin:6px 0; background:#fff; }
.an-h,.bz-h{ font-size:11px; font-weight:700; letter-spacing:.02em; color:#5a6470;
  text-transform:uppercase; margin:0 0 5px; }
.an-row,.bz-row{ display:flex; align-items:center; gap:6px; padding:3px 2px;
  border-top:1px solid #f0f2f5; font-size:12px; }
.an-row:first-of-type,.bz-row:first-of-type{ border-top:none; }
.an-img,.bz-img{ width:22px; height:16px; border-radius:3px; object-fit:cover; }
.an-rk{ font-weight:700; color:#6a7480; font-size:11px; min-width:26px; }
.an-nm,.bz-nm{ font-weight:600; color:#222; }
.an-tm,.bz-tm{ color:#8a929c; font-size:11px; }
.an-sv{ margin-left:auto; font-weight:700; color:#b14a2a; font-size:11.5px; }
.bz-ct{ margin-left:auto; font-weight:700; color:#c2410c; font-size:11.5px; }
.an-row.pos-QB,.bz-row.pos-QB{ box-shadow:inset 3px 0 0 -1px #e0556a; padding-left:6px; }
.an-row.pos-RB,.bz-row.pos-RB{ box-shadow:inset 3px 0 0 -1px #36a26b; padding-left:6px; }
.an-row.pos-WR,.bz-row.pos-WR{ box-shadow:inset 3px 0 0 -1px #4a7fd6; padding-left:6px; }
.an-row.pos-TE,.bz-row.pos-TE{ box-shadow:inset 3px 0 0 -1px #d98a2b; padding-left:6px; }
.dr-buzz{ display:inline-block; font-size:11px; font-weight:600; border-radius:6px;
  padding:2px 7px; margin:6px 0 2px; border:1px solid #f3d2b0; }
.dr-buzz.up{ background:#fff2e6; color:#c2410c; border-color:#f3cda3; }
.dr-buzz.down{ background:#eef3f8; color:#436389; border-color:#cdd9e6; }

/* ---- rookie reach (league-history boost readout) ---- */
.dr-rookhist{ border:1px solid var(--line); border-radius:9px; padding:7px 9px;
  margin:6px 0; background:#fbf7ff; }
.rh-h{ font-size:11px; font-weight:700; letter-spacing:.02em; color:#6b4a8a;
  text-transform:uppercase; margin:0 0 5px; }
.rh-row{ display:flex; align-items:center; gap:6px; padding:3px 2px;
  border-top:1px solid #efe7f6; font-size:12px; }
.rh-row:first-of-type{ border-top:none; }
.rh-img{ width:22px; height:16px; border-radius:3px; object-fit:cover; }
.rh-nm{ font-weight:600; color:#222; }
.rh-tm{ color:#8a929c; font-size:11px; }
.rh-adp{ margin-left:auto; color:#8a929c; font-size:11px; }
.rh-arrow{ color:#b9a0d6; }
.rh-slot{ font-weight:700; color:#6b4a8a; font-size:11.5px; }
.rh-up{ background:#efe2fb; color:#6b3fa0; border-radius:5px; padding:1px 5px;
  font-size:10.5px; font-weight:700; }
.rh-flat{ color:#9aa4b0; font-size:11px; }
.rh-foot{ font-size:10.5px; color:#8a7da0; margin-top:5px; }
.rh-row.pos-QB{ box-shadow:inset 3px 0 0 -1px #e0556a; padding-left:6px; }
.rh-row.pos-RB{ box-shadow:inset 3px 0 0 -1px #36a26b; padding-left:6px; }
.rh-row.pos-WR{ box-shadow:inset 3px 0 0 -1px #4a7fd6; padding-left:6px; }
.rh-row.pos-TE{ box-shadow:inset 3px 0 0 -1px #d98a2b; padding-left:6px; }

/* ---- always-visible roster-needs tray ---- */
.dr-needs{ display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin:0 0 8px;
  padding:5px 8px; background:#f6f8fb; border:1px solid var(--line); border-radius:8px; }
.ns-h{ font-size:11px; font-weight:700; color:#5a6470; text-transform:uppercase;
  letter-spacing:.02em; margin-right:3px; }
.ns-chip{ font-size:11px; font-weight:600; border-radius:5px; padding:2px 7px;
  border:1px solid transparent; }
.ns-fill{ background:#eef1f4; color:#9aa3ad; border-color:#e2e6ea; }
.ns-open{ background:#fff4e6; color:#b5631a; border-color:#f1cfa1; }
.ns-open.ns-QB{ background:#fdeef0; color:#b1364a; border-color:#f3c4cc; }
.ns-open.ns-RB{ background:#eaf6ef; color:#1f7d4d; border-color:#c2e4ce; }
.ns-open.ns-WR{ background:#eaf1fb; color:#2d5fa8; border-color:#c2d6f0; }
.ns-open.ns-TE{ background:#fbf2e6; color:#9a6312; border-color:#eed7b0; }

/* ---- inline stack / handcuff badge on board + suggestion rows ---- */
.stk-badge{ font-size:11px; }

/* ---- roster-construction path ---- */
.dr-plan{ background:#fff; border:1px solid var(--line); border-radius:9px; padding:8px 11px;
  margin-bottom:10px; box-shadow:var(--shadow); }
.pl-h{ font-size:9.5px; font-weight:800; letter-spacing:.6px; text-transform:uppercase;
  color:var(--mut2); margin-bottom:5px; }
.pl-row{ display:flex; align-items:center; flex-wrap:wrap; gap:3px; }
.pl-step{ display:inline-flex; align-items:center; gap:5px; }
.pl-pos{ font-size:10px; font-weight:800; padding:2px 7px; border-radius:10px; }
.pl-nm{ font-size:11px; font-weight:600; color:var(--ink); }
.pl-arrow{ color:var(--mut2); font-weight:800; margin:0 2px; }

/* ---- post-draft grade ---- */
.dr-grade{ display:flex; align-items:center; gap:14px; background:#fff; border:1px solid var(--line);
  border-radius:11px; padding:12px 16px; margin-bottom:12px; box-shadow:var(--shadow-lg); }
.g-badge{ font-size:30px; font-weight:900; color:#fff; width:58px; height:58px; border-radius:12px;
  display:flex; align-items:center; justify-content:center; flex:none; }
.g-top{ font-weight:800; font-size:13px; color:var(--ink); margin-bottom:5px; }
.g-pcs{ display:flex; gap:5px; flex-wrap:wrap; }
.g-pc{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:7px; }
.g-pc.g-ok{ background:#e6f6ec; color:#15663a; }
.g-pc.g-low{ background:#fdecec; color:#9a2820; }
.g-best{ font-size:11px; color:var(--muted); margin-top:5px; }

/* ---- quick-draft button beside each best-available row (List view) ---- */
[class*="_qdraft_"] .stButton{ margin:0; }
[class*="_qdraft_"] .stButton button{ width:100%; min-height:42px; padding:0 4px;
  border-radius:7px; border:none;
  background:linear-gradient(180deg,#23a65d,#1b854a); color:#fff;
  font-size:10px; font-weight:800; letter-spacing:.5px; text-transform:uppercase;
  box-shadow:0 1px 2px rgba(27,133,74,.32);
  transition:filter .12s ease, transform .12s ease, box-shadow .12s ease; }
[class*="_qdraft_"] .stButton button:hover{ filter:brightness(1.06); transform:translateY(-1px);
  box-shadow:0 3px 9px rgba(27,133,74,.42); }
[class*="_qdraft_"] .stButton button:active{ transform:translateY(0); }
/* force white label — Streamlit's inner <p> can carry its own (dark) text colour
   that wins over the button's `color`, so set it explicitly on the descendants */
[class*="_qdraft_"] .stButton button,
[class*="_qdraft_"] .stButton button *{ color:#fff !important; }
[class*="_qdraft_"] .stButton button *{ justify-content:center !important; }

/* drafted players left in the queue: struck through + dimmed */
[class*="_brow_"] .stButton button:disabled{ text-decoration:line-through;
  opacity:.5; filter:grayscale(.4); }

/* ---- clickable queue rows (open the player's card) + remove ✕ ---- */
[class*="_qrow_"] .stButton{ margin:0; }
[class*="_qrow_"] .stButton button{ width:100%; text-align:left !important;
  justify-content:flex-start !important; padding:5px 10px; min-height:30px; font-size:11.5px;
  font-weight:600; border-radius:7px; border:1px solid var(--line); background:#fff;
  color:var(--ink); margin:2px 0; }
[class*="_qrow_"] .stButton button *{ text-align:left !important; justify-content:flex-start !important; }
[class*="_qrow_"] .stButton button:hover{ border-color:var(--blue); background:#f4f8fd; }
[class*="_qrow_"] .stButton button:disabled{ color:var(--mut2); text-decoration:line-through;
  background:var(--panel2); border-style:dashed; }
[class*="_qx_"] .stButton{ margin:0; }
[class*="_qx_"] .stButton button{ border:none !important; background:transparent !important;
  color:var(--mut2); padding:0 !important; min-height:34px; font-size:13px; box-shadow:none !important; }
[class*="_qx_"] .stButton button:hover{ color:var(--red); background:transparent !important; }
/* the queue's add-box is search-only — hide its selected chips (the rows are the
   queue display), so a player isn't shown twice */
[class*="_q_ms"] [data-baseweb="tag"]{ display:none !important; }

/* ---- drafted players kept in the list (Show-drafted mode), struck through ---- */
.brow-drafted{ display:flex; align-items:center; gap:9px; padding:6px 12px; margin:2px 0;
  border:1px dashed var(--line); border-radius:7px; background:var(--panel2); opacity:.58; }
.brow-drafted .bd-img{ width:24px; height:24px; border-radius:50%; object-fit:cover;
  filter:grayscale(1); border:1px solid var(--line); }
.brow-drafted .bd-nm{ flex:1; font-size:12px; font-weight:600; text-decoration:line-through;
  color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.brow-drafted .bd-tag{ font-size:8.5px; font-weight:800; letter-spacing:.5px; color:var(--mut2);
  background:var(--line2); padding:2px 6px; border-radius:4px; }
.dr-avail tr.drafted{ opacity:.55; }
.dr-avail tr.drafted b{ text-decoration:line-through; color:var(--muted); }
.dr-avail tr.drafted img{ filter:grayscale(1); }
.dr-avail .drafted-tag{ font-size:8px; font-weight:800; color:var(--mut2); background:var(--line2);
  padding:1px 5px; border-radius:3px; margin-left:6px; letter-spacing:.5px; }

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
.rs{ display:flex; flex-direction:column; gap:3px; margin-bottom:16px; }
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
.cheat-head{ font-weight:800; color:#fff; text-align:center; padding:5px; font-size:12px;
  letter-spacing:1px; border-radius:7px; margin-bottom:2px; }
/* slim tier divider for the narrow by-position columns */
.ptier-mini{ font-weight:800; font-size:9.5px; letter-spacing:.8px; color:var(--mut2);
  text-transform:uppercase; padding:5px 2px 2px; margin-top:2px;
  border-top:1px solid var(--line2); }
.ptier-mini:first-child{ border-top:none; padding-top:1px; }
.cheat-row{ display:flex; align-items:center; gap:6px; padding:5px 8px; font-size:12px;
  border-bottom:1px solid var(--line2); }
.cheat-row .chs{ width:22px; height:22px; border-radius:50%; object-fit:cover; background:var(--line2); }
.cheat-row .cn{ font-weight:600; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.cheat-row .ca{ color:var(--mut2); font-size:10px; white-space:nowrap; }
.ptier{ font-weight:800; font-size:10px; letter-spacing:1.2px; padding:4px 9px; margin:11px 0 4px;
  border-radius:0 6px 6px 0; text-transform:uppercase; }

/* ---- pick queue ---- */
.dr-queue{ display:flex; flex-direction:column; gap:3px; }
.q-row{ display:flex; align-items:center; gap:6px; font-size:12.5px; padding:3px 8px;
  border:1px solid var(--line); border-radius:7px; background:#fff; }
.q-row.gone{ opacity:.45; text-decoration:line-through; }
.q-row .qn{ font-weight:600; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.q-row .qp{ font-size:10px; color:var(--mut2); }

/* ---- draft board grid ---- */
.dr-grid{ display:grid; gap:2px; min-width:0; width:100%; }
/* compact color-coded player cards — sized to fit the whole board in the column */
.dr-cell{ position:relative; min-height:50px; padding:4px 6px 16px; border-radius:7px;
  background:#fff; border:1px solid rgba(0,0,0,.05); overflow:hidden; }
.dr-cell .pk{ position:absolute; top:3px; right:5px; font-size:8.5px; font-weight:800;
  color:#27384c; opacity:.7; }
.dr-cell .c-name{ display:flex; flex-direction:column; line-height:1.02; max-width:100%;
  padding-right:14px; }
.dr-cell .c-name span{ font-weight:800; font-size:11px; color:#15212e; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.dr-cell .c-img{ display:none; }
/* roomy (≤8-team) boards keep a small headshot */
.dr-grid.wide .dr-cell{ min-height:58px; }
.dr-grid.wide .dr-cell .c-img{ display:block; position:absolute; right:5px; bottom:14px;
  width:26px; height:26px; border-radius:6px; object-fit:cover; object-position:top center;
  background:rgba(0,0,0,.06); }
.dr-grid.wide .dr-cell .c-name{ padding-right:30px; }
.dr-grid.wide .dr-cell.empty,.dr-grid.wide .dr-cell.onclk{ min-height:58px; }
.dr-cell .c-meta{ position:absolute; left:6px; bottom:3px; font-size:8.5px; font-weight:800;
  letter-spacing:.2px; color:#33465b; text-transform:uppercase; white-space:nowrap; }
/* position tints — RB blue, WR green, TE pink, QB purple, K/DST grey */
.dr-cell.pos-RB{ background:#c6e6f8; } .dr-cell.pos-WR{ background:#c8edcc; }
.dr-cell.pos-TE{ background:#f8ccd6; } .dr-cell.pos-QB{ background:#ddd2f3; }
.dr-cell.pos-K{ background:#e2e6ec; } .dr-cell.pos-DST,.dr-cell.pos-D{ background:#e2e6ec; }
.dr-cell.me{ outline:2px solid var(--blue); outline-offset:-2px; }
.dr-cell .c-meta .ktag{ font-weight:900; font-size:8px; color:#fff; background:var(--amber);
  border-radius:3px; padding:0 3px; margin-left:2px; }
.dr-cell .c-meta .rtag{ font-weight:900; font-size:8px; color:#fff; background:#7c3aed;
  border-radius:3px; padding:0 3px; margin-left:2px; }
.dr-cell.empty{ background:var(--panel2); border-color:var(--line2);
  display:flex; align-items:flex-start; min-height:50px; padding:4px 6px; }
.dr-cell.empty .pk{ position:static; opacity:.5; font-weight:700; }
.dr-cell.onclk{ background:var(--blue); display:flex; align-items:center; justify-content:center;
  gap:4px; border:none; box-shadow:0 2px 8px rgba(31,78,155,.3); min-height:50px; padding:4px; }
.dr-cell.onclk .oc-pk{ font-size:14px; font-weight:900; color:#fff; }
.dr-cell.onclk .oc-arrow{ font-size:14px; font-weight:900; color:#bcd2f7; }
.dr-colhead{ font-weight:800; font-size:10px; text-align:center; color:var(--muted);
  text-transform:uppercase; padding:5px 3px; background:var(--line2); border-radius:6px 6px 0 0;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  position:sticky; top:0; z-index:6; box-shadow:0 2px 4px rgba(0,0,0,.06); }
.dr-colhead.me{ background:var(--green); color:#fff; }
.dr-colhead.rd{ background:var(--blue); color:#fff; z-index:7; }
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
.dr-board-scroll{ max-height:calc(100vh - 360px); overflow:auto; border:1px solid var(--line);
  border-radius:10px; margin-bottom:8px; }

/* ---- whole-row clickable draft cards ---- */
[class*="_board_"] [data-testid="stVerticalBlock"]{ gap:3px; }
[class*="_brow_"]{ margin:0 !important; }
[class*="_brow_"] .stButton{ margin:0; }
[class*="_brow_"] .stButton button{ width:100%; text-align:left !important;
  justify-content:flex-start !important; align-items:center;
  padding:8px 58px 8px 46px; font-size:13px; font-weight:700; min-height:42px; line-height:1.25;
  border:1px solid var(--line); border-left-width:5px; border-radius:7px; background:#fff;
  color:var(--ink); white-space:normal; position:relative; }
/* keep the label left-aligned no matter how Streamlit wraps the button content.
   Streamlit 1.58 nests it as button(flex) > div(flex,justify:center) > span(flex)
   > markdown > p — so a plain text-align can't win; we force flex-start on the
   inner flex wrappers too. */
[class*="_brow_"] .stButton button div,
[class*="_brow_"] .stButton button span{ justify-content:flex-start !important; }
[class*="_brow_"] .stButton button div,
[class*="_brow_"] .stButton button p,
[class*="_brow_"] .stButton button [data-testid="stMarkdownContainer"]{
  text-align:left !important; }
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
  padding:6px 6px 6px 29px; min-height:32px; font-size:10.5px; line-height:1.2; font-weight:700; }
/* small headshot in the narrow columns; survival box hidden (no room) */
[class*="_board_QB"] .stButton button::before,[class*="_board_RB"] .stButton button::before,
[class*="_board_WR"] .stButton button::before,[class*="_board_TE"] .stButton button::before{
  width:21px; height:21px; left:4px; }
[class*="_board_QB"] .stButton button::after,[class*="_board_RB"] .stButton button::after,
[class*="_board_WR"] .stButton button::after,[class*="_board_TE"] .stButton button::after{ display:none; }

/* ---- empty lineup slot pill ---- */
.dr-lineup .slot .empty-pill{ display:inline-block; font-size:10px; font-weight:700;
  color:var(--mut2); border:1px dashed var(--line); border-radius:20px; padding:1px 11px;
  letter-spacing:.4px; text-transform:uppercase; }

/* ---- search input with a magnifier ---- */
[class*="dr_panel_board"] [data-testid="stTextInput"]{ position:relative; }
[class*="dr_panel_board"] [data-testid="stTextInput"]::before{ content:"⌕"; position:absolute;
  left:11px; top:50%; transform:translateY(-50%) scale(1.5); z-index:3; color:var(--mut2);
  font-weight:700; pointer-events:none; }
[class*="dr_panel_board"] [data-testid="stTextInput"] input{ padding-left:30px !important; }

/* ---- micro-interactions ---- */
[class*="_brow_"] .stButton button{ transition:transform .1s ease, box-shadow .1s ease,
  border-color .1s ease, background .1s ease; }
[class*="_brow_"] .stButton button:hover{ transform:translateY(-1px); }
[class*="_qrow_"] .stButton button, [class*="_pp_"] .stButton button,
[class*="_steals"] .stButton button, [class*="_traps"] .stButton button{
  transition:transform .1s ease, box-shadow .1s ease, border-color .1s ease, background .1s ease; }
.pcard,.recap{ transition:box-shadow .15s ease; }
.dr-cell.now{ animation:nowpulse 1.9s ease-in-out infinite; }
@keyframes nowpulse{
  0%,100%{ box-shadow:0 0 0 2px var(--blue), 0 3px 10px rgba(31,78,155,.20); }
  50%{ box-shadow:0 0 0 3px var(--blue), 0 5px 16px rgba(31,78,155,.40); } }

/* ---- mobile / tablet ---- */
@media (max-width:820px){
  .block-container{ padding:.5rem .7rem 2rem; }
  [class*="dr_panel_"]{ padding:11px 11px 9px; border-radius:11px; margin-bottom:10px; }
  .dr-status{ padding:10px 13px; gap:10px; } .dr-status .rd{ font-size:21px; }
  .dr-board-scroll{ max-height:300px; } .dr-grid{ font-size:10px; }
  h2{ font-size:1.15rem !important; }
  [class*="navbar"] [role="radiogroup"] label{ padding:8px 11px; font-size:12.5px; }
}
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


DARK = """
<style>
/* ===== Night Draft — dark hero (teal accent) ===== */
:root{
  --bg:#0e1424; --panel:#18213a; --panel2:#1f2b48; --line:#2c3a5c; --line2:#222f4a;
  --ink:#eaf0f9; --muted:#9fb2cc; --mut2:#6f82a0;
  --blue:#22d3aa; --green:#34d399; --amber:#fbbf24; --red:#f87171; --violet:#a78bfa;
  --accent:#22d3aa; --accent-soft:#13283a; --accent-line:#1f4a52;
  --qb:#f87171; --rb:#34d399; --wr:#60a5fa; --te:#fbbf24; --dst:#a78bfa;
  --shadow:0 2px 8px rgba(0,0,0,.4); --shadow-lg:0 8px 22px rgba(0,0,0,.55);
}
.stApp{ background:var(--bg); }
/* keep the Streamlit header transparent in dark too — painting it solid made it
   overlap & clip the topbar logo that sits pulled-up beneath it. */
[data-testid="stHeader"]{ background:transparent !important; }
/* big light surfaces → dark panels (board player cards keep their colour tints) */
.sc-card,.lb,.rs,.pcard,.dr-status,.dr-avail,.dr-predict,.dr-grid,
.dr-lastpick,.dr-queue,[class*="dr_panel_"],[class*="dr_topbar"],.dr-plan,.dr-grade{
  background:var(--panel) !important; border-color:var(--line) !important; }
.dr-cell.empty{ background:var(--panel2) !important; border-color:var(--line) !important; }
.dr-cell.onclk{ background:var(--blue) !important; }
.dr-colhead{ background:var(--panel2) !important; color:var(--muted) !important; }
.dr-colhead.me{ background:var(--green) !important; color:#fff !important; }
.dr-colhead.rd,.dr-rdlabel{ background:var(--blue) !important; color:#fff !important; }
.tk-chip,.lb-pc{ background:var(--panel2) !important; }
[class*="_brow_"] .stButton button,[class*="_qrow_"] .stButton button{
  background:var(--panel) !important; color:var(--ink) !important; border-color:var(--line) !important; }
.dr-status .now,.dr-cell.me{ background:#1d2c20 !important; }
/* streamlit widgets */
[data-baseweb="select"]>div,[data-testid="stTextInput"] input,
[data-baseweb="popover"] [role="listbox"],[data-baseweb="menu"]{
  background:var(--panel) !important; color:var(--ink) !important; border-color:var(--line) !important; }
[data-testid="stRadio"] [role="radiogroup"]{ background:var(--panel2) !important; }
[data-testid="stRadio"] [role="radiogroup"] label:has(input:checked){
  background:var(--panel) !important; color:var(--ink) !important; }
[data-baseweb="tab"]{ color:var(--muted) !important; }
[data-testid="stExpander"]{ background:var(--panel) !important; border-color:var(--line) !important; }
[data-testid="stExpander"] summary{ color:var(--ink) !important; }
.neon-tag{ color:var(--mut2) !important; }
/* secondary buttons hardcode a white bg in light mode → unreadable in dark
   (e.g. the saved-league buttons on the picker). Repaint them for dark. */
.stButton>button[kind="secondary"]{ background:var(--panel) !important;
  color:var(--ink) !important; border-color:var(--line) !important; }
.stButton>button[kind="secondary"]:hover{ border-color:var(--blue) !important;
  color:var(--blue) !important; }
/* primary CTA: dark ink on the bright teal for legible contrast */
.stButton>button[kind="primary"],.stButton>button[kind="primaryFormSubmit"]{
  color:#06251c !important; }
/* text areas + their placeholders were near-invisible on dark */
[data-testid="stTextArea"] textarea,[data-baseweb="textarea"] textarea{
  background:var(--panel) !important; color:var(--ink) !important; border-color:var(--line) !important; }
[data-testid="stTextArea"] textarea::placeholder,
[data-testid="stTextInput"] input::placeholder{ color:var(--mut2) !important; opacity:1; }
[class*="dr_topbar"] .stButton button{ background:var(--panel2) !important;
  color:var(--ink) !important; border-color:var(--line) !important; }
[class*="tb_war"] .stButton button{ background:var(--blue) !important; color:#fff !important;
  border-color:var(--blue) !important; }
/* live Picks feed + intel cards */
.dr-picks .pf-head{ background:var(--panel) !important; }
.pf-card{ background:var(--panel) !important; border-color:var(--line) !important; }
.pf-card.me{ background:#16263f !important; }
.pf-card.yours{ background:var(--blue) !important; }
.pf-img{ background:var(--panel2) !important; }
.pf-pred.pf-warn{ background:#3a1d22 !important; }
.dr-grade,.dr-plan{ background:var(--panel) !important; border-color:var(--line) !important; }
.dr-strategy{ background:#332a12 !important; border-color:#6a5320 !important; color:#e7c172 !important; }
.dr-strategy b{ color:#f3d98a !important; }
.g-pc.g-ok{ background:#173a28 !important; } .g-pc.g-low{ background:#3a1d22 !important; }
.dr-room.wait{ background:#16302a !important; border-color:#1c5a44 !important; color:#7fdcb4 !important; }
.dr-room.lean{ background:#33280f !important; border-color:#6a5320 !important; color:#e7c172 !important; }
.dr-room.grab{ background:#3a1d22 !important; border-color:#7a2e2e !important; color:#f0a3a3 !important; }
.dr-ai{ background:#1a2230 !important; border-color:#2c3b52 !important; border-left-color:#5f82c9 !important; color:#dbe4f0 !important; }
.dr-ai-q{ color:#9fb0c5 !important; }
.dr-ai-a{ background:#171c24 !important; border-color:#2a313c !important; color:#dbe4f0 !important; }
.dr-runban{ background:#33231a !important; border-color:#6a4127 !important; color:#f0b48a !important; }
.dr-runban.grab{ background:#3a1d22 !important; border-color:#7a2e2e !important; color:#f0a3a3 !important; }
.dr-actnow,.dr-buzzlist{ background:#161b22 !important; border-color:#2a313c !important; }
.an-h,.bz-h{ color:#9aa4b0 !important; }
.an-row,.bz-row{ border-top-color:#222831 !important; }
.an-nm,.bz-nm{ color:#e6ebf2 !important; }
.an-tm,.bz-tm{ color:#8a929c !important; }
.an-sv{ color:#f0a585 !important; }
.bz-ct{ color:#f0a585 !important; }
.dr-buzz.up{ background:#33231a !important; color:#f0b48a !important; border-color:#6a4127 !important; }
.dr-buzz.down{ background:#1a2330 !important; color:#9fc0e0 !important; border-color:#2c3f55 !important; }
.dr-rookhist{ background:#1e1830 !important; border-color:#3a2c52 !important; }
.rh-h{ color:#c0a3e6 !important; }
.rh-row{ border-top-color:#2a2140 !important; }
.rh-nm{ color:#e6ebf2 !important; }
.rh-tm,.rh-adp{ color:#9aa4b0 !important; }
.rh-slot{ color:#c0a3e6 !important; }
.rh-up{ background:#33265a !important; color:#cbb0f0 !important; }
.rh-foot{ color:#9a8cb8 !important; }
.dr-needs{ background:#161b22 !important; border-color:#2a313c !important; }
.ns-h{ color:#9aa4b0 !important; }
.ns-fill{ background:#21272f !important; color:#717b86 !important; border-color:#2a313c !important; }
.ns-open{ background:#33280f !important; color:#e7c172 !important; border-color:#6a5320 !important; }
.ns-open.ns-QB{ background:#3a1d22 !important; color:#f0a3a3 !important; border-color:#7a2e2e !important; }
.ns-open.ns-RB{ background:#16302a !important; color:#7fdcb4 !important; border-color:#1c5a44 !important; }
.ns-open.ns-WR{ background:#1a2330 !important; color:#9fc0e0 !important; border-color:#2c3f55 !important; }
.ns-open.ns-TE{ background:#33280f !important; color:#e7c172 !important; border-color:#6a5320 !important; }
/* keeper/empty board tints that read on dark */
.dr-cell.empty .pk{ color:var(--mut2) !important; }
[data-testid="stToggle"]{ color:var(--ink) !important; }
/* spotlight inner surfaces: the stat cells + chips used hardcoded light
   backgrounds (#f7f9fb / #f1f5f9) — invisible under dark text overrides. Re-tint
   them so GAMES / RUSH YDS / Snap% etc. stay readable in war-room mode. */
.pc-stat{ background:var(--panel2) !important; border-color:var(--line) !important; }
.pc-v{ color:var(--ink) !important; } .pc-k{ color:var(--mut2) !important; }
.pc-ochip{ background:var(--panel2) !important; border-color:var(--line) !important;
  color:var(--muted) !important; } .pc-ochip b{ color:var(--ink) !important; }
.pc-marg{ background:#2a2247 !important; color:#c8b3f5 !important; }
.pc-syn{ background:#241d3a !important; color:#c8b3f5 !important; }
.pc-fc{ color:var(--muted) !important; } .pc-fc b{ color:var(--ink) !important; }
.pc-img{ background:var(--panel2) !important; border-color:var(--line) !important; }
/* text-input wrapper (search): the <input> goes dark but its baseweb wrapper
   stayed white, leaving a white frame around the field. */
[data-baseweb="base-input"],[data-testid="stTextInputRootElement"]{
  background:var(--panel) !important; border-color:var(--line) !important; }
/* draft-recap card was a bare light surface */
.recap{ background:var(--panel) !important; border-color:var(--line) !important; }
.recap .rc-row,.recap td,.recap th{ border-color:var(--line2) !important; }
/* ---- dark sweep: granular surfaces that hardcoded white in light mode ---- */
.dr-lineup .slot,.neonwrap,.cs-col,.cheat-col,.cheat-row,.dr-needs .need,
.dr-onclock .tk-chip{ background:var(--panel) !important; border-color:var(--line) !important; }
.dr-lineup .slot .nm{ color:var(--ink) !important; }
.dr-lineup .slot.empty .nm,.empty-pill,.cs-tm,.cheat-tm{ color:var(--mut2) !important; }
.cs-head,.cheat-head{ color:#fff !important; }
.cs-row,.cheat-row{ border-top-color:var(--line2) !important; }
.cs-nm,.cheat-nm{ color:var(--ink) !important; }
.mk-src,.pc-stat{ background:var(--panel2) !important; color:var(--muted) !important; }
.st-row.steal{ background:#16302a !important; } .st-row.trap{ background:#3a1d22 !important; }
.dr-needs .need{ color:var(--ink) !important; }
/* draft grid: light pastel cells + dark text → dark position-tinted cells + light text */
.dr-cell.pos-QB{ background:#2a2138 !important; }
.dr-cell.pos-RB{ background:#16302a !important; }
.dr-cell.pos-WR{ background:#16263f !important; }
.dr-cell.pos-TE{ background:#33271a !important; }
.dr-cell.pos-K,.dr-cell.pos-DST,.dr-cell.pos-D{ background:var(--panel2) !important; }
.dr-cell.me{ background:#16302a !important; }
.dr-cell .c-name span{ color:var(--ink) !important; }
.dr-cell .c-meta{ color:var(--muted) !important; }
/* intel alert chips (Tier cliff / position run / needs) */
.alert{ background:var(--panel2) !important; border-color:var(--line) !important;
  color:var(--ink) !important; }
.alert.cliff{ background:#3a1d22 !important; border-color:#7a2e2e !important; color:#f0a3a3 !important; }
.alert.run{ background:#33280f !important; border-color:#6a5320 !important; color:#e7c172 !important; }
.alert.need{ background:#16263f !important; border-color:#2f5a8c !important; color:#9cc4f5 !important; }
/* spotlight semantic chips: re-tint light pastels for dark */
.pc-flag.ok,.pc-boom{ background:#173a28 !important; color:#7fdcb4 !important; }
.pc-flag.ques{ background:#33280f !important; color:#e7c172 !important; }
.pc-flag.out,.pc-bust{ background:#3a1d22 !important; color:#f0a3a3 !important; }
.pc-verdict.grab{ background:#3a1d22 !important; color:#f0a3a3 !important; }
.pc-verdict.lean{ background:#33280f !important; color:#e7c172 !important; }
.pc-verdict.wait{ background:#16263f !important; color:#9cc4f5 !important; }
.pc-verdict.ok{ background:var(--panel2) !important; color:var(--muted) !important; }
/* Streamlit ':gray[…]' text (ADP · team · bye · #rank in the ranking rows) is
   hardcoded to a dark slate (rgba(49,51,63,…)) meant for light mode — unreadable
   on dark. Lighten just that gray (other colored chips keep their colour). */
.stMarkdownColoredText[style*="49, 51, 63"]{ color:var(--muted) !important; }
.bal-chip.bal-ok{ background:#173a28 !important; color:#7fdcb4 !important; }
.bal-chip.bal-warn{ background:#33280f !important; color:#e7c172 !important; }
.mk-tag.mk-ok{ background:var(--panel2) !important; color:var(--muted) !important; }
.mk-tag.mk-split{ background:#33280f !important; color:#e7c172 !important; }
.mk-src{ background:var(--panel2) !important; border-color:var(--line) !important; }
.cs-head{ color:#fff !important; }
</style>
"""


def inject(st, dark: bool = False) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if dark:
        st.markdown(DARK, unsafe_allow_html=True)
