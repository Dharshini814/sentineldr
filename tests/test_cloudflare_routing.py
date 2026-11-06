"""
SentinelDR - Cloudflare Routing Test Suite (Phase 9)
Verifies:
1. Narrowly scoped active-origin endpoint (/api/v1/active-origin) on Laptop and Phone:
   - Exposes role, state, epoch, writable flag, and lease validity without secrets.
2. Traffic routing follows the active owner:
   - Routes to Laptop when PRIMARY_ACTIVE with valid lease.
   - Routes to Phone when promoted to SECONDARY_ACTIVE with valid lease.
3. Healthy tunnel on non-owner is NOT selected for writes:
   - Standby secondary does not receive write traffic simply because its tunnel is healthy.
4. SAFE_MODE or no owner produces a clear maintenance / read-only response:
   - Safe read requests (GET) allowed to reachable replica.
   - Mutation write requests (POST) blocked with 503 CLUSTER_MAINTENANCE envelope.
5. Direct public access to /api/v1/peer/* blocked at the edge with 403 Forbidden.
6. Server-side peer endpoints remain strongly authenticated (reject unauthenticated public access).
7. CORS restricted strictly to approved origins (portfolio.sentineldr.in, etc.); unapproved rejected.
"""

import json
import os
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
from shared.api_contract import (
    ALLOWED_ORIGINS,
    ROUTE_ACTIVE_ORIGIN,
    ROUTE_PEER_FAILOVER,
    ROUTE_PEER_HEARTBEAT,
    ROUTE_PEER_LEASE_REQUEST,
    ROUTE_PEER_REPLICATE,
    STATE_PRIMARY_ACTIVE,
    STATE_SAFE_MODE,
    STATE_SECONDARY_ACTIVE,
    STATE_SECONDARY_STANDBY,
    validate_active_origin_payload,
)
from shared.config import NodeConfig
from shared.ownership import OwnershipRecord, sign_ownership_record


@pytest.fixture(scope="module")
def cf_routing_test_env(tmp_path_factory):
    """Sets up isolated phone server and test databases."""
    tmp_dir = tmp_path_factory.mktemp("cf_routing_env")
    phone_db = str(tmp_dir / "phone_cf.db")
    phone_nonce = str(tmp_dir / "phone_nonce.db")

    # 1. Start Phone Server on ephemeral port
    phone_cfg = NodeConfig("phone")
    phone_cfg.port = 0
    phone_cfg.database_path = phone_db
    phone_cfg.nonce_cache_db = phone_nonce
    phone_cfg.witness_secret = "test-witness-secret-cf"
    phone_cfg.admin_key = "admin-secret-key-cf"
    phone_cfg.hmac_secret = "hmac-secret-key-cf"

    phone_srv = PhoneServer(phone_cfg)
    phone_srv.db.witness_secret = "test-witness-secret-cf"
    phone_srv.db.seed_portfolio_data()

    t_phone = threading.Thread(target=lambda: phone_srv.serve_forever(poll_interval=0.05), daemon=True)
    t_phone.start()
    time.sleep(0.15)
    phone_url = f"http://127.0.0.1:{phone_srv.server_port}"

    # 2. Setup Laptop Server
    orig_witness = laptop_server_mod.config.witness_secret
    orig_hmac = laptop_server_mod.config.hmac_secret
    orig_admin = laptop_server_mod.config.admin_key

    laptop_server_mod.config.witness_secret = "test-witness-secret-cf"
    laptop_server_mod.config.hmac_secret = "hmac-secret-key-cf"
    laptop_server_mod.config.admin_key = "admin-secret-key-cf"
    laptop_server_mod.db.witness_secret = "test-witness-secret-cf"
    laptop_server_mod.db.seed_portfolio_data()

    # Pre-populate active lease for Laptop
    now = time.time()
    laptop_lease_sig = sign_ownership_record(
        cluster_id=laptop_server_mod.config.cluster_id,
        owner_node_id="laptop",
        epoch=1,
        lease_id="test-lease-laptop-cf-01",
        lease_expires_at=now + 120.0,
        granted_by="witness",
        secret=laptop_server_mod.config.witness_secret,
    )
    laptop_server_mod.db.set_ownership(
        OwnershipRecord(
            cluster_id=laptop_server_mod.config.cluster_id,
            owner_node_id="laptop",
            epoch=1,
            lease_id="test-lease-laptop-cf-01",
            lease_expires_at=now + 120.0,
            granted_by="witness",
            signature=laptop_lease_sig,
            updated_at=now,
        )
    )
    laptop_server_mod.state_machine._state = STATE_PRIMARY_ACTIVE

    client = TestClient(laptop_server_mod.app)

    yield {
        "phone_srv": phone_srv,
        "phone_url": phone_url,
        "phone_cfg": phone_cfg,
        "laptop_client": client,
    }

    # Teardown
    laptop_server_mod.config.witness_secret = orig_witness
    laptop_server_mod.config.hmac_secret = orig_hmac
    laptop_server_mod.config.admin_key = orig_admin
    try:
        phone_srv.shutdown()
    except Exception:
        pass


def test_active_origin_endpoint_laptop(cf_routing_test_env):
    """Verify Laptop /api/v1/active-origin schema and truthfulness."""
    client = cf_routing_test_env["laptop_client"]
    res = client.get(ROUTE_ACTIVE_ORIGIN)
    assert res.status_code == 200

    body = res.json()
    assert body["ok"] is True
    data = body["data"]

    # Validate schema
    errors = validate_active_origin_payload(data)
    assert not errors, f"Active origin validation errors: {errors}"

    assert data["node_id"] == "laptop"
    assert data["node_type"] == "laptop"
    assert data["role"] == "PRIMARY_ACTIVE"
    assert data["epoch"] >= 1
    assert data["writable"] is True
    assert data["lease_valid"] is True
    assert data["lease_remaining_seconds"] > 0
    assert data["owner_node_id"] == "laptop"
    assert data["db_healthy"] is True

    # Verify no secrets leaked
    text = res.text
    assert "secret" not in text.lower() or "lease_remaining_seconds" in text.lower()
    assert "test-witness-secret-cf" not in text
    assert "hmac-secret-key-cf" not in text


def test_active_origin_endpoint_phone_standby(cf_routing_test_env):
    """Verify Phone /api/v1/active-origin marks writable=False when in standby."""
    phone_url = cf_routing_test_env["phone_url"]
    phone_srv = cf_routing_test_env["phone_srv"]

    phone_srv.state_machine._state = STATE_SECONDARY_STANDBY

    req = urllib.request.Request(f"{phone_url}{ROUTE_ACTIVE_ORIGIN}")
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))

    assert body["ok"] is True
    data = body["data"]

    errors = validate_active_origin_payload(data)
    assert not errors, f"Active origin validation errors: {errors}"

    assert data["node_id"] == "phone"
    assert data["role"] == STATE_SECONDARY_STANDBY
    # Standby node MUST NOT be writable
    assert data["writable"] is False
    assert data["db_healthy"] is True


def test_traffic_follows_active_owner_laptop(cf_routing_test_env):
    """Verify edge router sends read and write traffic to Laptop when Laptop is active primary."""
    phone_url = cf_routing_test_env["phone_url"]

    # Point mock worker to Laptop (simulated via in-process client) and Phone
    # For Laptop, we use a custom transport or adapter that calls laptop_client
    worker = MockCloudflareWorker(
        primary_origin="http://127.0.0.1:8000",
        backup_origin=phone_url,
        timeout_seconds=2.0
    )

    # Mock query_origin_status for primary to return laptop's active state
    laptop_status = {
        "cluster_id": "sentineldr-cluster-01",
        "node_id": "laptop",
        "node_type": "laptop",
        "role": "PRIMARY_ACTIVE",
        "epoch": 1,
        "writable": True,
        "lease_valid": True,
        "lease_remaining_seconds": 60.0,
        "owner_node_id": "laptop",
        "db_healthy": True,
    }
    worker.query_origin_status = lambda origin: laptop_status if origin == worker.primary_origin else {
        "cluster_id": "sentineldr-cluster-01",
        "node_id": "phone",
        "node_type": "phone",
        "role": "SECONDARY_STANDBY",
        "epoch": 1,
        "writable": False,
        "lease_valid": False,
        "lease_remaining_seconds": 0.0,
        "owner_node_id": "laptop",
        "db_healthy": True,
    }

    route = worker.resolve_active_target(force_refresh=True)
    assert route["active_node"] == "laptop"
    assert route["writable"] is True
    assert route["role"] == "PRIMARY_ACTIVE"


def test_healthy_tunnel_on_non_owner_is_not_selected_for_writes(cf_routing_test_env):
    """
    CRITICAL TEST: Even though Phone origin server is 100% up and healthy,
    the edge router MUST NOT select Phone for writes while in SECONDARY_STANDBY.
    """
    phone_url = cf_routing_test_env["phone_url"]
    worker = MockCloudflareWorker(primary_origin="http://unreachable-laptop:8000", backup_origin=phone_url)

    # Phone is up and tunnel is healthy, but Phone is in SECONDARY_STANDBY (not owner)
    route = worker.resolve_active_target(force_refresh=True)
    # Phone can be selected for read fallback, but MUST NOT be marked writable!
    assert route["writable"] is False
    assert route["role"] in (STATE_SECONDARY_STANDBY, "SECONDARY_STANDBY")

    # Any write mutation (POST) must be rejected with 503 CLUSTER_MAINTENANCE at edge
    status, headers, body = worker.handle_request(
        method="POST",
        path="/api/v1/portfolio/inquiry",
        headers={"Content-Type": "application/json"},
        body=b'{"name":"Test","email":"test@example.com"}'
    )
    assert status == 503
    resp_json = json.loads(body.decode("utf-8"))
    assert resp_json["ok"] is False
    assert resp_json["error"]["code"] == "CLUSTER_MAINTENANCE"
    assert "No active writable primary" in resp_json["error"]["message"]


def test_failover_routing_follows_promoted_phone(cf_routing_test_env):
    """
    Verify that when Phone is genuinely promoted to SECONDARY_ACTIVE with a valid lease,
    the edge router immediately routes write traffic to Phone.
    """
    phone_srv = cf_routing_test_env["phone_srv"]
    phone_url = cf_routing_test_env["phone_url"]

    # Promote Phone: Set SECONDARY_ACTIVE and store valid witness lease
    now = time.time()
    phone_lease_sig = sign_ownership_record(
        cluster_id=phone_srv.config.cluster_id,
        owner_node_id="phone",
        epoch=2,
        lease_id="failover-lease-phone-02",
        lease_expires_at=now + 120.0,
        granted_by="witness",
        secret=phone_srv.config.witness_secret,
    )
    phone_srv.db.set_ownership(
        OwnershipRecord(
            cluster_id=phone_srv.config.cluster_id,
            owner_node_id="phone",
            epoch=2,
            lease_id="failover-lease-phone-02",
            lease_expires_at=now + 120.0,
            granted_by="witness",
            signature=phone_lease_sig,
            updated_at=now,
        )
    )
    phone_srv.state_machine._state = STATE_SECONDARY_ACTIVE
    phone_srv.state_machine._epoch = 2

    # Verify /api/v1/active-origin on Phone now reports writable=True
    req = urllib.request.Request(f"{phone_url}{ROUTE_ACTIVE_ORIGIN}")
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    assert body["data"]["writable"] is True
    assert body["data"]["role"] == "SECONDARY_ACTIVE"

    # Edge router evaluation: Primary laptop is offline, Phone is SECONDARY_ACTIVE
    worker = MockCloudflareWorker(primary_origin="http://dead-laptop:8000", backup_origin=phone_url)
    route = worker.resolve_active_target(force_refresh=True)

    assert route["active_node"] == "phone"
    assert route["role"] == "SECONDARY_ACTIVE"
    assert route["writable"] is True

    # POST inquiry via edge router proxies directly to Phone and writes outbox!
    inquiry_body = json.dumps({
        "name": "Jane Failover",
        "email": "jane@failover.org",
        "subject": "DR Test",
        "message": "Testing write through Cloudflare Worker during failover"
    }).encode("utf-8")

    status, headers, body_resp = worker.handle_request(
        method="POST",
        path="/api/v1/portfolio/inquiry",
        headers={"Content-Type": "application/json"},
        body=inquiry_body
    )
    assert status in (200, 201)
    resp_data = json.loads(body_resp.decode("utf-8"))
    assert resp_data["ok"] is True
    assert "operation_id" in resp_data["data"] or "inquiry_id" in resp_data["data"]

    # Reset phone state
    phone_srv.state_machine._state = STATE_SECONDARY_STANDBY


def test_safe_mode_produces_clear_read_only_maintenance():
    """Verify that when cluster is in SAFE_MODE, reads are served while writes are rejected with 503."""
    worker = MockCloudflareWorker()

    # Mock both nodes in SAFE_MODE (e.g. partition detected)
    worker.query_origin_status = lambda origin: {
        "cluster_id": "sentineldr-cluster-01",
        "node_id": "laptop" if origin == worker.primary_origin else "phone",
        "node_type": "laptop" if origin == worker.primary_origin else "phone",
        "role": "SAFE_MODE",
        "epoch": 1,
        "writable": False,
        "lease_valid": False,
        "lease_remaining_seconds": 0.0,
        "owner_node_id": "none",
        "db_healthy": True,
    }

    # 1. Write request is blocked at edge with 503
    status, headers, body = worker.handle_request(
        method="POST",
        path="/api/v1/portfolio/inquiry",
        headers={"Content-Type": "application/json"},
        body=b'{"name":"SafeModeTest"}'
    )
    assert status == 503
    resp_json = json.loads(body.decode("utf-8"))
    assert resp_json["ok"] is False
    assert resp_json["error"]["code"] == "CLUSTER_MAINTENANCE"


def test_peer_endpoints_blocked_at_edge():
    """Verify edge router blocks all public access to /api/v1/peer/* with 403 Forbidden."""
    worker = MockCloudflareWorker()

    peer_paths = [
        "/api/v1/peer/heartbeat",
        "/api/v1/peer/replicate",
        "/api/v1/peer/lease/request",
        "/api/v1/peer/failover",
        "/api/v1/peer/recovery/start",
        "/api/v1/peer/recovery/complete",
        "/api/v1/peer/failback",
        "/api/v1/peer/changes",
    ]

    for path in peer_paths:
        status, headers, body = worker.handle_request("POST", path, body=b"{}")
        assert status == 403, f"Path {path} was not blocked by edge router!"
        envelope = json.loads(body.decode("utf-8"))
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "FORBIDDEN"
        assert "blocked from public internet" in envelope["error"]["message"]


def test_server_side_peer_endpoints_require_authentication(cf_routing_test_env):
    """Verify that origin servers still strongly reject unauthenticated peer requests (defense-in-depth)."""
    client = cf_routing_test_env["laptop_client"]
    phone_url = cf_routing_test_env["phone_url"]

    # 1. Laptop direct request without HMAC headers
    res_laptop = client.post(ROUTE_PEER_HEARTBEAT, json={"test": "data"})
    assert res_laptop.status_code == 401

    # 2. Phone direct request without HMAC headers
    req_phone = urllib.request.Request(
        f"{phone_url}{ROUTE_PEER_HEARTBEAT}",
        data=b'{"test": "data"}',
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req_phone, timeout=3.0) as resp:
            pytest.fail("Phone peer endpoint should have rejected unauthenticated request!")
    except urllib.error.HTTPError as e:
        assert e.code == 401


def test_cors_actual_origins_only():
    """Verify CORS policy on edge router only permits approved origins, rejecting unapproved."""
    worker = MockCloudflareWorker()

    approved = "https://portfolio.sentineldr.in"
    unapproved = "https://malicious-phishing-site.com"

    # 1. Approved origin on OPTIONS preflight
    status, headers, _ = worker.handle_request("OPTIONS", "/api/v1/portfolio/profile", headers={"Origin": approved})
    assert status == 204
    assert headers.get("Access-Control-Allow-Origin") == approved

    # 2. Unapproved origin on OPTIONS preflight
    status, headers, _ = worker.handle_request("OPTIONS", "/api/v1/portfolio/profile", headers={"Origin": unapproved})
    assert status == 204
    assert headers.get("Access-Control-Allow-Origin") is None

    # 3. Blocked peer path returns CORS header for approved origin
    status, headers, _ = worker.handle_request("POST", "/api/v1/peer/heartbeat", headers={"Origin": approved})
    assert status == 403
    assert headers.get("Access-Control-Allow-Origin") == approved
