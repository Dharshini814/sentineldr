from datetime import datetime, timezone
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    """Public health endpoint — no authentication required."""
    settings = request.app.state.settings
    runtime = request.app.state.runtime
    local_ip = request.app.state.local_ip

    # Include project_count from the database (best-effort; 0 on any error)
    project_count = 0
    try:
        from laptop.models.portfolio import Project
        from laptop.database import SessionLocal
        session = SessionLocal()
        try:
            project_count = session.query(Project).count()
        finally:
            session.close()
    except Exception:
        pass

    # Laptop should never report failover_active=True, it's always primary
    # peer_reachable should be based on actual connectivity, not just discovery
    peer_reachable = (
        runtime.peer_host is not None and 
        runtime.peer_status == "healthy"
    )

    return {
        "node_id": settings.NODE_ID,
        "role": settings.NODE_ROLE,  # Always "primary" for laptop
        "status": "healthy",
        "peer_reachable": peer_reachable,
        "peer_node_id": runtime.peer_node_id,
        "peer_host": runtime.peer_host,
        "failover_active": False,  # Laptop never reports failover active
        "local_ip": local_ip,
        "uptime_seconds": runtime.get_uptime(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sync_version": runtime.sync_version,
        "project_count": project_count,
    }


@router.get("/status")
async def status(request: Request):
    """Full system status — authentication required (enforced by middleware)."""
    settings = request.app.state.settings
    runtime = request.app.state.runtime
    local_ip = request.app.state.local_ip

    # Try database ping
    db_status = "connected"
    try:
        from laptop.database import get_engine
        from sqlalchemy import text as sa_text
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(sa_text("SELECT 1"))
    except Exception:
        db_status = "error"

    last_sync_iso = None
    if runtime.last_sync_time is not None:
        from datetime import datetime, timezone
        last_sync_iso = datetime.fromtimestamp(
            runtime.last_sync_time, tz=timezone.utc
        ).isoformat()

    return {
        "node_id": settings.NODE_ID,
        "role": settings.NODE_ROLE,
        "status": "healthy",
        "peer_reachable": runtime.peer_host is not None,
        "peer_node_id": runtime.peer_node_id,
        "peer_host": runtime.peer_host,
        "failover_active": runtime.failover_active,
        "local_ip": local_ip,
        "uptime_seconds": runtime.get_uptime(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sync_version": runtime.sync_version,
        "last_sync_time": last_sync_iso,
        "last_sync_checksum": runtime.last_sync_checksum,
        "missed_heartbeats": runtime.missed_heartbeats,
        "heartbeat_sequence": runtime.heartbeat_sequence,
        "heartbeat_interval": settings.HEARTBEAT_INTERVAL,
        "missed_heartbeat_threshold": settings.MISSED_HEARTBEAT_THRESHOLD,
        "database": db_status,
        "peer_status": runtime.peer_status,
    }
