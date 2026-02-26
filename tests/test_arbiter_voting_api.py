from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    UserRole, TaskType, TaskStatus, ChallengeStatus,
    TrustTier, ChallengeVerdict,
)


def _setup_challenge_with_jury(client):
    """Create a full scenario with task, challenge, and jury votes."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    pub = User(nickname="pub-v", wallet="0xPV", role=UserRole.publisher)
    worker = User(nickname="wrk-v", wallet="0xWV", role=UserRole.worker)
    challenger = User(nickname="chl-v", wallet="0xCV", role=UserRole.worker)
    db.add_all([pub, worker, challenger])
    db.commit()

    task = Task(
        title="Vote Test", description="Test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=1),
        status=TaskStatus.arbitrating, publisher_id=pub.id,
        bounty=100.0, challenge_duration=7200,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=worker.id,
                       content="w", score=0.9, status="scored")
    c_sub = Submission(task_id=task.id, worker_id=challenger.id,
                       content="c", score=0.7, status="scored")
    db.add_all([w_sub, c_sub])
    db.commit()

    task.winner_submission_id = w_sub.id

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Mine is better",
        status=ChallengeStatus.pending, challenger_wallet="0xCV",
    )
    db.add(ch)
    db.commit()

    arbs = []
    votes = []
    for i in range(3):
        a = User(
            nickname=f"arb-v{i}", wallet=f"0xAV{i}", role=UserRole.worker,
            trust_score=850.0, trust_tier=TrustTier.S,
            is_arbiter=True, staked_amount=100.0, github_id=f"gh-v{i}",
        )
        db.add(a)
        db.commit()
        arbs.append(a)

        v = ArbiterVote(challenge_id=ch.id, arbiter_user_id=a.id)
        db.add(v)
        votes.append(v)

    db.commit()
    for v in votes:
        db.refresh(v)

    return task, ch, arbs, votes


def test_get_challenge_votes(client):
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    resp = client.get(f"/challenges/{ch.id}/votes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert all(v["vote"] is None for v in data)


def test_submit_vote(client):
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    resp = client.post(f"/challenges/{ch.id}/vote", json={
        "arbiter_user_id": arbs[0].id,
        "verdict": "upheld",
        "feedback": "The challenger is correct, their work is superior.",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["vote"] == "upheld"
    assert data["feedback"] is not None


def test_submit_vote_not_arbiter(client):
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    resp = client.post(f"/challenges/{ch.id}/vote", json={
        "arbiter_user_id": "nonexistent-id",
        "verdict": "upheld",
        "feedback": "some feedback",
    })
    assert resp.status_code == 404


def test_submit_vote_duplicate(client):
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    client.post(f"/challenges/{ch.id}/vote", json={
        "arbiter_user_id": arbs[0].id,
        "verdict": "upheld",
        "feedback": "first vote",
    })
    resp = client.post(f"/challenges/{ch.id}/vote", json={
        "arbiter_user_id": arbs[0].id,
        "verdict": "rejected",
        "feedback": "second vote",
    })
    assert resp.status_code == 400


def test_votes_hidden_without_viewer(client):
    """Without viewer_id, all pending votes are hidden."""
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    # Arbiter 0 votes
    client.post(f"/challenges/{ch.id}/vote", json={
        "arbiter_user_id": arbs[0].id,
        "verdict": "upheld",
        "feedback": "good work",
    })

    # No viewer_id → all votes masked
    resp = client.get(f"/challenges/{ch.id}/votes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert all(v["vote"] is None for v in data)
    assert all(v["feedback"] is None for v in data)


def test_votes_visible_to_own_viewer(client):
    """Arbiter can see their own vote but not others'."""
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    # Arbiter 0 votes
    client.post(f"/challenges/{ch.id}/vote", json={
        "arbiter_user_id": arbs[0].id,
        "verdict": "upheld",
        "feedback": "good work",
    })

    # Arbiter 0 as viewer → sees own vote
    resp = client.get(f"/challenges/{ch.id}/votes?viewer_id={arbs[0].id}")
    data = resp.json()
    own = [v for v in data if v["arbiter_user_id"] == arbs[0].id]
    others = [v for v in data if v["arbiter_user_id"] != arbs[0].id]
    assert own[0]["vote"] == "upheld"
    assert own[0]["feedback"] == "good work"
    assert all(v["vote"] is None for v in others)
    assert all(v["feedback"] is None for v in others)


def test_votes_revealed_when_all_voted(client):
    """All votes become visible once every arbiter has voted."""
    task, ch, arbs, votes = _setup_challenge_with_jury(client)

    for a in arbs:
        client.post(f"/challenges/{ch.id}/vote", json={
            "arbiter_user_id": a.id,
            "verdict": "upheld",
            "feedback": f"feedback from {a.nickname}",
        })

    # No viewer_id needed — all votes visible
    resp = client.get(f"/challenges/{ch.id}/votes")
    data = resp.json()
    assert all(v["vote"] == "upheld" for v in data)
    assert all(v["feedback"] is not None for v in data)
