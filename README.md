# ShopEase — Self-Healing Cloud Application using Kubernetes Auto Scaling

> B.E. Final Year Project | Dept. of CSE | Cambridge Institute of Technology | VTU 2026–27

## Project Overview

ShopEase is a Flask-based e-commerce application deployed on **AWS EKS (Kubernetes)** with an AI-powered autoscaler using **PPO (Proximal Policy Optimization) Reinforcement Learning** and a **Transformer Encoder**. The system automatically scales pods based on real-time metrics collected by Prometheus.

## Project Structure

```
ecommerce/
├── app.py                    # Flask application 
├── app_mysql_backup.py       # Original MySQL version (backup)
├── scaler.py                 # Hybrid PPO + Rule-based autoscaler
├── train_ppo.py              # PPO model training script
├── k8s_ppo_model.pth         # Trained PPO Transformer model
├── requirements.txt          # Python dependencies
├── Dockerfile                # Flask app container
├── Dockerfile.scaler         # Scaler container
├── firebase-key.json         # Firebase credentials "  gitignored  "
├── deployment.yaml           # K8s deployment for Flask app
├── service.yaml              # K8s LoadBalancer service
├── scaler-deployment.yaml    # K8s deployment for scaler pod
├── scaler-rbac.yaml          # RBAC permissions for scaler
└── templates/
    ├── base.html
    ├── index.html            # Home / product listing
    ├── product.html          # Product detail
    ├── cart.html             # Shopping cart
    ├── checkout.html         # Checkout form
    ├── order_success.html
    ├── login.html
    ├── register.html
    └── admin.html            # Admin panel
```

## System Architecture

```
Users (Siege Load Test)
        ↓
AWS LoadBalancer (Public URL)
        ↓
ShopEase Pods (Flask App) ←──── ECR (Docker Images)
        ↓
Firebase Firestore

Prometheus Pod (inside EKS)
        ↓ scrapes every 15s
ShopEase Pods metrics - CPU, Memory, Network, Disk
        ↓
Scaler Pod (inside EKS)
        ↓ queries Prometheus
PPO + Transformer Model → Scaling Decision
        ↓
kubectl scale → Pods scale up/down automatically
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python Flask |
| Database | Firebase Firestore |
| Containerization | Docker + AWS ECR |
| Orchestration | AWS EKS (Kubernetes) |
| AI Model | PPO + Transformer (PyTorch) |
| Monitoring | Prometheus + Grafana (Helm) |
| Load Testing | Siege |
| Cluster Management | eksctl + kubectl |

## AI Autoscaler

The scaler uses a **hybrid approach**:
- **PPO Transformer model** — reads 20 timesteps of 6 metrics, outputs scaling action
- **Rule-based fallback** — triggers when PPO confidence < 70%

### Input Features (6)
1. Current pod count (normalized)
2. CPU usage %
3. Memory usage %
4. Network bandwidth
5. Disk I/O
6. Request rate (RPS)

### Output Actions (5)
- Scale −2, Scale −1, Keep same, Scale +1, Scale +2

## Local Setup

### Prerequisites
```bash
python3 -m venv cloud
source cloud/bin/activate
pip install -r requirements.txt
```

### Firebase Setup
1. Create Firebase project at console.firebase.google.com
2. Enable Firestore Database in test mode
3. Download service account key → save as `firebase-key.json`
4. Seed data:
```bash
python3 -c "
import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('firebase-key.json')
firebase_admin.initialize_app(cred, {'projectId': 'your-project-id'})
db = firestore.client()
# Add your seed data here
"
```

### Run locally
```bash
python app.py
```
Open: http://localhost:5000

## AWS Deployment

### Prerequisites
```bash
# Install tools
sudo dnf install awscli2        # Fedora
aws configure                   # Add your credentials
eksctl version                  # Verify eksctl installed
```

### Step 1 — Build and push Docker images
```bash
# Login to ECR
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS \
  --password-stdin <account-id>.dkr.ecr.ap-south-1.amazonaws.com

# Create ECR repos
aws ecr create-repository --repository-name shopease --region ap-south-1
aws ecr create-repository --repository-name shopease-scaler --region ap-south-1

# Build and push app
docker build -t shopease .
docker tag shopease:latest <account-id>.dkr.ecr.ap-south-1.amazonaws.com/shopease:latest
docker push <account-id>.dkr.ecr.ap-south-1.amazonaws.com/shopease:latest

# Build and push scaler
docker build -t shopease-scaler -f Dockerfile.scaler .
docker tag shopease-scaler:latest <account-id>.dkr.ecr.ap-south-1.amazonaws.com/shopease-scaler:latest
docker push <account-id>.dkr.ecr.ap-south-1.amazonaws.com/shopease-scaler:latest
```

### Step 2 — Create EKS Cluster
```bash
eksctl create cluster \
  --name shopease-cluster \
  --region ap-south-1 \
  --nodegroup-name shopease-nodes \
  --node-type t3.medium \
  --nodes 2 \
  --nodes-min 1 \
  --nodes-max 4 \
  --managed
```

### Step 3 — Deploy everything
```bash
# Connect kubectl
aws eks update-kubeconfig --region ap-south-1 --name shopease-cluster

# Create Firebase secret
kubectl create secret generic firebase-secret \
  --from-file=firebase-key.json=firebase-key.json

# Deploy app
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml

# Deploy scaler with RBAC
kubectl apply -f scaler-rbac.yaml
kubectl apply -f scaler-deployment.yaml

# Install Prometheus + Grafana
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.enabled=true \
  --set prometheus.prometheusSpec.retention=1h
```

### Step 4 — Get public URL
```bash
kubectl get services
# Copy EXTERNAL-IP of shopease-service
```

### Step 5 — Monitor
```bash
# Watch pods scaling
watch -n 3 kubectl get pods

# Watch scaler decisions
kubectl logs -l app=shopease-scaler -f

# View real CPU/memory
kubectl top pods

# Access Grafana dashboard
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80 &
# Open http://localhost:3000 (admin / get password below)
kubectl get secret --namespace monitoring prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

### Step 6 — Load test
```bash
siege -c 200 -t 3m http://<your-loadbalancer-url>
```

### Step 7 — Delete cluster
```bash
eksctl delete cluster --name shopease-cluster --region ap-south-1
```

## Pages

| Route | Description |
|-------|-------------|
| `/` | Product listing with search, filter, sort |
| `/product/<id>` | Product detail page |
| `/cart` | Shopping cart |
| `/checkout` | Checkout form |
| `/register` | User registration |
| `/login` | User login |
| `/admin` | Admin panel (add/delete products) |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| FLASK_SECRET_KEY | shopease_secret_key | Flask session key |
| FIREBASE_KEY | firebase-key.json | Path to Firebase credentials |
| PROMETHEUS_URL | http://localhost:9090 | Prometheus endpoint |

## Demo Results

- **Availability**: 97.6% under 200 concurrent users
- **Transactions**: 6,492+ hits in 3 minutes
- **Autoscaling**: Pods scaled 1→2→3→2→1 automatically
- **Real metrics**: CPU rising 1m→24m→51m→108m millicores under load
- **Scaler**: Runs as pod INSIDE EKS — no local machine dependency

## Base Paper

Singh, Muppiri & Chana, *"Efficient Resource Management of Kubernetes Pods using Artificial Intelligence"*, IEEE PDGC 2024.
DOI: 10.1109/PDGC64653.2024.10984409

Our project directly implements the future work suggested in this paper:
- ✅ Transformer models for prediction
- ✅ PPO Reinforcement Learning
- ✅ Real-world cloud deployment (AWS EKS)
- ✅ Multiple metrics (network, disk, latency)

## Team

- Bukka Rohith Reddy (1CD23CS031)
- K Bhuvan Chowdary (1CD23CS071)

**Guide**: Prof. Venkatesh Prasad
**Institution**: Cambridge Institute of Technology, Bangalore
**University**: Visvesvaraya Technological University, Belagavi
