#!/bin/bash
# Run this command once to make this script executable:
# chmod +x scripts/start-laptop.sh
# chmod +x scripts/start-phone.sh

# SentinelDR Laptop Primary Node Startup Script
# Linux/Mac bash script

echo "Starting SentinelDR Laptop Primary Node..."

# Check if .env.laptop exists
if [ ! -f "backend/laptop/.env.laptop" ]; then
    echo "ERROR: Configuration file not found"
    echo "Please create backend/laptop/.env.laptop first"
    echo "Copy from backend/laptop/.env.laptop.example and edit"
    exit 1
fi

# Check if Python is available
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "ERROR: Python not found in PATH"
    echo "Please install Python 3.11+ and add to PATH"
    exit 1
fi

# Use python3 if available, otherwise python
if command -v python3 &> /dev/null; then
    PYTHON_CMD=python3
else
    PYTHON_CMD=python
fi

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Change to backend directory
cd backend || exit 1

# Set Python path for imports
export PYTHONPATH=.

echo "API will be available at http://localhost:8000"
echo "Health check: http://localhost:8000/health"
echo "Press Ctrl+C to stop."
echo ""

# Start the FastAPI application with uvicorn
uvicorn laptop.main:app --host 0.0.0.0 --port 8000 --reload