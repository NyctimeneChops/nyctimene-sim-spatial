import random
import threading
import time

import requests

import constants
from constants import DAY_LENGTH_MINUTES
from groups.group_config import get_all_group_ids, get_group_config
from models.agent import Agent
from world.environment import initialize_world
from world.placement import place_point   # SPACE pass 1: agent spawn placement

BASE_URL = "http://127.0.0.1:5000"

# Populated by run_experiment; read by stop_experiment.
_agents: list[Agent] = []
_stop_flag = threading.Event()


def initialize_experiment():
    """
    Prepare the world and create all 32 models (8 per group × 4 groups).

    Model IDs follow the pattern '<group_id>_<nn>' e.g. 'tunnel_C1_03'.
    Every model starts with full session/social token budgets (set server-side);
    money (wallet) is set according to each group's config — in Run 4
    every group starts with balance 150.
    """
    initialize_world()

    total = 0
    for group_id in get_all_group_ids():
        config = get_group_config(group_id)

        for i in range(1, config["model_count"] + 1):
            model_id = f"{group_id}_{i:02d}"
            # SPACE pass 1: uniform-random spawn position (seeded RNG). Stored as both
            # the current position and the immutable spawn position (server-side).
            px, py = place_point(random)
            resp = requests.post(f"{BASE_URL}/models", json={
                "model_id":         model_id,
                "experiment_group": group_id,
                "run":              config["run"],
                "wallet":    config["starting_wallet"],
                "pos_x":     px,
                "pos_y":     py,
            }, timeout=10)
            resp.raise_for_status()
            total += 1

    print(f"[runner] initialized {total} models across {len(get_all_group_ids())} groups")


def run_experiment():
    """
    Fetch all alive models from the ledger, create one Agent per model, start
    every agent on its own background thread, then block until either:
      - all agent threads have exited naturally, or
      - EXPERIMENT_DURATION_DAYS of wall-clock time have elapsed from the
        current day as reported by the world clock.

    Calls stop_experiment() before returning so all agents are cleanly halted.
    """
    global _agents
    _agents = []
    _stop_flag.clear()

    from world.clock import get_current_day

    resp = requests.get(f"{BASE_URL}/models", timeout=10)
    resp.raise_for_status()
    models = [m for m in resp.json() if m.get("is_alive")]

    for model in models:
        group_id = model["experiment_group"]
        config   = get_group_config(group_id)
        _agents.append(Agent(model["model_id"], config))

    for agent in _agents:
        agent.start()

    print(f"[runner] started {len(_agents)} agents")

    start_day            = get_current_day()
    experiment_end_secs  = constants.EXPERIMENT_DURATION_DAYS * DAY_LENGTH_MINUTES * 60
    wall_start           = time.monotonic()

    while not _stop_flag.is_set():
        elapsed = time.monotonic() - wall_start

        if elapsed >= experiment_end_secs:
            print(f"[runner] {constants.EXPERIMENT_DURATION_DAYS}-day duration reached — stopping")
            break

        alive_threads = [a for a in _agents if a._thread and a._thread.is_alive()]
        if not alive_threads:
            print("[runner] all agent threads have exited — stopping")
            break

        # Pass 1 (participation economy): a run also ends when ALL agents are
        # INACTIVE - soft-locked (below the cheapest costed action) for a full
        # in-world day of consecutive ticks. Agents no longer die; this is the
        # emergent termination condition alongside the day cap. The flag clears
        # if an agent claws back above the soft-lock threshold.
        if _agents and all(getattr(a, "_inactive", False) for a in _agents):
            print("[runner] all agents INACTIVE (soft-locked >= one day) — stopping")
            break

        days_elapsed = get_current_day() - start_day
        print(f"[runner] day {start_day + days_elapsed} | "
              f"{len(alive_threads)} agents active | "
              f"{int(elapsed // 60)}m elapsed")

        time.sleep(60)

    stop_experiment()


def stop_experiment():
    """
    Signal every agent to exit its loop cleanly after the current iteration.
    Safe to call multiple times.
    """
    _stop_flag.set()
    for agent in _agents:
        agent.stop()
    print(f"[runner] stop signal sent to {len(_agents)} agents")
