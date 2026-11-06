"""
SentinelDR - Shared API Contract Module
Standard library only (runtime-neutral for Laptop & Phone).
"""

from typing import Dict, Any, List

# Ten Cluster States
STATE_STARTING = "STARTING"
STATE_PRIMARY_ACTIVE = "PRIMARY_ACTIVE"
STATE_SECONDARY_STANDBY = "SECONDARY_STANDBY"
STATE_SUSPECTED_OFFLINE = "SUSPECTED_OFFLINE"
STATE_PROMOTION_PENDING = "PROMOTION_PENDING"
STATE_SECONDARY_ACTIVE = "SECONDARY_ACTIVE"
STATE_RECOVERING = "RECOVERING"
STATE_RECONCILING = "RECONCILING"
STATE_FAILBACK_PENDING = "FAILBACK_PENDING"
STATE_SAFE_MODE = "SAFE_MODE"

ALL_STATES = {
    STATE_STARTING,
    STATE_PRIMARY_ACTIVE,
    STATE_SECONDARY_STANDBY,
    STATE_SUSPECTED_OFFLINE,
    STATE_PROMOTION_PENDING,
    STATE_SECONDARY_ACTIVE,
    STATE_RECOVERING,
    STATE_RECONCILING,
    STATE_FAILBACK_PENDING,
    STATE_SAFE_MODE,
}

# Canonical Endpoints
ROUTE_HEALTH = "/health"
ROUTE_READY = "/ready"
ROUTE_STATUS = "/api/v1/status"
ROUTE_METRICS = "/api/v1/metrics"
ROUTE_EVENTS = "/api/v1/events"
ROUTE_PEER_HEARTBEAT = "/api/v1/peer/heartbeat"
ROUTE_PEER_REPLICATE = "/api/v1/peer/replicate"
ROUTE_PEER_LEASE_REQUEST = "/api/v1/peer/lease/request"
ROUTE_PEER_FAILOVER = "/api/v1/peer/failover"
ROUTE_PEER_RECOVERY_START = "/api/v1/peer/recovery/start"
ROUTE_PEER_RECOVERY_COMPLETE = "/api/v1/peer/recovery/complete"
ROUTE_PEER_FAILBACK = "/api/v1/peer/failback"
ROUTE_PEER_CHANGES = "/api/v1/peer/changes"
ROUTE_DASHBOARD_STATUS = "/api/v1/dashboard/status"
ROUTE_DASHBOARD_EVENTS = "/api/v1/dashboard/events"
ROUTE_ACTIVE_ORIGIN = "/api/v1/active-origin"

# Approved Frontend Origins for Restricted CORS (No Wildcard with Credentials)
ALLOWED_ORIGINS = {
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
    "https://portfolio.sentineldr.in",
    "https://primary-origin.sentineldr.in",
    "https://backup-origin.sentineldr.in",
}




def validate_status_payload(payload: Dict[str, Any]) -> List[str]:
    """Validate that status payload adheres to SentinelDR specification."""
    errors = []
    required_keys = ["node_id", "node_type", "role", "epoch", "db_ready", "cluster_id"]
    for k in required_keys:
        if k not in payload:
            errors.append(f"Missing required field in status: {k}")
    if "role" in payload and payload["role"] not in ALL_STATES:
        errors.append(f"Invalid role state: {payload['role']}")
    return errors


def validate_health_payload(payload: Dict[str, Any]) -> List[str]:
    """Validate that health payload adheres to SentinelDR specification."""
    errors = []
    required_keys = ["status", "db_ready", "node_id"]
    for k in required_keys:
        if k not in payload:
            errors.append(f"Missing required field in health: {k}")
    return errors


def validate_readiness_payload(payload: Dict[str, Any]) -> List[str]:
    """Validate that readiness payload adheres to SentinelDR specification."""
    errors = []
    required_keys = ["ready", "status", "db_healthy", "role", "node_id"]
    for k in required_keys:
        if k not in payload:
            errors.append(f"Missing required field in readiness: {k}")
    return errors



def validate_active_origin_payload(payload: Dict[str, Any]) -> List[str]:
    """Validate that active-origin payload adheres to SentinelDR specification."""
    errors = []
    required_keys = [
        "node_id",
        "role",
        "epoch",
        "writable",
        "lease_valid",
        "owner_node_id",
        "cluster_id",
    ]
    for k in required_keys:
        if k not in payload:
            errors.append(f"Missing required field in active-origin: {k}")
    if "role" in payload and payload["role"] not in ALL_STATES:
        errors.append(f"Invalid role state: {payload['role']}")
    return errors

