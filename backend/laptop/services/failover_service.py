# SentinelDR — Laptop Failover Coordination Service
# Tracks failover state from the laptop's perspective and coordinates
# graceful failback when the laptop returns online.

import logging
from datetime import datetime, timezone

import requests

from shared.messages import build_failover_alert, build_recovery_alert

logger = logging.getLogger(__name__)


class FailoverService:
    """
    Laptop-side failover coordination.

    The laptop does NOT trigger failover — that is the phone's responsibility.
    The laptop:
      - Records when it learns the phone has taken over
      - Announces its return to the phone on restart
      - Coordinates failback after a successful recovery announcement
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

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """No background thread needed — service is event-driven."""
        logger.info("[FAILOVER] Failover service ready")

    def stop(self) -> None:
        """No background thread to stop — no-op, present for symmetry."""
        logger.info("[FAILOVER] Failover service stopped")

    def record_peer_failover(self) -> None:
        """
        Called when the laptop detects the phone has entered active failover.
        Records state so the laptop knows it needs to announce recovery on restart.
        """
        logger.warning(
            "[FAILOVER] Secondary node has taken over — laptop is recovering"
        )
        # Laptop should never set failover_active = True - it's always primary
        # self._runtime.failover_active = True  # Removed to maintain laptop as primary

        try:
            if self._alert is not None:
                self._alert.emit_failover(source_node_id=self._settings.NODE_ID)
            else:
                build_failover_alert(source_node_id=self._settings.NODE_ID)
        except Exception as exc:
            logger.debug("[FAILOVER] Alert build error: %s", exc)

    def announce_recovery(self) -> bool:
        """
        Called after the laptop restarts and rediscovers the phone.
        POSTs a recovery announcement to the phone.

        Returns True on success, False on failure.
        """
        peer_url = self._runtime.get_peer_url(self._settings.PEER_PORT)
        if peer_url is None:
            logger.warning("[RECOVERY] Cannot announce — peer URL not known yet")
            return False

        payload = {
            "node_id": self._settings.NODE_ID,
            "role": "primary",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            resp = requests.post(
                f"{peer_url}/recovery-announcement",
                json=payload,
                headers={"X-API-Key": self._settings.API_KEY},
                timeout=5,
            )
            if resp.status_code == 200:
                logger.info(
                    "[RECOVERY] Announced return to phone — awaiting sync"
                )
                return True
            else:
                logger.warning(
                    "[RECOVERY] Announcement got HTTP %d — will retry on next cycle",
                    resp.status_code,
                )
                return False
        except Exception as exc:
            logger.warning(
                "[RECOVERY] Announcement failed: %s — retry handled by discovery cycle",
                exc,
            )
            return False

    def coordinate_failback(self) -> None:
        """
        Called after a successful recovery announcement.
        Resets laptop state to normal primary operation.
        """
        self._runtime.failover_active = False
        self._runtime.peer_status = "healthy"
        logger.info(
            "[RECOVERY] Laptop PRIMARY restored — phone returning to SECONDARY"
        )
        if self._alert is not None:
            try:
                self._alert.emit_recovery(source_node_id=self._settings.NODE_ID)
            except Exception as exc:
                logger.debug("[RECOVERY] Alert emit error: %s", exc)

    def get_status(self) -> dict:
        """Return current failover state as a dict."""
        return {
            "failover_active": self._runtime.failover_active,
            "failover_time": self._runtime.failover_time,
            "peer_status": self._runtime.peer_status,
        }
