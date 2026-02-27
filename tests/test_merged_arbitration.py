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
