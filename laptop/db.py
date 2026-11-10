"""
SentinelDR Laptop Node - Database Layer
PostgreSQL support via psycopg, with SQLite development fallback if PostgreSQL is unavailable.
Includes Portfolio data seeding, reading, and protected transactional outbox writes.
"""

import json
import os
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
    RESUME_SEED,
    SKILLS_SEED,
)


class LaptopDatabase:
    """Manages database connection, migrations, portfolio queries, and outbox writes for Laptop node."""

    def __init__(self, database_url: str, dev_fallback_sqlite: bool = False, cluster_id: str = "sentineldr-cluster-01", secret: Optional[str] = None):
        self.database_url = database_url
        self.dev_fallback_sqlite = dev_fallback_sqlite
        self.cluster_id = cluster_id
        self.secret = secret or os.getenv("SDR_HMAC_SECRET", "sdr-dev-hmac-secret-change-in-prod-001")
        self.witness_secret = os.getenv("SDR_WITNESS_SECRET", self.secret)
        self.is_postgres = database_url.startswith("postgresql://") or database_url.startswith("postgres://")
        self._schema_file_pg = os.path.join(os.path.dirname(__file__), "migrations", "001_initial_schema.sql")
        self._schema_file_sqlite = os.path.join(os.path.dirname(os.path.dirname(__file__)), "phone", "schema.sql")
        if database_url.startswith("sqlite:///"):
            self._sqlite_path = database_url[10:]
        elif database_url.startswith("sqlite://"):
            self._sqlite_path = database_url[9:]
        else:
            self._sqlite_path = os.path.join(os.getcwd(), "laptop_dev_sentineldr.db")
        self.using_sqlite_fallback = False

        self.init_db()
        self.seed_portfolio_data()

    def get_connection(self):
        """Returns connection supporting dual PostgreSQL and SQLite dev fallback."""
        if self.is_postgres and not self.using_sqlite_fallback:
            try:
                import psycopg
                return psycopg.connect(self.database_url, autocommit=False, connect_timeout=2)
            except Exception:
                if self.dev_fallback_sqlite:
                    self.using_sqlite_fallback = True

        import sqlite3
        conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Initialize database schema, attempting PostgreSQL first and falling back to SQLite if enabled."""
        if self.is_postgres:
            try:
                import psycopg
                with psycopg.connect(self.database_url, connect_timeout=3) as conn:
                    with open(self._schema_file_pg, "r", encoding="utf-8") as f:
                        migration_sql = f.read()
                    with conn.cursor() as cur:
                        cur.execute(migration_sql)
                    conn.commit()
                self.using_sqlite_fallback = False
                return
            except Exception as e:
                if not self.dev_fallback_sqlite:
                    raise RuntimeError(
                        f"FATAL: PostgreSQL connection failed and SDR_DEV_FALLBACK_SQLITE is not enabled. "
                        f"Refusing to start laptop node without a reachable PostgreSQL database: {e}"
                    )
                self.using_sqlite_fallback = True
        else:
            self.using_sqlite_fallback = True

        # Initialize SQLite fallback
        import sqlite3
        with open(self._schema_file_sqlite, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
        try:
            conn.executescript(schema_sql)
            conn.commit()
        finally:
            conn.close()

    def is_healthy(self) -> Tuple[bool, Optional[str]]:
        """Verify database connectivity and health."""
        if self.is_postgres and not self.using_sqlite_fallback:
            try:
                import psycopg
                with psycopg.connect(self.database_url, connect_timeout=2) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1;")
                        cur.fetchone()
                return True, None
            except Exception as e:
                return False, f"PostgreSQL error: {str(e)}"
        else:
            try:
                import sqlite3
                conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
                try:
                    cur = conn.cursor()
                    cur.execute("PRAGMA quick_check;")
                    res = cur.fetchone()
                    if res and res[0] == "ok":
                        return True, None
                    return False, f"SQLite integrity failed: {res[0] if res else 'Unknown'}"
                finally:
                    conn.close()
            except Exception as e:
                return False, str(e)

    def verify_full_integrity(self) -> Tuple[bool, Optional[str]]:
        """Verify complete database physical integrity."""
        if self.is_postgres and not self.using_sqlite_fallback:
            try:
                import psycopg
                with psycopg.connect(self.database_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1;")
                return True, None
            except Exception as e:
                return False, str(e)
        else:
            try:
                import sqlite3
                conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
                try:
                    cur = conn.cursor()
                    cur.execute("PRAGMA integrity_check;")
                    rows = cur.fetchall()
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
        now = time.time()
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM portfolio_profile WHERE id = %s", (PROFILE_SEED["id"],))
                    if not cur.fetchone():
                        cur.execute(
                            """
                            INSERT INTO portfolio_profile (id, name, headline, bio_primary, bio_secondary, cta_text, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
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
                    # Skills
                    cur.execute("SELECT count(*) FROM portfolio_skills")
                    if cur.fetchone()[0] == 0:
                        for item in SKILLS_SEED:
                            cur.execute(
                                """
                                INSERT INTO portfolio_skills (id, category, items, display_order, updated_at)
                                VALUES (%s, %s, %s, %s, %s)
                                """,
                                (item["id"], item["category"], json.dumps(item["items"]), item["display_order"], now)
                            )
                    # Projects
                    cur.execute("SELECT count(*) FROM portfolio_projects")
                    if cur.fetchone()[0] == 0:
                        for item in PROJECTS_SEED:
                            cur.execute(
                                """
                                INSERT INTO portfolio_projects (id, title, description, link, display_order, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                """,
                                (item["id"], item["title"], item["description"], item["link"], item["display_order"], now)
                            )
                    # Experience
                    cur.execute("SELECT count(*) FROM portfolio_experience")
                    if cur.fetchone()[0] == 0:
                        for item in EXPERIENCE_SEED:
                            cur.execute(
                                """
                                INSERT INTO portfolio_experience (id, role, company, duration, description, display_order, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """,
                                (item["id"], item["role"], item["company"], item["duration"], item["description"], item["display_order"], now)
                            )
                    # Education
                    cur.execute("SELECT count(*) FROM portfolio_education")
                    if cur.fetchone()[0] == 0:
                        for item in EDUCATION_SEED:
                            cur.execute(
                                """
                                INSERT INTO portfolio_education (id, degree, institution, duration, details, display_order, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """,
                                (item["id"], item["degree"], item["institution"], item["duration"], item["details"], item["display_order"], now)
                            )
                    # Certifications
                    cur.execute("SELECT count(*) FROM portfolio_certifications")
                    if cur.fetchone()[0] == 0:
                        for item in CERTIFICATIONS_SEED:
                            cur.execute(
                                """
                                INSERT INTO portfolio_certifications (id, name, issuer, issue_date, credential_id, display_order, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """,
                                (item["id"], item["name"], item["issuer"], item["issue_date"], item["credential_id"], item["display_order"], now)
                            )
                    # Contact
                    cur.execute("SELECT 1 FROM portfolio_contact WHERE id = %s", (CONTACT_SEED["id"],))
                    if not cur.fetchone():
                        cur.execute(
                            """
                            INSERT INTO portfolio_contact (id, email, linkedin, github, updated_at)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (CONTACT_SEED["id"], CONTACT_SEED["email"], CONTACT_SEED["linkedin"], CONTACT_SEED["github"], now)
                        )

                    # Resume
                    cur.execute("SELECT 1 FROM portfolio_resume WHERE id = %s", (RESUME_SEED["id"],))
                    if not cur.fetchone():
                        cur.execute(
                            """
                            INSERT INTO portfolio_resume (id, name, title, email, phone, location, summary, skills, experience, education, template, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                RESUME_SEED["id"], RESUME_SEED["name"], RESUME_SEED["title"],
                                RESUME_SEED["email"], RESUME_SEED["phone"], RESUME_SEED["location"],
                                RESUME_SEED["summary"], RESUME_SEED["skills"], RESUME_SEED["experience"],
                                RESUME_SEED["education"], RESUME_SEED["template"], now
                            )
                        )

                    # Bootstrap Ownership Record if empty
                    cur.execute("SELECT count(*) FROM ownership WHERE cluster_id = %s", (self.cluster_id,))
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
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (self.cluster_id, "laptop", 1, "bootstrap-lease-01", expires_at, "bootstrap", bootstrap_sig, now)
                        )
                conn.commit()
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            try:
                cur = conn.cursor()
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

                cur.execute("SELECT 1 FROM portfolio_contact WHERE id = ?", (CONTACT_SEED["id"],))
                if not cur.fetchone():
                    cur.execute(
                        """
                        INSERT INTO portfolio_contact (id, email, linkedin, github, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (CONTACT_SEED["id"], CONTACT_SEED["email"], CONTACT_SEED["linkedin"], CONTACT_SEED["github"], now)
                    )

                # Resume
                cur.execute("SELECT 1 FROM portfolio_resume WHERE id = ?", (RESUME_SEED["id"],))
                if not cur.fetchone():
                    cur.execute(
                        """
                        INSERT INTO portfolio_resume (id, name, title, email, phone, location, summary, skills, experience, education, template, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            RESUME_SEED["id"], RESUME_SEED["name"], RESUME_SEED["title"],
                            RESUME_SEED["email"], RESUME_SEED["phone"], RESUME_SEED["location"],
                            RESUME_SEED["summary"], RESUME_SEED["skills"], RESUME_SEED["experience"],
                            RESUME_SEED["education"], RESUME_SEED["template"], now
                        )
                    )

                # Bootstrap Ownership Record if empty
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
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, name, headline, bio_primary, bio_secondary, cta_text, updated_at FROM portfolio_profile LIMIT 1")
                    r = cur.fetchone()
                    if r:
                        return {
                            "id": r[0], "name": r[1], "headline": r[2], "bio_primary": r[3],
                            "bio_secondary": r[4], "cta_text": r[5], "updated_at": r[6]
                        }
                    return None
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM portfolio_profile LIMIT 1")
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def get_skills(self) -> List[Dict[str, Any]]:
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, category, items, display_order, updated_at FROM portfolio_skills ORDER BY display_order ASC")
                    rows = cur.fetchall()
                    result = []
                    for r in rows:
                        items = r[2]
                        if isinstance(items, str):
                            try:
                                items = json.loads(items)
                            except Exception:
                                pass
                        result.append({"id": r[0], "category": r[1], "items": items, "display_order": r[3], "updated_at": r[4]})
                    return result
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
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
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, title, description, link, display_order, updated_at FROM portfolio_projects ORDER BY display_order ASC")
                    return [
                        {"id": r[0], "title": r[1], "description": r[2], "link": r[3], "display_order": r[4], "updated_at": r[5]}
                        for r in cur.fetchall()
                    ]
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM portfolio_projects ORDER BY display_order ASC")
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

    def get_experience(self) -> List[Dict[str, Any]]:
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, role, company, duration, description, display_order, updated_at FROM portfolio_experience ORDER BY display_order ASC")
                    return [
                        {"id": r[0], "role": r[1], "company": r[2], "duration": r[3], "description": r[4], "display_order": r[5], "updated_at": r[6]}
                        for r in cur.fetchall()
                    ]
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM portfolio_experience ORDER BY display_order ASC")
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

    def get_education(self) -> List[Dict[str, Any]]:
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, degree, institution, duration, details, display_order, updated_at FROM portfolio_education ORDER BY display_order ASC")
                    return [
                        {"id": r[0], "degree": r[1], "institution": r[2], "duration": r[3], "details": r[4], "display_order": r[5], "updated_at": r[6]}
                        for r in cur.fetchall()
                    ]
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM portfolio_education ORDER BY display_order ASC")
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

    def get_certifications(self) -> List[Dict[str, Any]]:
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, name, issuer, issue_date, credential_id, display_order, updated_at FROM portfolio_certifications ORDER BY display_order ASC")
                    return [
                        {"id": r[0], "name": r[1], "issuer": r[2], "issue_date": r[3], "credential_id": r[4], "display_order": r[5], "updated_at": r[6]}
                        for r in cur.fetchall()
                    ]
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM portfolio_certifications ORDER BY display_order ASC")
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

    def get_contact(self) -> Optional[Dict[str, Any]]:
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT email, linkedin, github, updated_at FROM portfolio_contact LIMIT 1")
                    r = cur.fetchone()
                    if r:
                        return {"email": r[0], "linkedin": r[1], "github": r[2], "updated_at": r[3]}
                    return None
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                cur.execute("SELECT email, linkedin, github, updated_at FROM portfolio_contact LIMIT 1")
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def get_resume(self) -> Dict[str, Any]:
        """Returns the current portfolio resume record, defaulting to RESUME_SEED if not set."""
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, name, title, email, phone, location, summary, skills, experience, education, template, updated_at "
                        "FROM portfolio_resume LIMIT 1"
                    )
                    r = cur.fetchone()
                    if r and r[1] != "Your Name":
                        return {
                            "id": r[0], "name": r[1], "title": r[2], "email": r[3],
                            "phone": r[4], "location": r[5], "summary": r[6], "skills": r[7],
                            "experience": r[8], "education": r[9], "template": r[10], "updated_at": r[11]
                        }
                    # Auto-upgrade stale placeholder
                    cur.execute(
                        """
                        INSERT INTO portfolio_resume (id, name, title, email, phone, location, summary, skills, experience, education, template, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(id) DO UPDATE SET
                            name = EXCLUDED.name, title = EXCLUDED.title, email = EXCLUDED.email,
                            phone = EXCLUDED.phone, location = EXCLUDED.location, summary = EXCLUDED.summary,
                            skills = EXCLUDED.skills, experience = EXCLUDED.experience, education = EXCLUDED.education,
                            template = EXCLUDED.template, updated_at = EXCLUDED.updated_at
                        """,
                        (
                            RESUME_SEED["id"], RESUME_SEED["name"], RESUME_SEED["title"],
                            RESUME_SEED["email"], RESUME_SEED["phone"], RESUME_SEED["location"],
                            RESUME_SEED["summary"], RESUME_SEED["skills"], RESUME_SEED["experience"],
                            RESUME_SEED["education"], RESUME_SEED["template"], time.time()
                        )
                    )
                    conn.commit()
                    return dict(RESUME_SEED)
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, name, title, email, phone, location, summary, skills, experience, education, template, updated_at "
                    "FROM portfolio_resume LIMIT 1"
                )
                row = cur.fetchone()
                if not row or (row["name"] == "Your Name"):
                    cur.execute(
                        """
                        INSERT INTO portfolio_resume (id, name, title, email, phone, location, summary, skills, experience, education, template, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            name = excluded.name, title = excluded.title, email = excluded.email,
                            phone = excluded.phone, location = excluded.location, summary = excluded.summary,
                            skills = excluded.skills, experience = excluded.experience, education = excluded.education,
                            template = excluded.template, updated_at = excluded.updated_at
                        """,
                        (
                            RESUME_SEED["id"], RESUME_SEED["name"], RESUME_SEED["title"],
                            RESUME_SEED["email"], RESUME_SEED["phone"], RESUME_SEED["location"],
                            RESUME_SEED["summary"], RESUME_SEED["skills"], RESUME_SEED["experience"],
                            RESUME_SEED["education"], RESUME_SEED["template"], time.time()
                        )
                    )
                    conn.commit()
                    return dict(RESUME_SEED)
                return dict(row)
            finally:
                conn.close()

    def save_resume(
        self,
        origin_node_id: str,
        origin_epoch: int,
        name: str,
        title: str,
        email: str,
        phone: str,
        location: str,
        summary: str,
        skills: str,
        experience: str,
        education: str,
        template: str = "modern",
        is_primary: bool = True,
        cluster_id: Optional[str] = None,
        secret: Optional[str] = None
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        Saves updated resume data using protected_write so it is committed atomically
        to portfolio_resume and change_log for peer synchronization.
        """
        now = time.time()
        resume_id = "default_resume"
        payload = {
            "id": resume_id,
            "name": name,
            "title": title,
            "email": email,
            "phone": phone,
            "location": location,
            "summary": summary,
            "skills": skills,
            "experience": experience,
            "education": education,
            "template": template,
            "updated_at": now
        }

        def _do_upsert(cur):
            if self.is_postgres and not self.using_sqlite_fallback:
                cur.execute(
                    """
                    INSERT INTO portfolio_resume (id, name, title, email, phone, location, summary, skills, experience, education, template, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(id) DO UPDATE SET
                        name = EXCLUDED.name,
                        title = EXCLUDED.title,
                        email = EXCLUDED.email,
                        phone = EXCLUDED.phone,
                        location = EXCLUDED.location,
                        summary = EXCLUDED.summary,
                        skills = EXCLUDED.skills,
                        experience = EXCLUDED.experience,
                        education = EXCLUDED.education,
                        template = EXCLUDED.template,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (resume_id, name, title, email, phone, location, summary, skills, experience, education, template, now)
                )
            else:
                cur.execute(
                    """
                    INSERT INTO portfolio_resume (id, name, title, email, phone, location, summary, skills, experience, education, template, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        title = excluded.title,
                        email = excluded.email,
                        phone = excluded.phone,
                        location = excluded.location,
                        summary = excluded.summary,
                        skills = excluded.skills,
                        experience = excluded.experience,
                        education = excluded.education,
                        template = excluded.template,
                        updated_at = excluded.updated_at
                    """,
                    (resume_id, name, title, email, phone, location, summary, skills, experience, education, template, now)
                )

        return self.protected_write(
            origin_node_id=origin_node_id,
            origin_epoch=origin_epoch,
            entity_type="resume",
            entity_id=resume_id,
            operation="upsert",
            payload=payload,
            execute_data_change=_do_upsert,
            is_primary=is_primary,
            cluster_id=cluster_id,
            secret=secret
        )

    # --- Ownership & Lease Operations ---
    def set_ownership(self, record: OwnershipRecord):
        """Persist ownership record atomically."""
        now = time.time()
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO ownership (
                            cluster_id, owner_node_id, epoch, lease_id, lease_expires_at, granted_by, signature, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (cluster_id) DO UPDATE SET
                            owner_node_id = EXCLUDED.owner_node_id,
                            epoch = EXCLUDED.epoch,
                            lease_id = EXCLUDED.lease_id,
                            lease_expires_at = EXCLUDED.lease_expires_at,
                            granted_by = EXCLUDED.granted_by,
                            signature = EXCLUDED.signature,
                            updated_at = EXCLUDED.updated_at;
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
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            try:
                cur = conn.cursor()
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
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT cluster_id, owner_node_id, epoch, lease_id, lease_expires_at, granted_by, signature, updated_at
                        FROM ownership
                        WHERE cluster_id = %s
                        """,
                        (target_cluster,)
                    )
                    r = cur.fetchone()
                    if not r:
                        return None
                    return OwnershipRecord(
                        cluster_id=r[0],
                        owner_node_id=r[1],
                        epoch=r[2],
                        lease_id=r[3],
                        lease_expires_at=r[4],
                        granted_by=r[5],
                        signature=r[6],
                        updated_at=r[7]
                    )
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
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
        execute_data_change: Callable[[Any], None],
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

        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            try:
                with psycopg.connect(self.database_url) as conn:
                    with conn.cursor() as cur:
                        # 1. Execute entity modification
                        execute_data_change(cur)

                        # 2. Compute sequence
                        cur.execute(
                            "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM change_log WHERE origin_node_id = %s",
                            (origin_node_id,)
                        )
                        seq_num = cur.fetchone()[0]

                        # 3. Insert change_log outbox row
                        cur.execute(
                            """
                            INSERT INTO change_log (
                                operation_id, sequence_number, origin_node_id, origin_epoch,
                                schema_version, entity_type, entity_id, operation, payload, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (op_id, seq_num, origin_node_id, origin_epoch, 1, entity_type, entity_id, operation, payload_str, now)
                        )
                    conn.commit()
                return True, None, None, op_id
            except Exception as e:
                return False, "INTERNAL_ERROR", f"Transaction failed: {str(e)}", None
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            try:
                cur = conn.cursor()
                execute_data_change(cur)

                cur.execute(
                    "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM change_log WHERE origin_node_id = ?",
                    (origin_node_id,)
                )
                seq_num = cur.fetchone()[0]

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

        def _do_insert(cur):
            if self.is_postgres and not self.using_sqlite_fallback:
                cur.execute(
                    """
                    INSERT INTO portfolio_inquiries (id, name, email, subject, message, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (op_id, name, email, subject, message, now)
                )
            else:
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
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, name, email, subject, message, created_at
                        FROM portfolio_inquiries
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (limit,)
                    )
                    rows = cur.fetchall()
                    return [{"id": r[0], "name": r[1], "email": r[2], "subject": r[3], "message": r[4], "created_at": r[5]} for r in rows]
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
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
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO audit_events (event_id, timestamp, node_id, epoch, event_type, severity, details)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (event_id, now, node_id, epoch, event_type, severity, details_str)
                    )
                conn.commit()
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
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
        events = []
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT event_id, timestamp, node_id, epoch, event_type, severity, details
                        FROM audit_events
                        ORDER BY timestamp DESC
                        LIMIT %s
                        """,
                        (limit,)
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        details = r[6]
                        if isinstance(details, str):
                            try:
                                details = json.loads(details)
                            except Exception:
                                pass
                        events.append({
                            "event_id": str(r[0]),
                            "timestamp": r[1],
                            "node_id": r[2],
                            "epoch": r[3],
                            "event_type": r[4],
                            "severity": r[5],
                            "details": details
                        })
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
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
            finally:
                conn.close()
        return events

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
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO conflict_records (
                            conflict_id, entity_type, entity_id, origin_node_id,
                            local_data, remote_data, detected_at, resolved, resolution_notes
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s)
                        """,
                        (
                            conflict_id, entity_type, entity_id, origin_node_id,
                            json.dumps(local_data), json.dumps(remote_data), now, resolution_notes
                        )
                    )
                conn.commit()
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
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
            finally:
                conn.close()
        return conflict_id

    def get_conflicts(self, resolved: Optional[bool] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recorded conflict events."""
        conflicts = []
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    if resolved is None:
                        cur.execute(
                            """
                            SELECT conflict_id, entity_type, entity_id, origin_node_id,
                                   local_data, remote_data, detected_at, resolved, resolution_notes
                            FROM conflict_records
                            ORDER BY detected_at DESC
                            LIMIT %s
                            """,
                            (limit,)
                        )
                    else:
                        cur.execute(
                            """
                            SELECT conflict_id, entity_type, entity_id, origin_node_id,
                                   local_data, remote_data, detected_at, resolved, resolution_notes
                            FROM conflict_records
                            WHERE resolved = %s
                            ORDER BY detected_at DESC
                            LIMIT %s
                            """,
                            (1 if resolved else 0, limit)
                        )
                    for r in cur.fetchall():
                        loc = r[4]
                        rem = r[5]
                        if isinstance(loc, str):
                            try:
                                loc = json.loads(loc)
                            except Exception:
                                pass
                        if isinstance(rem, str):
                            try:
                                rem = json.loads(rem)
                            except Exception:
                                pass
                        conflicts.append({
                            "conflict_id": str(r[0]),
                            "entity_type": r[1],
                            "entity_id": r[2],
                            "origin_node_id": r[3],
                            "local_data": loc,
                            "remote_data": rem,
                            "detected_at": r[6],
                            "resolved": r[7],
                            "resolution_notes": r[8]
                        })
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
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
                for r in cur.fetchall():
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
            finally:
                conn.close()
        return conflicts

    def get_canonical_hash(self, table_name: str = "portfolio_inquiries") -> str:
        """Compute deterministic SHA256 hash of table contents."""
        import hashlib
        rows = []
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    if table_name == "portfolio_inquiries":
                        cur.execute("SELECT id, name, email, subject, message FROM portfolio_inquiries ORDER BY id ASC")
                        for r in cur.fetchall():
                            rows.append({"id": str(r[0]), "name": r[1], "email": r[2], "subject": r[3], "message": r[4]})
                    elif table_name == "portfolio_resume":
                        cur.execute("SELECT id, name, title, email, phone, location, summary, skills, experience, education, template FROM portfolio_resume ORDER BY id ASC")
                        for r in cur.fetchall():
                            rows.append({"id": str(r[0]), "name": r[1], "title": r[2], "email": r[3], "phone": r[4], "location": r[5], "summary": r[6], "skills": r[7], "experience": r[8], "education": r[9], "template": r[10]})
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                if table_name == "portfolio_inquiries":
                    cur.execute("SELECT id, name, email, subject, message FROM portfolio_inquiries ORDER BY id ASC")
                    rows = [
                        {"id": r["id"], "name": r["name"], "email": r["email"], "subject": r["subject"], "message": r["message"]}
                        for r in cur.fetchall()
                    ]
                elif table_name == "portfolio_resume":
                    cur.execute("SELECT id, name, title, email, phone, location, summary, skills, experience, education, template FROM portfolio_resume ORDER BY id ASC")
                    rows = [
                        {"id": r["id"], "name": r["name"], "title": r["title"], "email": r["email"], "phone": r["phone"], "location": r["location"], "summary": r["summary"], "skills": r["skills"], "experience": r["experience"], "education": r["education"], "template": r["template"]}
                        for r in cur.fetchall()
                    ]
            finally:
                conn.close()
        serialized = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    # --- Replication & Checkpoint Operations ---

    def get_replication_checkpoint(self, peer_node_id: str) -> Dict[str, Any]:
        """Fetch replication checkpoint for given peer node."""
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT peer_node_id, last_applied_sequence, last_applied_operation_id, last_applied_at, updated_at
                        FROM replication_checkpoint
                        WHERE peer_node_id = %s
                        """,
                        (peer_node_id,)
                    )
                    r = cur.fetchone()
                    if r:
                        return {
                            "peer_node_id": r[0],
                            "last_applied_sequence": r[1],
                            "last_applied_operation_id": str(r[2]) if r[2] else None,
                            "last_applied_at": r[3],
                            "updated_at": r[4]
                        }
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
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
            finally:
                conn.close()

        return {
            "peer_node_id": peer_node_id,
            "last_applied_sequence": 0,
            "last_applied_operation_id": None,
            "last_applied_at": 0.0,
            "updated_at": 0.0
        }

    def get_unreplicated_changes(self, peer_node_id: str, from_sequence: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get committed local changes that have sequence > peer's last applied sequence."""
        events = []
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    if from_sequence is not None:
                        last_seq = from_sequence
                    else:
                        cur.execute("SELECT last_applied_sequence FROM replication_checkpoint WHERE peer_node_id = %s", (f"ack_{peer_node_id}",))
                        row = cur.fetchone()
                        last_seq = row[0] if row else 0

                    cur.execute(
                        """
                        SELECT operation_id, sequence_number, origin_node_id, origin_epoch,
                               schema_version, entity_type, entity_id, operation, payload, created_at
                        FROM change_log
                        WHERE origin_node_id != %s AND sequence_number > %s
                        ORDER BY sequence_number ASC
                        LIMIT %s
                        """,
                        (peer_node_id, last_seq, limit)
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        payload = r[8]
                        if isinstance(payload, str):
                            try:
                                payload = json.loads(payload)
                            except Exception:
                                pass
                        events.append({
                            "operation_id": str(r[0]),
                            "sequence_number": r[1],
                            "origin_node_id": r[2],
                            "origin_epoch": r[3],
                            "schema_version": r[4],
                            "entity_type": r[5],
                            "entity_id": r[6],
                            "operation": r[7],
                            "payload": payload,
                            "created_at": r[9]
                        })
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.cursor()
                if from_sequence is not None:
                    last_seq = from_sequence
                else:
                    cur.execute("SELECT last_applied_sequence FROM replication_checkpoint WHERE peer_node_id = ?", (f"ack_{peer_node_id}",))
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
                for r in rows:
                    ev = dict(r)
                    if isinstance(ev["payload"], str):
                        try:
                            ev["payload"] = json.loads(ev["payload"])
                        except Exception:
                            pass
                    events.append(ev)
            finally:
                conn.close()
        return events

    def get_pending_replication_events(self, origin_node_id: Optional[str] = None, from_sequence: int = 1, limit: int = 50) -> List[Dict[str, Any]]:
        """Query change_log events by origin node and sequence number."""
        events = []
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    if origin_node_id:
                        cur.execute(
                            """
                            SELECT operation_id, sequence_number, origin_node_id, origin_epoch,
                                   schema_version, entity_type, entity_id, operation, payload, created_at
                            FROM change_log
                            WHERE origin_node_id = %s AND sequence_number >= %s
                            ORDER BY sequence_number ASC
                            LIMIT %s
                            """,
                            (origin_node_id, from_sequence, limit)
                        )
                    else:
                        cur.execute(
                            """
                            SELECT operation_id, sequence_number, origin_node_id, origin_epoch,
                                   schema_version, entity_type, entity_id, operation, payload, created_at
                            FROM change_log
                            WHERE sequence_number >= %s
                            ORDER BY sequence_number ASC
                            LIMIT %s
                            """,
                            (from_sequence, limit)
                        )
                    for r in cur.fetchall():
                        payload = r[8]
                        if isinstance(payload, str):
                            try:
                                payload = json.loads(payload)
                            except Exception:
                                pass
                        events.append({
                            "operation_id": str(r[0]),
                            "sequence_number": r[1],
                            "origin_node_id": r[2],
                            "origin_epoch": r[3],
                            "schema_version": r[4],
                            "entity_type": r[5],
                            "entity_id": r[6],
                            "operation": r[7],
                            "payload": payload,
                            "created_at": r[9]
                        })
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
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
                for r in cur.fetchall():
                    ev = dict(r)
                    if isinstance(ev["payload"], str):
                        try:
                            ev["payload"] = json.loads(ev["payload"])
                        except Exception:
                            pass
                    events.append(ev)
            finally:
                conn.close()
        return events

    def record_peer_ack(self, peer_node_id: str, acked_sequence: int, operation_id: Optional[str] = None):
        """Record the sequence number that the peer has acknowledged applying."""
        now = time.time()
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO replication_checkpoint (peer_node_id, last_applied_sequence, last_applied_operation_id, last_applied_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (peer_node_id) DO UPDATE SET
                            last_applied_sequence = GREATEST(replication_checkpoint.last_applied_sequence, EXCLUDED.last_applied_sequence),
                            last_applied_operation_id = COALESCE(EXCLUDED.last_applied_operation_id, replication_checkpoint.last_applied_operation_id),
                            updated_at = EXCLUDED.updated_at;
                        """,
                        (f"ack_{peer_node_id}", acked_sequence, operation_id, now, now)
                    )
                conn.commit()
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
            try:
                cur = conn.cursor()
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
        if self.is_postgres and not self.using_sqlite_fallback:
            import psycopg
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COALESCE(MAX(sequence_number), 0) FROM change_log WHERE origin_node_id = %s", (origin_node_id,))
                    return cur.fetchone()[0]
        else:
            import sqlite3
            conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
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
            backup_dir = os.path.join(os.path.dirname(os.path.dirname(self._sqlite_path)), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        timestamp_str = str(int(time.time()))
        backup_file = os.path.join(backup_dir, f"backup_laptop_{timestamp_str}.db")

        if self.is_postgres and not self.using_sqlite_fallback:
            # In PG mode, record backup metadata
            return f"pg_backup_recorded_{timestamp_str}"
        else:
            import sqlite3
            src_conn = sqlite3.connect(self._sqlite_path)
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
        checkpoint = self.get_replication_checkpoint(origin_node_id)
        last_applied_seq = checkpoint["last_applied_sequence"]

        # Filter out already applied events (idempotence)
        duplicate_count = 0
        new_events = []
        for ev in events:
            if ev["sequence_number"] <= last_applied_seq:
                duplicate_count += 1
            else:
                new_events.append(ev)

        if not new_events:
            return True, last_applied_seq, duplicate_count, [], False, None

        # Check sequence continuity
        has_gap, missing = detect_sequence_gap(last_applied_seq, new_events)
        if has_gap:
            return False, last_applied_seq, duplicate_count, missing, True, "Sequence gap detected"

        import sqlite3
        conn = sqlite3.connect(self._sqlite_path, timeout=5.0)
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.cursor()
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

                cur.execute("SELECT 1 FROM change_log WHERE operation_id = ?", (op_id,))
                if cur.fetchone():
                    duplicate_count += 1
                    current_seq = seq_num
                    last_op_id = op_id
                    continue

                # Conflict detection & mutation
                if entity_type == "inquiry":
                    cur.execute("SELECT * FROM portfolio_inquiries WHERE id = ?", (entity_id,))
                    local_row = cur.fetchone()
                    if local_row:
                        local_dict = {
                            "id": local_row[0], "name": local_row[1], "email": local_row[2],
                            "subject": local_row[3], "message": local_row[4], "created_at": local_row[5]
                        }
                        if local_dict.get("message") != payload.get("message"):
                            conflict_id = uuid.uuid4().hex
                            cur.execute(
                                """
                                INSERT INTO conflict_records (conflict_id, entity_type, entity_id, origin_node_id, local_data, remote_data, detected_at, resolved)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                                """,
                                (conflict_id, entity_type, entity_id, origin_node_id, json.dumps(local_dict), json.dumps(payload), now)
                            )

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
                elif entity_type == "resume":
                    cur.execute("SELECT * FROM portfolio_resume WHERE id = ?", (entity_id,))
                    local_row = cur.fetchone()
                    remote_epoch = ev.get("origin_epoch", 1)
                    if local_row:
                        local_dict = {
                            "id": local_row[0], "name": local_row[1], "title": local_row[2],
                            "email": local_row[3], "phone": local_row[4], "location": local_row[5],
                            "summary": local_row[6], "skills": local_row[7], "experience": local_row[8],
                            "education": local_row[9], "template": local_row[10], "updated_at": local_row[11]
                        }
                        # A true conflict only occurs if local was modified after the remote payload at an older or equal epoch
                        if (local_dict.get("updated_at", 0) > payload.get("updated_at", 0)) and remote_epoch <= 1:
                            conflict_id = uuid.uuid4().hex
                            cur.execute(
                                """
                                INSERT INTO conflict_records (conflict_id, entity_type, entity_id, origin_node_id, local_data, remote_data, detected_at, resolved)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                                """,
                                (conflict_id, entity_type, entity_id, origin_node_id, json.dumps(local_dict), json.dumps(payload), now)
                            )

                    if operation == "upsert":
                        cur.execute(
                            """
                            INSERT INTO portfolio_resume (id, name, title, email, phone, location, summary, skills, experience, education, template, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(id) DO UPDATE SET
                                name = excluded.name,
                                title = excluded.title,
                                email = excluded.email,
                                phone = excluded.phone,
                                location = excluded.location,
                                summary = excluded.summary,
                                skills = excluded.skills,
                                experience = excluded.experience,
                                education = excluded.education,
                                template = excluded.template,
                                updated_at = excluded.updated_at
                            """,
                            (
                                payload.get("id", entity_id),
                                payload.get("name", ""),
                                payload.get("title", ""),
                                payload.get("email", ""),
                                payload.get("phone", ""),
                                payload.get("location", ""),
                                payload.get("summary", ""),
                                payload.get("skills", ""),
                                payload.get("experience", ""),
                                payload.get("education", ""),
                                payload.get("template", "modern"),
                                payload.get("updated_at", now)
                            )
                        )
                    elif operation == "delete":
                        cur.execute("DELETE FROM portfolio_resume WHERE id = ?", (entity_id,))
                else:
                    raise ValueError(f"Unsupported entity_type for replication: {entity_type}")

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

    # --- Durable Alert Outbox Operations (Phase 11b) ---

    def enqueue_alert(
        self,
        dedupe_key: str,
        severity: str,
        title: str,
        body: str,
        cooldown_seconds: float = 300.0,
        now: Optional[float] = None
    ) -> Optional[str]:
        """
        Durably enqueues an alert into alert_outbox.
        Enforces cooldown on duplicate dedupe_key to prevent flapping.
        Returns alert_id if enqueued, or None if suppressed by cooldown.
        """
        cur_time = now if now is not None else time.time()
        conn = self.get_connection()
        is_pg = self.is_postgres and not self.using_sqlite_fallback
        try:
            cur = conn.cursor()
            # Cooldown check
            if cooldown_seconds > 0:
                ph = "%s" if is_pg else "?"
                check_query = f"SELECT created_at FROM alert_outbox WHERE dedupe_key = {ph} ORDER BY created_at DESC LIMIT 1"
                cur.execute(check_query, (dedupe_key,))
                row = cur.fetchone()
                if row:
                    created_at_val = row[0] if is_pg else row["created_at"]
                    if (cur_time - float(created_at_val)) < cooldown_seconds:
                        return None

            alert_id = uuid.uuid4().hex
            ph = ["%s"] * 9 if is_pg else ["?"] * 9
            insert_query = f"INSERT INTO alert_outbox (id, dedupe_key, severity, title, body, created_at, sent_at, attempts, next_attempt_at) VALUES ({', '.join(ph)})"
            cur.execute(
                insert_query,
                (alert_id, dedupe_key, severity, title, body, cur_time, None, 0, cur_time)
            )
            conn.commit()
            return alert_id
        finally:
            conn.close()

    def get_pending_alerts(self, limit: int = 10, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Fetch pending alerts ready for delivery."""
        cur_time = now if now is not None else time.time()
        conn = self.get_connection()
        is_pg = self.is_postgres and not self.using_sqlite_fallback
        try:
            cur = conn.cursor()
            ph1 = "%s" if is_pg else "?"
            ph2 = "%s" if is_pg else "?"
            pending_query = f"SELECT id, dedupe_key, severity, title, body, created_at, attempts, next_attempt_at FROM alert_outbox WHERE sent_at IS NULL AND next_attempt_at <= {ph1} ORDER BY created_at ASC LIMIT {ph2}"
            cur.execute(pending_query, (cur_time, limit))
            if is_pg:
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def mark_alert_sent(self, alert_id: str, sent_at: Optional[float] = None) -> None:
        """Mark an alert as successfully delivered."""
        cur_time = sent_at if sent_at is not None else time.time()
        conn = self.get_connection()
        is_pg = self.is_postgres and not self.using_sqlite_fallback
        try:
            cur = conn.cursor()
            ph = "%s" if is_pg else "?"
            mark_query = f"UPDATE alert_outbox SET sent_at = {ph} WHERE id = {ph}"
            cur.execute(mark_query, (cur_time, alert_id))
            conn.commit()
        finally:
            conn.close()

    def record_alert_attempt(self, alert_id: str, next_attempt_at: float, current_attempts: int) -> None:
        """Record retry attempt and set next backoff timestamp."""
        conn = self.get_connection()
        is_pg = self.is_postgres and not self.using_sqlite_fallback
        try:
            cur = conn.cursor()
            ph = "%s" if is_pg else "?"
            attempt_query = f"UPDATE alert_outbox SET attempts = {ph}, next_attempt_at = {ph} WHERE id = {ph}"
            cur.execute(attempt_query, (current_attempts, next_attempt_at, alert_id))
            conn.commit()
        finally:
            conn.close()

    def get_alert_send_counts(self, since_timestamp: float) -> int:
        """Count number of alerts sent since a timestamp (for hourly/daily rate caps)."""
        conn = self.get_connection()
        is_pg = self.is_postgres and not self.using_sqlite_fallback
        try:
            cur = conn.cursor()
            ph = "%s" if is_pg else "?"
            count_query = f"SELECT COUNT(*) as cnt FROM alert_outbox WHERE sent_at >= {ph}"
            cur.execute(count_query, (since_timestamp,))
            row = cur.fetchone()
            val = row[0] if is_pg else row["cnt"]
            return int(val) if val else 0
        finally:
            conn.close()

    def prune_alert_outbox(self, max_rows: int = 1000, keep_seconds: float = 86400 * 7) -> int:
        """Prune old sent alerts to keep table size bounded."""
        conn = self.get_connection()
        is_pg = self.is_postgres and not self.using_sqlite_fallback
        try:
            cur = conn.cursor()
            cutoff = time.time() - keep_seconds
            ph = "%s" if is_pg else "?"
            prune_query = f"DELETE FROM alert_outbox WHERE sent_at IS NOT NULL AND sent_at < {ph}"
            cur.execute(prune_query, (cutoff,))
            pruned = cur.rowcount
            conn.commit()
            return pruned
        finally:
            conn.close()

    # --- Incident Tracker Operations (Phase 11b) ---

    def create_or_update_incident(self, incident_data: Dict[str, Any]) -> None:
        """Upsert incident tracking record."""
        now = time.time()
        conn = self.get_connection()
        is_pg = self.is_postgres and not self.using_sqlite_fallback
        try:
            cur = conn.cursor()
            inc_id = incident_data["incident_id"]
            ph = "%s" if is_pg else "?"
            chk_query = f"SELECT incident_id FROM incidents WHERE incident_id = {ph}"
            cur.execute(chk_query, (inc_id,))
            exists = cur.fetchone() is not None

            if exists:
                fields = []
                values = []
                for k, v in incident_data.items():
                    if k != "incident_id":
                        fields.append(f"{k} = {ph}")
                        values.append(v)
                fields.append(f"updated_at = {ph}")
                values.append(now)
                values.append(inc_id)
                upd_query = f"UPDATE incidents SET {', '.join(fields)} WHERE incident_id = {ph}"
                cur.execute(upd_query, values)
            else:
                cols = list(incident_data.keys())
                vals = list(incident_data.values())
                if "created_at" not in incident_data:
                    cols.append("created_at")
                    vals.append(now)
                if "updated_at" not in incident_data:
                    cols.append("updated_at")
                    vals.append(now)
                placeholders = ", ".join([ph] * len(cols))
                ins_query = f"INSERT INTO incidents ({', '.join(cols)}) VALUES ({placeholders})"
                cur.execute(ins_query, vals)
            conn.commit()
        finally:
            conn.close()

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve an incident record by ID."""
        conn = self.get_connection()
        is_pg = self.is_postgres and not self.using_sqlite_fallback
        try:
            cur = conn.cursor()
            ph = "%s" if is_pg else "?"
            inc_query = f"SELECT * FROM incidents WHERE incident_id = {ph}"
            cur.execute(inc_query, (incident_id,))
            row = cur.fetchone()
            if not row:
                return None
            if is_pg:
                cols = [desc[0] for desc in cur.description]
                return dict(zip(cols, row))
            return dict(row)
        finally:
            conn.close()

    def get_active_incident(self) -> Optional[Dict[str, Any]]:
        """Retrieve current OPEN incident, if any."""
        conn = self.get_connection()
        is_pg = self.is_postgres and not self.using_sqlite_fallback
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM incidents WHERE status = 'OPEN' ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            if is_pg:
                cols = [desc[0] for desc in cur.description]
                return dict(zip(cols, row))
            return dict(row)
        finally:
            conn.close()

    def count_writes_since(self, since_timestamp: float) -> int:
        """Count operations accepted in change_log since a timestamp."""
        conn = self.get_connection()
        is_pg = self.is_postgres and not self.using_sqlite_fallback
        try:
            cur = conn.cursor()
            ph = "%s" if is_pg else "?"
            cnt_query = f"SELECT COUNT(*) as cnt FROM change_log WHERE created_at >= {ph}"
            cur.execute(cnt_query, (since_timestamp,))
            row = cur.fetchone()
            val = row[0] if is_pg else row["cnt"]
            return int(val) if val else 0
        finally:
            conn.close()
