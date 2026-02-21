"""Tests for bounty and payout fields on the Task model."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def test_create_task_with_bounty(client):
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "Bounty task",
            "description": "Has a bounty",
            "type": "fastest_first",
            "threshold": 0.8,
            "deadline": future(),
            "publisher_id": "pub-001",
            "bounty": 2.5,
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 201
    data = resp.json()
    assert data["publisher_id"] == "pub-001"
    assert data["bounty"] == 2.5
    assert data["payout_status"] == "pending"
    assert data["payment_tx_hash"] == "0xtest"
    assert data["payout_tx_hash"] is None
    assert data["payout_amount"] is None


def test_bounty_fields_in_task_detail(client):
    with PAYMENT_MOCK:
        create_resp = client.post("/tasks", json={
            "title": "Detail check",
            "description": "d",
            "type": "fastest_first",
            "threshold": 0.5,
            "deadline": future(),
            "publisher_id": "pub-002",
            "bounty": 1.0,
        }, headers=PAYMENT_HEADERS)
    task_id = create_resp.json()["id"]
    resp = client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["publisher_id"] == "pub-002"
    assert data["bounty"] == 1.0
    assert data["payout_status"] == "pending"


def test_bounty_fields_in_task_list(client):
    with PAYMENT_MOCK:
        client.post("/tasks", json={
            "title": "Listed",
            "description": "d",
            "type": "fastest_first",
            "threshold": 0.5,
            "deadline": future(),
            "publisher_id": "pub-003",
            "bounty": 3.0,
        }, headers=PAYMENT_HEADERS)
    resp = client.get("/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["publisher_id"] == "pub-003"
    assert data[0]["bounty"] == 3.0
    assert data[0]["payout_status"] == "pending"


def test_payout_fields_default_values(client):
    """Verify payout columns default correctly at model level."""
    from app.database import get_db
    from app.main import app
    from app.models import Task as TaskModel

    db = next(app.dependency_overrides[get_db]())
    task = db.query(TaskModel).first()  # no tasks yet
    assert task is None

    # Create a task
    with PAYMENT_MOCK:
        client.post("/tasks", json={
            "title": "Defaults",
            "description": "d",
            "type": "fastest_first",
            "threshold": 0.5,
            "deadline": future(),
            "publisher_id": "pub-def",
            "bounty": 0.5,
        }, headers=PAYMENT_HEADERS)

    task = db.query(TaskModel).first()
    assert task.publisher_id == "pub-def"
    assert task.bounty == 0.5
    assert task.payment_tx_hash == "0xtest"
    assert task.payout_status.value == "pending"
    assert task.payout_tx_hash is None
    assert task.payout_amount is None
