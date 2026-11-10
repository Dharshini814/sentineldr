"""
SentinelDR - Shared Configuration Module
Standard library only (runtime-neutral for Laptop & Phone).
"""

import os
import sys
from typing import Dict, Optional


def load_env_file(filepath: str) -> Dict[str, str]:
    """Parse a .env file using standard library only."""
    env_vars = {}
    if not os.path.exists(filepath):
        return env_vars
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    env_vars[key] = val
                    if key not in os.environ:
                        os.environ[key] = val
    except Exception:
        pass
    return env_vars


class NodeConfig:
    """Runtime configuration for a SentinelDR node."""

    def __init__(self, node_type: str = "laptop", env_file: Optional[str] = None):
        self.node_type = node_type.lower()
        if env_file:
            load_env_file(env_file)
        else:
            # Try default locations
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            specific_env = os.path.join(base_dir, self.node_type, ".env")
            root_env = os.path.join(base_dir, ".env")
            if os.path.exists(specific_env):
                load_env_file(specific_env)
            elif os.path.exists(root_env):
                load_env_file(root_env)

        self.cluster_id: str = os.getenv("SDR_CLUSTER_ID", "sentineldr-cluster-01")
        default_node_id = "laptop" if self.node_type == "laptop" else "phone"
        self.node_id: str = os.getenv("SDR_NODE_ID", default_node_id)
        
        default_port = 8000 if self.node_type == "laptop" else 8001
        self.port: int = int(os.getenv("SDR_PORT", str(default_port)))
        self.host: str = os.getenv("SDR_HOST", "0.0.0.0")

        default_role = "PRIMARY_ACTIVE" if self.node_type == "laptop" else "SECONDARY_STANDBY"
        self.initial_role: str = os.getenv("SDR_INITIAL_ROLE", default_role)
        self.epoch: int = int(os.getenv("SDR_INITIAL_EPOCH", "1"))

        default_peer_url = "http://127.0.0.1:8001" if self.node_type == "laptop" else "http://127.0.0.1:8000"
        self.peer_url: str = os.getenv("SDR_PEER_URL", default_peer_url)

        # Secrets (Must be distinct in production)
        self.hmac_secret: str = os.getenv("SDR_HMAC_SECRET", "sdr-dev-hmac-secret-change-in-prod-001")
        self.admin_key: str = os.getenv("SDR_ADMIN_KEY", "sdr-dev-admin-key-change-in-prod-002")

        # Security tuning
        self.timestamp_window_seconds: float = float(os.getenv("SDR_TIMESTAMP_WINDOW_SECONDS", "30.0"))
        
        # Witness & Clock Skew Configuration (Phase 5)
        self.witness_url: str = os.getenv("SDR_WITNESS_URL", "http://127.0.0.1:8002")
        self.witness_secret: str = os.getenv("SDR_WITNESS_SECRET", self.hmac_secret)
        self.max_clock_skew: float = float(os.getenv("SDR_MAX_CLOCK_SKEW", "2.0"))

        # Database
        if self.node_type == "laptop":
            self.database_url: str = os.getenv("DATABASE_URL", "postgresql://sentinel:sentinel@localhost:5432/sentineldr")
            self.dev_db_fallback: bool = os.getenv("SDR_DEV_FALLBACK_SQLITE", "0").lower() in ("1", "true", "yes")
        else:
            self.database_path: str = os.getenv("SDR_SQLITE_PATH", os.path.join(os.getcwd(), "phone_sentineldr.db"))

        # Nonce cache DB
        self.nonce_cache_db: str = os.getenv(
            "SDR_NONCE_CACHE_DB",
            os.path.join(os.getcwd(), f"{self.node_id}_nonce_cache.db")
        )

        # Alert & SMTP Configuration
        self.alert_channel: str = os.getenv("SDR_ALERT_CHANNEL", "email")
        self.smtp_host: str = os.getenv("SDR_SMTP_HOST", "smtp.gmail.com")
        raw_port = os.getenv("SDR_SMTP_PORT", "465")
        try:
            self.smtp_port: int = int(raw_port)
        except (ValueError, TypeError):
            self.smtp_port = 465
        self.smtp_user: str = os.getenv("SDR_SMTP_USER", "")
        self.smtp_password: str = os.getenv("SDR_SMTP_APP_PASSWORD", "")
        self.admin_alert_email: str = os.getenv("SDR_ADMIN_ALERT_EMAIL", "")

    def to_dict(self) -> dict:
        """Return safe configuration dictionary with secrets redacted."""
        return {
            "cluster_id": self.cluster_id,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "host": self.host,
            "port": self.port,
            "initial_role": self.initial_role,
            "epoch": self.epoch,
            "peer_url": self.peer_url,
            "timestamp_window_seconds": self.timestamp_window_seconds,
            "secrets_configured": bool(self.hmac_secret and self.admin_key),
            "smtp_configured": bool(self.smtp_user and self.smtp_password and self.admin_alert_email),
            "hmac_secret": "***REDACTED***",
            "admin_key": "***REDACTED***",
            "smtp_password": "***REDACTED***" if self.smtp_password else "",
        }
