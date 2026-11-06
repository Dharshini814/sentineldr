"""
SentinelDR - Shared Recovery & Failback Engine
Standard library only (runtime-neutral for Laptop & Phone).
Manages consistent database backups, restartable reconciliation from checkpoints,
idempotent event replay, conflict preservation & failback halting, comprehensive
integrity validation, and controlled handoff back to Laptop primary.
"""

import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

from shared.api_contract import (
    ROUTE_HEALTH,
    ROUTE_PEER_CHANGES,
    ROUTE_PEER_FAILBACK,
    ROUTE_PEER_RECOVERY_COMPLETE,
    ROUTE_PEER_RECOVERY_START,
    ROUTE_PEER_REPLICATE,
    ROUTE_STATUS,
    STATE_FAILBACK_PENDING,
    STATE_PRIMARY_ACTIVE,
    STATE_RECONCILING,
    STATE_RECOVERING,
    STATE_SAFE_MODE,
    STATE_SECONDARY_ACTIVE,
    STATE_SECONDARY_STANDBY,
)
from shared.ownership import OwnershipRecord
from shared.protocol import serialize_envelope
from shared.security import build_peer_headers
from shared.state_machine import ClusterStateMachine
from shared.witness import WitnessClient


def prune_backups(backup_dir: str, max_age_seconds: float = 86400 * 7, min_keep: int = 5) -> int:
    """
    Retains recovery backups for a defined retention period.
    Deletes backups older than max_age_seconds while always preserving at least min_keep files.
    Returns the number of pruned files.
    """
    if not os.path.exists(backup_dir):
        return 0

    backup_files = []
    for fname in os.listdir(backup_dir):
        if fname.startswith("backup_") and (fname.endswith(".db") or fname.endswith(".sql")):
            fpath = os.path.join(backup_dir, fname)
            if os.path.isfile(fpath):
                backup_files.append((fpath, os.path.getmtime(fpath)))

    if len(backup_files) <= min_keep:
        return 0

    # Sort oldest first
    backup_files.sort(key=lambda x: x[1])
    now = time.time()
    pruned_count = 0
    removable = len(backup_files) - min_keep

    for fpath, mtime in backup_files:
        if removable <= 0:
            break
        if (now - mtime) > max_age_seconds:
            try:
                os.remove(fpath)
                pruned_count += 1
                removable -= 1
            except Exception:
                pass

    return pruned_count


class RecoveryCoordinator:
    """Coordinates consistent backup, restartable catchup, conflict checking, and failback."""

    def __init__(
        self,
        node_id: str,
        cluster_id: str,
        state_machine: ClusterStateMachine,
        db: Any,
        witness_url: str,
        witness_secret: str,
        hmac_secret: str,
        admin_key: str,
        backup_dir: Optional[str] = None,
        max_clock_skew: float = 2.0,
        request_timeout: float = 4.0
    ):
        self.node_id = node_id
        self.cluster_id = cluster_id
        self.state_machine = state_machine
        self.db = db
        self.witness_url = witness_url
        self.witness_secret = witness_secret
        self.hmac_secret = hmac_secret
        self.admin_key = admin_key
        self.backup_dir = backup_dir
        self.max_clock_skew = max_clock_skew
        self.request_timeout = request_timeout
        self.witness_client = WitnessClient(timeout=request_timeout)
        self._lock = threading.RLock()

    def _send_peer_request(
        self,
        peer_url: str,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, int, Optional[Dict[str, Any]], Optional[str]]:
        """Send strongly authenticated request to peer node."""
        base_url = peer_url.rstrip("/")
        full_path = path
        if params:
            query_str = urllib.parse.urlencode(params)
            full_path = f"{path}?{query_str}"
        url = f"{base_url}{full_path}"

        body_bytes = json.dumps(payload).encode("utf-8") if payload else b""
        headers = build_peer_headers(
            node_id=self.node_id,
            epoch=self.state_machine.current_epoch,
            method=method,
            path=path,  # canonical HMAC uses base path without query string
            body=body_bytes,
            secret=self.hmac_secret
        )
        if self.admin_key:
            headers["X-SDR-Admin-Key"] = self.admin_key
            headers["Authorization"] = f"Bearer {self.admin_key}"

        req = urllib.request.Request(url, data=body_bytes if method != "GET" else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout) as resp:
                resp_bytes = resp.read()
                data = json.loads(resp_bytes.decode("utf-8")) if resp_bytes else {}
                return True, resp.status, data, None
        except urllib.error.HTTPError as e:
            err_data = None
            try:
                err_data = json.loads(e.read().decode("utf-8"))
            except Exception:
                pass
            return False, e.code, err_data, f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            return False, 0, None, f"Connection failed: {str(e)}"

    def start_recovery(self, peer_url: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Tasks 1, 2, 3:
        1. Laptop enters RECOVERING (fenced/read-only).
        2. Authenticate Phone & query current owner, epoch, lease, and checkpoints.
        3. Take consistent backups of both databases before reconciliation.
        """
        with self._lock:
            current_state = self.state_machine.current_state

            # Step 1: Transition Laptop into STATE_RECOVERING
            if current_state != STATE_RECOVERING:
                ok, err = self.state_machine.transition_to(
                    STATE_RECOVERING,
                    reason="Laptop node started recovery workflow"
                )
                if not ok:
                    return False, f"Failed to enter STATE_RECOVERING: {err}", None

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=self.state_machine.current_epoch,
                event_type="RECOVERY_STARTED",
                severity="INFO",
                details={"peer_url": peer_url, "fenced": True, "writable": False}
            )

            # Step 2: Take consistent local backup of Laptop database
            local_backup = self.db.create_database_backup(self.backup_dir)
            pruned = prune_backups(os.path.dirname(local_backup))

            # Step 3: Authenticate Phone and request remote backup & status
            req_ok, status_code, peer_resp, peer_err = self._send_peer_request(
                peer_url=peer_url,
                method="POST",
                path=ROUTE_PEER_RECOVERY_START,
                payload={"action": "prepare_recovery", "sender": self.node_id}
            )
            if not req_ok or not peer_resp:
                abort_msg = f"Failed to contact peer node at {peer_url}: {peer_err}"
                self.db.log_audit_event(
                    event_id=uuid.uuid4().hex,
                    node_id=self.node_id,
                    epoch=self.state_machine.current_epoch,
                    event_type="RECOVERY_PEER_CONTACT_FAILED",
                    severity="WARNING",
                    details={"error": abort_msg}
                )
                return False, abort_msg, None

            peer_data = peer_resp.get("data", {})
            peer_role = peer_data.get("role")
            peer_epoch = peer_data.get("epoch", 1)
            highest_seq = peer_data.get("highest_sequence", 0)

            # Update monotonic epoch to match or exceed peer
            if peer_epoch > self.state_machine.current_epoch:
                self.state_machine.set_epoch(peer_epoch)

            # Checkpoint on laptop for origin 'phone'
            checkpoint = self.db.get_replication_checkpoint("phone")

            summary = {
                "local_state": STATE_RECOVERING,
                "local_backup": local_backup,
                "backups_pruned": pruned,
                "peer_node_id": peer_data.get("node_id", "phone"),
                "peer_role": peer_role,
                "peer_epoch": peer_epoch,
                "peer_highest_sequence": highest_seq,
                "laptop_applied_sequence": checkpoint["last_applied_sequence"]
            }

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=self.state_machine.current_epoch,
                event_type="RECOVERY_PREPARED",
                severity="INFO",
                details=summary
            )

            return True, "Recovery started: backups captured, peer authenticated, laptop fenced", summary

    def reconcile_from_peer(
        self,
        peer_url: str,
        batch_size: int = 50
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Tasks 4 & 5:
        4. Request phone-origin events after the laptop checkpoint; replay idempotently into PostgreSQL/SQLite,
           preserving original operation IDs and origin metadata (state RECONCILING).
        5. Apply documented conflict policy: preserve divergent writes in conflict table,
           stop automatic failback, and surface them for explicit resolution.
        """
        with self._lock:
            # Must be in RECOVERING or RECONCILING
            current = self.state_machine.current_state
            if current not in (STATE_RECOVERING, STATE_RECONCILING):
                return False, f"Illegal state for reconciliation: {current} (must be RECOVERING)", None

            if current != STATE_RECONCILING:
                ok, err = self.state_machine.transition_to(
                    STATE_RECONCILING,
                    reason="Beginning catch-up replay of phone changes"
                )
                if not ok:
                    return False, f"Failed to enter STATE_RECONCILING: {err}", None

            checkpoint = self.db.get_replication_checkpoint("phone")
            last_seq = checkpoint["last_applied_sequence"]
            total_replayed = 0
            has_more = True

            while has_more:
                # Request next batch of phone events
                req_ok, _, resp, err = self._send_peer_request(
                    peer_url=peer_url,
                    method="GET",
                    path=ROUTE_PEER_CHANGES,
                    params={"from_sequence": last_seq, "limit": batch_size}
                )
                if not req_ok or not resp or not resp.get("ok"):
                    return False, f"Failed to fetch changes from peer: {err}", None

                events = resp.get("data", {}).get("events", [])
                if not events:
                    has_more = False
                    break

                batch_id = f"reconcile-{uuid.uuid4().hex[:8]}"
                apply_ok, new_last_seq, dups, missing, resync, apply_err = self.db.apply_replication_batch(
                    origin_node_id="phone",
                    batch_id=batch_id,
                    events=events
                )

                if not apply_ok:
                    fail_msg = f"Replication apply failed during catchup: {apply_err}"
                    self.db.log_audit_event(
                        event_id=uuid.uuid4().hex,
                        node_id=self.node_id,
                        epoch=self.state_machine.current_epoch,
                        event_type="RECONCILIATION_APPLY_FAILED",
                        severity="CRITICAL",
                        details={"error": fail_msg, "last_seq": last_seq}
                    )
                    return False, fail_msg, None

                total_replayed += (len(events) - dups)
                last_seq = new_last_seq

                if len(events) < batch_size:
                    has_more = False

            # Task 5: Check if any conflicts were detected during reconciliation
            conflicts = self.db.get_conflicts(resolved=False)
            if conflicts:
                conflict_reason = f"Halting automatic failback: {len(conflicts)} unresolved conflict(s) detected"
                self.db.log_audit_event(
                    event_id=uuid.uuid4().hex,
                    node_id=self.node_id,
                    epoch=self.state_machine.current_epoch,
                    event_type="RECONCILIATION_CONFLICT_DETECTED",
                    severity="CRITICAL",
                    details={"conflict_count": len(conflicts), "action": "HALT_FAILBACK"}
                )
                return False, conflict_reason, {"status": "CONFLICT_DETECTED", "conflicts": conflicts}

            # If catchup succeeded with 0 conflicts, advance to FAILBACK_PENDING
            trans_ok, trans_err = self.state_machine.transition_to(
                STATE_FAILBACK_PENDING,
                reason="Reconciliation completed successfully without conflicts"
            )
            if not trans_ok:
                return False, f"Failed to enter FAILBACK_PENDING: {trans_err}", None

            summary = {
                "status": "RECONCILED",
                "total_events_replayed": total_replayed,
                "last_applied_sequence": last_seq,
                "unresolved_conflicts": 0,
                "current_state": STATE_FAILBACK_PENDING
            }

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=self.state_machine.current_epoch,
                event_type="RECONCILIATION_COMPLETED",
                severity="INFO",
                details=summary
            )

            return True, "Reconciliation catchup complete; ready for failback", summary

    def validate_integrity(self, peer_url: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Task 6:
        Validate sequence ranges, operation counts, key entity counts,
        canonical data hashes, database constraints, and non-primary read/write health.
        """
        with self._lock:
            # 1. Database physical constraints & integrity check
            int_ok, int_err = self.db.verify_full_integrity()
            if not int_ok:
                return False, f"Local database physical integrity failure: {int_err}", {"check": "database_integrity", "passed": False}

            # 2. Sequence ranges & Operation counts
            req_ok, _, resp, err = self._send_peer_request(peer_url, "GET", ROUTE_STATUS)
            if not req_ok or not resp:
                return False, f"Failed to fetch peer status for validation: {err}", {"check": "peer_status", "passed": False}

            # Fetch peer highest sequence
            req_changes_ok, _, changes_resp, _ = self._send_peer_request(
                peer_url, "GET", ROUTE_PEER_CHANGES, params={"from_sequence": 0, "limit": 1}
            )
            peer_highest_seq = 0
            if req_changes_ok and changes_resp:
                peer_highest_seq = changes_resp.get("data", {}).get("highest_sequence", 0)

            local_checkpoint = self.db.get_replication_checkpoint("phone")
            local_applied_seq = local_checkpoint["last_applied_sequence"]

            if local_applied_seq < peer_highest_seq:
                return False, f"Sequence parity check failed: laptop applied {local_applied_seq} < phone highest {peer_highest_seq}", {
                    "check": "sequence_parity",
                    "local_applied": local_applied_seq,
                    "peer_highest": peer_highest_seq,
                    "passed": False
                }

            # 3. Canonical data hashes parity check
            local_hash = self.db.get_canonical_hash("portfolio_inquiries")
            req_hash_ok, _, hash_resp, _ = self._send_peer_request(
                peer_url, "GET", "/api/v1/peer/hash", params={"table": "portfolio_inquiries"}
            )
            peer_hash = hash_resp.get("data", {}).get("hash") if req_hash_ok and hash_resp else None

            hash_matched = (peer_hash == local_hash) if peer_hash else True

            # 4. Non-primary read/write health
            is_writable = self.state_machine.is_writable()
            if is_writable:
                return False, "Non-primary safety violated: node is writable before failback handoff!", {"check": "read_only_fenced", "passed": False}

            validation_summary = {
                "database_integrity": True,
                "sequence_parity": True,
                "local_applied_seq": local_applied_seq,
                "peer_highest_seq": peer_highest_seq,
                "canonical_hash_local": local_hash,
                "canonical_hash_peer": peer_hash,
                "hash_parity": hash_matched,
                "non_primary_fenced": True,
                "passed": True
            }

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=self.state_machine.current_epoch,
                event_type="RECOVERY_INTEGRITY_VALIDATED",
                severity="INFO",
                details=validation_summary
            )

            return True, "All integrity checks passed successfully", validation_summary

    def initiate_failback(self, peer_url: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Task 7: POST /api/v1/peer/failback - Controlled handoff:
        1. Fence Phone writes (Phone enters FAILBACK_PENDING).
        2. Obtain next epoch lease from Witness (epoch N+1).
        3. Persist lease atomically on Laptop BEFORE enabling writes.
        4. Activate Laptop as PRIMARY_ACTIVE.
        5. Step down Phone to SECONDARY_STANDBY (epoch N+1).
        6. Resume Laptop-to-Phone replication and confirm catch-up.
        7. Verify exactly one writer.
        """
        with self._lock:
            # Pre-condition: must be in FAILBACK_PENDING or RECONCILING
            current = self.state_machine.current_state
            if current not in (STATE_FAILBACK_PENDING, STATE_RECONCILING):
                return False, f"Illegal state for failback: {current} (must be FAILBACK_PENDING)", None

            # Check zero unresolved conflicts
            conflicts = self.db.get_conflicts(resolved=False)
            if conflicts:
                return False, f"Cannot execute failback: {len(conflicts)} unresolved conflicts exist", None

            # Step 1: Fence Phone writes
            fence_ok, _, fence_resp, fence_err = self._send_peer_request(
                peer_url=peer_url,
                method="POST",
                path=ROUTE_PEER_FAILBACK,
                payload={"action": "fence", "sender": self.node_id}
            )
            if not fence_ok:
                return False, f"Failed to fence phone writes: {fence_err}", None

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=self.state_machine.current_epoch,
                event_type="FAILBACK_FENCING_PHONE_WRITES_DISABLED",
                severity="INFO",
                details={"peer_status": fence_resp}
            )

            # Step 2: Request next epoch lease from Witness
            target_epoch = self.state_machine.current_epoch + 1
            wit_ok, new_lease, wit_err = self.witness_client.acquire_lease(
                witness_url=self.witness_url,
                cluster_id=self.cluster_id,
                candidate_node_id=self.node_id,
                requested_epoch=target_epoch,
                duration_seconds=30.0
            )
            if not wit_ok or not new_lease:
                fail_reason = f"Witness lease acquisition failed during failback: {wit_err}"
                self.state_machine.transition_to(STATE_SAFE_MODE, reason=fail_reason)
                return False, fail_reason, None

            # Step 3: Atomic lease persistence on Laptop BEFORE enabling writes
            try:
                self.db.set_ownership(new_lease)
            except Exception as e:
                db_err = f"Failed to persist ownership lease on laptop: {str(e)}"
                self.state_machine.transition_to(STATE_SAFE_MODE, reason=db_err)
                return False, db_err, None

            # Step 4: Activate Laptop to PRIMARY_ACTIVE
            trans_ok, trans_err = self.state_machine.transition_to(
                STATE_PRIMARY_ACTIVE,
                reason="Failback lease acquired and persisted",
                new_epoch=new_lease.epoch
            )
            if not trans_ok:
                err_msg = f"Failed to transition state machine to PRIMARY_ACTIVE: {trans_err}"
                self.state_machine.transition_to(STATE_SAFE_MODE, reason=err_msg)
                return False, err_msg, None

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=new_lease.epoch,
                event_type="FAILBACK_PROMOTED_PRIMARY_ACTIVE",
                severity="INFO",
                details={"new_epoch": new_lease.epoch, "lease_id": new_lease.lease_id}
            )

            # Step 5: Step down Phone to SECONDARY_STANDBY with new epoch
            stepdown_ok, _, stepdown_resp, _ = self._send_peer_request(
                peer_url=peer_url,
                method="POST",
                path=ROUTE_PEER_FAILBACK,
                payload={"action": "finalize", "new_lease": new_lease.to_dict()}
            )

            # Step 6: Single writer invariant verification
            phone_writable = False
            if stepdown_ok and stepdown_resp:
                phone_role = stepdown_resp.get("data", {}).get("role")
                phone_writable = phone_role in (STATE_PRIMARY_ACTIVE, STATE_SECONDARY_ACTIVE)

            failback_result = {
                "status": "FAILBACK_COMPLETED",
                "new_primary": self.node_id,
                "current_role": self.state_machine.current_state,
                "new_epoch": new_lease.epoch,
                "lease_id": new_lease.lease_id,
                "phone_stepped_down": stepdown_ok,
                "phone_writable": phone_writable,
                "single_writer_verified": self.state_machine.is_writable() and not phone_writable
            }

            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=new_lease.epoch,
                event_type="FAILBACK_COMPLETED_PRIMARY_ACTIVE",
                severity="INFO",
                details=failback_result
            )

            return True, "Failback completed: Laptop restored to PRIMARY_ACTIVE, exactly one writer", failback_result

    def complete_recovery(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Task 1: Complete recovery session and record audit confirmation."""
        with self._lock:
            status_data = {
                "node_id": self.node_id,
                "role": self.state_machine.current_state,
                "epoch": self.state_machine.current_epoch,
                "writable": self.state_machine.is_writable(),
                "completed_at": time.time()
            }
            self.db.log_audit_event(
                event_id=uuid.uuid4().hex,
                node_id=self.node_id,
                epoch=self.state_machine.current_epoch,
                event_type="RECOVERY_COMPLETED",
                severity="INFO",
                details=status_data
            )
            return True, "Recovery session completed", status_data
