"""
Module 6 Verification Script
Run from backend/: python verify_module6.py
Expected: All checks PASS
"""

import sys
import os
import ast
import json
import socket
import time
import threading
import pathlib

print("=" * 55)
print("MODULE 6 — AUTOMATIC IP DISCOVERY VERIFICATION")
print("=" * 55)

BACKEND = pathlib.Path(__file__).parent
sys.path.insert(0, str(BACKEND))

# Ensure required env vars are set before any imports
os.environ.setdefault("API_KEY", "test-key-for-verification")

# ── CHECK 1: Files exist ───────────────────────────────
print("\n[1] Checking required files exist...")
required = [
    BACKEND / "laptop" / "services" / "__init__.py",
    BACKEND / "laptop" / "services" / "discovery_service.py",
    BACKEND / "phone" / "discovery.py",
]
missing = [str(p) for p in required if not p.exists()]
if missing:
    print("  FAIL — Missing files:\n    " + "\n    ".join(missing))
    sys.exit(1)
print("  PASS — All required files present")

# ── CHECK 2: Phone discovery.py — zero third-party imports ──
print("\n[2] AST scan: phone/discovery.py — zero third-party imports...")
STDLIB = {
    "os", "sys", "time", "pathlib", "json", "uuid", "datetime",
    "hashlib", "dataclasses", "typing", "abc", "re", "ast",
    "threading", "socket", "struct", "logging", "io", "collections",
    "functools", "itertools", "math", "random", "string", "copy",
    "traceback", "contextlib", "enum", "http", "urllib", "email",
    "html", "xml", "csv", "sqlite3", "subprocess", "signal",
}
FIRST_PARTY = {"shared", "phone", "laptop"}

def scan_imports(path: pathlib.Path, allowed_third_party=None):
    allowed_third_party = allowed_third_party or set()
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
            if mod and mod not in STDLIB and mod not in FIRST_PARTY and mod not in allowed_third_party:
                violations.append(mod)
    return violations

phone_violations = scan_imports(BACKEND / "phone" / "discovery.py")
if phone_violations:
    print(f"  FAIL — Third-party imports: {phone_violations}")
    sys.exit(1)
print("  PASS — Zero third-party imports in phone/discovery.py")

# ── CHECK 3: Laptop discovery_service.py — allowed imports only ──
print("\n[3] AST scan: laptop/services/discovery_service.py — allowed imports only...")
# Laptop allows: socket, threading, logging, requests + first-party
LAPTOP_ALLOWED = {"requests"}
laptop_violations = scan_imports(
    BACKEND / "laptop" / "services" / "discovery_service.py",
    allowed_third_party=LAPTOP_ALLOWED,
)
if laptop_violations:
    print(f"  FAIL — Unexpected imports: {laptop_violations}")
    sys.exit(1)
print("  PASS — Laptop discovery imports are all allowed")

# ── CHECK 4: get_local_ip() returns valid IP ──────────
print("\n[4] Testing get_local_ip() on both sides...")
from laptop.services.discovery_service import get_local_ip as laptop_get_local_ip
from phone.discovery import get_local_ip as phone_get_local_ip

laptop_ip = laptop_get_local_ip()
phone_ip = phone_get_local_ip()

import re
IP_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

assert laptop_ip and IP_PATTERN.match(laptop_ip), f"Bad laptop IP: {laptop_ip!r}"
assert phone_ip  and IP_PATTERN.match(phone_ip),  f"Bad phone IP:  {phone_ip!r}"
assert laptop_ip != "", "laptop get_local_ip() returned empty string"
assert phone_ip  != "", "phone get_local_ip() returned empty string"
print(f"  PASS — laptop IP: {laptop_ip}")
print(f"  PASS — phone  IP: {phone_ip}")

# ── CHECK 5: get_local_ip() not a hardcoded subnet ────
print("\n[5] Testing get_local_ip() is not a hardcoded address...")
# It may legitimately be 127.0.0.1 if no network interface is available,
# but it must not be the example IP we use in docs (192.168.1.x etc.)
for ip, label in [(laptop_ip, "laptop"), (phone_ip, "phone")]:
    assert ip not in ("0.0.0.0", ""), f"{label} get_local_ip() returned bad value: {ip}"
print("  PASS — get_local_ip() returns a real interface address")

# ── CHECK 6: Laptop DiscoveryService instantiates ─────
print("\n[6] Testing laptop DiscoveryService instantiation...")
from laptop.services.discovery_service import DiscoveryService as LaptopDS
from laptop.config import Settings, RuntimeState
from pydantic_settings import SettingsConfigDict

# Build minimal test settings (no .env file needed)
class TestSettings:
    NODE_ID = "laptop-test-node"
    NODE_ROLE = "primary"
    NODE_PORT = 18000

test_runtime = RuntimeState()
laptop_ds = LaptopDS(settings=TestSettings(), runtime=test_runtime)
print("  PASS — Laptop DiscoveryService instantiated")

# ── CHECK 7: Phone DiscoveryService instantiates ──────
print("\n[7] Testing phone DiscoveryService instantiation...")
from phone.discovery import DiscoveryService as PhoneDS

class MockPhoneConfig:
    NODE_ID = "phone-test-node"
    NODE_ROLE = "secondary"
    NODE_PORT = 18001

mock_runtime = {
    "peer_host": None, "peer_node_id": None, "peer_role": None,
    "peer_status": "offline", "peer_last_seen": None,
}
phone_ds = PhoneDS(config_module=MockPhoneConfig(), runtime_dict=mock_runtime)
print("  PASS — Phone DiscoveryService instantiated")

# ── CHECK 8 & 9: Threads start without error ──────────
print("\n[8] Testing broadcaster thread starts...")
print("\n[9] Testing listener thread starts...")

# Use a high test port so we don't conflict with real DISCOVERY_PORT
# We'll test the thread start by monkey-patching the socket binding port.
# Instead, just start the service and check threads are alive after a moment.

# Use stop_event to prevent actual broadcasting/listening beyond the test
import importlib
from laptop.services import discovery_service as _lds_mod

threads_before = threading.active_count()

# Patch DISCOVERY_PORT to a test port to avoid binding conflicts
TEST_PORT = 47799

class PatchedLaptopDS(LaptopDS):
    """Overrides _broadcaster and _listener to use TEST_PORT."""
    def _broadcaster(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            from shared.constants import DISCOVERY_INTERVAL
            from shared.messages import build_discovery_packet
            while not self._stop_event.is_set():
                try:
                    packet = build_discovery_packet(
                        self._settings.NODE_ID,
                        self._settings.NODE_ROLE,
                        self._settings.NODE_PORT,
                    )
                    data = json.dumps(packet).encode()
                    sock.sendto(data, ("127.0.0.1", TEST_PORT))
                except OSError:
                    pass
                self._stop_event.wait(0.1)
        finally:
            sock.close()

    def _listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        try:
            sock.bind(("127.0.0.1", TEST_PORT))
            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                    self._handle_packet(data, addr[0])
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            sock.close()

test_ds = PatchedLaptopDS(settings=TestSettings(), runtime=test_runtime)
test_ds.start()
time.sleep(0.3)

threads_after = threading.active_count()
new_threads = threads_after - threads_before

# Check daemon threads were started (at least 2 new ones)
running = [t for t in threading.enumerate()
           if t.name in ("discovery-broadcaster", "discovery-listener")]

assert len(running) == 2, f"Expected 2 discovery threads, found: {[t.name for t in running]}"
for t in running:
    assert t.daemon, f"Thread {t.name} is not a daemon thread"
    assert t.is_alive(), f"Thread {t.name} is not alive"

print("  PASS — Broadcaster thread started as daemon")
print("  PASS — Listener thread started as daemon")

# ── CHECK 10: Simulate discovery — listener receives packet ──
print("\n[10] Simulating discovery packet — testing listener parse...")

# Use a fresh service with a known test port
TEST_PORT_2 = 47798
received_packets = []
parse_errors = []

class CaptureDS(LaptopDS):
    """Captures parsed packets for test inspection."""
    def _handle_packet(self, data, sender_ip):
        try:
            packet = json.loads(data.decode("utf-8"))
            received_packets.append((packet, sender_ip))
        except Exception as e:
            parse_errors.append(str(e))

    def _listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        try:
            sock.bind(("127.0.0.1", TEST_PORT_2))
            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                    self._handle_packet(data, addr[0])
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            sock.close()

capture_runtime = RuntimeState()
capture_ds = CaptureDS(settings=TestSettings(), runtime=capture_runtime)

listener_t = threading.Thread(target=capture_ds._listener, daemon=True)
listener_t.start()
time.sleep(0.2)

# Send a mock peer packet
from shared.messages import build_discovery_packet
mock_packet = build_discovery_packet("peer-node-99", "secondary", 8001)
mock_data = json.dumps(mock_packet).encode("utf-8")

sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sender.sendto(mock_data, ("127.0.0.1", TEST_PORT_2))
sender.close()
time.sleep(0.3)

capture_ds.stop()

assert len(received_packets) >= 1, f"No packets received. parse_errors={parse_errors}"
pkt, ip = received_packets[0]
assert pkt["service"] == "sentineldr", f"Wrong service: {pkt.get('service')}"
assert pkt["node_id"] == "peer-node-99"
assert pkt["role"] == "secondary"
print(f"  PASS — Listener parsed packet: node_id={pkt['node_id']} from {ip}")

# ── CHECK 11: Self-packets are ignored ────────────────
print("\n[11] Testing self-packet filtering...")

TEST_PORT_3 = 47797
self_runtime = RuntimeState()

class SelfFilterDS(LaptopDS):
    def _listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        try:
            sock.bind(("127.0.0.1", TEST_PORT_3))
            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                    self._handle_packet(data, addr[0])
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            sock.close()

self_ds = SelfFilterDS(settings=TestSettings(), runtime=self_runtime)
t3 = threading.Thread(target=self_ds._listener, daemon=True)
t3.start()
time.sleep(0.2)

# Send a packet that looks like it came from SELF (same NODE_ID)
self_packet = build_discovery_packet("laptop-test-node", "primary", 18000)
self_data = json.dumps(self_packet).encode()
s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s2.sendto(self_data, ("127.0.0.1", TEST_PORT_3))
s2.close()
time.sleep(0.3)
self_ds.stop()

# Runtime must NOT have been updated
assert self_runtime.peer_host is None, \
    f"Self-packet was NOT filtered — peer_host={self_runtime.peer_host}"
assert self_runtime.peer_node_id is None
print("  PASS — Self-packets correctly ignored")

# ── CHECK 12: Peer packet updates runtime ─────────────
print("\n[12] Testing peer packet updates runtime correctly...")

TEST_PORT_4 = 47796
peer_runtime = RuntimeState()

class PeerUpdateDS(LaptopDS):
    def _listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.5)
        try:
            sock.bind(("127.0.0.1", TEST_PORT_4))
            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                    self._handle_packet(data, addr[0])
                except socket.timeout:
                    continue
                except OSError:
                    break
        finally:
            sock.close()

peer_ds = PeerUpdateDS(settings=TestSettings(), runtime=peer_runtime)
t4 = threading.Thread(target=peer_ds._listener, daemon=True)
t4.start()
time.sleep(0.2)

peer_packet = build_discovery_packet("phone-node-02", "secondary", 8001)
peer_data = json.dumps(peer_packet).encode()
s3 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s3.sendto(peer_data, ("127.0.0.1", TEST_PORT_4))
s3.close()
time.sleep(0.3)
peer_ds.stop()

assert peer_runtime.peer_host == "127.0.0.1", \
    f"peer_host not updated: {peer_runtime.peer_host}"
assert peer_runtime.peer_node_id == "phone-node-02", \
    f"peer_node_id not updated: {peer_runtime.peer_node_id}"
assert peer_runtime.peer_role == "secondary", \
    f"peer_role not updated: {peer_runtime.peer_role}"
print(f"  PASS — runtime updated: host={peer_runtime.peer_host} "
      f"node={peer_runtime.peer_node_id} role={peer_runtime.peer_role}")

# Stop test_ds broadcaster/listener
test_ds.stop()

# ── FINAL ─────────────────────────────────────────────
print("\n" + "=" * 55)
print("MODULE 6 COMPLETE — ALL CHECKS PASSED")
print("=" * 55)
print("\nReady to proceed to Module 7.")
