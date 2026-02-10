#!/bin/bash
# FastAPI Server Restart Script

echo "========================================"
echo "FastAPI Server Restart"
echo "========================================"
echo ""

# Check if server is running on port 8000
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "Found server running on port 8000"
    echo ""
    echo "Stopping server..."
    pkill -f "uvicorn app.main:app"
    sleep 2
fi

echo "Starting FastAPI server..."
echo ""

python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
