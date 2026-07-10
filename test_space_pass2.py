"""
Deterministic space-milestone PASS 2 test (spatial PERCEPTION / prompt rendering) -
NO GPU/DB/network. The data layer (prompt_builder._get + world.clock + group_config)
is stubbed with synthetic agent/node data at KNOWN coordinates, so build_prompt renders
a real full prompt that we can hand-check.

Verifies (design doc sections 1-2, pass 2 scope):
  * the agent's own position is shown (status, core).
  * each node shows the correct Euclidean distance + move cost from the agent's CURRENT
    position (hand-checked against pass-1 geometry).
  * distances are DYNAMIC: move the agent, re-render, distances update.
  * "move" is in AVAILABLE ACTIONS with its position-dependent cost.
  * HOW THE WORLD WORKS states the travel-to-node requirement (factual).
  * the spatial block's compression treatment (position core; per-node distances ride
    the nodes section / food-water exit) + the token cost it adds.
  * arrival-perception: a node UNDER the agent renders "you do not need to move or travel
    to reach this node" (at_node predicate) in place of the distance/move-cost row, and it
    rides the food/water exit (present in both arms exactly when the food/water node is at
    the agent's feet).
  * NO enforcement was built (harvest handler still position-agnostic).
"""
import json
import models.prompt_builder as PB
import world.clock as CLOCK
import groups.group_config as GC

_checks = []
def check(name, ok, detail=""):
    _checks.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

# ---- synthetic world (known coordinates) --------------------------------------
AGENT = "test_C1_01"

def make_model(group, px, py, tension, sources):
    return {"model_id": AGENT, "experiment_group": group, "current_energy": 15000,
            "pos_x": px, "pos_y": py, "shelter_status": "none",
            "attention_state": "free", "is_sleeping": False,
            "tension": tension, "tension_sources": sources, "inventory": {}}

def make_nodes(group):
    return [
        {"node_id": 1, "node_type": "apple",  "experiment_group": group, "current_yield": 6,
         "max_yield_per_day": 6,  "is_built": True, "pos_x": 400.0, "pos_y": 600.0},
        {"node_id": 2, "node_type": "potato", "experiment_group": group, "current_yield": 6,
         "max_yield_per_day": 6,  "is_built": True, "pos_x": 103.0, "pos_y": 204.0},
        {"node_id": 5, "node_type": "river",  "experiment_group": group, "current_yield": 12,
         "max_yield_per_day": 12, "is_built": True, "pos_x": 100.0, "pos_y": 700.0},
        {"node_id": 8, "node_type": "rock",   "experiment_group": group, "current_yield": 4,
         "max_yield_per_day": 6,  "is_built": True, "pos_x": 100.0, "pos_y": 200.0},
    ]

_WORLD = {"model": None, "nodes": None}

def fake_get(path, params=None):
    if path.endswith("/skills"):                    return {}
    if path.startswith("/models/"):                 return _WORLD["model"]     # /models/<id>
    if path.endswith("/summary"):                   return {}
    if path.startswith("/actions/"):                return []
    if path.startswith("/decision_log/recent/"):    return []
    if path == "/nodes":                            return _WORLD["nodes"]
    if path == "/nodes/activity":                   return {}
    if path == "/messages/broadcast":               return []
    if path == "/threads":                          return []
    if path.startswith("/transactions/"):           return []
    if path.startswith("/messages/direct/"):        return []
    if path.startswith("/survival/"):               return []
    return {}

# stub the whole data layer
PB._get = fake_get
CLOCK.get_current_day = lambda: 3
CLOCK.get_elapsed_minutes = lambda: 5.0
GC.get_group_config = lambda g: {"tunneling_enabled": not g.startswith("flat")}

def render(group, px, py, tension=0, sources="{}"):
    _WORLD["model"] = make_model(group, px, py, tension, sources)
    _WORLD["nodes"] = make_nodes(group)
    return PB.build_prompt(AGENT)


def line_with(prompt, needle):
    return next((l for l in prompt.splitlines() if needle in l), "")


# expected geometry from pass 1 (hand-checked): agent (100,200)
#   apple(400,600): dx300 dy400 -> 500.0, cost 1500
#   potato(103,204): dx3 dy4  -> 5.0,   cost 15
#   river(100,700):  dx0 dy500 -> 500.0, cost 1500
#   rock(100,200):   0.0, cost 0
print("=" * 72)
print("SPACE MILESTONE PASS 2 - spatial perception (prompt rendering)")
print("=" * 72)

# ---------------------------------------------------- [A] full CALM render
p = render("tunnel_C1", 100.0, 200.0, tension=0, sources="{}")
print("\n########## SAMPLE PROMPT - agent at (100, 200), CALM ##########")
print(p)

print("\n[A] agent position + per-node distance/cost (hand-checked)")
check("agent position shown in status", "Position:           (100.0, 200.0)" in p,
      line_with(p, "Position:").strip())
NODE_EXPECT = [("apple", "distance 500.0 / move cost 1500"),
               ("potato", "distance 5.0 / move cost 15"),
               ("river", "distance 500.0 / move cost 1500"),
               ("rock", "you do not need to move or travel to reach this node")]
for nt, expect in NODE_EXPECT:
    row = line_with(p, f"] {nt:<10}")
    print(f"    {nt:<7}: {row.strip()}")
    check(f"{nt} node shows '{expect}'", expect in row)
check("'move' is in AVAILABLE ACTIONS with a position-dependent cost",
      "move" in line_with(p, "move     costs energy"),
      line_with(p, "move     costs energy").strip())
check("HOW THE WORLD WORKS states the travel-to-node requirement",
      "MOVE to it first" in p and "SPACE:" in p)

# ---------------------------------------------------- [A2] arrival-perception
# rock(100,200) sits under the agent(100,200): its line must state arrival (perception),
# with the distance/move-cost suffix REPLACED (not appended). potato is not at-node.
print("\n[A2] arrival-perception: node under the agent shows the arrival note, not a distance")
rock_row = line_with(p, "] rock")
print(f"    at-node (rock): {rock_row.strip()}")
check("at-node line shows the arrival note",
      "you do not need to move or travel to reach this node" in rock_row, rock_row.strip())
check("at-node line does NOT contain 'distance' (suffix replaced, not appended)",
      "distance" not in rock_row)
check("at-node line does NOT contain 'move cost' (suffix replaced, not appended)",
      "move cost" not in rock_row)
potato_row = line_with(p, "] potato")
check("a non-at-node node still shows 'distance ... / move cost ...'",
      "distance" in potato_row and "move cost" in potato_row, potato_row.strip())

# ---------------------------------------------------- [B] dynamic after a move
p2 = render("tunnel_C1", 400.0, 600.0, tension=0, sources="{}")   # moved to the apple
print("\n[B] DYNAMIC: same agent moved to (400, 600), distances recomputed")
# from (400,600): apple 0/0 ; river dx300 dy100 -> 316.2 cost 949 ; rock 500/1500 ; potato 495/1485
DYN_EXPECT = [("apple", "you do not need to move or travel to reach this node"),
              ("river", "distance 316.2 / move cost 949"),
              ("rock", "distance 500.0 / move cost 1500"),
              ("potato", "distance 495.0 / move cost 1485")]
check("agent position updated in status", "Position:           (400.0, 600.0)" in p2)
for nt, expect in DYN_EXPECT:
    row = line_with(p2, f"] {nt:<10}")
    print(f"    {nt:<7}: {row.strip()}")
    check(f"[moved] {nt} shows '{expect}'", expect in row)
check("distances CHANGED after the move (dynamic, not static)",
      line_with(p, "] apple") != line_with(p2, "] apple"))

# ---------------------------------------------------- [C] compression / tension
sources_hunger = json.dumps({"hunger": 100, "thirst": 0, "failures": 0, "shelter": 0, "messages": 0})
from mechanics.tension import band_for_total
band = band_for_total(100)
print(f"\n[C] compression treatment (tension=100 -> band {band}; dominant=hunger)")
p_tunnel = render("tunnel_C1", 100.0, 200.0, tension=100, sources=sources_hunger)
p_flat   = render("flat_C1",   100.0, 200.0, tension=100, sources=sources_hunger)
# position is CORE -> shown in both arms even at max tension
check("position shown for TUNNEL-arm agent at max tension (core)",
      "Position:           (100.0, 200.0)" in p_tunnel)
check("position shown for FLAT-arm agent at max tension (core)",
      "Position:           (100.0, 200.0)" in p_flat)
# survival-critical distances ride the food/water EXIT: a hunger-tunnel agent still
# sees the distance to FOOD nodes (the exit), so it can decide where to travel to eat.
check("hunger-tunnel agent still sees FOOD-node distances via the exit",
      "distance" in line_with(p_tunnel, "] apple"),
      "apple line: " + line_with(p_tunnel, "] apple").strip())
# flat arm always shows the full node list with distances
check("flat arm shows full node list with distances at max tension",
      "distance 500.0 / move cost 1500" in p_flat)
print(f"    tunnel-arm prompt chars: {len(p_tunnel)}   flat-arm prompt chars: {len(p_flat)}")

# ---------------------------------------------------- [C2] arrival note rides the exit
# agent STANDING ON the apple food node (400,600) at max tension. Under hunger dominance
# food is the exit -> the apple line renders (with the arrival note). Under thirst
# dominance food is NOT the exit -> the apple per-node line is compressed away, so the
# arrival note does not appear. This proves the note rides the exit and never leaks as an
# always-shown element.
sources_thirst = json.dumps({"hunger": 0, "thirst": 100, "failures": 0, "shelter": 0, "messages": 0})
print(f"\n[C2] arrival note rides the food/water exit (agent ON the apple at (400,600), tension=100)")
p_food_exit = render("tunnel_C1", 400.0, 600.0, tension=100, sources=sources_hunger)  # hunger -> food exit
p_thirst    = render("tunnel_C1", 400.0, 600.0, tension=100, sources=sources_thirst)  # thirst -> food compressed
apple_food = line_with(p_food_exit, "] apple")
print(f"    hunger-dominant apple line: {apple_food.strip()}")
check("hunger-dominant: apple (food EXIT) line shows the arrival note",
      "you do not need to move or travel to reach this node" in apple_food, apple_food.strip())
check("thirst-dominant: apple (food, NON-exit) compressed away -> arrival note NOT present",
      "you do not need to move or travel to reach this node" not in p_thirst)

# ---------------------------------------------------- [D] token cost of spatial
print("\n[D] token cost the spatial block adds (chars = the project's prompt_length unit)")
spatial_chars = 0
for l in p.splitlines():          # p = the CALM tunnel render at (100,200)
    if "Position:" in l:                      spatial_chars += len(l)
    if "| distance" in l:                     spatial_chars += len(l.split("|", 1)[1]) + 1  # the suffix only
    if l.strip().startswith("SPACE:"):        spatial_chars += len(l)
    if "move     costs energy" in l:          spatial_chars += len(l)
print(f"    full CALM prompt: {len(p)} chars")
print(f"    spatial block adds ~{spatial_chars} chars (~{spatial_chars // 4} tokens approx) "
      f"across 4 test nodes; ~{spatial_chars + 5 * 30} chars with the full 9 nodes")
check("spatial block is a small fraction of the prompt (does not distort the tunnel)",
      spatial_chars < 0.20 * len(p), f"{spatial_chars} chars < 20% of {len(p)}")

# ---------------------------------------------------- [E] no enforcement built
print("\n[E] NO enforcement (harvest still position-agnostic; pass 3 will change this)")
import inspect, models.agent as AG
harvest_src = inspect.getsource(AG.Agent._handle_harvest)
no_pos_gate = not any(k in harvest_src for k in ("pos_x", "distance(", "_distance", "at the node", "move_cost"))
check("_handle_harvest has NO position/distance gate (enforcement is pass 3)", no_pos_gate)
check("harvest handler unchanged from pass 1 (position-agnostic)",
      "COST_HARVEST" not in harvest_src or "_charge_costed" in harvest_src)

print("\n" + "=" * 72)
passed = sum(_checks)
print(f"RESULT: {passed}/{len(_checks)} checks passed")
print("=" * 72)
import sys; sys.exit(0 if passed == len(_checks) else 1)
