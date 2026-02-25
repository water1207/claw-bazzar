from app.models import (
    TrustTier, TrustEventType, StakePurpose,
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
