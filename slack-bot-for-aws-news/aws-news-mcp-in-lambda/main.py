from typing import Optional
import feedparser
from mcp_lambda import McpLambdaServer

server = McpLambdaServer()

AWS_FEED = "https://aws.amazon.com/about-aws/whats-new/recent/feed/"

@server.tool()
def get_aws_feed_news(max_articles: int = 10, search_keywords: Optional[str] = None):
    feed = feedparser.parse(AWS_FEED)
    results = []

    for entry in feed.entries[:max_articles]:
        title = entry.get("title", "")
        link = entry.get("link", "")

        if search_keywords and search_keywords.lower() not in title.lower():
            continue

        results.append(f"- {title}\n  {link}")

    return "\n\n".join(results) or "No results"



def lambda_handler(event, context):
    return server.handle(event, context)
