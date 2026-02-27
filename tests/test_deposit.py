from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def make_quality_task(client, bounty=10.0, submission_deposit=1.0):
    body = {
        "title": "Q", "description": "d", "type": "quality_first",
        "max_revisions": 3, "deadline": future(),
        "publisher_id": "pub", "bounty": bounty,
        "submission_deposit": submission_deposit,
        "acceptance_criteria": ["验收标准"],
    }
    with PAYMENT_MOCK:
        return client.post("/tasks", json=body, headers=PAYMENT_HEADERS).json()


def test_quality_first_submission_no_deposit(client):
    """quality_first submissions no longer require deposit (deposits are for challenges only)."""
    task = make_quality_task(client, bounty=10.0, submission_deposit=1.0)
    with patch("app.routers.submissions.invoke_oracle"):
        resp = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "answer"
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["deposit"] is None


def test_fastest_first_no_deposit(client):
    """fastest_first tasks don't require deposit."""
    body = {
        "title": "F", "description": "d", "type": "fastest_first",
        "threshold": 0.8, "deadline": future(),
        "publisher_id": "pub", "bounty": 10.0,
        "acceptance_criteria": ["验收标准"],
    }
    with PAYMENT_MOCK:
        task = client.post("/tasks", json=body, headers=PAYMENT_HEADERS).json()
    with patch("app.routers.submissions.invoke_oracle"):
        resp = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "answer"
        })
    assert resp.status_code == 201
    assert resp.json()["deposit"] is None
