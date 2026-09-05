#!/bin/bash

set -u

REGION="ap-south-1"

echo "============================================================"
echo "        AWS COMPLETE CLEANUP - $REGION"
echo "============================================================"
echo ""
echo "WARNING: This will DELETE AWS resources in $REGION."
echo "EC2, EKS, ECR, EBS, Load Balancers, NAT Gateways,"
echo "Elastic IPs, non-default VPCs, and S3 bucket(s) specified."
echo ""

read -p "Type DELETE to continue: " CONFIRM

if [ "$CONFIRM" != "DELETE" ]; then
    echo "Cleanup cancelled."
    exit 1
fi

echo ""
echo "Checking AWS account..."
aws sts get-caller-identity
echo ""

# ============================================================
# 1. DELETE EKS CLUSTERS
# ============================================================

echo "============================================================"
echo "1. Deleting EKS clusters"
echo "============================================================"

CLUSTERS=$(aws eks list-clusters \
    --region "$REGION" \
    --query 'clusters[]' \
    --output text)

if [ -n "$CLUSTERS" ]; then
    for CLUSTER in $CLUSTERS; do
        echo "Deleting EKS cluster: $CLUSTER"

        eksctl delete cluster \
            --name "$CLUSTER" \
            --region "$REGION" \
            --wait || true
    done
else
    echo "No EKS clusters found."
fi


# ============================================================
# 2. DELETE ACTIVE CLOUDFORMATION STACKS
# ============================================================

echo ""
echo "============================================================"
echo "2. Deleting CloudFormation stacks"
echo "============================================================"

STACKS=$(aws cloudformation list-stacks \
    --region "$REGION" \
    --query 'StackSummaries[?StackStatus!=`DELETE_COMPLETE` && StackStatus!=`DELETE_IN_PROGRESS`].StackName' \
    --output text)

if [ -n "$STACKS" ]; then
    for STACK in $STACKS; do
        echo "Deleting CloudFormation stack: $STACK"

        aws cloudformation delete-stack \
            --region "$REGION" \
            --stack-name "$STACK" || true
    done

    echo "Waiting for CloudFormation deletion..."
    sleep 30
else
    echo "No active CloudFormation stacks found."
fi


# ============================================================
# 3. TERMINATE ALL EC2 INSTANCES
# ============================================================

echo ""
echo "============================================================"
echo "3. Terminating EC2 instances"
echo "============================================================"

INSTANCE_IDS=$(aws ec2 describe-instances \
    --region "$REGION" \
    --filters \
        "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' \
    --output text)

if [ -n "$INSTANCE_IDS" ]; then

    echo "Instances to terminate:"
    echo "$INSTANCE_IDS"

    aws ec2 terminate-instances \
        --region "$REGION" \
        --instance-ids $INSTANCE_IDS

    echo "Waiting for EC2 termination..."

    aws ec2 wait instance-terminated \
        --region "$REGION" \
        --instance-ids $INSTANCE_IDS || true

else
    echo "No EC2 instances found."
fi


# ============================================================
# 4. DELETE ECR REPOSITORIES
# ============================================================

echo ""
echo "============================================================"
echo "4. Deleting ECR repositories"
echo "============================================================"

REPOS=$(aws ecr describe-repositories \
    --region "$REGION" \
    --query 'repositories[].repositoryName' \
    --output text)

if [ -n "$REPOS" ]; then

    for REPO in $REPOS; do

        echo "Deleting ECR repository: $REPO"

        aws ecr delete-repository \
            --region "$REGION" \
            --repository-name "$REPO" \
            --force || true

    done

else
    echo "No ECR repositories found."
fi


# ============================================================
# 5. DELETE APPLICATION / NETWORK LOAD BALANCERS
# ============================================================

echo ""
echo "============================================================"
echo "5. Deleting Application/Network Load Balancers"
echo "============================================================"

LB_ARNS=$(aws elbv2 describe-load-balancers \
    --region "$REGION" \
    --query 'LoadBalancers[].LoadBalancerArn' \
    --output text)

if [ -n "$LB_ARNS" ]; then

    for ARN in $LB_ARNS; do

        echo "Deleting Load Balancer: $ARN"

        aws elbv2 delete-load-balancer \
            --region "$REGION" \
            --load-balancer-arn "$ARN" || true

    done

else
    echo "No ALB/NLB found."
fi


# ============================================================
# 6. DELETE CLASSIC LOAD BALANCERS
# ============================================================

echo ""
echo "============================================================"
echo "6. Deleting Classic Load Balancers"
echo "============================================================"

CLASSIC_LBS=$(aws elb describe-load-balancers \
    --region "$REGION" \
    --query 'LoadBalancerDescriptions[].LoadBalancerName' \
    --output text 2>/dev/null || true)

if [ -n "$CLASSIC_LBS" ]; then

    for LB in $CLASSIC_LBS; do

        echo "Deleting Classic ELB: $LB"

        aws elb delete-load-balancer \
            --region "$REGION" \
            --load-balancer-name "$LB" || true

    done

else
    echo "No Classic Load Balancers found."
fi


# ============================================================
# 7. DELETE NAT GATEWAYS
# ============================================================

echo ""
echo "============================================================"
echo "7. Deleting NAT Gateways"
echo "============================================================"

NATS=$(aws ec2 describe-nat-gateways \
    --region "$REGION" \
    --filter "Name=state,Values=available,pending" \
    --query 'NatGateways[].NatGatewayId' \
    --output text)

if [ -n "$NATS" ]; then

    for NAT in $NATS; do

        echo "Deleting NAT Gateway: $NAT"

        aws ec2 delete-nat-gateway \
            --region "$REGION" \
            --nat-gateway-id "$NAT" || true

    done

    echo "Waiting for NAT Gateway deletion..."
    sleep 60

else
    echo "No NAT Gateways found."
fi


# ============================================================
# 8. RELEASE ELASTIC IPs
# ============================================================

echo ""
echo "============================================================"
echo "8. Releasing Elastic IPs"
echo "============================================================"

ALLOCATIONS=$(aws ec2 describe-addresses \
    --region "$REGION" \
    --query 'Addresses[].AllocationId' \
    --output text)

if [ -n "$ALLOCATIONS" ]; then

    for ALLOCATION in $ALLOCATIONS; do

        echo "Releasing Elastic IP: $ALLOCATION"

        aws ec2 release-address \
            --region "$REGION" \
            --allocation-id "$ALLOCATION" || true

    done

else
    echo "No Elastic IPs found."
fi


# ============================================================
# 9. DELETE UNATTACHED EBS VOLUMES
# ============================================================

echo ""
echo "============================================================"
echo "9. Deleting unattached EBS volumes"
echo "============================================================"

VOLUMES=$(aws ec2 describe-volumes \
    --region "$REGION" \
    --filters "Name=status,Values=available" \
    --query 'Volumes[].VolumeId' \
    --output text)

if [ -n "$VOLUMES" ]; then

    for VOLUME in $VOLUMES; do

        echo "Deleting EBS volume: $VOLUME"

        aws ec2 delete-volume \
            --region "$REGION" \
            --volume-id "$VOLUME" || true

    done

else
    echo "No unattached EBS volumes found."
fi


# ============================================================
# 10. DELETE SPECIFIC S3 BUCKET
# ============================================================

echo ""
echo "============================================================"
echo "10. Deleting S3 bucket"
echo "============================================================"

BUCKET="cloudops-storage-217266131527"

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then

    echo "Deleting S3 bucket: $BUCKET"

    aws s3 rb "s3://$BUCKET" --force || true

else
    echo "Bucket not found: $BUCKET"
fi


# ============================================================
# 11. DELETE NON-DEFAULT VPCs
# ============================================================

echo ""
echo "============================================================"
echo "11. Cleaning non-default VPCs"
echo "============================================================"

VPCS=$(aws ec2 describe-vpcs \
    --region "$REGION" \
    --query 'Vpcs[?IsDefault==`false`].VpcId' \
    --output text)

for VPC in $VPCS; do

    echo ""
    echo "Processing VPC: $VPC"

    # Delete remaining network interfaces if possible
    ENIS=$(aws ec2 describe-network-interfaces \
        --region "$REGION" \
        --filters "Name=vpc-id,Values=$VPC" \
        --query 'NetworkInterfaces[?Status==`available`].NetworkInterfaceId' \
        --output text)

    for ENI in $ENIS; do

        echo "Deleting ENI: $ENI"

        aws ec2 delete-network-interface \
            --region "$REGION" \
            --network-interface-id "$ENI" || true

    done


    # Delete VPC endpoints
    ENDPOINTS=$(aws ec2 describe-vpc-endpoints \
        --region "$REGION" \
        --filters "Name=vpc-id,Values=$VPC" \
        --query 'VpcEndpoints[].VpcEndpointId' \
        --output text)

    if [ -n "$ENDPOINTS" ]; then

        echo "Deleting VPC endpoints..."

        aws ec2 delete-vpc-endpoints \
            --region "$REGION" \
            --vpc-endpoint-ids $ENDPOINTS || true

    fi


    # Delete remaining subnets
    SUBNETS=$(aws ec2 describe-subnets \
        --region "$REGION" \
        --filters "Name=vpc-id,Values=$VPC" \
        --query 'Subnets[].SubnetId' \
        --output text)

    for SUBNET in $SUBNETS; do

        echo "Deleting subnet: $SUBNET"

        aws ec2 delete-subnet \
            --region "$REGION" \
            --subnet-id "$SUBNET" || true

    done


    # Detach and delete Internet Gateways
    IGWS=$(aws ec2 describe-internet-gateways \
        --region "$REGION" \
        --filters "Name=attachment.vpc-id,Values=$VPC" \
        --query 'InternetGateways[].InternetGatewayId' \
        --output text)

    for IGW in $IGWS; do

        echo "Detaching Internet Gateway: $IGW"

        aws ec2 detach-internet-gateway \
            --region "$REGION" \
            --internet-gateway-id "$IGW" \
            --vpc-id "$VPC" || true

        aws ec2 delete-internet-gateway \
            --region "$REGION" \
            --internet-gateway-id "$IGW" || true

    done


    # Delete non-default security groups
    SECURITY_GROUPS=$(aws ec2 describe-security-groups \
        --region "$REGION" \
        --filters "Name=vpc-id,Values=$VPC" \
        --query 'SecurityGroups[?GroupName!=`default`].GroupId' \
        --output text)

    for SG in $SECURITY_GROUPS; do

        echo "Deleting security group: $SG"

        aws ec2 delete-security-group \
            --region "$REGION" \
            --group-id "$SG" || true

    done


    # Delete VPC
    echo "Deleting VPC: $VPC"

    aws ec2 delete-vpc \
        --region "$REGION" \
        --vpc-id "$VPC" || true

done


# ============================================================
# 12. FINAL VERIFICATION
# ============================================================

echo ""
echo "============================================================"
echo "                 FINAL VERIFICATION"
echo "============================================================"

echo ""
echo "EC2:"
aws ec2 describe-instances \
    --region "$REGION" \
    --filters "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId'

echo ""
echo "EKS:"
aws eks list-clusters \
    --region "$REGION"

echo ""
echo "ECR:"
aws ecr describe-repositories \
    --region "$REGION" \
    --query 'repositories[].repositoryName'

echo ""
echo "EBS:"
aws ec2 describe-volumes \
    --region "$REGION" \
    --query 'Volumes[].{ID:VolumeId,State:State,AttachedTo:Attachments[0].InstanceId}'

echo ""
echo "Load Balancers:"
aws elbv2 describe-load-balancers \
    --region "$REGION" \
    --query 'LoadBalancers[].LoadBalancerName'

echo ""
echo "NAT Gateways:"
aws ec2 describe-nat-gateways \
    --region "$REGION" \
    --filter "Name=state,Values=available,pending" \
    --query 'NatGateways[].NatGatewayId'

echo ""
echo "Elastic IPs:"
aws ec2 describe-addresses \
    --region "$REGION" \
    --query 'Addresses[].PublicIp'

echo ""
echo "S3:"
aws s3api list-buckets \
    --query 'Buckets[].Name'

echo ""
echo "VPCs:"
aws ec2 describe-vpcs \
    --region "$REGION" \
    --query 'Vpcs[].{ID:VpcId,Default:IsDefault,CIDR:CidrBlock}'

echo ""
echo "============================================================"
echo "              CLEANUP SCRIPT FINISHED"
echo "============================================================"
