"""
SentinelDR - Failover Test Suite (Phase 6)
Verifies:
1. Three missed heartbeats (3 x ~3s) move SECONDARY_STANDBY -> SUSPECTED_OFFLINE without auto-promotion.
2. Node in SUSPECTED_OFFLINE remains strictly read-only (write guards armed, writes rejected).
3. Safe scenario promotes end-to-end:
   - Witness grants lease at epoch N+1.
   - OwnershipRecord is persisted atomically BEFORE writes are enabled.
   - Database physical integrity check (PRAGMA integrity_check) passes.
   - Node enters SECONDARY_ACTIVE at epoch N+1.
   - Writes are accepted and queued in change_log outbox.
4. Unsafe scenario (peer lease still active under bounded clock-skew) rejects promotion and fails closed into SAFE_MODE.
5. Witness unavailable scenario rejects promotion and fails closed into SAFE_MODE.
6. Database corruption detected during promotion aborts promotion into SAFE_MODE.
7. Outage writes on Phone persist across process / database restarts.
8. Recovered laptop with old epoch cannot write.
9. POST /api/v1/peer/failover requires strong authentication (rejects unauthenticated, accepts admin key and HMAC).
"""

import json
import os
import sys
import threading
import time
import urllib.request
import uuid
import pytest
from starlette.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from laptop.db import LaptopDatabase
import laptop.server as laptop_server_mod
from phone.db import PhoneDatabase
from phone.server import PhoneServer
from shared.api_contract import (
    ROUTE_PEER_FAILOVER,
    ROUTE_STATUS,
    STATE_PRIMARY_ACTIVE,
    STATE_PROMOTION_PENDING,
    STATE_SAFE_MODE,
    STATE_SECONDARY_ACTIVE,
    STATE_SECONDARY_STANDBY,
    STATE_SUSPECTED_OFFLINE,
)
from shared.config import NodeConfig
from shared.failover import FailoverCoordinator
from shared.ownership import OwnershipRecord, sign_ownership_record
from shared.security import build_peer_headers
from shared.state_machine import ClusterStateMachine
from shared.witness import WitnessClient, WitnessServer


@pytest.fixture(scope="module")
def failover_test_env(tmp_path_factory):
    """Sets up isolated witness server, phone server, and test databases."""
    tmp_dir = tmp_path_factory.mktemp("failover_test_env")
    phone_db = str(tmp_dir / "phone_failover.db")
    phone_nonce = str(tmp_dir / "phone_nonce.db")
    laptop_db = str(tmp_dir / "laptop_failover.db")

    # 1. Start Witness Server
    witness_srv = WitnessServer(
        host="127.0.0.1",
        port=0,
        cluster_id="sentineldr-cluster-01",
        witness_secret="test-witness-secret-phase6"
    )
    t_wit = threading.Thread(target=lambda: witness_srv.serve_forever(poll_interval=0.05), daemon=True)
    t_wit.start()
    time.sleep(0.1)
    witness_url = f"http://127.0.0.1:{witness_srv.port}"

    # 2. Start Phone Server
    phone_cfg = NodeConfig("phone")
    phone_cfg.port = 0
    phone_cfg.database_path = phone_db
    phone_cfg.nonce_cache_db = phone_nonce
    phone_cfg.witness_url = witness_url
    phone_cfg.witness_secret = "test-witness-secret-phase6"
    phone_cfg.admin_key = "admin-secret-key-phase6"
    phone_cfg.hmac_secret = "hmac-secret-key-phase6"

    phone_srv = PhoneServer(phone_cfg)
    phone_srv.db.witness_secret = "test-witness-secret-phase6"
    t_phone = threading.Thread(target=lambda: phone_srv.serve_forever(poll_interval=0.05), daemon=True)
    t_phone.start()
    time.sleep(0.1)

    # 3. Setup Laptop Database
    laptop_db_inst = LaptopDatabase(f"sqlite:///{laptop_db}")
    laptop_db_inst._sqlite_path = laptop_db
    laptop_db_inst.using_sqlite_fallback = True
    laptop_db_inst.witness_secret = "test-witness-secret-phase6"
    laptop_db_inst.init_db()
    laptop_db_inst.seed_portfolio_data()

    yield {
        "tmp_dir": tmp_dir,
        "witness_srv": witness_srv,
        "witness_url": witness_url,
        "phone_srv": phone_srv,
        "phone_url": f"http://127.0.0.1:{phone_srv.server_port}",
        "phone_db": phone_db,
        "phone_nonce": phone_nonce,
        "laptop_db_inst": laptop_db_inst,
        "laptop_db_path": laptop_db,
    }

    try:
        phone_srv.stop()
    except Exception:
        pass
    try:
        witness_srv.stop()
    except Exception:
        pass


def test_three_misses_does_not_auto_promote(failover_test_env):
    """
    Task 1: After 3 missed heartbeats (3 x ~3s = 9s), move SECONDARY_STANDBY -> SUSPECTED_OFFLINE.
    This alone must NOT promote or enable writes!
    """
    phone_srv: PhoneServer = failover_test_env["phone_srv"]

    # Reset to SECONDARY_STANDBY
    phone_srv.state_machine._state = STATE_SECONDARY_STANDBY
    assert phone_srv.state_machine.current_state == STATE_SECONDARY_STANDBY
    assert not phone_srv.state_machine.is_writable()

    # Simulate 3 missed heartbeats (> 9.0s elapsed)
    now = time.time()
    phone_srv.heartbeat_tracker.last_received_at = now - 10.0
    misses = phone_srv.heartbeat_tracker.evaluate_misses()
    assert misses >= 3
    assert phone_srv.heartbeat_tracker.is_suspected_offline()

    # Evaluate timeout
    promoted, msg = phone_srv.failover_coordinator.evaluate_heartbeat_timeout()
    assert promoted is True
    assert "Transitioned to SUSPECTED_OFFLINE" in msg

    # State must be SUSPECTED_OFFLINE, NOT promoted!
    assert phone_srv.state_machine.current_state == STATE_SUSPECTED_OFFLINE
    assert phone_srv.state_machine.is_writable() is False

    # Verify audit event
    events = phone_srv.db.get_recent_audit_events(limit=10)
    timeout_events = [e for e in events if e["event_type"] == "HEARTBEAT_TIMEOUT_SUSPECTED_OFFLINE"]
    assert len(timeout_events) > 0
    assert timeout_events[0]["severity"] == "WARNING"
    assert "Automatic promotion NOT triggered" in str(timeout_events[0]["details"])

    # Verify writes remain strictly forbidden
    ok, err_code, err_msg, _ = phone_srv.db.submit_inquiry(
        origin_node_id="phone",
        origin_epoch=phone_srv.state_machine.current_epoch,
        name="Test Visitor",
        email="visitor@example.com",
        subject="Hello",
        message="Should fail during suspected offline",
        is_primary=phone_srv.state_machine.is_writable(),
        cluster_id=phone_srv.config.cluster_id,
        secret=phone_srv.config.hmac_secret
    )
    assert ok is False
    assert err_code == "FORBIDDEN"


def test_unsafe_partition_rejected_to_safe_mode(failover_test_env):
    """
    Task 3: If safe ownership cannot be proven (e.g. peer lease is still active),
    must enter SAFE_MODE, stay read-only, and raise critical audit event.
    """
    phone_srv: PhoneServer = failover_test_env["phone_srv"]

    # Ensure Phone is in SUSPECTED_OFFLINE
    phone_srv.state_machine._state = STATE_SUSPECTED_OFFLINE

    # Establish an unexpired lease for laptop expiring in 30 seconds
    now = time.time()
    active_lease = OwnershipRecord(
        cluster_id=phone_srv.config.cluster_id,
        owner_node_id="laptop",
        epoch=1,
        lease_id="laptop-active-lease",
        lease_expires_at=now + 30.0,
        granted_by="witness",
        signature="sig-active",
        updated_at=now
    )
    phone_srv.db.set_ownership(active_lease)

    # Attempt failover - should be rejected because peer lease is active under bounded clock-skew
    ok, msg, lease = phone_srv.failover_coordinator.attempt_failover(reason="Testing active peer lease rejection")
    assert ok is False
    assert "SAFE_MODE" in msg
    assert "lease has not expired" in msg

    # State must be SAFE_MODE and read-only
    assert phone_srv.state_machine.current_state == STATE_SAFE_MODE
    assert phone_srv.state_machine.is_writable() is False

    # Verify critical audit event
    events = phone_srv.db.get_recent_audit_events(limit=10)
    critical_events = [e for e in events if e["event_type"] == "PROMOTION_REJECTED_LEASE_ACTIVE"]
    assert len(critical_events) > 0
    assert critical_events[0]["severity"] == "CRITICAL"


def test_witness_unavailable_fails_closed_to_safe_mode(failover_test_env):
    """
    Task 3: When the witness is unreachable (e.g. network partition),
    fail closed into SAFE_MODE and raise a critical audit alert.
    """
    phone_srv: PhoneServer = failover_test_env["phone_srv"]

    # Reset state to SUSPECTED_OFFLINE
    phone_srv.state_machine._state = STATE_SUSPECTED_OFFLINE

    # Expire previous lease
    now = time.time()
    expired_lease = OwnershipRecord(
        cluster_id=phone_srv.config.cluster_id,
        owner_node_id="laptop",
        epoch=1,
        lease_id="laptop-expired-lease",
        lease_expires_at=now - 10.0,  # Expired safely
        granted_by="witness",
        signature="sig-expired",
        updated_at=now - 20.0
    )
    phone_srv.db.set_ownership(expired_lease)

    # Create coordinator pointing to non-existent witness port
    bad_coordinator = FailoverCoordinator(
        node_id=phone_srv.config.node_id,
        cluster_id=phone_srv.config.cluster_id,
        state_machine=phone_srv.state_machine,
        heartbeat_tracker=phone_srv.heartbeat_tracker,
        db=phone_srv.db,
        witness_url="http://127.0.0.1:19999",  # Nothing listening
        witness_secret="test-witness-secret-phase6",
        witness_timeout=0.5
    )

    ok, msg, lease = bad_coordinator.attempt_failover(reason="Testing witness unreachable")
    assert ok is False
    assert "SAFE_MODE" in msg

    # Must be in SAFE_MODE and read-only
    assert phone_srv.state_machine.current_state == STATE_SAFE_MODE
    assert phone_srv.state_machine.is_writable() is False

    # Verify critical audit alert
    events = phone_srv.db.get_recent_audit_events(limit=10)
    denied_events = [e for e in events if e["event_type"] == "FAILOVER_FAILED_WITNESS_DENIED"]
    assert len(denied_events) > 0
    assert denied_events[0]["severity"] == "CRITICAL"


def test_database_corruption_aborts_promotion(failover_test_env):
    """
    Task 4: Database physical integrity check (PRAGMA integrity_check) must pass.
    If integrity fails, fail closed into SAFE_MODE.
    """
    phone_srv: PhoneServer = failover_test_env["phone_srv"]

    # Reset state to SUSPECTED_OFFLINE
    phone_srv.state_machine._state = STATE_SUSPECTED_OFFLINE

    # Expire previous lease
    now = time.time()
    expired_lease = OwnershipRecord(
        cluster_id=phone_srv.config.cluster_id,
        owner_node_id="laptop",
        epoch=1,
        lease_id="laptop-expired-lease",
        lease_expires_at=now - 10.0,
        granted_by="witness",
        signature="sig-expired",
        updated_at=now - 20.0
    )
    phone_srv.db.set_ownership(expired_lease)

    # Temporarily mock verify_full_integrity to simulate database corruption
    original_verify = phone_srv.db.verify_full_integrity
    phone_srv.db.verify_full_integrity = lambda: (False, "Simulated disk page corruption in table 'portfolio_inquiries'")

    try:
        ok, msg, lease = phone_srv.failover_coordinator.attempt_failover(reason="Testing integrity failure")
        assert ok is False
        assert "SAFE_MODE" in msg
        assert "integrity check failed" in msg

        # Must fail closed to SAFE_MODE
        assert phone_srv.state_machine.current_state == STATE_SAFE_MODE
        assert phone_srv.state_machine.is_writable() is False

        # Verify audit alert
        events = phone_srv.db.get_recent_audit_events(limit=10)
        corrupt_events = [e for e in events if e["event_type"] == "DATABASE_INTEGRITY_CHECK_FAILED"]
        assert len(corrupt_events) > 0
        assert corrupt_events[0]["severity"] == "CRITICAL"
    finally:
        phone_srv.db.verify_full_integrity = original_verify


def test_safe_scenario_promotes_end_to_end(failover_test_env):
    """
    Task 4: If approved by witness and DB integrity passes:
    - Acquire lease with epoch N+1.
    - Persist it atomically BEFORE enabling writes.
    - Verify SQLite integrity.
    - Enter SECONDARY_ACTIVE.
    - Writes enabled and outbox rows generated atomically.
    """
    phone_srv: PhoneServer = failover_test_env["phone_srv"]
    witness_srv: WitnessServer = failover_test_env["witness_srv"]

    # Reset witness state: no unexpired lease for laptop
    with witness_srv.witness_state._lock:
        witness_srv.witness_state.current_lease = None
        witness_srv.witness_state.current_epoch = 1

    # Reset phone state to SUSPECTED_OFFLINE with expired laptop lease
    now = time.time()
    phone_srv.state_machine._state = STATE_SUSPECTED_OFFLINE
    phone_srv.state_machine._epoch = 1

    expired_lease = OwnershipRecord(
        cluster_id=phone_srv.config.cluster_id,
        owner_node_id="laptop",
        epoch=1,
        lease_id="laptop-expired-01",
        lease_expires_at=now - 5.0,  # Safely expired
        granted_by="witness",
        signature="sig-expired",
        updated_at=now - 20.0
    )
    phone_srv.db.set_ownership(expired_lease)

    # Execute failover
    ok, msg, lease_info = phone_srv.failover_coordinator.attempt_failover(reason="Laptop offline confirmed, promoting Phone")
    assert ok is True
    assert "Promotion successful" in msg
    assert lease_info is not None
    assert lease_info["owner_node_id"] == "phone"
    assert lease_info["epoch"] == 2
    assert lease_info["granted_by"] == "witness"

    # State machine must be SECONDARY_ACTIVE at epoch 2
    assert phone_srv.state_machine.current_state == STATE_SECONDARY_ACTIVE
    assert phone_srv.state_machine.current_epoch == 2
    assert phone_srv.state_machine.is_writable() is True

    # Atomic lease persistence: verify ownership table has new epoch 2 lease
    saved_ownership = phone_srv.db.get_ownership(phone_srv.config.cluster_id)
    assert saved_ownership is not None
    assert saved_ownership.owner_node_id == "phone"
    assert saved_ownership.epoch == 2
    assert saved_ownership.lease_id == lease_info["lease_id"]

    # Verify audit events for each step
    events = phone_srv.db.get_recent_audit_events(limit=10)
    event_types = [e["event_type"] for e in events]
    assert "PROMOTION_PENDING_ENTERED" in event_types
    assert "WITNESS_LEASE_REQUEST_SENT" in event_types
    assert "OWNERSHIP_LEASE_PERSISTED" in event_types
    assert "PROMOTION_SUCCESSFUL_SECONDARY_ACTIVE" in event_types

    # Task 6: During outage, writes must be committed and outbox rows generated
    write_ok, err_c, err_m, op_id = phone_srv.db.submit_inquiry(
        origin_node_id="phone",
        origin_epoch=2,
        name="Outage Client",
        email="client@outage.com",
        subject="Disaster Recovery Inquiry",
        message="Testing phone write acceptance during laptop outage",
        is_primary=phone_srv.state_machine.is_writable(),
        cluster_id=phone_srv.config.cluster_id,
        secret=phone_srv.config.hmac_secret
    )
    assert write_ok is True
    assert op_id is not None

    # Verify inquiry was persisted
    inquiries = phone_srv.db.get_inquiries()
    matching = [i for i in inquiries if i["email"] == "client@outage.com"]
    assert len(matching) == 1
    assert matching[0]["name"] == "Outage Client"

    # Verify change_log row was generated atomically in the same transaction
    pending = phone_srv.db.get_pending_replication_events(origin_node_id="phone", from_sequence=1, limit=10)
    assert len(pending) > 0
    change_row = pending[-1]
    assert change_row["entity_type"] in ("inquiry", "portfolio_inquiries")
    assert change_row["origin_node_id"] == "phone"
    assert change_row["origin_epoch"] == 2
    assert change_row["operation_id"] == op_id


def test_phone_outage_writes_persist_across_restart(failover_test_env):
    """
    Task 6 & 7: Writes committed during outage on Phone survive server/process restart.
    """
    phone_db_path = failover_test_env["phone_db"]
    witness_secret = "test-witness-secret-phase6"

    # Simulate restart by instantiating a completely new PhoneDatabase on the same file
    restarted_db = PhoneDatabase(phone_db_path)
    restarted_db.witness_secret = witness_secret

    # Verify DB health & physical integrity
    is_ready, _ = restarted_db.is_healthy()
    assert is_ready is True
    int_ok, _ = restarted_db.verify_full_integrity()
    assert int_ok is True

    # Verify previous outage inquiry still exists
    inquiries = restarted_db.get_inquiries()
    matching = [i for i in inquiries if i["email"] == "client@outage.com"]
    assert len(matching) == 1

    # Verify ownership record still reflects epoch 2 phone lease
    ownership = restarted_db.get_ownership("sentineldr-cluster-01")
    assert ownership is not None
    assert ownership.owner_node_id == "phone"
    assert ownership.epoch == 2

    # Verify pending outbox rows still intact
    pending = restarted_db.get_pending_replication_events(origin_node_id="phone", from_sequence=1, limit=10)
    assert len(pending) > 0
    assert pending[-1]["origin_epoch"] == 2


def test_recovered_laptop_with_old_epoch_cannot_write(failover_test_env):
    """
    Task 7: When the recovered laptop comes back up with its old epoch 1,
    it must NOT be permitted to write.
    """
    laptop_db: LaptopDatabase = failover_test_env["laptop_db_inst"]
    now = time.time()

    # Case 1: Laptop still has old epoch 1 lease (now superseded or expired)
    expired_old_lease = OwnershipRecord(
        cluster_id="sentineldr-cluster-01",
        owner_node_id="laptop",
        epoch=1,
        lease_id="old-laptop-lease",
        lease_expires_at=now - 50.0,  # Old expired lease
        granted_by="bootstrap",
        signature=sign_ownership_record("sentineldr-cluster-01", "laptop", 1, "old-laptop-lease", now - 50.0, "bootstrap", "test-secret"),
        updated_at=now - 100.0
    )
    laptop_db.set_ownership(expired_old_lease)

    # Attempt write on Laptop with old epoch 1 and expired lease
    ok, err_code, err_msg, _ = laptop_db.submit_inquiry(
        origin_node_id="laptop",
        origin_epoch=1,
        name="Stale Laptop",
        email="laptop@splitbrain.com",
        subject="Attempt Split-Brain Write",
        message="This must be rejected by write guard",
        is_primary=True,  # Even if laptop thinks it's primary!
        cluster_id="sentineldr-cluster-01",
        secret="test-secret"
    )
    assert ok is False
    assert err_code == "FORBIDDEN"
    assert "LEASE_EXPIRED" in (err_msg or "")

    # Case 2: Laptop attempts write with epoch 1 when ownership reflects Phone's epoch 2
    phone_active_lease = OwnershipRecord(
        cluster_id="sentineldr-cluster-01",
        owner_node_id="phone",
        epoch=2,
        lease_id="phone-active-lease",
        lease_expires_at=now + 100.0,
        granted_by="witness",
        signature="sig-witness-phone",
        updated_at=now
    )
    laptop_db.set_ownership(phone_active_lease)

    ok2, err_code2, err_msg2, _ = laptop_db.submit_inquiry(
        origin_node_id="laptop",
        origin_epoch=1,
        name="Stale Laptop",
        email="laptop@splitbrain.com",
        subject="Attempt Split-Brain Write",
        message="This must be rejected by write guard",
        is_primary=True,
        cluster_id="sentineldr-cluster-01",
        secret="test-secret"
    )
    assert ok2 is False
    assert err_code2 == "FORBIDDEN"
    assert "NODE_NOT_OWNER" in (err_msg2 or "") or "STALE_EPOCH" in (err_msg2 or "")


def test_authenticated_failover_endpoint(failover_test_env):
    """
    Task 5: POST /api/v1/peer/failover endpoint:
    - Strongly authenticated (never public).
    - Unauthenticated request is rejected with 401.
    - Bad HMAC signature is rejected with 401.
    - Valid admin key succeeds.
    - Valid peer HMAC succeeds.
    """
    phone_url = failover_test_env["phone_url"]
    phone_srv: PhoneServer = failover_test_env["phone_srv"]
    failover_url = f"{phone_url}{ROUTE_PEER_FAILOVER}"

    # 1. Unauthenticated request -> 401
    req = urllib.request.Request(
        failover_url,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 401
    err_body = json.loads(exc_info.value.read().decode())
    assert err_body["ok"] is False
    assert err_body["error"]["code"] == "UNAUTHORIZED"

    # 2. Tampered HMAC signature -> 401
    headers = {
        "Content-Type": "application/json",
        "X-SDR-Node": "laptop",
        "X-SDR-Timestamp": str(time.time()),
        "X-SDR-Nonce": uuid.uuid4().hex,
        "X-SDR-Epoch": "1",
        "X-SDR-Signature": "tampered-bad-signature"
    }
    req_bad = urllib.request.Request(failover_url, data=b"{}", headers=headers, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req_bad)
    assert exc_info.value.code == 401

    witness_srv: WitnessServer = failover_test_env["witness_srv"]

    # 3. Valid Admin Key Authentication
    # Ensure phone is in SUSPECTED_OFFLINE to accept promotion with expired laptop lease
    with witness_srv.witness_state._lock:
        witness_srv.witness_state.current_lease = None
        witness_srv.witness_state.current_epoch = 1
    phone_srv.state_machine._state = STATE_SUSPECTED_OFFLINE
    phone_srv.state_machine._epoch = 1

    now = time.time()
    expired_lease = OwnershipRecord(
        cluster_id=phone_srv.config.cluster_id,
        owner_node_id="laptop",
        epoch=1,
        lease_id="laptop-expired-auth-01",
        lease_expires_at=now - 5.0,
        granted_by="witness",
        signature="sig-expired",
        updated_at=now - 20.0
    )
    phone_srv.db.set_ownership(expired_lease)

    admin_headers = {
        "Content-Type": "application/json",
        "X-SDR-Admin-Key": phone_srv.config.admin_key,
        "Authorization": f"Bearer {phone_srv.config.admin_key}"
    }
    body = json.dumps({"reason": "Manual operator failover via Admin Key", "force_admin": True}).encode()
    req_admin = urllib.request.Request(failover_url, data=body, headers=admin_headers, method="POST")
    with urllib.request.urlopen(req_admin) as resp:
        assert resp.status == 200
        resp_data = json.loads(resp.read().decode())
        assert resp_data["ok"] is True
        assert resp_data["data"]["status"] == "PROMOTED"
        assert resp_data["data"]["role"] == STATE_SECONDARY_ACTIVE

    # 4. Valid Peer HMAC Request
    # Reset state to SUSPECTED_OFFLINE for test
    with witness_srv.witness_state._lock:
        witness_srv.witness_state.current_lease = None
        witness_srv.witness_state.current_epoch = phone_srv.state_machine.current_epoch
    phone_srv.state_machine._state = STATE_SUSPECTED_OFFLINE
    expired_lease.epoch = phone_srv.state_machine.current_epoch
    phone_srv.db.set_ownership(expired_lease)

    peer_body = json.dumps({"reason": "Automated failover via Peer HMAC"}).encode()
    peer_headers = build_peer_headers(
        node_id="laptop",
        epoch=phone_srv.state_machine.current_epoch,
        method="POST",
        path=ROUTE_PEER_FAILOVER,
        body=peer_body,
        secret=phone_srv.config.hmac_secret
    )
    req_peer = urllib.request.Request(failover_url, data=peer_body, headers=peer_headers, method="POST")
    with urllib.request.urlopen(req_peer) as resp:
        assert resp.status == 200
        resp_data = json.loads(resp.read().decode())
        assert resp_data["ok"] is True
        assert resp_data["data"]["status"] == "PROMOTED"
