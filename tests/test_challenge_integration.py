from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app.models import TaskStatus

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_manual_arbitrate_endpoint(client):
    """Test POST /internal/tasks/{id}/arbitrate triggers arbiter."""
    # Create task
    with PAYMENT_MOCK:
        task = client.post("/tasks", json={
            "title": "Q", "description": "d", "type": "quality_first",
            "max_revisions": 3, "deadline": future(),
            "publisher_id": "pub", "bounty": 10.0,
            "challenge_duration": 7200,
            "acceptance_criteria": ["验收标准"],
        }, headers=PAYMENT_HEADERS).json()

    # Submit
    with patch("app.routers.submissions.invoke_oracle"):
        s1 = client.post(f"/tasks/{task['id']}/submissions",
                         json={"worker_id": "w1", "content": "a"}).json()
        s2 = client.post(f"/tasks/{task['id']}/submissions",
                         json={"worker_id": "w2", "content": "b"}).json()

    # Score
    client.post(f"/internal/submissions/{s1['id']}/score", json={"score": 0.9})
    client.post(f"/internal/submissions/{s2['id']}/score", json={"score": 0.7})

    # Manually set to challenge_window
    from app.database import get_db
    from app.main import app
    from app.models import Task
    db = next(app.dependency_overrides[get_db]())
    t = db.query(Task).filter(Task.id == task["id"]).first()
    t.status = TaskStatus.challenge_window
    t.winner_submission_id = s1["id"]
    t.challenge_window_end = datetime.now(timezone.utc) + timedelta(hours=2)
    db.commit()

    # Create challenge
    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "I am better",
    })
    assert resp.status_code == 201

    # Set to arbitrating
    t.status = TaskStatus.arbitrating
    db.commit()

    # Trigger manual arbitration
    resp = client.post(f"/internal/tasks/{task['id']}/arbitrate")
    assert resp.status_code == 200

    # Check challenge is judged (stub always rejects)
    challenges = client.get(f"/tasks/{task['id']}/challenges").json()
    assert len(challenges) == 1
    assert challenges[0]["status"] == "judged"
    assert challenges[0]["verdict"] == "rejected"
