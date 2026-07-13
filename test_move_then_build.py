"""
MOVE-THEN-BUILD verification + prompt legibility - NO GPU/DB/network.

PART 1 (mechanical): one action per tick, so move-then-build is a TWO-TICK sequence.
  Drive tick 1 (move) then tick 2 (build) against a fake world and confirm the shelter is
  claimed at the moved-to point, the position persisted across ticks, and nothing blocks
  build-after-move (no stale read, no cooldown/guard).

PART 1b (ARRIVAL FIX v2): a move whose resolved target is the agent's CURRENT position is a
  FAILED no-op (position unchanged, no skill XP, spatial_note set); legit travel to a
  DIFFERENT node still SUCCEEDS; and a build denied on a resource node sets spatial_note.

PART 2 (comprehension): render a prompt and confirm the shelter rule states CONSTRAINTS only
  (built at CURRENT position, positional rest bonus) with NO move-first procedure.
"""
import models.agent as AG
import world.clock as CK

_checks = []
def check(name, ok, detail=""):
    _checks.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

print("=" * 72)
print("MOVE-THEN-BUILD verification (two-tick sequence) + prompt legibility")
print("=" * 72)

# ---------------------------------------------------- fake world (Part 1)
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
        p = url.split("5000", 1)[1]; w = self.w; b = json or {}; mid = p.split("/")[2] if p.startswith("/models/") else None
        if p.endswith("/energy/adjust"):
            m = w["models"][mid]; m["current_energy"] = max(0, min(m["current_energy"] + b["delta"], m["max_energy"])); return Resp({"energy": m["current_energy"]})
        if p.endswith("/position"):
            m = w["models"][mid]; m["pos_x"], m["pos_y"], m["spatial_note"] = b["pos_x"], b["pos_y"], b.get("note", ""); return Resp({"pos_x": m["pos_x"], "pos_y": m["pos_y"]})
        if p.endswith("/shelter"):
            m = w["models"][mid]; st = b["shelter_status"]
            if st == "none": m["shelter_status"], m["shelter_x"], m["shelter_y"] = "none", None, None
            elif "pos_x" in b: m["shelter_status"], m["shelter_x"], m["shelter_y"] = st, b["pos_x"], b["pos_y"]
            else: m["shelter_status"] = st
            return Resp({"shelter_status": m["shelter_status"]})
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
AG.build_build_prompt = lambda *a, **k: "exec"
CK.get_current_day = lambda: 3
AG.Agent._apply_action_tension = lambda self, at, s: 0
AG.Agent._record_decision_log = lambda self, aid: None

RIVER = {"node_id": 5, "node_type": "river", "experiment_group": "flat_C1", "current_yield": 12,
         "max_yield_per_day": 12, "is_built": True, "pos_x": 700.0, "pos_y": 100.0}

def fresh():
    w = {"models": {"flat_C1_01": {"model_id": "flat_C1_01", "experiment_group": "flat_C1",
             "current_energy": 15000, "max_energy": 30000, "pos_x": 0.0, "pos_y": 0.0,
             "shelter_status": "none", "shelter_x": None, "shelter_y": None, "spatial_note": ""}},
         "nodes": [dict(RIVER)], "inv": {"flat_C1_01": {"wood": 20, "stone": 20}}, "actions": []}
    AG.requests = FakeReq(w); return w

print("\n[PART 1] one action per tick -> move-then-build is a TWO-TICK sequence")

# ---- move to a coordinate, then build (two ticks) --------------------------
w = fresh()
a = AG.Agent("flat_C1_01", "flat_C1")
start = (w["models"]["flat_C1_01"]["pos_x"], w["models"]["flat_C1_01"]["pos_y"])
# TICK 1: move
a._handle_move({"action_type": "move", "target": "300,400"}, 500)
after_move = (w["models"]["flat_C1_01"]["pos_x"], w["models"]["flat_C1_01"]["pos_y"])
check("tick 1: agent at (0,0) moves to (300,400) -> position UPDATES to (300,400)",
      start == (0.0, 0.0) and after_move == (300.0, 400.0))
# TICK 2: build (a fresh handler call = the next cycle; position must persist + be read fresh)
a._handle_build({"action_type": "build", "target": "basic"}, 300)
shelter = (w["models"]["flat_C1_01"]["shelter_x"], w["models"]["flat_C1_01"]["shelter_y"])
check("tick 2: build claims the shelter at the MOVED-TO point (300,400), not the start",
      shelter == (300.0, 400.0) and w["models"]["flat_C1_01"]["shelter_status"] == "basic",
      f"shelter@{shelter}")
check("  ...position PERSISTED across ticks (build read the fresh moved-to position)",
      after_move == shelter)
check("  ...nothing blocked build-after-move (no cooldown / stale-state guard)",
      w["actions"][-1]["action_type"] == "build" and w["actions"][-1]["succeeded"] is True)

# ---- no-build-on-node: standing ON a resource node, a shelter build is DENIED ----
w = fresh()
a = AG.Agent("flat_C1_01", "flat_C1")
a._handle_move({"action_type": "move", "target": "river"}, 500)     # tick 1: move onto the river node
moved = (w["models"]["flat_C1_01"]["pos_x"], w["models"]["flat_C1_01"]["pos_y"])
a._handle_build({"action_type": "build", "target": "basic"}, 300)   # tick 2: build on the node -> DENIED
shelter = (w["models"]["flat_C1_01"]["shelter_x"], w["models"]["flat_C1_01"]["shelter_y"])
last = w["actions"][-1]
check("on a resource node (river@700,100), build shelter is DENIED (no claim, failed build)",
      moved == (700.0, 100.0) and shelter == (None, None)
      and last["action_type"] == "build" and last["succeeded"] is False,
      f"moved {moved}, shelter {shelter}, last {last['action_type']}/{last['succeeded']}")
check("  ...build denial sets spatial_note with the reason (agent sees it next tick)",
      w["models"]["flat_C1_01"]["spatial_note"]
      == "FAILED - you cannot build on a resource node. Move off the node first.",
      w["models"]["flat_C1_01"]["spatial_note"])

# ---- control: build WITHOUT moving claims the start point (proves it's 'here') ----
w = fresh()
a = AG.Agent("flat_C1_01", "flat_C1")
a._handle_build({"action_type": "build", "target": "basic"}, 300)   # no move first
check("build WITHOUT moving -> shelter claimed at the agent's start point (0,0) ('here')",
      (w["models"]["flat_C1_01"]["shelter_x"], w["models"]["flat_C1_01"]["shelter_y"]) == (0.0, 0.0))

print("\n[PART 1b] ARRIVAL FIX v2: a move to where you ALREADY are is a FAILED no-op")

# ---- legit node travel still SUCCEEDS, then a repeat onto the same node FAILS ----
w = fresh()
a = AG.Agent("flat_C1_01", "flat_C1")
a._handle_move({"action_type": "move", "target": "river"}, 500)     # (0,0) -> river (700,100)
pos1 = (w["models"]["flat_C1_01"]["pos_x"], w["models"]["flat_C1_01"]["pos_y"])
first = w["actions"][-1]
check("move to a DIFFERENT node (river@700,100) still SUCCEEDS (legit travel not broken)",
      pos1 == (700.0, 100.0) and first["action_type"] == "move" and first["succeeded"] is True,
      f"pos {pos1}, {first['action_type']}/{first['succeeded']}")
a._handle_move({"action_type": "move", "target": "river"}, 500)     # already on river -> no-op
pos2 = (w["models"]["flat_C1_01"]["pos_x"], w["models"]["flat_C1_01"]["pos_y"])
note = w["models"]["flat_C1_01"]["spatial_note"]
last = w["actions"][-1]
check("moving onto the node you already occupy is recorded FAILED (no silent success)",
      last["action_type"] == "move" and last["succeeded"] is False)
check("  ...position UNCHANGED (still on river@700,100, no teleport)", pos2 == (700.0, 100.0))
check("  ...move grants NO skill XP (skill_before == skill_after)",
      last["skill_level_before"] == last["skill_level_after"])
check("  ...spatial_note names the node and says no movement occurred",
      "FAILED" in note and "physically present at the river node" in note
      and "no movement occurred" in note, note)

# ---- a raw-coordinate move to the agent's CURRENT point also FAILS ----
w = fresh()
a = AG.Agent("flat_C1_01", "flat_C1")   # starts at (0,0)
a._handle_move({"action_type": "move", "target": "0,0"}, 500)       # move to where you already are
note = w["models"]["flat_C1_01"]["spatial_note"]
last = w["actions"][-1]
check("move to the agent's CURRENT coordinate (0,0) is recorded FAILED",
      last["action_type"] == "move" and last["succeeded"] is False)
check("  ...position UNCHANGED at (0,0)",
      (w["models"]["flat_C1_01"]["pos_x"], w["models"]["flat_C1_01"]["pos_y"]) == (0.0, 0.0))
check("  ...spatial_note uses the raw-point wording ('at that point'), not a node name",
      "FAILED" in note and "at that point" in note and "no movement occurred" in note, note)

# ---------------------------------------------------- PART 2: prompt legibility
print("\n[PART 2] prompt legibility (move -> build relationship)")
import models.prompt_builder as PB
import groups.group_config as GC

def make_model(px, py):
    return {"model_id": "flat_C1_01", "experiment_group": "flat_C1", "current_energy": 15000,
            "pos_x": px, "pos_y": py, "shelter_status": "none", "shelter_x": None, "shelter_y": None,
            "attention_state": "free", "is_sleeping": False, "tension": 0, "tension_sources": "{}",
            "inventory": {}, "spatial_note": ""}
NODES = [dict(RIVER), {"node_id": 1, "node_type": "apple", "experiment_group": "flat_C1",
         "current_yield": 6, "max_yield_per_day": 6, "is_built": True, "pos_x": 300.0, "pos_y": 400.0}]

def fake_get(path, params=None):
    if path.endswith("/skills"): return {}
    if path.startswith("/models/"): return make_model(0.0, 0.0)
    if path.endswith("/summary"): return {}
    if path.startswith("/actions/"): return []
    if path.startswith("/decision_log/recent/"): return []
    if path == "/nodes": return NODES
    if path == "/nodes/activity": return {}
    if path in ("/messages/broadcast", "/threads"): return []
    if path.startswith("/transactions/") or path.startswith("/messages/direct/") or path.startswith("/survival/"): return []
    return {}
PB._get = fake_get
CK.get_current_day = lambda: 3
CK.get_elapsed_minutes = lambda: 5.0
GC.get_group_config = lambda g: {"tunneling_enabled": True}

prompt = PB.build_prompt("flat_C1_01")
shelter_line = next((l for l in prompt.splitlines() if l.strip().startswith("SHELTER:")), "")
print("\n  HOW-THE-WORLD-WORKS shelter rule (rendered):")
for seg in [shelter_line[i:i+88] for i in range(0, len(shelter_line), 88)]:
    print("   " + seg.strip())
check("prompt states shelter is built at CURRENT position", "built at your CURRENT position" in prompt)
# ARRIVAL FIX v2: the prompt states CONSTRAINTS/facts only -- it must NOT teach a move-first
# PROCEDURE. The old 'move -> build' / 'move -> harvest' teaching arrows are gone.
check("prompt no longer teaches a move-first procedure (no 'move -> build' / 'move -> harvest')",
      "move -> build" not in prompt and "move -> harvest" not in prompt)
check("prompt states physical presence as a CONSTRAINT (not an instruction to move)",
      "You must be physically present at a" in prompt)
check("prompt states the rest bonus is positional (at your own shelter point)",
      "while you are AT your own shelter point" in prompt)
# factual, not a command: no imperative 'you should/must build' directive
lc = shelter_line.lower()
check("reads as factual mechanics, not an instruction to build",
      "you should build" not in lc and "you must build" not in lc and "build a shelter now" not in lc)

print("\n" + "=" * 72)
passed = sum(_checks)
print(f"RESULT: {passed}/{len(_checks)} checks passed")
print("=" * 72)
import sys; sys.exit(0 if passed == len(_checks) else 1)
