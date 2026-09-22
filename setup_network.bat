@echo off
echo 📱 SentinelDR Auto Network Configuration
echo =====================================

cd /d "%~dp0"

echo 🔍 Detecting network configuration...
python auto_network_setup.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ✅ Network configuration completed!
    echo.
    echo 🚀 Would you like to start all servers now? (Y/N)
    set /p choice="Enter choice: "
    
    if /i "%choice%"=="Y" (
        echo.
        echo 🖥️ Starting laptop server...
        start "SentinelDR Laptop" cmd /k "cd backend && uvicorn laptop.main:app --host 0.0.0.0 --port 8000 --reload"
        
        timeout /t 3 >nul
        
        echo 📱 Starting phone server...
        start "SentinelDR Phone" cmd /k "cd backend && set PYTHONPATH=%cd%\backend && python phone/phone_server.py"
        
        timeout /t 3 >nul
        
        echo 🌐 Starting frontend...
        start "SentinelDR Frontend" cmd /k "cd frontend && npm run dev"
        
        timeout /t 2 >nul
        
        echo 🔗 Starting smart proxy...
        start "SentinelDR Proxy" cmd /k "cd backend && python smart_proxy.py"
        
        echo.
        echo ✅ All servers starting up!
        echo 📊 Check the opened terminal windows for status
    )
) else (
    echo ❌ Network configuration failed!
)

echo.
pause