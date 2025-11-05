import asyncio
import boto3
import json
import uuid
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

agent_core_client = boto3.client('bedrock-agentcore')

st.title("Chatbot")

# Initialize session state for chat history and session ID
if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

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
        agent_runtime_arn = "arn:aws:bedrock-agentcore:us-east-1:<account-id>:runtime/strands_agentcore-nqLd8bConX"
        
        try:
            agent_response = agent_core_client.invoke_agent_runtime(
                agentRuntimeArn=agent_runtime_arn,
                runtimeSessionId=st.session_state.session_id,
                payload=json.dumps({"prompt": prompt}).encode()
            )
            
            for line in agent_response["response"].iter_lines():
                if not line:
                    continue
                    
                line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                    
                try:
                    data = json.loads(line[6:])
                    
                    if isinstance(data, dict):
                        event = data.get("event", {})

                        if "contentBlockStart" in event:
                            tool_use = event["contentBlockStart"].get("start", {}).get("toolUse", {})
                            tool_name = tool_use.get("name")
                            
                            if tool_name:
                                st.info(f"🔧 Using tool: {tool_name}")
                        
                        elif "contentBlockDelta" in event:
                            delta = event["contentBlockDelta"]["delta"]
                            if "text" in delta:
                                text = delta["text"]
                                full_response += text
                                message_placeholder.markdown(full_response + "▌")
                                
                except json.JSONDecodeError:
                    continue
            
            # Remove cursor and finalize response
            message_placeholder.markdown(full_response)
            
            # Add assistant response to chat history
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            st.error(f"Error: {str(e)}")

# Add a button to clear chat history
if st.sidebar.button("Clear Chat History"):
    st.session_state.messages = []
    st.session_state.session_id = str(uuid.uuid4())
    st.rerun()
