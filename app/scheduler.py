from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from .database import SessionLocal
from .models import (
    Task, Submission, Challenge, ArbiterVote,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus,
)
from .services.arbiter import run_arbitration
from .services.arbiter_pool import select_jury, resolve_jury, check_jury_ready
from .services.oracle import batch_score_submissions
from .services.escrow import create_challenge_onchain, resolve_challenge_onchain
from .services.payout import refund_publisher


def _resolve_via_contract(
    db: Session, task: Task, verdicts: list, arbiter_wallets: list[str] | None = None
) -> None:
    """Call resolveChallenge on-chain to distribute bounty + deposits."""
    from .models import User, PayoutStatus
    try:
        winner_sub = db.query(Submission).filter(
            Submission.id == task.winner_submission_id
        ).first()
        winner_user = db.query(User).filter(
            User.id == winner_sub.worker_id
        ).first() if winner_sub else None
        if winner_user:
            # Payout is 90% if challenger won, 80% if original winner kept
            has_upheld = any(v.get("result") == 0 for v in verdicts)
            payout_amount = round(task.bounty * 0.90, 6) if has_upheld else round(task.bounty * 0.80, 6)
            tx_hash = resolve_challenge_onchain(
                task.id, winner_user.wallet, verdicts, arbiter_wallets
            )
            task.payout_status = PayoutStatus.paid
            task.payout_tx_hash = tx_hash
            task.payout_amount = payout_amount
    except Exception as e:
        task.payout_status = PayoutStatus.failed
        print(f"[scheduler] resolveChallenge failed for {task.id}: {e}", flush=True)


def _refund_all_deposits(db: Session, task_id: str) -> None:
    """Refund all deposits for a task (no challenges scenario)."""
    submissions = db.query(Submission).filter(
        Submission.task_id == task_id,
        Submission.deposit.isnot(None),
    ).all()
    for sub in submissions:
        if sub.deposit_returned is None:
            sub.deposit_returned = sub.deposit


JURY_VOTING_TIMEOUT = timedelta(hours=6)


def _try_resolve_challenge_jury(
    db: Session, challenge: Challenge, task: Task, now: datetime
) -> None:
    """Check jury votes for a challenge; resolve if ready or timed out."""
    votes = db.query(ArbiterVote).filter_by(challenge_id=challenge.id).all()
    if not votes:
        # No jury was selected for this challenge (stub path) — skip
        return

    all_voted = check_jury_ready(db, challenge.id)
    # Determine timeout from the earliest vote created_at
    earliest = min(v.created_at for v in votes)
    # Ensure timezone-aware comparison (SQLite may strip tzinfo)
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)
    timed_out = (now - earliest) >= JURY_VOTING_TIMEOUT

    if not all_voted and not timed_out:
        return

    # Apply timeout penalty to non-voters
    if timed_out and not all_voted:
        from .services.trust import apply_event, TrustEventType
        for v in votes:
            if v.vote is None:
                apply_event(db, v.arbiter_user_id, TrustEventType.arbiter_timeout,
                            task_id=task.id)

    # Resolve jury vote
    from .models import ChallengeVerdict
    verdict = resolve_jury(db, challenge.id)
    _apply_verdict_trust(db, challenge, verdict, task)


def _apply_verdict_trust(
    db: Session, challenge: Challenge, verdict, task: Task
) -> None:
    """Apply trust score changes based on jury verdict."""
    from .services.trust import apply_event, TrustEventType
    from .models import ChallengeVerdict, ChallengeStatus as CS
    votes = db.query(ArbiterVote).filter_by(challenge_id=challenge.id).all()
    for v in votes:
        if v.vote is not None:
            if v.is_majority:
                apply_event(db, v.arbiter_user_id, TrustEventType.arbiter_majority,
                            task_id=task.id)
            else:
                apply_event(db, v.arbiter_user_id, TrustEventType.arbiter_minority,
                            task_id=task.id)
    challenge.verdict = verdict
    challenge.status = CS.judged
    db.commit()


def quality_first_lifecycle(db: Optional[Session] = None) -> None:
    """Push quality_first tasks through their 4-phase lifecycle."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # Snapshot IDs for each phase BEFORE any transitions, so tasks
        # don't cascade through multiple phases in a single tick.
        scoring_task_ids = [
            t.id for t in db.query(Task.id).filter(
                Task.type == TaskType.quality_first,
                Task.status == TaskStatus.scoring,
            ).all()
        ]
        challenge_window_task_ids = [
            t.id for t in db.query(Task.id).filter(
                Task.type == TaskType.quality_first,
                Task.status == TaskStatus.challenge_window,
                Task.challenge_window_end <= now,
            ).all()
        ]
        arbitrating_task_ids = [
            t.id for t in db.query(Task.id).filter(
                Task.type == TaskType.quality_first,
                Task.status == TaskStatus.arbitrating,
            ).all()
        ]

        # Phase 1: open -> scoring (deadline expired)
        expired_open = (
            db.query(Task)
            .filter(
                Task.type == TaskType.quality_first,
                Task.status == TaskStatus.open,
                Task.deadline <= now,
            )
            .all()
        )
        for task in expired_open:
            sub_count = db.query(Submission).filter(
                Submission.task_id == task.id
            ).count()
            if sub_count == 0:
                # No submissions → full refund, close immediately
                task.status = TaskStatus.closed
                if task.bounty and task.bounty > 0:
                    refund_publisher(db, task.id, rate=1.0)
            else:
                task.status = TaskStatus.scoring
        if expired_open:
            db.commit()
            for task in expired_open:
                if task.status == TaskStatus.scoring:
                    try:
                        batch_score_submissions(db, task.id)
                    except Exception as e:
                        print(f"[scheduler] batch_score error for {task.id}: {e}", flush=True)

        # Phase 2: scoring -> challenge_window (all submissions scored)
        scoring_tasks = (
            db.query(Task)
            .filter(Task.id.in_(scoring_task_ids))
            .all()
        ) if scoring_task_ids else []
        for task in scoring_tasks:
            pending_count = db.query(Submission).filter(
                Submission.task_id == task.id,
                Submission.status == SubmissionStatus.pending,
            ).count()
            if pending_count > 0:
                continue  # Still waiting for Oracle

            # Find best submission; apply threshold filter if set
            score_filter = [Submission.task_id == task.id, Submission.score.isnot(None)]
            if task.threshold is not None:
                score_filter.append(Submission.score >= task.threshold)
            best = (
                db.query(Submission)
                .filter(*score_filter)
                .order_by(Submission.score.desc())
                .first()
            )
            if best:
                task.winner_submission_id = best.id
                duration = task.challenge_duration or 7200
                task.challenge_window_end = now + timedelta(seconds=duration)
                task.status = TaskStatus.challenge_window

                # Lock 90% bounty into escrow contract at start of challenge window
                if task.bounty and task.bounty > 0:
                    try:
                        from .models import User
                        winner_sub = db.query(Submission).filter(
                            Submission.id == best.id
                        ).first()
                        winner_user = db.query(User).filter(
                            User.id == winner_sub.worker_id
                        ).first() if winner_sub else None
                        if winner_user:
                            escrow_amount = round(task.bounty * 0.90, 6)
                            incentive = round(task.bounty * 0.10, 6)
                            deposit_amount = task.submission_deposit or round(task.bounty * 0.10, 6)
                            create_challenge_onchain(
                                task.id, winner_user.wallet, escrow_amount, incentive, deposit_amount
                            )
                    except Exception as e:
                        print(f"[scheduler] createChallenge failed for {task.id}: {e}", flush=True)
            else:
                # No qualifying submissions → 95% refund if there were submissions, close
                task.status = TaskStatus.closed
                has_subs = db.query(Submission).filter(
                    Submission.task_id == task.id
                ).count() > 0
                if task.bounty and task.bounty > 0 and has_subs:
                    refund_publisher(db, task.id, rate=0.95)
        if scoring_tasks:
            db.commit()

        # Phase 3: challenge_window -> arbitrating or closed
        expired_window = (
            db.query(Task)
            .filter(Task.id.in_(challenge_window_task_ids))
            .all()
        ) if challenge_window_task_ids else []
        for task in expired_window:
            challenge_count = db.query(Challenge).filter(
                Challenge.task_id == task.id
            ).count()
            if challenge_count == 0:
                _refund_all_deposits(db, task.id)
                task.status = TaskStatus.closed
                # Release bounty via contract (no challengers, empty verdicts)
                if task.bounty and task.bounty > 0:
                    _resolve_via_contract(db, task, verdicts=[])
                db.commit()
            else:
                # Try jury-based arbitration first; fall back to stub
                jury_votes = select_jury(db, task.id)
                if jury_votes:
                    task.status = TaskStatus.arbitrating
                    db.commit()
                else:
                    task.status = TaskStatus.arbitrating
                    db.commit()
                    run_arbitration(db, task.id)

        # Phase 4: arbitrating -> closed (all challenges judged)
        arbitrating_tasks = (
            db.query(Task)
            .filter(Task.id.in_(arbitrating_task_ids))
            .all()
        ) if arbitrating_task_ids else []
        for task in arbitrating_tasks:
            pending_challenges = db.query(Challenge).filter(
                Challenge.task_id == task.id,
                Challenge.status == ChallengeStatus.pending,
            ).all()

            # Try to resolve pending challenges via jury voting
            for challenge in pending_challenges:
                _try_resolve_challenge_jury(db, challenge, task, now)

            # Re-check: if still pending challenges remain, wait
            still_pending = db.query(Challenge).filter(
                Challenge.task_id == task.id,
                Challenge.status == ChallengeStatus.pending,
            ).count()
            if still_pending > 0:
                continue

            _settle_after_arbitration(db, task)

    finally:
        if own_session:
            db.close()


def _settle_after_arbitration(db: Session, task: Task) -> None:
    """Settle a task after all challenges are judged."""
    from .models import ChallengeVerdict, PayoutStatus, User
    challenges = db.query(Challenge).filter(Challenge.task_id == task.id).all()

    # Process deposits (30% arbiter cut from ALL) and credit scores
    for c in challenges:
        challenger_sub = db.query(Submission).filter(
            Submission.id == c.challenger_submission_id
        ).first()
        worker = db.query(User).filter(
            User.id == challenger_sub.worker_id
        ).first() if challenger_sub else None

        if c.verdict == ChallengeVerdict.upheld:
            # 30% to arbiters, remaining 70% back to challenger
            if challenger_sub and challenger_sub.deposit is not None and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = round(challenger_sub.deposit * 0.70, 6)
            if worker:
                worker.trust_score = round(worker.trust_score + 5, 2)

        elif c.verdict == ChallengeVerdict.rejected:
            # 30% to arbiters, remaining 70% to platform — challenger gets nothing
            if challenger_sub and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = 0

        elif c.verdict == ChallengeVerdict.malicious:
            # 30% to arbiters, remaining 70% to platform — challenger gets nothing
            if challenger_sub and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = 0
            if worker:
                worker.trust_score = round(worker.trust_score - 20, 2)

    # Determine final winner
    upheld = [c for c in challenges if c.verdict == ChallengeVerdict.upheld]
    if upheld:
        best = max(upheld, key=lambda c: c.arbiter_score or 0)
        task.winner_submission_id = best.challenger_submission_id

    # Refund non-challenger deposits
    all_subs = db.query(Submission).filter(
        Submission.task_id == task.id,
        Submission.deposit.isnot(None),
        Submission.deposit_returned.is_(None),
    ).all()
    for sub in all_subs:
        sub.deposit_returned = sub.deposit

    task.status = TaskStatus.closed

    # Resolve on-chain: distribute bounty + deposits + arbiter rewards
    if task.bounty and task.bounty > 0:
        verdicts = []
        for c in challenges:
            if c.challenger_wallet:
                result_map = {
                    ChallengeVerdict.upheld: 0,
                    ChallengeVerdict.rejected: 1,
                    ChallengeVerdict.malicious: 2,
                }
                verdicts.append({
                    "challenger": c.challenger_wallet,
                    "result": result_map.get(c.verdict, 1),
                })
        # Collect arbiter wallets from jury votes; fall back to platform wallet
        from .models import User
        arbiter_user_ids = set()
        for c in challenges:
            jury_votes = db.query(ArbiterVote).filter_by(challenge_id=c.id).all()
            for v in jury_votes:
                if v.vote is not None:
                    arbiter_user_ids.add(v.arbiter_user_id)
        if arbiter_user_ids:
            arbiter_users = db.query(User).filter(User.id.in_(arbiter_user_ids)).all()
            arbiter_wallets = [u.wallet for u in arbiter_users if u.wallet]
        else:
            import os
            platform_wallet = os.environ.get("PLATFORM_WALLET", "")
            arbiter_wallets = [platform_wallet] if platform_wallet else []
        _resolve_via_contract(db, task, verdicts, arbiter_wallets)

    db.commit()


LEADERBOARD_TIERS = [
    (3, 30),    # Top 1-3: +30
    (10, 20),   # Top 4-10: +20
    (30, 15),   # Top 11-30: +15
    (100, 10),  # Top 31-100: +10
]


def run_weekly_leaderboard(db: Optional[Session] = None) -> None:
    """Weekly leaderboard: award trust points to top workers."""
    from sqlalchemy import func
    from app.models import User
    from app.services.trust import apply_event, TrustEventType

    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)

        results = (
            db.query(
                Submission.worker_id,
                func.sum(Task.payout_amount).label("total"),
            )
            .join(Task, Task.winner_submission_id == Submission.id)
            .filter(Task.status == TaskStatus.closed)
            .filter(Task.created_at >= week_ago)
            .filter(Task.payout_amount.isnot(None))
            .group_by(Submission.worker_id)
            .order_by(func.sum(Task.payout_amount).desc())
            .limit(100)
            .all()
        )

        rank = 0
        for worker_id, total in results:
            rank += 1
            bonus = 0
            for threshold, points in LEADERBOARD_TIERS:
                if rank <= threshold:
                    bonus = points
                    break
            if bonus > 0:
                apply_event(
                    db, worker_id, TrustEventType.weekly_leaderboard,
                    leaderboard_bonus=bonus,
                )
    finally:
        if own_session:
            db.close()


def fastest_first_refund(db: Optional[Session] = None) -> None:
    """Refund fastest_first tasks that expired without a winner."""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        expired = (
            db.query(Task)
            .filter(
                Task.type == TaskType.fastest_first,
                Task.status == TaskStatus.open,
                Task.deadline <= now,
            )
            .all()
        )
        for task in expired:
            sub_count = db.query(Submission).filter(
                Submission.task_id == task.id
            ).count()
            task.status = TaskStatus.closed
            if task.bounty and task.bounty > 0:
                if sub_count == 0:
                    refund_publisher(db, task.id, rate=1.0)
                else:
                    # Submissions exist but none passed threshold → 95% refund
                    refund_publisher(db, task.id, rate=0.95)
        if expired:
            db.commit()
    finally:
        if own_session:
            db.close()


def settle_expired_quality_first(db: Optional[Session] = None) -> None:
    """Legacy wrapper -- now calls quality_first_lifecycle."""
    quality_first_lifecycle(db=db)


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(quality_first_lifecycle, "interval", minutes=1)
    scheduler.add_job(fastest_first_refund, "interval", minutes=1)
    scheduler.add_job(
        run_weekly_leaderboard, "cron",
        day_of_week="sun", hour=0, minute=0,
        id="weekly_leaderboard",
    )
    return scheduler
