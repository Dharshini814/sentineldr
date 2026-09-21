# SentinelDR — Laptop Heartbeat Service
# Sends heartbeats to the peer and tracks missed beats for monitoring.
# Laptop does NOT trigger failover — that is the phone's responsibility.

import logging
import threading
import time
from datetime import datetime, timezone

import requests

from shared.constants import (
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    MISSED_HEARTBEAT_THRESHOLD,
    STATUS_HEALTHY,
)

logger = logging.getLogger(__name__)


class HeartbeatService:
    """
    Laptop heartbeat service.

    - _send_loop (daemon thread): periodically GETs /heartbeat on the peer
    - handle_incoming(): called by the FastAPI /heartbeat endpoint to
      respond with this node's current health status
    """

    def __init__(self, settings=None, runtime=None, alert_service=None):
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
        """Launch the send-loop daemon thread."""
        t = threading.Thread(
            target=self._send_loop,
            name="heartbeat-sender",
            daemon=True,
        )
        t.start()
        logger.info("[HEARTBEAT] Service started")

    def stop(self) -> None:
        """Signal the send loop to stop (best-effort for tests)."""
        self._stop_event.set()

    def handle_incoming(
        self,
        node_id: str,
        role: str,
        sequence: int,
        status: str,
    ) -> dict:
        """
        Called by the FastAPI /heartbeat endpoint when a peer heartbeat arrives.
        Returns this node's current health status as a dict.
        """
        return {
            "node_id": self._settings.NODE_ID,
            "role": self._settings.NODE_ROLE,
            "status": STATUS_HEALTHY,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sequence": self._runtime.heartbeat_sequence,
            "uptime_seconds": self._runtime.get_uptime(),
        }

    # ── Send loop ─────────────────────────────────────────────────────────────

    def _send_loop(self) -> None:
        """Daemon thread: send a heartbeat to the peer on every interval."""
        interval = getattr(self._settings, "HEARTBEAT_INTERVAL", HEARTBEAT_INTERVAL)
        timeout = getattr(self._settings, "HEARTBEAT_TIMEOUT", HEARTBEAT_TIMEOUT)
        threshold = getattr(
            self._settings, "MISSED_HEARTBEAT_THRESHOLD", MISSED_HEARTBEAT_THRESHOLD
        )
        peer_port = getattr(self._settings, "PEER_PORT", 8001)

        while not self._stop_event.is_set():
            self._stop_event.wait(interval)
            if self._stop_event.is_set():
                break
            self._tick(timeout, threshold, peer_port)

    def _tick(self, timeout: int, threshold: int, peer_port: int) -> None:
        """Single heartbeat attempt."""
        peer_url = self._runtime.get_peer_url(peer_port)
        if peer_url is None:
            logger.debug("[HEARTBEAT] No peer discovered yet — skipping")
            return

        try:
            resp = requests.get(
                f"{peer_url}/heartbeat",
                headers={"X-API-Key": self._settings.API_KEY},
                timeout=timeout,
            )
            if resp.status_code == 200:
                self._runtime.update_peer_healthy()
                self._runtime.heartbeat_sequence += 1
                seq = self._runtime.heartbeat_sequence
                logger.debug("[HEARTBEAT] Peer healthy — seq %d", seq)
            else:
                self._on_miss(threshold, resp.status_code)
        except Exception as exc:
            self._on_miss(threshold, exc)

    def _on_miss(self, threshold: int, reason) -> None:
        """Handle a failed heartbeat attempt."""
        count = self._runtime.increment_missed_heartbeat()
        logger.warning("[HEARTBEAT] Miss %d/%d (%s)", count, threshold, reason)
        if count >= threshold:
            self._runtime.mark_peer_offline()
            logger.error(
                "[HEARTBEAT] Peer unreachable — threshold reached"
            )
            # Emit alert if wired
            if self._alert is not None:
                try:
                    self._alert.emit_heartbeat_warning(missed=count, threshold=threshold)
                except Exception as exc:
                    logger.debug("[HEARTBEAT] Alert emit error: %s", exc)
            # Laptop does NOT trigger failover — phone is responsible
