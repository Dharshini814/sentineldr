from fastapi import APIRouter, Request, Query

router = APIRouter()


@router.get("/heartbeat")
async def receive_heartbeat(
    request: Request,
    node_id: str = Query(default="unknown"),
    role: str = Query(default="secondary"),
    sequence: int = Query(default=0),
    status: str = Query(default="healthy"),
):
    """
    Called by the phone to send a heartbeat to the laptop.
    The act of receiving this request IS the heartbeat.
    """
    hb_service = request.app.state.heartbeat_service
    return hb_service.handle_incoming(
        node_id=node_id,
        role=role,
        sequence=sequence,
        status=status,
    )
