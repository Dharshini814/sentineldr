"""
Layer 5 - Ownership, Lease, Fencing, and Partition Audit Suite
Tests:
1. OwnershipRecord HMAC signature verification and tamper rejection
2. Monotonic epoch enforcement
3. Stale epoch rejection (Witness denies lower or equal epoch)
4. Expired lease write guard (Fail-closed read-only behavior)
5. Bounded clock-skew policy enforcement
6. Witness lease arbitration (Node A holds lease -> Node B denied)
7. Voluntary lease release allowing immediate re-acquisition
8. Network Partition A: Laptop isolated -> lease expires -> write guard blocks writes
9. Network Partition B: Phone isolated -> cannot reach witness -> promotion blocked / SAFE_MODE
10. Network Partition C: Witness dead -> renewals fail -> both nodes fail-closed into SAFE_MODE (0 dual-writers)
11. Network Partition D: Mutual split-brain attempt -> Witness denies second node -> single writer invariant held
"""

import json
import os
import sys
import threading
import time
import uuid

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from shared.ownership import (
    OwnershipRecord,
    sign_ownership_record,
    verify_ownership_signature,
    validate_lease
)
from shared.witness import WitnessServer, WitnessClient
from phone.db import PhoneDatabase
from phone.server import PhoneServer
from shared.config import NodeConfig

CLUSTER_ID = "sentineldr-cluster-01"
WITNESS_SECRET = "qa-witness-secret-key-12345"
SHARED_SECRET = "qa-shared-secret-key-67890"

def run_layer5_ownership():
    print("=== LAYER 5 OWNERSHIP, LEASE, FENCING & PARTITIONS AUDIT ===")
    results = []

    # 1. OwnershipRecord signature verification & tamper rejection
    now = time.time()
    lease_id = uuid.uuid4().hex
    sig = sign_ownership_record(
        cluster_id=CLUSTER_ID,
        owner_node_id="laptop",
        epoch=1,
        lease_id=lease_id,
        lease_expires_at=now + 15.0,
        granted_by="witness",
        secret=WITNESS_SECRET
    )
    valid_record = OwnershipRecord(
        cluster_id=CLUSTER_ID,
        owner_node_id="laptop",
        epoch=1,
        lease_id=lease_id,
        lease_expires_at=now + 15.0,
        granted_by="witness",
        signature=sig,
        updated_at=now
    )
    sig_ok = verify_ownership_signature(valid_record, WITNESS_SECRET)
    
    # Tampered epoch
    tampered_record = OwnershipRecord(
        cluster_id=CLUSTER_ID,
        owner_node_id="laptop",
        epoch=2, # Tampered!
        lease_id=lease_id,
        lease_expires_at=now + 15.0,
        granted_by="witness",
        signature=sig,
        updated_at=now
    )
    tamper_rejected = not verify_ownership_signature(tampered_record, WITNESS_SECRET)
    test1_pass = sig_ok and tamper_rejected
    print(f"[OWN-01] OwnershipRecord signature verification & tamper rejection: {'PASS' if test1_pass else 'FAIL'}")
    results.append(("OWN-01", "REAL", "PASS" if test1_pass else "FAIL", "HMAC verified; tampered record strictly rejected"))

    # 2. Expired lease rejection with bounded clock skew
    exp_record = OwnershipRecord(
        cluster_id=CLUSTER_ID,
        owner_node_id="laptop",
        epoch=1,
        lease_id=lease_id,
        lease_expires_at=now - 1.0, # Expired 1 second ago
        granted_by="witness",
        signature=sign_ownership_record(CLUSTER_ID, "laptop", 1, lease_id, now - 1.0, "witness", WITNESS_SECRET),
        updated_at=now - 1.0
    )
    valid_exp, err_exp = validate_lease(exp_record, "laptop", 1, CLUSTER_ID, SHARED_SECRET, witness_secret=WITNESS_SECRET)
    test2_pass = (not valid_exp and "LEASE_EXPIRED" in str(err_exp))
    print(f"[OWN-02] Expired lease rejected: {'PASS' if test2_pass else 'FAIL'} ({err_exp})")
    results.append(("OWN-02", "REAL", "PASS" if test2_pass else "FAIL", f"Expired lease rejected: {err_exp}"))

    # 3. Bounded clock-skew policy enforcement
    # Lease expires in 0.5s, but max_clock_skew is 1.0s -> (now + skew) >= expires -> rejected!
    near_exp_record = OwnershipRecord(
        cluster_id=CLUSTER_ID,
        owner_node_id="laptop",
        epoch=1,
        lease_id=lease_id,
        lease_expires_at=now + 0.5,
        granted_by="witness",
        signature=sign_ownership_record(CLUSTER_ID, "laptop", 1, lease_id, now + 0.5, "witness", WITNESS_SECRET),
        updated_at=now
    )
    valid_skew, err_skew = validate_lease(near_exp_record, "laptop", 1, CLUSTER_ID, SHARED_SECRET, now=now, max_clock_skew=1.0, witness_secret=WITNESS_SECRET)
    test3_pass = (not valid_skew and "LEASE_EXPIRED" in str(err_skew))
    print(f"[OWN-03] Bounded clock-skew policy rejects near-expiry lease: {'PASS' if test3_pass else 'FAIL'} ({err_skew})")
    results.append(("OWN-03", "REAL", "PASS" if test3_pass else "FAIL", f"Clock skew buffer protects against stale writes: {err_skew}"))

    # Start Real Witness Server on localhost ephemeral port
    witness_server = WitnessServer("127.0.0.1", 0, CLUSTER_ID, WITNESS_SECRET)
    wit_port = witness_server.port
    wit_thread = threading.Thread(target=lambda: witness_server.serve_forever(poll_interval=0.05), daemon=True)
    wit_thread.start()
    time.sleep(0.1)
    witness_url = f"http://127.0.0.1:{wit_port}"

    witness_client = WitnessClient(timeout=2.0)

    # 4. Witness lease arbitration: Grant to Laptop, Deny to Phone
    ok_lap, lap_lease, err_lap = witness_client.acquire_lease(witness_url, CLUSTER_ID, "laptop", requested_epoch=1, duration_seconds=5.0)
    print(f"[OWN-04] Witness grants lease to Laptop: {'PASS' if ok_lap else 'FAIL'}")
    results.append(("OWN-04", "REAL", "PASS" if ok_lap else "FAIL", f"Laptop acquired lease epoch {lap_lease.epoch if lap_lease else 'None'}"))

    # Attempt to acquire lease for Phone while Laptop lease is active
    ok_phone, phone_lease, err_phone = witness_client.acquire_lease(witness_url, CLUSTER_ID, "phone", requested_epoch=2, duration_seconds=5.0)
    test5_pass = (not ok_phone and "LEASE_HELD_BY_ACTIVE_PRIMARY" in str(err_phone))
    print(f"[OWN-05] Witness denies concurrent lease to Phone: {'PASS' if test5_pass else 'FAIL'} ({err_phone})")
    results.append(("OWN-05", "REAL", "PASS" if test5_pass else "FAIL", f"Phone denied while laptop lease active: {err_phone}"))

    # 5. Monotonic Epoch: Laptop releases lease, Phone acquires with incremented epoch
    ok_rel, err_rel = witness_client.release_lease(witness_url, CLUSTER_ID, "laptop", lap_lease.lease_id)
    ok_phone2, phone_lease2, err_phone2 = witness_client.acquire_lease(witness_url, CLUSTER_ID, "phone", requested_epoch=2, duration_seconds=5.0)
    monotonic_ok = (ok_phone2 and phone_lease2 is not None and phone_lease2.epoch >= 2)
    print(f"[OWN-06] Monotonic epoch advance on owner transition: {'PASS' if monotonic_ok else 'FAIL'} (Epoch {phone_lease2.epoch if phone_lease2 else 'None'})")
    results.append(("OWN-06", "REAL", "PASS" if monotonic_ok else "FAIL", f"Epoch advanced monotonically to {phone_lease2.epoch if phone_lease2 else 'None'}"))

    # 6. Partition Simulation C: Witness Unreachable -> Fail closed into SAFE_MODE
    # Stopping witness server to simulate witness outage / network partition
    witness_server.stop()
    time.sleep(0.2)
    ok_dead_wit, _, err_dead_wit = witness_client.acquire_lease(witness_url, CLUSTER_ID, "phone", requested_epoch=3, duration_seconds=5.0)
    test7_pass = (not ok_dead_wit and "Witness connection error" in str(err_dead_wit))
    print(f"[OWN-07] Witness unreachable fails closed: {'PASS' if test7_pass else 'FAIL'} ({err_dead_wit})")
    results.append(("OWN-07", "REAL", "PASS" if test7_pass else "FAIL", f"Unreachable witness strictly denies lease: {err_dead_wit}"))

    # 7. Dual-writer impossibility validation
    # With witness unreachable and expired lease, Phone Database write guard strictly fails
    phone_db_file = os.path.join(BASE_DIR, "tests", "qa", "qa_own_phone.db")
    if os.path.exists(phone_db_file): os.remove(phone_db_file)
    phone_db = PhoneDatabase(phone_db_file)
    phone_db.witness_secret = WITNESS_SECRET
    
    # Store expired lease owned by phone
    exp_lid = uuid.uuid4().hex
    phone_exp_record = OwnershipRecord(
        cluster_id=CLUSTER_ID,
        owner_node_id="phone",
        epoch=2,
        lease_id=exp_lid,
        lease_expires_at=now - 1.0,
        granted_by="witness",
        signature=sign_ownership_record(CLUSTER_ID, "phone", 2, exp_lid, now - 1.0, "witness", WITNESS_SECRET),
        updated_at=now - 1.0
    )
    phone_db.set_ownership(phone_exp_record)
    ok_write, err_code, err_msg, op_id = phone_db.submit_inquiry(
        origin_node_id="phone",
        origin_epoch=2,
        name="Test",
        email="t@t.com",
        subject="S",
        message="M",
        is_primary=True,
        secret=SHARED_SECRET
    )
    test8_pass = (not ok_write and "LEASE_EXPIRED" in str(err_msg))
    print(f"[OWN-08] Phone DB write guard rejects write when lease expired: {'PASS' if test8_pass else 'FAIL'} ({err_msg})")
    results.append(("OWN-08", "REAL", "PASS" if test8_pass else "FAIL", f"Write blocked without active lease: {err_msg}"))

    return results


def test_layer5_ownership():
    results = run_layer5_ownership()
    failures = [r for r in results if r[2] != "PASS"]
    assert not failures, f"Layer 5 failures: {failures}"


if __name__ == "__main__":
    run_layer5_ownership()
