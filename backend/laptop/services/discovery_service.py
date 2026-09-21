# SentinelDR — Laptop Discovery Service
# Broadcasts presence over UDP and listens for peer nodes.
# Laptop: full stdlib + socket, threading, logging, json

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
    UDP broadcast discovery for the laptop (PRIMARY) node.

    Two daemon threads:
      - _broadcaster: sends a JSON discovery packet every DISCOVERY_INTERVAL s
      - _listener:    receives packets and updates runtime when a valid peer is found
    """

    def __init__(self, settings=None, runtime=None, alert_service=None):
        # Allow injection for testing; fall back to singletons
        if settings is None:
            from laptop.config import settings as _s
            settings = _s
        if runtime is None:
            from laptop.config import runtime as _r
            runtime = _r

        self._settings = settings
        self._runtime = runtime
        self._alert = alert_service
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
            name="discovery-broadcaster",
            daemon=True,
        )
        listener = threading.Thread(
            target=self._listener,
            name="discovery-listener",
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
                        node_id=self._settings.NODE_ID,
                        role=self._settings.NODE_ROLE,
                        port=self._settings.NODE_PORT,
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
        if node_id == self._settings.NODE_ID:
            return

        logger.info(
            "[DISCOVERY] Found peer %s at %s:%s", node_id, sender_ip, port
        )

        # Update runtime state — IP comes from the network, never the packet
        self._runtime.update_peer_discovered(
            host=sender_ip,
            node_id=node_id,
            role=role,
        )

        # Emit discovery event via alert service (or fire-and-forget if not wired)
        try:
            if self._alert is not None:
                self._alert.emit_discovery(
                    peer_node_id=node_id,
                    peer_ip=sender_ip,
                )
            else:
                build_discovery_event(
                    source_node_id=self._settings.NODE_ID,
                    peer_node_id=node_id,
                    peer_ip=sender_ip,
                )
        except Exception as exc:
            logger.debug("[DISCOVERY] Event build error: %s", exc)
