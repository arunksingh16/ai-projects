"""Bedrock AgentCore entrypoint implemented with LangChain.

This module defines a minimal AgentCore-compatible entrypoint that:
1) Builds a LangChain LLM backed by Amazon Bedrock (Converse API)
2) Extracts a user query from the runtime payload
3) Sends messages in (system, human) format to the LLM
4) Returns a simple JSON result expected by AgentCore callers

Notes for new engineers:
- The Bedrock AgentCore runtime calls the function decorated with `@app.entrypoint`.
- The `payload` can be a JSON string or a dict; we support both.
- We use LangChain's `ChatBedrockConverse` which integrates with Bedrock Runtime.
- The return value must be JSON-serializable (dicts are fine).
"""

from langchain_aws import ChatBedrockConverse
import os
import boto3
from botocore.exceptions import ClientError
import time
from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext
from collections import deque

app = BedrockAgentCoreApp()
# Short-term, in-process memory (per runtime session)
_MAX_TURNS = int(os.environ.get("SHORT_MEMORY_TURNS", "5"))  # number of (user, ai) pairs to retain
_SESSION_HISTORY = {}
MEMORY_ID = os.environ.get("MEMORY_ID")  # Optional: persistent short-term memory resource id

def _get_region() -> str:
    return os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "eu-west-1"))

def _get_session_id(payload, context: RequestContext | None) -> str:
    """Best-effort extraction of a session identifier for rolling memory."""
    sid = None
    try:
        if context is not None:
            # Common attributes; adjust as AgentCore SDK evolves
            sid = getattr(context, "session_id", None) or getattr(context, "sessionId", None)
            if not sid and hasattr(context, "__dict__"):
                d = getattr(context, "__dict__", {})
                sid = d.get("sessionId") or d.get("session_id")
    except Exception:
        sid = None
    if not sid and payload is not None:
        try:
            if isinstance(payload, str):
                import json
                obj = json.loads(payload)
            else:
                obj = payload
            if isinstance(obj, dict):
                sid = obj.get("sessionId") or obj.get("runtimeSessionId")
        except Exception:
            sid = None
    return sid or "default"

def _get_actor_and_session(payload, context: RequestContext | None) -> tuple[str, str]:
    """Extract actorId and sessionId with sensible fallbacks."""
    actor_id = "anonymous"
    try:
        if payload is not None:
            if isinstance(payload, str):
                import json
                obj = json.loads(payload)
            else:
                obj = payload
            if isinstance(obj, dict):
                actor_id = obj.get("actorId") or actor_id
    except Exception:
        pass
    return actor_id, _get_session_id(payload, context)

def _list_last_k_turns(memory_id: str, actor_id: str, session_id: str, k: int) -> list[tuple[str, str]]:
    """Fetch last k events via AWS SDK (boto3) and map to LangChain tuples."""
    try:
        client = boto3.client("bedrock-agentcore", region_name=_get_region())
        resp = client.list_events(
            memoryId=memory_id,
            actorId=actor_id,
            sessionId=session_id,
            maxResults=k,
            includePayloads=True,
        )
        events = list(reversed(resp.get("events", [])))
        turns: list[tuple[str, str]] = []
        for e in events:
            conv = e.get("conversational") or {}
            role = conv.get("role")
            text = (conv.get("content") or {}).get("text", "")
            if role == "USER":
                turns.append(("human", text))
            elif role == "ASSISTANT":
                turns.append(("ai", text))
        print(f"[memory] list_events ok actor={actor_id} session={session_id} count={len(turns)}", flush=True)
        return turns
    except Exception as e:
        print(f"[memory] list_events error: {e}", flush=True)
        return []

def _add_turns(memory_id: str, actor_id: str, session_id: str, user_text: str, assistant_text: str) -> None:
    """Append user/assistant turns via AWS SDK (boto3) using the documented 'payload' parameter."""
    try:
        client = boto3.client("bedrock-agentcore", region_name=_get_region())
        payload = [
            {"conversational": {"role": "USER", "content": {"text": user_text}}},
            {"conversational": {"role": "ASSISTANT", "content": {"text": assistant_text}}},
        ]
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        client.create_event(
            memoryId=memory_id,
            actorId=actor_id,
            sessionId=session_id,
            eventTimestamp=ts,
            payload=payload,
        )
        print(f"[memory] create_event ok actor={actor_id} session={session_id}", flush=True)
    except Exception as e:
        print(f"[memory] create_event error: {e}", flush=True)
        
def build_llm() -> ChatBedrockConverse:
    """Construct a LangChain Chat model using the Bedrock Converse API.

    Environment variables:
    - AWS_REGION / AWS_DEFAULT_REGION: determines the Bedrock runtime region
    - BEDROCK_MODEL_ID: fully qualified model ID (e.g., "anthropic.claude-3-sonnet-20240229-v1:0")
    """

    # Choose region, defaulting to eu-west-1 if nothing is set
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "eu-west-1"))
    model_id = os.environ.get(
        "BEDROCK_MODEL_ID",
        "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )

    # Low-level Bedrock Runtime client used by LangChain's ChatBedrockConverse
    client = boto3.client("bedrock-runtime", region_name=region)

    return ChatBedrockConverse(
        model_id=model_id,
        client=client,
    )

@app.entrypoint
def entrypoint(payload=None, context: RequestContext = None):
    """AgentCore runtime entrypoint.

    Parameters
    - payload: Either a JSON string or a dict. We look for keys "prompt" or "query".
    - context: AgentCore `RequestContext` (metadata about the invocation). Optional.

    Returns
    - A JSON-serializable dict with keys:
      {"status": "success", "response": <text>} on success, or
      {"status": "error", "error": <message>} on failure.
    """
    llm = build_llm()

    system_prompt = (
        "You are a helpful AWS and CloudOps Engineer, experienced in: AWS architecture design "
        "and operational strategy. Infrastructure as Code (Terraform, CloudFormation, CDK). "
        "Automation, cost optimization, and observability. Cross-service integration (ECS, EKS, "
        "Lambda, S3, VPC, IAM, CloudWatch, etc.). Implementing secure, scalable, and cost-efficient "
        "cloud environments."
    )

    # Extract the user query from the incoming payload (supports string JSON or dict)
    query = "Hello, how are you?"
    try:
        if payload:
            if isinstance(payload, str):
                try:
                    import json
                    payload_obj = json.loads(payload)
                except Exception:
                    payload_obj = {}
            else:
                payload_obj = payload
            if isinstance(payload_obj, dict):
                query = payload_obj.get("prompt") or payload_obj.get("query") or query
    except Exception:
        pass

    # Resolve ids for memory
    actor_id, session_id = _get_actor_and_session(payload, context)

    # Build message list with recent turns from persistent memory if configured,
    # otherwise fallback to in-process rolling memory
    prior_turns: list[tuple[str, str]] = []
    if MEMORY_ID:
        prior_turns = _list_last_k_turns(MEMORY_ID, actor_id, session_id, k=_MAX_TURNS * 2)
    if not prior_turns:
        history = _SESSION_HISTORY.get(session_id)
        if history is None:
            history = deque(maxlen=_MAX_TURNS * 2)
            _SESSION_HISTORY[session_id] = history
        prior_turns = list(history)

    # LangChain expects a list of (role, content) tuples
    messages = [("system", system_prompt)] + prior_turns + [("human", query)]

    try:
        # Synchronous single-shot invoke; for streaming, use llm.stream(messages)
        result = llm.invoke(messages)
        response_text = getattr(result, "content", None) or str(result)
        # Persist short-term memory if configured; also maintain local cache
        if MEMORY_ID:
            _add_turns(MEMORY_ID, actor_id, session_id, query, response_text)
        else:
            try:
                history = _SESSION_HISTORY.get(session_id)
                if history is None:
                    history = deque(maxlen=_MAX_TURNS * 2)
                    _SESSION_HISTORY[session_id] = history
                history.append(("human", query))
                history.append(("ai", response_text))
            except Exception:
                pass
        # Keep return shape simple and stable for AgentCore callers and tests
        return {"status": "success", "response": response_text}
    except ClientError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    # Enables local execution (e.g., `python agent.py`) using the AgentCore dev server
    # Bind explicitly to the required HTTP contract host/port
    app.run(host="0.0.0.0", port=8080)