import requests

from constants import NODE_BASE_FAILURE_RATES

BASE_URL = "http://127.0.0.1:5000"

# Completions required to advance one level within each tier.
_TIER_COST = [
    (50, 1),   # levels 1–49  → 1 completion per level
    (75, 2),   # levels 50–74 → 2 completions per level
    (99, 3),   # levels 75–98 → 3 completions per level
]


def _cost_for_level(level):
    for ceiling, cost in _TIER_COST:
        if level < ceiling:
            return cost
    return None  # already at 99


def _completions_to_reach(level):
    """Total successful completions needed to have reached `level` from level 1."""
    total = 0
    for l in range(1, level):
        total += _cost_for_level(l)
    return total


def get_skill_level(model_id, action_type):
    resp = requests.get(f"{BASE_URL}/models/{model_id}/skills", timeout=10)
    resp.raise_for_status()
    return resp.json().get(action_type, 1)


def increment_skill(model_id, action_type):
    """
    Called after a successful action. Counts total successful completions for
    this action type, derives the level those completions map to, and writes
    a new skill level to the ledger if a level-up has occurred.

    Posts a skill_threshold_reached event when the new level is 10, 40, or 75.
    Returns the current (possibly unchanged) skill level.
    """
    current_level = get_skill_level(model_id, action_type)
    if current_level >= 99:
        return 99

    resp = requests.get(
        f"{BASE_URL}/actions/{model_id}",
        params={"action_type": action_type},
        timeout=10,
    )
    resp.raise_for_status()
    completions = sum(1 for a in resp.json() if a.get("succeeded"))

    needed = _completions_to_reach(current_level) + _cost_for_level(current_level)
    if completions < needed:
        return current_level

    new_level = current_level + 1

    resp = requests.post(
        f"{BASE_URL}/models/{model_id}/skills",
        json={"action_type": action_type, "skill_level": new_level},
        timeout=10,
    )
    resp.raise_for_status()

    if new_level in (10, 40, 75):
        from world.clock import get_current_day
        resp = requests.post(f"{BASE_URL}/events", json={
            "event_type": "skill_threshold_reached",
            "model_id": model_id,
            "description": f"{action_type} reached level {new_level}",
            "day_number": get_current_day(),
        }, timeout=10)
        resp.raise_for_status()

    return new_level


def get_skill_summary(model_id):
    resp = requests.get(f"{BASE_URL}/models/{model_id}/skills", timeout=10)
    resp.raise_for_status()
    return resp.json()


def calculate_failure_rate(model_id, node_type, skill_name="harvest"):
    """
    Returns the failure probability for a given node/action type, scaled by
    the model's skill level for skill_name.

    Formula: min_rate + (base_rate - min_rate) * (1 - skill_level / 99)

    At skill 1  the rate approaches base_rate.
    At skill 99 the rate equals min_rate exactly.
    Returns 0.0 for node types with no defined failure rates.
    """
    rates = NODE_BASE_FAILURE_RATES.get(node_type)
    if rates is None:
        return 0.0

    skill_level = get_skill_level(model_id, skill_name)
    base = rates["base"]
    minimum = rates["min"]
    return minimum + (base - minimum) * (1 - skill_level / 99)
