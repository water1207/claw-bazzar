import json
from datetime import datetime, timezone
from typing import Optional, List, Annotated
from pydantic import BaseModel, model_validator, field_validator, PlainSerializer


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
    acceptance_criteria: list[str]

    @field_validator('acceptance_criteria')
    @classmethod
    def validate_criteria(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("acceptance_criteria must have at least one item")
        return v

    @field_validator('bounty')
    @classmethod
    def bounty_minimum(cls, v: float) -> float:
        if v < 0.1:
            raise ValueError("bounty must be at least 0.1 USDC")
        return v

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
    publisher_nickname: Optional[str] = None
    bounty: Optional[float] = None
    payment_tx_hash: Optional[str] = None
    payout_status: PayoutStatus = PayoutStatus.pending
    payout_tx_hash: Optional[str] = None
    payout_amount: Optional[float] = None
    submission_deposit: Optional[float] = None
    challenge_duration: Optional[int] = None
    acceptance_criteria: list[str] = []
    scoring_dimensions: List["ScoringDimensionPublic"] = []
    refund_amount: Optional[float] = None
    refund_tx_hash: Optional[str] = None
    escrow_tx_hash: Optional[str] = None
    created_at: UTCDatetime

    @model_validator(mode='before')
    @classmethod
    def parse_acceptance_criteria(cls, values):
        if isinstance(values, dict):
            raw = values.get('acceptance_criteria')
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    values['acceptance_criteria'] = parsed if isinstance(parsed, list) else []
                except (json.JSONDecodeError, ValueError):
                    values['acceptance_criteria'] = []
            return values
        else:
            # ORM object: convert to dict without modifying original object
            raw = getattr(values, 'acceptance_criteria', None)
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    parsed = parsed if isinstance(parsed, list) else []
                except (json.JSONDecodeError, ValueError):
                    parsed = []
            else:
                parsed = raw if isinstance(raw, list) else []
            # Extract all fields from ORM object into a dict
            from sqlalchemy.inspection import inspect as sa_inspect
            try:
                mapper = sa_inspect(values.__class__)
                d = {c.key: getattr(values, c.key) for c in mapper.mapper.column_attrs}
            except Exception:
                d = {k: v for k, v in values.__dict__.items() if not k.startswith('_')}
            d['acceptance_criteria'] = parsed
            return d

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


class JuryVoteIn(BaseModel):
    """Input for merged arbitration vote."""
    arbiter_user_id: str
    winner_submission_id: str
    malicious_submission_ids: list[str] = []
    feedback: str = ""

    @model_validator(mode="after")
    def winner_not_in_malicious(self):
        if self.winner_submission_id in self.malicious_submission_ids:
            raise ValueError("Winner cannot be tagged as malicious")
        return self


class JuryBallotOut(BaseModel):
    """Response for a single jury ballot."""
    id: str
    task_id: str
    arbiter_user_id: str
    winner_submission_id: Optional[str] = None
    feedback: Optional[str] = None
    coherence_status: Optional[str] = None
    is_majority: Optional[bool] = None
    created_at: UTCDatetime
    voted_at: Optional[UTCDatetime] = None
    model_config = {"from_attributes": True}


class MaliciousTagOut(BaseModel):
    """Response for a malicious tag."""
    id: str
    task_id: str
    arbiter_user_id: str
    target_submission_id: str
    created_at: UTCDatetime
    model_config = {"from_attributes": True}


class SettlementSource(BaseModel):
    label: str
    amount: float
    type: str           # "bounty" | "incentive" | "deposit"
    verdict: Optional[str] = None  # "upheld" | "rejected" | "malicious"

class SettlementDistribution(BaseModel):
    label: str
    amount: float
    type: str           # "winner" | "refund" | "arbiter" | "platform" | "publisher_refund"
    wallet: Optional[str] = None
    nickname: Optional[str] = None

class SettlementSummary(BaseModel):
    winner_payout: float
    winner_nickname: Optional[str] = None
    winner_tier: Optional[str] = None
    payout_rate: float
    deposits_forfeited: float
    deposits_refunded: float
    arbiter_reward_total: float
    platform_fee: float

class SettlementOut(BaseModel):
    escrow_total: float
    sources: list[SettlementSource]
    distributions: list[SettlementDistribution]
    resolve_tx_hash: Optional[str] = None
    summary: SettlementSummary


TaskDetail.model_rebuild()
