#!/bin/bash

# ============================================================
# ShopEase AWS COMPLETE CLEANUP
# Region: ap-south-1
#
# Deletes AWS resources created for the ShopEase deployment:
# EKS, CloudFormation stacks, ECR repos, Load Balancers,
# NAT Gateways, Elastic IPs, non-default VPCs and their
# networking resources, and unattached EBS volumes.
#
# ShopEase uses MySQL/SQL now.
# SQL data exists inside the Kubernetes MySQL workload and
# is removed automatically when the EKS cluster is deleted.
#
# NOTE:
# - The DEFAULT VPC is intentionally preserved.
# - No Firebase/Firestore resources are used or touched.
# - This script is intended for the ShopEase AWS environment.
# ============================================================

set -uo pipefail

REGION="ap-south-1"
CLUSTER="shopease-cluster"
ECR_REPOS=("shopease" "shopease-scaler")

echo "============================================================"
echo "        SHOP EASE AWS COMPLETE CLEANUP"
echo "============================================================"
echo "Region: $REGION"
echo ""
echo "This will delete ShopEase AWS infrastructure."
echo "EKS, SQL/MySQL workload, ECR, Load Balancers,"
echo "NAT Gateways, Elastic IPs and non-default VPC resources."
echo ""
echo "Firebase / Firestore is NOT used and will NOT be touched."
echo ""

read -r -p "Type DELETE to continue: " CONFIRM

if [[ "$CONFIRM" != "DELETE" ]]; then
    echo "Cleanup cancelled."
    exit 0
fi

echo ""
echo "Checking AWS account..."
aws sts get-caller-identity || exit 1

# ============================================================
# Helper
# ============================================================

wait_stack_delete() {
    local stack="$1"

    if aws cloudformation describe-stacks \
        --region "$REGION" \
        --stack-name "$stack" >/dev/null 2>&1; then

        echo "Waiting for CloudFormation stack deletion: $stack"

        aws cloudformation wait stack-delete-complete \
            --region "$REGION" \
            --stack-name "$stack" 2>/dev/null || true
    fi
}

# ============================================================
# 1. DELETE EKS CLUSTER
# ============================================================

echo ""
echo "============================================================"
echo "1. Deleting EKS cluster"
echo "============================================================"

if aws eks describe-cluster \
    --name "$CLUSTER" \
    --region "$REGION" >/dev/null 2>&1; then

    echo "Deleting EKS cluster: $CLUSTER"

    eksctl delete cluster \
        --name "$CLUSTER" \
        --region "$REGION" \
        --wait || true

else
    echo "EKS cluster not found: $CLUSTER"
fi

# ============================================================
# 2. DELETE EKS CLOUDFORMATION STACKS
# ============================================================

echo ""
echo "============================================================"
echo "2. Cleaning ShopEase CloudFormation stacks"
echo "============================================================"

aws cloudformation list-stacks \
    --region "$REGION" \
    --stack-status-filter \
        CREATE_IN_PROGRESS CREATE_COMPLETE \
        ROLLBACK_IN_PROGRESS ROLLBACK_FAILED ROLLBACK_COMPLETE \
        DELETE_FAILED UPDATE_IN_PROGRESS UPDATE_COMPLETE \
        UPDATE_ROLLBACK_IN_PROGRESS UPDATE_ROLLBACK_FAILED \
        UPDATE_ROLLBACK_COMPLETE \
    --query 'StackSummaries[].StackName' \
    --output text 2>/dev/null |
while read -r stack; do

    [[ -z "$stack" ]] && continue

    if [[ "$stack" == *"eksctl-${CLUSTER}"* ]]; then
        echo "Deleting stack: $stack"

        aws cloudformation delete-stack \
            --region "$REGION" \
            --stack-name "$stack" || true
    fi
done

for stack in \
    "eksctl-${CLUSTER}-cluster" \
    "eksctl-${CLUSTER}-nodegroup-${CLUSTER}-nodes" \
    "eksctl-${CLUSTER}-nodegroup-shopease-nodes" \
    "eksctl-${CLUSTER}-addon-iamserviceaccount-kube-system-ebs-csi-controller-sa"
do
    wait_stack_delete "$stack"
done

# ============================================================
# 3. DELETE LOAD BALANCERS
# ============================================================

echo ""
echo "============================================================"
echo "3. Deleting Application/Network Load Balancers"
echo "============================================================"

LB_ARNS=$(aws elbv2 describe-load-balancers \
    --region "$REGION" \
    --query 'LoadBalancers[].LoadBalancerArn' \
    --output text 2>/dev/null || true)

for arn in $LB_ARNS; do
    [[ -z "$arn" ]] && continue

    echo "Deleting Load Balancer: $arn"

    aws elbv2 delete-load-balancer \
        --region "$REGION" \
        --load-balancer-arn "$arn" || true
done

echo ""
echo "Deleting Classic Load Balancers..."

CLB_NAMES=$(aws elb describe-load-balancers \
    --region "$REGION" \
    --query 'LoadBalancerDescriptions[].LoadBalancerName' \
    --output text 2>/dev/null || true)

for name in $CLB_NAMES; do
    [[ -z "$name" ]] && continue

    echo "Deleting Classic Load Balancer: $name"

    aws elb delete-load-balancer \
        --region "$REGION" \
        --load-balancer-name "$name" || true
done

# ============================================================
# 4. DELETE ECR
# ============================================================

echo ""
echo "============================================================"
echo "4. Deleting ECR repositories"
echo "============================================================"

for repo in "${ECR_REPOS[@]}"; do

    if aws ecr describe-repositories \
        --region "$REGION" \
        --repository-names "$repo" >/dev/null 2>&1; then

        echo "Deleting ECR repository: $repo"

        aws ecr delete-repository \
            --region "$REGION" \
            --repository-name "$repo" \
            --force || true

    else
        echo "ECR repository not found: $repo"
    fi
done

# ============================================================
# 5. DELETE NAT GATEWAYS
# ============================================================

echo ""
echo "============================================================"
echo "5. Deleting NAT Gateways"
echo "============================================================"

NAT_IDS=$(aws ec2 describe-nat-gateways \
    --region "$REGION" \
    --filter "Name=state,Values=pending,available,failed" \
    --query 'NatGateways[].NatGatewayId' \
    --output text 2>/dev/null || true)

for nat in $NAT_IDS; do
    [[ -z "$nat" ]] && continue

    echo "Deleting NAT Gateway: $nat"

    aws ec2 delete-nat-gateway \
        --region "$REGION" \
        --nat-gateway-id "$nat" || true
done

if [[ -n "$NAT_IDS" ]]; then
    echo "Waiting for NAT Gateway deletion..."
    sleep 20
fi

# ============================================================
# 6. RELEASE ELASTIC IPS
# ============================================================

echo ""
echo "============================================================"
echo "6. Releasing Elastic IPs"
echo "============================================================"

EIP_DATA=$(aws ec2 describe-addresses \
    --region "$REGION" \
    --query 'Addresses[].{AllocationId:AllocationId,AssociationId:AssociationId}' \
    --output text 2>/dev/null || true)

while read -r allocation association; do

    [[ -z "$allocation" ]] && continue

    if [[ "$association" != "None" && -n "$association" ]]; then

        echo "Disassociating EIP: $association"

        aws ec2 disassociate-address \
            --region "$REGION" \
            --association-id "$association" || true
    fi

    echo "Releasing EIP: $allocation"

    aws ec2 release-address \
        --region "$REGION" \
        --allocation-id "$allocation" || true

done <<< "$EIP_DATA"

# ============================================================
# 7. DELETE UNATTACHED EBS VOLUMES
# ============================================================

echo ""
echo "============================================================"
echo "7. Deleting unattached EBS volumes"
echo "============================================================"

VOLUMES=$(aws ec2 describe-volumes \
    --region "$REGION" \
    --filters "Name=status,Values=available" \
    --query 'Volumes[].VolumeId' \
    --output text 2>/dev/null || true)

for vol in $VOLUMES; do
    [[ -z "$vol" ]] && continue

    echo "Deleting unattached EBS volume: $vol"

    aws ec2 delete-volume \
        --region "$REGION" \
        --volume-id "$vol" || true
done

# ============================================================
# 8. DELETE NON-DEFAULT VPCS
# ============================================================

echo ""
echo "============================================================"
echo "8. Deleting non-default VPCs"
echo "============================================================"

VPCS=$(aws ec2 describe-vpcs \
    --region "$REGION" \
    --query 'Vpcs[?IsDefault==`false`].VpcId' \
    --output text 2>/dev/null || true)

for vpc in $VPCS; do

    [[ -z "$vpc" ]] && continue

    echo ""
    echo "------------------------------------------------------------"
    echo "Processing VPC: $vpc"
    echo "------------------------------------------------------------"

    ENDPOINTS=$(aws ec2 describe-vpc-endpoints \
        --region "$REGION" \
        --filters "Name=vpc-id,Values=$vpc" \
        --query 'VpcEndpoints[].VpcEndpointId' \
        --output text 2>/dev/null || true)

    for ep in $ENDPOINTS; do
        [[ -z "$ep" ]] && continue

        echo "Deleting VPC endpoint: $ep"

        aws ec2 delete-vpc-endpoints \
            --region "$REGION" \
            --vpc-endpoint-ids "$ep" || true
    done

    VPC_NATS=$(aws ec2 describe-nat-gateways \
        --region "$REGION" \
        --filter "Name=vpc-id,Values=$vpc" \
                 "Name=state,Values=pending,available,failed" \
        --query 'NatGateways[].NatGatewayId' \
        --output text 2>/dev/null || true)

    for nat in $VPC_NATS; do
        [[ -z "$nat" ]] && continue

        echo "Deleting VPC NAT Gateway: $nat"

        aws ec2 delete-nat-gateway \
            --region "$REGION" \
            --nat-gateway-id "$nat" || true
    done

    ENIS=$(aws ec2 describe-network-interfaces \
        --region "$REGION" \
        --filters "Name=vpc-id,Values=$vpc" \
        --query 'NetworkInterfaces[?Status==`available`].NetworkInterfaceId' \
        --output text 2>/dev/null || true)

    for eni in $ENIS; do
        [[ -z "$eni" ]] && continue

        echo "Deleting available ENI: $eni"

        aws ec2 delete-network-interface \
            --region "$REGION" \
            --network-interface-id "$eni" || true
    done

    SUBNETS=$(aws ec2 describe-subnets \
        --region "$REGION" \
        --filters "Name=vpc-id,Values=$vpc" \
        --query 'Subnets[].SubnetId' \
        --output text 2>/dev/null || true)

    for subnet in $SUBNETS; do
        [[ -z "$subnet" ]] && continue

        echo "Deleting subnet: $subnet"

        aws ec2 delete-subnet \
            --region "$REGION" \
            --subnet-id "$subnet" || true
    done

    ROUTE_TABLES=$(aws ec2 describe-route-tables \
        --region "$REGION" \
        --filters "Name=vpc-id,Values=$vpc" \
        --query 'RouteTables[].{ID:RouteTableId,Main:Associations[?Main==`true`]|[0].Main}' \
        --output text 2>/dev/null || true)

    while read -r rtb main; do

        [[ -z "$rtb" ]] && continue

        if [[ "$main" == "True" || "$main" == "true" ]]; then
            echo "Keeping main route table: $rtb"
            continue
        fi

        echo "Deleting route table: $rtb"

        aws ec2 delete-route-table \
            --region "$REGION" \
            --route-table-id "$rtb" || true

    done <<< "$ROUTE_TABLES"

    IGWS=$(aws ec2 describe-internet-gateways \
        --region "$REGION" \
        --filters "Name=attachment.vpc-id,Values=$vpc" \
        --query 'InternetGateways[].InternetGatewayId' \
        --output text 2>/dev/null || true)

    for igw in $IGWS; do
        [[ -z "$igw" ]] && continue

        echo "Detaching Internet Gateway: $igw"

        aws ec2 detach-internet-gateway \
            --region "$REGION" \
            --internet-gateway-id "$igw" \
            --vpc-id "$vpc" || true

        echo "Deleting Internet Gateway: $igw"

        aws ec2 delete-internet-gateway \
            --region "$REGION" \
            --internet-gateway-id "$igw" || true
    done

    SGS=$(aws ec2 describe-security-groups \
        --region "$REGION" \
        --filters "Name=vpc-id,Values=$vpc" \
        --query 'SecurityGroups[?GroupName!=`default`].GroupId' \
        --output text 2>/dev/null || true)

    for sg in $SGS; do
        [[ -z "$sg" ]] && continue

        echo "Deleting security group: $sg"

        aws ec2 delete-security-group \
            --region "$REGION" \
            --group-id "$sg" || true
    done

    echo "Deleting VPC: $vpc"

    aws ec2 delete-vpc \
        --region "$REGION" \
        --vpc-id "$vpc" || true

done

# ============================================================
# 9. FINAL VERIFICATION
# ============================================================

echo ""
echo "============================================================"
echo "              FINAL AWS VERIFICATION"
echo "============================================================"

echo ""
echo "EC2:"
aws ec2 describe-instances \
    --region "$REGION" \
    --filters "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].{ID:InstanceId,State:State.Name,Type:InstanceType}' \
    --output table 2>/dev/null || true

echo ""
echo "EKS:"
aws eks list-clusters \
    --region "$REGION" 2>/dev/null || true

echo ""
echo "ECR:"
aws ecr describe-repositories \
    --region "$REGION" \
    --query 'repositories[].repositoryName' \
    --output table 2>/dev/null || true

echo ""
echo "Load Balancers:"
aws elbv2 describe-load-balancers \
    --region "$REGION" \
    --query 'LoadBalancers[].{Name:LoadBalancerName,Type:Type,State:State.Code}' \
    --output table 2>/dev/null || true

echo ""
echo "NAT Gateways:"
aws ec2 describe-nat-gateways \
    --region "$REGION" \
    --filter "Name=state,Values=pending,available,deleting" \
    --query 'NatGateways[].{ID:NatGatewayId,State:State}' \
    --output table 2>/dev/null || true

echo ""
echo "Elastic IPs:"
aws ec2 describe-addresses \
    --region "$REGION" \
    --query 'Addresses[].{AllocationId:AllocationId,PublicIP:PublicIp,Association:AssociationId}' \
    --output table 2>/dev/null || true

echo ""
echo "Non-default VPCs:"
aws ec2 describe-vpcs \
    --region "$REGION" \
    --query 'Vpcs[?IsDefault==`false`].{ID:VpcId,CIDR:CidrBlock}' \
    --output table 2>/dev/null || true

echo ""
echo "Default VPC is intentionally preserved."

echo ""
echo "============================================================"
echo "             CLEANUP SCRIPT FINISHED"
echo "============================================================"
echo ""
echo "ShopEase MySQL/SQL workload was removed with the EKS cluster."
echo "No Firebase / Firestore resources were touched."
echo "============================================================"
