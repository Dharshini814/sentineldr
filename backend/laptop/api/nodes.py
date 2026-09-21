from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()


def _self_node(settings, runtime, local_ip) -> dict:
    return {
        "node_id": settings.NODE_ID,
        "role": settings.NODE_ROLE,
        "host": local_ip,
        "port": settings.NODE_PORT,
        "status": "healthy",
        "uptime_seconds": runtime.get_uptime(),
        "failover_active": runtime.failover_active,
    }


def _peer_node(settings, runtime) -> dict | None:
    if runtime.peer_host is None:
        return None
    
    last_seen = None
    if runtime.peer_last_seen is not None:
        last_seen = datetime.fromtimestamp(
            runtime.peer_last_seen, tz=timezone.utc
        ).isoformat()
    
    # Determine actual peer status based on connectivity
    status = "healthy" if runtime.peer_status == "healthy" else "offline"
    
    return {
        "node_id": runtime.peer_node_id,
        "role": runtime.peer_role or "secondary",
        "host": runtime.peer_host,
        "port": settings.PEER_PORT,
        "status": status,
        "last_seen": last_seen,
        "failover_active": False,  # Laptop reports its view - peer failover determined by phone
    }


@router.get("/nodes")
async def list_nodes(request: Request):
    settings = request.app.state.settings
    runtime = request.app.state.runtime
    local_ip = request.app.state.local_ip

    nodes = [_self_node(settings, runtime, local_ip)]
    peer = _peer_node(settings, runtime)
    if peer:
        nodes.append(peer)
    return nodes


@router.get("/nodes/{node_id}")
async def get_node(node_id: str, request: Request):
    settings = request.app.state.settings
    runtime = request.app.state.runtime
    local_ip = request.app.state.local_ip

    if node_id == settings.NODE_ID:
        return _self_node(settings, runtime, local_ip)

    peer = _peer_node(settings, runtime)
    if peer and peer["node_id"] == node_id:
        return peer

    raise HTTPException(status_code=404, detail=f"Node {node_id!r} not found")
