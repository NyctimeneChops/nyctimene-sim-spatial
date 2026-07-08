import requests

from constants import SHELTER_WOOD_COST
from mechanics import tension

BASE_URL = "http://127.0.0.1:5000"


def _get(path, params=None):
    resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _post(path, body):
    resp = requests.post(f"{BASE_URL}{path}", json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


def check_ate_today(model_id):
    """
    Return True if the model has at least one successful eat action recorded
    for today's day number, False otherwise.
    """
    from world.clock import get_current_day
    actions = _get(
        f"/actions/{model_id}",
        params={"day": get_current_day(), "action_type": "eat"},
    )
    return any(a["succeeded"] for a in actions)


def check_drank_today(model_id):
    """
    Return True if the model has at least one successful drink action recorded
    for today's day number, False otherwise.
    """
    from world.clock import get_current_day
    actions = _get(
        f"/actions/{model_id}",
        params={"day": get_current_day(), "action_type": "drink"},
    )
    return any(a["succeeded"] for a in actions)


def check_shelter_maintenance(model_id):
    """
    Attempt to deduct SHELTER_WOOD_COST wood from the model's inventory as
    daily shelter upkeep.

    Returns True and deducts the wood if the model can afford it.
    Returns False without touching inventory if the model has insufficient wood.
    This function is unconditional — callers are responsible for only invoking
    it when the model actually has shelter to maintain.
    """
    inventory_resp = _get(f"/inventory/{model_id}")
    wood = next(
        (row["quantity"] for row in inventory_resp["inventory"]
         if row["resource_type"] == "wood"),
        0,
    )
    if wood < SHELTER_WOOD_COST:
        return False

    deduct_resp = requests.post(
        f"{BASE_URL}/inventory/{model_id}/deduct",
        json={"resource_type": "wood", "quantity": SHELTER_WOOD_COST},
        timeout=10,
    )
    if deduct_resp.status_code == 400:
        # Insufficient wood — race between the inventory read and the deduction.
        return False
    deduct_resp.raise_for_status()
    return True


def _notify_death_witnessed(dead_model_id, experiment_group):
    """
    Witnessing-death tension: every living member of the group a death
    occurred in gets +15. Generic over all deaths; in Run 4 every group has
    death enabled, so this fires within whichever sealed world the death occurs.
    """
    models = _get("/models")
    for m in models:
        if (m["experiment_group"] == experiment_group
                and m.get("is_alive")
                and m["model_id"] != dead_model_id):
            try:
                tension.accrue_death_witnessed(m["model_id"])
            except Exception as exc:
                print(f"[survival] death-witness tension error "
                      f"({m['model_id']}): {exc}")


def run_daily_survival(model_id):
    """
    Run the full end-of-day survival evaluation for a single model and post
    the result to the ledger.

    Steps:
      1. Check whether the model ate and drank today.
      2. If the model has shelter, attempt to collect the wood maintenance cost.
      3. POST /survival/check with all three outcomes so the ledger can update
         consecutive-day counters and apply death if thresholds are breached.
         The check records tension_end_of_day from the models row.
      4. Apply the tension day boundary (overnight failure fade) AFTER the
         end-of-day tension has been recorded.
      5. If the model died, apply witnessing-death tension to its group.

    Returns the ledger's response dict (includes died, death_cause, etc.).
    """
    from world.clock import get_current_day

    ate   = check_ate_today(model_id)
    drank = check_drank_today(model_id)

    model = _get(f"/models/{model_id}")
    has_shelter = model["shelter_status"] != "none"
    shelter_paid = check_shelter_maintenance(model_id) if has_shelter else False

    result = _post("/survival/check", {
        "model_id":                model_id,
        "day_number":              get_current_day(),
        "shelter_maintenance_paid": shelter_paid,
    })

    # SPATIAL CLEANUP: claim lifetime. A shelter that goes UNMAINTAINED (no wood) breaks,
    # and its territorial point-claim DISSOLVES -- setting shelter_status to 'none' clears
    # shelter_x/y, freeing the point (self-cleaning map, no ghost territory). Wired to the
    # existing wood-maintenance signal.
    if has_shelter and not shelter_paid:
        try:
            requests.post(f"{BASE_URL}/models/{model_id}/shelter",
                          json={"shelter_status": "none"}, timeout=10)
        except Exception as exc:
            print(f"[survival] shelter-break/claim-release error ({model_id}): {exc}")

    try:
        tension.day_boundary(model_id)
    except Exception as exc:
        print(f"[survival] tension day-boundary error ({model_id}): {exc}")

    if result.get("died"):
        _notify_death_witnessed(model_id, model["experiment_group"])

    return result
