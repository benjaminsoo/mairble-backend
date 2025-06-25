#!/bin/bash

# Simple mAIrble Backend Startup (No .env needed)
echo "🚀 Starting mAIrble Backend Server (No .env mode)..."

# Check if uvicorn is available
if ! command -v uvicorn &> /dev/null; then
    echo "❌ uvicorn not found. Please install requirements:"
    echo "   pip install -r requirements.txt"
    exit 1
fi

echo "✅ All dependencies available"
echo "🔧 Starting server on all interfaces (0.0.0.0:8000)"
echo "📱 React Native can connect via: http://172.16.17.32:8000"
echo "💻 Desktop browsers can use: http://127.0.0.1:8000"
echo "📝 All configuration is hardcoded in app.py"

# Start the server on all interfaces so React Native can connect
uvicorn app:app --host 0.0.0.0 --port 8000 --reload 