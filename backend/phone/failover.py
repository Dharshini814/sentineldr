# SentinelDR — Phone Failover & Recovery Service
# Standard library ONLY. Runs on Android Termux.
# urllib.request, threading, logging, time, json — nothing else.

import json
import logging
import time
import urllib.request
import urllib.error

from shared.constants import (
    FAILOVER_COOLDOWN,
    ROLE_SECONDARY,
    ROLE_ACTIVE_SECONDARY,
    STATUS_HEALTHY,
    STATUS_OFFLINE,
)
from shared.messages import build_failover_alert, build_recovery_alert

logger = logging.getLogger(__name__)

# ── Module-level state refs — injected by init_failover() or used directly ──
# Default to singletons; tests inject their own via the functions below.

_config = None
_runtime = None
_storage = None


def _get_config():
    global _config
    if _config is None:
        import phone.config as _c
        _config = _c
    return _config


def _get_runtime():
    global _runtime
    if _runtime is None:
        from phone.config import runtime as _r
        _runtime = _r
    return _runtime


def _get_storage():
    global _storage
    if _storage is None:
        import phone.storage as _s
        _storage = _s
    return _storage


def init_failover(config_module=None, runtime_dict=None, storage_module=None):
    """
    Inject dependencies for testing.
    Call before trigger_failover() / trigger_recovery() in tests.
    """
    global _config, _runtime, _storage
    if config_module is not None:
        _config = config_module
    if runtime_dict is not None:
        _runtime = runtime_dict
    if storage_module is not None:
        _storage = storage_module


# ── State machine ─────────────────────────────────────────────────────────────
#
#   STANDBY  ──► FAILOVER_ACTIVE  ──► RECOVERING  ──► STANDBY
#
# Stored in runtime dict:
#   runtime["failover_active"]   bool
#   runtime["peer_status"]       "offline" / "healthy"
#   runtime["failover_time"]     float or None


def trigger_failover() -> None:
    """
    Activate phone recovery mode.

    Guards:
    - Already active: return immediately
    - Cooldown: if recently triggered and active, block re-trigger
    """
    rt = _get_runtime()
    cfg = _get_config()
    st = _get_storage()

    # ── Guard: already in failover ────────────────────
    if rt.get("failover_active", False):
        logger.debug("[FAILOVER] Already active — ignoring trigger")
        return

    # ── Activate failover ─────────────────────────────
    rt["failover_active"] = True
    rt["peer_status"] = STATUS_OFFLINE
    rt["failover_time"] = time.time()

    # ── Persist event to SQLite ───────────────────────
    node_id = getattr(cfg, "NODE_ID", "phone-node-02")
    event = build_failover_alert(source_node_id=node_id)
    try:
        st.save_event(event)
    except Exception as exc:
        logger.error("[FAILOVER] Could not save failover event: %s", exc)

    logger.critical("[FAILOVER] PRIMARY OFFLINE — Phone recovery mode ACTIVATED")
    logger.critical("[FAILOVER] Phone is now serving recovery data")


def trigger_recovery(peer_url: str) -> None:
    """
    Attempt to hand back to the primary.

    Steps:
    1. GET {peer_url}/health — verify primary is actually healthy
    2. Only if health check passes: reset failover state and save event
    3. If health check fails for any reason: log and stay in failover
    """
    rt = _get_runtime()
    cfg = _get_config()
    st = _get_storage()

    # Guard: not in failover, nothing to recover from
    if not rt.get("failover_active", False):
        logger.debug("[RECOVERY] Not in failover — ignoring recovery trigger")
        return

    node_id = getattr(cfg, "NODE_ID", "phone-node-02")

    # ── Health check ──────────────────────────────────
    health_ok = False
    try:
        req = urllib.request.Request(f"{peer_url}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                # Verify it's actually the expected primary
                if (body.get("status") == "healthy" and 
                    body.get("node_id") == "laptop-node-01" and 
                    body.get("role") == "primary"):
                    health_ok = True
    except Exception as exc:
        logger.warning(
            "[RECOVERY] Primary health check failed: %s — staying in failover", exc
        )

    if not health_ok:
        logger.warning(
            "[RECOVERY] Primary health check failed — staying in failover"
        )
        return

    # ── Reset state ───────────────────────────────────
    rt["failover_active"] = False
    rt["peer_status"] = STATUS_HEALTHY
    rt["missed_heartbeats"] = 0
    rt["peer_last_seen"] = time.time()

    # ── Persist event to SQLite ───────────────────────
    event = build_recovery_alert(source_node_id=node_id)
    try:
        st.save_event(event)
    except Exception as exc:
        logger.error("[RECOVERY] Could not save recovery event: %s", exc)

    logger.info("[RECOVERY] Primary restored — returning to secondary role")


def get_failover_status() -> dict:
    """Return current failover state for the health/status endpoint."""
    rt = _get_runtime()
    in_failover = rt.get("failover_active", False)
    return {
        "failover_active": in_failover,
        "failover_time": rt.get("failover_time"),
        "peer_status": rt.get("peer_status", STATUS_OFFLINE),
        "role": ROLE_ACTIVE_SECONDARY if in_failover else ROLE_SECONDARY,
    }


def is_in_failover() -> bool:
    """Return True if the phone is currently in active failover mode."""
    return bool(_get_runtime().get("failover_active", False))
