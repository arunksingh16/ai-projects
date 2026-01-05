#!/bin/bash
# Run script for AWS News Slack Bot

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found!"
    echo "Please copy .env.example to .env and configure your credentials."
    exit 1
fi

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "⚠️  Warning: Virtual environment not found. Run setup.sh first."
fi

# Load environment variables
echo "Loading environment variables..."
export $(cat .env | grep -v '^#' | xargs)

# Run the bot
echo "Starting AWS News Slack Bot..."
python bot.py

