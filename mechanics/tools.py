import math
import random

import requests

from constants import (
    TOOL_CRAFT_RECIPES, TOOL_MAINTENANCE_COSTS,
    TOOL_NAMES, TOOL_SKILL_THRESHOLDS, TOOL_STAMINA_BONUS,
)
from mechanics.skills import calculate_failure_rate, get_skill_level

BASE_URL = "http://127.0.0.1:5000"



def _get_inventory(model_id):
    resp = requests.get(f"{BASE_URL}/inventory/{model_id}", timeout=10)
    resp.raise_for_status()
    return {row["resource_type"]: row["quantity"]
            for row in resp.json()["inventory"]}


def _add(model_id, resource_type, quantity):
    resp = requests.post(
        f"{BASE_URL}/inventory/{model_id}/add",
        json={"resource_type": resource_type, "quantity": quantity},
        timeout=10,
    )
    resp.raise_for_status()


def _deduct(model_id, resource_type, quantity):
    """Returns True on success, False if insufficient."""
    resp = requests.post(
        f"{BASE_URL}/inventory/{model_id}/deduct",
        json={"resource_type": resource_type, "quantity": quantity},
        timeout=10,
    )
    if resp.status_code == 400:
        return False
    resp.raise_for_status()
    return True


def _post_event(event_type, model_id, description):
    from world.clock import get_current_day
    try:
        resp = requests.post(f"{BASE_URL}/events", json={
            "event_type":  event_type,
            "model_id":    model_id,
            "description": description,
            "day_number":  get_current_day(),
        }, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[tools] event post failed ({event_type}): {e}", flush=True)


def can_craft_tool(model_id, tier):
    """
    Returns True if the model meets the skill threshold for this tier AND
    holds all required resources in inventory.
    """
    if tier not in TOOL_SKILL_THRESHOLDS:
        return False

    threshold = TOOL_SKILL_THRESHOLDS[tier]
    if get_skill_level(model_id, "craft") < threshold:
        return False

    inventory = _get_inventory(model_id)
    recipe = TOOL_CRAFT_RECIPES[tier]
    return all(inventory.get(r, 0) >= qty for r, qty in recipe.items())


def craft_tool(model_id, tier, action_type):
    """
    Attempt to craft a tool of the given tier.

    On success: deducts the full recipe, adds 1 tool to inventory, posts
    a tool_crafted event. Returns True.

    On failure: deducts half of each recipe ingredient (ceil) as waste,
    records the failed attempt. Returns False.

    Raises ValueError if the tier is invalid.
    """
    if tier not in TOOL_CRAFT_RECIPES:
        raise ValueError(f"Invalid tool tier: {tier}")

    tool_name = TOOL_NAMES[tier]
    recipe = TOOL_CRAFT_RECIPES[tier]
    failure_rate = calculate_failure_rate(model_id, f"craft_t{tier}", skill_name="craft")
    succeeded = random.random() >= failure_rate

    if succeeded:
        for resource_type, qty in recipe.items():
            _deduct(model_id, resource_type, qty)
        _add(model_id, tool_name, 1)
        _post_event("tool_crafted", model_id,
                    f"crafted {tool_name} for {action_type} (tier {tier})")
        return True
    else:
        for resource_type, qty in recipe.items():
            waste = math.ceil(qty / 2)
            _deduct(model_id, resource_type, waste)
        return False


def maintain_tools(model_id):
    """
    Called once per day. For each tool tier the model holds, attempts to deduct
    the daily maintenance cost. Any tool whose cost cannot be met is removed
    from inventory entirely and a tool_broken event is posted.
    """
    inventory = _get_inventory(model_id)

    for tool_name, costs in TOOL_MAINTENANCE_COSTS.items():
        quantity = inventory.get(tool_name, 0)
        if quantity == 0:
            continue

        can_pay = all(inventory.get(r, 0) >= qty for r, qty in costs.items())

        if can_pay:
            for resource_type, qty in costs.items():
                _deduct(model_id, resource_type, qty)
        else:
            _deduct(model_id, tool_name, 1)
            _post_event("tool_broken", model_id,
                        f"{tool_name} broken (maintenance not paid)")
        inventory = _get_inventory(model_id)


def get_tool_bonus(model_id, action_type):
    """
    Returns the stamina reduction fraction (0.0–0.45) granted by the best tool
    the model currently holds. Returns 0.0 if no tools are in inventory.

    The bonus is applied on top of the skill-based stamina reduction in
    stamina.py: effective_cost = skill_adjusted_cost * (1 - tool_bonus).
    """
    inventory = _get_inventory(model_id)

    for tier in (3, 2, 1):
        tool_name = TOOL_NAMES[tier]
        if inventory.get(tool_name, 0) > 0:
            return TOOL_STAMINA_BONUS[tier]

    return 0.0
