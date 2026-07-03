from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from constants import VALID_RESOURCE_TYPES
from extensions import db

inventory_bp = Blueprint("inventory", __name__, url_prefix="/inventory")


def _model_exists(model_id):
    return db.session.execute(
        text("SELECT 1 FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).one_or_none() is not None


@inventory_bp.route("/<model_id>", methods=["GET"])
def get_inventory(model_id):
    if not _model_exists(model_id):
        return jsonify({"error": "Model not found"}), 404

    rows = db.session.execute(text("""
        SELECT resource_type, quantity, last_updated
        FROM inventory
        WHERE model_id = :model_id
        ORDER BY resource_type
    """), {"model_id": model_id}).mappings().all()

    return jsonify({
        "model_id": model_id,
        "inventory": [dict(row) for row in rows],
    })


@inventory_bp.route("/<model_id>/add", methods=["POST"])
def add_resource(model_id):
    if not _model_exists(model_id):
        return jsonify({"error": "Model not found"}), 404

    data = request.get_json()
    required = ["resource_type", "quantity"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    resource_type = data["resource_type"]
    quantity = data["quantity"]

    if resource_type not in VALID_RESOURCE_TYPES:
        return jsonify({"error": f"Invalid resource_type: {resource_type}"}), 400
    if quantity <= 0:
        return jsonify({"error": "Quantity must be greater than zero"}), 400

    now = datetime.now(timezone.utc)

    new_quantity = db.session.execute(text("""
        INSERT INTO inventory (model_id, resource_type, quantity, last_updated)
        VALUES (:model_id, :resource_type, :quantity, :now)
        ON CONFLICT (model_id, resource_type)
        DO UPDATE SET quantity = inventory.quantity + :quantity, last_updated = :now
        RETURNING quantity
    """), {
        "model_id": model_id,
        "resource_type": resource_type,
        "quantity": quantity,
        "now": now,
    }).scalar()

    db.session.commit()
    return jsonify({
        "model_id": model_id,
        "resource_type": resource_type,
        "quantity": new_quantity,
    })


@inventory_bp.route("/<model_id>/deduct", methods=["POST"])
def deduct_resource(model_id):
    if not _model_exists(model_id):
        return jsonify({"error": "Model not found"}), 404

    data = request.get_json()
    required = ["resource_type", "quantity"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    resource_type = data["resource_type"]
    quantity = data["quantity"]

    if resource_type not in VALID_RESOURCE_TYPES:
        return jsonify({"error": f"Invalid resource_type: {resource_type}"}), 400
    if quantity <= 0:
        return jsonify({"error": "Quantity must be greater than zero"}), 400

    row = db.session.execute(text("""
        SELECT quantity FROM inventory
        WHERE model_id = :model_id AND resource_type = :resource_type
    """), {"model_id": model_id, "resource_type": resource_type}).one_or_none()

    current = row[0] if row else 0
    if current < quantity:
        return jsonify({
            "error": f"Insufficient {resource_type}: needs {quantity}, has {current}"
        }), 400

    now = datetime.now(timezone.utc)

    new_quantity = db.session.execute(text("""
        UPDATE inventory
        SET quantity = quantity - :quantity, last_updated = :now
        WHERE model_id = :model_id AND resource_type = :resource_type
        RETURNING quantity
    """), {
        "model_id": model_id,
        "resource_type": resource_type,
        "quantity": quantity,
        "now": now,
    }).scalar()

    db.session.commit()
    return jsonify({
        "model_id": model_id,
        "resource_type": resource_type,
        "quantity": new_quantity,
    })


@inventory_bp.route("/resource/<resource_type>", methods=["GET"])
def get_resource_population(resource_type):
    if resource_type not in VALID_RESOURCE_TYPES:
        return jsonify({"error": f"Invalid resource_type: {resource_type}"}), 400

    rows = db.session.execute(text("""
        SELECT model_id, quantity, last_updated
        FROM inventory
        WHERE resource_type = :resource_type
        ORDER BY model_id
    """), {"resource_type": resource_type}).mappings().all()

    total = sum(row["quantity"] for row in rows)

    return jsonify({
        "resource_type": resource_type,
        "total_across_population": total,
        "by_model": [dict(row) for row in rows],
    })
