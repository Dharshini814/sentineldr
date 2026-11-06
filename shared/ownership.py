"""
SentinelDR - Shared Ownership and Lease Module
Standard library only (runtime-neutral for Laptop & Phone).
"""

import hmac
import hashlib
import time
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, Tuple


@dataclass
class OwnershipRecord:
    cluster_id: str
    owner_node_id: str
    epoch: int
    lease_id: str
    lease_expires_at: float
    granted_by: str
    signature: str
    updated_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OwnershipRecord":
        return cls(
            cluster_id=str(data["cluster_id"]),
            owner_node_id=str(data["owner_node_id"]),
            epoch=int(data["epoch"]),
            lease_id=str(data["lease_id"]),
            lease_expires_at=float(data["lease_expires_at"]),
            granted_by=str(data["granted_by"]),
            signature=str(data["signature"]),
            updated_at=float(data.get("updated_at", time.time()))
        )


def compute_ownership_canonical(
    cluster_id: str,
    owner_node_id: str,
    epoch: int,
    lease_id: str,
    lease_expires_at: float,
    granted_by: str
) -> str:
    """Canonical string representation for ownership signing."""
    # Round lease_expires_at to 3 decimal places for deterministic cross-runtime representation
    ts_str = f"{lease_expires_at:.3f}"
    return f"{cluster_id}:{owner_node_id}:{epoch}:{lease_id}:{ts_str}:{granted_by}"


def sign_ownership_record(
    cluster_id: str,
    owner_node_id: str,
    epoch: int,
    lease_id: str,
    lease_expires_at: float,
    granted_by: str,
    secret: str
) -> str:
    """Generate HMAC-SHA256 signature for ownership record."""
    canonical = compute_ownership_canonical(
        cluster_id=cluster_id,
        owner_node_id=owner_node_id,
        epoch=epoch,
        lease_id=lease_id,
        lease_expires_at=lease_expires_at,
        granted_by=granted_by
    )
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def verify_ownership_signature(record: OwnershipRecord, secret: str) -> bool:
    """Verify ownership signature in constant time."""
    expected_sig = sign_ownership_record(
        cluster_id=record.cluster_id,
        owner_node_id=record.owner_node_id,
        epoch=record.epoch,
        lease_id=record.lease_id,
        lease_expires_at=record.lease_expires_at,
        granted_by=record.granted_by,
        secret=secret
    )
    return hmac.compare_digest(record.signature, expected_sig)


def validate_lease(
    record: Optional[OwnershipRecord],
    node_id: str,
    expected_epoch: int,
    expected_cluster_id: str,
    secret: str,
    now: Optional[float] = None,
    max_clock_skew: float = 1.0,
    witness_secret: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validate whether a node currently holds a valid, non-expired write lease.
    Bounded clock-skew policy: now + max_clock_skew must be strictly < lease_expires_at.
    """
    if record is None:
        return False, "NO_OWNERSHIP_RECORD"

    if record.cluster_id != expected_cluster_id:
        return False, f"CLUSTER_ID_MISMATCH: expected {expected_cluster_id}, got {record.cluster_id}"

    if record.owner_node_id != node_id:
        return False, f"NODE_NOT_OWNER: current owner is {record.owner_node_id}"

    if record.epoch != expected_epoch:
        return False, f"STALE_EPOCH: expected {expected_epoch}, got {record.epoch}"

    # Verify signature against witness_secret (if granted by witness) or secret
    is_witness_grant = bool(record.granted_by and (record.granted_by == "witness" or str(record.granted_by).startswith("witness")))
    target_secret = witness_secret if (is_witness_grant and witness_secret) else secret
    if not verify_ownership_signature(record, target_secret):
        if not verify_ownership_signature(record, secret):
            return False, "INVALID_SIGNATURE"

    current_time = now if now is not None else time.time()
    # Bounded clock skew guard: even with clock skew of up to max_clock_skew, lease must be valid
    if (current_time + max_clock_skew) >= record.lease_expires_at:
        return False, f"LEASE_EXPIRED: current={current_time:.3f}, skew_bound={current_time + max_clock_skew:.3f}, expires={record.lease_expires_at:.3f}"

    return True, None
