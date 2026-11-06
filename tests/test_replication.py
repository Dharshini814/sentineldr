"""
SentinelDR Replication Engine Tests
Verifies durable, ordered, idempotent, bidirectional replication,
gap and out-of-order detection, transaction atomicity on crash mid-apply,
conflict preservation, outage write persistence across restarts, and heartbeat tracking.
"""

import json
import os
import sqlite3
import sys
import threading
import time
import uuid
import pytest
from starlette.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import laptop.server as laptop_server_mod
from laptop.db import LaptopDatabase
from phone.db import PhoneDatabase
from phone.server import PhoneServer
from shared.config import NodeConfig
from shared.ownership import OwnershipRecord, sign_ownership_record
from shared.replication_worker import ReplicationClient
from shared.security import build_peer_headers


@pytest.fixture(scope="module")
def test_cluster(tmp_path_factory):
    """Sets up an isolated laptop and phone environment with fresh test databases."""
    tmp_dir = tmp_path_factory.mktemp("isolated_repl_cluster")
    phone_db_path = str(tmp_dir / "phone_repl.db")
    phone_nonce_path = str(tmp_dir / "phone_nonce.db")
    laptop_db_path = str(tmp_dir / "laptop_repl.db")
    laptop_nonce_path = str(tmp_dir / "laptop_nonce.db")

    # 1. Isolated Phone Server
    phone_cfg = NodeConfig("phone")
    phone_cfg.port = 0  # Dynamic ephemeral port to avoid collisions
    phone_cfg.database_path = phone_db_path
    phone_cfg.nonce_cache_db = phone_nonce_path

    phone_server = PhoneServer(phone_cfg)
    t = threading.Thread(target=lambda: phone_server.serve_forever(poll_interval=0.1), daemon=True)
    t.start()
    time.sleep(0.15)

    # 2. Isolated Laptop Database & Client
    laptop_db_inst = LaptopDatabase(f"sqlite:///{laptop_db_path}")
    laptop_db_inst._sqlite_path = laptop_db_path
    laptop_db_inst.using_sqlite_fallback = True
    laptop_db_inst.init_db()
    laptop_db_inst.seed_portfolio_data()

    orig_laptop_db = laptop_server_mod.db
    laptop_server_mod.db = laptop_db_inst
    laptop_c = TestClient(laptop_server_mod.app)

    yield {
        "phone_server": phone_server,
        "phone_url": f"http://127.0.0.1:{phone_server.config.port}",
        "phone_db": phone_server.db,
        "phone_cfg": phone_cfg,
        "laptop_client": laptop_c,
        "laptop_db": laptop_db_inst,
    }

    # Teardown
    laptop_server_mod.db = orig_laptop_db
    phone_server.stop()


# 1. Normal Sync (Laptop to Phone)
def test_normal_replication_laptop_to_phone(test_cluster):
    c = test_cluster
    # Laptop creates inquiry
    ok, _, _, op_id = c["laptop_db"].submit_inquiry(
        origin_node_id="laptop",
        origin_epoch=1,
        name="Carol Sync",
        email="carol@sync.org",
        subject="Replication Test",
        message="Message from laptop to phone.",
        is_primary=True
    )
    assert ok is True
    assert op_id is not None

    unreplicated = c["laptop_db"].get_unreplicated_changes(peer_node_id="phone")
    assert len(unreplicated) >= 1

    # Replicate all unreplicated events to Phone
    client = ReplicationClient(secret=c["phone_cfg"].hmac_secret)
    accepted, resp_data, err = client.replicate_batch(
        peer_url=c["phone_url"],
        sender_node_id="laptop",
        epoch=1,
        batch_id=uuid.uuid4().hex,
        from_sequence=unreplicated[0]["sequence_number"],
        events=unreplicated
    )

    assert accepted is True, f"Replication failed: {err}"
    assert resp_data["accepted"] is True
    assert resp_data["last_applied_sequence"] == unreplicated[-1]["sequence_number"]

    # Verify phone database has the replicated inquiry
    phone_conn = c["phone_db"].get_connection()
    cur = phone_conn.cursor()
    cur.execute("SELECT name, email, message FROM portfolio_inquiries WHERE id = ?", (op_id,))
    row = cur.fetchone()
    assert row is not None
    assert row["name"] == "Carol Sync"
    assert row["email"] == "carol@sync.org"

    # Verify phone checkpoint matches
    checkpoint = c["phone_db"].get_replication_checkpoint("laptop")
    assert checkpoint["last_applied_sequence"] == unreplicated[-1]["sequence_number"]
    assert checkpoint["last_applied_operation_id"] == op_id
    phone_conn.close()


# 2. Reverse Sync (Phone to Laptop)
def test_reverse_replication_phone_to_laptop(test_cluster):
    c = test_cluster
    # Phone generates an outage write (simulating promoted secondary active with valid lease)
    now = time.time()
    sig = sign_ownership_record("sentineldr-cluster-01", "phone", 2, "lease-ph-promoted", now + 60.0, "witness", c["phone_cfg"].hmac_secret)
    c["phone_db"].set_ownership(OwnershipRecord("sentineldr-cluster-01", "phone", 2, "lease-ph-promoted", now + 60.0, "witness", sig, now))

    ok, _, _, op_id = c["phone_db"].submit_inquiry(
        origin_node_id="phone",
        origin_epoch=2,
        name="Dave Reverse",
        email="dave@reverse.org",
        subject="Phone Failover Write",
        message="Created on phone during outage.",
        is_primary=True,  # Simulated promoted phone
        cluster_id="sentineldr-cluster-01",
        secret=c["phone_cfg"].hmac_secret
    )
    assert ok is True

    unreplicated = c["phone_db"].get_unreplicated_changes(peer_node_id="laptop")
    assert len(unreplicated) >= 1
    event = [e for e in unreplicated if e["operation_id"] == op_id][0]

    # Send batch from phone to laptop endpoint
    batch = {
        "batch_id": uuid.uuid4().hex,
        "from_sequence": event["sequence_number"],
        "events": [event]
    }
    body_bytes = json.dumps(batch).encode("utf-8")
    headers = build_peer_headers(
        node_id="phone",
        epoch=2,
        secret=c["phone_cfg"].hmac_secret,
        method="POST",
        path="/api/v1/peer/replicate",
        body=body_bytes
    )

    resp = c["laptop_client"].post("/api/v1/peer/replicate", content=body_bytes, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["accepted"] is True
    assert body["data"]["last_applied_sequence"] == event["sequence_number"]

    # Verify laptop checkpoint updated for peer "phone"
    lp_checkpoint = c["laptop_db"].get_replication_checkpoint("phone")
    assert lp_checkpoint["last_applied_sequence"] == event["sequence_number"]


# 3. Deduplication (Idempotence)
def test_duplicate_operation_id_deduplicated(test_cluster):
    c = test_cluster
    # Create change on laptop
    ok, _, _, op_id = c["laptop_db"].submit_inquiry(
        origin_node_id="laptop",
        origin_epoch=1,
        name="Eve Dedupe",
        email="eve@dedupe.org",
        subject="Dedupe Test",
        message="Testing idempotent delivery.",
        is_primary=True
    )
    assert ok is True

    unreplicated = c["laptop_db"].get_unreplicated_changes("phone")
    assert len(unreplicated) >= 1
    client = ReplicationClient(secret=c["phone_cfg"].hmac_secret)

    # First delivery: Accepted
    ok1, data1, err1 = client.replicate_batch(
        peer_url=c["phone_url"],
        sender_node_id="laptop",
        epoch=1,
        batch_id=uuid.uuid4().hex,
        from_sequence=unreplicated[0]["sequence_number"],
        events=unreplicated
    )
    assert ok1 is True, f"First delivery failed: {err1}"

    # Second delivery (Exact same batch re-sent): Must be deduplicated!
    ok2, data2, err2 = client.replicate_batch(
        peer_url=c["phone_url"],
        sender_node_id="laptop",
        epoch=1,
        batch_id=uuid.uuid4().hex,
        from_sequence=unreplicated[0]["sequence_number"],
        events=unreplicated
    )
    assert ok2 is True, f"Second delivery failed: {err2}"
    assert data2["duplicate_count"] >= 1


# 4. Sequence Gap Detection
def test_sequence_gap_rejected_and_rolls_back(test_cluster):
    c = test_cluster
    current_checkpoint = c["phone_db"].get_replication_checkpoint("laptop")["last_applied_sequence"]

    # Construct gap event: skip by +5
    gap_seq = current_checkpoint + 5
    gap_op_id = uuid.uuid4().hex
    gap_event = {
        "operation_id": gap_op_id,
        "sequence_number": gap_seq,
        "origin_node_id": "laptop",
        "origin_epoch": 1,
        "schema_version": 1,
        "entity_type": "inquiry",
        "entity_id": gap_op_id,
        "operation": "upsert",
        "payload": {
            "id": gap_op_id,
            "name": "Gap Subject",
            "email": "gap@test.org",
            "subject": "Gap",
            "message": "This should not be applied"
        },
        "created_at": time.time()
    }

    client = ReplicationClient(secret=c["phone_cfg"].hmac_secret)
    ok, data, err = client.replicate_batch(
        peer_url=c["phone_url"],
        sender_node_id="laptop",
        epoch=1,
        batch_id=uuid.uuid4().hex,
        from_sequence=gap_seq,
        events=[gap_event]
    )

    # Must be rejected due to sequence gap
    assert ok is False
    assert "CONFLICT" in str(err) or "gap" in str(err).lower()

    # Verify phone checkpoint was NOT advanced
    after_checkpoint = c["phone_db"].get_replication_checkpoint("laptop")["last_applied_sequence"]
    assert after_checkpoint == current_checkpoint

    # Verify entity was NOT committed
    conn = c["phone_db"].get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM portfolio_inquiries WHERE id = ?", (gap_op_id,))
    assert cur.fetchone() is None
    conn.close()


# 5. Out-of-Order Delivery Rejection
def test_out_of_order_batch_rejected(test_cluster):
    c = test_cluster
    current_seq = c["phone_db"].get_replication_checkpoint("laptop")["last_applied_sequence"]

    # Events in reverse order within same batch: seq+2 before seq+1
    ev_next = {
        "operation_id": uuid.uuid4().hex,
        "sequence_number": current_seq + 1,
        "origin_node_id": "laptop",
        "origin_epoch": 1,
        "schema_version": 1,
        "entity_type": "inquiry",
        "entity_id": "test_next",
        "operation": "upsert",
        "payload": {"id": "test_next", "name": "Next", "email": "n@t.org", "message": "msg"},
        "created_at": time.time()
    }
    ev_out_of_order = {
        "operation_id": uuid.uuid4().hex,
        "sequence_number": current_seq + 2,
        "origin_node_id": "laptop",
        "origin_epoch": 1,
        "schema_version": 1,
        "entity_type": "inquiry",
        "entity_id": "test_ooo",
        "operation": "upsert",
        "payload": {"id": "test_ooo", "name": "OOO", "email": "o@t.org", "message": "msg"},
        "created_at": time.time()
    }

    # Put out-of-order first
    batch_events = [ev_out_of_order, ev_next]

    client = ReplicationClient(secret=c["phone_cfg"].hmac_secret)
    ok, data, err = client.replicate_batch(
        peer_url=c["phone_url"],
        sender_node_id="laptop",
        epoch=1,
        batch_id=uuid.uuid4().hex,
        from_sequence=current_seq + 2,
        events=batch_events
    )

    assert ok is False, "Out of order batch must be rejected"


# 6. Crash Mid-Apply Atomicity (Single Transaction Rollback)
def test_crash_mid_apply_rolls_back_entire_batch(test_cluster):
    c = test_cluster
    current_seq = c["phone_db"].get_replication_checkpoint("laptop")["last_applied_sequence"]

    valid_ev = {
        "operation_id": uuid.uuid4().hex,
        "sequence_number": current_seq + 1,
        "origin_node_id": "laptop",
        "origin_epoch": 1,
        "schema_version": 1,
        "entity_type": "inquiry",
        "entity_id": "valid_entity_1",
        "operation": "upsert",
        "payload": {"id": "valid_entity_1", "name": "Valid", "email": "v@t.org", "message": "valid message"},
        "created_at": time.time()
    }

    # Second event causes error via unsupported entity type
    broken_ev = {
        "operation_id": uuid.uuid4().hex,
        "sequence_number": current_seq + 2,
        "origin_node_id": "laptop",
        "origin_epoch": 1,
        "schema_version": 1,
        "entity_type": "unsupported_type_that_triggers_rollback",
        "entity_id": "broken_1",
        "operation": "upsert",
        "payload": "invalid-payload",
        "created_at": time.time()
    }

    ok, last_seq, dups, missing, resync, err = c["phone_db"].apply_replication_batch(
        origin_node_id="laptop",
        batch_id=uuid.uuid4().hex,
        events=[valid_ev, broken_ev]
    )

    # Entire batch must fail
    assert ok is False

    # Checkpoint must NOT advance to current_seq + 1
    chk = c["phone_db"].get_replication_checkpoint("laptop")["last_applied_sequence"]
    assert chk == current_seq

    # First event must be rolled back completely
    conn = c["phone_db"].get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM portfolio_inquiries WHERE id = 'valid_entity_1'")
    assert cur.fetchone() is None
    conn.close()


# 7. Phone Outage Writes Survive Phone Restart
def test_phone_writes_survive_restart(tmp_path):
    phone_db_file = str(tmp_path / "phone_restart_test.db")

    # Phone DB instance 1 writes outage data with promoted lease
    db1 = PhoneDatabase(phone_db_file)
    now = time.time()
    sig = sign_ownership_record("sentineldr-cluster-01", "phone", 2, "lease-ph-survivor", now + 60.0, "witness", db1.secret)
    db1.set_ownership(OwnershipRecord("sentineldr-cluster-01", "phone", 2, "lease-ph-survivor", now + 60.0, "witness", sig, now))

    ok, _, _, op_id = db1.submit_inquiry(
        origin_node_id="phone",
        origin_epoch=2,
        name="Survivor User",
        email="survivor@mobile.org",
        subject="Outage Survival",
        message="Written on phone before simulated crash/restart.",
        is_primary=True,
        cluster_id="sentineldr-cluster-01",
        secret=db1.secret
    )
    assert ok is True

    # Simulate crash/restart by deleting db1 instance and recreating db2 on same file
    del db1
    time.sleep(0.05)

    db2 = PhoneDatabase(phone_db_file)

    # Verify write exists in restarted database
    conn = db2.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, email, message FROM portfolio_inquiries WHERE id = ?", (op_id,))
    row = cur.fetchone()
    assert row is not None
    assert row["name"] == "Survivor User"

    # Verify change_log outbox row is intact and ready for replication
    cur.execute("SELECT sequence_number, origin_node_id FROM change_log WHERE operation_id = ?", (op_id,))
    cl_row = cur.fetchone()
    assert cl_row is not None
    assert cl_row["sequence_number"] >= 1
    assert cl_row["origin_node_id"] == "phone"

    conn.close()


# 8. Conflict Preservation (No Wall-Clock LWW)
def test_conflict_preservation(test_cluster):
    c = test_cluster
    entity_id = "conflict_inquiry_01"

    # Create local inquiry on phone
    conn = c["phone_db"].get_connection()
    conn.execute(
        """
        INSERT INTO portfolio_inquiries (id, name, email, subject, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (entity_id, "Local Author", "local@test.org", "Subject A", "Original local text", time.time())
    )
    conn.commit()
    conn.close()

    current_seq = c["phone_db"].get_replication_checkpoint("laptop")["last_applied_sequence"]

    # Incoming conflicting update from laptop with different text
    conflicting_event = {
        "operation_id": uuid.uuid4().hex,
        "sequence_number": current_seq + 1,
        "origin_node_id": "laptop",
        "origin_epoch": 1,
        "schema_version": 1,
        "entity_type": "inquiry",
        "entity_id": entity_id,
        "operation": "upsert",
        "payload": {
            "id": entity_id,
            "name": "Remote Author",
            "email": "remote@test.org",
            "subject": "Subject B",
            "message": "Divergent remote text from laptop"
        },
        "created_at": time.time()
    }

    client = ReplicationClient(secret=c["phone_cfg"].hmac_secret)
    ok, data, err = client.replicate_batch(
        peer_url=c["phone_url"],
        sender_node_id="laptop",
        epoch=1,
        batch_id=uuid.uuid4().hex,
        from_sequence=current_seq + 1,
        events=[conflicting_event]
    )
    assert ok is True

    # Verify conflict record was preserved in conflict_records table
    conn = c["phone_db"].get_connection()
    cur = conn.cursor()
    cur.execute("SELECT entity_id, origin_node_id, local_data, remote_data FROM conflict_records WHERE entity_id = ?", (entity_id,))
    conflict_row = cur.fetchone()
    assert conflict_row is not None
    assert conflict_row["entity_id"] == entity_id
    assert conflict_row["origin_node_id"] == "laptop"
    assert "Original local text" in conflict_row["local_data"]
    assert "Divergent remote text from laptop" in conflict_row["remote_data"]
    conn.close()


# 9. Heartbeat Cadence & Tracking
def test_heartbeat_cadence_and_sequence_ack(test_cluster):
    c = test_cluster
    client = ReplicationClient(secret=c["phone_cfg"].hmac_secret)

    ok, ack_data, err = client.send_heartbeat(
        peer_url=c["phone_url"],
        sender_node_id="laptop",
        sender_state="PRIMARY_ACTIVE",
        epoch=1,
        lease_id="lease-001",
        last_committed_sequence=10,
        database_health="HEALTHY"
    )

    assert ok is True, f"Heartbeat failed: {err}"
    assert ack_data["status"] == "ACK"
    assert ack_data["receiver_node_id"] == "phone"
    assert "received_at" in ack_data
    assert isinstance(ack_data["highest_applied_sequence"], int)

    # Verify receiver tracker recorded heartbeat with its own clock
    hb_status = c["phone_server"].heartbeat_tracker.get_status()
    assert hb_status["consecutive_misses"] == 0
    assert hb_status["suspected_offline"] is False
    assert hb_status["last_sender_state"] == "PRIMARY_ACTIVE"
    assert hb_status["last_sender_seq"] == 10


# 10. Replication Retry with Exponential Backoff and Jitter
def test_replication_retry_with_exponential_backoff_and_jitter():
    import io
    from unittest.mock import MagicMock, patch
    import urllib.error

    client = ReplicationClient(secret="test-retry-secret")

    events = [{
        "operation_id": "op-retry-1",
        "origin_sequence": 1,
        "origin_node_id": "laptop",
        "origin_epoch": 1,
        "schema_version": 1,
        "entity_type": "inquiry",
        "entity_id": "ent-retry-1",
        "operation": "upsert",
        "payload": {"test": "val"},
        "created_at": time.time()
    }]

    # Case 1: Transient 503 HTTP errors on attempts 0 and 1, success on attempt 2
    sleep_calls = []
    def fake_sleep(duration):
        sleep_calls.append(duration)

    success_resp = MagicMock()
    success_resp.read.return_value = json.dumps({"ok": True, "data": {"accepted": True}}).encode("utf-8")
    success_resp.__enter__.return_value = success_resp

    http_err_503 = urllib.error.HTTPError(
        url="http://127.0.0.1:8001/api/v1/peer/replicate",
        code=503,
        msg="Service Unavailable",
        hdrs={},
        fp=None
    )

    with patch("urllib.request.urlopen", side_effect=[http_err_503, http_err_503, success_resp]), \
         patch("time.sleep", side_effect=fake_sleep):
        ok, data, err = client.send_batch_with_retry(
            peer_url="http://127.0.0.1:8001",
            sender_node_id="laptop",
            epoch=1,
            batch_id="batch-retry-01",
            from_sequence=1,
            events=events,
            max_retries=3
        )
        assert ok is True
        assert data == {"accepted": True}
        assert err is None
        # Verify 2 sleep intervals occurred before success on 3rd attempt
        assert len(sleep_calls) == 2

        # Verify exponential backoff: base = 0.1 * 2^attempt, jitter between 0.01 and 0.05
        # attempt 0: base 0.1s + jitter [0.01, 0.05] => [0.11, 0.15]s
        assert 0.109 <= sleep_calls[0] <= 0.155, f"Sleep 0 was {sleep_calls[0]}"
        # attempt 1: base 0.2s + jitter [0.01, 0.05] => [0.21, 0.25]s
        assert 0.209 <= sleep_calls[1] <= 0.255, f"Sleep 1 was {sleep_calls[1]}"
        # Strictly increasing backoff
        assert sleep_calls[1] > sleep_calls[0]

    # Case 2: Permanent failure exhausts max_retries
    sleep_calls.clear()
    with patch("urllib.request.urlopen", side_effect=[http_err_503, http_err_503, http_err_503]), \
         patch("time.sleep", side_effect=fake_sleep):
        ok, data, err = client.send_batch_with_retry(
            peer_url="http://127.0.0.1:8001",
            sender_node_id="laptop",
            epoch=1,
            batch_id="batch-retry-02",
            from_sequence=1,
            events=events,
            max_retries=3
        )
        assert ok is False
        assert len(sleep_calls) == 2
        assert "503" in str(err)

    # Case 3: 4xx Client error (e.g. 401 Unauthorized) fails fast WITHOUT retrying
    sleep_calls.clear()
    err_body_401 = json.dumps({"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Bad HMAC"}}).encode("utf-8")
    http_err_401 = urllib.error.HTTPError(
        url="http://127.0.0.1:8001/api/v1/peer/replicate",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=io.BytesIO(err_body_401)
    )
    with patch("urllib.request.urlopen", side_effect=http_err_401), \
         patch("time.sleep", side_effect=fake_sleep):
        ok, data, err = client.send_batch_with_retry(
            peer_url="http://127.0.0.1:8001",
            sender_node_id="laptop",
            epoch=1,
            batch_id="batch-retry-03",
            from_sequence=1,
            events=events,
            max_retries=3
        )
        assert ok is False
        assert "UNAUTHORIZED" in str(err)
        assert len(sleep_calls) == 0, "4xx client error must not trigger retry or sleep"
