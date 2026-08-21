#!/bin/bash
# ============================================================
# ShopEase — AWS Full Deployment Script
# Run this to deploy everything from scratch
# ============================================================

echo "🚀 Starting ShopEase deployment on AWS..."
echo "⏰ Note the time — billing starts when cluster is created!"
echo "============================================================"

# ── STEP 1: Login to ECR ────────────────────────────────────
echo ""
echo "📦 Step 1: Logging in to ECR..."
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS \
  --password-stdin 217266131527.dkr.ecr.ap-south-1.amazonaws.com

# ── STEP 2: Create ECR Repositories ─────────────────────────
echo ""
echo "📦 Step 2: Creating ECR repositories..."
aws ecr create-repository \
  --repository-name shopease \
  --region ap-south-1 2>/dev/null || echo "shopease repo already exists"

aws ecr create-repository \
  --repository-name shopease-scaler \
  --region ap-south-1 2>/dev/null || echo "shopease-scaler repo already exists"

# ── STEP 3: Build and Push Docker Images ─────────────────────
echo ""
echo "🐳 Step 3: Building and pushing Docker images..."

# App image
docker build -t shopease .
docker tag shopease:latest \
  217266131527.dkr.ecr.ap-south-1.amazonaws.com/shopease:latest
docker push \
  217266131527.dkr.ecr.ap-south-1.amazonaws.com/shopease:latest

# Scaler image
docker build -t shopease-scaler -f Dockerfile.scaler .
docker tag shopease-scaler:latest \
  217266131527.dkr.ecr.ap-south-1.amazonaws.com/shopease-scaler:latest
docker push \
  217266131527.dkr.ecr.ap-south-1.amazonaws.com/shopease-scaler:latest

echo "✅ Images pushed to ECR!"

# ── STEP 4: Create EKS Cluster ───────────────────────────────
echo ""
echo "☸️  Step 4: Creating EKS cluster (15-20 minutes)..."
echo "⏰ BILLING STARTS NOW!"
eksctl create cluster \
  --name shopease-cluster \
  --region ap-south-1 \
  --nodegroup-name shopease-nodes \
  --node-type t3.medium \
  --nodes 2 \
  --nodes-min 1 \
  --nodes-max 4 \
  --managed

# ── STEP 5: Connect kubectl ───────────────────────────────────
echo ""
echo "🔗 Step 5: Connecting kubectl to cluster..."
aws eks update-kubeconfig \
  --region ap-south-1 \
  --name shopease-cluster

# ── STEP 6: Create Firebase Secret ───────────────────────────
echo ""
echo "🔐 Step 6: Creating Firebase secret..."
kubectl create secret generic firebase-secret \
  --from-file=firebase-key.json=firebase-key.json

# ── STEP 7: Deploy App ────────────────────────────────────────
echo ""
echo "🌐 Step 7: Deploying ShopEase app..."
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml

# ── STEP 8: Deploy Scaler ─────────────────────────────────────
echo ""
echo "🤖 Step 8: Deploying PPO Scaler pod..."
kubectl apply -f scaler-rbac.yaml
kubectl apply -f scaler-deployment.yaml

# ── STEP 9: Install Prometheus + Grafana ─────────────────────
echo ""
echo "📊 Step 9: Installing Prometheus + Grafana..."
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.enabled=true \
  --set prometheus.prometheusSpec.retention=1h

# ── STEP 10: Wait for pods ────────────────────────────────────
echo ""
echo "⏳ Step 10: Waiting for all pods to be ready..."
kubectl wait --for=condition=ready pod \
  -l app=shopease \
  --timeout=120s

# ── STEP 11: Show Status ──────────────────────────────────────
echo ""
echo "============================================================"
echo "✅ DEPLOYMENT COMPLETE!"
echo "============================================================"
echo ""
echo "📋 Pod Status:"
kubectl get pods
echo ""
echo "🌐 Public URL:"
kubectl get services shopease-service \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
echo ""
echo ""
echo "📊 Grafana Password:"
kubectl get secret --namespace monitoring prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
echo ""
echo "============================================================"
echo "📌 USEFUL COMMANDS:"
echo ""
echo "Watch pods scaling:"
echo "  watch -n 3 kubectl get pods"
echo ""
echo "Watch scaler decisions:"
echo "  kubectl logs -l app=shopease-scaler -f"
echo ""
echo "View real CPU/memory:"
echo "  kubectl top pods"
echo ""
echo "Access Grafana (localhost:3000):"
echo "  kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80 &"
echo ""
echo "Access Prometheus (localhost:9090):"
echo "  kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090 &"
echo ""
echo "Load test:"
echo "  siege -c 200 -t 3m <PUBLIC-URL>"
echo ""
echo "⚠️  Remember to DELETE cluster after demo to stop billing!"
echo "   Run: bash delete_aws.sh"
echo "============================================================"
