@echo off
cls
echo.
echo ================================
echo   SentinelDR Dashboard Server
echo ================================
echo.
echo Starting production-ready dashboard with live backend integration...
echo.

cd /d "%~dp0"
python start_sentineldr_dashboard.py

pause