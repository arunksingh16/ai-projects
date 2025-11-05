import asyncio
import boto3
import json
import uuid
import os
import logging
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# --- Configuration & Client Initialization ---
AWS_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "eu-west-1"
AGENTCORE_ENDPOINT_URL = os.environ.get("AGENTCORE_ENDPOINT_URL")  # optional custom endpoint
AGENTCORE_RUNTIME_ARN = os.environ.get(
    "AGENTCORE_RUNTIME_ARN",
    "arn:aws:bedrock-agentcore:eu-west-1:xxxxxx:runtime/sample_agent_langchain-xxx"
)

# Initialize boto3 client for AgentCore runtime (optionally using custom endpoint)
if AGENTCORE_ENDPOINT_URL:
    agent_core_client = boto3.client('bedrock-agentcore', region_name=AWS_REGION, endpoint_url=AGENTCORE_ENDPOINT_URL)
else:
    agent_core_client = boto3.client('bedrock-agentcore', region_name=AWS_REGION)

st.title("Chatbot (AgentCore)")

# --- Logging Helpers & UI ---
if "logs" not in st.session_state:
    st.session_state.logs = []

def _append_log(level: str, message: str) -> None:
    st.session_state.logs.append(f"{level}: {message}")
    # also emit to server logs
    logging.log(getattr(logging, level, logging.INFO), message)

def log_info(message: str) -> None:
    _append_log("INFO", message)

def log_warn(message: str) -> None:
    _append_log("WARNING", message)

def log_error(message: str) -> None:
    _append_log("ERROR", message)

def log_debug(message: str) -> None:
    _append_log("DEBUG", message)

# Initialize session state for chat history and session ID
if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

# Sidebar: connection details and debug logs
with st.sidebar:
    st.subheader("Connection")
    st.caption("Ensure env vars are set if using a custom endpoint.")
    st.text(f"Region: {AWS_REGION}")
    st.text(f"Runtime ARN: {AGENTCORE_RUNTIME_ARN}")
    if AGENTCORE_ENDPOINT_URL:
        st.text(f"Endpoint: {AGENTCORE_ENDPOINT_URL}")
    else:
        st.text("Endpoint: AWS default")

    logs_box = st.expander("Debug logs", expanded=False)

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Enter your question or message:"):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Generate assistant response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        # Use the persistent session ID
        agent_runtime_arn = AGENTCORE_RUNTIME_ARN
        log_info(f"Invoking AgentCore runtime: session={st.session_state.session_id}")
        
        try:
            agent_response = agent_core_client.invoke_agent_runtime(
                agentRuntimeArn=agent_runtime_arn,
                runtimeSessionId=st.session_state.session_id,
                payload=json.dumps({"prompt": prompt}).encode()
            )
            log_debug("AgentCore invocation accepted. Streaming response...")

            # Helper to update logs panel live
            def _refresh_logs_panel():
                if logs_box:
                    with logs_box:
                        st.code("\n".join(st.session_state.logs[-200:]) or "(no logs yet)")

            # Find a stream-like object on the response
            stream_obj = None
            for key in ("response", "body", "stream", "payload"):
                candidate = agent_response.get(key) if isinstance(agent_response, dict) else None
                if candidate is not None and hasattr(candidate, "iter_lines"):
                    stream_obj = candidate
                    break
            if stream_obj is None and hasattr(agent_response, "iter_lines"):
                stream_obj = agent_response

            raw_seen_lines = []
            received_any_text = False

            if stream_obj is not None and hasattr(stream_obj, "iter_lines"):
                for line in stream_obj.iter_lines():
                    if not line:
                        continue
                    
                    try:
                        text_line = line.decode("utf-8", errors="replace")
                    except Exception:
                        text_line = str(line)

                    # Keep a small buffer of raw lines for diagnostics
                    if len(raw_seen_lines) < 20:
                        raw_seen_lines.append(text_line)

                    # Extract JSON payload: prefer SSE style `data: {json}`; otherwise try raw JSON
                    if text_line.startswith("data: "):
                        payload_str = text_line[6:]
                    else:
                        payload_str = text_line

                    try:
                        data = json.loads(payload_str)
                    except json.JSONDecodeError:
                        log_debug(f"Non-JSON stream line: {text_line[:120]}")
                        continue

                    # Common AgentCore event routing
                    event = data.get("event", data)

                    if "contentBlockStart" in event:
                        tool_use = event["contentBlockStart"].get("start", {}).get("toolUse", {})
                        tool_name = tool_use.get("name")
                        if tool_name:
                            st.info(f"🔧 Using tool: {tool_name}")
                            log_info(f"Tool started: {tool_name}")

                    elif "contentBlockDelta" in event:
                        delta = event["contentBlockDelta"].get("delta", {})
                        if "text" in delta:
                            text = delta["text"]
                            full_response += text
                            received_any_text = True
                            message_placeholder.markdown(full_response + "▌")
                        elif "json" in delta:
                            try:
                                tool_json = delta["json"]
                                as_text = "\n" + json.dumps(tool_json, indent=2)
                                full_response += as_text
                                received_any_text = True
                                message_placeholder.markdown(full_response + "▌")
                            except Exception as json_e:
                                log_warn(f"Failed to render JSON delta: {json_e}")

                    elif "contentBlockStop" in event:
                        log_info("Content block completed")

                    elif "messageStop" in event:
                        # Some implementations may include a final text field
                        final_text = (
                            event.get("messageStop", {}).get("text")
                            or data.get("outputText")
                            or data.get("response")
                        )
                        if isinstance(final_text, str) and final_text:
                            full_response += ("\n" if full_response else "") + final_text
                            received_any_text = True
                            message_placeholder.markdown(full_response)
                        log_info("Message streaming completed")

                    else:
                        # Fallback: check for generic text fields
                        for key in ("text", "outputText", "message", "content", "response"):
                            if isinstance(event.get(key), str):
                                full_response += ("\n" if full_response else "") + event[key]
                                received_any_text = True
                                message_placeholder.markdown(full_response + "▌")
                                break
                        else:
                            log_debug(f"Unknown event payload: {json.dumps(event)[:200]}")

            else:
                # Non-streaming fallback: try to read entire body if present
                log_warn("No stream-like object found; attempting non-streaming read")
                body = agent_response.get("body") if isinstance(agent_response, dict) else None
                if body is not None and hasattr(body, "read"):
                    content_bytes = body.read()
                    try:
                        content = json.loads(content_bytes.decode("utf-8", errors="replace"))
                    except Exception:
                        content = {"raw": content_bytes.decode("utf-8", errors="replace")}
                    text = (
                        content.get("outputText")
                        or content.get("text")
                        or content.get("message")
                        or content.get("content")
                        or content.get("response")
                        or json.dumps(content)[:2000]
                    )
                    full_response += text
                    received_any_text = True
                    message_placeholder.markdown(full_response)
                else:
                    log_error("Unable to read response body; unknown response shape")
            
            # Remove cursor and finalize response
            message_placeholder.markdown(full_response)
            
            if not received_any_text:
                log_warn("No assistant text received from stream. Showing first raw lines for diagnostics.")
                if raw_seen_lines:
                    with logs_box:
                        st.code("\n".join(raw_seen_lines))
                st.info("Invocation completed but no text was streamed. Check Debug logs for raw events.")

            # Add assistant response to chat history
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            log_error(f"Invocation error: {str(e)}")
            st.error(f"Error: {str(e)}")

# Add a button to clear chat history
if st.sidebar.button("Clear Chat History"):
    st.session_state.messages = []
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.logs = []
    st.rerun()