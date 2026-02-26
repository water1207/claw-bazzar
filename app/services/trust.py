import math
from sqlalchemy.orm import Session
from app.models import User, TrustEvent, TrustTier, TrustEventType


def _multiplier(amount: float) -> float:
    """Logarithmic amount weighting: M = 1 + log10(1 + amount/10)."""
    return 1 + math.log10(1 + amount / 10)


def _compute_tier(score: float) -> TrustTier:
    if score >= 800:
        return TrustTier.S
    if score >= 500:
        return TrustTier.A
    if score >= 300:
        return TrustTier.B
    return TrustTier.C


_FIXED_DELTAS = {
    TrustEventType.worker_malicious: -100,
    TrustEventType.challenger_rejected: -3,
    TrustEventType.challenger_malicious: -100,
    TrustEventType.arbiter_majority: 2,
    TrustEventType.arbiter_minority: -15,
    TrustEventType.arbiter_timeout: -10,
    TrustEventType.github_bind: 50,
}

_WEIGHTED_BASES = {
    TrustEventType.worker_won: 5,
    TrustEventType.challenger_won: 10,
    TrustEventType.publisher_completed: 3,
}


def apply_event(
    db: Session,
    user_id: str,
    event_type: TrustEventType,
    task_bounty: float = 0.0,
    task_id: str | None = None,
    leaderboard_bonus: int = 0,
    stake_amount: float = 0.0,
) -> TrustEvent:
    """Apply a trust event to a user. Returns the TrustEvent record."""
    user = db.query(User).filter_by(id=user_id).one()
    score_before = user.trust_score

    if event_type in _WEIGHTED_BASES:
        m = _multiplier(task_bounty)
        delta = _WEIGHTED_BASES[event_type] * m
    elif event_type in _FIXED_DELTAS:
        delta = float(_FIXED_DELTAS[event_type])
    elif event_type == TrustEventType.worker_consolation:
        if user.consolation_total >= 50.0:
            delta = 0.0
        else:
            delta = 1.0
            user.consolation_total = min(user.consolation_total + 1.0, 50.0)
    elif event_type == TrustEventType.weekly_leaderboard:
        delta = float(leaderboard_bonus)
    elif event_type == TrustEventType.stake_bonus:
        potential = (stake_amount / 50.0) * 50.0
        remaining_cap = 100.0 - user.stake_bonus
        delta = min(potential, remaining_cap)
        if delta > 0:
            user.stake_bonus += delta
    elif event_type == TrustEventType.stake_slash:
        delta = -user.stake_bonus if user.stake_bonus > 0 else 0.0
        user.stake_bonus = 0.0
        user.staked_amount = 0.0
        user.is_arbiter = False
    else:
        delta = 0.0

    new_score = max(0.0, min(1000.0, score_before + delta))
    actual_delta = new_score - score_before

    user.trust_score = new_score
    user.trust_tier = _compute_tier(new_score)

    event = TrustEvent(
        user_id=user_id,
        event_type=event_type,
        task_id=task_id,
        amount=task_bounty,
        delta=actual_delta,
        score_before=score_before,
        score_after=new_score,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_challenge_deposit_rate(tier: TrustTier) -> float:
    rates = {TrustTier.S: 0.05, TrustTier.A: 0.10, TrustTier.B: 0.30}
    if tier == TrustTier.C:
        raise ValueError("C-level users cannot challenge")
    return rates[tier]


def get_platform_fee_rate(tier: TrustTier) -> float:
    rates = {TrustTier.S: 0.15, TrustTier.A: 0.20, TrustTier.B: 0.25}
    if tier == TrustTier.C:
        raise ValueError("C-level users are banned")
    return rates[tier]


def check_permissions(user: User) -> dict:
    """Return permission dict for the user based on trust tier."""
    tier = user.trust_tier
    if tier == TrustTier.C:
        return {
            "can_accept_tasks": False,
            "can_challenge": False,
            "max_task_amount": None,
        }
    result = {
        "can_accept_tasks": True,
        "can_challenge": True,
        "max_task_amount": None,
    }
    if tier == TrustTier.B:
        result["max_task_amount"] = 50.0
    return result
