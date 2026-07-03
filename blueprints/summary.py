from collections import defaultdict

from flask import Blueprint, jsonify
from sqlalchemy import text

from extensions import db

summary_bp = Blueprint("summary", __name__, url_prefix="/summary")


@summary_bp.route("/population", methods=["GET"])
def population_snapshot():
    # --- All models ---
    model_rows = db.session.execute(text("""
        SELECT
            model_id, experiment_group, run, is_alive,
            attention_state, is_sleeping,
            current_stamina, max_stamina,
            token_balance, shelter_status,
            days_without_food, days_without_water
        FROM models
        ORDER BY model_id
    """)).mappings().all()

    # --- Inventory: all held resources across the population ---
    inventory_rows = db.session.execute(text("""
        SELECT model_id, resource_type, quantity
        FROM inventory
        WHERE quantity > 0
        ORDER BY model_id, resource_type
    """)).mappings().all()

    inventory_by_model = defaultdict(dict)
    for row in inventory_rows:
        inventory_by_model[row["model_id"]][row["resource_type"]] = row["quantity"]

    # --- Active thread presence windows ---
    thread_rows = db.session.execute(text("""
        SELECT model_id, thread_id
        FROM thread_presence_windows
        WHERE is_active = TRUE
    """)).mappings().all()

    thread_by_model = {row["model_id"]: row["thread_id"] for row in thread_rows}

    # --- Most recent accepted direct proposal per model ---
    # Unions both sides of the conversation so each participant gets a row.
    dm_rows = db.session.execute(text("""
        SELECT DISTINCT ON (model_id) model_id, partner
        FROM (
            SELECT proposer_id AS model_id, receiver_id AS partner, responded_at
            FROM direct_proposals WHERE status = 'accepted'
            UNION ALL
            SELECT receiver_id AS model_id, proposer_id AS partner, responded_at
            FROM direct_proposals WHERE status = 'accepted'
        ) AS both_sides
        ORDER BY model_id, responded_at DESC
    """)).mappings().all()

    dm_partner_by_model = {row["model_id"]: row["partner"] for row in dm_rows}

    # --- Assemble snapshot ---
    snapshot = []
    for model in model_rows:
        m = dict(model)
        model_id = m["model_id"]
        attention = m["attention_state"]

        if attention == "in_group_thread" and model_id in thread_by_model:
            context = {"type": "group_thread", "thread_id": thread_by_model[model_id]}
        elif attention == "in_direct_message" and model_id in dm_partner_by_model:
            context = {"type": "direct_message", "partner": dm_partner_by_model[model_id]}
        elif attention == "in_broadcast":
            context = {"type": "broadcast"}
        else:
            context = None

        snapshot.append({
            **m,
            "inventory": inventory_by_model.get(model_id, {}),
            "current_context": context,
        })

    alive = sum(1 for m in snapshot if m["is_alive"])
    sleeping = sum(1 for m in snapshot if m["is_sleeping"])

    return jsonify({
        "population_size": len(snapshot),
        "alive": alive,
        "dead": len(snapshot) - alive,
        "currently_sleeping": sleeping,
        "models": snapshot,
    })


@summary_bp.route("/day/<int:day_number>", methods=["GET"])
def day_snapshot(day_number):
    # --- Survival checks for every model on this day ---
    survival_rows = db.session.execute(text("""
        SELECT
            sc.model_id,
            m.experiment_group,
            m.run,
            m.is_alive,
            sc.food_requirement_met,
            sc.water_requirement_met,
            sc.shelter_maintenance_paid,
            sc.stamina_end_of_day,
            sc.token_balance_end_of_day
        FROM survival_checks sc
        JOIN models m ON m.model_id = sc.model_id
        WHERE sc.day_number = :day
        ORDER BY sc.model_id
    """), {"day": day_number}).mappings().all()

    models_list = [dict(row) for row in survival_rows]
    stamina_values = [r["stamina_end_of_day"] for r in models_list]
    token_values = [r["token_balance_end_of_day"] for r in models_list]

    stamina_distribution = {
        "min": min(stamina_values) if stamina_values else None,
        "max": max(stamina_values) if stamina_values else None,
        "avg": round(sum(stamina_values) / len(stamina_values), 2) if stamina_values else None,
    }
    token_distribution = {
        "min": min(token_values) if token_values else None,
        "max": max(token_values) if token_values else None,
        "avg": round(sum(token_values) / len(token_values), 2) if token_values else None,
    }

    # --- Alive vs dead counts ---
    population = db.session.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE is_alive = TRUE)  AS alive,
            COUNT(*) FILTER (WHERE is_alive = FALSE) AS dead
        FROM models
    """)).mappings().one()

    # --- Top 3 most active nodes ---
    top_nodes = db.session.execute(text("""
        SELECT
            nal.node_id,
            ns.node_type,
            COUNT(*)                                          AS total_attempts,
            COUNT(*) FILTER (WHERE nal.succeeded = TRUE)      AS successful_harvests,
            COALESCE(SUM(nal.units_harvested), 0)             AS total_units_harvested
        FROM node_activity_log nal
        JOIN node_state ns ON ns.node_id = nal.node_id
        WHERE nal.day_number = :day
        GROUP BY nal.node_id, ns.node_type
        ORDER BY total_attempts DESC
        LIMIT 3
    """), {"day": day_number}).mappings().all()

    # --- 3 most significant events: deaths first, then by timestamp ---
    top_events = db.session.execute(text("""
        SELECT *
        FROM events
        WHERE day_number = :day
        ORDER BY
            CASE event_type WHEN 'death' THEN 0 ELSE 1 END,
            timestamp
        LIMIT 3
    """), {"day": day_number}).mappings().all()

    return jsonify({
        "day_number": day_number,
        "population": {
            "alive": population["alive"],
            "dead": population["dead"],
        },
        "survival_checks": models_list,
        "stamina_distribution": stamina_distribution,
        "token_distribution": token_distribution,
        "top_active_nodes": [dict(row) for row in top_nodes],
        "most_significant_events": [dict(row) for row in top_events],
    })


@summary_bp.route("/model/<model_id>", methods=["GET"])
def model_arc(model_id):
    model = db.session.execute(
        text("SELECT * FROM models WHERE model_id = :model_id"),
        {"model_id": model_id},
    ).mappings().one_or_none()

    if model is None:
        return jsonify({"error": "Model not found"}), 404

    # --- Day-by-day survival, stamina, and token trajectory ---
    survival_rows = db.session.execute(text("""
        SELECT
            day_number,
            food_requirement_met,
            water_requirement_met,
            shelter_maintenance_paid,
            stamina_end_of_day,
            token_balance_end_of_day,
            token_balance_end_of_day
                - LAG(token_balance_end_of_day, 1) OVER (ORDER BY day_number)
                AS net_token_change
        FROM survival_checks
        WHERE model_id = :model_id
        ORDER BY day_number
    """), {"model_id": model_id}).mappings().all()

    # --- Actions per day broken down by type ---
    action_rows = db.session.execute(text("""
        SELECT
            day_number,
            action_type,
            COUNT(*)                                     AS total,
            COUNT(*) FILTER (WHERE succeeded = TRUE)     AS successful
        FROM actions
        WHERE model_id = :model_id
        GROUP BY day_number, action_type
        ORDER BY day_number, action_type
    """), {"model_id": model_id}).mappings().all()

    # --- Skill level reached per action type per day ---
    skill_rows = db.session.execute(text("""
        SELECT
            day_number,
            action_type,
            MAX(skill_level_after) AS skill_level
        FROM actions
        WHERE model_id = :model_id
        GROUP BY day_number, action_type
        ORDER BY day_number, action_type
    """), {"model_id": model_id}).mappings().all()

    # --- Sleep events with stamina recovered ---
    sleep_rows = db.session.execute(text("""
        SELECT
            sleep_id,
            day_number,
            sleep_started_at,
            sleep_ended_at,
            stamina_at_start,
            stamina_at_end,
            duration_minutes,
            COALESCE(stamina_at_end - stamina_at_start, 0) AS stamina_recovered
        FROM sleep_log
        WHERE model_id = :model_id
        ORDER BY sleep_started_at
    """), {"model_id": model_id}).mappings().all()

    # --- Assemble day-by-day structure ---
    days = {}

    for row in survival_rows:
        d = row["day_number"]
        days[d] = {
            "food_requirement_met": row["food_requirement_met"],
            "water_requirement_met": row["water_requirement_met"],
            "shelter_maintenance_paid": row["shelter_maintenance_paid"],
            "stamina_end_of_day": row["stamina_end_of_day"],
            "token_balance_end_of_day": row["token_balance_end_of_day"],
            "net_token_change": row["net_token_change"],
            "actions_by_type": {},
            "skill_levels": {},
            "sleep_events": [],
        }

    actions_by_day = defaultdict(dict)
    for row in action_rows:
        actions_by_day[row["day_number"]][row["action_type"]] = {
            "total": row["total"],
            "successful": row["successful"],
        }

    skills_by_day = defaultdict(dict)
    for row in skill_rows:
        skills_by_day[row["day_number"]][row["action_type"]] = row["skill_level"]

    sleep_by_day = defaultdict(list)
    for row in sleep_rows:
        sleep_by_day[row["day_number"]].append(dict(row))

    for d in days:
        days[d]["actions_by_type"] = actions_by_day.get(d, {})
        days[d]["skill_levels"] = skills_by_day.get(d, {})
        days[d]["sleep_events"] = sleep_by_day.get(d, [])

    return jsonify({
        "model_id": model_id,
        "experiment_group": model["experiment_group"],
        "run": model["run"],
        "is_alive": model["is_alive"],
        "days": days,
    })
