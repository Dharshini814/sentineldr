# SentinelDR — Phone Sync Handler
# Standard library ONLY. Runs on Android Termux.
# Receives and applies sync snapshots pushed by the laptop.

import logging

from shared.constants import STATUS_HEALTHY

logger = logging.getLogger(__name__)

# ── Dependency accessors (injectable for testing) ────────────────────────────

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


def init_sync(config_module=None, runtime_dict=None, storage_module=None):
    """Inject dependencies for testing."""
    global _config, _runtime, _storage
    if config_module is not None:
        _config = config_module
    if runtime_dict is not None:
        _runtime = runtime_dict
    if storage_module is not None:
        _storage = storage_module


# ── Handler ───────────────────────────────────────────────────────────────────

def receive_snapshot(data: dict, api_key: str) -> dict:
    """
    Validate and apply a sync snapshot from the laptop.

    Returns:
      {"status": "unauthorized"}                      — bad API key
      {"status": "error", "reason": "..."}            — missing fields or exception
      {"status": "ok", "version": v, "count": n}      — success
      {"status": "rejected", "reason": "stale"}       — version not newer
      {"status": "rejected", "reason": "checksum_mismatch"}
    """
    cfg = _get_config()
    st = _get_storage()

    # ── API key validation ────────────────────────────
    expected_key = getattr(cfg, "API_KEY", "")
    if api_key != expected_key:
        logger.warning("[SYNC] Rejected snapshot — invalid API key")
        return {"status": "unauthorized"}

    # ── Required field validation ─────────────────────
    required = ("version", "payload", "checksum", "source_node_id")
    for field in required:
        if field not in data:
            logger.warning("[SYNC] Rejected snapshot — missing field: %s", field)
            return {"status": "error", "reason": "invalid_snapshot"}

    # ── Apply via storage layer ───────────────────────
    try:
        result = st.apply_sync_snapshot(data)
    except Exception as exc:
        logger.error("[SYNC] Snapshot apply error: %s", exc)
        return {"status": "error", "reason": str(exc)}

    logger.info("[SYNC] Snapshot result: %s", result.get("status"))
    return result


# ── Status ────────────────────────────────────────────────────────────────────

def get_sync_status() -> dict:
    """Return current sync state from runtime and storage."""
    rt = _get_runtime()
    st = _get_storage()

    return {
        "sync_version": st.get_sync_version(),
        "last_sync_time": rt.get("last_sync_time"),
        "peer_status": rt.get("peer_status", "offline"),
        "project_count": st.get_storage_stats()["project_count"],
    }
