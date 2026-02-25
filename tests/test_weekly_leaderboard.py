from datetime import datetime, timezone, timedelta
from app.models import (
    User, Task, Submission, UserRole, TaskType, TaskStatus,
    TrustTier, TrustEvent, TrustEventType,
)


def test_weekly_leaderboard_top3_gets_30(client):
    """Top 1-3 workers get +30 trust points."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    pub = User(nickname="lb-pub", wallet="0xLBP", role=UserRole.publisher)
    db.add(pub)
    db.commit()

    # Create 5 workers
    workers = []
    for i in range(5):
        w = User(nickname=f"lb-w{i}", wallet=f"0xLB{i}", role=UserRole.worker)
        db.add(w)
        db.commit()
        workers.append(w)

    # Create closed tasks with different payout amounts, winner subs
    bounties = [100, 80, 60, 40, 20]
    for i, (worker, bounty) in enumerate(zip(workers, bounties)):
        sub = Submission(
            task_id="placeholder",  # will be set below
            worker_id=worker.id,
            content=f"work-{i}",
            score=0.9,
            status="scored",
        )
        db.add(sub)
        db.commit()

        task = Task(
            title=f"LB Task {i}", description="test",
            type=TaskType.quality_first,
            deadline=datetime.now(timezone.utc) - timedelta(days=1),
            status=TaskStatus.closed,
            publisher_id=pub.id,
            bounty=bounty, payout_amount=bounty * 0.8,
            winner_submission_id=sub.id,
        )
        db.add(task)
        db.commit()

        # Fix the submission's task_id
        sub.task_id = task.id
        db.commit()

    from app.scheduler import run_weekly_leaderboard
    run_weekly_leaderboard(db)

    # Top 1-3 get +30
    for i in range(3):
        db.refresh(workers[i])
        events = db.query(TrustEvent).filter_by(
            user_id=workers[i].id,
            event_type=TrustEventType.weekly_leaderboard,
        ).all()
        assert len(events) == 1
        assert events[0].delta == 30.0

    # Worker 4 (rank 4) gets +20
    events4 = db.query(TrustEvent).filter_by(
        user_id=workers[3].id,
        event_type=TrustEventType.weekly_leaderboard,
    ).all()
    assert len(events4) == 1
    assert events4[0].delta == 20.0

    # Worker 5 (rank 5) also gets +20
    events5 = db.query(TrustEvent).filter_by(
        user_id=workers[4].id,
        event_type=TrustEventType.weekly_leaderboard,
    ).all()
    assert len(events5) == 1
    assert events5[0].delta == 20.0


def test_weekly_leaderboard_no_closed_tasks(client):
    """No closed tasks = no leaderboard entries."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)

    from app.scheduler import run_weekly_leaderboard
    run_weekly_leaderboard(db)

    events = db.query(TrustEvent).filter_by(
        event_type=TrustEventType.weekly_leaderboard,
    ).all()
    assert len(events) == 0
