from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, TrustEvent, ArbiterVote, Challenge, ChallengeVerdict
from app.schemas import TrustProfile, TrustQuote, TrustEventOut, ArbiterVoteOut
from app.services.trust import (
    get_challenge_deposit_rate, get_platform_fee_rate, check_permissions,
)

router = APIRouter()


@router.get("/users/{user_id}/trust", response_model=TrustProfile)
def get_trust_profile(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    perms = check_permissions(user)

    try:
        deposit_rate = get_challenge_deposit_rate(user.trust_tier)
    except ValueError:
        deposit_rate = 0.0
    try:
        fee_rate = get_platform_fee_rate(user.trust_tier)
    except ValueError:
        fee_rate = 0.0

    return TrustProfile(
        trust_score=user.trust_score,
        trust_tier=user.trust_tier,
        challenge_deposit_rate=deposit_rate,
        platform_fee_rate=fee_rate,
        can_accept_tasks=perms["can_accept_tasks"],
        can_challenge=perms["can_challenge"],
        max_task_amount=perms["max_task_amount"],
        is_arbiter=user.is_arbiter,
        github_bound=user.github_id is not None,
        staked_amount=user.staked_amount,
        stake_bonus=user.stake_bonus,
        consolation_total=user.consolation_total,
    )


@router.get("/trust/quote", response_model=TrustQuote)
def trust_quote(
    user_id: str = Query(...),
    bounty: float = Query(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    try:
        deposit_rate = get_challenge_deposit_rate(user.trust_tier)
        fee_rate = get_platform_fee_rate(user.trust_tier)
    except ValueError:
        raise HTTPException(403, "User tier does not allow this action")

    return TrustQuote(
        trust_tier=user.trust_tier,
        challenge_deposit_rate=deposit_rate,
        challenge_deposit_amount=bounty * deposit_rate,
        platform_fee_rate=fee_rate,
        service_fee=0.01,
    )


@router.get("/users/{user_id}/trust/events", response_model=list[TrustEventOut])
def get_trust_events(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    events = (
        db.query(TrustEvent)
        .filter_by(user_id=user_id)
        .order_by(TrustEvent.created_at.desc())
        .limit(100)
        .all()
    )
    return events


@router.get("/challenges/{challenge_id}/votes", response_model=list[ArbiterVoteOut])
def get_challenge_votes(
    challenge_id: str,
    viewer_id: str = Query(default=None),
    db: Session = Depends(get_db),
):
    challenge = db.query(Challenge).filter_by(id=challenge_id).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found")
    votes = db.query(ArbiterVote).filter_by(challenge_id=challenge_id).all()

    # Hide other arbiters' votes while challenge is pending and not all voted
    all_voted = all(v.vote is not None for v in votes)
    if challenge.status.value == "pending" and not all_voted:
        result = []
        for v in votes:
            if v.arbiter_user_id == viewer_id:
                result.append(v)
            else:
                result.append(ArbiterVoteOut(
                    id=v.id,
                    challenge_id=v.challenge_id,
                    arbiter_user_id=v.arbiter_user_id,
                    vote=None,
                    feedback=None,
                    is_majority=None,
                    reward_amount=None,
                    created_at=v.created_at,
                ))
        return result

    return votes


@router.post("/challenges/{challenge_id}/vote", response_model=ArbiterVoteOut)
def submit_arbiter_vote(
    challenge_id: str,
    body: dict,
    db: Session = Depends(get_db),
):
    arbiter_user_id = body.get("arbiter_user_id")
    verdict_str = body.get("verdict")
    feedback = body.get("feedback")

    if not feedback:
        raise HTTPException(400, "Feedback is required")

    vote = (
        db.query(ArbiterVote)
        .filter_by(challenge_id=challenge_id, arbiter_user_id=arbiter_user_id)
        .first()
    )
    if not vote:
        raise HTTPException(404, "Vote record not found for this arbiter")
    if vote.vote is not None:
        raise HTTPException(400, "Already voted")

    vote.vote = ChallengeVerdict(verdict_str)
    vote.feedback = feedback
    db.commit()
    db.refresh(vote)
    return vote


@router.get("/leaderboard/weekly")
def weekly_leaderboard(db: Session = Depends(get_db)):
    """Return this week's leaderboard: workers ranked by total payout from closed tasks."""
    from datetime import timedelta
    from app.models import Task, Submission, TaskStatus

    now = datetime.now(timezone.utc)
    # Start of current week (Monday 00:00 UTC)
    monday = now - timedelta(days=now.weekday(), hours=now.hour, minutes=now.minute, seconds=now.second, microseconds=now.microsecond)

    # Find all closed tasks from this week with winners
    closed_tasks = (
        db.query(Task)
        .filter(
            Task.status == TaskStatus.closed,
            Task.created_at >= monday,
            Task.winner_submission_id.isnot(None),
        )
        .all()
    )

    # Aggregate earnings per worker
    worker_earnings: dict[str, float] = {}
    for task in closed_tasks:
        winner_sub = (
            db.query(Submission)
            .filter_by(id=task.winner_submission_id)
            .first()
        )
        if winner_sub:
            worker_earnings[winner_sub.worker_id] = (
                worker_earnings.get(winner_sub.worker_id, 0.0)
                + (task.payout_amount or task.bounty * 0.8)
            )

    # Sort by earnings, take top 100
    sorted_workers = sorted(worker_earnings.items(), key=lambda x: x[1], reverse=True)[:100]

    result = []
    for rank, (worker_id, total_earned) in enumerate(sorted_workers, start=1):
        user = db.query(User).filter_by(id=worker_id).first()
        if user:
            result.append({
                "user_id": user.id,
                "nickname": user.nickname,
                "total_earned": round(total_earned, 2),
                "trust_score": user.trust_score,
                "trust_tier": user.trust_tier,
                "rank": rank,
            })

    return result
