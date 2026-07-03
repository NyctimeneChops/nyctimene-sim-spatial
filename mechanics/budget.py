"""
Token-budget economy (Run 2). Replaces the Run 1 stamina mechanic.

Every agent has two budgets, persisted on the models row:
  session_budget (max MAX_SESSION_BUDGET) — drained by every inference call's
      tokens_used (decision inference AND execution inference).
  social_budget (max MAX_SOCIAL_BUDGET) — drained instead of session by the
      inference behind social actions (message, trade, thread participation).

Budgets carry over across days. Sleep restores SLEEP_SESSION_RECOVERY /
SLEEP_SOCIAL_RECOVERY (handled server-side in blueprints/sleep.py); passive
social recovery is applied at the day boundary (world/clock.py); COMPLETED
social interactions restore session budget (hooked in the trade-accept and
message endpoints).

mechanics/stamina.py remains as a thin shim over this module so old imports
don't break.
"""

import requests

from constants import (
    MAX_SESSION_BUDGET,
    MAX_SOCIAL_BUDGET,
    PASSIVE_SOCIAL_RECOVERY_PER_DAY,
    SOCIAL_ACTION_TYPES,
)

BASE_URL = "http://127.0.0.1:5000"


def is_social_action(action_type):
    """True if this action type is paid from the social budget."""
    return action_type in SOCIAL_ACTION_TYPES


def get_budget_state(model_id):
    """
    Return the model's budgets as
    {"session_budget", "social_budget", "session_max", "social_max"}.
    """
    resp = requests.get(f"{BASE_URL}/models/{model_id}", timeout=10)
    resp.raise_for_status()
    model = resp.json()
    return {
        "session_budget": model["session_budget"],
        "social_budget":  model["social_budget"],
        "session_max":    MAX_SESSION_BUDGET,
        "social_max":     MAX_SOCIAL_BUDGET,
    }


def charge_budget(model_id, tokens, budget="session"):
    """
    Drain `tokens` from the given budget ("session" or "social").

    The charge is unconditional — by the time it arrives the inference tokens
    are already spent, so budgets are allowed to go negative. Depletion is
    enforced *before* the next inference (the agent loop refuses to act except
    sleep on an empty session budget, and rejects social actions on an empty
    social budget).

    Returns the updated {"session_budget", "social_budget"} dict.
    """
    if tokens <= 0:
        return get_budget_state(model_id)

    resp = requests.post(
        f"{BASE_URL}/models/{model_id}/budget/deduct",
        json={"budget_type": budget, "amount": tokens},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def restore_budget(model_id, amount, budget="session"):
    """
    Add `amount` to the given budget, capped at its maximum.
    Returns the updated {"session_budget", "social_budget"} dict.
    """
    if amount <= 0:
        return get_budget_state(model_id)

    resp = requests.post(
        f"{BASE_URL}/models/{model_id}/budget/recover",
        json={"budget_type": budget, "amount": amount},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def apply_passive_social_recovery(model_id):
    """Day-boundary passive social recovery (+PASSIVE_SOCIAL_RECOVERY_PER_DAY)."""
    return restore_budget(model_id, PASSIVE_SOCIAL_RECOVERY_PER_DAY, budget="social")


# ------------------------------------------------------------------ legacy API
# Back-compat no-op shims for the Run 1 stamina interface. Nothing drains or
# recovers current_stamina any more; these exist only so old call sites and
# imports keep working.

def calculate_stamina_cost(base_cost, action_type, model_id):
    """Legacy shim — actions no longer cost stamina. Always returns 0."""
    return 0


def apply_stamina_cost(model_id, stamina_cost):
    """Legacy shim — no stamina is deducted. Always returns True."""
    return True


def recover_stamina(model_id, amount):
    """Legacy shim — no stamina is recovered. Returns the unchanged value."""
    resp = requests.get(f"{BASE_URL}/models/{model_id}", timeout=10)
    resp.raise_for_status()
    return resp.json()["current_stamina"]


def get_stamina_state(model_id):
    """Legacy shim — reads the untouched legacy stamina columns."""
    resp = requests.get(f"{BASE_URL}/models/{model_id}", timeout=10)
    resp.raise_for_status()
    model = resp.json()
    current = model["current_stamina"]
    maximum = model["max_stamina"]
    percentage = round(current / maximum * 100, 1) if maximum > 0 else 0.0
    return {"current": current, "maximum": maximum, "percentage": percentage}
