"""
Prompt builders for adaptive vLLM load testing.

The goal is not to create semantically perfect repository content. The goal is
to produce stable-prefix and long-context shapes that behave like coding
assistant traffic while staying deterministic enough for comparable trials.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List


TOKEN_TO_WORD_RATIO = 0.30


@dataclass(frozen=True)
class WorkloadRequest:
    label: str
    messages: List[dict]
    max_tokens: int


def words_for_tokens(tokens: int) -> int:
    return max(32, int(tokens * TOKEN_TO_WORD_RATIO))


def tokenish_block(prefix: str, target_tokens: int, modulo: int = 4096) -> str:
    words = words_for_tokens(target_tokens)
    return " ".join(f"{prefix}_{i % modulo}" for i in range(words))


def stable_repository_context(repo_id: int, target_tokens: int) -> str:
    words = words_for_tokens(target_tokens)
    sections = [
        "Repository: inference-platform",
        "Service: coding-assistant-gateway",
        "Stack: FastAPI, TypeScript client, vLLM OpenAI-compatible backend, EKS, ALB",
        "Task: answer questions using the repository context below.",
    ]
    body = " ".join(f"repo{repo_id}_file_{i % 128}_symbol_{i % 2048}" for i in range(words))
    return "\n".join(sections) + "\n\n" + body


REPO_CONTEXT_POOL = [
    stable_repository_context(repo_id=1, target_tokens=50_000),
    stable_repository_context(repo_id=2, target_tokens=40_000),
    stable_repository_context(repo_id=3, target_tokens=30_000),
]


AUTOCOMPLETE_PREFIXES = [
    "Complete the Python function below. Return only the code continuation.",
    "Complete the TypeScript method below. Return only the next lines.",
    "Finish this Terraform module snippet. Return only valid HCL.",
]


REFACTOR_TASKS = [
    "Refactor this service to separate request validation, scheduling, and metrics emission. Explain key code changes.",
    "Find concurrency bugs and propose a patch plan with specific files and tests.",
    "Rewrite this subsystem to reduce tail latency while preserving the public API.",
]


def _cap_prompt_tokens(max_model_len: int, desired_tokens: int, max_tokens: int) -> int:
    return max(512, min(desired_tokens, max_model_len - max_tokens - 512))


def repository_chat(max_model_len: int) -> WorkloadRequest:
    max_tokens = random.choice([256, 384, 512])
    desired_context = random.choice([20_000, 32_000, 50_000])
    prompt_tokens = _cap_prompt_tokens(max_model_len, desired_context, max_tokens)
    repo_context = random.choice(REPO_CONTEXT_POOL)
    repo_context = repo_context[: max(2_000, words_for_tokens(prompt_tokens) * 14)]
    question = random.choice(
        [
            "Where is request queue pressure most likely introduced, and what should I inspect first?",
            "Summarize the deployment path for vLLM and identify risky configuration defaults.",
            "Which tests should I add before changing the scheduler-facing code?",
            "Explain how to make this repository safer for a long-context coding assistant workflow.",
        ]
    )
    return WorkloadRequest(
        label="repo_chat",
        max_tokens=max_tokens,
        messages=[
            {
                "role": "system",
                "content": "You are a senior coding assistant. Use the repository context and be concise.",
            },
            {
                "role": "user",
                "content": f"{repo_context}\n\nQuestion: {question}",
            },
        ],
    )


def autocomplete(max_model_len: int) -> WorkloadRequest:
    max_tokens = random.choice([32, 48, 64])
    desired_context = random.choice([2_048, 4_096, 8_192])
    prompt_tokens = _cap_prompt_tokens(max_model_len, desired_context, max_tokens)
    code_context = tokenish_block("code_symbol", prompt_tokens, modulo=1024)
    return WorkloadRequest(
        label="autocomplete",
        max_tokens=max_tokens,
        messages=[
            {
                "role": "system",
                "content": "You are an autocomplete engine. Return only the completion.",
            },
            {
                "role": "user",
                "content": f"{random.choice(AUTOCOMPLETE_PREFIXES)}\n\n{code_context}\n\nContinuation:",
            },
        ],
    )


def large_refactor(max_model_len: int) -> WorkloadRequest:
    max_tokens = random.choice([512, 768, 1024])
    desired_context = random.choice([64_000, 96_000, 128_000])
    prompt_tokens = _cap_prompt_tokens(max_model_len, desired_context, max_tokens)
    context = tokenish_block("large_refactor_context", prompt_tokens, modulo=8192)
    return WorkloadRequest(
        label="large_refactor",
        max_tokens=max_tokens,
        messages=[
            {
                "role": "system",
                "content": "You are a senior AI engineer reviewing a large coding change.",
            },
            {
                "role": "user",
                "content": f"{context}\n\nTask: {random.choice(REFACTOR_TASKS)}",
            },
        ],
    )


def choose_request(max_model_len: int) -> WorkloadRequest:
    roll = random.random()
    if roll < 0.60:
        return repository_chat(max_model_len)
    if roll < 0.90:
        return autocomplete(max_model_len)
    return large_refactor(max_model_len)
