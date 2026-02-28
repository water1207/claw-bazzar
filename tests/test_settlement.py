from unittest.mock import patch
from datetime import datetime, timezone
from app.models import (
    Task, TaskType, TaskStatus, Submission, SubmissionStatus,
    Challenge, ChallengeVerdict, ChallengeStatus,
    User, UserRole, TrustTier, PayoutStatus, JuryBallot,
)

PAYMENT_MOCK = patch("app.routers.tasks.verify_payment",
                     return_value={"valid": True, "tx_hash": "0xtest"})


def _seed_quality_first_settled(db):
    """Seed a fully settled quality_first task with challenges."""
    publisher = User(id="pub1", nickname="Alice", wallet="0xPUB", role=UserRole.publisher)
    worker_a = User(id="w1", nickname="Bob", wallet="0xBOB", role=UserRole.worker, trust_tier=TrustTier.A)
    worker_b = User(id="w2", nickname="Charlie", wallet="0xCHA", role=UserRole.worker, trust_tier=TrustTier.A)
    arbiter1 = User(id="a1", nickname="arb-alpha", wallet="0xARB1", role=UserRole.worker, trust_tier=TrustTier.S, is_arbiter=True)
    arbiter2 = User(id="a2", nickname="arb-beta", wallet="0xARB2", role=UserRole.worker, trust_tier=TrustTier.S, is_arbiter=True)
    db.add_all([publisher, worker_a, worker_b, arbiter1, arbiter2])

    task = Task(
        id="t1", title="Test", description="test", type=TaskType.quality_first,
        status=TaskStatus.closed, bounty=10.0, publisher_id="pub1",
        winner_submission_id="s2", payout_amount=9.2, payout_status=PayoutStatus.paid,
        payout_tx_hash="0xRESOLVE", escrow_tx_hash="0xESCROW",
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc),
        acceptance_criteria='["test"]',
    )
    sub_a = Submission(id="s1", task_id="t1", worker_id="w1", content="a", status=SubmissionStatus.scored, score=0.9)
    sub_b = Submission(id="s2", task_id="t1", worker_id="w2", content="b", status=SubmissionStatus.scored, score=0.95)
    db.add_all([task, sub_a, sub_b])

    # Charlie challenged and won (upheld), Bob's rejected
    ch1 = Challenge(
        id="c1", task_id="t1",
        challenger_submission_id="s2", target_submission_id="s1",
        reason="better", verdict=ChallengeVerdict.upheld, status=ChallengeStatus.judged,
        challenger_wallet="0xCHA", deposit_amount=1.0,
    )
    ch2 = Challenge(
        id="c2", task_id="t1",
        challenger_submission_id="s1", target_submission_id="s2",
        reason="disagree", verdict=ChallengeVerdict.rejected, status=ChallengeStatus.judged,
        challenger_wallet="0xBOB", deposit_amount=1.0,
    )
    db.add_all([ch1, ch2])

    # Jury ballots
    b1 = JuryBallot(id="jb1", task_id="t1", arbiter_user_id="a1", winner_submission_id="s2", coherence_status="coherent")
    b2 = JuryBallot(id="jb2", task_id="t1", arbiter_user_id="a2", winner_submission_id="s2", coherence_status="coherent")
    db.add_all([b1, b2])
    db.commit()


def test_settlement_404_not_found(client):
    resp = client.get("/tasks/nonexistent/settlement")
    assert resp.status_code == 404


def test_settlement_404_still_open(client_with_db):
    c, db = client_with_db
    with PAYMENT_MOCK:
        resp = c.post("/tasks", json={
            "title": "T", "description": "d", "type": "fastest_first",
            "threshold": 0.6, "bounty": 1.0, "publisher_id": "p",
            "deadline": "2099-01-01T00:00:00Z", "acceptance_criteria": ["x"],
        }, headers={"X-PAYMENT": "test"})
    task_id = resp.json()["id"]
    resp = c.get(f"/tasks/{task_id}/settlement")
    assert resp.status_code == 404


def test_settlement_fastest_first_closed(client_with_db):
    c, db = client_with_db
    worker = User(id="fw1", nickname="FastWorker", wallet="0xFW", role=UserRole.worker, trust_tier=TrustTier.A)
    db.add(worker)
    task = Task(
        id="ft1", title="Fast", description="fast task", type=TaskType.fastest_first,
        status=TaskStatus.closed, bounty=5.0, publisher_id="fp",
        winner_submission_id="fs1", payout_amount=4.0, payout_status=PayoutStatus.paid,
        payout_tx_hash="0xFAST",
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc),
        acceptance_criteria='["test"]',
    )
    sub = Submission(id="fs1", task_id="ft1", worker_id="fw1", content="done", status=SubmissionStatus.scored, score=0.9)
    db.add_all([task, sub])
    db.commit()

    resp = c.get("/tasks/ft1/settlement")
    assert resp.status_code == 200
    data = resp.json()

    assert data["escrow_total"] == 5.0
    assert data["summary"]["winner_payout"] == 4.0
    assert data["summary"]["winner_nickname"] == "FastWorker"
    assert data["summary"]["platform_fee"] == 1.0
    assert data["resolve_tx_hash"] == "0xFAST"


def test_settlement_quality_first_with_challenges(client_with_db):
    c, db = client_with_db
    _seed_quality_first_settled(db)

    resp = c.get("/tasks/t1/settlement")
    assert resp.status_code == 200
    data = resp.json()

    # Sources: bounty(9.5) + incentive(0.5) + 2 deposits(1.0 each)
    assert data["escrow_total"] == 12.0
    assert len(data["sources"]) == 4

    # Winner payout is stored as 9.2
    assert data["summary"]["winner_payout"] == 9.2
    assert data["summary"]["winner_nickname"] == "Charlie"

    # Upheld deposit refunded
    assert data["summary"]["deposits_refunded"] == 1.0
    assert data["summary"]["deposits_forfeited"] == 1.0

    # Arbiter reward: losing_deposits(1.0)*0.30 + upheld_deposit(1.0)*0.30 = 0.6
    assert data["summary"]["arbiter_reward_total"] == 0.6

    # Platform fee = 12.0 - 9.2 - 1.0 - 0.6 = 1.2
    assert data["summary"]["platform_fee"] == 1.2

    # resolve_tx_hash
    assert data["resolve_tx_hash"] == "0xRESOLVE"
