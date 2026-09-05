import os
import time
import requests
import torch
import torch.nn as nn
from kubernetes import client, config


# ============================================================
# CONFIGURATION
# ============================================================

MIN_PODS = 1
MAX_PODS = 4
SEQ_LEN = 20
INTERVAL = 15


# ============================================================
# PPO ACTIONS
# ============================================================

# 0 = -2 pods
# 1 = -1 pod
# 2 = no change
# 3 = +1 pod
# 4 = +2 pods

ACTION_DELTAS = [-2, -1, 0, 1, 2]


# ============================================================
# SCALING THRESHOLDS
# ============================================================

# IMPORTANT:
# Scaling decisions are based ONLY on CPU and MEMORY.
#
# RPS and LATENCY are collected for monitoring/dashboard
# purposes, but they are NOT used for scaling.

CPU_HIGH = 0.70
CPU_LOW = 0.20

MEM_HIGH = 0.75
MEM_LOW = 0.25


# ============================================================
# PPO CONFIDENCE
# ============================================================

PPO_CONFIDENCE_THRESHOLD = 0.70


# ============================================================
# KUBERNETES CONFIG
# ============================================================

try:
    config.load_incluster_config()
    IN_CLUSTER = True
    print("✅ Kubernetes in-cluster configuration loaded")

except Exception:
    config.load_kube_config()
    IN_CLUSTER = False
    print("✅ Kubernetes local configuration loaded")


k8s_apps = client.AppsV1Api()


# ============================================================
# PROMETHEUS CONFIG
# ============================================================

PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL",
    "http://prometheus-kube-prometheus-prometheus.monitoring:9090"
)

print(f"📊 Prometheus: {PROMETHEUS_URL}")


# ============================================================
# TRANSFORMER
# ============================================================

class TransformerFeatureExtractor(nn.Module):

    def __init__(
        self,
        input_dim=6,
        d_model=64,
        nhead=4,
        seq_len=20
    ):

        super().__init__()

        self.input_projection = nn.Linear(
            input_dim,
            d_model
        )

        self.pos_embedding = nn.Parameter(
            torch.zeros(
                1,
                seq_len,
                d_model
            )
        )

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=128,
            batch_first=True
        )

        self.transformer_encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=1
        )

    def forward(self, x):

        x = self.input_projection(x)

        x = x + self.pos_embedding[
            :,
            :x.size(1),
            :
        ]

        x = self.transformer_encoder(x)

        return x[:, -1, :]


# ============================================================
# PPO ACTOR
# ============================================================

class PPOActor(nn.Module):

    def __init__(self):

        super().__init__()

        self.feature_extractor = TransformerFeatureExtractor()

        self.actor = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 5)
        )

        self.critic = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, x):

        features = self.feature_extractor(x)

        logits = self.actor(features)

        value = self.critic(features)

        return logits, value


# ============================================================
# LOAD PPO MODEL
# ============================================================

model = PPOActor()

MODEL_PATH = "/app/k8s_ppo_model.pth"


if os.path.exists(MODEL_PATH):

    try:

        model.load_state_dict(
            torch.load(
                MODEL_PATH,
                map_location="cpu"
            )
        )

        model.eval()

        print("✅ PPO Transformer model loaded")

    except Exception as e:

        print(
            f"⚠️ Could not load PPO model: {e}"
        )

else:

    print("⚠️ PPO model not found")


# ============================================================
# PROMETHEUS QUERY
# ============================================================

def query_prometheus(promql):

    try:

        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={
                "query": promql
            },
            timeout=5
        )

        response.raise_for_status()

        data = response.json()

        if data.get("status") != "success":

            return None

        results = data["data"]["result"]

        if not results:

            return None

        return float(
            results[0]["value"][1]
        )

    except Exception as e:

        print(
            f"⚠️ Prometheus query failed: {e}"
        )

        return None


# ============================================================
# KUBERNETES POD COUNT
# ============================================================

def get_current_pods():

    try:

        deployment = k8s_apps.read_namespaced_deployment(
            name="shopease",
            namespace="default"
        )

        replicas = deployment.spec.replicas

        if replicas is None:
            return MIN_PODS

        return replicas

    except Exception as e:

        print(
            f"⚠️ Failed to get pod count: {e}"
        )

        return MIN_PODS


# ============================================================
# SCALE PODS
# ============================================================

def scale_pods(target):

    target = max(
        MIN_PODS,
        min(MAX_PODS, target)
    )

    try:

        body = {
            "spec": {
                "replicas": target
            }
        }

        k8s_apps.patch_namespaced_deployment(
            name="shopease",
            namespace="default",
            body=body
        )

        return target

    except Exception as e:

        print(
            f"❌ Scaling failed: {e}"
        )

        return get_current_pods()


# ============================================================
# CPU
# ============================================================

def get_cpu():

    query = """
sum(
rate(
    container_cpu_usage_seconds_total{
        namespace="default",
        pod=~"shopease-[a-z0-9-]+",
        container="shopease"
    }[2m]
)
)
"""

    value = query_prometheus(query)

    if value is None:

        return 0.0

    return min(
        1.0,
        max(0.0, value)
    )


# ============================================================
# MEMORY
# ============================================================

def get_memory():

    query = """
sum(
    container_memory_working_set_bytes{
        namespace="default",
        pod=~"shopease-[a-z0-9-]+",
        container="shopease"
    }
)
"""

    value = query_prometheus(query)

    if value is None:

        return 0.0

    pods = max(
        get_current_pods(),
        1
    )

    memory_per_pod = value / pods

    memory_ratio = (
        memory_per_pod /
        (512 * 1024 * 1024)
    )

    return min(
        1.0,
        max(0.0, memory_ratio)
    )


# ============================================================
# REQUESTS PER SECOND
# ============================================================

# IMPORTANT:
# DO NOT CHANGE THIS EQUATION.
#
# RPS is collected for monitoring only.
# It is NOT used for scaling.

def get_rps():

    query = """
sum(
    rate(
        flask_http_request_total{
            namespace="default",
            pod=~"shopease-[a-z0-9-]+"
        }[1m]
    )
)
"""

    value = query_prometheus(query)

    if value is None:

        query = """
sum(
    rate(
        flask_http_request_total[1m]
    )
)
"""

        value = query_prometheus(query)

    if value is None:

        return 0.0

    # Normalize around 10 requests/sec
    return min(
        1.0,
        max(
            0.0,
            value / 10.0
        )
    )


# ============================================================
# P95 LATENCY
# ============================================================

# IMPORTANT:
# DO NOT CHANGE THIS EQUATION.
#
# Latency is collected for monitoring only.
# It is NOT used for scaling.

def get_latency():

    query = """
histogram_quantile(
    0.95,
    sum(
        rate(
            flask_http_request_duration_seconds_bucket{
                namespace="default",
                pod=~"shopease-[a-z0-9-]+"
            }[2m]
        )
    ) by (le)
)
"""

    value = query_prometheus(query)

    if value is None:

        query = """
histogram_quantile(
    0.95,
    sum(
        rate(
            flask_http_request_duration_seconds_bucket[2m]
        )
    ) by (le)
)
"""

        value = query_prometheus(query)

    if value is None:

        return 0.0

    return min(
        1.0,
        max(0.0, value)
    )


# ============================================================
# NETWORK
# ============================================================

def get_network():

    query = """
sum(
    rate(
        container_network_receive_bytes_total{
            namespace="default",
            pod=~"shopease-[a-z0-9-]+"
        }[2m]
    )
)
"""

    value = query_prometheus(query)

    if value is None:

        return 0.0

    return min(
        1.0,
        max(
            0.0,
            value / 10_000_000
        )
    )


# ============================================================
# GET ALL REAL METRICS
# ============================================================

def get_metrics(pods):

    cpu = get_cpu()

    memory = get_memory()

    # These are still collected.
    # They are NOT used for scaling.

    rps = get_rps()

    latency = get_latency()

    network = get_network()

    return [
        pods / MAX_PODS,
        cpu,
        memory,
        network,
        rps,
        latency
    ]


# ============================================================
# PPO DECISION
# ============================================================

history = []


def ppo_action(metrics):

    global history

    history.append(metrics)

    if len(history) > SEQ_LEN:

        history.pop(0)

    # --------------------------------------------------------
    # IMPORTANT
    # --------------------------------------------------------
    #
    # Original metrics:
    #
    # [pods, CPU, memory, network, RPS, latency]
    #
    # RPS and latency are monitored but must NOT influence
    # scaling.
    #
    # Therefore they are masked to 0 before being passed
    # to the PPO model.
    #
    # The model architecture still receives 6 inputs.
    # --------------------------------------------------------

    ppo_metrics = list(metrics)

    ppo_metrics[4] = 0.0   # RPS disabled for scaling
    ppo_metrics[5] = 0.0   # Latency disabled for scaling

    # Replace current history entry with masked metrics
    ppo_history = []

    for item in history:

        masked = list(item)

        masked[4] = 0.0
        masked[5] = 0.0

        ppo_history.append(masked)

    padded = (
        [[0.0] * 6] *
        (SEQ_LEN - len(ppo_history))
    ) + ppo_history

    tensor = torch.tensor(
        [padded],
        dtype=torch.float32
    )

    with torch.no_grad():

        logits, _ = model(tensor)

        probabilities = torch.softmax(
            logits,
            dim=-1
        )

        action = torch.argmax(
            probabilities,
            dim=-1
        ).item()

    return (
        action,
        probabilities.numpy()[0]
    )


# ============================================================
# RULE-BASED SCALING DECISION
# ============================================================

def rule_based_action(metrics):

    _, cpu, memory, network, rps, latency = metrics

    # ========================================================
    # SCALE UP
    # ========================================================
    #
    # ONLY CPU AND MEMORY CAN CAUSE SCALE-UP.
    #
    # RPS      -> NOT USED
    # LATENCY  -> NOT USED
    # NETWORK  -> NOT USED
    #
    # ========================================================

    if (
        cpu > CPU_HIGH
        or memory > MEM_HIGH
    ):

        return 1


    # ========================================================
    # SCALE DOWN
    # ========================================================
    #
    # ONLY CPU AND MEMORY CAN cause scale-down.
    #
    # RPS      -> NOT USED
    # LATENCY  -> NOT USED
    # NETWORK  -> NOT USED
    #
    # ========================================================

    if (
        cpu < CPU_LOW
        and memory < MEM_LOW
    ):

        return -1


    # ========================================================
    # KEEP CURRENT POD COUNT
    # ========================================================

    return 0


# ============================================================
# HYBRID DECISION
# ============================================================

def hybrid_decision(
    pods,
    metrics,
    ppo_delta,
    ppo_confidence
):

    rule_delta = rule_based_action(
        metrics
    )

    _, cpu, memory, network, rps, latency = metrics


    # ========================================================
    # SAFETY OVERRIDE
    # ========================================================
    #
    # ONLY CPU AND MEMORY.
    #
    # RPS and latency are intentionally excluded.
    #
    # ========================================================

    if (
        cpu > 0.90
        or memory > 0.90
    ):

        return (
            1,
            "Safety Rule"
        )


    # ========================================================
    # PPO
    # ========================================================
    #
    # PPO receives:
    #
    # CPU
    # Memory
    # Network
    #
    # RPS and latency are masked to zero.
    #
    # ========================================================

    if (
        ppo_confidence >=
        PPO_CONFIDENCE_THRESHOLD
    ):

        # ----------------------------------------------------
        # Additional safety:
        #
        # PPO is not allowed to scale UP unless CPU or
        # memory indicates pressure.
        #
        # ----------------------------------------------------

        if ppo_delta > 0:

            if (
                cpu <= CPU_HIGH
                and memory <= MEM_HIGH
            ):

                return (
                    0,
                    "PPO Blocked"
                )


        # ----------------------------------------------------
        # PPO scale-down is allowed only when CPU and memory
        # are both low.
        # ----------------------------------------------------

        if ppo_delta < 0:

            if (
                cpu >= CPU_LOW
                or memory >= MEM_LOW
            ):

                return (
                    0,
                    "PPO Blocked"
                )


        return (
            ppo_delta,
            "PPO"
        )


    # ========================================================
    # LOW PPO CONFIDENCE
    # ========================================================

    return (
        rule_delta,
        "Rule"
    )


# ============================================================
# MAIN AUTOSCALER
# ============================================================

print("")

print("=" * 70)

print(
    "🚀 SHOPEASE HYBRID AI AUTOSCALER"
)

print("=" * 70)

print(
    f"Mode       : "
    f"{'IN-CLUSTER' if IN_CLUSTER else 'LOCAL'}"
)

print(
    f"Min Pods   : {MIN_PODS}"
)

print(
    f"Max Pods   : {MAX_PODS}"
)

print(
    f"Interval   : {INTERVAL}s"
)

print(
    f"PPO Threshold: "
    f"{PPO_CONFIDENCE_THRESHOLD}"
)

print(
    "Scaling    : CPU + Memory ONLY"
)

print(
    "RPS        : Monitoring ONLY"
)

print(
    "Latency    : Monitoring ONLY"
)

print("=" * 70)


step = 0


while True:

    try:

        step += 1


        # ====================================================
        # CURRENT PODS
        # ====================================================

        pods = get_current_pods()


        # ====================================================
        # GET REAL METRICS
        # ====================================================

        metrics = get_metrics(
            pods
        )

        (
            pod_ratio,
            cpu,
            memory,
            network,
            rps,
            latency
        ) = metrics


        # ====================================================
        # PPO
        # ====================================================

        ppo_index, probabilities = ppo_action(
            metrics
        )

        ppo_delta = ACTION_DELTAS[
            ppo_index
        ]

        ppo_confidence = float(
            probabilities[
                ppo_index
            ]
        )


        # ====================================================
        # HYBRID DECISION
        # ====================================================

        final_delta, source = hybrid_decision(
            pods,
            metrics,
            ppo_delta,
            ppo_confidence
        )


        # ====================================================
        # TARGET POD COUNT
        # ====================================================

        target_pods = max(
            MIN_PODS,
            min(
                MAX_PODS,
                pods + final_delta
            )
        )


        # ====================================================
        # SCALE
        # ====================================================

        if target_pods != pods:

            actual = scale_pods(
                target_pods
            )

        else:

            actual = pods


        # ====================================================
        # LOAD STATUS
        # ====================================================
        #
        # This status is ONLY for display.
        # RPS and latency do NOT control scaling.
        #
        # ====================================================

        if (
            cpu > CPU_HIGH
            or memory > MEM_HIGH
        ):

            load = "🔴 HIGH"

        elif (
            cpu > CPU_LOW
            or memory > MEM_LOW
        ):

            load = "🟡 MEDIUM"

        else:

            load = "🟢 LOW"


        # ====================================================
        # LOG
        # ====================================================

        print("")

        print(
            f"[Step {step:04d}] {load}"
        )

        print(
            f"  Pods    : {pods}"
        )

        print(
            f"  CPU     : {cpu:.1%}"
        )

        print(
            f"  Memory  : {memory:.1%}"
        )

        print(
            f"  Network : {network:.1%}"
        )

        print(
            f"  RPS     : {rps:.1%} "
            f"(monitoring only)"
        )

        print(
            f"  P95 Lat : {latency:.1%} "
            f"(monitoring only)"
        )

        print(
            f"  PPO     : action={ppo_delta:+d} "
            f"confidence={ppo_confidence:.1%}"
        )

        print(
            f"  Rule    : action="
            f"{rule_based_action(metrics):+d}"
        )

        print(
            f"  Source  : {source}"
        )

        print(
            f"  Result  : "
            f"{pods} → {actual} pods"
        )


        # ====================================================
        # WAIT
        # ====================================================

        time.sleep(
            INTERVAL
        )


    except Exception as e:

        print(
            f"❌ Autoscaler error: {e}"
        )

        time.sleep(
            INTERVAL
        )
