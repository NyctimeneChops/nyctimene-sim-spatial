"""
Verification for the Run 3 tension system (see nyctimene_run3_tension_spec.md).

Modeled on verify_token_flow.py: the ledger HTTP API is replaced with an
in-memory fake so no Flask/Postgres is needed; the tension module, agent
hooks, and prompt builder run as-is.

Covers:
  1. 10-action simulation (3 failures, no eats): hunger/thirst climb,
     failures bucket jumps +4, total and band correct.
  2. Eat zeroes ONLY hunger; sleep relief touches ONLY psychological buckets.
  3. The token tax: 100 generated tokens at tension 40 bill 140.
  4. One full Agent.run() cycle: tension_at_action and tokens_billed land on
     the recorded action row, and the budget drains the billed amount.
  5. Three rendered prompts (tension 10 / 45 / 75, dominant hunger):
     CALM full, STRESSED compressed, TUNNEL collapsed — with food nodes and
     held edibles visible in ALL three (THE EXIT RULE).
"""

import os
os.environ["USE_MOCK_INFERENCE"] = "True"

import json
import random
import re
import threading

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
SURVIVAL_HISTORY = {}


def seed():
    for mid in ("group_A_01", "group_A_02", "group_A_03"):
        MODELS[mid] = {
            "model_id": mid, "experiment_group": "group_A", "run": "token_economy",
            "current_stamina": 100, "max_stamina": 100,
            "session_budget": MAX_SESSION_BUDGET, "social_budget": MAX_SOCIAL_BUDGET,
            "token_balance": 0, "shelter_status": "none",
            "days_without_food": 0, "days_without_water": 0,
            "is_alive": True, "attention_state": "free", "is_sleeping": False,
            "tension": 0, "tension_sources": "{}",
        }
        INVENTORY[mid] = {}
        SKILLS[mid] = {}
        SURVIVAL_HISTORY[mid] = []
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
    m = re.fullmatch(r"/survival/([\w]+)", path)
    if m:
        return FakeResponse(list(SURVIVAL_HISTORY.get(m.group(1), [])))
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

    m = re.fullmatch(r"/models/([\w]+)/tension", path)
    if m:
        mid = m.group(1)
        MODELS[mid]["tension"] = body["tension"]
        MODELS[mid]["tension_sources"] = body["tension_sources"]
        return FakeResponse({"tension": body["tension"],
                             "tension_sources": body["tension_sources"]})
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
from mechanics import tension  # noqa: E402
from models.agent import Agent  # noqa: E402
from models.prompt_builder import build_prompt  # noqa: E402


class OneShotEvent(threading.Event):
    """Lets Agent.run() execute exactly one loop iteration (waits return instantly)."""
    def wait(self, timeout=None):
        self.set()
        return True


def fresh_agent(mid):
    agent = Agent(mid, get_group_config("group_A"))
    agent._stop_event = OneShotEvent()
    return agent


def set_tension(mid, sources):
    """Force a model's tension state directly on the fake ledger."""
    full = tension.parse_sources(sources)
    MODELS[mid]["tension"] = tension.total_from_sources(full)
    MODELS[mid]["tension_sources"] = json.dumps(full)


def fmt_state(st):
    s = st["sources"]
    return (f"total={st['total']:3d}  band={st['band']:<8s}  "
            f"hunger={s['hunger']:5.1f} thirst={s['thirst']:5.1f} "
            f"failures={s['failures']:5.1f} shelter={s['shelter']:4.1f} "
            f"messages={s['messages']:4.1f}")


def show(title):
    print()
    print(f"=== {title} ===")


# ---------------------------------------------------------------- 1. 10 actions
show("1. unit sanity: 10 actions, 3 failures (actions 3, 6, 9), no eats")
MID = "group_A_01"
FAIL_AT = {3, 6, 9}
prev_failures = 0.0
for i in range(1, 11):
    tension.accrue_action_tick(MID, "harvest")
    if i in FAIL_AT:
        st = tension.accrue_failure(MID)
        jump = st["sources"]["failures"] - prev_failures
        assert abs(jump - 4.0) < 1e-9, f"failure jump was {jump}, expected +4"
    else:
        st = tension.apply_success_decay(MID)
    prev_failures = st["sources"]["failures"]
    outcome = "FAILED   " if i in FAIL_AT else "succeeded"
    print(f"  action {i:2d} ({outcome}): {fmt_state(st)}")
    assert abs(st["sources"]["hunger"] - 1.5 * i) < 1e-9, "hunger should climb +1.5/action"
    assert abs(st["sources"]["thirst"] - 2.0 * i) < 1e-9, "thirst should climb +2.0/action"
    expected_total = tension.total_from_sources(st["sources"])
    assert st["total"] == expected_total
    assert st["band"] == tension.band_for_total(st["total"])
print("  OK: hunger +1.5/action and thirst +2.0/action (no eats), "
      "failures bucket jumps +4 on each failure, total/band consistent")

# -------------------------------------------- 2. eat / sleep bucket selectivity
show("2. eat zeroes ONLY hunger; sleep relief touches ONLY psychological buckets")
MID2 = "group_A_02"
set_tension(MID2, {"hunger": 30, "thirst": 20, "failures": 10, "shelter": 5, "messages": 5})
print(f"  start:              {fmt_state(tension.get_state(MID2))}")
st = tension.resolve(MID2, "hunger")   # what a successful eat calls
print(f"  after eat resolve:  {fmt_state(st)}")
assert st["sources"]["hunger"] == 0.0
assert st["sources"]["thirst"] == 20.0 and st["sources"]["failures"] == 10.0
assert st["sources"]["shelter"] == 5.0 and st["sources"]["messages"] == 5.0
st = tension.apply_sleep_relief(MID2)  # what a successful sleep calls
print(f"  after sleep relief: {fmt_state(st)}")
assert st["sources"]["thirst"] == 20.0, "sleep must NOT touch thirst (physiological)"
assert st["sources"]["hunger"] == 0.0
assert (st["sources"]["failures"] + st["sources"]["shelter"]
        + st["sources"]["messages"]) == 0.0, "-25 relief should clear 20 psych tension"
print("  OK: eat zeroed only hunger; sleep relief cleared the psychological "
      "buckets and left thirst untouched — you cannot sleep away thirst/hunger")

# ---------------------------------------------------------------- 3. token tax
show("3. token tax: billed = ceil(tokens * (1 + tension/100))")
for tokens, tens, expected in ((100, 40, 140), (100, 0, 100), (100, 100, 200), (81, 33, 108)):
    billed = tension.billed_tokens(tokens, tens)
    print(f"  {tokens} generated tokens at tension {tens:3d} -> billed {billed}")
    assert billed == expected, f"expected {expected}, got {billed}"
print("  OK: 100 generated tokens at tension 40 bill 140")

# ------------------------------------------------- 4. agent cycle record fields
show("4. full Agent.run() cycle: tokens_billed and tension_at_action on the record")
MID3 = "group_A_03"
set_tension(MID3, {"hunger": 30, "thirst": 10})   # total 40 at inference time
s0 = MODELS[MID3]["session_budget"]
fresh_agent(MID3).run()
s1 = MODELS[MID3]["session_budget"]
rec = ACTIONS[-1]
print(f"  action record: {json.dumps({k: rec[k] for k in ('action_type', 'succeeded', 'tokens_used', 'tokens_billed', 'tension_at_action')})}")
print(f"  session budget drained by {s0 - s1} (= tokens_billed, not raw tokens_used)")
assert rec["tokens_used"] == MOCK_TOKENS_USED
assert rec["tokens_billed"] > rec["tokens_used"], "tax must inflate the billed amount"
assert s0 - s1 == rec["tokens_billed"], "budget must drain the BILLED amount"
assert rec["tension_at_action"] == MODELS[MID3]["tension"], \
    "tension_at_action must be the post-update total"
print("  OK: raw and billed both logged; budget drained tokens_billed; "
      "tension_at_action recorded")

# ------------------------------------------------------------- 5. three prompts
show("5. the tunnel: prompts at tension 10 / 45 / 75 (dominant: hunger)")
MID4 = "group_A_02"
INVENTORY[MID4] = {"apple": 2, "potato_raw": 1, "water": 1}
SURVIVAL_HISTORY[MID4] = [
    {"day_number": 1, "tension_end_of_day": 22},
    {"day_number": 2, "tension_end_of_day": 31},
]
scenarios = [
    ("CALM",     {"hunger": 6,  "thirst": 3,  "failures": 1}),    # total 10
    ("STRESSED", {"hunger": 28, "thirst": 10, "failures": 7}),    # total 45
    ("TUNNEL",   {"hunger": 50, "thirst": 15, "failures": 10}),   # total 75
]
prompts = {}
for band, sources in scenarios:
    set_tension(MID4, sources)
    p = build_prompt(MID4)
    prompts[band] = p
    print()
    print(f"--------------- PROMPT AT TENSION {MODELS[MID4]['tension']} ({band}) ---------------")
    print(p)

calm, stressed, tunnel = prompts["CALM"], prompts["STRESSED"], prompts["TUNNEL"]

# THE EXIT RULE: food nodes and held edibles visible in ALL three bands.
for band, p in prompts.items():
    assert "(CALM)" in p or "(STRESSED)" in p or "(TUNNEL)" in p
    assert re.search(r"apple\s+\d+ / \d+ yield remaining", p), \
        f"{band}: food node lines must be visible (EXIT RULE)"
    assert "apple: 2" in p, f"{band}: held edibles must be visible (EXIT RULE)"
    assert "potato_raw" in p, f"{band}: held raw food must be visible (EXIT RULE)"
    assert "cook" in p, f"{band}: cook/eat mechanics must be visible (EXIT RULE)"
    assert "sleep" in p.lower(), f"{band}: sleep must always be listed as available"
    assert "--- YOUR DIRECTIVE ---" in p
    assert "Resolve your tensions and survive as long as you can." in p

# CALM: full Run 2 prompt — every section present, no banner.
for section in ("--- INVENTORY ---", "--- SKILLS ---", "--- RESOURCE NODES ---",
                "--- ACTIVE THREADS ---", "--- HOW THE WORLD WORKS ---",
                "TENSION: unresolved problems accumulate tension"):
    assert section in calm, f"CALM must contain {section}"
assert "You feel tense" not in calm and "Your tension is severe" not in calm
assert "Tension: 10 / 100 (CALM) - yesterday: 31, day before: 22" in calm

# STRESSED: banner + dominant section in full + one-line summaries.
assert "You feel tense. Your attention is narrowing toward: hunger." in stressed
assert "--- FOOD NODES ---" in stressed
assert "--- ACTIVE THREADS --- (0 threads exist)" in stressed
assert "--- SKILLS --- (" in stressed and "--- SKILLS ---\n" not in stressed

# TUNNEL: collapsed — only status + banner + dominant-relevant sections + directive.
assert "Your tension is severe. You can barely think about anything except: hunger" in tunnel
assert "--- FOOD NODES ---" in tunnel
for hidden in ("--- ACTIVE THREADS ---", "--- SKILLS ---", "--- RECENT BROADCASTS",
               "--- HOW THE WORLD WORKS ---", "--- YOUR EXPERIENCE SO FAR"):
    assert hidden not in tunnel, f"TUNNEL must hide {hidden}"
assert len(tunnel) < len(stressed) < len(calm), \
    "prompt must shrink as tension rises"
print()
print("  OK: CALM full, STRESSED compressed with banner + dominant block, "
      "TUNNEL collapsed; food nodes + edibles + cook/eat lines visible in all "
      "three (EXIT RULE); sleep always listed; prompt length strictly shrinks: "
      f"{len(calm)} > {len(stressed)} > {len(tunnel)} chars")

print()
print("=== all tension-system assertions passed ===")
