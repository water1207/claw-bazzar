from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from .database import SessionLocal
from .models import (
    Task, Submission, Challenge,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus,
)
from .services.arbiter import run_arbitration
from .services.oracle import batch_score_submissions
from .services.escrow import create_challenge_onchain, resolve_challenge_onchain


def _resolve_via_contract(db: Session, task: Task, verdicts: list) -> None:
    """Call resolveChallenge on-chain to distribute bounty."""
    from .models import User, PayoutStatus
    try:
        winner_sub = db.query(Submission).filter(
            Submission.id == task.winner_submission_id
        ).first()
        winner_user = db.query(User).filter(
            User.id == winner_sub.worker_id
        ).first() if winner_sub else None
        if winner_user:
            payout_amount = round(task.bounty * 0.80, 6)
            tx_hash = resolve_challenge_onchain(
                task.id, winner_user.wallet, verdicts
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
            task.status = TaskStatus.scoring
        if expired_open:
            db.commit()
            for task in expired_open:
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

            best = (
                db.query(Submission)
                .filter(Submission.task_id == task.id, Submission.score.isnot(None))
                .order_by(Submission.score.desc())
                .first()
            )
            if best:
                task.winner_submission_id = best.id
                duration = task.challenge_duration or 7200
                task.challenge_window_end = now + timedelta(seconds=duration)
                task.status = TaskStatus.challenge_window

                # Lock bounty into escrow contract at start of challenge window
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
                            payout_amount = round(task.bounty * 0.80, 6)
                            deposit_amount = task.submission_deposit or round(task.bounty * 0.10, 6)
                            create_challenge_onchain(
                                task.id, winner_user.wallet, payout_amount, deposit_amount
                            )
                    except Exception as e:
                        print(f"[scheduler] createChallenge failed for {task.id}: {e}", flush=True)
            else:
                task.status = TaskStatus.closed
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
            ).count()
            if pending_challenges > 0:
                continue

            _settle_after_arbitration(db, task)

    finally:
        if own_session:
            db.close()


def _settle_after_arbitration(db: Session, task: Task) -> None:
    """Settle a task after all challenges are judged."""
    from .models import ChallengeVerdict, PayoutStatus, User
    challenges = db.query(Challenge).filter(Challenge.task_id == task.id).all()

    # Process deposits and credit scores
    for c in challenges:
        challenger_sub = db.query(Submission).filter(
            Submission.id == c.challenger_submission_id
        ).first()
        # Find the worker user for credit score updates
        worker = db.query(User).filter(
            User.id == challenger_sub.worker_id
        ).first() if challenger_sub else None

        if c.verdict == ChallengeVerdict.upheld:
            if challenger_sub and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = challenger_sub.deposit
            if worker:
                worker.credit_score = round(worker.credit_score + 5, 2)

        elif c.verdict == ChallengeVerdict.rejected:
            if challenger_sub and challenger_sub.deposit is not None and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = round(challenger_sub.deposit * 0.70, 6)
            # credit_score unchanged

        elif c.verdict == ChallengeVerdict.malicious:
            if challenger_sub and challenger_sub.deposit_returned is None:
                challenger_sub.deposit_returned = 0
            if worker:
                worker.credit_score = round(worker.credit_score - 20, 2)

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

    # Resolve on-chain: distribute bounty + deposits
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
        _resolve_via_contract(db, task, verdicts)

    db.commit()


def settle_expired_quality_first(db: Optional[Session] = None) -> None:
    """Legacy wrapper -- now calls quality_first_lifecycle."""
    quality_first_lifecycle(db=db)


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(quality_first_lifecycle, "interval", minutes=1)
    return scheduler
