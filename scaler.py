import torch
import torch.nn as nn
import subprocess
import time
import random
import math

# ── Model Architecture (must match training) ──────────────────────────────────
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
        return x[:, -1, :]  # last token

class PPOActor(nn.Module):
    def __init__(self, d_model=64, n_actions=5):
        super().__init__()
        self.feature_extractor = TransformerFeatureExtractor()
        self.actor = nn.Sequential(
            nn.Linear(d_model, 32),
            nn.ReLU(),
            nn.Linear(32, n_actions)
        )
        self.critic = nn.Sequential(
            nn.Linear(d_model, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, x):
        features = self.feature_extractor(x)
        return self.actor(features)

# ── Load Model ─────────────────────────────────────────────────────────────────
model = PPOActor()
state_dict = torch.load('k8s_ppo_model.pth', map_location='cpu')
model.load_state_dict(state_dict)
model.eval()
print("✅ PPO model loaded successfully")

# ── Action Map ─────────────────────────────────────────────────────────────────
# 5 actions: scale -2, -1, 0, +1, +2
ACTION_DELTAS = [-2, -1, 0, 1, 2]
MIN_PODS = 1
MAX_PODS = 4

def get_current_pods():
    result = subprocess.run(
        ["kubectl", "get", "deployment", "shopease",
         "-o", "jsonpath={.spec.replicas}"],
        capture_output=True, text=True
    )
    return int(result.stdout.strip() or 2)

def scale_pods(n):
    n = max(MIN_PODS, min(MAX_PODS, n))
    subprocess.run(
        ["kubectl", "scale", "deployment", "shopease",
         f"--replicas={n}"],
        capture_output=True
    )
    print(f"  → Scaled to {n} pods")
    return n

def get_metrics(current_pods):
    """
    Simulate metrics with more extreme values to trigger scaling
    """
    import time
    t = time.time()
    # cycle through low/medium/high load every 3 steps
    phase = int(t / 30) % 3
    if phase == 0:   # low load
        cpu = random.uniform(5, 20)
        memory = random.uniform(10, 30)
        request_rate = random.uniform(5, 50)
        response_time = random.uniform(0.05, 0.3)
        error_rate = random.uniform(0, 0.01)
    elif phase == 1:  # high load
        cpu = random.uniform(80, 99)
        memory = random.uniform(75, 95)
        request_rate = random.uniform(400, 500)
        response_time = random.uniform(2.0, 5.0)
        error_rate = random.uniform(0.05, 0.15)
    else:             # medium load
        cpu = random.uniform(40, 60)
        memory = random.uniform(40, 60)
        request_rate = random.uniform(150, 300)
        response_time = random.uniform(0.5, 1.0)
        error_rate = random.uniform(0.01, 0.03)
    return [current_pods, cpu, memory, request_rate, response_time, error_rate]

def normalize(metrics):
    """Normalize inputs to [0,1] range"""
    pods, cpu, mem, rps, rt, err = metrics
    return [
        pods / MAX_PODS,
        cpu / 100.0,
        mem / 100.0,
        rps / 500.0,
        rt / 5.0,
        err / 1.0
    ]

# ── Main Scaling Loop ──────────────────────────────────────────────────────────
SEQ_LEN = 20   # use last 10 timesteps
history = []   # rolling window of metric vectors
INTERVAL = 30  # seconds between decisions

print(f"🚀 PPO Autoscaler started — checking every {INTERVAL}s")
print(f"   Min pods: {MIN_PODS}, Max pods: {MAX_PODS}")
print("-" * 50)

while True:
    current_pods = get_current_pods()
    raw_metrics = get_metrics(current_pods)
    norm_metrics = normalize(raw_metrics)
    history.append(norm_metrics)

    # keep only last SEQ_LEN steps
    if len(history) > SEQ_LEN:
        history.pop(0)

    # pad if not enough history yet
    padded = history.copy()
    while len(padded) < SEQ_LEN:
        padded.insert(0, [0.0] * 6)

    # build tensor [1, SEQ_LEN, 6]
    x = torch.tensor([padded], dtype=torch.float32)

    with torch.no_grad():
        logits = model(x)
        action = torch.argmax(logits, dim=-1).item()

    delta = ACTION_DELTAS[action]
    new_pods = current_pods + delta

    print(f"[Step] pods={current_pods} | "
          f"cpu={raw_metrics[1]:.1f}% | "
          f"mem={raw_metrics[2]:.1f}% | "
          f"rps={raw_metrics[3]:.0f} | "
          f"action={delta:+d}")

    if delta != 0:
        scale_pods(new_pods)
    else:
        print(f"  → No change (staying at {current_pods} pods)")

    time.sleep(INTERVAL)
