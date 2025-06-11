# AWS Strands with Ollama
An artificial intelligence (AI) agent refers to a system or program that is capable of autonomously performing tasks on behalf of a user or another system by designing its workflow and utilizing available tools. [https://www.ibm.com/think/topics/ai-agents]


- download the model
```
ollama pull qwen3:latest
```
- validate ollama model
```
curl http://localhost:11434/api/tags
```
- prep python
```
python3 -m venv my_project_env
source my_project_env/bin/activate
pip install strands-agents strands-agents-tools
```
