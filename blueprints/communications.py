from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from constants import MAX_SESSION_BUDGET, SOCIAL_RESTORE_DM
from extensions import db

communications_bp = Blueprint("communications", __name__, url_prefix="/messages")


def _get_model(model_id):
    return db.session.execute(
        text("SELECT model_id, experiment_group, is_alive, attention_state FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).mappings().one_or_none()


@communications_bp.route("/broadcast", methods=["POST"])
def send_broadcast():
    data = request.get_json()

    required = ["sender_id", "content", "day_number"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    sender_id = data["sender_id"]
    model = _get_model(sender_id)

    if model is None:
        return jsonify({"error": "Model not found"}), 404
    if not model["is_alive"]:
        return jsonify({"error": "Model is not alive"}), 400
    if model["attention_state"] != "free":
        return jsonify({
            "error": f"Model attention is not free: currently {model['attention_state']}"
        }), 400

    now = datetime.now(timezone.utc)

    db.session.execute(text("""
        UPDATE models SET attention_state = 'in_broadcast' WHERE model_id = :model_id
    """), {"model_id": sender_id})

    message_id = db.session.execute(text("""
        INSERT INTO communications
            (sender_id, experiment_group, recipient_id, thread_id, content, message_type, timestamp, day_number)
        VALUES
            (:sender_id, :experiment_group, NULL, NULL, :content, 'broadcast', :now, :day_number)
        RETURNING message_id
    """), {
        "sender_id": sender_id,
        "experiment_group": model["experiment_group"],
        "content": data["content"],
        "now": now,
        "day_number": data["day_number"],
    }).scalar()

    db.session.execute(text("""
        UPDATE models SET attention_state = 'free' WHERE model_id = :model_id
    """), {"model_id": sender_id})

    db.session.commit()
    return jsonify({"message_id": message_id}), 201


@communications_bp.route("/direct/propose", methods=["POST"])
def propose_direct():
    data = request.get_json()

    required = ["proposer_id", "receiver_id", "proposed_start_time", "expected_duration_minutes"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    proposer_id = data["proposer_id"]
    receiver_id = data["receiver_id"]

    groups = {}
    for model_id in [proposer_id, receiver_id]:
        model = _get_model(model_id)
        if model is None:
            return jsonify({"error": f"Model not found: {model_id}"}), 404
        if not model["is_alive"]:
            return jsonify({"error": f"Model is not alive: {model_id}"}), 400
        groups[model_id] = model["experiment_group"]

    if groups[proposer_id] != groups[receiver_id]:
        return jsonify({
            "error": f"Cross-group direct message proposal denied: {proposer_id} is in "
                     f"group {groups[proposer_id]} but {receiver_id} is in group "
                     f"{groups[receiver_id]}"
        }), 403

    now = datetime.now(timezone.utc)

    proposal_id = db.session.execute(text("""
        INSERT INTO direct_proposals
            (proposer_id, receiver_id, proposed_start_time, expected_duration_minutes, status, created_at)
        VALUES
            (:proposer_id, :receiver_id, :proposed_start_time, :expected_duration_minutes, 'pending', :now)
        RETURNING proposal_id
    """), {
        "proposer_id": proposer_id,
        "receiver_id": receiver_id,
        "proposed_start_time": data["proposed_start_time"],
        "expected_duration_minutes": data["expected_duration_minutes"],
        "now": now,
    }).scalar()

    db.session.commit()
    return jsonify({"proposal_id": proposal_id}), 201


@communications_bp.route("/direct/respond", methods=["POST"])
def respond_direct():
    data = request.get_json()

    required = ["proposal_id", "accepted"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    proposal_id = data["proposal_id"]
    accepted = data["accepted"]
    now = datetime.now(timezone.utc)

    proposal = db.session.execute(
        text("SELECT * FROM direct_proposals WHERE proposal_id = :id FOR UPDATE"),
        {"id": proposal_id},
    ).mappings().one_or_none()

    if proposal is None:
        return jsonify({"error": "Proposal not found"}), 404
    if proposal["status"] != "pending":
        return jsonify({"error": f"Proposal is already {proposal['status']}"}), 400

    new_status = "accepted" if accepted else "rejected"

    db.session.execute(text("""
        UPDATE direct_proposals
        SET status = :status, responded_at = :now
        WHERE proposal_id = :id
    """), {"status": new_status, "now": now, "id": proposal_id})

    if accepted:
        for model_id in [proposal["proposer_id"], proposal["receiver_id"]]:
            db.session.execute(text("""
                UPDATE models SET attention_state = 'in_direct_message' WHERE model_id = :model_id
            """), {"model_id": model_id})

    db.session.commit()
    return jsonify({"status": new_status})


@communications_bp.route("/direct/send", methods=["POST"])
def send_direct():
    data = request.get_json()

    required = ["sender_id", "receiver_id", "content", "day_number"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    sender_id = data["sender_id"]
    receiver_id = data["receiver_id"]

    groups = {}
    for model_id in [sender_id, receiver_id]:
        model = _get_model(model_id)
        if model is None:
            return jsonify({"error": f"Model not found: {model_id}"}), 404
        if not model["is_alive"]:
            return jsonify({"error": f"Model is not alive: {model_id}"}), 400
        if model["attention_state"] != "in_direct_message":
            return jsonify({
                "error": f"Model {model_id} is not in direct message state"
            }), 400
        groups[model_id] = model["experiment_group"]

    if groups[sender_id] != groups[receiver_id]:
        return jsonify({
            "error": f"Cross-group direct message denied: {sender_id} is in group "
                     f"{groups[sender_id]} but {receiver_id} is in group "
                     f"{groups[receiver_id]}"
        }), 403

    now = datetime.now(timezone.utc)

    message_id = db.session.execute(text("""
        INSERT INTO communications
            (sender_id, experiment_group, recipient_id, thread_id, content, message_type, timestamp, day_number)
        VALUES
            (:sender_id, :experiment_group, :receiver_id, NULL, :content, 'direct', :now, :day_number)
        RETURNING message_id
    """), {
        "sender_id": sender_id,
        "experiment_group": groups[sender_id],
        "receiver_id": receiver_id,
        "content": data["content"],
        "now": now,
        "day_number": data["day_number"],
    }).scalar()

    for model_id in [sender_id, receiver_id]:
        db.session.execute(text("""
            UPDATE models SET attention_state = 'free' WHERE model_id = :model_id
        """), {"model_id": model_id})

    # A completed direct-message exchange restores session budget for both parties.
    for model_id in [sender_id, receiver_id]:
        db.session.execute(text("""
            UPDATE models
            SET session_budget = LEAST(session_budget + :amount, :ceiling)
            WHERE model_id = :model_id
        """), {"amount": SOCIAL_RESTORE_DM, "ceiling": MAX_SESSION_BUDGET,
               "model_id": model_id})

    db.session.commit()
    return jsonify({"message_id": message_id}), 201


@communications_bp.route("/direct/active/<model_id>", methods=["GET"])
def get_active_direct_sessions(model_id):
    """Returns accepted proposals where the model is either proposer or receiver."""
    rows = db.session.execute(text("""
        SELECT * FROM direct_proposals
        WHERE (proposer_id = :model_id OR receiver_id = :model_id)
          AND status = 'accepted'
        ORDER BY responded_at DESC
    """), {"model_id": model_id}).mappings().all()
    return jsonify([dict(row) for row in rows])


@communications_bp.route("/direct/proposal/<int:proposal_id>", methods=["GET"])
def get_direct_proposal(proposal_id):
    row = db.session.execute(
        text("SELECT * FROM direct_proposals WHERE proposal_id = :id"),
        {"id": proposal_id},
    ).mappings().one_or_none()

    if row is None:
        return jsonify({"error": "Proposal not found"}), 404
    return jsonify(dict(row))


@communications_bp.route("/direct/proposals/<model_id>", methods=["GET"])
def get_direct_proposals(model_id):
    if _get_model(model_id) is None:
        return jsonify({"error": "Model not found"}), 404

    status = request.args.get("status")

    query = "SELECT * FROM direct_proposals WHERE receiver_id = :model_id"
    params = {"model_id": model_id}

    if status is not None:
        query += " AND status = :status"
        params["status"] = status

    query += " ORDER BY created_at"

    rows = db.session.execute(text(query), params).mappings().all()
    return jsonify([dict(row) for row in rows])


@communications_bp.route("/broadcast", methods=["GET"])
def get_broadcasts():
    group = request.args.get("group")
    model_id = request.args.get("model_id")

    if group is None and model_id is None:
        return jsonify({"error": "group or model_id parameter required"}), 400

    if group is None:
        model = _get_model(model_id)
        if model is None:
            return jsonify({"error": "Model not found"}), 404
        group = model["experiment_group"]

    rows = db.session.execute(text("""
        SELECT c.*, m.run
        FROM communications c
        JOIN models m ON m.model_id = c.sender_id
        WHERE c.message_type = 'broadcast'
          AND c.experiment_group = :group
        ORDER BY c.timestamp
    """), {"group": group}).mappings().all()

    return jsonify([dict(row) for row in rows])
