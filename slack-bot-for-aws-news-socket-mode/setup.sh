#!/bin/bash
# Setup script for AWS News Slack Bot

echo "🚀 AWS News Slack Bot Setup"
echo "============================="
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Found Python $python_version"

# Create virtual environment
echo ""
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Copy environment file if it doesn't exist
if [ ! -f .env ]; then
    echo ""
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "✅ Created .env file - PLEASE EDIT IT WITH YOUR CREDENTIALS"
else
    echo ""
    echo "⚠️  .env file already exists, skipping..."
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env file with your credentials:"
echo "   - Slack tokens (SLACK_BOT_TOKEN, SLACK_APP_TOKEN)"
echo "   - Azure OpenAI credentials"
echo "   - MCP Server URL"
echo ""
echo "2. Run the bot:"
echo "   source venv/bin/activate  # if not already activated"
echo "   python bot.py"
echo ""

