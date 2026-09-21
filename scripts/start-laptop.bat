@echo off
REM SentinelDR Laptop Primary Node Startup Script
REM Windows batch script

echo Starting SentinelDR Laptop Primary Node...

REM Check if .env.laptop exists
if not exist "backend\laptop\.env.laptop" (
    echo ERROR: Configuration file not found
    echo Please create backend\laptop\.env.laptop first
    echo Copy from backend\laptop\.env.laptop.example and edit
    pause
    exit /b 1
)

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    echo Please install Python 3.11+ and add to PATH
    pause
    exit /b 1
)

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Change to backend directory
cd /d "backend"

REM Set Python path for imports
set PYTHONPATH=.

echo API will be available at http://localhost:8000
echo Health check: http://localhost:8000/health
echo Press Ctrl+C to stop.
echo.

REM Start the FastAPI application with uvicorn
uvicorn laptop.main:app --host 0.0.0.0 --port 8000 --reload