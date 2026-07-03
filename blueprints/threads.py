from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from constants import MAX_SESSION_BUDGET, SOCIAL_RESTORE_THREAD
from extensions import db

threads_bp = Blueprint("threads", __name__, url_prefix="/threads")


def _get_model(model_id):
    return db.session.execute(
        text("SELECT model_id, experiment_group, is_alive, attention_state FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).mappings().one_or_none()


def _get_thread(thread_id):
    return db.session.execute(
        text("SELECT * FROM threads WHERE thread_id = :thread_id"),
        {"thread_id": thread_id},
    ).mappings().one_or_none()


def _get_active_presence_window(thread_id, model_id):
    return db.session.execute(text("""
        SELECT * FROM thread_presence_windows
        WHERE thread_id = :thread_id AND model_id = :model_id AND is_active = TRUE
    """), {"thread_id": thread_id, "model_id": model_id}).mappings().one_or_none()


@threads_bp.route("/create", methods=["POST"])
def create_thread():
    data = request.get_json()

    if "creator_id" not in data:
        return jsonify({"error": "Missing required field: creator_id"}), 400

    creator_id = data["creator_id"]
    model = _get_model(creator_id)

    if model is None:
        return jsonify({"error": "Model not found"}), 404
    if not model["is_alive"]:
        return jsonify({"error": "Model is not alive"}), 400
    if model["attention_state"] != "free":
        return jsonify({
            "error": f"Model attention is not free: currently {model['attention_state']}"
        }), 400

    now = datetime.now(timezone.utc)

    thread_id = db.session.execute(text("""
        INSERT INTO threads (created_by, experiment_group, created_at, is_private, is_active)
        VALUES (:creator_id, :experiment_group, :now, FALSE, TRUE)
        RETURNING thread_id
    """), {
        "creator_id": creator_id,
        "experiment_group": model["experiment_group"],
        "now": now,
    }).scalar()

    db.session.execute(text("""
        INSERT INTO thread_presence_windows (thread_id, model_id, joined_at, is_active)
        VALUES (:thread_id, :model_id, :now, TRUE)
    """), {"thread_id": thread_id, "model_id": creator_id, "now": now})

    db.session.execute(text("""
        UPDATE models SET attention_state = 'in_group_thread' WHERE model_id = :model_id
    """), {"model_id": creator_id})

    db.session.commit()
    return jsonify({"thread_id": thread_id}), 201


@threads_bp.route("/<int:thread_id>/join", methods=["POST"])
def join_thread(thread_id):
    data = request.get_json()

    if "model_id" not in data:
        return jsonify({"error": "Missing required field: model_id"}), 400

    model_id = data["model_id"]
    model = _get_model(model_id)

    if model is None:
        return jsonify({"error": "Model not found"}), 404
    if not model["is_alive"]:
        return jsonify({"error": "Model is not alive"}), 400
    if model["attention_state"] != "free":
        return jsonify({
            "error": f"Model attention is not free: currently {model['attention_state']}"
        }), 400

    thread = _get_thread(thread_id)
    if thread is None:
        return jsonify({"error": "Thread not found"}), 404
    if thread["experiment_group"] != model["experiment_group"]:
        return jsonify({
            "error": f"Cross-group thread join denied: model {model_id} is in group "
                     f"{model['experiment_group']} but thread {thread_id} belongs to "
                     f"group {thread['experiment_group']}"
        }), 403
    if not thread["is_active"]:
        return jsonify({"error": "Thread is no longer active"}), 400
    if thread["is_private"]:
        return jsonify({"error": "Thread is private"}), 403

    existing_window = _get_active_presence_window(thread_id, model_id)
    if existing_window is not None:
        return jsonify({"error": "Model already has an active presence window in this thread"}), 400

    now = datetime.now(timezone.utc)

    db.session.execute(text("""
        INSERT INTO thread_presence_windows (thread_id, model_id, joined_at, is_active)
        VALUES (:thread_id, :model_id, :now, TRUE)
    """), {"thread_id": thread_id, "model_id": model_id, "now": now})

    db.session.execute(text("""
        UPDATE models SET attention_state = 'in_group_thread' WHERE model_id = :model_id
    """), {"model_id": model_id})

    db.session.commit()
    return jsonify({"status": "joined", "thread_id": thread_id})


@threads_bp.route("/<int:thread_id>/leave", methods=["POST"])
def leave_thread(thread_id):
    data = request.get_json()

    if "model_id" not in data:
        return jsonify({"error": "Missing required field: model_id"}), 400

    model_id = data["model_id"]

    if _get_model(model_id) is None:
        return jsonify({"error": "Model not found"}), 404

    window = _get_active_presence_window(thread_id, model_id)
    if window is None:
        return jsonify({"error": "Model has no active presence window in this thread"}), 400

    now = datetime.now(timezone.utc)

    db.session.execute(text("""
        UPDATE thread_presence_windows
        SET left_at = :now, is_active = FALSE
        WHERE window_id = :window_id
    """), {"now": now, "window_id": window["window_id"]})

    db.session.execute(text("""
        UPDATE models SET attention_state = 'free' WHERE model_id = :model_id
    """), {"model_id": model_id})

    db.session.commit()
    return jsonify({"status": "left", "thread_id": thread_id})


@threads_bp.route("/<int:thread_id>/message", methods=["POST"])
def send_thread_message(thread_id):
    data = request.get_json()

    required = ["model_id", "content", "day_number"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    model_id = data["model_id"]
    model = _get_model(model_id)
    if model is None:
        return jsonify({"error": "Model not found"}), 404

    thread = _get_thread(thread_id)
    if thread is None:
        return jsonify({"error": "Thread not found"}), 404
    if thread["experiment_group"] != model["experiment_group"]:
        return jsonify({
            "error": f"Cross-group thread message denied: model {model_id} is in group "
                     f"{model['experiment_group']} but thread {thread_id} belongs to "
                     f"group {thread['experiment_group']}"
        }), 403
    if not thread["is_active"]:
        return jsonify({"error": "Thread is no longer active"}), 400

    window = _get_active_presence_window(thread_id, model_id)
    if window is None:
        return jsonify({"error": "Model does not have an active presence window in this thread"}), 403

    now = datetime.now(timezone.utc)

    message_id = db.session.execute(text("""
        INSERT INTO communications
            (sender_id, experiment_group, recipient_id, thread_id, content, message_type, timestamp, day_number)
        VALUES
            (:model_id, :experiment_group, NULL, :thread_id, :content, 'group', :now, :day_number)
        RETURNING message_id
    """), {
        "model_id": model_id,
        "experiment_group": thread["experiment_group"],
        "thread_id": thread_id,
        "content": data["content"],
        "now": now,
        "day_number": data["day_number"],
    }).scalar()

    # A completed thread message restores session budget for the sender.
    db.session.execute(text("""
        UPDATE models
        SET session_budget = LEAST(session_budget + :amount, :ceiling)
        WHERE model_id = :model_id
    """), {"amount": SOCIAL_RESTORE_THREAD, "ceiling": MAX_SESSION_BUDGET,
           "model_id": model_id})

    db.session.commit()
    return jsonify({"message_id": message_id}), 201


@threads_bp.route("/<int:thread_id>/vote", methods=["POST"])
def vote_privacy(thread_id):
    data = request.get_json()

    required = ["model_id", "vote"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    model_id = data["model_id"]
    vote = data["vote"]

    if not isinstance(vote, bool):
        return jsonify({"error": "vote must be a boolean: true to close, false to open"}), 400

    model = _get_model(model_id)
    if model is None:
        return jsonify({"error": "Model not found"}), 404

    thread = _get_thread(thread_id)
    if thread is None:
        return jsonify({"error": "Thread not found"}), 404
    if thread["experiment_group"] != model["experiment_group"]:
        return jsonify({
            "error": f"Cross-group thread vote denied: model {model_id} is in group "
                     f"{model['experiment_group']} but thread {thread_id} belongs to "
                     f"group {thread['experiment_group']}"
        }), 403
    if not thread["is_active"]:
        return jsonify({"error": "Thread is no longer active"}), 400

    window = _get_active_presence_window(thread_id, model_id)
    if window is None:
        return jsonify({"error": "Model does not have an active presence window in this thread"}), 403

    now = datetime.now(timezone.utc)

    db.session.execute(text("""
        INSERT INTO thread_votes (thread_id, model_id, timestamp, vote)
        VALUES (:thread_id, :model_id, :now, :vote)
    """), {"thread_id": thread_id, "model_id": model_id, "now": now, "vote": vote})

    # Count only the most recent vote per model, restricted to currently present models.
    tally = db.session.execute(text("""
        WITH latest_votes AS (
            SELECT DISTINCT ON (model_id) model_id, vote
            FROM thread_votes
            WHERE thread_id = :thread_id
              AND model_id IN (
                  SELECT model_id FROM thread_presence_windows
                  WHERE thread_id = :thread_id AND is_active = TRUE
              )
            ORDER BY model_id, timestamp DESC
        )
        SELECT
            COUNT(*) FILTER (WHERE vote = TRUE)  AS votes_to_close,
            COUNT(*) FILTER (WHERE vote = FALSE) AS votes_to_open,
            COUNT(*)                              AS total_voters
        FROM latest_votes
    """), {"thread_id": thread_id}).mappings().one()

    votes_to_close = tally["votes_to_close"]
    votes_to_open = tally["votes_to_open"]
    total_voters = tally["total_voters"]

    majority = total_voters / 2
    old_privacy = thread["is_private"]
    new_privacy = old_privacy

    if votes_to_close > majority:
        new_privacy = True
    elif votes_to_open > majority:
        new_privacy = False

    if new_privacy != old_privacy:
        db.session.execute(text("""
            UPDATE threads SET is_private = :is_private WHERE thread_id = :thread_id
        """), {"is_private": new_privacy, "thread_id": thread_id})

        direction = "closed (private)" if new_privacy else "opened (public)"
        db.session.execute(text("""
            INSERT INTO events (model_id, event_type, description, day_number, timestamp)
            VALUES (NULL, 'thread_privacy_changed', :description, :day_number, :now)
        """), {
            "description": f"Thread {thread_id} {direction}: {votes_to_close} to close, {votes_to_open} to open of {total_voters} voters",
            "day_number": data.get("day_number"),
            "now": now,
        })

    db.session.commit()

    return jsonify({
        "thread_id": thread_id,
        "is_private": new_privacy,
        "votes_to_close": votes_to_close,
        "votes_to_open": votes_to_open,
        "total_voters": total_voters,
        "privacy_changed": new_privacy != old_privacy,
    })


@threads_bp.route("", methods=["GET"])
def get_active_threads():
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
        SELECT
            t.thread_id,
            t.experiment_group,
            t.is_private,
            t.created_by,
            t.created_at,
            array_remove(array_agg(w.model_id), NULL) AS current_participants
        FROM threads t
        LEFT JOIN thread_presence_windows w
            ON w.thread_id = t.thread_id AND w.is_active = TRUE
        WHERE t.is_active = TRUE
          AND t.experiment_group = :group
        GROUP BY t.thread_id, t.experiment_group, t.is_private, t.created_by, t.created_at
        ORDER BY t.thread_id
    """), {"group": group}).mappings().all()

    return jsonify([dict(row) for row in rows])


@threads_bp.route("/<int:thread_id>/messages/<model_id>", methods=["GET"])
def get_visible_messages(thread_id, model_id):
    thread = _get_thread(thread_id)
    if thread is None:
        return jsonify({"error": "Thread not found"}), 404

    if _get_model(model_id) is None:
        return jsonify({"error": "Model not found"}), 404

    rows = db.session.execute(text("""
        SELECT c.*
        FROM communications c
        WHERE c.thread_id = :thread_id
          AND c.message_type = 'group'
          AND EXISTS (
              SELECT 1 FROM thread_presence_windows w
              WHERE w.thread_id = c.thread_id
                AND w.model_id = :model_id
                AND c.timestamp >= w.joined_at
                AND (w.left_at IS NULL OR c.timestamp <= w.left_at)
          )
        ORDER BY c.timestamp
    """), {"thread_id": thread_id, "model_id": model_id}).mappings().all()

    return jsonify([dict(row) for row in rows])
