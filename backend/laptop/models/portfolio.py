import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime
from sqlalchemy.sql import func
from laptop.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    tech_stack = Column(String, nullable=True)   # comma-separated values
    status = Column(String, default="active", nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    sync_version = Column(Integer, default=0, nullable=False)
    checksum = Column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<Project id={self.id!r} title={self.title!r} status={self.status!r}>"
