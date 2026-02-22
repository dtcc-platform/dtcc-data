# AWS Deployment Scripts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Two bash scripts to provision and configure a fresh AWS EC2 instance running the DTCC tile server with PostGIS, data synced from S3.

**Architecture:** `aws-provision.sh` creates all AWS infrastructure (VPC, subnet, SG, IAM, EC2) via AWS CLI and writes resource IDs to `.env.aws`. `aws-setup.sh` reads that file, SSHs in, and configures Docker, PostGIS, data sync, ingestion, and systemd service.

**Tech Stack:** Bash, AWS CLI, Docker, systemd, uv

---

### Task 1: Add deploy directory and .gitignore entries

**Files:**
- Create: `deploy/.gitkeep`
- Modify: `.gitignore`

**Step 1: Create deploy directory**

```bash
mkdir -p deploy
touch deploy/.gitkeep
```

**Step 2: Add gitignore entries for secrets**

Append to `.gitignore` (create if it doesn't exist):

```
# AWS deployment secrets
deploy/.env.aws
deploy/*.pem
```

**Step 3: Commit**

```bash
git add deploy/.gitkeep .gitignore
git commit -m "Add deploy directory and gitignore for AWS secrets"
```

---

### Task 2: Create aws-provision.sh

**Files:**
- Create: `deploy/aws-provision.sh`

**Step 1: Write the provisioning script**

```bash
#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# DTCC Data — AWS Infrastructure Provisioning
#
# Creates: VPC, subnet, internet gateway, security group, IAM role, EC2 instance
# Output:  deploy/.env.aws with all resource IDs
# Usage:   ./deploy/aws-provision.sh
# Prereqs: aws cli configured with appropriate credentials
# =============================================================================

# --- Configuration (edit these) ---
REGION="${AWS_REGION:-eu-north-1}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.large}"
KEY_NAME="${KEY_NAME:-dtcc-data-key}"
S3_BUCKET="${S3_BUCKET:?S3_BUCKET must be set (e.g. export S3_BUCKET=my-dtcc-bucket)}"
PROJECT_NAME="${PROJECT_NAME:-dtcc-data}"

# --- Derived ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env.aws"
KEY_FILE="$SCRIPT_DIR/${KEY_NAME}.pem"
TAG_SPEC="ResourceType=__TYPE__,Tags=[{Key=Name,Value=${PROJECT_NAME}-__NAME__},{Key=Project,Value=${PROJECT_NAME}}]"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# --- Find Ubuntu 24.04 AMI ---
log "Finding Ubuntu 24.04 AMI in $REGION..."
AMI_ID=$(aws ec2 describe-images \
    --region "$REGION" \
    --owners 099720109477 \
    --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
              "Name=state,Values=available" \
    --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
    --output text)

if [ -z "$AMI_ID" ] || [ "$AMI_ID" = "None" ]; then
    echo "ERROR: Could not find Ubuntu 24.04 AMI in $REGION" >&2
    exit 1
fi
log "AMI: $AMI_ID"

# --- VPC ---
log "Creating VPC..."
VPC_ID=$(aws ec2 create-vpc \
    --region "$REGION" \
    --cidr-block 10.0.0.0/16 \
    --tag-specifications "$(echo "$TAG_SPEC" | sed 's/__TYPE__/vpc/; s/__NAME__/vpc/')" \
    --query 'Vpc.VpcId' --output text)
aws ec2 modify-vpc-attribute --region "$REGION" --vpc-id "$VPC_ID" --enable-dns-support
aws ec2 modify-vpc-attribute --region "$REGION" --vpc-id "$VPC_ID" --enable-dns-hostnames
log "VPC: $VPC_ID"

# --- Subnet ---
log "Creating subnet..."
AZ=$(aws ec2 describe-availability-zones \
    --region "$REGION" \
    --query 'AvailabilityZones[0].ZoneName' --output text)
SUBNET_ID=$(aws ec2 create-subnet \
    --region "$REGION" \
    --vpc-id "$VPC_ID" \
    --cidr-block 10.0.1.0/24 \
    --availability-zone "$AZ" \
    --tag-specifications "$(echo "$TAG_SPEC" | sed 's/__TYPE__/subnet/; s/__NAME__/subnet/')" \
    --query 'Subnet.SubnetId' --output text)
aws ec2 modify-subnet-attribute --region "$REGION" --subnet-id "$SUBNET_ID" --map-public-ip-on-launch
log "Subnet: $SUBNET_ID ($AZ)"

# --- Internet Gateway ---
log "Creating internet gateway..."
IGW_ID=$(aws ec2 create-internet-gateway \
    --region "$REGION" \
    --tag-specifications "$(echo "$TAG_SPEC" | sed 's/__TYPE__/internet-gateway/; s/__NAME__/igw/')" \
    --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --region "$REGION" --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID"
log "IGW: $IGW_ID"

# --- Route Table ---
log "Configuring route table..."
RTB_ID=$(aws ec2 describe-route-tables \
    --region "$REGION" \
    --filters "Name=vpc-id,Values=$VPC_ID" \
    --query 'RouteTables[0].RouteTableId' --output text)
aws ec2 create-route --region "$REGION" --route-table-id "$RTB_ID" --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID" > /dev/null
aws ec2 associate-route-table --region "$REGION" --route-table-id "$RTB_ID" --subnet-id "$SUBNET_ID" > /dev/null
log "Route table: $RTB_ID"

# --- Security Group ---
log "Creating security group..."
SG_ID=$(aws ec2 create-security-group \
    --region "$REGION" \
    --group-name "${PROJECT_NAME}-sg" \
    --description "DTCC Data tile server" \
    --vpc-id "$VPC_ID" \
    --tag-specifications "$(echo "$TAG_SPEC" | sed 's/__TYPE__/security-group/; s/__NAME__/sg/')" \
    --query 'GroupId' --output text)
# SSH
aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --protocol tcp --port 22 --cidr 0.0.0.0/0 > /dev/null
# API
aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --protocol tcp --port 8001 --cidr 0.0.0.0/0 > /dev/null
log "Security group: $SG_ID (ports 22, 8001)"

# --- Key Pair ---
if [ -f "$KEY_FILE" ]; then
    log "Key pair file already exists: $KEY_FILE"
else
    log "Creating key pair..."
    aws ec2 create-key-pair \
        --region "$REGION" \
        --key-name "$KEY_NAME" \
        --query 'KeyMaterial' --output text > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    log "Key pair saved: $KEY_FILE"
fi

# --- IAM Role + Instance Profile (S3 read-only) ---
log "Creating IAM role..."
ROLE_NAME="${PROJECT_NAME}-ec2-role"
PROFILE_NAME="${PROJECT_NAME}-ec2-profile"

# Trust policy for EC2
aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }' --no-cli-pager > /dev/null 2>&1 || log "IAM role already exists"

aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess 2>/dev/null || true

aws iam create-instance-profile \
    --instance-profile-name "$PROFILE_NAME" > /dev/null 2>&1 || true
aws iam add-role-to-instance-profile \
    --instance-profile-name "$PROFILE_NAME" \
    --role-name "$ROLE_NAME" 2>/dev/null || true

# IAM propagation delay
log "Waiting for IAM profile propagation..."
sleep 10

# --- EC2 Instance ---
log "Launching EC2 instance ($INSTANCE_TYPE)..."
INSTANCE_ID=$(aws ec2 run-instances \
    --region "$REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --subnet-id "$SUBNET_ID" \
    --iam-instance-profile "Name=$PROFILE_NAME" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":100,"VolumeType":"gp3"}}]' \
    --tag-specifications "$(echo "$TAG_SPEC" | sed 's/__TYPE__/instance/; s/__NAME__/server/')" \
    --query 'Instances[0].InstanceId' --output text)
log "Instance: $INSTANCE_ID"

log "Waiting for instance to be running..."
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"

PUBLIC_IP=$(aws ec2 describe-instances \
    --region "$REGION" \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
log "Public IP: $PUBLIC_IP"

# --- Write .env.aws ---
cat > "$ENV_FILE" <<ENVEOF
INSTANCE_ID=$INSTANCE_ID
PUBLIC_IP=$PUBLIC_IP
VPC_ID=$VPC_ID
SUBNET_ID=$SUBNET_ID
SG_ID=$SG_ID
IGW_ID=$IGW_ID
KEY_FILE=$KEY_FILE
KEY_NAME=$KEY_NAME
S3_BUCKET=$S3_BUCKET
REGION=$REGION
PROJECT_NAME=$PROJECT_NAME
ENVEOF

log "Environment saved to $ENV_FILE"
echo ""
echo "=========================================="
echo "  Provisioning complete!"
echo "  IP:  $PUBLIC_IP"
echo "  SSH: ssh -i $KEY_FILE ubuntu@$PUBLIC_IP"
echo ""
echo "  Next: ./deploy/aws-setup.sh"
echo "=========================================="
```

**Step 2: Make executable**

```bash
chmod +x deploy/aws-provision.sh
```

**Step 3: Commit**

```bash
git add deploy/aws-provision.sh
git commit -m "Add AWS infrastructure provisioning script"
```

---

### Task 3: Create aws-setup.sh

**Files:**
- Create: `deploy/aws-setup.sh`

**Step 1: Write the setup script**

```bash
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
DB_URL="postgresql://dtcc:dtcc@localhost:5433/dtcc_test"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# Wait for SSH to be ready
log "Waiting for SSH on $PUBLIC_IP..."
for i in $(seq 1 30); do
    if $SSH_CMD "echo ok" > /dev/null 2>&1; then
        break
    fi
    sleep 5
done

log "=== Step 1: Install system dependencies ==="
$SSH_CMD << 'REMOTE_STEP1'
set -euo pipefail

# Docker
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker ubuntu
fi

# Docker compose plugin
sudo apt-get update -qq
sudo apt-get install -y -qq docker-compose-plugin awscli

# uv
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

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
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[test]"

echo "[OK] Application deployed"
REMOTE_STEP2

log "=== Step 3: Start PostGIS ==="
$SSH_CMD << 'REMOTE_STEP3'
set -euo pipefail

cd ~/dtcc-data

# Need newgrp or re-login for docker group — use sudo instead
sudo docker compose -f docker-compose.test.yml up -d

# Wait for PostGIS to be healthy
echo "Waiting for PostGIS..."
for i in $(seq 1 30); do
    if sudo docker compose -f docker-compose.test.yml exec -T db pg_isready -U dtcc -d dtcc_test > /dev/null 2>&1; then
        echo "PostGIS is ready"
        break
    fi
    sleep 2
done

# Apply schema
sudo apt-get install -y -qq postgresql-client
PGPASSWORD=dtcc psql -h localhost -p 5433 -U dtcc -d dtcc_test -f src/schema.sql

echo "[OK] PostGIS running and schema applied"
REMOTE_STEP3

log "=== Step 4: Sync data from S3 ==="
$SSH_CMD << REMOTE_STEP4
set -euo pipefail

sudo mkdir -p /data/laz /data/gpkg
sudo chown -R ubuntu:ubuntu /data

aws s3 sync s3://$S3_BUCKET/laz/ /data/laz/ --no-sign-request 2>/dev/null \
    || aws s3 sync s3://$S3_BUCKET/laz/ /data/laz/

aws s3 sync s3://$S3_BUCKET/gpkg/ /data/gpkg/ --no-sign-request 2>/dev/null \
    || aws s3 sync s3://$S3_BUCKET/gpkg/ /data/gpkg/

echo "[OK] Data synced from S3"
echo "  LAZ files: \$(ls /data/laz/*.laz 2>/dev/null | wc -l)"
echo "  GPKG files: \$(ls /data/gpkg/*.gpkg 2>/dev/null | wc -l)"
REMOTE_STEP4

log "=== Step 5: Ingest into PostGIS ==="
$SSH_CMD << 'REMOTE_STEP5'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd ~/dtcc-data
source .venv/bin/activate

DB_URL="postgresql://dtcc:dtcc@localhost:5433/dtcc_test"

# Ingest LiDAR tiles
if ls /data/laz/*.laz 1>/dev/null 2>&1; then
    python src/create-atlas-lidar.py /data/laz/ --database-url "$DB_URL" --create-tables
else
    echo "No .laz files found, skipping LiDAR ingestion"
fi

# Ingest GPKG tiles
if ls /data/gpkg/*.gpkg 1>/dev/null 2>&1; then
    python src/create-atlas-gpkg.py /data/gpkg/ --database-url "$DB_URL" --create-tables --workers 0
else
    echo "No .gpkg files found, skipping GPKG ingestion"
fi

echo "[OK] Data ingested into PostGIS"
REMOTE_STEP5

log "=== Step 6: Start FastAPI as systemd service ==="
$SSH_CMD << 'REMOTE_STEP6'
set -euo pipefail

VENV_PYTHON="/home/ubuntu/dtcc-data/.venv/bin/python"
DB_URL="postgresql://dtcc:dtcc@localhost:5433/dtcc_test"

sudo tee /etc/systemd/system/dtcc-data.service > /dev/null << UNIT
[Unit]
Description=DTCC Data Tile Server
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/dtcc-data/src
Environment=DATABASE_URL=$DB_URL
Environment=LAZ_DIRECTORY=/data/laz
Environment=GPKG_DATA_DIRECTORY=/data/gpkg
Environment=PORT=8001
Environment=ENABLE_RATE_LIMIT=true
Environment=PYTHONPATH=/home/ubuntu/dtcc-data/src
ExecStart=$VENV_PYTHON -m uvicorn server:app --host 0.0.0.0 --port 8001
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
```

**Step 2: Make executable**

```bash
chmod +x deploy/aws-setup.sh
```

**Step 3: Commit**

```bash
git add deploy/aws-setup.sh
git commit -m "Add EC2 server setup script"
```

---

### Task 4: Test scripts locally (dry-run verification)

**Step 1: Verify provision script syntax**

```bash
bash -n deploy/aws-provision.sh
```

Expected: No output (syntax OK).

**Step 2: Verify setup script syntax**

```bash
bash -n deploy/aws-setup.sh
```

Expected: No output (syntax OK).

**Step 3: Commit (no changes needed if syntax is OK)**

All code already committed. This is a verification step only.
