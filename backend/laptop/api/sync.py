from datetime import datetime, timezone
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class RecoveryAnnouncement(BaseModel):
    node_id: str
    role: str
    timestamp: str


@router.post("/sync/now")
async def sync_now(request: Request):
    request.app.state.sync_service.push_now()
    return {
        "status": "triggered",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/sync/status")
async def sync_status(request: Request):
    return request.app.state.sync_service.get_status()


@router.post("/recovery-announcement")
async def recovery_announcement(body: RecoveryAnnouncement, request: Request):
    request.app.state.failover_service.coordinate_failback()
    return {"status": "acknowledged"}
