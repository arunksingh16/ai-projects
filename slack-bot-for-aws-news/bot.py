"""
AWS News Slack Bot with Azure OpenAI and MCP Server Integration
"""
import os
import json
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from openai import AzureOpenAI
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Slack app
app = AsyncApp(token=os.environ.get("SLACK_BOT_TOKEN"))

# Initialize Azure OpenAI client
azure_client = AzureOpenAI(
    api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
    api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
    azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
)

# MCP Server configuration
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL")
AZURE_DEPLOYMENT_NAME = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")

# MCP Tools definition for Azure OpenAI
MCP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_aws_news",
            "description": "Returns a list of AWS news articles with announcements of new products, services, and capabilities for the specified AWS topic/service. You can filter on news type (news or blogs) and optionally specify a since date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The AWS service or topic to get news about (e.g., 's3', 'ec2', 'lambda')"
                    },
                    "news_type": {
                        "type": "string",
                        "enum": ["all", "news", "blogs"],
                        "default": "all",
                        "description": "Filter by news type: 'all', 'news', or 'blogs'"
                    },
                    "include_regional_expansions": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include regional expansion news"
                    },
                    "number_of_results": {
                        "type": "integer",
                        "default": 20,
                        "description": "Number of results to return"
                    },
                    "since_date": {
                        "type": "string",
                        "description": "ISO 8601 date string to filter news since a specific date (e.g., '2025-01-01T00:00:00Z')"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_aws_announcements",
            "description": "Returns only official AWS News announcements (article_type=news) for the specified topic/service. Optionally include regional expansions and since date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "AWS service or topic (e.g., 's3', 'ec2', 'lambda')"
                    },
                    "include_regional_expansions": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include regional expansion announcements"
                    },
                    "number_of_results": {
                        "type": "integer",
                        "default": 20,
                        "description": "Number of results to return"
                    },
                    "since_date": {
                        "type": "string",
                        "description": "ISO 8601 date string filter (e.g., '2025-01-01T00:00:00Z')"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_aws_blogs",
            "description": "Returns only AWS Blog posts (article_type=blog) for the specified topic/service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "AWS service or topic (e.g., 's3', 'ec2', 'lambda')"
                    },
                    "number_of_results": {
                        "type": "integer",
                        "default": 20,
                        "description": "Number of results to return"
                    },
                    "since_date": {
                        "type": "string",
                        "description": "ISO 8601 date string filter (e.g., '2025-01-01T00:00:00Z')"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_aws_feed_news",
            "description": "Fetches the latest AWS announcements directly from the official AWS What's New RSS feed. This provides real-time access to the most recent announcements across all AWS services.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_articles": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum number of articles to return"
                    },
                    "search_keywords": {
                        "type": "string",
                        "description": "Optional keywords to filter the feed results"
                    }
                }
            }
        }
    }
]


class MCPClient:
    """Client for communicating with the MCP HTTP server"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json"
            }
        )
        self.session_id = None  # Will be set during initialization
        self.request_id = 0
        self.initialized = False
    
    async def initialize(self) -> bool:
        """Initialize MCP session according to MCP protocol"""
        try:
            if self.initialized:
                return True
            
            logger.info("Initializing MCP session...")
            
            # Send initialization request per MCP spec
            init_request = {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "aws-news-slack-bot",
                        "version": "1.0.0"
                    }
                },
                "id": 0
            }
            
            response = await self.client.post(
                f"{self.base_url}/mcp",
                json=init_request
            )
            response.raise_for_status()
            
            # Check for session ID in response header per MCP spec
            session_id = response.headers.get("Mcp-Session-Id")
            if session_id:
                self.session_id = session_id
                logger.info(f"MCP session established: {session_id[:16]}...")
            else:
                logger.info("MCP server does not use session management")
            
            # Check Content-Type to determine how to parse response
            content_type = response.headers.get("content-type", "")
            
            if "text/event-stream" in content_type:
                # Server returned SSE stream - we need to read the first event
                logger.info("Server returned SSE stream for initialization")
                # For initialization, we'll just check if we got a session ID
                # The actual initialization result will be in the SSE stream
                # For simplicity, if we got here with 200 OK, consider it successful
                init_success = True
            else:
                # Server returned JSON
                result = response.json()
                
                # Verify initialization succeeded
                if 'result' in result:
                    init_success = True
                    logger.info("MCP initialization successful")
                elif 'error' in result:
                    error_msg = result['error'].get('message', 'Unknown error')
                    logger.error(f"MCP initialization failed: {error_msg}")
                    return False
                else:
                    return False
            
            # Per MCP spec, after successful initialize response, client MUST send initialized notification
            if init_success:
                initialized_notification = {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized"
                }
                
                # Prepare headers for notification
                headers = {}
                if self.session_id:
                    headers["Mcp-Session-Id"] = self.session_id
                
                # Send initialized notification (202 Accepted expected per spec)
                notif_response = await self.client.post(
                    f"{self.base_url}/mcp",
                    json=initialized_notification,
                    headers=headers
                )
                
                # 202 Accepted is expected for notifications
                if notif_response.status_code == 202:
                    logger.info("Sent initialized notification")
                else:
                    logger.warning(f"Initialized notification returned: {notif_response.status_code}")
                
                self.initialized = True
                logger.info("MCP initialization complete")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error initializing MCP session: {e}")
            return False
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call a tool on the MCP server using JSON-RPC protocol"""
        try:
            # Ensure we're initialized first
            if not self.initialized:
                await self.initialize()
            
            logger.info(f"Calling MCP tool: {tool_name} with args: {arguments}")
            
            # Increment request ID for each call
            self.request_id += 1
            
            # FastMCP with HTTP transport uses JSON-RPC 2.0
            json_rpc_request = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                },
                "id": self.request_id
            }
            
            # Prepare headers - include session ID if server provided one
            headers = {}
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
            
            # Make request to /mcp endpoint per MCP spec
            response = await self.client.post(
                f"{self.base_url}/mcp",
                json=json_rpc_request,
                headers=headers
            )
            response.raise_for_status()
            
            # Check Content-Type to determine how to parse response
            content_type = response.headers.get("content-type", "")
            
            if "text/event-stream" in content_type:
                # Server returned SSE stream
                logger.info("Server returned SSE stream for tool call")
                # For SSE streams, we need to parse the events
                # For now, read the response text and look for data: lines
                response_text = response.text
                
                # Simple SSE parsing - look for data: lines
                lines = response_text.strip().split('\n')
                for line in lines:
                    if line.startswith('data: '):
                        data_json = line[6:]  # Remove 'data: ' prefix
                        try:
                            event_data = json.loads(data_json)
                            # Check if this is the result we're looking for
                            if isinstance(event_data, dict) and 'result' in event_data:
                                tool_result = event_data['result']
                                # Extract content from MCP response
                                if isinstance(tool_result, dict) and 'content' in tool_result:
                                    content = tool_result['content']
                                    if isinstance(content, list) and len(content) > 0 and 'text' in content[0]:
                                        text = content[0]['text']
                                        logger.info(f"MCP tool response received (SSE): {len(text)} chars")
                                        return text
                        except json.JSONDecodeError:
                            continue
                
                logger.warning("Could not extract result from SSE stream")
                return "Error: Could not parse SSE stream response"
            else:
                # Server returned JSON
                result = response.json()
                
                # Handle JSON-RPC response
                if isinstance(result, dict):
                    # Check for JSON-RPC error
                    if 'error' in result:
                        error_msg = result['error'].get('message', str(result['error']))
                        logger.error(f"MCP tool error: {error_msg}")
                        return f"Error from MCP server: {error_msg}"
                    
                    # Extract the result from JSON-RPC response
                    if 'result' in result:
                        tool_result = result['result']
                        
                        # MCP tool results have a 'content' field with array of content items
                        if isinstance(tool_result, dict) and 'content' in tool_result:
                            content = tool_result['content']
                            if isinstance(content, list) and len(content) > 0:
                                # Get the text from the first content item
                                if 'text' in content[0]:
                                    text = content[0]['text']
                                    logger.info(f"MCP tool response received: {len(text)} chars")
                                    return text
                        
                        # If result is already a string, return it
                        if isinstance(tool_result, str):
                            logger.info(f"MCP tool response received: {len(tool_result)} chars")
                            return tool_result
                        
                        # Otherwise return as JSON
                        logger.info(f"MCP tool response received: {len(str(tool_result))} chars")
                        return json.dumps(tool_result, indent=2)
                
                logger.warning(f"Unexpected MCP response format: {result}")
                return json.dumps(result, indent=2)
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling MCP tool: {e}")
            return f"Error calling tool: {str(e)}"
        except Exception as e:
            logger.error(f"Error calling MCP tool: {e}")
            return f"Error: {str(e)}"
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()


# Initialize MCP client
mcp_client = MCPClient(MCP_SERVER_URL)


async def chat_with_llm(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> str:
    """
    Chat with Azure OpenAI, handling tool calls for MCP server
    """
    if conversation_history is None:
        conversation_history = []
    
    # System message
    system_message = {
        "role": "system",
        "content": """You are AWS News Bot, a helpful assistant that provides information about AWS services, announcements, and news.

You have access to tools that can fetch:
1. AWS news and blog posts for specific services
2. Latest AWS announcements from the official RSS feed

When users ask about AWS news, announcements, or updates:
- Use the appropriate tool to fetch current information
- Provide concise, helpful summaries
- Include relevant details like dates and service names
- If asked about "this week" or recent news, use the since_date parameter

Be conversational and helpful. If the question is not about AWS news, provide general assistance."""
    }
    
    # Build messages
    messages = [system_message]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})
    
    max_iterations = 5
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        try:
            # Call Azure OpenAI
            response = azure_client.chat.completions.create(
                model=AZURE_DEPLOYMENT_NAME,
                messages=messages,
                tools=MCP_TOOLS,
                tool_choice="auto",
                #temperature=0.7,

            )
            
            assistant_message = response.choices[0].message
            
            # If no tool calls, return the response
            if not assistant_message.tool_calls:
                return assistant_message.content
            
            # Add assistant message to conversation
            messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in assistant_message.tool_calls
                ]
            })
            
            # Execute tool calls
            for tool_call in assistant_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                logger.info(f"Executing tool: {function_name}")
                
                # Call MCP server
                tool_response = await mcp_client.call_tool(function_name, function_args)
                
                # Add tool response to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_response
                })
            
            # Continue loop to get final response
            
        except Exception as e:
            logger.error(f"Error in chat_with_llm: {e}")
            return f"I encountered an error: {str(e)}"
    
    return "I apologize, but I reached the maximum number of tool calls. Please try simplifying your question."


@app.event("app_mention")
async def handle_mention(event, say, logger):
    """Handle @mention events"""
    try:
        user_id = event['user']
        text = event['text']
        thread_ts = event.get('thread_ts', event['ts'])
        
        # Remove the bot mention from the text
        # Extract bot user ID from text
        import re
        bot_mention = re.search(r'<@[A-Z0-9]+>', text)
        if bot_mention:
            text = text.replace(bot_mention.group(), '').strip()
        
        if not text:
            await say(
                text=f"Hi <@{user_id}>! Ask me anything about AWS news and announcements. For example: 'What's new with EC2 this week?'",
                thread_ts=thread_ts
            )
            return
        
        # Send typing indicator
        await say(
            text=f"<@{user_id}> bot is thinking... :mag:",
            thread_ts=thread_ts
        )
        
        # Get response from LLM
        response = await chat_with_llm(text)
        
        # Send response
        await say(
            text=f"<@{user_id}> {response}",
            thread_ts=thread_ts
        )
        
    except Exception as e:
        logger.error(f"Error handling mention: {e}")
        await say(
            text=f"Sorry, I encountered an error: {str(e)}",
            thread_ts=event.get('thread_ts', event['ts'])
        )


@app.command("/awsnews")
async def handle_command(ack, command, say, logger):
    """Handle /awsnews slash command"""
    await ack()
    
    try:
        user_id = command['user_id']
        text = command.get('text', '').strip()
        
        if not text:
            # Start a new thread with help message
            response = await say(
                text=f"Hi <@{user_id}>! :wave: I'm your AWS News assistant. Ask me anything about AWS announcements, updates, or services.\n\n"
                     f"Examples:\n"
                     f"• What's new with Lambda this week?\n"
                     f"• Show me recent S3 announcements\n"
                     f"• What are the latest AWS updates?\n"
                     f"• Tell me about EC2 news"
            )
            return
        
        # Start a thread with the user's question
        response = await say(
            text=f"<@{user_id}> asked: {text}\n\nLet me find that information for you... :mag:"
        )
        
        thread_ts = response['ts']
        
        # Get response from LLM
        answer = await chat_with_llm(text)
        
        # Reply in the thread
        await say(
            text=answer,
            thread_ts=thread_ts
        )
        
    except Exception as e:
        logger.error(f"Error handling command: {e}")
        await say(
            text=f"Sorry <@{user_id}>, I encountered an error: {str(e)}"
        )


@app.event("message")
async def handle_direct_message(event, say, logger):
    """Handle direct messages to the bot"""
    # Ignore bot messages and threaded messages (handled by mention handler)
    if event.get('bot_id') or event.get('thread_ts'):
        return
    
    # Only respond to DMs (channel type is 'im')
    channel_type = event.get('channel_type')
    if channel_type != 'im':
        return
    
    try:
        user_id = event['user']
        text = event.get('text', '').strip()
        
        if not text:
            return
        
        # Get response from LLM
        response = await chat_with_llm(text)
        
        # Send response
        await say(text=response)
        
    except Exception as e:
        logger.error(f"Error handling DM: {e}")
        await say(text=f"Sorry, I encountered an error: {str(e)}")


async def send_weekly_digest(app: AsyncApp, channel_id: str):
    """Send weekly AWS news digest"""
    try:
        logger.info("Sending weekly AWS news digest")
        
        # Get this week's news
        from datetime import timedelta
        week_ago = (datetime.now() - timedelta(days=7)).isoformat() + 'Z'
        
        # Fetch latest news
        prompt = f"Please provide a summary of the most important AWS announcements from this week. Focus on major service launches, significant updates, and notable features."
        
        response = await chat_with_llm(prompt)
        
        # Send to channel
        await app.client.chat_postMessage(
            channel=channel_id,
            text=f":newspaper: *Weekly AWS News Digest* :newspaper:\n\n{response}",
            unfurl_links=False,
            unfurl_media=False
        )
        
        logger.info("Weekly digest sent successfully")
        
    except Exception as e:
        logger.error(f"Error sending weekly digest: {e}")


async def validate_azure_openai():
    """Validate Azure OpenAI connection"""
    logger.info("Validating Azure OpenAI connection...")
    try:
        # Test connection with a simple request
        response = azure_client.chat.completions.create(
            model=AZURE_DEPLOYMENT_NAME,
            messages=[{"role": "user", "content": "Hello"}],
            
        )
        
        if response.choices[0].message.content:
            logger.info("✅ Azure OpenAI connection successful")
            logger.info(f"   Model: {AZURE_DEPLOYMENT_NAME}")
            logger.info(f"   Endpoint: {os.environ.get('AZURE_OPENAI_ENDPOINT')}")
            return True
        else:
            logger.error("❌ Azure OpenAI connection failed: No response content")
            return False
            
    except Exception as e:
        logger.error(f"❌ Azure OpenAI connection failed: {type(e).__name__}: {str(e)}")
        return False


async def validate_mcp_server():
    """Validate MCP Server connection"""
    logger.info("Validating MCP Server connection...")
    try:
        # Test connection with the health endpoint first
        try:
            health_response = await mcp_client.client.get(f"{MCP_SERVER_URL}/health")
            if health_response.status_code == 200:
                logger.info(f"   Health endpoint: OK")
        except:
            logger.info(f"   Health endpoint: Not available")
        
        # Initialize MCP session per MCP specification
        init_success = await mcp_client.initialize()
        
        if not init_success:
            logger.error(f"❌ MCP Server connection failed: Initialization failed")
            return False
        
        # Test a tool call
        result = await mcp_client.call_tool("get_aws_feed_news", {"max_articles": 1})
        
        # Check if we got an error response
        if result.startswith("Error"):
            logger.error(f"❌ MCP Server connection failed: {result}")
            return False
        
        logger.info("✅ MCP Server connection successful")
        logger.info(f"   URL: {MCP_SERVER_URL}")
        logger.info(f"   Protocol: MCP Streamable HTTP (JSON-RPC 2.0)")
        if mcp_client.session_id:
            logger.info(f"   Session: {mcp_client.session_id[:16]}...")
        return True
            
    except httpx.ConnectError as e:
        logger.error(f"❌ MCP Server connection failed: Cannot connect to {MCP_SERVER_URL}")
        logger.error(f"   Error: Connection refused - ensure MCP server is running")
        return False
    except Exception as e:
        logger.error(f"❌ MCP Server connection failed: {type(e).__name__}: {str(e)}")
        return False


def setup_scheduler(app: AsyncApp):
    """Setup scheduled jobs"""
    scheduler = AsyncIOScheduler()
    
    # Get notification channel from environment
    notification_channel = os.environ.get("SLACK_NOTIFICATION_CHANNEL")
    
    if notification_channel:
        # Schedule weekly digest (every Monday at 9 AM)
        scheduler.add_job(
            send_weekly_digest,
            trigger=CronTrigger(day_of_week='mon', hour=9, minute=0),
            args=[app, notification_channel],
            id='weekly_digest',
            name='Weekly AWS News Digest',
            replace_existing=True
        )
        logger.info(f"Scheduled weekly digest for channel: {notification_channel}")
    else:
        logger.warning("SLACK_NOTIFICATION_CHANNEL not set, weekly digest disabled")
    
    scheduler.start()
    return scheduler


async def main():
    """Main entry point"""
    logger.info("=" * 70)
    logger.info("AWS News Slack Bot - Starting Up")
    logger.info("=" * 70)
    
    # Validate required environment variables
    logger.info("Checking environment variables...")
    required_vars = [
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT_NAME",
        "MCP_SERVER_URL"
    ]
    
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        return
    logger.info("✅ All required environment variables present")
    
    # Validate connections
    logger.info("")
    logger.info("Validating external connections...")
    logger.info("-" * 70)
    
    # Validate Azure OpenAI
    azure_ok = await validate_azure_openai()
    
    # Validate MCP Server
    logger.info("")
    mcp_ok = await validate_mcp_server()
    
    logger.info("-" * 70)
    
    # Check if all validations passed
    if not azure_ok or not mcp_ok:
        logger.error("")
        logger.error("❌ Connection validation failed. Please fix the issues above.")
        logger.error("   Bot will still start, but functionality may be limited.")
        logger.error("")
    else:
        logger.info("")
        logger.info("✅ All connections validated successfully")
        logger.info("")
    
    # Setup scheduler
    scheduler = setup_scheduler(app)
    
    try:
        logger.info("=" * 70)
        logger.info("Starting Slack Bot...")
        logger.info(f"MCP Server URL: {MCP_SERVER_URL}")
        logger.info(f"Azure OpenAI Deployment: {AZURE_DEPLOYMENT_NAME}")
        logger.info("=" * 70)
        logger.info("")
        logger.info("🤖 Bot is running! Press Ctrl+C to stop.")
        logger.info("")
        
        # Start the bot
        handler = AsyncSocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
        await handler.start_async()
        
    except KeyboardInterrupt:
        logger.info("")
        logger.info("Shutting down gracefully...")
        scheduler.shutdown()
    except Exception as e:
        logger.error(f"❌ Error starting bot: {e}")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

