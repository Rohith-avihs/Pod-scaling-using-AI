cat > start_aws.sh << 'EOF'
#!/bin/bash
echo "🚀 Starting ShopEase deployment on AWS..."
echo "⏰ Billing starts when cluster is created!"
echo "============================================================"

# Step 1 - ECR Login
echo "📦 Step 1: Logging in to ECR..."
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS \
  --password-stdin 217266131527.dkr.ecr.ap-south-1.amazonaws.com

# Step 2 - Create ECR repos
echo "📦 Step 2: Creating ECR repositories..."
aws ecr create-repository --repository-name shopease \
  --region ap-south-1 2>/dev/null || echo "shopease repo already exists"
aws ecr create-repository --repository-name shopease-scaler \
  --region ap-south-1 2>/dev/null || echo "shopease-scaler repo already exists"

# Step 3 - Build and push images
echo "🐳 Step 3: Building and pushing Docker images..."
docker build -t shopease .
docker tag shopease:latest \
  217266131527.dkr.ecr.ap-south-1.amazonaws.com/shopease:latest
docker push \
  217266131527.dkr.ecr.ap-south-1.amazonaws.com/shopease:latest

docker build -t shopease-scaler -f Dockerfile.scaler .
docker tag shopease-scaler:latest \
  217266131527.dkr.ecr.ap-south-1.amazonaws.com/shopease-scaler:latest
docker push \
  217266131527.dkr.ecr.ap-south-1.amazonaws.com/shopease-scaler:latest
echo "✅ Images pushed!"

# Step 4 - Create EKS cluster
echo "☸️  Step 4: Creating EKS cluster..."
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

# Step 5 - Wait for cluster to be ACTIVE
echo "⏳ Waiting for cluster to be fully ready..."
aws eks wait cluster-active \
  --name shopease-cluster \
  --region ap-south-1
echo "✅ Cluster is ACTIVE!"

# Step 6 - Connect kubectl
echo "🔗 Step 6: Connecting kubectl..."
aws eks update-kubeconfig \
  --region ap-south-1 \
  --name shopease-cluster

# Step 7 - Install EBS CSI driver for PVC
echo "💾 Step 7: Installing EBS CSI driver..."
eksctl create addon \
  --name aws-ebs-csi-driver \
  --cluster shopease-cluster \
  --region ap-south-1 \
  --force
sleep 30

# Step 8 - Deploy PostgreSQL
echo "🗄️  Step 8: Deploying PostgreSQL with PVC..."
kubectl apply -f postgres-deployment.yaml
echo "Waiting for PostgreSQL to be ready..."
kubectl wait --for=condition=ready pod \
  -l app=postgres --timeout=120s

# Step 9 - Deploy app
echo "🌐 Step 9: Deploying ShopEase app..."
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml

# Step 10 - Deploy scaler
echo "🤖 Step 10: Deploying PPO Scaler..."
kubectl apply -f scaler-rbac.yaml
kubectl apply -f scaler-deployment.yaml

# Step 11 - Install Prometheus + Grafana
echo "📊 Step 11: Installing Prometheus + Grafana..."
helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.enabled=true \
  --set prometheus.prometheusSpec.retention=1h

# Step 12 - Wait for app pods
echo "⏳ Waiting for app pods..."
kubectl wait --for=condition=ready pod \
  -l app=shopease --timeout=120s

# Step 13 - Show status
echo ""
echo "============================================================"
echo "✅ DEPLOYMENT COMPLETE!"
echo "============================================================"
kubectl get pods
echo ""
echo "🌐 Public URL:"
kubectl get svc shopease-service \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
echo ""
echo ""
echo "📊 Grafana Password:"
kubectl get secret --namespace monitoring prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode
echo ""
echo ""
echo "============================================================"
echo "📌 DEMO COMMANDS:"
echo "  Monitor scaling:  bash monitor.sh"
echo "  Scaler logs:      kubectl logs -l app=shopease-scaler -f"
echo "  Watch pods:       watch -n 3 kubectl get pods"
echo "  Load test:        siege -c 200 -t 3m <PUBLIC-URL>"
echo "  Delete cluster:   bash delete_aws.sh"
echo "============================================================"
EOF
chmod +x start_aws.sh
