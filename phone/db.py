"""
SentinelDR Phone Node - Database Layer
Standard library only: sqlite3.
Strictly zero third-party dependencies (no FastAPI, Pydantic, psycopg, etc.).
"""

import json
import os
import sqlite3
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.ownership import (
    OwnershipRecord,
    sign_ownership_record,
    validate_lease,
)
from shared.seed_data import (
    CERTIFICATIONS_SEED,
    CONTACT_SEED,
    EDUCATION_SEED,
    EXPERIENCE_SEED,
    PROFILE_SEED,
    PROJECTS_SEED,
    SKILLS_SEED,
)


class PhoneDatabase:
    """Manages SQLite connection, WAL mode, pragmas, schema, and transactional outbox writes."""

    def __init__(self, db_path: str, cluster_id: str = "sentineldr-cluster-01", secret: Optional[str] = None):
        self.db_path = db_path
        self.cluster_id = cluster_id
        self.secret = secret or os.getenv("SDR_HMAC_SECRET", "sdr-dev-hmac-secret-change-in-prod-001")
        self.witness_secret = os.getenv("SDR_WITNESS_SECRET", self.secret)
        self._schema_file = os.path.join(os.path.dirname(__file__), "schema.sql")
        self.init_db()
        self.seed_portfolio_data()

    def get_connection(self) -> sqlite3.Connection:
        """Create a connection with required PRAGMAs enforced."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=5.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = FULL;")
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.close()
        return conn

    def init_db(self):
        """Execute initial schema migration if tables do not exist."""
        if not os.path.exists(self._schema_file):
            raise FileNotFoundError(f"Schema file not found at {self._schema_file}")

        with open(self._schema_file, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        conn = self.get_connection()
        try:
            conn.executescript(schema_sql)
            conn.commit()
        finally:
            conn.close()

    def is_healthy(self) -> Tuple[bool, Optional[str]]:
        """Verify DB readiness and integrity via PRAGMA quick_check."""
        try:
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA quick_check;")
                res = cursor.fetchone()
                if res and res[0] == "ok":
                    return True, None
                return False, f"Integrity check failed: {res[0] if res else 'Unknown'}"
            finally:
                conn.close()
        except Exception as e:
            return False, str(e)

    def verify_full_integrity(self) -> Tuple[bool, Optional[str]]:
        """Verify complete SQLite physical integrity via PRAGMA integrity_check."""
        try:
            conn = self.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check;")
                rows = cursor.fetchall()
                if rows and rows[0][0] == "ok":
                    return True, None
                errors = [r[0] for r in rows]
                return False, f"Integrity check failed: {'; '.join(errors)}"
            finally:
                conn.close()
        except Exception as e:
            return False, str(e)

    def seed_portfolio_data(self):
        """Seed initial portfolio records if empty."""
        conn = self.get_connection()
        now = time.time()
        try:
            cur = conn.cursor()
            # 1. Profile
            cur.execute("SELECT 1 FROM portfolio_profile WHERE id = ?", (PROFILE_SEED["id"],))
            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO portfolio_profile (id, name, headline, bio_primary, bio_secondary, cta_text, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        PROFILE_SEED["id"],
                        PROFILE_SEED["name"],
                        PROFILE_SEED["headline"],
                        PROFILE_SEED["bio_primary"],
                        PROFILE_SEED["bio_secondary"],
                        PROFILE_SEED["cta_text"],
                        now,
                    )
                )

            # 2. Skills
            cur.execute("SELECT count(*) FROM portfolio_skills")
            if cur.fetchone()[0] == 0:
                for item in SKILLS_SEED:
                    cur.execute(
                        """
                        INSERT INTO portfolio_skills (id, category, items, display_order, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (item["id"], item["category"], json.dumps(item["items"]), item["display_order"], now)
                    )

            # 3. Projects
            cur.execute("SELECT count(*) FROM portfolio_projects")
            if cur.fetchone()[0] == 0:
                for item in PROJECTS_SEED:
                    cur.execute(
                        """
                        INSERT INTO portfolio_projects (id, title, description, link, display_order, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (item["id"], item["title"], item["description"], item["link"], item["display_order"], now)
                    )

            # 4. Experience
            cur.execute("SELECT count(*) FROM portfolio_experience")
            if cur.fetchone()[0] == 0:
                for item in EXPERIENCE_SEED:
                    cur.execute(
                        """
                        INSERT INTO portfolio_experience (id, role, company, duration, description, display_order, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (item["id"], item["role"], item["company"], item["duration"], item["description"], item["display_order"], now)
                    )

            # 5. Education
            cur.execute("SELECT count(*) FROM portfolio_education")
            if cur.fetchone()[0] == 0:
                for item in EDUCATION_SEED:
                    cur.execute(
                        """
                        INSERT INTO portfolio_education (id, degree, institution, duration, details, display_order, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (item["id"], item["degree"], item["institution"], item["duration"], item["details"], item["display_order"], now)
                    )

            # 6. Certifications
            cur.execute("SELECT count(*) FROM portfolio_certifications")
            if cur.fetchone()[0] == 0:
                for item in CERTIFICATIONS_SEED:
                    cur.execute(
                        """
                        INSERT INTO portfolio_certifications (id, name, issuer, issue_date, credential_id, display_order, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (item["id"], item["name"], item["issuer"], item["issue_date"], item["credential_id"], item["display_order"], now)
                    )

            # 7. Contact
            cur.execute("SELECT 1 FROM portfolio_contact WHERE id = ?", (CONTACT_SEED["id"],))
            if not cur.fetchone():
                cur.execute(
                    """
                    INSERT INTO portfolio_contact (id, email, linkedin, github, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (CONTACT_SEED["id"], CONTACT_SEED["email"], CONTACT_SEED["linkedin"], CONTACT_SEED["github"], now)
                )

            # 8. Bootstrap Ownership Record if empty
            cur.execute("SELECT count(*) FROM ownership WHERE cluster_id = ?", (self.cluster_id,))
            if cur.fetchone()[0] == 0:
                expires_at = now + 86400.0
                bootstrap_sig = sign_ownership_record(
                    cluster_id=self.cluster_id,
                    owner_node_id="laptop",
                    epoch=1,
                    lease_id="bootstrap-lease-01",
                    lease_expires_at=expires_at,
                    granted_by="bootstrap",
                    secret=self.secret
                )
                cur.execute(
                    """
                    INSERT INTO ownership (
                        cluster_id, owner_node_id, epoch, lease_id, lease_expires_at, granted_by, signature, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (self.cluster_id, "laptop", 1, "bootstrap-lease-01", expires_at, "bootstrap", bootstrap_sig, now)
                )

            conn.commit()
        finally:
            conn.close()

    # --- Read Queries ---
    def get_profile(self) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM portfolio_profile LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_skills(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM portfolio_skills ORDER BY display_order ASC")
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["items"] = json.loads(d["items"])
                except Exception:
                    pass
                result.append(d)
            return result
        finally:
            conn.close()

    def get_projects(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM portfolio_projects ORDER BY display_order ASC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_experience(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM portfolio_experience ORDER BY display_order ASC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_education(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM portfolio_education ORDER BY display_order ASC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_certifications(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM portfolio_certifications ORDER BY display_order ASC")
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def get_contact(self) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT email, linkedin, github, updated_at FROM portfolio_contact LIMIT 1")
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # --- Ownership & Lease Operations ---
    def set_ownership(self, record: OwnershipRecord):
        """Persist ownership record atomically."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            now = time.time()
            cur.execute(
                """
                INSERT INTO ownership (
                    cluster_id, owner_node_id, epoch, lease_id, lease_expires_at, granted_by, signature, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    owner_node_id = excluded.owner_node_id,
                    epoch = excluded.epoch,
                    lease_id = excluded.lease_id,
                    lease_expires_at = excluded.lease_expires_at,
                    granted_by = excluded.granted_by,
                    signature = excluded.signature,
                    updated_at = excluded.updated_at;
                """,
                (
                    record.cluster_id,
                    record.owner_node_id,
                    record.epoch,
                    record.lease_id,
                    record.lease_expires_at,
                    record.granted_by,
                    record.signature,
                    now
                )
            )
            conn.commit()
        finally:
            conn.close()

    def get_ownership(self, cluster_id: Optional[str] = None) -> Optional[OwnershipRecord]:
        """Retrieve active ownership record."""
        target_cluster = cluster_id or self.cluster_id
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT cluster_id, owner_node_id, epoch, lease_id, lease_expires_at, granted_by, signature, updated_at
                FROM ownership
                WHERE cluster_id = ?
                """,
                (target_cluster,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return OwnershipRecord(
                cluster_id=row["cluster_id"],
                owner_node_id=row["owner_node_id"],
                epoch=row["epoch"],
                lease_id=row["lease_id"],
                lease_expires_at=row["lease_expires_at"],
                granted_by=row["granted_by"],
                signature=row["signature"],
                updated_at=row["updated_at"]
            )
        finally:
            conn.close()

    # --- Protected Transactional Outbox Write Path ---
    def protected_write(
        self,
        origin_node_id: str,
        origin_epoch: int,
        entity_type: str,
        entity_id: str,
        operation: str,
        payload: Dict[str, Any],
        execute_data_change: Callable[[sqlite3.Cursor], None],
        is_primary: bool,
        op_id: Optional[str] = None,
        cluster_id: Optional[str] = None,
        secret: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Executes data modification and outbox insertion in the SAME transaction.
        Enforces genuine ownership write guard: valid lease, current epoch, owner equals this node.
        Rejects expired leases and stale epochs.
        """
        if not is_primary:
            return False, "FORBIDDEN", "Protected write rejected: node is not primary writer", None

        now = time.time()
        c_id = cluster_id or self.cluster_id
        sec = secret or self.secret

        # Enforce Ownership Write Guard
        record = self.get_ownership(c_id)
        valid, lease_err = validate_lease(
            record=record,
            node_id=origin_node_id,
            expected_epoch=origin_epoch,
            expected_cluster_id=c_id,
            secret=sec,
            now=now,
            max_clock_skew=1.0,
            witness_secret=self.witness_secret
        )
        if not valid:
            return False, "FORBIDDEN", f"Write guard rejected: {lease_err}", None

        op_id = op_id or uuid.uuid4().hex
        payload_str = json.dumps(payload)

        conn = self.get_connection()
        try:
            cur = conn.cursor()
            # 1. Execute entity change
            execute_data_change(cur)

            # 2. Compute next monotonic sequence number for this origin node
            cur.execute(
                "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM change_log WHERE origin_node_id = ?",
                (origin_node_id,)
            )
            seq_num = cur.fetchone()[0]

            # 3. Insert outbox row in the SAME transaction
            cur.execute(
                """
                INSERT INTO change_log (
                    operation_id, sequence_number, origin_node_id, origin_epoch,
                    schema_version, entity_type, entity_id, operation, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (op_id, seq_num, origin_node_id, origin_epoch, 1, entity_type, entity_id, operation, payload_str, now)
            )

            conn.commit()
            return True, None, None, op_id
        except Exception as e:
            conn.rollback()
            return False, "INTERNAL_ERROR", f"Transaction failed: {str(e)}", None
        finally:
            conn.close()

    def submit_inquiry(
        self,
        origin_node_id: str,
        origin_epoch: int,
        name: str,
        email: str,
        subject: str,
        message: str,
        is_primary: bool,
        op_id: Optional[str] = None,
        cluster_id: Optional[str] = None,
        secret: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """Transactional user contact submission that writes to change_log outbox."""
        op_id = op_id or uuid.uuid4().hex
        now = time.time()
        payload = {
            "id": op_id,
            "name": name,
            "email": email,
            "subject": subject,
            "message": message,
            "created_at": now
        }

        def _do_insert(cur: sqlite3.Cursor):
            cur.execute(
                """
                INSERT INTO portfolio_inquiries (id, name, email, subject, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (op_id, name, email, subject, message, now)
            )

        return self.protected_write(
            origin_node_id=origin_node_id,
            origin_epoch=origin_epoch,
            entity_type="inquiry",
            entity_id=op_id,
            operation="upsert",
            payload=payload,
            execute_data_change=_do_insert,
            is_primary=is_primary,
            op_id=op_id,
            cluster_id=cluster_id,
            secret=secret
        )

    def get_inquiries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent portfolio inquiries."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, name, email, subject, message, created_at
                FROM portfolio_inquiries
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # --- Audit Events ---
    def log_audit_event(
        self,
        event_id: str,
        node_id: str,
        epoch: int,
        event_type: str,
        severity: str = "INFO",
        details: Optional[Dict[str, Any]] = None
    ):
        now = time.time()
        details_str = json.dumps(details) if details else None
        conn = self.get_connection()
        try:
            conn.execute(
                """
                INSERT INTO audit_events (event_id, timestamp, node_id, epoch, event_type, severity, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, now, node_id, epoch, event_type, severity, details_str)
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_audit_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT event_id, timestamp, node_id, epoch, event_type, severity, details
                FROM audit_events
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,)
            )
            rows = cur.fetchall()
            events = []
            for r in rows:
                details = None
                if r["details"]:
                    try:
                        details = json.loads(r["details"])
                    except Exception:
                        details = r["details"]
                events.append({
                    "event_id": r["event_id"],
                    "timestamp": r["timestamp"],
                    "node_id": r["node_id"],
                    "epoch": r["epoch"],
                    "event_type": r["event_type"],
                    "severity": r["severity"],
                    "details": details
                })
            return events
        finally:
            conn.close()

    # --- Conflict Records & Integrity Hash ---

    def record_conflict(
        self,
        entity_type: str,
        entity_id: str,
        origin_node_id: str,
        local_data: Dict[str, Any],
        remote_data: Dict[str, Any],
        resolution_notes: Optional[str] = None
    ) -> str:
        """Record divergent write in conflict_records table."""
        conflict_id = uuid.uuid4().hex
        now = time.time()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO conflict_records (
                    conflict_id, entity_type, entity_id, origin_node_id,
                    local_data, remote_data, detected_at, resolved, resolution_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    conflict_id, entity_type, entity_id, origin_node_id,
                    json.dumps(local_data), json.dumps(remote_data), now, resolution_notes
                )
            )
            conn.commit()
            return conflict_id
        finally:
            conn.close()

    def get_conflicts(self, resolved: Optional[bool] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recorded conflict events."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if resolved is None:
                cur.execute(
                    """
                    SELECT conflict_id, entity_type, entity_id, origin_node_id,
                           local_data, remote_data, detected_at, resolved, resolution_notes
                    FROM conflict_records
                    ORDER BY detected_at DESC
                    LIMIT ?
                    """,
                    (limit,)
                )
            else:
                cur.execute(
                    """
                    SELECT conflict_id, entity_type, entity_id, origin_node_id,
                           local_data, remote_data, detected_at, resolved, resolution_notes
                    FROM conflict_records
                    WHERE resolved = ?
                    ORDER BY detected_at DESC
                    LIMIT ?
                    """,
                    (1 if resolved else 0, limit)
                )
            rows = cur.fetchall()
            conflicts = []
            for r in rows:
                c = dict(r)
                if isinstance(c["local_data"], str):
                    try:
                        c["local_data"] = json.loads(c["local_data"])
                    except Exception:
                        pass
                if isinstance(c["remote_data"], str):
                    try:
                        c["remote_data"] = json.loads(c["remote_data"])
                    except Exception:
                        pass
                conflicts.append(c)
            return conflicts
        finally:
            conn.close()

    def get_canonical_hash(self, table_name: str = "portfolio_inquiries") -> str:
        """Compute deterministic SHA256 hash of table contents."""
        import hashlib
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if table_name == "portfolio_inquiries":
                cur.execute(
                    """
                    SELECT id, name, email, subject, message
                    FROM portfolio_inquiries
                    ORDER BY id ASC
                    """
                )
                rows = [
                    {"id": r["id"], "name": r["name"], "email": r["email"], "subject": r["subject"], "message": r["message"]}
                    for r in cur.fetchall()
                ]
            elif table_name == "change_log":
                cur.execute(
                    """
                    SELECT operation_id, sequence_number, origin_node_id, origin_epoch
                    FROM change_log
                    ORDER BY sequence_number ASC
                    """
                )
                rows = [dict(r) for r in cur.fetchall()]
            else:
                raise ValueError(f"Untrusted or unsupported table for hash: {table_name}")
            serialized = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode("utf-8")
            return hashlib.sha256(serialized).hexdigest()
        finally:
            conn.close()

    # --- Replication & Checkpoint Operations ---

    def get_replication_checkpoint(self, peer_node_id: str) -> Dict[str, Any]:
        """Fetch replication checkpoint for given peer node."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT peer_node_id, last_applied_sequence, last_applied_operation_id, last_applied_at, updated_at
                FROM replication_checkpoint
                WHERE peer_node_id = ?
                """,
                (peer_node_id,)
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            return {
                "peer_node_id": peer_node_id,
                "last_applied_sequence": 0,
                "last_applied_operation_id": None,
                "last_applied_at": 0.0,
                "updated_at": 0.0
            }
        finally:
            conn.close()

    def get_unreplicated_changes(self, peer_node_id: str, from_sequence: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get committed local changes that have sequence > peer's last applied sequence."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if from_sequence is not None:
                last_seq = from_sequence
            else:
                cur.execute(
                    "SELECT last_applied_sequence FROM replication_checkpoint WHERE peer_node_id = ?",
                    (f"ack_{peer_node_id}",)
                )
                row = cur.fetchone()
                last_seq = row[0] if row else 0

            cur.execute(
                """
                SELECT operation_id, sequence_number, origin_node_id, origin_epoch,
                       schema_version, entity_type, entity_id, operation, payload, created_at
                FROM change_log
                WHERE origin_node_id != ? AND sequence_number > ?
                ORDER BY sequence_number ASC
                LIMIT ?
                """,
                (peer_node_id, last_seq, limit)
            )
            rows = cur.fetchall()
            events = []
            for r in rows:
                ev = dict(r)
                if isinstance(ev["payload"], str):
                    try:
                        ev["payload"] = json.loads(ev["payload"])
                    except Exception:
                        pass
                events.append(ev)
            return events
        finally:
            conn.close()

    def get_pending_replication_events(self, origin_node_id: Optional[str] = None, from_sequence: int = 1, limit: int = 50) -> List[Dict[str, Any]]:
        """Query change_log events by origin node and sequence number."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if origin_node_id:
                cur.execute(
                    """
                    SELECT operation_id, sequence_number, origin_node_id, origin_epoch,
                           schema_version, entity_type, entity_id, operation, payload, created_at
                    FROM change_log
                    WHERE origin_node_id = ? AND sequence_number >= ?
                    ORDER BY sequence_number ASC
                    LIMIT ?
                    """,
                    (origin_node_id, from_sequence, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT operation_id, sequence_number, origin_node_id, origin_epoch,
                           schema_version, entity_type, entity_id, operation, payload, created_at
                    FROM change_log
                    WHERE sequence_number >= ?
                    ORDER BY sequence_number ASC
                    LIMIT ?
                    """,
                    (from_sequence, limit)
                )
            rows = cur.fetchall()
            events = []
            for r in rows:
                ev = dict(r)
                if isinstance(ev["payload"], str):
                    try:
                        ev["payload"] = json.loads(ev["payload"])
                    except Exception:
                        pass
                events.append(ev)
            return events
        finally:
            conn.close()

    def record_peer_ack(self, peer_node_id: str, acked_sequence: int, operation_id: Optional[str] = None):
        """Record the sequence number that the peer has acknowledged applying."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            now = time.time()
            cur.execute(
                """
                INSERT INTO replication_checkpoint (peer_node_id, last_applied_sequence, last_applied_operation_id, last_applied_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(peer_node_id) DO UPDATE SET
                    last_applied_sequence = MAX(replication_checkpoint.last_applied_sequence, excluded.last_applied_sequence),
                    last_applied_operation_id = COALESCE(excluded.last_applied_operation_id, replication_checkpoint.last_applied_operation_id),
                    updated_at = excluded.updated_at;
                """,
                (f"ack_{peer_node_id}", acked_sequence, operation_id, now, now)
            )
            conn.commit()
        finally:
            conn.close()

    def get_highest_local_sequence(self, origin_node_id: str) -> int:
        """Return highest committed sequence number for given origin."""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(sequence_number), 0) FROM change_log WHERE origin_node_id = ?", (origin_node_id,))
            return cur.fetchone()[0]
        finally:
            conn.close()

    def create_database_backup(self, backup_dir: Optional[str] = None) -> str:
        """Create a consistent physical database backup before any destructive operation."""
        import shutil
        if not backup_dir:
            backup_dir = os.path.join(os.path.dirname(self.db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        timestamp_str = str(int(time.time()))
        backup_file = os.path.join(backup_dir, f"backup_phone_{timestamp_str}.db")

        # Use SQLite backup API for 100% online consistency
        src_conn = self.get_connection()
        dst_conn = sqlite3.connect(backup_file)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()
        return backup_file

    def get_full_snapshot(self) -> Dict[str, Any]:
        """Produce full data snapshot for resync / initial snapshot."""
        return {
            "profile": self.get_profile(),
            "skills": self.get_skills(),
            "projects": self.get_projects(),
            "experience": self.get_experience(),
            "education": self.get_education(),
            "certifications": self.get_certifications(),
            "contact": self.get_contact(),
            "snapshot_timestamp": time.time()
        }

    def apply_replication_batch(
        self,
        origin_node_id: str,
        batch_id: str,
        events: List[Dict[str, Any]]
    ) -> Tuple[bool, int, int, List[int], bool, Optional[str]]:
        """
        Transactional apply algorithm.
        Executes sequence continuity check, deduplication by operation_id,
        conflict preservation, parameterized SQL mutation, and checkpoint update
        in ONE single atomic transaction.
        """
        from shared.replication import detect_sequence_gap

        now = time.time()
        conn = self.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.cursor()

            # 1. Fetch current checkpoint
            cur.execute(
                "SELECT last_applied_sequence FROM replication_checkpoint WHERE peer_node_id = ?",
                (origin_node_id,)
            )
            row = cur.fetchone()
            last_applied_seq = row[0] if row else 0

            # 2. Filter out already applied events (idempotence)
            duplicate_count = 0
            new_events = []
            for ev in events:
                if ev["sequence_number"] <= last_applied_seq:
                    duplicate_count += 1
                else:
                    new_events.append(ev)

            # If all events were already applied, acknowledge prior state
            if not new_events:
                conn.commit()
                return True, last_applied_seq, duplicate_count, [], False, None

            # 3. Detect sequence gaps or out-of-order delivery
            has_gap, missing = detect_sequence_gap(last_applied_seq, new_events)
            if has_gap:
                conn.rollback()
                return False, last_applied_seq, duplicate_count, missing, True, "Sequence gap detected"

            # 4. Apply each event
            current_seq = last_applied_seq
            last_op_id = None

            for ev in new_events:
                op_id = ev["operation_id"]
                seq_num = ev["sequence_number"]
                entity_type = ev["entity_type"]
                entity_id = ev["entity_id"]
                operation = ev["operation"]
                payload = ev["payload"]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        pass

                # Check if operation_id already applied previously
                cur.execute("SELECT 1 FROM change_log WHERE operation_id = ?", (op_id,))
                if cur.fetchone():
                    duplicate_count += 1
                    current_seq = seq_num
                    last_op_id = op_id
                    continue

                # Conflict Detection & Preservation
                # Check if local record exists and differs
                if entity_type == "inquiry":
                    cur.execute("SELECT * FROM portfolio_inquiries WHERE id = ?", (entity_id,))
                    local_row = cur.fetchone()
                    if local_row:
                        local_dict = dict(local_row)
                        if local_dict.get("message") != payload.get("message"):
                            conflict_id = uuid.uuid4().hex
                            cur.execute(
                                """
                                INSERT INTO conflict_records (conflict_id, entity_type, entity_id, origin_node_id, local_data, remote_data, detected_at, resolved)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                                """,
                                (conflict_id, entity_type, entity_id, origin_node_id, json.dumps(local_dict), json.dumps(payload), now)
                            )

                    # Apply mutation
                    if operation == "upsert":
                        cur.execute(
                            """
                            INSERT INTO portfolio_inquiries (id, name, email, subject, message, created_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(id) DO UPDATE SET
                                name = excluded.name,
                                email = excluded.email,
                                subject = excluded.subject,
                                message = excluded.message
                            """,
                            (
                                payload.get("id", entity_id),
                                payload.get("name", ""),
                                payload.get("email", ""),
                                payload.get("subject", ""),
                                payload.get("message", ""),
                                payload.get("created_at", now)
                            )
                        )
                    elif operation == "delete":
                        cur.execute("DELETE FROM portfolio_inquiries WHERE id = ?", (entity_id,))

                elif entity_type == "profile":
                    if operation == "upsert":
                        cur.execute(
                            """
                            INSERT INTO portfolio_profile (id, name, headline, bio_primary, bio_secondary, cta_text, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(id) DO UPDATE SET
                                name = excluded.name,
                                headline = excluded.headline,
                                bio_primary = excluded.bio_primary,
                                bio_secondary = excluded.bio_secondary,
                                cta_text = excluded.cta_text,
                                updated_at = excluded.updated_at
                            """,
                            (
                                payload.get("id", entity_id),
                                payload.get("name", ""),
                                payload.get("headline", ""),
                                payload.get("bio_primary", ""),
                                payload.get("bio_secondary", ""),
                                payload.get("cta_text", ""),
                                payload.get("updated_at", now)
                            )
                        )
                else:
                    raise ValueError(f"Unsupported entity_type for replication: {entity_type}")

                # Record in change_log for local audit and subsequent recovery
                cur.execute(
                    """
                    INSERT INTO change_log (
                        operation_id, sequence_number, origin_node_id, origin_epoch,
                        schema_version, entity_type, entity_id, operation, payload, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        op_id, seq_num, origin_node_id, ev.get("origin_epoch", 1),
                        ev.get("schema_version", 1), entity_type, entity_id,
                        operation, json.dumps(payload), ev.get("created_at", now)
                    )
                )

                current_seq = seq_num
                last_op_id = op_id

            # 5. Advance checkpoint
            cur.execute(
                """
                INSERT INTO replication_checkpoint (peer_node_id, last_applied_sequence, last_applied_operation_id, last_applied_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(peer_node_id) DO UPDATE SET
                    last_applied_sequence = excluded.last_applied_sequence,
                    last_applied_operation_id = excluded.last_applied_operation_id,
                    last_applied_at = excluded.last_applied_at,
                    updated_at = excluded.updated_at
                """,
                (origin_node_id, current_seq, last_op_id, now, now)
            )

            conn.commit()
            return True, current_seq, duplicate_count, [], False, None
        except Exception as e:
            conn.rollback()
            return False, last_applied_seq, 0, [], False, f"Replication transaction failed: {str(e)}"
        finally:
            conn.close()
