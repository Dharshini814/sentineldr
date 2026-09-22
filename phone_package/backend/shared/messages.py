# SentinelDR — Message Builders
# Builder functions that construct the correct dicts for every message type.
# Standard library only.

import uuid
from datetime import datetime, timezone

from shared.constants import (
    SERVICE_NAME,
    PROTOCOL_VERSION,
    EVT_FAILOVER,
    EVT_RECOVERY,
    EVT_DISCOVERY,
    EVT_SYNC,
    SEV_CRITICAL,
    SEV_SUCCESS,
    SEV_INFO,
)
from shared.protocol import (
    DiscoveryPacket,
    HeartbeatPacket,
    SyncSnapshot,
    AlertEvent,
)


def _utc_now() -> str:
    """Return current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def build_discovery_packet(node_id: str, role: str, port: int) -> dict:
    """Build a UDP discovery broadcast packet dict."""
    pkt = DiscoveryPacket(
        service=SERVICE_NAME,
        protocol_version=PROTOCOL_VERSION,
        node_id=node_id,
        role=role,
        port=port,
        timestamp=_utc_now(),
    )
    return pkt.to_dict()


def build_heartbeat(
    node_id: str,
    role: str,
    sequence: int,
    status: str,
    uptime_seconds: float,
) -> dict:
    """Build a heartbeat packet dict."""
    pkt = HeartbeatPacket(
        node_id=node_id,
        role=role,
        timestamp=_utc_now(),
        sequence=sequence,
        status=status,
        uptime_seconds=uptime_seconds,
    )
    return pkt.to_dict()


def build_sync_snapshot(
    source_node_id: str,
    version: int,
    payload: dict,
    checksum: str,
) -> dict:
    """Build a sync snapshot dict."""
    snap = SyncSnapshot(
        version=version,
        checksum=checksum,
        timestamp=_utc_now(),
        source_node_id=source_node_id,
        payload=payload,
    )
    return snap.to_dict()


def build_event(
    event_type: str,
    severity: str,
    source: str,
    message: str,
    metadata: dict = None,
) -> dict:
    """Build a generic alert event dict with a freshly generated UUID."""
    evt = AlertEvent(
        id=str(uuid.uuid4()),
        event_type=event_type,
        severity=severity,
        source=source,
        message=message,
        timestamp=_utc_now(),
        acknowledged=False,
        metadata=metadata or {},
    )
    return evt.to_dict()


def build_failover_alert(source_node_id: str) -> dict:
    """Emit a CRITICAL failover alert when the primary goes offline."""
    return build_event(
        event_type=EVT_FAILOVER,
        severity=SEV_CRITICAL,
        source=source_node_id,
        message="Primary node unavailable. Phone recovery node activated.",
    )


def build_recovery_alert(source_node_id: str) -> dict:
    """Emit a SUCCESS recovery alert when the primary comes back online."""
    return build_event(
        event_type=EVT_RECOVERY,
        severity=SEV_SUCCESS,
        source=source_node_id,
        message="Primary node restored. System returning to normal operation.",
    )


def build_discovery_event(
    source_node_id: str,
    peer_node_id: str,
    peer_ip: str,
) -> dict:
    """Emit an INFO event when a peer node is discovered on the network."""
    return build_event(
        event_type=EVT_DISCOVERY,
        severity=SEV_INFO,
        source=source_node_id,
        message=f"Peer {peer_node_id} discovered at {peer_ip}",
    )


def build_sync_event(
    source_node_id: str,
    version: int,
    project_count: int,
) -> dict:
    """Emit an INFO event when a sync snapshot is applied."""
    return build_event(
        event_type=EVT_SYNC,
        severity=SEV_INFO,
        source=source_node_id,
        message=f"Sync snapshot v{version} applied \u2014 {project_count} projects",
    )
