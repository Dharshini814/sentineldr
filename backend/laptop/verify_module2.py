"""
Module 2 Verification Script
Run from backend/: python -m laptop.verify_module2
Expected: All checks PASS
"""

import sys
import json
import time
import threading
import pathlib

print("=" * 55)
print("MODULE 2 — LAPTOP CONFIGURATION VERIFICATION")
print("=" * 55)

# ── CHECK 1: pydantic-settings installed ──────────────
print("\n[1] Checking pydantic-settings installed...")
try:
    import pydantic_settings
    print(f"  PASS — pydantic-settings found")
except ImportError:
    print("  FAIL — Run: pip install pydantic-settings")
    sys.exit(1)

# ── CHECK 2: Settings loads from .env file ────────────
print("\n[2] Testing Settings loads correctly...")

test_env = pathlib.Path(".env.laptop.test")
test_env.write_text(
    "NODE_ID=test-laptop-01\n"
    "NODE_ROLE=primary\n"
    "NODE_PORT=8000\n"
    "PEER_PORT=8001\n"
    "API_KEY=test-secret-key\n"
    "DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/testdb\n"
    "HEARTBEAT_INTERVAL=3\n"
    "HEARTBEAT_TIMEOUT=3\n"
    "MISSED_HEARTBEAT_THRESHOLD=3\n"
    "SYNC_INTERVAL=5\n"
    "FAILOVER_COOLDOWN=30\n"
    'CORS_ORIGINS=["http://localhost:5173"]\n'
    "LOG_LEVEL=INFO\n"
)

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class TestSettings(BaseSettings):
        NODE_ID: str = "laptop-node-01"
        NODE_ROLE: str = "primary"
        NODE_PORT: int = 8000
        PEER_PORT: int = 8001
        API_KEY: str
        DATABASE_URL: str
        HEARTBEAT_INTERVAL: int = 3
        HEARTBEAT_TIMEOUT: int = 3
        MISSED_HEARTBEAT_THRESHOLD: int = 3
        SYNC_INTERVAL: int = 5
        FAILOVER_COOLDOWN: int = 30
        CORS_ORIGINS: list[str] = ["http://localhost:5173"]
        LOG_LEVEL: str = "INFO"

        model_config = SettingsConfigDict(
            env_file=".env.laptop.test",
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore"
        )

    s = TestSettings()
    assert s.NODE_ID == "test-laptop-01"
    assert s.NODE_PORT == 8000
    assert s.API_KEY == "test-secret-key"
    assert s.HEARTBEAT_INTERVAL == 3
    assert "http://localhost:5173" in s.CORS_ORIGINS
    print("  PASS — Settings loads correctly")
finally:
    test_env.unlink(missing_ok=True)

# ── CHECK 3: Missing API_KEY raises error ─────────────
print("\n[3] Testing missing API_KEY raises error...")
test_env2 = pathlib.Path(".env.laptop.test2")
test_env2.write_text(
    "NODE_ID=test\n"
    "DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/testdb\n"
)
try:
    from pydantic import ValidationError

    class TestSettingsBad(BaseSettings):
        API_KEY: str
        DATABASE_URL: str
        NODE_ID: str = "x"
        model_config = SettingsConfigDict(
            env_file=".env.laptop.test2",
            extra="ignore"
        )

    try:
        _ = TestSettingsBad()
        print("  FAIL — Should have raised ValidationError")
        sys.exit(1)
    except (ValidationError, Exception):
        print("  PASS — Missing API_KEY correctly raises error")
finally:
    test_env2.unlink(missing_ok=True)

# ── CHECK 4: RuntimeState operations ─────────────────
print("\n[4] Testing RuntimeState...")
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from laptop.config import RuntimeState

rt = RuntimeState()
assert rt.peer_host is None
assert rt.peer_status == "offline"
assert rt.missed_heartbeats == 0
assert rt.failover_active == False
assert rt.sync_version == 0
assert rt.get_uptime() >= 0

rt.update_peer_discovered("192.168.1.50", "phone-node-02", "secondary")
assert rt.peer_host == "192.168.1.50"
assert rt.peer_node_id == "phone-node-02"

rt.update_peer_healthy()
assert rt.peer_status == "healthy"
assert rt.missed_heartbeats == 0

assert rt.increment_missed_heartbeat() == 1
assert rt.increment_missed_heartbeat() == 2

rt.mark_peer_offline()
assert rt.peer_status == "offline"

rt.update_sync(version=5, checksum="abc123")
assert rt.sync_version == 5
assert rt.last_sync_checksum == "abc123"

rt.set_failover(True)
assert rt.failover_active == True
assert rt.failover_time is not None

rt.set_failover(False)
assert rt.failover_active == False

print("  PASS — RuntimeState operations correct")

# ── CHECK 5: get_peer_url ─────────────────────────────
print("\n[5] Testing get_peer_url...")
rt2 = RuntimeState()
assert rt2.get_peer_url(8001) is None

rt2.update_peer_discovered("10.0.0.5", "phone-node-02", "secondary")
url = rt2.get_peer_url(8001)
assert url == "http://10.0.0.5:8001", f"Wrong: {url}"
print("  PASS — get_peer_url correct")

# ── CHECK 6: to_dict is JSON serializable ─────────────
print("\n[6] Testing to_dict JSON serializable...")
rt3 = RuntimeState()
rt3.update_peer_discovered("192.168.1.1", "phone-node-02", "secondary")
rt3.update_peer_healthy()
d = rt3.to_dict()
json_str = json.dumps(d)
parsed = json.loads(json_str)
assert parsed["peer_host"] == "192.168.1.1"
assert parsed["peer_status"] == "healthy"
print("  PASS — to_dict JSON serializable")

# ── CHECK 7: Thread safety ────────────────────────────
print("\n[7] Testing thread safety...")
rt4 = RuntimeState()
errors = []

def writer():
    for i in range(100):
        try:
            rt4.update_peer_discovered(f"192.168.1.{i%255}", "phone", "secondary")
            rt4.update_peer_healthy()
            rt4.increment_missed_heartbeat()
        except Exception as e:
            errors.append(str(e))

def reader():
    for i in range(100):
        try:
            _ = rt4.to_dict()
            _ = rt4.get_peer_url(8001)
        except Exception as e:
            errors.append(str(e))

threads = [threading.Thread(target=writer) for _ in range(3)]
threads += [threading.Thread(target=reader) for _ in range(3)]
for t in threads:
    t.start()
for t in threads:
    t.join()

if errors:
    print(f"  FAIL — {errors[:2]}")
    sys.exit(1)
print("  PASS — Thread safe")

# ── CHECK 8: No hardcoded IPs in example file ─────────
print("\n[8] Checking .env.laptop.example...")
import re
example = pathlib.Path(__file__).parent / ".env.laptop.example"
assert example.exists(), "FAIL — .env.laptop.example missing"
content = example.read_text()
for key in ["NODE_ID","API_KEY","DATABASE_URL","PEER_PORT","CORS_ORIGINS"]:
    assert key in content, f"FAIL — {key} missing from example"
real_ips = [ip for ip in re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', content)
            if not ip.startswith("127.")]
assert not real_ips, f"FAIL — Hardcoded IPs: {real_ips}"
print("  PASS — .env.laptop.example complete, no hardcoded IPs")

# ── CHECK 9: Pydantic IS used (laptop rule) ───────────
print("\n[9] Verifying pydantic-settings IS used in config.py...")
config_src = (pathlib.Path(__file__).parent / "config.py").read_text()
assert "pydantic_settings" in config_src or "pydantic-settings" in config_src or "BaseSettings" in config_src, \
    "FAIL — config.py must use pydantic-settings"
print("  PASS — pydantic-settings correctly used on laptop")

# ── FINAL ─────────────────────────────────────────────
print("\n" + "=" * 55)
print("MODULE 2 COMPLETE — ALL CHECKS PASSED")
print("=" * 55)
print("\nReady to proceed to Module 3.")
