# Sample Agent (LangChain) for AgentCore HTTP

This sample demonstrates a minimal AgentCore HTTP runtime using LangChain with optional persistent short‑term memory via AgentCore Memory.

## Endpoints
- `GET /ping` – health check (AgentCore SDK)
- `POST /invocations` – main entrypoint; expects strict JSON like `{ "prompt": "Hello" }`

## Memory
- In‑process short memory (default): rolling window of the last N turns per session (env: `SHORT_MEMORY_TURNS`, default 5).
- AgentCore Memory (optional): if `MEMORY_ID` is set, the agent will use `MemoryClient` to:
  - Read last K events (`list_events`, with `include_payload=True`) and prepend them to the LLM messages
  - Append the current user/assistant turns (`create_event`) with RFC3339 `event_timestamp`

This mirrors the AWS “customer scenario” steps (capture turns, retrieve last K). See the docs: [AgentCore Memory scenario](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-customer-scenario.html).

## Environment variables
- `AWS_REGION` (or `AWS_DEFAULT_REGION`): region for Bedrock Runtime and AgentCore Memory
- `BEDROCK_MODEL_ID`: Bedrock model id (e.g., `anthropic.claude-3-sonnet-20240229-v1:0`)
- `SHORT_MEMORY_TURNS`: number of recent turn pairs to retain in memory (default 5)
- `MEMORY_ID`: if set, enables persistent short‑term memory via AgentCore

## Deployment

Use CDK Stack in Infra folder to deploy AgentCore and Memory. Use Agent ARN in `frontend.py` to test.




## References
- AWS docs – HTTP contract: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html
- AWS docs – Memory scenario: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-customer-scenario.html
- Samples: https://github.com/awslabs/amazon-bedrock-agentcore-samples