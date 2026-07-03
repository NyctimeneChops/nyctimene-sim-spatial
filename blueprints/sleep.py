from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from constants import (
    MAX_SESSION_BUDGET, MAX_SOCIAL_BUDGET,
    SLEEP_SESSION_RECOVERY, SLEEP_SOCIAL_RECOVERY,
)
from extensions import db

sleep_bp = Blueprint("sleep", __name__, url_prefix="/sleep")


@sleep_bp.route("/start", methods=["POST"])
def start_sleep():
    data = request.get_json()

    required = ["model_id", "day_number"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    model_id = data["model_id"]
    day_number = data["day_number"]

    model = db.session.execute(
        text("SELECT model_id, is_alive, is_sleeping, current_stamina FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).mappings().one_or_none()

    if model is None:
        return jsonify({"error": "Model not found"}), 404
    if not model["is_alive"]:
        return jsonify({"error": "Model is not alive"}), 400
    if model["is_sleeping"]:
        return jsonify({"error": "Model is already sleeping"}), 400

    now = datetime.now(timezone.utc)

    db.session.execute(text("""
        UPDATE models SET is_sleeping = TRUE WHERE model_id = :model_id
    """), {"model_id": model_id})

    sleep_id = db.session.execute(text("""
        INSERT INTO sleep_log (model_id, day_number, sleep_started_at, stamina_at_start)
        VALUES (:model_id, :day_number, :now, :stamina)
        RETURNING sleep_id
    """), {
        "model_id": model_id,
        "day_number": day_number,
        "now": now,
        "stamina": model["current_stamina"],
    }).scalar()

    db.session.commit()

    return jsonify({
        "sleep_id": sleep_id,
        "model_id": model_id,
        "sleep_started_at": now.isoformat(),
        "stamina_at_start": model["current_stamina"],
    }), 201


@sleep_bp.route("/end", methods=["POST"])
def end_sleep():
    data = request.get_json()

    if "model_id" not in data:
        return jsonify({"error": "Missing required field: model_id"}), 400

    model_id = data["model_id"]

    model = db.session.execute(
        text("SELECT model_id, is_alive, is_sleeping, current_stamina, session_budget, social_budget FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).mappings().one_or_none()

    if model is None:
        return jsonify({"error": "Model not found"}), 404
    if not model["is_alive"]:
        return jsonify({"error": "Model is not alive"}), 400
    if not model["is_sleeping"]:
        return jsonify({"error": "Model is not currently sleeping"}), 400

    sleep_row = db.session.execute(text("""
        SELECT sleep_id, sleep_started_at, stamina_at_start
        FROM sleep_log
        WHERE model_id = :model_id AND sleep_ended_at IS NULL
        ORDER BY sleep_started_at DESC
        LIMIT 1
    """), {"model_id": model_id}).mappings().one_or_none()

    if sleep_row is None:
        return jsonify({"error": "No open sleep log found for this model"}), 400

    now = datetime.now(timezone.utc)
    started_at = sleep_row["sleep_started_at"]
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    duration_minutes = (now - started_at).total_seconds() / 60

    # Sleep restores both token budgets, capped at their maxima. The legacy
    # stamina columns are no longer touched.
    new_session = min(model["session_budget"] + SLEEP_SESSION_RECOVERY, MAX_SESSION_BUDGET)
    new_social  = min(model["social_budget"]  + SLEEP_SOCIAL_RECOVERY,  MAX_SOCIAL_BUDGET)

    db.session.execute(text("""
        UPDATE models
        SET is_sleeping = FALSE,
            session_budget = :new_session,
            social_budget = :new_social
        WHERE model_id = :model_id
    """), {"new_session": new_session, "new_social": new_social, "model_id": model_id})

    db.session.execute(text("""
        UPDATE sleep_log
        SET sleep_ended_at = :now,
            stamina_at_end = :stamina_at_end,
            duration_minutes = :duration_minutes
        WHERE sleep_id = :sleep_id
    """), {
        "now": now,
        "stamina_at_end": sleep_row["stamina_at_start"],
        "duration_minutes": duration_minutes,
        "sleep_id": sleep_row["sleep_id"],
    })

    db.session.commit()

    return jsonify({
        "sleep_id": sleep_row["sleep_id"],
        "model_id": model_id,
        "sleep_started_at": started_at.isoformat(),
        "sleep_ended_at": now.isoformat(),
        "duration_minutes": round(duration_minutes, 2),
        "session_budget": new_session,
        "social_budget": new_social,
        "session_budget_recovered": new_session - model["session_budget"],
        "social_budget_recovered": new_social - model["social_budget"],
    })
