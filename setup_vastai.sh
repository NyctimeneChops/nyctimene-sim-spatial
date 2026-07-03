#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DB_NAME="nyctimene_ledger"
DB_USER="postgres"
DB_PASS="nyctimene"

echo "=== nyctimene experiment setup ==="
echo

# ── 1. PostgreSQL ────────────────────────────────────────────────────────────
echo "[1/6] Installing PostgreSQL..."
apt-get update -qq
apt-get install -y -qq postgresql postgresql-contrib

echo "[2/6] Starting PostgreSQL and creating database..."
service postgresql start

# Wait for the server to accept connections (up to 30 s).
for i in $(seq 1 30); do
    pg_isready -q && break
    sleep 1
done
pg_isready -q || { echo "ERROR: PostgreSQL did not start in time"; exit 1; }

sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';"

if sudo -u postgres psql -lqt | cut -d '|' -f1 | grep -qw "$DB_NAME"; then
    echo "  Database '$DB_NAME' already exists — skipping creation."
else
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;"
    echo "  Database '$DB_NAME' created."
fi

echo "  Applying schema..."
PGPASSWORD="$DB_PASS" psql -U "$DB_USER" -h localhost -d "$DB_NAME" -f "$SCRIPT_DIR/schema.sql"
echo "  Schema applied."

# ── 2. CUDA verification ─────────────────────────────────────────────────────
echo
echo "[3/6] Verifying CUDA availability..."
if ! nvidia-smi; then
    echo "ERROR: nvidia-smi failed — CUDA is not available on this instance."
    echo "       Aborting setup. Please provision a GPU-enabled instance."
    exit 1
fi
echo "  CUDA verified."

# ── 3. Python dependencies ───────────────────────────────────────────────────
echo
echo "[4/6] Installing Python dependencies (torch may take a few minutes)..."
pip install -r "$SCRIPT_DIR/requirements.txt"

# ── 4. Pre-download Hugging Face model ───────────────────────────────────────
echo
echo "[5/6] Pre-downloading microsoft/Phi-3-mini-4k-instruct..."
python3 -c "from transformers import AutoTokenizer, AutoModelForCausalLM; AutoTokenizer.from_pretrained('microsoft/Phi-3-mini-4k-instruct'); AutoModelForCausalLM.from_pretrained('microsoft/Phi-3-mini-4k-instruct', torch_dtype='auto', device_map='auto')"
echo "  Model cached."

# ── 5. .env file ─────────────────────────────────────────────────────────────
echo
echo "[6/6] Writing .env file..."
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    echo "  .env already exists — skipping. Delete it and re-run to regenerate."
else
    cat > "$ENV_FILE" <<EOF
DATABASE_URL=postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME
FLASK_SECRET_KEY=REPLACE_ME
EXPERIMENT_RUN_NAME=REPLACE_ME
EOF
    echo "  .env created."
    echo "  Fill in FLASK_SECRET_KEY and EXPERIMENT_RUN_NAME before starting."
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo
echo "=== Setup complete ==="
echo "  Edit .env, then start the experiment with: python main.py"
