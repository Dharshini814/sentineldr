"""
SentinelDR Security Tests
Verifies HMAC request signing, timestamp freshness, replay rejection,
secret separation, and constant-time authentication.
"""

import os
import sys
import time
import uuid
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from shared.security import (
    PersistentNonceCache,
    build_peer_headers,
    compute_body_sha256,
    compute_canonical_string,
    sign_request,
    verify_admin_key,
    verify_peer_request,
)


@pytest.fixture
def temp_nonce_cache(tmp_path):
    cache_path = str(tmp_path / "test_nonce_cache.db")
    return PersistentNonceCache(cache_path)


def test_persistent_nonce_cache_replay_detection(temp_nonce_cache):
    nonce = uuid.uuid4().hex
    now = time.time()
    window = 30.0

    # First attempt must succeed
    stored_first = temp_nonce_cache.check_and_store(nonce, now, window)
    assert stored_first is True, "First nonce insertion must succeed"

    # Second attempt with same nonce must be detected as replay
    stored_second = temp_nonce_cache.check_and_store(nonce, now, window)
    assert stored_second is False, "Duplicate nonce must be rejected as replay"


def test_persistent_nonce_cache_pruning(temp_nonce_cache):
    window = 10.0
    now = time.time()

    old_nonce = "old-nonce-1"
    old_time = now - (window * 3)  # Outside 2x window
    temp_nonce_cache.check_and_store(old_nonce, old_time, window)

    fresh_nonce = "fresh-nonce-1"
    temp_nonce_cache.check_and_store(fresh_nonce, now, window)

    # Trigger prune by inserting another nonce
    newer_nonce = "newer-nonce-1"
    temp_nonce_cache.check_and_store(newer_nonce, now, window)

    # Verify old nonce was pruned by checking if it can be re-inserted
    re_inserted = temp_nonce_cache.check_and_store(old_nonce, now, window)
    assert re_inserted is True, "Old pruned nonce should no longer exist in cache"


def test_hmac_valid_request(temp_nonce_cache):
    secret = "test-hmac-secret-123456"
    method = "GET"
    path = "/api/v1/events"
    body = b""
    now = time.time()
    nonce = uuid.uuid4().hex

    headers = build_peer_headers(
        node_id="laptop",
        epoch=1,
        secret=secret,
        method=method,
        path=path,
        body=body,
        timestamp=now,
        nonce=nonce
    )

    is_valid, err, meta = verify_peer_request(
        headers=headers,
        method=method,
        path=path,
        body=body,
        secret=secret,
        nonce_cache=temp_nonce_cache,
        window_seconds=30.0
    )

    assert is_valid is True
    assert err is None
    assert meta["node_id"] == "laptop"
    assert meta["epoch"] == 1


def test_hmac_tampered_signature(temp_nonce_cache):
    secret = "test-hmac-secret-123456"
    headers = build_peer_headers(
        node_id="laptop",
        epoch=1,
        secret=secret,
        method="GET",
        path="/api/v1/events",
        body=b""
    )

    # Tamper with signature
    headers["X-SDR-Signature"] = "0" * 64

    is_valid, err, meta = verify_peer_request(
        headers=headers,
        method="GET",
        path="/api/v1/events",
        body=b"",
        secret=secret,
        nonce_cache=temp_nonce_cache
    )

    assert is_valid is False
    assert err == "INVALID_SIGNATURE"


def test_hmac_tampered_body(temp_nonce_cache):
    secret = "test-hmac-secret-123456"
    # Sign empty body
    headers = build_peer_headers(
        node_id="laptop",
        epoch=1,
        secret=secret,
        method="POST",
        path="/api/v1/peer/replicate",
        body=b'{"action":"none"}'
    )

    # Pass altered body to verifier
    is_valid, err, meta = verify_peer_request(
        headers=headers,
        method="POST",
        path="/api/v1/peer/replicate",
        body=b'{"action":"malicious_overwrite"}',
        secret=secret,
        nonce_cache=temp_nonce_cache
    )

    assert is_valid is False
    assert err == "INVALID_SIGNATURE"


def test_hmac_stale_timestamp_past(temp_nonce_cache):
    secret = "test-hmac-secret-123456"
    stale_time = time.time() - 65.0  # 65s ago (window is 30s)

    headers = build_peer_headers(
        node_id="phone",
        epoch=1,
        secret=secret,
        method="GET",
        path="/api/v1/events",
        body=b"",
        timestamp=stale_time
    )

    is_valid, err, meta = verify_peer_request(
        headers=headers,
        method="GET",
        path="/api/v1/events",
        body=b"",
        secret=secret,
        nonce_cache=temp_nonce_cache,
        window_seconds=30.0
    )

    assert is_valid is False
    assert err == "STALE_TIMESTAMP"


def test_hmac_stale_timestamp_future(temp_nonce_cache):
    secret = "test-hmac-secret-123456"
    future_time = time.time() + 65.0  # 65s into future

    headers = build_peer_headers(
        node_id="phone",
        epoch=1,
        secret=secret,
        method="GET",
        path="/api/v1/events",
        body=b"",
        timestamp=future_time
    )

    is_valid, err, meta = verify_peer_request(
        headers=headers,
        method="GET",
        path="/api/v1/events",
        body=b"",
        secret=secret,
        nonce_cache=temp_nonce_cache,
        window_seconds=30.0
    )

    assert is_valid is False
    assert err == "STALE_TIMESTAMP"


def test_hmac_replay_attack_rejected(temp_nonce_cache):
    secret = "test-hmac-secret-123456"
    fixed_nonce = uuid.uuid4().hex
    now = time.time()

    headers = build_peer_headers(
        node_id="phone",
        epoch=1,
        secret=secret,
        method="GET",
        path="/api/v1/events",
        body=b"",
        timestamp=now,
        nonce=fixed_nonce
    )

    # Request 1: Must pass
    valid_1, err_1, _ = verify_peer_request(
        headers=headers,
        method="GET",
        path="/api/v1/events",
        body=b"",
        secret=secret,
        nonce_cache=temp_nonce_cache,
        window_seconds=30.0
    )
    assert valid_1 is True

    # Request 2 (Replay of same headers): Must be rejected
    valid_2, err_2, _ = verify_peer_request(
        headers=headers,
        method="GET",
        path="/api/v1/events",
        body=b"",
        secret=secret,
        nonce_cache=temp_nonce_cache,
        window_seconds=30.0
    )
    assert valid_2 is False
    assert err_2 == "REPLAY_DETECTED"


def test_secret_separation_admin_and_hmac():
    hmac_secret = "hmac-secret-xyz"
    admin_key = "admin-bearer-token-abc"

    # Admin key check with Bearer header
    assert verify_admin_key({"Authorization": f"Bearer {admin_key}"}, admin_key) is True
    # Admin key check with HMAC secret as bearer token must FAIL
    assert verify_admin_key({"Authorization": f"Bearer {hmac_secret}"}, admin_key) is False

    # Empty or wrong headers
    assert verify_admin_key({}, admin_key) is False
    assert verify_admin_key({"Authorization": "Bearer wrong-key"}, admin_key) is False


def test_request_body_size_limits():
    """Verify request size limits (MAX_BODY_BYTES = 5MB) return 413 Payload Too Large."""
    from starlette.testclient import TestClient
    from laptop.server import app as laptop_app
    from shared.replication import MAX_BODY_BYTES

    client = TestClient(laptop_app)

    # Payload exceeding MAX_BODY_BYTES (5MB + 1 byte)
    oversized_body = b"X" * (MAX_BODY_BYTES + 1024)
    resp = client.post(
        "/api/v1/peer/replicate",
        content=oversized_body,
        headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 413
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "PAYLOAD_TOO_LARGE"

