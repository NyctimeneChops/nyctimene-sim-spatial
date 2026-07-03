import requests

BASE_URL = "http://127.0.0.1:5000"

_FALLBACK_RATES = {
    "apple":          3,
    "potato_raw":     2,
    "potato_cooked":  4,
    "grain_raw":      2,
    "grain_cooked":   4,
    "meat_raw":       5,
    "meat_cooked":    8,
    "bread":          6,
    "water":          2,
    "wood":           3,
    "stone":          4,
    "ore":            7,
    "tool_basic":    15,
    "tool_refined":  30,
    "tool_masterwork": 60,
}


def get_token_balance(model_id):
    resp = requests.get(f"{BASE_URL}/models/{model_id}", timeout=10)
    resp.raise_for_status()
    return resp.json()["token_balance"]


def can_afford(model_id, cost):
    return get_token_balance(model_id) >= cost


def propose_trade(proposer_id, receiver_id, tokens_offered, resources_offered, resources_requested):
    resp = requests.post(f"{BASE_URL}/transactions/propose", json={
        "proposer_id":        proposer_id,
        "receiver_id":        receiver_id,
        "tokens_offered":     tokens_offered,
        "resources_offered":  resources_offered,
        "resources_requested": resources_requested,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def respond_to_trade(transaction_id, accepted):
    resp = requests.post(f"{BASE_URL}/transactions/respond", json={
        "transaction_id": transaction_id,
        "accepted":       accepted,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_pending_proposals(model_id):
    resp = requests.get(
        f"{BASE_URL}/transactions/{model_id}",
        params={"status": "pending"},
        timeout=10,
    )
    resp.raise_for_status()
    txs = resp.json()
    return [tx for tx in txs if tx["receiver_id"] == model_id]


def calculate_trade_value(resources):
    """
    Estimate token value of a resources dict using average rates from recent
    accepted transactions. Falls back to hardcoded rates for any resource type
    with no transaction history.
    """
    rates = _market_rates()
    total = 0
    for resource_type, quantity in resources.items():
        rate = rates.get(resource_type, _FALLBACK_RATES.get(resource_type, 5))
        total += rate * quantity
    return total


def _market_rates():
    """
    Derive per-resource token rates from accepted transactions.
    For each accepted transaction where tokens_offered > 0 and resources_offered
    is non-empty, distribute the token value evenly across the offered resources
    to get a per-unit rate, then average across all transactions.
    """
    try:
        resp = requests.get(f"{BASE_URL}/transactions", params={"status": "accepted"}, timeout=10)
        resp.raise_for_status()
        transactions = resp.json()
    except Exception:
        return {}

    rate_samples = {}
    for tx in transactions:
        tokens = tx.get("tokens_offered", 0)
        offered = tx.get("resources_offered") or {}
        if not isinstance(offered, dict):
            continue
        total_units = sum(offered.values())
        if tokens <= 0 or total_units == 0:
            continue
        per_unit = tokens / total_units
        for resource_type, quantity in offered.items():
            if quantity > 0:
                rate_samples.setdefault(resource_type, []).append(per_unit)

    return {
        resource_type: sum(samples) / len(samples)
        for resource_type, samples in rate_samples.items()
    }
