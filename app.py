import os
from dotenv import load_dotenv
from flask import Flask, jsonify
from sqlalchemy import text
from extensions import db

from blueprints.models import models_bp
from blueprints.actions import actions_bp
from blueprints.transactions import transactions_bp
from blueprints.inventory import inventory_bp
from blueprints.communications import communications_bp
from blueprints.threads import threads_bp
from blueprints.nodes import nodes_bp
from blueprints.survival import survival_bp
from blueprints.events import events_bp
from blueprints.sleep import sleep_bp
from blueprints.summary import summary_bp
from blueprints.decision_log import decision_log_bp

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = os.getenv("FLASK_SECRET_KEY")

db.init_app(app)

app.register_blueprint(models_bp)
app.register_blueprint(actions_bp)
app.register_blueprint(transactions_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(communications_bp)
app.register_blueprint(threads_bp)
app.register_blueprint(nodes_bp)
app.register_blueprint(survival_bp)
app.register_blueprint(events_bp)
app.register_blueprint(sleep_bp)
app.register_blueprint(summary_bp)
app.register_blueprint(decision_log_bp)

@app.route("/health", methods=["GET"])
def health():
    try:
        db.session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"unreachable: {e}"

    return jsonify({
        "status": "ok",
        "database": db_status,
    })

if __name__ == "__main__":
    app.run(debug=False, port=5000)
