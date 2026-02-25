from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import (
    Task, Submission, User, Challenge,
    TaskType, TaskStatus, SubmissionStatus, PayoutStatus,
    ChallengeVerdict, ChallengeStatus, UserRole,
)
from datetime import datetime, timedelta, timezone


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_task_status_has_new_values():
    assert TaskStatus.scoring == "scoring"
    assert TaskStatus.challenge_window == "challenge_window"
    assert TaskStatus.arbitrating == "arbitrating"


def test_challenge_verdict_enum():
    assert ChallengeVerdict.upheld == "upheld"
    assert ChallengeVerdict.rejected == "rejected"
    assert ChallengeVerdict.malicious == "malicious"


def test_challenge_status_enum():
    assert ChallengeStatus.pending == "pending"
    assert ChallengeStatus.judged == "judged"


def test_task_new_fields():
    db = make_db()
    task = Task(
        title="T", description="d", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        submission_deposit=1.0, challenge_duration=7200,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    assert task.submission_deposit == 1.0
    assert task.challenge_duration == 7200
    assert task.challenge_window_end is None


def test_submission_deposit_fields():
    db = make_db()
    task = Task(title="T", description="d", type=TaskType.quality_first,
                deadline=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(task)
    db.flush()
    sub = Submission(task_id=task.id, worker_id="w1", content="c", deposit=0.5)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    assert sub.deposit == 0.5
    assert sub.deposit_returned is None


def test_user_trust_score_default():
    db = make_db()
    user = User(nickname="test", wallet="0x123", role=UserRole.worker)
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.trust_score == 500.0


def test_challenge_create():
    db = make_db()
    task = Task(title="T", description="d", type=TaskType.quality_first,
                deadline=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(task)
    db.flush()
    s1 = Submission(task_id=task.id, worker_id="w1", content="a")
    s2 = Submission(task_id=task.id, worker_id="w2", content="b")
    db.add_all([s1, s2])
    db.flush()

    challenge = Challenge(
        task_id=task.id,
        challenger_submission_id=s2.id,
        target_submission_id=s1.id,
        reason="My submission is better because...",
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    assert challenge.status == ChallengeStatus.pending
    assert challenge.verdict is None
    assert challenge.arbiter_score is None
