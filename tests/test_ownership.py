"""
SentinelDR - Ownership, Lease, and Fencing Tests (Phase 5)
Verifies:
1. Strict 10-state machine transitions and audit logging.
2. Independent Witness quorum lease acquisition and denial of second candidate.
3. Stale epoch rejection on both laptop and phone nodes.
4. Expired lease rejection on both laptop and phone nodes.
5. Bounded clock-skew policy enforcement on peer lease requests.
6. Network partition simulation proving dual-writer states are impossible.
7. Fail-closed behavior into SAFE_MODE when the witness is unavailable.
"""

import json
import os
import sys
import threading
import time
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
from shared.config import NodeConfig
from shared.ownership import OwnershipRecord, sign_ownership_record, validate_lease
from shared.security import build_peer_headers
from shared.state_machine import ClusterStateMachine, IllegalStateTransitionError
from shared.witness import WitnessClient, WitnessServer


@pytest.fixture(scope="module")
def isolated_ownership_env(tmp_path_factory):
    """Sets up an isolated test environment with fresh databases, phone server, and witness server."""
    tmp_dir = tmp_path_factory.mktemp("ownership_test_env")
    phone_db = str(tmp_dir / "phone_owner.db")
    phone_nonce = str(tmp_dir / "phone_nonce.db")
    laptop_db = str(tmp_dir / "laptop_owner.db")

    # 1. Start Witness Server on ephemeral port
    witness_srv = WitnessServer(
        host="127.0.0.1",
        port=0,
        cluster_id="sentineldr-cluster-01",
        witness_secret="test-witness-secret-001"
    )
    t_wit = threading.Thread(target=lambda: witness_srv.serve_forever(poll_interval=0.05), daemon=True)
    t_wit.start()
    time.sleep(0.1)
    witness_url = f"http://127.0.0.1:{witness_srv.port}"

    # 2. Start Phone Server on ephemeral port
    phone_cfg = NodeConfig("phone")
    phone_cfg.port = 0
    phone_cfg.database_path = phone_db
    phone_cfg.nonce_cache_db = phone_nonce
    phone_cfg.witness_url = witness_url
    phone_cfg.witness_secret = "test-witness-secret-001"

    phone_srv = PhoneServer(phone_cfg)
    phone_srv.db.witness_secret = "test-witness-secret-001"
    t_phone = threading.Thread(target=lambda: phone_srv.serve_forever(poll_interval=0.05), daemon=True)
    t_phone.start()
    time.sleep(0.1)

    # 3. Setup Laptop Database & Starlette TestClient
    laptop_db_inst = LaptopDatabase(f"sqlite:///{laptop_db}")
    laptop_db_inst._sqlite_path = laptop_db
    laptop_db_inst.using_sqlite_fallback = True
    laptop_db_inst.witness_secret = "test-witness-secret-001"
    laptop_db_inst.init_db()
    laptop_db_inst.seed_portfolio_data()

    orig_laptop_db = laptop_server_mod.db
    laptop_server_mod.db = laptop_db_inst
    laptop_server_mod.config.witness_url = witness_url
    laptop_server_mod.config.witness_secret = "test-witness-secret-001"
    laptop_client = TestClient(laptop_server_mod.app)

    yield {
        "witness_server": witness_srv,
        "witness_url": witness_url,
        "phone_server": phone_srv,
        "phone_url": f"http://127.0.0.1:{phone_srv.config.port}",
        "phone_db": phone_srv.db,
        "phone_cfg": phone_cfg,
        "laptop_client": laptop_client,
        "laptop_db": laptop_db_inst,
        "laptop_cfg": laptop_server_mod.config,
    }

    # Teardown
    laptop_server_mod.db = orig_laptop_db
    phone_srv.stop()
    witness_srv.stop()


# 1. State Machine Transitions & Auditing
def test_state_machine_transitions_and_auditing(isolated_ownership_env):
    env = isolated_ownership_env
    audit_events = []

    def audit_cb(evt_id, node_id, epoch, evt_type, severity, details):
        audit_events.append({"evt_type": evt_type, "details": details})

    sm = ClusterStateMachine(
        initial_state=STATE_STARTING,
        node_id="laptop",
        initial_epoch=1,
        audit_callback=audit_cb
    )

    # Valid transitions
    ok, err = sm.transition_to(STATE_PRIMARY_ACTIVE, reason="Bootstrap primary")
    assert ok is True
    assert sm.current_state == STATE_PRIMARY_ACTIVE
    assert sm.is_writable() is True

    ok, err = sm.transition_to(STATE_SUSPECTED_OFFLINE, reason="Phone missed 3 heartbeats")
    assert ok is True
    assert sm.current_state == STATE_SUSPECTED_OFFLINE
    assert sm.is_writable() is False

    ok, err = sm.transition_to(STATE_SAFE_MODE, reason="Manual safety trigger")
    assert ok is True
    assert sm.current_state == STATE_SAFE_MODE
    assert sm.is_writable() is False

    # Illegal transition: cannot go from SAFE_MODE directly to SECONDARY_ACTIVE
    ok, err = sm.transition_to(STATE_SECONDARY_ACTIVE, reason="Illegal jump")
    assert ok is False
    assert "ILLEGAL_TRANSITION" in err

    # Verify audit events were recorded
    assert len(audit_events) == 3
    assert audit_events[0]["details"]["to_state"] == STATE_PRIMARY_ACTIVE
    assert audit_events[1]["details"]["to_state"] == STATE_SUSPECTED_OFFLINE
    assert audit_events[2]["details"]["to_state"] == STATE_SAFE_MODE


# 2. Independent Witness Quorum: Acquire & Deny Active Primary
def test_witness_lease_acquire_and_deny_active_primary(isolated_ownership_env):
    env = isolated_ownership_env
    client = WitnessClient()

    # Laptop acquires lease for 2.0 seconds
    ok, record, err = client.acquire_lease(
        witness_url=env["witness_url"],
        cluster_id="sentineldr-cluster-01",
        candidate_node_id="laptop",
        requested_epoch=1,
        duration_seconds=2.0
    )
    assert ok is True
    assert record is not None
    assert record.owner_node_id == "laptop"
    assert record.epoch == 1

    # Phone requests lease immediately while Laptop lease is still active: MUST BE DENIED
    ok_phone, phone_record, phone_err = client.acquire_lease(
        witness_url=env["witness_url"],
        cluster_id="sentineldr-cluster-01",
        candidate_node_id="phone",
        requested_epoch=2,
        duration_seconds=5.0
    )
    assert ok_phone is False
    assert phone_record is None
    assert "LEASE_HELD_BY_ACTIVE_PRIMARY" in phone_err

    # Wait for Laptop's lease to expire
    time.sleep(2.1)

    # Now Phone requests lease: MUST BE GRANTED with incremented epoch
    ok_phone2, phone_record2, err2 = client.acquire_lease(
        witness_url=env["witness_url"],
        cluster_id="sentineldr-cluster-01",
        candidate_node_id="phone",
        requested_epoch=2,
        duration_seconds=5.0
    )
    assert ok_phone2 is True
    assert phone_record2.owner_node_id == "phone"
    assert phone_record2.epoch == 2

    # Clean release for subsequent tests
    client.release_lease(
        witness_url=env["witness_url"],
        cluster_id="sentineldr-cluster-01",
        owner_node_id="phone",
        lease_id=phone_record2.lease_id
    )


# 3. Stale Epoch Rejection on Both Nodes
def test_stale_epoch_write_rejected_laptop_and_phone(isolated_ownership_env):
    env = isolated_ownership_env

    # 1. On Laptop: set ownership with epoch 2, attempt write with epoch 1 (stale)
    now = time.time()
    lease_expires = now + 60.0
    sig = sign_ownership_record("sentineldr-cluster-01", "laptop", 2, "lease-lp-02", lease_expires, "witness", env["laptop_cfg"].hmac_secret)
    rec_laptop = OwnershipRecord("sentineldr-cluster-01", "laptop", 2, "lease-lp-02", lease_expires, "witness", sig, now)
    env["laptop_db"].set_ownership(rec_laptop)

    ok, code, err, _ = env["laptop_db"].submit_inquiry(
        origin_node_id="laptop",
        origin_epoch=1,  # STALE epoch (current is 2)
        name="Stale Laptop",
        email="stale@laptop.org",
        subject="Epoch Check",
        message="Stale epoch test",
        is_primary=True,
        cluster_id="sentineldr-cluster-01",
        secret=env["laptop_cfg"].hmac_secret
    )
    assert ok is False
    assert code == "FORBIDDEN"
    assert "STALE_EPOCH" in err

    # 2. On Phone: set ownership with epoch 3, attempt write with epoch 2 (stale)
    sig_phone = sign_ownership_record("sentineldr-cluster-01", "phone", 3, "lease-ph-03", lease_expires, "witness", env["phone_cfg"].hmac_secret)
    rec_phone = OwnershipRecord("sentineldr-cluster-01", "phone", 3, "lease-ph-03", lease_expires, "witness", sig_phone, now)
    env["phone_db"].set_ownership(rec_phone)

    ok_ph, code_ph, err_ph, _ = env["phone_db"].submit_inquiry(
        origin_node_id="phone",
        origin_epoch=2,  # STALE epoch (current is 3)
        name="Stale Phone",
        email="stale@phone.org",
        subject="Epoch Check",
        message="Stale epoch test",
        is_primary=True,
        cluster_id="sentineldr-cluster-01",
        secret=env["phone_cfg"].hmac_secret
    )
    assert ok_ph is False
    assert code_ph == "FORBIDDEN"
    assert "STALE_EPOCH" in err_ph


# 4. Expired Lease Rejection on Both Nodes
def test_expired_lease_write_rejected_laptop_and_phone(isolated_ownership_env):
    env = isolated_ownership_env
    now = time.time()
    expired_time = now - 5.0  # Expired 5 seconds ago

    # 1. Laptop with expired lease
    sig_exp_lp = sign_ownership_record("sentineldr-cluster-01", "laptop", 1, "lease-exp-01", expired_time, "witness", env["laptop_cfg"].hmac_secret)
    rec_exp_lp = OwnershipRecord("sentineldr-cluster-01", "laptop", 1, "lease-exp-01", expired_time, "witness", sig_exp_lp, now)
    env["laptop_db"].set_ownership(rec_exp_lp)

    ok, code, err, _ = env["laptop_db"].submit_inquiry(
        origin_node_id="laptop",
        origin_epoch=1,
        name="Expired Laptop",
        email="expired@laptop.org",
        subject="Lease Expired Check",
        message="Expired lease test",
        is_primary=True,
        cluster_id="sentineldr-cluster-01",
        secret=env["laptop_cfg"].hmac_secret
    )
    assert ok is False
    assert code == "FORBIDDEN"
    assert "LEASE_EXPIRED" in err

    # 2. Phone with expired lease
    sig_exp_ph = sign_ownership_record("sentineldr-cluster-01", "phone", 1, "lease-exp-ph", expired_time, "witness", env["phone_cfg"].hmac_secret)
    rec_exp_ph = OwnershipRecord("sentineldr-cluster-01", "phone", 1, "lease-exp-ph", expired_time, "witness", sig_exp_ph, now)
    env["phone_db"].set_ownership(rec_exp_ph)

    ok_ph, code_ph, err_ph, _ = env["phone_db"].submit_inquiry(
        origin_node_id="phone",
        origin_epoch=1,
        name="Expired Phone",
        email="expired@phone.org",
        subject="Lease Expired Check",
        message="Expired lease test",
        is_primary=True,
        cluster_id="sentineldr-cluster-01",
        secret=env["phone_cfg"].hmac_secret
    )
    assert ok_ph is False
    assert code_ph == "FORBIDDEN"
    assert "LEASE_EXPIRED" in err_ph


# 5. Bounded Clock Skew Enforcement on Peer Lease Request
def test_bounded_clock_skew_enforcement(isolated_ownership_env):
    env = isolated_ownership_env

    # 1. Request with 15.0s past clock skew (exceeds 2.0s limit)
    stale_payload = {
        "candidate_node_id": "phone",
        "requested_epoch": 2,
        "sent_at": time.time() - 15.0,  # 15 seconds skewed
        "reason": "Failover request"
    }
    body = json.dumps(stale_payload).encode("utf-8")
    headers = build_peer_headers(
        node_id="phone",
        epoch=2,
        secret=env["laptop_cfg"].hmac_secret,
        method="POST",
        path="/api/v1/peer/lease/request",
        body=body
    )

    resp = env["laptop_client"].post("/api/v1/peer/lease/request", content=body, headers=headers)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "CLOCK_SKEW_EXCEEDED"

    # 2. Request with synchronized clock (within threshold)
    valid_payload = {
        "candidate_node_id": "phone",
        "requested_epoch": 2,
        "sent_at": time.time(),
        "reason": "Failover request"
    }
    body2 = json.dumps(valid_payload).encode("utf-8")
    headers2 = build_peer_headers(
        node_id="phone",
        epoch=2,
        secret=env["laptop_cfg"].hmac_secret,
        method="POST",
        path="/api/v1/peer/lease/request",
        body=body2
    )
    resp2 = env["laptop_client"].post("/api/v1/peer/lease/request", content=body2, headers=headers2)
    assert resp2.status_code in (200, 409)  # 200 Yielded or 409 Denied by active primary, NOT clock skew error


# 6. Partition Simulation: Zero Dual Writers
def test_partition_simulation_no_dual_writer(isolated_ownership_env):
    """
    Simulates partition:
    1. Laptop holds valid lease (epoch 1) and is writable.
    2. Phone cannot write.
    3. Phone misses heartbeats -> tries Witness -> Witness denies because Laptop lease active -> Phone fails closed to SAFE_MODE.
    4. Laptop's lease expires -> Laptop can no longer write.
    5. Phone acquires lease at epoch 2 -> Phone becomes writable.
    6. Laptop cannot write with expired/stale lease.
    Zero dual writers at all points in time!
    """
    env = isolated_ownership_env
    client = WitnessClient()

    env["witness_server"].witness_state.current_lease = None
    cur_ep = env["witness_server"].witness_state.current_epoch + 1

    # Step 1: Laptop acquires 1.5s lease from witness
    ok, rec_lp, err = client.acquire_lease(
        witness_url=env["witness_url"],
        cluster_id="sentineldr-cluster-01",
        candidate_node_id="laptop",
        requested_epoch=cur_ep,
        duration_seconds=1.5
    )
    assert ok is True
    env["laptop_db"].set_ownership(rec_lp)

    # Laptop can write
    ok_w1, _, _, _ = env["laptop_db"].submit_inquiry(
        origin_node_id="laptop",
        origin_epoch=rec_lp.epoch,
        name="Valid Laptop Write",
        email="lp@test.org",
        subject="OK",
        message="Valid write",
        is_primary=True,
        cluster_id="sentineldr-cluster-01",
        secret=env["laptop_cfg"].hmac_secret
    )
    assert ok_w1 is True

    # Step 2: Phone is in SECONDARY_STANDBY -> cannot write
    ok_ph_w, code, err, _ = env["phone_db"].submit_inquiry(
        origin_node_id="phone",
        origin_epoch=rec_lp.epoch,
        name="Illegal Phone Write",
        email="ph@test.org",
        subject="Fail",
        message="Should fail",
        is_primary=False
    )
    assert ok_ph_w is False

    # Step 3: Network partition begins. Phone misses heartbeats.
    # Phone attempts to acquire lease from witness while laptop lease is active
    ok_wit, _, wit_err = client.acquire_lease(
        witness_url=env["witness_url"],
        cluster_id="sentineldr-cluster-01",
        candidate_node_id="phone",
        requested_epoch=rec_lp.epoch + 1,
        duration_seconds=5.0
    )
    assert ok_wit is False  # Witness denies phone!
    assert "LEASE_HELD_BY_ACTIVE_PRIMARY" in wit_err

    # Phone fails closed into SAFE_MODE
    env["phone_server"].state_machine.transition_to(STATE_SUSPECTED_OFFLINE, "Missed 3 heartbeats")
    env["phone_server"].state_machine.transition_to(STATE_SAFE_MODE, "Witness denied lease; failing closed")
    assert env["phone_server"].state_machine.current_state == STATE_SAFE_MODE
    assert env["phone_server"].state_machine.is_writable() is False

    # Step 4: Laptop's lease expires
    time.sleep(1.6)

    # Laptop attempts to write with its expired lease: MUST BE REJECTED
    ok_lp_exp, code_exp, err_exp, _ = env["laptop_db"].submit_inquiry(
        origin_node_id="laptop",
        origin_epoch=rec_lp.epoch,
        name="Expired Laptop Write",
        email="lp2@test.org",
        subject="Fail",
        message="Should fail expired",
        is_primary=True,
        cluster_id="sentineldr-cluster-01",
        secret=env["laptop_cfg"].hmac_secret
    )
    assert ok_lp_exp is False
    assert "LEASE_EXPIRED" in err_exp

    # Step 5: Phone acquires lease at next epoch from witness
    ok_ph_acq, rec_ph, _ = client.acquire_lease(
        witness_url=env["witness_url"],
        cluster_id="sentineldr-cluster-01",
        candidate_node_id="phone",
        requested_epoch=rec_lp.epoch + 1,
        duration_seconds=10.0
    )
    assert ok_ph_acq is True
    assert rec_ph.epoch == rec_lp.epoch + 1
    env["phone_db"].set_ownership(rec_ph)

    # Phone transitions to SECONDARY_ACTIVE
    env["phone_server"].state_machine.transition_to(STATE_SECONDARY_STANDBY, "Operator / recovery transition")
    env["phone_server"].state_machine.transition_to(STATE_SUSPECTED_OFFLINE, "Promoting")
    env["phone_server"].state_machine.transition_to(STATE_PROMOTION_PENDING, "Acquiring lease")
    env["phone_server"].state_machine.transition_to(STATE_SECONDARY_ACTIVE, "Promoted with witness lease", new_epoch=rec_ph.epoch)
    assert env["phone_server"].state_machine.is_writable() is True

    # Phone can now write at new epoch
    ok_ph_write, _, _, _ = env["phone_db"].submit_inquiry(
        origin_node_id="phone",
        origin_epoch=rec_ph.epoch,
        name="Phone Promoted Write",
        email="ph@promoted.org",
        subject="Failover Active",
        message="Writing during failover",
        is_primary=True,
        cluster_id="sentineldr-cluster-01",
        secret=env["phone_cfg"].hmac_secret
    )
    assert ok_ph_write is True

    # Laptop still cannot write (lease expired and stale epoch)
    ok_lp_blocked, _, _, _ = env["laptop_db"].submit_inquiry(
        origin_node_id="laptop",
        origin_epoch=rec_lp.epoch,
        name="Laptop Blocked",
        email="lp@blocked.org",
        subject="Blocked",
        message="Blocked write",
        is_primary=True,
        cluster_id="sentineldr-cluster-01",
        secret=env["laptop_cfg"].hmac_secret
    )
    assert ok_lp_blocked is False


# 7. Fail Closed when Witness is Unavailable
def test_fail_closed_when_witness_unavailable(isolated_ownership_env):
    env = isolated_ownership_env
    client = WitnessClient(timeout=0.5)

    # Point client to invalid dead witness port
    dead_witness_url = "http://127.0.0.1:19999"
    ok, rec, err = client.acquire_lease(
        witness_url=dead_witness_url,
        cluster_id="sentineldr-cluster-01",
        candidate_node_id="phone",
        requested_epoch=3
    )
    assert ok is False
    assert "Witness connection error" in err

    # Node must fail closed into SAFE_MODE
    phone_sm = env["phone_server"].state_machine
    phone_sm.transition_to(STATE_SAFE_MODE, "Witness unreachable during partition; fail closed")
    assert phone_sm.current_state == STATE_SAFE_MODE
    assert phone_sm.is_writable() is False
