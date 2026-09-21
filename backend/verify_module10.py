"""
Module 10 Verification Script
Run from backend/: python verify_module10.py
Expected: All checks PASS
"""

import sys
import os
import json
import logging
import pathlib
import time

print("=" * 55)
print("MODULE 10 — ALERT SERVICE VERIFICATION")
print("=" * 55)

BACKEND = pathlib.Path(__file__).parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("API_KEY", "test-key-for-verification")

# ── CHECK 1: File exists ───────────────────────────────
print("\n[1] Checking alert_service.py exists...")
alert_path = BACKEND / "laptop" / "services" / "alert_service.py"
if not alert_path.exists():
    print(f"  FAIL — Missing: {alert_path}")
    sys.exit(1)
print("  PASS — alert_service.py present")

# ── CHECK 2: AlertService importable ──────────────────
print("\n[2] Testing AlertService importable...")
try:
    from laptop.services.alert_service import AlertService
    print("  PASS — AlertService imported")
except ImportError as e:
    print(f"  FAIL — {e}")
    sys.exit(1)

# ── Setup: real DB session via init_db ─────────────────
from laptop.database import init_db, get_engine
init_db()

from sqlalchemy.orm import Session as _Session
engine = get_engine()

class _DirectSessionFactory:
    """Opens a real SQLAlchemy session against PostgreSQL."""
    def __call__(self):
        return _Session(engine)

class MockSettings:
    NODE_ID = "verify10-node"
    NODE_ROLE = "primary"
    API_KEY = "test-key"
    PEER_PORT = 8001

class MockRuntime:
    sync_version = 0
    last_sync_time = None
    last_sync_checksum = None
    failover_active = False
    peer_host = None
    def get_peer_url(self, port): return None

alert = AlertService(
    settings=MockSettings(),
    runtime=MockRuntime(),
    db_session_factory=_DirectSessionFactory(),
)

# Track emitted event IDs for cleanup
_emitted_ids = []

# ── CHECK 3: All required methods exist ───────────────
print("\n[3] Checking all required methods exist...")
required_methods = [
    "emit", "emit_failover", "emit_recovery", "emit_sync",
    "emit_discovery", "emit_heartbeat_warning", "emit_startup",
    "get_recent", "get_unacknowledged", "acknowledge", "get_counts", "start",
]
missing = [m for m in required_methods if not callable(getattr(alert, m, None))]
if missing:
    print(f"  FAIL — Missing methods: {missing}")
    sys.exit(1)
print(f"  PASS — All {len(required_methods)} methods present and callable")

# ── CHECK 4: emit() saves to PostgreSQL ───────────────
print("\n[4] Testing emit() saves event to PostgreSQL...")
evt = alert.emit("VERIFY", "INFO", "verify10", "Test emit check-4", {"key": "val"})
_emitted_ids.append(evt["id"])

with _Session(engine) as s:
    from laptop.models.events import Event
    row = s.get(Event, evt["id"])
    assert row is not None, "Event not found in PostgreSQL"
    assert row.event_type == "VERIFY"
    assert row.severity == "INFO"
    assert row.message == "Test emit check-4"
print("  PASS — emit() saves event to PostgreSQL")

# ── CHECK 5: CRITICAL severity logs at ERROR ──────────
print("\n[5] Testing CRITICAL severity logs at ERROR level...")
log_records = []

class _Capture(logging.Handler):
    def emit(self, record): log_records.append(record)

handler = _Capture()
logging.getLogger("laptop.services.alert_service").addHandler(handler)
logging.getLogger("laptop.services.alert_service").setLevel(logging.DEBUG)

evt5 = alert.emit("FAILOVER", "CRITICAL", "verify10", "Critical test", {})
_emitted_ids.append(evt5["id"])

critical_logs = [r for r in log_records if r.levelno == logging.ERROR]
assert len(critical_logs) >= 1, f"No ERROR-level logs for CRITICAL event. Got: {[(r.levelno, r.getMessage()) for r in log_records]}"
assert "[ALERT CRITICAL]" in critical_logs[0].getMessage()
logging.getLogger("laptop.services.alert_service").removeHandler(handler)
print("  PASS — CRITICAL severity correctly logged at ERROR level")

# ── CHECK 6: emit_failover() ──────────────────────────
print("\n[6] Testing emit_failover() event type and severity...")
evt6 = alert.emit_failover("laptop-node-01")
_emitted_ids.append(evt6["id"])
assert evt6["event_type"] == "FAILOVER"
assert evt6["severity"] == "CRITICAL"
assert "unavailable" in evt6["message"]
print("  PASS — emit_failover() correct")

# ── CHECK 7: emit_recovery() ──────────────────────────
print("\n[7] Testing emit_recovery() event type and severity...")
evt7 = alert.emit_recovery("laptop-node-01")
_emitted_ids.append(evt7["id"])
assert evt7["event_type"] == "RECOVERY"
assert evt7["severity"] == "SUCCESS"
assert "restored" in evt7["message"]
print("  PASS — emit_recovery() correct")

# ── CHECK 8: emit_sync() ──────────────────────────────
print("\n[8] Testing emit_sync() event type...")
evt8 = alert.emit_sync(version=5, project_count=12)
_emitted_ids.append(evt8["id"])
assert evt8["event_type"] == "SYNC"
assert "v5" in evt8["message"]
assert "12 projects" in evt8["message"]
print("  PASS — emit_sync() correct")

# ── CHECK 9: emit_discovery() ─────────────────────────
print("\n[9] Testing emit_discovery() event type...")
evt9 = alert.emit_discovery("phone-node-02", "192.168.1.50")
_emitted_ids.append(evt9["id"])
assert evt9["event_type"] == "DISCOVERY"
assert "phone-node-02" in evt9["message"]
assert "192.168.1.50" in evt9["message"]
print("  PASS — emit_discovery() correct")

# ── CHECK 10: emit_heartbeat_warning() ────────────────
print("\n[10] Testing emit_heartbeat_warning() severity...")
evt10 = alert.emit_heartbeat_warning(missed=2, threshold=3)
_emitted_ids.append(evt10["id"])
assert evt10["event_type"] == "HEARTBEAT"
assert evt10["severity"] == "WARNING"
assert "2/3" in evt10["message"]
print("  PASS — emit_heartbeat_warning() correct")

# ── CHECK 11: get_recent() ordered by timestamp desc ──
print("\n[11] Testing get_recent() returns events ordered by timestamp desc...")
recent = alert.get_recent(limit=50)
assert isinstance(recent, list)
# Must contain our emitted events
our_ids = set(_emitted_ids)
found_ids = {e["id"] for e in recent}
overlap = our_ids & found_ids
assert len(overlap) >= 5, f"Only found {len(overlap)} of our events in get_recent()"
# Verify descending timestamp order (compare first pair)
if len(recent) >= 2:
    ts0 = recent[0]["timestamp"]
    ts1 = recent[1]["timestamp"]
    assert ts0 >= ts1, f"Not descending: {ts0} < {ts1}"
print(f"  PASS — get_recent() returned {len(recent)} events, ordered desc")

# ── CHECK 12: get_recent(limit=3) returns at most 3 ───
print("\n[12] Testing get_recent(limit=3) caps at 3 results...")
capped = alert.get_recent(limit=3)
assert len(capped) <= 3, f"Expected ≤3, got {len(capped)}"
print(f"  PASS — get_recent(limit=3) returned {len(capped)} events")

# ── CHECK 13: get_unacknowledged() filters correctly ──
print("\n[13] Testing get_unacknowledged() returns only unacknowledged...")
unack = alert.get_unacknowledged()
assert isinstance(unack, list)
for e in unack:
    assert e["acknowledged"] == False, f"Event {e['id']} is acknowledged but was returned"
# All our emitted IDs should be unacknowledged (we haven't acked any yet)
our_unack = [e for e in unack if e["id"] in our_ids]
assert len(our_unack) >= 5, f"Expected ≥5 of our events unacked, got {len(our_unack)}"
print(f"  PASS — get_unacknowledged() returned {len(unack)} events, all unacknowledged")

# ── CHECK 14: acknowledge() sets acknowledged=True ────
print("\n[14] Testing acknowledge() sets acknowledged=True...")
target_id = evt6["id"]   # use the failover event
result = alert.acknowledge(target_id)
assert result == True, f"acknowledge() returned {result}"

# Verify in DB
with _Session(engine) as s:
    row = s.get(Event, target_id)
    assert row is not None
    assert row.acknowledged == True, f"Row still unacknowledged in DB"

# Confirm it no longer appears in get_unacknowledged()
unack2 = alert.get_unacknowledged()
still_there = [e for e in unack2 if e["id"] == target_id]
assert len(still_there) == 0, "Acknowledged event still in unacknowledged list"
print("  PASS — acknowledge() correctly sets acknowledged=True")

# ── CHECK 15: acknowledge("nonexistent") returns False ─
print("\n[15] Testing acknowledge() with nonexistent ID returns False...")
result = alert.acknowledge("00000000-0000-0000-0000-000000000000")
assert result == False, f"Expected False, got {result}"
print("  PASS — acknowledge(nonexistent) returns False without crashing")

# ── CHECK 16: get_counts() returns correct structure ──
print("\n[16] Testing get_counts() returns correct counts...")
counts = alert.get_counts()
required_count_keys = {"total", "unacknowledged", "critical", "warnings"}
missing_k = required_count_keys - set(counts.keys())
assert not missing_k, f"Missing keys: {missing_k}"
assert counts["total"] >= len(_emitted_ids), \
    f"total={counts['total']} < emitted={len(_emitted_ids)}"
assert counts["critical"] >= 1, "Should have at least 1 critical event"
assert counts["warnings"] >= 1, "Should have at least 1 warning event"
# We acked one, so unacknowledged should be < total
assert counts["unacknowledged"] < counts["total"], \
    "unacknowledged should be less than total (we acked one)"
print(f"  PASS — get_counts(): {counts}")

# ── CHECK 17: Database error does not crash emit() ────
print("\n[17] Testing emit() survives database error gracefully...")

class _BrokenSession:
    def add(self, _): raise RuntimeError("simulated DB failure")
    def commit(self): raise RuntimeError("simulated DB failure")
    def rollback(self): pass
    def close(self): pass

class _BrokenSessionFactory:
    def __call__(self): return _BrokenSession()

broken_alert = AlertService(
    settings=MockSettings(),
    runtime=MockRuntime(),
    db_session_factory=_BrokenSessionFactory(),
)
try:
    result = broken_alert.emit("TEST", "INFO", "verify10", "Should not crash")
    # Should return the event dict even though persistence failed
    assert result is not None
    assert "id" in result
    print("  PASS — Database error caught gracefully, no exception raised")
except Exception as e:
    print(f"  FAIL — Exception escaped: {e}")
    sys.exit(1)

# ── CHECK 18: Metadata round-trips correctly ──────────
print("\n[18] Testing metadata round-trips as dict (not string)...")
meta_in = {"failover_reason": "timeout", "missed_beats": 3, "threshold": 3}
evt18 = alert.emit("META_TEST", "INFO", "verify10", "Metadata round-trip", meta_in)
_emitted_ids.append(evt18["id"])

# Retrieve via get_recent and verify metadata is a dict
recent18 = alert.get_recent(limit=10)
found18 = next((e for e in recent18 if e["id"] == evt18["id"]), None)
assert found18 is not None, "Metadata test event not found in get_recent()"
meta_out = found18["metadata"]
assert isinstance(meta_out, dict), f"Expected dict, got {type(meta_out)}: {meta_out!r}"
assert meta_out["failover_reason"] == "timeout"
assert meta_out["missed_beats"] == 3
print(f"  PASS — Metadata round-trips correctly as dict: {meta_out}")

# ── CHECK 19: Cleanup all test events ─────────────────
print("\n[19] Cleaning up test events from PostgreSQL...")
with _Session(engine) as s:
    for eid in _emitted_ids:
        row = s.get(Event, eid)
        if row:
            s.delete(row)
    # Also delete any startup events we created
    from laptop.models.events import Event as _E
    startup_rows = s.query(_E).filter(
        _E.source == "verify10-node",
    ).all()
    for r in startup_rows:
        s.delete(r)
    s.commit()
print(f"  PASS — {len(_emitted_ids)} test events deleted, database clean")

# ── FINAL ─────────────────────────────────────────────
print("\n" + "=" * 55)
print("MODULE 10 COMPLETE — ALL CHECKS PASSED")
print("=" * 55)
print("\nReady to proceed to Module 11.")
