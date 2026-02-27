import random
from datetime import datetime, timezone
from collections import Counter
from sqlalchemy.orm import Session
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote, JuryBallot, MaliciousTag,
    ChallengeVerdict, ChallengeStatus, TaskStatus,
)

JURY_SIZE = 3


def select_jury(db: Session, task_id: str) -> list[JuryBallot]:
    """Select up to 3 arbiters for merged arbitration on a task.
    Creates one JuryBallot per arbiter (per-task, not per-challenge).
    """
    task = db.query(Task).filter_by(id=task_id).first()
    if not task:
        return []

    # Collect all participant user IDs to exclude
    exclude_ids = set()
    if task.publisher_id:
        exclude_ids.add(task.publisher_id)
    subs = db.query(Submission).filter_by(task_id=task_id).all()
    for s in subs:
        exclude_ids.add(s.worker_id)
    challenges = db.query(Challenge).filter_by(task_id=task_id).all()
    for c in challenges:
        challenger_sub = db.query(Submission).filter_by(id=c.challenger_submission_id).first()
        if challenger_sub:
            exclude_ids.add(challenger_sub.worker_id)

    # Select random eligible users
    candidates = db.query(User).filter(
        User.is_arbiter == True, User.id.notin_(exclude_ids)
    ).all()

    if not candidates:
        return []

    selected = random.sample(candidates, min(JURY_SIZE, len(candidates)))

    # Create one JuryBallot per arbiter (per-task)
    ballots = []
    for user in selected:
        ballot = JuryBallot(task_id=task_id, arbiter_user_id=user.id)
        db.add(ballot)
        ballots.append(ballot)
    db.commit()
    for b in ballots:
        db.refresh(b)
    return ballots


def submit_vote(
    db: Session, vote_id: str, verdict: ChallengeVerdict, feedback: str,
) -> ArbiterVote:
    """Arbiter submits their vote (legacy per-challenge path)."""
    vote = db.query(ArbiterVote).filter_by(id=vote_id).one()
    if vote.vote is not None:
        raise ValueError("Already voted")
    vote.vote = verdict
    vote.feedback = feedback
    db.commit()
    db.refresh(vote)
    return vote


def submit_merged_vote(
    db: Session,
    task_id: str,
    arbiter_user_id: str,
    winner_submission_id: str,
    malicious_submission_ids: list[str],
    feedback: str = "",
) -> JuryBallot:
    """Record an arbiter's merged vote: winner choice + malicious tags."""
    # Mutual exclusion check
    if winner_submission_id in malicious_submission_ids:
        raise ValueError("Winner cannot be tagged as malicious")

    ballot = db.query(JuryBallot).filter_by(
        task_id=task_id, arbiter_user_id=arbiter_user_id
    ).first()
    if not ballot:
        raise ValueError("No ballot found for this arbiter on this task")
    if ballot.winner_submission_id is not None:
        raise ValueError("Arbiter has already voted")

    ballot.winner_submission_id = winner_submission_id
    ballot.feedback = feedback
    ballot.voted_at = datetime.now(timezone.utc)

    # Create malicious tags
    for sub_id in malicious_submission_ids:
        tag = MaliciousTag(
            task_id=task_id,
            arbiter_user_id=arbiter_user_id,
            target_submission_id=sub_id,
        )
        db.add(tag)

    db.commit()
    db.refresh(ballot)
    return ballot


def check_merged_jury_ready(db: Session, task_id: str) -> bool:
    """Check if all jury ballots for a task have been submitted."""
    ballots = db.query(JuryBallot).filter_by(task_id=task_id).all()
    if not ballots:
        return False
    return all(b.winner_submission_id is not None for b in ballots)


def resolve_merged_jury(db: Session, task_id: str) -> dict:
    """
    Resolve merged arbitration for a task.
    Returns dict with: winner_submission_id, is_deadlock, is_voided.
    """
    task = db.query(Task).filter_by(id=task_id).first()
    ballots = db.query(JuryBallot).filter_by(task_id=task_id).all()
    voted_ballots = [b for b in ballots if b.winner_submission_id is not None]
    challenges = db.query(Challenge).filter_by(task_id=task_id).all()

    pw_submission_id = task.winner_submission_id

    # --- Step 1: Circuit breaker --- PW malicious check ---
    pw_malicious_count = db.query(MaliciousTag).filter_by(
        task_id=task_id, target_submission_id=pw_submission_id
    ).count()

    is_voided = pw_malicious_count >= 2

    if is_voided:
        task.status = TaskStatus.voided
        # Set per-challenge verdicts (malicious challengers still punished)
        for c in challenges:
            sub_id = c.challenger_submission_id
            mal_count = db.query(MaliciousTag).filter_by(
                task_id=task_id, target_submission_id=sub_id
            ).count()
            c.verdict = ChallengeVerdict.malicious if mal_count >= 2 else ChallengeVerdict.rejected
            c.status = ChallengeStatus.judged
        db.commit()
        return {
            "winner_submission_id": None,
            "is_deadlock": False,
            "is_voided": True,
        }

    # --- Step 2: Elect winner ---
    vote_counts = Counter(b.winner_submission_id for b in voted_ballots)
    winner = None
    is_deadlock = True
    for sub_id, cnt in vote_counts.most_common():
        if cnt >= 2:
            winner = sub_id
            is_deadlock = False
            break

    if winner is None:
        winner = pw_submission_id  # deadlock -> PW wins

    # --- Step 3: Set per-challenge verdicts ---
    for c in challenges:
        sub_id = c.challenger_submission_id
        mal_count = db.query(MaliciousTag).filter_by(
            task_id=task_id, target_submission_id=sub_id
        ).count()
        if sub_id == winner:
            c.verdict = ChallengeVerdict.upheld
        elif mal_count >= 2:
            c.verdict = ChallengeVerdict.malicious
        else:
            c.verdict = ChallengeVerdict.rejected
        c.status = ChallengeStatus.judged

    # --- Step 4: Arbiter coherence (winner dimension) ---
    if is_deadlock:
        for b in ballots:
            b.coherence_status = "neutral"
            b.is_majority = None
    else:
        for b in voted_ballots:
            if b.winner_submission_id == winner:
                b.coherence_status = "coherent"
                b.is_majority = True
            else:
                b.coherence_status = "incoherent"
                b.is_majority = False

    db.commit()
    return {
        "winner_submission_id": winner,
        "is_deadlock": is_deadlock,
        "is_voided": False,
    }


def resolve_jury(db: Session, challenge_id: str) -> ChallengeVerdict:
    """Resolve jury votes for a challenge (legacy per-challenge path).

    Sets coherence_status on each vote:
    - 2:1 or 3:0 -> majority="coherent", minority="incoherent"
    - 1:1:1 deadlock -> all="neutral", verdict defaults to rejected
    """
    votes = (
        db.query(ArbiterVote)
        .filter_by(challenge_id=challenge_id)
        .filter(ArbiterVote.vote.isnot(None))
        .all()
    )

    if not votes:
        return ChallengeVerdict.rejected

    counter = Counter(v.vote for v in votes)
    most_common = counter.most_common()

    if most_common[0][1] >= 2:
        majority_verdict = most_common[0][0]
        for vote in votes:
            vote.is_majority = (vote.vote == majority_verdict)
            vote.coherence_status = "coherent" if vote.is_majority else "incoherent"
    else:
        majority_verdict = ChallengeVerdict.rejected
        for vote in votes:
            vote.is_majority = None
            vote.coherence_status = "neutral"

    db.commit()
    return majority_verdict


def check_jury_ready(db: Session, challenge_id: str) -> bool:
    """Check if all jury members have voted for a challenge (legacy)."""
    votes = db.query(ArbiterVote).filter_by(challenge_id=challenge_id).all()
    if not votes:
        return False
    return all(v.vote is not None for v in votes)
