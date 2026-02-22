#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# DTCC Data — AWS Infrastructure Provisioning
#
# Creates: VPC, subnet, internet gateway, security group, IAM role, EC2 instance
# Output:  deploy/.env.aws with all resource IDs
# Usage:   S3_BUCKET=my-bucket ./deploy/aws-provision.sh
# Prereqs: aws cli configured with appropriate credentials
# =============================================================================

# --- Configuration (override via environment) ---
REGION="${AWS_REGION:-eu-north-1}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.large}"
KEY_NAME="${KEY_NAME:-dtcc-data-key}"
S3_BUCKET="${S3_BUCKET:?S3_BUCKET must be set (e.g. export S3_BUCKET=my-dtcc-bucket)}"
PROJECT_NAME="${PROJECT_NAME:-dtcc-data}"

# --- Derived ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env.aws"
KEY_FILE="$SCRIPT_DIR/${KEY_NAME}.pem"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

tag_spec() {
    local resource_type="$1"
    local name="$2"
    echo "ResourceType=${resource_type},Tags=[{Key=Name,Value=${PROJECT_NAME}-${name}},{Key=Project,Value=${PROJECT_NAME}}]"
}

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
    --tag-specifications "$(tag_spec vpc vpc)" \
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
    --tag-specifications "$(tag_spec subnet subnet)" \
    --query 'Subnet.SubnetId' --output text)
aws ec2 modify-subnet-attribute --region "$REGION" --subnet-id "$SUBNET_ID" --map-public-ip-on-launch
log "Subnet: $SUBNET_ID ($AZ)"

# --- Internet Gateway ---
log "Creating internet gateway..."
IGW_ID=$(aws ec2 create-internet-gateway \
    --region "$REGION" \
    --tag-specifications "$(tag_spec internet-gateway igw)" \
    --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --region "$REGION" --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID"
log "IGW: $IGW_ID"

# --- Route Table ---
log "Configuring route table..."
RTB_ID=$(aws ec2 describe-route-tables \
    --region "$REGION" \
    --filters "Name=vpc-id,Values=$VPC_ID" \
    --query 'RouteTables[0].RouteTableId' --output text)
aws ec2 create-route \
    --region "$REGION" \
    --route-table-id "$RTB_ID" \
    --destination-cidr-block 0.0.0.0/0 \
    --gateway-id "$IGW_ID" > /dev/null
aws ec2 associate-route-table \
    --region "$REGION" \
    --route-table-id "$RTB_ID" \
    --subnet-id "$SUBNET_ID" > /dev/null
log "Route table: $RTB_ID"

# --- Security Group ---
log "Creating security group..."
SG_ID=$(aws ec2 create-security-group \
    --region "$REGION" \
    --group-name "${PROJECT_NAME}-sg" \
    --description "DTCC Data tile server" \
    --vpc-id "$VPC_ID" \
    --tag-specifications "$(tag_spec security-group sg)" \
    --query 'GroupId' --output text)
# SSH
aws ec2 authorize-security-group-ingress \
    --region "$REGION" --group-id "$SG_ID" \
    --protocol tcp --port 22 --cidr 0.0.0.0/0 > /dev/null
# API
aws ec2 authorize-security-group-ingress \
    --region "$REGION" --group-id "$SG_ID" \
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
    --tag-specifications "$(tag_spec instance server)" \
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
cat > "$ENV_FILE" << ENVEOF
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
