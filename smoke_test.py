"""
Live-loop smoke test (Pass 1) with USE_MOCK_INFERENCE=True. NO GPU.

Starts the real Flask ledger app as a subprocess against a throwaway Postgres,
then drives a few real Agent threads through the REAL tick loop / execute_action
/ energy ledger / prompt builder, and checks:
  - agents spawn at max_energy
  - the energy ledger applies per tick (basal -> inference debit -> action)
  - costed actions gate on affordability (harvest DENIED when energy < cost)
  - soft-lock and the inactivity flag trigger
  - the run-termination condition (all agents inactive) is reachable
Also captures one REAL built prompt for token-cost measurement.

Env expected: DATABASE_URL (throwaway pg), set by the caller.
"""
import os, sys, time, subprocess, requests

BASE = "http://127.0.0.1:5000"
os.environ["USE_MOCK_INFERENCE"] = "True"
os.environ.setdefault("FLASK_SECRET_KEY", "smoke")
os.environ.setdefault("EXPERIMENT_RUN_NAME", "smoke")

PY = sys.executable
results = []
def ck(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

# ---- 1. start the real Flask app as a subprocess -------------------------
app = subprocess.Popen([PY, "app.py"], env=os.environ.copy(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
try:
    up = False
    for _ in range(40):
        try:
            if requests.get(BASE + "/health", timeout=2).json().get("database") == "connected":
                up = True; break
        except Exception:
            pass
        time.sleep(0.5)
    ck("Flask ledger app is up and DB-connected", up)
    if not up:
        raise SystemExit("app did not come up")

    # ---- 2. speed up the real agent loop (no code change; patch the module
    #         globals the loop reads) so ticks run in ms, not 175s ----------
    import models.agent as agent_mod
    agent_mod.ACTION_INTERVAL_SECONDS = 0.05
    agent_mod.LOOP_DELAY_SECONDS = 0.05

    from world.environment import initialize_world
    from groups.group_config import get_group_config
    from models.agent import Agent
    from models.prompt_builder import build_prompt
    from mechanics import energy as E
    from constants import MAX_ENERGY, INACTIVITY_THRESHOLD_TICKS

    initialize_world()
    GROUP = "flat_C1"
    ids = [f"{GROUP}_{i:02d}" for i in (1, 2, 3)]
    for mid in ids:
        requests.post(BASE + "/models", json={
            "model_id": mid, "experiment_group": GROUP,
            "run": "token_economy", "wallet": 150}, timeout=10)

    m0 = requests.get(BASE + f"/models/{ids[0]}", timeout=10).json()
    ck("agents spawn at max_energy",
       m0["current_energy"] == MAX_ENERGY and m0["max_energy"] == MAX_ENERGY,
       f"current_energy={m0['current_energy']} max_energy={m0['max_energy']}")

    # ---- 3. run the real agent threads briefly ---------------------------
    agents = [Agent(mid, get_group_config(GROUP)) for mid in ids]
    e_start = requests.get(BASE + f"/models/{ids[0]}", timeout=10).json()["current_energy"]
    for a in agents:
        a.start()
    # let them bleed energy via costed actions, soft-lock, then accumulate
    # enough consecutive soft-locked ticks to trip the inactivity flag
    # (INACTIVITY_THRESHOLD_TICKS). The mock never eats, so they never recover.
    deadline = time.time() + 40
    captured_prompt = None
    while time.time() < deadline:
        time.sleep(1)
        if captured_prompt is None:
            try:
                captured_prompt = build_prompt(ids[0])  # a REAL built prompt
            except Exception:
                pass
    for a in agents:
        a.stop()
    time.sleep(0.6)

    # ---- 4. inspect the outcome -----------------------------------------
    e_end = requests.get(BASE + f"/models/{ids[0]}", timeout=10).json()["current_energy"]
    acts = requests.get(BASE + f"/actions/{ids[0]}", params={"limit": 2000}, timeout=10).json()
    COSTED = ("harvest", "cook", "build")
    costed_acts = [a for a in acts if a["action_type"] in COSTED]
    costed_denied = [a for a in costed_acts if not a["succeeded"]]
    ck("energy ledger applied over the run (energy moved from full)",
       e_end != e_start, f"{e_start} -> {e_end}")
    ck("costed action executed at least once (harvest/cook/build)", len(costed_acts) > 0,
       f"{len(costed_acts)} costed actions recorded")
    ck("costed action was DENIED when energy < cost (soft-locked)",
       len(costed_denied) > 0, f"{len(costed_denied)} denied costed actions")
    ck("soft-lock reached (energy below cheapest costed action)",
       E.is_soft_locked(e_end), f"end energy {e_end} < {E.SOFT_LOCK_THRESHOLD}")
    inactive_flags = [getattr(a, "_inactive", False) for a in agents]
    streaks = [getattr(a, "_softlock_streak", 0) for a in agents]
    ck("inactivity flag triggered (>= INACTIVITY_THRESHOLD_TICKS soft-locked)",
       any(inactive_flags), f"inactive={inactive_flags} streaks={streaks} thr={INACTIVITY_THRESHOLD_TICKS}")
    ck("run-termination condition reachable (all agents inactive)",
       all(inactive_flags), f"all_inactive={all(inactive_flags)}")

    # decision_log populated (trainability invariant still holds)
    dl = requests.get(BASE + f"/decision_log/recent/{ids[0]}", params={"limit": 5}, timeout=10).json()
    ck("decision_log is being written", len(dl) > 0, f"{len(dl)} recent decision rows")

    # ---- 5. persist the captured real prompt for token measurement -------
    if captured_prompt:
        with open("_smoke_real_prompt.txt", "w", encoding="utf-8") as f:
            f.write(captured_prompt)
        print(f"\n  real built prompt captured: {len(captured_prompt)} chars "
              f"-> _smoke_real_prompt.txt")
        print("  --- prompt head ---")
        print("\n".join("  " + l for l in captured_prompt.splitlines()[:6]))

    print("\n" + "=" * 60)
    print(f"SMOKE RESULT: {sum(results)}/{len(results)} checks passed")
    print("=" * 60)
    sys.exit(0 if all(results) else 1)
finally:
    app.terminate()
    try:
        app.wait(timeout=10)
    except Exception:
        app.kill()
