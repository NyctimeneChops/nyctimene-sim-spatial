from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from constants import VALID_ACTION_TYPES
from extensions import db

actions_bp = Blueprint("actions", __name__, url_prefix="/actions")


@actions_bp.route("", methods=["POST"])
def record_action():
    data = request.get_json()

    required = ["model_id", "action_type", "succeeded",
                "skill_level_before", "skill_level_after", "day_number"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    if data["action_type"] not in VALID_ACTION_TYPES:
        return jsonify({"error": f"Invalid action_type: {data['action_type']}"}), 400

    model_id = data["model_id"]
    action_type = data["action_type"]
    now = data.get("timestamp", datetime.now(timezone.utc).isoformat())

    model_exists = db.session.execute(
        text("SELECT 1 FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).one_or_none()

    if model_exists is None:
        return jsonify({"error": "Model not found"}), 404

    action_id = db.session.execute(text("""
        INSERT INTO actions (
            model_id, timestamp, day_number, action_type,
            succeeded, stamina_cost, tokens_used,
            tokens_billed, tension_at_action,
            skill_level_before, skill_level_after,
            inputs_consumed, outputs_produced
        ) VALUES (
            :model_id, :timestamp, :day_number, :action_type,
            :succeeded, :stamina_cost, :tokens_used,
            :tokens_billed, :tension_at_action,
            :skill_level_before, :skill_level_after,
            :inputs_consumed, :outputs_produced
        )
        RETURNING action_id
    """), {
        "model_id": model_id,
        "timestamp": now,
        "day_number": data["day_number"],
        "action_type": action_type,
        "succeeded": data["succeeded"],
        "stamina_cost": data.get("stamina_cost", 0),
        "tokens_used": data.get("tokens_used", 0),
        "tokens_billed": data.get("tokens_billed", 0),
        "tension_at_action": data.get("tension_at_action", 0),
        "skill_level_before": data["skill_level_before"],
        "skill_level_after": data["skill_level_after"],
        "inputs_consumed": data.get("inputs_consumed", "{}"),
        "outputs_produced": data.get("outputs_produced", "{}"),
    }).scalar()

    db.session.execute(text("""
        INSERT INTO skills (model_id, action_type, skill_level, last_updated)
        VALUES (:model_id, :action_type, :skill_level, :now)
        ON CONFLICT (model_id, action_type)
        DO UPDATE SET skill_level = :skill_level, last_updated = :now
    """), {
        "model_id": model_id,
        "action_type": action_type,
        "skill_level": data["skill_level_after"],
        "now": now,
    })

    db.session.commit()

    return jsonify({"status": "recorded", "action_id": action_id}), 201


@actions_bp.route("/summary", methods=["GET"])
def get_actions_summary():
    """
    Returns total and succeeded action counts, optionally filtered by day.
    Used by main.py for the live status display.
    """
    day = request.args.get("day")

    query  = "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE succeeded) AS succeeded FROM actions"
    params = {}
    if day is not None:
        query += " WHERE day_number = :day"
        params["day"] = day

    row = db.session.execute(text(query), params).mappings().one()
    return jsonify({
        "day_number": day,
        "total":      row["total"],
        "succeeded":  row["succeeded"],
    })


@actions_bp.route("/<model_id>", methods=["GET"])
def get_actions(model_id):
    model_exists = db.session.execute(
        text("SELECT 1 FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).one_or_none()

    if model_exists is None:
        return jsonify({"error": "Model not found"}), 404

    day = request.args.get("day")
    action_type = request.args.get("action_type")
    limit = request.args.get("limit")

    if limit is not None:
        try:
            limit = int(limit)
        except ValueError:
            return jsonify({"error": f"Invalid limit: {limit}"}), 400
        if limit < 1:
            return jsonify({"error": f"Invalid limit: {limit}"}), 400

    query = "SELECT * FROM actions WHERE model_id = :model_id"
    params = {"model_id": model_id}

    if day is not None:
        query += " AND day_number = :day"
        params["day"] = day

    if action_type is not None:
        if action_type not in VALID_ACTION_TYPES:
            return jsonify({"error": f"Invalid action_type: {action_type}"}), 400
        query += " AND action_type = :action_type"
        params["action_type"] = action_type

    if limit is not None:
        query += " ORDER BY timestamp DESC LIMIT :limit"
        params["limit"] = limit
    else:
        query += " ORDER BY timestamp"

    rows = db.session.execute(text(query), params).mappings().all()

    results = [dict(row) for row in rows]
    if limit is not None:
        results.reverse()  # newest-last (chronological) order

    return jsonify(results)


@actions_bp.route("/<model_id>/summary", methods=["GET"])
def get_model_actions_summary(model_id):
    """
    Lifetime per-action-type totals for one model:
    {"harvest": {"attempts": 23, "succeeded": 14}, ...}
    """
    model_exists = db.session.execute(
        text("SELECT 1 FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).one_or_none()

    if model_exists is None:
        return jsonify({"error": "Model not found"}), 404

    rows = db.session.execute(text("""
        SELECT action_type,
               COUNT(*) AS attempts,
               COUNT(*) FILTER (WHERE succeeded) AS succeeded
        FROM actions
        WHERE model_id = :model_id
        GROUP BY action_type
    """), {"model_id": model_id}).mappings().all()

    return jsonify({
        row["action_type"]: {"attempts": row["attempts"], "succeeded": row["succeeded"]}
        for row in rows
    })
