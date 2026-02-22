# Design: AWS Deployment Scripts

## Summary

Two bash scripts using AWS CLI to provision and configure a fresh EC2 instance running the DTCC tile server with PostGIS. Data is synced from S3.

## Scope

- AWS infrastructure provisioning (VPC, subnet, security group, EC2, IAM)
- Server setup (Docker, PostGIS, data sync, ingestion, FastAPI systemd service)
- Out of scope: TLS/HTTPS, domain name, CI/CD, auto-scaling

## Architecture

```
VPC (10.0.0.0/16)
  └── Public Subnet (10.0.1.0/24)
       └── Internet Gateway + Route Table
            └── EC2 (t3.large, Ubuntu 24.04)
                 ├── Security Group: SSH (22) + API (8001)
                 ├── IAM Instance Profile: S3 read-only
                 ├── Docker: PostGIS 16 container
                 ├── systemd: FastAPI tile server
                 └── /data/laz/ + /data/gpkg/ (synced from S3)
```

## Script 1: deploy/aws-provision.sh

Creates all AWS infrastructure from scratch.

### Resources created
- VPC (10.0.0.0/16) with DNS support
- Public subnet (10.0.1.0/24)
- Internet gateway + route table
- Security group: inbound SSH (22) + API (8001)
- EC2 key pair (PEM saved locally)
- IAM role + instance profile with S3 read-only access
- EC2 instance (t3.large, Ubuntu 24.04 AMI)

### Configuration variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `REGION` | `eu-north-1` | AWS region (Stockholm) |
| `INSTANCE_TYPE` | `t3.large` | EC2 instance type |
| `KEY_NAME` | `dtcc-data-key` | SSH key pair name |
| `S3_BUCKET` | — | Bucket with .laz/.gpkg data |
| `PROJECT_NAME` | `dtcc-data` | Used for naming resources |

### Output
Writes `deploy/.env.aws` with all resource IDs and the public IP:
```
INSTANCE_ID=i-xxxx
PUBLIC_IP=x.x.x.x
VPC_ID=vpc-xxxx
SUBNET_ID=subnet-xxxx
SG_ID=sg-xxxx
KEY_FILE=deploy/dtcc-data-key.pem
S3_BUCKET=my-bucket
```

Key pair PEM saved to `deploy/dtcc-data-key.pem`.

Script is idempotent — checks if resources exist before creating.

## Script 2: deploy/aws-setup.sh

Reads `deploy/.env.aws`, SSHs into the instance, and configures everything.

### Step 1: Install system dependencies
- Docker + docker-compose plugin
- uv + Python 3.12
- AWS CLI (for S3 sync)

### Step 2: Deploy application
- Clones repo or rsyncs source files
- Creates .venv with uv, installs Python deps

### Step 3: Start PostGIS
- docker compose up -d (PostGIS 16 container)
- Waits for healthcheck
- Applies src/schema.sql

### Step 4: Sync data from S3
- `aws s3 sync s3://<bucket>/laz/ /data/laz/`
- `aws s3 sync s3://<bucket>/gpkg/ /data/gpkg/`

### Step 5: Ingest into PostGIS
- Runs create-atlas-lidar.py with --create-tables
- Runs create-atlas-gpkg.py with --create-tables

### Step 6: Start FastAPI as systemd service
- Creates /etc/systemd/system/dtcc-data.service
- Environment: DATABASE_URL, LAZ_DIRECTORY, GPKG_DATA_DIRECTORY
- Enables and starts service
- Verifies with curl http://localhost:8001/healthz

## File Organization

```
deploy/
  aws-provision.sh    — creates AWS infra
  aws-setup.sh        — configures the EC2 instance
  .env.aws            — generated, gitignored
  dtcc-data-key.pem   — generated, gitignored
```

## .gitignore additions
```
deploy/.env.aws
deploy/*.pem
```
