"""
SentinelDR - Cluster State Machine
Standard library only (runtime-neutral for Laptop & Phone).
Manages cluster state transitions, validates against illegal transitions,
and dispatches audit logging.
"""

import threading
import time
import uuid
from typing import Callable, Dict, Optional, Set, Tuple

from shared.api_contract import (
    ALL_STATES,
    STATE_FAILBACK_PENDING,
    STATE_PRIMARY_ACTIVE,
    STATE_PROMOTION_PENDING,
    STATE_RECONCILING,
    STATE_RECOVERING,
    STATE_SAFE_MODE,
    STATE_SECONDARY_ACTIVE,
    STATE_SECONDARY_STANDBY,
    STATE_STARTING,
    STATE_SUSPECTED_OFFLINE,
)


class IllegalStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


# Strict Adjacency Map for State Transitions
ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    STATE_STARTING: {
        STATE_PRIMARY_ACTIVE,
        STATE_SECONDARY_STANDBY,
        STATE_SAFE_MODE,
        STATE_RECOVERING,
    },
    STATE_PRIMARY_ACTIVE: {
        STATE_SUSPECTED_OFFLINE,
        STATE_SAFE_MODE,
        STATE_RECOVERING,
    },
    STATE_SECONDARY_STANDBY: {
        STATE_SUSPECTED_OFFLINE,
        STATE_SAFE_MODE,
    },
    STATE_SUSPECTED_OFFLINE: {
        STATE_SECONDARY_STANDBY,    # Peer recovered
        STATE_PRIMARY_ACTIVE,       # For laptop: phone was suspected offline, now back or still active
        STATE_PROMOTION_PENDING,    # Promoting to active
        STATE_SAFE_MODE,            # Fail closed
    },
    STATE_PROMOTION_PENDING: {
        STATE_SECONDARY_ACTIVE,     # Lease acquired from witness
        STATE_SAFE_MODE,            # Lease denied or witness unreachable
    },
    STATE_SECONDARY_ACTIVE: {
        STATE_RECONCILING,          # Recovering primary detected, starting sync
        STATE_FAILBACK_PENDING,     # Controlled step-down during failback
        STATE_SAFE_MODE,            # Lease lost or partition ended without lease
    },
    STATE_RECOVERING: {
        STATE_RECONCILING,
        STATE_SAFE_MODE,
    },
    STATE_RECONCILING: {
        STATE_FAILBACK_PENDING,
        STATE_SAFE_MODE,
    },
    STATE_FAILBACK_PENDING: {
        STATE_PRIMARY_ACTIVE,       # Laptop resumes primary role
        STATE_SECONDARY_STANDBY,    # Phone steps down to standby
        STATE_SAFE_MODE,
    },
    STATE_SAFE_MODE: {
        STATE_STARTING,             # Reset / bootstrap
        STATE_PRIMARY_ACTIVE,       # Manual operator promotion
        STATE_SECONDARY_STANDBY,    # Manual operator reset to standby
        STATE_PROMOTION_PENDING,    # Manual operator promotion attempt
        STATE_RECOVERING,           # Operator recovery attempt
    },
}


class ClusterStateMachine:
    """Thread-safe state machine for a SentinelDR node."""

    def __init__(
        self,
        initial_state: str,
        node_id: str,
        initial_epoch: int = 1,
        audit_callback: Optional[Callable[[str, str, int, str, str, Dict], None]] = None
    ):
        if initial_state not in ALL_STATES:
            raise ValueError(f"Invalid initial state: {initial_state}")
        self._state: str = initial_state
        self._node_id: str = node_id
        self._epoch: int = initial_epoch
        self._audit_callback = audit_callback
        self._last_transition_at: float = time.time()
        self._lock = threading.RLock()

    @property
    def current_state(self) -> str:
        with self._lock:
            return self._state

    @property
    def current_epoch(self) -> int:
        with self._lock:
            return self._epoch

    def set_epoch(self, new_epoch: int) -> None:
        """Set monotonic epoch (must be >= current epoch)."""
        with self._lock:
            if new_epoch < self._epoch:
                raise ValueError(f"Epoch cannot decrease: current={self._epoch}, attempted={new_epoch}")
            self._epoch = new_epoch

    def is_writable(self) -> bool:
        """Return True if node's state permits attempting data writes."""
        with self._lock:
            return self._state in (STATE_PRIMARY_ACTIVE, STATE_SECONDARY_ACTIVE)

    def transition_to(
        self,
        new_state: str,
        reason: str,
        new_epoch: Optional[int] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Safely transition to new_state if allowed.
        Logs an audit event on successful transition.
        """
        with self._lock:
            if new_state not in ALL_STATES:
                return False, f"UNKNOWN_STATE: {new_state}"

            if new_state == self._state:
                # No-op transition
                return True, None

            allowed_targets = ALLOWED_TRANSITIONS.get(self._state, set())
            if new_state not in allowed_targets:
                err_msg = f"ILLEGAL_TRANSITION: Cannot transition from {self._state} to {new_state}"
                return False, err_msg

            if new_epoch is not None:
                if new_epoch < self._epoch:
                    return False, f"STALE_EPOCH: new epoch {new_epoch} < current epoch {self._epoch}"
                self._epoch = new_epoch

            old_state = self._state
            self._state = new_state
            self._last_transition_at = time.time()

            # Dispatch audit event
            if self._audit_callback:
                try:
                    self._audit_callback(
                        str(uuid.uuid4()),
                        self._node_id,
                        self._epoch,
                        "STATE_TRANSITION",
                        "INFO",
                        {
                            "from_state": old_state,
                            "to_state": new_state,
                            "reason": reason,
                            "epoch": self._epoch,
                            "timestamp": self._last_transition_at
                        }
                    )
                except Exception:
                    pass

            return True, None
