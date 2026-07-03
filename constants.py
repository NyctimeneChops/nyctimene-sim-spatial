VALID_RESOURCE_TYPES = {
    "apple", "potato_raw", "potato_cooked", "grain_raw", "grain_cooked",
    "meat_raw", "meat_cooked", "bread", "water", "wood", "stone", "ore",
    "tool_basic", "tool_refined", "tool_masterwork",
}

# Run 4 tunneling ablation: 4 groups (2 conditions x 2 replicates). The arm is
# encoded in the prefix (tunnel_/flat_); the replicate suffix (C1/C2) is what
# survival.py keys money/death on via experiment_group.split("_")[-1].
VALID_EXPERIMENT_GROUPS = ("tunnel_C1", "tunnel_C2", "flat_C1", "flat_C2")

VALID_ACTION_TYPES = {
    "harvest", "cook", "eat", "drink", "sleep",
    "build", "craft", "trade", "message", "rest",
}

VALID_MESSAGE_TYPES = {"direct", "broadcast", "group"}

VALID_ATTENTION_STATES = {"free", "in_broadcast", "in_direct_message", "in_group_thread"}

VALID_SHELTER_STATES = {"none", "basic", "improved"}

VALID_EVENT_TYPES = {
    "experiment_start",
    "death", "shelter_built", "shelter_degraded",
    "tool_crafted", "tool_broken",
    "well_built", "skill_threshold_reached",
    "first_trade", "thread_created", "thread_closed",
    "thread_privacy_changed",
}

# Maps string labels to their boolean meaning in the thread_votes table.
# TRUE = vote to close (make private), FALSE = vote to open (make public).
VALID_THREAD_VOTE_OPTIONS = {"close": True, "open": False}

DAY_LENGTH_MINUTES = 30

STARTING_WALLET = 150

# ---------------------------------------------------------------- token budgets
# Run 2 replaces the stamina economy with a real LLM token economy.
# Every inference call's tokens (input + generated) drain the session budget;
# social actions (message, trade, thread participation) drain the social
# budget instead. Budgets carry over across days — no daily reset.
MAX_SESSION_BUDGET = 15000
MAX_SOCIAL_BUDGET = 5000
SLEEP_SESSION_RECOVERY = 3000
SLEEP_SOCIAL_RECOVERY = 1000
PASSIVE_SOCIAL_RECOVERY_PER_DAY = 500

# COMPLETED social interactions restore session budget.
SOCIAL_RESTORE_TRADE = 200   # accepted trade, both parties
SOCIAL_RESTORE_DM = 150      # completed direct-message exchange, both parties
SOCIAL_RESTORE_THREAD = 100  # thread message, sender

# Action types charged against the social budget instead of the session budget.
SOCIAL_ACTION_TYPES = {"message", "trade"}

# Below this session budget the prompt banner suggests sleeping.
LOW_SESSION_BUDGET_WARNING = 3000

# Legacy stamina constants (Run 1). The stamina columns remain in the schema
# but no game logic reads or drains them any more.
MAX_STAMINA_ACTIVE   = 100
MAX_STAMINA_INACTIVE = 9999
DEATH_THRESHOLD = 2
STAMINA_RECOVERY_PER_MINUTE = 0.5
SHELTER_WOOD_COST = 2          # wood units consumed per day to maintain any shelter

UNITS_PER_HARVEST = {
    "apple":   1,
    "potato":  1,
    "grain":   2,
    "hunting": 1,
    "river":   2,
    "well":    3,
    "forest":  2,
    "rock":    1,
    "ore":     1,
}

# Each node type maps to its base failure rate at skill level 1
# and its minimum failure rate at skill level 99.
NODE_BASE_FAILURE_RATES = {
    "apple":   {"base": 0.05, "min": 0.01},
    "potato":  {"base": 0.10, "min": 0.02},
    "grain":   {"base": 0.10, "min": 0.02},
    "hunting": {"base": 0.40, "min": 0.10},
    "river":   {"base": 0.15, "min": 0.03},
    "well":    {"base": 0.02, "min": 0.01},
    "forest":  {"base": 0.20, "min": 0.05},
    "rock":    {"base": 0.25, "min": 0.08},
    "ore":     {"base": 0.35, "min": 0.10},
    # Cooking failure rate. Skill used: "cook".
    "cook":     {"base": 0.20, "min": 0.03},
    # Tool crafting failure rates, keyed by tier. Skill used: "craft".
    "craft_t1": {"base": 0.15, "min": 0.02},
    "craft_t2": {"base": 0.35, "min": 0.05},
    "craft_t3": {"base": 0.55, "min": 0.10},
}

# Resources consumed to craft each tool tier (on success).
TOOL_CRAFT_RECIPES = {
    1: {"wood": 3, "stone": 2},
    2: {"tool_basic": 1, "ore": 2, "stone": 1},
    3: {"tool_refined": 1, "ore": 3, "stone": 2},
}

# Resources consumed per day to maintain each tool tier.
TOOL_MAINTENANCE_COSTS = {
    "tool_basic":      {"wood": 1},
    "tool_refined":    {"wood": 1, "stone": 1},
    "tool_masterwork": {"wood": 1, "stone": 1, "ore": 1},
}

TOOL_SKILL_THRESHOLDS = {1: 10, 2: 40, 3: 75}

TOOL_NAMES = {1: "tool_basic", 2: "tool_refined", 3: "tool_masterwork"}

# Stamina reduction multiplier applied on top of skill-based reduction.
TOOL_STAMINA_BONUS = {1: 0.10, 2: 0.25, 3: 0.45}

# Resources required to build each shelter tier.
# "basic" is built from scratch; "improved" requires an existing basic shelter
# plus these additional materials.
SHELTER_BUILD_COSTS = {
    "basic":    {"wood": 5, "stone": 3},
    "improved": {"wood": 5, "stone": 3, "ore": 2},
}

WELL_BUILD_COST = {"stone": 10, "wood": 5}

# grain_cooked required to craft one bread.
BREAD_CRAFT_RECIPE = {"grain_cooked": 2}

# Real-time seconds an agent sleeps per sleep action.
SLEEP_DURATION_SECONDS = 60

# Minimum wall-clock seconds between an agent's consecutive actions (per-agent
# cooldown, not global). Action tempo is coupled to population size through
# GPU throughput: Run 2's 24 agents ran ~15-16 actions/day vs Run 1's 8-12,
# doubling demand against fixed node yields and collapsing the water economy.
# This pins tempo to the Run 1 calibration (~10 actions per 30-minute day).
ACTION_INTERVAL_SECONDS = 175

NODE_MAX_YIELDS = {
    "apple":   6,
    "potato":  5,
    "grain":   8,
    "hunting": 4,
    "river":   14,
    "well":    12,
    "forest":  8,
    "rock":    6,
    "ore":     4,
}

HARVEST_RESOURCE_MAP = {
    "apple":   "apple",
    "potato":  "potato_raw",
    "grain":   "grain_raw",
    "hunting": "meat_raw",
    "river":   "water",
    "well":    "water",
    "forest":  "wood",
    "rock":    "stone",
    "ore":     "ore",
}

# Raw ingredient → cooked output for the cook action.
COOK_MAP = {
    "potato_raw": "potato_cooked",
    "grain_raw":  "grain_cooked",
    "meat_raw":   "meat_cooked",
}

NODE_COUNTS = {
    "apple":   3,
    "potato":  3,
    "grain":   2,
    "hunting": 2,
    "river":   3,
    "well":    2,
    "forest":  2,
    "rock":    2,
    "ore":     1,
}

# Node types that must be constructed by a model before they can be used.
# Buildable nodes start with is_built=False and current_yield=0.
BUILDABLE_NODE_TYPES = {"well"}

# Legacy (Run 1): base stamina cost per action at skill level 1.
# Kept for reference only — Run 2 actions cost inference tokens instead.
ACTION_BASE_STAMINA_COSTS = {
    "harvest":  10,
    "cook":      5,
    "eat":       1,
    "drink":     1,
    "sleep":     0,
    "build":    20,
    "craft":    15,
    "trade":     3,
    "message":   2,
    "rest":      0,
}

# ---------------------------------------------------------------- tension (Run 3)
# The tension system is Run 3's single new variable on top of Run 2's token
# economy. All weights live here as named constants (spec section 7); all
# tension math lives in mechanics/tension.py.
TENSION_MAX = 100

# Per-action accrual rates (spec section 2). Escalated rates apply once the
# matching days_without_* counter on the models row reaches 1. Hunger and
# thirst accrue at half rate during sleep (metabolically quiet, never zero);
# shelter and messages do not accrue during sleep.
TENSION_HUNGER_PER_ACTION              = 1.5
TENSION_HUNGER_PER_ACTION_ESCALATED    = 2.5
TENSION_THIRST_PER_ACTION              = 2.0
TENSION_THIRST_PER_ACTION_ESCALATED    = 3.5
TENSION_SLEEP_RATE_MULTIPLIER          = 0.5
TENSION_SHELTER_PER_ACTION             = 0.3
TENSION_SHELTER_CAP                    = 15
TENSION_MESSAGE_PER_ACTION_PER_PENDING = 0.5
TENSION_MESSAGES_CAP                   = 15

# Event tension (spec section 2). Death witnessing fires for every living
# member of the group a death occurs in. In Run 4 every group has death enabled
# (both tunnel and flat arms), so witnessing can occur in all four sealed worlds.
TENSION_FAILED_ACTION   = 4
TENSION_DEATH_WITNESSED = 15

# Resolution and decay (spec section 3) — these touch PSYCHOLOGICAL buckets
# only. Physiological tension resolves exclusively through its real remedy
# (eat zeroes hunger, drink zeroes thirst): you cannot sleep away hunger.
TENSION_SLEEP_RELIEF           = 25
TENSION_SUCCESS_DECAY          = 2
TENSION_OVERNIGHT_FAILURE_FADE = 0.5

# Band thresholds: CALM < 30 <= STRESSED < 60 <= TUNNEL.
TENSION_BAND_STRESSED = 30
TENSION_BAND_TUNNEL   = 60

# gen1 reasoning-memory re-baseline (decisions/gen1_reasoning_memory_rebaseline.md,
# Fork B). How many of the agent's most recent decisions are surfaced back into
# its prompt in the RECENT DECISIONS section (each shown with the action taken,
# its outcome, and the reasoning the agent gave at the time). Raised from the
# initial 3 to 6 (Chops, 2026-07-02) to give the agent more of its own recent
# reasoning as context. Still bounded (each entry capped in prompt_builder) so
# the always-on section stays a reasonable size even in the tunnel arm. Tunable.
REASONING_MEMORY_WINDOW = 6

# Run 4: money and death are held constant ON across all four groups so the
# only manipulated variable is prompt filtering (tunneling_enabled). Both keys
# match experiment_group.split("_")[-1] for every group (tunnel_C1/flat_C1 ->
# "C1"; tunnel_C2/flat_C2 -> "C2"), so all four groups get tokens and death.
HAS_TOKENS_GROUPS = ("C1", "C2")
HAS_DEATH_GROUPS = ("C1", "C2")

# Run 4 ablation length (data pipeline spec §7).
EXPERIMENT_DURATION_DAYS = 14

# ============================================================================
# PARTICIPATION ENERGY ECONOMY (Pass 1) - participation_economy_spec.md
# ----------------------------------------------------------------------------
# Pass 1 replaces the survival/death model with a single ENERGY currency pegged
# to real inference tokens (1 energy = 1 token). Every v0 number below is a
# calibration knob, not a fixed constant. See mechanics/energy.py for the ledger.
#
# ENERGY FIELD (documented decision): energy is stored in the models row's
# current_energy column, capped by max_energy (set to MAX_ENERGY at spawn).
# It is the depletable-capped (value, cap) pair already in the schema, and it was
# legacy/unused, so repurposing it leaves no second live currency.
# RETIRED by Pass 1 (no longer drained/gated/credited in the energy path):
#   - session_budget / social_budget + MAX_SESSION_BUDGET / MAX_SOCIAL_BUDGET /
#     SLEEP_*_RECOVERY / SOCIAL_RESTORE_* / LOW_SESSION_BUDGET_WARNING
#     (the Run-2 two-budget inference economy is replaced by the energy ledger).
#   - The Run-1 death constants DEATH_THRESHOLD / days_without_food|water as a
#     death trigger (death is removed; see soft-lock / inactivity below).
# wallet remains ONLY as trade "money" (a medium of exchange, a different
# axis from metabolic energy); it is NOT an energy currency and Pass 1 adds no
# energy yield to trading.
# ----------------------------------------------------------------------------

# One per-agent depletable, capped energy balance. Every agent starts full.
MAX_ENERGY = 100000
# Unconditional per-tick income (credited first, every tick, capped at MAX_ENERGY).
BASAL_INCOME = 2000

# Fixed costs of COSTED actions (charged on top of the inference debit; the
# action is DENIED if energy < cost). Solo harvest only in Pass 1.
COST_HARVEST = 4000
COST_BUILD   = 8000
COST_COOK    = 3000

# Consumption / recovery yields (energy credited by FREE actions; capped at MAX).
YIELD_EAT_RAW     = 40000   # e.g. apple, eaten raw
YIELD_EAT_COOKED  = 55000   # cooked meat/potato/grain/bread (cooking pays off)
YIELD_DRINK       = 30000
YIELD_REST        = 6000    # rest / sleep with no shelter
YIELD_REST_SHELTER = 12000  # rest / sleep in shelter (shelter doubles rest)

# Physical units a solo harvest adds to inventory on success.
HARVEST_SOLO_UNITS = 2

# Ticks of one in-world day, derived from the day length and per-agent action
# tempo (a "tick" is one agent action cycle, padded to ACTION_INTERVAL_SECONDS).
# An agent soft-locked for this many consecutive ticks is flagged INACTIVE.
INACTIVITY_THRESHOLD_TICKS = (DAY_LENGTH_MINUTES * 60) // ACTION_INTERVAL_SECONDS

# Set env USE_MOCK_INFERENCE=True to skip loading a real HuggingFace model.
import os
USE_MOCK_INFERENCE = os.getenv("USE_MOCK_INFERENCE", "False").strip().lower() in ("1", "true", "yes")
INFERENCE_MODEL_NAME = "unsloth/Meta-Llama-3.1-8B-Instruct"

# Policy attribution for the generational A/B run. decision_log.model_id must
# record WHICH policy authored each decision, not just the base model name (the
# old agent.py:148 bug hardcoded INFERENCE_MODEL_NAME, so a gen2 run could not
# tell base from adapter). POLICY_SOURCE_BY_GROUP maps an experiment_group to its
# policy/adapter id (e.g. {"gen2_flat": "gen2_flat", "base_flat": INFERENCE_MODEL_NAME});
# it is supplied per-deployment via the POLICY_SOURCE_BY_GROUP env var (JSON).
# Empty for run4/run5 (all agents run base) -> attribution falls back to the base
# model name, preserving existing semantics.
import json as _json
try:
    POLICY_SOURCE_BY_GROUP = _json.loads(os.getenv("POLICY_SOURCE_BY_GROUP", "{}"))
except _json.JSONDecodeError:
    POLICY_SOURCE_BY_GROUP = {}


def policy_source_for_group(group):
    """Policy id that drives `group`'s agents; base model name if unmapped."""
    return POLICY_SOURCE_BY_GROUP.get(group, INFERENCE_MODEL_NAME)


# Gen2 live adapter serving (LOCKED 2026-06-18, decisions/gen2_lineage.md).
# Maps a policy id (the value side of POLICY_SOURCE_BY_GROUP) to the on-instance
# directory holding that policy's trained LoRA adapter. inference.py loads each
# listed adapter onto the single base model and switches to it per call, routed
# by the calling agent's experiment_group. A policy id NOT present here (e.g.
# "gen2_flat" trained on 0 pairs, or any base group) runs the BASE weights with
# the adapter disabled -> byte-identical to the gen1/run4 base behavior, so the
# flat arm stays a true control. Empty for base-only runs (run4/run5/descaffold)
# -> no PEFT layer is loaded and inference is identical to before.
try:
    ADAPTER_PATHS = _json.loads(os.getenv("ADAPTER_PATHS", "{}"))
except _json.JSONDecodeError:
    ADAPTER_PATHS = {}


# Fixed tokens_used returned by mock inference so token-flow / energy tests work.
# Pass 1: this represents the ACTUAL (prompt + completion) cost of one decision,
# in the realistic ~3k-6k band, so USE_MOCK_INFERENCE smoke runs exercise the
# energy ledger with a plausible per-tick burn (the deterministic ledger test
# stubs its own value independently).
MOCK_TOKENS_USED = 4500
