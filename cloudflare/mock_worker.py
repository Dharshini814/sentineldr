"""
SentinelDR - Python Mock Implementation of Cloudflare Worker Edge Router
Mirrors cloudflare/worker.js for local automated testing and CI verification.
"""

import json
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, Tuple

APPROVED_ORIGINS = {
    "https://portfolio.sentineldr.in",
    "https://primary-origin.sentineldr.in",
    "https://backup-origin.sentineldr.in",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
}


class MockCloudflareWorker:
    """
    Python simulation of Cloudflare Worker Edge Router.
    Enforces identical guarantees to cloudflare/worker.js:
    - Blocks public access to /api/v1/peer/*
    - Evaluates /api/v1/active-origin
    - Enforces active-owner routing (tunnel health alone never routes writes to non-owner)
    - Fences writes when cluster is in safe mode or standby
    - Validates CORS origins
    """

    def __init__(
        self,
        primary_origin: str = "http://127.0.0.1:8000",
        backup_origin: str = "http://127.0.0.1:8001",
        timeout_seconds: float = 2.5,
        cache_ttl_seconds: float = 1.5,
    ):
        self.primary_origin = primary_origin
        self.backup_origin = backup_origin
        self.timeout = timeout_seconds
        self.cache_ttl = cache_ttl_seconds

        self._cached_route: Optional[Dict[str, Any]] = None
        self._cache_timestamp: float = 0.0

    def query_origin_status(self, origin_url: str) -> Optional[Dict[str, Any]]:
        """Query /api/v1/active-origin on candidate origin."""
        req = urllib.request.Request(
            f"{origin_url}/api/v1/active-origin",
            headers={"Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("data") if (data and data.get("ok")) else None
        except Exception:
            return None

    def resolve_active_target(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Determine eligible active origin based on /api/v1/active-origin."""
        now = time.time()
        if not force_refresh and self._cached_route and (now - self._cache_timestamp) < self.cache_ttl:
            return self._cached_route

        primary_status = self.query_origin_status(self.primary_origin)
        backup_status = self.query_origin_status(self.backup_origin)

        selected = {
            "target_origin": None,
            "active_node": None,
            "role": None,
            "writable": False,
        }

        # Rule 1: Active Primary Writer (Laptop)
        if primary_status and primary_status.get("writable") and primary_status.get("role") == "PRIMARY_ACTIVE":
            selected["target_origin"] = self.primary_origin
            selected["active_node"] = "laptop"
            selected["role"] = "PRIMARY_ACTIVE"
            selected["writable"] = True
        # Rule 2: Active Promoted Secondary (Phone failover)
        elif backup_status and backup_status.get("writable") and backup_status.get("role") == "SECONDARY_ACTIVE":
            selected["target_origin"] = self.backup_origin
            selected["active_node"] = "phone"
            selected["role"] = "SECONDARY_ACTIVE"
            selected["writable"] = True
        # Rule 3: Read-only standby / recovering fallback
        elif primary_status and primary_status.get("db_healthy"):
            selected["target_origin"] = self.primary_origin
            selected["active_node"] = "laptop"
            selected["role"] = primary_status.get("role")
            selected["writable"] = False
        elif backup_status and backup_status.get("db_healthy"):
            selected["target_origin"] = self.backup_origin
            selected["active_node"] = "phone"
            selected["role"] = backup_status.get("role")
            selected["writable"] = False

        self._cached_route = selected
        self._cache_timestamp = now
        return selected

    def handle_request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
        force_refresh: bool = False,
    ) -> Tuple[int, Dict[str, str], bytes]:
        """Simulate Cloudflare Worker request pipeline."""
        headers = headers or {}
        origin_header = headers.get("Origin") or headers.get("origin")

        # 1. Edge Perimeter Defense: Block public access to internal peer endpoints
        if path.startswith("/api/v1/peer/"):
            err_envelope = {
                "ok": False,
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Direct access to internal peer replication endpoints is blocked from public internet."
                },
                "node_id": "edge-router",
                "epoch": 0
            }
            resp_headers = {"Content-Type": "application/json; charset=utf-8"}
            self._apply_cors(resp_headers, origin_header)
            return 403, resp_headers, json.dumps(err_envelope).encode("utf-8")

        # 2. CORS Preflight
        if method == "OPTIONS":
            resp_headers = {}
            self._apply_cors(resp_headers, origin_header)
            return 204, resp_headers, b""

        # 3. Resolve active origin target
        route = self.resolve_active_target(force_refresh=force_refresh)

        # 4. Safe Mode / Standby Write Fencing
        is_write = method.upper() in ("POST", "PUT", "DELETE", "PATCH")
        if is_write and not route["writable"]:
            err_envelope = {
                "ok": False,
                "error": {
                    "code": "CLUSTER_MAINTENANCE",
                    "message": f"Protected write rejected: Cluster is in {route['role'] or 'SAFE_MODE'}. No active writable primary is elected."
                },
                "node_id": "edge-router",
                "epoch": 0
            }
            resp_headers = {"Content-Type": "application/json; charset=utf-8"}
            self._apply_cors(resp_headers, origin_header)
            return 503, resp_headers, json.dumps(err_envelope).encode("utf-8")

        # 5. Total Cluster Failure (All nodes unreachable)
        if not route["target_origin"]:
            err_envelope = {
                "ok": False,
                "error": {
                    "code": "SERVICE_UNAVAILABLE",
                    "message": "Disaster Recovery Alert: All cluster origin nodes are currently unreachable."
                },
                "node_id": "edge-router",
                "epoch": 0
            }
            resp_headers = {"Content-Type": "application/json; charset=utf-8"}
            self._apply_cors(resp_headers, origin_header)
            return 503, resp_headers, json.dumps(err_envelope).encode("utf-8")

        # 6. Proxy Request to Selected Origin
        target_url = f"{route['target_origin']}{path}"
        fwd_headers = dict(headers)
        fwd_headers["Host"] = urllib.parse_origin_host(route["target_origin"])
        fwd_headers["X-Forwarded-Host"] = "portfolio.sentineldr.in"
        fwd_headers["X-SDR-Routed-To"] = route["active_node"] or "unknown"

        req = urllib.request.Request(
            target_url,
            data=body if is_write else None,
            headers=fwd_headers,
            method=method.upper()
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_status = resp.status
                resp_headers = {k: v for k, v in resp.headers.items()}
                resp_body = resp.read()
                self._apply_cors(resp_headers, origin_header)
                resp_headers["X-SDR-Edge-Router"] = "SentinelDR-v1"
                resp_headers["X-SDR-Target-Node"] = route["active_node"] or "unknown"
                return resp_status, resp_headers, resp_body
        except urllib.error.HTTPError as e:
            resp_headers = {k: v for k, v in e.headers.items()}
            self._apply_cors(resp_headers, origin_header)
            return e.code, resp_headers, e.read()
        except Exception as e:
            self._cached_route = None
            err_envelope = {
                "ok": False,
                "error": {
                    "code": "BAD_GATEWAY",
                    "message": f"Failed to communicate with active origin ({route['active_node']}): {str(e)}"
                },
                "node_id": "edge-router",
                "epoch": 0
            }
            resp_headers = {"Content-Type": "application/json; charset=utf-8"}
            self._apply_cors(resp_headers, origin_header)
            return 502, resp_headers, json.dumps(err_envelope).encode("utf-8")

    def _apply_cors(self, headers: Dict[str, str], origin: Optional[str]):
        if origin and origin in APPROVED_ORIGINS:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            headers["Access-Control-Allow-Headers"] = "Content-Type, Accept, X-SDR-Node, X-SDR-Epoch"


def _parse_origin_host(url: str) -> str:
    if "://" in url:
        return url.split("://")[1].split("/")[0]
    return url.split("/")[0]


urllib.parse_origin_host = _parse_origin_host
