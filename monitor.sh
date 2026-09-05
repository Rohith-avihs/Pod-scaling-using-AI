#!/bin/bash
# ============================================================
# ShopEase — Real-time Pod Scaling Monitor
# Run this during demo to show scaling visually
# ============================================================

GREEN='\033[92m'
RED='\033[91m'
YELLOW='\033[93m'
BLUE='\033[94m'
CYAN='\033[96m'
BOLD='\033[1m'
RESET='\033[0m'

clear
echo -e "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║     ShopEase — Live Pod Autoscaling Monitor          ║"
echo "║     PPO + Transformer | AWS EKS | Kubernetes         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${RESET}"

PREV_COUNT=0

while true; do
    # Get current pod count
    POD_COUNT=$(kubectl get deployment shopease \
      -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")

    # Get pod details
    PODS=$(kubectl get pods -l app=shopease \
      --no-headers 2>/dev/null)

    # Get CPU from metrics server
    CPU=$(kubectl top pods -l app=shopease \
      --no-headers 2>/dev/null | \
      awk '{sum+=$2} END {print sum}')

    # Get scaler last decision
    LAST_LOG=$(kubectl logs -l app=shopease-scaler \
      --tail=5 2>/dev/null | grep "Result")

    # Clear screen and redraw
    clear
    echo -e "${BOLD}${CYAN}"
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║     ShopEase — Live Pod Autoscaling Monitor          ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo -e "${RESET}"

    # Timestamp
    echo -e "${BLUE}🕐 $(date '+%H:%M:%S')${RESET}"
    echo ""

    # Pod count with visual bar
    echo -e "${BOLD}📦 ACTIVE PODS: ${RESET}"

    # Show pod scaling direction
    if [ "$POD_COUNT" -gt "$PREV_COUNT" ] 2>/dev/null; then
        echo -e "${GREEN}${BOLD}  ▲ SCALING UP!   $PREV_COUNT → $POD_COUNT pods${RESET}"
    elif [ "$POD_COUNT" -lt "$PREV_COUNT" ] 2>/dev/null; then
        echo -e "${RED}${BOLD}  ▼ SCALING DOWN! $PREV_COUNT → $POD_COUNT pods${RESET}"
    else
        echo -e "${YELLOW}  → STABLE: $POD_COUNT pods${RESET}"
    fi

    # Visual pod representation
    echo ""
    echo -n "  "
    for i in $(seq 1 $POD_COUNT); do
        echo -ne "${GREEN}[POD $i ✓]${RESET} "
    done
    echo ""
    echo ""

    # Pod details
    echo -e "${BOLD}📋 POD STATUS:${RESET}"
    echo "$PODS" | while read line; do
        NAME=$(echo $line | awk '{print $1}')
        STATUS=$(echo $line | awk '{print $3}')
        AGE=$(echo $line | awk '{print $5}')
        if [ "$STATUS" = "Running" ]; then
            echo -e "  ${GREEN}✓${RESET} $NAME | $STATUS | Age: $AGE"
        else
            echo -e "  ${YELLOW}⟳${RESET} $NAME | $STATUS | Age: $AGE"
        fi
    done

    echo ""

    # CPU metrics
    if [ ! -z "$CPU" ]; then
        echo -e "${BOLD}📊 CPU USAGE: ${CPU}m millicores${RESET}"
        # Simple bar chart
        BAR_LENGTH=$((CPU / 10))
        echo -n "  ["
        for i in $(seq 1 $BAR_LENGTH); do
            if [ $i -lt 5 ]; then
                echo -ne "${GREEN}█${RESET}"
            elif [ $i -lt 8 ]; then
                echo -ne "${YELLOW}█${RESET}"
            else
                echo -ne "${RED}█${RESET}"
            fi
        done
        echo "]"
    fi

    echo ""

    # Last scaler decision
    echo -e "${BOLD}🤖 LAST SCALER DECISION:${RESET}"
    if [ ! -z "$LAST_LOG" ]; then
        echo "$LAST_LOG" | while read line; do
            if echo "$line" | grep -q "→"; then
                FROM=$(echo $line | grep -oP '\d+ →' | head -1)
                TO=$(echo $line | grep -oP '→ \d+' | head -1)
                if [ "$POD_COUNT" -gt "$PREV_COUNT" ] 2>/dev/null; then
                    echo -e "  ${GREEN}$line${RESET}"
                elif [ "$POD_COUNT" -lt "$PREV_COUNT" ] 2>/dev/null; then
                    echo -e "  ${RED}$line${RESET}"
                else
                    echo -e "  ${YELLOW}$line${RESET}"
                fi
            fi
        done
    else
        echo -e "  ${YELLOW}Waiting for scaler decisions...${RESET}"
    fi

    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "  Refreshing every 5 seconds... Press Ctrl+C to stop"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"

    PREV_COUNT=$POD_COUNT
    sleep 5
done
