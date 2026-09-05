#!/bin/bash

# ============================================================
# ShopEase — AWS Full Deployment
# MySQL/SQL + EKS + PPO Scaler + Prometheus/Grafana
# ============================================================

set -euo pipefail

REGION="ap-south-1"
ACCOUNT_ID="217266131527"

ECR_APP="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/shopease"
ECR_SCALER="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/shopease-scaler"

CLUSTER_NAME="shopease-cluster"
NODEGROUP_NAME="shopease-nodes"

MYSQL_ROOT_PASSWORD="rootpassword"
MYSQL_DATABASE="ecommerce"
MYSQL_USER="shopease"
MYSQL_PASSWORD="yourpassword"

echo "============================================================"
echo "        🚀 ShopEase AWS Deployment"
echo "============================================================"
echo ""
echo "Architecture:"
echo "  AWS Load Balancer"
echo "        ↓"
echo "  Amazon EKS"
echo "        ↓"
echo "  ShopEase Flask"
echo "        ↓"
echo "  MySQL / SQL Database"
echo "        ↓"
echo "  Prometheus → Monitor.html"
echo "        ↓"
echo "  PPO + Transformer Scaler"
echo ""
echo "⚠️ AWS billing starts when EKS resources are created."
echo "============================================================"

# ============================================================
# STEP 0 — Required tools/files
# ============================================================

echo ""
echo "🔎 Step 0: Checking required tools and files..."

for cmd in aws docker eksctl kubectl helm; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "❌ Required command not found: $cmd"
        exit 1
    fi
done

for file in app.py Dockerfile deployment.yaml service.yaml scaler.py \
            Dockerfile.scaler scaler-deployment.yaml scaler-rbac.yaml \
            k8s_ppo_model.pth schema.sql; do
    if [ ! -f "$file" ]; then
        echo "❌ Required project file not found: $file"
        exit 1
    fi
done

echo "✅ Tools and project files found."

# ============================================================
# STEP 1 — AWS credentials
# ============================================================

echo ""
echo "🔐 Step 1: Checking AWS credentials..."
aws sts get-caller-identity
echo "✅ AWS credentials are working."

# ============================================================
# STEP 2 — ECR login
# ============================================================

echo ""
echo "📦 Step 2: Logging in to ECR..."

aws ecr get-login-password --region "$REGION" |
    docker login \
        --username AWS \
        --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "✅ ECR login successful."

# ============================================================
# STEP 3 — Create ECR repositories if required
# ============================================================

echo ""
echo "📦 Step 3: Checking ECR repositories..."

for repo in shopease shopease-scaler; do
    if aws ecr describe-repositories \
        --repository-names "$repo" \
        --region "$REGION" >/dev/null 2>&1; then

        echo "✅ ECR repository '$repo' already exists."
    else
        aws ecr create-repository \
            --repository-name "$repo" \
            --region "$REGION" >/dev/null

        echo "✅ Created ECR repository '$repo'."
    fi
done

# ============================================================
# STEP 4 — Build ShopEase image
# ============================================================

echo ""
echo "🐳 Step 4: Building ShopEase application image..."

docker build --no-cache -t shopease:latest .

echo "✅ ShopEase image built."

# ============================================================
# STEP 5 — Verify SQL/MySQL dependency
# ============================================================

echo ""
echo "🔎 Step 5: Verifying MySQL dependency..."

docker run --rm shopease:latest pip show mysql-connector-python

echo "✅ MySQL dependency verified."

# ============================================================
# STEP 6 — Push ShopEase image
# ============================================================

echo ""
echo "📤 Step 6: Pushing ShopEase image to ECR..."

docker tag shopease:latest "${ECR_APP}:latest"
docker push "${ECR_APP}:latest"

echo "✅ ShopEase image pushed."

# ============================================================
# STEP 7 — Build PPO scaler image
# ============================================================

echo ""
echo "🤖 Step 7: Building PPO scaler image..."

docker build \
    --no-cache \
    -t shopease-scaler:latest \
    -f Dockerfile.scaler \
    .

echo "✅ PPO scaler image built."

# ============================================================
# STEP 8 — Push PPO scaler image
# ============================================================

echo ""
echo "📤 Step 8: Pushing PPO scaler image..."

docker tag shopease-scaler:latest "${ECR_SCALER}:latest"
docker push "${ECR_SCALER}:latest"

echo "✅ PPO scaler image pushed."

# ============================================================
# STEP 9 — Create EKS cluster
# ============================================================

echo ""
echo "============================================================"
echo "☸️  Step 9: Creating EKS cluster"
echo "============================================================"
echo "Cluster: $CLUSTER_NAME"
echo "Region : $REGION"
echo "Nodes  : 2 × t3.medium"
echo ""

if aws eks describe-cluster \
    --name "$CLUSTER_NAME" \
    --region "$REGION" >/dev/null 2>&1; then

    echo "✅ EKS cluster already exists."

else
    eksctl create cluster \
        --name "$CLUSTER_NAME" \
        --region "$REGION" \
        --nodegroup-name "$NODEGROUP_NAME" \
        --node-type t3.medium \
        --nodes 2 \
        --nodes-min 1 \
        --nodes-max 4 \
        --managed

    echo "✅ EKS cluster created."
fi

# ============================================================
# STEP 10 — Configure kubectl
# ============================================================

echo ""
echo "🔗 Step 10: Configuring kubectl..."

aws eks update-kubeconfig \
    --region "$REGION" \
    --name "$CLUSTER_NAME"

echo "✅ kubectl configured."

kubectl get nodes

kubectl wait \
    --for=condition=Ready \
    nodes \
    --all \
    --timeout=300s

echo "✅ All nodes are Ready."

# ============================================================
# STEP 11 — Install Prometheus + Grafana FIRST
# This must happen before the PPO scaler starts.
# ============================================================

echo ""
echo "📊 Step 11: Installing/upgrading Prometheus + Grafana..."

helm repo add prometheus-community \
    https://prometheus-community.github.io/helm-charts \
    2>/dev/null || true

helm repo update

PROM_INSTALLED="false"
for attempt in 1 2 3 4 5; do
    echo "Helm installation attempt $attempt/5..."
    if helm upgrade --install prometheus \
        prometheus-community/kube-prometheus-stack \
        --namespace monitoring \
        --create-namespace \
        --set grafana.enabled=true \
        --set prometheus.prometheusSpec.retention=1h \
        --wait \
        --timeout 10m; then
        PROM_INSTALLED="true"
        break
    fi
    if [ "$attempt" -lt 5 ]; then
        echo "⚠️ Prometheus download/install failed. Retrying in 15 seconds..."
        sleep 15
        helm repo update || true
    fi
done

if [ "$PROM_INSTALLED" != "true" ]; then
    echo "❌ Prometheus + Grafana could not be installed after 5 attempts."
    exit 1
fi

echo "✅ Prometheus + Grafana installed."

kubectl rollout status \
    deployment/prometheus-grafana \
    -n monitoring \
    --timeout=300s
# ============================================================
# STEP 12 — Deploy MySQL / SQL database
# ============================================================

echo ""
echo "🗄️ Step 12: Deploying MySQL / SQL database..."

cat > /tmp/mysql-shopease.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mysql
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mysql
  template:
    metadata:
      labels:
        app: mysql
    spec:
      containers:
      - name: mysql
        image: mysql:8.0
        ports:
        - containerPort: 3306
        env:
        - name: MYSQL_ROOT_PASSWORD
          value: "${MYSQL_ROOT_PASSWORD}"
        - name: MYSQL_DATABASE
          value: "${MYSQL_DATABASE}"
        - name: MYSQL_USER
          value: "${MYSQL_USER}"
        - name: MYSQL_PASSWORD
          value: "${MYSQL_PASSWORD}"
        resources:
          requests:
            cpu: "100m"
            memory: "256Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
---
apiVersion: v1
kind: Service
metadata:
  name: mysql-service
  namespace: default
spec:
  selector:
    app: mysql
  ports:
  - name: mysql
    port: 3306
    targetPort: 3306
  type: ClusterIP
EOF

# Apply MySQL deployment and service
kubectl apply -f /tmp/mysql-shopease.yaml

# Wait for Kubernetes deployment
kubectl rollout status \
    deployment/mysql \
    --timeout=300s

echo "✅ MySQL pod is ready."

# ============================================================
# Wait for the FINAL MySQL server
# Do NOT rely only on mysqladmin ping because the MySQL
# initialization process starts a temporary server first.
# ============================================================

MYSQL_POD=""

echo "Waiting for MySQL to become fully ready..."

MYSQL_READY="false"

for i in $(seq 1 60); do

    MYSQL_POD=$(kubectl get pod \
        -l app=mysql \
        -o jsonpath='{.items[0].metadata.name}' \
        2>/dev/null || true)

    if [ -n "$MYSQL_POD" ]; then

        # Check the actual application credentials
        # against the actual ecommerce database.
        if kubectl exec "$MYSQL_POD" -- \
            mysql \
            -u"${MYSQL_USER}" \
            "-p${MYSQL_PASSWORD}" \
            -Nse "SELECT 1;" \
            "${MYSQL_DATABASE}" \
            >/dev/null 2>&1; then

            MYSQL_READY="true"

            echo "✅ MySQL is fully ready."
            echo "   Pod: ${MYSQL_POD}"
            echo "   Database: ${MYSQL_DATABASE}"
            echo "   User: ${MYSQL_USER}"

            break
        fi
    fi

    echo "Waiting for MySQL to become ready... ($i/60)"
    sleep 5
done

# ============================================================
# Final MySQL readiness validation
# ============================================================

if [ -z "$MYSQL_POD" ]; then
    echo "❌ MySQL pod was not found."
    exit 1
fi

if [ "$MYSQL_READY" != "true" ]; then

    echo "❌ MySQL did not become ready."

    echo ""
    echo "MySQL pod status:"
    kubectl get pod "$MYSQL_POD" -o wide || true

    echo ""
    echo "MySQL logs:"
    kubectl logs "$MYSQL_POD" --tail=100 || true

    exit 1
fi

# ============================================================
# Verify database exists
# ============================================================

if ! kubectl exec "$MYSQL_POD" -- \
    mysql \
    -u"${MYSQL_USER}" \
    "-p${MYSQL_PASSWORD}" \
    -Nse "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME='${MYSQL_DATABASE}';" \
    >/dev/null 2>&1; then

    echo "❌ Database '${MYSQL_DATABASE}' could not be accessed."
    kubectl logs "$MYSQL_POD" --tail=100 || true
    exit 1
fi

echo "✅ Database '${MYSQL_DATABASE}' is accessible."

# ============================================================
# Verify MySQL service
# ============================================================

if kubectl get service mysql-service >/dev/null 2>&1; then
    echo "✅ MySQL service 'mysql-service' is available."
else
    echo "❌ MySQL service 'mysql-service' was not found."
    exit 1
fi

echo "✅ Step 12 completed successfully."

# ============================================================
# STEP 13 — Load schema.sql into MySQL
# ============================================================

echo ""
echo "📚 Step 13: Loading schema.sql into SQL database..."

# Load the schema using MySQL root.
if ! kubectl exec -i "$MYSQL_POD" -- \
    mysql \
    -uroot \
    "-p${MYSQL_ROOT_PASSWORD}" \
    "$MYSQL_DATABASE" < schema.sql; then
    echo "❌ schema.sql could not be loaded using MySQL root."
    echo "MySQL logs:"
    kubectl logs "$MYSQL_POD" --tail=100 || true
    exit 1
fi

echo "✅ schema.sql loaded successfully."
echo ""
echo "🔎 Checking SQL tables..."
kubectl exec "$MYSQL_POD" -- \
    mysql \
    -u"${MYSQL_USER}" \
    "-p${MYSQL_PASSWORD}" \
    -Nse "SHOW TABLES FROM ${MYSQL_DATABASE};"

# ============================================================
# STEP 14 — Deploy ShopEase Flask application
# ============================================================

echo ""
echo "🌐 Step 14: Deploying ShopEase application..."

kubectl apply -f deployment.yaml

echo "✅ deployment.yaml applied."

kubectl rollout restart deployment/shopease >/dev/null 2>&1 || true

kubectl rollout status \
    deployment/shopease \
    --timeout=300s

echo "✅ ShopEase Deployment successfully rolled out."

# ============================================================
# STEP 15 — Create/configure ShopEase LoadBalancer Service
# ============================================================

echo ""
echo "🌐 Step 15: Creating ShopEase Service..."

kubectl apply -f service.yaml

kubectl patch service shopease-service \
    -n default \
    --type='merge' \
    -p='{"metadata":{"labels":{"app":"shopease"}},"spec":{"ports":[{"name":"http","port":80,"protocol":"TCP","targetPort":5000}]}}'

echo "✅ ShopEase Service configured."

kubectl get service shopease-service \
    -n default \
    --show-labels

# ============================================================
# STEP 16 — Verify application pod/endpoints
# ============================================================

echo ""
echo "🔎 Step 16: Verifying ShopEase Pods..."

kubectl wait \
    --for=condition=Ready \
    pods \
    -l app=shopease \
    --timeout=180s

kubectl get pods -l app=shopease -o wide

ENDPOINTS=$(kubectl get endpoints shopease-service \
    -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null || true)

if [ -z "$ENDPOINTS" ]; then
    echo "❌ ShopEase Service has no endpoints."
    exit 1
fi

echo "✅ ShopEase endpoints: $ENDPOINTS"

# ============================================================
# STEP 17 — Configure Prometheus ServiceMonitor
# This is what makes flask_http_request_total and
# flask_http_request_duration_seconds available in Prometheus.
# ============================================================

echo ""
echo "📈 Step 17: Configuring ShopEase Prometheus ServiceMonitor..."

cat > /tmp/shopease-servicemonitor.yaml <<'EOF'
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: shopease
  namespace: monitoring
  labels:
    release: prometheus
spec:
  namespaceSelector:
    matchNames:
      - default
  selector:
    matchLabels:
      app: shopease
  endpoints:
    - port: http
      path: /metrics
      interval: 5s
EOF

kubectl apply -f /tmp/shopease-servicemonitor.yaml

echo "✅ ShopEase ServiceMonitor configured."

# Give Prometheus a few seconds to discover the target.
sleep 10

# ============================================================
# STEP 18 — Verify Flask metrics are being scraped
# ============================================================

echo ""
echo "🔎 Step 18: Verifying Prometheus Flask metrics..."

kubectl get servicemonitor shopease -n monitoring

# Start Prometheus port-forward now. Reuse an existing process on port 9090.
if command -v lsof >/dev/null 2>&1 && lsof -iTCP:9090 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "ℹ️ Port 9090 is already in use; keeping the existing process."
else
    nohup kubectl port-forward \
        -n monitoring \
        svc/prometheus-kube-prometheus-prometheus \
        9090:9090 \
        >/tmp/shopease-prometheus-port-forward.log 2>&1 &
    echo $! >/tmp/shopease-prometheus-port-forward.pid
    sleep 5
fi

TARGET_OK="false"
for i in {1..12}; do
    if curl -fsS --max-time 5 'http://localhost:9090/api/v1/targets' \
        >/tmp/shopease-targets.json 2>/dev/null; then
        if python3 - <<'PYCHECK'
import json
try:
    d=json.load(open('/tmp/shopease-targets.json'))
    ok=any(
        t.get('labels',{}).get('job') == 'shopease-service'
        and t.get('health') == 'up'
        for t in d.get('data',{}).get('activeTargets',[])
    )
    raise SystemExit(0 if ok else 1)
except Exception:
    raise SystemExit(1)
PYCHECK
        then
            TARGET_OK="true"
            break
        fi
    fi
    echo "Waiting for Prometheus to discover shopease-service... ($i/12)"
    sleep 5
done

if [ "$TARGET_OK" = "true" ]; then
    echo "✅ Prometheus is scraping ShopEase."
else
    echo "⚠️ ShopEase target is not UP yet. Showing matching targets:"
    python3 - <<'PYSHOW'
import json
try:
    d=json.load(open('/tmp/shopease-targets.json'))
    for t in d.get('data',{}).get('activeTargets',[]):
        if 'shopease' in str(t.get('labels',{})).lower() or 'shopease' in str(t.get('scrapeUrl','')).lower():
            print('labels:', t.get('labels'))
            print('health:', t.get('health'))
            print('url:', t.get('scrapeUrl'))
            print('error:', t.get('lastError'))
except Exception:
    pass
PYSHOW
fi

# ============================================================
# STEP 19 — Deploy PPO scaler
# ============================================================

echo ""
echo "🤖 Step 19: Deploying PPO Transformer scaler..."

kubectl apply -f scaler-rbac.yaml
kubectl apply -f scaler-deployment.yaml

kubectl rollout status \
    deployment/shopease-scaler \
    --timeout=300s

echo "✅ PPO scaler is running."

# ============================================================
# STEP 20 — Wait for AWS LoadBalancer
# ============================================================

echo ""
echo "🌐 Step 20: Waiting for AWS Load Balancer..."

PUBLIC_URL=""

for i in {1..40}; do
    PUBLIC_URL=$(kubectl get service shopease-service \
        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' \
        2>/dev/null || true)

    if [ -n "$PUBLIC_URL" ]; then
        break
    fi

    echo "Waiting for Load Balancer... ($i/40)"
    sleep 10
done

if [ -z "$PUBLIC_URL" ]; then
    echo "❌ Load Balancer hostname was not assigned."
    kubectl get service shopease-service
    exit 1
fi

echo "✅ Load Balancer created."

# ============================================================
# STEP 21 — Final verification
# ============================================================

echo ""
echo "🔎 Step 21: Final verification..."

echo ""
echo "Pods:"
kubectl get pods -o wide

echo ""
echo "ShopEase Deployment:"
kubectl get deployment shopease

echo ""
echo "MySQL Deployment:"
kubectl get deployment mysql

echo ""
echo "ShopEase Service:"
kubectl get service shopease-service

echo ""
echo "MySQL Service:"
kubectl get service mysql-service

echo ""
echo "ServiceMonitor:"
kubectl get servicemonitor shopease -n monitoring

echo ""
echo "Scaler logs:"
kubectl logs deployment/shopease-scaler --tail=12 || true

# ============================================================
# STEP 22 — Grafana password
# ============================================================

GRAFANA_PASSWORD=$(kubectl get secret \
    --namespace monitoring \
    prometheus-grafana \
    -o jsonpath="{.data.admin-password}" |
    base64 --decode)

# ============================================================
# STEP 23 — Prepare Prometheus for monitor.html
# ============================================================

echo ""
echo "📊 Step 23: Preparing Prometheus for monitor.html..."

if command -v lsof >/dev/null 2>&1 && lsof -iTCP:9090 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "✅ Prometheus is available at http://localhost:9090"
else
    nohup kubectl port-forward \
        -n monitoring \
        svc/prometheus-kube-prometheus-prometheus \
        9090:9090 \
        >/tmp/shopease-prometheus-port-forward.log 2>&1 &
    echo $! >/tmp/shopease-prometheus-port-forward.pid
    sleep 3
    echo "✅ Prometheus available at http://localhost:9090"
fi

# STEP 24 — Verify request rate and latency queries
# ============================================================

echo ""
echo "📈 Step 24: Checking request rate and latency metrics..."

REQUEST_RATE="0"
AVG_LATENCY="0"

if curl -fsS --max-time 5 \
    'http://localhost:9090/api/v1/query?query=sum(rate(flask_http_request_total%7Bjob%3D%22shopease-service%22%7D%5B1m%5D))' \
    >/tmp/shopease-rps.json 2>/dev/null; then

    REQUEST_RATE=$(python3 - <<'PY'
import json
try:
    d=json.load(open("/tmp/shopease-rps.json"))
    r=d["data"]["result"]
    print(r[0]["value"][1] if r else "0")
except Exception:
    print("0")
PY
)
fi

if curl -fsS --max-time 5 \
    'http://localhost:9090/api/v1/query?query=(sum(rate(flask_http_request_duration_seconds_sum%7Bjob%3D%22shopease-service%22%7D%5B1m%5D))%20%2F%20sum(rate(flask_http_request_duration_seconds_count%7Bjob%3D%22shopease-service%22%7D%5B1m%5D)))%20*%201000' \
    >/tmp/shopease-latency.json 2>/dev/null; then

    AVG_LATENCY=$(python3 - <<'PY'
import json
try:
    d=json.load(open("/tmp/shopease-latency.json"))
    r=d["data"]["result"]
    print(r[0]["value"][1] if r else "0")
except Exception:
    print("0")
PY
)
fi

echo "Request rate: ${REQUEST_RATE} req/s"
echo "Average latency: ${AVG_LATENCY} ms"

# ============================================================
# FINAL
# ============================================================

echo ""
echo "============================================================"
echo "       ✅ SHOP EASE DEPLOYMENT COMPLETED"
echo "============================================================"
echo ""
echo "🌐 ShopEase:"
echo "   http://$PUBLIC_URL"
echo ""
echo "🗄️ SQL:"
echo "   MySQL service: mysql-service:3306"
echo "   Database: $MYSQL_DATABASE"
echo "   User: $MYSQL_USER"
echo "   schema.sql: loaded"
echo ""
echo "🤖 PPO:"
echo "   deployment/shopease-scaler"
echo "   kubectl logs deployment/shopease-scaler -f"
echo ""
echo "📊 Monitor.html:"
echo "   Open: monitor.html"
echo "   Prometheus: http://localhost:9090"
echo ""
echo "📈 Request rate:"
echo "   sum(rate(flask_http_request_total{job="shopease-service"}[1m]))"
echo ""
echo "📈 Average latency:"
echo "   (sum(rate(flask_http_request_duration_seconds_sum{job="shopease-service"}[1m])) / sum(rate(flask_http_request_duration_seconds_count{job="shopease-service"}[1m]))) * 1000"
echo ""
echo "📊 Grafana:"
echo "   kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80"
echo "   Username: admin"
echo "   Password: $GRAFANA_PASSWORD"
echo ""
echo "🔥 Load test:"
echo "   siege -c 200 -t 3m http://$PUBLIC_URL"
echo ""
echo "⚠️ IMPORTANT: Delete AWS resources after the demo:"
echo "   bash delchat.sh"
echo ""
echo "============================================================"

