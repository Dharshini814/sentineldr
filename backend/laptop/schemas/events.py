from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class EventResponse(BaseModel):
    id: str
    event_type: str
    severity: str
    source: Optional[str] = None
    message: Optional[str] = None
    timestamp: datetime
    acknowledged: bool
    metadata: dict = {}

    model_config = ConfigDict(from_attributes=True)


class AcknowledgeRequest(BaseModel):
    event_id: str
