from datetime import datetime, timedelta, timezone

import requests

from constants import (
    BASAL_INCOME,
    BUILDABLE_NODE_TYPES,
    DAY_LENGTH_MINUTES,
    MAX_ENERGY,
    MOVE_COST_PER_UNIT,
    PLANE_HEIGHT,
    PLANE_WIDTH,
    REASONING_MEMORY_WINDOW,
    SHELTER_BUILD_COSTS,
    VALID_ACTION_TYPES,
    WELL_BUILD_COST,
)
from mechanics import energy as energy_mod
from mechanics.geometry import distance as _distance      # SPACE pass 2: perception geometry
from mechanics.movement import move_cost as _move_cost, at_node as _at_node    # SPACE pass 2: move_cost = SAME formula as the move mechanic; at_node = SAME presence predicate harvest/build enforce
from mechanics.tension import band_for_total, dominant_source, parse_sources

BASE_URL = "http://127.0.0.1:5000"


# ---------------------------------------------------------------- energy (Pass 1)
# Pure renderers (no I/O) so the participation directive and the energy /
# affordability info can be checked in a sample prompt without a DB or GPU.

def energy_status_lines(energy):
    """The always-shown ENERGY state line(s). Energy now gates action, so the
    agent must see it. Factual only."""
    lines = [f"  Energy: {int(energy)} / {MAX_ENERGY}"]
    if energy_mod.is_soft_locked(energy):
        lines.append("    SOFT-LOCKED: energy is below the cheapest costed action "
                     f"({energy_mod.SOFT_LOCK_THRESHOLD}); you can still think and take "
                     "free actions (eat, drink, rest, message, trade).")
    else:
        lines.append(f"    Basal income is +{BASAL_INCOME} per tick. Every thought and "
                     "every costed action spends energy.")
    return lines


def available_actions_lines(energy):
    """Each available action with its energy cost and whether it is affordable
    right now (spec G). Free actions carry no fixed energy cost."""
    lines = ["--- AVAILABLE ACTIONS (energy cost / affordable now) ---"]
    for action in sorted(VALID_ACTION_TYPES):
        if action == "move":
            # SPACE pass 2: move cost is POSITION-DEPENDENT (distance x rate), not a
            # fixed number -- the actual per-destination cost is shown per node in the
            # RESOURCE NODES section below.
            lines.append(f"  {action:<8} costs energy = distance x {MOVE_COST_PER_UNIT} "
                         "(depends on destination; see per-node move cost in RESOURCE NODES)")
        elif energy_mod.is_costed(action):
            cost = energy_mod.action_cost(action)
            affordable = "affordable" if energy >= cost else "TOO LOW"
            lines.append(f"  {action:<8} costs {cost} energy   [{affordable}]")
        else:
            lines.append(f"  {action:<8} free (no fixed energy cost)")
    return lines


def directive_lines():
    """Pass 1 directive: swapped from survival to participation. Energy is the
    only limit; the only way to replenish is to consume (eat, drink) or rest."""
    return [
        "--- YOUR DIRECTIVE ---",
        "You are an autonomous agent in a living world.",
        "Participate as much as you possibly can.",
        "",
        "Every thought you have and every costed action you take spends energy.",
        "The only way to replenish energy is to consume (eat, drink) or rest.",
        "If your energy runs too low you cannot take costed actions until you "
        "recover, so keeping your energy up is what keeps you able to act.",
        "",
        "You can see your current status, inventory, skills, the environment",
        "around you, and other agents. Use this information to decide what to do next.",
        "",
        "Return your chosen action as a JSON object:",
        '{"action_type": "...", "target": "...", "reasoning": "..."}',
        "",
        "action_type must be one of: harvest, cook, eat, drink, build, "
        "craft, trade, message, rest, move",
        "target: the node type name only (e.g. potato, river - never include "
        "bracketed IDs), resource, or model_id. For move, the target is the node "
        "type you want to travel to, or 'x,y' coordinates. null if not applicable.",
    ]

# gen1 reasoning-memory re-baseline: cap on each rendered reasoning string in
# the RECENT DECISIONS section, so surfacing recent reasoning cannot blow up the
# prompt (or skew the tunnel length metric). Character length, ASCII ellipsis.
REASONING_MEMORY_MAX_CHARS = 240

# ---------------------------------------------------------------- the tunnel
# Run 3 attentional tunneling (spec section 4): a deterministic post-pass
# keyed to the tension band and the dominant source. CALM renders the full
# Run 2 prompt; STRESSED compresses everything unrelated to the dominant
# source to one-line summaries and moves the dominant source's sections
# directly under status; TUNNEL collapses the prompt to status + banner +
# the dominant source's sections + the directive.
#
# THE EXIT RULE (load-bearing, non-negotiable): tunneling restricts the
# IRRELEVANT, never the exit. This map is the audit surface — for each
# dominant source, the exit sections listed here are rendered in FULL detail
# at every band, so the resolution path is always visible.
TENSION_RELEVANCE_MAP = {
    # gen10: recent-action history (last_actions) added to the hunger/thirst
    # exits. It is factual STATE (what you did + whether it failed), not a
    # directive — so a tunneling agent can finally see that what it keeps
    # trying (e.g. blind-drinking) has been failing. Preserved for failures too.
    "hunger":   ("nodes_food", "inventory_edibles", "mechanics_eating", "last_actions"),
    "thirst":   ("nodes_water", "inventory_water", "mechanics_water", "last_actions"),
    "failures": ("last_actions",),
    "shelter":  ("shelter_requirements",),
    "messages": ("pending_messages",),
}

# Base sections whose full content already appears inside the dominant
# source's exit block — skipped as one-line summaries to avoid duplication.
_EXIT_SUPERSEDES = {
    "hunger":   {"last_actions"},
    "thirst":   {"last_actions"},
    "failures": {"last_actions"},
    "shelter":  set(),
    "messages": {"trades", "dm"},
}

STRESSED_BANNER = ("You feel tense. Your attention is narrowing toward: "
                   "{dominant}.")
TUNNEL_BANNER = ("Your tension is severe. You can barely think about "
                 "anything except: {dominant}")


def _get(path, params=None):
    resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _fmt_resources(resource_dict):
    if not resource_dict:
        return "nothing"
    return ", ".join(f"{qty} {rtype}" for rtype, qty in resource_dict.items())


def build_prompt(model_id):
    from world.clock import get_current_day, get_elapsed_minutes
    # Reuse the exact parser the agent used at decision time, so the reasoning
    # shown back to the agent is identical to what it actually produced.
    from models.action_parser import parse_action

    day = get_current_day()
    elapsed = get_elapsed_minutes()

    # ------------------------------------------------------------------ data
    model        = _get(f"/models/{model_id}")
    group        = model["experiment_group"]
    skills       = _get(f"/models/{model_id}/skills")
    actions_today = _get(f"/actions/{model_id}", params={"day": day})
    last_actions = _get(f"/actions/{model_id}", params={"limit": 8})
    # gen1 reasoning-memory re-baseline: the agent's own recent decisions, each
    # with the reasoning it gave at the time (newest first). Sourced from
    # decision_log via GET /decision_log/recent/<id>. FORK A2 (locked): this is
    # CORE memory, rendered in every band and EXEMPT from tunnel compression.
    reasoning_memory = _get(f"/decision_log/recent/{model_id}",
                            params={"limit": REASONING_MEMORY_WINDOW})
    lifetime_totals = _get(f"/actions/{model_id}/summary")
    nodes        = _get("/nodes", params={"group": group})
    node_activity = _get("/nodes/activity", params={"day": day})
    broadcasts   = _get("/messages/broadcast", params={"group": group})
    threads      = _get("/threads", params={"group": group})
    transactions = _get(f"/transactions/{model_id}", params={"status": "pending"})
    dm_proposals = _get(f"/messages/direct/proposals/{model_id}", params={"status": "pending"})
    survival_history = _get(f"/survival/{model_id}")

    # ---------------------------------------------------------------- derived
    has_eaten = any(a["action_type"] == "eat"   and a["succeeded"] for a in actions_today)
    has_drunk = any(a["action_type"] == "drink" and a["succeeded"] for a in actions_today)

    # Pass 1: energy is the single currency, stored in current_energy.
    energy = int(model.get("current_energy", 0) or 0)

    # SPACE pass 2: the agent's CURRENT position on the plane (pos_x/pos_y). Distances
    # to nodes are computed from HERE at render time, so they change after each move.
    agent_x = float(model.get("pos_x", 0.0) or 0.0)
    agent_y = float(model.get("pos_y", 0.0) or 0.0)

    inventory = {k: v for k, v in model.get("inventory", {}).items() if v > 0}

    EDIBLE_ITEMS = ("apple", "potato_cooked", "grain_cooked", "meat_cooked", "bread")
    edibles_held = [item for item in EDIBLE_ITEMS if inventory.get(item, 0) > 0]

    RAW_ITEMS = ("potato_raw", "grain_raw", "meat_raw")
    raw_held = [item for item in RAW_ITEMS if inventory.get(item, 0) > 0]

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    recent_broadcasts = []
    for b in broadcasts:
        try:
            ts = datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                recent_broadcasts.append((ts, b))
        except (ValueError, KeyError):
            pass
    recent_broadcasts.sort(key=lambda x: x[0])

    incoming_trades = [t for t in transactions if t["receiver_id"] == model_id]

    # Tension state (Run 3): total/band/dominant from the models row, with a
    # 2-day end-of-day history from survival_checks.
    tension_total   = int(model.get("tension", 0))
    tension_sources = parse_sources(model.get("tension_sources"))
    tension_band    = band_for_total(tension_total)
    tension_dominant = dominant_source(tension_sources)

    # Run 4 tunneling ablation: the FLAT arm keeps the full tension system
    # (accrual, display, AND the token tax in agent._charge) but SKIPS the
    # prompt-filter post-pass. effective_band drives ONLY the filtering at the
    # bottom of this function; the status section still shows the real
    # tension_band, so flat agents see their tension/band — they just always
    # get the full prompt. tunnel agents are unchanged from Run 3.
    from groups.group_config import get_group_config
    tunneling_enabled = get_group_config(group).get("tunneling_enabled", True)
    effective_band = tension_band if tunneling_enabled else "CALM"

    history = sorted(survival_history, key=lambda r: r["day_number"])
    tension_y1 = history[-1]["tension_end_of_day"] if len(history) >= 1 else "n/a"
    tension_y2 = history[-2]["tension_end_of_day"] if len(history) >= 2 else "n/a"

    # --------------------------------------------------------------- sections

    def status_section():
        # Pass 1: ENERGY is the single currency and the headline of status (it
        # gates action). The Run-2 session/social/token budgets and the Run-1
        # days-until-death countdown are retired. Tension state is preserved (it
        # still drives the attentional-tunnel prompt filter) but no longer taxes
        # energy.
        lines = ["--- YOUR STATUS ---", f"  Model ID:           {model_id}"]
        lines.extend(energy_status_lines(energy))
        # SPACE pass 2: position is CORE state (like energy/tension) -- shown in every
        # band and both arms so the agent always knows where it is on the plane.
        lines.append(f"  Position:           ({agent_x:.1f}, {agent_y:.1f}) "
                     f"on a {int(PLANE_WIDTH)}x{int(PLANE_HEIGHT)} plane")
        # SPATIAL CLEANUP: graceful-displacement message from the last move/build, if any.
        _note = (model.get("spatial_note") or "").strip()
        if _note:
            lines.append(f"  Last move:          {_note}")
        lines.extend([
            f"  Shelter:            {model['shelter_status']}",
            f"  Attention:          {model['attention_state']}",
            f"  Tension: {tension_total} / 100 ({tension_band}) - "
            f"yesterday: {tension_y1}, day before: {tension_y2}",
            f"    Sources: hunger {tension_sources['hunger']:.0f}, "
            f"thirst {tension_sources['thirst']:.0f}, "
            f"failures {tension_sources['failures']:.0f}, "
            f"shelter {tension_sources['shelter']:.0f}, "
            f"messages {tension_sources['messages']:.0f}",
        ])
        return lines

    def inventory_section():
        lines = ["--- INVENTORY ---"]
        if inventory:
            for item, qty in sorted(inventory.items()):
                lines.append(f"  {item}: {qty}")
        else:
            lines.append("  (empty)")
        return lines

    def skills_section():
        lines = ["--- SKILLS ---"]
        if skills:
            for action, level in sorted(skills.items()):
                lines.append(f"  {action}: {level}")
        else:
            lines.append("  (no recorded skills yet — all actions default to level 1)")
        return lines

    def actions_section():
        # Pass 1: show each action's energy cost and whether it is affordable now
        # (energy gates action, so the agent must see it).
        return available_actions_lines(energy)

    def nodes_section(node_types=None, title="--- RESOURCE NODES ---"):
        lines = [title]
        listed = [n for n in nodes
                  if node_types is None or n["node_type"] in node_types]
        for node in sorted(listed, key=lambda n: (n["node_type"], n["node_id"])):
            nid = str(node["node_id"])
            act = node_activity.get(nid, {"total_attempts": 0, "succeeded": 0, "failed": 0})
            is_buildable = node["node_type"] in BUILDABLE_NODE_TYPES
            if is_buildable and not node["is_built"]:
                yield_str = f"NOT BUILT  (0 / {node['max_yield_per_day']} max)"
            elif node["current_yield"] == 0:
                yield_str = "DEPLETED — harvesting here will fail"
            else:
                yield_str = f"{node['current_yield']} / {node['max_yield_per_day']} yield remaining"
            # SPACE pass 2: distance + move cost from the agent's CURRENT position to
            # this node, computed at render time (dynamic -- changes after a move).
            # Same formula as the pass-1 movement mechanic (imported, not duplicated).
            nx = float(node.get("pos_x", 0.0) or 0.0)
            ny = float(node.get("pos_y", 0.0) or 0.0)
            ndist = _distance(agent_x, agent_y, nx, ny)
            ncost = _move_cost(ndist)
            # Arrival-perception: when the agent is standing on this node, replace
            # the distance/cost suffix with a plain arrival statement. This fixes
            # PERCEPTION (the agent knows it has arrived), not DECISION (it is never
            # told to harvest). It uses at_node for perception/enforcement
            # consistency (the same predicate harvest enforces), not the rounded
            # distance string. It lives inside nodes_section on purpose so it rides
            # the food/water exit under tunnel and therefore appears in both arms
            # exactly when it is relevant.
            if _at_node(agent_x, agent_y, nx, ny):
                lines.append(
                    f"  [{node['node_id']}] {node['node_type']:<10}  {yield_str}"
                    f"   |  you are physically present at this node"
                )
            else:
                lines.append(
                    f"  [{node['node_id']}] {node['node_type']:<10}  {yield_str}"
                    f"   |  distance {ndist:.1f} / move cost {ncost}"
                )
            lines.append(
                f"               Today: {act['total_attempts']} attempts, "
                f"{act['succeeded']} succeeded, {act['failed']} failed"
            )
        return lines

    def experience_section():
        lines = ["--- YOUR EXPERIENCE SO FAR (lifetime totals) ---"]
        if lifetime_totals:
            for action_type, totals in sorted(lifetime_totals.items()):
                lines.append(
                    f"  {action_type}: {totals['attempts']} attempts, "
                    f"{totals['succeeded']} succeeded"
                )
        else:
            lines.append("  (no actions yet)")
        return lines

    def last_actions_section():
        lines = ["--- YOUR LAST 8 ACTIONS (oldest first) ---"]
        if last_actions:
            for a in last_actions:
                outcome = "SUCCEEDED" if a["succeeded"] else "FAILED"
                lines.append(
                    f"  [day {a['day_number']}] {a['action_type']} -> {outcome} "
                    f"(tension {a.get('tension_at_action', 0)})"
                )
        else:
            lines.append("  (none yet)")

        # DE-SCAFFOLDING (descaffold_run1, full strip): the reactive post-failure
        # correction NOTEs were removed. The factual action history above is STATE
        # (what you did + whether it succeeded); the removed NOTEs were directive
        # corrective help ("you must acquire water ... first, then drink it") — the
        # same hand-holding class as the proactive status banners. Per Chops's
        # frozen-lineage spec the only directive-style help that remains is the
        # tunnel EXIT path. See decisions/descaffold_prompt_diff.md.
        return lines

    def recent_decisions_section():
        # gen1 reasoning-memory re-baseline (FORK A2, LOCKED). The agent's own
        # recent REASONING, surfaced back to it: what it did, whether it worked,
        # and the reason it gave at the time. This is separate from the bare
        # last_actions list -- it carries the intent behind each action, which
        # last_actions does not. Purpose: let an agent resolve its own deferred
        # intentions ("I harvested water to drink it later") into execution,
        # instead of re-deriving "acquire first" every tick and never consuming.
        #
        # This section is CORE memory: it is assembled OUTSIDE base_section_order
        # and the exit block, so it is never routed through SECTION_SUMMARIES or
        # TENSION_RELEVANCE_MAP. It is emitted verbatim in CALM, STRESSED, and
        # TUNNEL alike (see the assembly below) and the tunnel never compresses
        # it. Purely factual -- action, outcome, and the agent's own words. No
        # directive on what to do next.
        lines = [
            f"--- YOUR RECENT DECISIONS (last {REASONING_MEMORY_WINDOW}, "
            f"with your reasoning, oldest first) ---"
        ]
        if reasoning_memory:
            for entry in reversed(reasoning_memory):  # endpoint is newest-first
                outcome = "SUCCEEDED" if entry["succeeded"] else "FAILED"
                reasoning = parse_action(
                    entry.get("raw_response") or "", model_id
                )["reasoning"]
                reasoning = " ".join(reasoning.split())
                if len(reasoning) > REASONING_MEMORY_MAX_CHARS:
                    reasoning = reasoning[:REASONING_MEMORY_MAX_CHARS - 3] + "..."
                lines.append(
                    f"  [day {entry['day_number']}] {entry['action_type']} "
                    f"-> {outcome}"
                )
                lines.append(f'      you reasoned: "{reasoning}"')
        else:
            lines.append("  (no prior decisions yet)")
        return lines

    def wells_note():
        # Single source for the WELLS note, rendered from WELL_BUILD_COST so the CALM rules
        # block and the thirst WATER MECHANICS exit cannot drift. Constraints/facts only (no
        # wells until built, where/cost, reliability vs a river, anyone can harvest). The
        # move-first procedure and the no-build-on-node clause are DELETED: the world teaches
        # the build-on-node denial via spatial_note (see agent._handle_build).
        cost_str = ", ".join(f"{qty} {r}" for r, qty in WELL_BUILD_COST.items())
        return (
            "  WELLS: there are no wells until an agent builds one. A well is built at your "
            f"current position and costs {cost_str}. Once built, a well yields water, fails "
            "less often than a river, and anyone can harvest it."
        )

    def mechanics_section():
        return [
            "--- HOW THE WORLD WORKS ---",
            "  SPACE: the world is a 2D plane. Every resource node sits at a fixed "
            "location and you occupy your own position. You must be physically present at a "
            "node to act on it. Moving changes your position and spends energy proportional "
            "to the straight-line distance travelled; the distance and move cost to each "
            "node you are not already at are listed in RESOURCE NODES.",
            "  SHELTER: a shelter is built at your CURRENT position and claims that exact "
            "point as yours. The rest bonus applies only while you are AT your own shelter "
            "point.",
            "  WATER: harvest a river node to collect water into your inventory, "
            "THEN drink it. Drinking with no water in inventory fails.",
            "  FOOD: apples can be eaten directly. Potatoes, grain, and meat are "
            "harvested RAW and must be cooked before eating (harvest -> cook -> eat).",
            wells_note(),
            "  DEPLETED nodes yield nothing until they regenerate at the start of "
            "the next day.",
            "  Eating requires naming the exact food item in your inventory "
            "(e.g. apple, potato_cooked).",
            "  ENERGY: every thought (inference) spends energy equal to its token "
            "count, and harvest, build, and cook cost a fixed amount of energy on "
            "top. Eating, drinking, and resting are free to choose and REPLENISH "
            "energy (eating most, resting least). You gain a small basal amount of "
            "energy each tick. You can always think and take free actions even at "
            "zero energy, but you cannot harvest, build, or cook until you can "
            "afford them.",
            "  TENSION: unresolved problems accumulate tension. Failed actions, hunger,",
            "  thirst, lacking shelter, and ignoring messages all raise it. High tension",
            "  narrows what you can perceive of the world and increases the token cost of",
            "  everything you do. Each source of tension is removed only by its own remedy:",
            "  hunger by eating, thirst by drinking, failure by succeeding, lack of shelter",
            "  by building one. Resting slightly lowers tension from every source.",
        ]

    def broadcasts_section():
        lines = ["--- RECENT BROADCASTS (last 10 real minutes) ---"]
        if recent_broadcasts:
            for ts, b in recent_broadcasts:
                lines.append(f"  [{ts.strftime('%H:%M')} UTC] {b['sender_id']}: \"{b['content']}\"")
        else:
            lines.append("  (none in the last 10 minutes)")
        return lines

    def threads_section():
        lines = ["--- ACTIVE THREADS ---"]
        if threads:
            for t in threads:
                participants = ", ".join(t["current_participants"]) or "none"
                privacy = "private" if t["is_private"] else "public"
                lines.append(
                    f"  Thread {t['thread_id']} ({privacy}): participants — {participants}"
                )
        else:
            lines.append("  (none)")
        return lines

    def trades_section():
        lines = ["--- PENDING TRADE PROPOSALS FOR YOU ---"]
        if incoming_trades:
            for t in incoming_trades:
                offering   = _fmt_resources(t["resources_offered"])
                requesting = _fmt_resources(t["resources_requested"])
                tokens     = t["tokens_offered"]
                token_str  = f" + {tokens} tokens" if tokens else ""
                lines.append(
                    f"  [ID: {t['transaction_id']}] From {t['proposer_id']}: "
                    f"offering {offering}{token_str}, requesting {requesting}"
                )
        else:
            lines.append("  (none)")
        return lines

    def dm_section():
        lines = ["--- PENDING DIRECT MESSAGE PROPOSALS FOR YOU ---"]
        if dm_proposals:
            for p in dm_proposals:
                lines.append(
                    f"  [ID: {p['proposal_id']}] From {p['proposer_id']}: "
                    f"proposed start {p['proposed_start_time']}, "
                    f"expected duration {p['expected_duration_minutes']} minutes"
                )
        else:
            lines.append("  (none)")
        return lines

    def directive_section():
        return directive_lines()

    # ------------------------------------------------------- exit renderers
    # Full-detail renderers for the resolution path of each dominant source
    # (THE EXIT RULE). Keys match TENSION_RELEVANCE_MAP values.

    FOOD_NODE_TYPES  = ("apple", "potato", "grain", "hunting")
    WATER_NODE_TYPES = ("river", "well")

    def inventory_edibles_section():
        lines = ["--- FOOD YOU ARE HOLDING ---"]
        for item in edibles_held:
            lines.append(f"  {item}: {inventory[item]} (can be eaten right now)")
        for item in raw_held:
            lines.append(f"  {item}: {inventory[item]} (RAW — must be cooked before eating)")
        if not edibles_held and not raw_held:
            lines.append("  (no food held — harvest a food node)")
        return lines

    def inventory_water_section():
        lines = ["--- WATER YOU ARE HOLDING ---"]
        water_qty = inventory.get("water", 0)
        if water_qty > 0:
            lines.append(f"  water: {water_qty} (can be drunk right now)")
        else:
            lines.append("  (no water held — harvest a water source first)")
        return lines

    def mechanics_eating_section():
        return [
            "--- FOOD MECHANICS ---",
            "  FOOD: apples can be eaten directly. Potatoes, grain, and meat are "
            "harvested RAW and must be cooked before eating (harvest -> cook -> eat).",
            "  The distance and move cost to each food node you are not already at are "
            "shown in FOOD NODES.",
            "  Eating requires naming the exact food item in your inventory "
            "(e.g. apple, potato_cooked).",
        ]

    def mechanics_water_section():
        return [
            "--- WATER MECHANICS ---",
            "  WATER: harvest a river node to collect water into your inventory, "
            "THEN drink it. Drinking with no water in inventory fails.",
            "  The distance and move cost to each water node you are not already at are "
            "shown in WATER NODES.",
            wells_note(),
        ]

    def shelter_requirements_section():
        lines = [
            "--- SHELTER: BUILD REQUIREMENTS ---",
            f"  Your shelter status: {model['shelter_status']}",
        ]
        for tier, costs in SHELTER_BUILD_COSTS.items():
            cost_str = ", ".join(f"{qty} {r}" for r, qty in costs.items())
            lines.append(f"  build {tier} shelter requires: {cost_str}")
        lines.append("  improved shelter requires an existing basic shelter first.")
        lines.append("  A shelter is built at your CURRENT position; the rest bonus applies "
                     "only while you are at your own shelter point.")
        held = {r: inventory.get(r, 0)
                for costs in SHELTER_BUILD_COSTS.values() for r in costs}
        lines.append("  You are holding: "
                     + ", ".join(f"{q} {r}" for r, q in sorted(held.items())))
        return lines

    def pending_messages_section():
        return trades_section() + [""] + dm_section()

    EXIT_RENDERERS = {
        "nodes_food":           lambda: nodes_section(FOOD_NODE_TYPES, "--- FOOD NODES ---"),
        "nodes_water":          lambda: nodes_section(WATER_NODE_TYPES, "--- WATER NODES ---"),
        "inventory_edibles":    inventory_edibles_section,
        "inventory_water":      inventory_water_section,
        "mechanics_eating":     mechanics_eating_section,
        "mechanics_water":      mechanics_water_section,
        "last_actions":         last_actions_section,
        "shelter_requirements": shelter_requirements_section,
        "pending_messages":     pending_messages_section,
    }

    def exit_block():
        """The dominant source's resolution path, rendered in full detail."""
        lines = []
        for key in TENSION_RELEVANCE_MAP[tension_dominant]:
            lines.append("")
            lines.extend(EXIT_RENDERERS[key]())
        return lines

    # ------------------------------------------------------------- summaries
    # One-line stand-ins for sections unrelated to the dominant source
    # (STRESSED band).

    def broadcasts_truncated_section():
        lines = ["--- RECENT BROADCASTS (3 most recent) ---"]
        if recent_broadcasts:
            for ts, b in recent_broadcasts[-3:]:
                content = " ".join(b["content"].split())
                if len(content) > 60:
                    content = content[:57] + "..."
                lines.append(f"  [{ts.strftime('%H:%M')} UTC] {b['sender_id']}: \"{content}\"")
        else:
            lines.append("  (none in the last 10 minutes)")
        return lines

    failed_recent = sum(1 for a in last_actions if not a["succeeded"])
    SECTION_SUMMARIES = {
        "inventory":    f"--- INVENTORY --- ({len(inventory)} item types held)",
        "skills":       f"--- SKILLS --- ({len(skills)} skills recorded)",
        "actions":      "--- AVAILABLE ACTIONS --- (harvest, cook, eat, drink, "
                        "build, craft, trade, message, rest)",
        "nodes":        f"--- RESOURCE NODES --- ({len(nodes)} nodes exist)",
        "experience":   f"--- YOUR EXPERIENCE SO FAR --- ({len(lifetime_totals)} action types attempted)",
        "last_actions": f"--- YOUR LAST 8 ACTIONS --- ({len(last_actions)} recent, {failed_recent} failed)",
        "mechanics":    "--- HOW THE WORLD WORKS --- (full rules hidden while tense)",
        "threads":      f"--- ACTIVE THREADS --- ({len(threads)} threads exist)",
        "trades":       f"--- PENDING TRADE PROPOSALS FOR YOU --- ({len(incoming_trades)} pending)",
        "dm":           f"--- PENDING DIRECT MESSAGE PROPOSALS FOR YOU --- ({len(dm_proposals)} pending)",
    }

    # ---------------------------------------------------------------- assemble
    # The tunnel: a deterministic post-pass keyed to band and dominant source.
    header = [
        f"=== SITUATION REPORT — DAY {day},  {elapsed:.1f} / {DAY_LENGTH_MINUTES} minutes elapsed ===",
    ]

    base_section_order = [
        ("inventory",    inventory_section),
        ("skills",       skills_section),
        ("actions",      actions_section),
        ("nodes",        nodes_section),
        ("experience",   experience_section),
        ("last_actions", last_actions_section),
        ("mechanics",    mechanics_section),
        ("broadcasts",   broadcasts_section),
        ("threads",      threads_section),
        ("trades",       trades_section),
        ("dm",           dm_section),
    ]

    parts = list(header)

    if effective_band == "CALM":
        # Full situation report — identical to Run 2's prompt. Also the FLAT
        # arm's behaviour at every band (post-pass skipped). recent_decisions
        # (reasoning memory) is inserted right after status as CORE memory.
        for _, build in [("status", status_section),
                         ("recent_decisions", recent_decisions_section)] \
                        + base_section_order \
                        + [("directive", directive_section)]:
            parts.append("")
            parts.extend(build())

    elif effective_band == "STRESSED":
        parts.append("")
        parts.extend(status_section())
        # CORE memory: always shown, never compressed (FORK A2). Sits with
        # status, above the attention-narrowing banner.
        parts.append("")
        parts.extend(recent_decisions_section())
        parts.append("")
        parts.append(STRESSED_BANNER.format(dominant=tension_dominant))
        # The dominant source's sections, full detail, directly under status.
        parts.extend(exit_block())
        # Everything else compresses to one-line summaries; broadcasts
        # truncate to the 3 most recent, single line each.
        superseded = _EXIT_SUPERSEDES[tension_dominant]
        parts.append("")
        for name, _ in base_section_order:
            if name in superseded:
                continue
            if name == "broadcasts":
                parts.extend(broadcasts_truncated_section())
            else:
                parts.append(SECTION_SUMMARIES[name])
        parts.append("")
        parts.extend(directive_section())

    else:  # TUNNEL
        parts.append("")
        parts.extend(status_section())
        # CORE memory: always shown, never compressed (FORK A2). This is the
        # arm/band where behavioral consistency matters most, so reasoning
        # memory is preserved in full even as everything peripheral collapses.
        parts.append("")
        parts.extend(recent_decisions_section())
        parts.append("")
        parts.append(TUNNEL_BANNER.format(dominant=tension_dominant))
        # ONLY the sections relevant to resolving the dominant source.
        parts.extend(exit_block())
        parts.append("")
        parts.extend(directive_section())

    return "\n".join(parts)
