# SentinelDR — Phone Storage Layer
# Standard library ONLY. Runs on Android Termux.
# sqlite3, json, hashlib, logging, time, uuid — nothing else.

import sqlite3
import json
import hashlib
import logging
import time

logger = logging.getLogger(__name__)

# Module-level db path — set by init_storage()
_db_path: str = ""


# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    description  TEXT,
    tech_stack   TEXT,
    status       TEXT DEFAULT 'active',
    created_at   TEXT,
    updated_at   TEXT,
    sync_version INTEGER DEFAULT 0,
    checksum     TEXT
);
"""

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id            TEXT PRIMARY KEY,
    event_type    TEXT NOT NULL,
    severity      TEXT NOT NULL,
    source        TEXT,
    message       TEXT,
    timestamp     TEXT,
    acknowledged  INTEGER DEFAULT 0,
    metadata_json TEXT
);
"""

_CREATE_SYNC_META = """
CREATE TABLE IF NOT EXISTS sync_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# ── Connection helper ─────────────────────────────────────────────────────────

def _connect(db_path: str = "") -> sqlite3.Connection:
    """Open a connection to the configured (or provided) SQLite database."""
    path = db_path or _db_path
    if not path:
        raise RuntimeError("Storage not initialised — call init_storage() first.")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row   # rows accessible as dicts
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


# ── Public API ────────────────────────────────────────────────────────────────

def init_storage(db_path: str) -> None:
    """
    Initialise the SQLite database at db_path.
    Creates all three tables if they do not exist.
    """
    global _db_path
    _db_path = db_path

    conn = _connect(db_path)
    try:
        with conn:
            conn.execute(_CREATE_PROJECTS)
            conn.execute(_CREATE_EVENTS)
            conn.execute(_CREATE_SYNC_META)
        logger.info("Storage initialised at %s", db_path)
    except Exception as exc:
        logger.error("Failed to initialise storage: %s", exc)
        raise
    finally:
        conn.close()


def compute_checksum(projects: list) -> str:
    """
    Compute a deterministic SHA-256 checksum over a list of project dicts.
    Projects are sorted by 'id' before hashing for order independence.
    """
    sorted_projects = sorted(projects, key=lambda p: p.get("id", ""))
    serialised = json.dumps(sorted_projects, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()


def apply_sync_snapshot(snapshot: dict) -> dict:
    """
    Apply a full sync snapshot received from the laptop.

    Steps:
      1. Validate required keys
      2. Reject if incoming version <= current version (stale)
      3. Extract projects from payload
      4. Verify checksum
      5. Replace all projects atomically
      6. Update sync_meta version

    Returns a result dict: {"status": "ok"|"rejected", ...}
    """
    # ── Validate keys ─────────────────────────────────
    for key in ("version", "payload", "checksum"):
        if key not in snapshot:
            return {"status": "rejected", "reason": f"missing_key:{key}"}

    incoming_version: int = snapshot["version"]
    incoming_checksum: str = snapshot["checksum"]
    payload: dict = snapshot["payload"]
    projects: list = payload.get("projects", [])

    # ── Stale check ───────────────────────────────────
    current_version = get_sync_version()
    if incoming_version <= current_version:
        return {"status": "rejected", "reason": "stale"}

    # ── Checksum verification ─────────────────────────
    computed = compute_checksum(projects)
    if computed != incoming_checksum:
        return {"status": "rejected", "reason": "checksum_mismatch"}

    # ── Atomic replace ────────────────────────────────
    conn = _connect()
    try:
        with conn:   # single transaction — rolled back on any exception
            conn.execute("DELETE FROM projects;")
            for proj in projects:
                conn.execute(
                    """
                    INSERT INTO projects
                        (id, title, description, tech_stack, status,
                         created_at, updated_at, sync_version, checksum)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proj.get("id"),
                        proj.get("title"),
                        proj.get("description"),
                        proj.get("tech_stack"),
                        proj.get("status", "active"),
                        proj.get("created_at"),
                        proj.get("updated_at"),
                        proj.get("sync_version", 0),
                        proj.get("checksum"),
                    ),
                )
            # Update sync version and last sync time
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('sync_version', ?);",
                (str(incoming_version),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('last_sync_time', ?);",
                (now,),
            )
        logger.info("Sync snapshot v%d applied — %d projects", incoming_version, len(projects))
        return {"status": "ok", "version": incoming_version, "count": len(projects)}
    except Exception as exc:
        logger.error("Failed to apply sync snapshot: %s", exc)
        raise
    finally:
        conn.close()


def get_all_projects() -> list:
    """Return all projects as a list of dicts, ordered by created_at descending."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC;"
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_project(project_id: str):
    """Return a single project dict or None if not found."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM projects WHERE id = ?;", (project_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_event(event: dict) -> None:
    """Insert an event dict into the events table."""
    conn = _connect()
    try:
        acknowledged = 1 if event.get("acknowledged") else 0
        with conn:
            conn.execute(
                """
                INSERT INTO events
                    (id, event_type, severity, source, message,
                     timestamp, acknowledged, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("id"),
                    event.get("event_type"),
                    event.get("severity"),
                    event.get("source"),
                    event.get("message"),
                    event.get("timestamp"),
                    acknowledged,
                    event.get("metadata_json"),
                ),
            )
    finally:
        conn.close()


def get_events(limit: int = 50) -> list:
    """Return the most recent events as a list of dicts, ordered by timestamp descending."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?;", (limit,)
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_sync_version() -> int:
    """Return the current sync version from sync_meta, or 0 if not set."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT value FROM sync_meta WHERE key = 'sync_version';"
        )
        row = cur.fetchone()
        return int(row["value"]) if row else 0
    finally:
        conn.close()


def get_storage_stats() -> dict:
    """Return counts and sync metadata as a summary dict."""
    conn = _connect()
    try:
        project_count = conn.execute("SELECT COUNT(*) FROM projects;").fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM events;").fetchone()[0]

        version_row = conn.execute(
            "SELECT value FROM sync_meta WHERE key = 'sync_version';"
        ).fetchone()
        sync_version = int(version_row[0]) if version_row else 0

        time_row = conn.execute(
            "SELECT value FROM sync_meta WHERE key = 'last_sync_time';"
        ).fetchone()
        last_sync_time = time_row[0] if time_row else None

        return {
            "project_count": project_count,
            "event_count": event_count,
            "sync_version": sync_version,
            "last_sync_time": last_sync_time,
        }
    finally:
        conn.close()

def acknowledge_event(event_id: str) -> bool:
    """
    Mark a single event as acknowledged.
    Returns True if the event was found and updated, False otherwise.
    """
    conn = _connect()
    try:
        with conn:
            cursor = conn.execute(
                "UPDATE events SET acknowledged = 1 WHERE id = ?;",
                (event_id,)
            )
            return cursor.rowcount > 0
    except Exception as exc:
        logger.error("Failed to acknowledge event %s: %s", event_id, exc)
        return False
    finally:
        conn.close()