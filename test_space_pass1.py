"""
Deterministic space-milestone PASS 1 test (coordinate system + teleport-per-tick
move) - NO GPU/DB/network. Mirrors test_energy_ledger.py: pure functions, printed
hand-checkable numbers, PASS/FAIL per case.

Verifies (design doc sections 1-2):
  * Euclidean distance between known points.
  * move debits energy == round(distance * MOVE_COST_PER_UNIT).
  * position UPDATES to the destination on a successful (affordable) move.
  * an unaffordable move is DENIED: no position change, no energy spent beyond the
    inference; free actions still work at that low energy.
  * the 0-floor and MAX_ENERGY cap still hold under movement (full tick).
  * spawn positions (-> spawn_location) are populated non-null and spread on the plane.
  * the v1 economy numbers are UNCHANGED when no move is taken.
"""
import math
import random

from constants import (
    MAX_ENERGY, BASAL_INCOME, MOVE_COST_PER_UNIT, PLANE_WIDTH, PLANE_HEIGHT,
    COST_HARVEST, YIELD_EAT_RAW, YIELD_DRINK, YIELD_REST,
)
from mechanics import energy as E
from mechanics.geometry import distance
from mechanics.movement import move_cost, resolve_move
from world.placement import place_points

_checks = []
def check(name, ok, detail=""):
    _checks.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

print("=" * 72)
print("SPACE MILESTONE PASS 1 - coordinate system + teleport-per-tick move")
print(f"plane={PLANE_WIDTH:.0f} x {PLANE_HEIGHT:.0f} (floats)   "
      f"MOVE_COST_PER_UNIT={MOVE_COST_PER_UNIT}   MAX_ENERGY={MAX_ENERGY}  BASAL={BASAL_INCOME}")
print("=" * 72)

# ---------------------------------------------------------------- 1. geometry
print("\n[1] Euclidean distance (hand-checkable)")
DCASES = [
    ((0, 0),   (3, 4),   5.0),      # classic 3-4-5
    ((1, 1),   (4, 5),   5.0),      # dx=3 dy=4
    ((100, 200), (400, 600), 500.0),  # dx=300 dy=400 -> 500
    ((0, 0),   (0, 0),   0.0),      # zero distance
    ((0, 0),   (1000, 1000), math.hypot(1000, 1000)),  # plane diagonal ~1414.21
]
for (a, b, expect) in DCASES:
    d = distance(a[0], a[1], b[0], b[1])
    print(f"    {a} -> {b}: distance = {d:.4f}   (expected {expect:.4f})")
    check(f"distance {a}->{b} == {expect:.4f}", abs(d - expect) < 1e-9)

# ------------------------------------------------------------- 2. move cost
print("\n[2] move cost = round(distance * MOVE_COST_PER_UNIT), rate =", MOVE_COST_PER_UNIT)
CCASES = [(5, 15), (500, 1500), (400, 1200), (0, 0), (100, 300), (1000, 3000)]
for dist, expect in CCASES:
    c = move_cost(dist)
    print(f"    dist {dist:>5} * {MOVE_COST_PER_UNIT} = {c:>5}   (expected {expect})")
    check(f"move_cost({dist}) == {expect}", c == expect)
check("a 400-unit trip costs exactly one COST_HARVEST (economy anchor)",
      move_cost(400) == COST_HARVEST, f"move_cost(400)={move_cost(400)} == COST_HARVEST={COST_HARVEST}")

# ------------------------------------- 3. move debit + position update (success)
print("\n[3] successful move: debit == dist*rate AND position jumps to destination")
r = resolve_move(0, 0, 300, 400, 10000)   # dist 500, cost 1500
print(f"    from (0,0) to (300,400): dist={r['distance']:.1f} cost={r['cost']} "
      f"energy 10000 -> {r['energy']}  new_pos=({r['new_x']},{r['new_y']}) applied={r['applied']}")
check("move debits energy exactly dist*rate", r["applied"] and r["cost"] == 1500 and r["energy"] == 10000 - 1500,
      f"10000 - 1500 = {r['energy']}")
check("position UPDATES to the destination (teleport-per-tick)",
      (r["new_x"], r["new_y"]) == (300, 400))
r0 = resolve_move(10, 10, 10, 10, 5000)   # zero-distance move
check("zero-distance move costs 0, position unchanged, energy unchanged",
      r0["applied"] and r0["cost"] == 0 and r0["energy"] == 5000 and (r0["new_x"], r0["new_y"]) == (10, 10))

# ------------------------------------------- 4. unaffordable move is DENIED
print("\n[4] unaffordable move DENIED: no position change, no energy spent beyond inference")
rd = resolve_move(0, 0, 300, 400, 1000)   # cost 1500 > energy 1000
print(f"    from (0,0) to (300,400): dist={rd['distance']:.1f} cost={rd['cost']} "
      f"energy 1000 -> {rd['energy']}  new_pos=({rd['new_x']},{rd['new_y']}) applied={rd['applied']}")
check("move DENIED when energy < cost", rd["applied"] is False)
check("denied move spends NO energy (only the earlier inference was billed)", rd["energy"] == 1000)
check("denied move does NOT change position", (rd["new_x"], rd["new_y"]) == (0, 0))
# free action still works at that same low energy (rest is free)
freed = E.resolve_tick(1000, "rest", 200, target=None)
print(f"    free action at energy 1000: rest -> {freed['energy']} ({freed['outcome']})")
check("free action (rest) still applies at the low energy a move was denied at",
      freed["applied"] is True and freed["outcome"] == "free_applied")

# --------------------------------- 5. 0-floor and MAX_ENERGY cap under movement
print("\n[5] full-tick ledger invariants hold under movement")
# expensive move while nearly broke: basal+inference floor at 0, move denied
t_floor = E.resolve_tick(500, "move", 1660, move_distance=500)   # cost 1500
print(f"    energy 500, think 1660, move dist 500: before_action={t_floor['before_action']} "
      f"-> {t_floor['energy']} ({t_floor['outcome']})")
check("0-floor holds under movement (energy never negative)", t_floor["energy"] >= 0)
check("expensive move denied when post-inference balance can't cover it",
      t_floor["outcome"] == "move_denied" and t_floor["energy"] == 0)
# affordable full-tick move: basal(+500) - inference(1350) - move(1500)
t_ok = E.resolve_tick(10000, "move", 1350, move_distance=500)
expect_ok = 10000 + BASAL_INCOME - 1350 - 1500
print(f"    energy 10000, think 1350, move dist 500: -> {t_ok['energy']} "
      f"(expected {expect_ok}) ({t_ok['outcome']})")
check("affordable move: 10000 +500 -1350 -1500 == expected",
      t_ok["outcome"] == "move_applied" and t_ok["energy"] == expect_ok, f"{t_ok['energy']} == {expect_ok}")
# cap: near-max, zero-distance move (cost 0) -> basal caps at MAX
t_cap = E.resolve_tick(MAX_ENERGY - 100, "move", 0, move_distance=0)
print(f"    energy {MAX_ENERGY-100}, think 0, move dist 0: -> {t_cap['energy']} (cap {MAX_ENERGY})")
check("MAX_ENERGY cap holds under movement", t_cap["energy"] == MAX_ENERGY)

# ------------------------------------------- 6. spawn_location populated + spread
print("\n[6] spawn placement -> spawn_location populated (non-null), spread, in-bounds, seeded")
pts = place_points(random.Random(42), 8)
for i, (x, y) in enumerate(pts, 1):
    print(f"    agent {i}: spawn=({x:.2f}, {y:.2f})")
check("every spawn position is non-null (populates spawn_location)",
      all(x is not None and y is not None for (x, y) in pts))
check("all spawns in-bounds [0,PLANE]",
      all(0.0 <= x <= PLANE_WIDTH and 0.0 <= y <= PLANE_HEIGHT for (x, y) in pts))
check("spawns are spread (not all identical)", len(set(pts)) == len(pts))
check("placement is deterministic under a fixed seed",
      place_points(random.Random(42), 8) == pts)

# ----------------------------- 7. v1 economy UNCHANGED when no move is taken
print("\n[7] v1 economy numbers UNCHANGED (no move taken)")
BURN = 1350
h = E.resolve_tick(15000, "harvest", BURN, target="apple")
check("harvest tick unchanged: 15000 +500 -1350 -COST_HARVEST",
      h["energy"] == 15000 + BASAL_INCOME - BURN - COST_HARVEST,
      f"{h['energy']} == {15000 + BASAL_INCOME - BURN - COST_HARVEST}")
ea = E.resolve_tick(5000, "eat", BURN, target="apple")
check("eat tick unchanged: 5000 +500 -1350 +YIELD_EAT_RAW",
      ea["energy"] == 5000 + BASAL_INCOME - BURN + YIELD_EAT_RAW,
      f"{ea['energy']} == {5000 + BASAL_INCOME - BURN + YIELD_EAT_RAW}")
dr = E.resolve_tick(5000, "drink", BURN, target="water")
check("drink tick unchanged: 5000 +500 -1350 +YIELD_DRINK",
      dr["energy"] == 5000 + BASAL_INCOME - BURN + YIELD_DRINK)
rs = E.resolve_tick(5000, "rest", BURN, target=None)
check("rest tick unchanged: 5000 +500 -1350 +YIELD_REST",
      rs["energy"] == 5000 + BASAL_INCOME - BURN + YIELD_REST)
check("no economy constant moved (COST_HARVEST/BASAL/MAX/yields intact)",
      (COST_HARVEST, BASAL_INCOME, MAX_ENERGY, YIELD_EAT_RAW, YIELD_DRINK, YIELD_REST)
      == (1200, 500, 30000, 12000, 9000, 2000))

print("\n" + "=" * 72)
passed = sum(_checks)
print(f"RESULT: {passed}/{len(_checks)} checks passed")
print("=" * 72)
import sys; sys.exit(0 if passed == len(_checks) else 1)
