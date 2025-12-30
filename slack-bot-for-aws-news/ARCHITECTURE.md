# Architecture Overview

## System Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                         Slack Workspace                        │
│                                                                │
│  ┌──────────┐    ┌──────────┐    ┌─────────────┐               │
│  │  Channel │    │   DMs    │    │   Threads   │               │
│  │ @awsnews │    │          │    │ /awsnews    │               │
│  └────┬─────┘    └─────┬────┘    └──────┬──────┘               │
│       │                │                │                      │
│       └────────────────┴────────────────┘                      │
│                        │                                       │
└────────────────────────┴───────────────────────────────────────┘
                         │
                         │ Socket Mode (WebSocket)
                         │
                         ▼
┌───────────────────────────────────────────────────────────────┐
│                    AWS News Slack Bot                         │
│                      (Python Application)                     │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Event Handlers                                        │   │
│  │  • @app_mention → handle_mention()                     │   │
│  │  • /awsnews command → handle_command()                 │   │
│  │  • Direct messages → handle_direct_message()           │   │
│  └────────────────┬───────────────────────────────────────┘   │
│                   │                                           │
│  ┌────────────────▼───────────────────────────────────────┐   │
│  │  LLM Orchestration (chat_with_llm)                     │   │
│  │  • Manages conversation context                        │   │
│  │  • Handles tool calls                                  │   │
│  │  • Processes responses                                 │   │
│  └────────┬───────────────────────────────────┬───────────┘   │
│           │                                   │               │
│           │                                   │               │
│  ┌────────▼───────────┐          ┌────────────▼──────────┐    │
│  │  MCP Client        │          │  Scheduler            │    │
│  │  (HTTP)            │          │  • Weekly Digest      │    │
│  └────────┬───────────┘          │  • Monday 9 AM        │    │
│           │                      └───────────────────────┘    │
└───────────┼───────────────────────────────────────────────────┘
            │                       │
            │ HTTP                  │ Azure OpenAI API
            │                       │
┌───────────▼──────────┐   ┌────────▼────────────────────┐
│   MCP Server (AWS)   │   │   Azure OpenAI Service      │
│                      │   │   (GPT-4 / GPT-3.5)         │
│  ┌────────────────┐  │   │                             │
│  │ /tools/        │  │   │  • Chat Completions         │
│  │ get_aws_news   │  │   │  • Function Calling         │
│  │                │  │   │  • Tool Support             │
│  │ /tools/        │  │   └─────────────────────────────┘
│  │ get_aws_feed_  │  │
│  │ news           │  │
│  └────────────────┘  │
│                      │
│  ┌────────────────┐  │
│  │ /health        │  │
│  └────────────────┘  │
└──────────────────────┘
```

## Data Flow

### 1. User Mentions Bot

```
User in Slack: "@awsnews what's new with EC2 this week?"
       │
       ▼
[Slack Event: app_mention]
       │
       ▼
handle_mention() → Extracts text
       │
       ▼
chat_with_llm(user_message)
       │
       ├─────────────────────┐
       │                     │
       ▼                     ▼
[Azure OpenAI]         [Conversation Context]
       │
       ▼
[Response with function call: get_aws_news]
       │
       ▼
MCPClient.call_tool("get_aws_news", {...})
       │
       ▼
[HTTP POST to MCP Server]
       │
       ▼
[MCP Server fetches AWS news]
       │
       ▼
[Returns JSON data]
       │
       ▼
[Send to Azure OpenAI as tool result]
       │
       ▼
[Azure OpenAI generates natural language response]
       │
       ▼
[Post to Slack thread]
```

### 2. Slash Command

```
User in Slack: "/awsnews show me Lambda updates"
       │
       ▼
[Slack Command: /awsnews]
       │
       ▼
handle_command() → Creates thread
       │
       ▼
chat_with_llm(user_message)
       │
       ▼
[Same flow as mentions...]
       │
       ▼
[Reply in thread]
```

### 3. Weekly Digest

```
[APScheduler: Every Monday 9 AM]
       │
       ▼
send_weekly_digest()
       │
       ▼
chat_with_llm("Summarize this week's AWS news")
       │
       ▼
[Calls MCP tools with date filters]
       │
       ▼
[Generates digest]
       │
       ▼
[Posts to configured channel]
```

## Component Responsibilities

### Slack Bot (`bot.py`)

**Responsibilities:**
- Handle Slack events (mentions, commands, DMs)
- Manage WebSocket connection via Socket Mode
- Orchestrate LLM interactions
- Schedule background jobs

**Key Classes/Functions:**
- `handle_mention()` - Process @mentions
- `handle_command()` - Process slash commands
- `handle_direct_message()` - Process DMs
- `chat_with_llm()` - LLM orchestration with tool calling
- `MCPClient` - HTTP client for MCP server
- `send_weekly_digest()` - Scheduled digest sender

### Azure OpenAI

**Responsibilities:**
- Natural language understanding
- Generate conversational responses
- Determine when to call tools
- Synthesize tool results into answers

**Features Used:**
- Chat Completions API
- Function Calling / Tools
- Conversation context management

### MCP Server

**Responsibilities:**
- Fetch AWS news from various sources
- Filter and format data
- Provide tool endpoints

**Endpoints:**
- `POST /tools/get_aws_news` - Service-specific news
- `POST /tools/get_aws_feed_news` - Latest RSS feed

## Deployment Architecture

### Development

```
┌────────────────┐
│  Local Machine │
│                │
│  ┌──────────┐  │
│  │ Slack    │  │──── Socket Mode ────▶ Slack API
│  │ Bot      │  │
│  └─────┬────┘  │
│        │       │
│        │ HTTP  │
│        ▼       │
│  ┌──────────┐  │
│  │   MCP    │  │ (or remote AWS)
│  │  Server  │  │
│  └──────────┘  │
└────────────────┘
```

### Production (AWS)

```
┌────────────────────────────────────────────────┐
│                    AWS Cloud                   │
│                                                │
│  ┌────────────────┐         ┌───────────────┐  │
│  │   ECS/Fargate  │         │  MCP Server   │  │
│  │                │         │               │  │
│  │  ┌──────────┐  │  HTTP   │  ┌─────────┐  │  │
│  │  │  Slack   │  │◄────────┤  │ Lambda  │  │  │
│  │  │  Bot     │  │         │  │   or    │  │  │
│  │  │ Container│  │         │  │  ECS    │  │  │
│  │  └──────────┘  │         │  └─────────┘  │  │
│  │                │         │               │  │
│  │  • Auto-scaling│         │  • API GW     │  │
│  │  • Health check│         │  • ALB        │  │
│  │  • CloudWatch  │         └───────────────┘  │
│  └────────────────┘                            │
│         │                                      │
│         │ Secrets                              │
│         ▼                                      │
│  ┌────────────────┐                            │
│  │   Secrets      │                            │
│  │   Manager      │                            │
│  └────────────────┘                            │
└────────────────────────────────────────────────┘
         │
         │ HTTPS
         ▼
┌─────────────────┐
│  Azure OpenAI   │
│    Service      │
└─────────────────┘
```

## Security Considerations

### Secrets Management

```
Production:
├── AWS Secrets Manager
│   ├── slack/bot-token
│   ├── slack/app-token
│   └── azure/openai-key
│
Development:
└── .env file (gitignored)
```

### Network Security

- **Slack Connection**: Socket Mode (outbound only, no ingress)
- **MCP Server**: HTTPS with authentication
- **Azure OpenAI**: HTTPS with API key

### Permissions

**Slack Bot Scopes:**
- Minimal permissions for functionality
- Read-only where possible
- No admin privileges required

## Scalability

### Horizontal Scaling

- Bot can run multiple instances
- Socket Mode handles connection per instance
- MCP server scales independently
- No shared state required

### Performance Considerations

- **Async I/O**: All HTTP calls are async
- **Connection Pooling**: httpx client reuses connections
- **Rate Limiting**: Respect Slack and Azure OpenAI limits
- **Caching**: Consider caching frequent queries

## Monitoring

### Key Metrics

```
┌──────────────────────┐
│  Application Logs    │
│  • Event handling    │
│  • LLM calls         │
│  • MCP requests      │
│  • Errors            │
└──────────────────────┘
          │
          ▼
┌──────────────────────┐
│   CloudWatch Logs    │
│  • Structured logs   │
│  • Error tracking    │
│  • Performance       │
└──────────────────────┘
          │
          ▼
┌──────────────────────┐
│   CloudWatch Alarms  │
│  • Error rate        │
│  • Response time     │
│  • Health checks     │
└──────────────────────┘
```

### Health Checks

- Application health endpoint
- MCP server connectivity
- Azure OpenAI availability
- Slack connection status

## Cost Optimization

### Azure OpenAI

- Use appropriate model (GPT-3.5 vs GPT-4)
- Set max_tokens limits
- Cache frequent responses
- Monitor token usage

### AWS Costs

- Use Fargate Spot for cost savings
- Right-size container resources
- Use reserved capacity for steady state


