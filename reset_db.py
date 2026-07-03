import os
import re
import sys

import psycopg2
from dotenv import load_dotenv

DROP_ORDER = [
    "thread_presence_windows",
    "thread_votes",
    "communications",
    "node_activity_log",
    "sleep_log",
    "events",
    "inventory",
    "survival_checks",
    "direct_proposals",
    "transactions",
    "decision_log",
    "actions",
    "skills",
    "threads",
    "node_state",
    "models",
]


def main():
    print("This will delete all experiment data. Type RESET to confirm.")
    try:
        response = input().strip()
    except (EOFError, KeyboardInterrupt):
        response = ""
    if response != "RESET":
        print("Aborted.")
        sys.exit(0)

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    # psycopg2 does not recognise the SQLAlchemy dialect prefix.
    db_url = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)

    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    try:
        with open(schema_path) as f:
            schema_sql = f.read()
    except FileNotFoundError:
        print(f"ERROR: schema.sql not found at {schema_path}")
        sys.exit(1)

    try:
        conn = psycopg2.connect(db_url)
    except Exception as exc:
        print(f"ERROR: could not connect to database: {exc}")
        sys.exit(1)

    conn.autocommit = True
    cur = conn.cursor()

    print()
    print("Dropping tables...")
    for table in DROP_ORDER:
        cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        print(f"  Dropped:  {table}")

    print()
    print("Recreating schema...")
    # Strip SQL line comments before splitting so semicolons inside
    # comments don't cleave statements.
    decommented = "\n".join(
        line.split("--")[0] for line in schema_sql.split("\n")
    )
    statements = [s.strip() for s in decommented.split(";") if s.strip()]
    for stmt in statements:
        cur.execute(stmt)

    created = re.findall(r"(?i)CREATE TABLE (\w+)", schema_sql)
    for table in created:
        print(f"  Created:  {table}")

    cur.close()
    conn.close()

    print()
    print(f"Reset complete: {len(DROP_ORDER)} tables dropped, {len(created)} tables recreated.")


if __name__ == "__main__":
    main()
