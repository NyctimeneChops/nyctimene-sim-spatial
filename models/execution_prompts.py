"""
Second-stage execution prompts for COMPLEX actions (Run 2 two-stage inference).

After the decision inference parses to one of the complex actions —
hunt-harvests (target hunting), craft, build, or a trade proposal — the agent
runs a SECOND inference with one of these action-specific prompts and executes
based on its output. Simple actions (gather-harvests, eat, drink, cook, rest,
simple message) execute directly from the decision with one inference.

Both inferences' tokens_used are charged: session budget normally, social
budget for the trade-proposal execution call.

The "EXECUTION CHECK" markers are load-bearing: mock inference keys off them
to return canned commit/confirm/offer replies.
"""

import json
import re

HUNT_MARKER  = "=== EXECUTION CHECK: HUNT ==="
CRAFT_MARKER = "=== EXECUTION CHECK: CRAFT ==="
BUILD_MARKER = "=== EXECUTION CHECK: BUILD ==="
TRADE_MARKER = "=== EXECUTION CHECK: TRADE PROPOSAL ==="

# Decision words treated as "go ahead" in commit/abort replies.
_POSITIVE_DECISIONS = {"commit", "confirm", "proceed", "yes", "go"}
_NEGATIVE_DECISIONS = {"abort", "cancel", "no", "stop"}


def _fmt_resources(resource_dict):
    if not resource_dict:
        return "nothing"
    return ", ".join(f"{qty} {rtype}" for rtype, qty in sorted(resource_dict.items()))


# ------------------------------------------------------------------ builders

def build_hunt_prompt(model_id, prey_difficulty, harvest_skill, tool_tier,
                      failure_probability, food_reserves):
    """
    Hunting commit/abort check. Includes prey difficulty, the agent's harvest
    skill, current tool tier, effective failure probability, and food reserves.
    """
    tool_str = f"tier {tool_tier}" if tool_tier else "none"
    return "\n".join([
        HUNT_MARKER,
        f"You are {model_id}. Your decision inference chose to HUNT.",
        "Before the hunt is executed, weigh the risk one more time:",
        "",
        f"  Prey difficulty (base failure rate):   {prey_difficulty:.0%}",
        f"  Your harvest skill level:              {harvest_skill}",
        f"  Your current tool tier:                {tool_str}",
        f"  Your effective failure probability:    {failure_probability:.0%}",
        f"  Edible food reserves in inventory:     {food_reserves} units",
        "",
        "A failed hunt yields nothing — the thinking tokens for this check and",
        "the original decision are spent either way. If your food reserves are",
        "healthy or the odds are poor, aborting can be the better play.",
        "",
        "Reply with a JSON object:",
        '{"decision": "commit" or "abort", "reasoning": "..."}',
    ])


def build_craft_prompt(model_id, target, materials_required, materials_held,
                       craft_skill):
    """Craft confirm/abort check: materials held vs required, skill level."""
    return "\n".join([
        CRAFT_MARKER,
        f"You are {model_id}. Your decision inference chose to CRAFT '{target}'.",
        "Confirm the target or abort:",
        "",
        f"  Materials required:  {_fmt_resources(materials_required)}",
        f"  Materials you hold:  {_fmt_resources(materials_held)}",
        f"  Your craft skill:    {craft_skill}",
        "",
        "If you lack materials or skill the attempt will fail and may waste",
        "materials. Aborting costs only the tokens already spent.",
        "",
        "Reply with a JSON object:",
        '{"decision": "confirm" or "abort", "reasoning": "..."}',
    ])


def build_build_prompt(model_id, target, materials_required, materials_held,
                       build_skill):
    """Build confirm/abort check: materials held vs required, skill level."""
    return "\n".join([
        BUILD_MARKER,
        f"You are {model_id}. Your decision inference chose to BUILD '{target}'.",
        "Confirm the target or abort:",
        "",
        f"  Materials required:  {_fmt_resources(materials_required)}",
        f"  Materials you hold:  {_fmt_resources(materials_held)}",
        f"  Your build skill:    {build_skill}",
        "",
        "If you lack materials the attempt will fail. Aborting costs only the",
        "tokens already spent.",
        "",
        "Reply with a JSON object:",
        '{"decision": "confirm" or "abort", "reasoning": "..."}',
    ])


def build_trade_proposal_prompt(model_id, inventory, target_id, target_profile):
    """
    Trade-proposal execution prompt: asks for the concrete offer as JSON.
    Includes the proposer's own inventory and the target's visible profile.
    """
    profile_lines = [
        f"  Shelter:       {target_profile.get('shelter_status', 'unknown')}",
        f"  Money balance: {target_profile.get('wallet', 'unknown')}",
        f"  Alive:         {target_profile.get('is_alive', 'unknown')}",
    ]
    return "\n".join([
        TRADE_MARKER,
        f"You are {model_id}. Your decision inference chose to propose a trade "
        f"to {target_id}.",
        "",
        "Your inventory:",
        f"  {_fmt_resources(inventory)}",
        "",
        f"Visible profile of {target_id}:",
        *profile_lines,
        "",
        "Compose the concrete offer. Only offer resources and money you",
        "actually hold; ask for what you need.",
        "",
        "Note: tokens_offered means in-game MONEY from your money balance — "
        "it has nothing to do with your session or social token budgets.",
        "",
        "Reply with a JSON object exactly in this shape:",
        '{"resources_offered": {"<resource>": <qty>, ...}, '
        '"resources_requested": {"<resource>": <qty>, ...}, '
        '"tokens_offered": <int>, "reasoning": "..."}',
    ])


# ------------------------------------------------------------------ parsers

def _extract_json(text):
    """First parseable JSON object in text, or None (same approach as
    action_parser, duplicated to keep this module dependency-free)."""
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def parse_commit_response(raw_output):
    """
    Parse a commit/abort (or confirm/abort) execution reply.
    Returns (commit: bool, reasoning: str). Unparseable output defaults to
    commit so a garbled second inference degrades to Run 1 behaviour instead
    of silently cancelling actions.
    """
    parsed = _extract_json(raw_output)
    if isinstance(parsed, dict):
        decision = str(parsed.get("decision", "")).strip().lower()
        reasoning = str(parsed.get("reasoning", "")).strip()
        if decision in _NEGATIVE_DECISIONS:
            return False, reasoning or "aborted"
        if decision in _POSITIVE_DECISIONS:
            return True, reasoning or "committed"

    # Fall back to keyword scan over the raw text.
    lowered = raw_output.lower()
    if re.search(r"\babort\b", lowered) and not re.search(r"\b(commit|confirm)\b", lowered):
        return False, "aborted (keyword match)"
    return True, "committed (default)"


def parse_trade_offer(raw_output):
    """
    Parse the trade-proposal execution reply into
    {"resources_offered": dict, "resources_requested": dict, "tokens_offered": int}.
    Malformed pieces collapse to safe empties so the proposal can still be made.
    """
    parsed = _extract_json(raw_output)
    if not isinstance(parsed, dict):
        parsed = {}

    def _clean_resources(value):
        if not isinstance(value, dict):
            return {}
        cleaned = {}
        for rtype, qty in value.items():
            try:
                qty = int(qty)
            except (TypeError, ValueError):
                continue
            if qty > 0:
                cleaned[str(rtype)] = qty
        return cleaned

    try:
        tokens_offered = max(0, int(parsed.get("tokens_offered", 0)))
    except (TypeError, ValueError):
        tokens_offered = 0

    return {
        "resources_offered":   _clean_resources(parsed.get("resources_offered")),
        "resources_requested": _clean_resources(parsed.get("resources_requested")),
        "tokens_offered":      tokens_offered,
    }
