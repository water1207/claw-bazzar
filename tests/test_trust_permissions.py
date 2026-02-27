from unittest.mock import patch
from app.models import User, Task, Submission, UserRole, TaskType, TrustTier
from datetime import datetime, timezone, timedelta


def _create_quality_task(client, bounty=100.0):
    """Helper: create publisher + quality_first task."""
    db = next(iter(client.app.dependency_overrides.values()))()
    if hasattr(db, '__next__'):
        db = next(db)
    pub = User(nickname="perm-pub", wallet="0xPPUB", role=UserRole.publisher)
    db.add(pub)
    db.commit()

    PAYMENT_MOCK = patch("app.routers.tasks.verify_payment",
                         return_value={"valid": True, "tx_hash": "0xtest"})
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "Perm Test", "description": "test",
            "type": "quality_first",
            "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "publisher_id": pub.id,
            "bounty": bounty,
            "acceptance_criteria": ["验收标准"],
        }, headers={"X-PAYMENT": "test"})
    return resp.json()["id"], pub, db


def test_c_level_cannot_submit(client):
    """C-level user cannot submit to tasks."""
    task_id, pub, db = _create_quality_task(client)

    banned = User(
        nickname="banned-wrk", wallet="0xBAN", role=UserRole.worker,
        trust_score=100.0, trust_tier=TrustTier.C,
    )
    db.add(banned)
    db.commit()

    resp = client.post(f"/tasks/{task_id}/submissions", json={
        "worker_id": banned.id, "content": "attempt",
    })
    assert resp.status_code == 403


def test_b_level_bounty_cap(client):
    """B-level user cannot accept tasks with bounty > 50 USDC."""
    task_id, pub, db = _create_quality_task(client, bounty=100.0)

    warning_user = User(
        nickname="warning-wrk", wallet="0xWARN", role=UserRole.worker,
        trust_score=400.0, trust_tier=TrustTier.B,
    )
    db.add(warning_user)
    db.commit()

    resp = client.post(f"/tasks/{task_id}/submissions", json={
        "worker_id": warning_user.id, "content": "attempt",
    })
    assert resp.status_code == 403


def test_a_level_can_submit(client):
    """A-level user CAN submit normally."""
    task_id, pub, db = _create_quality_task(client, bounty=100.0)

    normal_user = User(
        nickname="normal-wrk", wallet="0xNRM", role=UserRole.worker,
        trust_score=500.0, trust_tier=TrustTier.A,
    )
    db.add(normal_user)
    db.commit()

    resp = client.post(f"/tasks/{task_id}/submissions", json={
        "worker_id": normal_user.id, "content": "good work",
    })
    assert resp.status_code == 201
