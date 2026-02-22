from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, model_validator
from .models import TaskType, TaskStatus, SubmissionStatus, UserRole, PayoutStatus


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
    publisher_id: str
    bounty: float

    @model_validator(mode="after")
    def validate_type_fields(self) -> "TaskCreate":
        if self.type == TaskType.fastest_first and self.threshold is None:
            raise ValueError("fastest_first tasks require a threshold")
        return self


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
    publisher_id: Optional[str] = None
    bounty: Optional[float] = None
    payment_tx_hash: Optional[str] = None
    payout_status: PayoutStatus = PayoutStatus.pending
    payout_tx_hash: Optional[str] = None
    payout_amount: Optional[float] = None
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
