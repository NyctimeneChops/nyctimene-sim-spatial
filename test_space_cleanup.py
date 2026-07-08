"""
Deterministic space-milestone SPATIAL CLEANUP test - NO GPU/DB/network.
Graceful displacement + positional shelter/territory.

  (1) PURE movement.resolve_landing - displacement geometry, cost-for-actual, deny hook.
  (2) HANDLER integration (fake world) - coord/node moves, shelter claim, positional rest
      bonus, owner-exception, claim lifetime, deny-hook wiring, sealed groups.
"""
import math
from constants import (YIELD_REST, YIELD_REST_SHELTER, MOVE_COST_PER_UNIT,
                       DISPLACEMENT_STEP, DISPLACEMENT_DENY_THRESHOLD)
from mechanics.movement import resolve_landing, move_cost, at_node

_checks = []
def check(name, ok, detail=""):
    _checks.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

print("=" * 72)
print("SPATIAL CLEANUP - graceful displacement + positional shelter/territory")
print(f"DISPLACEMENT_STEP={DISPLACEMENT_STEP}  DENY_THRESHOLD={DISPLACEMENT_DENY_THRESHOLD}  "
      f"YIELD_REST={YIELD_REST}  YIELD_REST_SHELTER={YIELD_REST_SHELTER}")
print("=" * 72)

# ---------------------------------------------------- [1] pure displacement
print("\n[1] PURE resolve_landing (graceful displacement)")
r = resolve_landing(0, 0, 100, 0, [(100, 0)], target_is_node=True)   # node target
check("NODE target occupied -> lands EXACTLY on it (no displacement)",
      (r["land_x"], r["land_y"]) == (100, 0) and not r["displaced"])
r = resolve_landing(0, 0, 100, 0, [], target_is_node=False)          # free non-node
check("FREE non-node target -> lands exactly", (r["land_x"], r["land_y"]) == (100, 0) and not r["displaced"])
r = resolve_landing(0, 0, 100, 0, [(100, 0)], target_is_node=False)  # occupied non-node
check("OCCUPIED non-node target -> displaced to nearest free point toward the actor",
      (round(r["land_x"], 6), round(r["land_y"], 6)) == (99.0, 0.0) and r["displaced"],
      f"landed ({r['land_x']:.2f},{r['land_y']:.2f}), displacement {r['displacement']:.2f}")
r = resolve_landing(0, 0, 100, 0, [(100, 0), (99, 0)], target_is_node=False)  # two stacked
check("two obstacles stacked at target -> steps back PAST both",
      round(r["land_x"], 6) == 98.0, f"landed ({r['land_x']:.2f},{r['land_y']:.2f})")
# deny hook
r = resolve_landing(0, 0, 100, 0, [(100, 0)], target_is_node=False, deny_threshold=0.5)
check("DENY HOOK: displacement (1.0) > low threshold (0.5) -> DENIED",
      r["denied"] is True and not r["displaced"])
r = resolve_landing(0, 0, 100, 0, [(100, 0)], target_is_node=False)  # default inf
check("DENY HOOK inert at default (inf) -> completes gracefully (not denied)", r["denied"] is False)

# ---------------------------------------------------- [2] handler integration
print("\n[2] HANDLER integration (fake world)")
import models.agent as AG
import world.clock as CK

class Resp:
    def __init__(self, d, s=200): self._d, self.status_code = d, s
    def json(self): return self._d
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError("HTTP")

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
        mid = p.split("/")[2] if p.startswith("/models/") else None
        if p.endswith("/energy/adjust"):
            m = w["models"][mid]; m["current_energy"] = max(0, min(m["current_energy"] + b["delta"], m["max_energy"]))
            return Resp({"energy": m["current_energy"]})
        if p.endswith("/position"):
            m = w["models"][mid]; m["pos_x"], m["pos_y"] = b["pos_x"], b["pos_y"]; m["spatial_note"] = b.get("note", "")
            return Resp({"pos_x": m["pos_x"], "pos_y": m["pos_y"]})
        if p.endswith("/shelter"):
            m = w["models"][mid]; st = b["shelter_status"]
            if st == "none": m["shelter_status"], m["shelter_x"], m["shelter_y"] = "none", None, None
            elif "pos_x" in b and "pos_y" in b: m["shelter_status"], m["shelter_x"], m["shelter_y"] = st, b["pos_x"], b["pos_y"]
            else: m["shelter_status"] = st
            return Resp({"shelter_status": m["shelter_status"], "shelter_x": m["shelter_x"], "shelter_y": m["shelter_y"]})
        if p.endswith("/add"):
            d = w["inv"].setdefault(mid, {}); d[b["resource_type"]] = d.get(b["resource_type"], 0) + b["quantity"]; return Resp({})
        if p.endswith("/deduct"):
            d = w["inv"].setdefault(mid, {})
            if d.get(b["resource_type"], 0) < b["quantity"]: return Resp({"error": "x"}, 400)
            d[b["resource_type"]] -= b["quantity"]; return Resp({})
        if p == "/actions": w["actions"].append(b); return Resp({"action_id": len(w["actions"])})
        if p == "/events": return Resp({})
        return Resp({})

AG.get_skill_level = lambda *a, **k: 1
AG.calculate_failure_rate = lambda *a, **k: 0.0
AG.increment_skill = lambda *a, **k: 2
AG.get_model_decision = lambda prompt, mid: {"response": "COMMIT", "tokens_used": 0}
AG.parse_commit_response = lambda resp: (True, "ok")
AG.build_build_prompt = lambda *a, **k: "build-exec"
CK.get_current_day = lambda: 3
AG.Agent._apply_action_tension = lambda self, at, s: 0
AG.Agent._record_decision_log = lambda self, aid: None

def M(mid, group, x, y, e=15000, sx=None, sy=None, st="none"):
    return {"model_id": mid, "experiment_group": group, "current_energy": e, "max_energy": 30000,
            "pos_x": x, "pos_y": y, "shelter_status": st, "shelter_x": sx, "shelter_y": sy, "spatial_note": ""}
def world(models, nodes=None, inv=None):
    return {"models": {m["model_id"]: m for m in models}, "nodes": nodes or [], "inv": inv or {}, "actions": []}
def bind(w): AG.requests = FakeReq(w); return w
def last(w, t=None):
    for a in reversed(w["actions"]):
        if t is None or a["action_type"] == t: return a
    return None
def P(w, mid): return (w["models"][mid]["pos_x"], w["models"][mid]["pos_y"])
def SH(w, mid): return (w["models"][mid]["shelter_x"], w["models"][mid]["shelter_y"])

APPLE = {"node_id": 1, "node_type": "apple", "experiment_group": "flat_C1", "current_yield": 6,
         "max_yield_per_day": 6, "is_built": True, "pos_x": 300.0, "pos_y": 400.0}

# --- DISPLACEMENT: coord move onto an occupied non-node point --------------
print("\n  graceful displacement (coord move)")
w = bind(world([M("flat_C1_01", "flat_C1", 0.0, 0.0), M("flat_C1_02", "flat_C1", 100.0, 0.0)]))
b = AG.Agent("flat_C1_01", "flat_C1")
b._handle_move({"action_type": "move", "target": "100,0"}, 500)
land = P(w, "flat_C1_01")
check("move to a coord occupied by another agent -> displaced to nearest free point toward actor",
      last(w, "move")["succeeded"] and land == (99.0, 0.0), f"landed {land}")
check("  ...pays for ACTUAL distance traveled (99*3=297), not intended (100*3=300)",
      w["models"]["flat_C1_01"]["current_energy"] == 15000 - 500 - move_cost(99),
      f"energy {w['models']['flat_C1_01']['current_energy']} = 15000-500-{move_cost(99)}")
check("  ...agent is INFORMED via spatial_note",
      "intended" in w["models"]["flat_C1_01"]["spatial_note"] and "stopped at" in w["models"]["flat_C1_01"]["spatial_note"],
      w["models"]["flat_C1_01"]["spatial_note"])

w = bind(world([M("flat_C1_01", "flat_C1", 0.0, 0.0)]))
b = AG.Agent("flat_C1_01", "flat_C1")
b._handle_move({"action_type": "move", "target": "100,0"}, 500)   # free coord
check("move to a FREE coord -> lands exactly there, no note", P(w, "flat_C1_01") == (100.0, 0.0)
      and w["models"]["flat_C1_01"]["spatial_note"] == "")

# --- NODE still stacks (no displacement) -----------------------------------
w = bind(world([M("flat_C1_01", "flat_C1", 0.0, 0.0), M("flat_C1_02", "flat_C1", 300.0, 400.0)], [dict(APPLE)]))
b = AG.Agent("flat_C1_01", "flat_C1")
b._handle_move({"action_type": "move", "target": "apple"}, 500)
check("move to an OCCUPIED NODE -> lands ON it (co-harvest stack, no displacement)",
      P(w, "flat_C1_01") == (300.0, 400.0) and w["models"]["flat_C1_01"]["spatial_note"] == "")

# --- BUILD claims the current position --------------------------------------
print("\n  positional shelter = territory")
w = bind(world([M("flat_C1_01", "flat_C1", 150.0, 250.0)], inv={"flat_C1_01": {"wood": 20, "stone": 20}}))
a = AG.Agent("flat_C1_01", "flat_C1")
a._handle_build({"action_type": "build", "target": "basic"}, 300)
check("build basic shelter -> CLAIMS the agent's current point (150,250)",
      w["models"]["flat_C1_01"]["shelter_status"] == "basic" and SH(w, "flat_C1_01") == (150.0, 250.0),
      f"shelter@{SH(w,'flat_C1_01')}")

# --- SHELTER OWNER-EXCEPTION -------------------------------------------------
# owner shelter at (200,0); OWNER can land exactly on it; a DIFFERENT agent is displaced.
w = bind(world([M("flat_C1_01", "flat_C1", 0.0, 0.0, sx=200.0, sy=0.0, st="basic"),
                M("flat_C1_02", "flat_C1", 400.0, 0.0)]))
owner = AG.Agent("flat_C1_01", "flat_C1")
owner._handle_move({"action_type": "move", "target": "200,0"}, 500)
check("OWNER moves to its OWN shelter point -> lands EXACTLY on it (home)",
      P(w, "flat_C1_01") == (200.0, 0.0) and last(w, "move")["succeeded"])
other = AG.Agent("flat_C1_02", "flat_C1")
other._handle_move({"action_type": "move", "target": "200,0"}, 500)
check("a DIFFERENT agent moves to that shelter point -> DISPLACED to nearest free point + informed",
      P(w, "flat_C1_02") == (201.0, 0.0) and "intended" in w["models"]["flat_C1_02"]["spatial_note"],
      f"landed {P(w,'flat_C1_02')}")

# --- REST BONUS is POSITIONAL ------------------------------------------------
w = bind(world([M("flat_C1_01", "flat_C1", 200.0, 0.0, sx=200.0, sy=0.0, st="basic")]))
a = AG.Agent("flat_C1_01", "flat_C1")
e0 = w["models"]["flat_C1_01"]["current_energy"]
a._handle_rest({"action_type": "rest", "target": None}, 0)   # AT its shelter point
check("owner rests AT its shelter point -> gets YIELD_REST_SHELTER (4000)",
      w["models"]["flat_C1_01"]["current_energy"] - e0 == YIELD_REST_SHELTER)
w = bind(world([M("flat_C1_01", "flat_C1", 500.0, 500.0, sx=200.0, sy=0.0, st="basic")]))  # away from shelter
a = AG.Agent("flat_C1_01", "flat_C1")
e0 = w["models"]["flat_C1_01"]["current_energy"]
a._handle_rest({"action_type": "rest", "target": None}, 0)
check("owner rests ELSEWHERE -> only YIELD_REST (2000), NOT the shelter bonus (positional)",
      w["models"]["flat_C1_01"]["current_energy"] - e0 == YIELD_REST)

# --- CLAIM LIFETIME ----------------------------------------------------------
w = bind(world([M("flat_C1_01", "flat_C1", 0.0, 0.0, sx=200.0, sy=0.0, st="basic"),
                M("flat_C1_02", "flat_C1", 400.0, 0.0)]))
d = AG.Agent("flat_C1_02", "flat_C1")
d._handle_move({"action_type": "move", "target": "200,0"}, 500)
check("while shelter MAINTAINED -> its point blocks others (they get displaced)",
      P(w, "flat_C1_02") == (201.0, 0.0))
# break the shelter (maintenance lapse -> status 'none' releases the claim)
FakeReq(w).post("http://x:5000/models/flat_C1_01/shelter", json={"shelter_status": "none"})
check("  shelter breaks -> claim DISSOLVES (shelter_x/y cleared, point freed)",
      SH(w, "flat_C1_01") == (None, None))
w["models"]["flat_C1_02"].update(pos_x=400.0, pos_y=0.0, spatial_note="")
d._handle_move({"action_type": "move", "target": "200,0"}, 500)
check("  after the claim ends -> another agent CAN land exactly on the freed point",
      P(w, "flat_C1_02") == (200.0, 0.0))

# --- DENY HOOK wired in the handler (force a low threshold) ------------------
print("\n  deferred deny-threshold hook")
_orig = AG.movement.resolve_landing
AG.movement.resolve_landing = lambda *a, **k: _orig(*a, **{**k, "deny_threshold": 0.5})
w = bind(world([M("flat_C1_01", "flat_C1", 0.0, 0.0), M("flat_C1_02", "flat_C1", 100.0, 0.0)]))
b = AG.Agent("flat_C1_01", "flat_C1")
b._handle_move({"action_type": "move", "target": "100,0"}, 500)   # displacement 1 > 0.5 -> deny
check("with the threshold lowered, a large-enough displacement -> move DENIED",
      last(w, "move")["succeeded"] is False)
check("  ...denied move does NOT change position, and informs 'decide again'",
      P(w, "flat_C1_01") == (0.0, 0.0) and "decide again" in w["models"]["flat_C1_01"]["spatial_note"])
AG.movement.resolve_landing = _orig   # restore (hook is inert at the real default)

# --- SEALED GROUPS -----------------------------------------------------------
print("\n  sealed groups")
w = bind(world([M("flat_C1_01", "flat_C1", 0.0, 0.0),
                M("flat_C2_01", "flat_C2", 999.0, 999.0, sx=200.0, sy=0.0, st="basic")]))  # C2 shelter at (200,0)
b = AG.Agent("flat_C1_01", "flat_C1")
b._handle_move({"action_type": "move", "target": "200,0"}, 500)
check("a cross-group shelter/agent does NOT obstruct (lands exactly on (200,0))",
      P(w, "flat_C1_01") == (200.0, 0.0))

print("\n" + "=" * 72)
passed = sum(_checks)
print(f"RESULT: {passed}/{len(_checks)} checks passed")
print("=" * 72)
import sys; sys.exit(0 if passed == len(_checks) else 1)
