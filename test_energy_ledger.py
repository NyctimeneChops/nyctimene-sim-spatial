"""
Deterministic energy-ledger test (Pass 1, v1 recalibration) - NO GPU/DB/network.

The ledger is validated against the MEASURED real per-decision burn (not the old
5000 stub): ~1350 early (day 1) rising to ~1660 mature. Every scenario is run at
BOTH ends so we confirm the constants produce pressure across the whole run.

GOVERNING PRINCIPLE checked here: BASAL_INCOME < the real per-thought cost, so an
agent that only thinks LOSES energy each tick (think-only net-NEGATIVE).
"""

from constants import (
    MAX_ENERGY, BASAL_INCOME, COST_HARVEST, COST_COOK, COST_BUILD,
    YIELD_EAT_RAW, YIELD_EAT_COOKED, YIELD_DRINK, YIELD_REST, YIELD_REST_SHELTER,
    INACTIVITY_THRESHOLD_TICKS,
)
from mechanics import energy as E

EARLY_BURN, MATURE_BURN = 1350, 1660   # measured real prompt+completion cost

_checks = []
def check(name, ok, detail=""):
    _checks.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def run(label, start, steps, burn, sheltered=False):
    print(f"\n=== {label}  (start={start}, burn={burn}/thought) ===")
    e, trace = start, []
    for i, (action, target, precond) in enumerate(steps, 1):
        r = E.resolve_tick(e, action, burn, target=target, sheltered=sheltered,
                           precondition_ok=precond)
        d = r["energy"] - e
        tgt = f" {target}" if target else ""
        print(f"  t{i:>2}: {action}{tgt:<12} {e:>6} -> {r['energy']:>6}  (d={d:+d})  "
              f"{r['outcome']}" + ("  SOFT-LOCKED" if r["soft_locked"] else ""))
        e = r["energy"]; trace.append(r)
    return trace


print("=" * 72)
print("ENERGY LEDGER v1 - deterministic traces at the REAL measured burn")
print(f"MAX_ENERGY={MAX_ENERGY}  BASAL_INCOME={BASAL_INCOME}  "
      f"soft-lock<{E.SOFT_LOCK_THRESHOLD}  inactivity@{INACTIVITY_THRESHOLD_TICKS} ticks")
print(f"costs harvest/cook/build={COST_HARVEST}/{COST_COOK}/{COST_BUILD}  "
      f"yields eat/cooked/drink/rest={YIELD_EAT_RAW}/{YIELD_EAT_COOKED}/{YIELD_DRINK}/{YIELD_REST}")
print(f"real burn: EARLY={EARLY_BURN}  MATURE={MATURE_BURN}   "
      f"(BASAL {BASAL_INCOME} < both => idle bleeds)")
print("=" * 72)

for burn in (EARLY_BURN, MATURE_BURN):
    tag = "EARLY" if burn == EARLY_BURN else "MATURE"
    print(f"\n############ BURN = {burn} ({tag}) ############")

    a = run("(a) harvest-then-eat cycle", 15000,
            [("harvest", "apple", True), ("eat", "apple", True)] * 3, burn)
    cycle_net = a[1]["energy"] - 15000
    check(f"[{tag}] (a) harvest-then-eat cycle strongly net-positive",
          cycle_net == 11800 - 2 * burn and cycle_net > 5000, f"cycle net = {cycle_net:+d}")

    b = run("(b) harvest but never eat", MAX_ENERGY,
            [("harvest", "apple", True)] * 18, burn)
    steady = b[2]["energy"] - b[1]["energy"]
    check(f"[{tag}] (b) harvest-never-eat bleeds each tick",
          steady == -(burn + COST_HARVEST - BASAL_INCOME) and steady < 0,
          f"steady delta = {steady:+d}")
    check(f"[{tag}] (b) harvest-never-eat soft-locks",
          any(t["soft_locked"] for t in b),
          f"first at t{next((i+1 for i,t in enumerate(b) if t['soft_locked']), None)}")

    c = run("(c) rest only", 10000, [("rest", None, True)] * 5, burn)
    rest_delta = c[1]["energy"] - c[0]["energy"]
    eat_delta = BASAL_INCOME - burn + YIELD_EAT_RAW   # a non-capped eat tick
    check(f"[{tag}] (c) rest-only slightly POSITIVE",
          rest_delta == BASAL_INCOME + YIELD_REST - burn and rest_delta > 0,
          f"rest delta = {rest_delta:+d}")
    check(f"[{tag}] (c) rest gain is well BELOW eating",
          rest_delta < 0.2 * eat_delta, f"rest {rest_delta} vs eat {eat_delta}")

    d = run("(d) think only (free, no yield)", 10000, [("message", None, True)] * 6, burn)
    think_delta = d[1]["energy"] - d[0]["energy"]
    check(f"[{tag}] (d) think-only is NET-NEGATIVE (the fix)",
          think_delta == BASAL_INCOME - burn and think_delta < 0,
          f"think delta = {think_delta:+d}  (BASAL {BASAL_INCOME} < burn {burn})")

print("\n############ burn-independent invariants ############")

e_tr = run("(e) 0-floor then social rescue (gifted apple)", 6000,
           [("message", None, True)] * 8 + [("eat", "apple", True)], MATURE_BURN)
check("(e) reaches 0 then recovers after eating the gifted apple",
      any(t["energy"] == 0 for t in e_tr[:-1]) and e_tr[-1]["energy"] > E.SOFT_LOCK_THRESHOLD,
      f"min={min(t['energy'] for t in e_tr)}, final={e_tr[-1]['energy']}")

alltr = list(e_tr)
for burn in (EARLY_BURN, MATURE_BURN):
    alltr += run("(bleed check)", 5000, [("message", None, True)] * 6, burn)
check("0-floor holds (energy never negative)", all(t["energy"] >= 0 for t in alltr))

cap = E.resolve_tick(MAX_ENERGY - 1000, "eat", MATURE_BURN, target="apple")
check("MAX_ENERGY cap holds (eat near cap clips)", cap["energy"] == MAX_ENERGY,
      f"{MAX_ENERGY-1000} -> {cap['energy']}")

denied = E.resolve_tick(500, "harvest", MATURE_BURN, target="apple")   # 500 < cook 1000
check("thinking never denied (inference applied even when broke)",
      denied["before_action"] == max(0, 500 + BASAL_INCOME - MATURE_BURN))
check("costed action denied when balance < cost",
      denied["outcome"] == "costed_denied" and denied["applied"] is False)
freed = E.resolve_tick(500, "eat", MATURE_BURN, target="apple")
check("free action allowed at the same low balance", freed["applied"] is True)
check("no death mechanic (soft-lock/inactivity only)",
      not hasattr(E, "apply_death") and hasattr(E, "is_soft_locked"))

print("\n############ sample built prompt (energy / affordability + directive) ############")
from models.prompt_builder import energy_status_lines, available_actions_lines, directive_lines
def sample(energy):
    p = ["--- YOUR STATUS ---", "  Model ID:           flat_C1_01"]
    p += energy_status_lines(energy) + [""] + available_actions_lines(energy) + [""] + directive_lines()
    return "\n".join(p)
healthy, locked = sample(15000), sample(500)
print("\n[ HEALTHY energy=15000 ]"); print(healthy)
print("\n[ SOFT-LOCKED energy=500 ] (changed lines)")
for l in locked.splitlines():
    if any(k in l for k in ("Energy:", "SOFT-LOCKED", "harvest", "cook", "build")):
        print(l)
def line(t, n): return next((l for l in t.splitlines() if l.strip().startswith(n)), "")
check("participation directive present", "participate as much as you possibly can" in healthy.lower())
check("survival/death directive gone", "die" not in healthy.lower() and "survive" not in healthy.lower())
check("current energy shown (new scale)", "Energy: 15000 / 30000" in healthy)
check("costed action shows cost+affordable when funded",
      f"{COST_HARVEST} energy" in line(healthy, "harvest") and "[affordable]" in line(healthy, "harvest"))
check("costed action shows TOO LOW when soft-locked", "[TOO LOW]" in line(locked, "harvest"))
check("free action shown as free", "free (no fixed energy cost)" in line(healthy, "eat"))

print("\n" + "=" * 72)
passed = sum(_checks)
print(f"RESULT: {passed}/{len(_checks)} checks passed")
print("=" * 72)
import sys; sys.exit(0 if passed == len(_checks) else 1)
