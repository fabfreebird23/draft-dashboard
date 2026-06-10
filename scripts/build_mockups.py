"""Generate two static, self-contained HTML mockups (real player data, no backend)
so we can compare design directions: a FantasyPros Draft Assistant replica and a
Draft Sharks War Room replica. Output -> /tmp/mockups/."""
import json
import os
import html

DATA = json.load(open("/tmp/mockdata.json"))
OUT = "/tmp/mockups"
os.makedirs(OUT, exist_ok=True)

HS = "https://a.espncdn.com/i/headshots/nfl/players/full/{eid}.png"
DEF = "https://a.espncdn.com/combiner/i?img=/i/headshots/nophoto.png&w=80&h=80"
POS_ORDER = {"QB": 0, "RB": 1, "WR": 2, "TE": 3}


def proj(adp):
    return max(48, round(335 - adp * 1.35))


def hs(p):
    return HS.format(eid=p["eid"]) if p.get("eid") else DEF


# Simulated draft state: picks 1-15 gone (by ADP), you're on the clock at 2.08.
DRAFTED = {d["name"] for d in DATA[:15]}
MY_TEAM = [DATA[0]]          # you kept/took Gibbs at 1.01 (illustrative)
AVAIL = [p for p in DATA if p["name"] not in DRAFTED]

# ----------------------------------------------------------------------------- FP
FP_POS = {"QB": "#d23b3b", "RB": "#2e9e5b", "WR": "#2f72c4", "TE": "#e08a1e",
          "K": "#7a7f87", "DST": "#6f5bd0"}


def fp_rows(players):
    rows, last = [], None
    for p in players[:46]:
        if p["tier"] != last:
            rows.append(f'<tr class="tband"><td colspan="7">Tier {p["tier"]}</td></tr>')
            last = p["tier"]
        c = FP_POS.get(p["pos"], "#888")
        rec = ' class="rec"' if p is players[0] else ""
        rows.append(
            f'<tr{rec}>'
            f'<td class="rk">{p["ovr"]}</td>'
            f'<td class="pl"><img src="{hs(p)}" onerror="this.src=\'{DEF}\'">'
            f'<span class="nm">{html.escape(p["name"])}</span>'
            f'<span class="pb" style="background:{c}">{p["pos"]}</span>'
            f'<span class="tm">{p["team"]}</span></td>'
            f'<td>{p["pr"]}</td>'
            f'<td class="mut">{p["bye"]}</td>'
            f'<td class="adp">{p["adp"]}</td>'
            f'<td class="proj">{proj(p["adp"])}</td>'
            f'<td><button class="dft">Draft</button></td></tr>')
    return "".join(rows)


def fp_bestpos():
    out = []
    for pos in ("QB", "RB", "WR", "TE"):
        lst = [p for p in AVAIL if p["pos"] == pos][:5]
        c = FP_POS[pos]
        items = "".join(
            f'<div class="bp-row"><span class="bp-pos" style="color:{c}">{p["pr"]}</span>'
            f'<span class="bp-nm">{html.escape(p["name"])}</span>'
            f'<span class="bp-adp">{p["adp"]}</span></div>' for p in lst)
        out.append(f'<div class="bp-col"><div class="bp-h" style="border-color:{c}">{pos}</div>{items}</div>')
    return "".join(out)


SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN", "BN", "BN", "BN"]


def fp_roster():
    filled = {0: MY_TEAM[0]} if MY_TEAM else {}
    out = []
    # place Gibbs in RB
    rb_done = False
    for i, s in enumerate(SLOTS):
        p = None
        if s == "RB" and not rb_done and MY_TEAM:
            p, rb_done = MY_TEAM[0], True
        nm = html.escape(p["name"]) if p else "Empty"
        cls = "r-slot" + ("" if p else " empty")
        out.append(f'<div class="{cls}"><span class="r-pos">{s}</span><span class="r-nm">{nm}</span></div>')
    return "".join(out)


FP = f"""<!doctype html><html><head><meta charset="utf-8"><title>FantasyPros replica</title>
<style>
*{{box-sizing:border-box;margin:0;font-family:-apple-system,'Segoe UI',Arial,sans-serif;}}
body{{background:#eef1f5;color:#1d2733;font-size:13px;}}
.top{{background:#fff;border-bottom:1px solid #dfe4ea;display:flex;align-items:center;gap:18px;
  padding:0 20px;height:54px;position:sticky;top:0;z-index:5;}}
.logo{{font-weight:800;font-size:18px;color:#1f4e9b;letter-spacing:-.3px;}}
.logo span{{color:#e74c3c;}}
.status{{margin-left:auto;display:flex;align-items:center;gap:14px;}}
.pill{{background:#f0f3f8;border:1px solid #dfe4ea;border-radius:20px;padding:6px 14px;font-weight:600;}}
.pill b{{color:#1f4e9b;}}
.clock{{background:#e9f8ef;color:#1c8a4d;border:1px solid #b7e6c9;border-radius:20px;padding:6px 14px;font-weight:700;}}
.wrap{{display:grid;grid-template-columns:230px 1fr 280px;gap:14px;padding:14px 20px;align-items:start;}}
.card{{background:#fff;border:1px solid #e3e8ef;border-radius:10px;overflow:hidden;}}
.card h3{{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:#7b8694;padding:11px 14px;
  border-bottom:1px solid #eef1f5;background:#fafbfc;}}
.r-slot{{display:flex;align-items:center;gap:8px;padding:8px 14px;border-bottom:1px solid #f2f4f7;}}
.r-pos{{font-weight:800;font-size:10px;color:#fff;background:#5b6b7f;border-radius:4px;padding:2px 7px;min-width:38px;text-align:center;}}
.r-slot.empty .r-nm{{color:#aab3bf;font-style:italic;}}
.needs{{padding:10px 14px;display:flex;flex-wrap:wrap;gap:6px;}}
.need{{font-size:11px;font-weight:700;border:1.5px solid #f0a;border-color:#e74c3c;color:#e74c3c;border-radius:14px;padding:3px 10px;}}
.need.ok{{border-color:#cfd6df;color:#aab3bf;}}
.pills{{display:flex;gap:6px;padding:11px 14px;border-bottom:1px solid #eef1f5;}}
.fpill{{font-weight:700;font-size:12px;padding:5px 13px;border-radius:18px;background:#f0f3f8;color:#5b6b7f;cursor:pointer;}}
.fpill.on{{background:#1f4e9b;color:#fff;}}
table{{width:100%;border-collapse:collapse;}}
th{{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:#9aa4b1;
  padding:8px 12px;border-bottom:1px solid #eef1f5;}}
th.r,td.rk,td.adp,td.proj{{text-align:center;}}
td{{padding:7px 12px;border-bottom:1px solid #f3f5f8;}}
tr:hover td{{background:#f7f9fc;}}
tr.rec td{{background:#fbfdff;box-shadow:inset 3px 0 0 #1f4e9b;}}
.tband td{{background:#eef3fb;color:#1f4e9b;font-weight:800;font-size:11px;text-transform:uppercase;letter-spacing:1px;padding:5px 12px;}}
td.rk{{color:#9aa4b1;font-weight:700;width:34px;}}
.pl{{display:flex;align-items:center;gap:8px;}}
.pl img{{width:30px;height:30px;border-radius:50%;object-fit:cover;background:#eef1f5;}}
.pl .nm{{font-weight:700;}}
.pb{{color:#fff;font-size:10px;font-weight:800;border-radius:3px;padding:1px 5px;}}
.pl .tm{{color:#9aa4b1;font-size:11px;}}
td.mut{{color:#9aa4b1;text-align:center;}}
td.adp{{font-weight:700;}}
td.proj{{color:#1c8a4d;font-weight:700;}}
.dft{{background:#1c8a4d;color:#fff;border:none;border-radius:6px;font-weight:700;font-size:11px;padding:5px 12px;cursor:pointer;}}
.dft:hover{{background:#15703d;}}
.bp-col{{border-bottom:1px solid #eef1f5;}}
.bp-h{{font-weight:800;font-size:11px;padding:6px 14px;border-left:3px solid;background:#fafbfc;}}
.bp-row{{display:flex;align-items:center;gap:8px;padding:5px 14px;font-size:12px;}}
.bp-pos{{font-weight:800;font-size:10px;width:30px;}}
.bp-nm{{flex:1;font-weight:600;}}
.bp-adp{{color:#9aa4b1;}}
.tabbar{{display:flex;border-bottom:1px solid #eef1f5;}}
.tb{{flex:1;text-align:center;font-weight:700;font-size:12px;padding:9px;color:#7b8694;cursor:pointer;}}
.tb.on{{color:#1f4e9b;box-shadow:inset 0 -2px 0 #1f4e9b;}}
</style></head><body>
<div class="top"><div class="logo">Fantasy<span>Pros</span> · Draft Assistant</div>
  <div class="status"><div class="pill">Round <b>2</b> · Pick <b>2.08</b></div>
  <div class="clock">⏱ YOU'RE ON THE CLOCK</div></div></div>
<div class="wrap">
  <div style="display:flex;flex-direction:column;gap:14px;">
    <div class="card"><h3>My Team</h3>{fp_roster()}</div>
    <div class="card"><h3>Team Needs</h3><div class="needs">
      <span class="need">QB</span><span class="need">WR</span><span class="need">TE</span>
      <span class="need ok">RB</span></div></div>
  </div>
  <div class="card">
    <div class="pills"><span class="fpill on">ALL</span><span class="fpill">QB</span>
      <span class="fpill">RB</span><span class="fpill">WR</span><span class="fpill">TE</span>
      <span class="fpill">K</span><span class="fpill">DST</span></div>
    <table><thead><tr><th class="r">Rank</th><th>Player</th><th>Pos</th><th class="r">Bye</th>
      <th class="r">ADP</th><th class="r">Proj</th><th></th></tr></thead>
      <tbody>{fp_rows(AVAIL)}</tbody></table>
  </div>
  <div style="display:flex;flex-direction:column;gap:14px;">
    <div class="card"><div class="tabbar"><div class="tb on">Best Available</div><div class="tb">Pick Analysis</div></div>
      {fp_bestpos()}</div>
    <div class="card"><h3>Suggested Pick</h3>
      <div style="padding:12px 14px;">
        <div style="font-weight:800;font-size:15px;">{html.escape(AVAIL[0]['name'])}
          <span style="color:#9aa4b1;font-weight:600;font-size:12px;">{AVAIL[0]['pos']} · {AVAIL[0]['team']}</span></div>
        <div style="color:#5b6b7f;margin-top:4px;">Best available, fills your RB need, ADP value.</div>
        <button class="dft" style="margin-top:10px;width:100%;padding:9px;">Draft {html.escape(AVAIL[0]['name'])}</button>
      </div></div>
  </div>
</div></body></html>"""

# ----------------------------------------------------------------------------- DS
DS_POS = {"QB": "#ff7a59", "RB": "#3ddc84", "WR": "#39c0ff", "TE": "#ffd166",
          "K": "#9aa4b1", "DST": "#b08bff"}


def ds_value(p, pick=16):
    d = p["adp"] - pick
    if d >= 8:
        return f'<span class="vb val">VALUE +{int(d)}</span>'
    if d <= -8:
        return f'<span class="vb rch">REACH {int(d)}</span>'
    return '<span class="vb nu">FAIR</span>'


def ds_rows(players):
    rows, last = [], None
    for p in players[:42]:
        if p["tier"] != last:
            rows.append(f'<div class="ds-tier">Tier {p["tier"]}</div>')
            last = p["tier"]
        c = DS_POS.get(p["pos"], "#888")
        rows.append(
            f'<div class="ds-row" style="--c:{c}">'
            f'<img src="{hs(p)}" onerror="this.src=\'{DEF}\'">'
            f'<div class="ds-main"><div class="ds-nm">{html.escape(p["name"])}'
            f'<span class="ds-prk" style="background:{c}">{p["pr"]}</span></div>'
            f'<div class="ds-sub">{p["pos"]} · {p["team"]} · Bye {p["bye"]}</div></div>'
            f'<div class="ds-adp"><b>{p["adp"]}</b><small>ADP</small></div>'
            f'{ds_value(p)}'
            f'<button class="ds-draft">DRAFT</button></div>')
    return "".join(rows)


def ds_reco():
    out = []
    reasons = ["Best player available · fills RB", "Falls past ADP · elite tier", "Positional run starting at WR"]
    for p, why in zip(AVAIL[:3], reasons):
        c = DS_POS.get(p["pos"], "#888")
        out.append(
            f'<div class="rc" style="--c:{c}"><div class="rc-top">'
            f'<span class="rc-nm">{html.escape(p["name"])}</span>'
            f'<span class="rc-pr" style="background:{c}">{p["pr"]}</span></div>'
            f'<div class="rc-why">{why}</div>'
            f'<button class="ds-draft sm">DRAFT</button></div>')
    return "".join(out)


def ds_strength():
    teams = [("FAABfreebird (You)", 96, True), ("Old Man Mike", 89, False),
             ("Business is Good", 80, False), ("Vice Vice Baby", 74, False),
             ("Wee Little Ladds", 68, False)]
    out = []
    for i, (nm, pct, me) in enumerate(teams, 1):
        out.append(f'<div class="st-row {"me" if me else ""}"><span class="st-rk">{i}</span>'
                   f'<span class="st-nm">{nm}</span><span class="st-bar"><i style="width:{pct}%"></i></span></div>')
    return "".join(out)


DS = f"""<!doctype html><html><head><meta charset="utf-8"><title>Draft Sharks replica</title>
<style>
*{{box-sizing:border-box;margin:0;font-family:-apple-system,'Segoe UI',Arial,sans-serif;}}
body{{background:#0c1626;color:#e8eef7;font-size:13px;}}
.top{{background:linear-gradient(90deg,#0a1322,#15243c);border-bottom:1px solid #22344f;
  display:flex;align-items:center;gap:16px;padding:0 22px;height:58px;position:sticky;top:0;z-index:5;}}
.logo{{font-weight:900;font-size:18px;letter-spacing:.5px;}}
.logo b{{color:#3ddc84;}}
.live{{display:flex;align-items:center;gap:7px;color:#3ddc84;font-weight:800;font-size:12px;}}
.live i{{width:8px;height:8px;border-radius:50%;background:#3ddc84;box-shadow:0 0 8px #3ddc84;display:inline-block;}}
.status{{margin-left:auto;display:flex;gap:12px;align-items:center;}}
.pchip{{background:#16263f;border:1px solid #26405f;border-radius:8px;padding:7px 14px;font-weight:700;}}
.pchip b{{color:#39c0ff;}}
.clock{{background:#3ddc84;color:#06281a;border-radius:8px;padding:7px 16px;font-weight:900;}}
.wrap{{display:grid;grid-template-columns:250px 1fr 290px;gap:14px;padding:14px 22px;align-items:start;}}
.panel{{background:#11203a;border:1px solid #22344f;border-radius:12px;overflow:hidden;}}
.panel h3{{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#7e93b3;padding:11px 14px;border-bottom:1px solid #1c2e49;}}
.run{{background:linear-gradient(90deg,rgba(255,122,89,.2),transparent);border:1px solid #ff7a59;
  border-radius:10px;padding:9px 13px;font-weight:800;color:#ff9d80;margin-bottom:12px;}}
.r-slot{{display:flex;align-items:center;gap:9px;padding:8px 14px;border-bottom:1px solid #1a2c47;}}
.r-pos{{font-weight:900;font-size:10px;color:#06281a;background:#3ddc84;border-radius:4px;padding:2px 7px;min-width:40px;text-align:center;}}
.r-slot.empty .r-pos{{background:#2a3e5c;color:#7e93b3;}}
.r-slot.empty .r-nm{{color:#5d7398;font-style:italic;}}
.needs{{padding:10px 14px;display:flex;flex-wrap:wrap;gap:6px;}}
.need{{font-size:11px;font-weight:800;border:1.5px solid #39c0ff;color:#39c0ff;border-radius:14px;padding:3px 10px;}}
.st-row{{display:flex;align-items:center;gap:8px;padding:5px 14px;font-size:12px;}}
.st-row.me{{background:rgba(61,220,132,.1);font-weight:800;}}
.st-rk{{width:14px;color:#7e93b3;font-weight:800;}}
.st-nm{{width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.st-bar{{flex:1;height:8px;background:#1a2c47;border-radius:5px;overflow:hidden;}}
.st-bar i{{display:block;height:100%;background:linear-gradient(90deg,#3ddc84,#39c0ff);}}
.st-row.me .st-bar i{{background:linear-gradient(90deg,#ff7a59,#ffd166);}}
.board-h{{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-bottom:1px solid #1c2e49;}}
.board-h b{{font-size:14px;}}
.bpills{{display:flex;gap:6px;}}
.bpill{{font-size:11px;font-weight:800;padding:4px 11px;border-radius:14px;background:#16263f;color:#7e93b3;cursor:pointer;}}
.bpill.on{{background:#39c0ff;color:#06283a;}}
.ds-tier{{font-weight:900;font-size:10px;letter-spacing:1.5px;color:#7e93b3;padding:8px 14px 3px;}}
.ds-row{{display:flex;align-items:center;gap:11px;padding:8px 14px;border-bottom:1px solid #16263f;
  border-left:4px solid var(--c);}}
.ds-row:hover{{background:#16263f;}}
.ds-row img{{width:34px;height:34px;border-radius:50%;object-fit:cover;background:#1a2c47;}}
.ds-main{{flex:1;}}
.ds-nm{{font-weight:800;font-size:14px;display:flex;align-items:center;gap:8px;}}
.ds-prk{{font-size:10px;font-weight:900;color:#06281a;border-radius:4px;padding:1px 6px;}}
.ds-sub{{color:#7e93b3;font-size:11px;margin-top:1px;}}
.ds-adp{{text-align:center;color:#cfe;}}
.ds-adp b{{font-size:15px;}}.ds-adp small{{display:block;font-size:8px;color:#7e93b3;letter-spacing:1px;}}
.vb{{font-size:10px;font-weight:900;border-radius:5px;padding:3px 8px;min-width:74px;text-align:center;}}
.vb.val{{background:rgba(61,220,132,.16);color:#3ddc84;}}
.vb.rch{{background:rgba(255,90,90,.16);color:#ff7676;}}
.vb.nu{{background:#16263f;color:#7e93b3;}}
.ds-draft{{background:#3ddc84;color:#06281a;border:none;border-radius:7px;font-weight:900;font-size:11px;padding:7px 14px;cursor:pointer;}}
.ds-draft:hover{{background:#2bc673;}}
.ds-draft.sm{{padding:5px 12px;margin-top:8px;width:100%;}}
.rc{{border:1px solid #22344f;border-left:4px solid var(--c);border-radius:10px;padding:10px 12px;margin:10px 14px;}}
.rc-top{{display:flex;align-items:center;justify-content:space-between;}}
.rc-nm{{font-weight:800;font-size:14px;}}
.rc-pr{{font-size:10px;font-weight:900;color:#06281a;border-radius:4px;padding:1px 6px;}}
.rc-why{{color:#9fb2cf;font-size:11px;margin-top:3px;}}
</style></head><body>
<div class="top"><div class="logo">DRAFT <b>SHARKS</b> · War Room</div>
  <div class="live"><i></i>LIVE</div>
  <div class="status"><div class="pchip">Round <b>2</b> · Pick <b>2.08</b></div>
  <div class="clock">⏱ YOUR PICK · 1:28</div></div></div>
<div class="wrap">
  <div style="display:flex;flex-direction:column;gap:14px;">
    <div class="panel"><h3>Your Roster</h3>
      <div class="r-slot"><span class="r-pos">RB</span><span class="r-nm">{html.escape(MY_TEAM[0]['name'])}</span></div>
      <div class="r-slot empty"><span class="r-pos">QB</span><span class="r-nm">Empty</span></div>
      <div class="r-slot empty"><span class="r-pos">RB</span><span class="r-nm">Empty</span></div>
      <div class="r-slot empty"><span class="r-pos">WR</span><span class="r-nm">Empty</span></div>
      <div class="r-slot empty"><span class="r-pos">WR</span><span class="r-nm">Empty</span></div>
      <div class="r-slot empty"><span class="r-pos">TE</span><span class="r-nm">Empty</span></div>
      <div class="r-slot empty"><span class="r-pos">FLEX</span><span class="r-nm">Empty</span></div></div>
    <div class="panel"><h3>Roster Needs</h3><div class="needs">
      <span class="need">QB</span><span class="need">WR×2</span><span class="need">TE</span></div></div>
    <div class="panel"><h3>Roster Strength vs League</h3>{ds_strength()}</div>
  </div>
  <div class="panel">
    <div class="board-h"><b>🦈 Big Board</b><div class="bpills"><span class="bpill on">ALL</span>
      <span class="bpill">QB</span><span class="bpill">RB</span><span class="bpill">WR</span><span class="bpill">TE</span></div></div>
    {ds_rows(AVAIL)}
  </div>
  <div style="display:flex;flex-direction:column;gap:14px;">
    <div class="panel" style="padding:12px 14px 4px;"><div class="run">🔥 RB RUN — 4 of last 6 picks</div>
      <h3 style="border:none;padding:0 0 4px;">⚡ Recommended Picks</h3></div>
    <div class="panel" style="margin-top:-14px;border-top:none;border-radius:0 0 12px 12px;">{ds_reco()}</div>
  </div>
</div></body></html>"""

INDEX = """<!doctype html><html><head><meta charset="utf-8"><title>Draft UI mockups</title>
<style>body{font-family:-apple-system,Arial,sans-serif;background:#f4f0fb;padding:40px;}
a{display:block;font-size:20px;margin:14px 0;color:#7b5cff;font-weight:700;}</style></head>
<body><h1>Draft Room — UI direction mockups</h1>
<a href="fantasypros.html">→ FantasyPros Draft Assistant replica (light, tabular)</a>
<a href="draftsharks.html">→ Draft Sharks War Room replica (dark, value-dense)</a></body></html>"""

open(f"{OUT}/fantasypros.html", "w").write(FP)
open(f"{OUT}/draftsharks.html", "w").write(DS)
open(f"{OUT}/index.html", "w").write(INDEX)
print("wrote mockups to", OUT)
