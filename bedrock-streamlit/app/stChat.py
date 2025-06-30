import json
import boto3
import streamlit as st
import dotenv
import os
import logging

# Set up basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

dotenv.load_dotenv()

st.title("Amazon Bedrock Claude3 Response Streaming Demo")


region = "us-east-2"
client = boto3.client("bedrock-runtime", region_name=region)

# model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
model_id = os.getenv(
    "BEDROCK_MODEL_ID",
    "anthropic.claude-3-haiku-20240307-v1:0"
)

# Print logs for current in use model, AWS region, and task id (if available)
task_id = os.getenv("TASK_ID", "N/A")
print(f"Using model_id: {model_id}")
print(f"AWS region: {region}")
print(f"Task ID: {task_id}")
# Log something
logger.info("Using model_id: {model_id}")


def parse_stream(stream):
    for event in stream:
        chunk = event.get('chunk')
        if chunk:
            message = json.loads(chunk.get("bytes").decode())
            if message['type'] == "content_block_delta":
                yield message['delta']['text'] or ""
            elif message['type'] == "message_stop":
                return "\n"


if prompt := st.text_input("Prompt"):

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        # "system": "You are a helpful assistant",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
    })

    streaming_response = client.invoke_model_with_response_stream(
        modelId=model_id,
        body=body,
    )

    st.subheader("Output stream", divider="rainbow")
    stream = streaming_response.get("body")
    st.write_stream(parse_stream(stream))
    st.write_stream(stream)