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
    "move",   # space milestone pass 1: teleport-per-tick move (Euclidean energy cost)
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

# --- v1 RECALIBRATION (2026-07-03), anchored to the MEASURED real burn --------
# The original v0 set was scaled to a 5000-token/thought stub. The live prompt
# builder was then measured with the real Llama-3.1 tokenizer: ~1251 tokens early
# (day 1) rising to ~1561 mature, i.e. ~1350-1660 energy/decision. GOVERNING
# PRINCIPLE (non-negotiable): BASAL_INCOME must sit clearly BELOW the real
# per-thought cost so an agent that ONLY thinks still LOSES energy each tick (the
# pressure exists from tick 1). v0's BASAL=2000 exceeded the real cost and
# inverted the pressure (idle was net-positive). The whole set below is scaled
# ~3x down from v0 to hold the same ratios against the ~1500 real per-thought
# cost. Every number remains a calibration knob.

# One per-agent depletable, capped energy balance. Every agent starts full.
# ~1500/thought => ~20 thoughts from full, so an agent that never eats runs low
# within roughly the first in-world day.
MAX_ENERGY = 30000
# Unconditional per-tick income. MUST be < the real per-thought cost (~1350-1660)
# so think-only nets negative (~-850 early / -1160 mature) while still being a
# genuine floor: a soft-locked agent, resting, slowly crawls back.
BASAL_INCOME = 500

# Fixed costs of COSTED actions (charged on top of the inference debit; the
# action is DENIED if energy < cost). Solo harvest only in Pass 1. Scaled ~3x
# from v0 (4000/8000/3000). Harvest ~= one thought's worth (cheap but non-trivial);
# build stays the most expensive single act.
COST_HARVEST = 1200
COST_BUILD   = 2500
COST_COOK    = 1000

# Consumption / recovery yields (energy credited by FREE actions; capped at MAX).
# Scaled ~3x from v0 so consumption stays an obviously-worth-it payoff: a
# harvest-then-eat cycle nets strongly positive (~+8.5-9k over 2 ticks) while NOT
# eating bleeds you out. Cooked keeps a meaningful premium over raw.
YIELD_EAT_RAW     = 12000   # e.g. apple, eaten raw
YIELD_EAT_COOKED  = 16000   # cooked meat/potato/grain/bread (cooking pays off)
YIELD_DRINK       = 9000
# Rest must beat idling (a stuck agent can crawl back) but lose badly to eating
# (rest is a survival floor, never a winning strategy): a rest tick nets ~+1000
# after the ~1500 thought, far below eating's +12000. Shelter doubles it.
YIELD_REST        = 2000    # rest / sleep with no shelter
YIELD_REST_SHELTER = 4000   # rest / sleep in shelter (shelter doubles rest)

# Physical units a solo harvest adds to inventory on success.
HARVEST_SOLO_UNITS = 2

# ============================================================================
# SPACE MILESTONE - PASS 1: coordinate system + teleport-per-tick movement
# ----------------------------------------------------------------------------
# nyctimene_space_milestone_design.md sections 1-2. Net-new surface on top of the
# intact v1 economy; NONE of the economy numbers above change.
#
# COORDINATE SPACE (documented decision): a continuous 2D plane of fixed size,
# PLANE_WIDTH x PLANE_HEIGHT, coordinates stored as floats (DOUBLE PRECISION in
# schema). Floats (not ints) because the plane is continuous and Euclidean
# distance is inherently real-valued; a grid would be an unnecessary constraint.
# Each experiment group is a SEALED sub-world (as in the economy: 9 nodes + 8
# agents per group), so every group is laid out on its OWN copy of this plane and
# distances/moves are always WITHIN a group. 1000 x 1000 gives room to spread
# 8 agents + 9 nodes per group without crowding and makes trip distances span
# 0 .. ~1414 (the diagonal), a useful dynamic range against the energy economy.
PLANE_WIDTH  = 1000.0
PLANE_HEIGHT = 1000.0

# Movement energy cost per unit of Euclidean distance (calibration knob; spec
# section 10 leaves the exact rate open). Scaling rationale against the v1 economy
# (MAX_ENERGY=30000, BASAL_INCOME=500/tick, COST_HARVEST=1200):
#   - short hop ~100 units  -> ~300 energy   (cheap, < a harvest)
#   - medium trip ~400 units -> ~1200 energy (== one COST_HARVEST)
#   - cross-plane ~1000     -> ~3000 energy  (~10% of MAX_ENERGY)
#   - max diagonal ~1414    -> ~4242 energy  (~14% of MAX_ENERGY)
# So a single trip is survivable (not instantly fatal), but an agent that keeps
# taking long trips nets negative (a 400-unit move costs 1200 vs +500 basal),
# creating pressure to settle near the resources it uses -- the intended spatial
# signal -- without the "instant death" failure mode (spec section 5 calibration).
MOVE_COST_PER_UNIT = 3

# --- SPACE MILESTONE pass 3: presence + exact-point occupancy enforcement ----
# "AT the node" definition (documented): an agent is AT a node if it is within
# AT_NODE_EPSILON of the node's (x,y). Nodes are SINGLE POINTS (no node radius -- we
# deliberately never build one). Teleport-per-tick lands a mover EXACTLY on the
# node's point, so this is effectively exact-coordinate presence; the tiny epsilon
# only absorbs float round-trip drift (DB DOUBLE PRECISION <-> Python float). The same
# epsilon defines "same point" for agent-vs-agent occupancy.
AT_NODE_EPSILON = 1e-6

# COLLISION MODEL (pass-3 CORRECTION): the earlier PERSONAL_RADIUS proximity rule was
# REMOVED -- a radius bubble wrongly let an agent near one node wall off moves to a
# DIFFERENT nearby node (accidental proximity-territoriality that worsens as node density
# scales). Collision is now EXACT-POINT OCCUPANCY only (mechanics/movement.destination_
# occupied): a move is denied only if a NON-node destination is already occupied by another
# agent in the same group; NODE destinations are never blocked (co-harvest stacking). No
# radius, no proximity, no "pass-through" (teleport has no transit). There is intentionally
# no PERSONAL_RADIUS constant anymore.

# --- SPATIAL FOUNDATION CLEANUP: graceful displacement + positional shelter ---
# GRACEFUL DISPLACEMENT replaces "deny the move/build" for an occupied NON-node target:
# the action lands at the nearest free point IN THE DIRECTION OF INTENT (step back from the
# target toward the actor past the occupied point). DISPLACEMENT_STEP is the back-off
# granularity in plane units; small so the landing is close to the intended point. (Node
# targets are exempt -- always stackable for co-harvest.)
DISPLACEMENT_STEP = 1.0

# DEFERRED DENY HOOK (dormant): if the displacement between the intended target and the
# actual landing point EXCEEDS this threshold, the action is DENIED for the tick instead of
# gracefully displaced (the agent is told to decide again). Default = infinite = never fires;
# on today's empty plane displacement is ~0. Later (crowded maps / shelter radii) this becomes
# a one-knob tuning change, not a re-architecture.
DISPLACEMENT_DENY_THRESHOLD = float("inf")

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
# Set to the MEASURED real per-decision cost (~1350 early -> ~1660 mature; ~1500
# mid) so USE_MOCK_INFERENCE smoke runs exercise the calibrated pressure the real
# model produces. The deterministic ledger test stubs its own values (1350/1660).
MOCK_TOKENS_USED = 1500
