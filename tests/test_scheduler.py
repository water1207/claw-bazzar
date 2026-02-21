from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Task, Submission, TaskType, TaskStatus, SubmissionStatus


def make_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return engine


def test_settle_picks_highest_score():
    engine = make_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(title="Q", description="d", type=TaskType.quality_first,
                max_revisions=3, deadline=past)
    db.add(task)
    db.flush()

    s1 = Submission(task_id=task.id, worker_id="w1", revision=1, content="v1",
                    score=0.6, status=SubmissionStatus.scored)
    s2 = Submission(task_id=task.id, worker_id="w1", revision=2, content="v2",
                    score=0.85, status=SubmissionStatus.scored)
    s3 = Submission(task_id=task.id, worker_id="w2", revision=1, content="v3",
                    score=0.7, status=SubmissionStatus.scored)
    db.add_all([s1, s2, s3])
    db.commit()

    from app.scheduler import settle_expired_quality_first
    settle_expired_quality_first(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == s2.id


def test_settle_closes_with_no_scored_submissions():
    engine = make_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(title="Q2", description="d", type=TaskType.quality_first,
                max_revisions=3, deadline=past)
    db.add(task)
    db.commit()

    from app.scheduler import settle_expired_quality_first
    settle_expired_quality_first(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id is None


def test_settle_ignores_open_tasks():
    engine = make_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    task = Task(title="Q3", description="d", type=TaskType.quality_first,
                max_revisions=3, deadline=future)
    db.add(task)
    db.commit()

    from app.scheduler import settle_expired_quality_first
    settle_expired_quality_first(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.open


def test_settle_ignores_fastest_first_tasks():
    engine = make_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(title="F", description="d", type=TaskType.fastest_first,
                threshold=0.8, deadline=past)
    db.add(task)
    db.commit()

    from app.scheduler import settle_expired_quality_first
    settle_expired_quality_first(db=db)

    db.refresh(task)
    # fastest_first is NOT handled by scheduler
    assert task.status == TaskStatus.open


def test_settle_triggers_payout():
    engine = make_engine()
    Session = sessionmaker(bind=engine)
    db = Session()

    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    task = Task(title="Q", description="d", type=TaskType.quality_first,
                max_revisions=3, deadline=past, publisher_id="pub-1", bounty=10.0)
    db.add(task)
    db.flush()

    s1 = Submission(task_id=task.id, worker_id="w1", revision=1, content="v1",
                    score=0.85, status=SubmissionStatus.scored)
    db.add(s1)
    db.commit()

    with patch("app.scheduler.pay_winner") as mock_payout:
        from app.scheduler import settle_expired_quality_first
        settle_expired_quality_first(db=db)
        mock_payout.assert_called_once_with(db, task.id)
