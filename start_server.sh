#!/bin/bash

# mAIrble Backend Startup Script
echo "🚀 Starting mAIrble Backend Server..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo "📋 Please copy config.example.env to .env and add your API keys:"
    echo "   cp config.example.env .env"
    echo "   nano .env"
    exit 1
fi

# Check if required environment variables are set
source .env

if [ -z "$PRICELABS_API_KEY" ]; then
    echo "❌ PRICELABS_API_KEY not set in .env file"
    exit 1
fi

if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ OPENAI_API_KEY not set in .env file"
    exit 1
fi

# Set default values if not provided
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8000}

echo "✅ Environment variables loaded"
echo "🔧 Starting server on http://$HOST:$PORT"

# Start the server
uvicorn app:app --host $HOST --port $PORT --reload 