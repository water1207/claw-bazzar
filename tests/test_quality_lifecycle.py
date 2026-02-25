import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import (
    Task, Submission, Challenge, User,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus, ChallengeVerdict,
    UserRole,
)


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def make_expired_quality_task(db, bounty=10.0):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(
        title="Q", description="d", type=TaskType.quality_first,
        max_revisions=3, deadline=past, bounty=bounty,
        submission_deposit=1.0, challenge_duration=7200,
    )
    db.add(task)
    db.flush()
    return task


def add_scored_submission(db, task_id, worker_id, score, content="c"):
    sub = Submission(
        task_id=task_id, worker_id=worker_id, revision=1,
        content=content, score=score, status=SubmissionStatus.scored,
        deposit=1.0,
    )
    db.add(sub)
    db.flush()
    return sub


# --- Phase 1: open -> scoring ---

def test_phase1_open_to_scoring():
    db = make_db()
    task = make_expired_quality_task(db)
    add_scored_submission(db, task.id, "w1", 0.9)
    db.commit()

    from app.scheduler import quality_first_lifecycle
    quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.scoring


# --- Phase 2: scoring -> challenge_window ---

def test_phase2_scoring_to_challenge_window():
    db = make_db()
    task = make_expired_quality_task(db)
    s1 = add_scored_submission(db, task.id, "w1", 0.9)
    s2 = add_scored_submission(db, task.id, "w2", 0.7)
    task.status = TaskStatus.scoring
    db.commit()

    from app.scheduler import quality_first_lifecycle
    quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.challenge_window
    assert task.winner_submission_id == s1.id
    assert task.challenge_window_end is not None


def test_phase2_no_submissions_closes():
    db = make_db()
    task = make_expired_quality_task(db)
    task.status = TaskStatus.scoring
    db.commit()

    from app.scheduler import quality_first_lifecycle
    quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id is None


# --- Phase 3: challenge_window -> closed (no challenges) ---

def test_phase3_no_challenges_closes():
    db = make_db()
    task = make_expired_quality_task(db)
    s1 = add_scored_submission(db, task.id, "w1", 0.9)
    task.status = TaskStatus.challenge_window
    task.winner_submission_id = s1.id
    task.challenge_window_end = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    with patch("app.scheduler._resolve_via_contract") as mock_pay:
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)
        mock_pay.assert_called_once()

    db.refresh(task)
    assert task.status == TaskStatus.closed


def test_phase3_with_challenges_goes_to_arbitrating():
    db = make_db()
    task = make_expired_quality_task(db)
    s1 = add_scored_submission(db, task.id, "w1", 0.9)
    s2 = add_scored_submission(db, task.id, "w2", 0.7)
    task.status = TaskStatus.challenge_window
    task.winner_submission_id = s1.id
    task.challenge_window_end = datetime.now(timezone.utc) - timedelta(minutes=1)

    challenge = Challenge(
        task_id=task.id, challenger_submission_id=s2.id,
        target_submission_id=s1.id, reason="I am better",
    )
    db.add(challenge)
    db.commit()

    with patch("app.scheduler.run_arbitration") as mock_arb:
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)
        mock_arb.assert_called_once_with(db, task.id)

    db.refresh(task)
    assert task.status == TaskStatus.arbitrating


# --- Phase 3: deposit refund for non-challengers ---

def test_phase3_no_challenge_refunds_all_deposits():
    db = make_db()
    task = make_expired_quality_task(db)
    s1 = add_scored_submission(db, task.id, "w1", 0.9)
    s2 = add_scored_submission(db, task.id, "w2", 0.7)
    task.status = TaskStatus.challenge_window
    task.winner_submission_id = s1.id
    task.challenge_window_end = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    with patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(s1)
    db.refresh(s2)
    assert s1.deposit_returned == s1.deposit
    assert s2.deposit_returned == s2.deposit


def test_phase1_triggers_batch_scoring():
    """After open->scoring, batch_score runs on second tick (Phase 2)."""
    db = make_db()
    task = make_expired_quality_task(db)
    # Add pending submission (no score yet)
    sub = Submission(
        task_id=task.id, worker_id="w1", revision=1,
        content="answer", status=SubmissionStatus.pending,
    )
    db.add(sub)
    db.commit()

    fake_score = json.dumps({"score": 0.88, "feedback": "ok"})
    mock_result = type("R", (), {"stdout": fake_score, "returncode": 0})()

    with patch("app.services.oracle.subprocess.run", return_value=mock_result):
        from app.scheduler import quality_first_lifecycle
        # Tick 1: open -> scoring
        quality_first_lifecycle(db=db)
        db.refresh(task)
        assert task.status == TaskStatus.scoring
        # Tick 2: Phase 2 runs batch_score
        quality_first_lifecycle(db=db)

    db.refresh(task)
    db.refresh(sub)
    assert sub.status == SubmissionStatus.scored
    assert sub.score == 0.88
