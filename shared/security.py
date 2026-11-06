"""
SentinelDR - Shared Security & Peer Authentication Module
Standard library only (runtime-neutral for Laptop & Phone).
"""

import hashlib
import hmac
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class PersistentNonceCache:
    """Thread-safe persistent nonce cache backed by SQLite to prevent replay attacks."""

    def __init__(self, db_path: str = "nonce_cache.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS nonce_cache (
                        nonce TEXT PRIMARY KEY,
                        created_at REAL NOT NULL
                    )
                    """
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_nonce_created_at ON nonce_cache(created_at)"
                )
                conn.commit()
            finally:
                conn.close()

    def check_and_store(self, nonce: str, timestamp: float, window_seconds: float) -> bool:
        """
        Check if nonce already exists. If not, store it and return True.
        If it exists (replay detected), return False.
        Also prunes nonces older than (now - 2 * window_seconds).
        """
        now = time.time()
        cutoff = now - (window_seconds * 2)

        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            try:
                cursor = conn.cursor()
                # Prune old nonces
                cursor.execute("DELETE FROM nonce_cache WHERE created_at < ?", (cutoff,))

                # Check if nonce exists
                cursor.execute("SELECT 1 FROM nonce_cache WHERE nonce = ?", (nonce,))
                if cursor.fetchone() is not None:
                    conn.commit()
                    return False  # Replay detected!

                # Store new nonce
                cursor.execute(
                    "INSERT INTO nonce_cache (nonce, created_at) VALUES (?, ?)",
                    (nonce, timestamp)
                )
                conn.commit()
                return True
            finally:
                conn.close()


def compute_body_sha256(body: bytes) -> str:
    """Compute hex SHA-256 digest of body bytes."""
    return hashlib.sha256(body).hexdigest()


def compute_canonical_string(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body_sha256: str
) -> str:
    """
    Build canonical representation for request signing:
    METHOD\nPATH\nTIMESTAMP\nNONCE\nBODY_SHA256
    """
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_sha256}"


def sign_request(
    secret: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes
) -> str:
    """Generate hex-encoded HMAC-SHA256 signature for canonical request."""
    body_sha256 = compute_body_sha256(body)
    canonical = compute_canonical_string(method, path, timestamp, nonce, body_sha256)
    signature = hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature


def build_peer_headers(
    node_id: str,
    epoch: int,
    secret: str,
    method: str,
    path: str,
    body: bytes,
    timestamp: Optional[float] = None,
    nonce: Optional[str] = None
) -> Dict[str, str]:
    """Build all required X-SDR-* peer authentication headers for outgoing request."""
    import uuid
    ts_str = str(int(timestamp if timestamp is not None else time.time()))
    nonce_str = nonce or uuid.uuid4().hex
    sig = sign_request(secret, method, path, ts_str, nonce_str, body)

    return {
        "X-SDR-Node": node_id,
        "X-SDR-Epoch": str(epoch),
        "X-SDR-Timestamp": ts_str,
        "X-SDR-Nonce": nonce_str,
        "X-SDR-Signature": sig,
        "Content-Type": "application/json",
        "Content-Length": str(len(body))
    }


def verify_peer_request(
    headers: Dict[str, str],
    method: str,
    path: str,
    body: bytes,
    secret: str,
    nonce_cache: PersistentNonceCache,
    window_seconds: float = 30.0
) -> Tuple[bool, Optional[str], Optional[Dict[str, str]]]:
    """
    Verify incoming peer request HMAC signature, timestamp freshness, and nonce.
    Returns: (is_valid, error_code, caller_metadata)
    """
    # Normalize headers to lowercase for case-insensitive lookup
    normalized_headers = {k.lower(): v for k, v in headers.items()}

    node_id = normalized_headers.get("x-sdr-node") or normalized_headers.get("node")
    ts_val = normalized_headers.get("x-sdr-timestamp") or normalized_headers.get("timestamp")
    nonce = normalized_headers.get("x-sdr-nonce") or normalized_headers.get("nonce")
    epoch_val = normalized_headers.get("x-sdr-epoch") or normalized_headers.get("epoch")
    signature = normalized_headers.get("x-sdr-signature") or normalized_headers.get("signature")

    if not all([node_id, ts_val, nonce, epoch_val, signature]):
        return False, "UNAUTHORIZED", None

    try:
        ts = float(ts_val)
    except ValueError:
        return False, "BAD_REQUEST", None

    # 1. Freshness window check
    now = time.time()
    if abs(now - ts) > window_seconds:
        return False, "STALE_TIMESTAMP", None

    # 2. Replay check via persistent nonce cache
    if not nonce_cache.check_and_store(nonce, ts, window_seconds):
        return False, "REPLAY_DETECTED", None

    # 3. Signature verification (constant-time compare)
    expected_sig = sign_request(secret, method, path, str(int(ts)), nonce, body)
    if not hmac.compare_digest(expected_sig, signature):
        return False, "INVALID_SIGNATURE", None

    try:
        epoch = int(epoch_val)
    except ValueError:
        return False, "INVALID_EPOCH", None

    caller_meta = {
        "node_id": node_id,
        "epoch": epoch,
        "timestamp": ts,
        "nonce": nonce
    }
    return True, None, caller_meta


def verify_admin_key(headers: Dict[str, str], expected_admin_key: str) -> bool:
    """Verify Admin Bearer token in constant time."""
    if not expected_admin_key:
        return False
    normalized = {k.lower(): v for k, v in headers.items()}
    auth_header = normalized.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        return hmac.compare_digest(token, expected_admin_key)
    admin_header = normalized.get("x-sdr-admin-key", "")
    if admin_header:
        return hmac.compare_digest(admin_header.strip(), expected_admin_key)
    return False


def sanitize_for_audit_stream(details: Optional[Dict[str, Any]], secrets: Optional[list] = None) -> Any:
    """
    Sanitize details dictionary or string for unprivileged dashboard audit stream.
    Redacts sensitive keys (secret, key, password, token, signature, auth, credential)
    and replaces occurrences of known secret strings.
    """
    if details is None:
        return None

    active_secrets = [s for s in (secrets or []) if s and isinstance(s, str) and len(s) > 2]

    def _redact_str(val: str) -> str:
        for sec in active_secrets:
            if sec in val:
                val = val.replace(sec, "[REDACTED]")
        return val

    sensitive_substrings = ("secret", "sig", "key", "pass", "token", "auth", "credential")

    if isinstance(details, dict):
        sanitized = {}
        for k, v in details.items():
            k_lower = str(k).lower()
            if any(sub in k_lower for sub in sensitive_substrings):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, (dict, list)):
                sanitized[k] = sanitize_for_audit_stream(v, active_secrets)
            elif isinstance(v, str):
                sanitized[k] = _redact_str(v)
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(details, list):
        return [sanitize_for_audit_stream(item, active_secrets) for item in details]
    elif isinstance(details, str):
        return _redact_str(details)
    return details

