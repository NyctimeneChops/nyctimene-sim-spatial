"""
Verification 2: with USE_MOCK_INFERENCE=True, simulate decision cycles and
show that tokens_used flows inference -> agent -> budget drain -> action record.

The ledger HTTP API is replaced with an in-memory fake so no Flask/Postgres
is needed. The agent code itself (loop, handlers, budget charges) runs as-is.
"""

import os
os.environ["USE_MOCK_INFERENCE"] = "True"

import json
import random
import re
import threading
from datetime import datetime, timezone

import requests

from constants import (
    MAX_SESSION_BUDGET, MAX_SOCIAL_BUDGET, MOCK_TOKENS_USED,
    NODE_MAX_YIELDS, SLEEP_SESSION_RECOVERY, SLEEP_SOCIAL_RECOVERY,
    UNITS_PER_HARVEST,
)
from world.nodes import NODE_TYPE_ORDER

# ------------------------------------------------------------------ fake ledger

MODELS = {}
INVENTORY = {}
SKILLS = {}
ACTIONS = []
NODES = {}
TRANSACTIONS = []


def seed():
    for mid in ("group_A_01", "group_A_02"):
        MODELS[mid] = {
            "model_id": mid, "experiment_group": "group_A", "run": "token_economy",
            "current_stamina": 100, "max_stamina": 100,
            "session_budget": MAX_SESSION_BUDGET, "social_budget": MAX_SOCIAL_BUDGET,
            "token_balance": 0, "shelter_status": "none",
            "days_without_food": 0, "days_without_water": 0,
            "is_alive": True, "attention_state": "free", "is_sleeping": False,
        }
        INVENTORY[mid] = {}
        SKILLS[mid] = {}
    for i, ntype in enumerate(NODE_TYPE_ORDER, start=1):
        NODES[i] = {
            "node_id": i, "node_type": ntype, "experiment_group": "group_A",
            "current_yield": 0 if ntype == "well" else NODE_MAX_YIELDS[ntype],
            "max_yield_per_day": NODE_MAX_YIELDS[ntype],
            "is_built": ntype != "well",
        }


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"fake ledger error {self.status_code}: {self._payload}")


def fake_get(url, params=None, timeout=None, **kw):
    params = params or {}
    path = url.replace("http://127.0.0.1:5000", "")

    m = re.fullmatch(r"/models/([\w]+)", path)
    if m:
        mid = m.group(1)
        return FakeResponse({**MODELS[mid], "inventory": dict(INVENTORY[mid])})
    m = re.fullmatch(r"/models/([\w]+)/skills", path)
    if m:
        return FakeResponse(dict(SKILLS[m.group(1)]))
    if path == "/models":
        return FakeResponse(list(MODELS.values()))
    m = re.fullmatch(r"/actions/([\w]+)/summary", path)
    if m:
        return FakeResponse({})
    m = re.fullmatch(r"/survival/([\w]+)", path)
    if m:
        # Run 3 prompt builder reads tension history from here; empty history
        # plus no /tension POST route keeps tension at 0, so this harness
        # still verifies the untaxed Run 2 token flow (billed == raw).
        return FakeResponse([])
    m = re.fullmatch(r"/actions/([\w]+)", path)
    if m:
        rows = [a for a in ACTIONS if a["model_id"] == m.group(1)]
        if "action_type" in params:
            rows = [a for a in rows if a["action_type"] == params["action_type"]]
        if "day" in params:
            rows = [a for a in rows if a["day_number"] == int(params["day"])]
        if "limit" in params:
            rows = rows[-int(params["limit"]):]
        return FakeResponse(rows)
    if path == "/nodes":
        return FakeResponse(list(NODES.values()))
    if path == "/nodes/activity":
        return FakeResponse({})
    if path == "/messages/broadcast":
        return FakeResponse([])
    if path == "/threads":
        return FakeResponse([])
    m = re.fullmatch(r"/transactions/([\w]+)", path)
    if m:
        return FakeResponse([t for t in TRANSACTIONS
                             if m.group(1) in (t["proposer_id"], t["receiver_id"])
                             and t["status"] == params.get("status", t["status"])])
    m = re.fullmatch(r"/messages/direct/proposals/([\w]+)", path)
    if m:
        return FakeResponse([])
    m = re.fullmatch(r"/inventory/([\w]+)", path)
    if m:
        inv = INVENTORY[m.group(1)]
        return FakeResponse({"inventory": [
            {"resource_type": r, "quantity": q} for r, q in inv.items()]})
    return FakeResponse({"error": f"no fake GET route for {path}"}, 404)


def fake_post(url, json=None, timeout=None, **kw):
    body = json or {}
    path = url.replace("http://127.0.0.1:5000", "")

    m = re.fullmatch(r"/models/([\w]+)/budget/deduct", path)
    if m:
        mid = m.group(1)
        col = "session_budget" if body.get("budget_type", "session") == "session" else "social_budget"
        MODELS[mid][col] -= body["amount"]
        return FakeResponse({"session_budget": MODELS[mid]["session_budget"],
                             "social_budget": MODELS[mid]["social_budget"]})
    m = re.fullmatch(r"/models/([\w]+)/budget/recover", path)
    if m:
        mid = m.group(1)
        if body.get("budget_type", "session") == "session":
            MODELS[mid]["session_budget"] = min(
                MODELS[mid]["session_budget"] + body["amount"], MAX_SESSION_BUDGET)
        else:
            MODELS[mid]["social_budget"] = min(
                MODELS[mid]["social_budget"] + body["amount"], MAX_SOCIAL_BUDGET)
        return FakeResponse({"session_budget": MODELS[mid]["session_budget"],
                             "social_budget": MODELS[mid]["social_budget"]})
    m = re.fullmatch(r"/models/([\w]+)/skills", path)
    if m:
        SKILLS[m.group(1)][body["action_type"]] = body["skill_level"]
        return FakeResponse(body)
    m = re.fullmatch(r"/nodes/(\d+)/harvest", path)
    if m:
        node = NODES[int(m.group(1))]
        units = 0
        if body["succeeded"] and node["current_yield"] > 0:
            units = min(UNITS_PER_HARVEST[node["node_type"]], node["current_yield"])
            node["current_yield"] -= units
        return FakeResponse({"units_harvested": units,
                             "yield_after": node["current_yield"]})
    m = re.fullmatch(r"/inventory/([\w]+)/add", path)
    if m:
        inv = INVENTORY[m.group(1)]
        inv[body["resource_type"]] = inv.get(body["resource_type"], 0) + body["quantity"]
        return FakeResponse({"status": "ok"})
    m = re.fullmatch(r"/inventory/([\w]+)/deduct", path)
    if m:
        inv = INVENTORY[m.group(1)]
        if inv.get(body["resource_type"], 0) < body["quantity"]:
            return FakeResponse({"error": "insufficient"}, 400)
        inv[body["resource_type"]] -= body["quantity"]
        return FakeResponse({"status": "ok"})
    if path == "/actions":
        ACTIONS.append(dict(body))
        return FakeResponse({"status": "recorded"}, 201)
    if path == "/events":
        return FakeResponse({"status": "ok"}, 201)
    if path == "/sleep/start":
        MODELS[body["model_id"]]["is_sleeping"] = True
        return FakeResponse({"sleep_id": 1}, 201)
    if path == "/sleep/end":
        model = MODELS[body["model_id"]]
        before_session, before_social = model["session_budget"], model["social_budget"]
        model["session_budget"] = min(before_session + SLEEP_SESSION_RECOVERY, MAX_SESSION_BUDGET)
        model["social_budget"]  = min(before_social  + SLEEP_SOCIAL_RECOVERY,  MAX_SOCIAL_BUDGET)
        model["is_sleeping"] = False
        return FakeResponse({
            "session_budget": model["session_budget"],
            "social_budget": model["social_budget"],
            "session_budget_recovered": model["session_budget"] - before_session,
            "social_budget_recovered": model["social_budget"] - before_social,
        })
    if path == "/transactions/propose":
        TRANSACTIONS.append({**body, "transaction_id": len(TRANSACTIONS) + 1,
                             "status": "pending"})
        return FakeResponse({"transaction_id": len(TRANSACTIONS)}, 201)
    if path == "/nodes/reset":
        return FakeResponse({"status": "ok"})
    return FakeResponse({"error": f"no fake POST route for {path}"}, 404)


requests.get = fake_get
requests.post = fake_post

seed()
random.seed(7)

from groups.group_config import get_group_config  # noqa: E402
from models.agent import Agent  # noqa: E402


class OneShotEvent(threading.Event):
    """Lets Agent.run() execute exactly one loop iteration (waits return instantly)."""
    def wait(self, timeout=None):
        self.set()
        return True


def fresh_agent(mid="group_A_01"):
    agent = Agent(mid, get_group_config("group_A"))
    agent._stop_event = OneShotEvent()
    return agent


def budgets(mid="group_A_01"):
    return MODELS[mid]["session_budget"], MODELS[mid]["social_budget"]


def show(title):
    print()
    print(f"--- {title} ---")


print(f"Mock inference returns a fixed tokens_used of {MOCK_TOKENS_USED} per call.")

# 1. One full decision cycle through Agent.run()
show("1. one decision cycle (Agent.run, mock inference)")
s0, o0 = budgets()
print(f"budgets before: session={s0}  social={o0}")
fresh_agent().run()
s1, o1 = budgets()
print(f"budgets after:  session={s1}  social={o1}")
print(f"session drained by {s0 - s1} (= 1 decision inference)")
print(f"action record:  {json.dumps({k: ACTIONS[-1][k] for k in ('action_type', 'succeeded', 'tokens_used')})}")
assert s0 - s1 == MOCK_TOKENS_USED
assert ACTIONS[-1]["tokens_used"] == MOCK_TOKENS_USED

# 2. Two-stage inference: forced hunting harvest
show("2. complex action (hunt) — decision + execution inference")
s0, _ = budgets()
fresh_agent().execute_action(
    {"action_type": "harvest", "target": "hunting", "reasoning": "test hunt"},
    decision_tokens=MOCK_TOKENS_USED,
)
s1, _ = budgets()
print(f"session drained by {s0 - s1} (= decision {MOCK_TOKENS_USED} + execution {MOCK_TOKENS_USED})")
print(f"action record:  {json.dumps({k: ACTIONS[-1][k] for k in ('action_type', 'succeeded', 'tokens_used')})}")
assert s0 - s1 == 2 * MOCK_TOKENS_USED
assert ACTIONS[-1]["tokens_used"] == 2 * MOCK_TOKENS_USED

# 3. Trade proposal: social budget pays for both inferences
show("3. trade proposal — both inferences charged to SOCIAL budget")
s0, o0 = budgets()
fresh_agent().execute_action(
    {"action_type": "trade", "target": "group_A_02", "reasoning": "test trade"},
    decision_tokens=MOCK_TOKENS_USED,
)
s1, o1 = budgets()
print(f"session drained by {s0 - s1}, social drained by {o0 - o1}")
print(f"action record:  {json.dumps({k: ACTIONS[-1][k] for k in ('action_type', 'succeeded', 'tokens_used')})}")
print(f"proposal made:  {json.dumps({k: TRANSACTIONS[-1][k] for k in ('proposer_id', 'receiver_id', 'tokens_offered', 'resources_requested')})}")
assert s0 - s1 == 0 and o0 - o1 == 2 * MOCK_TOKENS_USED

# 4. Social budget depleted → social action rejected, failure recorded
show("4. social budget <= 0 — social action rejected at agent layer")
MODELS["group_A_01"]["social_budget"] = 0
fresh_agent().execute_action(
    {"action_type": "message", "target": "broadcast", "reasoning": "hello?"},
    decision_tokens=MOCK_TOKENS_USED,
)
print(f"action record:  {json.dumps({k: ACTIONS[-1][k] for k in ('action_type', 'succeeded', 'tokens_used')})}")
print(f"social budget now: {MODELS['group_A_01']['social_budget']} (decision tokens still charged)")
assert ACTIONS[-1]["action_type"] == "message" and ACTIONS[-1]["succeeded"] is False

# 5. Session budget depleted → loop forces sleep, sleep restores budgets
show("5. session budget <= 0 — Agent.run() forces sleep; sleep restores budgets")
MODELS["group_A_01"]["session_budget"] = 0
fresh_agent().run()
s1, o1 = budgets()
print(f"action record:  {json.dumps({k: ACTIONS[-1][k] for k in ('action_type', 'succeeded', 'tokens_used')})}")
print(f"budgets after sleep: session={s1} (+{SLEEP_SESSION_RECOVERY}), social={o1} (capped at {MAX_SOCIAL_BUDGET})")
assert ACTIONS[-1]["action_type"] == "sleep" and ACTIONS[-1]["tokens_used"] == 0
assert s1 == SLEEP_SESSION_RECOVERY

print()
print("=== all assertions passed: tokens_used flows inference -> agent -> budget drain -> action record ===")
