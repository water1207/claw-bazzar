import os
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timedelta, timezone


def make_db():
    from app.database import Base
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def test_pay_winner_calculates_80_percent():
    from app.models import Task, Submission, User, TaskType, TaskStatus, SubmissionStatus, PayoutStatus
    Session = make_db()
    db = Session()

    user = User(nickname="winner1", wallet="0xWINNER", role="worker")
    db.add(user)
    db.flush()

    task = Task(
        title="T", description="d", type=TaskType.fastest_first,
        threshold=0.8, deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        status=TaskStatus.closed, publisher_id="pub-1", bounty=10.0,
        winner_submission_id="sub-1",
    )
    db.add(task)
    db.flush()

    sub = Submission(
        id="sub-1", task_id=task.id, worker_id=user.id,
        revision=1, content="answer", score=0.9, status=SubmissionStatus.scored,
    )
    db.add(sub)
    db.commit()

    with patch("app.services.payout._send_usdc_transfer") as mock_send:
        mock_send.return_value = "0xPAYOUT_TX"
        from app.services.payout import pay_winner
        pay_winner(db, task.id)

    db.refresh(task)
    assert task.payout_status == PayoutStatus.paid
    assert task.payout_tx_hash == "0xPAYOUT_TX"
    assert task.payout_amount == 8.0  # 10.0 * 0.80
    mock_send.assert_called_once_with("0xWINNER", 8.0)
    db.close()


def test_pay_winner_handles_transfer_failure():
    from app.models import Task, Submission, User, TaskType, TaskStatus, SubmissionStatus, PayoutStatus
    Session = make_db()
    db = Session()

    user = User(nickname="winner2", wallet="0xWINNER2", role="worker")
    db.add(user)
    db.flush()

    task = Task(
        title="T", description="d", type=TaskType.fastest_first,
        threshold=0.8, deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        status=TaskStatus.closed, publisher_id="pub-1", bounty=5.0,
        winner_submission_id="sub-2",
    )
    db.add(task)
    db.flush()

    sub = Submission(
        id="sub-2", task_id=task.id, worker_id=user.id,
        revision=1, content="answer", score=0.9, status=SubmissionStatus.scored,
    )
    db.add(sub)
    db.commit()

    with patch("app.services.payout._send_usdc_transfer") as mock_send:
        mock_send.side_effect = Exception("RPC error")
        from app.services.payout import pay_winner
        pay_winner(db, task.id)

    db.refresh(task)
    assert task.payout_status == PayoutStatus.failed
    assert task.payout_tx_hash is None
    db.close()


def test_pay_winner_skips_if_no_winner():
    from app.models import Task, TaskType, TaskStatus, PayoutStatus
    Session = make_db()
    db = Session()

    task = Task(
        title="T", description="d", type=TaskType.fastest_first,
        threshold=0.8, deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        status=TaskStatus.closed, publisher_id="pub-1", bounty=5.0,
        winner_submission_id=None,
    )
    db.add(task)
    db.commit()

    from app.services.payout import pay_winner
    pay_winner(db, task.id)

    db.refresh(task)
    assert task.payout_status == PayoutStatus.pending  # unchanged
    db.close()
