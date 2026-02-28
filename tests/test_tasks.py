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
            "acceptance_criteria": ["验收标准"],
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
            "acceptance_criteria": ["验收标准"],
        }, headers=PAYMENT_HEADERS)
        client.post("/tasks", json={
            "title": "T2", "description": "d", "type": "quality_first",
            "max_revisions": 3, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
            "acceptance_criteria": ["验收标准"],
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
            "acceptance_criteria": ["验收标准"],
        }, headers=PAYMENT_HEADERS)
        client.post("/tasks", json={
            "title": "T2", "description": "d", "type": "quality_first",
            "max_revisions": 3, "deadline": future(),
            "publisher_id": "test-pub", "bounty": 1.0,
            "acceptance_criteria": ["验收标准"],
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
            "acceptance_criteria": ["验收标准"],
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
        "acceptance_criteria": ["验收标准"],
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
            "acceptance_criteria": ["验收标准"],
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
            "acceptance_criteria": ["验收标准"],
        }, headers={"X-PAYMENT": "invalid-payment"})
    assert resp.status_code == 402



def test_submission_status_has_policy_violation():
    from app.models import SubmissionStatus
    assert SubmissionStatus.policy_violation == "policy_violation"


def test_task_create_requires_acceptance_criteria_list(client):
    """acceptance_criteria 必须是列表，不能是字符串"""
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "t", "description": "d", "type": "fastest_first",
            "threshold": 0.6, "deadline": future(),
            "publisher_id": "pub", "bounty": 1.0,
            "acceptance_criteria": "纯字符串不行",
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 422

def test_task_create_requires_nonempty_criteria(client):
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "t", "description": "d", "type": "fastest_first",
            "threshold": 0.6, "deadline": future(),
            "publisher_id": "pub", "bounty": 1.0,
            "acceptance_criteria": [],
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 422

def test_task_create_bounty_minimum(client):
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "t", "description": "d", "type": "fastest_first",
            "threshold": 0.6, "deadline": future(),
            "publisher_id": "pub", "bounty": 0.05,
            "acceptance_criteria": ["条目1"],
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 422

def test_task_out_no_challenge_window_end(client):
    """TaskOut 不再暴露 challenge_window_end"""
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "t", "description": "d", "type": "quality_first",
            "deadline": future(), "publisher_id": "pub", "bounty": 1.0,
            "acceptance_criteria": ["条目1"],
            "challenge_duration": 3600,
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 201
    assert "challenge_window_end" not in resp.json()

def test_task_acceptance_criteria_roundtrip(client):
    """acceptance_criteria 以 list[str] 写入后读出保持一致"""
    criteria = ["至少5个产品", "每个含官网", "信息真实"]
    with PAYMENT_MOCK:
        resp = client.post("/tasks", json={
            "title": "t", "description": "d", "type": "quality_first",
            "deadline": future(), "publisher_id": "pub", "bounty": 1.0,
            "acceptance_criteria": criteria,
        }, headers=PAYMENT_HEADERS)
    assert resp.status_code == 201
    assert resp.json()["acceptance_criteria"] == criteria


def test_policy_violation_worker_cannot_resubmit(client_with_db):
    from unittest.mock import patch
    from app.models import SubmissionStatus, Submission

    client, db = client_with_db

    # 创建任务
    with PAYMENT_MOCK:
        task_resp = client.post("/tasks", json={
            "title": "test injection ban",
            "description": "desc",
            "type": "quality_first",
            "deadline": "2099-01-01T00:00:00Z",
            "publisher_id": "pub1",
            "bounty": 0.1,
            "acceptance_criteria": ["验收标准"],
        }, headers=PAYMENT_HEADERS)
    assert task_resp.status_code == 201
    task_id = task_resp.json()["id"]

    # 第一次提交（mock oracle 不实际调用）
    with patch("app.routers.submissions.invoke_oracle"):
        sub_resp = client.post(
            f"/tasks/{task_id}/submissions",
            json={"worker_id": "bad_worker", "content": "inject attempt"},
        )
    assert sub_resp.status_code == 201
    sub_id = sub_resp.json()["id"]

    # 手动将该提交标记为 policy_violation（共享同一 in-memory DB）
    sub = db.query(Submission).filter_by(id=sub_id).first()
    sub.status = SubmissionStatus.policy_violation
    db.commit()

    # 第二次提交应被 403 拒绝
    with patch("app.routers.submissions.invoke_oracle"):
        resp2 = client.post(
            f"/tasks/{task_id}/submissions",
            json={"worker_id": "bad_worker", "content": "another attempt"},
        )
    assert resp2.status_code == 403
    assert "违规" in resp2.json()["detail"]


def test_content_visible_during_arbitrating(client_with_db):
    """During arbitrating, all submission content should be visible."""
    from app.models import Task, Submission, TaskStatus, SubmissionStatus

    client, db = client_with_db
    task = Task(
        title="t", description="d", type="quality_first",
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
        publisher_id="pub", bounty=1.0,
        acceptance_criteria='["c1"]',
        status=TaskStatus.arbitrating,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    sub1 = Submission(task_id=task.id, worker_id="w1", content="winner content", status=SubmissionStatus.scored)
    sub2 = Submission(task_id=task.id, worker_id="w2", content="challenger content", status=SubmissionStatus.scored)
    db.add_all([sub1, sub2])
    db.commit()
    db.refresh(sub1)

    task.winner_submission_id = sub1.id
    db.commit()

    resp = client.get(f"/tasks/{task.id}")
    assert resp.status_code == 200
    subs = resp.json()["submissions"]
    for s in subs:
        assert s["content"] != "[hidden]"
    assert any(s["content"] == "winner content" for s in subs)
    assert any(s["content"] == "challenger content" for s in subs)


def test_content_hidden_during_challenge_window(client_with_db):
    """During challenge_window, non-winner content should still be hidden."""
    from app.models import Task, Submission, TaskStatus, SubmissionStatus

    client, db = client_with_db
    task = Task(
        title="t", description="d", type="quality_first",
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
        publisher_id="pub", bounty=1.0,
        acceptance_criteria='["c1"]',
        status=TaskStatus.challenge_window,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    sub1 = Submission(task_id=task.id, worker_id="w1", content="winner content", status=SubmissionStatus.scored)
    sub2 = Submission(task_id=task.id, worker_id="w2", content="challenger content", status=SubmissionStatus.scored)
    db.add_all([sub1, sub2])
    db.commit()
    db.refresh(sub1)

    task.winner_submission_id = sub1.id
    db.commit()

    resp = client.get(f"/tasks/{task.id}")
    assert resp.status_code == 200
    subs = resp.json()["submissions"]
    winner_sub = next(s for s in subs if s["id"] == sub1.id)
    loser_sub = next(s for s in subs if s["id"] == sub2.id)
    assert winner_sub["content"] == "winner content"
    assert loser_sub["content"] == "[hidden]"


def test_task_detail_includes_full_scoring_dimensions(client_with_db):
    """scoring_dimensions should include dim_id, dim_type, weight, scoring_guidance."""
    from app.models import Task, ScoringDimension

    client, db = client_with_db
    task = Task(
        title="t", description="d", type="quality_first",
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
        publisher_id="pub", bounty=1.0,
        acceptance_criteria='["c1"]',
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    dim = ScoringDimension(
        task_id=task.id,
        dim_id="substantiveness",
        name="Substantiveness",
        dim_type="fixed",
        description="Content depth",
        weight=0.3,
        scoring_guidance="Evaluate depth of analysis",
    )
    db.add(dim)
    db.commit()

    resp = client.get(f"/tasks/{task.id}")
    assert resp.status_code == 200
    dims = resp.json()["scoring_dimensions"]
    assert len(dims) == 1
    assert dims[0]["dim_id"] == "substantiveness"
    assert dims[0]["dim_type"] == "fixed"
    assert dims[0]["weight"] == 0.3
    assert dims[0]["scoring_guidance"] == "Evaluate depth of analysis"
    assert dims[0]["name"] == "Substantiveness"
    assert dims[0]["description"] == "Content depth"
