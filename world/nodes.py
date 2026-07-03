import requests

from constants import BUILDABLE_NODE_TYPES, NODE_MAX_YIELDS

BASE_URL = "http://127.0.0.1:5000"

# Every experiment group gets exactly one node of each type, created in this
# exact order. models/action_parser._node_id_hint resolves bare node ids by
# assuming this 9-type cycle, so the order must not change.
NODE_TYPE_ORDER = [
    "apple", "potato", "grain", "hunting", "river",
    "well", "forest", "rock", "ore",
]


def initialize_nodes():
    """
    Create one sealed world per experiment group: 9 nodes per group
    (one of each type), 36 nodes total across the 4 Run 4 groups.

    Creation order is deterministic: all 9 nodes for the first group
    (in NODE_TYPE_ORDER), then the next, in get_all_group_ids() order
    (tunnel_C1, tunnel_C2, flat_C1, flat_C2).
    """
    from groups.group_config import get_all_group_ids

    created = []
    for group_id in get_all_group_ids():
        for node_type in NODE_TYPE_ORDER:
            body = {
                "node_type": node_type,
                "max_yield_per_day": NODE_MAX_YIELDS[node_type],
                "experiment_group": group_id,
            }
            if node_type in BUILDABLE_NODE_TYPES:
                body["initial_yield"] = 0
            resp = requests.post(f"{BASE_URL}/nodes", json=body, timeout=10)
            resp.raise_for_status()
            created.append(resp.json())
    return created
