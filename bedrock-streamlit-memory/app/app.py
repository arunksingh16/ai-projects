import json
import boto3
import streamlit as st
import dotenv
import os
import logging

# Load environment variables and set up logging
dotenv.load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Amazon Bedrock Claude3 Chat with Memory", layout="centered")
st.title("Amazon Bedrock Claude3 Chat with Memory")

region = "us-east-2"
client = boto3.client("bedrock-runtime", region_name=region)

model_id = os.getenv("BEDROCK_MODEL_ID", "arn:aws:bedrock:us-east-2:1111111:inference-profile/us.anthropic.claude-3-haiku-20240307-v1:0")
task_id = os.getenv("TASK_ID", "N/A")
logger.info(f"Using model_id: {model_id}, region: {region}, task_id: {task_id}")

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Clear chat button
if st.button("🧹 Clear Chat"):
    st.session_state.messages = []
    st.rerun()

# Parse response stream
def parse_stream(stream):
    for event in stream:
        chunk = event.get("chunk")
        if chunk:
            message = json.loads(chunk.get("bytes").decode())
            if message["type"] == "content_block_delta":
                yield message["delta"].get("text", "")
            elif message["type"] == "message_stop":
                break

# Show chat history
st.subheader("Chat History", divider="gray")
for msg in st.session_state.messages:
    role = "You" if msg["role"] == "user" else "Claude"
    text = msg["content"][0]["text"]
    st.markdown(f"**{role}:** {text}")

# Input prompt
prompt = st.text_input("Your message")

if prompt:
    # Add user message to session
    st.session_state.messages.append({
        "role": "user",
        "content": [{"type": "text", "text": prompt}]
    })

    # Prepare request
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "messages": st.session_state.messages
    })

    # Call Claude via Bedrock
    try:
        response = client.invoke_model_with_response_stream(
            modelId=model_id,
            body=body,
        )
        stream = response.get("body")

        st.subheader("Claude's response", divider="rainbow")
        response_placeholder = st.empty()
        full_response = ""

        for chunk in parse_stream(stream):
            full_response += chunk
            response_placeholder.markdown(full_response)

        # Add assistant message to session
        st.session_state.messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": full_response}]
        })

    except Exception as e:
        st.error(f"Error while invoking Claude: {e}")
        logger.error("Claude invocation failed", exc_info=True)
