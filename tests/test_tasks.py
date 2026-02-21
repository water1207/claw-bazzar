from datetime import datetime, timedelta, timezone


def future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def test_create_task(client):
    resp = client.post("/tasks", json={
        "title": "Write haiku",
        "description": "Write a haiku about the sea",
        "type": "fastest_first",
        "threshold": 0.8,
        "deadline": future(),
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Write haiku"
    assert data["status"] == "open"
    assert data["id"] is not None


def test_list_tasks(client):
    client.post("/tasks", json={
        "title": "T1", "description": "d", "type": "fastest_first",
        "threshold": 0.5, "deadline": future()
    })
    client.post("/tasks", json={
        "title": "T2", "description": "d", "type": "quality_first",
        "max_revisions": 3, "deadline": future()
    })
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_tasks_filter_by_type(client):
    client.post("/tasks", json={
        "title": "T1", "description": "d", "type": "fastest_first",
        "threshold": 0.5, "deadline": future()
    })
    client.post("/tasks", json={
        "title": "T2", "description": "d", "type": "quality_first",
        "max_revisions": 3, "deadline": future()
    })
    resp = client.get("/tasks?type=fastest_first")
    assert len(resp.json()) == 1
    assert resp.json()[0]["type"] == "fastest_first"


def test_get_task_not_found(client):
    resp = client.get("/tasks/nonexistent")
    assert resp.status_code == 404


def test_get_task_detail(client):
    create_resp = client.post("/tasks", json={
        "title": "T1", "description": "d", "type": "fastest_first",
        "threshold": 0.5, "deadline": future()
    })
    task_id = create_resp.json()["id"]
    resp = client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["submissions"] == []
