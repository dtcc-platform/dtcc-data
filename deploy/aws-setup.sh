#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# DTCC Data — EC2 Server Setup
#
# Reads deploy/.env.aws, SSHs into the instance, installs everything,
# syncs data from S3, runs ingestion, starts the tile server.
# Usage: ./deploy/aws-setup.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env.aws"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Run aws-provision.sh first." >&2
    exit 1
fi

source "$ENV_FILE"

SSH_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
SSH_CMD="ssh $SSH_OPTS ubuntu@$PUBLIC_IP"
REPO_URL="https://github.com/dtcc-platform/dtcc-data.git"
REPO_BRANCH="${REPO_BRANCH:-feature/postgis-migration}"
DB_URL="postgresql://dtcc:dtcc@localhost:5432/dtcc_data"

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

log "=== Step 1: Install system dependencies ==="
$SSH_CMD << 'REMOTE_STEP1'
set -euo pipefail

# PostgreSQL 16 + PostGIS
sudo apt-get update -qq
sudo apt-get install -y -qq postgresql-16 postgresql-16-postgis-3 unzip

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

echo "[OK] System deps installed"
REMOTE_STEP1

log "=== Step 2: Deploy application ==="
$SSH_CMD << REMOTE_STEP2
set -euo pipefail
export PATH="\$HOME/.local/bin:\$PATH"

# Clone or update repo
if [ -d ~/dtcc-data ]; then
    cd ~/dtcc-data && git fetch && git checkout $REPO_BRANCH && git pull
else
    git clone --branch $REPO_BRANCH $REPO_URL ~/dtcc-data
fi

# Create venv and install
cd ~/dtcc-data
uv venv .venv --allow-existing
source .venv/bin/activate
uv pip install -e ".[test]"

echo "[OK] Application deployed"
REMOTE_STEP2

log "=== Step 3: Configure PostgreSQL + PostGIS ==="
$SSH_CMD << 'REMOTE_STEP3'
set -euo pipefail

# Create database user and database
sudo -u postgres psql -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dtcc') THEN CREATE ROLE dtcc LOGIN PASSWORD 'dtcc'; END IF; END \$\$;"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = 'dtcc_data'" | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE dtcc_data OWNER dtcc"
sudo -u postgres psql -d dtcc_data -c "CREATE EXTENSION IF NOT EXISTS postgis;"

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    if pg_isready -U dtcc -d dtcc_data > /dev/null 2>&1; then
        echo "PostgreSQL is ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: PostgreSQL not ready after 60s" >&2
        exit 1
    fi
    sleep 2
done

# Apply schema
PGPASSWORD=dtcc psql -h localhost -p 5432 -U dtcc -d dtcc_data -f ~/dtcc-data/src/schema.sql

echo "[OK] PostgreSQL + PostGIS configured and schema applied"
REMOTE_STEP3

log "=== Step 4: Sync GPKG data from S3 ==="
$SSH_CMD << REMOTE_STEP4
set -euo pipefail

sudo mkdir -p /data/gpkg
sudo chown -R ubuntu:ubuntu /data

echo "Syncing GPKG data from s3://$S3_BUCKET/gpkg/ ..."
aws s3 sync "s3://$S3_BUCKET/gpkg/" /data/gpkg/

echo "[OK] GPKG data synced from S3"
echo "  GPKG files: \$(ls /data/gpkg/*.gpkg 2>/dev/null | wc -l)"
REMOTE_STEP4

log "=== Step 5: Ingest into PostGIS ==="
$SSH_CMD << REMOTE_STEP5
set -euo pipefail
export PATH="\$HOME/.local/bin:\$PATH"
cd ~/dtcc-data
source .venv/bin/activate

DB_URL="postgresql://dtcc:dtcc@localhost:5432/dtcc_data"

# Ingest LiDAR tiles — read headers directly from S3 (no local download)
echo "Ingesting LiDAR tile headers from s3://$S3_BUCKET/laz/ ..."
python src/create-atlas-lidar.py --s3-bucket $S3_BUCKET --s3-prefix laz/ --s3-region ${REGION:-eu-north-1} --database-url "\$DB_URL" --create-tables

# Ingest GPKG tiles from local disk
if ls /data/gpkg/*.gpkg 1>/dev/null 2>&1; then
    echo "Ingesting GPKG tiles..."
    python src/create-atlas-gpkg.py /data/gpkg/ --database-url "\$DB_URL" --create-tables --workers 0
else
    echo "No .gpkg files found, skipping GPKG ingestion"
fi

echo "[OK] Data ingested into PostGIS"
REMOTE_STEP5

log "=== Step 6: Start FastAPI as systemd service ==="
$SSH_CMD << REMOTE_STEP6
set -euo pipefail

VENV_PYTHON="/home/ubuntu/dtcc-data/.venv/bin/python"
DB_URL="postgresql://dtcc:dtcc@localhost:5432/dtcc_data"

sudo tee /etc/systemd/system/dtcc-data.service > /dev/null << UNIT
[Unit]
Description=DTCC Data Tile Server
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/dtcc-data/src
Environment=DATABASE_URL=\${DB_URL}
Environment=LAZ_DIRECTORY=/data/laz
Environment=GPKG_DATA_DIRECTORY=/data/gpkg
Environment=S3_BUCKET=$S3_BUCKET
Environment=S3_LAZ_PREFIX=laz/
Environment=S3_REGION=${REGION:-eu-north-1}
Environment=PORT=8001
Environment=ENABLE_RATE_LIMIT=true
Environment=PYTHONPATH=/home/ubuntu/dtcc-data/src
ExecStart=\${VENV_PYTHON} -m uvicorn server:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable dtcc-data
sudo systemctl start dtcc-data

# Wait and verify
sleep 3
if curl -sf http://localhost:8001/healthz > /dev/null; then
    echo "[OK] Tile server is running!"
    curl -s http://localhost:8001/healthz
else
    echo "[WARN] Health check failed, checking logs..."
    sudo journalctl -u dtcc-data --no-pager -n 20
fi
REMOTE_STEP6

log ""
log "=========================================="
log "  Setup complete!"
log "  Server: http://$PUBLIC_IP:8001"
log "  Health: http://$PUBLIC_IP:8001/healthz"
log "  SSH:    ssh -i $KEY_FILE ubuntu@$PUBLIC_IP"
log "=========================================="
