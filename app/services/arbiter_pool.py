import random
from collections import Counter
from sqlalchemy.orm import Session
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    ChallengeVerdict, ChallengeStatus,
)

JURY_SIZE = 3


def select_jury(db: Session, task_id: str) -> list[ArbiterVote]:
    """Select up to 3 random arbiters for a task, excluding participants."""
    task = db.query(Task).filter_by(id=task_id).one()

    exclude_ids = set()
    if task.publisher_id:
        exclude_ids.add(task.publisher_id)
    submissions = db.query(Submission).filter_by(task_id=task_id).all()
    for sub in submissions:
        exclude_ids.add(sub.worker_id)
    challenges = db.query(Challenge).filter_by(task_id=task_id).all()
    for ch in challenges:
        challenger_sub = db.query(Submission).filter_by(id=ch.challenger_submission_id).first()
        if challenger_sub:
            exclude_ids.add(challenger_sub.worker_id)

    eligible = (
        db.query(User)
        .filter(User.is_arbiter == True, ~User.id.in_(exclude_ids))
        .all()
    )

    if not eligible:
        return []

    selected = random.sample(eligible, min(JURY_SIZE, len(eligible)))

    votes = []
    for user in selected:
        for challenge in challenges:
            vote = ArbiterVote(
                challenge_id=challenge.id,
                arbiter_user_id=user.id,
            )
            db.add(vote)
            votes.append(vote)
    db.commit()
    for v in votes:
        db.refresh(v)
    return votes


def submit_vote(
    db: Session, vote_id: str, verdict: ChallengeVerdict, feedback: str,
) -> ArbiterVote:
    """Arbiter submits their vote."""
    vote = db.query(ArbiterVote).filter_by(id=vote_id).one()
    if vote.vote is not None:
        raise ValueError("Already voted")
    vote.vote = verdict
    vote.feedback = feedback
    db.commit()
    db.refresh(vote)
    return vote


def resolve_jury(db: Session, challenge_id: str) -> ChallengeVerdict:
    """Resolve jury votes for a challenge. Returns the majority verdict."""
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
    else:
        majority_verdict = ChallengeVerdict.rejected

    for vote in votes:
        vote.is_majority = (vote.vote == majority_verdict)

    db.commit()
    return majority_verdict


def check_jury_ready(db: Session, challenge_id: str) -> bool:
    """Check if all jury members have voted for a challenge."""
    votes = db.query(ArbiterVote).filter_by(challenge_id=challenge_id).all()
    if not votes:
        return False
    return all(v.vote is not None for v in votes)
