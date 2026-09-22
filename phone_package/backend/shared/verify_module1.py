"""
Module 1 Verification Script
Run: python verify_module1.py
Expected: All checks PASS, no exceptions
"""

import sys
import json
from pathlib import Path

# Add parent to path so shared imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

print("=" * 50)
print("MODULE 1 — SHARED PROTOCOL LAYER VERIFICATION")
print("=" * 50)

# ── CHECK 1: Imports ──────────────────────────────
print("\n[1] Testing imports...")
try:
    from shared.constants import (
        DISCOVERY_PORT, HEARTBEAT_INTERVAL, ROLE_PRIMARY,
        STATUS_HEALTHY, SEV_CRITICAL, EVT_FAILOVER,
        PROTOCOL_VERSION, SERVICE_NAME
    )
    from shared.protocol import (
        DiscoveryPacket, HeartbeatPacket,
        SyncSnapshot, NodeInfo, AlertEvent
    )
    from shared.messages import (
        build_discovery_packet, build_heartbeat,
        build_sync_snapshot, build_event,
        build_failover_alert, build_recovery_alert,
        build_discovery_event, build_sync_event
    )
    print("  PASS — All imports successful")
except ImportError as e:
    print(f"  FAIL — Import error: {e}")
    sys.exit(1)

# ── CHECK 2: Constants ────────────────────────────
print("\n[2] Testing constants...")
assert DISCOVERY_PORT == 47777, "DISCOVERY_PORT wrong"
assert HEARTBEAT_INTERVAL == 3, "HEARTBEAT_INTERVAL wrong"
assert ROLE_PRIMARY == "primary", "ROLE_PRIMARY wrong"
assert STATUS_HEALTHY == "healthy", "STATUS_HEALTHY wrong"
assert SEV_CRITICAL == "CRITICAL", "SEV_CRITICAL wrong"
assert EVT_FAILOVER == "FAILOVER", "EVT_FAILOVER wrong"
print("  PASS — All constants correct")

# ── CHECK 3: DiscoveryPacket ──────────────────────
print("\n[3] Testing DiscoveryPacket...")
pkt = DiscoveryPacket(
    service="sentineldr",
    protocol_version=1,
    node_id="laptop-node-01",
    role="primary",
    port=8000,
    timestamp="2024-01-01T00:00:00"
)
d = pkt.to_dict()
assert d["service"] == "sentineldr"
assert d["node_id"] == "laptop-node-01"
assert d["port"] == 8000

pkt2 = DiscoveryPacket.from_dict(d)
assert pkt2.node_id == pkt.node_id
assert pkt2.role == pkt.role

# JSON round-trip
json_str = json.dumps(d)
d2 = json.loads(json_str)
pkt3 = DiscoveryPacket.from_dict(d2)
assert pkt3.port == 8000
print("  PASS — DiscoveryPacket serializes and deserializes correctly")

# ── CHECK 4: HeartbeatPacket ──────────────────────
print("\n[4] Testing HeartbeatPacket...")
hb = HeartbeatPacket(
    node_id="laptop-node-01",
    role="primary",
    timestamp="2024-01-01T00:00:00",
    sequence=42,
    status="healthy",
    uptime_seconds=123.4
)
d = hb.to_dict()
assert d["sequence"] == 42
assert d["uptime_seconds"] == 123.4
hb2 = HeartbeatPacket.from_dict(d)
assert hb2.sequence == 42
print("  PASS — HeartbeatPacket correct")

# ── CHECK 5: SyncSnapshot ─────────────────────────
print("\n[5] Testing SyncSnapshot...")
snap = SyncSnapshot(
    version=7,
    checksum="abc123",
    timestamp="2024-01-01T00:00:00",
    source_node_id="laptop-node-01",
    payload={"projects": [{"id": "1", "title": "Test"}]}
)
d = snap.to_dict()
assert d["version"] == 7
assert d["payload"]["projects"][0]["title"] == "Test"
snap2 = SyncSnapshot.from_dict(d)
assert snap2.payload["projects"][0]["title"] == "Test"
print("  PASS — SyncSnapshot correct")

# ── CHECK 6: NodeInfo ─────────────────────────────
print("\n[6] Testing NodeInfo...")
ni = NodeInfo(
    node_id="phone-node-02",
    role="secondary",
    host="192.168.1.50",
    port=8001,
    status="healthy",
    last_seen="2024-01-01T00:00:00",
    failover_active=False,
    uptime_seconds=60.0
)
d = ni.to_dict()
assert d["failover_active"] == False
ni2 = NodeInfo.from_dict(d)
assert ni2.host == "192.168.1.50"
print("  PASS — NodeInfo correct")

# ── CHECK 7: AlertEvent ───────────────────────────
print("\n[7] Testing AlertEvent...")
ae = AlertEvent(
    id="some-uuid",
    event_type="FAILOVER",
    severity="CRITICAL",
    source="phone-node-02",
    message="Primary offline",
    timestamp="2024-01-01T00:00:00",
    acknowledged=False,
    metadata={"extra": "data"}
)
d = ae.to_dict()
assert d["acknowledged"] == False
assert d["metadata"]["extra"] == "data"
ae2 = AlertEvent.from_dict(d)
assert ae2.event_type == "FAILOVER"
print("  PASS — AlertEvent correct")

# ── CHECK 8: Message builders ─────────────────────
print("\n[8] Testing message builders...")

disc = build_discovery_packet("laptop-node-01", "primary", 8000)
assert disc["service"] == "sentineldr"
assert disc["node_id"] == "laptop-node-01"
assert "timestamp" in disc

hb = build_heartbeat("laptop-node-01", "primary", 1, "healthy", 10.0)
assert hb["sequence"] == 1
assert hb["status"] == "healthy"

snap = build_sync_snapshot("laptop-node-01", 3, {"projects": []}, "checksum123")
assert snap["version"] == 3
assert snap["source_node_id"] == "laptop-node-01"

evt = build_event("SYNC", "INFO", "laptop-node-01", "Sync complete")
assert evt["event_type"] == "SYNC"
assert evt["acknowledged"] == False
assert "id" in evt  # UUID generated

failover = build_failover_alert("phone-node-02")
assert failover["severity"] == "CRITICAL"
assert failover["event_type"] == "FAILOVER"

recovery = build_recovery_alert("phone-node-02")
assert recovery["severity"] == "SUCCESS"
assert recovery["event_type"] == "RECOVERY"

disc_evt = build_discovery_event("laptop-node-01", "phone-node-02", "192.168.1.50")
assert "192.168.1.50" in disc_evt["message"]

sync_evt = build_sync_event("laptop-node-01", 5, 3)
assert "v5" in sync_evt["message"]
assert "3 projects" in sync_evt["message"]

print("  PASS — All message builders correct")

# ── CHECK 9: No third-party imports ───────────────
print("\n[9] Verifying no third-party imports...")
import ast, pathlib

shared_dir = Path(__file__).parent
stdlib_only = {"json", "uuid", "datetime", "hashlib", "dataclasses",
               "typing", "os", "sys", "time", "pathlib", "abc"}
violations = []

for f in shared_dir.glob("*.py"):
    if f.name == "verify_module1.py":
        continue
    tree = ast.parse(f.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = ""
            if isinstance(node, ast.Import):
                mod = node.names[0].name.split(".")[0]
            elif node.module:
                mod = node.module.split(".")[0]
            if mod and mod not in stdlib_only and mod != "shared":
                violations.append(f"{f.name}: imports '{mod}'")

if violations:
    print(f"  FAIL — Third-party imports found:")
    for v in violations:
        print(f"    {v}")
    sys.exit(1)
else:
    print("  PASS — Zero third-party imports")

# ── FINAL ─────────────────────────────────────────
print("\n" + "=" * 50)
print("MODULE 1 COMPLETE — ALL CHECKS PASSED")
print("=" * 50)
print("\nReady to proceed to Module 2.")
