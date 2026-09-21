from typing import List
from fastapi import APIRouter, Request, HTTPException, Query

router = APIRouter()


@router.get("/events")
async def list_events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    unacknowledged_only: bool = Query(default=False),
):
    alert = request.app.state.alert_service
    if unacknowledged_only:
        return alert.get_unacknowledged()
    return alert.get_recent(limit=limit)


@router.post("/events/{event_id}/acknowledge")
async def acknowledge_event(event_id: str, request: Request):
    alert = request.app.state.alert_service
    ok = alert.acknowledge(event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"status": "ok"}
