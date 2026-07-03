import json
import random
import re

from constants import (
    ADAPTER_PATHS, INFERENCE_MODEL_NAME, MOCK_TOKENS_USED,
    NODE_BASE_FAILURE_RATES, USE_MOCK_INFERENCE, policy_source_for_group,
)

# Nodes the mock will consider for each goal category.
# Well is excluded from all lists: it is buildable and may have zero yield.
_FOOD_NODES    = ["apple", "potato", "grain", "hunting"]
_WATER_NODES   = ["river"]
_RESOURCE_NODES = ["forest", "rock", "ore"]
_ALL_HARVEST_NODES = _FOOD_NODES + _WATER_NODES + _RESOURCE_NODES

# Raw food items that require cooking before eating.
_RAW_FOOD_TYPES = ["potato_raw", "grain_raw", "meat_raw"]

# Lazy-loaded HuggingFace pipeline; populated on first real inference call.
_pipeline = None


def _parse_state(prompt):
    """
    Extract survival-relevant values from a free-text prompt string.
    Returns (stamina, wallet, has_eaten_today, raw_food_in_inventory).
    Falls back to safe defaults when a value cannot be found.
    """
    p = prompt.lower()

    stamina_match = re.search(r'stamina[^:\d]*:\s*(\d+(?:\.\d+)?)', p)
    stamina = float(stamina_match.group(1)) if stamina_match else 100.0

    token_match = re.search(r'token[_\s]balance[^:\d]*:\s*(\d+(?:\.\d+)?)', p)
    if not token_match:
        token_match = re.search(r'tokens?[^:\d]*:\s*(\d+(?:\.\d+)?)', p)
    tokens = float(token_match.group(1)) if token_match else 150.0

    # Accept any of several plausible phrasings the prompt builder might use.
    has_eaten = bool(re.search(
        r'(food[_\s](?:requirement[_\s])?met|has[_\s]eaten|ate[_\s]today)[^:\d]*:\s*(true|yes|1)\b',
        p,
    ))

    # Build list of raw food items that are present with qty > 0.
    # If the item name appears without a parseable quantity, assume it is present.
    raw_food = []
    for item in _RAW_FOOD_TYPES:
        qty_match = re.search(rf'{re.escape(item)}[^:\d]*:\s*(\d+)', p)
        if qty_match:
            if int(qty_match.group(1)) > 0:
                raw_food.append(item)
        elif item in p:
            raw_food.append(item)

    return stamina, tokens, has_eaten, raw_food


def _weighted_choice(node_list):
    """Pick a node at random, weighting by inverse base failure rate."""
    weights = [1.0 / NODE_BASE_FAILURE_RATES[n]["base"] for n in node_list]
    return random.choices(node_list, weights=weights, k=1)[0]


def _parse_node_yields(prompt):
    """
    Return {node_type: highest_current_yield} for every node type that still
    has yield > 0. Nodes showing '0 / N yield remaining' and 'NOT BUILT' nodes
    are omitted. When multiple nodes of the same type exist, keeps the maximum
    so the type is considered available as long as any one node has supply left.
    """
    yields = {}
    for match in re.finditer(
        r'\[\d+\]\s+(\w+)\s+(\d+)\s*/\s*\d+\s+yield remaining',
        prompt,
        re.IGNORECASE,
    ):
        node_type = match.group(1).lower()
        current_yield = int(match.group(2))
        if current_yield > 0:
            yields[node_type] = max(yields.get(node_type, 0), current_yield)
    return yields


def _mock_decision(prompt):
    """
    Return a plausible action decision without calling a real language model.

    Priority order:
      1. Stamina < 30              → rest
      2. Haven't eaten + raw food  → cook
      3. Haven't eaten + no food   → harvest a food node with yield remaining
      4. Raw food in inventory     → cook it
      5. Default                   → weighted-random harvest from nodes with yield remaining

    Nodes showing zero yield remaining in the prompt are excluded from harvest
    candidates. If all nodes in a category are depleted, falls back to the full
    list so the model never gets permanently stuck.
    """
    stamina, tokens, has_eaten, raw_food = _parse_state(prompt)
    node_yields = _parse_node_yields(prompt)

    def _available(node_list):
        # Exclude nodes we know are depleted. Fall back to the full list if
        # parsing failed (empty dict) or every node in the category is at zero,
        # so the model always has something to try.
        filtered = [n for n in node_list if node_yields.get(n, 1) > 0]
        return filtered if filtered else node_list

    if stamina < 30:
        return {
            "action_type": "rest",
            "target": None,
            "reasoning": (
                f"Stamina is critically low at {stamina:.0f}. "
                "Resting to recover before spending further energy."
            ),
        }

    if not has_eaten:
        if raw_food:
            item = random.choice(raw_food)
            return {
                "action_type": "cook",
                "target": item,
                "reasoning": (
                    f"Haven't eaten today. Cooking {item} now so it can be eaten this turn."
                ),
            }
        node = _weighted_choice(_available(_FOOD_NODES))
        return {
            "action_type": "harvest",
            "target": node,
            "reasoning": (
                f"Haven't eaten today and inventory has no food. "
                f"Harvesting {node} node — lowest failure rate among food sources with yield remaining."
            ),
        }

    if raw_food:
        item = random.choice(raw_food)
        return {
            "action_type": "cook",
            "target": item,
            "reasoning": (
                f"Survival needs are met for now. Cooking {item} to build cooked food reserves."
            ),
        }

    node = _weighted_choice(_available(_ALL_HARVEST_NODES))
    return {
        "action_type": "harvest",
        "target": node,
        "reasoning": (
            f"Food and stamina are both in good shape. "
            f"Harvesting {node} node to accumulate resources."
        ),
    }


def _mock_execution_response(prompt):
    """
    Return a canned response for second-stage execution prompts (see
    models/execution_prompts.py), or None if the prompt is a normal
    decision prompt. The mock always commits/confirms and proposes a
    minimal token-free trade so mock runs exercise the full two-stage path.
    """
    if "EXECUTION CHECK: HUNT" in prompt:
        return json.dumps({
            "decision": "commit",
            "reasoning": "mock: odds acceptable, committing to the hunt",
        })
    if "EXECUTION CHECK: CRAFT" in prompt or "EXECUTION CHECK: BUILD" in prompt:
        return json.dumps({
            "decision": "confirm",
            "reasoning": "mock: materials and skill check out, confirming",
        })
    if "EXECUTION CHECK: TRADE PROPOSAL" in prompt:
        return json.dumps({
            "resources_offered": {},
            "resources_requested": {"water": 1},
            "tokens_offered": 0,
            "reasoning": "mock: minimal opening offer",
        })
    return None


import threading
_inference_semaphore = threading.Semaphore(1)

def _group_of(model_id):
    """Experiment_group for a model_id of the form '<group_id>_<nn>'.

    group_id itself contains an underscore ('tunnel_C1'), so strip only the
    trailing '_<nn>' replicate-member suffix. Matches the id scheme in
    groups/group_runner.py ('<group_id>_<nn>').
    """
    return model_id.rsplit("_", 1)[0]


def _get_pipeline():
    """Load and cache (model, tokenizer, loaded_adapter_names).

    Loads the single base model once. If ADAPTER_PATHS is non-empty (gen2 and
    later lineage runs), each trained LoRA adapter is layered onto that same base
    via PEFT and kept resident; get_model_decision switches to the right one per
    call (serialized by the size-1 inference semaphore, so no adapter-state race)
    and falls back to the disabled-adapter base for any unmapped/base policy.
    When ADAPTER_PATHS is empty the model is the plain base and behaviour is
    byte-identical to the pre-gen2 code.
    """
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    tokenizer = AutoTokenizer.from_pretrained(INFERENCE_MODEL_NAME)
    model = AutoModelForCausalLM.from_pretrained(
        INFERENCE_MODEL_NAME,
        torch_dtype=torch.bfloat16,
        device_map="cuda:0"
    )
    loaded_adapters = set()
    if ADAPTER_PATHS:
        from peft import PeftModel
        first = True
        for name, path in ADAPTER_PATHS.items():
            if first:
                model = PeftModel.from_pretrained(model, path, adapter_name=name)
                first = False
            else:
                model.load_adapter(path, adapter_name=name)
            loaded_adapters.add(name)
        print(f"[inference] loaded {len(loaded_adapters)} gen2 adapter(s): "
              f"{sorted(loaded_adapters)}; base served with adapter disabled",
              flush=True)
    _pipeline = (model, tokenizer, loaded_adapters)
    return _pipeline

def get_model_decision(prompt, model_id):
    """
    Run one inference for the given prompt and return

        {"response": <text>, "tokens_used": <int>}

    where tokens_used = generated token count ONLY. The situation prompt is
    the world's gift; the agent pays for its own thinking. Every call is
    charged against the agent's token budgets by the caller.

    When USE_MOCK_INFERENCE is True, the response text comes from the
    rule-based mock (decision prompts) or canned execution-check replies, with
    a plausible fixed tokens_used so token-flow tests work without a model.
    """
    if USE_MOCK_INFERENCE:
        response = _mock_execution_response(prompt)
        if response is None:
            response = json.dumps(_mock_decision(prompt))
        return {"response": response, "tokens_used": MOCK_TOKENS_USED}

    import contextlib
    with _inference_semaphore:
        import torch
        model, tokenizer, loaded_adapters = _get_pipeline()

        # Route this agent to its generation's policy. tunnel groups -> their
        # gen2 adapter; flat/base/unmapped -> base weights (adapter disabled).
        # Serialized by _inference_semaphore so set_adapter/disable_adapter can
        # never interleave across concurrent agents.
        adapter_ctx = contextlib.nullcontext()
        if loaded_adapters:
            policy = policy_source_for_group(_group_of(model_id))
            if policy in loaded_adapters:
                model.set_adapter(policy)
            else:
                adapter_ctx = model.disable_adapter()

        messages = [{"role": "user", "content": prompt}]
        input_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(input_text, return_tensors="pt")
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        with adapter_ctx, torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=True,
                temperature=0.7,
                pad_token_id=tokenizer.eos_token_id
            )
        input_token_count = inputs["input_ids"].shape[1]
        generated = outputs[0][input_token_count:]
        response = tokenizer.decode(generated, skip_special_tokens=True)
        # Pass 1 energy peg: charge the ACTUAL (prompt + completion) tokens, so
        # verbose reasoning literally burns more energy. (Run 2 charged the
        # generated tokens only.)
        tokens_used = int(input_token_count) + int(generated.shape[0])
    return {"response": response, "tokens_used": tokens_used}
