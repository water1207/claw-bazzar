"""
End-to-end flow tests covering the full lifecycle of both task types.
Oracle is mocked to avoid subprocess calls.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_fastest_first_full_lifecycle(client):
    # 1. Publish task
    task = client.post("/tasks", json={
        "title": "Fastest wins", "description": "Solve it fast",
        "type": "fastest_first", "threshold": 0.8, "deadline": future(),
        "publisher_id": "test-pub", "bounty": 1.0,
    }).json()
    assert task["status"] == "open"

    # 2. Worker A submits (oracle mocked — score will be applied via internal endpoint)
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
    task = client.post("/tasks", json={
        "title": "Quality wins", "description": "Refine your answer",
        "type": "quality_first", "max_revisions": 3, "deadline": future(),
        "publisher_id": "test-pub", "bounty": 1.0,
    }).json()

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
    from app.scheduler import settle_expired_quality_first
    from app.database import get_db
    from app.main import app

    # Get the test db session via dependency override
    db = next(app.dependency_overrides[get_db]())

    # Force deadline to past
    from app.models import Task as TaskModel
    t = db.query(TaskModel).filter(TaskModel.id == task["id"]).first()
    t.deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    settle_expired_quality_first(db=db)

    task_detail = client.get(f"/tasks/{task['id']}").json()
    assert task_detail["status"] == "closed"
    assert task_detail["winner_submission_id"] == r2["id"]


def test_filter_tasks_by_status(client):
    with patch("app.routers.submissions.invoke_oracle"):
        t1 = client.post("/tasks", json={
            "title": "Open", "description": "d",
            "type": "fastest_first", "threshold": 0.5, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
        }).json()
        sub = client.post(f"/tasks/{t1['id']}/submissions", json={
            "worker_id": "w", "content": "x"
        }).json()

    client.post(f"/internal/submissions/{sub['id']}/score", json={"score": 0.9})

    client.post("/tasks", json={
        "title": "Still open", "description": "d",
        "type": "fastest_first", "threshold": 0.5, "deadline": future(),
        "publisher_id": "test-pub", "bounty": 1.0,
    })

    open_tasks = client.get("/tasks?status=open").json()
    closed_tasks = client.get("/tasks?status=closed").json()
    assert len(open_tasks) == 1
    assert len(closed_tasks) == 1
