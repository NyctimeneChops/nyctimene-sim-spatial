import requests

BASE_URL = "http://127.0.0.1:5000"


def get_world_state(group):
    """World snapshot for one experiment group's sealed world."""
    from world.clock import get_current_day
    day = get_current_day()

    models_resp = requests.get(f"{BASE_URL}/models", timeout=10)
    models_resp.raise_for_status()
    alive_models = [
        m for m in models_resp.json()
        if m["is_alive"] and m["experiment_group"] == group
    ]

    nodes_resp = requests.get(f"{BASE_URL}/nodes", params={"group": group}, timeout=10)
    nodes_resp.raise_for_status()

    broadcasts_resp = requests.get(f"{BASE_URL}/messages/broadcast",
                                   params={"group": group}, timeout=10)
    broadcasts_resp.raise_for_status()
    broadcasts_today = [b for b in broadcasts_resp.json() if b.get("day_number") == day]

    threads_resp = requests.get(f"{BASE_URL}/threads", params={"group": group}, timeout=10)
    threads_resp.raise_for_status()

    return {
        "day": day,
        "group": group,
        "alive_models": alive_models,
        "nodes": nodes_resp.json(),
        "broadcasts_today": broadcasts_today,
        "active_threads": threads_resp.json(),
    }


def get_node_state(node_id):
    from world.clock import get_current_day
    resp = requests.get(
        f"{BASE_URL}/nodes/{node_id}",
        params={"day": get_current_day()},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_model_state(model_id):
    model_resp = requests.get(f"{BASE_URL}/models/{model_id}", timeout=10)
    model_resp.raise_for_status()

    skills_resp = requests.get(f"{BASE_URL}/models/{model_id}/skills", timeout=10)
    skills_resp.raise_for_status()

    return {**model_resp.json(), "skills": skills_resp.json()}


def post_event(event_type, day_number, description=None, model_id=None):
    payload = {"event_type": event_type, "day_number": day_number}
    if description is not None:
        payload["description"] = description
    if model_id is not None:
        payload["model_id"] = model_id

    resp = requests.post(f"{BASE_URL}/events", json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


def initialize_world():
    from world.clock import get_current_day
    from world.nodes import initialize_nodes

    created_nodes = initialize_nodes()
    event = post_event(
        event_type="experiment_start",
        day_number=get_current_day(),
        description=f"World initialized with {len(created_nodes)} nodes across {len(set(n['node_type'] for n in created_nodes))} types",
    )
    return {"nodes_created": created_nodes, "event": event}
