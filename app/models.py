import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, Enum, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from .database import Base


class TaskType(str, PyEnum):
    fastest_first = "fastest_first"
    quality_first = "quality_first"


class TaskStatus(str, PyEnum):
    open = "open"
    scoring = "scoring"
    challenge_window = "challenge_window"
    arbitrating = "arbitrating"
    closed = "closed"


class SubmissionStatus(str, PyEnum):
    pending = "pending"
    gate_passed = "gate_passed"
    gate_failed = "gate_failed"
    scored = "scored"
    policy_violation = "policy_violation"


class UserRole(str, PyEnum):
    publisher = "publisher"
    worker = "worker"
    both = "both"


class PayoutStatus(str, PyEnum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
    refunded = "refunded"


class ChallengeVerdict(str, PyEnum):
    upheld = "upheld"
    rejected = "rejected"
    malicious = "malicious"


class ChallengeStatus(str, PyEnum):
    pending = "pending"
    judged = "judged"


class TrustTier(str, PyEnum):
    S = "S"
    A = "A"
    B = "B"
    C = "C"


class TrustEventType(str, PyEnum):
    worker_won = "worker_won"
    worker_consolation = "worker_consolation"
    worker_malicious = "worker_malicious"
    challenger_won = "challenger_won"
    challenger_rejected = "challenger_rejected"
    challenger_malicious = "challenger_malicious"
    arbiter_majority = "arbiter_majority"
    arbiter_minority = "arbiter_minority"
    arbiter_timeout = "arbiter_timeout"
    github_bind = "github_bind"
    weekly_leaderboard = "weekly_leaderboard"
    stake_bonus = "stake_bonus"
    stake_slash = "stake_slash"
    publisher_completed = "publisher_completed"
    arbiter_coherence = "arbiter_coherence"


class StakePurpose(str, PyEnum):
    arbiter_deposit = "arbiter_deposit"
    credit_recharge = "credit_recharge"


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
    winner_submission_id = Column(String, nullable=True)
    publisher_id = Column(String, nullable=True)
    bounty = Column(Float, nullable=True)
    payment_tx_hash = Column(String, nullable=True)
    payout_status = Column(Enum(PayoutStatus), nullable=False, default=PayoutStatus.pending)
    payout_tx_hash = Column(String, nullable=True)
    payout_amount = Column(Float, nullable=True)
    submission_deposit = Column(Float, nullable=True)
    challenge_duration = Column(Integer, nullable=True)
    challenge_window_end = Column(DateTime(timezone=True), nullable=True)
    acceptance_criteria = Column(Text, nullable=True)
    refund_amount = Column(Float, nullable=True)
    refund_tx_hash = Column(String, nullable=True)
    escrow_tx_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ScoringDimension(Base):
    __tablename__ = "scoring_dimensions"

    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    dim_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    dim_type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    weight = Column(Float, nullable=False)
    scoring_guidance = Column(Text, nullable=False)

    task = relationship("Task", backref="dimensions")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    nickname = Column(String, unique=True, nullable=False)
    wallet = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    trust_score = Column(Float, nullable=False, default=500.0)
    trust_tier = Column(Enum(TrustTier), nullable=False, default=TrustTier.A)
    github_id = Column(String, nullable=True)
    github_bonus_claimed = Column(Boolean, nullable=False, default=False)
    consolation_total = Column(Float, nullable=False, default=0.0)
    is_arbiter = Column(Boolean, nullable=False, default=False)
    staked_amount = Column(Float, nullable=False, default=0.0)
    stake_bonus = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, nullable=False)
    worker_id = Column(String, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    score = Column(Float, nullable=True)
    oracle_feedback = Column(Text, nullable=True)
    status = Column(Enum(SubmissionStatus), nullable=False, default=SubmissionStatus.pending)
    deposit = Column(Float, nullable=True)
    deposit_returned = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class Challenge(Base):
    __tablename__ = "challenges"

    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, nullable=False)
    challenger_submission_id = Column(String, nullable=False)
    target_submission_id = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    verdict = Column(Enum(ChallengeVerdict), nullable=True)
    arbiter_feedback = Column(Text, nullable=True)
    arbiter_score = Column(Float, nullable=True)
    status = Column(Enum(ChallengeStatus), nullable=False, default=ChallengeStatus.pending)
    challenger_wallet = Column(String, nullable=True)
    deposit_tx_hash = Column(String, nullable=True)
    deposit_amount = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class TrustEvent(Base):
    __tablename__ = "trust_events"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    event_type = Column(Enum(TrustEventType), nullable=False)
    task_id = Column(String, nullable=True)
    amount = Column(Float, nullable=False, default=0.0)
    delta = Column(Float, nullable=False, default=0.0)
    score_before = Column(Float, nullable=False, default=0.0)
    score_after = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class ArbiterVote(Base):
    __tablename__ = "arbiter_votes"

    id = Column(String, primary_key=True, default=_uuid)
    challenge_id = Column(String, nullable=False)
    arbiter_user_id = Column(String, nullable=False)
    vote = Column(Enum(ChallengeVerdict), nullable=True)
    feedback = Column(Text, nullable=True)
    is_majority = Column(Boolean, nullable=True)
    reward_amount = Column(Float, nullable=True)
    coherence_status = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class StakeRecord(Base):
    __tablename__ = "stake_records"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, nullable=False)
    amount = Column(Float, nullable=False, default=0.0)
    purpose = Column(Enum(StakePurpose), nullable=False)
    tx_hash = Column(String, nullable=True)
    slashed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
