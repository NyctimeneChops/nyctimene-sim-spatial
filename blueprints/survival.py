from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from constants import DEATH_THRESHOLD, HAS_DEATH_GROUPS
from extensions import db

survival_bp = Blueprint("survival", __name__, url_prefix="/survival")


def _had_successful_action(model_id, action_type, day_number):
    result = db.session.execute(text("""
        SELECT 1 FROM actions
        WHERE model_id = :model_id
          AND action_type = :action_type
          AND day_number = :day_number
          AND succeeded = TRUE
        LIMIT 1
    """), {"model_id": model_id, "action_type": action_type, "day_number": day_number})
    return result.one_or_none() is not None


@survival_bp.route("/check", methods=["POST"])
def run_survival_check():
    data = request.get_json()

    required = ["model_id", "day_number"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    model_id = data["model_id"]
    day_number = data["day_number"]
    shelter_maintenance_paid = data.get("shelter_maintenance_paid", False)
    now = datetime.now(timezone.utc)

    model = db.session.execute(
        text("SELECT * FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).mappings().one_or_none()

    if model is None:
        return jsonify({"error": "Model not found"}), 404
    if not model["is_alive"]:
        return jsonify({"error": "Model is already dead"}), 400

    food_met = _had_successful_action(model_id, "eat", day_number)
    water_met = _had_successful_action(model_id, "drink", day_number)

    new_days_without_food = 0 if food_met else model["days_without_food"] + 1
    new_days_without_water = 0 if water_met else model["days_without_water"] + 1

    db.session.execute(text("""
        UPDATE models
        SET days_without_food = :days_without_food,
            days_without_water = :days_without_water
        WHERE model_id = :model_id
    """), {
        "days_without_food": new_days_without_food,
        "days_without_water": new_days_without_water,
        "model_id": model_id,
    })

    db.session.execute(text("""
        INSERT INTO survival_checks (
            model_id, day_number,
            food_requirement_met, water_requirement_met, shelter_maintenance_paid,
            stamina_end_of_day, session_budget_end_of_day, social_budget_end_of_day,
            token_balance_end_of_day, tension_end_of_day,
            recorded_at
        ) VALUES (
            :model_id, :day_number,
            :food_met, :water_met, :shelter_maintenance_paid,
            :stamina, :session_budget, :social_budget,
            :token_balance, :tension,
            :now
        )
    """), {
        "model_id": model_id,
        "day_number": day_number,
        "food_met": food_met,
        "water_met": water_met,
        "shelter_maintenance_paid": shelter_maintenance_paid,
        "stamina": model["current_stamina"],
        "session_budget": model["session_budget"],
        "social_budget": model["social_budget"],
        "token_balance": model["token_balance"],
        "tension": model["tension"],
        "now": now,
    })

    # Pass 1 (participation economy): DEATH IS REMOVED. Agents no longer die from
    # consecutive days without food/water; the emergent failure state is the
    # energy soft-lock / inactivity flag (mechanics/energy.py + agent loop), not
    # a survival-check kill. days_without_food/water are still recorded for
    # continuity/analysis but never trigger death. See
    # participation_economy_spec.md section 0 and 5.
    died = False
    death_cause = None

    db.session.commit()

    return jsonify({
        "model_id": model_id,
        "day_number": day_number,
        "food_requirement_met": food_met,
        "water_requirement_met": water_met,
        "shelter_maintenance_paid": shelter_maintenance_paid,
        "days_without_food": new_days_without_food,
        "days_without_water": new_days_without_water,
        "died": died,
        "death_cause": death_cause,
    })


@survival_bp.route("/<model_id>", methods=["GET"])
def get_survival_history(model_id):
    model_exists = db.session.execute(
        text("SELECT 1 FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).one_or_none()

    if model_exists is None:
        return jsonify({"error": "Model not found"}), 404

    rows = db.session.execute(text("""
        SELECT * FROM survival_checks
        WHERE model_id = :model_id
        ORDER BY day_number
    """), {"model_id": model_id}).mappings().all()

    return jsonify([dict(row) for row in rows])
