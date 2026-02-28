from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    User, TrustEvent, ArbiterVote, Challenge, ChallengeVerdict,
    Task, Submission, StakeRecord, PayoutStatus,
)
from app.schemas import TrustProfile, TrustQuote, TrustEventOut, ArbiterVoteOut, BalanceEventOut, WeeklyLeaderboardEntry
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


@router.get("/users/{user_id}/balance-events", response_model=list[BalanceEventOut])
def get_balance_events(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    events: list[dict] = []

    # 1. Publisher: bounty paid
    pub_tasks = db.query(Task).filter(
        Task.publisher_id == user_id,
        Task.payment_tx_hash.isnot(None),
    ).all()
    for t in pub_tasks:
        events.append({
            "id": f"task_bounty:{t.id}",
            "event_type": "bounty_paid",
            "role": "publisher",
            "task_id": t.id,
            "task_title": t.title,
            "amount": t.bounty or 0,
            "direction": "outflow",
            "tx_hash": t.payment_tx_hash,
            "created_at": t.created_at,
        })

    # 2. Publisher: refund received
    refund_tasks = db.query(Task).filter(
        Task.publisher_id == user_id,
        Task.refund_tx_hash.isnot(None),
    ).all()
    for t in refund_tasks:
        events.append({
            "id": f"task_refund:{t.id}",
            "event_type": "refund_received",
            "role": "publisher",
            "task_id": t.id,
            "task_title": t.title,
            "amount": t.refund_amount or 0,
            "direction": "inflow",
            "tx_hash": t.refund_tx_hash,
            "created_at": t.created_at,
        })

    # 3. Worker: payout received
    winner_subs = db.query(Submission).filter(
        Submission.worker_id == user_id,
    ).all()
    winner_sub_ids = [s.id for s in winner_subs]
    if winner_sub_ids:
        payout_tasks = db.query(Task).filter(
            Task.winner_submission_id.in_(winner_sub_ids),
            Task.payout_status == PayoutStatus.paid,
        ).all()
        for t in payout_tasks:
            events.append({
                "id": f"task_payout:{t.id}",
                "event_type": "payout_received",
                "role": "worker",
                "task_id": t.id,
                "task_title": t.title,
                "amount": t.payout_amount or 0,
                "direction": "inflow",
                "tx_hash": t.payout_tx_hash,
                "created_at": t.created_at,
            })

    # 4. Challenger: deposit paid (on-chain via joinChallenge)
    challenger_subs = db.query(Submission).filter(
        Submission.worker_id == user_id,
    ).all()
    challenger_sub_ids = [s.id for s in challenger_subs]
    if challenger_sub_ids:
        deposit_challenges = db.query(Challenge).filter(
            Challenge.challenger_submission_id.in_(challenger_sub_ids),
            Challenge.deposit_tx_hash.isnot(None),
        ).all()
        for c in deposit_challenges:
            task = db.query(Task).filter_by(id=c.task_id).first()
            events.append({
                "id": f"challenge_deposit:{c.id}",
                "event_type": "challenge_deposit_paid",
                "role": "worker",
                "task_id": c.task_id,
                "task_title": task.title if task else None,
                "amount": c.deposit_amount or task.submission_deposit or round((task.bounty or 0) * 0.10, 6),
                "direction": "outflow",
                "tx_hash": c.deposit_tx_hash,
                "created_at": c.created_at,
            })

    # 6. Arbiter: reward
    arbiter_votes = db.query(ArbiterVote).filter(
        ArbiterVote.arbiter_user_id == user_id,
        ArbiterVote.reward_amount.isnot(None),
    ).all()
    for v in arbiter_votes:
        challenge = db.query(Challenge).filter_by(id=v.challenge_id).first()
        task = db.query(Task).filter_by(id=challenge.task_id).first() if challenge else None
        events.append({
            "id": f"vote_reward:{v.id}",
            "event_type": "arbiter_reward",
            "role": "arbiter",
            "task_id": challenge.task_id if challenge else None,
            "task_title": task.title if task else None,
            "amount": v.reward_amount,
            "direction": "inflow",
            "tx_hash": None,
            "created_at": v.created_at,
        })

    # 7. Staking: deposits and slashes
    stake_records = db.query(StakeRecord).filter(
        StakeRecord.user_id == user_id,
    ).all()
    for r in stake_records:
        events.append({
            "id": f"stake:{ r.id}",
            "event_type": "stake_slashed" if r.slashed else "stake_deposited",
            "role": "worker",
            "task_id": None,
            "task_title": None,
            "amount": r.amount,
            "direction": "outflow",
            "tx_hash": r.tx_hash,
            "created_at": r.created_at,
        })

    events.sort(key=lambda e: e["created_at"], reverse=True)
    return events[:100]


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


@router.get("/leaderboard/weekly", response_model=list[WeeklyLeaderboardEntry])
def weekly_leaderboard(db: Session = Depends(get_db)):
    """Return this week's leaderboard: workers ranked by total payout from closed tasks."""
    from datetime import timedelta
    from sqlalchemy import func
    from app.models import Task, Submission, TaskStatus

    now = datetime.now(timezone.utc)
    # Start of current week (Monday 00:00 UTC)
    monday = now - timedelta(
        days=now.weekday(), hours=now.hour, minutes=now.minute,
        seconds=now.second, microseconds=now.microsecond,
    )
    prev_monday = monday - timedelta(days=7)

    def _aggregate_earnings(start: datetime, end: datetime) -> dict[str, float]:
        """Aggregate worker earnings for closed tasks in a time range."""
        tasks = (
            db.query(Task)
            .filter(
                Task.status == TaskStatus.closed,
                Task.created_at >= start,
                Task.created_at < end,
                Task.winner_submission_id.isnot(None),
            )
            .all()
        )
        earnings: dict[str, float] = {}
        for task in tasks:
            sub = db.query(Submission).filter_by(id=task.winner_submission_id).first()
            if sub:
                earnings[sub.worker_id] = (
                    earnings.get(sub.worker_id, 0.0)
                    + (task.payout_amount or task.bounty * 0.8)
                )
        return earnings

    # Current week rankings
    current_earnings = _aggregate_earnings(monday, now)
    sorted_current = sorted(current_earnings.items(), key=lambda x: x[1], reverse=True)[:100]

    # Previous week rankings (for rank_change)
    prev_earnings = _aggregate_earnings(prev_monday, monday)
    sorted_prev = sorted(prev_earnings.items(), key=lambda x: x[1], reverse=True)[:100]
    prev_ranks = {wid: rank for rank, (wid, _) in enumerate(sorted_prev, start=1)}

    # Batch-fetch user info and stats for all current workers
    worker_ids = [wid for wid, _ in sorted_current]
    users_map: dict[str, User] = {}
    if worker_ids:
        users = db.query(User).filter(User.id.in_(worker_ids)).all()
        users_map = {u.id: u for u in users}

    # Batch stats: tasks_participated and tasks_won per worker
    participated_map: dict[str, int] = {}
    won_map: dict[str, int] = {}
    if worker_ids:
        participated_rows = (
            db.query(Submission.worker_id, func.count(func.distinct(Submission.task_id)))
            .filter(Submission.worker_id.in_(worker_ids))
            .group_by(Submission.worker_id)
            .all()
        )
        participated_map = {wid: cnt for wid, cnt in participated_rows}

        won_rows = (
            db.query(Submission.worker_id, func.count(Task.id))
            .join(Task, Task.winner_submission_id == Submission.id)
            .filter(Submission.worker_id.in_(worker_ids), Task.status == TaskStatus.closed)
            .group_by(Submission.worker_id)
            .all()
        )
        won_map = {wid: cnt for wid, cnt in won_rows}

    result = []
    for rank, (worker_id, total_earned) in enumerate(sorted_current, start=1):
        user = users_map.get(worker_id)
        if not user:
            continue
        prev_rank = prev_ranks.get(worker_id)
        rank_change = (prev_rank - rank) if prev_rank is not None else None
        tasks_participated = participated_map.get(worker_id, 0)
        tasks_won = won_map.get(worker_id, 0)
        win_rate = tasks_won / tasks_participated if tasks_participated > 0 else 0.0
        result.append(WeeklyLeaderboardEntry(
            rank=rank,
            rank_change=rank_change,
            user_id=user.id,
            nickname=user.nickname,
            wallet=user.wallet,
            github_id=user.github_id,
            total_earned=round(total_earned, 2),
            tasks_won=tasks_won,
            tasks_participated=tasks_participated,
            win_rate=round(win_rate, 4),
            trust_score=user.trust_score,
            trust_tier=user.trust_tier,
        ))

    return result
