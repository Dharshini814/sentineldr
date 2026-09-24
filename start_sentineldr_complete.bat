@echo off
cls
echo.
echo ================================
echo    SentinelDR Complete System
echo ================================
echo.
echo Checking system status...
echo.

cd frontend
python test_complete_system.py

echo.
echo ================================
echo      Access Your Dashboard
echo ================================
echo.
echo Live Dashboard: http://localhost:5174
echo API Endpoints: http://localhost:8000/health
echo.
echo Press any key to open dashboard in browser...
pause > nul

start http://localhost:5174