"""Headless 10-mock harness — mirrors mock_ui's AI draft loop (snake order,
POS_CAPS, QB/TE fill nudge, soft flex balance, rookie lean, jitter) without the
Streamlit UI, so we can audit roster construction + where rookies actually land.

Run: python3 scripts/mock_sim.py [n_mocks]
"""
import sys
from collections import Counter, defaultdict

from draftkit import players, config, rankings as R, draft_history as DH
from draftkit.adp import consensus
from draftkit.ui import components as C

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
LID = sys.argv[2] if len(sys.argv) > 2 else "1310907162930733056"  # Kreeper
# team count matters for snake order + round math (Kreeper=8, Babies&Boomer=10)
TEAMS = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("teams=")), 8)
BOOST = "--noboost" not in sys.argv
STARTERS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "FLEX"]
ROUNDS = 14                      # 9 starters + 5 bench
JITTER = 0.15
WATCH = ["Jeremiyah Love", "Jadarian Price"]

season = config.current_season()
reg = players.build_registry(season)
adp_pool = R.adp_pool(reg, consensus.load(season))
if BOOST:
    rc = DH.rookie_curve(LID, reg, season)
    adp_pool = R.apply_rookie_curve(adp_pool, reg, rc.get("curve", {}))
    print(f"[rookie boost ON] curve: "
          + ", ".join(f"R{k}:{v:.0f}" for k, v in sorted(rc.get('curve', {}).items())[:6]))
else:
    print("[rookie boost OFF]")
snake = C.snake(TEAMS)

def is_rookie(pid):
    try:
        return reg.meta(pid).years_exp == 0
    except Exception:
        return False

def run_one():
    taken, rosters = set(), {s: [] for s in range(TEAMS)}
    counts = {s: {} for s in range(TEAMS)}
    drafted_at = {}                       # name -> overall pick
    rookie_picks = []                     # (overall, name, pos)
    for overall in range(1, TEAMS * ROUNDS + 1):
        slot = snake(overall - 1)
        rnd = (overall - 1) // TEAMS + 1
        pool = [p for p in adp_pool if p["pid"] not in taken]
        ch = DH.pick_for_owner(str(slot), rnd, pool, {}, reg,
                               jitter=JITTER, roster_counts=counts[slot])
        if not ch:
            break
        taken.add(ch["pid"])
        pos = reg.meta(ch["pid"]).position
        rosters[slot].append((ch["name"], pos))
        counts[slot][pos] = counts[slot].get(pos, 0) + 1
        drafted_at[ch["name"]] = overall
        if is_rookie(ch["pid"]):
            rookie_picks.append((overall, ch["name"], pos))
    return rosters, counts, drafted_at, rookie_picks

flags = Counter()
watch_picks = {w: [] for w in WATCH}
qb_dist, rb_dist, wr_dist, te_dist = Counter(), Counter(), Counter(), Counter()
rookie_round_hist = Counter()
all_rookie_first = []
board_pos = defaultdict(list)                # overall pick -> [name,...] across mocks
adp_lk = {p["pid"]: p["adp"] for p in adp_pool}   # boosted adp
ELITE = [p["name"] for p in adp_pool[:8]]    # top-8 vets/players by board
elite_picks = defaultdict(list)

for i in range(N):
    rosters, counts, drafted_at, rookie_picks = run_one()
    for s in range(TEAMS):
        c = counts[s]
        q, r, w, t = c.get("QB", 0), c.get("RB", 0), c.get("WR", 0), c.get("TE", 0)
        qb_dist[q] += 1; rb_dist[r] += 1; wr_dist[w] += 1; te_dist[t] += 1
        if q == 0: flags["0 QB"] += 1
        if q >= 3: flags["3+ QB"] += 1
        if t == 0: flags["0 TE"] += 1
        if t >= 3: flags["3+ TE"] += 1
        if r < 3: flags["<3 RB"] += 1
        if w < 3: flags["<3 WR"] += 1
        if r + w < 8: flags["thin RB+WR (<8)"] += 1
    for nm, ov in drafted_at.items():
        if ov <= 15:
            board_pos[ov].append(nm)
        if nm in ELITE:
            elite_picks[nm].append(ov)
    for w in WATCH:
        if w in drafted_at:
            watch_picks[w].append(drafted_at[w])
    if rookie_picks:
        all_rookie_first.append(min(p[0] for p in rookie_picks))
    for ov, nm, pos in rookie_picks:
        rookie_round_hist[(ov - 1) // TEAMS + 1] += 1

def fmt(d):
    return ", ".join(f"{k}:{v}" for k, v in sorted(d.items()))

print(f"\n=== {N} mocks · {TEAMS} teams · {ROUNDS} rds · jitter={JITTER} · no keepers/tendencies ===")
print(f"\nRoster-construction flags (out of {N*TEAMS} teams):")
print("  ", fmt(flags) or "none 🎉")
print(f"\nPosition-count distributions (count: #teams):")
print("   QB:", fmt(qb_dist)); print("   RB:", fmt(rb_dist))
print("   WR:", fmt(wr_dist)); print("   TE:", fmt(te_dist))
print(f"\nMost common pick at each of the first 15 slots (name : times / {N}):")
for ov in range(1, 16):
    names = Counter(board_pos.get(ov, []))
    if names:
        top = names.most_common(1)[0]
        m = reg.by_norm  # noqa
        pid = next((p["pid"] for p in adp_pool if p["name"] == top[0]), None)
        adp = adp_lk.get(pid, "?")
        rk = " (R)" if pid and reg.meta(pid).years_exp == 0 else ""
        print(f"   #{ov:>2}: {top[0]}{rk}  ({top[1]}/{N}, boosted ADP {adp})")
print(f"\nRookie aggression:")
print("   first rookie off the board, per mock:", all_rookie_first or "(n/a)")
print("   rookies drafted by round:", fmt(rookie_round_hist))
print(f"\nWatched rookies (overall pick across {N} mocks):")
for w in WATCH:
    ps = watch_picks[w]
    if ps:
        print(f"   {w}: avg {sum(ps)/len(ps):.1f} | range {min(ps)}-{max(ps)} | {sorted(ps)}")
    else:
        print(f"   {w}: never drafted")
print(f"\nElite-vet landing (did the rookie boost push real studs too far?):")
for nm in ELITE:
    ps = elite_picks.get(nm, [])
    pid = next((p["pid"] for p in adp_pool if p["name"] == nm), None)
    base = adp_lk.get(pid, "?")
    if ps:
        print(f"   {nm} (ADP {base}): avg pick {sum(ps)/len(ps):.1f} | range {min(ps)}-{max(ps)}")
    else:
        print(f"   {nm} (ADP {base}): NEVER DRAFTED ⚠️")
