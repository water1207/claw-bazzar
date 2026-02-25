"""Tests for escrow-integrated settlement in scheduler."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from app.models import (
    Task, Submission, Challenge, User,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus, ChallengeVerdict, PayoutStatus,
)
from app.scheduler import _settle_after_arbitration


def _setup_arbitrated_task(db):
    """Create a task in arbitrating state with one judged challenge."""
    user_w = User(id="w1", nickname="worker1", wallet="0xWinner", role="worker")
    user_c = User(id="w2", nickname="worker2", wallet="0xChallenger", role="worker")
    db.add_all([user_w, user_c])

    task = Task(
        id="t1", title="T", description="d", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        status=TaskStatus.arbitrating,
        winner_submission_id="s1", bounty=10.0,
        submission_deposit=1.0,
    )
    db.add(task)

    s1 = Submission(id="s1", task_id="t1", worker_id="w1", content="winner", score=0.9,
                    status=SubmissionStatus.scored, deposit=1.0)
    s2 = Submission(id="s2", task_id="t1", worker_id="w2", content="challenger", score=0.7,
                    status=SubmissionStatus.scored, deposit=1.0)
    db.add_all([s1, s2])

    challenge = Challenge(
        id="c1", task_id="t1",
        challenger_submission_id="s2", target_submission_id="s1",
        reason="better", verdict=ChallengeVerdict.rejected,
        arbiter_score=0.6, status=ChallengeStatus.judged,
        challenger_wallet="0xChallenger",
    )
    db.add(challenge)
    db.commit()
    return task


def test_settle_calls_escrow_when_challengers_have_wallets(client):
    """When challenges have challenger_wallet, settlement calls resolveChallenge."""
    from app.database import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())

    task = _setup_arbitrated_task(db)

    with patch("app.scheduler.resolve_challenge_onchain", return_value="0xresolve") as mock_resolve:
        _settle_after_arbitration(db, task)

    # Verify resolveChallenge was called via _resolve_via_contract
    mock_resolve.assert_called_once()

    # Verify task is closed and payout recorded
    db.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.payout_tx_hash == "0xresolve"
    assert task.payout_status == PayoutStatus.paid


def test_settle_without_wallets_still_resolves(client):
    """When no challenger_wallet, settlement still resolves via contract with empty verdicts."""
    from app.database import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())

    # Setup without challenger_wallet
    user_w = User(id="w1b", nickname="worker1b", wallet="0xWinner", role="worker")
    user_c = User(id="w2b", nickname="worker2b", wallet="0xChallenger", role="worker")
    db.add_all([user_w, user_c])

    task = Task(
        id="t1b", title="T", description="d", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        status=TaskStatus.arbitrating,
        winner_submission_id="s1b", bounty=10.0, submission_deposit=1.0,
    )
    db.add(task)

    s1 = Submission(id="s1b", task_id="t1b", worker_id="w1b", content="w", score=0.9,
                    status=SubmissionStatus.scored, deposit=1.0)
    s2 = Submission(id="s2b", task_id="t1b", worker_id="w2b", content="c", score=0.7,
                    status=SubmissionStatus.scored, deposit=1.0)
    db.add_all([s1, s2])

    challenge = Challenge(
        id="c1b", task_id="t1b",
        challenger_submission_id="s2b", target_submission_id="s1b",
        reason="test", verdict=ChallengeVerdict.rejected,
        arbiter_score=0.6, status=ChallengeStatus.judged,
        challenger_wallet=None,  # No wallet -> no verdict entry, but escrow still called
    )
    db.add(challenge)
    db.commit()

    with patch("app.scheduler.resolve_challenge_onchain", return_value="0xresolve") as mock_resolve:
        _settle_after_arbitration(db, task)

    # Still calls resolve with empty verdicts (no challenger_wallet)
    mock_resolve.assert_called_once()

    db.refresh(task)
    assert task.status == TaskStatus.closed
