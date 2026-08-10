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
  /* --- Bloody Sunday. Crimson has exactly TWO jobs: the brand, and genuine
     urgency. Every other signal moves off red, or the brand stops meaning
     anything on a screen that already shouts in red (survival %, byes, reaches). --- */
  --bg:#f6f3f4; --panel:#ffffff; --panel2:#efeaec; --line:#e3dcdf; --line2:#efeaec;
  --ink:#1f1d1e; --muted:#6c6367; --mut2:#7a7277;
  --crimson:#e0043f; --crimson-d:#b00335;
  /* NB --blue is the ACCENT alias, not a hue: it was #0d9488 teal before. It
     drives buttons, active tabs and focus rings, so it follows the brand. The
     real blue lives on --wr. */
  --blue:#e0043f; --green:#1d7a55; --red:#b00335; --amber:#a8570d; --violet:#7a2b6b;
  --accent:#e0043f; --accent-fill:#e0043f; --accent-soft:#fdeaf0; --accent-line:#f6c2d3;
  /* QB moves off red — it is the one position colour that collides with the brand,
     and a QB chip that reads as an alert is worse than an unfamiliar hue. */
  --qb:#7a2b6b; --rb:#2d836f; --wr:#2f6fb5; --te:#a8570d; --k:#7a7277; --dst:#3273c8;
  --shadow:0 1px 2px rgba(31,29,30,.06), 0 1px 3px rgba(31,29,30,.06);
  --shadow-lg:0 4px 14px rgba(31,29,30,.10);
}
/* Sora as the display face for brand, section heads, and player names */
h1,h2,h3,.bs-word,.dr-h,.dr-status .rd,.tb-name,.pc-name,.pf-nm,.an-nm,.bz-nm,
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
.bs-logo{ display:inline-flex; align-items:center; gap:9px; line-height:1; }
.bs-mark{ flex:none; border-radius:5px; }
.bs-word{ font-style:italic; font-weight:900; letter-spacing:-.04em; color:var(--ink);
  font-family:"Helvetica Neue",Arial,sans-serif; }
.bs-word em{ font-style:italic; color:var(--crimson); }

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
[class*="navbar"] [role="radiogroup"] label>:first-child{ display:none; }
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
.dr-health{ display:inline-flex; align-items:center; gap:9px; margin-left:10px; }
.dr-health .hz{ display:inline-flex; align-items:center; gap:4px; font-size:10px;
  font-weight:700; color:var(--mut2); text-transform:uppercase; letter-spacing:.3px; }
.dr-health .hz i{ width:6px; height:6px; border-radius:50%; display:inline-block; }
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
/* draft board is pinned on top: the FULL board renders (every round), capped to a
   compact height and scrollable — the user can freely scroll it to browse other
   rounds, and a tiny script (current_pick_scroll_html, run via components.html
   right after this markdown) snaps it back to the current pick after every draft
   action, since that's a full script rerun. */
[class*="dr_board_top"]{ max-height:var(--dr-board) !important; overflow-y:auto !important;
  overflow-x:auto !important; margin-bottom:8px; }
[class*="dr_board_top"] .dr-grid{ min-width:0; }
/* compact-ish cells in the pinned board (headshots dropped) — still 6 rounds, but
   with real row height so it doesn't feel cramped */
[class*="dr_board_top"] .dr-cell,
[class*="dr_board_top"] .dr-grid.wide .dr-cell{ min-height:56px; padding:4px 6px 14px; }
[class*="dr_board_top"] .dr-grid.wide .dr-cell .c-img{ display:none; }
[class*="dr_board_top"] .dr-grid.wide .dr-cell .c-name{ padding-right:14px; }
[class*="dr_board_top"] .dr-cell.empty,
[class*="dr_board_top"] .dr-grid.wide .dr-cell.empty,
[class*="dr_board_top"] .dr-cell.onclk,
[class*="dr_board_top"] .dr-grid.wide .dr-cell.onclk{ min-height:56px; }
[class*="dr_board_top"] .dr-colhead{ padding:4px 3px; font-size:9.5px; }
[class*="dr_board_top"] .dr-rdlabel{ font-size:11px; }
[class*="dr_board_top"] .dr-rdlabel .dr-snk{ font-size:12px; }
/* the three draft columns fill the rest of one screen so their bottoms align and the
   page itself never scrolls — each scrolls its own content internally */
/* The panel itself is a FLEX ITEM (Streamlit's stVerticalBlock is display:flex)
   with flex-grow:1 — so a plain `height`, even !important, is only used as the
   flex-basis and then OVERRIDDEN by flex-grow distributing the parent's full
   content height to it (confirmed empirically: height:400px!important computed
   to 1655px anyway). The fix is the `flex` SHORTHAND with grow/shrink pinned to
   0, which stops the flex algorithm from resizing it past the given basis. */
/* Height is DERIVED from the two things above it rather than guessed. The old
   `calc(100vh - 800px)` hard-coded a single chrome+board total; measured live it is
   really 251px of chrome + 400px of board + ~13px of gaps = 664px, so the panels
   came up 136px short and left a band of dead space under all three columns. Any
   zoom level or monitor that isn't the one the 800 was tuned on drifts the same
   way. Now: viewport minus real chrome minus whatever the board actually took. */
:root{ --dr-chrome:264px; --dr-board:min(400px, 34vh); }
[class*="dr_panel_board"],[class*="dr_panel_intel"]{
  flex:0 0 calc(100vh - var(--dr-chrome) - var(--dr-board)) !important;
  height:calc(100vh - var(--dr-chrome) - var(--dr-board)) !important;
  min-height:260px !important; overflow-y:auto !important; overflow-x:hidden !important; }
/* SHORT viewports. The 800px subtrahend above assumes a tall screen; on a 13"
   laptop (~750-800px of viewport) calc() floors to the 260px minimum, so all
   three war-room panels collapse to about one row each while the pinned board
   still claims its full 400px. The only other media query in this stylesheet is
   a WIDTH query, so nothing rescued this. Rebalance in viewport-relative units
   as the screen shortens — these must stay AFTER the rule above to win. */
/* The @media (max-height:1000px / 800px) blocks that used to rebalance this were
   removed: they existed only because the split was fixed. `min(400px, 34vh)` now
   shrinks the board on short screens and the panel formula follows it for free. */
}
/* the flexbox chain (stHorizontalBlock -> stColumn -> stVerticalBlock*) must be
   allowed to SHRINK (min-height:0) for the panel's own height+overflow-y:auto to
   actually clip its content — otherwise a flex ancestor's default min-height:auto
   refuses to shrink below its content's natural height, so the whole COLUMN (and
   with it the page) grows tall instead of the panel scrolling internally. Scoped
   via :has() to just the row containing our draft columns. */
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_board"]),
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_boardc"]),
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_intel"]){ align-items:stretch; }
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_board"]) .stColumn,
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_boardc"]) .stColumn,
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_intel"]) .stColumn,
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_board"]) [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_boardc"]) [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_intel"]) [data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_board"]) [data-testid="stVerticalBlock"],
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_boardc"]) [data-testid="stVerticalBlock"],
[data-testid="stHorizontalBlock"]:has([class*="dr_panel_intel"]) [data-testid="stVerticalBlock"]{
  min-height:0 !important; }
[class*="dr_panel_"] [data-testid="stExpander"]{ background:var(--panel2); border:1px solid var(--line);
  border-radius:10px; margin-top:8px; }
[class*="dr_panel_"] [data-testid="stExpander"] summary{ font-size:11px; font-weight:800;
  text-transform:uppercase; letter-spacing:.5px; color:var(--muted); }

/* segmented pill toggles for the List/By-position + UDK/Value radios */
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"]{ gap:0; padding:3px;
  background:var(--line2); border:1px solid var(--line); border-radius:9px; display:inline-flex; }
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"] label{ padding:4px 13px;
  margin:0; border-radius:6px; font-size:11.5px; font-weight:700; color:var(--muted); cursor:pointer; }
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"] label>:first-child{ display:none; }
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"] label:hover{ color:var(--ink); }
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked){
  background:var(--panel); color:var(--ink); box-shadow:var(--shadow); }

/* ---- three things these pill radios need, all easy to miss ----
   1. Hiding Streamlit's styled circle (above) leaves the RAW <input> visible, so
      every "pill" grew a native radio dot. Hide it without display:none, which
      would cost the click target and keyboard focus.
   2. Streamlit's inner <p> carries its own colour, so colouring the LABEL does
      nothing — selected and unselected both rendered at the theme text colour and
      the only surviving cue was the background.
   3. Which is why the selected pill went invisible: near-white text on a pale
      selected background. Both now come from theme tokens, so they move together.
*/
[class*="dr_panel_board"] [role="radiogroup"] label>input,
[class*="_posf"] [role="radiogroup"] label>input{
  position:absolute !important; opacity:0 !important; width:1px !important;
  height:1px !important; margin:0 !important; pointer-events:none; }
/* Colour the TEXT node directly rather than the label. `color:inherit` on the
   markdown container loses to Streamlit's own rule, so the accent never reached
   the glyphs and every option rendered at the theme text colour — selected and
   unselected alike. Explicit beats clever here. */
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"] label
  [data-testid="stMarkdownContainer"] p,
[class*="_posf"] [data-testid="stRadio"] [role="radiogroup"] label
  [data-testid="stMarkdownContainer"] p{ color:var(--muted) !important; }
[class*="dr_panel_board"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked)
  [data-testid="stMarkdownContainer"] p{ color:var(--ink) !important; }
[class*="_posf"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked)
  [data-testid="stMarkdownContainer"] p{ color:var(--accent) !important; }

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
  background:var(--accent-soft) !important; color:var(--accent) !important;
  box-shadow:inset 0 0 0 1px var(--accent-line) !important; }

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

/* ---- full roster panel: every slot, filled or not ---- */
.dr-lineup.fr .fr-head{ display:flex; align-items:baseline; gap:8px; flex-wrap:wrap;
  font-size:12px; color:var(--muted); padding:2px 0 7px; border-bottom:1px solid var(--line);
  margin-bottom:5px; }
.dr-lineup.fr .fr-head b{ color:var(--ink); font-size:13.5px; }
.dr-lineup.fr .fr-need{ margin-left:auto; font-weight:700; color:var(--accent); }
.dr-lineup.fr .fr-div{ font-size:9.5px; font-weight:800; letter-spacing:.12em;
  text-transform:uppercase; color:var(--faint,var(--muted)); margin:9px 0 3px; }
.dr-lineup.fr .fr-meta{ margin-left:auto; font-size:10.5px; color:var(--muted);
  white-space:nowrap; }
.dr-lineup.fr .slot.empty{ opacity:.85; }
.dr-lineup.fr .slot.extra .pos{ opacity:.5; }

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

/* ---- rankings list: no height of its own — the outer panel (dr_panel_board,
   height:calc(100vh - 800px)) is the ONLY scroll region. A second independent
   max-height here used to be shorter than the outer panel and leave a dead gap
   below the list; letting it size to content and scroll with the panel fixes that. */
[class*="_ranklist"]{ overflow-x:hidden; padding-right:4px; margin-top:2px; }

/* ---- live 'Picks' rail (FantasyPros-style) — same reasoning: no independent
   height/scroll, the outer dr_panel_intel panel handles it alone. ---- */
.dr-picks{ display:flex; flex-direction:column; gap:5px; padding-right:3px; margin-bottom:8px; }
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
.cs-row.drafted{ opacity:.5; }
.cs-row.drafted .cs-nm{ text-decoration:line-through; }
.lm-track{ flex:1; max-width:46px; height:7px; background:var(--line2); border-radius:4px;
  overflow:hidden; margin-left:auto; }
.lm-track i{ display:block; height:100%; }
.lm-wrap{ display:flex; align-items:center; gap:5px; justify-content:flex-end; font-size:12px; }

/* ---- Juice's Value rows: grid layout (name + ADP/ECR/Δ/LANDMINE), same trick as
   the Suggestions rows so a real ☆ button can sit beside each row. ---- */
:root{ --jc-cols:26px minmax(0,1fr) 40px 40px 46px 88px; }
.jc-colhead{ display:grid; grid-template-columns:var(--jc-cols); align-items:center; gap:8px;
  padding:4px 6px 6px; color:var(--mut2); font-size:9.5px; font-weight:800; letter-spacing:.06em;
  text-transform:uppercase; border-bottom:1px solid var(--line2); margin-bottom:2px; }
.jc-colhead .c{ text-align:center; } .jc-colhead .r{ text-align:right; }
.jc-row{ display:grid; grid-template-columns:var(--jc-cols); align-items:center; gap:8px;
  padding:5px 6px; border-radius:8px; }
.jc-row:hover{ background:var(--panel2); }
.jc-row .c{ text-align:center; font-weight:700; font-size:12.5px; font-variant-numeric:tabular-nums; }
.jc-row .r{ text-align:right; }
.jc-rk{ text-align:center; color:var(--mut2); font-weight:700; font-size:12px; }
.jc-who{ display:flex; align-items:center; gap:8px; min-width:0; }
.jc-nm-wrap{ min-width:0; }
.jc-nm{ font-weight:800; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.jc-row .pp{ font-size:10px; color:var(--mut2); }
.jc-row.drafted{ opacity:.5; }
.jc-row.drafted .jc-nm{ text-decoration:line-through; }

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
/* traded pick: accent left bar + a small "⇄ new owner" chip (bottom-right) */
.dr-cell.traded{ box-shadow:inset 3px 0 0 var(--amber); }
.dr-trade{ position:absolute; right:5px; bottom:3px; max-width:calc(100% - 12px);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:8px;
  font-weight:900; letter-spacing:.2px; color:#fff; background:var(--amber);
  border-radius:4px; padding:0 3px; }
.dr-cell.empty .dr-trade{ bottom:auto; top:50%; right:50%; transform:translate(50%,-50%);
  background:transparent; color:var(--amber); font-size:9px; }
.dr-cell.onclk .dr-trade{ color:#fff; background:rgba(0,0,0,.28); }
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
.dr-strat{ background:rgba(34,211,170,.10); border:1px solid rgba(34,211,170,.40);
  border-radius:8px; padding:6px 11px; margin:2px 0 6px; font-size:.84rem;
  color:var(--ink); line-height:1.35; }
.dr-strat .st-tgt{ display:block; color:var(--muted); margin-top:1px; }
.dr-strat .st-tgt b{ color:var(--blue); }
.dr-rdlabel{ display:flex; flex-direction:column; align-items:center; justify-content:center;
  gap:1px; font-weight:800; font-size:12px; color:#fff; background:var(--blue); border-radius:6px; }
.dr-rdlabel .dr-snk{ font-size:13px; line-height:1; font-weight:700; opacity:.7; }

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

/* ---- Suggestions rows: clean columnar layout (avatar/name + ADP/RANK/VALUE/SURVIVAL) ---- */
.sg-colhead{ display:grid; grid-template-columns:var(--sg-cols); align-items:center; gap:8px;
  padding:4px 6px 6px; color:var(--mut2); font-size:9.5px; font-weight:800; letter-spacing:.06em;
  text-transform:uppercase; border-bottom:1px solid var(--line2); margin-bottom:2px; }
.sg-colhead .r{ text-align:center; }
:root{ --sg-cols:minmax(0,1fr) 42px 48px 56px 78px; }
.sg-row{ display:grid; grid-template-columns:var(--sg-cols); align-items:center; gap:8px;
  padding:5px 6px; border-radius:8px; }
.sg-row:hover{ background:var(--panel2); }
.sg-who{ display:flex; align-items:center; gap:9px; min-width:0; }
.sg-av{ width:30px; height:30px; border-radius:50%; object-fit:cover; flex:none;
  background:var(--panel2); border:1px solid var(--line); }
.sg-nm-wrap{ min-width:0; }
.sg-nm{ font-weight:800; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sg-tag{ font-size:8px; font-weight:900; color:#fff; padding:1px 4px; border-radius:4px;
  margin-left:4px; vertical-align:middle; white-space:nowrap; }
.sg-tag.rook{ background:var(--te); } .sg-tag.fall{ background:var(--red); }
.sg-tag.stack{ background:var(--violet); } .sg-tag.bye{ background:var(--red); }
.sg-tag.value{ background:var(--green); } .sg-tag.landmine{ background:var(--red); }
.sg-sub{ font-size:10.5px; color:var(--muted); font-weight:600; margin-top:1px;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sg-sub .dot{ display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:4px;
  vertical-align:middle; }
.sg-num{ text-align:center; font-weight:700; font-variant-numeric:tabular-nums; font-size:12px;
  color:var(--muted); }
.sg-rank{ text-align:center; font-weight:800; font-size:11.5px; }
.sg-val{ justify-self:center; font-weight:800; font-size:11.5px; font-variant-numeric:tabular-nums;
  padding:2px 8px; border-radius:7px; background:var(--accent-soft); color:var(--blue); }
.sg-val.lo{ background:var(--line2); color:var(--mut2); }
.sg-surv{ display:flex; flex-direction:column; gap:3px; }
.sg-surv .lab{ font-size:10.5px; font-weight:800; font-variant-numeric:tabular-nums; text-align:right; }
.sg-track{ height:5px; border-radius:3px; background:var(--line2); overflow:hidden; }
.sg-track>i{ display:block; height:100%; border-radius:3px; }
/* the star + Draft buttons flank the html row inside their own thin columns */
[class*="_sgstar2_"] .stButton button{ background:transparent !important; border:none !important;
  color:var(--mut2) !important; font-size:16px !important; padding:0 !important; min-height:0 !important;
  box-shadow:none !important; }
[class*="_sgstar2_"] .stButton button:hover{ color:var(--blue) !important; }
[class*="_sgdraft2_"] .stButton button{ background:var(--accent) !important; color:#fff !important;
  border:none !important; font-weight:800 !important; border-radius:8px !important; }
[class*="_sgdraft2_"] .stButton button:hover{ filter:brightness(1.08); }

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

/* ---- Player card (popup) — the click-to-inspect card inside st.dialog ---- */
.pcd{ font-size:13px; }
.pcd-top{ display:flex; align-items:center; gap:12px; margin-bottom:10px; }
.pcd-img{ width:54px; height:54px; border-radius:50%; object-fit:cover;
  background:var(--panel2); flex:none; }
.pcd-id{ min-width:0; }
.pcd-nm{ font-size:19px; font-weight:800; line-height:1.15; }
.pcd-bits{ font-size:12px; color:var(--mut2); margin-top:2px; }
.pcd-chips{ display:flex; flex-wrap:wrap; gap:5px; }
.pcd-chiprow{ margin-bottom:12px; }
.pcd-chip{ font-size:11px; font-weight:700; padding:3px 8px; border-radius:6px;
  background:var(--panel2); color:var(--muted); }
.pcd-c-red{ background:#fdecec; color:#b3261e; } .pcd-c-green{ background:#eaf7ef; color:#1c7a44; }
.pcd-c-amber{ background:#fdf3e3; color:#8a5a06; } .pcd-c-pink{ background:#fbeaf0; color:#8a2b4c; }
.pcd-inj-ok{ background:#eaf7ef; color:#1c7a44; } .pcd-inj-ques{ background:#fdf3e3; color:#8a5a06; }
.pcd-inj-out{ background:#fdecec; color:#b3261e; }
.pcd-stats{ display:grid; grid-template-columns:repeat(auto-fit,minmax(90px,1fr)); gap:8px;
  margin-bottom:10px; }
.pcd-stat{ background:var(--panel2); border-radius:8px; padding:8px 10px; }
.pcd-sl{ font-size:10px; color:var(--mut2); text-transform:uppercase; letter-spacing:.4px; }
.pcd-sv{ font-size:20px; font-weight:800; line-height:1.2; }
.pcd-tn{ font-size:11px; font-weight:600; color:var(--mut2); }
.pcd-vtag{ margin-left:auto; flex:none; font-size:12px; font-weight:800; padding:5px 11px; border-radius:8px; letter-spacing:.3px; }
.pcd-sec1{ border-top:none; padding-top:0; margin-top:0; }
.pcd-call{ border-radius:8px; padding:9px 11px; font-size:12.5px; line-height:1.45;
  margin-bottom:12px; background:var(--panel2); color:var(--muted); }
.pcd-call-grab{ background:#fdecec; color:#8c2320; } .pcd-call-wait{ background:#fdf3e3; color:#7a4f06; }
.pcd-sec{ border-top:1px solid var(--line2); padding-top:10px; margin-top:10px; }
.pcd-h{ font-size:10.5px; font-weight:800; text-transform:uppercase; letter-spacing:.5px;
  color:var(--mut2); margin-bottom:7px; display:flex; align-items:center; gap:7px; }
.pcd-sub{ font-weight:600; letter-spacing:0; text-transform:none; color:var(--mut2); }
.pcd-tag{ margin-left:auto; font-size:10.5px; font-weight:800; padding:2px 7px; border-radius:6px; }
.pcd-t-easy{ background:#eaf7ef; color:#1c7a44; } .pcd-t-hard{ background:#fdecec; color:#b3261e; }
.pcd-t-avg{ background:#eef1f4; color:#55606b; }
.pcd-wk{ display:grid; grid-template-columns:38px 38px 1fr 84px; align-items:center; gap:8px;
  padding:3px 0; }
.pcd-wkn{ font-size:11px; color:var(--mut2); font-weight:700; }
.pcd-opp{ font-size:12px; font-weight:800; }
.pcd-rk{ font-size:10.5px; color:var(--mut2); text-align:right; }
.pcd-track{ height:6px; border-radius:4px; background:var(--panel2); overflow:hidden; }
.pcd-fill{ display:block; height:100%; border-radius:4px; }
.pcd-easy{ background:#3fae72; } .pcd-avg{ background:#9aa6b2; } .pcd-hard{ background:#d9534f; }
.pcd-none{ font-size:12px; color:var(--mut2); font-style:italic; }
.pcd-mk{ display:grid; grid-template-columns:1fr 46px 46px; font-size:12px; padding:2px 0; }
.pcd-mk span:first-child{ color:var(--mut2); }
.pcd-mv{ text-align:right; font-weight:700; } .pcd-md{ text-align:right; color:var(--mut2); }
.pcd-grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(64px,1fr)); gap:8px;
  font-size:13px; font-weight:700; }

/* ---- Home: hero league up front, the rest quiet ----
   Cards are the st.container, never a markdown wrapper div — a div from
   st.markdown does not enclose a widget, which is what left the buttons outside
   the box. Note also that the container key must not be a PREFIX of any widget
   key inside it, or [class*=] styles the widget as a second card. */
.hm-h{ font-size:11px; font-weight:800; letter-spacing:.14em; text-transform:uppercase;
  color:var(--mut2); margin:16px 0 9px; }
[class*="st-key-hmhero_"]{ background:var(--panel); border:1px solid var(--line);
  border-top:3px solid var(--mut2); border-radius:12px; padding:16px 18px 14px; }
.hm-heroline{ display:flex; align-items:center; gap:10px; }
.hm-heroname{ font-size:19px; font-weight:800; letter-spacing:-.015em; }
.hm-badge{ font-size:9.5px; font-weight:800; letter-spacing:.07em; text-transform:uppercase;
  padding:3px 8px; border-radius:6px; }
.hm-meta{ font-size:11.5px; color:var(--mut2); margin:2px 0 12px; }
.hm-tile{ background:var(--panel2); border-radius:9px; padding:10px 12px; }
/* These three were used by the prep desk AND Home but never defined — which is why
   neither screen had any type hierarchy in its tiles. */
.tl{ font-size:9.5px; font-weight:800; letter-spacing:.11em; text-transform:uppercase;
  color:var(--mut2); line-height:1.5; }
.tv{ font-size:20px; font-weight:800; line-height:1.25; letter-spacing:-.01em;
  font-variant-numeric:tabular-nums; }
.ts{ font-size:11px; color:var(--mut2); line-height:1.45; }
.hm-of{ font-size:13px; font-weight:700; color:var(--mut2); }
.hm-wl{ font-size:9.5px; font-weight:800; letter-spacing:.11em; text-transform:uppercase;
  color:var(--mut2); margin-bottom:8px; }
.hm-note{ display:flex; gap:8px; align-items:flex-start; font-size:12.5px; line-height:1.45;
  padding:9px 11px; border-radius:8px; margin-bottom:7px; }
.hm-note i{ width:7px; height:7px; border-radius:50%; flex:none; margin-top:5px; }
/* scoped to the what's-left panel: the previous :last-child rule matched the last
   column of EVERY horizontal block inside the hero, so a divider appeared between
   the tiles and again between the action buttons. */
[class*="st-key-hmwl_"]{ border-left:1px solid var(--line2); padding-left:17px;
  height:100%; }
/* the action row is its own band, not a fourth thing stacked under the tiles */
[class*="st-key-hmact_"]{ margin-top:12px; }
[class*="st-key-hmq_"]{ background:var(--panel); border:1px solid var(--line);
  border-radius:11px; padding:12px 13px; height:100%; display:flex; flex-direction:column; }
.hm-qline{ display:flex; align-items:center; gap:8px; }
.hm-qname{ font-size:14px; font-weight:800; letter-spacing:-.01em; }
.hm-qnote{ font-size:12px; color:var(--mut2); line-height:1.45; margin-bottom:11px;
  min-height:52px; }
[class*="st-key-hmq_"] [data-testid="stHorizontalBlock"]{ margin-top:auto; }
[class*="st-key-hmhero_"] [data-testid="stLinkButton"] a,
[class*="st-key-hmq_"] [data-testid="stLinkButton"] a{ border-radius:8px; font-size:12px;
  font-weight:700; width:100%; }
  text-decoration:underline !important; }

/* ---- phase bar: pre-season vs in-season, above the section nav ---- */
.ph-note{ font-size:12px; color:var(--mut2); padding-top:9px; }
[class*="phasebar"] [role="radiogroup"]{ gap:4px; }
[class*="phasebar"] [role="radiogroup"] label{ padding:6px 14px; font-size:12px;
  font-weight:700; border-radius:7px; }

/* ---- Pre-season prep desk ---- */
[class*="st-key-pk1_"],[class*="st-key-pk2_"],[class*="st-key-pk3_"]{
  background:var(--panel2); border-radius:10px; padding:11px 13px; }
[class*="st-key-pc1_"],[class*="st-key-pc2_"],[class*="st-key-pc3_"],
[class*="st-key-pc4_"]{ background:var(--panel); border:1px solid var(--line);
  border-radius:12px; padding:13px 14px 12px; height:100%;
  display:flex; flex-direction:column; }
/* the card's action sits at the bottom so cards of different text length line up */
[class*="st-key-pc1_"] .stButton,[class*="st-key-pc2_"] .stButton,
[class*="st-key-pc3_"] .stButton,[class*="st-key-pc4_"] .stButton,
[class*="st-key-pc2_"] [data-testid="stLinkButton"]{ margin-top:auto; }
[class*="st-key-pc2_"] [data-testid="stLinkButton"] a{ border-radius:8px;
  font-size:12.5px; font-weight:700; }
.pk-of{ font-size:14px; font-weight:700; color:var(--mut2); }
.pk-t{ font-size:14px; font-weight:800; letter-spacing:-.01em; }
.pk-m{ font-size:11.5px; color:var(--mut2); margin:1px 0 9px; }
.pk-n{ font-size:12.5px; line-height:1.45; padding:9px 10px; border-radius:8px;
  margin-bottom:11px; min-height:58px; }
.pk-ok{ background:#e6f4ec; color:#14603f; } .pk-amb{ background:#fdf3e3; color:#7a4f06; }
.pk-red{ background:#fdecec; color:#8c2320; } .pk-nil{ background:var(--panel2); color:var(--muted); }

/* ---- topbar: one row, phase on the right, health folded into the pills ---- */
/* pills must never wrap the bar onto a second row — clip instead */
.tb-pills{ flex-wrap:nowrap; overflow:hidden; justify-content:flex-end; }
.tb-id{ flex-wrap:nowrap; gap:9px; align-items:center; min-width:0; }
.tb-id .bs-word{ font-size:15px; flex:none; }
.tb-sep{ width:1px; height:18px; background:var(--line); flex:none; }
/* health as ONE cluster of dots, not four pills — see app.py for why */
.tb-hc{ display:inline-flex; align-items:center; gap:5px; flex:none;
  padding:4px 9px; border-radius:7px; background:var(--panel2); }
.tb-hc i{ width:6px; height:6px; border-radius:50%; display:inline-block; }
.tb-hc > span{ font-size:9.5px; font-weight:700; letter-spacing:.06em;
  text-transform:uppercase; color:var(--mut2); margin-left:2px; }
/* degraded states are LOUDER than healthy, not quieter */
.tb-hc.hc-warn{ background:var(--accent-soft); }
.tb-hc.hc-warn > span{ color:var(--amber); }
.tb-hc.hc-bad{ background:var(--accent-soft); }
.tb-hc.hc-bad > span{ color:var(--red); }
.tb-name{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tb-bf{ font-size:10px; color:var(--mut2); font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  margin-top:9px; }
.tb-hh{ font-size:9.5px; font-weight:800; letter-spacing:.11em; text-transform:uppercase;
  color:var(--mut2); margin:10px 0 5px; }
.tb-hr{ display:flex; align-items:center; gap:7px; font-size:12px; padding:3px 0; }
.tb-hr b{ margin-left:auto; font-variant-numeric:tabular-nums; }
.tb-dot{ width:6px; height:6px; border-radius:50%; display:inline-block; margin-right:5px; }
/* The phase / nav controls are st.segmented_control now, not styled radios —
   see app.py for why. Streamlit ships it already looking like a segment, so this
   is only sizing and brand colour, no DOM archaeology. */
[class*="st-key-tb_phase"] [data-testid="stButtonGroup"],
[class*="st-key-hmphase"] [data-testid="stButtonGroup"],
[class*="navbar"] [data-testid="stButtonGroup"]{ gap:2px; }
[class*="st-key-tb_phase"] [data-testid="stButtonGroup"] button,
[class*="st-key-hmphase"] [data-testid="stButtonGroup"] button{
  font-size:11.5px; font-weight:700; padding:5px 15px; border-radius:7px; }
[class*="navbar"] [data-testid="stButtonGroup"] button{
  font-size:13.5px; font-weight:700; padding:8px 15px; }
[class*="st-key-tb_more"] button{ padding:4px 0; font-weight:800; }

/* ---- tone scale: one place, both themes. Anything that was inline hex could not
   follow the theme, which is how the Home notes and badges stayed pale-on-dark
   the moment dark became the default. ---- */
:root{ --tone-red:#b00335; --tone-amber:#a8570d; --tone-ok:#1d7a55; --tone-nil:#8a8085; }
.tone-red{ background:#fdeaf0; color:#8e0230; } .tone-red > i{ background:var(--tone-red); }
.tone-amber{ background:#fbf1e2; color:#7a4f06; } .tone-amber > i{ background:var(--tone-amber); }
.tone-ok{ background:#e7f3ed; color:#155f43; } .tone-ok > i{ background:var(--tone-ok); }
.tone-nil{ background:var(--panel2); color:var(--muted); } .tone-nil > i{ background:var(--tone-nil); }
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


def cherry_svg(size: int = 22) -> str:
    """The Bloody Sunday mark. Inline SVG rather than a file so it inherits the
    theme and never 404s on Cloud; swap in the real asset when you want the exact
    artwork."""
    h = int(size * 38 / 34)
    return (f'<svg class="bs-mark" width="{size}" height="{h}" viewBox="0 0 34 38" '
            f'aria-hidden="true"><rect width="34" height="38" rx="6" fill="var(--crimson)"/>'
            f'<circle cx="15" cy="26" r="7" fill="#fff"/>'
            f'<path d="M16 19 C17 13,20 11,21 10" stroke="#fff" stroke-width="2.2" '
            f'fill="none" stroke-linecap="round"/></svg>')


def logo_html(size: int = 30, tag: str | None = None) -> str:
    """Wordmark for the topbar. The BADGE is not used here on purpose — at 16-22px
    the cherry reads as a red smudge, so the mark earns its keep as the favicon
    where it sits alone, and the set wordmark carries the bar."""
    t = f'<div class="neon-tag">{tag}</div>' if tag else ""
    return (f'<span class="bs-logo" style="font-size:{size}px;">'
            f'{cherry_svg(max(16, int(size * 0.72)))}'
            f'<span class="bs-word">Bloody<em>Sunday</em></span></span>{t}')


DARK = """
<style>
/* ===== War room — the dark side of the SAME identity, not an inversion.
   The badge set already contains this near-black, so dark is first-class. ===== */
:root{
  --bg:#161415; --panel:#232022; --panel2:#2c282a; --line:#332e30; --line2:#2c282a;
  --ink:#f2eef0; --muted:#a2989c; --mut2:#95898e;
  /* TWO crimsons on dark, because one colour cannot do both jobs: --accent must
     read bright ON the dark panel, while a button FILL must be deep enough to
     carry white text. Chasing one value made one of the two fail AA every time. */
  --crimson:#ff336c; --crimson-d:#e02557;
  --blue:#ff336c; --green:#7fd8b4; --amber:#f0b357; --red:#ff8fae; --violet:#c98fbb;
  --accent:#ff336c; --accent-fill:#e02557; --accent-soft:#3a1020; --accent-line:#5a1b30;
  --qb:#c98fbb; --rb:#7fd8b4; --wr:#6aa6f0; --te:#f0b357; --dst:#8fb8f5;
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
/* The star recommendation was the one banner in this family that never got a
   dark counterpart, so it stayed a white card with dark-green text — the
   brightest thing on the panel, sitting directly under the war-room board. */
.dr-rec{ background:linear-gradient(180deg,#14332a,#112c25) !important;
  border-color:#1f5a46 !important; box-shadow:none !important; color:var(--ink) !important; }
.dr-rec b{ color:var(--green) !important; }
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

/* tone scale, dark half — same classes, darker grounds, lighter ink */
:root{ --tone-red:#ff5c85; --tone-amber:#f0b357; --tone-ok:#7fd8b4; --tone-nil:#847a7e; }
.tone-red{ background:#3a1020 !important; color:#ff8fae !important; }
.tone-amber{ background:#33280f !important; color:#f5c87d !important; }
.tone-ok{ background:#12312a !important; color:#7fd8b4 !important; }
.tone-nil{ background:#2c282a !important; color:#a2989c !important; }
/* prep-desk note tints predate the tone scale and are hardcoded light */
.pk-ok{ background:#12312a !important; color:#7fd8b4 !important; }
.pk-amb{ background:#33280f !important; color:#f5c87d !important; }
.pk-red{ background:#3a1020 !important; color:#ff8fae !important; }
.pk-nil{ background:#2c282a !important; color:#a2989c !important; }
.hm-note i{ }
</style>
"""


def inject(st, dark: bool = False) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if dark:
        st.markdown(DARK, unsafe_allow_html=True)


def fingerprint() -> str:
    """First 6 chars of a sha1 over the injected stylesheet.

    Streamlit Cloud re-runs app.py on a new commit but KEEPS already-imported
    modules, so an edited theme.py can go on serving its old CSS indefinitely and
    the page looks unchanged no matter how many times you push. The fix is Reboot
    app, not another commit — but the failure is invisible, which is the actual
    problem. Surfacing this makes it diagnosable: if the page looks wrong and this
    hasn't moved, it's a stale process rather than a bad stylesheet.

    Ported from seven-half-men, where this exact failure cost real time twice."""
    import hashlib
    return hashlib.sha1((CSS + DARK).encode()).hexdigest()[:6]
