"""
End-to-end flow tests covering the full lifecycle of both task types.
Oracle is mocked to avoid subprocess calls.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_fastest_first_full_lifecycle(client):
    # 1. Publish task
    with PAYMENT_MOCK:
        task = client.post("/tasks", json={
            "title": "Fastest wins", "description": "Solve it fast",
            "type": "fastest_first", "threshold": 0.8, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
        }, headers=PAYMENT_HEADERS).json()
    assert task["status"] == "open"

    # 2. Worker A submits (oracle mocked -- score will be applied via internal endpoint)
    with patch("app.routers.submissions.invoke_oracle"):
        sub_a = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "agent-A", "content": "My answer"
        }).json()
    assert sub_a["status"] == "pending"

    # 3. Worker B submits
    with patch("app.routers.submissions.invoke_oracle"):
        sub_b = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "agent-B", "content": "Another answer"
        }).json()

    # 4. Score sub_a below threshold -> task stays open
    client.post(f"/internal/submissions/{sub_a['id']}/score", json={"score": 0.5})
    assert client.get(f"/tasks/{task['id']}").json()["status"] == "open"

    # 5. Score sub_b above threshold -> task closes
    client.post(f"/internal/submissions/{sub_b['id']}/score", json={"score": 0.95, "feedback": "Perfect"})
    task_detail = client.get(f"/tasks/{task['id']}").json()
    assert task_detail["status"] == "closed"
    assert task_detail["winner_submission_id"] == sub_b["id"]


def test_quality_first_full_lifecycle(client):
    # 1. Publish quality_first task
    with PAYMENT_MOCK:
        task = client.post("/tasks", json={
            "title": "Quality wins", "description": "Refine your answer",
            "type": "quality_first", "max_revisions": 3, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
        }, headers=PAYMENT_HEADERS).json()

    # 2. Worker submits revision 1
    with patch("app.routers.submissions.invoke_oracle"):
        r1 = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "agent-X", "content": "Draft 1"
        }).json()
    assert r1["revision"] == 1

    # 3. Worker refines with revision 2
    with patch("app.routers.submissions.invoke_oracle"):
        r2 = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "agent-X", "content": "Better draft"
        }).json()
    assert r2["revision"] == 2

    # 4. Score both
    client.post(f"/internal/submissions/{r1['id']}/score", json={"score": 0.6})
    client.post(f"/internal/submissions/{r2['id']}/score", json={"score": 0.85})

    # 5. Manually trigger scheduler settlement (simulates deadline passing)
    from app.scheduler import quality_first_lifecycle
    from app.database import get_db
    from app.main import app

    # Get the test db session via dependency override
    db = next(app.dependency_overrides[get_db]())

    # Force deadline to past
    from app.models import Task as TaskModel
    t = db.query(TaskModel).filter(TaskModel.id == task["id"]).first()
    t.deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    # Phase 1: open → scoring
    quality_first_lifecycle(db=db)
    # Phase 2: scoring → challenge_window
    quality_first_lifecycle(db=db)

    # Expire challenge window
    db.refresh(t)
    t.challenge_window_end = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    # Phase 3: challenge_window → closed (no challenges)
    quality_first_lifecycle(db=db)

    task_detail = client.get(f"/tasks/{task['id']}").json()
    assert task_detail["status"] == "closed"
    assert task_detail["winner_submission_id"] == r2["id"]


def test_filter_tasks_by_status(client):
    with PAYMENT_MOCK:
        with patch("app.routers.submissions.invoke_oracle"):
            t1 = client.post("/tasks", json={
                "title": "Open", "description": "d",
                "type": "fastest_first", "threshold": 0.5, "deadline": future(),
                "publisher_id": "test-pub", "bounty": 1.0,
            }, headers=PAYMENT_HEADERS).json()
            sub = client.post(f"/tasks/{t1['id']}/submissions", json={
                "worker_id": "w", "content": "x"
            }).json()

    client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})

    with PAYMENT_MOCK:
        client.post("/tasks", json={
            "title": "Still open", "description": "d",
            "type": "fastest_first", "threshold": 0.5, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
        }, headers=PAYMENT_HEADERS)

    open_tasks = client.get("/tasks?status=open").json()
    closed_tasks = client.get("/tasks?status=closed").json()
    assert len(open_tasks) == 1
    assert len(closed_tasks) == 1


def test_bounty_lifecycle_fastest_first(client):
    """Full flow: register -> publish (with payment) -> submit -> score -> payout."""
    # 1. Register publisher and worker
    pub = client.post("/users", json={
        "nickname": "pub-int", "wallet": "0xPUB", "role": "publisher"
    }).json()
    worker = client.post("/users", json={
        "nickname": "worker-int", "wallet": "0xWORKER", "role": "worker"
    }).json()

    # 2. Publish task with bounty (mock x402 payment)
    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xPAYMENT"}):
        task = client.post("/tasks", json={
            "title": "Bounty task", "description": "Do it",
            "type": "fastest_first", "threshold": 0.7,
            "deadline": future(), "publisher_id": pub["id"], "bounty": 10.0,
        }, headers={"X-PAYMENT": "valid"}).json()

    assert task["bounty"] == 10.0
    assert task["payment_tx_hash"] == "0xPAYMENT"
    assert task["payout_status"] == "pending"

    # 3. Worker submits
    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": worker["id"], "content": "my answer"
        }).json()

    # 4. Score above threshold -> triggers payout
    with patch("app.services.payout._send_usdc_transfer", return_value="0xPAYOUT") as mock_tx:
        client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})
        mock_tx.assert_called_once_with("0xWORKER", 8.0)  # 10.0 * 0.80

    # 5. Verify final state
    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["status"] == "closed"
    assert detail["winner_submission_id"] == sub["id"]
    assert detail["payout_status"] == "paid"
    assert detail["payout_amount"] == 8.0
    assert detail["payout_tx_hash"] == "0xPAYOUT"


def test_bounty_lifecycle_quality_first(client):
    """Full flow: quality_first with deadline settlement and payout."""
    pub = client.post("/users", json={
        "nickname": "pub-q", "wallet": "0xPUBQ", "role": "publisher"
    }).json()
    worker = client.post("/users", json={
        "nickname": "worker-q", "wallet": "0xWORKERQ", "role": "worker"
    }).json()

    with patch("app.routers.tasks.verify_payment",
               return_value={"valid": True, "tx_hash": "0xPAY"}):
        task = client.post("/tasks", json={
            "title": "Quality bounty", "description": "Refine",
            "type": "quality_first", "max_revisions": 3,
            "deadline": future(), "publisher_id": pub["id"], "bounty": 20.0,
        }, headers={"X-PAYMENT": "valid"}).json()

    with patch("app.routers.submissions.invoke_oracle"):
        r1 = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": worker["id"], "content": "draft 1"
        }).json()
        r2 = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": worker["id"], "content": "draft 2"
        }).json()

    client.post(f"/internal/submissions/{r1['id']}/score", json={"score": 0.5})
    client.post(f"/internal/submissions/{r2['id']}/score", json={"score": 0.9})

    # Force deadline to past and settle through multi-phase lifecycle
    from app.database import get_db
    from app.main import app
    from app.models import Task as TaskModel
    from app.scheduler import quality_first_lifecycle
    db = next(app.dependency_overrides[get_db]())
    t = db.query(TaskModel).filter(TaskModel.id == task["id"]).first()
    t.deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    # Phase 1: open → scoring
    quality_first_lifecycle(db=db)
    # Phase 2: scoring → challenge_window
    quality_first_lifecycle(db=db)

    # Expire challenge window
    db.refresh(t)
    t.challenge_window_end = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    # Phase 3: challenge_window → closed (with escrow settlement)
    with patch("app.scheduler.resolve_challenge_onchain", return_value="0xQPAYOUT") as mock_resolve:
        quality_first_lifecycle(db=db)
        mock_resolve.assert_called_once()

    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["status"] == "closed"
    assert detail["payout_status"] == "paid"
    assert detail["payout_amount"] == 16.0  # 20.0 * 0.80
