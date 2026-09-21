"""
Module 9 Verification Script
Run from backend/: python verify_module9.py
Expected: All checks PASS
"""

import sys
import os
import ast
import json
import hashlib
import time
import pathlib

print("=" * 55)
print("MODULE 9 — SYNCHRONIZATION SERVICE VERIFICATION")
print("=" * 55)

BACKEND = pathlib.Path(__file__).parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("API_KEY", "test-key-for-verification")

# ── CHECK 1: Files exist ───────────────────────────────
print("\n[1] Checking required files exist...")
required = [
    BACKEND / "laptop" / "services" / "sync_service.py",
    BACKEND / "phone" / "sync.py",
]
missing = [str(p) for p in required if not p.exists()]
if missing:
    print("  FAIL — Missing:\n    " + "\n    ".join(missing))
    sys.exit(1)
print("  PASS — All required files present")

# ── CHECK 2: Phone sync.py — zero third-party imports ──
print("\n[2] AST scan: phone/sync.py — zero third-party imports...")
STDLIB = {
    "os", "sys", "time", "pathlib", "json", "uuid", "datetime",
    "hashlib", "dataclasses", "typing", "abc", "re", "ast",
    "threading", "socket", "struct", "logging", "io", "collections",
    "functools", "itertools", "math", "random", "string", "copy",
    "traceback", "contextlib", "enum", "http", "urllib", "email",
    "html", "xml", "csv", "sqlite3", "subprocess", "signal",
}
FIRST_PARTY = {"shared", "phone", "laptop"}

def scan_imports(path, allowed=None):
    allowed = allowed or set()
    violations = []
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = ""
            if isinstance(node, ast.Import):
                mod = node.names[0].name.split(".")[0]
            elif node.module:
                mod = node.module.split(".")[0]
            if mod and mod not in STDLIB and mod not in FIRST_PARTY and mod not in allowed:
                violations.append(mod)
    return violations

phone_v = scan_imports(BACKEND / "phone" / "sync.py")
if phone_v:
    print(f"  FAIL — Third-party imports: {phone_v}")
    sys.exit(1)
print("  PASS — Zero third-party imports in phone/sync.py")

# ── CHECK 3: Laptop sync does not import phone ─────────
print("\n[3] AST scan: laptop/sync_service.py — no phone imports...")
src = (BACKEND / "laptop" / "services" / "sync_service.py").read_text(encoding="utf-8")
tree = ast.parse(src)
phone_imports = [
    (n.names[0].name if isinstance(n, ast.Import) else (n.module or "")).split(".")[0]
    for n in ast.walk(tree)
    if isinstance(n, (ast.Import, ast.ImportFrom))
    and (
        (isinstance(n, ast.Import) and n.names[0].name.split(".")[0] == "phone") or
        (isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "phone")
    )
]
if phone_imports:
    print(f"  FAIL — Laptop imports phone: {phone_imports}")
    sys.exit(1)
print("  PASS — Laptop sync does not import phone modules")

# ── Setup: temp SQLite + phone sync module ─────────────
_tmp_db = str(BACKEND / "phone" / "_verify9_test.db")

import phone.storage as storage_mod
storage_mod.init_storage(_tmp_db)

import phone.sync as sync_mod

class MockPhoneConfig:
    NODE_ID = "phone-test-node"
    NODE_ROLE = "secondary"
    API_KEY = "correct-api-key"
    PEER_PORT = 18000

def fresh_runtime():
    return {
        "peer_host": None,
        "peer_status": "offline",
        "peer_last_seen": None,
        "missed_heartbeats": 0,
        "sync_version": 0,
        "last_sync_time": None,
        "last_sync_checksum": None,
        "failover_active": False,
        "failover_time": None,
        "start_time": time.time(),
        "heartbeat_sequence": 0,
    }

rt = fresh_runtime()
sync_mod.init_sync(
    config_module=MockPhoneConfig(),
    runtime_dict=rt,
    storage_module=storage_mod,
)

def _make_projects(n=2, version=1):
    return [
        {
            "id": f"proj-{i:03d}",
            "title": f"Project {i}",
            "description": f"Description {i}",
            "tech_stack": "Python",
            "status": "active",
            "created_at": "2024-01-01T10:00:00",
            "updated_at": "2024-01-01T10:00:00",
            "sync_version": version,
            "checksum": None,
        }
        for i in range(1, n + 1)
    ]

def _compute_checksum(projects):
    sorted_p = sorted(projects, key=lambda p: p.get("id", ""))
    s = json.dumps(sorted_p, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _make_snapshot(projects, version, checksum=None):
    if checksum is None:
        checksum = _compute_checksum(projects)
    return {
        "version": version,
        "checksum": checksum,
        "timestamp": "2024-01-01T10:00:00",
        "source_node_id": "laptop-node-01",
        "payload": {"projects": projects},
    }

# ── CHECK 4: Missing API key → unauthorized ────────────
print("\n[4] Testing missing API key returns unauthorized...")
result = sync_mod.receive_snapshot(_make_snapshot(_make_projects(), 1), api_key="")
assert result["status"] == "unauthorized", f"Expected unauthorized, got {result}"
print("  PASS — Empty API key returns unauthorized")

# ── CHECK 5: Wrong API key → unauthorized ──────────────
print("\n[5] Testing wrong API key returns unauthorized...")
result = sync_mod.receive_snapshot(_make_snapshot(_make_projects(), 1), api_key="wrong-key")
assert result["status"] == "unauthorized", f"Expected unauthorized, got {result}"
print("  PASS — Wrong API key returns unauthorized")

# ── CHECK 6: Missing required fields → error ──────────
print("\n[6] Testing missing required fields returns error...")
bad_snap = {"version": 1, "payload": {"projects": []}}  # missing checksum + source_node_id
result = sync_mod.receive_snapshot(bad_snap, api_key="correct-api-key")
assert result["status"] == "error", f"Expected error, got {result}"
assert result["reason"] == "invalid_snapshot"
print("  PASS — Missing fields returns error/invalid_snapshot")

# ── CHECK 7: Valid snapshot accepted ──────────────────
print("\n[7] Testing valid snapshot is accepted...")
projects_v1 = _make_projects(n=3, version=1)
snap_v1 = _make_snapshot(projects_v1, version=1)
result = sync_mod.receive_snapshot(snap_v1, api_key="correct-api-key")
assert result["status"] == "ok", f"Expected ok, got {result}"
assert result["version"] == 1
assert result["count"] == 3
print(f"  PASS — Valid snapshot accepted: v{result['version']}, {result['count']} projects")

# ── CHECK 8: Stale version rejected ───────────────────
print("\n[8] Testing stale version is rejected...")
snap_stale = _make_snapshot(projects_v1, version=1)  # same version as current
result = sync_mod.receive_snapshot(snap_stale, api_key="correct-api-key")
assert result["status"] == "rejected", f"Expected rejected, got {result}"
assert result["reason"] == "stale"
print("  PASS — Stale version correctly rejected")

# ── CHECK 9: Tampered checksum rejected ───────────────
print("\n[9] Testing tampered checksum is rejected...")
projects_v2 = _make_projects(n=3, version=2)
snap_tampered = _make_snapshot(projects_v2, version=2, checksum="0" * 64)
result = sync_mod.receive_snapshot(snap_tampered, api_key="correct-api-key")
assert result["status"] == "rejected", f"Expected rejected, got {result}"
assert result["reason"] == "checksum_mismatch"
print("  PASS — Tampered checksum correctly rejected")

# ── CHECK 10: Projects stored correctly in SQLite ─────
print("\n[10] Verifying projects stored in SQLite after valid snapshot...")
all_projects = storage_mod.get_all_projects()
assert len(all_projects) == 3, f"Expected 3 projects, got {len(all_projects)}"
ids = {p["id"] for p in all_projects}
assert "proj-001" in ids and "proj-002" in ids and "proj-003" in ids
assert all_projects[0]["title"].startswith("Project")
print(f"  PASS — {len(all_projects)} projects in SQLite with correct data")

# ── CHECK 11: Sync version updated ────────────────────
print("\n[11] Verifying sync version updated after snapshot...")
ver = storage_mod.get_sync_version()
assert ver == 1, f"Expected version 1, got {ver}"
print(f"  PASS — sync_version={ver} in SQLite")

# ── CHECK 12: get_sync_status() structure ─────────────
print("\n[12] Testing get_sync_status() dict structure...")
status = sync_mod.get_sync_status()
required_keys = {"sync_version", "last_sync_time", "peer_status", "project_count"}
missing_keys = required_keys - set(status.keys())
assert not missing_keys, f"Missing keys: {missing_keys}"
assert status["sync_version"] == 1
assert status["project_count"] == 3
print(f"  PASS — get_sync_status(): {status}")

# ── CHECK 13: Laptop SyncService instantiates ─────────
print("\n[13] Testing laptop SyncService instantiation...")
from laptop.services.sync_service import SyncService

class MockLaptopSettings:
    NODE_ID = "laptop-test-node"
    NODE_ROLE = "primary"
    NODE_PORT = 18000
    PEER_PORT = 18001
    API_KEY = "test-api-key"
    SYNC_INTERVAL = 60   # long — won't fire during test

class MockRuntime:
    def __init__(self):
        self.sync_version = 0
        self.last_sync_time = None
        self.last_sync_checksum = None
        self.failover_active = False
        self.peer_host = None

    def get_peer_url(self, port):
        if self.peer_host is None:
            return None
        return f"http://{self.peer_host}:{port}"

    def update_sync(self, version, checksum):
        self.sync_version = version
        self.last_sync_time = time.time()
        self.last_sync_checksum = checksum

class MockSession:
    """Minimal SQLAlchemy-like session that returns fake Project rows."""
    def query(self, model):
        return self
    def all(self):
        return self._rows
    def close(self):
        pass
    _rows = []

class MockSessionFactory:
    def __call__(self):
        return MockSession()

laptop_rt = MockRuntime()
sync_svc = SyncService(
    settings=MockLaptopSettings(),
    runtime=laptop_rt,
    db_session_factory=MockSessionFactory(),
)
print("  PASS — SyncService instantiated")

# ── CHECK 14: push_now() is callable ──────────────────
print("\n[14] Testing push_now() method exists and is callable...")
assert callable(getattr(sync_svc, "push_now", None)), "push_now() not found"
sync_svc.push_now()   # runs in daemon thread — no crash
import threading as _t
import time as _t2
_t2.sleep(0.2)
print("  PASS — push_now() callable and non-blocking")

# ── CHECK 15: get_status() structure ──────────────────
print("\n[15] Testing laptop get_status() structure...")
s = sync_svc.get_status()
required_s = {"sync_version", "last_sync_time", "last_sync_checksum", "peer_reachable"}
missing_s = required_s - set(s.keys())
assert not missing_s, f"Missing keys: {missing_s}"
assert isinstance(s["peer_reachable"], bool)
print(f"  PASS — get_status() keys: {sorted(s.keys())}")

# ── CHECK 16: _build_snapshot() correct structure ─────
print("\n[16] Testing _build_snapshot() snapshot structure with mock DB...")

class FakeProject:
    def __init__(self, id, title):
        self.id = id
        self.title = title
        self.description = "desc"
        self.tech_stack = "Python"
        self.status = "active"
        self.created_at = None
        self.updated_at = None
        self.sync_version = 0
        self.checksum = None

class MockSessionWithRows:
    def query(self, model): return self
    def all(self): return [FakeProject("p1", "Alpha"), FakeProject("p2", "Beta")]
    def close(self): pass

class MockSessionFactoryWithRows:
    def __call__(self): return MockSessionWithRows()

sync_svc2 = SyncService(
    settings=MockLaptopSettings(),
    runtime=MockRuntime(),
    db_session_factory=MockSessionFactoryWithRows(),
)

snap = sync_svc2._build_snapshot()

assert "version" in snap,       "Missing version"
assert "checksum" in snap,      "Missing checksum"
assert "payload" in snap,       "Missing payload"
assert "source_node_id" in snap,"Missing source_node_id"
assert "projects" in snap["payload"], "Missing projects in payload"
assert len(snap["payload"]["projects"]) == 2
assert snap["version"] == 1   # first build, starts at 0 then increments
print(f"  PASS — _build_snapshot() structure correct: v{snap['version']}, "
      f"{len(snap['payload']['projects'])} projects")

# ── CHECK 17: Snapshot checksum matches recomputed ────
print("\n[17] Verifying snapshot checksum matches recomputed checksum...")
projects_in_snap = snap["payload"]["projects"]
recomputed = _compute_checksum(projects_in_snap)
assert snap["checksum"] == recomputed, (
    f"Checksum mismatch:\n  snap:       {snap['checksum']}\n  recomputed: {recomputed}"
)
print(f"  PASS — Checksum verified: {snap['checksum'][:16]}...")

# ── CHECK 18: Cleanup test database ───────────────────
print("\n[18] Cleaning up test database...")
pathlib.Path(_tmp_db).unlink(missing_ok=True)
assert not pathlib.Path(_tmp_db).exists()
print("  PASS — Test database removed")

# ── FINAL ─────────────────────────────────────────────
print("\n" + "=" * 55)
print("MODULE 9 COMPLETE — ALL CHECKS PASSED")
print("=" * 55)
print("\nReady to proceed to Module 10.")
