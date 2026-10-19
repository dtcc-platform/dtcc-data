#!/usr/bin/env bash
# post-setup-dtcc-data.sh — App-specific setup for dtcc-data
#
# Called by aws-setup.sh via POST_SETUP_SCRIPT. Runs on the remote host.
# Expects deploy.env variables to already be available (S3_BUCKET, DB_NAME, etc.)
set -euo pipefail

# aws-setup.sh exports DATABASE_URL; the atlas scripts read it from the environment
: "${DATABASE_URL:?DATABASE_URL must be set}"

# --- Sync GPKG data from S3 ---
if [ -n "${S3_BUCKET:-}" ]; then
    echo "=== Sync GPKG data from S3 ==="
    sudo mkdir -p /data/gpkg
    sudo chown -R ubuntu:ubuntu /data

    echo "Syncing GPKG data from s3://$S3_BUCKET/gpkg/ ..."
    aws s3 sync "s3://$S3_BUCKET/gpkg/" /data/gpkg/
    echo "[OK] GPKG data synced from S3"
    echo "  GPKG files: $(ls /data/gpkg/*.gpkg 2>/dev/null | wc -l)"
fi

# --- Ingest into PostGIS ---
echo "=== Ingest data into PostGIS ==="
export PATH="$HOME/.local/bin:$PATH"
cd ~/"$APP_NAME"
source .venv/bin/activate

# Ingest LiDAR tiles — read headers directly from S3 (no local download)
if [ -n "${S3_BUCKET:-}" ]; then
    echo "Ingesting LiDAR tile headers from s3://$S3_BUCKET/${S3_LAZ_PREFIX:-laz/} ..."
    python src/create-atlas-lidar.py \
        --s3-bucket "$S3_BUCKET" \
        --s3-prefix "${S3_LAZ_PREFIX:-laz/}" \
        --s3-region "${S3_REGION:-eu-north-1}" \
        --create-tables
fi

# Ingest GPKG tiles from local disk
if ls /data/gpkg/*.gpkg 1>/dev/null 2>&1; then
    echo "Ingesting GPKG tiles..."
    python src/create-atlas-gpkg.py /data/gpkg/ \
        --create-tables \
        --workers 0
else
    echo "No .gpkg files found, skipping GPKG ingestion"
fi

echo "[OK] Data ingested into PostGIS"
