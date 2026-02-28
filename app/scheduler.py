from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from .database import SessionLocal
from .models import (
    Task, Submission, Challenge, ArbiterVote, JuryBallot,
    TaskType, TaskStatus, SubmissionStatus, ChallengeStatus,
)
from .services.arbiter import run_arbitration
from .services.arbiter_pool import (
    select_jury, resolve_jury, check_jury_ready,
    resolve_merged_jury, check_merged_jury_ready,
)
from .services.oracle import batch_score_submissions
from .services.escrow import create_challenge_onchain, resolve_challenge_onchain, void_challenge_onchain
from .services.payout import refund_publisher


def _resolve_via_contract(
    db: Session, task: Task,
    refunds: list[dict],
    arbiter_wallets: list[str],
    arbiter_reward: float,
    is_challenger_win: bool = False,
) -> None:
    """Call resolveChallenge on-chain with unified pool distribution."""
    from .models import User, PayoutStatus
    from .services.trust import get_winner_payout_rate
    try:
        winner_sub = db.query(Submission).filter(
            Submission.id == task.winner_submission_id
        ).first()
        winner_user = db.query(User).filter(
            User.id == winner_sub.worker_id
        ).first() if winner_sub else None
        if winner_user:
            try:
                rate = get_winner_payout_rate(winner_user.trust_tier,
                                              is_challenger_win=is_challenger_win)
            except ValueError:
                rate = 0.80
            payout_amount = round(task.bounty * rate, 6)
            if is_challenger_win:
                # Add incentive remainder: incentive - arbiter subsidy from incentive
                incentive = round(task.bounty * 0.05, 6)
                # Find upheld challenge to get deposit amount
                upheld_c = db.query(Challenge).filter(
                    Challenge.task_id == task.id,
                    Challenge.verdict == "upheld",
                ).first()
                upheld_deposit = (upheld_c.deposit_amount or 0) if upheld_c else 0
                arbiter_from_incentive = round(upheld_deposit * 0.30, 6)
                incentive_remainder = round(incentive - arbiter_from_incentive, 6)
                payout_amount = round(payout_amount + max(incentive_remainder, 0), 6)
            tx_hash = resolve_challenge_onchain(
                task.id, winner_user.wallet, payout_amount,
                refunds, arbiter_wallets, arbiter_reward,
            )
            task.payout_status = PayoutStatus.paid
            task.payout_tx_hash = tx_hash
            task.payout_amount = payout_amount
    except Exception as e:
        task.payout_status = PayoutStatus.failed
        print(f"[scheduler] resolveChallenge failed for {task.id}: {e}", flush=True)


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
    """Set challenge verdict and status. Arbiter trust is deferred to Task-level coherence."""
    from .models import ChallengeStatus as CS
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

        # Phase 1: open -> scoring (deadline expired, transition only)
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
                refund_publisher(db, task.id, rate=1.0)
            else:
                task.status = TaskStatus.scoring
        if expired_open:
            db.commit()

        # Phase 2: scoring -> challenge_window
        # Wait for all oracle background tasks to finish, then batch_score once.
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
                # V2 mode: if some submissions already went through gate check,
                # remaining pending ones are still being processed — wait.
                has_gated = db.query(Submission).filter(
                    Submission.task_id == task.id,
                    Submission.status.in_([
                        SubmissionStatus.gate_passed,
                        SubmissionStatus.gate_failed,
                    ]),
                ).count() > 0
                if has_gated:
                    continue

            # All oracle processing done (or V1 mode). Batch score if needed.
            unscored_count = db.query(Submission).filter(
                Submission.task_id == task.id,
                Submission.status.in_([
                    SubmissionStatus.pending,
                    SubmissionStatus.gate_passed,
                ]),
            ).count()
            if unscored_count > 0:
                try:
                    batch_score_submissions(db, task.id)
                except Exception as e:
                    print(f"[scheduler] batch_score error for {task.id}: {e}", flush=True)
                continue  # Re-check next tick

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

                # Lock 95% bounty into escrow contract at start of challenge window
                try:
                    from .models import User
                    winner_sub = db.query(Submission).filter(
                        Submission.id == best.id
                    ).first()
                    winner_user = db.query(User).filter(
                        User.id == winner_sub.worker_id
                    ).first() if winner_sub else None
                    if winner_user:
                        escrow_amount = round(task.bounty * 0.95, 6)
                        incentive = round(task.bounty * 0.05, 6)
                        tx_hash = create_challenge_onchain(
                            task.id, winner_user.wallet, escrow_amount, incentive
                        )
                        task.escrow_tx_hash = tx_hash
                except Exception as e:
                    print(f"[scheduler] createChallenge failed for {task.id}: {e}", flush=True)
                    # Revert: do NOT enter challenge_window if escrow lock failed
                    task.winner_submission_id = None
                    task.challenge_window_end = None
                    task.status = TaskStatus.scoring
                    continue
            else:
                # No qualifying submissions → 95% refund if there were submissions, close
                task.status = TaskStatus.closed
                has_subs = db.query(Submission).filter(
                    Submission.task_id == task.id
                ).count() > 0
                if has_subs:
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
                task.status = TaskStatus.closed
                # Publisher trust reward for successful task completion
                from .services.trust import apply_event as _apply_event
                from .models import TrustEventType as _TET, User as _User
                if db.query(_User).filter_by(id=task.publisher_id).first():
                    _apply_event(db, task.publisher_id, _TET.publisher_completed,
                                 task_bounty=task.bounty, task_id=task.id)
                # Release bounty via contract (no challengers)
                _resolve_via_contract(db, task, refunds=[], arbiter_wallets=[],
                                      arbiter_reward=0)
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

        # Phase 4: arbitrating -> closed/voided (merged jury resolution)
        arbitrating_tasks = (
            db.query(Task)
            .filter(Task.id.in_(arbitrating_task_ids))
            .all()
        ) if arbitrating_task_ids else []
        for task in arbitrating_tasks:
            ballots = db.query(JuryBallot).filter_by(task_id=task.id).all()
            if not ballots:
                # Legacy path: per-challenge jury
                pending_challenges = db.query(Challenge).filter(
                    Challenge.task_id == task.id,
                    Challenge.status == ChallengeStatus.pending,
                ).all()
                for challenge in pending_challenges:
                    _try_resolve_challenge_jury(db, challenge, task, now)
                still_pending = db.query(Challenge).filter(
                    Challenge.task_id == task.id,
                    Challenge.status == ChallengeStatus.pending,
                ).count()
                if still_pending > 0:
                    continue
                _settle_after_arbitration(db, task)
                continue

            # Merged jury path
            all_voted = all(b.winner_submission_id is not None for b in ballots)
            first_created = min(b.created_at for b in ballots)
            if first_created.tzinfo is None:
                first_created = first_created.replace(tzinfo=timezone.utc)
            timed_out = (now - first_created) >= JURY_VOTING_TIMEOUT

            if not all_voted and not timed_out:
                continue

            # Handle timeouts for non-voters
            if timed_out and not all_voted:
                from .services.trust import apply_event as _te_apply
                from .models import TrustEventType as _TET
                for b in ballots:
                    if b.winner_submission_id is None:
                        _te_apply(db, b.arbiter_user_id, _TET.arbiter_timeout,
                                  task_id=task.id)

            _settle_after_arbitration(db, task)

    finally:
        if own_session:
            db.close()


def _apply_hawkish_trust(
    db: Session, task: Task,
    voted_ballots: list, is_deadlock: bool,
) -> None:
    """Apply two-dimensional hawkish trust matrix to arbiters.

    Dimension 1 (Main): Winner pick consensus
      - Majority (coherent): +2
      - Minority (incoherent): -15
      - Deadlock: 0 (no event)

    Dimension 2 (Secondary): Malicious detection accuracy
      - True Positive (correctly flagged): +5 per target
      - False Positive (wrongly flagged): -1 per target
      - False Negative (missed flagging): -10 per target
    """
    from .models import MaliciousTag
    from .services.trust import apply_event, TrustEventType

    # --- Main dimension: winner pick ---
    for b in voted_ballots:
        if is_deadlock:
            pass  # 0 points, no event
        elif b.coherence_status == "coherent":
            apply_event(db, b.arbiter_user_id, TrustEventType.arbiter_majority,
                        task_id=task.id)
        elif b.coherence_status == "incoherent":
            apply_event(db, b.arbiter_user_id, TrustEventType.arbiter_minority,
                        task_id=task.id)

    # --- Secondary dimension: malicious detection accuracy ---
    # Build consensus malicious set (target_submission_id with ≥2 tags)
    all_tags = db.query(MaliciousTag).filter_by(task_id=task.id).all()
    tag_counts: dict[str, int] = {}
    for t in all_tags:
        tag_counts[t.target_submission_id] = tag_counts.get(t.target_submission_id, 0) + 1
    consensus_malicious = {sid for sid, count in tag_counts.items() if count >= 2}

    # Per-arbiter TP/FP/FN
    for b in voted_ballots:
        arbiter_tags = {t.target_submission_id for t in all_tags
                        if t.arbiter_user_id == b.arbiter_user_id}

        tp = arbiter_tags & consensus_malicious       # Correctly flagged
        fp = arbiter_tags - consensus_malicious       # Wrongly flagged
        fn = consensus_malicious - arbiter_tags       # Missed flagging

        for _ in tp:
            apply_event(db, b.arbiter_user_id, TrustEventType.arbiter_tp_malicious,
                        task_id=task.id)
        for _ in fp:
            apply_event(db, b.arbiter_user_id, TrustEventType.arbiter_fp_malicious,
                        task_id=task.id)
        for _ in fn:
            apply_event(db, b.arbiter_user_id, TrustEventType.arbiter_fn_malicious,
                        task_id=task.id)


def _settle_after_arbitration(db: Session, task: Task) -> None:
    """Settle a task after all challenges are judged.

    Uses merged jury resolution (JuryBallot) if ballots exist,
    otherwise falls back to legacy per-challenge ArbiterVote path.
    """
    from .models import ChallengeVerdict, PayoutStatus, User, MaliciousTag
    from .services.trust import apply_event, TrustEventType, compute_coherence_delta

    # Check if merged jury ballots exist for this task
    ballots = db.query(JuryBallot).filter_by(task_id=task.id).all()

    if ballots:
        # --- Merged jury path ---
        result = resolve_merged_jury(db, task.id)

        if result["is_voided"]:
            # PW is malicious -> task voided
            pw_sub = db.query(Submission).filter_by(
                id=task.winner_submission_id
            ).first()
            if pw_sub:
                pw_worker = db.query(User).filter_by(id=pw_sub.worker_id).first()
                if pw_worker:
                    apply_event(db, pw_worker.id, TrustEventType.pw_malicious,
                                task_id=task.id)

            # Process challenger trust events based on verdicts set by resolve_merged_jury
            challenges = db.query(Challenge).filter(Challenge.task_id == task.id).all()
            for c in challenges:
                challenger_sub = db.query(Submission).filter_by(
                    id=c.challenger_submission_id
                ).first()
                worker = db.query(User).filter_by(
                    id=challenger_sub.worker_id
                ).first() if challenger_sub else None
                if worker:
                    if c.verdict == ChallengeVerdict.malicious:
                        apply_event(db, worker.id, TrustEventType.challenger_malicious,
                                    task_id=task.id)
                    else:
                        # Justified challenger (verdict=rejected in voided scenario)
                        apply_event(db, worker.id, TrustEventType.challenger_justified,
                                    task_id=task.id)

            # Publisher trust
            publisher = db.query(User).filter_by(id=task.publisher_id).first()
            if publisher:
                apply_event(db, task.publisher_id, TrustEventType.publisher_completed,
                            task_bounty=task.bounty, task_id=task.id)

            # On-chain voided settlement
            try:
                publisher_wallet = publisher.wallet if publisher else None
                publisher_refund = round(task.bounty * 0.95, 6) if publisher_wallet else 0
                refunds = []
                for c in challenges:
                    if c.challenger_wallet:
                        refunds.append({
                            "challenger": c.challenger_wallet,
                            "refund": c.verdict != ChallengeVerdict.malicious,
                        })
                # Arbiter wallets: all voted ballots
                voted_bs = [b for b in db.query(JuryBallot).filter_by(task_id=task.id).all()
                            if b.winner_submission_id is not None]
                arb_users = db.query(User).filter(
                    User.id.in_([b.arbiter_user_id for b in voted_bs])
                ).all() if voted_bs else []
                arb_wallets = [u.wallet for u in arb_users if u.wallet]
                arbiter_reward = round(task.bounty * 0.05, 6)

                if publisher_wallet:
                    tx_hash = void_challenge_onchain(
                        task.id, publisher_wallet, publisher_refund,
                        refunds, arb_wallets, arbiter_reward,
                    )
                    from .models import PayoutStatus
                    task.payout_status = PayoutStatus.refunded
                    task.payout_tx_hash = tx_hash
            except Exception as e:
                print(f"[scheduler] voidChallenge failed for {task.id}: {e}", flush=True)

            # Hawkish trust matrix for arbiters (voided path)
            voted_bs = [b for b in ballots if b.winner_submission_id is not None]
            _apply_hawkish_trust(db, task, voted_bs, is_deadlock=False)

            # task.status already set to voided by resolve_merged_jury
            db.commit()
            return

        # --- Non-voided merged path ---
        challenges = db.query(Challenge).filter(Challenge.task_id == task.id).all()

        # If an upheld challenger won, switch winner
        upheld = [c for c in challenges if c.verdict == ChallengeVerdict.upheld]
        is_challenger_win = len(upheld) > 0
        if is_challenger_win:
            task.winner_submission_id = upheld[0].challenger_submission_id

        # Process challenger trust events
        for c in challenges:
            challenger_sub = db.query(Submission).filter_by(
                id=c.challenger_submission_id
            ).first()
            worker = db.query(User).filter_by(
                id=challenger_sub.worker_id
            ).first() if challenger_sub else None

            if c.verdict == ChallengeVerdict.upheld:
                if worker:
                    apply_event(db, worker.id, TrustEventType.challenger_won,
                                task_bounty=task.bounty, task_id=task.id)
            elif c.verdict == ChallengeVerdict.malicious:
                if worker:
                    apply_event(db, worker.id, TrustEventType.challenger_malicious,
                                task_id=task.id)

        # Apply worker_won trust event to the final winner
        winner_sub = db.query(Submission).filter_by(
            id=task.winner_submission_id
        ).first() if task.winner_submission_id else None
        if winner_sub:
            apply_event(db, winner_sub.worker_id, TrustEventType.worker_won,
                        task_bounty=task.bounty, task_id=task.id)

        # Apply worker_consolation to non-winning submitters with scored submissions
        if task.winner_submission_id:
            consolation_subs = db.query(Submission).filter(
                Submission.task_id == task.id,
                Submission.id != task.winner_submission_id,
                Submission.score.isnot(None),
            ).all()
            malicious_ids = {
                c.challenger_submission_id for c in challenges
                if c.verdict == ChallengeVerdict.malicious
            }
            for sub in consolation_subs:
                if sub.id not in malicious_ids:
                    apply_event(db, sub.worker_id, TrustEventType.worker_consolation,
                                task_id=task.id)

        task.status = TaskStatus.closed

        # Publisher trust reward
        if db.query(User).filter_by(id=task.publisher_id).first():
            apply_event(db, task.publisher_id, TrustEventType.publisher_completed,
                        task_bounty=task.bounty, task_id=task.id)

        # --- Unified pool financial settlement ---
        voted_ballots = [b for b in ballots if b.winner_submission_id is not None]
        is_deadlock = result.get("is_deadlock", False)

        # Select arbiter wallets (majority or all if deadlock)
        if is_deadlock:
            arbiter_ids = [b.arbiter_user_id for b in voted_ballots]
        else:
            arbiter_ids = [b.arbiter_user_id for b in voted_ballots
                           if b.coherence_status == "coherent"]
        arbiter_users = db.query(User).filter(User.id.in_(arbiter_ids)).all() if arbiter_ids else []
        arbiter_wallets = [u.wallet for u in arbiter_users if u.wallet]

        # Build refunds: upheld → refund deposit, others → forfeit
        refunds = []
        for c in challenges:
            if c.challenger_wallet:
                refunds.append({
                    "challenger": c.challenger_wallet,
                    "refund": c.verdict == ChallengeVerdict.upheld,
                })

        # Calculate arbiter reward from unified pool
        losing_deposits = sum(
            (c.deposit_amount or 0) for c in challenges
            if c.verdict != ChallengeVerdict.upheld and c.challenger_wallet
        )
        arbiter_from_pool = round(losing_deposits * 0.30, 6)
        if is_challenger_win:
            upheld_deposit = upheld[0].deposit_amount or 0
            arbiter_from_incentive = round(upheld_deposit * 0.30, 6)
        else:
            arbiter_from_incentive = 0
        arbiter_reward = round(arbiter_from_pool + arbiter_from_incentive, 6)

        _resolve_via_contract(db, task, refunds, arbiter_wallets,
                              arbiter_reward, is_challenger_win)

        # --- Hawkish trust matrix for arbiters ---
        _apply_hawkish_trust(db, task, voted_ballots, is_deadlock)

        db.commit()
        return

    # --- Legacy per-challenge ArbiterVote path ---
    challenges = db.query(Challenge).filter(Challenge.task_id == task.id).all()

    # Process trust events for challengers
    for c in challenges:
        challenger_sub = db.query(Submission).filter(
            Submission.id == c.challenger_submission_id
        ).first()
        worker = db.query(User).filter(
            User.id == challenger_sub.worker_id
        ).first() if challenger_sub else None

        if c.verdict == ChallengeVerdict.upheld:
            if worker:
                apply_event(db, worker.id, TrustEventType.challenger_won,
                            task_bounty=task.bounty, task_id=task.id)

        elif c.verdict == ChallengeVerdict.malicious:
            if worker:
                apply_event(db, worker.id, TrustEventType.challenger_malicious,
                            task_id=task.id)

    # Determine final winner
    upheld = [c for c in challenges if c.verdict == ChallengeVerdict.upheld]
    if upheld:
        best = max(upheld, key=lambda c: c.arbiter_score or 0)
        task.winner_submission_id = best.challenger_submission_id

    # Apply worker_won trust event to the final winner
    winner_sub = db.query(Submission).filter(
        Submission.id == task.winner_submission_id
    ).first() if task.winner_submission_id else None
    if winner_sub:
        apply_event(db, winner_sub.worker_id, TrustEventType.worker_won,
                    task_bounty=task.bounty, task_id=task.id)

    # Apply worker_consolation to non-winning submitters with scored submissions
    if task.winner_submission_id:
        consolation_subs = db.query(Submission).filter(
            Submission.task_id == task.id,
            Submission.id != task.winner_submission_id,
            Submission.score.isnot(None),
        ).all()
        for sub in consolation_subs:
            malicious_ids = {
                c.challenger_submission_id for c in challenges
                if c.verdict == ChallengeVerdict.malicious
            }
            if sub.id not in malicious_ids:
                apply_event(db, sub.worker_id, TrustEventType.worker_consolation,
                            task_id=task.id)

    task.status = TaskStatus.closed

    # Publisher trust reward for successful task completion
    if db.query(User).filter_by(id=task.publisher_id).first():
        apply_event(db, task.publisher_id, TrustEventType.publisher_completed,
                    task_bounty=task.bounty, task_id=task.id)

    # Resolve on-chain: unified pool distribution (legacy path adapted)
    is_challenger_win = len(upheld) > 0
    refunds = []
    for c in challenges:
        if c.challenger_wallet:
            refunds.append({
                "challenger": c.challenger_wallet,
                "refund": c.verdict == ChallengeVerdict.upheld,
            })

    # Collect arbiter wallets from per-challenge votes
    all_arbiter_ids = set()
    for c in challenges:
        jury_votes = db.query(ArbiterVote).filter_by(challenge_id=c.id).all()
        is_dl = any(v.coherence_status == "neutral" for v in jury_votes)
        if is_dl:
            all_arbiter_ids.update(v.arbiter_user_id for v in jury_votes if v.vote is not None)
        else:
            all_arbiter_ids.update(v.arbiter_user_id for v in jury_votes
                                   if v.coherence_status == "coherent")
    arbiter_users = db.query(User).filter(User.id.in_(list(all_arbiter_ids))).all() if all_arbiter_ids else []
    arbiter_wallets = [u.wallet for u in arbiter_users if u.wallet]

    # Calculate arbiter reward from pool
    losing_deps = sum(
        (c.deposit_amount or 0) for c in challenges
        if c.verdict != ChallengeVerdict.upheld and c.challenger_wallet
    )
    arb_from_pool = round(losing_deps * 0.30, 6)
    if is_challenger_win:
        upheld_dep = upheld[0].deposit_amount or 0 if upheld else 0
        arb_from_incentive = round(upheld_dep * 0.30, 6)
    else:
        arb_from_incentive = 0
    arbiter_reward = round(arb_from_pool + arb_from_incentive, 6)

    _resolve_via_contract(db, task, refunds, arbiter_wallets,
                          arbiter_reward, is_challenger_win)

    # Settle arbiter reputation via coherence rate
    all_votes = []
    for c in challenges:
        all_votes.extend(
            db.query(ArbiterVote).filter_by(challenge_id=c.id).all()
        )
    arbiter_groups: dict[str, list[ArbiterVote]] = {}
    for v in all_votes:
        arbiter_groups.setdefault(v.arbiter_user_id, []).append(v)

    for user_id, votes in arbiter_groups.items():
        effective = [v for v in votes
                     if v.coherence_status in ("coherent", "incoherent")]
        coherent_count = sum(1 for v in effective if v.coherence_status == "coherent")
        delta = compute_coherence_delta(coherent_count, len(effective))
        if delta is not None:
            apply_event(db, user_id, TrustEventType.arbiter_coherence,
                        task_id=task.id, coherence_delta=delta)

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
