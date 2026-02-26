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
