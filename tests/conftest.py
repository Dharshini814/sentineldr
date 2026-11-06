"""
SentinelDR Pytest Global Configuration
Ensures test fixtures have access to the SQLite development fallback when running
unit/integration suites on development machines without a local PostgreSQL daemon.
"""

import os
import sys

# Default test runs to explicit SQLite dev fallback unless PostgreSQL is configured
os.environ.setdefault("SDR_DEV_FALLBACK_SQLITE", "1")
