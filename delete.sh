#!/bin/bash
# ============================================================
# ShopEase — AWS Full Cleanup Script
# Run this AFTER demo to stop all billing
# ============================================================

echo "🗑️  Starting AWS cleanup..."
echo "This will delete ALL resources and STOP billing."
echo "============================================================"

# ── STEP 1: Delete Kubernetes resources ──────────────────────
echo ""
echo "☸️  Step 1: Deleting Kubernetes resources..."
kubectl delete -f scaler-deployment.yaml 2>/dev/null
kubectl delete -f scaler-rbac.yaml 2>/dev/null
kubectl delete -f service.yaml 2>/dev/null
kubectl delete -f deployment.yaml 2>/dev/null
kubectl delete secret firebase-secret 2>/dev/null
echo "✅ Kubernetes resources deleted!"

# ── STEP 2: Uninstall Prometheus + Grafana ───────────────────
echo ""
echo "📊 Step 2: Uninstalling Prometheus + Grafana..."
helm uninstall prometheus --namespace monitoring 2>/dev/null
kubectl delete namespace monitoring 2>/dev/null
echo "✅ Prometheus + Grafana removed!"

# ── STEP 3: Delete EKS Cluster ───────────────────────────────
echo ""
echo "☸️  Step 3: Deleting EKS cluster (10-15 minutes)..."
echo "⏰ BILLING STOPS after this completes!"
eksctl delete cluster \
  --name shopease-cluster \
  --region ap-south-1

# ── STEP 4: Delete ECR Repositories ──────────────────────────
echo ""
echo "📦 Step 4: Deleting ECR repositories..."
aws ecr delete-repository \
  --repository-name shopease \
  --force \
  --region ap-south-1 2>/dev/null
aws ecr delete-repository \
  --repository-name shopease-scaler \
  --force \
  --region ap-south-1 2>/dev/null
echo "✅ ECR repositories deleted!"

# ── STEP 5: Delete any remaining CloudFormation stacks ───────
echo ""
echo "🗂️  Step 5: Cleaning up CloudFormation stacks..."
aws cloudformation list-stacks \
  --region ap-south-1 \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query 'StackSummaries[*].StackName' \
  --output text | tr '\t' '\n' | grep eksctl | while read stack; do
    echo "Deleting stack: $stack"
    aws cloudformation update-termination-protection \
      --no-enable-termination-protection \
      --stack-name "$stack" \
      --region ap-south-1 2>/dev/null
    aws cloudformation delete-stack \
      --stack-name "$stack" \
      --region ap-south-1
done
echo "✅ CloudFormation stacks cleaned!"

# ── STEP 6: Delete Load Balancers ────────────────────────────
echo ""
echo "🔗 Step 6: Checking for remaining load balancers..."
aws elb describe-load-balancers \
  --region ap-south-1 \
  --query "LoadBalancerDescriptions[*].LoadBalancerName" \
  --output text | tr '\t' '\n' | while read lb; do
    echo "Deleting load balancer: $lb"
    aws elb delete-load-balancer \
      --load-balancer-name "$lb" \
      --region ap-south-1
done
echo "✅ Load balancers cleaned!"

# ── STEP 7: Release Elastic IPs ──────────────────────────────
echo ""
echo "🌐 Step 7: Releasing Elastic IPs..."
aws ec2 describe-addresses \
  --region ap-south-1 \
  --query "Addresses[*].AllocationId" \
  --output text | tr '\t' '\n' | while read eip; do
    echo "Releasing EIP: $eip"
    aws ec2 release-address \
      --allocation-id "$eip" \
      --region ap-south-1
done
echo "✅ Elastic IPs released!"

# ── STEP 8: Final Verification ────────────────────────────────
echo ""
echo "============================================================"
echo "🔍 Final verification..."
echo "============================================================"
echo ""
echo "EKS Clusters:"
aws eks list-clusters --region ap-south-1

echo ""
echo "EC2 Instances (running):"
aws ec2 describe-instances \
  --region ap-south-1 \
  --filters Name=instance-state-name,Values=running \
  --query "Reservations[*].Instances[*].InstanceId" \
  --output text

echo ""
echo "ECR Repositories:"
aws ecr describe-repositories \
  --region ap-south-1 \
  --query "repositories[*].repositoryName" \
  --output text

echo ""
echo "Load Balancers:"
aws elb describe-load-balancers \
  --region ap-south-1 \
  --query "LoadBalancerDescriptions[*].LoadBalancerName" \
  --output text

echo ""
echo "Elastic IPs:"
aws ec2 describe-addresses \
  --region ap-south-1 \
  --query "Addresses[*].PublicIp" \
  --output text

echo ""
echo "============================================================"
echo "✅ CLEANUP COMPLETE — BILLING STOPPED!"
echo "============================================================"
echo ""
echo "Check your AWS billing at:"
echo "  https://console.aws.amazon.com/billing/home"
echo ""
echo "To redeploy later run:"
echo "  bash start_aws.sh"
echo "============================================================"
