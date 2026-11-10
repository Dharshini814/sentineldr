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
from shared.alerts import (
    dispatch_alert,
    enqueue_alert,
    format_interim_incident_alert,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    SEVERITY_INFO,
)


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
                    now = time.time()
                    inc_id = None
                    if hasattr(self.db, "get_active_incident"):
                        active_inc = self.db.get_active_incident()
                        if not active_inc:
                            inc_id = f"inc-{int(now)}-{uuid.uuid4().hex[:6]}"
                            last_hb = getattr(self.heartbeat_tracker, "last_received_at", None) or now
                            if hasattr(self.db, "create_or_update_incident"):
                                self.db.create_or_update_incident({
                                    "incident_id": inc_id,
                                    "status": "OPEN",
                                    "last_good_heartbeat_at": last_hb,
                                    "suspected_at": now
                                })
                        else:
                            inc_id = active_inc["incident_id"]

                    if inc_id and hasattr(self.db, "enqueue_alert"):
                        enqueue_alert(
                            db=self.db,
                            dedupe_key=f"suspected_{inc_id}",
                            severity=SEVERITY_WARNING,
                            title="Laptop Node suspected offline",
                            body=(
                                f"Phone Node detected {misses} consecutive missed heartbeats from Laptop Node.\n"
                                f"Incident ID: {inc_id}\n"
                                f"Timestamp:   {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(now))}\n"
                                f"Disaster recovery evaluation has commenced."
                            ),
                            cooldown_seconds=120.0,
                            now=now
                        )

                    self.db.log_audit_event(
                        event_id=uuid.uuid4().hex,
                        node_id=self.node_id,
                        epoch=self.state_machine.current_epoch,
                        event_type="HEARTBEAT_TIMEOUT_SUSPECTED_OFFLINE",
                        severity="WARNING",
                        details={
                            "consecutive_misses": misses,
                            "incident_id": inc_id,
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

            now = time.time()
            # Update or create active incident
            inc_id = None
            if hasattr(self.db, "get_active_incident"):
                active_inc = self.db.get_active_incident()
                if not active_inc:
                    inc_id = f"inc-{int(now)}-{uuid.uuid4().hex[:6]}"
                    if hasattr(self.db, "create_or_update_incident"):
                        self.db.create_or_update_incident({
                            "incident_id": inc_id,
                            "status": "OPEN",
                            "suspected_at": now - 3.0,
                            "promotion_started_at": now
                        })
                else:
                    inc_id = active_inc["incident_id"]
                    if hasattr(self.db, "create_or_update_incident"):
                        self.db.create_or_update_incident({
                            "incident_id": inc_id,
                            "promotion_started_at": now
                        })

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=self.state_machine.current_epoch,
                event_type="PROMOTION_PENDING_ENTERED",
                severity="INFO",
                details={"reason": reason, "force_admin": force_admin, "incident_id": inc_id}
            )

            # Hook: Promotion started
            if hasattr(self.db, "enqueue_alert"):
                enqueue_alert(
                    db=self.db,
                    dedupe_key=f"promotion_started_{inc_id or int(now)}",
                    severity=SEVERITY_WARNING,
                    title="Promotion started",
                    body=(
                        f"Phone Node is initiating promotion to become active primary.\n"
                        f"Reason:      {reason}\n"
                        f"Incident ID: {inc_id or 'N/A'}\n"
                        f"Timestamp:   {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(now))}"
                    ),
                    cooldown_seconds=30.0,
                    now=now
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
                    if hasattr(self.db, "enqueue_alert"):
                        enqueue_alert(
                            db=self.db,
                            dedupe_key=f"promo_denied_lease_{self.cluster_id}_{int(now)}",
                            severity=SEVERITY_CRITICAL,
                            title="Promotion denied or failed",
                            body=abort_reason,
                            now=now
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
                is_unreachable = any(k in str(wit_err).upper() for k in ("UNREACHABLE", "REFUSED", "TIMEOUT", "CONNECT", "FAILED TO CONNECT"))
                if is_unreachable and hasattr(self.db, "enqueue_alert"):
                    enqueue_alert(
                        db=self.db,
                        dedupe_key=f"witness_unreachable_{int(now)}",
                        severity=SEVERITY_CRITICAL,
                        title="Witness unreachable",
                        body=f"Failed to communicate with witness quorum at {self.witness_url}: {wit_err}",
                        now=now
                    )
                if hasattr(self.db, "enqueue_alert"):
                    enqueue_alert(
                        db=self.db,
                        dedupe_key=f"promo_denied_witness_{self.cluster_id}_{int(now)}",
                        severity=SEVERITY_CRITICAL,
                        title="Promotion denied or failed",
                        body=fail_reason,
                        now=now
                    )
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

            now_active = time.time()
            # Update incident with active timestamp
            inc_rec = None
            if hasattr(self.db, "get_active_incident"):
                active_inc = self.db.get_active_incident()
                if active_inc:
                    inc_id = active_inc["incident_id"]
                    if hasattr(self.db, "create_or_update_incident"):
                        self.db.create_or_update_incident({
                            "incident_id": inc_id,
                            "phone_node_active_at": now_active
                        })
                    if hasattr(self.db, "get_incident"):
                        inc_rec = self.db.get_incident(inc_id)

            if not inc_rec:
                inc_rec = {
                    "incident_id": f"inc-{int(now_active)}",
                    "status": "OPEN",
                    "last_good_heartbeat_at": getattr(self.heartbeat_tracker, "last_received_at", None),
                    "suspected_at": now_active - 3.0,
                    "phone_node_active_at": now_active
                }

            report_body = format_interim_incident_alert(inc_rec)

            # Enqueue durable interim alert into alert_outbox
            if hasattr(self.db, "enqueue_alert"):
                enqueue_alert(
                    db=self.db,
                    dedupe_key=f"promoted_{inc_rec.get('incident_id')}",
                    severity=SEVERITY_CRITICAL,
                    title="Phone Node became active",
                    body=report_body,
                    cooldown_seconds=0.0,
                    now=now_active
                )

            # Also dispatch via async dispatcher for immediate background delivery
            dispatch_alert(
                subject="Phone Node became active",
                body=report_body,
                severity=SEVERITY_CRITICAL,
                node_id=self.node_id,
                incident_id=inc_rec.get("incident_id")
            )

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=new_record.epoch,
                event_type="PROMOTION_SUCCESSFUL_SECONDARY_ACTIVE",
                severity="INFO",
                details={
                    "new_role": STATE_SECONDARY_ACTIVE,
                    "new_epoch": new_record.epoch,
                    "lease_id": new_record.lease_id,
                    "incident_id": inc_rec.get("incident_id")
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
        safe_body = (
            f"Node '{self.node_id}' entered SAFE_MODE in epoch {self.state_machine.current_epoch}.\n"
            f"Event Type: {event_type}\n"
            f"Reason: {reason}\n"
            f"Writes are strictly fenced to prevent split-brain dual-primary corruption."
        )
        if hasattr(self.db, "enqueue_alert"):
            enqueue_alert(
                db=self.db,
                dedupe_key=f"safemode_{event_type}",
                severity=SEVERITY_CRITICAL,
                title=f"SAFE_MODE Engaged: {event_type}",
                body=safe_body,
                cooldown_seconds=60.0
            )
        dispatch_alert(
            subject=f"SAFE_MODE Engaged: {event_type}",
            body=safe_body,
            severity=SEVERITY_CRITICAL,
            node_id=self.node_id
        )
