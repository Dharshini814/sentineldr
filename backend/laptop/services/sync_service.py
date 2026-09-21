# SentinelDR — Laptop Synchronization Service
# Pushes PostgreSQL portfolio snapshots to the phone on a regular interval
# and immediately after any portfolio change.

import hashlib
import json
import logging
import threading
import time
from datetime import datetime

import requests

from shared.constants import SYNC_INTERVAL
from shared.messages import build_sync_snapshot

logger = logging.getLogger(__name__)


def _dt_to_iso(value) -> str | None:
    """Convert a datetime object to ISO 8601 string, or return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _compute_checksum(projects: list) -> str:
    """SHA-256 of sorted-by-id JSON of the projects list."""
    sorted_projects = sorted(projects, key=lambda p: p.get("id", ""))
    serialised = json.dumps(sorted_projects, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


class SyncService:
    """
    Laptop sync service.

    Periodically builds a full snapshot of the PostgreSQL projects table and
    POSTs it to the phone's /sync/snapshot endpoint.
    """

    def __init__(self, settings=None, runtime=None, db_session_factory=None, alert_service=None):
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
        self._alert = alert_service
        self._stop_event = threading.Event()

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the sync loop as a daemon thread."""
        interval = getattr(self._settings, "SYNC_INTERVAL", SYNC_INTERVAL)
        t = threading.Thread(
            target=self._sync_loop,
            name="sync-loop",
            daemon=True,
        )
        t.start()
        logger.info("[SYNC] Service started — interval %ds", interval)

    def stop(self) -> None:
        """Signal the sync loop to stop."""
        self._stop_event.set()

    def push_now(self) -> None:
        """
        Force an immediate sync outside the regular interval.
        Runs in a short-lived daemon thread so it does not block the API caller.
        """
        logger.info("[SYNC] Immediate sync triggered")
        t = threading.Thread(
            target=self._do_sync,
            name="sync-immediate",
            daemon=True,
        )
        t.start()

    def get_status(self) -> dict:
        """Return current sync state."""
        peer_url = self._runtime.get_peer_url(
            getattr(self._settings, "PEER_PORT", 8001)
        )
        last_sync_iso = None
        if self._runtime.last_sync_time is not None:
            from datetime import datetime, timezone
            last_sync_iso = datetime.fromtimestamp(
                self._runtime.last_sync_time, tz=timezone.utc
            ).isoformat()
        return {
            "sync_version": self._runtime.sync_version,
            "last_sync_time": last_sync_iso,
            "last_sync_checksum": self._runtime.last_sync_checksum,
            "peer_reachable": peer_url is not None,
            "sync_interval": getattr(self._settings, "SYNC_INTERVAL", 3),
        }

    # ── Snapshot building ─────────────────────────────────────────────────────

    def _build_snapshot(self) -> dict:
        """
        Query PostgreSQL, serialise all projects, compute checksum,
        and build a versioned sync snapshot dict.
        """
        from laptop.models.portfolio import Project

        session = self._db()
        try:
            rows = session.query(Project).all()
            projects = [
                {
                    "id": row.id,
                    "title": row.title,
                    "description": row.description,
                    "tech_stack": row.tech_stack,
                    "status": row.status,
                    "created_at": _dt_to_iso(row.created_at),
                    "updated_at": _dt_to_iso(row.updated_at),
                    "sync_version": row.sync_version,
                    "checksum": row.checksum,
                }
                for row in rows
            ]
        finally:
            session.close()

        checksum = _compute_checksum(projects)
        self._runtime.sync_version += 1
        version = self._runtime.sync_version

        snapshot = build_sync_snapshot(
            source_node_id=self._settings.NODE_ID,
            version=version,
            payload={"projects": projects},
            checksum=checksum,
        )
        return snapshot

    # ── Push ──────────────────────────────────────────────────────────────────

    def _push_snapshot(self, snapshot: dict) -> bool:
        """POST the snapshot to the phone's /sync/snapshot endpoint."""
        peer_port = getattr(self._settings, "PEER_PORT", 8001)
        peer_url = self._runtime.get_peer_url(peer_port)
        if peer_url is None:
            logger.debug("[SYNC] No peer discovered yet — skipping push")
            return False

        version = snapshot.get("version")
        checksum = snapshot.get("checksum", "")
        count = len(snapshot.get("payload", {}).get("projects", []))

        try:
            resp = requests.post(
                f"{peer_url}/sync/snapshot",
                json=snapshot,
                headers={"X-API-Key": self._settings.API_KEY},
                timeout=10,
            )
            if resp.status_code == 200:
                self._runtime.update_sync(version=version, checksum=checksum)
                logger.info(
                    "[SYNC] Snapshot v%d pushed — %d projects — checksum %s",
                    version,
                    count,
                    checksum[:8],
                )
                if self._alert is not None:
                    try:
                        self._alert.emit_sync(version=version, project_count=count)
                    except Exception as exc:
                        logger.debug("[SYNC] Alert emit error: %s", exc)
                return True
            else:
                logger.warning(
                    "[SYNC] Push failed — HTTP %d", resp.status_code
                )
                return False
        except Exception as exc:
            logger.warning("[SYNC] Push failed — %s", exc)
            return False

    # ── Loop ──────────────────────────────────────────────────────────────────

    def _sync_loop(self) -> None:
        """Daemon thread: sync on every interval."""
        interval = getattr(self._settings, "SYNC_INTERVAL", SYNC_INTERVAL)
        while not self._stop_event.is_set():
            self._stop_event.wait(interval)
            if self._stop_event.is_set():
                break
            self._do_sync()

    def _do_sync(self) -> None:
        """Build and push one snapshot — swallows all exceptions."""
        try:
            snapshot = self._build_snapshot()
            self._push_snapshot(snapshot)
        except Exception as exc:
            logger.warning("[SYNC] Sync cycle error — %s", exc)
