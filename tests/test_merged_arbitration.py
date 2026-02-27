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


# --- API endpoint tests ---

def test_jury_vote_endpoint_happy_path(client_with_db):
    """POST /tasks/{task_id}/jury-vote accepts a merged vote."""
    client, db = client_with_db

    users = _make_users(db, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db, task.id)
    arbiter_id = ballots[0].arbiter_user_id

    resp = client.post(
        f"/tasks/{task.id}/jury-vote",
        json={
            "arbiter_user_id": arbiter_id,
            "winner_submission_id": ch1_sub.id,
            "malicious_submission_ids": [ch2_sub.id],
            "feedback": "ch1 is best",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["winner_submission_id"] == ch1_sub.id
    assert data["voted_at"] is not None


def test_jury_vote_endpoint_rejects_non_candidate(client_with_db):
    """POST /tasks/{task_id}/jury-vote rejects non-candidate winner."""
    client, db = client_with_db
    users = _make_users(db, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db, task.id)
    arbiter_id = ballots[0].arbiter_user_id

    resp = client.post(
        f"/tasks/{task.id}/jury-vote",
        json={
            "arbiter_user_id": arbiter_id,
            "winner_submission_id": "nonexistent-id",
            "malicious_submission_ids": [],
            "feedback": "",
        },
    )
    assert resp.status_code == 400


def test_jury_vote_endpoint_rejects_winner_in_malicious(client_with_db):
    """POST /tasks/{task_id}/jury-vote rejects winner in malicious list."""
    client, db = client_with_db
    users = _make_users(db, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db, task.id)
    arbiter_id = ballots[0].arbiter_user_id

    resp = client.post(
        f"/tasks/{task.id}/jury-vote",
        json={
            "arbiter_user_id": arbiter_id,
            "winner_submission_id": ch1_sub.id,
            "malicious_submission_ids": [ch1_sub.id],
            "feedback": "",
        },
    )
    assert resp.status_code == 422  # Pydantic validation error


# --- Vote helper ---

def _vote_all(db, task, ballots, winner_ids, malicious_map=None):
    """
    Helper: submit votes for all ballots.
    winner_ids: list of submission IDs (one per arbiter).
    malicious_map: dict {arbiter_index: [sub_ids]} -- optional.
    """
    from app.services.arbiter_pool import submit_merged_vote
    malicious_map = malicious_map or {}
    for i, ballot in enumerate(ballots):
        submit_merged_vote(
            db,
            task_id=task.id,
            arbiter_user_id=ballot.arbiter_user_id,
            winner_submission_id=winner_ids[i],
            malicious_submission_ids=malicious_map.get(i, []),
            feedback=f"vote {i}",
        )


# --- Scheduler tests ---

def test_scheduler_resolves_merged_jury(db_session):
    """Scheduler calls resolve_merged_jury and applies trust events."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db_session, task.id)

    # All 3 vote for ch1 (3:0 consensus)
    _vote_all(db_session, task, ballots, [ch1_sub.id] * 3)

    # Mock on-chain call
    with patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import _settle_after_arbitration
        _settle_after_arbitration(db_session, task)

    db_session.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == ch1_sub.id  # switched to ch1


def test_scheduler_voided_path(db_session):
    """Scheduler handles voided task (PW malicious)."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db_session, task.id)

    # All vote ch1, tag PW malicious
    _vote_all(
        db_session, task, ballots,
        [ch1_sub.id] * 3,
        malicious_map={0: [pw_sub.id], 1: [pw_sub.id], 2: [pw_sub.id]},
    )

    with patch("app.scheduler.void_challenge_onchain", return_value="0xvoid_tx") as mock_void, \
         patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import _settle_after_arbitration
        _settle_after_arbitration(db_session, task)

    db_session.refresh(task)
    assert task.status == TaskStatus.voided


# --- Full lifecycle integration tests (Task 14) ---

def test_full_lifecycle_challenger_wins(db_session):
    """Full flow: jury votes challenger → challenger wins, task closed."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db_session, task.id)

    # 2:1 vote for ch1
    _vote_all(db_session, task, ballots, [ch1_sub.id, ch1_sub.id, pw_sub.id])

    with patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import _settle_after_arbitration
        _settle_after_arbitration(db_session, task)

    db_session.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == ch1_sub.id

    # Verify challenge verdicts
    for c in challenges:
        db_session.refresh(c)
    ch1_c = next(c for c in challenges if c.challenger_submission_id == ch1_sub.id)
    ch2_c = next(c for c in challenges if c.challenger_submission_id == ch2_sub.id)
    assert ch1_c.verdict == ChallengeVerdict.upheld
    assert ch2_c.verdict == ChallengeVerdict.rejected

    # Coherence: first 2 voted ch1 (coherent), last voted pw (incoherent)
    for b in ballots:
        db_session.refresh(b)
    assert ballots[0].coherence_status == "coherent"
    assert ballots[2].coherence_status == "incoherent"


def test_full_lifecycle_deadlock_pw_wins(db_session):
    """Full flow: 1:1:1 deadlock → PW keeps win, all challengers rejected."""
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db_session, task.id)

    # 1:1:1 split
    _vote_all(db_session, task, ballots, [pw_sub.id, ch1_sub.id, ch2_sub.id])

    with patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import _settle_after_arbitration
        _settle_after_arbitration(db_session, task)

    db_session.refresh(task)
    assert task.status == TaskStatus.closed
    assert task.winner_submission_id == pw_sub.id  # PW wins in deadlock

    for c in challenges:
        db_session.refresh(c)
        assert c.verdict == ChallengeVerdict.rejected

    for b in ballots:
        db_session.refresh(b)
        assert b.coherence_status == "neutral"


def test_full_lifecycle_pw_malicious_voided(db_session):
    """Full flow: PW tagged malicious ≥2 → task voided, trust events applied."""
    from app.models import TrustEvent
    users = _make_users(db_session, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db_session, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db_session, task.id)

    # All vote ch1, 2 tag PW malicious
    _vote_all(
        db_session, task, ballots,
        [ch1_sub.id] * 3,
        malicious_map={0: [pw_sub.id], 1: [pw_sub.id]},
    )

    with patch("app.scheduler.void_challenge_onchain", return_value="0xvoid_tx"), \
         patch("app.scheduler._resolve_via_contract"):
        from app.scheduler import _settle_after_arbitration
        _settle_after_arbitration(db_session, task)

    db_session.refresh(task)
    assert task.status == TaskStatus.voided

    # PW worker got pw_malicious trust event
    pw_events = db_session.query(TrustEvent).filter_by(
        user_id=users[1].id,  # pw_worker
        event_type=TrustEventType.pw_malicious,
    ).all()
    assert len(pw_events) == 1
    assert pw_events[0].delta == -100

    # Challengers got justified events (not malicious)
    for c_user_idx in [2, 3]:
        events = db_session.query(TrustEvent).filter_by(
            user_id=users[c_user_idx].id,
            event_type=TrustEventType.challenger_justified,
        ).all()
        assert len(events) == 1


# --- GET jury-ballots endpoint tests ---

def test_get_jury_ballots_hides_votes_before_complete(client_with_db):
    """GET /tasks/{task_id}/jury-ballots hides details until all voted."""
    client, db = client_with_db
    users = _make_users(db, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db, users)

    from app.services.arbiter_pool import select_jury, submit_merged_vote
    ballots = select_jury(db, task.id)

    # Only 1 of 3 voted
    submit_merged_vote(db, task.id, ballots[0].arbiter_user_id, ch1_sub.id, [], "ok")

    resp = client.get(f"/tasks/{task.id}/jury-ballots")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    # All winner_submission_id should be hidden (None)
    hidden_count = sum(1 for b in data if b["winner_submission_id"] is None)
    assert hidden_count == 3


def test_get_jury_ballots_reveals_after_complete(client_with_db):
    """GET /tasks/{task_id}/jury-ballots reveals all after 3/3 voted."""
    client, db = client_with_db
    users = _make_users(db, 7)
    task, pw_sub, ch1_sub, ch2_sub, challenges = _make_quality_task_with_challenges(db, users)

    from app.services.arbiter_pool import select_jury
    ballots = select_jury(db, task.id)
    _vote_all(db, task, ballots, [ch1_sub.id] * 3)

    resp = client.get(f"/tasks/{task.id}/jury-ballots")
    assert resp.status_code == 200
    data = resp.json()
    assert all(b["winner_submission_id"] == ch1_sub.id for b in data)
