"""
SentinelDR - Shared Heartbeat Module
Standard library only (runtime-neutral for Laptop & Phone).
"""

import threading
import time
from typing import Any, Dict, Optional, Tuple


class HeartbeatTracker:
    """
    Tracks peer heartbeats on the receiver node using the receiver's OWN clock.
    Tracks consecutive misses and detects peer health degradation.
    """

    def __init__(self, expected_interval: float = 3.0, miss_threshold: int = 3):
        self.expected_interval = expected_interval
        self.miss_threshold = miss_threshold
        self.last_received_at: Optional[float] = None
        self.consecutive_misses: int = 0
        self.last_payload: Optional[Dict[str, Any]] = None
        self._lock = threading.RLock()

    def record_heartbeat(self, payload: Dict[str, Any]) -> float:
        """
        Record a received heartbeat with receiver's clock.
        Resets consecutive misses and stores peer status.
        """
        now = time.time()
        with self._lock:
            self.last_received_at = now
            self.consecutive_misses = 0
            self.last_payload = payload
        return now

    def evaluate_misses(self) -> int:
        """
        Evaluate how many expected heartbeats have been missed based on receiver clock.
        """
        now = time.time()
        with self._lock:
            if self.last_received_at is None:
                return self.consecutive_misses

            elapsed = now - self.last_received_at
            if elapsed > self.expected_interval:
                misses = int(elapsed // self.expected_interval)
                self.consecutive_misses = misses
            else:
                self.consecutive_misses = 0
            return self.consecutive_misses

    def is_suspected_offline(self) -> bool:
        """Returns True if peer has missed >= miss_threshold consecutive heartbeats."""
        return self.evaluate_misses() >= self.miss_threshold

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic status of peer heartbeat."""
        now = time.time()
        with self._lock:
            last_ts = self.last_received_at
            misses = self.evaluate_misses()
            elapsed = (now - last_ts) if last_ts else None
            return {
                "last_received_at": last_ts,
                "elapsed_seconds": round(elapsed, 2) if elapsed is not None else None,
                "expected_interval": self.expected_interval,
                "consecutive_misses": misses,
                "suspected_offline": misses >= self.miss_threshold,
                "last_sender_epoch": self.last_payload.get("epoch") if self.last_payload else None,
                "last_sender_state": self.last_payload.get("sender_state") if self.last_payload else None,
                "last_sender_seq": self.last_payload.get("last_committed_sequence") if self.last_payload else None,
            }


def build_heartbeat_payload(
    cluster_id: str,
    sender_node_id: str,
    sender_state: str,
    epoch: int,
    lease_id: str,
    last_committed_sequence: int,
    database_health: str = "HEALTHY"
) -> Dict[str, Any]:
    """Construct standard heartbeat payload."""
    return {
        "protocol_version": "1.0.0",
        "cluster_id": cluster_id,
        "sender_node_id": sender_node_id,
        "sender_state": sender_state,
        "epoch": epoch,
        "lease_id": lease_id,
        "sent_at": time.time(),
        "last_committed_sequence": last_committed_sequence,
        "database_health": database_health
    }


def validate_heartbeat_payload(payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate structure of incoming heartbeat payload."""
    required = [
        "protocol_version", "cluster_id", "sender_node_id",
        "sender_state", "epoch", "lease_id", "sent_at",
        "last_committed_sequence", "database_health"
    ]
    for key in required:
        if key not in payload:
            return False, f"Missing required field in heartbeat: {key}"
    return True, None
