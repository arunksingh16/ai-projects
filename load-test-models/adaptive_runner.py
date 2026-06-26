#!/usr/bin/env python3
"""
Adaptive vLLM benchmark runner.

Runs quick vLLM Docker trials for multiple max-model-len and KV cache dtype
settings, drives a human-paced Locust coding-assistant workload, scrapes vLLM
/metrics directly, samples GPU state with nvidia-smi when available, and writes
CSV/HTML reports.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"
INTERESTING_VLLM_METRICS = {
    "vllm:num_requests_running",
    "vllm:num_requests_waiting",
    "vllm:gpu_cache_usage_perc",
    "vllm:cpu_cache_usage_perc",
    "vllm:prefix_cache_hit_rate",
}


@dataclass
class TrialConfig:
    context: int
    kv_dtype: str

    @property
    def label(self) -> str:
        return f"{self.kv_dtype}-{self.context}"


@dataclass
class TrialResult:
    config: TrialConfig
    status: str
    verdict: str
    trial_dir: Path
    startup_seconds: Optional[float] = None
    p95_ttft_ms: Optional[float] = None
    p99_ttft_ms: Optional[float] = None
    p95_e2e_ms: Optional[float] = None
    p99_e2e_ms: Optional[float] = None
    requests: int = 0
    failures: int = 0
    failure_pct: float = 0.0
    max_waiting_requests: Optional[float] = None
    max_running_requests: Optional[float] = None
    max_gpu_cache_usage_pct: Optional[float] = None
    max_gpu_memory_used_mb: Optional[float] = None
    max_gpu_util_pct: Optional[float] = None
    error: str = ""
    docker_logs_path: Optional[Path] = None
    locust_returncode: Optional[int] = None
    locust_stats_path: Optional[Path] = None


class SampleCollector:
    def __init__(self, base_url: str, output_dir: Path, interval_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.output_dir = output_dir
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.vllm_samples_path = output_dir / "vllm_metrics_samples.csv"
        self.gpu_samples_path = output_dir / "gpu_samples.csv"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="sample-collector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_seconds + 5)

    def _run(self) -> None:
        with self.vllm_samples_path.open("w", newline="") as vllm_file, self.gpu_samples_path.open(
            "w", newline=""
        ) as gpu_file:
            vllm_writer = csv.DictWriter(
                vllm_file,
                fieldnames=[
                    "timestamp",
                    "metric",
                    "value",
                ],
            )
            gpu_writer = csv.DictWriter(
                gpu_file,
                fieldnames=[
                    "timestamp",
                    "gpu_index",
                    "utilization_gpu_pct",
                    "memory_used_mb",
                    "memory_total_mb",
                ],
            )
            vllm_writer.writeheader()
            gpu_writer.writeheader()
            while not self._stop.is_set():
                ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                for name, value in scrape_vllm_metrics(f"{self.base_url}/metrics").items():
                    vllm_writer.writerow({"timestamp": ts, "metric": name, "value": value})
                for row in sample_gpus():
                    row["timestamp"] = ts
                    gpu_writer.writerow(row)
                vllm_file.flush()
                gpu_file.flush()
                self._stop.wait(self.interval_seconds)


def parse_int_list(raw: str) -> List[int]:
    values = []
    for part in raw.split(","):
        part = part.strip().lower()
        if not part:
            continue
        multiplier = 1
        if part.endswith("k"):
            multiplier = 1024
            part = part[:-1]
        values.append(int(part) * multiplier)
    return values


def parse_str_list(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def run_command(
    command: List[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    stdout_path: Optional[Path] = None,
    stderr_path: Optional[Path] = None,
    check: bool = False,
) -> subprocess.CompletedProcess:
    shared_handle = None
    if stdout_path and stderr_path and stdout_path == stderr_path:
        shared_handle = stdout_path.open("w")
        stdout_handle = shared_handle
        stderr_handle = shared_handle
    else:
        stdout_handle = stdout_path.open("w") if stdout_path else subprocess.PIPE
        stderr_handle = stderr_path.open("w") if stderr_path else subprocess.PIPE
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=check,
        )
    finally:
        if shared_handle:
            shared_handle.close()
        elif stdout_path:
            stdout_handle.close()
        if stderr_path and stderr_handle is not stdout_handle:
            stderr_handle.close()
    return result


def http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception:
        return 0, ""


def http_post_json(url: str, payload: dict, timeout: float = 30.0) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception:
        return 0, ""


def docker_container_running(name: str) -> bool:
    result = run_command(["docker", "inspect", "-f", "{{.State.Running}}", name])
    return result.returncode == 0 and (result.stdout or "").strip() == "true"


def docker_container_status(name: str) -> str:
    result = run_command(["docker", "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", name])
    if result.returncode != 0:
        return "missing"
    return (result.stdout or "").strip()


def write_docker_logs(container_name: str, output_path: Path) -> None:
    run_command(["docker", "logs", "--tail", "400", container_name], stdout_path=output_path, stderr_path=output_path)


def build_docker_command(args: argparse.Namespace, config: TrialConfig) -> List[str]:
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        args.container_name,
        "--gpus",
        args.gpus,
        "--ipc",
        "host",
        "--shm-size",
        args.shm_size,
    ]
    if args.env_file:
        command.extend(["--env-file", args.env_file])
    command.extend(
        [
            "-p",
            f"{args.host_bind}:{args.host_port}:8000",
            "-v",
            f"{args.hf_cache_dir}:/root/.cache/huggingface",
            "-v",
            f"{args.container_results_dir}:/bench-results",
            args.image,
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--model",
            args.model,
            "--served-model-name",
            args.model,
            "--tensor-parallel-size",
            str(args.tensor_parallel_size),
            "--gpu-memory-utilization",
            str(args.gpu_memory_utilization),
            "--max-model-len",
            str(config.context),
            "--dtype",
            args.dtype,
            "--kv-cache-dtype",
            config.kv_dtype,
            "--max-num-batched-tokens",
            str(args.max_num_batched_tokens),
            "--max-num-seqs",
            str(args.max_num_seqs),
            "--enable-prefix-caching",
            "--enable-auto-tool-choice",
            "--tool-call-parser",
            args.tool_call_parser,
            "--reasoning-parser",
            args.reasoning_parser,
        ]
    )
    if args.enable_chunked_prefill:
        command.append("--enable-chunked-prefill")
    for extra_arg in args.vllm_arg:
        command.append(extra_arg)
    return command


def wait_for_vllm_ready(args: argparse.Namespace, trial_dir: Path) -> tuple[str, Optional[float], str]:
    start = time.monotonic()
    deadline = start + args.startup_timeout_seconds
    health_url = f"{args.base_url}/health"
    models_url = f"{args.base_url}/v1/models"
    last_status = ""

    while time.monotonic() < deadline:
        if not docker_container_running(args.container_name):
            status = docker_container_status(args.container_name)
            logs_path = trial_dir / "docker-startup-failed.log"
            write_docker_logs(args.container_name, logs_path)
            return "startup_failed", None, f"Container stopped before health check passed: {status}"

        status_code, body = http_get(health_url, timeout=5)
        last_status = f"health={status_code}"
        if status_code == 200:
            model_code, model_body = http_get(models_url, timeout=10)
            if model_code == 200:
                startup_seconds = time.monotonic() - start
                (trial_dir / "models.json").write_text(model_body)
                return "ready", startup_seconds, ""
            last_status = f"models={model_code}"

        time.sleep(args.health_poll_seconds)

    logs_path = trial_dir / "docker-startup-timeout.log"
    write_docker_logs(args.container_name, logs_path)
    return "startup_timeout", None, f"Timed out waiting for vLLM readiness after {args.startup_timeout_seconds}s ({last_status})"


def warmup(args: argparse.Namespace, config: TrialConfig, trial_dir: Path) -> tuple[bool, str]:
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": "You are a concise coding assistant."},
            {"role": "user", "content": "Reply with the word ready."},
        ],
        "max_tokens": 8,
        "temperature": 0.0,
    }
    for attempt in range(1, args.warmup_attempts + 1):
        status, body = http_post_json(f"{args.base_url}/v1/chat/completions", payload, timeout=60)
        if status == 200:
            (trial_dir / "warmup-response.json").write_text(body)
            return True, ""
        time.sleep(min(10, attempt * 2))
    return False, f"Warmup chat request failed after {args.warmup_attempts} attempts"


def run_locust(args: argparse.Namespace, config: TrialConfig, trial_dir: Path) -> int:
    env = os.environ.copy()
    env.update(
        {
            "VLLM_MODEL": args.model,
            "MAX_MODEL_LEN": str(config.context),
            "THINK_TIME_MIN": str(args.think_time_min),
            "THINK_TIME_MAX": str(args.think_time_max),
            "REQUEST_TIMEOUT_SECS": str(args.request_timeout_seconds),
        }
    )
    csv_prefix = trial_dir / "locust"
    command = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(SCRIPT_DIR / "adaptive_locustfile.py"),
        "--host",
        args.base_url,
        "--users",
        str(args.users),
        "--spawn-rate",
        str(args.spawn_rate),
        "--run-time",
        args.run_time,
        "--headless",
        "--csv",
        str(csv_prefix),
        "--html",
        str(trial_dir / "locust.html"),
    ]
    result = run_command(
        command,
        cwd=SCRIPT_DIR,
        env=env,
        stdout_path=trial_dir / "locust.stdout.log",
        stderr_path=trial_dir / "locust.stderr.log",
    )
    return result.returncode


def metric_name(raw_name: str) -> str:
    return raw_name.split("{", 1)[0]


def scrape_vllm_metrics(metrics_url: str) -> Dict[str, float]:
    status, body = http_get(metrics_url, timeout=5)
    if status != 200:
        return {}
    values: Dict[str, float] = {}
    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        name = metric_name(parts[0])
        if name not in INTERESTING_VLLM_METRICS:
            continue
        try:
            value = float(parts[1])
        except ValueError:
            continue
        values[name] = max(values.get(name, value), value)
    return values


def sample_gpus() -> List[dict]:
    if not shutil.which("nvidia-smi"):
        return []
    command = [
        "nvidia-smi",
        "--query-gpu=index,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    result = run_command(command)
    if result.returncode != 0:
        return []
    rows = []
    for line in (result.stdout or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 4:
            continue
        rows.append(
            {
                "gpu_index": parts[0],
                "utilization_gpu_pct": parts[1],
                "memory_used_mb": parts[2],
                "memory_total_mb": parts[3],
            }
        )
    return rows


def parse_float(value: str) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_locust_stats(stats_path: Path) -> dict:
    if not stats_path.exists():
        return {}
    summary = {
        "requests": 0,
        "failures": 0,
        "failure_pct": 0.0,
        "p95_ttft_ms": None,
        "p99_ttft_ms": None,
        "p95_e2e_ms": None,
        "p99_e2e_ms": None,
    }
    ttft_rows = []
    chat_rows = []
    http_rows = []
    with stats_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            row_type = row.get("Type", "")
            name = row.get("Name", "")
            if row_type == "TTFT":
                ttft_rows.append(row)
            elif row_type == "CHAT" and "chat" in name.lower():
                chat_rows.append(row)
            elif row_type == "POST" and "/v1/chat/completions" in name:
                http_rows.append(row)

    for row in http_rows:
        summary["requests"] += int(float(row.get("Request Count") or 0))
        summary["failures"] += int(float(row.get("Failure Count") or 0))

    if summary["requests"] > 0:
        summary["failure_pct"] = (summary["failures"] / summary["requests"]) * 100

    summary["p95_ttft_ms"] = max_percentile(ttft_rows, "95%")
    summary["p99_ttft_ms"] = max_percentile(ttft_rows, "99%")
    summary["p95_e2e_ms"] = max_percentile(chat_rows or http_rows, "95%")
    summary["p99_e2e_ms"] = max_percentile(chat_rows or http_rows, "99%")
    return summary


def max_percentile(rows: Iterable[dict], column: str) -> Optional[float]:
    values = []
    for row in rows:
        value = parse_float(row.get(column, ""))
        if value is not None:
            values.append(value)
    return max(values) if values else None


def summarize_samples(result: TrialResult) -> None:
    metrics_path = result.trial_dir / "vllm_metrics_samples.csv"
    if metrics_path.exists():
        by_metric: Dict[str, float] = {}
        with metrics_path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                value = parse_float(row.get("value", ""))
                if value is None:
                    continue
                metric = row.get("metric", "")
                by_metric[metric] = max(by_metric.get(metric, value), value)
        result.max_waiting_requests = by_metric.get("vllm:num_requests_waiting")
        result.max_running_requests = by_metric.get("vllm:num_requests_running")
        cache_value = by_metric.get("vllm:gpu_cache_usage_perc")
        if cache_value is not None:
            result.max_gpu_cache_usage_pct = cache_value * 100 if cache_value <= 1.0 else cache_value

    gpu_path = result.trial_dir / "gpu_samples.csv"
    if gpu_path.exists():
        max_mem = []
        max_util = []
        with gpu_path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                mem = parse_float(row.get("memory_used_mb", ""))
                util = parse_float(row.get("utilization_gpu_pct", ""))
                if mem is not None:
                    max_mem.append(mem)
                if util is not None:
                    max_util.append(util)
        if max_mem:
            result.max_gpu_memory_used_mb = max(max_mem)
        if max_util:
            result.max_gpu_util_pct = max(max_util)


def classify_error_from_logs(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    text = log_path.read_text(errors="replace")[-20_000:].lower()
    if "out of memory" in text or "cuda error: out of memory" in text:
        return "OOM or CUDA memory failure detected in docker logs"
    if "maximum context length" in text or "max seq len" in text:
        return "Context length or sequence length failure detected in docker logs"
    return ""


def verdict_for(args: argparse.Namespace, result: TrialResult) -> str:
    if result.status != "completed":
        return "FAIL"
    if result.locust_returncode not in (0, None):
        return "FAIL"
    if result.p95_ttft_ms is None:
        return "FAIL"
    if result.p95_ttft_ms > args.ttft_p95_slo_ms:
        return "FAIL"
    if result.failure_pct > args.max_failure_pct:
        return "FAIL"
    return "PASS"


def stop_container(container_name: str) -> None:
    run_command(["docker", "rm", "-f", container_name])


def run_trial(args: argparse.Namespace, config: TrialConfig, run_dir: Path) -> TrialResult:
    trial_dir = run_dir / config.label
    trial_dir.mkdir(parents=True, exist_ok=True)
    result = TrialResult(config=config, status="created", verdict="FAIL", trial_dir=trial_dir)

    config_json = {
        "context": config.context,
        "kv_dtype": config.kv_dtype,
        "model": args.model,
        "users": args.users,
        "run_time": args.run_time,
        "ttft_p95_slo_ms": args.ttft_p95_slo_ms,
    }
    (trial_dir / "config.json").write_text(json.dumps(config_json, indent=2) + "\n")

    docker_command = build_docker_command(args, config)
    (trial_dir / "docker-command.txt").write_text(" ".join(docker_command) + "\n")
    if args.dry_run:
        result.status = "dry_run"
        result.verdict = "DRY_RUN"
        return result

    stop_container(args.container_name)
    docker_result = run_command(
        docker_command,
        stdout_path=trial_dir / "docker-run.stdout.log",
        stderr_path=trial_dir / "docker-run.stderr.log",
    )
    if docker_result.returncode != 0:
        result.status = "docker_run_failed"
        result.error = "docker run failed"
        result.docker_logs_path = trial_dir / "docker-run.stderr.log"
        return result

    ready_status, startup_seconds, ready_error = wait_for_vllm_ready(args, trial_dir)
    result.startup_seconds = startup_seconds
    if ready_status != "ready":
        result.status = ready_status
        result.error = ready_error
        logs_path = trial_dir / "docker.log"
        write_docker_logs(args.container_name, logs_path)
        result.docker_logs_path = logs_path
        classified = classify_error_from_logs(logs_path)
        if classified:
            result.error = f"{result.error}; {classified}"
        stop_container(args.container_name)
        return result

    warmup_ok, warmup_error = warmup(args, config, trial_dir)
    if not warmup_ok:
        result.status = "warmup_failed"
        result.error = warmup_error
        logs_path = trial_dir / "docker.log"
        write_docker_logs(args.container_name, logs_path)
        result.docker_logs_path = logs_path
        stop_container(args.container_name)
        return result

    collector = SampleCollector(args.base_url, trial_dir, args.metrics_interval_seconds)
    collector.start()
    try:
        result.locust_returncode = run_locust(args, config, trial_dir)
    finally:
        collector.stop()

    logs_path = trial_dir / "docker.log"
    write_docker_logs(args.container_name, logs_path)
    result.docker_logs_path = logs_path
    stop_container(args.container_name)

    stats_path = trial_dir / "locust_stats.csv"
    result.locust_stats_path = stats_path
    locust_summary = parse_locust_stats(stats_path)
    result.requests = int(locust_summary.get("requests") or 0)
    result.failures = int(locust_summary.get("failures") or 0)
    result.failure_pct = float(locust_summary.get("failure_pct") or 0.0)
    result.p95_ttft_ms = locust_summary.get("p95_ttft_ms")
    result.p99_ttft_ms = locust_summary.get("p99_ttft_ms")
    result.p95_e2e_ms = locust_summary.get("p95_e2e_ms")
    result.p99_e2e_ms = locust_summary.get("p99_e2e_ms")
    summarize_samples(result)
    result.status = "completed"
    result.error = classify_error_from_logs(logs_path)
    result.verdict = verdict_for(args, result)
    return result


def write_summary_csv(results: List[TrialResult], output_path: Path) -> None:
    fieldnames = [
        "kv_dtype",
        "context",
        "status",
        "verdict",
        "startup_seconds",
        "requests",
        "failures",
        "failure_pct",
        "p95_ttft_ms",
        "p99_ttft_ms",
        "p95_e2e_ms",
        "p99_e2e_ms",
        "max_waiting_requests",
        "max_running_requests",
        "max_gpu_cache_usage_pct",
        "max_gpu_memory_used_mb",
        "max_gpu_util_pct",
        "error",
        "trial_dir",
    ]
    with output_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "kv_dtype": result.config.kv_dtype,
                    "context": result.config.context,
                    "status": result.status,
                    "verdict": result.verdict,
                    "startup_seconds": fmt(result.startup_seconds),
                    "requests": result.requests,
                    "failures": result.failures,
                    "failure_pct": fmt(result.failure_pct),
                    "p95_ttft_ms": fmt(result.p95_ttft_ms),
                    "p99_ttft_ms": fmt(result.p99_ttft_ms),
                    "p95_e2e_ms": fmt(result.p95_e2e_ms),
                    "p99_e2e_ms": fmt(result.p99_e2e_ms),
                    "max_waiting_requests": fmt(result.max_waiting_requests),
                    "max_running_requests": fmt(result.max_running_requests),
                    "max_gpu_cache_usage_pct": fmt(result.max_gpu_cache_usage_pct),
                    "max_gpu_memory_used_mb": fmt(result.max_gpu_memory_used_mb),
                    "max_gpu_util_pct": fmt(result.max_gpu_util_pct),
                    "error": result.error,
                    "trial_dir": str(result.trial_dir),
                }
            )


def fmt(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def write_report_html(results: List[TrialResult], output_path: Path, args: argparse.Namespace) -> None:
    best_by_kv = {}
    for result in results:
        if result.verdict == "PASS":
            current = best_by_kv.get(result.config.kv_dtype)
            if current is None or result.config.context > current.config.context:
                best_by_kv[result.config.kv_dtype] = result

    rows = []
    for result in results:
        rows.append(
            "<tr>"
            f"<td>{html.escape(result.config.kv_dtype)}</td>"
            f"<td>{result.config.context}</td>"
            f"<td>{html.escape(result.status)}</td>"
            f"<td class='{result.verdict.lower()}'>{html.escape(result.verdict)}</td>"
            f"<td>{fmt(result.startup_seconds)}</td>"
            f"<td>{fmt(result.p95_ttft_ms)}</td>"
            f"<td>{fmt(result.p99_ttft_ms)}</td>"
            f"<td>{fmt(result.failure_pct)}</td>"
            f"<td>{fmt(result.max_waiting_requests)}</td>"
            f"<td>{fmt(result.max_gpu_cache_usage_pct)}</td>"
            f"<td>{html.escape(result.error)}</td>"
            "</tr>"
        )

    winners = []
    for kv_dtype, result in sorted(best_by_kv.items()):
        winners.append(
            f"<li>{html.escape(kv_dtype)}: {result.config.context} tokens "
            f"(p95 TTFT {fmt(result.p95_ttft_ms)} ms, p99 {fmt(result.p99_ttft_ms)} ms)</li>"
        )
    if not winners:
        winners.append("<li>No passing configuration found.</li>")

    output_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Adaptive vLLM Benchmark Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #17202a; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
    th, td {{ border: 1px solid #d7dde5; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f6f9; }}
    .pass {{ color: #116329; font-weight: 700; }}
    .fail {{ color: #a40e26; font-weight: 700; }}
    .dry_run {{ color: #7a4d00; font-weight: 700; }}
    code {{ background: #f3f6f9; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Adaptive vLLM Benchmark Report</h1>
  <p>Model: <code>{html.escape(args.model)}</code></p>
  <p>Target: {args.users} human-paced developers, p95 TTFT &lt;= {args.ttft_p95_slo_ms:.0f} ms. p99 TTFT is reported, not gated by default.</p>
  <h2>Largest Passing Context</h2>
  <ul>{''.join(winners)}</ul>
  <h2>Trials</h2>
  <table>
    <thead>
      <tr>
        <th>KV dtype</th><th>Context</th><th>Status</th><th>Verdict</th><th>Startup s</th>
        <th>p95 TTFT ms</th><th>p99 TTFT ms</th><th>Failure %</th>
        <th>Max waiting</th><th>Max GPU cache %</th><th>Error</th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>
""",
        encoding="utf-8",
    )


def validate_args(args: argparse.Namespace) -> None:
    if args.env_file and not Path(args.env_file).exists():
        raise SystemExit(f"Env file not found: {args.env_file}. Pass --env-file '' if this host does not need one.")
    Path(args.container_results_dir).mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adaptive vLLM context benchmark runner")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--image", default=os.environ.get("QUICK_IMAGE", "vllm/vllm-openai:latest"))
    parser.add_argument("--contexts", default="16k,32k,64k,96k,128k,160k,192k,256k")
    parser.add_argument("--kv-dtypes", default="auto,fp8")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--spawn-rate", type=float, default=1.0)
    parser.add_argument("--run-time", default="10m")
    parser.add_argument("--ttft-p95-slo-ms", type=float, default=2000.0)
    parser.add_argument("--max-failure-pct", type=float, default=0.5)
    parser.add_argument("--think-time-min", type=float, default=2.0)
    parser.add_argument("--think-time-max", type=float, default=8.0)
    parser.add_argument("--request-timeout-seconds", type=int, default=900)
    parser.add_argument("--startup-timeout-seconds", type=int, default=1800)
    parser.add_argument("--health-poll-seconds", type=float, default=5.0)
    parser.add_argument("--warmup-attempts", type=int, default=5)
    parser.add_argument("--metrics-interval-seconds", type=float, default=30.0)
    parser.add_argument("--continue-after-fail", action="store_true")
    parser.add_argument("--dry-run", action="store_true")

    parser.add_argument("--container-name", default="vllm-quick")
    parser.add_argument("--host-bind", default="127.0.0.1")
    parser.add_argument("--host-port", type=int, default=8001)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--gpus", default="all")
    parser.add_argument("--shm-size", default="16g")
    parser.add_argument("--env-file", default="/etc/vllm/vllm.env")
    parser.add_argument("--hf-cache-dir", default="/mnt/models/huggingface")
    parser.add_argument("--container-results-dir", default="/mnt/models/vllm-bench-results")

    parser.add_argument("--tensor-parallel-size", type=int, default=4)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.95)
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--max-num-batched-tokens", type=int, default=16384)
    parser.add_argument("--max-num-seqs", type=int, default=8)
    parser.add_argument("--tool-call-parser", default="qwen3_coder")
    parser.add_argument("--reasoning-parser", default="qwen3")
    parser.add_argument("--enable-chunked-prefill", action="store_true")
    parser.add_argument("--vllm-arg", action="append", default=[], help="Extra vLLM server arg; repeat for multiple args")

    parser.add_argument("--output-root", default=str(SCRIPT_DIR / "benchmark"))
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validate_args(args)

    contexts = parse_int_list(args.contexts)
    kv_dtypes = parse_str_list(args.kv_dtypes)
    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "runner-config.json").write_text(json.dumps(vars(args), indent=2) + "\n")

    results: List[TrialResult] = []
    for kv_dtype in kv_dtypes:
        for context in contexts:
            config = TrialConfig(context=context, kv_dtype=kv_dtype)
            print(f"=== Trial {config.label}: starting ===", flush=True)
            result = run_trial(args, config, run_dir)
            results.append(result)
            print(
                f"=== Trial {config.label}: {result.verdict} "
                f"p95_ttft={fmt(result.p95_ttft_ms)} p99_ttft={fmt(result.p99_ttft_ms)} "
                f"status={result.status} ===",
                flush=True,
            )
            write_summary_csv(results, run_dir / "summary.csv")
            write_report_html(results, run_dir / "report.html", args)
            if result.verdict != "PASS" and not args.continue_after_fail and not args.dry_run:
                print(f"Stopping {kv_dtype} search after first failing context.", flush=True)
                break

    write_summary_csv(results, run_dir / "summary.csv")
    write_report_html(results, run_dir / "report.html", args)
    print(f"Report: {run_dir / 'report.html'}", flush=True)
    print(f"Summary: {run_dir / 'summary.csv'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
