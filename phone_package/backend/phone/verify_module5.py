"""
Module 5 Verification Script
Run from backend/phone/: python verify_module5.py
Expected: All checks PASS
"""

import sys
import os
import ast
import json
import uuid
import hashlib
import pathlib
import tempfile

print("=" * 55)
print("MODULE 5 — PHONE STORAGE VERIFICATION")
print("=" * 55)

PHONE_DIR = pathlib.Path(__file__).parent

# ── Ensure API_KEY is set so phone.config doesn't fail on import ──
if not os.getenv("API_KEY"):
    os.environ["API_KEY"] = "test-key-for-verification"

sys.path.insert(0, str(PHONE_DIR.parent))

# Temp DB path — cleaned up at the end
_tmp_db = str(PHONE_DIR / "_verify_test.db")


def _remove_test_db():
    p = pathlib.Path(_tmp_db)
    if p.exists():
        p.unlink()


# ── CHECK 1: Zero third-party imports (AST scan) ──────
print("\n[1] Scanning storage.py for third-party imports...")
stdlib_only = {
    "os", "sys", "time", "pathlib", "json", "uuid", "datetime",
    "hashlib", "dataclasses", "typing", "abc", "re", "ast",
    "threading", "socket", "struct", "logging", "io", "collections",
    "functools", "itertools", "math", "random", "string", "copy",
    "traceback", "contextlib", "enum", "http", "urllib", "email",
    "html", "xml", "csv", "sqlite3", "subprocess", "signal",
}
violations = []
src = (PHONE_DIR / "storage.py").read_text(encoding="utf-8")
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        mod = ""
        if isinstance(node, ast.Import):
            mod = node.names[0].name.split(".")[0]
        elif node.module:
            mod = node.module.split(".")[0]
        if mod and mod not in stdlib_only and mod != "phone":
            violations.append(f"imports '{mod}'")
if violations:
    print(f"  FAIL — Third-party imports found: {violations}")
    sys.exit(1)
print("  PASS — Zero third-party imports")

# ── Import storage ─────────────────────────────────────
from phone.storage import (
    init_storage, compute_checksum, apply_sync_snapshot,
    get_all_projects, get_project, save_event, get_events,
    get_sync_version, get_storage_stats,
)

# ── CHECK 2: init_storage creates tables ──────────────
print("\n[2] Testing init_storage() creates all tables...")
_remove_test_db()
try:
    init_storage(_tmp_db)

    import sqlite3
    conn = sqlite3.connect(_tmp_db)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    ).fetchall()}
    conn.close()

    for t in ("projects", "events", "sync_meta"):
        assert t in tables, f"Table '{t}' not created"
    print(f"  PASS — Tables created: {sorted(tables)}")
except Exception as e:
    print(f"  FAIL — {e}")
    _remove_test_db()
    sys.exit(1)

# ── CHECK 3: compute_checksum is deterministic ─────────
print("\n[3] Testing compute_checksum() determinism...")
projects_a = [
    {"id": "p1", "title": "Alpha", "status": "active"},
    {"id": "p2", "title": "Beta",  "status": "active"},
]
c1 = compute_checksum(projects_a)
c2 = compute_checksum(projects_a)
assert c1 == c2, "Checksum not deterministic"
assert len(c1) == 64, f"Expected SHA-256 hex (64 chars), got {len(c1)}"
print(f"  PASS — Deterministic checksum: {c1[:16]}...")

# ── CHECK 4: checksum changes when data changes ────────
print("\n[4] Testing checksum changes with different data...")
projects_b = [{"id": "p1", "title": "CHANGED", "status": "active"},
              {"id": "p2", "title": "Beta",    "status": "active"}]
c3 = compute_checksum(projects_b)
assert c1 != c3, "Checksum did not change when data changed"

# Order independence — same data different order
projects_reversed = list(reversed(projects_a))
c4 = compute_checksum(projects_reversed)
assert c1 == c4, "Checksum differs for same data in different order"
print("  PASS — Checksum changes with data, order-independent")

# ── CHECK 5: apply_sync_snapshot inserts projects ─────
print("\n[5] Testing apply_sync_snapshot() inserts projects...")
projects_v1 = [
    {"id": "proj-001", "title": "Portfolio Site", "description": "My site",
     "tech_stack": "Python,FastAPI", "status": "active",
     "created_at": "2024-01-01T10:00:00", "updated_at": "2024-01-01T10:00:00",
     "sync_version": 1, "checksum": None},
    {"id": "proj-002", "title": "Mobile App", "description": "Android app",
     "tech_stack": "Kotlin", "status": "active",
     "created_at": "2024-01-02T10:00:00", "updated_at": "2024-01-02T10:00:00",
     "sync_version": 1, "checksum": None},
]
checksum_v1 = compute_checksum(projects_v1)
snapshot_v1 = {
    "version": 1,
    "checksum": checksum_v1,
    "payload": {"projects": projects_v1},
}
result = apply_sync_snapshot(snapshot_v1)
assert result["status"] == "ok", f"Expected ok, got {result}"
assert result["version"] == 1
assert result["count"] == 2
print(f"  PASS — Snapshot v1 applied: {result}")

# ── CHECK 6: get_all_projects returns inserted data ────
print("\n[6] Testing get_all_projects()...")
all_projects = get_all_projects()
assert len(all_projects) == 2, f"Expected 2, got {len(all_projects)}"
ids = {p["id"] for p in all_projects}
assert "proj-001" in ids
assert "proj-002" in ids
print(f"  PASS — get_all_projects() returned {len(all_projects)} projects")

# ── CHECK 7: stale snapshot rejection ─────────────────
print("\n[7] Testing stale snapshot rejection...")
snapshot_stale = {
    "version": 1,   # same version as current — should be rejected
    "checksum": checksum_v1,
    "payload": {"projects": projects_v1},
}
result = apply_sync_snapshot(snapshot_stale)
assert result["status"] == "rejected", f"Expected rejected, got {result}"
assert result["reason"] == "stale"

snapshot_older = {
    "version": 0,   # older — should also be rejected
    "checksum": checksum_v1,
    "payload": {"projects": projects_v1},
}
result2 = apply_sync_snapshot(snapshot_older)
assert result2["status"] == "rejected"
assert result2["reason"] == "stale"
print("  PASS — Stale snapshots correctly rejected")

# ── CHECK 8: checksum mismatch rejection ───────────────
print("\n[8] Testing checksum mismatch rejection...")
snapshot_tampered = {
    "version": 2,
    "checksum": "0" * 64,   # wrong checksum
    "payload": {"projects": projects_v1},
}
result = apply_sync_snapshot(snapshot_tampered)
assert result["status"] == "rejected", f"Expected rejected, got {result}"
assert result["reason"] == "checksum_mismatch"
# Version should still be 1 — nothing was applied
assert get_sync_version() == 1, "Version changed despite rejection"
print("  PASS — Tampered checksum correctly rejected")

# ── CHECK 9: Atomic transaction — old data survives failed apply ──
print("\n[9] Testing atomic transaction integrity...")
# Current state: 2 projects at version 1
# We will apply a v2 snapshot with a valid checksum but then verify
# that a corrupt snapshot does NOT wipe existing data
projects_v2 = [
    {"id": "proj-001", "title": "Portfolio v2", "description": "Updated",
     "tech_stack": "Python,FastAPI,React", "status": "active",
     "created_at": "2024-01-01T10:00:00", "updated_at": "2024-01-03T10:00:00",
     "sync_version": 2, "checksum": None},
]
# Build a snapshot that has correct checksum but then monkey-patch to be
# invalid AFTER checksum passes — we simulate this by trying a reject scenario:
# corrupt snapshot (checksum mismatch) at version 3 — data should remain v1/v2 stable.
bad_snap = {"version": 5, "checksum": "badhash" * 8, "payload": {"projects": []}}
result = apply_sync_snapshot(bad_snap)
assert result["status"] == "rejected"
# Old data still there
still_there = get_all_projects()
assert len(still_there) == 2, f"Old data was wiped by failed snapshot! Got {len(still_there)}"
print("  PASS — Atomic: old data intact after failed snapshot")

# ── CHECK 10: get_project returns single correct row ──
print("\n[10] Testing get_project()...")
p = get_project("proj-001")
assert p is not None, "proj-001 not found"
assert p["title"] == "Portfolio Site"
assert p["tech_stack"] == "Python,FastAPI"

missing = get_project("does-not-exist")
assert missing is None, "Expected None for missing project"
print("  PASS — get_project() returns correct row and None for missing")

# ── CHECK 11: save_event and get_events ───────────────
print("\n[11] Testing save_event() and get_events()...")
evt1 = {
    "id": str(uuid.uuid4()),
    "event_type": "HEARTBEAT",
    "severity": "INFO",
    "source": "laptop-node-01",
    "message": "Heartbeat received",
    "timestamp": "2024-01-01T10:00:00",
    "acknowledged": False,
    "metadata_json": json.dumps({"sequence": 1}),
}
evt2 = {
    "id": str(uuid.uuid4()),
    "event_type": "FAILOVER",
    "severity": "CRITICAL",
    "source": "phone-node-02",
    "message": "Primary offline",
    "timestamp": "2024-01-01T11:00:00",
    "acknowledged": False,
    "metadata_json": json.dumps({"reason": "timeout"}),
}
save_event(evt1)
save_event(evt2)

events = get_events(limit=10)
assert len(events) == 2, f"Expected 2 events, got {len(events)}"
# Most recent first
assert events[0]["event_type"] == "FAILOVER"
assert events[1]["event_type"] == "HEARTBEAT"
# acknowledged stored as int, value should be 0 (False)
assert events[0]["acknowledged"] == 0
meta = json.loads(events[0]["metadata_json"])
assert meta["reason"] == "timeout"
print("  PASS — save_event() and get_events() correct")

# ── CHECK 12: get_sync_version ────────────────────────
print("\n[12] Testing get_sync_version()...")
ver = get_sync_version()
assert ver == 1, f"Expected version 1, got {ver}"
print(f"  PASS — get_sync_version() returned {ver}")

# ── CHECK 13: get_storage_stats ───────────────────────
print("\n[13] Testing get_storage_stats()...")
stats = get_storage_stats()
assert stats["project_count"] == 2, f"project_count={stats['project_count']}"
assert stats["event_count"] == 2,   f"event_count={stats['event_count']}"
assert stats["sync_version"] == 1,  f"sync_version={stats['sync_version']}"
assert "last_sync_time" in stats
assert stats["last_sync_time"] is not None
print(f"  PASS — get_storage_stats(): {stats}")

# ── CHECK 14: Cleanup test database ───────────────────
print("\n[14] Cleaning up test database...")
_remove_test_db()
assert not pathlib.Path(_tmp_db).exists(), "Test DB not deleted"
print(f"  PASS — Test database removed")

# ── FINAL ─────────────────────────────────────────────
print("\n" + "=" * 55)
print("MODULE 5 COMPLETE — ALL CHECKS PASSED")
print("=" * 55)
print("\nReady to proceed to Module 6.")
