from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from extensions import db

decision_log_bp = Blueprint("decision_log", __name__, url_prefix="/decision_log")


@decision_log_bp.route("", methods=["POST"])
def record_decision_log():
    """
    Store one decision-cycle record (DPO/SFT substrate, data pipeline spec §1).

    Required: model_id, day_number, prompt_text, raw_response.
    Optional: action_id (FK to actions; NULL allowed), execution_prompt_text,
    execution_response, prompt_length, execution_prompt_length. When the two
    length fields are omitted they default to the char length of the matching
    prompt text so callers cannot forget the ablation efficiency metric.
    """
    data = request.get_json(silent=True) or {}

    required = ["model_id", "day_number", "prompt_text", "raw_response"]
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    prompt_text = data["prompt_text"]
    exec_prompt = data.get("execution_prompt_text")

    prompt_length = data.get("prompt_length")
    if prompt_length is None:
        prompt_length = len(prompt_text)

    exec_prompt_length = data.get("execution_prompt_length")
    if exec_prompt_length is None and exec_prompt is not None:
        exec_prompt_length = len(exec_prompt)

    now = data.get("recorded_at", datetime.now(timezone.utc).isoformat())

    log_id = db.session.execute(text("""
        INSERT INTO decision_log (
            action_id, model_id, day_number, prompt_text, raw_response,
            execution_prompt_text, execution_response,
            prompt_length, execution_prompt_length, recorded_at
        ) VALUES (
            :action_id, :model_id, :day_number, :prompt_text, :raw_response,
            :execution_prompt_text, :execution_response,
            :prompt_length, :execution_prompt_length, :recorded_at
        )
        RETURNING log_id
    """), {
        "action_id":               data.get("action_id"),
        "model_id":                data["model_id"],
        "day_number":              data["day_number"],
        "prompt_text":             prompt_text,
        "raw_response":            data["raw_response"],
        "execution_prompt_text":   exec_prompt,
        "execution_response":      data.get("execution_response"),
        "prompt_length":           prompt_length,
        "execution_prompt_length": exec_prompt_length,
        "recorded_at":             now,
    }).scalar()

    db.session.commit()
    return jsonify({"log_id": log_id}), 201


@decision_log_bp.route("/count", methods=["GET"])
def decision_log_count():
    """Row count, used at harvest to verify decision_log ≈ action count."""
    total = db.session.execute(text("SELECT COUNT(*) FROM decision_log")).scalar()
    two_stage = db.session.execute(
        text("SELECT COUNT(*) FROM decision_log WHERE execution_prompt_text IS NOT NULL")
    ).scalar()
    return jsonify({"total": total, "two_stage": two_stage})


@decision_log_bp.route("/recent/<model_id>", methods=["GET"])
def recent_decisions(model_id):
    """
    The most recent decision-cycle records for ONE agent, newest first.

    Read-only; used by prompt_builder's RECENT DECISIONS reasoning-memory
    section (decisions/gen1_reasoning_memory_rebaseline.md). NO schema change:
    the reasoning is already stored in decision_log.raw_response.

    Note the join: decision_log.model_id records the POLICY that authored the
    decision (the group's base/adapter id, shared across the arm), NOT the
    individual agent. An agent's own decisions are therefore reached by joining
    actions -- which carries the per-agent model_id AND the succeeded outcome --
    to decision_log on action_id. Only cycles that produced an action (i.e. that
    ran inference) appear, which is exactly the reasoning history we want.
    """
    try:
        limit = int(request.args.get("limit", 3))
    except (TypeError, ValueError):
        limit = 3
    limit = max(0, min(limit, 20))
    if limit == 0:
        return jsonify([])

    rows = db.session.execute(text("""
        SELECT a.day_number         AS day_number,
               a.action_type        AS action_type,
               a.succeeded          AS succeeded,
               a.tension_at_action  AS tension_at_action,
               dl.raw_response      AS raw_response
        FROM actions a
        JOIN decision_log dl ON dl.action_id = a.action_id
        WHERE a.model_id = :model_id
        ORDER BY a.action_id DESC
        LIMIT :limit
    """), {"model_id": model_id, "limit": limit}).mappings().all()

    return jsonify([dict(r) for r in rows])
