# SentinelDR — Phone Discovery Service
# Standard library ONLY. No pip installs. Runs on Android Termux.
# socket, threading, logging, json, time — nothing else.

import json
import logging
import socket
import threading
import time

from shared.constants import (
    DISCOVERY_PORT,
    DISCOVERY_INTERVAL,
    SERVICE_NAME,
)
from shared.messages import build_discovery_packet, build_discovery_event

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """
    Return the active LAN IP of this machine without assuming any subnet.
    Connects a UDP socket to an external address (no data sent), then
    reads back the locally-bound address.
    Falls back to 127.0.0.1 on any error.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class DiscoveryService:
    """
    UDP broadcast discovery for the phone (SECONDARY) node.
    Standard library only — no Pydantic, no FastAPI, no requests.

    Two daemon threads:
      - _broadcaster: sends a JSON discovery packet every DISCOVERY_INTERVAL s
      - _listener:    receives packets and updates runtime dict when a peer is found
    """

    def __init__(self, config_module=None, runtime_dict=None):
        # Allow injection for testing; fall back to module singletons
        if config_module is None:
            import phone.config as _c
            config_module = _c
        if runtime_dict is None:
            from phone.config import runtime as _r
            runtime_dict = _r

        self._config = config_module
        self._runtime = runtime_dict
        self._stop_event = threading.Event()

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start broadcaster and listener daemon threads."""
        local_ip = get_local_ip()
        logger.info(
            "[DISCOVERY] Starting on %s — broadcasting on port %d",
            local_ip,
            DISCOVERY_PORT,
        )

        broadcaster = threading.Thread(
            target=self._broadcaster,
            name="phone-discovery-broadcaster",
            daemon=True,
        )
        listener = threading.Thread(
            target=self._listener,
            name="phone-discovery-listener",
            daemon=True,
        )
        broadcaster.start()
        listener.start()

    def stop(self) -> None:
        """Signal threads to stop (best-effort for tests)."""
        self._stop_event.set()

    # ── Broadcaster ───────────────────────────────────────────────────────────

    def _broadcaster(self) -> None:
        """Periodically broadcast a discovery packet on the LAN."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            while not self._stop_event.is_set():
                try:
                    packet = build_discovery_packet(
                        node_id=self._config.NODE_ID,
                        role=self._config.NODE_ROLE,
                        port=self._config.NODE_PORT,
                    )
                    data = json.dumps(packet).encode("utf-8")
                    sock.sendto(data, ("255.255.255.255", DISCOVERY_PORT))
                    logger.debug(
                        "[DISCOVERY] Broadcast sent (%d bytes)", len(data)
                    )
                except OSError as exc:
                    logger.warning("[DISCOVERY] Broadcast error: %s", exc)
                self._stop_event.wait(DISCOVERY_INTERVAL)
        finally:
            sock.close()

    # ── Listener ──────────────────────────────────────────────────────────────

    def _listener(self) -> None:
        """Listen for discovery packets and register valid peers."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(2.0)   # allows checking stop_event periodically
        try:
            sock.bind(("0.0.0.0", DISCOVERY_PORT))
            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                    sender_ip = addr[0]
                    self._handle_packet(data, sender_ip)
                except socket.timeout:
                    continue
                except OSError as exc:
                    logger.warning("[DISCOVERY] Listener OSError: %s", exc)
        finally:
            sock.close()

    def _handle_packet(self, data: bytes, sender_ip: str) -> None:
        """Parse and process a single received discovery packet."""
        try:
            packet = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("[DISCOVERY] Bad packet from %s: %s", sender_ip, exc)
            return

        # Validate service name
        if packet.get("service") != SERVICE_NAME:
            return

        node_id = packet.get("node_id", "")
        role = packet.get("role", "")
        port = packet.get("port", DISCOVERY_PORT)

        # Ignore own broadcasts
        if node_id == self._config.NODE_ID:
            return

        logger.info(
            "[DISCOVERY] Found peer %s at %s:%s", node_id, sender_ip, port
        )

        # Update runtime dict — IP comes from the network, never the packet
        self._runtime["peer_host"] = sender_ip
        self._runtime["peer_node_id"] = node_id
        self._runtime["peer_role"] = role

        # Persist discovery event to SQLite (fire-and-forget)
        try:
            import phone.storage as _storage
            event = build_discovery_event(
                source_node_id=self._config.NODE_ID,
                peer_node_id=node_id,
                peer_ip=sender_ip,
            )
            _storage.save_event(event)
        except Exception as exc:
            logger.debug("[DISCOVERY] Event save error: %s", exc)
