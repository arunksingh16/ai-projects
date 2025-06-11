# AWS Strands with Ollama

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
