#!/usr/bin/env bash
# ==============================================================================
# SentinelDR - Phone Node Bootstrap & Startup Script (Android Termux)
# Role: SECONDARY_STANDBY (Standard-library http.server, SQLite only, port 8001)
# ==============================================================================

set -euo pipefail

echo "===================================================================="
echo " SentinelDR - Phone Node (Termux / Android)"
echo " Architectural Constraint: Python Standard Library + SQLite ONLY"
echo "===================================================================="

# 1. Verify Python Installation
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed."
    echo "In Termux, install using: pkg update && pkg install python sqlite"
    exit 1
fi

PY_VER=$(python3 --version)
echo "[SentinelDR] Python environment: ${PY_VER}"

# 2. Strict Zero Third-Party Dependency Audit
echo "[SentinelDR] Running dependency audit..."
python3 -c "
import sys
forbidden = ['fastapi', 'pydantic', 'psycopg', 'psycopg2', 'requests', 'sqlalchemy', 'aiohttp', 'flask']
found = []
for pkg in forbidden:
    try:
        __import__(pkg)
        found.append(pkg)
    except ImportError:
        pass
if found:
    print(f'[FATAL] Forbidden packages found in Phone environment: {found}', file=sys.stderr)
    print('SentinelDR Phone node requires Python standard library ONLY. Do NOT use virtualenvs with third-party wheels.', file=sys.stderr)
    sys.exit(1)
print('[SentinelDR] Zero third-party dependency constraint verified successfully.')
"

# 3. Environment Configuration
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "[SentinelDR] Creating .env from .env.example..."
        cp .env.example .env
        echo "[IMPORTANT] Set SDR_HMAC_SECRET, SDR_ADMIN_KEY, and SDR_WITNESS_SECRET to match Laptop node!"
    fi
fi

# 4. Acquire Termux Wake-Lock to Prevent Doze / Deep Sleep
if command -v termux-wake-lock &> /dev/null; then
    echo "[SentinelDR] Acquiring Termux wake-lock (prevents background throttling)..."
    termux-wake-lock
    echo "[SentinelDR] Wake-lock active."
else
    echo "[NOTE] termux-wake-lock utility not found. If running in Termux, install termux-api: pkg install termux-api"
    echo "Ensure battery optimization is disabled for Termux in Android Settings."
fi

# 5. Initialize SQLite Database & Portfolio Seeds
echo "[SentinelDR] Initializing SQLite database and verifying seeds..."
python3 -c "
from phone.db import PhoneDatabase
from shared.config import NodeConfig
cfg = NodeConfig('phone')
db = PhoneDatabase(cfg.database_path)
db.seed_portfolio_data()
print('[SentinelDR] SQLite schema and portfolio data verified.')
"

# 6. Start Phone Server on Port 8001
echo "[SentinelDR] Launching SentinelDR Phone Server on port 8001..."
exec python3 -m phone.server
