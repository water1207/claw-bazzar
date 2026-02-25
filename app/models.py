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
    scoring = "scoring"
    challenge_window = "challenge_window"
    arbitrating = "arbitrating"
    closed = "closed"


class SubmissionStatus(str, PyEnum):
    pending = "pending"
    gate_passed = "gate_passed"
    gate_failed = "gate_failed"
    scored = "scored"


class UserRole(str, PyEnum):
    publisher = "publisher"
    worker = "worker"
    both = "both"


class PayoutStatus(str, PyEnum):
    pending = "pending"
    paid = "paid"
    failed = "failed"


class ChallengeVerdict(str, PyEnum):
    upheld = "upheld"
    rejected = "rejected"
    malicious = "malicious"


class ChallengeStatus(str, PyEnum):
    pending = "pending"
    judged = "judged"


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
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    nickname = Column(String, unique=True, nullable=False)
    wallet = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    credit_score = Column(Float, nullable=False, default=100.0)
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
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
