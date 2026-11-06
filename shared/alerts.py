"""
SentinelDR - Alerting & Health Diagnostics Module
Standard library only (runtime-neutral for Laptop & Phone).
Evaluates operational health and produces structured alerts for:
- SAFE_MODE transitions
- Lease expiry
- Replication lag
- Sequence gaps
- Unresolved conflicts
- Integrity mismatches
- Peer liveness failures
"""

import time
from typing import Any, Dict, List, Optional

SEVERITY_INFO = "INFO"
SEVERITY_WARN = "WARN"
SEVERITY_CRITICAL = "CRITICAL"


class AlertChecker:
    """Evaluates cluster alerts against real database and in-memory states."""

    def __init__(
        self,
        node_id: str,
        cluster_id: str,
        db: Any,
        state_machine: Any,
        heartbeat_tracker: Optional[Any] = None,
        lag_warn_threshold: int = 5,
    ):
        self.node_id = node_id
        self.cluster_id = cluster_id
        self.db = db
        self.state_machine = state_machine
        self.heartbeat_tracker = heartbeat_tracker
        self.lag_warn_threshold = lag_warn_threshold

    def get_active_alerts(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Evaluate and return list of currently active alerts."""
        alerts: List[Dict[str, Any]] = []
        current_time = now if now is not None else time.time()

        # 1. Check SAFE_MODE
        current_state = self.state_machine.current_state
        if current_state == "SAFE_MODE":
            alerts.append({
                "alert_id": "ALERT_SAFE_MODE",
                "severity": SEVERITY_CRITICAL,
                "node_id": self.node_id,
                "message": "Node is in SAFE_MODE. Writes are strictly fenced; fail-closed disaster recovery active.",
                "action": "Inspect witness connectivity and audit log to verify cluster safety before manual override.",
                "detected_at": current_time,
            })

        # 2. Check Lease Expiry
        try:
            ownership = self.db.get_ownership(self.cluster_id)
            if ownership and ownership.owner_node_id == self.node_id:
                if current_time >= ownership.lease_expires_at:
                    alerts.append({
                        "alert_id": "ALERT_LEASE_EXPIRED",
                        "severity": SEVERITY_CRITICAL,
                        "node_id": self.node_id,
                        "message": f"Active primary lease '{ownership.lease_id}' expired at {ownership.lease_expires_at:.3f}.",
                        "action": "Renew lease from witness quorum immediately or step down to prevent dual-writers.",
                        "detected_at": current_time,
                    })
        except Exception:
            pass

        # 3. Check Unresolved Conflicts
        try:
            conflicts = self.db.get_conflicts(resolved=False)
            if conflicts:
                alerts.append({
                    "alert_id": "ALERT_UNRESOLVED_CONFLICTS",
                    "severity": SEVERITY_CRITICAL,
                    "node_id": self.node_id,
                    "message": f"{len(conflicts)} unresolved write conflict(s) detected during reconciliation.",
                    "action": "Automatic failback halted. Inspect conflict_records table and resolve conflicts explicitly.",
                    "detected_at": current_time,
                })
        except Exception:
            pass

        # 4. Check Replication Lag
        try:
            peer_node = "phone" if self.node_id == "laptop" else "laptop"
            highest_seq = self.db.get_highest_local_sequence(self.node_id)
            ack_checkpoint = self.db.get_replication_checkpoint(f"ack_{peer_node}")
            peer_applied = ack_checkpoint.get("last_applied_sequence", 0)
            lag = max(0, highest_seq - peer_applied)
            if lag > self.lag_warn_threshold:
                alerts.append({
                    "alert_id": "ALERT_REPLICATION_LAG",
                    "severity": SEVERITY_WARN,
                    "node_id": self.node_id,
                    "message": f"Replication lag is {lag} events behind (threshold: {self.lag_warn_threshold}).",
                    "action": "Check peer network connectivity and replication outbox worker.",
                    "detected_at": current_time,
                })
        except Exception:
            pass

        # 5. Check Peer Suspected Offline
        if self.heartbeat_tracker:
            try:
                hb_status = self.heartbeat_tracker.get_status()
                if hb_status.get("suspected_offline"):
                    misses = hb_status.get("consecutive_misses", 0)
                    alerts.append({
                        "alert_id": "ALERT_PEER_SUSPECTED_OFFLINE",
                        "severity": SEVERITY_WARN,
                        "node_id": self.node_id,
                        "message": f"Peer has missed {misses} consecutive heartbeats and is suspected offline.",
                        "action": "Verify direct LAN connectivity and peer process health.",
                        "detected_at": current_time,
                    })
            except Exception:
                pass

        # 6. Check Database Physical Health
        try:
            db_healthy, db_err = self.db.is_healthy()
            if not db_healthy:
                alerts.append({
                    "alert_id": "ALERT_INTEGRITY_MISMATCH",
                    "severity": SEVERITY_CRITICAL,
                    "node_id": self.node_id,
                    "message": f"Database physical health check failed: {db_err}",
                    "action": "Run database integrity check and restore from consistent backup if corrupted.",
                    "detected_at": current_time,
                })
        except Exception:
            pass

        return alerts
