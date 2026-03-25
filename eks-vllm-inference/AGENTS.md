# AI Agent Context — LLM Inference Service on EKS

This file provides structured context for AI assistants (Claude, GPT, Copilot, etc.) working in this repository.

---

## Project Summary

A **production-grade LLM inference service** serving **Mistral-7B-Instruct-v0.2** on AWS EKS using vLLM. The stack covers infrastructure-as-code (CDK), Kubernetes manifests, observability (Prometheus + Grafana + DCGM), load testing, and operational runbooks.

This is a realistic end-to-end AI Reliability Engineering POC — not a demo. Every design decision is documented. We are using NVIDIA A10g instances for model hosting.
- [https://aws.amazon.com/blogs/aws/new-ec2-instances-g5-with-nvidia-a10g-tensor-core-gpus/] 

---

## Architecture

```
Internet → ALB (eu-west-1) → EKS Cluster (llm-inference-poc)
                                 ├── inference namespace
                                 │     ├── vllm-inference Deployment  (GPU)
                                 │     ├── model-prefetch DaemonSet   (GPU)
                                 │     ├── vllm-inference-hpa
                                 │     └── vllm-pdb
                                 ├── observability namespace
                                 │     ├── kube-prometheus-stack
                                 │     ├── dcgm-exporter
                                 │     └── otel-collector
                                 └── gateway namespace (ALB Ingress)

S3 (llm-model-artifacts-<aws-account>-eu-west-1) ← Mistral-7B weights
```

**Key hardware:** g5.xlarge (NVIDIA A10G, 24 GB VRAM) · AWS eu-west-1

---

## Repository Structure

| Path | Purpose |
|------|---------|
| `cdk/` | TypeScript CDK stacks — VPC, EKS, model S3 bucket |
| `k8s/inference/` | vLLM deployment manifests (deployment, HPA, PDB, service, configmap, daemonset) |
| `k8s/observability/` | Prometheus storage class + Grafana dashboards |
| `k8s/gateway/` | ALB Ingress config |
| `k8s/namespaces.yaml` | Namespace definitions |
| `k8s/service-accounts.yaml` | IRSA service account (vllm → S3) |
| `helm/` | Helm values for kube-prometheus-stack, dcgm-exporter, otel-operator |
| `load-test/` | Locust load test scenarios + historical results |
| `scripts/` | EBS CSI driver setup, observability bootstrap |
| `CA/` | Cluster Autoscaler policy + YAML (alternative to Karpenter) |
| `mistral-7b/` | Model config/tokenizer files (not weights — served from S3) |
| `requirements.md` | Full POC brief with design rationale |
| `HowTo.md` | Quick operational commands |

---

## CDK Stacks

| Stack | File | What it creates |
|-------|------|-----------------|
| `NetworkingEksStack` | `cdk/lib/networking-eks-stack.ts` | VPC, EKS cluster, node groups, IRSA role |
| `ModelStorageStack` | `cdk/lib/model-storage-stack.ts` | S3 bucket for model weights |

**Key CDK outputs used in manifests:**
- `VllmRoleArn` → pod annotation `eks.amazonaws.com/role-arn` in `deployment.yaml`
- `ModelBucketName` → `k8s/inference/configmap.yaml` `model_bucket` key

**Deploy order:**
```bash
cd cdk
npm install
cdk deploy ModelStorageStack NetworkingEksStack
aws eks --region eu-west-1 update-kubeconfig --name llm-inference-poc
```

---

## Kubernetes Manifests — Key Files

### `k8s/inference/deployment.yaml`
The core workload. Critical settings:

| Flag | Value | Why |
|------|-------|-----|
| `--max-model-len` | 16384 | Total token budget (input + output combined); Mistral-7B native max is 32768 |
| `--max-num-seqs` | 64 | Concurrent sequences; must decrease as `max-model-len` increases (KV-cache budget) |
| `--gpu-memory-utilization` | 0.90 | 10% headroom against OOM under burst |
| `--tensor-parallel-size` | 1 | Single GPU (g5.xlarge has 1 GPU) |
| `--override-generation-config` | `{"max_tokens":2048}` | Server-side default output cap; callers can override per-request up to `max_model_len` |
| `--max-logprobs` | 5 | Caps log-probability tokens returned per response — reduces payload size |
| `startupProbe failureThreshold` | 30 × 10s = 300s | Mistral-7B loads in ~90–120s on warm node; 300s gives safe headroom |

**Context length / memory tradeoff** (g5.xlarge, 24 GB VRAM, 0.90 utilisation ≈ 21.6 GB):

| `--max-model-len` | `--max-num-seqs` | Notes |
|---|---|---|
| 4096 | 256 | Conservative default |
| 8192 | 128 | Good general balance |
| **16384** | **64** | **Current — long-doc use cases** |
| 32768 | 32 | Maximum; risky, monitor KV cache |

To change context length, update **both** `--max-model-len` and `--max-num-seqs` together.

---

## Token Budget: How Input & Output Limits Work

For any transformer model, the token budget is a **single shared pool** — not two separate limits:

```
┌─────────────────────────────────────────────────────────┐
│              max_model_len  (e.g. 16384 tokens)         │
│  ┌──────────────────────────┐  ┌───────────────────────┐│
│  │   Input (prompt tokens)  │  │  Output (new tokens)  ││
│  │  e.g. 14000 tokens       │  │  up to 2384 tokens    ││
│  └──────────────────────────┘  └───────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

**What decides each limit:**

| Limit | Decided by | Where |
|---|---|---|
| Max input + output combined | `--max-model-len` in vLLM | `deployment.yaml` — set at **model architecture + hardware** level |
| Model's native max context | Trained position embeddings | Model's `config.json` — Mistral-7B = 32768 |
| Default output cap (server) | `--override-generation-config max_tokens` | `deployment.yaml` — server default, 2048 currently |
| Output cap (per request) | `max_tokens` in request body | API caller — overrides server default, bounded by remaining budget |
| KV cache slots | `--max-num-seqs` × `max-model-len` | Determines GPU memory for concurrent sequences |

**Why you can't just raise `max_model_len` freely:** Each concurrent sequence needs `max_model_len` KV-cache slots reserved in GPU memory. On a 24 GB A10G at 0.90 utilisation (~21.6 GB), after the 14 GB model weights that leaves ~7.6 GB for KV cache — which must be split across all `max-num-seqs` sequences. Doubling context length halves the number of concurrent requests you can serve.

**Mistral-7B specifics:**
- Architecture: decoder-only transformer, sliding window attention (window = 4096)
- Native max context: 32768 tokens
- Tokeniser: SentencePiece BPE — roughly 1 token ≈ 0.75 English words
- At `max_model_len=16384`: a 12,000-token document leaves 4,384 tokens for output

---

## Alternative Models & Scaling Up

### Coding-Focused Models on the Same Hardware (g5.xlarge, 24 GB VRAM)

Drop-in replacements — change `model_path` in `configmap.yaml` and update `deployment.yaml`:

| Model | Size | VRAM (fp16) | Strengths | `--max-num-seqs` at 16k ctx |
|---|---|---|---|---|
| `Qwen/Qwen2.5-Coder-7B-Instruct` | 7B | ~14 GB | Best-in-class 7B coder; strong at Python, JS, SQL | 64 |
| `deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct` | 16B MoE | ~10 GB active | MoE architecture; 128k context native; excellent code reasoning | 96 |
| `Qwen/Qwen2.5-Coder-14B-Instruct-AWQ` | 14B (4-bit AWQ) | ~8 GB | Stronger than 7B; quantised to fit; minimal quality loss | 128 |
| `codellama/CodeLlama-34b-Instruct-hf` (AWQ) | 34B (4-bit AWQ) | ~18 GB | Large model; excellent for complex codegen; context = 16k max at this VRAM | 24 |

**Recommended upgrade path on current hardware:** `Qwen2.5-Coder-7B-Instruct` — same footprint as Mistral-7B, significantly better at coding tasks, supports 128k context natively (use `--max-model-len 32768` on g5.xlarge).

### Truly Large Coding Models (requires bigger instance)

| Model | Min instance | GPUs needed | Notes |
|---|---|---|---|
| `Qwen/Qwen2.5-Coder-32B-Instruct` | g5.12xlarge | 4× A10G (96 GB) | SOTA open coding model at 32B; set `--tensor-parallel-size 4` |
| `deepseek-ai/DeepSeek-Coder-V2-Instruct` | p4d.24xlarge | 8× A100 (320 GB) | 236B MoE; production-grade; expensive |
| `codellama/CodeLlama-70b-Instruct-hf` (AWQ) | g5.12xlarge | 4× A10G | 70B 4-bit; ~35 GB; strong but not SOTA |

### To deploy a different model — what to change

1. **Upload weights to S3:** `aws s3 sync <local_model_dir>/ s3://<bucket>/models/<model-name>/`
2. **`k8s/inference/configmap.yaml`:** Update `model_path` and `model_name`
3. **`k8s/inference/model-prefetch-daemonset.yaml`:** Update the S3 path and `TARGET` directory
4. **`k8s/inference/deployment.yaml`:**
   - Update `hostPath` volume to `/mnt/models/<model-name>`
   - Update `--served-model-name`
   - Adjust `--max-model-len` / `--max-num-seqs` for the new model's context size
   - Add `--tensor-parallel-size N` if using multi-GPU instance
5. **`cdk/lib/eks-stack.ts`:** Change instance type if upgrading hardware (e.g. `g5.12xlarge` for 4-GPU)

### `k8s/inference/model-prefetch-daemonset.yaml`
Runs `aws s3 sync` on every GPU node at startup. Writes a sentinel file (`.model_ready`) so the init container in the Deployment can skip S3 download on warm nodes. This reduces pod cold-start from ~5 min to ~90–120s.

### `k8s/inference/hpa.yaml`
Scales on two custom Prometheus metrics:
- `vllm_num_requests_waiting > 5` (queue depth — primary)
- `vllm_gpu_cache_usage_perc > 80` (KV cache pressure — leading OOM indicator)

Requires `prometheus-adapter` configured with rules from `helm/prometheus-adapter-values.yaml`.

### `k8s/inference/configmap.yaml`
Update `model_bucket` to match CDK output `ModelStorageStack.ModelBucketName` before deploying.

---

## Observability

**Metrics endpoint:** `http://<pod>:8000/metrics` (Prometheus scrape; annotated in deployment)

| Metric | SLI purpose |
|--------|-------------|
| `vllm:time_to_first_token_seconds` | Primary user-facing SLI (TTFT) |
| `vllm:e2e_request_latency_seconds` | Full request latency |
| `vllm:num_requests_waiting` | Queue depth — saturation signal |
| `vllm:gpu_cache_usage_perc` | KV cache pressure — pre-OOM signal |
| `dcgm_gpu_utilization` | GPU compute utilisation |
| `dcgm_fb_used` | GPU memory used |

**Grafana dashboards** (imported via `k8s/observability/dashboards/`):
- `inference-health-dashboard.yaml` — TTFT p50/p95/p99, error rate, queue depth
- `gpu-node-health-dashboard.yaml` — GPU utilisation, memory, KV cache
- `capacity-planning-dashboard.yaml` — scale-out events, cost per token estimate

---

## Load Testing

```bash
cd load-test
uv run --with locust locust -f locustfile.py \
  --host http://<ALB_URL> \
  --users 50 --spawn-rate 5
```

Three scenarios (results in `load-test/results_/`):
- **baseline** — 5 concurrent users, 10 min steady state
- **ramp** — 5 → 50 users over 20 min (finds saturation point)
- **spike** — 100 users sudden burst, 5 min (tests recovery)

**Finding from previous runs:** TTFT p99 degrades past acceptable threshold at ~35 concurrent users on a single g5.xlarge replica. HPA scale-out triggers at queue depth > 5.

---

## IRSA & IAM

The `vllm` ServiceAccount is annotated with `NetworkingEksStack-InferenceClusterRole*` ARN. This role has `s3:GetObject` / `s3:ListBucket` on the model bucket — no credentials in the pod.

If the init container fails with `AccessDenied`:
1. Verify the annotation in `deployment.yaml` pod template matches the CDK output `VllmRoleArn`.
2. Verify `k8s/service-accounts.yaml` annotation is applied: `kubectl get sa vllm -n inference -o yaml`.
3. Check OIDC provider: `aws eks describe-cluster --name llm-inference-poc --query cluster.identity`.

---

## Common Operations

```bash
# Access cluster
aws eks --region eu-west-1 update-kubeconfig --name llm-inference-poc

# Deploy / update inference stack
kubectl apply -f k8s/namespaces.yaml
kubectl apply -f k8s/service-accounts.yaml
kubectl apply -f k8s/inference/

# Check vLLM pod status
kubectl get pods -n inference
kubectl logs -n inference deploy/vllm-inference -c model-downloader  # init
kubectl logs -n inference deploy/vllm-inference -c vllm              # main

# Check model prefetch on node
kubectl get pods -n inference -l app=model-prefetch
kubectl exec -n inference <prefetch-pod> -- ls /mnt/models/mistral-7b-instruct-v0.2/

# Test inference
curl http://<ALB_URL>/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"mistral-7b","messages":[{"role":"user","content":"Hello"}],"max_tokens":200}'

# HPA status
kubectl get hpa -n inference
kubectl describe hpa vllm-inference-hpa -n inference

# GPU metrics
kubectl exec -n inference <vllm-pod> -- curl -s localhost:8000/metrics | grep vllm_gpu
```

---

## Known Failure Modes

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Init container stuck downloading | S3 IRSA misconfiguration | Check pod annotation vs CDK output |
| Pod stuck in `ContainerCreating` | GPU taint not tolerated / no GPU node available | Check node group, tolerations in deployment |
| Startup probe fails, pod restarts | Model load > 300s (cold node + slow S3) | Increase `failureThreshold` or ensure prefetch DaemonSet ran first |
| TTFT spikes under load | KV cache pressure (`vllm_gpu_cache_usage_perc > 80`) | HPA should trigger; reduce `--max-num-seqs` or `--max-model-len` |
| HPA not scaling | `prometheus-adapter` not configured | Check `kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1` |
| OOM kill on vLLM container | KV cache exceeded memory limit | Reduce `--max-model-len` or `--gpu-memory-utilization` |

---

## Design Decisions Log

- **Spot → On-Demand** node capacity type: changed to On-Demand for POC stability (Spot can be re-enabled by changing `capacityType` in `eks-stack.ts`).
- **hostPath for model cache**: model weights on node's 200 GB EBS root volume, not a PVC, to avoid EBS mount time on scale-out.
- **Sentinel file pattern**: `.model_ready` written only after complete S3 sync; prevents partial downloads from poisoning the cache.
- **`--gpu-memory-utilization 0.90`**: 10% headroom against GPU OOM under burst. Deliberate headroom, not waste.
- **PDB `minAvailable: 1`**: prevents node drains from taking entire inference capacity offline during Spot reclamation or upgrades.
- **`maxUnavailable: 0` in rolling update**: ensures at least one replica always handles traffic during a rollout.
- **`--override-generation-config max_tokens: 2048`**: server-side output default prevents runaway generations consuming KV cache slots indefinitely; callers can still override per-request.
- **`--max-logprobs 5`**: caps log-probability payload size — reduces response bytes for high-throughput workloads.
