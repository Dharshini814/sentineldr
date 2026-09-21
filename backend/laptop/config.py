import time
import threading
import logging
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Settings ──────────────────────────────────────────────────────────────────

class Settings(BaseSettings):

    # Node identity
    NODE_ID: str = "laptop-node-01"
    NODE_ROLE: str = "primary"
    NODE_PORT: int = 8000

    # Peer — IP is never configured here, only the port
    PEER_PORT: int = 8001

    # Security — REQUIRED, no defaults, missing raises ValidationError
    API_KEY: str
    DATABASE_URL: str

    # Timing
    HEARTBEAT_INTERVAL: int = 3
    HEARTBEAT_TIMEOUT: int = 3
    MISSED_HEARTBEAT_THRESHOLD: int = 3
    SYNC_INTERVAL: int = 5
    FAILOVER_COOLDOWN: int = 30

    # Frontend
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env.laptop",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


# Singleton — imported by all laptop modules
settings = Settings()


# ── RuntimeState ──────────────────────────────────────────────────────────────
# Holds live state discovered at runtime — never from .env
# Thread-safe — mutated by discovery, heartbeat, sync, failover services

class RuntimeState:
    def __init__(self):
        self._lock = threading.Lock()

        # Peer discovery — populated by DiscoveryService
        self.peer_host: Optional[str] = None
        self.peer_node_id: Optional[str] = None
        self.peer_role: Optional[str] = None

        # Peer health — updated by HeartbeatService
        self.peer_status: str = "offline"
        self.peer_last_seen: Optional[float] = None
        self.missed_heartbeats: int = 0

        # Sync — updated by SyncService
        self.sync_version: int = 0
        self.last_sync_time: Optional[float] = None
        self.last_sync_checksum: Optional[str] = None

        # Failover
        self.failover_active: bool = False
        self.failover_time: Optional[float] = None

        # Uptime
        self.start_time: float = time.time()

        # Heartbeat counter
        self.heartbeat_sequence: int = 0

    # ── Getters ───────────────────────────────────────────────────────────────

    def get_uptime(self) -> float:
        return time.time() - self.start_time

    def get_peer_url(self, peer_port: int) -> Optional[str]:
        with self._lock:
            if self.peer_host is None:
                return None
            return f"http://{self.peer_host}:{peer_port}"

    # ── Mutators ──────────────────────────────────────────────────────────────

    def update_peer_discovered(self, host: str, node_id: str, role: str):
        with self._lock:
            self.peer_host = host
            self.peer_node_id = node_id
            self.peer_role = role

    def update_peer_healthy(self):
        with self._lock:
            self.peer_last_seen = time.time()
            self.peer_status = "healthy"
            self.missed_heartbeats = 0

    def increment_missed_heartbeat(self) -> int:
        with self._lock:
            self.missed_heartbeats += 1
            return self.missed_heartbeats

    def mark_peer_offline(self):
        with self._lock:
            self.peer_status = "offline"

    def update_sync(self, version: int, checksum: str):
        with self._lock:
            self.sync_version = version
            self.last_sync_time = time.time()
            self.last_sync_checksum = checksum

    def set_failover(self, active: bool):
        with self._lock:
            # Laptop should never enter failover mode - it's always primary
            self.failover_active = False  # Force false for laptop
            if active:  # Only set timestamp if requested (for compatibility)
                self.failover_time = time.time()

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        with self._lock:
            last_sync_iso = None
            if self.last_sync_time is not None:
                from datetime import datetime, timezone
                last_sync_iso = datetime.fromtimestamp(
                    self.last_sync_time, tz=timezone.utc
                ).isoformat()
            return {
                "peer_host": self.peer_host,
                "peer_node_id": self.peer_node_id,
                "peer_role": self.peer_role,
                "peer_status": self.peer_status,
                "peer_last_seen": self.peer_last_seen,
                "missed_heartbeats": self.missed_heartbeats,
                "sync_version": self.sync_version,
                "last_sync_time": last_sync_iso,
                "last_sync_checksum": self.last_sync_checksum,
                "failover_active": False,  # Laptop never reports failover active
                "failover_time": self.failover_time,
                "uptime_seconds": self.get_uptime(),
                "heartbeat_sequence": self.heartbeat_sequence,
            }


# Singleton — imported by all laptop modules
runtime = RuntimeState()
