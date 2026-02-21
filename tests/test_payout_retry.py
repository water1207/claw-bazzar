from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def test_retry_payout_for_failed_task(client):
    # Create task and close it manually
    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xtest"}):
        task = client.post("/tasks", json={
            "title": "T", "description": "d", "type": "fastest_first",
            "threshold": 0.5, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 10.0,
        }, headers={"X-PAYMENT": "test"}).json()

    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "answer"
        }).json()

    # Score above threshold to close task — mock payout to fail
    with patch("app.routers.internal.pay_winner") as mock_pay:
        mock_pay.return_value = None  # payout handled separately
        client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})

    # Manually set payout_status to failed via DB
    from app.database import get_db
    from app.main import app
    from app.models import Task as TaskModel, PayoutStatus
    db = next(app.dependency_overrides[get_db]())
    t = db.query(TaskModel).filter(TaskModel.id == task["id"]).first()
    t.payout_status = PayoutStatus.failed
    db.commit()

    # Retry payout
    with patch("app.routers.internal.pay_winner") as mock_retry:
        resp = client.post(f"/internal/tasks/{task['id']}/payout")
    assert resp.status_code == 200
    mock_retry.assert_called_once()


def test_retry_payout_rejects_already_paid(client):
    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xtest"}):
        task = client.post("/tasks", json={
            "title": "T", "description": "d", "type": "fastest_first",
            "threshold": 0.5, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 10.0,
        }, headers={"X-PAYMENT": "test"}).json()

    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "answer"
        }).json()

    with patch("app.routers.internal.pay_winner"):
        client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})

    # Set payout_status to paid
    from app.database import get_db
    from app.main import app
    from app.models import Task as TaskModel, PayoutStatus
    db = next(app.dependency_overrides[get_db]())
    t = db.query(TaskModel).filter(TaskModel.id == task["id"]).first()
    t.payout_status = PayoutStatus.paid
    db.commit()

    resp = client.post(f"/internal/tasks/{task['id']}/payout")
    assert resp.status_code == 400
    assert "already paid" in resp.json()["detail"].lower()


def test_retry_payout_not_found(client):
    resp = client.post("/internal/tasks/nonexistent/payout")
    assert resp.status_code == 404
