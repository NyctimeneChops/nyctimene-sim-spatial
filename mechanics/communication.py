import requests

BASE_URL = "http://127.0.0.1:5000"


def _get(path, params=None):
    resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _post(path, body):
    resp = requests.post(f"{BASE_URL}{path}", json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _day():
    from world.clock import get_current_day
    return get_current_day()


def send_broadcast(model_id, content):
    """
    Posts a broadcast message if the model's attention state is currently free.
    Returns True on success, False if the model is busy or the ledger rejects it.
    """
    model = _get(f"/models/{model_id}")
    if model.get("attention_state") != "free":
        return False

    resp = requests.post(f"{BASE_URL}/messages/broadcast", json={
        "sender_id":  model_id,
        "content":    content,
        "day_number": _day(),
    }, timeout=10)

    if resp.status_code == 400:
        return False
    resp.raise_for_status()
    return True


def propose_direct(proposer_id, receiver_id, proposed_start_time, duration):
    """
    Proposes a direct message session.
    `proposed_start_time` is an ISO-8601 string; `duration` is minutes.
    Returns the new proposal_id.
    """
    result = _post("/messages/direct/propose", {
        "proposer_id":               proposer_id,
        "receiver_id":               receiver_id,
        "proposed_start_time":       proposed_start_time,
        "expected_duration_minutes": duration,
    })
    return result["proposal_id"]


def respond_direct(proposal_id, accepted):
    """
    Accepts or rejects a direct message proposal.
    Returns the ledger response dict (includes status).
    """
    return _post("/messages/direct/respond", {
        "proposal_id": proposal_id,
        "accepted":    accepted,
    })


def send_direct_message(model_id, proposal_id, content):
    """
    Sends a message within an accepted direct session. Looks up the proposal
    to resolve the receiver, then posts to /messages/direct/send.
    Returns the new message_id.
    """
    proposal = _get(f"/messages/direct/proposal/{proposal_id}")
    proposer_id = proposal["proposer_id"]
    receiver_id = proposal["receiver_id"]
    other_party = receiver_id if model_id == proposer_id else proposer_id

    result = _post("/messages/direct/send", {
        "sender_id":   model_id,
        "receiver_id": other_party,
        "content":     content,
        "day_number":  _day(),
    })
    return result["message_id"]


def create_thread(model_id):
    """
    Creates a new public group thread and joins the creator.
    Returns the new thread_id.
    """
    result = _post("/threads/create", {"creator_id": model_id})
    return result["thread_id"]


def join_thread(model_id, thread_id):
    """
    Joins an existing public thread. Returns the ledger response dict.
    """
    return _post(f"/threads/{thread_id}/join", {"model_id": model_id})


def leave_thread(model_id, thread_id):
    """
    Leaves a thread and frees the model's attention. Returns the ledger response dict.
    """
    return _post(f"/threads/{thread_id}/leave", {"model_id": model_id})


def send_thread_message(model_id, thread_id, content):
    """
    Posts a message to a thread the model is currently participating in.
    Returns the new message_id.
    """
    result = _post(f"/threads/{thread_id}/message", {
        "model_id":   model_id,
        "content":    content,
        "day_number": _day(),
    })
    return result["message_id"]


def cast_vote(model_id, thread_id, vote):
    """
    Casts a privacy vote for a thread (True = close/make private, False = open/make public).
    Returns the updated vote tally dict from the ledger.
    """
    return _post(f"/threads/{thread_id}/vote", {
        "model_id":   model_id,
        "vote":       vote,
        "day_number": _day(),
    })


def get_available_threads(model_id):
    """
    Returns all active public threads the model is not already participating in.
    """
    threads = _get("/threads", params={"model_id": model_id})
    return [
        t for t in threads
        if not t["is_private"] and model_id not in (t["current_participants"] or [])
    ]
