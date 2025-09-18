import streamlit as st
import os
import json
import logging
import tiktoken
from datetime import datetime
from langchain_openai import AzureChatOpenAI
from langchain_community.callbacks import get_openai_callback
from langchain.memory import ConversationBufferMemory

# Set page config
st.set_page_config(
    page_title="AI Agent",
    page_icon="🤖",
    layout="wide"
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ai_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

if "memory" not in st.session_state:
    st.session_state.memory = ConversationBufferMemory(return_messages=True)

if "total_cost" not in st.session_state:
    st.session_state.total_cost = 0.0

if "interaction_count" not in st.session_state:
    st.session_state.interaction_count = 0

# Configure Azure OpenAI
os.environ["AZURE_OPENAI_ENDPOINT"] = "https://dummy.openai.azure.com/"
os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"] = "gpt-4o"
os.environ["AZURE_OPENAI_API_VERSION"] = "2025-01-01-preview"

# Initialize the LLM
@st.cache_resource
def get_llm():
    return AzureChatOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"],
        openai_api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2,
        model_version="2024-08-06",
    )

llm = get_llm()

# Cost calculation function for Azure OpenAI
def calculate_cost(input_tokens, output_tokens, model="gpt-4o"):
    """Calculate cost based on Azure OpenAI pricing"""
    # Azure OpenAI GPT-4o pricing (as of 2024)
    pricing = {
        "gpt-4o": {
            "input": 0.0025 / 1000,  # $0.0025 per 1K input tokens
            "output": 0.01 / 1000    # $0.01 per 1K output tokens
        },
        "gpt-4": {
            "input": 0.03 / 1000,    # $0.03 per 1K input tokens
            "output": 0.06 / 1000    # $0.06 per 1K output tokens
        }
    }
    
    if model not in pricing:
        model = "gpt-4o"  # Default to gpt-4o pricing
    
    input_cost = input_tokens * pricing[model]["input"]
    output_cost = output_tokens * pricing[model]["output"]
    total_cost = input_cost + output_cost
    
    return total_cost, input_tokens, output_tokens

# Token counting function
def count_tokens(text, model="gpt-4o"):
    """Count tokens in text using tiktoken"""
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except:
        # Fallback to cl100k_base encoding (used by GPT-4)
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))

# App title
st.title("🤖 AI Agent")
st.markdown("A simple AI assistant powered by Azure OpenAI")

# Helper function to log interaction
def log_interaction(user_input, assistant_response, cost, input_tokens, output_tokens, total_tokens):
    """Log the interaction to file and console"""
    interaction_data = {
        "timestamp": datetime.now().isoformat(),
        "user_input": user_input,
        "assistant_response": assistant_response,
        "cost": cost,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "interaction_id": st.session_state.interaction_count
    }
    
    # Log to file
    logger.info(f"Interaction {st.session_state.interaction_count}: Cost ${cost:.6f} (Input: {input_tokens}, Output: {output_tokens})")
    logger.info(f"User: {user_input[:100]}...")
    logger.info(f"Assistant: {assistant_response[:100]}...")
    
    # Save detailed log to JSON file
    log_file = "conversation_log.json"
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                logs = json.load(f)
        else:
            logs = []
        
        logs.append(interaction_data)
        
        with open(log_file, 'w') as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save interaction log: {e}")

# Chat interface
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("What would you like to ask?"):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Add to memory
    st.session_state.memory.chat_memory.add_user_message(prompt)
    
    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Display assistant response
    with st.chat_message("assistant"):
        # Get conversation history from memory
        conversation_history = st.session_state.memory.chat_memory.messages
        
        # Prepare messages for the LLM with full conversation context
        messages = [("system", "You are a helpful assistant. You have access to the full conversation history.")]
        
        # Add conversation history
        for msg in conversation_history:
            if hasattr(msg, 'content'):
                role = "human" if msg.__class__.__name__ == "HumanMessage" else "assistant"
                messages.append((role, msg.content))
        
        # Calculate input tokens
        input_text = " ".join([msg[1] for msg in messages])
        input_tokens = count_tokens(input_text)
        
        # Stream the response
        response_container = st.empty()
        full_response = ""
        
        # Use streaming without callback (since it doesn't work with Azure OpenAI)
        for chunk in llm.stream(messages):
            full_response += chunk.content
            response_container.markdown(full_response + "▌")
        
        # Remove the cursor and display final response
        response_container.markdown(full_response)
        
        # Calculate output tokens and cost
        output_tokens = count_tokens(full_response)
        total_tokens = input_tokens + output_tokens
        cost, _, _ = calculate_cost(input_tokens, output_tokens)
        
        # Update session state with cost tracking
        st.session_state.total_cost += cost
        st.session_state.interaction_count += 1
        
        # Log the interaction
        log_interaction(prompt, full_response, cost, input_tokens, output_tokens, total_tokens)
    
    # Add assistant response to chat history and memory
    st.session_state.messages.append({"role": "assistant", "content": full_response})
    st.session_state.memory.chat_memory.add_ai_message(full_response)

# Sidebar
with st.sidebar:
    st.header("Settings")
    
    if st.button("Clear Chat"):
        st.session_state.messages = []
        st.session_state.memory.clear()
        st.session_state.total_cost = 0.0
        st.session_state.interaction_count = 0
        logger.info("Chat cleared by user")
        st.rerun()
    
    st.markdown("---")
    st.header("Session Statistics")
    
    # Cost tracking
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Cost", f"${st.session_state.total_cost:.6f}")
    with col2:
        st.metric("Interactions", st.session_state.interaction_count)
    
    # Average cost per interaction
    if st.session_state.interaction_count > 0:
        avg_cost = st.session_state.total_cost / st.session_state.interaction_count
        st.metric("Avg Cost/Interaction", f"${avg_cost:.6f}")
    
    # Token usage info
    if os.path.exists("conversation_log.json"):
        with open("conversation_log.json", 'r') as f:
            logs = json.load(f)
        if logs:
            total_input_tokens = sum(log.get("input_tokens", 0) for log in logs)
            total_output_tokens = sum(log.get("output_tokens", 0) for log in logs)
            st.metric("Total Input Tokens", f"{total_input_tokens:,}")
            st.metric("Total Output Tokens", f"{total_output_tokens:,}")
    
    st.markdown("---")
    st.header("Model Info")
    st.markdown("**Model:** GPT-4o")
    st.markdown("**Provider:** Azure OpenAI")
    
    # Memory info
    st.markdown("---")
    st.header("Memory")
    memory_messages = len(st.session_state.memory.chat_memory.messages)
    st.metric("Messages in Memory", memory_messages)
    
    if st.button("View Memory"):
        st.text_area("Conversation Memory", 
                    value=str(st.session_state.memory.chat_memory.messages), 
                    height=200)
    
    # Log files info
    st.markdown("---")
    st.header("Logs")
    if os.path.exists("ai_agent.log"):
        log_size = os.path.getsize("ai_agent.log")
        st.metric("Log File Size", f"{log_size} bytes")
    
    if os.path.exists("conversation_log.json"):
        with open("conversation_log.json", 'r') as f:
            logs = json.load(f)
        st.metric("Logged Interactions", len(logs))
