"""
SentinelDR Phone Node - Base HTTP Server & Peer Replication
Standard library only: http.server.
Strictly zero third-party dependencies (no FastAPI, Pydantic, psycopg, etc.).
Port: 8001
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

# Ensure repository root is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from phone.db import PhoneDatabase
from shared.api_contract import (
    ALLOWED_ORIGINS,
    ROUTE_ACTIVE_ORIGIN,
    ROUTE_DASHBOARD_EVENTS,
    ROUTE_DASHBOARD_STATUS,
    ROUTE_EVENTS,
    ROUTE_HEALTH,
    ROUTE_READY,
    ROUTE_METRICS,
    ROUTE_PEER_CHANGES,
    ROUTE_PEER_FAILBACK,
    ROUTE_PEER_FAILOVER,
    ROUTE_PEER_HEARTBEAT,
    ROUTE_PEER_LEASE_REQUEST,
    ROUTE_PEER_RECOVERY_COMPLETE,
    ROUTE_PEER_RECOVERY_START,
    ROUTE_PEER_REPLICATE,
    ROUTE_STATUS,
    STATE_FAILBACK_PENDING,
    STATE_PRIMARY_ACTIVE,
    STATE_SECONDARY_ACTIVE,
    STATE_SECONDARY_STANDBY,
)
from shared.config import NodeConfig
from shared.failover import FailoverCoordinator
from shared.heartbeat import HeartbeatTracker, validate_heartbeat_payload
from shared.logger import setup_logger
from shared.ownership import (
    OwnershipRecord,
    sign_ownership_record,
    validate_lease,
)
from shared.protocol import (
    ERR_BAD_REQUEST,
    ERR_CONFLICT,
    ERR_FORBIDDEN,
    ERR_METHOD_NOT_ALLOWED,
    ERR_NOT_FOUND,
    ERR_UNAUTHORIZED,
    make_error,
    make_success,
    serialize_envelope,
)
from shared.replication import MAX_BODY_BYTES, validate_batch_request
from shared.security import (
    PersistentNonceCache,
    sanitize_for_audit_stream,
    verify_admin_key,
    verify_peer_request,
)
from shared.state_machine import ClusterStateMachine
from shared.discovery import PhoneBeaconBroadcaster

PORTFOLIO_HTML_PATH = os.path.join(BASE_DIR, "frontend", "portfolio.html")
DASHBOARD_HTML_PATH = os.path.join(BASE_DIR, "frontend", "dashboard.html")



class PhoneRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for Phone Node using Python standard library."""

    server_start_time: float = time.time()
    request_counter: int = 0

    @property
    def config(self) -> NodeConfig:
        return self.server.config  # type: ignore

    @property
    def db(self) -> PhoneDatabase:
        return self.server.db  # type: ignore

    @property
    def nonce_cache(self) -> PersistentNonceCache:
        return self.server.nonce_cache  # type: ignore

    @property
    def heartbeat_tracker(self) -> HeartbeatTracker:
        return self.server.heartbeat_tracker  # type: ignore

    @property
    def state_machine(self) -> ClusterStateMachine:
        return self.server.state_machine  # type: ignore

    @property
    def failover_coordinator(self) -> FailoverCoordinator:
        return self.server.failover_coordinator  # type: ignore

    @property
    def logger(self):
        return self.server.logger  # type: ignore

    def log_message(self, format, *args):
        # Suppress default stdlib stderr logging
        pass

    def _apply_cors_headers(self):
        """Apply restricted CORS headers only to approved frontend origins."""
        origin = self.headers.get("Origin")
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept, X-SDR-Node, X-SDR-Epoch")

    def send_envelope_response(self, status_code: int, envelope: dict):
        """Send standard SentinelDR envelope response."""
        body = serialize_envelope(envelope)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-SDR-Node", self.config.node_id)
        self.send_header("X-SDR-Epoch", str(self.config.epoch))
        self._apply_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_html_response(self, html_content: bytes):
        """Serve raw HTML."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_content)))
        self.send_header("X-SDR-Node", self.config.node_id)
        self.send_header("X-SDR-Epoch", str(self.config.epoch))
        self._apply_cors_headers()
        self.end_headers()
        self.wfile.write(html_content)

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        PhoneRequestHandler.request_counter += 1
        origin = self.headers.get("Origin")
        if origin and origin in ALLOWED_ORIGINS:
            self.send_response(204)
            self._apply_cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_GET(self):
        PhoneRequestHandler.request_counter += 1
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        # 1. Root / Portfolio HTML & Dashboard
        if path in ("/", "/index.html", "/portfolio.html"):
            self.handle_serve_portfolio()
            return
        elif path in ("/dashboard", "/dashboard.html"):
            self.handle_serve_dashboard()
            return

        # 2. Base API & Dashboard Telemetry
        if path == ROUTE_HEALTH:
            self.handle_health()
        elif path == ROUTE_READY:
            self.handle_ready()
        elif path == ROUTE_STATUS:
            self.handle_status()
        elif path == ROUTE_METRICS:
            self.handle_metrics()
        elif path == ROUTE_EVENTS:
            self.handle_events()
        elif path == ROUTE_DASHBOARD_STATUS:
            self.handle_dashboard_status()
        elif path == ROUTE_DASHBOARD_EVENTS:
            self.handle_dashboard_events()
        elif path == ROUTE_ACTIVE_ORIGIN:
            self.handle_active_origin()

        # 3. Peer Endpoints
        elif path == "/api/v1/peer/snapshot":
            self.handle_peer_snapshot()
        elif path in (ROUTE_PEER_CHANGES, "/api/v1/peer/changes"):
            self.handle_peer_changes()
        elif path == "/api/v1/peer/hash":
            self.handle_peer_hash()

        # 4. Portfolio Read APIs
        elif path in ("/api/v1/portfolio/profile", "/api/v1/profile"):
            self.handle_get_profile()
        elif path in ("/api/v1/portfolio/skills", "/api/v1/skills"):
            self.handle_get_skills()
        elif path in ("/api/v1/portfolio/projects", "/api/v1/projects"):
            self.handle_get_projects()
        elif path in ("/api/v1/portfolio/experience", "/api/v1/experience"):
            self.handle_get_experience()
        elif path in ("/api/v1/portfolio/education", "/api/v1/education"):
            self.handle_get_education()
        elif path in ("/api/v1/portfolio/certifications", "/api/v1/certifications"):
            self.handle_get_certifications()
        elif path in ("/api/v1/portfolio/contact", "/api/v1/contact"):
            self.handle_get_contact()
        elif path in ("/api/v1/portfolio/inquiries", "/api/v1/inquiries"):
            self.handle_get_inquiries()

        # 5. Unsupported Features
        elif path == "/ws":
            self.handle_unsupported_websocket()
        else:
            err = make_error(
                code=ERR_NOT_FOUND,
                message=f"Path not found: {path}",
                node_id=self.config.node_id,
                epoch=self.config.epoch
            )
            self.send_envelope_response(404, err)

    def do_POST(self):
        PhoneRequestHandler.request_counter += 1
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        # 1. Peer Endpoints
        if path == ROUTE_PEER_HEARTBEAT:
            self.handle_peer_heartbeat()
        elif path == ROUTE_PEER_REPLICATE:
            self.handle_peer_replicate()
        elif path == ROUTE_PEER_LEASE_REQUEST:
            self.handle_peer_lease_request()
        elif path in (ROUTE_PEER_FAILOVER, "/api/v1/peer/failover"):
            self.handle_peer_failover()
        elif path in (ROUTE_PEER_RECOVERY_START, "/api/v1/peer/recovery/start"):
            self.handle_peer_recovery_start()
        elif path in (ROUTE_PEER_RECOVERY_COMPLETE, "/api/v1/peer/recovery/complete"):
            self.handle_peer_recovery_complete()
        elif path in (ROUTE_PEER_FAILBACK, "/api/v1/peer/failback"):
            self.handle_peer_failback()

        # 2. Protected Portfolio Inquiries
        elif path in ("/api/v1/portfolio/contact", "/api/v1/portfolio/inquiry", "/api/v1/contact"):
            self.handle_post_inquiry()

        # 3. Unsupported Uploads
        elif path in ("/api/v1/portfolio/upload", "/api/v1/upload"):
            self.handle_unsupported_upload()
        else:
            err = make_error(
                code=ERR_METHOD_NOT_ALLOWED,
                message=f"Method POST not allowed on {path}",
                node_id=self.config.node_id,
                epoch=self.config.epoch
            )
            self.send_envelope_response(405, err)

    # --- Base Handlers ---

    def handle_serve_portfolio(self):
        if not os.path.exists(PORTFOLIO_HTML_PATH):
            err = make_error(code=ERR_NOT_FOUND, message="portfolio.html not found on server", node_id=self.config.node_id, epoch=self.config.epoch)
            self.send_envelope_response(404, err)
            return
        with open(PORTFOLIO_HTML_PATH, "rb") as f:
            content = f.read()
        self.send_html_response(content)

    def handle_serve_dashboard(self):
        if not os.path.exists(DASHBOARD_HTML_PATH):
            err = make_error(code=ERR_NOT_FOUND, message="dashboard.html not found on server", node_id=self.config.node_id, epoch=self.config.epoch)
            self.send_envelope_response(404, err)
            return
        with open(DASHBOARD_HTML_PATH, "rb") as f:
            content = f.read()
        self.send_html_response(content)

    def handle_health(self):
        db_ready, _ = self.db.is_healthy()
        data = {
            "status": "HEALTHY" if db_ready else "DEGRADED",
            "db_ready": db_ready,
            "node_id": self.config.node_id,
            "version": "1.0.0"
        }
        status_code = 200 if db_ready else 503
        resp = make_success(data=data, node_id=self.config.node_id, epoch=self.config.epoch)
        self.send_envelope_response(status_code, resp)

    def handle_ready(self):
        """
        GET /ready
        Readiness probe: Returns 200 OK only if database is connected,
        SQLite integrity is operational, and node is ready to process traffic.
        """
        db_ready, err = self.db.is_healthy()
        is_ready = bool(db_ready)
        data = {
            "ready": is_ready,
            "status": "READY" if is_ready else "NOT_READY",
            "db_healthy": db_ready,
            "role": self.state_machine.current_state,
            "epoch": self.state_machine.current_epoch,
            "node_id": self.config.node_id,
            "details": err if not is_ready else "Node is initialized and ready",
        }
        status_code = 200 if is_ready else 503
        resp = make_success(data=data, node_id=self.config.node_id, epoch=self.state_machine.current_epoch)
        self.send_envelope_response(status_code, resp)


    def handle_status(self):
        if self.state_machine.current_state == "SECONDARY_STANDBY":
            self.failover_coordinator.evaluate_heartbeat_timeout()
        db_ready, _ = self.db.is_healthy()
        uptime = time.time() - PhoneRequestHandler.server_start_time
        hb_status = self.heartbeat_tracker.get_status()
        now = time.time()
        ownership = self.db.get_ownership(self.config.cluster_id)
        valid, _ = validate_lease(
            record=ownership,
            node_id=self.config.node_id,
            expected_epoch=self.state_machine.current_epoch,
            expected_cluster_id=self.config.cluster_id,
            secret=self.config.hmac_secret,
            now=now,
            max_clock_skew=1.0
        )
        remaining = max(0.0, round(ownership.lease_expires_at - now, 2)) if ownership else 0.0

        data = {
            "cluster_id": self.config.cluster_id,
            "node_id": self.config.node_id,
            "node_type": "phone",
            "role": self.state_machine.current_state,
            "epoch": self.state_machine.current_epoch,
            "db_ready": db_ready,
            "uptime_seconds": round(uptime, 2),
            "heartbeat": hb_status,
            "lease": {
                "valid": valid,
                "owner": ownership.owner_node_id if ownership else "none",
                "expires_at": ownership.lease_expires_at if ownership else 0.0,
                "remaining_seconds": remaining,
                "granted_by": ownership.granted_by if ownership else "none"
            },
            "split_brain_protection": {
                "mechanism": "INDEPENDENT_WITNESS_QUORUM",
                "witness_url": self.config.witness_url,
                "max_clock_skew_seconds": self.config.max_clock_skew,
                "fail_closed_mode": "SAFE_MODE_ENABLED"
            }
        }
        resp = make_success(data=data, node_id=self.config.node_id, epoch=self.state_machine.current_epoch)
        self.send_envelope_response(200, resp)

    def handle_metrics(self):
        uptime = time.time() - PhoneRequestHandler.server_start_time
        db_ready, _ = self.db.is_healthy()
        checkpoint = self.db.get_replication_checkpoint("laptop")
        hb_status = self.heartbeat_tracker.get_status()
        data = {
            "uptime_seconds": round(uptime, 2),
            "requests_total": PhoneRequestHandler.request_counter,
            "db_healthy": db_ready,
            "last_applied_sequence": checkpoint["last_applied_sequence"],
            "heartbeat_misses": hb_status["consecutive_misses"],
            "suspected_offline": hb_status["suspected_offline"],
            "audit_events_count": len(self.db.get_recent_audit_events(limit=100))
        }
        resp = make_success(data=data, node_id=self.config.node_id, epoch=self.config.epoch)
        self.send_envelope_response(200, resp)

    def handle_events(self):
        headers_dict = {k: v for k, v in self.headers.items()}
        is_admin = verify_admin_key(headers_dict, self.config.admin_key)
        is_peer = False
        err_code = ERR_UNAUTHORIZED

        if not is_admin:
            is_valid, err, _ = verify_peer_request(
                headers=headers_dict,
                method="GET",
                path=urlparse(self.path).path,
                body=b"",
                secret=self.config.hmac_secret,
                nonce_cache=self.nonce_cache,
                window_seconds=self.config.timestamp_window_seconds
            )
            if is_valid:
                is_peer = True
            else:
                err_code = err or ERR_UNAUTHORIZED

        if not (is_admin or is_peer):
            err_resp = make_error(code=err_code, message=f"Authentication failed: {err_code}", node_id=self.config.node_id, epoch=self.config.epoch)
            self.send_envelope_response(401, err_resp)
            return

        events = self.db.get_recent_audit_events(limit=50)
        resp = make_success(data={"events": events, "count": len(events)}, node_id=self.config.node_id, epoch=self.config.epoch)
        self.send_envelope_response(200, resp)

    def handle_dashboard_status(self):
        """GET /api/v1/dashboard/status - Unprivileged operational status telemetry for dashboard."""
        db_ready, _ = self.db.is_healthy()
        uptime = time.time() - PhoneRequestHandler.server_start_time
        now = time.time()
        ownership = self.db.get_ownership(self.config.cluster_id)

        # Ownership safety
        if ownership:
            valid, lease_err = validate_lease(
                record=ownership,
                node_id=ownership.owner_node_id,
                expected_epoch=ownership.epoch,
                expected_cluster_id=self.config.cluster_id,
                secret=self.config.hmac_secret,
                now=now,
                max_clock_skew=self.config.max_clock_skew,
                witness_secret=self.config.witness_secret,
            )
            remaining = max(0.0, round(ownership.lease_expires_at - now, 2))
            if self.state_machine.current_state == "SAFE_MODE":
                safety_status = "SAFE_MODE_FENCED"
            elif valid and remaining > 0:
                safety_status = "VALID"
            elif remaining == 0:
                safety_status = "EXPIRED"
            else:
                safety_status = f"INVALID: {lease_err}"

            ownership_data = {
                "owner_node_id": ownership.owner_node_id,
                "epoch": ownership.epoch,
                "safety_status": safety_status,
                "remaining_seconds": remaining,
                "granted_by": ownership.granted_by,
            }
        else:
            ownership_data = {
                "owner_node_id": "none",
                "epoch": 0,
                "safety_status": "NO_LEASE",
                "remaining_seconds": 0.0,
                "granted_by": "none",
            }

        # Heartbeat
        hb_status = self.heartbeat_tracker.get_status()
        hb_data = {
            "elapsed_seconds": hb_status.get("elapsed_seconds"),
            "consecutive_misses": hb_status.get("consecutive_misses", 0),
            "suspected_offline": hb_status.get("suspected_offline", False),
        }

        # Replication
        laptop_applied_checkpoint = self.db.get_replication_checkpoint("ack_laptop")
        phone_applied_checkpoint = self.db.get_replication_checkpoint("laptop")
        highest_local = self.db.get_highest_local_sequence(self.config.node_id)
        laptop_applied_seq = laptop_applied_checkpoint.get("last_applied_sequence", 0)
        pending_outbox = len(self.db.get_unreplicated_changes("laptop", limit=1000))
        rep_data = {
            "highest_local_sequence": highest_local,
            "peer_applied_sequence": phone_applied_checkpoint.get("last_applied_sequence", 0),
            "lag": max(0, highest_local - laptop_applied_seq),
            "pending_outbox_count": pending_outbox,
        }

        # Recovery & Integrity
        conflicts = self.db.get_conflicts(resolved=False)
        rec_data = {
            "phase": self.state_machine.current_state,
            "unresolved_conflicts": len(conflicts),
            "integrity_status": "PRAGMA_OK" if db_ready else "DEGRADED",
        }

        # Direct Peer API Connectivity
        if hb_status.get("suspected_offline"):
            peer_api_reachability = "OFFLINE"
        elif hb_status.get("elapsed_seconds") is not None and hb_status["elapsed_seconds"] <= 10.0:
            peer_api_reachability = "ONLINE"
        else:
            peer_api_reachability = "STANDBY"

        conn_data = {
            "peer_api_reachability": peer_api_reachability,
        }

        data = {
            "cluster_id": self.config.cluster_id,
            "node_id": self.config.node_id,
            "node_type": "phone",
            "role": self.state_machine.current_state,
            "epoch": self.state_machine.current_epoch,
            "db_ready": db_ready,
            "db_healthy": db_ready,
            "uptime_seconds": round(uptime, 2),
            "ownership": ownership_data,
            "heartbeat": hb_data,
            "replication": rep_data,
            "recovery": rec_data,
            "connectivity": conn_data,
        }
        resp = make_success(data=data, node_id=self.config.node_id, epoch=self.state_machine.current_epoch)
        self.send_envelope_response(200, resp)

    def handle_dashboard_events(self):
        """GET /api/v1/dashboard/events - Public sanitized audit stream for dashboard."""
        raw_events = self.db.get_recent_audit_events(limit=50)
        secrets_to_redact = [
            self.config.hmac_secret,
            self.config.admin_key,
            self.config.witness_secret,
        ]
        sanitized_events = []
        for ev in raw_events:
            sanitized = {
                "event_id": ev.get("event_id"),
                "timestamp": ev.get("timestamp"),
                "node_id": ev.get("node_id"),
                "epoch": ev.get("epoch"),
                "event_type": ev.get("event_type"),
                "severity": ev.get("severity", "INFO"),
                "details": sanitize_for_audit_stream(ev.get("details"), secrets_to_redact),
            }
            sanitized_events.append(sanitized)
        resp = make_success(
            data={"events": sanitized_events, "count": len(sanitized_events)},
            node_id=self.config.node_id,
            epoch=self.state_machine.current_epoch,
        )
        self.send_envelope_response(200, resp)

    def handle_active_origin(self):
        """
        GET /api/v1/active-origin
        Narrowly scoped active-origin status endpoint for Cloudflare edge routing.
        Exposes role, state, epoch, and lease validity without secrets.
        """
        db_ready, _ = self.db.is_healthy()
        now = time.time()
        ownership = self.db.get_ownership(self.config.cluster_id)
        valid = False
        remaining = 0.0
        if ownership:
            valid, _ = validate_lease(
                record=ownership,
                node_id=ownership.owner_node_id,
                expected_epoch=ownership.epoch,
                expected_cluster_id=self.config.cluster_id,
                secret=self.config.hmac_secret,
                now=now,
                max_clock_skew=self.config.max_clock_skew,
                witness_secret=self.config.witness_secret,
            )
            remaining = max(0.0, round(ownership.lease_expires_at - now, 2))

        is_owner = bool(ownership and ownership.owner_node_id == self.config.node_id)
        is_writable = bool(self.state_machine.is_writable() and valid and remaining > 0 and is_owner and db_ready)

        data = {
            "cluster_id": self.config.cluster_id,
            "node_id": self.config.node_id,
            "node_type": "phone",
            "role": self.state_machine.current_state,
            "epoch": self.state_machine.current_epoch,
            "writable": is_writable,
            "lease_valid": valid and remaining > 0,
            "lease_remaining_seconds": remaining,
            "owner_node_id": ownership.owner_node_id if ownership else "none",
            "db_healthy": db_ready,
        }
        resp = make_success(data=data, node_id=self.config.node_id, epoch=self.state_machine.current_epoch)
        self.send_envelope_response(200, resp)


    # --- Peer Endpoints ---

    def handle_peer_heartbeat(self):
        """POST /api/v1/peer/heartbeat - Strongly authenticated peer heartbeat."""
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""

        headers_dict = {k: v for k, v in self.headers.items()}
        is_valid, err_code, caller_meta = verify_peer_request(
            headers=headers_dict,
            method="POST",
            path=ROUTE_PEER_HEARTBEAT,
            body=body_bytes,
            secret=self.config.hmac_secret,
            nonce_cache=self.nonce_cache,
            window_seconds=self.config.timestamp_window_seconds
        )
        if not is_valid:
            self.send_envelope_response(401, make_error(err_code or ERR_UNAUTHORIZED, f"Heartbeat authentication failed: {err_code}", self.config.node_id, self.config.epoch))
            return

        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            self.send_envelope_response(400, make_error(ERR_BAD_REQUEST, "Malformed JSON heartbeat payload", self.config.node_id, self.config.epoch))
            return

        valid, val_err = validate_heartbeat_payload(payload)
        if not valid:
            self.send_envelope_response(400, make_error(ERR_BAD_REQUEST, val_err or "Invalid heartbeat structure", self.config.node_id, self.config.epoch))
            return

        # Record with receiver's OWN clock
        received_at = self.heartbeat_tracker.record_heartbeat(payload)
        peer_node_id = payload["sender_node_id"]
        checkpoint = self.db.get_replication_checkpoint(peer_node_id)
        highest_applied = checkpoint["last_applied_sequence"]

        data = {
            "status": "ACK",
            "receiver_node_id": self.config.node_id,
            "receiver_epoch": self.config.epoch,
            "highest_applied_sequence": highest_applied,
            "received_at": received_at
        }
        self.send_envelope_response(200, make_success(data, self.config.node_id, self.config.epoch))

    def handle_peer_replicate(self):
        """POST /api/v1/peer/replicate - Bounded, ordered, transactional replication batch."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > MAX_BODY_BYTES:
            # Drain socket buffer up to content_length (capped at 10MB) to prevent TCP RST on Windows
            try:
                drain_bytes = min(content_length, 10 * 1024 * 1024)
                while drain_bytes > 0:
                    chunk = self.rfile.read(min(drain_bytes, 65536))
                    if not chunk:
                        break
                    drain_bytes -= len(chunk)
            except Exception:
                pass
            self.close_connection = True
            self.send_envelope_response(413, make_error("PAYLOAD_TOO_LARGE", f"Batch exceeds {MAX_BODY_BYTES} bytes", self.config.node_id, self.config.epoch))
            return

        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        headers_dict = {k: v for k, v in self.headers.items()}

        is_valid, err_code, caller_meta = verify_peer_request(
            headers=headers_dict,
            method="POST",
            path=ROUTE_PEER_REPLICATE,
            body=body_bytes,
            secret=self.config.hmac_secret,
            nonce_cache=self.nonce_cache,
            window_seconds=self.config.timestamp_window_seconds
        )
        if not is_valid:
            self.send_envelope_response(401, make_error(err_code or ERR_UNAUTHORIZED, f"Replication authentication failed: {err_code}", self.config.node_id, self.config.epoch))
            return

        try:
            batch = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            self.send_envelope_response(400, make_error(ERR_BAD_REQUEST, "Malformed JSON replication batch", self.config.node_id, self.config.epoch))
            return

        valid, val_err = validate_batch_request(batch)
        if not valid:
            self.send_envelope_response(400, make_error(ERR_BAD_REQUEST, val_err or "Invalid batch format", self.config.node_id, self.config.epoch))
            return

        origin_node = caller_meta["node_id"] if caller_meta else "laptop"
        batch_id = batch["batch_id"]
        events = batch["events"]

        ok, last_seq, dups, missing, resync, err_detail = self.db.apply_replication_batch(
            origin_node_id=origin_node,
            batch_id=batch_id,
            events=events
        )

        resp_data = {
            "accepted": ok,
            "last_applied_sequence": last_seq,
            "duplicate_count": dups,
            "missing_sequences": missing,
            "requires_full_resync": resync
        }

        if not ok:
            status_code = 409 if missing else 500
            self.send_envelope_response(status_code, make_error(ERR_CONFLICT if missing else "APPLY_FAILED", err_detail or "Batch apply failed", self.config.node_id, self.config.epoch, details=resp_data))
            return

        self.send_envelope_response(200, make_success(resp_data, self.config.node_id, self.config.epoch))

    def handle_peer_snapshot(self):
        """GET /api/v1/peer/snapshot - Initial snapshot / full resync data."""
        headers_dict = {k: v for k, v in self.headers.items()}
        is_valid, err_code, _ = verify_peer_request(
            headers=headers_dict,
            method="GET",
            path="/api/v1/peer/snapshot",
            body=b"",
            secret=self.config.hmac_secret,
            nonce_cache=self.nonce_cache,
            window_seconds=self.config.timestamp_window_seconds
        )
        if not is_valid:
            self.send_envelope_response(401, make_error(err_code or ERR_UNAUTHORIZED, "Snapshot authentication failed", self.config.node_id, self.config.epoch))
            return

        snapshot = self.db.get_full_snapshot()
        self.send_envelope_response(200, make_success(snapshot, self.config.node_id, self.config.epoch))

    def handle_peer_lease_request(self):
        """POST /api/v1/peer/lease/request - Peer lease request with bounded clock-skew enforcement."""
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        headers_dict = {k: v for k, v in self.headers.items()}

        is_valid, err_code, caller_meta = verify_peer_request(
            headers=headers_dict,
            method="POST",
            path=ROUTE_PEER_LEASE_REQUEST,
            body=body_bytes,
            secret=self.config.hmac_secret,
            nonce_cache=self.nonce_cache,
            window_seconds=self.config.timestamp_window_seconds
        )
        if not is_valid:
            self.send_envelope_response(401, make_error(err_code or ERR_UNAUTHORIZED, f"Peer authentication failed: {err_code}", self.config.node_id, self.state_machine.current_epoch))
            return

        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            self.send_envelope_response(400, make_error(ERR_BAD_REQUEST, "Malformed JSON in lease request", self.config.node_id, self.state_machine.current_epoch))
            return

        # Bounded Clock Skew Policy
        sent_at = float(payload.get("sent_at", 0.0))
        now = time.time()
        skew = abs(now - sent_at)
        if skew > self.config.max_clock_skew:
            self.send_envelope_response(400, make_error("CLOCK_SKEW_EXCEEDED", f"Clock skew of {skew:.3f}s exceeds maximum threshold of {self.config.max_clock_skew}s", self.config.node_id, self.state_machine.current_epoch))
            return

        # Evaluate local ownership & state
        record = self.db.get_ownership(self.config.cluster_id)
        valid, _ = validate_lease(
            record=record,
            node_id=self.config.node_id,
            expected_epoch=self.state_machine.current_epoch,
            expected_cluster_id=self.config.cluster_id,
            secret=self.config.hmac_secret,
            now=now,
            max_clock_skew=1.0
        )

        if self.state_machine.current_state == STATE_PRIMARY_ACTIVE and valid and record:
            remaining = round(record.lease_expires_at - now, 2)
            data = {
                "status": "DENIED",
                "reason": "LOCAL_PRIMARY_ACTIVE_WITH_VALID_LEASE",
                "current_owner": self.config.node_id,
                "current_epoch": self.state_machine.current_epoch,
                "remaining_lease_seconds": remaining
            }
            self.send_envelope_response(409, make_error(ERR_CONFLICT, "Lease denied: active primary holds valid lease", self.config.node_id, self.state_machine.current_epoch, details=data))
            return

        # Yield ownership
        data = {
            "status": "YIELDED",
            "reason": "LOCAL_NODE_YIELDS_OWNERSHIP",
            "last_known_epoch": self.state_machine.current_epoch,
            "local_state": self.state_machine.current_state
        }
        self.send_envelope_response(200, make_success(data, self.config.node_id, self.state_machine.current_epoch))

    def handle_peer_failover(self):
        """POST /api/v1/peer/failover - Strongly authenticated failover promotion request."""
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        headers_dict = {k: v for k, v in self.headers.items()}

        is_admin = verify_admin_key(headers_dict, self.config.admin_key)
        is_peer = False
        err_code = ERR_UNAUTHORIZED

        if not is_admin:
            is_valid, err, _ = verify_peer_request(
                headers=headers_dict,
                method="POST",
                path=ROUTE_PEER_FAILOVER,
                body=body_bytes,
                secret=self.config.hmac_secret,
                nonce_cache=self.nonce_cache,
                window_seconds=self.config.timestamp_window_seconds
            )
            if is_valid:
                is_peer = True
            else:
                err_code = err or ERR_UNAUTHORIZED

        if not (is_admin or is_peer):
            self.send_envelope_response(
                401,
                make_error(err_code, f"Failover authentication failed: {err_code}", self.config.node_id, self.state_machine.current_epoch)
            )
            return

        reason = "Failover initiated via authenticated API"
        force_admin = False
        if body_bytes:
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
                if isinstance(payload, dict):
                    reason = payload.get("reason", reason)
                    if "force_admin" in payload and is_admin:
                        force_admin = bool(payload["force_admin"])
            except Exception:
                pass

        ok, msg, lease_info = self.failover_coordinator.attempt_failover(reason=reason, force_admin=force_admin)
        if not ok:
            self.send_envelope_response(
                409,
                make_error("FAILOVER_REJECTED", msg, self.config.node_id, self.state_machine.current_epoch)
            )
            return

        self.send_envelope_response(
            200,
            make_success({
                "status": "PROMOTED",
                "message": msg,
                "role": self.state_machine.current_state,
                "epoch": self.state_machine.current_epoch,
                "lease": lease_info
            }, self.config.node_id, self.state_machine.current_epoch)
        )

    def handle_peer_changes(self):
        """GET /api/v1/peer/changes - Query unreplicated change events."""
        headers_dict = {k: v for k, v in self.headers.items()}
        is_admin = verify_admin_key(headers_dict, self.config.admin_key)
        is_peer = False
        err_code = ERR_UNAUTHORIZED

        if not is_admin:
            is_valid, err, _ = verify_peer_request(
                headers=headers_dict,
                method="GET",
                path=ROUTE_PEER_CHANGES,
                body=b"",
                secret=self.config.hmac_secret,
                nonce_cache=self.nonce_cache,
                window_seconds=self.config.timestamp_window_seconds
            )
            if is_valid:
                is_peer = True
            else:
                err_code = err or ERR_UNAUTHORIZED

        if not (is_admin or is_peer):
            self.send_envelope_response(401, make_error(err_code, f"Authentication failed: {err_code}", self.config.node_id, self.state_machine.current_epoch))
            return

        parsed = urlparse(self.path)
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        from_seq = int(qs.get("from_sequence", [0])[0])
        limit = min(int(qs.get("limit", [50])[0]), 100)

        events = self.db.get_unreplicated_changes(peer_node_id="laptop", from_sequence=from_seq, limit=limit)
        highest_seq = self.db.get_highest_local_sequence("phone")
        data = {
            "events": events,
            "count": len(events),
            "highest_sequence": highest_seq,
            "from_sequence": from_seq
        }
        self.send_envelope_response(200, make_success(data, self.config.node_id, self.state_machine.current_epoch))

    def handle_peer_hash(self):
        """GET /api/v1/peer/hash - Return canonical hash of specified entity table."""
        headers_dict = {k: v for k, v in self.headers.items()}
        is_admin = verify_admin_key(headers_dict, self.config.admin_key)
        is_peer = False
        err_code = ERR_UNAUTHORIZED

        if not is_admin:
            is_valid, err, _ = verify_peer_request(
                headers=headers_dict,
                method="GET",
                path="/api/v1/peer/hash",
                body=b"",
                secret=self.config.hmac_secret,
                nonce_cache=self.nonce_cache,
                window_seconds=self.config.timestamp_window_seconds
            )
            if is_valid:
                is_peer = True
            else:
                err_code = err or ERR_UNAUTHORIZED

        if not (is_admin or is_peer):
            self.send_envelope_response(401, make_error(err_code, f"Authentication failed: {err_code}", self.config.node_id, self.state_machine.current_epoch))
            return

        parsed = urlparse(self.path)
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        table = qs.get("table", ["portfolio_inquiries"])[0]

        h = self.db.get_canonical_hash(table)
        self.send_envelope_response(200, make_success({"table": table, "hash": h}, self.config.node_id, self.state_machine.current_epoch))

    def handle_peer_recovery_start(self):
        """POST /api/v1/peer/recovery/start - Acknowledge recovery start and capture consistent backup."""
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        headers_dict = {k: v for k, v in self.headers.items()}

        is_admin = verify_admin_key(headers_dict, self.config.admin_key)
        is_peer = False
        err_code = ERR_UNAUTHORIZED

        if not is_admin:
            is_valid, err, _ = verify_peer_request(
                headers=headers_dict,
                method="POST",
                path=ROUTE_PEER_RECOVERY_START,
                body=body_bytes,
                secret=self.config.hmac_secret,
                nonce_cache=self.nonce_cache,
                window_seconds=self.config.timestamp_window_seconds
            )
            if is_valid:
                is_peer = True
            else:
                err_code = err or ERR_UNAUTHORIZED

        if not (is_admin or is_peer):
            self.send_envelope_response(401, make_error(err_code, f"Authentication failed: {err_code}", self.config.node_id, self.state_machine.current_epoch))
            return

        backup_file = self.db.create_database_backup()
        checkpoint = self.db.get_replication_checkpoint("laptop")
        highest_seq = self.db.get_highest_local_sequence("phone")

        data = {
            "status": "ACK",
            "node_id": self.config.node_id,
            "role": self.state_machine.current_state,
            "epoch": self.state_machine.current_epoch,
            "backup_file": backup_file,
            "highest_sequence": highest_seq,
            "checkpoint": checkpoint
        }
        self.send_envelope_response(200, make_success(data, self.config.node_id, self.state_machine.current_epoch))

    def handle_peer_recovery_complete(self):
        """POST /api/v1/peer/recovery/complete - Recovery completion acknowledgment."""
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        headers_dict = {k: v for k, v in self.headers.items()}

        is_admin = verify_admin_key(headers_dict, self.config.admin_key)
        is_peer = False
        err_code = ERR_UNAUTHORIZED

        if not is_admin:
            is_valid, err, _ = verify_peer_request(
                headers=headers_dict,
                method="POST",
                path=ROUTE_PEER_RECOVERY_COMPLETE,
                body=body_bytes,
                secret=self.config.hmac_secret,
                nonce_cache=self.nonce_cache,
                window_seconds=self.config.timestamp_window_seconds
            )
            if is_valid:
                is_peer = True
            else:
                err_code = err or ERR_UNAUTHORIZED

        if not (is_admin or is_peer):
            self.send_envelope_response(401, make_error(err_code, f"Authentication failed: {err_code}", self.config.node_id, self.state_machine.current_epoch))
            return

        data = {
            "status": "ACK",
            "node_id": self.config.node_id,
            "role": self.state_machine.current_state,
            "epoch": self.state_machine.current_epoch
        }
        self.send_envelope_response(200, make_success(data, self.config.node_id, self.state_machine.current_epoch))

    def handle_peer_failback(self):
        """POST /api/v1/peer/failback - Controlled handoff step-down handler."""
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""
        headers_dict = {k: v for k, v in self.headers.items()}

        is_admin = verify_admin_key(headers_dict, self.config.admin_key)
        is_peer = False
        err_code = ERR_UNAUTHORIZED

        if not is_admin:
            is_valid, err, _ = verify_peer_request(
                headers=headers_dict,
                method="POST",
                path=ROUTE_PEER_FAILBACK,
                body=body_bytes,
                secret=self.config.hmac_secret,
                nonce_cache=self.nonce_cache,
                window_seconds=self.config.timestamp_window_seconds
            )
            if is_valid:
                is_peer = True
            else:
                err_code = err or ERR_UNAUTHORIZED

        if not (is_admin or is_peer):
            self.send_envelope_response(401, make_error(err_code, f"Failback authentication failed: {err_code}", self.config.node_id, self.state_machine.current_epoch))
            return

        payload = {}
        if body_bytes:
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                pass

        action = payload.get("action", "fence")
        if action == "fence":
            # Fence Phone writes: move to STATE_FAILBACK_PENDING
            ok, err = self.state_machine.transition_to(
                STATE_FAILBACK_PENDING,
                reason="Fenced by primary failback handoff"
            )
            data = {
                "status": "FENCED",
                "role": self.state_machine.current_state,
                "epoch": self.state_machine.current_epoch,
                "writable": self.state_machine.is_writable()
            }
            self.send_envelope_response(200, make_success(data, self.config.node_id, self.state_machine.current_epoch))
            return
        elif action == "finalize":
            new_lease_data = payload.get("new_lease")
            new_epoch = self.state_machine.current_epoch
            if new_lease_data:
                try:
                    new_lease = OwnershipRecord.from_dict(new_lease_data)
                    self.db.set_ownership(new_lease)
                    new_epoch = new_lease.epoch
                except Exception as e:
                    pass

            ok, err = self.state_machine.transition_to(
                STATE_SECONDARY_STANDBY,
                reason="Failback handoff complete, phone stepped down to standby",
                new_epoch=new_epoch
            )
            data = {
                "status": "STEPPED_DOWN",
                "role": self.state_machine.current_state,
                "epoch": self.state_machine.current_epoch,
                "writable": self.state_machine.is_writable()
            }
            self.send_envelope_response(200, make_success(data, self.config.node_id, self.state_machine.current_epoch))
            return
        else:
            self.send_envelope_response(400, make_error(ERR_BAD_REQUEST, f"Unknown failback action: {action}", self.config.node_id, self.state_machine.current_epoch))

    # --- Portfolio Read Handlers ---

    def handle_get_profile(self):
        profile = self.db.get_profile()
        if not profile:
            self.send_envelope_response(404, make_error(ERR_NOT_FOUND, "Profile not found", self.config.node_id, self.config.epoch))
            return
        self.send_envelope_response(200, make_success(profile, self.config.node_id, self.config.epoch))

    def handle_get_skills(self):
        skills = self.db.get_skills()
        self.send_envelope_response(200, make_success({"skills": skills, "count": len(skills)}, self.config.node_id, self.config.epoch))

    def handle_get_projects(self):
        projects = self.db.get_projects()
        self.send_envelope_response(200, make_success({"projects": projects, "count": len(projects)}, self.config.node_id, self.config.epoch))

    def handle_get_experience(self):
        experience = self.db.get_experience()
        self.send_envelope_response(200, make_success({"experience": experience, "count": len(experience)}, self.config.node_id, self.config.epoch))

    def handle_get_education(self):
        education = self.db.get_education()
        self.send_envelope_response(200, make_success({"education": education, "count": len(education)}, self.config.node_id, self.config.epoch))

    def handle_get_certifications(self):
        certifications = self.db.get_certifications()
        self.send_envelope_response(200, make_success({"certifications": certifications, "count": len(certifications)}, self.config.node_id, self.config.epoch))

    def handle_get_contact(self):
        contact = self.db.get_contact()
        if not contact:
            self.send_envelope_response(404, make_error(ERR_NOT_FOUND, "Contact details not found", self.config.node_id, self.config.epoch))
            return
        self.send_envelope_response(200, make_success(contact, self.config.node_id, self.config.epoch))

    def handle_get_inquiries(self):
        inquiries = self.db.get_inquiries()
        self.send_envelope_response(200, make_success({"inquiries": inquiries, "count": len(inquiries)}, self.config.node_id, self.config.epoch))

    # --- Portfolio Protected Write Handler ---

    def handle_post_inquiry(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self.send_envelope_response(400, make_error(ERR_BAD_REQUEST, "Missing request body", self.config.node_id, self.config.epoch))
            return

        body_bytes = self.rfile.read(content_length)
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            self.send_envelope_response(400, make_error(ERR_BAD_REQUEST, "Malformed JSON payload", self.config.node_id, self.config.epoch))
            return

        name = payload.get("name", "").strip()
        email = payload.get("email", "").strip()
        subject = payload.get("subject", "General Inquiry").strip()
        message = payload.get("message", "").strip()

        if not name or not email or not message:
            self.send_envelope_response(400, make_error(ERR_BAD_REQUEST, "Name, email, and message are required fields", self.config.node_id, self.state_machine.current_epoch))
            return

        is_primary = self.state_machine.is_writable()
        current_epoch = self.state_machine.current_epoch

        ok, err_code, err_msg, op_id = self.db.submit_inquiry(
            origin_node_id=self.config.node_id,
            origin_epoch=current_epoch,
            name=name,
            email=email,
            subject=subject,
            message=message,
            is_primary=is_primary,
            cluster_id=self.config.cluster_id,
            secret=self.config.hmac_secret
        )

        if not ok:
            status_code = 403 if err_code == "FORBIDDEN" else 500
            self.send_envelope_response(status_code, make_error(err_code or "WRITE_FAILED", err_msg or "Write rejected", self.config.node_id, current_epoch))
            return

        self.send_envelope_response(201, make_success({
            "operation_id": op_id,
            "status": "PERSISTED_IN_OUTBOX",
            "message": "Inquiry accepted and queued for replication"
        }, self.config.node_id, current_epoch))

    # --- Unsupported Feature Handlers ---

    def handle_unsupported_upload(self):
        err = make_error(
            code="FEATURE_UNSUPPORTED_DURING_FAILOVER",
            message="File uploads are strictly unsupported during failover and safe mode.",
            node_id=self.config.node_id,
            epoch=self.config.epoch
        )
        self.send_envelope_response(400, err)

    def handle_unsupported_websocket(self):
        err = make_error(
            code="FEATURE_UNSUPPORTED_DURING_FAILOVER",
            message="WebSockets are strictly unsupported during failover and safe mode.",
            node_id=self.config.node_id,
            epoch=self.config.epoch
        )
        self.send_envelope_response(400, err)


class PhoneServer(ThreadingHTTPServer):
    """Custom HTTPServer maintaining shared application context."""
    allow_reuse_address = True

    def __init__(self, config: NodeConfig):
        self.config = config
        self.logger = setup_logger("phone_server", node_id=config.node_id, epoch=config.epoch)
        self.db = PhoneDatabase(config.database_path)
        self.nonce_cache = PersistentNonceCache(config.nonce_cache_db)
        self.heartbeat_tracker = HeartbeatTracker()
        init_ownership = self.db.get_ownership(config.cluster_id)
        initial_epoch = init_ownership.epoch if init_ownership else config.epoch
        self.state_machine = ClusterStateMachine(
            initial_state=config.initial_role,
            node_id=config.node_id,
            initial_epoch=initial_epoch,
            audit_callback=self.db.log_audit_event
        )
        self.failover_coordinator = FailoverCoordinator(
            node_id=config.node_id,
            cluster_id=config.cluster_id,
            state_machine=self.state_machine,
            heartbeat_tracker=self.heartbeat_tracker,
            db=self.db,
            witness_url=config.witness_url,
            witness_secret=config.witness_secret,
            max_clock_skew=config.max_clock_skew,
        )

        import uuid
        self.db.log_audit_event(
            event_id=uuid.uuid4().hex,
            node_id=self.config.node_id,
            epoch=self.config.epoch,
            event_type="NODE_STARTED",
            severity="INFO",
            details={"port": self.config.port, "role": self.config.initial_role}
        )

        super().__init__((config.host, config.port), PhoneRequestHandler)
        self.config.port = self.server_port
        self._running = True
        self._beacon = PhoneBeaconBroadcaster(port=self.config.port, cluster_id=self.config.cluster_id)
        self._beacon.start()
        self._monitor_thread = threading.Thread(target=self._auto_failover_monitor, daemon=True)
        self._monitor_thread.start()

    def _auto_failover_monitor(self):
        """Continuously checks for missed heartbeats from Laptop and auto-promotes after 3 misses."""
        while getattr(self, "_running", True):
            time.sleep(1.0)
            try:
                if self.state_machine.current_state == STATE_SECONDARY_STANDBY:
                    if self.heartbeat_tracker.last_received_at is not None:
                        misses = self.heartbeat_tracker.evaluate_misses()
                        if misses >= 3:
                            self.failover_coordinator.evaluate_heartbeat_timeout()
                            if self.state_machine.current_state == STATE_SUSPECTED_OFFLINE:
                                print(f"[Phone Node] Missed {misses} consecutive heartbeats from Laptop! Initiating automatic failover...", flush=True)
                                ok, msg, _ = self.failover_coordinator.attempt_failover(
                                    reason=f"Automatic failover: {misses} missed heartbeats from Laptop"
                                )
                                if ok:
                                    print(f"[Phone Node] Promotion successful! Phone is now PRIMARY ACTIVE on port {self.config.port}.", flush=True)
                                else:
                                    print(f"[Phone Node] Failover attempt result: {msg}", flush=True)
            except Exception:
                pass

    def stop(self):
        """Cleanly shutdown the HTTP server."""
        self._running = False
        try:
            self._beacon.stop()
        except Exception:
            pass
        try:
            self.shutdown()
        except Exception:
            pass
        try:
            self.server_close()
        except Exception:
            pass


def create_phone_server(env_file: Optional[str] = None) -> PhoneServer:
    config = NodeConfig(node_type="phone", env_file=env_file)
    return PhoneServer(config)


def main():
    server = create_phone_server()
    print(f"Phone node listening on http://{server.config.host}:{server.config.port} (Role: {server.config.initial_role})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Phone node...")
        server.server_close()


if __name__ == "__main__":
    main()
