# tests/test_staking_service.py
import pytest
from unittest.mock import patch, MagicMock
from app.models import User, StakeRecord, TrustTier, StakePurpose, UserRole


def test_stake_for_arbiter_success(client):
    from app.services.staking import stake_for_arbiter

    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)
    user = User(
        nickname="arb-stake", wallet="0xARB", role=UserRole.worker,
        trust_score=850.0, trust_tier=TrustTier.S, github_id="gh-arb",
    )
    db.add(user)
    db.commit()

    with patch("app.services.staking.stake_onchain", return_value="0xtx"):
        record = stake_for_arbiter(db, user.id, deadline=0, v=0, r="0x0", s="0x0")

    db.refresh(user)
    assert user.staked_amount == 100.0
    assert user.is_arbiter is True
    assert record.purpose == StakePurpose.arbiter_deposit
    assert record.amount == 100.0
    assert record.tx_hash == "0xtx"


def test_stake_for_arbiter_not_s_tier(client):
    from app.services.staking import stake_for_arbiter

    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)
    user = User(
        nickname="low-stake", wallet="0xLOW", role=UserRole.worker,
        trust_score=500.0, trust_tier=TrustTier.A,
    )
    db.add(user)
    db.commit()

    with pytest.raises(ValueError, match="S-tier"):
        stake_for_arbiter(db, user.id, deadline=0, v=0, r="0x0", s="0x0")


def test_stake_for_arbiter_no_github(client):
    from app.services.staking import stake_for_arbiter

    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)
    user = User(
        nickname="no-gh", wallet="0xNOGH", role=UserRole.worker,
        trust_score=850.0, trust_tier=TrustTier.S,
    )
    db.add(user)
    db.commit()

    with pytest.raises(ValueError, match="GitHub"):
        stake_for_arbiter(db, user.id, deadline=0, v=0, r="0x0", s="0x0")


def test_stake_for_credit(client):
    from app.services.staking import stake_for_credit

    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)
    user = User(nickname="credit-stake", wallet="0xCRD", role=UserRole.worker)
    db.add(user)
    db.commit()

    with patch("app.services.staking.stake_onchain", return_value="0xtx2"):
        record = stake_for_credit(db, user.id, amount=50.0,
                                  deadline=0, v=0, r="0x0", s="0x0")

    db.refresh(user)
    assert user.staked_amount == 50.0
    assert user.stake_bonus == 50.0
    assert user.trust_score == 550.0  # 500 + 50
    assert record.purpose == StakePurpose.credit_recharge


def test_stake_for_credit_cap(client):
    from app.services.staking import stake_for_credit

    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)
    user = User(
        nickname="cap-stake", wallet="0xCAP", role=UserRole.worker,
        stake_bonus=80.0,
    )
    db.add(user)
    db.commit()

    with patch("app.services.staking.stake_onchain", return_value="0xtx3"):
        record = stake_for_credit(db, user.id, amount=50.0,
                                  deadline=0, v=0, r="0x0", s="0x0")

    db.refresh(user)
    # Only +20 remaining cap (100 - 80 = 20), but paid 50 USDC
    assert user.stake_bonus == 100.0
    assert user.staked_amount == 50.0


def test_check_and_slash(client):
    from app.services.staking import check_and_slash

    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)
    user = User(
        nickname="slash-me", wallet="0xSLASH", role=UserRole.worker,
        trust_score=250.0, trust_tier=TrustTier.C,
        staked_amount=100.0, stake_bonus=50.0, is_arbiter=True,
    )
    db.add(user)
    db.commit()

    with patch("app.services.staking.slash_onchain", return_value="0xslash"):
        slashed = check_and_slash(db, user.id)

    assert slashed is True
    db.refresh(user)
    assert user.staked_amount == 0.0
    assert user.stake_bonus == 0.0
    assert user.is_arbiter is False


def test_check_and_slash_no_stake(client):
    from app.services.staking import check_and_slash

    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)
    user = User(
        nickname="no-stake", wallet="0xNOS", role=UserRole.worker,
        trust_score=250.0, trust_tier=TrustTier.C,
    )
    db.add(user)
    db.commit()

    slashed = check_and_slash(db, user.id)
    assert slashed is False
