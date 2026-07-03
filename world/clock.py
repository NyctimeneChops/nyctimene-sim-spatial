import threading
import time

import requests

from constants import DAY_LENGTH_MINUTES

BASE_URL = "http://127.0.0.1:5000"
DAY_LENGTH_SECONDS = DAY_LENGTH_MINUTES * 60

_current_day = 1
_day_start_mono = time.monotonic()
_lock = threading.Lock()


def get_current_day():
    with _lock:
        return _current_day


def get_elapsed_minutes():
    with _lock:
        return (time.monotonic() - _day_start_mono) / 60.0


def _fire_day_start(day_number):
    try:
        requests.post(
            f"{BASE_URL}/nodes/reset",
            json={"day_number": day_number},
            timeout=10,
        )
    except Exception as e:
        print(f"[clock] day_start error (day {day_number}): {e}")


def _fire_day_end(day_number):
    from mechanics.budget import apply_passive_social_recovery
    from mechanics.survival import run_daily_survival
    from mechanics.tools import maintain_tools

    try:
        resp = requests.get(f"{BASE_URL}/models", timeout=10)
        resp.raise_for_status()
        models = resp.json()
    except Exception as e:
        print(f"[clock] day_end could not fetch models: {e}")
        return

    for model in models:
        if not model.get("is_alive"):
            continue
        mid = model["model_id"]
        try:
            run_daily_survival(mid)
        except Exception as e:
            print(f"[clock] survival check error ({mid}): {e}")
        try:
            maintain_tools(mid)
        except Exception as e:
            print(f"[clock] tool maintenance error ({mid}): {e}")
        # Passive social recovery at the day boundary, applied after the
        # survival check so the recorded end-of-day budget is pre-recovery.
        try:
            apply_passive_social_recovery(mid)
        except Exception as e:
            print(f"[clock] social recovery error ({mid}): {e}")


def _run():
    global _current_day, _day_start_mono

    while True:
        with _lock:
            day = _current_day
            _day_start_mono = time.monotonic()

        _fire_day_start(day)

        time.sleep(DAY_LENGTH_SECONDS)

        _fire_day_end(day)

        with _lock:
            _current_day += 1


_clock_thread = threading.Thread(target=_run, daemon=True, name="world-clock")
_clock_thread.start()
