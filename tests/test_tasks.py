from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def test_create_task(client):
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "Write haiku",
            "description": "Write a haiku about the sea",
            "type": "fastest_first",
            "threshold": 0.8,
            "deadline": future(),
            "publisher_id": "test-pub",
            "bounty": 1.0,
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Write haiku"
    assert data["status"] == "open"
    assert data["id"] is not None


def test_list_tasks(client):
    with PAYMENT_MOCK:
        client.post("/tasks", json={
            "title": "T1", "description": "d", "type": "fastest_first",
            "threshold": 0.5, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
        }, headers=PAYMENT_HEADERS)
        client.post("/tasks", json={
            "title": "T2", "description": "d", "type": "quality_first",
            "max_revisions": 3, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
        }, headers=PAYMENT_HEADERS)
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_tasks_filter_by_type(client):
    with PAYMENT_MOCK:
        client.post("/tasks", json={
            "title": "T1", "description": "d", "type": "fastest_first",
            "threshold": 0.5, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
        }, headers=PAYMENT_HEADERS)
        client.post("/tasks", json={
            "title": "T2", "description": "d", "type": "quality_first",
            "max_revisions": 3, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
        }, headers=PAYMENT_HEADERS)
    resp = client.get("/tasks?type=fastest_first")
    assert len(resp.json()) == 1
    assert resp.json()[0]["type"] == "fastest_first"


def test_get_task_not_found(client):
    resp = client.get("/tasks/nonexistent")
    assert resp.status_code == 404


def test_get_task_detail(client):
    with PAYMENT_MOCK:
        create_resp = client.post("/tasks", json={
            "title": "T1", "description": "d", "type": "fastest_first",
            "threshold": 0.5, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
        }, headers=PAYMENT_HEADERS)
    task_id = create_resp.json()["id"]
    resp = client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["submissions"] == []


def test_create_task_returns_402_without_payment(client):
    resp = client.post("/tasks", json={
        "title": "No payment",
        "description": "d",
        "type": "fastest_first",
        "threshold": 0.8,
        "deadline": future(),
        "publisher_id": "test-pub",
        "bounty": 1.0,
    })
    assert resp.status_code == 402
    data = resp.json()
    assert "amount" in data
    assert "network" in data
    assert "asset" in data
    assert "payTo" in data
    assert "scheme" in data
    assert "extra" in data


def test_create_task_with_valid_payment(client):
    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xabc"}):
        resp = client.post("/tasks", json={
            "title": "Paid task",
            "description": "d",
            "type": "fastest_first",
            "threshold": 0.8,
            "deadline": future(),
            "publisher_id": "test-pub",
            "bounty": 1.0,
        }, headers={"X-PAYMENT": "valid-payment"})
    assert resp.status_code == 201
    assert resp.json()["payment_tx_hash"] == "0xabc"


def test_create_task_with_invalid_payment(client):
    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": False, "tx_hash": None}):
        resp = client.post("/tasks", json={
            "title": "Bad payment",
            "description": "d",
            "type": "fastest_first",
            "threshold": 0.8,
            "deadline": future(),
            "publisher_id": "test-pub",
            "bounty": 1.0,
        }, headers={"X-PAYMENT": "invalid-payment"})
    assert resp.status_code == 402


def test_create_task_zero_bounty_skips_payment(client):
    resp = client.post("/tasks", json={
        "title": "Free task",
        "description": "No bounty needed",
        "type": "fastest_first",
        "threshold": 0.8,
        "deadline": future(),
        "publisher_id": "test-pub",
        "bounty": 0,
    })
    assert resp.status_code == 201
    assert resp.json()["payment_tx_hash"] is None


def test_submission_status_has_policy_violation():
    from app.models import SubmissionStatus
    assert SubmissionStatus.policy_violation == "policy_violation"
