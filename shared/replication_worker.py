"""
SentinelDR - Replication & Heartbeat Network Client
Standard library only (runtime-neutral for Laptop & Phone).
"""

import json
import random
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

from shared.heartbeat import build_heartbeat_payload
from shared.replication import MAX_BATCH_SIZE, make_replication_response
from shared.security import build_peer_headers


class ReplicationClient:
    """Client for peer-to-peer replication and heartbeats using standard library urllib."""

    def __init__(self, secret: str, timeout: float = 4.0):
        self.secret = secret
        self.timeout = timeout

    def send_heartbeat(
        self,
        peer_url: str,
        sender_node_id: str,
        sender_state: str,
        epoch: int,
        lease_id: str,
        last_committed_sequence: int,
        database_health: str = "HEALTHY"
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """Send strongly-authenticated HMAC heartbeat to peer."""
        path = "/api/v1/peer/heartbeat"
        url = f"{peer_url.rstrip('/')}{path}"
        payload = build_heartbeat_payload(
            cluster_id="sentineldr-cluster-01",
            sender_node_id=sender_node_id,
            sender_state=sender_state,
            epoch=epoch,
            lease_id=lease_id,
            last_committed_sequence=last_committed_sequence,
            database_health=database_health
        )
        body = json.dumps(payload).encode("utf-8")
        headers = build_peer_headers(
            node_id=sender_node_id,
            epoch=epoch,
            secret=self.secret,
            method="POST",
            path=path,
            body=body
        )

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                return resp_data.get("ok", False), resp_data.get("data"), None
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                return False, None, err_body.get("error", {}).get("message", str(e))
            except Exception:
                return False, None, str(e)
        except Exception as e:
            return False, None, str(e)

    def replicate_batch(
        self,
        peer_url: str,
        sender_node_id: str,
        epoch: int,
        batch_id: str,
        from_sequence: int,
        events: List[Dict[str, Any]],
        max_retries: int = 3
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Send change_log batch to peer with exponential backoff and jitter.
        """
        path = "/api/v1/peer/replicate"
        url = f"{peer_url.rstrip('/')}{path}"
        batch = {
            "batch_id": batch_id,
            "from_sequence": from_sequence,
            "events": events
        }
        body = json.dumps(batch).encode("utf-8")

        for attempt in range(max_retries):
            # Compute fresh timestamp and headers per attempt
            headers = build_peer_headers(
                node_id=sender_node_id,
                epoch=epoch,
                secret=self.secret,
                method="POST",
                path=path,
                body=body
            )

            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    return resp_data.get("ok", False), resp_data.get("data"), None
            except urllib.error.HTTPError as e:
                # 4xx errors should not retry (e.g. auth failure or client error)
                try:
                    err_body = json.loads(e.read().decode("utf-8"))
                    err_msg = err_body.get("error", {}).get("message", str(e))
                    err_code = err_body.get("error", {}).get("code", "")
                    if e.code < 500:
                        return False, err_body.get("data"), f"{err_code}: {err_msg}"
                except Exception:
                    pass
                if attempt == max_retries - 1:
                    return False, None, f"HTTP Error {e.code}"
            except Exception as e:
                if attempt == max_retries - 1:
                    return False, None, str(e)

            # Exponential backoff with jitter: 0.1s * 2^attempt + jitter
            backoff = (0.1 * (2 ** attempt)) + (random.uniform(0.01, 0.05))
            time.sleep(backoff)

        return False, None, "Max retries exceeded"

    # Alias for explicit clarity in retry test suites
    send_batch_with_retry = replicate_batch

    def fetch_snapshot(
        self,
        peer_url: str,
        sender_node_id: str,
        epoch: int
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """Fetch full snapshot from peer for initial sync or full resync."""
        path = "/api/v1/peer/snapshot"
        url = f"{peer_url.rstrip('/')}{path}"
        headers = build_peer_headers(
            node_id=sender_node_id,
            epoch=epoch,
            secret=self.secret,
            method="GET",
            path=path,
            body=b""
        )
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                return resp_data.get("ok", False), resp_data.get("data"), None
        except Exception as e:
            return False, None, str(e)
