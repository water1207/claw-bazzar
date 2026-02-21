import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, Enum
from .database import Base


class TaskType(str, PyEnum):
    fastest_first = "fastest_first"
    quality_first = "quality_first"


class TaskStatus(str, PyEnum):
    open = "open"
    closed = "closed"


class SubmissionStatus(str, PyEnum):
    pending = "pending"
    scored = "scored"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    type = Column(Enum(TaskType), nullable=False)
    threshold = Column(Float, nullable=True)       # fastest_first only
    max_revisions = Column(Integer, nullable=True)  # quality_first only
    deadline = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.open)
    winner_submission_id = Column(String, nullable=True)  # plain string, no FK
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, nullable=False)       # FK enforced in app layer
    worker_id = Column(String, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    score = Column(Float, nullable=True)
    oracle_feedback = Column(Text, nullable=True)
    status = Column(Enum(SubmissionStatus), nullable=False, default=SubmissionStatus.pending)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
