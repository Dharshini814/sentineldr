# SentinelDR — Phone Heartbeat Service
# Standard library ONLY. Runs on Android Termux.
# urllib.request, threading, logging, time — nothing else.

import logging
import threading
import time
import urllib.request
import urllib.error

from shared.constants import (
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    MISSED_HEARTBEAT_THRESHOLD,
)

logger = logging.getLogger(__name__)


class HeartbeatService:
    """
    Phone heartbeat service — standard library only.

    Sends GET /heartbeat to the laptop every HEARTBEAT_INTERVAL seconds.
    Tracks missed beats and triggers failover when threshold is reached.

    Failover is imported lazily inside the trigger function to prevent
    circular imports before phone.failover is built (Module 8).
    """

    def __init__(self, config_module=None, runtime_dict=None):
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
        """Launch the send-loop daemon thread."""
        t = threading.Thread(
            target=self._send_loop,
            name="phone-heartbeat-sender",
            daemon=True,
        )
        t.start()
        logger.info("[HEARTBEAT] Service started")

    def stop(self) -> None:
        """Signal the send loop to stop (best-effort for tests)."""
        self._stop_event.set()

    # ── Send loop ─────────────────────────────────────────────────────────────

    def _send_loop(self) -> None:
        """Daemon thread: send a heartbeat to the laptop on every interval."""
        interval = getattr(self._config, "HEARTBEAT_INTERVAL", HEARTBEAT_INTERVAL)
        timeout = getattr(self._config, "HEARTBEAT_TIMEOUT", HEARTBEAT_TIMEOUT)
        threshold = getattr(
            self._config, "MISSED_HEARTBEAT_THRESHOLD", MISSED_HEARTBEAT_THRESHOLD
        )
        peer_port = getattr(self._config, "PEER_PORT", 8000)

        while not self._stop_event.is_set():
            self._stop_event.wait(interval)
            if self._stop_event.is_set():
                break
            try:
                self._tick(timeout, threshold, peer_port)
            except Exception as exc:
                # Phone server must never crash from heartbeat errors
                logger.error("[HEARTBEAT] Unexpected error in tick: %s", exc)

    def _tick(self, timeout: int, threshold: int, peer_port: int) -> None:
        """Single heartbeat attempt."""
        peer_host = self._runtime.get("peer_host")
        if not peer_host:
            logger.debug("[HEARTBEAT] No peer discovered yet — skipping")
            return

        peer_url = f"http://{peer_host}:{peer_port}"
        api_key = getattr(self._config, "API_KEY", "")

        try:
            req = urllib.request.Request(
                f"{peer_url}/heartbeat",
                headers={"X-API-Key": api_key},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    self._on_success(peer_url)
                else:
                    self._on_miss(threshold, f"HTTP {resp.status}")
        except Exception as exc:
            self._on_miss(threshold, exc)

    def _on_success(self, peer_url: str) -> None:
        """Handle a successful heartbeat response."""
        self._runtime["missed_heartbeats"] = 0
        self._runtime["peer_status"] = "healthy"
        self._runtime["peer_last_seen"] = time.time()
        self._runtime["heartbeat_sequence"] = self._runtime.get("heartbeat_sequence", 0) + 1
        seq = self._runtime["heartbeat_sequence"]
        logger.debug("[HEARTBEAT] Primary healthy — seq %d", seq)
        
        # If we're in failover but primary is healthy, attempt recovery
        if self._runtime.get("failover_active", False):
            logger.info("[HEARTBEAT] Primary responding during failover — attempting recovery")
            try:
                import phone.failover as failover_module
                failover_module.trigger_recovery(peer_url)
            except Exception as exc:
                logger.error("[HEARTBEAT] Recovery attempt failed: %s", exc)

    def _on_miss(self, threshold: int, reason) -> None:
        """Handle a failed heartbeat attempt."""
        self._runtime["missed_heartbeats"] = self._runtime.get("missed_heartbeats", 0) + 1
        count = self._runtime["missed_heartbeats"]
        logger.warning("[HEARTBEAT] Miss %d/%d (%s)", count, threshold, reason)

        # Only trigger failover ONCE when threshold is reached
        if count == threshold:  # EXACTLY equal, not >=
            self._runtime["peer_status"] = "offline"
            logger.error(
                "[HEARTBEAT] Primary failure threshold reached — triggering failover"
            )
            self._trigger_failover()
        elif count > threshold:
            # Continue marking peer offline but don't re-trigger failover
            self._runtime["peer_status"] = "offline"

    def _trigger_failover(self) -> None:
        """
        Lazy import of phone.failover to prevent circular imports.
        phone.failover is built in Module 8 — this import will succeed
        once that module exists.
        """
        try:
            import phone.failover as failover_module  # lazy import
            failover_module.trigger_failover()
        except ImportError:
            # Module 8 not yet built — log and continue
            logger.warning(
                "[HEARTBEAT] phone.failover not available yet — "
                "failover not triggered"
            )
        except Exception as exc:
            logger.error("[HEARTBEAT] Failover trigger error: %s", exc)
