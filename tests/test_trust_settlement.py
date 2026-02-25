from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    UserRole, TaskType, TaskStatus, ChallengeStatus,
    TrustTier, ChallengeVerdict, TrustEvent, TrustEventType,
)


def test_scheduler_selects_jury_on_challenge_window_expiry(client):
    """When challenge_window expires with challenges, scheduler selects jury."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    # Create 3 arbiters
    for i in range(3):
        a = User(
            nickname=f"sched-arb{i}", wallet=f"0xSA{i}", role=UserRole.worker,
            trust_score=850.0, trust_tier=TrustTier.S,
            is_arbiter=True, staked_amount=100.0, github_id=f"gh-sa{i}",
        )
        db.add(a)

    pub = User(nickname="sched-pub", wallet="0xSP", role=UserRole.publisher)
    wrk = User(nickname="sched-wrk", wallet="0xSW", role=UserRole.worker)
    db.add_all([pub, wrk])
    db.commit()

    task = Task(
        title="Sched Test", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=2),
        status=TaskStatus.challenge_window,
        challenge_window_end=datetime.now(timezone.utc) - timedelta(minutes=1),
        publisher_id=pub.id, bounty=100.0,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=wrk.id,
                       content="w", score=0.9, status="scored")
    db.add(w_sub)
    db.commit()
    task.winner_submission_id = w_sub.id

    chl_user = User(nickname="sched-chl", wallet="0xSC", role=UserRole.worker)
    db.add(chl_user)
    db.commit()
    c_sub = Submission(task_id=task.id, worker_id=chl_user.id,
                       content="c", score=0.7, status="scored")
    db.add(c_sub)
    db.commit()

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Better",
        status=ChallengeStatus.pending, challenger_wallet="0xSC",
    )
    db.add(ch)
    db.commit()

    from app.scheduler import quality_first_lifecycle
    with patch("app.scheduler.create_challenge_onchain", return_value="0x"):
        with patch("app.scheduler.resolve_challenge_onchain", return_value="0x"):
            quality_first_lifecycle(db)

    db.refresh(task)
    assert task.status == TaskStatus.arbitrating

    votes = db.query(ArbiterVote).filter_by(challenge_id=ch.id).all()
    assert len(votes) == 3


def test_scheduler_falls_back_to_stub_when_no_arbiters(client):
    """When no eligible arbiters exist, fall back to run_arbitration stub."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    pub = User(nickname="fb-pub", wallet="0xFP", role=UserRole.publisher)
    wrk = User(nickname="fb-wrk", wallet="0xFW", role=UserRole.worker)
    db.add_all([pub, wrk])
    db.commit()

    task = Task(
        title="Fallback Test", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=2),
        status=TaskStatus.challenge_window,
        challenge_window_end=datetime.now(timezone.utc) - timedelta(minutes=1),
        publisher_id=pub.id, bounty=50.0,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=wrk.id,
                       content="w", score=0.9, status="scored")
    db.add(w_sub)
    db.commit()
    task.winner_submission_id = w_sub.id

    chl_user = User(nickname="fb-chl", wallet="0xFC", role=UserRole.worker)
    db.add(chl_user)
    db.commit()
    c_sub = Submission(task_id=task.id, worker_id=chl_user.id,
                       content="c", score=0.7, status="scored")
    db.add(c_sub)
    db.commit()

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Better",
        status=ChallengeStatus.pending, challenger_wallet="0xFC",
    )
    db.add(ch)
    db.commit()

    from app.scheduler import quality_first_lifecycle
    with patch("app.scheduler.create_challenge_onchain", return_value="0x"):
        with patch("app.scheduler.resolve_challenge_onchain", return_value="0x"):
            with patch("app.scheduler.run_arbitration") as mock_arb:
                quality_first_lifecycle(db)
                mock_arb.assert_called_once_with(db, task.id)

    db.refresh(task)
    assert task.status == TaskStatus.arbitrating


def test_scheduler_resolves_jury_when_all_voted(client):
    """When all jury members vote, scheduler resolves and settles."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    # Create 3 arbiters
    arbiters = []
    for i in range(3):
        a = User(
            nickname=f"vote-arb{i}", wallet=f"0xVA{i}", role=UserRole.worker,
            trust_score=850.0, trust_tier=TrustTier.S,
            is_arbiter=True, staked_amount=100.0, github_id=f"gh-va{i}",
        )
        db.add(a)
        arbiters.append(a)

    pub = User(nickname="vote-pub", wallet="0xVP", role=UserRole.publisher)
    wrk = User(nickname="vote-wrk", wallet="0xVW", role=UserRole.worker)
    db.add_all([pub, wrk])
    db.commit()

    task = Task(
        title="Vote Test", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=2),
        status=TaskStatus.arbitrating,
        challenge_window_end=datetime.now(timezone.utc) - timedelta(hours=1),
        publisher_id=pub.id, bounty=100.0,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=wrk.id,
                       content="w", score=0.9, status="scored")
    db.add(w_sub)
    db.commit()
    task.winner_submission_id = w_sub.id

    chl_user = User(nickname="vote-chl", wallet="0xVC", role=UserRole.worker)
    db.add(chl_user)
    db.commit()
    c_sub = Submission(task_id=task.id, worker_id=chl_user.id,
                       content="c", score=0.7, status="scored")
    db.add(c_sub)
    db.commit()

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Better",
        status=ChallengeStatus.pending, challenger_wallet="0xVC",
    )
    db.add(ch)
    db.commit()

    # Create jury votes (all voted "rejected")
    for arb in arbiters:
        v = ArbiterVote(
            challenge_id=ch.id, arbiter_user_id=arb.id,
            vote=ChallengeVerdict.rejected, feedback="No improvement",
        )
        db.add(v)
    db.commit()

    from app.scheduler import quality_first_lifecycle
    with patch("app.scheduler.resolve_challenge_onchain", return_value="0x"):
        quality_first_lifecycle(db)

    db.refresh(task)
    db.refresh(ch)
    assert task.status == TaskStatus.closed
    assert ch.status == ChallengeStatus.judged
    assert ch.verdict == ChallengeVerdict.rejected

    # Check trust events were applied for majority voters
    events = db.query(TrustEvent).filter_by(
        event_type=TrustEventType.arbiter_majority
    ).all()
    assert len(events) == 3


def test_scheduler_applies_timeout_penalty(client):
    """When jury voting times out, non-voters get arbiter_timeout penalty."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    # Create 3 arbiters
    arbiters = []
    for i in range(3):
        a = User(
            nickname=f"to-arb{i}", wallet=f"0xTA{i}", role=UserRole.worker,
            trust_score=850.0, trust_tier=TrustTier.S,
            is_arbiter=True, staked_amount=100.0, github_id=f"gh-ta{i}",
        )
        db.add(a)
        arbiters.append(a)

    pub = User(nickname="to-pub", wallet="0xTP", role=UserRole.publisher)
    wrk = User(nickname="to-wrk", wallet="0xTW", role=UserRole.worker)
    db.add_all([pub, wrk])
    db.commit()

    task = Task(
        title="Timeout Test", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=10),
        status=TaskStatus.arbitrating,
        challenge_window_end=datetime.now(timezone.utc) - timedelta(hours=8),
        publisher_id=pub.id, bounty=100.0,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=wrk.id,
                       content="w", score=0.9, status="scored")
    db.add(w_sub)
    db.commit()
    task.winner_submission_id = w_sub.id

    chl_user = User(nickname="to-chl", wallet="0xTC", role=UserRole.worker)
    db.add(chl_user)
    db.commit()
    c_sub = Submission(task_id=task.id, worker_id=chl_user.id,
                       content="c", score=0.7, status="scored")
    db.add(c_sub)
    db.commit()

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Better",
        status=ChallengeStatus.pending, challenger_wallet="0xTC",
    )
    db.add(ch)
    db.commit()

    # Create jury votes — only 1 voted, 2 timed out
    past = datetime.now(timezone.utc) - timedelta(hours=7)
    v1 = ArbiterVote(
        challenge_id=ch.id, arbiter_user_id=arbiters[0].id,
        vote=ChallengeVerdict.rejected, feedback="No improvement",
        created_at=past,
    )
    v2 = ArbiterVote(
        challenge_id=ch.id, arbiter_user_id=arbiters[1].id,
        vote=None, created_at=past,
    )
    v3 = ArbiterVote(
        challenge_id=ch.id, arbiter_user_id=arbiters[2].id,
        vote=None, created_at=past,
    )
    db.add_all([v1, v2, v3])
    db.commit()

    from app.scheduler import quality_first_lifecycle
    with patch("app.scheduler.resolve_challenge_onchain", return_value="0x"):
        quality_first_lifecycle(db)

    db.refresh(task)
    db.refresh(ch)
    assert task.status == TaskStatus.closed
    assert ch.status == ChallengeStatus.judged

    # Check timeout penalties for the 2 non-voters
    timeout_events = db.query(TrustEvent).filter_by(
        event_type=TrustEventType.arbiter_timeout
    ).all()
    assert len(timeout_events) == 2

    # Check majority trust events for the single voter
    majority_events = db.query(TrustEvent).filter_by(
        event_type=TrustEventType.arbiter_majority
    ).all()
    assert len(majority_events) == 1


def test_apply_verdict_trust_minority(client):
    """Minority voters get arbiter_minority trust penalty."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    # Create 3 arbiters
    arbiters = []
    for i in range(3):
        a = User(
            nickname=f"min-arb{i}", wallet=f"0xMA{i}", role=UserRole.worker,
            trust_score=850.0, trust_tier=TrustTier.S,
            is_arbiter=True, staked_amount=100.0, github_id=f"gh-ma{i}",
        )
        db.add(a)
        arbiters.append(a)

    pub = User(nickname="min-pub", wallet="0xMP", role=UserRole.publisher)
    wrk = User(nickname="min-wrk", wallet="0xMW", role=UserRole.worker)
    db.add_all([pub, wrk])
    db.commit()

    task = Task(
        title="Minority Test", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=2),
        status=TaskStatus.arbitrating,
        challenge_window_end=datetime.now(timezone.utc) - timedelta(hours=1),
        publisher_id=pub.id, bounty=100.0,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=wrk.id,
                       content="w", score=0.9, status="scored")
    db.add(w_sub)
    db.commit()
    task.winner_submission_id = w_sub.id

    chl_user = User(nickname="min-chl", wallet="0xMC", role=UserRole.worker)
    db.add(chl_user)
    db.commit()
    c_sub = Submission(task_id=task.id, worker_id=chl_user.id,
                       content="c", score=0.7, status="scored")
    db.add(c_sub)
    db.commit()

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Better",
        status=ChallengeStatus.pending, challenger_wallet="0xMC",
    )
    db.add(ch)
    db.commit()

    # 2 vote "rejected", 1 votes "upheld" (minority)
    v1 = ArbiterVote(
        challenge_id=ch.id, arbiter_user_id=arbiters[0].id,
        vote=ChallengeVerdict.rejected, feedback="No",
    )
    v2 = ArbiterVote(
        challenge_id=ch.id, arbiter_user_id=arbiters[1].id,
        vote=ChallengeVerdict.rejected, feedback="No",
    )
    v3 = ArbiterVote(
        challenge_id=ch.id, arbiter_user_id=arbiters[2].id,
        vote=ChallengeVerdict.upheld, feedback="Yes",
    )
    db.add_all([v1, v2, v3])
    db.commit()

    from app.scheduler import quality_first_lifecycle
    with patch("app.scheduler.resolve_challenge_onchain", return_value="0x"):
        quality_first_lifecycle(db)

    db.refresh(task)
    assert task.status == TaskStatus.closed

    # 2 majority events, 1 minority event
    majority_events = db.query(TrustEvent).filter_by(
        event_type=TrustEventType.arbiter_majority
    ).all()
    minority_events = db.query(TrustEvent).filter_by(
        event_type=TrustEventType.arbiter_minority
    ).all()
    assert len(majority_events) == 2
    assert len(minority_events) == 1

    # Minority voter should have lost 15 trust points
    db.refresh(arbiters[2])
    assert arbiters[2].trust_score == 835.0
