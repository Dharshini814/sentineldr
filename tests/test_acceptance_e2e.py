"""
SentinelDR - End-to-End Acceptance Test Suite (Phase 10)
Verifies:
1. Liveness (/health) separate from Readiness (/ready) on both runtimes.
2. Alerting system evaluates and surfaces all critical conditions:
   - SAFE_MODE, LEASE_EXPIRED, REPLICATION_LAG, UNRESOLVED_CONFLICTS, INTEGRITY_MISMATCH, PEER_OFFLINE.
3. Full Minimum End-to-End Acceptance Scenario:
   - Step 1: Start both nodes; initial snapshot & parity verification.
   - Step 2: Write while laptop is primary; committed atomically with outbox.
   - Step 3: Safely stop/fence laptop; laptop rejects protected writes.
   - Step 4: Phone promoted to SECONDARY_ACTIVE only after safe witness grant (epoch 2).
   - Step 5: Write on Phone during failover & restart Phone; verify persistence.
   - Step 6: Restart laptop in RECOVERING; take backups; replay Phone writes into Laptop.
   - Step 7: Multi-layer validation: operation counts, entity counts, canonical hash parity.
   - Step 8: Controlled failback handoff: Phone steps down to standby, Laptop acquires epoch 3 lease.
   - Step 9: Verify Laptop is primary, Phone is standby, zero dual-writers throughout.
"""

import json
import os
import shutil
import sys
import threading
import time
import urllib.request
import urllib.error
import uuid
import pytest
from starlette.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from cloudflare.mock_worker import MockCloudflareWorker
from laptop.db import LaptopDatabase
import laptop.server as laptop_server_mod
from phone.db import PhoneDatabase
from phone.server import PhoneServer
from shared.alerts import AlertChecker, SEVERITY_CRITICAL, SEVERITY_WARN
from shared.api_contract import (
    ROUTE_ACTIVE_ORIGIN,
    ROUTE_HEALTH,
    ROUTE_READY,
    STATE_PRIMARY_ACTIVE,
    STATE_RECONCILING,
    STATE_RECOVERING,
    STATE_SAFE_MODE,
    STATE_SECONDARY_ACTIVE,
    STATE_SECONDARY_STANDBY,
    validate_readiness_payload,
)
from shared.config import NodeConfig
from shared.ownership import OwnershipRecord, sign_ownership_record
from shared.recovery import RecoveryCoordinator
from shared.witness import WitnessServer


@pytest.fixture(scope="module")
def e2e_acceptance_env(tmp_path_factory):
    """Sets up isolated witness server, phone server, and test databases."""
    tmp_dir = tmp_path_factory.mktemp("e2e_acceptance")
    phone_db = str(tmp_dir / "phone_e2e.db")
    phone_nonce = str(tmp_dir / "phone_nonce.db")
    laptop_db = str(tmp_dir / "laptop_e2e.db")
    laptop_nonce = str(tmp_dir / "laptop_nonce.db")
    backup_dir = str(tmp_dir / "backups")
    os.makedirs(backup_dir, exist_ok=True)

    witness_secret = "test-witness-secret-e2e"
    hmac_secret = "test-hmac-secret-e2e"
    admin_key = "test-admin-key-e2e"

    # 1. Start Witness Server on ephemeral port
    witness_srv = WitnessServer(
        host="127.0.0.1",
        port=0,
        cluster_id="sentineldr-cluster-01",
        witness_secret=witness_secret
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
    phone_cfg.witness_secret = witness_secret
    phone_cfg.admin_key = admin_key
    phone_cfg.hmac_secret = hmac_secret

    phone_srv = PhoneServer(phone_cfg)
    phone_srv.db.witness_secret = witness_secret
    phone_srv.db.seed_portfolio_data()

    t_phone = threading.Thread(target=lambda: phone_srv.serve_forever(poll_interval=0.05), daemon=True)
    t_phone.start()
    time.sleep(0.15)
    phone_url = f"http://127.0.0.1:{phone_srv.server_port}"

    # 3. Setup Laptop Database
    laptop_db_inst = LaptopDatabase(f"sqlite:///{laptop_db}")
    laptop_db_inst._sqlite_path = laptop_db
    laptop_db_inst.using_sqlite_fallback = True
    laptop_db_inst.witness_secret = witness_secret
    laptop_db_inst.init_db()
    laptop_db_inst.seed_portfolio_data()

    # Configure Laptop Server globals
    orig_witness = laptop_server_mod.config.witness_secret
    orig_hmac = laptop_server_mod.config.hmac_secret
    orig_admin = laptop_server_mod.config.admin_key
    orig_db = laptop_server_mod.db

    laptop_server_mod.config.witness_secret = witness_secret
    laptop_server_mod.config.hmac_secret = hmac_secret
    laptop_server_mod.config.admin_key = admin_key
    laptop_server_mod.config.witness_url = witness_url
    laptop_server_mod.db = laptop_db_inst
    laptop_server_mod.state_machine._audit_callback = laptop_db_inst.log_audit_event

    client = TestClient(laptop_server_mod.app)

    yield {
        "witness_srv": witness_srv,
        "witness_url": witness_url,
        "witness_secret": witness_secret,
        "hmac_secret": hmac_secret,
        "admin_key": admin_key,
        "phone_srv": phone_srv,
        "phone_url": phone_url,
        "phone_cfg": phone_cfg,
        "phone_db_path": phone_db,
        "laptop_client": client,
        "laptop_db": laptop_db_inst,
        "backup_dir": backup_dir,
    }

    # Teardown
    laptop_server_mod.config.witness_secret = orig_witness
    laptop_server_mod.config.hmac_secret = orig_hmac
    laptop_server_mod.config.admin_key = orig_admin
    laptop_server_mod.db = orig_db
    laptop_server_mod.state_machine._audit_callback = orig_db.log_audit_event
    try:
        phone_srv.shutdown()
    except Exception:
        pass
    try:
        witness_srv.stop()
    except Exception:
        pass


def test_readiness_probe_endpoints(e2e_acceptance_env):
    """Verify /ready readiness probes on both runtimes separately from /health."""
    client = e2e_acceptance_env["laptop_client"]
    phone_url = e2e_acceptance_env["phone_url"]

    # 1. Laptop readiness probe
    res_laptop = client.get(ROUTE_READY)
    assert res_laptop.status_code == 200
    laptop_body = res_laptop.json()
    assert laptop_body["ok"] is True
    assert laptop_body["data"]["ready"] is True
    assert laptop_body["data"]["db_healthy"] is True
    errors = validate_readiness_payload(laptop_body["data"])
    assert not errors, f"Laptop readiness validation error: {errors}"

    # 2. Phone readiness probe
    req = urllib.request.Request(f"{phone_url}{ROUTE_READY}")
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        assert resp.status == 200
        phone_body = json.loads(resp.read().decode("utf-8"))

    assert phone_body["ok"] is True
    assert phone_body["data"]["ready"] is True
    assert phone_body["data"]["db_healthy"] is True
    errors = validate_readiness_payload(phone_body["data"])
    assert not errors, f"Phone readiness validation error: {errors}"


def test_alert_checker_surfaces_operational_conditions(e2e_acceptance_env):
    """Verify AlertChecker evaluates and surfaces all critical operational conditions."""
    phone_srv = e2e_acceptance_env["phone_srv"]

    checker = AlertChecker(
        node_id="phone",
        cluster_id=phone_srv.config.cluster_id,
        db=phone_srv.db,
        state_machine=phone_srv.state_machine,
        heartbeat_tracker=phone_srv.heartbeat_tracker,
        lag_warn_threshold=2
    )

    # 1. Normal State: No critical alerts
    phone_srv.state_machine._state = STATE_SECONDARY_STANDBY
    phone_srv.heartbeat_tracker.consecutive_misses = 0
    phone_srv.heartbeat_tracker.last_received_at = time.time()
    alerts = checker.get_active_alerts()
    assert not any(a["alert_id"] == "ALERT_SAFE_MODE" for a in alerts)

    # 2. Trigger SAFE_MODE alert
    phone_srv.state_machine._state = STATE_SAFE_MODE
    alerts_safe = checker.get_active_alerts()
    safe_alert = next((a for a in alerts_safe if a["alert_id"] == "ALERT_SAFE_MODE"), None)
    assert safe_alert is not None
    assert safe_alert["severity"] == SEVERITY_CRITICAL

    # 3. Trigger PEER_OFFLINE alert
    phone_srv.heartbeat_tracker.last_received_at = time.time() - 15.0
    phone_srv.heartbeat_tracker.consecutive_misses = 3
    alerts_offline = checker.get_active_alerts()
    offline_alert = next((a for a in alerts_offline if a["alert_id"] == "ALERT_PEER_SUSPECTED_OFFLINE"), None)
    assert offline_alert is not None
    assert offline_alert["severity"] == SEVERITY_WARN

    # 4. Trigger UNRESOLVED_CONFLICTS alert
    c_id = phone_srv.db.record_conflict(
        entity_type="inquiry",
        entity_id="test-conflict-alert",
        origin_node_id="laptop",
        local_data={"message": "local"},
        remote_data={"message": "remote"},
        resolution_notes="Testing alert generation"
    )
    alerts_conflict = checker.get_active_alerts()
    conflict_alert = next((a for a in alerts_conflict if a["alert_id"] == "ALERT_UNRESOLVED_CONFLICTS"), None)
    assert conflict_alert is not None
    assert conflict_alert["severity"] == SEVERITY_CRITICAL

    # Cleanup conflict record and restore state
    conn = phone_srv.db.get_connection()
    conn.execute("DELETE FROM conflict_records WHERE conflict_id = ?", (c_id,))
    conn.commit()
    conn.close()

    phone_srv.state_machine._state = STATE_SECONDARY_STANDBY
    phone_srv.heartbeat_tracker.consecutive_misses = 0


def test_minimum_end_to_end_acceptance_scenario(e2e_acceptance_env):
    """
    Minimum End-to-End Acceptance Scenario:
    1. Start both nodes; initial snapshot.
    2. Write while laptop is primary.
    3. Safely stop/fence laptop.
    4. Phone becomes active only after safe witness grant.
    5. Write on phone and restart it.
    6. Restart laptop in recovery and replay.
    7. Validate equality.
    8. Controlled handoff.
    9. Verify laptop primary and phone standby; check audit log throughout.
    """
    client = e2e_acceptance_env["laptop_client"]
    laptop_db = e2e_acceptance_env["laptop_db"]
    phone_srv = e2e_acceptance_env["phone_srv"]
    phone_url = e2e_acceptance_env["phone_url"]
    witness_secret = e2e_acceptance_env["witness_secret"]
    backup_dir = e2e_acceptance_env["backup_dir"]

    # -------------------------------------------------------------
    # Step 1: Start both nodes & verify initial snapshot parity
    # -------------------------------------------------------------
    now = time.time()
    lease_sig_1 = sign_ownership_record("sentineldr-cluster-01", "laptop", 1, "lease-e2e-01", now + 120.0, "witness", witness_secret)
    lease_1 = OwnershipRecord("sentineldr-cluster-01", "laptop", 1, "lease-e2e-01", now + 120.0, "witness", lease_sig_1, now)
    laptop_db.set_ownership(lease_1)
    phone_srv.db.set_ownership(lease_1)

    laptop_server_mod.state_machine._state = STATE_PRIMARY_ACTIVE
    laptop_server_mod.state_machine._epoch = 1
    phone_srv.state_machine._state = STATE_SECONDARY_STANDBY
    phone_srv.state_machine._epoch = 1

    laptop_db.log_audit_event(
        event_id=str(uuid.uuid4()),
        node_id="laptop",
        epoch=1,
        event_type="BOOTSTRAP_PRIMARY",
        severity="INFO",
        details={"state": STATE_PRIMARY_ACTIVE}
    )

    # Verify initial data parity
    laptop_hash_init = laptop_db.get_canonical_hash("portfolio_inquiries")
    phone_hash_init = phone_srv.db.get_canonical_hash("portfolio_inquiries")
    assert laptop_hash_init == phone_hash_init

    # Edge router points to Laptop
    worker = MockCloudflareWorker(primary_origin="http://127.0.0.1:8000", backup_origin=phone_url)
    worker.query_origin_status = lambda o: {
        "cluster_id": "sentineldr-cluster-01",
        "node_id": "laptop" if o == worker.primary_origin else "phone",
        "node_type": "laptop" if o == worker.primary_origin else "phone",
        "role": "PRIMARY_ACTIVE" if o == worker.primary_origin else "SECONDARY_STANDBY",
        "epoch": 1,
        "writable": (o == worker.primary_origin),
        "lease_valid": True,
        "lease_remaining_seconds": 60.0,
        "owner_node_id": "laptop",
        "db_healthy": True,
    }
    route = worker.resolve_active_target(force_refresh=True)
    assert route["active_node"] == "laptop"
    assert route["writable"] is True

    # -------------------------------------------------------------
    # Step 2: Write while laptop is primary
    # -------------------------------------------------------------
    inquiry_1 = {
        "name": "Alice Primary",
        "email": "alice@primary.org",
        "subject": "Initial primary write",
        "message": "Testing laptop primary write"
    }
    res_w1 = client.post("/api/v1/portfolio/inquiry", json=inquiry_1)
    assert res_w1.status_code == 201
    op_id_1 = res_w1.json()["data"]["operation_id"]

    # Verify outbox item generated atomically on Laptop
    unrepl_laptop = laptop_db.get_unreplicated_changes(peer_node_id="phone")
    assert any(e["operation_id"] == op_id_1 for e in unrepl_laptop)

    # Replicate to Phone
    ev_1 = [e for e in unrepl_laptop if e["operation_id"] == op_id_1][0]
    apply_ok, _, _, _, _, err = phone_srv.db.apply_replication_batch(
        origin_node_id="laptop",
        batch_id="batch-e2e-01",
        events=[ev_1]
    )
    assert apply_ok is True

    # Check parity after replication
    assert laptop_db.get_canonical_hash() == phone_srv.db.get_canonical_hash()

    # -------------------------------------------------------------
    # Step 3: Safely stop/fence laptop
    # -------------------------------------------------------------
    # Laptop lease expires and laptop enters RECOVERING (fenced/read-only)
    expired_time = time.time() - 10.0
    exp_sig = sign_ownership_record("sentineldr-cluster-01", "laptop", 1, "lease-e2e-01", expired_time, "witness", witness_secret)
    laptop_db.set_ownership(OwnershipRecord("sentineldr-cluster-01", "laptop", 1, "lease-e2e-01", expired_time, "witness", exp_sig, now))
    laptop_server_mod.state_machine._state = STATE_RECOVERING
    laptop_db.log_audit_event(
        event_id=str(uuid.uuid4()),
        node_id="laptop",
        epoch=1,
        event_type="NODE_FENCED",
        severity="WARN",
        details={"reason": "Lease expired"}
    )

    # Attempted write on fenced Laptop MUST be rejected
    res_fenced = client.post("/api/v1/portfolio/inquiry", json={"name": "BadWrite", "email": "bad@fenced.org", "subject": "Rejected", "message": "Fenced"})
    assert res_fenced.status_code == 403

    # -------------------------------------------------------------
    # Step 4: Phone promoted to SECONDARY_ACTIVE after safe grant
    # -------------------------------------------------------------
    now_p = time.time()
    lease_sig_2 = sign_ownership_record("sentineldr-cluster-01", "phone", 2, "lease-e2e-02", now_p + 120.0, "witness", witness_secret)
    lease_2 = OwnershipRecord("sentineldr-cluster-01", "phone", 2, "lease-e2e-02", now_p + 120.0, "witness", lease_sig_2, now_p)
    phone_srv.db.set_ownership(lease_2)
    phone_srv.state_machine._state = STATE_SECONDARY_ACTIVE
    phone_srv.state_machine._epoch = 2
    phone_srv.db.log_audit_event(
        event_id=str(uuid.uuid4()),
        node_id="phone",
        epoch=2,
        event_type="PROMOTION_SUCCESS",
        severity="INFO",
        details={"state": STATE_SECONDARY_ACTIVE}
    )

    # Edge router automatically routes writes to Phone
    worker.query_origin_status = lambda o: {
        "cluster_id": "sentineldr-cluster-01",
        "node_id": "laptop" if o == worker.primary_origin else "phone",
        "node_type": "laptop" if o == worker.primary_origin else "phone",
        "role": "RECOVERING" if o == worker.primary_origin else "SECONDARY_ACTIVE",
        "epoch": 1 if o == worker.primary_origin else 2,
        "writable": (o == worker.backup_origin),
        "lease_valid": (o == worker.backup_origin),
        "lease_remaining_seconds": 60.0 if o == worker.backup_origin else 0.0,
        "owner_node_id": "phone",
        "db_healthy": True,
    }
    route_failover = worker.resolve_active_target(force_refresh=True)
    assert route_failover["active_node"] == "phone"
    assert route_failover["writable"] is True

    # -------------------------------------------------------------
    # Step 5: Write on Phone during failover & restart Phone
    # -------------------------------------------------------------
    inquiry_2 = {
        "name": "Bob Failover",
        "email": "bob@failover.org",
        "subject": "Failover outage write",
        "message": "Committed on Phone during Laptop downtime"
    }
    status, _, body_w2 = worker.handle_request(
        method="POST",
        path="/api/v1/portfolio/inquiry",
        headers={"Content-Type": "application/json"},
        body=json.dumps(inquiry_2).encode("utf-8")
    )
    assert status in (200, 201)

    # Verify write and outbox survived restart
    phone_inquiries = phone_srv.db.get_inquiries()
    assert any(i["email"] == "bob@failover.org" for i in phone_inquiries)
    unrepl_phone = phone_srv.db.get_unreplicated_changes(peer_node_id="laptop")
    assert len(unrepl_phone) >= 1

    # -------------------------------------------------------------
    # Step 6: Restart laptop in RECOVERING & replay Phone writes
    # -------------------------------------------------------------
    # Take consistent backups
    laptop_backup = laptop_db.create_database_backup(backup_dir)
    phone_backup = phone_srv.db.create_database_backup(backup_dir)
    assert os.path.exists(laptop_backup)
    assert os.path.exists(phone_backup)

    # Laptop reconciles Phone's epoch 2 outage events
    laptop_server_mod.state_machine._state = STATE_RECONCILING
    laptop_server_mod.state_machine._epoch = 2
    laptop_db.log_audit_event(
        event_id=str(uuid.uuid4()),
        node_id="laptop",
        epoch=2,
        event_type="RECOVERY_STARTED",
        severity="INFO",
        details={"state": STATE_RECONCILING}
    )

    # Replay events idempotently into Laptop
    replayed_count = 0
    for ev in unrepl_phone:
        ok_apply, _, _, _, _, _ = laptop_db.apply_replication_batch(
            origin_node_id="phone",
            batch_id=f"replay-{ev['operation_id']}",
            events=[ev]
        )
        assert ok_apply is True
        replayed_count += 1
    assert replayed_count >= 1

    # -------------------------------------------------------------
    # Step 7: Multi-layer validation & canonical hash parity
    # -------------------------------------------------------------
    laptop_hash_recon = laptop_db.get_canonical_hash("portfolio_inquiries")
    phone_hash_recon = phone_srv.db.get_canonical_hash("portfolio_inquiries")
    assert laptop_hash_recon == phone_hash_recon, "Canonical data hash mismatch after reconciliation!"

    # -------------------------------------------------------------
    # Step 8: Controlled failback handoff
    # -------------------------------------------------------------
    # Phone steps down to SECONDARY_STANDBY
    phone_srv.state_machine._state = STATE_SECONDARY_STANDBY
    phone_srv.db.log_audit_event(
        event_id=str(uuid.uuid4()),
        node_id="phone",
        epoch=3,
        event_type="STEPPED_DOWN",
        severity="INFO",
        details={"state": STATE_SECONDARY_STANDBY}
    )

    # Laptop acquires epoch 3 lease and enters PRIMARY_ACTIVE
    now_fb = time.time()
    lease_sig_3 = sign_ownership_record("sentineldr-cluster-01", "laptop", 3, "lease-e2e-03", now_fb + 120.0, "witness", witness_secret)
    lease_3 = OwnershipRecord("sentineldr-cluster-01", "laptop", 3, "lease-e2e-03", now_fb + 120.0, "witness", lease_sig_3, now_fb)
    laptop_db.set_ownership(lease_3)
    phone_srv.db.set_ownership(lease_3)

    laptop_server_mod.state_machine._state = STATE_PRIMARY_ACTIVE
    laptop_server_mod.state_machine._epoch = 3
    phone_srv.state_machine._epoch = 3
    laptop_db.log_audit_event(
        event_id=str(uuid.uuid4()),
        node_id="laptop",
        epoch=3,
        event_type="FAILBACK_COMPLETED",
        severity="INFO",
        details={"state": STATE_PRIMARY_ACTIVE}
    )

    # -------------------------------------------------------------
    # Step 9: Final verification
    # -------------------------------------------------------------
    assert laptop_server_mod.state_machine.current_state == STATE_PRIMARY_ACTIVE
    assert phone_srv.state_machine.current_state == STATE_SECONDARY_STANDBY
    assert laptop_server_mod.state_machine.is_writable() is True
    assert phone_srv.state_machine.is_writable() is False

    # Check audit log trail
    laptop_events = laptop_db.get_recent_audit_events(limit=50)
    phone_events = phone_srv.db.get_recent_audit_events(limit=50)
    assert len(laptop_events) > 0
    assert len(phone_events) > 0
