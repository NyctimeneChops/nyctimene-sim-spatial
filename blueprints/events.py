from flask import Blueprint, jsonify, request
from sqlalchemy import text

from constants import VALID_EVENT_TYPES
from extensions import db

events_bp = Blueprint("events", __name__, url_prefix="/events")


@events_bp.route("", methods=["POST"])
def record_event():
    data = request.get_json()

    required = ["event_type", "day_number"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    event_type = data["event_type"]
    if event_type not in VALID_EVENT_TYPES:
        return jsonify({"error": f"Invalid event_type: {event_type}"}), 400

    model_id = data.get("model_id")
    if model_id is not None:
        model_exists = db.session.execute(
            text("SELECT 1 FROM models WHERE model_id = :model_id"),
            {"model_id": model_id},
        ).one_or_none()
        if model_exists is None:
            return jsonify({"error": f"Model not found: {model_id}"}), 404

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    event_id = db.session.execute(text("""
        INSERT INTO events (model_id, event_type, description, day_number, timestamp)
        VALUES (:model_id, :event_type, :description, :day_number, :now)
        RETURNING event_id
    """), {
        "model_id": model_id,
        "event_type": event_type,
        "description": data.get("description"),
        "day_number": data["day_number"],
        "now": now,
    }).scalar()

    db.session.commit()
    return jsonify({"event_id": event_id}), 201


@events_bp.route("", methods=["GET"])
def get_events():
    event_type = request.args.get("event_type")
    model_id = request.args.get("model_id")
    day = request.args.get("day")

    if event_type is not None and event_type not in VALID_EVENT_TYPES:
        return jsonify({"error": f"Invalid event_type: {event_type}"}), 400

    query = "SELECT * FROM events WHERE 1=1"
    params = {}

    if event_type is not None:
        query += " AND event_type = :event_type"
        params["event_type"] = event_type

    if model_id is not None:
        query += " AND model_id = :model_id"
        params["model_id"] = model_id

    if day is not None:
        query += " AND day_number = :day"
        params["day"] = day

    query += " ORDER BY timestamp"

    rows = db.session.execute(text(query), params).mappings().all()
    return jsonify([dict(row) for row in rows])


@events_bp.route("/day/<int:day_number>", methods=["GET"])
def get_day_narrative(day_number):
    rows = db.session.execute(text("""
        SELECT
            e.event_id,
            e.event_type,
            e.description,
            e.timestamp,
            e.model_id,
            m.experiment_group,
            m.run,
            m.is_alive
        FROM events e
        LEFT JOIN models m ON m.model_id = e.model_id
        WHERE e.day_number = :day_number
        ORDER BY e.timestamp
    """), {"day_number": day_number}).mappings().all()

    timeline = [dict(row) for row in rows]

    counts_by_type = {}
    for event in timeline:
        counts_by_type[event["event_type"]] = counts_by_type.get(event["event_type"], 0) + 1

    return jsonify({
        "day_number": day_number,
        "event_count": len(timeline),
        "counts_by_type": counts_by_type,
        "timeline": timeline,
    })
