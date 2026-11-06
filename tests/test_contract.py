"""
SentinelDR API Contract Parity Tests
Verifies that both Laptop and Phone nodes adhere strictly to the uniform
SentinelDR API contract, response envelope, and error format.
"""

import os
import sys
import threading
import time
import uuid
import json
import urllib.request
import urllib.error
import pytest
from starlette.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from laptop.server import app as laptop_app
from phone.server import PhoneServer, PhoneRequestHandler
from shared.config import NodeConfig
from shared.api_contract import ALL_STATES
from shared.security import build_peer_headers


# Fixture for Laptop Test Client
@pytest.fixture(scope="module")
def laptop_client():
    return TestClient(laptop_app)


# Fixture for Phone HTTP Server running in background thread
@pytest.fixture(scope="module")
def phone_server_url(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("phone_test")
    db_path = str(tmp_dir / "phone_test.db")
    nonce_path = str(tmp_dir / "phone_nonce.db")

    config = NodeConfig(node_type="phone")
    config.port = 0  # Dynamic ephemeral port to avoid collisions
    config.database_path = db_path
    config.nonce_cache_db = nonce_path

    server = PhoneServer(config)
    t = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.1), daemon=True)
    t.start()
    time.sleep(0.1)  # Allow socket to bind

    url = f"http://127.0.0.1:{server.config.port}"
    yield url, config

    server.stop()


def phone_request(base_url: str, path: str, headers: dict = None) -> tuple:
    """Helper to perform HTTP requests against phone server using standard library."""
    req = urllib.request.Request(f"{base_url}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            status = resp.status
            body = json.loads(resp.read().decode("utf-8"))
            return status, body
    except urllib.error.HTTPError as e:
        status = e.code
        body = json.loads(e.read().decode("utf-8"))
        return status, body


def assert_standard_envelope(data: dict, expected_node: str):
    """Verify envelope keys and structure."""
    assert "ok" in data, "Envelope must contain 'ok'"
    assert "data" in data, "Envelope must contain 'data'"
    assert "error" in data, "Envelope must contain 'error'"
    assert "request_id" in data, "Envelope must contain 'request_id'"
    assert "node_id" in data, "Envelope must contain 'node_id'"
    assert "epoch" in data, "Envelope must contain 'epoch'"
    assert data["node_id"] == expected_node
    assert isinstance(data["epoch"], int)


# 1. Health Endpoint Parity
def test_laptop_health(laptop_client):
    resp = laptop_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert_standard_envelope(body, expected_node="laptop")
    assert body["ok"] is True
    assert body["data"]["status"] == "HEALTHY"
    assert body["data"]["db_ready"] is True


def test_phone_health(phone_server_url):
    url, _ = phone_server_url
    status, body = phone_request(url, "/health")
    assert status == 200
    assert_standard_envelope(body, expected_node="phone")
    assert body["ok"] is True
    assert body["data"]["status"] == "HEALTHY"
    assert body["data"]["db_ready"] is True


# 2. Status Endpoint Parity
def test_laptop_status(laptop_client):
    resp = laptop_client.get("/api/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    assert_standard_envelope(body, expected_node="laptop")
    assert body["ok"] is True
    data = body["data"]
    assert data["node_type"] == "laptop"
    assert data["role"] in ALL_STATES
    assert data["db_ready"] is True
    assert "uptime_seconds" in data
    assert "cluster_id" in data


def test_phone_status(phone_server_url):
    url, _ = phone_server_url
    status, body = phone_request(url, "/api/v1/status")
    assert status == 200
    assert_standard_envelope(body, expected_node="phone")
    assert body["ok"] is True
    data = body["data"]
    assert data["node_type"] == "phone"
    assert data["role"] in ALL_STATES
    assert data["db_ready"] is True
    assert "uptime_seconds" in data
    assert "cluster_id" in data


# 3. Metrics Endpoint Parity
def test_laptop_metrics(laptop_client):
    resp = laptop_client.get("/api/v1/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert_standard_envelope(body, expected_node="laptop")
    assert body["ok"] is True
    data = body["data"]
    assert data["db_healthy"] is True
    assert data["requests_total"] >= 1
    assert data["uptime_seconds"] >= 0


def test_phone_metrics(phone_server_url):
    url, _ = phone_server_url
    status, body = phone_request(url, "/api/v1/metrics")
    assert status == 200
    assert_standard_envelope(body, expected_node="phone")
    assert body["ok"] is True
    data = body["data"]
    assert data["db_healthy"] is True
    assert data["requests_total"] >= 1
    assert data["uptime_seconds"] >= 0


# 4. Events Authenticated Endpoint Parity
def test_laptop_events_unauthenticated(laptop_client):
    resp = laptop_client.get("/api/v1/events")
    assert resp.status_code == 401
    body = resp.json()
    assert_standard_envelope(body, expected_node="laptop")
    assert body["ok"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_phone_events_unauthenticated(phone_server_url):
    url, _ = phone_server_url
    status, body = phone_request(url, "/api/v1/events")
    assert status == 401
    assert_standard_envelope(body, expected_node="phone")
    assert body["ok"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_laptop_events_admin_key(laptop_client):
    from shared.config import NodeConfig
    cfg = NodeConfig("laptop")
    resp = laptop_client.get("/api/v1/events", headers={"Authorization": f"Bearer {cfg.admin_key}"})
    assert resp.status_code == 200
    body = resp.json()
    assert_standard_envelope(body, expected_node="laptop")
    assert body["ok"] is True
    assert "events" in body["data"]


def test_phone_events_admin_key(phone_server_url):
    url, cfg = phone_server_url
    status, body = phone_request(url, "/api/v1/events", headers={"Authorization": f"Bearer {cfg.admin_key}"})
    assert status == 200
    assert_standard_envelope(body, expected_node="phone")
    assert body["ok"] is True
    assert "events" in body["data"]


def test_laptop_events_hmac_signed(laptop_client):
    from shared.config import NodeConfig
    cfg = NodeConfig("laptop")
    headers = build_peer_headers(
        node_id="phone",
        epoch=1,
        secret=cfg.hmac_secret,
        method="GET",
        path="/api/v1/events",
        body=b""
    )
    resp = laptop_client.get("/api/v1/events", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert_standard_envelope(body, expected_node="laptop")
    assert body["ok"] is True


def test_phone_events_hmac_signed(phone_server_url):
    url, cfg = phone_server_url
    headers = build_peer_headers(
        node_id="laptop",
        epoch=1,
        secret=cfg.hmac_secret,
        method="GET",
        path="/api/v1/events",
        body=b""
    )
    status, body = phone_request(url, "/api/v1/events", headers=headers)
    assert status == 200
    assert_standard_envelope(body, expected_node="phone")
    assert body["ok"] is True


# 5. Not Found (404) Parity
def test_laptop_404(laptop_client):
    resp = laptop_client.get("/non_existent_path")
    assert resp.status_code == 404
    body = resp.json()
    assert_standard_envelope(body, expected_node="laptop")
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_phone_404(phone_server_url):
    url, _ = phone_server_url
    status, body = phone_request(url, "/non_existent_path")
    assert status == 404
    assert_standard_envelope(body, expected_node="phone")
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"
