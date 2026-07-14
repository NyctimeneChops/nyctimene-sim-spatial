"""
Participation energy ledger (Pass 1) - participation_economy_spec.md sections 2-5.

This module is the SINGLE SOURCE OF TRUTH for every energy transition, and it is
deliberately PURE: no HTTP, no DB, no threads. Given a balance (and the tick's
inputs) it returns the next balance. agent.py wires these to the DB-backed energy
field (models.current_energy); the deterministic ledger test drives them directly
with a stubbed inference cost. Keeping the math here (not in the agent loop) is
what makes the economy testable without a GPU.

The per-tick order is fixed (spec section 4.D):
  1. credit BASAL_INCOME            (cap at MAX_ENERGY)
  2. debit the inference token cost  (ALWAYS applied; floored at 0; never denied)
  3. resolve the chosen action:
       - FREE   action: apply its energy yield (eat/drink/rest); cap at MAX_ENERGY.
                        social/trade have NO energy yield in Pass 1.
       - COSTED action: if energy >= cost, debit the cost and apply the effect;
                        otherwise DENY (no effect, no debit).
"""

from constants import (
    MAX_ENERGY, BASAL_INCOME,
    COST_HARVEST, COST_BUILD, COST_COOK,
    YIELD_EAT_RAW, YIELD_EAT_COOKED, YIELD_DRINK,
    YIELD_REST, YIELD_REST_SHELTER,
)

# --- Action taxonomy (spec section 3) --------------------------------------
# FREE: never denied for lack of energy (still costs inference tokens).
FREE_ACTIONS = frozenset({"eat", "drink", "rest", "message", "trade"})
# COSTED: require energy >= the fixed cost, else denied. (Cooperative harvest is
# NOT in Pass 1 - solo harvest only.)
COSTED_ACTION_COSTS = {
    "harvest": COST_HARVEST,
    "build":   COST_BUILD,
    "cook":    COST_COOK,
}
# Soft-lock = cannot afford the CHEAPEST costed action (so no costed action at all).
SOFT_LOCK_THRESHOLD = min(COSTED_ACTION_COSTS.values())

# Cooked foods yield more than raw; anything else edible (e.g. apple) is raw.
COOKED_FOODS = frozenset({"potato_cooked", "grain_cooked", "meat_cooked", "bread"})


# --- classification ---------------------------------------------------------

def is_free(action_type):
    return action_type in FREE_ACTIONS


def is_costed(action_type):
    return action_type in COSTED_ACTION_COSTS


def action_cost(action_type):
    """Fixed energy cost of a costed action; 0 for free/unknown actions."""
    return COSTED_ACTION_COSTS.get(action_type, 0)


def can_afford(energy, action_type):
    """True if the action is free, or costed and the balance covers its cost."""
    if is_costed(action_type):
        return energy >= COSTED_ACTION_COSTS[action_type]
    return True


def is_soft_locked(energy):
    """True if the balance is below the cheapest costed action (spec section 5)."""
    return energy < SOFT_LOCK_THRESHOLD


# --- yields -----------------------------------------------------------------

def consumption_yield(action_type, target=None, sheltered=False):
    """Energy a FREE action credits. eat depends on raw/cooked; rest on
    shelter; social/trade yield nothing in Pass 1."""
    if action_type == "eat":
        return YIELD_EAT_COOKED if target in COOKED_FOODS else YIELD_EAT_RAW
    if action_type == "drink":
        return YIELD_DRINK
    if action_type == "rest":
        return YIELD_REST_SHELTER if sheltered else YIELD_REST
    return 0


# --- ledger steps (each returns the new balance) ----------------------------

def credit_basal(energy):
    """Step 1: unconditional basal income, capped at MAX_ENERGY."""
    return min(MAX_ENERGY, energy + BASAL_INCOME)


def debit_inference(energy, tokens):
    """Step 2: debit the ACTUAL (prompt + completion) tokens. Never denied; the
    unpayable remainder is waived by flooring at 0 (the inference still happened)."""
    return max(0, energy - tokens)


def apply_free_yield(energy, action_type, target=None, sheltered=False):
    """Step 3 (free): credit the consumption/rest yield, capped at MAX_ENERGY."""
    return min(MAX_ENERGY, energy + consumption_yield(action_type, target, sheltered))


def apply_costed_debit(energy, action_type):
    """Step 3 (costed): if affordable, debit the fixed cost. Returns
    (new_energy, applied): applied=False means the action is DENIED (no debit)."""
    cost = COSTED_ACTION_COSTS.get(action_type, 0)
    if energy >= cost:
        return energy - cost, True
    return energy, False


# --- one-tick resolver (used by the deterministic ledger test) --------------

def resolve_tick(energy, action_type, tokens, target=None,
                 sheltered=False, precondition_ok=True, move_distance=None):
    """Run one full tick of the ledger in the fixed order and report what
    happened. Pure: the caller supplies the inference `tokens` (stubbed in tests,
    real per-inference in the live loop) and whether a free action's precondition
    (holding the item / valid target) is met. For a `move` action the caller also
    supplies `move_distance` (euclidean distance current->destination); its cost is
    variable (distance-based) rather than a fixed COSTED_ACTION_COSTS entry.

    Returns a dict:
      energy         - balance after the tick
      before_action  - balance after basal + inference, before the action
      outcome        - one of: costed_applied, costed_denied, move_applied,
                       move_denied, free_applied, free_precondition_failed
      applied        - True if the action took effect
      soft_locked    - is_soft_locked(energy) after the tick
    """
    e = credit_basal(energy)
    e = debit_inference(e, tokens)
    before_action = e

    if action_type == "move":
        # Variable (distance-based) costed action: teleport-per-tick move.
        from mechanics.movement import move_cost
        cost = move_cost(move_distance if move_distance is not None else 0.0)
        if e >= cost:
            e, applied, outcome = e - cost, True, "move_applied"
        else:
            applied, outcome = False, "move_denied"
    elif is_costed(action_type):
        e, applied = apply_costed_debit(e, action_type)
        outcome = "costed_applied" if applied else "costed_denied"
    else:
        # Free action (or unknown -> treated as a no-yield free think).
        if precondition_ok:
            e = apply_free_yield(e, action_type, target, sheltered)
            outcome, applied = "free_applied", True
        else:
            outcome, applied = "free_precondition_failed", False

    return {
        "energy":        e,
        "before_action": before_action,
        "outcome":       outcome,
        "applied":       applied,
        "soft_locked":   is_soft_locked(e),
    }
