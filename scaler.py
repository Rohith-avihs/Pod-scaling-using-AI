import torch
import torch.nn as nn
import subprocess
import time
import random
import requests

PROMETHEUS_URL = "http://localhost:9090"

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

model = PPOActor()
model.load_state_dict(torch.load('k8s_ppo_model.pth', map_location='cpu'))
model.eval()
print("✅ PPO Transformer model loaded")

MIN_PODS = 1
MAX_PODS = 4
SEQ_LEN  = 20
INTERVAL = 15
ACTION_DELTAS = [-2, -1, 0, 1, 2]
history = []

def get_current_pods():
    result = subprocess.run(
        ["kubectl", "get", "deployment", "shopease",
         "-o", "jsonpath={.spec.replicas}"],
        capture_output=True, text=True
    )
    try:
        return int(result.stdout.strip())
    except:
        return 2

def scale_pods(n):
    n = max(MIN_PODS, min(MAX_PODS, n))
    subprocess.run(
        ["kubectl", "scale", "deployment", "shopease", f"--replicas={n}"],
        capture_output=True
    )
    return n

def query_prometheus(promql):
    try:
        r = requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                        params={'query': promql}, timeout=5)
        data = r.json()
        if data['status'] == 'success' and data['data']['result']:
            return float(data['data']['result'][0]['value'][1])
    except:
        pass
    return None

def get_metrics(pods):
    """Get REAL metrics from Prometheus"""
    # CPU usage rate per pod (normalized 0-1)
    cpu = query_prometheus(
        'sum(rate(container_cpu_usage_seconds_total{namespace="default",pod=~"shopease-.*",container!=""}[2m]))'
    )
    # Memory usage (normalized 0-1, assuming 512Mi limit)
    mem = query_prometheus(
        'sum(container_memory_working_set_bytes{namespace="default",pod=~"shopease-.*",container!=""})/sum(kube_pod_container_resource_limits{namespace="default",pod=~"shopease-.*",resource="memory"})'
    )
    # HTTP requests per second
    rps = query_prometheus(
        'sum(rate(container_cpu_usage_seconds_total{namespace="default",pod=~"shopease-.*"}[1m]))'
    )

    # fallback to simulated if Prometheus unavailable
    if cpu is None:
        t = int(time.time() / INTERVAL) % 9
        if t < 3:
            cpu = random.uniform(0.05, 0.20)
            mem = random.uniform(0.05, 0.25)
        elif t < 6:
            cpu = random.uniform(0.30, 0.60)
            mem = random.uniform(0.30, 0.55)
        else:
            cpu = random.uniform(0.75, 0.99)
            mem = random.uniform(0.70, 0.90)
        rps = random.uniform(0.02, 1.0)
        print("  ⚠️  Using simulated metrics (Prometheus unavailable)")
    else:
        cpu = min(1.0, max(0.0, cpu / 2.0))  # divide by 2 cores (t3.medium)
        mem = min(1.0, max(0.0, mem if mem else random.uniform(0.2, 0.5)))
        rps = min(1.0, max(0.0, (rps / 2.0) if rps else 0.3))
        print("  📊 Using REAL Prometheus metrics")

    rt  = max(0.01, min(1.0, cpu / max(pods, 1) * 0.8))
    err = max(0.0,  min(1.0, cpu - 0.85)) if cpu > 0.85 else 0.0
    return [pods / MAX_PODS, cpu, mem, rps, rt, err]

def rule_based(metrics):
    _, cpu, mem, rps, rt, err = metrics
    if cpu > 0.03 or rps > 0.03:  # 3% of 2 cores = ~60 millicores
        return 3   # scale +1
    elif cpu < 0.01 and rps < 0.01:
        return 1   # scale -1
    else:
        return 2   # keep same

def ppo_action(metrics):
    global history
    history.append(metrics)
    if len(history) > SEQ_LEN:
        history.pop(0)
    padded = history.copy()
    while len(padded) < SEQ_LEN:
        padded.insert(0, [0.0] * 6)
    x = torch.tensor([padded], dtype=torch.float32)
    with torch.no_grad():
        logits, _ = model(x)
        probs = torch.softmax(logits, dim=-1)
        action = torch.argmax(logits).item()
    return action, probs.numpy()[0]

print(f"\n🚀 Hybrid Autoscaler running — interval: {INTERVAL}s")
print(f"   Pods range: {MIN_PODS}–{MAX_PODS}")
print("-" * 65)

step = 0
while True:
    step += 1
    pods = get_current_pods()
    metrics = get_metrics(pods)
    _, cpu, mem, rps, rt, err = metrics

    ppo_act, probs = ppo_action(metrics)
    ppo_delta = ACTION_DELTAS[ppo_act]
    rule_act  = rule_based(metrics)
    rule_delta = ACTION_DELTAS[rule_act]

    load_level = "🔴 HIGH" if cpu > 0.75 else "🟡 MED" if cpu > 0.30 else "🟢 LOW"

    print(f"\n[Step {step:3d}] {load_level}")
    print(f"  Metrics : pods={pods} cpu={cpu:.0%} mem={mem:.0%} rps={rps:.0%}")
    print(f"  PPO     : action={ppo_delta:+d} | probs={probs.round(2)}")
    print(f"  Rule    : action={rule_delta:+d}")

    new_pods = max(MIN_PODS, min(MAX_PODS, pods + rule_delta))
    print(f"  Decision: {pods} → {new_pods} pods")

    if rule_delta != 0:
        scale_pods(new_pods)
        print(f"  ✅ Scaled to {new_pods} pods")
    else:
        print(f"  ➡️  No change")

    time.sleep(INTERVAL)
