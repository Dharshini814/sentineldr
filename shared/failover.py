"""
SentinelDR - Shared Failover Engine & Coordinator
Standard library only (runtime-neutral for Laptop & Phone).
Manages heartbeat failure detection, transition from SECONDARY_STANDBY to SUSPECTED_OFFLINE,
promotion evaluation with bounded clock-skew, witness quorum lease acquisition,
database physical integrity check, atomic lease persistence, and fail-closed SAFE_MODE.
"""

import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from shared.api_contract import (
    STATE_PRIMARY_ACTIVE,
    STATE_PROMOTION_PENDING,
    STATE_SAFE_MODE,
    STATE_SECONDARY_ACTIVE,
    STATE_SECONDARY_STANDBY,
    STATE_SUSPECTED_OFFLINE,
)
from shared.heartbeat import HeartbeatTracker
from shared.ownership import OwnershipRecord, validate_lease
from shared.state_machine import ClusterStateMachine
from shared.witness import WitnessClient


class FailoverCoordinator:
    """Coordinates failure detection and safe failover promotion."""

    def __init__(
        self,
        node_id: str,
        cluster_id: str,
        state_machine: ClusterStateMachine,
        heartbeat_tracker: HeartbeatTracker,
        db: Any,
        witness_url: str,
        witness_secret: str,
        max_clock_skew: float = 2.0,
        lease_duration_seconds: float = 30.0,
        witness_timeout: float = 3.0
    ):
        self.node_id = node_id
        self.cluster_id = cluster_id
        self.state_machine = state_machine
        self.heartbeat_tracker = heartbeat_tracker
        self.db = db
        self.witness_url = witness_url
        self.witness_secret = witness_secret
        self.max_clock_skew = max_clock_skew
        self.lease_duration_seconds = lease_duration_seconds
        self.witness_client = WitnessClient(timeout=witness_timeout)
        self._lock = threading.RLock()

    def evaluate_heartbeat_timeout(self) -> Tuple[bool, str]:
        """
        Evaluate missed heartbeats.
        After 3 missed heartbeats (~9s), moves SECONDARY_STANDBY to SUSPECTED_OFFLINE.
        IMPORTANT: This step alone MUST NOT promote!
        """
        with self._lock:
            if self.state_machine.current_state != STATE_SECONDARY_STANDBY:
                return False, f"Not in SECONDARY_STANDBY (current: {self.state_machine.current_state})"

            if self.heartbeat_tracker.is_suspected_offline():
                misses = self.heartbeat_tracker.evaluate_misses()
                ok, err = self.state_machine.transition_to(
                    STATE_SUSPECTED_OFFLINE,
                    reason=f"Peer missed {misses} consecutive heartbeats (>= 3 threshold)"
                )
                if ok:
                    self.db.log_audit_event(
                        event_id=uuid.uuid4().hex,
                        node_id=self.node_id,
                        epoch=self.state_machine.current_epoch,
                        event_type="HEARTBEAT_TIMEOUT_SUSPECTED_OFFLINE",
                        severity="WARNING",
                        details={
                            "consecutive_misses": misses,
                            "note": "Peer suspected offline. Automatic promotion NOT triggered."
                        }
                    )
                    return True, "Transitioned to SUSPECTED_OFFLINE (no automatic promotion)"
                return False, err or "Transition failed"

            return False, "Heartbeats healthy; threshold not reached"

    def attempt_failover(
        self,
        reason: str = "Failover initiated after peer loss",
        force_admin: bool = False
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Executes the safe promotion workflow:
        1. Checks state eligibility (must be SUSPECTED_OFFLINE or admin override from SAFE_MODE).
        2. Transitions to PROMOTION_PENDING.
        3. Evaluates last lease expiry with bounded clock-skew policy.
        4. Contacts Independent Witness to request lease for epoch N+1.
        5. If safe ownership cannot be proven: enters SAFE_MODE (read-only) and raises critical alert.
        6. If approved:
           a. Persists new OwnershipRecord atomically BEFORE enabling writes.
           b. Verifies database physical integrity (PRAGMA integrity_check).
           c. Transitions to SECONDARY_ACTIVE with new epoch N+1.
        """
        with self._lock:
            current_state = self.state_machine.current_state
            if current_state == STATE_SECONDARY_ACTIVE:
                return True, "Already in SECONDARY_ACTIVE", None

            # Only allow promotion from SUSPECTED_OFFLINE (or SAFE_MODE with admin override)
            if current_state != STATE_SUSPECTED_OFFLINE and not (force_admin and current_state == STATE_SAFE_MODE):
                return False, f"Illegal state for failover: {current_state} (must be SUSPECTED_OFFLINE)", None

            # Step 1: Transition to PROMOTION_PENDING
            ok, err = self.state_machine.transition_to(
                STATE_PROMOTION_PENDING,
                reason=f"Initiating promotion: {reason}"
            )
            if not ok:
                return False, f"Failed to enter PROMOTION_PENDING: {err}", None

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=self.state_machine.current_epoch,
                event_type="PROMOTION_PENDING_ENTERED",
                severity="INFO",
                details={"reason": reason, "force_admin": force_admin}
            )

            # Step 2: Check last lease expiry under bounded clock-skew policy
            now = time.time()
            ownership = self.db.get_ownership(self.cluster_id)
            if ownership and ownership.owner_node_id != self.node_id:
                # If local clock - max_clock_skew has not yet passed the previous owner's lease expiry:
                if (now - self.max_clock_skew) < ownership.lease_expires_at:
                    remaining = round(ownership.lease_expires_at - (now - self.max_clock_skew), 2)
                    abort_reason = (
                        f"Aborting promotion: Peer '{ownership.owner_node_id}' lease has not expired under bounded skew "
                        f"(effective remaining: {remaining}s, max_clock_skew: {self.max_clock_skew}s)"
                    )
                    self._enter_safe_mode(abort_reason, event_type="PROMOTION_REJECTED_LEASE_ACTIVE")
                    return False, f"SAFE_MODE: {abort_reason}", None

            # Step 3: Contact Witness / Quorum service
            last_epoch = ownership.epoch if ownership else self.state_machine.current_epoch
            target_epoch = last_epoch + 1

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=last_epoch,
                event_type="WITNESS_LEASE_REQUEST_SENT",
                severity="INFO",
                details={
                    "witness_url": self.witness_url,
                    "target_epoch": target_epoch,
                    "duration_seconds": self.lease_duration_seconds
                }
            )

            wit_ok, new_record, wit_err = self.witness_client.acquire_lease(
                witness_url=self.witness_url,
                cluster_id=self.cluster_id,
                candidate_node_id=self.node_id,
                requested_epoch=target_epoch,
                duration_seconds=self.lease_duration_seconds
            )

            if not wit_ok or not new_record:
                fail_reason = f"Witness lease acquisition denied or failed: {wit_err}"
                self._enter_safe_mode(fail_reason, event_type="FAILOVER_FAILED_WITNESS_DENIED")
                return False, f"SAFE_MODE: {fail_reason}", None

            # Step 4: Approved by Witness!
            # CRITICAL: Persist OwnershipRecord atomically BEFORE enabling writes
            try:
                self.db.set_ownership(new_record)
            except Exception as e:
                db_err = f"Failed to persist ownership lease to database: {str(e)}"
                self._enter_safe_mode(db_err, event_type="OWNERSHIP_PERSISTENCE_FAILED")
                return False, f"SAFE_MODE: {db_err}", None

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=new_record.epoch,
                event_type="OWNERSHIP_LEASE_PERSISTED",
                severity="INFO",
                details={
                    "lease_id": new_record.lease_id,
                    "epoch": new_record.epoch,
                    "expires_at": new_record.lease_expires_at,
                    "granted_by": new_record.granted_by
                }
            )

            # Step 5: Verify SQLite Physical Integrity
            int_ok, int_err = self.db.verify_full_integrity()
            if not int_ok:
                corrupt_msg = f"Database physical integrity check failed during promotion: {int_err}"
                self._enter_safe_mode(corrupt_msg, event_type="DATABASE_INTEGRITY_CHECK_FAILED")
                return False, f"SAFE_MODE: {corrupt_msg}", None

            # Step 6: Transition to SECONDARY_ACTIVE
            trans_ok, trans_err = self.state_machine.transition_to(
                STATE_SECONDARY_ACTIVE,
                reason="Witness quorum granted lease and DB integrity verified",
                new_epoch=new_record.epoch
            )
            if not trans_ok:
                err_msg = f"Failed to transition state machine to SECONDARY_ACTIVE: {trans_err}"
                self._enter_safe_mode(err_msg, event_type="STATE_MACHINE_PROMOTION_FAILED")
                return False, f"SAFE_MODE: {err_msg}", None

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=new_record.epoch,
                event_type="PROMOTION_SUCCESSFUL_SECONDARY_ACTIVE",
                severity="INFO",
                details={
                    "new_role": STATE_SECONDARY_ACTIVE,
                    "new_epoch": new_record.epoch,
                    "lease_id": new_record.lease_id
                }
            )

            return True, "Promotion successful: node is now SECONDARY_ACTIVE", new_record.to_dict()

    def _enter_safe_mode(self, reason: str, event_type: str = "SAFE_MODE_TRIGGERED"):
        """Helper to safely fail closed into SAFE_MODE and log critical audit alert."""
        self.state_machine.transition_to(STATE_SAFE_MODE, reason=reason)
        self.db.log_audit_event(
            event_id=uuid.uuid4().hex,
            node_id=self.node_id,
            epoch=self.state_machine.current_epoch,
            event_type=event_type,
            severity="CRITICAL",
            details={
                "action": "ENTERED_SAFE_MODE",
                "writable": False,
                "reason": reason
            }
        )
