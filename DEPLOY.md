# Deploying on AWS

## Prerequisites

- AWS CLI installed and configured (`aws configure`)
- IAM user with permissions for: EC2, VPC, IAM, S3

## Quick Start

```bash
# 1. Create your deploy config
cp deploy/deploy.env.example deploy/deploy.env
# Edit deploy/deploy.env with your values

# 2. If using S3, create bucket and upload data
aws s3 mb s3://my-dtcc-bucket --region eu-north-1
aws s3 sync /path/to/local/laz/ s3://my-dtcc-bucket/laz/
aws s3 sync /path/to/local/gpkg/ s3://my-dtcc-bucket/gpkg/

# 3. Provision AWS infrastructure
./deploy/aws-provision.sh

# 4. Configure the server
./deploy/aws-setup.sh
```

The server will be available at `http://<public-ip>:<FASTAPI_PORT>`.

## Configuration

All configuration is in `deploy/deploy.env` (gitignored). Copy from `deploy/deploy.env.example` and edit.

### Required Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `REPO_URL` | — | Git repository URL |
| `REPO_BRANCH` | `main` | Branch to deploy |

### AWS Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `eu-north-1` | AWS region |
| `INSTANCE_TYPE` | `t3.medium` | EC2 instance type |
| `EBS_VOLUME_SIZE` | `100` | Root volume size in GB |
| `KEY_NAME` | `dtcc-data-key` | SSH key pair name |
| `PROJECT_NAME` | `dtcc-data` | Prefix for all AWS resource names |
| `SG_PORTS` | `22 8001` | Space-separated inbound TCP ports |

### App Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `dtcc-data` | Systemd service name + clone directory |
| `FASTAPI_MODULE` | `server:app` | Uvicorn module path |
| `FASTAPI_PORT` | `8001` | Port for the FastAPI server |
| `WORK_DIR` | `src` | Working directory relative to repo root |
| `PYTHON_EXTRAS` | `.[test]` | pip install extras |

### Optional: Extra Repos

Clone and `pip install -e` additional repositories before the main app. Useful when your app depends on libraries not available on PyPI.

| Variable | Default | Description |
|----------|---------|-------------|
| `EXTRA_REPOS` | *(empty)* | Space-separated `url@branch` pairs |

```bash
EXTRA_REPOS="https://github.com/dtcc-platform/dtcc-sim.git@main"
```

### Optional: Conda

When set, creates a conda environment (via Miniforge) instead of a uv venv. Use this for packages only available on conda-forge.

| Variable | Default | Description |
|----------|---------|-------------|
| `CONDA_PACKAGES` | *(empty)* | Space-separated conda-forge packages. Empty = uv-only |

```bash
CONDA_PACKAGES="fenics-dolfinx mpich pyvista"
```

When `CONDA_PACKAGES` is set, the systemd service automatically gets `PATH`, `CONDA_PREFIX`, and `LD_LIBRARY_PATH` configured for the conda env.

### Optional: S3

Leave `S3_BUCKET` empty to skip IAM role creation and S3 access.

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_BUCKET` | *(empty)* | S3 bucket name. Empty = no S3 |
| `S3_LAZ_PREFIX` | `laz/` | Key prefix for .laz files |
| `S3_REGION` | `eu-north-1` | Region for S3 client |

### Optional: PostgreSQL

Leave `DB_NAME` empty to skip PostgreSQL installation and database setup entirely.

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_NAME` | *(empty)* | Database name. Empty = no DB |
| `DB_USER` | `dtcc` | Database user |
| `DB_PASS` | `dtcc` | Database password |

### Optional: Systemd Extra Env Vars

```bash
SYSTEMD_ENV="
PYTHONPATH=/home/ubuntu/dtcc-data/src
MY_CUSTOM_VAR=value
"
```

### Optional: Post-Setup Script

Set `POST_SETUP_SCRIPT` to a script path (relative to repo root) that runs after base setup but before the systemd service starts. This is where app-specific steps go (data sync, ingestion, etc.).

```bash
POST_SETUP_SCRIPT=deploy/post-setup-dtcc-data.sh
```

The script runs on the remote host with all deploy.env variables exported.

### Example: dtcc-data config

```bash
REPO_URL=https://github.com/dtcc-platform/dtcc-data.git
REPO_BRANCH=main
APP_NAME=dtcc-data
FASTAPI_MODULE=server:app
FASTAPI_PORT=8001
WORK_DIR=src
PYTHON_EXTRAS=".[test]"
S3_BUCKET=my-dtcc-bucket
DB_NAME=dtcc_data
DB_USER=dtcc
DB_PASS=dtcc
SYSTEMD_ENV="
PYTHONPATH=/home/ubuntu/dtcc-data/src
"
POST_SETUP_SCRIPT=deploy/post-setup-dtcc-data.sh
```

### Example: dtcc-atlas config

dtcc-atlas depends on dtcc-sim (which needs FEniCSx from conda-forge) and has a Svelte frontend:

```bash
REPO_URL=https://github.com/dtcc-platform/dtcc-atlas.git
REPO_BRANCH=main
INSTANCE_TYPE=t3.xlarge
EBS_VOLUME_SIZE=50
KEY_NAME=dtcc-atlas-key
PROJECT_NAME=dtcc-atlas
SG_PORTS="22 8000"
APP_NAME=dtcc-atlas
FASTAPI_MODULE=server.main:app
FASTAPI_PORT=8000
WORK_DIR=.
PYTHON_EXTRAS="."
EXTRA_REPOS="https://github.com/dtcc-platform/dtcc-sim.git@main"
CONDA_PACKAGES="fenics-dolfinx mpich pyvista"
S3_BUCKET=
DB_NAME=
POST_SETUP_SCRIPT=deploy/post-setup-dtcc-atlas.sh
```

## What Gets Created

### Infrastructure (`aws-provision.sh`)

| Resource | Details |
|----------|---------|
| VPC | `10.0.0.0/16` with DNS support |
| Subnet | `10.0.1.0/24`, public, auto-assign IP |
| Internet Gateway | Attached to VPC |
| Security Group | Inbound ports from `SG_PORTS` |
| Key Pair | PEM saved to `deploy/<KEY_NAME>.pem` |
| IAM Role | EC2 role with S3 read-only (only if `S3_BUCKET` set) |
| EC2 Instance | Ubuntu 24.04, `EBS_VOLUME_SIZE` GB gp3 EBS |

### Server Stack (`aws-setup.sh`)

| Component | Details |
|-----------|---------|
| PostgreSQL 16 + PostGIS 3 | Only if `DB_NAME` set |
| Python 3.12 | Managed by uv (or conda if `CONDA_PACKAGES` set) |
| FastAPI | Via systemd, configured from deploy.env |

## Generated Files

These files are created locally and **gitignored**:

| File | Contents |
|------|----------|
| `deploy/deploy.env` | Your per-app config |
| `deploy/.env.aws` | AWS resource IDs, public IP |
| `deploy/<KEY_NAME>.pem` | SSH private key |

## Server Management

After deployment, SSH into the instance:

```bash
ssh -i deploy/<KEY_NAME>.pem ubuntu@<public-ip>
```

### Service commands

```bash
# Check status
sudo systemctl status <APP_NAME>

# View logs
sudo journalctl -u <APP_NAME> -f

# Restart
sudo systemctl restart <APP_NAME>

# Stop
sudo systemctl stop <APP_NAME>
```

### PostGIS (if DB_NAME is set)

```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Connect to database
PGPASSWORD=<DB_PASS> psql -h localhost -U <DB_USER> -d <DB_NAME>
```

## S3 Bucket Structure

When using S3, the bucket should contain your geodata in these prefixes:

```
s3://my-bucket/
  laz/          ← LiDAR .laz files
  gpkg/         ← GeoPackage .gpkg files
```

### Download data from Lantmateriet Geotorget

Instead of syncing from S3, you can download data directly from Lantmateriet's Geotorget API using an order ID. The script downloads zip archives, extracts `.laz`/`.gpkg` files, and ingests them into PostGIS automatically.

```bash
cd ~/dtcc-data && source .venv/bin/activate

# Download and ingest (full pipeline)
python src/download-geotorget.py <order-uuid> \
  --database-url postgresql://dtcc:dtcc@localhost:5432/dtcc_data

# Download only (no ingestion)
python src/download-geotorget.py <order-uuid> --output-dir /data --no-ingest
```

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `ORDER_ID` | Yes | -- | Geotorget order UUID |
| `--output-dir` | No | `/data` | Base directory for `laz/` and `gpkg/` subdirs |
| `--database-url` | No | `$DATABASE_URL` | PostGIS connection string |
| `--no-ingest` | No | false | Skip PostGIS ingestion after download |

You can find your order IDs at https://geotorget.lantmateriet.se/mitt-konto/arende.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Health check |
| `POST` | `/lidar/tiles` | Find LiDAR tiles intersecting bbox |
| `POST` | `/gpkg/tiles` | Find GPKG tiles intersecting bbox |
| `GET` | `/files/lidar/{filename}` | Download .laz file |
| `GET` | `/files/gpkg/{filename}` | Download .gpkg file |

### Example: query LiDAR tiles

```bash
curl -X POST http://<public-ip>:8001/lidar/tiles \
  -H "Content-Type: application/json" \
  -d '{"xmin": 267000, "ymin": 6519000, "xmax": 268000, "ymax": 6520000}'
```

### Example: query GPKG tiles

```bash
curl -X POST http://<public-ip>:8001/gpkg/tiles \
  -H "Content-Type: application/json" \
  -d '{"minx": 268000, "miny": 6473500, "maxx": 278000, "maxy": 6483500}'
```

## Teardown

To remove all AWS resources, delete them in reverse order:

```bash
source deploy/.env.aws

# Terminate EC2
aws ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID
aws ec2 wait instance-terminated --region $REGION --instance-ids $INSTANCE_ID

# Remove IAM (only if S3 was configured)
aws iam remove-role-from-instance-profile --instance-profile-name ${PROJECT_NAME}-ec2-profile --role-name ${PROJECT_NAME}-ec2-role
aws iam delete-instance-profile --instance-profile-name ${PROJECT_NAME}-ec2-profile
aws iam detach-role-policy --role-name ${PROJECT_NAME}-ec2-role --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
aws iam delete-role --role-name ${PROJECT_NAME}-ec2-role

# Remove key pair
aws ec2 delete-key-pair --region $REGION --key-name $KEY_NAME

# Remove networking
aws ec2 delete-security-group --region $REGION --group-id $SG_ID
aws ec2 detach-internet-gateway --region $REGION --internet-gateway-id $IGW_ID --vpc-id $VPC_ID
aws ec2 delete-internet-gateway --region $REGION --internet-gateway-id $IGW_ID
aws ec2 delete-subnet --region $REGION --subnet-id $SUBNET_ID
aws ec2 delete-vpc --region $REGION --vpc-id $VPC_ID

# Clean up local files
rm deploy/.env.aws deploy/*.pem
```
