@echo off
REM ============================================================================
REM SentinelDR - Laptop Node Bootstrap & Startup Script (Windows)
REM Role: PRIMARY_ACTIVE (PostgreSQL with SQLite fallback, port 8000)
REM ============================================================================

setlocal enabledelayedexpansion

echo [SentinelDR] Bootstrapping Laptop Node on Windows...

REM 1. Verify Python Installation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in system PATH.
    echo Please install Python 3.13+ from https://www.python.org/
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [SentinelDR] Detected Python version: %PY_VER%

REM 2. Setup Virtual Environment
if not exist ".venv" (
    echo [SentinelDR] Creating virtual environment (.venv)...
    python -m venv .venv
)

echo [SentinelDR] Activating virtual environment...
call .venv\Scripts\activate.bat

REM 3. Install Dependencies
echo [SentinelDR] Installing / verifying laptop dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

REM 4. Verify Environment Configuration
if not exist ".env" (
    echo [SentinelDR] Creating .env from .env.example...
    copy .env.example .env
    echo [IMPORTANT] Remember to configure SDR_HMAC_SECRET, SDR_ADMIN_KEY, and SDR_WITNESS_SECRET in .env!
)

REM 5. Initialize Database & Seed Portfolio Data
echo [SentinelDR] Initializing database and verifying portfolio data...
python -c "from laptop.db import LaptopDatabase; from shared.config import NodeConfig; cfg = NodeConfig('laptop'); db = LaptopDatabase(cfg.database_url, dev_fallback_sqlite=cfg.dev_db_fallback); db.init_db(); db.seed_portfolio_data(); print('[SentinelDR] Database schema and portfolio seeds verified.')"

REM 6. Run Test Suite Validation (Optional flag)
if "%1"=="--test" (
    echo [SentinelDR] Running test validation...
    python -m pytest tests/ -v
    if errorlevel 1 (
        echo [ERROR] Tests failed! Aborting startup.
        exit /b 1
    )
)

REM 7. Start Laptop Server
echo [SentinelDR] Starting SentinelDR Laptop Server on port 8000...
python -m laptop.server

endlocal
