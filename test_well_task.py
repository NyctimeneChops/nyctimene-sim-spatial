"""Pure offline tests for agent-placed wells + no-build-on-node - NO GPU/DB/network.
Covers mechanics.on_any_node, action_parser._node_id_hint (8-type cycle, no 'well'),
score_generation.spawn_circumstance (spawn water distance to rivers only, wells ignored),
and world.nodes.NODE_TYPE_ORDER (no 'well', 8 types)."""
import sys

_checks = []
def check(name, ok, detail=""):
    _checks.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

print("=" * 60)
print("WELL TASK - pure offline logic")
print("=" * 60)

# [M] mechanics.on_any_node : build-only on-node predicate, reuses AT_NODE_EPSILON
from constants import AT_NODE_EPSILON
from mechanics.movement import on_any_node
pts = [(100.0, 200.0), (400.0, 600.0)]
print("\n[M] mechanics.on_any_node")
check("exactly on a node point -> True", on_any_node(100.0, 200.0, pts) is True)
check("within epsilon of a node point -> True",
      on_any_node(100.0 + AT_NODE_EPSILON / 2.0, 200.0, pts) is True)
check("off every node point -> False", on_any_node(250.0, 250.0, pts) is False)
check("just beyond epsilon -> False",
      on_any_node(100.0 + AT_NODE_EPSILON * 10.0, 200.0, pts) is False)
check("empty node list -> False", on_any_node(100.0, 200.0, []) is False)

# [P] action_parser._node_id_hint : 8-type cycle, never resolves to 'well'
from models.action_parser import _node_id_hint
EXPECT = ["apple", "potato", "grain", "hunting", "river", "forest", "rock", "ore"]
print("\n[P] action_parser._node_id_hint (8-type cycle)")
got = [_node_id_hint(str(i)) for i in range(1, 9)]
check("ids 1..8 map to the 8-type order", got == EXPECT, str(got))
check("id 9 wraps to 'apple' (modulo 8)", _node_id_hint("9") == "apple")
check("id 16 wraps to 'ore'", _node_id_hint("16") == "ore")
check("no id 1..64 maps to 'well' (wells are agent-placed, not in the cycle)",
      all(_node_id_hint(str(i)) != "well" for i in range(1, 65)))

# [S] scorer spawn_circumstance : water distance to RIVERS only, wells ignored
from scoring.score_generation import spawn_circumstance, WATER_NODES
print("\n[S] scorer spawn_circumstance ignores wells for spawn water")
check("WATER_NODES is rivers only", WATER_NODES == {"river"}, str(WATER_NODES))
# a CLOSE well (dist 1, must be ignored) + a FAR river (dist 300 = the real spawn water)
group_nodes = [("apple", 100.0, 100.0),
               ("well",  101.0, 100.0),
               ("river", 100.0, 400.0)]
circ = spawn_circumstance([100.0, 100.0], group_nodes)
check("d_water uses the far river, not the closer well",
      circ is not None and abs(circ["nearest_water_dist"] - 300.0) < 1e-6,
      f"nearest_water_dist={circ and circ['nearest_water_dist']}")

# [SEED] world.nodes.NODE_TYPE_ORDER : no 'well', 8 types
from world.nodes import NODE_TYPE_ORDER
print("\n[SEED] world.nodes.NODE_TYPE_ORDER")
check("NODE_TYPE_ORDER has 8 types", len(NODE_TYPE_ORDER) == 8, str(NODE_TYPE_ORDER))
check("NODE_TYPE_ORDER has no 'well'", "well" not in NODE_TYPE_ORDER)

print("\n" + "=" * 60)
passed = sum(_checks)
print(f"RESULT: {passed}/{len(_checks)} checks passed")
print("=" * 60)
sys.exit(0 if passed == len(_checks) else 1)
