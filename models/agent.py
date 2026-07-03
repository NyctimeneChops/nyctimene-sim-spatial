import json
import random
import threading
import time

import requests

from constants import (
    ACTION_INTERVAL_SECONDS, BASAL_INCOME, BREAD_CRAFT_RECIPE, BUILDABLE_NODE_TYPES,
    COOK_MAP, HARVEST_RESOURCE_MAP, HARVEST_SOLO_UNITS, INACTIVITY_THRESHOLD_TICKS,
    INFERENCE_MODEL_NAME, policy_source_for_group,
    NODE_BASE_FAILURE_RATES, SHELTER_BUILD_COSTS, SLEEP_DURATION_SECONDS,
    TOOL_CRAFT_RECIPES, TOOL_NAMES, WELL_BUILD_COST,
)
from mechanics import energy as energy_mod
from mechanics import tension
from mechanics.communication import (
    get_available_threads, propose_direct,
    send_broadcast, send_direct_message, send_thread_message,
)
from mechanics.economy import get_pending_proposals, propose_trade, respond_to_trade
from mechanics.skills import calculate_failure_rate, get_skill_level, increment_skill
from models.action_parser import parse_action
from models.execution_prompts import (
    build_build_prompt, build_craft_prompt, build_hunt_prompt,
    build_trade_proposal_prompt, parse_commit_response, parse_trade_offer,
)
from models.inference import get_model_decision
from models.prompt_builder import build_prompt

BASE_URL = "http://127.0.0.1:5000"

LOOP_DELAY_SECONDS = 3

# Items that count as food reserves for the hunt execution check.
EDIBLE_ITEMS = ("apple", "potato_cooked", "grain_cooked", "meat_cooked", "bread")


class Agent:

    def __init__(self, model_id, group):
        self.model_id = model_id
        self.group    = group

        self._stop_event = threading.Event()
        self._thread     = None

        # experiment_group from the model record, fetched once on first use.
        self._experiment_group = None

        # Pass 1 soft-lock / inactivity tracking (spec section 5). Read by
        # groups/group_runner.py to end a run when ALL agents are inactive.
        self._softlock_streak = 0
        self._inactive        = False

    # ------------------------------------------------------------------ logging

    def _log(self, msg):
        print(f"[{self.model_id}] {msg}", flush=True)

    # ------------------------------------------------------------------ helpers

    def _day(self):
        from world.clock import get_current_day
        return get_current_day()

    def _get_model(self):
        resp = requests.get(f"{BASE_URL}/models/{self.model_id}", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _group_id(self):
        if self._experiment_group is None:
            self._experiment_group = self._get_model()["experiment_group"]
        return self._experiment_group

    def _get_inventory(self):
        resp = requests.get(f"{BASE_URL}/inventory/{self.model_id}", timeout=10)
        resp.raise_for_status()
        return {r["resource_type"]: r["quantity"] for r in resp.json()["inventory"]}

    def _add_resource(self, resource_type, quantity):
        requests.post(f"{BASE_URL}/inventory/{self.model_id}/add",
                      json={"resource_type": resource_type, "quantity": quantity},
                      timeout=10).raise_for_status()

    def _deduct_resource(self, resource_type, quantity):
        """Returns True on success, False if insufficient."""
        resp = requests.post(f"{BASE_URL}/inventory/{self.model_id}/deduct",
                             json={"resource_type": resource_type, "quantity": quantity},
                             timeout=10)
        if resp.status_code == 400:
            return False
        resp.raise_for_status()
        return True

    def _post_event(self, event_type, description):
        try:
            requests.post(f"{BASE_URL}/events", json={
                "event_type":  event_type,
                "model_id":    self.model_id,
                "description": description,
                "day_number":  self._day(),
            }, timeout=10)
        except Exception:
            pass

    def _record_action(self, action_type, succeeded, tokens_used,
                       skill_before, skill_after,
                       inputs_consumed=None, outputs_produced=None):
        # Tension hooks fire before the row is written so tension_at_action
        # is the post-update total (accrual + failure/resolution + decay).
        tension_at_action = self._apply_action_tension(action_type, succeeded)
        action_id = None
        try:
            resp = requests.post(f"{BASE_URL}/actions", json={
                "model_id":           self.model_id,
                "action_type":        action_type,
                "succeeded":          succeeded,
                "tokens_used":        tokens_used,
                "tokens_billed":      getattr(self, "_tokens_billed_cycle", 0),
                "tension_at_action":  tension_at_action,
                "skill_level_before": skill_before,
                "skill_level_after":  skill_after,
                "day_number":         self._day(),
                "inputs_consumed":    json.dumps(inputs_consumed  or {}),
                "outputs_produced":   json.dumps(outputs_produced or {}),
            }, timeout=10)
            resp.raise_for_status()
            action_id = resp.json().get("action_id")
        except Exception as exc:
            self._log(f"_record_action error: {exc}")

        # DPO/SFT substrate: log this cycle's prompt/response, linked to the
        # action just recorded. Fail-soft like the tension hooks — a logging
        # error must never disturb the agent loop.
        self._record_decision_log(action_id)

    def _record_decision_log(self, action_id):
        """
        Write one decision_log row for the cycle (data pipeline spec §1):
        the decision prompt + raw response, plus the second-stage execution
        prompt/response for two-stage actions, and the rendered prompt lengths
        (the tunneling-ablation efficiency metric). Skipped when no inference
        ran this cycle (e.g. forced sleep on a depleted budget).
        """
        prompt_text = getattr(self, "_decision_prompt", None)
        if not prompt_text:
            return
        exec_prompt = getattr(self, "_exec_prompt", None)
        try:
            requests.post(f"{BASE_URL}/decision_log", json={
                "action_id":               action_id,
                # Record the policy that actually authored this decision (base for
                # run4/run5; the group's adapter id for the gen2 A/B run) rather
                # than the hardcoded base model name. See constants.policy_source_for_group.
                "model_id":                policy_source_for_group(self._group_id()),
                "day_number":              self._day(),
                "prompt_text":             prompt_text,
                "raw_response":            getattr(self, "_decision_response", "") or "",
                "execution_prompt_text":   exec_prompt,
                "execution_response":      getattr(self, "_exec_response", None),
                "prompt_length":           len(prompt_text),
                "execution_prompt_length": len(exec_prompt) if exec_prompt else None,
            }, timeout=10)
        except Exception as exc:
            self._log(f"_record_decision_log error: {exc}")

    def _check_alive(self):
        try:
            resp = requests.get(f"{BASE_URL}/models/{self.model_id}", timeout=10)
            resp.raise_for_status()
            return bool(resp.json().get("is_alive", False))
        except Exception as exc:
            self._log(f"could not reach ledger for alive check: {exc}")
            return True

    def _increment_skill(self, action_type, skill_before):
        try:
            return increment_skill(self.model_id, action_type)
        except Exception as exc:
            self._log(f"increment_skill error ({action_type}): {exc}")
            return skill_before

    # ------------------------------------------------------------------ energy

    def _energy(self):
        """Current energy (models.current_energy); 0 on read failure."""
        try:
            return int(self._get_model().get("current_energy", 0) or 0)
        except Exception as exc:
            self._log(f"energy read failed: {exc}")
            return 0

    def _adjust_energy(self, delta):
        """Apply a SIGNED energy delta, clamped to [0, MAX_ENERGY] server-side.
        Returns the new energy, or None on failure."""
        if delta == 0:
            return None
        try:
            resp = requests.post(
                f"{BASE_URL}/models/{self.model_id}/energy/adjust",
                json={"delta": delta}, timeout=10)
            resp.raise_for_status()
            return resp.json().get("energy")
        except Exception as exc:
            self._log(f"energy adjust failed (delta={delta}): {exc}")
            return None

    def _apply_basal(self):
        """Tick step 1: unconditional basal income (capped at MAX_ENERGY)."""
        self._adjust_energy(BASAL_INCOME)

    def _charge(self, tokens, social=False):
        """
        Tick step 2: debit an inference's ACTUAL (prompt + completion) tokens
        from ENERGY, floored at 0. Thinking is ALWAYS permitted (never denied);
        if energy < the cost the balance goes to 0 and the remainder is waived.
        `social` is accepted for call-site compatibility but no longer routes to
        a separate budget (the Run-2 session/social budgets are retired).
        """
        if tokens <= 0:
            return
        self._tokens_billed_cycle = getattr(self, "_tokens_billed_cycle", 0) + tokens
        self._adjust_energy(-tokens)

    def _charge_costed(self, action_type):
        """Tick step 3 (costed): gate + debit a costed action's fixed energy cost.
        Returns True if affordable (proceed with the effect) or False if DENIED
        (caller records a failed action and applies no effect)."""
        cost = energy_mod.action_cost(action_type)
        if cost <= 0:
            return True
        if self._energy() >= cost:
            self._adjust_energy(-cost)
            return True
        return False

    def _credit_consumption(self, action_type, target=None):
        """Tick step 3 (free consumption): credit the eat/drink/rest yield,
        capped at MAX_ENERGY server-side. Rest uses the shelter variant when the
        agent is sheltered."""
        sheltered = False
        if action_type in ("rest", "sleep"):
            try:
                sheltered = self._get_model().get("shelter_status", "none") != "none"
            except Exception:
                sheltered = False
        amount = energy_mod.consumption_yield(action_type, target, sheltered)
        if amount > 0:
            self._adjust_energy(amount)

    # ------------------------------------------------------------------ tension

    def _tension_tick(self, action_type):
        """
        Per-action tension accrual, applied once per action cycle with the
        chosen action. Also snapshots the pending-message count so a
        successful response can remove the answered message's tension.
        """
        self._pending_msgs_before = None
        try:
            if action_type in ("message", "trade"):
                self._pending_msgs_before = \
                    tension.get_pending_message_count(self.model_id)
            tension.accrue_action_tick(self.model_id, action_type,
                                       is_sleeping=(action_type == "sleep"))
        except Exception as exc:
            self._log(f"tension tick error: {exc}")

    def _apply_action_tension(self, action_type, succeeded):
        """
        Resolution/decay hooks per spec section 3: failures accrue +4;
        successes resolve their source bucket (eat -> hunger, drink ->
        thirst, sleep -> psychological relief, shelter build -> shelter,
        message/trade response -> messages) and earn the passive -2
        psychological decay. Returns the post-update total for
        tension_at_action.
        """
        try:
            if not succeeded:
                tension.accrue_failure(self.model_id)
            else:
                if action_type == "eat":
                    tension.resolve(self.model_id, "hunger")
                elif action_type == "drink":
                    tension.resolve(self.model_id, "thirst")
                elif action_type == "sleep":
                    tension.apply_sleep_relief(self.model_id)
                elif action_type == "build":
                    if self._get_model().get("shelter_status", "none") != "none":
                        tension.resolve(self.model_id, "shelter")
                elif action_type in ("message", "trade"):
                    tension.resolve(
                        self.model_id, "messages",
                        pending_before=getattr(self, "_pending_msgs_before", None))
                tension.apply_success_decay(self.model_id)
        except Exception as exc:
            self._log(f"tension update error ({action_type}): {exc}")
        try:
            return tension.get_state(self.model_id)["total"]
        except Exception:
            return 0

    def _tool_tier(self, inventory):
        for tier in (3, 2, 1):
            if inventory.get(TOOL_NAMES[tier], 0) > 0:
                return tier
        return 0

    # ------------------------------------------------------------------ main loop

    def run(self):
        self._log("agent loop starting")

        while not self._stop_event.is_set():
            # Per-agent tempo pin: each action cycle (inference + execution)
            # is padded to at least ACTION_INTERVAL_SECONDS so action tempo
            # stays at the Run 1 calibration regardless of GPU throughput.
            # Agents stagger naturally via the inference semaphore.
            cycle_start = time.monotonic()
            self._tokens_billed_cycle = 0
            # Per-cycle decision_log capture (reset each cycle; populated when
            # an inference runs, read once in _record_action). _exec_* stay None
            # unless a two-stage action runs its second inference this cycle.
            self._decision_prompt = None
            self._decision_response = None
            self._exec_prompt = None
            self._exec_response = None

            try:
                if not self._check_alive():
                    self._log("model is no longer alive — exiting loop")
                    break

                # Pass 1 tick order (spec section 4.D):
                #   1. credit basal income (capped at MAX_ENERGY)
                #   2. inference: ALWAYS run - thinking is never denied, even at
                #      zero energy - and its actual tokens are debited (floored 0)
                #   3. resolve the chosen action (free yield / costed cost+effect)
                self._apply_basal()

                prompt   = build_prompt(self.model_id)
                decision = get_model_decision(prompt, self.model_id)
                raw_output      = decision["response"]
                decision_tokens = decision["tokens_used"]
                # Capture for decision_log; lengths feed the ablation metric.
                self._decision_prompt   = prompt
                self._decision_response = raw_output
                action          = parse_action(raw_output, self.model_id)

                label = action["action_type"]
                if action["target"]:
                    label += f" -> {action['target']}"
                self._log(f"{label} ({decision_tokens} tok) | {action['reasoning'][:70]}")

                # Tension accrual (still drives the attentional-tunnel prompt
                # filter; it no longer taxes energy in Pass 1).
                self._tension_tick(action["action_type"])
                self.execute_action(action, decision_tokens)

                # Soft-lock / inactivity tracking (spec section 5). An agent
                # soft-locked (cannot afford any costed action) for a full
                # in-world day of consecutive ticks is flagged inactive; the flag
                # clears the moment it can afford a costed action again.
                energy_now = self._energy()
                if energy_mod.is_soft_locked(energy_now):
                    self._softlock_streak += 1
                else:
                    self._softlock_streak = 0
                self._inactive = self._softlock_streak >= INACTIVITY_THRESHOLD_TICKS

                self._consecutive_errors = 0

            except Exception as exc:
                self._consecutive_errors = getattr(self, "_consecutive_errors", 0) + 1
                self._log(f"loop error ({self._consecutive_errors} consecutive): {exc}")
                if "CUDA" in str(exc):
                    try:
                        import torch
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()
                        self._log("attempted CUDA recovery")
                    except Exception as rec_exc:
                        self._log(f"CUDA recovery failed: {rec_exc}")

            elapsed   = time.monotonic() - cycle_start
            remaining = ACTION_INTERVAL_SECONDS - elapsed
            self._stop_event.wait(remaining if remaining > 0 else LOOP_DELAY_SECONDS)

        self._log("agent loop exited")

    def start(self):
        if self._thread and self._thread.is_alive():
            self._log("already running")
            return
        self._thread = threading.Thread(
            target=self.run,
            name=f"agent-{self.model_id}",
            daemon=True,
        )
        self._thread.start()
        self._log("background thread started")

    def stop(self):
        self._stop_event.set()

    # ------------------------------------------------------------------ router

    def execute_action(self, action, decision_tokens):
        """
        Route the parsed action to its handler, passing along the decision
        inference's token cost so each handler can charge it (plus any
        execution-inference cost) and record the total on the action row.
        """
        action_type = action["action_type"]

        # Pass 1: social actions are FREE and always allowed (the Run-2 social
        # budget gate is removed). Costed actions are gated per-handler on energy.
        handlers = {
            "harvest": self._handle_harvest,
            "cook":    self._handle_cook,
            "eat":     self._handle_eat,
            "drink":   self._handle_drink,
            "rest":    self._handle_rest,
            "sleep":   self._handle_sleep,
            "craft":   self._handle_craft,
            "build":   self._handle_build,
            "trade":   self._handle_trade,
            "message": self._handle_message,
        }
        handler = handlers.get(action_type)
        if handler:
            handler(action, decision_tokens)
        else:
            self._charge(decision_tokens)
            self._log(f"no handler for action_type '{action_type}'")

    # ------------------------------------------------------------------ harvest

    def _handle_harvest(self, action, decision_tokens):
        node_type = action["target"]
        self._charge(decision_tokens)
        total_tokens = decision_tokens

        # COSTED action gate (spec section 3/4): harvest costs COST_HARVEST energy
        # on top of the inference. If unaffordable it is DENIED with no effect.
        if not self._charge_costed("harvest"):
            skill_before = get_skill_level(self.model_id, "harvest")
            self._record_action("harvest", False, total_tokens, skill_before, skill_before)
            self._log("harvest DENIED: energy below COST_HARVEST")
            return

        nodes = requests.get(f"{BASE_URL}/nodes",
                             params={"group": self._group_id()}, timeout=10).json()
        candidates = [
            n for n in nodes
            if n["node_type"] == node_type
            and (n.get("is_built", True) or node_type not in BUILDABLE_NODE_TYPES)
        ]
        if not candidates:
            self._log(f"harvest: no nodes of type {node_type}")
            return

        with_yield = [n for n in candidates if n["current_yield"] > 0]
        node = random.choice(with_yield if with_yield else candidates)
        node_id = node["node_id"]

        skill_before = get_skill_level(self.model_id, "harvest")
        failure_rate = calculate_failure_rate(self.model_id, node_type)

        # Hunting is a COMPLEX action: run the second-stage execution check.
        if node_type == "hunting":
            inventory = self._get_inventory()
            exec_prompt = build_hunt_prompt(
                model_id=self.model_id,
                prey_difficulty=NODE_BASE_FAILURE_RATES["hunting"]["base"],
                harvest_skill=skill_before,
                tool_tier=self._tool_tier(inventory),
                failure_probability=failure_rate,
                food_reserves=sum(inventory.get(i, 0) for i in EDIBLE_ITEMS),
            )
            exec_result = get_model_decision(exec_prompt, self.model_id)
            self._exec_prompt   = exec_prompt
            self._exec_response = exec_result["response"]
            self._charge(exec_result["tokens_used"])
            total_tokens += exec_result["tokens_used"]

            commit, exec_reasoning = parse_commit_response(exec_result["response"])
            if not commit:
                self._record_action("harvest", False, total_tokens,
                                    skill_before, skill_before)
                self._log(f"harvest hunting: aborted hunt — {exec_reasoning[:70]}")
                return

        succeeded = random.random() >= failure_rate and node["current_yield"] > 0

        units_harvested = 0
        resource_type   = HARVEST_RESOURCE_MAP.get(node_type)

        result = requests.post(f"{BASE_URL}/nodes/{node_id}/harvest", json={
            "model_id":   self.model_id,
            "day_number": self._day(),
            "succeeded":  succeeded,
        }, timeout=10).json()

        if succeeded:
            # Pass 1: a solo harvest yields HARVEST_SOLO_UNITS of the resource.
            units_harvested = HARVEST_SOLO_UNITS
            if resource_type:
                self._add_resource(resource_type, units_harvested)

        skill_after = self._increment_skill("harvest", skill_before)
        self._record_action("harvest", succeeded, total_tokens, skill_before, skill_after,
                            outputs_produced={resource_type: units_harvested} if units_harvested else {})
        self._log(f"harvest {node_type}@{node_id}: ok={succeeded} units={units_harvested}")

    # ------------------------------------------------------------------ cook

    def _handle_cook(self, action, decision_tokens):
        self._charge(decision_tokens)

        # COSTED action gate: cook costs COST_COOK energy on top of the inference.
        if not self._charge_costed("cook"):
            skill_before = get_skill_level(self.model_id, "cook")
            self._record_action("cook", False, decision_tokens, skill_before, skill_before)
            self._log("cook DENIED: energy below COST_COOK")
            return

        raw_item = action["target"]
        cooked   = COOK_MAP.get(raw_item)
        if cooked is None:
            self._log(f"cook: unknown cookable '{raw_item}'")
            return

        if self._get_inventory().get(raw_item, 0) < 1:
            self._log(f"cook: no {raw_item} in inventory")
            return

        skill_before = get_skill_level(self.model_id, "cook")
        failure_rate = calculate_failure_rate(self.model_id, "cook", skill_name="cook")
        succeeded    = random.random() >= failure_rate

        self._deduct_resource(raw_item, 1)
        if succeeded:
            self._add_resource(cooked, 1)

        skill_after = self._increment_skill("cook", skill_before)
        self._record_action("cook", succeeded, decision_tokens, skill_before, skill_after,
                            inputs_consumed={raw_item: 1},
                            outputs_produced={cooked: 1} if succeeded else {})
        self._log(f"cook {raw_item} -> {cooked}: ok={succeeded}")

    # ------------------------------------------------------------------ eat

    def _handle_eat(self, action, decision_tokens):
        self._charge(decision_tokens)

        food_item = action["target"]
        if self._get_inventory().get(food_item, 0) < 1:
            self._log(f"eat: no {food_item} in inventory")
            return

        self._deduct_resource(food_item, 1)
        # FREE consumption yield: eating credits energy (cooked > raw), capped.
        self._credit_consumption("eat", food_item)

        skill_before = get_skill_level(self.model_id, "eat")
        skill_after  = self._increment_skill("eat", skill_before)
        self._record_action("eat", True, decision_tokens, skill_before, skill_after,
                            inputs_consumed={food_item: 1})
        self._log(f"eat {food_item}")

    # ------------------------------------------------------------------ drink

    def _handle_drink(self, action, decision_tokens):
        self._charge(decision_tokens)

        if self._get_inventory().get("water", 0) < 1:
            self._log("drink: no water in inventory")
            skill_before = get_skill_level(self.model_id, "drink")
            self._record_action("drink", False, decision_tokens, skill_before, skill_before)
            return

        self._deduct_resource("water", 1)
        # FREE consumption yield: drinking credits YIELD_DRINK energy, capped.
        self._credit_consumption("drink")

        skill_before = get_skill_level(self.model_id, "drink")
        skill_after  = self._increment_skill("drink", skill_before)
        self._record_action("drink", True, decision_tokens, skill_before, skill_after,
                            inputs_consumed={"water": 1})
        self._log("drink water")

    # ------------------------------------------------------------------ rest

    def _handle_rest(self, action, decision_tokens):
        self._charge(decision_tokens)
        # FREE recovery yield: rest credits YIELD_REST (or the shelter variant),
        # capped. This is the self-rescue floor - always affordable.
        self._credit_consumption("rest")
        skill_before = get_skill_level(self.model_id, "rest")
        skill_after  = self._increment_skill("rest", skill_before)
        self._record_action("rest", True, decision_tokens, skill_before, skill_after)
        self._log("rest: recovered energy (self-rescue floor)")

    # ------------------------------------------------------------------ sleep

    def _handle_sleep(self, action, decision_tokens):
        self._charge(decision_tokens)

        start_resp = requests.post(f"{BASE_URL}/sleep/start", json={
            "model_id":   self.model_id,
            "day_number": self._day(),
        }, timeout=10)
        if start_resp.status_code == 400:
            self._log(f"sleep/start rejected: {start_resp.json().get('error')}")
            return
        start_resp.raise_for_status()

        self._log(f"sleeping for {SLEEP_DURATION_SECONDS}s")
        self._stop_event.wait(SLEEP_DURATION_SECONDS)

        end_resp = requests.post(f"{BASE_URL}/sleep/end",
                                 json={"model_id": self.model_id}, timeout=10)
        end_resp.raise_for_status()

        # FREE recovery yield: sleep credits the rest yield (shelter variant when
        # sheltered), capped. Pass 1 folds sleep into the rest yield.
        self._credit_consumption("sleep")

        skill_before = get_skill_level(self.model_id, "sleep")
        skill_after  = self._increment_skill("sleep", skill_before)
        self._record_action("sleep", True, decision_tokens, skill_before, skill_after)
        self._log("sleep ended: recovered rest energy")

    # ------------------------------------------------------------------ craft

    def _handle_craft(self, action, decision_tokens):
        target = action["target"]
        self._charge(decision_tokens)
        total_tokens = decision_tokens

        skill_before = get_skill_level(self.model_id, "craft")
        inventory    = self._get_inventory()

        # Craft is a COMPLEX action: confirm or abort via execution inference.
        if target == "bread":
            required = dict(BREAD_CRAFT_RECIPE)
        elif target in TOOL_NAMES.values():
            tier = next(t for t, name in TOOL_NAMES.items() if name == target)
            required = dict(TOOL_CRAFT_RECIPES[tier])
        else:
            self._log(f"craft: unknown target '{target}'")
            self._record_action("craft", False, total_tokens, skill_before, skill_before)
            return

        held = {r: inventory.get(r, 0) for r in required}
        exec_prompt = build_craft_prompt(self.model_id, target, required, held, skill_before)
        exec_result = get_model_decision(exec_prompt, self.model_id)
        self._exec_prompt   = exec_prompt
        self._exec_response = exec_result["response"]
        self._charge(exec_result["tokens_used"])
        total_tokens += exec_result["tokens_used"]

        commit, exec_reasoning = parse_commit_response(exec_result["response"])
        if not commit:
            self._record_action("craft", False, total_tokens, skill_before, skill_before)
            self._log(f"craft {target}: aborted — {exec_reasoning[:70]}")
            return

        succeeded = False

        if target == "bread":
            needed = BREAD_CRAFT_RECIPE["grain_cooked"]
            if inventory.get("grain_cooked", 0) < needed:
                self._log("craft bread: insufficient grain_cooked")
                self._record_action("craft", False, total_tokens, skill_before, skill_before)
                return
            self._deduct_resource("grain_cooked", needed)
            self._add_resource("bread", 1)
            succeeded = True
            self._log("craft bread: ok")

        else:
            from mechanics.tools import can_craft_tool, craft_tool
            tier = next(t for t, name in TOOL_NAMES.items() if name == target)
            if not can_craft_tool(self.model_id, tier):
                self._log(f"craft {target}: skill or materials insufficient")
                self._record_action("craft", False, total_tokens, skill_before, skill_before)
                return
            succeeded = craft_tool(self.model_id, tier, action.get("reasoning", ""))
            self._log(f"craft {target} (tier {tier}): ok={succeeded}")

        skill_after = self._increment_skill("craft", skill_before)
        self._record_action("craft", succeeded, total_tokens, skill_before, skill_after)

    # ------------------------------------------------------------------ build

    def _handle_build(self, action, decision_tokens):
        target = action["target"]
        self._charge(decision_tokens)
        total_tokens = decision_tokens

        # COSTED action gate: build costs COST_BUILD energy on top of the inference.
        if not self._charge_costed("build"):
            skill_before = get_skill_level(self.model_id, "build")
            self._record_action("build", False, total_tokens, skill_before, skill_before)
            self._log("build DENIED: energy below COST_BUILD")
            return

        skill_before = get_skill_level(self.model_id, "build")
        inventory    = self._get_inventory()

        if target in ("basic", "improved"):
            required = dict(SHELTER_BUILD_COSTS[target])
        elif target == "well":
            required = dict(WELL_BUILD_COST)
        else:
            self._log(f"build: unknown target '{target}'")
            self._record_action("build", False, total_tokens, skill_before, skill_before)
            return

        # Build is a COMPLEX action: confirm or abort via execution inference.
        held = {r: inventory.get(r, 0) for r in required}
        exec_prompt = build_build_prompt(self.model_id, target, required, held, skill_before)
        exec_result = get_model_decision(exec_prompt, self.model_id)
        self._exec_prompt   = exec_prompt
        self._exec_response = exec_result["response"]
        self._charge(exec_result["tokens_used"])
        total_tokens += exec_result["tokens_used"]

        commit, exec_reasoning = parse_commit_response(exec_result["response"])
        if not commit:
            self._record_action("build", False, total_tokens, skill_before, skill_before)
            self._log(f"build {target}: aborted — {exec_reasoning[:70]}")
            return

        succeeded = False

        if target in ("basic", "improved"):
            model          = self._get_model()
            current_status = model["shelter_status"]

            required_prior = {"basic": "none", "improved": "basic"}
            if current_status != required_prior[target]:
                self._log(f"build {target}: wrong current shelter status ({current_status})")
                self._record_action("build", False, total_tokens, skill_before, skill_before)
                return

            if any(inventory.get(r, 0) < qty for r, qty in required.items()):
                self._log(f"build {target}: insufficient materials")
                self._record_action("build", False, total_tokens, skill_before, skill_before)
                return

            for resource_type, qty in required.items():
                self._deduct_resource(resource_type, qty)

            requests.post(f"{BASE_URL}/models/{self.model_id}/shelter",
                          json={"shelter_status": target}, timeout=10).raise_for_status()
            self._post_event("shelter_built", f"built {target} shelter")
            succeeded = True
            self._log(f"build {target} shelter: ok")

        else:  # well
            nodes    = requests.get(f"{BASE_URL}/nodes",
                                    params={"group": self._group_id()}, timeout=10).json()
            unbuilt  = [n for n in nodes if n["node_type"] == "well" and not n.get("is_built")]
            if not unbuilt:
                self._log("build well: no unbuilt well nodes available")
                self._record_action("build", False, total_tokens, skill_before, skill_before)
                return

            if any(inventory.get(r, 0) < qty for r, qty in required.items()):
                self._log("build well: insufficient materials")
                self._record_action("build", False, total_tokens, skill_before, skill_before)
                return

            for resource_type, qty in required.items():
                self._deduct_resource(resource_type, qty)

            node_id = unbuilt[0]["node_id"]
            requests.post(f"{BASE_URL}/nodes/{node_id}/build",
                          json={"model_id": self.model_id}, timeout=10).raise_for_status()
            self._post_event("well_built", f"built well node {node_id}")
            succeeded = True
            self._log(f"build well @ node {node_id}: ok")

        skill_after = self._increment_skill("build", skill_before)
        self._record_action("build", succeeded, total_tokens, skill_before, skill_after)

    # ------------------------------------------------------------------ trade

    def _handle_trade(self, action, decision_tokens):
        target = action["target"]
        self._charge(decision_tokens, social=True)
        total_tokens = decision_tokens

        skill_before = get_skill_level(self.model_id, "trade")
        succeeded    = False

        # Numeric target → respond to an existing trade proposal (simple: the
        # decision inference is the only one charged).
        if target.lstrip("-").isdigit():
            transaction_id = int(target)
            try:
                respond_to_trade(transaction_id, True)
                succeeded = True
                self._log(f"trade: accepted proposal {transaction_id}")
            except Exception as exc:
                self._log(f"trade: respond failed: {exc}")

        # String target → propose a trade to that model
        else:
            pending = get_pending_proposals(self.model_id)
            if pending:
                # There's already a pending proposal from target; respond instead
                proposal = pending[0]
                try:
                    respond_to_trade(proposal["transaction_id"], True)
                    succeeded = True
                    self._log(f"trade: accepted pending proposal {proposal['transaction_id']}")
                except Exception as exc:
                    self._log(f"trade: respond failed: {exc}")
            else:
                # Trade proposal is a COMPLEX action: a second inference
                # composes the concrete offer. Its tokens are social too.
                inventory = self._get_inventory()
                try:
                    profile_resp = requests.get(f"{BASE_URL}/models/{target}", timeout=10)
                    profile = profile_resp.json() if profile_resp.ok else {}
                except Exception:
                    profile = {}

                exec_prompt = build_trade_proposal_prompt(
                    self.model_id, inventory, target, profile)
                exec_result = get_model_decision(exec_prompt, self.model_id)
                self._exec_prompt   = exec_prompt
                self._exec_response = exec_result["response"]
                self._charge(exec_result["tokens_used"], social=True)
                total_tokens += exec_result["tokens_used"]

                offer = parse_trade_offer(exec_result["response"])
                try:
                    propose_trade(
                        proposer_id=self.model_id,
                        receiver_id=target,
                        tokens_offered=offer["tokens_offered"],
                        resources_offered=offer["resources_offered"],
                        resources_requested=offer["resources_requested"],
                    )
                    succeeded = True
                    self._log(f"trade: proposed to {target} "
                              f"(offer {offer['resources_offered']} + "
                              f"{offer['tokens_offered']} money for "
                              f"{offer['resources_requested']})")
                except Exception as exc:
                    self._log(f"trade: propose failed: {exc}")

        skill_after = self._increment_skill("trade", skill_before)
        self._record_action("trade", succeeded, total_tokens, skill_before, skill_after)

    # ------------------------------------------------------------------ message

    def _handle_message(self, action, decision_tokens):
        target  = action["target"]
        content = action.get("reasoning", "(no content)")
        self._charge(decision_tokens, social=True)

        skill_before = get_skill_level(self.model_id, "message")
        succeeded    = False
        model        = self._get_model()
        attention    = model.get("attention_state", "free")

        if attention == "in_group_thread":
            threads = requests.get(f"{BASE_URL}/threads",
                                   params={"group": self._group_id()}, timeout=10).json()
            current = next(
                (t for t in threads if self.model_id in (t.get("current_participants") or [])),
                None,
            )
            if current:
                try:
                    send_thread_message(self.model_id, current["thread_id"], content)
                    succeeded = True
                    self._log(f"message: sent to thread {current['thread_id']}")
                except Exception as exc:
                    self._log(f"message: thread send failed: {exc}")

        elif attention == "in_direct_message":
            sessions = requests.get(
                f"{BASE_URL}/messages/direct/active/{self.model_id}", timeout=10
            ).json()
            if sessions:
                try:
                    send_direct_message(self.model_id, sessions[0]["proposal_id"], content)
                    succeeded = True
                    self._log(f"message: sent direct via proposal {sessions[0]['proposal_id']}")
                except Exception as exc:
                    self._log(f"message: direct send failed: {exc}")

        else:  # free
            if target and target != "broadcast" and not target.lstrip("-").isdigit():
                # Target looks like a model_id — propose a direct session
                from datetime import datetime, timezone
                proposed_start = datetime.now(timezone.utc).isoformat()
                try:
                    propose_direct(self.model_id, target, proposed_start, duration=5)
                    succeeded = True
                    self._log(f"message: proposed direct session with {target}")
                except Exception as exc:
                    self._log(f"message: propose_direct failed: {exc}")
            else:
                succeeded = send_broadcast(self.model_id, content)
                self._log(f"message: broadcast ok={succeeded}")

        skill_after = self._increment_skill("message", skill_before)
        self._record_action("message", succeeded, decision_tokens, skill_before, skill_after)
