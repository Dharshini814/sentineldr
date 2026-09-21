import uuid
from sqlalchemy import Column, String, Text, Boolean, DateTime
from sqlalchemy.sql import func
from laptop.database import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )
    event_type = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    source = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)
    acknowledged = Column(Boolean, default=False, nullable=False)
    metadata_json = Column(Text, nullable=True)   # stores JSON string

    def __repr__(self) -> str:
        return (
            f"<Event id={self.id!r} type={self.event_type!r} "
            f"severity={self.severity!r}>"
        )
