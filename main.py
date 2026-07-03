import os
import sys
import threading
import time

import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from groups.group_config import get_all_group_ids, get_group_config
from groups.group_runner import initialize_experiment, run_experiment, stop_experiment

BASE_URL = "http://127.0.0.1:5000"


# ------------------------------------------------ decision_log logging invariant
# (LOCKED 2026-06-29, decisions/c8_food_acquisition_and_logging_invariant.md)
# Runs 1-3 are permanently untrainable because decision_log was never written and
# nobody noticed until the instances were destroyed. These two assertions make a
# non-logging run die in minute 1 instead of at harvest. Uses the same
# DATABASE_URL the ledger uses (loaded via load_dotenv in main()); no new dep.

def _decision_log_engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set — cannot verify decision_log logging.")
        sys.exit(1)
    return create_engine(url)


def assert_decision_log_table():
    """PRE-FLIGHT. Aborts the run if the decision_log table does not exist."""
    eng = _decision_log_engine()
    with eng.connect() as c:
        exists = c.execute(
            text("SELECT to_regclass('public.decision_log') IS NOT NULL")
        ).scalar()
    if not exists:
        print("FATAL: decision_log table is MISSING. This run would be UNTRAINABLE "
              "(no prompts logged). Apply schema.sql / fix the agent loop before "
              "starting — refusing to run. (See c8_food_acquisition_and_logging_invariant.md)")
        sys.exit(1)
    print("Pre-flight OK: decision_log table present.")


def assert_decision_log_growing(min_rows=1):
    """POST-FIRST-CYCLE. Aborts if no prompt has been logged after the first
    monitoring pass — the agent loop is recording actions but dropping prompts."""
    eng = _decision_log_engine()
    with eng.connect() as c:
        rows = c.execute(text("SELECT count(*) FROM decision_log")).scalar() or 0
    if rows < min_rows:
        print(f"FATAL: {rows} decision_log rows after the first cycle — prompts are "
              f"NOT being logged (the DPO substrate is being lost in real time). "
              f"Stopping the run now rather than discovering this at harvest.")
        sys.exit(1)
    print(f"Logging OK: decision_log is filling ({rows} rows after first cycle).")


# ------------------------------------------------------------------ pre-flight

def _check_health():
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("database") != "connected":
            print(f"ERROR: ledger is reachable but database is not connected: "
                  f"{data.get('database')}")
            sys.exit(1)
        print(f"Ledger reachable. Database: {data['database']}")
    except requests.exceptions.ConnectionError:
        print(f"ERROR: cannot reach ledger at {BASE_URL}. "
              f"Is the Flask app running?")
        sys.exit(1)
    except Exception as exc:
        print(f"ERROR: health check failed: {exc}")
        sys.exit(1)


def _print_startup_summary():
    rows = [
        ("Group",    "Run",           "Money", "Death", "Balance", "Models"),
        ("-" * 9,    "-" * 13,        "-" * 5, "-" * 5, "-" * 7,   "-" * 6),
    ]
    for gid in get_all_group_ids():
        c = get_group_config(gid)
        rows.append((
            gid,
            c["run"],
            "yes" if c["has_tokens"] else "no",
            "yes" if c["has_death"]  else "no",
            str(c["starting_token_balance"]),
            str(c["model_count"]),
        ))
    col_widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    print()
    print("=== Experiment group configuration ===")
    for row in rows:
        print("  " + "  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)))
    print()


# ------------------------------------------------------------------ status

def _fetch_status():
    """
    Returns a dict with current_day, alive counts per group, and today's
    action totals. Returns None if the ledger is temporarily unreachable.
    """
    try:
        from world.clock import get_current_day
        day = get_current_day()

        models_resp = requests.get(f"{BASE_URL}/models", timeout=10)
        models_resp.raise_for_status()
        all_models = models_resp.json()

        alive_by_group = {}
        total_by_group = {}
        for gid in get_all_group_ids():
            group_models  = [m for m in all_models if m["experiment_group"] == gid]
            alive_by_group[gid] = sum(1 for m in group_models if m["is_alive"])
            total_by_group[gid] = len(group_models)

        actions_resp = requests.get(
            f"{BASE_URL}/actions/summary", params={"day": day}, timeout=10
        )
        actions_resp.raise_for_status()
        actions = actions_resp.json()

        return {
            "day":             day,
            "alive_by_group":  alive_by_group,
            "total_by_group":  total_by_group,
            "actions_today":   actions["total"],
            "succeeded_today": actions["succeeded"],
        }
    except Exception:
        return None


def _print_status(status, elapsed_seconds):
    if status is None:
        print("[status] ledger unreachable — skipping update")
        return

    elapsed_min = int(elapsed_seconds // 60)
    print(f"\n[day {status['day']} | {elapsed_min}m elapsed | "
          f"{status['actions_today']} actions today "
          f"({status['succeeded_today']} succeeded)]")

    for gid in get_all_group_ids():
        alive = status["alive_by_group"][gid]
        total = status["total_by_group"][gid]
        bar   = "#" * alive + "." * (total - alive)
        print(f"  {gid:<10}  [{bar}]  {alive}/{total} alive")


def _print_completion_summary(start_time):
    elapsed = int(time.monotonic() - start_time)
    print()
    print("=" * 50)
    print("EXPERIMENT COMPLETE")
    print(f"  Wall-clock runtime: {elapsed // 3600}h {(elapsed % 3600) // 60}m {elapsed % 60}s")

    status = _fetch_status()
    if status:
        print(f"  Final day: {status['day']}")
        print()
        print("  Final survival by group:")
        for gid in get_all_group_ids():
            alive = status["alive_by_group"][gid]
            total = status["total_by_group"][gid]
            print(f"    {gid:<10}  {alive}/{total} alive")

    try:
        all_actions = requests.get(f"{BASE_URL}/actions/summary", timeout=10).json()
        print()
        print(f"  Total actions recorded: {all_actions['total']} "
              f"({all_actions['succeeded']} succeeded)")
    except Exception:
        pass

    print("=" * 50)


# ------------------------------------------------------------------ main

def main():
    load_dotenv()

    print("nyctimene experiment — starting up")
    print()

    _check_health()
    assert_decision_log_table()
    _print_startup_summary()

    expected_models = sum(
        get_group_config(gid)["model_count"] for gid in get_all_group_ids()
    )
    print(f"Initializing experiment (creating world nodes and {expected_models} models)...")
    initialize_experiment()

    models_resp = requests.get(f"{BASE_URL}/models", timeout=10)
    models_resp.raise_for_status()
    model_count = len(models_resp.json())
    print(f"Initialization confirmed: {model_count} models in ledger")
    print()

    print(f"Experiment ready. {model_count} models initialized across "
          f"{len(get_all_group_ids())} groups.")
    print("Type START to begin or anything else to abort: ", end="", flush=True)
    try:
        choice = input().strip()
    except (EOFError, KeyboardInterrupt):
        choice = ""

    if choice != "START":
        print("Aborted.")
        sys.exit(0)

    print()
    print(f"Launching {model_count} agent threads...")
    start_time = time.monotonic()

    experiment_thread = threading.Thread(
        target=run_experiment,
        name="experiment",
        daemon=True,
    )
    experiment_thread.start()

    first_pass = True
    try:
        while experiment_thread.is_alive():
            time.sleep(60)
            if first_pass:
                assert_decision_log_growing()
                first_pass = False
            elapsed = time.monotonic() - start_time
            _print_status(_fetch_status(), elapsed)
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received — stopping experiment cleanly")
        stop_experiment()
        experiment_thread.join(timeout=30)

    _print_completion_summary(start_time)


if __name__ == "__main__":
    main()
