"""
SentinelDR - Shared Protocol & Envelope Module
Standard library only (runtime-neutral for Laptop & Phone).
"""

import json
import uuid
import re
from typing import Any, Dict, Optional, Tuple


# Stable Error Codes
ERR_BAD_REQUEST = "BAD_REQUEST"
ERR_UNAUTHORIZED = "UNAUTHORIZED"
ERR_FORBIDDEN = "FORBIDDEN"
ERR_NOT_FOUND = "NOT_FOUND"
ERR_METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
ERR_STALE_TIMESTAMP = "STALE_TIMESTAMP"
ERR_REPLAY_DETECTED = "REPLAY_DETECTED"
ERR_INVALID_SIGNATURE = "INVALID_SIGNATURE"
ERR_INVALID_EPOCH = "INVALID_EPOCH"
ERR_LEASE_EXPIRED = "LEASE_EXPIRED"
ERR_SAFE_MODE = "SAFE_MODE"
ERR_DUAL_WRITER_PREVENTED = "DUAL_WRITER_PREVENTED"
ERR_INTERNAL_ERROR = "INTERNAL_ERROR"
ERR_DB_UNAVAILABLE = "DB_UNAVAILABLE"
ERR_CONFLICT = "CONFLICT"


# Regular expressions for sanitization
RE_PATH_WINDOWS = re.compile(r"[A-Za-z]:\\[\w\\\.\-]+")
RE_PATH_UNIX = re.compile(r"/(?:[a-zA-Z0-9_\-\.]+/?)+")
RE_SQL_ERROR = re.compile(r"(?i)(syntax error at or near|relation \".*\" does not exist|sqlite3\.\w+Error|SELECT .* FROM)")


def sanitize_error_message(msg: str) -> str:
    """Strip paths, raw SQL, and potential sensitive strings from error messages."""
    if not isinstance(msg, str):
        msg = str(msg)
    # Redact Windows paths
    msg = RE_PATH_WINDOWS.sub("[REDACTED_PATH]", msg)
    # Redact Unix paths
    msg = RE_PATH_UNIX.sub("[REDACTED_PATH]", msg)
    # Redact raw SQL errors
    if RE_SQL_ERROR.search(msg):
        msg = "Database operation failed. Details redacted for security."
    return msg


def make_envelope(
    ok: bool,
    data: Optional[Any] = None,
    error: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    node_id: str = "unknown",
    epoch: int = 0
) -> Dict[str, Any]:
    """Build standard SentinelDR response envelope."""
    return {
        "ok": bool(ok),
        "data": data,
        "error": error,
        "request_id": request_id or str(uuid.uuid4()),
        "node_id": node_id,
        "epoch": int(epoch)
    }


def make_success(
    data: Any,
    node_id: str,
    epoch: int,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """Helper to build standard success response."""
    return make_envelope(
        ok=True,
        data=data,
        error=None,
        request_id=request_id,
        node_id=node_id,
        epoch=epoch
    )


def make_error(
    code: str,
    message: str,
    node_id: str,
    epoch: int,
    details: Optional[Any] = None,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """Helper to build standard sanitized error response."""
    safe_message = sanitize_error_message(message)
    safe_details = None
    if details:
        if isinstance(details, str):
            safe_details = sanitize_error_message(details)
        elif isinstance(details, dict):
            safe_details = {k: sanitize_error_message(str(v)) for k, v in details.items()}
        else:
            safe_details = sanitize_error_message(str(details))

    return make_envelope(
        ok=False,
        data=None,
        error={
            "code": code,
            "message": safe_message,
            "details": safe_details
        },
        request_id=request_id,
        node_id=node_id,
        epoch=epoch
    )


def serialize_envelope(envelope: Dict[str, Any]) -> bytes:
    """Serialize envelope to UTF-8 encoded JSON bytes."""
    return json.dumps(envelope, ensure_ascii=False, indent=None).encode("utf-8")


def parse_envelope(body_bytes: bytes) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse JSON body bytes into a dictionary envelope."""
    try:
        data = json.loads(body_bytes.decode("utf-8"))
        if isinstance(data, dict):
            return data, None
        return None, "Root element must be a JSON object"
    except Exception as e:
        return None, f"Malformed JSON: {sanitize_error_message(str(e))}"
