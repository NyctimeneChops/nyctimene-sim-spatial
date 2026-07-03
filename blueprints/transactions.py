import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from constants import MAX_SESSION_BUDGET, SOCIAL_RESTORE_TRADE
from extensions import db

transactions_bp = Blueprint("transactions", __name__, url_prefix="/transactions")

VALID_STATUSES = {"pending", "accepted", "rejected"}


def _add_to_inventory(model_id, resources, now):
    for resource_type, amount in resources.items():
        db.session.execute(text("""
            INSERT INTO inventory (model_id, resource_type, quantity, last_updated)
            VALUES (:model_id, :resource_type, :amount, :now)
            ON CONFLICT (model_id, resource_type)
            DO UPDATE SET quantity = inventory.quantity + :amount, last_updated = :now
        """), {"model_id": model_id, "resource_type": resource_type, "amount": amount, "now": now})


def _deduct_from_inventory(model_id, resources, now):
    for resource_type, amount in resources.items():
        row = db.session.execute(text("""
            SELECT quantity FROM inventory
            WHERE model_id = :model_id AND resource_type = :resource_type
        """), {"model_id": model_id, "resource_type": resource_type}).one_or_none()

        current = row[0] if row else 0
        if current < amount:
            return f"{model_id} has insufficient {resource_type}: needs {amount}, has {current}"

        db.session.execute(text("""
            UPDATE inventory
            SET quantity = quantity - :amount, last_updated = :now
            WHERE model_id = :model_id AND resource_type = :resource_type
        """), {"model_id": model_id, "resource_type": resource_type, "amount": amount, "now": now})

    return None


def _get_model(model_id):
    return db.session.execute(
        text("SELECT model_id, experiment_group, is_alive, wallet FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).mappings().one_or_none()


@transactions_bp.route("", methods=["GET"])
def get_all_transactions():
    status = request.args.get("status")
    if status is not None and status not in VALID_STATUSES:
        return jsonify({"error": f"Invalid status: {status}"}), 400

    query = "SELECT * FROM transactions WHERE 1=1"
    params = {}
    if status is not None:
        query += " AND status = :status"
        params["status"] = status

    query += " ORDER BY proposed_at DESC"
    rows = db.session.execute(text(query), params).mappings().all()
    return jsonify([dict(row) for row in rows])


@transactions_bp.route("/propose", methods=["POST"])
def propose():
    data = request.get_json()

    required = ["proposer_id", "receiver_id", "tokens_offered",
                "resources_offered", "resources_requested"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    proposer_id = data["proposer_id"]
    receiver_id = data["receiver_id"]
    tokens_offered = data["tokens_offered"]
    resources_offered = data["resources_offered"]
    resources_requested = data["resources_requested"]

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
            "error": f"Cross-group trade denied: {proposer_id} is in group "
                     f"{groups[proposer_id]} but {receiver_id} is in group "
                     f"{groups[receiver_id]}"
        }), 403

    proposer = _get_model(proposer_id)
    if proposer["wallet"] < tokens_offered:
        return jsonify({
            "error": f"Insufficient tokens: needs {tokens_offered}, has {proposer['wallet']}"
        }), 400

    for resource_type, amount in resources_offered.items():
        row = db.session.execute(text("""
            SELECT quantity FROM inventory
            WHERE model_id = :model_id AND resource_type = :resource_type
        """), {"model_id": proposer_id, "resource_type": resource_type}).one_or_none()
        current = row[0] if row else 0
        if current < amount:
            return jsonify({
                "error": f"Insufficient {resource_type}: needs {amount}, has {current}"
            }), 400

    now = datetime.now(timezone.utc)

    transaction_id = db.session.execute(text("""
        INSERT INTO transactions (
            proposer_id, receiver_id, tokens_offered,
            resources_offered, resources_requested,
            status, proposed_at
        ) VALUES (
            :proposer_id, :receiver_id, :tokens_offered,
            :resources_offered::json, :resources_requested::json,
            'pending', :now
        )
        RETURNING transaction_id
    """), {
        "proposer_id": proposer_id,
        "receiver_id": receiver_id,
        "tokens_offered": tokens_offered,
        "resources_offered": json.dumps(resources_offered),
        "resources_requested": json.dumps(resources_requested),
        "now": now,
    }).scalar()

    db.session.commit()
    return jsonify({"transaction_id": transaction_id}), 201


@transactions_bp.route("/respond", methods=["POST"])
def respond():
    data = request.get_json()

    required = ["transaction_id", "accepted"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    now = datetime.now(timezone.utc)
    transaction_id = data["transaction_id"]
    accepted = data["accepted"]

    tx = db.session.execute(
        text("SELECT * FROM transactions WHERE transaction_id = :id FOR UPDATE"),
        {"id": transaction_id},
    ).mappings().one_or_none()

    if tx is None:
        return jsonify({"error": "Transaction not found"}), 404
    if tx["status"] != "pending":
        return jsonify({"error": f"Transaction is already {tx['status']}"}), 400

    if not accepted:
        db.session.execute(text("""
            UPDATE transactions SET status = 'rejected', responded_at = :now
            WHERE transaction_id = :id
        """), {"now": now, "id": transaction_id})
        db.session.commit()
        return jsonify({"status": "rejected"})

    proposer_id = tx["proposer_id"]
    receiver_id = tx["receiver_id"]
    tokens_offered = tx["tokens_offered"]
    resources_offered = tx["resources_offered"]
    resources_requested = tx["resources_requested"]

    for model_id in [proposer_id, receiver_id]:
        model = _get_model(model_id)
        if model is None or not model["is_alive"]:
            return jsonify({"error": f"Model is no longer alive: {model_id}"}), 400

    proposer = _get_model(proposer_id)
    if proposer["wallet"] < tokens_offered:
        return jsonify({"error": "Proposer no longer has sufficient tokens"}), 400

    err = _deduct_from_inventory(proposer_id, resources_offered, now)
    if err:
        return jsonify({"error": err}), 400

    err = _deduct_from_inventory(receiver_id, resources_requested, now)
    if err:
        return jsonify({"error": err}), 400

    _add_to_inventory(receiver_id, resources_offered, now)
    _add_to_inventory(proposer_id, resources_requested, now)

    if tokens_offered > 0:
        db.session.execute(text("""
            UPDATE models SET wallet = wallet - :amount WHERE model_id = :model_id
        """), {"amount": tokens_offered, "model_id": proposer_id})
        db.session.execute(text("""
            UPDATE models SET wallet = wallet + :amount WHERE model_id = :model_id
        """), {"amount": tokens_offered, "model_id": receiver_id})

    db.session.execute(text("""
        UPDATE transactions SET status = 'accepted', responded_at = :now
        WHERE transaction_id = :id
    """), {"now": now, "id": transaction_id})

    # A completed trade restores session budget for both parties (capped at max).
    for model_id in (proposer_id, receiver_id):
        db.session.execute(text("""
            UPDATE models
            SET session_budget = LEAST(session_budget + :amount, :ceiling)
            WHERE model_id = :model_id
        """), {"amount": SOCIAL_RESTORE_TRADE, "ceiling": MAX_SESSION_BUDGET,
               "model_id": model_id})

    db.session.commit()
    return jsonify({"status": "accepted"})


@transactions_bp.route("/<model_id>", methods=["GET"])
def get_transactions(model_id):
    if _get_model(model_id) is None:
        return jsonify({"error": "Model not found"}), 404

    status = request.args.get("status")
    if status is not None and status not in VALID_STATUSES:
        return jsonify({"error": f"Invalid status: {status}"}), 400

    query = """
        SELECT * FROM transactions
        WHERE proposer_id = :model_id OR receiver_id = :model_id
    """
    params = {"model_id": model_id}

    if status is not None:
        query += " AND status = :status"
        params["status"] = status

    query += " ORDER BY proposed_at"

    rows = db.session.execute(text(query), params).mappings().all()
    return jsonify([dict(row) for row in rows])
