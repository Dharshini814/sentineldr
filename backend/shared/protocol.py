# SentinelDR — Shared Protocol Dataclasses
# Standard library only: dataclasses, json, uuid, datetime, hashlib
# Every dataclass: to_dict() + from_dict(cls, d)

from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class DiscoveryPacket:
    """UDP broadcast packet used for peer discovery."""
    service: str
    protocol_version: int
    node_id: str
    role: str
    port: int
    timestamp: str  # ISO 8601

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "protocol_version": self.protocol_version,
            "node_id": self.node_id,
            "role": self.role,
            "port": self.port,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DiscoveryPacket":
        return cls(
            service=d["service"],
            protocol_version=d["protocol_version"],
            node_id=d["node_id"],
            role=d["role"],
            port=d["port"],
            timestamp=d["timestamp"],
        )


@dataclass
class HeartbeatPacket:
    """Periodic liveness signal sent from a node to its peer."""
    node_id: str
    role: str
    timestamp: str  # ISO 8601
    sequence: int
    status: str
    uptime_seconds: float

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "role": self.role,
            "timestamp": self.timestamp,
            "sequence": self.sequence,
            "status": self.status,
            "uptime_seconds": self.uptime_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HeartbeatPacket":
        return cls(
            node_id=d["node_id"],
            role=d["role"],
            timestamp=d["timestamp"],
            sequence=d["sequence"],
            status=d["status"],
            uptime_seconds=d["uptime_seconds"],
        )


@dataclass
class SyncSnapshot:
    """Full state snapshot pushed from PRIMARY to SECONDARY during sync."""
    version: int
    checksum: str
    timestamp: str  # ISO 8601
    source_node_id: str
    payload: dict   # e.g. {"projects": [...]}

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "checksum": self.checksum,
            "timestamp": self.timestamp,
            "source_node_id": self.source_node_id,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SyncSnapshot":
        return cls(
            version=d["version"],
            checksum=d["checksum"],
            timestamp=d["timestamp"],
            source_node_id=d["source_node_id"],
            payload=d["payload"],
        )


@dataclass
class NodeInfo:
    """Describes a node's current identity and health state."""
    node_id: str
    role: str
    host: str
    port: int
    status: str
    last_seen: Optional[str]  # ISO 8601 or None
    failover_active: bool
    uptime_seconds: float

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "role": self.role,
            "host": self.host,
            "port": self.port,
            "status": self.status,
            "last_seen": self.last_seen,
            "failover_active": self.failover_active,
            "uptime_seconds": self.uptime_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NodeInfo":
        return cls(
            node_id=d["node_id"],
            role=d["role"],
            host=d["host"],
            port=d["port"],
            status=d["status"],
            last_seen=d.get("last_seen"),
            failover_active=d["failover_active"],
            uptime_seconds=d["uptime_seconds"],
        )


@dataclass
class AlertEvent:
    """A system event or alert emitted by any node."""
    id: str          # UUID4 string
    event_type: str
    severity: str
    source: str
    message: str
    timestamp: str   # ISO 8601
    acknowledged: bool
    metadata: dict

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "severity": self.severity,
            "source": self.source,
            "message": self.message,
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AlertEvent":
        return cls(
            id=d["id"],
            event_type=d["event_type"],
            severity=d["severity"],
            source=d["source"],
            message=d["message"],
            timestamp=d["timestamp"],
            acknowledged=d["acknowledged"],
            metadata=d.get("metadata", {}),
        )
