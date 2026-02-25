"""Tests for publisher refund logic.

Scenarios:
- No submissions by deadline → 100% refund
- Submissions but none pass threshold → 95% refund
- fastest_first expiry handling
- Refund fields stored correctly on task
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import (
    Task, Submission, User,
    TaskType, TaskStatus, SubmissionStatus, PayoutStatus, UserRole,
)


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_publisher(db, wallet="0xPublisher"):
    user = User(nickname="pub1", wallet=wallet, role=UserRole.publisher)
    db.add(user)
    db.flush()
    return user


def make_expired_task(db, task_type, bounty=10.0, threshold=None, publisher_id=None):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(
        title="T", description="d", type=task_type,
        deadline=past, bounty=bounty, threshold=threshold,
        max_revisions=3, publisher_id=publisher_id,
    )
    db.add(task)
    db.flush()
    return task


def add_pending_submission(db, task_id, worker_id, content="answer"):
    sub = Submission(
        task_id=task_id, worker_id=worker_id, revision=1,
        content=content, status=SubmissionStatus.pending,
    )
    db.add(sub)
    db.flush()
    return sub


def add_scored_submission(db, task_id, worker_id, score, content="answer"):
    sub = Submission(
        task_id=task_id, worker_id=worker_id, revision=1,
        content=content, score=score, status=SubmissionStatus.scored,
    )
    db.add(sub)
    db.flush()
    return sub


REFUND_MOCK = patch(
    "app.services.payout._send_usdc_transfer", return_value="0xrefund_tx"
)


# --- quality_first: no submissions → 100% refund ---

def test_quality_first_no_submissions_full_refund():
    db = make_db()
    pub = make_publisher(db)
    task = make_expired_task(
        db, TaskType.quality_first, bounty=10.0, publisher_id=pub.id
    )
    db.commit()

    with REFUND_MOCK as mock_transfer:
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.payout_status == PayoutStatus.refunded
    assert task.refund_amount == 10.0
    assert task.refund_tx_hash == "0xrefund_tx"
    mock_transfer.assert_called_once_with("0xPublisher", 10.0)


# --- quality_first: submissions but none pass threshold → 95% refund ---

def test_quality_first_no_qualifying_submissions_95_refund():
    db = make_db()
    pub = make_publisher(db)
    task = make_expired_task(
        db, TaskType.quality_first, bounty=10.0,
        threshold=0.8, publisher_id=pub.id,
    )
    task.status = TaskStatus.scoring
    # All submissions scored below threshold
    add_scored_submission(db, task.id, "w1", 0.5)
    add_scored_submission(db, task.id, "w2", 0.6)
    db.commit()

    with REFUND_MOCK as mock_transfer:
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.payout_status == PayoutStatus.refunded
    assert task.refund_amount == 9.5  # 10 * 0.95
    assert task.refund_tx_hash == "0xrefund_tx"


# --- quality_first: submissions above threshold → normal flow (no refund) ---

def test_quality_first_qualifying_submission_no_refund():
    db = make_db()
    pub = make_publisher(db)
    task = make_expired_task(
        db, TaskType.quality_first, bounty=10.0,
        threshold=0.8, publisher_id=pub.id,
    )
    task.status = TaskStatus.scoring
    s1 = add_scored_submission(db, task.id, "w1", 0.9)
    add_scored_submission(db, task.id, "w2", 0.6)
    db.commit()

    with patch("app.scheduler.create_challenge_onchain"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.challenge_window
    assert task.winner_submission_id == s1.id
    assert task.payout_status == PayoutStatus.pending  # not refunded


# --- quality_first: no threshold set → all scored subs qualify (backward compat) ---

def test_quality_first_no_threshold_picks_best():
    db = make_db()
    pub = make_publisher(db)
    task = make_expired_task(
        db, TaskType.quality_first, bounty=10.0,
        threshold=None, publisher_id=pub.id,
    )
    task.status = TaskStatus.scoring
    s1 = add_scored_submission(db, task.id, "w1", 0.3)
    db.commit()

    with patch("app.scheduler.create_challenge_onchain"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    # Even with low score, no threshold means it qualifies
    assert task.status == TaskStatus.challenge_window
    assert task.winner_submission_id == s1.id


# --- fastest_first: no submissions → 100% refund ---

def test_fastest_first_no_submissions_full_refund():
    db = make_db()
    pub = make_publisher(db)
    task = make_expired_task(
        db, TaskType.fastest_first, bounty=5.0,
        threshold=0.8, publisher_id=pub.id,
    )
    db.commit()

    with REFUND_MOCK as mock_transfer:
        from app.scheduler import fastest_first_refund
        fastest_first_refund(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.payout_status == PayoutStatus.refunded
    assert task.refund_amount == 5.0


# --- fastest_first: submissions but none passed threshold → 95% refund ---

def test_fastest_first_no_qualifying_95_refund():
    db = make_db()
    pub = make_publisher(db)
    task = make_expired_task(
        db, TaskType.fastest_first, bounty=5.0,
        threshold=0.8, publisher_id=pub.id,
    )
    # Submission scored below threshold (scored by oracle inline, but task still open)
    add_scored_submission(db, task.id, "w1", 0.5)
    db.commit()

    with REFUND_MOCK as mock_transfer:
        from app.scheduler import fastest_first_refund
        fastest_first_refund(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.payout_status == PayoutStatus.refunded
    assert task.refund_amount == 4.75  # 5 * 0.95


# --- fastest_first: already closed task not touched ---

def test_fastest_first_closed_not_refunded():
    db = make_db()
    pub = make_publisher(db)
    task = make_expired_task(
        db, TaskType.fastest_first, bounty=5.0,
        threshold=0.8, publisher_id=pub.id,
    )
    task.status = TaskStatus.closed
    task.payout_status = PayoutStatus.paid
    db.commit()

    from app.scheduler import fastest_first_refund
    fastest_first_refund(db=db)

    db.refresh(task)
    # Task was already closed before, should stay closed/paid
    assert task.payout_status == PayoutStatus.paid
    assert task.refund_amount is None


# --- zero bounty: no refund needed ---

def test_zero_bounty_no_refund():
    db = make_db()
    task = make_expired_task(db, TaskType.quality_first, bounty=0)
    db.commit()

    from app.scheduler import quality_first_lifecycle
    quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.payout_status == PayoutStatus.pending  # not refunded, no money involved


# --- double refund protection ---

def test_refund_not_called_twice():
    db = make_db()
    pub = make_publisher(db)
    task = make_expired_task(
        db, TaskType.quality_first, bounty=10.0, publisher_id=pub.id
    )
    task.status = TaskStatus.closed
    task.payout_status = PayoutStatus.refunded
    task.refund_amount = 10.0
    db.commit()

    with REFUND_MOCK as mock_transfer:
        from app.services.payout import refund_publisher
        refund_publisher(db, task.id, rate=1.0)

    # Should not have called transfer again
    mock_transfer.assert_not_called()
    db.refresh(task)
    assert task.refund_amount == 10.0
