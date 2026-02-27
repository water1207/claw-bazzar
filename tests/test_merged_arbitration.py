"""Tests for merged arbitration (JuryBallot + MaliciousTag)."""
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from app.models import (
    JuryBallot, MaliciousTag, TaskStatus, TrustEventType,
    Task, User, Submission, Challenge, ChallengeVerdict, ChallengeStatus,
)


def test_jury_ballot_model_exists(db_session):
    """JuryBallot model can be instantiated and persisted."""
    from app.models import JuryBallot
    ballot = JuryBallot(task_id="t1", arbiter_user_id="u1")
    db_session.add(ballot)
    db_session.commit()
    assert ballot.id is not None
    assert ballot.winner_submission_id is None  # not yet voted
    assert ballot.voted_at is None


def test_malicious_tag_model_exists(db_session):
    """MaliciousTag model can be instantiated and persisted."""
    from app.models import MaliciousTag
    tag = MaliciousTag(task_id="t1", arbiter_user_id="u1", target_submission_id="s1")
    db_session.add(tag)
    db_session.commit()
    assert tag.id is not None


def test_task_status_voided():
    """TaskStatus enum includes 'voided'."""
    assert TaskStatus.voided == "voided"


def test_trust_event_type_new_values():
    """TrustEventType includes pw_malicious and challenger_justified."""
    assert TrustEventType.pw_malicious == "pw_malicious"
    assert TrustEventType.challenger_justified == "challenger_justified"


def test_jury_vote_in_schema():
    """JuryVoteIn validates input correctly."""
    from app.schemas import JuryVoteIn
    vote = JuryVoteIn(
        arbiter_user_id="u1",
        winner_submission_id="s1",
        malicious_submission_ids=["s2", "s3"],
        feedback="Good work",
    )
    assert vote.winner_submission_id == "s1"
    assert len(vote.malicious_submission_ids) == 2


def test_jury_vote_in_rejects_winner_in_malicious():
    """JuryVoteIn rejects winner_submission_id appearing in malicious list."""
    from app.schemas import JuryVoteIn
    import pydantic
    import pytest
    with pytest.raises(pydantic.ValidationError):
        JuryVoteIn(
            arbiter_user_id="u1",
            winner_submission_id="s1",
            malicious_submission_ids=["s1"],  # conflict!
        )


# --- Helper functions ---

def _make_users(db, n):
    """Create n users and return them."""
    users = []
    for i in range(n):
        u = User(
            nickname=f"user{i}",
            wallet=f"0xuser{i}",
            role="both",
            is_arbiter=(i >= 4),  # indices 4,5,6 are arbiters
        )
        db.add(u)
        users.append(u)
    db.commit()
    for u in users:
        db.refresh(u)
    return users


def _make_quality_task_with_challenges(db, users):
    """
    Create a quality_first task with PW + 2 challengers.
    Returns (task, pw_submission, ch1_sub, ch2_sub, [challenge1, challenge2]).
    users: [publisher, pw_worker, challenger1, challenger2, arb1, arb2, arb3]
    """
    publisher, pw_worker, ch1, ch2 = users[0], users[1], users[2], users[3]
    task = Task(
        title="Test Task",
        description="desc",
        type="quality_first",
        bounty=100.0,
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        publisher_id=publisher.id,
        acceptance_criteria='["criterion 1"]',
        status=TaskStatus.arbitrating,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    pw_sub = Submission(task_id=task.id, worker_id=pw_worker.id, content="pw content")
    db.add(pw_sub)
    db.commit()
    db.refresh(pw_sub)
    task.winner_submission_id = pw_sub.id

    ch1_sub = Submission(task_id=task.id, worker_id=ch1.id, content="ch1 content")
    ch2_sub = Submission(task_id=task.id, worker_id=ch2.id, content="ch2 content")
    db.add_all([ch1_sub, ch2_sub])
    db.commit()
    db.refresh(ch1_sub)
    db.refresh(ch2_sub)

    c1 = Challenge(
        task_id=task.id,
        challenger_submission_id=ch1_sub.id,
        target_submission_id=pw_sub.id,
        reason="I'm better",
    )
    c2 = Challenge(
        task_id=task.id,
        challenger_submission_id=ch2_sub.id,
        target_submission_id=pw_sub.id,
        reason="I'm also better",
    )
    db.add_all([c1, c2])
    db.commit()
    db.refresh(c1)
    db.refresh(c2)
    db.refresh(task)

    return task, pw_sub, ch1_sub, ch2_sub, [c1, c2]


# --- Trust event tests ---

def test_pw_malicious_trust_event(db_session):
    """pw_malicious event applies -100 delta."""
    from app.services.trust import apply_event
    users = _make_users(db_session, 1)
    user = users[0]
    user.trust_score = 500
    db_session.commit()

    event = apply_event(db_session, user.id, TrustEventType.pw_malicious)
    db_session.refresh(user)
    assert event.delta == -100
    assert user.trust_score == 400


def test_challenger_justified_trust_event(db_session):
    """challenger_justified event applies +5 delta."""
    from app.services.trust import apply_event
    users = _make_users(db_session, 1)
    user = users[0]
    user.trust_score = 500
    db_session.commit()

    event = apply_event(db_session, user.id, TrustEventType.challenger_justified)
    db_session.refresh(user)
    assert event.delta == 5
    assert user.trust_score == 505
