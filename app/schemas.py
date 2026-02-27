from datetime import datetime, timezone
from typing import Optional, List, Annotated
from pydantic import BaseModel, model_validator, PlainSerializer


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace('+00:00', 'Z')


UTCDatetime = Annotated[datetime, PlainSerializer(_utc_iso, return_type=str)]
from .models import (
    TaskType, TaskStatus, SubmissionStatus, UserRole, PayoutStatus,
    ChallengeVerdict, ChallengeStatus,
    TrustTier, TrustEventType, StakePurpose,
)


class UserCreate(BaseModel):
    nickname: str
    wallet: str
    role: UserRole


class UserOut(BaseModel):
    id: str
    nickname: str
    wallet: str
    role: UserRole
    trust_score: float = 500.0
    trust_tier: TrustTier = TrustTier.A
    github_id: Optional[str] = None
    is_arbiter: bool = False
    staked_amount: float = 0.0
    created_at: UTCDatetime

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
    submission_deposit: Optional[float] = None
    challenge_duration: Optional[int] = None
    acceptance_criteria: Optional[str] = None

    @model_validator(mode="after")
    def check_fastest_first_threshold(self) -> "TaskCreate":
        if self.type == TaskType.fastest_first and self.threshold is None:
            raise ValueError("fastest_first tasks require a threshold")
        return self


class ScoringDimensionPublic(BaseModel):
    name: str
    description: str

    model_config = {"from_attributes": True}


class TaskOut(BaseModel):
    id: str
    title: str
    description: str
    type: TaskType
    threshold: Optional[float] = None
    max_revisions: Optional[int] = None
    deadline: UTCDatetime
    status: TaskStatus
    winner_submission_id: Optional[str] = None
    publisher_id: Optional[str] = None
    bounty: Optional[float] = None
    payment_tx_hash: Optional[str] = None
    payout_status: PayoutStatus = PayoutStatus.pending
    payout_tx_hash: Optional[str] = None
    payout_amount: Optional[float] = None
    submission_deposit: Optional[float] = None
    challenge_duration: Optional[int] = None
    challenge_window_end: Optional[UTCDatetime] = None
    acceptance_criteria: Optional[str] = None
    scoring_dimensions: List["ScoringDimensionPublic"] = []
    refund_amount: Optional[float] = None
    refund_tx_hash: Optional[str] = None
    escrow_tx_hash: Optional[str] = None
    created_at: UTCDatetime

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
    deposit: Optional[float] = None
    deposit_returned: Optional[float] = None
    created_at: UTCDatetime

    model_config = {"from_attributes": True}


class ChallengeCreate(BaseModel):
    challenger_submission_id: str
    reason: str
    challenger_wallet: Optional[str] = None
    permit_deadline: Optional[int] = None
    permit_v: Optional[int] = None
    permit_r: Optional[str] = None
    permit_s: Optional[str] = None


class ChallengeOut(BaseModel):
    id: str
    task_id: str
    challenger_submission_id: str
    target_submission_id: str
    reason: str
    verdict: Optional[ChallengeVerdict] = None
    arbiter_feedback: Optional[str] = None
    arbiter_score: Optional[float] = None
    status: ChallengeStatus
    challenger_wallet: Optional[str] = None
    deposit_tx_hash: Optional[str] = None
    deposit_amount: Optional[float] = None
    created_at: UTCDatetime

    model_config = {"from_attributes": True}


class ScoreInput(BaseModel):
    score: float
    feedback: Optional[str] = None


class ManualJudgeInput(BaseModel):
    verdict: ChallengeVerdict
    score: float
    feedback: Optional[str] = None


TaskOut.model_rebuild()


class TrustProfile(BaseModel):
    trust_score: float
    trust_tier: TrustTier
    challenge_deposit_rate: float
    platform_fee_rate: float
    can_accept_tasks: bool
    can_challenge: bool
    max_task_amount: Optional[float] = None
    is_arbiter: bool
    github_bound: bool
    staked_amount: float
    stake_bonus: float
    consolation_total: float


class TrustEventOut(BaseModel):
    id: str
    event_type: TrustEventType
    task_id: Optional[str] = None
    amount: float
    delta: float
    score_before: float
    score_after: float
    created_at: UTCDatetime

    model_config = {"from_attributes": True}


class BalanceEventOut(BaseModel):
    id: str
    event_type: str
    role: str
    task_id: Optional[str] = None
    task_title: Optional[str] = None
    amount: float
    direction: str
    tx_hash: Optional[str] = None
    created_at: UTCDatetime


class ArbiterVoteCreate(BaseModel):
    verdict: ChallengeVerdict
    feedback: str


class ArbiterVoteOut(BaseModel):
    id: str
    challenge_id: str
    arbiter_user_id: str
    vote: Optional[ChallengeVerdict] = None
    feedback: Optional[str] = None
    is_majority: Optional[bool] = None
    reward_amount: Optional[float] = None
    created_at: UTCDatetime

    model_config = {"from_attributes": True}


class StakeRequest(BaseModel):
    amount: float
    purpose: StakePurpose
    permit_deadline: Optional[int] = None
    permit_v: Optional[int] = None
    permit_r: Optional[str] = None
    permit_s: Optional[str] = None


class TrustQuote(BaseModel):
    trust_tier: TrustTier
    challenge_deposit_rate: float
    challenge_deposit_amount: float
    platform_fee_rate: float
    service_fee: float = 0.01


class WeeklyLeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    nickname: str
    wallet: str
    total_settled: float
    bonus: int



TaskDetail.model_rebuild()
