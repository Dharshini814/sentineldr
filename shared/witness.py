"""
SentinelDR - Independent Witness Service
Standard library only (runtime-neutral for Laptop & Phone).
Acts as an external 3rd-party quorum arbiter granting cryptographically signed,
time-bounded, monotonic epoch leases to prevent split-brain.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from shared.ownership import OwnershipRecord, sign_ownership_record
from shared.protocol import (
    ERR_CONFLICT,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    make_error,
    make_success,
    serialize_envelope,
)


class WitnessState:
    """In-memory durable state for the Independent Witness."""

    def __init__(self, cluster_id: str, witness_secret: str):
        self.cluster_id = cluster_id
        self.witness_secret = witness_secret
        self.current_epoch: int = 1
        self.current_lease: Optional[OwnershipRecord] = None
        self._lock = threading.RLock()

    def acquire_or_renew_lease(
        self,
        candidate_node_id: str,
        requested_epoch: int,
        duration_seconds: float = 15.0
    ) -> Tuple[bool, Optional[OwnershipRecord], Optional[str]]:
        """
        Evaluate and grant or deny a lease request.
        Guarantees:
        1. Never grants a lease to node B if node A's lease is still unexpired.
        2. Monotonically increments epoch on owner change.
        3. Signs the granted OwnershipRecord with the witness secret.
        """
        with self._lock:
            now = time.time()

            # Check if there is an unexpired lease held by another node
            if self.current_lease is not None:
                if self.current_lease.owner_node_id != candidate_node_id:
                    if now < self.current_lease.lease_expires_at:
                        remaining = round(self.current_lease.lease_expires_at - now, 2)
                        return (
                            False,
                            None,
                            f"LEASE_HELD_BY_ACTIVE_PRIMARY: Owner {self.current_lease.owner_node_id} holds lease for {remaining}s more"
                        )
                    # Lease has expired; owner change requires epoch increment
                    self.current_epoch = max(self.current_epoch + 1, requested_epoch)
                else:
                    # Same node renewing; maintain epoch unless requested higher
                    self.current_epoch = max(self.current_epoch, requested_epoch)
            else:
                self.current_epoch = max(self.current_epoch, requested_epoch)

            lease_id = uuid.uuid4().hex
            expires_at = now + duration_seconds
            signature = sign_ownership_record(
                cluster_id=self.cluster_id,
                owner_node_id=candidate_node_id,
                epoch=self.current_epoch,
                lease_id=lease_id,
                lease_expires_at=expires_at,
                granted_by="witness",
                secret=self.witness_secret
            )

            record = OwnershipRecord(
                cluster_id=self.cluster_id,
                owner_node_id=candidate_node_id,
                epoch=self.current_epoch,
                lease_id=lease_id,
                lease_expires_at=expires_at,
                granted_by="witness",
                signature=signature,
                updated_at=now
            )
            self.current_lease = record
            return True, record, None

    def release_lease(self, node_id: str, lease_id: str) -> Tuple[bool, Optional[str]]:
        """Voluntarily release active lease."""
        with self._lock:
            if self.current_lease is None:
                return True, None
            if self.current_lease.owner_node_id != node_id:
                return False, f"NODE_NOT_OWNER: {node_id} does not own lease"
            if self.current_lease.lease_id != lease_id:
                return False, f"LEASE_ID_MISMATCH: {lease_id} != {self.current_lease.lease_id}"

            self.current_lease = None
            return True, None

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic status of witness."""
        with self._lock:
            now = time.time()
            lease_active = False
            remaining = 0.0
            if self.current_lease:
                lease_active = now < self.current_lease.lease_expires_at
                remaining = max(0.0, round(self.current_lease.lease_expires_at - now, 2))

            return {
                "cluster_id": self.cluster_id,
                "current_epoch": self.current_epoch,
                "lease_active": lease_active,
                "remaining_seconds": remaining,
                "current_lease": self.current_lease.to_dict() if self.current_lease else None
            }


class WitnessRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Witness service using Python standard library."""

    @property
    def witness_state(self) -> WitnessState:
        return self.server.witness_state  # type: ignore

    def log_message(self, format, *args):
        pass  # Suppress default stdlib stderr logging

    def send_envelope_response(self, status_code: int, envelope: dict):
        body = serialize_envelope(envelope)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/api/v1/witness/status", "/health"):
            status_data = self.witness_state.get_status()
            resp = make_success(status_data, node_id="witness", epoch=self.witness_state.current_epoch)
            self.send_envelope_response(200, resp)
        else:
            self.send_envelope_response(404, make_error(ERR_NOT_FOUND, f"Path not found: {parsed.path}", "witness", 0))

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            payload = {}

        if parsed.path == "/api/v1/witness/lease/acquire":
            candidate = payload.get("candidate_node_id")
            epoch = payload.get("requested_epoch", 1)
            duration = float(payload.get("duration_seconds", 15.0))
            if not candidate:
                self.send_envelope_response(400, make_error("INVALID_REQUEST", "Missing candidate_node_id", "witness", self.witness_state.current_epoch))
                return

            ok, record, err = self.witness_state.acquire_or_renew_lease(
                candidate_node_id=candidate,
                requested_epoch=epoch,
                duration_seconds=duration
            )
            if ok and record:
                self.send_envelope_response(200, make_success(record.to_dict(), "witness", record.epoch))
            else:
                self.send_envelope_response(409, make_error(ERR_CONFLICT, err or "Lease acquisition denied", "witness", self.witness_state.current_epoch))

        elif parsed.path == "/api/v1/witness/lease/release":
            node_id = payload.get("owner_node_id")
            lease_id = payload.get("lease_id")
            ok, err = self.witness_state.release_lease(node_id, lease_id)
            if ok:
                self.send_envelope_response(200, make_success({"released": True}, "witness", self.witness_state.current_epoch))
            else:
                self.send_envelope_response(403, make_error(ERR_FORBIDDEN, err or "Release failed", "witness", self.witness_state.current_epoch))
        else:
            self.send_envelope_response(404, make_error(ERR_NOT_FOUND, f"Path not found: {parsed.path}", "witness", 0))


class WitnessServer(HTTPServer):
    """Standalone HTTP server for Witness service."""
    allow_reuse_address = True

    def __init__(self, host: str, port: int, cluster_id: str, witness_secret: str):
        self.witness_state = WitnessState(cluster_id=cluster_id, witness_secret=witness_secret)
        super().__init__((host, port), WitnessRequestHandler)
        self.port = self.server_port

    def stop(self):
        try:
            self.shutdown()
        except Exception:
            pass
        try:
            self.server_close()
        except Exception:
            pass


class WitnessClient:
    """Standard library client for interacting with the Independent Witness."""

    def __init__(self, timeout: float = 3.0):
        self.timeout = timeout

    def acquire_lease(
        self,
        witness_url: str,
        cluster_id: str,
        candidate_node_id: str,
        requested_epoch: int,
        duration_seconds: float = 15.0
    ) -> Tuple[bool, Optional[OwnershipRecord], Optional[str]]:
        """Request a write lease from the witness."""
        url = f"{witness_url.rstrip('/')}/api/v1/witness/lease/acquire"
        body = json.dumps({
            "cluster_id": cluster_id,
            "candidate_node_id": candidate_node_id,
            "requested_epoch": requested_epoch,
            "duration_seconds": duration_seconds
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok") and data.get("data"):
                    record = OwnershipRecord.from_dict(data["data"])
                    return True, record, None
                return False, None, "Witness response missing data"
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode("utf-8"))
                err_msg = err_data.get("error", {}).get("message", f"HTTP {e.code}")
            except Exception:
                err_msg = f"HTTP {e.code}"
            return False, None, err_msg
        except Exception as e:
            return False, None, f"Witness connection error: {str(e)}"

    def release_lease(
        self,
        witness_url: str,
        cluster_id: str,
        owner_node_id: str,
        lease_id: str
    ) -> Tuple[bool, Optional[str]]:
        """Voluntarily release write lease."""
        url = f"{witness_url.rstrip('/')}/api/v1/witness/lease/release"
        body = json.dumps({
            "cluster_id": cluster_id,
            "owner_node_id": owner_node_id,
            "lease_id": lease_id
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("ok", False), None
        except Exception as e:
            return False, str(e)


def main():
    """CLI entry point for running standalone Witness Quorum service."""
    import argparse
    parser = argparse.ArgumentParser(description="SentinelDR Independent Witness Quorum Service")
    parser.add_argument("--host", default=os.getenv("SDR_WITNESS_HOST", "0.0.0.0"), help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("SDR_WITNESS_PORT", "8002")), help="Bind port (default: 8002)")
    parser.add_argument("--cluster-id", default=os.getenv("SDR_CLUSTER_ID", "sentineldr-cluster-01"), help="Cluster ID")
    parser.add_argument("--secret", default=os.getenv("SDR_WITNESS_SECRET", "sentineldr-witness-secret-change-in-prod"), help="Witness Secret")
    args = parser.parse_args()

    server = WitnessServer(args.host, args.port, args.cluster_id, args.secret)
    print(f"[SentinelDR Witness] Listening on http://{args.host}:{args.port} for cluster '{args.cluster_id}'...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[SentinelDR Witness] Stopping...")
        server.stop()


if __name__ == "__main__":
    main()
