import torch
import torch.nn as nn
import subprocess
import time
import random
import requests
import os
from kubernetes import client, config

# ── Configuration & Environment Setup ───────────────────────────────────────
# Detect environment: Runs inside pod (in-cluster) or locally
try:
    config.load_incluster_config()
    IN_CLUSTER = True
except:
    config.load_kube_config()
    IN_CLUSTER = False

# Prometheus URL setup
PROMETHEUS_URL = os.getenv(
    'PROMETHEUS_URL',
    'http://prometheus-kube-prometheus-prometheus.monitoring:9090' if IN_CLUSTER
    else 'http://localhost:9090'
)

# Constants
MIN_PODS, MAX_PODS = 1, 4
SEQ_LEN = 20
INTERVAL = 15
ACTION_DELTAS = [-2, -1, 0, 1, 2]
history = []

# ── Model Definitions ───────────────────────────────────────────────────────
class TransformerFeatureExtractor(nn.Module):
    def __init__(self, input_dim=6, d_model=64, nhead=4, seq_len=20):
        super().__init__()
        self.input_projection = nn.Linear(input_dim, d_model)
        self.pos_embedding = nn.Parameter(torch.zeros(1, seq_len, d_model))
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead,
            dim_feedforward=128, batch_first=True
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=1)
    
    def forward(self, x):
        x = self.input_projection(x)
        x = x + self.pos_embedding[:, :x.size(1), :]
        x = self.transformer_encoder(x)
        return x[:, -1, :]

class PPOActor(nn.Module):
    def __init__(self):
        super().__init__()
        self.feature_extractor = TransformerFeatureExtractor()
        self.actor  = nn.Sequential(nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 5))
        self.critic = nn.Sequential(nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 1))
    
    def forward(self, x):
        f = self.feature_extractor(x)
        return self.actor(f), self.critic(f)

# Load PPO Model
model = PPOActor()
if os.path.exists('k8s_ppo_model.pth'):
    model.load_state_dict(torch.load('k8s_ppo_model.pth', map_location='cpu'))
    model.eval()
    print("✅ PPO Transformer model loaded")
else:
    print("⚠️  Warning: Model file not found, using uninitialized weights")

# ── Kubernetes Operations ───────────────────────────────────────────────────
k8s_apps = client.AppsV1Api()

def get_current_pods():
    if IN_CLUSTER:
        try:
            dep = k8s_apps.read_namespaced_deployment('shopease', 'default')
            return dep.spec.replicas
        except: return 2
    else:
        result = subprocess.run(["kubectl", "get", "deployment", "shopease", "-o", "jsonpath={.spec.replicas}"],
                                capture_output=True, text=True)
        try: return int(result.stdout.strip())
        except: return 2

def scale_pods(n):
    n = max(MIN_PODS, min(MAX_PODS, n))
    if IN_CLUSTER:
        dep = k8s_apps.read_namespaced_deployment('shopease', 'default')
        dep.spec.replicas = n
        k8s_apps.patch_namespaced_deployment('shopease', 'default', dep)
    else:
        subprocess.run(["kubectl", "scale", "deployment", "shopease", f"--replicas={n}"], capture_output=True)
    return n

# ── Metrics & Logic ─────────────────────────────────────────────────────────
def query_prometheus(promql):
    try:
        r = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={'query': promql}, timeout=5)
        data = r.json()
        if data['status'] == 'success' and data['data']['result']:
            return float(data['data']['result'][0]['value'][1])
    except: pass
    return None

def get_metrics(pods):
    cpu      = query_prometheus('sum(rate(container_cpu_usage_seconds_total{pod=~"shopease-.*"}[2m]))')
    mem      = query_prometheus('sum(container_memory_working_set_bytes{pod=~"shopease-.*"})/1024/1024/512')
    network  = query_prometheus('sum(rate(container_network_receive_bytes_total{pod=~"shopease-.*"}[2m]))')
    disk     = query_prometheus('sum(rate(container_fs_reads_bytes_total{pod=~"shopease-.*"}[2m]))')
    rps      = query_prometheus('sum(rate(container_cpu_usage_seconds_total{pod=~"shopease-.*"}[1m]))')
    err_rate = query_prometheus('sum(rate(container_oom_events_total{pod=~"shopease-.*"}[2m]))')

    cpu     = min(1.0, (cpu     or 0) / 2.0)
    mem     = min(1.0, (mem     or 0))
    network = min(1.0, (network or 0) / 1e7)   # normalize to 10MB/s
    disk    = min(1.0, (disk    or 0) / 1e6)   # normalize to 1MB/s
    rps     = min(1.0, (rps     or 0) / 2.0)
    err     = min(1.0, (err_rate or 0))

    return [pods / MAX_PODS, cpu, mem, network, disk, rps]
def ppo_action(metrics):
    global history
    history.append(metrics)
    if len(history) > SEQ_LEN: history.pop(0)
    padded = [[0.0]*6]*(SEQ_LEN - len(history)) + history
    with torch.no_grad():
        logits, _ = model(torch.tensor([padded], dtype=torch.float32))
        probs = torch.softmax(logits, dim=-1)
        return torch.argmax(logits).item(), probs.numpy()[0]

# ── Main Loop ───────────────────────────────────────────────────────────────
print(f"\n🚀 Autoscaler active. In-cluster: {IN_CLUSTER}")
while True:
    pods = get_current_pods()
    metrics = get_metrics(pods)
    act_idx, probs = ppo_action(metrics)
    
    # Simple hybrid: if model is > 70% confident, use PPO, else use rule
    if probs[act_idx] > 0.7:
        decision = pods + ACTION_DELTAS[act_idx]
        source = "PPO"
    else:
        decision = pods + (1 if metrics[1] > 0.10 or metrics[3] > 0.20
                  else -1 if metrics[1] < 0.05 and metrics[3] < 0.05
                  else 0)
        source = "Rule"
        
    new_pods = scale_pods(decision)
    print(f"\n[Step] pods={pods} cpu={metrics[1]:.0%} mem={metrics[2]:.0%} net={metrics[3]:.0%} disk={metrics[4]:.0%} rps={metrics[5]:.0%}")
    print(f"  PPO    : action={ACTION_DELTAS[act_idx]:+d} | confidence={probs[act_idx]:.0%}")
    print(f"  Source : {source}")
    print(f"  Result : {pods} → {new_pods} pods")
    time.sleep(INTERVAL)
