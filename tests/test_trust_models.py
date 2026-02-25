from app.models import (
    TrustTier, TrustEventType, StakePurpose, ChallengeVerdict,
    User, TrustEvent, ArbiterVote, StakeRecord,
)
from app.database import Base, engine, SessionLocal


def test_trust_tier_enum():
    assert TrustTier.S.value == "S"
    assert TrustTier.A.value == "A"
    assert TrustTier.B.value == "B"
    assert TrustTier.C.value == "C"


def test_trust_event_type_enum():
    assert TrustEventType.worker_won.value == "worker_won"
    assert TrustEventType.challenger_won.value == "challenger_won"
    assert TrustEventType.arbiter_majority.value == "arbiter_majority"
    assert TrustEventType.stake_slash.value == "stake_slash"


def test_stake_purpose_enum():
    assert StakePurpose.arbiter_deposit.value == "arbiter_deposit"
    assert StakePurpose.credit_recharge.value == "credit_recharge"


def test_user_model_trust_fields(client):
    """User model has trust-related fields with correct defaults."""
    from app.database import SessionLocal
    override_fn = next(iter(client.app.dependency_overrides.values()))
    db = next(override_fn())
    user = User(
        nickname="trust-test",
        wallet="0xTEST",
        role="worker",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.trust_score == 500.0
    assert user.trust_tier == TrustTier.A
    assert user.github_id is None
    assert user.github_bonus_claimed is False
    assert user.consolation_total == 0.0
    assert user.is_arbiter is False
    assert user.staked_amount == 0.0
    assert user.stake_bonus == 0.0


def test_trust_event_model(client):
    """TrustEvent stores reputation change events with full context."""
    override_fn = next(iter(client.app.dependency_overrides.values()))
    db = next(override_fn())
    user = User(nickname="evt-user", wallet="0x1", role="worker")
    db.add(user)
    db.commit()
    event = TrustEvent(
        user_id=user.id,
        event_type=TrustEventType.worker_won,
        task_id="task-123",
        amount=90.0,
        delta=10.0,
        score_before=500.0,
        score_after=510.0,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    assert event.id is not None
    assert event.delta == 10.0
    assert event.task_id == "task-123"
    assert event.amount == 90.0
    assert event.score_before == 500.0
    assert event.score_after == 510.0
    assert event.event_type == TrustEventType.worker_won
    assert event.created_at is not None


def test_arbiter_vote_model(client):
    """ArbiterVote records individual arbiter verdicts for a challenge."""
    override_fn = next(iter(client.app.dependency_overrides.values()))
    db = next(override_fn())
    vote = ArbiterVote(
        challenge_id="ch-1",
        arbiter_user_id="user-1",
        vote="upheld",
        feedback="The challenger's submission is clearly better.",
    )
    db.add(vote)
    db.commit()
    db.refresh(vote)
    assert vote.id is not None
    assert vote.is_majority is None
    assert vote.reward_amount is None
    assert vote.feedback == "The challenger's submission is clearly better."
    assert vote.challenge_id == "ch-1"
    assert vote.arbiter_user_id == "user-1"
    assert vote.created_at is not None


def test_stake_record_model(client):
    """StakeRecord tracks user stake deposits and slashing."""
    override_fn = next(iter(client.app.dependency_overrides.values()))
    db = next(override_fn())
    record = StakeRecord(
        user_id="user-1",
        amount=100.0,
        purpose=StakePurpose.arbiter_deposit,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    assert record.slashed is False
    assert record.tx_hash is None
    assert record.amount == 100.0
    assert record.purpose == StakePurpose.arbiter_deposit
    assert record.created_at is not None
