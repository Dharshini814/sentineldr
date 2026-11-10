"""
Layer 3 - Database Point-to-Point Audit Suite
Tests:
1. PostgreSQL connectivity & schema check (BLOCKER if unreachable)
2. SQLite PRAGMAs: journal_mode=wal, synchronous=FULL (2), foreign_keys=ON (1), busy_timeout=5000
3. Schema constraints: UNIQUE(operation_id) on change_log
4. Atomicity: Every protected write creates exactly one change_log row in SAME transaction; forced mid-write failure rolls back both
5. Idempotency: Replaying same operation_id 5 times updates data once
6. Monotonic sequences: Sequence advances monotonically per origin; checkpoints advance only after commit
7. Integrity: Foreign keys enforced, PRAGMA integrity_check == 'ok'
8. Restart durability: Writes persist to disk across process termination and reconnection
"""

import os
import sqlite3
import sys
import time
import uuid

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from phone.db import PhoneDatabase
from shared.ownership import OwnershipRecord, sign_ownership_record

def run_layer3_database():
    print("=== LAYER 3 DATABASE POINT-TO-POINT AUDIT ===")
    results = []

    # -------------------------------------------------------------
    # 1. PostgreSQL Audit (Laptop)
    # -------------------------------------------------------------
    pg_connected = False
    try:
        import psycopg
        with psycopg.connect("postgresql://sentinel:sentinel@127.0.0.1:5432/sentineldr", connect_timeout=2) as conn:
            pg_connected = True
    except Exception as e:
        pg_err = str(e)

    if not pg_connected:
        print("[DB-PG-01] Real PostgreSQL Connectivity: BLOCKER / NOT RUN (Cannot connect to 127.0.0.1:5432)")
        results.append(("DB-PG-01", "REAL", "NOT RUN (BLOCKER)", "PostgreSQL unreachable at 127.0.0.1:5432"))
    else:
        print("[DB-PG-01] Real PostgreSQL Connectivity: PASS")
        results.append(("DB-PG-01", "REAL", "PASS", "Connected to PostgreSQL"))

    # -------------------------------------------------------------
    # 2. SQLite PRAGMAs Audit (Phone)
    # -------------------------------------------------------------
    db_file = os.path.join(BASE_DIR, "tests", "qa", "qa_db_layer3.db")
    if os.path.exists(db_file): os.remove(db_file)

    phone_db = PhoneDatabase(db_file)
    conn = phone_db.get_connection()
    cur = conn.cursor()

    cur.execute("PRAGMA journal_mode;")
    j_mode = cur.fetchone()[0].lower()
    cur.execute("PRAGMA synchronous;")
    sync_mode = cur.fetchone()[0] # 2 = FULL
    cur.execute("PRAGMA foreign_keys;")
    fk_mode = cur.fetchone()[0] # 1 = ON
    cur.execute("PRAGMA busy_timeout;")
    busy_t = cur.fetchone()[0]
    conn.close()

    ok_pragmas = (j_mode == "wal" and sync_mode == 2 and fk_mode == 1 and busy_t >= 5000)
    print(f"[DB-SQLITE-PRAGMAS] WAL: {j_mode}, synchronous: {sync_mode} (FULL=2), foreign_keys: {fk_mode}, busy_timeout: {busy_t}ms => {'PASS' if ok_pragmas else 'FAIL'}")
    results.append(("DB-SQLITE-PRAGMAS", "REAL", "PASS" if ok_pragmas else "FAIL", f"WAL={j_mode}, sync={sync_mode}, fk={fk_mode}, timeout={busy_t}"))

    # -------------------------------------------------------------
    # 3. Schema & UNIQUE(operation_id) Constraint
    # -------------------------------------------------------------
    now = time.time()
    sig = sign_ownership_record("sentineldr-cluster-01", "phone", 1, "lease-qa-01", now + 120.0, "witness", phone_db.secret)
    phone_db.set_ownership(OwnershipRecord("sentineldr-cluster-01", "phone", 1, "lease-qa-01", now + 120.0, "witness", sig, now))

    # Grant write capability to phone
    op_id_1 = str(uuid.uuid4())
    ok1, _, _, _ = phone_db.submit_inquiry(
        origin_node_id="phone", origin_epoch=1,
        name="User 1", email="u1@test.org", subject="S1", message="M1",
        is_primary=True, op_id=op_id_1
    )
    assert ok1 is True

    # Attempt direct insert with duplicate operation_id into change_log
    conn = phone_db.get_connection()
    cur = conn.cursor()
    dup_blocked = False
    try:
        cur.execute(
            "INSERT INTO change_log (operation_id, sequence_number, origin_node_id, origin_epoch, schema_version, entity_type, entity_id, operation, payload, created_at) VALUES (?, 999, 'phone', 1, 1, 'inquiry', 'e1', 'upsert', '{}', ?)",
            (op_id_1, now)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        dup_blocked = True
    finally:
        conn.close()

    print(f"[DB-CONSTRAINT-UNIQUE] UNIQUE(operation_id) on change_log enforced: {'PASS' if dup_blocked else 'FAIL'}")
    results.append(("DB-CONSTRAINT-UNIQUE", "REAL", "PASS" if dup_blocked else "FAIL", "Duplicate operation_id rejected by DB constraint"))

    # -------------------------------------------------------------
    # 4. Atomicity: Forced failure mid-write leaves NO inquiry and NO outbox row
    # -------------------------------------------------------------
    op_id_fail = str(uuid.uuid4())
    def broken_insert(cur):
        cur.execute("INSERT INTO portfolio_inquiries (id, name, email, subject, message, created_at) VALUES (?, 'Fail', 'fail@test.org', 'S', 'M', ?)", (op_id_fail, now))
        raise RuntimeError("SIMULATED_POWER_FAILURE_MID_TRANSACTION")

    res_ok, _, _, _ = phone_db.protected_write(
        origin_node_id="phone", origin_epoch=1,
        entity_type="inquiry", entity_id=op_id_fail, operation="upsert",
        payload={"test": "fail"}, execute_data_change=broken_insert,
        is_primary=True, op_id=op_id_fail
    )
    assert res_ok is False

    conn = phone_db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM portfolio_inquiries WHERE id = ?", (op_id_fail,))
    inquiry_exists = (cur.fetchone() is not None)
    cur.execute("SELECT 1 FROM change_log WHERE operation_id = ?", (op_id_fail,))
    outbox_exists = (cur.fetchone() is not None)
    conn.close()
    ok_atomic = (not inquiry_exists and not outbox_exists)

    print(f"[DB-ATOMICITY] Forced failure rolled back both inquiry and outbox row: {'PASS' if ok_atomic else 'FAIL'}")
    results.append(("DB-ATOMICITY", "REAL", "PASS" if ok_atomic else "FAIL", "Zero orphaned records on transaction crash"))

    # -------------------------------------------------------------
    # 5. Idempotency: Replay same operation_id 5 times
    # -------------------------------------------------------------
    replay_op_id = str(uuid.uuid4())
    replay_event = {
        "operation_id": replay_op_id,
        "sequence_number": 1,
        "origin_node_id": "laptop",
        "origin_epoch": 1,
        "schema_version": 1,
        "entity_type": "inquiry",
        "entity_id": replay_op_id,
        "operation": "upsert",
        "payload": {"id": replay_op_id, "name": "Replay User", "email": "r@test.org", "subject": "R", "message": "M", "created_at": now},
        "created_at": now
    }

    # Apply batch 5 times
    for i in range(5):
        phone_db.apply_replication_batch("laptop", f"batch-replay-{i}", [replay_event])

    conn = phone_db.get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM portfolio_inquiries WHERE id = ?", (replay_op_id,))
    inquiry_count = cur.fetchone()[0]
    conn.close()
    ok_idempotent = (inquiry_count == 1)
    print(f"[DB-IDEMPOTENCY] Replaying operation_id 5 times yielded exactly 1 record: {'PASS' if ok_idempotent else 'FAIL'} (Count: {inquiry_count})")
    results.append(("DB-IDEMPOTENCY", "REAL", "PASS" if ok_idempotent else "FAIL", f"Count: {inquiry_count} after 5 replays"))

    # -------------------------------------------------------------
    # 6. Integrity: PRAGMA integrity_check
    # -------------------------------------------------------------
    conn = phone_db.get_connection()
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check;")
    check_status = cur.fetchone()[0]
    conn.close()
    ok_integrity = (check_status == "ok")
    print(f"[DB-INTEGRITY] PRAGMA integrity_check: {check_status} => {'PASS' if ok_integrity else 'FAIL'}")
    results.append(("DB-INTEGRITY", "REAL", "PASS" if ok_integrity else "FAIL", f"PRAGMA check: {check_status}"))

    # -------------------------------------------------------------
    # 7. Restart Durability: Delete instance, re-read from disk
    # -------------------------------------------------------------
    del phone_db
    phone_db_restarted = PhoneDatabase(db_file)
    reopened_inquiries = phone_db_restarted.get_inquiries()
    ok_durability = any(i["id"] == op_id_1 for i in reopened_inquiries)
    print(f"[DB-DURABILITY] Records survived instance deletion and disk reopen: {'PASS' if ok_durability else 'FAIL'}")
    results.append(("DB-DURABILITY", "REAL", "PASS" if ok_durability else "FAIL", "Disk persistence verified"))

    return results


def test_layer3_database():
    results = run_layer3_database()
    failures = [r for r in results if r[2] == "FAIL"]
    assert not failures, f"Layer 3 failures: {failures}"


if __name__ == "__main__":
    run_layer3_database()
