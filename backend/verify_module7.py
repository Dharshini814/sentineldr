"""
Module 7 Verification Script
Run from backend/: python verify_module7.py
Expected: All checks PASS
"""

import sys
import os
import ast
import time
import threading
import pathlib

print("=" * 55)
print("MODULE 7 — HEARTBEAT SERVICE VERIFICATION")
print("=" * 55)

BACKEND = pathlib.Path(__file__).parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("API_KEY", "test-key-for-verification")

# ── CHECK 1: Files exist ───────────────────────────────
print("\n[1] Checking required files exist...")
required = [
    BACKEND / "laptop" / "services" / "heartbeat_service.py",
    BACKEND / "phone" / "heartbeat.py",
]
missing = [str(p) for p in required if not p.exists()]
if missing:
    print("  FAIL — Missing:\n    " + "\n    ".join(missing))
    sys.exit(1)
print("  PASS — All required files present")

# ── CHECK 2: Phone heartbeat.py — zero third-party imports ──
print("\n[2] AST scan: phone/heartbeat.py — zero third-party imports...")
STDLIB = {
    "os", "sys", "time", "pathlib", "json", "uuid", "datetime",
    "hashlib", "dataclasses", "typing", "abc", "re", "ast",
    "threading", "socket", "struct", "logging", "io", "collections",
    "functools", "itertools", "math", "random", "string", "copy",
    "traceback", "contextlib", "enum", "http", "urllib", "email",
    "html", "xml", "csv", "sqlite3", "subprocess", "signal",
}
FIRST_PARTY = {"shared", "phone", "laptop"}

def scan_imports(path, allowed_third_party=None):
    allowed = allowed_third_party or set()
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

phone_v = scan_imports(BACKEND / "phone" / "heartbeat.py")
if phone_v:
    print(f"  FAIL — Third-party imports: {phone_v}")
    sys.exit(1)
print("  PASS — Zero third-party imports in phone/heartbeat.py")

# ── CHECK 3: Laptop heartbeat does not import phone modules ──
print("\n[3] AST scan: laptop heartbeat does not import phone modules...")
src = (BACKEND / "laptop" / "services" / "heartbeat_service.py").read_text(encoding="utf-8")
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
    print(f"  FAIL — Laptop imports phone modules: {phone_imports}")
    sys.exit(1)
print("  PASS — Laptop heartbeat does not import phone modules")

# ── Helper: minimal mock settings and runtime ──────────
class MockSettings:
    NODE_ID = "laptop-test-node"
    NODE_ROLE = "primary"
    NODE_PORT = 18000
    PEER_PORT = 18001
    API_KEY = "test-api-key"
    HEARTBEAT_INTERVAL = 60   # long — so loop doesn't fire during test
    HEARTBEAT_TIMEOUT = 1
    MISSED_HEARTBEAT_THRESHOLD = 3

class MockRuntime:
    def __init__(self):
        self.peer_host = None
        self.peer_node_id = None
        self.peer_role = None
        self.peer_status = "offline"
        self.peer_last_seen = None
        self.missed_heartbeats = 0
        self.failover_active = False
        self.heartbeat_sequence = 0
        self._start = time.time()

    def get_uptime(self): return time.time() - self._start
    def get_peer_url(self, port):
        if self.peer_host is None: return None
        return f"http://{self.peer_host}:{port}"
    def update_peer_healthy(self):
        self.peer_last_seen = time.time()
        self.peer_status = "healthy"
        self.missed_heartbeats = 0
    def increment_missed_heartbeat(self):
        self.missed_heartbeats += 1
        return self.missed_heartbeats
    def mark_peer_offline(self):
        self.peer_status = "offline"

class MockPhoneConfig:
    NODE_ID = "phone-test-node"
    NODE_ROLE = "secondary"
    NODE_PORT = 18001
    PEER_PORT = 18000
    API_KEY = "test-api-key"
    HEARTBEAT_INTERVAL = 60
    HEARTBEAT_TIMEOUT = 1
    MISSED_HEARTBEAT_THRESHOLD = 3

# ── CHECK 4: Laptop HeartbeatService instantiates ─────
print("\n[4] Testing laptop HeartbeatService instantiation...")
from laptop.services.heartbeat_service import HeartbeatService as LaptopHS
laptop_rt = MockRuntime()
laptop_hs = LaptopHS(settings=MockSettings(), runtime=laptop_rt)
print("  PASS — Laptop HeartbeatService instantiated")

# ── CHECK 5: Phone HeartbeatService instantiates ──────
print("\n[5] Testing phone HeartbeatService instantiation...")
from phone.heartbeat import HeartbeatService as PhoneHS
phone_rt = {
    "peer_host": None, "peer_node_id": None, "peer_role": None,
    "peer_status": "offline", "peer_last_seen": None,
    "missed_heartbeats": 0, "failover_active": False,
    "heartbeat_sequence": 0, "start_time": time.time(),
    "sync_version": 0, "last_sync_time": None,
    "last_sync_checksum": None, "failover_time": None,
}
phone_hs = PhoneHS(config_module=MockPhoneConfig(), runtime_dict=phone_rt)
print("  PASS — Phone HeartbeatService instantiated")

# ── CHECK 6: Laptop send loop starts as daemon ─────────
print("\n[6] Testing laptop send loop starts as daemon thread...")
laptop_hs2 = LaptopHS(settings=MockSettings(), runtime=MockRuntime())
laptop_hs2.start()
time.sleep(0.2)
threads = [t for t in threading.enumerate() if t.name == "heartbeat-sender"]
assert len(threads) >= 1, "heartbeat-sender thread not found"
assert threads[0].daemon, "heartbeat-sender is not a daemon thread"
assert threads[0].is_alive()
print("  PASS — Laptop heartbeat-sender daemon thread running")

# ── CHECK 7: Phone send loop starts as daemon ──────────
print("\n[7] Testing phone send loop starts as daemon thread...")
phone_hs2 = PhoneHS(config_module=MockPhoneConfig(), runtime_dict=dict(phone_rt))
phone_hs2.start()
time.sleep(0.2)
threads_p = [t for t in threading.enumerate() if t.name == "phone-heartbeat-sender"]
assert len(threads_p) >= 1, "phone-heartbeat-sender thread not found"
assert threads_p[0].daemon, "phone-heartbeat-sender is not a daemon thread"
assert threads_p[0].is_alive()
print("  PASS — Phone phone-heartbeat-sender daemon thread running")

# ── CHECK 8: handle_incoming() returns correct structure ──
print("\n[8] Testing laptop handle_incoming() dict structure...")
rt8 = MockRuntime()
hs8 = LaptopHS(settings=MockSettings(), runtime=rt8)
result = hs8.handle_incoming(
    node_id="phone-node-02",
    role="secondary",
    sequence=5,
    status="healthy",
)
required_keys = {"node_id", "role", "status", "timestamp", "sequence", "uptime_seconds"}
missing_keys = required_keys - set(result.keys())
assert not missing_keys, f"Missing keys: {missing_keys}"
assert result["node_id"] == "laptop-test-node"
assert result["role"] == "primary"
assert result["status"] == "healthy"
assert isinstance(result["uptime_seconds"], float)
assert isinstance(result["sequence"], int)
print(f"  PASS — handle_incoming() returns: {list(result.keys())}")

# ── CHECK 9: Successful heartbeat updates runtime ─────
print("\n[9] Testing successful heartbeat updates runtime correctly...")
rt9 = MockRuntime()
rt9.peer_host = "127.0.0.1"   # peer known
hs9 = LaptopHS(settings=MockSettings(), runtime=rt9)

# Mock a 200 response by calling _tick with a mock requests module
import unittest.mock as mock

mock_resp = mock.MagicMock()
mock_resp.status_code = 200

with mock.patch("requests.get", return_value=mock_resp):
    hs9._tick(
        timeout=1,
        threshold=MockSettings.MISSED_HEARTBEAT_THRESHOLD,
        peer_port=MockSettings.PEER_PORT,
    )

assert rt9.peer_status == "healthy", f"peer_status={rt9.peer_status}"
assert rt9.missed_heartbeats == 0
assert rt9.heartbeat_sequence == 1
print("  PASS — Successful heartbeat sets peer_status=healthy, seq=1")

# ── CHECK 10: Failed heartbeat increments missed counter ──
print("\n[10] Testing failed heartbeat increments missed counter...")
rt10 = MockRuntime()
rt10.peer_host = "127.0.0.1"
hs10 = LaptopHS(settings=MockSettings(), runtime=rt10)

import requests as req_lib
with mock.patch("requests.get", side_effect=req_lib.exceptions.ConnectionError("refused")):
    hs10._tick(timeout=1, threshold=3, peer_port=18001)

assert rt10.missed_heartbeats == 1, f"missed={rt10.missed_heartbeats}"
assert rt10.peer_status != "healthy"  # not explicitly reset yet — still "offline"
print(f"  PASS — Failed heartbeat: missed_heartbeats={rt10.missed_heartbeats}")

# ── CHECK 11: Threshold reached — laptop marks peer offline ──
print("\n[11] Testing laptop threshold reached — peer marked offline...")
rt11 = MockRuntime()
rt11.peer_host = "127.0.0.1"
rt11.peer_status = "healthy"  # start healthy
hs11 = LaptopHS(settings=MockSettings(), runtime=rt11)

with mock.patch("requests.get", side_effect=req_lib.exceptions.ConnectionError("refused")):
    hs11._tick(timeout=1, threshold=3, peer_port=18001)
    hs11._tick(timeout=1, threshold=3, peer_port=18001)
    hs11._tick(timeout=1, threshold=3, peer_port=18001)

assert rt11.missed_heartbeats >= 3
assert rt11.peer_status == "offline", f"peer_status={rt11.peer_status}"
print(f"  PASS — Laptop marks peer offline at threshold (missed={rt11.missed_heartbeats})")

# ── CHECK 11b: Laptop does NOT have failover trigger ──
print("       Confirming laptop does not trigger failover...")
src_laptop = (BACKEND / "laptop" / "services" / "heartbeat_service.py").read_text()
assert "trigger_failover" not in src_laptop, \
    "FAIL — Laptop heartbeat should NOT call trigger_failover"
print("  PASS — Laptop heartbeat has no failover trigger (correct)")

# ── CHECK 12: Phone missed heartbeat counter increments ──
print("\n[12] Testing phone missed heartbeat counter increments...")
rt12 = dict(phone_rt)
rt12["peer_host"] = "127.0.0.1"

class MockPhoneConfigFast(MockPhoneConfig):
    HEARTBEAT_TIMEOUT = 0    # immediate timeout
    MISSED_HEARTBEAT_THRESHOLD = 3

hs12 = PhoneHS(config_module=MockPhoneConfigFast(), runtime_dict=rt12)

# Call _tick directly — connection to 127.0.0.1:18000 should fail (nothing listening)
hs12._tick(timeout=0, threshold=3, peer_port=18000)
assert rt12["missed_heartbeats"] >= 1, f"missed={rt12['missed_heartbeats']}"
print(f"  PASS — Phone missed counter: {rt12['missed_heartbeats']}")

# ── CHECK 13: Phone threshold triggers failover ────────
print("\n[13] Testing phone threshold detection fires failover...")
rt13 = dict(phone_rt)
rt13["peer_host"] = "127.0.0.1"
rt13["missed_heartbeats"] = 0
failover_called = []

hs13 = PhoneHS(config_module=MockPhoneConfigFast(), runtime_dict=rt13)

# Patch _trigger_failover to capture the call
original_trigger = hs13._trigger_failover
hs13._trigger_failover = lambda: failover_called.append(True)

# Force 3 misses to hit threshold
for _ in range(3):
    hs13._on_miss(threshold=3, reason="test-timeout")

assert len(failover_called) >= 1, \
    f"_trigger_failover not called after threshold. missed={rt13['missed_heartbeats']}"
assert rt13["peer_status"] == "offline"
print(f"  PASS — Phone triggers failover at threshold (missed={rt13['missed_heartbeats']})")

# ── CHECK 14: All failures caught gracefully ───────────
print("\n[14] Testing all network failures caught gracefully (no crash)...")
rt14 = dict(phone_rt)
rt14["peer_host"] = "192.0.2.99"   # TEST-NET — guaranteed unreachable
hs14 = PhoneHS(config_module=MockPhoneConfigFast(), runtime_dict=rt14)

try:
    hs14._tick(timeout=0, threshold=99, peer_port=9)
    # No exception should escape
    print("  PASS — Network failure caught gracefully (no exception)")
except Exception as e:
    print(f"  FAIL — Uncaught exception: {e}")
    sys.exit(1)

# ── FINAL ─────────────────────────────────────────────
print("\n" + "=" * 55)
print("MODULE 7 COMPLETE — ALL CHECKS PASSED")
print("=" * 55)
print("\nReady to proceed to Module 8.")
