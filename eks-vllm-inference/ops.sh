#!/bin/bash
# ops.sh — Interactive operations CLI for the vLLM inference cluster on EKS
# Usage: ./scripts/ops.sh
# Dependencies: kubectl, aws, curl, jq
# To use a different profile at runtime without editing the file:
#   
# AWS_PROFILE=other-profile ./scripts/ops.sh
set -euo pipefail

# ── Config (override via environment) ────────────────────────────────────────
CLUSTER_NAME="${CLUSTER_NAME:-llm-inference-poc}"
REGION="${REGION:-eu-west-1}"
NAMESPACE="${NAMESPACE:-inference}"
ALB_URL="${ALB_URL:-yourlb.eu-west-1.elb.amazonaws.com}"
MODEL_NAME="${MODEL_NAME:-mistral-7b}"
LOG_LINES="${LOG_LINES:-100}"
AWS_PROFILE="${AWS_PROFILE:-yourawsprofile}"
# Node group names as defined in CDK eks-stack.ts (addNodegroupCapacity)
NODEGROUP_GPU="${NODEGROUP_GPU:-gpu-inference}"
NODEGROUP_SYSTEM="${NODEGROUP_SYSTEM:-system-nodes}"

export AWS_PROFILE

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
err()  { echo -e "  ${RED}✗${NC} $*"; }
info() { echo -e "  ${CYAN}→${NC} $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $*"; }
hr()   { echo -e "  ${BLUE}──────────────────────────────────────────────${NC}"; }

# ── Prerequisites ─────────────────────────────────────────────────────────────
check_prereqs() {
    local missing=()
    for cmd in kubectl aws curl jq; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo -e "${RED}Missing required tools: ${missing[*]}${NC}"
        echo "  Install: brew install ${missing[*]}"
        exit 1
    fi
}

# ── Helpers ───────────────────────────────────────────────────────────────────
get_vllm_pod() {
    kubectl get pod -n "$NAMESPACE" -l app=vllm-inference \
        --field-selector=status.phase=Running \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
}

header() {
    clear
    echo -e "${BOLD}${BLUE}"
    echo "  ╔═══════════════════════════════════════════════╗"
    echo "  ║   vLLM Inference Ops  ·  ${CLUSTER_NAME}   ║"
    echo "  ╚═══════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo -e "  Cluster: ${BOLD}${CLUSTER_NAME}${NC}  ·  Region: ${BOLD}${REGION}${NC}  ·  Model: ${BOLD}${MODEL_NAME}${NC}  ·  AWS Profile: ${BOLD}${AWS_PROFILE}${NC}"
    hr
}

pause() {
    echo ""
    read -rp "  Press Enter to return to menu..."
}

# ── 1. Pod status ─────────────────────────────────────────────────────────────
pod_status() {
    info "Pods in namespace: $NAMESPACE"
    hr
    kubectl get pods -n "$NAMESPACE" -o wide
    echo ""
    info "Pod count: $(kubectl get pods -n "$NAMESPACE" --no-headers | wc -l | tr -d ' ')"
    local not_running
    not_running=$(kubectl get pods -n "$NAMESPACE" --no-headers | grep -v ' Running ' | wc -l | tr -d ' ')
    [[ "$not_running" -gt 0 ]] && warn "$not_running pod(s) not in Running state"
}

# ── 2. vLLM logs ─────────────────────────────────────────────────────────────
vllm_logs() {
    local pod
    pod=$(get_vllm_pod)
    if [[ -z "$pod" ]]; then
        err "No running vllm-inference pod found"
        return
    fi
    info "Tailing last $LOG_LINES lines from $pod  (Ctrl+C to stop)"
    hr
    kubectl logs -n "$NAMESPACE" "$pod" -c vllm --tail="$LOG_LINES" -f
}

# ── 3. Init container logs ────────────────────────────────────────────────────
init_logs() {
    info "Init container (model-downloader) logs:"
    hr
    kubectl logs -n "$NAMESPACE" deploy/vllm-inference -c model-downloader --tail=80 2>/dev/null \
        || err "Could not retrieve init container logs (pod may still be initialising)"
}

# ── 4. Model prefetch status ──────────────────────────────────────────────────
prefetch_status() {
    info "Model prefetch DaemonSet pods:"
    hr
    kubectl get pods -n "$NAMESPACE" -l app=model-prefetch -o wide
    echo ""
    local prefetch_pod
    prefetch_pod=$(kubectl get pod -n "$NAMESPACE" -l app=model-prefetch \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [[ -n "$prefetch_pod" ]]; then
        info "Model cache directory on node:"
        kubectl exec -n "$NAMESPACE" "$prefetch_pod" -- \
            ls -lh /mnt/models/ 2>/dev/null \
            && ok "Sentinel check:" \
            && kubectl exec -n "$NAMESPACE" "$prefetch_pod" -- \
                sh -c 'ls /mnt/models/*/. model_ready 2>/dev/null && echo "  .model_ready found" || echo "  No sentinel yet"' \
            || warn "Could not exec into prefetch pod"
    fi
}

# ── 5. Restart deployment ─────────────────────────────────────────────────────
restart_deployment() {
    warn "This will trigger a rolling restart of vllm-inference"
    warn "At least 1 replica stays live (maxUnavailable=0 + PDB minAvailable=1)"
    read -rp "  Confirm restart? (yes/no): " confirm
    if [[ "$confirm" == "yes" ]]; then
        kubectl rollout restart deployment/vllm-inference -n "$NAMESPACE"
        ok "Rolling restart initiated — watching rollout status..."
        kubectl rollout status deployment/vllm-inference -n "$NAMESPACE"
    else
        info "Cancelled"
    fi
}

# ── 6. Warning events ─────────────────────────────────────────────────────────
events() {
    info "Recent Warning events in $NAMESPACE (last 20):"
    hr
    kubectl get events -n "$NAMESPACE" \
        --sort-by='.lastTimestamp' \
        --field-selector type=Warning 2>/dev/null | tail -20 \
        || info "No warning events found"
}

# ── 7. Node status ────────────────────────────────────────────────────────────
node_status() {
    info "All nodes:"
    hr
    kubectl get nodes -o wide
    echo ""
    info "GPU nodes (workload=gpu):"
    kubectl get nodes -l workload=gpu \
        -o custom-columns=\
'NAME:.metadata.name,STATUS:.status.conditions[-1].type,INSTANCE-TYPE:.metadata.labels.node\.kubernetes\.io/instance-type,GPU:.status.allocatable.nvidia\.com/gpu,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory' \
        2>/dev/null || warn "No nodes with label workload=gpu found"
    echo ""
    info "Node count summary:"
    printf "  %-20s %s\n" "Total nodes:"  "$(kubectl get nodes --no-headers | wc -l | tr -d ' ')"
    printf "  %-20s %s\n" "GPU nodes:"    "$(kubectl get nodes -l workload=gpu --no-headers 2>/dev/null | wc -l | tr -d ' ')"
    printf "  %-20s %s\n" "System nodes:" "$(kubectl get nodes -l role=system --no-headers 2>/dev/null | wc -l | tr -d ' ')"
}

# ── 8. HPA status ─────────────────────────────────────────────────────────────
hpa_status() {
    info "HPA status:"
    hr
    kubectl get hpa -n "$NAMESPACE"
    echo ""
    kubectl describe hpa vllm-inference-hpa -n "$NAMESPACE" 2>/dev/null \
        | grep -E "^(Conditions|Metrics|Min replicas|Max replicas|Current replicas|Events)" -A 3 \
        || warn "HPA vllm-inference-hpa not found — check prometheus-adapter"
}

# ── 9. Scale deployment ───────────────────────────────────────────────────────
scale_deployment() {
    local current
    current=$(kubectl get deployment vllm-inference -n "$NAMESPACE" \
        -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "?")
    warn "Current replicas: $current"
    warn "Note: HPA manages scale-out automatically. Manual scaling overrides temporarily."
    read -rp "  Set replicas to (1-3): " target
    if [[ "$target" =~ ^[1-3]$ ]]; then
        kubectl scale deployment vllm-inference -n "$NAMESPACE" --replicas="$target"
        ok "Scaled to $target replicas"
    else
        err "Invalid — must be 1, 2, or 3 (matches GPU node group maxSize)"
    fi
}

# ── 10. GPU & vLLM metrics ────────────────────────────────────────────────────
gpu_metrics() {
    local pod
    pod=$(get_vllm_pod)
    if [[ -z "$pod" ]]; then
        err "No running vllm pod found"
        return
    fi
    info "Raw vLLM Prometheus metrics from $pod:"
    hr
    kubectl exec -n "$NAMESPACE" "$pod" -c vllm -- \
        curl -s localhost:8000/metrics 2>/dev/null \
        | grep -E '^vllm:(gpu_cache|num_requests|e2e_request|time_to_first|time_per_output)' \
        | grep -v '^#' \
        | sort
}

# ── 11. KV cache snapshot ─────────────────────────────────────────────────────
kv_cache_status() {
    local pod
    pod=$(get_vllm_pod)
    if [[ -z "$pod" ]]; then
        err "No running vllm pod found"
        return
    fi
    info "KV cache & request queue snapshot:"
    hr
    local metrics kv_usage waiting running
    metrics=$(kubectl exec -n "$NAMESPACE" "$pod" -c vllm -- \
        curl -s localhost:8000/metrics 2>/dev/null)
    kv_usage=$(echo "$metrics" | grep 'vllm:gpu_cache_usage_perc{' | awk '{print $2}' | head -1)
    waiting=$(echo  "$metrics" | grep 'vllm:num_requests_waiting{'  | awk '{print $2}' | head -1)
    running=$(echo  "$metrics" | grep 'vllm:num_requests_running{'  | awk '{print $2}' | head -1)
    echo ""
    printf "  %-30s ${BOLD}%s%%${NC}\n"  "KV cache usage:"    "${kv_usage:-N/A}"
    printf "  %-30s ${BOLD}%s${NC}\n"    "Requests running:"  "${running:-N/A}"
    printf "  %-30s ${BOLD}%s${NC}\n"    "Requests waiting:"  "${waiting:-N/A}"
    echo ""
    # Thresholds matching HPA configuration
    if [[ "${kv_usage:-0}" == "N/A" ]]; then
        warn "Could not read KV cache metric"
    elif (( $(echo "${kv_usage:-0} > 80" | bc -l 2>/dev/null || echo 0) )); then
        warn "KV cache > 80% — HPA scale-out should be triggering"
    else
        ok "KV cache within normal range"
    fi
    [[ "${waiting:-0}" != "N/A" ]] && [[ "${waiting:-0}" -gt 5 ]] 2>/dev/null \
        && warn "Queue depth > 5 — HPA scale-out should be triggering"
}

# ── 12. Health check ──────────────────────────────────────────────────────────
health_check() {
    info "Health check → http://${ALB_URL}/health"
    hr
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 \
        "http://${ALB_URL}/health" 2>/dev/null || echo "TIMEOUT")
    if [[ "$http_code" == "200" ]]; then
        ok "HTTP $http_code — service is healthy"
    elif [[ "$http_code" == "TIMEOUT" ]]; then
        err "Request timed out — ALB or pod may be unreachable"
    else
        err "HTTP $http_code — service may be degraded"
        info "Check pod status (option 1) and vLLM logs (option 2)"
    fi
    echo ""
    info "Available models:"
    curl -s --max-time 10 "http://${ALB_URL}/v1/models" 2>/dev/null \
        | jq -r '.data[].id' 2>/dev/null || warn "Could not fetch model list"
}

# ── 13. Test prompt ───────────────────────────────────────────────────────────
test_prompt() {
    local default_prompt="Write a Python function that checks if a string is a palindrome."
    echo ""
    echo -e "  Default prompt: ${CYAN}${default_prompt}${NC}"
    read -rp "  Enter custom prompt (or Enter for default): " user_prompt
    local prompt="${user_prompt:-$default_prompt}"
    local max_tokens=512
    read -rp "  Max output tokens [${max_tokens}]: " user_tokens
    [[ -n "$user_tokens" ]] && max_tokens="$user_tokens"

    info "Sending to ${MODEL_NAME} (max_tokens=${max_tokens})..."
    hr
    local response
    response=$(curl -s --max-time 120 "http://${ALB_URL}/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"${MODEL_NAME}\",
            \"messages\": [{\"role\": \"user\", \"content\": \"${prompt}\"}],
            \"max_tokens\": ${max_tokens}
        }" 2>/dev/null)
    echo "$response" | jq -r '.choices[0].message.content // .error.message // "No response received"' 2>/dev/null \
        || echo "$response"
    echo ""
    # Show token usage
    local usage
    usage=$(echo "$response" | jq -r '"  Tokens → prompt: \(.usage.prompt_tokens)  completion: \(.usage.completion_tokens)  total: \(.usage.total_tokens)"' 2>/dev/null || true)
    [[ -n "$usage" ]] && echo -e "  ${CYAN}${usage}${NC}"
}

# ── 16. Night mode — scale everything to 0 ────────────────────────────────────
# Sets both node group ASGs min/desired to 0 AND scales the Deployment to 0.
# EKS control plane keeps running (~£0.10/hr) — that cannot be avoided.
# Restore with option 17 before your next working session.
night_mode() {
    warn "NIGHT MODE — will scale DOWN to 0:"
    warn "  - Deployment: vllm-inference (pods)"
    warn "  - Node group:  $NODEGROUP_GPU  (GPU — most expensive)"
    warn "  - Node group:  $NODEGROUP_SYSTEM  (system nodes)"
    warn "EKS control plane keeps running (~£0.10/hr regardless)."
    echo ""
    read -rp "  Confirm night mode? (yes/no): " confirm
    [[ "$confirm" != "yes" ]] && { info "Cancelled"; return; }

    info "Pausing HPA (prevents it fighting the scale-down)..."
    kubectl patch hpa vllm-inference-hpa -n "$NAMESPACE" \
        --type=merge -p '{"spec":{"minReplicas":0}}' 2>/dev/null \
        && ok "HPA minReplicas → 0" \
        || warn "HPA patch skipped (may not exist)"

    info "Scaling vllm-inference deployment to 0..."
    kubectl scale deployment vllm-inference -n "$NAMESPACE" --replicas=0
    ok "Deployment scaled to 0 — waiting for pods to terminate..."

    # Wait until no pods remain before draining nodes.
    # Skipping this risks pods stuck in Terminating on a drained node.
    local waited=0
    while true; do
        local running
        running=$(kubectl get pods -n "$NAMESPACE" -l app=vllm-inference \
            --no-headers 2>/dev/null | wc -l | tr -d ' ')
        [[ "$running" -eq 0 ]] && break
        printf "\r  ${CYAN}→${NC}  Waiting for %s pod(s) to terminate... (%ds)" "$running" "$waited"
        sleep 5
        (( waited += 5 ))
        if [[ $waited -ge 120 ]]; then
            echo ""
            warn "Pods still running after 120s — proceeding anyway (check for stuck Terminating pods)"
            break
        fi
    done
    echo ""
    ok "All vllm pods terminated"

    info "Scaling node group $NODEGROUP_GPU to 0..."
    aws eks update-nodegroup-config \
        --region "$REGION" \
        --cluster-name "$CLUSTER_NAME" \
        --nodegroup-name "$NODEGROUP_GPU" \
        --scaling-config minSize=0,maxSize=3,desiredSize=0 >/dev/null
    ok "$NODEGROUP_GPU → 0 nodes"

    info "Scaling node group $NODEGROUP_SYSTEM to 0..."
    aws eks update-nodegroup-config \
        --region "$REGION" \
        --cluster-name "$CLUSTER_NAME" \
        --nodegroup-name "$NODEGROUP_SYSTEM" \
        --scaling-config minSize=0,maxSize=2,desiredSize=0 >/dev/null
    ok "$NODEGROUP_SYSTEM → 0 nodes"

    echo ""
    ok "Night mode active — cluster is sleeping."
    warn "Run option 17 (Wake up) before your next session."
}

# ── 17. Wake up cluster ───────────────────────────────────────────────────────
wakeup_cluster() {
    info "Waking up cluster — restoring node groups and deployment..."
    hr

    info "Scaling $NODEGROUP_SYSTEM to 1 node..."
    aws eks update-nodegroup-config \
        --region "$REGION" \
        --cluster-name "$CLUSTER_NAME" \
        --nodegroup-name "$NODEGROUP_SYSTEM" \
        --scaling-config minSize=1,maxSize=2,desiredSize=1 >/dev/null
    ok "$NODEGROUP_SYSTEM scale-out requested"

    info "Scaling $NODEGROUP_GPU to 1 node..."
    aws eks update-nodegroup-config \
        --region "$REGION" \
        --cluster-name "$CLUSTER_NAME" \
        --nodegroup-name "$NODEGROUP_GPU" \
        --scaling-config minSize=1,maxSize=3,desiredSize=1 >/dev/null
    ok "$NODEGROUP_GPU scale-out requested"

    # ── Wait for at least 1 GPU node to reach Ready ───────────────────────────
    # The deployment will stay Pending until a GPU node is schedulable.
    # Polling kubectl is sufficient — no need for AWS API calls here.
    info "Waiting for a GPU node (workload=gpu) to become Ready..."
    local waited=0
    while true; do
        local ready_gpu
        ready_gpu=$(kubectl get nodes -l workload=gpu --no-headers 2>/dev/null \
            | grep -c ' Ready ' || true)
        [[ "$ready_gpu" -ge 1 ]] && break
        printf "\r  ${CYAN}→${NC}  No Ready GPU nodes yet... (%ds elapsed)" "$waited"
        sleep 10
        (( waited += 10 ))
        if [[ $waited -ge 300 ]]; then
            echo ""
            warn "GPU node not Ready after 300s — check EC2 console / node group events"
            break
        fi
    done
    echo ""
    ok "GPU node is Ready"

    info "Restoring HPA minReplicas to 1..."
    kubectl patch hpa vllm-inference-hpa -n "$NAMESPACE" \
        --type=merge -p '{"spec":{"minReplicas":1}}' 2>/dev/null \
        && ok "HPA minReplicas → 1" \
        || warn "HPA patch skipped"

    info "Restoring vllm-inference deployment to 1 replica..."
    kubectl scale deployment vllm-inference -n "$NAMESPACE" --replicas=1
    ok "Deployment scaled to 1 — waiting for pod to become Ready..."

    # ── Wait for the vLLM pod to pass its readiness probe ─────────────────────
    # Model load takes ~90-120s on a warm node. startupProbe allows up to 300s.
    waited=0
    while true; do
        local ready_pods
        ready_pods=$(kubectl get pods -n "$NAMESPACE" -l app=vllm-inference \
            --no-headers 2>/dev/null | grep -c ' Running ' || true)
        # Check readiness condition specifically
        local ready_cond
        ready_cond=$(kubectl get pods -n "$NAMESPACE" -l app=vllm-inference \
            -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' \
            2>/dev/null || echo "False")
        [[ "$ready_cond" == "True" ]] && break
        printf "\r  ${CYAN}→${NC}  Pod not Ready yet (phase: %s)... (%ds elapsed)" \
            "$(kubectl get pods -n "$NAMESPACE" -l app=vllm-inference \
               -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo 'Pending')" \
            "$waited"
        sleep 10
        (( waited += 10 ))
        if [[ $waited -ge 360 ]]; then
            echo ""
            warn "Pod not Ready after 360s — check logs with option 2 or 3"
            break
        fi
    done
    echo ""
    ok "vLLM pod is Ready — service is live"

    echo ""
    ok "Cluster is fully awake. Total wait: ~${waited}s"
    info "Run option 12 (Health check) to verify the ALB endpoint."
}

# ── 14. Update kubeconfig ─────────────────────────────────────────────────────
update_kubeconfig() {
    info "Updating kubeconfig for cluster: $CLUSTER_NAME in $REGION"
    aws eks --region "$REGION" update-kubeconfig --name "$CLUSTER_NAME"
    ok "kubeconfig updated"
}

# ── 15. Namespace overview ────────────────────────────────────────────────────
namespace_overview() {
    info "All namespaces:"
    hr
    kubectl get namespaces
    echo ""
    info "Pod counts per namespace:"
    for ns in inference observability kube-system; do
        local count
        count=$(kubectl get pods -n "$ns" --no-headers 2>/dev/null | wc -l | tr -d ' ')
        local not_running
        not_running=$(kubectl get pods -n "$ns" --no-headers 2>/dev/null | grep -vc ' Running ' || true)
        local status_flag=""
        [[ "$not_running" -gt 0 ]] && status_flag="${YELLOW} (${not_running} not Running)${NC}"
        printf "  %-22s %s pods%b\n" "$ns" "$count" "$status_flag"
    done
}

# ── Main menu ─────────────────────────────────────────────────────────────────
main_menu() {
    while true; do
        header

        echo -e "  ${CYAN}${BOLD}Pods & Workloads${NC}"
        echo "   1)  Pod status"
        echo "   2)  vLLM logs (live tail)"
        echo "   3)  Init container logs (model-downloader)"
        echo "   4)  Model prefetch status"
        echo "   5)  Restart deployment (rolling)"
        echo "   6)  Recent warning events"
        echo ""
        echo -e "  ${CYAN}${BOLD}Scaling & Nodes${NC}"
        echo "   7)  Node status & GPU node count"
        echo "   8)  HPA status & custom metrics"
        echo "   9)  Scale deployment (manual override)"
        echo ""
        echo -e "  ${CYAN}${BOLD}GPU & Performance${NC}"
        echo "  10)  GPU & vLLM raw metrics"
        echo "  11)  KV cache & queue depth snapshot"
        echo ""
        echo -e "  ${CYAN}${BOLD}Inference${NC}"
        echo "  12)  Health check (ALB → /health)"
        echo "  13)  Send test prompt"
        echo ""
        echo -e "  ${CYAN}${BOLD}Cluster${NC}"
        echo "  14)  Update kubeconfig"
        echo "  15)  All namespaces overview"
        echo ""
        echo -e "  ${YELLOW}${BOLD}Cost Control${NC}"
        echo -e "  ${YELLOW}16)  Night mode  — scale both ASGs + deployment to 0${NC}"
        echo -e "  ${GREEN}17)  Wake up     — restore ASGs + deployment to working state${NC}"
        echo ""
        echo "   q)  Quit"
        echo ""
        read -rp "$(echo -e "  ${BOLD}Select option: ${NC}")" choice
        echo ""

        case "$choice" in
            1)  pod_status ;;
            2)  vllm_logs ;;
            3)  init_logs ;;
            4)  prefetch_status ;;
            5)  restart_deployment ;;
            6)  events ;;
            7)  node_status ;;
            8)  hpa_status ;;
            9)  scale_deployment ;;
            10) gpu_metrics ;;
            11) kv_cache_status ;;
            12) health_check ;;
            13) test_prompt ;;
            14) update_kubeconfig ;;
            15) namespace_overview ;;
            16) night_mode ;;
            17) wakeup_cluster ;;
            q|Q) echo -e "\n  ${GREEN}Goodbye!${NC}\n"; exit 0 ;;
            *) err "Invalid option: '$choice'" ;;
        esac

        pause
    done
}

# ── Entry point ───────────────────────────────────────────────────────────────
check_prereqs
main_menu
