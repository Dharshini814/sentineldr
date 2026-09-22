#!/bin/bash
# SentinelDR Phone Server - Termux Startup Script

echo "📱 Starting SentinelDR Phone Server..."
echo "════════════════════════════════════"

# Set Python path
export PYTHONPATH="/data/data/com.termux/files/home/sentineldr/backend"

# Check if we're in the right directory
if [ ! -f "phone_server.py" ]; then
    echo "❌ Error: phone_server.py not found!"
    echo "Please run from: ~/sentineldr/backend/phone/"
    exit 1
fi

# Check if config exists
if [ ! -f ".env.phone" ]; then
    echo "❌ Error: .env.phone not found!"
    echo "Please copy .env.phone.example to .env.phone and configure it"
    exit 1
fi

# Check Python version
python_version=$(python --version 2>&1)
echo "🐍 Using: $python_version"

# Acquire wake lock to prevent Android from sleeping
if command -v termux-wake-lock >/dev/null 2>&1; then
    echo "🔒 Acquiring wake lock..."
    termux-wake-lock
else
    echo "⚠️  Warning: termux-wake-lock not installed. Phone may sleep."
    echo "Install with: pkg install termux-wake-lock"
fi

# Get phone IP for reference
phone_ip=$(ifconfig wlan0 2>/dev/null | grep 'inet ' | awk '{print $2}' | head -1)
if [ -n "$phone_ip" ]; then
    echo "📡 Phone IP: $phone_ip:8001"
    echo "🌐 Test URL: http://$phone_ip:8001/health"
else
    echo "⚠️  Could not determine phone IP"
fi

echo ""
echo "🚀 Starting phone server..."
echo "Press Ctrl+C to stop"
echo ""

# Start the server
python phone_server.py