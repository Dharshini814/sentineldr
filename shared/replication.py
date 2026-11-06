"""
SentinelDR - Shared Replication Protocol & Utilities
Standard library only (runtime-neutral for Laptop & Phone).
"""

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

MAX_BATCH_SIZE = 50
MAX_BODY_BYTES = 1024 * 1024  # 1 MB


def validate_change_event(event: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate a single change_log replication event."""
    required_keys = [
        "operation_id", "sequence_number", "origin_node_id",
        "origin_epoch", "schema_version", "entity_type",
        "entity_id", "operation", "payload", "created_at"
    ]
    for k in required_keys:
        if k not in event:
            return False, f"Missing required field in change event: {k}"

    if event["operation"] not in ("upsert", "delete"):
        return False, f"Invalid operation: {event['operation']}"

    if not isinstance(event["sequence_number"], int) or event["sequence_number"] < 1:
        return False, f"Invalid sequence_number: {event['sequence_number']}"

    if not isinstance(event["payload"], (dict, str)):
        return False, "Payload must be a JSON object or string"

    return True, None


def validate_batch_request(batch: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate replication batch envelope."""
    if not isinstance(batch, dict):
        return False, "Batch must be a JSON object"

    if "batch_id" not in batch or "events" not in batch:
        return False, "Batch must contain 'batch_id' and 'events'"

    events = batch["events"]
    if not isinstance(events, list):
        return False, "'events' must be a list"

    if len(events) > MAX_BATCH_SIZE:
        return False, f"Batch exceeds maximum allowed size of {MAX_BATCH_SIZE} events"

    for idx, ev in enumerate(events):
        valid, err = validate_change_event(ev)
        if not valid:
            return False, f"Invalid event at index {idx}: {err}"

    return True, None


def detect_sequence_gap(
    last_applied_sequence: int,
    incoming_events: List[Dict[str, Any]]
) -> Tuple[bool, List[int]]:
    """
    Check if incoming events have continuity with last_applied_sequence.
    Returns: (has_gap, missing_sequences)
    """
    if not incoming_events:
        return False, []

    first_seq = incoming_events[0]["sequence_number"]

    # Check for gap between last applied and first incoming event
    if first_seq > last_applied_sequence + 1:
        missing = list(range(last_applied_sequence + 1, first_seq))
        return True, missing

    # Check continuity within the batch
    for i in range(1, len(incoming_events)):
        prev_seq = incoming_events[i - 1]["sequence_number"]
        curr_seq = incoming_events[i]["sequence_number"]
        if curr_seq > prev_seq + 1:
            missing = list(range(prev_seq + 1, curr_seq))
            return True, missing
        elif curr_seq <= prev_seq:
            # Out of order or duplicate sequence within batch
            return True, [prev_seq + 1]

    return False, []


def make_replication_response(
    accepted: bool,
    last_applied_sequence: int,
    duplicate_count: int = 0,
    missing_sequences: Optional[List[int]] = None,
    requires_full_resync: bool = False
) -> Dict[str, Any]:
    """Format standard replication response payload."""
    return {
        "accepted": bool(accepted),
        "last_applied_sequence": int(last_applied_sequence),
        "duplicate_count": int(duplicate_count),
        "missing_sequences": missing_sequences or [],
        "requires_full_resync": bool(requires_full_resync)
    }
