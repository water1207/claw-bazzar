from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def make_task_and_submission(client, type="fastest_first", threshold=0.8):
    with PAYMENT_MOCK:
        task = client.post("/tasks", json={
            "title": "T", "description": "d", "type": type,
            "threshold": threshold, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
        }, headers=PAYMENT_HEADERS).json()
    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "answer"
        }).json()
    return task, sub


def test_score_submission_updates_score(client):
    task, sub = make_task_and_submission(client)
    resp = client.post(f"/internal/submissions/{sub['id']}/score", json={
        "score": 0.75, "feedback": "decent"
    })
    assert resp.status_code == 200
    updated = client.get(f"/tasks/{task['id']}/submissions/{sub['id']}").json()
    assert updated["score"] == 0.75
    assert updated["oracle_feedback"] == "decent"
    assert updated["status"] == "scored"


def test_fastest_first_closes_on_threshold(client):
    task, sub = make_task_and_submission(client, threshold=0.7)
    client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})
    task_resp = client.get(f"/tasks/{task['id']}").json()
    assert task_resp["status"] == "closed"
    assert task_resp["winner_submission_id"] == sub["id"]


def test_fastest_first_stays_open_below_threshold(client):
    task, sub = make_task_and_submission(client, threshold=0.9)
    client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.5})
    task_resp = client.get(f"/tasks/{task['id']}").json()
    assert task_resp["status"] == "open"
    assert task_resp["winner_submission_id"] is None


def test_score_nonexistent_submission(client):
    resp = client.post("/internal/submissions/bad-id/score", json={"score": 0.5})
    assert resp.status_code == 404
