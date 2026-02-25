from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import (
    Task, Submission, Challenge, User,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus, ChallengeVerdict,
    UserRole, PayoutStatus,
)


def make_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def setup_arbitrating_task(db):
    """Create a task in arbitrating state with 2 submissions and 1 challenge."""
    user_w1 = User(nickname="w1", wallet="0xaaa", role=UserRole.worker)
    user_w2 = User(nickname="w2", wallet="0xbbb", role=UserRole.worker)
    db.add_all([user_w1, user_w2])
    db.flush()

    task = Task(
        title="Q", description="d", type=TaskType.quality_first,
        max_revisions=3, deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        bounty=10.0, submission_deposit=1.0, challenge_duration=7200,
        status=TaskStatus.arbitrating,
    )
    db.add(task)
    db.flush()

    s1 = Submission(
        task_id=task.id, worker_id=user_w1.id, revision=1,
        content="winner", score=0.9, status=SubmissionStatus.scored, deposit=1.0,
    )
    s2 = Submission(
        task_id=task.id, worker_id=user_w2.id, revision=1,
        content="challenger", score=0.7, status=SubmissionStatus.scored, deposit=1.0,
    )
    db.add_all([s1, s2])
    db.flush()
    task.winner_submission_id = s1.id

    challenge = Challenge(
        task_id=task.id, challenger_submission_id=s2.id,
        target_submission_id=s1.id, reason="I am better",
    )
    db.add(challenge)
    db.commit()
    return task, s1, s2, challenge, user_w1, user_w2


def test_settle_upheld_changes_winner():
    db = make_db()
    task, s1, s2, challenge, w1, w2 = setup_arbitrating_task(db)

    # Manually judge the challenge as upheld
    challenge.verdict = ChallengeVerdict.upheld
    challenge.arbiter_score = 0.95
    challenge.status = ChallengeStatus.judged
    db.commit()

    with patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == s2.id  # Challenger took over

    db.refresh(s2)
    assert s2.deposit_returned == round(s2.deposit * 0.70, 6)  # 70% returned (30% to arbiters)

    # Challenger gets challenger_won trust event (weighted by bounty)
    from app.models import TrustEvent, TrustEventType
    events = db.query(TrustEvent).filter_by(
        user_id=w2.id, event_type=TrustEventType.challenger_won
    ).all()
    assert len(events) == 1


def test_settle_rejected_deducts_deposit():
    db = make_db()
    task, s1, s2, challenge, w1, w2 = setup_arbitrating_task(db)

    challenge.verdict = ChallengeVerdict.rejected
    challenge.status = ChallengeStatus.judged
    db.commit()

    with patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == s1.id  # Original winner stays

    db.refresh(s2)
    assert s2.deposit_returned == 0  # Challenger gets nothing on rejection


def test_settle_malicious_confiscates_deposit_and_credit():
    db = make_db()
    task, s1, s2, challenge, w1, w2 = setup_arbitrating_task(db)

    challenge.verdict = ChallengeVerdict.malicious
    challenge.status = ChallengeStatus.judged
    db.commit()

    with patch("app.scheduler._resolve_via_contract"), \
         patch("app.services.staking.slash_onchain", return_value="0xslash"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == s1.id  # Original winner stays

    db.refresh(s2)
    assert s2.deposit_returned == 0  # Confiscated

    # Challenger gets challenger_malicious trust event (-100)
    from app.models import TrustEvent, TrustEventType
    events = db.query(TrustEvent).filter_by(
        user_id=w2.id, event_type=TrustEventType.challenger_malicious
    ).all()
    assert len(events) == 1
    db.refresh(w2)
    assert w2.trust_score == 400.0  # 500 - 100


def test_settle_multiple_upheld_picks_highest():
    db = make_db()
    user_w1 = User(nickname="w1", wallet="0xaaa", role=UserRole.worker)
    user_w2 = User(nickname="w2", wallet="0xbbb", role=UserRole.worker)
    user_w3 = User(nickname="w3", wallet="0xccc", role=UserRole.worker)
    db.add_all([user_w1, user_w2, user_w3])
    db.flush()

    task = Task(
        title="Q", description="d", type=TaskType.quality_first,
        max_revisions=3, deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        bounty=10.0, submission_deposit=1.0,
        status=TaskStatus.arbitrating,
    )
    db.add(task)
    db.flush()

    s1 = Submission(task_id=task.id, worker_id=user_w1.id, revision=1,
                    content="a", score=0.9, status=SubmissionStatus.scored, deposit=1.0)
    s2 = Submission(task_id=task.id, worker_id=user_w2.id, revision=1,
                    content="b", score=0.7, status=SubmissionStatus.scored, deposit=1.0)
    s3 = Submission(task_id=task.id, worker_id=user_w3.id, revision=1,
                    content="c", score=0.8, status=SubmissionStatus.scored, deposit=1.0)
    db.add_all([s1, s2, s3])
    db.flush()
    task.winner_submission_id = s1.id

    c1 = Challenge(task_id=task.id, challenger_submission_id=s2.id,
                   target_submission_id=s1.id, reason="r1",
                   verdict=ChallengeVerdict.upheld, arbiter_score=0.88,
                   status=ChallengeStatus.judged)
    c2 = Challenge(task_id=task.id, challenger_submission_id=s3.id,
                   target_submission_id=s1.id, reason="r2",
                   verdict=ChallengeVerdict.upheld, arbiter_score=0.95,
                   status=ChallengeStatus.judged)
    db.add_all([c1, c2])
    db.commit()

    with patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(task)
    assert task.winner_submission_id == s3.id  # w3 had higher arbiter_score


def test_non_challengers_get_full_refund():
    db = make_db()
    task, s1, s2, challenge, w1, w2 = setup_arbitrating_task(db)

    # Add a third non-challenging worker
    user_w3 = User(nickname="w3", wallet="0xccc", role=UserRole.worker)
    db.add(user_w3)
    db.flush()
    s3 = Submission(task_id=task.id, worker_id=user_w3.id, revision=1,
                    content="passive", score=0.5, status=SubmissionStatus.scored, deposit=1.0)
    db.add(s3)

    challenge.verdict = ChallengeVerdict.rejected
    challenge.status = ChallengeStatus.judged
    db.commit()

    with patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import quality_first_lifecycle
        quality_first_lifecycle(db=db)

    db.refresh(s1)
    db.refresh(s3)
    assert s1.deposit_returned == s1.deposit  # Winner: full refund
    assert s3.deposit_returned == s3.deposit  # Non-challenger: full refund
