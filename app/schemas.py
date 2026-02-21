from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from .models import TaskType, TaskStatus, SubmissionStatus, UserRole


class UserCreate(BaseModel):
    nickname: str
    wallet: str
    role: UserRole


class UserOut(BaseModel):
    id: str
    nickname: str
    wallet: str
    role: UserRole
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    title: str
    description: str
    type: TaskType
    threshold: Optional[float] = None
    max_revisions: Optional[int] = None
    deadline: datetime


class TaskOut(BaseModel):
    id: str
    title: str
    description: str
    type: TaskType
    threshold: Optional[float] = None
    max_revisions: Optional[int] = None
    deadline: datetime
    status: TaskStatus
    winner_submission_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskDetail(TaskOut):
    submissions: List["SubmissionOut"] = []


class SubmissionCreate(BaseModel):
    worker_id: str
    content: str


class SubmissionOut(BaseModel):
    id: str
    task_id: str
    worker_id: str
    revision: int
    content: str
    score: Optional[float] = None
    oracle_feedback: Optional[str] = None
    status: SubmissionStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class ScoreInput(BaseModel):
    score: float
    feedback: Optional[str] = None


TaskDetail.model_rebuild()
