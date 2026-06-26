"""
Adaptive coding-assistant workload for vLLM.

This file is intentionally separate from locustfile.py so existing manual
benchmarks keep their previous behavior.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import List, Tuple

from locust import HttpUser, between, events, task

from workloads import choose_request


logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int for %s=%s, using default=%d", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%s, using default=%.2f", name, raw, default)
        return default


MODEL_NAME = os.environ.get("VLLM_MODEL", "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit")
MAX_MODEL_LEN = _env_int("MAX_MODEL_LEN", 32_768)
REQUEST_TIMEOUT_SECS = _env_int("REQUEST_TIMEOUT_SECS", 900)
THINK_TIME_MIN = _env_float("THINK_TIME_MIN", 2.0)
THINK_TIME_MAX = _env_float("THINK_TIME_MAX", 8.0)


class CodingAssistantUser(HttpUser):
    wait_time = between(THINK_TIME_MIN, THINK_TIME_MAX)

    @task
    def chat_completion(self) -> None:
        request = choose_request(MAX_MODEL_LEN)
        self._post_chat_completion(request.label, request.messages, request.max_tokens)

    def _post_chat_completion(self, label: str, messages: List[dict], max_tokens: int) -> None:
        payload = {
            "model": MODEL_NAME,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "stream": True,
        }
        start = time.perf_counter()
        with self.client.post(
            "/v1/chat/completions",
            json=payload,
            name=f"/v1/chat/completions [{label}]",
            timeout=REQUEST_TIMEOUT_SECS,
            catch_response=True,
            stream=True,
        ) as response:
            if response.status_code == 200:
                try:
                    ttft_ms, completion_tokens = self._read_stream(response, start, label)
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    events.request.fire(
                        request_type="CHAT",
                        name=f"chat_e2e [{label}]",
                        response_time=elapsed_ms,
                        response_length=completion_tokens,
                        exception=None,
                    )
                    response.success()
                except Exception as exc:
                    response.failure(f"Stream parse error: {exc}")
                return

            body_excerpt = response.text[:300].replace("\n", " ") if response.text else ""
            if response.status_code == 429:
                response.failure("Rate limited (429); vLLM queue likely saturated")
            elif response.status_code == 503:
                response.failure("Service unavailable (503); vLLM may be restarting")
            else:
                response.failure(f"Unexpected status {response.status_code}: {body_excerpt}")

    def _read_stream(self, response, start: float, label: str) -> Tuple[float, int]:
        first_chunk_at = 0.0
        completion_text_chunks: List[str] = []

        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                break

            if first_chunk_at == 0.0:
                first_chunk_at = time.perf_counter()
                ttft_ms = (first_chunk_at - start) * 1000
                events.request.fire(
                    request_type="TTFT",
                    name=f"ttft [{label}]",
                    response_time=ttft_ms,
                    response_length=0,
                    exception=None,
                )

            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                completion_text_chunks.append(piece)

        full_text = "".join(completion_text_chunks)
        completion_tokens = max(0, int(len(full_text.split()) * 1.3)) if full_text else 0
        ttft_ms = (first_chunk_at - start) * 1000 if first_chunk_at else 0.0
        return ttft_ms, completion_tokens


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    logger.info(
        "Adaptive coding workload starting: host=%s model=%s max_model_len=%s users=%s think_time=%.1f-%.1fs",
        environment.host,
        MODEL_NAME,
        MAX_MODEL_LEN,
        getattr(environment.runner, "target_user_count", "?"),
        THINK_TIME_MIN,
        THINK_TIME_MAX,
    )
