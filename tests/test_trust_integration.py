from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, Submission, Challenge, ArbiterVote,
    UserRole, TaskType, TaskStatus, ChallengeStatus,
    TrustTier, ChallengeVerdict, TrustEvent, TrustEventType,
)


def test_full_trust_settlement_upheld(client):
    """Challenge upheld: challenger gets challenger_won trust event."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    pub = User(nickname="int-pub", wallet="0xIP", role=UserRole.publisher)
    winner = User(nickname="int-win", wallet="0xIW", role=UserRole.worker)
    challenger = User(nickname="int-chl", wallet="0xIC", role=UserRole.worker)
    db.add_all([pub, winner, challenger])
    db.commit()

    task = Task(
        title="Int Test", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=2),
        status=TaskStatus.arbitrating,
        publisher_id=pub.id, bounty=100.0,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=winner.id,
                       content="w", score=0.9, status="scored")
    c_sub = Submission(task_id=task.id, worker_id=challenger.id,
                       content="c", score=0.7, status="scored")
    db.add_all([w_sub, c_sub])
    db.commit()
    task.winner_submission_id = w_sub.id

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Better",
        status=ChallengeStatus.judged, challenger_wallet="0xIC",
        verdict=ChallengeVerdict.upheld,
    )
    db.add(ch)
    db.commit()

    from app.scheduler import _settle_after_arbitration
    with patch("app.scheduler.resolve_challenge_onchain", return_value="0x"):
        _settle_after_arbitration(db, task)

    # Challenger should have challenger_won trust event
    challenger_events = db.query(TrustEvent).filter_by(
        user_id=challenger.id,
        event_type=TrustEventType.challenger_won,
    ).all()
    assert len(challenger_events) == 1

    # Winner submission was displaced — new winner is the challenger
    db.refresh(task)
    assert task.winner_submission_id == c_sub.id

    # The new winner (challenger) should also get worker_won
    worker_won_events = db.query(TrustEvent).filter_by(
        user_id=challenger.id,
        event_type=TrustEventType.worker_won,
    ).all()
    assert len(worker_won_events) == 1

    # Original winner gets worker_consolation (scored, non-winning, non-malicious)
    consolation_events = db.query(TrustEvent).filter_by(
        user_id=winner.id,
        event_type=TrustEventType.worker_consolation,
    ).all()
    assert len(consolation_events) == 1


def test_full_trust_settlement_rejected(client):
    """Challenge rejected: winner gets worker_won trust event."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    pub = User(nickname="rej-pub", wallet="0xRP", role=UserRole.publisher)
    winner = User(nickname="rej-win", wallet="0xRW", role=UserRole.worker)
    challenger = User(nickname="rej-chl", wallet="0xRC", role=UserRole.worker)
    db.add_all([pub, winner, challenger])
    db.commit()

    task = Task(
        title="Rej Test", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=2),
        status=TaskStatus.arbitrating,
        publisher_id=pub.id, bounty=100.0,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=winner.id,
                       content="w", score=0.9, status="scored")
    c_sub = Submission(task_id=task.id, worker_id=challenger.id,
                       content="c", score=0.7, status="scored")
    db.add_all([w_sub, c_sub])
    db.commit()
    task.winner_submission_id = w_sub.id

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Bad",
        status=ChallengeStatus.judged, challenger_wallet="0xRC",
        verdict=ChallengeVerdict.rejected,
    )
    db.add(ch)
    db.commit()

    from app.scheduler import _settle_after_arbitration
    with patch("app.scheduler.resolve_challenge_onchain", return_value="0x"):
        _settle_after_arbitration(db, task)

    # Winner should have worker_won trust event
    winner_events = db.query(TrustEvent).filter_by(
        user_id=winner.id,
        event_type=TrustEventType.worker_won,
    ).all()
    assert len(winner_events) == 1

    # Challenger should get worker_consolation (scored, non-winning)
    consolation_events = db.query(TrustEvent).filter_by(
        user_id=challenger.id,
        event_type=TrustEventType.worker_consolation,
    ).all()
    assert len(consolation_events) == 1


def test_full_trust_settlement_malicious(client):
    """Malicious challenge: challenger gets challenger_malicious + check_and_slash."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    pub = User(nickname="mal-pub", wallet="0xMP2", role=UserRole.publisher)
    winner = User(nickname="mal-win", wallet="0xMW2", role=UserRole.worker)
    challenger = User(
        nickname="mal-chl", wallet="0xMC2", role=UserRole.worker,
        trust_score=350.0, trust_tier=TrustTier.B, staked_amount=50.0,
    )
    db.add_all([pub, winner, challenger])
    db.commit()

    task = Task(
        title="Mal Test", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=2),
        status=TaskStatus.arbitrating,
        publisher_id=pub.id, bounty=100.0,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=winner.id,
                       content="w", score=0.9, status="scored")
    c_sub = Submission(task_id=task.id, worker_id=challenger.id,
                       content="c", score=0.7, status="scored")
    db.add_all([w_sub, c_sub])
    db.commit()
    task.winner_submission_id = w_sub.id

    ch = Challenge(
        task_id=task.id, challenger_submission_id=c_sub.id,
        target_submission_id=w_sub.id, reason="Malicious",
        status=ChallengeStatus.judged, challenger_wallet="0xMC2",
        verdict=ChallengeVerdict.malicious,
    )
    db.add(ch)
    db.commit()

    from app.scheduler import _settle_after_arbitration
    with patch("app.scheduler.resolve_challenge_onchain", return_value="0x"), \
         patch("app.services.staking.slash_onchain", return_value="0xslash"):
        _settle_after_arbitration(db, task)

    # Challenger should have challenger_malicious trust event
    malicious_events = db.query(TrustEvent).filter_by(
        user_id=challenger.id,
        event_type=TrustEventType.challenger_malicious,
    ).all()
    assert len(malicious_events) == 1

    # Winner keeps their position and gets worker_won
    winner_events = db.query(TrustEvent).filter_by(
        user_id=winner.id,
        event_type=TrustEventType.worker_won,
    ).all()
    assert len(winner_events) == 1

    # Malicious challenger should NOT get worker_consolation
    consolation_events = db.query(TrustEvent).filter_by(
        user_id=challenger.id,
        event_type=TrustEventType.worker_consolation,
    ).all()
    assert len(consolation_events) == 0


def test_settlement_no_challenges(client):
    """No challenges: winner gets worker_won, task closes normally."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    pub = User(nickname="nc-pub", wallet="0xNP", role=UserRole.publisher)
    winner = User(nickname="nc-win", wallet="0xNW", role=UserRole.worker)
    other = User(nickname="nc-oth", wallet="0xNO", role=UserRole.worker)
    db.add_all([pub, winner, other])
    db.commit()

    task = Task(
        title="No Chl Test", description="test", type=TaskType.quality_first,
        deadline=datetime.now(timezone.utc) - timedelta(hours=2),
        status=TaskStatus.arbitrating,
        publisher_id=pub.id, bounty=50.0,
    )
    db.add(task)
    db.commit()

    w_sub = Submission(task_id=task.id, worker_id=winner.id,
                       content="w", score=0.9, status="scored")
    o_sub = Submission(task_id=task.id, worker_id=other.id,
                       content="o", score=0.6, status="scored")
    db.add_all([w_sub, o_sub])
    db.commit()
    task.winner_submission_id = w_sub.id

    from app.scheduler import _settle_after_arbitration
    with patch("app.scheduler.resolve_challenge_onchain", return_value="0x"):
        _settle_after_arbitration(db, task)

    # Winner gets worker_won
    winner_events = db.query(TrustEvent).filter_by(
        user_id=winner.id,
        event_type=TrustEventType.worker_won,
    ).all()
    assert len(winner_events) == 1

    # Other submitter gets worker_consolation
    consolation_events = db.query(TrustEvent).filter_by(
        user_id=other.id,
        event_type=TrustEventType.worker_consolation,
    ).all()
    assert len(consolation_events) == 1

    db.refresh(task)
    assert task.status == TaskStatus.closed
