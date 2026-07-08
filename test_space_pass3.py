"""
Deterministic space-milestone PASS 3 test (spatial ENFORCEMENT) - NO GPU/DB/network.
Updated for the pass-3 CORRECTION: exact-point occupancy replaces the removed
PERSONAL_RADIUS proximity model.

Two layers:
  (1) PURE functions (movement.at_node / destination_occupied) - the enforcement
      decisions, hand-checkable.
  (2) HANDLER integration - the Agent handlers driven against a fake in-memory world,
      so we observe real behaviour: not-at-node harvest fails, move->harvest succeeds,
      proximity NO LONGER blocks a move (the fixed bug), co-harvest stacking works, and
      checks stay inside the sealed group.
"""
from constants import AT_NODE_EPSILON, COST_HARVEST, MOVE_COST_PER_UNIT
from mechanics.movement import at_node, destination_occupied

_checks = []
def check(name, ok, detail=""):
    _checks.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

print("=" * 72)
print("SPACE MILESTONE PASS 3 (corrected) - presence + EXACT-POINT occupancy")
print(f"AT_NODE_EPSILON={AT_NODE_EPSILON}  COST_HARVEST={COST_HARVEST}  "
      f"MOVE_COST_PER_UNIT={MOVE_COST_PER_UNIT}  (PERSONAL_RADIUS removed)")
print("=" * 72)

# ---------------------------------------------------- [1] pure enforcement logic
print("\n[1] PURE: at_node (presence) + destination_occupied (exact-point occupancy)")
check("at_node exact coords -> True", at_node(300, 400, 300, 400) is True)
check("at_node within epsilon (float drift) -> True", at_node(300, 400, 300 + 1e-7, 400) is True)
check("at_node 5 units away -> False (near is NOT at; no node radius)", at_node(300, 400, 305, 400) is False)

# NODE destination: NEVER blocked (co-harvest stacking), even when occupied.
check("dest_occupied: NODE dest, empty -> clear",
      destination_occupied(300, 400, [], dest_is_node=True) is None)
check("dest_occupied: NODE dest occupied by another agent -> clear (co-harvest stack)",
      destination_occupied(300, 400, [(300, 400)], dest_is_node=True) is None)
# NON-node destination: blocked ONLY if EXACTLY occupied.
check("dest_occupied: NON-node dest, empty -> clear",
      destination_occupied(300, 400, [], dest_is_node=False) is None)
o = destination_occupied(300, 400, [(300, 400)], dest_is_node=False)
check("dest_occupied: NON-node dest EXACTLY occupied -> BLOCKED", o == (300, 400), f"occupant={o}")
check("dest_occupied: NON-node dest, agent ~11 units away (old radius) -> CLEAR "
      "(proximity no longer blocks)",
      destination_occupied(300, 400, [(310, 405)], dest_is_node=False) is None)
check("dest_occupied: NON-node dest, agent far -> clear",
      destination_occupied(300, 400, [(600, 600)], dest_is_node=False) is None)
# PERSONAL_RADIUS is fully gone.
import mechanics.movement as MV, constants as C
check("PERSONAL_RADIUS constant REMOVED", not hasattr(C, "PERSONAL_RADIUS"))
check("radius_block function REMOVED", not hasattr(MV, "radius_block"))
check("destination_occupied function present", hasattr(MV, "destination_occupied"))

# ---------------------------------------------------- [2] handler integration
print("\n[2] HANDLER integration (fake world; observe real handler behaviour)")

import models.agent as AG
import world.clock as CK

class Resp:
    def __init__(self, data, status=200): self._d, self.status_code = data, status
    def json(self): return self._d
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")

class FakeReq:
    def __init__(self, w): self.w = w
    def get(self, url, params=None, timeout=None):
        p = url.split("5000", 1)[1]; w = self.w
        if p == "/models": return Resp(list(w["models"].values()))
        if p.startswith("/models/"): return Resp(w["models"].get(p.split("/")[2], {}))
        if p == "/nodes":
            g = (params or {}).get("group")
            return Resp([n for n in w["nodes"] if n["experiment_group"] == g])
        if p.startswith("/inventory/"):
            inv = w["inv"].get(p.split("/")[2], {})
            return Resp({"inventory": [{"resource_type": k, "quantity": v} for k, v in inv.items()]})
        return Resp({})
    def post(self, url, json=None, timeout=None):
        p = url.split("5000", 1)[1]; w = self.w; b = json or {}
        if p.endswith("/energy/adjust"):
            m = w["models"][p.split("/")[2]]
            m["current_energy"] = max(0, min(m["current_energy"] + b["delta"], m["max_energy"]))
            return Resp({"energy": m["current_energy"]})
        if p.endswith("/position"):
            m = w["models"][p.split("/")[2]]; m["pos_x"], m["pos_y"] = b["pos_x"], b["pos_y"]
            return Resp({"pos_x": m["pos_x"], "pos_y": m["pos_y"]})
        if p.endswith("/harvest"): return Resp({"succeeded": b.get("succeeded")})
        if p.endswith("/add"):
            d = w["inv"].setdefault(p.split("/")[2], {})
            d[b["resource_type"]] = d.get(b["resource_type"], 0) + b["quantity"]; return Resp({})
        if p.endswith("/deduct"):
            d = w["inv"].setdefault(p.split("/")[2], {})
            if d.get(b["resource_type"], 0) < b["quantity"]: return Resp({"error": "x"}, 400)
            d[b["resource_type"]] -= b["quantity"]; return Resp({})
        if p == "/actions": w["actions"].append(b); return Resp({"action_id": len(w["actions"])})
        return Resp({})

AG.get_skill_level = lambda *a, **k: 1
AG.calculate_failure_rate = lambda *a, **k: 0.0
AG.increment_skill = lambda *a, **k: 2
CK.get_current_day = lambda: 3
AG.Agent._apply_action_tension = lambda self, at, s: 0
AG.Agent._record_decision_log = lambda self, aid: None

def model(mid, group, x, y, e=15000):
    return {"model_id": mid, "experiment_group": group, "current_energy": e,
            "max_energy": 30000, "pos_x": x, "pos_y": y}
def world(models, nodes):
    return {"models": {m["model_id"]: m for m in models}, "nodes": nodes, "inv": {}, "actions": []}
def bind(w): AG.requests = FakeReq(w); return w
def last(w, atype=None):
    for a in reversed(w["actions"]):
        if atype is None or a["action_type"] == atype: return a
    return None
def pos(w, mid): return (w["models"][mid]["pos_x"], w["models"][mid]["pos_y"])

APPLE = {"node_id": 1, "node_type": "apple", "experiment_group": "flat_C1", "current_yield": 6,
         "max_yield_per_day": 6, "is_built": True, "pos_x": 300.0, "pos_y": 400.0}  # dist 500 from (0,0)
ROCK  = {"node_id": 8, "node_type": "rock", "experiment_group": "flat_C1", "current_yield": 4,
         "max_yield_per_day": 6, "is_built": True, "pos_x": 505.0, "pos_y": 505.0}

# --- PRESENCE (UNCHANGED from pass 3): not-at-node harvest FAILS --------------
print("\n  PRESENCE requirement (unchanged)")
w = bind(world([model("flat_C1_01", "flat_C1", 0.0, 0.0)], [dict(APPLE)]))
a = AG.Agent("flat_C1_01", "flat_C1")
a._handle_harvest({"action_type": "harvest", "target": "apple"}, 1000)
h = last(w, "harvest")
check("harvest while NOT at the apple node -> recorded FAILED", h and h["succeeded"] is False)
check("  ...yields NO resource", w["inv"].get("flat_C1_01", {}).get("apple", 0) == 0)
check("  ...costs only the inference (precondition denial)",
      w["models"]["flat_C1_01"]["current_energy"] == 15000 - 1000)

# move -> now at node -> harvest SUCCEEDS
w = bind(world([model("flat_C1_01", "flat_C1", 0.0, 0.0)], [dict(APPLE)]))
a = AG.Agent("flat_C1_01", "flat_C1")
a._handle_move({"action_type": "move", "target": "apple"}, 500)
check("move to apple SUCCEEDS and lands exactly on the node",
      last(w, "move")["succeeded"] and pos(w, "flat_C1_01") == (300.0, 400.0))
a._handle_harvest({"action_type": "harvest", "target": "apple"}, 1000)
check("harvest AFTER moving to the node -> SUCCEEDS (move -> harvest loop works)",
      last(w, "harvest")["succeeded"] is True)
check("  ...yields the resource", w["inv"].get("flat_C1_01", {}).get("apple", 0) > 0)

# --- non-node action position-agnostic ---------------------------------------
print("\n  non-node actions are position-agnostic")
w = bind(world([model("flat_C1_01", "flat_C1", 123.0, 456.0)], [dict(APPLE)]))
a = AG.Agent("flat_C1_01", "flat_C1")
a._handle_rest({"action_type": "rest", "target": None}, 400)
check("rest succeeds with the agent anywhere", last(w, "rest")["succeeded"] is True)

# --- CORRECTED collision: proximity no longer blocks (THE BUG FIX) -----------
print("\n  CORRECTED collision (exact-point occupancy; NO proximity blocking)")
# A at (500,500) [a NON-node point]; B moves to rock@(505,505), ~7 units away -- INSIDE the
# old PERSONAL_RADIUS. Pass-3 wrongly DENIED this. Now ALLOWED (rock is a node; no radius).
w = bind(world([model("flat_C1_01", "flat_C1", 0.0, 0.0), model("flat_C1_02", "flat_C1", 500.0, 500.0)],
               [dict(ROCK)]))
b = AG.Agent("flat_C1_01", "flat_C1")
b._handle_move({"action_type": "move", "target": "rock"}, 500)
check("move to a node ~7 units from another agent (was PERSONAL_RADIUS-blocked) -> now ALLOWED",
      last(w, "move")["succeeded"] is True and pos(w, "flat_C1_01") == (505.0, 505.0),
      "the specific previously-blocked case now passes")

# A ON node X (apple@300,400); B moves to a DIFFERENT nearby node Y (rock@310,405, ~11 units) -> OK
ROCK_NEAR = {"node_id": 8, "node_type": "rock", "experiment_group": "flat_C1", "current_yield": 4,
             "max_yield_per_day": 6, "is_built": True, "pos_x": 310.0, "pos_y": 405.0}
w = bind(world([model("flat_C1_01", "flat_C1", 0.0, 0.0), model("flat_C1_02", "flat_C1", 300.0, 400.0)],
               [dict(APPLE), ROCK_NEAR]))
b = AG.Agent("flat_C1_01", "flat_C1")
b._handle_move({"action_type": "move", "target": "rock"}, 500)
check("A on node X; B moves to a DIFFERENT nearby node Y -> ALLOWED (nearby-node bug fixed)",
      last(w, "move")["succeeded"] is True and pos(w, "flat_C1_01") == (310.0, 405.0))

# SHARED NODE still works: A on the apple; B moves to the SAME node -> ALLOWED (stack + co-harvest)
w = bind(world([model("flat_C1_01", "flat_C1", 0.0, 0.0), model("flat_C1_02", "flat_C1", 300.0, 400.0)],
               [dict(APPLE)]))
b = AG.Agent("flat_C1_01", "flat_C1")
b._handle_move({"action_type": "move", "target": "apple"}, 500)
check("SHARED NODE: move onto a node another agent occupies -> ALLOWED (co-harvest stack)",
      last(w, "move")["succeeded"] is True and pos(w, "flat_C1_01") == (300.0, 400.0))
b._handle_harvest({"action_type": "harvest", "target": "apple"}, 1000)
check("  ...and the co-located agent can harvest the shared node",
      last(w, "harvest")["succeeded"] is True)

# NON-node occupancy is verified at the function level (above): pass-1 move only targets
# nodes, so a NON-node destination cannot arise from the handler; the rule holds via
# destination_occupied(dest, others, dest_is_node=False) -> BLOCKED when exactly occupied.
print("  (non-node occupancy 'cannot stop on an occupied non-node point' is enforced by")
print("   destination_occupied and checked in [1]; move only targets nodes, so it never fires here)")

# --- SEALED GROUPS -----------------------------------------------------------
print("\n  sealed groups")
w = bind(world([model("flat_C1_01", "flat_C1", 0.0, 0.0), model("flat_C2_01", "flat_C2", 505.0, 505.0)],
               [dict(ROCK)]))
b = AG.Agent("flat_C1_01", "flat_C1")
b._handle_move({"action_type": "move", "target": "rock"}, 500)
check("occupancy check does NOT fire across groups (C2 agent at the coords is ignored)",
      last(w, "move")["succeeded"] is True)

print("\n" + "=" * 72)
passed = sum(_checks)
print(f"RESULT: {passed}/{len(_checks)} checks passed")
print("=" * 72)
import sys; sys.exit(0 if passed == len(_checks) else 1)
