"""
Deterministic energy-ledger test (Pass 1) - NO GPU, NO DB, NO network.

Stubs the inference token cost at a fixed value so the ledger is deterministic,
then drives a handful of agents over a series of ticks and prints the per-tick
energy trace for each, checking every worked number in the spec (sections 4-5).

Run:  python test_energy_ledger.py   (from the code root, USE_MOCK not needed)
"""

from constants import (
    MAX_ENERGY, BASAL_INCOME, COST_HARVEST, COST_COOK,
    YIELD_EAT_RAW, YIELD_REST, INACTIVITY_THRESHOLD_TICKS,
)
from mechanics import energy as E

STUB_TOKENS = 5000   # fixed (prompt+completion) inference cost for determinism

_checks = []
def check(name, ok, detail=""):
    _checks.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def run(label, start, steps, sheltered=False):
    """steps: list of (action_type, target, precondition_ok). Returns the full
    per-tick trace as a list of dicts, printing each tick."""
    print(f"\n=== {label}  (start={start}, stub inference={STUB_TOKENS}/tick) ===")
    e = start
    trace = []
    for i, (action, target, precond) in enumerate(steps, 1):
        r = E.resolve_tick(e, action, STUB_TOKENS, target=target,
                           sheltered=sheltered, precondition_ok=precond)
        delta = r["energy"] - e
        tgt = f" {target}" if target else ""
        print(f"  tick {i:>2}: {action}{tgt:<14} "
              f"{e:>7} -> {r['energy']:>7}  (d={delta:+d})  "
              f"{r['outcome']}" + ("  SOFT-LOCKED" if r["soft_locked"] else ""))
        e = r["energy"]
        trace.append(r)
    return trace


print("=" * 70)
print("ENERGY LEDGER - deterministic trace test (Pass 1)")
print(f"MAX_ENERGY={MAX_ENERGY}  BASAL_INCOME={BASAL_INCOME}  "
      f"stub_inference={STUB_TOKENS}")
print(f"soft-lock threshold (cheapest costed action) = {E.SOFT_LOCK_THRESHOLD}")
print(f"INACTIVITY_THRESHOLD_TICKS = {INACTIVITY_THRESHOLD_TICKS} "
      f"(ticks in one in-world day)")
print("=" * 70)

# (a) harvest-then-eat cycle: start below cap so basal is not clipped, so the
#     2-tick cycle net is clean. Expect about +30k per harvest+eat cycle.
a = run("(a) harvest-then-eat cycle", 50000,
        [("harvest", "apple", True), ("eat", "apple", True)] * 3)
cycle_net = a[1]["energy"] - 50000          # after the first harvest+eat cycle
check("(a) harvest-then-eat cycle strongly net-positive (~+30k / 2-tick cycle)",
      28000 <= cycle_net <= 32000, f"cycle net = {cycle_net:+d}")

# (b) harvest but never eat: start full. Steady-state (once below the cap) should
#     bleed about -7k/tick and eventually soft-lock.
b = run("(b) harvest but never eat", MAX_ENERGY,
        [("harvest", "apple", True)] * 16)
steady_delta = b[2]["energy"] - b[1]["energy"]   # a mid, below-cap tick
check("(b) harvest-never-eat bleeds ~-7k/tick",
      steady_delta == -(STUB_TOKENS + COST_HARVEST - BASAL_INCOME),
      f"per-tick delta = {steady_delta:+d}")
check("(b) harvest-never-eat eventually soft-locks",
      any(t["soft_locked"] for t in b),
      f"first soft-lock at tick {next((i+1 for i,t in enumerate(b) if t['soft_locked']), None)}")

# (c) rest only: nets about +3k/tick (survives slowly, banks little).
c = run("(c) rest only", 20000, [("rest", None, True)] * 6)
rest_delta = c[1]["energy"] - c[0]["energy"]
check("(c) rest-only nets ~+3k/tick",
      rest_delta == BASAL_INCOME + YIELD_REST - STUB_TOKENS,
      f"per-tick delta = {rest_delta:+d}")

# (d) think only / do nothing else: a free no-yield action (e.g. an unreciprocated
#     message). Nets about -3k/tick and bleeds out.
d = run("(d) think only (free, no yield)", 20000, [("message", None, True)] * 8)
think_delta = d[1]["energy"] - d[0]["energy"]
check("(d) think-only nets ~-3k/tick and bleeds out",
      think_delta == BASAL_INCOME - STUB_TOKENS and d[-1]["energy"] < d[0]["energy"],
      f"per-tick delta = {think_delta:+d}, ended at {d[-1]['energy']}")

# (e) driven to 0 then rescued by eating a stubbed gifted apple.
e_steps = [("message", None, True)] * 8 + [("eat", "apple", True)]  # think down, then eat gift
e = run("(e) 0-floor then social rescue (gifted apple)", 6000, e_steps)
hit_zero = any(t["energy"] == 0 for t in e[:-1])
rescued = e[-1]["energy"] > E.SOFT_LOCK_THRESHOLD
check("(e) reaches 0 then recovers after eating the gifted apple",
      hit_zero and rescued, f"min={min(t['energy'] for t in e)}, final={e[-1]['energy']}")

print("\n--- invariant checks ---")

# 0-floor: energy never goes negative across every trace above.
never_negative = all(t["energy"] >= 0 for tr in (a, b, c, d, e) for t in tr)
check("0-floor holds (energy never negative)", never_negative)

# MAX cap: eating near the cap clips at MAX_ENERGY.
cap = E.resolve_tick(98000, "eat", STUB_TOKENS, target="apple")
check("MAX_ENERGY cap holds (eat near cap clips)", cap["energy"] == MAX_ENERGY,
      f"98000 -> {cap['energy']}")

# Thinking is never denied; a costed action IS denied when balance < cost.
# Soft-locked agent (energy 1000) tries to harvest: inference still debits
# (the thought happened), the costed action is denied.
denied = E.resolve_tick(1000, "harvest", STUB_TOKENS, target="apple")
check("thinking never denied (inference applied even when broke)",
      denied["before_action"] == max(0, 1000 + BASAL_INCOME - STUB_TOKENS))
check("costed action denied when balance < cost",
      denied["outcome"] == "costed_denied" and denied["applied"] is False,
      f"energy {1000} -> {denied['energy']}, outcome={denied['outcome']}")
# ...and the same broke agent's FREE actions are always allowed.
freed = E.resolve_tick(1000, "eat", STUB_TOKENS, target="apple")
check("free action allowed at the same low balance",
      freed["applied"] is True and freed["outcome"] == "free_applied")

# Death conditions gone: the module has no death path; soft-lock/inactivity only.
check("no death mechanic in the energy ledger (soft-lock/inactivity only)",
      not hasattr(E, "apply_death") and hasattr(E, "is_soft_locked"))

print("\n--- sample built prompt (energy / affordability + participation directive) ---")
# Render the Pass-1 prompt pieces without a DB/GPU via the pure renderers.
from models.prompt_builder import (
    energy_status_lines, available_actions_lines, directive_lines,
)

def sample_prompt(energy):
    parts = ["--- YOUR STATUS ---", "  Model ID:           flat_C1_01"]
    parts += energy_status_lines(energy)
    parts += [""] + available_actions_lines(energy)
    parts += [""] + directive_lines()
    return "\n".join(parts)

healthy = sample_prompt(43000)
locked  = sample_prompt(1000)
print("\n[ HEALTHY AGENT, energy=43000 ]")
print(healthy)
print("\n[ SOFT-LOCKED AGENT, energy=1000 ]  (only the changed lines shown)")
for line in locked.splitlines():
    if "Energy:" in line or "SOFT-LOCKED" in line or "harvest" in line or "cook" in line or "build" in line:
        print(line)

check("participation directive present ('participate as much as you possibly can')",
      "participate as much as you possibly can" in healthy.lower())
check("survival/death directive removed from the prompt",
      "die" not in healthy.lower() and "survive" not in healthy.lower())
check("current energy shown in prompt", "Energy: 43000 / 100000" in healthy)
def _line(text, needle):
    return next((l for l in text.splitlines() if l.strip().startswith(needle)), "")
check("costed action shows cost + affordable when funded",
      "4000 energy" in _line(healthy, "harvest") and "[affordable]" in _line(healthy, "harvest"))
check("costed action shows TOO LOW when soft-locked",
      "4000 energy" in _line(locked, "harvest") and "[TOO LOW]" in _line(locked, "harvest"))
check("free action shown as free (no fixed energy cost)",
      "free (no fixed energy cost)" in _line(healthy, "eat"))

print("\n" + "=" * 70)
passed = sum(1 for _, ok, _ in _checks if ok)
print(f"RESULT: {passed}/{len(_checks)} checks passed")
print("=" * 70)
import sys
sys.exit(0 if passed == len(_checks) else 1)
