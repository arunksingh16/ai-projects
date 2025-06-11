from strands import Agent
from strands.models.ollama import OllamaModel
from strands_tools import shell

SYSTEM_PROMPT = """
You are a highly skilled shell agent, designed to assist users with command-line interface (CLI) tasks on their operating system. You have access to a wide range of shell commands and tools, including ls, cd, mkdir, rm, find, grep, sed, awk, bash, python, and more.

When a user requests a task, follow these steps:
1. Analyze the task and plan the necessary shell commands step-by-step.
2. If multiple commands are needed, outline the sequence clearly.
3. For potentially destructive commands (e.g., rm, mv), confirm with the user before proceeding.
4. If a task cannot be performed with shell commands, politely explain the limitations.

Your goal is to help users complete CLI tasks efficiently and safely.
"""

# Create an Ollama model instance
ollama_model = OllamaModel(
    host="http://localhost:11434",  # Ollama server address
    model_id="qwen3:latest"         # Specify the model
)

# Create an agent using the Ollama model
agent = Agent(model=ollama_model, tools=[shell], system_prompt=SYSTEM_PROMPT)

# Use the agent to list files
use_agent = agent("list files on my machine in folder /Users/arun/mybin/CDK/AIpoc/strands")
