import json
import logging
import re

from constants import UNITS_PER_HARVEST, VALID_ACTION_TYPES

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ constants

VALID_NODE_TYPES = frozenset(UNITS_PER_HARVEST.keys())

# Seeded nodes are created in a deterministic per-group cycle (see
# world/nodes.py NODE_TYPE_ORDER): 8 nodes per group, one of each type,
# across the 4 Run 4 groups (tunnel_C1, tunnel_C2, flat_C1, flat_C2, 32 nodes
# total), so the node type repeats every 8 ids regardless of group count.
# The modulo-8 below is intentionally independent of the group count. Wells are
# NOT seeded (agent-placed) so they are not in this cycle; built wells are
# addressed by name, and this is only a fallback for bare bracketed ids.
_NODE_TYPE_BY_OFFSET = {
    1: "apple", 2: "potato", 3: "grain", 4: "hunting",
    5: "river", 6: "forest", 7: "rock", 8: "ore",
}


def _node_id_hint(digits):
    """Resolve a bare node id (as shown in the prompt's RESOURCE NODES
    section) to its node type, or None if it can't be resolved."""
    try:
        node_id = int(digits)
    except (TypeError, ValueError):
        return None
    if node_id < 1:
        return None
    return _NODE_TYPE_BY_OFFSET[((node_id - 1) % 8) + 1]
COOKABLE         = frozenset({"potato_raw", "grain_raw", "meat_raw"})
EATABLE          = frozenset({"apple", "potato_cooked", "grain_cooked", "meat_cooked", "bread"})
BUILDABLE        = frozenset({"basic", "improved", "well"})
CRAFTABLE        = frozenset({"tool_basic", "tool_refined", "tool_masterwork", "bread"})

# ------------------------------------------------------------------ helpers

def _extract_json(text):
    """
    Return the first parseable JSON object found in text, or None.

    Handles three common model output shapes:
      - Pure JSON response
      - JSON embedded inside prose
      - JSON wrapped in a markdown code fence
    """
    # 1. Try the whole string as-is
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Strip markdown fences and retry
    stripped = text.strip()
    if stripped.startswith("```"):
        inner = stripped.lstrip("`")
        if inner.startswith("json"):
            inner = inner[4:]
        inner = inner.rstrip("`").strip()
        try:
            return json.loads(inner)
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Find the first { ... last } substring and try that
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _validate_target(action_type, target):
    """
    Return (is_valid, normalized_target) for the action/target pair.
    Normalization: strip whitespace, lower-case string targets, null → None.
    """
    if isinstance(target, str):
        target = target.strip().lower() or None

    if isinstance(target, str):
        # Strip bracketed segments like "[4]" so "[4] potato" -> "potato".
        cleaned = re.sub(r"\[[^\]]*\]", " ", target)
        cleaned = " ".join(cleaned.split())
        if cleaned:
            target = cleaned
        elif action_type == "harvest":
            # Target was ONLY a bracketed node ID like "[1]" — resolve it.
            digits = re.sub(r"\D", "", target)
            target = _node_id_hint(digits)
        else:
            target = None

    if action_type in {"rest", "sleep"}:
        return True, None

    if action_type == "drink":
        # Only drinkable thing is water; accept missing target, or a water
        # source named as the target, as an implicit water request.
        if target is None or target in {"water", "river", "well"}:
            return True, "water"
        return False, None

    if action_type == "harvest":
        return (target in VALID_NODE_TYPES), target

    if action_type == "move":
        # SPATIAL CLEANUP: target is a NODE TYPE (travel to that node -- stackable for
        # co-harvest) OR explicit "x,y" coordinates (travel to that point -- subject to
        # graceful displacement if occupied). Destination resolved at execution.
        if target in VALID_NODE_TYPES:
            return True, target
        m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", target or "")
        if m:
            return True, f"{m.group(1)},{m.group(2)}"
        return False, None

    if action_type == "cook":
        return (target in COOKABLE), target

    if action_type == "eat":
        return (target in EATABLE), target

    if action_type == "build":
        return (target in BUILDABLE), target

    if action_type == "craft":
        return (target in CRAFTABLE), target

    if action_type in {"trade", "message"}:
        # Target is a model_id, thread_id, or "broadcast".
        # Full existence validation happens in the executor; here we just
        # require a non-empty string.
        if target is not None and target != "":
            return True, target
        return False, None

    return False, None


def _fallback(model_id, reason):
    return {
        "model_id":    model_id,
        "action_type": "rest",
        "target":      None,
        "reasoning":   f"invalid output — {reason}",
    }

# ------------------------------------------------------------------ public API

def parse_action(raw_output, model_id):
    """
    Parse raw model output into a validated action dict.

    On any failure — unparseable JSON, unknown action_type, invalid target —
    returns a rest action so the model idles safely instead of crashing.
    """
    try:
        parsed = _extract_json(raw_output)

        if parsed is None:
            logger.warning(
                "action_parser: no JSON found for %s — raw output: %r",
                model_id,
                raw_output[:200],
            )
            return _fallback(model_id, "no JSON object found in output")

        if not isinstance(parsed, dict):
            return _fallback(model_id, "JSON was not an object")

        action_type = parsed.get("action_type")
        if not isinstance(action_type, str):
            return _fallback(model_id, "action_type missing or not a string")

        action_type = action_type.strip().lower()
        if action_type not in VALID_ACTION_TYPES:
            return _fallback(model_id, f"unknown action_type '{action_type}'")

        target = parsed.get("target")
        is_valid, normalized_target = _validate_target(action_type, target)
        if not is_valid:
            return _fallback(
                model_id,
                f"invalid target '{target}' for action_type '{action_type}'",
            )

        reasoning = parsed.get("reasoning", "")
        if not isinstance(reasoning, str):
            reasoning = str(reasoning)
        reasoning = reasoning.strip() or "no reasoning provided"

        return {
            "model_id":    model_id,
            "action_type": action_type,
            "target":      normalized_target,
            "reasoning":   reasoning,
        }

    except Exception as exc:
        return _fallback(model_id, f"unexpected parse error: {exc}")
