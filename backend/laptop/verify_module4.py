"""
Module 4 Verification Script
Run from backend/: python -m laptop.verify_module4
Expected: All checks PASS
"""

import sys
import uuid
import pathlib

print("=" * 55)
print("MODULE 4 — LAPTOP DATABASE VERIFICATION")
print("=" * 55)

BACKEND = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND))

# ── CHECK 1: Files exist ───────────────────────────────
print("\n[1] Checking required files exist...")
required = [
    BACKEND / "laptop" / "database.py",
    BACKEND / "laptop" / "models" / "__init__.py",
    BACKEND / "laptop" / "models" / "portfolio.py",
    BACKEND / "laptop" / "models" / "events.py",
]
missing = [str(p) for p in required if not p.exists()]
if missing:
    print(f"  FAIL — Missing files:\n    " + "\n    ".join(missing))
    sys.exit(1)
print("  PASS — All required files present")

# ── CHECK 2: SQLAlchemy + psycopg installed ────────────
print("\n[2] Checking SQLAlchemy and psycopg installed...")
try:
    import sqlalchemy
    print(f"  sqlalchemy {sqlalchemy.__version__}")
except ImportError:
    print("  FAIL — Run: pip install sqlalchemy")
    sys.exit(1)
try:
    import psycopg
    print(f"  psycopg {psycopg.__version__}")
except ImportError:
    print("  FAIL — Run: pip install 'psycopg[binary]'")
    sys.exit(1)
print("  PASS — Dependencies present")

# ── CHECK 3: database.py importable ───────────────────
print("\n[3] Testing database.py imports...")
try:
    from laptop.database import Base, get_db, init_db, SessionLocal, get_engine
    print("  PASS — Base, get_db, init_db, SessionLocal, get_engine all importable")
except ImportError as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── CHECK 4: Project model ─────────────────────────────
print("\n[4] Testing Project model...")
try:
    from laptop.models.portfolio import Project
    cols = {c.name for c in Project.__table__.columns}
    required_cols = {
        "id", "title", "description", "tech_stack", "status",
        "created_at", "updated_at", "sync_version", "checksum",
    }
    missing_cols = required_cols - cols
    if missing_cols:
        print(f"  FAIL — Missing columns: {missing_cols}")
        sys.exit(1)
    print(f"  PASS — Project model has all columns: {sorted(cols)}")
except Exception as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── CHECK 5: Event model ───────────────────────────────
print("\n[5] Testing Event model...")
try:
    from laptop.models.events import Event
    cols = {c.name for c in Event.__table__.columns}
    required_cols = {
        "id", "event_type", "severity", "source", "message",
        "timestamp", "acknowledged", "metadata_json",
    }
    missing_cols = required_cols - cols
    if missing_cols:
        print(f"  FAIL — Missing columns: {missing_cols}")
        sys.exit(1)
    print(f"  PASS — Event model has all columns: {sorted(cols)}")
except Exception as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── CHECK 6: init_db() creates tables ─────────────────
print("\n[6] Testing init_db() against PostgreSQL...")
try:
    init_db()
    print("  PASS — init_db() succeeded")
except Exception as e:
    print(f"\n  FAIL — Could not connect to PostgreSQL: {e}")
    print("\n  ── PostgreSQL Setup Required ───────────────────────────")
    print("  Make sure PostgreSQL is running and .env.laptop is set.")
    print("  Quickstart:")
    print("    1. Install PostgreSQL: https://www.postgresql.org/download/")
    print("    2. Create database:")
    print("       psql -U postgres -c \"CREATE USER sentineldr WITH PASSWORD 'password';\"")
    print("       psql -U postgres -c \"CREATE DATABASE sentineldr OWNER sentineldr;\"")
    print("    3. Set in backend/.env.laptop:")
    print("       DATABASE_URL=postgresql+psycopg://sentineldr:password@localhost:5432/sentineldr")
    print("  ────────────────────────────────────────────────────────")
    sys.exit(1)

# ── CHECK 7: init_db() is idempotent ──────────────────
print("\n[7] Testing init_db() idempotency (run twice)...")
try:
    init_db()
    print("  PASS — init_db() idempotent (second call did not error)")
except Exception as e:
    print(f"  FAIL — Second init_db() call raised: {e}")
    sys.exit(1)

# ── CHECK 8: Insert and query Project ─────────────────
print("\n[8] Testing Project insert and query...")
engine = get_engine()
from sqlalchemy.orm import Session

test_project_id = str(uuid.uuid4())
try:
    with Session(engine) as session:
        proj = Project(
            id=test_project_id,
            title="Verify Test Project",
            description="Created by verify_module4.py",
            tech_stack="Python,FastAPI",
            status="active",
            sync_version=0,
        )
        session.add(proj)
        session.commit()

    with Session(engine) as session:
        found = session.get(Project, test_project_id)
        assert found is not None, "Project not found after insert"
        assert found.title == "Verify Test Project"
        assert found.status == "active"
        assert found.sync_version == 0
        assert found.created_at is not None
        assert found.updated_at is not None

    print("  PASS — Project inserts and queries correctly")
except Exception as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── CHECK 9: Insert and query Event ───────────────────
print("\n[9] Testing Event insert and query...")
import json as _json

test_event_id = str(uuid.uuid4())
try:
    with Session(engine) as session:
        evt = Event(
            id=test_event_id,
            event_type="VERIFY",
            severity="INFO",
            source="verify_module4",
            message="Verification test event",
            acknowledged=False,
            metadata_json=_json.dumps({"test": True}),
        )
        session.add(evt)
        session.commit()

    with Session(engine) as session:
        found = session.get(Event, test_event_id)
        assert found is not None, "Event not found after insert"
        assert found.event_type == "VERIFY"
        assert found.severity == "INFO"
        assert found.acknowledged == False
        meta = _json.loads(found.metadata_json)
        assert meta["test"] == True
        assert found.timestamp is not None

    print("  PASS — Event inserts and queries correctly")
except Exception as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── CHECK 10: Cleanup test rows ────────────────────────
print("\n[10] Cleaning up test rows...")
try:
    with Session(engine) as session:
        proj = session.get(Project, test_project_id)
        evt = session.get(Event, test_event_id)
        if proj:
            session.delete(proj)
        if evt:
            session.delete(evt)
        session.commit()

    # Verify they are gone
    with Session(engine) as session:
        assert session.get(Project, test_project_id) is None, "Project not deleted"
        assert session.get(Event, test_event_id) is None, "Event not deleted"

    print("  PASS — Test rows deleted, database clean")
except Exception as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── FINAL ─────────────────────────────────────────────
print("\n" + "=" * 55)
print("MODULE 4 COMPLETE — ALL CHECKS PASSED")
print("=" * 55)
print("\nReady to proceed to Module 5.")
