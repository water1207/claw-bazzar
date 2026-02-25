# tests/test_arbiter_pool.py
import pytest
from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    UserRole, TaskType, TaskStatus, ChallengeStatus,
    TrustTier, ChallengeVerdict,
)
from app.services.arbiter_pool import (
    select_jury, submit_vote, resolve_jury, check_jury_ready,
)


def _make_arbiter(db, name, wallet):
    """Helper to create an S-tier arbiter user."""
    user = User(
        nickname=name, wallet=wallet, role=UserRole.worker,
        trust_score=850.0, trust_tier=TrustTier.S,
        is_arbiter=True, staked_amount=100.0, github_id="gh-" + name,
    )
    db.add(user)
    db.commit()
    return user


def _make_task_with_challenge(db):
    """Helper to create a task in arbitrating state with a challenge."""
    publisher = User(nickname="pub", wallet="0xPUB", role=UserRole.publisher)
    worker = User(nickname="wrk", wallet="0xWRK", role=UserRole.worker)
    challenger_user = User(nickname="chl", wallet="0xCHL", role=UserRole.worker)
    db.add_all([publisher, worker, challenger_user])
    db.commit()

    task = Task(
        title="Test", description="Test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        status=TaskStatus.arbitrating, publisher_id=publisher.id,
        bounty=100.0, challenge_duration=7200,
    )
    db.add(task)
    db.commit()

    winner_sub = Submission(
        task_id=task.id, worker_id=worker.id, content="winner",
        score=0.9, status="scored",
    )
    challenger_sub = Submission(
        task_id=task.id, worker_id=challenger_user.id, content="challenger",
        score=0.7, status="scored",
    )
    db.add_all([winner_sub, challenger_sub])
    db.commit()

    task.winner_submission_id = winner_sub.id

    challenge = Challenge(
        task_id=task.id,
        challenger_submission_id=challenger_sub.id,
        target_submission_id=winner_sub.id,
        reason="My submission is better",
        status=ChallengeStatus.pending,
        challenger_wallet="0xCHL",
    )
    db.add(challenge)
    db.commit()
    return task, challenge, publisher, worker, challenger_user


def test_select_jury_picks_3(client):
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)

    a1 = _make_arbiter(db, "arb1", "0xA1")
    a2 = _make_arbiter(db, "arb2", "0xA2")
    a3 = _make_arbiter(db, "arb3", "0xA3")
    a4 = _make_arbiter(db, "arb4", "0xA4")

    votes = select_jury(db, task.id)
    assert len(votes) == 3
    arbiter_ids = {v.arbiter_user_id for v in votes}
    assert pub.id not in arbiter_ids
    assert wrk.id not in arbiter_ids
    assert chl.id not in arbiter_ids


def test_select_jury_excludes_task_participants(client):
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)

    wrk.trust_score = 850.0
    wrk.trust_tier = TrustTier.S
    wrk.is_arbiter = True
    wrk.staked_amount = 100.0
    wrk.github_id = "gh-wrk"
    db.commit()

    a1 = _make_arbiter(db, "arb1", "0xA1")
    a2 = _make_arbiter(db, "arb2", "0xA2")
    a3 = _make_arbiter(db, "arb3", "0xA3")

    votes = select_jury(db, task.id)
    arbiter_ids = {v.arbiter_user_id for v in votes}
    assert wrk.id not in arbiter_ids


def test_select_jury_fallback_stub(client):
    """If 0 arbiters available, returns empty list (fallback to stub)."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)

    votes = select_jury(db, task.id)
    assert len(votes) == 0


def test_submit_vote(client):
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)
    a1 = _make_arbiter(db, "arb1", "0xA1")

    vote_record = ArbiterVote(
        challenge_id=challenge.id, arbiter_user_id=a1.id,
    )
    db.add(vote_record)
    db.commit()

    updated = submit_vote(db, vote_record.id, ChallengeVerdict.upheld,
                          "The challenger made valid points")
    assert updated.vote == ChallengeVerdict.upheld
    assert updated.feedback == "The challenger made valid points"


def test_resolve_jury_majority_upheld(client):
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)

    a1 = _make_arbiter(db, "arb1", "0xA1")
    a2 = _make_arbiter(db, "arb2", "0xA2")
    a3 = _make_arbiter(db, "arb3", "0xA3")

    v1 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a1.id,
                     vote=ChallengeVerdict.upheld, feedback="Agree")
    v2 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a2.id,
                     vote=ChallengeVerdict.upheld, feedback="Agree too")
    v3 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a3.id,
                     vote=ChallengeVerdict.rejected, feedback="Disagree")
    db.add_all([v1, v2, v3])
    db.commit()

    verdict = resolve_jury(db, challenge.id)
    assert verdict == ChallengeVerdict.upheld

    db.refresh(v1)
    db.refresh(v2)
    db.refresh(v3)
    assert v1.is_majority is True
    assert v2.is_majority is True
    assert v3.is_majority is False


def test_resolve_jury_no_majority_defaults_rejected(client):
    """3 different votes -> default to rejected."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)
    a1 = _make_arbiter(db, "arb1", "0xA1")
    a2 = _make_arbiter(db, "arb2", "0xA2")
    a3 = _make_arbiter(db, "arb3", "0xA3")

    v1 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a1.id,
                     vote=ChallengeVerdict.upheld, feedback="a")
    v2 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a2.id,
                     vote=ChallengeVerdict.rejected, feedback="b")
    v3 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a3.id,
                     vote=ChallengeVerdict.malicious, feedback="c")
    db.add_all([v1, v2, v3])
    db.commit()

    verdict = resolve_jury(db, challenge.id)
    assert verdict == ChallengeVerdict.rejected


def test_check_jury_ready_all_voted(client):
    """check_jury_ready returns True when all votes are cast."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)
    a1 = _make_arbiter(db, "arb1", "0xA1")
    a2 = _make_arbiter(db, "arb2", "0xA2")

    v1 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a1.id,
                     vote=ChallengeVerdict.upheld, feedback="ok")
    v2 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a2.id,
                     vote=ChallengeVerdict.rejected, feedback="no")
    db.add_all([v1, v2])
    db.commit()

    assert check_jury_ready(db, challenge.id) is True


def test_check_jury_ready_not_all_voted(client):
    """check_jury_ready returns False when some votes are missing."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)
    a1 = _make_arbiter(db, "arb1", "0xA1")
    a2 = _make_arbiter(db, "arb2", "0xA2")

    v1 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a1.id,
                     vote=ChallengeVerdict.upheld, feedback="ok")
    v2 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a2.id)
    db.add_all([v1, v2])
    db.commit()

    assert check_jury_ready(db, challenge.id) is False


def test_check_jury_ready_no_votes(client):
    """check_jury_ready returns False when no votes exist."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge, pub, wrk, chl = _make_task_with_challenge(db)

    assert check_jury_ready(db, challenge.id) is False
