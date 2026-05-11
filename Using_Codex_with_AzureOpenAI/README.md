Update .codex/config.toml


```
model = "gpt-5.5"  # Replace with your actual Azure model deployment name
model_provider = "azure"
model_reasoning_effort = "medium"

[model_providers.azure]
name = "Azure OpenAI"
base_url = "https://<project>.openai.azure.com/openai/v1/"
env_key = "AZURE_OPENAI_API_KEY"
wire_api = "responses"

[tui.model_availability_nux]
"gpt-5.5" = 3
```
