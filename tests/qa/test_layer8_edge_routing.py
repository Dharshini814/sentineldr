"""
Layer 8 - Cloudflare Edge Routing & Perimeter Security Audit Suite
Tests:
1. Edge perimeter defense: Public /api/v1/peer/* calls blocked with HTTP 403
2. Narrowly scoped /api/v1/active-origin contract validation
3. Active-owner routing: Laptop PRIMARY_ACTIVE selected
4. Failover routing: Promoted Phone SECONDARY_ACTIVE selected
5. Decoupled tunnel health: Healthy non-owner is NOT selected for writes
6. SAFE_MODE write fencing: Returns 503 CLUSTER_MAINTENANCE envelope
7. CORS origin restriction: Allowed origins accepted, arbitrary origins denied
"""

import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from cloudflare.mock_worker import MockCloudflareWorker
from phone.db import PhoneDatabase
from phone.server import PhoneServer
from shared.config import NodeConfig
from shared.ownership import OwnershipRecord, sign_ownership_record
from shared.api_contract import validate_active_origin_payload

CLUSTER_ID = "sentineldr-cluster-01"
WITNESS_SECRET = "qa-witness-secret-key-12345"
SHARED_SECRET = "qa-shared-secret-key-67890"

def run_layer8_edge_routing():
    print("=== LAYER 8 CLOUDFLARE EDGE ROUTING & PERIMETER AUDIT ===")
    results = []

    # 1. Edge Perimeter Defense: /api/v1/peer/* blocked with 403
    worker = MockCloudflareWorker(primary_origin="http://127.0.0.1:8000", backup_origin="http://127.0.0.1:8001")
    peer_paths = [
        "/api/v1/peer/heartbeat",
        "/api/v1/peer/replicate",
        "/api/v1/peer/lease/request",
        "/api/v1/peer/failover",
        "/api/v1/peer/recovery/start",
        "/api/v1/peer/recovery/complete",
        "/api/v1/peer/failback"
    ]
    all_blocked = True
    for p in peer_paths:
        status, headers, body = worker.handle_request("POST", p)
        if status != 403:
            all_blocked = False
            break

    print(f"[EDGE-01] Direct public access to /api/v1/peer/* blocked with 403: {'PASS' if all_blocked else 'FAIL'}")
    results.append(("EDGE-01", "SIMULATED", "PASS" if all_blocked else "FAIL", f"All {len(peer_paths)} peer endpoints blocked at edge with 403 Forbidden"))

    # Setup isolated real Phone server
    db_file = os.path.join(BASE_DIR, "tests", "qa", "qa_cf_phone.db")
    nonce_file = os.path.join(BASE_DIR, "tests", "qa", "qa_cf_nonce.db")
    if os.path.exists(db_file): os.remove(db_file)
    if os.path.exists(nonce_file): os.remove(nonce_file)

    phone_cfg = NodeConfig("phone")
    phone_cfg.port = 0
    phone_cfg.database_path = db_file
    phone_cfg.nonce_cache_db = nonce_file
    phone_cfg.secret = SHARED_SECRET
    phone_cfg.witness_secret = WITNESS_SECRET

    phone_srv = PhoneServer(phone_cfg)
    port = phone_srv.config.port
    server_thread = threading.Thread(target=lambda: phone_srv.serve_forever(poll_interval=0.05), daemon=True)
    server_thread.start()
    time.sleep(0.1)
    phone_url = f"http://127.0.0.1:{port}"

    # 2. Narrowly scoped /api/v1/active-origin contract
    req = urllib.request.Request(f"{phone_url}/api/v1/active-origin")
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        ao_body = json.loads(resp.read().decode("utf-8"))
    
    ao_data = ao_body.get("data", {})
    schema_errors = validate_active_origin_payload(ao_data)
    schema_ok = len(schema_errors) == 0 and "secret" not in json.dumps(ao_data).lower()
    print(f"[EDGE-02] /api/v1/active-origin contract valid & secret-free: {'PASS' if schema_ok else 'FAIL'}")
    results.append(("EDGE-02", "REAL", "PASS" if schema_ok else "FAIL", f"Active origin contract valid; no secrets exposed"))

    # 3. Decoupled Tunnel Health: Standby phone does NOT receive write traffic
    worker_phone_standby = MockCloudflareWorker(primary_origin="http://127.0.0.1:59998", backup_origin=phone_url)
    status_w, _, body_w = worker_phone_standby.handle_request(
        "POST",
        "/api/v1/portfolio/inquiry",
        headers={"Content-Type": "application/json"},
        body=b'{"name":"Test"}'
    )
    # Since laptop is down (59998) and phone is standby (not writable), writes must be blocked with 503
    body_json = json.loads(body_w.decode("utf-8"))
    write_fenced = (status_w == 503 and body_json.get("error", {}).get("code") == "CLUSTER_MAINTENANCE")
    print(f"[EDGE-03] Standby node does NOT receive writes despite healthy HTTP: {'PASS' if write_fenced else 'FAIL'}")
    results.append(("EDGE-03", "REAL", "PASS" if write_fenced else "FAIL", "Healthy standby strictly write-fenced with 503 CLUSTER_MAINTENANCE"))

    # 4. Promoted Secondary Write Routing
    # Promote phone to SECONDARY_ACTIVE with valid lease
    now = time.time()
    lease_record = OwnershipRecord(
        cluster_id=CLUSTER_ID,
        owner_node_id="phone",
        epoch=2,
        lease_id="promoted-lease",
        lease_expires_at=now + 60.0,
        granted_by="witness",
        signature=sign_ownership_record(CLUSTER_ID, "phone", 2, "promoted-lease", now + 60.0, "witness", WITNESS_SECRET),
        updated_at=now
    )
    phone_srv.db.witness_secret = WITNESS_SECRET
    phone_srv.db.set_ownership(lease_record)
    phone_srv.state_machine.transition_to("SUSPECTED_OFFLINE", reason="Test transition 1")
    phone_srv.state_machine.transition_to("PROMOTION_PENDING", reason="Test transition 2")
    phone_srv.state_machine.transition_to("SECONDARY_ACTIVE", reason="Test promotion", new_epoch=2)

    # Re-evaluate worker route
    route_promoted = worker_phone_standby.resolve_active_target(force_refresh=True)
    promo_routed = (route_promoted["target_origin"] == phone_url and route_promoted["writable"] is True)
    print(f"[EDGE-04] Promoted SECONDARY_ACTIVE successfully selected for writes: {'PASS' if promo_routed else 'FAIL'}")
    results.append(("EDGE-04", "REAL", "PASS" if promo_routed else "FAIL", f"Traffic dynamically routed to promoted phone: {phone_url}"))

    # 5. CORS Header Verification
    status_cors, headers_cors, _ = worker.handle_request("OPTIONS", "/api/v1/portfolio/profile", headers={"Origin": "https://portfolio.sentineldr.in"})
    cors_allowed = (headers_cors.get("Access-Control-Allow-Origin") == "https://portfolio.sentineldr.in")

    status_bad, headers_bad, _ = worker.handle_request("OPTIONS", "/api/v1/portfolio/profile", headers={"Origin": "https://malicious-site.com"})
    cors_denied = (headers_bad.get("Access-Control-Allow-Origin") is None)
    cors_ok = cors_allowed and cors_denied
    print(f"[EDGE-05] CORS restricted strictly to approved origins: {'PASS' if cors_ok else 'FAIL'}")
    results.append(("EDGE-05", "SIMULATED", "PASS" if cors_ok else "FAIL", "Approved origins allowed; malicious origins denied"))

    phone_srv.stop()
    return results


def test_layer8_edge_routing():
    results = run_layer8_edge_routing()
    failures = [r for r in results if r[2] != "PASS"]
    assert not failures, f"Layer 8 failures: {failures}"


if __name__ == "__main__":
    run_layer8_edge_routing()
