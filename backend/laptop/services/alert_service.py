# SentinelDR — Laptop Alert Service
# Single source of truth for all system events on the laptop.
# Stores events in PostgreSQL and serves them to the frontend.
#
# WIRE POINTS — called by other services:
#
# discovery_service.py  → self.alert.emit_discovery(peer_node_id, peer_ip)
# heartbeat_service.py  → self.alert.emit_heartbeat_warning(missed, threshold)
# sync_service.py       → self.alert.emit_sync(version, count)
# failover_service.py   → self.alert.emit_failover(source_node_id)
#                       → self.alert.emit_recovery(source_node_id)
# main.py               → self.alert.emit_startup()

import json
import logging

from shared.constants import (
    EVT_DISCOVERY,
    EVT_FAILOVER,
    EVT_HEARTBEAT,
    EVT_RECOVERY,
    EVT_STARTUP,
    EVT_SYNC,
    SEV_CRITICAL,
    SEV_INFO,
    SEV_SUCCESS,
    SEV_WARNING,
)
from shared.messages import build_event

logger = logging.getLogger(__name__)

# Severity → (log_level, log_prefix)
_SEV_LOG = {
    SEV_CRITICAL: (logging.ERROR,   "[ALERT CRITICAL]"),
    SEV_WARNING:  (logging.WARNING, "[ALERT WARNING]"),
    SEV_SUCCESS:  (logging.INFO,    "[ALERT SUCCESS]"),
    SEV_INFO:     (logging.INFO,    "[ALERT INFO]"),
}


class AlertService:
    """
    Centralised alert/event service for the laptop node.

    All services call this to emit events; it persists them to PostgreSQL
    and exposes query methods for the frontend API.
    """

    def __init__(self, settings=None, runtime=None, db_session_factory=None):
        if settings is None:
            from laptop.config import settings as _s
            settings = _s
        if runtime is None:
            from laptop.config import runtime as _r
            runtime = _r
        if db_session_factory is None:
            from laptop.database import SessionLocal as _sl
            db_session_factory = _sl

        self._settings = settings
        self._runtime = runtime
        self._db = db_session_factory

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Emit a startup event and signal readiness."""
        self.emit_startup()
        logger.info("[ALERT] Alert service ready")

    # ── Core emit ─────────────────────────────────────────────────────────────

    def emit(
        self,
        event_type: str,
        severity: str,
        source: str,
        message: str,
        metadata: dict = None,
    ) -> dict:
        """
        Build an event, persist it to PostgreSQL, log it, and return the dict.
        Never raises — database errors are caught and logged.
        """
        from laptop.models.events import Event

        event_dict = build_event(
            event_type=event_type,
            severity=severity,
            source=source,
            message=message,
            metadata=metadata or {},
        )

        # ── Log by severity ───────────────────────────
        log_level, prefix = _SEV_LOG.get(severity, (logging.INFO, "[ALERT]"))
        logger.log(log_level, "%s %s — %s", prefix, event_type, message)

        # ── Persist to PostgreSQL ─────────────────────
        session = self._db()
        try:
            row = Event(
                id=event_dict["id"],
                event_type=event_dict["event_type"],
                severity=event_dict["severity"],
                source=event_dict["source"],
                message=event_dict["message"],
                acknowledged=event_dict["acknowledged"],
                metadata_json=json.dumps(event_dict.get("metadata", {})),
            )
            session.add(row)
            session.commit()
        except Exception as exc:
            logger.error("[ALERT] Failed to persist event: %s", exc)
            try:
                session.rollback()
            except Exception:
                pass
        finally:
            session.close()

        return event_dict

    # ── Convenience emitters ──────────────────────────────────────────────────

    def emit_failover(self, source_node_id: str) -> dict:
        return self.emit(
            event_type=EVT_FAILOVER,
            severity=SEV_CRITICAL,
            source=source_node_id,
            message="Primary node unavailable. Phone recovery node activated.",
            metadata={"source_node": source_node_id},
        )

    def emit_recovery(self, source_node_id: str) -> dict:
        return self.emit(
            event_type=EVT_RECOVERY,
            severity=SEV_SUCCESS,
            source=source_node_id,
            message="Primary node restored. System returning to normal operation.",
            metadata={"source_node": source_node_id},
        )

    def emit_sync(self, version: int, project_count: int) -> dict:
        return self.emit(
            event_type=EVT_SYNC,
            severity=SEV_INFO,
            source=self._settings.NODE_ID,
            message=f"Sync snapshot v{version} pushed — {project_count} projects",
        )

    def emit_discovery(self, peer_node_id: str, peer_ip: str) -> dict:
        return self.emit(
            event_type=EVT_DISCOVERY,
            severity=SEV_INFO,
            source=self._settings.NODE_ID,
            message=f"Peer {peer_node_id} discovered at {peer_ip}",
        )

    def emit_heartbeat_warning(self, missed: int, threshold: int) -> dict:
        return self.emit(
            event_type=EVT_HEARTBEAT,
            severity=SEV_WARNING,
            source=self._settings.NODE_ID,
            message=f"Missed heartbeats: {missed}/{threshold}",
        )

    def emit_startup(self) -> dict:
        return self.emit(
            event_type=EVT_STARTUP,
            severity=SEV_INFO,
            source=self._settings.NODE_ID,
            message=(
                f"Node {self._settings.NODE_ID} started"
                f" — role: {self._settings.NODE_ROLE}"
            ),
        )

    # ── Query methods ─────────────────────────────────────────────────────────

    def _row_to_dict(self, row) -> dict:
        """Convert an Event ORM row to a plain dict."""
        metadata = {}
        if row.metadata_json:
            try:
                metadata = json.loads(row.metadata_json)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        return {
            "id": row.id,
            "event_type": row.event_type,
            "severity": row.severity,
            "source": row.source,
            "message": row.message,
            "timestamp": (
                row.timestamp.isoformat() if row.timestamp else None
            ),
            "acknowledged": row.acknowledged,
            "metadata": metadata,
        }

    def get_recent(self, limit: int = 50) -> list:
        """Return the most recent events ordered by timestamp descending."""
        from laptop.models.events import Event
        from sqlalchemy import desc

        session = self._db()
        try:
            rows = (
                session.query(Event)
                .order_by(desc(Event.timestamp))
                .limit(limit)
                .all()
            )
            return [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            logger.error("[ALERT] get_recent failed: %s", exc)
            return []
        finally:
            session.close()

    def get_unacknowledged(self) -> list:
        """Return all unacknowledged events ordered by timestamp descending."""
        from laptop.models.events import Event
        from sqlalchemy import desc

        session = self._db()
        try:
            rows = (
                session.query(Event)
                .filter(Event.acknowledged == False)  # noqa: E712
                .order_by(desc(Event.timestamp))
                .all()
            )
            return [self._row_to_dict(r) for r in rows]
        except Exception as exc:
            logger.error("[ALERT] get_unacknowledged failed: %s", exc)
            return []
        finally:
            session.close()

    def acknowledge(self, event_id: str) -> bool:
        """
        Mark a single event as acknowledged.
        Returns True on success, False if not found or on error.
        """
        from laptop.models.events import Event

        session = self._db()
        try:
            row = session.get(Event, event_id)
            if row is None:
                return False
            row.acknowledged = True
            session.commit()
            return True
        except Exception as exc:
            logger.error("[ALERT] acknowledge failed: %s", exc)
            try:
                session.rollback()
            except Exception:
                pass
            return False
        finally:
            session.close()

    def get_counts(self) -> dict:
        """Return summary counts for the dashboard."""
        from laptop.models.events import Event
        from sqlalchemy import func

        session = self._db()
        try:
            total = session.query(func.count(Event.id)).scalar() or 0
            unacknowledged = (
                session.query(func.count(Event.id))
                .filter(Event.acknowledged == False)  # noqa: E712
                .scalar()
                or 0
            )
            critical = (
                session.query(func.count(Event.id))
                .filter(Event.severity == SEV_CRITICAL)
                .scalar()
                or 0
            )
            warnings = (
                session.query(func.count(Event.id))
                .filter(Event.severity == SEV_WARNING)
                .scalar()
                or 0
            )
            return {
                "total": total,
                "unacknowledged": unacknowledged,
                "critical": critical,
                "warnings": warnings,
            }
        except Exception as exc:
            logger.error("[ALERT] get_counts failed: %s", exc)
            return {"total": 0, "unacknowledged": 0, "critical": 0, "warnings": 0}
        finally:
            session.close()
