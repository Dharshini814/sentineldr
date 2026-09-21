"""
Module 8 Verification Script
Run from backend/: python verify_module8.py
Expected: All checks PASS
"""

import sys
import os
import ast
import json
import time
import pathlib
import tempfile
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

print("=" * 55)
print("MODULE 8 — FAILOVER & RECOVERY VERIFICATION")
print("=" * 55)

BACKEND = pathlib.Path(__file__).parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("API_KEY", "test-key-for-verification")

# ── CHECK 1: Files exist ───────────────────────────────
print("\n[1] Checking required files exist...")
required = [
    BACKEND / "phone" / "failover.py",
    BACKEND / "laptop" / "services" / "failover_service.py",
]
missing = [str(p) for p in required if not p.exists()]
if missing:
    print("  FAIL — Missing:\n    " + "\n    ".join(missing))
    sys.exit(1)
print("  PASS — All required files present")

# ── CHECK 2: Phone failover.py — zero third-party imports ──
print("\n[2] AST scan: phone/failover.py — zero third-party imports...")
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

phone_v = scan_imports(BACKEND / "phone" / "failover.py")
if phone_v:
    print(f"  FAIL — Third-party imports: {phone_v}")
    sys.exit(1)
print("  PASS — Zero third-party imports in phone/failover.py")

# ── CHECK 3: Laptop failover does not import phone ─────
print("\n[3] AST scan: laptop failover_service.py — no phone imports...")
src = (BACKEND / "laptop" / "services" / "failover_service.py").read_text(encoding="utf-8")
tree = ast.parse(src)
phone_imports = []
for node in ast.walk(tree):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        mod = ""
        if isinstance(node, ast.Import):
            mod = node.names[0].name.split(".")[0]
        elif node.module:
            mod = node.module.split(".")[0]
        if mod == "phone":
            phone_imports.append(mod)
if phone_imports:
    print(f"  FAIL — Laptop imports phone: {phone_imports}")
    sys.exit(1)
print("  PASS — Laptop failover does not import phone modules")

# ── Setup: temp SQLite for phone tests ─────────────────
_tmp_db = str(BACKEND / "phone" / "_verify8_test.db")

import phone.storage as storage_mod
storage_mod.init_storage(_tmp_db)

# Minimal mock objects
class MockPhoneConfig:
    NODE_ID = "phone-test-node"
    NODE_ROLE = "secondary"
    FAILOVER_COOLDOWN = 30
    API_KEY = "test-key"
    PEER_PORT = 18000

def fresh_runtime():
    return {
        "peer_host": None,
        "peer_node_id": None,
        "peer_role": None,
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

import phone.failover as failover_mod

def init_fresh(rt=None):
    if rt is None:
        rt = fresh_runtime()
    failover_mod.init_failover(
        config_module=MockPhoneConfig(),
        runtime_dict=rt,
        storage_module=storage_mod,
    )
    return rt

# ── CHECK 4: trigger_failover() sets runtime fields ────
print("\n[4] Testing trigger_failover() sets all runtime fields...")
rt4 = init_fresh()
failover_mod.trigger_failover()

assert rt4["failover_active"] == True,  f"failover_active={rt4['failover_active']}"
assert rt4["peer_status"] == "offline",  f"peer_status={rt4['peer_status']}"
assert rt4["failover_time"] is not None, "failover_time not set"
assert isinstance(rt4["failover_time"], float)
print("  PASS — trigger_failover() sets failover_active=True, peer_status=offline")

# ── CHECK 5: Double trigger — cooldown blocks re-trigger ──
print("\n[5] Testing cooldown blocks double trigger...")
rt5 = init_fresh()
rt5["failover_active"] = False

failover_mod.trigger_failover()   # first trigger
ft1 = rt5["failover_time"]
assert rt5["failover_active"] == True

failover_mod.trigger_failover()   # second trigger — should be blocked
ft2 = rt5["failover_time"]

assert ft1 == ft2, f"failover_time changed on second call: {ft1} → {ft2}"
print("  PASS — Cooldown blocks double trigger (failover_time unchanged)")

# ── CHECK 6: is_in_failover() returns True ─────────────
print("\n[6] Testing is_in_failover() after trigger...")
rt6 = init_fresh()
assert failover_mod.is_in_failover() == False  # starts False (uses rt6)
failover_mod.trigger_failover()
assert failover_mod.is_in_failover() == True
print("  PASS — is_in_failover() correct before and after trigger")

# ── CHECK 7: get_failover_status() structure ───────────
print("\n[7] Testing get_failover_status() dict structure...")
status = failover_mod.get_failover_status()
required_keys = {"failover_active", "failover_time", "peer_status", "role"}
missing_keys = required_keys - set(status.keys())
assert not missing_keys, f"Missing keys: {missing_keys}"
print(f"  PASS — get_failover_status() keys: {sorted(status.keys())}")

# ── CHECK 8: role = active_secondary when in failover ──
print("\n[8] Testing role = 'active_secondary' when in failover...")
rt8 = init_fresh()
failover_mod.trigger_failover()
s8 = failover_mod.get_failover_status()
assert s8["role"] == "active_secondary", f"role={s8['role']}"
print(f"  PASS — role='{s8['role']}' when in failover")

# ── CHECK 9: role = secondary when not in failover ─────
print("\n[9] Testing role = 'secondary' when not in failover...")
rt9 = init_fresh()
rt9["failover_active"] = False
failover_mod.init_failover(runtime_dict=rt9)
s9 = failover_mod.get_failover_status()
assert s9["role"] == "secondary", f"role={s9['role']}"
print(f"  PASS — role='{s9['role']}' when not in failover")

# ── Spin up a tiny HTTP server for recovery tests ──────
_health_responses = {}   # port -> (status_code, body_dict)

class _MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass   # silence request logs
    def do_GET(self):
        port = self.server.server_address[1]
        code, body = _health_responses.get(port, (200, {"status": "healthy"}))
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

def _start_mock_server(port, status_code, body):
    _health_responses[port] = (status_code, body)
    srv = HTTPServer(("127.0.0.1", port), _MockHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv

# ── CHECK 10: trigger_recovery() with healthy peer ─────
print("\n[10] Testing trigger_recovery() with mock healthy peer...")
rt10 = init_fresh()
rt10["failover_active"] = True
rt10["peer_status"] = "offline"
rt10["missed_heartbeats"] = 5

srv10 = _start_mock_server(19010, 200, {"status": "healthy"})
time.sleep(0.1)

failover_mod.init_failover(runtime_dict=rt10, storage_module=storage_mod)
failover_mod.trigger_recovery("http://127.0.0.1:19010")
srv10.shutdown()

assert rt10["failover_active"] == False, f"failover_active={rt10['failover_active']}"
assert rt10["peer_status"] == "healthy",  f"peer_status={rt10['peer_status']}"
assert rt10["missed_heartbeats"] == 0,    f"missed={rt10['missed_heartbeats']}"
print("  PASS — trigger_recovery() resets failover state with healthy peer")

# ── CHECK 11: trigger_recovery() with unhealthy peer ───
print("\n[11] Testing trigger_recovery() with mock unhealthy peer (degraded)...")
rt11 = init_fresh()
rt11["failover_active"] = True
rt11["peer_status"] = "offline"

srv11 = _start_mock_server(19011, 200, {"status": "degraded"})
time.sleep(0.1)

failover_mod.init_failover(runtime_dict=rt11, storage_module=storage_mod)
failover_mod.trigger_recovery("http://127.0.0.1:19011")
srv11.shutdown()

assert rt11["failover_active"] == True,  f"Should stay in failover — got {rt11['failover_active']}"
assert rt11["peer_status"] == "offline", f"Should stay offline — got {rt11['peer_status']}"
print("  PASS — trigger_recovery() stays in failover when peer reports non-healthy status")

# ── CHECK 12: trigger_recovery() with unreachable peer ─
print("\n[12] Testing trigger_recovery() with unreachable peer — no crash...")
rt12 = init_fresh()
rt12["failover_active"] = True

failover_mod.init_failover(runtime_dict=rt12, storage_module=storage_mod)
try:
    failover_mod.trigger_recovery("http://127.0.0.1:19099")  # nothing listening
    print("  PASS — No exception from unreachable peer")
except Exception as e:
    print(f"  FAIL — Exception raised: {e}")
    sys.exit(1)

assert rt12["failover_active"] == True, "Should stay in failover on unreachable peer"
print("  PASS — Failover state unchanged after unreachable peer")

# ── CHECK 13: failover_active=False after recovery ─────
print("\n[13] Verifying failover_active=False after successful recovery...")
assert rt10["failover_active"] == False   # already checked in check 10
print("  PASS — failover_active=False after trigger_recovery()")

# ── CHECK 14: missed_heartbeats=0 after recovery ───────
print("\n[14] Verifying missed_heartbeats=0 after successful recovery...")
assert rt10["missed_heartbeats"] == 0
print("  PASS — missed_heartbeats=0 after trigger_recovery()")

# ── CHECK 15: Failover event saved to SQLite ───────────
print("\n[15] Verifying failover event saved to SQLite...")
events = storage_mod.get_events(limit=100)
failover_events = [e for e in events if e["event_type"] == "FAILOVER"]
assert len(failover_events) >= 1, f"No FAILOVER events found. Events: {[e['event_type'] for e in events]}"
assert failover_events[0]["severity"] == "CRITICAL"
print(f"  PASS — {len(failover_events)} FAILOVER event(s) in SQLite")

# ── CHECK 16: Recovery event saved to SQLite ───────────
print("\n[16] Verifying recovery event saved to SQLite...")
recovery_events = [e for e in events if e["event_type"] == "RECOVERY"]
assert len(recovery_events) >= 1, f"No RECOVERY events found. Events: {[e['event_type'] for e in events]}"
assert recovery_events[0]["severity"] == "SUCCESS"
print(f"  PASS — {len(recovery_events)} RECOVERY event(s) in SQLite")

# ── CHECK 17: Laptop FailoverService instantiates ──────
print("\n[17] Testing laptop FailoverService instantiation...")
from laptop.services.failover_service import FailoverService as LaptopFS
from laptop.config import RuntimeState

class MockLaptopSettings:
    NODE_ID = "laptop-test-node"
    NODE_ROLE = "primary"
    NODE_PORT = 18000
    PEER_PORT = 18001
    API_KEY = "test-api-key"

laptop_rt = RuntimeState()
laptop_fs = LaptopFS(settings=MockLaptopSettings(), runtime=laptop_rt)
laptop_fs.start()
print("  PASS — Laptop FailoverService instantiated and started")

# ── CHECK 18: Laptop get_status() structure ────────────
print("\n[18] Testing laptop get_status() dict structure...")
status = laptop_fs.get_status()
required = {"failover_active", "failover_time", "peer_status"}
missing_k = required - set(status.keys())
assert not missing_k, f"Missing keys: {missing_k}"
assert isinstance(status["failover_active"], bool)
print(f"  PASS — get_status() keys: {sorted(status.keys())}")

# ── Confirm record_peer_failover sets failover_active ──
laptop_fs.record_peer_failover()
assert laptop_rt.failover_active == True
laptop_fs.coordinate_failback()
assert laptop_rt.failover_active == False
assert laptop_rt.peer_status == "healthy"
print("  PASS — record_peer_failover() and coordinate_failback() correct")

# ── Cleanup ────────────────────────────────────────────
pathlib.Path(_tmp_db).unlink(missing_ok=True)

# ── FINAL ─────────────────────────────────────────────
print("\n" + "=" * 55)
print("MODULE 8 COMPLETE — ALL CHECKS PASSED")
print("=" * 55)
print("\nReady to proceed to Module 9.")
