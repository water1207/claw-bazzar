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


def make_quality_task(client, bounty=10.0):
    body = {
        "title": "Q", "description": "d", "type": "quality_first",
        "max_revisions": 3, "deadline": future(),
        "publisher_id": "pub", "bounty": bounty,
        "challenge_duration": 7200,
    }
    with PAYMENT_MOCK:
        return client.post("/tasks", json=body, headers=PAYMENT_HEADERS).json()


def submit(client, task_id, worker_id, content="answer"):
    with patch("app.routers.submissions.invoke_oracle"):
        return client.post(
            f"/tasks/{task_id}/submissions",
            json={"worker_id": worker_id, "content": content},
        ).json()


def setup_challenge_window(client, task_id, winner_sub_id):
    """Manually set task to challenge_window state via direct DB manipulation."""
    from app.database import get_db
    from app.main import app
    db = next(app.dependency_overrides[get_db]())
    from app.models import Task
    task = db.query(Task).filter(Task.id == task_id).first()
    task.status = TaskStatus.challenge_window
    task.winner_submission_id = winner_sub_id
    task.challenge_window_end = datetime.now(timezone.utc) + timedelta(hours=2)
    db.commit()


def test_create_challenge(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1", "winner content")
    s2 = submit(client, task["id"], "w2", "challenger content")

    # Score submissions via internal endpoint
    client.post(f"/internal/submissions/{s1['id']}/score", json={"score": 0.9})
    client.post(f"/internal/submissions/{s2['id']}/score", json={"score": 0.7})

    setup_challenge_window(client, task["id"], s1["id"])

    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "My solution handles edge cases better",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["challenger_submission_id"] == s2["id"]
    assert data["target_submission_id"] == s1["id"]
    assert data["status"] == "pending"
    assert data["verdict"] is None


def test_challenge_rejected_when_not_in_window(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    # Task is still 'open', not 'challenge_window'
    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "test",
    })
    assert resp.status_code == 400
    assert "challenge_window" in resp.json()["detail"]


def test_challenge_rejected_winner_cannot_challenge_self(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    setup_challenge_window(client, task["id"], s1["id"])

    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s1["id"],
        "reason": "challenging myself",
    })
    assert resp.status_code == 400
    assert "winner" in resp.json()["detail"].lower()


def test_challenge_rejected_submission_not_in_task(client):
    task1 = make_quality_task(client)
    task2 = make_quality_task(client)
    s1 = submit(client, task1["id"], "w1")
    s2 = submit(client, task2["id"], "w2")

    setup_challenge_window(client, task1["id"], s1["id"])

    resp = client.post(f"/tasks/{task1['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "wrong task",
    })
    assert resp.status_code == 400
    assert "not belong" in resp.json()["detail"].lower() or "not found" in resp.json()["detail"].lower()


def test_challenge_rejected_duplicate(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    setup_challenge_window(client, task["id"], s1["id"])

    client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "first attempt",
    })
    resp = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"],
        "reason": "second attempt",
    })
    assert resp.status_code == 400
    assert "already" in resp.json()["detail"].lower()


def test_list_challenges(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")
    s3 = submit(client, task["id"], "w3")

    setup_challenge_window(client, task["id"], s1["id"])

    client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"], "reason": "r1"})
    client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s3["id"], "reason": "r2"})

    resp = client.get(f"/tasks/{task['id']}/challenges")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_single_challenge(client):
    task = make_quality_task(client)
    s1 = submit(client, task["id"], "w1")
    s2 = submit(client, task["id"], "w2")

    setup_challenge_window(client, task["id"], s1["id"])

    created = client.post(f"/tasks/{task['id']}/challenges", json={
        "challenger_submission_id": s2["id"], "reason": "test"}).json()

    resp = client.get(f"/tasks/{task['id']}/challenges/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]
