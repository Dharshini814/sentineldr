from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    title: str
    description: str = ""
    tech_stack: str = ""
    status: str = "active"


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tech_stack: Optional[str] = None
    status: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = ""
    tech_stack: Optional[str] = ""
    status: str
    created_at: datetime
    updated_at: datetime
    sync_version: int

    model_config = ConfigDict(from_attributes=True)
