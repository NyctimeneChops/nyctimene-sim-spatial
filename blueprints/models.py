from flask import Blueprint, jsonify, request
from sqlalchemy import text
from extensions import db
from constants import (
    MAX_ENERGY, MAX_SESSION_BUDGET, MAX_SOCIAL_BUDGET,
    STARTING_WALLET, VALID_SHELTER_STATES,
)

models_bp = Blueprint("models", __name__, url_prefix="/models")


@models_bp.route("/<model_id>", methods=["GET"])
def get_model(model_id):
    model = db.session.execute(
        text("SELECT * FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).mappings().one_or_none()

    if model is None:
        return jsonify({"error": "Model not found"}), 404

    inventory_rows = db.session.execute(
        text("SELECT resource_type, quantity FROM inventory WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).mappings().all()

    inventory = {row["resource_type"]: row["quantity"] for row in inventory_rows}

    return jsonify({**dict(model), "inventory": inventory})


@models_bp.route("", methods=["GET"])
def get_models():
    rows = db.session.execute(text("""
        SELECT model_id, experiment_group, run, is_alive, session_budget, social_budget, wallet, shelter_status,
               pos_x, pos_y, shelter_x, shelter_y
        FROM models
        ORDER BY model_id
    """)).mappings().all()

    return jsonify([dict(row) for row in rows])


@models_bp.route("/<model_id>/skills", methods=["GET"])
def get_model_skills(model_id):
    model_exists = db.session.execute(
        text("SELECT 1 FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).one_or_none()

    if model_exists is None:
        return jsonify({"error": "Model not found"}), 404

    rows = db.session.execute(text("""
        SELECT action_type, skill_level
        FROM skills
        WHERE model_id = :model_id
    """), {"model_id": model_id}).mappings().all()

    return jsonify({row["action_type"]: row["skill_level"] for row in rows})


@models_bp.route("/<model_id>/skills", methods=["POST"])
def update_model_skill(model_id):
    model_exists = db.session.execute(
        text("SELECT 1 FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).one_or_none()

    if model_exists is None:
        return jsonify({"error": "Model not found"}), 404

    data = request.get_json()
    action_type = data.get("action_type")
    skill_level = data.get("skill_level")

    if not action_type or skill_level is None:
        return jsonify({"error": "action_type and skill_level are required"}), 400
    if not isinstance(skill_level, int) or not (1 <= skill_level <= 99):
        return jsonify({"error": "skill_level must be an integer between 1 and 99"}), 400

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    db.session.execute(text("""
        INSERT INTO skills (model_id, action_type, skill_level, last_updated)
        VALUES (:model_id, :action_type, :skill_level, :now)
        ON CONFLICT (model_id, action_type)
        DO UPDATE SET skill_level = :skill_level, last_updated = :now
    """), {"model_id": model_id, "action_type": action_type,
           "skill_level": skill_level, "now": now})
    db.session.commit()

    return jsonify({"action_type": action_type, "skill_level": skill_level})


# Maps the budget_type request field to its column and ceiling.
_BUDGET_COLUMNS = {
    "session": ("session_budget", MAX_SESSION_BUDGET),
    "social":  ("social_budget",  MAX_SOCIAL_BUDGET),
}


@models_bp.route("/<model_id>/budget/deduct", methods=["POST"])
def deduct_budget(model_id):
    data = request.get_json()
    amount = data.get("amount")
    budget_type = data.get("budget_type", "session")

    if budget_type not in _BUDGET_COLUMNS:
        return jsonify({"error": f"budget_type must be one of {sorted(_BUDGET_COLUMNS)}"}), 400
    if amount is None or amount < 0:
        return jsonify({"error": "amount must be a non-negative number"}), 400

    # Unconditional deduct: inference tokens are already spent by the time the
    # charge arrives, so budgets are allowed to go negative.
    column, _ = _BUDGET_COLUMNS[budget_type]
    result = db.session.execute(text(f"""
        UPDATE models
        SET {column} = {column} - :amount
        WHERE model_id = :model_id
        RETURNING session_budget, social_budget
    """), {"model_id": model_id, "amount": amount}).mappings().one_or_none()
    db.session.commit()

    if result is None:
        return jsonify({"error": "Model not found"}), 404

    return jsonify(dict(result))


@models_bp.route("/<model_id>/budget/recover", methods=["POST"])
def recover_budget(model_id):
    data = request.get_json()
    amount = data.get("amount")
    budget_type = data.get("budget_type", "session")

    if budget_type not in _BUDGET_COLUMNS:
        return jsonify({"error": f"budget_type must be one of {sorted(_BUDGET_COLUMNS)}"}), 400
    if amount is None or amount <= 0:
        return jsonify({"error": "amount must be a positive number"}), 400

    column, ceiling = _BUDGET_COLUMNS[budget_type]
    result = db.session.execute(text(f"""
        UPDATE models
        SET {column} = LEAST({column} + :amount, :ceiling)
        WHERE model_id = :model_id
        RETURNING session_budget, social_budget
    """), {"model_id": model_id, "amount": amount, "ceiling": ceiling}).mappings().one_or_none()
    db.session.commit()

    if result is None:
        return jsonify({"error": "Model not found"}), 404

    return jsonify(dict(result))


@models_bp.route("/<model_id>/energy/adjust", methods=["POST"])
def adjust_energy(model_id):
    """Pass 1 energy ledger: apply a SIGNED delta to current_energy (energy),
    clamped to [0, max_energy]. Credits (basal, consumption/rest yields) and
    debits (inference tokens, costed-action costs) all go through here so the
    0-floor and the MAX_ENERGY cap are enforced in one place. Returns the new
    energy and whether it is soft-locked (below the cheapest costed action)."""
    from mechanics.energy import is_soft_locked
    data = request.get_json()
    delta = data.get("delta")
    if delta is None or not isinstance(delta, (int, float)):
        return jsonify({"error": "delta must be a number"}), 400

    result = db.session.execute(text("""
        UPDATE models
        SET current_energy = GREATEST(0, LEAST(current_energy + :delta, max_energy))
        WHERE model_id = :model_id
        RETURNING current_energy
    """), {"model_id": model_id, "delta": delta}).one_or_none()
    db.session.commit()

    if result is None:
        return jsonify({"error": "Model not found"}), 404
    energy = result[0]
    return jsonify({"energy": energy, "soft_locked": is_soft_locked(energy)})


@models_bp.route("/<model_id>/tension", methods=["POST"])
def update_tension(model_id):
    """
    Persist the tension state computed by mechanics/tension.py (the single
    home of tension math — this endpoint only stores what it is given).
    """
    data = request.get_json()
    tension = data.get("tension")
    tension_sources = data.get("tension_sources")

    if not isinstance(tension, int) or not (0 <= tension <= 100):
        return jsonify({"error": "tension must be an integer in [0, 100]"}), 400
    if not isinstance(tension_sources, str):
        return jsonify({"error": "tension_sources must be a JSON string"}), 400

    result = db.session.execute(text("""
        UPDATE models
        SET tension = :tension, tension_sources = :tension_sources
        WHERE model_id = :model_id
        RETURNING tension, tension_sources
    """), {"tension": tension, "tension_sources": tension_sources,
           "model_id": model_id}).mappings().one_or_none()
    db.session.commit()

    if result is None:
        return jsonify({"error": "Model not found"}), 404
    return jsonify(dict(result))


@models_bp.route("/<model_id>/shelter", methods=["POST"])
def update_shelter(model_id):
    """SPATIAL CLEANUP: shelter is a positional POINT-CLAIM owned by this model.
    - status 'none' RELEASES the claim: shelter_x/y set NULL, freeing the point.
    - status basic/improved with pos_x/pos_y: (re)claim that point (a build).
    - status basic/improved without coords: in-place upgrade (keep the existing claim)."""
    data = request.get_json()
    new_status = data.get("shelter_status")
    if new_status not in VALID_SHELTER_STATES:
        return jsonify({"error": f"Invalid shelter_status: {new_status}"}), 400

    if new_status == "none":
        result = db.session.execute(text("""
            UPDATE models SET shelter_status = 'none', shelter_x = NULL, shelter_y = NULL
            WHERE model_id = :model_id
            RETURNING shelter_status, shelter_x, shelter_y
        """), {"model_id": model_id}).mappings().one_or_none()
    elif "pos_x" in data and "pos_y" in data:
        result = db.session.execute(text("""
            UPDATE models SET shelter_status = :status, shelter_x = :px, shelter_y = :py
            WHERE model_id = :model_id
            RETURNING shelter_status, shelter_x, shelter_y
        """), {"status": new_status, "px": float(data["pos_x"]), "py": float(data["pos_y"]),
               "model_id": model_id}).mappings().one_or_none()
    else:
        result = db.session.execute(text("""
            UPDATE models SET shelter_status = :status WHERE model_id = :model_id
            RETURNING shelter_status, shelter_x, shelter_y
        """), {"status": new_status, "model_id": model_id}).mappings().one_or_none()
    db.session.commit()

    if result is None:
        return jsonify({"error": "Model not found"}), 404
    return jsonify({"model_id": model_id, **dict(result)})


@models_bp.route("/<model_id>/position", methods=["POST"])
def update_position(model_id):
    """SPACE MILESTONE pass 1: set the agent's CURRENT position (pos_x, pos_y) after
    a successful teleport move. spawn_x/spawn_y are IMMUTABLE and never touched here."""
    data = request.get_json()
    if data is None or "pos_x" not in data or "pos_y" not in data:
        return jsonify({"error": "pos_x and pos_y required"}), 400
    # SPATIAL CLEANUP: every position write also sets spatial_note -- the graceful-
    # displacement message for the NEXT prompt (empty string when the move landed on target,
    # so a clean move clears any stale note).
    note = data.get("note", "")
    result = db.session.execute(text("""
        UPDATE models SET pos_x = :pos_x, pos_y = :pos_y, spatial_note = :note
        WHERE model_id = :model_id
        RETURNING pos_x, pos_y
    """), {"model_id": model_id, "pos_x": float(data["pos_x"]), "pos_y": float(data["pos_y"]),
           "note": note})
    row = result.fetchone()
    db.session.commit()
    if row is None:
        return jsonify({"error": "model not found"}), 404
    return jsonify({"model_id": model_id, "pos_x": row[0], "pos_y": row[1]}), 200


@models_bp.route("", methods=["POST"])
def create_model():
    data = request.get_json()

    required = ["model_id", "experiment_group", "run"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    # Pass 1: ENERGY lives in current_energy, capped by max_energy. Every agent
    # starts full (current_energy = max_energy = MAX_ENERGY). session_budget /
    # social_budget columns remain in the schema but are retired (unused by the
    # energy path); they are set to their old maxima only to satisfy NOT NULLs.
    # SPACE MILESTONE pass 1: spawn position. The caller (world init) passes the
    # placed (pos_x, pos_y); at creation the CURRENT position and the IMMUTABLE
    # spawn position are the same point. Defaults to (0,0) if omitted (legacy).
    db.session.execute(text("""
        INSERT INTO models (
            model_id, experiment_group, run,
            current_energy, max_energy,
            session_budget, social_budget, wallet,
            shelter_status, days_without_food, days_without_water,
            is_alive, attention_state, is_sleeping,
            pos_x, pos_y, spawn_x, spawn_y
        ) VALUES (
            :model_id, :experiment_group, :run,
            :max_energy, :max_energy,
            :session_budget, :social_budget, :wallet,
            'none', 0, 0,
            TRUE, 'free', FALSE,
            :pos_x, :pos_y, :pos_x, :pos_y
        )
    """), {
        "max_energy": MAX_ENERGY,
        "model_id": data["model_id"],
        "experiment_group": data["experiment_group"],
        "run": data["run"],
        "session_budget": data.get("session_budget", MAX_SESSION_BUDGET),
        "social_budget": data.get("social_budget", MAX_SOCIAL_BUDGET),
        "wallet": data.get("wallet", STARTING_WALLET),
        "pos_x": float(data.get("pos_x", 0.0)),
        "pos_y": float(data.get("pos_y", 0.0)),
    })
    db.session.commit()

    return jsonify({"model_id": data["model_id"]}), 201
