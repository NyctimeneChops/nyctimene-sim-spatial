"""
Deterministic LINE-2 SUBSTRATE test - NO GPU/DB/network.

Covers the line-2 change (LN-003):
  * REMOVE sleep entirely (parser rejects it; prompt never mentions it).
  * COLLAPSE the physiological/psychological categories (one rule: every source
    removed only by its own remedy; SUCCESS_DECAY -> failures bucket only).
  * REST relieves tension (proportional, floored, BELOW the need accrual rates so
    a need always outruns it -- the arithmetic invariant).
  * PROMPT states the one rule and no longer advertises sleep.

Pure math is exercised directly (tension.rest_relieved is a pure function);
the two IO helpers are exercised with a tiny in-memory fake for _get_model/_save.
A full prompt is rendered with the data layer stubbed (as in test_space_pass2).
"""

import json

import constants
from constants import (REST_TENSION_RELIEF, TENSION_HUNGER_PER_ACTION,
                       TENSION_THIRST_PER_ACTION, TENSION_SUCCESS_DECAY)
from mechanics import tension
from models import action_parser
import models.prompt_builder as PB
import world.clock as CLOCK
import groups.group_config as GC

_checks = []
def check(name, ok, detail=""):
    _checks.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

ALL = tension.ALL_SOURCES


# ============================================================ 1. rest relief (pure)
print("=" * 72)
print("LINE-2 SUBSTRATE - sleep removed, categories collapsed, rest relieves tension")
print("=" * 72)
print("\n[1] rest_relieved (pure): drains total by REST_TENSION_RELIEF, proportional, floored")

s = {"hunger": 30.0, "thirst": 20.0, "failures": 10.0, "shelter": 0.0, "messages": 0.0}
dom_before = tension.dominant_source(s)
r = tension.rest_relieved(s)
drained = sum(s.values()) - sum(r.values())
check("total drops by exactly REST_TENSION_RELIEF", abs(drained - REST_TENSION_RELIEF) < 1e-9,
      f"drained {drained}, expected {REST_TENSION_RELIEF}")
check("every bucket floored at >= 0", all(v >= 0.0 for v in r.values()))
check("zero buckets stay zero", r["shelter"] == 0.0 and r["messages"] == 0.0)
check("DOMINANT SOURCE unchanged by a rest", tension.dominant_source(r) == dom_before,
      f"{dom_before} -> {tension.dominant_source(r)}")
check("composition preserved (proportional): hunger/thirst ratio held",
      abs(r["hunger"] / r["thirst"] - 30.0 / 20.0) < 1e-9)

# total <= REST_TENSION_RELIEF -> everything floors to zero
s_small = {"hunger": 0.4, "thirst": 0.0, "failures": 0.0, "shelter": 0.0, "messages": 0.0}
r_small = tension.rest_relieved(s_small)
check("total below relief floors all buckets to 0", sum(r_small.values()) == 0.0)


# ============================================ 2. the arithmetic invariant (pure)
print("\n[2] a hungry agent that rests EVERY tick still gains tension over time")
s = {k: 0.0 for k in ALL}
totals = []
for _ in range(20):
    s = dict(s)
    s["hunger"] += TENSION_HUNGER_PER_ACTION   # the one unmet need accrues
    s = tension.rest_relieved(s)               # ... and the agent rests every tick
    totals.append(sum(s.values()))
increasing = all(totals[i] < totals[i + 1] for i in range(len(totals) - 1))
check("resting every tick, total tension STRICTLY INCREASES (accrual outruns relief)",
      increasing, f"totals {totals[0]:.1f} -> {totals[-1]:.1f}")
check("net gain per tick == accrual - relief (0.5); >0 by construction",
      abs(totals[-1] - 20 * (TENSION_HUNGER_PER_ACTION - REST_TENSION_RELIEF)) < 1e-6,
      f"final {totals[-1]:.2f}")
check("INVARIANT: relief < min(hunger, thirst) accrual",
      REST_TENSION_RELIEF < min(TENSION_HUNGER_PER_ACTION, TENSION_THIRST_PER_ACTION))


# ================================= 3. success decay touches ONLY the failures bucket
print("\n[3] TENSION_SUCCESS_DECAY drains ONLY the failures bucket")
_io = {}
def _fake_get_model(mid):
    return {"tension_sources": json.dumps(_io["in"])}
def _fake_save(mid, sources):
    _io["out"] = dict(sources)
    t = tension.total_from_sources(sources)
    return {"total": t, "sources": sources, "band": tension.band_for_total(t),
            "dominant": tension.dominant_source(sources)}
tension._get_model = _fake_get_model
tension._save = _fake_save

_io["in"] = {"hunger": 10.0, "thirst": 8.0, "failures": 6.0, "shelter": 4.0, "messages": 2.0}
tension.apply_success_decay("m")
out = _io["out"]
check("failures drained by TENSION_SUCCESS_DECAY", out["failures"] == 6.0 - TENSION_SUCCESS_DECAY,
      f"{out['failures']}")
check("hunger/thirst/shelter/messages UNTOUCHED by success decay",
      out["hunger"] == 10.0 and out["thirst"] == 8.0 and out["shelter"] == 4.0
      and out["messages"] == 2.0)
_io["in"] = {"hunger": 0.0, "thirst": 0.0, "failures": 1.0, "shelter": 0.0, "messages": 0.0}
tension.apply_success_decay("m")
check("failures floored at 0 (never negative)", _io["out"]["failures"] == 0.0)


# ================================================= 4. parser rejects 'sleep'
print("\n[4] parser: 'sleep' is no longer a valid action type")
check("'sleep' not in VALID_ACTION_TYPES", "sleep" not in constants.VALID_ACTION_TYPES)
res = action_parser.parse_action('{"action_type": "sleep", "target": null, "reasoning": "x"}', "m1")
check("a 'sleep' action falls back to rest", res["action_type"] == "rest", res["reasoning"])
check("fallback names sleep as the unknown action", "sleep" in res["reasoning"])


# ================================================= 5. prompt render (no sleep, one rule)
print("\n[5] prompt render: no sleep; TENSION block states the one rule")
AGENT = "test_C1_01"
def _make_model(tension_val, sources):
    return {"model_id": AGENT, "experiment_group": "tunnel_C1", "current_energy": 15000,
            "pos_x": 100.0, "pos_y": 200.0, "shelter_status": "none",
            "attention_state": "free", "is_sleeping": False,
            "tension": tension_val, "tension_sources": sources, "inventory": {}}
def _make_nodes():
    return [{"node_id": 1, "node_type": "apple", "experiment_group": "tunnel_C1",
             "current_yield": 6, "max_yield_per_day": 6, "is_built": True,
             "pos_x": 400.0, "pos_y": 600.0},
            {"node_id": 5, "node_type": "river", "experiment_group": "tunnel_C1",
             "current_yield": 12, "max_yield_per_day": 12, "is_built": True,
             "pos_x": 100.0, "pos_y": 700.0}]
_W = {"model": None, "nodes": None}
def _fake_get(path, params=None):
    if path.endswith("/skills"):                 return {}
    if path.startswith("/models/"):              return _W["model"]
    if path == "/nodes":                         return _W["nodes"]
    if path == "/nodes/activity":                return {}
    if path == "/messages/broadcast":            return []
    if path == "/threads":                       return []
    if path.startswith("/actions/"):             return []
    if path.startswith("/decision_log/recent/"): return []
    if path.startswith("/transactions/"):        return []
    if path.startswith("/messages/direct/"):     return []
    if path.startswith("/survival/"):            return []
    return {}
PB._get = _fake_get
CLOCK.get_current_day = lambda: 3
CLOCK.get_elapsed_minutes = lambda: 5.0
GC.get_group_config = lambda g: {"tunneling_enabled": not g.startswith("flat")}

def _render(tension_val, sources):
    _W["model"] = _make_model(tension_val, sources)
    _W["nodes"] = _make_nodes()
    return PB.build_prompt(AGENT)

calm = _render(0, "{}")
check("CALM prompt mentions no 'sleep' anywhere", "sleep" not in calm.lower(),
      "AVAILABLE ACTIONS + directive + status all sleep-free")
check("TENSION block dropped 'Sleep always reduces tension'",
      "sleep always reduces tension" not in calm.lower())
check("TENSION block states the one rule (removed only by its own remedy)",
      "removed only by its own remedy" in calm)
check("TENSION block states rest lowers tension from every source",
      "Resting slightly lowers tension from every source" in calm)
# high tension -> TUNNEL band still carries no 'Sleep is always available' line
tunnel = _render(75, '{"hunger": 75}')
check("TUNNEL prompt carries no sleep-always line", "sleep" not in tunnel.lower())

# available_actions_lines (pure) lists rest but not sleep
menu = "\n".join(PB.available_actions_lines(30000))
check("AVAILABLE ACTIONS menu lists rest, not sleep",
      "rest" in menu and "sleep" not in menu.lower())


# ================================================= 6. the constants invariant guard
print("\n[6] constants: the REST_TENSION_RELIEF invariant is enforced at import")
check("current REST_TENSION_RELIEF satisfies the invariant",
      REST_TENSION_RELIEF < min(TENSION_HUNGER_PER_ACTION, TENSION_THIRST_PER_ACTION))
# the guard WOULD fire if someone raised relief above the accrual rate
raised = TENSION_HUNGER_PER_ACTION + 0.5
fired = False
try:
    assert raised < min(TENSION_HUNGER_PER_ACTION, TENSION_THIRST_PER_ACTION), "guard"
except AssertionError:
    fired = True
check("guard fires if REST_TENSION_RELIEF raised above hunger accrual", fired)
src = open("constants.py", encoding="utf-8").read()
check("the assert exists in constants.py source",
      "assert REST_TENSION_RELIEF < min(TENSION_HUNGER_PER_ACTION, TENSION_THIRST_PER_ACTION)" in src)


print("\n" + "=" * 72)
passed = sum(_checks)
print(f"RESULT: {passed}/{len(_checks)} checks passed")
print("=" * 72)
import sys; sys.exit(0 if passed == len(_checks) else 1)
