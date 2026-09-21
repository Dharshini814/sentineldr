import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from laptop.database import get_db
from laptop.models.portfolio import Project
from laptop.schemas.portfolio import ProjectCreate, ProjectResponse, ProjectUpdate

router = APIRouter()


def _checksum(data: dict) -> str:
    s = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode()).hexdigest()[:16]


@router.get("/portfolio/projects", response_model=List[ProjectResponse])
async def list_projects(request: Request, db: Session = Depends(get_db)):
    return (
        db.query(Project)
        .order_by(Project.created_at.desc())
        .all()
    )


@router.post("/portfolio/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    cs = _checksum({"title": body.title, "description": body.description})

    proj = Project(
        id=project_id,
        title=body.title,
        description=body.description,
        tech_stack=body.tech_stack,
        status=body.status,
        created_at=now,
        updated_at=now,
        sync_version=0,
        checksum=cs,
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)

    # Trigger immediate sync
    request.app.state.sync_service.push_now()
    return proj


@router.get("/portfolio/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


@router.put("/portfolio/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    if body.title is not None:
        proj.title = body.title
    if body.description is not None:
        proj.description = body.description
    if body.tech_stack is not None:
        proj.tech_stack = body.tech_stack
    if body.status is not None:
        proj.status = body.status

    proj.updated_at = datetime.now(timezone.utc)
    proj.sync_version = (proj.sync_version or 0) + 1
    proj.checksum = _checksum({"title": proj.title, "description": proj.description})

    db.commit()
    db.refresh(proj)

    request.app.state.sync_service.push_now()
    return proj


@router.delete("/portfolio/projects/{project_id}")
async def delete_project(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    db.delete(proj)
    db.commit()

    request.app.state.sync_service.push_now()
    return {"status": "deleted", "id": project_id}
