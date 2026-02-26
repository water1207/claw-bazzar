# tests/test_arbiter_coherence.py
"""Tests for arbiter coherence status and reward distribution."""
import pytest
from app.models import (
    ArbiterVote, TrustEventType, ChallengeVerdict,
)


def test_arbiter_vote_has_coherence_status_field(client):
    """ArbiterVote model must have a coherence_status column."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    vote = ArbiterVote(
        challenge_id="ch-1",
        arbiter_user_id="arb-1",
        vote=ChallengeVerdict.upheld,
        coherence_status="coherent",
    )
    db.add(vote)
    db.commit()
    db.refresh(vote)
    assert vote.coherence_status == "coherent"


def test_trust_event_type_has_arbiter_coherence():
    """TrustEventType enum must include arbiter_coherence."""
    assert hasattr(TrustEventType, "arbiter_coherence")
    assert TrustEventType.arbiter_coherence.value == "arbiter_coherence"


from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    UserRole, TaskType, TaskStatus, ChallengeStatus,
    TrustTier, ChallengeVerdict,
)
from app.services.arbiter_pool import resolve_jury


def _make_arbiter(db, name, wallet):
    user = User(
        nickname=name, wallet=wallet, role=UserRole.worker,
        trust_score=850.0, trust_tier=TrustTier.S,
        is_arbiter=True, staked_amount=100.0, github_id="gh-" + name,
    )
    db.add(user)
    db.commit()
    return user


def _make_challenge(db):
    publisher = User(nickname="pub-c", wallet="0xPUB", role=UserRole.publisher)
    worker = User(nickname="wrk-c", wallet="0xWRK", role=UserRole.worker)
    db.add_all([publisher, worker])
    db.commit()
    task = Task(
        title="Test", description="Test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        status=TaskStatus.arbitrating, publisher_id=publisher.id,
        bounty=100.0,
    )
    db.add(task)
    db.commit()
    winner_sub = Submission(
        task_id=task.id, worker_id=worker.id, content="w", score=0.9, status="scored",
    )
    db.add(winner_sub)
    db.commit()
    task.winner_submission_id = winner_sub.id
    challenge = Challenge(
        task_id=task.id, challenger_submission_id=winner_sub.id,
        target_submission_id=winner_sub.id, reason="test",
        status=ChallengeStatus.pending, challenger_wallet="0xCHL",
    )
    db.add(challenge)
    db.commit()
    return task, challenge


def test_resolve_jury_2_1_coherence(client):
    """2:1 vote → majority=coherent, minority=incoherent."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge = _make_challenge(db)
    a1 = _make_arbiter(db, "c-arb1", "0xCA1")
    a2 = _make_arbiter(db, "c-arb2", "0xCA2")
    a3 = _make_arbiter(db, "c-arb3", "0xCA3")

    v1 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a1.id,
                     vote=ChallengeVerdict.upheld, feedback="a")
    v2 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a2.id,
                     vote=ChallengeVerdict.upheld, feedback="b")
    v3 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a3.id,
                     vote=ChallengeVerdict.rejected, feedback="c")
    db.add_all([v1, v2, v3])
    db.commit()

    verdict = resolve_jury(db, challenge.id)
    assert verdict == ChallengeVerdict.upheld

    db.refresh(v1); db.refresh(v2); db.refresh(v3)
    assert v1.coherence_status == "coherent"
    assert v2.coherence_status == "coherent"
    assert v3.coherence_status == "incoherent"


def test_resolve_jury_3_0_coherence(client):
    """3:0 vote → all coherent."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge = _make_challenge(db)
    a1 = _make_arbiter(db, "u-arb1", "0xUA1")
    a2 = _make_arbiter(db, "u-arb2", "0xUA2")
    a3 = _make_arbiter(db, "u-arb3", "0xUA3")

    v1 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a1.id,
                     vote=ChallengeVerdict.rejected, feedback="a")
    v2 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a2.id,
                     vote=ChallengeVerdict.rejected, feedback="b")
    v3 = ArbiterVote(challenge_id=challenge.id, arbiter_user_id=a3.id,
                     vote=ChallengeVerdict.rejected, feedback="c")
    db.add_all([v1, v2, v3])
    db.commit()

    verdict = resolve_jury(db, challenge.id)
    assert verdict == ChallengeVerdict.rejected
    db.refresh(v1); db.refresh(v2); db.refresh(v3)
    assert v1.coherence_status == "coherent"
    assert v2.coherence_status == "coherent"
    assert v3.coherence_status == "coherent"


def test_resolve_jury_deadlock_neutral(client):
    """1:1:1 deadlock → verdict=rejected, all neutral."""
    db = next(next(iter(client.app.dependency_overrides.values()))())
    task, challenge = _make_challenge(db)
    a1 = _make_arbiter(db, "d-arb1", "0xDA1")
    a2 = _make_arbiter(db, "d-arb2", "0xDA2")
    a3 = _make_arbiter(db, "d-arb3", "0xDA3")

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

    db.refresh(v1); db.refresh(v2); db.refresh(v3)
    assert v1.coherence_status == "neutral"
    assert v2.coherence_status == "neutral"
    assert v3.coherence_status == "neutral"
    assert v1.is_majority is None
    assert v2.is_majority is None
    assert v3.is_majority is None
