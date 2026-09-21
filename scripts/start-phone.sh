#!/bin/bash
# Run this command once to make this script executable:
# chmod +x scripts/start-laptop.sh
# chmod +x scripts/start-phone.sh

# SentinelDR Phone Secondary Node Startup Script
# Run inside Termux on Android
# No pip installs required — standard library only

echo "Starting SentinelDR Phone Secondary Node..."

# Check if .env.phone exists
if [ ! -f "backend/phone/.env.phone" ]; then
    echo "ERROR: Configuration file not found"
    echo "Please create backend/phone/.env.phone first"
    echo "Copy from backend/phone/.env.phone.example and edit"
    exit 1
fi

# Check if Python is available
if ! command -v python &> /dev/null; then
    echo "ERROR: Python not found"
    echo "In Termux, install with: pkg install python"
    exit 1
fi

# Change to backend directory
cd backend || exit 1

# Set Python path for imports
export PYTHONPATH=.

echo "Server will be available at http://0.0.0.0:8001"
echo "Health check: http://localhost:8001/health"
echo "Press Ctrl+C to stop."
echo ""

# Start the phone server (standard library only)
python -m phone.phone_server