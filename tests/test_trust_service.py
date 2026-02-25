# tests/test_trust_service.py
import math
import pytest
from unittest.mock import patch
from app.models import User, TrustEvent, TrustTier, TrustEventType, UserRole
from app.services.trust import (
    _multiplier, _compute_tier, apply_event,
    get_challenge_deposit_rate, get_platform_fee_rate,
    check_permissions,
)


def test_multiplier_zero():
    assert _multiplier(0) == 1.0


def test_multiplier_10():
    assert abs(_multiplier(10) - (1 + math.log10(2))) < 0.01


def test_multiplier_90():
    assert abs(_multiplier(90) - 2.0) < 0.01


def test_multiplier_990():
    assert abs(_multiplier(990) - 3.0) < 0.01


def test_compute_tier():
    assert _compute_tier(1000) == TrustTier.S
    assert _compute_tier(800) == TrustTier.S
    assert _compute_tier(799) == TrustTier.A
    assert _compute_tier(500) == TrustTier.A
    assert _compute_tier(499) == TrustTier.B
    assert _compute_tier(300) == TrustTier.B
    assert _compute_tier(299) == TrustTier.C
    assert _compute_tier(0) == TrustTier.C


def test_apply_event_worker_won(client):
    """Worker won with 90 USDC bounty: +5 * 2.0 = +10 points."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    user = User(nickname="w1", wallet="0x1", role=UserRole.worker)
    db.add(user)
    db.commit()

    event = apply_event(db, user.id, TrustEventType.worker_won, task_bounty=90.0)

    db.refresh(user)
    assert abs(event.delta - 10.0) < 0.1  # 5 * 2.0
    assert abs(user.trust_score - 510.0) < 0.1
    assert user.trust_tier == TrustTier.A


def test_apply_event_worker_consolation_cap(client):
    """Consolation is fixed +1, capped at 50 total."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    user = User(nickname="w2", wallet="0x2", role=UserRole.worker,
                consolation_total=49.0)
    db.add(user)
    db.commit()

    event1 = apply_event(db, user.id, TrustEventType.worker_consolation)
    assert event1.delta == 1.0

    event2 = apply_event(db, user.id, TrustEventType.worker_consolation)
    assert event2.delta == 0.0

    db.refresh(user)
    assert user.consolation_total == 50.0


def test_apply_event_worker_malicious(client):
    """Malicious submission: fixed -100."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    user = User(nickname="w3", wallet="0x3", role=UserRole.worker)
    db.add(user)
    db.commit()

    event = apply_event(db, user.id, TrustEventType.worker_malicious)
    assert event.delta == -100.0

    db.refresh(user)
    assert user.trust_score == 400.0
    assert user.trust_tier == TrustTier.B


def test_apply_event_challenger_won(client):
    """Challenge succeeded with 990 USDC: +10 * 3.0 = +30."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    user = User(nickname="c1", wallet="0x4", role=UserRole.worker)
    db.add(user)
    db.commit()

    event = apply_event(db, user.id, TrustEventType.challenger_won, task_bounty=990.0)
    assert abs(event.delta - 30.0) < 0.1

    db.refresh(user)
    assert abs(user.trust_score - 530.0) < 0.1


def test_apply_event_score_clamp(client):
    """Score never exceeds 1000 or drops below 0."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    user = User(nickname="clamp", wallet="0x5", role=UserRole.worker,
                trust_score=980.0, trust_tier=TrustTier.S)
    db.add(user)
    db.commit()

    event = apply_event(db, user.id, TrustEventType.challenger_won, task_bounty=990.0)
    db.refresh(user)
    assert user.trust_score == 1000.0

    user2 = User(nickname="clamp2", wallet="0x6", role=UserRole.worker,
                 trust_score=50.0, trust_tier=TrustTier.C)
    db.add(user2)
    db.commit()
    event2 = apply_event(db, user2.id, TrustEventType.worker_malicious)
    db.refresh(user2)
    assert user2.trust_score == 0.0


def test_apply_event_creates_trust_event(client):
    """Each apply_event writes a TrustEvent log record."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    user = User(nickname="log1", wallet="0x7", role=UserRole.worker)
    db.add(user)
    db.commit()

    apply_event(db, user.id, TrustEventType.github_bind)

    events = db.query(TrustEvent).filter_by(user_id=user.id).all()
    assert len(events) == 1
    assert events[0].event_type == TrustEventType.github_bind
    assert events[0].delta == 50.0
    assert events[0].score_before == 500.0
    assert events[0].score_after == 550.0


def test_get_challenge_deposit_rate():
    assert get_challenge_deposit_rate(TrustTier.S) == 0.05
    assert get_challenge_deposit_rate(TrustTier.A) == 0.10
    assert get_challenge_deposit_rate(TrustTier.B) == 0.30
    with pytest.raises(ValueError):
        get_challenge_deposit_rate(TrustTier.C)


def test_get_platform_fee_rate():
    assert get_platform_fee_rate(TrustTier.S) == 0.15
    assert get_platform_fee_rate(TrustTier.A) == 0.20
    assert get_platform_fee_rate(TrustTier.B) == 0.25
    with pytest.raises(ValueError):
        get_platform_fee_rate(TrustTier.C)


def test_check_permissions_c_level(client):
    """C-level users cannot accept tasks or challenge."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    user = User(nickname="banned", wallet="0x8", role=UserRole.worker,
                trust_score=100.0, trust_tier=TrustTier.C)
    db.add(user)
    db.commit()

    perms = check_permissions(user)
    assert perms["can_accept_tasks"] is False
    assert perms["can_challenge"] is False


def test_check_permissions_b_level(client):
    """B-level users have 50 USDC cap."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    user = User(nickname="warning", wallet="0x9", role=UserRole.worker,
                trust_score=400.0, trust_tier=TrustTier.B)
    db.add(user)
    db.commit()

    perms = check_permissions(user)
    assert perms["can_accept_tasks"] is True
    assert perms["can_challenge"] is True
    assert perms["max_task_amount"] == 50.0
