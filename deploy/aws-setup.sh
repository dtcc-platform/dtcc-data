#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# EC2 Server Setup
#
# Reads deploy/deploy.env + deploy/.env.aws, SSHs into the instance, installs
# dependencies, deploys app, optionally sets up DB + runs post-setup script,
# and starts the app as a systemd service.
# Config:  deploy/deploy.env (copy from deploy.env.example)
# Usage:   ./deploy/aws-setup.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_ENV="$SCRIPT_DIR/deploy.env"
ENV_FILE="$SCRIPT_DIR/.env.aws"

if [ ! -f "$DEPLOY_ENV" ]; then
    echo "ERROR: $DEPLOY_ENV not found." >&2
    echo "Copy deploy.env.example to deploy.env and edit for your project." >&2
    exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Run aws-provision.sh first." >&2
    exit 1
fi

source "$DEPLOY_ENV"
source "$ENV_FILE"

# --- Configuration (with defaults) ---
REPO_URL="${REPO_URL:?REPO_URL must be set in deploy.env}"
REPO_BRANCH="${REPO_BRANCH:-main}"
APP_NAME="${APP_NAME:-dtcc-data}"
FASTAPI_MODULE="${FASTAPI_MODULE:-server:app}"
FASTAPI_PORT="${FASTAPI_PORT:-8001}"
WORK_DIR="${WORK_DIR:-src}"
PYTHON_EXTRAS="${PYTHON_EXTRAS:-.[test]}"
S3_BUCKET="${S3_BUCKET:-}"
S3_LAZ_PREFIX="${S3_LAZ_PREFIX:-laz/}"
S3_REGION="${S3_REGION:-eu-north-1}"
DB_NAME="${DB_NAME:-}"
DB_USER="${DB_USER:-dtcc}"
DB_PASS="${DB_PASS:-dtcc}"
SYSTEMD_ENV="${SYSTEMD_ENV:-}"
POST_SETUP_SCRIPT="${POST_SETUP_SCRIPT:-}"
EXTRA_REPOS="${EXTRA_REPOS:-}"
CONDA_PACKAGES="${CONDA_PACKAGES:-}"

SSH_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
SSH_CMD="ssh $SSH_OPTS ubuntu@$PUBLIC_IP"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# Wait for SSH to be ready
log "Waiting for SSH on $PUBLIC_IP..."
for i in $(seq 1 30); do
    if $SSH_CMD "echo ok" > /dev/null 2>&1; then
        log "SSH is ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: SSH not available after 150s" >&2
        exit 1
    fi
    sleep 5
done

# =============================================================================
# Step 1: Install system dependencies
# =============================================================================
log "=== Step 1: Install system dependencies ==="
if [ -n "$DB_NAME" ]; then
    log "PostgreSQL requested (DB_NAME=$DB_NAME)"
    $SSH_CMD << 'REMOTE_STEP1_DB'
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq postgresql-16 postgresql-16-postgis-3 unzip
echo "[OK] PostgreSQL + PostGIS installed"
REMOTE_STEP1_DB
else
    log "No DB_NAME set, skipping PostgreSQL"
    $SSH_CMD << 'REMOTE_STEP1_NODB'
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq unzip
echo "[OK] Base packages installed"
REMOTE_STEP1_NODB
fi

$SSH_CMD << 'REMOTE_STEP1_TOOLS'
set -euo pipefail

# AWS CLI v2
if ! command -v aws &> /dev/null; then
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
    unzip -q /tmp/awscliv2.zip -d /tmp
    sudo /tmp/aws/install
    rm -rf /tmp/awscliv2.zip /tmp/aws
fi

# uv
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# Ensure PATH includes uv
grep -q 'local/bin' ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

echo "[OK] System tools installed"
REMOTE_STEP1_TOOLS

if [ -n "$CONDA_PACKAGES" ]; then
    log "Conda packages requested, installing Miniforge..."
    $SSH_CMD << 'REMOTE_STEP1_CONDA'
set -euo pipefail
if [ ! -d "$HOME/miniforge3" ]; then
    curl -fsSL -o /tmp/miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
    bash /tmp/miniforge.sh -b -p "$HOME/miniforge3"
    rm /tmp/miniforge.sh
fi
echo "[OK] Miniforge installed"
REMOTE_STEP1_CONDA
fi

# =============================================================================
# Step 2: Deploy application
# =============================================================================
log "=== Step 2: Deploy application ==="
$SSH_CMD << REMOTE_STEP2
set -euo pipefail
export PATH="\$HOME/.local/bin:\$PATH"

# Clone or update extra repos
for entry in $EXTRA_REPOS; do
    REPO_PART="\${entry%@*}"
    BRANCH_PART="\${entry#*@}"
    DIR_NAME="\$(basename "\$REPO_PART" .git)"
    if [ -d ~/"\$DIR_NAME" ]; then
        cd ~/"\$DIR_NAME" && git fetch && git checkout "\$BRANCH_PART" && git pull
        cd ~
    else
        git clone --branch "\$BRANCH_PART" "\$REPO_PART" ~/"\$DIR_NAME"
    fi
done

# Clone or update main app repo
if [ -d ~/$APP_NAME ]; then
    cd ~/$APP_NAME && git fetch && git checkout $REPO_BRANCH && git pull
else
    git clone --branch $REPO_BRANCH $REPO_URL ~/$APP_NAME
fi

if [ -n "$CONDA_PACKAGES" ]; then
    # --- Conda branch ---
    export PATH="\$HOME/miniforge3/bin:\$PATH"
    if conda env list | grep -q "^${APP_NAME} "; then
        echo "Conda env $APP_NAME already exists, updating..."
        conda install -y -n $APP_NAME $CONDA_PACKAGES
    else
        conda create -y -n $APP_NAME python=3.12 $CONDA_PACKAGES
    fi
    eval "\$(conda shell.bash hook)"
    conda activate $APP_NAME

    # pip install extra repos
    for entry in $EXTRA_REPOS; do
        REPO_PART="\${entry%@*}"
        DIR_NAME="\$(basename "\$REPO_PART" .git)"
        pip install -e ~/"\$DIR_NAME"
    done

    # pip install main app
    cd ~/$APP_NAME
    pip install -e "$PYTHON_EXTRAS"
else
    # --- uv branch ---
    cd ~/$APP_NAME
    uv venv .venv --allow-existing
    source .venv/bin/activate

    # uv pip install extra repos
    for entry in $EXTRA_REPOS; do
        REPO_PART="\${entry%@*}"
        DIR_NAME="\$(basename "\$REPO_PART" .git)"
        uv pip install -e ~/"\$DIR_NAME"
    done

    # uv pip install main app
    uv pip install -e "$PYTHON_EXTRAS"
fi

echo "[OK] Application deployed"
REMOTE_STEP2

# =============================================================================
# Step 3: Configure PostgreSQL + PostGIS (only if DB_NAME is set)
# =============================================================================
if [ -n "$DB_NAME" ]; then
    log "=== Step 3: Configure PostgreSQL + PostGIS ==="
    $SSH_CMD << REMOTE_STEP3
set -euo pipefail

# Create database user and database
sudo -u postgres psql -c "DO \\\$\\\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASS'; END IF; END \\\$\\\$;"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER"
sudo -u postgres psql -d $DB_NAME -c "CREATE EXTENSION IF NOT EXISTS postgis;"

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
for i in \$(seq 1 30); do
    if pg_isready -U $DB_USER -d $DB_NAME > /dev/null 2>&1; then
        echo "PostgreSQL is ready"
        break
    fi
    if [ "\$i" -eq 30 ]; then
        echo "ERROR: PostgreSQL not ready after 60s" >&2
        exit 1
    fi
    sleep 2
done

# Apply schema if it exists
SCHEMA_FILE=~/${APP_NAME}/${WORK_DIR}/schema.sql
if [ -f "\$SCHEMA_FILE" ]; then
    PGPASSWORD=$DB_PASS psql -h localhost -p 5432 -U $DB_USER -d $DB_NAME -f "\$SCHEMA_FILE"
    echo "[OK] Schema applied"
else
    echo "[SKIP] No schema.sql found at \$SCHEMA_FILE"
fi

echo "[OK] PostgreSQL + PostGIS configured"
REMOTE_STEP3
else
    log "=== Step 3: Skipped (no DB_NAME) ==="
fi

# =============================================================================
# Step 4: Run post-setup script (if configured)
# =============================================================================
if [ -n "$POST_SETUP_SCRIPT" ]; then
    FULL_SCRIPT_PATH="$SCRIPT_DIR/../$POST_SETUP_SCRIPT"
    if [ ! -f "$FULL_SCRIPT_PATH" ]; then
        # Also try relative to repo root
        FULL_SCRIPT_PATH="$(cd "$SCRIPT_DIR/.." && pwd)/$POST_SETUP_SCRIPT"
    fi
    if [ ! -f "$FULL_SCRIPT_PATH" ]; then
        echo "ERROR: POST_SETUP_SCRIPT not found: $POST_SETUP_SCRIPT" >&2
        exit 1
    fi

    log "=== Step 4: Running post-setup script ($POST_SETUP_SCRIPT) ==="

    # Export all config vars so the script can use them, then send script content
    $SSH_CMD << REMOTE_STEP4
set -euo pipefail
export APP_NAME="$APP_NAME"
export DB_NAME="${DB_NAME:-}"
export DB_USER="${DB_USER:-}"
export DB_PASS="${DB_PASS:-}"
export S3_BUCKET="${S3_BUCKET:-}"
export S3_LAZ_PREFIX="${S3_LAZ_PREFIX:-laz/}"
export S3_REGION="${S3_REGION:-eu-north-1}"
export REGION="${REGION:-eu-north-1}"
export CONDA_PACKAGES="$CONDA_PACKAGES"
export EXTRA_REPOS="$EXTRA_REPOS"

# Activate the correct Python env
if [ -n "$CONDA_PACKAGES" ]; then
    export PATH="\$HOME/miniforge3/bin:\$PATH"
    eval "\$(conda shell.bash hook)"
    conda activate $APP_NAME
else
    source ~/$APP_NAME/.venv/bin/activate
fi

$(cat "$FULL_SCRIPT_PATH")
REMOTE_STEP4
else
    log "=== Step 4: Skipped (no POST_SETUP_SCRIPT) ==="
fi

# =============================================================================
# Step 5: Start FastAPI as systemd service
# =============================================================================
log "=== Step 5: Start systemd service ==="

# Build environment lines for the systemd unit
ENV_LINES="Environment=PORT=$FASTAPI_PORT"
ENV_LINES="$ENV_LINES
Environment=ENABLE_RATE_LIMIT=true"

if [ -n "$DB_NAME" ]; then
    DB_URL="postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}"
    ENV_LINES="$ENV_LINES
Environment=DATABASE_URL=$DB_URL"
fi

if [ -n "$S3_BUCKET" ]; then
    ENV_LINES="$ENV_LINES
Environment=S3_BUCKET=$S3_BUCKET
Environment=S3_LAZ_PREFIX=$S3_LAZ_PREFIX
Environment=S3_REGION=$S3_REGION"
fi

# Add extra env vars from SYSTEMD_ENV (one per line, skip blanks)
if [ -n "$SYSTEMD_ENV" ]; then
    while IFS= read -r line; do
        line="$(echo "$line" | xargs)"  # trim whitespace
        [ -z "$line" ] && continue
        ENV_LINES="$ENV_LINES
Environment=$line"
    done <<< "$SYSTEMD_ENV"
fi

# Determine systemd dependencies
AFTER_DEPS="network.target"
WANTS_DEPS=""
if [ -n "$DB_NAME" ]; then
    AFTER_DEPS="$AFTER_DEPS postgresql.service"
    WANTS_DEPS="Wants=postgresql.service"
fi

if [ -n "$CONDA_PACKAGES" ]; then
    VENV_PYTHON="/home/ubuntu/miniforge3/envs/${APP_NAME}/bin/python"
    CONDA_PREFIX_VAL="/home/ubuntu/miniforge3/envs/${APP_NAME}"
    ENV_LINES="$ENV_LINES
Environment=PATH=${CONDA_PREFIX_VAL}/bin:/usr/local/bin:/usr/bin:/bin
Environment=CONDA_PREFIX=${CONDA_PREFIX_VAL}
Environment=LD_LIBRARY_PATH=${CONDA_PREFIX_VAL}/lib"
else
    VENV_PYTHON="/home/ubuntu/${APP_NAME}/.venv/bin/python"
fi

$SSH_CMD << REMOTE_STEP5
set -euo pipefail

sudo tee /etc/systemd/system/${APP_NAME}.service > /dev/null << UNIT
[Unit]
Description=${APP_NAME} server
After=${AFTER_DEPS}
${WANTS_DEPS}

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/${APP_NAME}/${WORK_DIR}
${ENV_LINES}
ExecStart=${VENV_PYTHON} -m uvicorn ${FASTAPI_MODULE} --host 0.0.0.0 --port ${FASTAPI_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable ${APP_NAME}
sudo systemctl start ${APP_NAME}

# Wait and verify
sleep 3
if curl -sf http://localhost:${FASTAPI_PORT}/healthz > /dev/null; then
    echo "[OK] Server is running!"
    curl -s http://localhost:${FASTAPI_PORT}/healthz
else
    echo "[WARN] Health check failed, checking logs..."
    sudo journalctl -u ${APP_NAME} --no-pager -n 20
fi
REMOTE_STEP5

log ""
log "=========================================="
log "  Setup complete!"
log "  Server: http://$PUBLIC_IP:$FASTAPI_PORT"
log "  Health: http://$PUBLIC_IP:$FASTAPI_PORT/healthz"
log "  SSH:    ssh -i $KEY_FILE ubuntu@$PUBLIC_IP"
log "=========================================="
