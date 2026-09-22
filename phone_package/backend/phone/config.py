# SentinelDR — Phone Configuration
# Standard library ONLY. No pip packages. Runs on Android Termux.

import os
import time
import threading
from pathlib import Path


# ── .env parser ───────────────────────────────────────────────────────────────

def _load_env_file(path: Path) -> None:
    """
    Parse a .env file and populate os.environ with its values.
    Rules:
      - Blank lines and lines starting with # are skipped
      - Format: KEY=VALUE
      - Values may be wrapped in single or double quotes (stripped)
      - Existing environment variables are NOT overridden
    """
    if not path.exists():
        return

    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            # Skip blanks and comments
            if not line or line.startswith("#"):
                continue
            # Must contain '='
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes (single or double)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            # Do not override existing env vars
            if key and key not in os.environ:
                os.environ[key] = value


# Load .env.phone from the same directory as this file
_env_path = Path(__file__).parent / ".env.phone"
_load_env_file(_env_path)


# ── Config values ─────────────────────────────────────────────────────────────

NODE_ID: str = os.getenv("NODE_ID", "phone-node-02")
NODE_ROLE: str = os.getenv("NODE_ROLE", "secondary")
NODE_PORT: int = int(os.getenv("NODE_PORT", "8001"))
PEER_PORT: int = int(os.getenv("PEER_PORT", "8000"))

# REQUIRED — raises ValueError if missing or empty
_api_key = os.getenv("API_KEY", "").strip()
if not _api_key:
    raise ValueError(
        "API_KEY is required but not set. "
        "Add API_KEY=<your-key> to backend/phone/.env.phone. "
        "It must match the laptop's API_KEY exactly."
    )
API_KEY: str = _api_key

HEARTBEAT_INTERVAL: int = int(os.getenv("HEARTBEAT_INTERVAL", "3"))
HEARTBEAT_TIMEOUT: int = int(os.getenv("HEARTBEAT_TIMEOUT", "3"))
MISSED_HEARTBEAT_THRESHOLD: int = int(os.getenv("MISSED_HEARTBEAT_THRESHOLD", "3"))
SYNC_INTERVAL: int = int(os.getenv("SYNC_INTERVAL", "5"))
FAILOVER_COOLDOWN: int = int(os.getenv("FAILOVER_COOLDOWN", "30"))

DB_PATH: str = os.getenv("DB_PATH", "./sentineldr_phone.db")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


# ── Runtime state ─────────────────────────────────────────────────────────────
# Thread-safe dict-like object. Mutated by discovery, heartbeat, sync, failover
# daemon threads concurrently. Uses a lock for all reads and writes so that
# multi-step updates (e.g. failover_active + failover_time) are atomic.

def _initial_state() -> dict:
    return {
        "peer_host": None,
        "peer_node_id": None,
        "peer_role": None,
        "peer_status": "offline",
        "peer_last_seen": None,
        "missed_heartbeats": 0,
        "sync_version": 0,
        "last_sync_time": None,
        "last_sync_checksum": None,
        "failover_active": False,
        "failover_time": None,
        "start_time": time.time(),
        "heartbeat_sequence": 0,
    }


class RuntimeDict:
    """Thread-safe dict wrapper. Drop-in replacement for a plain dict."""

    def __init__(self, initial: dict):
        self._lock = threading.Lock()
        self._data = dict(initial)

    # ── dict protocol ─────────────────────────────
    def __getitem__(self, key):
        with self._lock:
            return self._data[key]

    def __setitem__(self, key, value):
        with self._lock:
            self._data[key] = value

    def __contains__(self, key):
        with self._lock:
            return key in self._data

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def update(self, mapping):
        with self._lock:
            self._data.update(mapping)

    def clear(self):
        with self._lock:
            self._data.clear()

    def keys(self):
        with self._lock:
            return list(self._data.keys())

    def items(self):
        with self._lock:
            return list(self._data.items())

    def values(self):
        with self._lock:
            return list(self._data.values())

    def __repr__(self):
        with self._lock:
            return f"RuntimeDict({self._data!r})"


runtime: RuntimeDict = RuntimeDict(_initial_state())


def reset_runtime() -> None:
    """Reset runtime to its initial values (re-stamps start_time)."""
    runtime.clear()
    runtime.update(_initial_state())
