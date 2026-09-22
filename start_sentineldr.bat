@echo off
echo 🚀 Starting SentinelDR with Auto IP Detection
echo ═══════════════════════════════════════════

cd /d "%~dp0"

echo 📡 Servers will automatically detect network IP address
echo 🔧 Frontend .env will be auto-updated by laptop server
echo.

echo 🖥️ Starting Laptop Server (Primary)...
start "SentinelDR Laptop" cmd /k "cd backend && uvicorn laptop.main:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 5 >nul

echo 📱 Starting Phone Server (Secondary)...
start "SentinelDR Phone" cmd /k "cd backend && set PYTHONPATH=%cd%\backend && python phone/phone_server.py"

timeout /t 3 >nul

echo 🌐 Starting Frontend...
start "SentinelDR Frontend" cmd /k "cd frontend && npm run dev"

timeout /t 3 >nul

echo 🔗 Starting Smart Proxy...
start "SentinelDR Proxy" cmd /k "cd backend && python smart_proxy.py"

echo.
echo ✅ All SentinelDR components starting...
echo 📊 Check the terminal windows for status
echo 🌐 Frontend will auto-connect to detected IP addresses
echo.
echo 💡 The system will automatically adapt when you:
echo    - Switch to phone WiFi hotspot
echo    - Change networks
echo    - Connect to different WiFi
echo.
pause