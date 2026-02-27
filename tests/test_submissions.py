from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PAYMENT_MOCK = patch(
    "app.routers.tasks.verify_payment",
    return_value={"valid": True, "tx_hash": "0xtest"},
)
PAYMENT_HEADERS = {"X-PAYMENT": "test"}


def future(hours=1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def past() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def make_task(client, type="fastest_first", threshold=0.8, max_revisions=None):
    body = {"title": "T", "description": "d", "type": type,
            "threshold": threshold, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
            "acceptance_criteria": ["验收标准"]}
    if max_revisions:
        body["max_revisions"] = max_revisions
    with PAYMENT_MOCK:
        return client.post("/tasks", json=body,
                           headers=PAYMENT_HEADERS).json()


def test_submit_to_open_task(client):
    task = make_task(client)
    with patch("app.routers.submissions.invoke_oracle"):
        resp = client.post(f"/tasks/{task['id']}/submissions", json={
            "worker_id": "w1", "content": "my answer"
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["revision"] == 1
    assert data["status"] == "pending"
    assert data["worker_id"] == "w1"


def test_fastest_first_only_one_submission_per_worker(client):
    task = make_task(client, type="fastest_first")
    with patch("app.routers.submissions.invoke_oracle"):
        client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "a"})
        resp = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "b"})
    assert resp.status_code == 400
    assert "Already submitted" in resp.json()["detail"]


def test_quality_first_multiple_revisions(client):
    task = make_task(client, type="quality_first", max_revisions=3)
    with patch("app.routers.submissions.invoke_oracle"):
        r1 = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "v1"})
        r2 = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "v2"})
        r3 = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "v3"})
        r4 = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "v4"})
    assert r1.status_code == 201
    assert r2.json()["revision"] == 2
    assert r3.json()["revision"] == 3
    assert r4.status_code == 400
    assert "Max revisions" in r4.json()["detail"]


def test_submit_to_nonexistent_task(client):
    resp = client.post("/tasks/bad-id/submissions", json={"worker_id": "w1", "content": "x"})
    assert resp.status_code == 404


def test_submit_to_closed_task(client):
    task = make_task(client)
    # Manually close task via internal endpoint after scoring above threshold
    with patch("app.routers.submissions.invoke_oracle"):
        client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "a"})

    # Close via internal score endpoint
    sub_resp = client.get(f"/tasks/{task['id']}/submissions")
    sub_id = sub_resp.json()[0]["id"]
    client.post(f"/internal/submissions/{sub_id}/score", json={"score": 0.95, "feedback": "great"})

    # Task should now be closed
    task_resp = client.get(f"/tasks/{task['id']}")
    assert task_resp.json()["status"] == "closed"

    # Submitting to closed task should fail
    resp = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w2", "content": "late"})
    assert resp.status_code == 400
    assert "closed" in resp.json()["detail"]


def test_list_submissions(client):
    task = make_task(client)
    with patch("app.routers.submissions.invoke_oracle"):
        client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "a"})
        client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w2", "content": "b"})
    resp = client.get(f"/tasks/{task['id']}/submissions")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_single_submission(client):
    task = make_task(client)
    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "a"}).json()
    resp = client.get(f"/tasks/{task['id']}/submissions/{sub['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sub["id"]


def make_quality_task(client):
    body = {"title": "T", "description": "d", "type": "quality_first",
            "max_revisions": 3, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
            "acceptance_criteria": ["验收标准"]}
    with PAYMENT_MOCK:
        return client.post("/tasks", json=body, headers=PAYMENT_HEADERS).json()


def test_quality_first_score_hidden_when_open(client):
    task = make_quality_task(client)
    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions",
                          json={"worker_id": "w1", "content": "a"}).json()

    # Manually set score in DB to simulate oracle having run
    from app.database import get_db
    db = next(client.app.dependency_overrides[get_db]())
    from app.models import Submission
    s = db.query(Submission).filter(Submission.id == sub["id"]).first()
    s.score = 0.88
    db.commit()

    resp = client.get(f"/tasks/{task['id']}/submissions/{sub['id']}")
    assert resp.status_code == 200
    assert resp.json()["score"] is None  # hidden because task is open


def test_fastest_first_score_always_visible(client):
    task = make_task(client, type="fastest_first")
    with patch("app.routers.submissions.invoke_oracle"):
        sub = client.post(f"/tasks/{task['id']}/submissions",
                          json={"worker_id": "w1", "content": "a"}).json()

    from app.database import get_db
    db = next(client.app.dependency_overrides[get_db]())
    from app.models import Submission
    s = db.query(Submission).filter(Submission.id == sub["id"]).first()
    s.score = 0.88
    db.commit()

    resp = client.get(f"/tasks/{task['id']}/submissions/{sub['id']}")
    assert resp.status_code == 200
    assert resp.json()["score"] == 0.88  # always visible for fastest_first


def test_submit_after_deadline(client):
    body = {"title": "T", "description": "d", "type": "fastest_first",
            "threshold": 0.8, "deadline": past(),
            "publisher_id": "test-pub", "bounty": 1.0,
            "acceptance_criteria": ["验收标准"]}
    with PAYMENT_MOCK:
        task = client.post("/tasks", json=body,
                           headers=PAYMENT_HEADERS).json()
    resp = client.post(f"/tasks/{task['id']}/submissions", json={"worker_id": "w1", "content": "late"})
    assert resp.status_code == 400
    assert "deadline" in resp.json()["detail"]
