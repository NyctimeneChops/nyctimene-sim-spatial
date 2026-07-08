import random
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from constants import (
    BUILDABLE_NODE_TYPES, NODE_BASE_FAILURE_RATES, UNITS_PER_HARVEST,
    VALID_EXPERIMENT_GROUPS, WELL_BUILD_COST,
)
from extensions import db

nodes_bp = Blueprint("nodes", __name__, url_prefix="/nodes")


def _get_model_group(model_id):
    """Returns the model's experiment_group, or None if the model doesn't exist."""
    row = db.session.execute(
        text("SELECT experiment_group FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).one_or_none()
    return row[0] if row else None


def _resolve_group_param():
    """
    Resolve the experiment group from request args (?group= or ?model_id=).
    Returns (group, error_response, status_code); group is None on error.
    """
    group = request.args.get("group")
    model_id = request.args.get("model_id")

    if group is None and model_id is None:
        return None, jsonify({"error": "group or model_id parameter required"}), 400

    if group is None:
        group = _get_model_group(model_id)
        if group is None:
            return None, jsonify({"error": "Model not found"}), 404
    elif group not in VALID_EXPERIMENT_GROUPS:
        return None, jsonify({"error": f"Invalid group: {group}"}), 400

    return group, None, None


@nodes_bp.route("", methods=["GET"])
def get_nodes():
    group, error, status = _resolve_group_param()
    if error is not None:
        return error, status

    rows = db.session.execute(text("""
        SELECT node_id, node_type, experiment_group, current_yield, max_yield_per_day, pos_x, pos_y, is_built, built_by, yield_last_updated
        FROM node_state
        WHERE experiment_group = :group
        ORDER BY node_id
    """), {"group": group}).mappings().all()

    return jsonify([dict(row) for row in rows])


@nodes_bp.route("", methods=["POST"])
def create_node():
    data = request.get_json()

    required = ["node_type", "max_yield_per_day", "experiment_group"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    if data["experiment_group"] not in VALID_EXPERIMENT_GROUPS:
        return jsonify({"error": f"Invalid experiment_group: {data['experiment_group']}"}), 400

    max_yield = data["max_yield_per_day"]
    initial_yield = data.get("initial_yield", max_yield)
    now = datetime.now(timezone.utc)

    result = db.session.execute(text("""
        INSERT INTO node_state (node_type, experiment_group, current_yield, max_yield_per_day, pos_x, pos_y, is_built, yield_last_updated)
        VALUES (:node_type, :experiment_group, :current_yield, :max_yield_per_day, :pos_x, :pos_y, FALSE, :now)
        RETURNING node_id
    """), {
        "node_type": data["node_type"],
        "experiment_group": data["experiment_group"],
        "current_yield": initial_yield,
        "max_yield_per_day": max_yield,
        "pos_x": float(data.get("pos_x", 0.0)),   # SPACE pass 1: fixed node position
        "pos_y": float(data.get("pos_y", 0.0)),
        "now": now,
    })
    node_id = result.scalar()
    db.session.commit()

    return jsonify({
        "node_id": node_id,
        "node_type": data["node_type"],
        "experiment_group": data["experiment_group"],
    }), 201


@nodes_bp.route("/<int:node_id>", methods=["GET"])
def get_node(node_id):
    node = db.session.execute(
        text("SELECT * FROM node_state WHERE node_id = :node_id"),
        {"node_id": node_id},
    ).mappings().one_or_none()

    if node is None:
        return jsonify({"error": "Node not found"}), 404

    today = request.args.get("day")
    activity_query = """
        SELECT * FROM node_activity_log
        WHERE node_id = :node_id AND day_number = :day
        ORDER BY timestamp
    """
    activity_rows = db.session.execute(
        text(activity_query),
        {"node_id": node_id, "day": today},
    ).mappings().all()

    return jsonify({
        **dict(node),
        "activity_today": [dict(row) for row in activity_rows],
    })


@nodes_bp.route("/<int:node_id>/harvest", methods=["POST"])
def harvest(node_id):
    data = request.get_json()

    required = ["model_id", "day_number"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    model_id = data["model_id"]
    day_number = data["day_number"]
    now = datetime.now(timezone.utc)

    model_group = _get_model_group(model_id)
    if model_group is None:
        return jsonify({"error": "Model not found"}), 404

    # Lock the node row for the duration of this transaction to prevent
    # concurrent harvests from reading stale yield values.
    node = db.session.execute(
        text("SELECT * FROM node_state WHERE node_id = :node_id FOR UPDATE"),
        {"node_id": node_id},
    ).mappings().one_or_none()

    if node is None:
        return jsonify({"error": "Node not found"}), 404

    if node["experiment_group"] != model_group:
        return jsonify({
            "error": f"Cross-group harvest denied: model {model_id} is in group "
                     f"{model_group} but node {node_id} belongs to group "
                     f"{node['experiment_group']}"
        }), 403

    if node["current_yield"] <= 0:
        db.session.execute(text("""
            INSERT INTO node_activity_log
                (node_id, model_id, timestamp, day_number, succeeded, units_harvested, yield_after)
            VALUES
                (:node_id, :model_id, :timestamp, :day_number, FALSE, NULL, 0)
        """), {
            "node_id": node_id,
            "model_id": model_id,
            "timestamp": now,
            "day_number": day_number,
        })
        db.session.commit()
        return jsonify({"succeeded": False, "reason": "No yield remaining", "yield_after": 0})

    # Accept a pre-rolled result from the caller (e.g. agent with skill-adjusted rate).
    # Fall back to the base failure rate when called directly without one.
    if "succeeded" in data:
        succeeded = bool(data["succeeded"])
    else:
        failure_rate = NODE_BASE_FAILURE_RATES.get(node["node_type"], {"base": 0.20})["base"]
        succeeded = random.random() > failure_rate

    units_harvested = None
    yield_after = node["current_yield"]

    if succeeded:
        units_harvested = min(UNITS_PER_HARVEST[node["node_type"]], node["current_yield"])
        yield_after = node["current_yield"] - units_harvested

        db.session.execute(
            text("""
                UPDATE node_state
                SET current_yield = :yield_after, yield_last_updated = :now
                WHERE node_id = :node_id
            """),
            {"yield_after": yield_after, "now": now, "node_id": node_id},
        )

    db.session.execute(text("""
        INSERT INTO node_activity_log
            (node_id, model_id, timestamp, day_number, succeeded, units_harvested, yield_after)
        VALUES
            (:node_id, :model_id, :timestamp, :day_number, :succeeded, :units_harvested, :yield_after)
    """), {
        "node_id": node_id,
        "model_id": model_id,
        "timestamp": now,
        "day_number": day_number,
        "succeeded": succeeded,
        "units_harvested": units_harvested,
        "yield_after": yield_after,
    })

    db.session.commit()

    return jsonify({
        "succeeded": succeeded,
        "units_harvested": units_harvested,
        "yield_after": yield_after,
        "node_type": node["node_type"],
    })


@nodes_bp.route("/<int:node_id>/build", methods=["POST"])
def build_node(node_id):
    data = request.get_json()
    if "model_id" not in data:
        return jsonify({"error": "Missing required field: model_id"}), 400

    model_group = _get_model_group(data["model_id"])
    if model_group is None:
        return jsonify({"error": "Model not found"}), 404

    node = db.session.execute(
        text("SELECT * FROM node_state WHERE node_id = :node_id FOR UPDATE"),
        {"node_id": node_id},
    ).mappings().one_or_none()

    if node is None:
        return jsonify({"error": "Node not found"}), 404
    if node["experiment_group"] != model_group:
        return jsonify({
            "error": f"Cross-group build denied: model {data['model_id']} is in group "
                     f"{model_group} but node {node_id} belongs to group "
                     f"{node['experiment_group']}"
        }), 403
    if node["node_type"] not in BUILDABLE_NODE_TYPES:
        return jsonify({"error": f"Node type '{node['node_type']}' is not buildable"}), 400
    if node["is_built"]:
        return jsonify({"error": "Node is already built"}), 400

    now = datetime.now(timezone.utc)

    db.session.execute(text("""
        UPDATE node_state
        SET is_built = TRUE, built_by = :model_id,
            current_yield = max_yield_per_day, yield_last_updated = :now
        WHERE node_id = :node_id
    """), {"model_id": data["model_id"], "now": now, "node_id": node_id})
    db.session.commit()

    return jsonify({"node_id": node_id, "is_built": True, "built_by": data["model_id"]})


@nodes_bp.route("/reset", methods=["POST"])
def reset_node_yields():
    data = request.get_json() or {}
    now = datetime.now(timezone.utc)
    db.session.execute(text("""
        UPDATE node_state
        SET current_yield = max_yield_per_day, yield_last_updated = :now
    """), {"now": now})
    db.session.commit()
    return jsonify({"reset": True, "day_number": data.get("day_number")})


@nodes_bp.route("/activity", methods=["GET"])
def get_all_node_activity():
    day = request.args.get("day")
    if day is None:
        return jsonify({"error": "day parameter required"}), 400

    rows = db.session.execute(text("""
        SELECT
            node_id,
            COUNT(*)                                         AS total_attempts,
            COUNT(*) FILTER (WHERE succeeded = TRUE)         AS succeeded,
            COUNT(*) FILTER (WHERE succeeded = FALSE)        AS failed
        FROM node_activity_log
        WHERE day_number = :day
        GROUP BY node_id
    """), {"day": day}).mappings().all()

    return jsonify({
        str(row["node_id"]): {
            "total_attempts": row["total_attempts"],
            "succeeded":      row["succeeded"],
            "failed":         row["failed"],
        }
        for row in rows
    })


@nodes_bp.route("/<int:node_id>/activity", methods=["GET"])
def get_node_activity(node_id):
    day = request.args.get("day")

    node_exists = db.session.execute(
        text("SELECT 1 FROM node_state WHERE node_id = :node_id"),
        {"node_id": node_id},
    ).one_or_none()

    if node_exists is None:
        return jsonify({"error": "Node not found"}), 404

    query = "SELECT * FROM node_activity_log WHERE node_id = :node_id"
    params = {"node_id": node_id}

    if day is not None:
        query += " AND day_number = :day"
        params["day"] = day

    query += " ORDER BY timestamp"

    rows = db.session.execute(text(query), params).mappings().all()

    return jsonify([dict(row) for row in rows])
