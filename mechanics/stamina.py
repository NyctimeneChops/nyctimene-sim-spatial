"""
Back-compat shim: the Run 1 stamina economy was replaced by the token-budget
economy in Run 2. All real logic lives in mechanics/budget.py; this module
only re-exports it so old imports don't break.
"""

from mechanics.budget import (  # noqa: F401
    apply_passive_social_recovery,
    apply_stamina_cost,
    calculate_stamina_cost,
    charge_budget,
    get_budget_state,
    get_stamina_state,
    is_social_action,
    recover_stamina,
    restore_budget,
)
