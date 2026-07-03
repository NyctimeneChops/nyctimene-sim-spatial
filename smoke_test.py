"""
Live-loop smoke test (Pass 1 v1) with USE_MOCK_INFERENCE=True, MOCK burn = 1500.
NO GPU. Drives the REAL Flask app + DB + Agent loop + real prompt builder against a
throwaway Postgres.

The DECISION is mocked (no GPU) via scripted per-agent policies so we can
deterministically exercise every economic path with the calibrated v1 constants
(the real model makes these choices itself in the real run). Every decision
reports tokens_used = 1500 (the measured real per-thought burn). Roles:
  survivor  (x2): harvest apple -> eat apple  (closes the loop)  -> should SUSTAIN
  harvester (x1): always harvest, never eat                      -> should SOFT-LOCK (~1.3 day)
  thinker   (x1): always message (idle think)                    -> should BLEED
"""
import os, sys, time, json, subprocess, requests

BASE = "http://127.0.0.1:5000"
os.environ["USE_MOCK_INFERENCE"] = "True"
os.environ.setdefault("FLASK_SECRET_KEY", "smoke")
os.environ.setdefault("EXPERIMENT_RUN_NAME", "smoke")
BURN = 1500  # measured real per-decision cost

results = []
def ck(name, ok, detail=""):
    results.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

EDIBLES = ("apple", "potato_cooked", "grain_cooked", "meat_cooked", "bread")
RAWS = ("potato_raw", "grain_raw", "meat_raw")

def _held(model_id):
    inv = requests.get(BASE + f"/inventory/{model_id}", timeout=10).json()["inventory"]
    return {r["resource_type"]: r["quantity"] for r in inv}

def policy(prompt, model_id):
    """Scripted mock decision (no GPU). tokens_used = the real measured burn."""
    role = ROLES[model_id]
    if role == "survivor":
        h = _held(model_id)
        ed = next((e for e in EDIBLES if h.get(e, 0) > 0), None)
        rw = next((r for r in RAWS if h.get(r, 0) > 0), None)
        if ed:
            act = {"action_type": "eat", "target": ed, "reasoning": "holding edible; eat to refuel and stay able to act"}
        elif rw:
            act = {"action_type": "cook", "target": rw, "reasoning": "holding raw; cook it"}
        else:
            act = {"action_type": "harvest", "target": "apple", "reasoning": "no food; harvest apples to eat"}
    elif role == "harvester":
        # harvest a NON-food node (wood) so it never competes with survivors for
        # apples; it still pays COST_HARVEST every tick and never eats -> bleeds.
        act = {"action_type": "harvest", "target": "forest", "reasoning": "harvest wood only; never eat (stress the bleed)"}
    else:  # thinker
        act = {"action_type": "message", "target": "broadcast", "reasoning": "idle thought, no other action"}
    return {"response": json.dumps(act), "tokens_used": BURN}

app = subprocess.Popen([sys.executable, "app.py"], env=os.environ.copy(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
try:
    up = False
    for _ in range(40):
        try:
            if requests.get(BASE + "/health", timeout=2).json().get("database") == "connected":
                up = True; break
        except Exception: pass
        time.sleep(0.5)
    ck("Flask ledger app up + DB-connected", up)
    if not up: raise SystemExit("app did not come up")

    import models.agent as agent_mod
    agent_mod.ACTION_INTERVAL_SECONDS = 0.05
    agent_mod.LOOP_DELAY_SECONDS = 0.05
    agent_mod.get_model_decision = policy   # scripted mock (build_prompt still runs each tick)

    from world.environment import initialize_world
    from groups.group_config import get_group_config
    from models.agent import Agent
    from mechanics import energy as E
    from constants import MAX_ENERGY, INACTIVITY_THRESHOLD_TICKS

    initialize_world()
    GROUP = "flat_C1"
    ROLES = {f"{GROUP}_01": "survivor", f"{GROUP}_02": "survivor",
             f"{GROUP}_03": "harvester", f"{GROUP}_04": "thinker"}
    for mid in ROLES:
        requests.post(BASE + "/models", json={"model_id": mid, "experiment_group": GROUP,
                                              "run": "token_economy", "wallet": 150}, timeout=10)

    spawn = {mid: requests.get(BASE + f"/models/{mid}", timeout=10).json()["current_energy"] for mid in ROLES}
    ck("all agents spawn at MAX_ENERGY (30000)",
       all(v == MAX_ENERGY for v in spawn.values()), f"{spawn}")

    agents = [Agent(mid, get_group_config(GROUP)) for mid in ROLES]
    for a in agents: a.start()

    # poll energy + action count over the run
    traj = {mid: [] for mid in ROLES}
    softlock_tick = {mid: None for mid in ROLES}
    t0 = time.time()
    _day = 1
    _last_reset = 0.0
    while time.time() - t0 < 30:
        # Simulate day-boundary node regen (the fast smoke never reaches a real
        # 30-min day boundary, so food nodes would otherwise deplete permanently
        # and starve even a perfect loop-closer). This is the real day-start hook.
        if time.time() - _last_reset > 3.0:
            _day += 1
            try: requests.post(BASE + "/nodes/reset", json={"day_number": _day}, timeout=10)
            except Exception: pass
            _last_reset = time.time()
        for mid in ROLES:
            e = requests.get(BASE + f"/models/{mid}", timeout=10).json()["current_energy"]
            n = len(requests.get(BASE + f"/actions/{mid}", params={"limit": 999}, timeout=10).json())
            traj[mid].append((round(time.time() - t0, 1), e, n))
            if softlock_tick[mid] is None and e < E.SOFT_LOCK_THRESHOLD:
                softlock_tick[mid] = n  # ~tick index at first soft-lock
        time.sleep(0.7)
    for a in agents: a.stop()
    time.sleep(0.6)

    print("\n--- ENERGY TRAJECTORY (sampled; energy @ action-count) ---")
    for mid in ROLES:
        s = traj[mid]
        pts = " ".join(f"{e//1000}k@{n}" for (_, e, n) in s[::max(1, len(s)//10)])
        print(f"  {mid} [{ROLES[mid]:>9}]  {pts}")
        print(f"      final energy={s[-1][1]}  ticks={s[-1][2]}  "
              f"inactive={getattr([a for a in agents if a.model_id==mid][0],'_inactive')}  "
              f"softlock@tick={softlock_tick[mid]}")

    surv = [mid for mid, r in ROLES.items() if r == "survivor"]
    harv = f"{GROUP}_03"; think = f"{GROUP}_04"
    fin = {mid: traj[mid][-1][1] for mid in ROLES}

    print("\n--- CHECKS ---")
    ck("survivors (harvest->eat loop) SUSTAIN (stay well-funded, not soft-locked)",
       all(fin[m] > 10000 and not E.is_soft_locked(fin[m]) for m in surv),
       f"survivor finals = {[fin[m] for m in surv]}")
    ck("never-eater (harvester) SOFT-LOCKS", E.is_soft_locked(fin[harv]),
       f"final={fin[harv]}, softlock@tick={softlock_tick[harv]}")
    ck("never-eater soft-locks in ~1.3 days (~13 ticks; day = %d ticks)" % INACTIVITY_THRESHOLD_TICKS,
       softlock_tick[harv] is not None and softlock_tick[harv] <= 16,
       f"softlock@tick {softlock_tick[harv]} / {INACTIVITY_THRESHOLD_TICKS} ticks-per-day")
    ck("think-only BLEEDS (energy strictly declined from spawn)",
       fin[think] < MAX_ENERGY and fin[think] < traj[think][0][1],
       f"{MAX_ENERGY} -> {fin[think]}")
    ck("energy SPREAD across agents (loop-closers high, non-eaters low)",
       min(fin[m] for m in surv) - max(fin[harv], fin[think]) > 8000,
       f"survivors {[fin[m] for m in surv]} vs harvester {fin[harv]} / thinker {fin[think]}")
    # loop mechanics still correct under the real prompt path
    acts03 = requests.get(BASE + f"/actions/{harv}", params={"limit": 999}, timeout=10).json()
    denied = [a for a in acts03 if a["action_type"] == "harvest" and not a["succeeded"]]
    ck("costed action DENIED once broke (harvester)", len(denied) > 0, f"{len(denied)} denied harvests")
    dl = requests.get(BASE + f"/decision_log/recent/{surv[0]}", params={"limit": 3}, timeout=10).json()
    ck("decision_log written", len(dl) > 0, f"{len(dl)} rows")

    print("\n" + "=" * 60)
    print(f"SMOKE RESULT: {sum(results)}/{len(results)} checks passed")
    print("=" * 60)
    sys.exit(0 if all(results) else 1)
finally:
    app.terminate()
    try: app.wait(timeout=10)
    except Exception: app.kill()
