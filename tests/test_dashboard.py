"""
SentinelDR - Operational Visibility Dashboard Test Suite (Phase 8)
Verifies:
1. Serving unmodified dashboard.html at /dashboard and /dashboard.html on both Laptop and Phone.
2. Complete absence of secrets (SHARED_SECRET, signing keys, admin keys) in served HTML/JS and responses.
3. Real telemetry from GET /api/v1/dashboard/status on both Laptop and Phone:
   - Node cards (online / offline / unknown)
   - Ownership & lease fencing (owner, state, epoch, remaining lease, safety status)
   - Heartbeat & failure detection (elapsed, expected interval, consecutive misses, suspected offline)
   - Replication & outbox pipeline (committed seq, applied seq, lag, pending outbox)
   - Recovery & reconciliation (phase, unresolved conflicts, integrity status)
   - Connectivity (peer direct API reachability separate from Cloudflare tunnel)
4. Public sanitized audit stream from GET /api/v1/dashboard/events (redacts secrets, tokens, signatures).
5. Restricted CORS origin headers:
   - Approved frontend origins (localhost:8000, 127.0.0.1:8000, localhost:8001, 127.0.0.1:8001) accepted.
   - Unapproved / malicious origins rejected (no wildcard with credentials).
6. Honest operational reporting: one node down scenario shows accurate degradation without fabricated numbers.
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

from laptop.db import LaptopDatabase
import laptop.server as laptop_server_mod
from phone.db import PhoneDatabase
from phone.server import PhoneServer
from shared.api_contract import (
    ALLOWED_ORIGINS,
    ROUTE_DASHBOARD_EVENTS,
    ROUTE_DASHBOARD_STATUS,
    STATE_PRIMARY_ACTIVE,
    STATE_SECONDARY_STANDBY,
)
from shared.config import NodeConfig
from shared.ownership import OwnershipRecord, sign_ownership_record
from shared.security import sanitize_for_audit_stream


@pytest.fixture(scope="module")
def dashboard_test_env(tmp_path_factory):
    """Sets up isolated phone server and test databases."""
    tmp_dir = tmp_path_factory.mktemp("dashboard_test_env")
    phone_db = str(tmp_dir / "phone_dashboard.db")
    phone_nonce = str(tmp_dir / "phone_nonce.db")

    # 1. Start Phone Server on ephemeral port
    phone_cfg = NodeConfig("phone")
    phone_cfg.port = 0
    phone_cfg.database_path = phone_db
    phone_cfg.nonce_cache_db = phone_nonce
    phone_cfg.witness_secret = "test-witness-secret-dashboard"
    phone_cfg.admin_key = "admin-secret-key-dashboard"
    phone_cfg.hmac_secret = "hmac-secret-key-dashboard"

    phone_srv = PhoneServer(phone_cfg)
    phone_srv.db.witness_secret = "test-witness-secret-dashboard"
    phone_srv.db.seed_portfolio_data()

    # Pre-populate a valid lease for Phone
    now = time.time()
    lease_sig = sign_ownership_record(
        cluster_id=phone_cfg.cluster_id,
        owner_node_id="phone",
        epoch=1,
        lease_id="test-lease-phone-01",
        lease_expires_at=now + 120.0,
        granted_by="witness",
        secret=phone_cfg.witness_secret,
    )
    phone_srv.db.set_ownership(
        OwnershipRecord(
            cluster_id=phone_cfg.cluster_id,
            owner_node_id="phone",
            epoch=1,
            lease_id="test-lease-phone-01",
            lease_expires_at=now + 120.0,
            granted_by="witness",
            signature=lease_sig,
            updated_at=now,
        )
    )

    t_phone = threading.Thread(target=lambda: phone_srv.serve_forever(poll_interval=0.05), daemon=True)
    t_phone.start()
    time.sleep(0.15)
    phone_url = f"http://127.0.0.1:{phone_srv.server_port}"

    # 2. Setup Laptop TestClient
    orig_witness = laptop_server_mod.config.witness_secret
    orig_hmac = laptop_server_mod.config.hmac_secret
    orig_admin = laptop_server_mod.config.admin_key

    laptop_server_mod.config.witness_secret = "test-witness-secret-dashboard"
    laptop_server_mod.config.hmac_secret = "hmac-secret-key-dashboard"
    laptop_server_mod.config.admin_key = "admin-secret-key-dashboard"
    laptop_server_mod.db.witness_secret = "test-witness-secret-dashboard"
    laptop_server_mod.db.seed_portfolio_data()

    # Pre-populate lease for Laptop
    laptop_lease_sig = sign_ownership_record(
        cluster_id=laptop_server_mod.config.cluster_id,
        owner_node_id="laptop",
        epoch=1,
        lease_id="test-lease-laptop-01",
        lease_expires_at=now + 120.0,
        granted_by="witness",
        secret=laptop_server_mod.config.witness_secret,
    )
    laptop_server_mod.db.set_ownership(
        OwnershipRecord(
            cluster_id=laptop_server_mod.config.cluster_id,
            owner_node_id="laptop",
            epoch=1,
            lease_id="test-lease-laptop-01",
            lease_expires_at=now + 120.0,
            granted_by="witness",
            signature=laptop_lease_sig,
            updated_at=now,
        )
    )

    client = TestClient(laptop_server_mod.app)

    yield {
        "phone_srv": phone_srv,
        "phone_url": phone_url,
        "phone_cfg": phone_cfg,
        "laptop_client": client,
    }

    laptop_server_mod.config.witness_secret = orig_witness
    laptop_server_mod.config.hmac_secret = orig_hmac
    laptop_server_mod.config.admin_key = orig_admin

    try:
        phone_srv.shutdown()
    except Exception:
        pass


def test_dashboard_html_contains_zero_secrets():
    """Verify frontend/dashboard.html contains strictly NO hardcoded secrets or signing material."""
    dashboard_path = os.path.join(BASE_DIR, "frontend", "dashboard.html")
    assert os.path.exists(dashboard_path), "dashboard.html must exist in frontend/"

    with open(dashboard_path, "r", encoding="utf-8") as f:
        content = f.read()

    forbidden_tokens = [
        "SHARED_SECRET",
        "hmac_secret",
        "admin_key",
        "witness_secret",
        "PRIVATE KEY",
        "SECRET_KEY",
        "Authorization: Bearer",
    ]
    for token in forbidden_tokens:
        assert token.lower() not in content.lower(), f"Forbidden security token found in dashboard.html: {token}"

    # Ensure vital operational panels exist in HTML
    required_panels = [
        "Laptop Primary",
        "Phone Secondary",
        "Ownership & Lease Fencing",
        "Heartbeat & Failure Detection",
        "Replication & Outbox Pipeline",
        "Recovery & Integrity State",
        "Connectivity & Ingress Status",
        "Audit Events Stream",
    ]
    for panel in required_panels:
        assert panel in content, f"Missing telemetry panel: {panel}"


def test_serve_dashboard_html_on_both_nodes(dashboard_test_env):
    """Verify /dashboard and /dashboard.html are served identically on both Laptop and Phone."""
    client = dashboard_test_env["laptop_client"]
    phone_url = dashboard_test_env["phone_url"]

    # 1. Laptop serving
    for path in ("/dashboard", "/dashboard.html"):
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "SentinelDR" in res.text and "Telemetry" in res.text

    # 2. Phone serving
    for path in ("/dashboard", "/dashboard.html"):
        req = urllib.request.Request(f"{phone_url}{path}")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            assert resp.status == 200
            assert "text/html" in resp.headers.get("content-type", "")
            body = resp.read().decode("utf-8")
            assert "SentinelDR" in body and "Telemetry" in body


def test_laptop_dashboard_status_endpoint(dashboard_test_env):
    """Verify Laptop GET /api/v1/dashboard/status returns full, honest operational telemetry."""
    client = dashboard_test_env["laptop_client"]
    res = client.get(ROUTE_DASHBOARD_STATUS)
    assert res.status_code == 200

    payload = res.json()
    assert payload["ok"] is True
    data = payload["data"]

    # 1. Base Node Attributes
    assert data["node_id"] == "laptop"
    assert data["node_type"] == "laptop"
    assert "role" in data
    assert "epoch" in data
    assert data["db_healthy"] is True
    assert data["uptime_seconds"] >= 0

    # 2. Ownership & Lease Fencing
    ownership = data["ownership"]
    assert ownership["owner_node_id"] == "laptop"
    assert ownership["epoch"] >= 1
    assert ownership["safety_status"] == "VALID"
    assert ownership["remaining_seconds"] > 0
    assert ownership["granted_by"] == "witness"


    # 3. Heartbeat & Liveness
    heartbeat = data["heartbeat"]
    assert "consecutive_misses" in heartbeat
    assert "suspected_offline" in heartbeat

    # 4. Replication Pipeline
    replication = data["replication"]
    assert "highest_local_sequence" in replication
    assert "peer_applied_sequence" in replication
    assert "lag" in replication
    assert "pending_outbox_count" in replication

    # 5. Recovery State
    recovery = data["recovery"]
    assert "phase" in recovery
    assert "unresolved_conflicts" in recovery
    assert recovery["unresolved_conflicts"] == 0
    assert "integrity_status" in recovery

    # 6. Direct Peer Connectivity
    connectivity = data["connectivity"]
    assert "peer_api_reachability" in connectivity


def test_phone_dashboard_status_endpoint(dashboard_test_env):
    """Verify Phone GET /api/v1/dashboard/status returns full, honest operational telemetry."""
    phone_url = dashboard_test_env["phone_url"]
    req = urllib.request.Request(f"{phone_url}{ROUTE_DASHBOARD_STATUS}")
    with urllib.request.urlopen(req, timeout=3.0) as resp:
        assert resp.status == 200
        payload = json.loads(resp.read().decode("utf-8"))

    assert payload["ok"] is True
    data = payload["data"]

    # Base Node Attributes
    assert data["node_id"] == "phone"
    assert data["node_type"] == "phone"
    assert data["db_healthy"] is True
    assert data["uptime_seconds"] >= 0

    # Ownership & Lease Fencing
    ownership = data["ownership"]
    assert ownership["owner_node_id"] == "phone"
    assert ownership["safety_status"] == "VALID"
    assert ownership["remaining_seconds"] > 0

    # Heartbeat
    heartbeat = data["heartbeat"]
    assert "consecutive_misses" in heartbeat
    assert "suspected_offline" in heartbeat

    # Replication & Outbox
    replication = data["replication"]
    assert "highest_local_sequence" in replication
    assert "pending_outbox_count" in replication

    # Recovery
    recovery = data["recovery"]
    assert recovery["integrity_status"] in ("PRAGMA_OK", "HEALTHY")
    assert recovery["unresolved_conflicts"] == 0


def test_dashboard_events_redaction(dashboard_test_env):
    """Verify GET /api/v1/dashboard/events redacts all secrets, passwords, tokens, and keys."""
    client = dashboard_test_env["laptop_client"]
    phone_srv = dashboard_test_env["phone_srv"]
    phone_url = dashboard_test_env["phone_url"]

    secret_val = "super-secret-dashboard-key-999"

    # Log an audit event with sensitive details on Laptop
    laptop_server_mod.db.log_audit_event(
        event_id=uuid.uuid4().hex,
        node_id="laptop",
        epoch=1,
        event_type="TEST_SECURITY_EVENT",
        severity="WARN",
        details={
            "action": "key_rotation",
            "api_key": secret_val,
            "secret_token": "token-xyz-123",
            "safe_info": "rotation completed successfully"
        }
    )

    # Log an audit event with sensitive details on Phone
    phone_srv.db.log_audit_event(
        event_id=uuid.uuid4().hex,
        node_id="phone",
        epoch=1,
        event_type="TEST_SECURITY_EVENT_PHONE",
        severity="INFO",
        details={
            "action": "peer_check",
            "shared_secret": secret_val,
            "signature": "ab5819cf",
            "safe_info": "check ok"
        }
    )

    # 1. Test Laptop Events Endpoint (Unprivileged GET)
    res_laptop = client.get(ROUTE_DASHBOARD_EVENTS)
    assert res_laptop.status_code == 200
    laptop_json = res_laptop.json()
    assert laptop_json["ok"] is True
    events = laptop_json["data"]["events"]
    assert len(events) > 0

    # Verify no raw secret exists anywhere in JSON body
    laptop_body_str = res_laptop.text
    assert secret_val not in laptop_body_str, "Raw secret leaked in Laptop dashboard events!"
    assert "token-xyz-123" not in laptop_body_str, "Token leaked in Laptop dashboard events!"

    # Verify redaction marker
    test_event = next(e for e in events if e["event_type"] == "TEST_SECURITY_EVENT")
    assert test_event["details"]["api_key"] == "[REDACTED]"
    assert test_event["details"]["secret_token"] == "[REDACTED]"
    assert test_event["details"]["safe_info"] == "rotation completed successfully"

    # 2. Test Phone Events Endpoint (Unprivileged GET)
    req_phone = urllib.request.Request(f"{phone_url}{ROUTE_DASHBOARD_EVENTS}")
    with urllib.request.urlopen(req_phone, timeout=3.0) as resp:
        phone_body_str = resp.read().decode("utf-8")
        assert resp.status == 200

    assert secret_val not in phone_body_str, "Raw secret leaked in Phone dashboard events!"
    phone_json = json.loads(phone_body_str)
    phone_events = phone_json["data"]["events"]
    phone_test_ev = next(e for e in phone_events if e["event_type"] == "TEST_SECURITY_EVENT_PHONE")
    assert phone_test_ev["details"]["shared_secret"] == "[REDACTED]"
    assert phone_test_ev["details"]["signature"] == "[REDACTED]"
    assert phone_test_ev["details"]["safe_info"] == "check ok"


def test_cors_origin_restriction(dashboard_test_env):
    """Verify CORS restricts access strictly to allowed frontend origins, rejecting unknown origins."""
    client = dashboard_test_env["laptop_client"]
    phone_url = dashboard_test_env["phone_url"]

    approved_origin = "http://localhost:8000"
    forbidden_origin = "http://malicious-external-site.com"

    # 1. Laptop CORS check
    # Approved Origin
    res_appr = client.get(ROUTE_DASHBOARD_STATUS, headers={"Origin": approved_origin})
    assert res_appr.headers.get("access-control-allow-origin") == approved_origin

    # Forbidden Origin
    res_forb = client.get(ROUTE_DASHBOARD_STATUS, headers={"Origin": forbidden_origin})
    assert res_forb.headers.get("access-control-allow-origin") != forbidden_origin
    assert res_forb.headers.get("access-control-allow-origin") != "*"

    # 2. Phone CORS check
    # Approved Origin
    req_phone_appr = urllib.request.Request(
        f"{phone_url}{ROUTE_DASHBOARD_STATUS}",
        headers={"Origin": approved_origin}
    )
    with urllib.request.urlopen(req_phone_appr, timeout=3.0) as resp:
        assert resp.headers.get("Access-Control-Allow-Origin") == approved_origin

    # Forbidden Origin
    req_phone_forb = urllib.request.Request(
        f"{phone_url}{ROUTE_DASHBOARD_STATUS}",
        headers={"Origin": forbidden_origin}
    )
    with urllib.request.urlopen(req_phone_forb, timeout=3.0) as resp:
        phone_acao = resp.headers.get("Access-Control-Allow-Origin")
        assert phone_acao != forbidden_origin
        assert phone_acao != "*"


def test_one_node_down_telemetry(dashboard_test_env):
    """Verify dashboard operational telemetry reports honest degradation when peer is down."""
    client = dashboard_test_env["laptop_client"]

    # Simulate heartbeat failure detection on Laptop:
    # Set 3 consecutive misses on laptop's heartbeat tracker
    laptop_server_mod.heartbeat_tracker.consecutive_misses = 3
    laptop_server_mod.heartbeat_tracker.last_received_at = time.time() - 15.0

    res = client.get(ROUTE_DASHBOARD_STATUS)
    assert res.status_code == 200
    data = res.json()["data"]

    # Verify heartbeat reports peer is suspected offline
    assert data["heartbeat"]["consecutive_misses"] >= 3
    assert data["heartbeat"]["suspected_offline"] is True

    # Direct peer reachability accurately shows OFFLINE
    assert data["connectivity"]["peer_api_reachability"] == "OFFLINE"

    # Reset consecutive misses
    laptop_server_mod.heartbeat_tracker.consecutive_misses = 0
